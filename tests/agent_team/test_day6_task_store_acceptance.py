from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from codeteam.agent_team.coordination import TeamStateCoordinator
from codeteam.agent_team.mailbox import AgentMessage, AgentMessageType
from codeteam.agent_team.persistence_errors import (
    TeamRuntimePoisonedError,
    TeamStateCorruptedError,
    TeamStatePathError,
)
from codeteam.agent_team.persistence_models import (
    DurableEventDraft,
    TeamStateSnapshot,
)
from codeteam.agent_team.reconciliation import TeamStateReconciler
from codeteam.agent_team.runtime_factory import TeamRuntimeFactory
from codeteam.agent_team.team_store import (
    TEAM_STATE_DB_FILENAME,
    SQLiteTeamStateStore,
)

from .team_state_helpers import session_for_team, team_snapshot

TIMEOUT = 10.0


def _prepared_runtime(tmp_path: Path):
    session_dir = tmp_path / "ses_team_test"
    session_dir.mkdir(mode=0o700)
    store = SQLiteTeamStateStore(session_dir)
    original = store.initialize(team_snapshot())
    coordinator = TeamStateCoordinator()
    report = TeamStateReconciler().reconcile(
        session=session_for_team(),
        snapshot=original,
        planned_runtime_id=coordinator.runtime_id,
    )
    committed = store.commit(
        report.snapshot,
        expected_revision=original.revision,
        events=(DurableEventDraft(event_type="team.runtime_prepared"),),
    )
    runtime = TeamRuntimeFactory().hydrate(
        snapshot=committed,
        store=store,
        coordinator=coordinator,
    )
    return runtime, store


@pytest.mark.parametrize(
    "component",
    ["scheduler", "registry", "mailbox", "lifecycle"],
)
def test_public_component_reference_cannot_bypass_durable_gateway(
    tmp_path: Path,
    component: str,
) -> None:
    runtime, store = _prepared_runtime(tmp_path)
    persisted_before = store.load(runtime.snapshot.session_id)
    lease = runtime.registry.lease("worker-1")

    if component == "scheduler":
        runtime.scheduler.claim(lease)
    elif component == "registry":
        runtime.registry.heartbeat(lease)
    elif component == "mailbox":
        runtime.mailbox.send(
            AgentMessage(
                message_id="msg-direct-bypass",
                sender_id="lead-1",
                recipient_id="worker-1",
                message_type=AgentMessageType.INFO,
                task_id="task-1",
                correlation_id="corr-direct-bypass",
                payload={"source": "acceptance"},
                created_at=2.0,
            )
        )
    else:
        runtime.lifecycle.stop_worker(lease)

    persisted_after = store.load(runtime.snapshot.session_id)
    assert persisted_after == runtime.snapshot
    assert persisted_after.revision == persisted_before.revision + 1
    assert persisted_after != persisted_before

    if component == "scheduler":
        assert runtime.scheduler.runtime_records == persisted_after.tasks
    elif component == "registry":
        assert (
            runtime.registry.runtime("worker-1").revision
            == persisted_after.workers["worker-1"].revision
        )
    elif component == "mailbox":
        live_messages = runtime.mailbox.export_durable_mailbox_state()["messages"]
        assert live_messages == persisted_after.messages
        assert any(
            item.message.message_id == "msg-direct-bypass"
            for item in persisted_after.messages
        )
    else:
        assert (
            runtime.registry.runtime("worker-1").status
            is persisted_after.workers["worker-1"].status
        )


@pytest.mark.parametrize("method_name", ["restart_worker", "sweep"])
def test_durable_gateway_covers_lifecycle_mutations(
    tmp_path: Path,
    method_name: str,
) -> None:
    runtime, _store = _prepared_runtime(tmp_path)

    assert callable(getattr(runtime, method_name, None)), (
        f"DurableTeamRuntime is missing the {method_name} persistence gateway"
    )


def test_noop_schedule_does_not_advance_durable_revision(tmp_path: Path) -> None:
    runtime, store = _prepared_runtime(tmp_path)
    before = store.load(runtime.snapshot.session_id)

    result = runtime.schedule()

    after = store.load(runtime.snapshot.session_id)
    assert result.scheduled == ()
    assert after == before


def test_commit_failure_poisoning_preserves_last_durable_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, store = _prepared_runtime(tmp_path)
    before = store.load(runtime.snapshot.session_id)

    def fail_commit(*args: object, **kwargs: object) -> TeamStateSnapshot:
        raise TeamStateCorruptedError("injected persistence failure")

    monkeypatch.setattr(store, "commit", fail_commit)
    lease = runtime.registry.lease("worker-1")

    with pytest.raises(TeamStateCorruptedError, match="injected"):
        runtime.claim(lease)

    assert runtime.poisoned is True
    assert store.load(before.session_id) == before
    with pytest.raises(TeamRuntimePoisonedError):
        runtime.schedule()


