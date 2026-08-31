from __future__ import annotations

from threading import Barrier, Thread
from threading import Event as ThreadEvent
from types import MappingProxyType

import pytest

from codeteam.agent_team.dag import CycleDetectedError, TaskDAG, TaskNode, TaskStatus
from codeteam.agent_team.models import (
    AgentIdentity,
    AgentInfo,
    AgentRole,
    AgentStatus,
    WorkerAssignment,
)
from codeteam.agent_team.scheduler import (
    TASK_TRANSITIONS,
    InvalidSchedulerTransitionError,
    SchedulerError,
    SchedulerInitializationError,
    SchedulerResult,
    StaleTaskStateError,
    TaskClaim,
    TaskOwnershipError,
    TaskRuntimeRecord,
    TaskScheduler,
    WorkerRoleMismatchError,
    WorkerUnavailableError,
)
from codeteam.agent_team.worker import WorkerAgent, WorkerNotFoundError, WorkerRegistry
from codeteam.events import AgentEvent, AgentEventType

JOIN_TIMEOUT_SECONDS = 2.0


def _assignment(node_id: str, role: AgentRole = AgentRole.BACKEND) -> WorkerAssignment:
    return WorkerAssignment(
        assignment_id=node_id,
        task_id="task-1",
        source_step_id=f"step-{node_id}",
        role=role,
        goal=f"Complete {node_id}",
        expected_output=f"{node_id} complete",
    )


def _dag(*node_specs: str | tuple[str, AgentRole]) -> TaskDAG:
    dag = TaskDAG()
    for spec in node_specs:
        if isinstance(spec, tuple):
            node_id, role = spec
        else:
            node_id, role = spec, AgentRole.BACKEND
        dag.add_task(
            TaskNode(
                node_id=node_id,
                assignment=_assignment(node_id, role),
            )
        )
    return dag


def _worker(
    worker_id: str,
    role: AgentRole = AgentRole.BACKEND,
    *,
    status: AgentStatus = AgentStatus.READY,
) -> WorkerAgent:
    return WorkerAgent(
        AgentInfo(
            identity=AgentIdentity(agent_id=worker_id, display_name=worker_id),
            role=role,
            status=status,
        )
    )


def _registry(*workers: WorkerAgent) -> WorkerRegistry:
    registry = WorkerRegistry()
    for worker in workers:
        registry.register(worker)
    return registry


def _scheduler(
    dag: TaskDAG,
    *,
    workers: tuple[WorkerAgent, ...] | None = None,
    max_attempts: int = 1,
) -> TaskScheduler:
    return TaskScheduler(
        dag,
        _registry(*(workers or (_worker("worker-backend-1"),))),
        max_attempts=max_attempts,
    )


def _join_threads(threads: list[Thread]) -> None:
    for thread in threads:
        thread.join(timeout=JOIN_TIMEOUT_SECONDS)
    live_threads = [thread.name for thread in threads if thread.is_alive()]
    assert live_threads == []


def test_scheduler_models_are_serializable() -> None:
    record = TaskRuntimeRecord(
        node_id="A",
        status=TaskStatus.READY,
        owner_id="worker-1",
        attempt=1,
        claimed_at=1.25,
    )
    claim = TaskClaim(
        node_id="A",
        worker_id="worker-1",
        runtime_id="runtime-1",
        worker_generation=1,
        attempt=1,
        claimed_at=1.25,
    )
    result = SchedulerResult(scheduled=("A",))

    assert TaskRuntimeRecord.model_validate_json(record.model_dump_json()) == record
    assert TaskClaim.model_validate_json(claim.model_dump_json()) == claim
    assert SchedulerResult.model_validate_json(result.model_dump_json()) == result


def test_transition_table_is_immutable_and_rejects_forbidden_paths() -> None:
    assert isinstance(TASK_TRANSITIONS, MappingProxyType)
    assert TaskStatus.COMPLETED not in TASK_TRANSITIONS[TaskStatus.PENDING]
    assert TaskStatus.RUNNING not in TASK_TRANSITIONS[TaskStatus.READY]
    assert TaskStatus.COMPLETED not in TASK_TRANSITIONS[TaskStatus.FAILED]
    assert TaskStatus.RUNNING not in TASK_TRANSITIONS[TaskStatus.COMPLETED]
    assert TaskStatus.CLAIMED in TASK_TRANSITIONS[TaskStatus.READY]

    with pytest.raises(TypeError):
        TASK_TRANSITIONS[TaskStatus.READY] = (  # type: ignore[index]
            TaskStatus.RUNNING,
        )
    with pytest.raises(AttributeError):
        TASK_TRANSITIONS[TaskStatus.READY].append(  # type: ignore[attr-defined]
            TaskStatus.RUNNING
        )


