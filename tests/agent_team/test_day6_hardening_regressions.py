from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from codeteam.agent_team.contracts import RestartOutcome
from codeteam.agent_team.coordination import TeamStateCoordinator
from codeteam.agent_team.lifecycle import AgentLifecycleManager
from codeteam.agent_team.mailbox import AgentMailbox, AgentMessage, AgentMessageType
from codeteam.agent_team.models import AgentInfo
from codeteam.agent_team.persistence_errors import (
    TeamStateCorruptedError,
    TeamStatePathError,
)
from codeteam.agent_team.persistence_models import DurableEventDraft
from codeteam.agent_team.reconciliation import TeamStateReconciler
from codeteam.agent_team.registry import AgentRegistry
from codeteam.agent_team.runtime_factory import DurableTeamRuntime, TeamRuntimeFactory
from codeteam.agent_team.scheduler import TaskScheduler
from codeteam.agent_team.team_store import (
    TEAM_STATE_DB_FILENAME,
    SQLiteTeamStateStore,
)
from codeteam.agent_team.worker import WorkerAgent

from .team_state_helpers import session_for_team, team_snapshot
from .test_team_hydration import prepared_runtime


def test_public_facades_route_mutations_through_durable_runtime(tmp_path: Path) -> None:
    _original, runtime, store = prepared_runtime(tmp_path)
    lease = runtime.registry.lease("worker-1")
    before = runtime.snapshot.revision

    claim = runtime.scheduler.claim(lease)

    assert claim is not None
    assert runtime.snapshot.revision == before + 1
    assert store.load(runtime.snapshot.session_id) == runtime.snapshot

    runtime.registry.heartbeat(lease)
    assert store.load(runtime.snapshot.session_id) == runtime.snapshot

    runtime.mailbox.send(
        AgentMessage(
            message_id="msg-facade",
            sender_id="lead-1",
            recipient_id="worker-1",
            message_type=AgentMessageType.INFO,
            task_id="task-1",
            correlation_id="corr-facade",
            payload={"durable": True},
            created_at=2.0,
        )
    )
    assert store.load(runtime.snapshot.session_id) == runtime.snapshot

    runtime.lifecycle.stop_worker(lease)
    assert store.load(runtime.snapshot.session_id) == runtime.snapshot


def test_nested_public_facades_do_not_expose_raw_components(tmp_path: Path) -> None:
    _original, runtime, _store = prepared_runtime(tmp_path)

    assert not isinstance(runtime.registry, AgentRegistry)
    assert not isinstance(runtime.scheduler, TaskScheduler)
    assert not isinstance(runtime.mailbox, AgentMailbox)
    assert not isinstance(runtime.lifecycle, AgentLifecycleManager)
    assert runtime.scheduler.registry is runtime.registry
    assert runtime.lifecycle.registry is runtime.registry
    assert runtime.lifecycle.scheduler is runtime.scheduler


def test_noop_and_audited_noop_have_distinct_revision_semantics(
    tmp_path: Path,
) -> None:
    _original, runtime, store = prepared_runtime(tmp_path)
    before = runtime.snapshot

    runtime.schedule()
    assert runtime.snapshot == before

    runtime.persist(event_type="team.audit_only", payload={"reason": "evidence"})
    after = store.load(before.session_id)
    assert after.revision == before.revision + 1
    assert after.last_event_seq == before.last_event_seq + 1


def _failed_worker_runtime(
    tmp_path: Path,
    *,
    worker_factory: Callable[[AgentInfo], WorkerAgent] | None = None,
) -> tuple[DurableTeamRuntime, SQLiteTeamStateStore]:
    from codeteam.agent_team.models import AgentStatus

    source = team_snapshot()
    failed_worker = source.workers["worker-1"].model_copy(
        update={
            "status": AgentStatus.FAILED,
            "restart_not_before_utc": None,
        }
    )
    source = source.model_copy(
        update={"workers": {"worker-1": failed_worker}}
    )
    session_dir = tmp_path / "failed-session"
    session_dir.mkdir()
    store = SQLiteTeamStateStore(session_dir)
    initial = store.initialize(source)
    coordinator = TeamStateCoordinator()
    report = TeamStateReconciler().reconcile(
        session=session_for_team(),
        snapshot=initial,
        planned_runtime_id=coordinator.runtime_id,
    )
    prepared = store.commit(report.snapshot, expected_revision=1)
    factory = (
        TeamRuntimeFactory()
        if worker_factory is None
        else TeamRuntimeFactory(worker_factory=worker_factory)
    )
    runtime = factory.hydrate(
        snapshot=prepared,
        store=store,
        coordinator=coordinator,
    )
    return runtime, store


