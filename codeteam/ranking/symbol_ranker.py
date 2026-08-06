"""
SymbolRanker: 文件内符号排序。

在文件内部，决定哪些符号（类、函数、方法）应该优先展示在 Repo Map 中。

FileRanker 回答"哪些文件排前面"，
SymbolRanker 回答"文件内展示哪些符号"——两级排序。
"""
from __future__ import annotations

from codeteam.symbols.models import Symbol, SymbolKind


class SymbolRanker:
    """文件内符号排序器。

    用法：
        ranker = SymbolRanker()
        scored = ranker.rank(
            symbols=symbol_index.symbols_in_file("auth/service.py"),
            matched_names={"refresh_token", "UserService"},
            query_terms=["refresh", "token", "UserService"],
        )
        # scored 已按得分降序排列
    """

    # ── 权重常量 ─────────────────────────────────────────────

    _EXACT_QUALIFIED = 5.0     # 精确限定名匹配
    _EXACT_SHORT = 4.0         # 精确短名称匹配
    _PREFIX_MATCH = 2.0        # 前缀匹配
    _IS_CLASS = 1.5            # 是类定义
    _IS_FUNCTION_OR_METHOD = 1.0  # 是函数/方法
    _IS_PUBLIC = 1.0           # 公共 API（非 _ 开头）
    _PRIVATE_PENALTY = -1.0    # 私有符号惩罚（_ 开头）

    # ── 主入口 ──────────────────────────────────────────────

    def rank(
        self,
        symbols: list[Symbol],
        *,
        matched_names: set[str] | None = None,
        query_terms: list[str] | None = None,
    ) -> list[tuple[Symbol, float]]:
        """对符号列表打分并排序。

        Args:
            symbols: 一个文件中的所有符号（从 SymbolIndex.symbols_in_file() 获取）
            matched_names: RankedFile.matched_symbols——被查询精确命中的符号名
            query_terms: AnalyzedQuery 的 primary_terms——所有搜索关键词

        Returns:
            (symbol, score) 列表，按得分降序

        得分由 4 类信号加权求和：
            查询匹配（5/4/2） + 类型奖励（1.5/1） + 可见性（+1/-1）
        """
        matched = matched_names or set()
        terms = query_terms or []

        scored: list[tuple[Symbol, float]] = []

        for sym in symbols:
            score = self._score_symbol(sym, matched, terms)
            scored.append((sym, score))

        # 降序排列，同分按限定名稳定
        scored.sort(
            key=lambda item: (
                -round(item[1], 8),
                item[0].qualified_name,
            )
        )

        return scored

    # ── 评分逻辑 ─────────────────────────────────────────────

    def _score_symbol(
        self,
        sym: Symbol,
        matched_names: set[str],
        query_terms: list[str],
    ) -> float:
        """计算单个符号的得分。

        评分规则（按优先级）：
        1. 查询匹配 — 用户是否提到了这个符号
        2. 符号类型 — 类和函数比变量更有信息量
        3. 可见性 — 公共 API 优先于私有实现
        """
        score = 0.0

        # ── 第 1 层：查询匹配 ──
        score += self._query_match_score(sym, matched_names, query_terms)

        # ── 第 2 层：符号类型 ──
        score += self._kind_score(sym)

        # ── 第 3 层：可见性 ──
        score += self._visibility_score(sym)

        return score

    def _query_match_score(
        self,
        sym: Symbol,
        matched_names: set[str],
        query_terms: list[str],
    ) -> float:
        """计算查询匹配相关的得分。

        优先级：
            qualified_name 精确命中 > 短名称精确命中 > 前缀匹配
        """
        # 精确限定名匹配（5 分）：qualified_name 完整匹配
        if sym.qualified_name in matched_names:
            return self._EXACT_QUALIFIED

        # 精确短名称匹配（4 分）：name 匹配
        if sym.name in matched_names:
            return self._EXACT_SHORT

        # 前缀匹配（2 分）：任意 query_term 是符号名的前缀
        name_lower = sym.name.lower()
        for term in query_terms:
            term_lower = term.lower()
            if name_lower.startswith(term_lower):
                return self._PREFIX_MATCH

            # 也检查 qualified_name
            qn_lower = sym.qualified_name.lower()
            if qn_lower.startswith(term_lower):
                return self._PREFIX_MATCH

        return 0.0

    def _kind_score(self, sym: Symbol) -> float:
        """符号类型奖励。

        类的信息量最大 → 1.5
        函数/方法次之 → 1.0
        变量/参数 → 0（它们通常是实现细节）
        """
        if sym.kind == SymbolKind.CLASS:
            return self._IS_CLASS
        if sym.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
            return self._IS_FUNCTION_OR_METHOD
        return 0.0

    def _visibility_score(self, sym: Symbol) -> float:
        """可见性得分。

        公共 API（不以下划线开头）→ +1
        私有符号（以下划线开头）→ -1
        """
        if sym.name.startswith("_"):
            return self._PRIVATE_PENALTY
        return self._IS_PUBLIC