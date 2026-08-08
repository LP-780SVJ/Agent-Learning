"""检索评测运行器：批量运行评测并保存结果。"""
from __future__ import annotations

import json
import time
from pathlib import Path

from codeteam.evaluation.models import EvalCase, EvalResult
from codeteam.evaluation.metrics import evaluate_query


class RetrievalEvaluator:
    """检索系统评测器。

    用法：
        evaluator = RetrievalEvaluator(retrieve_func)
        results = evaluator.evaluate(
            cases=eval_cases,
            method_name="hybrid",
            top_k=5,
        )
    """

    def __init__(self, retrieve_func):
        """初始化评测器。

        Args:
            retrieve_func: 检索函数，签名为
                (query: str, top_k: int) -> list[str]
                返回预测的文件路径列表。
        """
        self._retrieve = retrieve_func

    def evaluate(
        self,
        *,
        cases: list[EvalCase],
        method_name: str,
        top_k: int = 5,
    ) -> list[EvalResult]:
        """批量评测。

        Args:
            cases:       评测案例列表。
            method_name: 方法名（如 "hybrid"、"ripgrep"）。
            top_k:       Top K 截断。

        Returns:
            list[EvalResult]，每个 case 一个结果。
        """
        results: list[EvalResult] = []

        for case in cases:
            started = time.monotonic()

            error_message: str | None = None

            # 运行检索。使用位置参数避免 retrieve(query, k=...)
            # 与 retrieve(query, top_k=...) 之间的关键字不一致。
            try:
                predicted = self._retrieve(case.query, top_k)
            except Exception as exc:
                predicted = []
                error_message = (
                    f"{type(exc).__name__}: {exc}"
                )

            latency_ms = int((time.monotonic() - started) * 1000)

            # 计算指标
            metrics = evaluate_query(
                predicted_files=predicted,
                gold_files=case.gold_files,
                k=top_k,
            )

            results.append(
                EvalResult(
                    case_id=case.id,
                    category=case.category,
                    method=method_name,
                    query=case.query,
                    gold_files=case.gold_files,
                    predicted_files=predicted[:top_k],
                    recall_at_5=metrics.recall_at_5,
                    hit_at_5=metrics.hit_at_5,
                    latency_ms=latency_ms,
                    candidate_count=len(predicted),
                    hit_files=list(metrics.hit_files),
                    missed_files=list(metrics.missed_files),
                    error=error_message,
                )
            )

        return results


def load_eval_cases(dataset_path: Path) -> list[EvalCase]:
    """从 JSONL 文件加载评测案例。

    JSONL 格式（每行一个 JSON 对象）：
    {"id":"s-001","category":"exact_symbol","query":"...","gold_files":["..."],...}

    Args:
        dataset_path: JSONL 文件路径。

    Returns:
        list[EvalCase]
    """
    cases: list[EvalCase] = []
    with open(dataset_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            data = json.loads(line)
            cases.append(
                EvalCase(
                    id=data["id"],
                    category=data.get("category", "unknown"),
                    query=data["query"],
                    gold_files=data.get("gold_files", []),
                    supporting_files=data.get("supporting_files", []),
                    gold_rationale=data.get("gold_rationale", {}),
                    repository_commit=data.get("repository_commit", ""),
                    notes=data.get("notes"),
                )
            )
    return cases


def save_results(
    results: list[EvalResult],
    output_path: Path,
) -> None:
    """将评测结果保存为 JSONL 文件。

    Args:
        results:     评测结果列表。
        output_path: 输出文件路径。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for result in results:
            f.write(
                json.dumps(
                    {
                        "case_id": result.case_id,
                        "category": result.category,
                        "method": result.method,
                        "query": result.query,
                        "gold_files": result.gold_files,
                        "predicted_files": result.predicted_files,
                        "recall_at_5": result.recall_at_5,
                        "hit_at_5": result.hit_at_5,
                        "latency_ms": result.latency_ms,
                        "candidate_count": result.candidate_count,
                        "hit_files": result.hit_files,
                        "missed_files": result.missed_files,
                        "error": result.error,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
