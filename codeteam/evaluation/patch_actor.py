"""LLM-backed patch generation and patch actor."""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from difflib import unified_diff
from pathlib import Path
from typing import Protocol

from codeteam.application.build_context import (
    ContextApplicationService,
    ContextBuildReport,
)
from codeteam.evaluation.agent_models import (
    AgentEvalTask,
    EvalRunConfig,
    PatchActorResult,
    PatchActorStatus,
)
from codeteam.git.workspace import GitWorkspace
from codeteam.planning.models import Plan, PlanStep, create_plan
from codeteam.planning.planner import LLMPlanner, RepositoryContext
from codeteam.schemas.messages import Message
from codeteam.task.models import TaskSpec, create_task_spec
from codeteam.usage.token_counter import ApproximateTokenCounter


class PatchGenerator(Protocol):
    def generate_patch(
        self,
        *,
        task: TaskSpec,
        plan: Plan | None,
        context: ContextBuildReport,
        workspace_root: Path,
        failure_summary: str | None = None,
    ) -> str:
        """Return a unified diff patch."""
        ...


class LLMPatchGenerator:
    """Generate a unified diff patch from task, plan, and repository context."""

    def __init__(
        self,
        *,
        complete: Callable[[list[Message]], str],
        model_id: str,
        token_counter: ApproximateTokenCounter | None = None,
    ) -> None:
        self._complete = complete
        self.model_id = model_id
        self.token_counter = token_counter or ApproximateTokenCounter()
        self.last_input_tokens = 0
        self.last_output_tokens = 0
        self.last_raw_output = ""
        self.last_extracted_patch = ""

    def generate_patch(
        self,
        *,
        task: TaskSpec,
        plan: Plan | None,
        context: ContextBuildReport,
        workspace_root: Path,
        failure_summary: str | None = None,
    ) -> str:
        prompt = self._build_prompt(
            task=task,
            plan=plan,
            context=context,
            failure_summary=failure_summary,
        )
        self.last_input_tokens = self.token_counter.count_text(prompt)
        raw = self._complete([Message(role="user", content=prompt)])
        self.last_output_tokens = self.token_counter.count_text(raw)
        self.last_raw_output = raw
        patch = patch_from_structured_file_edits(raw, workspace_root=workspace_root)
        if patch is None:
            patch = extract_unified_diff(raw)
        self.last_extracted_patch = patch
        return patch

    @staticmethod
    def _build_prompt(
        *,
        task: TaskSpec,
        plan: Plan | None,
        context: ContextBuildReport,
        failure_summary: str | None,
    ) -> str:
        lines: list[str] = []
        lines.append("You are CodeTeam's patch actor.")
        lines.append("Return only a unified diff patch. Do not use Markdown fences.")
        lines.append("Do not modify files outside the repository.")
        lines.append("")
        lines.append("## Task")
        lines.append(task.original_request)
        lines.append("")
        if plan is not None:
            lines.append("## Plan")
            for step in plan.steps:
                lines.append(f"- {step.step_id}: {step.title} :: {step.description}")
                if step.relevant_files:
                    lines.append(f"  files: {', '.join(step.relevant_files)}")
                if step.verification:
                    lines.append(f"  verification: {step.verification}")
            lines.append("")
        if failure_summary:
            lines.append("## Previous Failure")
            lines.append(failure_summary)
            lines.append("")
        lines.append("## Repository Context")
        lines.append(context.repo_map)
        for item in context.code_context:
            lines.append("")
            lines.append(f"### File: {item.path}")
            lines.append("```")
            lines.append(item.content)
            lines.append("```")
        lines.append("")
        lines.append("## Output")
        lines.append("Return only one of the supported output formats.")
        lines.append(
            "Preferred output is JSON: "
            '{"files":[{"path":"relative/path.py","content":"full new file content"}]}.'
        )
        lines.append(
            "If JSON is not practical, return a patch that can be applied by git apply."
        )
        return "\n".join(lines)


