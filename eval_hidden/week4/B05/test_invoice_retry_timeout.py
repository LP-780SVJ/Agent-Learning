import pytest
from src.billing import invoices


class TimeoutSession:
    def __init__(self) -> None:
        self.rolled_back = False

    def execute(self, query: str, params: dict | None = None):
        raise TimeoutError("gateway write timeout")

    def rollback(self) -> None:
        self.rolled_back = True


class SuccessfulSession:
    def __init__(self) -> None:
        self.executed = False

    def execute(self, query: str, params: dict | None = None) -> None:
        self.executed = True


def test_retry_request_timeout_does_not_leave_in_progress_state(monkeypatch) -> None:
    session = TimeoutSession()
    monkeypatch.setattr(invoices, "create_session", lambda: session)
    repository = invoices.InvoiceRepository()

    try:
        result = repository.mark_retry_requested("invoice-timeout")
    except TimeoutError:
        pytest.fail("retry timeout should be converted into a recoverable result")

    assert result is False
    assert session.rolled_back is True


def test_retry_request_success_returns_true(monkeypatch) -> None:
    session = SuccessfulSession()
    monkeypatch.setattr(invoices, "create_session", lambda: session)

    result = invoices.InvoiceRepository().mark_retry_requested("invoice-ok")

    assert result is True
    assert session.executed is True
