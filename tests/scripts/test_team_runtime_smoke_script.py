import json
import subprocess
from pathlib import Path


def test_team_runtime_smoke_dry_run_never_calls_network(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    output = tmp_path / "smoke"
    result = subprocess.run(
        [
            str(project_root / ".venv/bin/python"),
            str(project_root / "evals/week5/smoke_team_runtime.py"),
            "--suite",
            "evals/week4/agent_task_suite_v1.jsonl",
            "--task-id",
            "B01",
            "--runtime",
            "team",
            "--provider",
            "openai-compatible",
            "--plan",
            "deterministic-single-node",
            "--worker-count",
            "1",
            "--max-concurrency",
            "1",
            "--max-steps",
            "20",
            "--max-tool-calls",
            "40",
            "--output",
            str(output),
            "--dry-run",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        shell=False,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads((output / "team_smoke_manifest.json").read_text())
    assert manifest["task_id"] == "B01"
    assert manifest["network_call_performed"] is False
    assert manifest["real_llm_result"] == "NOT_RUN"
    assert manifest["worker"]["identity"]["agent_id"] == "worker-backend-1"
    assert manifest["budget"]["global_max_tool_calls"] == 40
    assert "API_KEY" not in result.stdout


def test_team_runtime_smoke_rejects_multiple_workers_before_api_use(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            str(project_root / ".venv/bin/python"),
            str(project_root / "evals/week5/smoke_team_runtime.py"),
            "--suite",
            "evals/week4/agent_task_suite_v1.jsonl",
            "--worker-count",
            "3",
            "--max-concurrency",
            "3",
            "--output",
            str(tmp_path / "smoke"),
            "--dry-run",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        shell=False,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert "requires worker-count=1" in result.stderr
    assert "Traceback" not in result.stderr
