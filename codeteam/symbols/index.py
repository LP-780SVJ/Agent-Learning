"""
SymbolIndex: 可查询的符号索引。

支持 5 种查询模式：
- find_exact:     按简单名字查找（可能返回多个）
- find_qualified: 按限定名精确查找（返回零个或一个）
- find_prefix:    按限定名前缀查找
- symbols_in_file: 按文件路径查找该文件所有符号
- references_to:   查找引用某个名字的所有位置

内部使用多索引模式：add() 时同时更新多张 dict，
实现 O(1) 的精确查询和 O(n) 的前缀查询。
"""
from __future__ import annotations

from codeteam.symbols.models import Symbol, Reference


class SymbolIndex:
    """可查询的代码符号索引。"""

    def __init__(self) -> None:
        # name → list[Symbol]: 简单名字可能对应多个符号（同名不同作用域）
        self._by_name: dict[str, list[Symbol]] = {}

        # qualified_name → Symbol: 每个限定名在索引中只保留最后一次 add 的结果
        self._by_qualified: dict[str, Symbol] = {}

        # file_path → list[Symbol]: 一个文件包含的所有符号定义
        self._by_file: dict[str, list[Symbol]] = {}

        # name → list[Reference]: 所有引用这个名字的位置
        self._references_to: dict[str, list[Reference]] = {}

    # ── 写入 ──────────────────────────────────────────────────

    def add(self, symbol: Symbol) -> None:
        """向索引中添加一个符号定义。

        同时更新三张索引表：_by_name、_by_qualified、_by_file。
        如果同一个 qualified_name 已存在，后添加的会覆盖先前的。
        """
        # 按简单名字索引
        if symbol.name not in self._by_name:
            self._by_name[symbol.name] = []
        self._by_name[symbol.name].append(symbol)

        # 按限定名索引（使用 name 作为 fallback）
        qn = symbol.qualified_name or symbol.name
        self._by_qualified[qn] = symbol

        # 按文件索引
        f = symbol.location.file
        if f not in self._by_file:
            self._by_file[f] = []
        self._by_file[f].append(symbol)

    def add_reference(self, ref: Reference) -> None:
        """向索引中添加一条引用记录。

        只有 _references_to 一张表需要更新。
        """
        if ref.name not in self._references_to:
            self._references_to[ref.name] = []
        self._references_to[ref.name].append(ref)

    def add_references(self, refs: list[Reference]) -> None:
        """批量添加引用记录。"""
        for ref in refs:
            self.add_reference(ref)

    # ── 查询 ──────────────────────────────────────────────────

    def find_exact(self, name: str) -> list[Symbol]:
        """按简单名字精确查找。

        返回所有叫这个名字的 Symbol，可能为空列表。
        例：find_exact("get") 可能返回 [UserService.get, OrderService.get]
        """
        return self._by_name.get(name, [])

    def find_qualified(self, qualified_name: str) -> Symbol | None:
        """按限定名精确查找。

        返回唯一的 Symbol 或 None。
        例：find_qualified("UserService.get_user")
        """
        return self._by_qualified.get(qualified_name)

    def find_prefix(self, prefix: str) -> list[Symbol]:
        """按限定名前缀查找。

        返回所有 qualified_name 以 prefix 开头的 Symbol。
        例：find_prefix("UserService") 返回 UserService 自身及其所有成员。
        """
        results: list[Symbol] = []
        for qn, sym in self._by_qualified.items():
            if qn.startswith(prefix):
                results.append(sym)
        return results

    def symbols_in_file(self, file_path: str) -> list[Symbol]:
        """返回某个文件中定义的所有符号。

        例：symbols_in_file("auth/service.py")
        """
        return self._by_file.get(file_path, [])

    def references_to(self, name: str) -> list[Reference]:
        """返回所有引用某个名字的位置。

        例：references_to("UserRepository") 返回所有写 UserRepository 的位置。
        """
        return self._references_to.get(name, [])

    # ── 统计 ──────────────────────────────────────────────────

    @property
    def total_symbols(self) -> int:
        """索引中的符号总数。"""
        return len(self._by_qualified)

    @property
    def total_references(self) -> int:
        """索引中的引用总数。"""
        return sum(len(refs) for refs in self._references_to.values())

    @property
    def total_files(self) -> int:
        """索引覆盖的文件数。"""
        return len(self._by_file)


    def _by_kind(self, kind: str) -> list[Symbol]:
        """按符号种类筛选（内部方法，供统计使用）。

        Args:
            kind: 种类值，如 "class"、"function"、"method"

        Returns:
            该种类的所有 Symbol 列表
        """
        return [
            sym for sym in self._by_qualified.values()
            if sym.kind.value == kind
        ]