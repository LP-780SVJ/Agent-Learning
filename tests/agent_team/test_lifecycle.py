from __future__ import annotations

from collections.abc import Callable
from threading import Barrier, Event, Thread

import pytest

from codeteam.agent_team.contracts import (
    LifecyclePolicy,
    RecoveryOutcome,
    RestartOutcome,
    RestartResult,
    StaleWorkerGenerationError,
    WorkerLease,
    WorkerStateError,
)
from codeteam.agent_team.dag import TaskStatus
from codeteam.agent_team.lifecycle import AgentLifecycleManager
from codeteam.agent_team.models import AgentInfo, AgentRole, AgentStatus
from codeteam.agent_team.registry import AgentRegistry
from codeteam.agent_team.scheduler import (
    TaskClaim,
    TaskOwnershipError,
    TaskScheduler,
    WorkerRoleMismatchError,
    WorkerUnavailableError,
)
from codeteam.agent_team.worker import WorkerAgent
from codeteam.events import AgentEvent, AgentEventType

from .test_registry import FakeClock
from .test_scheduler import _dag, _worker

WAIT = 2.0


def team(
    *,
    max_attempts: int = 2,
    factory: Callable[[AgentInfo], WorkerAgent] = WorkerAgent,
    max_restarts: int = 2,
    sink: Callable[[AgentEvent], None] | None = None,
) -> tuple[FakeClock, AgentRegistry, TaskScheduler, AgentLifecycleManager, WorkerLease]:
    clock = FakeClock()
    registry = AgentRegistry(clock=clock, event_sink=sink)
    lease = registry.register(_worker("w1"))
    dag = _dag("A", "B")
    dag.add_dependency("A", "B")
    scheduler = TaskScheduler(dag, registry, max_attempts=max_attempts)
    lifecycle = AgentLifecycleManager(
        registry,
        scheduler,
        worker_factory=factory,
        policy=LifecyclePolicy(max_restarts=max_restarts),
    )
    scheduler.schedule()
    return clock, registry, scheduler, lifecycle, lease


def owned(scheduler: TaskScheduler, lease: WorkerLease, *, running: bool) -> TaskClaim:
    claim = scheduler.claim(lease)
    assert claim is not None
    if running:
        scheduler.start(claim)
    return claim


@pytest.mark.parametrize("now,expired", [(14.999, False), (15, True), (15.001, True)])
@pytest.mark.parametrize("busy", [False, True])
def test_timeout_boundary_and_scan_is_read_only(
    now: float, expired: bool, busy: bool
) -> None:
    clock, registry, scheduler, lifecycle, lease = team()
    if busy:
        owned(scheduler, lease, running=True)
    clock.now = now
    before = scheduler.snapshot()
    events = (registry.events, scheduler.events)
    candidates = lifecycle.detect_timeouts()
    assert bool(candidates) is expired
    assert candidates == lifecycle.detect_timeouts()
    assert scheduler.snapshot() == before
    assert (registry.events, scheduler.events) == events


@pytest.mark.parametrize("running", [False, True])
@pytest.mark.parametrize("max_attempts", [1, 2])
def test_recovery_claimed_and_running_respects_retry_budget(
    running: bool, max_attempts: int
) -> None:
    clock, registry, scheduler, lifecycle, lease = team(max_attempts=max_attempts)
    claim = owned(scheduler, lease, running=running)
    clock.now = 15
    candidate = lifecycle.detect_timeouts()[0]
    result = scheduler.recover_worker_loss(candidate, heartbeat_timeout_seconds=15)
    assert registry.runtime("w1").status is AgentStatus.FAILED
    task = scheduler.runtime_records["A"]
    assert task.owner_id is None and task.owner_generation is None
    assert task.attempt == claim.attempt == 1
    if max_attempts == 2:
        assert result.outcome is RecoveryOutcome.TASK_REQUEUED
        assert task.status is TaskStatus.READY
        assert scheduler.queue == ("A",)
    else:
        assert result.outcome is RecoveryOutcome.TASK_FAILED
        assert task.status is TaskStatus.FAILED
        assert scheduler.runtime_records["B"].status is TaskStatus.BLOCKED
        assert scheduler.queue == ()
    before = scheduler.snapshot()
    again = scheduler.recover_worker_loss(candidate, heartbeat_timeout_seconds=15)
    assert again.outcome is RecoveryOutcome.STALE_CANDIDATE
    assert scheduler.snapshot() == before
    with pytest.raises(WorkerUnavailableError):
        scheduler.claim(lease)
    with pytest.raises(TaskOwnershipError):
        scheduler.complete(claim)


