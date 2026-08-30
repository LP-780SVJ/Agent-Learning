from __future__ import annotations

import json
import posixpath
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from codeteam.agent.completion import CompletionGateDecision
from codeteam.agent.editing import (
    FileEdit,
    TextReplacement,
    file_edits_to_patch,
    text_replacements_to_patch,
)
from codeteam.agent.initial_context import InitialContextSnapshot
from codeteam.agent.runtime_models import (
    CompletionMode,
    VerificationEvidence,
    VerificationOutcomeCategory,
)
from codeteam.agent.verification import (
    DEFAULT_TEST_TIMEOUT_SECONDS,
    normalize_allowed_verification_commands,
    normalize_run_tests_action,
    normalize_verification_argv,
    normalize_verification_cwd,
)
from codeteam.execution.models import CommandRequest
from codeteam.execution.safe_execution_service import (
    SafeCommandExecutionRequest,
    SafeExecutionService,
    SafeExecutionStatus,
    SafePatchExecutionRequest,
)
from codeteam.git.workspace import GitWorkspace
from codeteam.sandbox.environment_inspection import (
    DockerEnvironmentInspector,
    EnvironmentInspectionArgs,
    EnvironmentInspector,
)
from codeteam.sandbox.models import SandboxProfile
from codeteam.sandbox.verification_preflight import (
    classify_verification_environment_failure,
)
from codeteam.tools.base import RegisteredTool
from codeteam.tools.files import create_file_tools
from codeteam.tools.registry import ToolRegistry


class ApplyPatchArgs(BaseModel):
    patch: str | None = None
    edits: list[FileEdit] | None = None
    replacements: list[TextReplacement] | None = None

    @model_validator(mode="after")
    def exactly_one_representation(self) -> ApplyPatchArgs:
        representations = sum(
            value is not None for value in (self.patch, self.edits, self.replacements)
        )
        if representations != 1:
            raise ValueError("Provide exactly one of patch, edits, or replacements.")
        if self.edits == []:
            raise ValueError("edits must not be empty.")
        if self.replacements == []:
            raise ValueError("replacements must not be empty.")
        return self


class RunTestsArgs(BaseModel):
    argv: tuple[str, ...] = Field(min_length=1)
    cwd: str = "."
    timeout_seconds: float = Field(
        default=DEFAULT_TEST_TIMEOUT_SECONDS,
        gt=0,
        le=900,
    )


class EmptyArgs(BaseModel):
    pass


class SubmitResultArgs(BaseModel):
    summary: str = Field(min_length=1)
    notes: str | None = None


@dataclass
class RuntimeEvidence:
    workspace_version: int = 0
    verification: list[VerificationEvidence] = field(default_factory=list)
    repair_attempts: int = 0
    patch_attempts: int = 0
    paused_reason: str | None = None
    paused_category: str | None = None
    checkpoint_ids: list[str] = field(default_factory=list)
    repair_duration_ms: int = 0
    task_verification_commands: tuple[tuple[str, ...], ...] = ()
    regression_verification_commands: tuple[tuple[str, ...], ...] = ()
    required_verification_commands: tuple[tuple[str, ...], ...] = ()
    changed_files: tuple[str, ...] = ()
    git_diff_checked: bool = False
    git_diff_checked_version: int | None = None
    workspace_fingerprint: str | None = None
    workspace_hygiene_clean: bool = True
    accepted_submission_summary: str | None = None
    accepted_submission_notes: str | None = None
    completion_ready_seen: bool = False
    post_ready_tool_calls: int = 0
    completion_mode: CompletionMode | None = None
    effective_max_steps: int = 20
    finalization_reserve_steps: int = 4
    finalization_reserve_entered: bool = False
    finalization_reserve_entry_step: int | None = None
    budget_boundary_completion_count: int = 0
    post_ready_reopen_patch_count: int = 0
    post_ready_skipped_optional_tool_count: int = 0
    post_ready_nonfinalization_tool_count: int = 0
    verification_workspace_mutations: int = 0
    progress_metrics: dict[str, object] = field(default_factory=dict)

    @property
    def tests_passed(self) -> bool:
        required = tuple(
            dict.fromkeys(
                (
                    *self.task_verification_commands,
                    *self.regression_verification_commands,
                )
            )
        )
        if not required:
            required = self.required_verification_commands
        if not required:
            current = [
                item
                for item in self.verification
                if item.workspace_version == self.workspace_version
            ]
            return bool(current) and current[-1].passed
        latest: dict[tuple[str, ...], bool] = {}
        for item in self.verification:
            if (
                item.completion_required
                and item.workspace_version == self.workspace_version
            ):
                latest[item.argv] = item.passed
        return all(latest.get(command, False) for command in required)


