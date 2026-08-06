"""Tests for codeteam.repomap.budget — TokenBudget。

验证 Token 预算管理：count, add, can_add, used, remaining。
"""

from __future__ import annotations

import pytest

from codeteam.repomap.budget import TokenBudget


class TestTokenBudget:
    """TokenBudget 核心行为。"""

    def test_initial_values(self) -> None:
        """初始值：used=0, remaining=limit。"""
        budget = TokenBudget(limit=1024)
        assert budget.used == 0
        assert budget.remaining == 1024

    def test_add_increases_used(self) -> None:
        """add 后 used 增加，remaining 减少。"""
        budget = TokenBudget(limit=1024)
        budget.add("hello world")
        assert budget.used > 0
        assert budget.remaining < 1024

    def test_can_add_when_within_budget(self) -> None:
        """预算内 → can_add 返回 True。"""
        budget = TokenBudget(limit=10000)
        assert budget.can_add("short text")

    def test_cannot_add_when_exceeded_budget(self) -> None:
        """预算是够小时 → can_add 返回 False。"""
        budget = TokenBudget(limit=2)
        assert not budget.can_add("this is a long text that exceeds budget")

    def test_count_returns_positive_for_nonempty(self) -> None:
        """非空文本 count > 0。"""
        budget = TokenBudget()
        assert budget.count("hello") > 0

    def test_count_returns_zero_for_empty(self) -> None:
        """空文本 count == 0。"""
        budget = TokenBudget()
        assert budget.count("") == 0

    def test_reset_clears_used(self) -> None:
        """reset 后 used 回到 0。"""
        budget = TokenBudget(limit=1024)
        budget.add("hello world")
        assert budget.used > 0

        budget.reset()
        assert budget.used == 0
        assert budget.remaining == 1024

    def test_remaining_never_negative(self) -> None:
        """remaining 最小为 0，不为负数。"""
        budget = TokenBudget(limit=5)
        budget.add("a" * 1000)  # 远超预算
        assert budget.remaining >= 0


class TestTokenBudgetParametrized:
    """参数化测试：不同预算值。"""

    @pytest.mark.parametrize("limit", [128, 256, 512, 1024])
    def test_budget_respected(self, limit: int) -> None:
        """各预算值下 add 后 used ≤ limit。"""
        budget = TokenBudget(limit=limit)
        text = "def example_function(arg1: str, arg2: int) -> bool: pass"
        budget.add(text)
        assert budget.used <= limit, (
            f"Used {budget.used} exceeds limit {limit}"
        )
