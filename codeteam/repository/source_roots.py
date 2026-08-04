"""
SourceRoot: 定义 Python 源码根目录。

Resolver 用它确定从哪里开始查找模块。
在简单项目中通常只有一个 "."，在 monorepo 中可能有多个。
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceRoot:
    """一个 Python 源码根目录。

    Attributes:
        path: 相对于项目根目录的路径，如 "src"、"lib" 或 "."
        is_package: 该目录本身是否是 Python 包（包含 __init__.py）
    """
    path: str
    is_package: bool = False