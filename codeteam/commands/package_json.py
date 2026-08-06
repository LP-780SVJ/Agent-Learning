"""
package.json 命令检测器。

从 package.json 的 scripts 字段提取测试、检查、构建命令，
并自动识别包管理器（npm / pnpm / yarn）。
"""
from __future__ import annotations

import json
from pathlib import Path

from codeteam.commands.models import CommandKind, CommandRisk, DetectedCommand


# script 名 → CommandKind 映射
_SCRIPT_KIND_MAP: dict[str, CommandKind] = {
    "test": CommandKind.TEST,
    "test:unit": CommandKind.TEST,
    "test:integration": CommandKind.TEST,
    "test:e2e": CommandKind.TEST,
    "lint": CommandKind.LINT,
    "lint:fix": CommandKind.LINT,
    "typecheck": CommandKind.TYPECHECK,
    "type-check": CommandKind.TYPECHECK,
    "format": CommandKind.FORMAT,
    "format:check": CommandKind.FORMAT,
    "build": CommandKind.BUILD,
    "start": CommandKind.RUN,
    "dev": CommandKind.RUN,
    "clean": CommandKind.CLEAN,
}


def detect_from_package_json(
    repository_root: Path,
) -> list[DetectedCommand]:
    """从仓库根目录的 package.json 检测命令。

    Args:
        repository_root: 仓库根目录。

    Returns:
        list[DetectedCommand]，可能为空。
    """
    package_path = repository_root / "package.json"
    if not package_path.is_file():
        return []

    # 读取 package.json
    try:
        data = json.loads(package_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    scripts: dict[str, str] = data.get("scripts", {})
    if not isinstance(scripts, dict):
        return []

    # 识别包管理器
    pm, _ = _detect_package_manager(repository_root)

    # 构建命令
    commands: list[DetectedCommand] = []
    for script_name, script_body in scripts.items():
        kind = _SCRIPT_KIND_MAP.get(script_name, CommandKind.UNKNOWN)

        # 构建 npm run <name> 命令
        argv = [pm, "run", script_name]

        # 生命周期链
        lifecycle = _build_lifecycle(script_name, scripts)

        source_detail = f'"{script_name}": "{script_body}"'

        commands.append(
            DetectedCommand(
                command_id=f"npm:{script_name}",
                kind=kind,
                argv=argv,
                cwd="",
                source_path="package.json",
                source_type="package_script",
                source_detail=source_detail,
                confidence=1.0,
                risk=CommandRisk.UNKNOWN,
                requires_approval=True,
                underlying_script=script_body,
                lifecycle_chain=lifecycle,
            )
        )

    return commands

def _detect_package_manager(root: Path) -> tuple[str, float]:
    """根据锁文件识别包管理器。

    Returns:
        (包管理器名称, 置信度)
    """
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm", 1.0
    if (root / "yarn.lock").exists():
        return "yarn", 1.0
    if (root / "package-lock.json").exists():
        return "npm", 1.0
    # 有 package.json 但没有锁文件 → 猜测 npm
    return "npm", 0.6


def _build_lifecycle(
    script_name: str, scripts: dict[str, str]
) -> list[str]:
    """构建 npm 生命周期链。

    npm 会自动运行 pre<script> 和 post<script>。
    例如 "test" → ["pretest", "test", "posttest"]
    """
    chain: list[str] = []
    pre = f"pre{script_name}"
    post = f"post{script_name}"
    if pre in scripts:
        chain.append(pre)
    chain.append(script_name)
    if post in scripts:
        chain.append(post)
    return chain