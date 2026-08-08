"""Payment provider abstraction."""

from vendor.third_party_payment import ProviderClient


class PaymentGateway:
    """Wraps the vendored provider client."""

    def __init__(self, client: ProviderClient | None = None) -> None:
        self.client = client or ProviderClient()

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        return self.client.verify(payload, signature)

    def charge(self, customer_id: str, cents: int) -> dict:
        return self.client.charge(customer_id, cents)

