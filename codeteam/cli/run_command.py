from __future__ import annotations

import json
import os
import signal
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

import typer

from codeteam.agent.runtime import CodingAgentRuntime
from codeteam.agent.runtime_models import (
    CodingAgentRunRequest,
    CompactionMode,
    RuntimeStatus,
)
from codeteam.agent.runtime_tools import render_workspace_diff
from codeteam.cli.agent_eval_command import (
    _resolve_llm_config,
    make_runtime_model_client,
)
from codeteam.cli.render import render_error, render_json, render_text
from codeteam.cli.requests import (
    DiffRequest,
    ResumeRequest,
    RollbackRequest,
    RunRequest,
)
from codeteam.events import AgentEventType
from codeteam.git.checkpoint import CheckpointManager
from codeteam.git.errors import CheckpointError, GitWorkspaceError
from codeteam.git.models import (
    Checkpoint,
    GitDiff,
    RollbackResult,
    RollbackStatus,
)
from codeteam.git.workspace import GitWorkspace
from codeteam.git.worktree import WorktreeManager
from codeteam.git.worktree_paths import repository_worktree_root
from codeteam.llm.mock import MockModelClient
from codeteam.sandbox.preflight import SandboxPreflight, SandboxPreflightResult
from codeteam.session.errors import (
    RepositoryMismatchError,
    SessionAlreadyActiveError,
    SessionError,
    SessionRecoveryRequiredError,
    SessionTerminalError,
)
from codeteam.session.models import (
    ActiveOperation,
    AgentRuntimeState,
    OperationStatus,
    RepositoryRef,
    Session,
    SessionStatus,
    SessionUsage,
    WorktreeRef,
)
from codeteam.session.service import SessionService
from codeteam.session.store import JsonSessionStore
from codeteam.task.models import create_task_spec
from codeteam.task.state import TaskStatus


