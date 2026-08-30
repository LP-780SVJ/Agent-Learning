from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from codeteam.agent.runtime_tools import RuntimeEvidence, create_runtime_tools
from codeteam.agent.verification import (
    VerificationCommandError,
    normalize_run_tests_action,
    normalize_verification_argv,
    normalize_verification_cwd,
)
from codeteam.execution.models import CommandResult, CommandStatus
from codeteam.execution.safe_execution_service import SafeExecutionService
from codeteam.schemas.tool_calls import ToolCall


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
    (repo / "tests" / "auth").mkdir(parents=True)
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.name", "Verification Test")
    _git(repo, "config", "user.email", "verification@example.com")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "baseline")
    return repo


class RecordingSandbox:
    def __init__(self) -> None:
        self.contexts = []

    def run(self, context) -> CommandResult:
        self.contexts.append(context)
        return CommandResult(
            status=CommandStatus.SUCCESS,
            argv=context.argv,
            cwd=context.cwd,
            exit_code=0,
            stdout="passed",
            stderr="",
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/workspace/tests/auth", "tests/auth"),
        ("./tests/auth", "tests/auth"),
        ("tests/auth", "tests/auth"),
        ("/workspace", "."),
    ],
)
def test_verification_paths_normalize_to_workspace_relative(
    raw: str,
    expected: str,
) -> None:
    assert normalize_verification_argv(("pytest", raw)) == ("pytest", expected)


def test_verification_option_value_normalizes_container_workspace() -> None:
    assert normalize_verification_argv(
        ("pytest", "--rootdir=/workspace", "/workspace/tests")
    ) == ("pytest", "--rootdir=.", "tests")


@pytest.mark.parametrize(
    "argument",
    [
        "--rootdir=/etc",
        "--basetemp=../outside",
        "--rootdir=/workspace/../etc",
    ],
)
def test_verification_option_path_escape_is_rejected(argument: str) -> None:
    with pytest.raises(VerificationCommandError):
        normalize_verification_argv(("pytest", argument))


@pytest.mark.parametrize(
    "path",
    [
        "/workspace/../etc",
        "/workspace/tests/../../etc",
    ],
)
def test_container_workspace_escape_is_rejected(path: str) -> None:
    with pytest.raises(VerificationCommandError, match="escapes /workspace"):
        normalize_verification_argv(("pytest", path))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (".", "."),
        ("/workspace", "."),
        ("/workspace/tests", "tests"),
        ("./tests", "tests"),
    ],
)
def test_verification_cwd_is_workspace_relative(raw: str, expected: str) -> None:
    assert normalize_verification_cwd(raw) == expected


@pytest.mark.parametrize("cwd", ["/etc", "../outside", "/workspace/../etc"])
def test_verification_cwd_escape_is_rejected(cwd: str) -> None:
    with pytest.raises(VerificationCommandError):
        normalize_verification_cwd(cwd)


def test_run_tests_normalizer_equates_container_and_relative_actions() -> None:
    container = normalize_run_tests_action(
        "run_tests",
        {"argv": ["python", "-m", "pytest", "/workspace/tests"]},
    )
    relative = normalize_run_tests_action(
        "run_tests",
        {
            "argv": ["python", "-m", "pytest", "./tests"],
            "cwd": ".",
            "timeout_seconds": 120,
        },
    )

    assert container == relative


def test_runtime_maps_legacy_container_paths_before_policy_and_docker(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    sandbox = RecordingSandbox()
    evidence = RuntimeEvidence()
    tools = create_runtime_tools(
        workspace_root=repo,
        task_id="T01",
        checkpoint_state_root=tmp_path / "checkpoints",
        safe_execution=SafeExecutionService(sandbox_runner=sandbox),
        evidence=evidence,
        allowed_verification_commands=(
            ("python", "-m", "pytest", "tests/auth", "-q"),
        ),
    )

    result = tools.execute(
        ToolCall(
            call_id="call-1",
            name="run_tests",
            arguments={
                "argv": [
                    "python",
                    "-m",
                    "pytest",
                    "/workspace/tests/auth",
                    "-q",
                ],
                "cwd": "/workspace",
            },
        )
    )

    assert result.success
    assert json.loads(result.content)["passed"] is True
    assert sandbox.contexts[0].argv == (
        "python",
        "-m",
        "pytest",
        "tests/auth",
        "-q",
    )
    assert sandbox.contexts[0].cwd == repo
    assert sandbox.contexts[0].container_cwd == Path("/workspace")


def test_runtime_rejects_non_allowlisted_command_with_canonical_hint(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    tools = create_runtime_tools(
        workspace_root=repo,
        task_id="T02",
        checkpoint_state_root=tmp_path / "checkpoints",
        safe_execution=SafeExecutionService(sandbox_runner=RecordingSandbox()),
        evidence=RuntimeEvidence(),
        allowed_verification_commands=(
            ("python", "-m", "pytest", "tests/auth", "-q"),
        ),
    )

    result = tools.execute(
        ToolCall(
            call_id="call-2",
            name="run_tests",
            arguments={"argv": ["python", "-m", "pytest", "tests", "-q"]},
        )
    )

    assert not result.success
    assert "workspace-relative argv arrays" in (result.error or "")
    assert "tests/auth" in (result.error or "")


def test_runtime_rejects_container_escape_before_sandbox(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    sandbox = RecordingSandbox()
    tools = create_runtime_tools(
        workspace_root=repo,
        task_id="T03",
        checkpoint_state_root=tmp_path / "checkpoints",
        safe_execution=SafeExecutionService(sandbox_runner=sandbox),
        evidence=RuntimeEvidence(),
    )

    result = tools.execute(
        ToolCall(
            call_id="call-3",
            name="run_tests",
            arguments={"argv": ["pytest", "/workspace/../etc"]},
        )
    )

    assert not result.success
    assert "escapes /workspace" in (result.error or "")
    assert sandbox.contexts == []


def test_runtime_policy_rejects_host_absolute_path_before_sandbox(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    sandbox = RecordingSandbox()
    evidence = RuntimeEvidence()
    tools = create_runtime_tools(
        workspace_root=repo,
        task_id="T04",
        checkpoint_state_root=tmp_path / "checkpoints",
        safe_execution=SafeExecutionService(sandbox_runner=sandbox),
        evidence=evidence,
    )

    result = tools.execute(
        ToolCall(
            call_id="call-4",
            name="run_tests",
            arguments={"argv": ["pytest", "/etc"]},
        )
    )

    assert result.success
    assert json.loads(result.content)["passed"] is False
    assert evidence.verification[0].error == "Command denied by policy."
    assert sandbox.contexts == []
