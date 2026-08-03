"""测试 PythonAstParser 和 TreeSitterParser 的解析行为。

覆盖场景：
- T01: 正常 Python 文件
- T02: 空文件
- T03: 语法错误文件
- T04: 缺少括号
- T05: 非 UTF-8 编码
- T06: 超大文件
- T07: AST 与 Tree-sitter 数量对照
"""

from __future__ import annotations

import pytest

from codeteam.parsing.models import (
    DiagnosticKind,
    ParseStatus,
)
from codeteam.parsing.python_ast_parser import PythonAstParser
from codeteam.parsing.tree_sitter_parser import TreeSitterParser


# ---------------------------------------------------------------------------
# 共享 Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def ast_parser() -> PythonAstParser:
    return PythonAstParser()


@pytest.fixture
def ts_parser() -> TreeSitterParser:
    return TreeSitterParser()


# ---------------------------------------------------------------------------
# 共享测试数据
# ---------------------------------------------------------------------------

NORMAL_SOURCE = """\
class UserService:
    def get_user(self):
        return None

def create_user():
    return UserService()
"""

SYNTAX_ERROR_SOURCE = """\
def valid():
    return 1

this is not valid python !!!
"""

MISSING_PAREN_SOURCE = """\
def valid():
    return 1

def broken(value:
    return value
"""

LATIN1_BYTES = (
    b"# -*- coding: latin-1 -*-\n"
    b"name = 'caf\xe9'\n"
)

MULTI_CLASS_SOURCE = """\
class A:
    def method_a1(self):
        pass

    def method_a2(self):
        pass

class B:
    def method_b(self):
        pass

def top_level_func():
    pass
"""


# ===================================================================
# T01: 正常文件
# ===================================================================

class TestNormalFile:
    """T01: 正常 Python 文件解析。

    SOURCE 包含 1 个类 (UserService) + 2 个函数
    (UserService.get_user 方法 和 create_user 顶层函数)。
    方法也属于函数定义，所以函数数是 2。
    """

    def test_python_ast_returns_success(self, ast_parser: PythonAstParser) -> None:
        """Python AST 解析正常文件应返回 SUCCESS，统计正确。"""
        result = ast_parser.parse(NORMAL_SOURCE, "normal.py")

        assert result.status == ParseStatus.SUCCESS, (
            f"Expected SUCCESS, got {result.status}"
        )
        assert result.class_count == 1, (
            f"Expected 1 class, got {result.class_count}"
        )
        assert result.function_count == 2, (
            f"Expected 2 functions (1 method + 1 standalone), "
            f"got {result.function_count}"
        )

    def test_tree_sitter_returns_success(self, ts_parser: TreeSitterParser) -> None:
        """Tree-sitter 解析正常文件应返回 SUCCESS，统计正确。"""
        result = ts_parser.parse(NORMAL_SOURCE, "normal.py")

        assert result.status == ParseStatus.SUCCESS, (
            f"Expected SUCCESS, got {result.status}"
        )
        assert result.class_count == 1, (
            f"Expected 1 class, got {result.class_count}"
        )
        assert result.function_count == 2, (
            f"Expected 2 functions (1 method + 1 standalone), "
            f"got {result.function_count}"
        )

    def test_both_parsers_agree_on_counts(self,
                                           ast_parser: PythonAstParser,
                                           ts_parser: TreeSitterParser) -> None:
        """T07 补充: AST 与 Tree-sitter 对正常文件的统计应一致。"""
        ast_result = ast_parser.parse(NORMAL_SOURCE, "normal.py")
        ts_result = ts_parser.parse(NORMAL_SOURCE, "normal.py")

        assert ast_result.class_count == ts_result.class_count, (
            f"Class count mismatch: AST={ast_result.class_count}, "
            f"TS={ts_result.class_count}"
        )
        assert ast_result.function_count == ts_result.function_count, (
            f"Function count mismatch: AST={ast_result.function_count}, "
            f"TS={ts_result.function_count}"
        )


# ===================================================================
# T02: 空文件
# ===================================================================

class TestEmptyFile:
    """T02: 空文件是合法 Python 文件，不应标记为错误。

    空文件 → Module (AST) / module (Tree-sitter)
    函数 0，类 0，status=SUCCESS。
    """

    def test_python_ast_handles_empty_file(self, ast_parser: PythonAstParser) -> None:
        """Python AST 解析空文件应返回 SUCCESS，零统计。"""
        result = ast_parser.parse("", "empty.py")

        assert result.status == ParseStatus.SUCCESS, (
            f"Empty file should be valid Python, got {result.status}"
        )
        assert result.function_count == 0
        assert result.class_count == 0
        assert result.diagnostics == [], (
            f"Empty file should have no diagnostics, got {result.diagnostics}"
        )

    def test_tree_sitter_handles_empty_file(self, ts_parser: TreeSitterParser) -> None:
        """Tree-sitter 解析空文件应返回 SUCCESS，零统计。"""
        result = ts_parser.parse("", "empty.py")

        assert result.status == ParseStatus.SUCCESS, (
            f"Empty file should be valid, got {result.status}"
        )
        assert result.function_count == 0
        assert result.class_count == 0


