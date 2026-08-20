"""codeteam.session.models — Session 持久化的 Durable Domain State 契约。

本文件只回答一个问题：哪些状态必须在进程死后仍然存在？

Durable（本文件模型）：
    Task 契约 / 执行状态 / Plan / Provider+Model 标识 /
    Usage 预算计数 / Worktree 引用 / Checkpoint 引用 /
    in-flight 操作边界 / 最近失败

绝不进入 Session 的 Ephemeral Runtime 对象：
    ModelClient（HTTP 连接）、GitWorkspace、CheckpointManager、
    锁、subprocess.Popen、DockerRunner ——
    Resume 时从 Durable 配方重建，而不是反序列化旧对象。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_serializer, field_validator

from codeteam.events import AgentEventType
from codeteam.failures.models import AgentFailure
from codeteam.planning.models import Plan
from codeteam.task.models import TaskSpec
from codeteam.task.state import TaskStatus

SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1})
"""Loader 允许加载的 schema 代数。旧版本 ≠ 损坏（未来走 Migration）。"""

CURRENT_SCHEMA_VERSION = 1


class SessionStatus(str, Enum):
    """Session 的 Runtime 生命周期状态。

    与 TaskStatus 是两个维度，同时存在合法：
    SessionStatus=PAUSED + TaskStatus=VERIFYING 表示
    「任务执行到验证阶段时整个会话被暂停」。
    """
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    RECOVERY_REQUIRED = "recovery_required"  # stale RUNNING / drift 的中转态
    COMPLETED = "completed"                  # Terminal
    FAILED = "failed"                        # Terminal


class OperationStatus(str, Enum):
    """in-flight 操作的三段边界（day4.md §十四）。"""
    PREPARED = "prepared"
    STARTED = "started"
    COMPLETED = "completed"


def _require_aware(value: datetime, field_name: str) -> datetime:
    """拒绝 naive datetime：无时区的时间戳无法跨进程安全比较。"""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} 必须是 timezone-aware datetime")
    return value


class SessionManifest(BaseModel):
    """session.json 头部：格式与状态版本元数据。

    schema_version：Durable State 的格式代数（加字段/改结构才 +1）。
    state_version：第几次快照更新（每次 save +1）。
    last_event_seq：与 events.jsonl 对齐的审计游标。
    """
    schema_version: int = CURRENT_SCHEMA_VERSION
    session_id: str
    state_version: int = 1
    repo_id: str
    created_at: datetime
    updated_at: datetime
    last_event_seq: int = 0

    @field_validator("created_at", "updated_at")
    @classmethod
    def _check_aware(cls, value: datetime, info) -> datetime:
        return _require_aware(value, info.field_name)


class RepositoryRef(BaseModel):
    """仓库身份。

    用 git_common_dir（git rev-parse --git-common-dir 的输出）而不是
    remote URL：两个本地 clone 的 remote URL 完全相同，
    但它们是不同的 Runtime 工作区。
    探测函数（需要跑 git）放 service，不放纯数据模型。
    """
    repo_id: str
    git_common_dir: str
    base_sha: str


class WorktreeRef(BaseModel):
    """Task Worktree 身份 + 最近已知状态（Reconciliation 的对账基线）。

    head_sha：创建时的 HEAD，不变（历史事实）。
    last_known_head_sha：最近一次 save 时的 HEAD（随快照更新）。
    两者不等 = 外部有人动过 worktree → RECOVERY_REQUIRED。
    """
    task_id: str
    branch_name: str
    path: str
    base_sha: str
    head_sha: str
    last_known_head_sha: str
    last_known_dirty: bool = False


class ActiveOperation(BaseModel):
    """结果不确定的 in-flight 操作（Crash Recovery 关键）。

    kind 是开放集合（plan_generation / patch_apply / verification / ...），
    与 orchestrator._execute_with_recovery 的 operation 参数同名。
    status 必须 STOP 前落盘 STARTED，Resume 据此决定 reconcile。
    """
    operation_id: str
    kind: str
    status: OperationStatus
    checkpoint_before: str | None = None
    started_at: datetime | None = None


class SessionUsage(BaseModel):
    """Durable 预算计数（day4.md §六十四~六十五）。

    这些计数若不持久化，Resume 后归零 =
    预算被绕过 / 停止条件失效。是 ephemeral UsageTracker 的
    durable 投影，不是序列化 UsageTracker 本身。
    """
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    tool_calls: int = 0
    repair_attempts: int = 0
    retry_count: int = 0


class SessionEvent(BaseModel):
    """events.jsonl 的一行：append-only 审计事实。

    seq 从 1 严格递增（发现缺失/重复/乱序）；
    state_version 把 event 与当时的 snapshot 对齐。
    """
    event_id: str
    session_id: str
    seq: int = Field(ge=1)
    state_version: int = Field(ge=1)
    type: AgentEventType
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def _check_aware(cls, value: datetime, info) -> datetime:
        return _require_aware(value, info.field_name)


class ContextMetadata(BaseModel):
    """context.json 的最小版。完整 Compaction 是 Day 5。"""
    context_version: int = 1
    summary: str | None = None
    recent_turn_ids: tuple[str, ...] = ()
    retrieved_files: tuple[str, ...] = ()


class Session(BaseModel):
    """Durable Session 快照 = session.json 的全部内容。

    只存 checkpoint 的 id 引用，绝不复制 workspace 文件。
    """
    manifest: SessionManifest
    status: SessionStatus = SessionStatus.CREATED
    task: TaskSpec
    task_status: TaskStatus = TaskStatus.CREATED
    plan: Plan | None = None
    provider_id: str
    model_id: str
    usage: SessionUsage = Field(default_factory=SessionUsage)
    repo: RepositoryRef
    worktree: WorktreeRef | None = None
    checkpoint_ids: tuple[str, ...] = ()
    current_checkpoint_id: str | None = None
    active_operation: ActiveOperation | None = None
    last_failure: AgentFailure | None = None

    @field_validator("provider_id", "model_id")
    @classmethod
    def _check_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("provider_id / model_id 不能为空或纯空白")
        return stripped

    @field_serializer("last_failure")
    def _sanitize_last_failure(
        self, value: AgentFailure | None
    ) -> dict[str, Any] | None:
        """F10：sanitize before persist。

        source_message 是内部诊断信息、可能含敏感内容，
        在序列化边界打码。副作用：model_dump() 输出中该字段
        变为 dict；load 回来 source_message 恒为 "<redacted>"。
        metadata 字段的脱敏是已知限制（记入 Failure Case）。
        """
        if value is None:
            return None
        data = value.model_dump()
        if data.get("source_message") is not None:
            data["source_message"] = "<redacted>"
        return data


class ReconciliationVerdict(str, Enum):
    """对账裁决。全序：INVALID > RECOVERY_REQUIRED > RESUMABLE。"""
    RESUMABLE = "resumable"
    RECOVERY_REQUIRED = "recovery_required"
    INVALID = "invalid"