#!/usr/bin/env python3
"""Client-facing single-stage optimization harness with resumable state."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import random
import sys
import time
from io import StringIO
from pathlib import Path
from typing import Any

from surrogate_gp import propose_with_gp
from surrogate_proxy import propose_with_proxy

_TEMPLATE_DIR = Path(__file__).resolve().parent


def _load_shared_module(module_name: str, filename: str):
    module_path = _TEMPLATE_DIR.parent / "_shared" / filename
    if not module_path.exists():
        raise ModuleNotFoundError(
            f"Missing shared module at {module_path}. Ensure templates/_shared is present."
        )
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load shared module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CONTRACT = _load_shared_module("looptimum_shared_contract", "contract.py")
_RUNTIME = _load_shared_module("looptimum_shared_runtime", "runtime.py")

build_observation_contract = _CONTRACT.build_observation_contract
diff_contract_records = _CONTRACT.diff_contract_records
format_contract_diff_error = _CONTRACT.format_contract_diff_error
load_contract_document = _CONTRACT.load_contract_document
load_data_file = _CONTRACT.load_data_file
load_schema_from_paths = _CONTRACT.load_schema_from_paths
normalize_ingest_payload = _CONTRACT.normalize_ingest_payload
validate_against_schema = _CONTRACT.validate_against_schema

append_jsonl = _RUNTIME.append_jsonl
atomic_write_json = _RUNTIME.atomic_write_json
atomic_write_text = _RUNTIME.atomic_write_text
hold_exclusive_lock = _RUNTIME.hold_exclusive_lock
load_trial_manifest = _RUNTIME.load_trial_manifest
pending_age_seconds = _RUNTIME.pending_age_seconds
resolve_lock_timeout_seconds = _RUNTIME.resolve_lock_timeout_seconds
resolve_max_pending_age_seconds = _RUNTIME.resolve_max_pending_age_seconds
resolve_runtime_paths = _RUNTIME.resolve_runtime_paths
save_trial_manifest = _RUNTIME.save_trial_manifest
trial_dir = _RUNTIME.trial_dir


def load_cfg(path: Path) -> dict:
    data = load_data_file(path)
    if not isinstance(data, dict):
        raise ValueError(f"Config/state file must contain an object: {path}")
    return data


def load_state(path: Path) -> dict:
    if path.exists():
        return load_cfg(path)
    return {
        "meta": {"created_at": time.time(), "seed": None},
        "observations": [],
        "pending": [],
        "next_trial_id": 1,
        "best": None,
    }


def save_state(path: Path, state: dict) -> None:
    atomic_write_json(path, state, indent=2)


def write_obs_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        atomic_write_text(path, "")
        return
    keys = sorted({k for r in rows for k in r.keys()})
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=keys)
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_text(path, buffer.getvalue())


def norm_space(space_cfg: dict) -> list[dict]:
    params = space_cfg.get("parameters", [])
    if not params:
        raise ValueError("parameter_space.json must define 'parameters'")
    return params


def random_point(rng: random.Random, params: list[dict]) -> dict:
    out: dict = {}
    for p in params:
        lo, hi = p["bounds"]
        if p["type"] == "float":
            out[p["name"]] = rng.uniform(float(lo), float(hi))
        elif p["type"] == "int":
            out[p["name"]] = rng.randint(int(lo), int(hi))
        else:
            raise ValueError(f"Unsupported parameter type: {p['type']}")
    return out


def propose(
    rng: random.Random, state: dict, cfg: dict, params: list[dict], obj_cfg: dict, seed: int
) -> tuple[dict, dict]:
    obs = state["observations"]
    objective = obj_cfg["primary_objective"]
    if len(obs) < int(cfg["initial_random_trials"]):
        return random_point(rng, params), {"strategy": "initial_random", "surrogate_backend": None}

    surrogate_cfg = cfg["surrogate"]
    acq_cfg = cfg["acquisition"]
    backend = str(surrogate_cfg.get("type", "rbf_proxy")).lower()
    best = state["best"]["objective_value"] if state["best"] else None
    candidates = [random_point(rng, params) for _ in range(int(cfg["candidate_pool_size"]))]

    if backend == "rbf_proxy":
        return propose_with_proxy(candidates, obs, params, objective, surrogate_cfg, acq_cfg, best)
    if backend == "gp":
        return propose_with_gp(candidates, obs, params, objective, acq_cfg, best, seed)
    raise ValueError(f"Unsupported surrogate.type '{backend}'. Supported values: rbf_proxy | gp")


def update_best(state: dict, objective: dict) -> None:
    ok = [r for r in state["observations"] if str(r.get("status", "ok")) == "ok"]
    if not ok:
        state["best"] = None
        return
    name, direction = objective["name"], objective["direction"]
    picker = min if direction == "minimize" else max
    row = picker(ok, key=lambda r: float(r["objectives"][name]))
    state["best"] = {
        "trial_id": int(row["trial_id"]),
        "objective_name": name,
        "objective_value": float(row["objectives"][name]),
        "updated_at": time.time(),
    }


def _runtime_paths(root: Path, cfg: dict) -> dict[str, Path]:
    raw = cfg.get("paths", {})
    if not isinstance(raw, dict):
        raise ValueError("bo_config.paths must be an object")
    return resolve_runtime_paths(root, raw)


def _relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _append_event(paths: dict[str, Path], event: str, **fields: Any) -> None:
    payload = {"event": event, "timestamp": time.time()}
    payload.update(fields)
    append_jsonl(paths["event_log_file"], payload)


def _require_finite_number(value: Any, *, field_name: str, trial_id: int) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"trial_id {trial_id}: {field_name} must be a finite number")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"trial_id {trial_id}: {field_name} must be a finite number")
    return out


def _load_heartbeat_fields(payload: dict, trial_id: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "heartbeat_at" in payload:
        out["last_heartbeat_at"] = _require_finite_number(
            payload["heartbeat_at"], field_name="heartbeat_at", trial_id=trial_id
        )
    if "heartbeat_note" in payload:
        note = payload["heartbeat_note"]
        if not isinstance(note, str):
            raise ValueError(f"trial_id {trial_id}: heartbeat_note must be a string")
        out["heartbeat_note"] = note
    if "heartbeat_meta" in payload:
        meta = payload["heartbeat_meta"]
        if not isinstance(meta, dict):
            raise ValueError(f"trial_id {trial_id}: heartbeat_meta must be an object")
        out["heartbeat_meta"] = meta
    return out


def _pending_index(state: dict, trial_id: int) -> int | None:
    for idx, pending in enumerate(state["pending"]):
        if int(pending["trial_id"]) == trial_id:
            return idx
    return None


def _pop_pending(state: dict, trial_id: int) -> dict | None:
    idx = _pending_index(state, trial_id)
    if idx is None:
        return None
    return state["pending"].pop(idx)


def _ensure_pending_manifest(
    paths: dict[str, Path], pending_entry: dict, *, objective_name: str, now: float
) -> None:
    trial_id = int(pending_entry["trial_id"])
    manifest = load_trial_manifest(paths["trials_dir"], trial_id)
    manifest.setdefault("created_at", now)
    manifest["trial_id"] = trial_id
    manifest["status"] = "pending"
    manifest["terminal_reason"] = None
    manifest["params"] = pending_entry["params"]
    manifest["objective_name"] = objective_name
    manifest["objective_value"] = None
    manifest["penalty_objective"] = None
    manifest["suggested_at"] = float(pending_entry.get("suggested_at", now))
    manifest["completed_at"] = None
    manifest["last_heartbeat_at"] = pending_entry.get("last_heartbeat_at")
    manifest["heartbeat_count"] = int(pending_entry.get("heartbeat_count", 0) or 0)
    if "heartbeat_note" in pending_entry:
        manifest["heartbeat_note"] = pending_entry["heartbeat_note"]
    if "heartbeat_meta" in pending_entry:
        manifest["heartbeat_meta"] = pending_entry["heartbeat_meta"]
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
    manifest["artifacts"] = artifacts
    manifest["updated_at"] = now
    save_trial_manifest(paths["trials_dir"], trial_id, manifest)


def _ensure_terminal_manifest(
    root: Path,
    paths: dict[str, Path],
    observation: dict,
    *,
    objective_name: str,
    payload_copy_path: Path | None,
    now: float,
) -> None:
    trial_id = int(observation["trial_id"])
    manifest = load_trial_manifest(paths["trials_dir"], trial_id)
    manifest.setdefault("created_at", now)
    manifest["trial_id"] = trial_id
    manifest["status"] = observation["status"]
    manifest["terminal_reason"] = observation.get("terminal_reason")
    manifest["params"] = observation["params"]
    manifest["objective_name"] = objective_name
    manifest["objective_value"] = observation["objectives"].get(objective_name)
    manifest["penalty_objective"] = observation.get("penalty_objective")
    manifest["suggested_at"] = observation.get("suggested_at", manifest.get("suggested_at"))
    manifest["completed_at"] = observation.get("completed_at")
    manifest["last_heartbeat_at"] = observation.get("last_heartbeat_at")
    manifest["heartbeat_count"] = int(observation.get("heartbeat_count", 0) or 0)
    if "heartbeat_note" in observation:
        manifest["heartbeat_note"] = observation["heartbeat_note"]
    if "heartbeat_meta" in observation:
        manifest["heartbeat_meta"] = observation["heartbeat_meta"]
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
    if payload_copy_path is not None:
        artifacts["ingest_payload"] = _relative_path(root, payload_copy_path)
    manifest["artifacts"] = artifacts
    manifest["updated_at"] = now
    save_trial_manifest(paths["trials_dir"], trial_id, manifest)


def _observation_rows(state: dict) -> list[dict]:
    rows = []
    for obs in state["observations"]:
        row = {
            "trial_id": obs["trial_id"],
            "status": obs["status"],
            "completed_at": obs["completed_at"],
        }
        row.update({f"param_{k}": v for k, v in obs["params"].items()})
        row.update({f"objective_{k}": v for k, v in obs["objectives"].items()})
        if "penalty_objective" in obs:
            row["penalty_objective"] = obs["penalty_objective"]
        if "terminal_reason" in obs:
            row["terminal_reason"] = obs["terminal_reason"]
        if "last_heartbeat_at" in obs:
            row["last_heartbeat_at"] = obs["last_heartbeat_at"]
        rows.append(row)
    return rows


def _save_state_and_rows(paths: dict[str, Path], state: dict) -> None:
    save_state(paths["state_file"], state)
    write_obs_csv(paths["observations_csv"], _observation_rows(state))


def _new_terminal_observation(
    pending: dict,
    *,
    objective_name: str,
    terminal_reason: str,
    now: float,
) -> dict:
    observation = {
        "trial_id": int(pending["trial_id"]),
        "params": pending["params"],
        "objectives": {str(objective_name): None},
        "status": "killed",
        "terminal_reason": terminal_reason,
        "suggested_at": pending.get("suggested_at"),
        "completed_at": now,
    }
    if "last_heartbeat_at" in pending:
        observation["last_heartbeat_at"] = pending["last_heartbeat_at"]
    if "heartbeat_count" in pending:
        observation["heartbeat_count"] = pending["heartbeat_count"]
    if "heartbeat_note" in pending:
        observation["heartbeat_note"] = pending["heartbeat_note"]
    if "heartbeat_meta" in pending:
        observation["heartbeat_meta"] = pending["heartbeat_meta"]
    return observation


def _retire_stale_pending(
    state: dict,
    *,
    objective_name: str,
    max_pending_age_seconds: float,
    now: float,
    reason: str,
) -> list[dict]:
    stale_ids = [
        int(pending["trial_id"])
        for pending in state["pending"]
        if pending_age_seconds(pending, now=now) > max_pending_age_seconds
    ]
    observations: list[dict] = []
    for trial_id in stale_ids:
        pending = _pop_pending(state, trial_id)
        if pending is None:
            continue
        obs = _new_terminal_observation(
            pending,
            objective_name=objective_name,
            terminal_reason=reason,
            now=now,
        )
        state["observations"].append(obs)
        observations.append(obs)
    return observations


def _status_counts(observations: list[dict]) -> dict[str, int]:
    counts = {"ok": 0, "failed": 0, "killed": 0, "timeout": 0}
    for obs in observations:
        status = str(obs.get("status", "")).lower()
        counts[status] = counts.get(status, 0) + 1
    return counts


def _status_payload(
    root: Path, state: dict, paths: dict[str, Path], max_pending_age: float | None
) -> dict:
    now = time.time()
    stale_pending = 0
    if max_pending_age is not None:
        stale_pending = sum(
            1
            for pending in state["pending"]
            if pending_age_seconds(pending, now=now) > max_pending_age
        )

    return {
        "observations": len(state["observations"]),
        "pending": len(state["pending"]),
        "next_trial_id": state["next_trial_id"],
        "best": state["best"],
        "stale_pending": stale_pending,
        "observations_by_status": _status_counts(state["observations"]),
        "max_pending_age_seconds": max_pending_age,
        "paths": {
            "state_file": _relative_path(root, paths["state_file"]),
            "observations_csv": _relative_path(root, paths["observations_csv"]),
            "acquisition_log_file": _relative_path(root, paths["acquisition_log_file"]),
            "event_log_file": _relative_path(root, paths["event_log_file"]),
            "trials_dir": _relative_path(root, paths["trials_dir"]),
            "lock_file": _relative_path(root, paths["lock_file"]),
        },
    }


def _best_params_from_state(state: dict) -> dict | None:
    best = state.get("best")
    if not isinstance(best, dict):
        return None
    best_trial_id = int(best.get("trial_id", -1))
    for obs in state.get("observations", []):
        if int(obs.get("trial_id", -1)) == best_trial_id:
            params = obs.get("params")
            return params if isinstance(params, dict) else None
    return None


def _runtime_summary(observations: list[dict]) -> dict | None:
    runtimes = [
        float(obs["runtime_seconds"])
        for obs in observations
        if isinstance(obs.get("runtime_seconds"), (int, float))
        and not isinstance(obs.get("runtime_seconds"), bool)
        and math.isfinite(float(obs["runtime_seconds"]))
    ]
    if not runtimes:
        return None
    total = sum(runtimes)
    return {
        "count": len(runtimes),
        "min_seconds": min(runtimes),
        "max_seconds": max(runtimes),
        "mean_seconds": total / len(runtimes),
        "total_seconds": total,
    }


def _build_report_payload(
    *,
    state: dict,
    objective: dict,
    top_n: int,
) -> dict:
    objective_name = str(objective["name"])
    objective_direction = str(objective["direction"])
    observations = list(state.get("observations", []))
    status_counts = _status_counts(observations)

    ok_observations = [obs for obs in observations if str(obs.get("status", "")) == "ok"]
    if objective_direction == "minimize":
        ranked_ok = sorted(
            ok_observations, key=lambda obs: float(obs["objectives"][objective_name])
        )
    else:
        ranked_ok = sorted(
            ok_observations, key=lambda obs: float(obs["objectives"][objective_name]), reverse=True
        )

    top_trials = []
    for obs in ranked_ok[: max(1, int(top_n))]:
        top_trials.append(
            {
                "trial_id": int(obs["trial_id"]),
                "status": obs.get("status"),
                "objective_value": float(obs["objectives"][objective_name]),
                "penalty_objective": obs.get("penalty_objective"),
                "completed_at": obs.get("completed_at"),
                "params": obs.get("params"),
                "terminal_reason": obs.get("terminal_reason"),
            }
        )

    objective_trace = []
    for obs in sorted(observations, key=lambda row: int(row.get("trial_id", 0))):
        objective_trace.append(
            {
                "trial_id": int(obs["trial_id"]),
                "status": obs.get("status"),
                "objective_value": obs.get("objectives", {}).get(objective_name),
                "completed_at": obs.get("completed_at"),
            }
        )

    total_observations = len(observations)
    non_ok = total_observations - status_counts.get("ok", 0)
    failure_rate = (non_ok / total_observations) if total_observations else 0.0

    report = {
        "generated_at": time.time(),
        "objective": {
            "name": objective_name,
            "direction": objective_direction,
        },
        "counts": {
            "observations": total_observations,
            "pending": len(state.get("pending", [])),
            "observations_by_status": status_counts,
            "failure_rate": failure_rate,
        },
        "best": state.get("best"),
        "best_params": _best_params_from_state(state),
        "top_trials": top_trials,
        "objective_trace": objective_trace,
        "runtime_summary": _runtime_summary(observations),
    }
    return report


def _render_report_markdown(report: dict) -> str:
    objective = report["objective"]
    counts = report["counts"]
    lines = [
        "# Looptimum Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Objective: `{objective['name']}` ({objective['direction']})",
        f"- Observations: `{counts['observations']}`",
        f"- Pending: `{counts['pending']}`",
        f"- Failure rate: `{counts['failure_rate']:.4f}`",
        "",
        "## Best",
        "",
    ]
    best = report.get("best")
    if best is None:
        lines.append("No best trial yet.")
    else:
        lines.append(f"- trial_id: `{best['trial_id']}`")
        lines.append(f"- objective_value: `{best['objective_value']}`")
        best_params = report.get("best_params")
        lines.append(f"- params: `{json.dumps(best_params, sort_keys=True)}`")

    lines.extend(["", "## Top Trials", ""])
    top_trials = report.get("top_trials", [])
    if not top_trials:
        lines.append("No completed ok trials yet.")
    else:
        for row in top_trials:
            lines.append(
                f"- trial `{row['trial_id']}`: objective={row['objective_value']}, status={row['status']}"
            )

    runtime_summary = report.get("runtime_summary")
    lines.extend(["", "## Runtime Summary", ""])
    if runtime_summary is None:
        lines.append("No runtime_seconds fields found in observations.")
    else:
        lines.append(f"- count: `{runtime_summary['count']}`")
        lines.append(f"- min_seconds: `{runtime_summary['min_seconds']}`")
        lines.append(f"- max_seconds: `{runtime_summary['max_seconds']}`")
        lines.append(f"- mean_seconds: `{runtime_summary['mean_seconds']}`")
        lines.append(f"- total_seconds: `{runtime_summary['total_seconds']}`")

    return "\n".join(lines) + "\n"


def _validate_state_hard_checks(state: dict, objective_name: str) -> list[str]:
    errors: list[str] = []

    required_keys = ("meta", "observations", "pending", "next_trial_id", "best")
    for key in required_keys:
        if key not in state:
            errors.append(f"missing required state key: {key}")

    if not isinstance(state.get("meta"), dict):
        errors.append("state.meta must be an object")
    if not isinstance(state.get("observations"), list):
        errors.append("state.observations must be a list")
    if not isinstance(state.get("pending"), list):
        errors.append("state.pending must be a list")
    if not isinstance(state.get("next_trial_id"), int):
        errors.append("state.next_trial_id must be an integer")
    elif int(state["next_trial_id"]) < 1:
        errors.append("state.next_trial_id must be >= 1")

    observations = state.get("observations")
    observation_ids: list[int] = []
    if isinstance(observations, list):
        for idx, obs in enumerate(observations):
            if not isinstance(obs, dict):
                errors.append(f"state.observations[{idx}] must be an object")
                continue
            if not isinstance(obs.get("trial_id"), int):
                errors.append(f"state.observations[{idx}].trial_id must be an integer")
            else:
                observation_ids.append(int(obs["trial_id"]))
            if not isinstance(obs.get("params"), dict):
                errors.append(f"state.observations[{idx}].params must be an object")
            objectives = obs.get("objectives")
            if not isinstance(objectives, dict):
                errors.append(f"state.observations[{idx}].objectives must be an object")
            elif objective_name not in objectives:
                errors.append(
                    f"state.observations[{idx}].objectives missing primary objective '{objective_name}'"
                )
        if len(observation_ids) != len(set(observation_ids)):
            errors.append("state.observations contains duplicate trial_id values")

    pending = state.get("pending")
    pending_ids: list[int] = []
    if isinstance(pending, list):
        for idx, row in enumerate(pending):
            if not isinstance(row, dict):
                errors.append(f"state.pending[{idx}] must be an object")
                continue
            if not isinstance(row.get("trial_id"), int):
                errors.append(f"state.pending[{idx}].trial_id must be an integer")
            else:
                pending_ids.append(int(row["trial_id"]))
            if not isinstance(row.get("params"), dict):
                errors.append(f"state.pending[{idx}].params must be an object")
            if not isinstance(row.get("suggested_at"), (int, float)):
                errors.append(f"state.pending[{idx}].suggested_at must be numeric")
        if len(pending_ids) != len(set(pending_ids)):
            errors.append("state.pending contains duplicate trial_id values")

    overlap = sorted(set(observation_ids).intersection(pending_ids))
    if overlap:
        overlap_preview = ", ".join(str(trial_id) for trial_id in overlap[:5])
        if len(overlap) > 5:
            overlap_preview = f"{overlap_preview}, ..."
        errors.append(
            "state contains trial_id values present in both observations and pending: "
            f"{overlap_preview}"
        )

    if isinstance(state.get("next_trial_id"), int):
        highest_seen = max(observation_ids + pending_ids, default=0)
        if int(state["next_trial_id"]) <= highest_seen:
            errors.append("state.next_trial_id must be greater than any observed/pending trial_id")

    best = state.get("best")
    if best is not None:
        if not isinstance(best, dict):
            errors.append("state.best must be null or an object")
        else:
            best_trial_id = best.get("trial_id")
            if not isinstance(best_trial_id, int):
                errors.append("state.best.trial_id must be an integer")
            best_objective_name = best.get("objective_name")
            if best_objective_name != objective_name:
                errors.append(
                    f"state.best.objective_name must equal primary objective '{objective_name}'"
                )
            best_objective_value = best.get("objective_value")
            if (
                not isinstance(best_objective_value, (int, float))
                or isinstance(best_objective_value, bool)
                or not math.isfinite(float(best_objective_value))
            ):
                errors.append("state.best.objective_value must be a finite number")

            matching_ok_observation: dict[str, Any] | None = None
            if isinstance(observations, list) and isinstance(best_trial_id, int):
                for obs in observations:
                    if (
                        isinstance(obs, dict)
                        and isinstance(obs.get("trial_id"), int)
                        and int(obs["trial_id"]) == best_trial_id
                        and str(obs.get("status", "")) == "ok"
                    ):
                        matching_ok_observation = obs
                        break

            if isinstance(best_trial_id, int) and matching_ok_observation is None:
                errors.append("state.best.trial_id must reference an observed ok trial")
            elif matching_ok_observation is not None:
                objectives = matching_ok_observation.get("objectives")
                observed_primary = (
                    objectives.get(objective_name) if isinstance(objectives, dict) else None
                )
                if (
                    not isinstance(observed_primary, (int, float))
                    or isinstance(observed_primary, bool)
                    or not math.isfinite(float(observed_primary))
                ):
                    errors.append(
                        "state.best references an observation with non-numeric primary objective"
                    )
                elif (
                    isinstance(best_objective_value, (int, float))
                    and not isinstance(best_objective_value, bool)
                    and abs(float(observed_primary) - float(best_objective_value)) > 1e-12
                ):
                    errors.append(
                        "state.best.objective_value must match referenced observed objective"
                    )

    return errors


def _validate_state_warnings(
    *,
    state: dict,
    paths: dict[str, Path],
    max_pending_age: float | None,
) -> list[str]:
    warnings_out: list[str] = []

    pending = state.get("pending", [])
    if isinstance(pending, list) and max_pending_age is not None:
        now = time.time()
        stale_count = sum(
            1 for row in pending if pending_age_seconds(row, now=now) > max_pending_age
        )
        if stale_count > 0:
            warnings_out.append(
                f"{stale_count} pending trial(s) exceed max_pending_age_seconds={max_pending_age}"
            )

    for key in ("acquisition_log_file", "event_log_file", "observations_csv", "trials_dir"):
        if not paths[key].exists():
            warnings_out.append(f"optional path missing: {paths[key]}")

    return warnings_out


def _parse_heartbeat_meta(raw: str | None) -> dict | None:
    if raw is None:
        return None
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("--heartbeat-meta-json must parse to an object")
    return parsed


def cmd_suggest(args: argparse.Namespace) -> None:
    root = Path(args.project_root).resolve()
    cfg, _ = load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")

    space_cfg, space_path = load_contract_document(root, "parameter_space")
    if not isinstance(space_cfg, dict):
        raise ValueError(f"parameter_space must be an object: {space_path}")
    search_space_schema, _ = load_schema_from_paths(
        root,
        cfg["paths"],
        key="search_space_schema_file",
        default_rel="../_shared/schemas/search_space.schema.json",
    )
    validate_against_schema(space_cfg, search_space_schema, source_path=space_path)
    params = norm_space(space_cfg)

    obj_cfg, _ = load_contract_document(root, "objective_schema")
    if not isinstance(obj_cfg, dict):
        raise ValueError("objective_schema must be an object")
    objective = obj_cfg["primary_objective"]
    objective_name = str(objective["name"])

    paths = _runtime_paths(root, cfg)
    lock_timeout = resolve_lock_timeout_seconds(cfg, args.lock_timeout_seconds)
    max_pending_age = resolve_max_pending_age_seconds(cfg)

    with hold_exclusive_lock(
        paths["lock_file"], timeout_seconds=lock_timeout, fail_fast=args.fail_fast
    ) as lock:
        _append_event(
            paths,
            "lock_acquired",
            command="suggest",
            pid=os.getpid(),
            wait_seconds=lock.wait_seconds,
        )
        try:
            state = load_state(paths["state_file"])
            if state["meta"]["seed"] is None:
                state["meta"]["seed"] = int(cfg["seed"])

            now = time.time()
            stale_observations: list[dict] = []
            if max_pending_age is not None:
                stale_observations = _retire_stale_pending(
                    state,
                    objective_name=objective_name,
                    max_pending_age_seconds=max_pending_age,
                    now=now,
                    reason="retired_stale_auto",
                )
                for obs in stale_observations:
                    _ensure_terminal_manifest(
                        root,
                        paths,
                        obs,
                        objective_name=objective_name,
                        payload_copy_path=None,
                        now=now,
                    )
                    _append_event(
                        paths,
                        "trial_retired",
                        command="suggest",
                        mode="auto_stale",
                        trial_id=obs["trial_id"],
                        reason=obs["terminal_reason"],
                    )

            if len(state["observations"]) + len(state["pending"]) >= int(cfg["max_trials"]):
                if stale_observations:
                    update_best(state, objective)
                    _save_state_and_rows(paths, state)
                print("No suggestion generated: budget exhausted.")
                return

            seed = int(state["meta"]["seed"]) + int(state["next_trial_id"])
            rng = random.Random(seed)
            cand, decision = propose(rng, state, cfg, params, obj_cfg, seed)
            trial_id = int(state["next_trial_id"])
            suggestion = {"trial_id": trial_id, "params": cand, "suggested_at": time.time()}

            suggestion_schema, _ = load_schema_from_paths(
                root,
                cfg["paths"],
                key="suggestion_schema_file",
                default_rel="../_shared/schemas/suggestion_payload.schema.json",
            )
            validate_against_schema(
                suggestion,
                suggestion_schema,
                source_path=Path("<generated_suggestion>"),
                trial_id=trial_id,
            )

            state["pending"].append(suggestion)
            state["next_trial_id"] = trial_id + 1
            _ensure_pending_manifest(
                paths,
                suggestion,
                objective_name=objective_name,
                now=time.time(),
            )

            append_jsonl(
                paths["acquisition_log_file"],
                {"trial_id": trial_id, "decision": decision, "timestamp": time.time()},
            )
            _append_event(paths, "suggestion_created", trial_id=trial_id)

            save_state(paths["state_file"], state)
            if stale_observations:
                write_obs_csv(paths["observations_csv"], _observation_rows(state))

            print(json.dumps(suggestion, indent=2))
            if not args.json_only:
                print(f"Objective direction: {objective['direction']} ({objective['name']})")
        finally:
            _append_event(paths, "lock_released", command="suggest", pid=os.getpid())


def cmd_ingest(args: argparse.Namespace) -> None:
    root = Path(args.project_root).resolve()
    cfg, _ = load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")

    obj_cfg, _ = load_contract_document(root, "objective_schema")
    if not isinstance(obj_cfg, dict):
        raise ValueError("objective_schema must be an object")
    objective = obj_cfg["primary_objective"]
    objective_name = str(objective["name"])

    ingest_schema, _ = load_schema_from_paths(
        root,
        cfg["paths"],
        key="ingest_schema_file",
        legacy_key="result_schema_file",
        default_rel="../_shared/schemas/ingest_payload.schema.json",
    )

    paths = _runtime_paths(root, cfg)
    lock_timeout = resolve_lock_timeout_seconds(cfg, args.lock_timeout_seconds)

    with hold_exclusive_lock(
        paths["lock_file"], timeout_seconds=lock_timeout, fail_fast=args.fail_fast
    ) as lock:
        _append_event(
            paths,
            "lock_acquired",
            command="ingest",
            pid=os.getpid(),
            wait_seconds=lock.wait_seconds,
        )
        try:
            state = load_state(paths["state_file"])

            payload_path = Path(args.results_file)
            payload = load_data_file(payload_path)
            if not isinstance(payload, dict):
                raise ValueError(f"Ingest payload must be an object: {payload_path}")
            validate_against_schema(payload, ingest_schema, source_path=payload_path)
            payload, trial_id = normalize_ingest_payload(
                payload,
                objective_name=objective_name,
                source_path=payload_path,
            )
            heartbeat_fields = _load_heartbeat_fields(payload, trial_id)

            pending = {int(row["trial_id"]): row for row in state["pending"]}
            if trial_id not in pending:
                prior = next(
                    (obs for obs in state["observations"] if int(obs["trial_id"]) == trial_id), None
                )
                if prior is None:
                    raise ValueError(f"trial_id {trial_id} is not pending")

                expected = build_observation_contract(prior, objective_name=objective_name)
                received = {
                    "trial_id": trial_id,
                    "params": payload["params"],
                    "objectives": payload["objectives"],
                    "status": payload["status"],
                }
                if "penalty_objective" in payload:
                    received["penalty_objective"] = payload["penalty_objective"]
                diffs = diff_contract_records(expected, received)
                if not diffs:
                    _append_event(paths, "ingest_duplicate_noop", trial_id=trial_id)
                    print(f"No-op: trial_id={trial_id} already ingested with identical payload.")
                    return
                raise ValueError(format_contract_diff_error(trial_id, diffs))

            if payload.get("params") != pending[trial_id].get("params"):
                param_diffs = diff_contract_records(
                    {"params": pending[trial_id].get("params", {})},
                    {"params": payload.get("params", {})},
                )
                details = "\n".join(f"- field {diff}" for diff in param_diffs)
                raise ValueError(
                    f"ingest payload params mismatch for pending trial_id {trial_id}:\n{details}"
                )

            pending_entry = _pop_pending(state, trial_id)
            if pending_entry is None:
                raise ValueError(f"trial_id {trial_id} is not pending")

            now = time.time()
            observation = {
                "trial_id": trial_id,
                "params": payload["params"],
                "objectives": payload["objectives"],
                "status": payload["status"],
                "suggested_at": pending_entry.get("suggested_at"),
                "completed_at": now,
            }
            if "penalty_objective" in payload:
                observation["penalty_objective"] = payload["penalty_objective"]

            if "heartbeat_count" in pending_entry:
                observation["heartbeat_count"] = pending_entry["heartbeat_count"]
            if "last_heartbeat_at" in pending_entry:
                observation["last_heartbeat_at"] = pending_entry["last_heartbeat_at"]
            if "heartbeat_note" in pending_entry:
                observation["heartbeat_note"] = pending_entry["heartbeat_note"]
            if "heartbeat_meta" in pending_entry:
                observation["heartbeat_meta"] = pending_entry["heartbeat_meta"]

            observation.update(heartbeat_fields)
            state["observations"].append(observation)
            update_best(state, objective)

            payload_copy_path = trial_dir(paths["trials_dir"], trial_id) / "ingest_payload.json"
            atomic_write_json(payload_copy_path, payload, indent=2)
            _ensure_terminal_manifest(
                root,
                paths,
                observation,
                objective_name=objective_name,
                payload_copy_path=payload_copy_path,
                now=now,
            )

            _save_state_and_rows(paths, state)
            _append_event(paths, "ingest_applied", trial_id=trial_id, status=observation["status"])
            print(f"Ingested trial_id={trial_id}. Observations={len(state['observations'])}")
        finally:
            _append_event(paths, "lock_released", command="ingest", pid=os.getpid())


def cmd_cancel(args: argparse.Namespace) -> None:
    if args.trial_id is None:
        raise ValueError("cancel requires --trial-id")

    root = Path(args.project_root).resolve()
    cfg, _ = load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")
    obj_cfg, _ = load_contract_document(root, "objective_schema")
    if not isinstance(obj_cfg, dict):
        raise ValueError("objective_schema must be an object")
    objective = obj_cfg["primary_objective"]
    objective_name = str(objective["name"])

    paths = _runtime_paths(root, cfg)
    lock_timeout = resolve_lock_timeout_seconds(cfg, args.lock_timeout_seconds)

    with hold_exclusive_lock(
        paths["lock_file"], timeout_seconds=lock_timeout, fail_fast=args.fail_fast
    ) as lock:
        _append_event(
            paths,
            "lock_acquired",
            command="cancel",
            pid=os.getpid(),
            wait_seconds=lock.wait_seconds,
        )
        try:
            state = load_state(paths["state_file"])
            pending_entry = _pop_pending(state, int(args.trial_id))
            if pending_entry is None:
                raise ValueError(f"trial_id {args.trial_id} is not pending")

            now = time.time()
            terminal_reason = args.reason or "canceled"
            observation = _new_terminal_observation(
                pending_entry,
                objective_name=objective_name,
                terminal_reason=terminal_reason,
                now=now,
            )
            state["observations"].append(observation)
            update_best(state, objective)
            _ensure_terminal_manifest(
                root,
                paths,
                observation,
                objective_name=objective_name,
                payload_copy_path=None,
                now=now,
            )
            _save_state_and_rows(paths, state)
            _append_event(
                paths,
                "trial_canceled",
                trial_id=observation["trial_id"],
                reason=terminal_reason,
            )
            print(f"Canceled trial_id={observation['trial_id']}. Pending={len(state['pending'])}")
        finally:
            _append_event(paths, "lock_released", command="cancel", pid=os.getpid())


def cmd_retire(args: argparse.Namespace) -> None:
    if args.trial_id is None and not args.stale:
        raise ValueError("retire requires --trial-id and/or --stale")

    root = Path(args.project_root).resolve()
    cfg, _ = load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")
    obj_cfg, _ = load_contract_document(root, "objective_schema")
    if not isinstance(obj_cfg, dict):
        raise ValueError("objective_schema must be an object")
    objective = obj_cfg["primary_objective"]
    objective_name = str(objective["name"])

    paths = _runtime_paths(root, cfg)
    lock_timeout = resolve_lock_timeout_seconds(cfg, args.lock_timeout_seconds)

    with hold_exclusive_lock(
        paths["lock_file"], timeout_seconds=lock_timeout, fail_fast=args.fail_fast
    ) as lock:
        _append_event(
            paths,
            "lock_acquired",
            command="retire",
            pid=os.getpid(),
            wait_seconds=lock.wait_seconds,
        )
        try:
            state = load_state(paths["state_file"])
            now = time.time()

            stale_ids: set[int] = set()
            max_age_for_stale: float | None = None
            if args.stale:
                if args.max_age_seconds is not None:
                    max_age_for_stale = float(args.max_age_seconds)
                    if max_age_for_stale <= 0:
                        raise ValueError("--max-age-seconds must be > 0 when provided")
                else:
                    max_age_for_stale = resolve_max_pending_age_seconds(cfg)
                if max_age_for_stale is None:
                    raise ValueError(
                        "retire --stale requires max_pending_age_seconds in config or --max-age-seconds"
                    )
                stale_ids = {
                    int(pending["trial_id"])
                    for pending in state["pending"]
                    if pending_age_seconds(pending, now=now) > max_age_for_stale
                }

            target_ids: list[int] = []
            if args.trial_id is not None:
                target_ids.append(int(args.trial_id))
            for trial_id in sorted(stale_ids):
                if trial_id not in target_ids:
                    target_ids.append(trial_id)

            retired: list[dict] = []
            for trial_id in target_ids:
                pending_entry = _pop_pending(state, trial_id)
                if pending_entry is None:
                    if args.trial_id == trial_id:
                        raise ValueError(f"trial_id {trial_id} is not pending")
                    continue
                terminal_reason = args.reason or (
                    "retired_stale" if trial_id in stale_ids else "retired_manual"
                )
                observation = _new_terminal_observation(
                    pending_entry,
                    objective_name=objective_name,
                    terminal_reason=terminal_reason,
                    now=now,
                )
                state["observations"].append(observation)
                retired.append(observation)

            if not retired:
                print("No pending trials retired.")
                return

            update_best(state, objective)
            for observation in retired:
                _ensure_terminal_manifest(
                    root,
                    paths,
                    observation,
                    objective_name=objective_name,
                    payload_copy_path=None,
                    now=now,
                )
                _append_event(
                    paths,
                    "trial_retired",
                    trial_id=observation["trial_id"],
                    reason=observation["terminal_reason"],
                    mode="manual",
                )

            _save_state_and_rows(paths, state)
            print(f"Retired {len(retired)} pending trial(s). Pending={len(state['pending'])}")
        finally:
            _append_event(paths, "lock_released", command="retire", pid=os.getpid())


def cmd_heartbeat(args: argparse.Namespace) -> None:
    if args.trial_id is None:
        raise ValueError("heartbeat requires --trial-id")

    root = Path(args.project_root).resolve()
    cfg, _ = load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")
    obj_cfg, _ = load_contract_document(root, "objective_schema")
    if not isinstance(obj_cfg, dict):
        raise ValueError("objective_schema must be an object")
    objective = obj_cfg["primary_objective"]
    objective_name = str(objective["name"])

    paths = _runtime_paths(root, cfg)
    lock_timeout = resolve_lock_timeout_seconds(cfg, args.lock_timeout_seconds)

    with hold_exclusive_lock(
        paths["lock_file"], timeout_seconds=lock_timeout, fail_fast=args.fail_fast
    ) as lock:
        _append_event(
            paths,
            "lock_acquired",
            command="heartbeat",
            pid=os.getpid(),
            wait_seconds=lock.wait_seconds,
        )
        try:
            state = load_state(paths["state_file"])
            index = _pending_index(state, int(args.trial_id))
            if index is None:
                raise ValueError(f"trial_id {args.trial_id} is not pending")

            heartbeat_at = time.time() if args.heartbeat_at is None else float(args.heartbeat_at)
            if heartbeat_at <= 0 or not math.isfinite(heartbeat_at):
                raise ValueError("--heartbeat-at must be a positive finite epoch seconds value")

            heartbeat_meta = _parse_heartbeat_meta(args.heartbeat_meta_json)
            pending_entry = state["pending"][index]
            pending_entry["last_heartbeat_at"] = heartbeat_at
            pending_entry["heartbeat_count"] = int(pending_entry.get("heartbeat_count", 0) or 0) + 1
            if args.heartbeat_note is not None:
                pending_entry["heartbeat_note"] = args.heartbeat_note
            if heartbeat_meta is not None:
                pending_entry["heartbeat_meta"] = heartbeat_meta

            state["pending"][index] = pending_entry
            _ensure_pending_manifest(
                paths,
                pending_entry,
                objective_name=objective_name,
                now=time.time(),
            )
            save_state(paths["state_file"], state)
            _append_event(
                paths,
                "heartbeat",
                trial_id=int(args.trial_id),
                heartbeat_at=heartbeat_at,
            )
            print(f"Heartbeat recorded for trial_id={int(args.trial_id)}.")
        finally:
            _append_event(paths, "lock_released", command="heartbeat", pid=os.getpid())


def cmd_status(args: argparse.Namespace) -> None:
    root = Path(args.project_root).resolve()
    cfg, _ = load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")
    paths = _runtime_paths(root, cfg)
    state = load_state(paths["state_file"])
    max_pending_age = resolve_max_pending_age_seconds(cfg)
    print(json.dumps(_status_payload(root, state, paths, max_pending_age), indent=2))


def cmd_report(args: argparse.Namespace) -> None:
    root = Path(args.project_root).resolve()
    cfg, _ = load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")
    obj_cfg, _ = load_contract_document(root, "objective_schema")
    if not isinstance(obj_cfg, dict):
        raise ValueError("objective_schema must be an object")
    objective = obj_cfg["primary_objective"]
    if not isinstance(objective, dict):
        raise ValueError("objective_schema.primary_objective must be an object")

    paths = _runtime_paths(root, cfg)
    lock_timeout = resolve_lock_timeout_seconds(cfg, args.lock_timeout_seconds)

    with hold_exclusive_lock(
        paths["lock_file"], timeout_seconds=lock_timeout, fail_fast=args.fail_fast
    ) as lock:
        _append_event(
            paths,
            "lock_acquired",
            command="report",
            pid=os.getpid(),
            wait_seconds=lock.wait_seconds,
        )
        try:
            state = load_state(paths["state_file"])
            report = _build_report_payload(
                state=state,
                objective=objective,
                top_n=max(1, int(args.top_n)),
            )
            atomic_write_json(paths["report_json_file"], report, indent=2)
            atomic_write_text(paths["report_md_file"], _render_report_markdown(report))
            _append_event(
                paths,
                "report_generated",
                report_json=_relative_path(root, paths["report_json_file"]),
                report_md=_relative_path(root, paths["report_md_file"]),
            )
            print(
                "Generated report files:\n"
                f"- {paths['report_json_file']}\n"
                f"- {paths['report_md_file']}"
            )
        finally:
            _append_event(paths, "lock_released", command="report", pid=os.getpid())


def cmd_validate(args: argparse.Namespace) -> None:
    root = Path(args.project_root).resolve()
    hard_errors: list[str] = []
    warnings_out: list[str] = []

    try:
        cfg, _ = load_contract_document(root, "bo_config")
        if not isinstance(cfg, dict):
            raise ValueError("bo_config must be an object")
    except Exception as exc:  # pragma: no cover - exercised by subprocess integration tests.
        hard_errors.append(f"config load failure: {exc}")
        cfg = {}

    try:
        space_cfg, space_path = load_contract_document(root, "parameter_space")
        if not isinstance(space_cfg, dict):
            raise ValueError("parameter_space must be an object")
        search_space_schema, _ = load_schema_from_paths(
            root,
            cfg.get("paths", {}),
            key="search_space_schema_file",
            default_rel="../_shared/schemas/search_space.schema.json",
        )
        validate_against_schema(space_cfg, search_space_schema, source_path=space_path)
    except Exception as exc:  # pragma: no cover
        hard_errors.append(f"parameter_space validation failure: {exc}")

    objective_name = "loss"
    try:
        obj_cfg, _ = load_contract_document(root, "objective_schema")
        if not isinstance(obj_cfg, dict):
            raise ValueError("objective_schema must be an object")
        objective = obj_cfg.get("primary_objective")
        if not isinstance(objective, dict):
            raise ValueError("objective_schema.primary_objective must be an object")
        objective_name = str(objective["name"])
    except Exception as exc:  # pragma: no cover
        hard_errors.append(f"objective_schema validation failure: {exc}")

    if hard_errors:
        for err in hard_errors:
            print(f"ERROR: {err}")
        raise SystemExit(1)

    paths = _runtime_paths(root, cfg)
    try:
        state = load_state(paths["state_file"])
    except Exception as exc:
        print(f"ERROR: state load failure: {exc}")
        raise SystemExit(1) from exc

    hard_errors.extend(_validate_state_hard_checks(state, objective_name))
    warnings_out.extend(
        _validate_state_warnings(
            state=state,
            paths=paths,
            max_pending_age=resolve_max_pending_age_seconds(cfg),
        )
    )

    for err in hard_errors:
        print(f"ERROR: {err}")
    for warning in warnings_out:
        print(f"WARNING: {warning}")

    if hard_errors:
        raise SystemExit(1)
    if warnings_out and args.strict:
        raise SystemExit(1)

    print("Validation passed.")


def cmd_doctor(args: argparse.Namespace) -> None:
    root = Path(args.project_root).resolve()
    cfg, _ = load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")

    obj_cfg, _ = load_contract_document(root, "objective_schema")
    if not isinstance(obj_cfg, dict):
        raise ValueError("objective_schema must be an object")
    objective = obj_cfg["primary_objective"]

    paths = _runtime_paths(root, cfg)
    state = load_state(paths["state_file"])
    max_pending_age = resolve_max_pending_age_seconds(cfg)
    status = _status_payload(root, state, paths, max_pending_age)

    backend = str(cfg.get("surrogate", {}).get("type", "rbf_proxy")).lower()
    gp_dependency_available = None
    if backend == "gp":
        try:
            import sklearn  # noqa: F401

            gp_dependency_available = True
        except Exception:
            gp_dependency_available = False

    payload = {
        "generated_at": time.time(),
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "platform": sys.platform,
        "project_root": str(root),
        "pid": os.getpid(),
        "backend": {
            "configured": backend,
            "gp_dependency_available": gp_dependency_available,
        },
        "objective": objective,
        "status": status,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return

    print("Looptimum Doctor")
    print(f"- python_version: {payload['python_version']}")
    print(f"- python_executable: {payload['python_executable']}")
    print(f"- platform: {payload['platform']}")
    print(f"- project_root: {payload['project_root']}")
    print(f"- backend.configured: {backend}")
    if gp_dependency_available is not None:
        print(f"- backend.gp_dependency_available: {gp_dependency_available}")
    print(f"- observations: {status['observations']}")
    print(f"- pending: {status['pending']}")
    print(f"- stale_pending: {status['stale_pending']}")
    print(f"- next_trial_id: {status['next_trial_id']}")
    print(f"- state_file: {status['paths']['state_file']}")
    print(f"- event_log_file: {status['paths']['event_log_file']}")


def cmd_demo(args: argparse.Namespace) -> None:
    root = Path(args.project_root).resolve()

    def toy_loss(params: dict) -> float:
        return (
            (params["x1"] - 0.25) ** 2
            + (params["x2"] - 0.75) ** 2
            + 0.2 * math.sin(8.0 * params["x1"])
        )

    for _ in range(int(args.steps)):
        cfg, _ = load_contract_document(root, "bo_config")
        if not isinstance(cfg, dict):
            raise ValueError("bo_config must be an object")
        paths = _runtime_paths(root, cfg)
        state_before = load_state(paths["state_file"])
        pending_before = len(state_before["pending"])
        cmd_suggest(args)
        state = load_state(paths["state_file"])
        if len(state["pending"]) <= pending_before:
            print("Demo stopped: no pending suggestion generated.")
            break
        latest = state["pending"][-1]
        out = {
            "trial_id": latest["trial_id"],
            "params": latest["params"],
            "objectives": {"loss": toy_loss(latest["params"])},
            "status": "ok",
        }
        path = trial_dir(paths["trials_dir"], int(latest["trial_id"])) / "demo_result.json"
        atomic_write_json(path, out, indent=2)
        args.results_file = str(path)
        cmd_ingest(args)
    cmd_status(args)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Looptimum: minimal client-facing optimization harness"
    )
    parser.add_argument(
        "command",
        choices=[
            "suggest",
            "ingest",
            "status",
            "demo",
            "cancel",
            "retire",
            "heartbeat",
            "report",
            "validate",
            "doctor",
        ],
    )
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--results-file", default="examples/example_results.json")
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--trial-id", type=int)
    parser.add_argument(
        "--stale", action="store_true", help="For retire: retire stale pending trials"
    )
    parser.add_argument(
        "--max-age-seconds",
        type=float,
        help="For retire --stale: override stale age threshold in seconds",
    )
    parser.add_argument("--reason", help="For cancel/retire: terminal reason to store")
    parser.add_argument("--heartbeat-at", type=float, help="For heartbeat: explicit epoch seconds")
    parser.add_argument("--heartbeat-note", help="For heartbeat: short status note")
    parser.add_argument(
        "--heartbeat-meta-json",
        help='For heartbeat: JSON object payload, e.g. \'{"worker":"node-1"}\'',
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="For suggest: print only JSON (no trailing human-readable line).",
    )
    parser.add_argument(
        "--lock-timeout-seconds",
        type=float,
        help="Override lock acquisition timeout for mutating commands",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="For mutating commands: fail immediately if lock is already held",
    )
    parser.add_argument("--top-n", type=int, default=5, help="For report: number of top trials")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="For validate: treat warnings as fatal (non-zero exit).",
    )
    parser.add_argument(
        "--json", action="store_true", help="For doctor: emit machine-readable JSON output."
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    commands = {
        "suggest": cmd_suggest,
        "ingest": cmd_ingest,
        "status": cmd_status,
        "demo": cmd_demo,
        "cancel": cmd_cancel,
        "retire": cmd_retire,
        "heartbeat": cmd_heartbeat,
        "report": cmd_report,
        "validate": cmd_validate,
        "doctor": cmd_doctor,
    }
    try:
        commands[args.command](args)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
