"""
codeteam.repomap.models - RepoMap 数据模型

定义 RepoMap / RepoMapFile / RepoMapSymbol / SymbolRepresentation。
Builder 产出这些结构，Renderer 把这些结构转成文本。
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class SymbolRepresentation(str, Enum):
    """符号在 Repo Map 中的表示级别。

    从最详细到最精简：
        SIGNATURE_WITH_DOC → SIGNATURE → NAME_ONLY → OMITTED
    """
    SIGNATURE_WITH_DOC = "signature_with_doc"# 展示签名和文档信息，信息最全
    SIGNATURE = "signature"# 只展示符号签名，不带文档
    NAME_ONLY = "name_only"# 只展示符号名
    OMITTED = "omitted"# 完全省略，不在 Rrpo Map 中展示


class RepoMapSymbol(BaseModel):
    """Rep Map 中的一个符号。

    注意：这不是 SymbolIndex 中的完整 Symbol，而是经过裁剪的版
    只保留渲染所需的最小信息集。
    """
    symbol_id: str                      # 全局唯一标识
    name: str                           # 简短名称
    qualified_name: str                 # 限定名
    kind: str                           # 符号种类（class/function/method等）

    signature: str | None = None        # 签名字符串
    line: int = 0                       # 定义行号

    score: float = 0.0                  # 符号得分（来自 SymbolRanker）
    representation: SymbolRepresentation = SymbolRepresentation.SIGNATURE


class RepoMapFile(BaseModel):
    """Repo Map 中的一个文件条目。"""
    path: str
    file_score: float                   # 文件排名分数
    reasons: list[str] = []             # 为什么入选（简短理由）

    symbols: list[RepoMapSymbol] = []   # 该文件展示的符号
    omitted_symbol_count: int = 0       # 该文件中被省略的符号数

    estimated_tokens: int = 0           # 该条目估算的 Token 数


class RepoMap(BaseModel):
    """完整的 Repo Map。

    包含模式（global/query）、预算信息、文件列表和省略统计。
    """
    mode: str                           # "global" 或 "query"
    query: str | None = None            # 原始查询（global 模式为 None）

    budget_tokens: int                  # 预算上限
    used_tokens: int = 0                # 实际使用的 Token 数

    files: list[RepoMapFile] = []       # 按文件排名排序的文件

    omitted_file_count: int = 0         # 因超预算跳过的文件数
    truncated: bool = False             # 是否有文件被截断