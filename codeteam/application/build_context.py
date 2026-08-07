"""
BuildContext: 上下文构建管线。

把 QueryAnalyzer → CandidateGenerator → FileRanker
  → RepoMapBuilder → ContextSelector 串成完整流程。
"""
from __future__ import annotations

import time
from pathlib import Path

from pydantic import BaseModel

from codeteam.search.query_analyzer import QueryAnalyzer
from codeteam.search.candidate_generator import CandidateGenerator
from codeteam.ranking.file_ranker import FileRanker
from codeteam.ranking.models import RankedFile
from codeteam.repomap.builder import RepoMapBuilder
from codeteam.repomap.renderer import RepoMapRenderer
from codeteam.symbols.index import SymbolIndex
from codeteam.instructions.command_detector import (
    CommandDetector,
    DetectedCommand,
)


# ── 数据模型 ──────────────────────────────────────────────

class SelectedFileReport(BaseModel):
    """一个被选入 Top K 的文件。"""
    path: str
    rank: int
    score: float

    reasons: list[str] = []
    matched_symbols: list[str] = []
    matched_lines: list[int] = []


class OmittedCandidate(BaseModel):
    """一个被省略的候选文件。"""
    path: str
    original_rank: int
    score: float
    reason: str = ""


class ContextBuildReport(BaseModel):
    """上下文构建报告。

    这是 context 命令的数据输出——CLI 负责渲染成 text 或 json。
    """
    query: str
    analyzed_query: dict = {}

    top_files: list[SelectedFileReport] = []
    omitted_candidates: list[OmittedCandidate] = []

    repo_map: str = ""

    applicable_instructions: list[str] = []
    test_commands: list[DetectedCommand] = []

    budget_tokens: int = 0
    tokens_used: int = 0

    candidate_count: int = 0
    elapsed_ms: int = 0


# ── 应用服务 ──────────────────────────────────────────────

class BuildContext:
    """上下文构建管线。

    用法：
        builder = BuildContext(
            query_analyzer=qa,
            candidate_generator=cg,
            file_ranker=fr,
            symbol_index=si,
            command_detector=cd,
            repo_map_builder=rmb,
        )
        report = builder.execute(
            query="修复 refresh token 过期",
            repository_root=Path("/repo"),
            search_path="/repo",
        )
    """

    def __init__(
        self,
        *,
        query_analyzer: QueryAnalyzer,
        candidate_generator: CandidateGenerator,
        file_ranker: FileRanker,
        symbol_index: SymbolIndex,
        command_detector: CommandDetector,
        repo_map_builder: RepoMapBuilder,
    ) -> None:
        self.query_analyzer = query_analyzer
        self.candidate_generator = candidate_generator
        self.file_ranker = file_ranker
        self.symbol_index = symbol_index
        self.command_detector = command_detector
        self.repo_map_builder = repo_map_builder

    def execute(
        self,
        *,
        query: str,
        repository_root: Path,
        search_path: str = ".",
        top_k: int = 5,
        budget_tokens: int = 1024,
    ) -> ContextBuildReport:
        """执行完整的上下文构建管线。

        流程：
        1. 分析查询
        2. 生成候选 → 排序
        3. 选 Top K 文件
        4. 构建 Repo Map
        5. 检测测试命令
        6. 汇总报告
        """
        t0 = time.monotonic()

        # ── 步骤 1：分析查询 ──
        analyzed = self.query_analyzer.analyze(query)

        # ── 步骤 2：召回 + 排序 ──
        candidates = self.candidate_generator.generate(
            query, search_path=search_path
        )
        ranked = self.file_ranker.rank(candidates)

        # ── 步骤 3：Top K 文件 ──
        top_files: list[SelectedFileReport] = []
        for r in ranked[:top_k]:
            top_files.append(
                SelectedFileReport(
                    path=r.path,
                    rank=r.rank,
                    score=r.final_score,
                    reasons=[
                        e.reason for e in r.evidence[:3]
                    ],
                    matched_symbols=r.matched_symbols,
                    matched_lines=r.matched_lines,
                )
            )

        # 被省略的候选
        omitted: list[OmittedCandidate] = []
        for r in ranked[top_k:]:
            reason = (
                f"Rank {r.rank}: score {r.final_score:.2f} "
                f"低于 Top {top_k} 阈值"
            )
            omitted.append(
                OmittedCandidate(
                    path=r.path,
                    original_rank=r.rank,
                    score=r.final_score,
                    reason=reason,
                )
            )

        # ── 步骤 4：Repo Map ──
        self.repo_map_builder.budget_tokens = budget_tokens
        repo_map = self.repo_map_builder.build(
            ranked_files=ranked,
            symbol_index=self.symbol_index,
            query=query,
            mode="query",
        )
        renderer = RepoMapRenderer()
        repo_map_text = renderer.render(repo_map)

        # ── 步骤 5：测试命令 ──
        test_commands = self.command_detector.detect(
            repository_root=repository_root,
        )

        # ── 步骤 6：汇总 ──
        elapsed = int((time.monotonic() - t0) * 1000)

        return ContextBuildReport(
            query=query,
            analyzed_query={
                "primary_terms": analyzed.primary_terms,
                "secondary_terms": analyzed.secondary_terms,
                "identifiers": analyzed.identifiers,
                "quoted_literals": analyzed.quoted_literals,
                "paths": analyzed.paths,
                "exception_names": analyzed.exception_names,
            },
            top_files=top_files,
            omitted_candidates=omitted,
            repo_map=repo_map_text,
            applicable_instructions=[],
            test_commands=test_commands,
            budget_tokens=budget_tokens,
            tokens_used=repo_map.used_tokens,
            candidate_count=len(candidates),
            elapsed_ms=elapsed,
        )
