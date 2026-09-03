#!/usr/bin/env bash
set -euo pipefail

umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PYTHON="${REPO_ROOT}/.venv/bin/python"
SUITE="${REPO_ROOT}/evals/week4/agent_task_suite_v1.jsonl"
RUNS=2
OUTPUT_ROOT=""
WORKTREE_ROOT=""
KEEP_WORKSPACES=false
DRY_RUN=false

usage() {
  printf '%s\n' \
    "Usage: scripts/run_b01_team_stability.sh [options]" \
    "" \
    "Repeat the Week5 single-worker Team Runtime B01 smoke." \
    "" \
    "Options:" \
    "  --runs N                Number of repetitions (default: 2)" \
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

if [[ -z "${OUTPUT_ROOT}" ]]; then
  OUTPUT_ROOT="${REPO_ROOT}/evals/week5/agent_runs/b01_team_stability_$(date +%Y%m%d_%H%M%S)"
elif [[ "${OUTPUT_ROOT}" != /* ]]; then
  OUTPUT_ROOT="${REPO_ROOT}/${OUTPUT_ROOT}"
fi

export CODETEAM_LLM_TEMPERATURE="${CODETEAM_LLM_TEMPERATURE:-0}"
export CODETEAM_LLM_RESPONSE_MODE="${CODETEAM_LLM_RESPONSE_MODE:-auto}"

failures=0
if [[ "${DRY_RUN}" == "false" ]]; then
  mkdir -p "${OUTPUT_ROOT}"
  printf 'iteration\tcommand_exit\tmanifest_success\toutput_dir\n' \
    > "${OUTPUT_ROOT}/runs.tsv"
fi

for ((iteration = 1; iteration <= RUNS; iteration += 1)); do
  run_dir="${OUTPUT_ROOT}/run_$(printf '%02d' "${iteration}")"
  command=(
    "${PYTHON}" evals/week5/smoke_team_runtime.py
    --suite "${SUITE}"
    --task-id B01
    --runtime team
    --provider openai-compatible
    --plan deterministic-single-node
    --worker-count 1
    --max-concurrency 1
    --context-budget 4096
    --max-output-tokens 4096
    --model-context-window 32768
    --max-steps 20
    --max-tool-calls 40
    --max-repairs 3
    --max-protocol-repairs 2
    --timeout-seconds 900
    --output "${run_dir}"
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
  printf '\n=== B01 Team run %d/%d ===\n' "${iteration}" "${RUNS}"
  set +e
  (cd "${REPO_ROOT}" && "${command[@]}") 2>&1 | tee "${run_dir}/console.log"
  command_exit=${PIPESTATUS[0]}
  set -e

  manifest_success="$(${PYTHON} -c '
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except (OSError, ValueError):
    print("missing")
else:
    print("true" if payload.get("success") is True else "false")
' "${run_dir}/team_smoke_manifest.json")"

  printf '%d\t%d\t%s\t%s\n' \
    "${iteration}" "${command_exit}" "${manifest_success}" "${run_dir}" \
    >> "${OUTPUT_ROOT}/runs.tsv"
  if [[ "${command_exit}" -ne 0 || "${manifest_success}" != "true" ]]; then
    failures=$((failures + 1))
  fi
done

if [[ "${DRY_RUN}" == "true" ]]; then
  printf 'No provider calls were made.\n'
  exit 0
fi

printf '\nB01 Team stability campaign: %d passed, %d failed\n' \
  "$((RUNS - failures))" "${failures}"
printf 'Results: %s\n' "${OUTPUT_ROOT}"
[[ "${failures}" -eq 0 ]]
