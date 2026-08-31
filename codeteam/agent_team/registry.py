from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from copy import deepcopy
from typing import TYPE_CHECKING
from uuid import uuid4

from codeteam.agent_team.contracts import (
    Clock,
    InvalidClockError,
    LifecyclePolicy,
    RestartOutcome,
    RestartResult,
    RestartTicket,
    StaleWorkerGenerationError,
    SystemClock,
    WorkerLease,
    WorkerRuntimeRecord,
    WorkerStateError,
)
from codeteam.agent_team.coordination import TeamStateCoordinator
from codeteam.agent_team.models import AgentInfo, AgentRole, AgentStatus
from codeteam.events import AgentEvent, AgentEventType, make_event

if TYPE_CHECKING:
    from codeteam.agent_team.worker import WorkerAgent


class DuplicateWorkerError(ValueError):
    pass


class WorkerNotFoundError(LookupError):
    pass


class AgentRegistry:
    """Sole live Worker authority. Occupancy changes belong to Scheduler transactions."""

    def __init__(
        self,
        *,
        coordinator: TeamStateCoordinator | None = None,
        clock: Clock | None = None,
        event_sink: Callable[[AgentEvent], None] | None = None,
    ) -> None:
        self.coordinator = coordinator or TeamStateCoordinator()
        with self.coordinator.lock:
            if self.coordinator.registry is not None:
                raise WorkerStateError("coordinator already has a Registry")
            self.coordinator.registry = self
        self._clock = clock or SystemClock()
        self._last_clock = 0.0
        self._workers: dict[str, WorkerAgent] = {}
        self._infos: dict[str, AgentInfo] = {}
        self._records: dict[str, WorkerRuntimeRecord] = {}
        self._events: list[AgentEvent] = []
        self._event_sink = event_sink

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        # Draft references are visible only under the shared lock. Any preparation
        # failure restores *all* references before another reader can acquire it.
        with self.coordinator.lock:
            old = (
                self._workers,
                self._infos,
                self._records,
                self._events,
                self.coordinator.transaction_seq,
                self.coordinator.event_index,
            )
            self._workers = dict(self._workers)
            self._infos = dict(self._infos)
            self._records = dict(self._records)
            self._events = list(self._events)
            self.coordinator.transaction_seq += 1
            self.coordinator.event_index = 0
            try:
                yield
            except BaseException:
                (
                    self._workers,
                    self._infos,
                    self._records,
                    self._events,
                    self.coordinator.transaction_seq,
                    self.coordinator.event_index,
                ) = old
                raise

    def _checked_now_locked(self) -> float:
        now = self._clock.monotonic()
        if (
            isinstance(now, bool)
            or not isinstance(now, (int, float))
            or not math.isfinite(now)
            or now < self._last_clock
        ):
            raise InvalidClockError(
                "clock must be finite, non-negative and non-decreasing"
            )
        self._last_clock = now
        return now

    def register(self, worker: WorkerAgent) -> WorkerLease:
        # User-extensible object access stays outside core lock.
        info = AgentInfo.model_validate(worker.info.model_dump())
        worker_id = info.identity.agent_id
        if info.role is AgentRole.LEAD or info.status is AgentStatus.RESTARTING:
            raise WorkerStateError("invalid bootstrap role/status")
        with self._transaction():
            if worker_id in self._workers:
                raise DuplicateWorkerError(worker_id)
            now = self._checked_now_locked()
            record = WorkerRuntimeRecord(
                worker_id=worker_id,
                status=info.status,
                last_heartbeat_monotonic=now
                if info.status in {AgentStatus.READY, AgentStatus.BUSY}
                else None,
            )
            lease = self._lease(record)
            self._workers[worker_id] = worker
            self._infos[worker_id] = info.model_copy(deep=True)
            self._records[worker_id] = record
        return lease

    def get(self, worker_id: str) -> WorkerAgent:
        with self.coordinator.lock:
            self._runtime_locked(worker_id)
            return self._workers[worker_id]

    def compatible(self, role: AgentRole) -> tuple[WorkerAgent, ...]:
        with self.coordinator.lock:
            return tuple(
                self._workers[key]
                for key, info in self._infos.items()
                if info.role is role
            )

    def lease(self, worker_id: str) -> WorkerLease:
        """Trusted control-plane discovery; never infer a token for a delayed callback."""
        with self.coordinator.lock:
            return self._lease(self._runtime_locked(worker_id))

    def _lease(self, record: WorkerRuntimeRecord) -> WorkerLease:
        return WorkerLease(
            runtime_id=self.coordinator.runtime_id,
            worker_id=record.worker_id,
            generation=record.generation,
        )

    def runtime(self, worker_id: str) -> WorkerRuntimeRecord:
        with self.coordinator.lock:
            return self._runtime_locked(worker_id).model_copy(deep=True)

    @property
    def runtime_records(self) -> dict[str, WorkerRuntimeRecord]:
        with self.coordinator.lock:
            return {
                key: value.model_copy(deep=True)
                for key, value in sorted(self._records.items())
            }

    @property
    def events(self) -> tuple[AgentEvent, ...]:
        with self.coordinator.lock:
            return tuple(deepcopy(self._events))

    def _runtime_locked(self, worker_id: str) -> WorkerRuntimeRecord:
        try:
            return self._records[worker_id]
        except KeyError as exc:
            raise WorkerNotFoundError(worker_id) from exc

    def _require_lease_locked(self, lease: WorkerLease) -> WorkerRuntimeRecord:
        if not isinstance(lease, WorkerLease):
            raise TypeError("an explicit WorkerLease is required")
        lease = WorkerLease.model_validate(lease.model_dump())
        record = self._runtime_locked(lease.worker_id)
        if (
            lease.runtime_id != self.coordinator.runtime_id
            or lease.generation != record.generation
        ):
            raise StaleWorkerGenerationError(
                "worker lease is stale or belongs to another runtime"
            )
        return record

    def _update_locked(self, worker_id: str, **updates: object) -> WorkerRuntimeRecord:
        record = self._runtime_locked(worker_id)
        draft = WorkerRuntimeRecord.model_validate(
            {
                **record.model_dump(),
                **updates,
                "revision": record.revision + 1,
            }
        )
        self._records[worker_id] = draft
        return draft

    def activate(self, lease: WorkerLease) -> WorkerRuntimeRecord:
        with self._transaction():
            record = self._require_lease_locked(lease)
            if record.status is not AgentStatus.CREATED:
                raise WorkerStateError("only CREATED can activate")
            result = self._update_locked(
                lease.worker_id,
                status=AgentStatus.READY,
                last_heartbeat_monotonic=self._checked_now_locked(),
            )
        return result.model_copy(deep=True)

    def heartbeat(self, lease: WorkerLease) -> WorkerRuntimeRecord:
        pending: list[AgentEvent] = []
        with self._transaction():
            record = self._require_lease_locked(lease)
            if record.status not in {AgentStatus.READY, AgentStatus.BUSY}:
                raise WorkerStateError("heartbeat requires READY or BUSY")
            result = self._update_locked(
                lease.worker_id, last_heartbeat_monotonic=self._checked_now_locked()
            )
            self._record_event_locked(
                pending, AgentEventType.WORKER_HEARTBEAT_RECEIVED, result
            )
        self._deliver_events(pending)
        return result.model_copy(deep=True)

    def reserve_restart(
        self,
        lease: WorkerLease,
        *,
        policy: LifecyclePolicy,
    ) -> RestartTicket | RestartResult:
        pending: list[AgentEvent] = []
        with self._transaction():
            record = self._require_lease_locked(lease)
            now = self._checked_now_locked()
            outcome = None
            if record.status is not AgentStatus.FAILED:
                outcome = RestartOutcome.NOT_ELIGIBLE
            elif record.restart_attempts >= policy.max_restarts:
                outcome = RestartOutcome.EXHAUSTED
            elif now < record.next_restart_monotonic:
                outcome = RestartOutcome.COOLDOWN
            reservation: RestartTicket | RestartResult
            if outcome is not None:
                reservation = RestartResult(
                    outcome=outcome, lease=lease, reason_code=outcome.value
                )
                self._record_event_locked(
                    pending,
                    AgentEventType.WORKER_RESTART_REJECTED,
                    record,
                    reason_code=outcome.value,
                )
            else:
                updated = self._update_locked(
                    lease.worker_id,
                    status=AgentStatus.RESTARTING,
                    restart_id=uuid4().hex,
                    restart_attempts=record.restart_attempts + 1,
                    next_restart_monotonic=now + policy.restart_cooldown_seconds,
                )
                reservation = RestartTicket(
                    lease=lease,
                    restart_id=updated.restart_id or "",
                    expected_revision=updated.revision,
                    restart_attempt=updated.restart_attempts,
                    info=self._infos[lease.worker_id].model_copy(deep=True),
                )
                self._record_event_locked(
                    pending,
                    AgentEventType.WORKER_RESTARTING,
                    updated,
                    restart_id=reservation.restart_id,
                )
        try:
            self._deliver_events(pending)
        except (KeyboardInterrupt, SystemExit) as exc:
            # The reservation is committed, but the caller has not received its
            # ticket yet. Only this exact ticket may authorize cleanup.
            if isinstance(reservation, RestartTicket):
                self._interrupt_restart(reservation, exc)
            raise
        return reservation

    def _ticket_matches_locked(self, ticket: RestartTicket) -> bool:
        record = self._runtime_locked(ticket.lease.worker_id)
        return (
            ticket.lease.runtime_id == self.coordinator.runtime_id
            and ticket.lease.generation == record.generation
            and record.status is AgentStatus.RESTARTING
            and ticket.expected_revision == record.revision
            and ticket.restart_id == record.restart_id
        )

    def finish_restart_failure(
        self,
        ticket: RestartTicket,
        *,
        error_type: str,
    ) -> RestartResult:
        return self._finish_restart(ticket, None, None, error_type)

    def _interrupt_restart(
        self, ticket: RestartTicket, interrupt: BaseException
    ) -> None:
        """Clean a matching reservation without replacing the original interrupt."""
        self._finish_restart(
            ticket, None, None, type(interrupt).__name__, interrupted_by=interrupt
        )

    def publish_restart(
        self,
        ticket: RestartTicket,
        worker: WorkerAgent,
        info: AgentInfo,
    ) -> RestartResult:
        return self._finish_restart(ticket, worker, info, None)

    def _finish_restart(
        self,
        ticket: RestartTicket,
        worker: WorkerAgent | None,
        info: AgentInfo | None,
        error_type: str | None,
        *,
        interrupted_by: BaseException | None = None,
    ) -> RestartResult:
        pending: list[AgentEvent] = []
        ticket = RestartTicket.model_validate(ticket.model_dump())
        if info is not None:
            info = AgentInfo.model_validate(info.model_dump())
        with self._transaction():
            worker_id = ticket.lease.worker_id
            record = self._runtime_locked(worker_id)
            if not self._ticket_matches_locked(ticket):
                outcome = RestartOutcome.STALE_TICKET
                event_type = AgentEventType.WORKER_RESTART_REJECTED
            else:
                expected = self._infos[worker_id]
                valid = (
                    worker is not None
                    and worker is not self._workers[worker_id]
                    and info is not None
                    and info.identity == expected.identity
                    and info.role is expected.role
                    and info.capabilities == expected.capabilities
                )
                if not valid or error_type is not None:
                    record = self._update_locked(
                        worker_id, status=AgentStatus.FAILED, restart_id=None
                    )
                    outcome = RestartOutcome.FACTORY_FAILED
                    event_type = AgentEventType.WORKER_RESTART_FAILED
                else:
                    record = self._update_locked(
                        worker_id,
                        status=AgentStatus.READY,
                        generation=record.generation + 1,
                        restart_id=None,
                        last_heartbeat_monotonic=self._checked_now_locked(),
                    )
                    assert worker is not None
                    self._workers[worker_id] = worker
                    outcome = RestartOutcome.RESTARTED
                    event_type = AgentEventType.WORKER_RESTARTED
            reason_code = (
                "restart_interrupted"
                if interrupted_by is not None
                and outcome is RestartOutcome.FACTORY_FAILED
                else outcome.value
            )
            result = RestartResult(
                outcome=outcome, lease=self._lease(record), reason_code=reason_code
            )
            self._record_event_locked(
                pending,
                event_type,
                record,
                reason_code=reason_code,
                error_type=error_type,
                restart_id=ticket.restart_id,
            )
        if interrupted_by is None:
            self._deliver_events(pending)
        else:
            self._deliver_interruption_events(pending, interrupted_by)
        return result

    def _deliver_interruption_events(
        self, events: list[AgentEvent], interrupt: BaseException
    ) -> None:
        # Cleanup has committed before calling observers. This narrow exception
        # boundary preserves an interrupt already being propagated, not normal work.
        if self._event_sink is None:
            return
        for event in events:
            try:
                self._event_sink(deepcopy(event))
            except BaseException as secondary:  # noqa: BLE001 - retain the original interrupt.
                interrupt.add_note(
                    f"Restart cleanup observer failed: {type(secondary).__name__}"
                )
                try:
                    self._record_delivery_failure(event, secondary)
                except BaseException as audit_error:  # noqa: BLE001 - cleanup state is already committed.
                    interrupt.add_note(
                        f"Cleanup delivery audit failed: {type(audit_error).__name__}"
                    )

    def _record_event_locked(
        self,
        pending: list[AgentEvent],
        event_type: AgentEventType,
        record: WorkerRuntimeRecord,
        **metadata: object,
    ) -> None:
        data = {
            **self.coordinator.event_metadata_locked(),
            "worker_id": record.worker_id,
            "generation": record.generation,
            "status": record.status.value,
            "revision": record.revision,
            "restart_attempts": record.restart_attempts,
            **metadata,
        }
        event = make_event(event_type, event_type.value, data=data)
        self._events.append(event)
        pending.append(deepcopy(event))

    def _deliver_events(self, events: list[AgentEvent]) -> None:
        if self._event_sink is None:
            return
        for event in events:
            try:
                self._event_sink(deepcopy(event))
            except Exception as exc:  # noqa: BLE001 - observers cannot undo committed state.
                self._record_delivery_failure(event, exc)

    def _record_delivery_failure(self, event: AgentEvent, error: BaseException) -> None:
        with self._transaction():
            failure = make_event(
                AgentEventType.WORKER_EVENT_DELIVERY_FAILED,
                "Worker observer failed.",
                data={
                    **self.coordinator.event_metadata_locked(),
                    "failed_event_type": event.event_type.value,
                    "error_type": type(error).__name__,
                    "source_transaction_id": event.data.get("transaction_id"),
                    "worker_id": event.data.get("worker_id"),
                    "generation": event.data.get("generation"),
                },
            )
            self._events.append(failure)
