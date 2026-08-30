from __future__ import annotations

import subprocess
from pathlib import Path


def test_stability_script_dry_run_is_complete_and_side_effect_free() -> None:
    root = Path(__file__).resolve().parents[2]
    output = root / "evals/week4/agent_runs/test-dry-run-must-not-exist"

    result = subprocess.run(
        [
            "bash",
            str(root / "scripts/run_single_agent_stability_validation.sh"),
            "--dry-run",
            "--output-root",
            str(output),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("COMMAND ") == 10
    assert result.stdout.count("--task-id F03") == 5
    assert result.stdout.count("--task-id B01") == 2
    assert sum(
        line.startswith("OUTPUT ") and "_11task_" in line
        for line in result.stdout.splitlines()
    ) == 3
    assert "stability_summary.json" in result.stdout
    assert not output.exists()
