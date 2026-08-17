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
