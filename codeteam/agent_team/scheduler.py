from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from types import MappingProxyType
from typing import TypedDict

from pydantic import BaseModel, Field, field_validator

from codeteam.agent_team.contracts import (
    LifecyclePolicy,
    OwnedTaskToken,
    RecoveryOutcome,
    StaleWorkerGenerationError,
    TeamConsistencyError,
    TokenModel,
    WorkerLease,
    WorkerRuntimeRecord,
    WorkerTimeoutCandidate,
    is_expired,
)
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


class DurableSchedulerState(TypedDict):
    dag_nodes: tuple[TaskNode, ...]
    dependencies: dict[str, frozenset[str]]
    tasks: dict[str, TaskRuntimeRecord]
    ready_queue: tuple[str, ...]
    waiting_for_worker: frozenset[str]
    worker_ownership: dict[str, str | None]
    max_attempts: int


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


class StaleTaskClaimError(SchedulerError):
    """The task attempt or runtime epoch no longer matches."""


class WorkerUnavailableError(SchedulerError):
    """Raised when a worker exists but cannot claim a task now."""


class WorkerRoleMismatchError(SchedulerError):
    """Raised when queued tasks cannot be claimed by the worker role."""


class TaskRuntimeRecord(BaseModel):
    node_id: str
    status: TaskStatus = TaskStatus.PENDING
    owner_id: str | None = None
    owner_generation: int | None = Field(default=None, ge=1, strict=True)
    attempt: int = Field(default=0, ge=0)
    failure_reason: str | None = None
    claimed_at: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @field_validator("node_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("node_id must not be blank")
        return stripped


class TaskClaim(TokenModel):
    node_id: str = Field(min_length=1)
    worker_id: str = Field(min_length=1)
    attempt: int = Field(ge=1, strict=True)
    claimed_at: float = Field(ge=0, allow_inf_nan=False)
    runtime_id: str = Field(min_length=1)
    worker_generation: int = Field(ge=1, strict=True)


class WorkerRecoveryResult(TokenModel):
    lease: WorkerLease
    outcome: RecoveryOutcome
    task_record: TaskRuntimeRecord | None = None
    reason_code: str


class TeamSnapshot(TokenModel):
    tasks: dict[str, TaskRuntimeRecord]
    workers: dict[str, WorkerRuntimeRecord]
    queue: tuple[str, ...]
    ownership: dict[str, str | None]


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
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or max_attempts < 1
        ):
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
        self._coordinator = registry.coordinator
        self._lock = self._coordinator.lock
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
        self._topological_node_ids = tuple(
            node.node_id for node in dag.topological_sort()
        )
        self._records: dict[str, TaskRuntimeRecord] = {
            node_id: TaskRuntimeRecord(node_id=node_id) for node_id in self._nodes
        }
        self._worker_current_task: dict[str, str | None] = {}
        self._waiting_for_worker_node_ids: set[str] = set()
        self._events: list[AgentEvent] = []
        self._event_sink = event_sink
        with self._lock:
            if self._coordinator.scheduler is not None:
                raise SchedulerInitializationError("Registry already has a Scheduler")
            self._coordinator.scheduler = self

    @classmethod
    def from_durable_state(
        cls,
        dag: TaskDAG,
        registry: WorkerRegistry,
        *,
        tasks: dict[str, TaskRuntimeRecord],
        ready_queue: tuple[str, ...],
        waiting_for_worker: frozenset[str],
        worker_ownership: dict[str, str | None],
        max_attempts: int,
        event_sink: EventSink | None = None,
    ) -> TaskScheduler:
        """Hydrate Scheduler state through one validated package-owned boundary."""
        scheduler = cls(
            dag,
            registry,
            max_attempts=max_attempts,
            event_sink=event_sink,
        )
        node_ids = {node.node_id for node in dag.nodes}
        if set(tasks) != node_ids:
            raise SchedulerInitializationError("durable tasks do not match DAG nodes")
        if set(worker_ownership) != set(registry.runtime_records):
            raise SchedulerInitializationError(
                "durable ownership does not match Registry workers"
            )
        with scheduler._lock:
            scheduler._records = {
                node_id: TaskRuntimeRecord.model_validate(record.model_dump())
                for node_id, record in tasks.items()
            }
            scheduler._queue = deque(ready_queue)
            scheduler._queued_node_ids = set(ready_queue)
            scheduler._waiting_for_worker_node_ids = set(waiting_for_worker)
            scheduler._worker_current_task = dict(worker_ownership)
            if len(scheduler._queue) != len(scheduler._queued_node_ids):
                raise SchedulerInitializationError("durable ready queue has duplicates")
            for worker_id, node_id in scheduler._worker_current_task.items():
                if node_id is not None:
                    scheduler._owned_token_locked(worker_id)
        return scheduler

    @property
    def registry(self) -> WorkerRegistry:
        return self._registry

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    def export_durable_scheduler_state(self) -> DurableSchedulerState:
        """Return a same-lock snapshot including topology and queue membership."""
        with self._lock:
            return {
                "dag_nodes": tuple(
                    self._nodes[node_id].model_copy(deep=True)
                    for node_id in sorted(self._nodes)
                ),
                "dependencies": {
                    node_id: frozenset(self._dependencies[node_id])
                    for node_id in sorted(self._dependencies)
                },
                "tasks": {
                    node_id: record.model_copy(deep=True)
                    for node_id, record in sorted(self._records.items())
                },
                "ready_queue": tuple(self._queue),
                "waiting_for_worker": frozenset(self._waiting_for_worker_node_ids),
                "worker_ownership": {
                    worker_id: self._worker_current_task.get(worker_id)
                    for worker_id in self._registry.runtime_records
                },
                "max_attempts": self._max_attempts,
            }

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        # Registry rolls back its draft as well if any scheduler preparation fails.
        with self._registry._transaction():
            old = (
                self._records,
                self._queue,
                self._queued_node_ids,
                self._worker_current_task,
                self._waiting_for_worker_node_ids,
                self._events,
            )
            self._records = dict(self._records)
            self._queue = deque(self._queue)
            self._queued_node_ids = set(self._queued_node_ids)
            self._worker_current_task = dict(self._worker_current_task)
            self._waiting_for_worker_node_ids = set(self._waiting_for_worker_node_ids)
            self._events = list(self._events)
            try:
                yield
            except BaseException:
                (
                    self._records,
                    self._queue,
                    self._queued_node_ids,
                    self._worker_current_task,
                    self._waiting_for_worker_node_ids,
                    self._events,
                ) = old
                raise

    def snapshot(self) -> TeamSnapshot:
        with self._lock:
            return TeamSnapshot(
                tasks=self.runtime_records,
                workers=self._registry.runtime_records,
                queue=tuple(self._queue),
                ownership=dict(self._worker_current_task),
            )

    @contextmanager
    def _claimed_transaction(self, claim: TaskClaim) -> Iterator[None]:
        try:
            with self._transaction():
                self._require_claim_locked(claim)
                yield
        except (
            StaleTaskClaimError,
            StaleWorkerGenerationError,
            TaskOwnershipError,
        ) as exc:
            pending: list[AgentEvent] = []
            with self._transaction():
                self._record_event_locked(
                    pending,
                    AgentEventType.SCHEDULER_STALE_CLAIM_REJECTED,
                    "Rejected task claim.",
                    node_id=claim.node_id,
                    worker_id=claim.worker_id,
                    attempt=claim.attempt,
                    reason_code=type(exc).__name__,
                )
            self._deliver_events(pending)
            raise

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
        with self._transaction():
            result = self._schedule_locked(pending_delivery)
        self._deliver_events(pending_delivery)
        return result

    def claim(self, lease: WorkerLease) -> TaskClaim | None:
        pending_delivery: list[AgentEvent] = []
        with self._transaction():
            self._registry._require_lease_locked(lease)
            worker_id = lease.worker_id
            self._require_available_worker_locked(worker_id)
            checked_count = len(self._queue)
            saw_incompatible_ready_task = False

            for _ in range(checked_count):
                node_id = self._queue.popleft()
                self._queued_node_ids.discard(node_id)
                record = self._records[node_id]

                if record.status is not TaskStatus.READY:
                    continue

                if not self._worker_can_claim_locked(worker_id, node_id):
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
                    owner_generation=lease.generation,
                    attempt=record.attempt + 1,
                    failure_reason=None,
                    claimed_at=claimed_at,
                )
                self._registry._update_locked(worker_id, status=AgentStatus.BUSY)
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
                    runtime_id=lease.runtime_id,
                    worker_generation=lease.generation,
                )
                break
            else:
                if saw_incompatible_ready_task:
                    raise WorkerRoleMismatchError(worker_id)
                claim = None

        self._deliver_events(pending_delivery)
        return claim

    def start(self, claim: TaskClaim) -> TaskRuntimeRecord:
        pending_delivery: list[AgentEvent] = []
        with self._claimed_transaction(claim):
            node_id, worker_id = claim.node_id, claim.worker_id
            updated = self._transition_locked(
                node_id,
                TaskStatus.CLAIMED,
                TaskStatus.RUNNING,
            )
            self._registry._update_locked(worker_id)
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

    def complete(self, claim: TaskClaim) -> TaskRuntimeRecord:
        pending_delivery: list[AgentEvent] = []
        with self._claimed_transaction(claim):
            node_id, worker_id = claim.node_id, claim.worker_id
            updated = self._transition_locked(
                node_id,
                TaskStatus.RUNNING,
                TaskStatus.COMPLETED,
                owner_id=None,
                owner_generation=None,
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
        claim: TaskClaim,
        reason: str,
        *,
        retryable: bool = True,
    ) -> TaskRuntimeRecord:
        pending_delivery: list[AgentEvent] = []
        with self._claimed_transaction(claim):
            node_id, worker_id = claim.node_id, claim.worker_id
            failed = self._transition_locked(
                node_id,
                TaskStatus.RUNNING,
                TaskStatus.FAILED,
                owner_id=None,
                owner_generation=None,
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

    def _owned_token_locked(self, worker_id: str) -> OwnedTaskToken | None:
        node_id = self._worker_current_task.get(worker_id)
        if node_id is None:
            return None
        record = self._records[node_id]
        worker = self._registry._runtime_locked(worker_id)
        if (
            record.owner_id != worker_id
            or record.owner_generation != worker.generation
            or worker.status is not AgentStatus.BUSY
            or record.status not in {TaskStatus.CLAIMED, TaskStatus.RUNNING}
        ):
            raise TeamConsistencyError("ownership index and runtime records diverged")
        return OwnedTaskToken(
            node_id=node_id, attempt=record.attempt, worker_generation=worker.generation
        )

    def timeout_candidates(
        self, *, heartbeat_timeout_seconds: float
    ) -> tuple[WorkerTimeoutCandidate, ...]:
        policy = LifecyclePolicy(heartbeat_timeout_seconds=heartbeat_timeout_seconds)
        with self._lock:
            now = self._registry._checked_now_locked()
            candidates: list[WorkerTimeoutCandidate] = []
            for worker_id, record in sorted(self._registry._records.items()):
                if record.status not in {AgentStatus.READY, AgentStatus.BUSY}:
                    continue
                last_seen = record.last_heartbeat_monotonic
                if last_seen is None:
                    raise TeamConsistencyError("active worker has no heartbeat origin")
                if is_expired(last_seen, now, policy.heartbeat_timeout_seconds):
                    candidates.append(
                        WorkerTimeoutCandidate(
                            lease=self._registry._lease(record),
                            worker_revision=record.revision,
                            observed_status=record.status,
                            observed_at=now,
                            last_heartbeat_monotonic=last_seen,
                            active_task=self._owned_token_locked(worker_id),
                        )
                    )
            return tuple(candidates)

    def recover_worker_loss(
        self,
        candidate: WorkerTimeoutCandidate,
        *,
        heartbeat_timeout_seconds: float,
    ) -> WorkerRecoveryResult:
        policy = LifecyclePolicy(heartbeat_timeout_seconds=heartbeat_timeout_seconds)
        candidate = WorkerTimeoutCandidate.model_validate(candidate.model_dump())
        pending: list[AgentEvent] = []
        worker_pending: list[AgentEvent] = []
        with self._transaction():
            lease = candidate.lease
            worker = self._registry._runtime_locked(lease.worker_id)
            now = self._registry._checked_now_locked()
            if (
                lease.runtime_id != self._coordinator.runtime_id
                or lease.generation != worker.generation
                or worker.revision != candidate.worker_revision
                or worker.status != candidate.observed_status
                or worker.status not in {AgentStatus.READY, AgentStatus.BUSY}
                or worker.last_heartbeat_monotonic != candidate.last_heartbeat_monotonic
                or not is_expired(
                    candidate.last_heartbeat_monotonic,
                    now,
                    policy.heartbeat_timeout_seconds,
                )
                or self._owned_token_locked(lease.worker_id) != candidate.active_task
            ):
                return WorkerRecoveryResult(
                    lease=lease,
                    outcome=RecoveryOutcome.STALE_CANDIDATE,
                    reason_code="stale_candidate",
                )
            result = self._make_unavailable_locked(
                lease,
                AgentStatus.FAILED,
                "heartbeat_timeout",
                pending,
                worker_pending,
                elapsed_seconds=now - candidate.last_heartbeat_monotonic,
                timeout_seconds=policy.heartbeat_timeout_seconds,
            )
        self._deliver_events(pending)
        self._registry._deliver_events(worker_pending)
        return result

    def stop_worker(self, lease: WorkerLease) -> WorkerRecoveryResult:
        """Logical revocation, not process termination or whole-task cancellation."""
        pending: list[AgentEvent] = []
        worker_pending: list[AgentEvent] = []
        with self._transaction():
            worker = self._registry._require_lease_locked(lease)
            if worker.status is AgentStatus.STOPPED:
                return WorkerRecoveryResult(
                    lease=lease,
                    outcome=RecoveryOutcome.ALREADY_STOPPED,
                    reason_code="already_stopped",
                )
            result = self._make_unavailable_locked(
                lease,
                AgentStatus.STOPPED,
                "worker_stopped",
                pending,
                worker_pending,
            )
        self._deliver_events(pending)
        self._registry._deliver_events(worker_pending)
        return result

    def _make_unavailable_locked(
        self,
        lease: WorkerLease,
        target: AgentStatus,
        reason: str,
        pending: list[AgentEvent],
        worker_pending: list[AgentEvent],
        **metadata: object,
    ) -> WorkerRecoveryResult:
        token = self._owned_token_locked(lease.worker_id)
        previous = self._registry._runtime_locked(lease.worker_id)
        worker = self._registry._update_locked(
            lease.worker_id, status=target, restart_id=None
        )
        self._registry._record_event_locked(
            worker_pending,
            AgentEventType.WORKER_STOPPED
            if target is AgentStatus.STOPPED
            else AgentEventType.WORKER_FAILED,
            worker,
            from_status=previous.status.value,
            reason_code=reason,
            node_id=token.node_id if token else None,
            attempt=token.attempt if token else None,
            **metadata,
        )
        self._worker_current_task.pop(lease.worker_id, None)
        if token is None:
            return WorkerRecoveryResult(
                lease=lease, outcome=RecoveryOutcome.WORKER_ONLY, reason_code=reason
            )
        record = self._records[token.node_id]
        failed = self._transition_locked(
            token.node_id,
            record.status,
            TaskStatus.FAILED,
            owner_id=None,
            owner_generation=None,
            claimed_at=None,
            failure_reason=reason,
        )
        self._record_event_locked(
            pending,
            AgentEventType.SCHEDULER_TASK_FAILED,
            "Task ownership revoked.",
            node_id=token.node_id,
            worker_id=lease.worker_id,
            from_status=record.status,
            to_status=TaskStatus.FAILED,
            attempt=token.attempt,
            reason_code=reason,
        )
        outcome = RecoveryOutcome.TASK_FAILED
        if failed.attempt < self._max_attempts:
            failed = self._transition_locked(
                token.node_id, TaskStatus.FAILED, TaskStatus.READY
            )
            if token.node_id not in self._queued_node_ids:
                self._queue.append(token.node_id)
                self._queued_node_ids.add(token.node_id)
            self._record_event_locked(
                pending,
                AgentEventType.SCHEDULER_TASK_RETRIED,
                "Revoked task scheduled for retry.",
                node_id=token.node_id,
                worker_id=lease.worker_id,
                from_status=TaskStatus.FAILED,
                to_status=TaskStatus.READY,
                attempt=token.attempt,
                reason_code=reason,
            )
            outcome = RecoveryOutcome.TASK_REQUEUED
        else:
            self._schedule_locked(pending)
        return WorkerRecoveryResult(
            lease=lease,
            outcome=outcome,
            task_record=failed.model_copy(deep=True),
            reason_code=reason,
        )

    def _schedule_locked(self, pending_delivery: list[AgentEvent]) -> SchedulerResult:
        scheduled: list[str] = []
        blocked: list[str] = []
        already_ready: list[str] = []
        waiting_for_worker: list[str] = []
        terminal_blocked = self._terminal_blocked_nodes_locked()

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

            if node_id in terminal_blocked:
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

            if not self._registry.compatible_assignment(
                self._nodes[node_id].assignment
            ):
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
                        reason_code="no_compatible_worker",
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
        updated = TaskRuntimeRecord.model_validate(
            {**record.model_dump(), "status": target_status, **updates}
        )
        self._records[node_id] = updated
        return updated

    def _require_record_locked(self, node_id: str) -> None:
        if node_id not in self._records:
            raise UnknownTaskNodeError(node_id)

    def _require_claim_locked(self, claim: TaskClaim) -> None:
        if not isinstance(claim, TaskClaim):
            raise TypeError("an explicit TaskClaim is required")
        claim = TaskClaim.model_validate(claim.model_dump())
        self._require_record_locked(claim.node_id)
        record = self._records[claim.node_id]
        if claim.runtime_id != self._coordinator.runtime_id:
            raise StaleTaskClaimError("claim belongs to another runtime")
        worker = self._registry._runtime_locked(claim.worker_id)
        if worker.generation != claim.worker_generation:
            raise StaleWorkerGenerationError("worker was replaced")
        if record.owner_id != claim.worker_id:
            raise TaskOwnershipError(
                f"{claim.worker_id} does not own {claim.node_id}; owner is {record.owner_id}"
            )
        if (
            record.attempt != claim.attempt
            or record.owner_generation != claim.worker_generation
        ):
            raise StaleTaskClaimError("claim attempt or generation is stale")
        if worker.status is not AgentStatus.BUSY:
            raise WorkerUnavailableError(claim.worker_id)

    def _require_available_worker_locked(self, worker_id: str) -> WorkerAgent:
        worker = self._registry.get(worker_id)
        current_status = self._registry._runtime_locked(worker_id).status
        current_task = self._worker_current_task.get(worker_id)

        if current_status is not AgentStatus.READY or current_task is not None:
            raise WorkerUnavailableError(worker_id)
        return worker

    def _release_worker_locked(self, worker_id: str) -> None:
        if self._registry._runtime_locked(worker_id).status is not AgentStatus.BUSY:
            raise WorkerUnavailableError(worker_id)
        self._registry._update_locked(worker_id, status=AgentStatus.READY)
        self._worker_current_task[worker_id] = None

    def _role_for_node(self, node_id: str) -> AgentRole:
        self._require_record_locked(node_id)
        return self._nodes[node_id].assignment.role

    def _worker_can_claim_locked(self, worker_id: str, node_id: str) -> bool:
        assignment = self._nodes[node_id].assignment
        return any(
            worker.info.identity.agent_id == worker_id
            for worker in self._registry.compatible_assignment(assignment)
        )

    def _prerequisites_completed_locked(self, node_id: str) -> bool:
        return all(
            self._records[prerequisite_id].status is TaskStatus.COMPLETED
            for prerequisite_id in self._dependencies[node_id]
        )

    def _terminal_blocked_nodes_locked(self) -> set[str]:
        # Prerequisites precede descendants: one bounded O(V + E) pass computes
        # the closure. Apply it in the existing ID order to preserve scheduling.
        blocked: set[str] = set()
        for node_id in self._topological_node_ids:
            status = self._records[node_id].status
            if status in {TaskStatus.FAILED, TaskStatus.BLOCKED} or (
                status is TaskStatus.PENDING
                and any(parent in blocked for parent in self._dependencies[node_id])
            ):
                blocked.add(node_id)
        return blocked

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
        data: dict[str, object] = {
            "node_id": node_id,
            **self._coordinator.event_metadata_locked(),
        }
        if worker_id is not None:
            data["worker_id"] = worker_id
            data["generation"] = self._registry._runtime_locked(worker_id).generation
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
        with self._transaction():
            failure = make_event(
                AgentEventType.SCHEDULER_EVENT_DELIVERY_FAILED,
                "Scheduler event sink delivery failed.",
                data={
                    **self._coordinator.event_metadata_locked(),
                    "failed_event_type": event.event_type.value,
                    "error_type": type(error).__name__,
                    "source_transaction_id": event.data.get("transaction_id"),
                    "node_id": event.data.get("node_id"),
                    "worker_id": event.data.get("worker_id"),
                    "generation": event.data.get("generation"),
                },
            )
            self._events.append(failure)

    def _copy_event(self, event: AgentEvent) -> AgentEvent:
        return AgentEvent(
            event_type=event.event_type,
            message=event.message,
            step_index=event.step_index,
            data=dict(event.data),
            timestamp=event.timestamp,
        )