def test_transition_table_mutation_attempt_does_not_break_scheduler() -> None:
    scheduler = _scheduler(_dag("A"))

    scheduler.schedule()
    claim = scheduler.claim(scheduler.registry.lease("worker-backend-1"))

    assert claim is not None
    assert claim.node_id == "A"


def test_ready_task_is_enqueued_once_and_schedule_is_idempotent() -> None:
    scheduler = _scheduler(_dag("A"))

    first = scheduler.schedule()
    second = scheduler.schedule()

    assert first.scheduled == ("A",)
    assert second.scheduled == ()
    assert second.already_ready == ("A",)
    assert scheduler.queue == ("A",)
    assert scheduler.runtime_records["A"].status is TaskStatus.READY


def test_claim_assigns_unique_owner_and_marks_worker_busy() -> None:
    scheduler = _scheduler(_dag("A"))
    scheduler.schedule()

    claim = scheduler.claim(scheduler.registry.lease("worker-backend-1"))

    assert claim is not None
    assert claim.node_id == "A"
    record = scheduler.runtime_records["A"]
    assert record.status is TaskStatus.CLAIMED
    assert record.owner_id == "worker-backend-1"
    assert record.attempt == 1
    assert scheduler.queue == ()

    with pytest.raises(WorkerUnavailableError):
        scheduler.claim(scheduler.registry.lease("worker-backend-1"))


def test_empty_queue_claim_returns_none() -> None:
    scheduler = _scheduler(_dag("A"))

    assert scheduler.claim(scheduler.registry.lease("worker-backend-1")) is None


def test_unknown_worker_is_rejected() -> None:
    scheduler = _scheduler(_dag("A"))
    scheduler.schedule()

    with pytest.raises(WorkerNotFoundError, match="missing-worker"):
        scheduler.claim(scheduler.registry.lease("missing-worker"))


def test_role_mismatch_does_not_leave_half_written_claim() -> None:
    scheduler = _scheduler(
        _dag(("A", AgentRole.BACKEND)),
        workers=(
            _worker("worker-backend-1", AgentRole.BACKEND),
            _worker("worker-frontend-1", AgentRole.FRONTEND),
        ),
    )
    scheduler.schedule()

    with pytest.raises(WorkerRoleMismatchError):
        scheduler.claim(scheduler.registry.lease("worker-frontend-1"))

    record = scheduler.runtime_records["A"]
    assert record.status is TaskStatus.READY
    assert record.owner_id is None
    assert scheduler.queue == ("A",)


@pytest.mark.parametrize("status", [AgentStatus.BUSY, AgentStatus.FAILED, AgentStatus.STOPPED])
def test_unavailable_worker_status_cannot_claim(status: AgentStatus) -> None:
    scheduler = _scheduler(
        _dag("A"),
        workers=(_worker("worker-backend-1", status=status),),
    )
    scheduler.schedule()

    with pytest.raises(WorkerUnavailableError):
        scheduler.claim(scheduler.registry.lease("worker-backend-1"))

    assert scheduler.runtime_records["A"].owner_id is None
    assert scheduler.queue == ("A",)


def test_two_workers_contend_for_one_task_and_only_one_claims() -> None:
    scheduler = _scheduler(
        _dag("A"),
        workers=(
            _worker("worker-backend-1"),
            _worker("worker-backend-2"),
        ),
    )
    scheduler.schedule()
    barrier = Barrier(2)
    claims: list[TaskClaim | None] = []
    errors: list[BaseException] = []

    def contender(worker_id: str) -> None:
        try:
            barrier.wait()
            claims.append(scheduler.claim(scheduler.registry.lease(worker_id)))
        except (RuntimeError, SchedulerError, WorkerNotFoundError) as exc:
            errors.append(exc)

    threads = [
        Thread(target=contender, args=("worker-backend-1",)),
        Thread(target=contender, args=("worker-backend-2",)),
    ]
    for thread in threads:
        thread.start()
    _join_threads(threads)

    assert errors == []
    successful_claims = [claim for claim in claims if claim is not None]
    assert len(successful_claims) == 1
    assert scheduler.runtime_records["A"].owner_id in {
        "worker-backend-1",
        "worker-backend-2",
    }
    assert scheduler.queue == ()


