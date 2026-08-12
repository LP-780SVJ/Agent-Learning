from __future__ import annotations

import re
import subprocess
from pathlib import Path

from codeteam.git.errors import (
    BaseRefNotFoundError,
    BranchAlreadyExistsError,
    GitWorktreeCommandError,
    InvalidTaskIdError,
    WorktreePathConflictError,
)
from codeteam.git.models import WorktreeInfo

DEFAULT_WORKTREE_DIR_NAME = ".codeteam/worktrees"
TASK_BRANCH_PREFIX = "codeteam"
_TASK_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]+")
DEFAULT_GIT_TIMEOUT_SECONDS = 10.0


class WorktreeManager:
    """管理每个任务对应的 Git linked worktree。"""

    def __init__(
        self,
        repo_root: str | Path,
        worktree_root: str | Path | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve(strict=True)

        if worktree_root is None:
            self.worktree_root = self.repo_root / DEFAULT_WORKTREE_DIR_NAME
        else:
            self.worktree_root = Path(worktree_root).resolve(strict=False)

    def _run_git(
        self,
        args: list[str],
        cwd: Path | None = None,
    ) -> bytes:
        command_cwd = cwd or self.repo_root

        try:
            result = subprocess.run(  # noqa: UP022
                ["git", *args],
                cwd=command_cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                timeout=DEFAULT_GIT_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise GitWorktreeCommandError(
                f"Git command timed out: git {' '.join(args)}"
            ) from error

        if result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="replace")
            raise GitWorktreeCommandError(
                message or f"Git command failed: git {' '.join(args)}"
            )

        return result.stdout

    def _resolve_commit(self, ref: str) -> str:
        try:
            output = self._run_git(
                ["rev-parse", "--verify", f"{ref}^{{commit}}"]
            )
        except GitWorktreeCommandError as error:
            raise BaseRefNotFoundError(
                f"Base ref does not exist or is not a commit: {ref!r}"
            ) from error

        sha = output.decode("utf-8", errors="replace").strip()

        if not sha:
            raise BaseRefNotFoundError(
                f"Base ref resolved to an empty commit: {ref!r}"
            )

        return sha

    def _branch_exists(self, branch_name: str) -> bool:
        try:
            result = subprocess.run(
                [
                    "git",
                    "rev-parse",
                    "--verify",
                    "--quiet",
                    f"refs/heads/{branch_name}",
                ],
                cwd=self.repo_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                shell=False,
                timeout=DEFAULT_GIT_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise GitWorktreeCommandError(
                f"Git command timed out while checking branch: {branch_name}"
            ) from error

        return result.returncode == 0

    def _ensure_can_create_worktree(
        self,
        branch_name: str,
        worktree_path: Path,
    ) -> None:
        if self._branch_exists(branch_name):
            raise BranchAlreadyExistsError(
                f"Branch already exists: {branch_name}"
            )

        if worktree_path.exists():
            raise WorktreePathConflictError(
                f"Worktree path already exists: {worktree_path}"
            )

    def _validate_task_id(self, task_id: str) -> None:
        if not task_id:
            raise InvalidTaskIdError("task_id must not be empty.")

        if task_id.startswith("."):
            raise InvalidTaskIdError(
                f"task_id must not start with '.': {task_id!r}"
            )

        if ".." in task_id:
            raise InvalidTaskIdError(
                f"task_id must not contain '..': {task_id!r}"
            )

        if "/" in task_id or "\\" in task_id:
            raise InvalidTaskIdError(
                f"task_id must not contain path separators: {task_id!r}"
            )

        if not _TASK_ID_PATTERN.fullmatch(task_id):
            raise InvalidTaskIdError(
                f"task_id contains unsupported characters: {task_id!r}"
            )

    def _branch_name_for_task(self, task_id: str) -> str:
        self._validate_task_id(task_id)
        return f"{TASK_BRANCH_PREFIX}/{task_id}"

    def _worktree_path_for_task(self, task_id: str) -> Path:
        self._validate_task_id(task_id)
        return self.worktree_root / task_id

    def create(
        self,
        task_id: str,
        base_ref: str = "HEAD",
    ) -> WorktreeInfo:
        branch_name = self._branch_name_for_task(task_id)
        worktree_path = self._worktree_path_for_task(task_id)
        base_sha = self._resolve_commit(base_ref)

        self._ensure_can_create_worktree(
            branch_name,
            worktree_path,
        )

        self.worktree_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._run_git(
            [
                "worktree",
                "add",
                "-b",
                branch_name,
                str(worktree_path),
                base_ref,
            ]
        )

        current_branch = self._run_git(
            ["branch", "--show-current"],
            cwd=worktree_path,
        ).decode("utf-8", errors="replace").strip()

        if current_branch != branch_name:
            raise GitWorktreeCommandError(
                f"Created worktree is on {current_branch!r}, expected {branch_name!r}."
            )

        head_sha = self._run_git(
            ["rev-parse", "HEAD"],
            cwd=worktree_path,
        ).decode("utf-8", errors="replace").strip()

        if head_sha != base_sha:
            raise GitWorktreeCommandError(
                f"Created worktree HEAD is {head_sha!r}, expected {base_sha!r}."
            )

        return WorktreeInfo(
            task_id=task_id,
            branch_name=branch_name,
            path=worktree_path,
            base_ref=base_ref,
            base_sha=base_sha,
            head_sha=head_sha,
        )
