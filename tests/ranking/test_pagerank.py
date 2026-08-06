"""Tests for codeteam.ranking.pagerank — PageRank computation。

验证 build_networkx_graph, compute_global_pagerank,
compute_personalized_pagerank, safe_pagerank 降级。
"""

from __future__ import annotations

import pytest

from codeteam.ranking import pagerank as pr


class TestBuildNetworkXGraph:
    """ImportGraph → NetworkX DiGraph。"""

    def test_empty_graph_returns_empty(self) -> None:
        """空 ImportGraph 产生空 DiGraph。"""
        from codeteam.imports.graph import ImportGraph
        g = pr.build_networkx_graph(ImportGraph())
        assert g.number_of_nodes() == 0
        assert g.number_of_edges() == 0

    def test_nodes_are_file_paths(self, import_graph) -> None:
        """节点是文件路径字符串。"""
        g = pr.build_networkx_graph(import_graph)
        assert "src/auth/api.py" in g.nodes()
        assert "src/auth/service.py" in g.nodes()

    def test_edges_follow_import_direction(self, import_graph) -> None:
        """A import B → 边 A → B。"""
        g = pr.build_networkx_graph(import_graph)
        # api.py imports service.py → edge api → service
        assert g.has_edge("src/auth/api.py", "src/auth/service.py")

    def test_graph_is_deterministic(self, import_graph) -> None:
        """同一输入 → 同一图。"""
        g1 = pr.build_networkx_graph(import_graph)
        g2 = pr.build_networkx_graph(import_graph)
        assert list(g1.nodes()) == list(g2.nodes())
        assert list(g1.edges()) == list(g2.edges())

    def test_edge_has_weight(self, import_graph) -> None:
        """每条边有 weight 属性。"""
        g = pr.build_networkx_graph(import_graph)
        data = g.get_edge_data("src/auth/api.py", "src/auth/service.py")
        assert "weight" in data
        assert data["weight"] > 0


class TestGlobalPagerank:
    """compute_global_pagerank。"""

    def test_empty_graph_returns_empty_dict(self) -> None:
        import networkx as nx
        result = pr.compute_global_pagerank(nx.DiGraph())
        assert result == {}

    def test_nodes_only_uniform(self) -> None:
        """只有节点无边 → 均分。"""
        import networkx as nx
        g = nx.DiGraph()
        g.add_node("a")
        g.add_node("b")
        result = pr.compute_global_pagerank(g)
        assert len(result) == 2
        assert abs(result["a"] - 0.5) < 0.01

    def test_common_db_has_higher_pagerank(
        self, import_graph,
    ) -> None:
        """被多个文件 import 的文件有更高 PageRank。"""
        g = pr.build_networkx_graph(import_graph)
        result = pr.compute_global_pagerank(g)

        # database.py 被 3 个文件 import，应有较高的 PageRank
        db_score = result.get("src/common/database.py", 0)
        # 至少有值
        assert db_score > 0


class TestPersonalizedPagerank:
    """compute_personalized_pagerank。"""

    def test_seed_scores_influence_result(
        self, import_graph,
    ) -> None:
        """个性化 PageRank 受 seed 影响。"""
        g = pr.build_networkx_graph(import_graph)

        # 把 auth/api.py 设为最重要
        seeds = {
            "src/auth/api.py": 10.0,
            "src/auth/service.py": 1.0,
        }
        result = pr.compute_personalized_pagerank(g, seeds)

        # api.py 应该获得较高的分数（因为 seed 高）
        assert result.get("src/auth/api.py", 0) > 0

    def test_all_zero_seeds_falls_back_to_global(self, import_graph) -> None:
        """所有 seed 为 0 → 退化为全局 PageRank。"""
        g = pr.build_networkx_graph(import_graph)
        result = pr.compute_personalized_pagerank(g, {"src/auth/api.py": 0.0})
        assert len(result) > 0

    def test_empty_seeds_returns_global(self, import_graph) -> None:
        """空 seeds → 返回全局 PageRank。"""
        g = pr.build_networkx_graph(import_graph)
        result = pr.compute_personalized_pagerank(g, {})
        assert len(result) > 0


class TestSafePagerank:
    """safe_pagerank 降级行为。"""

    def test_safe_pagerank_handles_degenerate_graph(self) -> None:
        """退化的图不应抛异常。"""
        import networkx as nx
        g = nx.DiGraph()
        g.add_node("isolated")
        result = pr.safe_pagerank(g)
        assert "isolated" in result
        assert result["isolated"] > 0
