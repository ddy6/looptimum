# Feedback Loop

This document defines the post-`v0.2.0` feedback intake and backlog workflow.

## Source of Truth

Primary system of record: GitHub Issues.

- First-impression intake template:
  `.github/ISSUE_TEMPLATE/first_impression_feedback.yml`
- Optional community Q&A channel: GitHub Discussions (secondary only)

## Triage Workflow

1. Intake: collect feedback through GitHub Issues using the first-impression template.
2. Labeling: apply at least one area label (`docs`, `contract`, `runtime`, `tests`, `release`) and one priority label (`p0`, `p1`, `p2`).
3. Milestone mapping: assign to milestone `post-v0.2.0-followups` when actionable.
4. Backlog sync: mirror accepted work into `reports/post_v0.2.0_followup_backlog.md`.
5. Closure: link merged PRs back to the originating issue for traceability.

## Severity Guidelines

- `p0`: trust or contract blockers that can cause failed integrations or unsafe assumptions.
- `p1`: meaningful onboarding friction or workflow pain with practical workarounds.
- `p2`: polish and ergonomics improvements that improve conversion or maintainability.

## Review Cadence

- Triage target: first response within 2 business days.
- Backlog grooming: weekly while phase 8 is open; bi-weekly after `v0.2.0` release stabilization.
- Progress summary channel: `reports/update_program_tracking_issue.md`.

## Initial Backlog Seed

The starting post-release backlog is tracked in:

- `reports/post_v0.2.0_followup_backlog.md`

External engineer feedback should be appended there as issue-linked rows after triage.
