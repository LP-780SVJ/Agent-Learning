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
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from codeteam.agent.inspection import RepositoryInspector
from codeteam.events import (
    AgentEvent,
    AgentEventType,
    make_event,
)
from codeteam.failures.classifier import ErrorClassifier
from codeteam.failures.models import AgentFailure, FailureStage
from codeteam.failures.recovery import RecoveryAction, RecoveryPolicy
from codeteam.failures.retry import RetryPolicy
from codeteam.git.workspace import GitWorkspace
from codeteam.planning.models import (
    Plan,
    PlanStep,
    PlanStepStatus,
    validate_plan,
)
from codeteam.planning.planner import Planner, RepositoryContext
from codeteam.repair.loop import RepairAgent, RepairLoop
from codeteam.repair.models import (
    RepairLoopRunResult,
    RepairOutcome,
    RepairRunOutcome,
)
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
        # ── 错误恢复注入（全部可选，测试可替换）──
        classifier: ErrorClassifier | None = None,
        recovery_policy: RecoveryPolicy | None = None,
        retry_policy: RetryPolicy | None = None,
        sleeper: Callable[[float], None] | None = None,
        # ── W4D4 Step 4：暂停持久化回调 ──
        # orchestrator 不依赖 SessionService 类型（依赖倒置）；
        # 调用方绑定，如：
        #   lambda reason: service.pause(session, reason=reason)
        pause_persister: Callable[[str], None] | None = None,
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
        self._classifier = classifier or ErrorClassifier()
        self._recovery_policy = recovery_policy or RecoveryPolicy()
        self._retry_policy = retry_policy or RetryPolicy()
        self._sleeper = sleeper or time.sleep
        self._pause_persister = pause_persister
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
        except KeyboardInterrupt:
            # I6：用户中断是 Runtime Control Flow，不是 Failure（day3 §四十五）
            return self._pause(state, events, reason="user_interrupt")
        except _TerminalFailure as tf:
            # 已知 Domain Failure：分类/决策已完成，直接用其消息失败。
            # reason 含 source_type 以保持 D1 契约「error 含异常类型名」
            # （类型名不含敏感信息，原始消息仍在 failure.source_message 中），
            # 并含终态原因（如 max_attempts_exhausted）供审计定位。
            return self._fail(
                state, events,
                reason=(
                    f"{tf.failure.code.value}: "
                    f"{tf.failure.message} "
                    f"[{tf!s}] "
                    f"(来源: {tf.failure.source_type or 'unknown'})"
                ),
            )
        except Exception as exc:  # noqa: BLE001 — 兜底：未知异常仍 FAILED（D1 不回归）
            return self._fail(
                state, events,
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
        plan = self._execute_with_recovery(
            state=state,
            events=events,
            stage=FailureStage.MODEL_CALL,
            operation="plan_generation",
            action=lambda: self._planner.create_plan(
                task=spec,
                repo_context=repo_context,
            ),
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

    def _execute_with_recovery(
        self,
        *,
        state: TaskState,
        events: list[AgentEvent],
        stage: FailureStage,
        operation: str,
        action: Callable[[], object],
    ):
        """执行一个操作，失败时走「分类 → 决策 → 执行」恢复循环。

        可重试失败（RETRY + 预算内）→ 等待后重试同一操作；
        终态（STOP / PAUSE / 预算耗尽 / 无执行器的恢复）→ 抛
        _TerminalFailure，由 run() 闸门转为 FAILED。

        Returns:
            action 的返回值（恢复成功时）。
        """
        attempt = 1
        while True:
            try:
                return action()
            except KeyboardInterrupt:
                # 中断不进循环——直接抛给闸门（闸门 → PAUSE）
                raise
            except Exception as exc:  # noqa: BLE001 — 恢复循环必须捕获任意操作异常
                # ① 检测 → 分类（deterministic，不调模型）
                events.append(make_event(
                    AgentEventType.ERROR_DETECTED,
                    f"检测到失败: {type(exc).__name__}",
                    data={"operation": operation, "stage": stage.value,
                          "source_type": type(exc).__name__},
                ))
                failure = self._classifier.classify(
                    error=exc,
                    stage=stage,
                    operation=operation,
                    task_id=state.task_id,
                    attempt=attempt,
                )
                events.append(make_event(
                    AgentEventType.ERROR_CLASSIFIED,
                    f"错误分类: {failure.category.value}/{failure.code.value}",
                    data={"category": failure.category.value,
                          "code": failure.code.value,
                          "retryable": failure.retryable},
                ))

                # ② 决策
                action_type = self._recovery_policy.decide(failure)
                events.append(make_event(
                    AgentEventType.RECOVERY_DECIDED,
                    f"恢复决策: {action_type.value}",
                    data={"action": action_type.value},
                ))

                # ③ 执行
                if action_type == RecoveryAction.RETRY:
                    decision = self._retry_policy.decide(failure)
                    if not decision.should_retry:
                        # I7：预算耗尽 → 不再执行任何操作
                        events.append(make_event(
                            AgentEventType.RETRY_EXHAUSTED,
                            f"重试预算耗尽: {decision.reason}",
                            data={"reason": decision.reason,
                                  "attempt": attempt},
                        ))
                        raise _TerminalFailure(failure, decision.reason)
                    events.append(make_event(
                        AgentEventType.RETRY_SCHEDULED,
                        f"重试已排期: delay={decision.delay_seconds}s",
                        data={"delay_seconds": decision.delay_seconds,
                              "attempt": decision.attempt},
                    ))
                    self._sleeper(decision.delay_seconds)
                    attempt = decision.attempt
                    events.append(make_event(
                        AgentEventType.RETRY_STARTED,
                        f"重试开始: attempt={attempt}",
                        data={"attempt": attempt},
                    ))
                    continue  # 重试同一操作

                if action_type == RecoveryAction.PAUSE:
                    raise _TerminalFailure(failure, "pause")

                # REPAIR / REREAD / COMPACT 等：Day 3 只发事件与终态，
                # 执行接线留 Day 5（明确不做清单）
                events.append(make_event(
                    AgentEventType.RECOVERY_STARTED,
                    f"恢复执行开始: {action_type.value}",
                    data={"action": action_type.value},
                ))
                raise _TerminalFailure(
                    failure,
                    f"recovery_executor_not_wired:{action_type.value}",
                )

    def _pause(
        self,
        state: TaskState,
        events: list[AgentEvent],
        *,
        reason: str,
    ) -> OrchestrationResult:
        """进入 PAUSED 并返回结果（与 _fail 对称的 I6 路径）。"""
        try:
            state.transition_to(TaskStatus.PAUSED, reason=reason)
        except InvalidTransitionError:
            pass
        else:
            events.append(self._status_event(state, reason))

        events.append(make_event(
            AgentEventType.TASK_PAUSED,
            f"任务暂停: {reason}",
            data={"task_id": state.task_id, "reason": reason},
        ))
        # W4D4 Step 4：PAUSED 已在内存成立 → 交给持久化回调。
        # 持久化失败不抛出（保持 run() 绝不抛异常的 D1 契约），
        # 但必须在结果中可见：error 附加 persist 失败信息，
        # 调用方（Step 7 脚本）检查 error 决定是否安全退出。
        persist_error: str | None = None
        if self._pause_persister is not None:
            try:
                self._pause_persister(reason)
            except Exception as exc:  # noqa: BLE001 — 见上，不允许崩进程
                persist_error = f"pause_persist_failed: {type(exc).__name__}: {exc}"

        return OrchestrationResult(
            task_id=state.task_id,
            status=TaskStatus.PAUSED,
            events=events,
            error=reason if persist_error is None
                  else f"{reason}; {persist_error}",
            task_state=state,
        )
    
    def _pause_step(
        self,
        *,
        task: TaskSpec,
        plan_step: PlanStep,
        task_state: TaskState,
        events: list[AgentEvent],
        reason: str,
    ) -> StepExecutionResult:
        """W4D4 K1：执行期中断 → task PAUSED、step 保持 RUNNING。

        与 _pause（run() 闸门）对称，但是 StepExecutionResult 层的暂停出口：
        - 中断不是 step 失败，step 状态原样保留（通常是 RUNNING）
        - 二次防御：transition 抛 InvalidTransitionError 时不再重复发事件
        - Step 4 将在此接 SessionService.pause() 持久化
        """
        try:
            task_state.transition_to(TaskStatus.PAUSED, reason=reason)
        except InvalidTransitionError:
            pass
        else:
            events.append(self._status_event(task_state, reason))

        events.append(make_event(
            AgentEventType.TASK_PAUSED,
            f"任务暂停: {reason}",
            data={"task_id": task.task_id, "reason": reason,
                  "plan_step_id": plan_step.step_id},
        ))
        # W4D4 Step 4：PAUSED 已在内存成立 → 交给持久化回调。
        # 持久化失败不抛出；StepExecutionResult 没有 error 字段，
        # 失败信息进 TASK_PAUSED 事件 data（上方事件已 append，
        # 故此处只补一条持久化失败事件，便于审计）。
        if self._pause_persister is not None:
            try:
                self._pause_persister(reason)
            except Exception as exc:  # noqa: BLE001 — 不允许崩进程
                events.append(make_event(
                    AgentEventType.TASK_PAUSED,
                    f"暂停持久化失败: {exc}",
                    data={"task_id": task.task_id,
                          "reason": reason,
                          "persist_error": f"{type(exc).__name__}: {exc}",
                          "plan_step_id": plan_step.step_id},
                ))

        return StepExecutionResult(
            task_id=task.task_id,
            plan_step_id=plan_step.step_id,
            task_status=TaskStatus.PAUSED,
            step_status=plan_step.status,
            events=events,
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

            loop_result = None
            interrupted = False
            try:
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
            except KeyboardInterrupt:
                # W4D4 K1：执行期 Ctrl+C 是 Runtime Control Flow，不是 step 失败。
                # RepairLoop 的 except Exception 不会捕获 KeyboardInterrupt
                # （它继承 BaseException），此处原生穿透——必须就地转 PAUSED。
                # Step 4 将在此接 SessionService：先停操作、再持久化 PAUSED。
                interrupted = True

            # ④ 从结果回放 attempt 事件
            if interrupted:
                return self._pause_step(
                    task=task,
                    plan_step=plan_step,
                    task_state=task_state,
                    events=events,
                    reason="user_interrupt",
                )

            for attempt in loop_result.attempts:
                if attempt.patch_hash:
                    events.append(make_event(
                        AgentEventType.REPAIR_PATCH_PROPOSED,
                        f"修复 Patch 提出: attempt #{attempt.attempt_no}",
                        data={"attempt_no": attempt.attempt_no,
                            "patch_hash": attempt.patch_hash},
                    ))
                # F3 修复：PATCH_FAILED 的 attempt 只发 proposed 不发 applied。
                # changed_files 保留"patch 本打算改哪些文件"的审计信息
                # （不清空），但事件层的 applied 必须与磁盘事实一致——
                # patch 没落地就不能宣称已应用。
                if (
                    attempt.changed_files
                    and attempt.outcome is not RepairOutcome.PATCH_FAILED
                ):
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

class _TerminalFailure(Exception):
    """恢复循环的终态信号：已分类的 Domain Failure，交给 run() 闸门。"""

    def __init__(self, failure: AgentFailure, reason: str) -> None:
        super().__init__(reason)
        self.failure = failure