def test_idle_worker_loss_has_no_task_attempt_and_audit_is_correlated() -> None:
    clock, registry, scheduler, lifecycle, lease = team()
    clock.now = 15
    result = scheduler.recover_worker_loss(
        lifecycle.detect_timeouts()[0], heartbeat_timeout_seconds=15
    )
    assert result.outcome is RecoveryOutcome.WORKER_ONLY
    assert result.task_record is None
    assert scheduler.runtime_records["A"].attempt == 0
    assert registry.runtime("w1").status is AgentStatus.FAILED
    assert lifecycle.restart_worker(lease).outcome is RestartOutcome.RESTARTED


@pytest.mark.parametrize("update", ["heartbeat", "complete", "new_claim", "stop"])
def test_timeout_candidate_is_revalidated_after_state_change(update: str) -> None:
    clock, _registry, scheduler, lifecycle, lease = team()
    claim = owned(scheduler, lease, running=True)
    clock.now = 15
    candidate = lifecycle.detect_timeouts()[0]
    if update == "heartbeat":
        lifecycle.heartbeat(lease)
    elif update == "complete":
        scheduler.complete(claim)
    elif update == "new_claim":
        scheduler.fail(claim, "retry")
        owned(scheduler, lease, running=False)
    else:
        lifecycle.stop_worker(lease)
    before = scheduler.snapshot()
    result = scheduler.recover_worker_loss(candidate, heartbeat_timeout_seconds=15)
    assert result.outcome is RecoveryOutcome.STALE_CANDIDATE
    assert scheduler.snapshot() == before
    if update == "complete":
        # A fresh idle-worker timeout cannot resurrect a completed task either.
        scheduler.recover_worker_loss(
            lifecycle.detect_timeouts()[0], heartbeat_timeout_seconds=15
        )
        assert scheduler.runtime_records["A"].status is TaskStatus.COMPLETED


def test_restart_rejects_old_generation_heartbeat_claim_stop_and_scan() -> None:
    clock, registry, scheduler, lifecycle, lease = team()
    original = registry.get("w1")
    claim = owned(scheduler, lease, running=True)
    clock.now = 15
    candidate = lifecycle.detect_timeouts()[0]
    scheduler.recover_worker_loss(candidate, heartbeat_timeout_seconds=15)
    result = lifecycle.restart_worker(lease)
    assert result.outcome is RestartOutcome.RESTARTED
    assert result.lease.generation == lease.generation + 1
    assert registry.get("w1") is not original
    assert registry.get("w1").info == original.info
    assert registry.runtime("w1").last_heartbeat_monotonic == 15
    before = scheduler.snapshot()
    for operation in (
        lambda: lifecycle.heartbeat(lease),
        lambda: lifecycle.stop_worker(lease),
        lambda: scheduler.claim(lease),
        lambda: scheduler.complete(claim),
    ):
        with pytest.raises(StaleWorkerGenerationError):
            operation()
        assert scheduler.snapshot() == before
    assert (
        scheduler.recover_worker_loss(candidate, heartbeat_timeout_seconds=15).outcome
        is RecoveryOutcome.STALE_CANDIDATE
    )
    next_claim = owned(scheduler, result.lease, running=True)
    assert next_claim.attempt == 2
    scheduler.complete(next_claim)


