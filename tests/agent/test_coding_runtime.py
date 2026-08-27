from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from codeteam.agent.editing import (
    FileEdit,
    TextReplacement,
    file_edits_to_patch,
    text_replacements_to_patch,
)
from codeteam.agent.runtime import CodingAgentRuntime, _message_transform
from codeteam.agent.runtime_models import (
    CodingAgentRunRequest,
    CompactionMode,
    RuntimeStatus,
    VerificationEvidence,
)
from codeteam.agent.runtime_tools import RuntimeEvidence
from codeteam.execution.models import CommandResult, CommandStatus
from codeteam.execution.safe_execution_service import SafeExecutionService
from codeteam.git.workspace import GitWorkspace
from codeteam.sandbox.preflight import (
    DockerSandboxPreflight,
    SandboxPreflightResult,
)
from codeteam.schemas.messages import Message


@pytest.fixture(autouse=True)
def _sandbox_preflight_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        DockerSandboxPreflight,
        "check",
        lambda self, workspace_root: SandboxPreflightResult(available=True),
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        shell=False,
        timeout=10,
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Runtime Test")
    _git(repo, "config", "user.email", "runtime@example.com")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "baseline")
    return repo


class ScriptedModel:
    def __init__(self, outputs: list[dict]) -> None:
        self.outputs = outputs
        self.requests: list[list[Message]] = []

    def complete(self, messages: list[Message]) -> str:
        self.requests.append(messages)
        return json.dumps(self.outputs.pop(0))


class FailedPreflight:
    def check(self, workspace_root: Path) -> SandboxPreflightResult:
        del workspace_root
        return SandboxPreflightResult(
            available=False,
            category="workspace_mount_unavailable",
            error="bind source path does not exist",
        )


class StubContext:
    def execute(self, **kwargs):
        del kwargs
        return SimpleNamespace(
            repo_map="app.py",
            code_context=[],
            applicable_instructions=[],
            test_commands=[],
            diagnostics=[],
        )


class SequencedSandbox:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, context) -> CommandResult:
        self.calls += 1
        passed = self.calls == 2
        return CommandResult(
            status=CommandStatus.SUCCESS if passed else CommandStatus.NONZERO_EXIT,
            argv=context.argv,
            cwd=context.cwd,
            exit_code=0 if passed else 1,
            stdout="passed" if passed else "",
            stderr="" if passed else "assertion failed",
        )


class PassingSandbox:
    def run(self, context) -> CommandResult:
        return CommandResult(
            status=CommandStatus.SUCCESS,
            argv=context.argv,
            cwd=context.cwd,
            exit_code=0,
            stdout="passed",
            stderr="",
        )


class FailingSandbox:
    def run(self, context) -> CommandResult:
        return CommandResult(
            status=CommandStatus.NONZERO_EXIT,
            argv=context.argv,
            cwd=context.cwd,
            exit_code=1,
            stdout="",
            stderr="assertion failed",
        )


class MountFailingSandbox:
    def run(self, context) -> CommandResult:
        del context
        return CommandResult(
            status=CommandStatus.NONZERO_EXIT,
            argv=("docker", "run"),
            exit_code=125,
            stderr="invalid mount config: bind source path does not exist",
        )


def _call(index: int, name: str, arguments: dict) -> dict:
    return {
        "tool_calls": [
            {"call_id": f"call-{index}", "name": name, "arguments": arguments}
        ]
    }


