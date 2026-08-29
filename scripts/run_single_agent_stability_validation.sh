#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PYTHON="${REPO_ROOT}/.venv/bin/python"
SUITE="${REPO_ROOT}/evals/week4/agent_task_suite_v1.jsonl"
DRY_RUN=false
CAMPAIGN_ROOT=""

usage() {
  printf '%s\n' \
    "Usage: scripts/run_single_agent_stability_validation.sh [--dry-run] [--output-root PATH]" \
    "Runs F03 x5, B01 x2, then the full 11-task suite x3." 
}

while (($#)); do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --output-root)
      if (($# < 2)); then
        usage
        exit 2
      fi
      CAMPAIGN_ROOT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "${CAMPAIGN_ROOT}" ]]; then
  CAMPAIGN_ROOT="${REPO_ROOT}/evals/week4/agent_runs/stability_$(date +%Y%m%d_%H%M%S)"
elif [[ "${CAMPAIGN_ROOT}" != /* ]]; then
  CAMPAIGN_ROOT="${REPO_ROOT}/${CAMPAIGN_ROOT}"
fi

COMMON_ARGS=(
  -m codeteam.cli.app agent-eval
  --suite "${SUITE}"
  --actor llm
  --mode baseline
  --context-budget 8192
  --max-output-tokens 4096
  --model-context-window 32768
  --safety-headroom-tokens 1024
  --native-tools
  --no-reasoning
)

RUN_DIRS=()
RUN_GROUPS=()
RUN_REPETITIONS=()
RUN_EXIT_CODES=()
SEQUENCE=0

run_one() {
  local group="$1"
  local repetition="$2"
  shift 2
  SEQUENCE=$((SEQUENCE + 1))
  local stamp
  stamp="$(date +%Y%m%d_%H%M%S)"
  local output_dir="${CAMPAIGN_ROOT}/$(printf '%02d' "${SEQUENCE}")_${group}_${repetition}_${stamp}"
  local command=(
    "${PYTHON}" "${COMMON_ARGS[@]}"
    --output "${output_dir}"
  )
  if [[ "${CODETEAM_STABILITY_KEEP_WORKSPACES:-false}" == "true" ]]; then
    command+=(--keep-workspaces)
  fi
  command+=("$@")
  RUN_DIRS+=("${output_dir}")
  RUN_GROUPS+=("${group}")
  RUN_REPETITIONS+=("${repetition}")

  if [[ "${DRY_RUN}" == "true" ]]; then
    printf 'OUTPUT %s\n' "${output_dir}"
    printf 'COMMAND'
    printf ' %q' "${command[@]}"
    printf '\n'
    RUN_EXIT_CODES+=(0)
    return
  fi

  mkdir -p "${output_dir}"
  set +e
  "${command[@]}"
  local exit_code=$?
  set -e
  RUN_EXIT_CODES+=("${exit_code}")
  printf '%s\t%s\t%s\t%s\n' \
    "${group}" "${repetition}" "${exit_code}" "${output_dir}" \
    >> "${CAMPAIGN_ROOT}/exit_codes.tsv"
}

for repetition in 1 2 3 4 5; do
  run_one F03 "${repetition}" --task-id F03
done
for repetition in 1 2; do
  run_one B01 "${repetition}" --task-id B01
done
for repetition in 1 2 3; do
  run_one 11task "${repetition}"
done

if [[ "${DRY_RUN}" == "true" ]]; then
  printf 'SUMMARY %s\n' "${CAMPAIGN_ROOT}/stability_summary.json"
  exit 0
fi

export CODETEAM_STABILITY_CAMPAIGN_ROOT="${CAMPAIGN_ROOT}"
export CODETEAM_STABILITY_RUN_DIRS="$(printf '%s\n' "${RUN_DIRS[@]}")"
export CODETEAM_STABILITY_RUN_GROUPS="$(printf '%s\n' "${RUN_GROUPS[@]}")"
export CODETEAM_STABILITY_RUN_REPETITIONS="$(printf '%s\n' "${RUN_REPETITIONS[@]}")"
export CODETEAM_STABILITY_RUN_EXIT_CODES="$(printf '%s\n' "${RUN_EXIT_CODES[@]}")"

set +e
"${PYTHON}" - <<'PY'
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from pathlib import Path


campaign = Path(os.environ["CODETEAM_STABILITY_CAMPAIGN_ROOT"])
directories = os.environ["CODETEAM_STABILITY_RUN_DIRS"].splitlines()
groups = os.environ["CODETEAM_STABILITY_RUN_GROUPS"].splitlines()
repetitions = [int(value) for value in os.environ["CODETEAM_STABILITY_RUN_REPETITIONS"].splitlines()]
exit_codes = [int(value) for value in os.environ["CODETEAM_STABILITY_RUN_EXIT_CODES"].splitlines()]
runs = []
all_results: dict[str, list[dict[str, object]]] = defaultdict(list)

for directory, group, repetition, exit_code in zip(
    directories, groups, repetitions, exit_codes, strict=True
):
    root = Path(directory)
    summary_path = root / "summary.json"
    results_path = root / "results.jsonl"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else None
    results = []
    if results_path.is_file():
        results = [
            json.loads(line)
            for line in results_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    all_results[group].extend(results)
    runs.append(
        {
            "group": group,
            "repetition": repetition,
            "output_dir": str(root),
            "exit_code": exit_code,
            "summary": summary,
            "task_count": len(results),
            "steps": sum(int(item.get("steps", 0)) for item in results),
            "input_tokens": sum(int(item.get("input_tokens", 0)) for item in results),
            "output_tokens": sum(int(item.get("output_tokens", 0)) for item in results),
            "cost_usd": sum(float(item.get("cost_usd", 0.0)) for item in results),
        }
    )


def count(group: str, field: str, value: object = True) -> int:
    return sum(item.get(field) == value for item in all_results[group])


def total(group: str, field: str) -> int:
    return sum(int(item.get(field, 0) or 0) for item in all_results[group])


f03 = all_results["F03"]
b01 = all_results["B01"]
full = all_results["11task"]
per_task_success = Counter(
    str(item.get("task_id")) for item in full if item.get("success") is True
)
checks = {
    "f03_result_count_5": len(f03) == 5,
    "f03_success_at_least_4": count("F03", "success") >= 4,
    "f03_max_steps_0": count("F03", "failure_category", "max_steps") == 0,
    "f03_operational_failures_0": sum(
        count("F03", "failure_category", category)
        for category in (
            "provider_blocked",
            "sandbox_unavailable",
            "verification_environment_failed",
            "invalid_final_output",
        )
    ) == 0,
    "f03_workspace_mutation_0": total("F03", "verification_workspace_mutations") == 0,
    "b01_result_count_2": len(b01) == 2,
    "b01_success_2_of_2": count("B01", "success") == 2,
    "b01_control_false_negative_0": count("B01", "failure_category", "no_source_progress") == 0,
    "full_result_count_33": len(full) == 33,
    "full_security_33": count("11task", "security_passed") == 33,
    "full_success_at_least_90_percent": count("11task", "success") / max(1, len(full)) >= 0.90,
    "full_each_task_at_least_2_of_3": len(per_task_success) == 11 and min(per_task_success.values()) >= 2,
    "full_control_false_negative_0": count("11task", "failure_category", "no_source_progress") == 0,
    "full_workspace_mutation_0": total("11task", "verification_workspace_mutations") == 0,
}

task_success = {
    group: dict(Counter(str(item.get("task_id")) for item in items if item.get("success") is True))
    for group, items in all_results.items()
}
metrics = {
    group: {
        "result_count": len(items),
        "success_count": sum(item.get("success") is True for item in items),
        "failure_categories": dict(Counter(str(item.get("failure_category")) for item in items if item.get("failure_category") is not None)),
        "first_patch_step_count": sum(item.get("first_patch_step") is not None for item in items),
        "first_patch_step_by_task": {
            task_id: [item.get("first_patch_step") for item in items if str(item.get("task_id")) == task_id]
            for task_id in sorted({str(item.get("task_id")) for item in items})
        },
        "pre_edit_step_count": sum(int(item.get("pre_edit_step_count", 0) or 0) for item in items),
        "pre_edit_tool_call_count": sum(int(item.get("pre_edit_tool_call_count", 0) or 0) for item in items),
        "progress_advisory_count": sum(int(item.get("progress_advisory_count", 0) or 0) for item in items),
        "progress_advisory_level_counts": {
            level: sum(
                int((item.get("progress_advisory_level_counts") or {}).get(level, 0))
                for item in items
            )
            for level in ("1", "2")
        },
        "no_source_progress_pause_count": sum(int(item.get("no_source_progress_pause_count", 0) or 0) for item in items),
        "max_no_source_progress_streak": max(
            (int(item.get("max_no_source_progress_streak", 0) or 0) for item in items),
            default=0,
        ),
        "environment_inspection_count": sum(int(item.get("environment_inspection_count", 0) or 0) for item in items),
        "first_environment_inspection_step_count": sum(
            item.get("first_environment_inspection_step") is not None for item in items
        ),
        "first_environment_inspection_step_by_task": {
            task_id: [
                item.get("first_environment_inspection_step")
                for item in items
                if str(item.get("task_id")) == task_id
            ]
            for task_id in sorted({str(item.get("task_id")) for item in items})
        },
        "initial_context_cache_hit_count": sum(int(item.get("initial_context_cache_hit_count", 0) or 0) for item in items),
        "initial_context_reference_hit_count": sum(int(item.get("initial_context_reference_hit_count", 0) or 0) for item in items),
        "source_progress_count": sum(int(item.get("source_progress_count", 0) or 0) for item in items),
        "diagnostic_progress_count": sum(int(item.get("diagnostic_progress_count", 0) or 0) for item in items),
    }
    for group, items in all_results.items()
}
payload = {
    "campaign_root": str(campaign),
    "passed": all(checks.values()),
    "checks": checks,
    "runs": runs,
    "per_task_success": task_success,
    "metrics": metrics,
}
(campaign / "stability_summary.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(payload, ensure_ascii=False, indent=2))
raise SystemExit(0 if payload["passed"] else 1)
PY
aggregate_exit=$?
set -e
exit "${aggregate_exit}"
