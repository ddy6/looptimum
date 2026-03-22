from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE_MODULE = REPO_ROOT / "templates" / "_shared" / "governance.py"


def _load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load shared module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GOVERNANCE = _load_module(GOVERNANCE_MODULE, "looptimum_shared_governance_test")


def _runtime_paths(root: Path) -> dict[str, Path]:
    state_dir = root / "state"
    return {
        "state_file": state_dir / "bo_state.json",
        "observations_csv": state_dir / "observations.csv",
        "acquisition_log_file": state_dir / "acquisition_log.jsonl",
        "event_log_file": state_dir / "event_log.jsonl",
        "trials_dir": state_dir / "trials",
        "lock_file": state_dir / ".looptimum.lock",
        "report_json_file": state_dir / "report.json",
        "report_md_file": state_dir / "report.md",
    }


def test_normalize_governance_config_accepts_default_optional_sections() -> None:
    assert GOVERNANCE.normalize_governance_config(
        {
            "max_trials": 40,
            "max_pending_trials": None,
        }
    ) == {
        "allowed_statuses": ["ok", "failed", "killed", "timeout"],
        "retention": {
            "archives": {
                "max_count": None,
                "max_age_seconds": None,
                "max_total_bytes": None,
            },
            "logs": {
                "event_log_max_bytes": None,
                "acquisition_log_max_bytes": None,
            },
        },
        "pending_age_buckets_seconds": [60.0, 300.0, 3600.0, 21600.0, 86400.0],
    }


@pytest.mark.parametrize(
    ("cfg", "pattern"),
    [
        (
            {"governance": {"allowed_statuses": ["ok", "paused"]}},
            "must stay within canonical statuses",
        ),
        (
            {"governance": {"allowed_statuses": ["ok", "ok"]}},
            "must not contain duplicates",
        ),
        (
            {"retention": {"archives": {"max_count": 0}}},
            "retention.archives.max_count must be >= 1",
        ),
        (
            {"retention": {"logs": {"event_log_max_bytes": 0}}},
            "retention.logs.event_log_max_bytes must be >= 1",
        ),
        (
            {"retention": {"archives": {"unknown": 1}}},
            "retention.archives includes unsupported keys",
        ),
    ],
)
def test_normalize_governance_config_rejects_invalid_config(
    cfg: dict[str, object], pattern: str
) -> None:
    with pytest.raises(ValueError, match=pattern):
        GOVERNANCE.normalize_governance_config(cfg)


def test_summarize_pending_age_buckets_is_deterministic() -> None:
    summary = GOVERNANCE.summarize_pending_age_buckets(
        [
            {"trial_id": 1, "suggested_at": 150.0},
            {"trial_id": 2, "suggested_at": 0.0, "last_heartbeat_at": 20.0},
            {"trial_id": 3},
        ],
        now=200.0,
        bucket_edges_seconds=[60.0, 300.0],
    )

    assert summary == {
        "bucket_edges_seconds": [60.0, 300.0],
        "buckets": [
            {
                "bucket_id": "bucket_0",
                "lower_bound_seconds": 0.0,
                "upper_bound_seconds": 60.0,
                "count": 1,
            },
            {
                "bucket_id": "bucket_1",
                "lower_bound_seconds": 60.0,
                "upper_bound_seconds": 300.0,
                "count": 1,
            },
            {
                "bucket_id": "bucket_overflow",
                "lower_bound_seconds": 300.0,
                "upper_bound_seconds": None,
                "count": 0,
            },
        ],
        "pending_count": 3,
        "known_age_count": 2,
        "unknown_age_count": 1,
        "oldest_pending_age_seconds": 180.0,
    }


