"""Independent Day5 acceptance: transaction effects and controlled interleavings."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, Thread
from typing import cast

import pytest
from pydantic import ValidationError

from codeteam.agent_team import (
    DuplicateWorkerError,
    InvalidClockError,
    RecoveryOutcome,
    RestartOutcome,
    RestartResult,
    StaleTaskClaimError,
    StaleWorkerGenerationError,
    TaskClaim,
    TaskOwnershipError,
    TaskScheduler,
    TaskStatus,
    WorkerNotFoundError,
)
from codeteam.agent_team.contracts import LifecyclePolicy
from codeteam.agent_team.lifecycle import AgentLifecycleManager
from codeteam.agent_team.models import AgentInfo, AgentStatus
from codeteam.agent_team.registry import AgentRegistry
from codeteam.agent_team.worker import WorkerAgent
from codeteam.events import AgentEvent, AgentEventType

from .test_lifecycle import WAIT, owned, team
from .test_registry import FakeClock
from .test_scheduler import _dag, _worker


def audit(scheduler: TaskScheduler) -> tuple[object, ...]:
    registry = scheduler.registry
    return (
        scheduler.events,
        registry.events,
        registry.coordinator.transaction_seq,
        registry.coordinator.event_index,
    )


def full_state(scheduler: TaskScheduler) -> tuple[object, ...]:
    # Membership and transaction counters are part of the documented commit unit.
    with scheduler.registry.coordinator.lock:
        return (
            scheduler.snapshot(),
            audit(scheduler),
            frozenset(scheduler._queued_node_ids),
            frozenset(scheduler._waiting_for_worker_node_ids),
            tuple(
                (key, scheduler.registry.get(key))
                for key in scheduler.registry.runtime_records
            ),
        )


def assert_consistent(scheduler: TaskScheduler) -> None:
    snapshot = scheduler.snapshot()
    assert len(snapshot.queue) == len(set(snapshot.queue))
    assert set(snapshot.queue) == {
        key for key, task in snapshot.tasks.items() if task.status is TaskStatus.READY
    }
    for key, task in snapshot.tasks.items():
        if task.status in {TaskStatus.CLAIMED, TaskStatus.RUNNING}:
            assert task.owner_id is not None
            worker = snapshot.workers[task.owner_id]
            assert worker.status is AgentStatus.BUSY
            assert task.owner_generation == worker.generation
            assert snapshot.ownership[task.owner_id] == key
            assert task.attempt >= 1
        else:
            assert task.owner_id is None and task.owner_generation is None
            assert key not in snapshot.ownership.values()
    for worker_id, node_id in snapshot.ownership.items():
        if node_id is not None:
            assert snapshot.tasks[node_id].owner_id == worker_id


@pytest.mark.parametrize("operation", ["start", "complete", "fail"])
@pytest.mark.parametrize("old_kind", ["attempt", "runtime", "generation"])
def test_rejected_token_preserves_business_state_and_only_adds_rejection_audit(
    operation: str, old_kind: str
) -> None:
    clock, registry, scheduler, lifecycle, lease = team()
    first = owned(scheduler, lease, running=True)
    if old_kind == "attempt":
        scheduler.fail(first, "retry")
        current = owned(scheduler, lease, running=False)
        assert current.worker_generation == first.worker_generation
        assert current.attempt == first.attempt + 1
        rejected = first
        error: type[Exception] = StaleTaskClaimError
    elif old_kind == "runtime":
        _clock2, _registry2, other, _lifecycle2, lease2 = team()
        rejected = owned(other, lease2, running=True)
        current = first
        assert rejected.runtime_id != current.runtime_id
        error = StaleTaskClaimError
    else:
        clock.now = 15
        lifecycle.sweep()
        current = owned(scheduler, registry.lease("w1"), running=False)
        rejected = first
        error = StaleWorkerGenerationError
    before, prior_events = scheduler.snapshot(), scheduler.events
    worker_events = registry.events
    with pytest.raises(error):
        if operation == "fail":
            scheduler.fail(rejected, "late")
        else:
            getattr(scheduler, operation)(rejected)
    assert scheduler.snapshot() == before
    assert registry.events == worker_events
    assert scheduler.events[:-1] == prior_events
    assert (
        scheduler.events[-1].event_type is AgentEventType.SCHEDULER_STALE_CLAIM_REJECTED
    )
    assert_consistent(scheduler)


@pytest.mark.parametrize("operation", ["claim", "start", "complete", "fail"])
@pytest.mark.parametrize("token", [None, "w1"])
def test_missing_tokens_never_discover_new_authority(
    operation: str, token: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clock, registry, scheduler, _lifecycle, lease = team()
    owned(scheduler, lease, running=True)
    before = full_state(scheduler)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("a delayed request must not obtain a fresh lease")

    monkeypatch.setattr(registry, "lease", forbidden)
    with pytest.raises(TypeError, match="explicit"):
        if operation == "fail":
            getattr(scheduler, operation)(token, "late")
        else:
            getattr(scheduler, operation)(token)
    assert full_state(scheduler) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt", None),
        ("attempt", 0),
        ("attempt", True),
        ("worker_generation", None),
        ("worker_generation", -1),
        ("runtime_id", " "),
        ("worker_id", ""),
        ("node_id", " "),
    ],
)
def test_public_entry_revalidates_bypassed_claim_fields(
    field: str, value: object
) -> None:
    _clock, _registry, scheduler, _lifecycle, lease = team()
    claim = owned(scheduler, lease, running=False)
    before = full_state(scheduler)
    invalid = claim.model_copy(update={field: value})
    with pytest.raises(ValidationError):
        scheduler.start(invalid)
    assert full_state(scheduler) == before


def test_activation_uses_runtime_status_and_fresh_grace_not_bootstrap_info() -> None:
    clock = FakeClock(100)
    registry = AgentRegistry(clock=clock)
    worker = _worker("w1", status=AgentStatus.CREATED)
    lease = registry.register(worker)
    scheduler = TaskScheduler(_dag("A"), registry)
    clock.now = 200
    registry.activate(lease)
    assert worker.info.status is AgentStatus.CREATED
    assert registry.runtime("w1").last_heartbeat_monotonic == 200
    assert registry.events == ()
    scheduler.schedule()
    claim = owned(scheduler, lease, running=True)
    assert_consistent(scheduler)
    assert worker.info.status is AgentStatus.CREATED
    clock.now = 214.999
    assert scheduler.timeout_candidates(heartbeat_timeout_seconds=15) == ()
    scheduler.complete(claim)
    assert registry.runtime("w1").status is AgentStatus.READY
    assert_consistent(scheduler)


def test_previous_task_candidate_cannot_revoke_next_task_on_same_worker() -> None:
    clock, registry, scheduler, lifecycle, lease = team()
    first = owned(scheduler, lease, running=True)
    clock.now = 15
    candidate = lifecycle.detect_timeouts()[0]
    scheduler.complete(first)
    second = owned(scheduler, lease, running=True)
    assert second.node_id == "B" and first.node_id == "A"
    assert second.worker_generation == first.worker_generation
    before = scheduler.snapshot()
    prior_events = (registry.events, scheduler.events)
    result = scheduler.recover_worker_loss(candidate, heartbeat_timeout_seconds=15)
    assert result.outcome is RecoveryOutcome.STALE_CANDIDATE
    assert scheduler.snapshot() == before
    assert (registry.events, scheduler.events) == prior_events
    assert_consistent(scheduler)


@pytest.mark.parametrize("change", ["attempt", "runtime", "unknown_worker"])
def test_candidate_validation_has_no_partial_revocation(change: str) -> None:
    clock, registry, scheduler, lifecycle, lease = team()
    owned(scheduler, lease, running=True)
    clock.now = 15
    candidate = lifecycle.detect_timeouts()[0]
    assert candidate.active_task is not None
    if change == "attempt":
        candidate = candidate.model_copy(
            update={
                "active_task": candidate.active_task.model_copy(update={"attempt": 99}),
            }
        )
    else:
        field = "runtime_id" if change == "runtime" else "worker_id"
        candidate = candidate.model_copy(
            update={
                "lease": lease.model_copy(update={field: "unknown"}),
            }
        )
    before = scheduler.snapshot()
    prior_events = (registry.events, scheduler.events)
    if change == "unknown_worker":
        with pytest.raises(WorkerNotFoundError):
            scheduler.recover_worker_loss(candidate, heartbeat_timeout_seconds=15)
    else:
        result = scheduler.recover_worker_loss(candidate, heartbeat_timeout_seconds=15)
        assert result.outcome is RecoveryOutcome.STALE_CANDIDATE
    assert scheduler.snapshot() == before
    assert (registry.events, scheduler.events) == prior_events


@pytest.mark.parametrize("operation", ["detect", "recover", "restart"])
def test_invalid_clock_rejects_without_business_or_audit_updates(
    operation: str,
) -> None:
    clock, _registry, scheduler, lifecycle, lease = team()
    clock.now = 15
    candidate = lifecycle.detect_timeouts()[0]
    if operation == "restart":
        scheduler.recover_worker_loss(candidate, heartbeat_timeout_seconds=15)
    before = full_state(scheduler)
    clock.now = 14
    with pytest.raises(InvalidClockError):
        if operation == "detect":
            lifecycle.detect_timeouts()
        elif operation == "recover":
            scheduler.recover_worker_loss(candidate, heartbeat_timeout_seconds=15)
        else:
            lifecycle.restart_worker(lease)
    assert full_state(scheduler) == before


@pytest.mark.parametrize(
    "operation",
    ["heartbeat", "start", "complete", "fail", "stop", "recover", "reserve", "publish"],
)
def test_late_prepare_failure_restores_business_state_and_transaction_audit(
    operation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock, registry, scheduler, lifecycle, lease = team()
    claim = owned(scheduler, lease, running=operation != "start")
    clock.now = 15
    candidate = lifecycle.detect_timeouts()[0]
    action: Callable[[], object]
    target: AgentRegistry | TaskScheduler
    if operation in {"reserve", "publish"}:
        scheduler.recover_worker_loss(candidate, heartbeat_timeout_seconds=15)
        if operation == "reserve":
            action = lambda: registry.reserve_restart(lease, policy=lifecycle.policy)
        else:
            ticket = registry.reserve_restart(lease, policy=lifecycle.policy)
            assert not isinstance(ticket, RestartResult)
            replacement = WorkerAgent(ticket.info)
            action = lambda: registry.publish_restart(
                ticket, replacement, replacement.info
            )
        target = registry
    elif operation == "heartbeat":
        action = lambda: lifecycle.heartbeat(lease)
        target = registry
    else:
        actions: dict[str, Callable[[], object]] = {
            "start": lambda: scheduler.start(claim),
            "complete": lambda: scheduler.complete(claim),
            "fail": lambda: scheduler.fail(claim, "retry"),
            "stop": lambda: lifecycle.stop_worker(lease),
            "recover": lambda: scheduler.recover_worker_loss(
                candidate, heartbeat_timeout_seconds=15
            ),
        }
        action = actions[operation]
        target = scheduler
    original = target._record_event_locked

    def fail_after_event(*args: object, **kwargs: object) -> None:
        cast(Callable[..., None], original)(*args, **kwargs)
        raise ValueError("acceptance: failure after draft event append")

    before = full_state(scheduler)
    monkeypatch.setattr(target, "_record_event_locked", fail_after_event)
    with pytest.raises(ValueError, match="after draft event"):
        action()
    assert full_state(scheduler) == before
    assert_consistent(scheduler)


@pytest.mark.parametrize("running", [False, True])
@pytest.mark.parametrize("cause", ["timeout", "stop"])
def test_exhausted_loss_blocks_all_descendants_in_one_transaction(
    running: bool, cause: str
) -> None:
    clock = FakeClock()
    registry = AgentRegistry(clock=clock)
    lease = registry.register(_worker("w1"))
    dag = _dag("Z", "M", "A")
    dag.add_dependency("Z", "M")
    dag.add_dependency("M", "A")
    scheduler = TaskScheduler(dag, registry, max_attempts=1)
    lifecycle = AgentLifecycleManager(registry, scheduler)
    scheduler.schedule()
    claim = owned(scheduler, lease, running=running)
    assert claim.node_id == "Z"
    before = scheduler.snapshot()
    if cause == "timeout":
        clock.now = 15
        result = scheduler.recover_worker_loss(
            lifecycle.detect_timeouts()[0], heartbeat_timeout_seconds=15
        )
    else:
        result = lifecycle.stop_worker(lease)
    assert result.outcome is RecoveryOutcome.TASK_FAILED
    snapshot = scheduler.snapshot()
    assert snapshot.tasks["Z"].attempt == before.tasks["Z"].attempt == 1
    assert snapshot.workers["w1"].status is (
        AgentStatus.FAILED if cause == "timeout" else AgentStatus.STOPPED
    )
    assert snapshot.queue == ()
    assert_consistent(scheduler)
    assert {key: task.status for key, task in snapshot.tasks.items()} == {
        "Z": TaskStatus.FAILED,
        "M": TaskStatus.BLOCKED,
        "A": TaskStatus.BLOCKED,
    }
    events = [
        event
        for event in scheduler.events
        if event.event_type is AgentEventType.SCHEDULER_TASK_BLOCKED
    ]
    assert {event.data["node_id"] for event in events} == {"M", "A"}
    assert {event.data["transaction_id"] for event in events} == {
        registry.events[-1].data["transaction_id"]
    }


def test_wrong_factory_type_fails_without_replacing_worker_or_task_state() -> None:
    def invalid_factory(info: AgentInfo) -> object:
        return object()

    clock, registry, scheduler, lifecycle, lease = team(
        factory=cast(Callable[[AgentInfo], WorkerAgent], invalid_factory)
    )
    original = registry.get("w1")
    owned(scheduler, lease, running=True)
    clock.now = 15
    scheduler.recover_worker_loss(
        lifecycle.detect_timeouts()[0], heartbeat_timeout_seconds=15
    )
    before = scheduler.snapshot()
    result = lifecycle.restart_worker(lease)
    assert result.outcome is RestartOutcome.FACTORY_FAILED
    after = scheduler.snapshot()
    assert (after.tasks, after.queue, after.ownership) == (
        before.tasks,
        before.queue,
        before.ownership,
    )
    assert registry.get("w1") is original
    record = after.workers["w1"]
    assert record.status is AgentStatus.FAILED and record.restart_id is None
    assert record.generation == 1 and record.restart_attempts == 1


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("stage", ["factory", "reservation_observer"])
def test_restart_interrupt_cleans_matching_reservation(
    interrupt: type[BaseException], stage: str
) -> None:
    calls: list[str] = []

    def factory(info: AgentInfo) -> WorkerAgent:
        calls.append(info.identity.agent_id)
        raise interrupt("synthetic interrupt")

    def sink(event: AgentEvent) -> None:
        if (
            stage == "reservation_observer"
            and event.event_type is AgentEventType.WORKER_RESTARTING
        ):
            raise interrupt("synthetic interrupt")

    clock, registry, scheduler, lifecycle, lease = team(factory=factory, sink=sink)
    original = registry.get("w1")
    owned(scheduler, lease, running=True)
    clock.now = 15
    scheduler.recover_worker_loss(
        lifecycle.detect_timeouts()[0], heartbeat_timeout_seconds=15
    )
    before = scheduler.snapshot()
    with pytest.raises(interrupt):
        lifecycle.restart_worker(lease)
    after = scheduler.snapshot()
    assert (after.tasks, after.queue, after.ownership) == (
        before.tasks,
        before.queue,
        before.ownership,
    )
    assert registry.get("w1") is original
    record = after.workers["w1"]
    assert record.generation == 1 and record.restart_attempts == 1
    assert calls == (["w1"] if stage == "factory" else [])
    assert (record.status, record.restart_id) == (AgentStatus.FAILED, None)
    assert registry.events[-1].event_type is AgentEventType.WORKER_RESTART_FAILED
    assert_consistent(scheduler)


def test_slow_factory_does_not_block_other_worker_task_and_heartbeat() -> None:
    entered, release, progressed = Event(), Event(), Event()
    errors: list[BaseException] = []
    results: list[RestartResult] = []
    claims: list[TaskClaim] = []

    def factory(info: AgentInfo) -> WorkerAgent:
        entered.set()
        assert release.wait(WAIT)
        return WorkerAgent(info)

    clock, registry, scheduler, lifecycle, lease = team(factory=factory)
    other = registry.register(_worker("w2"))
    owned(scheduler, lease, running=True)
    clock.now = 15
    lifecycle.heartbeat(other)
    scheduler.recover_worker_loss(
        lifecycle.detect_timeouts()[0], heartbeat_timeout_seconds=15
    )

    def restart() -> None:
        try:
            results.append(lifecycle.restart_worker(lease))
        except BaseException as exc:  # noqa: BLE001 - assert thread failures in parent.
            errors.append(exc)

    def make_progress() -> None:
        try:
            assert entered.wait(WAIT)
            for node_id in ("A", "B"):
                claim = owned(scheduler, other, running=True)
                assert claim.node_id == node_id
                claims.append(claim)
                lifecycle.heartbeat(other)
                scheduler.complete(claim)
                assert_consistent(scheduler)
            progressed.set()
        except BaseException as exc:  # noqa: BLE001 - assert thread failures in parent.
            errors.append(exc)

    threads = [
        Thread(target=restart, daemon=True),
        Thread(target=make_progress, daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        assert progressed.wait(WAIT), (
            "other worker must progress before releasing factory"
        )
        assert registry.runtime("w1").status is AgentStatus.RESTARTING
    finally:
        release.set()
        for thread in threads:
            thread.join(WAIT)
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert results[0].outcome is RestartOutcome.RESTARTED
    assert [(claim.node_id, claim.attempt) for claim in claims] == [("A", 2), ("B", 1)]
    assert registry.runtime("w1").generation == 2
    assert scheduler.queue == ()
    assert_consistent(scheduler)


@pytest.mark.parametrize("winner", ["stop", "complete"])
def test_stop_complete_ordered_threads_never_revive_stopped_worker(winner: str) -> None:
    _clock, registry, scheduler, lifecycle, lease = team()
    claim = owned(scheduler, lease, running=True)
    committed = Event()
    errors: list[BaseException] = []

    def complete() -> None:
        if winner == "stop":
            with pytest.raises(TaskOwnershipError):
                scheduler.complete(claim)
        else:
            scheduler.complete(claim)

    def execute(name: str) -> None:
        try:
            if name != winner:
                assert committed.wait(WAIT)
            if name == "stop":
                lifecycle.stop_worker(lease)
            else:
                complete()
            assert_consistent(scheduler)
        except BaseException as exc:  # noqa: BLE001 - assert thread failures in parent.
            errors.append(exc)
        finally:
            if name == winner:
                committed.set()

    threads = [
        Thread(target=execute, args=(name,), daemon=True)
        for name in ("stop", "complete")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(WAIT)
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert registry.runtime("w1").status is AgentStatus.STOPPED
    assert scheduler.runtime_records["A"].status is (
        TaskStatus.READY if winner == "stop" else TaskStatus.COMPLETED
    )
    assert scheduler.queue == (("A",) if winner == "stop" else ("B",))
    before = full_state(scheduler)
    assert lifecycle.stop_worker(lease).outcome is RecoveryOutcome.ALREADY_STOPPED
    assert scheduler.snapshot() == before[0]


def test_legacy_registry_exception_exports_are_identical() -> None:
    from codeteam.agent_team.registry import DuplicateWorkerError as NewDuplicate
    from codeteam.agent_team.registry import WorkerNotFoundError as NewMissing
    from codeteam.agent_team.worker import DuplicateWorkerError as OldDuplicate
    from codeteam.agent_team.worker import WorkerNotFoundError as OldMissing

    assert NewDuplicate is OldDuplicate is DuplicateWorkerError
    assert NewMissing is OldMissing is WorkerNotFoundError


@pytest.mark.parametrize("max_restarts", [-1, "2", 2.5, False])
def test_invalid_restart_budget_is_rejected(max_restarts: object) -> None:
    with pytest.raises(ValidationError):
        LifecyclePolicy.model_validate({"max_restarts": max_restarts})
