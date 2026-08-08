"""Shared repository indexing for context and eval pipelines."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from codeteam.imports.extractor import ImportExtractor
from codeteam.imports.graph import ImportGraph
from codeteam.imports.models import ImportRecord, ResolveStatus
from codeteam.imports.module_index import ModuleIndex
from codeteam.imports.resolver import PythonImportResolver
from codeteam.parsing.models import ParseStatus
from codeteam.parsing.registry import ParserRegistry
from codeteam.repository.filename_index import FilenameIndex
from codeteam.repository.models import RepositorySnapshot
from codeteam.repository.scanner import RepositoryScanner
from codeteam.symbols.extractor import SymbolExtractor
from codeteam.symbols.index import SymbolIndex


@dataclass
class IndexDiagnostics:
    warnings: list[str] = field(default_factory=list)
    failed_files: list[str] = field(default_factory=list)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def summary(self, limit: int = 5) -> dict[str, object]:
        return {
            "warning_count": self.warning_count,
            "failed_files": list(self.failed_files),
            "warnings": self.warnings[:limit],
        }


@dataclass
class RepositoryIndexes:
    snapshot: RepositorySnapshot
    symbol_index: SymbolIndex
    filename_index: FilenameIndex
    import_graph: ImportGraph
    diagnostics: IndexDiagnostics


def build_repository_indexes(repository_root: Path) -> RepositoryIndexes:
    scanner = RepositoryScanner(repository_root)
    snapshot = scanner.scan()
    parser_registry = ParserRegistry()

    symbol_index = SymbolIndex()
    import_records: list[ImportRecord] = []
    diagnostics = IndexDiagnostics()

    for repo_file in snapshot.files:
        if repo_file.language != "python":
            continue

        full_path = repository_root / repo_file.path
        if not full_path.exists():
            diagnostics.warnings.append(f"{repo_file.path}: 文件不存在，跳过索引")
            diagnostics.failed_files.append(repo_file.path)
            continue

        try:
            source = full_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            _record_failure(diagnostics, repo_file.path, f"编码错误: {exc}")
            continue
        except OSError as exc:
            _record_failure(diagnostics, repo_file.path, f"读取失败: {exc}")
            continue

        try:
            result = parser_registry.parse(source, "python:strict", repo_file.path)
        except Exception as exc:
            _record_failure(diagnostics, repo_file.path, f"解析异常: {exc}")
            continue

        if result.status == ParseStatus.FAILED:
            _record_failure(diagnostics, repo_file.path, "解析失败")
            continue
        if result.status == ParseStatus.PARTIAL:
            diagnostics.warnings.append(f"{repo_file.path}: 部分解析成功")
        if result.raw_ast is None:
            _record_failure(diagnostics, repo_file.path, "缺少 AST，跳过符号和 import 提取")
            continue

        try:
            extractor = SymbolExtractor(repo_file.path)
            symbols, refs = extractor.extract(result.raw_ast)
            for symbol in symbols:
                symbol_index.add(symbol)
            for ref in refs:
                symbol_index.add_reference(ref)
        except Exception as exc:
            _record_failure(diagnostics, repo_file.path, f"符号提取失败: {exc}")

        try:
            import_records.extend(
                ImportExtractor(repo_file.path).extract(result.raw_ast)
            )
        except Exception as exc:
            _record_failure(diagnostics, repo_file.path, f"import 提取失败: {exc}")

    import_graph = ImportGraph()
    resolver = PythonImportResolver(ModuleIndex([file.path for file in snapshot.files]))
    for record in import_records:
        try:
            resolution = resolver.resolve(record)
        except Exception as exc:
            diagnostics.warnings.append(
                f"{record.source_file}: import 解析失败 ({record.module}): {exc}"
            )
            continue
        if resolution.status == ResolveStatus.RESOLVED and resolution.resolved_file:
            import_graph.add_edge(record.source_file, resolution.resolved_file)

    filename_index = FilenameIndex()
    for file in snapshot.files:
        filename_index.add(file.path)

    return RepositoryIndexes(
        snapshot=snapshot,
        symbol_index=symbol_index,
        filename_index=filename_index,
        import_graph=import_graph,
        diagnostics=diagnostics,
    )


def _record_failure(
    diagnostics: IndexDiagnostics,
    path: str,
    message: str,
) -> None:
    diagnostics.warnings.append(f"{path}: {message}")
    if path not in diagnostics.failed_files:
        diagnostics.failed_files.append(path)
