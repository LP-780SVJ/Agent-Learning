import json

from typing import Any

from dataclasses import dataclass, field
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

@dataclass(frozen=True)
class ActionFingerprint:# 检测重复动作 工具动作指纹
    tool_name: str
    arguments_json: str


@dataclass
class AgentLoopState:
    messages: list[Message] = field(default_factory=list)
    step_count: int = 0
    tool_call_count: int = 0
    last_action: ActionFingerprint | None = None
    stop_reason: StopReason | None = None

def normalize_arguments(arguments: dict[str, Any]) -> str:
    """
    Normalize the arguments dictionary to a JSON string with sorted keys.
    This ensures that the same arguments produce the same string representation.
    """
    return json.dumps(arguments,
                      sort_keys=True,
                      separators=(',', ':'),
                      ensure_ascii=False)

def make_action_fingerprint(tool_name: str, arguments: dict[str, Any]) -> ActionFingerprint:
    arguments_json = normalize_arguments(arguments)
    return ActionFingerprint(tool_name=tool_name, arguments_json=arguments_json)

def record_tool_call(state: AgentLoopState, tool_name: str, arguments: dict[str, Any]) -> None:
    state.tool_call_count += 1
    state.last_action = make_action_fingerprint(tool_name, arguments)

def is_repeated_action(state: AgentLoopState, tool_name: str, arguments: dict[str, Any]) -> bool:
    if not state.last_action:
        return False
    return state.last_action == make_action_fingerprint(tool_name, arguments)