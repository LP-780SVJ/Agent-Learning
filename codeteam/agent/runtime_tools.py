from __future__ import annotations

import json
import posixpath
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from codeteam.agent.editing import (
    FileEdit,
    TextReplacement,
    file_edits_to_patch,
    text_replacements_to_patch,
)
from codeteam.agent.runtime_models import VerificationEvidence
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
            value is not None
            for value in (self.patch, self.edits, self.replacements)
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


@dataclass
class RuntimeEvidence:
    workspace_version: int = 0
    verification: list[VerificationEvidence] = field(default_factory=list)
    repair_attempts: int = 0
    patch_attempts: int = 0
    paused_reason: str | None = None
    checkpoint_ids: list[str] = field(default_factory=list)
    repair_duration_ms: int = 0
    required_verification_commands: tuple[tuple[str, ...], ...] = ()
    changed_files: tuple[str, ...] = ()
    git_diff_checked: bool = False

    @property
    def tests_passed(self) -> bool:
        if not self.required_verification_commands:
            return bool(self.verification) and self.verification[-1].passed
        latest: dict[tuple[str, ...], bool] = {}
        for item in self.verification:
            if item.completion_required:
                latest[item.argv] = item.passed
        return all(
            latest.get(command, False)
            for command in self.required_verification_commands
        )


def create_runtime_tools(
    *,
    workspace_root: Path,
    task_id: str,
    checkpoint_state_root: Path,
    safe_execution: SafeExecutionService,
    evidence: RuntimeEvidence,
    allowed_verification_commands: tuple[tuple[str, ...], ...] = (),
    required_verification_commands: tuple[tuple[str, ...], ...] = (),
    max_repairs: int = 3,
) -> ToolRegistry:
    root = workspace_root.resolve(strict=True)
    canonical_allowed_commands = normalize_allowed_verification_commands(
        allowed_verification_commands
    )
    canonical_required_commands = normalize_allowed_verification_commands(
        required_verification_commands
    )
    evidence.required_verification_commands = canonical_required_commands
    registry = ToolRegistry()
    for tool in create_file_tools(root):
        if tool.name in {"list_files", "read_file", "search_code"}:
            registry.register(tool)

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
            evidence.repair_duration_ms += int(
                (time.monotonic() - started) * 1000
            )
        evidence.workspace_version += 1
        changed = [change.path for change in (result.diff.changes if result.diff else [])]
        evidence.changed_files = tuple(changed)
        evidence.git_diff_checked = False
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
                )
            )
        )
        command = result.command_result
        item = VerificationEvidence(
            argv=argv,
            passed=(
                result.status is SafeExecutionStatus.COMPLETED
                and command is not None
                and command.exit_code == 0
            ),
            exit_code=command.exit_code if command else None,
            duration_ms=command.duration_ms if command else 0.0,
            stdout=command.stdout if command else "",
            stderr=command.stderr if command else "",
            error=result.error or (command.error if command else None),
            completion_required=argv in canonical_required_commands,
        )
        evidence.verification.append(item)
        if evidence.repair_attempts:
            evidence.repair_duration_ms += int(item.duration_ms)
        if result.status in {
            SafeExecutionStatus.APPROVAL_REQUIRED,
            SafeExecutionStatus.SANDBOX_FAILED,
        }:
            evidence.paused_reason = result.error or result.status.value
        return item.model_dump_json()

    def git_status(_: BaseModel) -> str:
        changes = GitWorkspace(root).changed_files()
        return json.dumps(
            [{"kind": item.kind.value, "path": item.path, "old_path": item.old_path} for item in changes],
            ensure_ascii=False,
        )

    def git_diff(_: BaseModel) -> str:
        evidence.git_diff_checked = True
        return render_workspace_diff(root)

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
    elif tool_name in {"git_status", "git_diff"}:
        return {}
    return normalized


def render_workspace_diff(workspace_root: Path) -> str:
    workspace = GitWorkspace(workspace_root)
    diff = workspace.diff()
    chunks = [diff.patch]
    for path in diff.untracked_paths:
        target = workspace.root / path
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
