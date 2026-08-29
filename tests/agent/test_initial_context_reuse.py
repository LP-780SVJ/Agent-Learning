from __future__ import annotations

import json
from pathlib import Path

from codeteam.agent.initial_context import InitialContextSnapshot
from codeteam.agent.runtime_tools import RuntimeEvidence, create_runtime_tools
from codeteam.application.build_context import CodeContextReport, ContextBuildReport
from codeteam.context.models import CompressionLevel
from codeteam.execution.safe_execution_service import SafeExecutionService
from codeteam.schemas.tool_calls import ToolCall
from codeteam.usage.token_counter import ApproximateTokenCounter


class NeverInspector:
    def inspect(self, workspace_root, request):
        raise AssertionError("environment inspector should not run")


def _snapshot(level: CompressionLevel = CompressionLevel.FULL_FILE):
    report = ContextBuildReport(
        query="x",
        code_context=[
            CodeContextReport(
                path="app.py",
                compression_level=level.value,
                token_count=4,
                content="VALUE = 1\n",
            )
        ],
    )
    return InitialContextSnapshot.from_context_report(report, workspace_version=0)


def _registry(tmp_path: Path, snapshot: InitialContextSnapshot):
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    return create_runtime_tools(
        workspace_root=tmp_path,
        task_id="context",
        checkpoint_state_root=tmp_path / "checkpoints",
        safe_execution=SafeExecutionService(),
        evidence=RuntimeEvidence(),
        environment_inspector=NeverInspector(),
        initial_context_snapshot=snapshot,
    )


def _read(registry, **arguments):
    return registry.execute(
        ToolCall(call_id="read", name="read_file", arguments=arguments)
    )


def test_complete_visible_initial_file_returns_compact_structured_reference(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    result = _read(_registry(tmp_path, snapshot), path="app.py")
    payload = json.loads(result.content)

    assert payload["initial_context_reference"] is True
    assert payload["path"] == "app.py"
    assert snapshot.cache_hit_count == 1
    assert snapshot.reference_hit_count == 1


def test_compacted_request_returns_full_cached_content(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot.set_request_visibility(False)

    result = _read(_registry(tmp_path, snapshot), path="app.py")

    assert result.content == "VALUE = 1\n"
    assert snapshot.cache_hit_count == 1
    assert snapshot.reference_hit_count == 0


def test_partial_or_compressed_context_never_satisfies_full_read(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(CompressionLevel.SYMBOL_SIGNATURE)
    registry = _registry(tmp_path, snapshot)

    full = _read(registry, path="app.py")
    ranged = _read(registry, path="app.py", start_line=1, end_line=1)

    assert full.content == "VALUE = 1\n"
    assert ranged.content == "VALUE = 1\n"
    assert snapshot.cache_hit_count == 0


def test_workspace_version_change_invalidates_snapshot(tmp_path: Path) -> None:
    snapshot = _snapshot()

    assert snapshot.render_full_read("app.py", 1) is None


def test_reference_materially_reduces_estimated_tokens() -> None:
    content = "def example():\n    return 'long value'\n" * 100
    report = ContextBuildReport(
        query="x",
        code_context=[
            CodeContextReport(
                path="app.py",
                compression_level=CompressionLevel.FULL_FILE.value,
                token_count=1000,
                content=content,
            )
        ],
    )
    snapshot = InitialContextSnapshot.from_context_report(report, workspace_version=0)
    reference = snapshot.render_full_read("app.py", 0)
    counter = ApproximateTokenCounter()

    assert reference is not None
    assert counter.count_text(reference) < counter.count_text(content) / 4


def test_same_snapshot_can_satisfy_multiple_reads_without_mutation(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    registry = _registry(tmp_path, snapshot)

    first = _read(registry, path="app.py")
    second = _read(registry, path="app.py")

    assert first.success and second.success
    assert snapshot.cache_hit_count == 2
