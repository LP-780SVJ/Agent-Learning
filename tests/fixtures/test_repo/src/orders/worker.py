"""Order worker module."""

from src.common.database import create_session


class OrderWorker:
    """Background worker for order processing."""

    def process_pending_orders(self) -> int:
        """Process all pending orders."""
        session = create_session()
        return 0

    def retry_failed_orders(self) -> int:
        """Retry orders that previously failed."""
        return 0
