from typing import Any

from pydantic import BaseModel


class ToolCall(BaseModel):
    call_id: str
    name: str
    arguments: dict[str, Any]


class ToolResult(BaseModel):
    call_id: str
    name: str
    content: str
    success: bool
    error: str | None = None
