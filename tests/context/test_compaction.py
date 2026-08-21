"""W4D5：会话级 Context Compaction 测试（day5 §四十六 Context 矩阵）。

覆盖的不变量：
- Durable Session 与 Active Context 分离：compact 绝不删除 durable history
- under budget 不无意义 compact；over threshold 触发 compact
- Recent Window 按 token budget 装配（极大后缀），不是 keep_last_n
- Huge Tool Output 不把原始全文永久塞进 Active Context
- 结构化 working facts（goal/事实/决策/文件/失败尝试/验证态/下一步）
  在 compact 后保留，且连续压缩版本化、上一版可回溯（C3）
- compact 后仍超预算 → fits_budget=False（不得开始下一次 Model Turn 的信号）

工程约束：全 Fake（counter/summarizer），无网络、无 sleep、无 skip。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from codeteam.context.compaction import (
    CompactionReason,
    CompactionRequest,
    ContextCompactor,
    ContextSummary,
    SummarizationInput,
    build_recent_window,
    is_compaction_needed,
)
from codeteam.llm.registry import ModelMetadata, ModelSelection
from codeteam.schemas.messages import Message


class _CharCounter:
    """确定性计数器：1 字符 = 1 token（预算算术可精确断言）。"""

    def count_text(self, text: str) -> int:
        return len(text)


def _msg(role: str, content: str) -> Message:
    return Message(role=role, content=content)


def _selection() -> ModelSelection:
    return ModelSelection(provider_id="p", model_id="m")


def _request(
    *,
    target: int = 100,
    window: int = 1000,
    recent_budget: int = 40,
    previous: ContextSummary | None = None,
) -> CompactionRequest:
    return CompactionRequest(
        session_id="ses_t",
        reason=CompactionReason.AUTO_THRESHOLD,
        model_selection=_selection(),
        context_window_tokens=window,
        current_context_tokens=500,
        target_context_tokens=target,
        previous_summary=previous,
        recent_window_budget_tokens=recent_budget,
    )


def _metadata(window: int = 1000, max_output: int = 100) -> ModelMetadata:
    return ModelMetadata(
        provider_id="p",
        model_id="m",
        context_window_tokens=window,
        max_output_tokens=max_output,
    )


# ── 触发判定（under budget / over threshold）──────────────


class TestTriggerDecision:
    def test_under_budget_no_compaction_needed(self) -> None:
        """§四十六：Context under budget → 不应无意义 Compact。"""
        assert is_compaction_needed(current_tokens=100, target_tokens=500) is False

    def test_over_threshold_triggers_compaction(self) -> None:
        """§四十六：Context over threshold → 触发 Compact。"""
        assert is_compaction_needed(current_tokens=501, target_tokens=500) is True

    def test_boundary_equal_is_not_over(self) -> None:
        """等于阈值不算超出（严格大于才压）。"""
        assert is_compaction_needed(current_tokens=500, target_tokens=500) is False


# ── Durable 分离（结构性不变量）──────────────────────────


class TestDurableSeparation:
    def test_compact_never_mutates_input_messages(self) -> None:
        """Compact 只产出新材料，输入历史（durable 投影）原样保留。"""
        messages = tuple(
            _msg("user", f"message-{i} " + "x" * 30) for i in range(5)
        )
        before = [m.model_dump() for m in messages]
        result = ContextCompactor(_CharCounter()).compact(
            _request(), messages=messages
        )
        assert [m.model_dump() for m in messages] == before
        # 结果是引用清单（压了哪些/留了哪些），不是删除动作
        assert len(result.compacted_refs) + len(result.retained_refs) == 5

    def test_module_has_no_persistence_dependency(self) -> None:
        """架构级断言：compaction 不 import 任何持久化层——
        「不删 durable history」由依赖方向结构性保证，而非口头承诺。"""
        source = (
            Path(__file__).parents[2] / "codeteam" / "context" / "compaction.py"
        ).read_text(encoding="utf-8")
        assert "codeteam.session" not in source
        assert "codeteam.git" not in source


# ── Recent Window：按 token 装配，不是 keep_last_n ────────


class TestRecentWindow:
    def test_keeps_maximal_suffix_within_budget(self) -> None:
        """按 token 装配：从后往前装到预算尽为止。
        [a=10, b=60, c=10, d=10] 预算 25 → 保留 [c,d]（20 ≤ 25），
        再往左装 b(60) 会溢出 → 停。keep_last_n 固定条数，无此性质。"""
        messages = (
            _msg("user", "a" * 10),
            _msg("assistant", "b" * 60),
            _msg("user", "c" * 10),
            _msg("assistant", "d" * 10),
        )
        kept, refs, total, over = build_recent_window(
            messages, budget_tokens=25, counter=_CharCounter()
        )
        assert [m.content[0] for m in kept] == ["c", "d"]
        assert total == 20  # ≤ 预算，且是能装下的极大后缀
        assert over is False
        assert [r.index for r in refs] == [2, 3]

    def test_budget_adapts_to_message_sizes(self) -> None:
        """同样 4 条消息：预算 25 留 [c,d]，预算 90 留 [a,b,c,d]——
        保留集合由 token 决定，与消息条数无关。"""
        messages = (
            _msg("user", "a" * 10),
            _msg("assistant", "b" * 60),
            _msg("user", "c" * 10),
            _msg("assistant", "d" * 10),
        )
        kept90, _, total90, _ = build_recent_window(
            messages, budget_tokens=90, counter=_CharCounter()
        )
        assert len(kept90) == 4
        assert total90 == 90

    def test_window_preserves_time_order(self) -> None:
        kept, _, _, _ = build_recent_window(
            tuple(_msg("user", f"m{i}" * 5) for i in range(4)),
            budget_tokens=100,
            counter=_CharCounter(),
        )
        assert [m.content for m in kept] == [f"m{i}" * 5 for i in range(4)]

    def test_single_message_over_budget_still_kept_with_flag(self) -> None:
        """C4 防御：最后一条单条超预算仍保留（窗口不能空），
        但 over_budget 必须可观测。"""
        messages = (_msg("tool", "x" * 100),)
        kept, refs, total, over = build_recent_window(
            messages, budget_tokens=10, counter=_CharCounter()
        )
        assert len(kept) == 1
        assert total == 100
        assert over is True
        assert refs[0].token_count == 100

    def test_empty_messages_yield_empty_window(self) -> None:
        kept, refs, total, over = build_recent_window(
            (), budget_tokens=10, counter=_CharCounter()
        )
        assert kept == ()
        assert refs == ()
        assert total == 0
        assert over is False


# ── Huge Tool Output 不永久占位 ──────────────────────────


class TestHugeToolOutput:
    def test_huge_tool_output_not_in_recent_window(self) -> None:
        """巨大 tool 输出超出 recent 预算 → 被移入 compacted 段，
        Active Context 只留受控摘要（fallback：role 级统计）。"""
        messages = (
            _msg("user", "run tests"),
            _msg("tool", "LOG" * 500),   # 1500 tokens
            _msg("assistant", "analyzing"),
        )
        result = ContextCompactor(_CharCounter()).compact(
            _request(recent_budget=20), messages=messages
        )
        huge = next(r for r in result.compacted_refs if r.index == 1)
        assert huge.role == "tool"
        assert huge.token_count == 1500
        assert all(r.index != 1 for r in result.retained_refs)

    def test_fallback_summary_does_not_embed_raw_log(self) -> None:
        """fallback 摘要把消息降为 role 统计——原始全文不进 Summary，
        只留下可追溯的位置引用。"""
        raw = "SECRET-FRAGMENT-" * 100
        messages = (_msg("tool", raw), _msg("assistant", "ok"))
        result = ContextCompactor(_CharCounter()).compact(
            _request(recent_budget=5), messages=messages
        )
        rendered = " ".join(result.summary.unresolved_issues)
        assert "SECRET-FRAGMENT" not in rendered
        # 引用可回溯（audit trail 指向 durable history）
        assert 0 in result.summary.compacted_message_indices


# ── working facts 保留（结构化 Summary）──────────────────


class _ScriptedSummarizer:
    """注入式 summarizer：返回带全部要素的 Summary 并记录调用。"""

    def __init__(self) -> None:
        self.calls: list[SummarizationInput] = []

    def __call__(self, inp: SummarizationInput) -> ContextSummary:
        self.calls.append(inp)
        return ContextSummary(
            # summary_version 由 compactor 以版本链重算，此处占位
            summary_version=1,
            task_goal="修复登录超时",
            confirmed_facts=("timeout 在 transport/http.py",),
            decisions=("保留公开 API 不变",),
            modified_files=("src/auth/client.py",),
            failed_attempts=("test_login_timeout FAILED: TimeoutError",),
            verification_state=("target test 未跑",),
            unresolved_issues=("retry 策略未确认",),
            next_actions=("rerun test_login_timeout",),
        )


class TestWorkingFactsRetention:
    def test_fact_groups_survive_compaction(self) -> None:
        """6 要素中属于 Summary 职责的部分全部保留：
        失败尝试（earlier failed test）、当前文件、决策与下一步。
        （用户约束/plan/checkpoint 的权威重注入见 test_assembler.py）"""
        summarizer = _ScriptedSummarizer()
        result = ContextCompactor(
            _CharCounter(), summarizer=summarizer
        ).compact(
            _request(recent_budget=10),
            messages=tuple(_msg("user", f"turn-{i}" * 10) for i in range(6)),
        )
        s = result.summary
        assert s.task_goal == "修复登录超时"
        assert s.confirmed_facts == ("timeout 在 transport/http.py",)
        assert s.decisions == ("保留公开 API 不变",)
        assert s.modified_files == ("src/auth/client.py",)
        assert s.failed_attempts == (
            "test_login_timeout FAILED: TimeoutError",
        )
        assert s.verification_state == ("target test 未跑",)
        assert s.next_actions == ("rerun test_login_timeout",)

    def test_summarizer_receives_only_compacted_segment(self) -> None:
        """summarizer 拿到的是被压段，不含 recent window（职责分离）。"""
        summarizer = _ScriptedSummarizer()
        messages = (
            _msg("user", "old" * 10),
            _msg("assistant", "older" * 10),
            _msg("user", "recent-small"),
        )
        ContextCompactor(_CharCounter(), summarizer=summarizer).compact(
            _request(recent_budget=20), messages=messages
        )
        assert len(summarizer.calls) == 1
        sent = [m.content for m in summarizer.calls[0].messages]
        assert "recent-small" not in sent

    def test_previous_summary_version_chain(self) -> None:
        """C3 防御：连续压缩版本严格递增，上一版被传入 summarizer——
        Summary Drift 可回溯。"""
        previous = ContextSummary(
            summary_version=3,
            failed_attempts=("earlier failed test",),
        )
        summarizer = _ScriptedSummarizer()
        result = ContextCompactor(
            _CharCounter(), summarizer=summarizer
        ).compact(
            _request(previous=previous, recent_budget=10),
            messages=(_msg("user", "x" * 50),),
        )
        assert result.summary.summary_version == 4
        assert summarizer.calls[0].previous_summary is not None
        assert (
            summarizer.calls[0].previous_summary.failed_attempts
            == ("earlier failed test",)
        )

    def test_first_compaction_starts_at_version_1(self) -> None:
        result = ContextCompactor(_CharCounter()).compact(
            _request(recent_budget=10),
            messages=(_msg("user", "x" * 50),),
        )
        assert result.summary.summary_version == 1


# ── 计量与越界防御 ───────────────────────────────────────


class TestAccounting:
    def test_tokens_before_after_measured_consistently(self) -> None:
        messages = (
            _msg("user", "a" * 40),
            _msg("assistant", "b" * 30),
            _msg("user", "c" * 20),
        )
        result = ContextCompactor(_CharCounter()).compact(
            _request(recent_budget=25), messages=messages
        )
        assert result.tokens_before == 90
        assert result.tokens_after == (
            result.summary_tokens + result.recent_window_tokens
        )

    def test_target_must_be_below_window(self) -> None:
        """荒谬配置当场拒绝：target ≥ window 时压缩无意义。"""
        with pytest.raises(ValueError, match="target_context_tokens"):
            ContextCompactor(_CharCounter()).compact(
                _request(target=1000, window=1000),
                messages=(_msg("user", "x"),),
            )


# ── compact 后仍超预算 → 不得开始下一次 Model Turn ──────


class TestStillTooLargeAfterCompaction:
    def test_overflow_result_signals_no_next_turn(self) -> None:
        """压完仍放不下：summary + recent 重组 ActiveContext 后
        fits_budget=False——这是「不开始下一次 Model Turn」的生产
        信号（权威四段之外的段已全部裁尽仍超）。"""
        from codeteam.context.assembler import ContextAssembler
        from codeteam.planning.models import Plan, PlanStep, PlanStepStatus
        from codeteam.task.models import TaskSpec

        messages = (_msg("user", "x" * 400),)
        result = ContextCompactor(_CharCounter()).compact(
            _request(recent_budget=100), messages=messages
        )
        # 单条 400 超过 recent 预算 100：仍保留但必须可观测
        assert result.recent_window_over_budget is True

        task = TaskSpec(
            task_id="t",
            original_request="修复登录超时",
            goal="修复登录超时",
        )
        plan = Plan(
            plan_id="p1",
            task_id="t",
            version=1,
            steps=(PlanStep(
                step_id="s1", title="t", description="d",
                status=PlanStepStatus.PENDING,
            ),),
            goal="g",
        )
        # 小窗口模型：budget = 450 - 100 - 45 = 305 < 400
        active = ContextAssembler(_CharCounter()).assemble(
            task=task,
            plan=plan,
            checkpoint_id=None,
            summary=result.summary,
            recent_messages=messages,
            retrieved_code=(),
            repo_instructions=(),
            metadata=_metadata(window=450),
        )
        assert active.fits_budget is False
