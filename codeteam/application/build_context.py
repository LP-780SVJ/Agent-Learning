"""
BuildContext: 上下文构建管线。

把 QueryAnalyzer → CandidateGenerator → FileRanker
  → RepoMapBuilder → ContextSelector 串成完整流程。
"""
from __future__ import annotations

import time
from pathlib import Path

from pydantic import BaseModel

from codeteam.context.compressor import ContextCompressor
from codeteam.context.models import CompressionLevel, ContextItem
from codeteam.context.selector import ContextSelector
from codeteam.instructions.loader import InstructionLoader
from codeteam.application.repository_index import build_repository_indexes
from codeteam.search.query_analyzer import QueryAnalyzer
from codeteam.search.candidate_generator import CandidateGenerator
from codeteam.ranking.file_ranker import FileRanker
from codeteam.repomap.builder import RepoMapBuilder
from codeteam.repomap.renderer import RepoMapRenderer
from codeteam.search.ripgrep import RipgrepClient
from codeteam.symbols.index import SymbolIndex
from codeteam.instructions.command_detector import (
    CommandDetector,
    DetectedCommand,
)
from codeteam.usage.token_counter import ApproximateTokenCounter


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


class CodeContextReport(BaseModel):
    path: str
    compression_level: str
    token_count: int
    content: str


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
    code_context: list[CodeContextReport] = []
    tokens_before_compression: int = 0
    tokens_after_compression: int = 0
    compression_actions: list[str] = []
    diagnostics: list[str] = []
    warning_count: int = 0
    failed_files: list[str] = []
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
        context_selector: ContextSelector | None = None,
        instruction_loader: InstructionLoader | None = None,
        token_counter: ApproximateTokenCounter | None = None,
    ) -> None:
        self.query_analyzer = query_analyzer
        self.candidate_generator = candidate_generator
        self.file_ranker = file_ranker
        self.symbol_index = symbol_index
        self.command_detector = command_detector
        self.repo_map_builder = repo_map_builder
        self.token_counter = token_counter or ApproximateTokenCounter()
        self.context_selector = context_selector or ContextSelector(
            ContextCompressor(self.token_counter),
            self.token_counter,
        )
        self.instruction_loader = instruction_loader or InstructionLoader()

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

        diagnostics: list[str] = []

        # ── 步骤 4：Repo Map ──
        # 最终上下文预算要同时覆盖 repo_map、instructions 和 code_context。
        # 因此 repo_map 不能独占完整预算，这里先给它一部分预算。
        repo_map_budget = self._repo_map_budget(budget_tokens)
        self.repo_map_builder.budget_tokens = repo_map_budget
        repo_map = self.repo_map_builder.build(
            ranked_files=ranked,
            symbol_index=self.symbol_index,
            query=query,
            mode="query",
        )
        renderer = RepoMapRenderer()
        repo_map_text = renderer.render(repo_map)

        # ── 步骤 5：加载适用规则 + 测试命令 ──
        top_paths = [file.path for file in top_files]
        instruction_bundle = self.instruction_loader.load(
            repository_root=repository_root,
            target_paths=top_paths,
        )
        diagnostics.extend(instruction_bundle.diagnostics)
        applicable_instructions = self._render_instruction_summary(
            instruction_bundle,
        )
        test_commands = self.command_detector.detect(
            repository_root=repository_root,
        )

        # ── 步骤 6：选择/压缩代码上下文 ──
        compression_actions: list[str] = []
        instruction_budget = self._instruction_budget(budget_tokens)
        applicable_instructions, instruction_actions = self._fit_strings_to_budget(
            values=applicable_instructions,
            budget_tokens=instruction_budget,
            label="applicable_instructions",
        )
        compression_actions.extend(instruction_actions)

        repo_map_budget = self._repo_map_text_budget(budget_tokens)
        repo_map_text, repo_actions = self._fit_text_to_budget(
            text=repo_map_text,
            budget_tokens=repo_map_budget,
            label="repo_map",
        )
        compression_actions.extend(repo_actions)

        repo_map_tokens = self.token_counter.count_text(repo_map_text)
        instruction_tokens = self._count_strings(applicable_instructions)
        code_budget = max(
            0,
            budget_tokens - repo_map_tokens - instruction_tokens,
        )

        context_candidates = self._build_context_items(
            ranked=ranked[:top_k],
            repository_root=repository_root,
        )
        tokens_before = sum(item.token_count for item in context_candidates)
        selected_items, select_actions = self.context_selector.select(
            candidates=context_candidates,
            budget_tokens=code_budget,
        )
        compression_actions.extend(select_actions)
        selected_items, final_fit_actions = self._fit_items_to_budget(
            items=selected_items,
            budget_tokens=code_budget,
        )
        compression_actions.extend(final_fit_actions)
        tokens_after = sum(item.token_count for item in selected_items)
        code_context = [
            CodeContextReport(
                path=item.path,
                compression_level=item.current_level.value,
                token_count=item.token_count,
                content=item.content,
            )
            for item in selected_items
        ]

        # ── 步骤 7：汇总 ──
        elapsed = int((time.monotonic() - t0) * 1000)
        failed_files = self._failed_files_from_diagnostics(diagnostics)

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
            applicable_instructions=applicable_instructions,
            code_context=code_context,
            tokens_before_compression=tokens_before,
            tokens_after_compression=tokens_after,
            compression_actions=compression_actions,
            diagnostics=diagnostics,
            warning_count=len(diagnostics),
            failed_files=failed_files,
            test_commands=test_commands,
            budget_tokens=budget_tokens,
            tokens_used=repo_map_tokens + instruction_tokens + tokens_after,
            candidate_count=len(candidates),
            elapsed_ms=elapsed,
        )

    def _build_context_items(
        self,
        *,
        ranked: list,
        repository_root: Path,
    ) -> list[ContextItem]:
        items: list[ContextItem] = []
        for file in ranked:
            full_path = repository_root / file.path
            if not full_path.exists() or not full_path.is_file():
                continue
            try:
                content = full_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            token_count = self.token_counter.count_text(content)
            items.append(
                ContextItem(
                    path=file.path,
                    relevance_score=file.final_score,
                    current_level=CompressionLevel.FULL_FILE,
                    minimum_level=CompressionLevel.PATH_ONLY,
                    content=content,
                    token_count=token_count,
                    selected_symbols=file.matched_symbols,
                    reason=", ".join(reason.reason for reason in file.evidence[:3]),
                )
            )
        return items

    @staticmethod
    def _repo_map_budget(total_budget: int) -> int:
        if total_budget <= 0:
            return 0
        return min(total_budget, max(16, total_budget // 3))

    @staticmethod
    def _instruction_budget(total_budget: int) -> int:
        if total_budget <= 0:
            return 0
        return min(96, max(0, total_budget // 5))

    @staticmethod
    def _repo_map_text_budget(total_budget: int) -> int:
        if total_budget <= 0:
            return 0
        return min(256, max(0, total_budget // 3))

    def _count_strings(self, values: list[str]) -> int:
        return sum(self.token_counter.count_text(value) for value in values)

    def _fit_strings_to_budget(
        self,
        *,
        values: list[str],
        budget_tokens: int,
        label: str,
    ) -> tuple[list[str], list[str]]:
        if budget_tokens <= 0:
            if values:
                return [], [f"{label}: 预算为 0，省略 {len(values)} 条"]
            return [], []

        fitted: list[str] = []
        used = 0
        omitted = 0
        for value in values:
            token_count = self.token_counter.count_text(value)
            if used + token_count <= budget_tokens:
                fitted.append(value)
                used += token_count
            else:
                omitted += 1

        actions = []
        if omitted:
            actions.append(
                f"{label}: 省略 {omitted} 条，避免超过 {budget_tokens} tokens"
            )
        return fitted, actions

    def _fit_text_to_budget(
        self,
        *,
        text: str,
        budget_tokens: int,
        label: str,
    ) -> tuple[str, list[str]]:
        if self.token_counter.count_text(text) <= budget_tokens:
            return text, []
        if budget_tokens <= 0:
            return "", [f"{label}: 预算为 0，省略全部内容"]

        lines: list[str] = []
        used = 0
        for line in text.splitlines():
            line_tokens = self.token_counter.count_text(line + "\n")
            if used + line_tokens > budget_tokens:
                break
            lines.append(line)
            used += line_tokens

        if not lines:
            return "", [f"{label}: 预算太小，无法保留任何行"]

        return (
            "\n".join(lines).rstrip() + "\n",
            [f"{label}: 裁剪到 {used} tokens，避免超过 {budget_tokens} tokens"],
        )

    @staticmethod
    def _fit_items_to_budget(
        *,
        items: list[ContextItem],
        budget_tokens: int,
    ) -> tuple[list[ContextItem], list[str]]:
        if budget_tokens <= 0:
            if items:
                return [], ["代码上下文预算为 0，省略所有 code_context"]
            return [], []

        fitted: list[ContextItem] = []
        used = 0
        actions: list[str] = []

        for item in sorted(items, key=lambda i: (-i.relevance_score, i.path)):
            if used + item.token_count <= budget_tokens:
                fitted.append(item)
                used += item.token_count
                continue
            actions.append(
                f"{item.path}: 省略，避免 code_context 超过剩余预算"
            )

        return fitted, actions

    @staticmethod
    def _failed_files_from_diagnostics(diagnostics: list[str]) -> list[str]:
        failed: list[str] = []
        for diagnostic in diagnostics:
            path = diagnostic.split(":", 1)[0]
            if path and "/" in path or path.endswith(".py"):
                failed.append(path)
        return failed

    @staticmethod
    def _render_instruction_summary(instruction_bundle) -> list[str]:
        rendered: list[str] = []
        seen: set[str] = set()
        for target, effective in instruction_bundle.by_target.items():
            for source in effective.sources:
                key = f"{target}:{source.path}"
                if key in seen:
                    continue
                seen.add(key)
                rendered.append(f"{target}: {source.path}")
        rendered.extend(
            f"diagnostic: {diagnostic}"
            for diagnostic in instruction_bundle.diagnostics
        )
        return rendered


class ContextApplicationService:
    def execute(
        self,
        *,
        query: str,
        repository_root: Path,
        top_k: int = 5,
        budget_tokens: int = 1024,
    ) -> ContextBuildReport:
        indexes = build_repository_context_indexes(repository_root)
        qa = QueryAnalyzer()
        cg = CandidateGenerator(
            analyzer=qa,
            ripgrep=RipgrepClient(),
            symbol_index=indexes["symbol_index"],
            filename_index=indexes["filename_index"],
            import_graph=indexes["import_graph"],
            repository=indexes["snapshot"],
        )
        builder = BuildContext(
            query_analyzer=qa,
            candidate_generator=cg,
            file_ranker=FileRanker(),
            symbol_index=indexes["symbol_index"],
            command_detector=CommandDetector(),
            repo_map_builder=RepoMapBuilder(
                renderer=RepoMapRenderer(),
                budget_tokens=budget_tokens,
            ),
        )
        report = builder.execute(
            query=query,
            repository_root=repository_root,
            search_path=str(repository_root),
            top_k=top_k,
            budget_tokens=budget_tokens,
        )
        diagnostics = list(indexes.get("diagnostics", [])) + report.diagnostics
        report.diagnostics = diagnostics
        report.warning_count = len(diagnostics)
        report.failed_files = list(
            dict.fromkeys(indexes.get("failed_files", []) + report.failed_files)
        )
        return report


def build_repository_context_indexes(repository_root: Path) -> dict:
    indexes = build_repository_indexes(repository_root)

    return {
        "snapshot": indexes.snapshot,
        "symbol_index": indexes.symbol_index,
        "filename_index": indexes.filename_index,
        "import_graph": indexes.import_graph,
        "diagnostics": indexes.diagnostics.warnings,
        "failed_files": indexes.diagnostics.failed_files,
    }
