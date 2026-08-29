from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from codeteam.schemas.messages import Message

DIAGNOSTIC_TOOLS = frozenset(
    {"list_files", "read_file", "search_code", "run_tests", "inspect_environment"}
)


@dataclass(frozen=True)
class ProgressPolicy:
    """Turn-based progress checkpoints for one workspace version."""

    max_steps: int
    advisory_level_1_ratio: float = 0.40
    advisory_level_2_ratio: float = 0.70
    terminal_ratio: float = 0.85

    def threshold(self, ratio: float) -> int:
        return max(1, math.ceil(self.max_steps * ratio))

    @property
    def advisory_level_1_step(self) -> int:
        return self.threshold(self.advisory_level_1_ratio)

    @property
    def advisory_level_2_step(self) -> int:
        return self.threshold(self.advisory_level_2_ratio)

    @property
    def terminal_step(self) -> int:
        return self.threshold(self.terminal_ratio)


@dataclass
class ProgressTracker:
    """Keep source, diagnostic, and completion progress separate.

    Diagnostic discoveries are useful evidence, but deliberately do not reset
    the source-progress clock.  A successful source patch starts a new clock
    for the new workspace version.
    """

    policy: ProgressPolicy
    workspace_version: int = 0
    first_patch_step: int | None = None
    pre_edit_step_count: int = 0
    pre_edit_tool_call_count: int = 0
    progress_advisory_count: int = 0
    progress_advisory_level_counts: dict[str, int] = field(default_factory=dict)
    no_source_progress_pause_count: int = 0
    max_no_source_progress_streak: int = 0
    environment_inspection_count: int = 0
    initial_context_cache_hit_count: int = 0
    initial_context_reference_hit_count: int = 0
    source_progress_count: int = 0
    diagnostic_progress_count: int = 0
    first_environment_inspection_step: int | None = None
    _last_source_step: int = 0
    _advisories_fired: set[int] = field(default_factory=set)
    _diagnostic_evidence: set[str] = field(default_factory=set)
    paused_reason: str | None = None

    def advisory_for_request(
        self,
        *,
        step: int,
        tool_call_count: int,
        completion_ready: bool,
    ) -> Message | None:
        self._observe_streak(step)
        if completion_ready or self.paused_reason is not None:
            return None
        streak = step - self._last_source_step
        level = 0
        if (
            streak >= self.policy.advisory_level_2_step
            and 2 not in self._advisories_fired
        ):
            level = 2
        elif (
            streak >= self.policy.advisory_level_1_step
            and 1 not in self._advisories_fired
        ):
            level = 1
        if level == 0:
            return None

        self._advisories_fired.add(level)
        self.progress_advisory_count += 1
        key = str(level)
        self.progress_advisory_level_counts[key] = (
            self.progress_advisory_level_counts.get(key, 0) + 1
        )
        if self.first_patch_step is None:
            self.pre_edit_step_count = max(self.pre_edit_step_count, step - 1)
            self.pre_edit_tool_call_count = max(
                self.pre_edit_tool_call_count, tool_call_count
            )
        payload = {
            "progress_advisory": {
                "level": level,
                "workspace_version": self.workspace_version,
                "turns_without_source_progress": step - self._last_source_step,
                "diagnostic_evidence_count": len(self._diagnostic_evidence),
                "remaining_turns": max(0, self.policy.max_steps - step + 1),
                "guidance": (
                    "Consolidate the evidence and identify the smallest safe edit. "
                    "Use inspect_environment for a narrow runtime-availability "
                    "question; apply a patch once evidence is sufficient."
                    if level == 1
                    else "Stop broad exploration. State the concrete blocker, take one "
                    "focused diagnostic if needed, then make the smallest justified "
                    "edit. Do not force a speculative patch."
                ),
            }
        }
        return Message(
            role="user",
            content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )

    def observe_tool_result(
        self,
        *,
        step: int,
        tool_call_count: int,
        tool_name: str,
        success: bool,
        workspace_version: int,
        evidence_key: str,
        completion_ready: bool,
        initial_context_cache_hit: bool = False,
        initial_context_reference_hit: bool = False,
    ) -> None:
        if initial_context_cache_hit:
            self.initial_context_cache_hit_count += 1
        if initial_context_reference_hit:
            self.initial_context_reference_hit_count += 1
        if tool_name == "inspect_environment":
            self.environment_inspection_count += 1
            if self.first_environment_inspection_step is None:
                self.first_environment_inspection_step = step

        if (
            success
            and tool_name == "apply_patch"
            and workspace_version != self.workspace_version
        ):
            self.workspace_version = workspace_version
            self.source_progress_count += 1
            self.first_patch_step = self.first_patch_step or step
            self.pre_edit_step_count = max(self.pre_edit_step_count, step - 1)
            self.pre_edit_tool_call_count = max(
                self.pre_edit_tool_call_count, max(0, tool_call_count - 1)
            )
            self._last_source_step = step
            self._advisories_fired.clear()
            self._diagnostic_evidence.clear()
            self.paused_reason = None
            return

        if (
            success
            and tool_name in DIAGNOSTIC_TOOLS
            and evidence_key not in self._diagnostic_evidence
        ):
            self._diagnostic_evidence.add(evidence_key)
            self.diagnostic_progress_count += 1

        self._observe_streak(step)
        if (
            not completion_ready
            and self.paused_reason is None
            and step - self._last_source_step >= self.policy.terminal_step
            and {1, 2}.issubset(self._advisories_fired)
        ):
            self.no_source_progress_pause_count += 1
            evidence = sorted(self._diagnostic_evidence)[-5:]
            self.paused_reason = (
                "No source progress after both progress advisories. "
                f"workspace_version={self.workspace_version}; "
                f"diagnostic_evidence={evidence or ['none']}."
            )

    def _observe_streak(self, step: int) -> None:
        streak = max(0, step - self._last_source_step)
        self.max_no_source_progress_streak = max(
            self.max_no_source_progress_streak, streak
        )
