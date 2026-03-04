# Examples

Public examples directory for integration-pattern references and later case studies.

Purpose:

- show how to connect external evaluators to the optimization templates
- demonstrate common integration patterns (Python function, CLI/subprocess, etc.)
- provide small runnable references before moving to domain-specific examples

Included:

- `toy-objectives/`: two toy examples covering different integration patterns
- `toy_objectives/03_tiny_quadratic_loop/`: dedicated tiny end-to-end loop
  example (`suggest -> evaluate -> ingest -> status` in under one minute)

Planned later:

- sample result payloads and run artifacts
- advanced domain-specific case studies (for example, meshing/OpenFOAM)

Positioning note:

- The toy examples are not benchmark tasks and are not intended to demonstrate optimization performance claims.
- They are reference implementations for wiring `suggest -> evaluate -> ingest` end to end.
