from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class PolicyDecision(str, Enum):
    ALLOW = "allow"
    ALLOW_SANDBOXED = "allow_sandboxed"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class RiskCategory(str, Enum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    DESTRUCTIVE = "destructive"
    NETWORK = "network"
    REMOTE_WRITE = "remote_write"
    SECRET_ACCESS = "secret_access"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    SHELL_INTERPRETER = "shell_interpreter"
    FILESYSTEM_ESCAPE = "filesystem_escape"
    UNKNOWN = "unknown"


class CommandRequest(BaseModel):
    """表示一个命令请求的结构化数据。

    字段说明：
    - argv: 命令行参数
    - cwd: 当前工作目录
    - workspace_root: 工作区根目录
    - task_id: 任务 ID
    - agent_id: Agent ID
    - reason: 请求原因
    - timeout_seconds: 超时时间（秒）
    """

    argv: tuple[str, ...] = Field(min_length=1)
    cwd: Path
    workspace_root: Path
    task_id: str | None = None
    agent_id: str | None = None
    reason: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)

    def fingerprint(self) -> str:
        return command_request_fingerprint(self)


def command_request_fingerprint(request: CommandRequest) -> str:
    canonical = {
        "schema_version": 1,
        "argv": list(request.argv),
        "cwd": _canonical_path(request.cwd),
        "workspace_root": _canonical_path(request.workspace_root),
        "task_id": request.task_id or "",
        "agent_id": request.agent_id or "",
        "timeout_seconds": request.timeout_seconds,
    }
    payload = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_path(path: Path) -> str:
    return str(path.expanduser().resolve(strict=False))


class RuleResult(BaseModel):
    """表示一个规则检查的结果。

    字段说明：
    - rule_name: 规则名称
    - decision: 决策
    - risks: 风险类别
    - reason: 原因
    """

    rule_name: str
    decision: PolicyDecision
    risks: tuple[RiskCategory, ...] = ()
    reason: str


class PolicyEvaluation(BaseModel):
    """表示一个策略评估的结果。

    字段说明：
    - decision: 最终决策
    - risks: 涉及的风险类别
    - reasons: 决策的原因
    - matched_rules: 匹配的规则列表
    """

    decision: PolicyDecision
    risks: tuple[RiskCategory, ...] = ()
    reasons: tuple[str, ...] = ()
    matched_rules: tuple[str, ...] = ()


class ApprovalScope(str, Enum):
    ONCE = "once"
    TASK = "task"


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    DENIED = "denied"


class ApprovalRequest(BaseModel):
    """一次需要人工授权的命令请求。

    字段说明：
    - approval_id: 授权请求的 ID
    - task_id: 任务 ID
    - agent_id: Agent ID
    - command_fingerprint: 命令的指纹，用于唯一标识命令
    - argv: 命令行参数
    - cwd: 当前工作目录
    - workspace_root: 工作区根目录
    - risks: 涉及的风险类别
    - reasons: 需要授权的原因
    - requested_scope: 请求的授权范围（一次性或任务级别）
    - created_at: 授权请求创建的时间
    """

    approval_id: str

    task_id: str
    agent_id: str | None = None

    command_fingerprint: str

    argv: tuple[str, ...] = Field(min_length=1)
    cwd: Path
    workspace_root: Path

    risks: tuple[RiskCategory, ...] = ()
    reasons: tuple[str, ...] = ()

    requested_scope: ApprovalScope = ApprovalScope.ONCE
    created_at: datetime


class ApprovalGrant(BaseModel):
    """用户批准后产生的授权凭证。

    字段说明：
    - approval_id: 授权请求的 ID
    - command_fingerprint: 命令的指纹，用于唯一标识命令
    - task_id: 任务 ID
    - agent_id: Agent ID
    - scope: 授权的范围（一次性或任务级别）
    - decision: 授权的决策（批准或拒绝）
    - created_at: 授权创建的时间
    - consumed_at: 授权被使用的时间（如果已使用）
    """

    approval_id: str
    command_fingerprint: str

    task_id: str
    agent_id: str | None = None

    scope: ApprovalScope
    decision: ApprovalDecision

    created_at: datetime
    consumed_at: datetime | None = None

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None


class CommandStatus(str, Enum):
    """表示命令执行的状态。

    字段说明：
    - SUCCESS: 命令执行成功
    - NONZERO_EXIT: 命令执行失败，退出码非零
    - TIMED_OUT: 命令执行超时
    - START_FAILED: 命令启动失败
    - POLICY_DENIED: 命令被策略拒绝执行
    - APPROVAL_DENIED: 命令被人工授权拒绝执行
    - APPROVAL_REQUIRED: 命令需要人工授权才能执行
    """
    SUCCESS = "success"
    NONZERO_EXIT = "nonzero_exit"
    TIMED_OUT = "timed_out"
    START_FAILED = "start_failed"
    POLICY_DENIED = "policy_denied"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_REQUIRED = "approval_required"


class CommandLimits(BaseModel):
    """表示命令执行的限制条件。

    字段说明：
    - timeout_seconds: 命令执行的超时时间（秒）
    - terminate_grace_seconds: 在发送 SIGTERM 后等待的时间（秒）
    - max_stdout_bytes: 标准输出的最大字节数
    - max_stderr_bytes: 标准错误的最大字节数
    """
    timeout_seconds: float = Field(default=60.0, gt=0)
    terminate_grace_seconds: float = Field(default=2.0, ge=0)

    max_stdout_bytes: int = Field(default=64 * 1024, gt=0)
    max_stderr_bytes: int = Field(default=64 * 1024, gt=0)


class CommandResult(BaseModel):
    """表示命令执行的结果。

    字段说明：
    - status: 命令执行状态
    - argv: 命令行参数
    - cwd: 当前工作目录
    - exit_code: 命令退出码
    - stdout: 标准输出内容
    - stderr: 标准错误内容
    - stdout_total_bytes: 标准输出的总字节数
    - stderr_total_bytes: 标准错误的总字节数
    - stdout_truncated: 标准输出是否被截断
    - stderr_truncated: 标准错误是否被截断
    - timed_out: 命令是否超时
    - duration_ms: 命令执行的持续时间（毫秒）
    - terminated_with_sigterm: 是否通过 SIGTERM 终止
    - terminated_with_sigkill: 是否通过 SIGKILL 终止
    - error: 执行过程中发生的错误信息
    - policy_decision: 记录 policy 最终判断
    - approval_id: 返回给上层 UI / 人类审批
    - reasons: 告诉用户为什么被拒绝或需要 approval
    """
    status: CommandStatus

    argv: tuple[str, ...] = ()
    cwd: Path | None = None

    exit_code: int | None = None

    stdout: str = ""
    stderr: str = ""

    stdout_total_bytes: int = Field(default=0, ge=0)
    stderr_total_bytes: int = Field(default=0, ge=0)

    stdout_truncated: bool = False
    stderr_truncated: bool = False

    timed_out: bool = False
    duration_ms: float = Field(default=0.0, ge=0)

    terminated_with_sigterm: bool = False
    terminated_with_sigkill: bool = False

    error: str | None = None

    policy_decision: PolicyDecision | None = None
    approval_id: str | None = None
    reasons: tuple[str, ...] = ()
