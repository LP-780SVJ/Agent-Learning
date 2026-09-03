"""Static local Worker pool and assignment compatibility policy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from codeteam.agent_team.models import (
    AgentIdentity,
    AgentInfo,
    AgentRole,
    AgentStatus,
    WorkerAssignment,
)

if TYPE_CHECKING:
    from codeteam.agent_team.worker import WorkerAgent


def static_worker_infos() -> tuple[AgentInfo, ...]:
    return (
        AgentInfo(
            identity=AgentIdentity(
                agent_id="worker-general-1",
                display_name="General Worker",
            ),
            role=AgentRole.GENERAL,
            status=AgentStatus.READY,
            capabilities=("read", "search", "patch", "test", "git_diff"),
        ),
        AgentInfo(
            identity=AgentIdentity(
                agent_id="worker-backend-1",
                display_name="Backend Worker",
            ),
            role=AgentRole.BACKEND,
            status=AgentStatus.READY,
            capabilities=(
                "python",
                "api",
                "database",
                "read",
                "search",
                "patch",
                "test",
                "git_diff",
            ),
        ),
        AgentInfo(
            identity=AgentIdentity(
                agent_id="worker-test-1",
                display_name="Test Worker",
            ),
            role=AgentRole.TEST,
            status=AgentStatus.READY,
            capabilities=(
                "pytest",
                "regression",
                "review",
                "read",
                "search",
                "patch",
                "git_diff",
            ),
        ),
    )


def static_workers() -> tuple[WorkerAgent, ...]:
    from codeteam.agent_team.worker import WorkerAgent

    return tuple(WorkerAgent(info) for info in static_worker_infos())


def assignment_compatibility_rank(
    assignment: WorkerAssignment,
    worker: AgentInfo,
) -> int | None:
    required = set(assignment.required_capabilities)
    available = set(worker.capabilities)
    if not required.issubset(available):
        return None
    if worker.role is assignment.role:
        return 0
    if worker.role is AgentRole.GENERAL:
        return 1
    return None
