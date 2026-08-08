"""Order export module."""

import csv
import json
from pathlib import Path

from src.common.database import create_session


def export_orders_to_csv(output_path: str) -> int:
    """Export all orders to a CSV file.

    Returns the number of exported rows.
    """
    session = create_session()
    orders = _fetch_all_orders(session)
    if not orders:
        return 0

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "status", "total"])
        writer.writeheader()
        writer.writerows(orders)

    return len(orders)


def export_orders_to_json(output_path: str) -> int:
    """Export all orders to a JSON file.

    Returns the number of exported orders.
    """
    orders = _fetch_all_orders(None)
    if not orders:
        return 0

    with open(output_path, "w") as f:
        json.dump(orders, f, indent=2)

    return len(orders)


def _fetch_all_orders(session) -> list[dict]:
    """Fetch all orders from the database. Returns empty list on error."""
    try:
        if session is None:
            session = create_session()
        return session.execute("SELECT * FROM orders")
    except Exception:
        return []
