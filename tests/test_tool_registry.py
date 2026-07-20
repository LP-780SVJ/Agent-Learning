import unittest

from pydantic import BaseModel

from codeteam.schemas.tool_calls import ToolCall
from codeteam.tools.base import RegisteredTool
from codeteam.tools.calculator import create_calculator_tool
from codeteam.tools.registry import ToolRegistry


class ToolRegistryTests(unittest.TestCase):
    def test_execute_registered_calculator_tool(self) -> None:
        registry = ToolRegistry()
        registry.register(create_calculator_tool())
        call = ToolCall(
            call_id="call-1",
            name="calculator",
            arguments={"operation": "add", "left": 2, "right": 3},
        )

        result = registry.execute(call)

        self.assertTrue(result.success)
        self.assertEqual(result.call_id, call.call_id)
        self.assertEqual(result.name, "calculator")
        self.assertEqual(float(result.content), 5.0)

    def test_unknown_tool_returns_failed_result(self) -> None:
        registry = ToolRegistry()
        call = ToolCall(
            call_id="call-unknown",
            name="missing_tool",
            arguments={},
        )

        result = registry.execute(call)

        self.assertFalse(result.success)
        self.assertEqual(result.call_id, call.call_id)
        self.assertIn("Unknown tool", result.error or "")

    def test_missing_required_argument_returns_failed_result(self) -> None:
        result = self._execute_invalid_calculator_call(
            {"operation": "add", "right": 3},
        )

        self.assertFalse(result.success)
        self.assertIn("left", result.error or "")

    def test_invalid_operation_returns_failed_result(self) -> None:
        result = self._execute_invalid_calculator_call(
            {"operation": "pow", "left": 2, "right": 3},
        )

        self.assertFalse(result.success)
        self.assertIn("operation", result.error or "")

    def test_invalid_left_type_returns_failed_result(self) -> None:
        result = self._execute_invalid_calculator_call(
            {"operation": "add", "left": "abc", "right": 3},
        )

        self.assertFalse(result.success)
        self.assertIn("left", result.error or "")

    def test_invalid_arguments_do_not_enter_tool_function(self) -> None:
        class CountingArgs(BaseModel):
            value: int

        calls = {"count": 0}

        def counting_tool(args: CountingArgs) -> str:
            calls["count"] += 1
            return str(args.value)

        registry = ToolRegistry()
        registry.register(
            RegisteredTool(
                name="counting",
                description="Counts valid calls.",
                args_schema=CountingArgs,
                func=counting_tool,
            ),
        )
        call = ToolCall(
            call_id="call-invalid-counting",
            name="counting",
            arguments={"value": "not-an-int"},
        )

        result = registry.execute(call)

        self.assertFalse(result.success)
        self.assertEqual(calls["count"], 0)

    def _execute_invalid_calculator_call(self, arguments: dict[str, object]):
        registry = ToolRegistry()
        registry.register(create_calculator_tool())
        call = ToolCall(
            call_id="call-invalid",
            name="calculator",
            arguments=arguments,
        )

        return registry.execute(call)


if __name__ == "__main__":
    unittest.main()
