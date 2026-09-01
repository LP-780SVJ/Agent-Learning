from __future__ import annotations

import json
import selectors
import subprocess
import sys
from pathlib import Path

from codeteam.agent_team.persistence_models import TEAM_STATE_SCHEMA_VERSION
from codeteam.agent_team.team_store import SQLiteTeamStateStore
from codeteam.session.models import SessionStatus, TeamStateRef
from codeteam.session.store import JsonSessionStore
from tests.agent_team.team_state_helpers import team_snapshot

from .conftest import init_git_repo, make_session, make_worktree_ref

TIMEOUT = 10.0


def _setup(tmp_path: Path):
    repo = init_git_repo(tmp_path / "repo")
    sessions_root = tmp_path / "sessions"
    store = JsonSessionStore(sessions_root)
    session = make_session(
        repo,
        session_id="ses_team_test",
        status=SessionStatus.PAUSED,
        worktree=make_worktree_ref(repo),
        team_state=TeamStateRef(
            schema_version=TEAM_STATE_SCHEMA_VERSION,
            acknowledged_revision=1,
        ),
    )
    store.create(session)
    SQLiteTeamStateStore(store.session_dir(session.manifest.session_id)).initialize(
        team_snapshot(session_id=session.manifest.session_id)
    )
    return repo, sessions_root, store, session


def _start_holder(repo: Path, sessions_root: Path, session_id: str):
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.agent_team.team_process_helper",
            "resume-hold",
            str(sessions_root),
            str(repo),
            session_id,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )


def _readline_with_timeout(process: subprocess.Popen[str]) -> str:
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        ready = selector.select(timeout=TIMEOUT)
        assert ready, "resume process did not publish readiness before timeout"
        return process.stdout.readline()
    finally:
        selector.close()


def test_two_processes_cannot_both_resume_one_session(tmp_path: Path) -> None:
    repo, sessions_root, store, session = _setup(tmp_path)
    first = _start_holder(repo, sessions_root, session.manifest.session_id)
    first_line = _readline_with_timeout(first)
    first_result = json.loads(first_line)
    assert first_result["status"] == "resumed"

    second = _start_holder(repo, sessions_root, session.manifest.session_id)
    second_stdout, second_stderr = second.communicate(input="pause\n", timeout=TIMEOUT)
    assert second.returncode == 7
    assert json.loads(second_stdout)["status"] == "already_active"
    assert "Traceback" not in second_stderr

    assert first.stdin is not None
    first.stdin.write("pause\n")
    first.stdin.flush()
    first_stdout, first_stderr = first.communicate(timeout=TIMEOUT)
    assert first.returncode == 0
    assert json.loads(first_stdout)["status"] == "paused"
    assert "Traceback" not in first_stderr
    assert store.load(session.manifest.session_id).status is SessionStatus.PAUSED
    assert not (store.session_dir(session.manifest.session_id) / "writer.lock").exists()
