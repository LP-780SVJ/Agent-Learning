"""W4D5：Active Context 组装器测试（day5 §八/§四十六 Context 矩阵）。

覆盖的不变量：
- ActiveContext 不只依赖 summary：System Rules / Repository Rules /
  TaskSpec（用户约束）/ Active Plan / Current Checkpoint 每次从
  authoritative sources 重新注入（C1 结构性防御）
- Plan 状态以 Session.plan 为权威（Summary 无权决定 P3 状态）
- Token Budget 基于 ModelMetadata（window − max_output − headroom），
  不是固定常量；不同模型 → 不同预算
- 超预算从尾部裁剪（CODE → RECENT → SUMMARY），权威四段永不裁
- 权威四段本身超预算 → fits_budget=False（不开下一 Turn 的信号）
- CONTEXT_STALE：版本错位抛 ContextStaleError → rebuild 而非 fail
- 组装是纯函数：同样材料两次组装结果一致（可幂等 rebuild）

工程约束：全 Fake counter，无 IO、无网络、无 skip。
"""
from __future__ import annotations

import pytest

from codeteam.context.assembler import (
    ActiveContext,
    ContextAssembler,
    ContextSection,
    ContextStaleError,
)
from codeteam.context.compaction import ContextSummary
from codeteam.llm.registry import ModelMetadata, ModelSelection
from codeteam.planning.models import Plan, PlanStep, PlanStepStatus
from codeteam.schemas.messages import Message
from codeteam.task.models import TaskSpec


class _CharCounter:
    """确定性计数器：1 字符 = 1 token。"""

    def count_text(self, text: str) -> int:
        return len(text)


def _task(constraints: tuple[str, ...] = ("不能修改公开 API",)) -> TaskSpec:
    return TaskSpec(
        task_id="t-1",
        original_request="修复登录超时问题",
        goal="登录超时被正确处理",
        constraints=constraints,
        acceptance_criteria=("pytest tests/auth -q 全绿",),
    )


def _plan(
    s1: PlanStepStatus = PlanStepStatus.PENDING,
) -> Plan:
    return Plan(
        plan_id="p1",
        task_id="t-1",
        version=2,
        steps=(
            PlanStep(
                step_id="s1", title="定位 timeout", description="d",
                status=s1,
            ),
            PlanStep(
                step_id="s2", title="补回归测试", description="d",
                status=PlanStepStatus.PENDING,
            ),
        ),
        goal="g",
    )


def _metadata(window: int = 1000, max_output: int = 100) -> ModelMetadata:
    return ModelMetadata(
        provider_id="p",
        model_id="m",
        context_window_tokens=window,
        max_output_tokens=max_output,
    )


def _summary(**updates) -> ContextSummary:
    base = {
        "summary_version": 2,
        "task_goal": "修复登录超时",
        "failed_attempts": ("test_login_timeout FAILED: TimeoutError",),
        "modified_files": ("src/auth/client.py",),
    }
    base.update(updates)
    return ContextSummary(**base)


def _assemble(
    assembler: ContextAssembler,
    *,
    task: TaskSpec | None = None,
    plan: Plan | None = None,
    checkpoint_id: str | None = "cp-003",
    summary: ContextSummary | None = None,
    recent: tuple[Message, ...] = (),
    code: tuple[str, ...] = (),
    repo_instructions: tuple[str, ...] = ("遵循 AGENTS.md",),
    metadata: ModelMetadata | None = None,
) -> ActiveContext:
    return assembler.assemble(
        task=task or _task(),
        plan=plan if plan is not None else _plan(),
        checkpoint_id=checkpoint_id,
        summary=summary,
        recent_messages=recent,
        retrieved_code=code,
        repo_instructions=repo_instructions,
        metadata=metadata or _metadata(),
        selection=ModelSelection(provider_id="p", model_id="m"),
    )


# ── 权威重注入（summary 不是权威来源）────────────────────


