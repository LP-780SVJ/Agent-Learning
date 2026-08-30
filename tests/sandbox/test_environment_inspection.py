from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from codeteam.agent.runtime_tools import RuntimeEvidence, create_runtime_tools
from codeteam.execution.models import CommandResult, CommandStatus
from codeteam.execution.safe_execution_service import SafeExecutionService
from codeteam.sandbox.environment_inspection import (
    DockerEnvironmentInspector,
    EnvironmentInspectionArgs,
    EnvironmentInspectionResult,
)
from codeteam.schemas.tool_calls import ToolCall


class ProbeRunner:
    def __init__(self, available: bool) -> None:
        self.available = available
        self.contexts = []

    def run(self, context):
        self.contexts.append(context)
        return CommandResult(
            status=CommandStatus.SUCCESS,
            argv=context.argv,
            cwd=context.cwd,
            exit_code=0,
            stdout=json.dumps({"runtime_available": self.available}),
        )


class FailedProbeRunner:
    def run(self, context):
        return CommandResult(
            status=CommandStatus.NONZERO_EXIT,
            argv=context.argv,
            cwd=context.cwd,
            exit_code=1,
            stderr="fixed probe failed",
        )


def test_module_probe_runs_in_read_only_verification_sandbox(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="x"\ndependencies=["requests"]\n', encoding="utf-8"
    )
    runner = ProbeRunner(True)

    result = DockerEnvironmentInspector(runner=runner).inspect(
        tmp_path, EnvironmentInspectionArgs(python_module="requests")
    )

    assert result.runtime_available is True
    assert result.declared_by_project is True
    assert result.environment == "verification_sandbox"
    assert result.warning is None
    assert len(runner.contexts) == 1
    context = runner.contexts[0]
    assert context.argv[:2] == ("python", "-c")
    assert context.argv[-2:] == ("python_module", "requests")
    assert not context.profile.workspace_write


def test_host_availability_is_irrelevant_when_sandbox_reports_missing(
    tmp_path: Path,
) -> None:
    result = DockerEnvironmentInspector(runner=ProbeRunner(False)).inspect(
        tmp_path, EnvironmentInspectionArgs(python_module="pytest")
    )

    assert result.runtime_available is False
    assert result.declared_by_project is None


def test_available_but_undeclared_is_explicitly_nonportable(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\n', encoding="utf-8")

    result = DockerEnvironmentInspector(runner=ProbeRunner(True)).inspect(
        tmp_path, EnvironmentInspectionArgs(python_module="yaml")
    )

    assert result.runtime_available is True
    assert result.declared_by_project is False
    assert result.warning is not None


def test_declared_but_missing_keeps_the_two_facts_separate(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="x"\ndependencies=["requests>=2"]\n', encoding="utf-8"
    )

    result = DockerEnvironmentInspector(runner=ProbeRunner(False)).inspect(
        tmp_path, EnvironmentInspectionArgs(python_module="requests")
    )

    assert result.runtime_available is False
    assert result.declared_by_project is True


def test_probe_execution_failure_is_not_reported_as_clean_absence(
    tmp_path: Path,
) -> None:
    result = DockerEnvironmentInspector(runner=FailedProbeRunner()).inspect(
        tmp_path, EnvironmentInspectionArgs(python_module="yaml")
    )

    assert result.runtime_available is False
    assert result.error == "fixed probe failed"


def test_executable_probe_accepts_only_a_bare_name(tmp_path: Path) -> None:
    runner = ProbeRunner(True)
    result = DockerEnvironmentInspector(runner=runner).inspect(
        tmp_path, EnvironmentInspectionArgs(executable="git")
    )

    assert result.kind == "executable"
    assert runner.contexts[0].argv[-2:] == ("executable", "git")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"python_module": "yaml;open('/tmp/x','w')"},
        {"python_module": "yaml", "executable": "git"},
        {"executable": "sh -c whoami"},
        {},
    ],
)
def test_model_cannot_supply_code_or_ambiguous_probe(kwargs: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        EnvironmentInspectionArgs(**kwargs)


class FixedInspector:
    def inspect(self, workspace_root, request):
        del workspace_root
        return EnvironmentInspectionResult(
            kind="python_module",
            name=request.python_module or "",
            runtime_available=True,
            declared_by_project=False,
        )


def test_runtime_tool_observes_without_changing_completion_evidence(
    tmp_path: Path,
) -> None:
    evidence = RuntimeEvidence()
    registry = create_runtime_tools(
        workspace_root=tmp_path,
        task_id="inspect",
        checkpoint_state_root=tmp_path / "checkpoints",
        safe_execution=SafeExecutionService(),
        evidence=evidence,
        environment_inspector=FixedInspector(),
    )

    result = registry.execute(
        ToolCall(
            call_id="inspect-1",
            name="inspect_environment",
            arguments={"python_module": "yaml"},
        )
    )

    assert result.success
    assert json.loads(result.content)["runtime_available"] is True
    assert evidence.workspace_version == 0
    assert evidence.verification == []
    assert evidence.git_diff_checked_version is None
    schema = next(
        item for item in registry.describe() if item["name"] == "inspect_environment"
    )
    properties = schema["arguments"]["properties"]
    assert set(properties) == {"python_module", "executable"}
