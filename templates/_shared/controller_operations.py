"""Equivalent CLI reporting and lifecycle operations shared by all templates.

Backend-specific state, objective and report construction stay in each entrypoint;
this module owns the identical orchestration and publication order only.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import shutil
import sys
import time
from pathlib import Path
from typing import Any, ContextManager, Mapping, Protocol, Sequence

JSONDict = dict[str, Any]
PathMap = dict[str, Path]
ArchiveEntry = dict[str, Any]
ArchiveInspection = dict[str, Any]


class LockHandle(Protocol):
    wait_seconds: float


class ControllerHooks(Protocol):
    def _append_event(self, paths: PathMap, event: str, **fields: Any) -> None: ...

    def _append_governance_override_events_for_observations(
        self,
        paths: PathMap,
        cfg: JSONDict,
        *,
        command: str,
        observations: list[JSONDict],
        source: str,
    ) -> None: ...

    def _append_governance_violation_event(
        self, root: Path, paths: PathMap, state: JSONDict, cfg: JSONDict, *, command: str
    ) -> None: ...

    def _build_health_payload(self, args: argparse.Namespace) -> tuple[JSONDict, int]: ...

    def _build_metrics_payload(self, args: argparse.Namespace) -> tuple[JSONDict, int]: ...

    def _build_report_payload(
        self, *, state: JSONDict, objective_cfg: JSONDict, top_n: int
    ) -> JSONDict: ...

    def _ensure_terminal_manifest(
        self,
        root: Path,
        paths: PathMap,
        observation: JSONDict,
        *,
        objective_cfg: JSONDict,
        payload_copy_path: Path | None,
        now: float,
    ) -> None: ...

    def _load_objective_config(self, root: Path, cfg: JSONDict) -> JSONDict: ...

    def _new_terminal_observation(
        self, pending: JSONDict, *, objective_cfg: JSONDict, terminal_reason: str, now: float
    ) -> JSONDict: ...

    def _pop_pending(self, state: JSONDict, trial_id: int) -> JSONDict | None: ...

    def _render_report_markdown(self, report: JSONDict) -> str: ...

    def _runtime_paths(self, root: Path, cfg: JSONDict) -> PathMap: ...

    def _save_state_and_rows(self, paths: PathMap, state: JSONDict) -> None: ...

    def atomic_write_json(self, path: Path, payload: Any, *, indent: int = 2) -> None: ...

    def atomic_write_text(self, path: Path, text: str) -> None: ...

    def build_reset_archive_manifest(
        self,
        project_root: Path,
        archive_root: Path,
        archived_paths: Sequence[tuple[str, Path]],
        *,
        created_at: float,
    ) -> ArchiveInspection: ...

    def copy_path_to_archive(self, path: Path, destination: Path) -> None: ...

    def hold_exclusive_lock(
        self, path: Path, *, timeout_seconds: float, fail_fast: bool = False
    ) -> ContextManager[LockHandle]: ...

    def list_reset_archives(
        self, project_root: Path, runtime_paths: Mapping[str, Path], *, preview_limit: int = 5
    ) -> list[ArchiveInspection]: ...

    def load_contract_document(self, project_root: Path, stem: str) -> tuple[Any, Path]: ...

    def load_state(self, path: Path) -> JSONDict: ...

    def render_reset_archive_listing(
        self, archives: Sequence[Mapping[str, Any]], *, archives_root_rel: str
    ) -> list[str]: ...

    def reset_archives_root(self, runtime_paths: Mapping[str, Path]) -> Path: ...

    def reset_artifact_paths(
        self,
        project_root: Path,
        runtime_paths: Mapping[str, Path],
        *,
        demo_result_rel: str = "examples/_demo_result.json",
    ) -> list[tuple[str, Path]]: ...

    def resolve_lock_timeout_seconds(
        self, cfg: dict[str, Any], cli_override: float | None = None
    ) -> float: ...

    def restore_reset_archive(
        self, archive_id: str, *, project_root: Path, runtime_paths: Mapping[str, Path]
    ) -> ArchiveInspection: ...

    def update_best(self, state: JSONDict, objective_cfg: JSONDict) -> None: ...

    def write_archive_manifest(self, archive_root: Path, manifest: Mapping[str, Any]) -> Path: ...


def _relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _confirm_reset(args: argparse.Namespace, *, root: Path, archive_enabled: bool) -> None:
    if args.yes:
        return
    if not sys.stdin.isatty():
        raise ValueError("reset is destructive; re-run with --yes for non-interactive use")

    archive_label = "enabled" if archive_enabled else "disabled"
    print(f"Reset will remove runtime artifacts under {root} (archive={archive_label}).")
    print("Type RESET to continue: ", end="", flush=True)
    token = sys.stdin.readline().strip()
    if token != "RESET":
        raise ValueError("reset aborted: confirmation token mismatch")


def _confirm_restore(args: argparse.Namespace, *, root: Path, archive_id: str) -> None:
    if args.yes:
        return
    if not sys.stdin.isatty():
        raise ValueError("restore is destructive; re-run with --yes for non-interactive use")

    print(f"Restore will overwrite runtime artifacts under {root} from archive {archive_id}.")
    print("Type RESTORE to continue: ", end="", flush=True)
    token = sys.stdin.readline().strip()
    if token != "RESTORE":
        raise ValueError("restore aborted: confirmation token mismatch")


def _confirm_prune(args: argparse.Namespace, *, root: Path) -> None:
    if args.yes:
        return
    if not sys.stdin.isatty():
        raise ValueError("prune-archives is destructive; re-run with --yes for non-interactive use")

    print(
        f"Prune will permanently delete reset archives under {root / 'state' / 'reset_archives'}."
    )
    print("Type PRUNE to continue: ", end="", flush=True)
    token = sys.stdin.readline().strip()
    if token != "PRUNE":
        raise ValueError("prune-archives aborted: confirmation token mismatch")


def _require_finite_number(value: Any, *, field_name: str, trial_id: int) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"trial_id {trial_id}: {field_name} must be a finite number")
    try:
        out = float(value)
    except OverflowError as exc:
        raise ValueError(f"{field_name} must be finite for trial_id={trial_id}") from exc
    if not math.isfinite(out):
        raise ValueError(f"trial_id {trial_id}: {field_name} must be a finite number")
    return out


def _validate_jsonl_file_hard(path: Path, *, label: str) -> list[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        return [f"{label} unreadable: {exc}"]

    errors: list[str] = []
    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception as exc:
            errors.append(f"{label} line {idx} invalid JSON: {exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"{label} line {idx} must be a JSON object")
    return errors


def _normalize_lease_token(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string when present")
    return value.strip()


def _parse_cli_lease_token(raw: str | None) -> str | None:
    return _normalize_lease_token(raw, field_name="--lease-token")


def _build_lease_token() -> str:
    return secrets.token_hex(16)


def cmd_cancel(args: argparse.Namespace, *, api: ControllerHooks) -> None:
    if args.trial_id is None:
        raise ValueError("cancel requires --trial-id")
    root = Path(args.project_root).resolve()
    cfg, _ = api.load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")
    obj_cfg = api._load_objective_config(root, cfg)
    paths = api._runtime_paths(root, cfg)
    lock_timeout = api.resolve_lock_timeout_seconds(cfg, args.lock_timeout_seconds)
    with api.hold_exclusive_lock(
        paths["lock_file"], timeout_seconds=lock_timeout, fail_fast=args.fail_fast
    ) as lock:
        api._append_event(
            paths,
            "lock_acquired",
            command="cancel",
            pid=os.getpid(),
            wait_seconds=lock.wait_seconds,
        )
        try:
            state = api.load_state(paths["state_file"])
            pending_entry = api._pop_pending(state, int(args.trial_id))
            if pending_entry is None:
                raise ValueError(f"trial_id {args.trial_id} is not pending")
            now = time.time()
            terminal_reason = args.reason or "canceled"
            observation = api._new_terminal_observation(
                pending_entry, objective_cfg=obj_cfg, terminal_reason=terminal_reason, now=now
            )
            state["observations"].append(observation)
            api.update_best(state, obj_cfg)
            api._ensure_terminal_manifest(
                root, paths, observation, objective_cfg=obj_cfg, payload_copy_path=None, now=now
            )
            api._save_state_and_rows(paths, state)
            api._append_event(
                paths, "trial_canceled", trial_id=observation["trial_id"], reason=terminal_reason
            )
            api._append_governance_override_events_for_observations(
                paths, cfg, command="cancel", observations=[observation], source="manual_cancel"
            )
            api._append_governance_violation_event(root, paths, state, cfg, command="cancel")
            print(f"Canceled trial_id={observation['trial_id']}. Pending={len(state['pending'])}")
        finally:
            api._append_event(paths, "lock_released", command="cancel", pid=os.getpid())


def cmd_report(args: argparse.Namespace, *, api: ControllerHooks) -> None:
    root = Path(args.project_root).resolve()
    cfg, _ = api.load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")
    obj_cfg = api._load_objective_config(root, cfg)
    paths = api._runtime_paths(root, cfg)
    lock_timeout = api.resolve_lock_timeout_seconds(cfg, args.lock_timeout_seconds)
    with api.hold_exclusive_lock(
        paths["lock_file"], timeout_seconds=lock_timeout, fail_fast=args.fail_fast
    ) as lock:
        api._append_event(
            paths,
            "lock_acquired",
            command="report",
            pid=os.getpid(),
            wait_seconds=lock.wait_seconds,
        )
        try:
            state = api.load_state(paths["state_file"])
            report = api._build_report_payload(
                state=state, objective_cfg=obj_cfg, top_n=max(1, int(args.top_n))
            )
            api.atomic_write_json(paths["report_json_file"], report, indent=2)
            api.atomic_write_text(paths["report_md_file"], api._render_report_markdown(report))
            api._append_event(
                paths,
                "report_generated",
                report_json=_relative_path(root, paths["report_json_file"]),
                report_md=_relative_path(root, paths["report_md_file"]),
            )
            api._append_governance_violation_event(root, paths, state, cfg, command="report")
            print(
                f"Generated report files:\n- {paths['report_json_file']}\n- {paths['report_md_file']}"
            )
        finally:
            api._append_event(paths, "lock_released", command="report", pid=os.getpid())


def cmd_reset(args: argparse.Namespace, *, api: ControllerHooks) -> None:
    root = Path(args.project_root).resolve()
    cfg, _ = api.load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")
    paths = api._runtime_paths(root, cfg)
    archive_enabled = True if args.archive is None else bool(args.archive)
    _confirm_reset(args, root=root, archive_enabled=archive_enabled)
    targets = api.reset_artifact_paths(root, paths)
    lock_timeout = api.resolve_lock_timeout_seconds(cfg, args.lock_timeout_seconds)
    with api.hold_exclusive_lock(
        paths["lock_file"], timeout_seconds=lock_timeout, fail_fast=args.fail_fast
    ) as lock:
        api._append_event(
            paths, "lock_acquired", command="reset", pid=os.getpid(), wait_seconds=lock.wait_seconds
        )
        try:
            archive_root: Path | None = None
            archived: list[tuple[str, str]] = []
            archived_sources: list[tuple[str, Path]] = []
            if archive_enabled:
                archive_stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
                archive_root = (
                    paths["state_file"].parent
                    / "reset_archives"
                    / f"reset-{archive_stamp}-{time.time_ns()}"
                ).resolve()
                archive_root.mkdir(parents=True, exist_ok=False)
                for label, path in targets:
                    if not path.exists():
                        continue
                    rel = _relative_path(root, path)
                    dst = archive_root / rel
                    api.copy_path_to_archive(path, dst)
                    archived.append((rel, _relative_path(root, dst)))
                    archived_sources.append((label, path))
                manifest = api.build_reset_archive_manifest(
                    root, archive_root, archived_sources, created_at=time.time()
                )
                api.write_archive_manifest(archive_root, manifest)
            removed: list[str] = []
            missing: list[str] = []
            for _, path in targets:
                rel = _relative_path(root, path)
                if not path.exists():
                    missing.append(rel)
                    continue
                if path.is_dir() and (not path.is_symlink()):
                    shutil.rmtree(path)
                else:
                    path.unlink()
                removed.append(rel)
            archive_rel = _relative_path(root, archive_root) if archive_root is not None else None
            api._append_event(
                paths,
                "campaign_reset",
                archive_enabled=archive_enabled,
                archive_path=archive_rel,
                removed_count=len(removed),
                missing_count=len(missing),
            )
            api._append_governance_violation_event(
                root, paths, api.load_state(paths["state_file"]), cfg, command="reset"
            )
            print("Campaign reset completed.")
            if archive_enabled:
                print(f"Archive: {archive_rel}")
            else:
                print("Archive: disabled")
            if archived:
                print("Archived artifacts:")
                for src_rel, dst_rel in archived:
                    print(f"- {src_rel} -> {dst_rel}")
            elif archive_enabled:
                print("Archived artifacts:")
                print("- (none)")
            print("Removed artifacts:")
            if removed:
                for rel in removed:
                    print(f"- {rel}")
            else:
                print("- (none)")
            if missing:
                print("Already absent:")
                for rel in missing:
                    print(f"- {rel}")
            if archive_root is not None:
                print("Restore hint:")
                print(
                    f"- python3 run_bo.py restore --project-root {root} --archive-id {archive_root.name} --yes"
                )
        finally:
            api._append_event(paths, "lock_released", command="reset", pid=os.getpid())


def cmd_list_archives(args: argparse.Namespace, *, api: ControllerHooks) -> None:
    root = Path(args.project_root).resolve()
    cfg, _ = api.load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")
    paths = api._runtime_paths(root, cfg)
    archives = api.list_reset_archives(root, paths)
    archives_root_rel = _relative_path(root, api.reset_archives_root(paths))
    for line in api.render_reset_archive_listing(archives, archives_root_rel=archives_root_rel):
        print(line)


def cmd_restore(args: argparse.Namespace, *, api: ControllerHooks) -> None:
    if args.archive_id is None:
        raise ValueError("restore requires --archive-id")
    root = Path(args.project_root).resolve()
    cfg, _ = api.load_contract_document(root, "bo_config")
    if not isinstance(cfg, dict):
        raise ValueError("bo_config must be an object")
    paths = api._runtime_paths(root, cfg)
    _confirm_restore(args, root=root, archive_id=args.archive_id)
    lock_timeout = api.resolve_lock_timeout_seconds(cfg, args.lock_timeout_seconds)
    with api.hold_exclusive_lock(
        paths["lock_file"], timeout_seconds=lock_timeout, fail_fast=args.fail_fast
    ) as lock:
        lock_logged = False
        try:
            restore_result = api.restore_reset_archive(
                args.archive_id, project_root=root, runtime_paths=paths
            )
            api._append_event(
                paths,
                "lock_acquired",
                command="restore",
                pid=os.getpid(),
                wait_seconds=lock.wait_seconds,
            )
            lock_logged = True
            api._append_event(
                paths,
                "campaign_restored",
                archive_id=restore_result["archive_id"],
                archive_path=restore_result["archive_rel"],
                legacy_archive=restore_result["legacy"],
                restored_count=len(restore_result["restored_paths"]),
                overwritten_count=len(restore_result["overwritten_paths"]),
                ignored_count=len(restore_result["ignored_paths"]),
            )
            api._append_governance_violation_event(
                root, paths, api.load_state(paths["state_file"]), cfg, command="restore"
            )
            print("Campaign restore completed.")
            print(f"Archive: {restore_result['archive_rel']}")
            if restore_result["legacy"]:
                print("Archive kind: legacy")
            print("Restored artifacts:")
            for rel in restore_result["restored_paths"]:
                print(f"- {rel}")
            print("Overwritten artifacts:")
            if restore_result["overwritten_paths"]:
                for rel in restore_result["overwritten_paths"]:
                    print(f"- {rel}")
            else:
                print("- (none)")
            if restore_result["ignored_paths"]:
                print("Ignored archived artifacts:")
                for rel in restore_result["ignored_paths"]:
                    print(f"- {rel}")
        except Exception as exc:
            try:
                api._append_event(
                    paths,
                    "lock_acquired",
                    command="restore",
                    pid=os.getpid(),
                    wait_seconds=lock.wait_seconds,
                )
                lock_logged = True
                api._append_event(
                    paths,
                    "campaign_restore_failed",
                    archive_id=str(args.archive_id),
                    error=str(exc),
                )
            except Exception:
                pass
            raise
        finally:
            if lock_logged:
                api._append_event(paths, "lock_released", command="restore", pid=os.getpid())


def cmd_health(args: argparse.Namespace, *, api: ControllerHooks) -> None:
    payload, exit_code = api._build_health_payload(args)
    print(json.dumps(payload, indent=2))
    if exit_code != 0:
        raise SystemExit(exit_code)


def cmd_metrics(args: argparse.Namespace, *, api: ControllerHooks) -> None:
    payload, exit_code = api._build_metrics_payload(args)
    print(json.dumps(payload, indent=2))
    if exit_code != 0:
        raise SystemExit(exit_code)
