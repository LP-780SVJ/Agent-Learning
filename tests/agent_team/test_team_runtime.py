from __future__ import annotations

import subprocess
from pathlib import Path
from threading import Barrier, Lock
from typing import cast

import pytest

from codeteam.agent.runtime_models import (
    CodingAgentRunRequest,
    CodingAgentRunResult,
    RuntimeStatus,
    VerificationEvidence,
)
from codeteam.agent_team.dag import TaskStatus
from codeteam.agent_team.models import (
    AgentRole,
    LeadPlanningResult,
    WorkerAssignment,
)
from codeteam.agent_team.team_models import NodeExecutionResult, NodeTiming
from codeteam.agent_team.team_planning import (
    DeterministicSingleNodePlanner,
    StaticTeamPlanner,
    TeamPlan,
    TeamPlanner,
)
from codeteam.agent_team.team_runtime import (
    TeamCodingRuntime,
    TeamResultProtocolError,
)
from codeteam.agent_team.team_runtime_provider import (
    LocalTeamRuntimeProvider,
    TeamRuntimeHandle,
)
from codeteam.agent_team.worker_executor import (
    CodingRuntime,
    WorkerExecutionRequest,
    WorkerExecutor,
)
from codeteam.planning.models import Plan, PlanStep


class ScriptedRuntime:
    def __init__(self, statuses: list[RuntimeStatus] | None = None) -> None:
        self._statuses = statuses or [RuntimeStatus.COMPLETED]
        self._lock = Lock()
        self.requests: list[CodingAgentRunRequest] = []

    def run(self, request: CodingAgentRunRequest) -> CodingAgentRunResult:
        with self._lock:
            index = len(self.requests)
            self.requests.append(request)
            status = self._statuses[min(index, len(self._statuses) - 1)]
        changed_files: tuple[str, ...] = ()
        if status is RuntimeStatus.COMPLETED and request.workspace_write_allowed:
            (request.workspace_root / "app.py").write_text(
                "VALUE = 1\n",
                encoding="utf-8",
            )
            changed_files = ("worker-claimed-name.py",)
        return CodingAgentRunResult(
            task_id=request.task_id,
            status=status,
            summary=status.value,
            workspace_root=request.workspace_root,
            changed_files=changed_files,
            verification=(
                VerificationEvidence(argv=("worker-check",), passed=True),
            ),
            patch_attempts=1,
            steps_used=2,
            tool_calls_used=3,
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.001,
            failure_category="timeout" if status is RuntimeStatus.FAILED else None,
            error="transient timeout" if status is RuntimeStatus.FAILED else None,
        )


class BarrierRuntime:
    def __init__(self, parties: int) -> None:
        self.barrier = Barrier(parties)

    def run(self, request: CodingAgentRunRequest) -> CodingAgentRunResult:
        self.barrier.wait(timeout=5)
        return CodingAgentRunResult(
            task_id=request.task_id,
            status=RuntimeStatus.COMPLETED,
            summary="done",
            workspace_root=request.workspace_root,
            steps_used=1,
            tool_calls_used=1,
        )


class BudgetExhaustedRuntime:
    def run(self, request: CodingAgentRunRequest) -> CodingAgentRunResult:
        return CodingAgentRunResult(
            task_id=request.task_id,
            status=RuntimeStatus.FAILED,
            summary="tool budget exhausted",
            workspace_root=request.workspace_root,
            steps_used=2,
            tool_calls_used=request.max_tool_calls,
            failure_category="max_tool_calls",
            error="Agent stopped because max_tool_calls was reached.",
        )


class NoProgressRuntime:
    def run(self, request: CodingAgentRunRequest) -> CodingAgentRunResult:
        return CodingAgentRunResult(
            task_id=request.task_id,
            status=RuntimeStatus.FAILED,
            summary="cached exploration stalled",
            workspace_root=request.workspace_root,
            steps_used=5,
            tool_calls_used=12,
            failure_category="no_progress",
            failure_origin="cached_batch_stall",
            error="Agent repeated cached exploration.",
        )


