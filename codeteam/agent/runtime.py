from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from codeteam.agent.completion import CompletionGate
from codeteam.agent.initial_context import InitialContextSnapshot
from codeteam.agent.progress import ProgressPolicy, ProgressTracker
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
from codeteam.sandbox.environment_inspection import (
    DockerEnvironmentInspector,
    EnvironmentInspector,
)
from codeteam.sandbox.models import SandboxProfile
from codeteam.sandbox.preflight import DockerSandboxPreflight, SandboxPreflight
from codeteam.sandbox.verification_preflight import (
    DockerVerificationEnvironmentPreflight,
    VerificationEnvironmentPreflight,
    VerificationEnvironmentRequirement,
)
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
        verification_preflight: VerificationEnvironmentPreflight | None = None,
        sandbox_profile: SandboxProfile | None = None,
        environment_inspector: EnvironmentInspector | None = None,
    ) -> None:
        self._model_client = model_client
        self._safe_execution = safe_execution or SafeExecutionService()
        self._context_service = context_service or ContextApplicationService()
        self._state_callback = state_callback
        self._operation_callback = operation_callback
        self._sandbox_profile = sandbox_profile or SandboxProfile()
        self._environment_inspector = (
            environment_inspector
            or DockerEnvironmentInspector(
                profile=self._sandbox_profile.model_copy(
                    update={"workspace_write": False}
                )
            )
        )
        preflight_profile = self._sandbox_profile.model_copy(
            update={"workspace_write": False}
        )
        self._sandbox_preflight = sandbox_preflight or DockerSandboxPreflight(
            profile=preflight_profile
        )
        self._verification_preflight = (
            verification_preflight
            or DockerVerificationEnvironmentPreflight(profile=preflight_profile)
        )

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
        required_verification_commands = tuple(
            dict.fromkeys(
                (
                    *(request.task_verification_commands or ()),
                    *request.verification_commands,
                )
            )
        )
        verification_preflight = self._verification_preflight.check(
            root,
            VerificationEnvironmentRequirement.from_commands(
                required_verification_commands
            ),
        )
        if not verification_preflight.available:
            return CodingAgentRunResult(
                task_id=request.task_id,
                status=RuntimeStatus.PAUSED,
                summary="Verification environment is unavailable.",
                workspace_root=root,
                failure_category="verification_environment_failed",
                error=verification_preflight.error,
                sandbox_preflight_available=True,
                verification_preflight_available=False,
                verification_preflight_category=verification_preflight.category,
                verification_environment=verification_preflight.metadata,
                events=(
                    AgentEventType.SANDBOX_PREFLIGHT_STARTED.value,
                    AgentEventType.SANDBOX_PREFLIGHT_PASSED.value,
                    AgentEventType.VERIFICATION_PREFLIGHT_STARTED.value,
                    AgentEventType.VERIFICATION_PREFLIGHT_FAILED.value,
                ),
            )
        checkpoint_root = request.checkpoint_state_root or (
            root.parent / ".codeteam" / "checkpoints" / request.task_id
        )
        current_fingerprint = GitWorkspace(root).content_fingerprint()[0]
        restoring = bool(
            request.initial_messages
            or request.initial_workspace_version
            or request.initial_verification
            or request.initial_workspace_fingerprint
        )
        resume_matches = (
            request.initial_workspace_fingerprint is not None
            and request.initial_workspace_fingerprint == current_fingerprint
        )
        evidence = RuntimeEvidence(
            workspace_version=(
                request.initial_workspace_version
                if not restoring or resume_matches
                else request.initial_workspace_version + 1
            ),
            verification=list(request.initial_verification),
            git_diff_checked=(
                resume_matches
                and request.initial_git_diff_checked_version
                == request.initial_workspace_version
            ),
            git_diff_checked_version=(
                request.initial_git_diff_checked_version if resume_matches else None
            ),
            workspace_fingerprint=current_fingerprint,
            workspace_hygiene_clean=(
                request.initial_workspace_hygiene_clean if resume_matches else True
            ),
        )
        progress = _progress_tracker_from_request(request, evidence.workspace_version)
        allowed_verification_commands = tuple(
            dict.fromkeys(
                (*request.task_verification_commands, *request.verification_commands)
            )
        )

        def completion_decision():
            workspace = GitWorkspace(root)
            changed_files = tuple(change.path for change in workspace.changed_files())
            diff = render_workspace_diff(root) if changed_files else ""
            decision = CompletionGate.evaluate(
                evidence,
                changed_files=changed_files,
                diff=diff,
            )
            evidence.completion_ready_seen |= decision.ready
            return decision

        restored_messages = _canonicalize_conversation(list(request.initial_messages))
        if restored_messages:
            messages = restored_messages
            initial_snapshot = None
        else:
            messages, initial_snapshot = self._initial_messages(
                request, [], workspace_version=evidence.workspace_version
            )

        tools = create_runtime_tools(
            workspace_root=root,
            task_id=request.task_id,
            checkpoint_state_root=checkpoint_root,
            safe_execution=self._safe_execution,
            evidence=evidence,
            sandbox_profile=self._sandbox_profile,
            allowed_verification_commands=allowed_verification_commands,
            required_verification_commands=required_verification_commands,
            task_verification_commands=(
                request.task_verification_commands or request.verification_commands
            ),
            regression_verification_commands=(
                request.verification_commands
                if request.task_verification_commands
                else ()
            ),
            completion_gate_provider=completion_decision,
            environment_inspector=self._environment_inspector,
            initial_context_snapshot=initial_snapshot,
            max_repairs=request.max_repairs,
        )
        if not restored_messages:
            messages = _with_tool_schemas(messages, tools.describe())

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

        def observe_tool_result(
            state, call, result, workspace_version, cached, batch_complete
        ) -> None:
            del cached
            cache_hit, reference_hit = InitialContextSnapshot.result_flags(
                result.content if result.success else ""
            )
            if _initial_context_reuse_for_call(
                initial_snapshot, call, workspace_version
            ):
                cache_hit = True
                reference_hit = bool(
                    initial_snapshot is not None
                    and initial_snapshot.visible_in_current_request
                )
            evidence_key = hashlib.sha256(
                json.dumps(
                    {
                        "name": call.name,
                        "arguments": normalize_runtime_action(
                            call.name, call.arguments
                        ),
                        "success": result.success,
                        "content": result.content,
                        "error": result.error,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()[:16]
            decision = completion_decision()
            progress.observe_tool_result(
                step=state.step_count,
                tool_call_count=state.tool_call_count,
                tool_name=call.name,
                success=result.success,
                workspace_version=workspace_version,
                evidence_key=f"{call.name}:{evidence_key}",
                completion_ready=decision.ready,
                initial_context_cache_hit=cache_hit,
                initial_context_reference_hit=reference_hit,
            )
            if progress.paused_reason is not None and batch_complete:
                evidence.paused_category = "no_source_progress"
                evidence.paused_reason = progress.paused_reason
            evidence.progress_metrics = _progress_metrics(progress)

        def progress_advisory(state: AgentLoopState) -> Message | None:
            advisory = progress.advisory_for_request(
                step=state.step_count,
                tool_call_count=state.tool_call_count,
                completion_ready=completion_decision().ready,
            )
            evidence.progress_metrics = _progress_metrics(progress)
            return advisory

        def fingerprint_action(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            normalized = normalize_runtime_action(name, arguments)
            if initial_snapshot is not None and _initial_context_reuse_for_arguments(
                initial_snapshot,
                name,
                arguments,
                evidence.workspace_version,
            ):
                normalized["_initial_context_visibility"] = (
                    "visible"
                    if initial_snapshot.visible_in_current_request
                    else "compacted"
                )
            return normalized

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
                initial_context_snapshot=initial_snapshot,
            ),
            state_version_provider=lambda: evidence.workspace_version,
            action_fingerprint_normalizer=fingerprint_action,
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
            completion_gate_provider=completion_decision,
            terminal_completion_provider=(lambda: evidence.accepted_submission_summary),
            post_ready_tool_call_callback=(
                lambda: setattr(
                    evidence,
                    "post_ready_tool_calls",
                    evidence.post_ready_tool_calls + 1,
                )
            ),
            request_advisory_provider=progress_advisory,
            tool_result_observer=observe_tool_result,
            cached_no_progress_exempt_provider=(
                lambda call, workspace_version: _initial_context_reuse_for_call(
                    initial_snapshot, call, workspace_version
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
        if initial_snapshot is not None:
            progress.initial_context_cache_hit_count = max(
                progress.initial_context_cache_hit_count,
                initial_snapshot.cache_hit_count,
            )
            progress.initial_context_reference_hit_count = max(
                progress.initial_context_reference_hit_count,
                initial_snapshot.reference_hit_count,
            )
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
            verification_preflight_available=True,
            verification_preflight_category=verification_preflight.category,
            verification_environment=verification_preflight.metadata,
            messages=tuple(loop.messages),
            model_outputs=tuple(loop.model_outputs),
            events=(
                AgentEventType.SANDBOX_PREFLIGHT_STARTED.value,
                AgentEventType.SANDBOX_PREFLIGHT_PASSED.value,
                AgentEventType.VERIFICATION_PREFLIGHT_STARTED.value,
                AgentEventType.VERIFICATION_PREFLIGHT_PASSED.value,
                *(event.event_type.value for event in loop.events),
            ),
            workspace_version=evidence.workspace_version,
            workspace_fingerprint=evidence.workspace_fingerprint,
            git_diff_checked_version=evidence.git_diff_checked_version,
            workspace_hygiene_clean=evidence.workspace_hygiene_clean,
            completion_ready=evidence.completion_ready_seen,
            post_ready_tool_calls=evidence.post_ready_tool_calls,
            verification_workspace_mutations=(
                evidence.verification_workspace_mutations
            ),
            first_patch_step=progress.first_patch_step,
            pre_edit_step_count=progress.pre_edit_step_count,
            pre_edit_tool_call_count=progress.pre_edit_tool_call_count,
            progress_advisory_count=progress.progress_advisory_count,
            progress_advisory_level_counts=progress.progress_advisory_level_counts,
            no_source_progress_pause_count=progress.no_source_progress_pause_count,
            max_no_source_progress_streak=progress.max_no_source_progress_streak,
            environment_inspection_count=progress.environment_inspection_count,
            initial_context_cache_hit_count=progress.initial_context_cache_hit_count,
            initial_context_reference_hit_count=(
                progress.initial_context_reference_hit_count
            ),
            source_progress_count=progress.source_progress_count,
            diagnostic_progress_count=progress.diagnostic_progress_count,
            first_environment_inspection_step=(
                progress.first_environment_inspection_step
            ),
        )

    def _initial_messages(
        self,
        request: CodingAgentRunRequest,
        schemas: list[dict[str, object]],
        *,
        workspace_version: int,
    ) -> tuple[list[Message], InitialContextSnapshot]:
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
            "visible_test_commands": [
                item.model_dump(mode="json") for item in context.test_commands
            ],
            "diagnostics": context.diagnostics,
        }
        snapshot = InitialContextSnapshot.from_context_report(
            context, workspace_version=workspace_version
        )
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
                "completion_tool": {
                    "name": "submit_result",
                    "arguments": {
                        "summary": "short factual summary",
                        "notes": None,
                    },
                    "rule": "Call submit_result alone; only the Runtime may accept completion.",
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
                (
                    "After the Runtime reports completion-ready, call submit_result "
                    "as the sole tool call. Readiness does not auto-terminate the run."
                ),
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
            "verification_command_priority": (
                "Task-specific verification commands supplied by the Runtime are "
                "authoritative for completion. Repository-discovered commands are "
                "general guidance and are not substitutes unless the Runtime lists "
                "them as visible verification commands."
            ),
        }
        user = {
            "task": request.task,
            "workspace": str(request.workspace_root),
            "planning_enabled": request.planning_enabled,
            "task_verification_commands": [
                list(command)
                for command in (
                    request.task_verification_commands or request.verification_commands
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
        ], snapshot

    @staticmethod
    def _finalize(loop, evidence, changed_files, diff):
        if evidence.paused_reason:
            return (
                RuntimeStatus.PAUSED,
                evidence.paused_category or "execution_paused",
                evidence.paused_reason,
            )
        if loop.stop_reason is StopReason.PROVIDER_ERROR:
            return RuntimeStatus.FAILED, "provider_blocked", loop.error
        if loop.stop_reason is StopReason.INTERNAL_ERROR:
            return RuntimeStatus.FAILED, "internal_failure", loop.error
        if loop.status is CompletionStatus.NEEDS_USER_INPUT:
            return RuntimeStatus.PAUSED, "user_input_required", loop.error
        if loop.status is not CompletionStatus.COMPLETED:
            return RuntimeStatus.FAILED, loop.stop_reason.value, loop.error
        decision = CompletionGate.evaluate(
            evidence,
            changed_files=changed_files,
            diff=diff,
        )
        if not decision.ready:
            missing = ", ".join(decision.missing_requirements)
            if "real_git_diff" in decision.missing_requirements:
                return (
                    RuntimeStatus.FAILED,
                    "no_patch",
                    "Completion requires a real Git diff.",
                )
            if "safe_git_diff" in decision.missing_requirements:
                return (
                    RuntimeStatus.FAILED,
                    "security_failure",
                    "Final diff touches Git metadata.",
                )
            if "workspace_hygiene_clean" in decision.missing_requirements:
                return RuntimeStatus.PAUSED, "workspace_hygiene_failed", missing
            if "current_version_verification" in decision.missing_requirements:
                return RuntimeStatus.PAUSED, "verification_required", missing
            return RuntimeStatus.PAUSED, "diff_review_required", missing
        return RuntimeStatus.COMPLETED, None, None


def _message_transform(
    mode: CompactionMode,
    context_budget: int,
    evidence: RuntimeEvidence | None = None,
    *,
    tool_schemas: tuple[dict[str, object], ...] = (),
    initial_context_snapshot: InitialContextSnapshot | None = None,
) -> Callable[[list[Message]], list[Message]]:
    def transform(messages: list[Message]) -> list[Message]:
        messages = _canonicalize_conversation(messages)
        if mode is CompactionMode.NONE:
            if initial_context_snapshot is not None:
                initial_context_snapshot.set_request_visibility(True)
            return messages
        if _conversation_tokens(messages, tool_schemas) <= context_budget:
            if initial_context_snapshot is not None:
                initial_context_snapshot.set_request_visibility(True)
            return messages
        if initial_context_snapshot is not None:
            initial_context_snapshot.set_request_visibility(False)

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


def _with_tool_schemas(
    messages: list[Message], schemas: list[dict[str, object]]
) -> list[Message]:
    if not messages:
        return messages
    try:
        payload = json.loads(messages[0].content or "{}")
    except json.JSONDecodeError:
        return messages
    if not isinstance(payload, dict):
        return messages
    payload["tools"] = schemas
    return [
        messages[0].model_copy(
            update={"content": json.dumps(payload, ensure_ascii=False)}
        ),
        *messages[1:],
    ]


def _progress_tracker_from_request(
    request: CodingAgentRunRequest, workspace_version: int
) -> ProgressTracker:
    metrics = request.initial_progress_metrics

    def integer(name: str) -> int:
        value = metrics.get(name, 0)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    first_patch = metrics.get("first_patch_step")
    first_environment = metrics.get("first_environment_inspection_step")
    levels = metrics.get("progress_advisory_level_counts", {})
    return ProgressTracker(
        policy=ProgressPolicy(max_steps=request.max_steps),
        workspace_version=workspace_version,
        first_patch_step=(
            first_patch if isinstance(first_patch, int) and first_patch > 0 else None
        ),
        pre_edit_step_count=integer("pre_edit_step_count"),
        pre_edit_tool_call_count=integer("pre_edit_tool_call_count"),
        progress_advisory_count=integer("progress_advisory_count"),
        progress_advisory_level_counts=(
            {
                str(key): int(value)
                for key, value in levels.items()
                if isinstance(value, int)
            }
            if isinstance(levels, dict)
            else {}
        ),
        no_source_progress_pause_count=integer("no_source_progress_pause_count"),
        max_no_source_progress_streak=integer("max_no_source_progress_streak"),
        environment_inspection_count=integer("environment_inspection_count"),
        initial_context_cache_hit_count=integer("initial_context_cache_hit_count"),
        initial_context_reference_hit_count=integer(
            "initial_context_reference_hit_count"
        ),
        source_progress_count=integer("source_progress_count"),
        diagnostic_progress_count=integer("diagnostic_progress_count"),
        first_environment_inspection_step=(
            first_environment
            if isinstance(first_environment, int) and first_environment > 0
            else None
        ),
    )


def _progress_metrics(progress: ProgressTracker) -> dict[str, object]:
    return {
        "first_patch_step": progress.first_patch_step,
        "pre_edit_step_count": progress.pre_edit_step_count,
        "pre_edit_tool_call_count": progress.pre_edit_tool_call_count,
        "progress_advisory_count": progress.progress_advisory_count,
        "progress_advisory_level_counts": dict(progress.progress_advisory_level_counts),
        "no_source_progress_pause_count": progress.no_source_progress_pause_count,
        "max_no_source_progress_streak": progress.max_no_source_progress_streak,
        "environment_inspection_count": progress.environment_inspection_count,
        "initial_context_cache_hit_count": progress.initial_context_cache_hit_count,
        "initial_context_reference_hit_count": (
            progress.initial_context_reference_hit_count
        ),
        "source_progress_count": progress.source_progress_count,
        "diagnostic_progress_count": progress.diagnostic_progress_count,
        "first_environment_inspection_step": (
            progress.first_environment_inspection_step
        ),
    }


def _initial_context_reuse_for_call(
    snapshot: InitialContextSnapshot | None,
    call,
    workspace_version: int,
) -> bool:
    return _initial_context_reuse_for_arguments(
        snapshot, call.name, call.arguments, workspace_version
    )


def _initial_context_reuse_for_arguments(
    snapshot: InitialContextSnapshot | None,
    name: str,
    arguments: dict[str, Any],
    workspace_version: int,
) -> bool:
    if snapshot is None or name != "read_file":
        return False
    path = arguments.get("path")
    if not isinstance(path, str):
        return False
    if arguments.get("start_line") is not None:
        return False
    if arguments.get("end_line") is not None:
        return False
    return snapshot.reusable_file(path, workspace_version) is not None


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
                searches.add(json.dumps(arguments, ensure_ascii=False, sort_keys=True))
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
            "changed_files": list(evidence.changed_files)
            if evidence is not None
            else [],
            "latest_verification": latest_verification,
            "git_diff_checked": (
                evidence.git_diff_checked_version == evidence.workspace_version
                if evidence is not None
                else git_diff_checked
            ),
            "git_diff_checked_version": (
                evidence.git_diff_checked_version if evidence is not None else None
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
