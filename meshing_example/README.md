# Meshing Example (Advanced, Domain-Specific)

Minimal meshing optimizer example for an OpenFOAM-style workflow (advanced use case).

This folder is an advanced, environment-specific case study and is not part of
the default optimization template quickstart path.

Contents:
- `run_optuna_meshing.py`: meshing-only Optuna runner
- `instructions.json`: runtime config consumed by the runner
  (search space, edit regexes, checkMesh parse regexes, optimizer
  seed/direction)

Use case:
- Tune a small set of `snappyHexMeshDict` parameters
- Run `blockMesh`, `snappyHexMesh`, `checkMesh`
- Score meshes from `checkMesh` output (no CFD solve)

Requirements:
- Python 3.10+
- `optuna` installed (`python3 -m pip install optuna`)
- OpenFOAM shell with `blockMesh`, `snappyHexMesh`, `checkMesh` available

Paths (replace with your environment values):
- Template case: `/path/to/template_case`
- Output root: `/path/to/meshopt_output`

## Dry Run (no OpenFOAM commands executed)
```bash
python3 meshing_example/run_optuna_meshing.py \
  --single \
  --dry-run \
  --no-notify \
  --instructions-json meshing_example/instructions.json \
  --template-case-dir /path/to/template_case \
  --out-root /path/to/meshopt_output \
  --study-name snappy_mediumMesh_meshopt_v1_dryrun \
  --db-path /path/to/meshopt_output/BO_logs/optuna_meshing_dryrun.db
```

## Single Real Mesh Trial
```bash
python3 meshing_example/run_optuna_meshing.py \
  --single \
  --instructions-json meshing_example/instructions.json \
  --template-case-dir /path/to/template_case \
  --out-root /path/to/meshopt_output \
  --study-name snappy_mediumMesh_meshopt_v1 \
  --db-path /path/to/meshopt_output/BO_logs/optuna_meshing.db
```

## 3-Trial Smoke Test (resume an existing real study)
```bash
python3 meshing_example/run_optuna_meshing.py \
  --n-trials 3 \
  --resume \
  --instructions-json meshing_example/instructions.json \
  --template-case-dir /path/to/template_case \
  --out-root /path/to/meshopt_output \
  --study-name snappy_mediumMesh_meshopt_v1 \
  --db-path /path/to/meshopt_output/BO_logs/optuna_meshing.db
```
