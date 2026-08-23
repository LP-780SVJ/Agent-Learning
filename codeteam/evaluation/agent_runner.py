"""Task-level agent evaluation runner."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from pydantic import ValidationError

from codeteam.evaluation.agent_grader import AgentGrader
from codeteam.evaluation.agent_models import (
    AgentEvalRunSummary,
    AgentEvalSplit,
    AgentEvalTask,
    AgentEvalTaskResult,
    EvalRunConfig,
    GradeResult,
    PatchActorResult,
    PatchActorStatus,
)
from codeteam.evaluation.patch_actor import PatchActor

IGNORED_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "eval_hidden",
}


class AgentEvalDatasetError(ValueError):
    """Raised when an agent eval JSONL suite is malformed."""


class AgentEvalRunner:
    """Run coding tasks in isolated workspaces and grade the result."""

    def __init__(
        self,
        *,
        project_root: Path | None = None,
        actor: PatchActor,
        grader: AgentGrader | None = None,
        keep_workspaces: bool = False,
    ) -> None:
        self.project_root = (project_root or _default_project_root()).resolve()
        self.actor = actor
        self.grader = grader or AgentGrader(project_root=self.project_root)
        self.keep_workspaces = keep_workspaces

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
            task_workspace = workspace_root / _safe_name(task.task_id)
            pristine_workspace = workspace_root / "_pristine" / _safe_name(task.task_id)
            self._prepare_workspace(task=task, destination=pristine_workspace)
            pristine_acceptance_results = self.grader.check_pristine_acceptance(
                task=task,
                workspace_root=pristine_workspace,
                config=config,
            )
            if not self.keep_workspaces:
                shutil.rmtree(pristine_workspace, ignore_errors=True)

            self._prepare_workspace(task=task, destination=task_workspace)
            started = time.monotonic()
            actor_result = self.actor.run(
                task=task,
                workspace_root=task_workspace,
                config=config,
            )
            grade = self.grader.grade(
                task=task,
                workspace_root=task_workspace,
                actor_result=actor_result,
                config=config,
                pristine_acceptance_results=pristine_acceptance_results,
            )
            repair_attempts = 0
            while (
                config.repair_enabled
                and not grade.success
                and grade.failure_category != "oracle_not_discriminative"
                and actor_result.status in {
                    PatchActorStatus.COMPLETED,
                    PatchActorStatus.PATCH_FAILED,
                }
                and repair_attempts < min(task.budget.max_repairs, config.max_repairs)
            ):
                repair_attempts += 1
                repair_result = self.actor.run(
                    task=task,
                    workspace_root=task_workspace,
                    config=config,
                    failure_summary=_summarize_grade_failure(grade),
                    previous_patch_attempts=actor_result.patch_attempts,
                    previous_repair_attempts=repair_attempts,
                )
                actor_result = _merge_actor_results(actor_result, repair_result)
                grade = self.grader.grade(
                    task=task,
                    workspace_root=task_workspace,
                    actor_result=actor_result,
                    config=config,
                    pristine_acceptance_results=pristine_acceptance_results,
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
                    within_budget=grade.within_budget,
                    security_passed=grade.security_passed,
                    pristine_acceptance_passed=grade.pristine_acceptance_passed,
                    acceptance_results=grade.acceptance_results,
                    regression_results=grade.regression_results,
                    pristine_acceptance_results=grade.pristine_acceptance_results,
                    duration_ms=duration_ms,
                    changed_files=grade.changed_files,
                    patch_attempts=actor_result.patch_attempts,
                    repair_attempts=actor_result.repair_attempts,
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
                    "task_count": len(tasks),
                    "keep_workspaces": self.keep_workspaces,
                    "pristine_oracle_check": True,
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
            shutil.copytree(
                source,
                destination,
                ignore=shutil.ignore_patterns(*IGNORED_NAMES),
            )
        _init_git_repo(destination)

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
        acceptance_passed_count=sum(result.acceptance_passed for result in results),
        regression_passed_count=sum(result.regression_passed for result in results),
        security_passed_count=sum(result.security_passed for result in results),
        pristine_acceptance_passed_count=sum(
            result.pristine_acceptance_passed for result in results
        ),
    )


def make_run_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _summarize_grade_failure(grade: GradeResult) -> str:
    lines: list[str] = []
    if grade.failure_category:
        lines.append(f"failure_category: {grade.failure_category}")
    if grade.error:
        lines.append("actor_error:")
        lines.append(grade.error[-2000:])
    for result in (*grade.acceptance_results, *grade.regression_results):
        if result.passed:
            continue
        lines.append(f"command: {result.command}")
        lines.append(f"exit_code: {result.exit_code}")
        if result.stdout:
            lines.append("stdout:")
            lines.append(result.stdout[-2000:])
        if result.stderr:
            lines.append("stderr:")
            lines.append(result.stderr[-2000:])
    return "\n".join(lines) or "grader failed without command output"


def _merge_actor_results(
    previous: PatchActorResult,
    current: PatchActorResult,
) -> PatchActorResult:
    return current.model_copy(
        update={
            "patch_attempts": max(current.patch_attempts, previous.patch_attempts),
            "repair_attempts": max(current.repair_attempts, previous.repair_attempts),
            "tool_calls": previous.tool_calls + current.tool_calls,
            "input_tokens": previous.input_tokens + current.input_tokens,
            "output_tokens": previous.output_tokens + current.output_tokens,
            "cost_usd": previous.cost_usd + current.cost_usd,
            "changed_files": tuple(
                dict.fromkeys((*previous.changed_files, *current.changed_files))
            ),
            "artifact_paths": tuple(
                dict.fromkeys((*previous.artifact_paths, *current.artifact_paths))
            ),
            "events": (*previous.events, *current.events),
        },
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


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "-" for char in value)


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]
