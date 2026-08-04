"""测试 SymbolIndex: 符号索引的增删查操作。

覆盖场景：
- T07: find_exact("get") 返回多个同名符号
- 基础 CRUD: add / find_exact / find_qualified / find_prefix / symbols_in_file / references_to
"""

from __future__ import annotations

import pytest

from codeteam.symbols.models import (
    Symbol,
    SymbolKind,
    SymbolLocation,
    Reference,
    ReferenceKind,
)
from codeteam.symbols.index import SymbolIndex


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _make_symbol(name: str, kind: SymbolKind, qualified_name: str,
                 file_path: str = "test.py", line: int = 0) -> Symbol:
    return Symbol(
        name=name,
        kind=kind,
        location=SymbolLocation(file=file_path, line=line, column=0),
        qualified_name=qualified_name,
    )


def _make_ref(name: str, kind: ReferenceKind = ReferenceKind.SIMPLE,
              file_path: str = "test.py", line: int = 0, scope: str = "") -> Reference:
    return Reference(
        name=name,
        kind=kind,
        location=SymbolLocation(file=file_path, line=line, column=0),
        scope=scope,
    )


# ===================================================================
# T07: find_exact 同名方法
# ===================================================================

class TestFindExactSameName:
    """T07: find_exact("get") 返回多个同名符号。"""

    def test_find_exact_returns_multiple(self) -> None:
        """两个不同类中的同名方法应都被返回。"""
        idx = SymbolIndex()
        idx.add(_make_symbol("get", SymbolKind.METHOD, "UserService.get", "svc.py", 3))
        idx.add(_make_symbol("get", SymbolKind.METHOD, "OrderService.get", "svc.py", 10))

        results = idx.find_exact("get")
        assert len(results) == 2, f"Expected 2, got {len(results)}"
        qualified_names = {r.qualified_name for r in results}
        assert qualified_names == {"UserService.get", "OrderService.get"}

    def test_find_exact_returns_empty_for_unknown_name(self) -> None:
        """未知名字应返回空列表。"""
        idx = SymbolIndex()
        assert idx.find_exact("nonexistent") == []


# ===================================================================
# 基础 CRUD
# ===================================================================

class TestSymbolIndexCRUD:
    """SymbolIndex 的基础增删查操作。"""

    @pytest.fixture
    def index(self) -> SymbolIndex:
        idx = SymbolIndex()
        idx.add(_make_symbol("UserService", SymbolKind.CLASS,
                             "UserService", "app/service.py", 5))
        idx.add(_make_symbol("get_user", SymbolKind.METHOD,
                             "UserService.get_user", "app/service.py", 7))
        idx.add(_make_symbol("User", SymbolKind.CLASS,
                             "User", "app/models.py", 2))
        return idx

    def test_find_qualified_exact(self, index: SymbolIndex) -> None:
        """按限定名精确查找。"""
        sym = index.find_qualified("UserService.get_user")
        assert sym is not None
        assert sym.name == "get_user"
        assert sym.kind == SymbolKind.METHOD

    def test_find_qualified_returns_none_for_unknown(self, index: SymbolIndex) -> None:
        """未知限定名返回 None。"""
        assert index.find_qualified("DoesNotExist.method") is None

    def test_find_prefix(self, index: SymbolIndex) -> None:
        """前缀查找应返回所有匹配的符号。"""
        results = index.find_prefix("UserService")
        names = {r.qualified_name for r in results}
        assert "UserService" in names
        assert "UserService.get_user" in names

    def test_symbols_in_file(self, index: SymbolIndex) -> None:
        """按文件查找符号。"""
        results = index.symbols_in_file("app/service.py")
        assert len(results) == 2
        names = {r.name for r in results}
        assert names == {"UserService", "get_user"}

    def test_symbols_in_file_empty_for_unknown(self, index: SymbolIndex) -> None:
        """未知文件返回空列表。"""
        assert index.symbols_in_file("nonexistent.py") == []

    def test_total_symbols(self, index: SymbolIndex) -> None:
        """total_symbols 应返回正确数量。"""
        assert index.total_symbols == 3

    def test_total_files(self, index: SymbolIndex) -> None:
        """total_files 应返回正确文件数。"""
        assert index.total_files == 2


# ===================================================================
# Reference 索引
# ===================================================================

class TestReferenceIndex:
    """references_to 查询。"""

    def test_references_to_returns_all_refs(self) -> None:
        """查找对某名字的所有引用。"""
        idx = SymbolIndex()
        idx.add_reference(_make_ref("UserRepository", ReferenceKind.SIMPLE,
                                    "app/api.py", 5, "create_user"))
        idx.add_reference(_make_ref("UserRepository", ReferenceKind.ATTRIBUTE,
                                    "app/service.py", 10, "get_user"))

        refs = idx.references_to("UserRepository")
        assert len(refs) == 2
        files = {r.location.file for r in refs}
        assert files == {"app/api.py", "app/service.py"}

    def test_references_to_empty_for_unknown(self) -> None:
        """未知名字的引用返回空列表。"""
        idx = SymbolIndex()
        assert idx.references_to("no_such_name") == []

    def test_total_references(self) -> None:
        """total_references 计数正确。"""
        idx = SymbolIndex()
        idx.add_reference(_make_ref("a"))
        idx.add_reference(_make_ref("b"))
        idx.add_reference(_make_ref("a"))  # 同一名字两个引用
        assert idx.total_references == 3


# ===================================================================
# 去重行为
# ===================================================================

class TestDeduplication:
    """重复添加同名 qualified_name 应是覆盖行为。"""

    def test_duplicate_qualified_name_overwrites(self) -> None:
        """同一 qualified_name 重复添加应覆盖前一个。"""
        idx = SymbolIndex()
        idx.add(_make_symbol("f", SymbolKind.FUNCTION, "mod.f", "a.py", 1))
        idx.add(_make_symbol("f", SymbolKind.FUNCTION, "mod.f", "a.py", 42))

        sym = idx.find_qualified("mod.f")
        assert sym is not None
        assert sym.location.line == 42  # 被覆盖为第二个

    def test_find_exact_can_have_duplicates_from_different_qn(self) -> None:
        """不同 qualified_name 的同名符号在 find_exact 中都出现。"""
        idx = SymbolIndex()
        idx.add(_make_symbol("helper", SymbolKind.FUNCTION, "A.helper", "a.py", 1))
        idx.add(_make_symbol("helper", SymbolKind.FUNCTION, "B.helper", "b.py", 1))

        results = idx.find_exact("helper")
        assert len(results) == 2