def run_agent_task(request: RunRequest) -> None:
    repo_root = request.repo.resolve()
    task_id = f"task-{uuid.uuid4().hex[:8]}"

    try:
        test_wait = os.environ.get("CODETEAM_CLI_TEST_WAIT_AFTER_SESSION") == "1"
        provider_id, model_id, model_client = _build_model_client(
            "mock" if test_wait else request.provider_id,
            "mock-model" if test_wait else request.model_id,
        )
        worktree = WorktreeManager(
            repo_root,
            worktree_root=repository_worktree_root(
                repo_root,
                worktree_root=request.worktree_root,
            ),
        ).create(task_id, base_ref="HEAD")
    except (OSError, ValueError, RuntimeError) as error:
        render_error(str(error))
        raise typer.Exit(2) from error

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
        provider_id=provider_id,
        model_id=model_id,
        worktree=WorktreeRef(
            task_id=task_id,
            branch_name=worktree.branch_name,
            path=str(worktree.path),
            base_sha=worktree.base_sha,
            head_sha=worktree.head_sha,
            last_known_head_sha=worktree.head_sha,
        ),
    )

    if request.output_format == "text":
        render_text(f"Session: {session.manifest.session_id}")

    if test_wait:
        try:
            signal.pause()
        except KeyboardInterrupt as error:
            session_service.pause(session, reason="user_interrupt")
            render_text(f"Status: {TaskStatus.PAUSED.value}")
            raise typer.Exit(130) from error

    session = store.save(
        session.model_copy(
            update={
                "status": SessionStatus.RUNNING,
                "task_status": TaskStatus.IMPLEMENTING,
                "runtime_state": AgentRuntimeState(
                    context_budget=request.context_budget,
                    max_steps=request.max_steps,
                    max_tool_calls=request.max_tool_calls,
                    max_repairs=request.max_repairs,
                    max_protocol_repairs=request.max_protocol_repairs,
                    compaction_mode=request.compaction_mode,
                ),
            }
        )
    )
    persisted_model_output_count = 0

    def persist_state(state, evidence) -> None:
        nonlocal persisted_model_output_count, session
        for output in state.model_outputs[persisted_model_output_count:]:
            store.append_model_output(session.manifest.session_id, output)
        persisted_model_output_count = len(state.model_outputs)
        last_verification = (
            evidence.verification[-1].model_dump(mode="json")
            if evidence.verification
            else None
        )
        session = store.save(
            session.model_copy(
                update={
                    "runtime_state": session.runtime_state.model_copy(
                        update={
                            "step_count": state.step_count,
                            "tool_call_count": state.tool_call_count,
                            "repair_attempts": evidence.repair_attempts,
                            "protocol_repair_attempts": (
                                state.protocol_repair_count
                            ),
                            "protocol_repair_streak": state.protocol_repair_streak,
                            "workspace_version": evidence.workspace_version,
                            "recent_messages": tuple(state.messages[-24:]),
                            "last_verification": last_verification,
                        }
                    ),
                    "checkpoint_ids": tuple(
                        dict.fromkeys(
                            (*session.checkpoint_ids, *evidence.checkpoint_ids)
                        )
                    ),
                    "current_checkpoint_id": (
                        evidence.checkpoint_ids[-1]
                        if evidence.checkpoint_ids
                        else session.current_checkpoint_id
                    ),
                }
            )
        )
        event = store.append_event(
            session.manifest.session_id,
            event_type=AgentEventType.TURN_COMPLETED,
            state_version=session.manifest.state_version,
            payload={
                "step_count": state.step_count,
                "tool_call_count": state.tool_call_count,
                "workspace_version": evidence.workspace_version,
                "last_role": state.messages[-1].role if state.messages else None,
            },
        )
        session.manifest.last_event_seq = event.seq

    def persist_operation(phase, state, evidence, data) -> None:
        del state, evidence
        nonlocal session
        completed = phase.endswith(".completed")
        operation_id = str(
            data.get("call_id") or f"model-step-{data.get('step_index', 0)}"
        )
        operation_kind = (
            f"tool:{data['tool_name']}"
            if data.get("tool_name")
            else phase.split(".", 1)[0]
        )
        session = store.save(
            session.model_copy(
                update={
                    "active_operation": ActiveOperation(
                        operation_id=operation_id,
                        kind=operation_kind,
                        status=(
                            OperationStatus.COMPLETED
                            if completed
                            else OperationStatus.STARTED
                        ),
                        checkpoint_before=session.current_checkpoint_id,
                        started_at=datetime.now(UTC),
                    )
                }
            )
        )
        event = store.append_event(
            session.manifest.session_id,
            event_type=(
                AgentEventType.TURN_COMPLETED
                if completed
                else AgentEventType.TURN_STARTED
            ),
            state_version=session.manifest.state_version,
            payload={
                "phase": phase,
                "operation_id": operation_id,
                "tool_name": data.get("tool_name"),
                "success": data.get("success"),
            },
        )
        session.manifest.last_event_seq = event.seq

    runtime = CodingAgentRuntime(
        model_client=model_client,
        state_callback=persist_state,
        operation_callback=persist_operation,
        sandbox_preflight=_test_sandbox_preflight(),
    )
    runtime_request = CodingAgentRunRequest(
        task_id=task_id,
        task=request.task,
        workspace_root=worktree.path,
        provider_id=provider_id,
        model_id=model_id,
        context_budget=request.context_budget,
        max_steps=request.max_steps,
        max_tool_calls=request.max_tool_calls,
        max_repairs=request.max_repairs,
        max_protocol_repairs=request.max_protocol_repairs,
        compaction_mode=CompactionMode(request.compaction_mode),
        checkpoint_state_root=_checkpoint_state_root_for_repo(repo_root),
    )
    try:
        result = runtime.run(runtime_request)
    except KeyboardInterrupt as error:
        session_service.pause(session, reason="user_interrupt")
        render_text(f"Status: {TaskStatus.PAUSED.value}")
        raise typer.Exit(130) from error

    terminal_status = {
        RuntimeStatus.COMPLETED: SessionStatus.COMPLETED,
        RuntimeStatus.FAILED: SessionStatus.FAILED,
        RuntimeStatus.PAUSED: SessionStatus.PAUSED,
    }[result.status]
    task_status = {
        RuntimeStatus.COMPLETED: TaskStatus.COMPLETED,
        RuntimeStatus.FAILED: TaskStatus.FAILED,
        RuntimeStatus.PAUSED: TaskStatus.PAUSED,
    }[result.status]
    session = store.save(
        session.model_copy(
            update={
                "status": terminal_status,
                "task_status": task_status,
                "usage": SessionUsage(
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cost_usd=result.cost_usd,
                    tool_calls=result.tool_calls_used,
                    repair_attempts=result.repair_attempts,
                    protocol_repair_attempts=result.protocol_repairs_used,
                ),
                "checkpoint_ids": tuple(
                    dict.fromkeys((*session.checkpoint_ids, *result.checkpoint_ids))
                ),
                "current_checkpoint_id": (
                    result.checkpoint_ids[-1]
                    if result.checkpoint_ids
                    else session.current_checkpoint_id
                ),
            }
        )
    )

    payload = result.model_dump(mode="json", exclude={"messages"})
    payload.update(
        {
            "session_id": session.manifest.session_id,
            "branch": worktree.branch_name,
            "worktree": str(worktree.path),
        }
    )
    if request.output_format == "json":
        render_json(payload)
    else:
        render_text(f"Status: {result.status.value}")
        render_text(f"Worktree: {worktree.path}")
        render_text(f"Branch: {worktree.branch_name}")
        if result.error:
            render_error(result.error)
        if result.diff:
            render_text(result.diff)
    raise typer.Exit(_exit_code_for_runtime_status(result.status))


