"""
RepoMapBuilder: 贪心构建 Repo Map。

流程：
    按文件排名依次尝试加入
    → 先以 SIGNATURE 级别展示
    → 超预算 → 压缩到 NAME_ONLY → 仍超 → 仅路径 → 仍超 → 跳过
    → 累计 Token ≤ budget_tokens
"""
from __future__ import annotations

from codeteam.ranking.models import RankedFile
from codeteam.symbols.index import SymbolIndex
from codeteam.symbols.models import SymbolKind
from codeteam.repomap.models import (
    RepoMap,
    RepoMapFile,
    RepoMapSymbol,
    SymbolRepresentation,
)
from codeteam.repomap.budget import TokenBudget
from codeteam.repomap.compressor import compress_entry
from codeteam.repomap.renderer import RepoMapRenderer


# 每个文件最多展示的符号数
_MAX_SYMBOLS_PER_FILE = 8


class RepoMapBuilder:
    """贪心构建 Repo Map。

    用法：
        builder = RepoMapBuilder(
            renderer=RepoMapRenderer(),
            token_counter=...,
            budget_tokens=1024,
        )
        repo_map = builder.build(
            ranked_files=ranked,
            symbol_index=si,
            query="修复 refresh token",
            mode="query",
        )
    """

    def __init__(
        self,
        *,
        renderer: RepoMapRenderer,
        budget_tokens: int = 1024,
    ) -> None:
        self.renderer = renderer
        self.budget_tokens = budget_tokens

    # ── 主入口 ───────────────────────────────────────────────

    def build(
        self,
        *,
        ranked_files: list[RankedFile],
        symbol_index: SymbolIndex,
        query: str | None = None,
        mode: str = "query",
    ) -> RepoMap:
        """构建 Repo Map。

        Args:
            ranked_files: FileRanker 排序后的文件列表
            symbol_index: 符号索引（用于提取每个文件的符号）
            query: 用户查询（global 模式为 None）
            mode: "global" 或 "query"

        Returns:
            完整的 RepoMap，其中 used_tokens 已填入实际值
        """
        budget = TokenBudget(limit=self.budget_tokens)

        # 构建 header
        header = self._render_header(mode, query)
        budget.add(header)

        selected: list[RepoMapFile] = []
        omitted_files = 0

        for ranked in ranked_files:
            # 提取并排序该文件的符号
            symbols = self._select_symbols(
                ranked.path, ranked, symbol_index
            )

            # 构建初始条目（SIGNATURE 级别）
            reasons = [
                e.reason
                for e in ranked.evidence[:3]  # 只取前 3 条
            ]
            entry = RepoMapFile(
                path=ranked.path,
                file_score=ranked.final_score,
                reasons=reasons,
                symbols=symbols,
            )

            # 尝试加入（逐级压缩）
            accepted = self._fit_entry(
                budget, selected, entry, mode, query
            )

            if accepted:
                selected.append(entry)
            else:
                omitted_files += 1

        # 构建 footer
        footer = self._render_footer(omitted_files)
        budget.add(footer)

        # 汇总
        return RepoMap(
            mode=mode,
            query=query,
            budget_tokens=self.budget_tokens,
            used_tokens=budget.used,
            files=selected,
            omitted_file_count=omitted_files,
            truncated=omitted_files > 0,
        )

    # ── 符号选择 ─────────────────────────────────────────────

    @staticmethod
    def _select_symbols(
        file_path: str,
        ranked: RankedFile,
        symbol_index: SymbolIndex,
    ) -> list[RepoMapSymbol]:
        """从文件中选取要展示的符号。

        策略（v1 简化版）：
        - 取文件中所有符号
        - 优先取匹配到的符号（matched_symbols）
        - 其次是类/函数定义
        - 最多 _MAX_SYMBOLS_PER_FILE 个
        """
        all_syms = symbol_index.symbols_in_file(file_path)
        if not all_syms:
            return []

        # 分离：匹配到的 vs 未匹配的
        matched: list[RepoMapSymbol] = []
        others: list[RepoMapSymbol] = []

        for sym in all_syms:
            rms = RepoMapBuilder._to_repo_map_symbol(sym)

            if sym.name in ranked.matched_symbols:
                matched.append(rms)
            elif sym.kind in (SymbolKind.CLASS, SymbolKind.FUNCTION, SymbolKind.METHOD):
                others.append(rms)

        # 匹配到的在前，类/函数在后，截断
        selected = matched + others
        return selected[:_MAX_SYMBOLS_PER_FILE]

    @staticmethod
    def _to_repo_map_symbol(sym) -> RepoMapSymbol:
        """把 SymbolIndex 的 Symbol 转成 RepoMapSymbol。"""
        return RepoMapSymbol(
            symbol_id=sym.symbol_id,
            name=sym.name,
            qualified_name=sym.qualified_name or sym.name,
            kind=sym.kind.value,
            signature=sym.signature or None,
            line=sym.location.line,
            representation=SymbolRepresentation.SIGNATURE,
        )

    # ── 贪心加入 ─────────────────────────────────────────────

    def _fit_entry(
        self,
        budget: TokenBudget,
        selected: list[RepoMapFile],
        candidate: RepoMapFile,
        mode: str,
        query: str | None,
    ) -> bool:
        """尝试加入一个文件条目。超预算则逐级压缩。

        Returns:
            True  → 成功加入（entry 已被修改为最终状态）
            False → 全部级别都超预算，跳过
        """
        # 压缩级别：SIGNATURE → NAME_ONLY → OMITTED
        levels = [
            SymbolRepresentation.SIGNATURE,
            SymbolRepresentation.NAME_ONLY,
            SymbolRepresentation.OMITTED,
        ]

        for level in levels:
            if level != SymbolRepresentation.SIGNATURE:
                candidate.symbols = compress_entry(candidate, level).symbols
                candidate.omitted_symbol_count = compress_entry(
                    candidate, level
                ).omitted_symbol_count

            # 试渲染
            trial_text = self._render_trial(candidate)
            trial_tokens = budget.count(trial_text)

            if trial_tokens <= budget.remaining:
                # 成功加入
                candidate.estimated_tokens = trial_tokens
                budget.add(trial_text)
                return True

        return False

    # ── 渲染辅助 ─────────────────────────────────────────────

    def _render_trial(
        self,
        candidate: RepoMapFile,
    ) -> str:
        """生成只有候选条目的增量文本。"""
        # 渲染单个候选条目（不包含 header 和已有文件）
        '''需要注意的是，当前版本只对candidate进行了渲染，速度快但会有估算精度损失。
        在实际生产环境中，可以采用增量追踪的方式来计算token数，或者在渲染时对已有文件进行缓存，以提高精度。
        '''
        lines = self.renderer.render_file(candidate)
        return "\n".join(lines) + "\n"

    @staticmethod
    def _render_header(mode: str, query: str | None) -> str:
        lines = [f"# Repository map ({mode})"]
        if query:
            lines.append(f"# Query: {query}")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _render_footer(omitted_count: int) -> str:
        if omitted_count:
            return f"\n# ... {omitted_count} lower-ranked files omitted\n"
        return ""