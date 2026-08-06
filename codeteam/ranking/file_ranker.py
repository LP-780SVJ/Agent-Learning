"""
FileRanker: 文件级排序引擎。

把 CandidateFile 列表 → 计算 FileSignals → 加权融合 → list[RankedFile]。

先不接 PageRank —— global_pagerank 和 personalized_pagerank 作为可选参数传入。
第 4 步实现 PageRank 后直接喂入。
"""
from __future__ import annotations

from codeteam.search.models import CandidateFile, CandidateSource
from codeteam.ranking.models import (
    FileSignals,
    RankingEvidence,
    RankedFile,
    RankingWeights,
    saturate,
)


class FileRanker:
    """多信号加权融合排序器。

    用法：
        ranker = FileRanker()  # 使用默认权重
        ranked = ranker.rank(candidates)
        for r in ranked[:5]:
            print(f"{r.rank}. {r.path} (score={r.final_score:.2f})")
    """

    def __init__(
        self,
        weights: RankingWeights | None = None,
    ) -> None:
        """初始化 FileRanker。

        Args:
            weights: 权重配置。为 None 时使用默认权重。
        """
        self.weights = weights or RankingWeights()

    # ── 主入口 ───────────────────────────────────────────────

    def rank(
        self,
        candidates: list[CandidateFile],
        *,
        global_pagerank: dict[str, float] | None = None,
        personalized_pagerank: dict[str, float] | None = None,
    ) -> list[RankedFile]:
        """对候选文件排序。

        Args:
            candidates: CandidateGenerator 产出的候选文件列表
            global_pagerank: 全局 PageRank 分数（path → score）
            personalized_pagerank: 个性化 PageRank 分数（path → score）

        Returns:
            按 final_score 降序排列的 RankedFile 列表
        """
        # 归一化 PageRank 到 [0, 1]
        global_pr = self._normalize(global_pagerank or {})
        personalized_pr = self._normalize(personalized_pagerank or {})

        ranked: list[RankedFile] = []

        for candidate in candidates:
            # 步骤 1-3：计算信号值
            signals = self._build_signals(
                candidate,
                global_pr,
                personalized_pr,
            )

            # 步骤 4：解释每个信号 → RankingEvidence
            evidence = self._explain(signals)

            # 步骤 5：求和
            final_score = sum(e.contribution for e in evidence)

            # 收集匹配信息
            matched_symbols = self._extract_matched_symbols(candidate)
            matched_lines = self._extract_matched_lines(candidate)

            ranked.append(
                RankedFile(
                    path=candidate.path,
                    final_score=final_score,
                    rank=0,  # 排序后统一赋值
                    signals=signals,
                    evidence=evidence,
                    matched_symbols=matched_symbols,
                    matched_lines=matched_lines,
                    is_generated=self._is_generated(candidate.path),
                    is_test=candidate.is_test,
                )
            )

        # 步骤 6：稳定排序
        ranked.sort(
            key=lambda item: (
                -round(item.final_score, 8),  # 浮点精度固定
                item.path.casefold(),          # 同分按路径
                item.path,
            )
        )

        # 分配排名（1-based）
        for index, item in enumerate(ranked, start=1):
            item.rank = index

        return ranked

    # ── 信号计算 ────────────────────────────────────────────

    def _build_signals(
        self,
        candidate: CandidateFile,
        global_pr: dict[str, float],
        personalized_pr: dict[str, float],
    ) -> FileSignals:
        """根据 CandidateEvidence 计算 FileSignals。

        每类 evidence 累加计数 → saturate 压缩 → 填入对应信号字段
        """
        # 统计各类证据数量
        explicit_hits = 0
        filename_full_hits = 0
        filename_part_hits = 0
        symbol_exact_hits = 0
        symbol_prefix_hits = 0
        ripgrep_primary_hits = 0
        ripgrep_secondary_hits = 0
        import_hits = 0

        for ev in candidate.evidence:
            source = ev.source

            if source == CandidateSource.EXPLICIT_PATH:
                explicit_hits += 1

            elif source == CandidateSource.FILENAME:
                # weight >= 4 → 完整文件名匹配，weight < 4 → 部分匹配
                if ev.weight >= 4.0:
                    filename_full_hits += 1
                else:
                    filename_part_hits += 1

            elif source == CandidateSource.SYMBOL_EXACT:
                symbol_exact_hits += 1

            elif source == CandidateSource.SYMBOL_PREFIX:
                symbol_prefix_hits += 1

            elif source == CandidateSource.RIPGREP:
                # weight >= 2 → 高优 term，weight < 2 → 低优 t
                if ev.weight >= 2.0:
                    ripgrep_primary_hits += 1
                else:
                    ripgrep_secondary_hits += 1

            elif source in (
                CandidateSource.IMPORT_DEPENDENCY,
                CandidateSource.IMPORT_DEPENDENT,
            ):
                import_hits += 1

        # 构建信号值
        path = candidate.path
        return FileSignals(
            # query_match: 显式路径最强 → 完整文件名 → 部分匹配
            query_match=saturate(
                explicit_hits * 2.0
                + filename_full_hits
                + filename_part_hits * 0.5
            ),
            # symbol_match: 精确 > 前缀（前缀权重折半）
            symbol_match=saturate(
                symbol_exact_hits + symbol_prefix_hits * 0.5
            ),
            # ripgrep_match: 高优 term > 低优 term
            ripgrep_match=saturate(
                ripgrep_primary_hits + ripgrep_secondary_hits * 0.3
            ),
            # import: 有 import 关系就是 1.0（saturate(1) ≈ 0.63）
            import_one_hop=float(import_hits > 0),
            import_two_hop=0.0,  # 第 4 步接入
            # PageRank
            global_pagerank=global_pr.get(path, 0.0),
            personalized_pagerank=personalized_pr.get(path, 0.0),
            # 文件类型基础权重
            base_importance=self._compute_base_importance(candidate),
            test_relevance=1.0 if candidate.is_test else 0.0,
            # 惩罚项
            generated_penalty=-1.0 if self._is_generated(path) else 0.0,
            vendored_penalty=0.0,
            binary_penalty=0.0,
        )

    # ── 证据解释 ────────────────────────────────────────────

    def _explain(self, signals: FileSignals) -> list[RankingEvidence]:
        """把 FileSignals 展开为 RankingEvidence 列表。

        只有非零信号才生成 evidence——值为 0 的信号不贡献分数，
        省略以减少噪音。
        """
        w = self.weights
        evidence: list[RankingEvidence] = []

        # (信号名, 信号值, 权重) 三元组
        signal_defs = [
            ("query_match", signals.query_match, w.query_match),
            ("symbol_match", signals.symbol_match, w.symbol_match),
            ("ripgrep_match", signals.ripgrep_match, w.ripgrep_match),
            ("import_one_hop", signals.import_one_hop, w.import_one_hop),
            ("import_two_hop", signals.import_two_hop, w.import_two_hop),
            ("base_importance", signals.base_importance, w.base_importance),
            ("test_relevance", signals.test_relevance, w.test_relevance),
            ("global_pagerank", signals.global_pagerank, w.global_pagerank),
            ("personalized_pagerank", signals.personalized_pagerank, w.personalized_pagerank),
            ("generated_penalty", signals.generated_penalty, w.generated_penalty),
            ("vendored_penalty", signals.vendored_penalty, w.vendored_penalty),
            ("binary_penalty", signals.binary_penalty, w.binary_penalty),
        ]

        for name, value, weight in signal_defs:
            if value == 0.0:
                continue
            evidence.append(
                RankingEvidence(
                    signal=name,
                    value=value,
                    weight=weight,
                    contribution=value * weight,
                    reason=(
                        f"{name}: "
                        f"{value:.3f} × {weight} "
                        f"= {value * weight:.3f}"
                    ),
                )
            )

        return evidence

    # ── 辅助方法 ────────────────────────────────────────────

    @staticmethod
    def _compute_base_importance(candidate: CandidateFile) -> float:
        """根据文件类型计算基础重要性。

        配置文件 > 普通源码 > 测试文件。
        入口文件（main.py、__init__.py）适当提权。
        """
        path = candidate.path

        if candidate.is_config:
            return 0.6
        if candidate.is_test:
            return 0.4
        # 入口文件
        if path.endswith("main.py") or path.endswith("app.py"):
            return 0.6
        if path.endswith("__init__.py"):
            return 0.3  # __init__.py 通常是空的，不重要
        # README/文档类
        if "README" in path or "AGENTS" in path:
            return 0.3

        return 0.5  # 普通源码

    @staticmethod
    def _is_generated(path: str) -> bool:
        """路径启发式判断是否为生成代码。"""
        path_lower = path.lower()
        return (
            "generated" in path_lower
            or "openapi_client" in path_lower
            or "auto_generated" in path_lower
        )

    @staticmethod
    def _extract_matched_symbols(
        candidate: CandidateFile,
    ) -> list[str]:
        """从 evidence 中提取匹配到的符号名。"""
        symbols: list[str] = []
        for ev in candidate.evidence:
            if ev.source in (
                CandidateSource.SYMBOL_EXACT,
                CandidateSource.SYMBOL_PREFIX,
            ):
                # query_term 就是符号名
                if ev.query_term:
                    symbols.append(ev.query_term)
        return sorted(set(symbols))

    @staticmethod
    def _extract_matched_lines(
        candidate: CandidateFile,
    ) -> list[int]:
        """从 evidence 中提取匹配到的行号。"""
        lines: list[int] = []
        for ev in candidate.evidence:
            if ev.line_number is not None:
                lines.append(ev.line_number)
        return sorted(set(lines))

    @staticmethod
    def _normalize(
        values: dict[str, float],
    ) -> dict[str, float]:
        """把 dict 值归一化到 [0, 1]。

        除以最大值。如果所有值都 ≤ 0，全部归 0。
        空 dict 直接返回空。
        """
        if not values:
            return {}

        maximum = max(values.values())
        if maximum <= 0:
            return {key: 0.0 for key in values}

        return {key: value / maximum for key, value in values.items()}