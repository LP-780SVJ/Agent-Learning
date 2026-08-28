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
    normalize_runtime_action,
    render_workspace_diff,
)
from codeteam.agent_loop import run_agent_loop
from codeteam.application.build_context import ContextApplicationService
from codeteam.events import AgentEventType
from codeteam.execution.safe_execution_service import SafeExecutionService
from codeteam.git.workspace import GitWorkspace
from codeteam.limits import AgentLoopLimits
from codeteam.llm.base import LegacyModelClient, ModelClient
from codeteam.sandbox.preflight import DockerSandboxPreflight, SandboxPreflight
from codeteam.schemas.final_output import CompletionStatus
from codeteam.schemas.messages import Message
from codeteam.state import AgentLoopState, StopReason
from codeteam.usage.token_counter import ApproximateTokenCounter

StateCallback = Callable[[AgentLoopState, RuntimeEvidence], None]
OperationCallback = Callable[
    [str, AgentLoopState, RuntimeEvidence, dict[str, object]], None
]


class CodingAgentRuntime:
    """The single production loop used by both CLI and agent evaluation."""

    def __init__(
        self,
        *,
        model_client: ModelClient | LegacyModelClient,
        safe_execution: SafeExecutionService | None = None,
        context_service: ContextApplicationService | None = None,
        state_callback: StateCallback | None = None,
        operation_callback: OperationCallback | None = None,
        sandbox_preflight: SandboxPreflight | None = None,
    ) -> None:
        self._model_client = model_client
        self._safe_execution = safe_execution or SafeExecutionService()
        self._context_service = context_service or ContextApplicationService()
        self._state_callback = state_callback
        self._operation_callback = operation_callback
        self._sandbox_preflight = sandbox_preflight or DockerSandboxPreflight()

    def run(self, request: CodingAgentRunRequest) -> CodingAgentRunResult:
        root = request.workspace_root.resolve(strict=True)
        preflight = self._sandbox_preflight.check(root)
        if not preflight.available:
            return CodingAgentRunResult(
                task_id=request.task_id,
                status=RuntimeStatus.PAUSED,
                summary="Docker sandbox is unavailable for this workspace.",
                workspace_root=root,
                failure_category="sandbox_unavailable",
                error=preflight.error,
                sandbox_preflight_available=False,
                sandbox_preflight_category=preflight.category,
                events=(
                    AgentEventType.SANDBOX_PREFLIGHT_STARTED.value,
                    AgentEventType.SANDBOX_PREFLIGHT_FAILED.value,
                ),
            )
        checkpoint_root = request.checkpoint_state_root or (
            root.parent / ".codeteam" / "checkpoints" / request.task_id
        )
        evidence = RuntimeEvidence()
        required_verification_commands = (
            request.task_verification_commands or request.verification_commands
        )
        allowed_verification_commands = tuple(
            dict.fromkeys(
                (*request.task_verification_commands, *request.verification_commands)
            )
        )
        tools = create_runtime_tools(
            workspace_root=root,
            task_id=request.task_id,
            checkpoint_state_root=checkpoint_root,
            safe_execution=self._safe_execution,
            evidence=evidence,
            allowed_verification_commands=allowed_verification_commands,
            required_verification_commands=required_verification_commands,
            max_repairs=request.max_repairs,
        )
        messages = _canonicalize_conversation(
            list(request.initial_messages)
        ) or self._initial_messages(request, tools.describe())

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

        persist(
            AgentLoopState(
                messages=list(messages),
                protocol_repair_streak=request.initial_protocol_repair_streak,
            )
        )

        loop = run_agent_loop(
            self._model_client,
            tools,
            messages,
            limits=AgentLoopLimits(
                max_steps=request.max_steps,
                max_tool_calls=request.max_tool_calls,
                max_protocol_repairs=request.max_protocol_repairs,
            ),
            actual_tests_passed=lambda: evidence.tests_passed,
            message_transform=_message_transform(
                request.compaction_mode,
                request.context_budget,
                evidence,
                tool_schemas=tuple(tools.describe()),
            ),
            state_version_provider=lambda: evidence.workspace_version,
            action_fingerprint_normalizer=normalize_runtime_action,
            semantic_repeat_tools=frozenset({"run_tests"}),
            cacheable_tools=frozenset(
                {"list_files", "read_file", "search_code", "git_status", "git_diff"}
            ),
            initial_protocol_repair_streak=request.initial_protocol_repair_streak,
            state_callback=persist,
            lifecycle_callback=operation,
            halt_signal_provider=(
                lambda: (
                    (StopReason.PAUSED, evidence.paused_reason)
                    if evidence.paused_reason is not None
                    else None
                )
            ),
            max_output_tokens=request.max_output_tokens,
            max_input_tokens=request.context_budget,
            model_context_window=request.model_context_window,
            safety_headroom_tokens=request.safety_headroom_tokens,
            native_tools=request.native_tools,
            reasoning_enabled=request.reasoning_enabled,
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
            patch_attempts=evidence.patch_attempts,
            steps_used=loop.steps_used,
            tool_calls_used=loop.tool_calls_used,
            repair_attempts=evidence.repair_attempts,
            protocol_repairs_used=loop.protocol_repairs_used,
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
            sandbox_preflight_available=True,
            messages=tuple(loop.messages),
            model_outputs=tuple(loop.model_outputs),
            events=(
                AgentEventType.SANDBOX_PREFLIGHT_STARTED.value,
                AgentEventType.SANDBOX_PREFLIGHT_PASSED.value,
                *(event.event_type.value for event in loop.events),
            ),
        )

    def _initial_messages(
        self,
        request: CodingAgentRunRequest,
        schemas: list[dict[str, object]],
    ) -> list[Message]:
        context = self._context_service.execute(
            query=request.task,
            repository_root=request.workspace_root,
            # context_budget is the complete provider input budget. Reserve
            # room for instructions, durable history, and native tool schemas.
            budget_tokens=max(1, min(request.context_budget // 2, 4096)),
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
            "protocol": {
                "rule": (
                    "Use provider-native tools when they are available. Only when "
                    "native tools are unavailable, return exactly one raw JSON "
                    "object containing non-empty tool_calls or a final output."
                ),
                "tool_call_schema": {
                    "tool_calls": [
                        {
                            "name": "read_file",
                            "arguments": {"path": "src/example.py"},
                        }
                    ]
                },
                "tool_call_note": (
                    "Do not generate call_id; the Runtime assigns it after validation."
                ),
                "preferred_patch_example": {
                    "tool_calls": [
                        {
                            "name": "apply_patch",
                            "arguments": {
                                "replacements": [
                                    {
                                        "path": "src/example.py",
                                        "old_text": "OLD_VALUE",
                                        "new_text": "NEW_VALUE",
                                        "expected_replacements": 1,
                                    }
                                ]
                            },
                        }
                    ]
                },
                "final_output_schema": {
                    "status": "completed | failed | needs_user_input",
                    "summary": "short factual summary",
                    "tests_passed": True,
                    "error": None,
                    "user_input_request": None,
                },
            },
            "tools": schemas,
            "budgets": {
                "max_steps": request.max_steps,
                "max_tool_calls": request.max_tool_calls,
                "max_repairs": request.max_repairs,
                "max_protocol_repairs": request.max_protocol_repairs,
                "context_tokens": request.context_budget,
                "max_output_tokens": request.max_output_tokens,
                "model_context_window": request.model_context_window,
                "safety_headroom_tokens": request.safety_headroom_tokens,
            },
            "completion": [
                "Make a real Git diff.",
                "Run every task verification command successfully.",
                "Inspect the final diff before returning completed.",
                "Never claim hidden acceptance results.",
                (
                    "The initial context is a current snapshot. Do not reread the same "
                    "file unless it was truncated or the workspace changed."
                ),
            ],
            "execution_boundary": (
                "run_tests argv paths and cwd are relative to the workspace; use '.' for "
                "the workspace root and paths such as tests/auth. The Runtime maps them "
                "to Docker /workspace, so do not put /workspace or host-only .venv paths "
                "in tool arguments. Use python -m pytest. Commands are argv arrays; shell "
                "strings, pipes, and redirection are unavailable."
            ),
        }
        user = {
            "task": request.task,
            "workspace": str(request.workspace_root),
            "planning_enabled": request.planning_enabled,
            "task_verification_commands": [
                list(command)
                for command in (
                    request.task_verification_commands
                    or request.verification_commands
                )
            ],
            "regression_commands": [
                list(command) for command in request.verification_commands
            ],
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
        if not evidence.git_diff_checked:
            return RuntimeStatus.PAUSED, "diff_review_required", "The final Git diff was not inspected."
        return RuntimeStatus.COMPLETED, None, None


def _message_transform(
    mode: CompactionMode,
    context_budget: int,
    evidence: RuntimeEvidence | None = None,
    *,
    tool_schemas: tuple[dict[str, object], ...] = (),
) -> Callable[[list[Message]], list[Message]]:
    def transform(messages: list[Message]) -> list[Message]:
        messages = _canonicalize_conversation(messages)
        if mode is CompactionMode.NONE:
            return messages
        if _conversation_tokens(messages, tool_schemas) <= context_budget:
            return messages

        # Initial context is a snapshot, not an untouchable prefix.  Once the
        # request is over budget, replace it with an explicit compact form.
        prefix = [
            _compact_initial_message(item)
            for item in messages[:2]
            if item.role in {"system", "user"}
        ]
        summary = _structured_context_message(messages, evidence)
        base = [*prefix]
        if mode is CompactionMode.STRUCTURED:
            base.append(summary)

        recent_groups: list[list[Message]] = []
        for group in reversed(_atomic_conversation_groups(messages[2:])):
            candidate_groups = [group, *recent_groups]
            candidate = [*base, *(item for part in candidate_groups for item in part)]
            if _conversation_tokens(candidate, tool_schemas) > context_budget:
                continue
            recent_groups = candidate_groups

        compacted = [*base, *(item for group in recent_groups for item in group)]
        if _conversation_tokens(compacted, tool_schemas) <= context_budget:
            return compacted

        # Very small budgets may not fit the structured summary.  Drop it and
        # reduce initial messages to their durable task/protocol essentials.
        reduced = [_minimal_initial_message(item) for item in prefix]
        if mode is CompactionMode.STRUCTURED:
            # Preserve deterministic working memory even if an unrealistically
            # tiny configured budget cannot fit the minimum request. The
            # provider boundary will reject it as input_budget_exceeded.
            reduced.append(summary)
        for group in recent_groups:
            candidate = [*reduced, *group]
            if _conversation_tokens(candidate, tool_schemas) <= context_budget:
                reduced.extend(group)
        return reduced

    return transform


def _conversation_tokens(
    messages: list[Message],
    tool_schemas: tuple[dict[str, object], ...],
) -> int:
    serialized = json.dumps(
        {
            "messages": [message.model_dump(mode="json") for message in messages],
            "tools": list(tool_schemas),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return ApproximateTokenCounter().count_text(serialized)


def _compact_initial_message(message: Message) -> Message:
    try:
        payload = json.loads(message.content or "{}")
    except json.JSONDecodeError:
        return _minimal_initial_message(message)
    if not isinstance(payload, dict):
        return _minimal_initial_message(message)
    if message.role == "system":
        compact = {
            "role": payload.get("role", "coding_agent"),
            "protocol": {
                "native_tools": "preferred",
                "textual_json": "fallback_only",
            },
            "budgets": payload.get("budgets"),
            "completion": payload.get("completion"),
            "execution_boundary": payload.get("execution_boundary"),
            "compacted": True,
        }
    else:
        context = payload.get("initial_context")
        compact_context: dict[str, object] = {"compacted": True}
        if isinstance(context, dict):
            compact_context.update(
                {
                    "repo_map": context.get("repo_map"),
                    "instructions": context.get("instructions"),
                    "visible_test_commands": context.get("visible_test_commands"),
                }
            )
        compact = {
            "task": payload.get("task"),
            "planning_enabled": payload.get("planning_enabled"),
            "task_verification_commands": payload.get("task_verification_commands"),
            "regression_commands": payload.get("regression_commands"),
            "initial_context": compact_context,
        }
    return message.model_copy(
        update={
            "content": json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        }
    )


def _minimal_initial_message(message: Message) -> Message:
    try:
        payload = json.loads(message.content or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    compact = (
        {
            "role": "coding_agent",
            "protocol": "native_tools_preferred_text_fallback",
            "compacted": True,
        }
        if message.role == "system"
        else {
            "task": payload.get("task"),
            "task_verification_commands": payload.get("task_verification_commands"),
            "compacted": True,
        }
    )
    return message.model_copy(
        update={
            "content": json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        }
    )


def _atomic_conversation_groups(messages: list[Message]) -> list[list[Message]]:
    groups: list[list[Message]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.role == "assistant" and message.tool_calls:
            group = [message]
            expected = {
                call.provider_call_id
                for call in message.tool_calls
                if call.provider_call_id is not None
            }
            index += 1
            while index < len(messages) and messages[index].role == "tool":
                tool_message = messages[index]
                if expected and tool_message.provider_call_id not in expected:
                    break
                group.append(tool_message)
                index += 1
            groups.append(group)
            continue
        if message.role == "tool" and message.provider_call_id is not None:
            # Never retain an orphaned native tool result.
            index += 1
            continue
        groups.append([message])
        index += 1
    return groups


def durable_recent_messages(
    messages: list[Message],
    *,
    maximum: int = 24,
) -> tuple[Message, ...]:
    """Return a bounded durable tail without splitting native turn groups."""

    selected: list[list[Message]] = []
    count = 0
    for group in reversed(_atomic_conversation_groups(messages)):
        if selected and count + len(group) > maximum:
            break
        selected.insert(0, group)
        count += len(group)
    return tuple(item for group in selected for item in group)


def _canonicalize_conversation(messages: list[Message]) -> list[Message]:
    canonical: list[Message] = []
    for message in messages:
        if message.role != "assistant":
            canonical.append(message)
            continue
        if message.tool_calls:
            # Native assistant calls are already structured and carry the
            # durable provider/runtime correlation mapping.
            canonical.append(message)
            continue
        try:
            payload = json.loads(message.content or "")
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            canonical.append(
                message.model_copy(
                    update={
                        "content": json.dumps(
                            payload,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    }
                )
            )
    return canonical


def _structured_context_message(
    messages: list[Message],
    evidence: RuntimeEvidence | None,
) -> Message:
    read_files: set[str] = set()
    searches: set[str] = set()
    listed_paths: set[str] = set()
    git_diff_checked = False
    for message in messages:
        if message.role != "assistant":
            continue
        calls: list[tuple[str | None, dict[str, object]]] = []
        if message.tool_calls:
            calls.extend((call.name, call.arguments) for call in message.tool_calls)
        else:
            try:
                payload = json.loads(message.content or "{}")
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            for call in payload.get("tool_calls", []):
                if not isinstance(call, dict):
                    continue
                arguments = call.get("arguments")
                calls.append(
                    (
                        call.get("name") if isinstance(call.get("name"), str) else None,
                        arguments if isinstance(arguments, dict) else {},
                    )
                )
        for name, arguments in calls:
            path = arguments.get("path")
            if name == "read_file" and isinstance(path, str):
                read_files.add(path)
            elif name == "search_code":
                searches.add(
                    json.dumps(arguments, ensure_ascii=False, sort_keys=True)
                )
            elif name == "list_files" and isinstance(path, str):
                listed_paths.add(path)
            elif name == "git_diff":
                git_diff_checked = True

    latest_verification = None
    workspace_version = 0
    completion_gate = "verification_not_run"
    if evidence is not None:
        workspace_version = evidence.workspace_version
        if evidence.verification:
            latest_verification = evidence.verification[-1].model_dump(mode="json")
        completion_gate = (
            "task_verification_passed"
            if evidence.tests_passed
            else "task_verification_required"
        )
    summary = {
        "structured_context_summary": {
            "read_files": sorted(read_files),
            "searches": sorted(searches),
            "listed_paths": sorted(listed_paths),
            "workspace_version": workspace_version,
            "changed_files": list(evidence.changed_files) if evidence is not None else [],
            "latest_verification": latest_verification,
            "git_diff_checked": (
                evidence.git_diff_checked if evidence is not None else git_diff_checked
            ),
            "remaining_completion_gate": completion_gate,
        }
    }
    return Message(
        role="user",
        content=json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
    )


def _paired_event_duration_ms(events, start_type, end_type) -> int:
    started: list[float] = []
    total = 0.0
    for event in events:
        if event.event_type is start_type:
            started.append(event.timestamp)
        elif event.event_type is end_type and started:
            total += max(0.0, event.timestamp - started.pop(0))
    return int(total * 1000)
