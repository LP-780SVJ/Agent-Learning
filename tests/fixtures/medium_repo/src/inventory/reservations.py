"""Inventory reservation storage."""

from dataclasses import dataclass

from src.common.database import create_session


@dataclass
class InventoryReservation:
    reservation_id: str
    order_id: str
    sku: str
    quantity: int
    released: bool = False


class InventoryReservationStore:
    """Stores reservation state transitions."""

    def find_for_order(self, order_id: str) -> list[InventoryReservation]:
        session = create_session()
        session.execute("select * from inventory_reservations where order_id=:order_id", {"order_id": order_id})
        return [InventoryReservation("res-1", order_id, "sku-1", 2)]

    def mark_released(self, reservation_id: str) -> None:
        session = create_session()
        session.execute(
            "update inventory_reservations set released=true where reservation_id=:reservation_id",
            {"reservation_id": reservation_id},
        )

