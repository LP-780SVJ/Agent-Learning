from __future__ import annotations

import json
import sys
from pathlib import Path

from codeteam.agent_team.persistence_errors import TeamStateConflictError
from codeteam.agent_team.team_store import SQLiteTeamStateStore


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


def claim_once(session_dir: Path, session_id: str) -> int:
    if sys.stdin.readline().strip() != "go":
        _emit({"status": "invalid_control"})
        return 8

    store = SQLiteTeamStateStore(session_dir)
    try:
        committed, claim = store.claim_message(
            session_id,
            recipient_id="worker-1",
            runtime_id=f"runtime-{sys.argv[4]}",
            expected_revision=1,
        )
    except TeamStateConflictError:
        _emit({"status": "conflict"})
        return 7

    assert claim is not None
    _emit(
        {
            "status": "claimed",
            "claim_id": claim.claim_id,
            "revision": committed.revision,
        }
    )
    return 0


def main() -> int:
    if len(sys.argv) != 5 or sys.argv[1] != "claim-once":
        raise SystemExit("usage: claim-once SESSION_DIR SESSION_ID CONTENDER")
    return claim_once(Path(sys.argv[2]), sys.argv[3])


if __name__ == "__main__":
    raise SystemExit(main())
