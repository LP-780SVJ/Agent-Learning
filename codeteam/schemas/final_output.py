# 放 AgentFinalOutput、CompletionStatus、结构校验和语义校验逻辑。

from enum import Enum
from pydantic import BaseModel

class CompletionStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_USER_INPUT = "needs_user_input"

class AgentFinalOutput(BaseModel):
    status: CompletionStatus
    summary: str
    tests_passed: bool
    error: str | None = None
    user_input_request: str | None = None


def validate_final_output_semantics(output: AgentFinalOutput,
                                    actual_tests_passed: bool | None = None,) -> AgentFinalOutput: 

    if output.status == CompletionStatus.COMPLETED and actual_tests_passed is not None:
        if output.tests_passed != actual_tests_passed:
            raise ValueError("Semantic validation failed: tests_passed does not match actual test results.")
        return output
    
    if output.status == CompletionStatus.FAILED:
        if not output.error:
            raise ValueError("Semantic validation failed: error message must be provided for failed status.")
        return output

    if output.status == CompletionStatus.NEEDS_USER_INPUT:
        if not output.user_input_request:
            raise ValueError("Semantic validation failed: user_input_request must be provided for needs_user_input status.")
        return output

    return output
