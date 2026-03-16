# Run Machine Quickstart

Use this after copying the public repo to the run machine and adapting the
placeholder region labels in `evaluator/objective.py`.

## 1. Set Environment Variables

```bash
export LOOPTIMUM_SNAPPY_TEMPLATE_CASE_DIR=/path/to/reference_case
export LOOPTIMUM_SNAPPY_RUN_ROOT=/path/to/looptimum_mesh_runs
export LOOPTIMUM_RESUME_PINGER_PATH=/path/to/resumePinger.py
```

## 2. Preflight

From repo root:

```bash
command -v python3 blockMesh snappyHexMesh checkMesh
test -f "${LOOPTIMUM_SNAPPY_TEMPLATE_CASE_DIR}/system/snappyHexMeshDict"
mkdir -p "${LOOPTIMUM_SNAPPY_RUN_ROOT}"
python3 templates/bo_client/run_bo.py validate \
  --project-root examples/snappyhexmesh_campaign/project
python3 templates/bo_client/run_bo.py status \
  --project-root examples/snappyhexmesh_campaign/project \
  --json
```

## 3. Start A Short Loop

```bash
bash examples/snappyhexmesh_campaign/scripts/run_snappy_loop.sh 12
```

## 4. Main Outputs

- project state: `examples/snappyhexmesh_campaign/project/state/`
- copied per-trial cases: `${LOOPTIMUM_SNAPPY_RUN_ROOT}/mesh_trial_*/`

## Notes

- The public example does not ship a raw solver binary, a reference case, or
  a smoke helper.
- The public validation package in `docs/examples/snappyhexmesh_campaign/`
  is sanitized and intended for case-study review, not for rerunning the exact
  private setup unchanged.
