from src.auth.api import AuthController


def test_expired_refresh_token_returns_documented_auth_error() -> None:
    response = AuthController().refresh({"refresh_token": "expired"})

    assert response["status"] == 401
    assert "expired" in response["error"].lower()
    assert "server" not in response["error"].lower()


def test_missing_subject_still_uses_public_auth_error_contract() -> None:
    response = AuthController().refresh({"refresh_token": "missing-subject"})

    assert response["status"] == 400
    assert "subject" in response["error"].lower()
