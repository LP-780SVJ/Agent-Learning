"""codeteam.session.errors — Session Runtime 错误层级。

区分两类失败：
- 硬拒绝（本文件异常）：resume 明确不允许继续；
- RECOVERY_REQUIRED（SessionStatus 状态）：不是异常，
  是「对账后决定」，由 SessionService 转换状态。
"""
from __future__ import annotations


class SessionError(Exception):
    """Session 模块错误基类。"""


class SessionNotFoundError(SessionError):
    """session_id 在磁盘上不存在。绝不静默新建同名 Session。"""


class SessionAlreadyExistsError(SessionError):
    """create 时 session 目录已存在。绝不覆盖，可能属于另一进程。"""


class SessionCorruptedError(SessionError):
    """session.json 无法解析为合法快照。"""


class SessionSchemaUnsupportedError(SessionError):
    """schema_version 不在 SUPPORTED_SCHEMA_VERSIONS 中。

    旧版本 ≠ 损坏：未来应走 MigrationRegistry 迁移，
    而不是让 Pydantic 硬猜字段。
    """


class SessionAlreadyActiveError(SessionError):
    """另一进程持有 writer 所有权（single-writer lock）。"""


class SessionTerminalError(SessionError):
    """COMPLETED / FAILED 的 Session 不能作为同一 Task resume。"""


class RepositoryMismatchError(SessionError):
    """当前仓库身份与 Session 记录不一致（cross-repo 方案 A：拒绝）。"""


class WorktreeMissingError(SessionError):
    """Session 引用的 task worktree 已不存在。"""


class CheckpointMissingError(SessionError):
    """Session 引用的 checkpoint 在 Store 中缺失，不许悄悄清引用。"""


class ProviderUnavailableError(SessionError):
    """Session 记录的 provider/model 当前不可用（不许静默换模型）。"""

class SessionRecoveryRequiredError(SessionError):
    """对账结论为 RECOVERY_REQUIRED：不能直接续跑。

    不是「坏了」：Session 已被标记 RECOVERY_REQUIRED 落盘，
    issues 携带具体漂移项，等待恢复流程（Day 5）或人工介入。
    """

    def __init__(self, issues: tuple[str, ...] | list[str]) -> None:
        super().__init__("; ".join(issues))
        self.issues = tuple(issues)