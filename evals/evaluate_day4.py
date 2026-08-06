"""Day 4 检索评测脚本。

对 file_retrieval_day4.jsonl 中的每条查询，
分别用 Filename、Ripgrep、Symbol 三组基线进行评估。

指标：
- Candidate Recall: 候选集合中命中的 Gold 文件数 / Gold 文件总数
- Hit: 候选中是否至少出现一个 Gold 文件（1=命中，0=未命中）
- Candidate Size: 平均返回多少候选文件
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 确保项目根目录在 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from codeteam.repository.filename_index import FilenameIndex
from codeteam.repository.models import (
    FileKind,
    RepositoryFile,
    RepositorySnapshot,
)
from codeteam.search.models import (
    CandidateSource,
    CandidateFile,
    SearchMode,
    SearchQuery,
)
from codeteam.search.query_analyzer import QueryAnalyzer
from codeteam.search.ripgrep import RipgrepClient
from codeteam.symbols.index import SymbolIndex
from codeteam.symbols.models import (
    Symbol,
    SymbolKind,
    SymbolLocation,
)


# ── 构建测试仓库 ────────────────────────────────────────────────

def build_filename_index() -> FilenameIndex:
    """用 fixture 文件路径构建 FilenameIndex。"""
    fi = FilenameIndex()
    paths = [
        "auth/service.py",
        "auth/repository.py",
        "errors.py",
        "中文注释.py",
        "README.md",
    ]
    fi.add_batch(paths)
    return fi


def build_symbol_index() -> SymbolIndex:
    """填充已知符号。"""
    si = SymbolIndex()

    si.add(Symbol(
        name="UserService", kind=SymbolKind.CLASS,
        location=SymbolLocation(file="auth/service.py", line=3, column=0),
        qualified_name="UserService",
    ))
    si.add(Symbol(
        name="create_user", kind=SymbolKind.METHOD,
        location=SymbolLocation(file="auth/service.py", line=5, column=4),
        qualified_name="UserService.create_user",
    ))
    si.add(Symbol(
        name="get_user", kind=SymbolKind.METHOD,
        location=SymbolLocation(file="auth/service.py", line=9, column=4),
        qualified_name="UserService.get_user",
    ))
    si.add(Symbol(
        name="InvalidRefreshTokenError", kind=SymbolKind.CLASS,
        location=SymbolLocation(file="auth/service.py", line=17, column=0),
        qualified_name="InvalidRefreshTokenError",
    ))
    si.add(Symbol(
        name="UserRepository", kind=SymbolKind.CLASS,
        location=SymbolLocation(file="auth/repository.py", line=3, column=0),
        qualified_name="UserRepository",
    ))
    si.add(Symbol(
        name="ServiceError", kind=SymbolKind.CLASS,
        location=SymbolLocation(file="errors.py", line=3, column=0),
        qualified_name="ServiceError",
    ))
    si.add(Symbol(
        name="TIMEOUT_ERROR", kind=SymbolKind.VARIABLE,
        location=SymbolLocation(file="errors.py", line=10, column=0),
        qualified_name="TIMEOUT_ERROR",
    ))
    si.add(Symbol(
        name="DatabaseError", kind=SymbolKind.CLASS,
        location=SymbolLocation(file="errors.py", line=13, column=0),
        qualified_name="DatabaseError",
    ))
    si.add(Symbol(
        name="登录验证", kind=SymbolKind.FUNCTION,
        location=SymbolLocation(file="中文注释.py", line=6, column=0),
        qualified_name="登录验证",
    ))
    si.add(Symbol(
        name="用户服务", kind=SymbolKind.CLASS,
        location=SymbolLocation(file="中文注释.py", line=12, column=0),
        qualified_name="用户服务",
    ))
    return si


# ── 指标计算 ────────────────────────────────────────────────────

def compute_metrics(
    results: list[dict],
    gold_files: list[str],
) -> dict:
    """对单次查询计算指标。

    Args:
        results: 返回的候选文件列表（dict 或 CandidateFile）
        gold_files: 正确答案文件列表

    Returns:
        dict with: recall, hit, candidate_size
    """
    gold_set = set(gold_files)
    result_paths = set()

    for r in results:
        if isinstance(r, dict):
            result_paths.add(r.get("path", ""))
        elif hasattr(r, "path"):
            result_paths.add(r.path)

    matched = result_paths & gold_set
    recall = len(matched) / len(gold_set) if gold_set else 0.0
    hit = 1 if len(matched) > 0 else 0
    candidate_size = len(results)

    return {
        "recall": round(recall, 4),
        "hit": hit,
        "candidate_size": candidate_size,
    }


# ── 三组基线 ────────────────────────────────────────────────────

def baseline_filename(
    query: str,
    filename_index: FilenameIndex,
    analyzer: QueryAnalyzer,
) -> list[dict]:
    """只使用文件名和路径 Token。"""
    analyzed = analyzer.analyze(query)
    all_terms = analyzed.primary_terms + analyzed.secondary_terms

    seen: set[str] = set()
    results: list[dict] = []
    for term in all_terms:
        files = filename_index.search(term)
        for f in files:
            if f not in seen:
                seen.add(f)
                results.append({"path": f})

    return results


def baseline_ripgrep(
    query: str,
    search_path: str,
    client: RipgrepClient,
    analyzer: QueryAnalyzer,
) -> list[dict]:
    """只使用 QueryAnalyzer + 文本搜索。"""
    analyzed = analyzer.analyze(query)

    seen: set[str] = set()
    results: list[dict] = []

    # Primary terms
    for term in analyzed.primary_terms:
        sq = SearchQuery(pattern=term, mode=SearchMode.LITERAL, max_results=50)
        execution = client.search(sq, search_path)
        for match in execution.matches:
            if match.file_path not in seen:
                seen.add(match.file_path)
                results.append({"path": match.file_path})

    # Secondary terms
    for term in analyzed.secondary_terms:
        sq = SearchQuery(pattern=term, mode=SearchMode.LITERAL, max_results=20)
        execution = client.search(sq, search_path)
        for match in execution.matches:
            if match.file_path not in seen:
                seen.add(match.file_path)
                results.append({"path": match.file_path})

    return results


def baseline_symbol(
    query: str,
    symbol_index: SymbolIndex,
    analyzer: QueryAnalyzer,
) -> list[dict]:
    """只使用 SymbolIndex exact/prefix。"""
    analyzed = analyzer.analyze(query)

    seen: set[str] = set()
    results: list[dict] = []

    for identifier in analyzed.identifiers:
        exact_hits = symbol_index.find_exact(identifier)
        if exact_hits:
            for sym in exact_hits:
                if sym.location.file not in seen:
                    seen.add(sym.location.file)
                    results.append({"path": sym.location.file})
        else:
            prefix_hits = symbol_index.find_prefix(identifier)
            for sym in prefix_hits:
                if sym.location.file not in seen:
                    seen.add(sym.location.file)
                    results.append({"path": sym.location.file})

    return results


# ── 主程序 ──────────────────────────────────────────────────────

def main() -> None:
    """运行评测。"""

    # 数据路径
    eval_file = Path(__file__).resolve().parent / "file_retrieval_day4.jsonl"
    fixture_dir = (
        Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "search_repo"
    )

    if not eval_file.exists():
        print(f"ERROR: {eval_file} not found")
        sys.exit(1)
    if not fixture_dir.exists():
        print(f"ERROR: fixture dir {fixture_dir} not found")
        sys.exit(1)

    # 加载评测数据
    eval_tasks: list[dict] = []
    with open(eval_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                eval_tasks.append(json.loads(line))

    print(f"Loaded {len(eval_tasks)} evaluation tasks.\n")

    # 构建基础设施
    filename_index = build_filename_index()
    symbol_index = build_symbol_index()
    analyzer = QueryAnalyzer()
    client = RipgrepClient(timeout_seconds=30.0)

    # 为 ripgrep 准备 fixture repo（复制到 tmp 或直接使用源文件）
    search_path = str(fixture_dir)

    all_results: list[dict] = []

    for task in eval_tasks:
        task_id = task["id"]
        query = task["query"]
        gold_files = task["gold_files"]
        category = task.get("category", "unknown")

        # 三组基线
        fn_results = baseline_filename(query, filename_index, analyzer)
        rg_results = baseline_ripgrep(query, search_path, client, analyzer)
        sym_results = baseline_symbol(query, symbol_index, analyzer)

        fn_metrics = compute_metrics(fn_results, gold_files)
        rg_metrics = compute_metrics(rg_results, gold_files)
        sym_metrics = compute_metrics(sym_results, gold_files)

        print(f"--- {task_id} ({category}) ---")
        print(f"  Query: {query}")
        print(f"  Gold: {gold_files}")
        print(f"  Filename: recall={fn_metrics['recall']:.2%}, "
              f"hit={fn_metrics['hit']}, size={fn_metrics['candidate_size']}")
        print(f"  Ripgrep:  recall={rg_metrics['recall']:.2%}, "
              f"hit={rg_metrics['hit']}, size={rg_metrics['candidate_size']}")
        print(f"  Symbol:   recall={sym_metrics['recall']:.2%}, "
              f"hit={sym_metrics['hit']}, size={sym_metrics['candidate_size']}")
        print()

        all_results.append({
            "id": task_id,
            "query": query,
            "category": category,
            "gold_files": gold_files,
            "filename": fn_metrics,
            "ripgrep": rg_metrics,
            "symbol": sym_metrics,
        })

    # ── 汇总 ──
    n = len(all_results)
    if n == 0:
        return

    fn_avg_recall = sum(r["filename"]["recall"] for r in all_results) / n
    rg_avg_recall = sum(r["ripgrep"]["recall"] for r in all_results) / n
    sym_avg_recall = sum(r["symbol"]["recall"] for r in all_results) / n

    fn_hit_rate = sum(r["filename"]["hit"] for r in all_results) / n
    rg_hit_rate = sum(r["ripgrep"]["hit"] for r in all_results) / n
    sym_hit_rate = sum(r["symbol"]["hit"] for r in all_results) / n

    fn_avg_size = sum(r["filename"]["candidate_size"] for r in all_results) / n
    rg_avg_size = sum(r["ripgrep"]["candidate_size"] for r in all_results) / n
    sym_avg_size = sum(r["symbol"]["candidate_size"] for r in all_results) / n

    print("=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"{'Baseline':<12} {'Recall':>8} {'Hit Rate':>10} {'Avg Size':>10}")
    print(f"{'Filename':<12} {fn_avg_recall:>7.2%} {fn_hit_rate:>9.2%} {fn_avg_size:>9.1f}")
    print(f"{'Ripgrep':<12} {rg_avg_recall:>7.2%} {rg_hit_rate:>9.2%} {rg_avg_size:>9.1f}")
    print(f"{'Symbol':<12} {sym_avg_recall:>7.2%} {sym_hit_rate:>9.2%} {sym_avg_size:>9.1f}")

    # ── 写入 artifact ──
    artifacts_dir = (
        Path(__file__).resolve().parents[1] / "artifacts"
    )
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifacts_dir / "search_results.json"

    artifact = {
        "eval_results": all_results,
        "summary": {
            "filename": {
                "avg_recall": fn_avg_recall,
                "hit_rate": fn_hit_rate,
                "avg_candidate_size": fn_avg_size,
            },
            "ripgrep": {
                "avg_recall": rg_avg_recall,
                "hit_rate": rg_hit_rate,
                "avg_candidate_size": rg_avg_size,
            },
            "symbol": {
                "avg_recall": sym_avg_recall,
                "hit_rate": sym_hit_rate,
                "avg_candidate_size": sym_avg_size,
            },
        },
    }

    with open(artifact_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, ensure_ascii=False, indent=2)

    print(f"\nArtifact written to: {artifact_path}")


if __name__ == "__main__":
    main()
