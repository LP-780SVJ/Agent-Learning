from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def grader_correct_but_actor_failed(result: dict[str, Any]) -> bool:
    return bool(
        result.get("actor_status") != "completed"
        and result.get("acceptance_passed") is True
        and result.get("regression_passed") is True
        and result.get("task_verification_passed") is True
        and result.get("security_passed") is True
        and result.get("within_budget") is True
    )


def aggregate_stability_campaign(
    *,
    campaign_root: Path,
    run_directories: list[Path],
    run_groups: list[str],
    run_repetitions: list[int],
    run_exit_codes: list[int],
) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    all_results: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for directory, group, repetition, exit_code in zip(
        run_directories,
        run_groups,
        run_repetitions,
        run_exit_codes,
        strict=True,
    ):
        summary_path = directory / "summary.json"
        results_path = directory / "results.jsonl"
        summary = (
            json.loads(summary_path.read_text(encoding="utf-8"))
            if summary_path.is_file()
            else None
        )
        results = _load_results(results_path)
        all_results[group].extend(results)
        runs.append(
            {
                "group": group,
                "repetition": repetition,
                "output_dir": str(directory),
                "exit_code": exit_code,
                "summary": summary,
                "task_count": len(results),
                "steps": sum(int(item.get("steps", 0)) for item in results),
                "input_tokens": sum(
                    int(item.get("input_tokens", 0)) for item in results
                ),
                "output_tokens": sum(
                    int(item.get("output_tokens", 0)) for item in results
                ),
                "cost_usd": sum(
                    float(item.get("cost_usd", 0.0)) for item in results
                ),
            }
        )

    f03 = all_results["F03"]
    b01 = all_results["B01"]
    full = all_results["11task"]
    every_result = [*f03, *b01, *full]
    per_task_success = Counter(
        str(item.get("task_id")) for item in full if item.get("success") is True
    )
    actor_failures = [
        item for item in every_result if item.get("actor_status") != "completed"
    ]
    grader_correct_actor_failures = [
        item for item in every_result if grader_correct_but_actor_failed(item)
    ]
    ready_actor_failures = [
        item
        for item in actor_failures
        if item.get("completion_ready") is True
    ]
    provider_failures = [
        item
        for item in every_result
        if item.get("actor_status") == "provider_blocked"
        or item.get("failure_category") == "provider_blocked"
    ]
    environment_categories = {
        "sandbox_unavailable",
        "verification_environment_failed",
        "workspace_hygiene_failed",
    }
    environment_failures = [
        item
        for item in every_result
        if item.get("actor_status") == "environment_blocked"
        or item.get("failure_category") in environment_categories
    ]
    protocol_failures = [
        item
        for item in every_result
        if item.get("failure_category") == "invalid_final_output"
    ]
    workspace_mutations = sum(
        int(item.get("verification_workspace_mutations", 0) or 0)
        for item in every_result
    )
    checks = {
        "all_run_exit_codes_0": all(code == 0 for code in run_exit_codes),
        "f03_result_count_5": len(f03) == 5,
        "f03_success_at_least_4": _count(f03, "success") >= 4,
        "f03_max_steps_0": _count(f03, "failure_category", "max_steps") == 0,
        "b01_result_count_2": len(b01) == 2,
        "b01_success_2_of_2": _count(b01, "success") == 2,
        "full_result_count_33": len(full) == 33,
        "full_security_33": _count(full, "security_passed") == 33,
        "full_success_at_least_90_percent": (
            _count(full, "success") / max(1, len(full)) >= 0.90
        ),
        "full_each_task_at_least_2_of_3": (
            len(per_task_success) == 11
            and min(per_task_success.values(), default=0) >= 2
        ),
        "no_source_progress_0": _count(
            every_result, "failure_category", "no_source_progress"
        )
        == 0,
        "grader_correct_but_actor_failed_0": (
            len(grader_correct_actor_failures) == 0
        ),
        "completion_ready_but_actor_failed_0": len(ready_actor_failures) == 0,
        "provider_failures_0": len(provider_failures) == 0,
        "environment_failures_0": len(environment_failures) == 0,
        "protocol_failures_0": len(protocol_failures) == 0,
        "workspace_mutation_0": workspace_mutations == 0,
        "effective_max_steps_all_20": bool(every_result)
        and all(item.get("effective_max_steps") == 20 for item in every_result),
        "actor_failures_are_categorized": all(
            item.get("failure_category") not in {None, ""}
            for item in actor_failures
        ),
    }
    metrics = {
        group: _group_metrics(items) for group, items in all_results.items()
    }
    payload = {
        "campaign_root": str(campaign_root),
        "passed": all(checks.values()),
        "checks": checks,
        "runs": runs,
        "per_task_success": {
            group: dict(
                Counter(
                    str(item.get("task_id"))
                    for item in items
                    if item.get("success") is True
                )
            )
            for group, items in all_results.items()
        },
        "control_metrics": {
            "grader_correct_but_actor_failed_count": len(
                grader_correct_actor_failures
            ),
            "grader_correct_actor_max_steps_count": sum(
                item.get("failure_category") == "max_steps"
                for item in grader_correct_actor_failures
            ),
            "completion_ready_but_actor_failed_count": len(ready_actor_failures),
            "provider_failure_count": len(provider_failures),
            "environment_failure_count": len(environment_failures),
            "protocol_failure_count": len(protocol_failures),
            "verification_workspace_mutation_count": workspace_mutations,
            "budget_boundary_completion_count": sum(
                int(item.get("budget_boundary_completion_count", 0) or 0)
                for item in every_result
            ),
            "finalization_reserve_entry_count": sum(
                item.get("finalization_reserve_entered") is True
                for item in every_result
            ),
            "finalization_reserve_success_count": sum(
                item.get("finalization_reserve_entered") is True
                and item.get("actor_status") == "completed"
                for item in every_result
            ),
        },
        "metrics": metrics,
    }
    return payload


