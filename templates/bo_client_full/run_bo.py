#!/usr/bin/env python3
"""Client-facing single-stage optimization harness with resumable state.

bo_client_full adds an optional BoTorch GP backend behind a feature flag (with
proxy fallback support).
"""

from __future__ import annotations

import argparse
import copy
import csv
import importlib.util
import json
import math
import os
import random
import secrets
import shutil
import sys
import time
from io import StringIO
from pathlib import Path
from typing import Any

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
_CONSTRAINTS = _load_shared_module("looptimum_shared_constraints", "constraints.py")
_OBJECTIVES = _load_shared_module("looptimum_shared_objectives", "objectives.py")
_ARCHIVES = _load_shared_module("looptimum_shared_archives", "archives.py")
_RUNTIME = _load_shared_module("looptimum_shared_runtime", "runtime.py")
_SEARCH_SPACE = _load_shared_module("looptimum_shared_search_space", "search_space.py")
_OBSERVATIONS_IO = _load_shared_module("looptimum_shared_observations_io", "observations_io.py")

build_observation_contract = _CONTRACT.build_observation_contract
diff_contract_records = _CONTRACT.diff_contract_records
format_contract_diff_error = _CONTRACT.format_contract_diff_error
load_contract_document = _CONTRACT.load_contract_document
load_optional_contract_document = _CONTRACT.load_optional_contract_document
load_data_file = _CONTRACT.load_data_file
load_schema_from_paths = _CONTRACT.load_schema_from_paths
normalize_ingest_payload = _CONTRACT.normalize_ingest_payload
validate_against_schema = _CONTRACT.validate_against_schema

normalize_constraints = _CONSTRAINTS.normalize_constraints
apply_bound_tightening = _CONSTRAINTS.apply_bound_tightening
build_constraint_error_reason = _CONSTRAINTS.build_constraint_error_reason
build_constraint_status = _CONSTRAINTS.build_constraint_status
format_reject_summary = _CONSTRAINTS.format_reject_summary
sample_feasible_candidates = _CONSTRAINTS.sample_feasible_candidates

normalize_objective_schema = _OBJECTIVES.normalize_objective_schema
best_objective_name = _OBJECTIVES.best_objective_name
best_rank_key = _OBJECTIVES.best_rank_key
build_best_record = _OBJECTIVES.build_best_record
build_objective_metadata = _OBJECTIVES.build_objective_metadata
canonical_objective_vector = _OBJECTIVES.canonical_objective_vector
objective_names = _OBJECTIVES.objective_names
objective_config_snapshot = _OBJECTIVES.objective_config_snapshot
pareto_front_records = _OBJECTIVES.pareto_front_records
primary_objective_name = _OBJECTIVES.primary_objective_name
scalarize_objectives = _OBJECTIVES.scalarize_objectives
scalarization_policy = _OBJECTIVES.scalarization_policy
scalarized_direction = _OBJECTIVES.scalarized_direction

build_reset_archive_manifest = _ARCHIVES.build_reset_archive_manifest
copy_path_to_archive = _ARCHIVES.copy_path_to_archive
list_reset_archives = _ARCHIVES.list_reset_archives
plan_reset_archive_prune = _ARCHIVES.plan_reset_archive_prune
prune_reset_archives = _ARCHIVES.prune_reset_archives
render_reset_archive_listing = _ARCHIVES.render_reset_archive_listing
reset_archives_root = _ARCHIVES.reset_archives_root
reset_artifact_paths = _ARCHIVES.reset_artifact_paths
restore_reset_archive = _ARCHIVES.restore_reset_archive
write_archive_manifest = _ARCHIVES.write_archive_manifest

append_jsonl = _RUNTIME.append_jsonl
atomic_write_json = _RUNTIME.atomic_write_json
atomic_write_text = _RUNTIME.atomic_write_text
hold_exclusive_lock = _RUNTIME.hold_exclusive_lock
load_trial_manifest = _RUNTIME.load_trial_manifest
pending_age_seconds = _RUNTIME.pending_age_seconds
resolve_lock_timeout_seconds = _RUNTIME.resolve_lock_timeout_seconds
resolve_max_pending_age_seconds = _RUNTIME.resolve_max_pending_age_seconds
resolve_max_pending_trials = _RUNTIME.resolve_max_pending_trials
resolve_worker_leases_enabled = _RUNTIME.resolve_worker_leases_enabled
resolve_runtime_paths = _RUNTIME.resolve_runtime_paths
save_trial_manifest = _RUNTIME.save_trial_manifest
state_for_persist = _RUNTIME.state_for_persist
state_schema_upgrade_pending = _RUNTIME.state_schema_upgrade_pending
state_schema_version = _RUNTIME.state_schema_version
normalize_state_schema_version = _RUNTIME.normalize_state_schema_version
trial_dir = _RUNTIME.trial_dir
STATE_SCHEMA_VERSION = _RUNTIME.STATE_SCHEMA_VERSION

normalize_search_space = _SEARCH_SPACE.normalize_search_space
sample_random_point = _SEARCH_SPACE.sample_random_point
normalized_numeric_distance = _SEARCH_SPACE.normalized_numeric_distance
normalize_numeric_point = _SEARCH_SPACE.normalize_numeric_point
denormalize_numeric_point = _SEARCH_SPACE.denormalize_numeric_point
canonicalize_conditional_params = _SEARCH_SPACE.canonicalize_conditional_params

infer_observation_format = _OBSERVATIONS_IO.infer_observation_format
load_observation_rows = _OBSERVATIONS_IO.load_observation_rows
normalize_import_record = _OBSERVATIONS_IO.normalize_import_record
normalize_import_records_permissive = _OBSERVATIONS_IO.normalize_import_records_permissive
next_import_trial_id = _OBSERVATIONS_IO.next_import_trial_id
plan_import_trial_ids = _OBSERVATIONS_IO.plan_import_trial_ids
render_observations_csv = _OBSERVATIONS_IO.render_observations_csv
render_observations_jsonl = _OBSERVATIONS_IO.render_observations_jsonl


class ConstraintSamplingFailure(ValueError):
    def __init__(self, message: str, *, decision: dict) -> None:
        super().__init__(message)
        self.decision = decision


def load_cfg(path: Path) -> dict:
    data = load_data_file(path)
    if not isinstance(data, dict):
        raise ValueError(f"Config/state file must contain an object: {path}")
    return data


def load_state(path: Path) -> dict:
    state: dict
    if path.exists():
        state = load_cfg(path)
    else:
        state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "meta": {"created_at": time.time(), "seed": None},
            "observations": [],
            "pending": [],
            "next_trial_id": 1,
            "best": None,
        }
    return normalize_state_schema_version(state, state_path=path)


def save_state(path: Path, state: dict) -> None:
    atomic_write_json(path, state_for_persist(state), indent=2)


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


def norm_dist(a: dict, b: dict, params: list[dict]) -> float:
    return float(normalized_numeric_distance(a, b, params))


def predict_rbf_proxy(
    x: dict, obs: list[dict], params: list[dict], objective_cfg: dict, length_scale: float
) -> tuple[float, float]:
    if not obs:
        return 0.0, 1.0
    ys = []
    ws = []
    for row in obs:
        distance = norm_dist(x, row["params"], params)
        weight = math.exp(-(distance * distance) / (2.0 * max(length_scale, 1e-6) ** 2))
        ys.append(float(scalarize_objectives(row["objectives"], objective_cfg)))
        ws.append(weight)
    total_weight = sum(ws)
    if total_weight < 1e-9:
        return sum(ys) / len(ys), 1.0
    mean = sum(weight * y for weight, y in zip(ws, ys)) / total_weight
    variance = sum(weight * (y - mean) ** 2 for weight, y in zip(ws, ys)) / total_weight
    density = total_weight / len(obs)
    std = math.sqrt(max(variance, 1e-12)) + max(0.0, 1.0 - min(1.0, density))
    return mean, std


def acq_score(mean: float, std: float, best: float | None, direction: str, acq: dict) -> float:
    acq_type = acq.get("type", "ucb")
    kappa = float(acq.get("kappa", 1.5))
    xi = float(acq.get("xi", 0.01))
    if acq_type == "ucb":
        return -(mean - kappa * std) if direction == "minimize" else (mean + kappa * std)
    if acq_type == "ei_proxy":
        if best is None:
            return std
        improvement = max(0.0, best - mean) if direction == "minimize" else max(0.0, mean - best)
        return improvement + xi * std
    raise ValueError(f"Unsupported acquisition type: {acq_type}")


def _candidate_pool(rng: random.Random, params: list[dict], n: int) -> list[dict]:
    return [sample_random_point(rng, params) for _ in range(int(n))]


def _is_usable_observation(row: dict, objective_cfg: dict) -> bool:
    if str(row.get("status", "ok")) != "ok":
        return False
    try:
        canonical_objective_vector(row.get("objectives"), objective_cfg)
    except ValueError:
        return False
    return True


def _load_objective_config(root: Path, cfg: dict) -> dict:
    obj_cfg, obj_path = load_contract_document(root, "objective_schema")
    if not isinstance(obj_cfg, dict):
        raise ValueError("objective_schema must be an object")
    objective_schema, _ = load_schema_from_paths(
        root,
        cfg.get("paths", {}),
        key="objective_schema_schema_file",
        default_rel="../_shared/schemas/objective_schema.schema.json",
    )
    validate_against_schema(obj_cfg, objective_schema, source_path=obj_path)
    return normalize_objective_schema(obj_cfg)


def _load_constraints(root: Path, cfg: dict, params: list[dict]) -> dict | None:
    constraints_cfg, constraints_path = load_optional_contract_document(root, "constraints")
    if constraints_path is None:
        return None
    if not isinstance(constraints_cfg, dict):
        raise ValueError("constraints must be an object")
    constraints_schema, _ = load_schema_from_paths(
        root,
        cfg.get("paths", {}),
        key="constraints_schema_file",
        default_rel="../_shared/schemas/constraints.schema.json",
    )
    validate_against_schema(constraints_cfg, constraints_schema, source_path=constraints_path)
    return normalize_constraints(constraints_cfg, params)


