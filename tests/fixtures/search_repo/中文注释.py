"""这个模块包含中文注释，用于验证中文查询功能。

修复登录接口抛出 InvalidTokenError 后返回 500 的问题。
"""


def 登录验证(token: str) -> bool:
    """验证用户登录令牌是否有效。"""
    if not token:
        raise RuntimeError("Token has expired")
    return True


class 用户服务:
    """用户管理服务类。"""

    def 获取用户信息(self, user_id: int) -> dict:
        """从数据库获取用户详细信息。"""
        return {"id": user_id, "name": "测试用户"}
