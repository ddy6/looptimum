# CLI Transcript (Text-Only Demo)

This transcript shows a minimal `suggest -> evaluate -> ingest -> status` flow
using the tiny quadratic objective. It is text-only by design (no media asset).

## Setup Narration

- A clean temporary copy of `templates/` is created under
  `/tmp/looptimum_phase6_transcript`.
- State files are removed so the run starts from an empty state.
- The objective used is
  `examples/toy_objectives/03_tiny_quadratic_loop/objective.py`.

## Commands and Outputs

### 1. Suggest

```bash
python3 /tmp/looptimum_phase6_transcript/templates/bo_client_demo/run_bo.py suggest \
  --project-root /tmp/looptimum_phase6_transcript/templates/bo_client_demo \
  --json-only > /tmp/looptimum_phase6_transcript/suggestion_1.json
cat /tmp/looptimum_phase6_transcript/suggestion_1.json
```

Output:

```json
{
  "trial_id": 1,
  "params": {
    "x1": 0.18126486333322134,
    "x2": 0.6614305484952444
  },
  "suggested_at": 1772639853.5820448
}
```

Narration: `suggest` emits the immutable `trial_id` + `params` contract.

### 2. Evaluate (client harness adapter)

```bash
python3 client_harness_template/run_one_eval.py \
  /tmp/looptimum_phase6_transcript/suggestion_1.json \
  /tmp/looptimum_phase6_transcript/result_1.json \
  --objective-module examples/toy_objectives/03_tiny_quadratic_loop/objective.py \
  --objective-name loss \
  --print-result
```

Output:

```json
{
  "trial_id": 1,
  "params": {
    "x1": 0.18126486333322134,
    "x2": 0.6614305484952444
  },
  "objectives": {
    "loss": 0.035246812703647754
  },
  "status": "ok"
}
```

Narration: evaluator output is converted to an ingest-ready payload.

### 3. Ingest

```bash
python3 /tmp/looptimum_phase6_transcript/templates/bo_client_demo/run_bo.py ingest \
  --project-root /tmp/looptimum_phase6_transcript/templates/bo_client_demo \
  --results-file /tmp/looptimum_phase6_transcript/result_1.json
```

Output:

```text
Ingested trial_id=1. Observations=1
```

Narration: pending trial is resolved and stored as an observation.

### 4. Status

```bash
python3 /tmp/looptimum_phase6_transcript/templates/bo_client_demo/run_bo.py status \
  --project-root /tmp/looptimum_phase6_transcript/templates/bo_client_demo
```

Output:

```json
{
  "observations": 1,
  "pending": 0,
  "next_trial_id": 2,
  "best": {
    "trial_id": 1,
    "objective_name": "loss",
    "objective_value": 0.035246812703647754,
    "updated_at": 1772639861.774495
  },
  "stale_pending": 0,
  "observations_by_status": {
    "ok": 1,
    "failed": 0,
    "killed": 0,
    "timeout": 0
  },
  "max_pending_age_seconds": 86400.0,
  "paths": {
    "state_file": "state/bo_state.json",
    "observations_csv": "state/observations.csv",
    "acquisition_log_file": "state/acquisition_log.jsonl",
    "event_log_file": "state/event_log.jsonl",
    "trials_dir": "state/trials",
    "lock_file": "state/.looptimum.lock"
  }
}
```

Narration: status confirms one successful observation and zero pending trials.
