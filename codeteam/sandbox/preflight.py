from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from codeteam.execution.models import CommandResult, CommandStatus
from codeteam.sandbox.docker_runner import DockerRunner
from codeteam.sandbox.models import SandboxExecutionContext, SandboxProfile


class SandboxPreflightResult(BaseModel):
    available: bool
    category: str | None = None
    error: str | None = None


class SandboxPreflight(Protocol):
    def check(self, workspace_root: Path) -> SandboxPreflightResult: ...


class SandboxRunner(Protocol):
    def run(self, context: SandboxExecutionContext) -> CommandResult: ...


class DockerSandboxPreflight:
    """Verify that the production sandbox can mount and start a workspace."""

    def __init__(
        self,
        *,
        runner: SandboxRunner | None = None,
        profile: SandboxProfile | None = None,
    ) -> None:
        self._runner = runner or DockerRunner()
        self._profile = profile or SandboxProfile(workspace_write=False)

    def check(self, workspace_root: Path) -> SandboxPreflightResult:
        root = workspace_root.resolve(strict=True)
        try:
            result = self._runner.run(
                SandboxExecutionContext(
                    argv=("test", "-d", "/workspace"),
                    workspace_root=root,
                    cwd=root,
                    profile=self._profile,
                )
            )
        except Exception as error:  # noqa: BLE001 - normalize backend setup failures
            detail = str(error) or type(error).__name__
            return SandboxPreflightResult(
                available=False,
                category="sandbox_start_failed",
                error=(
                    "Docker sandbox preflight failed (sandbox_start_failed): "
                    f"{detail}. Set --worktree-root or CODETEAM_WORKTREE_ROOT to "
                    "a directory shared with Docker (for Colima, under $HOME)."
                ),
            )
        if result.status is CommandStatus.SUCCESS:
            return SandboxPreflightResult(available=True)

        detail = _combined_detail(result.error, result.stderr, result.stdout)
        category = _preflight_failure_category(
            detail,
            start_failed=result.status is CommandStatus.START_FAILED,
            exit_code=result.exit_code,
        )
        advice = (
            "Set --worktree-root or CODETEAM_WORKTREE_ROOT to a directory "
            "shared with Docker (for Colima, a directory under the current $HOME)."
        )
        return SandboxPreflightResult(
            available=False,
            category=category,
            error=f"Docker sandbox preflight failed ({category}): {detail}. {advice}",
        )


def _combined_detail(*values: str | None) -> str:
    detail = "\n".join(value.strip() for value in values if value and value.strip())
    return detail or "container did not start successfully"


def _preflight_failure_category(
    detail: str,
    *,
    start_failed: bool,
    exit_code: int | None,
) -> str:
    lowered = detail.lower()
    if start_failed and ("no such file" in lowered or "not found" in lowered):
        return "docker_cli_unavailable"
    if any(
        marker in lowered
        for marker in (
            "cannot connect to the docker daemon",
            "permission denied while trying to connect to the docker api",
            "docker daemon is not running",
        )
    ):
        return "docker_daemon_unavailable"
    if any(
        marker in lowered
        for marker in (
            "no such image",
            "pull access denied",
            "not found locally and pull policy is never",
        )
    ):
        return "sandbox_image_unavailable"
    if any(
        marker in lowered
        for marker in (
            "invalid mount config",
            "bind source path does not exist",
            "mounts denied",
        )
    ):
        return "workspace_mount_unavailable"
    if exit_code == 125:
        return "sandbox_start_failed"
    return "sandbox_start_failed"
