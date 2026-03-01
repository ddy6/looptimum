# Client Intake (Optimization Integration + Pilot Setup)

Use this intake to define the optimization problem and the minimum integration details needed to run a Looptimum pilot.

Fill in what you know. Unknown items can be marked `TBD`.

## 1. Project Summary

- Company / team:
- Primary contact:
- Technical contact (if different):
- Use case category (simulation / calibration / tuning / process / scheduling / pricing / marketing / other):
- Short problem statement (2-5 sentences):
- Success criteria for pilot:

## 2. Objective Definition (What We Are Optimizing)

- Primary objective name (example: `loss`, `yield`, `profit`, `runtime`, `conversion_rate`):
- Objective direction: `minimize` or `maximize`
- Plain-language definition of objective:
- Exact scalar formula (if available):
- Units (if any):
- Is the objective always defined for every run? `yes / no`
- If no, what failure/invalid outputs occur?

## 3. Parameters (Decision Variables)

For each parameter, provide name, type, and valid range/values.

Current public template support:

- native types in default templates: `float`, `int`
- `categorical` may still be specified in intake for planning, but requires template extension before execution

### Parameter Table (copy/add rows)

| name | type (`float`/`int`/`categorical`) | bounds or choices | default/current value | notes |
|---|---|---|---|---|
|  |  |  |  |  |

### Parameter Rules / Couplings

- Are any parameters conditionally active?
- Are there combinations that are invalid / infeasible?
- Are there hidden constraints not obvious from bounds?
- Any preferred operating region(s) to explore first?

## 4. Constraints and Invalid Regions

List hard and soft constraints that matter during optimization.

- Hard constraints (must not violate):
- Soft constraints (violations allowed but undesirable):
- Invalid regions / known crash regions:
- Runtime limits per evaluation (hard timeout):
- Resource limits (CPU/GPU/RAM/disk):
- Safety / compliance constraints:
- How should invalid/failed runs be scored (if known)?

## 5. Evaluation Budget and Runtime Expectations

- Target total evaluation budget (number of runs):
- Minimum useful pilot budget:
- Maximum feasible budget:
- Estimated runtime per evaluation (typical):
- Runtime variability (best/worst case):
- Can evaluations run in parallel? `yes / no / limited`
- If parallel, max concurrent evaluations:
- Cost per evaluation (if relevant):
- Scheduling constraints (business hours, queue windows, etc.):

## 6. Noise / Stochasticity / Repeatability

- Is the evaluation deterministic for fixed parameters? `yes / no / mostly`
- If stochastic, main noise sources:
- Expected noise magnitude (roughly):
- Does the system use random seeds internally? `yes / no`
- Can we control/fix those seeds? `yes / no / partial`
- Should repeated evaluations at the same params be allowed? `yes / no / maybe`

## 7. Environment and Execution Constraints

- Where will evaluations run? (local workstation / on-prem server / cluster / cloud / SaaS API):
- OS / platform:
- Required software / runtime dependencies:
- Python version (if applicable):
- Container requirement (Docker/Singularity/etc.)?:
- Network access restrictions (offline / limited / internet-allowed):
- File system restrictions / mount points:
- Credentials/secrets required at runtime? (describe handling approach, not the secret values):
- Logging / audit requirements:

## 8. Programmatic One-Evaluation Interface (Required)

Describe how to run one evaluation from code or CLI.

### Option A: Python function (preferred when available)

- Module/function name:
- Function signature (example: `evaluate(params: dict) -> float`):
- Minimal example call:
- Returned outputs (what metrics are available before scalarization?):

### Option B: CLI command / script

- Command template (show placeholders):
- Input format (flags / config file / JSON / env vars):
- Output location / format:
- Exit codes / failure semantics:
- Minimal example command:

### Option C: API / service call

- Endpoint / method:
- Request schema:
- Response schema:
- Auth method:
- Timeout / retry behavior:

## 9. Parameter -> Run -> Scalar Objective Mapping (Required)

Describe the exact mapping path:

1. How Looptimum parameters are injected into the system
2. What process/job/script is executed
3. What raw outputs/metrics are produced
4. How the scalar objective is computed
5. How failures/invalid runs are represented

## 10. Existing Baseline / Prior Knowledge (Optional but Helpful)

- Current best known parameter set:
- Current baseline objective value:
- Known good regions:
- Known bad regions:
- Prior experiments / historical data available? `yes / no`
- If yes, format and size:

## 11. Pilot Scope and Deliverables Alignment

- Desired engagement tier (if known): `Tier 1 / Tier 2 / Tier 3 / TBD`
- Timeline target:
- Stakeholders for readout/report:
- Preferred deliverables format (PR, docs, notebook, report, slides):

## 12. Data Handling / Security Preferences

- NDA required before technical discussion? `yes / no / maybe`
- Can work be performed fully on client-managed infrastructure? `yes / no`
- Data egress restrictions:
- What data may be shared externally (if any)?
- Any prohibited data types (PII/PHI/etc.)?

## Submission Notes

- You can redact proprietary names and still provide technical structure.
- For a fast start, the most critical items are:
  - objective + direction
  - parameter list with types/bounds
  - evaluation budget/runtime
  - failure modes/constraints
  - one-evaluation programmatic interface
