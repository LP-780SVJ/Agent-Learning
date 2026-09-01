from __future__ import annotations

from pathlib import Path

import pytest

from codeteam.agent_team.dag import TaskStatus
from codeteam.agent_team.models import AgentStatus
from codeteam.agent_team.persistence_models import (
    TEAM_STATE_SCHEMA_VERSION,
    DurableEventDraft,
)
from codeteam.agent_team.runtime_factory import DurableTeamRuntime
from codeteam.agent_team.session_integration import TeamSessionRuntimeBuilder
from codeteam.agent_team.team_store import SQLiteTeamStateStore
from codeteam.events import AgentEventType
from codeteam.session.errors import (
    SessionAlreadyActiveError,
    SessionRecoveryRequiredError,
)
from codeteam.session.models import SessionStatus, TeamStateRef
from codeteam.session.service import SessionService
from codeteam.session.store import JsonSessionStore
from tests.agent_team.team_state_helpers import team_snapshot

from .conftest import init_git_repo, make_session, make_worktree_ref


def persisted_team_session(tmp_path: Path):
    repo = init_git_repo(tmp_path / "repo")
    store = JsonSessionStore(tmp_path / "sessions")
    session = make_session(
        repo,
        session_id="ses_team_test",
        status=SessionStatus.PAUSED,
        worktree=make_worktree_ref(repo),
        team_state=TeamStateRef(
            schema_version=TEAM_STATE_SCHEMA_VERSION,
            acknowledged_revision=1,
        ),
    )
    store.create(session)
    team_store = SQLiteTeamStateStore(store.session_dir(session.manifest.session_id))
    team_store.initialize(team_snapshot(session_id=session.manifest.session_id))
    return repo, store, team_store, session


def test_team_resume_commits_then_hydrates_then_publishes_session(
    tmp_path: Path,
) -> None:
    repo, store, team_store, session = persisted_team_session(tmp_path)
    service = SessionService(
        store,
        runtime_builder=TeamSessionRuntimeBuilder(),
    )

    outcome = service.resume(session.manifest.session_id, current_repo=repo)

    assert outcome.session.status is SessionStatus.RUNNING
    assert isinstance(outcome.runtime, DurableTeamRuntime)
    assert outcome.session.team_state is not None
    assert outcome.session.team_state.acknowledged_revision == 2
    durable = team_store.load(session.manifest.session_id)
    assert durable.revision == 2
    assert durable.previous_runtime_id == outcome.runtime.coordinator.runtime_id
    events, _ = store.load_events(session.manifest.session_id)
    assert events[-1].type is AgentEventType.SESSION_RESUMED
    assert events[-1].payload["team_revision"] == 2
    assert events[-1].payload["team_runtime_id"] == durable.previous_runtime_id


def test_successful_resume_holds_writer_until_pause(tmp_path: Path) -> None:
    repo, store, _team_store, session = persisted_team_session(tmp_path)
    first = SessionService(store, runtime_builder=TeamSessionRuntimeBuilder())
    outcome = first.resume(session.manifest.session_id, current_repo=repo)
    second = SessionService(store, runtime_builder=TeamSessionRuntimeBuilder())

    with pytest.raises(SessionAlreadyActiveError):
        second.resume(session.manifest.session_id, current_repo=repo)

    paused = first.pause(outcome.session, reason="test complete")
    assert paused.status is SessionStatus.PAUSED
    assert not (store.session_dir(session.manifest.session_id) / "writer.lock").exists()


def test_team_db_ahead_of_session_hint_is_reconciled(tmp_path: Path) -> None:
    repo, store, team_store, session = persisted_team_session(tmp_path)
    current = team_store.load(session.manifest.session_id)
    ahead = team_store.commit(
        current,
        expected_revision=1,
        events=(DurableEventDraft(event_type="injected.db_ahead"),),
    )
    assert ahead.revision == 2

    outcome = SessionService(
        store,
        runtime_builder=TeamSessionRuntimeBuilder(),
    ).resume(session.manifest.session_id, current_repo=repo)

    assert outcome.session.team_state is not None
    assert outcome.session.team_state.acknowledged_revision == 3
    events, _ = store.load_events(session.manifest.session_id)
    assert events[-1].payload["team_revision_gap_reconciled"] == 1


