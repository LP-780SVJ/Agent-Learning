"""
CommandDetector：命令检测主入口。

组合多个来源的命令检测，去重并标记风险。
"""
from __future__ import annotations

from pathlib import Path
import re
import shlex

from codeteam.commands.models import CommandKind, CommandRisk, DetectedCommand
from codeteam.commands.package_json import detect_from_package_json
from codeteam.commands.pytest_config import detect_from_pytest
from codeteam.commands.makefile import detect_from_makefile
from codeteam.commands.risk_classifier import classify_risk
from codeteam.instructions.models import InstructionBundle


_LABELED_COMMAND_RE = re.compile(
    r"""
    ^\s*(?:[-*]\s*)?
    (?P<label>Run\s+tests?|Tests?|Lint|Type\s+check|Typecheck|Build|Run)
    \s*:\s*
    (?P<body>.+?)
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")


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
            agents_commands = _detect_from_agents_instructions(instructions)
            if agents_commands:
                agents_kinds = {cmd.kind for cmd in agents_commands}
                commands = [
                    cmd for cmd in commands
                    if cmd.kind not in agents_kinds
                ]
                commands.extend(agents_commands)

        # 步骤 A：分类风险
        for index, cmd in enumerate(commands):
            risk, requires = classify_risk(cmd.argv)
            commands[index] = DetectedCommand(
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


def _detect_from_agents_instructions(
    instructions: InstructionBundle,
) -> list[DetectedCommand]:
    sources = []
    seen_sources: set[tuple[str, str]] = set()
    for source in instructions.common_sources:
        key = (source.path, source.content_hash)
        if key not in seen_sources:
            seen_sources.add(key)
            sources.append(source)
    for effective in instructions.by_target.values():
        for source in effective.sources:
            key = (source.path, source.content_hash)
            if key not in seen_sources:
                seen_sources.add(key)
                sources.append(source)

    commands: list[DetectedCommand] = []
    seen_commands: set[tuple[CommandKind, tuple[str, ...]]] = set()
    for source in sources:
        for line_number, command_text, kind in _extract_commands(source.content):
            argv = shlex.split(command_text)
            if not argv:
                continue
            key = (kind, tuple(argv))
            if key in seen_commands:
                continue
            seen_commands.add(key)
            commands.append(
                DetectedCommand(
                    command_id=f"agents:{kind.value}:{line_number}",
                    kind=kind,
                    argv=argv,
                    cwd="",
                    source_path=source.path,
                    source_type="explicit_instruction",
                    source_detail=f"{source.path}:{line_number}",
                    confidence=1.0,
                )
            )
    return commands


def _extract_commands(content: str) -> list[tuple[int, str, CommandKind]]:
    commands: list[tuple[int, str, CommandKind]] = []
    in_shell_block = False
    for line_number, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_shell_block:
                in_shell_block = False
                continue
            language = stripped.removeprefix("```").strip().lower()
            in_shell_block = language in {"", "bash", "sh", "shell", "zsh"}
            continue

        if in_shell_block and stripped:
            kind = _classify_command(stripped)
            if kind:
                commands.append((line_number, stripped, kind))
            continue

        labeled = _LABELED_COMMAND_RE.match(line)
        if not labeled:
            continue
        command_text = _extract_command_text(labeled.group("body"))
        kind = _classify_label(labeled.group("label")) or _classify_command(command_text)
        if kind:
            commands.append((line_number, command_text, kind))
    return commands


def _extract_command_text(text: str) -> str:
    inline = _INLINE_CODE_RE.search(text)
    if inline:
        return inline.group(1).strip()
    return text.strip().lstrip("-* ").strip()


def _classify_label(label: str) -> CommandKind | None:
    normalized = label.lower().replace(" ", "")
    if normalized in {"runtest", "runtests", "test", "tests"}:
        return CommandKind.TEST
    if normalized == "lint":
        return CommandKind.LINT
    if normalized in {"typecheck", "typechecks"}:
        return CommandKind.TYPECHECK
    if normalized == "build":
        return CommandKind.BUILD
    if normalized == "run":
        return CommandKind.RUN
    return None


def _classify_command(command_text: str) -> CommandKind | None:
    lowered = command_text.lower()
    if "pytest" in lowered:
        return CommandKind.TEST
    if "ruff" in lowered or "eslint" in lowered:
        return CommandKind.LINT
    if "mypy" in lowered or "tsc" in lowered:
        return CommandKind.TYPECHECK
    if "build" in lowered:
        return CommandKind.BUILD
    return None