def test_snapshot_rejects_cycle_before_store_initialization(tmp_path: Path) -> None:
    source = team_snapshot()
    invalid = source.model_copy(
        update={
            "dependencies": {
                "A": frozenset({"B"}),
                "B": frozenset({"A"}),
            }
        }
    )

    session_dir = tmp_path / "ses_team_test"
    session_dir.mkdir()
    store = SQLiteTeamStateStore(session_dir)
    error: Exception | None = None
    try:
        store.initialize(invalid)
    except (ValidationError, TeamStateCorruptedError) as exc:
        error = exc

    assert not store.db_path.exists(), "cyclic DAG was persisted before rejection"
    assert error is not None, "cyclic DAG entered the durable contract"


def test_snapshot_rejects_worker_key_identity_mismatch() -> None:
    source = team_snapshot()
    raw = {
        **source.model_dump(),
        "workers": {"worker-alias": source.workers["worker-1"]},
        "worker_ownership": {"worker-alias": None},
    }

    with pytest.raises(ValidationError, match="identity"):
        TeamStateSnapshot.model_validate(raw)


@pytest.mark.parametrize("claimed_at", [math.nan, math.inf, -math.inf])
def test_snapshot_rejects_non_finite_task_timestamp(claimed_at: float) -> None:
    source = team_snapshot()
    raw = {
        **source.model_dump(),
        "tasks": {
            **source.tasks,
            "A": source.tasks["A"].model_copy(update={"claimed_at": claimed_at}),
        },
    }

    with pytest.raises(ValidationError, match="finite"):
        TeamStateSnapshot.model_validate(raw)


def test_load_detects_event_cursor_and_revision_drift(tmp_path: Path) -> None:
    session_dir = tmp_path / "ses_team_test"
    session_dir.mkdir()
    store = SQLiteTeamStateStore(session_dir)
    initial = store.initialize(team_snapshot())
    committed = store.commit(
        initial,
        expected_revision=1,
        events=(DurableEventDraft(event_type="event.one"),),
    )
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            "UPDATE team_events SET revision = ? WHERE session_id = ? AND seq = ?",
            (999, committed.session_id, 1),
        )

    with pytest.raises(TeamStateCorruptedError, match="event"):
        store.load(committed.session_id)


def test_database_symlink_is_rejected_without_touching_target(tmp_path: Path) -> None:
    session_dir = tmp_path / "sessions" / "ses_team_test"
    session_dir.mkdir(parents=True)
    external = tmp_path / "outside.sqlite3"
    external.write_bytes(b"")
    before_sha = hashlib.sha256(external.read_bytes()).hexdigest()
    (session_dir / TEAM_STATE_DB_FILENAME).symlink_to(external)
    store = SQLiteTeamStateStore(session_dir)

    error: Exception | None = None
    try:
        store.initialize(team_snapshot())
    except Exception as exc:  # noqa: BLE001 - assert exact domain error below.
        error = exc

    after_sha = hashlib.sha256(external.read_bytes()).hexdigest()
    assert after_sha == before_sha, "database symlink target was modified"
    assert isinstance(error, TeamStatePathError)


def _claim_process(session_dir: Path, contender: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.agent_team.day6_acceptance_process_helper",
            "claim-once",
            str(session_dir),
            "ses_team_test",
            contender,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )


def test_two_processes_cannot_claim_the_same_message(tmp_path: Path) -> None:
    session_dir = tmp_path / "ses_team_test"
    session_dir.mkdir()
    store = SQLiteTeamStateStore(session_dir)
    store.initialize(team_snapshot())
    processes = [_claim_process(session_dir, contender) for contender in ("a", "b")]

    for process in processes:
        assert process.stdin is not None
        process.stdin.write("go\n")
        process.stdin.flush()
        process.stdin.close()
        process.stdin = None

    results: list[tuple[int, dict[str, object], str]] = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=TIMEOUT)
        results.append((process.returncode, json.loads(stdout), stderr))

    assert sorted(result[0] for result in results) == [0, 7]
    assert {result[1]["status"] for result in results} == {"claimed", "conflict"}
    assert all("Traceback" not in result[2] for result in results)
    persisted = store.load("ses_team_test")
    assert persisted.revision == 2
    assert len(persisted.messages) == 1
    assert persisted.messages[0].claim_id is not None
