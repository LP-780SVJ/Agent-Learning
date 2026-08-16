"""测试 TaskStatus 状态机（codeteam/task/state.py）。

覆盖 day1.md 一百零五节验收：
- 合法链：CREATED→...→COMPLETED 每步转移成功（验收: 状态机正确性）
- VERIFYING→IMPLEMENTING 合法（验证失败回去修复）
- 非法转移拒绝（验收: Invalid Task Transition）
- Terminal 不可转移（验收: Terminal State）
- is_terminal / history / 初始状态
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from codeteam.task.state import (
    TASK_TRANSITIONS,
    InvalidTransitionError,
    TaskState,
    TaskStatus,
)

# ===================================================================
# 合法转移
# ===================================================================

class TestLegalTransitions:
    """合法状态链与回退路径。"""

    def test_full_happy_path_chain(self) -> None:
        """验收(状态机正确性): CREATED→INSPECTING→PLANNING→READY
        →IMPLEMENTING→VERIFYING→COMPLETED 每步 transition_to 成功。"""
        state = TaskState(task_id="t-001")

        chain = [
            TaskStatus.INSPECTING,
            TaskStatus.PLANNING,
            TaskStatus.READY,
            TaskStatus.IMPLEMENTING,
            TaskStatus.VERIFYING,
            TaskStatus.COMPLETED,
        ]
        for status in chain:
            state.transition_to(status, reason="test")

        assert state.status == TaskStatus.COMPLETED
        assert len(state.history) == len(chain)

    def test_verifying_back_to_implementing_is_legal(self) -> None:
        """验收(状态机正确性): VERIFYING→IMPLEMENTING 合法——
        验证失败后回去修复。"""
        state = TaskState(task_id="t-002")
        for status in (
            TaskStatus.INSPECTING,
            TaskStatus.PLANNING,
            TaskStatus.READY,
            TaskStatus.IMPLEMENTING,
            TaskStatus.VERIFYING,
        ):
            state.transition_to(status)

        state.transition_to(TaskStatus.IMPLEMENTING)

        assert state.status == TaskStatus.IMPLEMENTING

    def test_every_state_has_failed_outlet_except_terminal(self) -> None:
        """验收(状态机正确性): 除 PAUSED 外，每个非 Terminal 状态
        都有 FAILED 出口；Terminal 状态无任何出口。

        PAUSED 按转移表设计只有 READY/IMPLEMENTING 两个出口
        （day1.md 第四十五节），单独断言。
        """
        for status in TaskStatus:
            outlets = TASK_TRANSITIONS[status]
            if status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                assert outlets == ()
            elif status == TaskStatus.PAUSED:
                assert outlets == (
                    TaskStatus.READY,
                    TaskStatus.IMPLEMENTING,
                )
            else:
                assert TaskStatus.FAILED in outlets


# ===================================================================
# 非法转移
# ===================================================================

class TestIllegalTransitions:
    """非法转移必须被拒绝。"""

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            (TaskStatus.CREATED, TaskStatus.COMPLETED),
            (TaskStatus.CREATED, TaskStatus.PLANNING),
            (TaskStatus.PLANNING, TaskStatus.IMPLEMENTING),  # 跳过 READY
            (TaskStatus.PAUSED, TaskStatus.PLANNING),
        ],
    )
    def test_illegal_jump_rejected(
        self, from_status: TaskStatus, to_status: TaskStatus
    ) -> None:
        """验收(Invalid Task Transition): 非法跳转抛
        InvalidTransitionError。"""
        state = TaskState(task_id="t-x")
        # 把状态移动到 from_status（走合法路径，含终点本身）
        path = {
            TaskStatus.CREATED: [],
            TaskStatus.PLANNING: [
                TaskStatus.INSPECTING, TaskStatus.PLANNING
            ],
            TaskStatus.PAUSED: [
                TaskStatus.INSPECTING, TaskStatus.PLANNING,
                TaskStatus.READY, TaskStatus.PAUSED,
            ],
        }[from_status]
        for s in path:
            state.transition_to(s)
        assert state.status == from_status

        with pytest.raises(InvalidTransitionError):
            state.transition_to(to_status)

    def test_terminal_completed_cannot_transition(self) -> None:
        """验收(Terminal State): COMPLETED 不可转移到任何状态。"""
        state = TaskState(task_id="t-c")
        for s in (TaskStatus.INSPECTING, TaskStatus.PLANNING,
                  TaskStatus.READY, TaskStatus.IMPLEMENTING,
                  TaskStatus.VERIFYING, TaskStatus.COMPLETED):
            state.transition_to(s)

        with pytest.raises(InvalidTransitionError):
            state.transition_to(TaskStatus.PLANNING)

    def test_terminal_failed_cannot_transition(self) -> None:
        """验收(Terminal State): FAILED 不可转移到任何状态。"""
        state = TaskState(task_id="t-f")
        state.transition_to(TaskStatus.FAILED)

        for target in (TaskStatus.INSPECTING, TaskStatus.READY,
                       TaskStatus.COMPLETED):
            with pytest.raises(InvalidTransitionError):
                state.transition_to(target)


# ===================================================================
# is_terminal / history / 初始状态
# ===================================================================

class TestStateProperties:
    """is_terminal、history 审计与初始状态。"""

    # 每个状态到自身的合法路径（含终点本身）
    _PATHS: ClassVar[dict[TaskStatus, tuple[TaskStatus, ...]]] = {
        TaskStatus.CREATED: (),
        TaskStatus.INSPECTING: (TaskStatus.INSPECTING,),
        TaskStatus.PLANNING: (TaskStatus.INSPECTING, TaskStatus.PLANNING),
        TaskStatus.READY: (
            TaskStatus.INSPECTING, TaskStatus.PLANNING, TaskStatus.READY,
        ),
        TaskStatus.IMPLEMENTING: (
            TaskStatus.INSPECTING, TaskStatus.PLANNING,
            TaskStatus.READY, TaskStatus.IMPLEMENTING,
        ),
        TaskStatus.VERIFYING: (
            TaskStatus.INSPECTING, TaskStatus.PLANNING, TaskStatus.READY,
            TaskStatus.IMPLEMENTING, TaskStatus.VERIFYING,
        ),
        TaskStatus.PAUSED: (
            TaskStatus.INSPECTING, TaskStatus.PLANNING,
            TaskStatus.READY, TaskStatus.PAUSED,
        ),
        TaskStatus.COMPLETED: (
            TaskStatus.INSPECTING, TaskStatus.PLANNING, TaskStatus.READY,
            TaskStatus.IMPLEMENTING, TaskStatus.VERIFYING,
            TaskStatus.COMPLETED,
        ),
        TaskStatus.FAILED: (TaskStatus.FAILED,),  # CREATED→FAILED 合法
    }

    @pytest.mark.parametrize(
        "status,expected",
        [
            (TaskStatus.CREATED, False),
            (TaskStatus.INSPECTING, False),
            (TaskStatus.PLANNING, False),
            (TaskStatus.READY, False),
            (TaskStatus.IMPLEMENTING, False),
            (TaskStatus.VERIFYING, False),
            (TaskStatus.PAUSED, False),
            (TaskStatus.COMPLETED, True),
            (TaskStatus.FAILED, True),
        ],
    )
    def test_is_terminal(
        self, status: TaskStatus, expected: bool
    ) -> None:
        """验收(Terminal State): 只有 COMPLETED/FAILED 是 Terminal。"""
        state = TaskState(task_id="t")
        for s in self._PATHS[status]:
            state.transition_to(s)
        assert state.status == status
        assert state.is_terminal is expected

    def test_history_records_from_to_reason(self) -> None:
        """验收(状态机正确性): history 记录 from/to/reason 三元组。"""
        state = TaskState(task_id="t-h")
        state.transition_to(TaskStatus.INSPECTING, reason="r1")
        state.transition_to(TaskStatus.PLANNING, reason="r2")

        assert len(state.history) == 2
        first = state.history[0]
        assert first.from_status == TaskStatus.CREATED
        assert first.to_status == TaskStatus.INSPECTING
        assert first.reason == "r1"
        assert state.history[1].reason == "r2"

    def test_failed_transition_leaves_state_unchanged(self) -> None:
        """验收(状态机安全性): 非法转移失败后 history 不增长、
        status 不变——失败转移无副作用。"""
        state = TaskState(task_id="t-s")
        state.transition_to(TaskStatus.INSPECTING)

        before_history = len(state.history)
        before_status = state.status

        with pytest.raises(InvalidTransitionError):
            state.transition_to(TaskStatus.COMPLETED)

        assert len(state.history) == before_history
        assert state.status == before_status

    def test_initial_status_is_created(self) -> None:
        """验收(状态机正确性): TaskState 初始 status == CREATED。"""
        state = TaskState(task_id="t-i")
        assert state.status == TaskStatus.CREATED
        assert state.is_terminal is False


# ===================================================================
# F1 回归：类型守卫
# ===================================================================

class TestTransitionTypeGuard:
    """F1 回归: transition_to 拒绝非枚举输入（裸字符串/None/int）。

    根因：TaskStatus 是 str-Enum，'inspecting' == TaskStatus.INSPECTING
    为 True，裸字符串可绕过成员检查并被存入 status。
    """

    @pytest.mark.parametrize(
        "bad",
        ["inspecting", "ready", None, 1, 1.5, object()],
        ids=["str-inspecting", "str-ready", "none", "int", "float", "object"],
    )
    def test_non_enum_rejected_and_state_unchanged(self, bad) -> None:
        """验收(F1): 非法类型全部拒绝，status 与 history 不变。"""
        state = TaskState(task_id="t-f1")
        before_history = len(state.history)

        with pytest.raises(InvalidTransitionError):
            state.transition_to(bad)

        assert state.status == TaskStatus.CREATED
        assert len(state.history) == before_history

    def test_legal_enum_transition_still_works(self) -> None:
        """验收(F1 不破坏合法行为): 合法枚举转移不受类型守卫影响。"""
        state = TaskState(task_id="t-f1-ok")
        state.transition_to(TaskStatus.INSPECTING)
        assert state.status == TaskStatus.INSPECTING
        assert state.history[-1].to_status == TaskStatus.INSPECTING
