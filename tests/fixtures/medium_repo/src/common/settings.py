"""Configuration loading helpers."""

from pathlib import Path


def config_path(name: str) -> Path:
    return Path("configs") / name


def load_retry_policy() -> dict:
    return {"initial_delay_seconds": 30, "max_attempts": 5}

