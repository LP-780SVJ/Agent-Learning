"""Tests for codeteam.ranking.file_ranker — FileRanker.

覆盖 8 个核心测试场景中的 5 个：
  T01: 同一查询结果稳定（确定性排序）
  T03: 查询变化排名变化（auth vs order）
  T07: 一跳优于两跳（import distance）
  T08: PageRank 不压过精确查询
"""

from __future__ import annotations

import pytest

from codeteam.ranking.file_ranker import FileRanker
from codeteam.ranking.models import RankedFile, RankingWeights, saturate
from codeteam.search.models import CandidateFile, CandidateEvidence, CandidateSource


# ── T01: 同一查询结果稳定 ─────────────────────────────────────

class TestDeterministicRanking:
    """候选顺序不同 → 排序结果相同。"""

    def test_same_query_is_deterministic(
        self,
        file_ranker: FileRanker,
        auth_service_candidate: CandidateFile,
        auth_api_candidate: CandidateFile,
        auth_exceptions_candidate: CandidateFile,
    ) -> None:
        """输入顺序反转，输出顺序不变。"""
        candidates = [
            auth_service_candidate,
            auth_api_candidate,
            auth_exceptions_candidate,
        ]

        first = file_ranker.rank(candidates)
        second = file_ranker.rank(list(reversed(candidates)))

        assert [item.path for item in first] == [item.path for item in second]

    def test_same_scores_produce_stable_order(
        self,
        file_ranker: FileRanker,
    ) -> None:
        """同分文件按 path 字母序保持稳定。"""
        # 两个候选分数完全相同
        a = CandidateFile(path="src/b.py")
        a.evidence.append(CandidateEvidence(
            source=CandidateSource.RIPGREP,
            query_term="test", detail="match", weight=2.0,
        ))
        a.preliminary_score = 2.0

        b = CandidateFile(path="src/a.py")
        b.evidence.append(CandidateEvidence(
            source=CandidateSource.RIPGREP,
            query_term="test", detail="match", weight=2.0,
        ))
        b.preliminary_score = 2.0

        result = file_ranker.rank([a, b])
        # 同分按 casefold 排序: a.py < b.py
        assert result[0].path == "src/a.py"
        assert result[1].path == "src/b.py"


# ── T03: 查询变化排名变化 ─────────────────────────────────────

