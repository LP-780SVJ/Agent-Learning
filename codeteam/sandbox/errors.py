from __future__ import annotations


class SandboxError(Exception):
    """Sandbox 相关错误的基类。"""


class SandboxMountError(SandboxError):
    """Mount 配置不安全或不合法。"""


class SandboxRuntimeError(SandboxError):
    """Sandbox 执行失败。"""


class DockerUnavailableError(SandboxRuntimeError):
    """Docker CLI 或 Docker daemon 不可用。"""