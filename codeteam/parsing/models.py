'''
codeteam.parsing.models - 解析系统的统一数据模型

所有解析器（Python AST、 Tree-sitter 等）最终都输出这里定义的统一结构。
下游代码（SymbolExtractor 等）只消费这些模型，不接触底层解析器。
'''

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

'''
状态枚举
'''
class ParseStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"

class DiagnosticKind(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

'''
位置信息
'''
@dataclass(frozen=True)
class SourcePosition:
    '''
    源代码中的一个位置（行和列，从0开始计数）
    统一规定：所有行号和列号都从0开始
    - Python AST默认从1开始计数，所以需要减1
    - Tree-sitter默认从0开始计数
    '''

    line: int
    column: int

@dataclass(frozen=True)
class SourceRange:
    start: SourcePosition
    end: SourcePosition

'''
诊断信息
'''
@dataclass
class ParseDiagnostic:
    kind: DiagnosticKind
    message: str
    range: SourceRange | None = None

'''
解析结果
'''
@dataclass
class ParseResult:
    status: ParseStatus
    file_path: str = ""
    language: str = "python"

    diagnostics: list[ParseDiagnostic] = field(default_factory=list)

    # 统计摘要
    function_count: int = 0
    class_count: int = 0

    # 调试信息（原始树，供开发调试使用）
    raw_ast: Any = None
    raw_tree_sitter: Any = None
