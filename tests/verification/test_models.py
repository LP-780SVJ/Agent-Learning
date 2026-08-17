"""测试 Verification 数据模型（codeteam/verification/models.py）。

覆盖 day2.md 验收（一百二十一节 Implementation 部分）：
- VerificationRequest 校验（argv 非空 / timeout 正数 / 默认 exit codes）
- VerificationStatus.requires_repair 语义（三十节：只有 FAILED 触发修复）
- VerificationResult 默认值（三十五节：truncated 是 metadata 不是 status）
- extract_failure_signature（三十七~三十八节：稳定失败指纹）
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from codeteam.verification.models import (
    VerificationKind,
    VerificationRequest,
    VerificationResult,
    VerificationStatus,
    extract_failure_signature,
)


def _request(**kwargs) -> VerificationRequest:
    base = {
        "verification_id": "v-001",
        "task_id": "t-001",
        "kind": VerificationKind.TARGETED_TEST,
        "argv": ("pytest", "tests/test_auth.py"),
        "cwd": "/worktree/t-001",
        "purpose": "verify timeout retry",
    }
    base.update(kwargs)
    return VerificationRequest(**base)


# ===================================================================
# VerificationRequest
# ===================================================================

class TestVerificationRequest:
    """VerificationRequest 构造与校验。"""

    def test_valid_construction(self) -> None:
        """验收(VerificationRequest): 合法构造，字段正确。"""
        req = _request()
        assert req.verification_id == "v-001"
        assert req.task_id == "t-001"
        assert req.plan_step_id is None
        assert req.kind == VerificationKind.TARGETED_TEST
        assert req.argv == ("pytest", "tests/test_auth.py")
        assert req.cwd == "/worktree/t-001"

    def test_empty_argv_rejected(self) -> None:
        """验收(VerificationRequest): argv 空元组 → ValidationError。"""
        with pytest.raises(ValidationError):
            _request(argv=())

    def test_timeout_seconds_must_be_positive(self) -> None:
        """验收(VerificationRequest): timeout_seconds <= 0 → ValidationError。"""
        with pytest.raises(ValidationError):
            _request(timeout_seconds=0)
        with pytest.raises(ValidationError):
            _request(timeout_seconds=-1.5)

    def test_expected_exit_codes_default(self) -> None:
        """验收(VerificationRequest): expected_exit_codes 默认 (0,)。"""
        assert _request().expected_exit_codes == (0,)

    def test_custom_expected_exit_codes(self) -> None:
        """验收(VerificationRequest): 可指定非默认 exit codes 集合。"""
        req = _request(expected_exit_codes=(0, 1))
        assert req.expected_exit_codes == (0, 1)


# ===================================================================
# VerificationStatus.requires_repair
# ===================================================================

class TestRequiresRepair:
    """requires_repair 语义（day2.md 三十节）。"""

    @pytest.mark.parametrize(
        "status,expected",
        [
            (VerificationStatus.FAILED, True),
            (VerificationStatus.PASSED, False),
            (VerificationStatus.TIMED_OUT, False),
            (VerificationStatus.START_FAILED, False),
            (VerificationStatus.BLOCKED, False),
            (VerificationStatus.INCONCLUSIVE, False),
        ],
    )
    def test_requires_repair(
        self, status: VerificationStatus, expected: bool
    ) -> None:
        """验收(VerificationStatus): 只有 FAILED 才触发 Repair——
        TIMED_OUT/START_FAILED/BLOCKED/INCONCLUSIVE 都缺少
        行为失败证据，不默认修代码。"""
        assert status.requires_repair is expected


# ===================================================================
# VerificationResult 默认值
# ===================================================================

class TestVerificationResult:
    """VerificationResult 默认值与 truncated 语义。"""

    def test_defaults(self) -> None:
        """验收(VerificationResult): exit_code None、truncated False、
        signature None、summary 空。"""
        result = VerificationResult(
            verification_id="v-001", status=VerificationStatus.PASSED
        )
        assert result.exit_code is None
        assert result.duration_ms == 0.0
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.stdout_truncated is False
        assert result.stderr_truncated is False
        assert result.failure_signature is None
        assert result.summary == ""


# ===================================================================
# extract_failure_signature
# ===================================================================

class TestFailureSignature:
    """失败签名提取（day2.md 三十七~三十八节）。"""

    def test_pytest_summary_line(self) -> None:
        """验收(signature): pytest 摘要行提取
        test_name+exception_type。"""
        stderr = (
            "FAILED tests/test_auth.py::test_expired - "
            "AssertionError: expected retry==2\n"
        )
        sig = extract_failure_signature("", stderr)
        assert sig == "tests/test_auth.py::test_expired+AssertionError"

    def test_node_id_fallback(self) -> None:
        """验收(signature): 无摘要行时从 node id 兜底提取测试名。"""
        stderr = "E   ValueError: bad token\n  tests/test_x.py::test_b\n"
        sig = extract_failure_signature("", stderr)
        assert sig == "tests/test_x.py::test_b+ValueError"

    def test_exception_only(self) -> None:
        """验收(signature): 只有异常类型无测试名 → unknown+XXXError。"""
        sig = extract_failure_signature("", "RuntimeError: boom\n")
        assert sig == "unknown+RuntimeError"

    def test_no_failure_signal(self) -> None:
        """验收(signature): 完全无关输出 → None。"""
        assert extract_failure_signature("all passed", "") is None
        assert extract_failure_signature("", "") is None

    def test_test_name_without_exception(self) -> None:
        """验收(signature): 有测试名无异常词 → test_x+unknown。"""
        stderr = "FAILED tests/test_a.py::test_c - something went wrong\n"
        sig = extract_failure_signature("", stderr)
        assert sig == "tests/test_a.py::test_c+unknown"
