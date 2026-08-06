"""
PageRank：把 ImportGraph 转成 NetworkX 图，计算全局和个性化 PageRank。

核心能力：
- build_networkx_graph: ImportGraph → nx.DiGraph
- compute_global_pagerank: 全局图重要性
- compute_personalized_pagerank: 针对查询的图重要性
- safe_pagerank: 失败降级包装
"""
from __future__ import annotations

import networkx as nx
from networkx.exception import PowerIterationFailedConvergence

from codeteam.imports.graph import ImportGraph


def build_networkx_graph(
    import_graph: ImportGraph,
) -> nx.DiGraph:
    """把内部的 ImportGraph 转成 NetworkX DiGraph。

    方向保持不变：
        A import B → 边 A → B

    权重处理：
        如果 A 多次 import B（多条边），权重累加。
        最小权重 0.1，确保每条边都有非零权重。

    图构建是确定性的：
        节点和边都按 path 排序后依次加入，
        保证同一输入总是产生同一张图。
    """
    graph = nx.DiGraph()

    # 收集所有节点（从两个方向各取 key，确保覆盖所有）
    all_nodes = set(import_graph._outgoing.keys()) | set(
        import_graph._incoming.keys()
    )

    # 排序加入 → 确定性
    for node in sorted(all_nodes):
        graph.add_node(node)

    # 收集所有边（从 _outgoing）
    for source in sorted(import_graph._outgoing.keys()):
        for target in sorted(import_graph._outgoing[source]):
            # 累加权重（如果之前已有同向边）
            current = graph.get_edge_data(
                source, target, default={}
            )
            prev_weight = float(current.get("weight", 0.0))
            graph.add_edge(
                source,
                target,
                weight=prev_weight + 0.1,
            )

    return graph


def compute_global_pagerank(
    graph: nx.DiGraph,
) -> dict[str, float]:
    """计算全局 PageRank。

    - 空图 → 空 dict
    - 有节点但无边 → 所有节点均分 1/N
    - 正常图 → nx.pagerank(alpha=0.85)
    """
    if graph.number_of_nodes() == 0:
        return {}

    if graph.number_of_edges() == 0:
        uniform = 1.0 / graph.number_of_nodes()
        return {node: uniform for node in graph.nodes()}

    return safe_pagerank(graph, personalization=None)


def compute_personalized_pagerank(
    graph: nx.DiGraph,
    seed_scores: dict[str, float],
) -> dict[str, float]:
    """计算个性化 PageRank。

    Args:
        graph: 文件依赖图
        seed_scores: path → 初始重要性（通常来自 FileRanker 的初步排名）

    seed_scores 会先被归一化（总和 = 1），然后传给 nx.pagerank
    的 personalization 和 dangling 参数。

    如果所有 seed 的分数都是 0，退化为 global PageRank。
    """
    # 过滤：只保留图中存在的节点 + 非负分数
    valid = {
        path: max(score, 0.0)
        for path, score in seed_scores.items()
        if path in graph
    }

    total = sum(valid.values())
    if total <= 0:
        return compute_global_pagerank(graph)

    # 归一化
    personalization = {
        path: score / total for path, score in valid.items()
    }

    return safe_pagerank(
        graph,
        personalization=personalization,
    )


def safe_pagerank(
    graph: nx.DiGraph,
    personalization: dict[str, float] | None = None,
) -> dict[str, float]:
    """执行 PageRank，失败时降级为入度排序。

    PageRank 可能因为图结构问题（如迭代不收敛）而失败。
    作为排序增强项，不能让它导致整个 Repo Map 崩溃。

    降级策略：
        1. 尝试 nx.pagerank()
        2. 失败 → _in_degree_fallback()（按被引用数排序）
        3. in_degree 也失败 → 均分
    """
    try:
        return nx.pagerank(
            graph,
            alpha=0.85,
            personalization=personalization,
            dangling=personalization,
            weight="weight",
            max_iter=100,
            tol=1e-6,
        )
    except (PowerIterationFailedConvergence, ZeroDivisionError):
        return _in_degree_fallback(graph)


def _in_degree_fallback(graph: nx.DiGraph) -> dict[str, float]:
    """入度降级：被越多文件依赖，分数越高。

    如果所有入度都是 0 → 均分。
    """
    scores = {
        node: float(graph.in_degree(node))
        for node in graph.nodes()
    }

    total = sum(scores.values())
    if total <= 0:
        uniform = 1.0 / graph.number_of_nodes()
        return {node: uniform for node in graph.nodes()}

    return {
        node: score / total for node, score in scores.items()
    }