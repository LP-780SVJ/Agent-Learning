"""Regression evidence for the Day5 acceptance P1/P2 fixes."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, Thread
from typing import cast

import pytest

from codeteam.agent_team.contracts import RestartTicket
from codeteam.agent_team.dag import TaskStatus
from codeteam.agent_team.lifecycle import AgentLifecycleManager
from codeteam.agent_team.models import AgentInfo, AgentStatus
from codeteam.agent_team.registry import AgentRegistry
from codeteam.agent_team.scheduler import TaskClaim, TaskScheduler
from codeteam.agent_team.worker import WorkerAgent
from codeteam.events import AgentEvent, AgentEventType

from .test_lifecycle import WAIT, owned, team
from .test_lifecycle_acceptance import assert_consistent, full_state
from .test_registry import FakeClock
from .test_scheduler import _dag, _worker


@pytest.mark.parametrize("stage", ["reservation_observer", "factory"])
@pytest.mark.parametrize("interrupt_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize(
    "secondary_type", [None, RuntimeError, KeyboardInterrupt, SystemExit]
)
def test_restart_interrupt_preserves_original_and_committed_facts(
    stage: str,
    interrupt_type: type[BaseException],
    secondary_type: type[BaseException] | None,
) -> None:
    primary = interrupt_type("original synthetic interrupt")
    calls: list[str] = []
    cleanup_seen: list[AgentStatus] = []

    def factory(info: AgentInfo) -> WorkerAgent:
        calls.append(info.identity.agent_id)
        raise primary

    def sink(event: AgentEvent) -> None:
        if (
            event.event_type is AgentEventType.WORKER_RESTARTING
            and stage == "reservation_observer"
        ):
            raise primary
        if event.event_type is AgentEventType.WORKER_RESTART_FAILED:
            cleanup_seen.append(registry.runtime("w1").status)
            if secondary_type is not None:
                raise secondary_type("secondary secret must not be logged")

    clock, registry, scheduler, lifecycle, lease = team(factory=factory, sink=sink)
    original = registry.get("w1")
    owned(scheduler, lease, running=True)
    clock.now = 15
    scheduler.recover_worker_loss(
        lifecycle.detect_timeouts()[0], heartbeat_timeout_seconds=15
    )
    before = scheduler.snapshot()
    prior_events = registry.events
    with pytest.raises(interrupt_type) as raised:
        lifecycle.restart_worker(lease)
    assert raised.value is primary
    after = scheduler.snapshot()
    assert (after.tasks, after.queue, after.ownership) == (
        before.tasks,
        before.queue,
        before.ownership,
    )
    assert registry.get("w1") is original
    record = after.workers["w1"]
    assert (record.status, record.restart_id) == (AgentStatus.FAILED, None)
    assert record.generation == 1 and record.restart_attempts == 1
    assert record.next_restart_monotonic == 17
    assert calls == (["w1"] if stage == "factory" else [])
    assert cleanup_seen == [AgentStatus.FAILED]
    assert registry.events[: len(prior_events)] == prior_events
    new_events = registry.events[len(prior_events) :]
    assert [e.event_type for e in new_events[:2]] == [
        AgentEventType.WORKER_RESTARTING,
        AgentEventType.WORKER_RESTART_FAILED,
    ]
    assert new_events[0].data["restart_id"] == new_events[1].data["restart_id"]
    assert new_events[1].data["reason_code"] == "restart_interrupted"
    assert new_events[1].data["transaction_id"] > new_events[0].data["transaction_id"]
    if secondary_type is not None:
        assert new_events[-1].event_type is AgentEventType.WORKER_EVENT_DELIVERY_FAILED
        assert (
            new_events[-1].data["source_transaction_id"]
            == new_events[1].data["transaction_id"]
        )
        assert new_events[-1].data["error_type"] == secondary_type.__name__
        assert secondary_type.__name__ in " ".join(primary.__notes__)
    assert "secondary secret" not in repr(new_events)
    assert_consistent(scheduler)


@pytest.mark.parametrize("interrupt_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("stage", ["reservation_observer", "factory"])
def test_reentrant_stop_before_interrupt_is_not_overwritten(
    interrupt_type: type[BaseException],
    stage: str,
) -> None:
    primary = interrupt_type("stop then interrupt")

    def stop_then_interrupt() -> None:
        lifecycle.stop_worker(lease)
        raise primary

    def factory(info: AgentInfo) -> WorkerAgent:
        stop_then_interrupt()
        pytest.fail("interrupted factory must not return")

    def sink(event: AgentEvent) -> None:
        if (
            event.event_type is AgentEventType.WORKER_RESTARTING
            and stage == "reservation_observer"
        ):
            stop_then_interrupt()

    clock, registry, scheduler, lifecycle, lease = team(factory=factory, sink=sink)
    clock.now = 15
    scheduler.recover_worker_loss(
        lifecycle.detect_timeouts()[0], heartbeat_timeout_seconds=15
    )
    with pytest.raises(interrupt_type) as raised:
        lifecycle.restart_worker(lease)
    assert raised.value is primary
    record = registry.runtime("w1")
    assert record.status is AgentStatus.STOPPED
    assert record.restart_id is None and record.restart_attempts == 1
    assert record.generation == 1 and record.next_restart_monotonic == 17
    assert registry.events[-1].event_type is AgentEventType.WORKER_RESTART_REJECTED
    assert AgentEventType.WORKER_RESTART_FAILED not in [
        e.event_type for e in registry.events
    ]
    assert_consistent(scheduler)


@pytest.mark.parametrize("publish_new", [False, True])
def test_old_interrupt_cleanup_cannot_overwrite_new_ticket_or_generation(
    publish_new: bool,
) -> None:
    clock, registry, scheduler, lifecycle, lease = team()
    clock.now = 15
    scheduler.recover_worker_loss(
        lifecycle.detect_timeouts()[0], heartbeat_timeout_seconds=15
    )
    first = registry.reserve_restart(lease, policy=lifecycle.policy)
    assert isinstance(first, RestartTicket)
    registry.finish_restart_failure(first, error_type="ValueError")
    clock.now = 17
    newer = registry.reserve_restart(lease, policy=lifecycle.policy)
    assert isinstance(newer, RestartTicket)
    assert newer.restart_id != first.restart_id
    if publish_new:
        replacement = WorkerAgent(newer.info)
        registry.publish_restart(newer, replacement, replacement.info)
    before, original = scheduler.snapshot(), registry.get("w1")
    registry._interrupt_restart(first, KeyboardInterrupt())
    assert scheduler.snapshot() == before
    assert registry.get("w1") is original
    assert registry.events[-1].event_type is AgentEventType.WORKER_RESTART_REJECTED


@pytest.mark.parametrize(
    "field", ["runtime_id", "generation", "restart_id", "revision"]
)
def test_interrupt_cleanup_revalidates_every_ticket_fence(field: str) -> None:
    clock, registry, scheduler, lifecycle, lease = team()
    clock.now = 15
    scheduler.recover_worker_loss(
        lifecycle.detect_timeouts()[0], heartbeat_timeout_seconds=15
    )
    ticket = registry.reserve_restart(lease, policy=lifecycle.policy)
    assert isinstance(ticket, RestartTicket)
    if field in {"runtime_id", "generation"}:
        value: str | int = "other-runtime" if field == "runtime_id" else 2
        ticket = ticket.model_copy(
            update={"lease": ticket.lease.model_copy(update={field: value})}
        )
    else:
        update = (
            {"restart_id": "old-reservation"}
            if field == "restart_id"
            else {"expected_revision": ticket.expected_revision + 1}
        )
        ticket = ticket.model_copy(update=update)
    before = scheduler.snapshot()
    registry._interrupt_restart(ticket, SystemExit())
    assert scheduler.snapshot() == before
    assert registry.events[-1].event_type is AgentEventType.WORKER_RESTART_REJECTED


def test_cleanup_audit_error_does_not_mask_original_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = KeyboardInterrupt("original")

    def sink(event: AgentEvent) -> None:
        if event.event_type is AgentEventType.WORKER_RESTARTING:
            raise primary
        if event.event_type is AgentEventType.WORKER_RESTART_FAILED:
            raise SystemExit("secondary")

    def broken_audit(*args: object) -> None:
        raise RuntimeError("tertiary")

    clock, registry, scheduler, lifecycle, lease = team(sink=sink)
    clock.now = 15
    scheduler.recover_worker_loss(
        lifecycle.detect_timeouts()[0], heartbeat_timeout_seconds=15
    )
    monkeypatch.setattr(registry, "_record_delivery_failure", broken_audit)
    with pytest.raises(KeyboardInterrupt) as raised:
        lifecycle.restart_worker(lease)
    assert raised.value is primary
    assert registry.runtime("w1").status is AgentStatus.FAILED
    assert registry.runtime("w1").restart_id is None
    assert registry.events[-1].event_type is AgentEventType.WORKER_RESTART_FAILED
    assert "audit failed: RuntimeError" in " ".join(primary.__notes__)


def test_cleanup_observer_is_outside_lock_and_cannot_mask_interrupt() -> None:
    entered, release, read = Event(), Event(), Event()
    primary = KeyboardInterrupt("original")
    errors: list[BaseException] = []

    def sink(event: AgentEvent) -> None:
        if event.event_type is AgentEventType.WORKER_RESTARTING:
            raise primary
        if event.event_type is AgentEventType.WORKER_RESTART_FAILED:
            entered.set()
            assert release.wait(WAIT)
            raise SystemExit("secondary")

    clock, registry, scheduler, lifecycle, lease = team(sink=sink)
    clock.now = 15
    scheduler.recover_worker_loss(
        lifecycle.detect_timeouts()[0], heartbeat_timeout_seconds=15
    )

    def restart() -> None:
        try:
            lifecycle.restart_worker(lease)
        except BaseException as exc:  # noqa: BLE001 - assert exact exception in parent.
            errors.append(exc)

    def reader() -> None:
        try:
            assert registry.runtime("w1").status is AgentStatus.FAILED
            assert_consistent(scheduler)
            read.set()
        except BaseException as exc:  # noqa: BLE001 - surface thread assertion failures.
            errors.append(exc)

    worker = Thread(target=restart, daemon=True)
    observer = Thread(target=reader, daemon=True)
    worker.start()
    try:
        assert entered.wait(WAIT)
        observer.start()
        assert read.wait(WAIT), "cleanup observer must not hold the core lock"
    finally:
        release.set()
        worker.join(WAIT)
        if observer.ident is not None:
            observer.join(WAIT)
    assert not worker.is_alive() and not observer.is_alive()
    assert errors == [primary]


def _terminal_action(
    scheduler: TaskScheduler,
    lifecycle: AgentLifecycleManager,
    clock: FakeClock,
    claim: TaskClaim,
    cause: str,
) -> None:
    if cause == "timeout":
        clock.advance(15)
        candidates = lifecycle.detect_timeouts()
        candidate = next(
            item for item in candidates if item.lease.worker_id == claim.worker_id
        )
        scheduler.recover_worker_loss(candidate, heartbeat_timeout_seconds=15)
    elif cause == "stop":
        lifecycle.stop_worker(scheduler.registry.lease(claim.worker_id))
    else:
        scheduler.fail(claim, "terminal", retryable=cause != "non_retryable")


@pytest.mark.parametrize(
    "cause,running",
    [
        ("timeout", False),
        ("timeout", True),
        ("stop", False),
        ("stop", True),
        ("fail", True),
        ("non_retryable", True),
    ],
)
@pytest.mark.parametrize("shape", ["long_chain", "diamond"])
@pytest.mark.parametrize("reverse_names", [False, True])
def test_terminal_closure_is_atomic_and_independent_of_node_names(
    cause: str,
    running: bool,
    shape: str,
    reverse_names: bool,
) -> None:
    count = 64 if shape == "long_chain" else 6
    names = [f"N{i:03d}" for i in range(count)]
    if reverse_names:
        names.reverse()
    clock = FakeClock()
    registry = AgentRegistry(clock=clock)
    lease = registry.register(_worker("w1"))
    dag = _dag(*names, "zz-independent", "zz-child")
    edges = (
        list(zip(range(count - 1), range(1, count)))
        if shape == "long_chain"
        else [
            (0, 1),
            (0, 2),
            (1, 3),
            (2, 3),
            (3, 4),
            (4, 5),
        ]
    )
    for parent, child in edges:
        dag.add_dependency(names[parent], names[child])
    dag.add_dependency("zz-independent", "zz-child")
    scheduler = TaskScheduler(
        dag, registry, max_attempts=3 if cause == "non_retryable" else 1
    )
    lifecycle = AgentLifecycleManager(registry, scheduler)
    scheduler.schedule()
    claim = owned(scheduler, lease, running=running)
    assert claim.node_id == names[0]
    before = scheduler.snapshot()
    previous_count = len(scheduler.events)
    _terminal_action(scheduler, lifecycle, clock, claim, cause)
    after = scheduler.snapshot()
    assert [after.tasks[key].status for key in names] == [TaskStatus.FAILED] + [
        TaskStatus.BLOCKED
    ] * (count - 1)
    for key in names:
        assert after.tasks[key].owner_id is None
        assert after.tasks[key].owner_generation is None
        assert after.tasks[key].attempt == before.tasks[key].attempt
    for key in ("zz-independent", "zz-child"):
        assert after.tasks[key] == before.tasks[key]
    assert after.queue == before.queue == ("zz-independent",)
    events = scheduler.events[previous_count:]
    blocked = [
        e for e in events if e.event_type is AgentEventType.SCHEDULER_TASK_BLOCKED
    ]
    assert [e.data["node_id"] for e in blocked] == sorted(names[1:])
    assert len(blocked) == count - 1
    assert len({e.data["transaction_id"] for e in events}) == 1
    if cause in {"timeout", "stop"}:
        assert (
            registry.events[-1].data["transaction_id"]
            == events[0].data["transaction_id"]
        )
    assert_consistent(scheduler)
    prior = (scheduler.events, registry.events)
    scheduler.schedule()
    assert scheduler.snapshot() == after
    assert (scheduler.events, registry.events) == prior


@pytest.mark.parametrize(
    "cause,running",
    [
        ("timeout", False),
        ("timeout", True),
        ("stop", False),
        ("stop", True),
        ("fail", True),
    ],
)
def test_retry_blocks_descendants_only_after_budget_is_exhausted(
    cause: str, running: bool
) -> None:
    clock = FakeClock()
    registry = AgentRegistry(clock=clock)
    first_lease = registry.register(_worker("w1"))
    second_lease = registry.register(_worker("w2"))
    dag = _dag("Z", "M", "A")
    dag.add_dependency("Z", "M")
    dag.add_dependency("M", "A")
    scheduler = TaskScheduler(dag, registry, max_attempts=2)
    lifecycle = AgentLifecycleManager(registry, scheduler)
    scheduler.schedule()
    first = owned(scheduler, first_lease, running=running)
    _terminal_action(scheduler, lifecycle, clock, first, cause)
    assert scheduler.queue == ("Z",)
    assert scheduler.runtime_records["Z"].status is TaskStatus.READY
    assert scheduler.runtime_records["M"].status is TaskStatus.PENDING
    assert scheduler.runtime_records["A"].status is TaskStatus.PENDING
    assert AgentEventType.SCHEDULER_TASK_BLOCKED not in [
        e.event_type for e in scheduler.events
    ]
    scheduler.schedule()
    assert scheduler.queue == ("Z",)
    registry.heartbeat(second_lease)
    second = owned(scheduler, second_lease, running=running)
    _terminal_action(scheduler, lifecycle, clock, second, cause)
    assert second.attempt == 2
    assert scheduler.queue == ()
    assert scheduler.runtime_records["Z"].status is TaskStatus.FAILED
    assert scheduler.runtime_records["M"].status is TaskStatus.BLOCKED
    assert scheduler.runtime_records["A"].status is TaskStatus.BLOCKED
    assert_consistent(scheduler)


@pytest.mark.parametrize("cause", ["timeout", "stop", "fail"])
def test_descendant_event_failure_rolls_back_entire_terminal_transaction(
    cause: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    registry = AgentRegistry(clock=clock)
    lease = registry.register(_worker("w1"))
    dag = _dag("Z", "M", "A")
    dag.add_dependency("Z", "M")
    dag.add_dependency("M", "A")
    scheduler = TaskScheduler(dag, registry)
    lifecycle = AgentLifecycleManager(registry, scheduler)
    scheduler.schedule()
    claim = owned(scheduler, lease, running=True)
    original = scheduler._record_event_locked
    appended: list[str] = []

    def broken(*args: object, **kwargs: object) -> None:
        cast(Callable[..., None], original)(*args, **kwargs)
        if args[1] is AgentEventType.SCHEDULER_TASK_BLOCKED:
            appended.append(str(kwargs["node_id"]))
            if len(appended) == 2:
                raise ValueError("second descendant event failed")

    before = full_state(scheduler)
    monkeypatch.setattr(scheduler, "_record_event_locked", broken)
    with pytest.raises(ValueError, match="second descendant"):
        _terminal_action(scheduler, lifecycle, clock, claim, cause)
    assert appended == ["A", "M"]
    assert full_state(scheduler) == before
    assert_consistent(scheduler)
