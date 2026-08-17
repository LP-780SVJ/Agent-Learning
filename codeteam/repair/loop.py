"""
RepairLoop：候选 Patch 的验证循环（Day 2 版本）。

Step 3 只实现单次候选评估 run_candidate；
Step 5 叠加 FAIL → Repair → 再 Verify 的循环；
Step 6 叠加 Regression Cascade 与 PlanStep 状态推进。

RepairLoop 不自己 subprocess / git apply / 调模型——
只协调 GitWorkspace（Week 3）与 VerificationService（本日 Step 2）。
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from codeteam.git.models import PatchResult, PatchStatus
from codeteam.git.workspace import GitWorkspace
from codeteam.repair.models import (
    RepairAttempt,
    RepairContext,
    RepairLoopOutcome,
    RepairLoopResult,
    RepairLoopRunResult,
    RepairOutcome,
    RepairRunOutcome,
    build_repair_context,
)
from codeteam.task.models import TaskSpec
from codeteam.verification.models import (
    VerificationRequest,
    VerificationResult,
    VerificationStatus,
)
from codeteam.verification.service import VerificationService

_EMPTY_PATCH_RESULT = PatchResult(
    status=PatchStatus.APPLIED, patch_sha256="", affected_paths=[], applied=True
)


class RepairLoop:
    """候选 Patch 的验证循环器。

    用法：
        loop = RepairLoop(
            verification_service=service,
            workspace=GitWorkspace(worktree_root),
        )
        result = loop.run_candidate(
            task_id="t-001",
            plan_step_id="P3",
            patch=patch_text,
            target_request=target_req,
            workspace_root=worktree_root,
        )
    """

    def __init__(
        self,
        *,
        verification_service: VerificationService,
        workspace: GitWorkspace,
    ) -> None:
        self._verification_service = verification_service
        self._workspace = workspace

    # ── 单次候选评估（Step 3）──────────────────────────────

    def run_candidate(
        self,
        *,
        task_id: str,
        plan_step_id: str | None,
        patch: str,
        target_request: VerificationRequest,
        workspace_root: Path,
    ) -> RepairLoopResult:
        """应用一个候选 Patch 并跑 Target 验证。

        只评估、不推进状态、不回滚——
        PlanStep 状态推进是 Step 6 的事。

        Args:
            task_id: 任务标识。
            plan_step_id: 当前 PlanStep（审计用）。
            patch: 候选 Patch 文本。
            target_request: Target 验证请求（kind=TARGETED_TEST）。
            workspace_root: 任务 Worktree 根目录（验证的安全边界）。

        Returns:
            RepairLoopResult；PATCH_FAILED 时不跑验证。
        """
        # ① 应用 Patch（Week 3 安全链：validate → check → apply）
        patch_result = self._workspace.apply_patch(patch)

        if patch_result.status is not PatchStatus.APPLIED:
            # T12：Patch 无法应用是 PATCH FAILURE，不是 TEST FAILURE
            return RepairLoopResult(
                task_id=task_id,
                plan_step_id=plan_step_id,
                outcome=RepairLoopOutcome.PATCH_FAILED,
                patch_result=patch_result,
            )

        # ② Target 验证（走 Step 2 的安全执行链）
        target_result = self._verification_service.verify(
            target_request,
            workspace_root=workspace_root,
        )

        # ③ outcome 判定
        outcome = self._classify_target_outcome(target_result)

        return RepairLoopResult(
            task_id=task_id,
            plan_step_id=plan_step_id,
            outcome=outcome,
            patch_result=patch_result,
            target_result=target_result,
        )

    def run(
        self,
        *,
        task: TaskSpec,
        plan_step_title: str,
        initial_patch: str,
        target_request: VerificationRequest,
        workspace_root: Path,
        repair_agent: RepairAgent,
        max_repair_attempts: int = 3,
        should_stop: Callable[[], bool] | None = None,
        checkpoint_hook: Callable[[int], str | None] | None = None,
        related_regression_request: VerificationRequest | None = None,
    ) -> RepairLoopRunResult:
        """运行「候选 → 验证 → 修复」循环直到停止条件。

        新增（Step 6）：related_regression_request 非 None 时，
        Target PASS 之后接 Related Regression——
        Regression FAILED 以回归失败进入下一轮 Repair。
        """
        regression_results: list[VerificationResult] = []

        def evaluate(candidate: RepairLoopResult) -> tuple[str, VerificationResult | None]:
            """成功检查：返回 (阶段, 失败证据)。"""
            if candidate.outcome is RepairLoopOutcome.TARGET_FAILED:
                return "failure", candidate.target_result
            if candidate.outcome is RepairLoopOutcome.TARGET_PASSED:
                if related_regression_request is None:
                    return "success", None
                reg = self._verification_service.verify(
                    related_regression_request,
                    workspace_root=workspace_root,
                )
                regression_results.append(reg)
                if reg.status is VerificationStatus.PASSED:
                    return "success", None
                if reg.status.requires_repair:
                    return "failure", reg
                return "inconclusive", reg
            if candidate.outcome is RepairLoopOutcome.PATCH_FAILED:
                return "failure", None
            return "inconclusive", candidate.target_result

        # ① 初始候选（不算 repair）
        candidate = self.run_candidate(
            task_id=task.task_id,
            plan_step_id=target_request.plan_step_id,
            patch=initial_patch,
            target_request=target_request,
            workspace_root=workspace_root,
        )
        # 捕获初始候选：循环内 candidate 会被逐轮覆盖，
        # 所有返回路径的 initial_candidate 必须引用这份捕获值
        initial_candidate = candidate
        phase, failure = evaluate(candidate)

        if phase == "success":
            return RepairLoopRunResult(
                task_id=task.task_id,
                plan_step_id=target_request.plan_step_id,
                outcome=RepairRunOutcome.SUCCESS,
                initial_candidate=initial_candidate,
                final_candidate=candidate,
                regression_results=tuple(regression_results),
            )
        if phase == "inconclusive":
            return RepairLoopRunResult(
                task_id=task.task_id,
                plan_step_id=target_request.plan_step_id,
                outcome=RepairRunOutcome.EXECUTION_ERROR,
                initial_candidate=initial_candidate,
                final_candidate=candidate,
                regression_results=tuple(regression_results),
            )

        # ② 修复循环（failure 驱动）
        attempts: list[RepairAttempt] = []
        attempt_no = 1

        while attempt_no <= max_repair_attempts:
            if should_stop is not None and should_stop():
                return RepairLoopRunResult(
                    task_id=task.task_id,
                    plan_step_id=target_request.plan_step_id,
                    outcome=RepairRunOutcome.INTERRUPTED,
                    attempts=tuple(attempts),
                    initial_candidate=initial_candidate,
                    final_candidate=candidate,
                    regression_results=tuple(regression_results),
                )

            checkpoint_id = (
                checkpoint_hook(attempt_no)
                if checkpoint_hook is not None else None
            )

            context = self._build_context(
                task=task,
                plan_step_title=plan_step_title,
                candidate=candidate,
                failure_result=failure,
                previous_attempts=tuple(attempts),
            )

            try:
                patch = repair_agent.propose_patch(context)
            except Exception:  # noqa: BLE001 — 总闸门：agent 异常必须转 NO_PATCH → EXECUTION_ERROR，不能上抛
                attempts.append(self._no_patch_attempt(
                    attempt_no=attempt_no, task_id=task.task_id,
                    plan_step_id=target_request.plan_step_id or "",
                    checkpoint_id=checkpoint_id, failure=failure,
                ))
                return RepairLoopRunResult(
                    task_id=task.task_id,
                    plan_step_id=target_request.plan_step_id,
                    outcome=RepairRunOutcome.EXECUTION_ERROR,
                    attempts=tuple(attempts),
                    final_candidate=candidate,
                    regression_results=tuple(regression_results),
                )

            if not patch.strip():
                attempts.append(self._no_patch_attempt(
                    attempt_no=attempt_no, task_id=task.task_id,
                    plan_step_id=target_request.plan_step_id or "",
                    checkpoint_id=checkpoint_id, failure=failure,
                ))
                return RepairLoopRunResult(
                    task_id=task.task_id,
                    plan_step_id=target_request.plan_step_id,
                    outcome=RepairRunOutcome.EXECUTION_ERROR,
                    attempts=tuple(attempts),
                    final_candidate=candidate,
                    regression_results=tuple(regression_results),
                )

            new_candidate = self.run_candidate(
                task_id=task.task_id,
                plan_step_id=target_request.plan_step_id,
                patch=patch,
                target_request=target_request,
                workspace_root=workspace_root,
            )

            attempt = RepairAttempt(
                attempt_no=attempt_no,
                task_id=task.task_id,
                plan_step_id=target_request.plan_step_id or "",
                checkpoint_id=checkpoint_id,
                failure_signature=(
                    failure.failure_signature if failure else None
                ),
                patch_hash=hashlib.sha256(patch.encode("utf-8")).hexdigest(),
                changed_files=tuple(
                    new_candidate.patch_result.affected_paths
                    if new_candidate.patch_result else ()
                ),
                verification_ids=(
                    (target_request.verification_id,)
                    if new_candidate.target_result else ()
                ),
                outcome=self._attempt_outcome(new_candidate),
            )
            attempts.append(attempt)

            phase, failure = evaluate(new_candidate)

            if phase == "success":
                return RepairLoopRunResult(
                    task_id=task.task_id,
                    plan_step_id=target_request.plan_step_id,
                    outcome=RepairRunOutcome.SUCCESS,
                    attempts=tuple(attempts),
                    initial_candidate=initial_candidate,
                    final_candidate=new_candidate,
                    regression_results=tuple(regression_results),
                )
            if phase == "inconclusive":
                return RepairLoopRunResult(
                    task_id=task.task_id,
                    plan_step_id=target_request.plan_step_id,
                    outcome=RepairRunOutcome.EXECUTION_ERROR,
                    attempts=tuple(attempts),
                    final_candidate=new_candidate,
                    regression_results=tuple(regression_results),
                )

            candidate = new_candidate
            attempt_no += 1

        return RepairLoopRunResult(
            task_id=task.task_id,
            plan_step_id=target_request.plan_step_id,
            outcome=RepairRunOutcome.REPAIR_EXHAUSTED,
            attempts=tuple(attempts),
            initial_candidate=initial_candidate,
            final_candidate=candidate,
            regression_results=tuple(regression_results),
        )

    # ── 工具 ──────────────────────────────────────────────

    @staticmethod
    def _classify_target_outcome(
        target_result: VerificationResult,
    ) -> RepairLoopOutcome:
        """把 Target 验证证据分类为 loop outcome。

        PASSED → TARGET_PASSED
        FAILED（requires_repair）→ TARGET_FAILED
        TIMED_OUT / START_FAILED / BLOCKED / INCONCLUSIVE
            → TARGET_INCONCLUSIVE（无行为证据，不默认修代码）
        """
        if target_result.status is VerificationStatus.PASSED:
            return RepairLoopOutcome.TARGET_PASSED
        if target_result.status.requires_repair:
            return RepairLoopOutcome.TARGET_FAILED
        return RepairLoopOutcome.TARGET_INCONCLUSIVE

    @staticmethod
    def _attempt_outcome(candidate: RepairLoopResult) -> RepairOutcome:
        """把候选评估结果映射为本轮 repair 动作的结果。"""
        mapping = {
            RepairLoopOutcome.TARGET_PASSED: RepairOutcome.VERIFIED_PASSED,
            RepairLoopOutcome.TARGET_FAILED: RepairOutcome.VERIFIED_FAILED,
            RepairLoopOutcome.PATCH_FAILED: RepairOutcome.PATCH_FAILED,
            RepairLoopOutcome.TARGET_INCONCLUSIVE: (
                RepairOutcome.VERIFIED_INCONCLUSIVE
            ),
        }
        return mapping[candidate.outcome]

    @staticmethod
    def _build_context(
        *,
        task: TaskSpec,
        plan_step_title: str,
        candidate: RepairLoopResult,
        failure_result: VerificationResult | None,
        previous_attempts: tuple[RepairAttempt, ...],
    ) -> RepairContext:
        """组装反馈包。failure_result 是统一的失败来源——
        可以是 Target 失败，也可以是 Regression 失败。"""
        if failure_result is not None:
            return build_repair_context(
                task=task,
                plan_step_title=plan_step_title,
                target_result=failure_result,
                patch_result=candidate.patch_result or _EMPTY_PATCH_RESULT,
                previous_attempts=previous_attempts,
            )
        # PATCH_FAILED：没有验证证据，用 patch 失败信息
        return RepairContext(
            goal=task.goal,
            plan_step_title=plan_step_title,
            failure_summary=(
                f"PATCH_FAILED: {candidate.patch_result.failure_reason}"
                if candidate.patch_result else "PATCH_FAILED"
            ),
            previous_attempts="\n".join(
                f"attempt #{a.attempt_no}: outcome={a.outcome.value}"
                for a in previous_attempts
            ),
            constraints=task.constraints,
        )

    @staticmethod
    def _no_patch_attempt(
        *,
        attempt_no: int,
        task_id: str,
        plan_step_id: str,
        checkpoint_id: str | None,
        failure: VerificationResult | None,
    ) -> RepairAttempt:
        """构造 NO_PATCH 的 attempt 记录（agent 异常/空串共用）。"""
        return RepairAttempt(
            attempt_no=attempt_no,
            task_id=task_id,
            plan_step_id=plan_step_id,
            checkpoint_id=checkpoint_id,
            failure_signature=failure.failure_signature if failure else None,
            outcome=RepairOutcome.NO_PATCH,
        )

class RepairAgent(Protocol):
    """修复代理接口。循环只依赖这一个方法。"""

    def propose_patch(self, context: RepairContext) -> str:
        """根据修复上下文生成候选 Patch 文本。

        无法生成时返回空字符串。
        """
        ...


class MockRepairAgent:
    """确定性 RepairAgent：按队列顺序返回注入的 Patch。

    patches 耗尽后返回空串（模拟"模型无法生成"）。
    calls 记录收到的 RepairContext（断言 agent 调用次数）。
    """

    def __init__(self, patches: list[str] | None = None) -> None:
        self._patches = list(patches or [])
        self._index = 0
        self.calls: list[RepairContext] = []

    def propose_patch(self, context: RepairContext) -> str:
        self.calls.append(context)
        if self._index >= len(self._patches):
            return ""
        patch = self._patches[self._index]
        self._index += 1
        return patch