"""Agent task evaluation models.

These models are separate from the Week2 retrieval eval models. Retrieval eval
scores file ranking; agent eval scores an actor on a fresh workspace with an
external grader.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from codeteam.agent.runtime_models import CompletionMode
from codeteam.sandbox.verification_preflight import VerificationEnvironmentMetadata


class AgentEvalSplit(str, Enum):
    DEV = "dev"
    HELDOUT = "heldout"


class AgentTaskType(str, Enum):
    BUG = "bug"
    FEATURE = "feature"
    REFACTOR = "refactor"
    MAINTENANCE = "maintenance"


class PatchActorStatus(str, Enum):
    COMPLETED = "completed"
    PROVIDER_BLOCKED = "provider_blocked"
    NO_PATCH = "no_patch"
    PATCH_FAILED = "patch_failed"
    ENVIRONMENT_BLOCKED = "environment_blocked"
    FAILED = "failed"


class EvalRunMode(str, Enum):
    BASELINE = "baseline"
    DIRECT_EXECUTE = "direct_execute"
    SINGLE_SHOT = "single_shot"
    NO_COMPACTION = "no_compaction"
    NAIVE_COMPACTION = "naive_compaction"


class EffectiveBudgetSource(str, Enum):
    RUN_CAP = "run_cap"
    TASK_DECLARED = "task_declared"
    TASK_AND_RUN_EQUAL = "task_and_run_equal"


class EvalBudget(BaseModel):
    max_steps: int = Field(default=20, gt=0)
    max_repairs: int = Field(default=3, ge=0)
    timeout_seconds: int = Field(default=900, gt=0)


class AgentEvalTask(BaseModel):
    task_id: str
    split: AgentEvalSplit
    type: AgentTaskType
    difficulty: str
    repo_fixture: Path
    base_commit: str
    setup_patch: Path | None = None
    setup_patch_sha256: str | None = None
    public_test_patch: Path | None = None
    public_test_patch_sha256: str | None = None
    prompt: str
    acceptance_commands: tuple[str, ...] = ()
    task_verification_commands: tuple[str, ...] = ()
    verification_commands: tuple[str, ...] = ()
    regression_commands: tuple[str, ...] = ()
    budget: EvalBudget = Field(default_factory=EvalBudget)
    safety_invariants: tuple[str, ...] = ()
    oracle_review_status: str = "unknown"

    @model_validator(mode="after")
    def validate_setup_patch_metadata(self) -> AgentEvalTask:
        if (self.setup_patch is None) != (self.setup_patch_sha256 is None):
            raise ValueError(
                "setup_patch and setup_patch_sha256 must be provided together"
            )
        if (self.public_test_patch is None) != (self.public_test_patch_sha256 is None):
            raise ValueError(
                "public_test_patch and public_test_patch_sha256 must be provided together"
            )
        if not self.verification_commands and self.regression_commands:
            self.verification_commands = self.regression_commands
        return self


class EvalRunConfig(BaseModel):
    run_id: str
    mode: EvalRunMode = EvalRunMode.BASELINE
    provider_id: str = "openai-compatible"
    model_id: str = "unknown"
    planning_enabled: bool = True
    repair_enabled: bool = True
    compaction_mode: str = "structured"
    context_budget: int = Field(default=4096, gt=0)
    max_output_tokens: int = Field(default=4096, gt=0)
    model_context_window: int = Field(default=32768, gt=0)
    safety_headroom_tokens: int = Field(default=1024, ge=0)
    native_tools: bool = True
    reasoning_enabled: bool = False
    task_timeout_seconds: int = Field(default=900, gt=0)
    max_steps: int = Field(default=20, gt=0)
    finalization_reserve_steps: int | None = Field(default=None, gt=0)
    max_repairs: int = Field(default=3, ge=0)
    max_protocol_repairs: int = Field(default=2, ge=0, le=2)

    @model_validator(mode="after")
    def validate_model_budget(self) -> EvalRunConfig:
        if self.context_budget > (
            self.model_context_window
            - self.max_output_tokens
            - self.safety_headroom_tokens
        ):
            raise ValueError(
                "context_budget must reserve max_output_tokens and "
                "safety_headroom_tokens"
            )
        return self


class PatchActorResult(BaseModel):
    task_id: str
    status: PatchActorStatus
    planning_enabled: bool
    repair_enabled: bool
    compaction_mode: str
    patch_attempts: int = 0
    repair_attempts: int = 0
    protocol_repair_attempts: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    steps: int = 0
    model_duration_ms: int = 0
    tool_duration_ms: int = 0
    repair_duration_ms: int = 0
    changed_files: tuple[str, ...] = ()
    applied_patch: bool = False
    generated_patch_sha256: str | None = None
    raw_model_output_sha256: str | None = None
    extracted_patch_sha256: str | None = None
    artifact_paths: tuple[str, ...] = ()
    patch_apply_stdout: str = ""
    patch_apply_stderr: str = ""
    error: str | None = None
    failure_category: str | None = None
    events: tuple[str, ...] = ()
    sandbox_preflight_available: bool | None = None
    sandbox_preflight_category: str | None = None
    verification_preflight_available: bool | None = None
    verification_preflight_category: str | None = None
    verification_environment: VerificationEnvironmentMetadata | None = None
    completion_ready: bool = False
    post_ready_tool_calls: int = 0
    completion_mode: CompletionMode | None = None
    task_declared_max_steps: int = 20
    run_max_steps_cap: int = 20
    effective_max_steps: int = 20
    effective_budget_source: EffectiveBudgetSource = (
        EffectiveBudgetSource.TASK_AND_RUN_EQUAL
    )
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


class GraderCommandResult(BaseModel):
    command: str
    argv: tuple[str, ...]
    exit_code: int | None
    duration_ms: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and self.error is None


class GradeResult(BaseModel):
    success: bool
    acceptance_passed: bool
    regression_passed: bool
    task_verification_passed: bool = True
    within_budget: bool
    security_passed: bool
    pristine_acceptance_passed: bool = False
    pristine_task_verification_passed: bool = False
    acceptance_results: tuple[GraderCommandResult, ...] = ()
    regression_results: tuple[GraderCommandResult, ...] = ()
    task_verification_results: tuple[GraderCommandResult, ...] = ()
    pristine_acceptance_results: tuple[GraderCommandResult, ...] = ()
    pristine_task_verification_results: tuple[GraderCommandResult, ...] = ()
    changed_files: tuple[str, ...] = ()
    safety_violations: tuple[str, ...] = ()
    failure_category: str | None = None
    error: str | None = None


class AgentEvalTaskResult(BaseModel):
    run_id: str
    task_id: str
    split: AgentEvalSplit
    type: AgentTaskType
    difficulty: str
    mode: EvalRunMode
    provider_id: str
    model_id: str
    success: bool
    actor_status: PatchActorStatus
    acceptance_passed: bool
    regression_passed: bool
    task_verification_passed: bool = True
    within_budget: bool
    security_passed: bool
    pristine_acceptance_passed: bool = False
    pristine_task_verification_passed: bool = False
    acceptance_results: tuple[GraderCommandResult, ...] = ()
    regression_results: tuple[GraderCommandResult, ...] = ()
    task_verification_results: tuple[GraderCommandResult, ...] = ()
    pristine_acceptance_results: tuple[GraderCommandResult, ...] = ()
    pristine_task_verification_results: tuple[GraderCommandResult, ...] = ()
    duration_ms: int
    steps: int = 0
    model_duration_ms: int = 0
    tool_duration_ms: int = 0
    repair_duration_ms: int = 0
    changed_files: tuple[str, ...] = ()
    patch_attempts: int = 0
    repair_attempts: int = 0
    protocol_repair_attempts: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    artifact_paths: tuple[str, ...] = ()
    failure_category: str | None = None
    error: str | None = None
    sandbox_preflight_available: bool | None = None
    sandbox_preflight_category: str | None = None
    verification_preflight_available: bool | None = None
    verification_preflight_category: str | None = None
    verification_environment: VerificationEnvironmentMetadata | None = None
    completion_ready: bool = False
    post_ready_tool_calls: int = 0
    completion_mode: CompletionMode | None = None
    task_declared_max_steps: int = 20
    run_max_steps_cap: int = 20
    effective_max_steps: int = 20
    effective_budget_source: EffectiveBudgetSource = (
        EffectiveBudgetSource.TASK_AND_RUN_EQUAL
    )
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


class AgentEvalRunSummary(BaseModel):
    run_id: str
    mode: EvalRunMode
    task_count: int
    success_count: int
    provider_blocked_count: int
    environment_blocked_count: int = 0
    protocol_repair_attempt_count: int = 0
    protocol_failed_count: int = 0
    acceptance_passed_count: int
    regression_passed_count: int
    task_verification_passed_count: int = 0
    security_passed_count: int
    pristine_acceptance_passed_count: int = 0
    pristine_task_verification_passed_count: int = 0
    actor_completed_count: int = 0
    within_budget_count: int = 0
    failure_category_counts: dict[str, int] = Field(default_factory=dict)
    completion_ready_count: int = 0
    completion_ready_but_actor_failed_count: int = 0
    post_ready_tool_call_count: int = 0
    completion_mode_counts: dict[str, int] = Field(default_factory=dict)
    grader_correct_but_actor_failed_count: int = 0
    grader_correct_actor_max_steps_count: int = 0
    budget_boundary_completion_count: int = 0
    finalization_reserve_entry_count: int = 0
    finalization_reserve_success_count: int = 0
    post_ready_reopen_patch_count: int = 0
    post_ready_skipped_optional_tool_count: int = 0
    post_ready_nonfinalization_tool_count: int = 0
    effective_max_steps_counts: dict[str, int] = Field(default_factory=dict)
    effective_budget_source_counts: dict[str, int] = Field(default_factory=dict)
    verification_workspace_mutation_count: int = 0
    first_patch_step_count: int = 0
    first_patch_step_by_task: dict[str, int | None] = Field(default_factory=dict)
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
    first_environment_inspection_step_count: int = 0
    first_environment_inspection_step_by_task: dict[str, int | None] = Field(
        default_factory=dict
    )
