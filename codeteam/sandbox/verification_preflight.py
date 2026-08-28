from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from codeteam.execution.models import CommandRequest, CommandResult, CommandStatus
from codeteam.execution.runner import CommandRunner
from codeteam.sandbox.docker_runner import DockerRunner
from codeteam.sandbox.models import SandboxExecutionContext, SandboxProfile

PYTHON_VERSION_PROBE = ("python", "--version")
PYTEST_VERSION_PROBE = ("python", "-m", "pytest", "--version")


class VerificationCapability(str, Enum):
    PYTHON = "python"
    PYTEST = "pytest"


class VerificationEnvironmentRequirement(BaseModel):
    """The intentionally small Week4 logical verification contract."""

    capabilities: tuple[VerificationCapability, ...] = (
        VerificationCapability.PYTHON,
        VerificationCapability.PYTEST,
    )
    required_commands: tuple[tuple[str, ...], ...] = ()
    unsupported_commands: tuple[tuple[str, ...], ...] = ()

    @classmethod
    def from_commands(
        cls,
        commands: tuple[tuple[str, ...], ...],
    ) -> VerificationEnvironmentRequirement:
        unsupported = tuple(
            command
            for command in commands
            if command[:3] != ("python", "-m", "pytest")
        )
        return cls(
            required_commands=commands,
            unsupported_commands=unsupported,
        )


class SandboxImageIdentity(BaseModel):
    image_id: str | None = None
    image_digest: str | None = None
    error: str | None = None


class VerificationEnvironmentMetadata(BaseModel):
    configured_image: str
    image_id: str | None = None
    image_digest: str | None = None
    image_identity_error: str | None = None
    python_version: str | None = None
    pytest_version: str | None = None
    probe_argv: tuple[tuple[str, ...], ...] = ()
    capabilities: tuple[VerificationCapability, ...] = ()


class VerificationEnvironmentCheckResult(BaseModel):
    available: bool
    category: str
    error: str | None = None
    metadata: VerificationEnvironmentMetadata


class VerificationEnvironmentPreflight(Protocol):
    def check(
        self,
        workspace_root: Path,
        requirement: VerificationEnvironmentRequirement,
    ) -> VerificationEnvironmentCheckResult: ...


class VerificationSandboxRunner(Protocol):
    def run(self, context: SandboxExecutionContext) -> CommandResult: ...


class ImageInspector(Protocol):
    def inspect(self, image: str) -> SandboxImageIdentity: ...


class DockerImageInspector:
    """Resolve immutable local-image evidence with a Runtime-owned fixed command."""

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self._runner = runner or CommandRunner()

    def inspect(self, image: str) -> SandboxImageIdentity:
        root = Path.cwd().resolve()
        result = self._runner.run(
            CommandRequest(
                argv=(
                    "docker",
                    "image",
                    "inspect",
                    "--format",
                    "{{json .}}",
                    image,
                ),
                cwd=root,
                workspace_root=root,
                reason="Resolve verification sandbox image identity",
                timeout_seconds=10,
            )
        )
        if result.status is not CommandStatus.SUCCESS:
            return SandboxImageIdentity(error=_result_detail(result))
        try:
            payload = json.loads(result.stdout.strip())
        except (json.JSONDecodeError, TypeError) as error:
            return SandboxImageIdentity(error=f"Invalid docker image metadata: {error}")
        if not isinstance(payload, dict):
            return SandboxImageIdentity(error="Docker image metadata was not an object.")
        image_id = payload.get("Id")
        repo_digests = payload.get("RepoDigests")
        digest = (
            repo_digests[0]
            if isinstance(repo_digests, list)
            and repo_digests
            and isinstance(repo_digests[0], str)
            else None
        )
        return SandboxImageIdentity(
            image_id=image_id if isinstance(image_id, str) else None,
            image_digest=digest,
        )


