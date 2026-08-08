"""Order export tests."""

from src.orders.exporter import OrderExportStream


def test_export_stream_is_iterable() -> None:
    assert list(OrderExportStream().rows()) == []

