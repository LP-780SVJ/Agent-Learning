"""Normalized SQLite persistence for one Session's Team runtime."""

from __future__ import annotations

import json
import sqlite3
import stat
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from pydantic import ValidationError

from codeteam.agent_team.contracts import LifecyclePolicy
from codeteam.agent_team.dag import TaskNode, TaskStatus
from codeteam.agent_team.mailbox import AgentMessage, AgentMessageType
from codeteam.agent_team.models import (
    AgentIdentity,
    AgentInfo,
    AgentStatus,
    WorkerAssignment,
)
from codeteam.agent_team.persistence_errors import (
    StaleMessageClaimError,
    TeamStateAlreadyExistsError,
    TeamStateConflictError,
    TeamStateCorruptedError,
    TeamStateNotFoundError,
    TeamStatePathError,
    TeamStateSchemaUnsupportedError,
)
from codeteam.agent_team.persistence_models import (
    TEAM_STATE_SCHEMA_VERSION,
    DurableEvent,
    DurableEventDraft,
    DurableMessage,
    DurableMessageState,
    DurableWorkerState,
    MessageClaim,
    TeamStateSnapshot,
)
from codeteam.agent_team.scheduler import TaskRuntimeRecord

TEAM_STATE_DB_FILENAME = "team_state.sqlite3"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class TeamStateStore(Protocol):
    def initialize(self, snapshot: TeamStateSnapshot) -> TeamStateSnapshot: ...

    def load(self, session_id: str) -> TeamStateSnapshot: ...

    def commit(
        self,
        snapshot: TeamStateSnapshot,
        *,
        expected_revision: int,
        events: tuple[DurableEventDraft, ...] = (),
    ) -> TeamStateSnapshot: ...

    def load_events(
        self, session_id: str, *, after_seq: int = 0
    ) -> tuple[DurableEvent, ...]: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS team_meta (
    session_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    previous_runtime_id TEXT,
    mailbox_capacity INTEGER NOT NULL CHECK (mailbox_capacity >= 1),
    max_attempts INTEGER NOT NULL CHECK (max_attempts >= 1),
    lifecycle_policy_json TEXT NOT NULL,
    last_event_seq INTEGER NOT NULL CHECK (last_event_seq >= 0),
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_nodes (
    node_id TEXT PRIMARY KEY,
    assignment_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dag_edges (
    prerequisite_id TEXT NOT NULL,
    dependent_id TEXT NOT NULL,
    PRIMARY KEY (prerequisite_id, dependent_id),
    FOREIGN KEY (prerequisite_id) REFERENCES task_nodes(node_id),
    FOREIGN KEY (dependent_id) REFERENCES task_nodes(node_id)
);
CREATE TABLE IF NOT EXISTS task_runtime (
    node_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    owner_id TEXT,
    owner_generation INTEGER,
    attempt INTEGER NOT NULL,
    failure_reason TEXT,
    claimed_at REAL,
    FOREIGN KEY (node_id) REFERENCES task_nodes(node_id)
);
CREATE TABLE IF NOT EXISTS workers (
    worker_id TEXT PRIMARY KEY,
    info_json TEXT NOT NULL,
    status TEXT NOT NULL,
    generation INTEGER NOT NULL,
    revision INTEGER NOT NULL,
    restart_attempts INTEGER NOT NULL,
    restart_not_before_utc TEXT
);
CREATE TABLE IF NOT EXISTS ready_queue (
    position INTEGER PRIMARY KEY,
    node_id TEXT NOT NULL UNIQUE,
    FOREIGN KEY (node_id) REFERENCES task_runtime(node_id)
);
CREATE TABLE IF NOT EXISTS waiting_tasks (
    node_id TEXT PRIMARY KEY,
    FOREIGN KEY (node_id) REFERENCES task_runtime(node_id)
);
CREATE TABLE IF NOT EXISTS worker_ownership (
    worker_id TEXT PRIMARY KEY,
    node_id TEXT UNIQUE,
    FOREIGN KEY (worker_id) REFERENCES workers(worker_id),
    FOREIGN KEY (node_id) REFERENCES task_runtime(node_id)
);
CREATE TABLE IF NOT EXISTS mailbox_agents (
    agent_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    sender_id TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    message_type TEXT NOT NULL,
    task_id TEXT NOT NULL,
    node_id TEXT,
    correlation_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    state TEXT NOT NULL,
    enqueue_seq INTEGER NOT NULL UNIQUE,
    delivery_attempt INTEGER NOT NULL,
    claimed_by_runtime_id TEXT,
    claim_id TEXT,
    FOREIGN KEY (sender_id) REFERENCES mailbox_agents(agent_id),
    FOREIGN KEY (recipient_id) REFERENCES mailbox_agents(agent_id)
);
CREATE INDEX IF NOT EXISTS messages_recipient_order
ON messages(recipient_id, state, enqueue_seq);
CREATE TABLE IF NOT EXISTS seen_message_ids (
    message_id TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS team_events (
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    revision INTEGER NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (session_id, seq),
    FOREIGN KEY (session_id) REFERENCES team_meta(session_id)
);
"""


class SQLiteTeamStateStore:
    """A single-session normalized SQLite Store in a protected Session directory."""

    def __init__(self, session_dir: Path | str) -> None:
        self._session_dir = Path(session_dir)
        if (
            not self._session_dir.is_dir()
            or self._session_dir.is_symlink()
            or self._session_dir.name in {"", ".", ".."}
        ):
            raise TeamStatePathError(
                f"Team database requires a real Session directory: {session_dir}"
            )
        self._session_dir.chmod(0o700)
        self._db_path = self._session_dir / TEAM_STATE_DB_FILENAME

    @property
    def db_path(self) -> Path:
        return self._db_path

    def initialize(self, snapshot: TeamStateSnapshot) -> TeamStateSnapshot:
        snapshot = TeamStateSnapshot.model_validate(snapshot.model_dump())
        if snapshot.schema_version != TEAM_STATE_SCHEMA_VERSION:
            raise TeamStateSchemaUnsupportedError(str(snapshot.schema_version))
        if snapshot.revision != 1 or snapshot.last_event_seq != 0:
            raise ValueError("initial Team snapshot must be revision=1 with no events")
        try:
            with closing(self._connect(create=True)) as connection:
                self._initialize_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute("SELECT 1 FROM team_meta").fetchone() is not None:
                    raise TeamStateAlreadyExistsError(snapshot.session_id)
                self._write_snapshot(connection, snapshot, insert_meta=True)
                connection.commit()
        except TeamStateAlreadyExistsError:
            raise
        except (sqlite3.DatabaseError, OSError) as exc:
            raise TeamStateCorruptedError("unable to initialize Team database") from exc
        self._secure_database_files()
        return snapshot.model_copy(deep=True)

    def load(self, session_id: str) -> TeamStateSnapshot:
        self._reject_controlled_file_symlinks()
        if not self._db_path.is_file():
            raise TeamStateNotFoundError(session_id)
        try:
            with closing(self._connect(create=False)) as connection:
                self._require_schema(connection)
                return self._load_snapshot(connection, session_id)
        except (
            TeamStateNotFoundError,
            TeamStateSchemaUnsupportedError,
            TeamStateCorruptedError,
        ):
            raise
        except (sqlite3.DatabaseError, OSError, ValidationError, ValueError) as exc:
            raise TeamStateCorruptedError("unable to load Team state") from exc

    def commit(
        self,
        snapshot: TeamStateSnapshot,
        *,
        expected_revision: int,
        events: tuple[DurableEventDraft, ...] = (),
    ) -> TeamStateSnapshot:
        snapshot = TeamStateSnapshot.model_validate(snapshot.model_dump())
        drafts = tuple(
            DurableEventDraft.model_validate(event.model_dump()) for event in events
        )
        if snapshot.revision != expected_revision:
            raise TeamStateConflictError(
                "snapshot revision must equal expected_revision before commit"
            )
        try:
            with closing(self._connect(create=False)) as connection:
                self._require_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                current = self._load_snapshot(connection, snapshot.session_id)
                if current.revision != expected_revision:
                    raise TeamStateConflictError(
                        f"expected revision {expected_revision}, got {current.revision}"
                    )
                committed = self._commit_snapshot(connection, snapshot, drafts)
                connection.commit()
        except (TeamStateConflictError, TeamStateNotFoundError):
            raise
        except (sqlite3.DatabaseError, OSError, ValidationError, ValueError) as exc:
            raise TeamStateCorruptedError("Team commit failed") from exc
        self._secure_database_files()
        return committed

    def load_events(
        self, session_id: str, *, after_seq: int = 0
    ) -> tuple[DurableEvent, ...]:
        self._reject_controlled_file_symlinks()
        if after_seq < 0:
            raise ValueError("after_seq must be >= 0")
        if not self._db_path.is_file():
            raise TeamStateNotFoundError(session_id)
        try:
            with closing(self._connect(create=False)) as connection:
                self._require_schema(connection)
                self._load_snapshot(connection, session_id)
                rows = connection.execute(
                    "SELECT * FROM team_events WHERE session_id = ? AND seq > ? "
                    "ORDER BY seq",
                    (session_id, after_seq),
                ).fetchall()
                return tuple(self._event_from_row(row) for row in rows)
        except (TeamStateSchemaUnsupportedError, TeamStateCorruptedError):
            raise
        except (sqlite3.DatabaseError, OSError, ValidationError, ValueError) as exc:
            raise TeamStateCorruptedError("unable to load Team events") from exc

    def claim_message(
        self,
        session_id: str,
        *,
        recipient_id: str,
        runtime_id: str,
        expected_revision: int,
    ) -> tuple[TeamStateSnapshot, MessageClaim | None]:
        if not recipient_id.strip() or not runtime_id.strip():
            raise ValueError("recipient_id and runtime_id must not be blank")
        try:
            with closing(self._connect(create=False)) as connection:
                self._require_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                current = self._load_snapshot(connection, session_id)
                self._require_revision(current, expected_revision)
                candidate = next(
                    (
                        item
                        for item in sorted(
                            current.messages, key=lambda item: item.enqueue_seq
                        )
                        if item.message.recipient_id == recipient_id
                        and item.state is DurableMessageState.PENDING
                    ),
                    None,
                )
                if candidate is None:
                    connection.rollback()
                    return current, None
                claim_id = f"mclaim-{uuid4().hex}"
                claimed = candidate.model_copy(
                    update={
                        "state": DurableMessageState.IN_FLIGHT,
                        "delivery_attempt": candidate.delivery_attempt + 1,
                        "claimed_by_runtime_id": runtime_id,
                        "claim_id": claim_id,
                    }
                )
                messages = tuple(
                    claimed if item.message.message_id == claimed.message.message_id else item
                    for item in current.messages
                )
                draft = current.model_copy(update={"messages": messages})
                committed = self._commit_snapshot(
                    connection,
                    draft,
                    (
                        DurableEventDraft(
                            event_type="mailbox.message_claimed",
                            payload={
                                "message_id": claimed.message.message_id,
                                "recipient_id": recipient_id,
                                "runtime_id": runtime_id,
                                "claim_id": claim_id,
                                "delivery_attempt": claimed.delivery_attempt,
                            },
                        ),
                    ),
                )
                connection.commit()
        except (TeamStateConflictError, TeamStateNotFoundError):
            raise
        except (sqlite3.DatabaseError, OSError, ValidationError, ValueError) as exc:
            raise TeamStateCorruptedError("message claim failed") from exc
        return committed, MessageClaim(
            message=claimed.message,
            claim_id=claim_id,
            runtime_id=runtime_id,
            delivery_attempt=claimed.delivery_attempt,
            revision=committed.revision,
        )

    def ack_message(
        self,
        session_id: str,
        claim: MessageClaim,
        *,
        expected_revision: int,
    ) -> TeamStateSnapshot:
        claim = MessageClaim.model_validate(claim.model_dump())
        try:
            with closing(self._connect(create=False)) as connection:
                self._require_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                current = self._load_snapshot(connection, session_id)
                self._require_revision(current, expected_revision)
                durable = next(
                    (
                        item
                        for item in current.messages
                        if item.message.message_id == claim.message.message_id
                    ),
                    None,
                )
                if (
                    durable is None
                    or durable.state is not DurableMessageState.IN_FLIGHT
                    or durable.claim_id != claim.claim_id
                    or durable.claimed_by_runtime_id != claim.runtime_id
                    or durable.delivery_attempt != claim.delivery_attempt
                ):
                    raise StaleMessageClaimError(claim.claim_id)
                draft = current.model_copy(
                    update={
                        "messages": tuple(
                            item
                            for item in current.messages
                            if item.message.message_id != claim.message.message_id
                        )
                    }
                )
                committed = self._commit_snapshot(
                    connection,
                    draft,
                    (
                        DurableEventDraft(
                            event_type="mailbox.message_acked",
                            payload={
                                "message_id": claim.message.message_id,
                                "claim_id": claim.claim_id,
                                "runtime_id": claim.runtime_id,
                            },
                        ),
                    ),
                )
                connection.commit()
        except (
            StaleMessageClaimError,
            TeamStateConflictError,
            TeamStateNotFoundError,
        ):
            raise
        except (sqlite3.DatabaseError, OSError, ValidationError, ValueError) as exc:
            raise TeamStateCorruptedError("message acknowledgement failed") from exc
        return committed

    def release_message(
        self,
        session_id: str,
        claim: MessageClaim,
        *,
        expected_revision: int,
    ) -> TeamStateSnapshot:
        """Return a matching in-flight message to PENDING without losing its attempt."""
        claim = MessageClaim.model_validate(claim.model_dump())
        current = self.load(session_id)
        self._require_revision(current, expected_revision)
        durable = next(
            (
                item
                for item in current.messages
                if item.message.message_id == claim.message.message_id
            ),
            None,
        )
        if (
            durable is None
            or durable.state is not DurableMessageState.IN_FLIGHT
            or durable.claim_id != claim.claim_id
            or durable.claimed_by_runtime_id != claim.runtime_id
            or durable.delivery_attempt != claim.delivery_attempt
        ):
            raise StaleMessageClaimError(claim.claim_id)
        released = durable.model_copy(
            update={
                "state": DurableMessageState.PENDING,
                "claim_id": None,
                "claimed_by_runtime_id": None,
            }
        )
        draft = current.model_copy(
            update={
                "messages": tuple(
                    released
                    if item.message.message_id == released.message.message_id
                    else item
                    for item in current.messages
                )
            }
        )
        return self.commit(
            draft,
            expected_revision=expected_revision,
            events=(
                DurableEventDraft(
                    event_type="mailbox.message_released",
                    payload={
                        "message_id": claim.message.message_id,
                        "claim_id": claim.claim_id,
                    },
                ),
            ),
        )

    def integrity_check(self) -> str:
        self._reject_controlled_file_symlinks()
        if not self._db_path.is_file():
            raise TeamStateNotFoundError(str(self._db_path))
        with closing(self._connect(create=False)) as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        return str(row[0])

    def _connect(self, *, create: bool) -> sqlite3.Connection:
        self._reject_controlled_file_symlinks()
        if not create and not self._db_path.is_file():
            raise TeamStateNotFoundError(str(self._db_path))
        connection = sqlite3.connect(
            self._db_path,
            timeout=5.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize_schema(self, connection: sqlite3.Connection) -> None:
        current = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if current not in {0, TEAM_STATE_SCHEMA_VERSION}:
            raise TeamStateSchemaUnsupportedError(str(current))
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.executescript(_SCHEMA)
        connection.execute(f"PRAGMA user_version = {TEAM_STATE_SCHEMA_VERSION}")

    def _require_schema(self, connection: sqlite3.Connection) -> None:
        current = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if current != TEAM_STATE_SCHEMA_VERSION:
            raise TeamStateSchemaUnsupportedError(str(current))
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        required = {
            "team_meta",
            "task_nodes",
            "dag_edges",
            "task_runtime",
            "workers",
            "ready_queue",
            "waiting_tasks",
            "worker_ownership",
            "mailbox_agents",
            "messages",
            "seen_message_ids",
            "team_events",
        }
        if not required <= tables:
            raise TeamStateCorruptedError("Team database schema is incomplete")

    def _commit_snapshot(
        self,
        connection: sqlite3.Connection,
        snapshot: TeamStateSnapshot,
        drafts: tuple[DurableEventDraft, ...],
    ) -> TeamStateSnapshot:
        now = _utc_now()
        next_revision = snapshot.revision + 1
        next_seq = snapshot.last_event_seq
        events: list[DurableEvent] = []
        for draft in drafts:
            next_seq += 1
            events.append(
                DurableEvent(
                    event_id=f"team-event-{uuid4().hex}",
                    session_id=snapshot.session_id,
                    seq=next_seq,
                    revision=next_revision,
                    event_type=draft.event_type,
                    timestamp=now,
                    payload=draft.payload,
                )
            )
        committed = snapshot.model_copy(
            update={
                "revision": next_revision,
                "last_event_seq": next_seq,
                "updated_at": now,
            }
        )
        committed = TeamStateSnapshot.model_validate(committed.model_dump())
        self._write_snapshot(connection, committed, insert_meta=False)
        connection.executemany(
            "INSERT INTO team_events VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    event.session_id,
                    event.seq,
                    event.revision,
                    event.event_id,
                    event.event_type,
                    event.timestamp.isoformat(),
                    json.dumps(event.payload, sort_keys=True),
                )
                for event in events
            ],
        )
        return committed

    def _write_snapshot(
        self,
        connection: sqlite3.Connection,
        snapshot: TeamStateSnapshot,
        *,
        insert_meta: bool,
    ) -> None:
        if insert_meta:
            connection.execute(
                "INSERT INTO team_meta VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._meta_values(snapshot),
            )
        else:
            cursor = connection.execute(
                "UPDATE team_meta SET schema_version=?, revision=?, "
                "previous_runtime_id=?, mailbox_capacity=?, max_attempts=?, lifecycle_policy_json=?, "
                "last_event_seq=?, updated_at=? WHERE session_id=? AND revision=?",
                (
                    snapshot.schema_version,
                    snapshot.revision,
                    snapshot.previous_runtime_id,
                    snapshot.mailbox_capacity,
                    snapshot.max_attempts,
                    snapshot.lifecycle_policy.model_dump_json(),
                    snapshot.last_event_seq,
                    snapshot.updated_at.isoformat(),
                    snapshot.session_id,
                    snapshot.revision - 1,
                ),
            )
            if cursor.rowcount != 1:
                raise TeamStateConflictError("Team meta revision changed during commit")

        for table in (
            "dag_edges",
            "ready_queue",
            "waiting_tasks",
            "worker_ownership",
            "messages",
            "seen_message_ids",
            "task_runtime",
            "task_nodes",
            "workers",
            "mailbox_agents",
        ):
            connection.execute(f"DELETE FROM {table}")

        connection.executemany(
            "INSERT INTO task_nodes VALUES (?, ?)",
            [
                (node.node_id, node.assignment.model_dump_json())
                for node in snapshot.dag_nodes
            ],
        )
        connection.executemany(
            "INSERT INTO dag_edges VALUES (?, ?)",
            [
                (prerequisite, dependent)
                for dependent, prerequisites in snapshot.dependencies.items()
                for prerequisite in sorted(prerequisites)
            ],
        )
        connection.executemany(
            "INSERT INTO task_runtime VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    record.node_id,
                    record.status.value,
                    record.owner_id,
                    record.owner_generation,
                    record.attempt,
                    record.failure_reason,
                    record.claimed_at,
                )
                for record in snapshot.tasks.values()
            ],
        )
        connection.executemany(
            "INSERT INTO workers VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    worker_id,
                    worker.info.model_dump_json(),
                    worker.status.value,
                    worker.generation,
                    worker.revision,
                    worker.restart_attempts,
                    worker.restart_not_before_utc.isoformat()
                    if worker.restart_not_before_utc is not None
                    else None,
                )
                for worker_id, worker in snapshot.workers.items()
            ],
        )
        connection.executemany(
            "INSERT INTO ready_queue VALUES (?, ?)",
            [(position, node_id) for position, node_id in enumerate(snapshot.ready_queue)],
        )
        connection.executemany(
            "INSERT INTO waiting_tasks VALUES (?)",
            [(node_id,) for node_id in sorted(snapshot.waiting_for_worker)],
        )
        connection.executemany(
            "INSERT INTO worker_ownership VALUES (?, ?)",
            sorted(snapshot.worker_ownership.items()),
        )
        connection.executemany(
            "INSERT INTO mailbox_agents VALUES (?, ?)",
            [
                (identity.agent_id, identity.display_name)
                for identity in snapshot.mailbox_agents
            ],
        )
        connection.executemany(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [self._message_values(item) for item in snapshot.messages],
        )
        connection.executemany(
            "INSERT INTO seen_message_ids VALUES (?)",
            [(message_id,) for message_id in sorted(snapshot.seen_message_ids)],
        )

    def _load_snapshot(
        self, connection: sqlite3.Connection, session_id: str
    ) -> TeamStateSnapshot:
        meta = connection.execute(
            "SELECT * FROM team_meta WHERE session_id = ?", (session_id,)
        ).fetchone()
        if meta is None:
            raise TeamStateNotFoundError(session_id)
        if int(meta["schema_version"]) != TEAM_STATE_SCHEMA_VERSION:
            raise TeamStateSchemaUnsupportedError(str(meta["schema_version"]))

        node_rows = connection.execute(
            "SELECT * FROM task_nodes ORDER BY node_id"
        ).fetchall()
        nodes = tuple(
            TaskNode(
                node_id=row["node_id"],
                assignment=WorkerAssignment.model_validate_json(
                    row["assignment_json"]
                ),
            )
            for row in node_rows
        )
        dependencies: dict[str, set[str]] = {
            node.node_id: set() for node in nodes
        }
        for row in connection.execute(
            "SELECT * FROM dag_edges ORDER BY dependent_id, prerequisite_id"
        ).fetchall():
            dependencies[row["dependent_id"]].add(row["prerequisite_id"])
        tasks = {
            row["node_id"]: TaskRuntimeRecord(
                node_id=row["node_id"],
                status=TaskStatus(row["status"]),
                owner_id=row["owner_id"],
                owner_generation=row["owner_generation"],
                attempt=row["attempt"],
                failure_reason=row["failure_reason"],
                claimed_at=row["claimed_at"],
            )
            for row in connection.execute(
                "SELECT * FROM task_runtime ORDER BY node_id"
            ).fetchall()
        }
        workers = {
            row["worker_id"]: DurableWorkerState(
                info=AgentInfo.model_validate_json(row["info_json"]),
                status=AgentStatus(row["status"]),
                generation=row["generation"],
                revision=row["revision"],
                restart_attempts=row["restart_attempts"],
                restart_not_before_utc=datetime.fromisoformat(
                    row["restart_not_before_utc"]
                )
                if row["restart_not_before_utc"] is not None
                else None,
            )
            for row in connection.execute("SELECT * FROM workers ORDER BY worker_id")
        }
        ready_queue = tuple(
            row["node_id"]
            for row in connection.execute(
                "SELECT node_id FROM ready_queue ORDER BY position"
            ).fetchall()
        )
        waiting = frozenset(
            row["node_id"]
            for row in connection.execute("SELECT node_id FROM waiting_tasks")
        )
        ownership = {
            row["worker_id"]: row["node_id"]
            for row in connection.execute(
                "SELECT * FROM worker_ownership ORDER BY worker_id"
            ).fetchall()
        }
        agents = tuple(
            AgentIdentity(agent_id=row["agent_id"], display_name=row["display_name"])
            for row in connection.execute(
                "SELECT * FROM mailbox_agents ORDER BY agent_id"
            ).fetchall()
        )
        messages = tuple(
            self._message_from_row(row)
            for row in connection.execute(
                "SELECT * FROM messages ORDER BY enqueue_seq"
            ).fetchall()
        )
        seen = frozenset(
            row["message_id"]
            for row in connection.execute("SELECT * FROM seen_message_ids").fetchall()
        )
        snapshot = TeamStateSnapshot(
            schema_version=meta["schema_version"],
            session_id=meta["session_id"],
            revision=meta["revision"],
            previous_runtime_id=meta["previous_runtime_id"],
            dag_nodes=nodes,
            dependencies={key: frozenset(value) for key, value in dependencies.items()},
            tasks=tasks,
            workers=workers,
            ready_queue=ready_queue,
            waiting_for_worker=waiting,
            worker_ownership=ownership,
            mailbox_agents=agents,
            messages=messages,
            seen_message_ids=seen,
            mailbox_capacity=meta["mailbox_capacity"],
            max_attempts=meta["max_attempts"],
            lifecycle_policy=LifecyclePolicy.model_validate_json(
                meta["lifecycle_policy_json"]
            ),
            last_event_seq=meta["last_event_seq"],
            updated_at=datetime.fromisoformat(meta["updated_at"]),
        )
        self._validate_event_history(connection, snapshot)
        return snapshot

    def _validate_event_history(
        self,
        connection: sqlite3.Connection,
        snapshot: TeamStateSnapshot,
    ) -> None:
        rows = connection.execute(
            "SELECT session_id, seq, revision FROM team_events ORDER BY seq"
        ).fetchall()
        expected_seq = 1
        previous_revision = 0
        for row in rows:
            session_id = str(row["session_id"])
            seq = int(row["seq"])
            revision = int(row["revision"])
            if session_id != snapshot.session_id:
                raise TeamStateCorruptedError(
                    "event session_id does not match Team metadata"
                )
            if seq != expected_seq:
                raise TeamStateCorruptedError(
                    "event sequence is not unique and contiguous"
                )
            if revision < 1 or revision > snapshot.revision:
                raise TeamStateCorruptedError(
                    "event revision is outside the Team snapshot revision"
                )
            if revision < previous_revision:
                raise TeamStateCorruptedError(
                    "event revisions move backwards in sequence order"
                )
            expected_seq += 1
            previous_revision = revision
        if expected_seq - 1 != snapshot.last_event_seq:
            raise TeamStateCorruptedError(
                "event history does not match last_event_seq metadata"
            )

    def _message_from_row(self, row: sqlite3.Row) -> DurableMessage:
        return DurableMessage(
            message=AgentMessage(
                message_id=row["message_id"],
                sender_id=row["sender_id"],
                recipient_id=row["recipient_id"],
                message_type=AgentMessageType(row["message_type"]),
                task_id=row["task_id"],
                node_id=row["node_id"],
                correlation_id=row["correlation_id"],
                payload=json.loads(row["payload_json"]),
                created_at=row["created_at"],
            ),
            state=DurableMessageState(row["state"]),
            enqueue_seq=row["enqueue_seq"],
            delivery_attempt=row["delivery_attempt"],
            claimed_by_runtime_id=row["claimed_by_runtime_id"],
            claim_id=row["claim_id"],
        )

    def _message_values(self, durable: DurableMessage) -> tuple[object, ...]:
        message = durable.message
        return (
            message.message_id,
            message.sender_id,
            message.recipient_id,
            message.message_type.value,
            message.task_id,
            message.node_id,
            message.correlation_id,
            json.dumps(message.payload, sort_keys=True),
            message.created_at,
            durable.state.value,
            durable.enqueue_seq,
            durable.delivery_attempt,
            durable.claimed_by_runtime_id,
            durable.claim_id,
        )

    def _event_from_row(self, row: sqlite3.Row) -> DurableEvent:
        return DurableEvent(
            event_id=row["event_id"],
            session_id=row["session_id"],
            seq=row["seq"],
            revision=row["revision"],
            event_type=row["event_type"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            payload=json.loads(row["payload_json"]),
        )

    def _meta_values(self, snapshot: TeamStateSnapshot) -> tuple[object, ...]:
        return (
            snapshot.session_id,
            snapshot.schema_version,
            snapshot.revision,
            snapshot.previous_runtime_id,
            snapshot.mailbox_capacity,
            snapshot.max_attempts,
            snapshot.lifecycle_policy.model_dump_json(),
            snapshot.last_event_seq,
            snapshot.updated_at.isoformat(),
        )

    def _require_revision(
        self, snapshot: TeamStateSnapshot, expected_revision: int
    ) -> None:
        if snapshot.revision != expected_revision:
            raise TeamStateConflictError(
                f"expected revision {expected_revision}, got {snapshot.revision}"
            )

    def _secure_database_files(self) -> None:
        for path in self._session_dir.glob(f"{TEAM_STATE_DB_FILENAME}*"):
            if path.is_file() and not path.is_symlink():
                path.chmod(0o600)

    def _reject_controlled_file_symlinks(self) -> None:
        """Reject DB and SQLite sidecar symlinks before SQLite opens a path.

        This narrows the local path boundary but cannot remove the lstat/open
        TOCTOU window; kernel-backed directory handles would be needed for that.
        """
        for suffix in ("", "-wal", "-shm", "-journal"):
            path = Path(f"{self._db_path}{suffix}")
            try:
                mode = path.lstat().st_mode
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(mode):
                raise TeamStatePathError(
                    f"Team database controlled path must not be a symlink: {path}"
                )