def _sampling_attempt_budget(cfg: dict, constraints: dict | None, target_count: int) -> int:
    if not constraints:
        return target_count
    candidate_pool_size = max(1, int(cfg["candidate_pool_size"]))
    return max(target_count, candidate_pool_size, target_count * 8)


def _sample_random_candidates(
    rng: random.Random,
    cfg: dict,
    params: list[dict],
    constraints: dict | None,
    *,
    target_count: int,
) -> dict:
    sampling_params = apply_bound_tightening(params, constraints)
    return sample_feasible_candidates(
        lambda: sample_random_point(rng, sampling_params),
        constraints,
        target_count=target_count,
        max_attempts=_sampling_attempt_budget(cfg, constraints, target_count),
    )


def _decision_with_constraint_status(decision: dict, status: dict) -> dict:
    enriched = dict(decision)
    enriched["constraint_status"] = status
    return enriched


def _require_feasible_candidates(
    sampled: dict,
    constraints: dict | None,
    *,
    strategy: str,
    surrogate_backend: str | None,
    phase: str,
    requested: int,
    fallback_reason: str | None = None,
) -> tuple[list[dict], dict]:
    status = build_constraint_status(
        constraints,
        sampled,
        phase=phase,
        requested=requested,
    )
    candidates = sampled["candidates"]
    if candidates:
        return candidates, status

    decision = {
        "strategy": strategy,
        "surrogate_backend": surrogate_backend,
        "constraint_status": status,
    }
    if fallback_reason is not None:
        decision["fallback_reason"] = fallback_reason
    decision["constraint_error_reason"] = build_constraint_error_reason(status)
    raise ConstraintSamplingFailure(str(decision["constraint_error_reason"]), decision=decision)


def propose_with_proxy(
    rng: random.Random,
    observations: list[dict],
    state: dict,
    cfg: dict,
    params: list[dict],
    objective_cfg: dict,
    constraints: dict | None = None,
) -> tuple[dict, dict]:
    surrogate_cfg = cfg["surrogate"]
    acq_cfg = cfg["acquisition"]
    best = state["best"]["objective_value"] if state["best"] else None
    direction = scalarized_direction(objective_cfg)
    scored = []
    requested = int(cfg["candidate_pool_size"])
    sampled = _sample_random_candidates(
        rng,
        cfg,
        params,
        constraints,
        target_count=requested,
    )
    candidates, status = _require_feasible_candidates(
        sampled,
        constraints,
        strategy="surrogate_acquisition",
        surrogate_backend="rbf_proxy",
        phase="candidate-pool",
        requested=requested,
    )
    for candidate in candidates:
        mean, std = predict_rbf_proxy(
            candidate,
            observations,
            params,
            objective_cfg,
            float(surrogate_cfg.get("length_scale", 0.2)),
        )
        scored.append((acq_score(mean, std, best, direction, acq_cfg), candidate, mean, std))
    scored.sort(key=lambda row: row[0], reverse=True)
    score, candidate, mean, std = scored[0]
    return candidate, _decision_with_constraint_status(
        {
            "strategy": "surrogate_acquisition",
            "surrogate_backend": "rbf_proxy",
            "acquisition_type": acq_cfg.get("type", "ucb"),
            "predicted_mean": mean,
            "predicted_std": std,
            "acquisition_score": score,
        },
        status,
    )


def propose_with_botorch(
    rng: random.Random,
    observations: list[dict],
    state: dict,
    cfg: dict,
    params: list[dict],
    objective_cfg: dict,
    constraints: dict | None = None,
) -> tuple[dict, dict]:
    import torch
    from botorch.fit import fit_gpytorch_mll
    from botorch.models import SingleTaskGP
    from gpytorch.mlls import ExactMarginalLogLikelihood

    acq_cfg = cfg["acquisition"]
    direction = scalarized_direction(objective_cfg)

    x_train = torch.tensor(
        [normalize_numeric_point(obs["params"], params) for obs in observations], dtype=torch.double
    )
    y_raw = [float(scalarize_objectives(obs["objectives"], objective_cfg)) for obs in observations]
    y_train = torch.tensor(
        [[-value] if direction == "maximize" else [value] for value in y_raw], dtype=torch.double
    )

    model = SingleTaskGP(x_train, y_train)
    mll = ExactMarginalLogLikelihood(model.likelihood, model)
    fit_gpytorch_mll(mll)

    best = state["best"]["objective_value"] if state["best"] else None
    scored = []
    requested = int(cfg["candidate_pool_size"])
    sampled = _sample_random_candidates(
        rng,
        cfg,
        params,
        constraints,
        target_count=requested,
    )
    candidates, status = _require_feasible_candidates(
        sampled,
        constraints,
        strategy="surrogate_acquisition",
        surrogate_backend="botorch_gp",
        phase="candidate-pool",
        requested=requested,
    )
    for candidate in candidates:
        x = torch.tensor([normalize_numeric_point(candidate, params)], dtype=torch.double)
        posterior = model.posterior(x)
        mean_tensor = posterior.mean.detach().cpu().view(-1)[0].item()
        std_tensor = posterior.variance.detach().cpu().clamp_min(1e-12).sqrt().view(-1)[0].item()

        mean = -mean_tensor if direction == "maximize" else mean_tensor
        score = acq_score(mean, std_tensor, best, direction, acq_cfg)
        scored.append(
            (
                score,
                denormalize_numeric_point(normalize_numeric_point(candidate, params), params),
                mean,
                std_tensor,
            )
        )

    scored.sort(key=lambda row: row[0], reverse=True)
    score, candidate, mean, std = scored[0]
    return candidate, _decision_with_constraint_status(
        {
            "strategy": "surrogate_acquisition",
            "surrogate_backend": "botorch_gp",
            "acquisition_type": acq_cfg.get("type", "ucb"),
            "predicted_mean": mean,
            "predicted_std": std,
            "acquisition_score": score,
        },
        status,
    )


def use_botorch_backend(args: argparse.Namespace, cfg: dict) -> bool:
    flags = cfg.get("feature_flags", {})
    return bool(flags.get("enable_botorch_gp", False) or args.enable_botorch_gp)


def propose(
    rng: random.Random,
    state: dict,
    cfg: dict,
    params: list[dict],
    obj_cfg: dict,
    args: argparse.Namespace,
    constraints: dict | None = None,
) -> tuple[dict, dict]:
    observations = state["observations"]
    if len(observations) < int(cfg["initial_random_trials"]):
        sampled = _sample_random_candidates(rng, cfg, params, constraints, target_count=1)
        candidates, status = _require_feasible_candidates(
            sampled,
            constraints,
            strategy="initial_random",
            surrogate_backend=None,
            phase="initial-random",
            requested=1,
        )
        return candidates[0], _decision_with_constraint_status(
            {
                "strategy": "initial_random",
                "surrogate_backend": None,
            },
            status,
        )
    usable_obs = [row for row in observations if _is_usable_observation(row, obj_cfg)]
    if not usable_obs:
        sampled = _sample_random_candidates(rng, cfg, params, constraints, target_count=1)
        candidates, status = _require_feasible_candidates(
            sampled,
            constraints,
            strategy="initial_random",
            surrogate_backend=None,
            phase="fallback-random",
            requested=1,
            fallback_reason="no_usable_observations",
        )
        return candidates[0], _decision_with_constraint_status(
            {
                "strategy": "initial_random",
                "surrogate_backend": None,
                "fallback_reason": "no_usable_observations",
            },
            status,
        )

    if use_botorch_backend(args, cfg):
        surrogate_cfg = cfg.get("surrogate", {})
        min_botorch_fit_observations = max(
            2, int(surrogate_cfg.get("botorch_min_fit_observations", 2))
        )
        if len(usable_obs) < min_botorch_fit_observations:
            sampled = _sample_random_candidates(rng, cfg, params, constraints, target_count=1)
            fallback_reason = (
                "insufficient_usable_observations_for_botorch_gp"
                f"({len(usable_obs)}/{min_botorch_fit_observations})"
            )
            candidates, status = _require_feasible_candidates(
                sampled,
                constraints,
                strategy="initial_random",
                surrogate_backend=None,
                phase="fallback-random",
                requested=1,
                fallback_reason=fallback_reason,
            )
            return candidates[0], _decision_with_constraint_status(
                {
                    "strategy": "initial_random",
                    "surrogate_backend": None,
                    "fallback_reason": fallback_reason,
                },
                status,
            )
        try:
            return propose_with_botorch(rng, usable_obs, state, cfg, params, obj_cfg, constraints)
        except ConstraintSamplingFailure:
            raise
        except Exception as exc:
            flags = cfg.get("feature_flags", {})
            if flags.get("fallback_to_proxy_if_unavailable", True):
                candidate, decision = propose_with_proxy(
                    rng, usable_obs, state, cfg, params, obj_cfg, constraints
                )
                decision["fallback_reason"] = str(exc)
                return candidate, decision
            raise
    return propose_with_proxy(rng, usable_obs, state, cfg, params, obj_cfg, constraints)


def _emit_constraint_warning(decision: dict) -> None:
    status = decision.get("constraint_status")
    if not isinstance(status, dict):
        return
    warning = status.get("warning")
    if isinstance(warning, str) and warning:
        print(f"WARNING: {warning}", file=sys.stderr)


def _resolve_effective_suggest_count(cfg: dict, args: argparse.Namespace) -> int:
    raw = args.count if args.count is not None else cfg.get("batch_size", 1)
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ValueError("suggest count must be an integer > 0")
    count = int(raw)
    if count <= 0:
        raise ValueError("suggest count must be >= 1")
    return count


def _build_suggestion_bundle(suggestions: list[dict]) -> dict:
    if not suggestions:
        raise ValueError("suggestion bundle requires at least one suggestion")
    return {
        "schema_version": suggestions[0]["schema_version"],
        "count": len(suggestions),
        "suggestions": suggestions,
    }


def _emit_suggest_output(
    suggestions: list[dict], objective: dict, args: argparse.Namespace
) -> None:
    if args.jsonl:
        for suggestion in suggestions:
            print(json.dumps(suggestion, sort_keys=True))
        return

    payload = suggestions[0] if len(suggestions) == 1 else _build_suggestion_bundle(suggestions)
    print(json.dumps(payload, indent=2))
    if not args.json_only:
        print(f"Objective direction: {objective['direction']} ({objective['name']})")


