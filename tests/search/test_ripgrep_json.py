"""Tests for codeteam.search.json_decoder — ripgrep JSONL 解析。

覆盖五种消息类型（begin/match/context/end/summary）、
bytes/text 路径、submatch 解析、边界和异常输入。
"""

from __future__ import annotations

import base64
import json

import pytest

from codeteam.search.json_decoder import (
    extract_path,
    parse_ripgrep_line,
    parse_submatches,
)
from codeteam.search.models import SearchSubmatch


# ── parse_ripgrep_line ──────────────────────────────────────────

class TestParseRipgrepLine:
    """parse_ripgrep_line 的消息类型解析测试。"""

    def test_parses_begin_message(self) -> None:
        """begin 消息——开始搜索一个文件。"""
        line = json.dumps({
            "type": "begin",
            "data": {
                "path": {"text": "auth/service.py"},
            },
        })
        msg_type, data = parse_ripgrep_line(line)
        assert msg_type == "begin"
        assert data["path"]["text"] == "auth/service.py"

    def test_parses_match_message(self) -> None:
        """match 消息——找到一个匹配行。"""
        line = json.dumps({
            "type": "match",
            "data": {
                "path": {"text": "auth/service.py"},
                "lines": {"text": "class UserService:\n"},
                "line_number": 3,
                "absolute_offset": 40,
                "submatches": [
                    {
                        "match": {"text": "UserService"},
                        "start": 6,
                        "end": 17,
                    },
                ],
            },
        })
        msg_type, data = parse_ripgrep_line(line)
        assert msg_type == "match"
        assert data["line_number"] == 3
        assert data["submatches"][0]["match"]["text"] == "UserService"

    def test_parses_context_message(self) -> None:
        """context 消息——匹配行前后的一行上下文。"""
        line = json.dumps({
            "type": "context",
            "data": {
                "path": {"text": "auth/service.py"},
                "lines": {"text": "    def get_user(self):\n"},
                "line_number": 4,
            },
        })
        msg_type, data = parse_ripgrep_line(line)
        assert msg_type == "context"
        assert data["line_number"] == 4

    def test_parses_end_message(self) -> None:
        """end 消息——一个文件的搜索结束。"""
        line = json.dumps({
            "type": "end",
            "data": {
                "path": {"text": "auth/service.py"},
                "stats": {"elapsed": {"secs": 0, "nanos": 500000}},
            },
        })
        msg_type, data = parse_ripgrep_line(line)
        assert msg_type == "end"

    def test_parses_summary_message(self) -> None:
        """summary 消息——全局统计汇总。"""
        line = json.dumps({
            "type": "summary",
            "data": {
                "elapsed_total": {"secs": 0, "nanos": 1200000},
                "stats": {"matches": 5, "searches": 3},
            },
        })
        msg_type, data = parse_ripgrep_line(line)
        assert msg_type == "summary"
        assert data["stats"]["matches"] == 5

    def test_returns_none_for_empty_line(self) -> None:
        """空行返回 (None, None)。"""
        msg_type, data = parse_ripgrep_line("")
        assert msg_type is None
        assert data is None

    def test_returns_none_for_whitespace_only_line(self) -> None:
        """全是空白字符的行返回 (None, None)。"""
        msg_type, data = parse_ripgrep_line("   \n")
        assert msg_type is None
        assert data is None

    def test_returns_none_for_invalid_json(self) -> None:
        """非法 JSON 返回 (None, None)，不抛异常。"""
        msg_type, data = parse_ripgrep_line("not valid json {{{")
        assert msg_type is None
        assert data is None

    def test_handles_missing_type_field(self) -> None:
        """type 字段缺失时返回空字符串。"""
        line = json.dumps({"data": {}})
        msg_type, data = parse_ripgrep_line(line)
        assert msg_type == ""
        assert data == {}

    def test_handles_missing_data_field(self) -> None:
        """data 字段缺失时返回空字典。"""
        line = json.dumps({"type": "match"})
        msg_type, data = parse_ripgrep_line(line)
        assert msg_type == "match"
        assert data == {}


# ── extract_path ────────────────────────────────────────────────

