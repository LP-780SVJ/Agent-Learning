'''
不负责执行模型，也不负责计算成本。只负责记录：
第几步
发生了什么类型的事件
事件说明是什么
有没有附加数据
事件发生时间
'''

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentEventType(str, Enum):
    STEP_STARTED = "step_started"
    MODEL_REQUEST = "model_request"
    MODEL_RESPONSE = "model_response"
    TOOL_CALLED = "tool_called"
    TOOL_RESULT = "tool_result"
    RETRY_SCHEDULED = "retry_scheduled"
    LOOP_STOPPED = "loop_stopped"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_APPROVED = "approval.approved"
    APPROVAL_DENIED = "approval.denied"
    APPROVAL_CONSUMED = "approval.consumed"

    # Task 生命周期（Week 4）
    TASK_CREATED = "task.created"
    TASK_STATUS_CHANGED = "task.status_changed"
    REPOSITORY_INSPECTION_STARTED = "repository.inspection_started"
    REPOSITORY_INSPECTION_COMPLETED = "repository.inspection_completed"
    PLAN_STARTED = "plan.started"
    PLAN_CREATED = "plan.created"
    PLAN_VALIDATION_FAILED = "plan.validation_failed"
    TASK_READY = "task.ready"
    TASK_FAILED = "task.failed"

    # Verification / Repair 循环（Week 4 Day 2）
    VERIFICATION_STARTED = "verification.started"
    VERIFICATION_COMPLETED = "verification.completed"
    VERIFICATION_FAILED = "verification.failed"
    VERIFICATION_TIMED_OUT = "verification.timed_out"
    REPAIR_STARTED = "repair.started"
    REPAIR_PATCH_PROPOSED = "repair.patch_proposed"
    REPAIR_PATCH_APPLIED = "repair.patch_applied"
    REPAIR_COMPLETED = "repair.completed"
    REPAIR_EXHAUSTED = "repair.exhausted"
    REPAIR_FAILED = "repair.failed"

    # ── Day 3：错误分类与恢复事件（dotted 命名族）──
    # 注意：RETRY_SCHEDULED（"retry_scheduled"，Week1 定义、无调用方）
    # 在 Day 3 复用于 Domain 重试调度——语义一致，值保持兼容。
    ERROR_DETECTED = "error.detected"          # 捕获到底层失败
    ERROR_CLASSIFIED = "error.classified"      # 分类完成（category/code）
    RECOVERY_DECIDED = "recovery.decided"      # 决策完成（action）
    RETRY_STARTED = "retry.started"            # 第 N 次重试开始
    RETRY_EXHAUSTED = "retry.exhausted"        # 重试预算耗尽
    RECOVERY_STARTED = "recovery.started"      # 非 RETRY 恢复开始执行
    RECOVERY_COMPLETED = "recovery.completed"  # 恢复执行成功
    RECOVERY_FAILED = "recovery.failed"        # 恢复执行自身失败
    TASK_PAUSED = "task.paused"                # 任务暂停（USER_INTERRUPT）

    # ── Day 4：Session 持久化事件（dotted 命名族）──
    SESSION_CREATED = "session.created"
    SESSION_PAUSED = "session.paused"
    SESSION_RESUMED = "session.resumed"
    SESSION_RESUME_REJECTED = "session.resume_rejected"
    SESSION_RECOVERY_REQUIRED = "session.recovery_required"

    MODEL_SWITCH_REQUESTED = "model.switch_requested"
    MODEL_SWITCH_APPLIED   = "model.switch_applied"
    MODEL_SWITCH_REJECTED  = "model.switch_rejected"
    TURN_STARTED           = "turn.started"
    TURN_COMPLETED         = "turn.completed"


@dataclass(frozen=True)
class AgentEvent:
    event_type: AgentEventType
    message: str
    step_index: int | None = None
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


def make_event(
    event_type: AgentEventType,
    message: str,
    step_index: int | None = None,
    data: dict[str, Any] | None = None,
) -> AgentEvent:
    return AgentEvent(
        event_type=event_type,
        message=message,
        step_index=step_index,
        data={} if data is None else dict(data),
    )
