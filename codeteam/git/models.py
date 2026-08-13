from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class GitChangeKind(str, Enum):
    MODIFIED = "modified"
    ADDED = "added"
    DELETED = "deleted"
    RENAMED = "renamed"
    COPIED = "copied"
    TYPE_CHANGED = "type_changed"
    UNMERGED = "unmerged"
    UNTRACKED = "untracked"


class GitChange(BaseModel):
    """表示一个文件发生了什么变化

    字段说明：
    - kind： 修改类型
    - path： 修改后的当前路径
    - old_path： 修改前的路径（如果是重命名或复制）
    - similarity： Git 判断新旧文件内容的相似度
    """
    kind: GitChangeKind
    path: str
    old_path: str | None = None
    similarity: int | None = Field(default=None, ge=0, le=100)


class GitDiff(BaseModel):

    """一次仓库变化的完整快照

    字段说明：
    - base_ref：当前变化是相对于哪个版本计算的
    - patch：完整Unified Diff文本
    - changes：结构化文件变化列表
    - untracked_paths：未跟踪的文件路径列表
    - additions：新增行数
    - deletions：删除行数
    - has_binary_changes：是否包含二进制文件变化
    - patch_bytes：Patch 的 UTF-8 字节数
    """

    base_ref: str
    patch: str
    changes: list[GitChange]
    untracked_paths: list[str]
    additions: int = Field(default=0, ge=0)
    deletions: int = Field(default=0, ge=0)
    has_binary_changes: bool = False
    patch_bytes: int = Field(default=0, ge=0)


class PatchStatus(str, Enum):
    """
    补丁状态枚举
    | 状态 | 含义 |
    |---|---|
    | `VALID` | 验证通过，但还没有应用 |
    | `SECURITY_REJECTED` | 因路径或安全策略被拒绝 |
    | `CHECK_FAILED` | `git apply --check` 失败 |
    | `APPLY_FAILED` | 预检查通过，但真正应用失败 |
    | `APPLIED` | 已经成功应用 |
    """
    VALID = "valid"
    SECURITY_REJECTED = "security_rejected"
    CHECK_FAILED = "check_failed"
    APPLY_FAILED = "apply_failed"
    APPLIED = "applied"


class PatchResult(BaseModel):
    """验证或应用 Patch 后返回的统一结果

    字段说明：
    | 字段 | 含义 |
    |---|---|
    | `status` | 最终状态 |
    | `patch_sha256` | 这份 Patch 的唯一内容指纹 |
    | `affected_paths` | Patch 涉及哪些文件 |
    | `stderr` | Git 的错误输出 |
    | `stdout` | Git 的标准输出 |
    | `applied` | 是否真正修改了文件 |
    | `failure_reason` | 给程序或用户看的失败原因 |
    """
    status: PatchStatus
    patch_sha256: str
    affected_paths: list[str]
    stderr: str = ""
    stdout: str = ""
    applied: bool = False
    failure_reason: str | None = None


class WorktreeInfo(BaseModel):
    """一个任务 Worktree 的结构化信息。
    字段说明：
    - task_id: 任务 ID
    - branch_name: 分支名
    - path: linked worktree 的真实目录
    - base_ref: 创建 worktree 时用户传入的起点
    - base_sha: base_ref 解析出来的真实 commit sha
    - head_sha: worktree 创建完成后，它当前 HEAD 的 commit sha
    """

    task_id: str
    branch_name: str
    path: Path
    base_ref: str
    base_sha: str
    head_sha: str


class CheckpointReason(str, Enum):
    """Checkpoint 创建的原因枚举。

    字段说明：
    - TASK_START: 任务启动时创建的 checkpoint
    - BEFORE_TOOL: 执行工具前创建的 checkpoint
    - AFTER_TOOL: 执行工具后创建的 checkpoint
    - BEFORE_ROLLBACK: 回滚前创建的 checkpoint
    - AFTER_ROLLBACK: 回滚后创建的 checkpoint
    - MANUAL: 用户手动创建的 checkpoint
    """
    TASK_START = "task_start"
    BEFORE_TOOL = "before_tool"
    AFTER_TOOL = "after_tool"
    BEFORE_ROLLBACK = "before_rollback"
    AFTER_ROLLBACK = "after_rollback"
    MANUAL = "manual"