class TestAuthoritativeReinjection:
    def test_user_constraint_survives_even_if_summary_omits_it(self) -> None:
        """§四十六第 1 行：用户约束在很早的 Turn，Compact 后仍在
        Active Context——约束从 TaskSpec 重注入，Summary 只负责
        「过去发生了什么」，漏掉约束也不影响权威段。"""
        assembler = ContextAssembler(
            _CharCounter(), system_rules=("Never destroy git history",)
        )
        summary_without_constraint = _summary(
            confirmed_facts=("讨论了很多登录的事情",),  # 故意不含约束
        )
        active = _assemble(
            assembler,
            summary=summary_without_constraint,
            recent=(Message(role="user", content="continue"),),
        )
        task_section = active.section(ContextSection.TASK)
        assert task_section is not None
        assert "不能修改公开 API" in task_section.content
        system_section = active.section(ContextSection.SYSTEM)
        assert system_section is not None
        assert "Never destroy git history" in system_section.content

    def test_repo_rules_reinjected_every_turn(self) -> None:
        """Repository Rules 每次组装重新注入（不靠 Summary 记忆）。"""
        active = _assemble(
            ContextAssembler(_CharCounter()),
            summary=_summary(),  # Summary 完全不含 repo rules
        )
        rules = active.section(ContextSection.RULES)
        assert rules is not None
        assert "遵循 AGENTS.md" in rules.content

    def test_plan_status_comes_from_session_plan_not_summary(self) -> None:
        """§四十六：Unfinished step 在 Plan 中仍保持 PENDING——
        即使 Summary 的 next_actions 声称已完成（Summary 幻觉 C2
        不能污染权威状态）。"""
        assembler = ContextAssembler(_CharCounter())
        lying_summary = _summary(
            next_actions=("s1 已完成",),  # Summary 谎称 s1 done
        )
        active = _assemble(
            assembler,
            plan=_plan(s1=PlanStepStatus.PENDING),  # Session 权威：PENDING
            summary=lying_summary,
        )
        plan_section = active.section(ContextSection.PLAN)
        assert plan_section is not None
        assert "○ s1" in plan_section.content   # ○ = PENDING
        assert "✓ s1" not in plan_section.content

    def test_checkpoint_reinjected_in_plan_section(self) -> None:
        """Current Checkpoint 从 Session 重注入（可回滚的锚点不丢）。"""
        active = _assemble(
            ContextAssembler(_CharCounter()), checkpoint_id="cp-003"
        )
        plan_section = active.section(ContextSection.PLAN)
        assert plan_section is not None
        assert "Checkpoint: cp-003" in plan_section.content

    def test_failed_test_kept_via_summary_section(self) -> None:
        """earlier failed test 属于 Working Memory → Summary 段保留。"""
        active = _assemble(
            ContextAssembler(_CharCounter()), summary=_summary()
        )
        summary_section = active.section(ContextSection.SUMMARY)
        assert summary_section is not None
        assert "test_login_timeout FAILED" in summary_section.content

    def test_current_file_kept_via_recent_section(self) -> None:
        """current file 经 Recent Window 保留（不进 Summary 也能看到）。"""
        active = _assemble(
            ContextAssembler(_CharCounter()),
            summary=None,
            recent=(Message(role="assistant", content="editing src/auth/client.py"),),
        )
        recent_section = active.section(ContextSection.RECENT)
        assert recent_section is not None
        assert "src/auth/client.py" in recent_section.content


# ── 分层顺序：权威在前 ───────────────────────────────────


class TestSectionOrder:
    def test_authoritative_sections_precede_derived(self) -> None:
        """渲染顺序 = 权威层级：SYSTEM → RULES → TASK → PLAN →
        SUMMARY → RECENT → CODE（截断时牺牲尾部，保护头部）。"""
        active = _assemble(
            ContextAssembler(
                _CharCounter(), system_rules=("sys",)
            ),
            summary=_summary(),
            recent=(Message(role="user", content="hi"),),
            code=("def foo(): ...",),
        )
        kinds = [s.section_type for s in active.sections]
        order = {kind: i for i, kind in enumerate(kinds)}
        assert order[ContextSection.SYSTEM] < order[ContextSection.RULES]
        assert order[ContextSection.RULES] < order[ContextSection.TASK]
        assert order[ContextSection.TASK] < order[ContextSection.PLAN]
        assert order[ContextSection.PLAN] < order[ContextSection.SUMMARY]
        assert order[ContextSection.SUMMARY] < order[ContextSection.RECENT]
        assert order[ContextSection.RECENT] < order[ContextSection.CODE]


