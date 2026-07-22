import unittest

from codeteam.agent_loop import run_agent_loop
from codeteam.llm.mock import MockModelClient
from codeteam.schemas.final_output import CompletionStatus
from codeteam.state import StopReason
from codeteam.tools.registry import ToolRegistry


class AgentLoopStopConditionTests(unittest.TestCase):
    def test_no_tool_calls_and_no_final_output_stops_as_no_progress(self) -> None:
        result = run_agent_loop(
            MockModelClient(['{"message":"still thinking"}']),
            ToolRegistry(),
            [],
        )

        self.assertEqual(result.stop_reason, StopReason.NO_PROGRESS)

    def test_empty_tool_calls_stops_as_no_progress(self) -> None:
        result = run_agent_loop(
            MockModelClient(['{"tool_calls":[]}']),
            ToolRegistry(),
            [],
        )

        self.assertEqual(result.stop_reason, StopReason.NO_PROGRESS)

    def test_non_object_json_stops_as_invalid_final_output(self) -> None:
        result = run_agent_loop(
            MockModelClient(["[]"]),
            ToolRegistry(),
            [],
        )

        self.assertEqual(result.stop_reason, StopReason.INVALID_FINAL_OUTPUT)

    def test_completed_output_without_test_context_does_not_crash(self) -> None:
        result = run_agent_loop(
            MockModelClient(
                [
                    '{"status":"completed","summary":"done","tests_passed":true}',
                ],
            ),
            ToolRegistry(),
            [],
        )

        self.assertEqual(result.stop_reason, StopReason.COMPLETED)

    def test_completed_output_with_failed_validation_cannot_complete(self) -> None:
        result = run_agent_loop(
            MockModelClient(
                [
                    '{"status":"completed","summary":"done","tests_passed":true}',
                ],
            ),
            ToolRegistry(),
            [],
            actual_tests_passed=False,
        )

        self.assertNotEqual(result.stop_reason, StopReason.COMPLETED)
        self.assertNotEqual(result.status, CompletionStatus.COMPLETED)
        self.assertEqual(result.stop_reason, StopReason.INVALID_FINAL_OUTPUT)

    def test_failed_final_output_stops_as_failed(self) -> None:
        result = run_agent_loop(
            MockModelClient(
                [
                    '{"status":"failed","summary":"could not finish","tests_passed":false,"error":"tests failed"}',
                ],
            ),
            ToolRegistry(),
            [],
        )

        self.assertEqual(result.stop_reason, StopReason.FAILED)
        self.assertEqual(result.status, CompletionStatus.FAILED)
        self.assertEqual(result.error, "tests failed")

    def test_needs_user_input_final_output_stops_as_paused(self) -> None:
        result = run_agent_loop(
            MockModelClient(
                [
                    '{"status":"needs_user_input","summary":"need clarification","tests_passed":false,"user_input_request":"Which file should I edit?"}',
                ],
            ),
            ToolRegistry(),
            [],
        )

        self.assertEqual(result.stop_reason, StopReason.PAUSED)
        self.assertEqual(result.status, CompletionStatus.NEEDS_USER_INPUT)


if __name__ == "__main__":
    unittest.main()
