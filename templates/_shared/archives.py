from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence

ARCHIVE_MANIFEST_FILENAME = "archive_manifest.json"
RESET_ARCHIVE_TYPE = "reset"
RESET_ARCHIVE_MANIFEST_VERSION = 1

ArchiveEntry = dict[str, Any]
ArchiveInspection = dict[str, Any]


def _relative_path(root: Path, path: Path) -> str:
    root_resolved = root.resolve()
    path_resolved = path.resolve()
    try:
        return str(path_resolved.relative_to(root_resolved))
    except ValueError:
        return str(path_resolved)


def reset_artifact_paths(
    project_root: Path,
    runtime_paths: Mapping[str, Path],
    *,
    demo_result_rel: str = "examples/_demo_result.json",
) -> list[tuple[str, Path]]:
    candidates = [
        ("state_file", runtime_paths["state_file"]),
        ("observations_csv", runtime_paths["observations_csv"]),
        ("acquisition_log_file", runtime_paths["acquisition_log_file"]),
        ("event_log_file", runtime_paths["event_log_file"]),
        ("lock_file", runtime_paths["lock_file"]),
        ("report_json_file", runtime_paths["report_json_file"]),
        ("report_md_file", runtime_paths["report_md_file"]),
        ("trials_dir", runtime_paths["trials_dir"]),
        ("demo_result_file", (project_root / demo_result_rel).resolve()),
    ]
    out: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for label, path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append((label, resolved))
    return out


def copy_path_to_archive(path: Path, destination: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.copytree(path, destination, dirs_exist_ok=True)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)


def _entry_path_type(path: Path) -> str:
    if path.is_dir() and not path.is_symlink():
        return "directory"
    return "file"


def build_reset_archive_manifest(
    project_root: Path,
    archive_root: Path,
    archived_paths: Sequence[tuple[str, Path]],
    *,
    created_at: float,
) -> ArchiveInspection:
    if not math.isfinite(created_at):
        raise ValueError(f"created_at must be finite, got: {created_at!r}")

    entries: list[ArchiveEntry] = []
    for label, path in archived_paths:
        source_rel = _relative_path(project_root, path)
        entries.append(
            {
                "label": label,
                "source_rel": source_rel,
                "archive_rel": source_rel,
                "path_type": _entry_path_type(path),
            }
        )

    return {
        "manifest_version": RESET_ARCHIVE_MANIFEST_VERSION,
        "archive_type": RESET_ARCHIVE_TYPE,
        "archive_id": archive_root.name,
        "created_at": float(created_at),
        "source_root": str(project_root.resolve()),
        "entries": entries,
    }


def write_archive_manifest(archive_root: Path, manifest: Mapping[str, Any]) -> Path:
    manifest_path = archive_root / ARCHIVE_MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(dict(manifest), indent=2) + "\n", encoding="utf-8")
    return manifest_path


def _inspect_legacy_reset_archive(
    archive_root: Path,
    *,
    project_root: Path,
    runtime_paths: Mapping[str, Path],
) -> ArchiveInspection:
    entries: list[ArchiveEntry] = []
    for label, path in reset_artifact_paths(project_root, runtime_paths):
        source_rel = _relative_path(project_root, path)
        archived_path = archive_root / source_rel
        if not archived_path.exists():
            continue
        entries.append(
            {
                "label": label,
                "source_rel": source_rel,
                "archive_rel": source_rel,
                "path_type": _entry_path_type(archived_path),
            }
        )
    return {
        "manifest_version": None,
        "archive_type": RESET_ARCHIVE_TYPE,
        "archive_id": archive_root.name,
        "created_at": None,
        "source_root": None,
        "entries": entries,
        "manifest_present": False,
        "legacy": True,
        "integrity_status": "legacy",
        "integrity_errors": [],
    }


