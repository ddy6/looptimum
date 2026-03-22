from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

JSONDict = dict[str, Any]

_CANONICAL_STATUSES = ("ok", "failed", "killed", "timeout")
_DEFAULT_PENDING_AGE_BUCKETS_SECONDS = (60.0, 300.0, 3600.0, 21600.0, 86400.0)
_LOG_LABELS = ("acquisition_log_file", "event_log_file")
_LOG_LIMIT_KEYS = {
    "acquisition_log_file": "acquisition_log_max_bytes",
    "event_log_file": "event_log_max_bytes",
}
_SUGGEST_LATENCY_FIELD = "telemetry.suggest_latency_seconds"


def _require_object(value: Any, *, field_name: str) -> JSONDict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def _require_optional_positive_int(value: Any, *, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer >= 1 or null")
    if value < 1:
        raise ValueError(f"{field_name} must be >= 1")
    return int(value)


def _require_optional_positive_float(value: Any, *, field_name: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite number > 0 or null")
    out = float(value)
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(f"{field_name} must be a finite number > 0 or null")
    return out


def _normalize_allowed_statuses(value: Any) -> list[str]:
    if value is None:
        return list(_CANONICAL_STATUSES)
    if not isinstance(value, list) or not value:
        raise ValueError("governance.allowed_statuses must be a non-empty list or null")

    statuses: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, str):
            raise ValueError(f"governance.allowed_statuses[{index}] must be a string")
        status = raw.strip().lower()
        if status not in _CANONICAL_STATUSES:
            raise ValueError(
                "governance.allowed_statuses must stay within canonical statuses "
                f"{list(_CANONICAL_STATUSES)}"
            )
        if status in seen:
            raise ValueError("governance.allowed_statuses must not contain duplicates")
        seen.add(status)
        statuses.append(status)
    return statuses


def normalize_governance_config(cfg: Any) -> JSONDict:
    bo_config = _require_object(cfg, field_name="bo_config")

    governance = _require_object(bo_config.get("governance"), field_name="governance")
    retention = _require_object(bo_config.get("retention"), field_name="retention")
    archives = _require_object(retention.get("archives"), field_name="retention.archives")
    logs = _require_object(retention.get("logs"), field_name="retention.logs")

    extra_governance_keys = sorted(set(governance) - {"allowed_statuses"})
    if extra_governance_keys:
        raise ValueError(f"governance includes unsupported keys {extra_governance_keys}")

    extra_archive_keys = sorted(set(archives) - {"max_count", "max_age_seconds", "max_total_bytes"})
    if extra_archive_keys:
        raise ValueError(f"retention.archives includes unsupported keys {extra_archive_keys}")

    extra_log_keys = sorted(set(logs) - {"event_log_max_bytes", "acquisition_log_max_bytes"})
    if extra_log_keys:
        raise ValueError(f"retention.logs includes unsupported keys {extra_log_keys}")

    return {
        "allowed_statuses": _normalize_allowed_statuses(governance.get("allowed_statuses")),
        "retention": {
            "archives": {
                "max_count": _require_optional_positive_int(
                    archives.get("max_count"),
                    field_name="retention.archives.max_count",
                ),
                "max_age_seconds": _require_optional_positive_float(
                    archives.get("max_age_seconds"),
                    field_name="retention.archives.max_age_seconds",
                ),
                "max_total_bytes": _require_optional_positive_int(
                    archives.get("max_total_bytes"),
                    field_name="retention.archives.max_total_bytes",
                ),
            },
            "logs": {
                "event_log_max_bytes": _require_optional_positive_int(
                    logs.get("event_log_max_bytes"),
                    field_name="retention.logs.event_log_max_bytes",
                ),
                "acquisition_log_max_bytes": _require_optional_positive_int(
                    logs.get("acquisition_log_max_bytes"),
                    field_name="retention.logs.acquisition_log_max_bytes",
                ),
            },
        },
        "pending_age_buckets_seconds": list(_DEFAULT_PENDING_AGE_BUCKETS_SECONDS),
    }


def _pending_entry_age_seconds(entry: JSONDict, *, now: float) -> float | None:
    last_touch: float | None = None
    for raw in (entry.get("suggested_at"), entry.get("last_heartbeat_at")):
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            candidate = float(raw)
            if math.isfinite(candidate) and (last_touch is None or candidate > last_touch):
                last_touch = candidate
    if last_touch is None:
        return None
    return max(0.0, float(now) - last_touch)


def summarize_pending_age_buckets(
    pending: list[JSONDict],
    *,
    now: float,
    bucket_edges_seconds: list[float] | tuple[float, ...] | None = None,
) -> JSONDict:
    edges = [float(edge) for edge in (bucket_edges_seconds or _DEFAULT_PENDING_AGE_BUCKETS_SECONDS)]
    if not edges:
        raise ValueError("bucket_edges_seconds must not be empty")
    if any(not math.isfinite(edge) or edge <= 0.0 for edge in edges):
        raise ValueError("bucket_edges_seconds must contain finite values > 0")
    if edges != sorted(edges):
        raise ValueError("bucket_edges_seconds must be sorted ascending")
    if len(set(edges)) != len(edges):
        raise ValueError("bucket_edges_seconds must not contain duplicates")

    buckets: list[JSONDict] = []
    lower_bound = 0.0
    for index, upper_bound in enumerate(edges):
        buckets.append(
            {
                "bucket_id": f"bucket_{index}",
                "lower_bound_seconds": lower_bound,
                "upper_bound_seconds": upper_bound,
                "count": 0,
            }
        )
        lower_bound = upper_bound
    buckets.append(
        {
            "bucket_id": "bucket_overflow",
            "lower_bound_seconds": lower_bound,
            "upper_bound_seconds": None,
            "count": 0,
        }
    )

    known_ages: list[float] = []
    unknown_age_count = 0
    for entry in pending:
        age = _pending_entry_age_seconds(entry, now=float(now))
        if age is None:
            unknown_age_count += 1
            continue
        known_ages.append(age)
        placed = False
        for bucket in buckets[:-1]:
            upper_bound = bucket["upper_bound_seconds"]
            if isinstance(upper_bound, (int, float)) and age < float(upper_bound):
                bucket["count"] = int(bucket["count"]) + 1
                placed = True
                break
        if not placed:
            buckets[-1]["count"] = int(buckets[-1]["count"]) + 1

    return {
        "bucket_edges_seconds": edges,
        "buckets": buckets,
        "pending_count": len(pending),
        "known_age_count": len(known_ages),
        "unknown_age_count": unknown_age_count,
        "oldest_pending_age_seconds": max(known_ages) if known_ages else None,
    }


def _relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _path_size_bytes(path: Path) -> int:
    if path.is_file():
        return int(path.stat().st_size)
    total = 0
    for child in sorted(path.rglob("*")):
        if child.is_file():
            total += int(child.stat().st_size)
    return total


def collect_log_footprint(root: Path, paths: dict[str, Path]) -> JSONDict:
    files: list[JSONDict] = []
    total_size_bytes = 0
    for label in _LOG_LABELS:
        path = paths[label]
        exists = path.exists()
        size_bytes = _path_size_bytes(path) if exists else 0
        total_size_bytes += size_bytes
        files.append(
            {
                "label": label,
                "path": _relative_path(root, path),
                "exists": exists,
                "size_bytes": size_bytes,
            }
        )
    return {
        "root": _relative_path(root, paths["state_file"].parent),
        "files": files,
        "total_size_bytes": total_size_bytes,
    }


def summarize_suggestion_latency(acquisition_log_path: Path) -> JSONDict:
    if not acquisition_log_path.exists():
        return {
            "field": _SUGGEST_LATENCY_FIELD,
            "entry_count": 0,
            "count": 0,
            "missing_telemetry_count": 0,
            "min_seconds": None,
            "max_seconds": None,
            "mean_seconds": None,
            "total_seconds": 0.0,
            "latest_seconds": None,
        }

    try:
        lines = acquisition_log_path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        raise ValueError(f"acquisition_log_file unreadable: {exc}") from exc

    latencies: list[float] = []
    entry_count = 0
    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception as exc:
            raise ValueError(f"acquisition_log_file line {idx} invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"acquisition_log_file line {idx} must be a JSON object")

        entry_count += 1
        telemetry = payload.get("telemetry")
        if telemetry is None:
            continue
        if not isinstance(telemetry, dict):
            raise ValueError(f"acquisition_log_file line {idx} telemetry must be an object")

        raw_latency = telemetry.get("suggest_latency_seconds")
        if raw_latency is None:
            continue
        if not isinstance(raw_latency, (int, float)) or isinstance(raw_latency, bool):
            raise ValueError(
                f"acquisition_log_file line {idx} telemetry.suggest_latency_seconds must be numeric"
            )
        latency = float(raw_latency)
        if not math.isfinite(latency) or latency < 0.0:
            raise ValueError(
                "acquisition_log_file line "
                f"{idx} telemetry.suggest_latency_seconds must be finite and >= 0"
            )
        latencies.append(latency)

    if not latencies:
        return {
            "field": _SUGGEST_LATENCY_FIELD,
            "entry_count": entry_count,
            "count": 0,
            "missing_telemetry_count": entry_count,
            "min_seconds": None,
            "max_seconds": None,
            "mean_seconds": None,
            "total_seconds": 0.0,
            "latest_seconds": None,
        }

    total_seconds = sum(latencies)
    return {
        "field": _SUGGEST_LATENCY_FIELD,
        "entry_count": entry_count,
        "count": len(latencies),
        "missing_telemetry_count": entry_count - len(latencies),
        "min_seconds": min(latencies),
        "max_seconds": max(latencies),
        "mean_seconds": total_seconds / len(latencies),
        "total_seconds": total_seconds,
        "latest_seconds": latencies[-1],
    }


def _archive_created_at_seconds(archive_dir: Path) -> float | None:
    manifest_path = archive_dir / "archive_manifest.json"
    if not manifest_path.exists():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    created_at = payload.get("created_at")
    if not isinstance(created_at, (int, float)) or isinstance(created_at, bool):
        return None
    created_at_value = float(created_at)
    if not math.isfinite(created_at_value):
        return None
    return created_at_value


def collect_archive_footprint(root: Path, paths: dict[str, Path], *, now: float) -> JSONDict:
    archives_root = paths["state_file"].parent / "reset_archives"
    if not archives_root.exists():
        return {
            "root": _relative_path(root, archives_root),
            "exists": False,
            "archive_count": 0,
            "known_age_count": 0,
            "total_size_bytes": 0,
            "max_known_age_seconds": None,
            "archives": [],
        }

    archives: list[JSONDict] = []
    known_ages: list[float] = []
    total_size_bytes = 0
    for archive_dir in sorted(path for path in archives_root.iterdir() if path.is_dir()):
        size_bytes = _path_size_bytes(archive_dir)
        total_size_bytes += size_bytes
        created_at = _archive_created_at_seconds(archive_dir)
        age_seconds: float | None = None
        if created_at is not None:
            age_seconds = max(0.0, float(now) - created_at)
            known_ages.append(age_seconds)
        archives.append(
            {
                "archive_id": archive_dir.name,
                "path": _relative_path(root, archive_dir),
                "size_bytes": size_bytes,
                "age_seconds": age_seconds,
                "manifest_present": created_at is not None,
            }
        )

    return {
        "root": _relative_path(root, archives_root),
        "exists": True,
        "archive_count": len(archives),
        "known_age_count": len(known_ages),
        "total_size_bytes": total_size_bytes,
        "max_known_age_seconds": max(known_ages) if known_ages else None,
        "archives": archives,
    }


def evaluate_governance_findings(
    *,
    governance_cfg: JSONDict,
    observations: list[JSONDict],
    archive_footprint: JSONDict,
    log_footprint: JSONDict,
) -> JSONDict:
    warnings: list[JSONDict] = []
    violations: list[JSONDict] = []

    allowed_statuses = set(governance_cfg["allowed_statuses"])
    disallowed_statuses = sorted(
        {
            str(observation.get("status", "")).strip().lower()
            for observation in observations
            if isinstance(observation, dict)
        }
        - allowed_statuses
    )
    if disallowed_statuses:
        violations.append(
            {
                "policy_id": "governance.allowed_statuses",
                "message": "Observed statuses fall outside governance.allowed_statuses",
                "details": {
                    "allowed_statuses": list(governance_cfg["allowed_statuses"]),
                    "observed_statuses": disallowed_statuses,
                },
            }
        )

    archive_limits = governance_cfg["retention"]["archives"]
    archive_count_limit = archive_limits["max_count"]
    if archive_count_limit is not None and int(archive_footprint["archive_count"]) > int(
        archive_count_limit
    ):
        violations.append(
            {
                "policy_id": "retention.archives.max_count",
                "message": "Reset archive count exceeds configured retention limit",
                "details": {
                    "archive_count": int(archive_footprint["archive_count"]),
                    "max_count": int(archive_count_limit),
                },
            }
        )

    archive_size_limit = archive_limits["max_total_bytes"]
    if archive_size_limit is not None and int(archive_footprint["total_size_bytes"]) > int(
        archive_size_limit
    ):
        violations.append(
            {
                "policy_id": "retention.archives.max_total_bytes",
                "message": "Reset archive storage exceeds configured retention limit",
                "details": {
                    "total_size_bytes": int(archive_footprint["total_size_bytes"]),
                    "max_total_bytes": int(archive_size_limit),
                },
            }
        )

    archive_age_limit = archive_limits["max_age_seconds"]
    if archive_age_limit is not None:
        aged_archives = [
            {
                "archive_id": str(entry["archive_id"]),
                "age_seconds": float(entry["age_seconds"]),
            }
            for entry in archive_footprint["archives"]
            if isinstance(entry.get("age_seconds"), (int, float))
            and float(entry["age_seconds"]) > float(archive_age_limit)
        ]
        if aged_archives:
            violations.append(
                {
                    "policy_id": "retention.archives.max_age_seconds",
                    "message": "Reset archive age exceeds configured retention limit",
                    "details": {
                        "max_age_seconds": float(archive_age_limit),
                        "archives": aged_archives,
                    },
                }
            )

        unknown_age_archives = [
            str(entry["archive_id"])
            for entry in archive_footprint["archives"]
            if entry.get("age_seconds") is None
        ]
        if unknown_age_archives:
            warnings.append(
                {
                    "policy_id": "retention.archives.max_age_seconds.unknown_age_archives",
                    "message": "Some reset archives have unknown age and were not evaluated against retention.archives.max_age_seconds",
                    "details": {
                        "max_age_seconds": float(archive_age_limit),
                        "archive_ids": unknown_age_archives,
                    },
                }
            )

    log_limits = governance_cfg["retention"]["logs"]
    for file_summary in log_footprint["files"]:
        label = str(file_summary["label"])
        limit_key = _LOG_LIMIT_KEYS[label]
        limit = log_limits.get(limit_key)
        if limit is None:
            continue
        if int(file_summary["size_bytes"]) > int(limit):
            violations.append(
                {
                    "policy_id": f"retention.logs.{limit_key}",
                    "message": "Append-only log file exceeds configured retention limit",
                    "details": {
                        "label": label,
                        "path": file_summary["path"],
                        "size_bytes": int(file_summary["size_bytes"]),
                        "max_bytes": int(limit),
                    },
                }
            )

    return {
        "warnings": warnings,
        "violations": violations,
    }


def build_governance_snapshot(
    root: Path,
    state: JSONDict,
    paths: dict[str, Path],
    cfg: JSONDict,
    *,
    now: float,
) -> JSONDict:
    governance_cfg = normalize_governance_config(cfg)
    pending_age = summarize_pending_age_buckets(
        list(state.get("pending", [])),
        now=float(now),
        bucket_edges_seconds=governance_cfg["pending_age_buckets_seconds"],
    )
    archive_footprint = collect_archive_footprint(root, paths, now=float(now))
    log_footprint = collect_log_footprint(root, paths)
    findings = evaluate_governance_findings(
        governance_cfg=governance_cfg,
        observations=list(state.get("observations", [])),
        archive_footprint=archive_footprint,
        log_footprint=log_footprint,
    )
    return {
        "allowed_statuses": list(governance_cfg["allowed_statuses"]),
        "pending_age": pending_age,
        "retention": governance_cfg["retention"],
        "footprints": {
            "archives": archive_footprint,
            "logs": log_footprint,
        },
        "warnings": findings["warnings"],
        "violations": findings["violations"],
    }
