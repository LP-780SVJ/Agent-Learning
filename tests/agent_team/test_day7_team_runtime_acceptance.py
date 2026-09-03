from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from codeteam.agent.runtime_models import (
    CodingAgentRunRequest,
    CodingAgentRunResult,
    RuntimeStatus,
    VerificationEvidence,
)
from codeteam.agent_team.mailbox import AgentMessage, AgentMessageType
from codeteam.agent_team.models import AgentRole, WorkerAssignment
from codeteam.agent_team.scheduler import TaskClaim
from codeteam.agent_team.team_artifacts import (
    TeamArtifactError,
    TeamRunArtifactStore,
)
from codeteam.agent_team.team_budget import (
    TeamBudgetLedger,
    WeightedTeamBudgetPolicy,
)
from codeteam.agent_team.team_models import (
    NodeBudgetAllocation,
    NodeExecutionResult,
    NodeTiming,
    TeamProgressState,
)
from codeteam.agent_team.team_planning import DeterministicSingleNodePlanner
from codeteam.agent_team.team_runtime import (
    TeamCodingRuntime,
    TeamResultProtocolError,
    _validate_result_fence,
)
from codeteam.agent_team.team_runtime_provider import LocalTeamRuntimeProvider
from codeteam.agent_team.worker_executor import (
    WorkerExecutionRequest,
    WorkerExecutor,
)


def _parent_request(tmp_path: Path) -> CodingAgentRunRequest:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return CodingAgentRunRequest(
        task_id="task-acceptance",
        task="Implement and verify the requested behavior.",
        workspace_root=workspace,
        provider_id="provider-under-test",
        model_id="model-under-test",
        max_steps=25,
        max_tool_calls=50,
        max_repairs=4,
        max_protocol_repairs=2,
        finalization_reserve_steps=4,
        verification_commands=(("pytest", "-q"),),
        task_verification_commands=(("pytest", "tests/task", "-q"),),
    )


def _assignment(node_id: str = "node-1") -> WorkerAssignment:
    return WorkerAssignment(
        assignment_id=node_id,
        task_id="task-acceptance",
        source_step_id=node_id,
        role=AgentRole.BACKEND,
        goal="Implement the backend change.",
        expected_output="A verified patch.",
        required_capabilities=("python", "patch"),
        allow_workspace_write=False,
        budget_weight=1,
    )


def _claim(**updates: object) -> TaskClaim:
    values: dict[str, object] = {
        "node_id": "node-1",
        "worker_id": "worker-backend-1",
        "attempt": 1,
        "claimed_at": 1.0,
        "runtime_id": "runtime-current",
        "worker_generation": 2,
    }
    values.update(updates)
    return TaskClaim.model_validate(values)


def _node_result(**updates: object) -> NodeExecutionResult:
    values: dict[str, object] = {
        "node_id": "node-1",
        "worker_id": "worker-backend-1",
        "runtime_id": "runtime-current",
        "worker_generation": 2,
        "attempt": 1,
        "status": RuntimeStatus.COMPLETED,
        "timing": NodeTiming(ready_at=0.0, started_at=1.0, finished_at=2.0),
    }
    values.update(updates)
    return NodeExecutionResult.model_validate(values)


class RecordingRuntime:
    def __init__(self, result_factory: object | None = None) -> None:
        self.requests: list[CodingAgentRunRequest] = []
        self._result_factory = result_factory

    def run(self, request: CodingAgentRunRequest) -> CodingAgentRunResult:
        self.requests.append(request)
        if callable(self._result_factory):
            return self._result_factory(request)
        return CodingAgentRunResult(
            task_id=request.task_id,
            status=RuntimeStatus.COMPLETED,
            summary="completed",
            workspace_root=request.workspace_root,
            steps_used=1,
            tool_calls_used=1,
        )


def test_worker_executor_preserves_runtime_contract_budget_and_fence(
    tmp_path: Path,
) -> None:
    parent = _parent_request(tmp_path)
    runtime = RecordingRuntime()
    claim = _claim()
    result = WorkerExecutor(runtime).execute(
        WorkerExecutionRequest(
            parent_request=parent,
            assignment=_assignment(),
            claim=claim,
            workspace_root=parent.workspace_root,
            budget=NodeBudgetAllocation(
                node_id="node-1",
                weight=1,
                max_steps=5,
                max_tool_calls=9,
                max_repairs=2,
                max_protocol_repairs=1,
            ),
            ready_at=0.5,
        )
    )

    child = runtime.requests[0]
    assert child.provider_id == parent.provider_id
    assert child.model_id == parent.model_id
    assert child.verification_commands == parent.verification_commands
    assert child.task_verification_commands == parent.task_verification_commands
    assert child.max_steps == child.effective_max_steps == 5
    assert child.max_tool_calls == 9
    assert child.max_repairs == 2
    assert child.max_protocol_repairs == 1
    assert child.finalization_reserve_steps == 4
    assert child.workspace_write_allowed is False
    assert child.initial_messages == ()
    assert (result.runtime_id, result.worker_generation, result.attempt) == (
        claim.runtime_id,
        claim.worker_generation,
        claim.attempt,
    )


