"""
上下文数据模型：表示被选中的文件、代码片段和最终 ContextPack。

定义了 5 级压缩降级链和上下文组装所需的所有数据结构。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CompressionLevel(str, Enum):
    """代码压缩级别，形成一条从完整到极简的降级链。

    FULL_FILE → SYMBOL_BODY → SYMBOL_SIGNATURE → FILE_SUMMARY → PATH_ONLY
    """
    FULL_FILE = "full_file"             # 完整文件内容
    SYMBOL_BODY = "symbol_body"         # 相关符号的完整实现
    SYMBOL_SIGNATURE = "symbol_signature"  # 只展示签名
    FILE_SUMMARY = "file_summary"       # 确定性摘要
    PATH_ONLY = "path_only"             # 仅文件路径


class ContextSectionType(str, Enum):
    """上下文组成部分的类型。

    每种类型在 Token Budget 中有各自的配额。
    """
    SYSTEM = "system"             # 系统安全规则（永不压缩）
    TASK = "task"                 # 用户任务描述
    INSTRUCTIONS = "instructions" # 项目规则（AGENTS.md + .clinerules）
    REPO_MAP = "repo_map"         # 仓库结构地图
    CODE = "code"                 # 具体源码
    HISTORY = "history"           # 对话历史摘要
    OBSERVATION = "observation"   # 最近工具执行结果


@dataclass(frozen=True)
class ContextItem:
    """一个被选入上下文的文件或代码片段。

    由 ContextCompressor 管理其压缩状态。
    frozen=True 的原因：压缩状态变更时创建新实例，
    而不是修改旧实例 —— 保留完整的压缩历史用于调试。
    """

    path: str                               # 文件路径（仓库相对路径）
    relevance_score: float                  # 相关性分数 [0, 1]

    current_level: CompressionLevel         # 当前压缩级别
    minimum_level: CompressionLevel         # 最低允许的压缩级别

    content: str                            # 当前级别的实际文本
    token_count: int                        # content 的 Token 估算值

    selected_symbols: list[str] = field(    # 被选中的符号名
        default_factory=list
    )
    reason: str = ""                        # 为什么这个文件被包含

    file_hash: str = ""                     # 文件内容 SHA256（检测变更）
    start_line: int | None = None           # 展示起始行（0-based）
    end_line: int | None = None             # 展示结束行（0-based）


@dataclass
class ContextSection:
    """上下文的一个组成部分。

    与 ContextItem 不同：ContextItem 是单个文件，
    ContextSection 是上下文的一大块（如整个 Repo Map）。
    """

    section_type: ContextSectionType        # 属于哪个部分
    content: str                            # 该部分的文本内容

    priority: int = 0                       # 优先级（越高越不容易被压缩）
    token_count: int = 0                    # Token 估算值

    compressible: bool = True               # 是否允许压缩
    source_paths: list[str] = field(        # 内容来源的文件路径
        default_factory=list
    )


@dataclass
class ContextPack:
    """组装完毕的上下文包，可以直接渲染为 LLM 输入。

    包含多个 ContextSection，由 ContextAssembler 组装，
    经过 ContextCompressor 压缩到预算内。
    """

    sections: list[ContextSection] = field(
        default_factory=list
    )

    estimated_tokens: int = 0               # 本地估算的总 Token
    exact_tokens: int | None = None         # 供应商精确计数（发送前最后一次校验）

    max_input_tokens: int = 0               # 输入预算上限
    compression_actions: list[str] = field( # 压缩日志
        default_factory=list
    )

    @property
    def is_within_budget(self) -> bool:
        """估算 Token 是否在预算内。"""
        return self.estimated_tokens <= self.max_input_tokens