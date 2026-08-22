import json
import os
import subprocess
import sys
from pathlib import Path


def test_context_command_can_emit_compact_json_without_changing_default() -> None:
    workspace = Path.cwd()
    fixture = workspace / "tests" / "fixtures" / "test_repo"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "codeteam.cli.app",
            "context",
            "AuthService refresh",
            "--path",
            str(fixture),
            "--format",
            "json",
            "--compact-json",
        ],
        cwd=workspace,
        env={**os.environ, "PYTHONPATH": str(workspace)},
        shell=False,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "\n" not in result.stdout.strip()
    payload = json.loads(result.stdout)
    assert payload["query"] == "AuthService refresh"
