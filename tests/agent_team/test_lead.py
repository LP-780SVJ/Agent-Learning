from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from codeteam.agent_team.lead import (
    DeterministicRoleAssigner,
    LeadAgent,
)
from codeteam.agent_team.models import AgentIdentity, AgentInfo, AgentRole
from codeteam.planning.models import Plan, PlanStep, create_plan
from codeteam.planning.planner import MockPlanner, RepositoryContext
from codeteam.task.models import TaskSpec


def _task(task_id: str = "task-1") -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        original_request="Add OAuth login and regression tests.",
        goal="Add OAuth login and regression tests.",
    )


def _repo_context() -> RepositoryContext:
    return RepositoryContext(
        summary="Auth application.",
        relevant_files=("src/auth/service.py", "tests/test_auth.py"),
        test_commands=("pytest tests/test_auth.py",),
    )


def _plan(task_id: str = "task-1") -> Plan:
    return create_plan(
        plan_id="plan-1",
        task_id=task_id,
        steps=(
            PlanStep(
                step_id="P1",
                title="Update auth API",
                description="Modify backend service behavior.",
                relevant_files=("src/auth/service.py",),
                verification="pytest tests/test_auth.py",
            ),
            PlanStep(
                step_id="P2",
                title="Add regression test",
                description="Add pytest regression coverage.",
                relevant_files=("tests/test_auth.py",),
                verification="pytest tests/test_auth.py",
            ),
        ),
    )


def _lead_info(role: AgentRole = AgentRole.LEAD) -> AgentInfo:
    return AgentInfo(
        identity=AgentIdentity(agent_id="lead-1", display_name="Lead 1"),
        role=role,
    )


@dataclass
class FakeRoleAssigner:
    role: AgentRole = AgentRole.BACKEND
    calls: list[str] = field(default_factory=list)

    def assign(self, step: PlanStep) -> AgentRole:
        self.calls.append(step.step_id)
        return self.role


def test_lead_uses_injected_planner_and_returns_same_plan() -> None:
    plan = _plan()
    planner = MockPlanner(plan=plan)
    assigner = FakeRoleAssigner(role=AgentRole.BACKEND)
    lead = LeadAgent(
        info=_lead_info(),
        planner=planner,
        role_assigner=assigner,
    )

    result = lead.create_plan(task=_task(), repo_context=_repo_context())

    assert result.plan is plan
    assert planner.calls == [("task-1", "Add OAuth login and regression tests.")]


def test_each_plan_step_gets_one_assignment() -> None:
    plan = _plan()
    lead = LeadAgent(
        info=_lead_info(),
        planner=MockPlanner(plan=plan),
        role_assigner=FakeRoleAssigner(role=AgentRole.BACKEND),
    )

    result = lead.create_plan(task=_task(), repo_context=_repo_context())

    assert [item.source_step_id for item in result.assignments] == ["P1", "P2"]
    assert [item.assignment_id for item in result.assignments] == [
        "plan-1:P1",
        "plan-1:P2",
    ]
    assert result.assignments[0].goal == "Modify backend service behavior."
    assert result.assignments[0].expected_output == "pytest tests/test_auth.py"


def test_role_assigner_is_called_once_per_step() -> None:
    assigner = FakeRoleAssigner(role=AgentRole.TEST)
    lead = LeadAgent(
        info=_lead_info(),
        planner=MockPlanner(plan=_plan()),
        role_assigner=assigner,
    )

    result = lead.create_plan(task=_task(), repo_context=_repo_context())

    assert assigner.calls == ["P1", "P2"]
    assert [item.role for item in result.assignments] == [
        AgentRole.TEST,
        AgentRole.TEST,
    ]


def test_lead_requires_lead_identity() -> None:
    with pytest.raises(ValueError, match="lead role"):
        LeadAgent(
            info=_lead_info(role=AgentRole.BACKEND),
            planner=MockPlanner(plan=_plan()),
            role_assigner=FakeRoleAssigner(),
        )


def test_lead_has_no_worker_execution_api() -> None:
    lead = LeadAgent(
        info=_lead_info(),
        planner=MockPlanner(plan=_plan()),
        role_assigner=FakeRoleAssigner(),
    )

    for name in ("execute", "apply_patch", "run_command", "run_tests"):
        assert not hasattr(lead, name)


def test_deterministic_role_assigner_is_stable() -> None:
    assigner = DeterministicRoleAssigner()
    step = PlanStep(
        step_id="P1",
        title="Add API regression test",
        description="Cover backend timeout behavior.",
        relevant_files=("src/api.py", "tests/test_api.py"),
        verification="pytest tests/test_api.py",
    )

    results = [assigner.assign(step) for _ in range(100)]

    assert results == [AgentRole.TEST] * 100


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (
            PlanStep(
                step_id="P1",
                title="Add pytest coverage",
                description="Add regression test.",
            ),
            AgentRole.TEST,
        ),
        (
            PlanStep(
                step_id="P2",
                title="Update login UI",
                description="Edit React component.",
                relevant_files=("src/Login.tsx",),
            ),
            AgentRole.FRONTEND,
        ),
        (
            PlanStep(
                step_id="P3",
                title="Update API service",
                description="Change backend repository behavior.",
            ),
            AgentRole.BACKEND,
        ),
        (
            PlanStep(
                step_id="P4",
                title="Security review",
                description="Audit risky behavior.",
            ),
            AgentRole.REVIEW,
        ),
        (
            PlanStep(
                step_id="P5",
                title="Clarify rollout notes",
                description="Prepare release note summary.",
            ),
            AgentRole.GENERAL,
        ),
    ],
)
def test_deterministic_role_assigner_rules(
    step: PlanStep,
    expected: AgentRole,
) -> None:
    assert DeterministicRoleAssigner().assign(step) is expected


def test_deterministic_role_assigner_conflict_priority() -> None:
    step = PlanStep(
        step_id="P1",
        title="Add pytest for frontend API",
        description="Contains test, frontend, and api keywords.",
        relevant_files=("src/Login.tsx", "src/api.py"),
        verification="pytest tests/test_login.py",
    )

    assert DeterministicRoleAssigner().assign(step) is AgentRole.TEST
