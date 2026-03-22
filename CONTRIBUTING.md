# Contributing

## Scope

This repository focuses on file-based optimization template workflows under `templates/`.
Contributions should keep the public integration contract clear and stable:

- `suggest`
- `ingest`
- `status`
- `demo`

## Development Setup

```bash
python3 -m pip install -r requirements-dev.txt
```

For local work on the optional AWS Batch executor path, also install:

```bash
python3 -m pip install ".[aws]"
```

## Linting and Formatting

Run formatting first, then lint checks:

```bash
python3 -m ruff format .
python3 -m ruff check .
```

Install and run pre-commit hooks:

```bash
python3 -m pre_commit install
python3 -m pre_commit run --all-files
```

## Type Checking

Run the canonical type-check gate:

```bash
python3 -m mypy
```

Current enforced scope is intentionally narrow and canonical-first:

- `service/*.py`
- `templates/_shared/*.py`
- `templates/bo_client/run_bo.py`
- `client_harness_template/aws_*.py`
- `client_harness_template/objective_aws_batch_example.py`
- `client_harness_template/run_one_eval.py`
- `client_harness_template/starterkit_*.py`

`Any` policy:

- allowed only at explicit boundaries (JSON/file I/O, optional YAML paths, or
  weakly typed external library boundaries)
- otherwise avoid `Any`; use `TypedDict`/`Protocol`/dataclasses where practical
- if `Any` is unavoidable, keep it narrow and include a TODO for tightening

## Testing

Run canonical tests from repo root:

```bash
python3 -m pytest -q templates client_harness_template/tests service/tests
```

If `boto3` is installed, `client_harness_template/tests/test_aws_executor.py`
also exercises the executor against the real library stack with mocked clients
and no live AWS calls.

Optional GP backend test:

```bash
RUN_GP_TESTS=1 python3 -m pytest -q templates/bo_client/tests/test_suggest.py::test_suggest_works_with_gp_backend
```

## Validation Workflow

Run this full pre-push/pre-PR validation flow from repo root:

```bash
python3 -m ruff format --check .
python3 -m ruff check .
python3 -m mypy
python3 -m pytest -q templates client_harness_template/tests service/tests
python3 scripts/check_internal_links.py --paths README.md docs quickstart client_harness_template
python3 scripts/check_docs_consistency.py
python3 scripts/check_ci_playbook_sync.py
python3 scripts/check_benchmark_sanity.py
python3 templates/bo_client/run_bo.py validate --project-root templates/bo_client
python3 templates/bo_client_demo/run_bo.py validate --project-root templates/bo_client_demo
python3 templates/bo_client_full/run_bo.py validate --project-root templates/bo_client_full
python3 scripts/release_smoke.py
```

For manual smoke fallback commands, see
`quickstart/README.md` ("Release Smoke Checks (Automated + Manual)").

## Pull Requests

Please include:

- a concise description of behavior changes
- tests for new behavior or bug fixes
- documentation updates when contracts/commands change

Avoid adding environment-specific absolute paths or local/private references to tracked files.
