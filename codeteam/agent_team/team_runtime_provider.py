"""Fresh durable Team runtime construction for one coding request."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from codeteam.agent.runtime_models import CodingAgentRunRequest
from codeteam.agent_team.contracts import LifecyclePolicy
from codeteam.agent_team.coordination import TeamStateCoordinator
from codeteam.agent_team.dag import TaskDAG
from codeteam.agent_team.lifecycle import AgentLifecycleManager
from codeteam.agent_team.mailbox import AgentMailbox
from codeteam.agent_team.models import AgentIdentity, AgentInfo
from codeteam.agent_team.registry import AgentRegistry
from codeteam.agent_team.runtime_factory import (
    DurableTeamRuntime,
    capture_team_snapshot,
)
from codeteam.agent_team.scheduler import TaskScheduler
from codeteam.agent_team.team_planning import TeamPlan
from codeteam.agent_team.team_store import SQLiteTeamStateStore
from codeteam.agent_team.worker import WorkerAgent
from codeteam.agent_team.worker_pool import static_worker_infos


class TeamRuntimeProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class TeamRuntimeHandle:
    session_id: str
    session_dir: Path
    lead_id: str
    runtime: DurableTeamRuntime
    store: SQLiteTeamStateStore

    @classmethod
    def from_hydrated(
        cls,
        *,
        session_dir: Path,
        runtime: DurableTeamRuntime,
        lead_id: str = "lead",
    ) -> TeamRuntimeHandle:
        """Adapt the runtime returned by Day6 Session integration."""
        store = SQLiteTeamStateStore(session_dir)
        snapshot = runtime.snapshot
        if store.load(snapshot.session_id).revision != snapshot.revision:
            raise TeamRuntimeProviderError(
                "hydrated Team runtime and SQLite revision disagree"
            )
        return cls(
            session_id=snapshot.session_id,
            session_dir=session_dir.resolve(strict=True),
            lead_id=lead_id,
            runtime=runtime,
            store=store,
        )


class TeamRuntimeProvider(Protocol):
    def create(
        self,
        *,
        request: CodingAgentRunRequest,
        plan: TeamPlan,
    ) -> TeamRuntimeHandle: ...


class LocalTeamRuntimeProvider:
    """Create a new runtime epoch; old leases are never accepted here."""

    def __init__(
        self,
        state_root: Path,
        *,
        max_attempts: int = 2,
        lifecycle_policy: LifecyclePolicy | None = None,
        mailbox_capacity: int = 1000,
        worker_infos: tuple[AgentInfo, ...] | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._state_root = state_root
        self._max_attempts = max_attempts
        self._lifecycle_policy = lifecycle_policy or LifecyclePolicy()
        self._mailbox_capacity = mailbox_capacity
        selected = worker_infos or static_worker_infos()
        if not selected:
            raise ValueError("at least one Worker must be configured")
        self._worker_infos = tuple(
            AgentInfo.model_validate(info.model_dump()) for info in selected
        )

    def create(
        self,
        *,
        request: CodingAgentRunRequest,
        plan: TeamPlan,
    ) -> TeamRuntimeHandle:
        workspace = request.workspace_root.resolve(strict=True)
        state_root = self._state_root.resolve()
        try:
            state_root.relative_to(workspace)
        except ValueError:
            pass
        else:
            raise TeamRuntimeProviderError(
                "Team state root must be outside the mutable workspace"
            )

        state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(state_root, 0o700)
        session_id = f"team-{_safe_component(request.task_id)}-{uuid4().hex}"
        session_dir = state_root / session_id
        session_dir.mkdir(mode=0o700)
        os.chmod(session_dir, 0o700)

        coordinator = TeamStateCoordinator()
        registry = AgentRegistry(coordinator=coordinator)
        workers = tuple(WorkerAgent(info) for info in self._worker_infos)
        for worker in workers:
            registry.register(worker)

        dag = TaskDAG.from_lead_planning_result(
            plan.lead_result,
            dependencies=plan.dependencies,
        )
        scheduler = TaskScheduler(
            dag,
            registry,
            max_attempts=self._max_attempts,
        )
        mailbox = AgentMailbox(capacity_per_inbox=self._mailbox_capacity)
        lead = AgentIdentity(agent_id="lead", display_name="Team Lead")
        mailbox.register_agent(lead)
        for worker in workers:
            mailbox.register_agent(worker.info.identity)
        lifecycle = AgentLifecycleManager(
            registry,
            scheduler,
            policy=self._lifecycle_policy,
        )
        store = SQLiteTeamStateStore(session_dir)
        snapshot = capture_team_snapshot(
            session_id=session_id,
            registry=registry,
            scheduler=scheduler,
            mailbox=mailbox,
            policy=self._lifecycle_policy,
        )
        store.initialize(snapshot)
        runtime = DurableTeamRuntime(
            coordinator=coordinator,
            registry=registry,
            scheduler=scheduler,
            mailbox=mailbox,
            lifecycle=lifecycle,
            store=store,
            snapshot=snapshot,
        )
        runtime.persist(
            event_type="team.runtime.created",
            payload={
                "task_id": request.task_id,
                "runtime_id": coordinator.runtime_id,
                "worker_count": len(workers),
            },
        )
        return TeamRuntimeHandle(
            session_id=session_id,
            session_dir=session_dir,
            lead_id=lead.agent_id,
            runtime=runtime,
            store=store,
        )


def _safe_component(value: str) -> str:
    safe = "".join(character if character.isalnum() else "-" for character in value)
    return safe.strip("-") or "task"
