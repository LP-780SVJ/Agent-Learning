"""
Glob 模式匹配工具。

用于 Cline 条件规则的路径匹配，
如 paths: ["frontend/**"] 匹配路径 "frontend/src/App.tsx"。
"""
from __future__ import annotations

from pathlib import PurePosixPath


def glob_matches(pattern: str, path: str) -> bool:
    """检查 path 是否匹配 glob pattern。

    支持：
    - **  匹配任意层级的目录
    - *   匹配单层目录内的任意字符（不含 /）
    - ?   匹配单个字符（不含 /）

    Args:
        pattern: glob 模式，如 "frontend/**"、"src/**/*.tsx"
        path:    待检查的路径，如 "frontend/src/App.tsx"

    Returns:
        True 如果匹配。

    Examples:
        >>> glob_matches("frontend/**", "frontend/src/App.tsx")
        True
        >>> glob_matches("backend/**", "frontend/src/App.tsx")
        False
        >>> glob_matches("*.py", "main.py")
        True
    """
    # 统一使用 POSIX 风格路径（/ 分隔），避免 Windows 反斜杠问题
    posix_path = path.replace("\\", "/")
    return PurePosixPath(posix_path).match(pattern)