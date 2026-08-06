"""
TokenBudget: Token 预算管理器。

回答两个问题：
1. 当前已用多少 Token？
2. 再加一个新条目会不会超预算？
"""
from __future__ import annotations

from codeteam.usage.token_counter import ApproximateTokenCounter


class TokenBudget:
    """Token 预算管理器。

    用法：
        budget = TokenBudget(limit=1024)
        budget.can_add("新文本")  # → True/False
        budget.add("已接受的文本")
    """

    def __init__(self, limit: int = 1024) -> None:
        """初始化预算。

        Args:
            limit: Token 上限（默认 1024）
        """
        self.limit = limit
        self._counter = ApproximateTokenCounter()
        self._used = 0

    @property
    def used(self) -> int:
        return self._used

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self._used)

    def count(self, text: str) -> int:
        """估算文本的 Token 数。"""
        return self._counter.count(text)

    def can_add(self, text: str) -> bool:
        """判断加入 text 后是否仍不超预算。"""
        estimated = self.count(text)
        return (self._used + estimated) <= self.limit

    def add(self, text: str) -> None:
        """记录已使用的 Token。"""
        self._used += self.count(text)

    def reset(self) -> None:
        """重置计数器（用于压缩后重新构建）。"""
        self._used = 0