from __future__ import annotations

import hashlib
import io
import json
import subprocess
import urllib.error
from pathlib import Path

import pytest

from codeteam.cli import agent_eval_command
from codeteam.evaluation.agent_grader import AgentGrader
from codeteam.evaluation.agent_models import (
    AgentEvalSplit,
    AgentEvalTask,
    AgentTaskType,
    EvalRunConfig,
    PatchActorResult,
    PatchActorStatus,
)
from codeteam.evaluation.agent_runner import (
    AgentEvalDatasetError,
    AgentEvalRunner,
    load_agent_eval_tasks,
)
from codeteam.evaluation.patch_actor import (
    LLMPatchGenerator,
    NullPatchGenerator,
    PatchActor,
    extract_unified_diff,
    patch_from_structured_file_edits,
)
from codeteam.task.models import create_task_spec


class StaticPatchGenerator:
    last_input_tokens = 3
    last_output_tokens = 4

    def __init__(self, patch: str) -> None:
        self.patch = patch

    def generate_patch(self, **kwargs) -> str:
        return self.patch


def test_prepare_workspace_applies_verified_setup_patch(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    setup_patch = tmp_path / "setup.diff"
    setup_patch.write_text(
        "diff --git a/app.py b/app.py\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1 +1 @@\n"
        "-VALUE = 1\n"
        "+VALUE = 0\n",
        encoding="utf-8",
    )
    task = AgentEvalTask(
        task_id="T01",
        split=AgentEvalSplit.DEV,
        type=AgentTaskType.BUG,
        difficulty="L1",
        repo_fixture=Path("fixture"),
        base_commit="",
        setup_patch=Path("setup.diff"),
        setup_patch_sha256=hashlib.sha256(setup_patch.read_bytes()).hexdigest(),
        prompt="restore VALUE",
        oracle_review_status="test",
    )
    runner = AgentEvalRunner(
        project_root=tmp_path,
        actor=PatchActor(patch_generator=NullPatchGenerator()),
        keep_workspaces=True,
    )
    destination = tmp_path / "workspace"

    runner._prepare_workspace(task=task, destination=destination)

    assert (destination / "app.py").read_text(encoding="utf-8") == "VALUE = 0\n"
    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=destination,
        capture_output=True,
        text=True,
        check=True,
    )
    assert status.stdout == ""


