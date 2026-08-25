from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from codeteam.agent.editing import FileEdit, file_edits_to_patch
from codeteam.agent.runtime import CodingAgentRuntime, _message_transform
from codeteam.agent.runtime_models import (
    CodingAgentRunRequest,
    CompactionMode,
    RuntimeStatus,
)
from codeteam.execution.models import CommandResult, CommandStatus
from codeteam.execution.safe_execution_service import SafeExecutionService
from codeteam.git.workspace import GitWorkspace
from codeteam.schemas.messages import Message


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


def _call(index: int, name: str, arguments: dict) -> dict:
    return {
        "tool_calls": [
            {"call_id": f"call-{index}", "name": name, "arguments": arguments}
        ]
    }


def test_runtime_completes_search_patch_test_repair_diff_loop(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    model = ScriptedModel(
        [
            _call(1, "search_code", {"query": "VALUE", "path": "."}),
            _call(2, "read_file", {"path": "app.py"}),
            _call(3, "apply_patch", {"edits": [{"path": "app.py", "content": "VALUE = 2\n"}]}),
            _call(4, "run_tests", {"argv": ["python", "-m", "pytest"]}),
            _call(5, "git_diff", {}),
            _call(6, "apply_patch", {"edits": [{"path": "app.py", "content": "VALUE = 3\n"}]}),
            _call(7, "run_tests", {"argv": ["python", "-m", "pytest"]}),
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
            verification_commands=(("python", "-m", "pytest"),),
            checkpoint_state_root=tmp_path / "checkpoints",
        )
    )

    assert result.status is RuntimeStatus.COMPLETED
    assert result.repair_attempts == 1
    assert [item.passed for item in result.verification] == [False, True]
    assert result.changed_files == ("app.py",)
    assert "VALUE = 3" in (repo / "app.py").read_text(encoding="utf-8")
    assert "VALUE = 3" in result.diff
    second_request = model.requests[1]
    assert [message.role for message in second_request[-2:]] == ["assistant", "tool"]


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
    assert any("Structured context summary" in (item.content or "") for item in structured)
    assert structured != naive


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