class DockerVerificationEnvironmentPreflight:
    """Verify the fixed Python+pytest toolchain before any Provider call."""

    def __init__(
        self,
        *,
        runner: VerificationSandboxRunner | None = None,
        profile: SandboxProfile | None = None,
        image_inspector: ImageInspector | None = None,
    ) -> None:
        self._runner = runner or DockerRunner()
        self._profile = profile or SandboxProfile(workspace_write=False)
        self._image_inspector = image_inspector or DockerImageInspector()

    def check(
        self,
        workspace_root: Path,
        requirement: VerificationEnvironmentRequirement,
    ) -> VerificationEnvironmentCheckResult:
        root = workspace_root.resolve(strict=True)
        identity = self._image_inspector.inspect(self._profile.image)
        metadata = VerificationEnvironmentMetadata(
            configured_image=self._profile.image,
            image_id=identity.image_id,
            image_digest=identity.image_digest,
            image_identity_error=identity.error,
            capabilities=requirement.capabilities,
        )
        if requirement.unsupported_commands:
            return VerificationEnvironmentCheckResult(
                available=False,
                category="unsupported_verification_contract",
                error=(
                    "The current verification environment contract supports only "
                    "workspace-relative 'python -m pytest' commands."
                ),
                metadata=metadata,
            )

        attempted: list[tuple[str, ...]] = []
        python_result = self._run_probe(root, PYTHON_VERSION_PROBE)
        attempted.append(PYTHON_VERSION_PROBE)
        metadata = metadata.model_copy(
            update={
                "probe_argv": tuple(attempted),
                "python_version": (
                    _version_text(python_result)
                    if python_result.status is CommandStatus.SUCCESS
                    else None
                ),
            }
        )
        if python_result.status is not CommandStatus.SUCCESS:
            return self._failure(
                category="python_unavailable",
                result=python_result,
                metadata=metadata,
            )

        pytest_result = self._run_probe(root, PYTEST_VERSION_PROBE)
        attempted.append(PYTEST_VERSION_PROBE)
        metadata = metadata.model_copy(
            update={
                "probe_argv": tuple(attempted),
                "pytest_version": (
                    _version_text(pytest_result)
                    if pytest_result.status is CommandStatus.SUCCESS
                    else None
                ),
            }
        )
        if pytest_result.status is not CommandStatus.SUCCESS:
            category = (
                "pytest_unavailable"
                if _pytest_is_unavailable(pytest_result)
                else "verification_toolchain_unavailable"
            )
            return self._failure(
                category=category,
                result=pytest_result,
                metadata=metadata,
            )

        return VerificationEnvironmentCheckResult(
            available=True,
            category="verification_toolchain_ready",
            metadata=metadata,
        )

    def _run_probe(self, root: Path, argv: tuple[str, ...]) -> CommandResult:
        try:
            return self._runner.run(
                SandboxExecutionContext(
                    argv=argv,
                    workspace_root=root,
                    cwd=root,
                    profile=self._profile,
                )
            )
        except Exception as error:  # noqa: BLE001 - normalize infrastructure probe
            return CommandResult(
                status=CommandStatus.START_FAILED,
                argv=argv,
                cwd=root,
                error=f"{type(error).__name__}: {error}",
            )

    @staticmethod
    def _failure(
        *,
        category: str,
        result: CommandResult,
        metadata: VerificationEnvironmentMetadata,
    ) -> VerificationEnvironmentCheckResult:
        detail = _result_detail(result)
        return VerificationEnvironmentCheckResult(
            available=False,
            category=category,
            error=(
                "Verification environment preflight failed "
                f"({category}) in image {metadata.configured_image}: {detail}"
            ),
            metadata=metadata,
        )


def classify_verification_environment_failure(
    argv: tuple[str, ...],
    result: CommandResult,
) -> str | None:
    """Classify launch/toolchain failures without treating assertions as infra."""

    if result.exit_code == 0 and result.status is CommandStatus.SUCCESS:
        return None
    detail = _result_detail(result).lower()
    if argv[:3] == ("python", "-m", "pytest"):
        if _pytest_is_unavailable(result):
            return "pytest_unavailable"
        if result.status is CommandStatus.START_FAILED or any(
            marker in detail
            for marker in (
                "executable file not found",
                "python: not found",
                "no such file or directory: 'python'",
            )
        ):
            return "python_unavailable"
    return None


def _pytest_is_unavailable(result: CommandResult) -> bool:
    detail = _result_detail(result).lower()
    return any(
        marker in detail
        for marker in (
            "no module named pytest",
            "no module named 'pytest'",
            "pytest: not found",
        )
    )


def _version_text(result: CommandResult) -> str:
    return (result.stdout or result.stderr).strip().splitlines()[0]


def _result_detail(result: CommandResult) -> str:
    detail = "\n".join(
        value.strip()
        for value in (result.error, result.stderr, result.stdout)
        if value and value.strip()
    )
    return detail[:2_000] or f"command status={result.status.value}"