def _build_model_client(
    provider_id: str | None,
    model_id: str | None,
):
    if provider_id == "mock":
        return (
            "mock",
            model_id or "mock-model",
            MockModelClient(
                [
                    json.dumps(
                        {
                            "status": "needs_user_input",
                            "summary": "paused",
                            "tests_passed": False,
                            "user_input_request": (
                                "mock provider has no scripted actions"
                            ),
                        }
                    )
                ]
            ),
        )
    effective_provider = provider_id or "openai-compatible"
    if effective_provider != "openai-compatible":
        raise ValueError(f"Unsupported provider: {effective_provider}")
    try:
        config = _resolve_llm_config()
    except SystemExit as error:
        raise ValueError(str(error)) from error
    if model_id is not None:
        config["CODETEAM_LLM_MODEL"] = model_id
    client = make_runtime_model_client(config)
    return effective_provider, config["CODETEAM_LLM_MODEL"], client


def _exit_code_for_runtime_status(status: RuntimeStatus) -> int:
    if status is RuntimeStatus.COMPLETED:
        return 0
    if status is RuntimeStatus.PAUSED:
        return 130
    return 1


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

    try:
        store = _session_store_for_existing_session(repo_root, request.session_id)
        service = SessionService(
            store,
            runtime_factory=lambda session: session.manifest.session_id,
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

    state = outcome.session.runtime_state
    try:
        provider_id, model_id, model_client = _build_model_client(
            request.provider_id or outcome.session.provider_id,
            request.model_id or outcome.session.model_id,
        )
    except (OSError, ValueError, RuntimeError) as error:
        service.pause(outcome.session, reason="provider_unavailable")
        render_error(str(error))
        raise typer.Exit(2) from error

    session = store.save(
        outcome.session.model_copy(
            update={"provider_id": provider_id, "model_id": model_id}
        )
    )
    persisted_model_output_count = 0

    def persist_state(loop_state, evidence) -> None:
        nonlocal persisted_model_output_count, session
        for output in loop_state.model_outputs[persisted_model_output_count:]:
            store.append_model_output(session.manifest.session_id, output)
        persisted_model_output_count = len(loop_state.model_outputs)
        session = store.save(
            session.model_copy(
                update={
                    "runtime_state": session.runtime_state.model_copy(
                        update={
                            "step_count": state.step_count + loop_state.step_count,
                            "tool_call_count": (
                                state.tool_call_count + loop_state.tool_call_count
                            ),
                            "repair_attempts": (
                                state.repair_attempts + evidence.repair_attempts
                            ),
                            "protocol_repair_attempts": (
                                state.protocol_repair_attempts
                                + loop_state.protocol_repair_count
                            ),
                            "protocol_repair_streak": loop_state.protocol_repair_streak,
                            "workspace_version": (
                                state.workspace_version + evidence.workspace_version
                            ),
                            "recent_messages": tuple(loop_state.messages[-24:]),
                            "last_verification": (
                                evidence.verification[-1].model_dump(mode="json")
                                if evidence.verification
                                else state.last_verification
                            ),
                        }
                    ),
                    "checkpoint_ids": tuple(
                        dict.fromkeys(
                            (*session.checkpoint_ids, *evidence.checkpoint_ids)
                        )
                    ),
                    "current_checkpoint_id": (
                        evidence.checkpoint_ids[-1]
                        if evidence.checkpoint_ids
                        else session.current_checkpoint_id
                    ),
                }
            )
        )
        event = store.append_event(
            session.manifest.session_id,
            event_type=AgentEventType.TURN_COMPLETED,
            state_version=session.manifest.state_version,
            payload={
                "resumed": True,
                "step_count": loop_state.step_count,
                "tool_call_count": loop_state.tool_call_count,
                "workspace_version": evidence.workspace_version,
            },
        )
        session.manifest.last_event_seq = event.seq

    def persist_operation(phase, loop_state, evidence, data) -> None:
        del loop_state, evidence
        nonlocal session
        completed = phase.endswith(".completed")
        operation_id = str(
            data.get("call_id") or f"model-step-{data.get('step_index', 0)}"
        )
        operation_kind = (
            f"tool:{data['tool_name']}"
            if data.get("tool_name")
            else phase.split(".", 1)[0]
        )
        session = store.save(
            session.model_copy(
                update={
                    "active_operation": ActiveOperation(
                        operation_id=operation_id,
                        kind=operation_kind,
                        status=(
                            OperationStatus.COMPLETED
                            if completed
                            else OperationStatus.STARTED
                        ),
                        checkpoint_before=session.current_checkpoint_id,
                        started_at=datetime.now(UTC),
                    )
                }
            )
        )
        event = store.append_event(
            session.manifest.session_id,
            event_type=(
                AgentEventType.TURN_COMPLETED
                if completed
                else AgentEventType.TURN_STARTED
            ),
            state_version=session.manifest.state_version,
            payload={
                "phase": phase,
                "operation_id": operation_id,
                "tool_name": data.get("tool_name"),
                "success": data.get("success"),
                "resumed": True,
            },
        )
        session.manifest.last_event_seq = event.seq

    workspace_root = _workspace_path_for_session(session, repo_root)
    remaining_steps = state.max_steps - state.step_count
    remaining_tool_calls = state.max_tool_calls - state.tool_call_count
    remaining_repairs = state.max_repairs - state.repair_attempts
    if remaining_steps <= 0 or remaining_tool_calls <= 0:
        store.save(
            session.model_copy(
                update={
                    "status": SessionStatus.FAILED,
                    "task_status": TaskStatus.FAILED,
                }
            )
        )
        render_error("Session runtime budget is exhausted; resume is not allowed.")
        raise typer.Exit(1)
    runtime = CodingAgentRuntime(
        model_client=model_client,
        state_callback=persist_state,
        operation_callback=persist_operation,
        sandbox_preflight=_test_sandbox_preflight(),
    )
    result = runtime.run(
        CodingAgentRunRequest(
            task_id=session.task.task_id,
            task=session.task.original_request,
            workspace_root=workspace_root,
            provider_id=provider_id,
            model_id=model_id,
            context_budget=state.context_budget,
            max_steps=remaining_steps,
            max_tool_calls=remaining_tool_calls,
            max_repairs=max(0, remaining_repairs),
            max_protocol_repairs=state.max_protocol_repairs,
            compaction_mode=CompactionMode(state.compaction_mode),
            verification_commands=state.verification_commands,
            checkpoint_state_root=_checkpoint_state_root_for_repo(repo_root),
            initial_messages=state.recent_messages,
            initial_protocol_repair_streak=state.protocol_repair_streak,
        )
    )
    status = {
        RuntimeStatus.COMPLETED: SessionStatus.COMPLETED,
        RuntimeStatus.FAILED: SessionStatus.FAILED,
        RuntimeStatus.PAUSED: SessionStatus.PAUSED,
    }[result.status]
    resumed_task_status = {
        RuntimeStatus.COMPLETED: TaskStatus.COMPLETED,
        RuntimeStatus.FAILED: TaskStatus.FAILED,
        RuntimeStatus.PAUSED: TaskStatus.PAUSED,
    }[result.status]
    store.save(
        session.model_copy(
            update={
                "status": status,
                "task_status": resumed_task_status,
                "usage": session.usage.model_copy(
                    update={
                        "input_tokens": (
                            session.usage.input_tokens + result.input_tokens
                        ),
                        "output_tokens": (
                            session.usage.output_tokens + result.output_tokens
                        ),
                        "cost_usd": session.usage.cost_usd + result.cost_usd,
                        "tool_calls": (
                            session.usage.tool_calls + result.tool_calls_used
                        ),
                        "repair_attempts": (
                            session.usage.repair_attempts + result.repair_attempts
                        ),
                        "protocol_repair_attempts": (
                            session.usage.protocol_repair_attempts
                            + result.protocol_repairs_used
                        ),
                    }
                ),
                "checkpoint_ids": tuple(
                    dict.fromkeys((*session.checkpoint_ids, *result.checkpoint_ids))
                ),
            }
        )
    )
    render_text(f"Status: {result.status.value}")
    if result.error:
        render_error(result.error)
    raise typer.Exit(_exit_code_for_runtime_status(result.status))


def diff_agent_session(request: DiffRequest) -> None:
    repo_root = request.repo.resolve()

    try:
        store = _session_store_for_existing_session(repo_root, request.session_id)
        session = store.load(request.session_id)
        workspace_root = _workspace_path_for_session(session, repo_root)
        diff = GitWorkspace(workspace_root).diff(base_ref=request.base_ref)
        if request.base_ref == "HEAD":
            patch = render_workspace_diff(workspace_root)
            diff = diff.model_copy(
                update={"patch": patch, "patch_bytes": len(patch.encode("utf-8"))}
            )
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


class _AvailableTestPreflight:
    def check(self, workspace_root: Path) -> SandboxPreflightResult:
        del workspace_root
        return SandboxPreflightResult(available=True)


def _test_sandbox_preflight() -> SandboxPreflight | None:
    if os.environ.get("CODETEAM_CLI_TEST_WAIT_AFTER_SESSION") == "1":
        return _AvailableTestPreflight()
    return None
