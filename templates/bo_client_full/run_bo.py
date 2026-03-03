#!/usr/bin/env python3
"""Client-facing single-stage optimization harness with resumable state.

bo_client_full adds an optional BoTorch GP backend behind a feature flag (with proxy fallback support).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import time
from pathlib import Path


def load_cfg(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_type(value: object, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    return True


def validate_against_schema(value: object, schema: dict, path: str = "$") -> None:
    expected = schema.get("type")
    if isinstance(expected, str) and not _is_type(value, expected):
        raise ValueError(f"{path} must be of type '{expected}'")

    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} must be one of {schema['enum']}")

    if "minimum" in schema and isinstance(value, (int, float)) and not isinstance(value, bool):
        if float(value) < float(schema["minimum"]):
            raise ValueError(f"{path} must be >= {schema['minimum']}")

    if schema.get("type") == "object":
        assert isinstance(value, dict)
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"{path}.{key} is required")
        for key, child_schema in schema.get("properties", {}).items():
            if key in value:
                validate_against_schema(value[key], child_schema, f"{path}.{key}")


def validate_ingest_payload(payload: dict, schema: dict, objective: dict) -> None:
    validate_against_schema(payload, schema)
    obj_name = str(objective["name"])
    objectives = payload.get("objectives", {})
    if obj_name not in objectives:
        raise ValueError(f"ingest payload missing primary objective '{obj_name}'")
    try:
        obj_value = float(objectives[obj_name])
    except (TypeError, ValueError):
        raise ValueError(f"ingest payload objective '{obj_name}' must be numeric") from None
    if not math.isfinite(obj_value):
        raise ValueError(f"ingest payload objective '{obj_name}' must be finite")


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
        raise ValueError("parameter_space.yaml must define 'parameters'")
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


def _candidate_pool(rng: random.Random, params: list[dict], n: int) -> list[dict]:
    return [random_point(rng, params) for _ in range(int(n))]


def propose_with_proxy(
    rng: random.Random, state: dict, cfg: dict, params: list[dict], objective: dict
) -> tuple[dict, dict]:
    obj_name, direction = objective["name"], objective["direction"]
    surrogate, acq = cfg["surrogate"], cfg["acquisition"]
    best = state["best"]["objective_value"] if state["best"] else None
    scored = []
    for cand in _candidate_pool(rng, params, int(cfg["candidate_pool_size"])):
        mean, std = predict_rbf_proxy(
            cand, state["observations"], params, obj_name, float(surrogate.get("length_scale", 0.2))
        )
        scored.append((acq_score(mean, std, best, direction, acq), cand, mean, std))
    scored.sort(key=lambda x: x[0], reverse=True)
    score, cand, mean, std = scored[0]
    return cand, {
        "strategy": "surrogate_acquisition",
        "surrogate_backend": "rbf_proxy",
        "acquisition_type": acq.get("type", "ucb"),
        "predicted_mean": mean,
        "predicted_std": std,
        "acquisition_score": score,
    }


def propose_with_botorch(
    rng: random.Random, state: dict, cfg: dict, params: list[dict], objective: dict
) -> tuple[dict, dict]:
    import torch
    from botorch.fit import fit_gpytorch_mll
    from botorch.models import SingleTaskGP
    from gpytorch.mlls import ExactMarginalLogLikelihood

    obj_name, direction = objective["name"], objective["direction"]
    acq = cfg["acquisition"]

    def normalize(vec: dict) -> list[float]:
        out = []
        for p in params:
            lo, hi = map(float, p["bounds"])
            span = max(hi - lo, 1e-12)
            out.append((float(vec[p["name"]]) - lo) / span)
        return out

    def denormalize(vals: list[float]) -> dict:
        out: dict = {}
        for i, p in enumerate(params):
            lo, hi = map(float, p["bounds"])
            v = lo + float(vals[i]) * (hi - lo)
            out[p["name"]] = int(round(v)) if p["type"] == "int" else float(v)
        return out

    X = torch.tensor([normalize(o["params"]) for o in state["observations"]], dtype=torch.double)
    Y_raw = [float(o["objectives"][obj_name]) for o in state["observations"]]
    Y = torch.tensor([[-y] if direction == "maximize" else [y] for y in Y_raw], dtype=torch.double)

    model = SingleTaskGP(X, Y)
    mll = ExactMarginalLogLikelihood(model.likelihood, model)
    fit_gpytorch_mll(mll)

    best = state["best"]["objective_value"] if state["best"] else None
    scored = []
    for cand in _candidate_pool(rng, params, int(cfg["candidate_pool_size"])):
        x = torch.tensor([normalize(cand)], dtype=torch.double)
        post = model.posterior(x)
        mean_t = post.mean.detach().cpu().view(-1)[0].item()
        std_t = post.variance.detach().cpu().clamp_min(1e-12).sqrt().view(-1)[0].item()

        mean = -mean_t if direction == "maximize" else mean_t
        score = acq_score(mean, std_t, best, direction, acq)
        scored.append((score, denormalize(normalize(cand)), mean, std_t))

    scored.sort(key=lambda x: x[0], reverse=True)
    score, cand, mean, std = scored[0]
    return cand, {
        "strategy": "surrogate_acquisition",
        "surrogate_backend": "botorch_gp",
        "acquisition_type": acq.get("type", "ucb"),
        "predicted_mean": mean,
        "predicted_std": std,
        "acquisition_score": score,
    }


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
) -> tuple[dict, dict]:
    objective = obj_cfg["primary_objective"]
    if len(state["observations"]) < int(cfg["initial_random_trials"]):
        return random_point(rng, params), {"strategy": "initial_random", "surrogate_backend": None}

    if use_botorch_backend(args, cfg):
        try:
            return propose_with_botorch(rng, state, cfg, params, objective)
        except Exception as exc:
            if cfg.get("feature_flags", {}).get("fallback_to_proxy_if_unavailable", True):
                cand, decision = propose_with_proxy(rng, state, cfg, params, objective)
                decision["fallback_reason"] = str(exc)
                return cand, decision
            raise
    return propose_with_proxy(rng, state, cfg, params, objective)


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
    cfg = load_cfg(root / "bo_config.yaml")
    params = norm_space(load_cfg(root / "parameter_space.yaml"))
    obj_cfg = load_cfg(root / "objective_schema.yaml")
    objective = obj_cfg["primary_objective"]

    state_path = root / cfg["paths"]["state_file"]
    state = load_state(state_path)
    if state["meta"]["seed"] is None:
        state["meta"]["seed"] = int(cfg["seed"])

    if len(state["observations"]) + len(state["pending"]) >= int(cfg["max_trials"]):
        print("No suggestion generated: budget exhausted.")
        return

    rng = random.Random(int(state["meta"]["seed"]) + int(state["next_trial_id"]))
    cand, decision = propose(rng, state, cfg, params, obj_cfg, args)
    tid = int(state["next_trial_id"])
    suggestion = {"trial_id": tid, "params": cand, "suggested_at": time.time()}
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
    cfg = load_cfg(root / "bo_config.yaml")
    objective = load_cfg(root / "objective_schema.yaml")["primary_objective"]
    schema_rel = cfg["paths"].get("result_schema_file", "schemas/result_payload.schema.json")
    result_schema = load_cfg(root / schema_rel)
    state_path = root / cfg["paths"]["state_file"]
    state = load_state(state_path)

    payload = load_cfg(Path(args.results_file))
    validate_ingest_payload(payload, result_schema, objective)
    tid = int(payload["trial_id"])
    pending = {int(p["trial_id"]): p for p in state["pending"]}
    if tid not in pending:
        raise ValueError(f"trial_id {tid} is not pending")
    if payload.get("params") != pending[tid].get("params"):
        raise ValueError("ingest payload params do not match the pending suggestion")

    state["pending"] = [p for p in state["pending"] if int(p["trial_id"]) != tid]
    state["observations"].append(
        {
            "trial_id": tid,
            "params": payload["params"],
            "objectives": payload["objectives"],
            "status": payload.get("status", "ok"),
            "completed_at": time.time(),
        }
    )
    update_best(state, objective)
    save_state(state_path, state)

    rows = []
    for o in state["observations"]:
        r = {"trial_id": o["trial_id"], "status": o["status"], "completed_at": o["completed_at"]}
        r.update({f"param_{k}": v for k, v in o["params"].items()})
        r.update({f"objective_{k}": v for k, v in o["objectives"].items()})
        rows.append(r)
    write_obs_csv(root / cfg["paths"]["observations_csv"], rows)
    print(f"Ingested trial_id={tid}. Observations={len(state['observations'])}")


def cmd_status(args: argparse.Namespace) -> None:
    root = Path(args.project_root)
    cfg = load_cfg(root / "bo_config.yaml")
    s = load_state(root / cfg["paths"]["state_file"])
    print(
        json.dumps(
            {
                "observations": len(s["observations"]),
                "pending": len(s["pending"]),
                "next_trial_id": s["next_trial_id"],
                "best": s["best"],
                "botorch_feature_flag": use_botorch_backend(args, cfg),
            },
            indent=2,
        )
    )


def cmd_demo(args: argparse.Namespace) -> None:
    root = Path(args.project_root)

    def toy_loss(p: dict) -> float:
        return (p["x1"] - 0.25) ** 2 + (p["x2"] - 0.75) ** 2 + 0.2 * math.sin(8.0 * p["x1"])

    for _ in range(int(args.steps)):
        cfg = load_cfg(root / "bo_config.yaml")
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
    p.add_argument(
        "--enable-botorch-gp", action="store_true", help="Enable BoTorch GP backend for suggestions"
    )
    return p.parse_args()


def main() -> None:
    a = parse_args()
    {"suggest": cmd_suggest, "ingest": cmd_ingest, "status": cmd_status, "demo": cmd_demo}[
        a.command
    ](a)


if __name__ == "__main__":
    main()
