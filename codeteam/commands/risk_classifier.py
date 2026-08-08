"""
命令风险分类器：根据 argv 判断命令的风险等级。

使用模式匹配识别破坏性、网络、权限升级等高风险操作。
"""
from __future__ import annotations

from codeteam.commands.models import CommandRisk


# 危险命令关键字 → 风险等级
_RISK_PATTERNS: list[tuple[list[str], CommandRisk]] = [
    # 破坏性操作
    (["rm", "-rf"], CommandRisk.DESTRUCTIVE),
    (["rm", "-r"], CommandRisk.DESTRUCTIVE),
    (["git", "reset", "--hard"], CommandRisk.DESTRUCTIVE),
    (["git", "clean", "-fd"], CommandRisk.DESTRUCTIVE),
    (["drop", "database"], CommandRisk.DESTRUCTIVE),
    (["git", "push", "--force"], CommandRisk.DESTRUCTIVE),
    # 远程变更
    (["git", "push"], CommandRisk.NETWORK),
    (["npm", "publish"], CommandRisk.NETWORK),
    (["docker", "push"], CommandRisk.NETWORK),
    # 网络下载 + 管道执行
    (["curl"], CommandRisk.NETWORK),
    (["wget"], CommandRisk.NETWORK),
    # 权限升级
    (["sudo"], CommandRisk.DESTRUCTIVE),
    (["su"], CommandRisk.DESTRUCTIVE),
    (["chmod", "777"], CommandRisk.DESTRUCTIVE),
    # 安装（网络 + 写文件）
    (["pip", "install"], CommandRisk.NETWORK),
    (["npm", "install"], CommandRisk.NETWORK),
    (["pnpm", "install"], CommandRisk.NETWORK),
    (["yarn", "install"], CommandRisk.NETWORK),
    # 凭证访问
    (["cat", "~/.ssh"], CommandRisk.SECRET_ACCESS),
    (["cat", "~/.aws"], CommandRisk.SECRET_ACCESS),
]


def classify_risk(argv: list[str]) -> tuple[CommandRisk, bool]:
    """根据命令参数判断风险等级。

    Args:
        argv: 命令行参数列表，如 ["rm", "-rf", "/tmp/cache"]

    Returns:
        (risk, requires_approval)：
        - risk: 风险等级
        - requires_approval: 是否需要用户审批

    >>> classify_risk(["pytest", "tests/", "-q"])
    (CommandRisk.WORKSPACE_WRITE, False)
    >>> classify_risk(["rm", "-rf", "/tmp/cache"])
    (CommandRisk.DESTRUCTIVE, True)
    """
    if not argv:
        return CommandRisk.UNKNOWN, True

    command_str = " ".join(argv).lower()

    for patterns, risk in _RISK_PATTERNS:
        # 检查所有 pattern 是否都在命令中出现（顺序不限）
        if all(p.lower() in command_str for p in patterns):
            return risk, _requires_approval_for(risk)

    # 没有命中危险模式 → 根据 argv[0] 做基本判断
    executable = argv[0].lower()

    # 常见的读写命令
    safe_test_runners = {"pytest", "python", "go", "cargo", "vitest", "jest"}
    safe_linters = {"ruff", "eslint", "mypy", "flake8"}

    if executable in safe_test_runners:
        return CommandRisk.WORKSPACE_WRITE, False
    if executable in safe_linters:
        return CommandRisk.READ_ONLY, False

    return CommandRisk.UNKNOWN, True


def _requires_approval_for(risk: CommandRisk) -> bool:
    """判断某个风险等级是否需要审批。"""
    return risk in {
        CommandRisk.DESTRUCTIVE,
        CommandRisk.NETWORK,
        CommandRisk.SECRET_ACCESS,
        CommandRisk.UNKNOWN,
    }
