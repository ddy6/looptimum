# Security and Data Handling (Detailed)

This document expands on `SECURITY.MD` and describes the intended operating
model for using the optimization templates in client-controlled environments.

It focuses on practical data-handling boundaries and integration constraints, not legal certification.

## Design Intent

The repository is designed to support:

- local execution
- offline / air-gapped execution
- file-backed state and auditability
- minimal data requirements for optimization loops

The system does not require a hosted orchestration service to function.

## Data Minimization by Contract

The optimization loop only needs a small contract surface to operate:

- suggested parameter values
- one primary objective value per completed trial (`number` for `ok`, `null` for non-`ok`)
- trial status (`ok`, `failed`, `killed`, or `timeout`)

This supports a data-minimization-first integration pattern.

## Typical Local Artifacts

Template runs commonly produce local files such as:

- `state/bo_state.json`
- `state/observations.csv`
- `state/acquisition_log.jsonl`

These files are intended to remain on the client machine unless explicitly shared.

## Recommended Data Handling Practices

### Share only what is needed

Prefer sharing:

- parameter values
- scalar objective values
- run status

Avoid sharing by default:

- raw simulation outputs
- proprietary models
- sensitive logs
- credentials/secrets
- internal file paths or infrastructure identifiers

### Keep sensitive context local

If your evaluator generates rich outputs (meshes, traces, datasets, model
artifacts), keep them in the client environment unless there is a clear need to
export them.

### Use neutral naming when appropriate

If needed, parameter names and objective labels can be anonymized in shared
artifacts while preserving bounds and semantics.

## Offline / Air-Gapped Operation

The templates and client harness pattern are compatible with restricted environments where:

- outbound internet access is disabled
- execution must occur on client-managed infrastructure
- only file-based handoff is allowed

Practical implication:

- `suggest` and `ingest` run locally
- your evaluator runs locally (or inside your own cluster)
- result payloads are written to local files and ingested locally

## Secrets and Credentials

The templates are not a secret-management system (by design).

Recommended practices:

- do not hardcode secrets in repo files
- do not place secrets in result payloads
- use client-approved secret storage (environment variables, vaults, mounted credentials, etc.)
- redact secrets from logs before sharing

## Logging and Auditability

The templates support local auditability through persistent state and logs.

Examples:

- acquisition decision logging (`acquisition_log.jsonl`)
- resumable run state (`bo_state.json`)
- flattened observation history (`observations.csv`)

This supports:

- reproducibility
- post-run review
- interruption recovery
- traceability from suggestion to ingest

## Failure Handling and Sensitive Outputs

Failed trials should still be represented in the optimization loop using a minimal failed payload when possible:

- `trial_id`
- original `params`
- non-`ok` `status` (`failed`, `killed`, or `timeout`)
- primary objective set to `null`
- optional numeric `penalty_objective` when needed

Keep detailed stack traces, command outputs, or internal diagnostics in local
client logs rather than the optimization payload unless intentionally needed.

## Sharing Models and Results Externally (If Applicable)

Before sharing any artifacts externally, define:

- what can be shared
- who can access it
- retention duration
- how data should be anonymized/redacted

This should be agreed before pilot work begins, especially for regulated or
proprietary environments.

## NDA / Confidentiality Workflow

An NDA can be used when required.

Recommended sequence:

1. high-level discovery (possibly redacted)
2. NDA execution (if needed)
3. technical intake (`intake.md`)
4. integration planning and pilot setup

This repo is intentionally structured so technical scoping can happen with
limited information when possible.

## Client Responsibilities (Environment/Compliance)

Clients remain responsible for:

- access control
- network policy
- host hardening
- data classification
- retention policy
- regulatory/compliance requirements

## Scope Boundaries

This document does not claim:

- formal security certification
- compliance certification
- managed hosting controls

It describes a local, minimal-data workflow pattern that can fit cleanly into client-controlled environments.

## Related Docs

- `SECURITY.MD`
- `intake.md`
- `docs/integration-guide.md`
- `client_harness_template/README_INTEGRATION.md`
