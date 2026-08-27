from __future__ import annotations

import hashlib
import io
import json
import subprocess
import urllib.error
from pathlib import Path

import pytest

from codeteam.agent.runtime import CodingAgentRuntime
from codeteam.agent.runtime_models import (
    CodingAgentRunRequest,
    CodingAgentRunResult,
    RuntimeStatus,
)
from codeteam.cli import agent_eval_command, run_command
from codeteam.evaluation.agent_grader import AgentGrader
from codeteam.evaluation.agent_models import (
    AgentEvalSplit,
    AgentEvalTask,
    AgentEvalTaskResult,
    AgentTaskType,
    EvalRunConfig,
    EvalRunMode,
    PatchActorResult,
    PatchActorStatus,
)
from codeteam.evaluation.agent_runner import (
    AgentEvalDatasetError,
    AgentEvalRunner,
    _visible_verification_argv,
    load_agent_eval_tasks,
    summarize_agent_eval_results,
)
from codeteam.evaluation.patch_actor import (
    LLMPatchGenerator,
    extract_unified_diff,
    patch_from_structured_file_edits,
)
from codeteam.git.workspace import GitWorkspace
from codeteam.schemas.messages import Message
from codeteam.task.models import create_task_spec


class FakeRuntime:
    def __init__(self, patch: str | None = None) -> None:
        self.patch = patch
        self.requests: list[CodingAgentRunRequest] = []

    def run(self, request) -> CodingAgentRunResult:
        self.requests.append(request)
        if self.patch is None:
            return CodingAgentRunResult(
                task_id=request.task_id,
                status=RuntimeStatus.FAILED,
                summary="no patch",
                workspace_root=request.workspace_root,
                failure_category="no_patch",
                error="no patch",
            )
        applied = GitWorkspace(request.workspace_root).apply_patch(self.patch)
        assert applied.applied
        return CodingAgentRunResult(
            task_id=request.task_id,
            status=RuntimeStatus.COMPLETED,
            summary="done",
            workspace_root=request.workspace_root,
            diff=self.patch,
            changed_files=tuple(applied.affected_paths),
        )


class EnvironmentBlockedRuntime:
    def run(self, request) -> CodingAgentRunResult:
        return CodingAgentRunResult(
            task_id=request.task_id,
            status=RuntimeStatus.PAUSED,
            summary="sandbox unavailable",
            workspace_root=request.workspace_root,
            failure_category="sandbox_unavailable",
            error="bind source path does not exist",
            sandbox_preflight_available=False,
            sandbox_preflight_category="workspace_mount_unavailable",
        )


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
        runtime=FakeRuntime(),
        keep_workspaces=True,
        worktree_root=tmp_path / "worktrees",
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


