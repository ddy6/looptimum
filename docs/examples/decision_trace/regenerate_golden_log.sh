#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

OUTPUT_PATH="${REPO_ROOT}/docs/examples/decision_trace/golden_acquisition_log.jsonl"

python3 "${REPO_ROOT}/examples/toy_objectives/03_tiny_quadratic_loop/run_tiny_loop.py" \
  --steps 8 \
  --write-acquisition-log "${OUTPUT_PATH}" \
  --normalize-acquisition-timestamps

line_count="$(wc -l < "${OUTPUT_PATH}" | tr -d ' ')"
if [[ "${line_count}" -ne 8 ]]; then
  echo "Expected 8 log records, found ${line_count} in ${OUTPUT_PATH}" >&2
  exit 1
fi

surrogate_count="$(grep -c '"strategy": "surrogate_acquisition"' "${OUTPUT_PATH}" || true)"
if [[ "${surrogate_count}" -lt 1 ]]; then
  echo "Expected at least one surrogate_acquisition record in ${OUTPUT_PATH}" >&2
  exit 1
fi

echo "Regenerated ${OUTPUT_PATH} (${line_count} lines; ${surrogate_count} surrogate record(s))."
