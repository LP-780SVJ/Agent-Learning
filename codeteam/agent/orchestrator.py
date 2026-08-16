"""
SingleAgentOrchestrator：推动 Task 生命周期状态机。

Day 1 只走前半段：
CREATED → INSPECTING → PLANNING → READY

READY 即终点：不执行任何 PlanStep，磁盘零变更。

Orchestrator 只协调，不实现底层逻辑：
- 仓库检查 → RepositoryInspector（Step 5）
- 计划生成 → Planner（Step 4）
- 状态推进 → TaskState（Step 1）
- 审计记录 → make_event（events.py）
"""
from __future__ import annotations

import time
from pathlib import Path

from pydantic import BaseModel, Field

from codeteam.agent.inspection import RepositoryInspector
from codeteam.events import (
    AgentEvent,
    AgentEventType,
    make_event,
)
from codeteam.planning.models import Plan, validate_plan
from codeteam.planning.planner import Planner, RepositoryContext
from codeteam.task.models import TaskSpec, create_task_spec
from codeteam.task.state import InvalidTransitionError, TaskState, TaskStatus


class OrchestrationResult(BaseModel):
    """一次 run() 的完整结果。

    无论成功还是失败，都返回这个结构——
    调用方不需要捕获异常来判断结果。
    """

    task_id: str
    status: TaskStatus

    task: TaskSpec | None = None
    """空输入失败时为 None（TaskSpec 未构造成功）。"""

    repo_context: RepositoryContext | None = None
    plan: Plan | None = None

    events: list[AgentEvent] = Field(default_factory=list)
    """本次运行完整事件序列，供审计与 Step 7 评测断言。"""

    error: str | None = None
    """失败原因；成功时为 None。"""


