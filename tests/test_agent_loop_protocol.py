from __future__ import annotations

import json

from codeteam.agent_loop import run_agent_loop
from codeteam.events import AgentEventType
from codeteam.limits import AgentLoopLimits
from codeteam.llm.mock import MockModelClient
from codeteam.state import StopReason
from codeteam.tools.calculator import create_calculator_tool
from codeteam.tools.registry import ToolRegistry


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(create_calculator_tool())
    return registry


def test_runtime_assigns_call_id_when_model_omits_or_spoofs_it() -> None:
    result = run_agent_loop(
        MockModelClient(
            [
                json.dumps(
                    {
                        "tool_calls": [
                            {
                                "call_id": "provider-controlled",
                                "name": "calculator",
                                "arguments": {
                                    "operation": "add",
                                    "left": 1,
                                    "right": 2,
                                },
                            }
                        ]
                    }
                ),
                json.dumps(
                    {
                        "status": "completed",
                        "summary": "done",
                        "tests_passed": True,
                    }
                ),
            ]
        ),
        _registry(),
        [],
        actual_tests_passed=True,
    )

    tool_message = next(message for message in result.messages if message.role == "tool")
    assert tool_message.tool_call_id == "step-1-call-1"
    assert tool_message.tool_call_id != "provider-controlled"


def test_invalid_output_gets_bounded_protocol_repair_then_continues() -> None:
    client = MockModelClient(
        [
            "not-json",
            (
                '{"tool_calls":[{"name":"calculator","arguments":'
                '{"operation":"add","left":1,"right":2}}]}'
            ),
            '{"status":"completed","summary":"done","tests_passed":true}',
        ]
    )

    result = run_agent_loop(
        client,
        _registry(),
        [],
        actual_tests_passed=True,
    )

    assert result.stop_reason is StopReason.COMPLETED
    assert result.protocol_repairs_used == 1
    repair_message = result.messages[1]
    assert repair_message.role == "user"
    assert "protocol_repair" in (repair_message.content or "")
    assert "not-json" not in (repair_message.content or "")
    repair_events = [
        event
        for event in result.events
        if event.event_type is AgentEventType.PROTOCOL_REPAIR_REQUESTED
    ]
    assert len(repair_events) == 1


def test_protocol_repair_stops_after_two_attempts() -> None:
    result = run_agent_loop(
        MockModelClient(["bad-1", "bad-2", "bad-3"]),
        ToolRegistry(),
        [],
        limits=AgentLoopLimits(max_steps=10, max_protocol_repairs=2),
    )

    assert result.stop_reason is StopReason.INVALID_FINAL_OUTPUT
    assert result.protocol_repairs_used == 2
    assert result.steps_used == 3
    assert "not valid JSON" in (result.error or "")


def test_protocol_repair_can_be_disabled() -> None:
    result = run_agent_loop(
        MockModelClient(["bad"]),
        ToolRegistry(),
        [],
        limits=AgentLoopLimits(max_protocol_repairs=0),
    )

    assert result.stop_reason is StopReason.INVALID_FINAL_OUTPUT
    assert result.protocol_repairs_used == 0
    assert result.steps_used == 1
