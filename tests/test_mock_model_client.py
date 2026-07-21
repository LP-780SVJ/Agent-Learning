import unittest

from codeteam.llm.mock import MockModelClient


class MockModelClientTests(unittest.TestCase):
    def test_complete_returns_outputs_in_order(self) -> None:
        client = MockModelClient(["first response", "second response"])

        self.assertEqual(client.complete([]), "first response")
        self.assertEqual(client.complete([]), "second response")

    def test_complete_raises_when_outputs_are_exhausted(self) -> None:
        client = MockModelClient(["only response"])

        client.complete([])

        with self.assertRaisesRegex(IndexError, "No more mock outputs"):
            client.complete([])


if __name__ == "__main__":
    unittest.main()
