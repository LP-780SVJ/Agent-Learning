"""Week4 Day4 JsonSessionStore, atomic write, and event log tests."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pytest

from codeteam.events import AgentEventType
from codeteam.session import store as store_module
from codeteam.session.errors import (
    SessionAlreadyExistsError,
    SessionCorruptedError,
    SessionNotFoundError,
    SessionSchemaUnsupportedError,
)
from codeteam.session.models import SessionEvent
from codeteam.session.store import JsonSessionStore, find_timeline_anomalies

from .conftest import make_session


def test_store_create_then_load_round_trips(git_repo, tmp_path: Path) -> None:
    store = JsonSessionStore(tmp_path / "sessions")
    session = make_session(git_repo)

    store.create(session)

    assert store.load(session.manifest.session_id) == session


def test_store_create_existing_session_rejects_overwrite(
    git_repo,
    tmp_path: Path,
) -> None:
    store = JsonSessionStore(tmp_path / "sessions")
    session = make_session(git_repo)
    store.create(session)

    with pytest.raises(SessionAlreadyExistsError):
        store.create(session)


def test_store_save_increments_state_version_and_updated_at(
    git_repo,
    tmp_path: Path,
) -> None:
    store = JsonSessionStore(tmp_path / "sessions")
    session = store.create(make_session(git_repo))

    saved = store.save(session)

    assert saved.manifest.state_version == session.manifest.state_version + 1
    assert saved.manifest.updated_at > session.manifest.updated_at
    assert store.load(session.manifest.session_id).manifest.state_version == 2


def test_store_load_missing_session_raises(tmp_path: Path) -> None:
    store = JsonSessionStore(tmp_path / "sessions")

    with pytest.raises(SessionNotFoundError):
        store.load("ses_missing")


def test_store_load_invalid_json_raises_corrupted(tmp_path: Path) -> None:
    session_dir = tmp_path / "sessions" / "ses_bad"
    session_dir.mkdir(parents=True)
    (session_dir / "session.json").write_text("{not-json", encoding="utf-8")
    store = JsonSessionStore(tmp_path / "sessions")

    with pytest.raises(SessionCorruptedError):
        store.load("ses_bad")


def test_store_load_unsupported_schema_version_raises(tmp_path: Path) -> None:
    session_dir = tmp_path / "sessions" / "ses_old"
    session_dir.mkdir(parents=True)
    (session_dir / "session.json").write_text(
        '{"manifest": {"schema_version": 999}}',
        encoding="utf-8",
    )
    store = JsonSessionStore(tmp_path / "sessions")

    with pytest.raises(SessionSchemaUnsupportedError):
        store.load("ses_old")


@pytest.mark.parametrize(
    "bad_session_id",
    ["../ses_escape", "ses_bad/slash", "ses_bad\\slash", "bad"],
)
def test_store_rejects_session_id_path_traversal(
    tmp_path: Path,
    bad_session_id: str,
) -> None:
    store = JsonSessionStore(tmp_path / "sessions")

    with pytest.raises(SessionNotFoundError):
        store.load(bad_session_id)


def test_store_exposes_public_session_dir_with_path_guard(
    git_repo,
    tmp_path: Path,
) -> None:
    root = tmp_path / "sessions"
    store = JsonSessionStore(root)
    session = store.create(make_session(git_repo))
    any_store = cast(Any, store)

    assert "session_dir" in JsonSessionStore.__dict__
    assert any_store.session_dir(session.manifest.session_id) == (
        root / session.manifest.session_id
    )
    with pytest.raises(SessionNotFoundError):
        any_store.session_dir("../ses_escape")


def test_atomic_save_failure_preserves_previous_snapshot(
    git_repo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = JsonSessionStore(tmp_path / "sessions")
    session = store.create(make_session(git_repo))

    def fail_replace(src: Path, dst: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(store_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        store.save(session)

    loaded = store.load(session.manifest.session_id)
    assert loaded.manifest.state_version == 1
    assert loaded.manifest.updated_at == session.manifest.updated_at
    official_dir = tmp_path / "sessions" / session.manifest.session_id
    assert not (official_dir / "session.json.tmp").exists()


def test_append_event_seq_starts_at_one_and_uses_state_version(
    git_repo,
    tmp_path: Path,
) -> None:
    store = JsonSessionStore(tmp_path / "sessions")
    session = store.create(make_session(git_repo))

    first = store.append_event(
        session.manifest.session_id,
        event_type=AgentEventType.SESSION_CREATED,
        state_version=1,
    )
    second = store.append_event(
        session.manifest.session_id,
        event_type=AgentEventType.SESSION_PAUSED,
        state_version=2,
    )

    assert first.seq == 1
    assert first.state_version == 1
    assert second.seq == 2
    assert second.state_version == 2


def test_load_events_tolerates_trailing_partial_line(
    git_repo,
    tmp_path: Path,
) -> None:
    store = JsonSessionStore(tmp_path / "sessions")
    session = store.create(make_session(git_repo))
    store.append_event(
        session.manifest.session_id,
        event_type=AgentEventType.SESSION_CREATED,
        state_version=1,
    )
    events_path = tmp_path / "sessions" / session.manifest.session_id / "events.jsonl"
    with events_path.open("ab") as handle:
        handle.write(b'{"event_id":')

    events, dropped = store.load_events(session.manifest.session_id)

    assert [event.seq for event in events] == [1]
    assert dropped == 1


def test_last_valid_seq_uses_max_legal_seq_not_last_line(
    git_repo,
    tmp_path: Path,
) -> None:
    store = JsonSessionStore(tmp_path / "sessions")
    session = store.create(make_session(git_repo))
    events_path = tmp_path / "sessions" / session.manifest.session_id / "events.jsonl"
    event_5 = _event(session.manifest.session_id, 5).model_dump_json()
    event_2 = _event(session.manifest.session_id, 2).model_dump_json()
    events_path.write_text(f"{event_5}\nnot-json\n{event_2}\n", encoding="utf-8")

    appended = store.append_event(
        session.manifest.session_id,
        event_type=AgentEventType.SESSION_PAUSED,
        state_version=2,
    )

    assert appended.seq == 6


def test_find_timeline_anomalies_reports_duplicate_gap_and_out_of_order() -> None:
    events = [
        _event("ses_test", 1),
        _event("ses_test", 3),
        _event("ses_test", 3),
        _event("ses_test", 2),
    ]

    problems = find_timeline_anomalies(events)

    assert any(problem.startswith("gap:") for problem in problems)
    assert "duplicate: 3" in problems
    assert any(problem.startswith("out-of-order:") for problem in problems)


def _event(session_id: str, seq: int) -> SessionEvent:
    return SessionEvent(
        event_id=f"evt-{seq}",
        session_id=session_id,
        seq=seq,
        state_version=max(seq, 1),
        type=AgentEventType.SESSION_CREATED,
        timestamp=datetime.now(timezone.utc),
        payload={},
    )
