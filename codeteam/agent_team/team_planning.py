"""Planning boundary for Team Coding Runtime DAG construction."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, model_validator

from codeteam.agent.runtime_models import CodingAgentRunRequest
from codeteam.agent_team.models import (
    AgentRole,
    LeadPlanningResult,
    WorkerAssignment,
)
from codeteam.planning.models import Plan, PlanStep


class TeamPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_result: LeadPlanningResult
    dependencies: tuple[tuple[str, str], ...] = ()

    @model_validator(mode="after")
    def _dependencies_reference_assignments(self) -> TeamPlan:
        node_ids = {
            assignment.assignment_id
            for assignment in self.lead_result.assignments
        }
        if any(
            prerequisite == dependent
            or prerequisite not in node_ids
            or dependent not in node_ids
            for prerequisite, dependent in self.dependencies
        ):
            raise ValueError("dependencies contain a self-edge or unknown node")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError("dependencies must be unique")
        return self


class TeamPlanner(Protocol):
    def plan(self, request: CodingAgentRunRequest) -> TeamPlan: ...


class DeterministicSingleNodePlanner:
    """A reproducible first smoke: Team wiring with one real Worker node."""

    def __init__(
        self,
        *,
        role: AgentRole = AgentRole.BACKEND,
        required_capabilities: tuple[str, ...] = (
            "python",
            "api",
            "read",
            "search",
            "patch",
            "test",
            "git_diff",
        ),
        budget_weight: int = 5,
    ) -> None:
        self._role = role
        self._required_capabilities = required_capabilities
        self._budget_weight = budget_weight

    def plan(self, request: CodingAgentRunRequest) -> TeamPlan:
        step = PlanStep(
            step_id="worker-implementation",
            title="Implement and verify the requested change",
            description=request.task,
            verification="Run the request's configured verification commands.",
        )
        plan = Plan(
            plan_id=f"team-plan-{request.task_id}",
            task_id=request.task_id,
            steps=(step,),
        )
        assignment = WorkerAssignment(
            assignment_id="node-worker-implementation",
            task_id=request.task_id,
            source_step_id=step.step_id,
            role=self._role,
            goal=request.task,
            expected_output="A verified repository change and structured result.",
            verification=step.verification,
            required_capabilities=self._required_capabilities,
            allow_workspace_write=True,
            budget_weight=self._budget_weight,
        )
        return TeamPlan(
            lead_result=LeadPlanningResult(
                task_id=request.task_id,
                plan=plan,
                assignments=(assignment,),
            )
        )


class StaticTeamPlanner:
    """Test/script adapter for a prevalidated Lead result and explicit edges."""

    def __init__(self, plan: TeamPlan) -> None:
        self._plan = TeamPlan.model_validate(plan.model_dump())

    def plan(self, request: CodingAgentRunRequest) -> TeamPlan:
        if request.task_id != self._plan.lead_result.task_id:
            raise ValueError("request task_id does not match static Team plan")
        return TeamPlan.model_validate(self._plan.model_dump())
