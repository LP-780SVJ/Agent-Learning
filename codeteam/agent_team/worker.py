from __future__ import annotations

from codeteam.agent_team.models import AgentInfo, AgentRole
from codeteam.agent_team.registry import AgentRegistry as WorkerRegistry
from codeteam.agent_team.registry import DuplicateWorkerError, WorkerNotFoundError

__all__ = [
    "DuplicateWorkerError",
    "WorkerAgent",
    "WorkerNotFoundError",
    "WorkerRegistry",
]


class WorkerAgent:
    def __init__(self, info: AgentInfo) -> None:
        if info.role is AgentRole.LEAD:
            raise ValueError("WorkerAgent cannot use the lead role")
        self._info = info.model_copy(deep=True)

    @property
    def info(self) -> AgentInfo:
        return self._info.model_copy(deep=True)

    def supports(self, role: AgentRole) -> bool:
        return self._info.role is role
