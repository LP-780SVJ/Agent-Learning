from __future__ import annotations

import difflib
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, Field, model_validator


class FileEdit(BaseModel):
    """A complete replacement or deletion used by the provider-neutral protocol."""

    path: str = Field(min_length=1)
    content: str | None = None
    delete: bool = False

    @model_validator(mode="after")
    def validate_operation(self) -> FileEdit:
        if self.delete and self.content is not None:
            raise ValueError("A delete edit cannot also provide content.")
        if not self.delete and self.content is None:
            raise ValueError("A replacement edit must provide content.")
        validate_edit_path(self.path)
        return self


class TextReplacement(BaseModel):
    """A small exact text replacement converted to a local Git patch."""

    path: str = Field(min_length=1)
    old_text: str = Field(min_length=1)
    new_text: str
    expected_replacements: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_replacement(self) -> TextReplacement:
        validate_edit_path(self.path)
        if self.old_text == self.new_text:
            raise ValueError("Replacement old_text and new_text must differ.")
        return self


def validate_edit_path(path: str) -> None:
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"Edit path escapes workspace: {path}")
    if not candidate.parts or candidate.parts[0] == ".git":
        raise ValueError(f"Git metadata cannot be edited: {path}")


def file_edits_to_patch(
    workspace_root: Path,
    edits: list[FileEdit],
    *,
    assume_missing_paths: frozenset[str] = frozenset(),
) -> str:
    """Convert complete-file edits to one deterministic unified Git patch."""
    root = workspace_root.resolve(strict=True)
    sections: list[str] = []
    seen: set[str] = set()

    for edit in edits:
        validate_edit_path(edit.path)
        if edit.path in seen:
            raise ValueError(f"Duplicate file edit: {edit.path}")
        seen.add(edit.path)

        target = (root / edit.path).resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError as error:
            raise ValueError(f"Edit path escapes workspace: {edit.path}") from error
        if target.exists() and not target.is_file():
            raise ValueError(f"Edit target is not a regular file: {edit.path}")

        target_exists = target.exists() and edit.path not in assume_missing_paths
        old_text = target.read_text(encoding="utf-8") if target_exists else ""
        if edit.delete:
            if not target_exists:
                raise ValueError(f"Cannot delete missing file: {edit.path}")
            new_text = ""
            fromfile = f"a/{edit.path}"
            tofile = "/dev/null"
        else:
            new_text = edit.content or ""
            fromfile = f"a/{edit.path}" if target_exists else "/dev/null"
            tofile = f"b/{edit.path}"

        if old_text == new_text:
            continue
        body = "".join(
            difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=fromfile,
                tofile=tofile,
            )
        )
        sections.append(f"diff --git a/{edit.path} b/{edit.path}\n{body}")

    if not sections:
        raise ValueError("Structured edits produced no changes.")
    return "".join(sections)


def text_replacements_to_patch(
    workspace_root: Path,
    replacements: list[TextReplacement],
) -> str:
    """Apply exact replacements in memory and render one deterministic patch."""
    if not replacements:
        raise ValueError("replacements must not be empty.")

    root = workspace_root.resolve(strict=True)
    originals: dict[str, str] = {}
    updated: dict[str, str] = {}
    for replacement in replacements:
        validate_edit_path(replacement.path)
        target = (root / replacement.path).resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError as error:
            raise ValueError(
                f"Edit path escapes workspace: {replacement.path}"
            ) from error
        if not target.is_file():
            raise ValueError(
                f"Replacement target must be an existing regular file: "
                f"{replacement.path}"
            )

        if replacement.path not in originals:
            originals[replacement.path] = target.read_text(encoding="utf-8")
            updated[replacement.path] = originals[replacement.path]
        current = updated[replacement.path]
        actual = current.count(replacement.old_text)
        if actual != replacement.expected_replacements:
            raise ValueError(
                f"Replacement count mismatch for {replacement.path}: "
                f"expected {replacement.expected_replacements}, found {actual}."
            )
        updated[replacement.path] = current.replace(
            replacement.old_text,
            replacement.new_text,
        )

    return file_edits_to_patch(
        root,
        [
            FileEdit(path=path, content=content)
            for path, content in updated.items()
        ],
    )
