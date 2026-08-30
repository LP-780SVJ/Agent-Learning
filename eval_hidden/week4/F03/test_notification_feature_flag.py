from pathlib import Path

from src.common.events import ORDER_CANCELLED, EventEnvelope
from src.notifications.dispatcher import NotificationDispatcher


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict]] = []

    def send(self, to: str, template: str, context: dict) -> None:
        self.sent.append((to, template, context))


def _dispatch_with_config(
    tmp_path,
    monkeypatch,
    config: str | None,
) -> list[tuple[str, str, dict]]:
    if config is not None:
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        (config_dir / "feature_flags.yaml").write_text(config, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    sender = RecordingSender()
    NotificationDispatcher(sender=sender).handle(
        EventEnvelope(ORDER_CANCELLED, {"order_id": "order-1"}),
    )
    return sender.sent


def test_notification_dispatch_can_be_disabled_by_config(tmp_path, monkeypatch) -> None:
    sent = _dispatch_with_config(
        tmp_path,
        monkeypatch,
        "notifications:\n  email_dispatch_enabled: false\n",
    )
    assert sent == []
    assert Path("configs/feature_flags.yaml").exists()


def test_notification_dispatch_preserves_default_when_flag_is_missing(
    tmp_path,
    monkeypatch,
) -> None:
    sent = _dispatch_with_config(tmp_path, monkeypatch, "orders:\n  enabled: true\n")
    assert len(sent) == 1


def test_notification_dispatch_preserves_default_when_file_is_missing(
    tmp_path,
    monkeypatch,
) -> None:
    sent = _dispatch_with_config(tmp_path, monkeypatch, None)
    assert len(sent) == 1
