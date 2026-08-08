"""
Token 预算模型：将上下文窗口划分成有名字的子预算。

设计原则：
  模型上下文窗口 ≠ 全部可用于输入
  需要预留输出、推理和安全余量

学习阶段默认使用 32K 窗口（远小于模型实际能力），
以便主动测试压缩逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TokenBudget:
    """分层的 Token 预算。

    用法：
        budget = TokenBudget(context_window=32000)
        # 各项子预算使用默认值
        print(budget.max_input_tokens)      # 24000
        print(budget.allocated_input_tokens) # 24000
    """

    # ── 窗口与预留 ─────────────────────────────────────────

    context_window: int = 32000
    """模型上下文窗口总 Token 数。"""

    reserved_output: int = 4096
    """预留的模型输出空间。"""

    reserved_reasoning: int = 2048
    """预留的推理（thinking）空间。"""

    safety_margin: int = 1856
    """安全余量，防止意外溢出。"""

    # ── 子预算 ──────────────────────────────────────────────

    system_budget: int = 1500
    """系统安全规则的 Token 配额（永不压缩）。"""

    tool_schema_budget: int = 2500
    """工具定义和 JSON Schema 的 Token 配额。"""

    task_budget: int = 1000
    """用户任务描述的 Token 配额。"""

    instruction_budget: int = 2000
    """项目指令（AGENTS.md + .clinerules）的 Token 配额。"""

    repo_map_budget: int = 3000
    """Repo Map 的 Token 配额。"""

    code_budget: int = 8000
    """具体源码的 Token 配额。"""

    history_budget: int = 3000
    """对话历史摘要的 Token 配额。"""

    observation_budget: int = 3000
    """最近工具执行结果的 Token 配额。"""

    # ── 计算属性 ────────────────────────────────────────────

    @property
    def max_input_tokens(self) -> int:
        """真正可用于输入的最大 Token 数。

        = 上下文窗口 - 输出预留 - 推理预留 - 安全余量
        """
        return (
            self.context_window
            - self.reserved_output
            - self.reserved_reasoning
            - self.safety_margin
        )

    @property
    def allocated_input_tokens(self) -> int:
        """所有子预算的分配总额。

        这个值不能超过 max_input_tokens。
        """
        return (
            self.system_budget
            + self.tool_schema_budget
            + self.task_budget
            + self.instruction_budget
            + self.repo_map_budget
            + self.code_budget
            + self.history_budget
            + self.observation_budget
        )

    # ── 校验 ────────────────────────────────────────────────

    def __post_init__(self) -> None:
        """创建后自动校验：子预算总额不能超过可用输入空间。

        Raises:
            ValueError: 如果分配超过可用输入预算
        """
        if self.allocated_input_tokens > self.max_input_tokens:
            raise ValueError(
                f"子预算总额 ({self.allocated_input_tokens}) "
                f"超过可用输入空间 ({self.max_input_tokens})。"
                f"请减少子预算或增大 context_window。"
            )

        # 检查单个预算不能为负
        budgets = [
            ("reserved_output", self.reserved_output),
            ("reserved_reasoning", self.reserved_reasoning),
            ("safety_margin", self.safety_margin),
            ("system_budget", self.system_budget),
            ("tool_schema_budget", self.tool_schema_budget),
            ("task_budget", self.task_budget),
            ("instruction_budget", self.instruction_budget),
            ("repo_map_budget", self.repo_map_budget),
            ("code_budget", self.code_budget),
            ("history_budget", self.history_budget),
            ("observation_budget", self.observation_budget),
        ]
        for name, value in budgets:
            if value < 0:
                raise ValueError(
                    f"{name} 不能为负数，当前值: {value}"
                )
