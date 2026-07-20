import unittest

from codeteam.schemas.messages import Message
from codeteam.schemas.tool_calls import ToolCall, ToolResult


class ToolModelTests(unittest.TestCase):
    def test_tool_call_stores_call_id_name_and_arguments(self) -> None:
        call = ToolCall(
            call_id="call-1",
            name="calculator",
            arguments={"operation": "add", "left": 1, "right": 2},
        )

        self.assertEqual(call.call_id, "call-1")
        self.assertEqual(call.name, "calculator")
        self.assertEqual(
            call.arguments,
            {"operation": "add", "left": 1, "right": 2},
        )

    def test_tool_result_call_id_matches_tool_call_call_id(self) -> None:
        call = ToolCall(
            call_id="call-2",
            name="calculator",
            arguments={"operation": "multiply", "left": 3, "right": 4},
        )
        result = ToolResult(
            call_id=call.call_id,
            name=call.name,
            content="12",
            success=True,
        )

        self.assertEqual(result.call_id, call.call_id)

    def test_assistant_message_accepts_tool_calls(self) -> None:
        call = ToolCall(
            call_id="call-3",
            name="calculator",
            arguments={"operation": "subtract", "left": 9, "right": 5},
        )
        message = Message(role="assistant", tool_calls=[call])

        self.assertEqual(message.role, "assistant")
        self.assertEqual(message.tool_calls, [call])

    def test_tool_message_accepts_tool_call_id(self) -> None:
        message = Message(role="tool", content="4", tool_call_id="call-3")

        self.assertEqual(message.role, "tool")
        self.assertEqual(message.tool_call_id, "call-3")


if __name__ == "__main__":
    unittest.main()
