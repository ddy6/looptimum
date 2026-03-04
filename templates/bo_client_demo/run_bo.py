#!/usr/bin/env python3
"""Client-facing single-stage optimization harness with resumable state."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import random
import time
from pathlib import Path

_TEMPLATE_DIR = Path(__file__).resolve().parent


def _load_contract_module():
    contract_path = _TEMPLATE_DIR.parent / "_shared" / "contract.py"
    if not contract_path.exists():
        raise ModuleNotFoundError(
            f"Missing shared contract module at {contract_path}. "
            "Ensure templates/_shared is present."
        )
    spec = importlib.util.spec_from_file_location("looptimum_shared_contract", contract_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load shared contract module from {contract_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CONTRACT = _load_contract_module()
build_observation_contract = _CONTRACT.build_observation_contract
diff_contract_records = _CONTRACT.diff_contract_records
format_contract_diff_error = _CONTRACT.format_contract_diff_error
load_contract_document = _CONTRACT.load_contract_document
load_data_file = _CONTRACT.load_data_file
load_schema_from_paths = _CONTRACT.load_schema_from_paths
normalize_ingest_payload = _CONTRACT.normalize_ingest_payload
validate_against_schema = _CONTRACT.validate_against_schema


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
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(path)


def write_obs_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    keys = sorted({k for r in rows for k in r.keys()})
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


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


def norm_dist(a: dict, b: dict, params: list[dict]) -> float:
    s = 0.0
    for p in params:
        lo, hi = map(float, p["bounds"])
        span = max(hi - lo, 1e-12)
        s += ((float(a[p["name"]]) - float(b[p["name"]])) / span) ** 2
    return math.sqrt(s)


def predict_rbf_proxy(
    x: dict, obs: list[dict], params: list[dict], obj: str, l: float
) -> tuple[float, float]:
    if not obs:
        return 0.0, 1.0
    ys, ws = [], []
    for row in obs:
        d = norm_dist(x, row["params"], params)
        w = math.exp(-(d * d) / (2.0 * max(l, 1e-6) ** 2))
        ys.append(float(row["objectives"][obj]))
        ws.append(w)
    wsum = sum(ws)
    if wsum < 1e-9:
        return sum(ys) / len(ys), 1.0
    mean = sum(w * y for w, y in zip(ws, ys)) / wsum
    var = sum(w * (y - mean) ** 2 for w, y in zip(ws, ys)) / wsum
    density = wsum / len(obs)
    std = math.sqrt(max(var, 1e-12)) + max(0.0, 1.0 - min(1.0, density))
    return mean, std


def acq_score(mean: float, std: float, best: float | None, direction: str, acq: dict) -> float:
    t = acq.get("type", "ucb")
    kappa = float(acq.get("kappa", 1.5))
    xi = float(acq.get("xi", 0.01))
    if t == "ucb":
        return -(mean - kappa * std) if direction == "minimize" else (mean + kappa * std)
    if t == "ei_proxy":
        if best is None:
            return std
        imp = max(0.0, best - mean) if direction == "minimize" else max(0.0, mean - best)
        return imp + xi * std
    raise ValueError(f"Unsupported acquisition type: {t}")


def propose(
    rng: random.Random, state: dict, cfg: dict, params: list[dict], obj_cfg: dict
) -> tuple[dict, dict]:
    obs = state["observations"]
    objective = obj_cfg["primary_objective"]
    obj_name, direction = objective["name"], objective["direction"]
    if len(obs) < int(cfg["initial_random_trials"]):
        return random_point(rng, params), {"strategy": "initial_random"}

    surrogate, acq = cfg["surrogate"], cfg["acquisition"]
    best = state["best"]["objective_value"] if state["best"] else None
    scored = []
    for _ in range(int(cfg["candidate_pool_size"])):
        cand = random_point(rng, params)
        mean, std = predict_rbf_proxy(
            cand, obs, params, obj_name, float(surrogate.get("length_scale", 0.2))
        )
        scored.append((acq_score(mean, std, best, direction, acq), cand, mean, std))
    scored.sort(key=lambda x: x[0], reverse=True)
    score, cand, mean, std = scored[0]
    return cand, {
        "strategy": "surrogate_acquisition",
        "acquisition_type": acq.get("type", "ucb"),
        "predicted_mean": mean,
        "predicted_std": std,
        "acquisition_score": score,
    }


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


def cmd_suggest(args: argparse.Namespace) -> None:
    root = Path(args.project_root)
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

    state_path = root / cfg["paths"]["state_file"]
    state = load_state(state_path)
    if state["meta"]["seed"] is None:
        state["meta"]["seed"] = int(cfg["seed"])

    if len(state["observations"]) + len(state["pending"]) >= int(cfg["max_trials"]):
        print("No suggestion generated: budget exhausted.")
        return

    rng = random.Random(int(state["meta"]["seed"]) + int(state["next_trial_id"]))
    cand, decision = propose(rng, state, cfg, params, obj_cfg)
    tid = int(state["next_trial_id"])
    suggestion = {"trial_id": tid, "params": cand, "suggested_at": time.time()}
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
        trial_id=tid,
    )
    state["pending"].append(suggestion)
    state["next_trial_id"] = tid + 1

    log_path = root / cfg["paths"]["acquisition_log_file"]
    with log_path.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps({"trial_id": tid, "decision": decision, "timestamp": time.time()}) + "\n"
        )

    save_state(state_path, state)
    print(json.dumps(suggestion, indent=2))
    if not args.json_only:
        print(f"Objective direction: {objective['direction']} ({objective['name']})")


def cmd_ingest(args: argparse.Namespace) -> None:
    root = Path(args.project_root)
    cfg, _ = load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")

    obj_cfg, _ = load_contract_document(root, "objective_schema")
    if not isinstance(obj_cfg, dict):
        raise ValueError("objective_schema must be an object")
    objective = obj_cfg["primary_objective"]

    ingest_schema, _ = load_schema_from_paths(
        root,
        cfg["paths"],
        key="ingest_schema_file",
        legacy_key="result_schema_file",
        default_rel="../_shared/schemas/ingest_payload.schema.json",
    )
    state_path = root / cfg["paths"]["state_file"]
    state = load_state(state_path)

    payload_path = Path(args.results_file)
    payload = load_data_file(payload_path)
    if not isinstance(payload, dict):
        raise ValueError(f"Ingest payload must be an object: {payload_path}")
    validate_against_schema(payload, ingest_schema, source_path=payload_path)
    payload, tid = normalize_ingest_payload(
        payload,
        objective_name=str(objective["name"]),
        source_path=payload_path,
    )

    pending = {int(p["trial_id"]): p for p in state["pending"]}
    if tid not in pending:
        prior = next((o for o in state["observations"] if int(o["trial_id"]) == tid), None)
        if prior is None:
            raise ValueError(f"trial_id {tid} is not pending")

        expected = build_observation_contract(prior, objective_name=str(objective["name"]))
        received = {
            "trial_id": tid,
            "params": payload["params"],
            "objectives": payload["objectives"],
            "status": payload["status"],
        }
        if "penalty_objective" in payload:
            received["penalty_objective"] = payload["penalty_objective"]
        diffs = diff_contract_records(expected, received)
        if not diffs:
            print(f"No-op: trial_id={tid} already ingested with identical payload.")
            return
        raise ValueError(format_contract_diff_error(tid, diffs))

    if payload.get("params") != pending[tid].get("params"):
        param_diffs = diff_contract_records(
            {"params": pending[tid].get("params", {})},
            {"params": payload.get("params", {})},
        )
        details = "\n".join(f"- field {d}" for d in param_diffs)
        raise ValueError(f"ingest payload params mismatch for pending trial_id {tid}:\n{details}")

    state["pending"] = [p for p in state["pending"] if int(p["trial_id"]) != tid]
    observation = {
        "trial_id": tid,
        "params": payload["params"],
        "objectives": payload["objectives"],
        "status": payload["status"],
        "completed_at": time.time(),
    }
    if "penalty_objective" in payload:
        observation["penalty_objective"] = payload["penalty_objective"]
    state["observations"].append(observation)
    update_best(state, objective)
    save_state(state_path, state)

    rows = []
    for o in state["observations"]:
        r = {"trial_id": o["trial_id"], "status": o["status"], "completed_at": o["completed_at"]}
        r.update({f"param_{k}": v for k, v in o["params"].items()})
        r.update({f"objective_{k}": v for k, v in o["objectives"].items()})
        if "penalty_objective" in o:
            r["penalty_objective"] = o["penalty_objective"]
        rows.append(r)
    write_obs_csv(root / cfg["paths"]["observations_csv"], rows)
    print(f"Ingested trial_id={tid}. Observations={len(state['observations'])}")


def cmd_status(args: argparse.Namespace) -> None:
    root = Path(args.project_root)
    cfg, _ = load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")
    s = load_state(root / cfg["paths"]["state_file"])
    print(
        json.dumps(
            {
                "observations": len(s["observations"]),
                "pending": len(s["pending"]),
                "next_trial_id": s["next_trial_id"],
                "best": s["best"],
            },
            indent=2,
        )
    )


def cmd_demo(args: argparse.Namespace) -> None:
    root = Path(args.project_root)

    def toy_loss(p: dict) -> float:
        return (p["x1"] - 0.25) ** 2 + (p["x2"] - 0.75) ** 2 + 0.2 * math.sin(8.0 * p["x1"])

    for _ in range(int(args.steps)):
        cfg, _ = load_contract_document(root, "bo_config")
        if not isinstance(cfg, dict):
            raise ValueError("bo_config must be an object")
        state_before = load_state(root / cfg["paths"]["state_file"])
        pending_before = len(state_before["pending"])
        cmd_suggest(args)
        state = load_state(root / cfg["paths"]["state_file"])
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
        p = root / "examples" / "_demo_result.json"
        p.write_text(json.dumps(out, indent=2), encoding="utf-8")
        args.results_file = str(p)
        cmd_ingest(args)
    cmd_status(args)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Looptimum: minimal client-facing optimization harness")
    p.add_argument("command", choices=["suggest", "ingest", "status", "demo"])
    p.add_argument("--project-root", default=".")
    p.add_argument("--results-file", default="examples/example_results.json")
    p.add_argument("--steps", type=int, default=8)
    p.add_argument(
        "--json-only",
        action="store_true",
        help="For suggest: print only JSON (no trailing human-readable line).",
    )
    return p.parse_args()


def main() -> None:
    a = parse_args()
    {"suggest": cmd_suggest, "ingest": cmd_ingest, "status": cmd_status, "demo": cmd_demo}[
        a.command
    ](a)


if __name__ == "__main__":
    main()
