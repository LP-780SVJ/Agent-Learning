'''
定义 ImportRecord、ImportEdge 等数据结构

  - ImportKind — 枚举：import os / from X import Y / 动态 import
  - ResolveStatus — 枚举：解析成功 / 外部模块 / 无法解析
  - ImportRecord — 一条 import 语句的原始记录 
  - ImportResolution — 解析后的结果
  - ImportEdge — Import Graph 中的一条边（A 依赖 B）
'''

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class ImportKind(str, Enum):
    """Import 语句的种类。

    IMPORT:      import os  /  import os.path as osp
    IMPORT_FROM: from os.path import join  /  from .repo import UserRepo as Repo
    DYNAMIC:     动态 import，如 __import__("os") 或 importlib.import_module("x")
    """
    IMPORT = "import"
    IMPORT_FROM = "import_from"
    DYNAMIC = "dynamic"


class ResolveStatus(str, Enum):
    """Import 解析的结果状态。

    RESOLVED:   成功解析到仓库内的具体文件
    EXTERNAL:   外部模块（如 os, requests），不在本仓库内
    UNRESOLVED: 无法解析（路径无效、模块不存在等）
    """
    RESOLVED = "resolved"
    EXTERNAL = "external"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class ImportRecord:
    """一条 import 语句的原始记录。

    frozen=True 的原因和 Symbol 一样：import 语句是源代码中的客观事实。

    示例映射：
    from .repository import UserRepository as Repository
    → ImportRecord(
        source_file="auth/service.py",
        module=".repository",
        name="UserRepository",
        alias="Repository",
        level=1,
        kind=ImportKind.IMPORT_FROM,
    )
    """
    source_file: str             # 发起 import 的文件，如 "auth/service.py"
    module: str                  # 模块路径，如 "os.path"、".repository"、"auth.models"
    name: str                    # 导入的名字，如 "UserRepository"、"join"
    alias: str | None = None     # 别名（as 后面的名字），没有别名则为 None
    level: int = 0               # 相对层级：0=绝对导入，1=当前包，2=父包...
    kind: ImportKind = ImportKind.IMPORT_FROM
    line: int = 0
    column: int = 0


@dataclass(frozen=True)
class ImportResolution:
    """一条 import 解析后的结果。

    把 ImportRecord（语法层）解析成具体的文件路径。

    示例：
    ImportRecord(module=".repository", level=1, source_file="auth/service.py")
    → ImportResolution(
        record=...,
        status=RESOLVED,
        resolved_file="auth/repository.py",
    )
    """
    record: ImportRecord
    status: ResolveStatus
    resolved_file: str | None = None   # 解析后的目标文件路径
    reason: str = ""                    # 无法解析时的原因说明（如 "模块 'os' 是外部模块"）


@dataclass(frozen=True)
class ImportEdge:
    """Import Graph 中的一条有向边。

    方向：source_file → target_file
    含义：source_file 依赖 target_file

    例：auth/service.py import 了 auth/repository.py
    → ImportEdge(
        source_file="auth/service.py",
        target_file="auth/repository.py",
    )
    """
    source_file: str    # 发起 import 的文件（依赖者）
    target_file: str    # 被 import 的文件（被依赖者）
    import_line: int = 0
    module_path: str = ""