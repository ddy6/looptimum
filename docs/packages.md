# Working with Looptimum

Looptimum was built to solve a concrete problem that emerged in CFD work:
expensive simulation loops, fragile iteration,
and too much manual overhead around restarting, tracking, and steering optimization.
That same structure turned out to transfer well into adjacent layers of computational research where evaluations are costly, parameter spaces are awkward, and a resumable optimization loop is more useful than a heavier platform.
The repo shows the core of that system; in some settings it stands on its own, and in others it becomes the starting point for a more specific discussion about fit, constraints, and deployment context.

If you want to talk through fit or timing, reach out at
[contact@looptimum.com](mailto:contact@looptimum.com).

---

## Start with the repo

The repo remains the natural starting point because that is where the tool was first meant to live: close to the evaluation loop, file-backed, locally inspectable, and easy to adapt without giving up control of the environment. That path is still the right one for many groups, especially when the immediate goal is to test the optimizer inside an existing workflow and see how it behaves under actual research or engineering conditions.

- CLI runtime
- mixed-type and conditional parameters
- constraints
- batch suggestions and async worker flow
- archive / restore
- warm-start import / export
- health, metrics, and governance surfaces
- starter adapters and examples: webhooks, Airflow, Slurm, MLflow, W&B
- community-style support, best effort

---

## When a pilot needs a clearer operating surface

Some pilots benefit from a little more structure around the same core runtime. In those cases, the useful additions are usually modest: a local service API, a lightweight dashboard, coordination across more than one controller, and somewhat closer support during early setup and shakeout.

- service API preview
- dashboard preview
- multi-controller coordination preview
- more direct pilot support

These remain preview surfaces: functional, practical, and intentionally kept light.

---

## When security and process become the main constraint

In more mature environments, the central question is often less about whether the loop runs and more about whether it fits the surrounding system. That is where identity, access control, governance, retention, auditability, documentation, and integration scope begin to matter more than the optimizer itself.

- OIDC / SSO preview
- role-based access
- governance policy enforcement
- retention controls and audit trails
- dedicated support path
- security / compliance packaging
- custom scoping for harder integrations

Still self-run. Not a hosted SaaS handoff.

---

## Common ways support is usually scoped

**Fit check.** Review the problem definition, objective structure, parameterization, invalid regions, runtime limits, and whether a pilot is well-timed or premature.

**Pilot integration sprint.** Lock down the first loop, wire the evaluator path, run preflight checks, and make sure the artifacts and operating steps are usable in practice.

**Assisted pilot / readout.** Stay close to a bounded pilot, review failures and outputs, summarize findings, and decide whether to expand, refine, or stop.

---

## A practical rule of thumb

Start with the repo unless there is already a known need for preview surfaces, tighter support, or identity and governance work.

If the fit is still unclear, start with the pilot-fit docs:
[`PILOT.md`](../PILOT.md) and [`intake.md`](../intake.md).