class TrackingProvider(LocalTeamRuntimeProvider):
    handle: TeamRuntimeHandle | None = None

    def create(self, **kwargs: object) -> TeamRuntimeHandle:
        request = cast(CodingAgentRunRequest, kwargs["request"])
        plan = cast(TeamPlan, kwargs["plan"])
        self.handle = super().create(request=request, plan=plan)
        return self.handle


class StoppedBackendProvider(TrackingProvider):
    def create(self, **kwargs: object) -> TeamRuntimeHandle:
        handle = super().create(**kwargs)
        lease = handle.runtime.registry.lease("worker-backend-1")
        handle.runtime.stop_worker(lease)
        return handle


class StaleResultExecutor:
    def execute(self, request: WorkerExecutionRequest) -> NodeExecutionResult:
        claim = request.claim
        return NodeExecutionResult(
            node_id=claim.node_id,
            worker_id=claim.worker_id,
            runtime_id=claim.runtime_id,
            worker_generation=claim.worker_generation + 1,
            attempt=claim.attempt,
            status=RuntimeStatus.COMPLETED,
            timing=NodeTiming(ready_at=0.0, started_at=0.0, finished_at=0.0),
        )


def _request(tmp_path: Path, *, max_steps: int = 20) -> CodingAgentRunRequest:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    if not (workspace / ".git").exists():
        _git(workspace, "init", "-q")
        _git(workspace, "config", "user.name", "CodeTeam Tests")
        _git(workspace, "config", "user.email", "codeteam-tests@example.invalid")
        (workspace / "README.md").write_text("baseline\n", encoding="utf-8")
        _git(workspace, "add", "README.md")
        _git(workspace, "commit", "-qm", "baseline")
    return CodingAgentRunRequest(
        task_id="B01",
        task="Fix the expired refresh token mapping.",
        workspace_root=workspace,
        provider_id="scripted",
        model_id="scripted",
        max_steps=max_steps,
        max_tool_calls=40,
    )


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        shell=False,
        timeout=10,
        check=True,
    )


def _runtime(
    tmp_path: Path,
    scripted: CodingRuntime,
    *,
    planner: TeamPlanner | None = None,
    max_workers: int = 1,
    provider: LocalTeamRuntimeProvider | None = None,
) -> TeamCodingRuntime:
    return TeamCodingRuntime(
        planner=planner or DeterministicSingleNodePlanner(),
        worker_executor=WorkerExecutor(scripted),
        runtime_provider=provider or LocalTeamRuntimeProvider(tmp_path / "state"),
        max_workers=max_workers,
    )


def _static_plan(assignments: tuple[WorkerAssignment, ...]) -> StaticTeamPlanner:
    steps = tuple(
        PlanStep(
            step_id=assignment.source_step_id,
            title=assignment.goal,
            description=assignment.goal,
        )
        for assignment in assignments
    )
    return StaticTeamPlanner(
        TeamPlan(
            lead_result=LeadPlanningResult(
                task_id="B01",
                plan=Plan(plan_id="plan-B01", task_id="B01", steps=steps),
                assignments=assignments,
            ),
            dependencies=(),
        )
    )


def test_single_node_team_run_persists_artifact_and_common_reference(
    tmp_path: Path,
) -> None:
    scripted = ScriptedRuntime()

    result = _runtime(tmp_path, scripted).run_team(_request(tmp_path))

    assert result.runtime_result.status is RuntimeStatus.COMPLETED
    assert result.runtime_result.task_id == "B01"
    assert result.runtime_result.changed_files == ("app.py",)
    assert "VALUE = 1" in result.runtime_result.diff
    assert result.runtime_result.verification == ()
    assert result.artifact.control_status.value == "completed"
    assert result.artifact.metrics.messages_sent == 1
    assert result.artifact.metrics.messages_acked == 1
    assert result.artifact.metrics.usage.input_tokens == 10
    reference = result.runtime_result.artifacts[-1]
    assert reference.kind == "team_run"
    assert reference.session_id is not None
    artifact_path = tmp_path / "state" / reference.session_id / reference.path
    assert artifact_path.is_file()


