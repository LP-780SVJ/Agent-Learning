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


class CompletionMode(str, Enum):
    MODEL_SUBMITTED = "model_submitted"
    RUNTIME_COMPLETION_GATE_SETTLEMENT = "runtime_completion_gate_settlement"
    RUNTIME_BUDGET_BOUNDARY_SETTLEMENT = "runtime_budget_boundary_settlement"


class CompactionMode(str, Enum):
    STRUCTURED = "structured"
    NONE = "none"
    NAIVE = "naive"


class VerificationOutcomeCategory(str, Enum):
    PASSED = "passed"
    TEST_FAILED = "test_failed"
    ENVIRONMENT_FAILED = "verification_environment_failed"
    WORKSPACE_HYGIENE_FAILED = "workspace_hygiene_failed"


class RuntimeArtifactRef(BaseModel):
    """Runtime-neutral reference to a separately persisted result artifact."""

    kind: str = Field(min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    path: Path
    schema_version: int = Field(default=1, ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _relative_safe_path(self) -> RuntimeArtifactRef:
        if (
            self.path.is_absolute()
            or self.path == Path(".")
            or ".." in self.path.parts
        ):
            raise ValueError("artifact path must be relative and cannot contain '..'")
        return self


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
    workspace_write_allowed: bool = True
    reasoning_enabled: bool | None = False
    max_steps: int = Field(default=20, gt=0)
    effective_max_steps: int | None = Field(default=None, gt=0)
    step_offset: int = Field(default=0, ge=0)
    finalization_reserve_steps: int | None = Field(default=None, gt=0)
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
        if self.effective_max_steps is None:
            self.effective_max_steps = self.step_offset + self.max_steps
        if self.step_offset + self.max_steps > self.effective_max_steps:
            raise ValueError(
                "step_offset plus max_steps cannot exceed effective_max_steps"
            )
        if (
            self.finalization_reserve_steps is not None
            and self.finalization_reserve_steps > self.effective_max_steps
        ):
            raise ValueError(
                "finalization_reserve_steps cannot exceed effective_max_steps"
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


class ModelRequestEvidence(BaseModel):
    """Bounded audit metadata for the request actually sent to a provider."""

    step: int = Field(gt=0)
    source_message_count: int = Field(ge=0)
    sent_message_count: int = Field(ge=0)
    dropped_message_count: int = Field(ge=0)
    estimated_input_tokens: int = Field(ge=0)
    context_budget: int = Field(gt=0)
    compaction_applied: bool = False
    visible_tool_observation_count: int = Field(ge=0)
    visible_read_paths: tuple[str, ...] = ()
    retained_provider_call_ids: tuple[str, ...] = ()


class CodingAgentRunResult(BaseModel):
    task_id: str
    status: RuntimeStatus
    summary: str
    workspace_root: Path
    diff: str = ""
    changed_files: tuple[str, ...] = ()
    checkpoint_ids: tuple[str, ...] = ()
    verification: tuple[VerificationEvidence, ...] = ()
    artifacts: tuple[RuntimeArtifactRef, ...] = ()
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
    failure_origin: str | None = None
    error: str | None = None
    declared_tool_calls: int = 0
    processed_tool_calls: int = 0
    rejected_tool_calls: int = 0
    unprocessed_safe_tool_calls: int = 0
    mechanical_no_progress_failure_count: int = 0
    batch_premature_stop_count: int = 0
    progress_guard_unprocessed_safe_tool_call_count: int = 0
    source_no_progress_failure_count: int = 0
    repeated_action_failure_count: int = 0
    sandbox_preflight_available: bool | None = None
    sandbox_preflight_category: str | None = None
    verification_preflight_available: bool | None = None
    verification_preflight_category: str | None = None
    verification_environment: VerificationEnvironmentMetadata | None = None
    messages: tuple[Message, ...] = ()
    model_outputs: tuple[ModelOutputEvidence, ...] = ()
    model_requests: tuple[ModelRequestEvidence, ...] = ()
    events: tuple[str, ...] = ()
    workspace_version: int = 0
    workspace_fingerprint: str | None = None
    git_diff_checked_version: int | None = None
    workspace_hygiene_clean: bool = True
    completion_ready: bool = False
    post_ready_tool_calls: int = 0
    completion_mode: CompletionMode | None = None
    effective_max_steps: int = 20
    finalization_reserve_steps: int = 4
    finalization_reserve_entered: bool = False
    finalization_reserve_entry_step: int | None = None
    budget_boundary_completion_count: int = 0
    post_ready_reopen_patch_count: int = 0
    post_ready_skipped_optional_tool_count: int = 0
    post_ready_nonfinalization_tool_count: int = 0
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
