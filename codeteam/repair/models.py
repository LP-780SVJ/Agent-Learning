"""
Repair 层数据模型。

Step 3 只有单次候选评估的结果类型；
Step 4 会扩展 RepairAttempt / RepairContext。
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from codeteam.git.models import PatchResult
from codeteam.verification.models import VerificationResult


class RepairLoopOutcome(str, Enum):
    """一次候选 Patch 评估的结果语义。

    PATCH_FAILED ≠ TARGET_FAILED（day2.md T12）：
    - PATCH_FAILED：Patch 没能落地，没有行为证据
    - TARGET_FAILED：代码行为未通过验证（唯一触发 Repair 的）
    - TARGET_INCONCLUSIVE：验证无结论（超时/环境/被拦截），不默认修代码
    """

    TARGET_PASSED = "target_passed"
    TARGET_FAILED = "target_failed"
    TARGET_INCONCLUSIVE = "target_inconclusive"
    PATCH_FAILED = "patch_failed"


class RepairLoopResult(BaseModel):
    """单次候选评估的完整结果。"""

    task_id: str
    plan_step_id: str | None = None

    outcome: RepairLoopOutcome

    patch_result: PatchResult | None = None
    """apply_patch 的结果；PATCH_FAILED 时必有。"""

    target_result: VerificationResult | None = None
    """Target 验证证据；跑了验证才有（PATCH_FAILED 时为 None）。"""

    events: list = Field(default_factory=list)
    """Step 5/6 接入事件系统时填充（本步留空列表）。"""


class RepairOutcome(str, Enum):
    """一次 Repair 动作的结果语义。

    与 RepairLoopOutcome（候选评估层）是两个层级：
    评估层回答"这个候选过没过"，动作层回答"这轮修复产生了什么"。
    """

    VERIFIED_PASSED = "verified_passed"
    """本轮修复后验证通过。"""

    VERIFIED_FAILED = "verified_failed"
    """本轮修复后验证仍失败。"""

    PATCH_FAILED = "patch_failed"
    """本轮生成的 Patch 无法应用。"""

    NO_PATCH = "no_patch"
    """RepairAgent 没有生成出 Patch（如超时/异常）。"""

    VERIFIED_INCONCLUSIVE = "verified_inconclusive"
    """本轮修复后的验证无结论（超时/环境/被拦截）。"""


class RepairAttempt(BaseModel):
    """一次 Repair 动作的完整审计记录（day2.md 四十一节）。

    frozen：修复事实创建后不可改，Evaluation 反复读取不失真。
    """

    model_config = ConfigDict(frozen=True)

    attempt_no: int = Field(ge=1)
    """第几次 Repair。1 起；initial patch 不算 repair。"""

    task_id: str
    plan_step_id: str

    checkpoint_id: str | None = None
    """本轮修复前保存的 checkpoint（day2.md 四十二节：
    rollback 时能回到修复前状态）。"""

    failure_signature: str | None = None
    """本轮要解决的失败指纹（来自上一轮 VerificationResult）。"""

    diagnosis_summary: str = ""
    """外显诊断结论（Actionable explanation，不是模型 CoT）。"""

    patch_hash: str | None = None
    """生成 Patch 的 SHA256；None 表示这轮没生成出 Patch。"""

    changed_files: tuple[str, ...] = ()
    verification_ids: tuple[str, ...] = ()

    outcome: RepairOutcome


class RepairContext(BaseModel):
    """喂给 RepairAgent 的有界反馈包（day2.md 四十七节）。

    只含下一轮修复需要的信息——不是整个 Session + 5MB stdout。
    """

    goal: str
    plan_step_title: str

    changed_files: tuple[str, ...] = ()
    current_diff: str = ""

    failure_summary: str = ""
    failure_tail: str = ""

    previous_attempts: str = ""

    constraints: tuple[str, ...] = ()


def failure_tail(stderr: str, *, max_lines: int = 40) -> str:
    """提取 stderr 的尾部（有界）。

    测试失败的关键证据（FAILURES 摘要、traceback）通常在尾部。
    超过 max_lines 时只保留最后 max_lines 行。
    """
    lines = stderr.splitlines()
    if len(lines) <= max_lines:
        return stderr.strip()
    return "\n".join(lines[-max_lines:]).strip()


def build_repair_context(
    *,
    task: Any,  # TaskSpec；用 Any 避免循环 import（task.models 不依赖本模块）
    plan_step_title: str,
    target_result: VerificationResult,
    patch_result: PatchResult,
    previous_attempts: tuple[RepairAttempt, ...] = (),
) -> RepairContext:
    """组装 RepairAgent 的输入。

    Args:
        task: TaskSpec（goal/constraints 来源）。
        plan_step_title: 当前 PlanStep 标题。
        target_result: 失败的 Target 验证证据。
        patch_result: 刚应用的 Patch 结果（changed_files 来源）。
        previous_attempts: 历史修复记录（压缩成摘要，防振荡）。

    Returns:
        RepairContext：有界、结构化、可序列化的反馈包。
    """
    # 历史尝试压缩成行：第几次修了什么、结果如何
    if previous_attempts:
        history_lines = [
            f"attempt #{a.attempt_no}: "
            f"signature={a.failure_signature or '-'} "
            f"outcome={a.outcome.value}"
            for a in previous_attempts
        ]
        history_summary = "\n".join(history_lines)
    else:
        history_summary = "(无历史修复)"

    return RepairContext(
        goal=task.goal,
        plan_step_title=plan_step_title,
        changed_files=tuple(patch_result.affected_paths),
        current_diff="",  # Step 5 由 loop 注入 workspace.diff().patch
        failure_summary=target_result.summary,
        failure_tail=failure_tail(target_result.stderr),
        previous_attempts=history_summary,
        constraints=task.constraints,
    )


# ── 以下为 Step 5 追加内容 ─────────────────────────────────

class RepairRunOutcome(str, Enum):
    """一次 RepairLoop.run 的最终结果。

    与 RepairOutcome（单次动作）层级不同：
    这是整个循环（含 initial candidate）的终点。
    """

    SUCCESS = "success"
    """S1：Target 验证通过（可能经历 0~N 次 repair）。"""

    REPAIR_EXHAUSTED = "repair_exhausted"
    """S2：max_repair_attempts 耗尽，agent 不再被调用。"""

    EXECUTION_ERROR = "execution_error"
    """S3：不可恢复执行错误（无行为证据/agent 无法生成 Patch）。"""

    INTERRUPTED = "interrupted"
    """S4：should_stop 回调触发（用户/运行时中断）。"""


class RepairLoopRunResult(BaseModel):
    """一次 RepairLoop.run 的完整结果。"""

    task_id: str
    plan_step_id: str | None = None

    outcome: RepairRunOutcome

    attempts: tuple[RepairAttempt, ...] = ()
    """本轮的 RepairAttempt 审计序列（顺序 = 时间序）。"""

    initial_candidate: RepairLoopResult | None = None
    final_candidate: RepairLoopResult | None = None

    regression_results: tuple[VerificationResult, ...] = ()
    """本循环中实际执行的回归验证证据（顺序 = 时间序）。
    为空表示没有配置 Related Regression。"""

    @property
    def repair_count(self) -> int:
        """实际发生的 repair 次数（周度评测 Mean Repair Attempts 的数据源）。"""
        return len(self.attempts)