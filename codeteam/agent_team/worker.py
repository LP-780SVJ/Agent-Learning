from __future__ import annotations

from codeteam.agent_team.models import AgentInfo, AgentRole


class DuplicateWorkerError(ValueError):
    """Raised when a worker id is registered more than once."""


class WorkerNotFoundError(LookupError):
    """Raised when a worker id is not present in the registry."""


class WorkerAgent:
    def __init__(self, info: AgentInfo) -> None:
        if info.role is AgentRole.LEAD:
            raise ValueError("WorkerAgent cannot use the lead role")
        self._info = info

    @property
    def info(self) -> AgentInfo:
        return self._info

    def supports(self, role: AgentRole) -> bool:
        return self._info.role is role


class WorkerRegistry:
    def __init__(self) -> None:
        self._workers: dict[str, WorkerAgent] = {}

    def register(self, worker: WorkerAgent) -> None:
        worker_id = worker.info.identity.agent_id
        if worker_id in self._workers:
            raise DuplicateWorkerError(worker_id)
        self._workers[worker_id] = worker

    def get(self, worker_id: str) -> WorkerAgent:
        try:
            return self._workers[worker_id]
        except KeyError as exc:
            raise WorkerNotFoundError(worker_id) from exc

    def compatible(self, role: AgentRole) -> tuple[WorkerAgent, ...]:
        return tuple(
            worker
            for worker in self._workers.values()
            if worker.supports(role)
        )
