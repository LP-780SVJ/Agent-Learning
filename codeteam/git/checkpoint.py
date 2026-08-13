from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from codeteam.git.errors import (
    CheckpointOwnershipError,
    CheckpointStoreError,
    InvalidTaskIdError,
    RollbackVerificationError,
)
from codeteam.git.models import (
    Checkpoint,
    CheckpointComparison,
    CheckpointReason,
    RollbackResult,
    RollbackStatus,
)

DEFAULT_STATE_DIR_NAME = ".codeteam/checkpoints"
_TASK_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]+")
SNAPSHOT_EXCLUDED_DIR_NAMES = {
    ".git",
    ".codeteam",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "build",
    "dist",
}
DEFAULT_GIT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class SnapshotScope:
    """定义 checkpoint 管理哪些 workspace 文件。

    Symlink policy: checkpoint creation rejects symlinks instead of following
    them or snapshotting link targets. This avoids leaking files outside the
    workspace through symlink traversal.
    """

    include_tracked: bool = True
    include_untracked_non_ignored: bool = True
    excluded_dir_names: frozenset[str] = frozenset(SNAPSHOT_EXCLUDED_DIR_NAMES)


@dataclass(frozen=True)
class CheckpointLayout:
    """一个 task 的 checkpoint runtime state 路径布局。"""

    state_root: Path
    task_id: str

    @property
    def task_state_dir(self) -> Path:
        return self.state_root / "tasks" / self.task_id

    @property
    def shadow_repo_dir(self) -> Path:
        return self.task_state_dir / "shadow"

    @property
    def metadata_dir(self) -> Path:
        return self.task_state_dir / "checkpoints"


