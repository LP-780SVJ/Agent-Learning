from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

OutputFormat = Literal["text", "json"]


class RunRequest(BaseModel):
    task: str = Field(min_length=1)
    repo: Path = Path(".")
    output_format: OutputFormat = "text"
    provider_id: str | None = None
    model_id: str | None = None
    context_budget: int = Field(default=4096, gt=0)
    max_steps: int = Field(default=20, gt=0)
    max_tool_calls: int = Field(default=40, gt=0)
    max_repairs: int = Field(default=3, ge=0)
    compaction_mode: Literal["structured", "none", "naive"] = "structured"

    @model_validator(mode="after")
    def _check_provider_pair(self) -> RunRequest:
        if (self.provider_id is None) != (self.model_id is None):
            raise ValueError("provider_id 和 model_id 必须同时提供")
        return self


class ResumeRequest(BaseModel):
    session_id: str = Field(min_length=1)
    repo: Path = Path(".")
    output_format: OutputFormat = "text"
    provider_id: str | None = None
    model_id: str | None = None

    @model_validator(mode="after")
    def _check_override_pair(self) -> ResumeRequest:
        if (self.provider_id is None) != (self.model_id is None):
            raise ValueError("provider_id 和 model_id 必须同时提供")
        return self


class DiffRequest(BaseModel):
    session_id: str = Field(min_length=1)
    repo: Path = Path(".")
    base_ref: str = "HEAD"
    output_format: OutputFormat = "text"


class RollbackRequest(BaseModel):
    session_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    repo: Path = Path(".")
    output_format: OutputFormat = "text"
