"""context 命令：构建查询上下文。"""
from __future__ import annotations

from pathlib import Path

from codeteam.application.build_context import (
    ContextApplicationService,
    ContextBuildReport,
)


def run_context(args) -> None:
    """执行 context 命令。"""
    root = Path(args.path).resolve()

    if not root.exists():
        print(f"路径不存在: {root}")
        return

    report = ContextApplicationService().execute(
        query=args.query,
        repository_root=root,
        top_k=args.top_k,
        budget_tokens=args.budget,
    )

    if args.format == "json":
        print(report.model_dump_json(indent=2))
    else:
        _render_text(report)


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

    if report.applicable_instructions:
        print("Applicable instructions")
        for instruction in report.applicable_instructions:
            print(f"  - {instruction}")
        print()

    if report.code_context:
        print("Code context")
        for item in report.code_context:
            print(
                f"  {item.path} "
                f"[{item.compression_level}, {item.token_count} tokens]"
            )
        print()

    if report.test_commands:
        print("Test commands")
        for cmd in report.test_commands:
            print(f"  [{cmd.category}] {cmd.command}")

    print()
    print("Token usage")
    print(f"  Budget:  {report.budget_tokens}")
    print(f"  Used:    {report.tokens_used}")
    print(f"  Before compression: {report.tokens_before_compression}")
    print(f"  After compression:  {report.tokens_after_compression}")
    if report.compression_actions:
        print("  Compression actions:")
        for action in report.compression_actions:
            print(f"    - {action}")
    if report.warning_count:
        print("Diagnostics")
        print(f"  Warnings: {report.warning_count}")
        for warning in report.diagnostics[:5]:
            print(f"    - {warning}")
    print()
    print(f"Candidates: {report.candidate_count}")
    print(f"Elapsed:    {report.elapsed_ms}ms")
