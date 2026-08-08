"""Order worker module."""

import time
from dataclasses import dataclass

from src.common.database import create_session


@dataclass
class OrderResult:
    """Result of processing a batch of orders."""
    processed: int
    succeeded: int
    failed: int


class OrderWorker:
    """Background worker for order processing."""

    def __init__(self, batch_size: int = 100) -> None:
        self._batch_size = batch_size
        self._session = create_session()

    def process_pending_orders(self) -> OrderResult:
        """Process all pending orders in batches."""
        pending = self._fetch_pending()
        succeeded = 0
        failed = 0

        for order in pending[:self._batch_size]:
            try:
                self._process_one(order)
                succeeded += 1
            except Exception:
                failed += 1

        return OrderResult(
            processed=len(pending[:self._batch_size]),
            succeeded=succeeded,
            failed=failed,
        )

    def retry_failed_orders(self) -> int:
        """Retry orders that previously failed. Returns count of retried orders."""
        failed_orders = self._fetch_failed()
        retried = 0

        for order in failed_orders:
            try:
                self._process_one(order)
                retried += 1
            except Exception:
                continue

        return retried

    def release_inventory_holds(self, order_ids: list[int]) -> int:
        """Release inventory holds for cancelled orders.

        This must be called after an order is cancelled to free up
        reserved stock for other customers.
        """
        released = 0
        for order_id in order_ids:
            ok = self._session.execute(
                f"UPDATE inventory SET held = 0 WHERE order_id = {order_id}"
            )
            if ok:
                released += 1
        return released

    def _fetch_pending(self) -> list[dict]:
        return self._session.execute(
            "SELECT * FROM orders WHERE status = 'pending'"
        )

    def _fetch_failed(self) -> list[dict]:
        return self._session.execute(
            "SELECT * FROM orders WHERE status = 'failed'"
        )

    def _process_one(self, order: dict) -> None:
        order_id = order.get("id")
        if order_id is None:
            raise ValueError("Order missing id")
        # Simulate processing time
        time.sleep(0.001)
        self._session.execute(
            f"UPDATE orders SET status = 'completed' WHERE id = {order_id}"
        )
