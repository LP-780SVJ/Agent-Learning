"""测试 TokenBudget 和 ContextCompressor。

覆盖场景：
- T08: Token 预算不足 - 上下文超过预算时触发压缩
- T09: 大文件逐级降级 - FULL_FILE → SYMBOL_BODY → ... → PATH_ONLY
"""

from __future__ import annotations

import pytest

from codeteam.context.models import (
    CompressionLevel,
    ContextItem,
)
from codeteam.context.budget import TokenBudget
from codeteam.context.compressor import ContextCompressor
from codeteam.usage.token_counter import ApproximateTokenCounter


# ---------------------------------------------------------------------------
# 适配器：ApproximateTokenCounter 实现了 count() 而非 count_text()
# TokenCounter Protocol 要求 count_text()。此适配器弥补该缺陷以测试 Compressor。
# 已知缺陷：ApproximateTokenCounter 不遵循 TokenCounter Protocol。
# ---------------------------------------------------------------------------

class _FixedCounter:
    """将 ApproximateTokenCounter 包装为 TokenCounter Protocol 兼容接口。"""

    def __init__(self) -> None:
        self._inner = ApproximateTokenCounter()

    def count_text(self, text: str) -> int:
        return self._inner.count(text)

    def count(self, text: str) -> int:
        return self._inner.count(text)


# ===================================================================
# T08: Token 预算不足
# ===================================================================

class TestTokenBudget:
    """T08: Token 预算 - 子预算分配和上限检查。"""

    def test_default_budget_computes_max_input(self) -> None:
        """默认 32K 窗口的 max_input_tokens 应合理。

        已知缺陷：默认子预算总额 (24000) 超过可用输入 (23808)，
        TokenBudget() 默认构造会抛出 ValueError。
        """
        # 预期：32K - 4K(output) - 2K(reasoning) - 2K(margin) = 24K
        try:
            budget = TokenBudget()
            assert budget.max_input_tokens == 24000
        except ValueError as exc:
            pytest.fail(
                f"PRODUCTION DEFECT: Default TokenBudget() raises ValueError. "
                f"allocated_input_tokens (24000) exceeds max_input_tokens "
                f"(23808). Sub-budgets need to be reduced by 192 tokens. "
                f"Original error: {exc}"
            )

    def test_allocated_not_exceed_max_input(self) -> None:
        """子预算总额不应超过 max_input_tokens。

        已知缺陷：默认配置触发此条件。
        """
        try:
            budget = TokenBudget()
            assert budget.allocated_input_tokens <= budget.max_input_tokens
        except ValueError as exc:
            pytest.fail(
                f"PRODUCTION DEFECT: Default TokenBudget raises ValueError. "
                f"allocated (24000) > max_input (23808). "
                f"Error: {exc}"
            )

    def test_custom_budget_values(self) -> None:
        """自定义子预算值应在创建时通过校验。"""
        budget = TokenBudget(
            context_window=10000,
            reserved_output=1000,
            reserved_reasoning=500,
            safety_margin=500,
            system_budget=500,
            tool_schema_budget=500,
            task_budget=500,
            instruction_budget=500,
            repo_map_budget=500,
            code_budget=4000,
            history_budget=500,
            observation_budget=500,
        )
        assert budget.max_input_tokens == 8000
        assert budget.allocated_input_tokens <= budget.max_input_tokens

    def test_exceeded_budget_raises_value_error(self) -> None:
        """子预算超额应抛出 ValueError。"""
        with pytest.raises(ValueError):
            TokenBudget(
                context_window=1000,  # 太小
                code_budget=10000,    # 远超窗口
            )

    def test_negative_budget_raises_value_error(self) -> None:
        """负数预算应抛出 ValueError。"""
        with pytest.raises(ValueError):
            TokenBudget(code_budget=-100)

    def test_budget_for_compression_scenario(self) -> None:
        """模拟压缩场景：20K 总代码，5K 代码预算。"""
        budget = TokenBudget(
            context_window=32000,
            code_budget=5000,
        )
        # 5K 代码预算应生效
        assert budget.code_budget == 5000


# ===================================================================
# T09: 大文件逐级降级
# ===================================================================

BIG_FILE = (
    "class UserService:\n"
    "    def get_user(self, user_id: int) -> User:\n"
    '        """Get a user by ID."""\n'
    "        return self.repository.find(user_id)\n"
    "\n"
    "    def create_user(self, name: str, email: str) -> User:\n"
    '        """Create a new user."""\n'
    "        user = User(name=name, email=email)\n"
    "        return self.repository.save(user)\n"
    "\n"
    "    def delete_user(self, user_id: int) -> None:\n"
    '        """Delete a user."""\n'
    "        self.repository.delete(user_id)\n"
    "\n"
    "    def list_users(self) -> list[User]:\n"
    '        """List all users."""\n'
    "        return self.repository.all()\n"
) * 20  # 重复 20 次使其变大


