from src.common.events import EventEnvelope
from src.notifications.dispatcher import NotificationDispatcher


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict]] = []

    def send(self, to: str, template: str, context: dict) -> None:
        self.sent.append((to, template, context))


def test_paid_invoice_event_notifies_customer() -> None:
    sender = RecordingSender()
    event = EventEnvelope(
        "billing.invoice.paid",
        {
            "invoice_id": "inv-1",
            "customer_email": "customer@example.com",
            "amount": 1500,
        },
    )

    NotificationDispatcher(sender=sender).handle(event)

    assert sender.sent == [
        (
            "customer@example.com",
            "invoice_paid",
            {
                "invoice_id": "inv-1",
                "customer_email": "customer@example.com",
                "amount": 1500,
            },
        )
    ]