def test_recovery_does_not_bypass_role_gate_or_pick_successor() -> None:
    clock, registry, scheduler, lifecycle, lease = team()
    frontend = registry.register(_worker("front", role=AgentRole.FRONTEND))
    owned(scheduler, lease, running=False)
    clock.now = 15
    lifecycle.heartbeat(frontend)
    result = lifecycle.sweep()
    assert result.recoveries[0].outcome is RecoveryOutcome.TASK_REQUEUED
    assert scheduler.runtime_records["A"].owner_id is None
    with pytest.raises(WorkerRoleMismatchError):
        scheduler.claim(frontend)


def test_factory_failure_budget_and_cooldown_are_bounded() -> None:
    calls: list[str] = []

    def broken(info: AgentInfo) -> WorkerAgent:
        calls.append(info.identity.agent_id)
        raise RuntimeError("secret contents must not be logged")

    clock, registry, scheduler, lifecycle, lease = team(factory=broken)
    owned(scheduler, lease, running=False)
    clock.now = 15
    first = lifecycle.sweep()
    assert first.restarts[0].outcome is RestartOutcome.FACTORY_FAILED
    assert scheduler.queue == ("A",)
    assert registry.runtime("w1").status is AgentStatus.FAILED
    assert lifecycle.sweep().restarts[0].outcome is RestartOutcome.COOLDOWN
    clock.now = 16.999
    assert lifecycle.restart_worker(lease).outcome is RestartOutcome.COOLDOWN
    clock.now = 17
    assert lifecycle.restart_worker(lease).outcome is RestartOutcome.FACTORY_FAILED
    clock.now = 30
    assert lifecycle.sweep().restarts[0].outcome is RestartOutcome.EXHAUSTED
    assert len(calls) == 2
    assert registry.runtime("w1").restart_attempts == 2
    assert registry.runtime("w1").generation == 1
    assert "secret contents" not in repr(registry.events)
    assert scheduler.runtime_records["A"].attempt == 1


@pytest.mark.parametrize("change", ["identity", "role", "capabilities", "same_object"])
def test_factory_must_preserve_identity_and_return_new_object(change: str) -> None:
    original = _worker("w1")

    def factory(info: AgentInfo) -> WorkerAgent:
        if change == "same_object":
            return original
        if change == "identity":
            info.identity.display_name = "changed"
        elif change == "role":
            info.role = AgentRole.TEST
        else:
            info.capabilities = ("elevated",)
        return WorkerAgent(info)

    clock = FakeClock()
    registry = AgentRegistry(clock=clock)
    lease = registry.register(original)
    lifecycle = AgentLifecycleManager(
        registry, TaskScheduler(_dag("A"), registry), worker_factory=factory
    )
    clock.now = 15
    result = lifecycle.sweep()
    assert result.restarts[0].outcome is RestartOutcome.FACTORY_FAILED
    assert registry.get("w1") is original
    assert registry.runtime("w1").generation == lease.generation


def test_restart_success_does_not_reset_lifetime_budget() -> None:
    clock, registry, _scheduler, lifecycle, _lease = team(max_restarts=1)
    clock.now = 15
    assert lifecycle.sweep().restarts[0].outcome is RestartOutcome.RESTARTED
    clock.now = 30
    assert lifecycle.sweep().restarts[0].outcome is RestartOutcome.EXHAUSTED
    assert registry.runtime("w1").status is AgentStatus.FAILED


def test_stop_is_idempotent_and_never_resurrects() -> None:
    clock, registry, scheduler, lifecycle, lease = team()
    owned(scheduler, lease, running=False)
    assert lifecycle.stop_worker(lease).outcome is RecoveryOutcome.TASK_REQUEUED
    events = registry.events
    assert lifecycle.stop_worker(lease).outcome is RecoveryOutcome.ALREADY_STOPPED
    assert registry.events == events
    clock.now = 100
    assert lifecycle.detect_timeouts() == ()
    assert lifecycle.sweep().restarts == ()
    assert lifecycle.restart_worker(lease).outcome is RestartOutcome.NOT_ELIGIBLE
    with pytest.raises(WorkerStateError):
        lifecycle.heartbeat(lease)
    assert scheduler.queue == ("A",)