class NullPatchGenerator:
    """Deterministic generator used to prove the harness without modifying code."""

    def generate_patch(
        self,
        *,
        task: TaskSpec,
        plan: Plan | None,
        context: ContextBuildReport,
        workspace_root: Path,
        failure_summary: str | None = None,
    ) -> str:
        return ""


def extract_unified_diff(text: str) -> str:
    stripped = _strip_code_fences(text.strip())
    if not stripped:
        return ""

    markers = ["diff --git ", "--- "]
    starts = [stripped.find(marker) for marker in markers if stripped.find(marker) >= 0]
    if starts:
        return stripped[min(starts):].strip() + "\n"
    if stripped.upper() in {"NO_PATCH", "NO_CHANGES"}:
        return ""
    return stripped


def patch_from_structured_file_edits(
    text: str,
    *,
    workspace_root: Path,
) -> str | None:
    payload = _extract_json_object(text)
    if payload is None:
        return None
    files = payload.get("files")
    if not isinstance(files, list):
        return None

    patches: list[str] = []
    for item in files:
        if not isinstance(item, dict):
            return None
        path = item.get("path")
        content = item.get("content", item.get("new_content"))
        if not isinstance(path, str) or not isinstance(content, str):
            return None
        if _unsafe_structured_edit_path(path):
            raise ValueError(f"Unsafe structured edit path: {path!r}")
        patches.append(
            _full_file_edit_to_patch(
                path=path,
                content=content,
                workspace_root=workspace_root,
            )
        )

    return "".join(patches) if patches else None


def _extract_json_object(text: str) -> dict | None:
    stripped = _strip_code_fences(text.strip())
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(stripped[start:end + 1])
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _unsafe_structured_edit_path(path: str) -> bool:
    candidate = Path(path)
    parts = candidate.parts
    return (
        not path
        or candidate.is_absolute()
        or ".." in parts
        or (bool(parts) and parts[0] == ".git")
    )


def _full_file_edit_to_patch(
    *,
    path: str,
    content: str,
    workspace_root: Path,
) -> str:
    file_path = workspace_root / path
    old_text = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
    old_lines = old_text.splitlines(keepends=True)
    new_text = content if content.endswith("\n") else f"{content}\n"
    new_lines = new_text.splitlines(keepends=True)
    from_file = f"a/{path}" if file_path.exists() else "/dev/null"
    diff_lines = list(
        unified_diff(
            old_lines,
            new_lines,
            fromfile=from_file,
            tofile=f"b/{path}",
            lineterm="",
        )
    )
    normalized = [
        line if line.endswith("\n") else f"{line}\n"
        for line in diff_lines
    ]
    header = f"diff --git a/{path} b/{path}\n"
    if not file_path.exists():
        header += "new file mode 100644\n"
    return header + "".join(normalized)


