"""Task-level agent evaluation runner."""
from __future__ import annotations

import hashlib
import json
import shlex
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from codeteam.agent.runtime_models import (
    CodingAgentRunRequest,
    CodingAgentRunResult,
    CompactionMode,
    RuntimeStatus,
)
from codeteam.agent.verification import normalize_verification_argv
from codeteam.evaluation.agent_grader import AgentGrader
from codeteam.evaluation.agent_models import (
    AgentEvalRunSummary,
    AgentEvalSplit,
    AgentEvalTask,
    AgentEvalTaskResult,
    EvalRunConfig,
    PatchActorResult,
    PatchActorStatus,
)
from codeteam.git.worktree import WorktreeManager

IGNORED_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "eval_hidden",
}


class CodingRuntime(Protocol):
    def run(self, request: CodingAgentRunRequest) -> CodingAgentRunResult: ...


class AgentEvalDatasetError(ValueError):
    """Raised when an agent eval JSONL suite is malformed."""


class AgentEvalRunner:
    """Run coding tasks in isolated workspaces and grade the result."""

    def __init__(
        self,
        *,
        project_root: Path | None = None,
        runtime: CodingRuntime,
        grader: AgentGrader | None = None,
        keep_workspaces: bool = False,
        provider_metadata: Callable[[], dict[str, object]] | None = None,
    ) -> None:
        self.project_root = (project_root or _default_project_root()).resolve()
        self.runtime = runtime
        self.grader = grader or AgentGrader(project_root=self.project_root)
        self.keep_workspaces = keep_workspaces
        self.provider_metadata = provider_metadata

    def run_suite(
        self,
        *,
        tasks: list[AgentEvalTask],
        config: EvalRunConfig,
        output_dir: Path,
    ) -> list[AgentEvalTaskResult]:
        output_dir.mkdir(parents=True, exist_ok=True)
        workspace_root = output_dir / "workspaces" / config.run_id
        workspace_root.mkdir(parents=True, exist_ok=True)

        results: list[AgentEvalTaskResult] = []
        for task in tasks:
            task_repo = workspace_root / "_repos" / _safe_name(task.task_id)
            task_workspace = workspace_root / "tasks" / _safe_name(task.task_id)
            pristine_workspace = workspace_root / "_pristine" / _safe_name(task.task_id)
            self._prepare_workspace(task=task, destination=pristine_workspace)
            pristine_acceptance_results = self.grader.check_pristine_acceptance(
                task=task,
                workspace_root=pristine_workspace,
                config=config,
            )
            pristine_task_verification_results = (
                self.grader.check_pristine_task_verification(
                    task=task,
                    workspace_root=pristine_workspace,
                    config=config,
                )
            )
            if not self.keep_workspaces:
                shutil.rmtree(pristine_workspace, ignore_errors=True)

            self._prepare_workspace(task=task, destination=task_repo)
            worktree = WorktreeManager(
                task_repo,
                worktree_root=task_workspace.parent,
            ).create(_safe_name(task.task_id), base_ref="HEAD")
            started = time.monotonic()
            runtime_result = self.runtime.run(
                CodingAgentRunRequest(
                    task_id=task.task_id,
                    task=task.prompt,
                    workspace_root=worktree.path,
                    provider_id=config.provider_id,
                    model_id=config.model_id,
                    context_budget=config.context_budget,
                    max_steps=min(task.budget.max_steps, config.max_steps),
                    max_tool_calls=max(1, min(task.budget.max_steps, config.max_steps) * 3),
                    max_repairs=min(task.budget.max_repairs, config.max_repairs),
                    max_protocol_repairs=config.max_protocol_repairs,
                    compaction_mode=CompactionMode(config.compaction_mode),
                    planning_enabled=config.planning_enabled,
                    verification_commands=_verification_argv(
                        task.verification_commands
                    ),
                    task_verification_commands=_verification_argv(
                        task.task_verification_commands
                    ),
                    checkpoint_state_root=(
                        task_repo.parent / "checkpoints" / _safe_name(task.task_id)
                    ),
                )
            )
            actor_result = _runtime_to_actor_result(runtime_result, config)
            actor_result = actor_result.model_copy(
                update={
                    "artifact_paths": _save_runtime_artifacts(
                        output_dir=output_dir,
                        result=runtime_result,
                    )
                }
            )
            grade = self.grader.grade(
                task=task,
                workspace_root=worktree.path,
                actor_result=actor_result,
                config=config,
                pristine_acceptance_results=pristine_acceptance_results,
                pristine_task_verification_results=(
                    pristine_task_verification_results
                ),
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            results.append(
                AgentEvalTaskResult(
                    run_id=config.run_id,
                    task_id=task.task_id,
                    split=task.split,
                    type=task.type,
                    difficulty=task.difficulty,
                    mode=config.mode,
                    provider_id=config.provider_id,
                    model_id=config.model_id,
                    success=grade.success,
                    actor_status=actor_result.status,
                    acceptance_passed=grade.acceptance_passed,
                    regression_passed=grade.regression_passed,
                    task_verification_passed=grade.task_verification_passed,
                    within_budget=grade.within_budget,
                    security_passed=grade.security_passed,
                    pristine_acceptance_passed=grade.pristine_acceptance_passed,
                    pristine_task_verification_passed=(
                        grade.pristine_task_verification_passed
                    ),
                    acceptance_results=grade.acceptance_results,
                    regression_results=grade.regression_results,
                    task_verification_results=grade.task_verification_results,
                    pristine_acceptance_results=grade.pristine_acceptance_results,
                    pristine_task_verification_results=(
                        grade.pristine_task_verification_results
                    ),
                    duration_ms=duration_ms,
                    steps=actor_result.steps,
                    model_duration_ms=actor_result.model_duration_ms,
                    tool_duration_ms=actor_result.tool_duration_ms,
                    repair_duration_ms=actor_result.repair_duration_ms,
                    changed_files=grade.changed_files,
                    patch_attempts=actor_result.patch_attempts,
                    repair_attempts=actor_result.repair_attempts,
                    protocol_repair_attempts=(
                        actor_result.protocol_repair_attempts
                    ),
                    tool_calls=actor_result.tool_calls,
                    input_tokens=actor_result.input_tokens,
                    output_tokens=actor_result.output_tokens,
                    cost_usd=actor_result.cost_usd,
                    artifact_paths=actor_result.artifact_paths,
                    failure_category=grade.failure_category,
                    error=grade.error,
                )
            )

        save_agent_eval_results(results, output_dir / "results.jsonl")
        summary = summarize_agent_eval_results(
            results,
            run_id=config.run_id,
            mode=config.mode,
        )
        (output_dir / "summary.json").write_text(
            json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        (output_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "run_id": config.run_id,
                    "mode": config.mode.value,
                    "provider_id": config.provider_id,
                    "model_id": config.model_id,
                    "planning_enabled": config.planning_enabled,
                    "repair_enabled": config.repair_enabled,
                    "compaction_mode": config.compaction_mode,
                    "context_budget": config.context_budget,
                    "max_protocol_repairs": config.max_protocol_repairs,
                    "task_count": len(tasks),
                    "tasks": [
                        {
                            "task_id": task.task_id,
                            "repo_fixture": str(task.repo_fixture),
                            "base_commit": task.base_commit,
                            "setup_patch": (
                                str(task.setup_patch)
                                if task.setup_patch is not None
                                else None
                            ),
                            "setup_patch_sha256": task.setup_patch_sha256,
                            "public_test_patch": (
                                str(task.public_test_patch)
                                if task.public_test_patch is not None
                                else None
                            ),
                            "public_test_patch_sha256": (
                                task.public_test_patch_sha256
                            ),
                            "oracle_review_status": task.oracle_review_status,
                        }
                        for task in tasks
                    ],
                    "keep_workspaces": self.keep_workspaces,
                    "pristine_oracle_check": True,
                    "provider_runtime": (
                        self.provider_metadata()
                        if self.provider_metadata is not None
                        else None
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if not self.keep_workspaces:
            shutil.rmtree(workspace_root, ignore_errors=True)
        return results

    def _prepare_workspace(
        self,
        *,
        task: AgentEvalTask,
        destination: Path,
    ) -> None:
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)

        source = _resolve_fixture_root(self.project_root, task.repo_fixture)
        archived = self._archive_fixture(
            source=source,
            base_commit=task.base_commit,
            destination=destination,
        )
        if not archived:
            if task.base_commit:
                raise AgentEvalDatasetError(
                    f"Unable to archive base_commit {task.base_commit!r} "
                    f"for fixture {task.repo_fixture}."
                )
            shutil.copytree(
                source,
                destination,
                ignore=shutil.ignore_patterns(*IGNORED_NAMES),
            )
        _init_git_repo(destination)
        if task.setup_patch is not None:
            self._apply_setup_patch(task=task, destination=destination)
        if task.public_test_patch is not None:
            self._apply_public_test_patch(task=task, destination=destination)

    def _apply_setup_patch(
        self,
        *,
        task: AgentEvalTask,
        destination: Path,
    ) -> None:
        patch_path = task.setup_patch
        if patch_path is None:
            return
        resolved = (
            patch_path.resolve()
            if patch_path.is_absolute()
            else (self.project_root / patch_path).resolve()
        )
        try:
            resolved.relative_to(self.project_root)
        except ValueError as error:
            raise AgentEvalDatasetError(
                f"Setup patch must be inside the project: {patch_path}"
            ) from error
        if not resolved.is_file():
            raise AgentEvalDatasetError(f"Setup patch does not exist: {patch_path}")

        patch_bytes = resolved.read_bytes()
        actual_sha256 = hashlib.sha256(patch_bytes).hexdigest()
        if task.setup_patch_sha256 != actual_sha256:
            raise AgentEvalDatasetError(
                f"Setup patch hash mismatch for {task.task_id}: "
                f"expected {task.setup_patch_sha256!r}, got {actual_sha256!r}"
            )

        apply_result = subprocess.run(  # noqa: UP022
            ["git", "apply", "--check", "-"],
            cwd=destination,
            input=patch_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            timeout=30,
            check=False,
        )
        if apply_result.returncode != 0:
            stderr = apply_result.stderr.decode("utf-8", errors="replace")
            raise AgentEvalDatasetError(
                f"Setup patch check failed for {task.task_id}: {stderr}"
            )
        apply_result = subprocess.run(  # noqa: UP022
            ["git", "apply", "-"],
            cwd=destination,
            input=patch_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            timeout=30,
            check=False,
        )
        if apply_result.returncode != 0:
            stderr = apply_result.stderr.decode("utf-8", errors="replace")
            raise AgentEvalDatasetError(
                f"Setup patch apply failed for {task.task_id}: {stderr}"
            )
        _commit_workspace_state(destination, message=f"seed {task.task_id}")

    def _apply_public_test_patch(
        self,
        *,
        task: AgentEvalTask,
        destination: Path,
    ) -> None:
        patch_path = task.public_test_patch
        if patch_path is None:
            return
        resolved = _resolve_pinned_patch(
            project_root=self.project_root,
            patch_path=patch_path,
            expected_sha256=task.public_test_patch_sha256,
            task_id=task.task_id,
            label="Public test",
        )
        _apply_patch_bytes(
            destination=destination,
            patch_bytes=resolved.read_bytes(),
            task_id=task.task_id,
            label="Public test",
        )
        _commit_workspace_state(
            destination,
            message=f"public verification {task.task_id}",
        )

    def _archive_fixture(
        self,
        *,
        source: Path,
        base_commit: str,
        destination: Path,
    ) -> bool:
        if not base_commit:
            return False
        try:
            if source == self.project_root:
                treeish = base_commit
            else:
                rel = source.relative_to(self.project_root).as_posix()
                treeish = f"{base_commit}:{rel}"
        except ValueError:
            return False

        archive = subprocess.run(  # noqa: UP022
            [
                "git",
                "-C",
                str(self.project_root),
                "archive",
                "--format=tar",
                f"--prefix={destination.name}/",
                treeish,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            timeout=30,
            check=False,
        )
        if archive.returncode != 0:
            return False

        extract = subprocess.run(  # noqa: UP022
            ["tar", "-x", "-C", str(destination.parent)],
            input=archive.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            timeout=30,
            check=False,
        )
        if extract.returncode != 0:
            if destination.exists():
                shutil.rmtree(destination)
            return False
        return destination.exists()


def load_agent_eval_tasks(path: Path) -> list[AgentEvalTask]:
    tasks: list[AgentEvalTask] = []
    errors: list[str] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            tasks.append(AgentEvalTask.model_validate_json(stripped))
        except (ValidationError, ValueError) as error:
            errors.append(f"{path}:{line_no}: {error}")
    if errors:
        raise AgentEvalDatasetError("\n".join(errors))
    return tasks


def filter_agent_eval_tasks(
    tasks: list[AgentEvalTask],
    *,
    split: AgentEvalSplit | None = None,
    task_ids: set[str] | None = None,
    limit: int | None = None,
) -> list[AgentEvalTask]:
    selected = [
        task
        for task in tasks
        if (split is None or task.split == split)
        and (task_ids is None or task.task_id in task_ids)
    ]
    if limit is not None:
        selected = selected[:limit]
    return selected


def save_agent_eval_results(
    results: list[AgentEvalTaskResult],
    output_path: Path,
) -> None:
    output_path.write_text(
        "".join(
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False) + "\n"
            for result in results
        ),
        encoding="utf-8",
    )


def summarize_agent_eval_results(
    results: list[AgentEvalTaskResult],
    *,
    run_id: str,
    mode,
) -> AgentEvalRunSummary:
    return AgentEvalRunSummary(
        run_id=run_id,
        mode=mode,
        task_count=len(results),
        success_count=sum(result.success for result in results),
        provider_blocked_count=sum(
            result.actor_status == PatchActorStatus.PROVIDER_BLOCKED
            for result in results
        ),
        protocol_repair_attempt_count=sum(
            result.protocol_repair_attempts for result in results
        ),
        protocol_failed_count=sum(
            result.failure_category == "invalid_final_output" for result in results
        ),
        acceptance_passed_count=sum(result.acceptance_passed for result in results),
        regression_passed_count=sum(result.regression_passed for result in results),
        task_verification_passed_count=sum(
            result.task_verification_passed for result in results
        ),
        security_passed_count=sum(result.security_passed for result in results),
        pristine_acceptance_passed_count=sum(
            result.pristine_acceptance_passed for result in results
        ),
        pristine_task_verification_passed_count=sum(
            result.pristine_task_verification_passed for result in results
        ),
    )


def make_run_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _verification_argv(
    source_commands: tuple[str, ...],
) -> tuple[tuple[str, ...], ...]:
    commands: list[tuple[str, ...]] = []
    for command in source_commands:
        formatted = command.format(
            python="python",
            workspace=".",
            project_root=".",
            hidden_root="<hidden-not-visible>",
        )
        commands.append(normalize_verification_argv(tuple(shlex.split(formatted))))
    return tuple(commands)


def _visible_verification_argv(
    task: AgentEvalTask,
) -> tuple[tuple[str, ...], ...]:
    """Backward-compatible adapter for callers using the Week4 name."""
    return _verification_argv(task.verification_commands)


def _resolve_pinned_patch(
    *,
    project_root: Path,
    patch_path: Path,
    expected_sha256: str | None,
    task_id: str,
    label: str,
) -> Path:
    resolved = (
        patch_path.resolve()
        if patch_path.is_absolute()
        else (project_root / patch_path).resolve()
    )
    try:
        resolved.relative_to(project_root)
    except ValueError as error:
        raise AgentEvalDatasetError(
            f"{label} patch must be inside the project: {patch_path}"
        ) from error
    if not resolved.is_file():
        raise AgentEvalDatasetError(f"{label} patch does not exist: {patch_path}")
    actual_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if expected_sha256 != actual_sha256:
        raise AgentEvalDatasetError(
            f"{label} patch hash mismatch for {task_id}: "
            f"expected {expected_sha256!r}, got {actual_sha256!r}"
        )
    return resolved


def _apply_patch_bytes(
    *,
    destination: Path,
    patch_bytes: bytes,
    task_id: str,
    label: str,
) -> None:
    for arguments in (["git", "apply", "--check", "-"], ["git", "apply", "-"]):
        result = subprocess.run(  # noqa: UP022
            arguments,
            cwd=destination,
            input=patch_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            raise AgentEvalDatasetError(
                f"{label} patch apply failed for {task_id}: {stderr}"
            )


def _runtime_to_actor_result(
    result: CodingAgentRunResult,
    config: EvalRunConfig,
) -> PatchActorResult:
    if result.status is RuntimeStatus.COMPLETED:
        status = PatchActorStatus.COMPLETED
    elif result.failure_category == "provider_blocked":
        status = PatchActorStatus.PROVIDER_BLOCKED
    elif result.failure_category == "no_patch":
        status = PatchActorStatus.NO_PATCH
    elif result.failure_category in {"patch_failed", "security_failure"}:
        status = PatchActorStatus.PATCH_FAILED
    else:
        status = PatchActorStatus.FAILED
    return PatchActorResult(
        task_id=result.task_id,
        status=status,
        planning_enabled=config.planning_enabled,
        repair_enabled=config.repair_enabled,
        compaction_mode=config.compaction_mode,
        patch_attempts=1 if result.changed_files else 0,
        repair_attempts=result.repair_attempts,
        protocol_repair_attempts=result.protocol_repairs_used,
        tool_calls=result.tool_calls_used,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_usd=result.cost_usd,
        duration_ms=result.duration_ms,
        steps=result.steps_used,
        model_duration_ms=result.model_duration_ms,
        tool_duration_ms=result.tool_duration_ms,
        repair_duration_ms=result.repair_duration_ms,
        changed_files=result.changed_files,
        applied_patch=bool(result.changed_files),
        error=result.error,
        failure_category=result.failure_category,
        events=result.events,
    )


def _save_runtime_artifacts(
    *,
    output_dir: Path,
    result: CodingAgentRunResult,
) -> tuple[str, ...]:
    relative_root = Path("_artifacts") / _safe_name(result.task_id)
    root = output_dir / relative_root
    root.mkdir(parents=True, exist_ok=True)
    messages_path = root / "runtime_messages.json"
    messages_path.write_text(
        json.dumps(
            [message.model_dump(mode="json") for message in result.messages],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    diff_path = root / "final.diff"
    diff_path.write_text(result.diff, encoding="utf-8")
    verification_path = root / "verification.json"
    verification_path.write_text(
        json.dumps(
            [item.model_dump(mode="json") for item in result.verification],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    model_outputs_path = root / "model_outputs.jsonl"
    model_outputs_path.write_text(
        "".join(
            json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n"
            for item in result.model_outputs
        ),
        encoding="utf-8",
    )
    return tuple(
        path.as_posix()
        for path in (
            relative_root / messages_path.name,
            relative_root / diff_path.name,
            relative_root / verification_path.name,
            relative_root / model_outputs_path.name,
        )
    )


def _resolve_fixture_root(project_root: Path, fixture: Path) -> Path:
    if fixture.is_absolute():
        return fixture.resolve()
    return (project_root / fixture).resolve()


def _init_git_repo(path: Path) -> None:
    commands = [
        ["git", "init"],
        ["git", "config", "user.email", "eval@example.com"],
        ["git", "config", "user.name", "Agent Eval"],
        ["git", "add", "."],
        ["git", "commit", "-m", "baseline"],
    ]
    for command in commands:
        result = subprocess.run(  # noqa: UP022
            command,
            cwd=path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(
                f"workspace git command failed: {' '.join(command)}: {stderr}"
            )


def _commit_workspace_state(path: Path, *, message: str) -> None:
    for command in (["git", "add", "."], ["git", "commit", "-m", message]):
        result = subprocess.run(  # noqa: UP022
            command,
            cwd=path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            raise AgentEvalDatasetError(
                f"workspace setup commit failed: {' '.join(command)}: {stderr}"
            )


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "-" for char in value)


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]
