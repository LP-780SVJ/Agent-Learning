"""
InspectRepository: 仓库索引管线。

把 Scanner → Parser → Extractor → Index → Graph 串成完整流程。
单个文件解析失败不终止——收集警告，继续处理下一个。
"""
from __future__ import annotations

import time
from pathlib import Path

from pydantic import BaseModel

from codeteam.repository.scanner import RepositoryScanner
from codeteam.repository.models import RepositorySnapshot, FileKind
from codeteam.parsing.registry import ParserRegistry
from codeteam.parsing.models import ParseStatus
from codeteam.symbols.extractor import SymbolExtractor
from codeteam.symbols.index import SymbolIndex
from codeteam.symbols.models import SymbolKind
from codeteam.imports.extractor import ImportExtractor
from codeteam.imports.models import ImportRecord, ResolveStatus
from codeteam.imports.module_index import ModuleIndex
from codeteam.imports.resolver import PythonImportResolver
from codeteam.imports.graph import ImportGraph


# ── 数据模型 ──────────────────────────────────────────────

class ParseStatistics(BaseModel):
    """解析统计。"""
    success: int = 0
    partial: int = 0
    failed: int = 0
    skipped: int = 0


class ImportGraphStatistics(BaseModel):
    """Import 图统计。"""
    node_count: int = 0
    edge_count: int = 0
    resolved_local: int = 0
    external: int = 0
    unresolved: int = 0
    dynamic: int = 0


class RepositoryInspectionReport(BaseModel):
    """仓库检查报告。

    包含文件统计、解析统计、Symbol 统计和 Import 图统计。
    这是 inspect-repo 命令的数据输出——CLI 负责把它渲染成 text 或 json。
    """
    repository_root: str
    head_commit: str | None = None
    working_tree_dirty: bool = False

    # 文件统计
    tracked_files: int = 0
    untracked_files: int = 0
    ignored_files: int = 0

    # 分类统计
    language_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}

    # 解析统计
    parse_statistics: ParseStatistics = ParseStatistics()

    # Symbol 统计
    symbol_count: int = 0
    reference_count: int = 0
    symbols_by_kind: dict[str, int] = {}

    # Import 图统计
    import_graph: ImportGraphStatistics = ImportGraphStatistics()

    # 重要文件
    important_files: list[str] = []

    # 警告
    warnings: list[str] = []

    # 耗时
    scan_duration_ms: int = 0
    index_duration_ms: int = 0


# ── 应用服务 ──────────────────────────────────────────────

