"""
ImportGraph：文件依赖关系图（谁依赖谁）

内部用双向邻接表存储：
- _outgoing: source → {targets}  （我依赖谁）
- _incoming: target → {sources}  （谁依赖我）

这样 dependencies_of 和 dependents_of 都能 O(1) 起步查询。
"""
from __future__ import annotations


class ImportGraph:
    """有向依赖图，节点是文件路径，边表示 import 依赖。

    用法：
        graph = ImportGraph()
        graph.add_edge("auth/service.py", "auth/repository.py")
        graph.add_edge("auth/service.py", "auth/models.py")

        graph.dependencies_of("auth/service.py")
        # → {"auth/repository.py", "auth/models.py"}

        graph.dependents_of("auth/repository.py")
        # → {"auth/service.py"}
    """

    def __init__(self) -> None:
        self._outgoing: dict[str, set[str]] = {}
        self._incoming: dict[str, set[str]] = {}

    # ── 写操作 ─────────────────────────────────────────────────

    def add_edge(self, source_file: str, target_file: str) -> None:
        """添加一条有向边：source_file 依赖 target_file。

        重复添加同一条边不会有副作用（set 天然去重）。
        """
        # 确保两个节点在两个方向的索引中都"注册"了
        if source_file not in self._outgoing:
            self._outgoing[source_file] = set()
        if target_file not in self._incoming:
            self._incoming[target_file] = set()

        self._outgoing[source_file].add(target_file)
        self._incoming[target_file].add(source_file)

    # ── 查询：直接邻居 ─────────────────────────────────────────

    def neighbors(self, file: str) -> set[str]:
        """返回 file 的所有直接邻居（依赖的 + 被依赖的）。

        查询不存在的节点返回空 set，不抛异常。
        """
        outgoing = self._outgoing.get(file, set())
        incoming = self._incoming.get(file, set())
        return outgoing | incoming

    # ── 查询：多层遍历 ─────────────────────────────────────────

    def dependencies_of(self, file: str, depth: int | None = 1) -> set[str]:
        """返回 file 依赖的所有文件（沿 _outgoing 方向遍历）。

        Args:
            file:  起点文件路径。
            depth: 遍历深度。1 = 直接依赖，None = 传递闭包（所有可达节点）。

        Returns:
            file 依赖的文件集合（不包含 file 自身）。
        """
        return self._traverse(file, self._outgoing, depth)

    def dependents_of(self, file: str, depth: int | None = 1) -> set[str]:
        """返回依赖 file 的所有文件（沿 _incoming 方向遍历）。

        Args:
            file:  起点文件路径。
            depth: 遍历深度。1 = 直接依赖者，None = 传递闭包。

        Returns:
            依赖 file 的文件集合（不包含 file 自身）。
        """
        return self._traverse(file, self._incoming, depth)

    # ── 内部：BFS 遍历 ─────────────────────────────────────────

    def _traverse(
        self,
        start: str,
        adjacency: dict[str, set[str]],
        depth: int | None,
    ) -> set[str]:
        """从 start 出发，沿 adjacency 方向走 depth 层。

        Args:
            start:     起点节点。
            adjacency: 邻接表（_outgoing 或 _incoming）。
            depth:     层数限制。None 表示无限制。

        Returns:
            访问到的所有节点集合（不包含 start 自身）。
        """
        # 起点不在图中 → 快速返回
        if start not in adjacency:
            return set()

        visited: set[str] = set()
        current_layer: set[str] = {start}

        # depth=None → remaining 保持为 -1，永远不会减到 0
        remaining = depth if depth is not None else -1

        while remaining != 0:
            next_layer: set[str] = set()
            for node in current_layer:
                for neighbor in adjacency.get(node, set()):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_layer.add(neighbor)
            current_layer = next_layer
            if remaining > 0:
                remaining -= 1
            if not current_layer:
                break

        return visited