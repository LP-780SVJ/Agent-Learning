import unittest

from codeteam.llm.openai_compatible import OpenAICompatibleClient, RetryConfig


class StatusCodeError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class RetryTests(unittest.TestCase):
    def test_two_429_errors_then_success(self) -> None:
        outcomes: list[Exception | str] = [
            StatusCodeError(429, "rate limited"),
            StatusCodeError(429, "rate limited"),
            "ok",
        ]
        calls = []
        sleeps = []

        def request_func(messages):
            calls.append(messages)
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        client = OpenAICompatibleClient(
            model="mock-model",
            request_func=request_func,
            retry_config=RetryConfig(max_retries=3, base_delay_seconds=0.5),
            sleep_func=sleeps.append,
        )

        result = client.complete([])

        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [0.5, 1.0])

    def test_api_key_error_is_called_once(self) -> None:
        calls = []
        sleeps = []

        def request_func(messages):
            calls.append(messages)
            raise RuntimeError("API key invalid")

        client = OpenAICompatibleClient(
            model="mock-model",
            request_func=request_func,
            retry_config=RetryConfig(max_retries=3, base_delay_seconds=0.5),
            sleep_func=sleeps.append,
        )

        with self.assertRaisesRegex(RuntimeError, "API key invalid"):
            client.complete([])

        self.assertEqual(len(calls), 1)
        self.assertEqual(sleeps, [])

    def test_exceeding_retry_limit_raises_clear_error(self) -> None:
        calls = []
        sleeps = []

        def request_func(messages):
            calls.append(messages)
            raise StatusCodeError(429, "rate limited after retries")

        client = OpenAICompatibleClient(
            model="mock-model",
            request_func=request_func,
            retry_config=RetryConfig(max_retries=2, base_delay_seconds=0.25),
            sleep_func=sleeps.append,
        )

        with self.assertRaisesRegex(StatusCodeError, "rate limited after retries"):
            client.complete([])

        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [0.25, 0.5])


if __name__ == "__main__":
    unittest.main()
