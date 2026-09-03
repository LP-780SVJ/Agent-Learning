from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, field_validator, model_validator

from codeteam.planning.models import Plan


class AgentRole(str, Enum):
    LEAD = "lead"
    BACKEND = "backend"
    FRONTEND = "frontend"
    TEST = "test"
    REVIEW = "review"
    GENERAL = "general"


class AgentStatus(str, Enum):
    CREATED = "created"
    READY = "ready"
    BUSY = "busy"
    FAILED = "failed"
    RESTARTING = "restarting"
    STOPPED = "stopped"


class AgentIdentity(BaseModel):
    agent_id: str
    display_name: str

    @field_validator("agent_id", "display_name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("identity fields must not be blank")
        return stripped


class AgentInfo(BaseModel):
    """Identity and bootstrap status; live state belongs to AgentRegistry."""

    identity: AgentIdentity
    role: AgentRole
    status: AgentStatus = AgentStatus.CREATED
    capabilities: tuple[str, ...] = ()

    @field_validator("capabilities")
    @classmethod
    def _normalized_capabilities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip().casefold() for item in value)
        if any(not item for item in normalized):
            raise ValueError("capabilities must not contain blank values")
        if len(set(normalized)) != len(normalized):
            raise ValueError("capabilities must be unique")
        return normalized


class WorkerAssignment(BaseModel):
    assignment_id: str
    task_id: str
    source_step_id: str
    role: AgentRole
    goal: str
    expected_output: str
    relevant_files: tuple[str, ...] = ()
    verification: str | None = None
    required_capabilities: tuple[str, ...] = ()
    allow_workspace_write: bool = True
    budget_weight: int | None = None

    @field_validator(
        "assignment_id",
        "task_id",
        "source_step_id",
        "goal",
        "expected_output",
    )
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("assignment fields must not be blank")
        return stripped

    @field_validator("role")
    @classmethod
    def _worker_role(cls, value: AgentRole) -> AgentRole:
        if value is AgentRole.LEAD:
            raise ValueError("WorkerAssignment cannot target the lead role")
        return value

    @field_validator("required_capabilities")
    @classmethod
    def _normalized_required_capabilities(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        normalized = tuple(item.strip().casefold() for item in value)
        if any(not item for item in normalized):
            raise ValueError("required capabilities must not contain blank values")
        if len(set(normalized)) != len(normalized):
            raise ValueError("required capabilities must be unique")
        return normalized

    @field_validator("budget_weight", mode="before")
    @classmethod
    def _normalize_budget_weight(cls, value: object) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = int(value)
            except ValueError:
                return None
        else:
            return None
        return parsed if 1 <= parsed <= 5 else None


class LeadPlanningResult(BaseModel):
    task_id: str
    plan: Plan
    assignments: tuple[WorkerAssignment, ...]

    @field_validator("task_id")
    @classmethod
    def _task_id_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("task_id must not be blank")
        return stripped

    @model_validator(mode="after")
    def _check_consistency(self) -> LeadPlanningResult:
        if self.plan.task_id != self.task_id:
            raise ValueError("plan.task_id must match result.task_id")

        if not self.assignments:
            raise ValueError("assignments must not be empty")

        assignment_ids = [item.assignment_id for item in self.assignments]
        if len(set(assignment_ids)) != len(assignment_ids):
            raise ValueError(f"assignment_id values must be unique: {assignment_ids}")

        for assignment in self.assignments:
            if assignment.task_id != self.task_id:
                raise ValueError("assignment.task_id must match result.task_id")

        step_ids = {step.step_id for step in self.plan.steps}
        assignment_step_ids = {
            assignment.source_step_id for assignment in self.assignments
        }
        if assignment_step_ids != step_ids:
            raise ValueError("assignments must cover every plan step")

        return self
