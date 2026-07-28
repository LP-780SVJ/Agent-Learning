import unittest

from codeteam.usage.pricing import ModelPricing
from codeteam.usage.tracker import UsageTracker


class UsageTrackerTests(unittest.TestCase):
    def test_records_single_step_tokens(self) -> None:
        tracker = UsageTracker()

        record = tracker.record_step(
            step_index=1,
            model="mock-model",
            input_tokens=100,
            output_tokens=50,
        )

        self.assertEqual(record.step_index, 1)
        self.assertEqual(record.input_tokens, 100)
        self.assertEqual(record.output_tokens, 50)

    def test_accumulates_total_tokens(self) -> None:
        tracker = UsageTracker()

        tracker.record_step(1, "mock-model", 100, 50)
        tracker.record_step(2, "mock-model", 20, 30)

        self.assertEqual(tracker.total_input_tokens(), 120)
        self.assertEqual(tracker.total_output_tokens(), 80)
        self.assertEqual(tracker.total_tokens(), 200)

    def test_calculates_total_cost_from_pricing(self) -> None:
        tracker = UsageTracker()
        pricing = {
            "unit-test-model": ModelPricing(
                input_per_1m_tokens=2.0,
                output_per_1m_tokens=6.0,
            ),
        }

        tracker.record_step(
            step_index=1,
            model="unit-test-model",
            input_tokens=500_000,
            output_tokens=500_000,
            pricing=pricing,
        )
        tracker.record_step(
            step_index=2,
            model="unit-test-model",
            input_tokens=250_000,
            output_tokens=250_000,
            pricing=pricing,
        )

        self.assertAlmostEqual(tracker.total_cost(), 6.0)


if __name__ == "__main__":
    unittest.main()
