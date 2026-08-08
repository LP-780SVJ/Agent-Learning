"""Invoice persistence."""

from src.common.database import create_session
from src.common.time import utc_now


class InvoiceRepository:
    """Stores invoice state."""

    def mark_retry_requested(self, invoice_id: str) -> None:
        session = create_session()
        session.execute(
            "update invoices set retry_requested_at=:now where invoice_id=:invoice_id",
            {"invoice_id": invoice_id, "now": utc_now().isoformat()},
        )

