# Campaign Runtime Reconstruction

This sanitized note reconstructs the effective campaign setup used for the
public case study.

## Runtime-Critical Files

- example evaluator logic
- public template `run_one_eval.py`
- project `parameter_space.json`
- project `bo_config.json`

## Search Space

The campaign iterated five knobs:

- `castellatedMeshControls.nCellsBetweenLevels`: `[1, 3]`
- `refinementSurfaces.pipe_level_mode`: `[1, 2]`
- `refinementRegions.distance_mode`: `[1, 4]`
- `snapControls.nSmoothPatch`: `[5, 7]`
- `snapControls.tolerance_mode`: `[1, 3]`

Mode mappings:

- `pipe_level_mode`
  - `1 -> focus surface level (1 1)`
  - `2 -> focus surface level (2 2)`
- `distance_mode`
  - `1 -> ((0.00025 1))`
  - `2 -> ((0.00025 2) (0.00075 1))`
  - `3 -> ((0.0005 2) (0.0015 1))`
  - `4 -> ((0.00075 2) (0.0025 1))`
- `tolerance_mode`
  - `1 -> 0.15`
  - `2 -> 0.5`
  - `3 -> 1.0`

Fixed settings:

- non-focus surface regions fixed at `level (2 2)`
- `snapControls.nFeatureSnapIter = 10`

## BO Config

- `seed = 17`
- `max_trials = 40`
- `initial_random_trials = 8`
- `candidate_pool_size = 300`
- surrogate: `rbf_proxy`
- acquisition: `ei`
- `batch_size = 1`

## Archived Objective

Campaign minimized a scalar mesh-quality loss with these terms:

- underdetermined-cell penalty
- low-weight-face penalty
- severe non-orthogonality penalty
- warped-face penalty
- cell-count penalty only when `total_cells > 250000`
- optional solver-smoke penalty if the smoke run did not reach its target end
  time

Important archived behavior:

- campaign did not add a direct scalar penalty for failed `checkMesh` status
- therefore a very low archived loss did not automatically guarantee
  `checkMesh` cleanliness

That nuance matters for the selected public case:

- archived trial `15` achieved `loss = 9.0`
- archived trial `15` still recorded `1` failed `checkMesh` check
- post-hoc solver validation was then used to confirm acceptability

## Public Validated Case

The public selected case is campaign trial `15`.

Why it is acceptable for the public case study:

- it met the coarse-mesh objective target
- it completed a post-hoc solver run to the target end time
- fine-versus-coarse aggregate pressure and pulse-pressure drifts stayed within
  `0.5 mmHg`
- all major outlet-flow drifts stayed within `1%`
