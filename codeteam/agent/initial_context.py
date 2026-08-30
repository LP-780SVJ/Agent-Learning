from __future__ import annotations

import hashlib
import json
import posixpath
from dataclasses import dataclass, field

from codeteam.application.build_context import ContextBuildReport
from codeteam.context.models import CompressionLevel


@dataclass(frozen=True)
class InitialContextFile:
    path: str
    content: str
    content_hash: str
    compression_level: str
    workspace_version: int
    is_complete: bool


@dataclass
class InitialContextSnapshot:
    files: dict[str, InitialContextFile] = field(default_factory=dict)
    workspace_version: int = 0
    visible_in_current_request: bool = True
    cache_hit_count: int = 0
    reference_hit_count: int = 0

    @classmethod
    def from_context_report(
        cls,
        report: ContextBuildReport,
        *,
        workspace_version: int,
    ) -> InitialContextSnapshot:
        files: dict[str, InitialContextFile] = {}
        for item in report.code_context:
            path = posixpath.normpath(item.path)
            complete = item.compression_level == CompressionLevel.FULL_FILE.value
            files[path] = InitialContextFile(
                path=path,
                content=item.content,
                content_hash=hashlib.sha256(item.content.encode("utf-8")).hexdigest(),
                compression_level=item.compression_level,
                workspace_version=workspace_version,
                is_complete=complete,
            )
        return cls(files=files, workspace_version=workspace_version)

    def set_request_visibility(self, visible: bool) -> None:
        self.visible_in_current_request = visible

    def reusable_file(
        self, path: str, workspace_version: int
    ) -> InitialContextFile | None:
        normalized = posixpath.normpath(path)
        item = self.files.get(normalized)
        if (
            item is None
            or not item.is_complete
            or item.compression_level != CompressionLevel.FULL_FILE.value
            or item.workspace_version != workspace_version
            or self.workspace_version != workspace_version
        ):
            return None
        return item

    def render_full_read(self, path: str, workspace_version: int) -> str | None:
        item = self.reusable_file(path, workspace_version)
        if item is None:
            return None
        self.cache_hit_count += 1
        if not self.visible_in_current_request:
            return item.content
        self.reference_hit_count += 1
        return json.dumps(
            {
                "initial_context_reference": True,
                "initial_context_cache_hit": True,
                "path": item.path,
                "content_hash": item.content_hash,
                "workspace_version": workspace_version,
                "content_location": "current_model_request.initial_context",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def result_flags(content: str) -> tuple[bool, bool]:
        try:
            payload = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return False, False
        if not isinstance(payload, dict):
            return False, False
        return (
            payload.get("initial_context_cache_hit") is True,
            payload.get("initial_context_reference") is True,
        )
