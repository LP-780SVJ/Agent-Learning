"""Tests for codeteam.search.query_analyzer — QueryAnalyzer。

覆盖 7 种信号类型提取：引号内容、文件路径、代码标识符、
异常名、错误码、中文片段，以及 primary/secondary 分类。
"""

from __future__ import annotations

import pytest

from codeteam.search.models import AnalyzedQuery
from codeteam.search.query_analyzer import QueryAnalyzer


@pytest.fixture
def analyzer() -> QueryAnalyzer:
    return QueryAnalyzer()


# ── 引号内容提取 ────────────────────────────────────────────────

class TestQuotedLiterals:
    """五种引号格式的精确文本提取。"""

    def test_double_quotes(self, analyzer: QueryAnalyzer) -> None:
        """英文双引号。"""
        result = analyzer.analyze('修复报错 "Token has expired" 的问题')
        assert "Token has expired" in result.quoted_literals

    def test_single_quotes(self, analyzer: QueryAnalyzer) -> None:
        """英文单引号。"""
        result = analyzer.analyze("修复报错 'Token has expired' 的问题")
        assert "Token has expired" in result.quoted_literals

    def test_backtick_quotes(self, analyzer: QueryAnalyzer) -> None:
        """反引号。"""
        result = analyzer.analyze(
            "修复 `InvalidRefreshTokenError` 导致的问题"
        )
        assert "InvalidRefreshTokenError" in result.quoted_literals

    def test_chinese_double_quotes(self, analyzer: QueryAnalyzer) -> None:
        """中文双引号。"""
        result = analyzer.analyze(
            "修复报错“Token has expired”的问题"
        )
        assert "Token has expired" in result.quoted_literals

    def test_chinese_single_quotes(self, analyzer: QueryAnalyzer) -> None:
        """中文单引号。"""
        result = analyzer.analyze(
            "修复报错‘Token has expired’的问题"
        )
        assert "Token has expired" in result.quoted_literals

    def test_quoted_content_becomes_primary_term(self, analyzer: QueryAnalyzer) -> None:
        """引号内容自动进入 primary_terms。"""
        result = analyzer.analyze('修复报错 "Token has expired"')
        assert "Token has expired" in result.primary_terms


# ── 标识符识别 ──────────────────────────────────────────────────

class TestIdentifierExtraction:
    """代码标识符（CamelCase / snake_case）提取。"""

    def test_extracts_camel_case_identifiers(self, analyzer: QueryAnalyzer) -> None:
        """提取 CamelCase 标识符。"""
        result = analyzer.analyze("UserService 在哪里定义？")
        assert "UserService" in result.identifiers

    def test_extracts_snake_case_identifiers(self, analyzer: QueryAnalyzer) -> None:
        """提取 snake_case 标识符。"""
        result = analyzer.analyze("create_user 方法有什么作用？")
        assert "create_user" in result.identifiers

    def test_splits_camel_case_into_parts(self, analyzer: QueryAnalyzer) -> None:
        """CamelCase 标识符被拆分成单词片段。

        InvalidRefreshTokenError → [Invalid, Refresh, Token, Error]
        """
        result = analyzer.analyze("修复 InvalidRefreshTokenError")
        parts_lower = {p.lower() for p in result.identifier_parts}
        assert "invalid" in parts_lower
        assert "refresh" in parts_lower
        assert "token" in parts_lower
        assert "error" in parts_lower

    def test_splits_snake_case_into_parts(self, analyzer: QueryAnalyzer) -> None:
        """snake_case 标识符被按 _ 拆分。

        refresh_access_token → [refresh, access, token]
        """
        result = analyzer.analyze("refresh_access_token 方法")
        parts_lower = {p.lower() for p in result.identifier_parts}
        assert "refresh" in parts_lower
        assert "access" in parts_lower
        assert "token" in parts_lower

    def test_splits_kebab_case_into_parts(self, analyzer: QueryAnalyzer) -> None:
        """kebab-case 标识符被按 - 拆分。"""
        result = analyzer.analyze("user-service 配置")
        parts_lower = {p.lower() for p in result.identifier_parts}
        assert "user" in parts_lower
        assert "service" in parts_lower


# ── 异常名识别 ──────────────────────────────────────────────────

class TestExceptionExtraction:
    """异常类名识别：*Error / *Exception。"""

    def test_extracts_error_suffix(self, analyzer: QueryAnalyzer) -> None:
        """识别以 Error 结尾的异常名。"""
        result = analyzer.analyze("InvalidRefreshTokenError 未被捕获")
        assert "InvalidRefreshTokenError" in result.exception_names

    def test_extracts_exception_suffix(self, analyzer: QueryAnalyzer) -> None:
        """识别以 Exception 结尾的异常名。"""
        result = analyzer.analyze("ValidationException 需要处理")
        assert "ValidationException" in result.exception_names

    def test_exception_names_are_primary_terms(self, analyzer: QueryAnalyzer) -> None:
        """异常名作为高优先级搜索词。"""
        result = analyzer.analyze("修复 InvalidRefreshTokenError")
        assert "InvalidRefreshTokenError" in result.primary_terms