class SingleAgentOrchestrator:
    """单 Agent 任务编排器（Day 1 版）。

    用法：
        orchestrator = SingleAgentOrchestrator(
            inspector=RepositoryInspector(service),
            planner=MockPlanner(plan=...),
        )
        result = orchestrator.run(
            request="修复登录超时问题",
            task_id="task-001",
        )
    """

    def __init__(
        self,
        *,
        inspector: RepositoryInspector,
        planner: Planner,
        repository_root: Path,
    ) -> None:
        """全部依赖注入——测试可替换，生产可换真实实现。"""
        self._inspector = inspector
        self._planner = planner
        self._repository_root = repository_root

    # ── 主入口 ────────────────────────────────────────────

    def run(
        self,
        *,
        request: str,
        task_id: str,
    ) -> OrchestrationResult:
        """执行 Task 生命周期前半段。

        任何阶段失败 → status=FAILED，绝不抛异常给调用方，
        绝不卡死在中间状态。
        """
        state = TaskState(task_id=task_id)
        events: list[AgentEvent] = []

        events.append(
            make_event(
                AgentEventType.TASK_CREATED,
                f"任务创建: {task_id}",
                data={"task_id": task_id},
            )
        )

        try:
            return self._run_pipeline(
                request=request,
                state=state,
                events=events,
            )
        except Exception as exc:  # noqa: BLE001 — 总闸门：任何未预期异常必须转 FAILED，不能上抛
            return self._fail(
                state,
                events,
                reason=f"{type(exc).__name__}: {exc}",
            )

    # ── 管线 ──────────────────────────────────────────────

    def _run_pipeline(
        self,
        *,
        request: str,
        state: TaskState,
        events: list[AgentEvent],
    ) -> OrchestrationResult:
        # ① 用户请求 → TaskSpec（空输入在构造时被拒绝 → 早失败）
        spec = create_task_spec(
            task_id=state.task_id,
            original_request=request,
        )

        # ② CREATED → INSPECTING
        state.transition_to(TaskStatus.INSPECTING, reason="task_spec_created")
        events.append(self._status_event(state, "task_spec_created"))

        # ③ 仓库检查（真实 Context Engine）
        events.append(
            make_event(
                AgentEventType.REPOSITORY_INSPECTION_STARTED,
                f"仓库检查开始: {state.task_id}",
                data={"task_id": state.task_id},
            )
        )
        repo_context = self._inspector.inspect(
            query=request,
            repository_root=self._repository_root,
        )
        events.append(
            make_event(
                AgentEventType.REPOSITORY_INSPECTION_COMPLETED,
                f"仓库检查完成: {len(repo_context.relevant_files)} 个相关文件",
                data={
                    "task_id": state.task_id,
                    "relevant_files": list(repo_context.relevant_files),
                },
            )
        )

        # ④ INSPECTING → PLANNING
        state.transition_to(TaskStatus.PLANNING, reason="inspection_completed")
        events.append(self._status_event(state, "inspection_completed"))

        # ⑤ 生成 Plan（计 planner_ms 供 Benchmark）
        events.append(
            make_event(
                AgentEventType.PLAN_STARTED,
                f"计划生成开始: {state.task_id}",
                data={"task_id": state.task_id},
            )
        )
        started = time.monotonic()
        plan = self._planner.create_plan(
            task=spec,
            repo_context=repo_context,
        )
        planner_ms = int((time.monotonic() - started) * 1000)
        events.append(
            make_event(
                AgentEventType.PLAN_CREATED,
                f"计划生成完成: {plan.plan_id} v{plan.version}",
                data={
                    "task_id": state.task_id,
                    "plan_id": plan.plan_id,
                    "version": plan.version,
                    "step_count": len(plan.steps),
                    "planner_ms": planner_ms,
                },
            )
        )

        # ⑥ Plan 校验（Runtime 闸门：模型输出不能直接当状态）
        problems = validate_plan(plan)
        if problems:
            events.append(
                make_event(
                    AgentEventType.PLAN_VALIDATION_FAILED,
                    f"Plan 校验失败: {'; '.join(problems)}",
                    data={"task_id": state.task_id, "problems": problems},
                )
            )
            return self._fail(
                state,
                events,
                reason="plan_validation_failed",
            )

        # ⑦ PLANNING → READY（今天终点）
        state.transition_to(TaskStatus.READY, reason="valid_plan_created")
        events.append(self._status_event(state, "valid_plan_created"))
        events.append(
            make_event(
                AgentEventType.TASK_READY,
                f"任务就绪: {state.task_id}",
                data={"task_id": state.task_id},
            )
        )

        return OrchestrationResult(
            task_id=state.task_id,
            status=TaskStatus.READY,
            task=spec,
            repo_context=repo_context,
            plan=plan,
            events=events,
        )

    # ── 工具 ──────────────────────────────────────────────

    def _status_event(self, state: TaskState, reason: str) -> AgentEvent:
        """生成一条 status_changed 事件（记录 from/to/reason）。"""
        last = state.history[-1]
        return make_event(
            AgentEventType.TASK_STATUS_CHANGED,
            f"状态转移: {last.from_status.value} → {last.to_status.value}",
            data={
                "task_id": state.task_id,
                "from_status": last.from_status.value,
                "to_status": last.to_status.value,
                "reason": reason,
            },
        )

    def _fail(
        self,
        state: TaskState,
        events: list[AgentEvent],
        *,
        reason: str,
    ) -> OrchestrationResult:
        """进入 FAILED 并返回失败结果。

        二次防御：transition 本身抛异常（如已在 Terminal）
        不能反过来让 run() 崩溃。
        """
        try:
            state.transition_to(TaskStatus.FAILED, reason=reason)
        except InvalidTransitionError:
            # 已在 Terminal（重复失败）——没有发生转移，不发 status_changed
            pass
        else:
            # 转移成功 → 与成功路径一致，补一条 →FAILED 的
            # status_changed 事件（day1.md 九十三节：每次状态变化
            # 都要记录 from/to/reason 供时序审计）
            events.append(self._status_event(state, reason))

        events.append(
            make_event(
                AgentEventType.TASK_FAILED,
                f"任务失败: {reason}",
                data={"task_id": state.task_id, "reason": reason},
            )
        )

        return OrchestrationResult(
            task_id=state.task_id,
            status=TaskStatus.FAILED,
            events=events,
            error=reason,
        )