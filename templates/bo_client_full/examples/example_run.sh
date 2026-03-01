#!/usr/bin/env bash
set -euo pipefail

if [ -f state/bo_state.json ]; then
  if ! python3 -c 'import json, pathlib, sys; p = pathlib.Path("state/bo_state.json"); s = json.loads(p.read_text(encoding="utf-8")); sys.exit(0 if (len(s.get("observations", [])) == 0 and len(s.get("pending", [])) == 0) else 1)'; then
    echo "This script expects a clean state (0 observations, 0 pending)." >&2
    echo "Remove state artifacts or run from a fresh template copy." >&2
    exit 1
  fi
fi

python3 run_bo.py status
python3 run_bo.py suggest

# In a real workflow, an external experiment system produces results JSON.
python3 run_bo.py ingest --results-file examples/example_results.json

python3 run_bo.py status
python3 run_bo.py demo --steps 5

echo
echo "Optional: try GP backend suggestion on a prepared run:"
echo "python3 run_bo.py suggest --enable-botorch-gp --json-only"
