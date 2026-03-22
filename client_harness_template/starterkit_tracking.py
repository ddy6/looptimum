from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from starterkit_events import build_webhook_payload, consume_starter_events

JSONDict = dict[str, Any]


def _require_object(value: Any, *, field_name: str) -> JSONDict:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return dict(value)


def _load_json_object(path: Path, *, field_name: str) -> JSONDict:
    if not path.exists():
        raise ValueError(f"{field_name} not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} invalid JSON: {exc}") from exc
    return _require_object(payload, field_name=field_name)


def _load_optional_json_object(path: Path, *, field_name: str) -> JSONDict | None:
    if not path.exists():
        return None
    return _load_json_object(path, field_name=field_name)


def _runtime_paths(project_root: Path) -> dict[str, Path]:
    state_dir = project_root / "state"
    return {
        "bo_state": state_dir / "bo_state.json",
        "report_json": state_dir / "report.json",
        "report_md": state_dir / "report.md",
        "event_log": state_dir / "event_log.jsonl",
        "acquisition_log": state_dir / "acquisition_log.jsonl",
        "trials_dir": state_dir / "trials",
    }


def _trial_manifest_path(project_root: Path, trial_id: int) -> Path:
    return project_root / "state" / "trials" / f"trial_{int(trial_id)}" / "manifest.json"


def _relative_or_absolute_path(project_root: Path, raw: Any) -> Path | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw)
    if path.is_absolute():
        return path
    return (project_root / path).resolve()


def _fallback_trial_summaries(bo_state: JSONDict, *, max_trials: int) -> list[JSONDict]:
    observations = bo_state.get("observations")
    if not isinstance(observations, list):
        return []

    summaries: list[JSONDict] = []
    for raw in observations:
        observation = _require_object(raw, field_name="bo_state observation")
        trial_id = observation.get("trial_id")
        if not isinstance(trial_id, int) or isinstance(trial_id, bool):
            raise ValueError("bo_state observation.trial_id must be an integer")
        objective_name = None
        objectives = observation.get("objectives")
        objective_vector = objectives if isinstance(objectives, dict) else {}
        if objective_vector:
            objective_name = next(iter(objective_vector))
        summaries.append(
            {
                "trial_id": trial_id,
                "status": observation.get("status"),
                "objective_name": objective_name,
                "objective_value": observation.get("objective_value"),
                "objective_vector": dict(objective_vector),
                "scalarized_objective": observation.get("scalarized_objective"),
                "penalty_objective": observation.get("penalty_objective"),
                "suggested_at": observation.get("suggested_at"),
                "completed_at": observation.get("completed_at"),
                "artifact_path": observation.get("artifact_path"),
                "terminal_reason": observation.get("terminal_reason"),
                "params": dict(observation.get("params", {}))
                if isinstance(observation.get("params"), dict)
                else {},
            }
        )
    summaries.sort(key=lambda row: int(row["trial_id"]), reverse=True)
    return summaries[:max_trials]


def _load_manifest_summaries(project_root: Path, trial_ids: list[int]) -> dict[int, JSONDict]:
    manifests: dict[int, JSONDict] = {}
    for trial_id in trial_ids:
        path = _trial_manifest_path(project_root, trial_id)
        payload = _load_optional_json_object(path, field_name=f"manifest for trial_id {trial_id}")
        if payload is not None:
            manifests[trial_id] = payload
    return manifests


