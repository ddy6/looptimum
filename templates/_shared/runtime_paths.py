"""Dependency-free artifact paths shared by controllers, copying and tracking."""

from __future__ import annotations

from pathlib import Path
from typing import Any

DEFAULT_PATHS = {
    "state_file": "state/bo_state.json",
    "observations_csv": "state/observations.csv",
    "acquisition_log_file": "state/acquisition_log.jsonl",
    "event_log_file": "state/event_log.jsonl",
    "import_reports_dir": "state/import_reports",
    "trials_dir": "state/trials",
    "optimizer_dir": "state/optimizer",
    "lock_file": "state/.looptimum.lock",
    "report_json_file": "state/report.json",
    "report_md_file": "state/report.md",
}


def resolve_runtime_paths(project_root: Path, paths_cfg: dict[str, Any]) -> dict[str, Path]:
    resolved: dict[str, Path] = {}
    for key, default_rel in DEFAULT_PATHS.items():
        rel = paths_cfg.get(key, default_rel)
        resolved[key] = (project_root / str(rel)).resolve()
    return resolved
