from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from codeteam.agent_team.persistence_models import DurableEventDraft
from codeteam.agent_team.session_integration import TeamSessionRuntimeBuilder
from codeteam.agent_team.team_store import SQLiteTeamStateStore
from codeteam.session.errors import SessionAlreadyActiveError
from codeteam.session.service import SessionService
from codeteam.session.store import JsonSessionStore


def _emit(data: dict[str, object]) -> None:
    print(json.dumps(data, sort_keys=True), flush=True)


def resume_hold(sessions_root: Path, repo: Path, session_id: str) -> int:
    store = JsonSessionStore(sessions_root)
    service = SessionService(store, runtime_builder=TeamSessionRuntimeBuilder())
    try:
        outcome = service.resume(session_id, current_repo=repo)
    except SessionAlreadyActiveError:
        _emit({"status": "already_active"})
        return 7
    assert outcome.runtime is not None
    assert outcome.session.team_state is not None
    _emit(
        {
            "status": "resumed",
            "runtime_id": outcome.runtime.coordinator.runtime_id,
            "revision": outcome.session.team_state.acknowledged_revision,
        }
    )
    command = sys.stdin.readline().strip()
    if command != "pause":
        _emit({"status": "invalid_control"})
        return 8
    service.pause(outcome.session, reason="process test release")
    _emit({"status": "paused"})
    return 0


def crash_store_commit(session_dir: Path, session_id: str) -> int:
    store = SQLiteTeamStateStore(session_dir)
    snapshot = store.load(session_id)
    original = store._write_snapshot

    def exit_after_state_write(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)  # type: ignore[arg-type]
        _emit({"status": "inside_transaction"})
        os._exit(91)

    store._write_snapshot = exit_after_state_write  # type: ignore[method-assign]
    store.commit(
        snapshot,
        expected_revision=snapshot.revision,
        events=(DurableEventDraft(event_type="must.rollback"),),
    )
    return 9


def commit_then_exit(session_dir: Path, session_id: str) -> int:
    store = SQLiteTeamStateStore(session_dir)
    snapshot = store.load(session_id)
    committed = store.commit(
        snapshot,
        expected_revision=snapshot.revision,
        events=(DurableEventDraft(event_type="team.committed_before_session"),),
    )
    _emit({"status": "team_committed", "revision": committed.revision})
    os._exit(92)


def dirty_worktree_then_exit(worktree: Path) -> int:
    (worktree / "crash-effect.txt").write_text("partial effect\n", encoding="utf-8")
    _emit({"status": "workspace_mutated"})
    os._exit(93)


def main() -> int:
    action = sys.argv[1]
    if action == "resume-hold":
        return resume_hold(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4])
    if action == "crash-store-commit":
        return crash_store_commit(Path(sys.argv[2]), sys.argv[3])
    if action == "commit-then-exit":
        return commit_then_exit(Path(sys.argv[2]), sys.argv[3])
    if action == "dirty-worktree-then-exit":
        return dirty_worktree_then_exit(Path(sys.argv[2]))
    raise SystemExit(f"unknown action: {action}")


if __name__ == "__main__":
    raise SystemExit(main())
