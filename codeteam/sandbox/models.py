from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class SandboxProfile(BaseModel):
    """描述安全意图
    
    字段说明：
    - image: 运行沙箱的容器镜像
    - network_enabled: 是否允许网络访问
    - read_only_root: 是否将根文件系统设置为只读
    - drop_all_capabilities: 是否丢弃所有的 Linux 能力
    - no_new_privileges: 是否防止容器内进程获得新权限
    - memory_mb: 分配给沙箱的内存大小（以 MB 为单位）
    - cpus: 分配给沙箱的 CPU 核数
    - pids_limit: 沙箱内允许的最大进程数
    - workspace_write: 是否允许写入工作目录
    - pull_policy: 镜像拉取策略（"always", "never", "if_not_present"）
    """
    image: str = "codeteam-sandbox:latest"

    network_enabled: bool = False
    read_only_root: bool = True
    drop_all_capabilities: bool = True
    no_new_privileges: bool = True

    memory_mb: int = Field(default=512, gt=0)
    cpus: float = Field(default=1.0, gt=0)
    pids_limit: int = Field(default=256, gt=0)

    workspace_write: bool = True
    pull_policy: str = "never"


class SandboxExecutionContext(BaseModel):
    """描述一次沙箱执行的具体上下文。

    字段说明：
    - argv: 要在容器里执行的命令参数
    - workspace_root: Host 上的任务工作目录
    - cwd: Host 上本次命令的工作目录
    - profile: 本次执行使用的沙箱配置
    - container_workspace: 容器内 workspace 挂载位置
    """

    argv: tuple[str, ...] = Field(min_length=1)

    workspace_root: Path
    cwd: Path

    profile: SandboxProfile = Field(default_factory=SandboxProfile)

    container_workspace: Path = Path("/workspace")

    @model_validator(mode="after")
    def validate_paths(self) -> SandboxExecutionContext:
        workspace_root = self.workspace_root.expanduser().resolve(strict=False)
        cwd = self.cwd.expanduser().resolve(strict=False)

        if not _is_relative_to(cwd, workspace_root):
            raise ValueError("cwd must be inside workspace_root.")

        return self

    @property
    def container_cwd(self) -> Path:
        relative_cwd = self.cwd.resolve(strict=False).relative_to(
            self.workspace_root.resolve(strict=False)
        )
        return self.container_workspace / relative_cwd


# ----HELPER FUNCTIONS-----------------------------------------------------------
def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True