def test_team_budget_reserve_hard_caps_and_uncapped_usage_are_auditable(
    tmp_path: Path,
) -> None:
    parent = _parent_request(tmp_path)
    assignments = (_assignment("node-1"), _assignment("node-2"))
    allocation = WeightedTeamBudgetPolicy().allocate(
        parent=parent,
        assignments=assignments,
    )

    assert sum(item.max_steps for item in allocation.nodes.values()) == 20
    assert allocation.reserve_steps == 5
    assert sum(item.max_tool_calls for item in allocation.nodes.values()) == 40
    assert allocation.reserve_tool_calls == 10
    assert all(item.max_steps <= parent.max_steps for item in allocation.nodes.values())

    ledger = TeamBudgetLedger(allocation)
    node_budget = allocation.nodes["node-1"]
    ledger.record(
        "node-1",
        CodingAgentRunResult(
            task_id="child",
            status=RuntimeStatus.COMPLETED,
            summary="done",
            workspace_root=parent.workspace_root,
            steps_used=node_budget.max_steps,
            tool_calls_used=node_budget.max_tool_calls,
            input_tokens=100,
            output_tokens=25,
            cost_usd=1.25,
        ),
    )
    assert ledger.usage.input_tokens == 100
    assert ledger.usage.output_tokens == 25
    assert ledger.usage.cost_usd == 1.25
    assert ledger.can_dispatch("node-1") is False


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("runtime_id", "runtime-stale"),
        ("worker_generation", 1),
        ("attempt", 2),
    ),
)
def test_each_result_fence_dimension_rejects_a_stale_value(
    field: str,
    value: object,
) -> None:
    claim = _claim()
    message = AgentMessage(
        message_id="message-1",
        sender_id=claim.worker_id,
        recipient_id="lead",
        message_type=AgentMessageType.TASK_COMPLETED,
        task_id="task-acceptance",
        node_id=claim.node_id,
        correlation_id="claim-node-1-attempt-1",
        payload={
            "runtime_id": claim.runtime_id,
            "worker_generation": claim.worker_generation,
            "attempt": claim.attempt,
        },
    )

    with pytest.raises(TeamResultProtocolError, match="fence"):
        _validate_result_fence(claim, message, _node_result(**{field: value}))


def test_node_artifact_replace_failure_keeps_previous_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    store = TeamRunArtifactStore(session_dir)
    original = _node_result(error="old snapshot")
    reference = store.write_node_result(original)

    def fail_replace(source: Path, target: Path) -> None:
        del source, target
        raise OSError("injected replace failure")

    monkeypatch.setattr("codeteam.agent_team.team_artifacts.os.replace", fail_replace)
    with pytest.raises(OSError, match="injected replace failure"):
        store.write_node_result(_node_result(error="new snapshot"))

    assert store.load_node_result(reference) == original
    assert not tuple((session_dir / "artifacts" / "nodes").glob("*.tmp"))


def test_artifact_missing_truncated_and_symlink_escape_are_detected(
    tmp_path: Path,
) -> None:
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    store = TeamRunArtifactStore(session_dir)
    reference = store.write_node_result(_node_result())
    (session_dir / reference.path).unlink()
    with pytest.raises(TeamArtifactError, match="missing or unsafe"):
        store.load_node_result(reference)

    parent = _parent_request(tmp_path)
    allocation = WeightedTeamBudgetPolicy().allocate(
        parent=parent,
        assignments=(_assignment(),),
    )
    store.write_progress(
        TeamProgressState(task_id=parent.task_id, allocation=allocation)
    )
    (session_dir / "artifacts" / "team_progress.json").write_text(
        "{",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        store.load_progress()

    second_session = tmp_path / "session-symlink"
    second_session.mkdir()
    second_store = TeamRunArtifactStore(second_session)
    outside = tmp_path / "outside"
    outside.mkdir()
    (second_session / "artifacts" / "nodes").symlink_to(
        outside,
        target_is_directory=True,
    )
    with pytest.raises(TeamArtifactError, match="escapes"):
        second_store.write_node_result(_node_result())
    assert tuple(outside.iterdir()) == ()


def test_team_result_does_not_trust_worker_reported_workspace_evidence(
    tmp_path: Path,
) -> None:
    def forged_result(request: CodingAgentRunRequest) -> CodingAgentRunResult:
        return CodingAgentRunResult(
            task_id=request.task_id,
            status=RuntimeStatus.COMPLETED,
            summary="worker self-report",
            workspace_root=request.workspace_root,
            changed_files=("forged.py",),
            diff="FORGED_DIFF_EVIDENCE",
            verification=(
                VerificationEvidence(argv=("fake-check",), passed=True),
            ),
            steps_used=1,
            tool_calls_used=1,
        )

    parent = _parent_request(tmp_path)
    result = TeamCodingRuntime(
        planner=DeterministicSingleNodePlanner(),
        worker_executor=WorkerExecutor(RecordingRuntime(forged_result)),
        runtime_provider=LocalTeamRuntimeProvider(tmp_path / "state"),
    ).run_team(parent)

    assert tuple(parent.workspace_root.iterdir()) == ()
    if (
        result.runtime_result.changed_files
        or result.runtime_result.diff
        or result.runtime_result.verification
    ):
        pytest.fail("Team result trusted unverified Worker workspace evidence")


def test_team_artifacts_redact_credential_markers_from_worker_failures(
    tmp_path: Path,
) -> None:
    marker = "credential-marker-for-redaction-test"

    class RaisingRuntime:
        def run(self, request: CodingAgentRunRequest) -> CodingAgentRunResult:
            del request
            raise RuntimeError(marker)

    parent = _parent_request(tmp_path)
    TeamCodingRuntime(
        planner=DeterministicSingleNodePlanner(),
        worker_executor=WorkerExecutor(RaisingRuntime()),
        runtime_provider=LocalTeamRuntimeProvider(tmp_path / "state"),
    ).run_team(parent)

    artifact_payloads = "".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "state").rglob("*.json")
    )
    if marker in artifact_payloads:
        pytest.fail("Team artifact persisted an unredacted credential marker")
