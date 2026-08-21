"""W4D5：ProviderRegistry / ModelSelection / ModelMetadata 测试。

覆盖 day5 §四十六 Model 矩阵的注册与解析不变量：
- 注册并解析 Provider / Model / ModelMetadata
- ModelSelection 区分 provider_id 与 model_id（组合键）
- 同名模型经不同 Provider 部署 → 独立 metadata（window 属于部署）
- 注册顺序与重复注册的 fail-fast 语义
- 凭证纪律：只存环境变量名，绝不在 durable 层出现凭证值
- compute_context_budget：window − max_output − headroom − fixed

工程约束：全 Fake client factory，无网络、无真实 Provider API。
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from codeteam.llm.base import ModelClient
from codeteam.llm.registry import (
    DEFAULT_SAFETY_HEADROOM_RATIO,
    ModelMetadata,
    ModelSelection,
    ProviderConfig,
    ProviderCredentialError,
    ProviderRegistry,
    RegistryError,
    UnknownModelError,
    UnknownProviderError,
    compute_context_budget,
)
from codeteam.schemas.messages import Message


class _FakeClient:
    """满足 ModelClient Protocol 的最小假客户端。"""

    def __init__(self, selection: ModelSelection) -> None:
        self.selection = selection

    def complete(self, messages: list[Message]) -> str:
        return f"fake:{self.selection.model_id}"


def _factory(selection: ModelSelection) -> ModelClient:
    return _FakeClient(selection)


def _metadata(
    provider: str = "p1",
    model: str = "m1",
    window: int = 1000,
    supports_tools: bool = True,
) -> ModelMetadata:
    return ModelMetadata(
        provider_id=provider,
        model_id=model,
        context_window_tokens=window,
        max_output_tokens=100,
        supports_tools=supports_tools,
    )


def _registry(*, credential_env: str | None = None) -> ProviderRegistry:
    reg = ProviderRegistry()
    reg.register_provider(
        ProviderConfig(
            provider_id="p1",
            client_factory=_factory,
            credential_env_name=credential_env,
        ),
        models=(_metadata(),),
    )
    return reg


# ── 注册与解析 ───────────────────────────────────────────


class TestRegistration:
    def test_register_and_resolve_metadata(self) -> None:
        reg = _registry()
        metadata = reg.metadata(ModelSelection(provider_id="p1", model_id="m1"))
        assert metadata.context_window_tokens == 1000
        assert metadata.supports_tools is True

    def test_selection_key_is_provider_model_pair(self) -> None:
        """ModelSelection 区分两个轴：provider（连接方式）与
        model（能力容量），组合键定位 metadata。"""
        sel = ModelSelection(provider_id="openai", model_id="gpt-x")
        assert sel.key == ("openai", "gpt-x")
        assert sel.provider_id != sel.model_id  # 两个字段语义独立

    def test_same_model_name_different_providers_independent(self) -> None:
        """同名模型经两个 Provider 部署 → 两份独立 metadata
        （window 属于部署而非模型名，C5 防御的注册面）。"""
        reg = ProviderRegistry()
        reg.register_provider(
            ProviderConfig(provider_id="gw", client_factory=_factory),
            models=(_metadata(provider="gw", window=128_000),),
        )
        reg.register_provider(
            ProviderConfig(provider_id="local", client_factory=_factory),
            models=(_metadata(provider="local", window=32_000),),
        )
        via_gw = reg.metadata(ModelSelection(provider_id="gw", model_id="m1"))
        via_local = reg.metadata(
            ModelSelection(provider_id="local", model_id="m1")
        )
        assert via_gw.context_window_tokens == 128_000
        assert via_local.context_window_tokens == 32_000

    def test_duplicate_provider_rejected(self) -> None:
        """重复注册 fail fast，绝不静默覆盖先注册者。"""
        reg = _registry()
        with pytest.raises(RegistryError, match="已注册"):
            reg.register_provider(
                ProviderConfig(provider_id="p1", client_factory=_factory)
            )

    def test_duplicate_model_rejected(self) -> None:
        reg = _registry()
        with pytest.raises(RegistryError, match="模型已注册"):
            reg.register_model(_metadata())

    def test_model_before_provider_rejected(self) -> None:
        reg = ProviderRegistry()
        with pytest.raises(UnknownProviderError):
            reg.register_model(_metadata())

    def test_list_selections_sorted(self) -> None:
        reg = _registry()
        reg.register_model(_metadata(model="m0"))
        selections = reg.list_selections()
        assert [
            (s.provider_id, s.model_id) for s in selections
        ] == [("p1", "m0"), ("p1", "m1")]


# ── 解析失败路径 ─────────────────────────────────────────


class TestResolutionErrors:
    def test_unknown_provider(self) -> None:
        reg = _registry()
        with pytest.raises(UnknownProviderError):
            reg.metadata(ModelSelection(provider_id="nope", model_id="m1"))

    def test_unknown_model_under_known_provider(self) -> None:
        reg = _registry()
        with pytest.raises(UnknownModelError):
            reg.metadata(ModelSelection(provider_id="p1", model_id="ghost"))

    def test_blank_selection_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ModelSelection(provider_id="  ", model_id="m")
        with pytest.raises(ValidationError):
            ModelSelection(provider_id="p", model_id="")


# ── 凭证纪律：名字可存，值不可达 ─────────────────────────


class TestCredentialDiscipline:
    def test_credential_present_passes(self, monkeypatch) -> None:
        monkeypatch.setenv("P1_API_KEY", "secret-value")
        reg = _registry(credential_env="P1_API_KEY")
        reg.require_credential(
            ModelSelection(provider_id="p1", model_id="m1")
        )  # 不抛即通过

    def test_missing_credential_raises(self, monkeypatch) -> None:
        monkeypatch.delenv("P1_API_KEY", raising=False)
        reg = _registry(credential_env="P1_API_KEY")
        with pytest.raises(ProviderCredentialError, match="P1_API_KEY"):
            reg.require_credential(
                ModelSelection(provider_id="p1", model_id="m1")
            )

    def test_provider_without_credential_always_available(
        self, monkeypatch
    ) -> None:
        """无凭证要求的 provider（本地/mock）不受环境变量影响。"""
        monkeypatch.delenv("NOT_SET_ENV", raising=False)
        reg = _registry()  # credential_env_name=None
        reg.require_credential(
            ModelSelection(provider_id="p1", model_id="m1")
        )

    def test_selection_never_carries_credential_material(self) -> None:
        """durable 层（ModelSelection）只有 id 字段——API key
        任何序列化路径不可达（§四十二）。"""
        selection = ModelSelection(provider_id="p1", model_id="m1")
        dumped = selection.model_dump()
        assert set(dumped) == {
            "provider_id", "model_id", "reasoning_effort",
        }
        assert "sk-secret" not in selection.model_dump_json()
        assert "P1_API_KEY" not in dumped

    def test_provider_config_is_ephemeral_not_pydantic(self) -> None:
        """ProviderConfig 含 Callable（连接配方）→ dataclass、
        绝不进 session.json（与 durable 的 Pydantic 边界）。"""
        config = ProviderConfig(
            provider_id="p1", client_factory=_factory
        )
        assert not isinstance(config, BaseModel)
        assert callable(config.client_factory)


# ── client 重建 ──────────────────────────────────────────


class TestClientRebuild:
    def test_build_client_uses_factory_with_selection(self) -> None:
        reg = _registry()
        client = reg.build_client(ModelSelection(provider_id="p1", model_id="m1"))
        assert isinstance(client, _FakeClient)
        assert client.selection.model_id == "m1"

    def test_build_client_unknown_selection_rejected(self) -> None:
        reg = _registry()
        with pytest.raises(UnknownModelError):
            reg.build_client(ModelSelection(provider_id="p1", model_id="x"))

    def test_no_client_caching_per_turn_lifecycle(self) -> None:
        """不缓存：每次 build 新实例——client 生命周期与 Turn 对齐
        （Turn 内 selection 不可变的前提，见 test_switching）。"""
        reg = _registry()
        selection = ModelSelection(provider_id="p1", model_id="m1")
        first = reg.build_client(selection)
        second = reg.build_client(selection)
        assert first is not second


# ── Budget 公式 ──────────────────────────────────────────


class TestContextBudget:
    def test_formula_window_minus_output_minus_headroom(self) -> None:
        metadata = _metadata(window=1000)
        budget = compute_context_budget(metadata)
        assert budget == 1000 - 100 - 100  # 800

    def test_headroom_default_ratio_is_ten_percent(self) -> None:
        assert DEFAULT_SAFETY_HEADROOM_RATIO == 0.10
        budget = compute_context_budget(_metadata(window=1000))
        assert budget < 1000 - 100  # 严格小于 window − max_output

    def test_fixed_overheads_deducted(self) -> None:
        budget = compute_context_budget(
            _metadata(window=1000), fixed_overheads_tokens=250
        )
        assert budget == 800 - 250

    def test_custom_headroom_ratio(self) -> None:
        budget = compute_context_budget(
            _metadata(window=1000), safety_headroom_ratio=0.20
        )
        assert budget == 1000 - 100 - 200

    def test_non_positive_budget_raises(self) -> None:
        """window 连固定开销都装不下 → 当场报错，绝不返回 0
        让上游「安静地什么都不装」。"""
        with pytest.raises(RegistryError, match="非正"):
            compute_context_budget(
                _metadata(window=200), fixed_overheads_tokens=100
            )  # 200-100-20-100 = -20
