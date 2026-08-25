"""Agent task evaluation models.

These models are separate from the Week2 retrieval eval models. Retrieval eval
scores file ranking; agent eval scores an actor on a fresh workspace with an
external grader.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


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
    FAILED = "failed"


class EvalRunMode(str, Enum):
    BASELINE = "baseline"
    DIRECT_EXECUTE = "direct_execute"
    SINGLE_SHOT = "single_shot"
    NO_COMPACTION = "no_compaction"
    NAIVE_COMPACTION = "naive_compaction"


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
    prompt: str
    acceptance_commands: tuple[str, ...] = ()
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
    task_timeout_seconds: int = Field(default=900, gt=0)
    max_steps: int = Field(default=20, gt=0)
    max_repairs: int = Field(default=3, ge=0)


class PatchActorResult(BaseModel):
    task_id: str
    status: PatchActorStatus
    planning_enabled: bool
    repair_enabled: bool
    compaction_mode: str
    patch_attempts: int = 0
    repair_attempts: int = 0
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
    events: tuple[str, ...] = ()


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
    within_budget: bool
    security_passed: bool
    pristine_acceptance_passed: bool = False
    acceptance_results: tuple[GraderCommandResult, ...] = ()
    regression_results: tuple[GraderCommandResult, ...] = ()
    pristine_acceptance_results: tuple[GraderCommandResult, ...] = ()
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
    within_budget: bool
    security_passed: bool
    pristine_acceptance_passed: bool = False
    acceptance_results: tuple[GraderCommandResult, ...] = ()
    regression_results: tuple[GraderCommandResult, ...] = ()
    pristine_acceptance_results: tuple[GraderCommandResult, ...] = ()
    duration_ms: int
    steps: int = 0
    model_duration_ms: int = 0
    tool_duration_ms: int = 0
    repair_duration_ms: int = 0
    changed_files: tuple[str, ...] = ()
    patch_attempts: int = 0
    repair_attempts: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    artifact_paths: tuple[str, ...] = ()
    failure_category: str | None = None
    error: str | None = None


class AgentEvalRunSummary(BaseModel):
    run_id: str
    mode: EvalRunMode
    task_count: int
    success_count: int
    provider_blocked_count: int
    acceptance_passed_count: int
    regression_passed_count: int
    security_passed_count: int
    pristine_acceptance_passed_count: int = 0
