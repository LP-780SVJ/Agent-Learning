from src.inventory.reservations import InventoryReservation
from src.inventory.service import InventoryService


class FakeReservationStore:
    def __init__(self) -> None:
        self.records = {
            "res-active": InventoryReservation("res-active", "order-1", "sku-1", 1, released=False),
            "res-released": InventoryReservation("res-released", "order-1", "sku-1", 1, released=True),
        }

    def find_by_id(self, reservation_id: str) -> InventoryReservation | None:
        return self.records.get(reservation_id)


def test_public_helper_reports_active_reservation() -> None:
    service = InventoryService(reservations=FakeReservationStore())

    assert service.is_reservation_active("res-active") is True
    assert service.is_reservation_active("res-released") is False
    assert service.is_reservation_active("missing") is False
