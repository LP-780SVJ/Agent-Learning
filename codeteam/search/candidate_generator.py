"""
CandidateGenerator: 七路召回聚合器。

召回来源：
1. EXPLICIT_PATH    — 用户指定了文件路径（最强信号）
2. FILENAME         — 文件名 token 匹配
3. SYMBOL_EXACT     — SymbolIndex 精确名称匹配
4. SYMBOL_PREFIX    — SymbolIndex 前缀匹配
5. RIPGREP          — ripgrep 文本搜索
6. IMPORT_DEPENDENCY / IMPORT_DEPENDENT — 导入图邻居
7. TEST_PAIR        — 源文件的对应测试文件
8. IMPORTANT_CONFIG — 重要配置文件（条件触发）
"""
from __future__ import annotations

from pathlib import Path

from codeteam.search.models import (
    AnalyzedQuery,
    CandidateSource,
    CandidateEvidence,
    CandidateFile,
    SearchQuery,
    SearchMode,
)
from codeteam.search.query_analyzer import QueryAnalyzer
from codeteam.search.ripgrep import RipgrepClient
from codeteam.symbols.index import SymbolIndex
from codeteam.imports.graph import ImportGraph
from codeteam.repository.filename_index import FilenameIndex
from codeteam.repository.models import RepositorySnapshot


# ── 权重常量 ─────────────────────────────────────────────────

class _Weight:
    """各召回来源的证据权重。

    权重设计原则：
    - 显式路径 >> 符号精确匹配 > 文件名完整匹配 > ripgrep > 前缀/邻居
    - 越精确的信号权重越高
    - 权重不是绝对值，是相对比例
    """
    EXPLICIT_PATH = 10.0
    SYMBOL_EXACT = 5.0
    SYMBOL_PREFIX = 2.0
    RIPGREP_PRIMARY = 2.0
    RIPGREP_SECONDARY = 1.0
    FILENAME_FULL = 4.0
    FILENAME_PART = 1.0
    IMPORT_NEIGHBOR = 3.0
    TEST_PAIR = 1.0
    IMPORTANT_CONFIG = 2.0


# ── 每 term 的 ripgrep 上限 ──────────────────────────────────

_PRIMARY_TERM_MAX = 50      # 高优先级 term 最多 50 条匹配
_SECONDARY_TERM_MAX = 20    # 低优先级 term 最多 20 条匹配
_IMPORT_MAX_NEIGHBORS = 10  # import 扩展最多增加 10 个文件