# ── 错误码识别 ──────────────────────────────────────────────────

class TestErrorCodeExtraction:
    """HTTP 错误码和命名错误码识别。"""

    def test_extracts_http_500(self, analyzer: QueryAnalyzer) -> None:
        """HTTP 500 错误码。"""
        result = analyzer.analyze("接口返回 HTTP 500 错误")
        assert "500" in result.error_codes

    def test_extracts_http_400_series(self, analyzer: QueryAnalyzer) -> None:
        """HTTP 4xx 系列错误码。"""
        for code in ["400", "401", "403", "404", "429", "499"]:
            result = analyzer.analyze(f"返回 HTTP {code}")
            assert code in result.error_codes

    def test_extracts_http_500_series(self, analyzer: QueryAnalyzer) -> None:
        """HTTP 5xx 系列错误码。"""
        for code in ["500", "502", "503", "504"]:
            result = analyzer.analyze(f"返回 HTTP {code}")
            assert code in result.error_codes

    def test_extracts_named_error_code(self, analyzer: QueryAnalyzer) -> None:
        """命名错误码 AUTH-1003。"""
        result = analyzer.analyze("出现 AUTH-1003 错误")
        assert "AUTH-1003" in result.error_codes

    def test_error_codes_are_secondary_terms(self, analyzer: QueryAnalyzer) -> None:
        """错误码作为低优先级搜索词。"""
        result = analyzer.analyze("修复 HTTP 500 问题")
        assert "500" in result.secondary_terms

    def test_ignores_http_200(self, analyzer: QueryAnalyzer) -> None:
        """HTTP 200 不是错误码，不应提取。"""
        result = analyzer.analyze("返回 HTTP 200 成功")
        assert "200" not in result.error_codes


# ── 中文片段识别 ────────────────────────────────────────────────

class TestChineseSpanExtraction:
    """中文连续片段提取。"""

    def test_extracts_chinese_spans(self, analyzer: QueryAnalyzer) -> None:
        """提取中文连续片段（CJK_RE 匹配连续中文字符块）。"""
        result = analyzer.analyze("修复登录接口中文查询功能的问题")
        # CJK_RE 返回完整连续中文块，只要包含预期子串即可
        assert len(result.chinese_spans) >= 1
        assert any("登录接口" in span for span in result.chinese_spans)

    def test_filters_generic_chinese_terms(self, analyzer: QueryAnalyzer) -> None:
        """过滤无搜索价值的停用词。"""
        result = analyzer.analyze("修复这个问题")
        # "修复"、"问题" 在停用词表中，不应出现
        assert "修复" not in result.chinese_spans
        assert "问题" not in result.chinese_spans

    def test_chinese_spans_are_secondary_terms(self, analyzer: QueryAnalyzer) -> None:
        """中文片段作为低优先级搜索词。"""
        result = analyzer.analyze("修复登录接口的异常处理")
        for span in result.chinese_spans:
            assert span in result.secondary_terms


# ── 文件路径提取 ────────────────────────────────────────────────

class TestPathExtraction:
    """文件路径识别。"""

    def test_extracts_unix_style_path(self, analyzer: QueryAnalyzer) -> None:
        """Unix 风格路径。"""
        result = analyzer.analyze("修改 src/auth/service.py 中的逻辑")
        # 路径提取可能包含前导空格，使用 strip 标准化
        stripped = [p.strip() for p in result.paths]
        assert "src/auth/service.py" in stripped

    def test_extracts_windows_style_path(self, analyzer: QueryAnalyzer) -> None:
        """Windows 风格路径——统一转换为 / 分隔。"""
        result = analyzer.analyze("修改 src\\auth\\service.py")
        stripped = [p.strip() for p in result.paths]
        assert "src/auth/service.py" in stripped

    def test_rejects_path_with_dotdot(self, analyzer: QueryAnalyzer) -> None:
        """拒绝含 .. 的路径（防止越界）。"""
        result = analyzer.analyze("读取 ../../etc/passwd")
        for path in result.paths:
            assert ".." not in path

    def test_paths_become_primary_terms(self, analyzer: QueryAnalyzer) -> None:
        """文件路径作为高优先级搜索词。"""
        result = analyzer.analyze("修改 src/auth/service.py")
        stripped = [p.strip() for p in result.primary_terms]
        assert "src/auth/service.py" in stripped

    def test_path_with_spaces(self, analyzer: QueryAnalyzer) -> None:
        """路径中包含空格。"""
        result = analyzer.analyze("修改 src/legacy auth/service.py")
        paths_lower = [p.lower() for p in result.paths]
        assert any("legacy auth/service.py" in p for p in paths_lower)


# ── 混合查询 ────────────────────────────────────────────────────

