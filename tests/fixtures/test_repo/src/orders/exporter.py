"""Order export module."""

from src.common.database import create_session


def export_orders_to_csv(output_path: str) -> int:
    """Export all orders to a CSV file."""
    session = create_session()
    return 0


def export_orders_to_json(output_path: str) -> int:
    """Export all orders to a JSON file."""
    return 0
