"""tests/failures/test_fault_injection.py — 50 Case 数据驱动正确性测试。

对应 day3.md §六十七~六十九：
每个 Case 断言 expected category/code/action/retryable 四元组。
这是 classifier 级正确性测试——周度评测只读本 corpus 做 Accuracy
汇总，今天只做全绿断言（验收标准 3/9）。

分布断言按 case_id 前缀（day3 §六十九 的 9 个 section）：
M=10 C=6 P=7 T=6 S=6 V=5 G=4 N=4 U=2 → 50。
"""

from __future__ import annotations

import pytest

from codeteam.failures.classifier import ErrorClassifier
from tests.failures.fault_cases import FAILURE_CASES, FailureCase

# 9 个 section 的期望数量（day3 §六十九）
_EXPECTED_SECTION_COUNTS = {
    "M": 10,  # MODEL
    "C": 6,   # CONTEXT
    "P": 7,   # PATCH
    "T": 6,   # TOOL
    "S": 6,   # SECURITY
    "V": 5,   # TEST
    "G": 4,   # GIT
    "N": 4,   # SESSION
    "U": 2,   # INTERRUPT
}


class TestCorpusCompleteness:
    """corpus 结构契约（周度评测脚本依赖此契约）。"""

    def test_total_case_count_is_50(self) -> None:
        """验收(50 条): corpus 总数 50，与 day3 §六十九 一致。"""
        assert len(FAILURE_CASES) == 50

    def test_section_distribution_matches_spec(self) -> None:
        """验收(分布): 9 个 section 各自数量与 day3 §六十九 一致。"""
        counts: dict[str, int] = {}
        for case in FAILURE_CASES:
            prefix = case.case_id[0]
            counts[prefix] = counts.get(prefix, 0) + 1
        assert counts == _EXPECTED_SECTION_COUNTS

    def test_case_ids_are_unique(self) -> None:
        """验收(case_id 唯一): 周度评测按 case_id 定位与去重。"""
        ids = [c.case_id for c in FAILURE_CASES]
        assert len(ids) == len(set(ids))

    def test_failure_case_fields_match_weekly_export_contract(self) -> None:
        """验收(周度数据出口): FailureCase 含六字段契约
        （case_id/stage/raw_error/expected_category/expected_code/
        expected_action/expected_retryable），周度脚本直接 import。"""
        case = FAILURE_CASES[0]
        assert isinstance(case, FailureCase)
        for field in (
            "case_id", "stage", "raw_error",
            "expected_category", "expected_code",
            "expected_action", "expected_retryable",
        ):
            assert hasattr(case, field), f"缺字段 {field}"


@pytest.fixture(scope="module")
def classifier() -> ErrorClassifier:
    return ErrorClassifier()


@pytest.mark.parametrize(
    "case",
    FAILURE_CASES,
    ids=[c.case_id for c in FAILURE_CASES],
)
def test_case_classifies_as_expected(
    case: FailureCase, classifier: ErrorClassifier
) -> None:
    """验收(50 Case 四元组): category/code/action/retryable
    全部与 day3 §七十~八十 的冻结预期一致。

    为什么能证明：deterministic classifier 对固定输入必须产出
    固定分类；任何一条不一致都意味着「底层故障 → Agent 行为」
    的语义层有回归。
    """
    failure = classifier.classify(
        error=case.raw_error,
        stage=case.stage,
        operation="corpus_op",
        task_id="fault-test",
        attempt=1,
    )
    assert failure.category == case.expected_category, (
        f"{case.case_id}: category={failure.category.value} "
        f"期望 {case.expected_category.value}"
    )
    assert failure.code == case.expected_code, (
        f"{case.case_id}: code={failure.code.value} "
        f"期望 {case.expected_code.value}"
    )
    assert failure.recommended_recovery == case.expected_action, (
        f"{case.case_id}: action={failure.recommended_recovery.value} "
        f"期望 {case.expected_action.value}"
    )
    assert failure.retryable is case.expected_retryable, (
        f"{case.case_id}: retryable={failure.retryable} "
        f"期望 {case.expected_retryable}"
    )
