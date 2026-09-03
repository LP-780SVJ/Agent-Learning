from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.week5 import smoke_team_runtime


class _FailedResult:
    success = False

    def model_dump_json(self, *, indent: int) -> str:
        del indent
        return '{"success": false}'


class _FakeRunner:
    def __init__(self, **kwargs: object) -> None:
        del kwargs

    def run_suite(self, **kwargs: object) -> list[_FailedResult]:
        del kwargs
        return [_FailedResult()]


def test_real_smoke_manifest_is_finalized_after_a_failed_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    output = tmp_path / "smoke"
    monkeypatch.setattr(smoke_team_runtime, "AgentEvalRunner", _FakeRunner)
    monkeypatch.setattr(
        smoke_team_runtime,
        "resolve_llm_config",
        lambda path: {"CODETEAM_LLM_MODEL": "model-under-test"},
    )
    monkeypatch.setattr(
        smoke_team_runtime,
        "build_openai_compatible_client",
        lambda config: object(),
    )
    monkeypatch.setattr(
        smoke_team_runtime,
        "CodingAgentRuntime",
        lambda **kwargs: object(),
    )

    return_code = smoke_team_runtime.main(
        [
            "--suite",
            str(project_root / "evals/week4/agent_task_suite_v1.jsonl"),
            "--task-id",
            "B01",
            "--worker-count",
            "1",
            "--max-concurrency",
            "1",
            "--output",
            str(output),
        ]
    )

    manifest = json.loads(
        (output / "team_smoke_manifest.json").read_text(encoding="utf-8")
    )
    assert return_code == 1
    assert manifest["network_call_performed"] is True
    assert manifest["real_llm_result"] == "FAILED"
