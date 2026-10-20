"""Dependency-free optimizer configuration, capability checks, and diagnostics."""

from __future__ import annotations

import hashlib
import json
import math
from importlib.metadata import PackageNotFoundError, version
from typing import Any

JSONDict = dict[str, Any]
AX_STATE_SCHEMA_VERSION = "0.4.0"
AX_FORMAT_VERSION = 1
AX_TESTED_VERSION = "1.3.1"
AX_DEFAULTS: JSONDict = {
    "method": "fast",
    "initialization_budget": 6,
    "min_observed_initialization_trials": 6,
    "initialize_with_center": False,
    "generation_timeout_seconds": 120.0,
    "max_generation_attempts": 8,
    "allow_completed_repeats": False,
}


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def normalize_optimizer_config(
    cfg: JSONDict, *, template: str = "bo_client", enable_botorch_gp: bool = False
) -> JSONDict:
    raw = cfg.get("optimizer", {})
    if not isinstance(raw, dict):
        raise ValueError("optimizer must be an object")
    if set(raw) - {"backend", "ax"}:
        raise ValueError(f"Unknown optimizer settings: {sorted(set(raw) - {'backend', 'ax'})}")
    backend = raw.get("backend", "legacy")
    if backend not in ("legacy", "ax"):
        raise ValueError("optimizer.backend must be 'legacy' or 'ax'")
    if backend == "legacy":
        if raw.get("ax"):
            raise ValueError("optimizer.ax settings require optimizer.backend='ax'")
        return {"backend": "legacy"}
    if template == "bo_client_demo":
        raise ValueError("Ax is supported by bo_client and bo_client_full, not bo_client_demo")
    if enable_botorch_gp or cfg.get("feature_flags", {}).get("enable_botorch_gp", False):
        raise ValueError("Ax selection conflicts with enable_botorch_gp; choose one optimizer")
    settings = raw.get("ax", {})
    if not isinstance(settings, dict):
        raise ValueError("optimizer.ax must be an object")
    unknown = set(settings) - set(AX_DEFAULTS)
    if unknown:
        raise ValueError(f"Unknown optimizer.ax settings: {sorted(unknown)}")
    options = {**AX_DEFAULTS, **settings}
    if "min_observed_initialization_trials" not in settings:
        options["min_observed_initialization_trials"] = options["initialization_budget"]
    if options["method"] != "fast":
        raise ValueError("optimizer.ax.method currently supports only 'fast'")
    for name in (
        "initialization_budget",
        "min_observed_initialization_trials",
        "max_generation_attempts",
    ):
        value = options[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"optimizer.ax.{name} must be a positive integer")
    if options["min_observed_initialization_trials"] > options["initialization_budget"]:
        raise ValueError("Ax minimum observed initialization trials must not exceed its budget")
    for name in ("initialize_with_center", "allow_completed_repeats"):
        if not isinstance(options[name], bool):
            raise ValueError(f"optimizer.ax.{name} must be a boolean")
    timeout = options["generation_timeout_seconds"]
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("optimizer.ax.generation_timeout_seconds must be finite and positive")
    return {"backend": "ax", "ax": options}


def validate_ax_capabilities(
    params: list[JSONDict], objective_cfg: JSONDict, constraints: JSONDict | None
) -> None:
    if objective_cfg["scalarization"]["policy"] == "lexicographic":
        raise ValueError("Ax does not yet support lexicographic objectives")
    for param in params:
        name = param["name"]
        if param.get("when"):
            raise ValueError(f"Ax does not yet support conditional parameter '{name}'")
        if param["type"] == "categorical":
            types = {type(value) for value in param["choices"]}
            if len(types) != 1:
                raise ValueError(f"Ax requires homogeneous categorical choices for '{name}'")
    if constraints:
        for rule in ("linear_inequalities", "forbidden_combinations"):
            if constraints.get(rule):
                raise ValueError(f"Ax does not yet support constraints.{rule}")


def assert_backend_matches_state(state: JSONDict, optimizer: JSONDict) -> None:
    persisted = state.get("optimizer")
    if persisted is not None:
        if not isinstance(persisted, dict) or persisted.get("backend") != "ax":
            raise ValueError("Invalid persisted optimizer identity")
        if optimizer["backend"] != "ax":
            raise ValueError(
                "This is an Ax campaign; restore optimizer.backend='ax' before suggesting"
            )
    elif optimizer["backend"] == "ax" and state.get("pending"):
        raise ValueError("Finish existing pending trials before initializing an Ax campaign")


def dependency_versions() -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for name in ("ax-platform", "botorch", "torch", "gpytorch", "numpy", "scipy"):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = None
    return result


def optimizer_diagnostics(
    cfg: JSONDict, *, template: str, enable_botorch_gp: bool = False
) -> JSONDict:
    optimizer = normalize_optimizer_config(
        cfg, template=template, enable_botorch_gp=enable_botorch_gp
    )
    versions = dependency_versions()
    result: JSONDict = {**optimizer, "versions": versions}
    if optimizer["backend"] == "ax":
        result["available"] = versions["ax-platform"] == AX_TESTED_VERSION and all(
            versions.values()
        )
        result["supported_ax_version"] = AX_TESTED_VERSION
        result["inactive_legacy_settings"] = [
            key
            for key in ("surrogate", "acquisition", "initial_random_trials", "candidate_pool_size")
            if key in cfg
        ]
    return result
