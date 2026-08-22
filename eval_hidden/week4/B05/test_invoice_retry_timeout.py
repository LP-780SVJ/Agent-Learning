import pytest
from src.billing import invoices


class TimeoutSession:
    def execute(self, query: str, params: dict | None = None):
        raise TimeoutError("gateway write timeout")


def test_retry_request_timeout_does_not_leave_in_progress_state(monkeypatch) -> None:
    monkeypatch.setattr(invoices, "create_session", lambda: TimeoutSession())
    repository = invoices.InvoiceRepository()

    try:
        result = repository.mark_retry_requested("invoice-timeout")
    except TimeoutError:
        pytest.fail("retry timeout should be converted into a recoverable result")

    assert result is False
