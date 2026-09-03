#!/usr/bin/env bash
set -euo pipefail

umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PYTHON="${REPO_ROOT}/.venv/bin/python"
SUITE="${REPO_ROOT}/evals/week4/agent_task_suite_v1.jsonl"
RUNS=3
OUTPUT_ROOT=""
WORKTREE_ROOT=""
KEEP_WORKSPACES=false
DRY_RUN=false

usage() {
  printf '%s\n' \
    "Usage: scripts/run_11task_stability.sh [options]" \
    "" \
    "Repeat the complete 11-task dev suite through the production single Agent Runtime." \
    "" \
    "Options:" \
    "  --runs N                Number of complete suite runs (default: 3)" \
    "  --output-root PATH      Campaign output directory" \
    "  --worktree-root PATH    Docker-shareable execution root" \
    "  --keep-workspaces       Keep task worktrees after each run" \
    "  --dry-run               Print commands without calling the provider" \
    "  -h, --help              Show this help"
}

require_positive_integer() {
  local name="$1"
  local value="$2"
  if [[ ! "${value}" =~ ^[1-9][0-9]*$ ]]; then
    printf '%s must be a positive integer: %s\n' "${name}" "${value}" >&2
    exit 2
  fi
}

while (($#)); do
  case "$1" in
    --runs)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      RUNS="$2"
      shift 2
      ;;
    --output-root)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      OUTPUT_ROOT="$2"
      shift 2
      ;;
    --worktree-root)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      WORKTREE_ROOT="$2"
      shift 2
      ;;
    --keep-workspaces)
      KEEP_WORKSPACES=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
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

require_positive_integer "--runs" "${RUNS}"
[[ -x "${PYTHON}" ]] || {
  printf 'Project Python is missing or not executable: %s\n' "${PYTHON}" >&2
  exit 2
}

task_count="$(${PYTHON} -c '
import json
import sys
from pathlib import Path

count = 0
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if line.strip() and json.loads(line).get("split") == "dev":
        count += 1
print(count)
' "${SUITE}")"
if [[ "${task_count}" -ne 11 ]]; then
  printf 'Expected exactly 11 dev tasks, found %s in %s\n' \
    "${task_count}" "${SUITE}" >&2
  exit 2
fi

if [[ -z "${OUTPUT_ROOT}" ]]; then
  OUTPUT_ROOT="${REPO_ROOT}/evals/week5/agent_runs/11task_single_stability_$(date +%Y%m%d_%H%M%S)"
elif [[ "${OUTPUT_ROOT}" != /* ]]; then
  OUTPUT_ROOT="${REPO_ROOT}/${OUTPUT_ROOT}"
fi

export CODETEAM_LLM_TEMPERATURE="${CODETEAM_LLM_TEMPERATURE:-0}"
export CODETEAM_LLM_RESPONSE_MODE="${CODETEAM_LLM_RESPONSE_MODE:-auto}"

failures=0
if [[ "${DRY_RUN}" == "false" ]]; then
  mkdir -p "${OUTPUT_ROOT}"
  printf 'iteration\tcommand_exit\tsuccess_count\ttask_count\tall_succeeded\toutput_dir\n' \
    > "${OUTPUT_ROOT}/runs.tsv"
fi

for ((iteration = 1; iteration <= RUNS; iteration += 1)); do
  run_dir="${OUTPUT_ROOT}/run_$(printf '%02d' "${iteration}")"
  command=(
    "${PYTHON}" -m codeteam.cli.app agent-eval
    --suite "${SUITE}"
    --output "${run_dir}"
    --actor llm
    --mode baseline
    --split dev
    --context-budget 8192
    --max-steps 20
    --max-output-tokens 4096
    --model-context-window 32768
    --safety-headroom-tokens 1024
    --native-tools
    --no-reasoning
  )
  [[ "${KEEP_WORKSPACES}" == "false" ]] || command+=(--keep-workspaces)
  [[ -z "${WORKTREE_ROOT}" ]] || command+=(--worktree-root "${WORKTREE_ROOT}")

  if [[ "${DRY_RUN}" == "true" ]]; then
    printf 'RUN %d/%d\nCOMMAND' "${iteration}" "${RUNS}"
    printf ' %q' "${command[@]}"
    printf '\nOUTPUT %s\n\n' "${run_dir}"
    continue
  fi

  mkdir -p "${run_dir}"
  printf '\n=== 11-task single Agent run %d/%d ===\n' "${iteration}" "${RUNS}"
  set +e
  (cd "${REPO_ROOT}" && "${command[@]}") 2>&1 | tee "${run_dir}/console.log"
  command_exit=${PIPESTATUS[0]}
  set -e

  counts="$(${PYTHON} -c '
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except (OSError, ValueError):
    print("0 0")
else:
    print(int(payload.get("success_count", 0)), int(payload.get("total_task_results", 0)))
' "${run_dir}/combined_summary.json")"
  read -r success_count actual_task_count <<< "${counts}"
  all_succeeded=false
  if [[ "${command_exit}" -eq 0 && "${success_count}" -eq 11 && "${actual_task_count}" -eq 11 ]]; then
    all_succeeded=true
  else
    failures=$((failures + 1))
  fi

  printf '%d\t%d\t%d\t%d\t%s\t%s\n' \
    "${iteration}" "${command_exit}" "${success_count}" "${actual_task_count}" \
    "${all_succeeded}" "${run_dir}" >> "${OUTPUT_ROOT}/runs.tsv"
done

if [[ "${DRY_RUN}" == "true" ]]; then
  printf 'No provider calls were made.\n'
  exit 0
fi

printf '\n11-task stability campaign: %d complete passes, %d incomplete runs\n' \
  "$((RUNS - failures))" "${failures}"
printf 'Results: %s\n' "${OUTPUT_ROOT}"
[[ "${failures}" -eq 0 ]]
