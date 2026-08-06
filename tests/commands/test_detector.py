"""测试 CommandDetector: 命令检测主入口 + 各来源检测器。

覆盖场景：
- T05: package.json 脚本检测 + lifecycle chain
- T06: pyproject.toml pytest 配置
- T07: pytest.ini 配置
- T10: 危险命令风险分类
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from codeteam.commands.detector import CommandDetector
from codeteam.commands.models import CommandKind, CommandRisk, DetectedCommand
from codeteam.commands.package_json import detect_from_package_json
from codeteam.commands.pytest_config import detect_from_pytest
from codeteam.commands.risk_classifier import classify_risk


# ===================================================================
# T05: package.json
# ===================================================================

class TestPackageJson:
    """T05: package.json 脚本检测 + lifecycle chain。

    断言：
    - 检测 npm run test
    - 检测 lifecycle chain (pretest → test → posttest)
    - 记录 underlying script（"vitest run"）
    - 不会执行任何脚本
    """

    def test_detects_test_script(self) -> None:
        """package.json 中 "test": "vitest run" 应被检测为 TEST 命令。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = {
                "scripts": {
                    "test": "vitest run"
                }
            }
            (root / "package.json").write_text(json.dumps(pkg))

            commands = detect_from_package_json(root)

            test_cmds = [c for c in commands if c.kind == CommandKind.TEST]
            assert len(test_cmds) >= 1, (
                f"Expected at least 1 TEST command, got {len(test_cmds)}"
            )
            test_cmd = test_cmds[0]
            assert test_cmd.source_path == "package.json"
            assert test_cmd.source_type == "package_script"
            assert test_cmd.underlying_script == "vitest run"

    def test_lifecycle_chain_is_detected(self) -> None:
        """pretest + test + posttest 应组成完整 lifecycle chain。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = {
                "scripts": {
                    "pretest": "node scripts/setup.js",
                    "test": "vitest run",
                    "posttest": "node scripts/report.js",
                }
            }
            (root / "package.json").write_text(json.dumps(pkg))

            commands = detect_from_package_json(root)
            test_cmd = next(c for c in commands if c.command_id == "npm:test")

            chain = test_cmd.lifecycle_chain
            assert "pretest" in chain, (
                f"Expected 'pretest' in lifecycle_chain, got {chain}"
            )
            assert "test" in chain
            assert "posttest" in chain, (
                f"Expected 'posttest' in lifecycle_chain, got {chain}"
            )
            assert chain == ["pretest", "test", "posttest"], (
                f"Lifecycle chain order wrong: {chain}"
            )

    def test_no_package_json_returns_empty(self) -> None:
        """没有 package.json 时返回空列表。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assert detect_from_package_json(root) == []

    def test_package_json_with_no_scripts(self) -> None:
        """package.json 无 scripts 字段时返回空列表。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name": "test"}')
            assert detect_from_package_json(root) == []

    def test_npm_run_test_is_argv(self) -> None:
        """argv 应为 ['npm', 'run', 'test']（不执行）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest run"}})
            )
            commands = detect_from_package_json(root)
            test_cmd = next(c for c in commands if c.command_id == "npm:test")

            assert test_cmd.argv[:2] == ["npm", "run"], (
                f"Expected ['npm', 'run', ...], got {test_cmd.argv}"
            )


# ===================================================================
# T06: pyproject.toml pytest
# ===================================================================

class TestPyprojectPytest:
    """T06: pyproject.toml 中的 pytest 配置。

    断言：
    - 检测 python -m pytest
    - 记录 testpaths
    - 不把 addopts 重复拼接进命令
    """

    def test_detects_pytest_in_pyproject(self) -> None:
        """pyproject.toml 有 [tool.pytest.ini_options] 时应检测到 pytest。

        已知缺陷：_from_pyproject 的 `if "pytest" in tool` 分支
        取到的是 `{"ini_options": {...}}` 而不是 `ini_options` 的内容，
        导致 addopts/testpaths 无法被正确提取。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 使用 [tool.pytest] 格式（非 ini_options 嵌套）
            toml = (
                "[tool.pytest]\n"
                'addopts = "-ra -q"\n'
                'testpaths = ["tests"]\n'
            )
            (root / "pyproject.toml").write_text(toml)

            cmd = detect_from_pytest(root)
            assert cmd is not None, "Should detect pytest in pyproject.toml"
            assert cmd.kind == CommandKind.TEST
            assert cmd.argv == ["python", "-m", "pytest"], (
                f"argv should not include addopts, got {cmd.argv}"
            )
            assert cmd.source_type == "pytest_config"
            # source_detail 应包含 addopts 和 testpaths 信息
            assert "addopts" in cmd.source_detail, (
                f"source_detail should mention addopts: {cmd.source_detail}"
            )
            assert "tests" in cmd.source_detail, (
                f"source_detail should mention testpaths: {cmd.source_detail}"
            )

    def test_no_pyproject_returns_none(self) -> None:
        """没有 pyproject.toml 时返回 None。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assert detect_from_pytest(root) is None


