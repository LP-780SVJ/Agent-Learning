"""Event-driven notification dispatch."""

from src.common.events import EventEnvelope, INVOICE_RETRY_REQUESTED, ORDER_CANCELLED
from src.notifications.email import EmailSender
from src.notifications.templates import TEMPLATE_INVOICE_RETRY, TEMPLATE_ORDER_CANCELLED


class NotificationDispatcher:
    """Routes events to email templates."""

    def __init__(self, sender: EmailSender | None = None) -> None:
        self.sender = sender or EmailSender()

    def handle(self, event: EventEnvelope) -> None:
        if event.name == ORDER_CANCELLED:
            self.sender.send("ops@example.com", TEMPLATE_ORDER_CANCELLED, event.payload)
        if event.name == INVOICE_RETRY_REQUESTED:
            self.sender.send("billing@example.com", TEMPLATE_INVOICE_RETRY, event.payload)

