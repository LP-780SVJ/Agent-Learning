import unittest

from pydantic import ValidationError

from codeteam.schemas.final_output import AgentFinalOutput, CompletionStatus


class FinalOutputModelTests(unittest.TestCase):
    def test_model_validate_json_parses_valid_final_output(self) -> None:
        raw_output = """
        {
            "status": "completed",
            "summary": "Implemented the requested feature.",
            "tests_passed": true,
            "error": null,
            "user_input_request": null
        }
        """

        output = AgentFinalOutput.model_validate_json(raw_output)

        self.assertEqual(output.status, CompletionStatus.COMPLETED)
        self.assertEqual(output.summary, "Implemented the requested feature.")
        self.assertTrue(output.tests_passed)
        self.assertIsNone(output.error)
        self.assertIsNone(output.user_input_request)

    def test_model_validate_json_rejects_unknown_status(self) -> None:
        raw_output = """
        {
            "status": "done",
            "summary": "Finished.",
            "tests_passed": true
        }
        """

        with self.assertRaises(ValidationError):
            AgentFinalOutput.model_validate_json(raw_output)

    def test_model_validate_json_rejects_missing_required_field(self) -> None:
        raw_output = """
        {
            "status": "completed",
            "summary": "Finished."
        }
        """

        with self.assertRaises(ValidationError):
            AgentFinalOutput.model_validate_json(raw_output)


if __name__ == "__main__":
    unittest.main()
