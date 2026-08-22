from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from codeteam.cli.app import app
from codeteam.git.checkpoint import CheckpointManager
from codeteam.git.models import CheckpointReason
from codeteam.session.models import RepositoryRef, Session, SessionStatus
from codeteam.session.service import SessionService
from codeteam.session.store import JsonSessionStore
from codeteam.task.models import create_task_spec

runner = CliRunner()


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        shell=False,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init")
    _run_git(repo, "config", "user.name", "CodeTeam Test")
    _run_git(repo, "config", "user.email", "codeteam@example.com")
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    _run_git(repo, "add", "app.py")
    _run_git(repo, "commit", "-m", "init")
    return repo


def _git_common_dir(repo: Path) -> Path:
    return (repo / _run_git(repo, "rev-parse", "--git-common-dir")).resolve()


def _session_store(repo: Path) -> JsonSessionStore:
    return JsonSessionStore(_git_common_dir(repo) / "codeteam" / "sessions")


def _checkpoint_state_root(repo: Path) -> Path:
    return repo.resolve().parent / ".codeteam" / "checkpoints" / repo.name


def _create_session(
    repo: Path,
    *,
    task_id: str = "task-cli",
    status: SessionStatus = SessionStatus.CREATED,
) -> tuple[JsonSessionStore, Session]:
    store = _session_store(repo)
    service = SessionService(store)
    session = service.create_session(
        task=create_task_spec(
            task_id=task_id,
            original_request="CLI integration task",
        ),
        repo=RepositoryRef(
            repo_id=str(repo.resolve()),
            git_common_dir=str(_git_common_dir(repo)),
            base_sha=_run_git(repo, "rev-parse", "HEAD"),
        ),
        provider_id="mock",
        model_id="mock-model",
    )
    if status is not SessionStatus.CREATED:
        session = store.save(session.model_copy(update={"status": status}))
    return store, session


def _git_status(repo: Path) -> str:
    return _run_git(repo, "status", "--porcelain=v1")


def test_diff_is_read_only_and_does_not_mutate_repo_state(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _, session = _create_session(repo)
    (repo / "app.py").write_text("value = 2\n", encoding="utf-8")
    (repo / "scratch.txt").write_text("scratch\n", encoding="utf-8")
    before = _git_status(repo)

    result = runner.invoke(
        app,
        ["diff", session.manifest.session_id, "--repo", str(repo)],
    )

    assert result.exit_code == 0
    assert _git_status(repo) == before
    assert "scratch.txt" in result.stdout
    assert ".codeteam/sessions" not in result.stdout
    assert result.stderr == ""


def test_no_change_diff_exits_zero(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _, session = _create_session(repo)

    result = runner.invoke(
        app,
        ["diff", session.manifest.session_id, "--repo", str(repo)],
    )

    assert result.exit_code == 0
    assert "No tracked diff." in result.stdout


def test_diff_json_output_is_valid_and_stable(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _, session = _create_session(repo)
    (repo / "app.py").write_text("value = 3\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "diff",
            session.manifest.session_id,
            "--repo",
            str(repo),
            "--format",
            "json",
        ],
    )

    payload = json.loads(result.stdout)
    assert result.exit_code == 0
    assert payload["session_id"] == session.manifest.session_id
    assert payload["base_ref"] == "HEAD"
    assert payload["additions"] == 1
    assert payload["deletions"] == 1
    assert isinstance(payload["changes"], list)
    assert "patch" in payload


def test_resume_missing_session_exits_2_and_does_not_create_session(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)

    result = runner.invoke(app, ["resume", "ses_missing", "--repo", str(repo)])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "session 不存在" in result.stderr
    assert not (_session_store(repo).session_dir("ses_missing") / "session.json").exists()


def test_resume_completed_session_rejects_without_rerun(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _, session = _create_session(repo, status=SessionStatus.COMPLETED)

    result = runner.invoke(
        app,
        ["resume", session.manifest.session_id, "--repo", str(repo)],
    )

    assert result.exit_code == 2
    assert "cannot resume" in result.stderr
    assert "Session:" not in result.stdout


def test_resume_model_override_fails_closed_until_registry_is_wired(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _, session = _create_session(repo)

    result = runner.invoke(
        app,
        [
            "resume",
            session.manifest.session_id,
            "--repo",
            str(repo),
            "--provider",
            "mock",
            "--model",
            "mock-model",
        ],
    )

    assert result.exit_code == 2
    assert "Model override is not wired" in result.stderr


def test_rollback_rejects_checkpoint_not_owned_by_session(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    store, session = _create_session(repo)
    manager = CheckpointManager(
        workspace_root=repo,
        state_root=_checkpoint_state_root(repo),
        task_id=session.task.task_id,
    )
    checkpoint = manager.create(CheckpointReason.TASK_START)
    store.save(
        session.model_copy(
            update={
                "checkpoint_ids": ("cp-not-this-one",),
                "current_checkpoint_id": "cp-not-this-one",
            }
        )
    )

    result = runner.invoke(
        app,
        [
            "rollback",
            session.manifest.session_id,
            checkpoint.checkpoint_id,
            "--repo",
            str(repo),
        ],
    )

    assert result.exit_code == 2
    assert "不属于 session" in result.stderr


def test_rollback_success_restores_workspace(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    store, session = _create_session(repo)
    manager = CheckpointManager(
        workspace_root=repo,
        state_root=_checkpoint_state_root(repo),
        task_id=session.task.task_id,
    )
    checkpoint = manager.create(CheckpointReason.TASK_START)
    store.save(
        session.model_copy(
            update={
                "checkpoint_ids": (checkpoint.checkpoint_id,),
                "current_checkpoint_id": checkpoint.checkpoint_id,
            }
        )
    )
    (repo / "app.py").write_text("broken\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "rollback",
            session.manifest.session_id,
            checkpoint.checkpoint_id,
            "--repo",
            str(repo),
        ],
    )

    assert result.exit_code == 0
    assert "Rollback: success" in result.stdout
    assert "Safety checkpoint: cp-000001" in result.stdout
    assert (repo / "app.py").read_text(encoding="utf-8") == "value = 1\n"


def test_session_id_path_traversal_is_rejected(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    result = runner.invoke(app, ["diff", "../evil", "--repo", str(repo)])

    assert result.exit_code == 2
    assert "非法 session_id" in result.stderr
    assert "Traceback" not in result.stderr


def test_checkpoint_id_path_traversal_does_not_escape_checkpoint_store(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _, session = _create_session(repo)

    result = runner.invoke(
        app,
        ["rollback", session.manifest.session_id, "../evil", "--repo", str(repo)],
    )

    assert result.exit_code == 2
    assert "checkpoint 不存在" in result.stderr
    assert "Traceback" not in result.stderr
