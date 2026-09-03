from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.week5 import smoke_team_runtime


class _Result:
    def __init__(
        self,
        *,
        success: bool,
        failure_category: str | None = None,
        failure_origin: str | None = None,
        error: str | None = None,
    ) -> None:
        self.success = success
        self.failure_category = failure_category
        self.failure_origin = failure_origin
        self.error = error

    def model_dump_json(self, *, indent: int) -> str:
        return json.dumps({"success": self.success}, indent=indent)


def _run_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result_or_error: _Result | BaseException,
) -> tuple[int, dict[str, object]]:
    class FakeRunner:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def run_suite(self, **kwargs: object) -> list[_Result]:
            del kwargs
            if isinstance(result_or_error, BaseException):
                raise result_or_error
            return [result_or_error]

    project_root = Path(__file__).resolve().parents[2]
    output = tmp_path / "smoke"
    monkeypatch.setattr(smoke_team_runtime, "AgentEvalRunner", FakeRunner)
    monkeypatch.setattr(
        smoke_team_runtime,
        "resolve_llm_config",
        lambda path: {
            "CODETEAM_LLM_MODEL": "model-under-test",
            "CODETEAM_LLM_API_KEY": "sk-do-not-persist-12345",
        },
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
    code = smoke_team_runtime.main(
        [
            "--suite",
            str(project_root / "evals/week4/agent_task_suite_v1.jsonl"),
            "--task-id",
            "B01",
            "--output",
            str(output),
        ]
    )
    return code, json.loads(
        (output / "team_smoke_manifest.json").read_text(encoding="utf-8")
    )


def test_successful_smoke_terminalizes_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, manifest = _run_main(tmp_path, monkeypatch, _Result(success=True))

    assert code == 0
    assert manifest["real_llm_result"] == "COMPLETED"
    assert manifest["success"] is True
    assert manifest["finished_at"]
    assert manifest["run_id"]
    assert manifest["task_id"] == "B01"
    assert manifest["artifacts"] == {
        "results": "results.jsonl",
        "summary": "summary.json",
        "runner_manifest": "manifest.json",
    }


def test_failed_smoke_terminalizes_and_redacts_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sk-failed-result-secret-12345"
    code, manifest = _run_main(
        tmp_path,
        monkeypatch,
        _Result(
            success=False,
            failure_category="actor_failed",
            failure_origin="worker",
            error=f"Authorization: Bearer {secret}",
        ),
    )

    assert code == 1
    assert manifest["real_llm_result"] == "FAILED"
    assert manifest["success"] is False
    assert secret not in json.dumps(manifest)
    assert manifest["failure"]["category"] == "actor_failed"


def test_runner_exception_terminalizes_manifest_and_is_reraised(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "credential-runner-exception-12345"

    with pytest.raises(RuntimeError, match=secret):
        _run_main(tmp_path, monkeypatch, RuntimeError(secret))

    manifest = json.loads(
        (tmp_path / "smoke/team_smoke_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["real_llm_result"] == "FAILED"
    assert manifest["failure"]["exception_type"] == "RuntimeError"
    assert secret not in json.dumps(manifest)


def test_atomic_manifest_replace_failure_keeps_previous_valid_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "manifest.json"
    smoke_team_runtime._atomic_write_manifest(
        path,
        {"real_llm_result": "STARTED"},
    )

    def fail_replace(source: Path, target: Path) -> None:
        del source, target
        raise OSError("replace failed")

    monkeypatch.setattr(smoke_team_runtime.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        smoke_team_runtime._atomic_write_manifest(
            path,
            {"real_llm_result": "COMPLETED"},
        )

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "real_llm_result": "STARTED"
    }
    assert tuple(tmp_path.glob("*.tmp")) == ()
