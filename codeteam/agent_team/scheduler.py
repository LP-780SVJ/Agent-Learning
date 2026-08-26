from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Mapping
from threading import Lock
from types import MappingProxyType

from pydantic import BaseModel, Field, field_validator

from codeteam.agent_team.dag import (
    DAGError,
    TaskDAG,
    TaskNode,
    TaskStatus,
    UnknownTaskNodeError,
)
from codeteam.agent_team.models import AgentRole, AgentStatus
from codeteam.agent_team.worker import WorkerAgent, WorkerRegistry
from codeteam.events import AgentEvent, AgentEventType, make_event

_TASK_TRANSITIONS: dict[TaskStatus, tuple[TaskStatus, ...]] = {
    TaskStatus.PENDING: (TaskStatus.READY, TaskStatus.BLOCKED),
    TaskStatus.READY: (TaskStatus.CLAIMED, TaskStatus.BLOCKED),
    TaskStatus.CLAIMED: (TaskStatus.RUNNING, TaskStatus.FAILED),
    TaskStatus.RUNNING: (TaskStatus.COMPLETED, TaskStatus.FAILED),
    TaskStatus.FAILED: (TaskStatus.READY,),
    TaskStatus.COMPLETED: (),
    TaskStatus.BLOCKED: (),
}
TASK_TRANSITIONS: Mapping[TaskStatus, tuple[TaskStatus, ...]] = MappingProxyType(
    _TASK_TRANSITIONS
)


class SchedulerError(Exception):
    """Base class for task scheduler errors."""


class SchedulerInitializationError(SchedulerError):
    """Raised when a DAG cannot initialize a fresh scheduler."""


class InvalidSchedulerTransitionError(SchedulerError):
    """Raised when a task transition is not allowed."""


class StaleTaskStateError(SchedulerError):
    """Raised when compare-and-set sees an unexpected status."""


class TaskOwnershipError(SchedulerError):
    """Raised when a non-owner tries to advance an owned task."""


class WorkerUnavailableError(SchedulerError):
    """Raised when a worker exists but cannot claim a task now."""


class WorkerRoleMismatchError(SchedulerError):
    """Raised when queued tasks cannot be claimed by the worker role."""