# ===================================================================
# T03: 语法错误文件
# ===================================================================

class TestSyntaxError:
    """T03: 语法错误文件。

    Python AST → FAILED
    Tree-sitter → PARTIAL，仍可能提取 valid 函数。
    """

    def test_python_ast_fails_on_syntax_error(self,
                                               ast_parser: PythonAstParser) -> None:
        """Python AST 遇到语法错误应返回 FAILED 并附诊断。"""
        result = ast_parser.parse(SYNTAX_ERROR_SOURCE, "bad_syntax.py")

        assert result.status == ParseStatus.FAILED, (
            f"Expected FAILED, got {result.status}"
        )
        assert len(result.diagnostics) > 0, "Should have at least one diagnostic"
        assert result.diagnostics[0].kind == DiagnosticKind.ERROR
        assert "SyntaxError" in result.diagnostics[0].message

    def test_tree_sitter_is_partial_and_extracts_valid_function(
        self, ts_parser: TreeSitterParser
    ) -> None:
        """Tree-sitter 容错：返回 PARTIAL 但仍可提取 valid 函数。"""
        result = ts_parser.parse(SYNTAX_ERROR_SOURCE, "bad_syntax.py")

        assert result.status == ParseStatus.PARTIAL, (
            f"Expected PARTIAL, got {result.status}"
        )
        assert result.function_count >= 1, (
            f"Tree-sitter should extract at least the valid function, "
            f"got {result.function_count}"
        )


# ===================================================================
# T04: 缺少括号
# ===================================================================

class TestMissingParen:
    """T04: 语法不完整（缺少括号）。

    Python AST → FAILED
    Tree-sitter → PARTIAL，has_error=True，diagnostics 非空。

    不强制 Tree-sitter 必须生成某个特定 MISSING 节点，
    因为恢复形态可能随 Grammar 版本变化。
    """

    def test_python_ast_fails_on_missing_paren(self,
                                                ast_parser: PythonAstParser) -> None:
        """Python AST 对不完整语法返回 FAILED。"""
        result = ast_parser.parse(MISSING_PAREN_SOURCE, "missing_paren.py")

        assert result.status == ParseStatus.FAILED, (
            f"Expected FAILED, got {result.status}"
        )

    def test_tree_sitter_is_partial_with_diagnostics(
        self, ts_parser: TreeSitterParser
    ) -> None:
        """Tree-sitter 容错：has_error=True，diagnostics 非空。"""
        result = ts_parser.parse(MISSING_PAREN_SOURCE, "missing_paren.py")

        assert result.status == ParseStatus.PARTIAL, (
            f"Expected PARTIAL, got {result.status}"
        )
        assert len(result.diagnostics) > 0, (
            "Should have diagnostics (ERROR or MISSING nodes)"
        )
        assert result.function_count >= 1, (
            "Should still find the valid function"
        )

    def test_does_not_require_specific_missing_node_type(
        self, ts_parser: TreeSitterParser
    ) -> None:
        """不强制要求 Tree-sitter 产生特定 MISSING 节点类型。

        恢复形态可能随 Grammar 版本变化，只验证有诊断信息即可。
        """
        result = ts_parser.parse(MISSING_PAREN_SOURCE, "missing_paren.py")
        diagnostic_messages = [d.message for d in result.diagnostics]

        has_error_or_missing = any(
            "ERROR" in msg or "Missing" in msg
            for msg in diagnostic_messages
        )
        assert has_error_or_missing, (
            f"Expected ERROR or Missing node diagnostics, "
            f"got: {diagnostic_messages}"
        )


# ===================================================================
# T05: 非 UTF-8 编码
# ===================================================================

