from __future__ import annotations

import ast
from pathlib import Path

from codeteam.parsing.models import (
    ParseResult,
    ParseStatus,
    ParseDiagnostic,
    DiagnosticKind,
    SourcePosition,
    SourceRange,
)
from codeteam.parsing.base import CodeParser

class PythonAstParser:
    """使用 Python 标准库 ast 模块的严格解析器。

    解析成功 → ParseStatus.SUCCESS
    语法错误 → ParseStatus.FAILED（含 ParseDiagnostic）
    编码/大小问题 → ParseStatus.PARTIAL
    """

    def __init__(self, max_file_size: int = 1_000_000) -> None:
        """初始化解析器。

        Args:
            max_file_size: 最大文件大小（字节），默认 1MB。
        """
        self._max_file_size = max_file_size

    @property
    def name(self) -> str:
        return "python-ast"

    def parse(self, source_code: str, file_path: str = "") -> ParseResult:
        # 步骤 1：编码检测
        try:
            source_code.encode("utf-8")
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
        byte_size = len(source_code.encode("utf-8"))
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

        # 步骤 3：调用 ast.parse()
        try:
            tree = ast.parse(source_code)
        except SyntaxError as exc:
            # ast 的行号从 1 开始，我们要转成 0-based
            line = (exc.lineno - 1) if exc.lineno is not None else 0
            col = (exc.offset - 1) if exc.offset is not None else 0
            return ParseResult(
                status=ParseStatus.FAILED,
                file_path=file_path,
                diagnostics=[
                    ParseDiagnostic(
                        kind=DiagnosticKind.ERROR,
                        message=f"SyntaxError: {exc.msg}",
                        range=SourceRange(
                            start=SourcePosition(line=line, column=col),
                            end=SourcePosition(line=line, column=col),
                        ),
                    )
                ],
            )

        # 步骤 4：统计函数和类
        func_count, class_count = self._count_functions_and_classes(tree)

        # 步骤 5：返回成功结果
        return ParseResult(
            status=ParseStatus.SUCCESS,
            file_path=file_path,
            function_count=func_count,
            class_count=class_count,
            raw_ast=tree,
        )

    def _count_functions_and_classes(
        self, tree: ast.AST
    ) -> tuple[int, int]:
        """遍历 AST 树，统计函数和类的数量。

        Returns:
            (function_count, class_count)
        """
        func_count = 0
        class_count = 0

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_count += 1
            elif isinstance(node, ast.ClassDef):
                class_count += 1

        return func_count, class_count