# SnappyHexMesh Campaign Case Study

Sanitized domain-specific example showing how Looptimum can drive a bounded
mesh-control campaign and then close the loop with post-hoc solver validation.

This example is intentionally split:

- `project/`: Looptimum project-root config only
- `evaluator/`: environment-specific evaluator logic
- `scripts/`: one-command loop wrapper
- `../../docs/examples/snappyhexmesh_campaign/`: frozen campaign archive and
  validation evidence

## What This Example Shows

- a five-knob bounded search over `snappyHexMeshDict` controls
- file-backed `suggest -> evaluate -> ingest` operation
- transition from initial random trials to surrogate-guided trials
- a selected coarse candidate (`trial 15`) validated against a fine reference
  solve

## Project Layout

- `project/bo_config.json`
- `project/parameter_space.json`
- `project/objective_schema.json`
- `evaluator/objective.py`
- `scripts/run_snappy_loop.sh`

The example uses the public template runtime:

- controller: `../../templates/bo_client/run_bo.py`
- one-eval bridge: `../../client_harness_template/run_one_eval.py`

This keeps the example thin and avoids vendoring a second BO runtime under
`examples/`.

## Environment Requirements

You must provide:

- OpenFOAM commands on `PATH`
- a readable reference case directory
- a writable run root
- an optional resume/smoke helper if you want the smoke-test gating path

Expected environment variables:

- `LOOPTIMUM_SNAPPY_TEMPLATE_CASE_DIR`
- `LOOPTIMUM_SNAPPY_RUN_ROOT`
- `LOOPTIMUM_RESUME_PINGER_PATH`

The evaluator uses placeholder region labels in the public copy. Replace those
labels with the names used by your own `snappyHexMeshDict`.

## Tuned Knobs

- `castellatedMeshControls.nCellsBetweenLevels`
- `refinementSurfaces.pipe_level_mode`
- `refinementRegions.distance_mode`
- `snapControls.nSmoothPatch`
- `snapControls.tolerance_mode`

Mode mappings are documented in
`../../docs/examples/snappyhexmesh_campaign/campaign/c06_config_record.md`.

## Validated Outcome

The selected public example case is `campaign` trial `15`.

Key validation facts:

- archived objective loss: `9.0`
- coarse selected mesh cells: `178473`
- fine reference mesh cells: `658647`
- cell-count reduction: `72.9%`
- fine reference solver wall clock: `1.80645e+06 s`
- selected coarse solver wall clock: `162928 s`
- solver wall-clock reduction: `91.0%`
- solver speedup: `11.1x`
- all major outlet flows stayed within `1%`
- aggregate MAP/PP stayed within `0.5 mmHg`
- archived optimization still recorded `1` failed `checkMesh` check, but the
  post-hoc solver run was accepted based on solver stability and fine-versus-
  coarse agreement

See `../../docs/examples/snappyhexmesh_campaign/case_study.md`.
