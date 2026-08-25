from __future__ import annotations

import json
from collections.abc import Callable

from codeteam.agent.runtime_models import (
    CodingAgentRunRequest,
    CodingAgentRunResult,
    CompactionMode,
    RuntimeStatus,
)
from codeteam.agent.runtime_tools import (
    RuntimeEvidence,
    create_runtime_tools,
    render_workspace_diff,
)
from codeteam.agent_loop import run_agent_loop
from codeteam.application.build_context import ContextApplicationService
from codeteam.events import AgentEventType
from codeteam.execution.safe_execution_service import SafeExecutionService
from codeteam.git.workspace import GitWorkspace
from codeteam.limits import AgentLoopLimits
from codeteam.llm.base import ModelClient
from codeteam.schemas.final_output import CompletionStatus
from codeteam.schemas.messages import Message
from codeteam.state import AgentLoopState, StopReason

StateCallback = Callable[[AgentLoopState, RuntimeEvidence], None]
OperationCallback = Callable[
    [str, AgentLoopState, RuntimeEvidence, dict[str, object]], None
]


class CodingAgentRuntime:
    """The single production loop used by both CLI and agent evaluation."""

    def __init__(
        self,
        *,
        model_client: ModelClient,
        safe_execution: SafeExecutionService | None = None,
        context_service: ContextApplicationService | None = None,
        state_callback: StateCallback | None = None,
        operation_callback: OperationCallback | None = None,
    ) -> None:
        self._model_client = model_client
        self._safe_execution = safe_execution or SafeExecutionService()
        self._context_service = context_service or ContextApplicationService()
        self._state_callback = state_callback
        self._operation_callback = operation_callback

    def run(self, request: CodingAgentRunRequest) -> CodingAgentRunResult:
        root = request.workspace_root.resolve(strict=True)
        checkpoint_root = request.checkpoint_state_root or (
            root.parent / ".codeteam" / "checkpoints" / request.task_id
        )
        evidence = RuntimeEvidence()
        tools = create_runtime_tools(
            workspace_root=root,
            task_id=request.task_id,
            checkpoint_state_root=checkpoint_root,
            safe_execution=self._safe_execution,
            evidence=evidence,
            allowed_verification_commands=request.verification_commands,
            max_repairs=request.max_repairs,
        )
        messages = list(request.initial_messages) or self._initial_messages(
            request,
            tools.describe(),
        )

        def persist(state: AgentLoopState) -> None:
            if self._state_callback is not None:
                self._state_callback(state, evidence)

        def operation(
            phase: str,
            state: AgentLoopState,
            data: dict[str, object],
        ) -> None:
            if self._operation_callback is not None:
                self._operation_callback(phase, state, evidence, data)

        persist(AgentLoopState(messages=list(messages)))

        loop = run_agent_loop(
            self._model_client,
            tools,
            messages,
            limits=AgentLoopLimits(
                max_steps=request.max_steps,
                max_tool_calls=request.max_tool_calls,
            ),
            actual_tests_passed=lambda: evidence.tests_passed,
            message_transform=_message_transform(
                request.compaction_mode,
                request.context_budget,
            ),
            state_version_provider=lambda: evidence.workspace_version,
            state_callback=persist,
            lifecycle_callback=operation,
        )
        workspace = GitWorkspace(root)
        changed_files = tuple(change.path for change in workspace.changed_files())
        diff = render_workspace_diff(root) if changed_files else ""
        status, category, error = self._finalize(loop, evidence, changed_files, diff)
        summary = (
            loop.final_output.summary
            if loop.final_output is not None
            else error or "Agent stopped without a final response."
        )
        return CodingAgentRunResult(
            task_id=request.task_id,
            status=status,
            summary=summary,
            workspace_root=root,
            diff=diff,
            changed_files=changed_files,
            checkpoint_ids=tuple(evidence.checkpoint_ids),
            verification=tuple(evidence.verification),
            steps_used=loop.steps_used,
            tool_calls_used=loop.tool_calls_used,
            repair_attempts=evidence.repair_attempts,
            input_tokens=loop.total_input_tokens,
            output_tokens=loop.total_output_tokens,
            cost_usd=loop.total_cost,
            duration_ms=int(loop.duration_seconds * 1000),
            model_duration_ms=_paired_event_duration_ms(
                loop.events,
                AgentEventType.MODEL_REQUEST,
                AgentEventType.MODEL_RESPONSE,
            ),
            tool_duration_ms=_paired_event_duration_ms(
                loop.events,
                AgentEventType.TOOL_CALLED,
                AgentEventType.TOOL_RESULT,
            ),
            repair_duration_ms=evidence.repair_duration_ms,
            failure_category=category,
            error=error,
            messages=tuple(loop.messages),
            events=tuple(event.event_type.value for event in loop.events),
        )

    def _initial_messages(
        self,
        request: CodingAgentRunRequest,
        schemas: list[dict[str, object]],
    ) -> list[Message]:
        context = self._context_service.execute(
            query=request.task,
            repository_root=request.workspace_root,
            budget_tokens=min(request.context_budget, 4096),
        )
        context_payload = {
            "repo_map": context.repo_map,
            "files": [item.model_dump() for item in context.code_context],
            "instructions": context.applicable_instructions,
            "visible_test_commands": [item.model_dump(mode="json") for item in context.test_commands],
            "diagnostics": context.diagnostics,
        }
        system = {
            "role": "coding_agent",
            "protocol": "Return exactly one JSON object containing non-empty tool_calls or a final output.",
            "tools": schemas,
            "budgets": {
                "max_steps": request.max_steps,
                "max_tool_calls": request.max_tool_calls,
                "max_repairs": request.max_repairs,
                "context_tokens": request.context_budget,
            },
            "completion": [
                "Make a real Git diff.",
                "Run at least one visible verification command successfully.",
                "Inspect the final diff before returning completed.",
                "Never claim hidden acceptance results.",
            ],
            "execution_boundary": (
                "run_tests executes inside Docker at /workspace. Use python -m pytest "
                "instead of host-only .venv/bin/python paths. Commands are argv arrays; "
                "shell strings, pipes, and redirection are unavailable."
            ),
        }
        user = {
            "task": request.task,
            "workspace": str(request.workspace_root),
            "planning_enabled": request.planning_enabled,
            "verification_commands": [list(command) for command in request.verification_commands],
            "initial_context": context_payload,
        }
        return [
            Message(role="system", content=json.dumps(system, ensure_ascii=False)),
            Message(role="user", content=json.dumps(user, ensure_ascii=False)),
        ]

    @staticmethod
    def _finalize(loop, evidence, changed_files, diff):
        if evidence.paused_reason:
            return RuntimeStatus.PAUSED, "execution_paused", evidence.paused_reason
        if loop.stop_reason is StopReason.PROVIDER_ERROR:
            return RuntimeStatus.FAILED, "provider_blocked", loop.error
        if loop.stop_reason is StopReason.INTERNAL_ERROR:
            return RuntimeStatus.FAILED, "internal_failure", loop.error
        if loop.status is CompletionStatus.NEEDS_USER_INPUT:
            return RuntimeStatus.PAUSED, "user_input_required", loop.error
        if loop.status is not CompletionStatus.COMPLETED:
            return RuntimeStatus.FAILED, loop.stop_reason.value, loop.error
        if not changed_files or not diff.strip():
            return RuntimeStatus.FAILED, "no_patch", "Completion requires a real Git diff."
        if any(path == ".git" or path.startswith(".git/") for path in changed_files):
            return RuntimeStatus.FAILED, "security_failure", "Final diff touches Git metadata."
        if not evidence.verification:
            return RuntimeStatus.PAUSED, "verification_required", "No visible verification was run."
        if not evidence.tests_passed:
            return RuntimeStatus.FAILED, "verification_failed", "The latest visible verification failed."
        return RuntimeStatus.COMPLETED, None, None


