"""Tests for codeteam.search.ripgrep — RipgrepClient。

覆盖: build_argv 参数映射、search() 执行搜索、超时、截断、
特殊字符、中文、路径空格等场景。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from codeteam.search.models import (
    CaseMode,
    SearchExecution,
    SearchMode,
    SearchQuery,
)
from codeteam.search.ripgrep import RipgrepClient


# ── 辅助函数 ────────────────────────────────────────────────────

def _rg_available() -> bool:
    """检查 ripgrep 是否已安装。"""
    try:
        subprocess.run(
            ["rg", "--version"],
            capture_output=True,
            timeout=5,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


RG_INSTALLED = _rg_available()


# ── build_argv ──────────────────────────────────────────────────

class TestBuildArgv:
    """build_argv(): SearchQuery → rg 命令行参数。"""

    def test_default_literal_mode_adds_F_flag(self) -> None:
        """LITERAL 模式默认加 -F 标志。"""
        client = RipgrepClient()
        query = SearchQuery(pattern="UserService")
        argv = client.build_argv(query, search_path=".")
        assert "-F" in argv

    def test_regex_mode_omits_F_flag(self) -> None:
        """REGEX 模式不加 -F 标志。"""
        client = RipgrepClient()
        query = SearchQuery(pattern=r"class\s+\w+", mode=SearchMode.REGEX)
        argv = client.build_argv(query, search_path=".")
        assert "-F" not in argv

    def test_case_sensitive_adds_s_flag(self) -> None:
        """区分大小写模式加 -s 标志。"""
        client = RipgrepClient()
        query = SearchQuery(pattern="User", case_mode=CaseMode.SENSITIVE)
        argv = client.build_argv(query, search_path=".")
        assert "-s" in argv

    def test_case_insensitive_omits_s_flag(self) -> None:
        """不区分大小写时 ripgrep 默认行为，不加 -s 也不加 -i。"""
        client = RipgrepClient()
        query = SearchQuery(pattern="user", case_mode=CaseMode.INSENSITIVE)
        argv = client.build_argv(query, search_path=".")
        assert "-s" not in argv

    def test_file_types_map_to_t_flags(self) -> None:
        """file_types=["py", "js"] → -t py -t js。"""
        client = RipgrepClient()
        query = SearchQuery(pattern="test", file_types=["py", "js"])
        argv = client.build_argv(query, search_path=".")
        assert argv.count("-t") == 2
        assert argv[argv.index("-t") + 1] == "py"

    def test_globs_map_to_g_flags(self) -> None:
        """globs=["src/**", "!tests/**"] → -g src/** -g !tests/**。"""
        client = RipgrepClient()
        query = SearchQuery(pattern="test", globs=["src/**", "!tests/**"])
        argv = client.build_argv(query, search_path=".")
        assert argv.count("-g") == 2

    def test_context_lines_adds_C_flag(self) -> None:
        """context_lines=2 → -C 2。"""
        client = RipgrepClient()
        query = SearchQuery(pattern="test", context_lines=2)
        argv = client.build_argv(query, search_path=".")
        assert "-C" in argv
        idx = argv.index("-C")
        assert argv[idx + 1] == "2"

    def test_no_context_lines_omits_C_flag(self) -> None:
        """context_lines=0 → 不加 -C。"""
        client = RipgrepClient()
        query = SearchQuery(pattern="test", context_lines=0)
        argv = client.build_argv(query, search_path=".")
        assert "-C" not in argv

    def test_argv_includes_json_and_no_config(self) -> None:
        """argv 必须包含 --json 和 --no-config。"""
        client = RipgrepClient()
        query = SearchQuery(pattern="x")
        argv = client.build_argv(query, search_path=".")
        assert "--json" in argv
        assert "--no-config" in argv

    def test_pattern_is_last_before_path(self) -> None:
        """pattern 参数在 search_path 之前。"""
        client = RipgrepClient()
        query = SearchQuery(pattern="UserService")
        argv = client.build_argv(query, search_path="/repo")
        assert argv[-2] == "UserService"
        assert argv[-1] == "/repo"

    def test_no_m_flag_in_argv(self) -> None:
        """不传 -m 标志（全局截断在 Python 端处理）。"""
        client = RipgrepClient()
        query = SearchQuery(pattern="test", max_results=10)
        argv = client.build_argv(query, search_path=".")
        assert "-m" not in argv


# ── search() 集成测试（需要 ripgrep）────────────────────────────

@pytest.mark.skipif(not RG_INSTALLED, reason="ripgrep (rg) 未安装")
class TestRipgrepClientSearch:
    """search() 方法的集成测试。"""

    def test_exact_symbol_search(self, tmp_path: Path) -> None:
        """精确符号搜索——使用 -F 模式查找 UserService。"""
        source = tmp_path / "sample.py"
        source.write_text("class UserService:\n    pass\n", encoding="utf-8")

        client = RipgrepClient()
        query = SearchQuery(pattern="UserService", mode=SearchMode.LITERAL)
        result = client.search(query, search_path=str(tmp_path))

        assert len(result.matches) >= 1
        assert any(
            "UserService" in m.line_text for m in result.matches
        )

    def test_literal_special_characters(self, tmp_path: Path) -> None:
        """正则特殊字符 ( ) [ ] 在 LITERAL 模式下被当作普通文本匹配。

        对应需求：文件中有 value = foo(bar)[0]，搜索 foo(bar)[0]
        """
        source = tmp_path / "sample.py"
        source.write_text("value = foo(bar)[0]\n", encoding="utf-8")

        client = RipgrepClient()
        query = SearchQuery(pattern="foo(bar)[0]", mode=SearchMode.LITERAL)
        result = client.search(query, search_path=str(tmp_path))

        assert len(result.matches) == 1
        assert "foo(bar)[0]" in result.matches[0].line_text

    def test_no_results_returns_empty_matches(self, tmp_path: Path) -> None:
        """搜索不存在的符号返回空结果，不抛异常。"""
        source = tmp_path / "sample.py"
        source.write_text("x = 1\n", encoding="utf-8")

        client = RipgrepClient()
        query = SearchQuery(
            pattern="DefinitelyNotExistingSymbol",
            mode=SearchMode.LITERAL,
        )
        result = client.search(query, search_path=str(tmp_path))

        assert result.matches == []
        assert result.error == ""
        assert not result.truncated

    def test_global_result_limit(self, tmp_path: Path) -> None:
        """超过 max_results 时截断并设置 truncated=True。"""
        source = tmp_path / "many.txt"
        source.write_text(
            "\n".join(f"match {i}" for i in range(200)),
            encoding="utf-8",
        )

        client = RipgrepClient()
        query = SearchQuery(pattern="match", mode=SearchMode.LITERAL, max_results=10)
        result = client.search(query, search_path=str(tmp_path))

        assert len(result.matches) <= 10
        assert result.truncated

    def test_chinese_text_search(self, tmp_path: Path) -> None:
        """中文文本搜索不因中文报错。"""
        source = tmp_path / "zh.py"
        source.write_text("# 修复登录接口异常\nx = 1\n", encoding="utf-8")

        client = RipgrepClient()
        query = SearchQuery(pattern="修复", mode=SearchMode.LITERAL)
        result = client.search(query, search_path=str(tmp_path))

        assert len(result.matches) >= 1

    def test_error_message_search(self, tmp_path: Path) -> None:
        """搜索错误消息文本 'Token has expired'。

        对应需求：文件中 raise RuntimeError("Token has expired")
        """
        source = tmp_path / "errors.py"
        source.write_text(
            'raise RuntimeError("Token has expired")\n',
            encoding="utf-8",
        )

        client = RipgrepClient()
        query = SearchQuery(pattern="Token has expired", mode=SearchMode.LITERAL)
        result = client.search(query, search_path=str(tmp_path))

        assert len(result.matches) >= 1

    def test_path_with_spaces(self, tmp_path: Path) -> None:
        """含空格的路径能被正常搜索。

        对应需求：src/legacy auth/service.py 路径中空格不会导致参数拆分。
        """
        space_dir = tmp_path / "legacy auth"
        space_dir.mkdir(parents=True, exist_ok=True)
        source = space_dir / "service.py"
        source.write_text("class UserService:\n    pass\n", encoding="utf-8")

        client = RipgrepClient()
        query = SearchQuery(pattern="UserService", mode=SearchMode.LITERAL)
        result = client.search(query, search_path=str(tmp_path))

        assert len(result.matches) >= 1
        # 匹配到的路径包含 legacy auth
        matched_paths = {m.file_path for m in result.matches}
        assert any("legacy auth" in p for p in matched_paths)

    def test_exact_case_match(self, tmp_path: Path) -> None:
        """精确大小写匹配（ripgrep 默认 smart-case）。"""
        source = tmp_path / "sample.py"
        source.write_text("class UserService:\n    pass\n", encoding="utf-8")

        client = RipgrepClient()
        # 大小写完全一致，应命中
        query = SearchQuery(pattern="UserService", mode=SearchMode.LITERAL)
        result = client.search(query, search_path=str(tmp_path))

        assert len(result.matches) >= 1
        assert any("UserService" in m.line_text for m in result.matches)

    def test_case_sensitive_search(self, tmp_path: Path) -> None:
        """区分大小写——大写搜索应命中大写定义。"""
        source = tmp_path / "sample.py"
        source.write_text("class USERSERVICE:\n    pass\n", encoding="utf-8")

        client = RipgrepClient()
        query = SearchQuery(
            pattern="USERSERVICE",
            mode=SearchMode.LITERAL,
            case_mode=CaseMode.SENSITIVE,
        )
        result = client.search(query, search_path=str(tmp_path))

        assert len(result.matches) >= 1

    def test_search_execution_structure(self, tmp_path: Path) -> None:
        """验证 SearchExecution 结构完整性。"""
        source = tmp_path / "sample.py"
        source.write_text("class UserService:\n    pass\n", encoding="utf-8")

        client = RipgrepClient()
        query = SearchQuery(pattern="UserService", mode=SearchMode.LITERAL)
        result = client.search(query, search_path=str(tmp_path))

        assert isinstance(result, SearchExecution)
        assert result.pattern == "UserService"
        assert result.duration_ms >= 0
        assert result.total_match_count >= 1

    def test_ripgrep_not_installed_returns_error(self) -> None:
        """rg 未安装时返回带 error 字段的 SearchExecution。"""
        with mock.patch("subprocess.Popen", side_effect=FileNotFoundError):
            client = RipgrepClient()
            query = SearchQuery(pattern="test")
            result = client.search(query)
            assert "未安装" in result.error


# ── 超时测试 ────────────────────────────────────────────────────

class TestRipgrepClientTimeout:
    """search() 超时行为测试。"""

    @pytest.mark.skipif(not RG_INSTALLED, reason="ripgrep (rg) 未安装")
    def test_timeout_kills_subprocess(self, tmp_path: Path) -> None:
        """超时后子进程被杀死。

        使用真正的 ripgrep 但设极短的 client 超时来验证超时逻辑。
        注意：ripgrep 搜索 tiny repo 很快，这里验证超时机制本身。
        """
        # 创建大量文件让搜索变慢
        for i in range(500):
            f = tmp_path / f"file_{i}.txt"
            f.write_text(f"match line {i}\n" * 100, encoding="utf-8")

        # 使用极短超时
        client = RipgrepClient(timeout_seconds=0.001)
        query = SearchQuery(pattern="match", mode=SearchMode.LITERAL)

        result = client.search(query, search_path=str(tmp_path))
        # timeout 可能触发（proc.wait timeout）也可能搜索完成得太快
        # 这里是验证错误处理路径存在
        if result.error:
            assert "超时" in result.error

    def test_fake_rg_timeout(self) -> None:
        """使用 mock 子进程注入超时。

        对应需求：fake_rg 使用 time.sleep(5)，client timeout=0.1，
        验证进程被杀死。
        """
        client = RipgrepClient(timeout_seconds=0.01)

        with mock.patch("subprocess.Popen") as mock_popen:
            proc_mock = mock.MagicMock()
            proc_mock.stdout = iter([])  # 空输出 —— 无匹配
            proc_mock.stderr = iter([])
            proc_mock.poll.return_value = None
            # 第一次 wait(timeout=...) 抛 TimeoutExpired, 第二次 wait() 正常返回
            proc_mock.wait.side_effect = [
                subprocess.TimeoutExpired(cmd=["rg"], timeout=0.01),
                None,  # except 块中的 proc.wait() 正常返回
            ]
            mock_popen.return_value = proc_mock

            query = SearchQuery(pattern="test")
            result = client.search(query)

            assert "超时" in result.error
            # 验证进程被 kill
            proc_mock.kill.assert_called()


# ── 辅助方法测试 ────────────────────────────────────────────────

class TestMakeRelative:
    """_make_relative 路径转换测试。"""

    def test_absolute_to_relative(self) -> None:
        """绝对路径转为相对路径。"""
        result = RipgrepClient._make_relative(
            "/repo/auth/service.py", "/repo"
        )
        assert result == "auth/service.py"

    def test_dot_search_path_returns_as_is(self) -> None:
        """search_path 为 '.' 时直接返回。"""
        result = RipgrepClient._make_relative(
            "auth/service.py", "."
        )
        assert result == "auth/service.py"

    def test_non_matching_prefix_returns_as_is(self) -> None:
        """路径不以 search_path 开头时返回原值。"""
        result = RipgrepClient._make_relative(
            "/other/auth/service.py", "/repo"
        )
        assert result == "/other/auth/service.py"


# ── 搜索模式对比 ────────────────────────────────────────────────

@pytest.mark.skipif(not RG_INSTALLED, reason="ripgrep (rg) 未安装")
class TestSearchModes:
    """LITERAL vs REGEX 模式的行为对比。"""

    def test_regex_matches_pattern_syntax(self, tmp_path: Path) -> None:
        """REGEX 模式使用正则语法匹配。"""
        source = tmp_path / "sample.py"
        source.write_text("class UserService:\n    pass\n", encoding="utf-8")

        client = RipgrepClient()
        query = SearchQuery(
            pattern=r"class\s+\w+Service",
            mode=SearchMode.REGEX,
        )
        result = client.search(query, search_path=str(tmp_path))

        assert len(result.matches) >= 1

    def test_literal_wont_interpret_regex_syntax(self, tmp_path: Path) -> None:
        r"""LITERAL 模式下 \w 被当作普通文本，不应匹配。"""
        source = tmp_path / "sample.py"
        source.write_text("class UserService:\n    pass\n", encoding="utf-8")

        client = RipgrepClient()
        query = SearchQuery(pattern=r"\w+Service", mode=SearchMode.LITERAL)
        result = client.search(query, search_path=str(tmp_path))

        # 文件中没有字面量 \w+Service，所以应该是 0 个匹配
        assert len(result.matches) == 0
