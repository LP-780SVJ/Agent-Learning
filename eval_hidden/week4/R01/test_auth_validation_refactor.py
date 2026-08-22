from pathlib import Path


def test_auth_validation_is_extracted_to_private_helper() -> None:
    source = Path("src/auth/service.py").read_text(encoding="utf-8")

    assert "def _" in source
    assert "_validate_refresh" in source or "_decode_refresh" in source
    assert "refresh_session" in source
    assert "revoke_session" in source
