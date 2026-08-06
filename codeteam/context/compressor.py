"""
ContextCompressor：上下文压缩器。

当上下文超过 Token Budget 时，逐级降级 ContextItem，
优先降级「损失小、省 Token 多」的文件。

压缩降级链：
FULL_FILE → SYMBOL_BODY → SYMBOL_SIGNATURE → FILE_SUMMARY → PATH_ONLY
"""
from __future__ import annotations

import re
import math

from codeteam.context.models import (
    CompressionLevel,
    ContextItem,
)
from codeteam.usage.token_counter import TokenCounter


# 每个压缩级别的信息权重（用于计算相关性损失）
_LEVEL_WEIGHTS: dict[CompressionLevel, float] = {
    CompressionLevel.FULL_FILE: 1.0,
    CompressionLevel.SYMBOL_BODY: 0.8,
    CompressionLevel.SYMBOL_SIGNATURE: 0.5,
    CompressionLevel.FILE_SUMMARY: 0.2,
    CompressionLevel.PATH_ONLY: 0.05,
}

# 降级链的顺序
_LEVEL_ORDER: list[CompressionLevel] = [
    CompressionLevel.FULL_FILE,
    CompressionLevel.SYMBOL_BODY,
    CompressionLevel.SYMBOL_SIGNATURE,
    CompressionLevel.FILE_SUMMARY,
    CompressionLevel.PATH_ONLY,
]


