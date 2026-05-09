# -*- coding: utf-8 -*-
"""
Headless Experiment Runner
=========================

Runs a dataset (YAML episode template or expanded JSONL ticks) against an
`ObservatoryApp` instance and writes paper-friendly metrics to disk.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import time
import contextlib
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from itertools import islice
from pathlib import Path
from typing import Any, Callable, Iterable

from . import dataset as ds
from .expectation_contracts import ExpectationContractEngine, ExpectationContractError
from .io import ExperimentIOError, iter_jsonl, load_yaml_file, sha256_file, write_jsonl
from .metrics import extract_tick_metrics
from .storage import DatasetFileRef, ExperimentStorageError, make_run_dir, resolve_dataset_file, safe_slug
from .auto_tuner import AutoTuner

_ORJSON_MODULE: Any | None = None
_ORJSON_IMPORT_ATTEMPTED = False


EXPERIMENT_DEFAULT_APP_OVERRIDES: dict[str, Any] = {
    # Dataset runs are used as baseline evidence. Keep them on the current
    # growth-era cognition path unless a dataset explicitly asks for rollback.
    "input_chunking_enabled": True,
    "enable_goal_b_char_sa_string_mode": True,
    "induction_projection_mode": "growth",
    "enable_cognitive_stitching": False,
    "cognitive_stitching_stage": "disabled",
}


class ExperimentRunnerError(RuntimeError):
    pass


class ExperimentRunnerCancelled(RuntimeError):
    pass


def _metric_preview_items(value: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return rows
    for item in value[: max(0, int(limit or 0))]:
        if isinstance(item, dict):
            rows.append(copy.deepcopy(item))
    return rows


def _compact_latest_metrics_preview(metrics: dict[str, Any]) -> dict[str, Any]:
    """Small in-memory tick preview for live UI; metrics.jsonl remains the full record."""

    scalar_keys = (
        "tick_index",
        "tick",
        "trace_id",
        "tick_id",
        "tick_source",
        "synthetic_tick",
        "source_dataset_tick_index",
        "dataset_tick_index",
        "input_is_empty",
        "input_len",
        "input_text_preview",
        "input_queue_tick_text_preview",
        "input_queue_submitted_text_preview",
        "input_queue_source_text_preview",
        "external_sa_count",
        "pool_active_item_count",
        "hdb_structure_count",
        "stimulus_wide_candidate_count",
        "timing_total_logic_ms",
        "timing_maintenance_ms",
        "timing_attention_ms",
        "timing_structure_level_ms",
        "timing_cache_neutralization_ms",
        "timing_stimulus_level_ms",
        "timing_induction_and_memory_ms",
        "timing_induction_hdb_propagation_ms",
        "timing_induction_projection_prepare_ms",
        "timing_induction_target_apply_ms",
        "timing_iesm_ms",
        "timing_action_ms",
        "timing_runner_cycle_wall_ms",
        "timing_runner_lock_wait_ms",
        "timing_runner_metrics_extract_ms",
    )
    preview: dict[str, Any] = {key: copy.deepcopy(metrics.get(key)) for key in scalar_keys if key in metrics}
    for key in (
        "pool_er_top5",
        "pool_ev_top5",
        "pool_cp_top5",
        "pool_er_structure_top5",
        "pool_ev_structure_top5",
        "pool_cp_structure_top5",
        "attention_top5",
    ):
        preview[key] = _metric_preview_items(metrics.get(key), limit=5)
    for key in (
        "pool_er_structure_top5_same_as_top5",
        "pool_ev_structure_top5_same_as_top5",
        "pool_cp_structure_top5_same_as_top5",
    ):
        if key in metrics:
            preview[key] = int(metrics.get(key, 0) or 0)
    preview["preview_source"] = "experiment_runner_memory"
    return preview


class ProgressLockContext:
    """Wrap a lock so long waits are visible to the experiment job UI."""

    def __init__(
        self,
        lock: Any,
        *,
        progress_cb: Callable[[dict[str, Any]], None] | None,
        stage: str,
        label: str = "",
        poll_sec: float = 0.01,
        cancel_cb: Callable[[], bool] | None = None,
    ) -> None:
        self._lock = lock
        self._progress_cb = progress_cb
        self._stage = str(stage or "waiting_for_app_lock")
        self._label = str(label or "")
        self._poll_sec = max(0.002, float(poll_sec or 0.01))
        self._cancel_cb = cancel_cb
        self._acquired = False
        self._wait_started_ms = 0
        self._last_emit_ms = 0

    def __enter__(self) -> "ProgressLockContext":
        self._acquired = False
        acquire = getattr(self._lock, "acquire", None)
        if not callable(acquire):
            self._lock.__enter__()
            self._acquired = True
            return self
        self._wait_started_ms = _now_ms()
        while True:
            if self._cancel_cb is not None and self._cancel_cb():
                if self._progress_cb is not None:
                    self._progress_cb(
                        {
                            "status": "cancelled",
                            "stage": "cancelled",
                            "stage_label": "已在等待主循环锁时收到停止请求，运行已取消",
                            "lock_waiting": False,
                            "lock_wait_ms": max(0, _now_ms() - self._wait_started_ms),
                        }
                    )
                raise ExperimentRunnerCancelled("cancelled while waiting for app lock")
            try:
                acquired = bool(acquire(blocking=False))
            except TypeError:
                acquired = bool(acquire(False))
            if acquired:
                self._acquired = True
                waited_ms = max(0, _now_ms() - self._wait_started_ms)
                if waited_ms >= 250 and self._progress_cb is not None:
                    self._progress_cb(
                        {
                            "stage": "running",
                            "stage_label": "已获得主循环锁，继续运行",
                            "lock_waiting": False,
                            "last_lock_wait_ms": waited_ms,
                        }
                    )
                return self
            now_ms = _now_ms()
            if self._progress_cb is not None and (not self._last_emit_ms or now_ms - self._last_emit_ms >= 1000):
                self._last_emit_ms = now_ms
                self._progress_cb(
                    {
                        "stage": self._stage,
                        "stage_label": self._label or "等待主循环锁释放",
                        "lock_waiting": True,
                        "lock_wait_started_at_ms": self._wait_started_ms,
                        "lock_wait_ms": max(0, now_ms - self._wait_started_ms),
                    }
                )
            time.sleep(self._poll_sec)

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if not self._acquired:
            return None
        release = getattr(self._lock, "release", None)
        if callable(release):
            release()
            self._acquired = False
            return None
        result = self._lock.__exit__(exc_type, exc, tb)
        self._acquired = False
        return result


@dataclass(frozen=True)
class RunOptions:
    reset_mode: str = "keep"  # keep | clear_runtime | clear_all
    clean_run: bool = False
    export_json: bool = False
    export_html: bool = False
    # Adaptive auto tuner (self-adaptive parameter tuning)
    auto_tune_enabled: bool = False
    auto_tune_short_term: bool = True
    auto_tune_long_term: bool = True
    # time sensor override during the run (None means keep current runtime config)
    time_sensor_time_basis: str | None = None  # tick | wallclock | None
    tick_interval_sec: float | None = None  # for display only (time_sensor config field)
    max_ticks: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reset_mode": self.reset_mode,
            "clean_run": bool(self.clean_run),
            "export_json": bool(self.export_json),
            "export_html": bool(self.export_html),
            "auto_tune_enabled": bool(self.auto_tune_enabled),
            "auto_tune_short_term": bool(self.auto_tune_short_term),
            "auto_tune_long_term": bool(self.auto_tune_long_term),
            "time_sensor_time_basis": self.time_sensor_time_basis,
            "tick_interval_sec": self.tick_interval_sec,
            "max_ticks": self.max_ticks,
        }


def _now_ms() -> int:
    return int(time.time() * 1000)


def _cancel_run_manifest(
    manifest: dict[str, Any],
    manifest_path: Path | None,
    progress_cb: Callable[[dict[str, Any]], None] | None,
    *,
    run_id: str,
    source_tick_done: int = 0,
    synthetic_tick_done: int = 0,
    executed_tick_done_total: int = 0,
    effective_tick_planned: int | None = None,
    stage_label: str = "已收到停止请求，正在结束运行",
) -> None:
    manifest["status"] = "cancelled"
    manifest["tick_done"] = int(source_tick_done)
    manifest["source_tick_done"] = int(source_tick_done)
    manifest["synthetic_tick_done"] = int(synthetic_tick_done)
    manifest["executed_tick_done_total"] = int(executed_tick_done_total)
    manifest["finished_at_ms"] = _now_ms()
    if manifest_path is not None:
        try:
            _persist_manifest(manifest_path, manifest)
        except Exception:
            pass
    if progress_cb is not None:
        progress_cb(
            {
                "run_id": run_id,
                "status": "cancelled",
                "stage": "cancelled",
                "stage_label": stage_label,
                "tick_done": int(source_tick_done),
                "source_tick_done": int(source_tick_done),
                "synthetic_tick_done": int(synthetic_tick_done),
                "executed_tick_done_total": int(executed_tick_done_total),
                "tick_planned": effective_tick_planned,
            }
        )


def _resolve_runtime_clock_override(
    *,
    started_wall_ms: int,
    executed_tick_done_total: int,
    effective_time_sensor_basis: str | None,
    effective_tick_interval_sec: float | None,
) -> int | None:
    basis = str(effective_time_sensor_basis or "").strip().lower()
    if basis != "tick":
        return None
    if effective_tick_interval_sec is None:
        return None
    try:
        tick_interval_ms = int(round(float(effective_tick_interval_sec) * 1000.0))
    except Exception:
        return None
    if tick_interval_ms <= 0:
        return None
    return int(started_wall_ms) + max(0, int(executed_tick_done_total)) * tick_interval_ms


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _json_dumps_text(payload: Any, *, indent: int | None = None) -> str:
    """Serialize JSON for experiment files, preferring orjson when available."""

    global _ORJSON_MODULE, _ORJSON_IMPORT_ATTEMPTED
    if not _ORJSON_IMPORT_ATTEMPTED:
        try:
            import orjson  # type: ignore

            _ORJSON_MODULE = orjson
        except Exception:
            _ORJSON_MODULE = None
        _ORJSON_IMPORT_ATTEMPTED = True
    if _ORJSON_MODULE is not None:
        try:
            option = 0
            if indent is not None and int(indent or 0) > 0:
                option |= _ORJSON_MODULE.OPT_INDENT_2
            return _ORJSON_MODULE.dumps(payload, option=option).decode("utf-8")
        except Exception:
            pass
    if indent is not None and int(indent or 0) > 0:
        return json.dumps(payload, ensure_ascii=False, indent=int(indent))
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _persist_manifest(path: Path, manifest: dict[str, Any]) -> None:
    try:
        path.write_text(_json_dumps_text(manifest, indent=2), encoding="utf-8")
    except Exception:
        pass


def _append_manifest_error(
    manifest: dict[str, Any],
    exc: BaseException,
    *,
    source_tick_done: int | None = None,
    synthetic_tick_done: int | None = None,
    executed_tick_done_total: int | None = None,
    include_traceback: bool = True,
) -> None:
    manifest.setdefault("errors", [])
    error: dict[str, Any] = {
        "type": type(exc).__name__,
        "message": str(exc),
    }
    if source_tick_done is not None or synthetic_tick_done is not None or executed_tick_done_total is not None:
        error["tick_context"] = {
            "source_tick_done": int(source_tick_done or 0),
            "synthetic_tick_done": int(synthetic_tick_done or 0),
            "executed_tick_done_total": int(executed_tick_done_total or 0),
        }
    if include_traceback:
        tb = traceback.format_exc()
        if tb and tb.strip() and tb.strip() != "NoneType: None":
            error["traceback"] = tb
    manifest["errors"].append(error)


def _format_progress_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _build_default_progress_cb() -> Callable[[dict[str, Any]], None]:
    last_source_tick = -1
    last_executed_tick_total = -1
    last_print_ms = 0
    started_ms = _now_ms()

    def _cb(payload: dict[str, Any]) -> None:
        nonlocal last_source_tick, last_executed_tick_total, last_print_ms
        if not isinstance(payload, dict):
            return
        status = str(payload.get("status", "") or "running")
        source_tick_done = int(payload.get("source_tick_done", payload.get("tick_done", 0)) or 0)
        synthetic_tick_done = int(payload.get("synthetic_tick_done", 0) or 0)
        executed_tick_done_total = int(payload.get("executed_tick_done_total", source_tick_done + synthetic_tick_done) or 0)
        tick_planned_raw = payload.get("tick_planned", None)
        try:
            tick_planned = int(tick_planned_raw) if tick_planned_raw is not None else None
        except Exception:
            tick_planned = None
        is_long_run = tick_planned is None or int(tick_planned or 0) > 20
        now_ms = _now_ms()
        execution_advanced = executed_tick_done_total != last_executed_tick_total
        should_print = False
        if status in {"completed", "stopped_max_ticks", "cancelled", "failed"}:
            should_print = True
        elif not is_long_run:
            should_print = False
        elif source_tick_done <= 1 and source_tick_done != last_source_tick:
            should_print = True
        elif source_tick_done > 0 and source_tick_done % 5 == 0 and source_tick_done != last_source_tick:
            should_print = True
        elif execution_advanced and (now_ms - last_print_ms) >= 5000:
            should_print = True
        if not should_print:
            return
        pct = ""
        if tick_planned and tick_planned > 0:
            pct = f" ({(100.0 * float(source_tick_done) / float(max(1, tick_planned))):.1f}%)"
        tick_source = str(payload.get("tick_source", "dataset") or "dataset")
        tick_index = payload.get("tick_index", None)
        tick_index_text = ""
        if tick_index is not None:
            try:
                tick_index_text = f" | tick={int(tick_index)}"
            except Exception:
                tick_index_text = f" | tick={tick_index}"
        elapsed_sec = max(0.0, float(now_ms - started_ms) / 1000.0)
        elapsed_text = _format_progress_duration(elapsed_sec)
        eta_text = ""
        if tick_planned and tick_planned > 0 and source_tick_done > 0 and source_tick_done < tick_planned:
            avg_source_sec = elapsed_sec / float(max(1, source_tick_done))
            eta_text = f" | eta~{_format_progress_duration(avg_source_sec * float(tick_planned - source_tick_done))}"
        try:
            print(
                f"[Experiment] status={status} | source={source_tick_done}/{tick_planned if tick_planned is not None else '?'}{pct} | synthetic={synthetic_tick_done} | executed={executed_tick_done_total} | source_type={tick_source}{tick_index_text} | elapsed={elapsed_text}{eta_text}",
                flush=True,
            )
        except OSError:
            # Long background runs must not fail just because the host console
            # pipe is closed or refuses a progress line.
            pass
        last_source_tick = source_tick_done
        last_executed_tick_total = executed_tick_done_total
        last_print_ms = now_ms

    return _cb


def _sync_expectation_contract_manifest_aliases(manifest: dict[str, Any]) -> None:
    if not isinstance(manifest, dict):
        return
    snapshot = manifest.get("expectation_contracts", {})
    if not isinstance(snapshot, dict):
        snapshot = {}
        manifest["expectation_contracts"] = snapshot
    for key in (
        "registered_count",
        "success_count",
        "failure_count",
        "synthetic_tick_count",
        "pending_count",
    ):
        try:
            manifest[key] = int(snapshot.get(key, 0) or 0)
        except Exception:
            manifest[key] = 0


def make_run_id(*, dataset_id: str) -> str:
    # Example: exp_smoke_100_v0_20260418_123456_1a2b
    base = safe_slug(dataset_id or "dataset", fallback="dataset")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # small random suffix (deterministic not required; just to avoid collisions)
    suffix = f"{os.getpid() % 10000:04d}"
    return f"exp_{base}_{stamp}_{suffix}"


def _count_jsonl_lines(path: Path) -> int:
    n = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def _safe_hdb_runtime_baseline_snapshot(app: Any, *, trace_id: str) -> dict[str, Any]:
    """
    Capture a lightweight HDB baseline for audit/debug.

    Why:
    - experiment runs can start either from a long-lived persisted HDB or from a
      freshly cleared / isolated HDB
    - this distinction materially changes whether certain structure-level paths
      can compete on early ticks
    - keeping the snapshot in manifest avoids future "runner vs manual" false
      divergences caused by hidden warm-start state
    """

    out: dict[str, Any] = {}
    hdb = getattr(app, "hdb", None)
    if hdb is None:
        return out

    try:
        hdb_config = dict(getattr(hdb, "_config", {}) or {})
        data_dir = str(hdb_config.get("data_dir", "") or "")
        if data_dir:
            out["hdb_data_dir"] = data_dir
    except Exception:
        pass

    try:
        if hasattr(hdb, "get_hdb_snapshot"):
            snapshot_res = hdb.get_hdb_snapshot(
                trace_id=trace_id,
                include_stats=True,
                include_recent_structures=False,
                include_recent_groups=False,
                top_k=0,
            )
            snapshot_data = snapshot_res.get("data", {}) if isinstance(snapshot_res, dict) else {}
            summary = snapshot_data.get("summary", {}) if isinstance(snapshot_data, dict) else {}
            if isinstance(summary, dict):
                out["summary"] = dict(summary)
    except Exception as exc:
        out["snapshot_error"] = str(exc)
    return out


def _compact_auto_tuner_tick_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    compact: dict[str, Any] = {
        "enabled": bool(result.get("enabled", False)),
        "applied": bool(result.get("applied", False)),
        "reason": str(result.get("reason", "") or ""),
        "applied_count": int(result.get("applied_count", 0) or 0),
        }
    updates = []
    snapshots = result.get("snapshots", {}) if isinstance(result.get("snapshots"), dict) else {}
    timing_hotspot = snapshots.get("timing_hotspot", {}) if isinstance(snapshots.get("timing_hotspot"), dict) else {}
    if timing_hotspot:
        compact["timing_hotspot"] = {
            "dominant_group_id": str(timing_hotspot.get("dominant_group_id", "") or ""),
            "dominant_group_label": str(timing_hotspot.get("dominant_group_label", "") or ""),
            "total_hot": bool(timing_hotspot.get("total_hot", False)),
        }
    for item in (result.get("applied_updates") or []):
        if not isinstance(item, dict):
            continue
        updates.append(
            {
                "rule_id": str(item.get("rule_id", "") or ""),
                "param": str(item.get("param", "") or ""),
                "metric_key": str(item.get("metric_key", "") or ""),
                "issue_mode": str(item.get("issue_mode", "") or ""),
                "reason": str(item.get("reason", "") or ""),
                "from": item.get("from"),
                "to": item.get("to"),
            }
        )
    if updates:
        compact["applied_updates"] = updates[:8]
    return compact


def _resolve_time_sensor_runtime_overrides(
    *,
    normalized_doc: dict[str, Any] | None,
    options: RunOptions,
) -> tuple[str | None, float | None]:
    """
    Resolve the effective time-sensor runtime override for this run.

    Priority:
    1. Explicit RunOptions override
    2. Dataset-declared time basis / tick interval
    3. Keep current runtime config (None)
    """

    basis = options.time_sensor_time_basis
    tick_interval_sec = options.tick_interval_sec

    meta_basis = None
    meta_tick_dt_ms = None
    if isinstance(normalized_doc, dict):
        meta_basis = str(normalized_doc.get("time_basis", "") or "").strip().lower() or None
        try:
            raw_tick_dt_ms = normalized_doc.get("tick_dt_ms", None)
            if raw_tick_dt_ms is not None:
                meta_tick_dt_ms = int(raw_tick_dt_ms)
        except Exception:
            meta_tick_dt_ms = None

    if basis not in {"tick", "wallclock"}:
        if meta_basis in {"tick", "wallclock"}:
            basis = meta_basis
        else:
            basis = None

    if tick_interval_sec is None and meta_tick_dt_ms is not None and meta_tick_dt_ms > 0:
        tick_interval_sec = float(meta_tick_dt_ms) / 1000.0

    return basis, tick_interval_sec


def _resolve_dataset_app_config_override(*, normalized_doc: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(normalized_doc, dict):
        return {}
    raw = normalized_doc.get("app_config_override", None)
    if not isinstance(raw, dict):
        return {}
    return copy.deepcopy(raw)


def _experiment_default_overrides_applied(dataset_app_config_override: dict[str, Any]) -> dict[str, bool]:
    dataset_keys = set((dataset_app_config_override or {}).keys())
    return {key: key not in dataset_keys for key in EXPERIMENT_DEFAULT_APP_OVERRIDES.keys()}


def apply_experiment_default_app_overrides(
    app: Any,
    *,
    app_config_override: dict[str, Any] | None = None,
    source: str = "experiment_runner",
    refresh_runtime: bool = True,
) -> dict[str, Any]:
    """Apply the same current-mainline app overrides used by dataset runs.

    The realtime observatory and the headless dataset runner both execute
    `ObservatoryApp.run_cycle()`.  This helper keeps their pre-tick runtime
    baseline aligned so a saved legacy config cannot silently send one entry
    point through an old rollback path.
    """

    override = copy.deepcopy(app_config_override) if isinstance(app_config_override, dict) else {}
    applied_defaults: dict[str, bool] = {}
    changed_keys: list[str] = []
    errors: list[str] = []
    runtime_refresh_applied = False
    cfg = getattr(app, "_config", None)
    if not isinstance(cfg, dict):
        return {
            "source": source,
            "applied": False,
            "runtime_refresh_applied": False,
            "app_config_override": override,
            "app_config_override_keys": sorted(override.keys()),
            "experiment_default_overrides": copy.deepcopy(EXPERIMENT_DEFAULT_APP_OVERRIDES),
            "experiment_default_overrides_applied": _experiment_default_overrides_applied(override),
            "effective_app_baseline": {},
            "baseline_conforms_to_growth_cs_off": False,
            "changed_keys": [],
            "errors": ["app._config is unavailable"],
        }

    for key, value in EXPERIMENT_DEFAULT_APP_OVERRIDES.items():
        applied = key not in override
        applied_defaults[key] = bool(applied)
        if not applied:
            continue
        if cfg.get(key) != value:
            changed_keys.append(key)
        cfg[key] = copy.deepcopy(value)

    for key, value in override.items():
        if cfg.get(key) != value:
            changed_keys.append(str(key))
        cfg[key] = copy.deepcopy(value)

    if refresh_runtime:
        try:
            if hasattr(app, "_apply_runtime_overrides"):
                app._apply_runtime_overrides()  # type: ignore[attr-defined]
                runtime_refresh_applied = True
            else:
                sensor_override = app._sensor_config_override() if hasattr(app, "_sensor_config_override") else {}  # type: ignore[attr-defined]
                sensor = getattr(app, "sensor", None)
                sensor_config = getattr(sensor, "_config", None)
                if isinstance(sensor_config, dict):
                    sensor_config.update(sensor_override)
                    for attr_name in ("_normalizer", "_segmenter", "_scorer", "_echo_mgr"):
                        obj = getattr(sensor, attr_name, None)
                        if hasattr(obj, "update_config"):
                            obj.update_config(sensor_config)
                hdb_override = app._hdb_config_override() if hasattr(app, "_hdb_config_override") else {}  # type: ignore[attr-defined]
                hdb = getattr(app, "hdb", None)
                hdb_config = getattr(hdb, "_config", None)
                if isinstance(hdb_config, dict):
                    hdb_config.update(hdb_override)
                    for attr_name in ("_stimulus", "_cut"):
                        obj = getattr(hdb, attr_name, None)
                        if hasattr(obj, "update_config"):
                            obj.update_config(hdb_config)
                runtime_refresh_applied = True
        except Exception as exc:
            errors.append(str(exc))

    effective_config = {
        key: copy.deepcopy(cfg.get(key))
        for key in EXPERIMENT_DEFAULT_APP_OVERRIDES.keys()
    }
    baseline_conforms = bool(
        str(cfg.get("induction_projection_mode", "")).strip().lower() == "growth"
        and not bool(cfg.get("enable_cognitive_stitching", False))
        and str(cfg.get("cognitive_stitching_stage", "")).strip().lower() == "disabled"
    )
    return {
        "source": source,
        "app_config_override": override,
        "app_config_override_keys": sorted(override.keys()),
        "experiment_default_overrides": copy.deepcopy(EXPERIMENT_DEFAULT_APP_OVERRIDES),
        "experiment_default_overrides_applied": applied_defaults,
        "applied": bool(override or any(applied_defaults.values())),
        "runtime_refresh_applied": bool(runtime_refresh_applied),
        "effective_app_baseline": effective_config,
        "baseline_conforms_to_growth_cs_off": baseline_conforms,
        "changed_keys": sorted(set(changed_keys)),
        "errors": errors,
    }


def load_dataset_ticks(
    *,
    dataset_ref: DatasetFileRef,
    preview_limit: int | None = None,
) -> tuple[str, str, dict[str, Any] | None, Iterable[dict[str, Any]], int | None]:
    """Load dataset ticks generator.

    Returns:
      (dataset_id, dataset_sha256, normalized_dataset_doc, ticks_iter, total_ticks)
    - For YAML: normalized_dataset_doc is returned and total_ticks is exact.
    - For JSONL: normalized_dataset_doc is None; total_ticks is best-effort (counts lines).
    """

    path = resolve_dataset_file(dataset_ref)
    if not path.exists() or not path.is_file():
        raise ExperimentRunnerError(f"Dataset file not found: {path}")

    digest = sha256_file(path)
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        raw = load_yaml_file(path)
        normalized = ds.validate_and_normalize_dataset(raw)
        dataset_id = str(normalized.get("dataset_id", "") or "").strip() or path.stem
        total = ds.estimate_total_ticks(normalized)
        ticks = ds.expand_dataset(normalized)
        if preview_limit is not None and preview_limit > 0:
            ticks = list(islice(ticks, int(preview_limit)))
        return dataset_id, digest, normalized, ticks, total

    if suffix == ".jsonl":
        # JSONL can be either "expanded ticks" output of the expander,
        # or a user-provided per-tick stream with at least input_text/input_is_empty.
        total = _count_jsonl_lines(path)
        ticks = iter_jsonl(path)
        if preview_limit is not None and preview_limit > 0:
            ticks = list(islice(ticks, int(preview_limit)))
        # Derive dataset_id from first item (if any), else filename stem.
        derived_id = path.stem
        try:
            first = None
            if isinstance(ticks, list):
                first = ticks[0] if ticks else None
            else:
                # preview_limit is None; do not consume generator here
                first = None
            if isinstance(first, dict) and str(first.get("dataset_id", "") or "").strip():
                derived_id = str(first.get("dataset_id") or "").strip()
        except Exception:
            derived_id = path.stem
        return derived_id, digest, None, ticks, total

    raise ExperimentRunnerError(f"Unsupported dataset file type: {path.suffix} (expected .yaml/.yml/.jsonl)")


def run_dataset(
    *,
    app,
    app_lock: Any | None = None,
    dataset_ref: DatasetFileRef,
    options: RunOptions,
    run_id: str | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    cancel_cb: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Run a dataset against the provided ObservatoryApp.

    This function is designed to be called in a background thread from the web server.
    It is intentionally synchronous and writes results to disk incrementally.
    """

    cancel_cb = cancel_cb or (lambda: False)
    progress_cb = progress_cb or _build_default_progress_cb()
    lock_ctx = (
        ProgressLockContext(
            app_lock,
            progress_cb=progress_cb,
            stage="waiting_for_app_lock",
            label="等待主循环/维护任务释放运行锁",
            poll_sec=0.005,
            cancel_cb=cancel_cb,
        )
        if app_lock is not None
        else contextlib.nullcontext()
    )

    progress_cb({"status": "running", "stage": "loading_dataset", "stage_label": "正在读取数据集"})
    dataset_id, dataset_sha, normalized_doc, ticks_iter, total_ticks = load_dataset_ticks(dataset_ref=dataset_ref)
    if run_id is None:
        run_id = make_run_id(dataset_id=dataset_id)
    progress_cb(
        {
            "run_id": run_id,
            "status": "running",
            "stage": "preparing_manifest",
            "stage_label": "正在准备运行清单与指标文件",
        }
    )
    effective_tick_planned: int | None = int(total_ticks) if total_ticks is not None else None
    if options.max_ticks is not None and int(options.max_ticks) > 0:
        max_ticks_opt = int(options.max_ticks)
        if effective_tick_planned is None:
            effective_tick_planned = max_ticks_opt
        else:
            effective_tick_planned = min(effective_tick_planned, max_ticks_opt)

    run_dir = make_run_dir(run_id)
    started_wall_ms = _now_ms()
    manifest_path = run_dir / "manifest.json"
    metrics_path = run_dir / "metrics.jsonl"
    runner_timing_path = run_dir / "runner_timing.jsonl"
    expectation_events_path = run_dir / "expectation_contract_events.jsonl"
    normalized_path = run_dir / "dataset.normalized.yaml"
    dataset_copy_path = run_dir / f"dataset.source{Path(resolve_dataset_file(dataset_ref)).suffix.lower()}"

    # Copy source dataset for audit (small, safe: outputs/ is gitignored).
    try:
        dataset_copy_path.write_text(_read_text(resolve_dataset_file(dataset_ref)), encoding="utf-8")
    except Exception:
        # Non-fatal.
        pass

    if normalized_doc is not None:
        try:
            from .io import dump_yaml

            normalized_path.write_text(dump_yaml(normalized_doc), encoding="utf-8")
        except Exception:
            pass

    # Prepare initial manifest
    tick_summary = ds.summarize_tick_counts(normalized_doc) if isinstance(normalized_doc, dict) else {}
    planned_tick_summary = dict(tick_summary) if tick_summary else {}
    if isinstance(normalized_doc, dict) and options.max_ticks is not None and int(options.max_ticks) > 0:
        try:
            planned_items = []
            limit = max(0, int(options.max_ticks))
            for idx, item in enumerate(ds.expand_dataset(normalized_doc)):
                if idx >= limit:
                    break
                planned_items.append(item)
            planned_tick_summary = ds.summarize_expanded_tick_items(planned_items)
        except Exception:
            planned_tick_summary = dict(tick_summary) if tick_summary else {}
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "status": "running",
        "dataset": {
            "dataset_id": dataset_id,
            "dataset_sha256": dataset_sha,
            "dataset_ref": dataset_ref.to_dict(),
            "dataset_path": str(resolve_dataset_file(dataset_ref)),
            "total_ticks": int(total_ticks) if total_ticks is not None else None,
            "effective_text_ticks": planned_tick_summary.get("effective_text_ticks") if planned_tick_summary else None,
            "empty_ticks": planned_tick_summary.get("empty_ticks") if planned_tick_summary else None,
            "labeled_ticks": planned_tick_summary.get("labeled_ticks") if planned_tick_summary else None,
        },
        "options": options.to_dict(),
        "runtime": {
            "python": sys.version,
            "platform": sys.platform,
            "pid": os.getpid(),
        },
        "started_at_ms": int(started_wall_ms),
        "finished_at_ms": 0,
        "tick_done": 0,
        "source_tick_done": 0,
        "synthetic_tick_done": 0,
        "executed_tick_done_total": 0,
        "tick_planned": effective_tick_planned,
        "errors": [],
        "expectation_contracts": {
            "registered_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "synthetic_tick_count": 0,
            "pending_count": 0,
            "events_path": str(expectation_events_path),
        },
        "runner_timing_path": str(runner_timing_path),
    }
    _sync_expectation_contract_manifest_aliases(manifest)

    if cancel_cb():
        _cancel_run_manifest(
            manifest,
            manifest_path,
            progress_cb,
            run_id=run_id,
            effective_tick_planned=effective_tick_planned,
            stage_label="已在启动阶段收到停止请求，运行已取消",
        )
        return {"success": True, "run_id": run_id, "run_dir": str(run_dir), "manifest": manifest}

    # Adaptive tuner (optional)
    tuner: AutoTuner | None = None
    if bool(options.auto_tune_enabled):
        tuner = AutoTuner(
            app=app,
            run_dir=run_dir,
            enabled=True,
            enable_short_term=bool(options.auto_tune_short_term),
            enable_long_term=bool(options.auto_tune_long_term),
        )
        try:
            with lock_ctx:
                applied = tuner.prepare_and_apply_overrides(trace_id="exp_prepare")
            manifest["auto_tuner"] = {"enabled": True, "prepare": applied}
        except Exception as exc:
            manifest["auto_tuner"] = {"enabled": True, "prepare_error": str(exc)}
    else:
        manifest["auto_tuner"] = {"enabled": False}

    effective_time_sensor_basis, effective_tick_interval_sec = _resolve_time_sensor_runtime_overrides(
        normalized_doc=normalized_doc,
        options=options,
    )
    dataset_app_config_override = _resolve_dataset_app_config_override(normalized_doc=normalized_doc)
    manifest["time_sensor_runtime_override"] = {
        "time_basis": effective_time_sensor_basis,
        "tick_interval_sec": effective_tick_interval_sec,
    }
    manifest["dataset_runtime_override"] = {
        "app_config_override": dataset_app_config_override,
        "app_config_override_keys": sorted(dataset_app_config_override.keys()),
        "experiment_default_overrides": copy.deepcopy(EXPERIMENT_DEFAULT_APP_OVERRIDES),
        "experiment_default_overrides_applied": _experiment_default_overrides_applied(dataset_app_config_override),
        "applied": False,
    }
    manifest["runtime_clock_override"] = {
        "mode": "dataset_tick" if str(effective_time_sensor_basis or "").strip().lower() == "tick" else "wallclock",
        "base_now_ms": int(started_wall_ms),
        "tick_interval_sec": effective_tick_interval_sec,
    }

    _persist_manifest(manifest_path, manifest)
    progress_cb(
        {
            "run_id": run_id,
            "status": manifest.get("status", "running"),
            "stage": "prepared",
            "stage_label": "运行清单已创建，准备初始化运行态",
            "tick_done": 0,
            "source_tick_done": 0,
            "synthetic_tick_done": 0,
            "executed_tick_done_total": 0,
            "tick_planned": effective_tick_planned,
            "tick_source": "dataset",
            "tick_index": -1,
        }
    )

    if cancel_cb():
        _cancel_run_manifest(
            manifest,
            manifest_path,
            progress_cb,
            run_id=run_id,
            effective_tick_planned=effective_tick_planned,
            stage_label="已在初始化前收到停止请求，运行已取消",
        )
        return {"success": True, "run_id": run_id, "run_dir": str(run_dir), "manifest": manifest}

    # Apply pre-run options (save old values, restore on exit)
    old_config = {}
    old_time_sensor = {}
    old_module_configs: dict[str, dict[str, Any]] = {}
    old_config_captured = False
    old_time_sensor_captured = False
    try:
        with lock_ctx:
            progress_cb({"run_id": run_id, "status": "running", "stage": "capturing_baseline", "stage_label": "正在读取运行前基线"})
            try:
                old_config = dict(getattr(app, "_config", {}) or {})
                old_config_captured = True
            except Exception:
                old_config = {}
            try:
                old_time_sensor = dict(getattr(app, "time_sensor")._config or {})  # type: ignore[attr-defined]
                old_time_sensor_captured = True
            except Exception:
                old_time_sensor = {}
            for attr_name in ("sensor", "pool", "hdb", "attention", "cognitive_stitching", "action"):
                module_obj = getattr(app, attr_name, None)
                module_cfg = getattr(module_obj, "_config", None)
                if isinstance(module_cfg, dict):
                    old_module_configs[attr_name] = dict(module_cfg)
            manifest["runtime_baseline"] = {
                "hdb_before_reset": _safe_hdb_runtime_baseline_snapshot(
                    app,
                    trace_id=f"{run_id}_hdb_before_reset",
                )
            }

        # Ensure experiment runs follow the current string-mode theory path when the dataset
        # is intended for companion / dialogue style runs. Without this, HDB stimulus-level
        # string projections may never be seeded, causing `stimulus_new_structure_count` to
        # stay at 0 even though the frontend/user observes long string objects elsewhere.
        with lock_ctx:
            progress_cb({"run_id": run_id, "status": "running", "stage": "applying_overrides", "stage_label": "正在应用数据集运行覆盖"})
            try:
                manifest["dataset_runtime_override"].update(
                    apply_experiment_default_app_overrides(
                        app,
                        app_config_override=dataset_app_config_override,
                        source="experiment_runner",
                        refresh_runtime=True,
                    )
                )
            except Exception:
                pass

        # Reset modes (mutates app state)
        with lock_ctx:
            progress_cb({"run_id": run_id, "status": "running", "stage": "resetting_runtime", "stage_label": "正在按重置策略清理运行态"})
            effective_reset_mode = "clear_all" if bool(options.clean_run) else str(options.reset_mode or "keep")
            if effective_reset_mode == "clear_all":
                if hasattr(app, "_clear_runtime_modules"):
                    app._clear_runtime_modules(  # type: ignore[attr-defined]
                        clear_hdb=True,
                        trace_prefix="exp_clear_all",
                        reason="experiment_reset",
                        operator="researcher",
                    )
                else:
                    app.sensor.clear_echo_pool(trace_id="exp_clear_sensor")  # type: ignore[attr-defined]
                    if hasattr(getattr(app, "time_sensor", None), "clear_runtime_state"):
                        app.time_sensor.clear_runtime_state(trace_id="exp_clear_time_sensor", reason="experiment_reset")  # type: ignore[attr-defined]
                    if hasattr(getattr(app, "action", None), "clear_runtime_state"):
                        app.action.clear_runtime_state(trace_id="exp_clear_action", reason="experiment_reset")  # type: ignore[attr-defined]
                    if hasattr(getattr(app, "cognitive_stitching", None), "clear_runtime_state"):
                        app.cognitive_stitching.clear_runtime_state(trace_id="exp_clear_cs", reason="experiment_reset")  # type: ignore[attr-defined]
                    if hasattr(getattr(app, "attention", None), "clear_runtime_state"):
                        app.attention.clear_runtime_state(trace_id="exp_clear_attention", reason="experiment_reset")  # type: ignore[attr-defined]
                    app.pool.clear_state_pool(trace_id="exp_clear_pool", reason="experiment_reset", operator="researcher")  # type: ignore[attr-defined]
                    app.hdb.clear_hdb(trace_id="exp_clear_hdb", reason="experiment_reset", operator="researcher")  # type: ignore[attr-defined]
                    app._last_report = None  # type: ignore[attr-defined]
                    app._report_history = []  # type: ignore[attr-defined]
            elif effective_reset_mode == "clear_runtime":
                if hasattr(app, "_clear_runtime_modules"):
                    app._clear_runtime_modules(  # type: ignore[attr-defined]
                        clear_hdb=False,
                        trace_prefix="exp_clear_runtime",
                        reason="experiment_reset",
                        operator="researcher",
                    )
                else:
                    app.sensor.clear_echo_pool(trace_id="exp_clear_sensor")  # type: ignore[attr-defined]
                    if hasattr(getattr(app, "time_sensor", None), "clear_runtime_state"):
                        app.time_sensor.clear_runtime_state(trace_id="exp_clear_time_sensor", reason="experiment_reset")  # type: ignore[attr-defined]
                    if hasattr(getattr(app, "action", None), "clear_runtime_state"):
                        app.action.clear_runtime_state(trace_id="exp_clear_action", reason="experiment_reset")  # type: ignore[attr-defined]
                    if hasattr(getattr(app, "cognitive_stitching", None), "clear_runtime_state"):
                        app.cognitive_stitching.clear_runtime_state(trace_id="exp_clear_cs", reason="experiment_reset")  # type: ignore[attr-defined]
                    if hasattr(getattr(app, "attention", None), "clear_runtime_state"):
                        app.attention.clear_runtime_state(trace_id="exp_clear_attention", reason="experiment_reset")  # type: ignore[attr-defined]
                    if hasattr(getattr(app, "hdb", None), "clear_runtime_state"):
                        app.hdb.clear_runtime_state(trace_id="exp_clear_hdb_runtime", reason="experiment_reset")  # type: ignore[attr-defined]
                    app.pool.clear_state_pool(trace_id="exp_clear_pool", reason="experiment_reset", operator="researcher")  # type: ignore[attr-defined]
                    app._last_report = None  # type: ignore[attr-defined]
                    app._report_history = []  # type: ignore[attr-defined]
            elif effective_reset_mode == "keep":
                pass
            else:
                raise ExperimentRunnerError(f"Unknown reset_mode: {options.reset_mode}")
            manifest["effective_reset_mode"] = effective_reset_mode
            manifest["clean_run_requested"] = bool(options.clean_run)
            baseline = manifest.setdefault("runtime_baseline", {})
            if isinstance(baseline, dict):
                baseline["hdb_after_reset"] = _safe_hdb_runtime_baseline_snapshot(
                    app,
                    trace_id=f"{run_id}_hdb_after_reset",
                )

        # Disable per-tick exports by default for long runs (overrideable)
        # Note: we mutate app._config in-place for the duration of this run.
        with lock_ctx:
            progress_cb({"run_id": run_id, "status": "running", "stage": "configuring_exports", "stage_label": "正在配置实验导出开关"})
            try:
                app._config["export_json"] = bool(options.export_json)  # type: ignore[attr-defined]
                app._config["export_html"] = bool(options.export_html)  # type: ignore[attr-defined]
                app._config["auto_open_html_report"] = False  # type: ignore[attr-defined]
            except Exception:
                pass

        # time_sensor override (runtime-only)
        with lock_ctx:
            progress_cb({"run_id": run_id, "status": "running", "stage": "configuring_time_sensor", "stage_label": "正在配置时间感受器覆盖"})
            if effective_time_sensor_basis in {"tick", "wallclock"}:
                try:
                    app.time_sensor._config["time_basis"] = str(effective_time_sensor_basis)  # type: ignore[attr-defined]
                except Exception:
                    pass
            if effective_tick_interval_sec is not None:
                try:
                    app.time_sensor._config["tick_interval_sec"] = float(effective_tick_interval_sec)  # type: ignore[attr-defined]
                except Exception:
                    pass

        # Main loop
        source_tick_done = 0
        synthetic_tick_done = 0
        executed_tick_done_total = 0
        max_ticks = options.max_ticks
        if max_ticks is not None:
            max_ticks = max(1, int(max_ticks))

        expectation_engine = ExpectationContractEngine()
        synthetic_queue: deque[dict[str, Any]] = deque()
        source_iter = iter(ticks_iter)
        source_exhausted = False
        runner_timing_totals: dict[str, float] = {
            "tick_loop_wall_ms": 0.0,
            "run_cycle_wall_ms": 0.0,
            "run_cycle_lock_wait_ms": 0.0,
            "metrics_extract_ms": 0.0,
            "metrics_serialize_ms": 0.0,
            "metrics_write_ms": 0.0,
            "expectation_contract_ms": 0.0,
            "manifest_update_ms": 0.0,
            "manifest_persist_ms": 0.0,
            "auto_tuner_short_term_ms": 0.0,
            "progress_callback_ms": 0.0,
            "file_flush_ms": 0.0,
        }
        runner_timing_max: dict[str, float] = {key: 0.0 for key in runner_timing_totals}

        def _add_runner_timing(key: str, elapsed_ms: float) -> None:
            value = max(0.0, float(elapsed_ms or 0.0))
            runner_timing_totals[key] = float(runner_timing_totals.get(key, 0.0) or 0.0) + value
            runner_timing_max[key] = max(float(runner_timing_max.get(key, 0.0) or 0.0), value)

        with (
            metrics_path.open("w", encoding="utf-8") as mf,
            expectation_events_path.open("w", encoding="utf-8") as ef,
            runner_timing_path.open("w", encoding="utf-8") as rf,
        ):
            while True:
                if cancel_cb():
                    _cancel_run_manifest(
                        manifest,
                        manifest_path,
                        progress_cb,
                        run_id=run_id,
                        source_tick_done=source_tick_done,
                        synthetic_tick_done=synthetic_tick_done,
                        executed_tick_done_total=executed_tick_done_total,
                        effective_tick_planned=effective_tick_planned,
                    )
                    break

                tick: dict[str, Any] | None = None
                tick_is_synthetic = False

                if synthetic_queue:
                    tick = synthetic_queue.popleft()
                    tick_is_synthetic = True
                else:
                    if not source_exhausted:
                        if max_ticks is not None and source_tick_done >= max_ticks:
                            manifest["status"] = "stopped_max_ticks"
                            source_exhausted = True
                        else:
                            try:
                                tick = next(source_iter)
                            except StopIteration:
                                source_exhausted = True
                    if tick is None and source_exhausted:
                        settle_res = expectation_engine.settle_on_run_end()
                        for event in settle_res.get("events", []) or []:
                            ef.write(_json_dumps_text(event))
                            ef.write("\n")
                        for synthetic_tick in settle_res.get("synthetic_ticks", []) or []:
                            if isinstance(synthetic_tick, dict):
                                synthetic_queue.append(synthetic_tick)
                        if synthetic_queue:
                            try:
                                ef.flush()
                            except Exception:
                                pass
                            continue
                        break

                if not isinstance(tick, dict):
                    continue

                text = str(tick.get("input_text", "") or "")
                is_empty = bool(tick.get("input_is_empty", False)) or (text == "")
                labels = tick.get("labels") if isinstance(tick.get("labels"), dict) else None
                runtime_now_ms = _resolve_runtime_clock_override(
                    started_wall_ms=int(started_wall_ms),
                    executed_tick_done_total=int(executed_tick_done_total),
                    effective_time_sensor_basis=effective_time_sensor_basis,
                    effective_tick_interval_sec=effective_tick_interval_sec,
                )
                progress_cb(
                    {
                        "run_id": run_id,
                        "status": "running",
                        "stage": "running_tick",
                        "stage_label": "正在执行数据集 tick",
                        "tick_done": source_tick_done,
                        "source_tick_done": source_tick_done,
                        "synthetic_tick_done": synthetic_tick_done,
                        "executed_tick_done_total": executed_tick_done_total,
                        "tick_planned": effective_tick_planned,
                        "tick_source": "synthetic" if tick_is_synthetic else "dataset",
                    }
                )
                tick_outer_t0 = time.perf_counter()
                runner_cycle_t0 = time.perf_counter()
                lock_wait_t0 = time.perf_counter()
                with lock_ctx:
                    run_cycle_lock_wait_ms = int((time.perf_counter() - lock_wait_t0) * 1000)
                    _add_runner_timing("run_cycle_lock_wait_ms", run_cycle_lock_wait_ms)
                    run_cycle_call_t0 = time.perf_counter()
                    run_cycle_kwargs = {
                        "text": None if is_empty else text,
                        "labels": labels,
                    }
                    if runtime_now_ms is not None:
                        try:
                            report = app.run_cycle(  # type: ignore[attr-defined]
                                now_ms_override=runtime_now_ms,
                                **run_cycle_kwargs,
                            )
                        except TypeError as exc:
                            if "now_ms_override" not in str(exc):
                                raise
                            report = app.run_cycle(**run_cycle_kwargs)  # type: ignore[attr-defined]
                    else:
                        report = app.run_cycle(**run_cycle_kwargs)  # type: ignore[attr-defined]
                    run_cycle_call_ms = int((time.perf_counter() - run_cycle_call_t0) * 1000)
                    _add_runner_timing("run_cycle_wall_ms", run_cycle_call_ms)
                runner_cycle_wall_ms = int((time.perf_counter() - runner_cycle_t0) * 1000)
                metrics_extract_t0 = time.perf_counter()
                metrics = extract_tick_metrics(report=report, dataset_tick=tick)
                metrics_extract_ms = int((time.perf_counter() - metrics_extract_t0) * 1000)
                _add_runner_timing("metrics_extract_ms", metrics_extract_ms)
                try:
                    logic_ms = float(metrics.get("timing_total_logic_ms", 0.0) or 0.0)
                except Exception:
                    logic_ms = 0.0
                metrics["timing_runner_cycle_wall_ms"] = float(runner_cycle_wall_ms)
                metrics["timing_runner_cycle_overhead_ms"] = round(max(0.0, float(runner_cycle_wall_ms) - logic_ms), 8)
                metrics["timing_runner_metrics_extract_ms"] = float(metrics_extract_ms)
                metrics["timing_runner_run_cycle_call_ms"] = float(run_cycle_call_ms)
                metrics["timing_runner_lock_wait_ms"] = float(run_cycle_lock_wait_ms)
                executed_tick_done_total += 1

                expectation_t0 = time.perf_counter()
                if tick_is_synthetic:
                    synthetic_tick_done += 1
                else:
                    source_tick_done += 1
                    try:
                        contract_res = expectation_engine.on_source_tick(
                            tick=tick,
                            report=report,
                            metrics=metrics,
                            source_tick_cursor=source_tick_done,
                        )
                    except ExpectationContractError as exc:
                        raise ExperimentRunnerError(f"Expectation contract error: {exc}") from exc
                    for event in contract_res.get("events", []) or []:
                        ef.write(_json_dumps_text(event))
                        ef.write("\n")
                    for synthetic_tick in contract_res.get("synthetic_ticks", []) or []:
                        if isinstance(synthetic_tick, dict):
                            synthetic_queue.append(synthetic_tick)
                expectation_ms = int((time.perf_counter() - expectation_t0) * 1000)
                _add_runner_timing("expectation_contract_ms", expectation_ms)

                manifest_update_t0 = time.perf_counter()
                manifest["tick_done"] = int(source_tick_done)
                manifest["source_tick_done"] = int(source_tick_done)
                manifest["synthetic_tick_done"] = int(synthetic_tick_done)
                manifest["executed_tick_done_total"] = int(executed_tick_done_total)
                manifest["expectation_contracts"] = {
                    **dict(manifest.get("expectation_contracts", {}) or {}),
                    **expectation_engine.snapshot(),
                    "events_path": str(expectation_events_path),
                }
                _sync_expectation_contract_manifest_aliases(manifest)
                manifest_update_ms = int((time.perf_counter() - manifest_update_t0) * 1000)
                _add_runner_timing("manifest_update_ms", manifest_update_ms)
                manifest_persist_t0 = time.perf_counter()
                _persist_manifest(manifest_path, manifest)
                manifest_persist_ms = int((time.perf_counter() - manifest_persist_t0) * 1000)
                _add_runner_timing("manifest_persist_ms", manifest_persist_ms)

                # Short-term auto tuning (best-effort, should never crash the run)
                short_term_res: dict[str, Any] | None = None
                auto_tuner_t0 = time.perf_counter()
                if tuner is not None and not cancel_cb():
                    try:
                        # Keep tuning within the same app lock to avoid races with run_cycle/web reads.
                        with lock_ctx:
                            short_term_res = tuner.on_tick(metrics=metrics)
                    except Exception:
                        short_term_res = {"enabled": True, "applied": False, "reason": "short_term_error"}
                auto_tuner_short_term_ms = int((time.perf_counter() - auto_tuner_t0) * 1000)
                _add_runner_timing("auto_tuner_short_term_ms", auto_tuner_short_term_ms)

                progress_t0 = time.perf_counter()
                progress_cb(
                    {
                        "run_id": run_id,
                        "status": manifest.get("status", "running"),
                        "stage": "tick_finished",
                        "stage_label": "tick 已完成，最新结构 Top 已进入内存预览",
                        "tick_done": source_tick_done,
                        "source_tick_done": source_tick_done,
                        "synthetic_tick_done": synthetic_tick_done,
                        "executed_tick_done_total": executed_tick_done_total,
                        "tick_planned": effective_tick_planned,
                        "tick_index": int(metrics.get("tick_index", source_tick_done - 1) or (source_tick_done - 1)),
                        "tick_source": str(metrics.get("tick_source", "dataset") or "dataset"),
                        "latest_metrics_preview": _compact_latest_metrics_preview(metrics),
                        "auto_tuner_short_term": _compact_auto_tuner_tick_result(short_term_res),
                    }
                )
                progress_ms = int((time.perf_counter() - progress_t0) * 1000)
                _add_runner_timing("progress_callback_ms", progress_ms)

                metrics["timing_runner_expectation_contract_ms"] = float(expectation_ms)
                metrics["timing_runner_manifest_update_ms"] = float(manifest_update_ms)
                metrics["timing_runner_manifest_persist_ms"] = float(manifest_persist_ms)
                metrics["timing_runner_auto_tuner_short_term_ms"] = float(auto_tuner_short_term_ms)
                metrics["timing_runner_progress_callback_ms"] = float(progress_ms)
                metrics_serialize_t0 = time.perf_counter()
                metrics_line = _json_dumps_text(metrics)
                metrics_serialize_ms = int((time.perf_counter() - metrics_serialize_t0) * 1000)
                _add_runner_timing("metrics_serialize_ms", metrics_serialize_ms)
                metrics_write_t0 = time.perf_counter()
                mf.write(metrics_line)
                mf.write("\n")
                metrics_write_ms = int((time.perf_counter() - metrics_write_t0) * 1000)
                _add_runner_timing("metrics_write_ms", metrics_write_ms)
                flush_t0 = time.perf_counter()
                try:
                    mf.flush()
                    ef.flush()
                except Exception:
                    pass
                flush_ms = int((time.perf_counter() - flush_t0) * 1000)
                _add_runner_timing("file_flush_ms", flush_ms)
                tick_outer_ms = int((time.perf_counter() - tick_outer_t0) * 1000)
                _add_runner_timing("tick_loop_wall_ms", tick_outer_ms)
                runner_tick_timing = {
                    "tick_index": int(metrics.get("tick_index", executed_tick_done_total - 1) or (executed_tick_done_total - 1)),
                    "tick_source": str(metrics.get("tick_source", "dataset") or "dataset"),
                    "input_is_empty": bool(metrics.get("input_is_empty", False)),
                    "timing_runner_tick_loop_wall_ms": float(tick_outer_ms),
                    "timing_runner_cycle_wall_ms": float(runner_cycle_wall_ms),
                    "timing_runner_run_cycle_call_ms": float(run_cycle_call_ms),
                    "timing_runner_lock_wait_ms": float(run_cycle_lock_wait_ms),
                    "timing_runner_metrics_extract_ms": float(metrics_extract_ms),
                    "timing_runner_metrics_serialize_ms": float(metrics_serialize_ms),
                    "timing_runner_metrics_write_ms": float(metrics_write_ms),
                    "timing_runner_expectation_contract_ms": float(expectation_ms),
                    "timing_runner_manifest_update_ms": float(manifest_update_ms),
                    "timing_runner_manifest_persist_ms": float(manifest_persist_ms),
                    "timing_runner_auto_tuner_short_term_ms": float(auto_tuner_short_term_ms),
                    "timing_runner_progress_callback_ms": float(progress_ms),
                    "timing_runner_file_flush_ms": float(flush_ms),
                    "timing_total_logic_ms": float(logic_ms),
                }
                rf.write(_json_dumps_text(runner_tick_timing))
                rf.write("\n")

        manifest["tick_done"] = int(source_tick_done)
        manifest["source_tick_done"] = int(source_tick_done)
        manifest["synthetic_tick_done"] = int(synthetic_tick_done)
        manifest["executed_tick_done_total"] = int(executed_tick_done_total)
        manifest["expectation_contracts"] = {
            **dict(manifest.get("expectation_contracts", {}) or {}),
            **expectation_engine.snapshot(),
            "events_path": str(expectation_events_path),
        }
        _sync_expectation_contract_manifest_aliases(manifest)
        if manifest.get("status") == "running":
            manifest["status"] = "completed"
        manifest["tick_loop_finished_at_ms"] = _now_ms()
        manifest["runner_timing"] = {
            "totals_ms": {key: round(float(value), 3) for key, value in runner_timing_totals.items()},
            "max_ms": {key: round(float(value), 3) for key, value in runner_timing_max.items()},
            "executed_tick_count": int(executed_tick_done_total),
            "avg_ms": {
                key: round(float(value) / max(1.0, float(executed_tick_done_total or 0)), 3)
                for key, value in runner_timing_totals.items()
            },
        }

        completion_timing: dict[str, Any] = {}
        completion_started = time.perf_counter()

        # Long-term tuning at completion
        allow_completion_work = str(manifest.get("status", "") or "") in {"completed", "stopped_max_ticks"} and not cancel_cb()
        if tuner is not None and allow_completion_work:
            try:
                stage_t0 = time.perf_counter()
                # Re-read metrics.jsonl (bounded by run length; acceptable for paper runs).
                from .io import iter_jsonl

                all_rows = list(iter_jsonl(metrics_path))
                with lock_ctx:
                    long_res = tuner.on_run_complete(all_metrics=all_rows, trace_id="exp_complete")
                manifest.setdefault("auto_tuner", {})
                manifest["auto_tuner"]["long_term"] = long_res
                completion_timing["auto_tuner_long_term_ms"] = int((time.perf_counter() - stage_t0) * 1000)
            except Exception as exc:
                manifest.setdefault("auto_tuner", {})
                manifest["auto_tuner"]["long_term_error"] = str(exc)

        # Idle-time consolidation (best-effort): keep long-run storage/runtime from drifting too far.
        # Skip it on cancellation so the UI can leave "正在停止" promptly.
        idle_cons: dict[str, Any] = {}
        if allow_completion_work and hasattr(app, "hdb") and hasattr(app.hdb, "idle_consolidate_hdb"):
            try:
                stage_t0 = time.perf_counter()
                progress_cb({"run_id": run_id, "status": manifest.get("status"), "stage": "idle_consolidation", "stage_label": "运行结束后正在做 HDB 闲时整理"})
                with lock_ctx:
                    idle_cons["hdb"] = app.hdb.idle_consolidate_hdb(
                        trace_id="exp_idle_consolidate",
                        reason="experiment_run_completed",
                        rebuild_pointer_index=True,
                        apply_soft_limits=True,
                    )
                completion_timing["idle_consolidation_hdb_ms"] = int((time.perf_counter() - stage_t0) * 1000)
            except Exception as exc:
                idle_cons["hdb_error"] = str(exc)

        if allow_completion_work and hasattr(app, "cognitive_stitching") and hasattr(app.cognitive_stitching, "idle_consolidate"):
            try:
                stage_t0 = time.perf_counter()
                progress_cb({"run_id": run_id, "status": manifest.get("status"), "stage": "idle_consolidation_cs", "stage_label": "运行结束后正在整理认知拼接缓存"})
                with lock_ctx:
                    idle_cons["cognitive_stitching"] = app.cognitive_stitching.idle_consolidate(
                        hdb=app.hdb,
                        trace_id="exp_idle_consolidate_cs",
                        tick_id="exp_idle_consolidate",
                        reason="experiment_run_completed",
                    )
                completion_timing["idle_consolidation_cognitive_stitching_ms"] = int((time.perf_counter() - stage_t0) * 1000)
            except Exception as exc:
                idle_cons["cognitive_stitching_error"] = str(exc)

        if idle_cons:
            manifest["idle_consolidation"] = idle_cons

        hdb_flush: dict[str, Any] = {}
        if hasattr(app, "hdb") and hasattr(app.hdb, "_structure_store"):
            try:
                stage_t0 = time.perf_counter()
                hdb_flush = dict(app.hdb._structure_store.flush_pending_persistence() or {})  # type: ignore[attr-defined]
                completion_timing["hdb_pending_persistence_flush_ms"] = int((time.perf_counter() - stage_t0) * 1000)
            except Exception as exc:
                hdb_flush = {"error": str(exc)}
        if hdb_flush:
            manifest["hdb_pending_persistence_flush"] = hdb_flush

        completion_timing["total_after_tick_loop_ms"] = int((time.perf_counter() - completion_started) * 1000)
        if completion_timing:
            manifest["completion_timing"] = completion_timing
        manifest["finished_at_ms"] = _now_ms()
        manifest["total_wall_ms"] = max(0, int(manifest.get("finished_at_ms", 0) or 0) - int(started_wall_ms))
        manifest["tick_loop_wall_ms"] = max(0, int(manifest.get("tick_loop_finished_at_ms", 0) or 0) - int(started_wall_ms))

        _persist_manifest(manifest_path, manifest)
        progress_cb(
            {
                "run_id": run_id,
                "status": manifest.get("status"),
                "stage": "finished",
                "stage_label": "运行结束",
                "tick_done": manifest.get("tick_done"),
                "source_tick_done": manifest.get("source_tick_done"),
                "synthetic_tick_done": manifest.get("synthetic_tick_done"),
                "executed_tick_done_total": manifest.get("executed_tick_done_total"),
                "tick_planned": effective_tick_planned,
            }
        )
        return {"success": True, "run_id": run_id, "run_dir": str(run_dir), "manifest": manifest}

    except ExperimentRunnerCancelled:
        source_done = locals().get("source_tick_done", manifest.get("source_tick_done", 0))
        synthetic_done = locals().get("synthetic_tick_done", manifest.get("synthetic_tick_done", 0))
        executed_done = locals().get("executed_tick_done_total", manifest.get("executed_tick_done_total", 0))
        planned = locals().get("effective_tick_planned", manifest.get("tick_planned", None))
        _cancel_run_manifest(
            manifest,
            locals().get("manifest_path", None),
            progress_cb,
            run_id=str(run_id or manifest.get("run_id", "")),
            source_tick_done=source_done,
            synthetic_tick_done=synthetic_done,
            executed_tick_done_total=executed_done,
            effective_tick_planned=planned,
            stage_label="已取消：停止请求发生在等待主循环锁阶段",
        )
        return {"success": True, "run_id": run_id, "run_dir": str(locals().get("run_dir", "")), "manifest": manifest}

    except (ExperimentIOError, ExperimentStorageError, ds.DatasetValidationError, ExperimentRunnerError) as exc:
        manifest["status"] = "failed"
        manifest["finished_at_ms"] = _now_ms()
        _append_manifest_error(
            manifest,
            exc,
            source_tick_done=locals().get("source_tick_done", manifest.get("source_tick_done", 0)),
            synthetic_tick_done=locals().get("synthetic_tick_done", manifest.get("synthetic_tick_done", 0)),
            executed_tick_done_total=locals().get("executed_tick_done_total", manifest.get("executed_tick_done_total", 0)),
        )
        _persist_manifest(manifest_path, manifest)
        progress_cb({"run_id": run_id, "status": "failed", "stage": "failed", "stage_label": "运行失败", "error": str(exc)})
        return {"success": False, "run_id": run_id, "run_dir": str(run_dir), "error": str(exc)}

    except Exception as exc:  # pragma: no cover (unexpected)
        manifest["status"] = "failed"
        manifest["finished_at_ms"] = _now_ms()
        _append_manifest_error(
            manifest,
            exc,
            source_tick_done=locals().get("source_tick_done", manifest.get("source_tick_done", 0)),
            synthetic_tick_done=locals().get("synthetic_tick_done", manifest.get("synthetic_tick_done", 0)),
            executed_tick_done_total=locals().get("executed_tick_done_total", manifest.get("executed_tick_done_total", 0)),
        )
        _persist_manifest(manifest_path, manifest)
        progress_cb({"run_id": run_id, "status": "failed", "stage": "failed", "stage_label": "运行失败", "error": str(exc)})
        return {"success": False, "run_id": run_id, "run_dir": str(run_dir), "error": str(exc)}

    finally:
        # Restore configs (best-effort)
        restore_lock_ctx = (
            ProgressLockContext(
                app_lock,
                progress_cb=None,
                stage="restoring_runtime_config",
                label="恢复实验运行前配置",
            )
            if app_lock is not None
            else contextlib.nullcontext()
        )
        with restore_lock_ctx:
            try:
                if old_config_captured:
                    app._config.clear()  # type: ignore[attr-defined]
                    app._config.update(old_config)  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                if old_time_sensor_captured:
                    app.time_sensor._config.clear()  # type: ignore[attr-defined]
                    app.time_sensor._config.update(old_time_sensor)  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                for attr_name, module_snapshot in old_module_configs.items():
                    module_obj = getattr(app, attr_name, None)
                    module_cfg = getattr(module_obj, "_config", None)
                    if isinstance(module_cfg, dict):
                        module_cfg.clear()
                        module_cfg.update(module_snapshot)
            except Exception:
                pass
            try:
                if hasattr(app, "_apply_runtime_overrides"):
                    app._apply_runtime_overrides()  # type: ignore[attr-defined]
            except Exception:
                pass


def export_expanded_ticks(
    *,
    dataset_ref: DatasetFileRef,
    out_path: str | Path,
) -> dict[str, Any]:
    """Expand a YAML dataset into JSONL expanded ticks.

    This is shared by web UI and CLI tools.
    """
    path = resolve_dataset_file(dataset_ref)
    if path.suffix.lower() not in {".yaml", ".yml"}:
        raise ExperimentRunnerError("Only YAML datasets can be expanded via this API.")
    raw = load_yaml_file(path)
    normalized = ds.validate_and_normalize_dataset(raw)
    items = list(ds.expand_dataset(normalized))
    out_p = Path(out_path)
    n = write_jsonl(out_p, items)
    return {
        "success": True,
        "dataset_id": str(normalized.get("dataset_id", "") or ""),
        "tick_count": int(n),
        "out_path": str(out_p),
    }
