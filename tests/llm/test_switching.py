"""W4D5：Model Switch 事务 + Turn Boundary 测试（day5 §四十六 Model 矩阵）。

覆盖的不变量（14 项矩阵中 mapper/resume 之外的 11 项 +
架构度量，429 归一化见 test_error_mapper.py）：
- Provider A / Provider B 各自正常运行（turn → client → complete）
- invalid provider / invalid model / missing credential /
  missing tool capability 切换失败 → REJECTED 且旧 selection 保留
- 小窗口模型切换 → compat_check（压缩钩子）先行；压后仍放不下 → 拒绝
- Turn 内 selection 不可变；mid-turn switch → QUEUED
- Turn 结束（boundary）才 drain 队列；下一 Turn 用新模型
- per-turn provider/model/tokens/cost 落事件（S4 usage 归因）
- persist hook 在生效时被调用（durable 同步）
- resume：从 durable (provider_id, model_id) 重建 selection 并验证；
  显式 override 走完整事务，失败不动 session selection
- 架构度量（A4）：AgentLoop / Orchestrator 零 provider 分支

W4D6 B11 追加：turn.completed 的 per-turn 计量（tokens/cost）。

工程约束：全 Fake client/事件接收器，无网络、无 sleep、无 skip。
"""
from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from codeteam.llm.base import ModelClient, ModelResponse
from codeteam.llm.registry import (
    ModelMetadata,
    ModelSelection,
    ProviderConfig,
    ProviderRegistry,
    RegistryError,
)
from codeteam.llm.switching import (
    ModelSwitchService,
    RejectionReason,
    SwitchOutcome,
    SwitchRequest,
    SwitchResult,
    TurnBoundaryQueue,
)
from codeteam.schemas.messages import Message


class _FakeClient:
    def __init__(self, selection: ModelSelection, tag: str) -> None:
        self.selection = selection
        self.tag = tag

    def complete(self, messages: list[Message]) -> str:
        return f"{self.tag}:{self.selection.model_id}"


class _RecordingEvents:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def __call__(self, event_type: str, data: dict) -> None:
        self.events.append((event_type, dict(data)))

    def of(self, event_type: str) -> list[dict]:
        return [d for t, d in self.events if t == event_type]


def _build_registry(*, credential_env: str | None = None) -> ProviderRegistry:
    reg = ProviderRegistry()

    def make_factory(tag: str):
        def factory(selection: ModelSelection) -> _FakeClient:
            return _FakeClient(selection, tag)
        return factory

    reg.register_provider(
        ProviderConfig(
            provider_id="prov-a",
            client_factory=make_factory("A"),
            credential_env_name=credential_env,
        ),
        models=(
            ModelMetadata(
                provider_id="prov-a", model_id="model-a",
                context_window_tokens=8000, max_output_tokens=500,
            ),
            ModelMetadata(
                provider_id="prov-a", model_id="model-a-notools",
                context_window_tokens=8000, max_output_tokens=500,
                supports_tools=False,
            ),
        ),
    )
    reg.register_provider(
        ProviderConfig(provider_id="prov-b", client_factory=make_factory("B")),
        models=(
            ModelMetadata(
                provider_id="prov-b", model_id="model-b-small",
                context_window_tokens=2000, max_output_tokens=200,
            ),
        ),
    )
    return reg


def _service(
    reg: ProviderRegistry | None = None,
    *,
    compat_check=None,
    persist=None,
) -> tuple[ModelSwitchService, _RecordingEvents]:
    events = _RecordingEvents()
    service = ModelSwitchService(
        reg or _build_registry(),
        on_event=events,
        compat_check=compat_check,
        persist=persist,
    )
    return service, events


def _sel(provider: str, model: str) -> ModelSelection:
    return ModelSelection(provider_id=provider, model_id=model)


def _switch(service: ModelSwitchService, target: ModelSelection) -> SwitchResult:
    return service.request_switch(SwitchRequest(target=target))


def _rejection(result: SwitchResult) -> RejectionReason:
    assert result.rejection is not None
    return result.rejection


# ── 双 Provider 正常运行 ─────────────────────────────────


