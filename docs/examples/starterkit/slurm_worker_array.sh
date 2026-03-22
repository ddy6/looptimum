#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${SLURM_ARRAY_TASK_ID:-}" ]]; then
  echo "SLURM_ARRAY_TASK_ID is required for the queue-worker starter" >&2
  exit 2
fi

# Controller step (run separately before sbatch):
# python3 /campaign/run_bo.py suggest --project-root /campaign --count 2 --jsonl --fail-fast > /campaign/state/starterkit_suggestions.jsonl
# Submission step:
# sbatch --array 0-1 starterkit_worker_array.sh

python3 /campaign/client_harness_template/starterkit_queue_worker.py /campaign/state/starterkit_suggestions.jsonl --project-root /campaign --work-dir /campaign/state/starterkit_worker_runs --run-bo-script /campaign/run_bo.py --run-one-eval-script /campaign/client_harness_template/run_one_eval.py --objective-schema /campaign/objective_schema.json --worker-index "${SLURM_ARRAY_TASK_ID}"
