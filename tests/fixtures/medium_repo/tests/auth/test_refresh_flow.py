"""Auth refresh flow tests."""

from src.auth.api import AuthController


def test_expired_refresh_returns_401() -> None:
    controller = AuthController()
    response = controller.refresh({"refresh_token": "expired"})
    assert response["status"] == 401

