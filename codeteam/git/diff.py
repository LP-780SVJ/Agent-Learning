from __future__ import annotations

import os

from codeteam.git.errors import PatchParseError
from codeteam.git.models import GitChange, GitChangeKind

# 状态映射表
_STATUS_KIND_MAP: dict[str, GitChangeKind] = {# 变量名前面的 _ 是 Python 约定，表示它是模块内部实现，不建议其他模块直接依赖。
    "M": GitChangeKind.MODIFIED,
    "A": GitChangeKind.ADDED,
    "D": GitChangeKind.DELETED,
    "R": GitChangeKind.RENAMED,
    "C": GitChangeKind.COPIED,
    "T": GitChangeKind.TYPE_CHANGED,
    "U": GitChangeKind.UNMERGED,
}


def parse_nul_paths(data: bytes) -> list[str]:
    """解析由 NUL 分隔的路径列表。"""
    records = _split_nul_records(data)

    return [
        _decode_path(record, field_name="path")
        for record in records
    ]


def parse_name_status(data: bytes) -> list[GitChange]:
    """解析 git diff --name-status -z 的输出。"""
    records = _split_nul_records(data)
    changes: list[GitChange] = []
    cursor = 0

    while cursor < len(records):
        status_text = os.fsdecode(records[cursor])
        cursor += 1

        if not status_text:
            raise PatchParseError("Git change status cannot be empty.")

        status_code = status_text[0]
        kind = _STATUS_KIND_MAP.get(status_code)

        if kind is None:
            raise PatchParseError(
                f"Unsupported Git change status: {status_text!r}"
            )

        if status_code in {"R", "C"}:
            if cursor + 1 >= len(records):
                raise PatchParseError(
                    f"Missing old or new path for status {status_text!r}."
                )

            old_path = _decode_path(
                records[cursor],
                field_name="old_path",
            )
            new_path = _decode_path(
                records[cursor + 1],
                field_name="new_path",
            )
            cursor += 2

            changes.append(
                GitChange(
                    kind=kind,
                    path=new_path,
                    old_path=old_path,
                    similarity=_parse_similarity(status_text),
                )
            )
            continue

        if cursor >= len(records):
            raise PatchParseError(
                f"Missing path for status {status_text!r}."
            )

        path = _decode_path(
            records[cursor],
            field_name="path",
        )
        cursor += 1

        changes.append(
            GitChange(
                kind=kind,
                path=path,
            )
        )

    return changes


def parse_numstat_summary(
    data: bytes,
) -> tuple[int, int, bool]:
    """解析 git diff --numstat -z 并汇总行数。"""
    records = _split_nul_records(data)
    additions = 0
    deletions = 0
    has_binary_changes = False
    cursor = 0

    while cursor < len(records):
        record = records[cursor]
        cursor += 1

        try:
            added_raw, deleted_raw, path_raw = record.split(
                b"\t",
                maxsplit=2,
            )
        except ValueError as error:
            raise PatchParseError(
                "Malformed git numstat record."
            ) from error

        if added_raw == b"-" or deleted_raw == b"-":
            has_binary_changes = True
        else:
            try:
                additions += int(added_raw)
                deletions += int(deleted_raw)
            except ValueError as error:
                raise PatchParseError(
                    "Numstat additions and deletions must be integers."
                ) from error

        if not path_raw:
            if cursor + 1 >= len(records):
                raise PatchParseError(
                    "Rename numstat record is missing old or new path."
                )

            # Rename/Copy 后面还跟着 old_path 和 new_path。
            cursor += 2

    return additions, deletions, has_binary_changes


def _split_nul_records(data: bytes) -> list[bytes]:
    """检查结尾的 NUL，并分割机器格式记录。"""
    if not data:
        return []

    if not data.endswith(b"\0"):
        raise PatchParseError(
            "Git machine output must end with a NUL byte."
        )

    return data[:-1].split(b"\0")


def _decode_path(
    raw_path: bytes,
    *,
    field_name: str,
) -> str:
    """使用文件系统编码将路径 bytes 转为 str。"""
    if not raw_path:
        raise PatchParseError(
            f"Git {field_name} cannot be empty."
        )

    return os.fsdecode(raw_path)


def _parse_similarity(status_text: str) -> int | None:
    """从 R090 或 C075 中提取相似度。"""
    similarity_text = status_text[1:]

    if not similarity_text:
        return None

    if not similarity_text.isdigit():
        raise PatchParseError(
            f"Invalid similarity value: {status_text!r}"
        )

    similarity = int(similarity_text)

    if not 0 <= similarity <= 100:
        raise PatchParseError(
            f"Similarity must be between 0 and 100: {status_text!r}"
        )

    return similarity