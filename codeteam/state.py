from enum import Enum
from codeteam.schemas.messages import Message


class StopReason(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    MAX_STEPS = "max_steps"
    MAX_TOOL_CALLS = "max_tool_calls"
    REPEATED_ACTION = "repeated_action"
    NO_PROGRESS = "no_progress"
    INVALID_FINAL_OUTPUT = "invalid_final_output"

class ActionFingerprint:# 检测重复动作
    tool_name: str
    arguments_json: str

class AgentLoopState:
    messages: list[Message]
    step_count: int
    tool_call_count: int
    last_action: ActionFingerprint | None
    stop_reason: StopReason | None

def make_action_fingerprint(tool_name: str, arguments_json: str) -> ActionFingerprint:
    return ActionFingerprint(tool_name=tool_name, arguments_json=arguments_json)

def record_tool_call(state: AgentLoopState, tool_name: str, arguments_json: str) -> None:
    state.tool_call_count += 1
    state.last_action = make_action_fingerprint(tool_name, arguments_json)

def is_repeated_action(state: AgentLoopState, tool_name: str, arguments_json: str) -> bool:
    if not state.last_action:
        return False
    return state.last_action == make_action_fingerprint(tool_name, arguments_json)