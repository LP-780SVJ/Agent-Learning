from __future__ import annotations

from threading import Barrier, Thread

import pytest

from codeteam.agent_team.dag import TaskDAG, TaskNode, TaskStatus
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
from codeteam.events import AgentEventType


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
        attempt=1,
        claimed_at=1.25,
    )
    result = SchedulerResult(scheduled=("A",))

    assert TaskRuntimeRecord.model_validate_json(record.model_dump_json()) == record
    assert TaskClaim.model_validate_json(claim.model_dump_json()) == claim
    assert SchedulerResult.model_validate_json(result.model_dump_json()) == result


def test_transition_table_rejects_direct_pending_to_completed() -> None:
    assert TaskStatus.COMPLETED not in TASK_TRANSITIONS[TaskStatus.PENDING]
    assert TaskStatus.RUNNING not in TASK_TRANSITIONS[TaskStatus.COMPLETED]
    assert TaskStatus.CLAIMED in TASK_TRANSITIONS[TaskStatus.READY]


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

    claim = scheduler.claim("worker-backend-1")

    assert claim is not None
    assert claim.node_id == "A"
    record = scheduler.runtime_records["A"]
    assert record.status is TaskStatus.CLAIMED
    assert record.owner_id == "worker-backend-1"
    assert record.attempt == 1
    assert scheduler.queue == ()

    with pytest.raises(WorkerUnavailableError):
        scheduler.claim("worker-backend-1")


def test_empty_queue_claim_returns_none() -> None:
    scheduler = _scheduler(_dag("A"))

    assert scheduler.claim("worker-backend-1") is None


def test_unknown_worker_is_rejected() -> None:
    scheduler = _scheduler(_dag("A"))
    scheduler.schedule()

    with pytest.raises(WorkerNotFoundError, match="missing-worker"):
        scheduler.claim("missing-worker")


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
        scheduler.claim("worker-frontend-1")

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
        scheduler.claim("worker-backend-1")

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
            claims.append(scheduler.claim(worker_id))
        except (RuntimeError, SchedulerError, WorkerNotFoundError) as exc:
            errors.append(exc)

    threads = [
        Thread(target=contender, args=("worker-backend-1",)),
        Thread(target=contender, args=("worker-backend-2",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

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
            claims.append(scheduler.claim(worker.info.identity.agent_id))
        except (RuntimeError, SchedulerError, WorkerNotFoundError) as exc:
            errors.append(exc)

    threads = [Thread(target=contender, args=(worker,)) for worker in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

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
    claim = scheduler.claim("worker-backend-1")
    assert claim is not None
    scheduler.start("A", "worker-backend-1")

    with pytest.raises(TaskOwnershipError):
        scheduler.complete("A", "worker-backend-2")

    completed = scheduler.complete("A", "worker-backend-1")

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
    claim = scheduler.claim("worker-backend-1")
    assert claim is not None
    scheduler.start("A", "worker-backend-1")

    with pytest.raises(TaskOwnershipError):
        scheduler.fail("A", "worker-backend-2", "not mine")

    record = scheduler.runtime_records["A"]
    assert record.status is TaskStatus.RUNNING
    assert record.owner_id == "worker-backend-1"


def test_invalid_state_progression_is_rejected_without_half_write() -> None:
    scheduler = _scheduler(_dag("A"))
    scheduler.schedule()
    claim = scheduler.claim("worker-backend-1")
    assert claim is not None

    with pytest.raises(StaleTaskStateError):
        scheduler.complete("A", "worker-backend-1")

    record = scheduler.runtime_records["A"]
    assert record.status is TaskStatus.CLAIMED
    assert record.owner_id == "worker-backend-1"


def test_retry_under_limit_requeues_and_clears_owner() -> None:
    scheduler = _scheduler(_dag("A"), max_attempts=2)
    scheduler.schedule()
    claim = scheduler.claim("worker-backend-1")
    assert claim is not None
    scheduler.start("A", "worker-backend-1")

    retried = scheduler.fail("A", "worker-backend-1", "test failed")

    assert retried.status is TaskStatus.READY
    assert retried.owner_id is None
    assert retried.attempt == 1
    assert retried.failure_reason == "test failed"
    assert scheduler.queue == ("A",)


def test_retry_limit_keeps_terminal_failed() -> None:
    scheduler = _scheduler(_dag("A"), max_attempts=1)
    scheduler.schedule()
    claim = scheduler.claim("worker-backend-1")
    assert claim is not None
    scheduler.start("A", "worker-backend-1")

    failed = scheduler.fail("A", "worker-backend-1", "test failed")

    assert failed.status is TaskStatus.FAILED
    assert failed.owner_id is None
    assert failed.attempt == 1
    assert scheduler.queue == ()


def test_non_retryable_failure_blocks_dependent() -> None:
    dag = _dag("A", "B")
    dag.add_dependency("A", "B")
    scheduler = _scheduler(dag, max_attempts=3)
    scheduler.schedule()
    claim = scheduler.claim("worker-backend-1")
    assert claim is not None
    scheduler.start("A", "worker-backend-1")

    scheduler.fail("A", "worker-backend-1", "policy denied", retryable=False)

    assert scheduler.runtime_records["A"].status is TaskStatus.FAILED
    assert scheduler.runtime_records["B"].status is TaskStatus.BLOCKED
    assert scheduler.queue == ()


def test_missing_worker_role_blocks_ready_task_fail_closed() -> None:
    scheduler = _scheduler(
        _dag(("A", AgentRole.TEST)),
        workers=(_worker("worker-backend-1", AgentRole.BACKEND),),
    )

    result = scheduler.schedule()

    assert result.blocked == ("A",)
    record = scheduler.runtime_records["A"]
    assert record.status is TaskStatus.BLOCKED
    assert record.failure_reason == "blocked_by_missing_worker_role"
    assert scheduler.queue == ()


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
    claim = scheduler.claim("worker-backend-1")
    assert claim is not None
    scheduler.start("A", "worker-backend-1")
    scheduler.complete("A", "worker-backend-1")

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
        }


def test_event_sink_receives_scheduler_events() -> None:
    received = []
    scheduler = TaskScheduler(
        _dag("A"),
        _registry(_worker("worker-backend-1")),
        event_sink=received.append,
    )

    scheduler.schedule()

    assert len(received) == 1
    assert received[0].event_type is AgentEventType.SCHEDULER_TASK_SCHEDULED


def test_public_api_exports_scheduler_objects() -> None:
    from codeteam.agent_team import (
        InvalidSchedulerTransitionError as ExportedInvalidTransition,
    )
    from codeteam.agent_team import SchedulerResult as ExportedSchedulerResult
    from codeteam.agent_team import StaleTaskStateError as ExportedStaleState
    from codeteam.agent_team import TaskClaim as ExportedTaskClaim
    from codeteam.agent_team import TaskRuntimeRecord as ExportedTaskRuntimeRecord
    from codeteam.agent_team import TaskScheduler as ExportedTaskScheduler

    assert ExportedInvalidTransition is InvalidSchedulerTransitionError
    assert ExportedSchedulerResult is SchedulerResult
    assert ExportedStaleState is StaleTaskStateError
    assert ExportedTaskClaim is TaskClaim
    assert ExportedTaskRuntimeRecord is TaskRuntimeRecord
    assert ExportedTaskScheduler is TaskScheduler
