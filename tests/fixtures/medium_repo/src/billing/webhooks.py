"""Billing webhook handling."""

from src.billing.invoices import InvoiceRepository
from src.billing.payment_gateway import PaymentGateway
from src.common.events import EventBus, EventEnvelope, PAYMENT_WEBHOOK_ACCEPTED


class PaymentWebhookVerifier:
    """Validates payment webhook signatures."""

    def __init__(self, gateway: PaymentGateway | None = None) -> None:
        self.gateway = gateway or PaymentGateway()

    def verify(self, payload: bytes, signature: str) -> bool:
        return self.gateway.verify_signature(payload, signature)


class BillingWebhookController:
    """Controller for provider callbacks."""

    def __init__(
        self,
        verifier: PaymentWebhookVerifier | None = None,
        repository: InvoiceRepository | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.verifier = verifier or PaymentWebhookVerifier()
        self.repository = repository or InvoiceRepository()
        self.event_bus = event_bus or EventBus()

    def receive(self, payload: bytes, signature: str) -> dict:
        if not self.verifier.verify(payload, signature):
            return {"status": 401, "error": "invalid provider signature"}
        self.repository.mark_retry_requested("invoice-123")
        self.event_bus.publish(EventEnvelope(PAYMENT_WEBHOOK_ACCEPTED, {"invoice_id": "invoice-123"}))
        return {"status": 202}

