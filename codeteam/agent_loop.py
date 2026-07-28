import json
import time

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from codeteam.limits import AgentLoopLimits, check_step_limit, check_tool_call_limit
from codeteam.events import AgentEvent, AgentEventType, make_event
from codeteam.llm.base import ModelResponse
from codeteam.schemas.final_output import (
    AgentFinalOutput,
    CompletionStatus,
    validate_final_output_semantics,
)
from codeteam.schemas.messages import Message
from codeteam.schemas.tool_calls import ToolCall, ToolResult
from codeteam.state import AgentLoopState, StopReason, is_repeated_action, record_tool_call
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


def run_agent_loop(
        model_client: Any,
        tool_registry: ToolRegistry,
        messages: list[Message],
        limits: AgentLoopLimits | None = None,
        actual_tests_passed: bool | None = None,
) -> AgentLoopResult:
    if limits is None:
        limits = AgentLoopLimits()

    state = AgentLoopState(messages=list(messages))
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

        raw_response = model_client.complete(state.messages)
        try:
            model_response = _normalize_model_response(raw_response)
        except TypeError as error:
            return _stop_with_failure(
                state,
                StopReason.INVALID_FINAL_OUTPUT,
                str(error),
                start_time,
                usage_tracker,
                events,
            )

        usage_record = usage_tracker.record_step(
            step_index=state.step_count,
            model=model_response.model,
            input_tokens=model_response.input_tokens,
            output_tokens=model_response.output_tokens,
        )

        events.append(make_event(
            AgentEventType.MODEL_RESPONSE,
            "Model response received.",
            step_index=state.step_count,
            data={
                "model": model_response.model,
                "input_tokens": model_response.input_tokens,
                "output_tokens": model_response.output_tokens,
                "cost": usage_record.cost.total_cost,
            },
        ))

        parsed_output = _parse_model_output(
            model_response.content,
            actual_tests_passed=actual_tests_passed,
        )

        if parsed_output.stop_reason is not None:
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
) -> ParsedModelOutput:
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError as error:
        return ParsedModelOutput(
            stop_reason=StopReason.INVALID_FINAL_OUTPUT,
            error=f"Model output was not valid JSON: {error}",
        )

    if not isinstance(parsed, dict):
        return ParsedModelOutput(
            stop_reason=StopReason.INVALID_FINAL_OUTPUT,
            error="Model output must be a JSON object.",
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

        try:
            tool_calls = [ToolCall.model_validate(item) for item in tool_calls_data]
        except ValidationError as error:
            return ParsedModelOutput(
                stop_reason=StopReason.INVALID_FINAL_OUTPUT,
                error=f"Tool call validation failed: {error}",
            )
        return ParsedModelOutput(tool_calls=tool_calls)

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

    return ParsedModelOutput(final_output=final_output)


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
) -> AgentLoopResult | None:
    for call in tool_calls:
        if check_tool_call_limit(state, limits):
            return _stop_with_failure(
                state,
                StopReason.MAX_TOOL_CALLS,
                "Agent stopped because max_tool_calls was reached.",
                start_time,
                usage_tracker,
                events,
            )

        if is_repeated_action(state, call.name, call.arguments):
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
            data={"call_id": call.call_id, "name": call.name, "arguments": call.arguments},
        ))

        result = tool_registry.execute(call)

        events.append(make_event(
            AgentEventType.TOOL_RESULT,
            "Tool call finished.",
            step_index=state.step_count,
            data={
                "call_id": result.call_id,
                "name": result.name,
                "success": result.success,
                "error": result.error,
            },
        ))
        record_tool_call(state, call.name, call.arguments)
        state.messages.append(_tool_result_to_message(result))

    return None


def _tool_result_to_message(result: ToolResult) -> Message:
    return Message(
        role="tool",
        content=result.content if result.success else result.error,
        tool_call_id=result.call_id,
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


def _normalize_model_response(raw_response: str | ModelResponse) -> ModelResponse:
    if isinstance(raw_response, str):
        return ModelResponse(content=raw_response)
    if isinstance(raw_response, ModelResponse):
        return raw_response

    raise TypeError("Model client must return str or ModelResponse.")


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
        events=events,
        total_input_tokens=usage_tracker.total_input_tokens(),
        total_output_tokens=usage_tracker.total_output_tokens(),
        total_cost=usage_tracker.total_cost(),
        duration_seconds=duration_seconds,
    )
