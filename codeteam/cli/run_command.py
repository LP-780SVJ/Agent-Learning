from __future__ import annotations

import os
import signal
import subprocess
import uuid
from pathlib import Path

import typer

from codeteam.agent.inspection import RepositoryInspector
from codeteam.agent.orchestrator import SingleAgentOrchestrator
from codeteam.application.build_context import ContextApplicationService
from codeteam.cli.render import render_error, render_json, render_text
from codeteam.cli.requests import (
    DiffRequest,
    ResumeRequest,
    RollbackRequest,
    RunRequest,
)
from codeteam.git.checkpoint import CheckpointManager
from codeteam.git.errors import CheckpointError, GitWorkspaceError
from codeteam.git.models import (
    Checkpoint,
    GitDiff,
    RollbackResult,
    RollbackStatus,
)
from codeteam.git.workspace import GitWorkspace
from codeteam.planning.models import PlanStep, create_plan
from codeteam.planning.planner import MockPlanner
from codeteam.session.errors import (
    RepositoryMismatchError,
    SessionAlreadyActiveError,
    SessionError,
    SessionRecoveryRequiredError,
    SessionTerminalError,
)
from codeteam.session.models import RepositoryRef, Session
from codeteam.session.service import SessionService
from codeteam.session.store import JsonSessionStore
from codeteam.task.models import create_task_spec
from codeteam.task.state import TaskStatus


def run_agent_task(request: RunRequest) -> None:
    repo_root = request.repo.resolve()
    task_id = f"task-{uuid.uuid4().hex[:8]}"

    task = create_task_spec(
        task_id=task_id,
        original_request=request.task,
    )
    repo_ref = _build_repository_ref(repo_root)

    store = _session_store_for_repo(repo_root)
    session_service = SessionService(store)

    session = session_service.create_session(
        task=task,
        repo=repo_ref,
        provider_id="mock",
        model_id="mock-model",
    )

    render_text(f"Session: {session.manifest.session_id}")

    if os.environ.get("CODETEAM_CLI_TEST_WAIT_AFTER_SESSION") == "1":
        try:
            signal.pause()
        except KeyboardInterrupt as error:
            session_service.pause(session, reason="user_interrupt")
            render_text(f"Status: {TaskStatus.PAUSED.value}")
            raise typer.Exit(130) from error

    planner = MockPlanner(
        plan=create_plan(
            plan_id=f"{task_id}-plan-v1",
            task_id=task_id,
            steps=(
                PlanStep(
                    step_id="P1",
                    title="Inspect task",
                    description="Inspect repository context and prepare plan.",
                ),
            ),
        )
    )

    def persist_pause(reason: str) -> None:
        session_service.pause(session, reason=reason)

    orchestrator = SingleAgentOrchestrator(
        inspector=RepositoryInspector(ContextApplicationService()),
        planner=planner,
        repository_root=repo_root,
        pause_persister=persist_pause,
    )

    result = orchestrator.run(
        request=request.task,
        task_id=task_id,
    )

    render_text(f"Status: {result.status.value}")

    if result.error:
        render_error(result.error)

    for event in result.events:
        render_text(f"[{event.event_type.value}] {event.message}")

    raise typer.Exit(_exit_code_for_status(result.status))


def _exit_code_for_status(status: TaskStatus) -> int:
    if status is TaskStatus.PAUSED:
        return 130
    if status is TaskStatus.FAILED:
        return 1
    return 0


def _build_repository_ref(repo_root: Path) -> RepositoryRef:
    git_common_dir = _git_output(repo_root, "rev-parse", "--git-common-dir")
    base_sha = _git_output(repo_root, "rev-parse", "HEAD")

    return RepositoryRef(
        repo_id=str(repo_root),
        git_common_dir=str((repo_root / git_common_dir).resolve()),
        base_sha=base_sha,
    )


