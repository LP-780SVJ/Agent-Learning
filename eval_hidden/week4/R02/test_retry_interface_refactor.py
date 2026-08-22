from pathlib import Path


def test_billing_retry_has_small_execution_interface() -> None:
    source = Path("src/billing/retries.py").read_text(encoding="utf-8")

    assert "Protocol" in source or "ABC" in source or "RetryExecutor" in source
    assert "load_invoice_retry_policy" in source
    assert "InvoiceRetryPolicy" in source
