from __future__ import annotations

from codeteam.execution.models import CommandLimits, CommandRequest, CommandResult
from codeteam.execution.runner import CommandRunner
from codeteam.sandbox.docker_builder import DockerCommandBuilder
from codeteam.sandbox.models import SandboxExecutionContext


class DockerRunner:
    """通过 Docker 执行 SandboxExecutionContext。"""

    def __init__(
        self,
        *,
        builder: DockerCommandBuilder | None = None,
        runner: CommandRunner | None = None,
        limits: CommandLimits | None = None,
    ) -> None:
        self._builder = builder or DockerCommandBuilder()
        self._runner = runner or CommandRunner(limits)

    def run(self, context: SandboxExecutionContext) -> CommandResult:
        docker_argv = self._builder.build(context)

        request = CommandRequest(
            argv=docker_argv,
            cwd=context.workspace_root,
            workspace_root=context.workspace_root,
        )

        return self._runner.run(request)