def create_runtime_tools(
    *,
    workspace_root: Path,
    task_id: str,
    checkpoint_state_root: Path,
    safe_execution: SafeExecutionService,
    evidence: RuntimeEvidence,
    sandbox_profile: SandboxProfile | None = None,
    allowed_verification_commands: tuple[tuple[str, ...], ...] = (),
    required_verification_commands: tuple[tuple[str, ...], ...] = (),
    task_verification_commands: tuple[tuple[str, ...], ...] = (),
    regression_verification_commands: tuple[tuple[str, ...], ...] = (),
    completion_gate_provider: Callable[[], CompletionGateDecision] | None = None,
    environment_inspector: EnvironmentInspector | None = None,
    initial_context_snapshot: InitialContextSnapshot | None = None,
    max_repairs: int = 3,
) -> ToolRegistry:
    root = workspace_root.resolve(strict=True)
    canonical_allowed_commands = normalize_allowed_verification_commands(
        allowed_verification_commands
    )
    canonical_required_commands = normalize_allowed_verification_commands(
        required_verification_commands
    )
    canonical_task_commands = normalize_allowed_verification_commands(
        task_verification_commands
    )
    canonical_regression_commands = normalize_allowed_verification_commands(
        regression_verification_commands
    )
    if not canonical_task_commands:
        canonical_task_commands = canonical_required_commands
    evidence.task_verification_commands = canonical_task_commands
    evidence.regression_verification_commands = canonical_regression_commands
    evidence.required_verification_commands = canonical_required_commands
    execution_profile = (sandbox_profile or SandboxProfile()).model_copy(
        update={"workspace_write": False}
    )
    registry = ToolRegistry()
    for tool in create_file_tools(root):
        if tool.name in {"list_files", "read_file", "search_code"}:
            if tool.name == "read_file" and initial_context_snapshot is not None:
                original = tool.func

                def read_file_with_initial_context(
                    args: BaseModel,
                    original_func: Callable[[BaseModel], str] = original,
                ) -> str:
                    path = getattr(args, "path", None)
                    start_line = getattr(args, "start_line", None)
                    end_line = getattr(args, "end_line", None)
                    if (
                        isinstance(path, str)
                        and start_line is None
                        and end_line is None
                    ):
                        reused = initial_context_snapshot.render_full_read(
                            path, evidence.workspace_version
                        )
                        if reused is not None:
                            return reused
                    return original_func(args)

                registry.register(
                    RegisteredTool(
                        name=tool.name,
                        description=(
                            tool.description
                            + " A complete current initial-context copy may be "
                            "returned as a compact reference."
                        ),
                        args_schema=tool.args_schema,
                        func=read_file_with_initial_context,
                    )
                )
            else:
                registry.register(tool)

    inspector = environment_inspector or DockerEnvironmentInspector(
        profile=execution_profile
    )

    def inspect_environment(args: BaseModel) -> str:
        parsed = EnvironmentInspectionArgs.model_validate(args)
        return inspector.inspect(root, parsed).model_dump_json()

    def apply_patch(args: BaseModel) -> str:
        evidence.patch_attempts += 1
        parsed = ApplyPatchArgs.model_validate(args)
        is_repair = bool(evidence.verification and not evidence.verification[-1].passed)
        if is_repair and evidence.repair_attempts >= max_repairs:
            raise ValueError("Repair budget exhausted.")
        if parsed.patch is not None:
            patch = parsed.patch
        elif parsed.edits is not None:
            patch = file_edits_to_patch(root, parsed.edits)
        else:
            patch = text_replacements_to_patch(root, parsed.replacements or [])
        started = time.monotonic()
        result = safe_execution.execute_patch(
            SafePatchExecutionRequest(
                patch=patch,
                workspace_root=root,
                checkpoint_state_root=checkpoint_state_root,
                task_id=task_id,
                agent_id="coding-agent-runtime",
            )
        )
        if result.checkpoint is not None:
            evidence.checkpoint_ids.append(result.checkpoint.checkpoint_id)
        if result.status is not SafeExecutionStatus.COMPLETED:
            detail = result.error or "Patch was rejected."
            if result.patch_result is not None and result.patch_result.stderr:
                detail = f"{detail}\ngit apply: {result.patch_result.stderr}"
            raise ValueError(detail)
        if is_repair:
            evidence.repair_attempts += 1
            evidence.repair_duration_ms += int((time.monotonic() - started) * 1000)
        evidence.workspace_version += 1
        changed = [
            change.path for change in (result.diff.changes if result.diff else [])
        ]
        evidence.changed_files = tuple(changed)
        evidence.git_diff_checked = False
        evidence.git_diff_checked_version = None
        evidence.workspace_fingerprint = GitWorkspace(root).content_fingerprint()[0]
        return json.dumps(
            {"applied": True, "changed_files": changed},
            ensure_ascii=False,
        )

    def run_tests(args: BaseModel) -> str:
        parsed = RunTestsArgs.model_validate(args)
        argv = normalize_verification_argv(parsed.argv)
        cwd_argument = normalize_verification_cwd(parsed.cwd)
        if canonical_allowed_commands and argv not in canonical_allowed_commands:
            allowed = json.dumps(
                [list(command) for command in canonical_allowed_commands],
                ensure_ascii=False,
            )
            raise ValueError(
                "Command is not in the task's visible verification commands. "
                f"Use one of these workspace-relative argv arrays: {allowed}"
            )
        cwd = (root / cwd_argument).resolve(strict=False)
        try:
            cwd.relative_to(root)
        except ValueError as error:
            raise ValueError("Test cwd escapes workspace.") from error
        workspace = GitWorkspace(root)
        fingerprint_before, entries_before = workspace.content_fingerprint()
        result = safe_execution.execute_command(
            SafeCommandExecutionRequest(
                command=CommandRequest(
                    argv=argv,
                    cwd=cwd,
                    workspace_root=root,
                    task_id=task_id,
                    agent_id="coding-agent-runtime",
                    reason="Agent-visible verification",
                    timeout_seconds=parsed.timeout_seconds,
                ),
                sandbox_profile=execution_profile,
            )
        )
        command = result.command_result
        environment_failure_category = (
            classify_verification_environment_failure(argv, command)
            if command is not None
            else None
        )
        fingerprint_after, entries_after = workspace.content_fingerprint()
        before_map = dict(entries_before)
        after_map = dict(entries_after)
        mutations = tuple(
            path
            for path in sorted(before_map.keys() | after_map.keys())
            if before_map.get(path) != after_map.get(path)
        )
        if mutations:
            evidence.workspace_version += 1
            evidence.workspace_hygiene_clean = False
            evidence.verification_workspace_mutations += 1
            evidence.git_diff_checked = False
            evidence.git_diff_checked_version = None
        evidence.workspace_fingerprint = fingerprint_after
        passed = (
            result.status is SafeExecutionStatus.COMPLETED
            and command is not None
            and command.exit_code == 0
            and not mutations
        )
        if mutations:
            outcome_category = VerificationOutcomeCategory.WORKSPACE_HYGIENE_FAILED
        elif passed:
            outcome_category = VerificationOutcomeCategory.PASSED
        elif (
            environment_failure_category is not None
            or result.status is SafeExecutionStatus.SANDBOX_FAILED
        ):
            outcome_category = VerificationOutcomeCategory.ENVIRONMENT_FAILED
        else:
            outcome_category = VerificationOutcomeCategory.TEST_FAILED
        item = VerificationEvidence(
            argv=argv,
            passed=passed,
            category=outcome_category,
            environment_failure_category=environment_failure_category,
            exit_code=command.exit_code if command else None,
            duration_ms=command.duration_ms if command else 0.0,
            stdout=command.stdout if command else "",
            stderr=command.stderr if command else "",
            error=result.error or (command.error if command else None),
            completion_required=argv in canonical_required_commands,
            workspace_version=evidence.workspace_version,
            workspace_fingerprint_before=fingerprint_before,
            workspace_fingerprint_after=fingerprint_after,
            workspace_mutations=mutations,
        )
        evidence.verification.append(item)
        if evidence.repair_attempts:
            evidence.repair_duration_ms += int(item.duration_ms)
        if result.status in {
            SafeExecutionStatus.APPROVAL_REQUIRED,
            SafeExecutionStatus.SANDBOX_FAILED,
        }:
            evidence.paused_reason = result.error or result.status.value
        if environment_failure_category is not None:
            evidence.paused_category = "verification_environment_failed"
            evidence.paused_reason = (
                "Verification environment failed during required command "
                f"execution ({environment_failure_category})."
            )
        if mutations:
            evidence.paused_category = "workspace_hygiene_failed"
            evidence.paused_reason = (
                "Verification mutated the source workspace: " + ", ".join(mutations)
            )
        return item.model_dump_json()

    def git_status(_: BaseModel) -> str:
        changes = GitWorkspace(root).changed_files()
        return json.dumps(
            [
                {"kind": item.kind.value, "path": item.path, "old_path": item.old_path}
                for item in changes
            ],
            ensure_ascii=False,
        )

    def git_diff(_: BaseModel) -> str:
        rendered = render_workspace_diff(root)
        evidence.git_diff_checked = True
        evidence.git_diff_checked_version = evidence.workspace_version
        return rendered

    def submit_result(args: BaseModel) -> str:
        parsed = SubmitResultArgs.model_validate(args)
        if completion_gate_provider is None:
            raise ValueError("Completion gate is unavailable.")
        decision = completion_gate_provider()
        if not isinstance(decision, CompletionGateDecision):
            raise TypeError("Completion gate returned an invalid decision.")
        evidence.completion_ready_seen |= decision.ready
        payload = {"accepted": decision.ready, **decision.as_dict()}
        if decision.ready:
            evidence.accepted_submission_summary = parsed.summary
            evidence.accepted_submission_notes = parsed.notes
            evidence.completion_mode = CompletionMode.MODEL_SUBMITTED
        return json.dumps(payload, ensure_ascii=False)

    registry.register(
        RegisteredTool(
            name="inspect_environment",
            description=(
                "Check one Python module or bare executable in the actual verification "
                "Docker sandbox using a Runtime-owned fixed probe. The model cannot "
                "supply code or command arguments."
            ),
            args_schema=EnvironmentInspectionArgs,
            func=inspect_environment,
        )
    )
    registry.register(
        RegisteredTool(
            name="apply_patch",
            description="Apply a unified diff or complete structured file edits safely.",
            args_schema=ApplyPatchArgs,
            func=apply_patch,
        )
    )
    registry.register(
        RegisteredTool(
            name="run_tests",
            description="Run an argv-based visible verification command in Docker.",
            args_schema=RunTestsArgs,
            func=run_tests,
        )
    )
    registry.register(
        RegisteredTool(
            name="git_status",
            description="Inspect final changed files from Git.",
            args_schema=EmptyArgs,
            func=git_status,
        )
    )
    registry.register(
        RegisteredTool(
            name="git_diff",
            description="Inspect the current source diff, including untracked text files.",
            args_schema=EmptyArgs,
            func=git_diff,
        )
    )
    registry.register(
        RegisteredTool(
            name="submit_result",
            description=(
                "Request Runtime-authorized completion after all current-version "
                "verification and diff-review requirements are satisfied. Call alone."
            ),
            args_schema=SubmitResultArgs,
            func=submit_result,
        )
    )
    return registry