class InspectRepository:
    """仓库索引管线。

    用法：
        inspector = InspectRepository(
            scanner=RepositoryScanner(root),
            parser_registry=ParserRegistry(),
        )
        report = inspector.execute(Path("/repo"))
    """

    def __init__(
        self,
        *,
        scanner: RepositoryScanner,
        parser_registry: ParserRegistry,
    ) -> None:
        self.scanner = scanner
        self.parser_registry = parser_registry

    def execute(
        self,
        repository_root: Path,
    ) -> RepositoryInspectionReport:
        """执行完整的索引管线。

        流程：
        1. 扫描仓库 → RepositorySnapshot
        2. 遍历 Python 文件 → Parse → Extract Symbols → Extract Imports
        3. 构建 ModuleIndex → Resolve Imports → Build ImportGraph
        4. 汇总统计 → RepositoryInspectionReport

        单个文件失败不终止。警告收集到 report.warnings 中。
        """
        # ── 阶段 1：扫描仓库 ──
        t0 = time.monotonic()# 阶段计时起点
        snapshot = self.scanner.scan()
        scan_ms = int((time.monotonic() - t0) * 1000)

        # ── 阶段 2：解析 + 提取 ──
        t1 = time.monotonic()

        symbol_index = SymbolIndex()
        import_records: list[ImportRecord] = []
        parse_stats = ParseStatistics()
        warnings: list[str] = []

        # 筛选 Python 文件
        python_files = [
            f for f in snapshot.files
            if f.language == "python"
        ]

        for repo_file in python_files:
            try:
                # 读取源码
                full_path = repository_root / repo_file.path
                if not full_path.exists():
                    parse_stats.skipped += 1# 文件缺失时直接跳过当前文件
                    continue

                source_code = full_path.read_text(encoding="utf-8")

                # 解析
                parse_result = self.parser_registry.parse(
                    source_code, "python:strict", repo_file.path
                )

                if parse_result.status == ParseStatus.SUCCESS:
                    parse_stats.success += 1
                elif parse_result.status == ParseStatus.PARTIAL:
                    parse_stats.partial += 1
                    warnings.append(
                        f"{repo_file.path}: 部分解析成功"
                    )
                else:
                    parse_stats.failed += 1# 解析状态失败时跳过当前文件
                    continue

                # 提取符号
                if parse_result.raw_ast is not None:
                    extractor = SymbolExtractor(repo_file.path)
                    symbols, refs = extractor.extract(parse_result.raw_ast)
                    for sym in symbols:
                        symbol_index.add(sym)
                    for ref in refs:
                        symbol_index.add_reference(ref)

                # 提取 Import
                if parse_result.raw_ast is not None:
                    imp_extractor = ImportExtractor(repo_file.path)
                    records = imp_extractor.extract(parse_result.raw_ast)
                    import_records.extend(records)

            # 异常被捕获后不中断循环
            except SyntaxError:
                parse_stats.failed += 1
                warnings.append(f"{repo_file.path}: 语法错误")
            except UnicodeDecodeError:
                parse_stats.failed += 1
                warnings.append(f"{repo_file.path}: 编码错误")
            except Exception as exc:
                parse_stats.failed += 1
                warnings.append(f"{repo_file.path}: {exc}")

        # ── 阶段 3：Import 解析 + 构图 ──
        module_index = ModuleIndex(
            [f.path for f in snapshot.files]
        )
        resolver = PythonImportResolver(module_index)

        import_graph = ImportGraph()
        graph_stats = ImportGraphStatistics()

        for record in import_records:
            if record.kind.value == "dynamic":
                graph_stats.dynamic += 1

            resolution = resolver.resolve(record)

            if resolution.status == ResolveStatus.RESOLVED:
                graph_stats.resolved_local += 1
                import_graph.add_edge(
                    record.source_file,
                    resolution.resolved_file,
                )
            elif resolution.status == ResolveStatus.EXTERNAL:
                graph_stats.external += 1
            else:
                graph_stats.unresolved += 1

        # 统计图信息
        graph_stats.node_count = len(
            set(import_graph._outgoing.keys())
            | set(import_graph._incoming.keys())
        )
        graph_stats.edge_count = sum(
            len(targets)
            for targets in import_graph._outgoing.values()
        )

        # ── 阶段 4：汇总统计 ──
        index_ms = int((time.monotonic() - t1) * 1000)

        # 按 SymbolKind 统计
        kind_counts: dict[str, int] = {}
        for kind in SymbolKind:
            count = len(symbol_index._by_kind(kind.value))
            if count > 0:
                kind_counts[kind.value] = count

        # 按 FileKind 统计
        role_counts: dict[str, int] = {}
        for f in snapshot.files:
            key = f.kind.value
            role_counts[key] = role_counts.get(key, 0) + 1

        return RepositoryInspectionReport(
            repository_root=str(repository_root),
            # 文件统计
            tracked_files=sum(
                1 for f in snapshot.files
                if f.kind != FileKind.IGNORED
            ),
            language_counts=snapshot.languages,
            role_counts=role_counts,
            # 解析统计
            parse_statistics=parse_stats,
            # Symbol 统计
            symbol_count=symbol_index.total_symbols,
            reference_count=symbol_index.total_references,
            symbols_by_kind=kind_counts,
            # Import 图统计
            import_graph=graph_stats,
            # 重要文件
            important_files=snapshot.important_configs,
            # 警告
            warnings=warnings,
            # 耗时
            scan_duration_ms=scan_ms,
            index_duration_ms=index_ms,
        )