def test_retryable_worker_failure_uses_new_attempt_and_stays_within_budget(
    tmp_path: Path,
) -> None:
    scripted = ScriptedRuntime([RuntimeStatus.FAILED, RuntimeStatus.COMPLETED])

    result = _runtime(tmp_path, scripted).run_team(_request(tmp_path))

    assert result.runtime_result.status is RuntimeStatus.COMPLETED
    assert [item.attempt for item in result.artifact.node_results] == [1, 2]
    assert result.artifact.metrics.retries == 1
    assert result.artifact.budget_usage.steps == 4
    assert result.runtime_result.patch_attempts == 2


def test_team_preserves_worker_budget_exhaustion_as_root_failure(
    tmp_path: Path,
) -> None:
    result = _runtime(tmp_path, BudgetExhaustedRuntime()).run_team(
        _request(tmp_path)
    )

    assert result.runtime_result.status is RuntimeStatus.FAILED
    assert result.runtime_result.failure_category == "budget_exhausted"
    assert "node-worker-implementation=max_tool_calls" in (
        result.runtime_result.error or ""
    )
    assert result.artifact.failure_category is not None
    assert result.artifact.failure_category.value == "budget_exhausted"


def test_team_preserves_specific_worker_failure_category_and_origin(
    tmp_path: Path,
) -> None:
    result = _runtime(tmp_path, NoProgressRuntime()).run_team(_request(tmp_path))

    assert result.runtime_result.status is RuntimeStatus.FAILED
    assert result.runtime_result.failure_category == "no_progress"
    assert result.runtime_result.failure_origin == "cached_batch_stall"
    assert result.artifact.failure_category is not None
    assert result.artifact.failure_category.value == "worker_runtime_failure"


def test_no_compatible_worker_pauses_without_running_worker_code(
    tmp_path: Path,
) -> None:
    assignment = WorkerAssignment(
        assignment_id="frontend",
        task_id="B01",
        source_step_id="frontend",
        role=AgentRole.FRONTEND,
        goal="Implement UI.",
        expected_output="UI complete.",
        required_capabilities=("typescript",),
        budget_weight=1,
    )
    scripted = ScriptedRuntime()

    result = _runtime(
        tmp_path,
        scripted,
        planner=_static_plan((assignment,)),
    ).run_team(_request(tmp_path))

    assert result.runtime_result.status is RuntimeStatus.PAUSED
    assert result.runtime_result.failure_category == "no_compatible_worker"
    assert scripted.requests == []


def test_compatible_general_worker_is_used_when_specialist_is_absent(
    tmp_path: Path,
) -> None:
    assignment = WorkerAssignment(
        assignment_id="frontend-read",
        task_id="B01",
        source_step_id="frontend-read",
        role=AgentRole.FRONTEND,
        goal="Inspect frontend files.",
        expected_output="Frontend notes.",
        required_capabilities=("read", "search"),
        allow_workspace_write=False,
        budget_weight=1,
    )
    scripted = ScriptedRuntime()

    result = _runtime(
        tmp_path,
        scripted,
        planner=_static_plan((assignment,)),
    ).run_team(_request(tmp_path))

    assert result.runtime_result.status is RuntimeStatus.FAILED
    assert result.runtime_result.failure_category == "no_trusted_workspace_change"
    assert result.artifact.control_status.value == "completed"
    assert result.artifact.node_results[0].worker_id == "worker-general-1"


def test_stopped_only_compatible_worker_pauses_instead_of_reporting_deadlock(
    tmp_path: Path,
) -> None:
    scripted = ScriptedRuntime()
    provider = StoppedBackendProvider(tmp_path / "state")

    result = _runtime(
        tmp_path,
        scripted,
        provider=provider,
    ).run_team(_request(tmp_path))

    assert result.runtime_result.status is RuntimeStatus.PAUSED
    assert result.runtime_result.failure_category == "no_compatible_worker"
    assert "currently available" in (result.runtime_result.error or "")
    assert scripted.requests == []