class TestExtractPath:
    """extract_path —— ripgrep 的 path 对象 → 字符串。"""

    def test_extracts_text_path(self) -> None:
        """普通 UTF-8 文本路径。"""
        path = extract_path({"text": "auth/service.py"})
        assert path == "auth/service.py"

    def test_extracts_bytes_path(self) -> None:
        """base64 编码的 bytes 路径（非 UTF-8 文件名）。"""
        raw = "/broken/path.py".encode("utf-8")
        encoded = base64.b64encode(raw).decode("ascii")
        path = extract_path({"bytes": encoded})
        assert path == "/broken/path.py"

    def test_bytes_path_with_non_utf8_uses_replace(self) -> None:
        """非 UTF-8 bytes 路径——用 replacement character 替换。"""
        raw = b"/broken/\xff\xfe.py"
        encoded = base64.b64encode(raw).decode("ascii")
        path = extract_path({"bytes": encoded})
        assert "broken" in path
        assert ".py" in path

    def test_bytes_path_decode_failure_returns_unknown(self) -> None:
        """base64 解码失败时返回 '<unknown>'。"""
        path = extract_path({"bytes": "!!!not-valid-base64!!!"})
        assert path == "<unknown>"

    def test_unknown_path_format_returns_unknown(self) -> None:
        """既没有 text 也没有 bytes 时返回 '<unknown>'。"""
        path = extract_path({})
        assert path == "<unknown>"

    def test_prefers_text_over_bytes(self) -> None:
        """同时包含 text 和 bytes 时优先使用 text。"""
        path = extract_path({
            "text": "real_path.py",
            "bytes": base64.b64encode(b"fake.py").decode("ascii"),
        })
        assert path == "real_path.py"


# ── parse_submatches ────────────────────────────────────────────

class TestParseSubmatches:
    """parse_submatches —— submatch 数组 → SearchSubmatch 列表。"""

    def test_parses_single_submatch(self) -> None:
        """单个捕获组。"""
        result = parse_submatches([
            {"match": {"text": "get_user"}, "start": 8, "end": 16},
        ])
        assert len(result) == 1
        assert isinstance(result[0], SearchSubmatch)
        assert result[0].text == "get_user"
        assert result[0].start == 8
        assert result[0].end == 16

    def test_parses_multiple_submatches(self) -> None:
        """多个捕获组。"""
        raw = [
            {"match": {"text": "self"}, "start": 4, "end": 8},
            {"match": {"text": "repository"}, "start": 9, "end": 19},
        ]
        result = parse_submatches(raw)
        assert len(result) == 2
        assert result[0].text == "self"
        assert result[1].text == "repository"

    def test_returns_empty_list_for_empty_input(self) -> None:
        """空列表 → 空列表。"""
        result = parse_submatches([])
        assert result == []

    def test_preserves_byte_offsets(self) -> None:
        """start/end 字节偏移正确保留。"""
        result = parse_submatches([
            {"match": {"text": "🐍"}, "start": 0, "end": 4},
        ])
        assert result[0].start == 0
        assert result[0].end == 4


# ── 集成测试：消息序列 ──────────────────────────────────────────

class TestMessageSequence:
    """模拟 ripgrep 完整输出流程。"""

    def test_begin_match_end_summary_sequence(self) -> None:
        """完整的 begin → match → end → summary 流程。"""
        lines = [
            json.dumps({
                "type": "begin",
                "data": {"path": {"text": "x.py"}},
            }),
            json.dumps({
                "type": "match",
                "data": {
                    "path": {"text": "x.py"},
                    "lines": {"text": "hello\n"},
                    "line_number": 1,
                    "submatches": [],
                },
            }),
            json.dumps({
                "type": "end",
                "data": {"path": {"text": "x.py"}},
            }),
            json.dumps({
                "type": "summary",
                "data": {
                    "elapsed_total": {"secs": 0, "nanos": 500000},
                    "stats": {"matches": 1},
                },
            }),
        ]

        types = []
        for line in lines:
            msg_type, _data = parse_ripgrep_line(line)
            types.append(msg_type)

        assert types == ["begin", "match", "end", "summary"]