def _normalize_manifest_entry(entry: Any, *, index: int) -> ArchiveEntry:
    if not isinstance(entry, dict):
        raise ValueError(f"archive manifest entry[{index}] must be an object")

    label = entry.get("label")
    if not isinstance(label, str) or not label:
        raise ValueError(f"archive manifest entry[{index}].label must be a non-empty string")

    source_rel = entry.get("source_rel")
    if not isinstance(source_rel, str) or not source_rel:
        raise ValueError(f"archive manifest entry[{index}].source_rel must be a non-empty string")

    archive_rel = entry.get("archive_rel")
    if not isinstance(archive_rel, str) or not archive_rel:
        raise ValueError(f"archive manifest entry[{index}].archive_rel must be a non-empty string")

    path_type = entry.get("path_type")
    if path_type not in {"file", "directory"}:
        raise ValueError(f"archive manifest entry[{index}].path_type must be 'file' or 'directory'")

    return {
        "label": label,
        "source_rel": source_rel,
        "archive_rel": archive_rel,
        "path_type": path_type,
    }


def inspect_reset_archive(
    archive_root: Path,
    *,
    project_root: Path,
    runtime_paths: Mapping[str, Path],
) -> ArchiveInspection:
    manifest_path = archive_root / ARCHIVE_MANIFEST_FILENAME
    if not manifest_path.exists():
        return _inspect_legacy_reset_archive(
            archive_root,
            project_root=project_root,
            runtime_paths=runtime_paths,
        )

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("archive manifest root must be an object")

        manifest_version = payload.get("manifest_version")
        if manifest_version != RESET_ARCHIVE_MANIFEST_VERSION:
            raise ValueError(
                f"archive manifest manifest_version must be {RESET_ARCHIVE_MANIFEST_VERSION}"
            )

        archive_type = payload.get("archive_type")
        if archive_type != RESET_ARCHIVE_TYPE:
            raise ValueError(f"archive manifest archive_type must be {RESET_ARCHIVE_TYPE!r}")

        archive_id = payload.get("archive_id")
        if not isinstance(archive_id, str) or not archive_id:
            raise ValueError("archive manifest archive_id must be a non-empty string")
        if archive_id != archive_root.name:
            raise ValueError(
                f"archive manifest archive_id {archive_id!r} does not match directory "
                f"name {archive_root.name!r}"
            )

        created_at = payload.get("created_at")
        if not isinstance(created_at, (int, float)) or isinstance(created_at, bool):
            raise ValueError("archive manifest created_at must be numeric")
        created_at = float(created_at)
        if not math.isfinite(created_at):
            raise ValueError("archive manifest created_at must be finite")

        source_root = payload.get("source_root")
        if not isinstance(source_root, str) or not source_root:
            raise ValueError("archive manifest source_root must be a non-empty string")

        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, list):
            raise ValueError("archive manifest entries must be a list")

        entries = [
            _normalize_manifest_entry(entry, index=index) for index, entry in enumerate(raw_entries)
        ]
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        return {
            "manifest_version": None,
            "archive_type": RESET_ARCHIVE_TYPE,
            "archive_id": archive_root.name,
            "created_at": None,
            "source_root": None,
            "entries": [],
            "manifest_present": True,
            "legacy": False,
            "integrity_status": "invalid_manifest",
            "integrity_errors": [str(exc)],
        }

    integrity_errors: list[str] = []
    for entry in entries:
        archived_path = archive_root / str(entry["archive_rel"])
        if not archived_path.exists():
            integrity_errors.append(
                f"missing archived path for {entry['label']}: {entry['archive_rel']}"
            )

    integrity_status = "ok" if not integrity_errors else "missing_files"
    return {
        "manifest_version": RESET_ARCHIVE_MANIFEST_VERSION,
        "archive_type": RESET_ARCHIVE_TYPE,
        "archive_id": archive_id,
        "created_at": created_at,
        "source_root": source_root,
        "entries": entries,
        "manifest_present": True,
        "legacy": False,
        "integrity_status": integrity_status,
        "integrity_errors": integrity_errors,
    }