class Checkpoint(BaseModel):
    """Agent Runtime 的 workspace snapshot metadata。
    字段说明：
    - checkpoint_id: Checkpoint 的唯一 ID
    - task_id: Checkpoint 所属的任务 ID
    - sequence: Checkpoint 在任务中的顺序号，从 0 开始
    - reason: Checkpoint 创建的原因
    - created_at: Checkpoint 创建的时间戳
    - shadow_commit_sha: Checkpoint 对应的 shadow commit sha
    - shadow_tree_sha: Checkpoint 对应的 shadow tree sha
    - workspace_head_sha: Checkpoint 创建时 workspace 的 HEAD commit sha
    - parent_checkpoint_id: Checkpoint 的父 checkpoint ID，如果没有则为 None
    - file_count: Checkpoint 中的文件数量
    - restored_from: 如果这个 checkpoint 是从另一个 checkpoint 恢复的，则为那个 checkpoint 的 ID，否则为 None
    """

    checkpoint_id: str
    task_id: str
    sequence: int = Field(ge=0)
    reason: CheckpointReason
    created_at: datetime

    shadow_commit_sha: str
    shadow_tree_sha: str
    workspace_head_sha: str

    parent_checkpoint_id: str | None = None
    file_count: int = Field(ge=0)
    restored_from: str | None = None


class CheckpointComparison(BaseModel):
    """Checkpoint snapshot 与当前 workspace 的差异。
    字段说明：
    - task_id: Checkpoint 所属的任务 ID
    - checkpoint_id: Checkpoint 的唯一 ID
    - checkpoint_tree_sha: Checkpoint 对应的 tree sha
    - current_tree_sha: 当前 workspace 的 tree sha，如果 workspace 已经被修改则为 None
    - modified_paths: Checkpoint 与当前 workspace 的修改文件路径列表
    - added_paths: Checkpoint 与当前 workspace 的新增文件路径列表
    - deleted_paths: Checkpoint 与当前 workspace 的删除文件路径列表
    """

    task_id: str
    checkpoint_id: str
    checkpoint_tree_sha: str

    current_tree_sha: str | None = None

    modified_paths: list[str] = Field(default_factory=list)
    added_paths: list[str] = Field(default_factory=list)
    deleted_paths: list[str] = Field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.modified_paths
            or self.added_paths
            or self.deleted_paths
        )


class RollbackStatus(str, Enum):
    SUCCESS = "success"
    REJECTED = "rejected"
    FAILED_RECOVERED = "failed_recovered"
    FAILED_UNRECOVERED = "failed_unrecovered"


class RollbackResult(BaseModel):
    """一次 rollback 操作的结构化结果。
    字段说明：
    - status: rollback 的最终状态
    - task_id: rollback 所属的任务 ID
    - target_checkpoint_id: rollback 的目标 checkpoint ID
    - safety_checkpoint_id: rollback 前创建的安全 checkpoint ID，如果 rollback 失败可以回滚到这个 checkpoint
    - before_tree_sha: rollback 前 workspace 的 tree sha
    - after_tree_sha: rollback 后 workspace 的 tree sha，如果 rollback 失败则为 None
    - restored_paths: rollback 后被恢复的文件路径列表
    - removed_paths: rollback 后被删除的文件路径列表
    - error: rollback 失败的错误信息，如果 rollback 成功则为 None
    """

    status: RollbackStatus
    task_id: str
    target_checkpoint_id: str

    safety_checkpoint_id: str | None = None

    before_tree_sha: str
    after_tree_sha: str | None = None

    restored_paths: list[str] = Field(default_factory=list)
    removed_paths: list[str] = Field(default_factory=list)

    error: str | None = None
