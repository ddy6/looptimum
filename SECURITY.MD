# Security and Data Handling (Basic)

This repository and the Looptimum workflow are designed to support local, client-controlled execution.

## Core Operating Model

- The optimization loop can be run entirely locally/offline.
- File-backed state stays on the client machine by default.
- You do not need a hosted service to use these templates.
- Network access is optional and only relevant if your evaluator itself needs it.

## What Data the Optimization Loop Needs

At minimum, the optimization loop only needs:

- parameter values proposed for a trial
- a scalar objective value returned for that trial
- a simple status (`ok` / `failed`)

This supports data minimization by default.

In practice, the Looptimum CLI contract keeps the required payload small and explicit.

## Default Local Artifacts (Client Machine)

Typical local state files include:

- `state/bo_state.json`
- `state/observations.csv`
- `state/acquisition_log.jsonl`

These remain on the client machine unless the client explicitly chooses to share them.

## Data Minimization Guidance

Recommended practice:

1. Share only parameter values and scalar objectives when possible.
2. Keep raw simulation/model outputs inside the client environment unless needed.
3. Avoid including secrets, credentials, or proprietary internals in result payloads.
4. Use anonymized parameter names if needed for external collaboration.

## Offline / Restricted Environments

The templates are compatible with restricted environments where:

- outbound internet access is blocked
- only local files are permitted
- execution must occur on client-managed infrastructure

The `client_harness_template` is file-based for this reason.

## NDA / Confidentiality

- An NDA can be used when required by the client.
- Scope, handling rules, and retention expectations should be agreed before exchanging sensitive artifacts.
- This repository is intended to enable a minimal-information integration path when possible.

## Secrets and Credentials

- Do not hardcode secrets in template files.
- Use client-approved secret management (env vars, vaults, mounted files, etc.).
- Keep credentials out of optimization state files and result payloads.

## Logging and Auditability

The templates record suggest/ingest transitions for reproducibility and auditability.

- Acquisition decisions are logged in JSONL
- Observations are persisted locally
- Trial IDs support traceability across suggest -> run -> ingest

Clients can extend local logging to meet internal compliance requirements.

## Limitations / Scope

This document is a basic operational note, not a legal or compliance certification.

Clients are responsible for:

- environment hardening
- access control
- network policy
- data classification
- regulatory compliance requirements

## Questions to Clarify Up Front

- Must the system run fully offline?
- What data may leave the environment, if any?
- Is an NDA required before sharing examples or logs?
- Are there prohibited data types (PII/PHI/export-controlled data)?
