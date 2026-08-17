"""
Verification 数据模型。

Verification 层位于 CommandResult（进程视角）与 TaskResult（任务视角）
之间：把"命令执行了、exit code 是多少"解释成
"代码行为是否通过了验证"的语义。

VerificationRequest ≠ CommandRequest：
- CommandRequest 描述"我要执行什么 OS 命令"
- VerificationRequest 描述"我为什么执行这个检查、它在 Task 中
  代表什么验证语义"
前者由 Week 3 安全链消费；后者是本层的语义入口，
Step 2 的 VerificationService 负责转换。
"""
from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field


class VerificationKind(str, Enum):
    """验证的种类。不同 kind 的失败在 Runtime 中语义不同。"""

    REPRODUCTION = "reproduction"
    """修改前复现问题（Baseline 证据）。"""

    TARGETED_TEST = "targeted_test"
    """直接验证当前修改所针对行为的最小测试集合。"""

    RELATED_REGRESSION = "related_regression"
    """附近相关行为的回归验证。"""

    FULL_REGRESSION = "full_regression"
    """全量回归（Day 2 预留，不执行）。"""

    BUILD = "build"
    LINT = "lint"
    TYPECHECK = "typecheck"


class VerificationStatus(str, Enum):
    """验证结果的语义状态。

    注意：不是 CommandStatus 的别名。Runner 说
    SUCCESSFULLY_EXECUTED（进程正常管理），Verification 说
    FAILED（exit code 不符合预期）——两层各说各的。
    """

    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    START_FAILED = "start_failed"
    BLOCKED = "blocked"
    INCONCLUSIVE = "inconclusive"

    @property
    def requires_repair(self) -> bool:
        """只有 FAILED 才触发 Repair。

        TIMED_OUT / START_FAILED / BLOCKED / INCONCLUSIVE
        都缺少"代码行为失败"的证据，不应默认修代码。
        """
        return self is VerificationStatus.FAILED


class VerificationRequest(BaseModel):
    """一次验证的语义描述。

    argv 保持结构化 tuple（不是 shell 字符串），
    与 Week 1 以来的安全约定一致。
    """

    verification_id: str
    """稳定标识，Event/RepairAttempt 引用它。"""

    task_id: str
    plan_step_id: str | None = None

    kind: VerificationKind

    argv: tuple[str, ...] = Field(min_length=1)
    """验证命令，如 ("pytest", "tests/auth/test_timeout.py")。"""

    cwd: str
    """执行目录（任务 Worktree）。"""

    expected_exit_codes: tuple[int, ...] = (0,)
    """Oracle：exit code 落在集合内即通过。默认只有 0。"""

    timeout_seconds: float = Field(default=60.0, gt=0)

    purpose: str
    """为什么执行这次检查（人读语义，如 "verify timeout retry behavior"）。"""


class VerificationResult(BaseModel):
    """一次验证的结构化证据。"""

    verification_id: str
    status: VerificationStatus

    exit_code: int | None = None
    duration_ms: float = 0.0

    stdout: str = ""
    stderr: str = ""

    stdout_truncated: bool = False
    stderr_truncated: bool = False
    """truncated 是 Result Metadata，不是 VerificationStatus——
    输出被截断不改变 exit code 判定的结果（day2.md 三十五节）。"""

    failure_signature: str | None = None
    """稳定失败指纹（test name + exception type）。
    只有 status==FAILED 时由 service 提取。"""

    summary: str = ""
    """一行人类可读结论。"""


# ── Failure Signature 提取（纯函数，不接 LLM）──────────────

# pytest 摘要行：FAILED tests/test_auth.py::test_x - AssertionError: ...
_FAILED_SUMMARY_RE = re.compile(r"^FAILED\s+(\S+)", re.MULTILINE)

# 节点 id 兜底：tests/test_auth.py::test_x
_NODE_ID_RE = re.compile(r"\S+::\S+")

# 异常类型：形如 XXXError / XXXException 的词
_EXCEPTION_RE = re.compile(r"\b\w+(?:Error|Exception)\b")


def extract_failure_signature(stdout: str, stderr: str) -> str | None:
    """从验证输出提取稳定失败签名。

    第一版签名 = "{test_name}+{exception_type}"（day2.md 三十七节），
    足够 RepairLoop 识别"连续几次是不是同一失败"。

    例如 stderr 含：
        FAILED tests/test_auth.py::test_expired - AssertionError: ...
    返回：
        "tests/test_auth.py::test_expired+AssertionError"

    Args:
        stdout: 验证命令的标准输出（可能已截断）。
        stderr: 验证命令的标准错误。

    Returns:
        签名字符串；提取不到任何失败信号时返回 None。
    """
    combined = f"{stdout}\n{stderr}"

    # 1. 测试名：优先 pytest 摘要行
    test_name: str | None = None
    match = _FAILED_SUMMARY_RE.search(combined)
    if match:
        test_name = match.group(1)
    else:
        node_match = _NODE_ID_RE.search(combined)
        if node_match:
            test_name = node_match.group(0)

    # 2. 异常类型：第一个 Error/Exception 词
    exception: str | None = None
    for candidate in _EXCEPTION_RE.findall(combined):
        exception = candidate
        break
    if exception is None and "AssertionError" in combined:
        # AssertionError 不以 Error 结尾也能被正则覆盖，
        # 这行是防御性兜底：正则漏掉时手动补
        exception = "AssertionError"

    # 3. 组合
    if test_name and exception:
        return f"{test_name}+{exception}"
    if test_name:
        return f"{test_name}+unknown"
    if exception:
        return f"unknown+{exception}"
    return None