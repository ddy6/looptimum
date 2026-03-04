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

## Testing

Run canonical tests from repo root:

```bash
python3 -m pytest -q templates client_harness_template/tests
```

Optional GP backend test:

```bash
RUN_GP_TESTS=1 python3 -m pytest -q templates/bo_client/tests/test_suggest.py::test_suggest_works_with_gp_backend
```

## Validation Workflow

Run this full pre-push/pre-PR validation flow from repo root:

```bash
python3 -m ruff format --check .
python3 -m ruff check .
python3 -m pytest -q templates client_harness_template/tests
python3 scripts/check_internal_links.py
python3 templates/bo_client/run_bo.py validate --project-root templates/bo_client
python3 templates/bo_client_demo/run_bo.py validate --project-root templates/bo_client_demo
python3 templates/bo_client_full/run_bo.py validate --project-root templates/bo_client_full
```

## Pull Requests

Please include:

- a concise description of behavior changes
- tests for new behavior or bug fixes
- documentation updates when contracts/commands change

Avoid adding environment-specific absolute paths or local/private references to tracked files.
