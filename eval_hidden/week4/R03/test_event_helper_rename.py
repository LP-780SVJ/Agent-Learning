from pathlib import Path

from src.common.events import EventEnvelope


def test_event_envelope_serialized_fields_remain_stable() -> None:
    event = EventEnvelope("demo.event", {"value": 1})

    assert event.name == "demo.event"
    assert event.payload == {"value": 1}


def test_internal_event_helper_has_domain_specific_name() -> None:
    source = Path("src/common/events.py").read_text(encoding="utf-8")

    assert "class DomainEvent" in source or "def domain_event" in source