def test_restart_worker_success_is_one_durable_mutation(tmp_path: Path) -> None:
    runtime, store = _failed_worker_runtime(tmp_path)
    lease = runtime.registry.lease("worker-1")
    before = runtime.snapshot

    result = runtime.restart_worker(lease)

    assert result.outcome is RestartOutcome.RESTARTED
    after = store.load(before.session_id)
    assert after == runtime.snapshot
    assert after.revision == before.revision + 1
    assert after.workers["worker-1"].generation == lease.generation + 1


def test_restart_factory_failure_is_durable(tmp_path: Path) -> None:
    calls = 0

    def fail_on_restart(info: AgentInfo) -> WorkerAgent:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("factory failed")
        return WorkerAgent(info)

    runtime, store = _failed_worker_runtime(
        tmp_path,
        worker_factory=fail_on_restart,
    )
    before = runtime.snapshot

    result = runtime.restart_worker(runtime.registry.lease("worker-1"))

    assert result.outcome is RestartOutcome.FACTORY_FAILED
    assert store.load(before.session_id) == runtime.snapshot
    assert runtime.snapshot.revision == before.revision + 1


def test_sweep_restart_is_committed_before_return(tmp_path: Path) -> None:
    runtime, store = _failed_worker_runtime(tmp_path)
    before = runtime.snapshot

    result = runtime.sweep()

    assert result.restarts[0].outcome is RestartOutcome.RESTARTED
    assert runtime.snapshot.revision == before.revision + 1
    assert store.load(before.session_id) == runtime.snapshot


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm"])
def test_sqlite_controlled_path_symlink_is_rejected_before_open(
    tmp_path: Path,
    suffix: str,
) -> None:
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    target = tmp_path / f"outside{suffix or '-db'}"
    original = b"outside-must-not-change"
    target.write_bytes(original)
    (session_dir / f"{TEAM_STATE_DB_FILENAME}{suffix}").symlink_to(target)
    store = SQLiteTeamStateStore(session_dir)

    with pytest.raises(TeamStatePathError, match="symlink"):
        store.initialize(team_snapshot())

    assert target.read_bytes() == original


@pytest.mark.parametrize(
    ("statement", "params"),
    [
        (
            "UPDATE team_events SET seq = 2 WHERE session_id = ? AND seq = 1",
            ("ses_team_test",),
        ),
        (
            "UPDATE team_events SET session_id = 'other' WHERE seq = 1",
            (),
        ),
        (
            "UPDATE team_events SET revision = 99 WHERE seq = 1",
            (),
        ),
    ],
)
def test_load_rejects_event_meta_drift(
    tmp_path: Path,
    statement: str,
    params: tuple[object, ...],
) -> None:
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    store = SQLiteTeamStateStore(session_dir)
    initial = store.initialize(team_snapshot())
    committed = store.commit(
        initial,
        expected_revision=1,
        events=(DurableEventDraft(event_type="event.one"),),
    )
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(statement, params)

    with pytest.raises(TeamStateCorruptedError, match="event"):
        store.load(committed.session_id)


def test_load_rejects_event_revision_regression(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    store = SQLiteTeamStateStore(session_dir)
    initial = store.initialize(team_snapshot())
    second = store.commit(
        initial,
        expected_revision=1,
        events=(DurableEventDraft(event_type="event.one"),),
    )
    third = store.commit(
        second,
        expected_revision=2,
        events=(DurableEventDraft(event_type="event.two"),),
    )
    with sqlite3.connect(store.db_path) as connection:
        connection.execute("UPDATE team_events SET revision = 3 WHERE seq = 1")
        connection.execute("UPDATE team_events SET revision = 2 WHERE seq = 2")

    with pytest.raises(TeamStateCorruptedError, match="backwards"):
        store.load(third.session_id)