def _strip_code_fences(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines:
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


class PatchActor:
    """Single-patch actor used by the agent evaluation harness.

    V1 intentionally keeps the actor small: build context, optionally plan,
    ask a patch generator for one unified diff, and apply it with GitWorkspace.
    Repair and compaction modes are recorded in the result so ablation runs are
    reproducible even before a full multi-turn actor is wired.
    """

    def __init__(
        self,
        *,
        patch_generator: PatchGenerator,
        context_service: ContextApplicationService | None = None,
        planner_complete: Callable[[list[Message]], str] | None = None,
    ) -> None:
        self._patch_generator = patch_generator
        self._context_service = context_service or ContextApplicationService()
        self._planner_complete = planner_complete

    def run(
        self,
        *,
        task: AgentEvalTask,
        workspace_root: Path,
        config: EvalRunConfig,
        failure_summary: str | None = None,
        previous_patch_attempts: int = 0,
        previous_repair_attempts: int = 0,
    ) -> PatchActorResult:
        started = time.monotonic()
        events: list[str] = ["actor.started"]
        input_tokens = 0
        output_tokens = 0
        attempt_no = previous_patch_attempts + 1
        artifact_paths: list[str] = []
        raw_model_output_sha: str | None = None
        extracted_patch_sha: str | None = None

        try:
            task_spec = create_task_spec(
                task_id=task.task_id,
                original_request=task.prompt,
            )
            context = self._context_service.execute(
                query=task.prompt,
                repository_root=workspace_root,
                top_k=5,
                budget_tokens=config.context_budget,
            )
            events.append("context.built")

            plan = None
            if config.planning_enabled:
                plan = self._create_plan(
                    task=task_spec,
                    context=context,
                    config=config,
                )
                events.append("plan.created")

            patch = self._patch_generator.generate_patch(
                task=task_spec,
                plan=plan,
                context=context,
                workspace_root=workspace_root,
                failure_summary=failure_summary,
            )
            events.append("patch.generated")
            input_tokens += getattr(self._patch_generator, "last_input_tokens", 0)
            output_tokens += getattr(self._patch_generator, "last_output_tokens", 0)
            raw_model_output = getattr(self._patch_generator, "last_raw_output", None)
            extracted_patch = getattr(
                self._patch_generator,
                "last_extracted_patch",
                patch,
            )
            if raw_model_output is not None:
                raw_model_output_sha = _sha256_text(raw_model_output)
                artifact_paths.append(
                    _write_artifact(
                        workspace_root=workspace_root,
                        task_id=task.task_id,
                        attempt_no=attempt_no,
                        name="raw_model_output.txt",
                        content=raw_model_output,
                    )
                )
            if extracted_patch is not None:
                extracted_patch_sha = _sha256_text(extracted_patch)
                artifact_paths.append(
                    _write_artifact(
                        workspace_root=workspace_root,
                        task_id=task.task_id,
                        attempt_no=attempt_no,
                        name="extracted_patch.diff",
                        content=extracted_patch,
                    )
                )
        except Exception as error:  # noqa: BLE001
            return PatchActorResult(
                task_id=task.task_id,
                status=PatchActorStatus.PROVIDER_BLOCKED,
                planning_enabled=config.planning_enabled,
                repair_enabled=config.repair_enabled,
                compaction_mode=config.compaction_mode,
                duration_ms=_elapsed_ms(started),
                patch_attempts=previous_patch_attempts,
                repair_attempts=previous_repair_attempts,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                artifact_paths=tuple(artifact_paths),
                raw_model_output_sha256=raw_model_output_sha,
                extracted_patch_sha256=extracted_patch_sha,
                error=f"{type(error).__name__}: {error}",
                events=(*events, "actor.provider_blocked"),
            )

        if not patch.strip():
            return PatchActorResult(
                task_id=task.task_id,
                status=PatchActorStatus.NO_PATCH,
                planning_enabled=config.planning_enabled,
                repair_enabled=config.repair_enabled,
                compaction_mode=config.compaction_mode,
                duration_ms=_elapsed_ms(started),
                patch_attempts=previous_patch_attempts + 1,
                repair_attempts=previous_repair_attempts,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                artifact_paths=tuple(artifact_paths),
                raw_model_output_sha256=raw_model_output_sha,
                extracted_patch_sha256=extracted_patch_sha,
                error="Patch generator returned an empty patch.",
                events=(*events, "actor.no_patch"),
            )

        patch_sha = hashlib.sha256(patch.encode("utf-8")).hexdigest()
        workspace = GitWorkspace(workspace_root)
        patch_result = workspace.apply_patch(patch)
        if not patch_result.applied:
            if patch_result.stdout:
                artifact_paths.append(
                    _write_artifact(
                        workspace_root=workspace_root,
                        task_id=task.task_id,
                        attempt_no=attempt_no,
                        name="git_apply_stdout.txt",
                        content=patch_result.stdout,
                    )
                )
            if patch_result.stderr or patch_result.failure_reason:
                artifact_paths.append(
                    _write_artifact(
                        workspace_root=workspace_root,
                        task_id=task.task_id,
                        attempt_no=attempt_no,
                        name="git_apply_stderr.txt",
                        content=patch_result.stderr or patch_result.failure_reason or "",
                    )
                )
            return PatchActorResult(
                task_id=task.task_id,
                status=PatchActorStatus.PATCH_FAILED,
                planning_enabled=config.planning_enabled,
                repair_enabled=config.repair_enabled,
                compaction_mode=config.compaction_mode,
                duration_ms=_elapsed_ms(started),
                patch_attempts=previous_patch_attempts + 1,
                repair_attempts=previous_repair_attempts,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                generated_patch_sha256=patch_sha,
                raw_model_output_sha256=raw_model_output_sha,
                extracted_patch_sha256=extracted_patch_sha,
                artifact_paths=tuple(artifact_paths),
                patch_apply_stdout=patch_result.stdout,
                patch_apply_stderr=patch_result.stderr,
                error=_patch_failure_message(patch_result.failure_reason, patch_result.stderr),
                events=(*events, "patch.apply_failed"),
            )

        changed_files = tuple(dict.fromkeys(patch_result.affected_paths))
        return PatchActorResult(
            task_id=task.task_id,
            status=PatchActorStatus.COMPLETED,
            planning_enabled=config.planning_enabled,
            repair_enabled=config.repair_enabled,
            compaction_mode=config.compaction_mode,
            duration_ms=_elapsed_ms(started),
            patch_attempts=previous_patch_attempts + 1,
            repair_attempts=previous_repair_attempts,
            tool_calls=1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            changed_files=changed_files,
            applied_patch=True,
            generated_patch_sha256=patch_sha,
            raw_model_output_sha256=raw_model_output_sha,
            extracted_patch_sha256=extracted_patch_sha,
            artifact_paths=tuple(artifact_paths),
            patch_apply_stdout=patch_result.stdout,
            patch_apply_stderr=patch_result.stderr,
            events=(*events, "patch.applied", "actor.completed"),
        )

    def _create_plan(
        self,
        *,
        task: TaskSpec,
        context: ContextBuildReport,
        config: EvalRunConfig,
    ) -> Plan:
        repo_context = RepositoryContext(
            summary=f"Eval task {task.task_id}: {len(context.top_files)} relevant files",
            relevant_files=tuple(item.path for item in context.top_files),
            relevant_symbols=tuple(
                symbol
                for item in context.top_files
                for symbol in item.matched_symbols
            ),
            instructions=tuple(context.applicable_instructions),
            test_commands=tuple(command.command for command in context.test_commands),
        )
        if self._planner_complete is None:
            return create_plan(
                plan_id=f"{task.task_id}-{config.mode.value}-plan",
                task_id=task.task_id,
                steps=(
                    PlanStep(
                        step_id="P1",
                        title="Generate patch",
                        description="Use retrieved repository context to generate a focused patch.",
                        relevant_files=tuple(item.path for item in context.top_files),
                        verification="Run the task acceptance and regression commands.",
                    ),
                ),
            )
        planner_complete = self._planner_complete
        planner = LLMPlanner(complete=lambda prompt: planner_complete(
            [Message(role="user", content=prompt)]
        ))
        return planner.create_plan(task=task, repo_context=repo_context)


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_artifact(
    *,
    workspace_root: Path,
    task_id: str,
    attempt_no: int,
    name: str,
    content: str,
) -> str:
    relative = (
        Path("_artifacts")
        / _safe_artifact_name(task_id)
        / f"attempt-{attempt_no:02d}"
        / name
    )
    target = workspace_root.parent / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return relative.as_posix()


def _safe_artifact_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "-" for char in value)


def _patch_failure_message(reason: str | None, stderr: str) -> str:
    parts = [reason or "patch apply failed"]
    if stderr:
        parts.append(stderr[-2000:])
    return "\n".join(parts)