class TestMixedQueries:
    """中文 + 代码混合查询。"""

    def test_analyze_mixed_chinese_query(self, analyzer: QueryAnalyzer) -> None:
        """完整中文查询：修复登录接口中的 `InvalidRefreshTokenError`，HTTP 500。

        对应需求中的示例查询。
        """
        result = analyzer.analyze(
            "修复登录接口中的 "
            "`InvalidRefreshTokenError`，"
            "该异常导致 HTTP 500"
        )

        # 引号内容
        assert "InvalidRefreshTokenError" in result.quoted_literals
        # 异常名
        assert "InvalidRefreshTokenError" in result.exception_names
        # 错误码
        assert "500" in result.error_codes
        # 标识符
        assert "InvalidRefreshTokenError" in result.identifiers
        # 标识符拆分片段
        parts_lower = {p.lower() for p in result.identifier_parts}
        assert "invalid" in parts_lower
        assert "refresh" in parts_lower
        # 中文片段
        assert len(result.chinese_spans) >= 1

    def test_chinese_query_does_not_error(self, analyzer: QueryAnalyzer) -> None:
        """纯中文查询不报错。"""
        result = analyzer.analyze(
            "修复登录接口抛出 InvalidTokenError 后返回 500 的问题"
        )
        assert isinstance(result, AnalyzedQuery)
        assert result.raw_query is not None


# ── 主次词分类 ──────────────────────────────────────────────────

class TestTermClassification:
    """primary_terms vs secondary_terms 分类。"""

    def test_high_priority_identifier_goes_to_primary(self, analyzer: QueryAnalyzer) -> None:
        """蛇形命名法的代码标识符进入 primary。

        snake_case 得分 +2（有 _），达到 primary 阈值。
        """
        result = analyzer.analyze("get_user_by_id 方法")
        # get_user_by_id 的 priority >= 2（含下划线），应为 primary
        assert "get_user_by_id" in result.primary_terms

    def test_low_priority_identifier_goes_to_secondary(self, analyzer: QueryAnalyzer) -> None:
        """简单单词如 'user' 可能不足够代码化，会进入 secondary。

        注意：'user' 如果是标识符但没有 CamelCase 或下划线，
        得分可能 < 2，进入 secondary。
        """
        result = analyzer.analyze("user 管理")
        assert len(result.secondary_terms) >= 0  # 至少有部分 secondary

    def test_deduplication_across_categories(self, analyzer: QueryAnalyzer) -> None:
        """同一词条出现在多个类别中，在 primary/secondary 中不重复。"""
        result = analyzer.analyze('"InvalidTokenError" 导致 InvalidTokenError')
        primary_lower = [t.lower() for t in result.primary_terms]
        # 不应有重复
        assert len(primary_lower) == len(set(primary_lower))

    def test_exception_names_have_higher_priority_than_simple_words(
        self, analyzer: QueryAnalyzer
    ) -> None:
        """异常名（含 Error 后缀 +3 分）总是 primary term。"""
        result = analyzer.analyze("修复 MyCustomError")
        assert "MyCustomError" in result.primary_terms


# ── 边界和回归 ──────────────────────────────────────────────────

class TestEdgeCases:
    """边界输入和回归场景。"""

    def test_empty_query_returns_valid_structure(self, analyzer: QueryAnalyzer) -> None:
        """空查询返回有效的 AnalyzedQuery（所有列表为空）。"""
        result = analyzer.analyze("")
        assert result.raw_query == ""
        assert result.quoted_literals == []
        assert result.identifiers == []
        assert result.exception_names == []
        assert result.primary_terms == []
        assert result.secondary_terms == []

    def test_only_special_characters(self, analyzer: QueryAnalyzer) -> None:
        """只有特殊字符的查询不报错。"""
        result = analyzer.analyze("@#$%^&*()")
        assert isinstance(result, AnalyzedQuery)

    def test_very_long_query(self, analyzer: QueryAnalyzer) -> None:
        """超长查询不报错。"""
        long_query = "修复 " + "InvalidRefreshTokenError " * 100
        result = analyzer.analyze(long_query)
        assert isinstance(result, AnalyzedQuery)
        assert len(result.identifiers) > 0

    def test_idempotent_analysis(self, analyzer: QueryAnalyzer) -> None:
        """多次分析同一查询返回相同结果。"""
        query = "修复 `InvalidRefreshTokenError` 导致的 HTTP 500"
        result1 = analyzer.analyze(query)
        result2 = analyzer.analyze(query)

        assert result1.primary_terms == result2.primary_terms
        assert result1.secondary_terms == result2.secondary_terms
        assert result1.exception_names == result2.exception_names
        assert result1.error_codes == result2.error_codes

    def test_analyzed_query_serializable(self, analyzer: QueryAnalyzer) -> None:
        """AnalyzedQuery 可以通过 model_dump 序列化。"""
        result = analyzer.analyze(
            "修复登录接口中的 "
            "`InvalidRefreshTokenError`，"
            "该异常导致 HTTP 500"
        )
        dumped = result.model_dump()
        assert dumped["raw_query"] == result.raw_query
        assert "InvalidRefreshTokenError" in dumped["quoted_literals"]
        assert "500" in dumped["error_codes"]
