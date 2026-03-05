# Search Space Contract

This document defines search-space support in current public templates and the
boundaries you should plan around during integration.

## Current Support (All Public Templates)

Current default template implementations support:

- `float` parameters with numeric bounds
- `int` parameters with numeric bounds

Expected parameter entry shape:

```json
{
  "name": "x1",
  "type": "float",
  "bounds": [0.0, 1.0],
  "description": "Optional human-readable note"
}
```

`name`, `type`, and `bounds` are required for runtime sampling behavior.

## Sampling Semantics

### `float`

- Sampled uniformly between lower and upper bounds.
- Bounds are interpreted on a linear scale.

### `int`

- Sampled with inclusive integer bounds.
- Values are whole-number candidates only.

## Log-Scale Parameters

Native log-scale parameter types are not currently implemented.

Pragmatic workaround:

- Define a linear parameter in log-space (example: `log10_lr` in `[-5, -1]`).
- Convert inside your evaluator (`lr = 10 ** log10_lr`) before running.
- Record both transformed and raw values in your own artifacts if needed.

## Categorical and Conditional Parameters

Current status:

- Categorical parameters: not natively sampled by default `run_bo.py`.
- Conditional parameters: not natively modeled.

Recommended approach today:

- Start with a numeric subset (`float`/`int`) for first pilot.
- Add template extension logic for category encoding or conditional activation
  when required by your use case.

## Constraints and Invalid Regions

Native hard-constraint solving is not currently built into default templates.

Hard callout:

- No native hard-constraint solver in `v0.2.x`/`v0.3.0`; use bounds + penalty + failure policy.

Current integration pattern:

1. Keep bounds as first-line constraints.
2. Use scalar penalties for soft constraints and tradeoff pressure.
3. Detect invalid/non-evaluable combinations in evaluator/runtime.
4. Return a failure payload with clear status and policy-aligned objective
   representation.

This keeps behavior explicit and auditable for pilot workflows.
See `docs/how-it-works.md` for pathologies and deterministic-boundary guidance.

## Multi-Objective Handling

Current templates optimize one primary objective.

Details:

- Primary objective is configured in `objective_schema.json`.
- Best-so-far tracking uses only that primary objective.
- Additional metrics/objectives can still be stored externally for analysis.

If your problem is multi-objective, define and document scalarization before
running a pilot.

## Reproducibility Guidance

To keep optimization traces reproducible:

- Keep parameter names stable across runs.
- Keep bounds and parameter order stable within a campaign.
- Version control changes to parameter definitions before new runs.
- Avoid changing units mid-campaign; if needed, start a new campaign.

## Practical Pilot Pattern

For first implementation:

1. Choose 2-20 high-leverage numeric parameters.
2. Use clear, bounded ranges based on known safe operation.
3. Document invalid regions and failure handling in intake artifacts.
4. Expand only after one stable end-to-end cycle.

Related docs:

- `docs/integration-guide.md`
- `docs/operational-semantics.md`
- `intake.md`
