# Tree-sitter parser integration will provide an optional syntax-tree backend for languages that need richer structural parsing.
from __future__ import annotations

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

from codeteam.parsing.base import CodeParser
from codeteam.parsing.models import (
    DiagnosticKind,
    ParseDiagnostic,
    ParseResult,
    ParseStatus,
    SourcePosition,
    SourceRange,
)

# 模块级常量：加载一次 Python 语法，所有实例共享
PY_LANGUAGE = Language(tspython.language())

class TreeSitterParser:
    """使用 Tree-sitter 的容错解析器。

    解析成功且无错误 → ParseStatus.SUCCESS
    解析成功但有 ERROR/MISSING → ParseStatus.PARTIAL
    编码问题 → ParseStatus.PARTIAL
    """

    def __init__(self, max_file_size: int = 1_000_000) -> None:
        self._max_file_size = max_file_size
        self._parser = Parser(PY_LANGUAGE)

    @property
    def name(self) -> str:
        return "tree-sitter"

    def parse(self, source_code: str, file_path: str = "") -> ParseResult:
        # 步骤 1：编码为 UTF-8 bytes
        try:
            source_bytes = source_code.encode("utf-8")
        except UnicodeEncodeError:
            return ParseResult(
                status=ParseStatus.PARTIAL,
                file_path=file_path,
                diagnostics=[
                    ParseDiagnostic(
                        kind=DiagnosticKind.ERROR,
                        message="Source code is not valid UTF-8",
                    )
                ],
            )

        # 步骤 2：文件大小检测
        byte_size = len(source_bytes)
        if byte_size > self._max_file_size:
            return ParseResult(
                status=ParseStatus.PARTIAL,
                file_path=file_path,
                diagnostics=[
                    ParseDiagnostic(
                        kind=DiagnosticKind.WARNING,
                        message=(
                            f"File size ({byte_size} bytes) exceeds "
                            f"limit ({self._max_file_size} bytes)"
                        ),
                    )
                ],
            )

        # 步骤 3：解析（不会抛异常，语法错误只标记在树上）
        tree = self._parser.parse(source_bytes)

        # 步骤 4：遍历整棵树，统计函数/类 + 收集错误
        counters = {"functions": 0, "classes": 0}
        errors: list[ParseDiagnostic] = []
        self._visit_node(tree.root_node, source_bytes, counters, errors)

        # 步骤 5：判断最终状态
        status = (
            ParseStatus.PARTIAL
            if tree.root_node.has_error
            else ParseStatus.SUCCESS
        )

        return ParseResult(
            status=status,
            file_path=file_path,
            diagnostics=errors,
            function_count=counters["functions"],
            class_count=counters["classes"],
            raw_tree_sitter=tree,
        )

    def _visit_node(
        self,
        node: Node,
        source_bytes: bytes,
        counters: dict[str, int],
        diagnostics: list[ParseDiagnostic],
    ) -> None:
        # 检查当前节点是不是错误
        if node.type == "ERROR":
            diagnostics.append(
                ParseDiagnostic(
                    kind=DiagnosticKind.ERROR,
                    message="Tree-sitter ERROR node",
                    range=SourceRange(
                        start=SourcePosition(
                            line=node.start_point[0],
                            column=node.start_point[1],
                        ),
                        end=SourcePosition(
                            line=node.end_point[0],
                            column=node.end_point[1],
                        ),
                    ),
                )
            )

        # 检查当前节点是不是 MISSING（语法上应该有，但代码里没写）
        if node.is_missing:
            diagnostics.append(
                ParseDiagnostic(
                    kind=DiagnosticKind.WARNING,
                    message=f"Missing node: {node.type}",
                    range=SourceRange(
                        start=SourcePosition(
                            line=node.start_point[0],
                            column=node.start_point[1],
                        ),
                        end=SourcePosition(
                            line=node.end_point[0],
                            column=node.end_point[1],
                        ),
                    ),
                )
            )

        # 统计函数和类（只看 named 节点）
        if node.is_named:
            if node.type == "function_definition":
                counters["functions"] += 1
            elif node.type == "class_definition":
                counters["classes"] += 1

        # 递归遍历子节点
        for child in node.children:
            self._visit_node(child, source_bytes, counters, diagnostics)