class TestBothProvidersRun:
    def test_provider_a_turn_completes(self) -> None:
        service, events = _service()
        with service.turn(_sel("prov-a", "model-a")) as client:
            reply = client.complete([Message(role="user", content="hi")])
        assert reply == "A:model-a"
        started = events.of("turn.started")
        assert started[0]["provider_id"] == "prov-a"
        assert started[0]["model_id"] == "model-a"

    def test_provider_b_turn_completes(self) -> None:
        service, _ = _service()
        with service.turn(_sel("prov-b", "model-b-small")) as client:
            reply = client.complete([Message(role="user", content="hi")])
        assert reply == "B:model-b-small"

    def test_turn_events_carry_selection_for_attribution(self) -> None:
        """S4：每 Turn 记录 provider/model——usage/cost 归因的依据。"""
        service, events = _service()
        with service.turn(_sel("prov-a", "model-a")):
            pass
        with service.turn(_sel("prov-b", "model-b-small")):
            pass
        started = events.of("turn.started")
        assert [ (e["provider_id"], e["model_id"]) for e in started ] == [
            ("prov-a", "model-a"),
            ("prov-b", "model-b-small"),
        ]
        completed = events.of("turn.completed")
        assert len(completed) == 2
        assert completed[0]["turn_id"] != completed[1]["turn_id"]

    def test_nested_turn_rejected(self) -> None:
        """同一时刻只允许一个活跃 Turn（嵌套 = 状态机错误）。"""
        service, _ = _service()
        with (
            service.turn(_sel("prov-a", "model-a")),
            pytest.raises(RegistryError, match="嵌套"),
            service.turn(_sel("prov-b", "model-b-small")),
        ):
            pass


# ── 切换失败矩阵：REJECTED 且旧 selection 保留 ──────────


class TestSwitchRejections:
    def _seed(self, service: ModelSwitchService) -> None:
        """先成功应用一个 selection 作为「旧值」。"""
        ok = _switch(service, _sel("prov-a", "model-a"))
        assert ok.outcome is SwitchOutcome.APPLIED

    def test_invalid_provider_rejected_old_kept(self) -> None:
        service, events = _service()
        self._seed(service)
        result = _switch(service, _sel("prov-ghost", "model-a"))
        assert result.outcome is SwitchOutcome.REJECTED
        assert _rejection(result).value == "unknown_provider"
        assert service.current_selection == _sel("prov-a", "model-a")
        assert events.of("model.switch_rejected")

    def test_invalid_model_rejected_old_kept(self) -> None:
        service, _ = _service()
        self._seed(service)
        result = _switch(service, _sel("prov-a", "model-ghost"))
        assert result.outcome is SwitchOutcome.REJECTED
        assert _rejection(result).value == "unknown_model"
        assert service.current_selection == _sel("prov-a", "model-a")

    def test_missing_credential_rejected_old_kept(self, monkeypatch) -> None:
        monkeypatch.delenv("PROV_A_KEY", raising=False)
        service, _ = _service(
            _build_registry(credential_env="PROV_A_KEY")
        )
        # turn() 构建旧 client 不做凭证闸门（凭证只在 switch 事务验证）
        with service.turn(_sel("prov-a", "model-a")):
            pass
        result = _switch(service, _sel("prov-a", "model-a-notools"))
        assert result.outcome is SwitchOutcome.REJECTED
        assert _rejection(result).value == "missing_credential"
        assert service.current_selection == _sel("prov-a", "model-a")

    def test_capability_mismatch_rejected_old_kept(self) -> None:
        """不支持 tool calling 的模型不能接管 AgentLoop。
        （修复回归：曾未捕获 RegistryError 直接抛出。）"""
        service, _ = _service()
        self._seed(service)
        result = _switch(service, _sel("prov-a", "model-a-notools"))
        assert result.outcome is SwitchOutcome.REJECTED
        assert _rejection(result).value == "capability_mismatch"
        assert service.current_selection == _sel("prov-a", "model-a")

    def test_rejection_events_emitted(self) -> None:
        service, events = _service()
        _switch(service, _sel("prov-ghost", "x"))
        requested = events.of("model.switch_requested")
        rejected = events.of("model.switch_rejected")
        assert requested and rejected
        assert rejected[0]["reason"] == "unknown_provider"


# ── 小窗口：先压缩，压后仍超 → 拒绝 ─────────────────────


