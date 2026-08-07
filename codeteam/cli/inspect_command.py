"""inspect-repo 命令：参数解析 + 调用 InspectRepository + 渲染输出。"""
from __future__ import annotations

import subprocess
from pathlib import Path

from codeteam.repository.scanner import RepositoryScanner
from codeteam.parsing.registry import ParserRegistry
from codeteam.application.inspect_repository import (
    InspectRepository,
    RepositoryInspectionReport,
)


def run_inspect(args) -> None:
    """执行 inspect-repo 命令。"""
    root = Path(args.path).resolve()

    if not root.exists():
        print(f"路径不存在: {root}")
        return

    # ── 构建依赖 ──
    scanner = RepositoryScanner(root)
    parser_registry = ParserRegistry()

    inspector = InspectRepository(
        scanner=scanner,
        parser_registry=parser_registry,
    )

    # ── 执行 ──
    report = inspector.execute(root)

    # ── 补充 Git 信息 ──
    report.head_commit = _get_head_commit(root)
    report.working_tree_dirty = _is_working_tree_dirty(root)

    # ── 输出 ──
    if args.format == "json":
        print(report.model_dump_json(indent=2))
    else:
        _render_text(report)


# ── Git 辅助 ────────────────────────────────────────────

def _get_head_commit(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()[:8] if result.returncode == 0 else None
    except Exception:
        return None


def _is_working_tree_dirty(root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


# ── 文本渲染 ────────────────────────────────────────────

def _render_text(report: RepositoryInspectionReport) -> None:
    print("Repository")
    print(f"  Root:       {report.repository_root}")
    print(f"  Commit:     {report.head_commit or 'N/A'}")
    print(f"  Dirty:      {'yes' if report.working_tree_dirty else 'no'}")
    print()

    print("Files")
    print(f"  Tracked:    {report.tracked_files}")
    print()

    if report.language_counts:
        print("Languages")
        for lang, count in sorted(report.language_counts.items()):
            print(f"  {lang:12} {count}")
        print()

    if report.role_counts:
        print("Roles")
        for role, count in sorted(report.role_counts.items()):
            print(f"  {role:12} {count}")
        print()

    ps = report.parse_statistics
    print("Parsing")
    print(f"  Success:     {ps.success}")
    print(f"  Partial:     {ps.partial}")
    print(f"  Failed:      {ps.failed}")
    print(f"  Skipped:     {ps.skipped}")
    print()

    if report.symbol_count > 0:
        print("Symbols")
        for kind, count in sorted(report.symbols_by_kind.items()):
            print(f"  {kind:12} {count}")
        print(f"  References:  {report.reference_count}")
        print()

    ig = report.import_graph
    print("Import graph")
    print(f"  Nodes:       {ig.node_count}")
    print(f"  Edges:       {ig.edge_count}")
    print(f"  Local:       {ig.resolved_local}")
    print(f"  External:    {ig.external}")
    print(f"  Unresolved:  {ig.unresolved}")
    print(f"  Dynamic:     {ig.dynamic}")
    print()

    if report.important_files:
        print("Important files")
        for f in report.important_files:
            print(f"  {f}")
        print()

    if report.warnings:
        print(f"Warnings ({len(report.warnings)} 条)")
        for w in report.warnings[:10]:
            print(f"  {w}")
        if len(report.warnings) > 10:
            print(f"  ... 还有 {len(report.warnings) - 10} 条")
        print()

    print(f"Scan:  {report.scan_duration_ms}ms")
    print(f"Index: {report.index_duration_ms}ms")