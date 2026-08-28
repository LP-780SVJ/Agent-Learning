import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from codeteam.agent.protocol import (
    ModelOutputDialect,
    ModelOutputNormalizationError,
    normalize_model_output,
)
from codeteam.agent.runtime_models import ModelOutputEvidence
from codeteam.events import AgentEvent, AgentEventType, make_event
from codeteam.limits import AgentLoopLimits, check_step_limit, check_tool_call_limit
from codeteam.llm.base import (
    LegacyModelClient,
    ModelClient,
    ModelFinishState,
    ModelRequest,
    ModelResponse,
    ModelResponseMode,
    ModelTurn,
    ModelUsage,
)
from codeteam.schemas.final_output import (
    AgentFinalOutput,
    CompletionStatus,
    validate_final_output_semantics,
)
from codeteam.schemas.messages import Message
from codeteam.schemas.tool_calls import ToolCall, ToolResult
from codeteam.state import (
    AgentLoopState,
    StopReason,
    is_repeated_action,
    make_action_fingerprint,
    record_tool_call,
)
from codeteam.tools.registry import ToolRegistry
from codeteam.usage.tracker import UsageTracker

"""
MockModelClient 返回两种 JSON 格式：
1. 最终输出的 JSON
{
  "status": "completed",
  "summary": "done",
  "tests_passed": true,
  "error": null,
  "user_input_request": null
}

2. 工具调用的 JSON
{
  "tool_calls": [
    {
      "call_id": "call-1",
      "name": "calculator",
      "arguments": {
        "operation": "add",
        "left": 1,
        "right": 2
      }
    }
  ]
}
"""


@dataclass
class AgentLoopResult:
    status: CompletionStatus
    stop_reason: StopReason
    messages: list[Message] = field(default_factory=list)
    final_output: AgentFinalOutput | None = None
    error: str | None = None
    steps_used: int = 0
    tool_calls_used: int = 0
    protocol_repairs_used: int = 0
    protocol_repair_streak: int = 0
    model_outputs: list[ModelOutputEvidence] = field(default_factory=list)

    events: list[AgentEvent] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0.0
    duration_seconds: float = 0.0


@dataclass
class ParsedModelOutput:
    """Internal result for one model response after JSON and schema checks."""

    tool_calls: list[ToolCall] | None = None
    final_output: AgentFinalOutput | None = None
    stop_reason: StopReason | None = None
    error: str | None = None
    dialect: ModelOutputDialect | None = None
    canonical_payload: dict[str, object] | None = None