class TestContextCompatOnSwitch:
    def test_compact_hook_invoked_before_applying(self) -> None:
        """切到小窗口模型：compat_check（压缩钩子）先执行，
        通过后才 APPLIED——压缩是切换事务的一步，不是事后补救。"""
        calls: list[ModelSelection] = []

        def compat(target: ModelSelection) -> bool:
            calls.append(target)
            return True  # 调用方已完成压缩且放得下

        service, _ = _service(compat_check=compat)
        result = _switch(service, _sel("prov-b", "model-b-small"))
        assert result.outcome is SwitchOutcome.APPLIED
        assert calls == [_sel("prov-b", "model-b-small")]

    def test_still_overflow_after_compact_rejects(self) -> None:
        """压缩后仍放不下 → 拒绝切换，旧 selection 保留
        （绝不让下一 Turn 撞 context overflow）。"""

        def compat(target: ModelSelection) -> bool:
            # 大窗口模型无需压缩；小窗口模型压缩后仍超
            return target.model_id != "model-b-small"

        service, _ = _service(compat_check=compat)
        seeded = _switch(service, _sel("prov-a", "model-a"))
        assert seeded.outcome is SwitchOutcome.APPLIED
        result = _switch(service, _sel("prov-b", "model-b-small"))
        assert result.outcome is SwitchOutcome.REJECTED
        assert _rejection(result).value == "context_still_overflow"
        assert service.current_selection == _sel("prov-a", "model-a")

    def test_no_compat_check_means_unchecked(self) -> None:
        """未注入压缩钩子 = 调用方声明无兼容性要求（MVP 语义），
        切换直接生效。"""
        service, _ = _service()
        result = _switch(service, _sel("prov-b", "model-b-small"))
        assert result.outcome is SwitchOutcome.APPLIED


# ── Turn Boundary：mid-turn 排队，boundary 生效 ──────────


class TestTurnBoundary:
    def test_midturn_switch_is_queued_not_applied(self) -> None:
        """§三十二核心不变量：Turn 内 selection 不可变——
        mid-turn 请求只入队，current_selection 立刻不变。"""
        service, events = _service()
        with service.turn(_sel("prov-a", "model-a")) as client:
            mid = _switch(service, _sel("prov-b", "model-b-small"))
            assert mid.outcome is SwitchOutcome.QUEUED
            assert service.current_selection == _sel("prov-a", "model-a")
            # 当前 Turn 继续用旧 client 完成
            assert client.complete(
                [Message(role="user", content="x")]
            ) == "A:model-a"
        # boundary 已 drain：排队请求在 Turn 结束后生效
        assert service.current_selection == _sel("prov-b", "model-b-small")
        assert events.of("model.switch_applied")

    def test_queued_switch_applied_at_boundary(self) -> None:
        """Turn 结束才处理队列 → 生效事件 → 下一 Turn 用新模型。"""
        service, events = _service()
        with service.turn(_sel("prov-a", "model-a")):
            _switch(service, _sel("prov-b", "model-b-small"))

        assert service.current_selection == _sel("prov-b", "model-b-small")
        # boundary 生效发两条事件：事务本身的 switch_applied +
        # drain 层的带 queued 标记版本（调用方无需同步等待）
        applied = events.of("model.switch_applied")
        assert applied
        assert all(e["provider_id"] == "prov-b" for e in applied)
        assert any(e.get("queued") is True for e in applied)

        with service.turn(service.current_selection) as client:
            assert client.complete(
                [Message(role="user", content="x")]
            ) == "B:model-b-small"

    def test_queue_is_fifo(self) -> None:
        queue = TurnBoundaryQueue()
        first = SwitchRequest(target=_sel("p", "m1"))
        second = SwitchRequest(target=_sel("p", "m2"))
        queue.enqueue(first)
        queue.enqueue(second)
        assert len(queue) == 2
        assert queue.drain_one() is first
        assert queue.drain_one() is second
        assert queue.drain_one() is None

    def test_exception_inside_turn_still_drains_and_completes(self) -> None:
        """Turn 内异常不能吞掉 turn.completed 与 boundary 处理
        （finally 语义）。"""
        service, events = _service()
        with pytest.raises(RuntimeError), service.turn(
            _sel("prov-a", "model-a")
        ):
            raise RuntimeError("model blew up mid-turn")
        assert len(events.of("turn.completed")) == 1
        # 异常 Turn 结束后 service 可继续开新 Turn
        with service.turn(_sel("prov-a", "model-a")):
            pass


# ── persist hook：生效即落盘 ─────────────────────────────


class TestPersistHook:
    def test_applied_switch_persists_selection(self) -> None:
        persisted: list[ModelSelection] = []
        service, _ = _service(persist=persisted.append)
        _switch(service, _sel("prov-b", "model-b-small"))
        assert persisted == [_sel("prov-b", "model-b-small")]

    def test_rejected_switch_never_persists(self) -> None:
        persisted: list[ModelSelection] = []
        service, _ = _service(persist=persisted.append)
        _switch(service, _sel("prov-ghost", "x"))
        assert persisted == []


# ── B11：turn.completed 的 per-turn 计量（W4D6 Step 1）──


