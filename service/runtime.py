from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Iterator, cast

from service.models import CampaignDetailResponse, CampaignRecord
from service.registry import InvalidCampaignRootError, ServiceRegistryError, validate_campaign_root

JSONDict = dict[str, Any]


class ReportNotGeneratedError(ServiceRegistryError):
    pass


class RuntimeArtifactError(ServiceRegistryError):
    pass


@contextmanager
def _prepend_sys_path(path: Path) -> Iterator[None]:
    inserted = False
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)
        inserted = True
    try:
        yield
    finally:
        if inserted:
            try:
                sys.path.remove(path_text)
            except ValueError:
                pass


@lru_cache(maxsize=32)
def _load_runtime_module(run_bo_path: str) -> ModuleType:
    module_path = Path(run_bo_path).resolve()
    spec = importlib.util.spec_from_file_location(
        f"looptimum_service_runtime_{abs(hash(module_path))}",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeArtifactError(f"unable to load runtime entrypoint: {module_path}")
    module = importlib.util.module_from_spec(spec)
    with _prepend_sys_path(module_path.parent):
        spec.loader.exec_module(module)
    return module


def _load_campaign_runtime(root: Path) -> tuple[Path, ModuleType]:
    validated_root = validate_campaign_root(root)
    run_bo_path = validated_root / "run_bo.py"
    if not run_bo_path.exists():
        raise InvalidCampaignRootError("campaign root missing required files: run_bo.py")
    return validated_root, _load_runtime_module(str(run_bo_path))


def _load_runtime_cfg(root: Path, runtime_module: ModuleType) -> tuple[JSONDict, dict[str, Path]]:
    runtime_any = cast(Any, runtime_module)
    cfg_doc, _ = runtime_any.load_contract_document(root, "bo_config")
    if not isinstance(cfg_doc, dict):
        raise InvalidCampaignRootError("bo_config must be an object")
    paths = runtime_any._runtime_paths(root, cfg_doc)
    return cast(JSONDict, cfg_doc), cast(dict[str, Path], paths)


def build_status_payload(root: Path) -> JSONDict:
    validated_root, runtime_module = _load_campaign_runtime(root)
    runtime_any = cast(Any, runtime_module)
    cfg, paths = _load_runtime_cfg(validated_root, runtime_module)
    state = cast(JSONDict, runtime_any.load_state(paths["state_file"]))
    max_pending_age = runtime_any.resolve_max_pending_age_seconds(cfg)
    worker_leases_enabled = runtime_any.resolve_worker_leases_enabled(cfg)
    status_payload_fn = runtime_any._status_payload
    signature = inspect.signature(status_payload_fn)
    if "botorch_feature_flag" in signature.parameters:
        botorch_feature_flag = runtime_any.use_botorch_backend(
            SimpleNamespace(enable_botorch_gp=False),
            cfg,
        )
        return cast(
            JSONDict,
            status_payload_fn(
                validated_root,
                state,
                paths,
                max_pending_age,
                botorch_feature_flag=botorch_feature_flag,
                worker_leases_enabled=worker_leases_enabled,
            ),
        )
    return cast(
        JSONDict,
        status_payload_fn(
            validated_root,
            state,
            paths,
            max_pending_age,
            worker_leases_enabled,
        ),
    )


def load_report_payload(root: Path) -> JSONDict:
    validated_root, runtime_module = _load_campaign_runtime(root)
    _cfg, paths = _load_runtime_cfg(validated_root, runtime_module)
    report_path = paths["report_json_file"]
    if not report_path.exists():
        raise ReportNotGeneratedError(
            f"report.json has not been generated for campaign root: {validated_root}"
        )
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeArtifactError(f"report.json must contain valid JSON: {report_path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeArtifactError(f"report.json must contain a JSON object: {report_path}")
    return cast(JSONDict, payload)


def build_campaign_detail(record: CampaignRecord) -> CampaignDetailResponse:
    validated_root, runtime_module = _load_campaign_runtime(Path(record.root_path))
    _cfg, paths = _load_runtime_cfg(validated_root, runtime_module)
    runtime_any = cast(Any, runtime_module)
    relative_path = runtime_any._relative_path
    return CampaignDetailResponse(
        campaign=record,
        status=build_status_payload(validated_root),
        paths={
            "state_file": relative_path(validated_root, paths["state_file"]),
            "observations_csv": relative_path(validated_root, paths["observations_csv"]),
            "acquisition_log_file": relative_path(validated_root, paths["acquisition_log_file"]),
            "event_log_file": relative_path(validated_root, paths["event_log_file"]),
            "trials_dir": relative_path(validated_root, paths["trials_dir"]),
            "report_json_file": relative_path(validated_root, paths["report_json_file"]),
            "report_md_file": relative_path(validated_root, paths["report_md_file"]),
        },
        artifacts={
            "state_file_exists": paths["state_file"].exists(),
            "report_json_exists": paths["report_json_file"].exists(),
            "report_md_exists": paths["report_md_file"].exists(),
        },
    )
