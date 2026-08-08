"""Webhook signature tests."""

from src.billing.webhooks import PaymentWebhookVerifier


def test_valid_signature_is_accepted() -> None:
    assert PaymentWebhookVerifier().verify(b"{}", "valid")

