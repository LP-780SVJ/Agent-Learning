"""
CommandDetector：命令检测主入口。

组合多个来源的命令检测，去重并标记风险。
"""
from __future__ import annotations

from pathlib import Path

from codeteam.commands.models import CommandKind, CommandRisk, DetectedCommand
from codeteam.commands.package_json import detect_from_package_json
from codeteam.commands.pytest_config import detect_from_pytest
from codeteam.commands.makefile import detect_from_makefile
from codeteam.commands.risk_classifier import classify_risk
from codeteam.instructions.models import InstructionBundle


class CommandDetector:
    """仓库命令检测器。

    检测项目的测试、检查、构建命令，
    并标记每条命令的风险等级。

    用法：
        detector = CommandDetector()
        commands = detector.detect(
            repository_root=Path("/repo"),
            instructions=instruction_bundle,
        )
    """

    def detect(
        self,
        *,
        repository_root: Path,
        instructions: InstructionBundle | None = None,
    ) -> list[DetectedCommand]:
        """检测仓库中所有可用的命令。

        Args:
            repository_root: 仓库根目录。
            instructions:    可选的 InstructionBundle，
                             用于提取 AGENTS.md 中的显式命令。

        Returns:
            list[DetectedCommand]，已去重并按 Kind 排序。
        """
        commands: list[DetectedCommand] = []

        # 来源 1：package.json（优先级最低，先加）
        commands.extend(
            detect_from_package_json(repository_root)
        )

        # 来源 2：pytest 配置
        pytest_cmd = detect_from_pytest(repository_root)
        if pytest_cmd:
            commands.append(pytest_cmd)

        # 来源 3：Makefile 目标
        commands.extend(
            detect_from_makefile(repository_root)
        )

        # 来源 4：AGENTS.md 显式命令（优先级最高，最后加）
        if instructions is not None:
            # 如果有 instructions，其中的命令会覆盖自动检测的同名命令
            # 第一版暂不实现自动提取（留作扩展点）
            pass

        # 步骤 A：分类风险
        for cmd in commands:
            risk, requires = classify_risk(cmd.argv)
            cmd = DetectedCommand(
                command_id=cmd.command_id,
                kind=cmd.kind,
                argv=cmd.argv,
                cwd=cmd.cwd,
                source_path=cmd.source_path,
                source_type=cmd.source_type,
                source_detail=cmd.source_detail,
                confidence=cmd.confidence,
                risk=risk,
                requires_approval=requires,
                underlying_script=cmd.underlying_script,
                lifecycle_chain=cmd.lifecycle_chain,
            )
            # 替换列表中原有的 cmd
            commands[commands.index(cmd)] = cmd

        # 步骤 B：去重（同 kind + 同 argv 只保留 confidence 最高的）
        commands = _deduplicate(commands)

        # 步骤 C：按 kind 排序
        _KIND_ORDER = {
            CommandKind.TEST: 0,
            CommandKind.LINT: 1,
            CommandKind.TYPECHECK: 2,
            CommandKind.FORMAT: 3,
            CommandKind.BUILD: 4,
            CommandKind.RUN: 5,
            CommandKind.INSTALL: 6,
            CommandKind.CLEAN: 7,
            CommandKind.UNKNOWN: 99,
        }
        commands.sort(key=lambda c: (_KIND_ORDER.get(c.kind, 99), c.command_id))

        return commands


def _deduplicate(
    commands: list[DetectedCommand],
) -> list[DetectedCommand]:
    """按 (kind, tuple(argv)) 去重，保留置信度最高的。"""
    seen: dict[tuple, DetectedCommand] = {}

    for cmd in commands:
        key = (cmd.kind, tuple(cmd.argv))
        if key not in seen or cmd.confidence > seen[key].confidence:
            seen[key] = cmd

    return list(seen.values())