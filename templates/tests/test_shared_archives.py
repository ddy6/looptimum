from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ARCHIVES_MODULE = REPO_ROOT / "templates" / "_shared" / "archives.py"


def _load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load shared module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ARCHIVES = _load_module(ARCHIVES_MODULE, "looptimum_shared_archives_test")


def _runtime_paths(root: Path) -> dict[str, Path]:
    return {
        "state_file": root / "state" / "bo_state.json",
        "observations_csv": root / "state" / "observations.csv",
        "acquisition_log_file": root / "state" / "acquisition_log.jsonl",
        "event_log_file": root / "state" / "event_log.jsonl",
        "trials_dir": root / "state" / "trials",
        "lock_file": root / "state" / ".looptimum.lock",
        "report_json_file": root / "state" / "report.json",
        "report_md_file": root / "state" / "report.md",
    }


def _seed_runtime_artifacts(root: Path) -> dict[str, Path]:
    paths = _runtime_paths(root)
    paths["state_file"].parent.mkdir(parents=True, exist_ok=True)
    paths["state_file"].write_text('{"schema_version":"0.3.0"}\n', encoding="utf-8")
    paths["trials_dir"].mkdir(parents=True, exist_ok=True)
    (paths["trials_dir"] / "trial_1").mkdir(parents=True, exist_ok=True)
    (paths["trials_dir"] / "trial_1" / "manifest.json").write_text("{}", encoding="utf-8")
    demo_result_path = root / "examples" / "_demo_result.json"
    demo_result_path.parent.mkdir(parents=True, exist_ok=True)
    demo_result_path.write_text("{}\n", encoding="utf-8")
    return paths


def _copy_existing_reset_targets(
    root: Path,
    archive_root: Path,
    runtime_paths: dict[str, Path],
) -> list[tuple[str, Path]]:
    archived: list[tuple[str, Path]] = []
    for label, path in ARCHIVES.reset_artifact_paths(root, runtime_paths):
        if not path.exists():
            continue
        ARCHIVES.copy_path_to_archive(path, archive_root / path.relative_to(root))
        archived.append((label, path))
    return archived


def test_build_and_inspect_reset_archive_manifest_round_trips(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    runtime_paths = _seed_runtime_artifacts(root)
    archive_root = root / "state" / "reset_archives" / "reset-123"
    archive_root.mkdir(parents=True)

    archived = _copy_existing_reset_targets(root, archive_root, runtime_paths)
    manifest = ARCHIVES.build_reset_archive_manifest(
        root,
        archive_root,
        archived,
        created_at=123.0,
    )
    ARCHIVES.write_archive_manifest(archive_root, manifest)

    inspected = ARCHIVES.inspect_reset_archive(
        archive_root,
        project_root=root,
        runtime_paths=runtime_paths,
    )

    assert inspected["manifest_present"] is True
    assert inspected["legacy"] is False
    assert inspected["integrity_status"] == "ok"
    assert inspected["archive_id"] == "reset-123"
    assert inspected["created_at"] == 123.0
    assert inspected["source_root"] == str(root.resolve())
    assert {entry["source_rel"] for entry in inspected["entries"]} == {
        "state/bo_state.json",
        "state/trials",
        "examples/_demo_result.json",
    }


def test_inspect_reset_archive_discovers_manifestless_legacy_archives(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    runtime_paths = _seed_runtime_artifacts(root)
    archive_root = root / "state" / "reset_archives" / "reset-legacy"
    archive_root.mkdir(parents=True)

    _copy_existing_reset_targets(root, archive_root, runtime_paths)

    inspected = ARCHIVES.inspect_reset_archive(
        archive_root,
        project_root=root,
        runtime_paths=runtime_paths,
    )

    assert inspected["manifest_present"] is False
    assert inspected["legacy"] is True
    assert inspected["integrity_status"] == "legacy"
    assert inspected["integrity_errors"] == []
    assert {entry["label"] for entry in inspected["entries"]} == {
        "state_file",
        "trials_dir",
        "demo_result_file",
    }


def test_inspect_reset_archive_reports_missing_manifested_files(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    runtime_paths = _seed_runtime_artifacts(root)
    archive_root = root / "state" / "reset_archives" / "reset-broken"
    archive_root.mkdir(parents=True)

    archived = _copy_existing_reset_targets(root, archive_root, runtime_paths)
    manifest = ARCHIVES.build_reset_archive_manifest(
        root,
        archive_root,
        archived,
        created_at=456.0,
    )
    ARCHIVES.write_archive_manifest(archive_root, manifest)
    (archive_root / "state" / "bo_state.json").unlink()

    inspected = ARCHIVES.inspect_reset_archive(
        archive_root,
        project_root=root,
        runtime_paths=runtime_paths,
    )

    assert inspected["manifest_present"] is True
    assert inspected["legacy"] is False
    assert inspected["integrity_status"] == "missing_files"
    assert inspected["integrity_errors"] == [
        "missing archived path for state_file: state/bo_state.json"
    ]
