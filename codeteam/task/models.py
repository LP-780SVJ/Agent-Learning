"""
TaskSpec：用户自然语言任务的结构化表示。

把"用户的一句话"从聊天 Prompt 升级成 Runtime 可以管理的 Task：
- original_request  用户原话（永不改写，用于 Failure Analysis 对照）
- goal              最终希望改变什么（不是实现方式）
- constraints       完成 Goal 过程中不能违反什么（Solution Space Boundary）
- acceptance        怎么证明 Goal 已完成（Observable + Verifiable）

goal 的初值等于 original_request：
Day 1 还没有 TaskNormalizer，goal 的细化交给 Planner（Step 4+）；
但 original_request 永远保存用户原话，即使 goal 被改写也能回溯。
"""
from __future__ import annotations

from pydantic import BaseModel, field_validator


class TaskSpec(BaseModel):
    """一个用户任务的规格说明。"""

    task_id: str
    """任务稳定标识，如 "task-001"。Event / Benchmark 都引用它。"""

    original_request: str
    """用户原话，永不改写。"""

    goal: str
    """任务最终希望改变什么。注意：不是实现方式。

    错误示例：goal="修改 login.py"
    正确示例：goal="登录请求在后端响应延迟时能按 timeout/retry 策略
              正确处理，而不是提前失败"
    """

    constraints: tuple[str, ...] = ()
    """完成 Goal 过程中不能违反的限制。

    例如："不能修改公开 API"、"不能添加新的第三方依赖"。
    用 tuple 而非 list：约束是事实声明，不应被悄悄原地修改。
    """

    acceptance_criteria: tuple[str, ...] = ()
    """可观察、可验证的完成标准。

    例如："pytest tests/auth/test_timeout.py 返回 0"。
    """

    # ── 校验：坏数据在构造时就拒绝 ────────────────────────────

    @field_validator("task_id", "original_request", "goal")
    @classmethod
    def _check_not_blank(cls, value: str) -> str:
        """task_id / original_request / goal 都必须是非空字符串。

        同时自动 strip 首尾空白。
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("字段不能为空或纯空白")
        return stripped


def create_task_spec(
    *,
    task_id: str,
    original_request: str,
) -> TaskSpec:
    """从用户自然语言请求创建初始 TaskSpec。

    Day 1 版本：goal 初值 = 原话（尚未细化）；
    constraints / acceptance 留空，后续由用户明确约束
    和 Repository Inspection 的验证候选逐步补充。

    Args:
        task_id: 任务标识。
        original_request: 用户原话。

    Returns:
        TaskSpec。空输入会直接抛 ValidationError，不会到达 LLM。

    Raises:
        pydantic.ValidationError: original_request 为空或纯空白。
    """
    return TaskSpec(
        task_id=task_id,
        original_request=original_request,
        goal=original_request,  # 初值：尚未细化
    )