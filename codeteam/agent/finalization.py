from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class FinalizationBudgetPolicy:
    """Reserve part of the existing model-turn budget for deterministic closeout."""

    effective_max_steps: int
    configured_reserve_steps: int | None = None

    def __post_init__(self) -> None:
        if self.effective_max_steps <= 0:
            raise ValueError("effective_max_steps must be positive")
        if (
            self.configured_reserve_steps is not None
            and self.configured_reserve_steps <= 0
        ):
            raise ValueError("configured_reserve_steps must be positive")

    @property
    def reserve_steps(self) -> int:
        requested = self.configured_reserve_steps
        if requested is None:
            requested = max(3, math.ceil(self.effective_max_steps * 0.20))
        return min(self.effective_max_steps, requested)

    def remaining_turns(self, step: int) -> int:
        """Return legal model turns including the turn about to be requested."""

        return max(0, self.effective_max_steps - step + 1)

    def should_enter_reserve(self, *, step: int, has_real_diff: bool) -> bool:
        remaining = self.remaining_turns(step)
        return has_real_diff and 0 < remaining <= self.reserve_steps


@dataclass
class FinalizationBudgetTracker:
    policy: FinalizationBudgetPolicy
    reserve_entered: bool = False
    reserve_entry_step: int | None = None

    def observe(self, *, step: int, has_real_diff: bool) -> bool:
        if not self.reserve_entered and self.policy.should_enter_reserve(
            step=step,
            has_real_diff=has_real_diff,
        ):
            self.reserve_entered = True
            self.reserve_entry_step = step
            return True
        return False


@dataclass(frozen=True)
class TerminalSettlementDecision:
    settled: bool
    summary: str | None = None
    reason: str | None = None

