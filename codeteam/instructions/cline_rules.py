"""
ClineRulesLoader：加载 .clinerules 条件规则。

支持 YAML Frontmatter 中的 paths 条件：
- 无 Frontmatter → 无条件规则（始终激活）
- paths: [...]  → 条件规则（路径匹配时激活）
- paths: []     → 永不激活
- YAML 解析失败 → 不激活，记录诊断
"""
from __future__ import annotations

from pathlib import Path

from codeteam.instructions.models import InstructionSource, InstructionSourceType
from codeteam.instructions.frontmatter import split_frontmatter
from codeteam.instructions.glob_matcher import glob_matches


class ClineRulesLoader:
    """.clinerules 条件规则加载器。

    用法：
        loader = ClineRulesLoader()
        sources, diags = loader.load(
            repository_root=Path("/repo"),
            context_paths={"frontend/src/App.tsx", "backend/src/api.py"},
        )
        # sources → 激活的规则转为 InstructionSource
        # diags   → 解析失败的诊断信息
    """

    def load(
        self,
        *,
        repository_root: Path,
        context_paths: set[str],
    ) -> tuple[list[InstructionSource], list[str]]:
        """加载 .clinerules 目录中的规则。

        Args:
            repository_root: 仓库根目录。
            context_paths:   当前上下文中涉及的文件路径集合。
                             用于匹配条件规则的 paths 模式。

        Returns:
            (激活的规则列表, 诊断信息列表)
        """
        rules_dir = repository_root / ".clinerules"
        if not rules_dir.is_dir():
            return [], []

        # 收集所有 .md 和 .txt 文件
        rule_files: list[Path] = []
        for ext in (".md", ".txt"):
            rule_files.extend(rules_dir.rglob(f"*{ext}"))

        # 排序保证确定性（文件名顺序）
        rule_files = sorted(rule_files)

        sources: list[InstructionSource] = []
        diagnostics: list[str] = []

        for rule_file in rule_files:
            content = rule_file.read_text(
                encoding="utf-8",
                errors="replace",
            )

            frontmatter, body = split_frontmatter(content)

            relative_path = rule_file.relative_to(
                repository_root
            ).as_posix()

            # 情况 1：无 Frontmatter → 无条件规则，始终激活
            if frontmatter is None:
                sources.append(
                    InstructionSource(
                        path=relative_path,
                        source_type=InstructionSourceType.CLINE_RULE,
                        scope_path="",  # 无作用域限制
                        depth=0,
                        priority=50,  # 低于 AGENTS.md
                        content=body,
                    )
                )
                continue

            # 情况 2：有 Frontmatter 但 YAML 解析失败
            if frontmatter is None or not isinstance(frontmatter, dict):
                # 这不会发生（split_frontmatter 返回 None 是情况 1），
                # 但保留防御性代码
                diagnostics.append(
                    f"YAML 解析失败：{relative_path}"
                    f"，规则不激活"
                )
                continue

            # 情况 3：有 Frontmatter，提取 paths
            patterns = frontmatter.get("paths", [])

            if not isinstance(patterns, list):
                diagnostics.append(
                    f"paths 字段必须是列表：{relative_path}"
                )
                continue

            # paths: [] 空列表 → 永不激活
            if not patterns:
                continue

            # 检查是否至少匹配一个上下文路径
            matched = [
                p for p in sorted(context_paths)
                if any(
                    glob_matches(pattern, p)
                    for pattern in patterns
                )
            ]

            if matched:
                # 作用域是第一个 pattern 的目录部分
                scope = patterns[0].rstrip("/**").rstrip("/*")
                sources.append(
                    InstructionSource(
                        path=relative_path,
                        source_type=InstructionSourceType.CLINE_RULE,
                        scope_path=scope,
                        depth=0,
                        priority=60,  # 条件规则比无条件高，但低于 AGENTS.md
                        content=body,
                    )
                )
            # 不匹配 → 不激活（不是错误，不需要诊断）

        return sources, diagnostics