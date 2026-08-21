"""codeteam.context.assembler — 每 Turn 的 Active Context 组装器。

与 compaction.py 的分工（day5 §四十三）：
- ContextCompactor：压缩历史（产出 Summary + Recent Window 材料）
- ContextAssembler：决定下一次真正发送什么（本文件）
两者不合成一个 God Object。

三级权威（§八）：
- Authoritative（SYSTEM/RULES/TASK/PLAN）：从 Durable State 重注入，
  永不依赖 Summary —— C1（约束丢失）的结构性防御
- Durable Derived（SUMMARY）：Step 2 的结构化 Working Memory
- Ephemeral（RECENT/CODE）：Recent Window + 当前检索

本模块纯组装：不碰 IO（Store/InstructionLoader 由调用方），
不删任何历史（Invariant 与 compaction 同源）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel

from codeteam.context.compaction import ContextSummary
from codeteam.llm.registry import (
    ModelMetadata,
    ModelSelection,
    compute_context_budget,
)
from codeteam.planning.models import Plan, PlanStepStatus
from codeteam.schemas.messages import Message
from codeteam.task.models import TaskSpec
from codeteam.usage.token_counter import TokenCounter


class ContextSection(str, Enum):
    SYSTEM = "system"
    RULES = "rules"
    TASK = "task"
    PLAN = "plan"
    SUMMARY = "summary"
    RECENT = "recent"
    CODE = "code"


class ContextStaleError(Exception):
    """context.json 与 session.json 版本错位（崩溃残留/调用方 bug）。

    携带 expected/actual，调用方据此 rebuild 而非 fail Session
    （day4 §九十四）。
    """

    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"context stale: expected summary_version={expected}, "
            f"actual={actual}"
        )


@dataclass(frozen=True)
class AssembledSection:
    section_type: ContextSection
    content: str
    token_count: int


@dataclass(frozen=True)
class ActiveContext:
    """一次 Model Call 的工作集快照（ephemeral，绝不落盘）。"""

    sections: tuple[AssembledSection, ...]
    total_tokens: int
    budget_tokens: int
    fits_budget: bool
    selection: ModelSelection | None
    assembled_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def section(self, kind: ContextSection) -> AssembledSection | None:
        for s in self.sections:
            if s.section_type is kind:
                return s
        return None


class ContextAssembler:
    """组装顺序 = 权威层级：SYSTEM → RULES → TASK → PLAN → SUMMARY
    → RECENT → CODE。超预算从尾部裁剪（CODE 先于 RECENT 先于
    SUMMARY），头部四段永不裁。"""

    _RENDER_ORDER: tuple[ContextSection, ...] = (
        ContextSection.SYSTEM, ContextSection.RULES, ContextSection.TASK,
        ContextSection.PLAN, ContextSection.SUMMARY,
        ContextSection.RECENT, ContextSection.CODE,
    )

    def __init__(
        self,
        counter: TokenCounter,
        *,
        system_rules: tuple[str, ...] = (),
    ) -> None:
        self._counter = counter
        self._system_rules = system_rules

    # ── STALE 检查 ──────────────────────────────────────

    @staticmethod
    def check_stale(
        session_expected: int | None,
        context_actual: int | None,
    ) -> None:
        """版本对齐检查。错位抛 ContextStaleError；None 表示
        任一侧尚未初始化——视为 fresh（首次组装的合法状态）。"""
        if (
            session_expected is not None
            and context_actual is not None
            and session_expected != context_actual
        ):
            raise ContextStaleError(session_expected, context_actual)

    # ── 组装 ────────────────────────────────────────────

    def assemble(
        self,
        *,
        task: TaskSpec,
        plan: Plan | None,
        checkpoint_id: str | None,
        summary: ContextSummary | None,
        recent_messages: tuple[Message, ...],
        retrieved_code: tuple[str, ...],
        repo_instructions: tuple[str, ...],
        metadata: ModelMetadata,
        selection: ModelSelection | None = None,
        fixed_overheads_tokens: int = 0,
    ) -> ActiveContext:
        budget = compute_context_budget(
            metadata,
            fixed_overheads_tokens=fixed_overheads_tokens,
        )

        sections: list[AssembledSection] = []
        self._add(sections, ContextSection.SYSTEM, "\n".join(self._system_rules) or None)
        self._add(sections, ContextSection.RULES,
                  "\n".join(repo_instructions) or None)
        self._add(sections, ContextSection.TASK, self._render_task(task))
        self._add(sections, ContextSection.PLAN,
                  self._render_plan(plan, checkpoint_id) if plan else None)
        self._add(sections, ContextSection.SUMMARY,
                  self._render_summary(summary) if summary else None)
        self._add(sections, ContextSection.RECENT,
                  self._render_recent(recent_messages) or None)
        self._add(sections, ContextSection.CODE,
                  "\n".join(retrieved_code) or None)

        # 超预算：从尾部裁剪（CODE → RECENT → SUMMARY），头部四段永不裁
        while self._total(sections) > budget and len(sections) > 4:
            sections.pop()

        total = self._total(sections)
        return ActiveContext(
            sections=tuple(sections),
            total_tokens=total,
            budget_tokens=budget,
            fits_budget=(total <= budget),
            selection=selection,
        )

    # ── 渲染器（Authoritative 段的结构化文本）───────────

    def _render_task(self, task: TaskSpec) -> str:
        lines = [f"Task {task.task_id}: {task.goal}"]
        if task.constraints:
            lines.append("Constraints (authoritative, 永不依赖摘要):")
            lines += [f"- {c}" for c in task.constraints]
        if task.acceptance_criteria:
            lines.append("Acceptance:")
            lines += [f"- {a}" for a in task.acceptance_criteria]
        return "\n".join(lines)

    def _render_plan(self, plan: Plan, checkpoint_id: str | None) -> str:
        """Plan 状态从 Session.plan 权威渲染——Summary 无权决定 P3 状态（§十一）。"""
        lines = [f"Plan {plan.plan_id} v{plan.version}:"]
        for step in plan.steps:
            marker = {
                PlanStepStatus.PENDING: "○",
                PlanStepStatus.RUNNING: "→",
                PlanStepStatus.COMPLETED: "✓",
                PlanStepStatus.FAILED: "✗",
                PlanStepStatus.SKIPPED: "-",
            }[step.status]
            lines.append(f"{marker} {step.step_id} {step.title}")
        if checkpoint_id:
            lines.append(f"Checkpoint: {checkpoint_id}")
        return "\n".join(lines)

    def _render_summary(self, summary: ContextSummary) -> str:
        lines = [f"[Working Memory v{summary.summary_version}]"]
        if summary.task_goal:
            lines.append(f"Goal: {summary.task_goal}")
        for label, items in (
            ("Confirmed", summary.confirmed_facts),
            ("Decisions", summary.decisions),
            ("Modified files", summary.modified_files),
            ("Failed attempts", summary.failed_attempts),
            ("Verification", summary.verification_state),
            ("Unresolved", summary.unresolved_issues),
            ("Next", summary.next_actions),
        ):
            if items:
                lines.append(f"{label}:")
                lines += [f"- {i}" for i in items]
        return "\n".join(lines)

    def _render_recent(self, messages: tuple[Message, ...]) -> str:
        return "\n".join(
            f"[{m.role}] {m.content or ''}" for m in messages
        )

    # ── 工具 ────────────────────────────────────────────

    def _add(
        self,
        sections: list[AssembledSection],
        kind: ContextSection,
        content: str | None,
    ) -> None:
        if not content:
            return
        sections.append(AssembledSection(
            section_type=kind,
            content=content,
            token_count=self._counter.count_text(content),
        ))

    def _total(self, sections: list[AssembledSection]) -> int:
        return sum(s.token_count for s in sections)

    def to_messages(self, active: ActiveContext) -> list[Message]:
        """ActiveContext → ModelClient 消息序列（单 system + 单 user 合成）。

        MVP 渲染策略：全段合并为一条 system（权威在前）+ 近期消息
        保持原 role 结构追加——真实多消息布局留 Day 6 CLI 调优。
        """
        rendered = "\n\n".join(s.content for s in active.sections)
        messages = [Message(role="system", content=rendered)]
        # RECENT 段已并入 system 渲染时不重复；此处预留逐条保真路径：
        return messages