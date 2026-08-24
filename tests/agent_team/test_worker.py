from __future__ import annotations

import pytest

from codeteam.agent_team.models import AgentIdentity, AgentInfo, AgentRole
from codeteam.agent_team.worker import (
    DuplicateWorkerError,
    WorkerAgent,
    WorkerNotFoundError,
    WorkerRegistry,
)


def _worker(
    worker_id: str,
    role: AgentRole,
    *,
    display_name: str | None = None,
) -> WorkerAgent:
    return WorkerAgent(
        AgentInfo(
            identity=AgentIdentity(
                agent_id=worker_id,
                display_name=display_name or worker_id,
            ),
            role=role,
        )
    )


def test_register_then_get_returns_same_worker() -> None:
    registry = WorkerRegistry()
    worker = _worker("worker-backend-1", AgentRole.BACKEND)

    registry.register(worker)

    assert registry.get("worker-backend-1") is worker


def test_duplicate_worker_id_is_rejected_without_overwrite() -> None:
    registry = WorkerRegistry()
    original = _worker("worker-test-1", AgentRole.TEST)
    replacement = _worker("worker-test-1", AgentRole.REVIEW)
    registry.register(original)

    with pytest.raises(DuplicateWorkerError, match="worker-test-1"):
        registry.register(replacement)

    assert registry.get("worker-test-1") is original


def test_unknown_worker_id_raises_domain_error() -> None:
    registry = WorkerRegistry()

    with pytest.raises(WorkerNotFoundError, match="missing-worker"):
        registry.get("missing-worker")


def test_compatible_returns_only_matching_role() -> None:
    registry = WorkerRegistry()
    backend = _worker("worker-backend-1", AgentRole.BACKEND)
    test = _worker("worker-test-1", AgentRole.TEST)
    reviewer = _worker("worker-review-1", AgentRole.REVIEW)
    registry.register(backend)
    registry.register(test)
    registry.register(reviewer)

    assert registry.compatible(AgentRole.TEST) == (test,)
    assert registry.compatible(AgentRole.BACKEND) == (backend,)
    assert registry.compatible(AgentRole.FRONTEND) == ()


def test_worker_supports_only_its_role() -> None:
    worker = _worker("worker-front-1", AgentRole.FRONTEND)

    assert worker.supports(AgentRole.FRONTEND) is True
    assert worker.supports(AgentRole.BACKEND) is False


def test_lead_role_cannot_be_registered_as_worker() -> None:
    info = AgentInfo(
        identity=AgentIdentity(agent_id="lead-1", display_name="Lead 1"),
        role=AgentRole.LEAD,
    )

    with pytest.raises(ValueError, match="lead role"):
        WorkerAgent(info)
