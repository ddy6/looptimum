from __future__ import annotations

import json
import math
import os
import shutil
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

ARCHIVE_MANIFEST_FILENAME = "archive_manifest.json"
RESET_ARCHIVE_TYPE = "reset"
RESET_ARCHIVE_MANIFEST_VERSION = 1
_RESTORE_FAIL_SOURCE_REL_ENV = "LOOPTIMUM_TEST_RESTORE_FAIL_SOURCE_REL"
_IGNORED_RESTORE_LABELS = frozenset({"lock_file"})

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


def restorable_artifact_paths(
    project_root: Path,
    runtime_paths: Mapping[str, Path],
    *,
    demo_result_rel: str = "examples/_demo_result.json",
) -> list[tuple[str, Path]]:
    return [
        (label, path)
        for label, path in reset_artifact_paths(
            project_root,
            runtime_paths,
            demo_result_rel=demo_result_rel,
        )
        if label not in _IGNORED_RESTORE_LABELS
    ]


def copy_path_to_archive(path: Path, destination: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.copytree(path, destination, dirs_exist_ok=True)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)


def reset_archives_root(runtime_paths: Mapping[str, Path]) -> Path:
    return runtime_paths["state_file"].parent / "reset_archives"


def resolve_reset_archive(
    archive_id: str,
    *,
    project_root: Path,
    runtime_paths: Mapping[str, Path],
) -> Path:
    archive_id = archive_id.strip()
    if not archive_id:
        raise ValueError("restore requires --archive-id")
    if archive_id != Path(archive_id).name or archive_id in {".", ".."}:
        raise ValueError("--archive-id must be a simple directory name")

    archives_root = reset_archives_root(runtime_paths).resolve()
    archive_root = (archives_root / archive_id).resolve()
    try:
        archive_root.relative_to(archives_root)
    except ValueError as exc:
        raise ValueError("--archive-id must resolve under state/reset_archives") from exc

    if not archive_root.exists() or not archive_root.is_dir():
        archives_root_rel = _relative_path(project_root, archives_root)
        raise ValueError(f"archive_id {archive_id!r} not found under {archives_root_rel}")

    return archive_root


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


def summarize_archive_entries(
    entries: Sequence[Mapping[str, Any]],
    *,
    preview_limit: int = 5,
) -> ArchiveInspection:
    inventory_paths = sorted(
        source_rel
        for entry in entries
        for source_rel in [entry.get("source_rel")]
        if isinstance(source_rel, str) and source_rel
    )
    file_count = sum(1 for entry in entries if entry.get("path_type") == "file")
    directory_count = sum(1 for entry in entries if entry.get("path_type") == "directory")
    preview_paths = inventory_paths[:preview_limit]
    return {
        "entry_count": len(inventory_paths),
        "file_count": file_count,
        "directory_count": directory_count,
        "preview_paths": preview_paths,
        "remaining_entry_count": max(0, len(inventory_paths) - len(preview_paths)),
    }


def list_reset_archives(
    project_root: Path,
    runtime_paths: Mapping[str, Path],
    *,
    preview_limit: int = 5,
) -> list[ArchiveInspection]:
    archives_root = reset_archives_root(runtime_paths)
    if not archives_root.exists() or not archives_root.is_dir():
        return []

    archives: list[ArchiveInspection] = []
    for archive_root in (path for path in archives_root.iterdir() if path.is_dir()):
        archive = inspect_reset_archive(
            archive_root,
            project_root=project_root,
            runtime_paths=runtime_paths,
        )
        archive["archive_rel"] = _relative_path(project_root, archive_root)
        archive.update(summarize_archive_entries(archive["entries"], preview_limit=preview_limit))
        archives.append(archive)

    def _archive_sort_key(archive: Mapping[str, Any]) -> tuple[float, str]:
        created_at = archive.get("created_at")
        if isinstance(created_at, (int, float)) and not isinstance(created_at, bool):
            created_at_value = float(created_at)
            if math.isfinite(created_at_value):
                return (created_at_value, str(archive.get("archive_id") or ""))
        return (float("-inf"), str(archive.get("archive_id") or ""))

    archives.sort(key=_archive_sort_key, reverse=True)
    return archives