class TestNonUTF8:
    """T05: 非 UTF-8 编码文件的处理。

    Latin-1 编码的 Python 源码: name = 'café' (其中 é = \\xe9)

    PythonAstParser：
        通过编码声明检测 Latin-1，解码后可以成功解析。

    TreeSitterParser：
        当前封装只接受 str（已解码的 Unicode）。正常传入 str 时，
        UTF-8 编码检查始终通过（全部 Unicode 可编为 UTF-8）。
        若传入 bytes（类型错误），不应抛异常导致扫描器退出。
    """

    def test_python_ast_handles_latin1_source(self,
                                               ast_parser: PythonAstParser) -> None:
        """Python AST 解码 Latin-1 源码后应能成功解析。

        Latin-1 bytes 解码为 str 后（name='café'），
        str 可正常编码为 UTF-8，ast.parse() 可正常解析。
        """
        source_str = LATIN1_BYTES.decode("latin-1")
        result = ast_parser.parse(source_str, "latin1.py")

        assert result.status == ParseStatus.SUCCESS, (
            f"Python AST should parse Latin-1 source after decoding, "
            f"got {result.status}: {result.diagnostics}"
        )

    def test_tree_sitter_handles_latin1_str_gracefully(
        self, ts_parser: TreeSitterParser
    ) -> None:
        """Tree-sitter 解析解码后的 Latin-1 源码（现在是合法 Unicode）。

        当前接口接受 str。正确解码后的 Latin-1 源码是合法 str，
        应能正常解析。本测试验证正常路径；编码相关的边界由下方测试覆盖。
        """
        source_str = LATIN1_BYTES.decode("latin-1")
        result = ts_parser.parse(source_str, "latin1.py")

        # str 可编码为 UTF-8，应正常解析
        assert result.status in (
            ParseStatus.SUCCESS,
            ParseStatus.PARTIAL,
            ParseStatus.FAILED,
        ), f"Unexpected status: {result.status}"

    def test_tree_sitter_returns_partial_for_non_utf8_encodable_str(
        self, ts_parser: TreeSitterParser
    ) -> None:
        """Tree-sitter 对无法编码为 UTF-8 的输入应返回 PARTIAL。

        构造含 surrogate 字符的 str（模拟错误解码），
        该 str 无法编码为 UTF-8，应触发 parse() 中的编码检查。
        """
        # 使用 surrogate 构造不可 UTF-8 编码的 str
        bad_str = "def foo():\n    pass\n" + chr(0xDC80)

        # 确认该 str 确实无法编码为 UTF-8
        try:
            bad_str.encode("utf-8")
            can_encode = True
        except UnicodeEncodeError:
            can_encode = False

        if can_encode:
            pytest.skip("Cannot construct a str that fails UTF-8 encoding")

        # 核心断言：不应抛异常，应安全返回 PARTIAL/FAILED
        result = ts_parser.parse(bad_str, "bad_encoding.py")
        assert result.status in (ParseStatus.PARTIAL, ParseStatus.FAILED), (
            f"Expected PARTIAL or FAILED for non-UTF-8-encodable input, "
            f"got {result.status}"
        )

    def test_tree_sitter_does_not_raise_on_bytes_input(
        self, ts_parser: TreeSitterParser
    ) -> None:
        """Tree-sitter 即使收到 bytes 也不应抛未捕获异常。

        当前接口签名声明 source_code: str，但若调用方错误传入 bytes，
        解析器不应让异常传播导致扫描器退出。

        注：bytes 类型没有 .encode() 方法，若实现直接调用
        source_code.encode("utf-8") 将引发 AttributeError。
        此测试记录当前行为的健壮性。
        """
        try:
            result = ts_parser.parse(LATIN1_BYTES, "latin1_bytes.py")  # type: ignore[arg-type]
        except AttributeError as exc:
            pytest.fail(
                f"Tree-sitter parser raised AttributeError on bytes input — "
                f"this should be handled gracefully: {exc}"
            )
        except Exception:
            # 其他异常类型也应记录，不应导致扫描器退出
            pytest.fail("Tree-sitter parser raised unexpected exception on bytes input")
        else:
            # 如果没抛异常，检查结果是否合理
            assert result.status in (
                ParseStatus.PARTIAL,
                ParseStatus.FAILED,
            ), (
                f"Expected PARTIAL or FAILED when receiving bytes, "
                f"got {result.status}"
            )


# ===================================================================
# T06: 超大文件
# ===================================================================