class ContextCompressor:
    """上下文压缩器。

    用法：
        counter = ApproximateTokenCounter()
        compressor = ContextCompressor(counter)
        compressed, actions = compressor.fit_to_budget(
            items=[item1, item2, item3],
            budget_tokens=5000,
        )
        for action in actions:
            print(action)  # 查看压缩日志
    """

    def __init__(self, counter: TokenCounter) -> None:
        self._counter = counter

    # ── 主入口 ────────────────────────────────────────────────

    def fit_to_budget(
        self,
        *,
        items: list[ContextItem],
        budget_tokens: int,
    ) -> tuple[list[ContextItem], list[str]]:
        """压缩 items 直到总 Token ≤ budget_tokens。

        选择策略：降级代价 = 相关性损失 / 节省 Token 数。
        每次只降级一个 item 的一级。

        Args:
            items:         待压缩的 ContextItem 列表。
            budget_tokens: Token 预算上限。

        Returns:
            (压缩后的 items, 压缩动作日志)
        """
        actions: list[str] = []

        while self._total_tokens(items) > budget_tokens:
            # 选降级代价最小的 item
            candidate = self._choose_downgrade(items)
            if candidate is None:
                actions.append("所有 item 已达到最低压缩级别，无法继续压缩")
                break

            next_level = self._next_level(candidate.current_level)
            if next_level is None:
                break

            before_tokens = candidate.token_count

            # 压缩
            compressed = self.compress_item(
                item=candidate,
                target_level=next_level,
            )

            # 替换
            self._replace_item(items, candidate, compressed)

            actions.append(
                f"{candidate.path}: "
                f"{candidate.current_level.value} → {next_level.value}; "
                f"{before_tokens} → {compressed.token_count} tokens"
            )

        return items, actions

    # ── 压缩单个 item ─────────────────────────────────────────

    def compress_item(
        self,
        *,
        item: ContextItem,
        target_level: CompressionLevel,
    ) -> ContextItem:
        """将一个 ContextItem 压缩到目标级别。

        返回新的 ContextItem（原 item 不变，frozen=True）。
        """
        content = item.content

        if target_level == CompressionLevel.SYMBOL_BODY:
            content = self._to_symbol_body(item)
        elif target_level == CompressionLevel.SYMBOL_SIGNATURE:
            content = self._to_symbol_signature(item)
        elif target_level == CompressionLevel.FILE_SUMMARY:
            content = self._to_file_summary(item)
        elif target_level == CompressionLevel.PATH_ONLY:
            content = self._to_path_only(item)

        return ContextItem(
            path=item.path,
            relevance_score=item.relevance_score,
            current_level=target_level,
            minimum_level=item.minimum_level,
            content=content,
            token_count=self._counter.count_text(content),
            selected_symbols=item.selected_symbols,
            reason=item.reason,
            file_hash=item.file_hash,
            start_line=item.start_line,
            end_line=item.end_line,
        )

    # ── 压缩转换实现 ──────────────────────────────────────────

    @staticmethod
    def _to_symbol_body(item: ContextItem) -> str:
        """FULL_FILE → SYMBOL_BODY：只保留选中符号的完整实现。

        第一版简化实现：保留整个文件内容，但去掉空行和注释。
        生产环境应使用 AST/Tree-sitter 精确提取符号范围。
        """
        if not item.selected_symbols:
            # 没有指定选中符号 → 保留前 60% 的内容
            lines = item.content.splitlines()
            cutoff = max(1, int(len(lines) * 0.6))
            return "\n".join(lines[:cutoff])

        # 对每个选中的符号，提取它的定义块
        kept_lines: list[str] = []
        for symbol_name in item.selected_symbols:
            block = ContextCompressor._extract_block(
                item.content, symbol_name
            )
            if block:
                kept_lines.append(block)

        if kept_lines:
            return "\n\n".join(kept_lines)
        # 提取失败 → 保留内容的前 40%
        lines = item.content.splitlines()
        cutoff = max(1, int(len(lines) * 0.4))
        return "\n".join(lines[:cutoff])

    @staticmethod
    def _to_symbol_signature(item: ContextItem) -> str:
        """SYMBOL_BODY → SYMBOL_SIGNATURE：只保留签名行。

        提取 class/def 行和紧接的 docstring。
        不包含函数实现体。
        """
        lines = item.content.splitlines()
        signatures: list[str] = []
        in_signature = False

        for i, line in enumerate(lines):
            stripped = line.strip()

            # 类或函数定义
            if stripped.startswith("class ") or stripped.startswith("def "):
                signatures.append(line)
                in_signature = True
                continue

            # 签名后的 docstring（紧跟的 """..."""）
            if in_signature and ('"""' in stripped or "'''" in stripped):
                signatures.append(line)
                if stripped.count('"""') == 2 or stripped.count("'''") == 2:
                    in_signature = False
                continue

            # 签名后的装饰器（下一行的 @）
            if in_signature and stripped.startswith("@"):
                in_signature = False
                continue

            # 进入实现体（非空非注释行）
            if in_signature and stripped and not stripped.startswith("#"):
                signatures.append("    ...")
                in_signature = False

        if signatures:
            return "\n".join(signatures)
        # 提取失败 → 只保留前几行
        return "\n".join(lines[:5]) + "\n    ..."

    @staticmethod
    def _to_file_summary(item: ContextItem) -> str:
        """SYMBOL_SIGNATURE → FILE_SUMMARY：确定性摘要。

        由现有数据字段生成，不调用 LLM。
        生产环境可接入 SymbolIndex 和 ImportGraph。
        """
        parts = [f"{item.path}"]
        if item.reason:
            parts.append(f"Role: {item.reason}")
        if item.selected_symbols:
            parts.append(f"Symbols: {', '.join(item.selected_symbols[:8])}")
            if len(item.selected_symbols) > 8:
                parts[-1] += f" (+{len(item.selected_symbols) - 8} more)"
        return "\n".join(parts)

    @staticmethod
    def _to_path_only(item: ContextItem) -> str:
        """FILE_SUMMARY → PATH_ONLY：仅路径。"""
        return item.path

    # ── 降级选择 ──────────────────────────────────────────────

    def _choose_downgrade(
        self, items: list[ContextItem]
    ) -> ContextItem | None:
        """选择降级代价最小的 ContextItem。

        代价 = 相关性损失 / 预计节省 Token 数。

        相关性损失 = (当前级别权重 - 下一级别权重) × relevance_score
        """
        best: ContextItem | None = None
        best_cost = float("inf")

        for item in items:
            next_level = self._next_level(item.current_level)
            if next_level is None:
                continue  # 已经到最低级别

            # 不能被压缩到 minimum_level 以下
            level_rank = _LEVEL_ORDER.index
            if level_rank(next_level) > level_rank(item.minimum_level):
                continue

            # 计算损失
            current_weight = _LEVEL_WEIGHTS[item.current_level]
            next_weight = _LEVEL_WEIGHTS[next_level]
            relevance_loss = (current_weight - next_weight) * item.relevance_score

            # 预计节省的 Token（粗略估算）
            if item.current_level == CompressionLevel.FULL_FILE:
                estimated_next_tokens = max(1, item.token_count // 3)
            elif item.current_level == CompressionLevel.SYMBOL_BODY:
                estimated_next_tokens = max(1, item.token_count // 3)
            elif item.current_level == CompressionLevel.SYMBOL_SIGNATURE:
                estimated_next_tokens = max(1, item.token_count // 4)
            else:
                estimated_next_tokens = max(1, item.token_count // 5)

            saved = item.token_count - estimated_next_tokens
            if saved <= 0:
                continue

            cost = relevance_loss / saved

            if cost < best_cost:
                best_cost = cost
                best = item

        return best

    # ── 工具方法 ──────────────────────────────────────────────

    @staticmethod
    def _next_level(
        level: CompressionLevel,
    ) -> CompressionLevel | None:
        """获取下一个压缩级别（降一级）。

        >>> _next_level(FULL_FILE)
        CompressionLevel.SYMBOL_BODY
        >>> _next_level(PATH_ONLY)
        None
        """
        try:
            idx = _LEVEL_ORDER.index(level)
            return _LEVEL_ORDER[idx + 1]
        except IndexError:
            return None

    @staticmethod
    def _total_tokens(items: list[ContextItem]) -> int:
        """计算所有 item 的总 Token 数。"""
        return sum(item.token_count for item in items)

    @staticmethod
    def _replace_item(
        items: list[ContextItem],
        old: ContextItem,
        new: ContextItem,
    ) -> None:
        """在列表中原地替换一个 ContextItem。"""
        for i, item in enumerate(items):
            if item is old:
                items[i] = new
                return

    @staticmethod
    def _extract_block(
        content: str, symbol_name: str
    ) -> str | None:
        """从 Python 源码中提取一个 top-level 符号的定义块。

        使用简单的正则方法（第一版简化实现）。
        生产环境应使用 AST 精确定位。
        """
        # 匹配 class/def 开头，直到下一个同缩进级别的 class/def
        pattern = re.compile(
            rf'^((?:class|def)\s+{re.escape(symbol_name)}\b.*?(?=^[^ \t#\n]|\Z))',
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(content)
        return match.group(1).strip() if match else None