def archive_created_at_seconds(archive: Mapping[str, Any]) -> float | None:
    created_at = archive.get("created_at")
    if not isinstance(created_at, (int, float)) or isinstance(created_at, bool):
        return None
    created_at_value = float(created_at)
    if not math.isfinite(created_at_value):
        return None
    return created_at_value


def format_archive_created_at(created_at: Any) -> str:
    created_at_value = archive_created_at_seconds({"created_at": created_at})
    if created_at_value is None:
        return "unknown"
    return time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(created_at_value))


def render_reset_archive_listing(
    archives: Sequence[Mapping[str, Any]],
    *,
    archives_root_rel: str,
) -> list[str]:
    if not archives:
        return [f"No reset archives found under {archives_root_rel}."]

    lines = [f"Found {len(archives)} reset archive(s) under {archives_root_rel}:"]
    for archive in archives:
        archive_id = str(archive.get("archive_id") or "<unknown>")
        integrity_status = str(archive.get("integrity_status") or "unknown")
        archive_kind = "legacy" if archive.get("legacy") else "manifest"
        created_at_text = format_archive_created_at(archive.get("created_at"))
        entry_count = int(archive.get("entry_count", 0) or 0)
        lines.append(
            f"- {archive_id} | status={integrity_status} | kind={archive_kind} "
            f"| created_at={created_at_text} | entries={entry_count}"
        )

        archive_rel = archive.get("archive_rel")
        if isinstance(archive_rel, str) and archive_rel:
            lines.append(f"  path: {archive_rel}")

        preview_paths = archive.get("preview_paths")
        inventory_line = "(empty)"
        if isinstance(preview_paths, list) and preview_paths:
            inventory_line = ", ".join(str(path) for path in preview_paths)
            remaining_entry_count = int(archive.get("remaining_entry_count", 0) or 0)
            if remaining_entry_count > 0:
                inventory_line += f" (+{remaining_entry_count} more)"
        lines.append(f"  inventory: {inventory_line}")

        integrity_errors = archive.get("integrity_errors")
        if isinstance(integrity_errors, list):
            for error in integrity_errors:
                if isinstance(error, str) and error:
                    lines.append(f"  integrity_error: {error}")
    return lines


def _remove_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
        return
    path.unlink()


def _restorable_path_map(
    project_root: Path,
    runtime_paths: Mapping[str, Path],
) -> dict[str, tuple[str, Path]]:
    return {
        _relative_path(project_root, path): (label, path)
        for label, path in restorable_artifact_paths(project_root, runtime_paths)
    }


def _ignored_restore_paths(
    project_root: Path,
    runtime_paths: Mapping[str, Path],
) -> set[str]:
    return {
        _relative_path(project_root, path)
        for label, path in reset_artifact_paths(project_root, runtime_paths)
        if label in _IGNORED_RESTORE_LABELS
    }


