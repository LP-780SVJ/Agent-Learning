class GitWorkspaceError(RuntimeError):
    """Git workspace 模块的基础异常。"""


class NotGitRepositoryError(GitWorkspaceError):
    """给定目录不是 Git 仓库。"""


class GitCommandError(GitWorkspaceError):
    """Git 子进程执行失败。"""


class PatchParseError(GitWorkspaceError):
    """无法解析 Patch 或 Git 的机器格式输出。"""


class PatchSecurityError(GitWorkspaceError):
    """Patch 违反路径或安全限制。"""

class WorktreeError(GitWorkspaceError):
    """Git worktree 管理失败。"""


class InvalidTaskIdError(WorktreeError):
    """任务 ID 不符合安全命名规则。"""


class BaseRefNotFoundError(WorktreeError):
    """创建 Worktree 的 base_ref 不存在或不是 commit。"""


class BranchAlreadyExistsError(WorktreeError):
    """目标任务分支已经存在。"""


class WorktreePathConflictError(WorktreeError):
    """目标 Worktree 路径已经存在或不可用。"""


class GitWorktreeCommandError(WorktreeError):
    """git worktree 子命令执行失败。"""


class CheckpointError(GitWorkspaceError):
    """Checkpoint 管理失败。"""


class CheckpointNotFoundError(CheckpointError):
    """指定 checkpoint 不存在。"""


class CheckpointOwnershipError(CheckpointError):
    """Checkpoint 不属于当前 task 或 workspace。"""


class CheckpointStoreError(CheckpointError):
    """Checkpoint 存储层失败。"""


class RollbackVerificationError(CheckpointError):
    """Rollback 后状态校验失败。"""