def test_many_workers_claim_many_tasks_without_duplicates_or_loss() -> None:
    dag = _dag(*(f"N{index:02d}" for index in range(10)))
    workers = tuple(_worker(f"worker-{index:02d}") for index in range(10))
    scheduler = _scheduler(dag, workers=workers)
    scheduler.schedule()
    barrier = Barrier(len(workers))
    claims: list[TaskClaim | None] = []
    errors: list[BaseException] = []

    def contender(worker: WorkerAgent) -> None:
        try:
            barrier.wait()
            claims.append(scheduler.claim(scheduler.registry.lease(worker.info.identity.agent_id)))
        except (RuntimeError, SchedulerError, WorkerNotFoundError) as exc:
            errors.append(exc)

    threads = [Thread(target=contender, args=(worker,)) for worker in workers]
    for thread in threads:
        thread.start()
    _join_threads(threads)

    assert errors == []
    claimed_ids = sorted(claim.node_id for claim in claims if claim is not None)
    assert claimed_ids == [f"N{index:02d}" for index in range(10)]
    assert scheduler.queue == ()


def test_start_complete_requires_owner_and_unlocks_dependent() -> None:
    dag = _dag("A", "B")
    dag.add_dependency("A", "B")
    scheduler = _scheduler(
        dag,
        workers=(
            _worker("worker-backend-1"),
            _worker("worker-backend-2"),
        ),
    )
    scheduler.schedule()
    claim = scheduler.claim(scheduler.registry.lease("worker-backend-1"))
    assert claim is not None
    scheduler.start(claim)

    with pytest.raises(TaskOwnershipError):
        scheduler.complete(claim.model_copy(update={"worker_id": "worker-backend-2"}))

    completed = scheduler.complete(claim)

    assert completed.status is TaskStatus.COMPLETED
    assert completed.owner_id is None
    assert scheduler.runtime_records["B"].status is TaskStatus.READY
    assert scheduler.queue == ("B",)


def test_fail_requires_owner() -> None:
    scheduler = _scheduler(
        _dag("A"),
        workers=(
            _worker("worker-backend-1"),
            _worker("worker-backend-2"),
        ),
    )
    scheduler.schedule()
    claim = scheduler.claim(scheduler.registry.lease("worker-backend-1"))
    assert claim is not None
    scheduler.start(claim)

    with pytest.raises(TaskOwnershipError):
        scheduler.fail(claim.model_copy(update={"worker_id": "worker-backend-2"}), "not mine")

    record = scheduler.runtime_records["A"]
    assert record.status is TaskStatus.RUNNING
    assert record.owner_id == "worker-backend-1"


def test_invalid_state_progression_is_rejected_without_half_write() -> None:
    scheduler = _scheduler(_dag("A"))
    scheduler.schedule()
    claim = scheduler.claim(scheduler.registry.lease("worker-backend-1"))
    assert claim is not None

    with pytest.raises(StaleTaskStateError):
        scheduler.complete(claim)

    record = scheduler.runtime_records["A"]
    assert record.status is TaskStatus.CLAIMED
    assert record.owner_id == "worker-backend-1"


def test_retry_under_limit_requeues_and_clears_owner() -> None:
    scheduler = _scheduler(_dag("A"), max_attempts=2)
    scheduler.schedule()
    claim = scheduler.claim(scheduler.registry.lease("worker-backend-1"))
    assert claim is not None
    scheduler.start(claim)

    retried = scheduler.fail(claim, "test failed")

    assert retried.status is TaskStatus.READY
    assert retried.owner_id is None
    assert retried.attempt == 1
    assert retried.failure_reason == "test failed"
    assert scheduler.queue == ("A",)


def test_retry_limit_keeps_terminal_failed() -> None:
    scheduler = _scheduler(_dag("A"), max_attempts=1)
    scheduler.schedule()
    claim = scheduler.claim(scheduler.registry.lease("worker-backend-1"))
    assert claim is not None
    scheduler.start(claim)

    failed = scheduler.fail(claim, "test failed")

    assert failed.status is TaskStatus.FAILED
    assert failed.owner_id is None
    assert failed.attempt == 1
    assert scheduler.queue == ()


