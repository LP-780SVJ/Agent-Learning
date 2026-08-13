from __future__ import annotations

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