def normalize_runtime_action(
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    if tool_name == "run_tests":
        return normalize_run_tests_action(tool_name, arguments)
    normalized = dict(arguments)
    if tool_name in {"list_files", "read_file", "search_code"}:
        raw_path = normalized.get("path", ".")
        if isinstance(raw_path, str):
            normalized["path"] = posixpath.normpath(raw_path) or "."
    if tool_name == "list_files":
        normalized.setdefault("recursive", True)
    elif tool_name == "read_file":
        normalized.setdefault("start_line", None)
        normalized.setdefault("end_line", None)
    elif tool_name == "search_code":
        normalized.setdefault("max_results", 50)
    elif tool_name == "inspect_environment":
        return normalized
    elif tool_name in {"git_status", "git_diff"}:
        return {}
    return normalized


def render_workspace_diff(workspace_root: Path) -> str:
    workspace = GitWorkspace(workspace_root)
    diff = workspace.diff()
    chunks = [diff.patch]
    for path in diff.untracked_paths:
        target = workspace.root / path
        if target.is_symlink():
            continue
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        patch = file_edits_to_patch(
            workspace.root,
            [FileEdit(path=path, content=content)],
            assume_missing_paths=frozenset({path}),
        )
        chunks.append(patch)
    return "".join(chunks)