class _TokenReportingClient:
    """返回 ModelResponse 的假 client（tokens 非零）。"""

    def __init__(self, *, input_tokens: int, output_tokens: int) -> None:
        self._input = input_tokens
        self._output = output_tokens

    def complete(self, messages: list[Message]) -> ModelResponse:
        return ModelResponse(
            content="ok",
            model="metered-fake",
            input_tokens=self._input,
            output_tokens=self._output,
        )


class _RaisingClient:
    """complete 必炸的假 client（失败 Turn 归因）。"""

    def complete(self, messages: list[Message]) -> str:
        raise RuntimeError("model blew up")


def _metered_registry(
    *,
    input_price: Decimal | None,
    output_price: Decimal | None,
    factory=None,
) -> ProviderRegistry:
    reg = ProviderRegistry()
    metadata = ModelMetadata(
        provider_id="p", model_id="m",
        context_window_tokens=8000, max_output_tokens=500,
    )
    if input_price is not None and output_price is not None:
        metadata = metadata.model_copy(update={
            "input_price_per_million": input_price,
            "output_price_per_million": output_price,
        })
    reg.register_provider(
        ProviderConfig(
            provider_id="p",
            client_factory=(
                cast(Callable[[ModelSelection], ModelClient], factory)
                if factory is not None
                else cast(
                    Callable[[ModelSelection], ModelClient],
                    lambda sel: _TokenReportingClient(
                        input_tokens=1500, output_tokens=300,
                    ),
                )
            ),
        ),
        models=(metadata,),
    )
    return reg


class TestTurnUsageAccounting:
    """B11：tokens 只在响应返回后可知 → Turn 边界是唯一计量点。"""

    def test_completed_carries_tokens_and_cost(self) -> None:
        """ModelResponse 形态 + 已配置价格 → 四字段齐全，cost 精确。"""
        events = _RecordingEvents()
        service = ModelSwitchService(
            _metered_registry(
                input_price=Decimal("0.15"),
                output_price=Decimal("0.60"),
            ),
            on_event=events,
        )
        with service.turn(_sel("p", "m")) as client:
            client.complete([Message(role="user", content="hi")])

        completed = events.of("turn.completed")[0]
        assert completed["input_tokens"] == 1500
        assert completed["output_tokens"] == 300
        assert completed["model_calls"] == 1
        # 1500/1e6×0.15 + 300/1e6×0.60 = 0.000405（Decimal 精确后转 float）
        assert completed["cost_usd"] == pytest.approx(0.000405)

    def test_multiple_calls_accumulate(self) -> None:
        """一个 Turn 多次 complete → 计量是累计语义（repair 场景）。"""
        events = _RecordingEvents()
        service = ModelSwitchService(
            _metered_registry(
                input_price=Decimal("0.15"),
                output_price=Decimal("0.60"),
            ),
            on_event=events,
        )
        with service.turn(_sel("p", "m")) as client:
            client.complete([Message(role="user", content="a")])
            client.complete([Message(role="user", content="b")])

        completed = events.of("turn.completed")[0]
        assert completed["input_tokens"] == 3000
        assert completed["output_tokens"] == 600
        assert completed["model_calls"] == 2

    def test_str_only_client_degrades_honestly(self) -> None:
        """返 str 的 client（Protocol 声明形态）+ 无价格 →
        tokens 0、calls 1、cost None——不伪造数据。"""
        service, events = _service()  # 既有工厂：str client + 无价格
        with service.turn(_sel("prov-a", "model-a")) as client:
            client.complete([Message(role="user", content="x")])

        completed = events.of("turn.completed")[0]
        assert completed["input_tokens"] == 0
        assert completed["output_tokens"] == 0
        assert completed["model_calls"] == 1
        assert completed["cost_usd"] is None

    def test_no_pricing_yields_none_not_zero(self) -> None:
        """tokens 已报但价格未配置 → cost None（"不知道"≠"免费"）。"""
        events = _RecordingEvents()
        service = ModelSwitchService(
            _metered_registry(input_price=None, output_price=None),
            on_event=events,
        )
        with service.turn(_sel("p", "m")) as client:
            client.complete([Message(role="user", content="x")])

        completed = events.of("turn.completed")[0]
        assert completed["input_tokens"] == 1500
        assert completed["cost_usd"] is None

    def test_failed_turn_still_attributed(self) -> None:
        """Turn 内异常 → completed 仍发：calls=1（尝试即计数）、
        tokens=0；价格在但 0 tokens → cost 0.0（数学事实，非伪装）。"""
        events = _RecordingEvents()
        service = ModelSwitchService(
            _metered_registry(
                input_price=Decimal("0.15"),
                output_price=Decimal("0.60"),
                factory=lambda sel: _RaisingClient(),
            ),
            on_event=events,
        )
        with (
            pytest.raises(RuntimeError),
            service.turn(_sel("p", "m")) as client,
        ):
            client.complete([Message(role="user", content="x")])

        completed = events.of("turn.completed")[0]
        assert completed["model_calls"] == 1
        assert completed["input_tokens"] == 0
        assert completed["output_tokens"] == 0
        assert completed["cost_usd"] == 0.0


