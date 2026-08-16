"""
Task 生命周期状态机。

TaskStatus 定义一个 Coding Task 从创建到终止的全部状态，
TASK_TRANSITIONS 集中定义合法转移，
TaskState.transition_to() 是唯一允许修改状态的入口。

与 codeteam/state.py 的区别：
- codeteam/state.py 是 AgentLoopState（Week 1 的循环步数计数）
- 本文件是 Task 生命周期状态机（Week 4 的任务阶段管理）
两者职责不同，互不依赖。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    """Task 生命周期状态。

    CREATED → INSPECTING → PLANNING → READY → IMPLEMENTING
    → VERIFYING → COMPLETED；任何状态在不可恢复错误时可 → FAILED。
    """
    CREATED = "created"          # 任务已创建，尚未开始
    INSPECTING = "inspecting"    # 正在检查仓库
    PLANNING = "planning"        # 正在生成执行计划
    READY = "ready"              # 计划就绪，尚未执行（Day 1 终点）
    IMPLEMENTING = "implementing"  # 正在修改代码（Day 2+）
    VERIFYING = "verifying"      # 正在验证（Day 2+）
    PAUSED = "paused"            # 已暂停
    COMPLETED = "completed"      # 成功结束（Terminal）
    FAILED = "failed"            # 失败结束（Terminal）


# 合法转移表：键 = 当前状态，值 = 可到达的目标状态
# Terminal 状态（COMPLETED / FAILED）的值为空元组
TASK_TRANSITIONS: dict[TaskStatus, tuple[TaskStatus, ...]] = {
    TaskStatus.CREATED: (
        TaskStatus.INSPECTING,
        TaskStatus.FAILED,
    ),
    TaskStatus.INSPECTING: (
        TaskStatus.PLANNING,
        TaskStatus.FAILED,
    ),
    TaskStatus.PLANNING: (
        TaskStatus.READY,
        TaskStatus.FAILED,
    ),
    TaskStatus.READY: (
        TaskStatus.IMPLEMENTING,
        TaskStatus.PAUSED,
        TaskStatus.FAILED,
    ),
    TaskStatus.IMPLEMENTING: (
        TaskStatus.VERIFYING,
        TaskStatus.PAUSED,
        TaskStatus.FAILED,
    ),
    TaskStatus.VERIFYING: (
        TaskStatus.COMPLETED,
        TaskStatus.IMPLEMENTING,  # 验证失败 → 回去修复
        TaskStatus.FAILED,
    ),
    TaskStatus.PAUSED: (
        TaskStatus.READY,
        TaskStatus.IMPLEMENTING,
    ),
    TaskStatus.COMPLETED: (),
    TaskStatus.FAILED: (),
}


class InvalidTransitionError(Exception):
    """状态转移非法时抛出。

    专门定义而不是用 ValueError，是为了让调用方
    （如 Orchestrator）能够精确捕获并分类这个错误。
    """


@dataclass(frozen=True)
class TaskTransition:
    """一次状态转移的记录（审计用）。"""
    from_status: TaskStatus
    to_status: TaskStatus
    reason: str = ""


@dataclass
class TaskState:
    """一个 Task 的当前生命周期状态。

    唯一修改状态的入口是 transition_to()。
    history 记录全部转移，供事件/审计/调试使用。
    """

    task_id: str
    status: TaskStatus = TaskStatus.CREATED
    history: list[TaskTransition] = field(default_factory=list)

    @property
    def is_terminal(self) -> bool:
        """当前状态是否是终止状态。

        Terminal = 转移表中没有任何合法出口。
        用 @property 实时计算而不是存字段，
        避免 status 变化后 terminal 标志不一致。
        """
        return not TASK_TRANSITIONS[self.status]

    def transition_to(
        self,
        new_status: TaskStatus,
        *,
        reason: str = "",
    ) -> None:
        """转移到 new_status。

        唯一合法的状态修改入口。非法转移抛 InvalidTransitionError。

        Args:
            new_status: 目标状态。
            reason:     转移原因（如 "valid_plan_created"），
                        只用于审计记录，不影响合法性判断。

        Raises:
            InvalidTransitionError: new_status 不在当前状态的合法出口中，
                                    或当前状态是 Terminal。
        """
        legal = TASK_TRANSITIONS[self.status]

        if new_status not in legal:
            raise InvalidTransitionError(
                f"非法状态转移: {self.status.value} "
                f"→ {new_status.value}。"
                f"允许的目标: {[s.value for s in legal]}"
            )

        self.history.append(
            TaskTransition(
                from_status=self.status,
                to_status=new_status,
                reason=reason,
            )
        )
        self.status = new_status