#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${EXAMPLE_ROOT}/../.." && pwd)"
PROJECT_ROOT="${EXAMPLE_ROOT}/project"
RUN_BO="${REPO_ROOT}/templates/bo_client/run_bo.py"
RUN_ONE_EVAL="${REPO_ROOT}/client_harness_template/run_one_eval.py"
OBJECTIVE_MODULE="${EXAMPLE_ROOT}/evaluator/objective.py"

MAX_ITERS="${1:-12}"
TMP_ROOT="${TMPDIR:-/tmp}"
SUGGEST_FILE="${TMP_ROOT}/looptimum_snappy_suggestion.json"
RESULT_FILE="${TMP_ROOT}/looptimum_snappy_result.json"

echo "project_root=${PROJECT_ROOT}"
echo "max_iters=${MAX_ITERS}"
echo "suggest_file=${SUGGEST_FILE}"
echo "result_file=${RESULT_FILE}"

for ((iter=1; iter<=MAX_ITERS; iter++)); do
  echo "=== Iteration ${iter}/${MAX_ITERS} ==="

  if ! python3 "${RUN_BO}" suggest --project-root "${PROJECT_ROOT}" --json-only > "${SUGGEST_FILE}"; then
    echo "suggest returned non-zero (likely no remaining budget). stopping."
    break
  fi

  python3 "${RUN_ONE_EVAL}" \
    "${SUGGEST_FILE}" \
    "${RESULT_FILE}" \
    --objective-module "${OBJECTIVE_MODULE}" \
    --objective-schema "${PROJECT_ROOT}/objective_schema.json"

  python3 "${RUN_BO}" ingest \
    --project-root "${PROJECT_ROOT}" \
    --results-file "${RESULT_FILE}"

  python3 "${RUN_BO}" status --project-root "${PROJECT_ROOT}"
done
