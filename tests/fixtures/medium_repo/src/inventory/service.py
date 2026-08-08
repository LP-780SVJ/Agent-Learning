"""Inventory service facade."""

from src.inventory.allocator import StockAllocator
from src.inventory.reservations import InventoryReservationStore


class InventoryService:
    """Coordinates inventory allocation and release."""

    def __init__(
        self,
        allocator: StockAllocator | None = None,
        reservations: InventoryReservationStore | None = None,
    ) -> None:
        self.allocator = allocator or StockAllocator()
        self.reservations = reservations or InventoryReservationStore()

    def reserve_for_order(self, order_id: str, sku: str, quantity: int) -> dict:
        allocation = self.allocator.allocate(sku, quantity)
        return {"order_id": order_id, **allocation}

    def release_for_order(self, order_id: str) -> int:
        reservations = self.reservations.find_for_order(order_id)
        for reservation in reservations:
            self.reservations.mark_released(reservation.reservation_id)
        return len(reservations)

