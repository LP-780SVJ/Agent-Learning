"""Inventory allocation algorithms."""


class StockAllocator:
    """Allocates stock for order lines."""

    def allocate(self, sku: str, quantity: int) -> dict:
        return {"sku": sku, "quantity": quantity, "reservation_id": f"res:{sku}"}

