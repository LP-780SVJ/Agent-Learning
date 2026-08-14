from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LimitedOutput:
    text: str
    total_bytes: int
    truncated: bool


class OutputLimiter:
    def __init__(
        self,
        max_bytes: int,
        *,
        encoding: str = "utf-8",
        errors: str = "replace",
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive.")

        self._max_bytes = max_bytes
        self._head_limit = max_bytes // 2
        self._tail_limit = max_bytes - self._head_limit
        self._encoding = encoding
        self._errors = errors

        self._head = bytearray()
        self._tail = bytearray()
        self._total_bytes = 0

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return

        self._total_bytes += len(chunk)

        head_remaining = self._head_limit - len(self._head)
        if head_remaining > 0:
            self._head.extend(chunk[:head_remaining])
            chunk = chunk[head_remaining:]

        if chunk and self._tail_limit > 0:
            self._tail.extend(chunk)
            overflow = len(self._tail) - self._tail_limit
            if overflow > 0:
                del self._tail[:overflow]

    def snapshot(self) -> LimitedOutput:
        captured = bytes(self._head) + bytes(self._tail)
        truncated = self._total_bytes > len(captured)
        return LimitedOutput(
            text=captured.decode(self._encoding, errors=self._errors),
            total_bytes=self._total_bytes,
            truncated=truncated,
        )