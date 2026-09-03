"""Durable Team Runtime composition and persistence gateway."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import TypeVar

from codeteam.agent_team.contracts import (
    Clock,
    LifecyclePolicy,
    RestartResult,
    WorkerLease,
    WorkerRuntimeRecord,
    WorkerTimeoutCandidate,
)
from codeteam.agent_team.coordination import TeamStateCoordinator
from codeteam.agent_team.dag import TaskDAG
from codeteam.agent_team.lifecycle import AgentLifecycleManager, SweepResult
from codeteam.agent_team.mailbox import (
    AgentMailbox,
    AgentMessage,
    DurableMailboxState,
)
from codeteam.agent_team.models import (
    AgentIdentity,
    AgentInfo,
    AgentRole,
    WorkerAssignment,
)
from codeteam.agent_team.persistence_errors import (
    StaleMessageClaimError,
    TeamRuntimePoisonedError,
)
from codeteam.agent_team.persistence_models import (
    DurableEventDraft,
    MessageClaim,
    TeamStateSnapshot,
)
from codeteam.agent_team.registry import AgentRegistry
from codeteam.agent_team.scheduler import (
    SchedulerResult,
    TaskClaim,
    TaskRuntimeRecord,
    TaskScheduler,
    WorkerRecoveryResult,
)
from codeteam.agent_team.team_store import SQLiteTeamStateStore
from codeteam.agent_team.worker import WorkerAgent
from codeteam.events import AgentEvent
from codeteam.redaction import redact_sensitive_data, redact_sensitive_text

T = TypeVar("T")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def capture_team_snapshot(
    *,
    session_id: str,
    registry: AgentRegistry,
    scheduler: TaskScheduler,
    mailbox: AgentMailbox,
    policy: LifecyclePolicy,
    revision: int = 1,
    last_event_seq: int = 0,
    now_utc: datetime | None = None,
) -> TeamStateSnapshot:
    """Capture Registry/Scheduler and Mailbox under a fixed lock order."""
    wall_now = now_utc or _utc_now()
    with registry.coordinator.lock:
        scheduler_state = scheduler.export_durable_scheduler_state()
        workers = registry.export_durable_workers(now_utc=wall_now)
        mailbox_state = mailbox.export_durable_mailbox_state()
    return TeamStateSnapshot(
        session_id=session_id,
        revision=revision,
        previous_runtime_id=registry.coordinator.runtime_id,
        lifecycle_policy=policy,
        last_event_seq=last_event_seq,
        updated_at=wall_now,
        workers=workers,
        **scheduler_state,
        **mailbox_state,
    )


@dataclass(frozen=True)
class TeamCoordinatorView:
    """Public identity of a runtime epoch without exposing the shared lock."""

    runtime_id: str


class DurableRegistryFacade:
    def __init__(self, runtime: DurableTeamRuntime) -> None:
        self._runtime = runtime

    def compatible(self, role: AgentRole) -> tuple[WorkerAgent, ...]:
        return self._runtime._registry.compatible(role)

    def compatible_assignment(
        self, assignment: WorkerAssignment
    ) -> tuple[WorkerAgent, ...]:
        return self._runtime._registry.compatible_assignment(assignment)

    def lease(self, worker_id: str) -> WorkerLease:
        return self._runtime._registry.lease(worker_id)

    def runtime(self, worker_id: str) -> WorkerRuntimeRecord:
        return self._runtime._registry.runtime(worker_id)

    @property
    def runtime_records(self) -> dict[str, WorkerRuntimeRecord]:
        return self._runtime._registry.runtime_records

    @property
    def events(self) -> tuple[AgentEvent, ...]:
        return self._runtime._registry.events

    def heartbeat(self, lease: WorkerLease) -> WorkerRuntimeRecord:
        return self._runtime.heartbeat(lease)


class DurableSchedulerFacade:
    def __init__(self, runtime: DurableTeamRuntime) -> None:
        self._runtime = runtime

    @property
    def registry(self) -> DurableRegistryFacade:
        return self._runtime.registry

    @property
    def max_attempts(self) -> int:
        return self._runtime._scheduler.max_attempts

    @property
    def runtime_records(self) -> dict[str, TaskRuntimeRecord]:
        return self._runtime._scheduler.runtime_records

    @property
    def queue(self) -> tuple[str, ...]:
        return self._runtime._scheduler.queue

    @property
    def events(self) -> tuple[AgentEvent, ...]:
        return self._runtime._scheduler.events

    def schedule(self) -> SchedulerResult:
        return self._runtime.schedule()

    def claim(self, lease: WorkerLease) -> TaskClaim | None:
        return self._runtime.claim(lease)

    def start(self, claim: TaskClaim) -> TaskRuntimeRecord:
        return self._runtime.start(claim)

    def complete(self, claim: TaskClaim) -> TaskRuntimeRecord:
        return self._runtime.complete(claim)

    def fail(
        self, claim: TaskClaim, reason: str, *, retryable: bool = True
    ) -> TaskRuntimeRecord:
        return self._runtime.fail(claim, reason, retryable=retryable)

    def stop_worker(self, lease: WorkerLease) -> WorkerRecoveryResult:
        return self._runtime.stop_worker(lease)


class DurableMailboxFacade:
    def __init__(self, runtime: DurableTeamRuntime) -> None:
        self._runtime = runtime

    @property
    def events(self) -> tuple[AgentEvent, ...]:
        return self._runtime._mailbox.events

    @property
    def registered_agents(self) -> tuple[AgentIdentity, ...]:
        return self._runtime._mailbox.registered_agents

    def queue_size(self, agent_id: str) -> int:
        return self._runtime._mailbox.queue_size(agent_id)

    def export_durable_mailbox_state(self) -> DurableMailboxState:
        return self._runtime._mailbox.export_durable_mailbox_state()

    def send(self, message: AgentMessage) -> AgentMessage:
        return self._runtime.send_message(message)


class DurableLifecycleFacade:
    def __init__(self, runtime: DurableTeamRuntime) -> None:
        self._runtime = runtime

    @property
    def registry(self) -> DurableRegistryFacade:
        return self._runtime.registry

    @property
    def scheduler(self) -> DurableSchedulerFacade:
        return self._runtime.scheduler

    @property
    def policy(self) -> LifecyclePolicy:
        return self._runtime._lifecycle.policy.model_copy(deep=True)

    def heartbeat(self, lease: WorkerLease) -> WorkerRuntimeRecord:
        return self._runtime.heartbeat(lease)

    def detect_timeouts(self) -> tuple[WorkerTimeoutCandidate, ...]:
        return self._runtime._lifecycle.detect_timeouts()

    def restart_worker(self, lease: WorkerLease) -> RestartResult:
        return self._runtime.restart_worker(lease)

    def stop_worker(self, lease: WorkerLease) -> WorkerRecoveryResult:
        return self._runtime.stop_worker(lease)

    def sweep(self) -> SweepResult:
        return self._runtime.sweep()


class DurableTeamRuntime:
    """The only supported mutation gateway for a persisted Team Runtime."""

    def __init__(
        self,
        *,
        coordinator: TeamStateCoordinator,
        registry: AgentRegistry,
        scheduler: TaskScheduler,
        mailbox: AgentMailbox,
        lifecycle: AgentLifecycleManager,
        store: SQLiteTeamStateStore,
        snapshot: TeamStateSnapshot,
    ) -> None:
        self._coordinator = coordinator
        self._registry = registry
        self._scheduler = scheduler
        self._mailbox = mailbox
        self._lifecycle = lifecycle
        self._store = store
        self.coordinator = TeamCoordinatorView(runtime_id=coordinator.runtime_id)
        self.registry = DurableRegistryFacade(self)
        self.scheduler = DurableSchedulerFacade(self)
        self.mailbox = DurableMailboxFacade(self)
        self.lifecycle = DurableLifecycleFacade(self)
        self._snapshot = snapshot.model_copy(deep=True)
        self._durability_gate = Lock()
        self._poisoned = False
        self._event_cursors = self._current_event_lengths()

    @property
    def snapshot(self) -> TeamStateSnapshot:
        return self._snapshot.model_copy(deep=True)

    @property
    def poisoned(self) -> bool:
        return self._poisoned

    def schedule(self) -> SchedulerResult:
        return self._mutate(self._scheduler.schedule)

    def claim(self, lease: WorkerLease) -> TaskClaim | None:
        return self._mutate(lambda: self._scheduler.claim(lease))

    def start(self, claim: TaskClaim) -> TaskRuntimeRecord:
        return self._mutate(lambda: self._scheduler.start(claim))

    def complete(self, claim: TaskClaim) -> TaskRuntimeRecord:
        return self._mutate(lambda: self._scheduler.complete(claim))

    def fail(
        self, claim: TaskClaim, reason: str, *, retryable: bool = True
    ) -> TaskRuntimeRecord:
        safe_reason = redact_sensitive_text(reason)
        return self._mutate(
            lambda: self._scheduler.fail(claim, safe_reason, retryable=retryable)
        )

    def heartbeat(self, lease: WorkerLease) -> WorkerRuntimeRecord:
        return self._mutate(lambda: self._lifecycle.heartbeat(lease))

    def stop_worker(self, lease: WorkerLease) -> WorkerRecoveryResult:
        return self._mutate(lambda: self._lifecycle.stop_worker(lease))

    def restart_worker(self, lease: WorkerLease) -> RestartResult:
        return self._mutate(lambda: self._lifecycle.restart_worker(lease))

    def sweep(self) -> SweepResult:
        return self._mutate(self._lifecycle.sweep)

    def send_message(self, message: AgentMessage) -> AgentMessage:
        safe_message = AgentMessage.model_validate(
            redact_sensitive_data(message.model_dump(mode="python"))
        )
        return self._mutate(lambda: self._mailbox.send(safe_message))

    def claim_message(self, recipient_id: str) -> MessageClaim | None:
        with self._durability_gate:
            self._require_healthy()
            try:
                committed, claim = self._store.claim_message(
                    self._snapshot.session_id,
                    recipient_id=recipient_id,
                    runtime_id=self._coordinator.runtime_id,
                    expected_revision=self._snapshot.revision,
                )
                self._replace_mailbox_from_snapshot(committed)
            except BaseException:
                self._poisoned = True
                raise
            self._snapshot = committed
            return claim

    def ack_message(self, claim: MessageClaim) -> TeamStateSnapshot:
        with self._durability_gate:
            self._require_healthy()
            if claim.runtime_id != self._coordinator.runtime_id:
                raise TeamRuntimePoisonedError("message claim belongs to an old runtime")
            try:
                committed = self._store.ack_message(
                    self._snapshot.session_id,
                    claim,
                    expected_revision=self._snapshot.revision,
                )
                self._replace_mailbox_from_snapshot(committed)
            except StaleMessageClaimError:
                raise
            except BaseException:
                self._poisoned = True
                raise
            self._snapshot = committed
            return committed.model_copy(deep=True)

    def release_message(self, claim: MessageClaim) -> TeamStateSnapshot:
        """Return a matching in-flight message to the durable pending queue."""
        with self._durability_gate:
            self._require_healthy()
            if claim.runtime_id != self._coordinator.runtime_id:
                raise StaleMessageClaimError(claim.claim_id)
            try:
                committed = self._store.release_message(
                    self._snapshot.session_id,
                    claim,
                    expected_revision=self._snapshot.revision,
                )
                self._replace_mailbox_from_snapshot(committed)
            except StaleMessageClaimError:
                raise
            except BaseException:
                self._poisoned = True
                raise
            self._snapshot = committed
            return committed.model_copy(deep=True)

    def persist(self, *, event_type: str, payload: dict[str, object]) -> None:
        safe_payload = redact_sensitive_data(payload)
        self._mutate(
            lambda: None,
            extra_events=(
                DurableEventDraft(event_type=event_type, payload=safe_payload),
            ),
        )

    def _mutate(
        self,
        operation: Callable[[], T],
        *,
        extra_events: tuple[DurableEventDraft, ...] = (),
    ) -> T:
        with self._durability_gate:
            self._require_healthy()
            result = operation()
            try:
                events, next_cursors = self._new_event_drafts()
                draft = capture_team_snapshot(
                    session_id=self._snapshot.session_id,
                    registry=self._registry,
                    scheduler=self._scheduler,
                    mailbox=self._mailbox,
                    policy=self._lifecycle.policy,
                    revision=self._snapshot.revision,
                    last_event_seq=self._snapshot.last_event_seq,
                )
                all_events = (*events, *extra_events)
                if not all_events and self._same_business_state(
                    draft, self._snapshot
                ):
                    self._event_cursors = next_cursors
                    return result
                committed = self._store.commit(
                    draft,
                    expected_revision=self._snapshot.revision,
                    events=(*events, *extra_events),
                )
            except BaseException:
                # A live mutation may already exist. Never continue from unproven state.
                self._poisoned = True
                raise
            self._snapshot = committed
            self._event_cursors = next_cursors
            return result

    def _new_event_drafts(
        self,
    ) -> tuple[tuple[DurableEventDraft, ...], tuple[int, int, int]]:
        event_groups = (
            self._registry.events,
            self._scheduler.events,
            self._mailbox.events,
        )
        events: list[DurableEventDraft] = []
        for group, cursor in zip(event_groups, self._event_cursors, strict=True):
            for event in group[cursor:]:
                events.append(self._draft_from_agent_event(event))
        next_cursors = (
            len(event_groups[0]),
            len(event_groups[1]),
            len(event_groups[2]),
        )
        return tuple(events), next_cursors

    def _draft_from_agent_event(self, event: AgentEvent) -> DurableEventDraft:
        # Round-trip rejects observer payloads that are not durable JSON facts.
        payload = redact_sensitive_data(json.loads(json.dumps(event.data)))
        return DurableEventDraft(event_type=event.event_type.value, payload=payload)

    def _current_event_lengths(self) -> tuple[int, int, int]:
        return (
            len(self._registry.events),
            len(self._scheduler.events),
            len(self._mailbox.events),
        )

    def _replace_mailbox_from_snapshot(self, snapshot: TeamStateSnapshot) -> None:
        self._mailbox.restore_durable_state(
            agents=snapshot.mailbox_agents,
            messages=snapshot.messages,
            seen_message_ids=snapshot.seen_message_ids,
        )

    def _same_business_state(
        self,
        left: TeamStateSnapshot,
        right: TeamStateSnapshot,
    ) -> bool:
        excluded = {"revision", "last_event_seq", "updated_at"}
        left_data = left.model_dump(exclude=excluded)
        right_data = right.model_dump(exclude=excluded)
        # This UTC projection is derived from a monotonic deadline at capture
        # time. Advancing wall/monotonic clocks alone is not a business mutation.
        for data in (left_data, right_data):
            workers = data["workers"]
            for worker in workers.values():
                worker.pop("restart_not_before_utc", None)
        return left_data == right_data

    def _require_healthy(self) -> None:
        if self._poisoned:
            raise TeamRuntimePoisonedError(
                "Team Runtime is not proven consistent with durable state"
            )


class TeamRuntimeFactory:
    def __init__(
        self,
        *,
        worker_factory: Callable[[AgentInfo], WorkerAgent] = WorkerAgent,
        clock: Clock | None = None,
        now_utc: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._worker_factory = worker_factory
        self._clock = clock
        self._now_utc = now_utc

    def hydrate(
        self,
        *,
        snapshot: TeamStateSnapshot,
        store: SQLiteTeamStateStore,
        coordinator: TeamStateCoordinator | None = None,
    ) -> DurableTeamRuntime:
        snapshot = TeamStateSnapshot.model_validate(snapshot.model_dump())
        runtime_coordinator = coordinator or TeamStateCoordinator()
        if snapshot.previous_runtime_id != runtime_coordinator.runtime_id:
            raise ValueError("snapshot was not prepared for this runtime_id")
        dag = TaskDAG.from_durable_definition(
            snapshot.dag_nodes,
            snapshot.dependencies,
        )
        registry = AgentRegistry.from_durable_state(
            snapshot.workers,
            coordinator=runtime_coordinator,
            clock=self._clock,
            worker_factory=self._worker_factory,
            now_utc=self._now_utc(),
        )
        scheduler = TaskScheduler.from_durable_state(
            dag,
            registry,
            tasks=snapshot.tasks,
            ready_queue=snapshot.ready_queue,
            waiting_for_worker=snapshot.waiting_for_worker,
            worker_ownership=snapshot.worker_ownership,
            max_attempts=snapshot.max_attempts,
        )
        mailbox = AgentMailbox.from_durable_state(
            agents=snapshot.mailbox_agents,
            messages=snapshot.messages,
            seen_message_ids=snapshot.seen_message_ids,
            capacity_per_inbox=snapshot.mailbox_capacity,
        )
        lifecycle = AgentLifecycleManager(
            registry,
            scheduler,
            policy=snapshot.lifecycle_policy,
            worker_factory=self._worker_factory,
        )
        return DurableTeamRuntime(
            coordinator=runtime_coordinator,
            registry=registry,
            scheduler=scheduler,
            mailbox=mailbox,
            lifecycle=lifecycle,
            store=store,
            snapshot=snapshot,
        )
