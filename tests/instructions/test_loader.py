"""测试 InstructionLoader: 加载嵌套 AGENTS.md 规则。

覆盖场景：
- T01: 根规则 - target 文件加载根 AGENTS.md
- T02: 嵌套规则 - 子目录规则优先级 > 父规则
- T03: 冲突规则 - 同名指令冲突
- T04: 多目标作用域 - 不同 target 加载不同规则
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from codeteam.instructions.loader import InstructionLoader
from codeteam.instructions.models import InstructionSourceType


# ===================================================================
# T01: 根规则
# ===================================================================

class TestRootRule:
    """T01: 根规则 - target 文件能加载根 AGENTS.md，source_path 可追踪。"""

    def test_single_target_loads_root_agents_md(self) -> None:
        """src/main.py 应加载根 AGENTS.md。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text("# Project Rules\n\nRun tests with pytest.\n")
            src_dir = root / "src"
            src_dir.mkdir()
            (src_dir / "main.py").write_text("print('hello')\n")

            loader = InstructionLoader()
            bundle = loader.load(
                repository_root=root,
                target_paths=["src/main.py"],
            )

            # 根 AGENTS.md 应出现在 common_sources
            assert len(bundle.common_sources) >= 1, (
                f"Expected at least 1 common source, got {len(bundle.common_sources)}"
            )
            root_source = bundle.common_sources[0]
            assert root_source.path == "AGENTS.md", (
                f"Expected 'AGENTS.md', got '{root_source.path}'"
            )
            assert root_source.source_type == InstructionSourceType.AGENTS_MD
            assert root_source.scope_path == "", (
                f"Root scope should be empty, got '{root_source.scope_path}'"
            )
            assert root_source.content == "# Project Rules\n\nRun tests with pytest.\n"

    def test_source_path_is_traceable(self) -> None:
        """source_path 应可追踪到具体文件。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text("Root rules.\n")
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("")

            loader = InstructionLoader()
            bundle = loader.load(
                repository_root=root,
                target_paths=["src/main.py"],
            )

            by_target = bundle.by_target["src/main.py"]
            for source in by_target.sources:
                # source_path 必须存在且非空
                assert source.path, "source_path should not be empty"
                # content 必须非空（加载了规则）
                assert source.content, (
                    f"Source {source.path} should have content"
                )

    def test_no_agents_md_produces_empty_sources(self) -> None:
        """没有 AGENTS.md 时 sources 为空。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("")

            loader = InstructionLoader()
            bundle = loader.load(
                repository_root=root,
                target_paths=["src/main.py"],
            )

            by_target = bundle.by_target["src/main.py"]
            assert len(by_target.sources) == 0, (
                f"Expected 0 sources without AGENTS.md, "
                f"got {len(by_target.sources)}"
            )


# ===================================================================
# T02: 嵌套规则
# ===================================================================

class TestNestedRules:
    """T02: 嵌套规则 - backend/service.py 规则顺序：根 → backend，
    backend 规则优先级更高。"""

    def test_nested_rules_ordered_root_to_near(self) -> None:
        """规则应按根→近端顺序排列。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text("Root: pytest\n")
            backend_dir = root / "backend"
            backend_dir.mkdir()
            (backend_dir / "AGENTS.md").write_text("Backend: uv run pytest\n")
            (backend_dir / "service.py").write_text("")

            loader = InstructionLoader()
            bundle = loader.load(
                repository_root=root,
                target_paths=["backend/service.py"],
            )

            by_target = bundle.by_target["backend/service.py"]
            sources = by_target.sources

            assert len(sources) == 2, (
                f"Expected 2 sources (root + backend), got {len(sources)}"
            )
            # 根在先
            assert sources[0].path == "AGENTS.md"
            # backend 在后（近端优先级更高）
            assert sources[1].path == "backend/AGENTS.md"
            assert sources[1].priority > sources[0].priority, (
                f"backend priority ({sources[1].priority}) "
                f"should be > root ({sources[0].priority})"
            )

    def test_nested_rule_priority_increases_with_depth(self) -> None:
        """更深层的规则应有更高优先级。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text("Root.\n")
            a = root / "a"
            a.mkdir()
            (a / "AGENTS.md").write_text("A.\n")
            b = a / "b"
            b.mkdir()
            (b / "AGENTS.md").write_text("B.\n")
            (b / "file.py").write_text("")

            loader = InstructionLoader()
            bundle = loader.load(
                repository_root=root,
                target_paths=["a/b/file.py"],
            )

            sources = bundle.by_target["a/b/file.py"].sources
            assert len(sources) == 3
            priorities = [s.priority for s in sources]
            assert priorities == sorted(priorities), (
                f"Priorities should be ascending (root→near), got {priorities}"
            )


