#!/usr/bin/env python3
"""Meshing-only Optuna optimizer for snappyHexMeshDict tuning.

This script is adapted for a meshing-only workflow:
  - copy pristine template case per trial
  - edit selected snappyHexMeshDict keys
  - run blockMesh / snappyHexMesh / checkMesh (single-process only)
  - parse checkMesh metrics and compute scalar score
  - persist trial artifacts and campaign logs
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib import parse as urlparse
from urllib import request as urlrequest

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INSTRUCTIONS_PATH = SCRIPT_DIR / "instructions.json"
DEFAULT_TEMPLATE_CASE_DIR = Path("./template_case")
DEFAULT_OUTPUT_ROOT = Path("./meshopt_output")
DEFAULT_STUDY_NAME = "snappy_mediumMesh_meshopt_v1"
SENSITIVE_LOG_ARG_KEYS = {"pushover_token", "pushover_user"}

TERMINAL_STATUSES = {
    "ok",
    "warn_checkmesh_exit_nonzero",
    "failed_preflight",
    "failed_copy",
    "failed_edit",
    "failed_command",
    "failed_parse",
    "abandoned_recovered",
    "dry_run",
}

FORBIDDEN_PARALLEL_TOKENS = {
    "mpirun",
    "decomposePar",
    "reconstructParMesh",
}
FORBIDDEN_PARALLEL_FLAGS = {
    "-parallel",
}

SCORE_TERMS_KEYS = [
    "underdetermined_term",
    "low_weight_term",
    "non_ortho_term",
    "warped_faces_term",
    "cells_term",
    "checkmesh_exit_penalty",
    "skewness_term",  # reserved, currently zero
    "concave_term",  # reserved, currently zero
    "failure_penalty_term",
]

RAW_METRIC_KEYS = [
    "total_cells",
    "N_faces_nonOrtho_gt_70",
    "N_warpedFaces",
    "N_underdeterminedCells",
    "N_lowWeightFaces",
    "maxNonOrtho",
    "maxSkewness",
    "minVol",
    "minTetQuality",
    "minFaceWeight",
]

ACCEPTANCE_FLAG_KEYS = [
    "accept_total_cells_lte_250000",
    "accept_underdetermined_lt_10",
    "accept_lowWeight_eq_0",
    "accept_nonOrtho70_lt_100",
    "accept_warped_lt_5",
]

EXIT_CODE_KEYS = [
    "blockMesh_exit_code",
    "snappyHexMesh_exit_code",
    "checkMesh_exit_code",
]

TIMING_KEYS = [
    "blockMesh_s",
    "snappyHexMesh_s",
    "checkMesh_s",
    "total_s",
]

RUNLOG_COLUMNS = [
    "ts_iso",
    "event",
    "run_ts",
    "trial_number",
    "status",
    "score",
    "study_name",
    "storage_uri",
    "study_fingerprint",
    "message",
    "payload_json",
]


def now_run_ts() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def json_dump_fallback(obj: Any) -> Any:
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    return repr(obj)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, default=json_dump_fallback) + "\n")


def append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, default=json_dump_fallback, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


def csv_append_row(path: Path, columns: Sequence[str], row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header_needed = (not path.exists()) or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(columns), extrasaction="ignore")
        if header_needed:
            writer.writeheader()
        payload = {col: row.get(col, "") for col in columns}
        writer.writerow(payload)
        fh.flush()
        os.fsync(fh.fileno())


def load_json_if_exists(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


def path_is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def format_float_literal(value: float) -> str:
    return f"{float(value):.12g}"


def normalize_value_for_compare(value: Any, param_type: str) -> str:
    if param_type == "float":
        return format_float_literal(float(value))
    if param_type == "int":
        return str(int(value))
    if param_type == "categorical":
        return str(value)
    return str(value).strip()


def shell_cmd_preview(cmd: Sequence[str]) -> str:
    return " ".join(str(x) for x in cmd)


def redact_notification_text(text: str, max_len: int = 220) -> str:
    cleaned = str(text or "")
    if not cleaned:
        return ""
    cleaned = re.sub(r"\bsqlite:///\S+", "sqlite:///<redacted>", cleaned)
    cleaned = re.sub(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://\S+", "<uri>", cleaned)
    cleaned = re.sub(r"(?:[A-Za-z]:)?/[^\s\n]+", "<path>", cleaned)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 3].rstrip() + "..."
    return cleaned


def sanitized_args_for_logs(args: argparse.Namespace) -> Dict[str, Any]:
    payload = dict(vars(args))
    for key in SENSITIVE_LOG_ARG_KEYS:
        if key in payload and str(payload[key]).strip():
            payload[key] = "<redacted>"
    return payload


def top_score_terms_summary(score_terms: Dict[str, Any], n: int = 3) -> str:
    pairs: List[Tuple[str, float]] = []
    for k, v in (score_terms or {}).items():
        try:
            fv = float(v)
        except Exception:
            continue
        if not math.isfinite(fv) or abs(fv) <= 0:
            continue
        pairs.append((k, fv))
    if not pairs:
        return "none"
    pairs.sort(key=lambda kv: abs(kv[1]), reverse=True)
    return ", ".join(f"{k}={v:.1f}" for k, v in pairs[:n])


def acceptance_flags_summary(flags: Dict[str, bool]) -> str:
    short = {
        "accept_total_cells_lte_250000": "cells",
        "accept_underdetermined_lt_10": "under",
        "accept_lowWeight_eq_0": "lowW",
        "accept_nonOrtho70_lt_100": "nO70",
        "accept_warped_lt_5": "warp",
    }
    bits = []
    for key in ACCEPTANCE_FLAG_KEYS:
        bits.append(f"{short.get(key, key)}={'ok' if flags.get(key) else 'bad'}")
    return " ".join(bits)


@dataclass
class CampaignPaths:
    out_root: Path
    logs_dir: Path
    summary_csv: Path
    run_csv: Path
    runs_jsonl: Path
    inflight_json: Path
    state_json: Path
    db_path: Optional[Path]
    storage_uri: str


@dataclass
class StartupMeta:
    run_ts: str
    study_name: str
    storage_uri: str
    db_path: Optional[str]
    template_case_dir: str
    campaign_output_root: str
    instructions_json: str
    instructions_hash: str
    scoring_config_hash: str
    study_fingerprint: str
    edit_scope: List[Dict[str, str]]
    startup_warnings: List[str] = field(default_factory=list)
    started_at: str = field(default_factory=now_iso)


class Notifier:
    def __init__(
        self,
        enabled: bool,
        token: str,
        user: str,
        notify_on_failure: bool = True,
        notify_on_success: bool = True,
    ) -> None:
        self.enabled = bool(enabled and token and user)
        self.token = token
        self.user = user
        self.notify_on_failure = bool(notify_on_failure)
        self.notify_on_success = bool(notify_on_success)

    def _send(self, title: str, message: str) -> None:
        if not self.enabled:
            return
        try:
            data = urlparse.urlencode(
                {
                    "token": self.token,
                    "user": self.user,
                    "title": title[:250],
                    "message": (message or "")[:1024],
                    "priority": "0",
                }
            ).encode()
            req = urlrequest.Request("https://api.pushover.net/1/messages.json", data=data)
            with urlrequest.urlopen(req, timeout=10) as resp:
                if resp.getcode() != 200:
                    print(f"[notify] HTTP {resp.getcode()}")
        except Exception as exc:
            print(f"[notify] failed: {exc.__class__.__name__}")

    def start(self, title: str, message: str) -> None:
        self._send(title, message)

    def termination(self, title: str, message: str) -> None:
        self._send(title, message)

    def recovery(self, title: str, message: str) -> None:
        self._send(title, message)

    def success(self, title: str, message: str) -> None:
        if self.notify_on_success:
            self._send(title, message)

    def failure(self, title: str, message: str) -> None:
        if self.notify_on_failure:
            self._send(title, message)


@dataclass
class TrialResult:
    trial_number: int
    trial_dir: Path
    trial_dir_collision_suffix: Optional[str]
    status: str
    score: float
    params: Dict[str, Any]
    raw_metrics: Dict[str, Any]
    acceptance_flags: Dict[str, bool]
    score_terms: Dict[str, float]
    exit_codes: Dict[str, Optional[int]]
    timings: Dict[str, Optional[float]]
    failure_reason: Optional[str]
    failed_step: Optional[str]
    dry_run: bool = False


class CampaignContext:
    def __init__(
        self,
        args: argparse.Namespace,
        instructions: Dict[str, Any],
        paths: CampaignPaths,
        startup: StartupMeta,
        notifier: Notifier,
    ) -> None:
        self.args = args
        self.instructions = instructions
        self.paths = paths
        self.startup = startup
        self.notifier = notifier
        self.search_space = instructions["search_space"]
        self.log_regex = instructions["log_parsing_regex"]
        self.scoring_spec = instructions["score_spec"]
        self.editing_spec = instructions["editing_snappyHexMeshDict"]
        self.optimizer_cfg = instructions["optimizer"]
        self.summary_columns = build_summary_columns(self.search_space)
        self.state: Dict[str, Any] = {
            "run_ts": startup.run_ts,
            "study_name": startup.study_name,
            "resolved_storage_uri": startup.storage_uri,
            "db_path": startup.db_path,
            "study_fingerprint": startup.study_fingerprint,
            "campaign_output_root": str(paths.out_root),
            "template_case_dir": startup.template_case_dir,
            "instructions_json": startup.instructions_json,
            "instructions_hash": startup.instructions_hash,
            "scoring_config_hash": startup.scoring_config_hash,
            "startup_warnings": list(startup.startup_warnings),
            "last_success_trial": None,
            "last_success_score": None,
            "started_at": startup.started_at,
            "updated_at": now_iso(),
        }
        self.best_score_so_far: Optional[float] = None
        self.best_trial_number: Optional[int] = None
        self.successful_meshes: int = 0
        self.completed_trials: int = 0
        self.template_guard: Dict[str, Any] = snapshot_template_guard(
            Path(startup.template_case_dir)
        )

    def save_state(self) -> None:
        self.state["updated_at"] = now_iso()
        atomic_write_json(self.paths.state_json, self.state)

    def log_event(self, event: str, message: str = "", **payload: Any) -> None:
        row = {
            "ts_iso": now_iso(),
            "event": event,
            "run_ts": self.startup.run_ts,
            "trial_number": payload.get("trial_number", ""),
            "status": payload.get("status", ""),
            "score": payload.get("score", ""),
            "study_name": self.startup.study_name,
            "storage_uri": self.startup.storage_uri,
            "study_fingerprint": self.startup.study_fingerprint,
            "message": message,
            "payload_json": canonical_json(payload) if payload else "",
        }
        csv_append_row(self.paths.run_csv, RUNLOG_COLUMNS, row)

    def append_runs_index(self, record: Dict[str, Any]) -> None:
        append_jsonl(self.paths.runs_jsonl, record)

    def write_inflight(
        self, trial_number: int, trial_dir: Path, stage: str, extra: Optional[Dict[str, Any]] = None
    ) -> None:
        payload = {
            "RUN_TS": self.startup.run_ts,
            "trial_number": int(trial_number),
            "trial_dir": str(trial_dir),
            "start_time": self.state.get("updated_at", now_iso()),
            "stage": stage,
            "study_name": self.startup.study_name,
            "storage_uri": self.startup.storage_uri,
            "updated_at": now_iso(),
        }
        if extra:
            payload.update(extra)
        atomic_write_json(self.paths.inflight_json, payload)

    def clear_inflight(self) -> None:
        try:
            self.paths.inflight_json.unlink()
        except FileNotFoundError:
            return
        except Exception as exc:
            print(f"[recover] warn: could not clear inflight marker: {exc}")


def build_summary_columns(search_space: Dict[str, Any]) -> List[str]:
    cols: List[str] = [
        "ts_iso",
        "run_ts",
        "study_name",
        "storage_uri",
        "trial_number",
        "status",
        "score",
        "trial_dir",
        "trial_dir_basename",
        "failure_reason",
        "failed_step",
        "dry_run",
    ]
    cols.extend(sorted(search_space.keys()))
    cols.extend(RAW_METRIC_KEYS)
    cols.extend(ACCEPTANCE_FLAG_KEYS)
    cols.extend(SCORE_TERMS_KEYS)
    cols.extend(EXIT_CODE_KEYS)
    cols.extend(TIMING_KEYS)
    cols.extend(["score_terms_top3", "acceptance_flags_summary"])
    return cols


def snapshot_template_guard(template_dir: Path) -> Dict[str, Any]:
    key_files = [
        template_dir / "system" / "snappyHexMeshDict",
        template_dir / "system" / "blockMeshDict",
    ]
    snapshot: Dict[str, Any] = {"created_at": now_iso(), "files": {}}
    for p in key_files:
        if p.exists():
            try:
                st = p.stat()
                snapshot["files"][str(p)] = {
                    "size": st.st_size,
                    "mtime_ns": st.st_mtime_ns,
                    "sha256": sha256_file(p),
                }
            except Exception as exc:
                snapshot["files"][str(p)] = {"error": repr(exc)}
    return snapshot


def verify_template_guard(snapshot: Dict[str, Any]) -> Tuple[bool, List[str]]:
    mismatches: List[str] = []
    for path_s, meta in snapshot.get("files", {}).items():
        path = Path(path_s)
        if not path.exists():
            mismatches.append(f"missing:{path}")
            continue
        try:
            st = path.stat()
            if meta.get("size") != st.st_size:
                mismatches.append(f"size:{path}")
            if meta.get("mtime_ns") != st.st_mtime_ns:
                # mtime drift alone might occur; confirm content hash before flagging hard mismatch.
                current_hash = sha256_file(path)
                if meta.get("sha256") != current_hash:
                    mismatches.append(f"hash:{path}")
        except Exception as exc:
            mismatches.append(f"error:{path}:{exc}")
    return (len(mismatches) == 0, mismatches)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Optuna meshing optimizer for mediumMesh snappyHexMeshDict tuning"
    )
    parser.add_argument("--instructions-json", type=str, default=str(DEFAULT_INSTRUCTIONS_PATH))
    parser.add_argument("--template-case-dir", type=str, default=str(DEFAULT_TEMPLATE_CASE_DIR))
    parser.add_argument("--out-root", type=str, default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--n-trials", type=int, default=40)
    parser.add_argument(
        "--n-jobs", type=int, default=1, help="Initial supported mode is 1 (no concurrent meshing)."
    )
    parser.add_argument("--study-name", type=str, default=DEFAULT_STUDY_NAME)
    parser.add_argument("--storage", type=str, default="")
    parser.add_argument("--db-path", type=str, default="")
    parser.add_argument("--resume", action="store_true", help="Resume/load existing Optuna study.")
    parser.add_argument(
        "--recover",
        action="store_true",
        help="Resolve inflight marker deterministically before continuing.",
    )
    parser.add_argument(
        "--force-resume",
        action="store_true",
        help="Override study fingerprint mismatch protection.",
    )
    parser.add_argument(
        "--require-empty-root",
        action="store_true",
        help="Fail if output root exists and is non-empty.",
    )
    parser.add_argument("--copy-mode", choices=["copytree", "rsync"], default="copytree")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Copy/edit/write metadata but do not run meshing commands.",
    )
    parser.add_argument(
        "--single",
        action="store_true",
        help="Run a single fixed-parameter trial (via Optuna enqueue).",
    )
    parser.add_argument("--checkmesh-exit-penalty", type=float, default=0.0)

    parser.add_argument("--no-notify", action="store_true", help="Disable Pushover notifications.")
    parser.add_argument("--pushover_token", type=str, default=os.environ.get("PUSHOVER_TOKEN", ""))
    parser.add_argument("--pushover_user", type=str, default=os.environ.get("PUSHOVER_USER", ""))
    parser.add_argument("--notify-on-failure", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--notify-on-success", action=argparse.BooleanOptionalAction, default=True)
    return parser


def load_instructions(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    for key in [
        "search_space",
        "score_spec",
        "log_parsing_regex",
        "editing_snappyHexMeshDict",
        "optimizer",
    ]:
        require(key in data, f"Missing required key in instructions.json: {key}")
    return data


def resolve_storage(args: argparse.Namespace, logs_dir: Path) -> Tuple[str, Optional[Path]]:
    if args.storage:
        raw = args.storage.strip()
        if raw.startswith("sqlite:///"):
            path_part = raw[len("sqlite:///") :]
            if path_part and not path_part.startswith("/"):
                abs_db = (Path.cwd() / path_part).resolve()
                return f"sqlite:///{abs_db.as_posix()}", abs_db
            if path_part.startswith("/"):
                return raw, Path(path_part).resolve()
        return raw, None
    db_path = Path(args.db_path).expanduser() if args.db_path else (logs_dir / "optuna_meshing.db")
    db_path = db_path.resolve()
    uri = f"sqlite:///{db_path.as_posix()}"
    return uri, db_path


def build_notifier(args: argparse.Namespace) -> Notifier:
    token = (args.pushover_token or os.environ.get("PUSHOVER_TOKEN", "")).strip()
    user = (args.pushover_user or os.environ.get("PUSHOVER_USER", "")).strip()
    env_disable = os.environ.get("BO_NOTIFY", "").strip().lower() in {"0", "false", "no", "off"}
    enabled = (not args.no_notify) and (not env_disable) and bool(token and user)
    if (not args.no_notify) and (not env_disable) and not enabled:
        print("[notify] token/user missing; notifications disabled")
    return Notifier(
        enabled=enabled,
        token=token,
        user=user,
        notify_on_failure=bool(args.notify_on_failure),
        notify_on_success=bool(args.notify_on_success),
    )


def prepare_output_root(args: argparse.Namespace, out_root: Path, notifier: Notifier) -> List[str]:
    warnings: List[str] = []
    if out_root.exists():
        if args.require_empty_root:
            try:
                if any(out_root.iterdir()):
                    raise RuntimeError(
                        f"--require-empty-root set, but output root is non-empty: {out_root}"
                    )
            except StopIteration:
                pass
        if not os.access(out_root, os.W_OK):
            notifier.termination("MeshOpt Error", "preflight failed: output root not writable")
            raise RuntimeError(f"Output root exists but is not writable: {out_root}")
    else:
        out_root.mkdir(parents=True, exist_ok=True)

    logs_dir = out_root / "BO_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Writeability test in logs dir.
    test_path = logs_dir / f".write_test_{int(time.time())}.tmp"
    try:
        atomic_write_text(test_path, "ok\n")
        test_path.unlink(missing_ok=True)
    except Exception as exc:
        notifier.termination("MeshOpt Error", "preflight failed: cannot write logs directory")
        raise RuntimeError(f"Cannot write to logs directory {logs_dir}: {exc}") from exc

    inflight = logs_dir / "meshing_inflight.json"
    if inflight.exists() and not args.recover:
        warnings.append(f"inflight marker present but --recover not set: {inflight}")
    return warnings


def validate_template_and_paths(template_dir: Path, out_root: Path) -> None:
    require(template_dir.exists(), f"Template case dir not found: {template_dir}")
    require(template_dir.is_dir(), f"Template case path is not a directory: {template_dir}")
    require(os.access(template_dir, os.R_OK), f"Template case dir is not readable: {template_dir}")
    require(
        not path_is_within(template_dir, out_root),
        f"Template case dir must not be nested inside output root: {template_dir}",
    )
    require(
        not path_is_within(out_root, template_dir),
        f"Output root must not be nested inside template case dir: {out_root}",
    )


def validate_runtime_requirements(args: argparse.Namespace) -> None:
    require(
        args.n_jobs == 1,
        "Only --n-jobs=1 is supported in this implementation (single-process meshing loop).",
    )
    if args.copy_mode == "rsync":
        require(
            shutil.which("rsync") is not None,
            "--copy-mode=rsync requested but `rsync` was not found in PATH.",
        )
    if not args.dry_run:
        for cmd in ("blockMesh", "snappyHexMesh", "checkMesh"):
            require(shutil.which(cmd) is not None, f"Required command not found in PATH: {cmd}")


def compute_instruction_identifiers(
    instructions_path: Path, instructions: Dict[str, Any]
) -> Tuple[str, str]:
    instructions_hash = sha256_file(instructions_path)
    scoring_cfg_obj = {
        "score_spec": instructions.get("score_spec"),
        "log_parsing_regex": instructions.get("log_parsing_regex"),
    }
    scoring_hash = sha256_text(canonical_json(scoring_cfg_obj))
    return instructions_hash, scoring_hash


def derive_edit_scope(instructions: Dict[str, Any]) -> List[Dict[str, str]]:
    scope: List[Dict[str, str]] = []
    for item in instructions.get("editing_snappyHexMeshDict", {}).get("required_replacements", []):
        scope.append(
            {
                "block": str(item.get("block", "")),
                "key": str(item.get("key", "")),
            }
        )
    return scope


def compute_study_fingerprint(
    template_case_dir: Path,
    instructions_hash: str,
    scoring_hash: str,
    edit_scope: List[Dict[str, str]],
) -> str:
    payload = {
        "template_case_dir": str(template_case_dir.resolve()),
        "instructions_json_hash": instructions_hash,
        "scoring_config_hash": scoring_hash,
        "edit_scope": edit_scope,
    }
    return sha256_text(canonical_json(payload))


def load_previous_state_for_resume(state_path: Path) -> Optional[Dict[str, Any]]:
    return load_json_if_exists(state_path)


def check_resume_fingerprint(
    args: argparse.Namespace,
    previous_state: Optional[Dict[str, Any]],
    startup: StartupMeta,
) -> None:
    if not (args.resume or args.recover):
        return
    if not previous_state:
        return
    prev_fp = str(previous_state.get("study_fingerprint", "")).strip()
    if not prev_fp:
        return
    mismatches: List[str] = []
    if prev_fp != startup.study_fingerprint:
        mismatches.append("study_fingerprint")
    prev_study_name = str(previous_state.get("study_name", "")).strip()
    if prev_study_name and prev_study_name != startup.study_name:
        mismatches.append("study_name")
    prev_storage = str(previous_state.get("resolved_storage_uri", "")).strip()
    if prev_storage and prev_storage != startup.storage_uri:
        mismatches.append("storage_uri")
    if mismatches and not args.force_resume:
        raise RuntimeError(
            "Resume/recover blocked due to study identity mismatch "
            f"({', '.join(mismatches)}). Re-run with --force-resume to override."
        )


def write_trial_status(path: Path, payload: Dict[str, Any]) -> None:
    data = dict(payload)
    data.setdefault("updated_at", now_iso())
    atomic_write_json(path, data)


def is_terminal_trial_status(status: str) -> bool:
    return status in TERMINAL_STATUSES or status.startswith("failed_")


def reconcile_inflight(ctx: CampaignContext) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "event": "recovery",
        "run_ts": ctx.startup.run_ts,
        "found_inflight": False,
        "action": "not_requested" if not ctx.args.recover else "none_found",
        "details": "",
    }
    inflight = load_json_if_exists(ctx.paths.inflight_json)
    if not inflight:
        if ctx.args.recover:
            ctx.notifier.recovery(
                "MeshOpt Recovery",
                f"run_ts={ctx.startup.run_ts}\ninflight=none\naction=none",
            )
            ctx.log_event("recovery", "no inflight marker found", action="none_found")
        return summary

    summary["found_inflight"] = True
    summary["inflight"] = inflight

    if not ctx.args.recover:
        summary["action"] = "warning_only"
        summary["details"] = "inflight present but --recover not set"
        return summary

    trial_number = inflight.get("trial_number")
    trial_dir = Path(str(inflight.get("trial_dir", ""))) if inflight.get("trial_dir") else None
    action = ""
    details = ""

    if not trial_dir or not trial_dir.exists():
        action = "abandoned_missing_trial_dir"
        details = "trial_dir missing"
        rec = {
            "event": "recovery_resolve",
            "run_ts": ctx.startup.run_ts,
            "ts_iso": now_iso(),
            "trial_number": trial_number,
            "trial_dir": str(trial_dir) if trial_dir else "",
            "status": "abandoned_recovered",
            "reason": "inflight_trial_dir_missing",
            "inflight": inflight,
        }
        ctx.append_runs_index(rec)
        ctx.clear_inflight()
    else:
        trial_status_path = trial_dir / "trial_status.json"
        trial_status = load_json_if_exists(trial_status_path)
        terminal = False
        if trial_status:
            terminal = is_terminal_trial_status(str(trial_status.get("status", "")))
        if terminal:
            action = "clear_inflight_terminal_trial"
            details = f"terminal_status={trial_status.get('status')}"
            ctx.clear_inflight()
        else:
            action = "mark_abandoned_recovered"
            details = "trial_dir exists without terminal trial_status"
            payload = {
                "status": "abandoned_recovered",
                "reason": "found_inflight_on_startup",
                "run_ts": ctx.startup.run_ts,
                "trial_number": trial_number,
                "trial_dir": str(trial_dir),
                "recovered_at": now_iso(),
            }
            write_trial_status(trial_status_path, payload)
            ctx.append_runs_index(
                {
                    "event": "recovery_resolve",
                    "run_ts": ctx.startup.run_ts,
                    "ts_iso": now_iso(),
                    "trial_number": trial_number,
                    "trial_dir": str(trial_dir),
                    "status": "abandoned_recovered",
                    "reason": "found_inflight_on_startup",
                }
            )
            ctx.clear_inflight()

    summary["action"] = action
    summary["details"] = details
    ctx.log_event("recovery", details, action=action, inflight=inflight, trial_number=trial_number)
    ctx.notifier.recovery(
        "MeshOpt Recovery",
        (
            f"run_ts={ctx.startup.run_ts}\n"
            f"inflight=found\n"
            f"action={action}\n"
            f"trial={trial_number}\n"
            f"details={details}"
        ),
    )
    return summary


def build_trial_dir(out_root: Path, run_ts: str, trial_number: int) -> Tuple[Path, Optional[str]]:
    base_name = f"mediumMesh_meshTrial_{run_ts}_t{trial_number:04d}"
    base_path = out_root / base_name
    if not base_path.exists():
        return base_path, None
    dup = 1
    while True:
        suffix = f"_dup{dup}"
        candidate = out_root / f"{base_name}{suffix}"
        if not candidate.exists():
            return candidate, suffix
        dup += 1


def copy_template_case(template_dir: Path, trial_dir: Path, copy_mode: str) -> None:
    if copy_mode == "copytree":
        shutil.copytree(template_dir, trial_dir, symlinks=True)
        return

    if copy_mode != "rsync":
        raise RuntimeError(f"Unsupported copy mode: {copy_mode}")

    trial_dir.mkdir(parents=True, exist_ok=False)
    excludes = [
        "processor*",
        "postProcessing",
        "*.foam",
        "log.*",
        # Numeric time directory excludes are intentionally omitted because the template's `0/`
        # directory is required for meshing and must be copied.
    ]
    cmd = ["rsync", "-a"]
    for ex in excludes:
        cmd.append(f"--exclude={ex}")
    cmd.extend([f"{template_dir.as_posix()}/", f"{trial_dir.as_posix()}/"])
    subprocess.run(cmd, check=True)


def verify_trial_dir_minima(trial_dir: Path) -> None:
    require((trial_dir / "system").exists(), f"Copied trial missing `system/`: {trial_dir}")
    require((trial_dir / "constant").exists(), f"Copied trial missing `constant/`: {trial_dir}")
    require(
        (trial_dir / "0").exists() or (trial_dir / "0.org").exists(),
        f"Copied trial missing `0/` or `0.org/`: {trial_dir}",
    )


def write_trial_readme(
    path: Path,
    template_case_dir: Path,
    run_ts: str,
    trial_number: int,
    storage_uri: str,
    study_name: str,
    params: Dict[str, Any],
    commands: Sequence[Sequence[str]],
) -> None:
    lines = [
        "Mesh Optimizer Trial Provenance",
        "==============================",
        f"template_case_dir: {template_case_dir}",
        f"RUN_TS: {run_ts}",
        f"trial_number: {trial_number}",
        f"study_name: {study_name}",
        f"resolved_storage_uri: {storage_uri}",
        "params_applied:",
    ]
    for k in sorted(params.keys()):
        lines.append(f"  {k}: {params[k]}")
    lines.append("planned_commands:")
    for cmd in commands:
        lines.append(f"  - {shell_cmd_preview(cmd)}")
    atomic_write_text(path, "\n".join(lines) + "\n")


def find_block_span(text: str, block_name: str) -> Tuple[int, int]:
    m = re.search(rf"(?m)\b{re.escape(block_name)}\s*\{{", text)
    if not m:
        raise RuntimeError(f"Block not found: {block_name}")
    brace_start = text.find("{", m.start())
    if brace_start < 0:
        raise RuntimeError(f"Block opening brace not found: {block_name}")
    depth = 0
    for idx in range(brace_start, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return (brace_start, idx)
    raise RuntimeError(f"Unbalanced braces while scanning block: {block_name}")


def braces_balanced(text: str) -> bool:
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def parameter_literal_map(params: Dict[str, Any], search_space: Dict[str, Any]) -> Dict[str, str]:
    lit: Dict[str, str] = {}
    for full_key, spec in search_space.items():
        key = full_key.split(".")[-1]
        ptype = str(spec.get("type"))
        value = params[full_key]
        if ptype == "float":
            lit[key] = format_float_literal(float(value))
        elif ptype == "int":
            lit[key] = str(int(value))
        else:
            lit[key] = str(value)
    return lit


def edit_snappy_hex_mesh_dict(
    path: Path,
    params: Dict[str, Any],
    search_space: Dict[str, Any],
    editing_spec: Dict[str, Any],
) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    original_text = text
    replacements = editing_spec.get("required_replacements", [])
    literal_by_key = parameter_literal_map(params, search_space)
    diagnostics: Dict[str, Any] = {"replacements": [], "roundtrip": [], "brace_balanced": None}

    block_spans: Dict[str, Tuple[int, int]] = {}

    for item in replacements:
        key = str(item["key"])
        block = str(item["block"])
        regex = str(item["regex"])
        replacement_template = str(item["replacement"])
        expected_lit = literal_by_key[key]
        repl = replacement_template.format(**{key: expected_lit})

        matches = list(re.finditer(regex, text))
        if len(matches) != 1:
            raise RuntimeError(
                f"failed_edit: expected exactly one match for {block}.{key}, found {len(matches)}"
            )
        m = matches[0]
        block_spans[block] = find_block_span(text, block)
        block_start, block_end = block_spans[block]
        value_start = m.start(2) if m.lastindex and m.lastindex >= 2 else m.start()
        value_end = m.end(2) if m.lastindex and m.lastindex >= 2 else m.end()
        if not (
            block_start <= value_start <= block_end and block_start <= value_end <= block_end + 1
        ):
            raise RuntimeError(
                f"failed_edit: match for {block}.{key} is outside intended block boundaries"
            )

        new_text, count = re.subn(regex, repl, text, count=1)
        if count != 1:
            raise RuntimeError(
                f"failed_edit: replacement count for {block}.{key} was {count}, expected 1"
            )
        text = new_text
        diagnostics["replacements"].append(
            {"block": block, "key": key, "expected": expected_lit, "replacement_count": count}
        )

    if not braces_balanced(text):
        raise RuntimeError("failed_edit: snappyHexMeshDict braces appear unbalanced after edits")

    # Round-trip verify values.
    for item in replacements:
        key = str(item["key"])
        regex = str(item["regex"])
        expected_lit = literal_by_key[key]
        matches = list(re.finditer(regex, text))
        if len(matches) != 1:
            raise RuntimeError(
                f"failed_edit: round-trip expected one match for {key}, found {len(matches)}"
            )
        actual_raw = matches[0].group(2).strip()
        spec = search_space.get(next(k for k in search_space if k.endswith(f".{key}") or k == key))
        ptype = str(spec.get("type"))
        actual_norm = normalize_value_for_compare(actual_raw, ptype)
        expected_norm = normalize_value_for_compare(expected_lit, ptype)
        if ptype == "float":
            # Normalize actual via float parse to avoid formatting differences.
            try:
                actual_norm = normalize_value_for_compare(float(actual_raw), ptype)
            except Exception as exc:
                raise RuntimeError(
                    f"failed_edit: could not parse float round-trip for {key}: {exc}"
                ) from exc
        elif ptype == "int":
            try:
                actual_norm = normalize_value_for_compare(int(float(actual_raw)), ptype)
            except Exception as exc:
                raise RuntimeError(
                    f"failed_edit: could not parse int round-trip for {key}: {exc}"
                ) from exc
        if actual_norm != expected_norm:
            raise RuntimeError(
                f"failed_edit: round-trip mismatch for {key}: expected {expected_norm}, got {actual_norm}"
            )
        diagnostics["roundtrip"].append(
            {"key": key, "expected": expected_norm, "actual": actual_norm}
        )

    diagnostics["brace_balanced"] = True
    if text != original_text:
        atomic_write_text(path, text)
    return diagnostics


def enforce_single_process_command(cmd: Sequence[str]) -> None:
    tokens = [str(x) for x in cmd]
    low = [t.lower() for t in tokens]
    for tok in low:
        if tok in FORBIDDEN_PARALLEL_TOKENS:
            raise RuntimeError(
                f"Parallel meshing invocation forbidden: token `{tok}` in command {tokens}"
            )
        if tok in FORBIDDEN_PARALLEL_FLAGS:
            raise RuntimeError(
                f"Parallel meshing invocation forbidden: flag `{tok}` in command {tokens}"
            )


def run_command_logged(cmd: Sequence[str], cwd: Path, log_path: Path) -> Tuple[int, float]:
    enforce_single_process_command(cmd)
    start = time.monotonic()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as fh:
        fh.write(f"# cwd: {cwd}\n")
        fh.write(f"# cmd: {shell_cmd_preview(cmd)}\n")
        fh.flush()
        proc = subprocess.run(
            list(cmd),
            cwd=str(cwd),
            stdout=fh,
            stderr=subprocess.STDOUT,
            check=False,
        )
        fh.flush()
        os.fsync(fh.fileno())
    elapsed = time.monotonic() - start
    return int(proc.returncode), float(elapsed)


def parse_optional_float(pattern: str, text: str) -> Optional[float]:
    m = re.search(pattern, text, flags=re.M | re.S)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def parse_required_int(pattern: str, text: str) -> Optional[int]:
    m = re.search(pattern, text, flags=re.M | re.S)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        try:
            return int(float(m.group(1)))
        except Exception:
            return None


def parse_checkmesh_metrics(
    text: str, regex_cfg: Dict[str, Any]
) -> Tuple[Dict[str, Any], List[str]]:
    metrics: Dict[str, Any] = {}
    errors: List[str] = []

    total_cells = None
    for pat in regex_cfg.get("total_cells_patterns", []):
        total_cells = parse_required_int(str(pat), text)
        if total_cells is not None:
            break
    if total_cells is None:
        errors.append("total_cells")
    metrics["total_cells"] = total_cells

    metrics["N_faces_nonOrtho_gt_70"] = parse_required_int(
        str(regex_cfg["N_faces_nonOrtho_gt_70"]), text
    )
    if metrics["N_faces_nonOrtho_gt_70"] is None:
        # Some versions omit the explicit severe count line when zero.
        if "severely non-orthogonal" in text:
            errors.append("N_faces_nonOrtho_gt_70")
        else:
            metrics["N_faces_nonOrtho_gt_70"] = 0

    metrics["N_warpedFaces"] = parse_required_int(str(regex_cfg["N_warpedFaces"]), text)
    if metrics["N_warpedFaces"] is None:
        if re.search(r"ratio between projected and actual area < 0\.8", text):
            errors.append("N_warpedFaces")
        else:
            metrics["N_warpedFaces"] = 0

    metrics["N_underdeterminedCells"] = parse_required_int(
        str(regex_cfg["N_underdeterminedCells"]), text
    )
    if metrics["N_underdeterminedCells"] is None:
        if re.search(r"small determinant\s*\(<\s*0\.001\)", text):
            errors.append("N_underdeterminedCells")
        else:
            metrics["N_underdeterminedCells"] = 0

    metrics["N_lowWeightFaces"] = parse_required_int(str(regex_cfg["N_lowWeightFaces"]), text)
    if metrics["N_lowWeightFaces"] is None:
        if re.search(r"small interpolation weight\s*\(<\s*0\.05\)", text):
            errors.append("N_lowWeightFaces")
        else:
            metrics["N_lowWeightFaces"] = 0

    # Optional debug metrics (best-effort).
    metrics["maxNonOrtho"] = parse_optional_float(
        r"Mesh non-orthogonality Max:\s*([0-9eE\.\+\-]+)", text
    )
    metrics["maxSkewness"] = parse_optional_float(r"Max skewness =\s*([0-9eE\.\+\-]+)", text)
    metrics["minVol"] = parse_optional_float(r"Min volume =\s*([0-9eE\.\+\-]+)", text)
    metrics["minTetQuality"] = parse_optional_float(r"Min tet quality =\s*([0-9eE\.\+\-]+)", text)
    metrics["minFaceWeight"] = parse_optional_float(r"Min face weight =\s*([0-9eE\.\+\-]+)", text)

    # Final required checks.
    for k in [
        "total_cells",
        "N_faces_nonOrtho_gt_70",
        "N_warpedFaces",
        "N_underdeterminedCells",
        "N_lowWeightFaces",
    ]:
        if metrics.get(k) is None and k not in errors:
            errors.append(k)

    return metrics, sorted(set(errors))


def compute_acceptance_flags(metrics: Dict[str, Any]) -> Dict[str, bool]:
    return {
        "accept_total_cells_lte_250000": int(metrics["total_cells"]) <= 250000,
        "accept_underdetermined_lt_10": int(metrics["N_underdeterminedCells"]) < 10,
        "accept_lowWeight_eq_0": int(metrics["N_lowWeightFaces"]) == 0,
        "accept_nonOrtho70_lt_100": int(metrics["N_faces_nonOrtho_gt_70"]) < 100,
        "accept_warped_lt_5": int(metrics["N_warpedFaces"]) < 5,
    }


def zero_score_terms() -> Dict[str, float]:
    return {k: 0.0 for k in SCORE_TERMS_KEYS}


def compute_score(
    metrics: Dict[str, Any], checkmesh_exit_penalty: float = 0.0
) -> Tuple[float, Dict[str, float], Dict[str, bool]]:
    m = {
        k: int(metrics[k])
        for k in [
            "total_cells",
            "N_faces_nonOrtho_gt_70",
            "N_warpedFaces",
            "N_underdeterminedCells",
            "N_lowWeightFaces",
        ]
    }
    terms = zero_score_terms()
    terms["underdetermined_term"] = (
        1000.0 * max(0, m["N_underdeterminedCells"] - 9) + 50.0 * m["N_underdeterminedCells"]
    )
    terms["low_weight_term"] = 10000.0 * max(0, m["N_lowWeightFaces"])
    terms["non_ortho_term"] = (
        50.0 * max(0, m["N_faces_nonOrtho_gt_70"] - 99) + 0.5 * m["N_faces_nonOrtho_gt_70"]
    )
    terms["warped_faces_term"] = 200.0 * max(0, m["N_warpedFaces"] - 4) + 2.0 * m["N_warpedFaces"]
    if m["total_cells"] > 250000:
        terms["cells_term"] = 0.1 * (m["total_cells"] - 250000) + 20000.0
    if checkmesh_exit_penalty:
        terms["checkmesh_exit_penalty"] = float(checkmesh_exit_penalty)
    score = float(sum(float(v) for v in terms.values()))
    flags = compute_acceptance_flags(metrics)
    return score, terms, flags


def sample_params_from_trial(trial: Any, search_space: Dict[str, Any]) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    for name, spec in search_space.items():
        ptype = spec["type"]
        if ptype == "float":
            params[name] = float(trial.suggest_float(name, float(spec["low"]), float(spec["high"])))
        elif ptype == "int":
            low = int(spec["low"])
            high = int(spec["high"])
            if name == "snapControls.nSolveIter":
                params[name] = int(trial.suggest_int(name, low, high, step=50))
            else:
                params[name] = int(trial.suggest_int(name, low, high))
        elif ptype == "categorical":
            params[name] = trial.suggest_categorical(name, list(spec["choices"]))
        else:
            raise RuntimeError(f"Unsupported search space type for {name}: {ptype}")
    return params


def single_trial_default_params(search_space: Dict[str, Any]) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    for name, spec in search_space.items():
        ptype = spec["type"]
        if ptype == "float":
            lo = float(spec["low"])
            hi = float(spec["high"])
            params[name] = float((lo + hi) / 2.0)
        elif ptype == "int":
            lo = int(spec["low"])
            hi = int(spec["high"])
            params[name] = int(round((lo + hi) / 2.0))
        elif ptype == "categorical":
            params[name] = list(spec["choices"])[0]
        else:
            raise RuntimeError(f"Unsupported search space type for {name}: {ptype}")
    return params


def trial_commands() -> List[List[str]]:
    cmds = [
        ["blockMesh"],
        ["snappyHexMesh", "-overwrite"],
        ["checkMesh", "-allGeometry", "-allTopology"],
    ]
    for cmd in cmds:
        enforce_single_process_command(cmd)
    return cmds


def flatten_trial_for_summary(ctx: CampaignContext, result: TrialResult) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "ts_iso": now_iso(),
        "run_ts": ctx.startup.run_ts,
        "study_name": ctx.startup.study_name,
        "storage_uri": ctx.startup.storage_uri,
        "trial_number": result.trial_number,
        "status": result.status,
        "score": result.score,
        "trial_dir": str(result.trial_dir),
        "trial_dir_basename": result.trial_dir.name,
        "failure_reason": result.failure_reason or "",
        "failed_step": result.failed_step or "",
        "dry_run": str(bool(result.dry_run)).lower(),
        "score_terms_top3": top_score_terms_summary(result.score_terms),
        "acceptance_flags_summary": acceptance_flags_summary(result.acceptance_flags),
    }
    row.update(result.params)
    row.update({k: result.raw_metrics.get(k, "") for k in RAW_METRIC_KEYS})
    row.update({k: result.acceptance_flags.get(k, "") for k in ACCEPTANCE_FLAG_KEYS})
    row.update({k: result.score_terms.get(k, 0.0) for k in SCORE_TERMS_KEYS})
    row.update({k: result.exit_codes.get(k, "") for k in EXIT_CODE_KEYS})
    row.update({k: result.timings.get(k, "") for k in TIMING_KEYS})
    return row


def write_trial_artifacts(
    ctx: CampaignContext,
    result: TrialResult,
    trial_dir: Path,
    trial_status_payload: Dict[str, Any],
) -> None:
    trial_params_path = trial_dir / "trial_params.json"
    trial_metrics_path = trial_dir / "trial_metrics.json"
    trial_status_path = trial_dir / "trial_status.json"

    atomic_write_json(
        trial_params_path,
        {
            "run_ts": ctx.startup.run_ts,
            "trial_number": result.trial_number,
            "study_name": ctx.startup.study_name,
            "storage_uri": ctx.startup.storage_uri,
            "params": result.params,
        },
    )

    atomic_write_json(
        trial_metrics_path,
        {
            "run_ts": ctx.startup.run_ts,
            "trial_number": result.trial_number,
            "trial_dir": str(trial_dir),
            "status": result.status,
            "score": result.score,
            "raw_metrics": result.raw_metrics,
            "acceptance_flags": result.acceptance_flags,
            "score_terms": {k: float(result.score_terms.get(k, 0.0)) for k in SCORE_TERMS_KEYS},
            "exit_codes": result.exit_codes,
            "timings": result.timings,
            "failure_reason": result.failure_reason,
            "failed_step": result.failed_step,
            "dry_run": result.dry_run,
            "trial_dir_collision_suffix": result.trial_dir_collision_suffix,
        },
    )

    write_trial_status(trial_status_path, trial_status_payload)


def update_best_tracking(ctx: CampaignContext, result: TrialResult) -> None:
    if result.status in {"ok", "warn_checkmesh_exit_nonzero"}:
        ctx.successful_meshes += 1
        if (ctx.best_score_so_far is None) or (float(result.score) < float(ctx.best_score_so_far)):
            ctx.best_score_so_far = float(result.score)
            ctx.best_trial_number = int(result.trial_number)
            ctx.state["last_success_trial"] = int(result.trial_number)
            ctx.state["last_success_score"] = float(result.score)
    ctx.completed_trials += 1
    ctx.save_state()


def notify_trial_result(ctx: CampaignContext, result: TrialResult) -> None:
    run_ts = ctx.startup.run_ts
    top_terms = top_score_terms_summary(result.score_terms)
    if result.status == "dry_run":
        return
    if result.status in {"ok", "warn_checkmesh_exit_nonzero"}:
        msg = (
            f"RUN_TS={run_ts}\n"
            f"trial={result.trial_number} status={result.status}\n"
            f"score={result.score:.3f}\n"
            f"cells={result.raw_metrics.get('total_cells', '?')} under={result.raw_metrics.get('N_underdeterminedCells', '?')} "
            f"lowW={result.raw_metrics.get('N_lowWeightFaces', '?')}\n"
            f"nO70={result.raw_metrics.get('N_faces_nonOrtho_gt_70', '?')} warp={result.raw_metrics.get('N_warpedFaces', '?')}\n"
            f"flags={acceptance_flags_summary(result.acceptance_flags)}\n"
            f"terms={top_terms}\n"
            f"best={ctx.best_score_so_far if ctx.best_score_so_far is not None else float(result.score):.3f}\n"
            f"case={result.trial_dir.name}"
        )
        title = f"MESH trial {result.trial_number} {'OK' if result.status == 'ok' else 'WARN'}"
        ctx.notifier.success(title, msg)
        return

    redacted_reason = redact_notification_text(result.failure_reason or "")
    msg = (
        f"RUN_TS={run_ts}\n"
        f"trial={result.trial_number} status={result.status}\n"
        f"failed_step={result.failed_step or 'unknown'}\n"
        f"score={result.score:.3g}\n"
        f"reason={redacted_reason if redacted_reason else 'n/a'}\n"
        f"terms={top_terms}\n"
        f"case={result.trial_dir.name if result.trial_dir else 'n/a'}"
    )
    ctx.notifier.failure(f"MESH trial {result.trial_number} FAIL", msg)


def execute_trial(
    ctx: CampaignContext,
    trial_number: int,
    params: Dict[str, Any],
) -> TrialResult:
    out_root = ctx.paths.out_root
    trial_dir, collision_suffix = build_trial_dir(out_root, ctx.startup.run_ts, trial_number)
    cmds = trial_commands()
    trial_status_path = trial_dir / "trial_status.json"
    start_wall = time.monotonic()

    exit_codes: Dict[str, Optional[int]] = {k: None for k in EXIT_CODE_KEYS}
    timings: Dict[str, Optional[float]] = {k: None for k in TIMING_KEYS}
    raw_metrics: Dict[str, Any] = {k: None for k in RAW_METRIC_KEYS}
    acceptance_flags = {k: False for k in ACCEPTANCE_FLAG_KEYS}
    score_terms = zero_score_terms()
    status = "failed_preflight"
    score = 1.0e9
    failure_reason: Optional[str] = None
    failed_step: Optional[str] = None
    dry_run = bool(ctx.args.dry_run)

    try:
        ctx.write_inflight(trial_number, trial_dir, "copy")

        if trial_dir.exists():
            raise RuntimeError(
                f"failed_copy: trial directory already exists unexpectedly: {trial_dir}"
            )

        try:
            copy_template_case(Path(ctx.startup.template_case_dir), trial_dir, ctx.args.copy_mode)
            verify_trial_dir_minima(trial_dir)
        except Exception as exc:
            raise RuntimeError(f"failed_copy: {exc}") from exc

        write_trial_status(
            trial_status_path,
            {
                "status": "running",
                "stage": "copy",
                "run_ts": ctx.startup.run_ts,
                "trial_number": trial_number,
                "trial_dir": str(trial_dir),
                "copy_mode": ctx.args.copy_mode,
                "created_at": now_iso(),
            },
        )

        write_trial_readme(
            trial_dir / "TRIAL_README.txt",
            Path(ctx.startup.template_case_dir),
            ctx.startup.run_ts,
            trial_number,
            ctx.startup.storage_uri,
            ctx.startup.study_name,
            params,
            cmds,
        )

        atomic_write_json(
            trial_dir / "trial_params.json",
            {
                "run_ts": ctx.startup.run_ts,
                "trial_number": trial_number,
                "params": params,
                "study_name": ctx.startup.study_name,
                "storage_uri": ctx.startup.storage_uri,
                "copy_mode": ctx.args.copy_mode,
                "dry_run": dry_run,
            },
        )

        ctx.write_inflight(trial_number, trial_dir, "edit")
        write_trial_status(
            trial_status_path,
            {
                "status": "running",
                "stage": "edit",
                "run_ts": ctx.startup.run_ts,
                "trial_number": trial_number,
                "trial_dir": str(trial_dir),
            },
        )

        edit_diagnostics = edit_snappy_hex_mesh_dict(
            trial_dir / "system" / "snappyHexMeshDict",
            params=params,
            search_space=ctx.search_space,
            editing_spec=ctx.editing_spec,
        )

        if dry_run:
            status = "dry_run"
            score = 0.0
            failure_reason = None
            failed_step = None
            raw_metrics.update(
                {
                    "total_cells": 0,
                    "N_faces_nonOrtho_gt_70": 0,
                    "N_warpedFaces": 0,
                    "N_underdeterminedCells": 0,
                    "N_lowWeightFaces": 0,
                }
            )
            acceptance_flags = {k: True for k in ACCEPTANCE_FLAG_KEYS}
            timings["total_s"] = float(time.monotonic() - start_wall)
            write_trial_artifacts(
                ctx,
                TrialResult(
                    trial_number=trial_number,
                    trial_dir=trial_dir,
                    trial_dir_collision_suffix=collision_suffix,
                    status=status,
                    score=score,
                    params=params,
                    raw_metrics=raw_metrics,
                    acceptance_flags=acceptance_flags,
                    score_terms=score_terms,
                    exit_codes=exit_codes,
                    timings=timings,
                    failure_reason=failure_reason,
                    failed_step=failed_step,
                    dry_run=True,
                ),
                trial_dir,
                {
                    "status": status,
                    "stage": "complete",
                    "run_ts": ctx.startup.run_ts,
                    "trial_number": trial_number,
                    "trial_dir": str(trial_dir),
                    "dry_run": True,
                    "edit_diagnostics": edit_diagnostics,
                    "updated_at": now_iso(),
                },
            )
            ctx.clear_inflight()
            result = TrialResult(
                trial_number=trial_number,
                trial_dir=trial_dir,
                trial_dir_collision_suffix=collision_suffix,
                status=status,
                score=score,
                params=params,
                raw_metrics=raw_metrics,
                acceptance_flags=acceptance_flags,
                score_terms=score_terms,
                exit_codes=exit_codes,
                timings=timings,
                failure_reason=failure_reason,
                failed_step=failed_step,
                dry_run=True,
            )
            finalize_trial_logging(ctx, result)
            return result

        # blockMesh
        ctx.write_inflight(trial_number, trial_dir, "run", {"command": "blockMesh"})
        rc, elapsed = run_command_logged(cmds[0], trial_dir, trial_dir / "log.blockMesh")
        exit_codes["blockMesh_exit_code"] = rc
        timings["blockMesh_s"] = elapsed
        if rc != 0:
            status = "failed_command"
            score_terms["failure_penalty_term"] = 1.0e9
            score = 1.0e9
            failure_reason = f"blockMesh exit code {rc}"
            failed_step = "blockMesh"
            raise RuntimeError(failure_reason)

        # snappyHexMesh
        ctx.write_inflight(trial_number, trial_dir, "run", {"command": "snappyHexMesh"})
        rc, elapsed = run_command_logged(cmds[1], trial_dir, trial_dir / "log.snappy")
        exit_codes["snappyHexMesh_exit_code"] = rc
        timings["snappyHexMesh_s"] = elapsed
        if rc != 0:
            status = "failed_command"
            score_terms["failure_penalty_term"] = 1.0e9
            score = 1.0e9
            failure_reason = f"snappyHexMesh exit code {rc}"
            failed_step = "snappyHexMesh"
            raise RuntimeError(failure_reason)

        # checkMesh
        ctx.write_inflight(trial_number, trial_dir, "checkMesh")
        rc, elapsed = run_command_logged(cmds[2], trial_dir, trial_dir / "log.checkMesh")
        exit_codes["checkMesh_exit_code"] = rc
        timings["checkMesh_s"] = elapsed

        log_text = (trial_dir / "log.checkMesh").read_text(encoding="utf-8", errors="replace")
        parsed_metrics, parse_errors = parse_checkmesh_metrics(log_text, ctx.log_regex)
        raw_metrics.update(parsed_metrics)

        if parse_errors:
            status = "failed_parse"
            score_terms["failure_penalty_term"] = 1.0e9
            score = 1.0e9
            failure_reason = f"missing required metrics: {', '.join(parse_errors)}"
            failed_step = "checkMesh_parse"
        else:
            ctx.write_inflight(trial_number, trial_dir, "score")
            score, score_terms, acceptance_flags = compute_score(
                parsed_metrics,
                checkmesh_exit_penalty=(ctx.args.checkmesh_exit_penalty if rc != 0 else 0.0),
            )
            status = "warn_checkmesh_exit_nonzero" if rc != 0 else "ok"
            failure_reason = None
            failed_step = None

        timings["total_s"] = float(time.monotonic() - start_wall)

        result = TrialResult(
            trial_number=trial_number,
            trial_dir=trial_dir,
            trial_dir_collision_suffix=collision_suffix,
            status=status,
            score=float(score),
            params=params,
            raw_metrics=raw_metrics,
            acceptance_flags=acceptance_flags,
            score_terms=score_terms,
            exit_codes=exit_codes,
            timings=timings,
            failure_reason=failure_reason,
            failed_step=failed_step,
            dry_run=False,
        )

        write_trial_artifacts(
            ctx,
            result,
            trial_dir,
            {
                "status": status,
                "stage": "complete",
                "run_ts": ctx.startup.run_ts,
                "trial_number": trial_number,
                "trial_dir": str(trial_dir),
                "failure_reason": failure_reason,
                "failed_step": failed_step,
                "edit_diagnostics": edit_diagnostics,
                "exit_codes": exit_codes,
                "timings": timings,
                "score": result.score,
            },
        )

        ctx.clear_inflight()
        finalize_trial_logging(ctx, result)
        return result

    except Exception as exc:
        if failure_reason is None:
            err_text = str(exc) or exc.__class__.__name__
            if err_text.startswith("failed_edit:"):
                status = "failed_edit"
                failed_step = "snappyHexMeshDict_edit"
            elif err_text.startswith("failed_copy:"):
                status = "failed_copy"
                failed_step = "copy"
            elif status not in {"failed_command", "failed_parse"}:
                status = "failed_preflight"
                failed_step = failed_step or "trial_setup"
            failure_reason = err_text
        score_terms["failure_penalty_term"] = 1.0e9
        score = 1.0e9
        timings["total_s"] = float(time.monotonic() - start_wall)

        trial_dir.mkdir(parents=True, exist_ok=True)
        result = TrialResult(
            trial_number=trial_number,
            trial_dir=trial_dir,
            trial_dir_collision_suffix=collision_suffix,
            status=status,
            score=float(score),
            params=params,
            raw_metrics=raw_metrics,
            acceptance_flags=acceptance_flags,
            score_terms=score_terms,
            exit_codes=exit_codes,
            timings=timings,
            failure_reason=failure_reason,
            failed_step=failed_step,
            dry_run=dry_run,
        )
        write_trial_artifacts(
            ctx,
            result,
            trial_dir,
            {
                "status": status,
                "stage": "complete",
                "run_ts": ctx.startup.run_ts,
                "trial_number": trial_number,
                "trial_dir": str(trial_dir),
                "failure_reason": failure_reason,
                "failed_step": failed_step,
                "exit_codes": exit_codes,
                "timings": timings,
                "traceback": traceback.format_exc(),
            },
        )
        # Keep inflight marker if process truly crashes; for handled exceptions, clear to avoid limbo.
        ctx.clear_inflight()
        finalize_trial_logging(ctx, result)
        return result


def finalize_trial_logging(ctx: CampaignContext, result: TrialResult) -> None:
    row = flatten_trial_for_summary(ctx, result)
    csv_append_row(ctx.paths.summary_csv, ctx.summary_columns, row)
    ctx.append_runs_index(
        {
            "event": "trial",
            "ts_iso": now_iso(),
            "run_ts": ctx.startup.run_ts,
            "study_name": ctx.startup.study_name,
            "storage_uri": ctx.startup.storage_uri,
            "trial_number": result.trial_number,
            "trial_dir": str(result.trial_dir),
            "trial_dir_basename": result.trial_dir.name,
            "status": result.status,
            "score": result.score,
            "params": result.params,
            "raw_metrics": result.raw_metrics,
            "acceptance_flags": result.acceptance_flags,
            "score_terms": result.score_terms,
            "exit_codes": result.exit_codes,
            "timings": result.timings,
            "failure_reason": result.failure_reason,
            "failed_step": result.failed_step,
            "dry_run": result.dry_run,
        }
    )
    ctx.log_event(
        "trial_end",
        f"trial {result.trial_number} {result.status}",
        trial_number=result.trial_number,
        status=result.status,
        score=result.score,
        trial_dir=str(result.trial_dir),
        failed_step=result.failed_step,
        failure_reason=result.failure_reason,
        score_terms_top3=top_score_terms_summary(result.score_terms),
    )
    update_best_tracking(ctx, result)
    notify_trial_result(ctx, result)


def objective_factory(ctx: CampaignContext):
    def _objective(trial: Any) -> float:
        params = sample_params_from_trial(trial, ctx.search_space)
        result = execute_trial(ctx, int(trial.number), params)
        # Persist a compact status in Optuna trial attrs for traceability.
        try:
            trial.set_user_attr("status", result.status)
            trial.set_user_attr("trial_dir", str(result.trial_dir))
            trial.set_user_attr("run_ts", ctx.startup.run_ts)
            trial.set_user_attr("score_terms_top3", top_score_terms_summary(result.score_terms))
        except Exception:
            pass
        return float(result.score)

    return _objective


def startup_record(ctx: CampaignContext, recovery_summary: Dict[str, Any]) -> None:
    payload = {
        "run_ts": ctx.startup.run_ts,
        "study_name": ctx.startup.study_name,
        "storage_uri": ctx.startup.storage_uri,
        "db_path": ctx.startup.db_path,
        "study_fingerprint": ctx.startup.study_fingerprint,
        "template_case_dir": ctx.startup.template_case_dir,
        "campaign_output_root": ctx.startup.campaign_output_root,
        "instructions_json": ctx.startup.instructions_json,
        "instructions_hash": ctx.startup.instructions_hash,
        "scoring_config_hash": ctx.startup.scoring_config_hash,
        "startup_warnings": ctx.startup.startup_warnings,
        "recovery_summary": recovery_summary,
        "args": sanitized_args_for_logs(ctx.args),
    }
    ctx.log_event("startup", "campaign startup", **payload)
    ctx.append_runs_index({"event": "startup", "ts_iso": now_iso(), **payload})
    ctx.save_state()


def notify_campaign_start(ctx: CampaignContext) -> None:
    warning_count = len(ctx.startup.startup_warnings)
    msg = (
        f"run_ts={ctx.startup.run_ts}\n"
        f"study={ctx.startup.study_name}\n"
        f"n_trials={1 if ctx.args.single else ctx.args.n_trials}\n"
        f"fingerprint={ctx.startup.study_fingerprint[:12]}\n"
        f"warning_count={warning_count}"
    )
    ctx.notifier.start("MeshOpt Start", msg)


def notify_campaign_termination(
    ctx: CampaignContext, reason: str, exc: Optional[BaseException] = None
) -> None:
    best_score = ctx.best_score_so_far
    best_trial = ctx.best_trial_number
    msg_lines = [
        f"termination_reason={reason}",
        f"run_ts={ctx.startup.run_ts}",
        f"study={ctx.startup.study_name}",
        f"completed_trials={ctx.completed_trials}",
        f"successful_meshes={ctx.successful_meshes}",
        f"best_score={best_score if best_score is not None else 'n/a'}",
        f"best_trial={best_trial if best_trial is not None else 'n/a'}",
    ]
    if exc is not None:
        msg_lines.append(f"error_type={exc.__class__.__name__}")
    title = {
        "completed": "MeshOpt Finished",
        "no_valid_trials": "MeshOpt Finished",
        "keyboard_interrupt": "MeshOpt Interrupted",
        "exception": "MeshOpt Error",
    }.get(reason, "MeshOpt Finished")
    ctx.notifier.termination(title, "\n".join(msg_lines))


def maybe_record_template_guard_result(ctx: CampaignContext) -> None:
    ok, mismatches = verify_template_guard(ctx.template_guard)
    if not ok:
        msg = f"template guard mismatch: {mismatches}"
        ctx.state.setdefault("startup_warnings", []).append(msg)
        ctx.log_event("template_guard_warn", msg, mismatches=mismatches)


def import_optuna():
    try:
        import optuna  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"optuna is required but could not be imported: {exc}") from exc
    return optuna


def build_campaign_paths(
    args: argparse.Namespace, run_ts: str, storage_uri: str, db_path: Optional[Path]
) -> CampaignPaths:
    out_root = Path(args.out_root).expanduser().resolve()
    logs_dir = out_root / "BO_logs"
    return CampaignPaths(
        out_root=out_root,
        logs_dir=logs_dir,
        summary_csv=logs_dir / "meshing_summary.csv",
        run_csv=logs_dir / f"BO_run_{run_ts}.csv",
        runs_jsonl=logs_dir / "runs.jsonl",
        inflight_json=logs_dir / "meshing_inflight.json",
        state_json=logs_dir / "meshing_resume_state.json",
        db_path=db_path.resolve() if db_path else None,
        storage_uri=storage_uri,
    )


def preflight(
    args: argparse.Namespace, notifier: Notifier
) -> Tuple[Dict[str, Any], CampaignPaths, StartupMeta, Optional[Dict[str, Any]]]:
    instructions_path = Path(args.instructions_json).expanduser().resolve()
    instructions = load_instructions(instructions_path)

    run_ts = now_run_ts()
    out_root = Path(args.out_root).expanduser().resolve()
    startup_warnings = prepare_output_root(args, out_root, notifier)
    validate_template_and_paths(Path(args.template_case_dir).expanduser().resolve(), out_root)
    validate_runtime_requirements(args)

    logs_dir = out_root / "BO_logs"
    storage_uri, db_path = resolve_storage(args, logs_dir)
    paths = build_campaign_paths(args, run_ts, storage_uri, db_path)

    instructions_hash, scoring_hash = compute_instruction_identifiers(
        instructions_path, instructions
    )
    edit_scope = derive_edit_scope(instructions)
    study_fingerprint = compute_study_fingerprint(
        template_case_dir=Path(args.template_case_dir).expanduser().resolve(),
        instructions_hash=instructions_hash,
        scoring_hash=scoring_hash,
        edit_scope=edit_scope,
    )

    startup = StartupMeta(
        run_ts=run_ts,
        study_name=args.study_name,
        storage_uri=storage_uri,
        db_path=str(paths.db_path) if paths.db_path else None,
        template_case_dir=str(Path(args.template_case_dir).expanduser().resolve()),
        campaign_output_root=str(out_root),
        instructions_json=str(instructions_path),
        instructions_hash=instructions_hash,
        scoring_config_hash=scoring_hash,
        study_fingerprint=study_fingerprint,
        edit_scope=edit_scope,
        startup_warnings=startup_warnings,
    )

    previous_state = load_previous_state_for_resume(paths.state_json)
    return instructions, paths, startup, previous_state


def create_or_load_study(ctx: CampaignContext):
    optuna = import_optuna()
    sampler_seed = int(ctx.optimizer_cfg.get("seed", 1337))
    sampler = optuna.samplers.TPESampler(seed=sampler_seed)
    load_if_exists = bool(ctx.args.resume or ctx.args.recover)
    study = optuna.create_study(
        study_name=ctx.startup.study_name,
        storage=ctx.startup.storage_uri,
        direction=str(ctx.optimizer_cfg.get("direction", "minimize")),
        sampler=sampler,
        load_if_exists=load_if_exists,
    )
    return optuna, study


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    notifier = build_notifier(args)

    ctx: Optional[CampaignContext] = None
    termination_reason = "completed"
    caught_exc: Optional[BaseException] = None

    try:
        instructions, paths, startup, previous_state = preflight(args, notifier)
        ctx = CampaignContext(
            args=args, instructions=instructions, paths=paths, startup=startup, notifier=notifier
        )
        check_resume_fingerprint(args, previous_state, startup)
        recovery_summary = reconcile_inflight(ctx)
        startup_record(ctx, recovery_summary)

        optuna, study = create_or_load_study(ctx)
        if args.single:
            fixed = single_trial_default_params(ctx.search_space)
            study.enqueue_trial(fixed)
            ctx.log_event("single_enqueue", "enqueued fixed single trial", params=fixed)

        notify_campaign_start(ctx)

        n_trials = 1 if args.single else int(args.n_trials)
        objective = objective_factory(ctx)
        study.optimize(objective, n_trials=n_trials, n_jobs=1)

        if ctx.successful_meshes == 0 and not args.dry_run:
            termination_reason = "no_valid_trials"
        else:
            termination_reason = "completed"

        # Template guard best-effort warning (optional hardening).
        maybe_record_template_guard_result(ctx)
        ctx.log_event(
            "termination",
            f"campaign {termination_reason}",
            status=termination_reason,
            completed_trials=ctx.completed_trials,
            successful_meshes=ctx.successful_meshes,
            best_score=ctx.best_score_so_far,
            best_trial=ctx.best_trial_number,
        )
        ctx.append_runs_index(
            {
                "event": "termination",
                "ts_iso": now_iso(),
                "run_ts": ctx.startup.run_ts,
                "termination_reason": termination_reason,
                "completed_trials": ctx.completed_trials,
                "successful_meshes": ctx.successful_meshes,
                "best_score": ctx.best_score_so_far,
                "best_trial": ctx.best_trial_number,
            }
        )
        ctx.save_state()
        notify_campaign_termination(ctx, termination_reason)
        return 0

    except KeyboardInterrupt as exc:
        termination_reason = "keyboard_interrupt"
        caught_exc = exc
        if ctx is not None:
            try:
                ctx.log_event("termination", "keyboard interrupt", status=termination_reason)
                ctx.append_runs_index(
                    {
                        "event": "termination",
                        "ts_iso": now_iso(),
                        "run_ts": ctx.startup.run_ts,
                        "termination_reason": termination_reason,
                    }
                )
                ctx.save_state()
            except Exception:
                pass
            notify_campaign_termination(ctx, termination_reason, exc=exc)
        else:
            notifier.termination("MeshOpt Interrupted", "startup interrupted")
        return 130

    except Exception as exc:
        termination_reason = "exception"
        caught_exc = exc
        if ctx is not None:
            try:
                ctx.log_event(
                    "termination",
                    f"exception: {exc}",
                    status=termination_reason,
                    error=str(exc),
                    traceback=traceback.format_exc(),
                )
                ctx.append_runs_index(
                    {
                        "event": "termination",
                        "ts_iso": now_iso(),
                        "run_ts": ctx.startup.run_ts,
                        "termination_reason": termination_reason,
                        "error": str(exc),
                    }
                )
                ctx.save_state()
            except Exception:
                pass
            notify_campaign_termination(ctx, termination_reason, exc=exc)
        else:
            notifier.termination("MeshOpt Error", "startup failed; see local logs")
        print(f"[error] {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1

    finally:
        # `caught_exc` is intentionally retained for debugging if this script is embedded.
        _ = caught_exc


if __name__ == "__main__":
    raise SystemExit(main())
