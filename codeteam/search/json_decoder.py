"""
JSON 解码器：解析 ripgrep --json 的 JSONL 输出。

ripgrep --json 每行输出一个 JSON 对象，包含 type 和 data 字段。
type 有 5 种：begin、match、context、end、summary。

提供纯函数，不持有状态。状态管理由 RipgrepClient 负责。
"""
from __future__ import annotations

import base64
import json

from codeteam.search.models import SearchSubmatch


def extract_path(path_obj: dict) -> str:
    """从 ripgrep JSON 的 path 对象中提取文件路径字符串。

    ripgrep 的 path 有两种格式：
        {"text": "/normal/path.py"}          — 正常 UTF-8 路径
        {"bytes": "L2Jyb2tlbi9wYXRoLnB5"}    — 非 UTF-8 路径（base64 编码）

    Args:
        path_obj: ripgrep JSON 中的 data.path 对象

    Returns:
        文件路径字符串。非 UTF-8 路径会尝试用 base64 解码，
        解码失败或格式未知时返回 "<unknown>"。
    """
    if "text" in path_obj:
        return path_obj["text"]

    if "bytes" in path_obj:
        try:
            decoded_bytes = base64.b64decode(path_obj["bytes"])
            return decoded_bytes.decode("utf-8", errors="replace")
        except Exception:
            return "<unknown>"

    return "<unknown>"


def parse_submatches(submatches: list[dict]) -> list[SearchSubmatch]:
    """解析 ripgrep 的 submatches 列表。

    每个 submatch 的结构：
        {
            "match": {"text": "get_user"},
            "start": 8,    # 在 lines.text 中的字节偏移（起始）
            "end": 16      # 在 lines.text 中的字节偏移（结束）
        }

    注意：start/end 是字节偏移，不是字符偏移。

    Args:
        submatches: ripgrep JSON 中 data.submatches 列表

    Returns:
        SearchSubmatch 对象列表
    """
    result: list[SearchSubmatch] = []
    for sm in submatches:
        result.append(
            SearchSubmatch(
                start=sm["start"],
                end=sm["end"],
                text=sm["match"]["text"],
            )
        )
    return result


def parse_ripgrep_line(line: str) -> tuple[str, dict] | tuple[None, None]:
    """解析一行 ripgrep --json 的 JSONL 输出。

    Args:
        line: 一行 JSON 字符串（可能为空行）

    Returns:
        (message_type, data_dict) — 正常解析
        (None, None) — 空行或解析失败

        message_type 是以下之一：
            "begin"   — 开始搜索一个文件
            "match"   — 一个匹配行
            "context" — 上下文行（匹配行前后）
            "end"     — 结束搜索一个文件
            "summary" — 全局搜索汇总

    Usage:
        msg_type, data = parse_ripgrep_line(line)
        if msg_type == "match":
            path = extract_path(data["path"])
            line_text = data["lines"]["text"].rstrip('\n')
            submatches = parse_submatches(data["submatches"])
    """
    line = line.strip()
    if not line:
        return None, None

    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None, None

    msg_type = obj.get("type", "")
    data = obj.get("data", {})

    return msg_type, data