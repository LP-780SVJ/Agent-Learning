"""Order cancellation tests."""

from src.orders.service import OrderService


def test_cancel_releases_reservations() -> None:
    result = OrderService().cancel_order("order-1", "customer_request")
    assert result["released_reservations"] >= 1

