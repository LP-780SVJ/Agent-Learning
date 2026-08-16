"""
Planner 接口与确定性的 Mock 实现。

Planner 是 Decision / Planning Component：
只负责 TaskSpec + RepositoryContext → Plan。

它不负责（也从接口上杜绝了）：
apply patch、run tests、change worktree、create checkpoint。

分工：
- Unit / Integration 测试 → MockPlanner（确定性）
- Benchmark → 真实 LLMPlanner（Step 7 实现）
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from codeteam.planning.models import Plan, PlanStep, create_plan
from codeteam.task.models import TaskSpec


@dataclass
class RepositoryContext:
    """Planner 的仓库证据输入。

    注意：不是"把整个仓库塞给 LLM"——
    而是 Week 2 Context Engine 检索后的精选证据。

    用 dataclass 而非 BaseModel：
    这是内部流转数据（由我们自己的代码产生），
    不需要外部输入校验。
    """

    summary: str
    """仓库一句话总结。"""

    relevant_files: tuple[str, ...] = ()
    """检索到的相关文件路径。"""

    relevant_symbols: tuple[str, ...] = ()
    """相关符号名（如 "AuthService.refresh_access_token"）。"""

    instructions: tuple[str, ...] = ()
    """适用的项目规则（AGENTS.md / .clinerules）。"""

    test_commands: tuple[str, ...] = ()
    """检测到的测试/检查命令。"""


class Planner(Protocol):
    """计划生成器的接口契约。

    Protocol = 鸭子类型的正式化：
    任何有 create_plan 方法的对象都是 Planner，
    不需要显式继承。

    输入是 TaskSpec + RepositoryContext，
    输出是结构化的 Plan（Runtime source of truth）。
    """

    def create_plan(
        self,
        *,
        task: TaskSpec,
        repo_context: RepositoryContext,
    ) -> Plan:
        """根据任务和仓库证据生成执行计划。"""
        ...


@dataclass
class MockPlanner:
    """确定性 Planner：返回注入的固定 Plan。

    有意**不校验**注入的 Plan：
    测试需要故意注入非法 Plan（空 steps / 重复 ID）
    来验证 Runtime 的 validate_plan 闸门。
    """

    plan: Plan | None = None
    """每次调用都返回的固定 Plan。"""

    error: Exception | None = None
    """如果非 None，每次调用抛出该异常（模拟模型故障）。"""

    calls: list[tuple[str, str]] = field(default_factory=list)
    """审计记录：(task_id, plan_id) 的调用历史。"""

    def create_plan(
        self,
        *,
        task: TaskSpec,
        repo_context: RepositoryContext,
    ) -> Plan:
        """返回注入的 plan 或抛出注入的 error。"""
        self.calls.append((task.task_id, task.original_request))

        if self.error is not None:
            raise self.error

        if self.plan is None:
            raise RuntimeError(
                "MockPlanner 未注入 plan 也未注入 error"
            )

        return self.plan


@dataclass
class FailingPlanner:
    """总是抛出指定异常的 Planner。

    用于测试 Orchestrator 的失败路径：
    Planner 异常 → Task 必须 FAILED，绝不卡死在 PLANNING。
    """

    error: Exception
    calls: int = 0

    def create_plan(
        self,
        *,
        task: TaskSpec,
        repo_context: RepositoryContext,
    ) -> Plan:
        self.calls += 1
        raise self.error



class PlanParseError(Exception):
    """模型输出无法解析为合法 Plan 时抛出。

    与 InvalidStepTransitionError 同理：
    专用异常让调用方（Orchestrator 的失败分类）
    能精确识别"解析失败"这一类问题。
    """


def _build_planning_prompt(
    task: TaskSpec,
    repo_context: RepositoryContext,
) -> str:
    """构造 Planning Prompt。

    核心契约（对应 day1.md 第五十三节的 8 条规则）：
    1. 只基于提供的 Repository Evidence
    2. 不假设不存在的文件或 Symbol
    3. 步骤可执行
    4. 步骤大小适中（一个步骤 ≈ 一次有明确产物和验证的工作单元）
    5. 每步尽量包含验证方式
    6. 不要开始写代码
    7. 不确定的事实明确标记
    8. Plan 服务于 Goal 和 Constraints
    """
    lines: list[str] = []
    lines.append("你是一个 Coding Agent 的规划组件。")
    lines.append("")
    lines.append("## 任务")
    lines.append(f"Goal: {task.goal}")
    if task.constraints:
        lines.append("Constraints:")
        lines.extend(f"- {c}" for c in task.constraints)
    if task.acceptance_criteria:
        lines.append("Acceptance:")
        lines.extend(f"- {a}" for a in task.acceptance_criteria)
    lines.append("")
    lines.append("## 仓库证据（唯一事实来源）")
    lines.append(repo_context.summary)
    if repo_context.relevant_files:
        lines.append("相关文件:")
        lines.extend(f"- {f}" for f in repo_context.relevant_files)
    if repo_context.relevant_symbols:
        lines.append("相关符号:")
        lines.extend(f"- {s}" for s in repo_context.relevant_symbols)
    if repo_context.instructions:
        lines.append("项目规则:")
        lines.extend(f"- {i}" for i in repo_context.instructions)
    if repo_context.test_commands:
        lines.append("可用命令:")
        lines.extend(f"- {c}" for c in repo_context.test_commands)
    lines.append("")
    lines.append("## 输出要求")
    lines.append("只输出 JSON，不要输出解释文字。JSON 格式：")
    lines.append("{")
    lines.append('  "steps": [')
    lines.append("    {")
    lines.append('      "step_id": "P1",')
    lines.append('      "title": "简短标题",')
    lines.append('      "description": "这一步做什么的详细说明",')
    lines.append('      "relevant_files": ["src/a.py"],')
    lines.append('      "verification": "如何验证（可为 null）"')
    lines.append("    }")
    lines.append("  ]")
    lines.append("}")
    return "\n".join(lines)


def _strip_code_fences(text: str) -> str:
    """剥掉模型输出可能的 ```json 围栏。只剥围栏，不修内容。"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


class LLMPlanner:
    """真实模型驱动的 Planner。

    依赖注入一个 complete 函数（prompt -> 文本），
    不绑定任何具体模型客户端。

    用法：
        planner = LLMPlanner(
            complete=lambda prompt: client.complete(
                [Message(role="user", content=prompt)]
            )
        )
        plan = planner.create_plan(task=spec, repo_context=ctx)

    Raises:
        PlanParseError: 模型输出无法解析为合法 Plan。
        其他 Pydantic ValidationError / ValueError 也会传播——
        由 Orchestrator 总闸门统一转成 Task FAILED。
    """

    def __init__(self, complete: Callable[[str], str]) -> None:
        self._complete = complete

    def create_plan(
        self,
        *,
        task: TaskSpec,
        repo_context: RepositoryContext,
    ) -> Plan:
        """生成结构化 Plan。

        流程：构造 prompt → 调模型 → 剥围栏 → 解析 JSON
        → 构造 PlanStep（字段校验）→ create_plan（结构校验）。
        """
        prompt = _build_planning_prompt(task, repo_context)

        raw = self._complete(prompt)

        text = _strip_code_fences(raw)

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PlanParseError(
                f"模型输出不是合法 JSON: {exc}"
            ) from exc

        if not isinstance(data, dict) or "steps" not in data:
            raise PlanParseError(
                "模型输出缺少 steps 字段"
            )

        steps = tuple(
            PlanStep.model_validate(item)
            for item in data["steps"]
        )

        return create_plan(
            plan_id=f"{task.task_id}-plan-v1",
            task_id=task.task_id,
            steps=steps,
        )