from __future__ import annotations

import json

from codeteam.agent_loop import run_agent_loop
from codeteam.events import AgentEventType
from codeteam.limits import AgentLoopLimits
from codeteam.llm.mock import MockModelClient
from codeteam.state import FailureOrigin, StopReason
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
    repair_message = next(
        message
        for message in result.messages
        if message.role == "user" and "protocol_repair" in (message.content or "")
    )
    assert repair_message.role == "user"
    assert "protocol_repair" in (repair_message.content or "")
    assert "not-json" not in (repair_message.content or "")
    assert all("not-json" not in (message.content or "") for message in result.messages)
    assert result.model_outputs[0].raw_content == "not-json"
    assert result.model_outputs[0].parse_error is not None
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


def test_protocol_repair_budget_resets_after_valid_actions() -> None:
    client = MockModelClient(
        [
            "bad-1",
            "bad-2",
            '{"tool_calls":[{"name":"calculator","arguments":{"operation":"add","left":1,"right":2}}]}',
            "bad-3",
            '{"tool_calls":[{"name":"calculator","arguments":{"operation":"add","left":2,"right":3}}]}',
            '{"status":"completed","summary":"done","tests_passed":true}',
        ]
    )

    result = run_agent_loop(
        client,
        _registry(),
        [],
        limits=AgentLoopLimits(max_steps=8, max_protocol_repairs=2),
        actual_tests_passed=True,
    )

    assert result.stop_reason is StopReason.COMPLETED
    assert result.protocol_repairs_used == 3
    assert result.protocol_repair_streak == 0
    assert [item.parse_error is not None for item in result.model_outputs] == [
        True,
        True,
        False,
        True,
        False,
        False,
    ]


def test_repeated_read_only_action_uses_cache_then_stops_no_progress() -> None:
    action = (
        '{"tool_calls":[{"name":"calculator","arguments":'
        '{"operation":"add","left":1,"right":2}}]}'
    )
    result = run_agent_loop(
        MockModelClient([action, action, action]),
        _registry(),
        [],
        limits=AgentLoopLimits(max_steps=5, max_tool_calls=5),
        cacheable_tools=frozenset({"calculator"}),
    )

    assert result.stop_reason is StopReason.NO_PROGRESS
    assert result.tool_calls_used == 3
    assert "cached or repeated exploration turns" in (result.error or "")
    assert result.failure_origin is FailureOrigin.CACHED_BATCH_STALL
    assert result.processed_tool_calls == 3
    assert result.progress_guard_unprocessed_safe_tool_call_count == 0


def test_resumed_protocol_streak_uses_consecutive_budget_then_resets() -> None:
    result = run_agent_loop(
        MockModelClient(
            [
                "bad-after-resume",
                '{"status":"completed","summary":"done","tests_passed":true}',
            ]
        ),
        ToolRegistry(),
        [],
        limits=AgentLoopLimits(max_steps=4, max_protocol_repairs=2),
        actual_tests_passed=True,
        initial_protocol_repair_streak=1,
    )

    assert result.stop_reason is StopReason.COMPLETED
    assert result.protocol_repairs_used == 1
    assert result.protocol_repair_streak == 0
