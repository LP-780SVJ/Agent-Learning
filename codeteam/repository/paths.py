"""
仓库路径规范化工具。

系统内部统一路径格式：
  - POSIX 风格（正斜杠 /）
  - 相对于 Git 仓库根目录
  - 不以 ./ 开头
  - 不以 / 开头

示例：
  normalize_repo_path(Path("/repo"), Path("/repo/src/auth/service.py"))
  → "src/auth/service.py"
"""
from __future__ import annotations

from pathlib import Path


def normalize_repo_path(
    repository_root: Path,
    target: Path | str,
) -> str:
    """将任意路径规范化为仓库相对路径。

    处理以下输入格式：
        /absolute/path/to/repo/src/auth/service.py → src/auth/service.py
        ./src/auth/service.py                       → src/auth/service.py
        src/auth/service.py                         → src/auth/service.py
        src\\auth\\service.py                       → src/auth/service.py

    Args:
        repository_root: Git 仓库根目录（绝对路径）
        target: 待规范化的路径

    Returns:
        POSIX 风格、不以 ./ 或 / 开头的相对路径

    Raises:
        ValueError: target 不在 repository_root 下（防止路径逃逸）
    """
    root = Path(repository_root).resolve()
    target_path = Path(target)

    # 如果是相对路径，拼到 root 下再 resolve
    if not target_path.is_absolute():
        target_path = (root / target_path).resolve()
    else:
        target_path = target_path.resolve()

    # 安全检查：目标必须在仓库根目录下
    try:
        relative = target_path.relative_to(root)
    except ValueError:
        raise ValueError(
            f"路径 '{target}' 不在仓库根目录 '{root}' 下"
        )

    # 转 POSIX 格式（正斜杠）
    return relative.as_posix()