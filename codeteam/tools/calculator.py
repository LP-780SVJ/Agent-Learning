from codeteam.tools.base import RegisteredTool
from pydantic import BaseModel
from typing import Literal

class CalculatorArgs(BaseModel):
    operation: Literal["add", "subtract", "multiply", "divide"]
    left: float
    right: float

def calculator(args: CalculatorArgs) -> str:
    if args.operation == "add":
        return str(args.left + args.right)
    elif args.operation == "subtract":
        return str(args.left - args.right)
    elif args.operation == "multiply":
        return str(args.left * args.right)
    elif args.operation == "divide":
        if args.right == 0:
            raise ValueError("Cannot divide by zero.")
        return str(args.left / args.right)
    else:
        raise ValueError(f"Unknown operation: {args.operation}")
    
def create_calculator_tool() -> RegisteredTool:
    return RegisteredTool(
        name="calculator",
        description="Basic arithmetic calculator.",
        args_schema=CalculatorArgs,
        func=calculator,
    )