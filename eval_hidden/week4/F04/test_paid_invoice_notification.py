import json

from src.billing.webhooks import BillingWebhookController
from src.common.events import INVOICE_PAID, EventBus
from src.notifications.dispatcher import NotificationDispatcher


class AcceptingVerifier:
    def verify(self, payload: bytes, signature: str) -> bool:
        return True


class RecordingRepository:
    def __init__(self) -> None:
        self.retry_requests: list[str] = []

    def mark_retry_requested(self, invoice_id: str) -> None:
        self.retry_requests.append(invoice_id)


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict]] = []

    def send(self, to: str, template: str, context: dict) -> None:
        self.sent.append((to, template, context))


def test_verified_paid_invoice_webhook_notifies_customer() -> None:
    bus = EventBus()
    sender = RecordingSender()
    bus.subscribe(INVOICE_PAID, NotificationDispatcher(sender=sender).handle)
    repository = RecordingRepository()
    controller = BillingWebhookController(
        verifier=AcceptingVerifier(),
        repository=repository,
        event_bus=bus,
    )
    payload = {
        "type": "billing.invoice.paid",
        "data": {
            "invoice_id": "inv-1",
            "customer_email": "customer@example.com",
            "amount": 1500,
        },
    }

    response = controller.receive(json.dumps(payload).encode("utf-8"), "valid")

    assert response["status"] == 202
    assert sender.sent == [
        (
            "customer@example.com",
            "invoice_paid",
            payload["data"],
        )
    ]
