from dataclasses import dataclass, field
from codeteam.state import AgentLoopState, StopReason, ActionFingerprint
from codeteam.schemas.messages import Message
from codeteam.schemas.final_output import AgentFinalOutput, CompletionStatus, validate_final_output_semantics

@dataclass
class AgentLoopResult:
    status: CompletionStatus
    stop_reason: StopReason
    messages: list[Message] = field(default_factory=list)
    final_output: AgentFinalOutput | None = None
    error: str | None = None
    steps_used: int = 0
    tool_calls_used: int = 0


def run_agent_loop() -> None:
    raise NotImplementedError("run_agent_loop will be implemented later.")


def _parse_model_output() -> None:
    raise NotImplementedError("_parse_model_output will be implemented later.")


def _handle_final_output() -> None:
    raise NotImplementedError("_handle_final_output will be implemented later.")


def _handle_tool_calls() -> None:
    raise NotImplementedError("_handle_tool_calls will be implemented later.")


def _tool_result_to_message() -> None:
    raise NotImplementedError("_tool_result_to_message will be implemented later.")


def _stop_with_failure() -> None:
    raise NotImplementedError("_stop_with_failure will be implemented later.")