from __future__ import annotations

import json

from pydantic import BaseModel

from codeteam.agent_loop import run_agent_loop
from codeteam.llm.base import (
    ModelFinishState,
    ModelRequest,
    ModelResponseMode,
    ModelTurn,
)
from codeteam.schemas.final_output import CompletionStatus
from codeteam.schemas.messages import Message
from codeteam.schemas.tool_calls import ToolCall
from codeteam.state import StopReason
from codeteam.tools.base import RegisteredTool
from codeteam.tools.registry import ToolRegistry


class _Args(BaseModel):
    value: int


class TurnClient:
    def __init__(self, turns: list[ModelTurn]) -> None:
        self.turns = turns
        self.requests: list[ModelRequest] = []

    def turn(self, request: ModelRequest) -> ModelTurn:
        self.requests.append(request)
        return self.turns.pop(0)


def _final() -> ModelTurn:
    return ModelTurn(
        text=json.dumps(
            {
                "status": "completed",
                "summary": "done",
                "tests_passed": True,
                "error": None,
                "user_input_request": None,
            }
        ),
        finish_state=ModelFinishState.STOP,
        actual_response_mode=ModelResponseMode.TEXT,
    )


def test_native_turn_executes_once_and_round_trips_double_ids() -> None:
    invocations = {"count": 0}

    def execute(args: BaseModel) -> str:
        parsed = _Args.model_validate(args)
        invocations["count"] += 1
        return str(parsed.value)

    registry = ToolRegistry()
    registry.register(RegisteredTool("count", "count", _Args, execute))
    client = TurnClient(
        [
            ModelTurn(
                # A textual duplicate must not be parsed or executed.
                text='{"tool_calls":[{"name":"count","arguments":{"value":99}}]}',
                tool_calls=(
                    ToolCall(
                        provider_call_id="provider-1",
                        name="count",
                        arguments={"value": 7},
                    ),
                ),
                finish_state=ModelFinishState.TOOL_CALLS,
                finish_reason="tool_calls",
                actual_response_mode=ModelResponseMode.NATIVE_TOOLS,
            ),
            _final(),
        ]
    )

    result = run_agent_loop(
        client,
        registry,
        [Message(role="user", content="go")],
        actual_tests_passed=True,
    )

    assert result.status is CompletionStatus.COMPLETED
    assert invocations["count"] == 1
    assert result.tool_calls_used == 1
    assistant, tool = client.requests[1].messages[-2:]
    assert assistant.role == "assistant"
    assert assistant.tool_calls is not None
    assert assistant.tool_calls[0].call_id == "step-1-call-1"
    assert assistant.tool_calls[0].provider_call_id == "provider-1"
    assert tool.role == "tool"
    assert tool.tool_call_id == "step-1-call-1"
    assert tool.provider_call_id == "provider-1"


def test_incomplete_length_and_malformed_turns_never_reach_backend() -> None:
    def should_not_execute(args: BaseModel) -> str:
        del args
        raise AssertionError("typed provider failure reached tool backend")

    for finish_state, expected in [
        (ModelFinishState.INCOMPLETE, StopReason.INCOMPLETE_PROVIDER_TURN),
        (ModelFinishState.OUTPUT_TRUNCATED, StopReason.OUTPUT_TRUNCATED),
        (ModelFinishState.INVALID_TOOL_CALL, StopReason.INVALID_TOOL_CALL),
    ]:
        invocations = {"count": 0}
        registry = ToolRegistry()
        registry.register(
                RegisteredTool(
                    "count",
                    "count",
                    _Args,
                    should_not_execute,
                )
        )
        result = run_agent_loop(
            TurnClient(
                    [
                        ModelTurn(
                            text=None,
                            tool_calls=(
                                ToolCall(
                                    provider_call_id="must-not-run",
                                    name="count",
                                    arguments={"value": 1},
                                ),
                            )
                            if finish_state is ModelFinishState.OUTPUT_TRUNCATED
                            else (),
                            finish_state=finish_state,
                        incomplete_reason="typed failure",
                    )
                ]
            ),
            registry,
            [Message(role="user", content="go")],
        )

        assert result.stop_reason is expected
        assert result.protocol_repairs_used == 0
        assert invocations["count"] == 0


def test_unknown_native_tool_is_registry_rejected_with_runtime_id() -> None:
    client = TurnClient(
        [
            ModelTurn(
                tool_calls=(
                    ToolCall(
                        provider_call_id="provider-unknown",
                        name="missing",
                        arguments={},
                    ),
                ),
                finish_state=ModelFinishState.TOOL_CALLS,
            ),
            _final(),
        ]
    )
    result = run_agent_loop(
        client,
        ToolRegistry(),
        [Message(role="user", content="go")],
        actual_tests_passed=True,
    )

    assert result.status is CompletionStatus.COMPLETED
    tool = client.requests[1].messages[-1]
    assert tool.role == "tool"
    assert tool.tool_call_id == "step-1-call-1"
    assert tool.provider_call_id == "provider-unknown"
    assert "Unknown tool" in (tool.content or "")


def test_native_argument_schema_failure_does_not_invoke_tool_function() -> None:
    invoked = {"count": 0}

    def execute(args: BaseModel) -> str:
        del args
        invoked["count"] += 1
        return "should not run"

    registry = ToolRegistry()
    registry.register(RegisteredTool("count", "count", _Args, execute))
    client = TurnClient(
        [
            ModelTurn(
                tool_calls=(
                    ToolCall(
                        provider_call_id="provider-invalid-args",
                        name="count",
                        arguments={"value": "not-an-int"},
                    ),
                ),
                finish_state=ModelFinishState.TOOL_CALLS,
            ),
            _final(),
        ]
    )

    result = run_agent_loop(
        client,
        registry,
        [Message(role="user", content="go")],
        actual_tests_passed=True,
    )

    assert result.status is CompletionStatus.COMPLETED
    assert invoked["count"] == 0
    tool = client.requests[1].messages[-1]
    assert tool.role == "tool"
    assert tool.tool_call_id == "step-1-call-1"
    assert tool.provider_call_id == "provider-invalid-args"
    assert "value" in (tool.content or "")
