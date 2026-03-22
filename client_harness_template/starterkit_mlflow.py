from __future__ import annotations

from pathlib import Path
from typing import Any

from starterkit_tracking import JSONDict, load_tracking_snapshot


def _import_mlflow() -> Any:
    try:
        import mlflow  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "mlflow is not installed; install it in the client environment to use the starter adapter."
        ) from exc
    return mlflow


def _numeric_metrics(snapshot: JSONDict) -> dict[str, float]:
    metrics: dict[str, float] = {}
    counts = snapshot.get("counts")
    if isinstance(counts, dict):
        for key in ("observations", "pending", "failure_rate"):
            raw = counts.get(key)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                metrics[f"looptimum.{key}"] = float(raw)
    best = snapshot.get("best")
    if isinstance(best, dict):
        objective_value = best.get("objective_value")
        if isinstance(objective_value, (int, float)) and not isinstance(objective_value, bool):
            metrics["looptimum.best_objective"] = float(objective_value)
        scalarized_objective = best.get("scalarized_objective")
        if isinstance(scalarized_objective, (int, float)) and not isinstance(
            scalarized_objective, bool
        ):
            metrics["looptimum.best_scalarized_objective"] = float(scalarized_objective)
    return metrics


def build_mlflow_log_payload(
    project_root: str | Path,
    *,
    max_trials: int = 10,
    max_events: int = 20,
) -> JSONDict:
    snapshot = load_tracking_snapshot(project_root, max_trials=max_trials, max_events=max_events)
    objective_config = snapshot.get("objective_config")
    objective_names: list[str] = []
    scalarization_policy = None
    if isinstance(objective_config, dict):
        raw_names = objective_config.get("objective_names")
        if isinstance(raw_names, list):
            objective_names = [str(name) for name in raw_names]
        scalarization = objective_config.get("scalarization")
        if isinstance(scalarization, dict):
            raw_policy = scalarization.get("policy")
            if isinstance(raw_policy, str):
                scalarization_policy = raw_policy

    best = snapshot.get("best")
    tags: dict[str, str] = {
        "looptimum.project_root": str(snapshot["project_root"]),
        "looptimum.objective_names": ",".join(objective_names),
    }
    if scalarization_policy is not None:
        tags["looptimum.scalarization_policy"] = scalarization_policy
    if isinstance(best, dict):
        trial_id = best.get("trial_id")
        if isinstance(trial_id, int) and not isinstance(trial_id, bool):
            tags["looptimum.best_trial_id"] = str(trial_id)
        objective_name = best.get("objective_name")
        if isinstance(objective_name, str):
            tags["looptimum.best_objective_name"] = objective_name

    params: dict[str, str] = {
        "looptimum.next_trial_id": str(snapshot.get("next_trial_id")),
        "looptimum.top_trial_count": str(len(snapshot.get("top_trials", []))),
        "looptimum.recent_event_count": str(len(snapshot.get("recent_events", []))),
    }

    artifact_paths = [
        str(item["path"])
        for item in snapshot.get("artifacts", [])
        if isinstance(item, dict) and item.get("exists") is True
    ]

    return {
        "snapshot": snapshot,
        "metrics": _numeric_metrics(snapshot),
        "params": params,
        "tags": tags,
        "artifact_paths": artifact_paths,
    }


def log_to_mlflow(
    project_root: str | Path,
    *,
    experiment_name: str | None = None,
    run_name: str | None = None,
    tracking_uri: str | None = None,
    max_trials: int = 10,
    max_events: int = 20,
) -> JSONDict:
    mlflow = _import_mlflow()
    payload = build_mlflow_log_payload(project_root, max_trials=max_trials, max_events=max_events)

    if tracking_uri is not None:
        mlflow.set_tracking_uri(tracking_uri)
    if experiment_name is not None:
        mlflow.set_experiment(experiment_name)

    with mlflow.start_run(run_name=run_name) as run:
        metrics = payload["metrics"]
        if metrics:
            mlflow.log_metrics(metrics)
        params = payload["params"]
        if params:
            mlflow.log_params(params)
        tags = payload["tags"]
        if tags:
            mlflow.set_tags(tags)
        mlflow.log_dict(payload["snapshot"], "looptimum_snapshot.json")
        for artifact_path in payload["artifact_paths"]:
            mlflow.log_artifact(artifact_path, artifact_path="looptimum")
        run_id = getattr(getattr(run, "info", None), "run_id", None)

    return {
        "backend": "mlflow",
        "run_id": run_id,
        "artifact_count": len(payload["artifact_paths"]),
        "metric_count": len(payload["metrics"]),
    }
