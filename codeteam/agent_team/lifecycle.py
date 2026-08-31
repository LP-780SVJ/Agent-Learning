from __future__ import annotations

from collections.abc import Callable

from codeteam.agent_team.contracts import (
    LifecyclePolicy,
    RestartOutcome,
    RestartResult,
    StaleWorkerGenerationError,
    TokenModel,
    WorkerLease,
    WorkerRuntimeRecord,
    WorkerTimeoutCandidate,
)
from codeteam.agent_team.models import AgentInfo, AgentStatus
from codeteam.agent_team.registry import AgentRegistry
from codeteam.agent_team.scheduler import TaskScheduler, WorkerRecoveryResult
from codeteam.agent_team.worker import WorkerAgent

WorkerFactory = Callable[[AgentInfo], WorkerAgent]


class SweepResult(TokenModel):
    recoveries: tuple[WorkerRecoveryResult, ...]
    restarts: tuple[RestartResult, ...]


class AgentLifecycleManager:
    """In-process liveness coordination, never task selection or execution."""

    def __init__(
        self,
        registry: AgentRegistry,
        scheduler: TaskScheduler,
        *,
        policy: LifecyclePolicy | None = None,
        worker_factory: WorkerFactory = WorkerAgent,
    ) -> None:
        if scheduler.registry is not registry:
            raise ValueError("Lifecycle and Scheduler must share the same Registry")
        self.registry = registry
        self.scheduler = scheduler
        self.policy = policy or LifecyclePolicy()
        self._worker_factory = worker_factory

    def heartbeat(self, lease: WorkerLease) -> WorkerRuntimeRecord:
        return self.registry.heartbeat(lease)

    def detect_timeouts(self) -> tuple[WorkerTimeoutCandidate, ...]:
        return self.scheduler.timeout_candidates(
            heartbeat_timeout_seconds=self.policy.heartbeat_timeout_seconds,
        )

    def restart_worker(self, lease: WorkerLease) -> RestartResult:
        reservation = self.registry.reserve_restart(lease, policy=self.policy)
        if isinstance(reservation, RestartResult):
            return reservation
        # No core lock across factory or arbitrary property access. Publication
        # revalidates the reservation even when the factory appears successful.
        try:
            replacement = self._worker_factory(reservation.info.model_copy(deep=True))
            if not isinstance(replacement, WorkerAgent):
                raise TypeError("factory must return WorkerAgent")
            info = AgentInfo.model_validate(replacement.info.model_dump())
        except Exception as exc:  # noqa: BLE001 - explicit factory failure outcome.
            return self.registry.finish_restart_failure(
                reservation, error_type=type(exc).__name__
            )
        except BaseException as exc:
            self.registry._interrupt_restart(reservation, exc)
            raise
        return self.registry.publish_restart(reservation, replacement, info)

    def stop_worker(self, lease: WorkerLease) -> WorkerRecoveryResult:
        return self.scheduler.stop_worker(lease)

    def sweep(self) -> SweepResult:
        recoveries = tuple(
            self.scheduler.recover_worker_loss(
                candidate,
                heartbeat_timeout_seconds=self.policy.heartbeat_timeout_seconds,
            )
            for candidate in self.detect_timeouts()
        )
        # A previous failed factory may become eligible after cooldown. Capture a
        # fresh lease per candidate; reserve_restart still revalidates it.
        leases = [
            self.registry._lease(record)
            for record in self.registry.runtime_records.values()
            if record.status is AgentStatus.FAILED
        ]
        restarts: list[RestartResult] = []
        for lease in leases:
            try:
                restarts.append(self.restart_worker(lease))
            except StaleWorkerGenerationError:
                # Another sweep published a newer generation after the snapshot.
                # This is a stale observation, not a new recovery authorization.
                restarts.append(
                    RestartResult(
                        outcome=RestartOutcome.STALE_TICKET,
                        lease=lease,
                        reason_code="stale_sweep_lease",
                    )
                )
        return SweepResult(recoveries=recoveries, restarts=tuple(restarts))
