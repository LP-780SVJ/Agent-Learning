"""Invoice retry policy."""

from dataclasses import dataclass

from src.common.settings import load_retry_policy


@dataclass(frozen=True)
class InvoiceRetryPolicy:
    initial_delay_seconds: int
    max_attempts: int
    backoff_multiplier: int


def load_invoice_retry_policy() -> InvoiceRetryPolicy:
    raw = load_retry_policy()
    return InvoiceRetryPolicy(
        initial_delay_seconds=raw["initial_delay_seconds"],
        max_attempts=raw["max_attempts"],
        backoff_multiplier=raw.get("backoff_multiplier", 2),
    )

