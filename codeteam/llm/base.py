from __future__ import annotations

import json
from enum import Enum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field, model_validator

from codeteam.schemas.messages import Message
from codeteam.schemas.tool_calls import ToolCall
from codeteam.usage.token_counter import ApproximateTokenCounter


class ModelFinishState(str, Enum):
    """Provider-neutral meaning of one completed provider turn."""

    STOP = "stop"
    TOOL_CALLS = "tool_calls"
    OUTPUT_TRUNCATED = "output_truncated"
    CONTENT_FILTERED = "content_filtered"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    INCOMPLETE = "incomplete"
    INVALID_TOOL_CALL = "invalid_tool_call"
    OTHER = "other"


class ModelResponseMode(str, Enum):
    AUTO = "auto"
    NATIVE_TOOLS = "native_tools"
    JSON_OBJECT = "json_object"
    TEXT = "text"


class ModelUsage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class ModelRequest(BaseModel):
    """Provider-neutral request for one agent turn."""

    messages: tuple[Message, ...]
    # Existing ToolRegistry.describe() records; adapters own wire conversion.
    tools: tuple[dict[str, object], ...] = ()
    max_output_tokens: int = Field(default=4096, gt=0)
    max_input_tokens: int = Field(default=4096, gt=0)
    model_context_window: int = Field(default=32768, gt=0)
    safety_headroom_tokens: int = Field(default=1024, ge=0)
    temperature: float | None = Field(default=None, ge=0)
    response_mode: ModelResponseMode = ModelResponseMode.AUTO
    native_tools: bool = True
    reasoning_enabled: bool | None = False

    @model_validator(mode="after")
    def _validate_budget_partition(self) -> ModelRequest:
        available_input = (
            self.model_context_window
            - self.max_output_tokens
            - self.safety_headroom_tokens
        )
        if available_input <= 0:
            raise ValueError(
                "model context window must exceed max_output_tokens plus "
                "safety_headroom_tokens"
            )
        if self.max_input_tokens > available_input:
            raise ValueError(
                "max_input_tokens exceeds model_context_window - "
                "max_output_tokens - safety_headroom_tokens"
            )
        return self


class ModelTurn(BaseModel):
    """A provider-neutral agent turn, not a renamed text completion."""

    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    finish_state: ModelFinishState = ModelFinishState.STOP
    finish_reason: str | None = None
    usage: ModelUsage = Field(default_factory=ModelUsage)
    model: str = "mock-model"
    provider: str | None = None
    response_id: str | None = None
    actual_response_mode: ModelResponseMode | None = None
    incomplete_reason: str | None = None
    system_fingerprint: str | None = None


class InputBudgetExceededError(ValueError):
    """The serialized provider input does not fit its declared input budget."""


def estimate_model_request_tokens(request: ModelRequest) -> int:
    """Estimate complete structured input, including message/tool overhead."""

    payload = {
        "messages": [message.model_dump(mode="json") for message in request.messages],
        "tools": list(request.tools),
    }
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return ApproximateTokenCounter().count_text(serialized)


def validate_model_request_input(request: ModelRequest) -> int:
    estimated = estimate_model_request_tokens(request)
    if estimated > request.max_input_tokens:
        raise InputBudgetExceededError(
            f"estimated provider input {estimated} exceeds max_input_tokens "
            f"{request.max_input_tokens}"
        )
    return estimated


# Compatibility DTO for older callers and recorded fixtures. Production uses
# ModelRequest -> ModelTurn.
class ModelResponse(BaseModel):
    content: str
    model: str = "mock-model"
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


@runtime_checkable
class ModelClient(Protocol):
    def turn(self, request: ModelRequest) -> ModelTurn:
        """Execute one provider-neutral agent turn."""
        ...


@runtime_checkable
class LegacyModelClient(Protocol):
    def complete(self, messages: list[Message]) -> str | ModelResponse:
        """Compatibility text-completion shape for old fakes and planners."""
        ...
