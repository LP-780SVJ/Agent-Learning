# ParserRegistry will choose the correct parser implementation for each detected language and provide a single parsing entrypoint.
from __future__ import annotations

from codeteam.parsing.base import CodeParser
from codeteam.parsing.models import ParseResult, ParseStatus, ParseDiagnostic, DiagnosticKind
from codeteam.parsing.python_ast_parser import PythonAstParser
from codeteam.parsing.tree_sitter_parser import TreeSitterParser

class UnknownParserError(KeyError):
    """请求的解析器名称未注册。"""
    ...

class UnsupportedLanguageError(ValueError):
    """请求的语言没有默认解析器。"""
    ...

class ParserRegistry:
    """解析器注册中心。

    维护一个 name → CodeParser 的映射表，
    根据语言和场景选择最合适的解析器。

    默认配置：
    - Python 仓库扫描 → Tree-sitter（容错，写一半的代码也能解析）
    - Python 严格验证 → Python AST（语法错误直接报 FAILED）
    """

    def __init__(self) -> None:
        self._parsers: dict[str, CodeParser] = {}
        self._defaults: dict[str, str] = {}

        self._setup_defaults()

    def _setup_defaults(self) -> None:
        """注册默认解析器并配置默认选择。"""
        # 注册两个解析器实例
        self.register("tree-sitter", TreeSitterParser())
        self.register("python-ast", PythonAstParser())

        # 配置默认选择：哪个语言默认走哪个解析器
        # "语言 → 解析器名" 的映射
        self._defaults["python"] = "tree-sitter"
        self._defaults["python:strict"] = "python-ast"


    def register(self, name: str, parser: CodeParser) -> None:
        """注册一个解析器。

        Args:
            name: 解析器的名称（如 "tree-sitter"）。
            parser: CodeParser 实例。
        """
        self._parsers[name] = parser# 允许用户用自定义解析器替换默认的

    def get(self, name: str) -> CodeParser:
        """按名称获取解析器。

        Args:
            name: 解析器名称。

        Returns:
            CodeParser 实例。

        Raises:
            UnknownParserError: 名称未注册。
        """
        if name not in self._parsers:# 哈希查找
            raise UnknownParserError(
                f"Unknown parser: {name!r}. "
                f"Available: {list(self._parsers.keys())}"
            )
        return self._parsers[name]

    def get_default(self, language: str) -> CodeParser:
        """根据语言获取默认解析器。

        Args:
            language: 语言标识符，如 "python"、"python:strict"。

        Returns:
            默认的 CodeParser 实例。

        Raises:
            UnsupportedLanguageError: 语言没有配置默认解析器。
        """
        if language not in self._defaults:
            raise UnsupportedLanguageError(
                f"Unsupported language: {language!r}. "
                f"Supported: {list(self._defaults.keys())}"
            )
        parser_name = self._defaults[language]
        return self._parsers[parser_name]

    def parse(
        self, 
        source_code: str, 
        language: str, 
        file_path: str = ""
        ) -> ParseResult:
        """使用默认解析器解析源代码。

        这是最常用的入口——调用者只需要传源代码和语言，
        不需要知道底层用了哪个解析器。

        Args:
            source_code: 源代码字符串。
            language: 语言标识符（如 "python"）。
            file_path: 文件路径（可选，用于错误报告）。

        Returns:
            ParseResult。
        """
        parser = self.get_default(language)
        return parser.parse(source_code, file_path)