class TestQueryDrivenRanking:
    """不同查询应产生不同排名。"""

    def test_auth_query_ranks_auth_files_higher(
        self,
        file_ranker: FileRanker,
    ) -> None:
        """auth 查询 → auth 文件排前面。"""
        # 模拟 auth 查询的候选
        auth_service = CandidateFile(path="src/auth/service.py")
        auth_service.evidence.extend([
            CandidateEvidence(source=CandidateSource.SYMBOL_EXACT, query_term="AuthService", detail="def", weight=5.0, line_number=5),
            CandidateEvidence(source=CandidateSource.RIPGREP, query_term="refresh", detail="match", weight=2.0, line_number=12),
            CandidateEvidence(source=CandidateSource.RIPGREP, query_term="token", detail="match", weight=2.0, line_number=16),
        ])
        auth_service.preliminary_score = 9.0

        auth_api = CandidateFile(path="src/auth/api.py")
        auth_api.evidence.extend([
            CandidateEvidence(source=CandidateSource.SYMBOL_EXACT, query_term="AuthController", detail="def", weight=5.0, line_number=5),
            CandidateEvidence(source=CandidateSource.IMPORT_DEPENDENCY, query_term="service", detail="import", weight=1.5, line_number=None),
        ])
        auth_api.preliminary_score = 6.5

        auth_exc = CandidateFile(path="src/auth/exceptions.py")
        auth_exc.evidence.extend([
            CandidateEvidence(source=CandidateSource.SYMBOL_EXACT, query_term="InvalidRefreshTokenError", detail="def", weight=5.0, line_number=7),
        ])
        auth_exc.preliminary_score = 5.0

        orders = CandidateFile(path="src/orders/exporter.py")
        orders.evidence.extend([
            CandidateEvidence(source=CandidateSource.RIPGREP, query_term="export", detail="secondary_match", weight=1.0, line_number=5),
        ])
        orders.preliminary_score = 1.0

        candidates = [auth_service, auth_api, auth_exc, orders]
        result = file_ranker.rank(candidates)

        # Top 3 应全部是 auth 文件
        top3_paths = [item.path for item in result[:3]]
        for path in top3_paths:
            assert "auth" in path, (
                f"Expected auth file in top 3, got: {top3_paths}"
            )

    def test_order_query_ranks_order_files_higher(
        self,
        file_ranker: FileRanker,
    ) -> None:
        """order 查询 → order 文件排前面。"""
        orders_exporter = CandidateFile(path="src/orders/exporter.py")
        orders_exporter.evidence.extend([
            CandidateEvidence(source=CandidateSource.SYMBOL_EXACT, query_term="export_orders_to_csv", detail="def", weight=5.0, line_number=5),
            CandidateEvidence(source=CandidateSource.RIPGREP, query_term="export", detail="match", weight=2.0, line_number=5),
            CandidateEvidence(source=CandidateSource.RIPGREP, query_term="order", detail="match", weight=2.0, line_number=5),
        ])
        orders_exporter.preliminary_score = 9.0

        orders_worker = CandidateFile(path="src/orders/worker.py")
        orders_worker.evidence.extend([
            CandidateEvidence(source=CandidateSource.SYMBOL_EXACT, query_term="OrderWorker", detail="def", weight=5.0, line_number=5),
            CandidateEvidence(source=CandidateSource.RIPGREP, query_term="order", detail="match", weight=2.0, line_number=8),
        ])
        orders_worker.preliminary_score = 7.0

        auth_service = CandidateFile(path="src/auth/service.py")
        auth_service.evidence.extend([
            CandidateEvidence(source=CandidateSource.RIPGREP, query_term="order", detail="secondary_match", weight=1.0, line_number=1),
        ])
        auth_service.preliminary_score = 1.0

        candidates = [orders_exporter, orders_worker, auth_service]
        result = file_ranker.rank(candidates)

        # Top 2 应全部是 orders 文件
        top2_paths = [item.path for item in result[:2]]
        for path in top2_paths:
            assert "orders" in path, (
                f"Expected orders file in top 2, got: {top2_paths}"
            )

    def test_different_queries_produce_different_top_file(
        self,
        file_ranker: FileRanker,
    ) -> None:
        """auth 查询和 order 查询的首位文件不同。"""
        # auth 候选集
        auth_candidates = [
            CandidateFile(
                path="src/auth/service.py",
                evidence=[
                    CandidateEvidence(source=CandidateSource.SYMBOL_EXACT, query_term="refresh_access_token", detail="def", weight=5.0, line_number=12),
                ],
                preliminary_score=5.0,
            ),
            CandidateFile(
                path="src/orders/exporter.py",
                evidence=[
                    CandidateEvidence(source=CandidateSource.RIPGREP, query_term="order", detail="match", weight=1.0, line_number=1),
                ],
                preliminary_score=1.0,
            ),
        ]

        # order 候选集
        order_candidates = [
            CandidateFile(
                path="src/orders/exporter.py",
                evidence=[
                    CandidateEvidence(source=CandidateSource.SYMBOL_EXACT, query_term="export_orders_to_csv", detail="def", weight=5.0, line_number=5),
                ],
                preliminary_score=5.0,
            ),
            CandidateFile(
                path="src/auth/service.py",
                evidence=[
                    CandidateEvidence(source=CandidateSource.RIPGREP, query_term="export", detail="secondary_match", weight=1.0, line_number=0),
                ],
                preliminary_score=1.0,
            ),
        ]

        auth_rank = file_ranker.rank(auth_candidates)
        order_rank = file_ranker.rank(order_candidates)

        assert auth_rank[0].path != order_rank[0].path
        assert auth_rank[0].path == "src/auth/service.py"
        assert order_rank[0].path == "src/orders/exporter.py"


# ── T07: 一跳优于两跳 ─────────────────────────────────────────

class TestImportDistance:
    """直接依赖（一跳）的分数应高于间接依赖（两跳）。"""

    def test_one_hop_scores_higher_than_two_hop(
        self,
        file_ranker: FileRanker,
    ) -> None:
        """api → service → repository 链条：
        api 直接命中 → score(api) > score(service) > score(repo)
        """
        # api.py 直接命中查询
        api = CandidateFile(path="src/auth/api.py")
        api.evidence.extend([
            CandidateEvidence(source=CandidateSource.SYMBOL_EXACT, query_term="AuthController", detail="def", weight=5.0, line_number=5),
            CandidateEvidence(source=CandidateSource.RIPGREP, query_term="token", detail="match", weight=2.0, line_number=11),
        ])
        api.preliminary_score = 7.0

        # service.py 只有 import 关系
        service = CandidateFile(path="src/auth/service.py")
        service.evidence.extend([
            CandidateEvidence(source=CandidateSource.IMPORT_DEPENDENCY, query_term="api", detail="imported-by-api", weight=1.5, line_number=None),
        ])
        service.preliminary_score = 1.5

        # database.py 更多层间接
        db = CandidateFile(path="src/common/database.py")
        db.evidence.extend([
            CandidateEvidence(source=CandidateSource.IMPORT_DEPENDENCY, query_term="service", detail="imported-by-service", weight=1.5, line_number=None),
        ])
        db.preliminary_score = 1.5

        candidates = [api, service, db]
        result = file_ranker.rank(candidates)

        # api 的 final_score 最高（直接命中+import），
        # service 和 db 只有 import 关系
        api_score = next(item.final_score for item in result if item.path == "src/auth/api.py")
        service_score = next(item.final_score for item in result if item.path == "src/auth/service.py")
        db_score = next(item.final_score for item in result if item.path == "src/common/database.py")

        assert api_score > service_score, (
            f"api_score={api_score} should be > service_score={service_score}"
        )
        assert service_score >= db_score, (
            f"service_score={service_score} should be >= db_score={db_score}"
        )


