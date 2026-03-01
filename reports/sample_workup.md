# Sample Workup (Pilot-Style Report)

This is a sample reporting format for an optimization pilot run; think of it as a template, not a claim.

It uses a local toy objective (`templates/bo_client_demo` `demo` mode) to demonstrate report structure, analysis style, and decision-making output. The numbers below are from a reproducible sample run on a temporary copy of the demo template.

## 1. Problem Statement

Objective:

- Minimize a scalar `loss` over a 2-parameter bounded search space (`x1`, `x2`)

Purpose of this sample report:

- show what a pilot readout can look like
- demonstrate convergence interpretation and next-step recommendations
- provide a template for real client-facing workups

## 2. Optimization Setup Summary

### Optimization Template Variant

- `templates/bo_client_demo`

### Loop Contract

- file-backed `suggest -> evaluate -> ingest`
- resumable local state (`bo_state.json`)
- append-only acquisition decision log (`acquisition_log.jsonl`)

### Parameter Space (Toy Example)

- `x1`: float in `[0.0, 1.0]`
- `x2`: float in `[0.0, 1.0]`

### Objective

- primary objective: `loss`
- direction: `minimize`

### Run Configuration (Demo Template Defaults)

- max trial budget: `40`
- initial random trials: `6`
- acquisition: proxy UCB
- sample run executed here: `20` evaluations (demo-mode synthetic evaluator)

## 3. Evaluation Run Summary

### Run Size and Status

- Total completed evaluations: `20`
- Successful evaluations: `20`
- Failed evaluations: `0`

### Best Result

- Best trial ID: `19`
- Best observed objective (`loss`): `-0.024306480195727467`

### Reference Baseline (First Evaluation)

- Trial 1 objective (`loss`): `0.2111145292728927`

### Improvement (Best vs First Observed)

- Absolute improvement: `0.23542100946862016`
- Relative improvement vs first observed value: `111.5%`

Note:

- The toy objective can produce negative values, so percentage improvement is relative to the first observed value and is reported for illustration only.

## 4. Convergence Behavior (Sample Interpretation)

Best-so-far objective by selected evaluation counts:

| eval count | best-so-far loss |
|---|---:|
| 1 | 0.2111145292728927 |
| 3 | 0.03128341826910849 |
| 5 | 0.03128341826910849 |
| 10 | -0.007994595854536726 |
| 15 | -0.007994595854536726 |
| 20 | -0.024306480195727467 |

Observations:

- Rapid early improvement occurred within the first few evaluations.
- Best-so-far improved again by evaluation `10`.
- A smaller later improvement occurred near evaluation `19`.
- This pattern is typical for many expensive black-box problems:
  - fast early gains
  - plateau periods
  - occasional later improvements

## 5. Best-Found Configuration (Sample)

Best observed trial (`trial_id=19`):

- `x1 = 0.4936969718011921`
- `x2 = 0.9967474805735372`
- `loss = -0.024306480195727467`

Interpretation (toy-example specific):

- The optimizer concentrated near a high-`x2` region with selective exploration in `x1`.
- Later-stage suggestions continued to sample near previously promising areas while maintaining some exploration pressure via acquisition scoring.

## 6. Objective Behavior / Trade-Off Notes (Sample)

Even in this toy run, several practical pilot-style observations are visible:

- Some trials produced significantly worse objective values despite nearby promising trials.
- Best results were not found during the initial random phase.
- Continued evaluations after early gains still produced useful improvements.

What this usually suggests in real applications:

- A pilot budget should usually allow room beyond pure initialization.
- Failure/invalid-run handling must be part of the integration design even if the toy objective never fails.
- Resume capability matters because meaningful improvements can happen late in a campaign.

## 7. Reliability and Traceability Notes

This sample run exercised the standard local traceability artifacts:

- resumable state tracking
- flattened observations CSV
- append-only acquisition decision logging

These artifacts help with:

- interruption recovery
- post-run analysis
- auditability of suggestion decisions

## 8. Recommended Next Steps (Pilot-to-Production Pattern)

For a real client pilot, recommended next actions after an initial run like this:

1. Review parameter bounds for over-broad or clearly low-value regions.
2. Validate objective scalarization with domain stakeholders (especially if multiple metrics are involved).
3. Document failure/invalid-run policy explicitly (sentinel values, retry vs fail-fast behavior).
4. Run a second pilot with refined bounds and a larger budget if the first run shows signal.
5. Compare proxy-only vs GP-backed mode only after integration stability is confirmed.

## 9. Template Reuse Notes

This report format can be reused for real client work by replacing:

- toy objective description with client problem statement
- toy parameter names with client parameters
- sample convergence table with actual campaign results
- sample recommendations with domain-specific next steps

## 10. Appendix: Sample Metrics (This Report)

Source summary used in this sample:

- evaluations run: `20`
- best trial: `19`
- best loss: `-0.024306480195727467`
- first loss: `0.2111145292728927`
- best-so-far milestones shown at evals: `1, 3, 5, 10, 15, 20`