def test_prepare_workspace_fails_closed_for_missing_base_commit(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    task = AgentEvalTask(
        task_id="T01",
        split=AgentEvalSplit.DEV,
        type=AgentTaskType.BUG,
        difficulty="L1",
        repo_fixture=Path("fixture"),
        base_commit="not-a-real-commit",
        prompt="change VALUE",
        oracle_review_status="test",
    )
    runner = AgentEvalRunner(
        project_root=tmp_path,
        actor=PatchActor(patch_generator=NullPatchGenerator()),
        keep_workspaces=True,
    )

    with pytest.raises(AgentEvalDatasetError, match="Unable to archive base_commit"):
        runner._prepare_workspace(task=task, destination=tmp_path / "workspace")


def test_setup_patch_path_and_hash_must_be_provided_together() -> None:
    with pytest.raises(ValueError, match="must be provided together"):
        AgentEvalTask(
            task_id="T01",
            split=AgentEvalSplit.DEV,
            type=AgentTaskType.BUG,
            difficulty="L1",
            repo_fixture=Path("fixture"),
            base_commit="",
            setup_patch=Path("setup.diff"),
            prompt="change VALUE",
            oracle_review_status="test",
        )


def test_extract_unified_diff_from_markdown_fence() -> None:
    raw = """```diff
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
```"""

    patch = extract_unified_diff(raw)

    assert patch.startswith("diff --git a/app.py b/app.py")
    assert patch.endswith("\n")


def test_structured_file_edits_generate_local_patch(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    raw = json.dumps({"files": [{"path": "app.py", "content": "VALUE = 2\n"}]})

    patch = patch_from_structured_file_edits(raw, workspace_root=tmp_path)

    assert patch is not None
    assert patch.startswith("diff --git a/app.py b/app.py")
    assert "-VALUE = 1" in patch
    assert "+VALUE = 2" in patch


def test_agent_eval_runner_applies_patch_and_grades_hidden_oracle(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    hidden = tmp_path / "hidden" / "T01"
    hidden.mkdir(parents=True)
    (hidden / "test_app.py").write_text(
        "from app import VALUE\n\n"
        "def test_value_changed() -> None:\n"
        "    assert VALUE == 2\n",
        encoding="utf-8",
    )
    suite = tmp_path / "suite.jsonl"
    suite.write_text(
        json.dumps(
            {
                "task_id": "T01",
                "split": "dev",
                "type": "bug",
                "difficulty": "L1",
                "repo_fixture": str(fixture),
                "base_commit": "",
                "prompt": "change VALUE to 2",
                "acceptance_commands": ["{python} -m pytest {hidden_root}/T01 -q"],
                "regression_commands": [],
                "oracle_review_status": "test",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""
    runner = AgentEvalRunner(
        actor=PatchActor(patch_generator=StaticPatchGenerator(patch)),
        grader=AgentGrader(hidden_root=tmp_path / "hidden"),
        keep_workspaces=True,
    )

    results = runner.run_suite(
        tasks=load_agent_eval_tasks(suite),
        config=EvalRunConfig(run_id="test-run"),
        output_dir=tmp_path / "out",
    )

    assert len(results) == 1
    assert results[0].success is True
    assert results[0].pristine_acceptance_passed is False
    assert results[0].changed_files == ("app.py",)
    assert results[0].artifact_paths == (
        "_artifacts/T01/attempt-01/extracted_patch.diff",
    )
    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert summary["success_count"] == 1
    assert summary["pristine_acceptance_passed_count"] == 0
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert manifest["tasks"] == [
        {
            "task_id": "T01",
            "repo_fixture": str(fixture),
            "base_commit": "",
            "setup_patch": None,
            "setup_patch_sha256": None,
            "oracle_review_status": "test",
        }
    ]


def test_null_patch_actor_cannot_pass_even_if_oracle_would_pass(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    hidden = tmp_path / "hidden" / "T01"
    hidden.mkdir(parents=True)
    (hidden / "test_app.py").write_text(
        "from app import VALUE\n\n"
        "def test_baseline_value() -> None:\n"
        "    assert VALUE == 1\n",
        encoding="utf-8",
    )
    task = AgentEvalTask(
        task_id="T01",
        split=AgentEvalSplit.DEV,
        type=AgentTaskType.BUG,
        difficulty="L1",
        repo_fixture=fixture,
        base_commit="",
        prompt="no-op",
        acceptance_commands=("{python} -m pytest {hidden_root}/T01 -q",),
        oracle_review_status="test",
    )
    runner = AgentEvalRunner(
        actor=PatchActor(patch_generator=NullPatchGenerator()),
        grader=AgentGrader(hidden_root=tmp_path / "hidden"),
        keep_workspaces=True,
    )

    results = runner.run_suite(
        tasks=[task],
        config=EvalRunConfig(run_id="null-run"),
        output_dir=tmp_path / "out",
    )

    assert results[0].acceptance_passed is True
    assert results[0].pristine_acceptance_passed is True
    assert results[0].success is False
    assert results[0].failure_category == "no_patch"


def test_pristine_oracle_pass_blocks_completed_actor_success(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    hidden = tmp_path / "hidden" / "T01"
    hidden.mkdir(parents=True)
    (hidden / "test_app.py").write_text(
        "from app import VALUE\n\n"
        "def test_baseline_value() -> None:\n"
        "    assert VALUE == 1\n",
        encoding="utf-8",
    )
    task = AgentEvalTask(
        task_id="T01",
        split=AgentEvalSplit.DEV,
        type=AgentTaskType.BUG,
        difficulty="L1",
        repo_fixture=fixture,
        base_commit="",
        prompt="add a comment",
        acceptance_commands=("{python} -m pytest {hidden_root}/T01 -q",),
        oracle_review_status="test",
    )
    patch = patch_from_structured_file_edits(
        json.dumps(
            {
                "files": [
                    {
                        "path": "app.py",
                        "content": "VALUE = 1\n# comment\n",
                    }
                ]
            }
        ),
        workspace_root=fixture,
    )
    assert patch is not None
    runner = AgentEvalRunner(
        actor=PatchActor(patch_generator=StaticPatchGenerator(patch)),
        grader=AgentGrader(hidden_root=tmp_path / "hidden"),
        keep_workspaces=True,
    )

    results = runner.run_suite(
        tasks=[task],
        config=EvalRunConfig(run_id="oracle-run"),
        output_dir=tmp_path / "out",
    )

    assert results[0].actor_status is PatchActorStatus.COMPLETED
    assert results[0].acceptance_passed is True
    assert results[0].pristine_acceptance_passed is True
    assert results[0].success is False
    assert results[0].failure_category == "oracle_not_discriminative"


def test_grader_filters_runtime_artifacts_from_changed_files(tmp_path: Path) -> None:
    task = AgentEvalTask(
        task_id="T01",
        split=AgentEvalSplit.DEV,
        type=AgentTaskType.BUG,
        difficulty="L1",
        repo_fixture=tmp_path,
        base_commit="",
        prompt="test",
        oracle_review_status="test",
    )
    actor_result = PatchActorResult(
        task_id="T01",
        status=PatchActorStatus.COMPLETED,
        planning_enabled=True,
        repair_enabled=True,
        compaction_mode="structured",
        changed_files=(
            "app.py",
            "src/__pycache__/app.cpython-311.pyc",
            ".pytest_cache/v/cache/nodeids",
        ),
    )

    grade = AgentGrader(hidden_root=tmp_path / "hidden").grade(
        task=task,
        workspace_root=tmp_path,
        actor_result=actor_result,
        config=EvalRunConfig(run_id="filter-run"),
    )

    assert grade.changed_files == ("app.py",)
    assert grade.security_passed is True


def test_llm_patch_generator_records_raw_and_extracted_patch(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    raw = json.dumps({"files": [{"path": "app.py", "content": "VALUE = 2\n"}]})
    generator = LLMPatchGenerator(
        complete=lambda messages: raw,
        model_id="fake",
    )
    task = create_task_spec(
        task_id="T01",
        original_request="change value",
    )

    patch = generator.generate_patch(
        task=task,
        plan=None,
        context=type(
            "Context",
            (),
            {"repo_map": "", "code_context": ()},
        )(),
        workspace_root=tmp_path,
    )

    assert generator.last_raw_output == raw
    assert generator.last_extracted_patch == patch
    assert "+VALUE = 2" in patch


def test_provider_request_retries_retryable_http_errors(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.HTTPError(
                url="https://example.test",
                code=429,
                msg="rate limited",
                hdrs={},
                fp=io.BytesIO(b"slow down"),
            )
        return _FakeResponse(
            b'{"choices":[{"message":{"content":"ok"}}]}'
        )

    monkeypatch.setattr(agent_eval_command.urllib.request, "urlopen", fake_urlopen)

    result = agent_eval_command._chat_completion_request(
        {
            "CODETEAM_LLM_BASE_URL": "https://example.test",
            "CODETEAM_LLM_API_KEY": "key",
            "CODETEAM_LLM_MODEL": "model",
            "CODETEAM_LLM_MAX_ATTEMPTS": "2",
            "CODETEAM_LLM_BACKOFF_SECONDS": "0.01",
        },
        [],
        sleep_func=lambda seconds: None,
    )

    assert result == "ok"
    assert calls["count"] == 2


def test_provider_request_records_non_retryable_auth_error(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            url="https://example.test",
            code=401,
            msg="unauthorized",
            hdrs={},
            fp=io.BytesIO(b"bad key"),
        )

    monkeypatch.setattr(agent_eval_command.urllib.request, "urlopen", fake_urlopen)

    try:
        agent_eval_command._chat_completion_request(
            {
                "CODETEAM_LLM_BASE_URL": "https://example.test",
                "CODETEAM_LLM_API_KEY": "key",
                "CODETEAM_LLM_MODEL": "model",
                "CODETEAM_LLM_MAX_ATTEMPTS": "3",
            },
            [],
            sleep_func=lambda seconds: None,
        )
    except agent_eval_command.ProviderRequestError as error:
        assert len(error.failures) == 1
        assert error.failures[0].category == "auth"
        assert error.failures[0].retryable is False
        assert "attempt 1: auth status=401" in str(error)
    else:
        raise AssertionError("expected ProviderRequestError")


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self.body