# ── Budget 基于 ModelMetadata ────────────────────────────


class TestBudgetFromMetadata:
    def test_budget_formula_window_minus_output_minus_headroom(self) -> None:
        """budget = 1000 − 100(max_output) − 100(10% headroom) = 800。
        预算是推导值，不是固定常量。"""
        active = _assemble(
            ContextAssembler(_CharCounter()), metadata=_metadata()
        )
        assert active.budget_tokens == 800

    def test_different_models_get_different_budgets(self) -> None:
        """同名模型经不同部署（window 不同）→ 预算不同（C5：window
        属于部署而非模型名）。"""
        assembler = ContextAssembler(_CharCounter())
        big = _assemble(assembler, metadata=_metadata(window=10_000))
        small = _assemble(assembler, metadata=_metadata(window=500))
        assert big.budget_tokens == 10_000 - 100 - 1_000
        assert small.budget_tokens == 500 - 100 - 50
        assert big.budget_tokens != small.budget_tokens

    def test_fixed_overheads_shrink_budget(self) -> None:
        """本 Turn 已知固定开销（tools schema 等）先扣除再装配。"""
        active = ContextAssembler(_CharCounter()).assemble(
            task=_task(),
            plan=None,
            checkpoint_id=None,
            summary=None,
            recent_messages=(),
            retrieved_code=(),
            repo_instructions=(),
            metadata=_metadata(),
            fixed_overheads_tokens=200,
        )
        assert active.budget_tokens == 800 - 200

    def test_headroom_leaves_margin_below_window(self) -> None:
        """§十六：预算必须显著小于 window——为输出与 Tool Result
        增长留空间，在 Provider 报 overflow 之前自我管理。"""
        active = _assemble(ContextAssembler(_CharCounter()))
        assert active.budget_tokens < 1000 - 100  # window − max_output


# ── 超预算裁剪：尾部牺牲，头部永裁 ───────────────────────


class TestOverBudgetTrimming:
    def test_code_trimmed_before_recent_before_summary(self) -> None:
        """预算容下权威四段 + SUMMARY：CODE 与 RECENT 依次被裁，
        SUMMARY 保留；权威四段全程在场。"""
        assembler = ContextAssembler(
            _CharCounter(),
            system_rules=("sys-rule",),
        )
        # budget = 450 - 25 - 45 = 380：权威四段+SUMMARY（约 200）装得下，
        # 再加 RECENT(300) 装不下 → CODE、RECENT 依次被裁。
        active = assembler.assemble(
            task=_task(),
            plan=_plan(),
            checkpoint_id="cp-1",
            summary=_summary(),
            recent_messages=(
                Message(role="user", content="r" * 300),
            ),
            retrieved_code=("code " * 100,),
            repo_instructions=("rules",),
            metadata=_metadata(window=450, max_output=25),
        )
        kinds = {s.section_type for s in active.sections}
        assert ContextSection.CODE not in kinds       # 最先裁
        assert ContextSection.RECENT not in kinds     # 其次
        assert ContextSection.SUMMARY in kinds        # 保留
        assert ContextSection.TASK in kinds           # 权威四段永在场
        assert ContextSection.PLAN in kinds
        assert active.fits_budget is True

    def test_authoritative_four_never_trimmed_even_over_budget(self) -> None:
        """权威四段本身超预算 → 不再裁剪，fits_budget=False——
        这是「不开始下一次 Model Turn」的信号，而不是砍掉约束
        （砍约束 = C1 事故）。"""
        assembler = ContextAssembler(
            _CharCounter(), system_rules=("s" * 400,)
        )
        active = assembler.assemble(
            task=_task(),
            plan=_plan(),
            checkpoint_id="cp-1",
            summary=_summary(),
            recent_messages=(Message(role="user", content="x" * 500),),
            retrieved_code=("y" * 500,),
            repo_instructions=("r" * 300,),
            metadata=_metadata(window=200, max_output=20),  # budget=160
        )
        kinds = [s.section_type for s in active.sections]
        assert kinds == [
            ContextSection.SYSTEM, ContextSection.RULES,
            ContextSection.TASK, ContextSection.PLAN,
        ]  # 尾部三段裁尽后停手
        assert active.fits_budget is False

    def test_empty_materials_skip_sections(self) -> None:
        """无 plan/summary/recent 时对应段不出现（不是空段占位）。"""
        active = ContextAssembler(_CharCounter()).assemble(
            task=_task(),
            plan=None,
            checkpoint_id=None,
            summary=None,
            recent_messages=(),
            retrieved_code=(),
            repo_instructions=(),
            metadata=_metadata(),
        )
        kinds = {s.section_type for s in active.sections}
        assert kinds == {ContextSection.TASK}


