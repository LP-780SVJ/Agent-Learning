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
  --max-steps 20
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
"${PYTHON}" -m codeteam.evaluation.stability
aggregate_exit=$?
set -e
exit "${aggregate_exit}"
