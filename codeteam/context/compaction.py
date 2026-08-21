"""codeteam.context.compaction — 会话级上下文压缩（W4D5）。

与 context/compressor.py（Week 2）的区别：
- compressor.py 压缩【代码文件】（CompressionLevel 降级链，repo-map 用）
- 本文件压缩【会话历史】（Summary + Recent Window，Agent Runtime 用）

Invariant（day5 §二十）：Compaction 只产出新的 Active Context 材料，
绝不删除 Durable Session History——本模块不持有 Store/Session 引用，
不写任何持久化（结构性保证，测试断言）。
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from codeteam.llm.registry import ModelSelection
from codeteam.schemas.messages import Message
from codeteam.usage.token_counter import TokenCounter


class CompactionReason(str, Enum):
    AUTO_THRESHOLD = "auto_threshold"            # Turn 末超阈值
    MODEL_SWITCH = "model_switch"                # 小窗口切换前预压（§三十五）
    MANUAL = "manual"                            # 用户显式 /compact
    CONTEXT_OVERFLOW_RECOVERY = "context_overflow_recovery"  # K2 恢复动作


class MessageRef(BaseModel):
    """消息的轻量引用（Message 无 id 字段，用位置索引标识）。

    durable：进 CompactionResult 供审计"压了哪些/留了哪些"。
    """

    index: int = Field(ge=0)
    role: str
    token_count: int = Field(ge=0)


class ContextSummary(BaseModel):
    """结构化 Working Memory（day5 §十七）——不是一段散文。

    权威边界：task constraints / plan status / checkpoint identity
    不由本对象承载——它们从 TaskSpec/Plan/Session 重新注入（Step 3）。
    Summary 只负责"过去发生了什么"（§九）。
    """

    summary_version: int = Field(ge=1)

    task_goal: str = ""

    confirmed_facts: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    modified_files: tuple[str, ...] = ()
    failed_attempts: tuple[str, ...] = ()
    verification_state: tuple[str, ...] = ()
    unresolved_issues: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = ()

    current_checkpoint_id: str | None = None

    compacted_message_indices: tuple[int, ...] = ()
    """被本版 Summary 吸收的消息范围（审计 + 防重复压缩）。"""

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class CompactionRequest(BaseModel):
    """为什么压 / 压哪段 / 当前容量多少（§十八）。"""

    session_id: str
    reason: CompactionReason
    model_selection: ModelSelection

    context_window_tokens: int = Field(ge=1)
    current_context_tokens: int = Field(ge=0)
    target_context_tokens: int = Field(ge=1)

    previous_summary: ContextSummary | None = None
    recent_window_budget_tokens: int = Field(ge=0)

    @field_validator("target_context_tokens")
    @classmethod
    def _target_within_window(cls, value: int, info) -> int:
        # window 在场（pydantic 后续校验顺序不保证跨字段，这里在
        # Compactor 里做跨字段断言；单字段只防"压到 0"这种荒谬值）
        return value


class CompactionResult(BaseModel):
    """压缩的完整计量（§十九，Benchmark 数据出口）。"""

    summary: ContextSummary
    reason: CompactionReason

    compacted_refs: tuple[MessageRef, ...] = ()
    retained_refs: tuple[MessageRef, ...] = ()

    tokens_before: int = Field(ge=0)
    tokens_after: int = Field(ge=0)
    summary_tokens: int = Field(ge=0)
    recent_window_tokens: int = Field(ge=0)
    recent_window_over_budget: bool = False
    """最后一条消息单条超预算时仍保留（C4 防御），但必须可观测。"""

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class SummarizationInput(BaseModel):
    """summarizer 的输入契约：待压消息 + 上一版 Summary + 元信息。"""

    messages: tuple[Message, ...]
    previous_summary: ContextSummary | None
    reason: CompactionReason
    session_id: str


Summarizer = Callable[[SummarizationInput], ContextSummary]


def is_compaction_needed(
    current_tokens: int,
    target_tokens: int,
) -> bool:
    """触发判定（§二十一）：当前超出目标即需压缩。纯函数。"""
    return current_tokens > target_tokens


def build_recent_window(
    messages: tuple[Message, ...],
    *,
    budget_tokens: int,
    counter: TokenCounter,
) -> tuple[tuple[Message, ...], tuple[MessageRef, ...], int, bool]:
    """按 token 预算从后往前装配 Recent Window（§十三~十四）。

    Returns:
        (kept_messages, kept_refs, total_tokens, over_budget)
        over_budget=True 表示最后一条单条即超预算——仍保留（窗口
        不能为空，模型不能对最近事实失忆），由调用方观测。
    """
    kept: list[tuple[int, Message, int]] = []  # (原始位置, 消息, token)
    total = 0
    over_budget = False

    # reversed(list(enumerate(...)))：位置先行，从后往前装（§十四）
    for index, message in reversed(list(enumerate(messages))):
        tokens = counter.count_text(message.content or "")
        if total + tokens > budget_tokens and kept:
            break  # 预算尽且窗口非空 → 停
        if total + tokens > budget_tokens and not kept:
            over_budget = True  # 单条超预算：仍保留最后一条
        kept.append((index, message, tokens))
        total += tokens

    kept.reverse()  # 恢复时间序

    refs = tuple(
        MessageRef(index=index, role=message.role, token_count=tokens)
        for index, message, tokens in kept
    )
    return (
        tuple(message for _, message, _ in kept),
        refs,
        total,
        over_budget,
    )


class ContextCompactor:
    """压缩编排：判定 → 分段（recent/compacted）→ summarize → 计量。

    summarizer 注入（§四十五：先 Mock 测试，真实 LLM 后接）；
    缺省 deterministic fallback——保留 previous_summary 并把待压
    消息降为 role 级统计（保底永不崩，信息损失可观测于 Summary 字段）。
    """

    def __init__(
        self,
        counter: TokenCounter,
        *,
        summarizer: Summarizer | None = None,
    ) -> None:
        self._counter = counter
        self._summarizer = summarizer or self._fallback_summary

    def compact(
        self,
        request: CompactionRequest,
        *,
        messages: tuple[Message, ...],
    ) -> CompactionResult:
        """执行一次压缩。绝不修改 messages，绝不触碰任何存储。"""
        if request.target_context_tokens >= request.context_window_tokens:
            raise ValueError(
                "target_context_tokens 必须 < context_window_tokens"
            )

        recent, recent_refs, recent_tokens, over_budget = build_recent_window(
            messages,
            budget_tokens=request.recent_window_budget_tokens,
            counter=self._counter,
        )

        # 分段：recent 之外的进入 summary
        recent_set = {id(m) for m in recent}
        compacted = tuple(m for m in messages if id(m) not in recent_set)
        compacted_refs = tuple(
            MessageRef(
                index=i,
                role=m.role,
                token_count=self._counter.count_text(m.content or ""),
            )
            for i, m in enumerate(messages)
            if id(m) not in recent_set
        )

        summary = self._summarizer(
            SummarizationInput(
                messages=compacted,
                previous_summary=request.previous_summary,
                reason=request.reason,
                session_id=request.session_id,
            )
        )
        summary = summary.model_copy(
            update={
                "summary_version": (
                    request.previous_summary.summary_version + 1
                    if request.previous_summary else 1
                ),
                "compacted_message_indices": tuple(r.index for r in compacted_refs),
            }
        )

        tokens_before = sum(
            self._counter.count_text(m.content or "") for m in messages
        )
        summary_tokens = self._measure_summary_tokens(summary)
        tokens_after = summary_tokens + recent_tokens

        return CompactionResult(
            summary=summary,
            reason=request.reason,
            compacted_refs=compacted_refs,
            retained_refs=recent_refs,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            summary_tokens=summary_tokens,
            recent_window_tokens=recent_tokens,
            recent_window_over_budget=over_budget,
        )

    @staticmethod
    def _fallback_summary(
        inp: SummarizationInput,
    ) -> ContextSummary:
        """deterministic 保底：消息降为 role 统计（无信息幻觉风险）。

        summary_version 占位为 1——compact() 随后必经 model_copy
        以 previous_summary 链重算版本，此值不进入结果。
        （缺陷修复：此前缺该必填字段，未注入 summarizer 时
        fallback 构造直接 ValidationError，默认压缩器不可用。）
        """
        role_counts: dict[str, int] = {}
        for m in inp.messages:
            role_counts[m.role] = role_counts.get(m.role, 0) + 1
        stats = "; ".join(f"{r}×{c}" for r, c in sorted(role_counts.items()))
        return ContextSummary(
            summary_version=1,
            task_goal=(inp.previous_summary.task_goal if inp.previous_summary else ""),
            confirmed_facts=(inp.previous_summary.confirmed_facts if inp.previous_summary else ()),
            unresolved_issues=(f"auto_compacted: {stats}",),
        )

    def _measure_summary_tokens(self, summary: ContextSummary) -> int:
        """用注入 counter 计量 Summary 全部文本字段（口径统一）。"""
        parts: list[str] = [summary.task_goal]
        for group in (
            summary.confirmed_facts,
            summary.decisions,
            summary.modified_files,
            summary.failed_attempts,
            summary.verification_state,
            summary.unresolved_issues,
            summary.next_actions,
        ):
            parts.extend(group)
        return sum(
            self._counter.count_text(part) for part in parts if part
        )