from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from codeteam.agent.runtime_models import (
    CodingAgentRunRequest,
    CodingAgentRunResult,
    RuntimeStatus,
)
from codeteam.agent_team.models import AgentInfo, AgentRole, WorkerAssignment
from codeteam.agent_team.team_budget import (
    TeamBudgetExceededError,
    TeamBudgetLedger,
    WeightedTeamBudgetPolicy,
)
from codeteam.agent_team.worker_pool import (
    assignment_compatibility_rank,
    static_worker_infos,
)


def _request(tmp_path: Path, *, max_steps: int = 60) -> CodingAgentRunRequest:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return CodingAgentRunRequest(
        task_id="task-1",
        task="Implement the change.",
        workspace_root=workspace,
        provider_id="scripted",
        model_id="scripted",
        max_steps=max_steps,
        max_tool_calls=120,
        max_repairs=6,
    )


def _assignment(node_id: str, weight: int | str | None) -> WorkerAssignment:
    return WorkerAssignment(
        assignment_id=node_id,
        task_id="task-1",
        source_step_id=node_id,
        role=AgentRole.BACKEND,
        goal="Implement backend code.",
        expected_output="Verified code.",
        required_capabilities=("python", "patch"),
        budget_weight=cast(int | None, weight),
    )


def test_agent_capabilities_are_normalized_and_unique() -> None:
    backend = static_worker_infos()[1]

    assert "python" in backend.capabilities
    with pytest.raises(ValidationError, match="unique"):
        AgentInfo(
            identity=backend.identity,
            role=backend.role,
            capabilities=("Python", "python"),
        )


def test_static_pool_prefers_exact_role_then_general_fallback() -> None:
    backend_assignment = _assignment("backend", 3)
    read_assignment = backend_assignment.model_copy(
        update={
            "role": AgentRole.FRONTEND,
            "required_capabilities": ("read", "search"),
        }
    )
    general, backend, test_worker = static_worker_infos()

    assert assignment_compatibility_rank(backend_assignment, backend) == 0
    assert assignment_compatibility_rank(backend_assignment, general) is None
    assert assignment_compatibility_rank(read_assignment, general) == 1
    assert assignment_compatibility_rank(read_assignment, test_worker) is None


def test_invalid_lead_weight_falls_back_to_equal_allocation(tmp_path: Path) -> None:
    assignments = (_assignment("A", "invalid"), _assignment("B", 5))

    allocation = WeightedTeamBudgetPolicy().allocate(
        parent=_request(tmp_path),
        assignments=assignments,
    )

    assert allocation.weight_fallback is True
    assert {item.weight for item in allocation.nodes.values()} == {1}
    assert allocation.reserve_steps == 12
    assert sum(item.max_steps for item in allocation.nodes.values()) == 48


def test_constrained_weights_reserve_finalization_budget(tmp_path: Path) -> None:
    assignments = (
        _assignment("implementation", 3),
        _assignment("tests", 2),
        _assignment("review", 1),
    )

    allocation = WeightedTeamBudgetPolicy().allocate(
        parent=_request(tmp_path),
        assignments=assignments,
    )

    assert allocation.nodes["implementation"].max_steps == 24
    assert allocation.nodes["tests"].max_steps == 16
    assert allocation.nodes["review"].max_steps == 8
    assert sum(item.max_steps for item in allocation.nodes.values()) + 12 == 60


def test_budget_ledger_rejects_node_overrun(tmp_path: Path) -> None:
    assignment = _assignment("implementation", 5)
    allocation = WeightedTeamBudgetPolicy().allocate(
        parent=_request(tmp_path, max_steps=10),
        assignments=(assignment,),
    )
    ledger = TeamBudgetLedger(allocation)

    with pytest.raises(TeamBudgetExceededError, match="node budget"):
        ledger.record(
            assignment.assignment_id,
            CodingAgentRunResult(
                task_id="child",
                status=RuntimeStatus.COMPLETED,
                summary="done",
                workspace_root=tmp_path / "workspace",
                steps_used=allocation.nodes[assignment.assignment_id].max_steps + 1,
            ),
        )

    assert ledger.usage.steps == 0
