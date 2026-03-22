# Client Harness Template

Lean starter harness for client-side integration.

Use this as the default adapter for wiring external evaluators into Looptimum.

Contents:

- `objective.py`: client-fill stub (`evaluate(params)`)
- `objective_aws_batch_example.py`: optional AWS Batch-backed example objective
- `run_one_eval.py`: suggestion JSON -> ingest payload JSON adapter
- `aws_config.py`: optional AWS Batch config loader
- `aws_executor.py`: optional AWS Batch submit/poll/download helper
- `aws_models.py`: typed request/config/recovery models for the AWS path
- `starterkit_scheduler.py`: shared suggestion parsing and command-render helpers
- `starterkit_queue_worker.py`: generic queue-worker starter for batch handoff
- `starterkit_airflow.py`: Airflow DAG render helper for the canonical loop
- `starterkit_slurm.py`: Slurm array-script render helper for the canonical loop
- `aws_batch_config.example.json`: committed example AWS config
- `README_INTEGRATION.md`: implementation instructions and failure-mode guidance

Start with `README_INTEGRATION.md` first.
