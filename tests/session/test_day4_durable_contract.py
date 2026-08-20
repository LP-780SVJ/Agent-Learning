"""Week4 Day4 durable session model contract tests."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

import pytest
from pydantic import ValidationError

from codeteam.events import AgentEventType
from codeteam.session.models import (
    Session,
    SessionEvent,
    SessionManifest,
)

from .conftest import make_failure, make_session


def test_session_model_round_trips_through_json(git_repo) -> None:
    session = make_session(git_repo)

    loaded = Session.model_validate_json(session.model_dump_json())

    assert loaded.manifest.session_id == session.manifest.session_id
    assert loaded.provider_id == session.provider_id
    assert loaded.model_id == session.model_id
    assert loaded.repo == session.repo


@pytest.mark.parametrize("field", ["provider_id", "model_id"])
def test_provider_and_model_ids_must_not_be_blank(git_repo, field: str) -> None:
    with pytest.raises(ValidationError):
        if field == "provider_id":
            make_session(git_repo, provider_id="   ")
        else:
            make_session(git_repo, model_id="   ")


def test_manifest_requires_timezone_aware_datetimes() -> None:
    naive = datetime.now(timezone.utc).replace(tzinfo=None)

    with pytest.raises(ValidationError):
        SessionManifest(
            session_id="ses_naive",
            repo_id="repo-1",
            created_at=naive,
            updated_at=datetime.now(timezone.utc),
        )


def test_session_event_requires_timezone_aware_timestamp() -> None:
    naive = datetime.now(timezone.utc).replace(tzinfo=None)

    with pytest.raises(ValidationError):
        SessionEvent(
            event_id="evt-1",
            session_id="ses_test",
            seq=1,
            state_version=1,
            type=AgentEventType.SESSION_CREATED,
            timestamp=naive,
            payload={},
        )


def test_last_failure_source_message_is_redacted_when_persisted(git_repo) -> None:
    session = make_session(
        git_repo,
        last_failure=make_failure(source_message="secret api key sk-test"),
    )

    raw_json = session.model_dump_json()
    loaded = Session.model_validate_json(raw_json)

    assert "secret api key" not in raw_json
    assert loaded.last_failure is not None
    assert loaded.last_failure.source_message == "<redacted>"


def test_ephemeral_objects_are_rejected_from_durable_snapshot(git_repo) -> None:
    runtime_object = cast(Any, object())

    with pytest.raises(ValidationError):
        make_session(git_repo, usage=runtime_object)
