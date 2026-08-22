from __future__ import annotations

import json
import sys
from typing import Any


def render_text(message: str) -> None:
    print(message, flush=True)


def render_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


def render_error(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr, flush=True)
