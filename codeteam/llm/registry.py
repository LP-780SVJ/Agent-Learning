"""codeteam.llm.registry — Provider / Model 解析层。

职责（day5 §二十四~二十八）：
- Provider ≠ Model：连接方式 vs 能力容量，两条独立轴
- ModelMetadata 以 (provider_id, model_id) 为键——同名模型经不同
  Provider 部署，window/价格/能力可能不同（window 属于部署而非模型名）
- AgentLoop 永远只拿 ModelClient Protocol；registry 不 import 任何
  具体 client 类（client_factory 由调用方注入 → 零 provider 分支）

凭证纪律（§四十二）：ProviderConfig 只存环境变量名，不存值；
API key 只活在 client 进程内存，任何序列化路径不可达。

Durable/Ephemeral 边界（Day 4 技能复用）：
- ModelSelection / ModelMetadata = Pydantic（进 session.json 与事件 payload）
- ProviderConfig = dataclass（含 Callable，绝不序列化）
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from codeteam.llm.base import ModelClient

DEFAULT_SAFETY_HEADROOM_RATIO = 0.10
"""动态预算的默认安全余量比例（day5 §十六：必须为 Output/后续
Tool Result/意外增长留空间；MVP 同步压缩取保守 10%，
周度 Benchmark 后再校准——GitHub 的 20% 是后台异步压缩场景）。"""


class RegistryError(Exception):
    """registry 层错误基类。"""


class UnknownProviderError(RegistryError):
    """selection.provider_id 未注册。"""


class UnknownModelError(RegistryError):
    """provider 已注册但 (provider, model) 组合无 metadata。"""


class ProviderCredentialError(RegistryError):
    """selection 指定的凭证环境变量不存在（不静默降级）。"""


class ModelSelection(BaseModel):
    """一次模型选择（durable：进 Session 与 turn.started 事件）。

    与 session.provider_id/model_id 对接：Session 升级为
    current_selection 后即本类型（Step 5）。
    """

    provider_id: str
    model_id: str
    reasoning_effort: str | None = None

    @field_validator("provider_id", "model_id")
    @classmethod
    def _check_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("provider_id / model_id 不能为空或纯空白")
        return stripped

    @property
    def key(self) -> tuple[str, str]:
        """metadata 字典的组合键。"""
        return (self.provider_id, self.model_id)


class ModelMetadata(BaseModel):
    """一个 (provider, model) 部署的容量/能力/价格（§二十七~二十八）。

    注意：window 属于实际部署——Gateway/Custom 端点的真实容量
    可能与模型官方标称不同，允许注册时显式修正（C5 防御）。
    """

    provider_id: str
    model_id: str

    context_window_tokens: int = Field(ge=1)
    max_output_tokens: int = Field(ge=1)

    supports_tools: bool = True
    supports_structured_output: bool = True
    supports_streaming: bool = False

    input_price_per_million: Decimal | None = None
    output_price_per_million: Decimal | None = None

    @field_validator("context_window_tokens")
    @classmethod
    def _check_output_fits(cls, value: int, info) -> int:
        # 构造期防御：max_output 必须 < context_window，
        # 否则 compute_context_budget 必然得到非正数
        return value


@dataclass(frozen=True)
class ProviderConfig:
    """Provider 连接配置（ephemeral：含 Callable，绝不序列化）。

    credential_env_name 只存名字（§四十二）；client_factory 是
    "如何建连接"的配方——Resume 时从 selection 重新调用。
    """

    provider_id: str
    client_factory: Callable[[ModelSelection], ModelClient]
    credential_env_name: str | None = None
    base_url: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def has_credential(self) -> bool:
        """凭证是否存在于当前环境（只查存在性，不读值）。"""
        if self.credential_env_name is None:
            return True  # 无凭证要求的 provider（如本地/mock）
        return self.credential_env_name in os.environ


class ProviderRegistry:
    """(provider, model) → metadata / client 的唯一解析入口。"""

    def __init__(self) -> None:
        self._providers: dict[str, ProviderConfig] = {}
        self._models: dict[tuple[str, str], ModelMetadata] = {}

    # ── 注册 ────────────────────────────────────────────

    def register_provider(
        self,
        config: ProviderConfig,
        *,
        models: tuple[ModelMetadata, ...] = (),
    ) -> None:
        """注册 provider 及其初始模型集。

        重复注册同一 provider_id 直接拒绝（配置错误 fail fast，
        而不是后注册者静默覆盖先注册者）。
        """
        if config.provider_id in self._providers:
            raise RegistryError(f"provider 已注册: {config.provider_id}")
        self._providers[config.provider_id] = config
        for metadata in models:
            self._register_model(metadata)

    def register_model(self, metadata: ModelMetadata) -> None:
        """单独补充模型（幂等语义：同键重复注册拒绝）。"""
        self._register_model(metadata)

    def _register_model(self, metadata: ModelMetadata) -> None:
        if metadata.provider_id not in self._providers:
            raise UnknownProviderError(
                f"先注册 provider 再注册模型: {metadata.provider_id}"
            )
        key = (metadata.provider_id, metadata.model_id)
        if key in self._models:
            raise RegistryError(
                f"模型已注册: {metadata.provider_id}/{metadata.model_id}"
            )
        self._models[key] = metadata

    # ── 解析 ────────────────────────────────────────────

    def has_provider(self, provider_id: str) -> bool:
        return provider_id in self._providers

    def list_selections(self) -> tuple[ModelSelection, ...]:
        """全部已注册选择（Debug/CLI 列表用）。"""
        return tuple(
            ModelSelection(provider_id=p, model_id=m)
            for (p, m) in sorted(self._models)
        )

    def metadata(self, selection: ModelSelection) -> ModelMetadata:
        """查 (provider, model) 元数据。组合缺失逐层报错。"""
        if selection.provider_id not in self._providers:
            raise UnknownProviderError(selection.provider_id)
        try:
            return self._models[selection.key]
        except KeyError as error:
            raise UnknownModelError(
                f"{selection.provider_id}/{selection.model_id}"
            ) from error

    def require_credential(self, selection: ModelSelection) -> None:
        """凭证缺失显式报错（Step 5 switch 事务的第 4 步）。"""
        config = self._require_config(selection)
        if not config.has_credential():
            raise ProviderCredentialError(
                f"凭证环境变量未设置: {config.credential_env_name}"
            )

    def build_client(self, selection: ModelSelection) -> ModelClient:
        """从 durable selection 重建 ephemeral client。

        不缓存：调用方（Turn 开始处）持引用，Turn 内 selection
        不可变（Step 5 不变量）→ client 生命周期与 Turn 对齐。
        """
        config = self._require_config(selection)
        self.metadata(selection)  # 组合必须已注册
        return config.client_factory(selection)

    def _require_config(self, selection: ModelSelection) -> ProviderConfig:
        if selection.provider_id not in self._providers:
            raise UnknownProviderError(selection.provider_id)
        return self._providers[selection.provider_id]


def compute_context_budget(
    metadata: ModelMetadata,
    *,
    fixed_overheads_tokens: int = 0,
    safety_headroom_ratio: float = DEFAULT_SAFETY_HEADROOM_RATIO,
) -> int:
    """计算动态上下文预算（day5 §十五 公式的 capacity 侧）。

        dynamic = window − max_output − headroom − fixed_overheads

    - max_output 取自 metadata（模型自己的输出上限）
    - headroom = window × ratio（§十六：为同 Turn 内的 Tool Result
      增长与意外溢出留空间，必须在 Provider 报 overflow 之前管理）
    - fixed_overheads：system/tools/instructions/task_plan 等
      本 Turn 已知固定项（由调用方用估算器算好传入；
      分层再分配交给 context/budget.TokenBudget，本函数不管分配）

    预算非正 = 配置矛盾（window 连固定开销都装不下）→ 当场抛错，
    绝不返回 0 让上游"安静地什么都不装"。

    Raises:
        RegistryError: 计算结果 ≤ 0。
    """
    headroom = int(metadata.context_window_tokens * safety_headroom_ratio)
    budget = (
        metadata.context_window_tokens
        - metadata.max_output_tokens
        - headroom
        - fixed_overheads_tokens
    )
    if budget <= 0:
        raise RegistryError(
            f"context budget 非正({budget}): window="
            f"{metadata.context_window_tokens}, max_output="
            f"{metadata.max_output_tokens}, headroom={headroom}, "
            f"fixed={fixed_overheads_tokens} —— 模型容量装不下固定开销"
        )
    return budget