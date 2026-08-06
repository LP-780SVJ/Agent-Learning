"""
Makefile 静态目标检测器。

只用正则表达式提取目标名，不执行任何 Make 命令。
不可信仓库的 Makefile 可能包含 $(shell cat ~/.secret) 等恶意代码。
"""
from __future__ import annotations

import re
from pathlib import Path

from codeteam.commands.models import CommandKind, CommandRisk, DetectedCommand


# 目标名 → CommandKind 映射
_MAKE_TARGET_KIND: dict[str, CommandKind] = {
    "test": CommandKind.TEST,
    "check": CommandKind.TEST,
    "lint": CommandKind.LINT,
    "typecheck": CommandKind.TYPECHECK,
    "format": CommandKind.FORMAT,
    "build": CommandKind.BUILD,
    "clean": CommandKind.CLEAN,
    "install": CommandKind.INSTALL,
}

# 匹配 Makefile 目标的正则
# 目标名后跟冒号（非赋值冒号 :=）
_MAKE_TARGET_RE = re.compile(
    r"^([A-Za-z0-9_.-]+)"        # 目标名
    r"(?:\s+[A-Za-z0-9_.-]+)*"   # 可选的其他目标（多目标规则）
    r"\s*:(?!=)"                   # 冒号（排除 := 赋值）
)


def detect_from_makefile(
    repository_root: Path,
) -> list[DetectedCommand]:
    """从 Makefile 静态提取目标。

    Args:
        repository_root: 仓库根目录。

    Returns:
        list[DetectedCommand]。
    """
    makefile_path = repository_root / "Makefile"
    if not makefile_path.is_file():
        return []

    content = makefile_path.read_text(encoding="utf-8", errors="replace")
    targets = _extract_targets(content)

    commands: list[DetectedCommand] = []
    for target in sorted(targets):
        kind = _MAKE_TARGET_KIND.get(target, CommandKind.UNKNOWN)
        commands.append(
            DetectedCommand(
                command_id=f"make:{target}",
                kind=kind,
                argv=["make", target],
                cwd="",
                source_path="Makefile",
                source_type="makefile_target",
                source_detail=f"Makefile target: {target}",
                confidence=0.7,  # 静态解析，可能不完整
                risk=CommandRisk.UNKNOWN,
                requires_approval=True,
            )
        )

    return commands


def _extract_targets(content: str) -> set[str]:
    """从 Makefile 内容中静态提取目标名。

    只提取简单的静态目标，跳过：
    - 模式规则（%）
    - 特殊目标（.PHONY, .DEFAULT 等）
    - 缩进行（命令行）
    """
    targets: set[str] = set()

    for line in content.splitlines():
        if not line:
            continue
        # 跳过缩进行（命令行）
        if line[0].isspace():
            continue

        match = _MAKE_TARGET_RE.match(line)
        if not match:
            continue

        target = match.group(1)

        # 跳过模式规则和特殊目标
        if "%" in target:
            continue
        if target.startswith("."):
            continue

        targets.add(target)

    return targets