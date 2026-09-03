"""Prepare the weekend Single-vs-Team architecture comparison manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "status": "NOT_RUN",
        "comparison_type": "architecture_comparison_not_pure_ablation",
        "tasks": "Week4 11-task dev suite; not held-out",
        "arms": {
            "single": "CodingAgentRuntime",
            "team": "TeamCodingRuntime(max_workers=1, deterministic-single-node)",
        },
        "controlled": [
            "task/base_sha",
            "provider/model/reasoning",
            "context and hard budgets",
            "grader and security policy",
            "clean worktree",
        ],
        "required_metrics": [
            "external grader success",
            "wall time",
            "aggregate compute",
            "tokens/cost/tool calls",
            "control-plane overhead",
        ],
        "execution": "Real LLM commands must be run manually by the learner.",
    }
    target = args.output / "comparison_plan.json"
    target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