def update_best(state: dict, objective_cfg: dict) -> None:
    ok = [r for r in state["observations"] if str(r.get("status", "ok")) == "ok"]
    if not ok:
        state["best"] = None
        return
    row = min(
        ok,
        key=lambda r: best_rank_key(
            r.get("objectives", {}), objective_cfg, trial_id=int(r["trial_id"])
        ),
    )
    state["best"] = build_best_record(row, objective_cfg, updated_at=time.time())


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


def _confirm_reset(args: argparse.Namespace, *, root: Path, archive_enabled: bool) -> None:
    if args.yes:
        return
    if not sys.stdin.isatty():
        raise ValueError("reset is destructive; re-run with --yes for non-interactive use")

    archive_label = "enabled" if archive_enabled else "disabled"
    print(f"Reset will remove runtime artifacts under {root} (archive={archive_label}).")
    print("Type RESET to continue: ", end="", flush=True)
    token = sys.stdin.readline().strip()
    if token != "RESET":
        raise ValueError("reset aborted: confirmation token mismatch")


def _confirm_restore(args: argparse.Namespace, *, root: Path, archive_id: str) -> None:
    if args.yes:
        return
    if not sys.stdin.isatty():
        raise ValueError("restore is destructive; re-run with --yes for non-interactive use")

    print(f"Restore will overwrite runtime artifacts under {root} from archive {archive_id}.")
    print("Type RESTORE to continue: ", end="", flush=True)
    token = sys.stdin.readline().strip()
    if token != "RESTORE":
        raise ValueError("restore aborted: confirmation token mismatch")


def _confirm_prune(args: argparse.Namespace, *, root: Path) -> None:
    if args.yes:
        return
    if not sys.stdin.isatty():
        raise ValueError("prune-archives is destructive; re-run with --yes for non-interactive use")

    print(
        f"Prune will permanently delete reset archives under {root / 'state' / 'reset_archives'}."
    )
    print("Type PRUNE to continue: ", end="", flush=True)
    token = sys.stdin.readline().strip()
    if token != "PRUNE":
        raise ValueError("prune-archives aborted: confirmation token mismatch")


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
    paths: dict[str, Path], pending_entry: dict, *, objective_cfg: dict, now: float
) -> None:
    trial_id = int(pending_entry["trial_id"])
    manifest = load_trial_manifest(paths["trials_dir"], trial_id)
    objective_meta = build_objective_metadata(None, objective_cfg)
    manifest.setdefault("created_at", now)
    manifest["trial_id"] = trial_id
    manifest["status"] = "pending"
    manifest["terminal_reason"] = None
    manifest["params"] = pending_entry["params"]
    manifest["objective_name"] = objective_meta["objective_name"]
    manifest["objective_value"] = objective_meta["objective_value"]
    manifest["objective_vector"] = objective_meta["objective_vector"]
    manifest["scalarized_objective"] = objective_meta["scalarized_objective"]
    if "scalarization_policy" in objective_meta:
        manifest["scalarization_policy"] = objective_meta["scalarization_policy"]
    else:
        manifest.pop("scalarization_policy", None)
    manifest["penalty_objective"] = None
    manifest["suggested_at"] = float(pending_entry.get("suggested_at", now))
    manifest["completed_at"] = None
    manifest["last_heartbeat_at"] = pending_entry.get("last_heartbeat_at")
    manifest["heartbeat_count"] = int(pending_entry.get("heartbeat_count", 0) or 0)
    if "heartbeat_note" in pending_entry:
        manifest["heartbeat_note"] = pending_entry["heartbeat_note"]
    if "heartbeat_meta" in pending_entry:
        manifest["heartbeat_meta"] = pending_entry["heartbeat_meta"]
    manifest["lease_token"] = pending_entry.get("lease_token")
    manifest["artifact_path"] = None
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
    objective_cfg: dict,
    payload_copy_path: Path | None,
    now: float,
) -> None:
    trial_id = int(observation["trial_id"])
    manifest = load_trial_manifest(paths["trials_dir"], trial_id)
    objective_meta = build_objective_metadata(observation.get("objectives"), objective_cfg)
    manifest.setdefault("created_at", now)
    manifest["trial_id"] = trial_id
    manifest["status"] = observation["status"]
    manifest["terminal_reason"] = observation.get("terminal_reason")
    manifest["params"] = observation["params"]
    manifest["objective_name"] = objective_meta["objective_name"]
    manifest["objective_value"] = objective_meta["objective_value"]
    manifest["objective_vector"] = objective_meta["objective_vector"]
    manifest["scalarized_objective"] = objective_meta["scalarized_objective"]
    if "scalarization_policy" in objective_meta:
        manifest["scalarization_policy"] = objective_meta["scalarization_policy"]
    else:
        manifest.pop("scalarization_policy", None)
    manifest["penalty_objective"] = observation.get("penalty_objective")
    manifest["suggested_at"] = observation.get("suggested_at", manifest.get("suggested_at"))
    manifest["completed_at"] = observation.get("completed_at")
    manifest["last_heartbeat_at"] = observation.get("last_heartbeat_at")
    manifest["heartbeat_count"] = int(observation.get("heartbeat_count", 0) or 0)
    if "heartbeat_note" in observation:
        manifest["heartbeat_note"] = observation["heartbeat_note"]
    if "heartbeat_meta" in observation:
        manifest["heartbeat_meta"] = observation["heartbeat_meta"]
    manifest["lease_token"] = observation.get("lease_token")

    artifact_path = observation.get("artifact_path")
    if artifact_path is not None and not isinstance(artifact_path, str):
        artifact_path = None

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
    if payload_copy_path is not None:
        artifact_path = _relative_path(root, payload_copy_path)
        artifacts["ingest_payload"] = artifact_path
    manifest["artifact_path"] = artifact_path
    manifest["artifacts"] = artifacts
    manifest["updated_at"] = now
    save_trial_manifest(paths["trials_dir"], trial_id, manifest)


def _annotate_import_manifest(
    paths: dict[str, Path],
    *,
    trial_id: int,
    import_source: str,
    row_format: str,
    imported_at: float,
    source_trial_id: int | str | None,
) -> None:
    manifest = load_trial_manifest(paths["trials_dir"], trial_id)
    manifest["import_source"] = import_source
    manifest["import_format"] = row_format
    manifest["imported_at"] = imported_at
    if source_trial_id is not None:
        manifest["source_trial_id"] = source_trial_id
    else:
        manifest.pop("source_trial_id", None)
    manifest["updated_at"] = imported_at
    save_trial_manifest(paths["trials_dir"], trial_id, manifest)


def _import_report_path(paths: dict[str, Path], *, imported_at: float) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(imported_at))
    micros = int((imported_at - math.floor(imported_at)) * 1_000_000)
    return paths["import_reports_dir"] / f"import-{stamp}-{micros:06d}-{os.getpid()}.json"


def _observation_rows(state: dict) -> list[dict]:
    rows = []
    for obs in state["observations"]:
        row = {
            "trial_id": obs["trial_id"],
            "status": obs["status"],
            "completed_at": obs["completed_at"],
        }
        if "source_trial_id" in obs:
            row["source_trial_id"] = obs["source_trial_id"]
        row.update({f"param_{k}": v for k, v in obs["params"].items()})
        row.update({f"objective_{k}": v for k, v in obs["objectives"].items()})
        if "penalty_objective" in obs:
            row["penalty_objective"] = obs["penalty_objective"]
        if "terminal_reason" in obs:
            row["terminal_reason"] = obs["terminal_reason"]
        if "last_heartbeat_at" in obs:
            row["last_heartbeat_at"] = obs["last_heartbeat_at"]
        if "artifact_path" in obs:
            row["artifact_path"] = obs["artifact_path"]
        if "lease_token" in obs:
            row["lease_token"] = obs["lease_token"]
        rows.append(row)
    return rows


def _save_state_and_rows(paths: dict[str, Path], state: dict) -> None:
    save_state(paths["state_file"], state)
    write_obs_csv(paths["observations_csv"], _observation_rows(state))


