"""测试 ParserRegistry 的注册、选择和解析功能。

覆盖场景：
- T08: Registry 默认选择
- T09: Registry 指定选择
- T10: 未知语言
- T11: 未知 Parser
"""

from __future__ import annotations

import pytest

from codeteam.parsing.models import (
    ParseStatus,
)
from codeteam.parsing.registry import (
    ParserRegistry,
    UnknownParserError,
    UnsupportedLanguageError,
)


# ---------------------------------------------------------------------------
# 共享 Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def registry() -> ParserRegistry:
    return ParserRegistry()


NORMAL_SOURCE = """\
class UserService:
    def get_user(self):
        return None

def create_user():
    return UserService()
"""


# ===================================================================
# T08: Registry 默认选择
# ===================================================================

class TestRegistryDefaultSelection:
    """T08: Registry 默认选择。

    默认配置：
    - Python 仓库扫描 → tree-sitter（容错）
    - Python 严格验证 → python-ast
    """

    def test_default_for_python_is_tree_sitter(self, registry: ParserRegistry) -> None:
        """Python 语言的默认解析器应是 tree-sitter（容错解析）。"""
        parser = registry.get_default("python")
        assert parser.name == "tree-sitter", (
            f"Expected default 'tree-sitter' for Python, got '{parser.name}'"
        )

    def test_default_for_python_strict_is_python_ast(self,
                                                      registry: ParserRegistry) -> None:
        """Python:strict 的默认解析器应是 python-ast（严格解析）。"""
        parser = registry.get_default("python:strict")
        assert parser.name == "python-ast", (
            f"Expected default 'python-ast' for python:strict, "
            f"got '{parser.name}'"
        )

    def test_default_parse_uses_default_parser(self,
                                                registry: ParserRegistry) -> None:
        """registry.parse() 应使用语言的默认解析器。"""
        result = registry.parse(NORMAL_SOURCE, "python", "test.py")
        # Python 默认是 tree-sitter，应返回 SUCCESS
        assert result.status == ParseStatus.SUCCESS, (
            f"Expected SUCCESS via default parser, got {result.status}"
        )
        assert result.class_count == 1
        assert result.function_count == 2


# ===================================================================
# T09: Registry 指定选择
# ===================================================================

class TestRegistrySpecificSelection:
    """T09: Registry 指定选择。

    可以通过 register() 注册自定义解析器，通过 get() 按名称获取。
    """

    def test_get_returns_registered_parser(self, registry: ParserRegistry) -> None:
        """get() 应按名称返回已注册的解析器。"""
        ts = registry.get("tree-sitter")
        assert ts.name == "tree-sitter"

        ast_p = registry.get("python-ast")
        assert ast_p.name == "python-ast"

    def test_register_overwrites_existing_parser(self,
                                                  registry: ParserRegistry) -> None:
        """register() 允许用户用自定义解析器替换默认的。"""
        from codeteam.parsing.python_ast_parser import PythonAstParser

        custom = PythonAstParser(max_file_size=999)
        registry.register("tree-sitter", custom)  # 覆盖默认
        retrieved = registry.get("tree-sitter")
        assert retrieved is custom, (
            "register() should replace the parser instance"
        )

    def test_different_languages_use_different_defaults(self,
                                                         registry: ParserRegistry) -> None:
        """不同语言标识符对应不同默认解析器。"""
        ts = registry.get_default("python")
        ast_p = registry.get_default("python:strict")
        assert ts.name != ast_p.name, (
            f"python and python:strict should use different defaults, "
            f"got {ts.name} vs {ast_p.name}"
        )


# ===================================================================
# T10: 未知语言
# ===================================================================

class TestUnknownLanguage:
    """T10: 请求未知语言时应抛出 UnsupportedLanguageError。"""

    def test_unsupported_language_raises_error(self,
                                                registry: ParserRegistry) -> None:
        """get_default() 对未配置的语言应抛出 UnsupportedLanguageError。"""
        with pytest.raises(UnsupportedLanguageError) as exc_info:
            registry.get_default("rust")

        error_msg = str(exc_info.value)
        assert "rust" in error_msg, (
            f"Error should mention the unsupported language, got: {error_msg}"
        )
        assert "Unsupported" in error_msg or "unsupported" in error_msg.lower()

    def test_parse_with_unknown_language_raises_error(self,
                                                       registry: ParserRegistry) -> None:
        """registry.parse() 对未知语言也应抛出 UnsupportedLanguageError。"""
        with pytest.raises(UnsupportedLanguageError) as exc_info:
            registry.parse(NORMAL_SOURCE, "javascript", "test.js")

        error_msg = str(exc_info.value)
        assert "javascript" in error_msg, (
            f"Error should mention the unsupported language, got: {error_msg}"
        )

    @pytest.mark.parametrize(
        "language",
        [
            pytest.param("", id="empty-string"),
            pytest.param("c++", id="cpp"),
            pytest.param("typescript", id="typescript"),
        ],
    )
    def test_various_unsupported_languages_raise_error(self,
                                                        registry: ParserRegistry,
                                                        language: str) -> None:
        """多种未配置语言都应抛出 UnsupportedLanguageError。"""
        with pytest.raises(UnsupportedLanguageError):
            registry.get_default(language)


# ===================================================================
# T11: 未知 Parser
# ===================================================================

class TestUnknownParser:
    """T11: 请求未注册的解析器名称时应抛出 UnknownParserError。"""

    def test_unknown_parser_name_raises_error(self,
                                               registry: ParserRegistry) -> None:
        """get() 对未注册的名称应抛出 UnknownParserError。"""
        with pytest.raises(UnknownParserError) as exc_info:
            registry.get("non-existent-parser")

        error_msg = str(exc_info.value)
        assert "non-existent-parser" in error_msg, (
            f"Error should mention the unknown parser name, got: {error_msg}"
        )
        assert "Unknown" in error_msg or "unknown" in error_msg.lower()

    def test_error_message_lists_available_parsers(self,
                                                    registry: ParserRegistry) -> None:
        """错误消息应列出可用的解析器名称。"""
        with pytest.raises(UnknownParserError) as exc_info:
            registry.get("imaginary-parser")

        error_msg = str(exc_info.value)
        # 应列出已注册的解析器
        assert "tree-sitter" in error_msg, (
            f"Error should list 'tree-sitter' as available, got: {error_msg}"
        )
        assert "python-ast" in error_msg, (
            f"Error should list 'python-ast' as available, got: {error_msg}"
        )

    @pytest.mark.parametrize(
        "parser_name",
        [
            pytest.param("", id="empty-string"),
            pytest.param("Tree-Sitter", id="wrong-case"),
            pytest.param("tree_sitter", id="underscore-instead-of-dash"),
        ],
    )
    def test_various_unknown_parser_names_raise_error(self,
                                                       registry: ParserRegistry,
                                                       parser_name: str) -> None:
        """多种无效解析器名称都应抛出 UnknownParserError。"""
        with pytest.raises(UnknownParserError):
            registry.get(parser_name)