def test_preflight_failure_pauses_before_provider_call(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    model = ScriptedModel(
        [{"status": "completed", "summary": "should not run", "tests_passed": True}]
    )

    result = CodingAgentRuntime(
        model_client=model,
        context_service=StubContext(),
        sandbox_preflight=FailedPreflight(),
    ).run(
        CodingAgentRunRequest(
            task_id="T00",
            task="fix app",
            workspace_root=repo,
            provider_id="scripted",
            model_id="scripted",
        )
    )

    assert result.status is RuntimeStatus.PAUSED
    assert result.failure_category == "sandbox_unavailable"
    assert result.sandbox_preflight_available is False
    assert result.sandbox_preflight_category == "workspace_mount_unavailable"
    assert result.steps_used == 0
    assert result.tool_calls_used == 0
    assert result.input_tokens == 0
    assert result.output_tokens == 0
    assert result.cost_usd == 0
    assert model.requests == []


def test_sandbox_backend_failure_halts_without_second_model_turn(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    model = ScriptedModel(
        [
            _call(
                1,
                "apply_patch",
                {
                    "replacements": [
                        {
                            "path": "app.py",
                            "old_text": "VALUE = 1",
                            "new_text": "VALUE = 2",
                        }
                    ]
                },
            ),
            _call(2, "run_tests", {"argv": ["pytest", "tests", "-q"]}),
            {"status": "completed", "summary": "must not run", "tests_passed": True},
        ]
    )

    result = CodingAgentRuntime(
        model_client=model,
        context_service=StubContext(),
        safe_execution=SafeExecutionService(sandbox_runner=MountFailingSandbox()),
    ).run(
        CodingAgentRunRequest(
            task_id="T00B",
            task="fix app",
            workspace_root=repo,
            provider_id="scripted",
            model_id="scripted",
            checkpoint_state_root=tmp_path / "checkpoints",
        )
    )

    assert result.status is RuntimeStatus.PAUSED
    assert result.failure_category == "execution_paused"
    assert "bind source path" in (result.error or "")
    assert len(model.requests) == 2


def test_patch_attempts_include_rejected_patch_calls(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    model = ScriptedModel(
        [
            _call(1, "apply_patch", {"patch": "not a patch"}),
            _call(
                2,
                "apply_patch",
                {
                    "replacements": [
                        {
                            "path": "app.py",
                            "old_text": "VALUE = 1",
                            "new_text": "VALUE = 2",
                        }
                    ]
                },
            ),
            _call(3, "run_tests", {"argv": ["pytest", "tests", "-q"]}),
            _call(4, "git_diff", {}),
            {"status": "completed", "summary": "done", "tests_passed": True},
        ]
    )

    result = CodingAgentRuntime(
        model_client=model,
        context_service=StubContext(),
        safe_execution=SafeExecutionService(sandbox_runner=PassingSandbox()),
    ).run(
        CodingAgentRunRequest(
            task_id="T00C",
            task="fix app",
            workspace_root=repo,
            provider_id="scripted",
            model_id="scripted",
            checkpoint_state_root=tmp_path / "checkpoints",
        )
    )

    assert result.status is RuntimeStatus.COMPLETED
    assert result.patch_attempts == 2
    assert result.repair_attempts == 0


def test_runtime_completes_search_patch_test_repair_diff_loop(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    model = ScriptedModel(
        [
            _call(1, "search_code", {"query": "VALUE", "path": "."}),
            _call(2, "read_file", {"path": "app.py"}),
            _call(3, "apply_patch", {"edits": [{"path": "app.py", "content": "VALUE = 2\n"}]}),
            _call(30, "read_file", {"path": "app.py"}),
            _call(
                4,
                "run_tests",
                {"argv": ["python", "-m", "pytest", "/workspace/tests"]},
            ),
            _call(5, "git_diff", {}),
            _call(6, "apply_patch", {"edits": [{"path": "app.py", "content": "VALUE = 3\n"}]}),
            _call(
                7,
                "run_tests",
                {"argv": ["python", "-m", "pytest", "./tests"]},
            ),
            _call(8, "git_diff", {}),
            {"status": "completed", "summary": "fixed", "tests_passed": True},
        ]
    )
    runtime = CodingAgentRuntime(
        model_client=model,
        safe_execution=SafeExecutionService(sandbox_runner=SequencedSandbox()),
        context_service=StubContext(),
    )

    result = runtime.run(
        CodingAgentRunRequest(
            task_id="T01",
            task="change VALUE",
            workspace_root=repo,
            provider_id="scripted",
            model_id="scripted",
            max_steps=12,
            max_tool_calls=12,
            verification_commands=(("python", "-m", "pytest", "tests"),),
            checkpoint_state_root=tmp_path / "checkpoints",
        )
    )

    assert result.status is RuntimeStatus.COMPLETED
    assert result.repair_attempts == 1
    assert [item.passed for item in result.verification] == [False, True]
    assert result.changed_files == ("app.py",)
    assert "VALUE = 3" in (repo / "app.py").read_text(encoding="utf-8")
    assert "VALUE = 3" in result.diff
    assert result.verification[0].argv == ("python", "-m", "pytest", "tests")
    assert result.verification[1].argv == ("python", "-m", "pytest", "tests")
    second_request = model.requests[1]
    assert [message.role for message in second_request[-2:]] == ["assistant", "tool"]


def test_task_verification_is_distinct_from_broad_regression(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    model = ScriptedModel(
        [
            _call(1, "apply_patch", {"edits": [{"path": "app.py", "content": "VALUE = 2\n"}]}),
            _call(2, "run_tests", {"argv": ["python", "-m", "pytest", "tests"]}),
            _call(3, "run_tests", {"argv": ["python", "-m", "pytest", "tests/task.py"]}),
            _call(4, "git_diff", {}),
            {"status": "completed", "summary": "verified", "tests_passed": True},
        ]
    )
    result = CodingAgentRuntime(
        model_client=model,
        safe_execution=SafeExecutionService(sandbox_runner=PassingSandbox()),
        context_service=StubContext(),
    ).run(
        CodingAgentRunRequest(
            task_id="required-test",
            task="change VALUE",
            workspace_root=repo,
            provider_id="scripted",
            model_id="scripted",
            verification_commands=(("python", "-m", "pytest", "tests"),),
            task_verification_commands=(
                ("python", "-m", "pytest", "tests/task.py"),
            ),
            checkpoint_state_root=tmp_path / "checkpoints",
        )
    )

    assert result.status is RuntimeStatus.COMPLETED
    assert [item.completion_required for item in result.verification] == [False, True]


def test_runtime_preserves_resumed_protocol_streak_before_first_model_call(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    observed_streaks: list[int] = []
    runtime = CodingAgentRuntime(
        model_client=ScriptedModel(
            [
                {
                    "status": "failed",
                    "summary": "stop",
                    "tests_passed": False,
                    "error": "stop",
                }
            ]
        ),
        context_service=StubContext(),
        state_callback=lambda state, evidence: observed_streaks.append(
            state.protocol_repair_streak
        ),
    )

    runtime.run(
        CodingAgentRunRequest(
            task_id="resume-streak",
            task="stop",
            workspace_root=repo,
            provider_id="scripted",
            model_id="scripted",
            initial_protocol_repair_streak=1,
        )
    )

    assert observed_streaks[0] == 1
    assert observed_streaks[-1] == 0


def test_completed_without_verification_pauses(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    model = ScriptedModel(
        [
            _call(1, "apply_patch", {"edits": [{"path": "app.py", "content": "VALUE = 2\n"}]}),
            {"status": "completed", "summary": "done", "tests_passed": False},
        ]
    )
    result = CodingAgentRuntime(
        model_client=model,
        context_service=StubContext(),
    ).run(
        CodingAgentRunRequest(
            task_id="T02",
            task="change VALUE",
            workspace_root=repo,
            provider_id="scripted",
            model_id="scripted",
            checkpoint_state_root=tmp_path / "checkpoints",
        )
    )
    assert result.status is RuntimeStatus.PAUSED
    assert result.failure_category == "verification_required"


def test_compaction_modes_are_behaviorally_distinct() -> None:
    messages = [
        Message(role="system", content="system"),
        Message(role="user", content="task"),
        *[Message(role="tool", content="x" * 40, tool_call_id=str(i)) for i in range(6)],
    ]
    none = _message_transform(CompactionMode.NONE, 20)(messages)
    naive = _message_transform(CompactionMode.NAIVE, 20)(messages)
    structured = _message_transform(CompactionMode.STRUCTURED, 20)(messages)

    assert none == messages
    assert len(naive) < len(none)
    assert any("structured_context_summary" in (item.content or "") for item in structured)
    assert structured != naive


def test_structured_compaction_keeps_deterministic_runtime_facts() -> None:
    evidence = RuntimeEvidence(
        workspace_version=2,
        changed_files=("app.py",),
        git_diff_checked=True,
        required_verification_commands=(("python", "-m", "pytest", "tests/task.py"),),
        verification=[
            VerificationEvidence(
                argv=("python", "-m", "pytest", "tests/task.py"),
                passed=True,
                completion_required=True,
            )
        ],
    )
    messages = [
        Message(role="system", content="system"),
        Message(role="user", content="task"),
        Message(
            role="assistant",
            content=json.dumps(
                {
                    "tool_calls": [
                        {"name": "read_file", "arguments": {"path": "app.py"}},
                        {"name": "search_code", "arguments": {"query": "VALUE"}},
                        {"name": "git_diff", "arguments": {}},
                    ]
                }
            ),
        ),
        Message(role="tool", content="x" * 200, tool_call_id="call-1"),
        Message(role="assistant", content="<｜｜DSML｜｜tool_calls>raw"),
    ]

    compacted = _message_transform(CompactionMode.STRUCTURED, 20, evidence)(
        messages
    )
    summary = next(
        json.loads(item.content)["structured_context_summary"]
        for item in compacted
        if "structured_context_summary" in (item.content or "")
    )

    assert summary["read_files"] == ["app.py"]
    assert summary["workspace_version"] == 2
    assert summary["changed_files"] == ["app.py"]
    assert summary["git_diff_checked"] is True
    assert summary["remaining_completion_gate"] == "task_verification_passed"
    assert all("DSML" not in (item.content or "") for item in compacted)


def test_provider_failure_is_classified_without_escaping(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    class BrokenProvider:
        def complete(self, messages: list[Message]) -> str:
            del messages
            raise TimeoutError("provider timed out")

    result = CodingAgentRuntime(
        model_client=BrokenProvider(),
        context_service=StubContext(),
    ).run(
        CodingAgentRunRequest(
            task_id="T03",
            task="change VALUE",
            workspace_root=repo,
            provider_id="broken",
            model_id="broken",
        )
    )

    assert result.status is RuntimeStatus.FAILED
    assert result.failure_category == "provider_blocked"
    assert "timed out" in (result.error or "")


def test_path_escape_patch_is_rejected_without_side_effects(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    outside = tmp_path / "outside.py"
    model = ScriptedModel(
        [
            _call(
                1,
                "apply_patch",
                {"edits": [{"path": "../outside.py", "content": "bad\n"}]},
            ),
            {
                "status": "failed",
                "summary": "rejected",
                "tests_passed": False,
                "error": "unsafe edit rejected",
            },
        ]
    )

    result = CodingAgentRuntime(
        model_client=model,
        context_service=StubContext(),
    ).run(
        CodingAgentRunRequest(
            task_id="T04",
            task="unsafe edit",
            workspace_root=repo,
            provider_id="scripted",
            model_id="scripted",
        )
    )

    assert result.status is RuntimeStatus.FAILED
    assert not outside.exists()
    assert result.changed_files == ()


def test_approval_required_command_pauses_fail_closed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    model = ScriptedModel(
        [
            _call(1, "apply_patch", {"edits": [{"path": "app.py", "content": "VALUE = 2\n"}]}),
            _call(2, "run_tests", {"argv": ["pip", "install", "package"]}),
            {"status": "completed", "summary": "done", "tests_passed": False},
        ]
    )

    result = CodingAgentRuntime(
        model_client=model,
        context_service=StubContext(),
    ).run(
        CodingAgentRunRequest(
            task_id="T05",
            task="unsafe command",
            workspace_root=repo,
            provider_id="scripted",
            model_id="scripted",
            checkpoint_state_root=tmp_path / "checkpoints",
        )
    )

    assert result.status is RuntimeStatus.PAUSED
    assert result.failure_category == "execution_paused"
    assert "approval" in (result.error or "").lower()


def test_structured_edits_support_new_and_deleted_files(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    patch = file_edits_to_patch(
        repo,
        [
            FileEdit(path="app.py", delete=True),
            FileEdit(path="new.py", content="NEW = True\n"),
        ],
    )

    result = GitWorkspace(repo).apply_patch(patch)

    assert result.applied
    assert not (repo / "app.py").exists()
    assert (repo / "new.py").read_text(encoding="utf-8") == "NEW = True\n"


def test_text_replacement_generates_local_patch(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    patch = text_replacements_to_patch(
        repo,
        [
            TextReplacement(
                path="app.py",
                old_text="VALUE = 1",
                new_text="VALUE = 2",
            )
        ],
    )

    assert "-VALUE = 1" in patch
    assert "+VALUE = 2" in patch
    assert (repo / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"


@pytest.mark.parametrize(
    ("old_text", "expected", "found"),
    [
        ("MISSING", 1, 0),
        ("VALUE", 1, 1),
    ],
)
def test_text_replacement_requires_exact_match_count(
    tmp_path: Path,
    old_text: str,
    expected: int,
    found: int,
) -> None:
    repo = _repo(tmp_path)
    if old_text == "VALUE":
        (repo / "app.py").write_text("VALUE = 1\nVALUE = 2\n", encoding="utf-8")
        found = 2

    with pytest.raises(ValueError, match=f"expected {expected}, found {found}"):
        text_replacements_to_patch(
            repo,
            [
                TextReplacement(
                    path="app.py",
                    old_text=old_text,
                    new_text="CHANGED",
                    expected_replacements=expected,
                )
            ],
        )


def test_text_replacement_rejects_symlink_escape(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("SECRET = 1\n", encoding="utf-8")
    (repo / "linked.py").symlink_to(outside)

    with pytest.raises(ValueError, match="escapes workspace"):
        text_replacements_to_patch(
            repo,
            [
                TextReplacement(
                    path="linked.py",
                    old_text="SECRET = 1",
                    new_text="SECRET = 2",
                )
            ],
        )

    assert outside.read_text(encoding="utf-8") == "SECRET = 1\n"


def test_runtime_completes_with_dsml_actions_and_fenced_final(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    dsml = "｜｜DSML｜｜"
    model = SimpleNamespace()
    model.outputs = [
        (
            f"<{dsml}tool_calls><{dsml}invoke name=\"apply_patch\">"
            f"<{dsml}parameter name=\"edits\" string=\"false\">"
            '[{"path":"app.py","content":"VALUE = 2\\n"}]'
            f"</{dsml}parameter></{dsml}invoke></{dsml}tool_calls>"
        ),
        (
            f"<{dsml}tool_calls><{dsml}invoke name=\"run_tests\">"
            f"<{dsml}parameter name=\"argv\" string=\"false\">"
            '["python","-m","pytest"]'
            f"</{dsml}parameter></{dsml}invoke></{dsml}tool_calls>"
        ),
        (
            f"<{dsml}tool_calls><{dsml}invoke name=\"git_diff\">"
            f"</{dsml}invoke></{dsml}tool_calls>"
        ),
        (
            "```json\n"
            '{"status":"completed","summary":"fixed",'
            '"tests_passed":true}\n'
            "```"
        ),
    ]
    model.requests = []

    def complete(messages: list[Message]) -> str:
        model.requests.append(messages)
        return model.outputs.pop(0)

    model.complete = complete
    runtime = CodingAgentRuntime(
        model_client=model,
        safe_execution=SafeExecutionService(sandbox_runner=PassingSandbox()),
        context_service=StubContext(),
    )

    result = runtime.run(
        CodingAgentRunRequest(
            task_id="T06",
            task="change VALUE",
            workspace_root=repo,
            provider_id="deepseek-compatible",
            model_id="deepseek",
            max_steps=8,
            verification_commands=(("python", "-m", "pytest"),),
            checkpoint_state_root=tmp_path / "checkpoints",
        )
    )

    assert result.status is RuntimeStatus.COMPLETED
    assert result.protocol_repairs_used == 0
    assert result.tool_calls_used == 3
    assert result.changed_files == ("app.py",)
    assert (repo / "app.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert all(
        "<｜｜DSML｜｜tool_calls>" not in (message.content or "")
        for message in result.messages
    )
    assert result.model_outputs[0].dialect == "deepseek_dsml"
    assert "<｜｜DSML｜｜tool_calls>" in result.model_outputs[0].raw_content


def test_runtime_prompt_contains_complete_action_contract(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    model = ScriptedModel(
        [
            {
                "status": "failed",
                "summary": "stop after prompt inspection",
                "tests_passed": False,
                "error": "test-only stop",
            }
        ]
    )

    CodingAgentRuntime(model_client=model, context_service=StubContext()).run(
        CodingAgentRunRequest(
            task_id="T07",
            task="inspect protocol",
            workspace_root=repo,
            provider_id="scripted",
            model_id="scripted",
        )
    )

    system = json.loads(model.requests[0][0].content or "{}")
    assert "tool_call_schema" in system["protocol"]
    assert "final_output_schema" in system["protocol"]
    assert "Runtime assigns" in system["protocol"]["tool_call_note"]
    assert "paths and cwd are relative to the workspace" in system["execution_boundary"]
    assert "do not put /workspace" in system["execution_boundary"]


def test_equivalent_failed_verification_stops_without_spending_more_steps(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    model = ScriptedModel(
        [
            _call(
                1,
                "apply_patch",
                {"edits": [{"path": "app.py", "content": "VALUE = 2\n"}]},
            ),
            _call(
                2,
                "run_tests",
                {"argv": ["python", "-m", "pytest", "/workspace/tests"]},
            ),
            _call(3, "git_diff", {}),
            _call(
                4,
                "run_tests",
                {
                    "argv": ["python", "-m", "pytest", "./tests"],
                    "cwd": ".",
                    "timeout_seconds": 120,
                },
            ),
        ]
    )
    result = CodingAgentRuntime(
        model_client=model,
        safe_execution=SafeExecutionService(sandbox_runner=FailingSandbox()),
        context_service=StubContext(),
    ).run(
        CodingAgentRunRequest(
            task_id="T08",
            task="change VALUE",
            workspace_root=repo,
            provider_id="scripted",
            model_id="scripted",
            max_steps=10,
            verification_commands=(("python", "-m", "pytest", "tests"),),
            checkpoint_state_root=tmp_path / "checkpoints",
        )
    )

    assert result.status is RuntimeStatus.FAILED
    assert result.failure_category == "repeated_action"
    assert result.steps_used == 4
    assert result.tool_calls_used == 3
    assert len(result.verification) == 1
