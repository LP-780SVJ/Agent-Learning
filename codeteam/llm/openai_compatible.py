'''
429 -> 重试
timeout -> 重试
500/502/503 -> 重试
401/403/API Key 错误 -> 不重试
400 参数错误 -> 不重试

重试等待时间是指数退避:

delay = base_delay_seconds * (2 ** retry_index)

第 1 次失败后等 0.5 秒
第 2 次失败后等 1.0 秒
第 3 次失败后等 2.0 秒
'''

import time
from dataclasses import dataclass
from typing import Callable

from codeteam.errors import classify_exception, should_retry
from codeteam.schemas.messages import Message

@dataclass(frozen=True)
class RetryConfig:
    max_retries: int = 3
    base_delay_seconds: float = 0.5


class OpenAICompatibleClient:
    def __init__(
        self,
        model: str,# 模型名
        request_func: Callable[[list[Message]], str],# 真正发送请求的函数
        retry_config: RetryConfig | None = None,# 重试配置
        sleep_func: Callable[[float], None] = time.sleep,# 等待函数
    ) -> None:
        self.model = model
        self.request_func = request_func
        self.retry_config = retry_config or RetryConfig()
        self.sleep_func = sleep_func

    def complete(self, messages: list[Message]) -> str:
        retry_index = 0

        while True:
            try:
                return self.request_func(messages)
            except Exception as error:
                agent_error = classify_exception(error)

                if not should_retry(agent_error):
                    raise error

                if retry_index >= self.retry_config.max_retries:
                    raise error

                delay = self.retry_config.base_delay_seconds * (2 ** retry_index)
                self.sleep_func(delay)
                retry_index += 1