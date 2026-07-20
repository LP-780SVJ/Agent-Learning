from typing import Literal

from pydantic import BaseModel

from codeteam.schemas.tool_calls import ToolCall


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
