"""Domain event primitives."""

from dataclasses import dataclass
from typing import Callable


ORDER_CANCELLED = "order.cancelled"
PAYMENT_WEBHOOK_ACCEPTED = "billing.webhook.accepted"
INVOICE_RETRY_REQUESTED = "billing.invoice.retry_requested"


@dataclass(frozen=True)
class EventEnvelope:
    """Event wrapper shared by producers and consumers."""

    name: str
    payload: dict


class EventBus:
    """In-memory event bus for the fixture."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[EventEnvelope], None]]] = {}

    def subscribe(self, name: str, handler: Callable[[EventEnvelope], None]) -> None:
        self._handlers.setdefault(name, []).append(handler)

    def publish(self, event: EventEnvelope) -> None:
        for handler in self._handlers.get(event.name, []):
            handler(event)

