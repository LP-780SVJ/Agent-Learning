import unittest

from codeteam.errors import ErrorCategory, classify_exception, should_retry


class StatusCodeError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class ErrorClassificationTests(unittest.TestCase):
    def test_429_is_retryable_rate_limit(self) -> None:
        agent_error = classify_exception(StatusCodeError(429, "rate limited"))

        self.assertEqual(agent_error.category, ErrorCategory.RATE_LIMIT)
        self.assertTrue(should_retry(agent_error))

    def test_timeout_is_retryable(self) -> None:
        agent_error = classify_exception(TimeoutError("request timed out"))

        self.assertEqual(agent_error.category, ErrorCategory.TIMEOUT)
        self.assertTrue(should_retry(agent_error))

    def test_api_key_error_is_not_retryable(self) -> None:
        agent_error = classify_exception(RuntimeError("API key invalid"))

        self.assertEqual(agent_error.category, ErrorCategory.AUTH)
        self.assertFalse(should_retry(agent_error))

    def test_validation_error_is_not_retryable(self) -> None:
        agent_error = classify_exception(ValueError("validation failed"))

        self.assertEqual(agent_error.category, ErrorCategory.VALIDATION)
        self.assertFalse(should_retry(agent_error))


if __name__ == "__main__":
    unittest.main()
