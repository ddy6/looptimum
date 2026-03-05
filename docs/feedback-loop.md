# Feedback Loop

This document defines the post-`v0.2.0` feedback intake and backlog workflow.

## Source of Truth

Primary system of record: GitHub Issues.

- First-impression intake template:
  `.github/ISSUE_TEMPLATE/first-impressions.yml`
- Optional community Q&A channel: GitHub Discussions (secondary only)

## Triage Workflow

1. Intake: collect feedback through GitHub Issues using the first-impression template.
2. Labeling: apply `first-impression` plus one category label (`docs`, `bug`, `question`, `enhancement`).
3. Triage decision (required): every new issue gets exactly one of:
   - label + next-step request for missing repro details,
   - label + linked fix (commit/PR),
   - close with short reason + pointer to docs/alternative path.
4. Milestone mapping: assign to milestone `post-v0.2.0-followups` when actionable.
5. Backlog sync: mirror accepted work into `reports/post_v0.2.0_followup_backlog.md`.
6. Closure: link merged PRs back to the originating issue for traceability.

## Label Baseline (GitHub UI)

- `first-impression`
- `docs`
- `bug`
- `question`
- `enhancement`

## Severity Guidelines

- `bug`: behavior is incorrect, broken, or regressed.
- `docs`: expected path is unclear or missing from docs.
- `question`: clarification is needed before deciding action.
- `enhancement`: useful change that does not fix a defect.

## Review Cadence

- Triage target: first response within 2 business days.
- Backlog grooming: weekly while phase 8 is open; bi-weekly after `v0.2.0` release stabilization.
- Progress summary channel: `reports/README.md`.

## Scope and Close Policy

- Close as out-of-scope when requests expand beyond the current product scope:
  resumable Bayesian optimization harness + workflow.
- Convert "where do I start?" confusion into `docs` issues first when behavior is otherwise correct.

## Security Routing

- If a report is potentially sensitive, do not continue triage in public Issues.
- Redirect reporters to `SECURITY.MD` and continue via the security disclosure path.

## Current Phase 8 State

- Feedback-loop scaffolding is complete.
- Final phase 8 completion still requires external submissions and maintainer
  triage decisions.
- External dependency checklist: `reports/phase8_external_inputs.md`.

## Initial Backlog Seed

The starting post-release backlog is tracked in:

- `reports/post_v0.2.0_followup_backlog.md`

External engineer feedback should be appended there as issue-linked rows after triage.
