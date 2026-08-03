# Parser base interfaces will define the common contract for language parsers that produce symbols, imports, references, and parse errors.
'''
codeteam.parsing.base - 定义 CodeParser 抽象接口（Protocol）

模块职责：
- CodeParser Protocol 是所有语言解析器必须遵守的接口规范，确保解析器能够输出统一的数据模型（ParseResult）。
- 不提供任何具体实现，只规定方法签名
- 使用Protocol（而非 ABC）实现结构化鸭子类型：
    任何类只要拥有 parse() 方法和 name 属性，就能被当作 CodeParser 使用，无需显式继承。
'''

from __future__ import annotations
from typing import Protocol, runtime_checkable

from codeteam.parsing.models import ParseResult


@runtime_checkable
class CodeParser(Protocol):
    @property
    def name(self) -> str:
        """解析器名称"""
        ...

    def parse(self, source_code: str, file_path: str) -> ParseResult:
        """解析源代码，返回统一的解析结果"""
        ...