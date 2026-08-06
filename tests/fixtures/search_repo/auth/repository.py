"""User repository module."""


class UserRepository:
    """Database access layer for user records."""

    def find_by_id(self, user_id: int) -> dict | None:
        return None

    def find_by_email(self, email: str) -> dict | None:
        return None

    def save(self, user: dict) -> dict:
        value = foo(bar)[0]
        return user
