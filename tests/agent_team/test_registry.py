from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from codeteam.agent_team.contracts import (
    InvalidClockError,
    LifecyclePolicy,
    StaleWorkerGenerationError,
    WorkerLease,
    WorkerStateError,
)
from codeteam.agent_team.registry import AgentRegistry
from codeteam.agent_team.scheduler import SchedulerInitializationError, TaskScheduler
from codeteam.agent_team.worker import WorkerRegistry

from .test_scheduler import _dag, _worker


@dataclass
class FakeClock:
    now: float = 0.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("cannot rewind")
        self.now += seconds


def test_registry_alias_and_single_scheduler_domain() -> None:
    assert WorkerRegistry is AgentRegistry
    registry = AgentRegistry()
    worker = _worker("w1")
    lease = registry.register(worker)
    assert registry.get("w1") is worker
    assert registry.lease("w1") == lease
    scheduler = TaskScheduler(_dag("A"), registry)
    assert scheduler.registry is registry
    with pytest.raises(SchedulerInitializationError, match="already"):
        TaskScheduler(_dag("B"), registry)
    with pytest.raises(WorkerStateError, match="already"):
        AgentRegistry(coordinator=registry.coordinator)


def test_first_heartbeat_grace_is_registration_time_not_zero() -> None:
    clock = FakeClock(100)
    registry = AgentRegistry(clock=clock)
    registry.register(_worker("w1"))
    scheduler = TaskScheduler(_dag("A"), registry)
    assert registry.runtime("w1").last_heartbeat_monotonic == 100
    assert scheduler.timeout_candidates(heartbeat_timeout_seconds=15) == ()
    clock.now = 115
    assert len(scheduler.timeout_candidates(heartbeat_timeout_seconds=15)) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("generation", 0),
        ("generation", -1),
        ("generation", True),
        ("worker_id", "  "),
        ("runtime_id", ""),
    ],
)
def test_lease_rejects_invalid_fields(field: str, value: object) -> None:
    data = {"worker_id": "w1", "runtime_id": "r1", "generation": 1, field: value}
    with pytest.raises(ValidationError):
        WorkerLease.model_validate(data)


def test_lease_requires_generation_and_roundtrips() -> None:
    with pytest.raises(ValidationError):
        WorkerLease.model_validate({"worker_id": "w1", "runtime_id": "r1"})
    lease = WorkerLease(worker_id="w1", runtime_id="r1", generation=1)
    assert WorkerLease.model_validate_json(lease.model_dump_json()) == lease


@pytest.mark.parametrize(
    "field,value",
    [
        ("heartbeat_timeout_seconds", 0),
        ("heartbeat_timeout_seconds", -1),
        ("heartbeat_timeout_seconds", float("inf")),
        ("heartbeat_timeout_seconds", True),
        ("heartbeat_timeout_seconds", "15"),
        ("restart_cooldown_seconds", float("nan")),
        ("restart_cooldown_seconds", -1),
        ("max_restarts", True),
        ("max_restarts", 1.5),
    ],
)
def test_policy_rejects_invalid_time_and_budget(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        LifecyclePolicy.model_validate({field: value})


@pytest.mark.parametrize("bad_time", [-1, float("inf"), float("nan"), True])
def test_bad_clock_does_not_mutate_worker(bad_time: float) -> None:
    clock = FakeClock()
    registry = AgentRegistry(clock=clock)
    lease = registry.register(_worker("w1"))
    before = registry.runtime("w1")
    clock.now = bad_time
    with pytest.raises(InvalidClockError):
        registry.heartbeat(lease)
    assert registry.runtime("w1") == before
    assert registry.events == ()


def test_clock_rewind_relative_to_previous_read_is_rejected() -> None:
    clock = FakeClock()
    registry = AgentRegistry(clock=clock)
    lease = registry.register(_worker("w1"))
    clock.now = 10
    registry.register(_worker("w2"))
    clock.now = 5  # Still after w1's last heartbeat, but behind domain clock.
    with pytest.raises(InvalidClockError):
        registry.heartbeat(lease)


def test_heartbeat_revision_changes_even_at_same_time_and_snapshot_is_defensive() -> (
    None
):
    registry = AgentRegistry(clock=FakeClock())
    lease = registry.register(_worker("w1"))
    first = registry.heartbeat(lease)
    second = registry.heartbeat(lease)
    assert second.revision == first.revision + 1
    assert second.last_heartbeat_monotonic == 0
    records = registry.runtime_records
    records.clear()
    assert registry.runtime("w1") == second
    registry.events[0].data.clear()
    assert registry.events[0].data["worker_id"] == "w1"


def test_heartbeat_rejects_wrong_runtime_and_inactive_states() -> None:
    from codeteam.agent_team.models import AgentStatus

    for status in (AgentStatus.CREATED, AgentStatus.FAILED, AgentStatus.STOPPED):
        registry = AgentRegistry()
        lease = registry.register(_worker("w1", status=status))
        with pytest.raises(WorkerStateError):
            registry.heartbeat(lease)
        with pytest.raises(StaleWorkerGenerationError):
            registry.heartbeat(lease.model_copy(update={"runtime_id": "other"}))
        if status is AgentStatus.CREATED:
            assert registry.activate(lease).status is AgentStatus.READY
            registry.heartbeat(lease)
