from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from codeteam.agent_team.persistence_errors import (
    StaleMessageClaimError,
    TeamStateAlreadyExistsError,
    TeamStateConflictError,
    TeamStateCorruptedError,
    TeamStatePathError,
    TeamStateSchemaUnsupportedError,
)
from codeteam.agent_team.persistence_models import DurableEventDraft
from codeteam.agent_team.team_store import SQLiteTeamStateStore

from .team_state_helpers import team_snapshot


def store_at(tmp_path: Path) -> SQLiteTeamStateStore:
    session_dir = tmp_path / "ses_team_test"
    session_dir.mkdir(mode=0o700)
    return SQLiteTeamStateStore(session_dir)


def test_normalized_store_round_trip_and_schema(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    snapshot = team_snapshot()

    assert store.initialize(snapshot) == snapshot
    assert store.load(snapshot.session_id) == snapshot

    with sqlite3.connect(store.db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"task_runtime", "messages", "workers", "team_events"} <= tables
        assert connection.execute("SELECT count(*) FROM task_runtime").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM messages").fetchone()[0] == 1
    assert store.db_path.stat().st_mode & 0o777 == 0o600
    assert store.db_path.parent.stat().st_mode & 0o777 == 0o700


def test_initialize_refuses_overwrite(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.initialize(team_snapshot())

    with pytest.raises(TeamStateAlreadyExistsError):
        store.initialize(team_snapshot())


def test_commit_updates_revision_and_event_atomically(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    snapshot = store.initialize(team_snapshot())

    committed = store.commit(
        snapshot,
        expected_revision=1,
        events=(DurableEventDraft(event_type="team.changed", payload={"value": 1}),),
    )

    assert committed.revision == 2
    assert committed.last_event_seq == 1
    assert store.load(snapshot.session_id) == committed
    events = store.load_events(snapshot.session_id)
    assert [(event.seq, event.revision, event.event_type) for event in events] == [
        (1, 2, "team.changed")
    ]


def test_stale_cas_has_no_state_or_event_side_effect(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    initial = store.initialize(team_snapshot())
    committed = store.commit(initial, expected_revision=1)

    with pytest.raises(TeamStateConflictError):
        store.commit(initial, expected_revision=1)

    assert store.load(initial.session_id) == committed
    assert store.load_events(initial.session_id) == ()


def test_failure_after_state_write_rolls_back_state_and_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = store_at(tmp_path)
    initial = store.initialize(team_snapshot())
    original = store._write_snapshot

    def fail_after_write(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)  # type: ignore[arg-type]
        raise sqlite3.IntegrityError("injected")

    monkeypatch.setattr(store, "_write_snapshot", fail_after_write)

    with pytest.raises(TeamStateCorruptedError):
        store.commit(
            initial,
            expected_revision=1,
            events=(DurableEventDraft(event_type="never.committed"),),
        )

    assert store.load(initial.session_id) == initial
    assert store.load_events(initial.session_id) == ()


def test_schema_gate_rejects_future_version(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    snapshot = store.initialize(team_snapshot())
    with sqlite3.connect(store.db_path) as connection:
        connection.execute("PRAGMA user_version = 999")

    with pytest.raises(TeamStateSchemaUnsupportedError):
        store.load(snapshot.session_id)


def test_corrupted_database_is_not_treated_as_empty_state(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.db_path.write_bytes(b"not-sqlite")

    with pytest.raises(TeamStateCorruptedError):
        store.load("ses_team_test")


def test_claim_ack_is_durable_and_preserves_dedupe(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    initial = store.initialize(team_snapshot())

    claimed, claim = store.claim_message(
        initial.session_id,
        recipient_id="worker-1",
        runtime_id="runtime-new",
        expected_revision=1,
    )

    assert claim is not None
    assert claimed.revision == claim.revision == 2
    assert store.load(initial.session_id).messages[0].claim_id == claim.claim_id

    acked = store.ack_message(
        initial.session_id,
        claim,
        expected_revision=claimed.revision,
    )
    assert acked.messages == ()
    assert "msg-1" in acked.seen_message_ids
    assert [event.event_type for event in store.load_events(initial.session_id)] == [
        "mailbox.message_claimed",
        "mailbox.message_acked",
    ]

    with pytest.raises(StaleMessageClaimError):
        store.ack_message(
            initial.session_id,
            claim,
            expected_revision=acked.revision,
        )


def test_no_pending_message_does_not_increment_revision(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    initial = store.initialize(team_snapshot())

    unchanged, claim = store.claim_message(
        initial.session_id,
        recipient_id="lead-1",
        runtime_id="runtime-new",
        expected_revision=1,
    )

    assert claim is None
    assert unchanged == initial


def test_release_rejects_modified_delivery_attempt(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    initial = store.initialize(team_snapshot())
    claimed, claim = store.claim_message(
        initial.session_id,
        recipient_id="worker-1",
        runtime_id="runtime-new",
        expected_revision=1,
    )
    assert claim is not None

    with pytest.raises(StaleMessageClaimError):
        store.release_message(
            initial.session_id,
            claim.model_copy(update={"delivery_attempt": 99}),
            expected_revision=claimed.revision,
        )

    assert store.load(initial.session_id) == claimed


def test_store_rejects_symlink_session_directory(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)

    with pytest.raises(TeamStatePathError):
        SQLiteTeamStateStore(alias)