class CheckpointManager:
    """管理单个 task worktree 的 checkpoint scope 和 runtime state。"""

    def __init__(
        self,
        workspace_root: Path | str,
        state_root: Path | str,
        task_id: str,
        *,
        scope: SnapshotScope | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve(strict=True)
        if not self.workspace_root.is_dir():
            raise ValueError("workspace_root must be an existing directory.")

        _validate_task_id(task_id)
        self.state_root = Path(state_root).resolve(strict=False)
        self.task_id = task_id
        self.scope = scope or SnapshotScope()
        self.layout = CheckpointLayout(
            state_root=self.state_root,
            task_id=task_id,
        )

        self._validate_runtime_state_outside_workspace()

    def _validate_runtime_state_outside_workspace(self) -> None:
        workspace = self.workspace_root
        state_root = self.state_root

        if _is_relative_to(state_root, workspace):
            raise ValueError("checkpoint state_root must be outside workspace_root.")

    def managed_paths(self) -> list[str]:
        paths: list[str] = []

        if self.scope.include_tracked:
            paths.extend(
                self._git_paths(["ls-files", "-z"])
            )

        if self.scope.include_untracked_non_ignored:
            paths.extend(
                self._git_paths(
                    ["ls-files", "--others", "--exclude-standard", "-z"]
                )
            )

        return sorted(
            path for path in dict.fromkeys(paths) if self._is_managed_path(path)
        )

    def _git_paths(self, args: list[str]) -> list[str]:
        output = self._run_git(args, cwd=self.workspace_root)
        return [
            path
            for path in output.decode("utf-8", errors="replace").split("\0")
            if path
        ]

    def _is_managed_path(self, relative_path: str) -> bool:
        path = Path(relative_path)

        if path.is_absolute() or ".." in path.parts:
            return False

        if any(part in self.scope.excluded_dir_names for part in path.parts):
            return False

        candidate_parent = (self.workspace_root / relative_path).parent.resolve(
            strict=False
        )
        return _is_relative_to(candidate_parent, self.workspace_root)

    def initialize(self) -> None:
        """初始化当前 task 的 shadow git repository 和 metadata 目录。"""
        self.layout.metadata_dir.mkdir(parents=True, exist_ok=True)

        if self.is_initialized():
            return

        self.layout.shadow_repo_dir.mkdir(parents=True, exist_ok=True)
        self._run_git(
            ["init", "--quiet"],
            cwd=self.layout.shadow_repo_dir,
        )
        self._run_git(
            ["config", "--local", "user.name", "CodeTeam Checkpoint"],
            cwd=self.layout.shadow_repo_dir,
        )
        self._run_git(
            ["config", "--local", "user.email", "checkpoint@codeteam.local"],
            cwd=self.layout.shadow_repo_dir,
        )
        self._run_git(
            ["config", "--local", "core.quotepath", "false"],
            cwd=self.layout.shadow_repo_dir,
        )

    def is_initialized(self) -> bool:
        return (self.layout.shadow_repo_dir / ".git").is_dir()

    def _run_git(
        self,
        args: list[str],
        *,
        cwd: Path,
    ) -> bytes:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=cwd,
                capture_output=True,
                shell=False,
                timeout=DEFAULT_GIT_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise CheckpointStoreError(
                f"Git command timed out: git {' '.join(args)}"
            ) from error

        if result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="replace")
            raise CheckpointStoreError(
                message or f"Git command failed: git {' '.join(args)}"
            )

        return result.stdout

    def create(
        self,
        reason: CheckpointReason = CheckpointReason.MANUAL,
        *,
        restored_from: str | None = None,
    ) -> Checkpoint:
        """创建一个新的 checkpoint。

        Args:
            reason: 创建 checkpoint 的原因。
            restored_from: 如果是从某个 checkpoint 恢复的，则传入该 checkpoint 的 ID，否则为 None。
        Returns:
            新创建的 Checkpoint 对象。
        Raises:
            CheckpointStoreError: 如果 Git 操作失败。
        """
        self.initialize()

        existing = self.list_checkpoints()
        sequence = len(existing)
        parent_id = existing[-1].checkpoint_id if existing else None
        checkpoint_id = f"cp-{sequence:06d}"

        paths = self.managed_paths()
        self._sync_workspace_to_shadow(paths)

        self._run_git(["add", "--all"], cwd=self.layout.shadow_repo_dir)
        self._run_git(
            [
                "commit",
                "--quiet",
                "--allow-empty",
                "-m",
                f"{checkpoint_id}: {reason.value}",
            ],
            cwd=self.layout.shadow_repo_dir,
        )

        shadow_commit_sha = self._git_text(
            ["rev-parse", "HEAD"],
            cwd=self.layout.shadow_repo_dir,
        )
        shadow_tree_sha = self._git_text(
            ["rev-parse", "HEAD^{tree}"],
            cwd=self.layout.shadow_repo_dir,
        )
        workspace_head_sha = self._git_text(
            ["rev-parse", "HEAD"],
            cwd=self.workspace_root,
        )

        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            task_id=self.task_id,
            sequence=sequence,
            reason=reason,
            created_at=datetime.now(timezone.utc),
            shadow_commit_sha=shadow_commit_sha,
            shadow_tree_sha=shadow_tree_sha,
            workspace_head_sha=workspace_head_sha,
            parent_checkpoint_id=parent_id,
            file_count=len(paths),
            restored_from=restored_from,
        )
        self._write_checkpoint_metadata(checkpoint)
        return checkpoint

    def compare(self, checkpoint: Checkpoint) -> CheckpointComparison:
        self._validate_checkpoint_ownership(checkpoint)

        snapshot_hashes = self._checkpoint_file_hashes(checkpoint)
        current_hashes = self._workspace_file_hashes(self.managed_paths())

        snapshot_paths = set(snapshot_hashes)
        current_paths = set(current_hashes)

        added_paths = sorted(current_paths - snapshot_paths)
        deleted_paths = sorted(snapshot_paths - current_paths)
        modified_paths = sorted(
            path
            for path in snapshot_paths & current_paths
            if snapshot_hashes[path] != current_hashes[path]
        )

        return CheckpointComparison(
            task_id=self.task_id,
            checkpoint_id=checkpoint.checkpoint_id,
            checkpoint_tree_sha=checkpoint.shadow_tree_sha,
            modified_paths=modified_paths,
            added_paths=added_paths,
            deleted_paths=deleted_paths,
        )

    def list_checkpoints(self) -> list[Checkpoint]:
        if not self.layout.metadata_dir.exists():
            return []

        checkpoints: list[Checkpoint] = []
        for path in sorted(self.layout.metadata_dir.glob("cp-*.json")):
            checkpoints.append(
                Checkpoint.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            )
        return checkpoints

    def _write_checkpoint_metadata(self, checkpoint: Checkpoint) -> None:
        self.layout.metadata_dir.mkdir(parents=True, exist_ok=True)
        path = self.layout.metadata_dir / f"{checkpoint.checkpoint_id}.json"
        path.write_text(
            checkpoint.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def _git_text(
        self,
        args: list[str],
        *,
        cwd: Path,
    ) -> str:
        return self._run_git(args, cwd=cwd).decode(
            "utf-8",
            errors="replace",
        ).strip()

    def _sync_workspace_to_shadow(self, paths: list[str]) -> None:
        """将 workspace 中的文件同步到 shadow git repository。"""
        self._clear_shadow_worktree()

        for relative_path in paths:
            source = self.workspace_root / relative_path
            target = self.layout.shadow_repo_dir / relative_path

            if source.is_symlink():
                raise CheckpointStoreError(
                    "Checkpoint refuses to snapshot symlinks: "
                    f"{relative_path!r}"
                )

            if not source.is_file():
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def _clear_shadow_worktree(self) -> None:
        shadow_root = self.layout.shadow_repo_dir
        shadow_root.mkdir(parents=True, exist_ok=True)

        for child in shadow_root.iterdir():
            if child.name == ".git":
                continue

            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    def _validate_checkpoint_ownership(self, checkpoint: Checkpoint) -> None:
        if checkpoint.task_id != self.task_id:
            raise CheckpointOwnershipError(
                f"Checkpoint {checkpoint.checkpoint_id!r} belongs to "
                f"{checkpoint.task_id!r}, not {self.task_id!r}."
            )

    def _checkpoint_file_hashes(
        self,
        checkpoint: Checkpoint,
    ) -> dict[str, str]:
        output = self._run_git(
            ["ls-tree", "-r", "-z", "--name-only", checkpoint.shadow_commit_sha],
            cwd=self.layout.shadow_repo_dir,
        )
        paths = [
            path
            for path in output.decode("utf-8", errors="replace").split("\0")
            if path
        ]

        hashes: dict[str, str] = {}
        for path in paths:
            content = self._run_git(
                ["show", f"{checkpoint.shadow_commit_sha}:{path}"],
                cwd=self.layout.shadow_repo_dir,
            )
            hashes[path] = hashlib.sha256(content).hexdigest()
        return hashes

    def _workspace_file_hashes(self, paths: list[str]) -> dict[str, str]:
        hashes: dict[str, str] = {}

        for relative_path in paths:
            path = self.workspace_root / relative_path
            if not path.is_file():
                continue
            hashes[relative_path] = hashlib.sha256(path.read_bytes()).hexdigest()

        return hashes

    def rollback(self, checkpoint: Checkpoint) -> RollbackResult:
        self._validate_checkpoint_ownership(checkpoint)

        comparison = self.compare(checkpoint)
        safety_checkpoint = self.create(CheckpointReason.BEFORE_ROLLBACK)

        restored_paths = sorted(
            set(comparison.modified_paths) | set(comparison.deleted_paths)
        )
        removed_paths = list(comparison.added_paths)

        try:
            self._restore_checkpoint(checkpoint)
            verification = self.compare(checkpoint)
            if verification.has_changes:
                raise RollbackVerificationError(
                    f"Rollback verification failed for {checkpoint.checkpoint_id}."
                )

            return RollbackResult(
                status=RollbackStatus.SUCCESS,
                task_id=self.task_id,
                target_checkpoint_id=checkpoint.checkpoint_id,
                safety_checkpoint_id=safety_checkpoint.checkpoint_id,
                before_tree_sha=safety_checkpoint.shadow_tree_sha,
                after_tree_sha=checkpoint.shadow_tree_sha,
                restored_paths=restored_paths,
                removed_paths=removed_paths,
            )
        except Exception as error:  # noqa: BLE001
            return self._recover_failed_rollback(
                target_checkpoint=checkpoint,
                safety_checkpoint=safety_checkpoint,
                restored_paths=restored_paths,
                removed_paths=removed_paths,
                error=error,
            )
    def _restore_checkpoint(self, checkpoint: Checkpoint) -> None:
        target_paths = set(self._checkpoint_paths(checkpoint))
        current_paths = set(self.managed_paths())

        for relative_path in sorted(current_paths - target_paths):
            self._remove_workspace_path(relative_path)

        for relative_path in sorted(target_paths):
            content = self._run_git(
                ["show", f"{checkpoint.shadow_commit_sha}:{relative_path}"],
                cwd=self.layout.shadow_repo_dir,
            )
            destination = self.workspace_root / relative_path
            self._replace_file(destination, content)

    def _checkpoint_paths(self, checkpoint: Checkpoint) -> list[str]:
        output = self._run_git(
            ["ls-tree", "-r", "-z", "--name-only", checkpoint.shadow_commit_sha],
            cwd=self.layout.shadow_repo_dir,
        )
        return [
            path
            for path in output.decode("utf-8", errors="replace").split("\0")
            if path
        ]

    def _remove_workspace_path(self, relative_path: str) -> None:
        path = self.workspace_root / relative_path
        if path.is_symlink() or path.is_file():
            path.unlink()
            self._remove_empty_parents(path.parent)

    def _replace_file(self, path: Path, content: bytes) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.exists() and path.is_dir():
            shutil.rmtree(path)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def _remove_empty_parents(self, path: Path) -> None:
        current = path
        while current != self.workspace_root and _is_relative_to(
            current,
            self.workspace_root,
        ):
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent

    def _recover_failed_rollback(
        self,
        *,
        target_checkpoint: Checkpoint,
        safety_checkpoint: Checkpoint,
        restored_paths: list[str],
        removed_paths: list[str],
        error: Exception,
    ) -> RollbackResult:
        try:
            self._restore_checkpoint(safety_checkpoint)
            verification = self.compare(safety_checkpoint)
            if verification.has_changes:
                raise RollbackVerificationError(
                    f"Safety checkpoint verification failed for "
                    f"{safety_checkpoint.checkpoint_id}."
                )

            return RollbackResult(
                status=RollbackStatus.FAILED_RECOVERED,
                task_id=self.task_id,
                target_checkpoint_id=target_checkpoint.checkpoint_id,
                safety_checkpoint_id=safety_checkpoint.checkpoint_id,
                before_tree_sha=safety_checkpoint.shadow_tree_sha,
                after_tree_sha=safety_checkpoint.shadow_tree_sha,
                restored_paths=restored_paths,
                removed_paths=removed_paths,
                error=str(error),
            )
        except Exception as recovery_error:  # noqa: BLE001
            return RollbackResult(
                status=RollbackStatus.FAILED_UNRECOVERED,
                task_id=self.task_id,
                target_checkpoint_id=target_checkpoint.checkpoint_id,
                safety_checkpoint_id=safety_checkpoint.checkpoint_id,
                before_tree_sha=safety_checkpoint.shadow_tree_sha,
                after_tree_sha=None,
                restored_paths=restored_paths,
                removed_paths=removed_paths,
                error=f"{error}; recovery failed: {recovery_error}",
            )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _validate_task_id(task_id: str) -> None:
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
