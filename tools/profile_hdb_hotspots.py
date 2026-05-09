#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Focused hotspot profiler for the current AP prototype.

Targets:
1. HDB stimulus-level retrieval-storage
2. HDB induction propagation / memory-related routing

Design goals:
- Use isolated temporary HDB data dirs only.
- Use clean UTF-8 / ASCII-safe texts to avoid mojibake pollution.
- Surface direct call timing plus selected internal subcall totals.
- Keep output machine-readable for before/after comparison.
"""

from __future__ import annotations

import copy
import functools
import gc
import json
import shutil
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_JSON = REPORT_DIR / "hdb_hotspot_profile.json"

sys.path.insert(0, str(ROOT))

from observatory._app import ObservatoryApp  # noqa: E402


SEED_TEXTS = [
    "alpha greets beta",
    "beta answers alpha",
    "alpha recalls beta greeting",
    "reward follows correct alpha action",
    "penalty follows wrong beta action",
    "alpha expects reward after correct action",
    "beta remembers penalty after wrong action",
    "alpha beta action focus reward",
]

PROBE_STIMULUS_TEXT = "alpha expects beta reward action"
PROBE_CYCLE_TEXT = "alpha beta reward memory action"


def now_iso() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    if low == high:
        return ordered[low]
    frac = position - low
    return ordered[low] + (ordered[high] - ordered[low]) * frac


def summarize(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"runs": 0, "min_ms": 0.0, "mean_ms": 0.0, "median_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
    return {
        "runs": len(values),
        "min_ms": round(min(values), 4),
        "mean_ms": round(statistics.fmean(values), 4),
        "median_ms": round(statistics.median(values), 4),
        "p95_ms": round(percentile(values, 0.95), 4),
        "max_ms": round(max(values), 4),
    }


def ensure_logger_dir(obj: Any, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    if hasattr(obj, "_config"):
        obj._config["log_dir"] = str(target_dir)
    if hasattr(obj, "_logger") and hasattr(obj._logger, "update_config"):
        obj._logger.update_config(
            log_dir=str(target_dir),
            max_file_bytes=int(getattr(obj, "_config", {}).get("log_max_file_bytes", 5 * 1024 * 1024)),
        )


def close_if_present(obj: Any) -> None:
    if obj is None:
        return
    if hasattr(obj, "close") and callable(obj.close):
        obj.close()
        return
    if hasattr(obj, "_logger") and hasattr(obj._logger, "close"):
        obj._logger.close()


def clone_dir(src: Path, prefix: str) -> tuple[Path, Path]:
    root = Path(tempfile.mkdtemp(prefix=prefix))
    dst = root / "hdb_data"
    shutil.copytree(src, dst)
    return root, dst


def build_seed() -> dict[str, Any]:
    seed_root = Path(tempfile.mkdtemp(prefix="ap_hotspot_seed_"))
    seed_data_dir = seed_root / "hdb_data"
    app = ObservatoryApp(
        config_override={
            "export_html": False,
            "export_json": False,
            "auto_open_html_report": False,
            "web_auto_open_browser": False,
            "hdb_enable_background_repair": False,
            "state_pool_enable_placeholder_interfaces": False,
            "state_pool_enable_script_broadcast": False,
            "hdb_data_dir": str(seed_data_dir),
        }
    )
    ensure_logger_dir(app.sensor, seed_root / "logs" / "text_sensor")
    ensure_logger_dir(app.pool, seed_root / "logs" / "state_pool")
    ensure_logger_dir(app.hdb, seed_root / "logs" / "hdb")

    for text in SEED_TEXTS:
        app.run_cycle(text=text)

    probe_packet = app.sensor.ingest_text(
        text=PROBE_STIMULUS_TEXT,
        trace_id="probe_packet",
        tick_id="probe_packet",
    )["data"]["stimulus_packet"]
    induction_snapshot = app._build_induction_source_snapshot(
        trace_id="probe_induction_snapshot",
        tick_id="probe_induction_snapshot",
    )
    seed_summary = app.hdb.get_hdb_snapshot(trace_id="probe_hdb_snapshot", top_k=8)["data"]["summary"]
    close_if_present(app)
    return {
        "seed_root": seed_root,
        "seed_data_dir": seed_data_dir,
        "probe_packet": probe_packet,
        "induction_snapshot": induction_snapshot,
        "probe_cycle_text": PROBE_CYCLE_TEXT,
        "seed_summary": seed_summary,
        "seed_text_count": len(SEED_TEXTS),
    }


@dataclass
class CallStat:
    name: str
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0

    def add(self, elapsed_ms: float) -> None:
        self.count += 1
        self.total_ms += elapsed_ms
        self.max_ms = max(self.max_ms, elapsed_ms)


@dataclass
class CallStats:
    rows: dict[str, CallStat] = field(default_factory=dict)

    def record(self, name: str, elapsed_ms: float) -> None:
        row = self.rows.setdefault(name, CallStat(name=name))
        row.add(elapsed_ms)

    def as_sorted_rows(self) -> list[dict[str, Any]]:
        rows = []
        for row in self.rows.values():
            avg_ms = row.total_ms / row.count if row.count else 0.0
            rows.append(
                {
                    "name": row.name,
                    "count": row.count,
                    "total_ms": round(row.total_ms, 4),
                    "avg_ms": round(avg_ms, 4),
                    "max_ms": round(row.max_ms, 4),
                }
            )
        rows.sort(key=lambda item: (-float(item["total_ms"]), -int(item["count"]), str(item["name"])))
        return rows


class PatchManager:
    def __init__(self, stats: CallStats):
        self._stats = stats
        self._restore: list[tuple[Any, str, Any]] = []

    def patch_method(self, obj: Any, attr: str, label: str) -> None:
        if obj is None or not hasattr(obj, attr):
            return
        original = getattr(obj, attr)
        if not callable(original):
            return

        @functools.wraps(original)
        def wrapper(*args, **kwargs):
            started = time.perf_counter_ns()
            try:
                return original(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
                self._stats.record(label, elapsed_ms)

        self._restore.append((obj, attr, original))
        setattr(obj, attr, wrapper)

    def restore(self) -> None:
        for obj, attr, original in reversed(self._restore):
            setattr(obj, attr, original)
        self._restore.clear()


def build_app(data_dir: Path, root: Path) -> ObservatoryApp:
    app = ObservatoryApp(
        config_override={
            "export_html": False,
            "export_json": False,
            "auto_open_html_report": False,
            "web_auto_open_browser": False,
            "hdb_enable_background_repair": False,
            "state_pool_enable_placeholder_interfaces": False,
            "state_pool_enable_script_broadcast": False,
            "hdb_data_dir": str(data_dir),
        }
    )
    ensure_logger_dir(app.sensor, root / "logs" / "text_sensor")
    ensure_logger_dir(app.pool, root / "logs" / "state_pool")
    ensure_logger_dir(app.hdb, root / "logs" / "hdb")
    return app


def install_hdb_hotspot_patches(app: ObservatoryApp, stats: CallStats) -> PatchManager:
    pm = PatchManager(stats)
    stimulus = app.hdb._stimulus
    induction = app.hdb._induction
    cut = app.hdb._cut
    pointer = app.hdb._pointer_index
    structure_store = app.hdb._structure_store

    pm.patch_method(stimulus, "_resolve_anchor_chain_match", "stimulus._resolve_anchor_chain_match")
    pm.patch_method(stimulus, "_best_structure_match", "stimulus._best_structure_match")
    pm.patch_method(stimulus, "_build_structure_profile", "stimulus._build_structure_profile")
    pm.patch_method(stimulus, "_list_owner_local_residual_items", "stimulus._list_owner_local_residual_items")
    pm.patch_method(stimulus, "_build_round_debug", "stimulus._build_round_debug")

    pm.patch_method(induction, "_resolve_runtime_source_data", "induction._resolve_runtime_source_data")
    pm.patch_method(induction, "_aggregate_local_targets", "induction._aggregate_local_targets")
    pm.patch_method(
        induction,
        "_select_existing_structure_candidates_for_raw_residual",
        "induction._select_existing_structure_candidates_for_raw_residual",
    )
    pm.patch_method(
        induction,
        "_select_group_component_candidates_for_raw_residual",
        "induction._select_group_component_candidates_for_raw_residual",
    )
    pm.patch_method(induction, "_filter_full_inclusion_targets", "induction._filter_full_inclusion_targets")

    pm.patch_method(cut, "maximum_common_part", "cut.maximum_common_part")
    pm.patch_method(cut, "build_sequence_profile_from_groups", "cut.build_sequence_profile_from_groups")
    pm.patch_method(cut, "build_sequence_profile_from_structure", "cut.build_sequence_profile_from_structure")
    pm.patch_method(pointer, "resolve_db", "pointer.resolve_db")
    pm.patch_method(pointer, "query_candidates_by_signature", "pointer.query_candidates_by_signature")
    pm.patch_method(structure_store, "update_db", "structure_store.update_db")
    pm.patch_method(structure_store, "add_diff_entry", "structure_store.add_diff_entry")
    return pm


def force_gc() -> None:
    gc.collect()
    gc.collect()


def timed_call(fn: Callable[[], Any]) -> tuple[Any, float]:
    force_gc()
    started = time.perf_counter_ns()
    result = fn()
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    return result, elapsed_ms


def run_stimulus_scenario(seed: dict[str, Any], runs: int = 3) -> dict[str, Any]:
    timings: list[float] = []
    scenario_stats = CallStats()
    context: dict[str, Any] = {}

    for index in range(runs):
        root, data_dir = clone_dir(seed["seed_data_dir"], prefix="ap_hotspot_stimulus_")
        app = build_app(data_dir, root)
        patches = install_hdb_hotspot_patches(app, scenario_stats)
        try:
            packet = copy.deepcopy(seed["probe_packet"])
            result, elapsed_ms = timed_call(
                lambda: app.hdb.run_stimulus_level_retrieval_storage(
                    stimulus_packet=packet,
                    trace_id=f"hotspot_stimulus_{index:02d}",
                    tick_id=f"hotspot_stimulus_{index:02d}",
                    now_ms=int(time.time() * 1000),
                )
            )
            timings.append(elapsed_ms)
            if not context:
                data = dict(result.get("data", {}) or {})
                context = {
                    "matched_structure_count": len(data.get("matched_structure_ids", []) or []),
                    "new_structure_count": len(data.get("new_structure_ids", []) or []),
                    "remaining_stimulus_sa_count": int(data.get("remaining_stimulus_sa_count", 0) or 0),
                    "round_count": int(data.get("round_count", 0) or 0),
                }
        finally:
            patches.restore()
            close_if_present(app)
            shutil.rmtree(root, ignore_errors=True)

    return {
        "name": "hdb.stimulus_level_retrieval_storage",
        "elapsed_ms": summarize(timings),
        "context": context,
        "subcalls": scenario_stats.as_sorted_rows(),
    }


def run_induction_scenario(seed: dict[str, Any], runs: int = 3) -> dict[str, Any]:
    timings: list[float] = []
    scenario_stats = CallStats()
    context: dict[str, Any] = {}

    for index in range(runs):
        root, data_dir = clone_dir(seed["seed_data_dir"], prefix="ap_hotspot_induction_")
        app = build_app(data_dir, root)
        patches = install_hdb_hotspot_patches(app, scenario_stats)
        try:
            snapshot = copy.deepcopy(seed["induction_snapshot"])
            result, elapsed_ms = timed_call(
                lambda: app.hdb.run_induction_propagation(
                    state_snapshot=snapshot,
                    trace_id=f"hotspot_induction_{index:02d}",
                    tick_id=f"hotspot_induction_{index:02d}",
                    max_source_items=int((snapshot.get("summary", {}) or {}).get("induction_source_selected_count", 0) or 0),
                    enable_ev_propagation=True,
                    enable_er_induction=True,
                )
            )
            timings.append(elapsed_ms)
            if not context:
                data = dict(result.get("data", {}) or {})
                context = {
                    "source_item_count": int(data.get("source_item_count", 0) or 0),
                    "propagated_target_count": int(data.get("propagated_target_count", 0) or 0),
                    "induced_target_count": int(data.get("induced_target_count", 0) or 0),
                    "total_delta_ev": round(float(data.get("total_delta_ev", 0.0) or 0.0), 4),
                }
        finally:
            patches.restore()
            close_if_present(app)
            shutil.rmtree(root, ignore_errors=True)

    return {
        "name": "hdb.induction_propagation",
        "elapsed_ms": summarize(timings),
        "context": context,
        "subcalls": scenario_stats.as_sorted_rows(),
    }


def run_cycle_scenario(seed: dict[str, Any], runs: int = 2) -> dict[str, Any]:
    timings: list[float] = []
    scenario_stats = CallStats()
    step_rows: list[dict[str, Any]] = []

    for index in range(runs):
        root, data_dir = clone_dir(seed["seed_data_dir"], prefix="ap_hotspot_cycle_")
        app = build_app(data_dir, root)
        patches = install_hdb_hotspot_patches(app, scenario_stats)
        try:
            result, elapsed_ms = timed_call(
                lambda: app.run_cycle(
                    text=seed["probe_cycle_text"],
                )
            )
            timings.append(elapsed_ms)
            data = dict(result.get("data", {}) or {})
            report = dict(data.get("report", {}) or {})
            timing_steps_ms = dict(report.get("timing_steps_ms", {}) or {})
            if timing_steps_ms:
                step_rows.append(timing_steps_ms)
        finally:
            patches.restore()
            close_if_present(app)
            shutil.rmtree(root, ignore_errors=True)

    averaged_steps: dict[str, float] = {}
    if step_rows:
        keys = set()
        for row in step_rows:
            keys.update(row.keys())
        for key in sorted(keys):
            values = [float(row.get(key, 0.0) or 0.0) for row in step_rows]
            averaged_steps[key] = round(statistics.fmean(values), 4)

    return {
        "name": "observatory.run_cycle",
        "elapsed_ms": summarize(timings),
        "context": {
            "avg_timing_steps_ms": averaged_steps,
        },
        "subcalls": scenario_stats.as_sorted_rows(),
    }


def main() -> None:
    seed = build_seed()
    try:
        report = {
            "generated_at": now_iso(),
            "cwd": str(ROOT),
            "seed_summary": {
                "seed_text_count": int(seed.get("seed_text_count", 0) or 0),
                "probe_stimulus_text": PROBE_STIMULUS_TEXT,
                "probe_cycle_text": PROBE_CYCLE_TEXT,
                "hdb_summary": seed.get("seed_summary", {}),
            },
            "scenarios": [
                run_stimulus_scenario(seed),
                run_induction_scenario(seed),
                run_cycle_scenario(seed),
            ],
        }
        OUTPUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ok": True, "output": str(OUTPUT_JSON)}, ensure_ascii=False))
    finally:
        seed_root = seed.get("seed_root")
        if seed_root:
            shutil.rmtree(seed_root, ignore_errors=True)


if __name__ == "__main__":
    main()
