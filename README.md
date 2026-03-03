# Looptimum

Looping refinement toward an optimum parameter set.

Looptimum provides a file-backed, restart-friendly workflow that can be integrated
into local, offline, or client-controlled environments with minimal surface area.

## What It Is

- Resumable optimization loop templates with a stable CLI contract: `suggest`, `ingest`, `status`, `demo`
- Client integration starter harness (`client_harness_template/`)
- Quickstart notes and integration docs
- Example integration patterns
  (direct Python function and subprocess/CLI wrapper)
- Intake and security/data-handling docs for pilot setup

## 3-Step Workflow

1. `suggest` a parameter set
2. run one evaluation in your environment
3. `ingest` a result payload (`params` + scalar objective + status)

The loop persists state locally and can be resumed after interruptions.

## Quickstart (Single Command)

From the repo root, run a local demo:

```bash
python3 templates/bo_client_demo/run_bo.py demo --project-root templates/bo_client_demo --steps 5
```

For full repo-root commands and resume/state examples, see:

- `quickstart/README.md`

## Why This Exists

Many optimization problems are:

- expensive to evaluate
- black-box (no gradients)
- noisy or failure-prone
- run in restricted environments

The integration surface is intentionally small and only needs:

- parameter values
- one scalar objective value
- trial status (`ok` / `failed`)

Current public templates support `float` and `int` parameter types.

## Templates

### `templates/bo_client_demo`

- Surrogate backend: `rbf_proxy` only
- Dependencies: Python standard library
- Best for: onboarding, contract validation, dependency-light demos

### `templates/bo_client`

- Surrogate backends: `rbf_proxy` (default) or config-selected `gp`
- Dependencies:
  Python standard library; optional PyTorch/BoTorch/GPyTorch for GP mode
- Best for: baseline client integrations (recommended default)

### `templates/bo_client_full`

- Surrogate backends: `rbf_proxy` + optional `botorch_gp`
- Dependencies: optional PyTorch/BoTorch/GPyTorch for GP mode
- Best for:
  same client contract with feature-flag GP behavior in the public template

## Shared Behavior Across Templates

- CLI commands: `suggest`, `ingest`, `status`, `demo`
- Ingest payload validation via JSON schema
- Resumable local state (`state/bo_state.json`)
- Observation export (`state/observations.csv`)
- Append-only acquisition decision trace (`state/acquisition_log.jsonl`)

## Integrating Your Evaluator

Start here:

- `docs/integration-guide.md`
- `client_harness_template/README_INTEGRATION.md`

Helpful related docs:

- `intake.md` (problem scoping checklist)
- `SECURITY.MD` and `docs/security-data-handling.md`
- `docs/faq.md`

## Examples (Integration Patterns)

The `examples/` folder shows integration patterns, not benchmark tasks.

- `examples/toy-objectives/01_python_function/`: direct in-process Python function
- `examples/toy-objectives/02_subprocess_cli/`:
  subprocess/CLI wrapper with scalarization + failure mapping

Domain-specific examples (for example, meshing/OpenFOAM) are best treated as
advanced case studies; they can require specialized environments.

## Testing

Install test dependencies:

```bash
python3 -m pip install -r requirements-dev.txt
```

Run template test suites:

```bash
python3 -m pytest -q templates
```

Optional GP backend validation for `bo_client`:

```bash
RUN_GP_TESTS=1 python3 -m pytest -q \
  templates/bo_client/tests/test_suggest.py::test_suggest_works_with_gp_backend
```

## Automation Note

For machine parsing of `suggest` output, use:

```bash
python3 templates/bo_client_demo/run_bo.py suggest \
  --project-root templates/bo_client_demo \
  --json-only
```
