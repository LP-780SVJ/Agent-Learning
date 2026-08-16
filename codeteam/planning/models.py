"""
Planning 数据模型：PlanStepStatus 与步骤状态机。

Step 3 会在本文件继续添加 PlanStep / Plan。
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class PlanStepStatus(str, Enum):
    """单个 PlanStep 的执行状态。

    禁止 PENDING → COMPLETED 直跳：
    必须先 PENDING → RUNNING → COMPLETED，
    强制记录"开始执行"这个事实，方便审计。
    """
    PENDING = "pending"      # 尚未开始
    RUNNING = "running"      # 正在执行
    COMPLETED = "completed"  # 已完成（Terminal）
    FAILED = "failed"        # 已失败（Terminal）
    SKIPPED = "skipped"      # 已跳过（Terminal）


# 合法转移表
STEP_TRANSITIONS: dict[PlanStepStatus, tuple[PlanStepStatus, ...]] = {
    PlanStepStatus.PENDING: (
        PlanStepStatus.RUNNING,
        PlanStepStatus.SKIPPED,
        PlanStepStatus.FAILED,
    ),
    PlanStepStatus.RUNNING: (
        PlanStepStatus.COMPLETED,
        PlanStepStatus.FAILED,
    ),
    PlanStepStatus.COMPLETED: (),
    PlanStepStatus.FAILED: (),
    PlanStepStatus.SKIPPED: (),
}


class InvalidStepTransitionError(Exception):
    """PlanStep 状态转移非法时抛出。"""


class PlanStep(BaseModel):
    """计划中的一个工作单元。

    一个 PlanStep 不是一次 Tool Call——
    它是一次"有明确产物和验证方式的工作单元"，
    内部可能包含多个 Tool Call（read_file + rg + ...）。

    例如：
        PlanStep(
            step_id="P1",
            title="Trace timeout flow",
            description="Inspect LoginService and HTTP client "
                        "to locate timeout configuration.",
            relevant_files=("src/auth/login_service.py",),
            verification="确认 timeout 参数的配置来源",
        )
    """

    step_id: str
    title: str
    description: str

    status: PlanStepStatus = PlanStepStatus.PENDING

    relevant_files: tuple[str, ...] = ()
    """相关文件提示。是当前证据快照，不是硬白名单。"""

    verification: str | None = None
    """怎么证明这一步完成（如 'pytest tests/auth/test_timeout.py'）。
    没有天然验证命令的步骤可以为 None。"""

    # ── 校验 ──────────────────────────────────────────────

    @field_validator("step_id", "title", "description")
    @classmethod
    def _check_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("字段不能为空或纯空白")
        return stripped

    # ── 状态转移（复用 Step 1 的 STEP_TRANSITIONS）───────────

    def transition_to(self, new_status: PlanStepStatus) -> None:
        """推进本步骤状态。唯一合法的状态修改入口。

        Raises:
            InvalidStepTransitionError: 非法转移（含 PENDING→COMPLETED 直跳），
                或 new_status 不是 PlanStepStatus 枚举成员（如裸字符串）。
        """
        # 类型守卫：PlanStepStatus 是 str-Enum，裸字符串会绕过
        # 成员检查（'pending' == PlanStepStatus.PENDING），必须显式拦截。
        if not isinstance(new_status, PlanStepStatus):
            raise InvalidStepTransitionError(
                f"目标状态必须是 PlanStepStatus 枚举成员，"
                f"收到 {type(new_status).__name__}: {new_status!r}"
            )

        legal = STEP_TRANSITIONS[self.status]
        if new_status not in legal:
            raise InvalidStepTransitionError(
                f"非法 Step 转移: {self.status.value} "
                f"→ {new_status.value}。"
                f"允许的目标: {[s.value for s in legal]}"
            )
        self.status = new_status


class Plan(BaseModel):
    """一份完整执行计划。

    steps 用 tuple 存储：序列创建后不可替换。
    要改变方向 → replan() 生成 version+1 的新 Plan。
    """

    plan_id: str
    task_id: str
    version: int = 1

    steps: tuple[PlanStep, ...]
    """执行步骤序列。非空、ID 唯一、创建时全部 PENDING。"""

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # ── 整体状态查询 ──────────────────────────────────────

    @property
    def is_complete(self) -> bool:
        """所有步骤都已 COMPLETED 或 SKIPPED。

        注意：对空 steps 返回 True，所以必须配合
        validate_plan 保证 steps 非空。
        """
        return all(
            s.status in (
                PlanStepStatus.COMPLETED,
                PlanStepStatus.SKIPPED,
            )
            for s in self.steps
        )

    @property
    def has_failed_step(self) -> bool:
        """是否存在 FAILED 的步骤。"""
        return any(
            s.status == PlanStepStatus.FAILED
            for s in self.steps
        )


def validate_plan(plan: Plan) -> list[str]:
    """校验 Plan 的 Runtime 不变量。返回问题列表，空列表 = 通过。

    模型可能返回 steps=[]、重复 ID、非法初始状态——
    Runtime 不能"模型返回什么就接受什么"。

    检查项：
    1. 至少 1 个 step
    2. step_id 唯一
    3. 每个 step 的当前状态是合法枚举值（构造时已保证，防御性检查）
    """
    problems: list[str] = []

    if not plan.steps:
        problems.append("Plan 至少需要 1 个 Step")
        return problems

    ids = [s.step_id for s in plan.steps]
    if len(set(ids)) != len(ids):
        problems.append(f"Step ID 重复: {ids}")

    for step in plan.steps:
        if step.status not in list(PlanStepStatus):
            problems.append(
                f"Step {step.step_id} 状态非法: {step.status}"
            )

    return problems


def create_plan(
    *,
    plan_id: str,
    task_id: str,
    steps: tuple[PlanStep, ...],
    version: int = 1,
) -> Plan:
    """创建新 Plan。强制初始步骤全部 PENDING。

    Raises:
        ValueError: steps 为空、ID 重复、或存在非 PENDING 的步骤。
    """
    if not steps:
        raise ValueError("Plan 至少需要 1 个 Step")

    for step in steps:
        if step.status != PlanStepStatus.PENDING:
            raise ValueError(
                f"新建 Plan 的步骤必须全部 PENDING，"
                f"但 {step.step_id} 是 {step.status.value}"
            )

    plan = Plan(
        plan_id=plan_id,
        task_id=task_id,
        version=version,
        steps=steps,
    )

    problems = validate_plan(plan)
    if problems:
        raise ValueError("; ".join(problems))

    return plan


def replan(
    *,
    existing: Plan,
    new_steps: tuple[PlanStep, ...],
) -> Plan:
    """基于新证据生成新版本 Plan。

    - version = 旧 version + 1
    - task_id 不变
    - 旧 Plan 对象不被修改（steps 是 tuple，天然不可变）
    - 新 steps 必须全部 PENDING

    Raises:
        ValueError: new_steps 非法。
    """
    return create_plan(
        plan_id=existing.plan_id,
        task_id=existing.task_id,
        steps=new_steps,
        version=existing.version + 1,
    )