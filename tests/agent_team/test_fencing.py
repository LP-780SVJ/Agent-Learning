from __future__ import annotations

import pytest

from codeteam.agent_team.models import AgentStatus
from codeteam.agent_team.scheduler import StaleTaskClaimError, TaskScheduler

from .test_scheduler import _dag, _registry, _worker


@pytest.mark.parametrize("operation", ["start", "complete", "fail"])
def test_same_worker_old_attempt_cannot_mutate_new_attempt(operation: str) -> None:
    registry = _registry(_worker("w1"))
    scheduler = TaskScheduler(_dag("A"), registry, max_attempts=2)
    lease = registry.lease("w1")
    scheduler.schedule()
    first = scheduler.claim(lease)
    assert first is not None
    scheduler.start(first)
    scheduler.fail(first, "transient")
    second = scheduler.claim(lease)
    assert second is not None
    scheduler.start(second)
    assert first.worker_id == second.worker_id
    assert first.worker_generation == second.worker_generation
    assert second.attempt == first.attempt + 1
    before = scheduler.snapshot()
    with pytest.raises(StaleTaskClaimError):
        if operation == "fail":
            scheduler.fail(first, "late")
        elif operation == "start":
            scheduler.start(first)
        else:
            scheduler.complete(first)
    assert scheduler.snapshot() == before
    scheduler.complete(second)
    assert registry.runtime("w1").status is AgentStatus.READY


def test_draft_failure_rolls_back_registry_task_queue_and_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _registry(_worker("w1"))
    scheduler = TaskScheduler(_dag("A"), registry)
    scheduler.schedule()
    before = scheduler.snapshot()
    events = scheduler.events

    def broken_event(*args: object, **kwargs: object) -> None:
        raise ValueError("injected event preparation failure")

    monkeypatch.setattr(scheduler, "_record_event_locked", broken_event)
    with pytest.raises(ValueError, match="preparation"):
        scheduler.claim(registry.lease("w1"))
    assert scheduler.snapshot() == before
    assert scheduler.events == events
    assert registry.events == ()


def test_claim_and_completion_require_explicit_tokens() -> None:
    scheduler = TaskScheduler(_dag("A"), _registry(_worker("w1")))
    scheduler.schedule()
    for name in ("claim", "start", "complete"):
        with pytest.raises(TypeError, match="explicit"):
            getattr(scheduler, name)("w1")


def test_cross_runtime_claim_is_rejected_without_side_effect() -> None:
    scheduler = TaskScheduler(_dag("A"), _registry(_worker("w1")))
    scheduler.schedule()
    claim = scheduler.claim(scheduler.registry.lease("w1"))
    assert claim is not None
    before = scheduler.snapshot()
    with pytest.raises(StaleTaskClaimError):
        scheduler.start(claim.model_copy(update={"runtime_id": "other"}))
    assert scheduler.snapshot() == before
