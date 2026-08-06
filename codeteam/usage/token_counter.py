"""
Token 计数器：估算文本占用的 Token 数量。

第一版使用近似算法：Token ≈ UTF-8 字节数 / 4。（经验公式）
生产环境可替换为 tiktoken 或模型适配层的真实 tokenizer。
"""
from __future__ import annotations


class ApproximateTokenCounter:
    """近似 Token 计数器。

    英语文本平均 1 Token ≈ 4 字节（UTF-8 编码）。

    用法：
        counter = ApproximateTokenCounter()
        tokens = counter.count("def get_user(self) -> User:")
        # → 约 10
    """

    def count(self, text: str) -> int:
        """估算文本的 Token 数量。

        Args:
            text: 待估算的文本

        Returns:
            Token 数的近似值，最小为 1
        """
        if not text:
            return 0
        # UTF-8 编码后每 4 字节约等于 1 Token
        return max(1, len(text.encode("utf-8")) // 4)# 即使空字符串或极短字符串，也要返回至少 1 Token——预算计算中 0 会导致除零或误判