def _build_restore_entries(
    archive_root: Path,
    archive: Mapping[str, Any],
    *,
    project_root: Path,
    runtime_paths: Mapping[str, Path],
) -> tuple[list[ArchiveEntry], list[str]]:
    restorable_paths = _restorable_path_map(project_root, runtime_paths)
    ignored_paths = _ignored_restore_paths(project_root, runtime_paths)

    raw_entries = archive.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("archive inspection entries must be a list")

    restore_entries: list[ArchiveEntry] = []
    ignored: list[str] = []
    errors: list[str] = []
    seen_paths: set[str] = set()
    for index, entry in enumerate(raw_entries):
        if not isinstance(entry, dict):
            errors.append(f"archive entry[{index}] must be an object")
            continue

        source_rel = entry.get("source_rel")
        archive_rel = entry.get("archive_rel")
        path_type = entry.get("path_type")
        if not isinstance(source_rel, str) or not source_rel:
            errors.append(f"archive entry[{index}] has invalid source_rel")
            continue
        if not isinstance(archive_rel, str) or not archive_rel:
            errors.append(f"archive entry[{index}] has invalid archive_rel")
            continue

        if source_rel in ignored_paths:
            ignored.append(source_rel)
            continue
        if source_rel in seen_paths:
            errors.append(f"duplicate archived runtime path for restore: {source_rel}")
            continue

        mapping = restorable_paths.get(source_rel)
        if mapping is None:
            errors.append(f"unsupported archived path for restore: {source_rel}")
            continue

        label, target_path = mapping
        restore_entries.append(
            {
                "label": label,
                "source_rel": source_rel,
                "archive_rel": archive_rel,
                "path_type": path_type,
                "archive_path": archive_root / archive_rel,
                "target_path": target_path,
            }
        )
        seen_paths.add(source_rel)

    if errors:
        raise ValueError("; ".join(errors))
    if not restore_entries:
        raise ValueError("archive contains no restorable runtime artifacts")

    return restore_entries, sorted(set(ignored))


def _stage_restore_entries(entries: Sequence[Mapping[str, Any]], staging_root: Path) -> None:
    for entry in entries:
        source_rel = str(entry["source_rel"])
        archived_path = Path(entry["archive_path"])
        copy_path_to_archive(archived_path, staging_root / source_rel)


def _backup_restore_targets(entries: Sequence[Mapping[str, Any]], backup_root: Path) -> list[str]:
    overwritten_paths: list[str] = []
    for entry in entries:
        source_rel = str(entry["source_rel"])
        target_path = Path(entry["target_path"])
        if not target_path.exists() and not target_path.is_symlink():
            continue
        copy_path_to_archive(target_path, backup_root / source_rel)
        overwritten_paths.append(source_rel)
    return overwritten_paths


def _remove_restore_targets(entries: Sequence[Mapping[str, Any]]) -> None:
    for entry in entries:
        _remove_path(Path(entry["target_path"]))


def _apply_restore_entries(entries: Sequence[Mapping[str, Any]], staging_root: Path) -> None:
    fail_source_rel = os.getenv(_RESTORE_FAIL_SOURCE_REL_ENV, "").strip()
    for entry in entries:
        source_rel = str(entry["source_rel"])
        if fail_source_rel and source_rel == fail_source_rel:
            raise OSError(f"Injected restore failure for {source_rel}")
        copy_path_to_archive(staging_root / source_rel, Path(entry["target_path"]))


def _restore_backup(entries: Sequence[Mapping[str, Any]], backup_root: Path) -> None:
    for entry in entries:
        source_rel = str(entry["source_rel"])
        backup_path = backup_root / source_rel
        if not backup_path.exists() and not backup_path.is_symlink():
            continue
        copy_path_to_archive(backup_path, Path(entry["target_path"]))


def restore_reset_archive(
    archive_id: str,
    *,
    project_root: Path,
    runtime_paths: Mapping[str, Path],
) -> ArchiveInspection:
    archive_root = resolve_reset_archive(
        archive_id,
        project_root=project_root,
        runtime_paths=runtime_paths,
    )
    archive = inspect_reset_archive(
        archive_root,
        project_root=project_root,
        runtime_paths=runtime_paths,
    )
    integrity_status = str(archive.get("integrity_status") or "unknown")
    if integrity_status not in {"ok", "legacy"}:
        raise ValueError(
            f"archive_id {archive_id!r} is not restorable: integrity_status={integrity_status}"
        )

    restore_entries, ignored_paths = _build_restore_entries(
        archive_root,
        archive,
        project_root=project_root,
        runtime_paths=runtime_paths,
    )

    state_root = runtime_paths["state_file"].parent.resolve()
    nonce = f"{time.time_ns()}-{os.getpid()}"
    staging_root = state_root / f".restore-staging-{nonce}"
    backup_root = state_root / f".restore-backup-{nonce}"
    overwritten_paths: list[str] = []

    try:
        _stage_restore_entries(restore_entries, staging_root)
        overwritten_paths = _backup_restore_targets(restore_entries, backup_root)
        _remove_restore_targets(restore_entries)
        _apply_restore_entries(restore_entries, staging_root)
    except Exception:
        _remove_restore_targets(restore_entries)
        _restore_backup(restore_entries, backup_root)
        raise
    finally:
        _remove_path(staging_root)
        _remove_path(backup_root)

    return {
        "archive_id": str(archive["archive_id"]),
        "archive_rel": _relative_path(project_root, archive_root),
        "legacy": bool(archive.get("legacy")),
        "integrity_status": integrity_status,
        "restored_paths": [str(entry["source_rel"]) for entry in restore_entries],
        "overwritten_paths": overwritten_paths,
        "ignored_paths": ignored_paths,
    }


