"""测试 RepositoryInspector 适配层（codeteam/agent/inspection.py）。

覆盖 day1.md 一百零五节验收（管线: Repository Inspection）：
- 真实 ContextApplicationService + fixture 拷贝 → RepositoryContext
  字段映射正确（relevant_files / 去重有序符号 / test_commands 前缀 / summary）
- 注入假 service（固定 report）→ 适配行为正确
- 注入假 service（抛异常）→ 异常原样传播

遵守测试隔离规约：fixture 一律拷贝到 tmp_path（见 conftest.py）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeteam.agent.inspection import RepositoryInspector
from codeteam.application.build_context import (
    ContextApplicationService,
    ContextBuildReport,
    SelectedFileReport,
)
from codeteam.instructions.command_detector import DetectedCommand

# ---------------------------------------------------------------------------
# 假 service（duck typing：只需 execute 方法）
# ---------------------------------------------------------------------------

class _FakeService:
    """返回固定 ContextBuildReport 的假服务。"""

    def __init__(self, report: ContextBuildReport) -> None:
        self._report = report

    def execute(
        self,
        *,
        query: str,
        repository_root: Path,
        top_k: int = 5,
        budget_tokens: int = 1024,
    ) -> ContextBuildReport:
        return self._report


class _RaisingService:
    """总是抛出异常的服务（模拟 Context Engine 故障）。"""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def execute(
        self,
        *,
        query: str,
        repository_root: Path,
        top_k: int = 5,
        budget_tokens: int = 1024,
    ) -> ContextBuildReport:
        raise self._error


def _fixed_report() -> ContextBuildReport:
    """构造一个字段明确的固定 report（供适配层映射断言）。"""
    return ContextBuildReport(
        query="测试查询",
        top_files=[
            SelectedFileReport(
                path="src/auth/service.py",
                rank=1,
                score=9.5,
                matched_symbols=["AuthService", "refresh_access_token"],
            ),
            SelectedFileReport(
                path="src/auth/api.py",
                rank=2,
                score=8.1,
                # 与第一个文件重复的符号，验证去重
                matched_symbols=["AuthService", "AuthController"],
            ),
        ],
        applicable_instructions=["所有修改必须有测试"],
        test_commands=[
            DetectedCommand(
                category="test", command="pytest", source="AGENTS.md"
            ),
            DetectedCommand(
                category="lint", command="ruff check .", source="AGENTS.md"
            ),
        ],
        candidate_count=7,
    )


# ===================================================================
# 真实 Context Engine + fixture 拷贝
# ===================================================================

class TestRealContextEngine:
    """真实 ContextApplicationService 在 fixture 拷贝上的适配。"""

    def test_inspect_returns_grounded_context(self, repo_copy: Path) -> None:
        """验收(管线: Repository Inspection): 真实引擎在 fixture 拷贝上
        返回 RepositoryContext——relevant_files 非空、不超过 top_k、
        符号去重有序、test_commands 带 category 前缀、summary 非空。"""
        inspector = RepositoryInspector(ContextApplicationService())

        ctx = inspector.inspect(
            query="AuthService refresh 的完整链路",
            repository_root=repo_copy,
            top_k=5,
        )

        # relevant_files 非空且不超过 top_k
        assert ctx.relevant_files, "相关文件不应为空"
        assert len(ctx.relevant_files) <= 5

        # 所有引用文件真实存在（Grounding）
        for f in ctx.relevant_files:
            assert (repo_copy / f).exists(), f"幻觉文件引用: {f}"

        # 符号去重 + 有序（确定性）
        assert ctx.relevant_symbols == tuple(
            sorted(set(ctx.relevant_symbols))
        )

        # test_commands 带 "category: command" 前缀（fixture 有 pytest 配置）
        assert ctx.test_commands, "fixture 含 pytest 配置，命令不应为空"
        for cmd in ctx.test_commands:
            assert ":" in cmd
        assert any(c.startswith("test") for c in ctx.test_commands)

        # summary 非空
        assert ctx.summary


# ===================================================================
# 假 service：固定 report 的映射正确性
# ===================================================================

class TestAdapterMapping:
    """适配层的字段映射与异常传播。"""

    def test_maps_fixed_report_fields(self) -> None:
        """验收(管线: Repository Inspection): 字段映射正确——
        relevant_files 来自 top_files；符号去重排序；
        instructions 原样；test_commands 字符串化。"""
        inspector = RepositoryInspector(_FakeService(_fixed_report()))

        ctx = inspector.inspect(
            query="q", repository_root=Path("/tmp/whatever")
        )

        assert ctx.relevant_files == (
            "src/auth/service.py",
            "src/auth/api.py",
        )

        # AuthService 在两个文件中都出现 → 去重后只保留一份
        assert ctx.relevant_symbols == (
            "AuthController",
            "AuthService",
            "refresh_access_token",
        )

        assert ctx.instructions == ("所有修改必须有测试",)
        assert ctx.test_commands == (
            "test: pytest",
            "lint: ruff check .",
        )
        assert ctx.summary  # 非空

    def test_service_exception_propagates(self) -> None:
        """验收(管线: 失败路径): Context Engine 抛异常 → 适配层原样传播，
        由 Orchestrator 总闸门处理。"""
        inspector = RepositoryInspector(
            _RaisingService(RuntimeError("index build failed"))
        )

        with pytest.raises(RuntimeError, match="index build failed"):
            inspector.inspect(query="q", repository_root=Path("/tmp/x"))
