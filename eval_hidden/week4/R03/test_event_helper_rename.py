import ast
from pathlib import Path

from src.common.events import EventEnvelope
from src.orders.events import build_order_cancelled_event


def test_event_envelope_serialized_fields_remain_stable() -> None:
    event = build_order_cancelled_event("order-1", "customer_request")

    assert isinstance(event, EventEnvelope)
    assert event.name == "order.cancelled"
    assert event.payload == {
        "order_id": "order-1",
        "reason": "customer_request",
    }


def test_old_internal_helper_and_references_are_removed() -> None:
    events_source = Path("src/orders/events.py").read_text(encoding="utf-8")
    service_source = Path("src/orders/service.py").read_text(encoding="utf-8")
    service_tree = ast.parse(service_source)
    called_names = {
        node.func.id
        for node in ast.walk(service_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "def build_order_cancelled_event" in events_source
    assert "def order_cancelled_event" not in events_source
    assert "build_order_cancelled_event" in service_source
    assert "order_cancelled_event" not in called_names