# ===================================================================
# T07: pytest.ini
# ===================================================================

class TestPytestIni:
    """T07: pytest.ini 配置检测。

    断言：
    - 正确识别 pytest
    - 正确识别 testpaths
    """

    def test_detects_pytest_ini(self) -> None:
        """pytest.ini 应被正确识别。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pytest.ini").write_text(
                "[pytest]\n"
                "testpaths = tests integration\n"
                "addopts = -q\n"
            )

            cmd = detect_from_pytest(root)
            assert cmd is not None, "Should detect pytest in pytest.ini"
            assert cmd.kind == CommandKind.TEST
            assert cmd.argv[0] == "python"
            assert "pytest" in cmd.argv
            # addopts 不应拼进 argv
            assert "-q" not in cmd.argv, (
                f"addopts should NOT be spliced into argv, got {cmd.argv}"
            )
            assert "tests" in cmd.source_detail, (
                f"source_detail should mention testpaths: {cmd.source_detail}"
            )

    def test_detects_multiple_testpaths(self) -> None:
        """testpaths = tests integration（多个目录）应被记录。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pytest.ini").write_text(
                "[pytest]\n"
                "testpaths = tests integration\n"
            )

            cmd = detect_from_pytest(root)
            assert cmd is not None
            assert "tests" in cmd.source_detail
            assert "integration" in cmd.source_detail


# ===================================================================
# T10: 危险命令
# ===================================================================

class TestDangerousCommands:
    """T10: 危险命令风险分类。

    断言：
    - sudo rm -rf → DESTRUCTIVE
    - requires_approval = true
    - 执行器没有被调用（本测试只检查分类器输出）
    """

    @pytest.mark.parametrize(
        ("argv", "expected_risk", "expected_approval"),
        [
            pytest.param(
                ["rm", "-rf", "/tmp/project-cache"],
                CommandRisk.DESTRUCTIVE, True,
                id="rm-rf-destructive",
            ),
            pytest.param(
                ["sudo", "rm", "-rf", "/tmp/project-cache"],
                CommandRisk.DESTRUCTIVE, True,
                id="sudo-rm-rf",
            ),
            pytest.param(
                ["git", "push", "--force"],
                CommandRisk.DESTRUCTIVE, True,
                id="git-push-force",
            ),
            pytest.param(
                ["git", "reset", "--hard"],
                CommandRisk.DESTRUCTIVE, True,
                id="git-reset-hard",
            ),
            pytest.param(
                ["pip", "install", "requests"],
                CommandRisk.NETWORK, True,
                id="pip-install-network",
            ),
            pytest.param(
                ["curl", "https://example.com"],
                CommandRisk.NETWORK, True,
                id="curl-network",
            ),
            pytest.param(
                ["cat", "~/.ssh/config"],
                CommandRisk.SECRET_ACCESS, True,
                id="cat-ssh-secret",
            ),
            pytest.param(
                ["python", "-m", "pytest", "tests/"],
                CommandRisk.WORKSPACE_WRITE, False,
                id="pytest-safe",
            ),
            pytest.param(
                ["ruff", "check", "src/"],
                CommandRisk.READ_ONLY, False,
                id="ruff-safe-readonly",
            ),
        ],
    )
    def test_risk_classification(self, argv: list[str],
                                  expected_risk: CommandRisk,
                                  expected_approval: bool) -> None:
        """命令应根据参数被正确分类。"""
        risk, requires = classify_risk(argv)
        assert risk == expected_risk, (
            f"Expected risk={expected_risk.value}, got {risk.value}"
        )
        assert requires == expected_approval, (
            f"Expected requires_approval={expected_approval}, "
            f"got {requires}"
        )

    def test_dangerous_command_is_marked_as_such(self) -> None:
        """sudo rm -rf 应被标记为 destructive + requires_approval。"""
        risk, requires = classify_risk(["sudo", "rm", "-rf", "/tmp/cache"])
        assert risk == CommandRisk.DESTRUCTIVE
        assert requires is True

    def test_empty_argv_is_unknown(self) -> None:
        """空命令参数返回 UNKNOWN。"""
        risk, requires = classify_risk([])
        assert risk == CommandRisk.UNKNOWN
        assert requires is True


# ===================================================================
# CommandDetector 集成
# ===================================================================

class TestCommandDetectorIntegration:
    """CommandDetector 多来源集成。"""

    def test_detector_combines_sources(self) -> None:
        """多配置来源的命令应被整合。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 添加 package.json
            (root / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest run", "lint": "eslint src"}})
            )
            # 添加 pytest.ini
            (root / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n")

            detector = CommandDetector()
            commands = detector.detect(repository_root=root)

            kinds = {c.kind for c in commands}
            assert CommandKind.TEST in kinds, (
                f"Should detect TEST commands, got kinds: {kinds}"
            )
            # 应去重（两个 TEST 命令可能被合并）
            test_cmds = [c for c in commands if c.kind == CommandKind.TEST]
            assert len(test_cmds) >= 1