@pytest.mark.parametrize("factory_fails", [False, True])
def test_stop_during_factory_rejects_late_callback_without_core_lock(
    factory_fails: bool,
) -> None:
    entered, release = Event(), Event()
    results: list[RestartResult] = []
    errors: list[BaseException] = []

    def factory(info: AgentInfo) -> WorkerAgent:
        entered.set()
        assert release.wait(WAIT)
        if factory_fails:
            raise ValueError("late factory failure")
        return WorkerAgent(info)

    clock, registry, scheduler, lifecycle, lease = team(factory=factory)
    clock.now = 15
    scheduler.recover_worker_loss(
        lifecycle.detect_timeouts()[0], heartbeat_timeout_seconds=15
    )

    def restart() -> None:
        try:
            results.append(lifecycle.restart_worker(lease))
        except BaseException as exc:  # noqa: BLE001 - propagate thread failures to assertions.
            errors.append(exc)

    thread = Thread(target=restart)
    thread.start()
    try:
        assert entered.wait(WAIT)
        assert registry.runtime("w1").status is AgentStatus.RESTARTING
        assert lifecycle.detect_timeouts() == ()
        assert lifecycle.restart_worker(lease).outcome is RestartOutcome.NOT_ELIGIBLE
        with pytest.raises(WorkerStateError):
            lifecycle.heartbeat(lease)
        stopper = Thread(target=lambda: lifecycle.stop_worker(lease))
        stopper.start()
        stopper.join(WAIT)
        assert not stopper.is_alive(), "factory must not hold core lock"
    finally:
        release.set()
        thread.join(WAIT)
    assert not thread.is_alive()
    assert errors == []
    assert results[0].outcome is RestartOutcome.STALE_TICKET
    assert registry.runtime("w1").status is AgentStatus.STOPPED
    assert registry.runtime("w1").generation == 1
    assert AgentEventType.WORKER_RESTARTED not in [
        e.event_type for e in registry.events
    ]


def test_old_restart_success_and_failure_cannot_change_new_generation() -> None:
    clock, registry, scheduler, lifecycle, lease = team()
    clock.now = 15
    scheduler.recover_worker_loss(
        lifecycle.detect_timeouts()[0], heartbeat_timeout_seconds=15
    )
    ticket = registry.reserve_restart(lease, policy=lifecycle.policy)
    assert not isinstance(ticket, RestartResult)
    worker = WorkerAgent(ticket.info)
    result = registry.publish_restart(ticket, worker, worker.info)
    assert result.outcome is RestartOutcome.RESTARTED
    before = registry.runtime("w1")
    replacement = WorkerAgent(ticket.info)
    assert (
        registry.publish_restart(ticket, replacement, replacement.info).outcome
        is RestartOutcome.STALE_TICKET
    )
    assert (
        registry.finish_restart_failure(ticket, error_type="RuntimeError").outcome
        is RestartOutcome.STALE_TICKET
    )
    assert registry.runtime("w1") == before


def test_recovery_prepare_failure_rolls_back_all_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock, registry, scheduler, lifecycle, lease = team()
    owned(scheduler, lease, running=True)
    clock.now = 15
    candidate = lifecycle.detect_timeouts()[0]
    before, events = scheduler.snapshot(), (scheduler.events, registry.events)

    def broken(*args: object, **kwargs: object) -> None:
        raise ValueError("task event preparation failed")

    monkeypatch.setattr(scheduler, "_record_event_locked", broken)
    with pytest.raises(ValueError, match="preparation"):
        scheduler.recover_worker_loss(candidate, heartbeat_timeout_seconds=15)
    assert scheduler.snapshot() == before
    assert (scheduler.events, registry.events) == events


