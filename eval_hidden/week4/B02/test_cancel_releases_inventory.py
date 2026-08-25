from src.orders.service import OrderService


class RecordingInventory:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self.released_order_ids: list[str] = []

    def release_for_order(self, order_id: str) -> int:
        self.trace.append("release")
        self.released_order_ids.append(order_id)
        return 2


class RecordingBus:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.trace.append("publish")
        self.events.append(event)


def test_cancel_order_releases_inventory_before_returning() -> None:
    trace: list[str] = []
    inventory = RecordingInventory(trace)
    bus = RecordingBus(trace)

    result = OrderService(event_bus=bus, inventory=inventory).cancel_order(
        "order-42",
        "customer_request",
    )

    assert inventory.released_order_ids == ["order-42"]
    assert result["released_reservations"] == 2
    assert len(bus.events) == 1
    assert trace == ["release", "publish"]
