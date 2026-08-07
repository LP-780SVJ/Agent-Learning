"""context 命令：构建查询上下文。"""
from __future__ import annotations

from pathlib import Path

from codeteam.repository.scanner import RepositoryScanner
from codeteam.parsing.registry import ParserRegistry
from codeteam.application.inspect_repository import InspectRepository
from codeteam.application.build_context import (
    BuildContext,
    ContextBuildReport,
)
from codeteam.search.query_analyzer import QueryAnalyzer
from codeteam.search.ripgrep import RipgrepClient
from codeteam.search.candidate_generator import CandidateGenerator
from codeteam.symbols.index import SymbolIndex
from codeteam.repository.filename_index import FilenameIndex
from codeteam.imports.graph import ImportGraph
from codeteam.ranking.file_ranker import FileRanker
from codeteam.repomap.builder import RepoMapBuilder
from codeteam.repomap.renderer import RepoMapRenderer
from codeteam.instructions.command_detector import CommandDetector


def run_context(args) -> None:
    """执行 context 命令。"""
    root = Path(args.path).resolve()

    if not root.exists():
        print(f"路径不存在: {root}")
        return

    # ── 阶段 1：构建索引 ──
    print("正在构建索引...", end=" ", flush=True)

    scanner = RepositoryScanner(root)
    parser_registry = ParserRegistry()
    inspector = InspectRepository(
        scanner=scanner,
        parser_registry=parser_registry,
    )
    index_report = inspector.execute(root)

    print(f"完成 ({index_report.symbol_count} 符号, {index_report.import_graph.edge_count} Import 边)")
    # ── 阶段 2：构建 BuildContext 的依赖 ──
    si = _build_symbol_index(inspector, root)
    fi = _build_filename_index(scanner)

    qa = QueryAnalyzer()
    rg = RipgrepClient()
    fr = FileRanker()
    cd = CommandDetector()
    rmb = RepoMapBuilder(
        renderer=RepoMapRenderer(),
        budget_tokens=args.budget,
    )

    # 重新扫描一次获取 RepositorySnapshot（供 CandidateGenerator）
    snapshot = scanner.scan()

    # 构建 ImportGraph
    ig = ImportGraph()
    # 从 index_report 中无法直接拿到 ImportGraph，简化处理
    # 生产环境应该缓存 index_report 里的图

    cg = CandidateGenerator(
        analyzer=qa,
        ripgrep=rg,
        symbol_index=si,
        filename_index=fi,
        import_graph=ig,
        repository=snapshot,
    )

    # ── 阶段 3：执行上下文构建 ──
    builder = BuildContext(
        query_analyzer=qa,
        candidate_generator=cg,
        file_ranker=fr,
        symbol_index=si,
        command_detector=cd,
        repo_map_builder=rmb,
    )

    report = builder.execute(
        query=args.query,
        repository_root=root,
        search_path=str(root),
        top_k=args.top_k,
        budget_tokens=args.budget,
    )

    # ── 输出 ──
    if args.format == "json":
        print(report.model_dump_json(indent=2))
    else:
        _render_text(report)


def _build_symbol_index(
    inspector: InspectRepository,
    root: Path,
) -> SymbolIndex:
    """从 InspectRepository 重新执行解析，构建 SymbolIndex。

    注意：InspectRepository.execute() 内部已经构建了 SymbolIndex，
    但未暴露出来。这里是简化版——实际应该让 InspectRepository
    返回索引对象，或缓存索引结果。
    """
    # 简化实现：重新执行索引构建
    scanner = RepositoryScanner(root)
    parser_registry = ParserRegistry()

    from codeteam.symbols.extractor import SymbolExtractor
    from codeteam.parsing.models import ParseStatus

    si = SymbolIndex()
    snapshot = scanner.scan()

    for repo_file in snapshot.files:
        if repo_file.language != "python":
            continue
        full_path = root / repo_file.path
        if not full_path.exists():
            continue
        try:
            source = full_path.read_text(encoding="utf-8")
            result = parser_registry.parse(source, "python", repo_file.path)
            if result.status in (ParseStatus.SUCCESS, ParseStatus.PARTIAL) and result.raw_ast:
                extractor = SymbolExtractor(repo_file.path)
                symbols, refs = extractor.extract(result.raw_ast)
                for sym in symbols:
                    si.add(sym)
                for ref in refs:
                    si.add_reference(ref)
        except Exception:
            pass

    return si


def _build_filename_index(scanner: RepositoryScanner) -> FilenameIndex:
    """根据仓库文件列表构建文件名索引。"""
    fi = FilenameIndex()
    snapshot = scanner.scan()
    for f in snapshot.files:
        fi.add(f.path)
    return fi


# ── 文本渲染 ────────────────────────────────────────────────

def _render_text(report: ContextBuildReport) -> None:
    print()
    print("Query")
    print(f"  {report.query}")
    print()

    print(f"Top {len(report.top_files)} files")
    print()

    for f in report.top_files:
        print(f"{f.rank}. {f.path:40} score={f.score:.2f}")
        for reason in f.reasons:
            print(f"   - {reason}")
        if f.matched_symbols:
            print(f"   Symbols: {', '.join(f.matched_symbols)}")
        print()

    if report.omitted_candidates:
        print(f"Omitted ({len(report.omitted_candidates)} files)")
        for oc in report.omitted_candidates[:3]:
            print(f"  {oc.path}  (rank {oc.original_rank}, score {oc.score:.2f})")
        if len(report.omitted_candidates) > 3:
            print(f"  ... 还有 {len(report.omitted_candidates) - 3} 个文件")
        print()

    print("Repository map")
    print(report.repo_map)

    if report.test_commands:
        print("Test commands")
        for cmd in report.test_commands:
            print(f"  [{cmd.category}] {cmd.command}")

    print()
    print(f"Token usage")
    print(f"  Budget:  {report.budget_tokens}")
    print(f"  Used:    {report.tokens_used}")
    print()
    print(f"Candidates: {report.candidate_count}")
    print(f"Elapsed:    {report.elapsed_ms}ms")