from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class CompletionEvidence(Protocol):
    workspace_version: int
    tests_passed: bool
    git_diff_checked_version: int | None
    workspace_hygiene_clean: bool
    paused_reason: str | None


@dataclass(frozen=True)
class CompletionGateDecision:
    ready: bool
    workspace_version: int
    missing_requirements: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "workspace_version": self.workspace_version,
            "missing_requirements": list(self.missing_requirements),
        }


class CompletionGate:
    """Pure policy for authorizing completion at one workspace version."""

    @staticmethod
    def evaluate(
        evidence: CompletionEvidence,
        *,
        changed_files: tuple[str, ...],
        diff: str,
    ) -> CompletionGateDecision:
        missing: list[str] = []
        if not changed_files or not diff.strip():
            missing.append("real_git_diff")
        if any(path == ".git" or path.startswith(".git/") for path in changed_files):
            missing.append("safe_git_diff")
        if not evidence.tests_passed:
            missing.append("current_version_verification")
        if evidence.git_diff_checked_version != evidence.workspace_version:
            missing.append("current_version_diff_review")
        if not evidence.workspace_hygiene_clean:
            missing.append("workspace_hygiene_clean")
        if evidence.paused_reason is not None:
            missing.append("execution_not_paused")
        return CompletionGateDecision(
            ready=not missing,
            workspace_version=evidence.workspace_version,
            missing_requirements=tuple(missing),
        )
