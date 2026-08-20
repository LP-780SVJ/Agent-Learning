"""Session lifecycle orchestration for durable pause/resume state."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from codeteam.events import AgentEventType
from codeteam.session.errors import (
    RepositoryMismatchError,
    SessionAlreadyActiveError,
    SessionRecoveryRequiredError,
    SessionTerminalError,
)
from codeteam.session.models import (
    OperationStatus,
    ReconciliationVerdict,
    RepositoryRef,
    Session,
    SessionManifest,
    SessionStatus,
    WorktreeRef,
)
from codeteam.session.store import JsonSessionStore
from codeteam.task.models import TaskSpec

PAUSABLE_STATUSES: frozenset[SessionStatus] = frozenset(
    {
        SessionStatus.CREATED,
        SessionStatus.RUNNING,
        SessionStatus.RECOVERY_REQUIRED,
    }
)

TERMINAL_STATUSES: frozenset[SessionStatus] = frozenset(
    {SessionStatus.COMPLETED, SessionStatus.FAILED}
)

OperationStopper = Callable[[Session], None]
SessionRefresher = Callable[[Session], Session]
RuntimeFactory = Callable[[Session], Any]

_GIT_TIMEOUT_SECONDS = 10.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ReconciliationReport:
    """Result of comparing durable session state with current runtime state."""

    verdict: ReconciliationVerdict
    issues: tuple[str, ...]
    session: Session


@dataclass(frozen=True)
class ResumeOutcome:
    """Successful resume result.

    ``session`` is the newly persisted RUNNING snapshot. ``runtime`` is the
    ephemeral object rebuilt by the injected RuntimeFactory.
    """

    session: Session
    runtime: Any | None


class SessionService:
    """Session lifecycle service: create, pause, resume."""

    def __init__(
        self,
        store: JsonSessionStore,
        *,
        stop_operation: OperationStopper | None = None,
        refresher: SessionRefresher | None = None,
        reconciler: SessionReconciler | None = None,
        runtime_factory: RuntimeFactory | None = None,
    ) -> None:
        self._store = store
        self._stop_operation = stop_operation
        self._refresher = refresher
        self._reconciler = reconciler or SessionReconciler()
        self._runtime_factory = runtime_factory
        self._locks: dict[str, SessionWriterLock] = {}

    def create_session(
        self,
        *,
        task: TaskSpec,
        repo: RepositoryRef,
        provider_id: str,
        model_id: str,
        worktree: WorktreeRef | None = None,
    ) -> Session:
        """Create and persist a new session snapshot plus created event."""

        session_id = f"ses_{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        session = Session(
            manifest=SessionManifest(
                session_id=session_id,
                repo_id=repo.repo_id,
                created_at=now,
                updated_at=now,
            ),
            task=task,
            provider_id=provider_id,
            model_id=model_id,
            repo=repo,
            worktree=worktree,
        )
        self._store.create(session)

        event = self._store.append_event(
            session_id,
            event_type=AgentEventType.SESSION_CREATED,
            state_version=session.manifest.state_version,
            payload={
                "task_id": task.task_id,
                "repo_id": repo.repo_id,
                "provider_id": provider_id,
                "model_id": model_id,
            },
        )
        return session.model_copy(
            update={
                "manifest": session.manifest.model_copy(
                    update={"last_event_seq": event.seq}
                ),
                "status": SessionStatus.CREATED,
            }
        )

    def pause(
        self,
        session: Session,
        *,
        reason: str,
    ) -> Session:
        """Pause a non-terminal session and persist the pause event.

        The order is intentional: stop work, refresh runtime references, save
        PAUSED, append audit event, then release the writer lock.
        """

        if session.status is SessionStatus.PAUSED:
            return session
        if session.status not in PAUSABLE_STATUSES:
            raise SessionTerminalError(
                f"终态 Session 不能 pause: {session.status.value}"
            )

        if self._stop_operation is not None:
            self._stop_operation(session)

        current = session
        if self._refresher is not None:
            current = self._refresher(session)

        persisted = self._store.save(
            current.model_copy(update={"status": SessionStatus.PAUSED})
        )
        event = self._store.append_event(
            persisted.manifest.session_id,
            event_type=AgentEventType.SESSION_PAUSED,
            state_version=persisted.manifest.state_version,
            payload={
                "reason": reason,
                "task_status": persisted.task_status.value,
            },
        )

        lock = self._locks.pop(persisted.manifest.session_id, None)
        if lock is not None:
            lock.release()

        return persisted.model_copy(
            update={
                "manifest": persisted.manifest.model_copy(
                    update={"last_event_seq": event.seq}
                )
            }
        )

    def resume(
        self,
        session_id: str,
        *,
        current_repo: Path,
    ) -> ResumeOutcome:
        """Resume from durable state, never from an old runtime object."""

        session = self._store.load(session_id)

        if session.status in TERMINAL_STATUSES:
            self._store.append_event(
                session_id,
                event_type=AgentEventType.SESSION_RESUME_REJECTED,
                state_version=session.manifest.state_version,
                payload={"reason": "terminal", "status": session.status.value},
            )
            raise SessionTerminalError(
                f"终态 Session 不能 resume: {session.status.value}"
            )

        lock = SessionWriterLock(self._store.session_dir(session_id))
        lock.acquire()
        try:
            report = self._reconciler.reconcile(
                session,
                current_repo=current_repo,
            )

            if report.verdict is ReconciliationVerdict.INVALID:
                self._store.append_event(
                    session_id,
                    event_type=AgentEventType.SESSION_RESUME_REJECTED,
                    state_version=report.session.manifest.state_version,
                    payload={
                        "reason": "invalid",
                        "issues": list(report.issues),
                    },
                )
                raise RepositoryMismatchError("; ".join(report.issues))

            if report.verdict is ReconciliationVerdict.RECOVERY_REQUIRED:
                flagged = report.session.model_copy(
                    update={"status": SessionStatus.RECOVERY_REQUIRED}
                )
                persisted = self._store.save(flagged)
                self._store.append_event(
                    session_id,
                    event_type=AgentEventType.SESSION_RECOVERY_REQUIRED,
                    state_version=persisted.manifest.state_version,
                    payload={"issues": list(report.issues)},
                )
                raise SessionRecoveryRequiredError(report.issues)

            runtime = (
                self._runtime_factory(report.session)
                if self._runtime_factory is not None
                else None
            )
            persisted = self._store.save(
                report.session.model_copy(update={"status": SessionStatus.RUNNING})
            )
            event = self._store.append_event(
                session_id,
                event_type=AgentEventType.SESSION_RESUMED,
                state_version=persisted.manifest.state_version,
                payload={
                    "verdict": report.verdict.value,
                    "task_status": persisted.task_status.value,
                },
            )
        except BaseException:
            lock.release()
            raise

        self._locks[session_id] = lock
        return ResumeOutcome(
            session=persisted.model_copy(
                update={
                    "manifest": persisted.manifest.model_copy(
                        update={"last_event_seq": event.seq}
                    )
                }
            ),
            runtime=runtime,
        )


def _run_git(argv: list[str], *, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    """Run git using project subprocess safety conventions."""

    return subprocess.run(
        ["git", *argv],
        cwd=cwd,
        capture_output=True,
        shell=False,
        timeout=_GIT_TIMEOUT_SECONDS,
        check=False,
    )


def probe_git_common_dir(cwd: Path) -> str:
    result = _run_git(["rev-parse", "--git-common-dir"], cwd=cwd)
    if result.returncode != 0:
        raise RepositoryMismatchError(f"不是 Git 仓库: {cwd}")
    return str((cwd / result.stdout.decode().strip()).resolve())


def probe_head(worktree: Path) -> str | None:
    result = _run_git(["rev-parse", "HEAD"], cwd=worktree)
    if result.returncode != 0:
        return None
    return result.stdout.decode().strip()


def probe_dirty(worktree: Path) -> bool:
    result = _run_git(["status", "--porcelain"], cwd=worktree)
    return bool(result.stdout.decode().strip())


def probe_commit_exists(repo: Path, sha: str) -> bool:
    return (
        _run_git(["cat-file", "-e", f"{sha}^{{commit}}"], cwd=repo).returncode
        == 0
    )


class GitWorktreeRefresher:
    """Refresh persisted worktree facts before pausing."""

    def __call__(self, session: Session) -> Session:
        if session.worktree is None:
            return session
        path = Path(session.worktree.path)
        head = probe_head(path) if path.is_dir() else None
        dirty = (
            probe_dirty(path)
            if path.is_dir()
            else session.worktree.last_known_dirty
        )
        if head is None:
            return session
        return session.model_copy(
            update={
                "worktree": session.worktree.model_copy(
                    update={
                        "last_known_head_sha": head,
                        "last_known_dirty": dirty,
                    }
                )
            }
        )


class SessionReconciler:
    """Compare durable session references against current external state."""

    _SEVERITY: ClassVar[dict[ReconciliationVerdict, int]] = {
        ReconciliationVerdict.RESUMABLE: 0,
        ReconciliationVerdict.RECOVERY_REQUIRED: 1,
        ReconciliationVerdict.INVALID: 2,
    }

    def __init__(
        self,
        *,
        is_provider_available: Callable[[str, str], bool] | None = None,
        list_checkpoint_ids: Callable[[], set[str]] | None = None,
    ) -> None:
        self._is_provider_available = is_provider_available
        self._list_checkpoint_ids = list_checkpoint_ids

    def reconcile(
        self,
        session: Session,
        *,
        current_repo: Path,
    ) -> ReconciliationReport:
        issues: list[tuple[str, ReconciliationVerdict]] = []

        if probe_git_common_dir(current_repo) != session.repo.git_common_dir:
            issues.append(
                (
                    (
                        f"repo_mismatch: {current_repo} != "
                        f"{session.repo.git_common_dir}"
                    ),
                    ReconciliationVerdict.INVALID,
                )
            )
            return self._report(session, issues)

        if not probe_commit_exists(current_repo, session.repo.base_sha):
            issues.append(
                (
                    f"base_missing: {session.repo.base_sha}",
                    ReconciliationVerdict.RECOVERY_REQUIRED,
                )
            )

        session = self._reconcile_worktree(session, issues)
        session = self._reconcile_checkpoints(session, issues)

        if self._is_provider_available is not None and not (
            self._is_provider_available(session.provider_id, session.model_id)
        ):
            issues.append(
                (
                    (
                        f"provider_unavailable: {session.provider_id}/"
                        f"{session.model_id}"
                    ),
                    ReconciliationVerdict.RECOVERY_REQUIRED,
                )
            )

        session = self._reconcile_stale_running(session, issues)

        if (
            session.active_operation is not None
            and session.active_operation.status is OperationStatus.STARTED
        ):
            issues.append(
                (
                    f"inflight_operation: {session.active_operation.kind}",
                    ReconciliationVerdict.RECOVERY_REQUIRED,
                )
            )

        return self._report(session, issues)

    def _reconcile_worktree(
        self,
        session: Session,
        issues: list[tuple[str, ReconciliationVerdict]],
    ) -> Session:
        ref = session.worktree
        if ref is None:
            return session

        path = Path(ref.path)
        if not path.is_dir():
            issues.append(
                (
                    f"worktree_missing: {ref.path}",
                    ReconciliationVerdict.RECOVERY_REQUIRED,
                )
            )
            return session

        head = probe_head(path)
        if head is not None and head != ref.last_known_head_sha:
            issues.append(
                (
                    (
                        f"worktree_head_drift: "
                        f"{ref.last_known_head_sha[:8]}→{head[:8]}"
                    ),
                    ReconciliationVerdict.RECOVERY_REQUIRED,
                )
            )

        dirty = probe_dirty(path)
        if dirty != ref.last_known_dirty:
            issues.append(
                (
                    f"worktree_dirty_drift: {ref.last_known_dirty}→{dirty}",
                    ReconciliationVerdict.RECOVERY_REQUIRED,
                )
            )
        return session

    def _reconcile_checkpoints(
        self,
        session: Session,
        issues: list[tuple[str, ReconciliationVerdict]],
    ) -> Session:
        if self._list_checkpoint_ids is None:
            return session

        available = self._list_checkpoint_ids()
        for checkpoint_id in (*session.checkpoint_ids, session.current_checkpoint_id):
            if checkpoint_id is not None and checkpoint_id not in available:
                issues.append(
                    (
                        f"checkpoint_missing: {checkpoint_id}",
                        ReconciliationVerdict.RECOVERY_REQUIRED,
                    )
                )
        return session

    def _reconcile_stale_running(
        self,
        session: Session,
        issues: list[tuple[str, ReconciliationVerdict]],
    ) -> Session:
        if session.status is not SessionStatus.RUNNING:
            return session

        issues.append(
            (
                "stale_running: 磁盘 RUNNING 且无活跃 writer",
                ReconciliationVerdict.RECOVERY_REQUIRED,
            )
        )
        return session.model_copy(
            update={"status": SessionStatus.RECOVERY_REQUIRED}
        )

    def _report(
        self,
        session: Session,
        issues: list[tuple[str, ReconciliationVerdict]],
    ) -> ReconciliationReport:
        verdict = max(
            (severity for _, severity in issues),
            default=ReconciliationVerdict.RESUMABLE,
            key=lambda item: self._SEVERITY[item],
        )
        return ReconciliationReport(
            verdict=verdict,
            issues=tuple(text for text, _ in issues),
            session=session,
        )


class SessionWriterLock:
    """Single-writer lock stored under one session directory."""

    _LOCK_NAME = "writer.lock"

    def __init__(self, session_dir: Path) -> None:
        self._path = session_dir / self._LOCK_NAME
        self._held = False

    @property
    def held(self) -> bool:
        return self._held

    def acquire(self) -> None:
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "acquired_at": _utc_now().isoformat(),
            }
        ).encode("utf-8")

        for attempt in range(2):
            try:
                fd = os.open(
                    self._path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o644,
                )
            except FileExistsError:
                if attempt == 0 and self._holder_is_dead():
                    self._path.unlink()
                    continue
                raise SessionAlreadyActiveError(
                    f"另一进程持有 writer lock: {self._path}"
                ) from None
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            self._held = True
            return

    def release(self) -> None:
        if self._held:
            self._path.unlink(missing_ok=True)
            self._held = False

    def _holder_is_dead(self) -> bool:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False

        if raw.get("host") != socket.gethostname():
            return False

        pid = raw.get("pid")
        if not isinstance(pid, int):
            return False

        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return False