def write_stability_summary(payload: dict[str, Any], campaign_root: Path) -> Path:
    output = campaign_root / "stability_summary.json"
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


def main() -> int:
    campaign_root = Path(os.environ["CODETEAM_STABILITY_CAMPAIGN_ROOT"])
    payload = aggregate_stability_campaign(
        campaign_root=campaign_root,
        run_directories=[
            Path(value)
            for value in os.environ["CODETEAM_STABILITY_RUN_DIRS"].splitlines()
        ],
        run_groups=os.environ["CODETEAM_STABILITY_RUN_GROUPS"].splitlines(),
        run_repetitions=[
            int(value)
            for value in os.environ[
                "CODETEAM_STABILITY_RUN_REPETITIONS"
            ].splitlines()
        ],
        run_exit_codes=[
            int(value)
            for value in os.environ["CODETEAM_STABILITY_RUN_EXIT_CODES"].splitlines()
        ],
    )
    write_stability_summary(payload, campaign_root)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["passed"] else 1


def _load_results(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _count(
    items: list[dict[str, Any]], field: str, value: object = True
) -> int:
    return sum(item.get(field) == value for item in items)


def _group_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    task_ids = sorted({str(item.get("task_id")) for item in items})
    return {
        "result_count": len(items),
        "success_count": _count(items, "success"),
        "failure_categories": dict(
            Counter(
                str(item.get("failure_category"))
                for item in items
                if item.get("failure_category") is not None
            )
        ),
        "completion_mode_counts": dict(
            Counter(
                str(item.get("completion_mode"))
                for item in items
                if item.get("completion_mode") is not None
            )
        ),
        "grader_correct_but_actor_failed_count": sum(
            grader_correct_but_actor_failed(item) for item in items
        ),
        "budget_boundary_completion_count": sum(
            int(item.get("budget_boundary_completion_count", 0) or 0)
            for item in items
        ),
        "finalization_reserve_entry_count": sum(
            item.get("finalization_reserve_entered") is True for item in items
        ),
        "effective_max_steps_counts": dict(
            Counter(str(item.get("effective_max_steps")) for item in items)
        ),
        "first_patch_step_count": sum(
            item.get("first_patch_step") is not None for item in items
        ),
        "first_patch_step_by_task": {
            task_id: [
                item.get("first_patch_step")
                for item in items
                if str(item.get("task_id")) == task_id
            ]
            for task_id in task_ids
        },
        "pre_edit_step_count": sum(
            int(item.get("pre_edit_step_count", 0) or 0) for item in items
        ),
        "pre_edit_tool_call_count": sum(
            int(item.get("pre_edit_tool_call_count", 0) or 0) for item in items
        ),
        "progress_advisory_count": sum(
            int(item.get("progress_advisory_count", 0) or 0) for item in items
        ),
        "progress_advisory_level_counts": {
            level: sum(
                int(
                    (item.get("progress_advisory_level_counts") or {}).get(level, 0)
                )
                for item in items
            )
            for level in ("1", "2")
        },
        "no_source_progress_pause_count": sum(
            int(item.get("no_source_progress_pause_count", 0) or 0)
            for item in items
        ),
        "max_no_source_progress_streak": max(
            (
                int(item.get("max_no_source_progress_streak", 0) or 0)
                for item in items
            ),
            default=0,
        ),
        "environment_inspection_count": sum(
            int(item.get("environment_inspection_count", 0) or 0)
            for item in items
        ),
        "initial_context_cache_hit_count": sum(
            int(item.get("initial_context_cache_hit_count", 0) or 0)
            for item in items
        ),
        "initial_context_reference_hit_count": sum(
            int(item.get("initial_context_reference_hit_count", 0) or 0)
            for item in items
        ),
        "source_progress_count": sum(
            int(item.get("source_progress_count", 0) or 0) for item in items
        ),
        "diagnostic_progress_count": sum(
            int(item.get("diagnostic_progress_count", 0) or 0) for item in items
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
