"""
RepositoryInspector：INSPECTING 阶段的仓库检查器。

把 Week 2 Context Engine 的输出（ContextBuildReport）
适配成 Planner 的输入（RepositoryContext）。

这是 Adapter（防腐层）：
Week 2 的 report 结构变化时，只需要改本文件，
Planner 和 Orchestrator 都不受影响。
"""
from __future__ import annotations

from pathlib import Path

from codeteam.application.build_context import (
    ContextApplicationService,
)
from codeteam.planning.planner import RepositoryContext


class RepositoryInspector:
    """用 ContextApplicationService 检查仓库并产出 RepositoryContext。

    用法：
        service = ContextApplicationService()
        inspector = RepositoryInspector(service)
        context = inspector.inspect(
            query="修复登录超时",
            repository_root=Path("/repo"),
        )
    """

    def __init__(self, service: ContextApplicationService) -> None:
        """注入 Week 2 的上下文服务（可替换、可 Mock）。"""
        self._service = service

    def inspect(
        self,
        *,
        query: str,
        repository_root: Path,
        top_k: int = 5,
        budget_tokens: int = 1024,
    ) -> RepositoryContext:
        """执行仓库检查，返回 Planner 可用的仓库证据。

        只读操作：不修改任何磁盘文件。

        Args:
            query: 任务的自然语言描述。
            repository_root: 仓库根目录。
            top_k: 检索 Top K 文件数。
            budget_tokens: 上下文引擎的 token 预算。

        Returns:
            RepositoryContext：从真实检索结果提炼的仓库证据。
        """
        report = self._service.execute(
            query=query,
            repository_root=repository_root,
            top_k=top_k,
            budget_tokens=budget_tokens,
        )

        # 相关文件：Top K 的路径
        relevant_files = tuple(f.path for f in report.top_files)

        # 相关符号：去重 + 排序保证确定性
        symbols: set[str] = set()
        for f in report.top_files:
            for sym in f.matched_symbols:
                symbols.add(sym)
        relevant_symbols = tuple(sorted(symbols))

        # 测试命令：字符串化（Planner 输入是可读文本，不是对象）
        test_commands = tuple(
            f"{c.category}: {c.command}"
            for c in report.test_commands
        )

        summary = (
            f"任务: {query} | "
            f"相关文件: {len(report.top_files)} | "
            f"候选总数: {report.candidate_count}"
        )

        return RepositoryContext(
            summary=summary,
            relevant_files=relevant_files,
            relevant_symbols=relevant_symbols,
            instructions=tuple(report.applicable_instructions),
            test_commands=test_commands,
        )