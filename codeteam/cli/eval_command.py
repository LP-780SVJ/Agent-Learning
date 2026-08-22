"""eval 命令：运行检索评测实验。"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from codeteam.application.repository_index import (
    RepositoryIndexes,
    build_repository_indexes,
)
from codeteam.evaluation.runner import (
    RetrievalEvaluator,
    load_eval_cases,
    save_results,
)
from codeteam.imports.graph import ImportGraph
from codeteam.ranking.file_ranker import FileRanker
from codeteam.ranking.models import RankingWeights
from codeteam.search.candidate_generator import CandidateGenerator
from codeteam.search.models import SearchExecution, SearchQuery
from codeteam.search.query_analyzer import QueryAnalyzer
from codeteam.search.ripgrep import RipgrepClient
from codeteam.symbols.index import SymbolIndex

VALID_METHODS = {"filename", "ripgrep", "ripgrep_symbol", "hybrid"}
CANDIDATE_LIMIT = 50
EVAL_CONTEXT_BUDGET = 0


class _DisabledRipgrepClient(RipgrepClient):
    """No-op ripgrep client for eval methods that intentionally disable text search."""

    def search(
        self,
        query: SearchQuery,
        search_path: str = ".",
    ) -> SearchExecution:
        return SearchExecution(pattern=query.pattern)


def run_eval(args) -> None:
    """执行 eval 命令。"""
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"评测数据文件不存在: {dataset_path}")
        sys.exit(1)

    repo_root = Path(args.repo).resolve()
    if not repo_root.exists():
        print(f"仓库路径不存在: {repo_root}")
        sys.exit(1)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    unknown_methods = sorted(set(methods) - VALID_METHODS)
    if unknown_methods:
        print(
            "未知评测方法: "
            f"{', '.join(unknown_methods)}. "
            f"可用方法: {', '.join(sorted(VALID_METHODS))}"
        )
        sys.exit(1)

    print(f"仓库:    {repo_root}")
    print(f"数据集:  {dataset_path}")
    cases = load_eval_cases(dataset_path)
    print(f"案例数:  {len(cases)}")
    print(f"方法:    {', '.join(methods)}")
    print()

    had_error = False
    indexes = build_repository_indexes(repo_root)

    for method in methods:
        print(f"=== {method} ===")

        retrieve_func = _build_retriever(
            method,
            repo_root,
            indexes=indexes,
            candidate_limit=CANDIDATE_LIMIT,
        )

        evaluator = RetrievalEvaluator(retrieve_func)
        results = evaluator.evaluate(
            cases=cases,
            method_name=method,
            top_k=5,
        )

        output_path = output_dir / f"{method}.jsonl"
        save_results(results, output_path)
        manifest_path = output_dir / f"{method}.manifest.json"
        save_run_manifest(
            output_path=manifest_path,
            repo_root=repo_root,
            dataset_path=dataset_path,
            method=method,
            top_k=5,
            candidate_limit=CANDIDATE_LIMIT,
            context_budget=EVAL_CONTEXT_BUDGET,
            diagnostics_summary=indexes.diagnostics.summary(),
            command_argv=sys.argv,
        )

        avg_recall = sum(r.recall_at_5 for r in results) / len(results) if results else 0
        avg_hit = sum(r.hit_at_5 for r in results) / len(results) if results else 0
        avg_latency = sum(r.latency_ms for r in results) / len(results) if results else 0

        print(f"  平均 Recall@5: {avg_recall:.3f}")
        print(f"  平均 Hit@5:    {avg_hit:.3f}")
        print(f"  平均延迟:      {avg_latency:.0f}ms")
        print(f"  结果已保存:    {output_path}")
        print(f"  Manifest:      {manifest_path}")
        failed = [r for r in results if r.error]
        if failed:
            print(f"  检索失败:      {len(failed)} cases")
            for result in failed[:3]:
                print(f"    - {result.case_id}: {result.error}")
            had_error = True
        print()

    if had_error:
        sys.exit(1)


def save_run_manifest(
    *,
    output_path: Path,
    repo_root: Path,
    dataset_path: Path,
    method: str,
    top_k: int,
    candidate_limit: int = CANDIDATE_LIMIT,
    context_budget: int = EVAL_CONTEXT_BUDGET,
    diagnostics_summary: dict[str, object] | None = None,
    command_argv: list[str] | None = None,
) -> None:
    """保存本次 eval 运行的可追溯元数据。"""
    manifest = {
        "repo_path": str(repo_root),
        "head_commit": _git_head_commit(repo_root),
        "dirty": _git_dirty(repo_root),
        "dirty_files": _git_dirty_files(repo_root),
        "dirty_summary": _git_dirty_summary(repo_root),
        "dataset_path": str(dataset_path),
        "dataset_hash": _sha256_file(dataset_path),
        "command_argv": command_argv or list(sys.argv),
        "command": " ".join(command_argv or sys.argv),
        "python_version": sys.version.split()[0],
        "ripgrep_version": _ripgrep_version(),
        "parser_version": _parser_version(),
        "method": method,
        "top_k": top_k,
        "candidate_limit": candidate_limit,
        "context_budget": context_budget,
        "ranking_weights": asdict(RankingWeights()),
        "diagnostics_summary": diagnostics_summary or {},
        "started_at": datetime.now(UTC).isoformat(),
    }
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head_commit(repo_root: Path) -> str | None:
    result = _run_git(repo_root, "rev-parse", "HEAD")
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _git_dirty(repo_root: Path) -> bool | None:
    result = _run_git(repo_root, "status", "--porcelain")
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def _git_dirty_files(repo_root: Path) -> list[str]:
    result = _run_git(repo_root, "status", "--porcelain")
    if result.returncode != 0:
        return []
    files: list[str] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        files.append(line[3:] if len(line) > 3 else line)
    return files


def _git_dirty_summary(repo_root: Path) -> dict[str, object]:
    files = _git_dirty_files(repo_root)
    return {
        "count": len(files),
        "files": files[:20],
        "truncated": len(files) > 20,
    }


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _ripgrep_version() -> str | None:
    result = subprocess.run(
        ["rg", "--version"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.splitlines()[0] if result.stdout else None


def _parser_version() -> str | None:
    try:
        import tree_sitter
    except ImportError:
        return None
    return getattr(tree_sitter, "__version__", "tree_sitter-installed")


def _build_retriever(
    method: str,
    repo_root: Path,
    *,
    indexes: RepositoryIndexes | None = None,
    candidate_limit: int = CANDIDATE_LIMIT,
):
    """根据方法名构建检索函数。

    四种方法：
    - filename:       只用文件名索引
    - ripgrep:        文件名 + 文本搜索
    - ripgrep_symbol: 文件名 + 文本搜索 + 符号索引
    - hybrid:         全部（文件名 + 文本 + 符号 + Import 图 + FileRanker）
    """

    if method not in VALID_METHODS:
        raise ValueError(
            f"unknown eval method {method!r}; expected one of "
            f"{', '.join(sorted(VALID_METHODS))}"
        )

    indexes = indexes or build_repository_indexes(repo_root)

    def _run_pipeline(
        query: str,
        top_k: int,
        *,
        use_ripgrep: bool,
        use_symbol: bool,
        use_import_graph: bool,
    ) -> list[str]:
        qa = QueryAnalyzer()
        ripgrep_client = (
            RipgrepClient() if use_ripgrep else _DisabledRipgrepClient()
        )
        cg = CandidateGenerator(
            analyzer=qa,
            ripgrep=ripgrep_client,
            symbol_index=indexes.symbol_index if use_symbol else SymbolIndex(),
            filename_index=indexes.filename_index,
            import_graph=indexes.import_graph if use_import_graph else ImportGraph(),
            repository=indexes.snapshot,
        )
        candidates = cg.generate(
            query,
            search_path=str(repo_root),
            candidate_limit=candidate_limit,
        )
        ranked = FileRanker().rank(candidates)
        return [file.path for file in ranked[:max(top_k, candidate_limit)]]

    if method == "filename":
        def retrieve(q: str, k: int = 5) -> list[str]:
            return _run_pipeline(q, k, use_ripgrep=False, use_symbol=False, use_import_graph=False)
        return retrieve

    elif method == "ripgrep":
        def retrieve(q: str, k: int = 5) -> list[str]:
            return _run_pipeline(q, k, use_ripgrep=True, use_symbol=False, use_import_graph=False)
        return retrieve

    elif method == "ripgrep_symbol":
        def retrieve(q: str, k: int = 5) -> list[str]:
            return _run_pipeline(q, k, use_ripgrep=True, use_symbol=True, use_import_graph=False)
        return retrieve

    elif method == "hybrid":
        def retrieve(q: str, k: int = 5) -> list[str]:
            return _run_pipeline(q, k, use_ripgrep=True, use_symbol=True, use_import_graph=True)
        return retrieve
