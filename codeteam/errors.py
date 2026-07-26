from dataclasses import dataclass
from enum import Enum

class ErrorCategory(str, Enum):
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    AUTH = "auth"
    API = "api"
    VALIDATION = "validation"
    TOOL = "tool"
    FILE_NOT_FOUND = "file_not_found"
    UNKNOWN = "unknown"


@dataclass
class AgentError:# 统一错误对象
    category: ErrorCategory
    message: str    # 错误说明
    retryable: bool = False # 错误能否重试
    feedback_to_model: bool = False # 错误是否要反馈给模型修正

def should_retry(error: AgentError) -> bool:
    return error.retryable

def classify_exception(error: Exception) -> AgentError:
    message = str(error)
    status_code = getattr(error, "status_code", None)


    # RATE_LIMIT
    # API 限流，通常是 HTTP 429。意思是请求太频繁了。
    # 可重试，等一会儿再试。
    if status_code == 429:
        return AgentError(
            category=ErrorCategory.RATE_LIMIT,
            message=message,
            retryable=True,
        )

    # TIMEOUT
    # 请求超时，比如网络慢、服务没及时响应。
    # 可重试，因为可能只是临时问题。
    if isinstance(error, TimeoutError):
        return AgentError(
            category=ErrorCategory.TIMEOUT,
            message=message,
            retryable=True,
        )

    # 可重试的 API 错误
    if status_code in {500, 502, 503}:
        return AgentError(
            category=ErrorCategory.API,
            message=message,
            retryable=True,
        )

    # AUTH
    # 认证错误，比如 API Key 无效、没权限，常见状态码 401 / 403。
    # 不可重试，因为重试也不会突然有权限。
    if status_code in {401, 403} or "api key" in message.lower():
        return AgentError(
            category=ErrorCategory.AUTH,
            message=message,
            retryable=False,
        )

    # FILE_NOT_FOUND
    # 文件不存在，比如读取 missing.txt。
    # 不可重试 API，但应该反馈给模型，让模型换路径或先列目录。
    if isinstance(error, FileNotFoundError):
        return AgentError(
            category=ErrorCategory.FILE_NOT_FOUND,
            message=message,
            retryable=False,
            feedback_to_model=True,
        )

    # VALIDATION
    # 参数或结构不合法，比如工具参数错、模型输出字段错。
    # 不可重试 API，应该修正输入。
    if isinstance(error, ValueError):
        return AgentError(
            category=ErrorCategory.VALIDATION,
            message=message,
            retryable=False,
        )

    # UNKNOWN
    # 没识别出来的其他错误。
    # 默认 不可重试，避免盲目循环。
    return AgentError(
        category=ErrorCategory.UNKNOWN,
        message=message,
        retryable=False,
    )
