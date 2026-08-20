"""Week4 Day4 pause, reconciliation, and resume orchestration tests."""
from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pytest

from codeteam.events import AgentEventType
from codeteam.session.errors import (
    RepositoryMismatchError,
    SessionNotFoundError,
    SessionRecoveryRequiredError,
    SessionTerminalError,
)
from codeteam.session.models import (
    ActiveOperation,
    OperationStatus,
    ReconciliationVerdict,
    Session,
    SessionEvent,
    SessionStatus,
)
from codeteam.session.store import JsonSessionStore

from .conftest import (
    commit_file,
    head_sha,
    init_git_repo,
    make_repo_ref,
    make_session,
    make_worktree_ref,
)


def _service_module() -> Any:
    return importlib.import_module("codeteam.session.service")


class RecordingStore:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.events: list[SessionEvent] = []
        self.saved: list[Session] = []

    def save(self, session: Session) -> Session:
        self.calls.append("save")
        persisted = session.model_copy(deep=True)
        persisted.manifest.state_version += 1
        persisted.manifest.updated_at = datetime.now(timezone.utc)
        self.saved.append(persisted)
        return persisted

    def append_event(
        self,
        session_id: str,
        *,
        event_type: AgentEventType,
        payload: dict[str, Any] | None = None,
        state_version: int,
    ) -> SessionEvent:
        self.calls.append(f"event:{event_type.value}")
        event = SessionEvent(
            event_id=f"evt-{len(self.events) + 1}",
            session_id=session_id,
            seq=len(self.events) + 1,
            state_version=state_version,
            type=event_type,
            timestamp=datetime.now(timezone.utc),
            payload=payload or {},
        )
        self.events.append(event)
        return event


class FakeLock:
    def __init__(self) -> None:
        self.released = False

    def release(self) -> None:
        self.released = True


def test_session_service_module_imports_normally() -> None:
    assert _service_module().__name__ == "codeteam.session.service"


def test_pause_order_is_stop_refresher_save_then_event(git_repo) -> None:
    calls: list[str] = []
    store = RecordingStore(calls)
    session = make_session(git_repo, status=SessionStatus.RUNNING)
    service_module = _service_module()

    def stop_operation(current: Session) -> None:
        assert current is session
        calls.append("stop")

    def refresher(current: Session) -> Session:
        assert current is session
        calls.append("refresh")
        return current

    service = service_module.SessionService(
        cast(JsonSessionStore, store),
        stop_operation=stop_operation,
        refresher=refresher,
    )

    paused = service.pause(session, reason="user interrupt")

    assert paused.status is SessionStatus.PAUSED
    assert calls == ["stop", "refresh", "save", "event:session.paused"]
    assert store.events[0].state_version == paused.manifest.state_version


def test_pause_is_idempotent_when_already_paused(git_repo) -> None:
    calls: list[str] = []
    store = RecordingStore(calls)
    service_module = _service_module()
    service = service_module.SessionService(cast(JsonSessionStore, store))
    session = make_session(git_repo, status=SessionStatus.PAUSED)

    returned = service.pause(session, reason="again")

    assert returned is session
    assert calls == []


@pytest.mark.parametrize(
    "status",
    [SessionStatus.COMPLETED, SessionStatus.FAILED],
)
def test_pause_rejects_terminal_sessions(git_repo, status: SessionStatus) -> None:
    service_module = _service_module()
    service = service_module.SessionService(
        cast(JsonSessionStore, RecordingStore([]))
    )
    session = make_session(git_repo, status=status)

    with pytest.raises(SessionTerminalError):
        service.pause(session, reason="too late")


def test_pause_releases_existing_writer_lock(git_repo) -> None:
    calls: list[str] = []
    store = RecordingStore(calls)
    service_module = _service_module()
    service = service_module.SessionService(cast(JsonSessionStore, store))
    session = make_session(git_repo, status=SessionStatus.RUNNING)
    fake_lock = FakeLock()
    service._locks[session.manifest.session_id] = fake_lock

    paused = service.pause(session, reason="user interrupt")

    assert paused.status is SessionStatus.PAUSED
    assert fake_lock.released is True
    assert session.manifest.session_id not in service._locks


def test_reconciler_clean_paused_session_is_resumable(git_repo) -> None:
    session = make_session(
        git_repo,
        status=SessionStatus.PAUSED,
        worktree=make_worktree_ref(git_repo),
    )
    service_module = _service_module()
    reconciler = service_module.SessionReconciler()

    report = reconciler.reconcile(session, current_repo=git_repo)

    assert isinstance(report, service_module.ReconciliationReport)
    assert report.verdict is ReconciliationVerdict.RESUMABLE
    assert report.issues == ()


def test_reconciler_repo_common_dir_mismatch_is_invalid(tmp_path: Path) -> None:
    repo_a = init_git_repo(tmp_path / "repo-a")
    repo_b = init_git_repo(tmp_path / "repo-b")
    session = make_session(repo_a, status=SessionStatus.PAUSED)

    service_module = _service_module()
    report = service_module.SessionReconciler().reconcile(
        session,
        current_repo=repo_b,
    )

    assert report.verdict is ReconciliationVerdict.INVALID
    assert any("repo_mismatch" in issue for issue in report.issues)