# ===================================================================
# T03: 冲突规则
# ===================================================================

class TestConflictRules:
    """T03: 冲突规则 - 同名指令在两个层级定义时检测冲突。

    注：当前 InstructionLoader 不自动检测冲突（InstructionConflict 由
    业务层使用）。本测试验证 EffectiveInstructions.rendered_content 中
    同时包含两个层级的指令。
    """

    def test_rendered_content_includes_both_levels(self) -> None:
        """rendered_content 应包含根和子目录的规则。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text("Root: pytest\n")
            sub = root / "sub"
            sub.mkdir()
            (sub / "AGENTS.md").write_text("Sub: uv run pytest\n")
            (sub / "file.py").write_text("")

            loader = InstructionLoader()
            bundle = loader.load(
                repository_root=root,
                target_paths=["sub/file.py"],
            )

            eff = bundle.by_target["sub/file.py"]
            rendered = eff.rendered_content

            assert "Root: pytest" in rendered
            assert "Sub: uv run pytest" in rendered
            # 子目录规则应出现在后面（优先级更高）
            root_pos = rendered.index("Root: pytest")
            sub_pos = rendered.index("Sub: uv run pytest")
            assert root_pos < sub_pos, (
                f"Root rule should appear before sub rule"
            )


# ===================================================================
# T04: 多目标作用域
# ===================================================================

class TestMultiTargetScoping:
    """T04: 多目标作用域 - 不同 target 加载不同规则。

    frontend 规则不应用到 backend 文件，反之亦然。
    公共根规则应用到两者。
    """

    def test_different_targets_get_different_rules(self) -> None:
        """frontend 和 backend 应各自加载对应规则。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text("Root rules.\n")

            fe_dir = root / "frontend"
            fe_dir.mkdir()
            (fe_dir / "AGENTS.md").write_text("Frontend: vitest\n")
            (fe_dir / "src").mkdir(parents=True)
            (fe_dir / "src" / "App.tsx").write_text("")

            be_dir = root / "backend"
            be_dir.mkdir()
            (be_dir / "AGENTS.md").write_text("Backend: pytest\n")
            (be_dir / "src").mkdir(parents=True)
            (be_dir / "src" / "api.py").write_text("")

            loader = InstructionLoader()
            bundle = loader.load(
                repository_root=root,
                target_paths=[
                    "frontend/src/App.tsx",
                    "backend/src/api.py",
                ],
            )

            fe_sources = bundle.by_target["frontend/src/App.tsx"].sources
            be_sources = bundle.by_target["backend/src/api.py"].sources

            # 两者都有根规则
            assert any(s.path == "AGENTS.md" for s in fe_sources)
            assert any(s.path == "AGENTS.md" for s in be_sources)

            # frontend 独有的子目录规则
            fe_paths = {s.path for s in fe_sources}
            assert "frontend/AGENTS.md" in fe_paths
            assert "backend/AGENTS.md" not in fe_paths, (
                "frontend target should NOT get backend rules"
            )

            # backend 独有的子目录规则
            be_paths = {s.path for s in be_sources}
            assert "backend/AGENTS.md" in be_paths
            assert "frontend/AGENTS.md" not in be_paths, (
                "backend target should NOT get frontend rules"
            )

    def test_empty_target_paths_produces_diagnostics(self) -> None:
        """空 target_paths 应产生诊断信息。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            loader = InstructionLoader()
            bundle = loader.load(
                repository_root=root,
                target_paths=[],
            )

            assert len(bundle.diagnostics) > 0, (
                "Empty target_paths should produce a diagnostic"
            )
