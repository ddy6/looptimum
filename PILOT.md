# Pilot and Service Options

Looptimum can be used self-serve, but it can also support scoped pilot work
for teams running expensive black-box evaluations in local, on-prem, or
otherwise client-controlled environments.

Private contact for pilot fit and scope:
[contact@looptimum.com](mailto:contact@looptimum.com)

## Best Initial Fit

Looptimum is the strongest near-term fit when the pilot looks like:

- bounded numeric parameters
- one scalar objective
- expensive evaluations where each run matters
- a clear one-evaluation interface
- client-controlled, offline-friendly, or restricted execution

Current public baseline: `v0.3.2`

If your problem requires heavier categorical search, strong conditional
parameter logic, native multi-objective support, or a hosted control plane,
that may be a roadmap discussion rather than the best first pilot.

## Public Offers

### Fit Assessment

Review whether Looptimum is a practical fit for your optimization problem,
including parameter framing, objective design, runtime constraints, and pilot
readiness.

Typical scope:

- review the optimization problem and intended pilot outcome
- review the scalar objective or loss definition
- review candidate parameters, bounds, and known invalid regions
- review runtime, security, and operating constraints
- recommend whether to proceed now, reframe the pilot, or defer

This is the right starting point when the main question is not "can we run the
loop?" but "are we framing the right problem so the pilot does not waste runs?"

### Pilot Integration Sprint

Wire Looptimum into a real evaluation workflow, validate a one-trial preflight,
and prepare a bounded pilot with clear operational semantics.

Typical scope:

- freeze the initial objective, parameter set, and failure policy
- define or validate the one-evaluation interface
- wire the pilot path to the evaluator workflow
- run a one-trial preflight
- validate artifact flow and execution instructions for a bounded pilot

### Assisted Pilot / Readout

Run a bounded pilot with support on artifact review, result interpretation, and
recommended next steps.

Typical scope:

- support bounded pilot execution against the agreed framing
- review failures, retries, and audit artifacts
- summarize outcomes and status breakdown
- recommend whether to expand, refine, or stop

## Scoping Posture

Scope and delivery are tailored to the project.
Contact for scope rather than relying on rigid public pricing or fixed
delivery templates.

Looptimum is not positioned as a hosted SaaS platform.
The core value is a reliable, auditable outer loop that can run in the
client's environment.

## Start Here

If you are evaluating fit for a pilot:

1. Read this page.
2. Send a short note to [contact@looptimum.com](mailto:contact@looptimum.com)
   or fill out [`intake.md`](./intake.md).
3. Review [`docs/pilot-checklist.md`](./docs/pilot-checklist.md) for pilot
   execution expectations.
4. Review [`docs/integration-guide.md`](./docs/integration-guide.md) if you
   already have a likely evaluator path.

Security or data-handling questions can be reviewed against
[`docs/security-data-handling.md`](./docs/security-data-handling.md).
