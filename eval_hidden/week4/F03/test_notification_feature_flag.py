from pathlib import Path

from src.common.events import ORDER_CANCELLED, EventEnvelope
from src.notifications.dispatcher import NotificationDispatcher


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict]] = []

    def send(self, to: str, template: str, context: dict) -> None:
        self.sent.append((to, template, context))


def test_notification_dispatch_can_be_disabled_by_config(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "feature_flags.yaml").write_text(
        "notifications:\n  email_dispatch_enabled: false\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    sender = RecordingSender()

    NotificationDispatcher(sender=sender).handle(
        EventEnvelope(ORDER_CANCELLED, {"order_id": "order-1"}),
    )

    assert sender.sent == []
    assert Path("configs/feature_flags.yaml").exists()
