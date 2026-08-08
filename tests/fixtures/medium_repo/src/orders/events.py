"""Order events."""

from src.common.events import EventEnvelope, ORDER_CANCELLED


def order_cancelled_event(order_id: str, reason: str) -> EventEnvelope:
    return EventEnvelope(
        name=ORDER_CANCELLED,
        payload={"order_id": order_id, "reason": reason},
    )

