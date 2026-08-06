"""
命令检测数据模型：表示从仓库配置中检测到的命令。

命令来源包括 AGENTS.md 显式命令、package.json scripts、
pytest 配置和 Makefile 目标。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CommandKind(str, Enum):
    """命令的种类。"""
    INSTALL = "install"        # 依赖安装
    TEST = "test"              # 测试
    LINT = "lint"              # 代码检查
    TYPECHECK = "typecheck"    # 类型检查
    FORMAT = "format"          # 代码格式化
    BUILD = "build"            # 构建
    RUN = "run"                # 运行
    CLEAN = "clean"            # 清理
    MIGRATION = "migration"    # 数据库迁移
    UNKNOWN = "unknown"        # 未知类型


class CommandRisk(str, Enum):
    """命令的风险等级。

    用于决定是否需要用户审批。
    """
    READ_ONLY = "read_only"              # 只读（如 pytest --collect-only）
    WORKSPACE_WRITE = "workspace_write"   # 写工作区（如 ruff format）
    NETWORK = "network"                   # 网络访问（如 pip install）
    DESTRUCTIVE = "destructive"           # 破坏性（如 rm -rf）
    SECRET_ACCESS = "secret_access"       # 访问凭证（如读取 ~/.aws）
    UNKNOWN = "unknown"                   # 无法判断


@dataclass(frozen=True)
class DetectedCommand:
    """一条检测到的命令。

    frozen=True：检测结果是事实，不应被修改。
    如需调整（如修改 argv），创建新实例。

    字段说明：
    - command_id:       唯一标识（如 "test:backend"）
    - kind:             命令种类
    - argv:             命令行参数列表（如 ["pytest", "tests/", "-q"]）
    - cwd:              运行目录（相对于仓库根）
    - source_path:      命令来源文件（如 "AGENTS.md"）
    - source_type:      来源类型（如 "explicit_instruction"）
    - source_detail:    来源的详细描述
    - confidence:       置信度 [0, 1]。显式命令 = 1.0，推断 = 0.6
    - risk:             风险等级
    - requires_approval:是否需要用户审批
    - underlying_script: 实际执行的脚本（如 npm script 中的 "vitest run"）
    - lifecycle_chain:  生命周期链（如 ["pretest", "test", "posttest"]）
    """

    command_id: str
    kind: CommandKind

    argv: list[str] = field(default_factory=list)
    cwd: str = ""

    source_path: str = ""
    source_type: str = ""
    source_detail: str = ""

    confidence: float = 1.0

    risk: CommandRisk = CommandRisk.UNKNOWN
    requires_approval: bool = True  # 默认需要审批（安全优先）

    underlying_script: str | None = None
    lifecycle_chain: list[str] = field(default_factory=list)