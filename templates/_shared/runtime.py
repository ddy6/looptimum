from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ModuleNotFoundError:  # pragma: no cover - non-POSIX environments only.
    fcntl = None


DEFAULT_LOCK_TIMEOUT_SECONDS = 45.0
DEFAULT_MAX_PENDING_AGE_SECONDS = 86400.0
_ATOMIC_FAIL_BASENAME_ENV = "LOOPTIMUM_TEST_ATOMIC_FAIL_BASENAME"

DEFAULT_PATHS = {
    "state_file": "state/bo_state.json",
    "observations_csv": "state/observations.csv",
    "acquisition_log_file": "state/acquisition_log.jsonl",
    "event_log_file": "state/event_log.jsonl",
    "trials_dir": "state/trials",
    "lock_file": "state/.looptimum.lock",
    "report_json_file": "state/report.json",
    "report_md_file": "state/report.md",
}


def _as_positive_float(value: Any, *, field_name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric, got: {value!r}")
    out = float(value)
    if out < 0.0:
        raise ValueError(f"{field_name} must be >= 0, got: {value!r}")
    return out


def resolve_runtime_paths(project_root: Path, paths_cfg: dict[str, Any]) -> dict[str, Path]:
    resolved: dict[str, Path] = {}
    for key, default_rel in DEFAULT_PATHS.items():
        rel = paths_cfg.get(key, default_rel)
        resolved[key] = (project_root / str(rel)).resolve()
    return resolved


def resolve_lock_timeout_seconds(cfg: dict[str, Any], cli_override: float | None = None) -> float:
    if cli_override is not None:
        return _as_positive_float(cli_override, field_name="--lock-timeout-seconds")
    raw = cfg.get("lock_timeout_seconds", DEFAULT_LOCK_TIMEOUT_SECONDS)
    return _as_positive_float(raw, field_name="lock_timeout_seconds")


def resolve_max_pending_age_seconds(cfg: dict[str, Any]) -> float | None:
    raw = cfg.get("max_pending_age_seconds", DEFAULT_MAX_PENDING_AGE_SECONDS)
    if raw is None:
        return None
    value = _as_positive_float(raw, field_name="max_pending_age_seconds")
    if value == 0.0:
        return None
    return value


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    tmp.write_text(text, encoding="utf-8")
    fail_basename = os.getenv(_ATOMIC_FAIL_BASENAME_ENV, "").strip()
    if fail_basename and path.name == fail_basename:
        raise OSError(f"Injected atomic write failure for {path}")
    tmp.replace(path)


def atomic_write_json(path: Path, payload: Any, *, indent: int = 2) -> None:
    atomic_write_text(path, json.dumps(payload, indent=indent))


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def load_json_dict(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}, got {type(data).__name__}")
    return data


def pending_age_seconds(pending_entry: dict[str, Any], *, now: float) -> float:
    suggested_at = pending_entry.get("suggested_at")
    last_heartbeat_at = pending_entry.get("last_heartbeat_at")

    last_touch: float | None = None
    for raw in (suggested_at, last_heartbeat_at):
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            candidate = float(raw)
            if last_touch is None or candidate > last_touch:
                last_touch = candidate

    if last_touch is None:
        return 0.0
    return max(0.0, now - last_touch)


def trial_dir(trials_root: Path, trial_id: int) -> Path:
    return trials_root / f"trial_{int(trial_id)}"


def trial_manifest_path(trials_root: Path, trial_id: int) -> Path:
    return trial_dir(trials_root, trial_id) / "manifest.json"


def load_trial_manifest(trials_root: Path, trial_id: int) -> dict[str, Any]:
    path = trial_manifest_path(trials_root, trial_id)
    if path.exists():
        return load_json_dict(path)
    return {}


def save_trial_manifest(trials_root: Path, trial_id: int, manifest: dict[str, Any]) -> Path:
    root = trial_dir(trials_root, trial_id)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "manifest.json"
    atomic_write_json(path, manifest, indent=2)
    return path


class ExclusiveFileLock:
    def __init__(
        self,
        path: Path,
        *,
        timeout_seconds: float,
        fail_fast: bool = False,
        poll_interval_seconds: float = 0.1,
    ) -> None:
        self.path = path
        self.timeout_seconds = max(0.0, float(timeout_seconds))
        self.fail_fast = bool(fail_fast)
        self.poll_interval_seconds = max(0.01, float(poll_interval_seconds))
        self._handle: Any | None = None
        self.wait_seconds = 0.0

    def acquire(self) -> None:
        if fcntl is None:  # pragma: no cover - non-POSIX environments only.
            raise RuntimeError("File locking requires POSIX fcntl support.")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+", encoding="utf-8")
        start = time.monotonic()
        deadline = start + self.timeout_seconds

        while True:
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                now = time.monotonic()
                timed_out = now >= deadline
                if self.fail_fast or timed_out:
                    self._handle.close()
                    self._handle = None
                    mode = "fail-fast" if self.fail_fast else "timeout"
                    waited = now - start
                    raise TimeoutError(
                        f"Could not acquire lock ({mode}) at {self.path} after {waited:.2f}s"
                    ) from exc
                time.sleep(self.poll_interval_seconds)

        self.wait_seconds = time.monotonic() - start
        meta = {
            "pid": os.getpid(),
            "acquired_at": time.time(),
            "wait_seconds": self.wait_seconds,
        }
        self._handle.seek(0)
        self._handle.truncate(0)
        self._handle.write(json.dumps(meta, sort_keys=True))
        self._handle.flush()

    def release(self) -> None:
        if self._handle is None:
            return
        if fcntl is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None


@contextmanager
def hold_exclusive_lock(
    path: Path, *, timeout_seconds: float, fail_fast: bool = False
) -> Iterator[ExclusiveFileLock]:
    lock = ExclusiveFileLock(path, timeout_seconds=timeout_seconds, fail_fast=fail_fast)
    lock.acquire()
    try:
        yield lock
    finally:
        lock.release()
