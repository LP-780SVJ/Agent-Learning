import subprocess
from pathlib import Path

from codeteam.agent.runtime_models import RuntimeStatus
from codeteam.agent_team.coordination import TeamStateCoordinator
from codeteam.agent_team.persistence_models import DurableEventDraft
from codeteam.agent_team.reconciliation import (
    TeamReconciliationVerdict,
    TeamStateReconciler,
)
from codeteam.agent_team.runtime_factory import TeamRuntimeFactory
from codeteam.agent_team.team_planning import DeterministicSingleNodePlanner
from codeteam.agent_team.team_runtime import TeamCodingRuntime
from codeteam.agent_team.team_runtime_provider import (
    TeamRuntimeHandle,
)
from codeteam.agent_team.team_store import SQLiteTeamStateStore
from codeteam.agent_team.worker_executor import WorkerExecutor

from .team_state_helpers import session_for_team
from .test_team_runtime import ScriptedRuntime, TrackingProvider, _request


def test_paused_attempt_resumes_in_new_runtime_without_resetting_usage(
    tmp_path: Path,
) -> None:
    provider = TrackingProvider(tmp_path / "state")
    planner = DeterministicSingleNodePlanner()
    first_runtime = TeamCodingRuntime(
        planner=planner,
        worker_executor=WorkerExecutor(ScriptedRuntime([RuntimeStatus.PAUSED])),
        runtime_provider=provider,
    )
    request = _request(tmp_path)

    paused = first_runtime.run_team(request)

    assert paused.runtime_result.status is RuntimeStatus.PAUSED
    assert provider.handle is not None
    old_handle = provider.handle
    old_runtime_id = old_handle.runtime.coordinator.runtime_id
    old_snapshot = old_handle.store.load(old_handle.session_id)
    coordinator = TeamStateCoordinator()
    report = TeamStateReconciler().reconcile(
        session=session_for_team(session_id=old_handle.session_id),
        snapshot=old_snapshot,
        planned_runtime_id=coordinator.runtime_id,
    )
    assert report.verdict is TeamReconciliationVerdict.RESUMABLE
    committed = old_handle.store.commit(
        report.snapshot,
        expected_revision=old_snapshot.revision,
        events=(DurableEventDraft(event_type="team.runtime_prepared"),),
    )
    hydrated = TeamRuntimeFactory().hydrate(
        snapshot=committed,
        store=old_handle.store,
        coordinator=coordinator,
    )
    resumed_handle = TeamRuntimeHandle.from_hydrated(
        session_dir=old_handle.session_dir,
        runtime=hydrated,
    )
    second_runtime = TeamCodingRuntime(
        planner=planner,
        worker_executor=WorkerExecutor(ScriptedRuntime()),
        runtime_provider=provider,
    )

    completed = second_runtime.resume_team(
        request,
        plan=planner.plan(request),
        handle=resumed_handle,
    )

    assert completed.runtime_result.status is RuntimeStatus.COMPLETED
    assert hydrated.coordinator.runtime_id != old_runtime_id
    assert [item.attempt for item in completed.artifact.node_results] == [1, 2]
    assert completed.artifact.budget_usage.steps == 4
    assert completed.artifact.metrics.retries == 1


def test_process_crash_with_unknown_usage_fails_closed_after_reconciliation(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    crashed = subprocess.run(
        [
            str(project_root / ".venv/bin/python"),
            str(
                project_root
                / "tests/agent_team/day7_process_crash_helper.py"
            ),
            str(workspace),
            str(state_root),
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        shell=False,
        timeout=30,
        check=False,
    )
    assert crashed.returncode == 73
    session_dirs = tuple(state_root.iterdir())
    assert len(session_dirs) == 1
    session_dir = session_dirs[0]
    store = SQLiteTeamStateStore(session_dir)
    original = store.load(session_dir.name)
    old_runtime_id = original.previous_runtime_id
    coordinator = TeamStateCoordinator()
    report = TeamStateReconciler().reconcile(
        session=session_for_team(session_id=session_dir.name),
        snapshot=original,
        planned_runtime_id=coordinator.runtime_id,
    )
    committed = store.commit(
        report.snapshot,
        expected_revision=original.revision,
        events=(DurableEventDraft(event_type="team.runtime_prepared"),),
    )
    hydrated = TeamRuntimeFactory().hydrate(
        snapshot=committed,
        store=store,
        coordinator=coordinator,
    )
    handle = TeamRuntimeHandle.from_hydrated(
        session_dir=session_dir,
        runtime=hydrated,
    )
    scripted = ScriptedRuntime()
    planner = DeterministicSingleNodePlanner()
    request = _request(tmp_path)

    result = TeamCodingRuntime(
        planner=planner,
        worker_executor=WorkerExecutor(scripted),
        runtime_provider=TrackingProvider(tmp_path / "unused"),
    ).resume_team(request, plan=planner.plan(request), handle=handle)

    assert result.runtime_result.status is RuntimeStatus.FAILED
    assert result.artifact.budget_usage.steps == 16
    assert scripted.requests == []
    assert hydrated.coordinator.runtime_id != old_runtime_id
