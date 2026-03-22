from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_DIR = REPO_ROOT / "client_harness_template"
if str(HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESS_DIR))

starterkit_tracking = importlib.import_module("starterkit_tracking")


def _write_tracker_fixture(project_root: Path) -> None:
    state_dir = project_root / "state"
    trial_dir = state_dir / "trials" / "trial_2"
    trial_dir.mkdir(parents=True, exist_ok=True)
    (trial_dir / "ingest_payload.json").write_text(
        json.dumps(
            {
                "schema_version": "0.3.0",
                "trial_id": 2,
                "params": {"x1": 0.6, "x2": 0.8},
                "objectives": {"loss": 0.082},
                "status": "ok",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (trial_dir / "manifest.json").write_text(
        json.dumps(
            {
                "trial_id": 2,
                "status": "ok",
                "objective_name": "loss",
                "objective_value": 0.082,
                "objective_vector": {"loss": 0.082},
                "scalarized_objective": 0.082,
                "artifact_path": "state/trials/trial_2/ingest_payload.json",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (state_dir / "bo_state.json").write_text(
        json.dumps(
            {
                "schema_version": "0.3.0",
                "meta": {"created_at": 10.0, "seed": 17},
                "observations": [
                    {
                        "trial_id": 2,
                        "params": {"x1": 0.6, "x2": 0.8},
                        "objectives": {"loss": 0.082},
                        "status": "ok",
                        "artifact_path": "state/trials/trial_2/ingest_payload.json",
                        "completed_at": 12.0,
                    }
                ],
                "pending": [],
                "next_trial_id": 3,
                "best": {
                    "trial_id": 2,
                    "objective_name": "loss",
                    "objective_value": 0.082,
                    "updated_at": 12.0,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (state_dir / "report.json").write_text(
        json.dumps(
            {
                "schema_version": "0.3.0",
                "generated_at": 13.0,
                "objective": {
                    "name": "loss",
                    "direction": "minimize",
                    "best_objective_name": "loss",
                    "scalarization_policy": "primary_only",
                },
                "objective_config": {
                    "primary_objective": {"name": "loss", "direction": "minimize"},
                    "secondary_objectives": [],
                    "objective_names": ["loss"],
                    "scalarization": {"policy": "primary_only"},
                },
                "counts": {
                    "observations": 1,
                    "pending": 0,
                    "failure_rate": 0.0,
                },
                "best": {
                    "trial_id": 2,
                    "objective_name": "loss",
                    "objective_value": 0.082,
                    "updated_at": 12.0,
                },
                "best_params": {"x1": 0.6, "x2": 0.8},
                "top_trials": [
                    {
                        "trial_id": 2,
                        "status": "ok",
                        "objective_name": "loss",
                        "objective_value": 0.082,
                        "objective_vector": {"loss": 0.082},
                        "scalarized_objective": 0.082,
                        "artifact_path": "state/trials/trial_2/ingest_payload.json",
                        "params": {"x1": 0.6, "x2": 0.8},
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (state_dir / "report.md").write_text("# report\n", encoding="utf-8")
    (state_dir / "event_log.jsonl").write_text(
        json.dumps({"event": "suggestion_created", "timestamp": 11.0, "trial_id": 2})
        + "\n"
        + json.dumps(
            {
                "event": "ingest_applied",
                "timestamp": 12.0,
                "trial_id": 2,
                "status": "ok",
                "command": "ingest",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_load_tracking_snapshot_collects_runtime_artifacts_and_events(tmp_path: Path) -> None:
    project_root = tmp_path / "campaign"
    _write_tracker_fixture(project_root)

    snapshot = starterkit_tracking.load_tracking_snapshot(project_root)

    assert snapshot["counts"]["observations"] == 1
    assert snapshot["best"]["trial_id"] == 2
    assert snapshot["top_trials"][0]["objective_vector"] == {"loss": 0.082}
    assert [event["topic"] for event in snapshot["recent_events"]] == ["suggested", "ingested"]
    artifact_labels = {item["label"] for item in snapshot["artifacts"]}
    assert "bo_state_json" in artifact_labels
    assert "report_json" in artifact_labels
    assert "trial_2_manifest" in artifact_labels
