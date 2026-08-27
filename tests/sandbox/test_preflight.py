from __future__ import annotations

from pathlib import Path

import pytest

from codeteam.execution.models import CommandResult, CommandStatus
from codeteam.sandbox.models import SandboxExecutionContext
from codeteam.sandbox.preflight import DockerSandboxPreflight


class StubDockerRunner:
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        self.contexts: list[SandboxExecutionContext] = []

    def run(self, context: SandboxExecutionContext) -> CommandResult:
        self.contexts.append(context)
        return self.result


def _result(
    *,
    status: CommandStatus = CommandStatus.NONZERO_EXIT,
    exit_code: int | None = 1,
    stderr: str = "",
    error: str | None = None,
) -> CommandResult:
    return CommandResult(
        status=status,
        argv=("docker", "run"),
        exit_code=exit_code,
        stderr=stderr,
        error=error,
    )


def test_preflight_uses_same_workspace_mount_with_read_only_profile(
    tmp_path: Path,
) -> None:
    runner = StubDockerRunner(
        _result(status=CommandStatus.SUCCESS, exit_code=0)
    )

    result = DockerSandboxPreflight(runner=runner).check(tmp_path)

    assert result.available
    assert runner.contexts[0].workspace_root == tmp_path
    assert runner.contexts[0].cwd == tmp_path
    assert runner.contexts[0].argv == ("test", "-d", "/workspace")
    assert runner.contexts[0].profile.workspace_write is False
    assert runner.contexts[0].profile.pull_policy == "never"


@pytest.mark.parametrize(
    ("result", "category"),
    [
        (
            _result(
                status=CommandStatus.START_FAILED,
                exit_code=None,
                error="No such file or directory: docker",
            ),
            "docker_cli_unavailable",
        ),
        (
            _result(stderr="Cannot connect to the Docker daemon"),
            "docker_daemon_unavailable",
        ),
        (
            _result(stderr="No such image: codeteam-sandbox:latest"),
            "sandbox_image_unavailable",
        ),
        (
            _result(
                exit_code=125,
                stderr="invalid mount config: bind source path does not exist",
            ),
            "workspace_mount_unavailable",
        ),
        (
            _result(exit_code=125, stderr="docker: invalid invocation"),
            "sandbox_start_failed",
        ),
    ],
)
def test_preflight_classifies_environment_failures(
    tmp_path: Path,
    result: CommandResult,
    category: str,
) -> None:
    outcome = DockerSandboxPreflight(
        runner=StubDockerRunner(result)
    ).check(tmp_path)

    assert not outcome.available
    assert outcome.category == category
    assert "--worktree-root" in (outcome.error or "")
