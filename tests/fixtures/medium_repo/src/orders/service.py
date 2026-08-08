"""Order business logic."""

from src.common.events import EventBus
from src.inventory.service import InventoryService
from src.orders.events import order_cancelled_event


class OrderService:
    """Coordinates order state transitions."""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        inventory: InventoryService | None = None,
    ) -> None:
        self.event_bus = event_bus or EventBus()
        self.inventory = inventory or InventoryService()

    def cancel_order(self, order_id: str, reason: str) -> dict:
        released = self.inventory.release_for_order(order_id)
        self.event_bus.publish(order_cancelled_event(order_id, reason))
        return {"order_id": order_id, "released_reservations": released}

    def create_order(self, order_id: str, sku: str, quantity: int) -> dict:
        reservation = self.inventory.reserve_for_order(order_id, sku, quantity)
        return {"order_id": order_id, "reservation": reservation}

