"""Fail-closed reconciliation of process-durable Team state."""

from __future__ import annotations

import heapq
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict

from codeteam.agent_team.dag import TaskStatus
from codeteam.agent_team.models import AgentStatus
from codeteam.agent_team.persistence_models import (
    DurableMessageState,
    TeamStateSnapshot,
)
from codeteam.agent_team.scheduler import TaskRuntimeRecord
from codeteam.session.models import OperationStatus, Session


class TeamReconciliationVerdict(str, Enum):
    RESUMABLE = "resumable"
    RECOVERY_REQUIRED = "recovery_required"
    INVALID = "invalid"


class TeamReconciliationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: TeamReconciliationVerdict
    issues: tuple[str, ...]
    snapshot: TeamStateSnapshot
    recovery_actions: tuple[str, ...] = ()


class TeamStateReconciler:
    """Convert old-runtime facts into a snapshot safe for a new runtime epoch."""

    def reconcile(
        self,
        *,
        session: Session,
        snapshot: TeamStateSnapshot,
        planned_runtime_id: str,
        git_has_unreconciled_effects: bool = False,
    ) -> TeamReconciliationReport:
        snapshot = TeamStateSnapshot.model_validate(snapshot.model_dump())
        issues: list[str] = []
        actions: list[str] = []
        in_flight = {
            node_id
            for node_id, record in snapshot.tasks.items()
            if record.status in {TaskStatus.CLAIMED, TaskStatus.RUNNING}
        }
        active = session.active_operation
        if git_has_unreconciled_effects and in_flight:
            issues.append("inflight_git_effects_are_not_reconciled")
        if (
            active is not None
            and active.status is OperationStatus.STARTED
            and in_flight
        ):
            issues.append(f"session_operation_still_started:{active.kind}")
        if issues:
            return TeamReconciliationReport(
                verdict=TeamReconciliationVerdict.RECOVERY_REQUIRED,
                issues=tuple(issues),
                snapshot=snapshot,
            )

        tasks = {
            node_id: record.model_copy(deep=True)
            for node_id, record in snapshot.tasks.items()
        }
        queue = list(snapshot.ready_queue)
        waiting = set(snapshot.waiting_for_worker)
        for node_id in sorted(in_flight):
            record = tasks[node_id]
            if record.attempt < snapshot.max_attempts:
                tasks[node_id] = record.model_copy(
                    update={
                        "status": TaskStatus.READY,
                        "owner_id": None,
                        "owner_generation": None,
                        "claimed_at": None,
                        "failure_reason": "process_recovery",
                    }
                )
                if node_id not in queue:
                    queue.append(node_id)
                actions.append(f"requeue:{node_id}:attempt={record.attempt}")
            else:
                tasks[node_id] = record.model_copy(
                    update={
                        "status": TaskStatus.FAILED,
                        "owner_id": None,
                        "owner_generation": None,
                        "claimed_at": None,
                        "failure_reason": "process_recovery_budget_exhausted",
                    }
                )
                actions.append(f"fail:{node_id}:retry_budget_exhausted")
            waiting.discard(node_id)

        blocked = self._terminal_blocked_closure(snapshot, tasks)
        for node_id in sorted(blocked):
            record = tasks[node_id]
            if record.status is TaskStatus.PENDING:
                tasks[node_id] = record.model_copy(
                    update={
                        "status": TaskStatus.BLOCKED,
                        "failure_reason": "blocked_by_failed_prerequisite",
                    }
                )
                waiting.discard(node_id)
                actions.append(f"block:{node_id}:failed_prerequisite")

        queue = [
            node_id
            for node_id in queue
            if tasks[node_id].status is TaskStatus.READY
        ]
        workers = {}
        for worker_id, worker in snapshot.workers.items():
            if worker.status is AgentStatus.STOPPED:
                workers[worker_id] = worker.model_copy(deep=True)
                continue
            target_status = worker.status
            if target_status in {AgentStatus.BUSY, AgentStatus.READY}:
                target_status = AgentStatus.READY
            elif target_status is AgentStatus.RESTARTING:
                target_status = AgentStatus.FAILED
            workers[worker_id] = worker.model_copy(
                update={
                    "status": target_status,
                    "generation": worker.generation + 1,
                    "revision": worker.revision + 1,
                }
            )
            actions.append(
                f"fence_worker:{worker_id}:generation={worker.generation + 1}"
            )

        messages = tuple(
            message.model_copy(
                update={
                    "state": DurableMessageState.PENDING,
                    "claimed_by_runtime_id": None,
                    "claim_id": None,
                }
            )
            if message.state is DurableMessageState.IN_FLIGHT
            else message.model_copy(deep=True)
            for message in snapshot.messages
        )
        for message in snapshot.messages:
            if message.state is DurableMessageState.IN_FLIGHT:
                actions.append(f"release_message:{message.message.message_id}")

        reconciled = snapshot.model_copy(
            update={
                "previous_runtime_id": planned_runtime_id,
                "tasks": tasks,
                "workers": workers,
                "ready_queue": tuple(queue),
                "waiting_for_worker": frozenset(waiting),
                "worker_ownership": {
                    worker_id: None for worker_id in snapshot.workers
                },
                "messages": messages,
                "updated_at": datetime.now(UTC),
            }
        )
        reconciled = TeamStateSnapshot.model_validate(reconciled.model_dump())
        return TeamReconciliationReport(
            verdict=TeamReconciliationVerdict.RESUMABLE,
            issues=(),
            snapshot=reconciled,
            recovery_actions=tuple(actions),
        )

    def _terminal_blocked_closure(
        self,
        snapshot: TeamStateSnapshot,
        tasks: dict[str, TaskRuntimeRecord],
    ) -> set[str]:
        statuses = {node_id: record.status for node_id, record in tasks.items()}
        indegrees = {
            node_id: len(snapshot.dependencies[node_id])
            for node_id in snapshot.dependencies
        }
        dependents: dict[str, set[str]] = {
            node_id: set() for node_id in snapshot.dependencies
        }
        for dependent_id, prerequisites in snapshot.dependencies.items():
            for prerequisite_id in prerequisites:
                dependents[prerequisite_id].add(dependent_id)
        ready = [node_id for node_id, degree in indegrees.items() if degree == 0]
        heapq.heapify(ready)
        blocked: set[str] = set()
        visited = 0
        while ready:
            node_id = heapq.heappop(ready)
            visited += 1
            if statuses[node_id] in {TaskStatus.FAILED, TaskStatus.BLOCKED} or any(
                parent in blocked for parent in snapshot.dependencies[node_id]
            ):
                blocked.add(node_id)
            for dependent_id in dependents[node_id]:
                indegrees[dependent_id] -= 1
                if indegrees[dependent_id] == 0:
                    heapq.heappush(ready, dependent_id)
        if visited != len(tasks):
            raise ValueError("durable DAG contains a cycle")
        return blocked
