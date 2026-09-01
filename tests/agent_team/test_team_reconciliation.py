from __future__ import annotations

from codeteam.agent_team.dag import TaskStatus
from codeteam.agent_team.models import AgentStatus
from codeteam.agent_team.persistence_models import (
    DurableMessageState,
    TeamStateSnapshot,
)
from codeteam.agent_team.reconciliation import (
    TeamReconciliationVerdict,
    TeamStateReconciler,
)

from .team_state_helpers import session_for_team, team_snapshot


def running_snapshot(*, max_attempts: int = 2) -> TeamStateSnapshot:
    snapshot = team_snapshot()
    return TeamStateSnapshot.model_validate(
        {
            **snapshot.model_dump(),
            "max_attempts": max_attempts,
            "ready_queue": (),
            "tasks": {
                "A": snapshot.tasks["A"].model_copy(
                    update={
                        "status": TaskStatus.RUNNING,
                        "owner_id": "worker-1",
                        "owner_generation": 2,
                        "attempt": 1,
                        "claimed_at": 1.0,
                    }
                ),
                "B": snapshot.tasks["B"],
            },
            "workers": {
                "worker-1": snapshot.workers["worker-1"].model_copy(
                    update={"status": AgentStatus.BUSY}
                )
            },
            "worker_ownership": {"worker-1": "A"},
        }
    )


def test_running_task_is_requeued_only_after_clean_reconciliation() -> None:
    snapshot = running_snapshot(max_attempts=2)

    report = TeamStateReconciler().reconcile(
        session=session_for_team(),
        snapshot=snapshot,
        planned_runtime_id="runtime-new",
    )

    assert report.verdict is TeamReconciliationVerdict.RESUMABLE
    assert report.snapshot.tasks["A"].status is TaskStatus.READY
    assert report.snapshot.tasks["A"].attempt == 1
    assert report.snapshot.tasks["A"].owner_id is None
    assert report.snapshot.ready_queue == ("A",)
    assert report.snapshot.worker_ownership == {"worker-1": None}
    assert report.snapshot.workers["worker-1"].status is AgentStatus.READY
    assert report.snapshot.workers["worker-1"].generation == 3
    assert report.snapshot.workers["worker-1"].restart_attempts == 1
    assert report.snapshot.previous_runtime_id == "runtime-new"


def test_exhausted_running_task_fails_and_blocks_all_descendants() -> None:
    snapshot = running_snapshot(max_attempts=1)

    report = TeamStateReconciler().reconcile(
        session=session_for_team(),
        snapshot=snapshot,
        planned_runtime_id="runtime-new",
    )

    assert report.snapshot.tasks["A"].status is TaskStatus.FAILED
    assert report.snapshot.tasks["B"].status is TaskStatus.BLOCKED
    assert report.snapshot.ready_queue == ()
    assert any(action.startswith("block:B") for action in report.recovery_actions)


def test_unknown_git_effects_fail_closed_without_rewriting_snapshot() -> None:
    snapshot = running_snapshot()

    report = TeamStateReconciler().reconcile(
        session=session_for_team(),
        snapshot=snapshot,
        planned_runtime_id="runtime-new",
        git_has_unreconciled_effects=True,
    )

    assert report.verdict is TeamReconciliationVerdict.RECOVERY_REQUIRED
    assert report.snapshot == snapshot
    assert report.issues == ("inflight_git_effects_are_not_reconciled",)


def test_old_inflight_message_is_released_but_delivery_attempt_is_preserved() -> None:
    snapshot = team_snapshot()
    message = snapshot.messages[0].model_copy(
        update={
            "state": DurableMessageState.IN_FLIGHT,
            "delivery_attempt": 2,
            "claimed_by_runtime_id": "runtime-old",
            "claim_id": "claim-old",
        }
    )
    snapshot = snapshot.model_copy(update={"messages": (message,)})

    report = TeamStateReconciler().reconcile(
        session=session_for_team(),
        snapshot=snapshot,
        planned_runtime_id="runtime-new",
    )

    recovered = report.snapshot.messages[0]
    assert recovered.state is DurableMessageState.PENDING
    assert recovered.delivery_attempt == 2
    assert recovered.claim_id is None
    assert recovered.claimed_by_runtime_id is None


def test_stopped_worker_is_not_resurrected_or_regenerated() -> None:
    snapshot = team_snapshot()
    stopped = snapshot.workers["worker-1"].model_copy(
        update={"status": AgentStatus.STOPPED}
    )
    snapshot = snapshot.model_copy(update={"workers": {"worker-1": stopped}})

    report = TeamStateReconciler().reconcile(
        session=session_for_team(),
        snapshot=snapshot,
        planned_runtime_id="runtime-new",
    )

    assert report.snapshot.workers["worker-1"] == stopped
