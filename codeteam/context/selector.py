"""
ContextSelector：选择最相关的文件进入上下文。

按相关性分数排序 + Token 预算限制 + 压缩器兜底。
"""
from __future__ import annotations

from codeteam.context.models import ContextItem, CompressionLevel
from codeteam.context.compressor import ContextCompressor
from codeteam.usage.token_counter import TokenCounter


class ContextSelector:
    """上下文选择器。

    用法：
        counter = ApproximateTokenCounter()
        compressor = ContextCompressor(counter)
        selector = ContextSelector(compressor, counter)

        items, actions = selector.select(
            candidates=candidates,   # 来自 CandidateGenerator + FileRanker
            budget_tokens=8000,
        )
    """

    def __init__(
        self,
        compressor: ContextCompressor,
        counter: TokenCounter,
    ) -> None:
        self._compressor = compressor
        self._counter = counter

    def select(
        self,
        *,
        candidates: list[ContextItem],
        budget_tokens: int,
    ) -> tuple[list[ContextItem], list[str]]:
        """选择并压缩到预算内。

        策略：
        1. 按 relevance_score 降序排列
        2. 贪心加入（优先高相关性文件）
        3. 如果超预算，调用 ContextCompressor 逐级降级

        Args:
            candidates:    候选文件列表。
            budget_tokens: Token 预算上限。

        Returns:
            (最终选中的 items, 压缩动作日志)
        """
        # 步骤 1：按相关性排序
        sorted_items = sorted(
            candidates,
            key=lambda item: (-item.relevance_score, item.path),
        )

        # 步骤 2：检查是否已超预算
        total = sum(item.token_count for item in sorted_items)

        if total <= budget_tokens:
            return sorted_items, []

        # 步骤 3：超预算 → 调用压缩器
        return self._compressor.fit_to_budget(
            items=sorted_items,
            budget_tokens=budget_tokens,
        )