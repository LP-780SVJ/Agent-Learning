import unittest

from codeteam.agent_loop import run_agent_loop
from codeteam.limits import AgentLoopLimits
from codeteam.llm.mock import MockModelClient
from codeteam.state import StopReason
from codeteam.tools.calculator import create_calculator_tool
from codeteam.tools.registry import ToolRegistry


class AgentLoopRepeatedActionTests(unittest.TestCase):
    def test_consecutive_same_tool_and_arguments_stops_as_repeated_action(self) -> None:
        client = MockModelClient(
            [
                '{"tool_calls":[{"call_id":"call-1","name":"calculator","arguments":{"operation":"add","left":1,"right":2}}]}',
                '{"tool_calls":[{"call_id":"call-2","name":"calculator","arguments":{"right":2,"left":1,"operation":"add"}}]}',
            ],
        )

        result = run_agent_loop(
            client,
            _calculator_registry(),
            [],
            limits=AgentLoopLimits(max_steps=10, max_tool_calls=10),
        )

        self.assertEqual(result.stop_reason, StopReason.REPEATED_ACTION)
        self.assertEqual(result.tool_calls_used, 1)
        self.assertIn("repeated", result.error or "")


def _calculator_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(create_calculator_tool())
    return registry


if __name__ == "__main__":
    unittest.main()