class CandidateGenerator:
    """七路召回聚合器。

    用法：
        gen = CandidateGenerator(
            analyzer=qa,
            ripgrep=rg,
            symbol_index=si,
            filename_index=fi,
            import_graph=ig,
            repository=repo,
        )
        candidates = gen.generate("UserService 在哪里定义？")
    """

    def __init__(
        self,
        *,
        analyzer: QueryAnalyzer,
        ripgrep: RipgrepClient,
        symbol_index: SymbolIndex,
        filename_index: FilenameIndex,
        import_graph: ImportGraph,
        repository: RepositorySnapshot,
    ) -> None:
        self.analyzer = analyzer
        self.ripgrep = ripgrep
        self.symbol_index = symbol_index
        self.filename_index = filename_index
        self.import_graph = import_graph
        self.repository = repository

    # ── 主入口 ───────────────────────────────────────────────

    def generate(
        self,
        query: str,
        search_path: str = ".",
        candidate_limit: int = 50,
    ) -> list[CandidateFile]:
        """执行七路召回，返回候选文件列表。

        Args:
            query: 用户的自然语言问题
            search_path: ripgrep 搜索目录
            candidate_limit: 最多返回多少个候选（粗排后截断）

        Returns:
            按 preliminary_score 降序排列的候选文件列表
        """
        # 步骤 0：分析查询
        analyzed = self.analyzer.analyze(query)

        # 候选池：path → CandidateFile
        candidates: dict[str, CandidateFile] = {}

        # ── 来源 1：显式路径 ──
        self._add_explicit_paths(analyzed, candidates)

        # ── 来源 2：文件名匹配 ──
        self._add_filename_candidates(analyzed, candidates)

        # ── 来源 3+4：SymbolIndex ──
        self._add_symbol_candidates(analyzed, candidates)

        # ── 来源 5：ripgrep ──
        self._add_ripgrep_candidates(
            analyzed, candidates, search_path
        )

        # ── 来源 6：Import 邻居 ──
        self._expand_import_neighbors(candidates)

        # ── 来源 7：测试文件 ──
        self._add_test_pairs(candidates)

        # ── 来源 8：重要配置 ──
        self._add_important_configs(analyzed, candidates)

        # ── 粗排 + 截断 ──
        ordered = sorted(
            candidates.values(),
            key=lambda c: (-c.preliminary_score, c.path),
        )
        return ordered[:candidate_limit]

    # ── 证据添加（去重）─────────────────────────────────────

    @staticmethod
    def _add_evidence(
        candidates: dict[str, CandidateFile],
        path: str,
        evidence: CandidateEvidence,
    ) -> None:
        """向候选池添加一条证据，自动去重和累加分数。

        如果文件不在候选池中，先创建 CandidateFile。
        如果证据已存在（来源+词条+详情+行号相同），跳过不重复添加。
        """
        candidate = candidates.get(path)

        if candidate is None:
            candidate = CandidateFile(path=path)
            candidates[path] = candidate

        # 收集已有证据的去重 key
        existing_keys = {
            e._dedup_key for e in candidate.evidence
        }

        if evidence._dedup_key in existing_keys:
            return  # 重复证据，跳过

        candidate.evidence.append(evidence)
        candidate.preliminary_score += evidence.weight

        if evidence.source == CandidateSource.RIPGREP:
            candidate.match_count += 1

    # ── 来源 1：显式路径 ─────────────────────────────────────

    def _add_explicit_paths(
        self,
        analyzed: AnalyzedQuery,
        candidates: dict[str, CandidateFile],
    ) -> None:
        """用户明确指定了文件路径——最强信号。

        例如用户说"修改 src/auth/service.py"，提取路径后
        检查该文件是否在仓库中存在。
        """
        for path in analyzed.paths:
            # 检查文件是否在仓库快照中
            if not self._file_exists(path):
                continue

            self._add_evidence(
                candidates,
                path,
                CandidateEvidence(
                    source=CandidateSource.EXPLICIT_PATH,
                    query_term=path,
                    detail=f"用户指定路径: {path}",
                    weight=_Weight.EXPLICIT_PATH,
                ),
            )

    # ── 来源 2：文件名匹配 ───────────────────────────────────

    def _add_filename_candidates(
        self,
        analyzed: AnalyzedQuery,
        candidates: dict[str, CandidateFile],
    ) -> None:
        """用 primary + secondary terms 搜索 FilenameIndex。

        完整文件名匹配权重高（4.0），拆分片段匹配权重低（1.0）。
        """
        all_terms = analyzed.primary_terms + analyzed.secondary_terms

        for term in all_terms:
            files = self.filename_index.search(term)
            for f in files:
                # 判断是完整匹配还是部分匹配
                basename = f.rsplit("/", 1)[-1]
                term_lower = term.lower()
                basename_lower = basename.lower()

                if term_lower == basename_lower or term_lower in basename_lower.split(".")[0]:
                    weight = _Weight.FILENAME_FULL
                else:
                    weight = _Weight.FILENAME_PART

                self._add_evidence(
                    candidates,
                    f,
                    CandidateEvidence(
                        source=CandidateSource.FILENAME,
                        query_term=term,
                        detail=f"文件名匹配 '{term}'",
                        weight=weight,
                    ),
                )

    # ── 来源 3+4：SymbolIndex ────────────────────────────────

    def _add_symbol_candidates(
        self,
        analyzed: AnalyzedQuery,
        candidates: dict[str, CandidateFile],
    ) -> None:
        """先精确匹配，再前缀匹配。

        精确命中权重 5.0，前缀命中权重 2.0。
        精确命中之后不再做前缀匹配（同一个 identifier 不需要重复）。
        """
        for identifier in analyzed.identifiers:
            exact_hits = self.symbol_index.find_exact(identifier)

            if exact_hits:
                for sym in exact_hits:
                    self._add_evidence(
                        candidates,
                        sym.location.file,
                        CandidateEvidence(
                            source=CandidateSource.SYMBOL_EXACT,
                            query_term=identifier,
                            detail=(
                                f"符号定义 '{sym.qualified_name or sym.name}' "
                                f"({sym.kind.value})"
                            ),
                            line_number=sym.location.line,
                            weight=_Weight.SYMBOL_EXACT,
                        ),
                    )
            else:
                # 精确无结果才做前缀匹配
                prefix_hits = self.symbol_index.find_prefix(identifier)
                for sym in prefix_hits:
                    self._add_evidence(
                        candidates,
                        sym.location.file,
                        CandidateEvidence(
                            source=CandidateSource.SYMBOL_PREFIX,
                            query_term=identifier,
                            detail=(
                                f"前缀匹配 '{sym.qualified_name or sym.name}' "
                                f"({sym.kind.value})"
                            ),
                            line_number=sym.location.line,
                            weight=_Weight.SYMBOL_PREFIX,
                        ),
                    )

    # ── 来源 5：ripgrep ──────────────────────────────────────

    def _add_ripgrep_candidates(
        self,
        analyzed: AnalyzedQuery,
        candidates: dict[str, CandidateFile],
        search_path: str,
    ) -> None:
        """对 primary terms 逐个执行 ripgrep 搜索。

        高优先级 term 上限 50，低优先级 term 上限 20。
        防止 service、user 这类常见词淹没其他信号。
        """
        if self.ripgrep is None:
            return

        # Primary terms → 权重 2.0，上限 50
        for term in analyzed.primary_terms:
            query = SearchQuery(
                pattern=term,
                mode=SearchMode.LITERAL,
                file_types=[],
                max_results=_PRIMARY_TERM_MAX,
            )
            result = self.ripgrep.search(query, search_path)
            for match in result.matches:
                self._add_evidence(
                    candidates,
                    match.file_path,
                    CandidateEvidence(
                        source=CandidateSource.RIPGREP,
                        query_term=term,
                        detail=(
                            f"文本匹配在第 {match.line_number} 行: "
                            f"{match.line_text.strip()}"
                        ),
                        line_number=match.line_number,
                        weight=_Weight.RIPGREP_PRIMARY,
                    ),
                )

        # Secondary terms → 权重 1.0，上限 20
        for term in analyzed.secondary_terms:
            query = SearchQuery(
                pattern=term,
                mode=SearchMode.LITERAL,
                file_types=[],
                max_results=_SECONDARY_TERM_MAX,
            )
            result = self.ripgrep.search(query, search_path)
            for match in result.matches:
                self._add_evidence(
                    candidates,
                    match.file_path,
                    CandidateEvidence(
                        source=CandidateSource.RIPGREP,
                        query_term=term,
                        detail=(
                            f"文本匹配在第 {match.line_number} 行: "
                            f"{match.line_text.strip()}"
                        ),
                        line_number=match.line_number,
                        weight=_Weight.RIPGREP_SECONDARY,
                    ),
                )

    # ── 来源 6：Import 邻居 ──────────────────────────────────

    def _expand_import_neighbors(
        self,
        candidates: dict[str, CandidateFile],
    ) -> None:
        """对已有候选文件，扩展其 import 邻居。

        只做一层扩展（depth=1），防止扩散到整个仓库。
        最多增加 IMPORT_MAX_NEIGHBORS 个文件。
        """
        explicit_candidates = [
            candidate for candidate in candidates.values()
            if any(
                evidence.source == CandidateSource.EXPLICIT_PATH
                for evidence in candidate.evidence
            )
        ]
        if explicit_candidates:
            strong_candidates = explicit_candidates
        else:
            # 按分数排序，只从高分候选扩展
            strong_candidates = sorted(
                candidates.values(),
                key=lambda c: -c.preliminary_score,
            )[:10]  # 只从 top 10 扩展

        added_count = 0
        for candidate in strong_candidates:
            if added_count >= _IMPORT_MAX_NEIGHBORS:
                break

            # outgoing: 这个文件依赖了谁？
            for dep in self.import_graph.dependencies_of(candidate.path):
                was_new = dep not in candidates
                self._add_evidence(
                    candidates,
                    dep,
                    CandidateEvidence(
                        source=CandidateSource.IMPORT_DEPENDENCY,
                        detail=f"被 '{candidate.path}' 依赖",
                        weight=_Weight.IMPORT_NEIGHBOR,
                    ),
                )
                if was_new:
                    added_count += 1

            # incoming: 谁依赖了这个文件？
            for dep in self.import_graph.dependents_of(candidate.path):
                was_new = dep not in candidates
                self._add_evidence(
                    candidates,
                    dep,
                    CandidateEvidence(
                        source=CandidateSource.IMPORT_DEPENDENT,
                        detail=f"依赖了 '{candidate.path}'",
                        weight=_Weight.IMPORT_NEIGHBOR,
                    ),
                )
                if was_new:
                    added_count += 1

    # ── 来源 7：测试文件 ─────────────────────────────────────

    def _add_test_pairs(
        self,
        candidates: dict[str, CandidateFile],
    ) -> None:
        """对已有候选文件，查找对应的测试文件。

        例如 auth/service.py → tests/auth/test_service.py

        测试文件不需要包含查询词——它和源文件有对应关系就应该纳入候选。
        """
        # 复制 key 列表，因为 _add_evidence 会修改 candidates
        found_paths = list(candidates.keys())

        for path in found_paths:
            for test_name in self._possible_test_names(path):
                if self._file_exists(test_name):
                    self._add_evidence(
                        candidates,
                        test_name,
                        CandidateEvidence(
                            source=CandidateSource.TEST_PAIR,
                            detail=f"测试文件对应 '{path}'",
                            weight=_Weight.TEST_PAIR,
                        ),
                    )

    @staticmethod
    def _possible_test_names(source_path: str) -> set[str]:
        """生成可能的测试文件名。

        auth/service.py →
            tests/auth/test_service.py
            tests/auth/service_test.py
            auth/test_service.py
            auth/service_test.py
        """
        p = Path(source_path)
        stem = p.stem      # "service"
        suffix = p.suffix  # ".py"
        parent = str(p.parent)

        return {
            f"tests/{parent}/test_{stem}{suffix}",
            f"tests/{parent}/{stem}_test{suffix}",
            f"{parent}/test_{stem}{suffix}",
            f"{parent}/{stem}_test{suffix}",
        }

    # ── 来源 8：重要配置 ─────────────────────────────────────

    # 条件触发关键词——查询中包含这些词时，才补充配置文件
    _CONFIG_TRIGGER_TERMS = {
        "依赖", "构建", "测试", "安装", "部署",
        "版本", "配置", "环境", "lint", "format",
        "dependencies", "build", "test", "deploy",
        "pip", "npm", "cargo", "go mod",
        "规则", "不允许", "手动修改", "生成代码", "generated",
        "agents.md", "do not modify",
    }

    _IMPORTANT_CONFIGS = [
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "AGENTS.md",
        "Makefile",
        "Dockerfile",
        ".gitignore",
    ]

    def _add_important_configs(
        self,
        analyzed: AnalyzedQuery,
        candidates: dict[str, CandidateFile],
    ) -> None:
        """如果查询涉及构建/配置/依赖，补充重要配置文件。

        不要无条件加入配置文件——用户说"修改 UserService.get_user"时
        不需要 pyproject.toml 出现在候选列表里。
        """
        query_text = analyzed.raw_query.lower()
        triggered = any(
            term.lower() in query_text
            for term in self._CONFIG_TRIGGER_TERMS
        )

        if not triggered:
            return

        for config_path in self._IMPORTANT_CONFIGS:
            if self._file_exists(config_path):
                self._add_evidence(
                    candidates,
                    config_path,
                    CandidateEvidence(
                        source=CandidateSource.IMPORTANT_CONFIG,
                        detail=f"重要配置文件 ({config_path})",
                        weight=_Weight.IMPORTANT_CONFIG,
                    ),
                )

    # ── 辅助 ─────────────────────────────────────────────────

    def _file_exists(self, path: str) -> bool:
        """检查文件路径是否在仓库快照中。"""
        for f in self.repository.files:
            if f.path == path:
                return True
        return False
