from src.billing.payment_gateway import PaymentGateway
from src.billing.retries import InvoiceRetryPolicy, RetryExecutor


class StaticPolicyProvider:
    def get_policy(self, invoice: dict) -> InvoiceRetryPolicy:
        return InvoiceRetryPolicy(
            initial_delay_seconds=0,
            max_attempts=2,
            backoff_multiplier=1,
        )


class FlakyExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, invoice: dict) -> dict:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary provider failure")
        return {"provider_id": "recovered", **invoice}


def test_payment_gateway_uses_injected_retry_contract() -> None:
    executor: RetryExecutor = FlakyExecutor()
    gateway = PaymentGateway(
        policy_provider=StaticPolicyProvider(),
        executor=executor,
    )

    result = gateway.charge("customer-1", 500)

    assert result["provider_id"] == "recovered"
    assert result["customer_id"] == "customer-1"
    assert executor.calls == 2