def test_build_governance_snapshot_reports_deterministic_findings(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    paths = _runtime_paths(root)
    paths["state_file"].parent.mkdir(parents=True, exist_ok=True)
    paths["acquisition_log_file"].write_text("{}\n", encoding="utf-8")
    paths["event_log_file"].write_text("{}\n{}\n", encoding="utf-8")

    archives_root = paths["state_file"].parent / "reset_archives"
    manifest_archive = archives_root / "reset-001"
    manifest_archive.mkdir(parents=True)
    (manifest_archive / "payload.txt").write_text("archive payload\n", encoding="utf-8")
    (manifest_archive / "archive_manifest.json").write_text(
        json.dumps({"archive_id": "reset-001", "created_at": 100.0}) + "\n",
        encoding="utf-8",
    )

    legacy_archive = archives_root / "reset-legacy"
    legacy_archive.mkdir(parents=True)
    (legacy_archive / "payload.txt").write_text("legacy archive\n", encoding="utf-8")

    state = {
        "observations": [
            {"trial_id": 1, "status": "ok"},
            {"trial_id": 2, "status": "timeout"},
        ],
        "pending": [
            {"trial_id": 3, "suggested_at": 150.0},
            {"trial_id": 4, "suggested_at": 0.0, "last_heartbeat_at": 20.0},
        ],
    }
    cfg = {
        "governance": {"allowed_statuses": ["ok", "failed"]},
        "retention": {
            "archives": {
                "max_count": 1,
                "max_age_seconds": 50.0,
                "max_total_bytes": 1,
            },
            "logs": {
                "event_log_max_bytes": 1,
                "acquisition_log_max_bytes": 1,
            },
        },
    }

    snapshot = GOVERNANCE.build_governance_snapshot(
        root,
        state,
        paths,
        cfg,
        now=200.0,
    )

    assert snapshot["allowed_statuses"] == ["ok", "failed"]
    assert snapshot["pending_age"]["pending_count"] == 2
    assert snapshot["footprints"]["archives"]["archive_count"] == 2
    assert snapshot["footprints"]["archives"]["known_age_count"] == 1
    assert snapshot["footprints"]["archives"]["archives"][0]["archive_id"] == "reset-001"
    assert snapshot["footprints"]["archives"]["archives"][0]["age_seconds"] == 100.0
    assert snapshot["footprints"]["archives"]["archives"][1]["archive_id"] == "reset-legacy"
    assert snapshot["footprints"]["archives"]["archives"][1]["age_seconds"] is None
    assert snapshot["footprints"]["logs"]["files"] == [
        {
            "label": "acquisition_log_file",
            "path": "state/acquisition_log.jsonl",
            "exists": True,
            "size_bytes": 3,
        },
        {
            "label": "event_log_file",
            "path": "state/event_log.jsonl",
            "exists": True,
            "size_bytes": 6,
        },
    ]
    assert {item["policy_id"] for item in snapshot["violations"]} == {
        "governance.allowed_statuses",
        "retention.archives.max_age_seconds",
        "retention.archives.max_count",
        "retention.archives.max_total_bytes",
        "retention.logs.acquisition_log_max_bytes",
        "retention.logs.event_log_max_bytes",
    }
    assert snapshot["warnings"] == [
        {
            "policy_id": "retention.archives.max_age_seconds.unknown_age_archives",
            "message": "Some reset archives have unknown age and were not evaluated against retention.archives.max_age_seconds",
            "details": {
                "max_age_seconds": 50.0,
                "archive_ids": ["reset-legacy"],
            },
        }
    ]


def test_summarize_suggestion_latency_is_deterministic(tmp_path: Path) -> None:
    acquisition_log = tmp_path / "acquisition_log.jsonl"
    acquisition_log.write_text(
        "\n".join(
            [
                json.dumps({"trial_id": 1, "decision": {"kind": "random"}, "timestamp": 1.0}),
                json.dumps(
                    {
                        "trial_id": 2,
                        "decision": {"kind": "random"},
                        "timestamp": 2.0,
                        "telemetry": {"suggest_latency_seconds": 0.125},
                    }
                ),
                json.dumps(
                    {
                        "trial_id": 3,
                        "decision": {"kind": "proxy"},
                        "timestamp": 3.0,
                        "telemetry": {"suggest_latency_seconds": 0.375},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert GOVERNANCE.summarize_suggestion_latency(acquisition_log) == {
        "field": "telemetry.suggest_latency_seconds",
        "entry_count": 3,
        "count": 2,
        "missing_telemetry_count": 1,
        "min_seconds": 0.125,
        "max_seconds": 0.375,
        "mean_seconds": 0.25,
        "total_seconds": 0.5,
        "latest_seconds": 0.375,
    }


def test_summarize_suggestion_latency_rejects_invalid_numeric_payload(tmp_path: Path) -> None:
    acquisition_log = tmp_path / "acquisition_log.jsonl"
    acquisition_log.write_text(
        json.dumps(
            {
                "trial_id": 1,
                "decision": {"kind": "random"},
                "timestamp": 1.0,
                "telemetry": {"suggest_latency_seconds": -1.0},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be finite and >= 0"):
        GOVERNANCE.summarize_suggestion_latency(acquisition_log)
