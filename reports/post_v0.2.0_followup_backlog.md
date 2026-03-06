# Post-v0.2.0 Follow-Up Backlog

Date opened: 2026-03-04
Last updated: 2026-03-05
Scope: Phase 8 step 73 follow-up queue seeded from current repo review and validated by initial external feedback.
Current release context: active backlog for the `v0.2.x` line (`v0.2.7` current).

## Workflow

Primary intake/source of truth: GitHub Issues.
Triage process: `docs/feedback-loop.md`.

## Seed Backlog (Pre-Feedback)

| Priority | Area | Candidate | Why it matters | Linked issue |
|---|---|---|---|---|
| P1 | Docs | Add explicit release-playbook page with tag/publish commands and rollback notes | Reduces ambiguity for first public release operations | TBD |
| P1 | Docs | Expand quickstart with one complete lifecycle/ops run transcript per variant | Makes non-happy-path behavior easier to trust | TBD |
| P1 | Contract | Add machine-readable state schema references for `doctor` and `report` outputs | Simplifies downstream tooling integration | TBD |
| P2 | CI | Add a dedicated workflow trigger for smoke-only reruns | Faster release-gate verification during docs-only changes | TBD |
| P2 | UX | Add a `--json-only` option for `doctor`/`validate` parity docs examples in quickstart | Improves consistency for automation users | TBD |
| P2 | Adoption | Add a short "time-to-first-signal" section to README with realistic expectations | Improves qualification and trust during evaluation | TBD |

## External Feedback Intake Rows

Append rows below after triage from `first-impression` GitHub issues.

| Date | Issue | Priority | Theme | Action |
|---|---|---|---|---|
| 2026-03-05 | https://github.com/ddy6/looptimum/issues/1 | P2 | First-impression intake validation | Triaged and closed with policy-conformant maintainer decision |
