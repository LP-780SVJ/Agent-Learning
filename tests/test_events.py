import unittest

from codeteam.events import AgentEventType, make_event


class EventTests(unittest.TestCase):
    def test_can_create_step_event(self) -> None:
        event = make_event(
            AgentEventType.STEP_STARTED,
            "Agent step started.",
            step_index=1,
        )

        self.assertEqual(event.event_type, AgentEventType.STEP_STARTED)
        self.assertEqual(event.step_index, 1)
        self.assertEqual(event.message, "Agent step started.")
        self.assertGreater(event.timestamp, 0)

    def test_event_can_include_token_data(self) -> None:
        event = make_event(
            AgentEventType.MODEL_RESPONSE,
            "Model response received.",
            step_index=2,
            data={
                "model": "mock-model",
                "input_tokens": 100,
                "output_tokens": 50,
            },
        )

        self.assertEqual(event.event_type, AgentEventType.MODEL_RESPONSE)
        self.assertEqual(event.step_index, 2)
        self.assertEqual(event.message, "Model response received.")
        self.assertEqual(event.data["input_tokens"], 100)
        self.assertEqual(event.data["output_tokens"], 50)


if __name__ == "__main__":
    unittest.main()
