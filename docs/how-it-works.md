# How It Works

This page explains how suggestions are generated, when backend choices matter,
and how to run Looptimum in a way that is predictable in real operations.

## Core Loop

Looptimum is a file-backed suggest/evaluate/ingest workflow:

1. `suggest` proposes one trial from bounded parameter space.
2. Your evaluator runs that trial in your environment.
3. `ingest` records the outcome (`ok` or non-`ok`) and updates state.
4. Repeat until budget or stop policy is reached.

State and decision logs are local files, so runs resume across interruptions
without a hosted control plane.

## Backend and Acquisition by Template

| Template | Default backend | Optional backend | Default acquisition |
|---|---|---|---|
| `templates/bo_client_demo` | `rbf_proxy` | none | `ucb` |
| `templates/bo_client` | `rbf_proxy` | `gp` | `ei` |
| `templates/bo_client_full` | `rbf_proxy` | `botorch_gp` (feature flag) | `ucb` |

Operational guidance:

- `rbf_proxy` is the primary baseline for client-controlled environments:
  low dependency overhead, restart-friendly behavior, and predictable ops.
- GP paths are optional and can improve modeling on some objectives, but they
  add dependencies, tuning surface area, and more runtime variability.

For `bo_client_full`, BoTorch GP is optional/feature-flagged and not the
default path. Proxy fallback remains the primary baseline.

## Suggest Policy (Conceptual)

Suggestion behavior has two phases:

1. Warmup (`initial_random`): bounded random sampling for the first
   `initial_random_trials`.
2. Surrogate acquisition (`surrogate_acquisition`): sample a candidate pool,
   score candidates with surrogate + acquisition policy, emit the top score.

This keeps early exploration broad, then shifts to model-guided search once
there is enough signal.

## Exploration vs Exploitation

Main controls:

- `initial_random_trials`: larger values increase early exploration.
- `candidate_pool_size`: larger pools improve best-candidate quality at
  higher compute cost.
- `acquisition.type`: `ucb` or `ei`/`ei_proxy`.
- `acquisition.kappa` and `acquisition.xi`: higher values generally push more
  exploration; lower values push exploitation.

Practical tuning pattern:

- Start with defaults.
- If search locks onto early local regions too fast, increase exploration
  pressure (`kappa`/`xi`) or warmup length.
- If suggestions remain too diffuse late in the run, reduce exploration
  pressure.

## Noisy Objectives (Recommended Default)

Recommended default for noisy objectives:

- Use median-of-k repeats with `k=3` for candidate evaluations.
- Apply repeats only under a re-eval budget policy:
  - top-N candidates, or
  - candidates within epsilon of current best.

This gives a robust baseline without tripling every trial cost.

Alternatives (brief):

- mean-of-k
- trimmed mean
- replication-on-promotion (re-test only near deployment thresholds)
- heteroscedastic-aware policies (advanced; usually requires custom handling)

## Constraints and Failure Policy

> No native hard-constraint solver in `v0.2.x`/`v0.3.0`; use bounds + penalty + failure policy.

Sanctioned pattern:

1. Bounds for always-invalid regions.
2. Penalty shaping for soft constraints and tradeoff pressure.
3. Explicit fail-fast policy for non-evaluable regions (ingest non-`ok` with
   contract-consistent payload semantics).

## Known Pathologies and Failure Modes

| Scenario | What happens | Mitigation |
|---|---|---|
| High-dimensional space with weak structure | Candidate pool under-covers useful regions | Tighten bounds, reduce active dimensions, increase budget carefully |
| Heavy objective noise | Ranking instability and churn near top candidates | Use median-of-k default with re-eval budget policy |
| Conditional/discontinuous spaces | Surrogate assumptions degrade | Encode safe bounds, use explicit penalties/fail-fast policy |
| Optional GP dependency/runtime variance | Behavior shifts by dependency stack | Prefer proxy baseline unless GP benefits are validated in your environment |
| Frequent evaluator failures/timeouts | Effective trial budget collapses | Strengthen failure policy, improve evaluator reliability, tune penalty policy |

## Determinism Boundaries

| Deterministic anchor (if config/state/backend are fixed) | Not fully deterministic |
|---|---|
| Trial id sequence and state progression | Wall-clock timestamps |
| Seed persistence in `state.meta.seed` | External evaluator runtime randomness |
| Suggestion order for stable local path | Optional GP numeric/runtime differences across dependency versions |
| Logged decision chronology in `acquisition_log.jsonl` | System-level scheduling and environment drift outside controller state |

## Math Appendix (Optional)

<details>
<summary>Canonical EI/UCB formulas and proxy-scoring note</summary>

UCB (maximize frame):

`UCB(x) = mu(x) + kappa * sigma(x)`

EI (minimize frame, conceptual):

`EI(x) = E[max(0, f_best - f(x) - xi)]`

Proxy-scoring note:

- Proxy backends estimate `mu(x)` and `sigma(x)` from distance-weighted signal
  over observed points (RBF-style weighting), then apply the chosen
  acquisition heuristic.
- The appendix is intentionally minimal; operational behavior is driven by the
  config knobs and runtime policies above.

</details>

## Related Docs

- `docs/integration-guide.md`
- `docs/operational-semantics.md`
- `docs/decision-trace.md`
- `docs/search-space.md`
