import unittest

from codeteam.tools.calculator import CalculatorArgs, calculator


class CalculatorTests(unittest.TestCase):
    def test_add(self) -> None:
        result = calculator(CalculatorArgs(operation="add", left=2, right=3))

        self.assertEqual(float(result), 5.0)

    def test_subtract(self) -> None:
        result = calculator(CalculatorArgs(operation="subtract", left=7, right=4))

        self.assertEqual(float(result), 3.0)

    def test_multiply(self) -> None:
        result = calculator(CalculatorArgs(operation="multiply", left=6, right=5))

        self.assertEqual(float(result), 30.0)

    def test_divide(self) -> None:
        result = calculator(CalculatorArgs(operation="divide", left=8, right=2))

        self.assertEqual(float(result), 4.0)

    def test_divide_by_zero_raises_controlled_error(self) -> None:
        args = CalculatorArgs(operation="divide", left=8, right=0)

        with self.assertRaisesRegex(ValueError, "Cannot divide by zero"):
            calculator(args)


if __name__ == "__main__":
    unittest.main()
