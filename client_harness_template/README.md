# Client Harness Template

Use [the integration guide](../docs/integration-guide.md) to define your evaluator
boundary, then follow [adapter setup](./README_INTEGRATION.md) to implement it.
The default `objective.py` is a stub; it does not run a successful evaluation
until you supply an implementation.

## Files by task

| Task | Files |
| --- | --- |
| Run one local evaluation and write an ingest payload | `objective.py`, `run_one_eval.py` |
| Use AWS Batch | `objective_aws_batch_example.py`, `aws_config.py`, `aws_executor.py`, `aws_models.py`, `aws_batch_config.example.json` |
| Dispatch queue, Airflow or Slurm work | `starterkit_scheduler.py`, `starterkit_queue_worker.py`, `starterkit_airflow.py`, `starterkit_slurm.py` |
| Deliver event webhooks | `starterkit_config.py`, `starterkit_events.py` |
| Export observations to optional trackers | `starterkit_tracking.py`, `starterkit_mlflow.py`, `starterkit_wandb.py` |

The local adapter is a single-objective starter. Optional executors and sidecars
have their own dependencies and operating requirements; see
[AWS Batch](../docs/aws-batch-integration.md) and the
[integration starter kit](../docs/integration-starter-kit.md).
