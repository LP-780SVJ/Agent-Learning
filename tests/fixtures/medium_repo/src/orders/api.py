"""Orders API boundary."""

from src.orders.service import OrderService


class OrderController:
    """Controller for order endpoints."""

    def __init__(self, service: OrderService | None = None) -> None:
        self.service = service or OrderService()

    def cancel(self, request: dict) -> dict:
        order_id = request["order_id"]
        result = self.service.cancel_order(order_id, request.get("reason", "customer_request"))
        return {"status": 200, "body": result}

