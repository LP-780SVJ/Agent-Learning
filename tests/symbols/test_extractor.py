"""测试 SymbolExtractor: 从 Python AST 提取符号定义和引用。

覆盖场景：
- T06: 嵌套类 qualified names 和 SymbolKind
- T07: 同名方法区分（不同 qualified_name / symbol_id）
- 基础: 函数、类、方法、变量的提取
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from codeteam.symbols.extractor import SymbolExtractor
from codeteam.symbols.models import (
    Symbol,
    SymbolKind,
    ReferenceKind,
    Reference,
)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _extract(source: str, file_path: str = "test.py") -> tuple[list[Symbol], list[Reference]]:
    """解析源码并提取符号。

    若生产代码缺失 _extract_parameters 方法，抛出明确的 AttributeError
    并在消息中标注为生产缺陷。
    """
    source = textwrap.dedent(source).strip()
    tree = ast.parse(source)
    extractor = SymbolExtractor(file_path)
    try:
        return extractor.extract(tree)
    except AttributeError as exc:
        if "_extract_parameters" in str(exc):
            raise AttributeError(
                f"PRODUCTION DEFECT: SymbolExtractor._extract_parameters() "
                f"is called at extractor.py:140 but not defined. "
                f"The extractor cannot parse any source containing function "
                f"or class definitions. "
                f"Original error: {exc}"
            ) from exc
        raise


def _dedent(source: str) -> str:
    return textwrap.dedent(source).strip()


# ===================================================================
# T06: 嵌套类
# ===================================================================

NESTED_SOURCE = """
class Outer:
    class Inner:
        def run(self, value: int) -> bool:
            return value > 0
"""


class TestNestedClass:
    """T06: 嵌套类——qualified names 和 SymbolKind 正确性。

    需求断言：
    - app.nested::Outer          → CLASS
    - app.nested::Outer.Inner    → CLASS
    - app.nested::Outer.Inner.run → METHOD

    注意：实际实现使用 "." 分隔 qualified_name（非 "::"），
    module_name 不包含在 qualified_name 中（由 extractor 的 file_path 表达）。
    qualified_name 格式：Outer, Outer.Inner, Outer.Inner.run
    """

    def test_nested_class_qualified_names(self) -> None:
        """嵌套类的 qualified_name 应正确反映层级。"""
        tree = ast.parse(_dedent(NESTED_SOURCE))
        extractor = SymbolExtractor("app/nested.py")
        symbols, _ = extractor.extract(tree)

        # 按 qualified_name 建立索引
        by_qn = {s.qualified_name: s for s in symbols}

        # Outer 类
        assert "Outer" in by_qn, f"Expected 'Outer' in symbols, got {list(by_qn.keys())}"
        outer = by_qn["Outer"]
        assert outer.kind == SymbolKind.CLASS, (
            f"Outer should be CLASS, got {outer.kind}"
        )
        assert outer.name == "Outer"

        # Inner 类
        assert "Outer.Inner" in by_qn, (
            f"Expected 'Outer.Inner' in symbols, got {list(by_qn.keys())}"
        )
        inner = by_qn["Outer.Inner"]
        assert inner.kind == SymbolKind.CLASS, (
            f"Inner should be CLASS, got {inner.kind}"
        )
        assert inner.name == "Inner"

        # run 方法
        assert "Outer.Inner.run" in by_qn, (
            f"Expected 'Outer.Inner.run' in symbols, got {list(by_qn.keys())}"
        )
        run_method = by_qn["Outer.Inner.run"]
        assert run_method.kind == SymbolKind.METHOD, (
            f"run should be METHOD, got {run_method.kind}"
        )
        assert run_method.name == "run"

    def test_nested_class_symbol_ids_are_unique(self) -> None:
        """每个嵌套符号的 symbol_id 应全局唯一。"""
        tree = ast.parse(_dedent(NESTED_SOURCE))
        extractor = SymbolExtractor("app/nested.py")
        symbols, _ = extractor.extract(tree)

        ids = [s.symbol_id for s in symbols]
        assert len(ids) == len(set(ids)), f"Duplicate symbol_ids: {ids}"

    def test_inner_class_is_method_in_scope(self) -> None:
        """Inner 的方法 run 应被识别为 METHOD（因为 Inner 在类内部）。"""
        tree = ast.parse(_dedent(NESTED_SOURCE))
        extractor = SymbolExtractor("app/nested.py")
        symbols, _ = extractor.extract(tree)

        run_sym = [s for s in symbols if s.name == "run"]
        assert len(run_sym) == 1, f"Expected 1 'run' symbol, got {len(run_sym)}"
        assert run_sym[0].kind == SymbolKind.METHOD


# ===================================================================
# T07: 同名方法
# ===================================================================

SAME_NAME_SOURCE = """
class UserService:
    def get(self):
        pass

class OrderService:
    def get(self):
        pass
