"""
pytest 配置检测器。

从 pyproject.toml 和 pytest.ini 检测 Python 测试命令。
关键决策：检测到 addopts 时不手工拼接进命令 ——
pytest 会自行加载配置文件。
"""
from __future__ import annotations

import configparser
import tomllib
from pathlib import Path

from codeteam.commands.models import CommandKind, CommandRisk, DetectedCommand


def detect_from_pytest(repository_root: Path) -> DetectedCommand | None:
    """从 pytest 配置检测测试命令。

    按 pytest 优先级查找配置文件：
    pytest.ini → pyproject.toml → setup.cfg

    Args:
        repository_root: 仓库根目录。

    Returns:
        DetectedCommand 或 None（如果没找到 pytest 配置）。
    """
    # 优先级 1：pytest.ini
    ini_path = repository_root / "pytest.ini"
    if ini_path.is_file():
        return _from_pytest_ini(ini_path)

    # 优先级 2：pyproject.toml
    pyproject_path = repository_root / "pyproject.toml"
    if pyproject_path.is_file():
        return _from_pyproject(pyproject_path)

    # 优先级 3：setup.cfg
    setup_cfg = repository_root / "setup.cfg"
    if setup_cfg.is_file():
        return _from_setup_cfg(setup_cfg)

    return None


def _from_pytest_ini(path: Path) -> DetectedCommand:
    """从 pytest.ini 提取命令信息。"""
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")

    addopts = ""
    testpaths = ""

    if "pytest" in parser:
        section = parser["pytest"]
        addopts = section.get("addopts", "")
        testpaths = section.get("testpaths", "")

    return DetectedCommand(
        command_id="pytest",
        kind=CommandKind.TEST,
        argv=["python", "-m", "pytest"],
        cwd=str(path.parent.relative_to(path.parent)),  # "."
        source_path=str(path),
        source_type="pytest_config",
        source_detail=(
            f"pytest.ini config"
            f"{'; addopts=' + addopts if addopts else ''}"
            f"{'; testpaths=' + testpaths if testpaths else ''}"
        ),
        confidence=0.85,
        risk=CommandRisk.WORKSPACE_WRITE,
        requires_approval=False,
    )


def _from_pyproject(path: Path) -> DetectedCommand | None:
    """从 pyproject.toml 提取 pytest 配置。"""
    with path.open("rb") as f:
        data = tomllib.load(f)

    tool = data.get("tool", {})
    pytest_config = None

    # [tool.pytest]（原生 TOML 格式）
    if "pytest" in tool:
        pytest_config = tool["pytest"]
    # [tool.pytest.ini_options]（INI 兼容格式）
    elif "pytest" in tool and "ini_options" in tool.get("pytest", {}):
        pytest_config = tool["pytest"]["ini_options"]

    if pytest_config is None:
        return None

    addopts = pytest_config.get("addopts", "")
    testpaths_raw = pytest_config.get("testpaths", [])
    if isinstance(testpaths_raw, list):
        testpaths = ", ".join(testpaths_raw)
    else:
        testpaths = str(testpaths_raw)

    return DetectedCommand(
        command_id="pytest",
        kind=CommandKind.TEST,
        argv=["python", "-m", "pytest"],
        cwd="",
        source_path=str(path),
        source_type="pytest_config",
        source_detail=(
            f"pyproject.toml pytest config"
            f"{'; addopts=' + addopts if addopts else ''}"
            f"{'; testpaths=' + testpaths if testpaths else ''}"
        ),
        confidence=0.85,
        risk=CommandRisk.WORKSPACE_WRITE,
        requires_approval=False,
    )


def _from_setup_cfg(path: Path) -> DetectedCommand | None:
    """从 setup.cfg 提取 pytest 配置。"""
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")

    if "tool:pytest" not in parser:
        return None

    section = parser["tool:pytest"]
    addopts = section.get("addopts", "")
    testpaths = section.get("testpaths", "")

    return DetectedCommand(
        command_id="pytest",
        kind=CommandKind.TEST,
        argv=["python", "-m", "pytest"],
        cwd="",
        source_path=str(path),
        source_type="pytest_config",
        source_detail=(
            f"setup.cfg pytest config"
            f"{'; addopts=' + addopts if addopts else ''}"
        ),
        confidence=0.8,
        risk=CommandRisk.WORKSPACE_WRITE,
        requires_approval=False,
    )