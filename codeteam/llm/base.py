from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from codeteam.schemas.messages import Message


@dataclass(frozen=True)
class ModelResponse:
    content: str
    model: str = "mock-model"
    input_tokens: int = 0
    output_tokens: int = 0

@runtime_checkable
class ModelClient(Protocol):
    """模型客户端的结构化契约（形式化既有 duck typing）。

    MockModelClient / OpenAICompatibleClient 无需继承即满足本 Protocol；
    AgentLoop 的 model_client 参数从 Any 升级为本类型后，
    静态检查器可捕获签名漂移（运行时行为零变化）。
    """

    def complete(self, messages: list[Message]) -> str:
        """发送消息序列，返回模型的原始文本响应。"""
        ...
