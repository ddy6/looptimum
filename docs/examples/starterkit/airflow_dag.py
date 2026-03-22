from __future__ import annotations

from datetime import datetime

from airflow import DAG
from airflow.operators.bash import BashOperator

# Single-controller pattern: only controller_suggest creates the batch.
with DAG(
    dag_id="looptimum_batch",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
    max_active_runs=1,
) as dag:
    controller_suggest = BashOperator(
        task_id="controller_suggest",
        bash_command="python3 /campaign/run_bo.py suggest --project-root /campaign --count 2 --jsonl --fail-fast > /campaign/state/starterkit_suggestions.jsonl",
        retries=0,
    )

    worker_0 = BashOperator(
        task_id="worker_0",
        bash_command="python3 /campaign/client_harness_template/starterkit_queue_worker.py /campaign/state/starterkit_suggestions.jsonl --project-root /campaign --worker-index 0 --work-dir /campaign/state/starterkit_worker_runs --run-bo-script /campaign/run_bo.py --run-one-eval-script /campaign/client_harness_template/run_one_eval.py --objective-schema /campaign/objective_schema.json",
        retries=1,
    )
    controller_suggest >> worker_0

    worker_1 = BashOperator(
        task_id="worker_1",
        bash_command="python3 /campaign/client_harness_template/starterkit_queue_worker.py /campaign/state/starterkit_suggestions.jsonl --project-root /campaign --worker-index 1 --work-dir /campaign/state/starterkit_worker_runs --run-bo-script /campaign/run_bo.py --run-one-eval-script /campaign/client_harness_template/run_one_eval.py --objective-schema /campaign/objective_schema.json",
        retries=1,
    )
    controller_suggest >> worker_1
