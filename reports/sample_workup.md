# Sample Workup (Pilot-Style)

This is a reusable report structure based on a real local demo run. It is not a client performance claim.

## 1. Run Provenance

- Template variant: `templates/bo_client_demo`
- Snapshot data source: `docs/examples/state_snapshots/`
- Source commit (when this sample was captured): `b6b6bf1`
- Snapshot timestamp (UTC): `2026-02-25T19:57:45Z`
- Command pattern used for this run:
  - `python3 templates/bo_client_demo/run_bo.py demo --project-root templates/bo_client_demo --steps 20`
- Seed from config: `17`
- Environment: local development machine (demo synthetic objective)

## 2. Problem Statement

Objective:

- Minimize scalar `loss` over a 2-parameter bounded space (`x1`, `x2`)

Purpose of this sample:

- show a practical readout structure
- tie claims to explicit run evidence
- define concrete next-step decision gates

## 3. Optimization Setup Summary

- Loop contract: file-backed `suggest -> evaluate -> ingest`
- State artifacts:
  - `bo_state.json`
  - `observations.csv`
  - `acquisition_log.jsonl`
- Parameter space:
  - `x1`: float in `[0.0, 1.0]`
  - `x2`: float in `[0.0, 1.0]`
- Objective: `loss` (`minimize`)
- Config values used:
  - `max_trials = 40`
  - `initial_random_trials = 6`
  - acquisition: proxy UCB
- Executed evaluations in this sample: `20`

## 4. Evaluation Results (Rounded)

- Completed evaluations: `20`
- Successful evaluations: `20`
- Failed evaluations: `0`
- Best trial: `19`
- Best observed `loss`: `-0.02431`
- Trial 1 `loss` (baseline reference): `0.21111`
- Absolute improvement vs trial 1: `0.23542`
- Relative improvement vs trial 1: `111.5%`

Note: The toy objective can produce negative values. Relative improvement is shown only as a directional summary.

## 5. Convergence Evidence

Best-so-far loss at selected checkpoints:

| eval count | best-so-far loss |
|---|---:|
| 1 | 0.21111 |
| 3 | 0.03128 |
| 5 | 0.03128 |
| 10 | -0.00799 |
| 15 | -0.00799 |
| 20 | -0.02431 |

Observed step changes from this run:

- Eval `1 -> 3`: improvement of `0.17983`
- Eval `5 -> 10`: improvement of `0.03928`
- Eval `15 -> 20`: improvement of `0.01631`

Interpretation tied to data:

- Largest gain happened early (1 to 3).
- Mid-run plateau appears (3 to 5 and 10 to 15).
- Later improvement still occurred by eval 20.

## 6. Best-Found Configuration

Best observed trial (`trial_id=19`):

- `x1 = 0.49370`
- `x2 = 0.99675`
- `loss = -0.02431`

## 7. Reliability / Traceability Checks

Artifacts expected from this run pattern are present in snapshots:

- pending/observation transitions are represented in state files
- acquisition decisions are present in JSONL
- flattened observation export is present in CSV

These checks support replayability of the run narrative and post-run inspection.

## 8. Uncertainty and Limits

This sample is useful for format and workflow validation, but has strict limits:

- objective is synthetic (not a production evaluator)
- no runtime failures occurred in this run
- 2D search space is simpler than most client problems
- no measurement noise model was exercised

Because of these limits, the result should be treated as a process example, not performance evidence.

## 9. Decision Gates For A Real Pilot

Use explicit gates before moving from pilot to broader rollout:

1. Integration reliability gate:
   - `suggest -> ingest` loop completes without manual state repair
   - restart/resume works after interruption
2. Optimization signal gate:
   - best-so-far improves beyond initialization and does not regress after objective-definition review
3. Operational gate:
   - failure policy is documented (`status`, sentinel behavior, retry/timeout policy)
   - run logs are sufficient for root-cause review

If any gate is not met, pause scaling and fix integration or objective framing first.

## 10. Reuse Checklist

When adapting this report for real client work, replace:

- toy objective text with client objective definition
- toy parameter names with client parameter names
- checkpoint table with actual campaign checkpoints
- decision gates with client-specific thresholds and SLAs
