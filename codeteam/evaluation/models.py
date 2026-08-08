"""评测数据模型：评测案例、结果和指标。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalCase:
    """一条评测案例。

    包含自然语言查询和期望的 Gold Files。
    """
    id: str
    category: str
    query: str
    gold_files: list[str] = field(default_factory=list)
    supporting_files: list[str] = field(default_factory=list)
    gold_rationale: dict[str, str] = field(default_factory=dict)
    repository_commit: str = ""
    notes: str | None = None


@dataclass(frozen=True)
class QueryMetrics:
    """单条查询的评测指标。"""
    recall_at_5: float
    hit_at_5: float
    hit_files: tuple[str, ...]
    missed_files: tuple[str, ...]


@dataclass
class EvalResult:
    """一条评测的完整结果。"""
    case_id: str
    category: str
    method: str
    query: str
    gold_files: list[str]
    predicted_files: list[str]
    recall_at_5: float
    hit_at_5: float
    latency_ms: int
    candidate_count: int = 0
    hit_files: list[str] = field(default_factory=list)
    missed_files: list[str] = field(default_factory=list)
    error: str | None = None
