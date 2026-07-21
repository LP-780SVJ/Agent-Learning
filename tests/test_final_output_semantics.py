import unittest

from codeteam.schemas.final_output import (
    AgentFinalOutput,
    CompletionStatus,
    validate_final_output_semantics,
)


class FinalOutputSemanticsTests(unittest.TestCase):
    def test_completed_output_is_accepted_when_real_tests_passed(self) -> None:
        output = AgentFinalOutput(
            status=CompletionStatus.COMPLETED,
            summary="Feature completed.",
            tests_passed=True,
        )

        validated = validate_final_output_semantics(
            output,
            actual_tests_passed=True,
        )

        self.assertIs(validated, output)

    def test_completed_output_is_rejected_when_real_tests_failed(self) -> None:
        output = AgentFinalOutput(
            status=CompletionStatus.COMPLETED,
            summary="Feature completed.",
            tests_passed=True,
        )

        with self.assertRaisesRegex(ValueError, "tests_passed"):
            validate_final_output_semantics(
                output,
                actual_tests_passed=False,
            )

    def test_failed_output_requires_error_message(self) -> None:
        output = AgentFinalOutput(
            status=CompletionStatus.FAILED,
            summary="Could not complete the task.",
            tests_passed=False,
        )

        with self.assertRaisesRegex(ValueError, "error"):
            validate_final_output_semantics(output)

    def test_failed_output_is_accepted_with_error_message(self) -> None:
        output = AgentFinalOutput(
            status=CompletionStatus.FAILED,
            summary="Could not complete the task.",
            tests_passed=False,
            error="Unit tests failed.",
        )

        validated = validate_final_output_semantics(output)

        self.assertIs(validated, output)

    def test_needs_user_input_requires_request_text(self) -> None:
        output = AgentFinalOutput(
            status=CompletionStatus.NEEDS_USER_INPUT,
            summary="Blocked on missing context.",
            tests_passed=False,
        )

        with self.assertRaisesRegex(ValueError, "user_input_request"):
            validate_final_output_semantics(output)

    def test_needs_user_input_is_accepted_with_request_text(self) -> None:
        output = AgentFinalOutput(
            status=CompletionStatus.NEEDS_USER_INPUT,
            summary="Blocked on missing context.",
            tests_passed=False,
            user_input_request="Which API should I target?",
        )

        validated = validate_final_output_semantics(output)

        self.assertIs(validated, output)


if __name__ == "__main__":
    unittest.main()
