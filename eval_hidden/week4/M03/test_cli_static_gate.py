import subprocess
import sys
from pathlib import Path


def test_cli_package_static_gates_pass() -> None:
    workspace = Path.cwd()
    ruff = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "codeteam/cli", "tests/cli"],
        cwd=workspace,
        shell=False,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert ruff.returncode == 0, ruff.stdout + ruff.stderr

    mypy = subprocess.run(
        [sys.executable, "-m", "mypy", "codeteam/cli", "tests/cli"],
        cwd=workspace,
        shell=False,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert mypy.returncode == 0, mypy.stdout + mypy.stderr
