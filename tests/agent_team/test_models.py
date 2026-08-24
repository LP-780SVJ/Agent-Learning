from __future__ import annotations

import pytest
from pydantic import ValidationError

from codeteam.agent_team.models import (
    AgentIdentity,
    AgentInfo,
    AgentRole,
    AgentStatus,
    LeadPlanningResult,
    WorkerAssignment,
)
from codeteam.planning.models import Plan, PlanStep, create_plan


def _plan(task_id: str = "task-1") -> Plan:
    return create_plan(
        plan_id="plan-1",
        task_id=task_id,
        steps=(
            PlanStep(
                step_id="P1",
                title="Inspect API service",
                description="Inspect backend API service.",
                relevant_files=("src/api.py",),
                verification="Review notes exist.",
            ),
            PlanStep(
                step_id="P2",
                title="Add regression tests",
                description="Add pytest coverage.",
                relevant_files=("tests/test_api.py",),
                verification="pytest tests/test_api.py",
            ),
        ),
    )


def _assignment(
    step_id: str,
    *,
    assignment_id: str | None = None,
    task_id: str = "task-1",
) -> WorkerAssignment:
    return WorkerAssignment(
        assignment_id=assignment_id or f"plan-1:{step_id}",
        task_id=task_id,
        source_step_id=step_id,
        role=AgentRole.BACKEND,
        goal=f"Complete {step_id}.",
        expected_output=f"{step_id} done.",
    )


def test_role_and_status_json_round_trip() -> None:
    info = AgentInfo(
        identity=AgentIdentity(
            agent_id="worker-backend-1",
            display_name="Backend Worker 1",
        ),
        role=AgentRole.BACKEND,
        status=AgentStatus.READY,
        capabilities=("api", "service"),
    )

    payload = info.model_dump(mode="json")
    restored = AgentInfo.model_validate(payload)

    assert payload["role"] == "backend"
    assert payload["status"] == "ready"
    assert restored.role is AgentRole.BACKEND
    assert restored.status is AgentStatus.READY


@pytest.mark.parametrize(
    ("agent_id", "display_name"),
    [
        ("", "Backend Worker"),
        ("worker-1", ""),
        ("   ", "Backend Worker"),
        ("worker-1", "   "),
    ],
)
def test_identity_rejects_blank_fields(
    agent_id: str,
    display_name: str,
) -> None:
    with pytest.raises(ValidationError):
        AgentIdentity(agent_id=agent_id, display_name=display_name)


def test_identity_fields_are_stripped() -> None:
    identity = AgentIdentity(
        agent_id="  worker-1  ",
        display_name="  Worker 1  ",
    )

    assert identity.agent_id == "worker-1"
    assert identity.display_name == "Worker 1"


def test_invalid_role_and_status_are_rejected() -> None:
    identity = AgentIdentity(agent_id="worker-1", display_name="Worker 1")

    with pytest.raises(ValidationError):
        AgentInfo(identity=identity, role="database-wizard")

    with pytest.raises(ValidationError):
        AgentInfo(identity=identity, role=AgentRole.TEST, status="alive")


def test_lead_planning_result_can_be_serialized() -> None:
    plan = _plan()
    result = LeadPlanningResult(
        task_id="task-1",
        plan=plan,
        assignments=(_assignment("P1"), _assignment("P2")),
    )

    restored = LeadPlanningResult.model_validate_json(result.model_dump_json())

    assert restored.task_id == "task-1"
    assert restored.plan.plan_id == "plan-1"
    assert [item.source_step_id for item in restored.assignments] == ["P1", "P2"]


def test_lead_planning_result_rejects_empty_assignments() -> None:
    with pytest.raises(ValidationError, match="assignments must not be empty"):
        LeadPlanningResult(task_id="task-1", plan=_plan(), assignments=())


def test_lead_planning_result_rejects_duplicate_assignment_ids() -> None:
    with pytest.raises(ValidationError, match="assignment_id values"):
        LeadPlanningResult(
            task_id="task-1",
            plan=_plan(),
            assignments=(
                _assignment("P1", assignment_id="same"),
                _assignment("P2", assignment_id="same"),
            ),
        )


def test_lead_planning_result_rejects_task_id_mismatch() -> None:
    with pytest.raises(ValidationError, match="plan.task_id"):
        LeadPlanningResult(
            task_id="task-2",
            plan=_plan(task_id="task-1"),
            assignments=(
                _assignment("P1", task_id="task-2"),
                _assignment("P2", task_id="task-2"),
            ),
        )


def test_lead_planning_result_rejects_assignment_task_mismatch() -> None:
    with pytest.raises(ValidationError, match="assignment.task_id"):
        LeadPlanningResult(
            task_id="task-1",
            plan=_plan(),
            assignments=(
                _assignment("P1"),
                _assignment("P2", task_id="task-2"),
            ),
        )


def test_lead_planning_result_rejects_missing_step_assignment() -> None:
    with pytest.raises(ValidationError, match="cover every plan step"):
        LeadPlanningResult(
            task_id="task-1",
            plan=_plan(),
            assignments=(_assignment("P1"),),
        )


def test_lead_planning_result_rejects_unknown_step_assignment() -> None:
    with pytest.raises(ValidationError, match="cover every plan step"):
        LeadPlanningResult(
            task_id="task-1",
            plan=_plan(),
            assignments=(_assignment("P1"), _assignment("P3")),
        )


def test_worker_assignment_rejects_lead_role() -> None:
    with pytest.raises(ValidationError, match="lead role"):
        WorkerAssignment(
            assignment_id="A1",
            task_id="task-1",
            source_step_id="P1",
            role=AgentRole.LEAD,
            goal="Coordinate work.",
            expected_output="A plan.",
        )


def test_empty_plan_cannot_be_reported_as_success() -> None:
    empty_plan = Plan(plan_id="plan-empty", task_id="task-1", steps=())

    with pytest.raises(ValidationError, match="assignments must not be empty"):
        LeadPlanningResult(task_id="task-1", plan=empty_plan, assignments=())