def test_eval_separates_execution_root_and_reports_environment_block(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    worktree_base = tmp_path / "worktree-base"
    output = tmp_path / "results"
    task = AgentEvalTask(
        task_id="T01",
        split=AgentEvalSplit.DEV,
        type=AgentTaskType.BUG,
        difficulty="L1",
        repo_fixture=fixture,
        base_commit="",
        prompt="change value",
        oracle_review_status="test",
    )

    results = AgentEvalRunner(
        project_root=tmp_path,
        runtime=EnvironmentBlockedRuntime(),
        keep_workspaces=False,
        worktree_root=worktree_base,
    ).run_suite(
        tasks=[task],
        config=EvalRunConfig(run_id="blocked-run"),
        output_dir=output,
    )

    assert results[0].actor_status is PatchActorStatus.ENVIRONMENT_BLOCKED
    assert results[0].failure_category == "sandbox_unavailable"
    assert not results[0].success
    assert not (output / "workspaces").exists()
    assert not (worktree_base / "evals" / "blocked-run").exists()
    summary = json.loads((output / "summary.json").read_text())
    assert summary["environment_blocked_count"] == 1
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["preflight_results"] == [
        {
            "task_id": "T01",
            "available": False,
            "category": "workspace_mount_unavailable",
        }
    ]


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
        runtime=FakeRuntime(),
        keep_workspaces=True,
        worktree_root=tmp_path / "worktrees",
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
                "verification_commands": [
                    "{python} -c 'import app; assert app.VALUE == 2'"
                ],
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
    runtime = FakeRuntime(patch)
    runner = AgentEvalRunner(
        runtime=runtime,
        grader=AgentGrader(hidden_root=tmp_path / "hidden"),
        keep_workspaces=True,
        worktree_root=tmp_path / "worktrees",
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
        "_artifacts/T01/runtime_messages.json",
        "_artifacts/T01/final.diff",
        "_artifacts/T01/verification.json",
        "_artifacts/T01/model_outputs.jsonl",
    )
    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert summary["success_count"] == 1
    assert summary["pristine_acceptance_passed_count"] == 0
    assert summary["protocol_repair_attempt_count"] == 0
    assert summary["protocol_failed_count"] == 0
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert manifest["execution_root"] == str(
        tmp_path / "worktrees" / "evals" / "test-run"
    )
    assert manifest["runtime_execution"] == "docker"
    assert manifest["grader_execution"] == "trusted_host_subprocess"
    assert manifest["max_protocol_repairs"] == 2
    assert manifest["tasks"] == [
        {
            "task_id": "T01",
            "repo_fixture": str(fixture),
            "base_commit": "",
            "setup_patch": None,
            "setup_patch_sha256": None,
            "public_test_patch": None,
            "public_test_patch_sha256": None,
            "oracle_review_status": "test",
        }
    ]
    runtime_request = runtime.requests[0]
    assert runtime_request.verification_commands == (
        ("python", "-c", "import app; assert app.VALUE == 2"),
    )
    assert "hidden" not in runtime_request.task.lower()
    assert all(
        "hidden" not in part.lower()
        for command in runtime_request.verification_commands
        for part in command
    )


def test_summary_separates_protocol_repair_and_exhaustion() -> None:
    result = AgentEvalTaskResult(
        run_id="protocol-run",
        task_id="T01",
        split=AgentEvalSplit.DEV,
        type=AgentTaskType.BUG,
        difficulty="L1",
        mode=EvalRunMode.BASELINE,
        provider_id="openai-compatible",
        model_id="model",
        success=False,
        actor_status=PatchActorStatus.FAILED,
        acceptance_passed=False,
        regression_passed=True,
        within_budget=True,
        security_passed=True,
        duration_ms=10,
        protocol_repair_attempts=2,
        failure_category="invalid_final_output",
    )

    summary = summarize_agent_eval_results(
        [result],
        run_id="protocol-run",
        mode=EvalRunMode.BASELINE,
    )

    assert summary.protocol_repair_attempt_count == 2
    assert summary.protocol_failed_count == 1


def test_grader_treats_public_task_test_changes_as_safety_violation() -> None:
    violations = AgentGrader._find_safety_violations(
        ("src/app.py", "tests/task_verification/test_t01.py")
    )

    assert violations == [
        "public task oracle changed: tests/task_verification/test_t01.py"
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
        runtime=FakeRuntime(),
        grader=AgentGrader(hidden_root=tmp_path / "hidden"),
        keep_workspaces=True,
        worktree_root=tmp_path / "worktrees",
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
        runtime=FakeRuntime(patch),
        grader=AgentGrader(hidden_root=tmp_path / "hidden"),
        keep_workspaces=True,
        worktree_root=tmp_path / "worktrees",
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
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Eval Test"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "eval@example.com"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "baseline"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    cache = tmp_path / "src" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "app.cpython-311.pyc").write_bytes(b"cache")
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
        changed_files=("untrusted-actor-report.py",),
    )

    grade = AgentGrader(hidden_root=tmp_path / "hidden").grade(
        task=task,
        workspace_root=tmp_path,
        actor_result=actor_result,
        config=EvalRunConfig(run_id="filter-run"),
    )

    assert grade.changed_files == ("app.py",)
    assert grade.security_passed is True


def test_grader_cannot_rescue_environment_blocked_runtime(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Eval Test"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "eval@example.com"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "baseline"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    task = AgentEvalTask(
        task_id="T01",
        split=AgentEvalSplit.DEV,
        type=AgentTaskType.BUG,
        difficulty="L1",
        repo_fixture=tmp_path,
        base_commit="",
        prompt="test",
        acceptance_commands=(
            "{python} -c 'import app; assert app.VALUE == 2'",
        ),
        oracle_review_status="test",
    )
    actor_result = PatchActorResult(
        task_id="T01",
        status=PatchActorStatus.ENVIRONMENT_BLOCKED,
        planning_enabled=True,
        repair_enabled=True,
        compaction_mode="structured",
        failure_category="sandbox_unavailable",
        error="bind source path does not exist",
    )

    grade = AgentGrader(hidden_root=tmp_path / "hidden").grade(
        task=task,
        workspace_root=tmp_path,
        actor_result=actor_result,
        config=EvalRunConfig(run_id="blocked-run"),
    )

    assert grade.acceptance_passed
    assert not grade.success
    assert grade.failure_category == "sandbox_unavailable"


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


def test_provider_response_preserves_token_usage(monkeypatch) -> None:
    monkeypatch.setattr(
        agent_eval_command.urllib.request,
        "urlopen",
        lambda request, timeout: _FakeResponse(
            b'{"model":"provider-model","choices":[{"message":{"content":"{}"}}],'
            b'"usage":{"prompt_tokens":12,"completion_tokens":7}}'
        ),
    )

    response = agent_eval_command._chat_completion_model_response(
        {
            "CODETEAM_LLM_BASE_URL": "https://example.test",
            "CODETEAM_LLM_API_KEY": "key",
            "CODETEAM_LLM_MODEL": "model",
        },
        [],
    )

    assert response.model == "provider-model"
    assert response.input_tokens == 12
    assert response.output_tokens == 7


def test_provider_auto_requests_json_object_mode_with_zero_temperature(
    monkeypatch,
) -> None:
    payloads: list[dict] = []
    agent_eval_command._JSON_MODE_CAPABILITY.clear()
    agent_eval_command._PROVIDER_RUNTIME_STATE.clear()

    def fake_urlopen(request, timeout):
        del timeout
        payloads.append(json.loads(request.data))
        return _FakeResponse(b'{"choices":[{"message":{"content":"{}"}}]}')

    monkeypatch.setattr(agent_eval_command.urllib.request, "urlopen", fake_urlopen)
    config = {
        "CODETEAM_LLM_BASE_URL": "https://json-mode.test",
        "CODETEAM_LLM_API_KEY": "secret-key",
        "CODETEAM_LLM_MODEL": "model",
    }

    agent_eval_command._chat_completion_model_response(config, [])

    assert payloads[0]["response_format"] == {"type": "json_object"}
    assert payloads[0]["temperature"] == 0.0
    manifest = agent_eval_command._provider_manifest(config)
    assert manifest == {
        "response_mode_requested": "auto",
        "response_mode_actual": "json_object",
        "response_mode_fallback": False,
        "temperature": 0.0,
    }
    assert "secret-key" not in json.dumps(manifest)


def test_provider_auto_falls_back_only_for_explicit_unsupported_json_mode(
    monkeypatch,
) -> None:
    payloads: list[dict] = []
    agent_eval_command._JSON_MODE_CAPABILITY.clear()
    agent_eval_command._PROVIDER_RUNTIME_STATE.clear()

    def fake_urlopen(request, timeout):
        del timeout
        payload = json.loads(request.data)
        payloads.append(payload)
        if "response_format" in payload:
            raise urllib.error.HTTPError(
                url="https://fallback.test",
                code=400,
                msg="unsupported",
                hdrs={},
                fp=io.BytesIO(b"response_format json_object is not supported"),
            )
        return _FakeResponse(b'{"choices":[{"message":{"content":"{}"}}]}')

    monkeypatch.setattr(agent_eval_command.urllib.request, "urlopen", fake_urlopen)
    config = {
        "CODETEAM_LLM_BASE_URL": "https://fallback.test",
        "CODETEAM_LLM_API_KEY": "key",
        "CODETEAM_LLM_MODEL": "model",
        "CODETEAM_LLM_TEMPERATURE": "0.25",
    }

    agent_eval_command._chat_completion_model_response(config, [])
    agent_eval_command._chat_completion_model_response(config, [])

    assert ["response_format" in payload for payload in payloads] == [True, False, False]
    assert all(payload["temperature"] == 0.25 for payload in payloads)
    manifest = agent_eval_command._provider_manifest(config)
    assert manifest["response_mode_actual"] == "text"
    assert manifest["response_mode_fallback"] is True


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


def test_provider_serializes_custom_tool_observation_as_user_message() -> None:
    payload = agent_eval_command._provider_message(
        Message(role="tool", content="tests passed", tool_call_id="call-7")
    )

    assert payload["role"] == "user"
    assert "call-7" in (payload["content"] or "")
    assert "tests passed" in (payload["content"] or "")


def test_week4_development_suite_has_no_claimed_heldout_tasks() -> None:
    project_root = Path(__file__).resolve().parents[2]
    tasks = load_agent_eval_tasks(
        project_root / "evals" / "week4" / "agent_task_suite_v1.jsonl"
    )

    assert len(tasks) == 11
    assert {task.split for task in tasks} == {AgentEvalSplit.DEV}
    assert all(task.verification_commands for task in tasks)
    assert all(task.task_verification_commands for task in tasks)
    assert all(task.public_test_patch for task in tasks)
    assert all(task.public_test_patch_sha256 for task in tasks)


def test_eval_exposes_workspace_relative_verification_commands() -> None:
    task = AgentEvalTask(
        task_id="T01",
        split=AgentEvalSplit.DEV,
        type=AgentTaskType.BUG,
        difficulty="L1",
        repo_fixture=Path("fixture"),
        base_commit="",
        prompt="test",
        verification_commands=(
            (
                "{python} -m pytest {workspace}/tests/auth "
                "{project_root}/tests/inventory -q"
            ),
        ),
        oracle_review_status="test",
    )

    assert _visible_verification_argv(task) == (
        (
            "python",
            "-m",
            "pytest",
            "tests/auth",
            "tests/inventory",
            "-q",
        ),
    )


def test_product_cli_and_evaluator_import_the_same_runtime() -> None:
    assert run_command.CodingAgentRuntime is CodingAgentRuntime
    assert agent_eval_command.CodingAgentRuntime is CodingAgentRuntime


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self.body
