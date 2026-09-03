"""Structured Team Coding Runtime results and metrics."""

from __future__ import annotations

from enum import Enum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from codeteam.agent.runtime_models import (
    CodingAgentRunResult,
    RuntimeArtifactRef,
    RuntimeStatus,
)
from codeteam.agent_team.models import WorkerAssignment
from codeteam.agent_team.workspace_evidence import TrustedWorkspaceEvidence

TEAM_RUN_ARTIFACT_SCHEMA_VERSION = 2


class TeamModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TeamControlStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class TeamFailureCategory(str, Enum):
    PLANNING = "planning_failure"
    SCHEDULER = "scheduler_failure"
    NO_COMPATIBLE_WORKER = "no_compatible_worker"
    WORKER_RUNTIME = "worker_runtime_failure"
    PROVIDER = "provider_failure"
    ENVIRONMENT = "environment_failure"
    PROTOCOL = "protocol_failure"
    DURABILITY = "durability_failure"
    BUDGET = "budget_exhausted"
    INTERRUPTED = "interrupted"


class NodeBudgetAllocation(TeamModel):
    node_id: str = Field(min_length=1)
    weight: int = Field(ge=1, le=5)
    max_steps: int = Field(ge=0)
    max_tool_calls: int = Field(ge=0)
    max_repairs: int = Field(ge=0)
    max_protocol_repairs: int = Field(ge=0, le=2)


class TeamBudgetAllocation(TeamModel):
    global_max_steps: int = Field(gt=0)
    global_max_tool_calls: int = Field(gt=0)
    global_max_repairs: int = Field(ge=0)
    reserve_steps: int = Field(ge=0)
    reserve_tool_calls: int = Field(ge=0)
    weight_fallback: bool = False
    weight_fallback_reason: str | None = None
    nodes: dict[str, NodeBudgetAllocation]


class TeamBudgetUsage(TeamModel):
    steps: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    repairs: int = Field(default=0, ge=0)
    protocol_repairs: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)


class NodeTiming(TeamModel):
    ready_at: float = Field(ge=0, allow_inf_nan=False)
    started_at: float = Field(ge=0, allow_inf_nan=False)
    finished_at: float = Field(ge=0, allow_inf_nan=False)

    @property
    def scheduler_wait_seconds(self) -> float:
        return max(0.0, self.started_at - self.ready_at)

    @property
    def busy_seconds(self) -> float:
        return max(0.0, self.finished_at - self.started_at)


class NodeExecutionResult(TeamModel):
    node_id: str = Field(min_length=1)
    worker_id: str = Field(min_length=1)
    runtime_id: str = Field(min_length=1)
    worker_generation: int = Field(ge=1)
    attempt: int = Field(ge=1)
    status: RuntimeStatus
    runtime_result: CodingAgentRunResult | None = Field(
        default=None,
        validation_alias=AliasChoices("runtime_result", "worker_reported_result"),
        serialization_alias="worker_reported_result",
    )
    retryable: bool = False
    failure_category: str | None = None
    error_code: str | None = None
    exception_type: str | None = None
    error_summary_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    error: str | None = None
    timing: NodeTiming

class TeamUsage(TeamModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    steps: int = Field(default=0, ge=0)
    repairs: int = Field(default=0, ge=0)


class TeamMetrics(TeamModel):
    wall_seconds: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    aggregate_worker_seconds: float = Field(
        default=0.0, ge=0, allow_inf_nan=False
    )
    scheduler_wait_seconds: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    max_parallelism: int = Field(default=0, ge=0)
    configured_workers: int = Field(default=1, ge=1)
    retries: int = Field(default=0, ge=0)
    messages_sent: int = Field(default=0, ge=0)
    messages_acked: int = Field(default=0, ge=0)
    usage: TeamUsage = Field(default_factory=TeamUsage)

    @property
    def utilization(self) -> float:
        capacity = self.configured_workers * self.wall_seconds
        return self.aggregate_worker_seconds / capacity if capacity > 0 else 0.0


class TeamRunArtifact(TeamModel):
    schema_version: int = Field(default=TEAM_RUN_ARTIFACT_SCHEMA_VERSION, ge=1)
    task_id: str = Field(min_length=1)
    control_status: TeamControlStatus
    dag_dependencies: dict[str, frozenset[str]]
    worker_assignments: tuple[WorkerAssignment, ...]
    node_results: tuple[NodeExecutionResult, ...] = Field(
        validation_alias=AliasChoices(
            "node_results",
            "worker_reported_node_results",
        ),
        serialization_alias="worker_reported_node_results",
    )
    trusted_workspace_evidence: TrustedWorkspaceEvidence
    blocked_nodes: tuple[str, ...] = ()
    mailbox_messages: tuple[dict[str, object], ...] = ()
    event_timeline: tuple[dict[str, object], ...] = ()
    budget: TeamBudgetAllocation
    budget_usage: TeamBudgetUsage
    metrics: TeamMetrics
    failure_category: TeamFailureCategory | None = None
    failure_reason: str | None = None

class TeamProgressState(TeamModel):
    """Durable budget replay input; never stores Future or runtime objects."""

    schema_version: int = Field(default=1, ge=1)
    task_id: str = Field(min_length=1)
    allocation: TeamBudgetAllocation
    node_artifacts: tuple[RuntimeArtifactRef, ...] = ()


class TeamCodingRunResult(TeamModel):
    runtime_result: CodingAgentRunResult
    artifact: TeamRunArtifact