def run_agent_loop(
    model_client: ModelClient | LegacyModelClient,
    tool_registry: ToolRegistry,
    messages: list[Message],
    limits: AgentLoopLimits | None = None,
    actual_tests_passed: bool | Callable[[], bool] | None = None,
    message_transform: Callable[[list[Message]], list[Message]] | None = None,
    state_version_provider: Callable[[], int] | None = None,
    action_fingerprint_normalizer: Callable[
        [str, dict[str, Any]], dict[str, Any]
    ] | None = None,
    semantic_repeat_tools: frozenset[str] = frozenset(),
    cacheable_tools: frozenset[str] = frozenset(),
    initial_protocol_repair_streak: int = 0,
    state_callback: Callable[[AgentLoopState], None] | None = None,
    lifecycle_callback: Callable[
        [str, AgentLoopState, dict[str, Any]], None
    ] | None = None,
    halt_signal_provider: Callable[[], tuple[StopReason, str] | None] | None = None,
    max_output_tokens: int = 4096,
    max_input_tokens: int = 4096,
    model_context_window: int = 32768,
    safety_headroom_tokens: int = 1024,
    native_tools: bool = True,
    reasoning_enabled: bool | None = False,
) -> AgentLoopResult:
    if limits is None:
        limits = AgentLoopLimits()

    state = AgentLoopState(
        messages=list(messages),
        protocol_repair_streak=initial_protocol_repair_streak,
    )
    start_time = time.monotonic()
    usage_tracker = UsageTracker()
    events: list[AgentEvent] = []

    while True:
        if check_step_limit(state, limits):
            return _stop_with_failure(
                state,
                StopReason.MAX_STEPS,
                "Agent stopped because max_steps was reached.",
                start_time,
                usage_tracker,
                events,
            )

        state.step_count += 1

        events.append(make_event(
            AgentEventType.STEP_STARTED,
            "Agent step started.",
            step_index=state.step_count,
        ))

        events.append(make_event(
            AgentEventType.MODEL_REQUEST,
            "Sending messages to model.",
            step_index=state.step_count,
            data={"message_count": len(state.messages)},
        ))

        request_messages = (
            message_transform(list(state.messages))
            if message_transform is not None
            else list(state.messages)
        )
        if lifecycle_callback is not None:
            lifecycle_callback(
                "model.started",
                state,
                {"step_index": state.step_count},
            )
        try:
            model_request = ModelRequest(
                messages=tuple(request_messages),
                tools=tuple(tool_registry.describe()),
                max_output_tokens=max_output_tokens,
                max_input_tokens=max_input_tokens,
                model_context_window=model_context_window,
                safety_headroom_tokens=safety_headroom_tokens,
                native_tools=native_tools,
                reasoning_enabled=reasoning_enabled,
            )
            model_turn = _request_model_turn(model_client, model_request)
        except Exception as error:  # noqa: BLE001
            if lifecycle_callback is not None:
                lifecycle_callback(
                    "model.completed",
                    state,
                    {
                        "step_index": state.step_count,
                        "success": False,
                        "error_type": type(error).__name__,
                    },
                )
            stop_reason = (
                StopReason.PROVIDER_ERROR
                if _is_provider_error(error)
                else StopReason.INTERNAL_ERROR
            )
            return _stop_with_failure(
                state,
                stop_reason,
                (
                    f"Model provider failed: {error}"
                    if stop_reason is StopReason.PROVIDER_ERROR
                    else f"Model client failed internally: {error}"
                ),
                start_time,
                usage_tracker,
                events,
            )
        usage_record = usage_tracker.record_step(
            step_index=state.step_count,
            model=model_turn.model,
            input_tokens=model_turn.usage.input_tokens,
            output_tokens=model_turn.usage.output_tokens,
        )
        if lifecycle_callback is not None:
            lifecycle_callback(
                "model.completed",
                state,
                {"step_index": state.step_count},
            )

        events.append(make_event(
            AgentEventType.MODEL_RESPONSE,
            "Model response received.",
            step_index=state.step_count,
            data={
                "model": model_turn.model,
                "provider": model_turn.provider,
                "finish_state": model_turn.finish_state.value,
                "finish_reason": model_turn.finish_reason,
                "actual_response_mode": (
                    model_turn.actual_response_mode.value
                    if model_turn.actual_response_mode is not None
                    else None
                ),
                "input_tokens": model_turn.usage.input_tokens,
                "output_tokens": model_turn.usage.output_tokens,
                "cost": usage_record.cost.total_cost,
            },
        ))

        native_tool_calls = _assign_runtime_call_ids(
            model_turn.tool_calls,
            call_id_prefix=f"step-{state.step_count}",
        )
        early_stop = _stop_reason_for_turn(model_turn)
        if native_tool_calls and early_stop is None:
            canonical_payload: dict[str, object] | None = {
                "tool_calls": [
                    {
                        "name": call.name,
                        "arguments": call.arguments,
                        "runtime_call_id": call.call_id,
                        "provider_call_id": call.provider_call_id,
                    }
                    for call in native_tool_calls
                ]
            }
            parsed_output = ParsedModelOutput(
                tool_calls=native_tool_calls,
                canonical_payload=canonical_payload,
            )
        elif early_stop is None:
            tests_passed = (
                actual_tests_passed()
                if callable(actual_tests_passed)
                else actual_tests_passed
            )
            parsed_output = _parse_model_output(
                model_turn.text or "",
                actual_tests_passed=tests_passed,
                call_id_prefix=f"step-{state.step_count}",
            )
            canonical_payload = parsed_output.canonical_payload
        else:
            parsed_output = ParsedModelOutput(
                stop_reason=early_stop,
                error=model_turn.incomplete_reason or _turn_failure_message(model_turn),
            )
            canonical_payload = None

        state.model_outputs.append(
            ModelOutputEvidence(
                step=state.step_count,
                raw_content=model_turn.text,
                native_tool_calls=tuple(native_tool_calls),
                dialect=(
                    parsed_output.dialect.value
                    if parsed_output.dialect is not None
                    else None
                ),
                canonical_payload=canonical_payload,
                parse_error=(
                    parsed_output.error
                    if parsed_output.stop_reason is not None
                    else None
                ),
                model=model_turn.model,
                provider=model_turn.provider,
                response_id=model_turn.response_id,
                finish_state=model_turn.finish_state,
                finish_reason=model_turn.finish_reason,
                actual_response_mode=model_turn.actual_response_mode,
                incomplete_reason=model_turn.incomplete_reason,
                system_fingerprint=model_turn.system_fingerprint,
                input_tokens=model_turn.usage.input_tokens,
                output_tokens=model_turn.usage.output_tokens,
            )
        )

        if parsed_output.stop_reason is None:
            state.protocol_repair_streak = 0
            if native_tool_calls and early_stop is None:
                state.messages.append(
                    Message(
                        role="assistant",
                        content=model_turn.text,
                        tool_calls=native_tool_calls,
                    )
                )
            else:
                state.messages.append(
                    Message(
                        role="assistant",
                        content=json.dumps(
                            parsed_output.canonical_payload,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    )
                )
        if state_callback is not None:
            state_callback(state)

        if parsed_output.stop_reason is not None:
            if (
                parsed_output.stop_reason is StopReason.INVALID_FINAL_OUTPUT
                and state.protocol_repair_streak < limits.max_protocol_repairs
                and state.step_count < limits.max_steps
            ):
                state.protocol_repair_count += 1
                state.protocol_repair_streak += 1
                state.messages.append(
                    _protocol_repair_message(
                        parsed_output.error or "Invalid model output.",
                        attempt=state.protocol_repair_streak,
                        maximum=limits.max_protocol_repairs,
                    )
                )
                events.append(
                    make_event(
                        AgentEventType.PROTOCOL_REPAIR_REQUESTED,
                        "Model output protocol repair requested.",
                        step_index=state.step_count,
                        data={
                            "attempt": state.protocol_repair_count,
                            "streak": state.protocol_repair_streak,
                            "maximum": limits.max_protocol_repairs,
                            "error": parsed_output.error,
                        },
                    )
                )
                if state_callback is not None:
                    state_callback(state)
                continue
            return _stop_with_failure(
                state,
                parsed_output.stop_reason,
                parsed_output.error or "Model output could not be handled.",
                start_time,
                usage_tracker,
                events,
            )

        if parsed_output.tool_calls is not None:
            stop_result = _handle_tool_calls(
                state,
                parsed_output.tool_calls,
                tool_registry,
                limits,
                start_time,
                usage_tracker,
                events,
                state_version_provider=state_version_provider,
                action_fingerprint_normalizer=action_fingerprint_normalizer,
                semantic_repeat_tools=semantic_repeat_tools,
                cacheable_tools=cacheable_tools,
                state_callback=state_callback,
                lifecycle_callback=lifecycle_callback,
                halt_signal_provider=halt_signal_provider,
            )
            if stop_result is not None:
                return stop_result
            continue

        if parsed_output.final_output is not None:
            return _handle_final_output(
                state,
                parsed_output.final_output,
                start_time,
                usage_tracker,
                events,
            )

        return _stop_with_failure(
            state,
            StopReason.NO_PROGRESS,
            "Model produced neither tool calls nor final output.",
            start_time,
            usage_tracker,
            events,
        )


def _parse_model_output(
    raw_output: str,
    actual_tests_passed: bool | None = None,
    call_id_prefix: str = "step-0",
) -> ParsedModelOutput:
    try:
        normalized = normalize_model_output(raw_output)
        parsed = normalized.payload
    except ModelOutputNormalizationError as error:
        return ParsedModelOutput(
            stop_reason=StopReason.INVALID_FINAL_OUTPUT,
            error=str(error),
        )

    if "tool_calls" in parsed:
        tool_calls_data = parsed["tool_calls"]
        # An empty tool call list gives the loop nothing to execute or finalize.
        if not tool_calls_data:
            return ParsedModelOutput(
                stop_reason=StopReason.NO_PROGRESS,
                error="Model produced an empty tool_calls list.",
            )
        if not isinstance(tool_calls_data, list):
            return ParsedModelOutput(
                stop_reason=StopReason.INVALID_FINAL_OUTPUT,
                error="tool_calls must be a list.",
            )
        if not all(isinstance(item, dict) for item in tool_calls_data):
            return ParsedModelOutput(
                stop_reason=StopReason.INVALID_FINAL_OUTPUT,
                error="Each tool call must be a JSON object.",
            )

        try:
            tool_calls = [
                ToolCall.model_validate(
                    {
                        **item,
                        "call_id": f"{call_id_prefix}-call-{index}",
                    }
                )
                for index, item in enumerate(tool_calls_data, start=1)
            ]
        except ValidationError as error:
            return ParsedModelOutput(
                stop_reason=StopReason.INVALID_FINAL_OUTPUT,
                error=f"Tool call validation failed: {error}",
            )
        return ParsedModelOutput(
            tool_calls=tool_calls,
            dialect=normalized.dialect,
            canonical_payload={
                "tool_calls": [
                    {
                        "name": call.name,
                        "arguments": call.arguments,
                    }
                    for call in tool_calls
                ]
            },
        )

    if "status" not in parsed:
        return ParsedModelOutput(
            stop_reason=StopReason.NO_PROGRESS,
            error="Model produced neither tool calls nor final output.",
        )

    try:
        final_output = AgentFinalOutput.model_validate(parsed)
        final_output = validate_final_output_semantics(
            final_output,
            actual_tests_passed=actual_tests_passed,
        )
    except (ValidationError, ValueError) as error:
        return ParsedModelOutput(
            stop_reason=StopReason.INVALID_FINAL_OUTPUT,
            error=f"Final output validation failed: {error}",
        )

    return ParsedModelOutput(
        final_output=final_output,
        dialect=normalized.dialect,
        canonical_payload=final_output.model_dump(mode="json"),
    )


def _protocol_repair_message(error: str, *, attempt: int, maximum: int) -> Message:
    payload = {
        "protocol_repair": {
            "attempt": attempt,
            "maximum": maximum,
            "error": error,
            "requirement": (
                "Return exactly one raw JSON object with no prose, Markdown fence, "
                "or provider-specific tags. The Runtime assigns call_id."
            ),
            "tool_call_example": {
                "tool_calls": [
                    {
                        "name": "read_file",
                        "arguments": {"path": "src/example.py"},
                    }
                ]
            },
            "final_output_example": {
                "status": "completed",
                "summary": "Implemented and verified the requested change.",
                "tests_passed": True,
                "error": None,
                "user_input_request": None,
            },
        }
    }
    return Message(role="user", content=json.dumps(payload, ensure_ascii=False))


def _handle_final_output(
        state: AgentLoopState,
        final_output: AgentFinalOutput,
        start_time: float,
        usage_tracker: UsageTracker,
        events: list[AgentEvent],
) -> AgentLoopResult:
    if final_output.status == CompletionStatus.COMPLETED:
        stop_reason = StopReason.COMPLETED
    elif final_output.status == CompletionStatus.FAILED:
        stop_reason = StopReason.FAILED
    else:
        stop_reason = StopReason.PAUSED

    return _build_loop_result(
        state=state,
        status=final_output.status,
        stop_reason=stop_reason,
        start_time=start_time,
        usage_tracker=usage_tracker,
        events=events,
        final_output=final_output,
        error=final_output.error,
    )


def _handle_tool_calls(
    state: AgentLoopState,
    tool_calls: list[ToolCall],
    tool_registry: ToolRegistry,
    limits: AgentLoopLimits,
    start_time: float,
    usage_tracker: UsageTracker,
    events: list[AgentEvent],
    *,
    state_version_provider: Callable[[], int] | None = None,
    action_fingerprint_normalizer: Callable[
        [str, dict[str, Any]], dict[str, Any]
    ] | None = None,
    semantic_repeat_tools: frozenset[str] = frozenset(),
    cacheable_tools: frozenset[str] = frozenset(),
    state_callback: Callable[[AgentLoopState], None] | None = None,
    lifecycle_callback: Callable[
        [str, AgentLoopState, dict[str, Any]], None
    ] | None = None,
    halt_signal_provider: Callable[[], tuple[StopReason, str] | None] | None = None,
) -> AgentLoopResult | None:
    for call in tool_calls:
        if call.call_id is None:
            return _stop_with_failure(
                state,
                StopReason.INVALID_TOOL_CALL,
                "Runtime call id was not assigned after tool-call validation.",
                start_time,
                usage_tracker,
                events,
            )
        if check_tool_call_limit(state, limits):
            return _stop_with_failure(
                state,
                StopReason.MAX_TOOL_CALLS,
                "Agent stopped because max_tool_calls was reached.",
                start_time,
                usage_tracker,
                events,
            )

        workspace_version = (
            state_version_provider() if state_version_provider is not None else 0
        )
        fingerprint_arguments = (
            action_fingerprint_normalizer(call.name, call.arguments)
            if action_fingerprint_normalizer is not None
            else call.arguments
        )
        fingerprint = make_action_fingerprint(
            call.name,
            fingerprint_arguments,
            workspace_version,
        )
        if call.name in cacheable_tools and fingerprint in state.tool_result_cache:
            cached = state.tool_result_cache[fingerprint].model_copy(
                update={
                    "call_id": call.call_id,
                    "provider_call_id": call.provider_call_id,
                }
            )
            state.cached_no_progress_count += 1
            record_tool_call(
                state,
                call.name,
                fingerprint_arguments,
                workspace_version,
            )
            state.messages.append(_tool_result_to_message(cached))
            events.append(
                make_event(
                    AgentEventType.TOOL_RESULT,
                    "Cached tool observation returned.",
                    step_index=state.step_count,
                    data={
                        "call_id": cached.call_id,
                        "provider_call_id": cached.provider_call_id,
                        "name": cached.name,
                        "success": cached.success,
                        "cached": True,
                    },
                )
            )
            if state_callback is not None:
                state_callback(state)
            if state.cached_no_progress_count >= 2:
                return _stop_with_failure(
                    state,
                    StopReason.NO_PROGRESS,
                    "Agent stopped after repeated cached exploration without workspace changes.",
                    start_time,
                    usage_tracker,
                    events,
                )
            continue

        state.cached_no_progress_count = 0
        if is_repeated_action(
            state,
            call.name,
            fingerprint_arguments,
            workspace_version,
            include_history=call.name in semantic_repeat_tools,
        ):
            return _stop_with_failure(
                state,
                StopReason.REPEATED_ACTION,
                "Agent stopped because it repeated the same tool call.",
                start_time,
                usage_tracker,
                events,
            )

        events.append(make_event(
            AgentEventType.TOOL_CALLED,
            f"Calling tool: {call.name}",
            step_index=state.step_count,
            data={
                "call_id": call.call_id,
                "provider_call_id": call.provider_call_id,
                "name": call.name,
                "arguments": call.arguments,
            },
        ))

        if lifecycle_callback is not None:
            lifecycle_callback(
                "tool.started",
                state,
                {
                    "call_id": call.call_id,
                    "provider_call_id": call.provider_call_id,
                    "tool_name": call.name,
                },
            )

        result = tool_registry.execute(call)
        if call.name in cacheable_tools:
            state.tool_result_cache[fingerprint] = result

        if lifecycle_callback is not None:
            lifecycle_callback(
                "tool.completed",
                state,
                {
                    "call_id": call.call_id,
                    "provider_call_id": call.provider_call_id,
                    "tool_name": call.name,
                    "success": result.success,
                },
            )

        events.append(make_event(
            AgentEventType.TOOL_RESULT,
            "Tool call finished.",
            step_index=state.step_count,
            data={
                "call_id": result.call_id,
                "provider_call_id": result.provider_call_id,
                "name": result.name,
                "success": result.success,
                "error": result.error,
            },
        ))
        record_tool_call(
            state,
            call.name,
            fingerprint_arguments,
            workspace_version,
        )
        state.messages.append(_tool_result_to_message(result))
        if state_callback is not None:
            state_callback(state)
        halt = halt_signal_provider() if halt_signal_provider is not None else None
        if halt is not None:
            stop_reason, error = halt
            return _stop_with_pause(
                state,
                stop_reason,
                error,
                start_time,
                usage_tracker,
                events,
            )

    return None


def _tool_result_to_message(result: ToolResult) -> Message:
    return Message(
        role="tool",
        content=result.content if result.success else result.error,
        tool_call_id=result.call_id,
        provider_call_id=result.provider_call_id,
    )


def _stop_with_failure(
    state: AgentLoopState,
    stop_reason: StopReason,
    error: str,
    start_time: float,
    usage_tracker: UsageTracker,
    events: list[AgentEvent],
) -> AgentLoopResult:
    return _build_loop_result(
        state=state,
        status=CompletionStatus.FAILED,
        stop_reason=stop_reason,
        start_time=start_time,
        usage_tracker=usage_tracker,
        events=events,
        error=error,
    )


def _stop_with_pause(
    state: AgentLoopState,
    stop_reason: StopReason,
    error: str,
    start_time: float,
    usage_tracker: UsageTracker,
    events: list[AgentEvent],
) -> AgentLoopResult:
    return _build_loop_result(
        state=state,
        status=CompletionStatus.NEEDS_USER_INPUT,
        stop_reason=stop_reason,
        start_time=start_time,
        usage_tracker=usage_tracker,
        events=events,
        error=error,
    )


def _request_model_turn(
    model_client: ModelClient | LegacyModelClient,
    request: ModelRequest,
) -> ModelTurn:
    turn_method = getattr(model_client, "turn", None)
    if callable(turn_method):
        turn = turn_method(request)
        if not isinstance(turn, ModelTurn):
            raise TypeError("ModelClient.turn() must return ModelTurn.")
        return turn

    complete_method = getattr(model_client, "complete", None)
    if not callable(complete_method):
        raise TypeError("Model client must implement turn() or legacy complete().")
    raw_response = complete_method(list(request.messages))
    if isinstance(raw_response, str):
        return ModelTurn(
            text=raw_response,
            finish_state=ModelFinishState.STOP,
            actual_response_mode=ModelResponseMode.TEXT,
            model="mock-model",
        )
    if isinstance(raw_response, ModelResponse):
        return ModelTurn(
            text=raw_response.content,
            finish_state=ModelFinishState.STOP,
            actual_response_mode=ModelResponseMode.TEXT,
            model=raw_response.model,
            usage=ModelUsage(
                input_tokens=raw_response.input_tokens,
                output_tokens=raw_response.output_tokens,
            ),
        )
    raise TypeError("Legacy model client must return str or ModelResponse.")


def _assign_runtime_call_ids(
    tool_calls: tuple[ToolCall, ...],
    *,
    call_id_prefix: str,
) -> list[ToolCall]:
    return [
        call.model_copy(update={"call_id": f"{call_id_prefix}-call-{index}"})
        for index, call in enumerate(tool_calls, start=1)
    ]


def _stop_reason_for_turn(turn: ModelTurn) -> StopReason | None:
    if turn.finish_state is ModelFinishState.OUTPUT_TRUNCATED:
        return StopReason.OUTPUT_TRUNCATED
    if turn.finish_state is ModelFinishState.CONTENT_FILTERED:
        return StopReason.CONTENT_FILTERED
    if turn.finish_state is ModelFinishState.RESOURCE_EXHAUSTED:
        return StopReason.PROVIDER_ERROR
    if turn.finish_state is ModelFinishState.INCOMPLETE:
        return StopReason.INCOMPLETE_PROVIDER_TURN
    if turn.finish_state is ModelFinishState.INVALID_TOOL_CALL:
        return StopReason.INVALID_TOOL_CALL
    return None


def _turn_failure_message(turn: ModelTurn) -> str:
    return {
        ModelFinishState.OUTPUT_TRUNCATED: "Provider output was truncated.",
        ModelFinishState.CONTENT_FILTERED: "Provider content filter stopped the turn.",
        ModelFinishState.RESOURCE_EXHAUSTED: "Provider resource failure stopped the turn.",
        ModelFinishState.INCOMPLETE: "Provider returned an incomplete empty turn.",
        ModelFinishState.INVALID_TOOL_CALL: "Provider returned malformed native tool arguments.",
    }.get(turn.finish_state, "Provider turn could not be handled.")


def _is_provider_error(error: Exception) -> bool:
    return (
        isinstance(error, (TimeoutError, OSError))
        or hasattr(error, "normalized_code")
        or (
            type(error).__name__ == "ProviderRequestError"
            and hasattr(error, "failures")
        )
    )


def _build_loop_result(
    state: AgentLoopState,
    status: CompletionStatus,
    stop_reason: StopReason,
    start_time: float,
    usage_tracker: UsageTracker,
    events: list[AgentEvent],
    final_output: AgentFinalOutput | None = None,
    error: str | None = None,
) -> AgentLoopResult:
    duration_seconds = time.monotonic() - start_time

    events.append(make_event(
        AgentEventType.LOOP_STOPPED,
        "Agent loop stopped.",
        step_index=state.step_count,
        data={
            "stop_reason": stop_reason.value,
            "total_cost": usage_tracker.total_cost(),
            "duration_seconds": duration_seconds,
        },
    ))

    return AgentLoopResult(
        status=status,
        stop_reason=stop_reason,
        messages=state.messages,
        final_output=final_output,
        error=error,
        steps_used=state.step_count,
        tool_calls_used=state.tool_call_count,
        protocol_repairs_used=state.protocol_repair_count,
        protocol_repair_streak=state.protocol_repair_streak,
        model_outputs=state.model_outputs,
        events=events,
        total_input_tokens=usage_tracker.total_input_tokens(),
        total_output_tokens=usage_tracker.total_output_tokens(),
        total_cost=usage_tracker.total_cost(),
        duration_seconds=duration_seconds,
    )
