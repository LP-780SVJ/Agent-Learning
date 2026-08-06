"""
指令系统数据模型：表示项目规则来源、有效规则集合和冲突。

支持三种指令来源：
- AGENTS.md：嵌套的 Markdown 项目操作手册
- .clinerules：YAML Frontmatter + Markdown 条件规则
- User/System：用户显式指令和系统安全策略
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class InstructionSourceType(str, Enum):
    """指令来源类型。

    AGENTS_MD 和 CLINE_RULE 是项目级规则，
    USER 和 SYSTEM 拥有更高优先级。
    """
    AGENTS_MD = "agents_md"
    CLINE_RULE = "cline_rule"
    USER = "user"
    SYSTEM = "system"


@dataclass(frozen=True)
class InstructionSource:
    """一条指令的来源信息。

    frozen=True：来源信息是客观事实，创建后不应修改。

    字段说明：
    - path:         规则文件的仓库相对路径，如 "backend/AGENTS.md"
    - source_type:  来源类型
    - scope_path:   作用域路径，空字符串表示仓库根
    - depth:        距离仓库根的目录层级（0 = 根）
    - priority:     优先级（越高越优先，近端规则 priority 更大）
    - content:      规则文件的完整文本内容
    - content_hash: 内容的 SHA256 哈希（用于缓存失效判断）
    """
    path: str
    source_type: InstructionSourceType

    scope_path: str = ""
    depth: int = 0
    priority: int = 100

    content: str = ""
    content_hash: str = ""


@dataclass(frozen=True)
class EffectiveInstructions:
    """一个目标文件的有效规则集合。

    包含从根到目标目录的所有适用规则，
    按优先级升序排列（低 → 高）。
    """
    target_path: str
    sources: list[InstructionSource] = field(default_factory=list)

    @property
    def rendered_content(self) -> str:
        """将所有规则内容合并为一个字符串。

        高优先级规则放在后面，这样 LLM 看到的是
        「先看通用规则，再看具体规则」。
        """
        parts: list[str] = []
        for source in self.sources:
            if source.content:
                parts.append(
                    f"# Rules from {source.path}\n"
                    f"{source.content}"
                )
        return "\n\n".join(parts)


@dataclass
class InstructionConflict:
    """两条规则之间的冲突记录。

    不静默选择优胜方 —— 记录冲突后由 Lead Agent 或用户解决。
    """
    key: str
    """冲突的指令键，如 'test_command'"""

    source_a: str = ""
    """第一条规则的来源路径"""

    source_b: str = ""
    """第二条规则的来源路径"""

    detail: str = ""
    """冲突描述，如：'AGENTS.md 说 pytest，backend/AGENTS.md 说 uv run pytest'"""

    resolution: str | None = None
    """解决方式，None 表示未解决"""


@dataclass
class InstructionBundle:
    """一次任务加载的完整指令包。

    common_sources：所有目标文件都适用的公共规则（如根 AGENTS.md）
    by_target：    每个目标文件的独立规则（如 backend/AGENTS.md 只适用 api.py）
    conflicts：    检测到的规则冲突
    diagnostics：  加载过程中的警告信息（如「未找到 AGENTS.md」）
    """
    common_sources: list[InstructionSource] = field(default_factory=list)
    by_target: dict[str, EffectiveInstructions] = field(default_factory=dict)
    conflicts: list[InstructionConflict] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)