def test_worker_and_task_failure_events_share_transaction() -> None:
    clock, registry, scheduler, lifecycle, lease = team()
    owned(scheduler, lease, running=True)
    clock.now = 15
    scheduler.recover_worker_loss(
        lifecycle.detect_timeouts()[0], heartbeat_timeout_seconds=15
    )
    worker_event = registry.events[-1]
    task_events = scheduler.events[-2:]
    assert worker_event.event_type is AgentEventType.WORKER_FAILED
    assert {e.data["transaction_id"] for e in (worker_event, *task_events)} == {
        worker_event.data["transaction_id"]
    }
    assert [
        e.data["transaction_event_index"] for e in (worker_event, *task_events)
    ] == [1, 2, 3]
    for event in (worker_event, *task_events):
        assert event.data["worker_id"] == "w1"
        assert event.data["generation"] == 1
        assert event.data["node_id"] == "A"
        assert event.data["attempt"] == 1


def test_reentrant_and_throwing_observer_cannot_hide_commit() -> None:
    ref: dict[str, AgentLifecycleManager] = {}

    def sink(event: AgentEvent) -> None:
        if event.event_type is AgentEventType.WORKER_RESTARTING:
            manager = ref["manager"]
            manager.stop_worker(manager.registry.lease("w1"))
            raise RuntimeError("observer failed")

    clock, registry, _scheduler, lifecycle, _lease = team(sink=sink)
    ref["manager"] = lifecycle
    clock.now = 15
    result = lifecycle.sweep()
    assert result.restarts[0].outcome is RestartOutcome.STALE_TICKET
    assert registry.runtime("w1").status is AgentStatus.STOPPED
    assert AgentEventType.WORKER_EVENT_DELIVERY_FAILED in [
        e.event_type for e in registry.events
    ]


def test_factory_interrupt_cleans_reservation_and_propagates() -> None:
    def factory(info: AgentInfo) -> WorkerAgent:
        raise KeyboardInterrupt

    clock, registry, _scheduler, lifecycle, _lease = team(factory=factory)
    clock.now = 15
    with pytest.raises(KeyboardInterrupt):
        lifecycle.sweep()
    record = registry.runtime("w1")
    assert record.status is AgentStatus.FAILED
    assert record.restart_id is None
    assert record.restart_attempts == 1


