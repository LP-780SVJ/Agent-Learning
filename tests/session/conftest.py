"""Shared fixtures for Week4 Day4 session persistence tests."""
from __future__ import annotations

import subprocess
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from codeteam.failures.models import (
    AgentErrorCode,
    AgentFailure,
    ErrorCategory,
    FailureStage,
    RecoveryAction,
)
from codeteam.session.models import (
    RepositoryRef,
    Session,
    SessionManifest,
    SessionStatus,
    WorktreeRef,
)
from codeteam.task.models import TaskSpec

GIT_TIMEOUT_SECONDS = 10.0


def run_git(repo: Path, args: Sequence[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        shell=False,
        timeout=GIT_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed: "
            f"{result.stderr.decode('utf-8', errors='replace')}"
        )
    return result.stdout.decode("utf-8", errors="replace").strip()


def init_git_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    run_git(root, ["init", "--quiet"])
    run_git(root, ["config", "--local", "user.name", "Test User"])
    run_git(root, ["config", "--local", "user.email", "t@example.com"])
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    run_git(root, ["add", "--all"])
    run_git(root, ["commit", "--quiet", "-m", "baseline"])
    return root


def commit_file(repo: Path, relative_path: str, content: str) -> str:
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    run_git(repo, ["add", "--all"])
    run_git(repo, ["commit", "--quiet", "-m", f"update {relative_path}"])
    return head_sha(repo)


def git_common_dir(repo: Path) -> str:
    raw = run_git(repo, ["rev-parse", "--git-common-dir"])
    return str((repo / raw).resolve())


def head_sha(repo: Path) -> str:
    return run_git(repo, ["rev-parse", "HEAD"])


def make_task(task_id: str = "task-1") -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        original_request="Fix the failing test",
        goal="Make the test pass",
        constraints=("Do not edit unrelated files",),
        acceptance_criteria=("pytest passes",),
    )


def make_repo_ref(
    repo_path: Path,
    *,
    repo_id: str = "repo-1",
    base_sha: str | None = None,
) -> RepositoryRef:
    sha = base_sha if base_sha is not None else head_sha(repo_path)
    return RepositoryRef(
        repo_id=repo_id,
        git_common_dir=git_common_dir(repo_path),
        base_sha=sha,
    )


def make_worktree_ref(
    repo_path: Path,
    *,
    task_id: str = "task-1",
    branch_name: str = "codeteam/task-1",
    last_known_dirty: bool = False,
    last_known_head_sha: str | None = None,
) -> WorktreeRef:
    sha = head_sha(repo_path)
    return WorktreeRef(
        task_id=task_id,
        branch_name=branch_name,
        path=str(repo_path),
        base_sha=sha,
        head_sha=sha,
        last_known_head_sha=last_known_head_sha or sha,
        last_known_dirty=last_known_dirty,
    )


def make_failure(*, source_message: str = "raw token sk-secret") -> AgentFailure:
    return AgentFailure(
        failure_id="fail-1",
        task_id="task-1",
        category=ErrorCategory.SESSION,
        code=AgentErrorCode.SESSION_CORRUPTED,
        stage=FailureStage.SESSION,
        message="Session failed",
        transient=False,
        retryable=False,
        recommended_recovery=RecoveryAction.STOP,
        source_type="RuntimeError",
        source_message=source_message,
    )


def make_session(
    repo_path: Path,
    *,
    session_id: str = "ses_test",
    status: SessionStatus = SessionStatus.CREATED,
    repo: RepositoryRef | None = None,
    worktree: WorktreeRef | None = None,
    task: TaskSpec | None = None,
    provider_id: str = "provider-a",
    model_id: str = "model-a",
    **overrides: Any,
) -> Session:
    now = datetime.now(timezone.utc)
    repository = repo if repo is not None else make_repo_ref(repo_path)
    data: dict[str, Any] = {
        "manifest": SessionManifest(
            session_id=session_id,
            repo_id=repository.repo_id,
            created_at=now,
            updated_at=now,
        ),
        "status": status,
        "task": task if task is not None else make_task(),
        "provider_id": provider_id,
        "model_id": model_id,
        "repo": repository,
        "worktree": worktree,
    }
    data.update(overrides)
    return Session.model_validate(data)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    return init_git_repo(tmp_path / "repo")
