from __future__ import annotations

import pytest

from codeteam.execution.output_limiter import OutputLimiter


def test_small_output_is_kept_without_truncation() -> None:
    limiter = OutputLimiter(10)

    limiter.feed(b"hello")

    output = limiter.snapshot()
    assert output.text == "hello"
    assert output.total_bytes == 5
    assert output.truncated is False


def test_large_output_keeps_head_and_tail() -> None:
    limiter = OutputLimiter(10)

    limiter.feed(b"abcdefghijklmnopqrstuvwxyz")

    output = limiter.snapshot()
    assert output.text == "abcdevwxyz"
    assert output.total_bytes == 26
    assert output.truncated is True


def test_multiple_chunks_keep_same_head_tail_semantics() -> None:
    limiter = OutputLimiter(8)

    limiter.feed(b"abcd")
    limiter.feed(b"efgh")
    limiter.feed(b"ijkl")

    output = limiter.snapshot()
    assert output.text == "abcdijkl"
    assert output.total_bytes == 12
    assert output.truncated is True


def test_invalid_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_bytes"):
        OutputLimiter(0)


def test_split_utf8_sequence_is_replaced_instead_of_crashing() -> None:
    limiter = OutputLimiter(3)

    limiter.feed("你".encode())
    limiter.feed("好".encode())

    output = limiter.snapshot()
    assert output.total_bytes == 6
    assert output.truncated is True
    assert output.text