def _new_terminal_observation(
    pending: dict,
    *,
    objective_cfg: dict,
    terminal_reason: str,
    now: float,
) -> dict:
    observation = {
        "trial_id": int(pending["trial_id"]),
        "params": pending["params"],
        "objectives": {name: None for name in objective_names(objective_cfg)},
        "status": "killed",
        "terminal_reason": terminal_reason,
        "penalty_objective": None,
        "artifact_path": None,
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
    if "lease_token" in pending:
        observation["lease_token"] = pending["lease_token"]
    return observation


def _retire_stale_pending(
    state: dict,
    *,
    objective_cfg: dict,
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
            objective_cfg=objective_cfg,
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
    root: Path,
    state: dict,
    paths: dict[str, Path],
    max_pending_age: float | None,
    *,
    botorch_feature_flag: bool | None = None,
    worker_leases_enabled: bool,
) -> dict:
    now = time.time()
    stale_pending = 0
    leased_pending = 0
    if max_pending_age is not None:
        stale_pending = sum(
            1
            for pending in state["pending"]
            if pending_age_seconds(pending, now=now) > max_pending_age
        )
    leased_pending = sum(
        1
        for pending in state["pending"]
        if isinstance(pending.get("lease_token"), str) and bool(pending.get("lease_token"))
    )

    payload = {
        "schema_version": state_schema_version(state),
        "observations": len(state["observations"]),
        "pending": len(state["pending"]),
        "leased_pending": leased_pending,
        "next_trial_id": state["next_trial_id"],
        "best": state["best"],
        "stale_pending": stale_pending,
        "observations_by_status": _status_counts(state["observations"]),
        "max_pending_age_seconds": max_pending_age,
        "worker_leases_enabled": worker_leases_enabled,
        "paths": {
            "state_file": _relative_path(root, paths["state_file"]),
            "observations_csv": _relative_path(root, paths["observations_csv"]),
            "acquisition_log_file": _relative_path(root, paths["acquisition_log_file"]),
            "event_log_file": _relative_path(root, paths["event_log_file"]),
            "trials_dir": _relative_path(root, paths["trials_dir"]),
            "lock_file": _relative_path(root, paths["lock_file"]),
        },
    }
    if botorch_feature_flag is not None:
        payload["botorch_feature_flag"] = bool(botorch_feature_flag)
    return payload


def _best_params_from_state(state: dict) -> dict | None:
    best = state.get("best")
    if not isinstance(best, dict):
        return None
    best_trial_id = int(best.get("trial_id", -1))
    for observation in state.get("observations", []):
        if int(observation.get("trial_id", -1)) == best_trial_id:
            params = observation.get("params")
            return params if isinstance(params, dict) else None
    return None


def _runtime_summary(observations: list[dict]) -> dict | None:
    runtimes = [
        float(observation["runtime_seconds"])
        for observation in observations
        if isinstance(observation.get("runtime_seconds"), (int, float))
        and not isinstance(observation.get("runtime_seconds"), bool)
        and math.isfinite(float(observation["runtime_seconds"]))
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


def _build_observation_report_row(
    observation: dict,
    objective_cfg: dict,
    *,
    include_params: bool,
) -> dict:
    objective_meta = build_objective_metadata(observation.get("objectives"), objective_cfg)
    row = {
        "trial_id": int(observation["trial_id"]),
        "status": observation.get("status"),
        "objective_name": objective_meta["objective_name"],
        "objective_value": objective_meta["objective_value"],
        "objective_vector": objective_meta["objective_vector"],
        "scalarized_objective": objective_meta["scalarized_objective"],
        "penalty_objective": observation.get("penalty_objective"),
        "suggested_at": observation.get("suggested_at"),
        "completed_at": observation.get("completed_at"),
        "artifact_path": observation.get("artifact_path"),
        "terminal_reason": observation.get("terminal_reason"),
    }
    if "scalarization_policy" in objective_meta:
        row["scalarization_policy"] = objective_meta["scalarization_policy"]
    if include_params:
        row["params"] = observation.get("params")
    return row


def _build_report_payload(
    *,
    state: dict,
    objective_cfg: dict,
    top_n: int,
) -> dict:
    objective = objective_cfg["primary_objective"]
    objective_name = str(objective["name"])
    objective_direction = str(objective["direction"])
    observations = list(state.get("observations", []))
    status_counts = _status_counts(observations)

    ok_observations = [
        observation for observation in observations if observation.get("status") == "ok"
    ]
    ranked_ok = sorted(
        ok_observations,
        key=lambda observation: best_rank_key(
            observation["objectives"],
            objective_cfg,
            trial_id=int(observation["trial_id"]),
        ),
    )
    top_trials = [
        _build_observation_report_row(observation, objective_cfg, include_params=True)
        for observation in ranked_ok[: max(1, int(top_n))]
    ]
    terminal_trials = [
        _build_observation_report_row(observation, objective_cfg, include_params=False)
        for observation in sorted(observations, key=lambda row: int(row.get("trial_id", 0)))
        if str(observation.get("status", "")) in {"failed", "killed", "timeout"}
    ]
    objective_trace = [
        _build_observation_report_row(observation, objective_cfg, include_params=False)
        for observation in sorted(observations, key=lambda row: int(row.get("trial_id", 0)))
    ]
    pareto_records = pareto_front_records(ok_observations, objective_cfg)

    total_observations = len(observations)
    non_ok = total_observations - status_counts.get("ok", 0)
    failure_rate = (non_ok / total_observations) if total_observations else 0.0

    return {
        "schema_version": state_schema_version(state),
        "generated_at": time.time(),
        "objective": {
            "name": objective_name,
            "direction": objective_direction,
            "best_objective_name": best_objective_name(objective_cfg),
            "scalarization_policy": scalarization_policy(objective_cfg),
        },
        "objective_config": objective_config_snapshot(objective_cfg),
        "counts": {
            "observations": total_observations,
            "pending": len(state.get("pending", [])),
            "observations_by_status": status_counts,
            "failure_rate": failure_rate,
        },
        "best": state.get("best"),
        "best_params": _best_params_from_state(state),
        "top_trials": top_trials,
        "terminal_trials": terminal_trials,
        "objective_trace": objective_trace,
        "pareto_front": {
            "count": len(pareto_records),
            "trial_ids": [int(observation["trial_id"]) for observation in pareto_records],
            "trials": [
                _build_observation_report_row(observation, objective_cfg, include_params=True)
                for observation in pareto_records
            ],
        },
        "runtime_summary": _runtime_summary(observations),
    }


def _render_report_markdown(report: dict) -> str:
    objective = report["objective"]
    counts = report["counts"]
    objective_config = report["objective_config"]
    lines = [
        "# Looptimum Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Objective: `{objective['name']}` ({objective['direction']})",
        f"- Best ranking target: `{objective['best_objective_name']}`",
        f"- Scalarization policy: `{objective['scalarization_policy']}`",
        f"- Objectives: `{json.dumps(objective_config['objective_names'])}`",
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
        lines.append(f"- objective_name: `{best['objective_name']}`")
        lines.append(f"- objective_value: `{best['objective_value']}`")
        if "scalarization_policy" in best:
            lines.append(f"- scalarization_policy: `{best['scalarization_policy']}`")
        if "objective_vector" in best:
            lines.append(
                f"- objective_vector: `{json.dumps(best['objective_vector'], sort_keys=True)}`"
            )
        best_params = report.get("best_params")
        lines.append(f"- params: `{json.dumps(best_params, sort_keys=True)}`")

    lines.extend(["", "## Pareto Front", ""])
    pareto_front = report.get("pareto_front", {})
    pareto_trials = pareto_front.get("trials", [])
    lines.append(f"- count: `{pareto_front.get('count', 0)}`")
    lines.append(f"- trial_ids: `{json.dumps(pareto_front.get('trial_ids', []))}`")
    if pareto_trials:
        for row in pareto_trials:
            lines.append(
                f"- trial `{row['trial_id']}`: objective={row['objective_value']}, "
                f"scalarized={row['scalarized_objective']}, "
                f"vector={json.dumps(row['objective_vector'], sort_keys=True)}"
            )
    else:
        lines.append("No completed ok trials yet.")

    lines.extend(["", "## Top Trials", ""])
    top_trials = report.get("top_trials", [])
    if not top_trials:
        lines.append("No completed ok trials yet.")
    else:
        for row in top_trials:
            if row.get("scalarization_policy") is not None:
                lines.append(
                    f"- trial `{row['trial_id']}`: objective={row['objective_value']}, "
                    f"scalarized={row['scalarized_objective']}, status={row['status']}"
                )
            else:
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


def _validate_state_hard_checks(state: dict, objective_cfg: dict) -> list[str]:
    errors: list[str] = []
    configured_names = objective_names(objective_cfg)
    expected_best_name = best_objective_name(objective_cfg)

    required_keys = ("schema_version", "meta", "observations", "pending", "next_trial_id", "best")
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
    ok_ranked: list[tuple[int, tuple[object, ...], dict]] = []
    if isinstance(observations, list):
        for idx, observation in enumerate(observations):
            if not isinstance(observation, dict):
                errors.append(f"state.observations[{idx}] must be an object")
                continue
            if not isinstance(observation.get("trial_id"), int):
                errors.append(f"state.observations[{idx}].trial_id must be an integer")
            else:
                observation_ids.append(int(observation["trial_id"]))
            if not isinstance(observation.get("params"), dict):
                errors.append(f"state.observations[{idx}].params must be an object")
            try:
                _normalize_lease_token(
                    observation.get("lease_token"),
                    field_name=f"state.observations[{idx}].lease_token",
                )
            except ValueError as exc:
                errors.append(str(exc))
            objectives = observation.get("objectives")
            if not isinstance(objectives, dict):
                errors.append(f"state.observations[{idx}].objectives must be an object")
            else:
                status = str(observation.get("status", "ok"))
                if status not in {"ok", "failed", "killed", "timeout"}:
                    errors.append(
                        f"state.observations[{idx}].status must be one of ok|failed|killed|timeout"
                    )
                if status == "ok":
                    try:
                        canonical = canonical_objective_vector(objectives, objective_cfg)
                    except ValueError as exc:
                        errors.append(f"state.observations[{idx}].objectives invalid: {exc}")
                    else:
                        if isinstance(observation.get("trial_id"), int):
                            ok_ranked.append(
                                (
                                    int(observation["trial_id"]),
                                    best_rank_key(
                                        canonical,
                                        objective_cfg,
                                        trial_id=int(observation["trial_id"]),
                                    ),
                                    canonical,
                                )
                            )
                else:
                    for objective_name in configured_names:
                        if objectives.get(objective_name) is not None:
                            errors.append(
                                "state.observations"
                                f"[{idx}] objective '{objective_name}' must be null when status={status}"
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
            try:
                _normalize_lease_token(
                    row.get("lease_token"),
                    field_name=f"state.pending[{idx}].lease_token",
                )
            except ValueError as exc:
                errors.append(str(exc))
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

    best_trial_id_valid: int | None = None
    best_objective_value_valid: float | None = None
    best = state.get("best")
    if best is not None:
        if not isinstance(best, dict):
            errors.append("state.best must be null or an object")
        else:
            best_trial_id = best.get("trial_id")
            if not isinstance(best_trial_id, int):
                errors.append("state.best.trial_id must be an integer")
            else:
                best_trial_id_valid = int(best_trial_id)
            actual_best_name = best.get("objective_name")
            if actual_best_name != expected_best_name:
                errors.append(f"state.best.objective_name must equal '{expected_best_name}'")
            best_objective_value = best.get("objective_value")
            if (
                not isinstance(best_objective_value, (int, float))
                or isinstance(best_objective_value, bool)
                or not math.isfinite(float(best_objective_value))
            ):
                errors.append("state.best.objective_value must be a finite number")
            else:
                best_objective_value_valid = float(best_objective_value)

            matching_ok_observation: dict[str, Any] | None = None
            if isinstance(observations, list) and isinstance(best_trial_id, int):
                for observation in observations:
                    if (
                        isinstance(observation, dict)
                        and isinstance(observation.get("trial_id"), int)
                        and int(observation["trial_id"]) == best_trial_id
                        and str(observation.get("status", "")) == "ok"
                    ):
                        matching_ok_observation = observation
                        break

            if isinstance(best_trial_id, int) and matching_ok_observation is None:
                errors.append("state.best.trial_id must reference an observed ok trial")
            elif matching_ok_observation is not None:
                objectives = matching_ok_observation.get("objectives")
                try:
                    canonical = canonical_objective_vector(objectives, objective_cfg)
                except ValueError as exc:
                    errors.append(
                        f"state.best references an observation with invalid objectives: {exc}"
                    )
                else:
                    expected_scalar = float(scalarize_objectives(canonical, objective_cfg))
                    if (
                        isinstance(best_objective_value, (int, float))
                        and not isinstance(best_objective_value, bool)
                        and abs(expected_scalar - float(best_objective_value)) > 1e-12
                    ):
                        errors.append(
                            "state.best.objective_value must match the scalarized objective of the referenced observation"
                        )
                    best_vector = best.get("objective_vector")
                    if best_vector is not None and best_vector != canonical:
                        errors.append(
                            "state.best.objective_vector must match the referenced observation objectives"
                        )
                    if len(configured_names) > 1 and not isinstance(best_vector, dict):
                        errors.append(
                            "state.best.objective_vector must be present for multi-objective campaigns"
                        )

    if ok_ranked:
        expected_trial_id, _, expected_vector = min(ok_ranked, key=lambda item: item[1])
        expected_objective_value = float(scalarize_objectives(expected_vector, objective_cfg))
        if best is None:
            errors.append("state.best must be set when at least one ok observation exists")
        elif best_trial_id_valid is not None and best_trial_id_valid != expected_trial_id:
            errors.append(
                "state.best.trial_id must reference the optimal ok trial for the configured scalarization policy"
            )
        elif (
            best_objective_value_valid is not None
            and abs(best_objective_value_valid - expected_objective_value) > 1e-12
        ):
            errors.append(
                "state.best.objective_value must match the optimal scalarized objective value"
            )

    return errors


def _validate_state_warnings(
    *,
    state: dict,
    paths: dict[str, Path],
    max_pending_age: float | None,
    max_pending_trials: int | None,
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
    if (
        isinstance(pending, list)
        and max_pending_trials is not None
        and len(pending) > max_pending_trials
    ):
        warnings_out.append(
            f"{len(pending)} pending trial(s) exceed max_pending_trials={max_pending_trials}"
        )

    for key in ("acquisition_log_file", "event_log_file", "observations_csv", "trials_dir"):
        if not paths[key].exists():
            warnings_out.append(f"optional path missing: {paths[key]}")

    return warnings_out


def _validate_jsonl_file_hard(path: Path, *, label: str) -> list[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        return [f"{label} unreadable: {exc}"]

    errors: list[str] = []
    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception as exc:
            errors.append(f"{label} line {idx} invalid JSON: {exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"{label} line {idx} must be a JSON object")
    return errors


def _validate_trial_manifests_hard(trials_dir: Path, objective_cfg: dict) -> list[str]:
    if not trials_dir.exists():
        return []
    if not trials_dir.is_dir():
        return [f"trials_dir is not a directory: {trials_dir}"]

    errors: list[str] = []
    for child in sorted(trials_dir.iterdir()):
        if not child.is_dir() or not child.name.startswith("trial_"):
            continue
        suffix = child.name[len("trial_") :]
        try:
            expected_trial_id = int(suffix)
        except ValueError:
            errors.append(f"invalid trial directory name (expected trial_<id>): {child}")
            continue

        manifest_path = child / "manifest.json"
        if not manifest_path.exists():
            errors.append(f"missing manifest for trial directory: {child}")
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid manifest JSON at {manifest_path}: {exc}")
            continue
        if not isinstance(manifest, dict):
            errors.append(f"manifest must be a JSON object: {manifest_path}")
            continue

        manifest_trial_id = manifest.get("trial_id")
        if not isinstance(manifest_trial_id, int):
            errors.append(f"manifest trial_id must be an integer: {manifest_path}")
        elif int(manifest_trial_id) != expected_trial_id:
            errors.append(
                "manifest trial_id does not match trial directory name: "
                f"{manifest_path} (trial_id={manifest_trial_id}, expected={expected_trial_id})"
            )

        status = manifest.get("status")
        if status is not None and status not in {"pending", "ok", "failed", "killed", "timeout"}:
            errors.append(f"manifest status is invalid: {manifest_path} (status={status!r})")

        for key in ("status", "terminal_reason", "suggested_at", "artifact_path"):
            if key not in manifest:
                errors.append(f"manifest missing required field '{key}': {manifest_path}")

        suggested_at = manifest.get("suggested_at")
        if suggested_at is not None and (
            not isinstance(suggested_at, (int, float))
            or isinstance(suggested_at, bool)
            or not math.isfinite(float(suggested_at))
        ):
            errors.append(
                f"manifest suggested_at must be finite number or null: {manifest_path} "
                f"(suggested_at={suggested_at!r})"
            )

        artifact_path = manifest.get("artifact_path")
        if artifact_path is not None and not isinstance(artifact_path, str):
            errors.append(
                f"manifest artifact_path must be string or null: {manifest_path} "
                f"(artifact_path={artifact_path!r})"
            )
        try:
            _normalize_lease_token(
                manifest.get("lease_token"),
                field_name=f"manifest lease_token at {manifest_path}",
            )
        except ValueError as exc:
            errors.append(str(exc))

        if status in {"ok", "failed", "killed", "timeout"}:
            if "completed_at" not in manifest:
                errors.append(f"manifest missing required field 'completed_at': {manifest_path}")
            completed_at = manifest.get("completed_at")
            if not isinstance(completed_at, (int, float)) or isinstance(completed_at, bool):
                errors.append(
                    f"manifest completed_at must be finite number for terminal status: "
                    f"{manifest_path} (completed_at={completed_at!r})"
                )
            elif not math.isfinite(float(completed_at)):
                errors.append(
                    f"manifest completed_at must be finite number for terminal status: "
                    f"{manifest_path} (completed_at={completed_at!r})"
                )

        if status in {"failed", "killed", "timeout"} and "penalty_objective" not in manifest:
            errors.append(f"manifest missing required field 'penalty_objective': {manifest_path}")

        objective_vector = manifest.get("objective_vector")
        if objective_vector is not None:
            try:
                build_objective_metadata(objective_vector, objective_cfg)
            except ValueError as exc:
                errors.append(f"manifest objective_vector invalid: {manifest_path} ({exc})")

    return errors


def _parse_heartbeat_meta(raw: str | None) -> dict | None:
    if raw is None:
        return None
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("--heartbeat-meta-json must parse to an object")
    return parsed


def _normalize_lease_token(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string when present")
    return value.strip()


def _parse_cli_lease_token(raw: str | None) -> str | None:
    return _normalize_lease_token(raw, field_name="--lease-token")


def _build_lease_token() -> str:
    return secrets.token_hex(16)


def _require_matching_lease_token(
    pending_entry: dict,
    *,
    provided_token: str | None,
    trial_id: int,
    command: str,
) -> None:
    expected = _normalize_lease_token(
        pending_entry.get("lease_token"),
        field_name=f"trial_id {trial_id} lease_token",
    )
    if expected is None:
        return
    if provided_token is None:
        raise ValueError(f"trial_id {trial_id} requires --lease-token for {command}")
    if provided_token != expected:
        raise ValueError(f"trial_id {trial_id} lease token mismatch for {command}")


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
    params = normalize_search_space(space_cfg)
    constraints = _load_constraints(root, cfg, params)

    obj_cfg = _load_objective_config(root, cfg)
    objective = obj_cfg["primary_objective"]
    paths = _runtime_paths(root, cfg)
    lock_timeout = resolve_lock_timeout_seconds(cfg, args.lock_timeout_seconds)
    max_pending_age = resolve_max_pending_age_seconds(cfg)
    max_pending_trials = resolve_max_pending_trials(cfg)
    worker_leases_enabled = resolve_worker_leases_enabled(cfg)
    requested_count = _resolve_effective_suggest_count(cfg, args)

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
                    objective_cfg=obj_cfg,
                    max_pending_age_seconds=max_pending_age,
                    now=now,
                    reason="retired_stale_auto",
                )
                for obs in stale_observations:
                    _ensure_terminal_manifest(
                        root,
                        paths,
                        obs,
                        objective_cfg=obj_cfg,
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

            current_pending = len(state["pending"])
            if (
                max_pending_trials is not None
                and current_pending + requested_count > max_pending_trials
            ):
                if stale_observations:
                    update_best(state, obj_cfg)
                    _save_state_and_rows(paths, state)
                elif state_schema_upgrade_pending(state):
                    save_state(paths["state_file"], state)
                print(
                    "No suggestion generated: "
                    f"max_pending_trials={max_pending_trials} would be exceeded "
                    f"(current_pending={current_pending}, requested_count={requested_count})."
                )
                return

            if len(state["observations"]) + current_pending + requested_count > int(
                cfg["max_trials"]
            ):
                if stale_observations:
                    update_best(state, obj_cfg)
                    _save_state_and_rows(paths, state)
                elif state_schema_upgrade_pending(state):
                    save_state(paths["state_file"], state)
                print("No suggestion generated: budget exhausted.")
                return

            suggestion_schema, _ = load_schema_from_paths(
                root,
                cfg["paths"],
                key="suggestion_schema_file",
                default_rel="../_shared/schemas/suggestion_payload.schema.json",
            )

            planning_state = copy.deepcopy(state)
            planned_suggestions: list[dict] = []
            planned_decisions: list[tuple[int, dict]] = []
            try:
                for _ in range(requested_count):
                    seed = int(planning_state["meta"]["seed"]) + int(
                        planning_state["next_trial_id"]
                    )
                    rng = random.Random(seed)
                    trial_id = int(planning_state["next_trial_id"])
                    cand, decision = propose(
                        rng,
                        planning_state,
                        cfg,
                        params,
                        obj_cfg,
                        args,
                        constraints,
                    )
                    suggestion = {
                        "schema_version": state_schema_version(planning_state),
                        "trial_id": trial_id,
                        "params": cand,
                        "suggested_at": time.time(),
                    }
                    if worker_leases_enabled:
                        suggestion["lease_token"] = _build_lease_token()
                    validate_against_schema(
                        suggestion,
                        suggestion_schema,
                        source_path=Path("<generated_suggestion>"),
                        trial_id=trial_id,
                    )
                    planning_state["pending"].append(suggestion)
                    planning_state["next_trial_id"] = trial_id + 1
                    planned_suggestions.append(suggestion)
                    planned_decisions.append((trial_id, decision))
            except ConstraintSamplingFailure as exc:
                failed_trial_id = int(planning_state["next_trial_id"])
                append_jsonl(
                    paths["acquisition_log_file"],
                    {
                        "trial_id": failed_trial_id,
                        "decision": exc.decision,
                        "timestamp": time.time(),
                    },
                )
                save_state(paths["state_file"], state)
                if stale_observations:
                    write_obs_csv(paths["observations_csv"], _observation_rows(state))
                raise

            state = planning_state
            for suggestion in planned_suggestions:
                _ensure_pending_manifest(
                    paths,
                    suggestion,
                    objective_cfg=obj_cfg,
                    now=time.time(),
                )
            for trial_id, decision in planned_decisions:
                append_jsonl(
                    paths["acquisition_log_file"],
                    {"trial_id": trial_id, "decision": decision, "timestamp": time.time()},
                )
                _emit_constraint_warning(decision)
                _append_event(paths, "suggestion_created", trial_id=trial_id)

            save_state(paths["state_file"], state)
            if stale_observations:
                write_obs_csv(paths["observations_csv"], _observation_rows(state))

            _emit_suggest_output(planned_suggestions, objective, args)
        finally:
            _append_event(paths, "lock_released", command="suggest", pid=os.getpid())


def cmd_ingest(args: argparse.Namespace) -> None:
    root = Path(args.project_root).resolve()
    cfg, _ = load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")
    space_cfg, space_path = load_contract_document(root, "parameter_space")
    if not isinstance(space_cfg, dict):
        raise ValueError(f"parameter_space must be an object: {space_path}")
    params = normalize_search_space(space_cfg)

    obj_cfg = _load_objective_config(root, cfg)
    ingest_schema, _ = load_schema_from_paths(
        root,
        cfg["paths"],
        key="ingest_schema_file",
        removed_key="result_schema_file",
        default_rel="../_shared/schemas/ingest_payload.schema.json",
    )

    paths = _runtime_paths(root, cfg)
    lock_timeout = resolve_lock_timeout_seconds(cfg, args.lock_timeout_seconds)
    lease_token = _parse_cli_lease_token(args.lease_token)

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
                objective_cfg=obj_cfg,
                source_path=payload_path,
            )
            payload["params"] = canonicalize_conditional_params(payload["params"], params)
            heartbeat_fields = _load_heartbeat_fields(payload, trial_id)

            pending = {int(row["trial_id"]): row for row in state["pending"]}
            if trial_id not in pending:
                prior = next(
                    (obs for obs in state["observations"] if int(obs["trial_id"]) == trial_id), None
                )
                if prior is None:
                    raise ValueError(f"trial_id {trial_id} is not pending")

                prior_for_compare = dict(prior)
                prior_for_compare["params"] = canonicalize_conditional_params(
                    prior.get("params", {}), params
                )
                expected = build_observation_contract(prior_for_compare, objective_cfg=obj_cfg)
                received = {
                    "trial_id": trial_id,
                    "params": payload["params"],
                    "objectives": payload["objectives"],
                    "status": payload["status"],
                }
                if "penalty_objective" in payload:
                    received["penalty_objective"] = payload["penalty_objective"]
                if "terminal_reason" in payload:
                    received["terminal_reason"] = payload["terminal_reason"]
                diffs = diff_contract_records(expected, received)
                if not diffs:
                    _append_event(paths, "ingest_duplicate_noop", trial_id=trial_id)
                    print(f"No-op: trial_id={trial_id} already ingested with identical payload.")
                    return
                raise ValueError(format_contract_diff_error(trial_id, diffs))

            _require_matching_lease_token(
                pending[trial_id],
                provided_token=lease_token,
                trial_id=trial_id,
                command="ingest",
            )
            pending_params = canonicalize_conditional_params(
                pending[trial_id].get("params", {}), params
            )
            if payload.get("params") != pending_params:
                param_diffs = diff_contract_records(
                    {"params": pending_params},
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
                "artifact_path": None,
                "suggested_at": pending_entry.get("suggested_at"),
                "completed_at": now,
            }
            if payload["status"] != "ok":
                observation["terminal_reason"] = payload.get("terminal_reason")
                observation["penalty_objective"] = payload.get("penalty_objective")

            if "heartbeat_count" in pending_entry:
                observation["heartbeat_count"] = pending_entry["heartbeat_count"]
            if "last_heartbeat_at" in pending_entry:
                observation["last_heartbeat_at"] = pending_entry["last_heartbeat_at"]
            if "heartbeat_note" in pending_entry:
                observation["heartbeat_note"] = pending_entry["heartbeat_note"]
            if "heartbeat_meta" in pending_entry:
                observation["heartbeat_meta"] = pending_entry["heartbeat_meta"]
            if "lease_token" in pending_entry:
                observation["lease_token"] = pending_entry["lease_token"]

            observation.update(heartbeat_fields)
            state["observations"].append(observation)
            update_best(state, obj_cfg)

            payload_copy_path = trial_dir(paths["trials_dir"], trial_id) / "ingest_payload.json"
            atomic_write_json(payload_copy_path, payload, indent=2)
            observation["artifact_path"] = _relative_path(root, payload_copy_path)
            _ensure_terminal_manifest(
                root,
                paths,
                observation,
                objective_cfg=obj_cfg,
                payload_copy_path=payload_copy_path,
                now=now,
            )

            _save_state_and_rows(paths, state)
            _append_event(paths, "ingest_applied", trial_id=trial_id, status=observation["status"])
            print(f"Ingested trial_id={trial_id}. Observations={len(state['observations'])}")
        finally:
            _append_event(paths, "lock_released", command="ingest", pid=os.getpid())


def cmd_import_observations(args: argparse.Namespace) -> None:
    if not args.input_file:
        raise ValueError("import-observations requires --input-file")

    root = Path(args.project_root).resolve()
    cfg, _ = load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")
    space_cfg, space_path = load_contract_document(root, "parameter_space")
    if not isinstance(space_cfg, dict):
        raise ValueError(f"parameter_space must be an object: {space_path}")
    params = normalize_search_space(space_cfg)
    obj_cfg = _load_objective_config(root, cfg)

    input_path = Path(args.input_file).resolve()
    row_format = args.format or infer_observation_format(input_path)
    import_mode = str(args.import_mode or "strict").strip().lower()
    raw_rows = load_observation_rows(input_path, row_format)
    if not raw_rows:
        raise ValueError(f"No observation rows found in {input_path}")
    if import_mode not in {"strict", "permissive"}:
        raise ValueError("import-observations requires --import-mode strict|permissive")

    paths = _runtime_paths(root, cfg)
    lock_timeout = resolve_lock_timeout_seconds(cfg, args.lock_timeout_seconds)

    with hold_exclusive_lock(
        paths["lock_file"], timeout_seconds=lock_timeout, fail_fast=args.fail_fast
    ) as lock:
        _append_event(
            paths,
            "lock_acquired",
            command="import-observations",
            pid=os.getpid(),
            wait_seconds=lock.wait_seconds,
        )
        try:
            state = load_state(paths["state_file"])
            imported_at = time.time()
            import_source = _relative_path(root, input_path)
            import_report_rel: str | None = None
            reject_report_rel: str | None = None
            rejected_rows: list[dict] = []

            if import_mode == "strict":
                planned_trial_ids = plan_import_trial_ids(state, len(raw_rows))
                normalized_rows = [
                    normalize_import_record(
                        raw_row,
                        row_format=row_format,
                        params=params,
                        objective_cfg=obj_cfg,
                        local_trial_id=planned_trial_ids[index],
                        imported_at=imported_at,
                    )
                    for index, raw_row in enumerate(raw_rows)
                ]
                next_trial_id_after_import = planned_trial_ids[-1] + 1
            else:
                start_trial_id = next_import_trial_id(state)
                permissive_result = normalize_import_records_permissive(
                    raw_rows,
                    row_format=row_format,
                    params=params,
                    objective_cfg=obj_cfg,
                    next_trial_id=start_trial_id,
                    imported_at=imported_at,
                )
                normalized_rows = permissive_result["accepted"]
                rejected_rows = permissive_result["rejected"]
                next_trial_id_after_import = int(permissive_result["next_trial_id"])
                report_path = _import_report_path(paths, imported_at=imported_at)
                report_payload = {
                    "mode": import_mode,
                    "import_source": import_source,
                    "row_format": row_format,
                    "imported_at": imported_at,
                    "requested_count": len(raw_rows),
                    "accepted_count": len(normalized_rows),
                    "rejected_count": len(rejected_rows),
                    "accepted_trial_ids": [
                        int(record["observation"]["trial_id"]) for record in normalized_rows
                    ],
                    "rejected_rows": rejected_rows,
                }
                atomic_write_json(report_path, report_payload, indent=2)
                import_report_rel = _relative_path(root, report_path)
                if rejected_rows:
                    reject_report_rel = import_report_rel

            imported_observations = [record["observation"] for record in normalized_rows]
            if not imported_observations:
                event_fields: dict[str, Any] = {
                    "import_source": import_source,
                    "imported_at": imported_at,
                    "row_format": row_format,
                    "import_mode": import_mode,
                    "requested_count": len(raw_rows),
                    "accepted_count": 0,
                    "rejected_count": len(rejected_rows),
                }
                if import_report_rel is not None:
                    event_fields["import_report_path"] = import_report_rel
                if reject_report_rel is not None:
                    event_fields["reject_report_path"] = reject_report_rel
                _append_event(paths, "observations_imported", **event_fields)
                detail = f" Reject report: {reject_report_rel}" if reject_report_rel else ""
                raise ValueError(
                    f"No observations imported from {import_source}; all {len(raw_rows)} row(s) were rejected.{detail}"
                )

            for observation, record in zip(imported_observations, normalized_rows, strict=True):
                source_trial_id = record.get("source_trial_id")
                if source_trial_id is not None:
                    observation["source_trial_id"] = source_trial_id
                state["observations"].append(observation)
                _ensure_terminal_manifest(
                    root,
                    paths,
                    observation,
                    objective_cfg=obj_cfg,
                    payload_copy_path=None,
                    now=imported_at,
                )
                _annotate_import_manifest(
                    paths,
                    trial_id=int(observation["trial_id"]),
                    import_source=import_source,
                    row_format=row_format,
                    imported_at=imported_at,
                    source_trial_id=source_trial_id,
                )

            state["next_trial_id"] = next_trial_id_after_import
            update_best(state, obj_cfg)
            _save_state_and_rows(paths, state)
            event_fields = {
                "import_source": import_source,
                "imported_at": imported_at,
                "row_format": row_format,
                "import_mode": import_mode,
                "requested_count": len(raw_rows),
                "accepted_count": len(imported_observations),
                "rejected_count": len(rejected_rows),
            }
            if import_report_rel is not None:
                event_fields["import_report_path"] = import_report_rel
            if reject_report_rel is not None:
                event_fields["reject_report_path"] = reject_report_rel
            _append_event(paths, "observations_imported", **event_fields)
            print(f"Imported {len(imported_observations)} observation(s) from {import_source}.")
            if import_mode == "strict":
                print(
                    f"Format: {row_format}. Observations={len(state['observations'])} "
                    f"Next trial id={state['next_trial_id']}"
                )
            else:
                print(
                    f"Format: {row_format}. Mode: {import_mode}. Observations={len(state['observations'])} "
                    f"Next trial id={state['next_trial_id']}. Rejected rows={len(rejected_rows)}"
                )
                if import_report_rel is not None:
                    print(f"Import report: {import_report_rel}")
        finally:
            _append_event(paths, "lock_released", command="import-observations", pid=os.getpid())


def cmd_export_observations(args: argparse.Namespace) -> None:
    if not args.output_file:
        raise ValueError("export-observations requires --output-file")

    root = Path(args.project_root).resolve()
    cfg, _ = load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")

    output_path = Path(args.output_file).resolve()
    row_format = args.format or infer_observation_format(output_path)
    paths = _runtime_paths(root, cfg)
    lock_timeout = resolve_lock_timeout_seconds(cfg, args.lock_timeout_seconds)

    with hold_exclusive_lock(
        paths["lock_file"], timeout_seconds=lock_timeout, fail_fast=args.fail_fast
    ) as lock:
        _append_event(
            paths,
            "lock_acquired",
            command="export-observations",
            pid=os.getpid(),
            wait_seconds=lock.wait_seconds,
        )
        try:
            state = load_state(paths["state_file"])
            observations = state.get("observations", [])
            if not isinstance(observations, list):
                raise ValueError("state.observations must be a list")
            exported_at = time.time()
            export_path = _relative_path(root, output_path)
            if row_format == "jsonl":
                payload = render_observations_jsonl(observations)
            else:
                payload = render_observations_csv(observations)
            atomic_write_text(output_path, payload)
            _append_event(
                paths,
                "observations_exported",
                export_path=export_path,
                exported_at=exported_at,
                row_format=row_format,
                exported_count=len(observations),
            )
            print(f"Exported {len(observations)} observation(s) to {export_path}.")
            print(f"Format: {row_format}.")
        finally:
            _append_event(paths, "lock_released", command="export-observations", pid=os.getpid())


def cmd_cancel(args: argparse.Namespace) -> None:
    if args.trial_id is None:
        raise ValueError("cancel requires --trial-id")

    root = Path(args.project_root).resolve()
    cfg, _ = load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")
    obj_cfg = _load_objective_config(root, cfg)
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
                objective_cfg=obj_cfg,
                terminal_reason=terminal_reason,
                now=now,
            )
            state["observations"].append(observation)
            update_best(state, obj_cfg)
            _ensure_terminal_manifest(
                root,
                paths,
                observation,
                objective_cfg=obj_cfg,
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
    obj_cfg = _load_objective_config(root, cfg)
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
                    objective_cfg=obj_cfg,
                    terminal_reason=terminal_reason,
                    now=now,
                )
                state["observations"].append(observation)
                retired.append(observation)

            if not retired:
                print("No pending trials retired.")
                return

            update_best(state, obj_cfg)
            for observation in retired:
                _ensure_terminal_manifest(
                    root,
                    paths,
                    observation,
                    objective_cfg=obj_cfg,
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
    obj_cfg = _load_objective_config(root, cfg)
    paths = _runtime_paths(root, cfg)
    lock_timeout = resolve_lock_timeout_seconds(cfg, args.lock_timeout_seconds)
    lease_token = _parse_cli_lease_token(args.lease_token)

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
            _require_matching_lease_token(
                pending_entry,
                provided_token=lease_token,
                trial_id=int(args.trial_id),
                command="heartbeat",
            )
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
                objective_cfg=obj_cfg,
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
    print(
        json.dumps(
            _status_payload(
                root,
                state,
                paths,
                max_pending_age,
                botorch_feature_flag=use_botorch_backend(args, cfg),
                worker_leases_enabled=resolve_worker_leases_enabled(cfg),
            ),
            indent=2,
        )
    )


def cmd_report(args: argparse.Namespace) -> None:
    root = Path(args.project_root).resolve()
    cfg, _ = load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")
    obj_cfg = _load_objective_config(root, cfg)
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
                state=state, objective_cfg=obj_cfg, top_n=max(1, int(args.top_n))
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


def cmd_reset(args: argparse.Namespace) -> None:
    root = Path(args.project_root).resolve()
    cfg, _ = load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")

    paths = _runtime_paths(root, cfg)
    archive_enabled = True if args.archive is None else bool(args.archive)
    _confirm_reset(args, root=root, archive_enabled=archive_enabled)

    targets = reset_artifact_paths(root, paths)
    lock_timeout = resolve_lock_timeout_seconds(cfg, args.lock_timeout_seconds)

    with hold_exclusive_lock(
        paths["lock_file"], timeout_seconds=lock_timeout, fail_fast=args.fail_fast
    ) as lock:
        _append_event(
            paths,
            "lock_acquired",
            command="reset",
            pid=os.getpid(),
            wait_seconds=lock.wait_seconds,
        )
        try:
            archive_root: Path | None = None
            archived: list[tuple[str, str]] = []
            archived_sources: list[tuple[str, Path]] = []
            if archive_enabled:
                archive_stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
                archive_root = (
                    paths["state_file"].parent
                    / "reset_archives"
                    / f"reset-{archive_stamp}-{time.time_ns()}"
                ).resolve()
                archive_root.mkdir(parents=True, exist_ok=False)
                for label, path in targets:
                    if not path.exists():
                        continue
                    rel = _relative_path(root, path)
                    dst = archive_root / rel
                    copy_path_to_archive(path, dst)
                    archived.append((rel, _relative_path(root, dst)))
                    archived_sources.append((label, path))
                manifest = build_reset_archive_manifest(
                    root,
                    archive_root,
                    archived_sources,
                    created_at=time.time(),
                )
                write_archive_manifest(archive_root, manifest)

            removed: list[str] = []
            missing: list[str] = []
            for _, path in targets:
                rel = _relative_path(root, path)
                if not path.exists():
                    missing.append(rel)
                    continue
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                removed.append(rel)

            archive_rel = _relative_path(root, archive_root) if archive_root is not None else None
            _append_event(
                paths,
                "campaign_reset",
                archive_enabled=archive_enabled,
                archive_path=archive_rel,
                removed_count=len(removed),
                missing_count=len(missing),
            )

            print("Campaign reset completed.")
            if archive_enabled:
                print(f"Archive: {archive_rel}")
            else:
                print("Archive: disabled")

            if archived:
                print("Archived artifacts:")
                for src_rel, dst_rel in archived:
                    print(f"- {src_rel} -> {dst_rel}")
            elif archive_enabled:
                print("Archived artifacts:")
                print("- (none)")

            print("Removed artifacts:")
            if removed:
                for rel in removed:
                    print(f"- {rel}")
            else:
                print("- (none)")

            if missing:
                print("Already absent:")
                for rel in missing:
                    print(f"- {rel}")

            if archive_root is not None:
                print("Restore hint:")
                print(
                    f"- python3 run_bo.py restore --project-root {root} "
                    f"--archive-id {archive_root.name} --yes"
                )
        finally:
            _append_event(paths, "lock_released", command="reset", pid=os.getpid())


def cmd_list_archives(args: argparse.Namespace) -> None:
    root = Path(args.project_root).resolve()
    cfg, _ = load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")

    paths = _runtime_paths(root, cfg)
    archives = list_reset_archives(root, paths)
    archives_root_rel = _relative_path(root, reset_archives_root(paths))
    for line in render_reset_archive_listing(archives, archives_root_rel=archives_root_rel):
        print(line)


def cmd_restore(args: argparse.Namespace) -> None:
    if args.archive_id is None:
        raise ValueError("restore requires --archive-id")

    root = Path(args.project_root).resolve()
    cfg, _ = load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")

    paths = _runtime_paths(root, cfg)
    _confirm_restore(args, root=root, archive_id=args.archive_id)
    lock_timeout = resolve_lock_timeout_seconds(cfg, args.lock_timeout_seconds)

    with hold_exclusive_lock(
        paths["lock_file"], timeout_seconds=lock_timeout, fail_fast=args.fail_fast
    ) as lock:
        lock_logged = False
        try:
            restore_result = restore_reset_archive(
                args.archive_id,
                project_root=root,
                runtime_paths=paths,
            )

            _append_event(
                paths,
                "lock_acquired",
                command="restore",
                pid=os.getpid(),
                wait_seconds=lock.wait_seconds,
            )
            lock_logged = True
            _append_event(
                paths,
                "campaign_restored",
                archive_id=restore_result["archive_id"],
                archive_path=restore_result["archive_rel"],
                legacy_archive=restore_result["legacy"],
                restored_count=len(restore_result["restored_paths"]),
                overwritten_count=len(restore_result["overwritten_paths"]),
                ignored_count=len(restore_result["ignored_paths"]),
            )

            print("Campaign restore completed.")
            print(f"Archive: {restore_result['archive_rel']}")
            if restore_result["legacy"]:
                print("Archive kind: legacy")

            print("Restored artifacts:")
            for rel in restore_result["restored_paths"]:
                print(f"- {rel}")

            print("Overwritten artifacts:")
            if restore_result["overwritten_paths"]:
                for rel in restore_result["overwritten_paths"]:
                    print(f"- {rel}")
            else:
                print("- (none)")

            if restore_result["ignored_paths"]:
                print("Ignored archived artifacts:")
                for rel in restore_result["ignored_paths"]:
                    print(f"- {rel}")
        except Exception as exc:
            try:
                _append_event(
                    paths,
                    "lock_acquired",
                    command="restore",
                    pid=os.getpid(),
                    wait_seconds=lock.wait_seconds,
                )
                lock_logged = True
                _append_event(
                    paths,
                    "campaign_restore_failed",
                    archive_id=str(args.archive_id),
                    error=str(exc),
                )
            except Exception:
                pass
            raise
        finally:
            if lock_logged:
                _append_event(paths, "lock_released", command="restore", pid=os.getpid())


def cmd_prune_archives(args: argparse.Namespace) -> None:
    root = Path(args.project_root).resolve()
    cfg, _ = load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")

    paths = _runtime_paths(root, cfg)
    keep_last = args.keep_last
    older_than_seconds = args.older_than_seconds
    _confirm_prune(args, root=root)
    lock_timeout = resolve_lock_timeout_seconds(cfg, args.lock_timeout_seconds)

    with hold_exclusive_lock(
        paths["lock_file"], timeout_seconds=lock_timeout, fail_fast=args.fail_fast
    ) as lock:
        _append_event(
            paths,
            "lock_acquired",
            command="prune-archives",
            pid=os.getpid(),
            wait_seconds=lock.wait_seconds,
        )
        try:
            prune_result = prune_reset_archives(
                root,
                paths,
                keep_last=keep_last,
                older_than_seconds=older_than_seconds,
            )
            criteria = prune_result["criteria"]
            _append_event(
                paths,
                "archives_pruned",
                pruned_count=prune_result["pruned_count"],
                keep_last=criteria["keep_last"],
                older_than_seconds=criteria["older_than_seconds"],
            )

            pruned_paths = prune_result["pruned_paths"]
            kept_ids = prune_result["kept_archive_ids"]
            unknown_age_kept = prune_result["kept_due_to_unknown_age"]

            if pruned_paths:
                print(f"Pruned {len(pruned_paths)} reset archive(s).")
            else:
                print("No reset archives matched prune criteria.")

            print("Criteria:")
            print(f"- keep_last: {criteria['keep_last']}")
            print(f"- older_than_seconds: {criteria['older_than_seconds']}")

            print("Pruned archives:")
            if pruned_paths:
                for rel in pruned_paths:
                    print(f"- {rel}")
            else:
                print("- (none)")

            print("Kept archives:")
            if kept_ids:
                for archive_id in kept_ids:
                    print(f"- {archive_id}")
            else:
                print("- (none)")

            if unknown_age_kept:
                print("Kept due to unknown age:")
                for archive_id in unknown_age_kept:
                    print(f"- {archive_id}")
        finally:
            _append_event(paths, "lock_released", command="prune-archives", pid=os.getpid())


def cmd_validate(args: argparse.Namespace) -> None:
    root = Path(args.project_root).resolve()
    hard_errors: list[str] = []
    warnings_out: list[str] = []
    params: list[dict[str, Any]] | None = None
    max_pending_age: float | None = None
    max_pending_trials: int | None = None

    try:
        cfg, _ = load_contract_document(root, "bo_config")
        if not isinstance(cfg, dict):
            raise ValueError("bo_config must be an object")
    except Exception as exc:
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
        params = normalize_search_space(space_cfg)
    except Exception as exc:
        hard_errors.append(f"parameter_space validation failure: {exc}")

    if params is not None:
        try:
            _load_constraints(root, cfg, params)
        except Exception as exc:
            hard_errors.append(f"constraints validation failure: {exc}")

    obj_cfg = normalize_objective_schema(
        {
            "primary_objective": {
                "name": "loss",
                "direction": "minimize",
            }
        }
    )
    try:
        obj_cfg = _load_objective_config(root, cfg)
    except Exception as exc:
        hard_errors.append(f"objective_schema validation failure: {exc}")

    try:
        max_pending_age = resolve_max_pending_age_seconds(cfg)
    except Exception as exc:
        hard_errors.append(f"config validation failure: {exc}")

    try:
        max_pending_trials = resolve_max_pending_trials(cfg)
    except Exception as exc:
        hard_errors.append(f"config validation failure: {exc}")
    try:
        resolve_worker_leases_enabled(cfg)
    except Exception as exc:
        hard_errors.append(f"config validation failure: {exc}")

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

    hard_errors.extend(_validate_state_hard_checks(state, obj_cfg))
    hard_errors.extend(
        _validate_jsonl_file_hard(paths["acquisition_log_file"], label="acquisition_log_file")
    )
    hard_errors.extend(_validate_jsonl_file_hard(paths["event_log_file"], label="event_log_file"))
    hard_errors.extend(_validate_trial_manifests_hard(paths["trials_dir"], obj_cfg))
    warnings_out.extend(
        _validate_state_warnings(
            state=state,
            paths=paths,
            max_pending_age=max_pending_age,
            max_pending_trials=max_pending_trials,
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

    obj_cfg = _load_objective_config(root, cfg)
    objective = obj_cfg["primary_objective"]
    paths = _runtime_paths(root, cfg)
    state = load_state(paths["state_file"])
    max_pending_age = resolve_max_pending_age_seconds(cfg)
    botorch_enabled = use_botorch_backend(args, cfg)
    status = _status_payload(
        root,
        state,
        paths,
        max_pending_age,
        botorch_feature_flag=botorch_enabled,
        worker_leases_enabled=resolve_worker_leases_enabled(cfg),
    )

    backend = str(cfg.get("surrogate", {}).get("type", "rbf_proxy")).lower()
    botorch_dependency_available = None
    if botorch_enabled:
        try:
            import botorch  # noqa: F401

            botorch_dependency_available = True
        except Exception:
            botorch_dependency_available = False

    payload = {
        "schema_version": state_schema_version(state),
        "generated_at": time.time(),
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "platform": sys.platform,
        "project_root": str(root),
        "pid": os.getpid(),
        "backend": {
            "configured": backend,
            "botorch_enabled": botorch_enabled,
            "botorch_dependency_available": botorch_dependency_available,
        },
        "objective": objective,
        "status": status,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return

    print("Looptimum Doctor")
    print(f"- schema_version: {payload['schema_version']}")
    print(f"- python_version: {payload['python_version']}")
    print(f"- python_executable: {payload['python_executable']}")
    print(f"- platform: {payload['platform']}")
    print(f"- project_root: {payload['project_root']}")
    print(f"- backend.configured: {backend}")
    print(f"- backend.botorch_enabled: {botorch_enabled}")
    if botorch_dependency_available is not None:
        print(f"- backend.botorch_dependency_available: {botorch_dependency_available}")
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
        original_count = getattr(args, "count", None)
        args.count = 1
        try:
            cmd_suggest(args)
        finally:
            args.count = original_count
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
            "import-observations",
            "export-observations",
            "status",
            "demo",
            "cancel",
            "retire",
            "heartbeat",
            "report",
            "reset",
            "list-archives",
            "restore",
            "prune-archives",
            "validate",
            "doctor",
        ],
    )
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--results-file", default="examples/example_results.json")
    parser.add_argument("--input-file", help="For import-observations: CSV/JSONL input file.")
    parser.add_argument("--output-file", help="For export-observations: CSV/JSONL output file.")
    parser.add_argument(
        "--import-mode",
        choices=["strict", "permissive"],
        default="strict",
        help="For import-observations: strict or permissive row rejection handling.",
    )
    parser.add_argument(
        "--format",
        choices=["csv", "jsonl"],
        help="For import-observations/export-observations: format override.",
    )
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
        "--lease-token",
        help="For heartbeat/ingest: required when a pending trial carries a lease token.",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="For suggest: print only JSON (no trailing human-readable line).",
    )
    parser.add_argument(
        "--jsonl",
        action="store_true",
        help="For suggest: emit one JSON suggestion per line and suppress summary text.",
    )
    parser.add_argument(
        "--count",
        type=int,
        help="For suggest: number of suggestions to allocate in one locked batch.",
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
    parser.add_argument(
        "--yes",
        action="store_true",
        help="For reset/restore/prune-archives: skip interactive confirmation prompt.",
    )
    parser.add_argument("--archive-id", help="For restore: reset archive id to rehydrate.")
    parser.add_argument(
        "--keep-last",
        type=int,
        help="For prune-archives: keep the newest N reset archives and prune older ones.",
    )
    parser.add_argument(
        "--older-than-seconds",
        type=float,
        help="For prune-archives: prune archives with known age >= this threshold.",
    )
    archive_group = parser.add_mutually_exclusive_group()
    archive_group.add_argument(
        "--archive",
        dest="archive",
        action="store_true",
        default=None,
        help="For reset: archive runtime artifacts before cleanup (default).",
    )
    archive_group.add_argument(
        "--no-archive",
        dest="archive",
        action="store_false",
        default=None,
        help="For reset: skip archive before cleanup.",
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
    parser.add_argument(
        "--enable-botorch-gp", action="store_true", help="Enable BoTorch GP backend for suggestions"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    commands = {
        "suggest": cmd_suggest,
        "ingest": cmd_ingest,
        "import-observations": cmd_import_observations,
        "export-observations": cmd_export_observations,
        "status": cmd_status,
        "demo": cmd_demo,
        "cancel": cmd_cancel,
        "retire": cmd_retire,
        "heartbeat": cmd_heartbeat,
        "report": cmd_report,
        "reset": cmd_reset,
        "list-archives": cmd_list_archives,
        "restore": cmd_restore,
        "prune-archives": cmd_prune_archives,
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
