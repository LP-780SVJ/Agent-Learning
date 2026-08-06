"""
InstructionLoader：加载项目指令的主入口。

组合 AgentsMdLoader（AGENTS.md）和 ClineRulesLoader（.clinerules），
为多个目标文件生成独立的有效规则集合。
"""
from __future__ import annotations

from pathlib import Path

from codeteam.instructions.models import (
    EffectiveInstructions,
    InstructionBundle,
    InstructionSource,
)
from codeteam.instructions.agents_md import AgentsMdLoader
from codeteam.instructions.cline_rules import ClineRulesLoader


class InstructionLoader:
    """项目指令加载器。

    用法：
        loader = InstructionLoader()
        bundle = loader.load(
            repository_root=Path("/repo"),
            target_paths=[
                "frontend/src/App.tsx",
                "backend/src/api.py",
            ],
        )
        # bundle.common_sources → 两个文件都适用的公共规则
        # bundle.by_target → 每个文件的独立规则
    """

    def __init__(self) -> None:
        self._agents_md = AgentsMdLoader()
        self._cline_rules = ClineRulesLoader()

    def load(
        self,
        *,
        repository_root: Path,
        target_paths: list[str],
    ) -> InstructionBundle:
        """加载所有目标文件的有效规则。

        Args:
            repository_root: 仓库根目录。
            target_paths:    目标文件路径列表。

        Returns:
            InstructionBundle，包含公共规则和每个目标的独立规则。
        """
        if not target_paths:
            return InstructionBundle(
                diagnostics=["target_paths 为空，未加载任何规则"]
            )

        # 步骤 1：对每个目标文件发现 AGENTS.md 链
        per_target: dict[str, list[InstructionSource]] = {}
        all_sources: list[list[InstructionSource]] = []

        for target in target_paths:
            try:
                sources = self._agents_md.discover_for_target(
                    repository_root=repository_root,
                    target_path=target,
                )
            except (ValueError, PermissionError) as exc:
                # 单个目标加载失败不阻塞其他目标
                per_target[target] = []
                all_sources.append([])
                continue

            per_target[target] = sources
            all_sources.append(sources)

        # 步骤 1.5：加载 .clinerules（统一收集所有目标路径作为上下文）
        all_context_paths = set(target_paths)
        cline_sources, cline_diags = self._cline_rules.load(
            repository_root=repository_root,
            context_paths=all_context_paths,
        )
        diagnostics.extend(cline_diags)

        # 将激活的 cline rules 加入每个目标的 source 列表
        # （无条件规则对所有目标生效，条件规则已在 load 里按匹配激活）
        for target in target_paths:
            if target in per_target:
                per_target[target].extend(cline_sources)

        # 步骤 2：找出公共规则（所有目标都有的 AGENTS.md）
        common = self._find_common_sources(all_sources)

        # 步骤 3：为每个目标构建 EffectiveInstructions
        #    （每个目标的规则 = 公共规则 + 独有规则）
        by_target: dict[str, EffectiveInstructions] = {}
        for target, sources in per_target.items():
            unique = [s for s in sources if s not in common]
            by_target[target] = EffectiveInstructions(
                target_path=target,
                sources=common + unique,  # 公共在前，独有在后
            )

        # 步骤 4：收集诊断信息
        diagnostics: list[str] = []
        for target, sources in per_target.items():
            if not sources:
                diagnostics.append(
                    f"未找到适用于 '{target}' 的 AGENTS.md"
                )

        return InstructionBundle(
            common_sources=common,
            by_target=by_target,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _find_common_sources(
        all_sources: list[list[InstructionSource]],
    ) -> list[InstructionSource]:
        """找出所有目标文件共有的规则来源。

        公共来源的判断标准：path 相同 且 scope_path 相同。
        使用这个标准（而不是对象相等），因为 content 和 hash 可能不同。
        """
        if not all_sources:
            return []

        # 过滤掉空列表（加载失败的目标）
        non_empty = [slist for slist in all_sources if slist]
        if not non_empty:
            return []

        # 以第一个目标为基准，找所有目标都有的 source
        first = non_empty[0]
        common: list[InstructionSource] = []

        for source in first:
            key = (source.path, source.scope_path)
            if all(
                any(
                    (s.path, s.scope_path) == key
                    for s in slist
                )
                for slist in non_empty[1:]
            ):
                common.append(source)

        return common