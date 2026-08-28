from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from codeteam.agent.runtime import CodingAgentRuntime
from codeteam.agent.runtime_models import (
    CodingAgentRunRequest,
    RuntimeStatus,
    VerificationOutcomeCategory,
)
from codeteam.execution.models import CommandResult, CommandStatus
from codeteam.execution.safe_execution_service import SafeExecutionService
from codeteam.sandbox.models import SandboxProfile
from codeteam.sandbox.preflight import SandboxPreflightResult
from codeteam.sandbox.verification_preflight import (
    DockerVerificationEnvironmentPreflight,
    VerificationEnvironmentCheckResult,
    VerificationEnvironmentMetadata,
)
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
    _git(repo, "config", "user.name", "Verification Test")
    _git(repo, "config", "user.email", "verification@example.com")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "baseline")
    return repo


class AvailableSandboxPreflight:
    def check(self, workspace_root: Path) -> SandboxPreflightResult:
        del workspace_root
        return SandboxPreflightResult(available=True)


def _metadata() -> VerificationEnvironmentMetadata:
    return VerificationEnvironmentMetadata(
        configured_image="codeteam-sandbox:latest",
        image_id="sha256:test-image",
        python_version="Python 3.11.15",
        pytest_version="pytest 9.1.1",
    )


class FailedVerificationPreflight:
    def check(self, workspace_root, requirement):
        del workspace_root, requirement
        return VerificationEnvironmentCheckResult(
            available=False,
            category="pytest_unavailable",
            error="No module named pytest",
            metadata=_metadata().model_copy(update={"pytest_version": None}),
        )


class AvailableVerificationPreflight:
    def check(self, workspace_root, requirement):
        del workspace_root, requirement
        return VerificationEnvironmentCheckResult(
            available=True,
            category="verification_toolchain_ready",
            metadata=_metadata(),
        )


class SpyModel:
    def __init__(self, outputs: list[dict[str, object]]) -> None:
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
            test_commands=[
                SimpleNamespace(
                    model_dump=lambda **kwargs: {
                        "category": "test",
                        "command": "uv run pytest tests/ -q",
                        "source": "AGENTS.md",
                    }
                )
            ],
            diagnostics=[],
        )


class MissingPytestSandbox:
    def run(self, context) -> CommandResult:
        return CommandResult(
            status=CommandStatus.NONZERO_EXIT,
            argv=context.argv,
            cwd=context.cwd,
            exit_code=1,
            stderr="/usr/local/bin/python: No module named pytest",
        )


class AssertionFailingSandbox:
    def run(self, context) -> CommandResult:
        return CommandResult(
            status=CommandStatus.NONZERO_EXIT,
            argv=context.argv,
            cwd=context.cwd,
            exit_code=1,
            stderr="1 failed, AssertionError: expected 2",
        )


class ProfileRecordingSandbox(AssertionFailingSandbox):
    def __init__(self) -> None:
        self.profiles: list[SandboxProfile] = []

    def run(self, context) -> CommandResult:
        self.profiles.append(context.profile)
        return super().run(context)


def _request(repo: Path) -> CodingAgentRunRequest:
    return CodingAgentRunRequest(
        task_id="verification-contract",
        task="fix VALUE",
        workspace_root=repo,
        provider_id="spy",
        model_id="spy",
        verification_commands=(("python", "-m", "pytest", "tests", "-q"),),
    )


def test_verification_preflight_failure_stops_before_provider_or_repair(
    tmp_path: Path,
) -> None:
    model = SpyModel([])

    result = CodingAgentRuntime(
        model_client=model,
        context_service=StubContext(),
        sandbox_preflight=AvailableSandboxPreflight(),
        verification_preflight=FailedVerificationPreflight(),
    ).run(_request(_repo(tmp_path)))

    assert result.status is RuntimeStatus.PAUSED
    assert result.failure_category == "verification_environment_failed"
    assert result.verification_preflight_available is False
    assert result.verification_preflight_category == "pytest_unavailable"
    assert result.steps_used == 0
    assert result.tool_calls_used == 0
    assert result.repair_attempts == 0
    assert result.input_tokens == 0
    assert result.output_tokens == 0
    assert model.requests == []
    assert "repeated_action" not in result.events


