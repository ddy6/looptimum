# Starter-Kit Integration Example Pack

Reference starter assets for the optional Workstream 9 integration surface.

This pack uses placeholder paths rooted at `/campaign` so the files stay
portable and do not embed any local machine paths.

Included:

- `starterkit_config.webhook.json`: example sidecar config for replaying
  `state/event_log.jsonl` into a webhook target
- `webhook_payload.json`: normalized lifecycle event payload produced by the
  starter event helpers
- `starterkit_suggestions.jsonl`: canonical worker-handoff suggestions with
  lease tokens
- `queue_worker_plan.json`: one selected queue-worker execution plan for
  `trial_id = 2`
- `airflow_dag.py`: rendered Airflow starter DAG for one controller plus two
  workers
- `slurm_worker_array.sh`: rendered Slurm array worker script for the same flow
- `mlflow_payload.json`: example payload shape logged by `starterkit_mlflow.py`
- `wandb_payload.json`: example payload shape logged by `starterkit_wandb.py`

Suggested usage pattern:

1. controller runs `suggest --count N --jsonl`
2. workers select one suggestion by index or `trial_id`
3. workers evaluate and ingest using the queue-worker wrapper
4. webhook sidecar tails `state/event_log.jsonl`
5. tracker sync runs post-ingest or post-report using canonical state files

These files are wiring references for the public starter-kit modules. They are
not benchmark evidence or production configuration defaults.