def test_non_retryable_failure_blocks_dependent() -> None:
    dag = _dag("A", "B")
    dag.add_dependency("A", "B")
    scheduler = _scheduler(dag, max_attempts=3)
    scheduler.schedule()
    claim = scheduler.claim(scheduler.registry.lease("worker-backend-1"))
    assert claim is not None
    scheduler.start(claim)

    scheduler.fail(claim, "policy denied", retryable=False)

    assert scheduler.runtime_records["A"].status is TaskStatus.FAILED
    assert scheduler.runtime_records["B"].status is TaskStatus.BLOCKED
    assert scheduler.queue == ()


def test_missing_worker_role_waits_and_can_recover_after_registration() -> None:
    registry = _registry(_worker("worker-backend-1", AgentRole.BACKEND))
    scheduler = TaskScheduler(_dag(("A", AgentRole.TEST)), registry)

    result = scheduler.schedule()

    assert result.waiting_for_worker == ("A",)
    assert result.blocked == ()
    record = scheduler.runtime_records["A"]
    assert record.status is TaskStatus.PENDING
    assert record.failure_reason is None
    assert scheduler.queue == ()

    repeat = scheduler.schedule()
    assert repeat.waiting_for_worker == ("A",)
    assert [
        event.event_type
        for event in scheduler.events
        if event.event_type is AgentEventType.SCHEDULER_TASK_WAITING_FOR_WORKER
    ] == [AgentEventType.SCHEDULER_TASK_WAITING_FOR_WORKER]

    registry.register(_worker("worker-test-1", AgentRole.TEST))
    recovered = scheduler.schedule()

    assert recovered.scheduled == ("A",)
    assert scheduler.runtime_records["A"].status is TaskStatus.READY
    assert scheduler.queue == ("A",)


def test_runtime_record_snapshots_do_not_mutate_scheduler() -> None:
    scheduler = _scheduler(_dag("A"))
    scheduler.schedule()
    record = scheduler.runtime_records["A"]

    record.status = "corrupted"  # type: ignore[assignment]
    record.owner_id = "mutated"

    fresh = scheduler.runtime_records["A"]
    assert fresh.status is TaskStatus.READY
    assert fresh.owner_id is None


def test_scheduler_events_use_existing_event_log_and_safe_fields() -> None:
    scheduler = _scheduler(_dag("A"))
    scheduler.schedule()
    claim = scheduler.claim(scheduler.registry.lease("worker-backend-1"))
    assert claim is not None
    scheduler.start(claim)
    scheduler.complete(claim)

    event_types = [event.event_type for event in scheduler.events]
    assert event_types == [
        AgentEventType.SCHEDULER_TASK_SCHEDULED,
        AgentEventType.SCHEDULER_TASK_CLAIMED,
        AgentEventType.SCHEDULER_TASK_STARTED,
        AgentEventType.SCHEDULER_TASK_COMPLETED,
    ]
    for event in scheduler.events:
        assert set(event.data) <= {
            "node_id",
            "worker_id",
            "from_status",
            "to_status",
            "attempt",
            "reason_code",
            "failed_event_type",
            "error_type",
            "runtime_id",
            "generation",
            "transaction_id",
            "transaction_event_index",
        }


def test_event_sink_receives_scheduler_event_snapshot() -> None:
    received: list[AgentEvent] = []
    scheduler = TaskScheduler(
        _dag("A"),
        _registry(_worker("worker-backend-1")),
        event_sink=received.append,
    )

    scheduler.schedule()

    assert len(received) == 1
    assert received[0].event_type is AgentEventType.SCHEDULER_TASK_SCHEDULED

    received[0].data["node_id"] = "mutated"
    assert scheduler.events[0].data["node_id"] == "A"


def test_event_sink_can_read_scheduler_events_without_deadlock() -> None:
    scheduler_ref: dict[str, TaskScheduler] = {}
    seen_event_count: list[int] = []

    def sink(_event: object) -> None:
        seen_event_count.append(len(scheduler_ref["scheduler"].events))

    scheduler = TaskScheduler(
        _dag("A"),
        _registry(_worker("worker-backend-1")),
        event_sink=sink,
    )
    scheduler_ref["scheduler"] = scheduler
    thread = Thread(target=scheduler.schedule)

    thread.start()
    _join_threads([thread])

    assert seen_event_count == [1]


