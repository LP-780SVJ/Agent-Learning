from __future__ import annotations

from pathlib import Path

from codeteam.execution.models import CommandResult, CommandStatus
from codeteam.sandbox.models import DEFAULT_SANDBOX_IMAGE, SandboxExecutionContext
from codeteam.sandbox.verification_preflight import (
    PYTEST_VERSION_PROBE,
    PYTHON_VERSION_PROBE,
    DockerVerificationEnvironmentPreflight,
    SandboxImageIdentity,
    VerificationEnvironmentRequirement,
    classify_verification_environment_failure,
)


class SequenceRunner:
    def __init__(self, results: list[CommandResult]) -> None:
        self.results = results
        self.contexts: list[SandboxExecutionContext] = []

    def run(self, context: SandboxExecutionContext) -> CommandResult:
        self.contexts.append(context)
        return self.results.pop(0)


class StubImageInspector:
    def inspect(self, image: str) -> SandboxImageIdentity:
        assert image == DEFAULT_SANDBOX_IMAGE
        return SandboxImageIdentity(
            image_id="sha256:image-id",
            image_digest="codeteam-sandbox@sha256:digest",
        )


def _result(
    argv: tuple[str, ...],
    *,
    status: CommandStatus,
    exit_code: int | None,
    stdout: str = "",
    stderr: str = "",
) -> CommandResult:
    return CommandResult(
        status=status,
        argv=argv,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
    )


def _requirement() -> VerificationEnvironmentRequirement:
    return VerificationEnvironmentRequirement.from_commands(
        (("python", "-m", "pytest", "tests/task.py", "-q"),)
    )


def test_python_and_pytest_ready_return_auditable_metadata(tmp_path: Path) -> None:
    runner = SequenceRunner(
        [
            _result(
                PYTHON_VERSION_PROBE,
                status=CommandStatus.SUCCESS,
                exit_code=0,
                stdout="Python 3.11.15\n",
            ),
            _result(
                PYTEST_VERSION_PROBE,
                status=CommandStatus.SUCCESS,
                exit_code=0,
                stdout="pytest 9.1.1\n",
            ),
        ]
    )

    result = DockerVerificationEnvironmentPreflight(
        runner=runner,
        image_inspector=StubImageInspector(),
    ).check(tmp_path, _requirement())

    assert result.available
    assert result.category == "verification_toolchain_ready"
    assert result.metadata.configured_image == DEFAULT_SANDBOX_IMAGE
    assert result.metadata.image_id == "sha256:image-id"
    assert result.metadata.image_digest == "codeteam-sandbox@sha256:digest"
    assert result.metadata.python_version == "Python 3.11.15"
    assert result.metadata.pytest_version == "pytest 9.1.1"
    assert result.metadata.probe_argv == (
        PYTHON_VERSION_PROBE,
        PYTEST_VERSION_PROBE,
    )
    assert all(not context.profile.workspace_write for context in runner.contexts)
    assert all(
        context.profile.image == DEFAULT_SANDBOX_IMAGE
        for context in runner.contexts
    )


def test_pytest_missing_is_not_sandbox_infrastructure_failure(tmp_path: Path) -> None:
    runner = SequenceRunner(
        [
            _result(
                PYTHON_VERSION_PROBE,
                status=CommandStatus.SUCCESS,
                exit_code=0,
                stdout="Python 3.11.15\n",
            ),
            _result(
                PYTEST_VERSION_PROBE,
                status=CommandStatus.NONZERO_EXIT,
                exit_code=1,
                stderr="/usr/local/bin/python: No module named pytest\n",
            ),
        ]
    )

    result = DockerVerificationEnvironmentPreflight(
        runner=runner,
        image_inspector=StubImageInspector(),
    ).check(tmp_path, _requirement())

    assert not result.available
    assert result.category == "pytest_unavailable"
    assert result.metadata.python_version == "Python 3.11.15"
    assert result.metadata.pytest_version is None


def test_missing_python_is_verification_environment_failure(tmp_path: Path) -> None:
    runner = SequenceRunner(
        [
            _result(
                PYTHON_VERSION_PROBE,
                status=CommandStatus.NONZERO_EXIT,
                exit_code=127,
                stderr='exec: "python": executable file not found in $PATH\n',
            )
        ]
    )

    result = DockerVerificationEnvironmentPreflight(
        runner=runner,
        image_inspector=StubImageInspector(),
    ).check(tmp_path, _requirement())

    assert not result.available
    assert result.category == "python_unavailable"
    assert result.metadata.probe_argv == (PYTHON_VERSION_PROBE,)


def test_non_python_pytest_contract_fails_closed_without_running_probe(
    tmp_path: Path,
) -> None:
    runner = SequenceRunner([])
    requirement = VerificationEnvironmentRequirement.from_commands(
        (("uv", "run", "pytest", "tests"),)
    )

    result = DockerVerificationEnvironmentPreflight(
        runner=runner,
        image_inspector=StubImageInspector(),
    ).check(tmp_path, requirement)

    assert not result.available
    assert result.category == "unsupported_verification_contract"
    assert runner.contexts == []


def test_assertion_failure_is_not_misclassified_as_environment_failure() -> None:
    assertion = _result(
        ("python", "-m", "pytest", "tests/task.py"),
        status=CommandStatus.NONZERO_EXIT,
        exit_code=1,
        stderr="1 failed, AssertionError: expected 2",
    )
    missing_module = assertion.model_copy(
        update={"stderr": "/usr/local/bin/python: No module named pytest"}
    )

    assert (
        classify_verification_environment_failure(assertion.argv, assertion) is None
    )
    assert (
        classify_verification_environment_failure(
            missing_module.argv,
            missing_module,
        )
        == "pytest_unavailable"
    )
