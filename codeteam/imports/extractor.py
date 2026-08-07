"""
ImportExtractor: 从 Python AST 中提取 import 语句。

支持 3 种 ImportKind：
- IMPORT:      import os / import numpy as np
- IMPORT_FROM: from os.path import join / from .repo import UserRepo
- DYNAMIC:     __import__("x") / importlib.import_module("x")
"""
from __future__ import annotations

import ast

from codeteam.imports.models import ImportRecord, ImportKind


class ImportExtractor(ast.NodeVisitor):
    """遍历 Python AST，提取所有 import 语句为 ImportRecord。

    用法：
        tree = ast.parse(source_code)
        extractor = ImportExtractor("path/to/file.py")
        records = extractor.extract(tree)
    """

    def __init__(self, file_path: str) -> None:
        super().__init__()
        self.file_path: str = file_path
        self._records: list[ImportRecord] = []

    # ── 公开入口 ─────────────────────────────────────────────

    def extract(self, tree: ast.AST) -> list[ImportRecord]:
        """提取所有 import 语句，返回 ImportRecord 列表。"""
        self.visit(tree)
        return self._records

    # ── Import 节点处理 ──────────────────────────────────────

    def visit_Import(self, node: ast.Import) -> None:
        """处理 import os / import numpy as np。

        一个 Import 节点可包含多个 alias：
            import os, json as j
        两个 alias 产生两条 ImportRecord。
        """
        line = self._line(node)
        col = self._col(node)

        for alias in node.names:
            record = ImportRecord(
                source_file=self.file_path,
                module=alias.name,       # "os" 或 "os.path"
                name=alias.name,         # 同 module，因为是整个模块导入
                alias=alias.asname,      # "np" 或 None
                level=0,
                kind=ImportKind.IMPORT,
                line=line,
                column=col,
            )
            self._records.append(record)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """处理 from X import Y 和相对导入。

        AST 中 module 不含点，level 表示点数。
            代码                         module        level  拼接结果
            from os import path          "os"           0     "os"
            from .repo import UserRepo   "repo"         1     ".repo"
            from ..repo import Base      "repo"         2     "..repo"
            from . import something      None           1     "."
        """
        # 拼接完整模块路径
        if node.level > 0:
            dots = "." * node.level
            module = dots + (node.module or "")
        else:
            module = node.module or ""

        line = self._line(node)
        col = self._col(node)

        for alias in node.names:
            record = ImportRecord(
                source_file=self.file_path,
                module=module,
                name=alias.name,           # 导入的名字（原始名字）
                alias=alias.asname,        # as 后面的别名，可能为 None
                level=node.level,
                kind=ImportKind.IMPORT_FROM,
                line=line,
                column=col,
            )
            self._records.append(record)

    # ── 动态 Import 检测 ─────────────────────────────────────

    def visit_Call(self, node: ast.Call) -> None:
        """检测动态 import 调用。

        两种形式：
            __import__("os")
            importlib.import_module("os.path")

        只能解析常量字符串参数。变量参数标记为 "<dynamic>"。
        """
        if self._is_dynamic_import(node):
            module_name = self._extract_string_arg(node)
            record = ImportRecord(
                source_file=self.file_path,
                module=module_name or "<dynamic>",
                name=module_name or "<dynamic>",
                kind=ImportKind.DYNAMIC,
                line=self._line(node),
                column=self._col(node),
            )
            self._records.append(record)

        # 无论如何都要继续遍历子节点（可能有嵌套的 import）
        self.generic_visit(node)

    def _is_dynamic_import(self, node: ast.Call) -> bool:
        """判断一个 Call 节点是否是动态 import。

        __import__("x")   → func 是 Name(id='__import__')
        importlib.import_module("x") → func 是
            Attribute(value=Name(id='importlib'), attr='import_module')
        """
        # 检查 __import__("x")
        if isinstance(node.func, ast.Name) and node.func.id == "__import__":
            return True

        # 检查 importlib.import_module("x")
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "import_module"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "importlib"
        ):
            return True

        return False

    @staticmethod
    def _extract_string_arg(node: ast.Call) -> str | None:
        """提取函数调用的第一个字符串常量参数。

        能解析：__import__("os") → "os"
        不能解析：__import__(variable) → None
                   __import__()        → None（无参数）
        """
        if not node.args:
            return None
        first_arg = node.args[0]
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            return first_arg.value
        return None

    # ── 工具方法 ─────────────────────────────────────────────
    def _line(self, node: ast.AST) -> int:
        """获取节点的行号（从 0 开始）。"""
        return node.lineno - 1 if hasattr(node, "lineno") and node.lineno is not None else 0

    def _col(self, node: ast.AST) -> int:
        """获取节点的列号（从 0 开始）。"""
        return node.col_offset if hasattr(node, "col_offset") and node.col_offset is not None else 0