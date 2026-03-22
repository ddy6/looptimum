from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from starterkit_tracking import JSONDict, load_tracking_snapshot


def _import_wandb() -> Any:
    try:
        import wandb  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "wandb is not installed; install it in the client environment to use the starter adapter."
        ) from exc
    return wandb


def _history_metrics(snapshot: JSONDict) -> dict[str, float]:
    history: dict[str, float] = {}
    counts = snapshot.get("counts")
    if isinstance(counts, dict):
        for key in ("observations", "pending", "failure_rate"):
            raw = counts.get(key)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                history[f"looptimum/{key}"] = float(raw)
    best = snapshot.get("best")
    if isinstance(best, dict):
        objective_value = best.get("objective_value")
        if isinstance(objective_value, (int, float)) and not isinstance(objective_value, bool):
            history["looptimum/best_objective"] = float(objective_value)
    return history


def build_wandb_log_payload(
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

    summary: dict[str, Any] = {
        "looptimum/project_root": snapshot["project_root"],
        "looptimum/top_trial_count": len(snapshot.get("top_trials", [])),
        "looptimum/recent_event_count": len(snapshot.get("recent_events", [])),
    }
    best = snapshot.get("best")
    if isinstance(best, dict):
        summary["looptimum/best"] = best

    config: dict[str, Any] = {
        "project_root": snapshot["project_root"],
        "objective_names": objective_names,
    }
    if scalarization_policy is not None:
        config["scalarization_policy"] = scalarization_policy

    artifact_paths = [
        str(item["path"])
        for item in snapshot.get("artifacts", [])
        if isinstance(item, dict) and item.get("exists") is True
    ]

    return {
        "snapshot": snapshot,
        "summary": summary,
        "config": config,
        "history": _history_metrics(snapshot),
        "artifact_paths": artifact_paths,
    }


def log_to_wandb(
    project_root: str | Path,
    *,
    project: str,
    entity: str | None = None,
    run_name: str | None = None,
    job_type: str = "looptimum",
    mode: str | None = None,
    max_trials: int = 10,
    max_events: int = 20,
) -> JSONDict:
    wandb = _import_wandb()
    payload = build_wandb_log_payload(project_root, max_trials=max_trials, max_events=max_events)

    run = wandb.init(
        project=project,
        entity=entity,
        name=run_name,
        job_type=job_type,
        mode=mode,
    )
    run.config.update(payload["config"])
    run.summary.update(payload["summary"])
    if payload["history"]:
        run.log(payload["history"])

    artifact = wandb.Artifact(name="looptimum-state", type="looptimum-state")
    with tempfile.TemporaryDirectory(prefix="looptimum_wandb_snapshot_") as tmp_dir:
        snapshot_path = Path(tmp_dir) / "looptimum_snapshot.json"
        snapshot_path.write_text(json.dumps(payload["snapshot"], indent=2) + "\n", encoding="utf-8")
        artifact.add_file(str(snapshot_path), name="looptimum_snapshot.json")
        for artifact_path in payload["artifact_paths"]:
            artifact.add_file(artifact_path, name=Path(artifact_path).name)
        run.log_artifact(artifact)
    run.finish()

    run_id = getattr(run, "id", None)
    return {
        "backend": "wandb",
        "run_id": run_id,
        "artifact_count": len(payload["artifact_paths"]) + 1,
        "history_metric_count": len(payload["history"]),
    }
