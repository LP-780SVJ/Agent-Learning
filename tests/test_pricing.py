import unittest

from codeteam.usage.pricing import ModelPricing, calculate_cost


class PricingTests(unittest.TestCase):
    def test_calculates_mock_model_cost(self) -> None:
        cost = calculate_cost(
            model="mock-model",
            input_tokens=1_000_000,
            output_tokens=500_000,
        )

        self.assertEqual(cost.model, "mock-model")
        self.assertEqual(cost.input_tokens, 1_000_000)
        self.assertEqual(cost.output_tokens, 500_000)
        self.assertAlmostEqual(cost.input_cost, 0.10)
        self.assertAlmostEqual(cost.output_cost, 0.20)
        self.assertAlmostEqual(cost.total_cost, 0.30)

    def test_calculates_cost_with_custom_pricing_table(self) -> None:
        cost = calculate_cost(
            model="custom-model",
            input_tokens=2_000_000,
            output_tokens=3_000_000,
            pricing={
                "custom-model": ModelPricing(
                    input_per_1m_tokens=1.50,
                    output_per_1m_tokens=2.00,
                ),
            },
        )

        self.assertAlmostEqual(cost.input_cost, 3.00)
        self.assertAlmostEqual(cost.output_cost, 6.00)
        self.assertAlmostEqual(cost.total_cost, 9.00)

    def test_unknown_model_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown model pricing"):
            calculate_cost(
                model="missing-model",
                input_tokens=1,
                output_tokens=1,
            )

    def test_negative_tokens_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "input_tokens"):
            calculate_cost(
                model="mock-model",
                input_tokens=-1,
                output_tokens=0,
            )

        with self.assertRaisesRegex(ValueError, "output_tokens"):
            calculate_cost(
                model="mock-model",
                input_tokens=0,
                output_tokens=-1,
            )


if __name__ == "__main__":
    unittest.main()
