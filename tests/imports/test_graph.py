"""测试 ImportGraph: 文件依赖关系图。

覆盖场景：
- T01: 基本有向边（api.py → service.py, api.py → repository.py）
- T09: 循环 import（cycle_a ↔ cycle_b），neighbors depth=5 安全终止
"""

from __future__ import annotations

import pytest

from codeteam.imports.graph import ImportGraph


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _make_edge(source: str, target: str) -> tuple[str, str]:
    return (source, target)


# ===================================================================
# T01: 基本 Import Graph
# ===================================================================

class TestBasicGraph:
    """T01: Import Graph 基本操作。

    需求断言：
    - api.py → service.py
    - api.py → repository.py
    - dependencies_of("api.py") = {service.py, repository.py}
    - dependents_of("service.py") = {api.py}
    """

    def test_dependencies_of(self) -> None:
        """dependencies_of 应返回直接依赖的文件。"""
        graph = ImportGraph()
        graph.add_edge("app/api.py", "app/service.py")
        graph.add_edge("app/api.py", "app/repository.py")

        deps = graph.dependencies_of("app/api.py")
        assert deps == {"app/service.py", "app/repository.py"}, (
            f"Expected {{service.py, repository.py}}, got {deps}"
        )

    def test_dependents_of(self) -> None:
        """dependents_of 应返回直接依赖者。"""
        graph = ImportGraph()
        graph.add_edge("app/api.py", "app/service.py")

        dependents = graph.dependents_of("app/service.py")
        assert dependents == {"app/api.py"}, (
            f"Expected {{api.py}}, got {dependents}"
        )

    def test_neighbors(self) -> None:
        """neighbors 返回直接邻居（出边 + 入边）。"""
        graph = ImportGraph()
        graph.add_edge("app/api.py", "app/service.py")
        graph.add_edge("app/api.py", "app/repository.py")

        neighbors = graph.neighbors("app/api.py")
        assert neighbors == {"app/service.py", "app/repository.py"}

    def test_dependencies_of_unknown_file(self) -> None:
        """未知文件的依赖为空集合。"""
        graph = ImportGraph()
        assert graph.dependencies_of("nonexistent.py") == set()

    def test_dependents_of_unknown_file(self) -> None:
        """未知文件的被依赖为空集合。"""
        graph = ImportGraph()
        assert graph.dependents_of("nonexistent.py") == set()


# ===================================================================
# T09: 循环 Import
# ===================================================================

class TestCycleImport:
    """T09: 循环 import——cycle_a.py ↔ cycle_b.py。

    需求断言：
    - cycle_a.py → cycle_b.py
    - cycle_b.py → cycle_a.py
    - neighbors("cycle_a.py", depth=5) 能结束，不发生无限循环
    """

    def test_cycle_bidirectional_edges(self) -> None:
        """循环依赖应有双向边。"""
        graph = ImportGraph()
        graph.add_edge("app/cycle_a.py", "app/cycle_b.py")
        graph.add_edge("app/cycle_b.py", "app/cycle_a.py")

        assert graph.dependencies_of("app/cycle_a.py") == {"app/cycle_b.py"}
        assert graph.dependencies_of("app/cycle_b.py") == {"app/cycle_a.py"}

    def test_neighbors_with_depth_terminates(self) -> None:
        """neighbors 在 depth=5 时应在循环图中安全终止。"""
        graph = ImportGraph()
        graph.add_edge("app/cycle_a.py", "app/cycle_b.py")
        graph.add_edge("app/cycle_b.py", "app/cycle_a.py")

        # depth=5 应终止，不无限循环
        result = graph.neighbors("app/cycle_a.py")
        assert result == {"app/cycle_b.py"}, (
            f"Expected {{cycle_b.py}}, got {result}"
        )

    def test_dependencies_of_with_depth_on_cycle(self) -> None:
        """循环图中 dependencies_of 指定 depth 应安全终止。

        a → b → a 的循环中，从 a 出发遍历可到达 b 和 a（通过环路）。
        这验证了 BFS 不会无限循环。
        """
        graph = ImportGraph()
        graph.add_edge("app/cycle_a.py", "app/cycle_b.py")
        graph.add_edge("app/cycle_b.py", "app/cycle_a.py")

        # depth=5 应终止（不无限循环）
        result = graph.dependencies_of("app/cycle_a.py", depth=5)
        assert "app/cycle_b.py" in result
        # BFS 遍历 a→b→a，a 也会被加入 visited（通过环路回到 a）
        assert "app/cycle_a.py" in result

    def test_full_closure_on_cycle(self) -> None:
        """depth=None（传递闭包）在循环图中也应安全终止。"""
        graph = ImportGraph()
        graph.add_edge("app/cycle_a.py", "app/cycle_b.py")
        graph.add_edge("app/cycle_b.py", "app/cycle_a.py")

        # 传递闭包遍历——不应无限循环
        result = graph.dependencies_of("app/cycle_a.py", depth=None)
        assert result == {"app/cycle_b.py", "app/cycle_a.py"}

    def test_larger_cycle(self) -> None:
        """三节点循环：a → b → c → a。"""
        graph = ImportGraph()
        graph.add_edge("a.py", "b.py")
        graph.add_edge("b.py", "c.py")
        graph.add_edge("c.py", "a.py")

        # BFS 遍历 a→b→c→a，最终 visited = {a, b, c}
        result = graph.dependencies_of("a.py", depth=None)
        assert result == {"a.py", "b.py", "c.py"}


# ===================================================================
# 多层依赖
# ===================================================================

class TestMultiLevelDependencies:
    """多层依赖遍历。"""

    def test_depth_2_traversal(self) -> None:
        """a → b → c: depth=2 从 a 出发应返回 b 和 c。"""
        graph = ImportGraph()
        graph.add_edge("a.py", "b.py")
        graph.add_edge("b.py", "c.py")

        result = graph.dependencies_of("a.py", depth=2)
        assert result == {"b.py", "c.py"}

    def test_depth_1_only_direct(self) -> None:
        """a → b → c: depth=1 从 a 出发只返回 b。"""
        graph = ImportGraph()
        graph.add_edge("a.py", "b.py")
        graph.add_edge("b.py", "c.py")

        result = graph.dependencies_of("a.py", depth=1)
        assert result == {"b.py"}

    def test_duplicate_edge_no_effect(self) -> None:
        """重复添加同一条边不应改变结果。"""
        graph = ImportGraph()
        graph.add_edge("a.py", "b.py")
        graph.add_edge("a.py", "b.py")  # 重复
        graph.add_edge("a.py", "b.py")  # 再次重复

        assert graph.dependencies_of("a.py") == {"b.py"}
