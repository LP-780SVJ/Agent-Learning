"""Background order workers."""

from src.common.events import EventEnvelope, ORDER_CANCELLED
from src.inventory.service import InventoryService


class OrderEventWorker:
    """Consumes order events."""

    def __init__(self, inventory: InventoryService | None = None) -> None:
        self.inventory = inventory or InventoryService()

    def handle(self, event: EventEnvelope) -> None:
        if event.name == ORDER_CANCELLED:
            self.inventory.release_for_order(event.payload["order_id"])

