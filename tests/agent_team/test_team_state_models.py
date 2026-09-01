from __future__ import annotations

from threading import RLock

import pytest
from pydantic import ValidationError

from codeteam.agent_team.dag import TaskStatus
from codeteam.agent_team.persistence_models import (
    DurableEventDraft,
    TeamStateSnapshot,
)

from .team_state_helpers import team_snapshot


def test_team_snapshot_json_round_trip_covers_complete_runtime_state() -> None:
    snapshot = team_snapshot()

    loaded = TeamStateSnapshot.model_validate_json(snapshot.model_dump_json())

    assert loaded == snapshot
    assert loaded.dependencies["B"] == frozenset({"A"})
    assert loaded.workers["worker-1"].restart_attempts == 1
    assert loaded.messages[0].message.message_id == "msg-1"
    assert "msg-consumed" in loaded.seen_message_ids


@pytest.mark.parametrize(
    "updates,match",
    [
        ({"ready_queue": ("A", "A")}, "ready_queue"),
        ({"ready_queue": ()}, "every READY"),
        ({"waiting_for_worker": frozenset({"A"})}, "waiting"),
        ({"worker_ownership": {}}, "worker_ownership"),
        ({"seen_message_ids": frozenset()}, "dedupe"),
        ({"dependencies": {"A": frozenset()}}, "dependencies"),
    ],
)
def test_team_snapshot_rejects_cross_object_inconsistency(
    updates: dict[str, object], match: str
) -> None:
    with pytest.raises(ValidationError, match=match):
        team_snapshot().model_copy(update=updates).model_dump_json()
        TeamStateSnapshot.model_validate(
            {**team_snapshot().model_dump(), **updates}
        )


def test_inflight_task_requires_matching_worker_generation_and_owner() -> None:
    snapshot = team_snapshot()
    task = snapshot.tasks["A"].model_copy(
        update={
            "status": TaskStatus.RUNNING,
            "owner_id": "worker-1",
            "owner_generation": 99,
            "attempt": 1,
        }
    )

    with pytest.raises(ValidationError, match="ownership"):
        TeamStateSnapshot.model_validate(
            {
                **snapshot.model_dump(),
                "ready_queue": (),
                "tasks": {**snapshot.tasks, "A": task},
                "worker_ownership": {"worker-1": "A"},
                "workers": {
                    "worker-1": snapshot.workers["worker-1"].model_copy(
                        update={"status": "busy"}
                    )
                },
            }
        )


def test_ephemeral_object_cannot_enter_snapshot() -> None:
    with pytest.raises(ValidationError):
        TeamStateSnapshot.model_validate(
            {**team_snapshot().model_dump(), "runtime_lock": RLock()}
        )


def test_durable_payloads_must_be_json_safe() -> None:
    with pytest.raises(ValidationError, match="JSON-safe"):
        DurableEventDraft(event_type="invalid", payload={"values": {1, 2}})

    snapshot = team_snapshot()
    message = snapshot.messages[0].model_copy(
        update={
            "message": snapshot.messages[0].message.model_copy(
                update={"payload": {"values": {1, 2}}}
            )
        }
    )
    with pytest.raises(ValidationError, match="JSON-safe"):
        TeamStateSnapshot.model_validate(
            {**snapshot.model_dump(), "messages": (message,)}
        )
