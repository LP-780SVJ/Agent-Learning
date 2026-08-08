"""Application entrypoint for the medium fixture."""

from src.auth.api import AuthController
from src.orders.api import OrderController
from src.billing.webhooks import BillingWebhookController


def create_app() -> dict:
    """Wire controllers for tests and retrieval fixtures."""
    return {
        "auth": AuthController(),
        "orders": OrderController(),
        "billing_webhooks": BillingWebhookController(),
    }

