"""
AgentsMdLoader：发现嵌套 AGENTS.md 并计算作用域链。

沿目标文件的目录层级向上查找 AGENTS.md，
按根→近端顺序返回，近端规则拥有更高优先级。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from codeteam.instructions.models import InstructionSource, InstructionSourceType


class AgentsMdLoader:
    """AGENTS.md 发现器。

    对每个目标文件，从它所在目录向上走到仓库根，
    检查每一级是否存在 AGENTS.md。

    用法：
        loader = AgentsMdLoader()
        sources = loader.discover_for_target(
            repository_root=Path("/repo"),
            target_path="backend/src/auth/service.py",
        )
        # → [root_AGENTS.md, backend/AGENTS.md]
    """

    def discover_for_target(
        self,
        *,
        repository_root: Path,
        target_path: str,
    ) -> list[InstructionSource]:
        """为目标文件发现所有适用的 AGENTS.md。

        Args:
            repository_root: 仓库根目录（绝对路径）。
            target_path:     目标文件的仓库相对路径。

        Returns:
            list[InstructionSource]，按根→近端排序。

        Raises:
            ValueError: target_path 是绝对路径。
            PermissionError: 目标路径解析后逃逸出仓库。
        """
        root = repository_root.resolve(strict=False)

        # 步骤 1：校验 target_path 必须是相对路径
        relative = Path(target_path)
        if relative.is_absolute():
            raise ValueError(
                f"target_path 必须是仓库相对路径，"
                f"不能是绝对路径: {target_path!r}"
            )

        # 步骤 2：解析为绝对路径
        absolute = (root / relative).resolve(strict=False)

        # 步骤 3：安全检查 —— 防止 ../../etc/passwd 路径逃逸
        if not self._is_inside(absolute, root):
            raise PermissionError(
                f"目标路径逃逸出仓库: {target_path!r}"
                f" → {absolute}"
            )

        # 步骤 4：从目标目录向上收集所有目录
        current = absolute if absolute.is_dir() else absolute.parent
        directories: list[Path] = []
        while True:
            directories.append(current)
            if current == root:
                break
            current = current.parent

        # 步骤 5：反转（根→近端），检查每个目录
        directories.reverse()
        sources: list[InstructionSource] = []

        for depth, directory in enumerate(directories):
            agents_file = directory / "AGENTS.md"
            if not agents_file.is_file():
                continue

            # 读取文件内容
            content = agents_file.read_text(
                encoding="utf-8",
                errors="replace",  # 非 UTF-8 字符用 � 替代，不崩溃
            )

            # 计算相对路径和作用域
            relative_path = agents_file.relative_to(root).as_posix()
            scope = directory.relative_to(root).as_posix()
            if scope == ".":
                scope = ""

            sources.append(
                InstructionSource(
                    path=relative_path,
                    source_type=InstructionSourceType.AGENTS_MD,
                    scope_path=scope,
                    depth=depth,
                    priority=100 + depth,  # 越近优先级越高
                    content=content,
                    content_hash=hashlib.sha256(
                        content.encode("utf-8")
                    ).hexdigest(),
                )
            )

        return sources

    @staticmethod
    def _is_inside(path: Path, parent: Path) -> bool:
        """检查 path 是否在 parent 目录内。

        使用 Path.is_relative_to（Python 3.9+）。
        """
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False