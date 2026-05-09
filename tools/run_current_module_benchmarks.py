#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AP prototype performance benchmarks (current implemented modules).

Benchmarked paths:
- text_sensor: ingest_text (simple/advanced + echo steady-state)
- state_pool: apply_stimulus_packet / tick_maintain_state_pool / get_state_snapshot
- hdb: run_structure_level_retrieval_storage / run_stimulus_level_retrieval_storage /
       run_induction_propagation / apply_memory_activation_targets / tick_memory_activation_pool
- observatory: run_cycle / get_dashboard_data

Design goals:
- Keep writes isolated: run on temporary HDB data dirs, never touch project HDB data.
- Exclude setup/teardown from timing.
- Provide distribution metrics (min/mean/median/p95/max) and tracemalloc peak.
"""

from __future__ import annotations

import copy
import gc
import json
import os
import platform
import shutil
import statistics
import sys
import tempfile
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_JSON = REPORT_DIR / "current_module_performance_benchmark.json"

sys.path.insert(0, str(ROOT))

from hdb import HDB  # noqa: E402
from observatory._app import ObservatoryApp  # noqa: E402
from state_pool.main import StatePool  # noqa: E402
from text_sensor import TextSensor  # noqa: E402


SHORT_TEXT = "你好呀！"
MEDIUM_TEXT = "请记录当前状态，并在下一轮比较输入残差与历史结构的匹配结果。"
SEED_TEXTS = [
    "你好呀！",
    "你也好呀。",
    "今天状态稳定。",
    "请记录当前输入并观察残差变化。",
    "现在开始进行结构级查存测试。",
    "如果再次看到相似输入，请优先打开局部数据库。",
    "请比较预测与现实之间的偏差。",
    "在下一轮里继续观察近因增益与疲劳变化。",
]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _percentile(samples: list[float], q: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    if low == high:
        return ordered[low]
    frac = position - low
    return ordered[low] + (ordered[high] - ordered[low]) * frac


def _summarize(samples: list[float]) -> dict[str, float | int]:
    return {
        "iterations": len(samples),
        "min_ms": min(samples),
        "mean_ms": statistics.fmean(samples),
        "median_ms": statistics.median(samples),
        "p95_ms": _percentile(samples, 0.95),
        "max_ms": max(samples),
    }


def _disable_gc_while(fn: Callable[[], Any]) -> Any:
    enabled = gc.isenabled()
    if enabled:
        gc.disable()
    try:
        return fn()
    finally:
        if enabled:
            gc.enable()


def _ensure_logger_dir(obj: Any, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    if hasattr(obj, "_config"):
        obj._config["log_dir"] = str(target_dir)
    if hasattr(obj, "_logger") and hasattr(obj._logger, "update_config"):
        obj._logger.update_config(
            log_dir=str(target_dir),
            max_file_bytes=int(getattr(obj, "_config", {}).get("log_max_file_bytes", 5 * 1024 * 1024)),
        )


def _close_if_present(obj: Any) -> None:
    if obj is None:
        return
    if hasattr(obj, "close") and callable(obj.close):
        obj.close()
        return
    if hasattr(obj, "_logger") and hasattr(obj._logger, "close"):
        obj._logger.close()


def _clone_dir(src: Path, prefix: str) -> tuple[Path, Path]:
    root = Path(tempfile.mkdtemp(prefix=prefix))
    dst = root / "hdb_data"
    shutil.copytree(src, dst)
    return root, dst


def _build_seed() -> dict[str, Any]:
    seed_root = Path(tempfile.mkdtemp(prefix="ap_bench_seed_"))
    seed_data_dir = seed_root / "hdb_data"

    app = ObservatoryApp(
        config_override={
            "export_html": False,
            "export_json": False,
            "auto_open_html_report": False,
            "web_auto_open_browser": False,
            "state_pool_enable_placeholder_interfaces": False,
            "state_pool_enable_script_broadcast": False,
            "hdb_enable_background_repair": False,
            "hdb_data_dir": str(seed_data_dir),
        }
    )
    _ensure_logger_dir(app.sensor, seed_root / "logs" / "text_sensor")
    _ensure_logger_dir(app.pool, seed_root / "logs" / "state_pool")
    _ensure_logger_dir(app.hdb, seed_root / "logs" / "hdb")

    for text in SEED_TEXTS:
        app.run_cycle(text=text)

    packet = app.sensor.ingest_text(text=MEDIUM_TEXT, trace_id="bench_packet", tick_id="bench_packet")["data"][
        "stimulus_packet"
    ]
    snapshot = app.pool.get_state_snapshot(trace_id="bench_snapshot", tick_id="bench_snapshot", top_k=32)["data"][
        "snapshot"
    ]
    append = app.hdb.append_episodic_memory(
        episodic_payload={"event_summary": "bench_memory", "structure_refs": [], "group_refs": [], "meta": {}},
        trace_id="bench_append_memory",
        tick_id="bench_append_memory",
    )
    memory_id = append["data"]["episodic_id"]
    hdb_summary = app.hdb.get_hdb_snapshot(trace_id="bench_hdb", top_k=8)["data"]["summary"]

    app.close()
    return {
        "seed_root": seed_root,
        "seed_data_dir": seed_data_dir,
        "packet": packet,
        "snapshot": snapshot,
        "memory_id": memory_id,
        "hdb_summary": hdb_summary,
    }


@dataclass
class Scenario:
    name: str
    group: str
    description: str
    warmup: int
    runs: int
    setup: Callable[[dict[str, Any]], dict[str, Any]]
    run: Callable[[dict[str, Any]], Any]
    teardown: Callable[[dict[str, Any]], None]
    context: Callable[[dict[str, Any], Any], dict[str, Any]]


def run_scenario(spec: Scenario, seed: dict[str, Any]) -> dict[str, Any]:
    timings: list[float] = []
    ctx_payload: dict[str, Any] = {}

    for idx in range(spec.warmup + spec.runs):
        ctx = spec.setup(seed)
        try:
            if idx < spec.warmup:
                spec.run(ctx)
                continue

            gc.collect()

            def _timed():
                started = time.perf_counter_ns()
                result = spec.run(ctx)
                ended = time.perf_counter_ns()
                return result, (ended - started) / 1_000_000.0

            result, elapsed_ms = _disable_gc_while(_timed)
            timings.append(elapsed_ms)
            if not ctx_payload:
                ctx_payload = spec.context(ctx, result)
        finally:
            spec.teardown(ctx)

    mem_ctx = spec.setup(seed)
    try:
        gc.collect()
        tracemalloc.start()
        mem_result = spec.run(mem_ctx)
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        if not ctx_payload:
            ctx_payload = spec.context(mem_ctx, mem_result)
    finally:
        spec.teardown(mem_ctx)

    return {
        "name": spec.name,
        "group": spec.group,
        "description": spec.description,
        "timing": _summarize(timings),
        "peak_tracemalloc_mb": round(peak_bytes / (1024 * 1024), 4),
        "context": ctx_payload,
    }


def make_scenarios() -> list[Scenario]:
    def ts_simple_setup(_: dict[str, Any]) -> dict[str, Any]:
        root = Path(tempfile.mkdtemp(prefix="ap_bench_ts_simple_"))
        sensor = TextSensor(
            config_override={
                "default_mode": "simple",
                "enable_echo": False,
                "enable_char_output": True,
                "enable_token_output": False,
                "log_dir": str(root / "logs"),
            }
        )
        return {"root": root, "sensor": sensor}

    def ts_simple_run(ctx: dict[str, Any]) -> dict[str, Any]:
        return ctx["sensor"].ingest_text(text=SHORT_TEXT, trace_id="bench_ts_simple", tick_id="bench_ts_simple")

    def ts_simple_teardown(ctx: dict[str, Any]) -> None:
        _close_if_present(ctx.get("sensor"))
        shutil.rmtree(ctx["root"], ignore_errors=True)

    def ts_simple_context(_: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        data = result["data"]
        return {
            "mode": data["tokenization_summary"]["mode"],
            "feature_sa_count": data["stats"]["feature_sa_count"],
            "attribute_sa_count": data["stats"]["attribute_sa_count"],
            "csa_count": data["stats"]["csa_count"],
            "group_count": len(data["stimulus_packet"]["grouped_sa_sequences"]),
        }

    def ts_adv_setup(_: dict[str, Any]) -> dict[str, Any]:
        root = Path(tempfile.mkdtemp(prefix="ap_bench_ts_adv_"))
        sensor = TextSensor(
            config_override={
                "default_mode": "advanced",
                "tokenizer_backend": "jieba",
                "enable_echo": False,
                "enable_char_output": False,
                "enable_token_output": True,
                "log_dir": str(root / "logs"),
            }
        )
        return {"root": root, "sensor": sensor}

    def ts_adv_run(ctx: dict[str, Any]) -> dict[str, Any]:
        return ctx["sensor"].ingest_text(text=MEDIUM_TEXT, trace_id="bench_ts_adv", tick_id="bench_ts_adv")

    def ts_adv_context(_: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        data = result["data"]
        return {
            "mode": data["tokenization_summary"]["mode"],
            "token_units": data["tokenization_summary"]["token_units"],
            "tokenizer_fallback": data["tokenization_summary"]["tokenizer_fallback"],
            "feature_sa_count": data["stats"]["feature_sa_count"],
        }

    def ts_echo_setup(_: dict[str, Any]) -> dict[str, Any]:
        root = Path(tempfile.mkdtemp(prefix="ap_bench_ts_echo_"))
        sensor = TextSensor(
            config_override={
                "default_mode": "simple",
                "enable_echo": True,
                "enable_char_output": True,
                "enable_token_output": False,
                "log_dir": str(root / "logs"),
            }
        )
        for idx, text in enumerate(["你好", "你好呀", "你也好", "现在观察", "继续"]):
            trace = f"bench_ts_echo_seed_{idx}"
            sensor.ingest_text(text=text, trace_id=trace, tick_id=trace)
        return {"root": root, "sensor": sensor}

    def ts_echo_run(ctx: dict[str, Any]) -> dict[str, Any]:
        return ctx["sensor"].ingest_text(text=SHORT_TEXT, trace_id="bench_ts_echo", tick_id="bench_ts_echo")

    def ts_echo_context(_: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        data = result["data"]
        packet = data["stimulus_packet"]
        return {
            "echo_frames_used": data["echo_frames_used"],
            "echo_frame_count": len(packet.get("echo_frames", [])),
            "group_count": len(packet["grouped_sa_sequences"]),
        }

    def sp_apply_setup(seed: dict[str, Any]) -> dict[str, Any]:
        root = Path(tempfile.mkdtemp(prefix="ap_bench_sp_apply_"))
        pool = StatePool(
            config_override={
                "enable_placeholder_interfaces": False,
                "enable_script_broadcast": False,
                "log_dir": str(root / "logs"),
            }
        )
        return {"root": root, "pool": pool, "packet": seed["packet"]}

    def sp_apply_run(ctx: dict[str, Any]) -> dict[str, Any]:
        return ctx["pool"].apply_stimulus_packet(
            stimulus_packet=ctx["packet"],
            trace_id="bench_sp_apply",
            tick_id="bench_sp_apply",
            source_module="text_sensor",
            enable_script_broadcast=False,
        )

    def sp_apply_teardown(ctx: dict[str, Any]) -> None:
        _close_if_present(ctx.get("pool"))
        shutil.rmtree(ctx["root"], ignore_errors=True)

    def sp_apply_context(_: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        data = result["data"]
        return {
            "new_item_count": data["new_item_count"],
            "updated_item_count": data["updated_item_count"],
            "merged_item_count": data["merged_item_count"],
            "priority_neutralized_item_count": data["priority_neutralized_item_count"],
        }

    def sp_tick_setup(seed: dict[str, Any]) -> dict[str, Any]:
        root = Path(tempfile.mkdtemp(prefix="ap_bench_sp_tick_"))
        pool = StatePool(
            config_override={
                "enable_placeholder_interfaces": False,
                "enable_script_broadcast": False,
                "log_dir": str(root / "logs"),
            }
        )
        pool.apply_stimulus_packet(seed["packet"], trace_id="bench_sp_tick_seed", tick_id="bench_sp_tick_seed", enable_script_broadcast=False)
        snapshot = pool.get_state_snapshot(trace_id="bench_sp_tick_snap", top_k=4)["data"]["snapshot"]
        if snapshot.get("top_items"):
            item_id = snapshot["top_items"][0]["item_id"]
            pool.apply_energy_update(
                target_item_id=item_id,
                delta_er=0.0,
                delta_ev=0.3,
                trace_id="bench_sp_tick_ev",
                tick_id="bench_sp_tick_ev",
                reason="bench_ev_seed",
                source_module="bench",
            )
        return {"root": root, "pool": pool}

    def sp_tick_run(ctx: dict[str, Any]) -> dict[str, Any]:
        return ctx["pool"].tick_maintain_state_pool(
            trace_id="bench_sp_tick",
            tick_id="bench_sp_tick",
            enable_script_broadcast=False,
        )

    def sp_tick_context(_: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        data = result["data"]
        return {
            "before_item_count": data["before_item_count"],
            "after_item_count": data["after_item_count"],
            "decayed_item_count": data["decayed_item_count"],
            "neutralized_item_count": data["neutralized_item_count"],
            "pruned_item_count": data["pruned_item_count"],
        }

    def sp_snapshot_setup(seed: dict[str, Any]) -> dict[str, Any]:
        root = Path(tempfile.mkdtemp(prefix="ap_bench_sp_snap_"))
        pool = StatePool(
            config_override={
                "enable_placeholder_interfaces": False,
                "enable_script_broadcast": False,
                "log_dir": str(root / "logs"),
            }
        )
        pool.apply_stimulus_packet(seed["packet"], trace_id="bench_sp_snap_seed", tick_id="bench_sp_snap_seed", enable_script_broadcast=False)
        return {"root": root, "pool": pool}

    def sp_snapshot_run(ctx: dict[str, Any]) -> dict[str, Any]:
        return ctx["pool"].get_state_snapshot(trace_id="bench_sp_snap", tick_id="bench_sp_snap", top_k=32)

    def sp_snapshot_context(_: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        snapshot = result["data"]["snapshot"]
        return {
            "active_item_count": snapshot["summary"].get("active_item_count", 0),
            "top_items_count": len(snapshot.get("top_items", [])),
        }

    def hdb_setup(seed: dict[str, Any]) -> dict[str, Any]:
        root, data_dir = _clone_dir(seed["seed_data_dir"], "ap_bench_hdb_clone_")
        hdb = HDB(config_override={"data_dir": str(data_dir), "enable_background_repair": False, "log_dir": str(root / "logs")})
        return {"root": root, "hdb": hdb, "packet": seed["packet"], "snapshot": seed["snapshot"], "memory_id": seed["memory_id"], "seed_summary": seed["hdb_summary"]}

    def hdb_teardown(ctx: dict[str, Any]) -> None:
        _close_if_present(ctx.get("hdb"))
        shutil.rmtree(ctx["root"], ignore_errors=True)

    def hdb_structure_run(ctx: dict[str, Any]) -> dict[str, Any]:
        return ctx["hdb"].run_structure_level_retrieval_storage(
            state_snapshot=copy.deepcopy(ctx["snapshot"]),
            trace_id="bench_hdb_structure",
            tick_id="bench_hdb_structure",
            top_n=16,
        )

    def hdb_structure_ctx(ctx: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        data = result["data"]
        return {
            "seed_summary": ctx["seed_summary"],
            "round_count": data["round_count"],
            "matched_group_count": len(data.get("matched_group_ids", [])),
            "new_group_count": len(data.get("new_group_ids", [])),
            "fallback_used": data.get("fallback_used", False),
        }

    def hdb_stimulus_run(ctx: dict[str, Any]) -> dict[str, Any]:
        return ctx["hdb"].run_stimulus_level_retrieval_storage(
            stimulus_packet=copy.deepcopy(ctx["packet"]),
            trace_id="bench_hdb_stimulus",
            tick_id="bench_hdb_stimulus",
        )

    def hdb_stimulus_ctx(ctx: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        data = result["data"]
        return {
            "seed_summary": ctx["seed_summary"],
            "round_count": data["round_count"],
            "matched_structure_count": len(data.get("matched_structure_ids", [])),
            "new_structure_count": len(data.get("new_structure_ids", [])),
            "fallback_used": data.get("fallback_used", False),
        }

    def hdb_induction_run(ctx: dict[str, Any]) -> dict[str, Any]:
        return ctx["hdb"].run_induction_propagation(
            state_snapshot=copy.deepcopy(ctx["snapshot"]),
            trace_id="bench_hdb_induction",
            tick_id="bench_hdb_induction",
            max_source_items=8,
        )

    def hdb_induction_ctx(ctx: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        data = result["data"]
        return {
            "seed_summary": ctx["seed_summary"],
            "source_item_count": data.get("source_item_count", 0),
            "propagated_target_count": data.get("propagated_target_count", 0),
            "induced_target_count": data.get("induced_target_count", 0),
        }

    def hdb_mem_apply_run(ctx: dict[str, Any]) -> dict[str, Any]:
        return ctx["hdb"].apply_memory_activation_targets(
            targets=[
                {
                    "projection_kind": "memory",
                    "memory_id": ctx["memory_id"],
                    "target_display_text": ctx["memory_id"],
                    "delta_er": 0.3,
                    "delta_ev": 0.2,
                    "sources": ["bench"],
                    "modes": ["bench_apply"],
                }
            ],
            trace_id="bench_hdb_mem_apply",
            tick_id="bench_hdb_mem_apply",
        )

    def hdb_mem_apply_ctx(ctx: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        data = result["data"]
        return {
            "memory_id": ctx["memory_id"],
            "applied_count": data.get("applied_count", 0),
            "total_delta_energy": data.get("total_delta_energy", 0.0),
        }

    def hdb_mem_tick_setup(seed: dict[str, Any]) -> dict[str, Any]:
        ctx = hdb_setup(seed)
        hdb_mem_apply_run(ctx)
        return ctx

    def hdb_mem_tick_run(ctx: dict[str, Any]) -> dict[str, Any]:
        return ctx["hdb"].tick_memory_activation_pool(trace_id="bench_hdb_mem_tick", tick_id="bench_hdb_mem_tick")

    def hdb_mem_tick_ctx(_: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        data = result["data"]
        return {
            "decayed_count": data.get("decayed_count", 0),
            "pruned_count": data.get("pruned_count", 0),
            "total_energy_before": data.get("total_energy_before", 0.0),
            "total_energy_after": data.get("total_energy_after", 0.0),
        }

    def obs_setup(seed: dict[str, Any]) -> dict[str, Any]:
        root, data_dir = _clone_dir(seed["seed_data_dir"], "ap_bench_obs_clone_")
        app = ObservatoryApp(
            config_override={
                "export_html": False,
                "export_json": False,
                "auto_open_html_report": False,
                "web_auto_open_browser": False,
                "state_pool_enable_placeholder_interfaces": False,
                "state_pool_enable_script_broadcast": False,
                "hdb_enable_background_repair": False,
                "hdb_data_dir": str(data_dir),
            }
        )
        _ensure_logger_dir(app.sensor, root / "logs" / "text_sensor")
        _ensure_logger_dir(app.pool, root / "logs" / "state_pool")
        _ensure_logger_dir(app.hdb, root / "logs" / "hdb")
        app.run_cycle(text="你好呀！")
        app.run_cycle(text="请记录当前输入并观察残差变化。")
        return {"root": root, "app": app}

    def obs_teardown(ctx: dict[str, Any]) -> None:
        _close_if_present(ctx.get("app"))
        shutil.rmtree(ctx["root"], ignore_errors=True)

    def obs_cycle_run(ctx: dict[str, Any]) -> dict[str, Any]:
        return ctx["app"].run_cycle(text=MEDIUM_TEXT)

    def obs_cycle_ctx(_: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        return {
            "structure_rounds": result["structure_level"]["result"]["round_count"],
            "stimulus_rounds": result["stimulus_level"]["result"]["round_count"],
            "memory_activation_count": result["memory_activation"]["snapshot"]["summary"]["count"],
            "final_state_active_item_count": result["final_state"]["state_snapshot"]["summary"].get("active_item_count", 0),
        }

    def obs_dashboard_run(ctx: dict[str, Any]) -> dict[str, Any]:
        return ctx["app"].get_dashboard_data()

    def obs_dashboard_ctx(_: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        return {
            "recent_cycle_count": len(result.get("recent_cycles", [])),
            "state_top_items": len(result.get("state_snapshot", {}).get("top_items", [])),
            "hdb_structure_count": result.get("hdb_snapshot", {}).get("summary", {}).get("structure_count", 0),
        }

    return [
        Scenario(
            name="text_sensor.simple_short",
            group="text_sensor",
            description="ingest_text(simple) short text, echo disabled",
            warmup=3,
            runs=12,
            setup=ts_simple_setup,
            run=ts_simple_run,
            teardown=ts_simple_teardown,
            context=ts_simple_context,
        ),
        Scenario(
            name="text_sensor.advanced_medium",
            group="text_sensor",
            description="ingest_text(advanced) medium text, jieba tokenization",
            warmup=3,
            runs=12,
            setup=ts_adv_setup,
            run=ts_adv_run,
            teardown=ts_simple_teardown,
            context=ts_adv_context,
        ),
        Scenario(
            name="text_sensor.echo_steady_short",
            group="text_sensor",
            description="ingest_text(simple) short text, echo enabled after pre-seeding",
            warmup=2,
            runs=10,
            setup=ts_echo_setup,
            run=ts_echo_run,
            teardown=ts_simple_teardown,
            context=ts_echo_context,
        ),
        Scenario(
            name="state_pool.apply_packet_fresh",
            group="state_pool",
            description="apply_stimulus_packet on empty pool (packet built from seeded sensor)",
            warmup=3,
            runs=12,
            setup=sp_apply_setup,
            run=sp_apply_run,
            teardown=sp_apply_teardown,
            context=sp_apply_context,
        ),
        Scenario(
            name="state_pool.tick_seeded",
            group="state_pool",
            description="tick_maintain_state_pool after applying one packet and injecting EV",
            warmup=2,
            runs=10,
            setup=sp_tick_setup,
            run=sp_tick_run,
            teardown=sp_apply_teardown,
            context=sp_tick_context,
        ),
        Scenario(
            name="state_pool.snapshot_seeded",
            group="state_pool",
            description="get_state_snapshot(top_k=32) after applying one packet",
            warmup=2,
            runs=10,
            setup=sp_snapshot_setup,
            run=sp_snapshot_run,
            teardown=sp_apply_teardown,
            context=sp_snapshot_context,
        ),
        Scenario(
            name="hdb.structure_rs_seeded",
            group="hdb",
            description="run_structure_level_retrieval_storage on cloned seeded HDB data",
            warmup=2,
            runs=8,
            setup=hdb_setup,
            run=hdb_structure_run,
            teardown=hdb_teardown,
            context=hdb_structure_ctx,
        ),
        Scenario(
            name="hdb.stimulus_rs_seeded",
            group="hdb",
            description="run_stimulus_level_retrieval_storage on cloned seeded HDB data",
            warmup=2,
            runs=8,
            setup=hdb_setup,
            run=hdb_stimulus_run,
            teardown=hdb_teardown,
            context=hdb_stimulus_ctx,
        ),
        Scenario(
            name="hdb.induction_seeded",
            group="hdb",
            description="run_induction_propagation on cloned seeded HDB data",
            warmup=2,
            runs=8,
            setup=hdb_setup,
            run=hdb_induction_run,
            teardown=hdb_teardown,
            context=hdb_induction_ctx,
        ),
        Scenario(
            name="hdb.memory_apply_seeded",
            group="hdb",
            description="apply_memory_activation_targets on cloned seeded HDB data",
            warmup=2,
            runs=8,
            setup=hdb_setup,
            run=hdb_mem_apply_run,
            teardown=hdb_teardown,
            context=hdb_mem_apply_ctx,
        ),
        Scenario(
            name="hdb.memory_tick_seeded",
            group="hdb",
            description="tick_memory_activation_pool after applying one memory target",
            warmup=2,
            runs=8,
            setup=hdb_mem_tick_setup,
            run=hdb_mem_tick_run,
            teardown=hdb_teardown,
            context=hdb_mem_tick_ctx,
        ),
        Scenario(
            name="observatory.run_cycle_seeded",
            group="observatory",
            description="observatory.run_cycle on cloned seeded HDB data (after 2 warm cycles)",
            warmup=1,
            runs=6,
            setup=obs_setup,
            run=obs_cycle_run,
            teardown=obs_teardown,
            context=obs_cycle_ctx,
        ),
        Scenario(
            name="observatory.dashboard_seeded",
            group="observatory",
            description="observatory.get_dashboard_data after warm cycles",
            warmup=1,
            runs=6,
            setup=obs_setup,
            run=obs_dashboard_run,
            teardown=obs_teardown,
            context=obs_dashboard_ctx,
        ),
    ]


def main() -> None:
    seed = _build_seed()
    try:
        env = {
            "timestamp": _now_iso(),
            "cwd": str(ROOT),
            "python_version": sys.version,
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
            "seed_hdb_summary": seed["hdb_summary"],
        }
        results = [run_scenario(spec, seed) for spec in make_scenarios()]
        payload = {"environment": env, "results": results}
        OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote benchmark JSON: {OUTPUT_JSON}")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    finally:
        shutil.rmtree(seed["seed_root"], ignore_errors=True)


if __name__ == "__main__":
    main()
