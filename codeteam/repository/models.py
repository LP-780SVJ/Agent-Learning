# Repository scanning data models will describe files, directories, project metadata, and scan results shared by the repository understanding layer.
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class FileKind(str, Enum):
    SOURCE = "source"# 源码
    TEST = "test"# 测试
    CONFIG = "config"# 配置
    BUILD = "build"# 构建
    INSTRUCTION = "instruction"# 指令
    DOCUMENTATION = "documentation"# 文档
    GENERATED = "generated"# 生成
    VENDORED = "vendored"# 第三方代码
    LOCK = "lock"# 锁文件
    DATA = "data"# 数据
    BINARY = "binary"# 二进制文件
    ASSET = "asset"# 静态资源
    UNKNOWN = "unknown"
    IGNORED = "ignored"# 忽略文件


class GitStatus(str, Enum):
    TRACKED = "tracked"
    UNTRACKED = "untracked"
    DELETED = "deleted"
    IGNORED = "ignored"
    UNKNOWN = "unknown"


class FileImportance(str, Enum):
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


@dataclass
class RepositoryFile:
    path: str
    language: str | None
    kind: FileKind
    size_bytes: int
    status: GitStatus = GitStatus.UNKNOWN
    importance: FileImportance = FileImportance.NORMAL


@dataclass
class RepositorySnapshot:
    root: Path
    files: list[RepositoryFile]
    is_git_repo: bool
    languages: dict[str, int] = field(default_factory=dict)
    important_configs: list[str] = field(default_factory=list)

    @property
    def total_files(self) -> int:
        return len(self.files)
