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