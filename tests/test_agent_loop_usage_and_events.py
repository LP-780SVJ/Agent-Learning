import json
import tempfile
import unittest
from pathlib import Path

from codeteam.agent_loop import run_agent_loop
from codeteam.events import AgentEventType
from codeteam.llm.base import ModelResponse
from codeteam.schemas.messages import Message
from codeteam.state import StopReason
from codeteam.tools.calculator import create_calculator_tool
from codeteam.tools.files import create_file_tools
from codeteam.tools.registry import ToolRegistry


class UsageModelClient:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = responses
        self.index = 0
        self.calls: list[list[Message]] = []

    def complete(self, messages: list[Message]) -> ModelResponse:
        self.calls.append(list(messages))
        response = self.responses[self.index]
        self.index += 1
        return response


class AgentLoopUsageAndEventTests(unittest.TestCase):
    def test_result_includes_total_cost_and_duration(self) -> None:
        client = UsageModelClient(
            [
                ModelResponse(
                    content=json.dumps(
                        {
                            "status": "completed",
                            "summary": "done",
                            "tests_passed": True,
                        }
                    ),
                    model="mock-model",
                    input_tokens=1_000_000,
                    output_tokens=1_000_000,
                ),
            ]
        )

        result = run_agent_loop(
            client,
            ToolRegistry(),
            [],
            actual_tests_passed=True,
        )

        self.assertEqual(result.stop_reason, StopReason.COMPLETED)
        self.assertAlmostEqual(result.total_cost, 0.5)
        self.assertGreaterEqual(result.duration_seconds, 0)

    def test_each_step_records_input_and_output_tokens(self) -> None:
        client = UsageModelClient(
            [
                ModelResponse(
                    content=json.dumps(
                        {
                            "tool_calls": [
                                {
                                    "call_id": "call-1",
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
                    model="mock-model",
                    input_tokens=1_000_000,
                    output_tokens=500_000,
                ),
                ModelResponse(
                    content=json.dumps(
                        {
                            "status": "completed",
                            "summary": "done",
                            "tests_passed": True,
                        }
                    ),
                    model="mock-model",
                    input_tokens=500_000,
                    output_tokens=1_000_000,
                ),
            ]
        )
        registry = ToolRegistry()
        registry.register(create_calculator_tool())

        result = run_agent_loop(
            client,
            registry,
            [],
            actual_tests_passed=True,
        )

        model_response_events = [
            event
            for event in result.events
            if event.event_type == AgentEventType.MODEL_RESPONSE
        ]
        self.assertEqual(len(model_response_events), 2)
        self.assertEqual(result.total_input_tokens, 1_500_000)
        self.assertEqual(result.total_output_tokens, 1_500_000)
        self.assertAlmostEqual(result.total_cost, 0.75)
        self.assertEqual(
            [event.data["input_tokens"] for event in model_response_events],
            [1_000_000, 500_000],
        )
        self.assertEqual(
            [event.data["output_tokens"] for event in model_response_events],
            [500_000, 1_000_000],
        )

    def test_file_not_found_tool_result_is_sent_back_to_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            client = UsageModelClient(
                [
                    ModelResponse(
                        content=json.dumps(
                            {
                                "tool_calls": [
                                    {
                                        "call_id": "call-missing",
                                        "name": "read_file",
                                        "arguments": {"path": "missing.txt"},
                                    }
                                ]
                            }
                        ),
                    ),
                    ModelResponse(
                        content=json.dumps(
                            {
                                "status": "failed",
                                "summary": "missing file",
                                "tests_passed": False,
                                "error": "file was missing",
                            }
                        ),
                    ),
                ]
            )
            registry = ToolRegistry()
            for tool in create_file_tools(workspace):
                registry.register(tool)

            result = run_agent_loop(client, registry, [])

            self.assertEqual(result.stop_reason, StopReason.FAILED)
            self.assertEqual(len(client.calls), 2)

            messages_seen_by_second_model_call = client.calls[1]
            tool_messages = [
                message
                for message in messages_seen_by_second_model_call
                if message.role == "tool"
            ]
            self.assertEqual(len(tool_messages), 1)
            self.assertEqual(tool_messages[0].tool_call_id, "call-missing")
            self.assertIn("Path does not exist", tool_messages[0].content or "")

            tool_result_events = [
                event
                for event in result.events
                if event.event_type == AgentEventType.TOOL_RESULT
            ]
            self.assertEqual(len(tool_result_events), 1)
            self.assertFalse(tool_result_events[0].data["success"])


if __name__ == "__main__":
    unittest.main()