def test_runtime_module_missing_halts_without_second_provider_turn(
    tmp_path: Path,
) -> None:
    model = SpyModel(
        [
            {
                "tool_calls": [
                    {
                        "name": "run_tests",
                        "arguments": {
                            "argv": ["python", "-m", "pytest", "tests", "-q"]
                        },
                    }
                ]
            }
        ]
    )

    result = CodingAgentRuntime(
        model_client=model,
        safe_execution=SafeExecutionService(
            sandbox_runner=MissingPytestSandbox()
        ),
        context_service=StubContext(),
        sandbox_preflight=AvailableSandboxPreflight(),
        verification_preflight=AvailableVerificationPreflight(),
    ).run(_request(_repo(tmp_path)))

    assert result.status is RuntimeStatus.PAUSED
    assert result.failure_category == "verification_environment_failed"
    assert result.repair_attempts == 0
    assert len(model.requests) == 1
    assert result.verification[0].category is VerificationOutcomeCategory.ENVIRONMENT_FAILED
    assert result.verification[0].environment_failure_category == "pytest_unavailable"


def test_real_pytest_assertion_failure_remains_task_feedback(
    tmp_path: Path,
) -> None:
    model = SpyModel(
        [
            {
                "tool_calls": [
                    {
                        "name": "run_tests",
                        "arguments": {
                            "argv": ["python", "-m", "pytest", "tests", "-q"]
                        },
                    }
                ]
            },
            {
                "status": "failed",
                "summary": "test assertion still fails",
                "tests_passed": False,
                "error": "assertion failure",
            },
        ]
    )

    result = CodingAgentRuntime(
        model_client=model,
        safe_execution=SafeExecutionService(
            sandbox_runner=AssertionFailingSandbox()
        ),
        context_service=StubContext(),
        sandbox_preflight=AvailableSandboxPreflight(),
        verification_preflight=AvailableVerificationPreflight(),
    ).run(_request(_repo(tmp_path)))

    assert result.status is RuntimeStatus.FAILED
    assert result.failure_category != "verification_environment_failed"
    assert len(model.requests) == 2
    assert result.verification[0].category is VerificationOutcomeCategory.TEST_FAILED
    assert result.verification[0].environment_failure_category is None


def test_prompt_marks_task_specific_verification_as_authoritative(
    tmp_path: Path,
) -> None:
    model = SpyModel(
        [
            {
                "status": "failed",
                "summary": "stop",
                "tests_passed": False,
                "error": "stop",
            }
        ]
    )

    CodingAgentRuntime(
        model_client=model,
        context_service=StubContext(),
        sandbox_preflight=AvailableSandboxPreflight(),
        verification_preflight=AvailableVerificationPreflight(),
    ).run(_request(_repo(tmp_path)))

    system = json.loads(model.requests[0][0].content or "{}")
    user = json.loads(model.requests[0][1].content or "{}")
    priority = system["verification_command_priority"]
    assert "authoritative" in priority
    assert "not substitutes" in priority
    assert user["task_verification_commands"] == [
        ["python", "-m", "pytest", "tests", "-q"]
    ]
    assert user["initial_context"]["visible_test_commands"][0]["command"] == (
        "uv run pytest tests/ -q"
    )


def test_runtime_and_verification_preflight_share_configured_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_preflight_images: list[str] = []

    def ready(self, workspace_root, requirement):
        del workspace_root, requirement
        observed_preflight_images.append(self._profile.image)
        return VerificationEnvironmentCheckResult(
            available=True,
            category="verification_toolchain_ready",
            metadata=VerificationEnvironmentMetadata(
                configured_image=self._profile.image,
                python_version="Python 3.11.15",
                pytest_version="pytest 9.1.1",
            ),
        )

    monkeypatch.setattr(DockerVerificationEnvironmentPreflight, "check", ready)
    sandbox = ProfileRecordingSandbox()
    model = SpyModel(
        [
            {
                "tool_calls": [
                    {
                        "name": "run_tests",
                        "arguments": {
                            "argv": ["python", "-m", "pytest", "tests", "-q"]
                        },
                    }
                ]
            },
            {
                "status": "failed",
                "summary": "test assertion still fails",
                "tests_passed": False,
                "error": "assertion failure",
            },
        ]
    )
    profile = SandboxProfile(image="codeteam-sandbox:contract-test")

    CodingAgentRuntime(
        model_client=model,
        safe_execution=SafeExecutionService(sandbox_runner=sandbox),
        context_service=StubContext(),
        sandbox_preflight=AvailableSandboxPreflight(),
        sandbox_profile=profile,
    ).run(_request(_repo(tmp_path)))

    assert observed_preflight_images == [profile.image]
    assert [item.image for item in sandbox.profiles] == [profile.image]