class TaskRuntimeRecord(BaseModel):
    node_id: str
    status: TaskStatus = TaskStatus.PENDING
    owner_id: str | None = None
    attempt: int = Field(default=0, ge=0)
    failure_reason: str | None = None
    claimed_at: float | None = None

    @field_validator("node_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("node_id must not be blank")
        return stripped


class TaskClaim(BaseModel):
    node_id: str
    worker_id: str
    attempt: int
    claimed_at: float


class SchedulerResult(BaseModel):
    scheduled: tuple[str, ...] = ()
    blocked: tuple[str, ...] = ()
    already_ready: tuple[str, ...] = ()
    waiting_for_worker: tuple[str, ...] = ()


EventSink = Callable[[AgentEvent], None]


class TaskScheduler:
    def __init__(
        self,
        dag: TaskDAG,
        registry: WorkerRegistry,
        *,
        max_attempts: int = 1,
        event_sink: EventSink | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

        try:
            dag.validate()
        except DAGError as exc:
            raise SchedulerInitializationError(
                "TaskScheduler requires a valid TaskDAG"
            ) from exc

        self._dag = dag
        self._registry = registry
        self._max_attempts = max_attempts
        self._lock = Lock()
        self._queue: deque[str] = deque()
        self._queued_node_ids: set[str] = set()
        self._nodes: dict[str, TaskNode] = {}
        for node in dag.nodes:
            if node.status is not TaskStatus.PENDING:
                raise SchedulerInitializationError(
                    "TaskScheduler requires a fresh DAG with all nodes PENDING; "
                    f"{node.node_id} is {node.status.value}"
                )
            self._nodes[node.node_id] = node.model_copy(deep=True)
        self._dependencies = dag.dependencies
        self._records: dict[str, TaskRuntimeRecord] = {
            node_id: TaskRuntimeRecord(node_id=node_id)
            for node_id in self._nodes
        }
        self._worker_runtime_status: dict[str, AgentStatus] = {}
        self._worker_current_task: dict[str, str | None] = {}
        self._waiting_for_worker_node_ids: set[str] = set()
        self._events: list[AgentEvent] = []
        self._event_sink = event_sink

    @property
    def runtime_records(self) -> dict[str, TaskRuntimeRecord]:
        with self._lock:
            return {
                node_id: record.model_copy(deep=True)
                for node_id, record in sorted(self._records.items())
            }

    @property
    def queue(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._queue)

    @property
    def events(self) -> tuple[AgentEvent, ...]:
        with self._lock:
            return tuple(self._copy_event(event) for event in self._events)

    def schedule(self) -> SchedulerResult:
        pending_delivery: list[AgentEvent] = []
        with self._lock:
            result = self._schedule_locked(pending_delivery)
        self._deliver_events(pending_delivery)
        return result

    def claim(self, worker_id: str) -> TaskClaim | None:
        pending_delivery: list[AgentEvent] = []
        with self._lock:
            worker = self._require_available_worker_locked(worker_id)
            checked_count = len(self._queue)
            saw_incompatible_ready_task = False

            for _ in range(checked_count):
                node_id = self._queue.popleft()
                self._queued_node_ids.discard(node_id)
                record = self._records[node_id]

                if record.status is not TaskStatus.READY:
                    continue

                if not worker.supports(self._role_for_node(node_id)):
                    self._queue.append(node_id)
                    self._queued_node_ids.add(node_id)
                    saw_incompatible_ready_task = True
                    continue

                claimed_at = time.time()
                updated = self._transition_locked(
                    node_id,
                    TaskStatus.READY,
                    TaskStatus.CLAIMED,
                    owner_id=worker_id,
                    attempt=record.attempt + 1,
                    failure_reason=None,
                    claimed_at=claimed_at,
                )
                self._worker_runtime_status[worker_id] = AgentStatus.BUSY
                self._worker_current_task[worker_id] = node_id
                self._record_event_locked(
                    pending_delivery,
                    AgentEventType.SCHEDULER_TASK_CLAIMED,
                    f"Task {node_id} claimed.",
                    node_id=node_id,
                    worker_id=worker_id,
                    from_status=TaskStatus.READY,
                    to_status=TaskStatus.CLAIMED,
                    attempt=updated.attempt,
                )
                claim = TaskClaim(
                    node_id=node_id,
                    worker_id=worker_id,
                    attempt=updated.attempt,
                    claimed_at=claimed_at,
                )
                break
            else:
                if saw_incompatible_ready_task:
                    raise WorkerRoleMismatchError(worker_id)
                claim = None

        self._deliver_events(pending_delivery)
        return claim

    def start(self, node_id: str, worker_id: str) -> TaskRuntimeRecord:
        pending_delivery: list[AgentEvent] = []
        with self._lock:
            self._require_owner_locked(node_id, worker_id)
            updated = self._transition_locked(
                node_id,
                TaskStatus.CLAIMED,
                TaskStatus.RUNNING,
            )
            self._record_event_locked(
                pending_delivery,
                AgentEventType.SCHEDULER_TASK_STARTED,
                f"Task {node_id} started.",
                node_id=node_id,
                worker_id=worker_id,
                from_status=TaskStatus.CLAIMED,
                to_status=TaskStatus.RUNNING,
                attempt=updated.attempt,
            )
            result = updated.model_copy(deep=True)
        self._deliver_events(pending_delivery)
        return result

    def complete(self, node_id: str, worker_id: str) -> TaskRuntimeRecord:
        pending_delivery: list[AgentEvent] = []
        with self._lock:
            self._require_owner_locked(node_id, worker_id)
            updated = self._transition_locked(
                node_id,
                TaskStatus.RUNNING,
                TaskStatus.COMPLETED,
                owner_id=None,
                failure_reason=None,
                claimed_at=None,
            )
            self._release_worker_locked(worker_id)
            self._record_event_locked(
                pending_delivery,
                AgentEventType.SCHEDULER_TASK_COMPLETED,
                f"Task {node_id} completed.",
                node_id=node_id,
                worker_id=worker_id,
                from_status=TaskStatus.RUNNING,
                to_status=TaskStatus.COMPLETED,
                attempt=updated.attempt,
            )
            self._schedule_locked(pending_delivery)
            result = updated.model_copy(deep=True)
        self._deliver_events(pending_delivery)
        return result

    def fail(
        self,
        node_id: str,
        worker_id: str,
        reason: str,
        *,
        retryable: bool = True,
    ) -> TaskRuntimeRecord:
        pending_delivery: list[AgentEvent] = []
        with self._lock:
            self._require_owner_locked(node_id, worker_id)
            failed = self._transition_locked(
                node_id,
                TaskStatus.RUNNING,
                TaskStatus.FAILED,
                owner_id=None,
                failure_reason=reason,
                claimed_at=None,
            )
            self._release_worker_locked(worker_id)
            self._record_event_locked(
                pending_delivery,
                AgentEventType.SCHEDULER_TASK_FAILED,
                f"Task {node_id} failed.",
                node_id=node_id,
                worker_id=worker_id,
                from_status=TaskStatus.RUNNING,
                to_status=TaskStatus.FAILED,
                attempt=failed.attempt,
                reason_code="failed",
            )

            if retryable and failed.attempt < self._max_attempts:
                retried = self._transition_locked(
                    node_id,
                    TaskStatus.FAILED,
                    TaskStatus.READY,
                    owner_id=None,
                    failure_reason=reason,
                    claimed_at=None,
                )
                if node_id not in self._queued_node_ids:
                    self._queue.append(node_id)
                    self._queued_node_ids.add(node_id)
                self._record_event_locked(
                    pending_delivery,
                    AgentEventType.SCHEDULER_TASK_RETRIED,
                    f"Task {node_id} scheduled for retry.",
                    node_id=node_id,
                    worker_id=worker_id,
                    from_status=TaskStatus.FAILED,
                    to_status=TaskStatus.READY,
                    attempt=retried.attempt,
                    reason_code="retryable_failure",
                )
                result = retried.model_copy(deep=True)
            else:
                self._schedule_locked(pending_delivery)
                result = failed.model_copy(deep=True)

        self._deliver_events(pending_delivery)
        return result

    def _schedule_locked(self, pending_delivery: list[AgentEvent]) -> SchedulerResult:
        scheduled: list[str] = []
        blocked: list[str] = []
        already_ready: list[str] = []
        waiting_for_worker: list[str] = []

        for node_id in sorted(self._records):
            record = self._records[node_id]

            if record.status is TaskStatus.READY:
                already_ready.append(node_id)
                if node_id not in self._queued_node_ids:
                    self._queue.append(node_id)
                    self._queued_node_ids.add(node_id)
                continue

            if record.status is not TaskStatus.PENDING:
                continue

            if self._has_terminal_blocking_prerequisite_locked(node_id):
                updated = self._transition_locked(
                    node_id,
                    TaskStatus.PENDING,
                    TaskStatus.BLOCKED,
                    failure_reason="blocked_by_failed_prerequisite",
                )
                blocked.append(node_id)
                self._waiting_for_worker_node_ids.discard(node_id)
                self._record_event_locked(
                    pending_delivery,
                    AgentEventType.SCHEDULER_TASK_BLOCKED,
                    f"Task {node_id} blocked.",
                    node_id=node_id,
                    from_status=TaskStatus.PENDING,
                    to_status=TaskStatus.BLOCKED,
                    attempt=updated.attempt,
                    reason_code="failed_prerequisite",
                )
                continue

            if not self._prerequisites_completed_locked(node_id):
                continue

            if not self._registry.compatible(self._role_for_node(node_id)):
                waiting_for_worker.append(node_id)
                if node_id not in self._waiting_for_worker_node_ids:
                    self._waiting_for_worker_node_ids.add(node_id)
                    self._record_event_locked(
                        pending_delivery,
                        AgentEventType.SCHEDULER_TASK_WAITING_FOR_WORKER,
                        f"Task {node_id} waiting for worker.",
                        node_id=node_id,
                        from_status=TaskStatus.PENDING,
                        to_status=TaskStatus.PENDING,
                        attempt=record.attempt,
                        reason_code="missing_worker_role",
                    )
                continue

            updated = self._transition_locked(
                node_id,
                TaskStatus.PENDING,
                TaskStatus.READY,
            )
            self._waiting_for_worker_node_ids.discard(node_id)
            if node_id not in self._queued_node_ids:
                self._queue.append(node_id)
                self._queued_node_ids.add(node_id)
            scheduled.append(node_id)
            self._record_event_locked(
                pending_delivery,
                AgentEventType.SCHEDULER_TASK_SCHEDULED,
                f"Task {node_id} scheduled.",
                node_id=node_id,
                from_status=TaskStatus.PENDING,
                to_status=TaskStatus.READY,
                attempt=updated.attempt,
            )

        return SchedulerResult(
            scheduled=tuple(scheduled),
            blocked=tuple(blocked),
            already_ready=tuple(already_ready),
            waiting_for_worker=tuple(waiting_for_worker),
        )

    def _transition_locked(
        self,
        node_id: str,
        expected_status: TaskStatus,
        target_status: TaskStatus,
        **updates: object,
    ) -> TaskRuntimeRecord:
        self._require_record_locked(node_id)
        if not isinstance(target_status, TaskStatus):
            raise InvalidSchedulerTransitionError(
                f"target status must be TaskStatus, got {type(target_status).__name__}"
            )
        record = self._records[node_id]
        if record.status is not expected_status:
            raise StaleTaskStateError(
                f"{node_id} expected {expected_status.value}, got {record.status.value}"
            )
        if target_status not in _TASK_TRANSITIONS[expected_status]:
            raise InvalidSchedulerTransitionError(
                f"cannot transition {node_id} from {expected_status.value} "
                f"to {target_status.value}"
            )
        updated = record.model_copy(
            update={"status": target_status, **updates},
            deep=True,
        )
        self._records[node_id] = updated
        return updated

    def _require_record_locked(self, node_id: str) -> None:
        if node_id not in self._records:
            raise UnknownTaskNodeError(node_id)

    def _require_owner_locked(self, node_id: str, worker_id: str) -> None:
        self._require_record_locked(node_id)
        record = self._records[node_id]
        if record.owner_id != worker_id:
            raise TaskOwnershipError(
                f"{worker_id} does not own {node_id}; owner is {record.owner_id}"
            )

    def _require_available_worker_locked(self, worker_id: str) -> WorkerAgent:
        worker = self._registry.get(worker_id)
        info = worker.info
        self._worker_runtime_status.setdefault(worker_id, info.status)
        self._worker_current_task.setdefault(worker_id, None)
        current_status = self._worker_runtime_status[worker_id]
        current_task = self._worker_current_task[worker_id]

        if current_status is not AgentStatus.READY or current_task is not None:
            raise WorkerUnavailableError(worker_id)
        return worker

    def _release_worker_locked(self, worker_id: str) -> None:
        self._worker_runtime_status[worker_id] = AgentStatus.READY
        self._worker_current_task[worker_id] = None

    def _role_for_node(self, node_id: str) -> AgentRole:
        self._require_record_locked(node_id)
        return self._nodes[node_id].assignment.role

    def _prerequisites_completed_locked(self, node_id: str) -> bool:
        return all(
            self._records[prerequisite_id].status is TaskStatus.COMPLETED
            for prerequisite_id in self._dependencies[node_id]
        )

    def _has_terminal_blocking_prerequisite_locked(self, node_id: str) -> bool:
        return any(
            self._records[prerequisite_id].status
            in {TaskStatus.FAILED, TaskStatus.BLOCKED}
            for prerequisite_id in self._dependencies[node_id]
        )

    def _record_event_locked(
        self,
        pending_delivery: list[AgentEvent],
        event_type: AgentEventType,
        message: str,
        *,
        node_id: str,
        worker_id: str | None = None,
        from_status: TaskStatus | None = None,
        to_status: TaskStatus | None = None,
        attempt: int | None = None,
        reason_code: str | None = None,
    ) -> None:
        data: dict[str, object] = {"node_id": node_id}
        if worker_id is not None:
            data["worker_id"] = worker_id
        if from_status is not None:
            data["from_status"] = from_status.value
        if to_status is not None:
            data["to_status"] = to_status.value
        if attempt is not None:
            data["attempt"] = attempt
        if reason_code is not None:
            data["reason_code"] = reason_code

        event = make_event(event_type, message, data=data)
        self._events.append(event)
        pending_delivery.append(self._copy_event(event))

    def _deliver_events(self, events: list[AgentEvent]) -> None:
        if self._event_sink is None:
            return
        for event in events:
            try:
                self._event_sink(self._copy_event(event))
            except Exception as exc:  # noqa: BLE001 - observer failure is isolated.
                self._record_delivery_failure(event, exc)

    def _record_delivery_failure(self, event: AgentEvent, error: Exception) -> None:
        failure = make_event(
            AgentEventType.SCHEDULER_EVENT_DELIVERY_FAILED,
            "Scheduler event sink delivery failed.",
            data={
                "failed_event_type": event.event_type.value,
                "error_type": type(error).__name__,
            },
        )
        with self._lock:
            self._events.append(failure)

    def _copy_event(self, event: AgentEvent) -> AgentEvent:
        return AgentEvent(
            event_type=event.event_type,
            message=event.message,
            step_index=event.step_index,
            data=dict(event.data),
            timestamp=event.timestamp,
        )