"""


class TestSameNameMethods:
    """T07: 同名方法——不同类中的同名方法应有不同的 qualified_name 和 symbol_id。"""

    def test_find_exact_returns_multiple_symbols(self) -> None:
        """按简单名字查找 'get' 应返回两个 Symbol。"""
        symbols, _ = _extract(SAME_NAME_SOURCE, "app/services.py")

        gets = [s for s in symbols if s.name == "get"]
        assert len(gets) == 2, (
            f"Expected 2 'get' symbols, got {len(gets)}: "
            f"{[(s.name, s.qualified_name) for s in gets]}"
        )

    def test_different_qualified_names(self) -> None:
        """同名方法应有不同的 qualified_name。"""
        symbols, _ = _extract(SAME_NAME_SOURCE, "app/services.py")

        gets = [s for s in symbols if s.name == "get"]
        qns = {s.qualified_name for s in gets}

        assert "UserService.get" in qns, (
            f"Expected 'UserService.get', got {qns}"
        )
        assert "OrderService.get" in qns, (
            f"Expected 'OrderService.get', got {qns}"
        )

    def test_different_symbol_ids(self) -> None:
        """同名方法应有不同的 symbol_id。"""
        symbols, _ = _extract(SAME_NAME_SOURCE, "app/services.py")

        gets = [s for s in symbols if s.name == "get"]
        ids = [s.symbol_id for s in gets]
        assert len(ids) == len(set(ids)), (
            f"symbol_ids should be unique, got {ids}"
        )

    def test_both_are_methods(self) -> None:
        """类中的函数应被识别为 METHOD（不是 FUNCTION）。"""
        symbols, _ = _extract(SAME_NAME_SOURCE, "app/services.py")

        gets = [s for s in symbols if s.name == "get"]
        for s in gets:
            assert s.kind == SymbolKind.METHOD, (
                f"{s.qualified_name}: expected METHOD, got {s.kind}"
            )


# ===================================================================
# 基础提取：函数、类、变量
# ===================================================================

class TestBasicExtraction:
    """基础提取：顶层函数（FUNCTION）、类内方法（METHOD）、变量（VARIABLE）。"""

    def test_top_level_function_is_function(self) -> None:
        """模块级函数应为 FUNCTION。"""
        source = "def hello():\n    pass\n"
        symbols, _ = _extract(source, "mod.py")

        funcs = [s for s in symbols if s.kind == SymbolKind.FUNCTION]
        assert len(funcs) == 1
        assert funcs[0].name == "hello"

    def test_method_is_method(self) -> None:
        """类内函数应为 METHOD。"""
        source = "class A:\n    def m(self):\n        pass\n"
        symbols, _ = _extract(source, "mod.py")

        methods = [s for s in symbols if s.kind == SymbolKind.METHOD]
        assert len(methods) == 1
        assert methods[0].name == "m"
        assert methods[0].qualified_name == "A.m"

    def test_variable_assignment_is_variable(self) -> None:
        """变量赋值（Store ctx）应产生 VARIABLE 符号。"""
        source = "x = 5\n"
        symbols, _ = _extract(source, "mod.py")

        vars_ = [s for s in symbols if s.kind == SymbolKind.VARIABLE]
        assert len(vars_) >= 1
        assert any(v.name == "x" for v in vars_)

    def test_signature_extraction(self) -> None:
        """函数签名应包含参数和返回类型。"""
        source = "def get_user(self, user_id: int) -> str:\n    pass\n"
        symbols, _ = _extract(source, "mod.py")

        func = next(s for s in symbols if s.name == "get_user")
        assert "user_id" in func.signature
        assert "int" in func.signature
        assert "str" in func.signature

    def test_decorator_extraction(self) -> None:
        """装饰器名字应被提取。"""
        source = "@staticmethod\ndef helper():\n    pass\n"
        symbols, _ = _extract(source, "mod.py")

        func = next(s for s in symbols if s.name == "helper")
        assert "staticmethod" in func.decorators


# ===================================================================
# Reference 提取
# ===================================================================

class TestReferenceExtraction:
    """名称引用的提取：SIMPLE、ATTRIBUTE、CALL 等。"""

    def test_simple_reference(self) -> None:
        """简单名称引用（Load ctx）应产生 SIMPLE 引用。"""
        source = "x = 5\nprint(x)\n"
        _, refs = _extract(source, "mod.py")

        x_refs = [r for r in refs if r.name == "x"]
        assert any(r.kind == ReferenceKind.SIMPLE for r in x_refs), (
            f"Expected SIMPLE reference to 'x', got {x_refs}"
        )

    def test_attribute_reference(self) -> None:
        """属性访问应产生 ATTRIBUTE 引用。"""
        source = "obj.attr\n"
        _, refs = _extract(source, "mod.py")

        attr_refs = [r for r in refs if r.name == "attr"]
        assert any(r.kind == ReferenceKind.ATTRIBUTE for r in attr_refs), (
            f"Expected ATTRIBUTE reference to 'attr', got {attr_refs}"
        )

    def test_attribute_chain_produces_multiple_refs(self) -> None:
        """链式属性访问 self.repo.find 应产生多个引用。"""
        source = "class A:\n    def m(self):\n        self.repo.find()\n"
        _, refs = _extract(source, "mod.py")

        names_in_refs = {r.name for r in refs}
        # self, repo, find 都应出现
        for expected in ("self", "repo", "find"):
            assert expected in names_in_refs, (
                f"Expected '{expected}' in references, got {names_in_refs}"
            )