def test_reconciler_missing_base_sha_requires_recovery(git_repo) -> None:
    repo = make_repo_ref(git_repo, base_sha="0" * 40)
    session = make_session(git_repo, status=SessionStatus.PAUSED, repo=repo)

    service_module = _service_module()
    report = service_module.SessionReconciler().reconcile(
        session,
        current_repo=git_repo,
    )

    assert report.verdict is ReconciliationVerdict.RECOVERY_REQUIRED
    assert any("base_missing" in issue for issue in report.issues)


def test_reconciler_missing_worktree_requires_recovery(
    git_repo,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing-worktree"
    worktree = make_worktree_ref(git_repo).model_copy(
        update={"path": str(missing)}
    )
    session = make_session(
        git_repo,
        status=SessionStatus.PAUSED,
        worktree=worktree,
    )

    service_module = _service_module()
    report = service_module.SessionReconciler().reconcile(
        session,
        current_repo=git_repo,
    )

    assert report.verdict is ReconciliationVerdict.RECOVERY_REQUIRED
    assert any("worktree_missing" in issue for issue in report.issues)


def test_reconciler_worktree_head_drift_requires_recovery(git_repo) -> None:
    old_head = head_sha(git_repo)
    commit_file(git_repo, "app.py", "VALUE = 2\n")
    worktree = make_worktree_ref(
        git_repo,
        last_known_head_sha=old_head,
    )
    session = make_session(
        git_repo,
        status=SessionStatus.PAUSED,
        worktree=worktree,
    )

    service_module = _service_module()
    report = service_module.SessionReconciler().reconcile(
        session,
        current_repo=git_repo,
    )

    assert report.verdict is ReconciliationVerdict.RECOVERY_REQUIRED
    assert any("worktree_head_drift" in issue for issue in report.issues)


def test_reconciler_worktree_dirty_drift_requires_recovery(git_repo) -> None:
    worktree = make_worktree_ref(git_repo, last_known_dirty=False)
    (git_repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    session = make_session(
        git_repo,
        status=SessionStatus.PAUSED,
        worktree=worktree,
    )

    service_module = _service_module()
    report = service_module.SessionReconciler().reconcile(
        session,
        current_repo=git_repo,
    )

    assert report.verdict is ReconciliationVerdict.RECOVERY_REQUIRED
    assert any("worktree_dirty_drift" in issue for issue in report.issues)


def test_reconciler_missing_checkpoint_requires_recovery(git_repo) -> None:
    session = make_session(
        git_repo,
        status=SessionStatus.PAUSED,
        checkpoint_ids=("cp-1",),
        current_checkpoint_id="cp-2",
    )
    service_module = _service_module()
    reconciler = service_module.SessionReconciler(list_checkpoint_ids=lambda: set())

    report = reconciler.reconcile(session, current_repo=git_repo)

    assert report.verdict is ReconciliationVerdict.RECOVERY_REQUIRED
    assert any("checkpoint_missing: cp-1" in issue for issue in report.issues)
    assert any("checkpoint_missing: cp-2" in issue for issue in report.issues)


def test_reconciler_provider_unavailable_requires_recovery(git_repo) -> None:
    session = make_session(git_repo, status=SessionStatus.PAUSED)
    service_module = _service_module()
    reconciler = service_module.SessionReconciler(
        is_provider_available=lambda provider_id, model_id: False,
    )

    report = reconciler.reconcile(session, current_repo=git_repo)

    assert report.verdict is ReconciliationVerdict.RECOVERY_REQUIRED
    assert any("provider_unavailable" in issue for issue in report.issues)


def test_reconciler_stale_running_requires_recovery_and_patches_status(
    git_repo,
) -> None:
    session = make_session(git_repo, status=SessionStatus.RUNNING)

    service_module = _service_module()
    report = service_module.SessionReconciler().reconcile(
        session,
        current_repo=git_repo,
    )

    assert report.verdict is ReconciliationVerdict.RECOVERY_REQUIRED
    assert report.session.status is SessionStatus.RECOVERY_REQUIRED
    assert any("stale_running" in issue for issue in report.issues)


def test_reconciler_started_active_operation_requires_recovery(git_repo) -> None:
    operation = ActiveOperation(
        operation_id="op-1",
        kind="verification",
        status=OperationStatus.STARTED,
        started_at=datetime.now(timezone.utc),
    )
    session = make_session(
        git_repo,
        status=SessionStatus.PAUSED,
        active_operation=operation,
    )

    service_module = _service_module()
    report = service_module.SessionReconciler().reconcile(
        session,
        current_repo=git_repo,
    )

    assert report.verdict is ReconciliationVerdict.RECOVERY_REQUIRED
    assert any("inflight_operation" in issue for issue in report.issues)


def test_session_service_resume_exists_on_service_not_outcome() -> None:
    service_module = _service_module()
    assert hasattr(service_module.SessionService, "resume")
    assert not hasattr(service_module.ResumeOutcome, "resume")


def test_resume_store_not_found_is_propagated(tmp_path: Path, git_repo) -> None:
    service_module = _service_module()
    service = service_module.SessionService(JsonSessionStore(tmp_path / "sessions"))
    resume = service.resume

    with pytest.raises(SessionNotFoundError):
        resume("ses_missing", current_repo=git_repo)


@pytest.mark.parametrize(
    "status",
    [SessionStatus.COMPLETED, SessionStatus.FAILED],
)
def test_resume_rejects_terminal_session_and_writes_event(
    tmp_path: Path,
    git_repo,
    status: SessionStatus,
) -> None:
    store = JsonSessionStore(tmp_path / "sessions")
    session = store.create(make_session(git_repo, status=status))
    service_module = _service_module()
    service = service_module.SessionService(store)
    resume = service.resume

    with pytest.raises(SessionTerminalError):
        resume(session.manifest.session_id, current_repo=git_repo)

    events, _ = store.load_events(session.manifest.session_id)
    assert events[-1].type is AgentEventType.SESSION_RESUME_REJECTED


def test_resume_repo_mismatch_rejects_and_releases_writer_lock(
    tmp_path: Path,
) -> None:
    repo_a = init_git_repo(tmp_path / "repo-a")
    repo_b = init_git_repo(tmp_path / "repo-b")
    store = JsonSessionStore(tmp_path / "sessions")
    session = store.create(make_session(repo_a, status=SessionStatus.PAUSED))
    service_module = _service_module()
    service = service_module.SessionService(store)
    resume = service.resume

    with pytest.raises(RepositoryMismatchError):
        resume(session.manifest.session_id, current_repo=repo_b)

    lock_path = tmp_path / "sessions" / session.manifest.session_id / "writer.lock"
    assert not lock_path.exists()


def test_resume_recovery_required_persists_status_and_event(
    tmp_path: Path,
    git_repo,
) -> None:
    store = JsonSessionStore(tmp_path / "sessions")
    session = store.create(make_session(git_repo, status=SessionStatus.RUNNING))
    service_module = _service_module()
    service = service_module.SessionService(store)
    resume = service.resume

    with pytest.raises(SessionRecoveryRequiredError):
        resume(session.manifest.session_id, current_repo=git_repo)

    loaded = store.load(session.manifest.session_id)
    events, _ = store.load_events(session.manifest.session_id)
    assert loaded.status is SessionStatus.RECOVERY_REQUIRED
    assert events[-1].type is AgentEventType.SESSION_RECOVERY_REQUIRED


def test_resume_resumable_reconstructs_runtime_saves_running_and_holds_lock(
    tmp_path: Path,
    git_repo,
) -> None:
    store = JsonSessionStore(tmp_path / "sessions")
    session = store.create(
        make_session(
            git_repo,
            status=SessionStatus.PAUSED,
            worktree=make_worktree_ref(git_repo),
        )
    )
    factory_sessions: list[Session] = []

    def runtime_factory(durable_session: Session) -> object:
        factory_sessions.append(durable_session)
        return {"runtime": "rebuilt"}

    service_module = _service_module()
    service = service_module.SessionService(store, runtime_factory=runtime_factory)
    resume = service.resume

    outcome = resume(session.manifest.session_id, current_repo=git_repo)

    assert isinstance(outcome, service_module.ResumeOutcome)
    assert outcome.session.status is SessionStatus.RUNNING
    assert outcome.runtime == {"runtime": "rebuilt"}
    assert factory_sessions == [session]
    lock_path = tmp_path / "sessions" / session.manifest.session_id / "writer.lock"
    assert lock_path.exists()
    events, _ = store.load_events(session.manifest.session_id)
    assert events[-1].type is AgentEventType.SESSION_RESUMED


def test_successful_resume_lock_is_released_by_pause(
    tmp_path: Path,
    git_repo,
) -> None:
    store = JsonSessionStore(tmp_path / "sessions")
    session = store.create(
        make_session(
            git_repo,
            status=SessionStatus.PAUSED,
            worktree=make_worktree_ref(git_repo),
        )
    )
    service_module = _service_module()
    service = service_module.SessionService(store)
    resume = service.resume
    outcome = resume(session.manifest.session_id, current_repo=git_repo)
    lock_path = tmp_path / "sessions" / session.manifest.session_id / "writer.lock"
    assert lock_path.exists()

    service.pause(outcome.session, reason="done for now")

    assert not lock_path.exists()


def test_concurrent_resume_allows_only_one_writer(
    tmp_path: Path,
    git_repo,
) -> None:
    store = JsonSessionStore(tmp_path / "sessions")
    session = store.create(
        make_session(
            git_repo,
            status=SessionStatus.PAUSED,
            worktree=make_worktree_ref(git_repo),
        )
    )
    service_module = _service_module()
    first = service_module.SessionService(store)
    second = service_module.SessionService(store)
    first_resume = first.resume
    second_resume = second.resume

    first_resume(session.manifest.session_id, current_repo=git_repo)

    with pytest.raises(Exception, match="writer lock|持有"):
        second_resume(session.manifest.session_id, current_repo=git_repo)