# ── resume：durable 重建与显式 override ──────────────────


class TestResumeSelection:
    """resume 语义在 registry/switching 层的表达：
    - 无 override：用 session 记录的 (provider_id, model_id) 重建
      selection 并验证（registry 是唯一解析入口）
    - 显式 override：走完整 switch 事务；失败不动 session selection

    注：SessionService.resume 的完整接线（读 session.json 字段后调
    用本层）属 Day 6 CLI 集成，此处覆盖可复用的核心判定。"""

    def test_resume_without_override_restores_session_selection(self) -> None:
        reg = _build_registry()
        # durable session 只存这两个 id（session.provider_id/model_id）
        durable = ("prov-a", "model-a")
        selection = ModelSelection(
            provider_id=durable[0], model_id=durable[1]
        )
        metadata = reg.metadata(selection)  # 验证通过 = 可恢复
        assert metadata.context_window_tokens == 8000

    def test_resume_with_override_validated_before_apply(self) -> None:
        service, _ = _service()
        _switch(service, _sel("prov-a", "model-a"))
        # 合法 override → 生效
        ok = _switch(service, _sel("prov-b", "model-b-small"))
        assert ok.outcome is SwitchOutcome.APPLIED
        # 非法 override → 拒绝且 session selection 不动
        bad = _switch(service, _sel("prov-a", "model-ghost"))
        assert bad.outcome is SwitchOutcome.REJECTED
        assert service.current_selection == _sel("prov-b", "model-b-small")

    def test_corrupt_durable_ids_rejected_at_rebuild(self) -> None:
        """session.json 里的 id 已不在 registry（provider 下线）→
        重建即失败，绝不静默换模型（S5）。"""
        reg = _build_registry()
        with pytest.raises(RegistryError):
            reg.metadata(ModelSelection(provider_id="prov-z", model_id="x"))


# ── 架构度量（A4）：零 provider 分支 ──────────────────────


class TestProviderNeutralArchitecture:
    """DD-W4-D5-02 的静态证据：Agent Runtime 核心链路
    （AgentLoop / Orchestrator / RepairLoop / Planner / Verification）
    不得出现 provider 特定分支或 provider id 字面量——新增 Provider
    = 新增 adapter（openai_compatible.py / mapper），零 core 改动。"""

    _CORE_FILES = (
        "codeteam/agent_loop.py",
        "codeteam/agent/orchestrator.py",
        "codeteam/repair/loop.py",
        "codeteam/planning/planner.py",
        "codeteam/verification/service.py",
    )

    def test_core_runtime_has_no_provider_branches(self) -> None:
        root = Path(__file__).parents[2]
        forbidden_literals = (
            '"openai"', "'openai'", '"anthropic"', "'anthropic'",
            "provider_id ==", "provider == ",
        )
        for rel in self._CORE_FILES:
            source = (root / rel).read_text(encoding="utf-8")
            for literal in forbidden_literals:
                assert literal not in source, (
                    f"{rel} 出现 provider 特定逻辑: {literal!r}"
                )

    def test_core_runtime_depends_only_on_client_protocol(self) -> None:
        """AgentLoop 对 llm 的依赖仅限 base 契约层（ModelResponse/
        ModelClient Protocol）——具体实现（mock/openai_compatible/
        registry/switching/error_mapper）零 import，client 由调用方注入。"""
        root = Path(__file__).parents[2]
        agent_loop = (
            root / "codeteam" / "agent_loop.py"
        ).read_text(encoding="utf-8")
        allowed_prefix = "from codeteam.llm.base import"
        llm_imports = [
            line.strip()
            for line in agent_loop.splitlines()
            if line.strip().startswith("from codeteam.llm")
        ]
        assert llm_imports, "agent_loop 应显式依赖 llm.base 契约层"
        assert all(
            imp.startswith(allowed_prefix) for imp in llm_imports
        ), llm_imports
