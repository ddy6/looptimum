from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

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


def _write_manifest_archive(
    root: Path,
    runtime_paths: dict[str, Path],
    archive_id: str,
    *,
    created_at: float,
) -> Path:
    archive_root = root / "state" / "reset_archives" / archive_id
    archive_root.mkdir(parents=True, exist_ok=True)
    archived = _copy_existing_reset_targets(root, archive_root, runtime_paths)
    manifest = ARCHIVES.build_reset_archive_manifest(
        root,
        archive_root,
        archived,
        created_at=created_at,
    )
    ARCHIVES.write_archive_manifest(archive_root, manifest)
    return archive_root


def _write_legacy_archive(
    root: Path,
    runtime_paths: dict[str, Path],
    archive_id: str,
) -> Path:
    archive_root = root / "state" / "reset_archives" / archive_id
    archive_root.mkdir(parents=True, exist_ok=True)
    _copy_existing_reset_targets(root, archive_root, runtime_paths)
    return archive_root


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


def test_list_reset_archives_summarizes_manifest_and_legacy_archives(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    runtime_paths = _seed_runtime_artifacts(root)
    archives_root = root / "state" / "reset_archives"

    legacy_root = archives_root / "reset-legacy"
    legacy_root.mkdir(parents=True)
    _copy_existing_reset_targets(root, legacy_root, runtime_paths)

    manifest_root = archives_root / "reset-999"
    manifest_root.mkdir(parents=True)
    archived = _copy_existing_reset_targets(root, manifest_root, runtime_paths)
    manifest = ARCHIVES.build_reset_archive_manifest(
        root,
        manifest_root,
        archived,
        created_at=999.0,
    )
    ARCHIVES.write_archive_manifest(manifest_root, manifest)

    archives = ARCHIVES.list_reset_archives(root, runtime_paths, preview_limit=2)

    assert [archive["archive_id"] for archive in archives] == ["reset-999", "reset-legacy"]
    assert archives[0]["archive_rel"] == "state/reset_archives/reset-999"
    assert archives[0]["integrity_status"] == "ok"
    assert archives[0]["entry_count"] == 3
    assert archives[0]["remaining_entry_count"] == 1
    assert archives[0]["preview_paths"] == [
        "examples/_demo_result.json",
        "state/bo_state.json",
    ]
    assert archives[1]["legacy"] is True
    assert archives[1]["integrity_status"] == "legacy"


def test_render_reset_archive_listing_handles_empty_and_broken_archives() -> None:
    assert ARCHIVES.render_reset_archive_listing([], archives_root_rel="state/reset_archives") == [
        "No reset archives found under state/reset_archives."
    ]

    lines = ARCHIVES.render_reset_archive_listing(
        [
            {
                "archive_id": "reset-bad",
                "archive_rel": "state/reset_archives/reset-bad",
                "legacy": False,
                "integrity_status": "invalid_manifest",
                "created_at": None,
                "entry_count": 0,
                "preview_paths": [],
                "remaining_entry_count": 0,
                "integrity_errors": ["archive manifest root must be an object"],
            }
        ],
        archives_root_rel="state/reset_archives",
    )

    assert lines[0] == "Found 1 reset archive(s) under state/reset_archives:"
    assert any(
        "reset-bad | status=invalid_manifest | kind=manifest | created_at=unknown | entries=0"
        in line
        for line in lines
    )
    assert "  path: state/reset_archives/reset-bad" in lines
    assert "  inventory: (empty)" in lines
    assert "  integrity_error: archive manifest root must be an object" in lines


def test_restore_reset_archive_round_trips_and_ignores_lock_file(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    runtime_paths = _seed_runtime_artifacts(root)
    runtime_paths["lock_file"].write_text("current-lock\n", encoding="utf-8")
    archive_root = root / "state" / "reset_archives" / "reset-restore"
    archive_root.mkdir(parents=True)

    archived = _copy_existing_reset_targets(root, archive_root, runtime_paths)
    manifest = ARCHIVES.build_reset_archive_manifest(
        root,
        archive_root,
        archived,
        created_at=777.0,
    )
    ARCHIVES.write_archive_manifest(archive_root, manifest)

    archived_state_text = (archive_root / "state" / "bo_state.json").read_text(encoding="utf-8")
    archived_demo_text = (archive_root / "examples" / "_demo_result.json").read_text(
        encoding="utf-8"
    )
    archived_trial_manifest_text = (
        archive_root / "state" / "trials" / "trial_1" / "manifest.json"
    ).read_text(encoding="utf-8")

    runtime_paths["state_file"].write_text(
        '{"schema_version":"0.3.0","marker":"current"}\n', encoding="utf-8"
    )
    shutil.rmtree(runtime_paths["trials_dir"])
    (runtime_paths["trials_dir"] / "trial_current").mkdir(parents=True, exist_ok=True)
    (runtime_paths["trials_dir"] / "trial_current" / "manifest.json").write_text(
        '{"marker":"current"}\n',
        encoding="utf-8",
    )
    (root / "examples" / "_demo_result.json").write_text('{"marker":"current"}\n', encoding="utf-8")

    restored = ARCHIVES.restore_reset_archive(
        "reset-restore",
        project_root=root,
        runtime_paths=runtime_paths,
    )

    assert restored["archive_rel"] == "state/reset_archives/reset-restore"
    assert restored["integrity_status"] == "ok"
    assert restored["ignored_paths"] == ["state/.looptimum.lock"]
    assert runtime_paths["state_file"].read_text(encoding="utf-8") == archived_state_text
    assert (root / "examples" / "_demo_result.json").read_text(
        encoding="utf-8"
    ) == archived_demo_text
    assert (runtime_paths["trials_dir"] / "trial_1" / "manifest.json").read_text(
        encoding="utf-8"
    ) == archived_trial_manifest_text
    assert runtime_paths["lock_file"].read_text(encoding="utf-8") == "current-lock\n"


def test_restore_reset_archive_rolls_back_on_injected_apply_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    runtime_paths = _seed_runtime_artifacts(root)
    archive_root = root / "state" / "reset_archives" / "reset-rollback"
    archive_root.mkdir(parents=True)

    archived = _copy_existing_reset_targets(root, archive_root, runtime_paths)
    manifest = ARCHIVES.build_reset_archive_manifest(
        root,
        archive_root,
        archived,
        created_at=888.0,
    )
    ARCHIVES.write_archive_manifest(archive_root, manifest)

    current_state_text = '{"schema_version":"0.3.0","marker":"current"}\n'
    runtime_paths["state_file"].write_text(current_state_text, encoding="utf-8")
    shutil.rmtree(runtime_paths["trials_dir"])
    (runtime_paths["trials_dir"] / "trial_current").mkdir(parents=True, exist_ok=True)
    current_manifest_text = '{"marker":"current"}\n'
    (runtime_paths["trials_dir"] / "trial_current" / "manifest.json").write_text(
        current_manifest_text,
        encoding="utf-8",
    )
    current_demo_text = '{"marker":"current"}\n'
    (root / "examples" / "_demo_result.json").write_text(current_demo_text, encoding="utf-8")

    monkeypatch.setenv("LOOPTIMUM_TEST_RESTORE_FAIL_SOURCE_REL", "state/trials")
    with pytest.raises(OSError, match="Injected restore failure for state/trials"):
        ARCHIVES.restore_reset_archive(
            "reset-rollback",
            project_root=root,
            runtime_paths=runtime_paths,
        )
    monkeypatch.delenv("LOOPTIMUM_TEST_RESTORE_FAIL_SOURCE_REL", raising=False)

    assert runtime_paths["state_file"].read_text(encoding="utf-8") == current_state_text
    assert (runtime_paths["trials_dir"] / "trial_current" / "manifest.json").read_text(
        encoding="utf-8"
    ) == current_manifest_text
    assert (root / "examples" / "_demo_result.json").read_text(
        encoding="utf-8"
    ) == current_demo_text


def test_plan_reset_archive_prune_with_age_keeps_unknown_age_legacy_archives(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    runtime_paths = _seed_runtime_artifacts(root)
    _write_manifest_archive(root, runtime_paths, "reset-old", created_at=100.0)
    _write_manifest_archive(root, runtime_paths, "reset-new", created_at=200.0)
    _write_legacy_archive(root, runtime_paths, "reset-legacy")

    plan = ARCHIVES.plan_reset_archive_prune(
        root,
        runtime_paths,
        older_than_seconds=750.0,
        now=1_000.0,
    )

    assert plan["prunable_archive_ids"] == ["reset-new", "reset-old"]
    assert plan["kept_due_to_unknown_age"] == ["reset-legacy"]
    assert plan["kept_archive_ids"] == ["reset-legacy"]


def test_prune_reset_archives_keep_last_prunes_older_archives(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    runtime_paths = _seed_runtime_artifacts(root)
    _write_manifest_archive(root, runtime_paths, "reset-old", created_at=100.0)
    kept_archive = _write_manifest_archive(root, runtime_paths, "reset-new", created_at=200.0)
    _write_legacy_archive(root, runtime_paths, "reset-legacy")

    result = ARCHIVES.prune_reset_archives(root, runtime_paths, keep_last=1, now=1_000.0)

    assert result["prunable_archive_ids"] == ["reset-old", "reset-legacy"]
    assert result["pruned_count"] == 2
    assert kept_archive.exists()
    assert not (root / "state" / "reset_archives" / "reset-old").exists()
    assert not (root / "state" / "reset_archives" / "reset-legacy").exists()
