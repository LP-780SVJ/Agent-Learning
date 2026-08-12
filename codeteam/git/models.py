from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field
from pathlib import Path


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
