from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from codeteam.agent_team.team_store import SQLiteTeamStateStore

from .team_state_helpers import team_snapshot

TIMEOUT = 10.0


def test_os_exit_inside_store_transaction_leaves_old_state_and_events(
    tmp_path: Path,
) -> None:
    session_dir = tmp_path / "ses_team_test"
    session_dir.mkdir()
    store = SQLiteTeamStateStore(session_dir)
    initial = store.initialize(team_snapshot())

    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.agent_team.team_process_helper",
            "crash-store-commit",
            str(session_dir),
            initial.session_id,
        ],
        capture_output=True,
        text=True,
        shell=False,
        timeout=TIMEOUT,
        check=False,
    )

    assert process.returncode == 91
    assert json.loads(process.stdout)["status"] == "inside_transaction"
    assert "Traceback" not in process.stderr
    reopened = SQLiteTeamStateStore(session_dir)
    assert reopened.load(initial.session_id) == initial
    assert reopened.load_events(initial.session_id) == ()
    assert reopened.integrity_check() == "ok"
