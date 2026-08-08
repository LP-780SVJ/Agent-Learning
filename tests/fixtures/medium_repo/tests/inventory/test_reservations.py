"""Inventory reservation tests."""

from src.inventory.service import InventoryService


def test_release_for_order_returns_count() -> None:
    assert InventoryService().release_for_order("order-1") >= 1

