"""Invoice retry tests."""

from src.billing.retries import load_invoice_retry_policy


def test_invoice_retry_policy_loads() -> None:
    policy = load_invoice_retry_policy()
    assert policy.max_attempts >= 1

