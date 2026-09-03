import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from codeteam.agent.runtime_models import ModelOutputEvidence, ModelRequestEvidence
from codeteam.schemas.messages import Message
from codeteam.schemas.tool_calls import ToolResult


class StopReason(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    MAX_STEPS = "max_steps"
    MAX_TOOL_CALLS = "max_tool_calls"
    REPEATED_ACTION = "repeated_action"
    NO_PROGRESS = "no_progress"
    INVALID_FINAL_OUTPUT = "invalid_final_output"
    PROVIDER_ERROR = "provider_error"
    INTERNAL_ERROR = "internal_error"
    OUTPUT_TRUNCATED = "output_truncated"
    CONTENT_FILTERED = "content_filtered"
    INCOMPLETE_PROVIDER_TURN = "incomplete_provider_turn"
    INVALID_TOOL_CALL = "invalid_tool_call"


class FailureOrigin(str, Enum):
    """Structured ownership for otherwise ambiguous loop stop reasons."""

    CACHED_BATCH_STALL = "cached_batch_stall"
    EMPTY_TOOL_BATCH = "empty_tool_batch"
    EMPTY_MODEL_TURN = "empty_model_turn"
    COMPLETION_GUIDANCE_IGNORED = "completion_guidance_ignored"
    REPEATED_ACTION_STALL = "repeated_action_stall"
    REPEATED_DESTRUCTIVE_ACTION = "repeated_destructive_action"

@dataclass(frozen=True)
class ActionFingerprint:# 检测重复动作 工具动作指纹
    tool_name: str
    arguments_json: str
    workspace_version: int = 0


@dataclass
class AgentLoopState:
    messages: list[Message] = field(default_factory=list)
    step_count: int = 0
    tool_call_count: int = 0
    protocol_repair_count: int = 0
    protocol_repair_streak: int = 0
    model_outputs: list[ModelOutputEvidence] = field(default_factory=list)
    model_requests: list[ModelRequestEvidence] = field(default_factory=list)
    last_action: ActionFingerprint | None = None
    action_history: set[ActionFingerprint] = field(default_factory=set)
    tool_result_cache: dict[ActionFingerprint, ToolResult] = field(default_factory=dict)
    cached_no_progress_count: int = 0
    declared_tool_call_count: int = 0
    processed_tool_call_count: int = 0
    rejected_tool_call_count: int = 0
    unprocessed_safe_tool_call_count: int = 0
    batch_premature_stop_count: int = 0
    progress_guard_unprocessed_safe_tool_call_count: int = 0
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

def make_action_fingerprint(
    tool_name: str,
    arguments: dict[str, Any],
    workspace_version: int = 0,
) -> ActionFingerprint:
    arguments_json = normalize_arguments(arguments)
    return ActionFingerprint(
        tool_name=tool_name,
        arguments_json=arguments_json,
        workspace_version=workspace_version,
    )

def record_tool_call(
    state: AgentLoopState,
    tool_name: str,
    arguments: dict[str, Any],
    workspace_version: int = 0,
) -> None:
    state.tool_call_count += 1
    state.processed_tool_call_count += 1
    fingerprint = make_action_fingerprint(
        tool_name,
        arguments,
        workspace_version,
    )
    state.last_action = fingerprint
    state.action_history.add(fingerprint)

def is_repeated_action(
    state: AgentLoopState,
    tool_name: str,
    arguments: dict[str, Any],
    workspace_version: int = 0,
    include_history: bool = False,
) -> bool:
    fingerprint = make_action_fingerprint(
        tool_name,
        arguments,
        workspace_version,
    )
    return state.last_action == fingerprint or (
        include_history and fingerprint in state.action_history
    )
