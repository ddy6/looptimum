# Type Safety

This document defines the Phase 6 typing policy for public/shared runtime
surfaces and the initial `mypy` enforcement model.

## Checker and Gate Scope

Type-checking tool: `mypy`.

Initial blocking CI gate scope (`v0.3.x` rollout phase 1):

- `templates/_shared/*.py`
- `templates/bo_client/run_bo.py`
- `client_harness_template/aws_*.py`
- `client_harness_template/objective_aws_batch_example.py`
- `client_harness_template/run_one_eval.py`
- `client_harness_template/starterkit_*.py`

Gate runtime for CI: Python `3.12`.

## Strictness Profile (Phase 6 Start)

The first gate uses staged moderate strictness to catch high-value type errors
without forcing immediate strict-mode purity.

Current emphasis:

- optional handling (`None`-safety)
- boundary shape mismatches for payload/state dictionaries
- path/file boundary typing
- dead/incorrect type-ignore cleanup
- explicit generic/container typing (`disallow_any_generics`)
- fully typed function signatures in gated modules (`disallow_untyped_defs`)
- no implicit module re-export leakage (`no_implicit_reexport`)
- no implicit `Any` returns from typed functions (`warn_return_any`)

Strictness will ratchet tighter after the canonical scope is stable and green.

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
python3 -m mypy
```

Before opening a PR, run full validation from `CONTRIBUTING.md`.
