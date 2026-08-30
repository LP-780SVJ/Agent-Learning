"""Independent grader for agent coding benchmarks."""
from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path

from codeteam.evaluation.agent_models import (
    AgentEvalTask,
    EvalRunConfig,
    GraderCommandResult,
    GradeResult,
    PatchActorResult,
    PatchActorStatus,
)
from codeteam.git.workspace import GitWorkspace

OUTPUT_LIMIT = 8_000
RUNTIME_ARTIFACT_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
}
RUNTIME_ARTIFACT_SUFFIXES = {
    ".pyc",
    ".pyo",
}


class AgentGrader:
    """Run hidden acceptance and public regression checks for a task workspace."""

    def __init__(
        self,
        *,
        project_root: Path | None = None,
        hidden_root: Path | None = None,
    ) -> None:
        self.project_root = (project_root or _default_project_root()).resolve()
        self.hidden_root = (hidden_root or self.project_root / "eval_hidden" / "week4").resolve()
        self.python = self.project_root / ".venv" / "bin" / "python"

    def verification_environment_metadata(self) -> dict[str, object]:
        """Record the trusted-host side of the logical Python+pytest contract."""

        python = self._run_metadata_probe((str(self.python), "--version"))
        pytest = self._run_metadata_probe(
            (str(self.python), "-m", "pytest", "--version")
        )
        return {
            "python_executable": str(self.python),
            "python_version": python[0],
            "pytest_version": pytest[0],
            "python_probe_error": python[1],
            "pytest_probe_error": pytest[1],
        }

    def _run_metadata_probe(
        self,
        argv: tuple[str, ...],
    ) -> tuple[str | None, str | None]:
        try:
            result = subprocess.run(  # noqa: UP022
                list(argv),
                cwd=self.project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return None, f"{type(error).__name__}: {error}"
        detail = (result.stdout or result.stderr).strip().splitlines()
        version = detail[0] if result.returncode == 0 and detail else None
        probe_error = (
            None
            if result.returncode == 0
            else (detail[0] if detail else "probe failed")
        )
        return version, probe_error

    def grade(
        self,
        *,
        task: AgentEvalTask,
        workspace_root: Path,
        actor_result: PatchActorResult,
        config: EvalRunConfig,
        pristine_acceptance_results: tuple[GraderCommandResult, ...] = (),
        pristine_task_verification_results: tuple[GraderCommandResult, ...] = (),
    ) -> GradeResult:
        workspace_root = workspace_root.resolve()
        pristine_acceptance_passed = bool(pristine_acceptance_results) and all(
            result.passed for result in pristine_acceptance_results
        )
        pristine_task_verification_passed = bool(
            pristine_task_verification_results
        ) and all(result.passed for result in pristine_task_verification_results)
        acceptance_results = tuple(
            self._run_command(
                command=command,
                workspace_root=workspace_root,
                timeout_seconds=min(task.budget.timeout_seconds, config.task_timeout_seconds),
            )
            for command in task.acceptance_commands
        )
        regression_results = tuple(
            self._run_command(
                command=command,
                workspace_root=workspace_root,
                timeout_seconds=min(task.budget.timeout_seconds, config.task_timeout_seconds),
            )
            for command in task.verification_commands
        )
        task_verification_results = tuple(
            self._run_command(
                command=command,
                workspace_root=workspace_root,
                timeout_seconds=min(task.budget.timeout_seconds, config.task_timeout_seconds),
            )
            for command in task.task_verification_commands
        )

        acceptance_passed = bool(acceptance_results) and all(
            result.passed for result in acceptance_results
        )
        regression_passed = all(result.passed for result in regression_results)
        task_verification_passed = all(
            result.passed for result in task_verification_results
        )
        within_budget = (
            actor_result.duration_ms
            <= min(task.budget.timeout_seconds, config.task_timeout_seconds) * 1000
            and actor_result.steps <= min(task.budget.max_steps, config.max_steps)
            and actor_result.repair_attempts <= config.max_repairs
        )
        changed_files = _filter_runtime_artifacts(
            tuple(change.path for change in GitWorkspace(workspace_root).changed_files())
        )
        safety_violations = self._find_safety_violations(changed_files)
        security_passed = not safety_violations
        actor_completed = actor_result.status == PatchActorStatus.COMPLETED
        success = (
            actor_completed
            and acceptance_passed
            and regression_passed
            and task_verification_passed
            and within_budget
            and security_passed
            and not pristine_acceptance_passed
            and not pristine_task_verification_passed
        )
        failure_category = _failure_category(
            actor_result=actor_result,
            acceptance_passed=acceptance_passed,
            regression_passed=regression_passed,
            task_verification_passed=task_verification_passed,
            within_budget=within_budget,
            security_passed=security_passed,
            pristine_acceptance_passed=pristine_acceptance_passed,
            pristine_task_verification_passed=pristine_task_verification_passed,
        )

        return GradeResult(
            success=success,
            acceptance_passed=acceptance_passed,
            regression_passed=regression_passed,
            task_verification_passed=task_verification_passed,
            within_budget=within_budget,
            security_passed=security_passed,
            pristine_acceptance_passed=pristine_acceptance_passed,
            pristine_task_verification_passed=pristine_task_verification_passed,
            acceptance_results=acceptance_results,
            regression_results=regression_results,
            task_verification_results=task_verification_results,
            pristine_acceptance_results=pristine_acceptance_results,
            pristine_task_verification_results=pristine_task_verification_results,
            changed_files=changed_files,
            safety_violations=tuple(safety_violations),
            failure_category=failure_category,
            error=actor_result.error if not success else None,
        )

    def check_pristine_acceptance(
        self,
        *,
        task: AgentEvalTask,
        workspace_root: Path,
        config: EvalRunConfig,
    ) -> tuple[GraderCommandResult, ...]:
        workspace_root = workspace_root.resolve()
        return tuple(
            self._run_command(
                command=command,
                workspace_root=workspace_root,
                timeout_seconds=min(task.budget.timeout_seconds, config.task_timeout_seconds),
            )
            for command in task.acceptance_commands
        )

    def check_pristine_task_verification(
        self,
        *,
        task: AgentEvalTask,
        workspace_root: Path,
        config: EvalRunConfig,
    ) -> tuple[GraderCommandResult, ...]:
        return tuple(
            self._run_command(
                command=command,
                workspace_root=workspace_root.resolve(),
                timeout_seconds=min(task.budget.timeout_seconds, config.task_timeout_seconds),
            )
            for command in task.task_verification_commands
        )

    def _run_command(
        self,
        *,
        command: str,
        workspace_root: Path,
        timeout_seconds: int,
    ) -> GraderCommandResult:
        formatted = _format_command(
            command,
            python=self.python,
            workspace_root=workspace_root,
            project_root=self.project_root,
            hidden_root=self.hidden_root,
        )
        argv = tuple(shlex.split(formatted))
        started = time.monotonic()
        env = os.environ.copy()
        env["PYTHONPATH"] = _prepend_path(
            str(workspace_root),
            env.get("PYTHONPATH", ""),
        )
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            result = subprocess.run(  # noqa: UP022
                list(argv),
                cwd=workspace_root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            return GraderCommandResult(
                command=formatted,
                argv=argv,
                exit_code=None,
                duration_ms=_elapsed_ms(started),
                stdout=_limit(error.stdout or ""),
                stderr=_limit(error.stderr or ""),
                timed_out=True,
                error=f"timed out after {timeout_seconds}s",
            )
        except OSError as error:
            return GraderCommandResult(
                command=formatted,
                argv=argv,
                exit_code=None,
                duration_ms=_elapsed_ms(started),
                error=f"{type(error).__name__}: {error}",
            )

        return GraderCommandResult(
            command=formatted,
            argv=argv,
            exit_code=result.returncode,
            duration_ms=_elapsed_ms(started),
            stdout=_limit(result.stdout),
            stderr=_limit(result.stderr),
        )

    @staticmethod
    def _find_safety_violations(changed_files: tuple[str, ...]) -> list[str]:
        violations: list[str] = []
        for raw_path in changed_files:
            path = Path(raw_path)
            parts = path.parts
            if path.is_absolute():
                violations.append(f"absolute changed path: {raw_path}")
            if ".." in parts:
                violations.append(f"path traversal in changed path: {raw_path}")
            if parts and parts[0] == ".git":
                violations.append(f"git metadata changed: {raw_path}")
            if parts[:2] == ("tests", "task_verification"):
                violations.append(f"public task oracle changed: {raw_path}")
        return violations


def _format_command(
    command: str,
    *,
    python: Path,
    workspace_root: Path,
    project_root: Path,
    hidden_root: Path,
) -> str:
    return command.format(
        python=str(python),
        workspace=str(workspace_root),
        project_root=str(project_root),
        hidden_root=str(hidden_root),
    )


def _failure_category(
    *,
    actor_result: PatchActorResult,
    acceptance_passed: bool,
    regression_passed: bool,
    within_budget: bool,
    security_passed: bool,
    pristine_acceptance_passed: bool,
    task_verification_passed: bool = True,
    pristine_task_verification_passed: bool = False,
) -> str | None:
    if pristine_task_verification_passed:
        return "visible_oracle_not_discriminative"
    if actor_result.status == PatchActorStatus.PROVIDER_BLOCKED:
        return "provider_blocked"
    if actor_result.status == PatchActorStatus.ENVIRONMENT_BLOCKED:
        return actor_result.failure_category or "sandbox_unavailable"
    if actor_result.status == PatchActorStatus.NO_PATCH:
        return "no_patch"
    if actor_result.status == PatchActorStatus.PATCH_FAILED:
        return "patch_failed"
    if actor_result.status == PatchActorStatus.FAILED:
        return actor_result.failure_category or "actor_failed"
    if not security_passed:
        return "security_failed"
    if not within_budget:
        return "budget_exceeded"
    if pristine_acceptance_passed:
        return "oracle_not_discriminative"
    if not task_verification_passed:
        return "task_verification_failed"
    if not acceptance_passed:
        return "acceptance_failed"
    if not regression_passed:
        return "regression_failed"
    return None


def _prepend_path(path: str, existing: str) -> str:
    if not existing:
        return path
    return f"{path}{os.pathsep}{existing}"


def _filter_runtime_artifacts(paths: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        path
        for path in paths
        if not _is_runtime_artifact(path)
    )


def _is_runtime_artifact(path: str) -> bool:
    candidate = Path(path)
    if any(part in RUNTIME_ARTIFACT_PARTS for part in candidate.parts):
        return True
    return candidate.suffix in RUNTIME_ARTIFACT_SUFFIXES


def _limit(value: str | bytes) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if len(value) <= OUTPUT_LIMIT:
        return value
    return value[:OUTPUT_LIMIT] + "\n... <truncated>"


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]
