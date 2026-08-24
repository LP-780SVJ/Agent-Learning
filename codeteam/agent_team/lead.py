from __future__ import annotations

from typing import Protocol

from codeteam.agent_team.models import (
    AgentInfo,
    AgentRole,
    LeadPlanningResult,
    WorkerAssignment,
)
from codeteam.planning.models import PlanStep
from codeteam.planning.planner import Planner, RepositoryContext
from codeteam.task.models import TaskSpec


class RoleAssigner(Protocol):
    def assign(self, step: PlanStep) -> AgentRole:
        ...


class DeterministicRoleAssigner:
    _RULES: tuple[tuple[AgentRole, tuple[str, ...]], ...] = (
        (AgentRole.TEST, ("test", "pytest", "fixture", "regression")),
        (AgentRole.FRONTEND, ("frontend", "ui", ".tsx", ".jsx")),
        (
            AgentRole.BACKEND,
            ("backend", "api", "service", "database", "repository"),
        ),
        (AgentRole.REVIEW, ("review", "audit", "security")),
    )

    def assign(self, step: PlanStep) -> AgentRole:
        evidence = " ".join(
            (
                step.title,
                step.description,
                *step.relevant_files,
                step.verification or "",
            )
        ).casefold()

        for role, keywords in self._RULES:
            if any(keyword in evidence for keyword in keywords):
                return role

        return AgentRole.GENERAL


class LeadAgent:
    def __init__(
        self,
        *,
        info: AgentInfo,
        planner: Planner,
        role_assigner: RoleAssigner,
    ) -> None:
        if info.role is not AgentRole.LEAD:
            raise ValueError("LeadAgent requires the lead role")
        self._info = info
        self._planner = planner
        self._role_assigner = role_assigner

    @property
    def info(self) -> AgentInfo:
        return self._info

    def create_plan(
        self,
        *,
        task: TaskSpec,
        repo_context: RepositoryContext,
    ) -> LeadPlanningResult:
        plan = self._planner.create_plan(
            task=task,
            repo_context=repo_context,
        )
        assignments = tuple(
            self._assignment_for(task=task, plan_id=plan.plan_id, step=step)
            for step in plan.steps
        )
        return LeadPlanningResult(
            task_id=task.task_id,
            plan=plan,
            assignments=assignments,
        )

    def _assignment_for(
        self,
        *,
        task: TaskSpec,
        plan_id: str,
        step: PlanStep,
    ) -> WorkerAssignment:
        return WorkerAssignment(
            assignment_id=f"{plan_id}:{step.step_id}",
            task_id=task.task_id,
            source_step_id=step.step_id,
            role=self._role_assigner.assign(step),
            goal=step.description,
            expected_output=step.verification or step.title,
            relevant_files=step.relevant_files,
            verification=step.verification,
        )
