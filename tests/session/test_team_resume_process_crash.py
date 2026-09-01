from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from codeteam.agent_team.dag import TaskStatus
from codeteam.agent_team.models import AgentStatus
from codeteam.agent_team.persistence_models import TEAM_STATE_SCHEMA_VERSION
from codeteam.agent_team.session_integration import TeamSessionRuntimeBuilder
from codeteam.agent_team.team_store import SQLiteTeamStateStore
from codeteam.session.errors import SessionRecoveryRequiredError
from codeteam.session.models import SessionStatus, TeamStateRef
from codeteam.session.service import SessionService
from codeteam.session.store import JsonSessionStore
from tests.agent_team.team_state_helpers import team_snapshot

from .conftest import init_git_repo, make_session, make_worktree_ref

TIMEOUT = 10.0


def test_process_exit_after_team_commit_is_reconciled_on_next_resume(
    tmp_path: Path,
) -> None:
    repo = init_git_repo(tmp_path / "repo")
    store = JsonSessionStore(tmp_path / "sessions")
    session = make_session(
        repo,
        session_id="ses_team_test",
        status=SessionStatus.RUNNING,
        worktree=make_worktree_ref(repo),
        team_state=TeamStateRef(
            schema_version=TEAM_STATE_SCHEMA_VERSION,
            acknowledged_revision=1,
        ),
    )
    store.create(session)
    team_store = SQLiteTeamStateStore(store.session_dir(session.manifest.session_id))
    team_store.initialize(team_snapshot(session_id=session.manifest.session_id))

    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.agent_team.team_process_helper",
            "commit-then-exit",
            str(store.session_dir(session.manifest.session_id)),
            session.manifest.session_id,
        ],
        capture_output=True,
        text=True,
        shell=False,
        timeout=TIMEOUT,
        check=False,
    )

    assert process.returncode == 92
    assert json.loads(process.stdout) == {"revision": 2, "status": "team_committed"}
    assert store.load(session.manifest.session_id).team_state == session.team_state

    service = SessionService(store, runtime_builder=TeamSessionRuntimeBuilder())
    outcome = service.resume(session.manifest.session_id, current_repo=repo)
    assert outcome.session.team_state is not None
    assert outcome.session.team_state.acknowledged_revision == 3
    events, _ = store.load_events(session.manifest.session_id)
    assert events[-1].payload["team_revision_gap_reconciled"] == 1
    service.pause(outcome.session, reason="test cleanup")


def test_running_task_with_crashed_git_side_effect_fails_closed(
    tmp_path: Path,
) -> None:
    repo = init_git_repo(tmp_path / "repo")
    store = JsonSessionStore(tmp_path / "sessions")
    session = make_session(
        repo,
        session_id="ses_team_test",
        status=SessionStatus.RUNNING,
        worktree=make_worktree_ref(repo),
        team_state=TeamStateRef(
            schema_version=TEAM_STATE_SCHEMA_VERSION,
            acknowledged_revision=1,
        ),
    )
    store.create(session)
    snapshot = team_snapshot(session_id=session.manifest.session_id)
    running = snapshot.model_copy(
        update={
            "ready_queue": (),
            "tasks": {
                "A": snapshot.tasks["A"].model_copy(
                    update={
                        "status": TaskStatus.RUNNING,
                        "owner_id": "worker-1",
                        "owner_generation": 2,
                        "attempt": 1,
                        "claimed_at": 1.0,
                    }
                ),
                "B": snapshot.tasks["B"],
            },
            "workers": {
                "worker-1": snapshot.workers["worker-1"].model_copy(
                    update={"status": AgentStatus.BUSY}
                )
            },
            "worker_ownership": {"worker-1": "A"},
        }
    )
    SQLiteTeamStateStore(store.session_dir(session.manifest.session_id)).initialize(
        running
    )

    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.agent_team.team_process_helper",
            "dirty-worktree-then-exit",
            str(repo),
        ],
        capture_output=True,
        text=True,
        shell=False,
        timeout=TIMEOUT,
        check=False,
    )
    assert process.returncode == 93
    assert json.loads(process.stdout)["status"] == "workspace_mutated"

    service = SessionService(store, runtime_builder=TeamSessionRuntimeBuilder())
    with pytest.raises(SessionRecoveryRequiredError, match="worktree_dirty_drift"):
        service.resume(session.manifest.session_id, current_repo=repo)
    assert store.load(session.manifest.session_id).status is SessionStatus.RECOVERY_REQUIRED
    assert not (store.session_dir(session.manifest.session_id) / "writer.lock").exists()
