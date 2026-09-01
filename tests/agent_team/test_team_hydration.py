from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from codeteam.agent_team.contracts import StaleWorkerGenerationError, WorkerLease
from codeteam.agent_team.coordination import TeamStateCoordinator
from codeteam.agent_team.persistence_models import DurableEventDraft
from codeteam.agent_team.reconciliation import TeamStateReconciler
from codeteam.agent_team.runtime_factory import TeamRuntimeFactory
from codeteam.agent_team.scheduler import StaleTaskClaimError
from codeteam.agent_team.team_store import SQLiteTeamStateStore

from .team_state_helpers import session_for_team, team_snapshot
from .test_registry import FakeClock


def prepared_runtime(tmp_path: Path):
    session_dir = tmp_path / "ses_team_test"
    session_dir.mkdir()
    store = SQLiteTeamStateStore(session_dir)
    original = store.initialize(team_snapshot())
    coordinator = TeamStateCoordinator()
    report = TeamStateReconciler().reconcile(
        session=session_for_team(),
        snapshot=original,
        planned_runtime_id=coordinator.runtime_id,
    )
    committed = store.commit(
        report.snapshot,
        expected_revision=original.revision,
        events=(DurableEventDraft(event_type="team.runtime_prepared"),),
    )
    runtime = TeamRuntimeFactory().hydrate(
        snapshot=committed,
        store=store,
        coordinator=coordinator,
    )
    return original, runtime, store


def test_hydrate_builds_new_epoch_and_preserves_queue_and_budget(tmp_path: Path) -> None:
    original, runtime, _store = prepared_runtime(tmp_path)

    assert runtime.coordinator.runtime_id != original.previous_runtime_id
    assert runtime.snapshot.previous_runtime_id == runtime.coordinator.runtime_id
    assert runtime.scheduler.queue == ("A",)
    assert runtime.scheduler.max_attempts == 2
    record = runtime.registry.runtime("worker-1")
    assert record.generation == 3
    assert record.restart_attempts == 1


def test_utc_restart_deadline_becomes_a_new_monotonic_deadline(
    tmp_path: Path,
) -> None:
    session_dir = tmp_path / "ses_team_test"
    session_dir.mkdir()
    store = SQLiteTeamStateStore(session_dir)
    original = store.initialize(team_snapshot())
    coordinator = TeamStateCoordinator()
    report = TeamStateReconciler().reconcile(
        session=session_for_team(),
        snapshot=original,
        planned_runtime_id=coordinator.runtime_id,
    )
    committed = store.commit(report.snapshot, expected_revision=1)
    clock = FakeClock(100.0)
    factory = TeamRuntimeFactory(
        clock=clock,
        now_utc=lambda: datetime(2029, 12, 31, 23, 59, 50, tzinfo=UTC),
    )

    runtime = factory.hydrate(
        snapshot=committed,
        store=store,
        coordinator=coordinator,
    )

    assert runtime.registry.runtime("worker-1").next_restart_monotonic == 110.0


def test_old_worker_lease_is_rejected_without_poisoning_new_runtime(
    tmp_path: Path,
) -> None:
    _original, runtime, _store = prepared_runtime(tmp_path)
    old = WorkerLease(
        runtime_id="runtime-old",
        worker_id="worker-1",
        generation=2,
    )

    with pytest.raises(StaleWorkerGenerationError):
        runtime.claim(old)

    assert runtime.poisoned is False
    assert runtime.scheduler.queue == ("A",)


def test_task_mutation_is_committed_before_result_is_reused(tmp_path: Path) -> None:
    _original, runtime, store = prepared_runtime(tmp_path)
    lease = runtime.registry.lease("worker-1")

    claim = runtime.claim(lease)

    assert claim is not None
    persisted = store.load(runtime.snapshot.session_id)
    assert persisted.revision == runtime.snapshot.revision
    assert persisted.tasks["A"].owner_id == "worker-1"
    assert persisted.ready_queue == ()

    runtime.start(claim)
    runtime.complete(claim)
    assert store.load(runtime.snapshot.session_id).tasks["A"].status.value == "completed"


def test_old_task_claim_is_rejected_after_new_runtime_hydration(tmp_path: Path) -> None:
    _original, runtime, _store = prepared_runtime(tmp_path)
    lease = runtime.registry.lease("worker-1")
    claim = runtime.claim(lease)
    assert claim is not None
    old = claim.model_copy(update={"runtime_id": "runtime-old"})

    with pytest.raises(StaleTaskClaimError):
        runtime.start(old)

    assert runtime.poisoned is False


def test_durable_claim_ack_updates_live_and_sqlite_mailbox(tmp_path: Path) -> None:
    _original, runtime, store = prepared_runtime(tmp_path)

    claim = runtime.claim_message("worker-1")

    assert claim is not None
    assert claim.runtime_id == runtime.coordinator.runtime_id
    assert runtime.mailbox.queue_size("worker-1") == 0
    assert store.load(runtime.snapshot.session_id).messages[0].claim_id == claim.claim_id

    runtime.ack_message(claim)
    assert store.load(runtime.snapshot.session_id).messages == ()
    assert "msg-1" in runtime.snapshot.seen_message_ids


def test_durable_claim_can_be_released_without_losing_delivery_attempt(
    tmp_path: Path,
) -> None:
    _original, runtime, store = prepared_runtime(tmp_path)
    claim = runtime.claim_message("worker-1")
    assert claim is not None

    released = runtime.release_message(claim)

    message = released.messages[0]
    assert message.state.value == "pending"
    assert message.delivery_attempt == 1
    assert message.claim_id is None
    assert runtime.mailbox.queue_size("worker-1") == 1
    assert store.load(runtime.snapshot.session_id) == released
