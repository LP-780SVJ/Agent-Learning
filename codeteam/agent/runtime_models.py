from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from codeteam.schemas.messages import Message


class RuntimeStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class CompactionMode(str, Enum):
    STRUCTURED = "structured"
    NONE = "none"
    NAIVE = "naive"


class CodingAgentRunRequest(BaseModel):
    task_id: str = Field(min_length=1)
    task: str = Field(min_length=1)
    workspace_root: Path
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    context_budget: int = Field(default=4096, gt=0)
    max_steps: int = Field(default=20, gt=0)
    max_tool_calls: int = Field(default=40, gt=0)
    max_repairs: int = Field(default=3, ge=0)
    max_protocol_repairs: int = Field(default=2, ge=0, le=2)
    compaction_mode: CompactionMode = CompactionMode.STRUCTURED
    planning_enabled: bool = True
    verification_commands: tuple[tuple[str, ...], ...] = ()
    task_verification_commands: tuple[tuple[str, ...], ...] = ()
    checkpoint_state_root: Path | None = None
    initial_messages: tuple[Message, ...] = ()
    initial_protocol_repair_streak: int = Field(default=0, ge=0, le=2)


class VerificationEvidence(BaseModel):
    argv: tuple[str, ...]
    passed: bool
    exit_code: int | None = None
    duration_ms: float = 0.0
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    completion_required: bool = False


class ModelOutputEvidence(BaseModel):
    """Raw provider response retained outside the canonical conversation."""

    step: int = Field(gt=0)
    raw_content: str
    dialect: str | None = None
    canonical_payload: dict[str, object] | None = None
    parse_error: str | None = None
    model: str = "unknown"
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class CodingAgentRunResult(BaseModel):
    task_id: str
    status: RuntimeStatus
    summary: str
    workspace_root: Path
    diff: str = ""
    changed_files: tuple[str, ...] = ()
    checkpoint_ids: tuple[str, ...] = ()
    verification: tuple[VerificationEvidence, ...] = ()
    patch_attempts: int = 0
    steps_used: int = 0
    tool_calls_used: int = 0
    repair_attempts: int = 0
    protocol_repairs_used: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    model_duration_ms: int = 0
    tool_duration_ms: int = 0
    repair_duration_ms: int = 0
    failure_category: str | None = None
    error: str | None = None
    sandbox_preflight_available: bool | None = None
    sandbox_preflight_category: str | None = None
    messages: tuple[Message, ...] = ()
    model_outputs: tuple[ModelOutputEvidence, ...] = ()
    events: tuple[str, ...] = ()
