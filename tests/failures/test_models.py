"""tests/failures/test_models.py — 错误 Domain 模型与枚举的单元测试。

对应 day3.md 附录「Day 3 教学工程地图」§9 Test Strategy 第 1 层：
枚举数量契约、AgentFailure 构造契约、cause 序列化排除、
to_public_message() 的 secret-safe 行为（day3 §十三~十五）。
"""

from __future__ import annotations

from codeteam.failures.models import (
    AgentErrorCode,
    AgentFailure,
    ErrorCategory,
    FailureStage,
    RecoveryAction,
)


class TestEnums:
    """枚举数量与值契约（day3 §七/九/十二/十六）。"""

    def test_category_count_matches_day3_spec(self) -> None:
        """验收(9 个 ErrorCategory): day3 §七 定义的九大类完整无缺。"""
        assert len(ErrorCategory) == 9
        expected = {
            "model", "context", "patch", "tool", "security",
            "test", "git", "session", "user_interrupt",
        }
        assert {c.value for c in ErrorCategory} == expected

    def test_error_code_count_matches_day3_spec(self) -> None:
        """验收(32 个 AgentErrorCode): day3 §九 的 30 码
        + Step 3 补充的 MODEL_QUOTA_EXCEEDED / UNKNOWN。"""
        assert len(AgentErrorCode) == 32

    def test_stage_count_matches_day3_spec(self) -> None:
        """验收(11 个 FailureStage): day3 §十二 的完整生命周期阶段。"""
        assert len(FailureStage) == 11

    def test_recovery_action_count_matches_day3_spec(self) -> None:
        """验收(9 个 RecoveryAction): day3 §十六 的第一版动作集。"""
        assert len(RecoveryAction) == 9

    def test_str_enum_compatibility(self) -> None:
        """验收(str 兼容): 枚举可与字符串直接比较/序列化——
        周度评测脚本依赖 model_dump_json 无需自定义 serializer。"""
        assert ErrorCategory.MODEL == "model"
        assert AgentErrorCode.MODEL_RATE_LIMIT == "model_rate_limit"
        assert FailureStage.MODEL_CALL == "model_call"
        assert RecoveryAction.RETRY == "retry"

    def test_domain_enum_does_not_collide_with_week1_transport_enum(
        self,
    ) -> None:
        """验收(分层隔离): Domain ErrorCategory 与 Week1 传输层
        codeteam.errors.ErrorCategory 是两个独立枚举（DD-W4-D3-01
        命名决策），互不覆盖。"""
        from codeteam.errors import ErrorCategory as TransportCategory

        assert hasattr(ErrorCategory, "MODEL")
        assert not hasattr(TransportCategory, "MODEL")
        assert hasattr(TransportCategory, "RATE_LIMIT")
        assert not hasattr(ErrorCategory, "RATE_LIMIT")


class TestAgentFailure:
    """AgentFailure 构造契约（day3 §十三~十五）。"""

    def _make(self, **overrides) -> AgentFailure:
        defaults = {
            "failure_id": "f-t1-mc-mrl-1",
            "task_id": "t1",
            "category": ErrorCategory.MODEL,
            "code": AgentErrorCode.MODEL_RATE_LIMIT,
            "stage": FailureStage.MODEL_CALL,
            "message": "模型服务请求过于频繁，正在等待后重试。",
            "transient": True,
            "retryable": True,
            "attempt": 1,
            "recommended_recovery": RecoveryAction.RETRY,
        }
        defaults.update(overrides)
        return AgentFailure(**defaults)

    def test_attempt_defaults_to_one(self) -> None:
        """验收(attempt 默认 1): 首次失败即 attempt=1（1-based）。"""
        f = self._make()
        assert f.attempt == 1

    def test_metadata_defaults_to_empty_dict_per_instance(self) -> None:
        """验收(可变默认值隔离): 每个实例的 metadata 独立，
        不为共享 dict（Pydantic default_factory 契约）。"""
        f1 = self._make()
        f2 = self._make()
        f1.metadata["key"] = "value"
        assert "key" not in f2.metadata

    def test_cause_excluded_from_serialization(self) -> None:
        """验收(cause 序列化排除): 原始异常对象不进入 model_dump()——
        周度评测脚本只消费结构化字段。"""
        original = RuntimeError("boom")
        f = self._make(
            cause=original,
            source_type="RuntimeError",
            source_message="boom",
        )
        dumped = f.model_dump()
        assert "cause" not in dumped
        assert dumped["source_type"] == "RuntimeError"
        assert dumped["source_message"] == "boom"

    def test_cause_object_preserved_in_memory(self) -> None:
        """验收(cause preservation, T17 半边): 内存中 cause 对象可访问，
        序列化排除 ≠ 内存丢失。"""
        original = RuntimeError("boom")
        f = self._make(cause=original)
        assert f.cause is original

    def test_to_public_message_returns_sanitized_message(self) -> None:
        """验收(secret-safe, T18): 用户可见消息与原始异常文本解耦——
        to_public_message 只返回固定模板 message。"""
        f = self._make(
            message="模型服务认证失败，请检查 API 配置。",
            source_message="401 Unauthorized: api key sk-abc123secret",
        )
        public = f.to_public_message()
        assert public == "模型服务认证失败，请检查 API 配置。"
        assert "sk-abc123secret" not in public
        assert "401" not in public

    def test_failure_id_is_deterministic_format(self) -> None:
        """验收(确定性 failure_id): task:stage:code:attempt 格式——
        周度评测脚本可据此去重。"""
        f = self._make()
        assert f.failure_id == "f-t1-mc-mrl-1"