def _artifact_inventory(
    project_root: Path,
    *,
    paths: dict[str, Path],
    best_trial_id: int | None,
    top_trials: list[JSONDict],
) -> list[JSONDict]:
    candidates: list[tuple[str, Path]] = [
        ("bo_state_json", paths["bo_state"]),
        ("report_json", paths["report_json"]),
        ("report_md", paths["report_md"]),
        ("event_log_jsonl", paths["event_log"]),
        ("acquisition_log_jsonl", paths["acquisition_log"]),
    ]
    if best_trial_id is not None:
        candidates.append(
            (f"trial_{best_trial_id}_manifest", _trial_manifest_path(project_root, best_trial_id))
        )
    for trial in top_trials:
        trial_id = trial.get("trial_id")
        if isinstance(trial_id, int) and not isinstance(trial_id, bool):
            candidates.append(
                (f"trial_{trial_id}_manifest", _trial_manifest_path(project_root, trial_id))
            )
        artifact_path = _relative_or_absolute_path(project_root, trial.get("artifact_path"))
        if artifact_path is not None:
            label = f"trial_{trial_id}_artifact" if trial_id is not None else "trial_artifact"
            candidates.append((label, artifact_path))

    inventory: list[JSONDict] = []
    seen: set[str] = set()
    for label, path in candidates:
        resolved = path.resolve()
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        inventory.append(
            {
                "label": label,
                "path": str(resolved),
                "exists": resolved.exists(),
            }
        )
    return inventory


def load_tracking_snapshot(
    project_root: str | Path,
    *,
    max_trials: int = 10,
    max_events: int = 20,
) -> JSONDict:
    if max_trials < 1:
        raise ValueError("max_trials must be >= 1")
    if max_events < 0:
        raise ValueError("max_events must be >= 0")

    root = Path(project_root).resolve()
    paths = _runtime_paths(root)
    bo_state = _load_json_object(paths["bo_state"], field_name="bo_state")
    report = _load_optional_json_object(paths["report_json"], field_name="report_json")

    best = report.get("best") if report is not None else bo_state.get("best")
    best_record = _require_object(best, field_name="best") if isinstance(best, dict) else None

    if report is not None:
        raw_top_trials = report.get("top_trials")
        if not isinstance(raw_top_trials, list):
            raise ValueError("report_json.top_trials must be a list when report_json is present")
        top_trials = [
            _require_object(item, field_name=f"report_json.top_trials[{index}]")
            for index, item in enumerate(raw_top_trials[:max_trials])
        ]
    else:
        top_trials = _fallback_trial_summaries(bo_state, max_trials=max_trials)

    counts = report.get("counts") if report is not None else None
    if counts is None:
        observations = bo_state.get("observations")
        pending = bo_state.get("pending")
        counts_payload: JSONDict = {
            "observations": len(observations) if isinstance(observations, list) else 0,
            "pending": len(pending) if isinstance(pending, list) else 0,
        }
    else:
        counts_payload = _require_object(counts, field_name="counts")

    trial_ids: list[int] = []
    if best_record is not None:
        best_trial_id = best_record.get("trial_id")
        if isinstance(best_trial_id, int) and not isinstance(best_trial_id, bool):
            trial_ids.append(best_trial_id)
    for row in top_trials:
        trial_id = row.get("trial_id")
        if isinstance(trial_id, int) and not isinstance(trial_id, bool):
            trial_ids.append(trial_id)

    manifests = _load_manifest_summaries(root, sorted(set(trial_ids)))
    recent_events, _ = consume_starter_events(paths["event_log"])
    event_payloads = [build_webhook_payload(event) for event in recent_events[-max_events:]]

    best_trial_id = None
    if best_record is not None:
        raw_trial_id = best_record.get("trial_id")
        if isinstance(raw_trial_id, int) and not isinstance(raw_trial_id, bool):
            best_trial_id = raw_trial_id

    snapshot: JSONDict = {
        "snapshot_version": 1,
        "project_root": str(root),
        "paths": {
            label: str(path.resolve()) for label, path in paths.items() if label != "trials_dir"
        },
        "counts": counts_payload,
        "next_trial_id": bo_state.get("next_trial_id"),
        "objective": report.get("objective") if report is not None else None,
        "objective_config": report.get("objective_config") if report is not None else None,
        "best": best_record,
        "best_params": report.get("best_params") if report is not None else None,
        "top_trials": top_trials,
        "recent_events": event_payloads,
        "manifests": {str(trial_id): payload for trial_id, payload in manifests.items()},
        "artifacts": _artifact_inventory(
            root,
            paths=paths,
            best_trial_id=best_trial_id,
            top_trials=top_trials,
        ),
    }
    return snapshot
