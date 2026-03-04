# Pilot Checklist

Use this checklist to scope and execute a Looptimum pilot with clear
responsibilities, realistic evaluation budgets, and auditable deliverables.

This checklist complements `intake.md` and the integration docs. It is intended
for implementation planning, not marketing collateral.

## 1. Entry Checklist (Before Any Run)

Required before pilot execution:

- Named primary objective and direction (`minimize` or `maximize`)
- Parameter list with types and bounds (or explicit extension plan)
- Failure policy for invalid/failed evaluations
- One-evaluation interface definition (function, CLI, API, or job wrapper)
- Evaluation budget range (minimum useful and maximum feasible)
- Runtime/environment constraints (offline, queue, security, dependencies)
- Success criteria for pilot readout

Recommended:

- Known baseline parameter set and baseline objective value
- Known unsafe/invalid regions
- Noise/repeatability notes

## 2. Responsibility Matrix

| Area | Client Team | Looptimum Team | Joint |
|---|---|---|---|
| Objective definition | Own domain objective meaning and acceptance criteria | Review optimization framing | Finalize scalar objective and direction |
| Parameter space | Provide parameter candidates, safe bounds, and constraints | Advise on sample-efficient framing | Freeze pilot parameter set |
| Evaluator integration | Implement/run system-specific evaluation path | Provide harness pattern and payload contract support | Validate one end-to-end trial |
| Runtime operations | Provide environment access, scheduling, and guardrails | Provide command workflow and troubleshooting guidance | Define retry/failure handling |
| Pilot reporting | Provide business/domain context for results | Summarize optimization outcomes and trace artifacts | Agree final interpretation and next-step plan |

## 3. Preflight Validation

Before batch pilot execution, run a one-trial preflight:

1. Generate one suggestion with `--json-only`.
2. Execute exactly one evaluation in target environment.
3. Build ingest payload with exact `trial_id` and `params`.
4. Ingest result and confirm `status` updates.
5. Verify state artifacts:
   - `state/bo_state.json`
   - `state/observations.csv`
   - `state/acquisition_log.jsonl`
   - `state/event_log.jsonl`
   - `state/trials/trial_<id>/manifest.json` for the preflight trial

Do not scale pilot volume before this passes.

## 4. Budget Planning (Evaluation Count, Not Calendar Time)

Budget should be set in evaluation counts first, then translated to timeline.

Pragmatic starting ranges:

- Contract/integration validation: 5-10 evaluations
- Initial pilot learning: 10-30 evaluations
- Stronger optimization signal: 30-100+ evaluations (problem dependent)

Planning factors:

- Number of parameters and bound width
- Objective noise and failure rate
- Runtime per evaluation
- Parallel capacity and queue constraints

## 5. Reproducibility Plan

Capture this before execution:

- Seed strategy for Looptimum templates
- Seed/control strategy in external evaluator (if available)
- Dependency/runtime versions used during pilot
- Rules for reruns and duplicate ingest handling
  (`identical replay -> no-op success`, `conflicting replay -> reject`)

Define deterministic boundaries explicitly:

- What should reproduce exactly (suggestion order, payload schema, state shape)
- What may vary (wall-clock runtime, external stochasticity, GP numerics)

## 6. Failure and Recovery Plan

Agree in advance:

- What non-`ok` statuses you will emit (`failed`, `killed`, `timeout`)
- Failure payload representation (`objective: null` and optional `penalty_objective`)
- Retry policy for transient failures
- Operator workflow when ingest fails validation
- Escalation path when pending trials become stale
- Lifecycle command policy (`cancel`, `retire`, `retire --stale`, `heartbeat`)

This avoids ad hoc policy changes mid-pilot.

## 7. Deliverables at Pilot End

Minimum expected pilot artifacts:

- Best-known parameter set and objective value
- Top trial summary with status breakdown
- `bo_state.json`, `observations.csv`, `acquisition_log.jsonl`, `event_log.jsonl`
- Trial audit manifests under `state/trials/`
- Brief decision log interpretation (warmup, surrogate phase, anomalies)
- Recommended next-step parameter/budget adjustments

Optional:

- Generated `report.json` / `report.md`
- Pilot readout report in Markdown/JSON/slides
- Proposed productionization checklist

## 8. Exit Criteria

A pilot should be considered complete when:

- End-to-end loop is stable (`suggest -> evaluate -> ingest`) in target env
- Objective and failure policy are unambiguous
- Result artifacts are reproducible and auditable
- Stakeholders agree whether to expand, refine, or stop

## 9. Related References

- `intake.md`
- `docs/integration-guide.md`
- `docs/operational-semantics.md`
- `docs/search-space.md`
- `docs/decision-trace.md`
- `docs/security-data-handling.md`
