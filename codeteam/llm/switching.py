"""codeteam.llm.switching — Model Switch 事务 + Turn Boundary（W4D5 Step 5）。

核心不变量（day5 §三十二）：Turn 内 ModelSelection 不可变。
- begin_turn() 冻结 selection；turn 结束（context manager 退出）才 drain 队列
- mid-turn 的 switch 请求 → QUEUED（保留意图，绝不打断当前 Turn）

事务（§三十七，任一步失败旧 selection 保持有效）：
  resolve → capability → credential → metadata → context compat
  → [compact] → rebuild client → persist → event → 下一 Turn 生效
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from codeteam.llm.base import ModelClient
from codeteam.llm.registry import (
    ModelMetadata,
    ModelSelection,
    ProviderCredentialError,
    ProviderRegistry,
    RegistryError,
    UnknownModelError,
    UnknownProviderError,
)


class SwitchOutcome(str, Enum):
    APPLIED = "applied"                      # 立即生效（无 Turn 活跃）
    COMPACTED_THEN_APPLIED = "compacted_then_applied"  # 小窗口先压后过
    QUEUED = "queued"                        # mid-turn，boundary 后处理
    REJECTED = "rejected"                    # 事务失败，旧 selection 有效


class RejectionReason(str, Enum):
    UNKNOWN_PROVIDER = "unknown_provider"
    UNKNOWN_MODEL = "unknown_model"
    MISSING_CREDENTIAL = "missing_credential"
    CAPABILITY_MISMATCH = "capability_mismatch"
    CONTEXT_STILL_OVERFLOW = "context_still_overflow"


@dataclass(frozen=True)
class SwitchRequest:
    target: ModelSelection
    reason: str = "user_request"


@dataclass
class SwitchResult:
    outcome: SwitchOutcome
    rejection: RejectionReason | None = None
    applied_selection: ModelSelection | None = None
    compacted: bool = False
    message: str = field(default="", compare=False)


EventSink = Callable[[str, dict[str, Any]], None]
PersistHook = Callable[[ModelSelection], None]


@dataclass
class TurnScope:
    """一次 Turn 的冻结状态。selection 不可变 = Turn 归因可信（S4 防御）。"""

    selection: ModelSelection
    turn_id: str
    context_tokens: int = 0


class TurnBoundaryQueue:
    """mid-turn switch 请求的 FIFO 队列（§三十三 Copilot 同款语义）。"""

    def __init__(self) -> None:
        self._pending: deque[SwitchRequest] = deque()

    def enqueue(self, request: SwitchRequest) -> None:
        self._pending.append(request)

    def drain_one(self) -> SwitchRequest | None:
        return self._pending.popleft() if self._pending else None

    def __len__(self) -> int:
        return len(self._pending)


class ModelSwitchService:
    def __init__(
        self,
        registry: ProviderRegistry,
        *,
        on_event: EventSink,
        persist: PersistHook | None = None,
        compat_check: Callable[[ModelSelection], bool] | None = None,
    ) -> None:
        self._registry = registry
        self._on_event = on_event
        self._persist = persist
        self._compat_check = compat_check
        self._current: ModelSelection | None = None
        self._active_turn: TurnScope | None = None
        self._queue = TurnBoundaryQueue()
        self._turn_counter = 0

    # ── Turn 生命周期 ──────────────────────────────────

    @contextmanager
    def turn(
        self,
        selection: ModelSelection,
        *,
        context_tokens: int = 0,
    ) -> Iterator[ModelClient]:
        """Turn Scope：进入冻结 selection，退出即 boundary（drain 队列）。

        用法：
            with service.turn(selection) as client:
                client.complete(messages)   # 整个 Turn 用同一个 client
        """
        if self._active_turn is not None:
            raise RegistryError("上一 Turn 未结束（嵌套 turn 禁止）")
        self._turn_counter += 1
        self._active_turn = TurnScope(
            selection=selection,
            turn_id=f"turn-{self._turn_counter:04d}",
            context_tokens=context_tokens,
        )
        self._current = selection
        self._emit("turn.started", {
            "turn_id": self._active_turn.turn_id,
            "provider_id": selection.provider_id,
            "model_id": selection.model_id,
            "context_tokens": context_tokens,
        })
        try:
            yield self._registry.build_client(selection)
        finally:
            scope = self._active_turn
            self._active_turn = None
            self._emit("turn.completed", {
                "turn_id": scope.turn_id if scope else "?",
                "provider_id": selection.provider_id,
                "model_id": selection.model_id,
            })
            self._drain_after_boundary()

    def _drain_after_boundary(self) -> None:
        while (request := self._queue.drain_one()) is not None:
            result = self._apply_transaction(request)
            # 排队请求在 boundary 处理，结果只发事件（无人同步等待）
            if result.outcome is SwitchOutcome.APPLIED:
                self._emit("model.switch_applied", {
                    "provider_id": result.applied_selection.provider_id
                    if result.applied_selection else None,
                    "queued": True,
                })

    # ── Switch 事务入口 ────────────────────────────────

    @property
    def current_selection(self) -> ModelSelection | None:
        return self._current

    def request_switch(self, request: SwitchRequest) -> SwitchResult:
        """11 步事务。mid-turn → QUEUED；失败 → REJECTED（旧 selection 不动）。"""
        self._emit("model.switch_requested", {
            "target_provider": request.target.provider_id,
            "target_model": request.target.model_id,
            "reason": request.reason,
        })

        # ★ Turn Boundary 不变量：活跃 Turn 中绝不切换
        if self._active_turn is not None:
            self._queue.enqueue(request)
            return SwitchResult(
                outcome=SwitchOutcome.QUEUED,
                message="turn 进行中，已排队至 boundary",
            )
        return self._apply_transaction(request)

    def _apply_transaction(self, request: SwitchRequest) -> SwitchResult:
        target = request.target
        try:
            # ②③ resolve + metadata（①requested 已发）
            metadata = self._registry.metadata(target)
            # ④ credential
            self._registry.require_credential(target)
            # capability（§三十八：requires_tools → supports_tools 等）
            self._validate_capability(metadata, request)
        except UnknownProviderError as e:
            return self._rejected(request, RejectionReason.UNKNOWN_PROVIDER, str(e))
        except UnknownModelError as e:
            return self._rejected(request, RejectionReason.UNKNOWN_MODEL, str(e))
        except ProviderCredentialError as e:
            return self._rejected(request, RejectionReason.MISSING_CREDENTIAL, str(e))

        # ⑥ context compatibility：小窗口 → 调用方注入的 compact 回调
        #    （compact 执行权在调用方——本层只判定放行与否）
        compacted = False
        if self._compat_check and not self._compat_check(target):
            return self._rejected(
                request, RejectionReason.CONTEXT_STILL_OVERFLOW,
                "compact 后仍超出目标窗口（或未提供 compactor）",
            )
        # ⑧ rebuild / ⑨ persist / ⑩ event
        self._current = target
        if self._persist is not None:
            self._persist(target)          # 生产：更新 Session 并 store.save
        self._emit("model.switch_applied", {
            "provider_id": target.provider_id,
            "model_id": target.model_id,
            "compacted": compacted,
        })
        return SwitchResult(
            outcome=SwitchOutcome.APPLIED,
            applied_selection=target,
            compacted=compacted,
            message="下一 Turn 生效",
        )

    # ── 校验辅助 ────────────────────────────────────────

    def _validate_capability(
        self,
        metadata: ModelMetadata,
        request: SwitchRequest,
    ) -> None:
        """capability 需求由 SwitchRequest.reason 之外的构造参数传入；
        MVP 服务级固定要求 supports_tools（AgentLoop 依赖 tool calling）。"""
        if not metadata.supports_tools:
            raise RegistryError(
                "capability mismatch: 目标模型不支持 tool calling"
            )  # 由 _apply_transaction 捕获归入 REJECTED

    def _rejected(
        self,
        request: SwitchRequest,
        reason: RejectionReason,
        detail: str,
    ) -> SwitchResult:
        self._emit("model.switch_rejected", {
            "reason": reason.value, "detail": detail,
        })
        return SwitchResult(
            outcome=SwitchOutcome.REJECTED,
            rejection=reason,
            message=detail,
        )

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        self._on_event(event, dict(data))