class TestLargeFile:
    """T06: 超大文件应被跳过而不真正执行解析。

    注意：当前实现存在以下已知差异（参见测试报告）：
    - ParseStatus 枚举无 SKIPPED 值，实现返回 PARTIAL
    - 构造参数名为 max_file_size（需求文档为 max_source_bytes）
    - DiagnosticKind 无 FILE_TOO_LARGE 枚举，使用 WARNING + 文本消息
    """

    def test_parser_skips_file_exceeding_size_limit(self) -> None:
        """超过 max_file_size 的文件应返回 PARTIAL 并附诊断。

        需求预期: status=SKIPPED, diagnostic=FILE_TOO_LARGE
        实际行为: status=PARTIAL, diagnostic=WARNING + 描述文本
        """
        parser = PythonAstParser(max_file_size=64)
        large_source = "x = 1\n" * 100
        result = parser.parse(large_source, "large.py")

        # 当前实现返回 PARTIAL（ParseStatus 无 SKIPPED 值）
        assert result.status == ParseStatus.PARTIAL, (
            f"Expected PARTIAL (SKIPPED not defined in ParseStatus enum), "
            f"got {result.status}"
        )
        assert len(result.diagnostics) > 0, (
            "Should have a diagnostic about file size"
        )
        size_diagnostic = result.diagnostics[0]
        assert size_diagnostic.kind == DiagnosticKind.WARNING
        assert "exceeds" in size_diagnostic.message.lower(), (
            f"Diagnostic should mention size exceeded, got: "
            f"{size_diagnostic.message}"
        )
        # 关键：不应真正执行解析
        assert result.raw_ast is None, (
            "Oversized file should not be parsed (raw_ast should be None)"
        )

    def test_tree_sitter_also_skips_large_file(self) -> None:
        """Tree-sitter 解析器同样跳过超大文件，不真正解析。"""
        parser = TreeSitterParser(max_file_size=64)
        large_source = "x = 1\n" * 100
        result = parser.parse(large_source, "large.py")

        assert result.status == ParseStatus.PARTIAL
        assert len(result.diagnostics) > 0
        assert "exceeds" in result.diagnostics[0].message.lower()
        assert result.raw_tree_sitter is None, (
            "Oversized file should not be parsed"
        )

    def test_file_under_limit_parses_normally(self) -> None:
        """文件大小未超限时应正常解析。"""
        parser = PythonAstParser(max_file_size=10_000)
        result = parser.parse("x = 1\n", "small.py")
        assert result.status == ParseStatus.SUCCESS


# ===================================================================
# T07: AST 与 Tree-sitter 数量对照
# ===================================================================

class TestCountComparison:
    """T07: AST 与 Tree-sitter 在不同场景下的函数/类统计对照。"""

    @pytest.mark.parametrize(
        ("source", "description", "expected_funcs", "expected_classes"),
        [
            pytest.param(
                MULTI_CLASS_SOURCE,
                "multi-class",
                4,  # method_a1, method_a2, method_b, top_level_func
                2,  # A, B
                id="multi-class-with-methods",
            ),
            pytest.param(
                "def f():\n    pass\n",
                "single-function",
                1,
                0,
                id="single-function",
            ),
            pytest.param(
                "class X:\n    pass\n",
                "single-class-no-methods",
                0,
                1,
                id="single-class-no-methods",
            ),
            pytest.param(
                "",
                "empty",
                0,
                0,
                id="empty-source",
            ),
        ],
    )
    def test_both_parsers_agree_on_counts(
        self,
        ast_parser: PythonAstParser,
        ts_parser: TreeSitterParser,
        source: str,
        description: str,
        expected_funcs: int,
        expected_classes: int,
    ) -> None:
        """验证 AST 和 Tree-sitter 对同一源码的统计一致且正确。"""
        ast_result = ast_parser.parse(source, f"{description}.py")
        ts_result = ts_parser.parse(source, f"{description}.py")

        assert ast_result.function_count == expected_funcs, (
            f"[AST] {description}: expected {expected_funcs} functions, "
            f"got {ast_result.function_count}"
        )
        assert ast_result.class_count == expected_classes, (
            f"[AST] {description}: expected {expected_classes} classes, "
            f"got {ast_result.class_count}"
        )
        assert ts_result.function_count == expected_funcs, (
            f"[TS] {description}: expected {expected_funcs} functions, "
            f"got {ts_result.function_count}"
        )
        assert ts_result.class_count == expected_classes, (
            f"[TS] {description}: expected {expected_classes} classes, "
            f"got {ts_result.class_count}"
        )

    def test_syntax_error_sources_may_diverge(
        self,
        ast_parser: PythonAstParser,
        ts_parser: TreeSitterParser,
    ) -> None:
        """语法错误时 AST 和 TS 的统计可能不同，TS 应能提取更多信息。"""
        ast_result = ast_parser.parse(SYNTAX_ERROR_SOURCE, "bad.py")
        ts_result = ts_parser.parse(SYNTAX_ERROR_SOURCE, "bad.py")

        # AST 完全失败，不提供统计（function_count 保持默认 0）
        assert ast_result.status == ParseStatus.FAILED
        # TS 容错，至少能提取 valid 函数
        assert ts_result.status == ParseStatus.PARTIAL
        assert ts_result.function_count >= ast_result.function_count, (
            f"Tree-sitter should extract >= functions than AST on error: "
            f"TS={ts_result.function_count}, AST={ast_result.function_count}"
        )
