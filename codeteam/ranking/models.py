"""
codeteam.ranking.models - 排序系统的统一数据模型

定义 FileSignals / RankingEvidence / RankedFile / RankingWeights。
FileRanker 产出这些结构，RepoMapBuilder 消费这些结构。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from pydantic import BaseModel


def saturate(value: float) -> float:
    """饱和函数：把多次同类命中压缩到 [0, 1)。

    1 - e^(-value) 的作用：
    - 1 次命中 → 0.63
    - 3 次命中 → 0.95
    - 10 次命中 → ≈1.0

    防止 service、user 这类常见词在文件中命中 100 次
    导致 signal 值无限增长，淹没其他信号。
    """
    return 1.0 - math.exp(-max(value, 0.0))


# ── 信号集合 ──────────────────────────────────────────────

class FileSignals(BaseModel):
    """一个文件在所有排名维度上的信号值。

    每个信号已归一化到 [0, 1]。
    惩罚项为负值或 0（如 generated_penalty = -1.0 表示完全惩
    """

    query_match: float = 0.0          # 用户查询直接匹配路径/文件名
    symbol_match: float = 0.0         # SymbolIndex 命中（精
    ripgrep_match: float = 0.0        # ripgrep 文本搜索命中

    import_one_hop: float = 0.0       # 直接依赖或被依赖
    import_two_hop: float = 0.0       # 间接依赖

    global_pagerank: float = 0.0      # 整个仓库中的图重要性
    personalized_pagerank: float = 0.0  # 针对当前查询的图重要性 [0, 1]

    base_importance: float = 0.0      # 文件类型先验权重（SOURCE > TEST > GENERATED）
    test_relevance: float = 0.0       # 作为测试文件的相关性

    # 惩罚项（通常为负值）
    generated_penalty: float = 0.0    # 生成代码惩罚
    vendored_penalty: float = 0.0     # 第三方代码惩罚
    binary_penalty: float = 0.0       # 二进制文件直接封杀


# ── 排名证据 ──────────────────────────────────────────────

class RankingEvidence(BaseModel):
    """一条排名证据：为什么这个文件得到这个分数。

    每条证据记录：
    - signal: 信号名称（对应 FileSignals 的字段名）
    - value: 信号的归一化值（0～1）
    - weight: 该信号的权重
    - contribution: value × weight（该信号对最终得分的贡献）
    - reason: 人类可读的理由

    示例：
        RankingEvidence(
            signal="symbol_match",
            value=1.0,
            weight=4.0,
            contribution=4.0,
            reason="Defines refresh_access_token"
        )
    """
    signal: str
    value: float
    weight: float
    contribution: float
    reason: str = ""


# ── 排序后的文件 ──────────────────────────────────────────

class RankedFile(BaseModel):
    """排序后的一个文件。

    Attributes:
        path: 文件路径
        final_score: 最终得分（所有 signal × weight 之和）
        rank: 排名（1-based）
        signals: 各信号的值
        evidence: 每条信号的贡献详情
        matched_symbols: 匹配到的符号名称列表
        matched_lines: 匹配到的行号列表
        is_generated: 是否为生成代码
        is_test: 是否为测试文件
    """
    path: str
    final_score: float
    rank: int

    signals: FileSignals
    evidence: list[RankingEvidence] = []

    matched_symbols: list[str] = []
    matched_lines: list[int] = []

    is_generated: bool = False
    is_test: bool = False


# ── 权重配置 ──────────────────────────────────────────────

@dataclass(frozen=True)
class RankingWeights:
    """FileRanker 的权重配置。

    为什么用 frozen dataclass 而不是 BaseModel？
    - 权重是固定配置，创建后不需要修改
    - dataclass 比 BaseModel 轻量（不需要验证/序列化）
    - frozen=True 防止意外修改

    权重代表的优先级关系（不是绝对值，是相对比例）：
        用户直接给出路径 ≈ 精确 Symbol 定义  4.0
        > 错误信息匹配                       2.5
        > 一跳依赖                           1.8
        > 个性化 PageRank                    1.2
        > 文件基础权重 ≈ 测试相关性          1.0
        > 两跳依赖                           0.8
        > 全局 PageRank                      0.4
        > Generated 惩罚                   -4.0
        > Vendored 惩罚                    -5.0
        > Binary 封杀                     -10.0
    """

    query_match: float = 4.0
    symbol_match: float = 4.0
    ripgrep_match: float = 2.5

    import_one_hop: float = 1.8
    import_two_hop: float = 0.8

    base_importance: float = 1.0
    test_relevance: float = 1.0

    personalized_pagerank: float = 1.2
    global_pagerank: float = 0.4

    # 惩罚项权重
    generated_penalty: float = 4.0
    vendored_penalty: float = 5.0
    binary_penalty: float = 10.0