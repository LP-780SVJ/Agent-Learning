"""Order export utilities."""

import csv
from pathlib import Path
from typing import Iterable

from src.common.database import create_session


class OrderExportStream:
    """Streams order rows to avoid loading all data at once."""

    def rows(self) -> Iterable[dict]:
        session = create_session()
        result = session.execute("select id, status, total from orders order by id")
        yield from result.rows


def stream_orders_to_csv(output_path: str) -> int:
    """Stream orders into a CSV file."""
    exporter = OrderExportStream()
    count = 0
    with Path(output_path).open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["id", "status", "total"])
        writer.writeheader()
        for row in exporter.rows():
            writer.writerow(row)
            count += 1
    return count