# ── CONTEXT_STALE：错位 → rebuild，不是 fail ─────────────


class TestContextStale:
    def test_version_mismatch_raises_stale_error(self) -> None:
        with pytest.raises(ContextStaleError) as excinfo:
            ContextAssembler.check_stale(
                session_expected=5, context_actual=3
            )
        assert excinfo.value.expected == 5
        assert excinfo.value.actual == 3

    def test_aligned_versions_pass(self) -> None:
        ContextAssembler.check_stale(session_expected=7, context_actual=7)

    def test_uninitialized_sides_treated_as_fresh(self) -> None:
        """首次组装（任一侧 None）是合法状态，不算 stale。"""
        ContextAssembler.check_stale(session_expected=None, context_actual=3)
        ContextAssembler.check_stale(session_expected=5, context_actual=None)
        ContextAssembler.check_stale(
            session_expected=None, context_actual=None
        )

    def test_stale_context_is_rebuildable_not_fatal(self) -> None:
        """CONTEXT_STALE 的恢复语义 = 丢弃派生 context、用权威材料
        重新组装（rebuild），Session 不失败。组装是纯函数：
        同样材料重组两次结果一致 → rebuild 幂等。"""
        assembler = ContextAssembler(_CharCounter())
        materials = {
            "task": _task(),
            "plan": _plan(),
            "checkpoint_id": "cp-1",
            "summary": _summary(),
            "recent_messages": (Message(role="user", content="hi"),),
            "retrieved_code": ("code",),
            "repo_instructions": ("rules",),
            "metadata": _metadata(),
        }
        try:
            ContextAssembler.check_stale(session_expected=2, context_actual=1)
        except ContextStaleError:
            pass  # stale 检测到 → 丢弃旧派生状态，走 rebuild
        first = assembler.assemble(**materials)
        second = assembler.assemble(**materials)
        assert [s.content for s in first.sections] == [
            s.content for s in second.sections
        ]
        assert first.total_tokens == second.total_tokens


# ── to_messages：ActiveContext → Model 输入 ──────────────


class TestToMessages:
    def test_renders_single_system_message_with_authoritative_first(self):
        """MVP 渲染：全段合并单 system 消息，权威段在前。"""
        assembler = ContextAssembler(
            _CharCounter(), system_rules=("SYS-RULE",)
        )
        active = _assemble(
            assembler,
            summary=_summary(),
            recent=(Message(role="user", content="RECENT-MARK"),),
        )
        messages = assembler.to_messages(active)
        assert len(messages) == 1
        assert messages[0].role == "system"
        content = messages[0].content or ""
        assert "SYS-RULE" in content
        assert "不能修改公开 API" in content
        assert "RECENT-MARK" in content
        # 权威在前：约束出现在 recent 标记之前
        assert content.index("不能修改公开 API") < content.index("RECENT-MARK")