def test_concurrent_read_only_nodes_reach_three_workers(tmp_path: Path) -> None:
    assignments = (
        WorkerAssignment(
            assignment_id="general",
            task_id="B01",
            source_step_id="general",
            role=AgentRole.GENERAL,
            goal="Inspect files.",
            expected_output="Notes.",
            required_capabilities=("read",),
            allow_workspace_write=False,
            budget_weight=1,
        ),
        WorkerAssignment(
            assignment_id="backend",
            task_id="B01",
            source_step_id="backend",
            role=AgentRole.BACKEND,
            goal="Inspect backend.",
            expected_output="Backend notes.",
            required_capabilities=("python",),
            allow_workspace_write=False,
            budget_weight=1,
        ),
        WorkerAssignment(
            assignment_id="tests",
            task_id="B01",
            source_step_id="tests",
            role=AgentRole.TEST,
            goal="Inspect tests.",
            expected_output="Test notes.",
            required_capabilities=("pytest",),
            allow_workspace_write=False,
            budget_weight=1,
        ),
    )

    result = _runtime(
        tmp_path,
        BarrierRuntime(3),
        planner=_static_plan(assignments),
        max_workers=3,
    ).run_team(_request(tmp_path, max_steps=30))

    assert result.runtime_result.status is RuntimeStatus.FAILED
    assert result.runtime_result.failure_category == "no_trusted_workspace_change"
    assert result.artifact.control_status.value == "completed"
    assert result.artifact.metrics.max_parallelism == 3
    assert len(result.artifact.node_results) == 3


def test_duplicate_worker_file_claims_do_not_duplicate_trusted_git_evidence(
    tmp_path: Path,
) -> None:
    assignments = tuple(
        WorkerAssignment(
            assignment_id=f"backend-{index}",
            task_id="B01",
            source_step_id=f"backend-{index}",
            role=AgentRole.BACKEND,
            goal=f"Implement backend part {index}.",
            expected_output="A patch.",
            required_capabilities=("python", "patch"),
            allow_workspace_write=True,
            budget_weight=1,
        )
        for index in (1, 2)
    )

    result = _runtime(
        tmp_path,
        ScriptedRuntime(),
        planner=_static_plan(assignments),
        max_workers=1,
    ).run_team(_request(tmp_path, max_steps=30))

    assert result.runtime_result.status is RuntimeStatus.COMPLETED
    assert result.runtime_result.changed_files == ("app.py",)
    assert len(result.artifact.node_results) == 2
    assert all(
        item.runtime_result is not None
        and item.runtime_result.changed_files == ("worker-claimed-name.py",)
        for item in result.artifact.node_results
    )


def test_node_artifact_publication_failure_never_returns_trusted_common_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_publication(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError("injected node artifact publication failure")

    monkeypatch.setattr(
        "codeteam.agent_team.team_artifacts.TeamRunArtifactStore.write_node_result",
        fail_publication,
    )

    with pytest.raises(OSError, match="artifact publication failure"):
        _runtime(tmp_path, ScriptedRuntime()).run_team(_request(tmp_path))

    assert not tuple((tmp_path / "state").rglob("team_run.json"))


def test_concurrent_writable_shared_workspace_fails_before_state_creation(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, ScriptedRuntime(), max_workers=2)

    result = runtime.run_team(_request(tmp_path))

    assert result.runtime_result.status is RuntimeStatus.FAILED
    assert "concurrent writable" in (result.runtime_result.error or "")
    assert not (tmp_path / "state").exists()


def test_stale_worker_generation_cannot_complete_current_claim(tmp_path: Path) -> None:
    provider = TrackingProvider(tmp_path / "state")
    runtime = TeamCodingRuntime(
        planner=DeterministicSingleNodePlanner(),
        worker_executor=cast(WorkerExecutor, StaleResultExecutor()),
        runtime_provider=provider,
    )

    with pytest.raises(TeamResultProtocolError, match="fence"):
        runtime.run_team(_request(tmp_path))

    assert provider.handle is not None
    snapshot = provider.handle.store.load(provider.handle.session_id)
    assert snapshot.tasks["node-worker-implementation"].status is TaskStatus.RUNNING
