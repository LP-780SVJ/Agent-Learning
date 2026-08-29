from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from codeteam.llm.base import ModelFinishState, ModelResponseMode
from codeteam.sandbox.verification_preflight import VerificationEnvironmentMetadata
from codeteam.schemas.messages import Message
from codeteam.schemas.tool_calls import ToolCall


class RuntimeStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class CompactionMode(str, Enum):
    STRUCTURED = "structured"
    NONE = "none"
    NAIVE = "naive"


class VerificationOutcomeCategory(str, Enum):
    PASSED = "passed"
    TEST_FAILED = "test_failed"
    ENVIRONMENT_FAILED = "verification_environment_failed"
    WORKSPACE_HYGIENE_FAILED = "workspace_hygiene_failed"


class VerificationEvidence(BaseModel):
    argv: tuple[str, ...]
    passed: bool
    category: VerificationOutcomeCategory = VerificationOutcomeCategory.TEST_FAILED
    environment_failure_category: str | None = None
    exit_code: int | None = None
    duration_ms: float = 0.0
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    completion_required: bool = False
    workspace_version: int = Field(default=0, ge=0)
    workspace_fingerprint_before: str | None = None
    workspace_fingerprint_after: str | None = None
    workspace_mutations: tuple[str, ...] = ()


class CodingAgentRunRequest(BaseModel):
    task_id: str = Field(min_length=1)
    task: str = Field(min_length=1)
    workspace_root: Path
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    context_budget: int = Field(default=4096, gt=0)
    max_output_tokens: int = Field(default=4096, gt=0)
    model_context_window: int = Field(default=32768, gt=0)
    safety_headroom_tokens: int = Field(default=1024, ge=0)
    native_tools: bool = True
    reasoning_enabled: bool | None = False
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
    initial_workspace_version: int = Field(default=0, ge=0)
    initial_verification: tuple[VerificationEvidence, ...] = ()
    initial_git_diff_checked_version: int | None = Field(default=None, ge=0)
    initial_workspace_fingerprint: str | None = None
    initial_workspace_hygiene_clean: bool = True
    initial_progress_metrics: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_model_budget(self) -> CodingAgentRunRequest:
        if self.context_budget > (
            self.model_context_window
            - self.max_output_tokens
            - self.safety_headroom_tokens
        ):
            raise ValueError(
                "context_budget is the max input budget and must reserve "
                "max_output_tokens plus safety_headroom_tokens"
            )
        return self


class ModelOutputEvidence(BaseModel):
    """Raw provider response retained outside the canonical conversation."""

    step: int = Field(gt=0)
    raw_content: str | None = None
    native_tool_calls: tuple[ToolCall, ...] = ()
    dialect: str | None = None
    canonical_payload: dict[str, object] | None = None
    parse_error: str | None = None
    model: str = "unknown"
    provider: str | None = None
    response_id: str | None = None
    finish_state: ModelFinishState = ModelFinishState.STOP
    finish_reason: str | None = None
    actual_response_mode: ModelResponseMode | None = None
    incomplete_reason: str | None = None
    system_fingerprint: str | None = None
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
    verification_preflight_available: bool | None = None
    verification_preflight_category: str | None = None
    verification_environment: VerificationEnvironmentMetadata | None = None
    messages: tuple[Message, ...] = ()
    model_outputs: tuple[ModelOutputEvidence, ...] = ()
    events: tuple[str, ...] = ()
    workspace_version: int = 0
    workspace_fingerprint: str | None = None
    git_diff_checked_version: int | None = None
    workspace_hygiene_clean: bool = True
    completion_ready: bool = False
    post_ready_tool_calls: int = 0
    verification_workspace_mutations: int = 0
    first_patch_step: int | None = None
    pre_edit_step_count: int = 0
    pre_edit_tool_call_count: int = 0
    progress_advisory_count: int = 0
    progress_advisory_level_counts: dict[str, int] = Field(default_factory=dict)
    no_source_progress_pause_count: int = 0
    max_no_source_progress_streak: int = 0
    environment_inspection_count: int = 0
    initial_context_cache_hit_count: int = 0
    initial_context_reference_hit_count: int = 0
    source_progress_count: int = 0
    diagnostic_progress_count: int = 0
    first_environment_inspection_step: int | None = None