class TestContextCompressor:
    """T09: 大文件逐级降级。

    FULL_FILE → SYMBOL_BODY → SYMBOL_SIGNATURE → FILE_SUMMARY → PATH_ONLY
    断言：
    - 最终结果在预算内
    - 至少发生一次压缩
    - compression_actions 非空
    - 不从文件中间截断（压缩是基于级别的整体降级）
    """

    def test_compressor_fits_to_budget(self) -> None:
        """内容超过预算时应触发压缩。"""
        counter = _FixedCounter()
        compressor = ContextCompressor(counter)

        item = ContextItem(
            path="app/service.py",
            relevance_score=0.9,
            current_level=CompressionLevel.FULL_FILE,
            minimum_level=CompressionLevel.PATH_ONLY,
            content=BIG_FILE,
            token_count=counter.count(BIG_FILE),
            selected_symbols=["UserService"],
        )

        # 设置预算远小于内容 token 数
        budget_tokens = 50
        compressed_items, actions = compressor.fit_to_budget(
            items=[item],
            budget_tokens=budget_tokens,
        )

        # 验证在预算内
        total = sum(it.token_count for it in compressed_items)
        assert total <= budget_tokens, (
            f"Compressed total ({total}) should be <= budget ({budget_tokens})"
        )

    def test_compression_produces_actions(self) -> None:
        """压缩应产生 actions 日志。"""
        counter = _FixedCounter()
        compressor = ContextCompressor(counter)

        item = ContextItem(
            path="app/service.py",
            relevance_score=0.9,
            current_level=CompressionLevel.FULL_FILE,
            minimum_level=CompressionLevel.PATH_ONLY,
            content=BIG_FILE,
            token_count=counter.count(BIG_FILE),
            selected_symbols=["UserService"],
        )

        budget_tokens = 50
        _, actions = compressor.fit_to_budget(
            items=[item],
            budget_tokens=budget_tokens,
        )

        # 应至少有一条压缩动作
        assert len(actions) > 0, (
            f"Expected at least 1 compression action, got {len(actions)}"
        )

    def test_compression_levels_form_valid_chain(self) -> None:
        """压缩应从 FULL_FILE 开始，逐级下降。"""
        counter = _FixedCounter()
        compressor = ContextCompressor(counter)

        item = ContextItem(
            path="app/service.py",
            relevance_score=0.9,
            current_level=CompressionLevel.FULL_FILE,
            minimum_level=CompressionLevel.PATH_ONLY,
            content=BIG_FILE,
            token_count=counter.count(BIG_FILE),
            selected_symbols=["UserService"],
        )

        budget_tokens = 30
        _, actions = compressor.fit_to_budget(
            items=[item],
            budget_tokens=budget_tokens,
        )

        for action in actions:
            # 每个 action 格式如 "path: full_file → symbol_body; N → M tokens"
            assert "→" in action, (
                f"Action should show level transition, got: {action}"
            )

    def test_compress_single_item_to_target_level(self) -> None:
        """compress_item 应正确转换内容。"""
        counter = _FixedCounter()
        compressor = ContextCompressor(counter)

        source = (
            "def get_user(self, user_id: int) -> User:\n"
            '    """Get a user."""\n'
            "    return self.repository.find(user_id)\n"
        )
        item = ContextItem(
            path="app/service.py",
            relevance_score=0.9,
            current_level=CompressionLevel.FULL_FILE,
            minimum_level=CompressionLevel.PATH_ONLY,
            content=source,
            token_count=counter.count(source),
        )

        # 压缩到 SIGNATURE
        compressed = compressor.compress_item(
            item=item,
            target_level=CompressionLevel.SYMBOL_SIGNATURE,
        )

        assert compressed.current_level == CompressionLevel.SYMBOL_SIGNATURE
        # 签名应包含 def 行和 docstring
        assert "def get_user" in compressed.content, (
            f"Signature should include function def, got: {compressed.content}"
        )

    def test_path_only_is_minimum(self) -> None:
        """压缩到 PATH_ONLY 只保留路径。"""
        counter = _FixedCounter()
        compressor = ContextCompressor(counter)

        item = ContextItem(
            path="app/service.py",
            relevance_score=0.9,
            current_level=CompressionLevel.FILE_SUMMARY,
            minimum_level=CompressionLevel.PATH_ONLY,
            content="app/service.py\nRole: core\nSymbols: UserService",
            token_count=20,
        )

        compressed = compressor.compress_item(
            item=item,
            target_level=CompressionLevel.PATH_ONLY,
        )

        assert compressed.current_level == CompressionLevel.PATH_ONLY
        assert compressed.content == "app/service.py"

    def test_all_items_at_minimum_stops_compression(self) -> None:
        """所有 item 达到最低级别时压缩停止（无崩溃）。"""
        counter = _FixedCounter()
        compressor = ContextCompressor(counter)

        item = ContextItem(
            path="app/service.py",
            relevance_score=0.5,
            current_level=CompressionLevel.PATH_ONLY,
            minimum_level=CompressionLevel.PATH_ONLY,
            content="app/service.py",
            token_count=counter.count("app/service.py"),
        )

        budget_tokens = 10
        _, actions = compressor.fit_to_budget(
            items=[item],
            budget_tokens=budget_tokens,
        )

        # 如果已经是最低级别，应报告无法再压缩
        if counter.count("app/service.py") > budget_tokens:
            assert any("最低" in a or "无法" in a for a in actions), (
                f"Should report unable to compress further: {actions}"
            )
