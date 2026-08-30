from __future__ import annotations

import pytest

from codeteam.agent.progress import ProgressPolicy, ProgressTracker


def _observe(
    tracker: ProgressTracker,
    step: int,
    name: str = "search_code",
    *,
    version: int = 0,
    success: bool = True,
    key: str | None = None,
    ready: bool = False,
) -> None:
    tracker.observe_tool_result(
        step=step,
        tool_call_count=step,
        tool_name=name,
        success=success,
        workspace_version=version,
        evidence_key=key or f"{name}:{step}",
        completion_ready=ready,
    )


def test_diverse_diagnostics_do_not_hide_source_stagnation() -> None:
    tracker = ProgressTracker(ProgressPolicy(max_steps=20))

    for step in range(1, 18):
        tracker.advisory_for_request(
            step=step, tool_call_count=step - 1, completion_ready=False
        )
        _observe(tracker, step, ("read_file", "search_code", "list_files")[step % 3])

    assert tracker.diagnostic_progress_count == 17
    assert tracker.source_progress_count == 0
    assert tracker.progress_advisory_level_counts == {"1": 1, "2": 1}
    assert tracker.paused_reason is not None
    assert tracker.no_source_progress_pause_count == 1
    assert tracker.max_no_source_progress_streak == 17


def test_patch_resets_advisories_for_new_workspace_version() -> None:
    tracker = ProgressTracker(ProgressPolicy(max_steps=20))
    assert (
        tracker.advisory_for_request(step=8, tool_call_count=7, completion_ready=False)
        is not None
    )

    _observe(tracker, 9, "apply_patch", version=1)

    assert tracker.first_patch_step == 9
    assert tracker.source_progress_count == 1
    assert (
        tracker.advisory_for_request(step=10, tool_call_count=9, completion_ready=False)
        is None
    )
    assert tracker.paused_reason is None


def test_reasonable_exploration_is_not_paused_before_terminal_checkpoint() -> None:
    tracker = ProgressTracker(ProgressPolicy(max_steps=20))

    for step in range(1, 17):
        tracker.advisory_for_request(
            step=step, tool_call_count=step - 1, completion_ready=False
        )
        _observe(tracker, step)

    assert tracker.paused_reason is None
    assert tracker.progress_advisory_count == 2


def test_completion_progress_suppresses_advisory_and_pause() -> None:
    tracker = ProgressTracker(ProgressPolicy(max_steps=20))

    assert (
        tracker.advisory_for_request(step=14, tool_call_count=10, completion_ready=True)
        is None
    )
    _observe(tracker, 17, "git_diff", ready=True)

    assert tracker.progress_advisory_count == 0
    assert tracker.paused_reason is None


def test_diagnostic_duplicate_does_not_reset_or_inflate_progress() -> None:
    tracker = ProgressTracker(ProgressPolicy(max_steps=20))

    _observe(tracker, 1, key="same")
    _observe(tracker, 2, key="same")

    assert tracker.diagnostic_progress_count == 1
    assert tracker.max_no_source_progress_streak == 2


def test_environment_inspection_observability_is_separate() -> None:
    tracker = ProgressTracker(ProgressPolicy(max_steps=20))

    _observe(tracker, 3, "inspect_environment")

    assert tracker.environment_inspection_count == 1
    assert tracker.first_environment_inspection_step == 3
    assert tracker.diagnostic_progress_count == 1


@pytest.mark.parametrize("patch_step", [6, 8, 12])
def test_b03_f04_r02_like_exploration_then_patch_is_not_paused(
    patch_step: int,
) -> None:
    tracker = ProgressTracker(ProgressPolicy(max_steps=20))
    for step in range(1, patch_step):
        tracker.advisory_for_request(
            step=step, tool_call_count=step * 2, completion_ready=False
        )
        _observe(tracker, step, ("read_file", "search_code")[step % 2])

    _observe(tracker, patch_step, "apply_patch", version=1)

    assert tracker.paused_reason is None
    assert tracker.first_patch_step == patch_step
