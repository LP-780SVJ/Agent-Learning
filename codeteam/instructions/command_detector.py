"""
CommandDetector: 从仓库配置文件推断测试、lint、构建命令。

检测来源：
- pyproject.toml → pytest/ruff/mypy 配置
- AGENTS.md     → 显式声明的命令
- Makefile      → test/lint 等 target
- package.json  → scripts
"""
from __future__ import annotations

from pathlib import Path
import re

from pydantic import BaseModel


class DetectedCommand(BaseModel):
    """一条检测到的命令。"""
    category: str          # "test" / "lint" / "typecheck" / "build" / "run"
    command: str           # 实际可执行的命令
    source: str            # 来源文件名
    description: str = ""  # 人类可读描述


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
    """命令检测器。

    用法：
        detector = CommandDetector()
        commands = detector.detect(repository_root=Path("/repo"))
    """

    def detect(
        self,
        *,
        repository_root: Path,
    ) -> list[DetectedCommand]:
        commands: list[DetectedCommand] = []

        # 按优先级检测各个配置文件
        self._from_pyproject(repository_root, commands)
        self._from_makefile(repository_root, commands)
        self._from_agents_md(repository_root, commands)
        self._from_package_json(repository_root, commands)

        return commands

    # ── 各配置文件检测 ──────────────────────────────────

    def _from_pyproject(
        self, root: Path, commands: list[DetectedCommand]
    ) -> None:
        pyproject = root / "pyproject.toml"
        if not pyproject.exists():
            return

        content = pyproject.read_text(encoding="utf-8")

        # 检测 pytest
        if "pytest" in content or "[tool.pytest" in content:
            commands.append(DetectedCommand(
                category="test",
                command="pytest",
                source="pyproject.toml",
                description="Python 测试运行器",
            ))

        # 检测 ruff
        if "ruff" in content:
            commands.append(DetectedCommand(
                category="lint",
                command="ruff check .",
                source="pyproject.toml",
                description="Ruff 代码检查",
            ))

        # 检测 mypy
        if "mypy" in content:
            commands.append(DetectedCommand(
                category="typecheck",
                command="mypy src",
                source="pyproject.toml",
                description="Mypy 类型检查",
            ))

    def _from_makefile(
        self, root: Path, commands: list[DetectedCommand]
    ) -> None:
        makefile = root / "Makefile"
        if not makefile.exists():
            return

        content = makefile.read_text(encoding="utf-8")

        # 解析 target 名
        for line in content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # 匹配 "target:" 格式
            if ":" in line and not line.startswith("\t"):
                target = line.split(":")[0].strip()
                if target.startswith("."):
                    continue  # 跳过 .PHONY 等特殊 target

                category = self._classify_target(target)
                if category:
                    commands.append(DetectedCommand(
                        category=category,
                        command=f"make {target}",
                        source="Makefile",
                        description=f"Make target: {target}",
                    ))

    def _from_agents_md(
        self, root: Path, commands: list[DetectedCommand]
    ) -> None:
        agents_md = root / "AGENTS.md"
        if not agents_md.exists():
            return

        content = agents_md.read_text(encoding="utf-8")

        explicit_commands: list[DetectedCommand] = []
        in_bash_block = False
        for line_number, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("```"):
                if in_bash_block:
                    in_bash_block = False
                    continue
                language = stripped.removeprefix("```").strip().lower()
                in_bash_block = language in {"", "bash", "sh", "shell", "zsh"}
                continue

            if in_bash_block and stripped:
                category = self._classify_command(stripped)
                if category:
                    explicit_commands.append(DetectedCommand(
                        category=category,
                        command=stripped,
                        source=f"AGENTS.md:{line_number}",
                        description="从 AGENTS.md fenced code block 提取",
                    ))
                continue

            labeled = _LABELED_COMMAND_RE.match(line)
            if labeled:
                label = labeled.group("label")
                body = labeled.group("body")
                command = self._extract_command_text(body)
                category = self._classify_label(label) or self._classify_command(command)
                if command and category:
                    explicit_commands.append(DetectedCommand(
                        category=category,
                        command=command,
                        source=f"AGENTS.md:{line_number}",
                        description="从 AGENTS.md 显式标签提取",
                    ))

        if not explicit_commands:
            return

        # AGENTS.md 是显式项目指令；同一类别下优先展示它，而不是 pyproject 推断值。
        explicit_categories = {cmd.category for cmd in explicit_commands}
        commands[:] = [
            cmd for cmd in commands
            if cmd.category not in explicit_categories
        ]
        seen: set[tuple[str, str]] = set()
        for cmd in explicit_commands:
            key = (cmd.category, cmd.command)
            if key in seen:
                continue
            seen.add(key)
            commands.append(cmd)

    def _from_package_json(
        self, root: Path, commands: list[DetectedCommand]
    ) -> None:
        pkg_json = root / "package.json"
        if not pkg_json.exists():
            return

        import json
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return

        scripts = data.get("scripts", {})
        for name, cmd in scripts.items():
            category = self._classify_target(name)
            if category:
                commands.append(DetectedCommand(
                    category=category,
                    command=f"npm run {name}",
                    source="package.json",
                    description=f"npm script: {name}",
                ))

    # ── 分类辅助 ────────────────────────────────────────

    @staticmethod
    def _classify_target(name: str) -> str | None:
        """根据 target/script 名推断类别。"""
        name_lower = name.lower()
        if name_lower in ("test", "tests", "testing"):
            return "test"
        if "test" in name_lower:
            return "test"
        if name_lower in ("lint", "format", "fmt", "check"):
            return "lint"
        if name_lower in ("typecheck", "mypy", "tsc", "types"):
            return "typecheck"
        if name_lower in ("build", "compile"):
            return "build"
        if name_lower in ("run", "start", "dev", "serve"):
            return "run"
        return None

    @staticmethod
    def _classify_command(cmd: str) -> str | None:
        """根据命令内容推断类别。"""
        cmd_lower = cmd.lower()
        if "pytest" in cmd_lower:
            return "test"
        if "ruff" in cmd_lower or "eslint" in cmd_lower:
            return "lint"
        if "mypy" in cmd_lower:
            return "typecheck"
        return None

    @staticmethod
    def _classify_label(label: str) -> str | None:
        label_lower = label.lower().replace(" ", "")
        if label_lower in {"runtests", "runtest", "tests", "test"}:
            return "test"
        if label_lower == "lint":
            return "lint"
        if label_lower in {"typecheck", "typechecks"}:
            return "typecheck"
        if label_lower == "build":
            return "build"
        if label_lower == "run":
            return "run"
        return None

    @staticmethod
    def _extract_command_text(text: str) -> str:
        inline = _INLINE_CODE_RE.search(text)
        if inline:
            return inline.group(1).strip()
        return text.strip().lstrip("-* ").strip()
