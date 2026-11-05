# Type Safety

This document describes the current typing policy and CI gate for canonical
runtime, service, harness and selected tooling surfaces.

## Checker and Gate Scope

Type-checking tool: `mypy`.

Current blocking CI gate scope, configured in `pyproject.toml`:

- `benchmarks/backend_comparison/*.py`, `benchmarks/ax_capabilities/*.py`
- `examples/ax_pipeline_tuning/*.py`
- `scripts/check_release.py`
- `service/*.py`
- `templates/_shared/*.py`
- `templates/bo_client/run_bo.py`
- `client_harness_template/aws_*.py`
- `client_harness_template/objective_aws_batch_example.py`
- `client_harness_template/run_one_eval.py`
- `client_harness_template/starterkit_*.py`

Gate runtime for CI: Python `3.12`. Install from `requirements-dev.txt` in a
lean environment without Torch, BoTorch or Ax. An optional numerical environment
can hide missing-import errors and does not substitute for this gate.
Inherited `PYTHONPATH`, `PYTHONHOME` or `PYTHONUSERBASE` settings can also select
packages outside an activated environment. Clear those overrides for local
validation and any child processes it launches.

## Strictness Profile

The configured flags require typed definitions and explicit boundary handling
without applying global strict mode to every repository file.

Current emphasis:

- optional handling (`None`-safety)
- boundary shape mismatches for payload/state dictionaries
- path/file boundary typing
- dead/incorrect type-ignore cleanup
- explicit generic/container typing (`disallow_any_generics`)
- fully typed function signatures in gated modules (`disallow_untyped_defs`)
- no implicit module re-export leakage (`no_implicit_reexport`)
- no implicit `Any` returns from typed functions (`warn_return_any`)

The narrow overrides for legacy surrogate/acquisition modules and optional
imports are recorded in `pyproject.toml`; they are not blanket permission to
suppress new errors.

## `Any` Usage Policy

Allowed `Any` boundaries:

- JSON/file I/O ingestion/serialization boundaries
- weakly typed external library boundaries

Outside those boundaries, `Any` is not allowed unless it is narrowly justified
with an inline comment and a tightening TODO.

Preferred alternatives:

- `TypedDict` for payload/state schemas
- `Protocol` for structural callable/runtime contracts
- dataclasses for explicit record-like structures

## Suppression Policy

Suppressions are temporary and allowlist-only:

- keep suppressions narrow (per module/error code where possible)
- do not add global blanket ignores
- each suppression must include a removal target (TODO or issue link)

The default expectation for new code is to pass mypy in-scope without adding
new suppressions.

## Contributor Workflow

From repo root:

```bash
env -u PYTHONPATH -u PYTHONHOME -u PYTHONUSERBASE python3 -m mypy
```

Before opening a PR, run full validation from `CONTRIBUTING.md`.