def test_event_sink_can_read_runtime_records_without_deadlock() -> None:
    scheduler_ref: dict[str, TaskScheduler] = {}
    statuses: list[TaskStatus] = []

    def sink(_event: object) -> None:
        statuses.append(scheduler_ref["scheduler"].runtime_records["A"].status)

    scheduler = TaskScheduler(
        _dag("A"),
        _registry(_worker("worker-backend-1")),
        event_sink=sink,
    )
    scheduler_ref["scheduler"] = scheduler
    thread = Thread(target=scheduler.schedule)

    thread.start()
    _join_threads([thread])

    assert statuses == [TaskStatus.READY]


def test_raising_event_sink_does_not_hide_successful_claim() -> None:
    delivered_types: list[AgentEventType] = []

    def sink(event: object) -> None:
        delivered_types.append(event.event_type)  # type: ignore[attr-defined]
        raise RuntimeError("sink failed")

    scheduler = TaskScheduler(
        _dag("A"),
        _registry(_worker("worker-backend-1")),
        event_sink=sink,
    )
    scheduler.schedule()

    claim = scheduler.claim(scheduler.registry.lease("worker-backend-1"))

    assert claim is not None
    assert claim.node_id == "A"
    record = scheduler.runtime_records["A"]
    assert record.status is TaskStatus.CLAIMED
    assert record.owner_id == "worker-backend-1"
    assert scheduler.queue == ()
    assert delivered_types == [
        AgentEventType.SCHEDULER_TASK_SCHEDULED,
        AgentEventType.SCHEDULER_TASK_CLAIMED,
    ]
    assert [
        event.event_type for event in scheduler.events
    ] == [
        AgentEventType.SCHEDULER_TASK_SCHEDULED,
        AgentEventType.SCHEDULER_EVENT_DELIVERY_FAILED,
        AgentEventType.SCHEDULER_TASK_CLAIMED,
        AgentEventType.SCHEDULER_EVENT_DELIVERY_FAILED,
    ]


def test_slow_event_sink_does_not_hold_scheduler_state_lock() -> None:
    entered_sink = ThreadEvent()
    release_sink = ThreadEvent()

    def sink(_event: object) -> None:
        entered_sink.set()
        release_sink.wait(timeout=JOIN_TIMEOUT_SECONDS)

    scheduler = TaskScheduler(
        _dag("A"),
        _registry(_worker("worker-backend-1")),
        event_sink=sink,
    )
    schedule_thread = Thread(target=scheduler.schedule)
    status_seen: list[TaskStatus] = []

    def read_state() -> None:
        status_seen.append(scheduler.runtime_records["A"].status)

    schedule_thread.start()
    assert entered_sink.wait(timeout=JOIN_TIMEOUT_SECONDS)
    reader_thread = Thread(target=read_state)
    reader_thread.start()
    _join_threads([reader_thread])
    release_sink.set()
    _join_threads([schedule_thread])

    assert status_seen == [TaskStatus.READY]


def test_events_property_returns_defensive_event_copies() -> None:
    scheduler = _scheduler(_dag("A"))
    scheduler.schedule()
    event = scheduler.events[0]

    event.data["node_id"] = "mutated"

    assert scheduler.events[0].data["node_id"] == "A"


def test_failed_operations_do_not_emit_false_success_events() -> None:
    scheduler = _scheduler(
        _dag(("A", AgentRole.BACKEND)),
        workers=(
            _worker("worker-backend-1", AgentRole.BACKEND),
            _worker("worker-frontend-1", AgentRole.FRONTEND),
        ),
    )
    scheduler.schedule()

    with pytest.raises(WorkerRoleMismatchError):
        scheduler.claim(scheduler.registry.lease("worker-frontend-1"))
    assert AgentEventType.SCHEDULER_TASK_CLAIMED not in [
        event.event_type for event in scheduler.events
    ]

    claim = scheduler.claim(scheduler.registry.lease("worker-backend-1"))
    assert claim is not None

    with pytest.raises(StaleTaskStateError):
        scheduler.complete(claim)
    with pytest.raises(TaskOwnershipError):
        scheduler.start(claim.model_copy(update={"worker_id": "worker-frontend-1"}))

    event_types = [event.event_type for event in scheduler.events]
    assert AgentEventType.SCHEDULER_TASK_COMPLETED not in event_types
    assert AgentEventType.SCHEDULER_TASK_STARTED not in event_types


