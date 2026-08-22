from pathlib import Path

from src.billing.retries import load_invoice_retry_policy


def test_invoice_retry_policy_uses_toml_values(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "retry_policy.toml").write_text(
        "[invoice_retry]\n"
        "initial_delay_seconds = 11\n"
        "max_attempts = 7\n"
        "backoff_multiplier = 4\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    policy = load_invoice_retry_policy()

    assert policy.initial_delay_seconds == 11
    assert policy.max_attempts == 7
    assert policy.backoff_multiplier == 4
    assert Path("configs/retry_policy.toml").exists()
