from pathlib import Path

import pytest

from codeteam.agent.runtime_models import CodingAgentRunRequest, RuntimeStatus
from codeteam.agent_team.models import AgentRole, WorkerAssignment
from codeteam.agent_team.team_artifacts import (
    TeamArtifactError,
    TeamRunArtifactStore,
)
from codeteam.agent_team.team_budget import WeightedTeamBudgetPolicy
from codeteam.agent_team.team_models import (
    NodeExecutionResult,
    NodeTiming,
    TeamProgressState,
)


def _result() -> NodeExecutionResult:
    return NodeExecutionResult(
        node_id="node-1",
        worker_id="worker-1",
        runtime_id="runtime-1",
        worker_generation=1,
        attempt=1,
        status=RuntimeStatus.FAILED,
        error="expected test failure",
        timing=NodeTiming(ready_at=1.0, started_at=2.0, finished_at=3.0),
    )


def test_node_artifact_round_trip_is_hash_verified(tmp_path: Path) -> None:
    session_dir = tmp_path / "session-1"
    session_dir.mkdir()
    store = TeamRunArtifactStore(session_dir)

    reference = store.write_node_result(_result())
    restored = store.load_node_result(reference)

    assert restored == _result()
    assert reference.session_id == "session-1"
    assert not reference.path.is_absolute()


def test_tampered_node_artifact_is_rejected(tmp_path: Path) -> None:
    session_dir = tmp_path / "session-1"
    session_dir.mkdir()
    store = TeamRunArtifactStore(session_dir)
    reference = store.write_node_result(_result())
    (session_dir / reference.path).write_text("tampered\n", encoding="utf-8")

    with pytest.raises(TeamArtifactError, match="hash mismatch"):
        store.load_node_result(reference)


def test_progress_round_trip_keeps_hashed_node_references(tmp_path: Path) -> None:
    session_dir = tmp_path / "session-1"
    session_dir.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = TeamRunArtifactStore(session_dir)
    node_reference = store.write_node_result(_result())
    assignment = WorkerAssignment(
        assignment_id="node-1",
        task_id="task-1",
        source_step_id="node-1",
        role=AgentRole.BACKEND,
        goal="Implement.",
        expected_output="Done.",
        budget_weight=1,
    )
    allocation = WeightedTeamBudgetPolicy().allocate(
        parent=CodingAgentRunRequest(
            task_id="task-1",
            task="Implement.",
            workspace_root=workspace,
            provider_id="scripted",
            model_id="scripted",
        ),
        assignments=(assignment,),
    )

    store.write_progress(
        TeamProgressState(
            task_id="task-1",
            allocation=allocation,
            node_artifacts=(node_reference,),
        )
    )

    assert store.load_progress().node_artifacts == (node_reference,)