def _message_transform(
    mode: CompactionMode,
    context_budget: int,
) -> Callable[[list[Message]], list[Message]]:
    max_chars = context_budget * 4

    def transform(messages: list[Message]) -> list[Message]:
        if mode is CompactionMode.NONE:
            return messages
        if sum(len(item.content or "") for item in messages) <= max_chars:
            return messages
        prefix = [item for item in messages[:2] if item.role in {"system", "user"}]
        recent: list[Message] = []
        used = sum(len(item.content or "") for item in prefix)
        for item in reversed(messages[2:]):
            size = len(item.content or "")
            if recent and used + size > max_chars:
                break
            recent.append(item)
            used += size
        recent.reverse()
        if mode is CompactionMode.NAIVE:
            return [*prefix, *recent]
        omitted = max(0, len(messages) - len(prefix) - len(recent))
        summary = Message(
            role="user",
            content=(
                "Structured context summary: "
                f"{omitted} older interaction messages were compacted. "
                "Use the retained tool observations as current workspace facts."
            ),
        )
        return [*prefix, summary, *recent]

    return transform


def _paired_event_duration_ms(events, start_type, end_type) -> int:
    started: list[float] = []
    total = 0.0
    for event in events:
        if event.event_type is start_type:
            started.append(event.timestamp)
        elif event.event_type is end_type and started:
            total += max(0.0, event.timestamp - started.pop(0))
    return int(total * 1000)
