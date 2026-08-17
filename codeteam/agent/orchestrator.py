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
from codeteam.git.workspace import GitWorkspace
from codeteam.planning.models import (
    Plan,
    PlanStep,
    PlanStepStatus,
    validate_plan,
)
from codeteam.planning.planner import Planner, RepositoryContext
from codeteam.repair.loop import RepairAgent, RepairLoop
from codeteam.repair.models import RepairLoopRunResult, RepairRunOutcome
from codeteam.task.models import TaskSpec, create_task_spec
from codeteam.task.state import InvalidTransitionError, TaskState, TaskStatus
from codeteam.verification.models import VerificationRequest
from codeteam.verification.service import VerificationService


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

    task_state: TaskState | None = None
    """本次运行使用的 TaskState（Day 2 execute_plan_step 需要跨方法持有）。"""


class StepExecutionResult(BaseModel):
    """一次 PlanStep 执行的完整结果（Day 2）。"""

    task_id: str
    plan_step_id: str

    task_status: TaskStatus
    step_status: PlanStepStatus

    loop_result: RepairLoopRunResult | None = None
    events: list[AgentEvent] = Field(default_factory=list)


class SingleAgentOrchestrator:
    """单 Agent 任务编排器。

    Day 1：run() 走到 READY。
    Day 2：execute_plan_step() 执行「候选 → 验证 → 修复」循环
    并推进 PlanStep / Task 状态。

    用法：
        orchestrator = SingleAgentOrchestrator(
            inspector=RepositoryInspector(service),
            planner=MockPlanner(plan=...),
            repository_root=root,
            verification_service=VerificationService(),   # Day 2 执行期依赖
            workspace=GitWorkspace(root),                 # Day 2 执行期依赖
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
        verification_service: VerificationService | None = None,
        workspace: GitWorkspace | None = None,
    ) -> None:
        """全部依赖注入——测试可替换，生产可换真实实现。

        verification_service / workspace 是 Day 2 的执行期依赖：
        run()（Day 1 到 READY）不需要；execute_plan_step() 必须注入，
        缺失时 execute_plan_step 抛带明确消息的 RuntimeError。
        """
        self._inspector = inspector
        self._planner = planner
        self._repository_root = repository_root
        self._verification_service = verification_service
        self._workspace = workspace

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
            task_state=state,
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
            task_state=state,
        )
    
    def execute_plan_step(
            self,
            *,
            task: TaskSpec,
            plan_step: PlanStep,
            task_state: TaskState,
            initial_patch: str,
            repair_agent: RepairAgent,
            target_request: VerificationRequest,
            related_regression_request: VerificationRequest | None = None,
            max_repair_attempts: int = 3,
            workspace_root: Path,
        ) -> StepExecutionResult:
            """执行一个 PlanStep 的「候选 → 验证 → 修复」循环并推进状态。

            状态规则（day2.md 七十九节）：
            - SUCCESS → step COMPLETED、task → VERIFYING → COMPLETED
            - REPAIR_EXHAUSTED → step FAILED、task FAILED（唯一 step FAILED 路径）
            - EXECUTION_ERROR / INTERRUPTED → step 保持 RUNNING、
            task 保持 IMPLEMENTING（恢复策略是 Day 3 的事）
            """
            # 执行期依赖守卫：run()（Day 1 路径）不需要这两个注入，
            # 但 execute_plan_step 离不开——缺失时大声失败而非静默出错
            if (
                self._verification_service is None
                or self._workspace is None
            ):
                raise RuntimeError(
                    "execute_plan_step 需要 verification_service 与 workspace，"
                    "请在构造 SingleAgentOrchestrator 时注入"
                )

            events: list[AgentEvent] = []

            # ① 前置状态推进：task READY → IMPLEMENTING
            try:
                task_state.transition_to(
                    TaskStatus.IMPLEMENTING, reason="step_execution_started"
                )
            except InvalidTransitionError:
                return StepExecutionResult(
                    task_id=task.task_id,
                    plan_step_id=plan_step.step_id,
                    task_status=task_state.status,
                    step_status=plan_step.status,
                    events=events,
                )
            events.append(self._status_event(task_state, "step_execution_started"))

            # ② step PENDING → RUNNING
            plan_step.transition_to(PlanStepStatus.RUNNING)

            # ③ 运行修复循环
            loop = RepairLoop(
                verification_service=self._verification_service,
                workspace=self._workspace,
            )
            events.append(make_event(
                AgentEventType.REPAIR_STARTED,
                f"修复循环开始: {task.task_id}/{plan_step.step_id}",
                data={"task_id": task.task_id, "plan_step_id": plan_step.step_id},
            ))

            loop_result = loop.run(
                task=task,
                plan_step_title=plan_step.title,
                initial_patch=initial_patch,
                target_request=target_request,
                workspace_root=workspace_root,
                repair_agent=repair_agent,
                max_repair_attempts=max_repair_attempts,
                related_regression_request=related_regression_request,
            )

            # ④ 从结果回放 attempt 事件
            for attempt in loop_result.attempts:
                if attempt.patch_hash:
                    events.append(make_event(
                        AgentEventType.REPAIR_PATCH_PROPOSED,
                        f"修复 Patch 提出: attempt #{attempt.attempt_no}",
                        data={"attempt_no": attempt.attempt_no,
                            "patch_hash": attempt.patch_hash},
                    ))
                if attempt.changed_files:
                    events.append(make_event(
                        AgentEventType.REPAIR_PATCH_APPLIED,
                        f"修复 Patch 应用: {', '.join(attempt.changed_files)}",
                        data={"attempt_no": attempt.attempt_no,
                            "changed_files": list(attempt.changed_files)},
                    ))

            # ⑤ outcome → 状态推进
            if loop_result.outcome is RepairRunOutcome.SUCCESS:
                task_state.transition_to(TaskStatus.VERIFYING, reason="target_passed")
                events.append(self._status_event(task_state, "target_passed"))
                task_state.transition_to(TaskStatus.COMPLETED, reason="regression_passed")
                events.append(self._status_event(task_state, "regression_passed"))
                plan_step.transition_to(PlanStepStatus.COMPLETED)
                events.append(make_event(
                    AgentEventType.REPAIR_COMPLETED,
                    f"修复完成: {plan_step.step_id}",
                    data={"task_id": task.task_id, "plan_step_id": plan_step.step_id,
                        "repair_count": loop_result.repair_count},
                ))
            elif loop_result.outcome is RepairRunOutcome.REPAIR_EXHAUSTED:
                plan_step.transition_to(PlanStepStatus.FAILED)
                self._fail(task_state, events, reason="repair_exhausted")
                events.append(make_event(
                    AgentEventType.REPAIR_EXHAUSTED,
                    f"修复预算耗尽: {plan_step.step_id}",
                    data={"task_id": task.task_id, "plan_step_id": plan_step.step_id,
                        "repair_count": loop_result.repair_count},
                ))
            else:
                events.append(make_event(
                    AgentEventType.REPAIR_FAILED,
                    f"修复循环异常结束: {loop_result.outcome.value}",
                    data={"task_id": task.task_id, "plan_step_id": plan_step.step_id,
                        "outcome": loop_result.outcome.value},
                ))

            return StepExecutionResult(
                task_id=task.task_id,
                plan_step_id=plan_step.step_id,
                task_status=task_state.status,
                step_status=plan_step.status,
                loop_result=loop_result,
                events=events,
            )