def _git_output(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        shell=False,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


def _session_store_for_repo(repo_root: Path) -> JsonSessionStore:
    """Keep CLI runtime state out of the working tree diff surface."""
    git_common_dir = _git_output(repo_root, "rev-parse", "--git-common-dir")
    sessions_root = (repo_root / git_common_dir).resolve() / "codeteam" / "sessions"
    return JsonSessionStore(sessions_root)


def _session_store_for_existing_session(
    repo_root: Path,
    session_id: str,
) -> JsonSessionStore:
    primary = _session_store_for_repo(repo_root)
    if (primary.session_dir(session_id) / "session.json").exists():
        return primary

    # Compatibility with sessions created before CLI state moved under .git/.
    legacy = JsonSessionStore(repo_root / ".codeteam" / "sessions")
    if (legacy.session_dir(session_id) / "session.json").exists():
        return legacy

    return primary


def resume_agent_session(request: ResumeRequest) -> None:
    repo_root = request.repo.resolve()

    if request.provider_id is not None or request.model_id is not None:
        render_error("Model override is not wired for CLI resume yet.")
        raise typer.Exit(2)

    try:
        store = _session_store_for_existing_session(repo_root, request.session_id)
        service = SessionService(
            store,
            runtime_factory=_rebuild_runtime,
        )
        outcome = service.resume(
            request.session_id,
            current_repo=repo_root,
        )
    except SessionRecoveryRequiredError as error:
        render_error(f"Session requires recovery: {error}")
        raise typer.Exit(2) from error
    except RepositoryMismatchError as error:
        render_error(f"Repository mismatch: {error}")
        raise typer.Exit(2) from error
    except SessionAlreadyActiveError as error:
        render_error(f"Session is already active: {error}")
        raise typer.Exit(2) from error
    except SessionTerminalError as error:
        render_error(f"Session cannot resume: {error}")
        raise typer.Exit(2) from error
    except SessionError as error:
        render_error(str(error))
        raise typer.Exit(2) from error

    render_text(f"Session: {outcome.session.manifest.session_id}")
    render_text(f"Status: {outcome.session.status.value}")
    render_text(f"Task: {outcome.session.task.original_request}")

    if outcome.runtime is not None:
        render_text("Runtime: rebuilt")

    raise typer.Exit(0)


def _rebuild_runtime(session: Session) -> dict[str, str]:
    return {
        "session_id": session.manifest.session_id,
        "task_id": session.task.task_id,
        "provider_id": session.provider_id,
        "model_id": session.model_id,
    }


def diff_agent_session(request: DiffRequest) -> None:
    repo_root = request.repo.resolve()

    try:
        store = _session_store_for_existing_session(repo_root, request.session_id)
        session = store.load(request.session_id)
        workspace_root = _workspace_path_for_session(session, repo_root)
        diff = GitWorkspace(workspace_root).diff(base_ref=request.base_ref)
    except SessionError as error:
        render_error(str(error))
        raise typer.Exit(2) from error
    except (OSError, ValueError) as error:
        render_error(f"Invalid workspace path: {error}")
        raise typer.Exit(2) from error
    except GitWorkspaceError as error:
        render_error(str(error))
        raise typer.Exit(2) from error

    if request.output_format == "json":
        render_json({
            "session_id": session.manifest.session_id,
            "workspace": str(workspace_root),
            "base_ref": diff.base_ref,
            "additions": diff.additions,
            "deletions": diff.deletions,
            "patch_bytes": diff.patch_bytes,
            "has_binary_changes": diff.has_binary_changes,
            "changes": [
                {
                    "kind": change.kind.value,
                    "path": change.path,
                    "old_path": change.old_path,
                    "similarity": change.similarity,
                }
                for change in diff.changes
            ],
            "untracked_paths": diff.untracked_paths,
            "patch": diff.patch,
        })
        raise typer.Exit(0)

    _render_diff_text(
        session_id=session.manifest.session_id,
        workspace_root=workspace_root,
        diff=diff,
    )
    raise typer.Exit(0)


def _workspace_path_for_session(session: Session, fallback_repo: Path) -> Path:
    if session.worktree is not None:
        return Path(session.worktree.path).resolve()
    return fallback_repo


def _render_diff_text(
    *,
    session_id: str,
    workspace_root: Path,
    diff: GitDiff,
) -> None:
    render_text(f"Session: {session_id}")
    render_text(f"Workspace: {workspace_root}")
    render_text(f"Base: {diff.base_ref}")
    render_text(
        f"Summary: {len(diff.changes)} files changed, "
        f"+{diff.additions}/-{diff.deletions}, "
        f"{diff.patch_bytes} patch bytes"
    )

    if diff.has_binary_changes:
        render_text("Warning: binary changes detected")

    if diff.untracked_paths:
        render_text("")
        render_text("Untracked:")
        for path in diff.untracked_paths:
            render_text(f"  {path}")

    if diff.patch:
        render_text("")
        render_text(diff.patch)
    else:
        render_text("")
        render_text("No tracked diff.")


def _checkpoint_state_root_for_repo(repo_root: Path) -> Path:
    return (
        repo_root.resolve().parent
        / ".codeteam"
        / "checkpoints"
        / repo_root.name
    )


def rollback_agent_session(request: RollbackRequest) -> None:
    repo_root = request.repo.resolve()

    try:
        store = _session_store_for_existing_session(repo_root, request.session_id)
        session = store.load(request.session_id)
        workspace_root = _workspace_path_for_session(session, repo_root)
        manager = CheckpointManager(
            workspace_root=workspace_root,
            state_root=_checkpoint_state_root_for_repo(repo_root),
            task_id=session.task.task_id,
        )
        checkpoint = _find_checkpoint(
            manager=manager,
            session=session,
            checkpoint_id=request.checkpoint_id,
        )
        result = manager.rollback(checkpoint)
    except SessionError as error:
        render_error(str(error))
        raise typer.Exit(2) from error
    except (OSError, ValueError) as error:
        render_error(f"Invalid rollback workspace: {error}")
        raise typer.Exit(2) from error
    except CheckpointError as error:
        render_error(str(error))
        raise typer.Exit(2) from error
    except typer.BadParameter as error:
        render_error(str(error))
        raise typer.Exit(2) from error

    if request.output_format == "json":
        render_json(_rollback_result_payload(result))
        raise typer.Exit(_exit_code_for_rollback(result))

    _render_rollback_text(result)
    raise typer.Exit(_exit_code_for_rollback(result))


def _find_checkpoint(
    *,
    manager: CheckpointManager,
    session: Session,
    checkpoint_id: str,
) -> Checkpoint:
    checkpoints = {
        checkpoint.checkpoint_id: checkpoint
        for checkpoint in manager.list_checkpoints()
    }

    checkpoint = checkpoints.get(checkpoint_id)
    if checkpoint is None:
        raise typer.BadParameter(f"checkpoint 不存在: {checkpoint_id}")

    known_checkpoint_ids = set(session.checkpoint_ids)
    if session.current_checkpoint_id is not None:
        known_checkpoint_ids.add(session.current_checkpoint_id)

    if known_checkpoint_ids and checkpoint_id not in known_checkpoint_ids:
        raise typer.BadParameter(
            f"checkpoint {checkpoint_id} 不属于 session "
            f"{session.manifest.session_id}"
        )

    if checkpoint.task_id != session.task.task_id:
        raise typer.BadParameter(
            f"checkpoint {checkpoint_id} 属于 {checkpoint.task_id}，"
            f"不是当前 session task {session.task.task_id}"
        )

    return checkpoint


def _rollback_result_payload(result: RollbackResult) -> dict[str, object]:
    return {
        "status": result.status.value,
        "task_id": result.task_id,
        "target_checkpoint_id": result.target_checkpoint_id,
        "safety_checkpoint_id": result.safety_checkpoint_id,
        "restored_paths": result.restored_paths,
        "removed_paths": result.removed_paths,
        "error": result.error,
    }


def _render_rollback_text(result: RollbackResult) -> None:
    render_text(f"Rollback: {result.status.value}")
    render_text(f"Task: {result.task_id}")
    render_text(f"Target checkpoint: {result.target_checkpoint_id}")
    render_text(f"Safety checkpoint: {result.safety_checkpoint_id}")

    if result.restored_paths:
        render_text("")
        render_text("Restored:")
        for path in result.restored_paths:
            render_text(f"  {path}")

    if result.removed_paths:
        render_text("")
        render_text("Removed:")
        for path in result.removed_paths:
            render_text(f"  {path}")

    if result.error:
        render_error(result.error)


def _exit_code_for_rollback(result: RollbackResult) -> int:
    if result.status is RollbackStatus.SUCCESS:
        return 0
    return 1