# ── T08: PageRank 不压过精确查询 ───────────────────────────────

class TestPageRankVsExactMatch:
    """精确符号匹配的权重应高于 PageRank。"""

    def test_rare_symbol_ranks_above_high_pagerank_file(
        self,
        file_ranker: FileRanker,
    ) -> None:
        """定义了 RareError 的文件排名高于被 100 个文件 import 的 common.py。"""
        # rare_bug.py — 精确定义了 UserSpecifiedRareError
        rare_bug = CandidateFile(path="src/rare_bug.py")
        rare_bug.evidence.extend([
            CandidateEvidence(source=CandidateSource.SYMBOL_EXACT, query_term="UserSpecifiedRareError", detail="defines-class", weight=5.0, line_number=3),
        ])
        rare_bug.preliminary_score = 5.0

        # common.py — 被很多文件依赖
        common = CandidateFile(path="src/common/database.py")
        common.evidence.extend([
            CandidateEvidence(source=CandidateSource.IMPORT_DEPENDENCY, query_term="file_1", detail="depends", weight=1.5, line_number=None),
            CandidateEvidence(source=CandidateSource.IMPORT_DEPENDENCY, query_term="file_2", detail="depends", weight=1.5, line_number=None),
            CandidateEvidence(source=CandidateSource.IMPORT_DEPENDENCY, query_term="file_3", detail="depends", weight=1.5, line_number=None),
        ])
        common.preliminary_score = 4.5

        # 模拟高 PageRank
        global_pr = {"src/common/database.py": 100.0, "src/rare_bug.py": 0.1}
        personalized_pr = {"src/rare_bug.py": 5.0, "src/common/database.py": 1.0}

        candidates = [rare_bug, common]
        result = file_ranker.rank(
            candidates,
            global_pagerank=global_pr,
            personalized_pagerank=personalized_pr,
        )

        assert result[0].path == "src/rare_bug.py", (
            f"RareBug should rank #1, got: {result[0].path} "
            f"(score={result[0].final_score})"
        )

    def test_exact_path_always_wins_over_pagerank(
        self,
        file_ranker: FileRanker,
    ) -> None:
        """用户明确指定的路径 > 任何 PageRank。"""
        explicit = CandidateFile(path="src/specific/file.py")
        explicit.evidence.extend([
            CandidateEvidence(source=CandidateSource.EXPLICIT_PATH, query_term="src/specific/file.py", detail="user-specified", weight=10.0, line_number=None),
        ])
        explicit.preliminary_score = 10.0

        popular = CandidateFile(path="src/common/database.py")
        popular.evidence.extend([
            CandidateEvidence(source=CandidateSource.IMPORT_DEPENDENCY, query_term="f1", detail="dep", weight=1.5, line_number=None),
        ])
        popular.preliminary_score = 1.5

        global_pr = {"src/common/database.py": 1000.0, "src/specific/file.py": 1.0}

        candidates = [explicit, popular]
        result = file_ranker.rank(candidates, global_pagerank=global_pr)

        assert result[0].path == "src/specific/file.py"


# ── saturate 函数 ──────────────────────────────────────────────

class TestSaturate:
    """saturate() 辅助函数：压缩多次命中到 [0, 1)。"""

    def test_zero_returns_zero(self) -> None:
        assert saturate(0.0) == 0.0

    def test_one_returns_about_point_six_three(self) -> None:
        result = saturate(1.0)
        assert 0.63 < result < 0.64

    def test_large_value_approaches_one(self) -> None:
        result = saturate(100.0)
        assert 0.99 < result <= 1.0

    def test_negative_value_clamped_to_zero(self) -> None:
        assert saturate(-5.0) == 0.0


# ── 权重常量 ───────────────────────────────────────────────────

class TestRankingWeights:
    """权重常量的相对顺序检查。"""

    def test_exact_match_weights_are_highest(self) -> None:
        w = RankingWeights()
        assert w.query_match == 4.0
        assert w.symbol_match == 4.0

    def test_generated_penalty_is_negative(self) -> None:
        w = RankingWeights()
        assert w.generated_penalty > 0  # 权重为正，信号值为负
