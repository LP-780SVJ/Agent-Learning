"""评测指标：Recall@5、Hit@5 计算。"""
from __future__ import annotations

from codeteam.evaluation.models import QueryMetrics


def evaluate_query(
    *,
    predicted_files: list[str],
    gold_files: list[str],
    k: int = 5,
) -> QueryMetrics:
    """计算单条查询的 Recall@K 和 Hit@K。

    Recall@K = |Gold ∩ TopK| / |Gold|
    Hit@K    = 1 if 至少命中一个 Gold else 0

    Args:
        predicted_files: 系统预测的文件路径列表（已排序）。
        gold_files:      人工标注的 Gold Files。
        k:               Top K 截断数。

    Returns:
        QueryMetrics，包含命中文件和遗漏文件。

    Raises:
        ValueError: gold_files 为空。
    """
    if not gold_files:
        raise ValueError("gold_files 不能为空")

    # 去重保留顺序，截取 Top K
    seen: set[str] = set()
    predictions: list[str] = []
    for path in predicted_files:
        if path not in seen:
            seen.add(path)
            predictions.append(path)
    predictions = predictions[:k]

    gold_set = set(gold_files)

    hits = [path for path in predictions if path in gold_set]
    missed = sorted(gold_set - set(hits))

    return QueryMetrics(
        recall_at_5=len(hits) / len(gold_set),
        hit_at_5=1.0 if hits else 0.0,
        hit_files=tuple(hits),
        missed_files=tuple(missed),
    )