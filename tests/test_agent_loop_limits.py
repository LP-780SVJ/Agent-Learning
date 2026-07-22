import unittest

from codeteam.agent_loop import run_agent_loop
from codeteam.limits import AgentLoopLimits
from codeteam.llm.mock import MockModelClient
from codeteam.state import StopReason
from codeteam.tools.calculator import create_calculator_tool
from codeteam.tools.registry import ToolRegistry


class AgentLoopLimitTests(unittest.TestCase):
    def test_max_steps_stops_before_third_model_call(self) -> None:
        client = MockModelClient(
            [
                '{"tool_calls":[{"call_id":"call-1","name":"calculator","arguments":{"operation":"add","left":1,"right":2}}]}',
                '{"tool_calls":[{"call_id":"call-2","name":"calculator","arguments":{"operation":"add","left":3,"right":4}}]}',
                '{"status":"completed","summary":"should not be consumed","tests_passed":true}',
            ],
        )

        result = run_agent_loop(
            client,
            _calculator_registry(),
            [],
            limits=AgentLoopLimits(max_steps=2, max_tool_calls=10),
        )

        self.assertEqual(result.stop_reason, StopReason.MAX_STEPS)
        self.assertEqual(result.steps_used, 2)
        self.assertEqual(client.index, 2)
        self.assertIn("max_steps", result.error or "")

    def test_max_tool_calls_stops_before_second_tool_execution(self) -> None:
        client = MockModelClient(
            [
                '{"tool_calls":[{"call_id":"call-1","name":"calculator","arguments":{"operation":"add","left":1,"right":2}}]}',
                '{"tool_calls":[{"call_id":"call-2","name":"calculator","arguments":{"operation":"add","left":3,"right":4}}]}',
            ],
        )

        result = run_agent_loop(
            client,
            _calculator_registry(),
            [],
            limits=AgentLoopLimits(max_steps=10, max_tool_calls=1),
        )

        self.assertEqual(result.stop_reason, StopReason.MAX_TOOL_CALLS)
        self.assertEqual(result.tool_calls_used, 1)
        self.assertIn("max_tool_calls", result.error or "")


def _calculator_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(create_calculator_tool())
    return registry


if __name__ == "__main__":
    unittest.main()
