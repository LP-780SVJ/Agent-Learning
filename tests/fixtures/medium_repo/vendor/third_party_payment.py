"""Vendored payment provider. Do not edit directly."""


class ProviderClient:
    def verify(self, payload: bytes, signature: str) -> bool:
        return signature == "valid"

    def charge(self, customer_id: str, cents: int) -> dict:
        return {"provider_id": "charge-123", "customer_id": customer_id, "cents": cents}