@pytest.mark.parametrize("_repeat", range(20))
def test_complete_vs_recovery_is_consistent_with_bounded_concurrency(
    _repeat: int,
) -> None:
    clock, _registry, scheduler, lifecycle, lease = team()
    claim = owned(scheduler, lease, running=True)
    clock.now = 15
    candidate = lifecycle.detect_timeouts()[0]
    barrier = Barrier(2)
    errors: list[BaseException] = []

    def complete() -> None:
        try:
            barrier.wait(WAIT)
            scheduler.complete(claim)
        except TaskOwnershipError:
            pass  # Recovery won the same claim; assert final state below.
        except BaseException as exc:  # noqa: BLE001 - propagate thread failures to assertions.
            errors.append(exc)

    def recover() -> None:
        try:
            barrier.wait(WAIT)
            scheduler.recover_worker_loss(candidate, heartbeat_timeout_seconds=15)
        except BaseException as exc:  # noqa: BLE001 - propagate thread failures to assertions.
            errors.append(exc)

    threads = [Thread(target=complete), Thread(target=recover)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(WAIT)
        assert not thread.is_alive()
    assert errors == []
    snapshot = scheduler.snapshot()
    task = snapshot.tasks["A"]
    assert task.owner_id is None and task.owner_generation is None
    if task.status is TaskStatus.COMPLETED:
        assert snapshot.workers["w1"].status is AgentStatus.READY
        assert snapshot.queue == ("B",)
    else:
        assert task.status is TaskStatus.READY
        assert snapshot.workers["w1"].status is AgentStatus.FAILED
        assert snapshot.queue == ("A",)


def test_wall_clock_does_not_drive_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    clock, _registry, _scheduler, lifecycle, lease = team()
    monkeypatch.setattr("codeteam.events.time.time", lambda: 1000000)
    clock.now = 14
    lifecycle.heartbeat(lease)
    monkeypatch.setattr("codeteam.events.time.time", lambda: 1)
    clock.now = 28
    assert lifecycle.detect_timeouts() == ()
    clock.now = 29
    assert len(lifecycle.detect_timeouts()) == 1


@pytest.mark.parametrize("running", [False, True])
def test_stop_respects_exhausted_task_budget(running: bool) -> None:
    _clock, registry, scheduler, lifecycle, lease = team(max_attempts=1)
    owned(scheduler, lease, running=running)
    assert lifecycle.stop_worker(lease).outcome is RecoveryOutcome.TASK_FAILED
    assert scheduler.runtime_records["A"].status is TaskStatus.FAILED
    assert scheduler.runtime_records["B"].status is TaskStatus.BLOCKED
    assert registry.runtime("w1").status is AgentStatus.STOPPED
    assert scheduler.queue == ()


def test_zero_restart_budget_and_repeated_sweep_never_call_factory() -> None:
    def forbidden(info: AgentInfo) -> WorkerAgent:
        pytest.fail("factory must not run without restart budget")

    clock, registry, scheduler, lifecycle, lease = team(
        factory=forbidden, max_restarts=0
    )
    owned(scheduler, lease, running=False)
    clock.now = 15
    assert lifecycle.sweep().restarts[0].outcome is RestartOutcome.EXHAUSTED
    before = scheduler.snapshot()
    assert lifecycle.sweep().restarts[0].outcome is RestartOutcome.EXHAUSTED
    assert scheduler.snapshot() == before
    assert registry.runtime("w1").restart_attempts == 0
    assert registry.events[-1].event_type is AgentEventType.WORKER_RESTART_REJECTED


def test_old_failure_ticket_cannot_overwrite_new_reservation_same_generation() -> None:
    clock, registry, scheduler, lifecycle, lease = team()
    clock.now = 15
    scheduler.recover_worker_loss(
        lifecycle.detect_timeouts()[0], heartbeat_timeout_seconds=15
    )
    first = registry.reserve_restart(lease, policy=lifecycle.policy)
    assert not isinstance(first, RestartResult)
    registry.finish_restart_failure(first, error_type="ValueError")
    clock.now = 17
    second = registry.reserve_restart(lease, policy=lifecycle.policy)
    assert not isinstance(second, RestartResult)
    assert second.lease.generation == first.lease.generation
    assert second.restart_id != first.restart_id
    before = registry.runtime("w1")
    assert (
        registry.finish_restart_failure(first, error_type="RuntimeError").outcome
        is RestartOutcome.STALE_TICKET
    )
    assert registry.runtime("w1") == before


def test_mailbox_backlog_does_not_block_heartbeat_or_advance_task() -> None:
    from codeteam.agent_team.mailbox import MailboxFullError

    from .test_mailbox import _mailbox, _message

    clock, registry, scheduler, lifecycle, lease = team()
    owned(scheduler, lease, running=True)
    mailbox = _mailbox("lead", "w1", capacity_per_inbox=1)
    mailbox.send(_message("one", recipient_id="w1"))
    with pytest.raises(MailboxFullError):
        mailbox.send(_message("two", recipient_id="w1"))
    before = scheduler.runtime_records
    clock.now = 14
    lifecycle.heartbeat(lease)
    assert registry.runtime("w1").last_heartbeat_monotonic == 14
    assert scheduler.runtime_records == before
    assert mailbox.queue_size("w1") == 1


@pytest.mark.parametrize("_repeat", range(10))
def test_claim_vs_recovery_keeps_combined_snapshot_consistent(_repeat: int) -> None:
    clock, registry, scheduler, lifecycle, lease = team()
    clock.now = 15
    candidate = lifecycle.detect_timeouts()[0]  # READY, no owner yet.
    barrier = Barrier(3)
    errors: list[BaseException] = []

    def claim() -> None:
        try:
            barrier.wait(WAIT)
            scheduler.claim(lease)
        except WorkerUnavailableError:
            pass
        except BaseException as exc:  # noqa: BLE001 - assert thread errors in parent.
            errors.append(exc)

    def recover() -> None:
        try:
            barrier.wait(WAIT)
            scheduler.recover_worker_loss(candidate, heartbeat_timeout_seconds=15)
        except BaseException as exc:  # noqa: BLE001 - assert thread errors in parent.
            errors.append(exc)

    def observe() -> None:
        try:
            barrier.wait(WAIT)
            for _ in range(10):
                snapshot = scheduler.snapshot()
                task, worker = snapshot.tasks["A"], snapshot.workers["w1"]
                assert len(snapshot.queue) == len(set(snapshot.queue))
                if task.status is TaskStatus.CLAIMED:
                    assert task.owner_id == "w1"
                    assert task.owner_generation == worker.generation
                    assert worker.status is AgentStatus.BUSY
                    assert snapshot.ownership["w1"] == "A"
                    assert snapshot.queue == ()
                else:
                    assert task.status is TaskStatus.READY
                    assert task.owner_id is None
                    assert worker.status in {AgentStatus.READY, AgentStatus.FAILED}
                    assert snapshot.queue == ("A",)
        except BaseException as exc:  # noqa: BLE001 - assert thread errors in parent.
            errors.append(exc)

    threads = [Thread(target=operation) for operation in (claim, recover, observe)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(WAIT)
        assert not thread.is_alive()
    assert errors == []
    assert registry.runtime("w1").status in {AgentStatus.BUSY, AgentStatus.FAILED}


def test_concurrent_sweeps_reserve_only_one_factory_and_requeue_once() -> None:
    entered, release = Event(), Event()
    calls: list[str] = []
    errors: list[BaseException] = []

    def factory(info: AgentInfo) -> WorkerAgent:
        calls.append(info.identity.agent_id)
        entered.set()
        assert release.wait(WAIT)
        return WorkerAgent(info)

    clock, registry, scheduler, lifecycle, lease = team(factory=factory)
    owned(scheduler, lease, running=True)
    clock.now = 15

    def sweep() -> None:
        try:
            lifecycle.sweep()
        except BaseException as exc:  # noqa: BLE001 - assert thread errors in parent.
            errors.append(exc)

    first = Thread(target=sweep)
    first.start()
    try:
        assert entered.wait(WAIT)
        second = Thread(target=sweep)
        second.start()
        second.join(WAIT)
        assert not second.is_alive()
    finally:
        release.set()
        first.join(WAIT)
    assert not first.is_alive()
    assert errors == []
    assert calls == ["w1"]
    assert scheduler.queue == ("A",)
    assert registry.runtime("w1").restart_attempts == 1
    assert registry.runtime("w1").generation == 2


def test_worker_observer_runs_outside_core_lock() -> None:
    entered, release = Event(), Event()
    observations: list[AgentStatus] = []

    def sink(event: AgentEvent) -> None:
        entered.set()
        assert release.wait(WAIT)

    _clock, registry, _scheduler, lifecycle, lease = team(sink=sink)
    sender = Thread(target=lambda: lifecycle.heartbeat(lease))
    sender.start()
    try:
        assert entered.wait(WAIT)
        reader = Thread(
            target=lambda: observations.append(registry.runtime("w1").status)
        )
        reader.start()
        reader.join(WAIT)
        assert not reader.is_alive()
    finally:
        release.set()
        sender.join(WAIT)
    assert not sender.is_alive()
    assert observations == [AgentStatus.READY]


def test_public_lifecycle_exports_and_wrong_registry_rejected() -> None:
    from codeteam.agent_team import AgentLifecycleManager as PublicLifecycle
    from codeteam.agent_team import AgentRegistry as PublicRegistry
    from codeteam.agent_team import WorkerRegistry

    assert PublicLifecycle is AgentLifecycleManager
    assert PublicRegistry is WorkerRegistry is AgentRegistry
    _clock, _registry, scheduler, _lifecycle, _lease = team()
    with pytest.raises(ValueError, match="same Registry"):
        AgentLifecycleManager(AgentRegistry(), scheduler)