def test_stale_running_team_session_reconciles_inflight_task_before_hydration(
    tmp_path: Path,
) -> None:
    repo, store, team_store, session = persisted_team_session(tmp_path)
    current = team_store.load(session.manifest.session_id)
    running = current.model_copy(
        update={
            "ready_queue": (),
            "tasks": {
                "A": current.tasks["A"].model_copy(
                    update={
                        "status": TaskStatus.RUNNING,
                        "owner_id": "worker-1",
                        "owner_generation": 2,
                        "attempt": 1,
                        "claimed_at": 1.0,
                    }
                ),
                "B": current.tasks["B"],
            },
            "workers": {
                "worker-1": current.workers["worker-1"].model_copy(
                    update={"status": AgentStatus.BUSY}
                )
            },
            "worker_ownership": {"worker-1": "A"},
        }
    )
    team_store.commit(running, expected_revision=1)
    stale = store.save(session.model_copy(update={"status": SessionStatus.RUNNING}))

    outcome = SessionService(
        store,
        runtime_builder=TeamSessionRuntimeBuilder(),
    ).resume(stale.manifest.session_id, current_repo=repo)

    assert outcome.session.status is SessionStatus.RUNNING
    assert outcome.runtime is not None
    durable = team_store.load(stale.manifest.session_id)
    assert durable.tasks["A"].status is TaskStatus.READY
    assert durable.tasks["A"].attempt == 1
    assert durable.tasks["A"].owner_id is None
    assert durable.ready_queue == ("A",)
    assert durable.workers["worker-1"].generation == 3


def test_team_db_behind_session_hint_fails_closed_and_releases_lock(
    tmp_path: Path,
) -> None:
    repo, store, _team_store, session = persisted_team_session(tmp_path)
    stored = store.load(session.manifest.session_id)
    store.save(
        stored.model_copy(
            update={
                "team_state": TeamStateRef(
                    schema_version=TEAM_STATE_SCHEMA_VERSION,
                    acknowledged_revision=2,
                )
            }
        )
    )
    service = SessionService(store, runtime_builder=TeamSessionRuntimeBuilder())

    with pytest.raises(SessionRecoveryRequiredError, match="behind"):
        service.resume(session.manifest.session_id, current_repo=repo)

    persisted = store.load(session.manifest.session_id)
    assert persisted.status is SessionStatus.RECOVERY_REQUIRED
    assert not (store.session_dir(session.manifest.session_id) / "writer.lock").exists()
    events, _ = store.load_events(session.manifest.session_id)
    assert events[-1].type is AgentEventType.SESSION_RECOVERY_REQUIRED
    assert events[-1].payload["source"] == "team"


def test_missing_team_database_never_falls_back_to_empty_runtime(
    tmp_path: Path,
) -> None:
    repo = init_git_repo(tmp_path / "repo")
    store = JsonSessionStore(tmp_path / "sessions")
    session = make_session(
        repo,
        session_id="ses_team_test",
        status=SessionStatus.PAUSED,
        team_state=TeamStateRef(
            schema_version=TEAM_STATE_SCHEMA_VERSION,
            acknowledged_revision=1,
        ),
    )
    store.create(session)

    with pytest.raises(SessionRecoveryRequiredError, match="load_failed"):
        SessionService(
            store,
            runtime_builder=TeamSessionRuntimeBuilder(),
        ).resume(session.manifest.session_id, current_repo=repo)

    assert store.load(session.manifest.session_id).status is SessionStatus.RECOVERY_REQUIRED


def test_team_reference_without_runtime_builder_fails_closed(
    tmp_path: Path,
) -> None:
    repo, store, _team_store, session = persisted_team_session(tmp_path)

    with pytest.raises(
        SessionRecoveryRequiredError,
        match="team_runtime_builder_not_configured",
    ):
        SessionService(store).resume(session.manifest.session_id, current_repo=repo)

    persisted = store.load(session.manifest.session_id)
    assert persisted.status is SessionStatus.RECOVERY_REQUIRED
    assert not (store.session_dir(session.manifest.session_id) / "writer.lock").exists()
    events, _ = store.load_events(session.manifest.session_id)
    assert events[-1].type is AgentEventType.SESSION_RECOVERY_REQUIRED
    assert events[-1].payload["source"] == "team"
