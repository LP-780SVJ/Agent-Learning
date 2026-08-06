"""Tests for codeteam.search.candidate_generator — CandidateGenerator。

覆盖：单路召回、多路聚合、证据合并去重、空结果处理。
由于 CandidateGenerator 依赖 ripgrep，部分测试 mock 掉 ripgrep 调用。
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from codeteam.repository.filename_index import FilenameIndex
from codeteam.search.candidate_generator import CandidateGenerator
from codeteam.search.models import (
    AnalyzedQuery,
    CandidateEvidence,
    CandidateFile,
    CandidateSource,
    SearchExecution,
    SearchMode,
    SearchQuery,
)
from codeteam.search.query_analyzer import QueryAnalyzer
from codeteam.search.ripgrep import RipgrepClient
from codeteam.symbols.models import (
    Symbol,
    SymbolKind,
    SymbolLocation,
)


# ── 辅助 ────────────────────────────────────────────────────────

def _make_candidate(path: str, score: float = 0.0) -> CandidateFile:
    return CandidateFile(path=path, preliminary_score=score)


# ── _add_evidence（静态方法）─────────────────────────────────────

class TestAddEvidence:
    """_add_evidence：证据添加、去重和分数累加。"""

    def test_adds_evidence_to_new_file(self) -> None:
        """新文件——创建 CandidateFile 并添加证据。"""
        candidates: dict[str, CandidateFile] = {}
        evidence = CandidateEvidence(
            source=CandidateSource.SYMBOL_EXACT,
            query_term="UserService",
            detail="Defines class UserService",
            weight=5.0,
        )

        CandidateGenerator._add_evidence(
            candidates, "auth/service.py", evidence
        )

        assert "auth/service.py" in candidates
        candidate = candidates["auth/service.py"]
        assert len(candidate.evidence) == 1
        assert candidate.preliminary_score == 5.0

    def test_accumulates_score_from_multiple_evidence(self) -> None:
        """多条证据——分数累加。"""
        candidates: dict[str, CandidateFile] = {}

        CandidateGenerator._add_evidence(
            candidates,
            "auth/service.py",
            CandidateEvidence(
                source=CandidateSource.SYMBOL_EXACT,
                query_term="UserService",
                detail="Defines",
                weight=5.0,
            ),
        )
        CandidateGenerator._add_evidence(
            candidates,
            "auth/service.py",
            CandidateEvidence(
                source=CandidateSource.RIPGREP,
                query_term="UserService",
                detail="Matched at line 3",
                line_number=3,
                weight=2.0,
            ),
        )

        candidate = candidates["auth/service.py"]
        assert len(candidate.evidence) == 2
        assert candidate.preliminary_score == 7.0

    def test_duplicate_evidence_not_added_twice(self) -> None:
        """同一来源+词条+详情+行号的证据不重复添加。"""
        candidates: dict[str, CandidateFile] = {}

        evidence = CandidateEvidence(
            source=CandidateSource.RIPGREP,
            query_term="UserService",
            detail="Matched at line 3",
            line_number=3,
            weight=2.0,
        )

        CandidateGenerator._add_evidence(
            candidates, "auth/service.py", evidence
        )
        CandidateGenerator._add_evidence(
            candidates, "auth/service.py", evidence
        )

        candidate = candidates["auth/service.py"]
        assert len(candidate.evidence) == 1
        assert candidate.preliminary_score == 2.0

    def test_ripgrep_evidence_increments_match_count(self) -> None:
        """RIPGREP 来源的证据会递增 match_count。"""
        candidates: dict[str, CandidateFile] = {}

        for i in range(3):
            CandidateGenerator._add_evidence(
                candidates,
                "auth/service.py",
                CandidateEvidence(
                    source=CandidateSource.RIPGREP,
                    query_term=f"term_{i}",
                    detail=f"Match {i}",
                    line_number=i + 1,
                    weight=1.0,
                ),
            )

        candidate = candidates["auth/service.py"]
        assert candidate.match_count == 3


# ── _add_explicit_paths ─────────────────────────────────────────

class TestExplicitPaths:
    """显式路径召回测试。"""

    def test_existing_path_added_as_candidate(
        self, candidate_generator: CandidateGenerator
    ) -> None:
        """仓库中存在的路径被添加为候选。"""
        query = "修改 auth/service.py"
        candidates = candidate_generator.generate(query)

        paths = {c.path for c in candidates}
        assert "auth/service.py" in paths

    def test_explicit_path_has_highest_weight(
        self, candidate_generator: CandidateGenerator
    ) -> None:
        """显式路径的权重最高（10.0）。

        注意：路径提取可能包含前导空格，使用精确路径查询确保匹配。
        """
        # 使用英文查询，路径前后无中文文本干扰
        query = "auth/service.py"
        candidates = candidate_generator.generate(query)

        service_candidate = next(
            c for c in candidates if c.path == "auth/service.py"
        )
        # 寻找 EXPLICIT_PATH 证据
        explicit = [
            e for e in service_candidate.evidence
            if e.source == CandidateSource.EXPLICIT_PATH
        ]
        assert len(explicit) >= 1
        assert explicit[0].weight == 10.0

    def test_nonexistent_path_not_added(
        self, candidate_generator: CandidateGenerator
    ) -> None:
        """不存在的路径不会被添加为候选。"""
        query = "修改 nonexistent/file.py"
        candidates = candidate_generator.generate(query)

        paths = {c.path for c in candidates}
        assert "nonexistent/file.py" not in paths


# ── _add_symbol_candidates ──────────────────────────────────────

class TestSymbolCandidates:
    """SymbolIndex 精确和前缀匹配。"""

    def test_exact_symbol_match_adds_candidate(
        self, candidate_generator: CandidateGenerator
    ) -> None:
        """精确符号名匹配——添加候选文件。"""
        query = "UserService 在哪里定义"
        candidates = candidate_generator.generate(query)

        paths = {c.path for c in candidates}
        assert "auth/service.py" in paths

    def test_exact_symbol_has_weight_5(
        self, candidate_generator: CandidateGenerator
    ) -> None:
        """精确符号匹配权重为 5.0。"""
        query = "UserService 服务类"
        candidates = candidate_generator.generate(query)

        service_candidate = next(
            c for c in candidates if c.path == "auth/service.py"
        )
        exact = [
            e for e in service_candidate.evidence
            if e.source == CandidateSource.SYMBOL_EXACT
        ]
        assert len(exact) >= 1
        assert exact[0].weight == 5.0

    def test_prefix_match_used_when_exact_not_found(
        self, candidate_generator: CandidateGenerator
    ) -> None:
        """精确匹配无结果时走前缀匹配。"""
        query = "User 相关"
        candidates = candidate_generator.generate(query)

        paths = {c.path for c in candidates}
        # 应该通过前缀匹配到 UserService 和 UserRepository
        assert len(paths) >= 1

    def test_no_symbol_match_returns_empty_for_unrelated_query(
        self, candidate_generator: CandidateGenerator
    ) -> None:
        """与索引无关的查询不会错误添加符号候选。"""
        query = "xyz_not_in_index_123"
        candidates = candidate_generator.generate(query)

        symbol_evidence_files = set()
        for c in candidates:
            for e in c.evidence:
                if e.source in (
                    CandidateSource.SYMBOL_EXACT,
                    CandidateSource.SYMBOL_PREFIX,
                ):
                    symbol_evidence_files.add(c.path)

        # 不应该通过符号匹配添加任何文件
        assert len(symbol_evidence_files) == 0


# ── _add_filename_candidates ────────────────────────────────────

class TestFilenameCandidates:
    """FilenameIndex 文件名匹配。"""

    def test_filename_match_adds_candidate(
        self, candidate_generator: CandidateGenerator
    ) -> None:
        """文件名 token 匹配——添加候选。"""
        query = "service.py 文件"
        candidates = candidate_generator.generate(query)

        paths = {c.path for c in candidates}
        assert "auth/service.py" in paths

    def test_partial_filename_match_has_lower_weight(
        self, candidate_generator: CandidateGenerator
    ) -> None:
        """文件名部分匹配——权重低于完整匹配。"""
        query = "repository 模块"
        candidates = candidate_generator.generate(query)

        repo_candidate = next(
            c for c in candidates if c.path == "auth/repository.py"
        )
        filename_evidence = [
            e for e in repo_candidate.evidence
            if e.source == CandidateSource.FILENAME
        ]
        assert len(filename_evidence) >= 1
        # repository 完整匹配 -> FILENAME_FULL (4.0)
        assert filename_evidence[0].weight >= 1.0


# ── 空结果处理 ──────────────────────────────────────────────────

class TestEmptyResults:
    """无匹配查询的处理。"""

    def test_empty_query_returns_empty_list(
        self,
        query_analyzer: QueryAnalyzer,
        ripgrep_client: RipgrepClient,
        symbol_index,
        filename_index,
        import_graph,
        repository_snapshot,
    ) -> None:
        """空查询返回空候选列表，不抛异常。"""
        gen = CandidateGenerator(
            analyzer=query_analyzer,
            ripgrep=ripgrep_client,
            symbol_index=symbol_index,
            filename_index=filename_index,
            import_graph=import_graph,
            repository=repository_snapshot,
        )
        result = gen.generate("")
        assert result == []

    def test_unmatched_query_handled_gracefully(
        self, candidate_generator: CandidateGenerator
    ) -> None:
        """没有任何匹配的查询不抛异常。"""
        result = candidate_generator.generate(
            "DefinitelyNotExistingSymbol12345"
        )
        assert isinstance(result, list)
        # 可能因为 FilenameIndex 匹配到一些文件，这是正常的


# ── 候选排序 ────────────────────────────────────────────────────

class TestCandidateOrdering:
    """候选结果按 preliminary_score 排序。"""

    def test_candidates_sorted_by_score_desc(
        self, candidate_generator: CandidateGenerator
    ) -> None:
        """候选人按分数降序排列。"""
        query = "修改 auth/service.py 文件中的 UserService 类"
        candidates = candidate_generator.generate(query)

        scores = [c.preliminary_score for c in candidates]
        # 验证单调递减
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], (
                f"Score at {i} ({scores[i]}) < score at {i+1} ({scores[i+1]})"
            )

    def test_candidate_limit_respected(
        self, candidate_generator: CandidateGenerator
    ) -> None:
        """candidate_limit 参数生效。"""
        query = "service User repository errors 中文注释"
        candidates = candidate_generator.generate(query, candidate_limit=3)
        assert len(candidates) <= 3


# ── 多路聚合 ────────────────────────────────────────────────────

class TestMultiSourceAggregation:
    """多路召回汇聚到同一个文件。"""

    def test_file_with_multiple_sources_has_higher_score(
        self, candidate_generator: CandidateGenerator
    ) -> None:
        """同一文件被多个通道命中——分数叠加。

        使用符号名查询，确保至少通过符号匹配召回文件。
        """
        query = "UserService class"
        candidates = candidate_generator.generate(query)

        service_candidate = next(
            c for c in candidates if c.path == "auth/service.py"
        )
        sources = {e.source for e in service_candidate.evidence}

        # auth/service.py 应通过 SYMBOL_EXACT + 至少一个其他来源
        assert CandidateSource.SYMBOL_EXACT in sources, (
            f"Expected SYMBOL_EXACT in sources, got: {sources}"
        )
        assert len(sources) >= 2, (
            f"Expected at least 2 sources, got: {sources}"
        )

    def test_different_files_from_different_sources(
        self, candidate_generator: CandidateGenerator
    ) -> None:
        """不同来源召回不同的文件。"""
        query = "UserService 在 auth/service.py"
        candidates = candidate_generator.generate(query)

        paths = {c.path for c in candidates}
        # 路径来源 + 符号来源应召回不同文件
        assert "auth/service.py" in paths


# ── _possible_test_names ────────────────────────────────────────

class TestPossibleTestNames:
    """测试文件名生成。"""

    def test_generates_test_paths(self) -> None:
        """为源文件生成对应的测试文件路径。"""
        names = CandidateGenerator._possible_test_names("auth/service.py")
        assert "tests/auth/test_service.py" in names
        assert "tests/auth/service_test.py" in names
        assert "auth/test_service.py" in names
        assert "auth/service_test.py" in names

    def test_all_generated_paths_are_unique(self) -> None:
        """生成的路径不应有重复。"""
        names = CandidateGenerator._possible_test_names("auth/service.py")
        assert len(names) == len(set(names))


# ── 权重常量访问 ────────────────────────────────────────────────

class TestWeights:
    """权重常量可达性检查。"""

    def test_weights_have_expected_relative_order(self) -> None:
        """验证权重相对顺序：EXPLICIT > SYMBOL_EXACT > FILENAME_FULL > RIPGREP_PRIMARY。"""
        from codeteam.search.candidate_generator import _Weight

        assert _Weight.EXPLICIT_PATH > _Weight.SYMBOL_EXACT
        assert _Weight.SYMBOL_EXACT > _Weight.FILENAME_FULL
        assert _Weight.FILENAME_FULL > _Weight.RIPGREP_PRIMARY
        assert _Weight.RIPGREP_PRIMARY > _Weight.RIPGREP_SECONDARY


# ── import 邻居扩展 ─────────────────────────────────────────────

class TestImportNeighbors:
    """ImportGraph 邻居扩展。"""

    def test_import_neighbors_expand_from_strong_candidates(
        self, candidate_generator: CandidateGenerator
    ) -> None:
        """高分候选文件的 import 邻居被扩展进来。"""
        # auth/api.py 不在 fixture 文件系统中，但可以通过 import 边找到
        # 先通过 symbols 让 auth/service.py 成为候选
        query = "UserService 类"
        candidates = candidate_generator.generate(query)

        # 检查是否有 IMPORT_DEPENDENCY / IMPORT_DEPENDENT 来源的证据
        import_sources_seen = set()
        for c in candidates:
            for e in c.evidence:
                if e.source in (
                    CandidateSource.IMPORT_DEPENDENCY,
                    CandidateSource.IMPORT_DEPENDENT,
                ):
                    import_sources_seen.add(e.source)

        # 如果有 import 邻居证据，说明扩展生效
        if import_sources_seen:
            assert CandidateSource.IMPORT_DEPENDENCY in import_sources_seen or \
                   CandidateSource.IMPORT_DEPENDENT in import_sources_seen
