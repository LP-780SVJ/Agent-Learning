from __future__ import annotations

import json
from pathlib import Path

from codeteam.evaluation.stability import aggregate_stability_campaign


def _completed_result(task_id: str) -> dict[str, object]:
    return {
        "task_id": task_id,
        "success": True,
        "actor_status": "completed",
        "acceptance_passed": True,
        "regression_passed": True,
        "task_verification_passed": True,
        "security_passed": True,
        "within_budget": True,
        "failure_category": None,
        "completion_ready": True,
        "completion_mode": "model_submitted",
        "effective_max_steps": 20,
        "verification_workspace_mutations": 0,
    }


def _campaign_inputs(tmp_path: Path):
    directories: list[Path] = []
    groups: list[str] = []
    repetitions: list[int] = []
    exit_codes: list[int] = []
    run_results: list[list[dict[str, object]]] = []
    for group, count in (("F03", 5), ("B01", 2), ("11task", 3)):
        for repetition in range(1, count + 1):
            directory = tmp_path / f"{group}-{repetition}"
            directory.mkdir()
            results = (
                [_completed_result(group)]
                if group != "11task"
                else [
                    _completed_result(f"T{index:02d}")
                    for index in range(1, 12)
                ]
            )
            (directory / "results.jsonl").write_text(
                "".join(json.dumps(item) + "\n" for item in results),
                encoding="utf-8",
            )
            directories.append(directory)
            groups.append(group)
            repetitions.append(repetition)
            exit_codes.append(0)
            run_results.append(results)
    return directories, groups, repetitions, exit_codes, run_results


def test_stability_aggregation_passes_only_clean_completed_campaign(
    tmp_path: Path,
) -> None:
    directories, groups, repetitions, exit_codes, _ = _campaign_inputs(tmp_path)

    payload = aggregate_stability_campaign(
        campaign_root=tmp_path,
        run_directories=directories,
        run_groups=groups,
        run_repetitions=repetitions,
        run_exit_codes=exit_codes,
    )

    assert payload["passed"] is True
    assert payload["checks"]["effective_max_steps_all_20"] is True
    assert payload["control_metrics"][
        "grader_correct_but_actor_failed_count"
    ] == 0


def test_stability_aggregation_fails_for_grader_correct_actor_max_steps(
    tmp_path: Path,
) -> None:
    directories, groups, repetitions, exit_codes, run_results = _campaign_inputs(
        tmp_path
    )
    full_run_index = groups.index("11task")
    false_negative = run_results[full_run_index][0]
    false_negative.update(
        {
            "success": False,
            "actor_status": "failed",
            "failure_category": "max_steps",
            "completion_ready": False,
        }
    )
    (directories[full_run_index] / "results.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in run_results[full_run_index]),
        encoding="utf-8",
    )

    payload = aggregate_stability_campaign(
        campaign_root=tmp_path,
        run_directories=directories,
        run_groups=groups,
        run_repetitions=repetitions,
        run_exit_codes=exit_codes,
    )

    assert payload["checks"]["no_source_progress_0"] is True
    assert payload["checks"]["grader_correct_but_actor_failed_0"] is False
    assert payload["control_metrics"][
        "grader_correct_but_actor_failed_count"
    ] == 1
    assert payload["control_metrics"][
        "grader_correct_actor_max_steps_count"
    ] == 1
    assert payload["passed"] is False