@pytest.mark.parametrize(
    "status",
    [
        TaskStatus.READY,
        TaskStatus.CLAIMED,
        TaskStatus.RUNNING,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.BLOCKED,
    ],
)
def test_scheduler_rejects_non_pending_dag_at_initialization(
    status: TaskStatus,
) -> None:
    dag = _dag("A")
    dag.replace_task_status("A", status)

    with pytest.raises(SchedulerInitializationError, match="fresh DAG"):
        _scheduler(dag)


def test_scheduler_rejects_unvalidated_cycle_at_initialization() -> None:
    dag = _dag("A", "B")
    dag.add_dependency("A", "B")
    dag.add_dependency("B", "A")
    scheduler = TaskScheduler.__new__(TaskScheduler)

    with pytest.raises(SchedulerInitializationError) as exc_info:
        TaskScheduler.__init__(scheduler, dag, _registry(_worker("worker-backend-1")))

    assert isinstance(exc_info.value.__cause__, CycleDetectedError)
    assert not hasattr(scheduler, "_records")
    assert not hasattr(scheduler, "_queue")
    assert not hasattr(scheduler, "_events")


def test_scheduler_initializes_and_schedules_valid_manual_dag() -> None:
    dag = _dag("A", "B")
    dag.add_dependency("A", "B")
    scheduler = _scheduler(dag)

    result = scheduler.schedule()

    assert result.scheduled == ("A",)
    assert scheduler.queue == ("A",)
    assert scheduler.runtime_records["A"].status is TaskStatus.READY
    assert scheduler.runtime_records["B"].status is TaskStatus.PENDING


def test_scheduler_uses_dag_topology_snapshot_after_initialization() -> None:
    dag = _dag("A")
    scheduler = _scheduler(dag)

    dag.add_task(TaskNode(node_id="B", assignment=_assignment("B")))
    dag.replace_task_status("A", TaskStatus.COMPLETED)

    result = scheduler.schedule()

    assert result.scheduled == ("A",)
    assert scheduler.runtime_records == {
        "A": TaskRuntimeRecord(node_id="A", status=TaskStatus.READY)
    }


def test_concurrent_claims_are_stable_over_repeated_runs() -> None:
    for _ in range(50):
        scheduler = _scheduler(
            _dag("A"),
            workers=(
                _worker("worker-backend-1"),
                _worker("worker-backend-2"),
            ),
        )
        scheduler.schedule()
        barrier = Barrier(2)
        claims: list[TaskClaim | None] = []
        errors: list[BaseException] = []

        def contender(
            worker_id: str,
            *,
            current_barrier: Barrier = barrier,
            current_claims: list[TaskClaim | None] = claims,
            current_errors: list[BaseException] = errors,
            current_scheduler: TaskScheduler = scheduler,
        ) -> None:
            try:
                current_barrier.wait()
                current_claims.append(current_scheduler.claim(current_scheduler.registry.lease(worker_id)))
            except (RuntimeError, SchedulerError, WorkerNotFoundError) as exc:
                current_errors.append(exc)

        threads = [
            Thread(target=contender, args=("worker-backend-1",)),
            Thread(target=contender, args=("worker-backend-2",)),
        ]
        for thread in threads:
            thread.start()
        _join_threads(threads)

        assert errors == []
        assert len([claim for claim in claims if claim is not None]) == 1


def test_public_api_exports_scheduler_objects() -> None:
    from codeteam.agent_team import (
        InvalidSchedulerTransitionError as ExportedInvalidTransition,
    )
    from codeteam.agent_team import (
        SchedulerInitializationError as ExportedSchedulerInitializationError,
    )
    from codeteam.agent_team import SchedulerResult as ExportedSchedulerResult
    from codeteam.agent_team import StaleTaskStateError as ExportedStaleState
    from codeteam.agent_team import TaskClaim as ExportedTaskClaim
    from codeteam.agent_team import TaskRuntimeRecord as ExportedTaskRuntimeRecord
    from codeteam.agent_team import TaskScheduler as ExportedTaskScheduler

    assert ExportedInvalidTransition is InvalidSchedulerTransitionError
    assert ExportedSchedulerInitializationError is SchedulerInitializationError
    assert ExportedSchedulerResult is SchedulerResult
    assert ExportedStaleState is StaleTaskStateError
    assert ExportedTaskClaim is TaskClaim
    assert ExportedTaskRuntimeRecord is TaskRuntimeRecord
    assert ExportedTaskScheduler is TaskScheduler
