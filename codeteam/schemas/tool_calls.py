from typing import Any

from pydantic import BaseModel


class ToolCall(BaseModel):
    # Runtime-owned and assigned after schema validation.
    call_id: str | None = None
    # Opaque provider correlation, used only for transport round-trip.
    provider_call_id: str | None = None
    name: str
    arguments: dict[str, Any]


class ToolResult(BaseModel):
    call_id: str
    provider_call_id: str | None = None
    name: str
    content: str
    success: bool
    error: str | None = None