def plan_reset_archive_prune(
    project_root: Path,
    runtime_paths: Mapping[str, Path],
    *,
    keep_last: int | None = None,
    older_than_seconds: float | None = None,
    now: float | None = None,
) -> ArchiveInspection:
    if keep_last is None and older_than_seconds is None:
        raise ValueError("prune-archives requires --keep-last and/or --older-than-seconds")
    if keep_last is not None and keep_last < 0:
        raise ValueError("--keep-last must be >= 0")
    if older_than_seconds is not None:
        if not math.isfinite(older_than_seconds) or older_than_seconds < 0:
            raise ValueError("--older-than-seconds must be a finite value >= 0")

    reference_time = time.time() if now is None else float(now)
    if not math.isfinite(reference_time):
        raise ValueError("prune reference time must be finite")

    archives = list_reset_archives(project_root, runtime_paths)
    prunable: list[ArchiveInspection] = []
    kept: list[ArchiveInspection] = []
    kept_due_to_unknown_age: list[ArchiveInspection] = []

    for index, archive in enumerate(archives):
        keep_by_count = keep_last is not None and index < keep_last
        if keep_by_count:
            kept.append(archive)
            continue

        created_at = archive_created_at_seconds(archive)
        if older_than_seconds is not None:
            if created_at is None:
                kept.append(archive)
                kept_due_to_unknown_age.append(archive)
                continue
            archive_age_seconds = max(0.0, reference_time - created_at)
            if archive_age_seconds < older_than_seconds:
                kept.append(archive)
                continue

        prunable.append(archive)

    prunable_ids = [str(archive["archive_id"]) for archive in prunable]
    return {
        "criteria": {
            "keep_last": keep_last,
            "older_than_seconds": older_than_seconds,
            "now": reference_time,
        },
        "archives": archives,
        "prunable_archives": prunable,
        "prunable_archive_ids": prunable_ids,
        "kept_archives": kept,
        "kept_archive_ids": [str(archive["archive_id"]) for archive in kept],
        "kept_due_to_unknown_age": [
            str(archive["archive_id"]) for archive in kept_due_to_unknown_age
        ],
    }


def prune_reset_archives(
    project_root: Path,
    runtime_paths: Mapping[str, Path],
    *,
    keep_last: int | None = None,
    older_than_seconds: float | None = None,
    now: float | None = None,
) -> ArchiveInspection:
    plan = plan_reset_archive_prune(
        project_root,
        runtime_paths,
        keep_last=keep_last,
        older_than_seconds=older_than_seconds,
        now=now,
    )
    pruned_paths: list[str] = []
    for archive in plan["prunable_archives"]:
        archive_root = resolve_reset_archive(
            str(archive["archive_id"]),
            project_root=project_root,
            runtime_paths=runtime_paths,
        )
        _remove_path(archive_root)
        pruned_paths.append(_relative_path(project_root, archive_root))

    return {
        **plan,
        "pruned_count": len(pruned_paths),
        "pruned_paths": pruned_paths,
    }
