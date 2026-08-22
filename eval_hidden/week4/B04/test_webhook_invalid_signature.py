from src.billing.webhooks import BillingWebhookController


class RejectingVerifier:
    def verify(self, payload: bytes, signature: str) -> bool:
        return False


class ExplodingRepository:
    def mark_retry_requested(self, invoice_id: str) -> None:
        raise AssertionError("invalid webhook must not mutate invoice state")


class RecordingBus:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


def test_invalid_signature_rejects_without_downstream_effects() -> None:
    bus = RecordingBus()
    controller = BillingWebhookController(
        verifier=RejectingVerifier(),
        repository=ExplodingRepository(),
        event_bus=bus,
    )

    response = controller.receive(b"{}", "bad")

    assert response["status"] == 401
    assert "signature" in response["error"].lower()
    assert bus.events == []
