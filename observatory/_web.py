# -*- coding: utf-8 -*-
"""
AP 原型观测台 Web 服务（本地）
===========================

说明：
  - 本文件提供一个最小本地 HTTP 服务，用于观测台前端页面与 API 调用。
  - 目标是“可用、可读、可审计”，而非生产级别的高并发 Web 框架。

English (short):
  Local web server for the AP observatory.
"""

from __future__ import annotations

import copy
import json
import mimetypes
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
import traceback

from ._app import ObservatoryApp
from .agent_runtime import AgentRuntime
from . import experiment as exp
from .experiment.runner import apply_experiment_default_app_overrides


EXPERIMENT_TERMINAL_STATUSES = {"completed", "stopped_max_ticks", "cancelled", "failed"}
EXPERIMENT_ACTIVE_STATUSES = {"queued", "waiting_for_app_lock", "running", "cancelling"}
EXPERIMENT_CANCEL_STALE_MS = 90_000


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _reset_app_runtime_modules(
    app: ObservatoryApp,
    *,
    clear_hdb: bool,
    trace_prefix: str,
    reason: str,
    operator: str,
) -> dict[str, Any]:
    """Reset runtime modules through the app helper, with a legacy-safe fallback."""
    if hasattr(app, "_clear_runtime_modules"):
        return app._clear_runtime_modules(  # type: ignore[attr-defined]
            clear_hdb=clear_hdb,
            trace_prefix=trace_prefix,
            reason=reason,
            operator=operator,
        )

    result: dict[str, Any] = {
        "sensor": app.sensor.clear_echo_pool(trace_id=f"{trace_prefix}_sensor"),
        "state_pool": app.pool.clear_state_pool(
            trace_id=f"{trace_prefix}_pool",
            reason=reason,
            operator=operator,
        ),
    }
    if clear_hdb:
        result["hdb"] = app.hdb.clear_hdb(trace_id=trace_prefix, reason=reason, operator=operator)
    elif hasattr(getattr(app, "hdb", None), "clear_runtime_state"):
        result["hdb_runtime"] = app.hdb.clear_runtime_state(trace_id=f"{trace_prefix}_hdb_runtime", reason=reason)  # type: ignore[attr-defined]

    for module_name in ("time_sensor", "action", "attention", "cognitive_stitching"):
        module = getattr(app, module_name, None)
        if hasattr(module, "clear_runtime_state"):
            try:
                result[module_name] = module.clear_runtime_state(  # type: ignore[attr-defined]
                    trace_id=f"{trace_prefix}_{module_name}",
                    reason=reason,
                )
            except TypeError:
                result[module_name] = module.clear_runtime_state()  # type: ignore[attr-defined]

    app._last_report = None  # type: ignore[attr-defined]
    app._report_history = []  # type: ignore[attr-defined]
    old_tick_counter = int(getattr(app, "tick_counter", 0) or 0)
    app.tick_counter = 0  # type: ignore[attr-defined]
    if hasattr(app, "_started_at"):
        app._started_at = int(time.time() * 1000)  # type: ignore[attr-defined]
    result["report_cache_cleared"] = True
    result["tick_counter_reset"] = True
    result["tick_counter_before_reset"] = old_tick_counter
    result["started_at_reset"] = True
    return result


def _normalize_experiment_job_state(job: dict[str, Any]) -> dict[str, Any]:
    """Keep experiment job rows from staying in an endless cancelling state."""

    status = str(job.get("status", "") or "").lower()
    if status in EXPERIMENT_TERMINAL_STATUSES:
        return job

    now_ms = int(time.time() * 1000)
    if bool(job.get("cancelled", False)):
        requested_at = _coerce_int(
            job.get("cancel_requested_at_ms")
            or job.get("updated_at_ms")
            or job.get("last_progress_at_ms")
            or job.get("started_at_ms")
            or job.get("created_at_ms")
            or now_ms,
            now_ms,
        )
        job["cancel_requested_at_ms"] = requested_at
        elapsed_ms = max(0, now_ms - requested_at)
        if elapsed_ms >= EXPERIMENT_CANCEL_STALE_MS:
            job["status"] = "cancelled"
            job["stage"] = "cancelled"
            job["stage_label"] = "已取消（停止请求超时兜底）"
            job["finished_at_ms"] = job.get("finished_at_ms") or now_ms
            job["updated_at_ms"] = now_ms
            job["lock_waiting"] = False
        else:
            job["status"] = "cancelling"
            job["stage"] = str(job.get("stage", "") or "cancelling")
            job["stage_label"] = str(job.get("stage_label", "") or "正在停止：会在当前 tick 或收尾阶段结束后取消")
            job["cancel_elapsed_ms"] = elapsed_ms
    return job


def _repair_job_row(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "repair_job_id": str(job.get("repair_job_id", "") or job.get("job_id", "") or ""),
        "job_id": str(job.get("job_id", "") or job.get("repair_job_id", "") or ""),
        "job_type": str(job.get("job_type", "repair") or "repair"),
        "status": str(job.get("status", "") or ""),
        "scope": str(job.get("repair_scope", job.get("scope", "")) or ""),
        "target_id": str(job.get("target_id", "") or job.get("target", "") or "全局"),
        "processed_count": int(job.get("processed_count", 0) or 0),
        "repaired_count": int(job.get("repaired_count", 0) or 0),
        "deleted_count": int(job.get("deleted_count", 0) or 0),
        "issue_count": int(job.get("issue_count", 0) or 0),
        "batch_limit": int(job.get("batch_limit", 0) or 0),
        "created_at_ms": int(job.get("created_at", job.get("created_at_ms", 0)) or 0),
        "started_at_ms": int(job.get("started_at", job.get("started_at_ms", 0)) or 0),
        "updated_at_ms": int(job.get("updated_at", job.get("updated_at_ms", 0)) or 0),
        "finished_at_ms": int(job.get("finished_at", job.get("finished_at_ms", 0)) or 0),
        "request": {
            "repair_scope": job.get("repair_scope", ""),
            "target_id": job.get("target_id", ""),
            "batch_limit": job.get("batch_limit", 0),
            "background": job.get("background", False),
        },
        "data": job,
        "error": "; ".join(str(item.get("error", "")) for item in (job.get("errors", []) or []) if isinstance(item, dict) and item.get("error")),
    }


def _idle_job_row(job: dict[str, Any]) -> dict[str, Any]:
    data = job.get("data") if isinstance(job.get("data"), dict) else {}
    hdb_data = (((data or {}).get("hdb") or {}).get("data") or {}) if isinstance(data, dict) else {}
    progress = dict(job.get("progress", {}) or {})
    scanned = progress.get("scanned_structure_db_count", hdb_data.get("scanned_structure_db_count", 0))
    updated = progress.get("updated_structure_db_count", hdb_data.get("updated_structure_db_count", 0))
    return {
        "repair_job_id": str(job.get("job_id", "") or ""),
        "job_id": str(job.get("job_id", "") or ""),
        "job_type": str(job.get("job_type", "idle_consolidation") or "idle_consolidation"),
        "status": str(job.get("status", "") or ""),
        "scope": "手动闲时整理",
        "target_id": "HDB",
        "processed_count": int(scanned or 0),
        "repaired_count": int(updated or 0),
        "deleted_count": int(progress.get("trimmed_diff_entry_total", hdb_data.get("trimmed_diff_entry_total", 0)) or 0),
        "issue_count": int(progress.get("trimmed_group_entry_total", hdb_data.get("trimmed_group_entry_total", 0)) or 0),
        "batch_limit": int((job.get("request", {}) or {}).get("batch_limit", 0) or 0),
        "created_at_ms": int(job.get("created_at_ms", 0) or 0),
        "started_at_ms": int(job.get("started_at_ms", 0) or 0),
        "updated_at_ms": int(job.get("updated_at_ms", job.get("finished_at_ms", job.get("started_at_ms", 0))) or 0),
        "finished_at_ms": int(job.get("finished_at_ms", 0) or 0),
        "request": job.get("request", {}),
        "progress": progress,
        "data": job.get("data"),
        "error": str(job.get("error", "") or ""),
    }


def _job_stage_label(stage: Any, status: Any = "") -> str:
    raw = str(stage or status or "").strip()
    labels = {
        "queued": "排队中",
        "loading_dataset": "读取数据集",
        "preparing_manifest": "准备运行清单",
        "prepared": "准备初始化运行态",
        "waiting_for_app_lock": "等待主循环锁/维护任务",
        "capturing_baseline": "读取运行前基线",
        "applying_overrides": "应用运行覆盖",
        "resetting_runtime": "清理运行态",
        "configuring_exports": "配置导出开关",
        "configuring_time_sensor": "配置时间感受器",
        "running": "运行中",
        "running_tick": "执行 tick",
        "tick_finished": "tick 已写入指标",
        "idle_consolidation": "HDB 闲时整理",
        "idle_consolidation_cs": "认知拼接整理",
        "finished": "已结束",
        "completed": "已完成",
        "stopped_max_ticks": "达到最大 tick",
        "cancelled": "已取消",
        "cancelling": "正在停止",
        "failed": "失败",
    }
    return labels.get(raw, raw or "未知")


def _experiment_job_row(job: dict[str, Any]) -> dict[str, Any]:
    job = _normalize_experiment_job_state(job)
    status = str(job.get("status", "") or "")
    stage = str(job.get("stage", "") or status or "")
    tick_done = int(job.get("tick_done", job.get("source_tick_done", 0)) or 0)
    tick_planned = job.get("tick_planned", None)
    try:
        planned_num = int(tick_planned) if tick_planned is not None else 0
    except Exception:
        planned_num = 0
    progress_ratio = (float(tick_done) / float(planned_num)) if planned_num > 0 else 0.0
    latest_metrics_preview = job.get("latest_metrics_preview") if isinstance(job.get("latest_metrics_preview"), dict) else None
    return {
        "job_id": str(job.get("job_id", "") or ""),
        "job_type": "experiment_run",
        "type_label": "数据集运行",
        "status": status,
        "stage": stage,
        "stage_label": str(job.get("stage_label", "") or _job_stage_label(stage, status)),
        "run_id": str(job.get("run_id", "") or ""),
        "dataset_id": str(job.get("dataset_id", "") or ""),
        "tick_done": tick_done,
        "source_tick_done": int(job.get("source_tick_done", tick_done) or 0),
        "synthetic_tick_done": int(job.get("synthetic_tick_done", 0) or 0),
        "executed_tick_done_total": int(job.get("executed_tick_done_total", tick_done) or 0),
        "tick_planned": tick_planned,
        "progress_ratio": max(0.0, min(1.0, progress_ratio)),
        "lock_waiting": bool(job.get("lock_waiting", False)),
        "lock_wait_ms": int(job.get("lock_wait_ms", 0) or 0),
        "last_lock_wait_ms": int(job.get("last_lock_wait_ms", 0) or 0),
        "created_at_ms": int(job.get("created_at_ms", 0) or 0),
        "started_at_ms": int(job.get("started_at_ms", 0) or 0),
        "updated_at_ms": int(job.get("updated_at_ms", job.get("last_progress_at_ms", job.get("started_at_ms", 0))) or 0),
        "finished_at_ms": int(job.get("finished_at_ms", 0) or 0),
        "error": str(job.get("error", "") or ""),
        "last_tick_index": int(job.get("last_tick_index", -1) or -1),
        "latest_metrics_tick_index": int(job.get("latest_metrics_tick_index", job.get("last_tick_index", -1)) or -1),
        "latest_metrics_preview": dict(latest_metrics_preview) if isinstance(latest_metrics_preview, dict) else None,
        "data": job,
    }


def _active_experiment_job_with_preview(server: "ObservatoryWebServer") -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    with server.experiment_jobs_lock:
        jobs = [
            dict(job)
            for job in server.experiment_jobs.values()
            if isinstance(job, dict)
            and (
                str(job.get("status", "") or "").lower() in EXPERIMENT_ACTIVE_STATUSES
                or str(job.get("stage", "") or "").lower() in EXPERIMENT_ACTIVE_STATUSES
            )
        ]
    if not jobs:
        return None, None
    jobs.sort(
        key=lambda item: int(item.get("updated_at_ms", item.get("last_progress_at_ms", item.get("started_at_ms", 0))) or 0),
        reverse=True,
    )
    job = jobs[0]
    preview = job.get("latest_metrics_preview") if isinstance(job.get("latest_metrics_preview"), dict) else None
    return _experiment_job_row(job), dict(preview) if isinstance(preview, dict) else None


def _generic_background_job_row(job: dict[str, Any], *, job_type: str, type_label: str) -> dict[str, Any]:
    status = str(job.get("status", "") or "")
    stage = str(job.get("stage", "") or status or "")
    return {
        "job_id": str(job.get("job_id", "") or job.get("repair_job_id", "") or ""),
        "job_type": job_type,
        "type_label": type_label,
        "status": status,
        "stage": stage,
        "stage_label": str(job.get("stage_label", "") or _job_stage_label(stage, status)),
        "run_id": str(job.get("run_id", "") or ""),
        "created_at_ms": int(job.get("created_at_ms", 0) or 0),
        "started_at_ms": int(job.get("started_at_ms", 0) or 0),
        "updated_at_ms": int(job.get("updated_at_ms", job.get("finished_at_ms", job.get("started_at_ms", 0))) or 0),
        "finished_at_ms": int(job.get("finished_at_ms", 0) or 0),
        "error": str(job.get("error", "") or ""),
        "data": job,
    }


def _collect_background_jobs(server: "ObservatoryWebServer", *, limit: int = 80) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with server.experiment_jobs_lock:
        rows.extend(_experiment_job_row(job) for job in server.experiment_jobs.values() if isinstance(job, dict))
    with server.maintenance_jobs_lock:
        for job_id, job in server.maintenance_jobs.items():
            if job_id == "_seq" or not isinstance(job, dict):
                continue
            row = _generic_background_job_row(dict(job), job_type=str(job.get("job_type", "maintenance") or "maintenance"), type_label="维护任务")
            row.update(_idle_job_row(dict(job)))
            row["type_label"] = "维护任务"
            rows.append(row)
    try:
        rows.extend(
            _generic_background_job_row(dict(job), job_type="hdb_repair", type_label="HDB 修复")
            for job in server.app.hdb._repair.jobs.values()
            if isinstance(job, dict)
        )
    except Exception:
        pass
    with server.llm_review_jobs_lock:
        rows.extend(_generic_background_job_row(dict(job), job_type="llm_review", type_label="LLM 审查") for job in server.llm_review_jobs.values() if isinstance(job, dict))
    with server.auto_tuner_llm_jobs_lock:
        rows.extend(_generic_background_job_row(dict(job), job_type="auto_tuner_llm", type_label="AutoTuner LLM") for job in server.auto_tuner_llm_jobs.values() if isinstance(job, dict))
    rows.sort(
        key=lambda item: int(item.get("updated_at_ms", 0) or item.get("created_at_ms", 0) or item.get("started_at_ms", 0) or 0),
        reverse=True,
    )
    return rows[: max(1, int(limit or 80))]


class ObservatoryWebServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, host: str, port: int, app: ObservatoryApp):
        self.app = app
        self.app_lock = threading.RLock()
        self.agent_runtime = AgentRuntime(app)
        self.agent_runtime.set_app_lock(self.app_lock)
        self.agent_background_lock = threading.RLock()
        self.agent_background_stop = threading.Event()
        self.agent_background_thread: threading.Thread | None = None
        self.agent_foreground_priority = threading.Event()
        self.agent_foreground_priority_lock = threading.RLock()
        self.agent_foreground_priority_until_ms = 0
        self.agent_foreground_priority_reason = ""
        self.agent_turn_jobs: dict[str, dict[str, Any]] = {}
        self.agent_turn_jobs_lock = threading.RLock()
        self.agent_turn_job_queue: queue.Queue[str] = queue.Queue()
        self.agent_turn_job_stop = threading.Event()
        self.agent_turn_worker: threading.Thread | None = None
        self.group_continuity_gate_jobs: dict[str, dict[str, Any]] = {}
        self.group_continuity_gate_jobs_lock = threading.RLock()
        self.group_continuity_gate_queue: queue.Queue[str] = queue.Queue()
        self.group_continuity_gate_stop = threading.Event()
        self.group_continuity_gate_worker: threading.Thread | None = None
        self.agent_background_state: dict[str, Any] = {
            "running": False,
            "started_at_ms": 0,
            "stopped_at_ms": 0,
            "step_count": 0,
            "trigger_count": 0,
            "thought_check_count": 0,
            "last_save_at_ms": 0,
            "last_save_step_count": 0,
            "last_save_wall_ms": 0,
            "last_step_at_ms": 0,
            "last_result": None,
            "last_error": "",
        }
        # Background experiment jobs (in-memory, non-persistent).
        self.experiment_jobs: dict[str, dict[str, Any]] = {}
        self.experiment_jobs_lock = threading.RLock()
        # Background LLM review jobs (in-memory, non-persistent; status is persisted under run_dir).
        self.llm_review_jobs: dict[str, dict[str, Any]] = {}
        self.llm_review_jobs_lock = threading.RLock()
        # Background auto-tuner LLM analysis jobs.
        self.auto_tuner_llm_jobs: dict[str, dict[str, Any]] = {}
        self.auto_tuner_llm_jobs_lock = threading.RLock()
        # Background maintenance jobs (idle consolidation etc.).
        self.maintenance_jobs: dict[str, dict[str, Any]] = {}
        self.maintenance_jobs_lock = threading.RLock()
        # Dataset catalog cache keyed by resolved path + file fingerprint.
        self.dataset_catalog_cache: dict[str, dict[str, Any]] = {}
        self.dataset_catalog_lock = threading.RLock()
        # Auto-tuner state cache for UI polling; allows quick/stale responses when the app lock is busy.
        self.auto_tuner_state_cache: dict[str, Any] = {}
        self.auto_tuner_state_lock = threading.RLock()
        self.web_host = str(host or "127.0.0.1")
        self.web_port = int(port or 8765)
        self.static_dir = Path(__file__).resolve().parent / "web_static"
        self.next_static_dir = Path(__file__).resolve().parent / "web_static_next"
        self.started_at = app._started_at
        self._ensure_agent_turn_worker()
        self._ensure_group_continuity_gate_worker()
        super().__init__((host, port), _build_handler())

    def _ensure_agent_turn_worker(self) -> None:
        with self.agent_turn_jobs_lock:
            if self.agent_turn_worker and self.agent_turn_worker.is_alive():
                return
            self.agent_turn_job_stop.clear()
            self.agent_turn_worker = threading.Thread(target=self._agent_turn_worker_loop, daemon=True, name="pa-agent-turn-worker")
            self.agent_turn_worker.start()

    def _ensure_group_continuity_gate_worker(self) -> None:
        with self.group_continuity_gate_jobs_lock:
            if self.group_continuity_gate_worker and self.group_continuity_gate_worker.is_alive():
                return
            self.group_continuity_gate_stop.clear()
            self.group_continuity_gate_worker = threading.Thread(
                target=self._group_continuity_gate_worker_loop,
                daemon=True,
                name="pa-group-continuity-gate-worker",
            )
            self.group_continuity_gate_worker.start()

    def _mark_agent_foreground_pending(self, reason: str = "foreground_input", *, hold_ms: int = 4000) -> None:
        now = int(time.time() * 1000)
        hold_ms = max(500, min(30_000, int(hold_ms or 4000)))
        with self.agent_foreground_priority_lock:
            self.agent_foreground_priority_until_ms = max(self.agent_foreground_priority_until_ms, now + hold_ms)
            self.agent_foreground_priority_reason = str(reason or "foreground_input")[:120]
            self.agent_foreground_priority.set()

    def _agent_foreground_is_pending(self) -> bool:
        if self._has_active_agent_turn_jobs():
            self.agent_foreground_priority.set()
            return True
        now = int(time.time() * 1000)
        with self.agent_foreground_priority_lock:
            if self.agent_foreground_priority.is_set() and now <= int(self.agent_foreground_priority_until_ms or 0):
                return True
            self.agent_foreground_priority.clear()
            self.agent_foreground_priority_until_ms = 0
            self.agent_foreground_priority_reason = ""
        return False

    def _clear_agent_foreground_priority_if_idle(self) -> None:
        if self._has_active_agent_turn_jobs():
            return
        with self.agent_foreground_priority_lock:
            self.agent_foreground_priority.clear()
            self.agent_foreground_priority_until_ms = 0
            self.agent_foreground_priority_reason = ""

    def _job_stage_label(self, stage: Any) -> str:
        stage_name = str(stage or "").strip().lower()
        labels = {
            "queued": "排队中",
            "ingesting_user_input": "输入进入 AP 文本感受器",
            "input_ap_tick_done": "输入 AP tick 完成",
            "user_input_ingested": "输入感受器处理完成",
            "pre_thought_tick": "AP 预运行中",
            "building_ap_packet": "整理 AP 状态包",
            "waiting_llm": "等待 LLM",
            "llm_returned": "LLM 已返回",
            "executing_tools": "执行工具",
            "thought_ready": "想法已生成",
            "thought_ingested": "想法已回灌 AP",
            "tool_result_ingested": "工具结果已回灌",
            "post_thought_tick": "想法后整理",
            "decision_continue": "继续下一段想法",
            "decision_ready": "决策已形成",
            "replying": "准备回复用户",
            "reply_ingested": "回复已回灌 AP",
            "operator_stopped": "已手动停止，进入休眠",
            "cancelled": "已取消",
            "completed": "本轮完成",
            "failed": "本轮失败",
        }
        return labels.get(stage_name, str(stage or ""))

    def _trim_agent_turn_jobs_locked(self, *, keep: int = 60) -> None:
        keep = max(12, min(300, int(keep or 60)))
        jobs = [job for job in self.agent_turn_jobs.values() if isinstance(job, dict)]
        if len(jobs) <= keep:
            return
        jobs.sort(key=lambda item: int(item.get("updated_at_ms", item.get("created_at_ms", 0)) or 0), reverse=True)
        keep_ids = {str(item.get("job_id") or "") for item in jobs[:keep]}
        for job_id in list(self.agent_turn_jobs.keys()):
            if job_id not in keep_ids:
                self.agent_turn_jobs.pop(job_id, None)

    def clear_agent_history(self, *, clear_ap_runtime: bool = False) -> dict[str, Any]:
        now = int(time.time() * 1000)
        with self.agent_turn_jobs_lock:
            job_count_before = len(self.agent_turn_jobs)
            kept: dict[str, dict[str, Any]] = {}
            cancelled_count = 0
            for job_id, job in list(self.agent_turn_jobs.items()):
                if not isinstance(job, dict):
                    continue
                if str(job.get("status") or "") in {"queued", "running"}:
                    cancelled_count += 1
                    job["cancel_requested"] = True
                    job["stop_reason"] = "history_clear"
                    job["status"] = "cancelled"
                    job["stage"] = "operator_stopped"
                    job["stage_label"] = "已清空历史，停止本轮"
                    job["updated_at_ms"] = now
                    job["finished_at_ms"] = job.get("finished_at_ms") or now
                    job["hidden_after_clear"] = True
                    job["user_message"] = {}
                    job["initial_user_message"] = {}
                    job["visible_user_messages"] = []
                    job["absorbed_messages"] = []
                    job["reply_message"] = {}
                    job["reply_messages"] = []
                    job["replies"] = []
                    job["thought"] = {}
                    job["thoughts"] = []
                    job["payload"] = {}
                    kept[job_id] = job
            self.agent_turn_jobs = kept
        with self.app_lock:
            result = self.agent_runtime.clear_history(clear_ap_runtime=clear_ap_runtime)
        try:
            self.agent_runtime.record_event(
                {
                    "event": "turn_jobs_cleared",
                    "cleared_turn_jobs": job_count_before,
                    "cancelled_active_jobs": cancelled_count,
                }
            )
        except Exception:
            pass
        if isinstance(result, dict):
            result = dict(result)
            result["cleared_turn_jobs"] = job_count_before
            result["cancelled_active_jobs"] = cancelled_count
        return result

    def _public_agent_turn_job(self, job: dict[str, Any], *, include_payload: bool = False) -> dict[str, Any]:
        row = dict(job or {})
        payload = row.get("payload") if include_payload and isinstance(row.get("payload"), dict) else None
        return {
            "job_id": str(row.get("job_id") or ""),
            "status": str(row.get("status") or ""),
            "stage": str(row.get("stage") or ""),
            "stage_label": str(row.get("stage_label") or self._job_stage_label(row.get("stage")) or row.get("status") or ""),
            "created_at_ms": int(row.get("created_at_ms", 0) or 0),
            "started_at_ms": int(row.get("started_at_ms", 0) or 0),
            "updated_at_ms": int(row.get("updated_at_ms", 0) or 0),
            "finished_at_ms": int(row.get("finished_at_ms", 0) or 0),
            "queue_index": int(row.get("queue_index", 0) or 0),
            "turn_id": str(row.get("turn_id") or ""),
            "source": str(row.get("source") or ""),
            "decision": str(row.get("decision") or ""),
            "thought_count": int(row.get("thought_count", 0) or 0),
            "reply_count": int(row.get("reply_count", 0) or 0),
            "ap_tick_count": int(row.get("ap_tick_count", 0) or 0),
            "attachment_count": int(row.get("attachment_count", 0) or 0),
            "current_thought_index": int(row.get("current_thought_index", 0) or 0),
            "thought_budget": int(row.get("thought_budget", 0) or 0),
            "pre_tick_index": int(row.get("pre_tick_index", 0) or 0),
            "pre_tick_total": int(row.get("pre_tick_total", 0) or 0),
            "post_tick_index": int(row.get("post_tick_index", 0) or 0),
            "post_tick_total": int(row.get("post_tick_total", 0) or 0),
            "llm_wait_tick_count": int(row.get("llm_wait_tick_count", 0) or 0),
            "llm_wait_tick_total": int(row.get("llm_wait_tick_total", 0) or 0),
            "llm_status": dict(row.get("llm_status") or {}) if isinstance(row.get("llm_status"), dict) else {},
            "current_thought_text": str(row.get("current_thought_text") or ""),
            "current_reply_text": str(row.get("current_reply_text") or ""),
            "why": str(row.get("why") or ""),
            "confidence": row.get("confidence"),
            "tool_calls": list(row.get("tool_calls") or [])[:5],
            "tool_results": list(row.get("tool_results") or [])[:5],
            "adapter_replies": list(row.get("adapter_replies") or [])[:8],
            "bridges": list(row.get("bridges") or [])[:12],
            "bridge_teacher_feedback": list(row.get("bridge_teacher_feedback") or [])[:12],
            "recent_reports": list(row.get("recent_reports") or [])[-8:],
            "ap_packet": dict(row.get("ap_packet") or {}) if isinstance(row.get("ap_packet"), dict) else {},
            "user_message": dict(row.get("user_message") or {}) if isinstance(row.get("user_message"), dict) else {},
            "reply_message": dict(row.get("reply_message") or {}) if isinstance(row.get("reply_message"), dict) else {},
            "reply_messages": list(row.get("reply_messages") or row.get("replies") or [])[-8:],
            "visible_user_messages": list(row.get("visible_user_messages") or [])[-12:],
            "absorbed_messages": list(row.get("absorbed_messages") or [])[-12:],
            "pending_external_input_count": int(
                row.get("pending_external_input_count", getattr(self.agent_runtime, "pending_external_input_count", lambda: 0)()) or 0
            ),
            "thought": dict(row.get("thought") or {}) if isinstance(row.get("thought"), dict) else {},
            "turn": dict(row.get("turn") or {}) if isinstance(row.get("turn"), dict) else {},
            "thoughts": list(row.get("thoughts") or [])[:8],
            "replies": list(row.get("replies") or [])[:4],
            "cancel_requested": bool(row.get("cancel_requested", False)),
            "stop_reason": str(row.get("stop_reason") or ""),
            "error": str(row.get("error") or ""),
            "result_status": dict(row.get("result_status") or {}) if isinstance(row.get("result_status"), dict) else {},
            "payload": payload,
        }

    def submit_agent_turn(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_agent_turn_worker()
        now = int(time.time() * 1000)
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")
        source = str(payload.get("source") or "user")
        attachments = payload.get("attachments") if isinstance(payload.get("attachments"), list) else []
        self._mark_agent_foreground_pending("agent_message_submit")
        with self.agent_turn_jobs_lock:
            active_jobs = [
                item
                for item in self.agent_turn_jobs.values()
                if isinstance(item, dict) and str(item.get("status") or "") in {"queued", "running"}
            ]
            running_jobs = [
                item
                for item in active_jobs
                if str(item.get("status") or "") == "running"
            ]
            queue_index = len(active_jobs)
            job_id = f"agent_job_{now}_{len(self.agent_turn_jobs) + 1}"
            client_message_id = str(payload.get("_client_message_id") or payload.get("_message_id") or "").strip()
            adapter_event = copy.deepcopy(payload.get("adapter_event")) if isinstance(payload.get("adapter_event"), dict) else {}
            reply_target = copy.deepcopy(payload.get("reply_target")) if isinstance(payload.get("reply_target"), dict) else {}
            conversation_id = str(payload.get("conversation_id") or adapter_event.get("conversation_id") or reply_target.get("conversation_id") or "").strip()
            adapter_label = str(payload.get("adapter_label") or adapter_event.get("target_label") or reply_target.get("target_label") or "").strip()
            user_message = {
                "id": client_message_id or f"queued_msg_{now}",
                "turn_id": "",
                "role": "user",
                "text": text,
                "source": source,
                "conversation_id": conversation_id,
                "reply_target": reply_target,
                "adapter_event": adapter_event,
                "adapter_label": adapter_label,
                "attachments": attachments[:12],
                "created_at_ms": now,
            }
            visible_user_message = copy.deepcopy(payload.get("_visible_user_message")) if isinstance(payload.get("_visible_user_message"), dict) else {}
            if visible_user_message:
                user_message.update({k: v for k, v in visible_user_message.items() if k != "payload"})
            absorbable_stages = {
                "queued",
                "waiting_for_app_lock",
                "ingesting_user_input",
                "input_ap_tick_done",
                "user_input_ingested",
                "pre_thought_tick",
                "building_ap_packet",
                "waiting_llm",
                "waiting_llm_ap_tick",
                "llm_returned",
                "executing_tools",
                "thought_ready",
                "reply_deferred_for_external_input",
                "thought_ingested",
                "tool_result_ingested",
                "post_thought_tick",
                "decision_continue",
                "external_input_absorbed",
                "external_input_ingested",
                "external_input_tick_done",
                "external_input_bridge_done",
            }
            absorb_targets = [
                item
                for item in (running_jobs or active_jobs)
                if str(item.get("stage") or "") in absorbable_stages
            ]
            if absorb_targets:
                if running_jobs:
                    absorb_targets.sort(key=lambda item: int(item.get("started_at_ms", item.get("updated_at_ms", 0)) or 0), reverse=True)
                else:
                    absorb_targets.sort(key=lambda item: int(item.get("created_at_ms", item.get("updated_at_ms", 0)) or 0))
                target = absorb_targets[0]
                target_job_id = str(target.get("job_id") or "")
                try:
                    absorbed_message = self.agent_runtime.enqueue_external_input(
                        {
                            **copy.deepcopy(payload),
                            "id": user_message["id"],
                            "role": "user",
                        }
                    )
                except Exception:
                    absorbed_message = user_message
                absorbed = [item for item in list(target.get("absorbed_messages") or []) if isinstance(item, dict)]
                initial_message = target.get("initial_user_message") or target.get("user_message")
                if isinstance(initial_message, dict) and initial_message.get("id"):
                    initial_id = str(initial_message.get("id") or "")
                    if all(str(item.get("id") or "") != initial_id for item in absorbed):
                        absorbed.insert(0, initial_message)
                absorbed.append(absorbed_message if isinstance(absorbed_message, dict) else user_message)
                target["absorbed_messages"] = absorbed[-12:]
                target["user_message"] = absorbed[-1]
                target["visible_user_messages"] = absorbed[-12:]
                target["stage"] = "external_input_absorbed"
                target["stage_label"] = "新输入已插入当前思考"
                target["updated_at_ms"] = now
                public = self._public_agent_turn_job(target, include_payload=False)
                try:
                    self.agent_runtime.record_event(
                        {
                            "event": "turn_job_absorbed_external_input",
                            "job_id": target_job_id,
                            "message_id": user_message["id"],
                            "source": source,
                            "attachment_count": len(attachments),
                        }
                    )
                except Exception:
                    pass
                return {"job": public}
            job = {
                "job_id": job_id,
                "status": "queued",
                "stage": "queued",
                "stage_label": "排队中",
                "created_at_ms": now,
                "started_at_ms": 0,
                "updated_at_ms": now,
                "finished_at_ms": 0,
                "queue_index": queue_index,
                "source": source,
                "decision": "continue_thinking",
                "thought_count": 0,
                "reply_count": 0,
                "ap_tick_count": 0,
                "attachment_count": len(attachments),
                "current_thought_index": 0,
                "thought_budget": int(getattr(self.agent_runtime.config, "max_thoughts_per_turn", 1) or 1),
                "current_thought_text": "",
                "current_reply_text": "",
                "tool_calls": [],
                "tool_results": [],
                "recent_reports": [],
                "ap_packet": {},
                "user_message": user_message,
                "initial_user_message": user_message,
                "visible_user_messages": [user_message],
                "reply_message": {},
                "thought": {},
                "turn": {},
                "thoughts": [],
                "replies": [],
                "cancel_requested": False,
                "stop_reason": "",
                "error": "",
                "payload": {**copy.deepcopy(payload), "_message_id": user_message["id"]},
            }
            if source == "napcat_qq" or str(adapter_event.get("adapter") or "") == "napcat_qq" or str(reply_target.get("adapter") or "") == "napcat_qq":
                try:
                    visible_message = visible_user_message or self.agent_runtime._append_visible_adapter_message(
                        adapter_event if adapter_event else {**copy.deepcopy(payload), "reply_target": reply_target},
                        source=source or "napcat_qq",
                    )
                    if isinstance(visible_message, dict):
                        job["user_message"] = {k: v for k, v in visible_message.items() if k != "payload"}
                        job["initial_user_message"] = job["user_message"]
                        job["visible_user_messages"] = [job["user_message"]]
                        job["payload"]["_message_id"] = str(job["user_message"].get("id") or user_message["id"])
                        job["payload"]["_skip_user_message_append"] = True
                        job["payload"]["_visible_user_message"] = job["user_message"]
                except Exception:
                    pass
            self.agent_turn_jobs[job_id] = job
            self._trim_agent_turn_jobs_locked()
        try:
            self.agent_runtime.record_event({"event": "turn_job_queued", "job_id": job_id, "source": source, "attachment_count": len(attachments)})
        except Exception:
            pass
        self.agent_turn_job_queue.put(job_id)
        return {"job": self._public_agent_turn_job(job, include_payload=False)}

    def _adapter_base_log(self, normalized: dict[str, Any], should_wake: dict[str, Any]) -> dict[str, Any]:
        access = dict(should_wake.get("access") or {}) if isinstance(should_wake.get("access"), dict) else {}
        return {
            "adapter": normalized.get("adapter"),
            "message_type": normalized.get("message_type"),
            "conversation_id": normalized.get("conversation_id"),
            "target_label": normalized.get("target_label"),
            "group_id": normalized.get("group_id"),
            "user_id": normalized.get("user_id"),
            "message_id": normalized.get("message_id"),
            "text": normalized.get("text"),
            "attachment_count": len(normalized.get("attachments") if isinstance(normalized.get("attachments"), list) else []),
            "mentions": list(normalized.get("mentions") or [])[:8],
            "access_allowed": bool(access.get("allowed", True)),
            "access_reason": access.get("reason", ""),
            "should_wake": bool(should_wake.get("should_wake")),
            "ap_gate": bool(should_wake.get("ap_gate")),
            "continuity_gate": bool(should_wake.get("continuity_gate")),
            "wake_reason": should_wake.get("reason"),
            "event_payload": normalized,
            "reply_target": normalized.get("reply_target"),
        }

    def _queue_group_continuity_gate_job(self, normalized: dict[str, Any], should_wake: dict[str, Any], base_log: dict[str, Any]) -> dict[str, Any]:
        self._ensure_group_continuity_gate_worker()
        now = int(time.time() * 1000)
        with self.group_continuity_gate_jobs_lock:
            job_id = f"group_continuity_gate_{now}_{len(self.group_continuity_gate_jobs) + 1}"
            job = {
                "job_id": job_id,
                "status": "queued",
                "stage": "queued",
                "stage_label": "连续窗口门控排队中",
                "created_at_ms": now,
                "updated_at_ms": now,
                "finished_at_ms": 0,
                "normalized": copy.deepcopy(normalized),
                "should_wake": copy.deepcopy(should_wake),
                "base_log": copy.deepcopy(base_log),
                "gate": {},
                "window": {},
                "queued_turn": {},
                "error": "",
            }
            self.group_continuity_gate_jobs[job_id] = job
            if len(self.group_continuity_gate_jobs) > 120:
                rows = sorted(
                    self.group_continuity_gate_jobs.values(),
                    key=lambda item: int(item.get("updated_at_ms", item.get("created_at_ms", 0)) or 0),
                    reverse=True,
                )
                keep_ids = {str(item.get("job_id") or "") for item in rows[:120]}
                for existing_id in list(self.group_continuity_gate_jobs.keys()):
                    if existing_id not in keep_ids:
                        self.group_continuity_gate_jobs.pop(existing_id, None)
        self.group_continuity_gate_queue.put(job_id)
        self.agent_runtime.record_adapter_log(
            {
                "event": "adapter_message_group_continuity_gate_queued",
                "level": "info",
                "handled": True,
                "gate_job_id": job_id,
                **base_log,
            }
        )
        return {"job_id": job_id, "status": "queued"}

    def _group_continuity_gate_worker_loop(self) -> None:
        while not self.group_continuity_gate_stop.is_set():
            try:
                job_id = self.group_continuity_gate_queue.get(timeout=0.3)
            except queue.Empty:
                continue
            if not job_id:
                self.group_continuity_gate_queue.task_done()
                continue
            with self.group_continuity_gate_jobs_lock:
                job = self.group_continuity_gate_jobs.get(job_id)
                if not isinstance(job, dict):
                    self.group_continuity_gate_queue.task_done()
                    continue
                job["status"] = "running"
                job["stage"] = "checking"
                job["stage_label"] = "连续窗口门控判断中"
                job["started_at_ms"] = int(time.time() * 1000)
                job["updated_at_ms"] = job["started_at_ms"]
                normalized = copy.deepcopy(job.get("normalized") if isinstance(job.get("normalized"), dict) else {})
                should_wake = copy.deepcopy(job.get("should_wake") if isinstance(job.get("should_wake"), dict) else {})
                base_log = copy.deepcopy(job.get("base_log") if isinstance(job.get("base_log"), dict) else {})
            try:
                self.agent_runtime.record_adapter_log({"event": "adapter_message_group_continuity_gate", "level": "info", "handled": True, "gate_job_id": job_id, **base_log})
                gate = self.agent_runtime._group_continuity_gate(normalized)
                window = self.agent_runtime._consume_group_continuity_gate_result(normalized, gate)
                threshold = float(getattr(self.agent_runtime.config, "group_continuity_gate_min_confidence", 0.62) or 0.62)
                passed = bool(gate.get("should_pass")) and float(gate.get("confidence", 0.0) or 0.0) >= threshold
                self.agent_runtime.record_adapter_log(
                    {
                        "event": "adapter_message_group_continuity_passed" if passed else "adapter_message_group_continuity_rejected",
                        "level": "info",
                        "handled": bool(passed),
                        "gate_job_id": job_id,
                        "group_continuity_gate": gate,
                        "group_continuity_window": window,
                        **base_log,
                    }
                )
                queued_turn: dict[str, Any] = {}
                if not passed:
                    if int(window.get("remaining", 0) or 0) <= 0:
                        self.agent_runtime.record_adapter_log({"event": "adapter_message_group_continuity_closed", "level": "info", "handled": True, "gate_job_id": job_id, "group_continuity_window": window, **base_log})
                    status = "rejected"
                    stage_label = "连续窗口门控拒绝"
                else:
                    passed_log = {**base_log, "should_wake": True, "wake_reason": "group_continuity_gate_pass", "group_continuity_gate": gate}
                    self.agent_runtime.record_adapter_log({"event": "adapter_message_wake", "level": "info", "handled": True, "gate_job_id": job_id, **passed_log})
                    opened = self.agent_runtime._activate_group_continuity_window(
                        normalized,
                        reason="group_continuity_gate_pass",
                        gate_result=gate,
                    )
                    if opened:
                        self.agent_runtime.record_adapter_log({"event": "adapter_message_group_continuity_window_opened", "level": "info", "handled": True, "gate_job_id": job_id, "group_continuity_window": opened, **passed_log})
                    message_payload = self.agent_runtime._adapter_message_payload(normalized)
                    message_payload["_group_continuity_gate"] = gate
                    try:
                        visible_message = self.agent_runtime._append_visible_adapter_message(
                            normalized,
                            source=str(normalized.get("adapter") or "napcat_qq"),
                        )
                        if isinstance(visible_message, dict):
                            message_payload["_visible_user_message"] = visible_message
                            message_payload["_message_id"] = visible_message.get("id") or message_payload.get("_message_id")
                            message_payload["_skip_user_message_append"] = True
                    except Exception:
                        pass
                    queued_turn = self.submit_agent_turn(message_payload).get("job") or {}
                    status = "passed"
                    stage_label = "连续窗口门控通过，已插入主对话"
                with self.group_continuity_gate_jobs_lock:
                    live_job = self.group_continuity_gate_jobs.get(job_id)
                    if isinstance(live_job, dict):
                        live_job.update(
                            {
                                "status": status,
                                "stage": status,
                                "stage_label": stage_label,
                                "gate": gate,
                                "window": window,
                                "queued_turn": queued_turn,
                                "finished_at_ms": int(time.time() * 1000),
                                "updated_at_ms": int(time.time() * 1000),
                            }
                        )
            except Exception as exc:
                error = str(exc)
                with self.group_continuity_gate_jobs_lock:
                    live_job = self.group_continuity_gate_jobs.get(job_id)
                    if isinstance(live_job, dict):
                        live_job.update(
                            {
                                "status": "failed",
                                "stage": "failed",
                                "stage_label": "连续窗口门控失败",
                                "error": error,
                                "finished_at_ms": int(time.time() * 1000),
                                "updated_at_ms": int(time.time() * 1000),
                            }
                        )
                self.agent_runtime.record_adapter_log({"event": "adapter_message_group_continuity_error", "level": "error", "handled": False, "gate_job_id": job_id, "error": error, **base_log})
            finally:
                self.group_continuity_gate_queue.task_done()

    def submit_adapter_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = self.agent_runtime._normalize_adapter_event(payload)
        self.agent_runtime._remember_adapter_group_history(normalized, gate_stage="received")
        should_wake = self.agent_runtime.should_wake(normalized)
        access = dict(should_wake.get("access") or {}) if isinstance(should_wake.get("access"), dict) else {}
        base_log = self._adapter_base_log(normalized, should_wake)
        self.agent_runtime.record_adapter_log({"event": "adapter_message_received", "level": "info", **base_log})
        self.agent_runtime.record_event(
            {
                "event": "adapter_event",
                "adapter": normalized.get("adapter"),
                "message_type": normalized.get("message_type"),
                "should_wake": bool(should_wake.get("should_wake")),
                "reason": should_wake.get("reason"),
                "text": str(normalized.get("text") or "")[:180],
            }
        )
        if not should_wake.get("should_wake"):
            if should_wake.get("continuity_gate"):
                gate_job = self._queue_group_continuity_gate_job(normalized, should_wake, base_log)
                return {"handled": True, "queued": True, "continuity_gate": True, "gate_job": gate_job, "wake": should_wake, "event": normalized, "status": self.agent_runtime.status(compact=True)}
            if should_wake.get("ap_gate"):
                with self.app_lock:
                    apply_experiment_default_app_overrides(self.app, source="agent_api_adapter_ap_gate")
                    return self.agent_runtime._ingest_group_all_ap_gate(normalized, should_wake)
            if not should_wake.get("should_wake"):
                self.agent_runtime.record_adapter_log(
                    {
                        "event": "adapter_message_filtered",
                        "level": "warn" if not access.get("allowed", True) else "info",
                        "handled": False,
                        **base_log,
                    }
                )
                return {"handled": False, "wake": should_wake, "event": normalized, "status": self.agent_runtime.status()}
        self.agent_runtime.record_adapter_log({"event": "adapter_message_wake", "level": "info", "handled": True, **base_log})
        if str(normalized.get("message_type") or "").lower() == "group":
            window = self.agent_runtime._activate_group_continuity_window(
                normalized,
                reason=str(should_wake.get("reason") or "group_wake"),
                gate_result=should_wake.get("continuity_gate_result") if isinstance(should_wake.get("continuity_gate_result"), dict) else None,
            )
            if window:
                self.agent_runtime.record_adapter_log({"event": "adapter_message_group_continuity_window_opened", "level": "info", "handled": True, "group_continuity_window": window, **base_log})
        message_payload = self.agent_runtime._adapter_message_payload(normalized)
        if should_wake.get("continuity_gate_result"):
            message_payload["_group_continuity_gate"] = should_wake.get("continuity_gate_result")
        try:
            visible_message = self.agent_runtime._append_visible_adapter_message(
                normalized,
                source=str(normalized.get("adapter") or "napcat_qq"),
            )
            if isinstance(visible_message, dict):
                message_payload["_visible_user_message"] = visible_message
                message_payload["_message_id"] = visible_message.get("id") or message_payload.get("_message_id")
                message_payload["_skip_user_message_append"] = True
        except Exception:
            pass
        queued = self.submit_agent_turn(message_payload)
        return {"handled": True, "queued": True, "wake": should_wake, "event": normalized, "job": queued.get("job")}

    def _update_agent_turn_job(self, job_id: str, updates: dict[str, Any]) -> None:
        if not isinstance(updates, dict):
            return
        with self.agent_turn_jobs_lock:
            job = self.agent_turn_jobs.get(job_id)
            if not isinstance(job, dict):
                return
            absorbed_update = updates.get("absorbed_messages")
            if not isinstance(absorbed_update, list):
                absorbed_update = updates.get("external_messages")
            if isinstance(absorbed_update, list):
                absorbed = [item for item in list(job.get("absorbed_messages") or []) if isinstance(item, dict)]
                initial_message = job.get("initial_user_message") or job.get("user_message")
                if isinstance(initial_message, dict) and initial_message.get("id"):
                    initial_id = str(initial_message.get("id") or "")
                    if all(str(item.get("id") or "") != initial_id for item in absorbed):
                        absorbed.insert(0, initial_message)
                seen = {str(item.get("id") or "") for item in absorbed}
                for item in absorbed_update:
                    if not isinstance(item, dict):
                        continue
                    item_id = str(item.get("id") or "")
                    if item_id and item_id in seen:
                        continue
                    absorbed.append(item)
                    if item_id:
                        seen.add(item_id)
                job["absorbed_messages"] = absorbed[-12:]
                job["visible_user_messages"] = absorbed[-12:]
            thought = updates.get("thought")
            if isinstance(thought, dict) and thought.get("id"):
                thoughts = [item for item in list(job.get("thoughts") or []) if isinstance(item, dict)]
                if all(str(item.get("id") or "") != str(thought.get("id") or "") for item in thoughts):
                    thoughts.insert(0, thought)
                job["thoughts"] = thoughts[:12]
            reply = updates.get("reply_message")
            if isinstance(reply, dict) and reply.get("id"):
                replies = [item for item in list(job.get("replies") or []) if isinstance(item, dict)]
                if all(str(item.get("id") or "") != str(reply.get("id") or "") for item in replies):
                    replies.append(reply)
                job["replies"] = replies[-8:]
            reply_messages = updates.get("reply_messages")
            if isinstance(reply_messages, list):
                replies = [item for item in list(job.get("replies") or []) if isinstance(item, dict)]
                seen_reply_ids = {str(item.get("id") or "") for item in replies if str(item.get("id") or "")}
                for item in reply_messages:
                    if not isinstance(item, dict):
                        continue
                    item_id = str(item.get("id") or "")
                    if item_id and item_id in seen_reply_ids:
                        continue
                    replies.append(item)
                    if item_id:
                        seen_reply_ids.add(item_id)
                job["replies"] = replies[-8:]
                job["reply_messages"] = replies[-8:]
            previous_stage = str(job.get("stage") or "")
            previous_stage_label = str(job.get("stage_label") or "")
            stop_locked = bool(job.get("cancel_requested")) and previous_stage in {"stopping", "operator_stopped"}
            job.update(updates)
            if stop_locked and str(job.get("status") or "") == "running":
                incoming_stage = str(updates.get("stage") or "")
                if incoming_stage not in {"operator_stopped", "completed", "cancelled", "failed"}:
                    job["stage"] = previous_stage
                    job["stage_label"] = previous_stage_label or "正在停止思考"
            try:
                job["pending_external_input_count"] = int(self.agent_runtime.pending_external_input_count())
            except Exception:
                pass
            job["updated_at_ms"] = int(updates.get("updated_at_ms", time.time() * 1000) or int(time.time() * 1000))
            stage = updates.get("stage")
            if stage and not updates.get("stage_label"):
                job["stage_label"] = self._job_stage_label(stage)
            if stop_locked and str(job.get("status") or "") == "running" and str(job.get("stage") or "") == "stopping":
                job["stage_label"] = "正在停止思考"
            if str(job.get("status") or "") in {"completed", "cancelled", "failed"} and not job.get("finished_at_ms"):
                job["finished_at_ms"] = job["updated_at_ms"]

    def agent_turn_jobs_snapshot(self, *, job_id: str = "", include_payload: bool = False, limit: int = 20) -> dict[str, Any]:
        with self.agent_turn_jobs_lock:
            if job_id:
                job = self.agent_turn_jobs.get(job_id)
                if not isinstance(job, dict) or bool(job.get("hidden_after_clear")):
                    raise ValueError(f"job not found: {job_id}")
                return {"job": self._public_agent_turn_job(job, include_payload=include_payload)}
            jobs = [
                self._public_agent_turn_job(job, include_payload=False)
                for job in self.agent_turn_jobs.values()
                if isinstance(job, dict) and not bool(job.get("hidden_after_clear"))
            ]
        jobs.sort(key=lambda item: int(item.get("updated_at_ms", item.get("created_at_ms", 0)) or 0), reverse=True)
        active = [job for job in jobs if str(job.get("status") or "") in {"queued", "running"}]
        return {"jobs": jobs[: max(1, min(120, int(limit or 20)))], "active_jobs": active[:8]}

    def request_stop_agent_turn(self, *, job_id: str = "", reason: str = "operator_stop") -> dict[str, Any]:
        now = int(time.time() * 1000)
        reason = str(reason or "operator_stop")[:160]
        background_was_running = False
        try:
            background_was_running = bool(self.agent_background_status().get("running"))
        except Exception:
            background_was_running = False
        background_result: dict[str, Any] = {}
        with self.agent_turn_jobs_lock:
            target: dict[str, Any] | None = None
            if job_id:
                item = self.agent_turn_jobs.get(job_id)
                if isinstance(item, dict):
                    target = item
            if target is None:
                active = [
                    item
                    for item in self.agent_turn_jobs.values()
                    if isinstance(item, dict) and str(item.get("status") or "") in {"queued", "running"}
                ]
                active.sort(key=lambda item: int(item.get("updated_at_ms", item.get("created_at_ms", 0)) or 0), reverse=True)
                target = active[0] if active else None
            if target is None:
                if background_was_running:
                    try:
                        background_result = self.stop_agent_background()
                    except Exception as exc:
                        background_result = {"ok": False, "error": str(exc)}
                    try:
                        self.agent_runtime.record_event({"event": "background_stop_requested_from_turn_panel", "reason": reason})
                    except Exception:
                        pass
                    return {"ok": True, "reason": "background_stop_requested", "job": {}, "background": background_result}
                return {"ok": False, "reason": "no_active_agent_turn", "job": {}, "background": {}}
            target["cancel_requested"] = True
            target["stop_reason"] = reason
            if str(target.get("status") or "") == "queued":
                target["status"] = "cancelled"
                target["stage"] = "operator_stopped"
                target["stage_label"] = "已手动停止，未开始本轮"
                target["finished_at_ms"] = now
            else:
                target["stage"] = "stopping"
                target["stage_label"] = "正在停止思考"
            target["updated_at_ms"] = now
            public = self._public_agent_turn_job(target, include_payload=False)
        if background_was_running:
            try:
                background_result = self.stop_agent_background()
            except Exception as exc:
                background_result = {"ok": False, "error": str(exc)}
        try:
            self.agent_runtime.record_event({"event": "turn_job_stop_requested", "job_id": public.get("job_id"), "reason": reason})
        except Exception:
            pass
        return {"ok": True, "job": public, "background": background_result}

    def _has_active_agent_turn_jobs(self) -> bool:
        with self.agent_turn_jobs_lock:
            return any(
                isinstance(item, dict) and str(item.get("status") or "") in {"queued", "running"}
                for item in self.agent_turn_jobs.values()
            )

    def _agent_turn_worker_loop(self) -> None:
        while not self.agent_turn_job_stop.is_set():
            try:
                job_id = self.agent_turn_job_queue.get(timeout=0.3)
            except queue.Empty:
                continue
            if not job_id:
                self.agent_turn_job_queue.task_done()
                continue
            with self.agent_turn_jobs_lock:
                job = self.agent_turn_jobs.get(job_id)
                if not isinstance(job, dict):
                    self.agent_turn_job_queue.task_done()
                    continue
                if bool(job.get("cancel_requested")) or str(job.get("status") or "") not in {"queued", "running"}:
                    now_ms = int(time.time() * 1000)
                    job["status"] = "cancelled"
                    job["stage"] = "operator_stopped"
                    job["stage_label"] = str(job.get("stage_label") or "已手动停止，未开始本轮")
                    job["finished_at_ms"] = job.get("finished_at_ms") or now_ms
                    job["updated_at_ms"] = now_ms
                    self.agent_turn_job_queue.task_done()
                    continue
                job["status"] = "running"
                job["stage"] = "waiting_for_app_lock"
                job["stage_label"] = "等待 AP 主锁"
                job["started_at_ms"] = int(time.time() * 1000)
                job["updated_at_ms"] = job["started_at_ms"]
            job_payload_for_start = dict(job.get("payload") or {})
            adapter_event_for_start = job_payload_for_start.get("adapter_event") if isinstance(job_payload_for_start.get("adapter_event"), dict) else {}
            if str(job_payload_for_start.get("source") or "") == "napcat_qq" or str(adapter_event_for_start.get("adapter") or "") == "napcat_qq":
                self.agent_runtime.record_adapter_log(
                    {
                        "event": "adapter_message_job_started",
                        "level": "info",
                        "handled": True,
                        "job_id": job_id,
                        "adapter": adapter_event_for_start.get("adapter") or "napcat_qq",
                        "message_type": adapter_event_for_start.get("message_type"),
                        "conversation_id": adapter_event_for_start.get("conversation_id"),
                        "target_label": adapter_event_for_start.get("target_label"),
                        "group_id": adapter_event_for_start.get("group_id"),
                        "user_id": adapter_event_for_start.get("user_id"),
                        "message_id": adapter_event_for_start.get("message_id", ""),
                        "text": job_payload_for_start.get("text", ""),
                        "event_payload": adapter_event_for_start,
                        "reply_target": job_payload_for_start.get("reply_target") if isinstance(job_payload_for_start.get("reply_target"), dict) else {},
                    }
                )
            try:
                with self.app_lock:
                    apply_experiment_default_app_overrides(self.app, source="agent_api_message_async")

                def _progress(update: dict[str, Any]) -> None:
                    patch = dict(update or {})
                    patch.setdefault("status", "running")
                    self._update_agent_turn_job(job_id, patch)

                def _should_stop() -> bool:
                    with self.agent_turn_jobs_lock:
                        live_job = self.agent_turn_jobs.get(job_id)
                        return bool(isinstance(live_job, dict) and live_job.get("cancel_requested"))

                job_payload = dict(job.get("payload") or {})
                reply_target = job_payload.get("reply_target") if isinstance(job_payload.get("reply_target"), dict) else {}
                adapter_event = job_payload.get("adapter_event") if isinstance(job_payload.get("adapter_event"), dict) else {}
                should_route_adapter = bool(
                    str(job_payload.get("source") or "") == "napcat_qq"
                    or str(adapter_event.get("adapter") or "") == "napcat_qq"
                    or str(reply_target.get("adapter") or "") == "napcat_qq"
                )
                sent_reply_ids: set[str] = set()
                adapter_replies: list[dict[str, Any]] = []

                def _send_adapter_reply_compat(
                    target: dict[str, Any],
                    reply_text: str,
                    reply_id: str,
                    *,
                    mentions: list[str] | None = None,
                    segments: list[Any] | None = None,
                    attachments: list[dict[str, Any]] | None = None,
                    action_type: str = "reply",
                    sticker_id: str = "",
                ) -> dict[str, Any]:
                    try:
                        return self.agent_runtime.send_adapter_reply(
                            target,
                            reply_text,
                            reply_id=reply_id,
                            mentions=mentions,
                            segments=segments,
                            attachments=attachments,
                            action_type=action_type,
                            sticker_id=sticker_id,
                        )
                    except TypeError as exc:
                        if "reply_id" not in str(exc):
                            raise
                        return self.agent_runtime.send_adapter_reply(target, reply_text)

                def _dispatch_adapter_reply(reply: dict[str, Any]) -> dict[str, Any] | None:
                    if not should_route_adapter or not isinstance(reply, dict):
                        return None
                    reply_id = str(reply.get("id") or "")
                    if reply_id and reply_id in sent_reply_ids:
                        return None
                    reply_text = str(reply.get("text") or "")
                    target = reply.get("reply_target") if isinstance(reply.get("reply_target"), dict) else None
                    if target is None:
                        target = reply_target if isinstance(reply_target, dict) and reply_target else adapter_event
                    target_compact = self.agent_runtime._compact_reply_target(target if isinstance(target, dict) else {})
                    mentions = self.agent_runtime._normalize_mentions(reply.get("mentions"))
                    segments = list(reply.get("segments") if isinstance(reply.get("segments"), list) else [])
                    attachments = [item for item in (reply.get("attachments") if isinstance(reply.get("attachments"), list) else []) if isinstance(item, dict)]
                    action_type = str(reply.get("action_type") or reply.get("type") or "reply")
                    sticker_id = str(reply.get("sticker_id") or "")
                    result_row = _send_adapter_reply_compat(
                        dict(target_compact or target or {}),
                        reply_text,
                        reply_id,
                        mentions=mentions,
                        segments=segments,
                        attachments=attachments,
                        action_type=action_type,
                        sticker_id=sticker_id,
                    )
                    adapter_replies.append(result_row)
                    if reply_id:
                        sent_reply_ids.add(reply_id)
                    self.agent_runtime.record_adapter_log(
                        {
                            "event": "adapter_message_reply_dispatched",
                            "level": "info" if result_row.get("ok") else "warn",
                            "handled": bool(result_row.get("ok")),
                            "outbound": bool(result_row.get("ok")),
                            "outbound_count": 1,
                            "outbound_ok_count": 1 if result_row.get("ok") else 0,
                            "outbound_error_count": 0 if result_row.get("ok") else 1,
                            "reply_count": 1,
                            "job_id": job_id,
                            "reply_id": reply_id,
                            "adapter": target_compact.get("adapter") or adapter_event.get("adapter") or reply_target.get("adapter") or "napcat_qq",
                            "message_type": target_compact.get("message_type") or adapter_event.get("message_type") or reply_target.get("message_type"),
                            "conversation_id": target_compact.get("conversation_id") or adapter_event.get("conversation_id") or reply_target.get("conversation_id"),
                            "target_label": target_compact.get("target_label") or adapter_event.get("target_label") or reply_target.get("target_label"),
                            "group_id": target_compact.get("group_id") or adapter_event.get("group_id") or reply_target.get("group_id"),
                            "user_id": target_compact.get("user_id") or adapter_event.get("user_id") or reply_target.get("user_id"),
                            "message_id": adapter_event.get("message_id", ""),
                            "napcat_message_id": result_row.get("message_id") or result_row.get("napcat_message_id") or "",
                            "reply_text": reply_text,
                            "action_type": action_type,
                            "mentions": mentions[:8],
                            "attachment_count": len(attachments),
                            "sticker_id": sticker_id,
                            "reply_target": target_compact or target or {},
                            "adapter_reply": result_row,
                        }
                    )
                    return result_row

                try:
                    result = self.agent_runtime.send_message(
                        job_payload,
                        progress=_progress,
                        on_reply=_dispatch_adapter_reply if should_route_adapter else None,
                        should_stop=_should_stop,
                    )
                except TypeError as exc:
                    if "on_reply" not in str(exc):
                        raise
                    result = self.agent_runtime.send_message(
                        job_payload,
                        progress=_progress,
                        should_stop=_should_stop,
                    )
                if should_route_adapter:
                    for reply in list(result.get("replies") if isinstance(result.get("replies"), list) else [])[:8]:
                        if not isinstance(reply, dict):
                            continue
                        _dispatch_adapter_reply(reply)
                    result["adapter_replies"] = adapter_replies
                    result["adapter_reply"] = adapter_replies[0] if adapter_replies else None
                    outbound_ok_count = sum(1 for item in adapter_replies if isinstance(item, dict) and item.get("ok"))
                    outbound_error_count = sum(1 for item in adapter_replies if isinstance(item, dict) and not item.get("ok"))
                    if adapter_replies and outbound_ok_count:
                        adapter_log_event = "adapter_message_replied"
                        adapter_log_level = "info"
                    elif adapter_replies:
                        adapter_log_event = "adapter_message_reply_failed"
                        adapter_log_level = "warn"
                    else:
                        adapter_log_event = "adapter_message_passed"
                        adapter_log_level = "info"
                    self.agent_runtime.record_adapter_log(
                        {
                            "event": adapter_log_event,
                            "level": adapter_log_level,
                            "handled": True,
                            "reply_count": len(result.get("replies") if isinstance(result.get("replies"), list) else []),
                            "outbound_count": len(adapter_replies),
                            "outbound_ok_count": outbound_ok_count,
                            "outbound_error_count": outbound_error_count,
                            "adapter": adapter_event.get("adapter") or reply_target.get("adapter") or "napcat_qq",
                            "message_type": adapter_event.get("message_type") or reply_target.get("message_type"),
                            "conversation_id": adapter_event.get("conversation_id") or reply_target.get("conversation_id"),
                            "target_label": adapter_event.get("target_label") or reply_target.get("target_label"),
                            "group_id": adapter_event.get("group_id") or reply_target.get("group_id"),
                            "user_id": adapter_event.get("user_id") or reply_target.get("user_id"),
                            "message_id": adapter_event.get("message_id", ""),
                            "text": job_payload.get("text", ""),
                            "event_payload": adapter_event,
                            "reply_target": reply_target or adapter_event,
                            "adapter_replies": adapter_replies,
                        }
                    )
                turn = result.get("turn") if isinstance(result.get("turn"), dict) else {}
                final_patch = {
                    "status": "completed",
                    "stage": "completed",
                    "stage_label": "本轮完成",
                    "finished_at_ms": int(time.time() * 1000),
                    "turn_id": str(turn.get("id") or ""),
                    "turn": turn,
                    "thoughts": self.agent_runtime._compact_thoughts(result.get("thoughts") if isinstance(result.get("thoughts"), list) else []),
                    "replies": self.agent_runtime._compact_messages(result.get("replies") if isinstance(result.get("replies"), list) else []),
                    "decision": str(turn.get("decision") or ""),
                    "thought_count": len(result.get("thoughts") if isinstance(result.get("thoughts"), list) else []),
                    "reply_count": len(result.get("replies") if isinstance(result.get("replies"), list) else []),
                    "ap_tick_count": int(turn.get("ap_tick_count", len(result.get("ap_reports") if isinstance(result.get("ap_reports"), list) else [])) or 0),
                    "bridges": list(result.get("bridges") or [])[:12],
                    "bridge_teacher_feedback": list(result.get("bridge_teacher_feedback") or [])[:12],
                    "adapter_replies": adapter_replies,
                    "ap_packet": self.agent_runtime._compact_packet_for_status(dict(result.get("ap_packet") or {})),
                    "recent_reports": list(result.get("ap_reports") or [])[-8:],
                    "result_status": dict(self.agent_runtime._compact_status()),
                }
                with self.agent_turn_jobs_lock:
                    live_job = self.agent_turn_jobs.get(job_id)
                    was_cancelled = bool(isinstance(live_job, dict) and live_job.get("cancel_requested"))
                if was_cancelled:
                    final_patch.update(
                        {
                            "status": "cancelled",
                            "stage": "operator_stopped",
                            "stage_label": "已手动停止，进入休眠",
                            "decision": "sleep",
                        }
                    )
                self._update_agent_turn_job(job_id, final_patch)
                try:
                    self.agent_runtime.record_event({"event": "turn_job_completed", "job_id": job_id, "turn_id": final_patch["turn_id"], "decision": final_patch["decision"]})
                except Exception:
                    pass
            except Exception as exc:
                error = str(exc)
                self._update_agent_turn_job(
                    job_id,
                    {
                        "status": "failed",
                        "stage": "failed",
                        "stage_label": "本轮失败",
                        "error": error,
                        "finished_at_ms": int(time.time() * 1000),
                    },
                )
                try:
                    self.agent_runtime.record_event({"event": "turn_job_failed", "job_id": job_id, "error": error})
                except Exception:
                    pass
            finally:
                self._clear_agent_foreground_priority_if_idle()
                self.agent_turn_job_queue.task_done()

    def agent_background_status(self) -> dict[str, Any]:
        with self.agent_background_lock:
            state = dict(self.agent_background_state)
            state["thread_alive"] = bool(self.agent_background_thread and self.agent_background_thread.is_alive())
            state["interval_ms"] = int(getattr(self.agent_runtime.config, "background_tick_interval_ms", 1200) or 1200)
            state["thought_interval_ticks"] = int(getattr(self.agent_runtime.config, "background_thought_interval_ticks", 1) or 1)
            state["reinforced_agency_interval_ticks"] = int(getattr(self.agent_runtime.config, "reinforced_agency_interval_ticks", 30) or 30)
            state["agency_trigger_window_ticks"] = int(getattr(self.agent_runtime.config, "agency_trigger_window_ticks", 12) or 12)
            state["agency_trigger_threshold"] = float(getattr(self.agent_runtime.config, "agency_trigger_threshold", 0.92) or 0.0)
            state["agency_teacher_gate_enabled"] = bool(getattr(self.agent_runtime.config, "agency_teacher_gate_enabled", True))
            state["sleep_mode"] = str(getattr(self.agent_runtime.config, "sleep_mode", "full_silent") or "full_silent")
            state["wake_drive_threshold"] = float(getattr(self.agent_runtime.config, "wake_drive_threshold", 0.68) or 0.0)
            state["background_save_interval_ticks"] = int(getattr(self.agent_runtime.config, "background_save_interval_ticks", 30) or 30)
            state["background_save_interval_ms"] = int(getattr(self.agent_runtime.config, "background_save_interval_ms", 60000) or 60000)
            return state

    def start_agent_background(self) -> dict[str, Any]:
        with self.agent_background_lock:
            if self.agent_background_thread and self.agent_background_thread.is_alive():
                return self.agent_background_status()
            self.agent_background_stop.clear()
            self.agent_background_state.update(
                {
                    "running": True,
                    "started_at_ms": int(time.time() * 1000),
                    "stopped_at_ms": 0,
                    "last_error": "",
                    "thought_check_count": 0,
                }
            )
            self.agent_background_thread = threading.Thread(target=self._agent_background_loop, daemon=True, name="pa-agent-background")
            self.agent_background_thread.start()
            return self.agent_background_status()

    def stop_agent_background(self) -> dict[str, Any]:
        self.agent_background_stop.set()
        with self.agent_background_lock:
            self.agent_background_state["running"] = False
            self.agent_background_state["last_stage"] = "stopping"
            self.agent_background_state["last_stage_label"] = "正在停止后台思考"
            self.agent_background_state["stopped_at_ms"] = int(time.time() * 1000)
        return self.agent_background_status()

    def run_agent_background_step(self) -> dict[str, Any]:
        result = self._agent_background_step()
        return {"step": result, "background": self.agent_background_status()}

    def _background_internal_think_progress(self, update: dict[str, Any]) -> None:
        patch = dict(update or {})
        stage = str(patch.get("stage") or "background_internal_think")
        stage_label = str(patch.get("stage_label") or self._job_stage_label(stage) or "后台内部思考中")
        now_ms = int(time.time() * 1000)
        result = {
            "ok": True,
            "mode": str(getattr(self.agent_runtime.config, "sleep_mode", "full_silent") or "full_silent"),
            "triggered": True,
            "reason": "background_internal_think_running",
            "stage": stage,
            "stage_label": stage_label,
            "internal_mode": True,
            "internal_think_progress": patch,
            "thought_result": None,
            "ap_packet": patch.get("ap_packet") if isinstance(patch.get("ap_packet"), dict) else {},
            "recent_reports": list(patch.get("recent_reports") or [])[-8:],
            "bridges": list(patch.get("bridges") or [])[-12:],
            "teacher_gate": {"mode": "background_internal_think", "reason": "running"},
        }
        for key in (
            "turn_id",
            "decision",
            "current_thought_index",
            "thought_budget",
            "thought_soft_window_index",
            "thought_soft_window_limit",
            "thought_hard_step_limit",
            "thought_reset_count",
            "thought_reset_limit",
            "thought_count",
            "reply_count",
            "current_thought_text",
            "current_reply_text",
            "why",
            "llm_status",
            "llm_wait_tick_count",
            "llm_wait_tick_total",
            "pre_tick_index",
            "pre_tick_total",
            "ap_tick_count",
            "tool_calls",
            "tool_results",
        ):
            if key in patch:
                result[key] = patch.get(key)
        with self.agent_background_lock:
            self.agent_background_state["last_step_at_ms"] = now_ms
            self.agent_background_state["last_result"] = result
            self.agent_background_state["last_stage"] = stage
            self.agent_background_state["last_stage_label"] = stage_label
            self.agent_background_state["last_error"] = ""

    def launch_napcat(self) -> dict[str, Any]:
        repo = Path(__file__).resolve().parents[2] / "NapCatQQ"
        shell_loader = repo / "packages" / "napcat-shell-loader"
        release_candidates = [
            shell_loader / "launcher-win10.bat",
            shell_loader / "launcher.bat",
            shell_loader / "launcher-win10-user.bat",
            shell_loader / "launcher-user.bat",
        ]
        develop_dir = repo / "packages" / "napcat-develop"
        shell_dist_main = repo / "packages" / "napcat-shell" / "dist" / "napcat.mjs"
        shell_static_index = repo / "packages" / "napcat-shell" / "dist" / "static" / "index.html"
        webui_dist_index = repo / "packages" / "napcat-webui-frontend" / "dist" / "index.html"
        loader_main = shell_loader / "napcat.mjs"
        repo_root = Path(__file__).resolve().parents[1]
        source_launcher_candidates = [
            repo_root / "start-napcat-pa.bat",
            repo.parent / "start-napcat-pa.bat",
        ]
        source_launcher = next((item for item in source_launcher_candidates if item.exists()), source_launcher_candidates[0])
        release_launcher = next((item for item in release_candidates if item.exists()), release_candidates[0])
        release_ready = bool(release_launcher.exists() and loader_main.exists())
        source_ready = bool(source_launcher.exists() and (develop_dir / "loadNapCat.cjs").exists())
        if release_ready:
            launch_bat = release_launcher
            launch_cwd = launch_bat.parent
            launch_mode = "shell-loader-release"
            launch_note = "NapCat release shell-loader 入口完整，使用官方 shell-loader 启动。"
        elif source_ready:
            launch_bat = source_launcher
            launch_cwd = repo.parent
            source_dist_ready = bool(shell_dist_main.exists() and shell_static_index.exists() and webui_dist_index.exists())
            launch_mode = "source-dev-built" if source_dist_ready else "source-dev-prepare"
            launch_note = (
                "检测到当前 NapCatQQ 是源码工作区，shell-loader 缺少 napcat.mjs。"
                "已改用 PA 源码启动脚本；首次运行会先安装依赖并构建 WebUI 与 packages\\napcat-shell\\dist。"
            )
        elif release_launcher.exists() and not loader_main.exists():
            raise ValueError(
                "NapCat shell-loader exists but napcat.mjs is missing. "
                f"Expected {loader_main}. This looks like a source checkout; "
                f"please create {source_launcher} or build NapCat shell first."
            )
        else:
            raise ValueError(f"NapCat launcher not found. Checked {release_launcher} and {source_launcher}")

        def port_open(host: str, port: int, timeout: float = 0.35) -> bool:
            try:
                with socket.create_connection((host, int(port)), timeout=timeout):
                    return True
            except OSError:
                return False

        webui = repo / "packages" / "napcat-webui-backend" / "webui.json"
        webui_port = 6099
        webui_token = ""
        try:
            payload = json.loads(webui.read_text(encoding="utf-8"))
            webui_port = int(payload.get("port", webui_port) or webui_port)
            webui_token = str(payload.get("token") or "")
        except Exception:
            pass
        http_api_host = "127.0.0.1"
        http_api_port = 3000
        webhook_host = str(getattr(self, "web_host", "127.0.0.1") or "127.0.0.1")
        if webhook_host in {"0.0.0.0", "::"}:
            webhook_host = "127.0.0.1"
        webhook_port = int(getattr(self, "web_port", 8765) or 8765)
        webhook_url = f"http://{webhook_host}:{webhook_port}/api/agent/napcat/event"
        onebot_config = repo / "packages" / "napcat-develop" / "config" / "onebot11.json"
        onebot_config_paths = [
            onebot_config,
            repo / "packages" / "napcat-develop" / "dist" / "config" / "onebot11.json",
            repo / "packages" / "napcat-shell" / "dist" / "config" / "onebot11.json",
            shell_loader / "config" / "onebot11.json",
        ]
        onebot_config_updated = False
        onebot_config_error = ""
        patched_config_paths: list[str] = []

        def patch_onebot_config(config_path: Path, *, create: bool) -> bool:
            nonlocal onebot_config_updated
            if not create and not config_path.exists():
                return False
            config_payload = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {"network": {}}
            network = config_payload.setdefault("network", {})
            servers = network.setdefault("httpServers", [])
            if not isinstance(servers, list):
                servers = []
                network["httpServers"] = servers
            server = next((item for item in servers if isinstance(item, dict) and str(item.get("name") or "").lower() == "http"), None)
            if server is None:
                server = {}
                servers.append(server)
            server_before = json.dumps(server, ensure_ascii=False, sort_keys=True)
            server.update(
                {
                    "enable": True,
                    "name": server.get("name") or "HTTP",
                    "host": http_api_host,
                    "port": http_api_port,
                    "enableCors": True,
                    "enableWebsocket": bool(server.get("enableWebsocket", False)),
                    "messagePostFormat": "array",
                    "token": str(server.get("token") or ""),
                    "debug": bool(server.get("debug", False)),
                }
            )
            clients = network.setdefault("httpClients", [])
            if not isinstance(clients, list):
                clients = []
                network["httpClients"] = clients
            client = next((item for item in clients if isinstance(item, dict) and str(item.get("name") or "") == "PA Agent Webhook"), None)
            if client is None:
                client = {}
                clients.append(client)
            client_before = json.dumps(client, ensure_ascii=False, sort_keys=True)
            client.update(
                {
                    "enable": True,
                    "name": "PA Agent Webhook",
                    "url": webhook_url,
                    "messagePostFormat": "array",
                    "reportSelfMessage": False,
                    "token": str(client.get("token") or ""),
                    "debug": bool(client.get("debug", False)),
                }
            )
            server_after = json.dumps(server, ensure_ascii=False, sort_keys=True)
            client_after = json.dumps(client, ensure_ascii=False, sort_keys=True)
            if server_before != server_after or client_before != client_after or not config_path.exists():
                config_path.parent.mkdir(parents=True, exist_ok=True)
                if config_path.exists():
                    backup = config_path.with_suffix(config_path.suffix + ".pa-agent.bak")
                    if not backup.exists():
                        backup.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
                config_path.write_text(json.dumps(config_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                onebot_config_updated = True
            patched_config_paths.append(str(config_path))
            return True

        try:
            seen_config_paths: set[str] = set()
            for path_item in onebot_config_paths:
                key = str(path_item.resolve()) if path_item.exists() else str(path_item)
                if key in seen_config_paths:
                    continue
                seen_config_paths.add(key)
                patch_onebot_config(path_item, create=(path_item == onebot_config))
        except Exception as exc:
            onebot_config_error = str(exc)
        ports_before = {
            "webui": port_open("127.0.0.1", webui_port),
            "http_api": port_open(http_api_host, http_api_port),
        }
        subprocess.Popen(
            ["cmd.exe", "/c", str(launch_bat)],
            cwd=str(launch_cwd),
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
        time.sleep(0.7)
        ports_after = {
            "webui": port_open("127.0.0.1", webui_port),
            "http_api": port_open(http_api_host, http_api_port),
        }
        webui_url = f"http://127.0.0.1:{webui_port}/webui/"
        try:
            webbrowser.open(webui_url)
        except Exception:
            pass
        return {
            "ok": True,
            "launched": True,
            "launcher": str(launch_bat),
            "cwd": str(launch_cwd),
            "webui_url": webui_url,
            "webui_token": webui_token,
            "http_api_url": f"http://{http_api_host}:{http_api_port}",
            "webhook_url": webhook_url,
            "onebot_config": str(onebot_config),
            "onebot_config_paths": patched_config_paths,
            "onebot_config_updated": onebot_config_updated,
            "onebot_config_error": onebot_config_error,
            "ports_before": ports_before,
            "ports_after": ports_after,
            "launch_mode": launch_mode,
            "launcher_checks": {
                "release_launcher": str(release_launcher),
                "release_loader_main": str(loader_main),
                "release_ready": release_ready,
                    "source_launcher": str(source_launcher),
                    "source_launcher_candidates": [str(item) for item in source_launcher_candidates],
                "source_shell_dist_main": str(shell_dist_main),
                "source_shell_static_index": str(shell_static_index),
                "source_webui_dist_index": str(webui_dist_index),
                "source_dist_ready": bool(shell_dist_main.exists() and shell_static_index.exists() and webui_dist_index.exists()),
                "source_ready": source_ready,
            },
            "note": (
                f"{launch_note} 已确保 OneBot HTTP API / PA Webhook 配置存在。"
                "若端口仍未亮起，请在弹出的窗口完成首次构建、QQ 登录或查看 NapCat 报错。"
            ),
        }

    def _agent_background_loop(self) -> None:
        while not self.agent_background_stop.is_set():
            result = self._agent_background_step()
            interval_ms = int(getattr(self.agent_runtime.config, "background_tick_interval_ms", 1200) or 1200)
            if result.get("error"):
                interval_ms = max(interval_ms, 3000)
            self.agent_background_stop.wait(max(0.25, min(300.0, interval_ms / 1000.0)))
        with self.agent_background_lock:
            self.agent_background_state["running"] = False
            self.agent_background_state["stopped_at_ms"] = int(time.time() * 1000)

    def _agent_background_step(self) -> dict[str, Any]:
        try:
            def background_stop_requested() -> bool:
                try:
                    return bool(self.agent_background_stop.is_set())
                except Exception:
                    return False

            def background_should_abort() -> bool:
                return background_stop_requested() or foreground_pending()

            def foreground_pending() -> bool:
                return self._agent_foreground_is_pending()

            def paused_result(reason: str) -> dict[str, Any]:
                stage_label = "后台已收到停止信号" if "stop_requested" in reason else "后台让路给前台输入"
                result = {
                    "ok": True,
                    "mode": str(getattr(self.agent_runtime.config, "sleep_mode", "full_silent") or "full_silent"),
                    "triggered": False,
                    "reason": reason,
                    "stage": reason,
                    "stage_label": stage_label,
                    "latency_ms": 0,
                    "foreground_priority": True,
                    "background_thought_interval_ticks": int(getattr(self.agent_runtime.config, "background_thought_interval_ticks", 30) or 30),
                    "reinforced_agency_interval_ticks": int(getattr(self.agent_runtime.config, "reinforced_agency_interval_ticks", 30) or 30),
                }
                with self.agent_background_lock:
                    self.agent_background_state["last_step_at_ms"] = int(time.time() * 1000)
                    self.agent_background_state["last_result"] = result
                    self.agent_background_state["last_stage"] = reason
                    self.agent_background_state["last_stage_label"] = stage_label
                    self.agent_background_state["last_error"] = ""
                return result

            started_ms = int(time.time() * 1000)
            if background_stop_requested():
                return paused_result("background_stop_requested")
            if foreground_pending():
                return paused_result("background_paused_for_foreground_turn")
            locked = self.app_lock.acquire(blocking=False)
            if not locked:
                result = {
                    "ok": True,
                    "mode": str(getattr(self.agent_runtime.config, "sleep_mode", "full_silent") or "full_silent"),
                    "triggered": False,
                    "reason": "background_skipped_app_lock_busy",
                    "stage": "background_skipped_app_lock_busy",
                    "stage_label": "后台等待 AP 主锁",
                    "latency_ms": 0,
                }
                with self.agent_background_lock:
                    self.agent_background_state["last_step_at_ms"] = int(time.time() * 1000)
                    self.agent_background_state["last_result"] = result
                    self.agent_background_state["last_stage"] = result["stage"]
                    self.agent_background_state["last_stage_label"] = result["stage_label"]
                    self.agent_background_state["last_error"] = ""
                return result
            try:
                if background_stop_requested():
                    return paused_result("background_stop_requested_before_tick")
                if foreground_pending():
                    return paused_result("background_paused_after_lock_before_tick")
                apply_experiment_default_app_overrides(self.app, source="agent_background")
                mode = str(getattr(self.agent_runtime.config, "sleep_mode", "full_silent") or "full_silent")
                thought_interval_ticks = max(3, int(getattr(self.agent_runtime.config, "background_thought_interval_ticks", 30) or 30))
                reinforced_interval_ticks = max(5, int(getattr(self.agent_runtime.config, "reinforced_agency_interval_ticks", 30) or 30))
                with self.agent_background_lock:
                    next_step_count = int(self.agent_background_state.get("step_count", 0) or 0) + 1
                should_reinforced_eval = mode == "reinforced_agency" and next_step_count % reinforced_interval_ticks == 0
                if foreground_pending():
                    return paused_result("background_paused_after_lock_for_foreground_turn")
                if mode == "full_silent":
                    report = {}
                else:
                    report = self.app.run_cycle(text=None, labels={"source": "agent_background"})
            finally:
                self.app_lock.release()
            if background_stop_requested():
                return paused_result("background_stop_requested_after_tick")
            if foreground_pending():
                return paused_result("background_paused_after_tick_for_foreground_turn")
            should_think = False
            bridge: dict[str, Any] = {"bridges": [], "bridge_reports": [], "tool_results": [], "teacher_feedback": [], "internal_think_result": None}
            reports = [report] if isinstance(report, dict) and report else []
            drive: dict[str, Any] = {}
            thought_result: dict[str, Any] | None = None
            triggered = False
            teacher_gate: dict[str, Any] = {}
            eval_reason = "background_interval_wait"
            if mode == "full_silent":
                eval_reason = "full_silent"
                packet = {}
            else:
                bridge = self.agent_runtime._bridge_tick_side_effects(
                    report,
                    source="agent_background",
                    allow_internal_think=(mode == "ap_agency"),
                    require_teacher_gate=True,
                    should_abort=background_should_abort,
                    internal_think_progress=self._background_internal_think_progress,
                )
                reports.extend([item for item in bridge.get("bridge_reports", []) if isinstance(item, dict)])
                if background_stop_requested():
                    return paused_result("background_stop_requested_after_bridge")
                if foreground_pending():
                    return paused_result("background_paused_after_bridge_for_foreground_turn")
                packet = self.agent_runtime.build_prompt_packet(reports=reports)
                drive = self.agent_runtime._estimate_wake_drive(packet)
                thought_result = bridge.get("internal_think_result") if isinstance(bridge.get("internal_think_result"), dict) else None
                triggered = bool(thought_result)
                if should_reinforced_eval:
                    teacher_gate = self.agent_runtime._teacher_gate_should_wake(packet=packet, drive=drive, mode=mode)
                    eval_reason = "reinforced_periodic_teacher_gate"
                    if background_stop_requested():
                        return paused_result("background_stop_requested_after_gate")
                    if foreground_pending():
                        return paused_result("background_paused_after_gate_for_foreground_turn")
                    if bool(teacher_gate.get("should_wake")) and float(teacher_gate.get("confidence", 0.0) or 0.0) >= float(getattr(self.agent_runtime.config, "agency_teacher_gate_confidence", 0.62) or 0.62):
                        thought_result = self.agent_runtime._run_internal_think(
                            packet=packet,
                            source="agent_background",
                            reason=str(teacher_gate.get("reason") or eval_reason),
                            progress=self._background_internal_think_progress,
                            should_stop=background_should_abort,
                        )
                        triggered = True
                        eval_reason = "reinforced_periodic_teacher_gate_allow"
                    else:
                        eval_reason = "reinforced_periodic_teacher_gate_reject"
                elif mode == "reinforced_agency":
                    eval_reason = "reinforced_interval_wait"
                elif triggered:
                    eval_reason = "ap_agency_action_teacher_gate_allow"
                elif mode == "ap_agency":
                    eval_reason = "ap_agency_wait_action_trigger"
                self.agent_runtime._remember_snapshot(packet)
                should_save_background = False
                save_reason = "interval_wait"
                save_started_ms = 0
                save_wall_ms = 0
                with self.agent_background_lock:
                    last_save_at_ms = int(self.agent_background_state.get("last_save_at_ms", 0) or 0)
                    last_save_step_count = int(self.agent_background_state.get("last_save_step_count", 0) or 0)
                save_interval_ticks = max(1, int(getattr(self.agent_runtime.config, "background_save_interval_ticks", 30) or 30))
                save_interval_ms = max(1000, int(getattr(self.agent_runtime.config, "background_save_interval_ms", 60000) or 60000))
                if triggered:
                    should_save_background = True
                    save_reason = "triggered_internal_thought"
                elif next_step_count - last_save_step_count >= save_interval_ticks:
                    should_save_background = True
                    save_reason = "tick_interval"
                elif last_save_at_ms > 0 and started_ms - last_save_at_ms >= save_interval_ms:
                    should_save_background = True
                    save_reason = "time_interval"
                if foreground_pending():
                    should_save_background = False
                    save_reason = "foreground_pending_skip"
                if should_save_background:
                    save_started_ms = int(time.time() * 1000)
                    self.agent_runtime.save()
                    save_wall_ms = max(0, int(time.time() * 1000) - save_started_ms)
                    with self.agent_background_lock:
                        self.agent_background_state["last_save_at_ms"] = int(time.time() * 1000)
                        self.agent_background_state["last_save_step_count"] = next_step_count
                        self.agent_background_state["last_save_wall_ms"] = save_wall_ms
            result = {
                "ok": True,
                "mode": mode,
                "triggered": triggered,
                "reason": eval_reason,
                "stage": "background_internal_think" if triggered else eval_reason,
                "stage_label": "后台内部思考已触发" if triggered else "后台主观能动性运行中",
                "background_save": {
                    "saved": bool(locals().get("should_save_background", False)),
                    "reason": locals().get("save_reason", ""),
                    "wall_ms": int(locals().get("save_wall_ms", 0) or 0),
                },
                "drive": drive,
                "report": self.agent_runtime._compact_report_meta(report) if isinstance(report, dict) else {},
                "ap_packet": packet,
                "thought_result": thought_result,
                "latency_ms": max(0, int(time.time() * 1000) - started_ms),
                "background_thought_interval_ticks": thought_interval_ticks,
                "reinforced_agency_interval_ticks": reinforced_interval_ticks,
                "bridges": list(bridge.get("bridges") or []),
                "teacher_gate": teacher_gate or {"mode": "ap_action_gate", "reason": "waiting_for_ap_action_or_reinforced_interval"},
            }
            with self.agent_background_lock:
                self.agent_background_state["step_count"] = int(self.agent_background_state.get("step_count", 0) or 0) + 1
                if should_think or should_reinforced_eval:
                    self.agent_background_state["thought_check_count"] = int(self.agent_background_state.get("thought_check_count", 0) or 0) + 1
                if bool(result.get("triggered")):
                    self.agent_background_state["trigger_count"] = int(self.agent_background_state.get("trigger_count", 0) or 0) + 1
                self.agent_background_state["last_step_at_ms"] = int(time.time() * 1000)
                self.agent_background_state["last_result"] = result
                self.agent_background_state["last_stage"] = result.get("stage", "")
                self.agent_background_state["last_stage_label"] = result.get("stage_label", "")
                self.agent_background_state["last_error"] = ""
            return result
        except Exception as exc:
            error = str(exc)
            with self.agent_background_lock:
                self.agent_background_state["step_count"] = int(self.agent_background_state.get("step_count", 0) or 0) + 1
                self.agent_background_state["last_step_at_ms"] = int(time.time() * 1000)
                self.agent_background_state["last_error"] = error
            try:
                self.agent_runtime.record_event({"event": "background_error", "ok": False, "error": error})
            except Exception:
                pass
            return {"ok": False, "error": error}

    def server_close(self) -> None:
        self.stop_agent_background()
        self.agent_turn_job_stop.set()
        self.group_continuity_gate_stop.set()
        try:
            self.agent_turn_job_queue.put_nowait("")
        except Exception:
            pass
        try:
            self.group_continuity_gate_queue.put_nowait("")
        except Exception:
            pass
        super().server_close()


def _request_server_stop(server: ObservatoryWebServer, *, force_exit: bool = False) -> None:
    """Stop the local web server from an API handler without blocking the response."""
    if force_exit:
        def _force_exit() -> None:
            os._exit(0)

        threading.Timer(0.8, _force_exit).start()

    def _stop() -> None:
        try:
            server.shutdown()
        except Exception:
            pass
        if force_exit:
            time.sleep(0.25)
            os._exit(0)

    threading.Thread(target=_stop, daemon=True).start()


def _schedule_observatory_restart(server: ObservatoryWebServer) -> dict[str, Any]:
    """Launch a detached helper that restarts the web server after this process exits."""
    host = str(getattr(server, "web_host", "127.0.0.1") or "127.0.0.1")
    port = int(getattr(server, "web_port", 8765) or 8765)
    repo_root = Path(__file__).resolve().parents[1]
    python_exe = sys.executable or "python"
    helper_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    helper_code = (
        "import subprocess, sys, time\n"
        "py, cwd, host, port = sys.argv[1:5]\n"
        "time.sleep(1.2)\n"
        "flags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)\n"
        "subprocess.Popen([py, '-m', 'observatory', '--mode', 'web', '--no-browser', '--host', host, '--port', port], cwd=cwd, creationflags=flags)\n"
    )
    subprocess.Popen(
        [python_exe, "-c", helper_code, python_exe, str(repo_root), host, str(port)],
        cwd=str(repo_root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=helper_flags,
        close_fds=True,
    )
    _request_server_stop(server, force_exit=True)
    return {"message": "server restarting", "host": host, "port": port}


def _blank_dataset_meta() -> dict[str, Any]:
    return {
        "dataset_id": "",
        "title": "",
        "description": "",
        "experiment_goal": "",
        "time_basis": "",
        "tick_dt_ms": None,
        "estimated_ticks": None,
        "effective_text_ticks": None,
        "empty_ticks": None,
        "labeled_ticks": None,
        "evaluation_dimensions": [],
        "notes": [],
        "app_config_override": {},
        "app_config_override_keys": [],
        "dataset_kind": "",
    }


def _dataset_fingerprint(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
        return int(stat.st_mtime_ns), int(stat.st_size)
    except OSError:
        return 0, 0


def _load_dataset_meta(path: Path) -> dict[str, Any]:
    meta = _blank_dataset_meta()
    if path.suffix.lower() in {".yaml", ".yml"}:
        raw = exp.io.load_yaml_file(path)  # type: ignore[attr-defined]
        norm = exp.validate_and_normalize_dataset(raw)
        meta.update(exp.dataset_overview(norm))
        meta["dataset_kind"] = "yaml_episode_template"
    elif path.suffix.lower() == ".jsonl":
        summary = exp.summarize_expanded_tick_items(exp.io.iter_jsonl(path))  # type: ignore[attr-defined]
        meta.update(
            {
                "dataset_id": summary.get("dataset_id", "") or path.stem,
                "time_basis": summary.get("time_basis", ""),
                "tick_dt_ms": summary.get("tick_dt_ms", None),
                "estimated_ticks": summary.get("total_ticks", 0),
                "effective_text_ticks": summary.get("effective_text_ticks", 0),
                "empty_ticks": summary.get("empty_ticks", 0),
                "labeled_ticks": summary.get("labeled_ticks", 0),
                "dataset_kind": "jsonl_tick_stream",
            }
        )
    return meta


def _load_dataset_meta_cached(server: ObservatoryWebServer, ref) -> dict[str, Any]:
    meta = _blank_dataset_meta()
    try:
        path = exp.storage.resolve_dataset_file(ref)  # type: ignore[attr-defined]
        path_key = str(path.resolve())
        fingerprint = _dataset_fingerprint(path)
        with server.dataset_catalog_lock:
            cached = server.dataset_catalog_cache.get(path_key)
            if cached and tuple(cached.get("fingerprint", ())) == fingerprint:
                return dict(cached.get("meta", meta))
        loaded = _load_dataset_meta(path)
        with server.dataset_catalog_lock:
            server.dataset_catalog_cache[path_key] = {
                "fingerprint": fingerprint,
                "meta": dict(loaded),
            }
        return loaded
    except Exception:
        return meta


_AUTO_TUNER_STATE_CACHE_TTL_MS = 1500
_AUTO_TUNER_STATE_STALE_MAX_MS = 15000
_AUTO_TUNER_STATE_LOCK_TIMEOUT_SEC = 0.15


def _decorate_auto_tuner_state_payload(payload: dict[str, Any], *, mode: str, refreshed_at_ms: int, now_ms: int) -> dict[str, Any]:
    data = dict(payload or {})
    fetch_meta = dict(data.get("fetch_meta", {})) if isinstance(data.get("fetch_meta"), dict) else {}
    fetch_meta.update(
        {
            "mode": str(mode or "live"),
            "refreshed_at_ms": int(refreshed_at_ms or 0),
            "cache_age_ms": max(0, int(now_ms or 0) - int(refreshed_at_ms or 0)),
        }
    )
    data["fetch_meta"] = fetch_meta
    return data


def _load_auto_tuner_state_cached(server: ObservatoryWebServer) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    cached_payload: dict[str, Any] | None = None
    cached_mode = "live"
    cached_refreshed_at_ms = 0
    with server.auto_tuner_state_lock:
        cached_payload = server.auto_tuner_state_cache.get("payload") if isinstance(server.auto_tuner_state_cache.get("payload"), dict) else None
        cached_mode = str(server.auto_tuner_state_cache.get("mode", "live") or "live")
        cached_refreshed_at_ms = int(server.auto_tuner_state_cache.get("refreshed_at_ms", 0) or 0)
    if cached_payload is not None and max(0, now_ms - cached_refreshed_at_ms) <= _AUTO_TUNER_STATE_CACHE_TTL_MS:
        return _decorate_auto_tuner_state_payload(
            cached_payload,
            mode=cached_mode,
            refreshed_at_ms=cached_refreshed_at_ms,
            now_ms=now_ms,
        )

    locked = False
    try:
        locked = bool(server.app_lock.acquire(timeout=_AUTO_TUNER_STATE_LOCK_TIMEOUT_SEC))
        if locked:
            live_payload = exp.read_auto_tuner_state(app=server.app)
            refreshed_at_ms = int(time.time() * 1000)
            with server.auto_tuner_state_lock:
                server.auto_tuner_state_cache = {
                    "payload": dict(live_payload),
                    "mode": "live",
                    "refreshed_at_ms": refreshed_at_ms,
                }
            return _decorate_auto_tuner_state_payload(
                live_payload,
                mode="live",
                refreshed_at_ms=refreshed_at_ms,
                now_ms=refreshed_at_ms,
            )
    except Exception:
        pass
    finally:
        if locked:
            server.app_lock.release()

    if cached_payload is not None and max(0, now_ms - cached_refreshed_at_ms) <= _AUTO_TUNER_STATE_STALE_MAX_MS:
        return _decorate_auto_tuner_state_payload(
            cached_payload,
            mode="stale_cache",
            refreshed_at_ms=cached_refreshed_at_ms,
            now_ms=now_ms,
        )

    fallback_payload = exp.read_auto_tuner_state(app=None)
    refreshed_at_ms = int(time.time() * 1000)
    with server.auto_tuner_state_lock:
        server.auto_tuner_state_cache = {
            "payload": dict(fallback_payload),
            "mode": "fallback_disk",
            "refreshed_at_ms": refreshed_at_ms,
        }
    return _decorate_auto_tuner_state_payload(
        fallback_payload,
        mode="fallback_disk",
        refreshed_at_ms=refreshed_at_ms,
        now_ms=refreshed_at_ms,
    )


def _build_handler():
    class ObservatoryHandler(BaseHTTPRequestHandler):
        server: ObservatoryWebServer

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path.startswith("/api/"):
                self._handle_api_get(parsed)
                return
            self._serve_static(parsed.path)

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if not parsed.path.startswith("/api/"):
                self._send_json({"success": False, "message": "Not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._handle_api_post(parsed)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _handle_api_get(self, parsed: urllib.parse.ParseResult) -> None:
            query = urllib.parse.parse_qs(parsed.query)
            try:
                if parsed.path == "/api/health":
                    self._send_json({"success": True, "data": {"status": "ok"}})
                    return
                if parsed.path == "/api/agent/status":
                    compact = str(query.get("compact", ["0"])[0] or "").lower() in {"1", "true", "yes"}
                    if compact:
                        payload = self.server.agent_runtime.status_compact_cached()
                    else:
                        with self.server.app_lock:
                            payload = self.server.agent_runtime.status(compact=False)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/config":
                    payload = self.server.agent_runtime.get_config_public()
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/config/profiles":
                    payload = self.server.agent_runtime.config_profiles()
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/summary":
                    with self.server.app_lock:
                        payload = self.server.agent_runtime.summary()
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/packet/detail":
                    with self.server.app_lock:
                        payload = self.server.agent_runtime.packet_detail()
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/diagnostics":
                    with self.server.app_lock:
                        payload = self.server.agent_runtime.diagnostics()
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/readiness":
                    with self.server.app_lock:
                        payload = self.server.agent_runtime.readiness(background=self.server.agent_background_status())
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/acceptance":
                    with self.server.app_lock:
                        payload = self.server.agent_runtime.acceptance_report(background=self.server.agent_background_status())
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/safety-radar":
                    with self.server.app_lock:
                        payload = self.server.agent_runtime.safety_radar(background=self.server.agent_background_status())
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/handoff":
                    write_file = str(query.get("write", ["0"])[0]).lower() in {"1", "true", "yes"}
                    compact = str(query.get("compact", ["1" if write_file else "0"])[0]).lower() in {"1", "true", "yes"}
                    with self.server.app_lock:
                        payload = self.server.agent_runtime.handoff_report(write_file=write_file, compact=compact, background=self.server.agent_background_status())
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/morning-brief":
                    write_file = str(query.get("write", ["0"])[0]).lower() in {"1", "true", "yes"}
                    with self.server.app_lock:
                        payload = self.server.agent_runtime.morning_brief(write_file=write_file, background=self.server.agent_background_status())
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/morning-review":
                    keep = _maybe_int(query.get("keep", [None])[0])
                    with self.server.app_lock:
                        payload = self.server.agent_runtime.morning_review(background=self.server.agent_background_status(), keep=keep)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/diagnostic_bundle":
                    write_file = str(query.get("write", ["0"])[0]).lower() in {"1", "true", "yes"}
                    with self.server.app_lock:
                        payload = self.server.agent_runtime.diagnostic_bundle(write_file=write_file)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/logs/plan":
                    keep = _maybe_int(query.get("keep", [None])[0])
                    with self.server.app_lock:
                        payload = self.server.agent_runtime.log_maintenance_plan(keep=keep)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/events":
                    limit = _maybe_int(query.get("limit", [80])[0]) or 80
                    payload = self.server.agent_runtime.events(limit=limit)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/jobs":
                    job_id = str(query.get("job_id", [""])[0] or "").strip()
                    include_payload = str(query.get("include_payload", ["0"])[0] or "").lower() in {"1", "true", "yes"}
                    limit = _maybe_int(query.get("limit", [20])[0]) or 20
                    payload = self.server.agent_turn_jobs_snapshot(job_id=job_id, include_payload=include_payload, limit=limit)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/outbox":
                    limit = _maybe_int(query.get("limit", [80])[0]) or 80
                    payload = self.server.agent_runtime.outbox(limit=limit)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/adapter/events":
                    limit = _maybe_int(query.get("limit", [120])[0]) or 120
                    view = str(query.get("view", ["important"])[0] or "important")
                    payload = self.server.agent_runtime.adapter_events(limit=limit, view=view)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/llm-api/events":
                    limit = _maybe_int(query.get("limit", [120])[0]) or 120
                    view = str(query.get("view", ["important"])[0] or "important")
                    payload = self.server.agent_runtime.llm_api_events(limit=limit, view=view)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/stickers":
                    payload = self.server.agent_runtime.stickers_public()
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/prompt/experiments":
                    limit = _maybe_int(query.get("limit", [40])[0]) or 40
                    payload = self.server.agent_runtime.prompt_experiments(limit=limit)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/prompt/scenarios":
                    limit = _maybe_int(query.get("limit", [80])[0]) or 80
                    payload = self.server.agent_runtime.prompt_scenarios(limit=limit)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/wake/previews":
                    limit = _maybe_int(query.get("limit", [40])[0]) or 40
                    payload = self.server.agent_runtime.wake_previews(limit=limit)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/wake/matrix":
                    limit = _maybe_int(query.get("limit", [20])[0]) or 20
                    payload = self.server.agent_runtime.wake_matrix_history(limit=limit)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/wake/policy":
                    payload = self.server.agent_runtime.wake_policy()
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/napcat/guide":
                    payload = self.server.agent_runtime.napcat_guide(host=self.server.web_host, port=self.server.web_port)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/selftests":
                    limit = _maybe_int(query.get("limit", [20])[0]) or 20
                    payload = self.server.agent_runtime.selftest_history(limit=limit)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/morning-checks":
                    limit = _maybe_int(query.get("limit", [20])[0]) or 20
                    payload = self.server.agent_runtime.morning_check_history(limit=limit)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/history":
                    kind = str(query.get("kind", ["thoughts"])[0] or "thoughts")
                    limit = _maybe_int(query.get("limit", [40])[0]) or 40
                    offset = _maybe_int(query.get("offset", [0])[0]) or 0
                    payload = self.server.agent_runtime.history(kind=kind, limit=limit, offset=offset)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/tools":
                    payload = self.server.agent_runtime.list_tools()
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/tool-matrix":
                    payload = self.server.agent_runtime.tool_matrix()
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/protocol-registry":
                    payload = self.server.agent_runtime.protocol_registry()
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/integrations":
                    payload = self.server.agent_runtime.integration_registry()
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/model-pool":
                    payload = self.server.agent_runtime.list_model_pool()
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/model-readiness":
                    with self.server.app_lock:
                        payload = self.server.agent_runtime.model_readiness()
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/model-export-preview":
                    with self.server.app_lock:
                        payload = self.server.agent_runtime.model_export_preview()
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/prompt-contract":
                    with self.server.app_lock:
                        payload = self.server.agent_runtime.prompt_injection_contract()
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/thought-continuity":
                    limit = _maybe_int(query.get("limit", [24])[0]) or 24
                    with self.server.app_lock:
                        payload = self.server.agent_runtime.thought_continuity_report(limit=limit)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/cognitive-timeline":
                    limit = _maybe_int(query.get("limit", [80])[0]) or 80
                    with self.server.app_lock:
                        payload = self.server.agent_runtime.cognitive_timeline(limit=limit)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/reply-action-audit":
                    limit = _maybe_int(query.get("limit", [80])[0]) or 80
                    with self.server.app_lock:
                        payload = self.server.agent_runtime.reply_action_audit(limit=limit)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/reply-debt-preview":
                    limit = _maybe_int(query.get("limit", [40])[0]) or 40
                    with self.server.app_lock:
                        payload = self.server.agent_runtime.reply_debt_preview(limit=limit)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/activation-roadmap":
                    with self.server.app_lock:
                        payload = self.server.agent_runtime.activation_roadmap(background=self.server.agent_background_status())
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/multimodal-readiness":
                    with self.server.app_lock:
                        payload = self.server.agent_runtime.multimodal_readiness()
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/agent/background/status":
                    payload = self.server.agent_background_status()
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/dashboard":
                    with self.server.app_lock:
                        payload = self.server.app.get_dashboard_data()
                    active_experiment_job, latest_metrics_preview = _active_experiment_job_with_preview(self.server)
                    try:
                        with self.server.maintenance_jobs_lock:
                            maintenance_jobs = [
                                dict(job)
                                for job_id, job in self.server.maintenance_jobs.items()
                                if job_id != "_seq" and isinstance(job, dict)
                            ]
                        maintenance_jobs.sort(key=lambda item: int(item.get("created_at_ms", 0) or 0), reverse=True)
                        payload = dict(payload)
                        hdb_snapshot = dict(payload.get("hdb_snapshot", {}) or {})
                        hdb_repair_jobs = list(hdb_snapshot.get("repair_jobs", []) or [])
                        idle_rows = [_idle_job_row(job) for job in maintenance_jobs[:20]]
                        hdb_snapshot["repair_jobs"] = idle_rows + hdb_repair_jobs
                        payload["hdb_snapshot"] = hdb_snapshot
                    except Exception:
                        pass
                    try:
                        payload = dict(payload)
                        if active_experiment_job is not None:
                            payload["active_experiment_job"] = active_experiment_job
                        if latest_metrics_preview is not None:
                            payload["active_experiment_latest_metrics"] = latest_metrics_preview
                            payload["live_metrics_source"] = "experiment_runner_memory"
                    except Exception:
                        pass
                    # The raw per-tick report can become extremely large during long runs.
                    # Keep the default dashboard payload compact for UI responsiveness.
                    # Use `?full=1` when a deep offline inspection is needed.
                    full = str(query.get("full", ["0"])[0] or "0").strip().lower() in {"1", "true", "yes"}
                    if not full:
                        try:
                            payload = dict(payload)
                            payload["last_report"] = _compact_report_for_web(payload.get("last_report"))
                        except Exception:
                            pass
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/experiment/live_preview":
                    active_experiment_job, latest_metrics_preview = _active_experiment_job_with_preview(self.server)
                    payload = {
                        "active_experiment_job": active_experiment_job,
                        "active_experiment_latest_metrics": latest_metrics_preview,
                        "live_metrics_source": "experiment_runner_memory" if latest_metrics_preview else "experiment_jobs",
                        "generated_at_ms": int(time.time() * 1000),
                    }
                    if latest_metrics_preview is not None:
                        tick_index = latest_metrics_preview.get("tick_index")
                        payload["tick_counter"] = tick_index
                        payload["meta"] = {
                            "tick_counter": tick_index,
                            "trace_id": latest_metrics_preview.get("trace_id"),
                            "tick_id": latest_metrics_preview.get("tick_id"),
                            "tick_source": latest_metrics_preview.get("tick_source"),
                        }
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/idle_consolidate_status":
                    job_id = (query.get("job_id", [""])[0] or "").strip()
                    if not job_id:
                        raise ValueError("job_id is required")
                    with self.server.maintenance_jobs_lock:
                        job = self.server.maintenance_jobs.get(job_id)
                    if not job:
                        self._send_json({"success": False, "message": f"job not found: {job_id}"}, status=HTTPStatus.NOT_FOUND)
                        return
                    self._send_json({"success": True, "data": job})
                    return
                if parsed.path == "/api/maintenance_jobs":
                    with self.server.maintenance_jobs_lock:
                        idle_jobs = [
                            _idle_job_row(dict(job))
                            for job_id, job in self.server.maintenance_jobs.items()
                            if job_id != "_seq" and isinstance(job, dict)
                        ]
                    try:
                        repair_jobs = [
                            _repair_job_row(dict(job))
                            for job in self.server.app.hdb._repair.jobs.values()
                            if isinstance(job, dict)
                        ]
                    except Exception:
                        repair_jobs = []
                    jobs = idle_jobs + repair_jobs
                    jobs.sort(
                        key=lambda item: int(item.get("created_at_ms", 0) or item.get("started_at_ms", 0) or 0),
                        reverse=True,
                    )
                    self._send_json({"success": True, "data": {"jobs": jobs[:80]}})
                    return
                if parsed.path == "/api/background_jobs":
                    limit = _maybe_int(query.get("limit", [80])[0]) or 80
                    jobs = _collect_background_jobs(self.server, limit=max(1, min(200, int(limit))))
                    active = [
                        job
                        for job in jobs
                        if str(job.get("status", "") or "").lower() in EXPERIMENT_ACTIVE_STATUSES
                        or str(job.get("stage", "") or "").lower() in EXPERIMENT_ACTIVE_STATUSES
                        or bool(job.get("lock_waiting", False))
                    ]
                    self._send_json(
                        {
                            "success": True,
                            "data": {
                                "jobs": jobs,
                                "active_jobs": active,
                                "active_count": len(active),
                                "generated_at_ms": int(time.time() * 1000),
                            },
                        }
                    )
                    return
                if parsed.path == "/api/state":
                    top_k = _maybe_int(query.get("top_k", [None])[0])
                    with self.server.app_lock:
                        payload = self.server.app.get_state_snapshot_data(top_k=top_k)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/hdb":
                    top_k = _maybe_int(query.get("top_k", [12])[0]) or 12
                    with self.server.app_lock:
                        payload = self.server.app.get_hdb_snapshot_data(top_k=top_k)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/action_runtime":
                    with self.server.app_lock:
                        payload = self.server.app.get_action_runtime_data()
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/episodic":
                    limit = _maybe_int(query.get("limit", [10])[0]) or 10
                    with self.server.app_lock:
                        payload = self.server.app.get_episodic_data(limit=limit)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/structure":
                    structure_id = (query.get("structure_id", [""])[0] or "").strip()
                    with self.server.app_lock:
                        payload = self.server.app.get_structure_data(structure_id)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/group":
                    group_id = (query.get("group_id", [""])[0] or "").strip()
                    with self.server.app_lock:
                        payload = self.server.app.get_group_data(group_id)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/report":
                    trace_id = (query.get("trace_id", ["latest"])[0] or "latest").strip()
                    with self.server.app_lock:
                        payload = self.server.app.get_report(trace_id)
                    if payload is None:
                        self._send_json({"success": False, "message": f"report not found: {trace_id}"}, status=HTTPStatus.NOT_FOUND)
                        return
                    full = str(query.get("full", ["0"])[0] or "0").strip().lower() in {"1", "true", "yes"}
                    if not full:
                        try:
                            payload = _compact_report_for_web(payload)
                        except Exception:
                            pass
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/config":
                    with self.server.app_lock:
                        payload = self.server.app.get_config_bundle()
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/innate_rules":
                    with self.server.app_lock:
                        payload = self.server.app.get_innate_rules_data()
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/experiment/datasets":
                    # List built-in and imported dataset files.
                    items = []
                    for ref in exp.list_dataset_files():
                        meta = _load_dataset_meta_cached(self.server, ref)
                        items.append(
                            {
                                "source": ref.source,
                                "rel_path": ref.rel_path,
                                "meta": meta,
                            }
                        )
                    self._send_json({"success": True, "data": {"datasets": items}})
                    return
                if parsed.path == "/api/experiment/dataset_protocol":
                    self._send_json({"success": True, "data": exp.dataset_protocol_doc()})
                    return
                if parsed.path == "/api/experiment/runs":
                    limit = _maybe_int(query.get("limit", [32])[0]) or 32
                    run_ids = exp.list_runs(limit=limit)
                    run_items = exp.list_run_infos(limit=limit)
                    with self.server.experiment_jobs_lock:
                        active_jobs = [
                            _experiment_job_row(job)
                            for job in self.server.experiment_jobs.values()
                            if isinstance(job, dict)
                            and str(_normalize_experiment_job_state(job).get("status", "") or "").lower()
                            in EXPERIMENT_ACTIVE_STATUSES
                        ]
                    by_run = {str(item.get("run_id", "") or ""): dict(item) for item in run_items if isinstance(item, dict)}
                    for job in active_jobs:
                        rid = str(job.get("run_id", "") or "")
                        if not rid:
                            continue
                        merged = dict(by_run.get(rid, {}))
                        merged.update(
                            {
                                "run_id": rid,
                                "status": job.get("status", merged.get("status", "")),
                                "dataset_id": job.get("dataset_id", merged.get("dataset_id", "")),
                                "tick_done": job.get("tick_done", merged.get("tick_done", 0)),
                                "source_tick_done": job.get("source_tick_done", merged.get("source_tick_done", 0)),
                                "synthetic_tick_done": job.get("synthetic_tick_done", merged.get("synthetic_tick_done", 0)),
                                "executed_tick_done_total": job.get("executed_tick_done_total", merged.get("executed_tick_done_total", 0)),
                                "tick_planned": job.get("tick_planned", merged.get("tick_planned", None)),
                                "started_at_ms": job.get("started_at_ms", merged.get("started_at_ms", 0)),
                                "updated_at_ms": job.get("updated_at_ms", merged.get("updated_at_ms", 0)),
                                "job_id": job.get("job_id", ""),
                                "job_stage": job.get("stage", ""),
                                "job_stage_label": job.get("stage_label", ""),
                                "lock_waiting": job.get("lock_waiting", False),
                            }
                        )
                        by_run[rid] = merged
                    run_items = list(by_run.values())
                    run_items.sort(key=lambda item: int(item.get("updated_at_ms", 0) or item.get("started_at_ms", 0) or 0), reverse=True)
                    self._send_json({"success": True, "data": {"runs": run_ids, "items": run_items}})
                    return
                if parsed.path == "/api/experiment/llm_review/config":
                    cfg = exp.load_review_config()
                    self._send_json({"success": True, "data": {"config": cfg.to_public_dict()}})
                    return
                if parsed.path == "/api/experiment/run/llm_review_status":
                    run_id = (query.get("run_id", [""])[0] or "").strip()
                    if not run_id:
                        raise ValueError("run_id is required")
                    payload = exp.read_review_status(run_id=run_id)
                    latest_job = _latest_llm_review_job_for_run(server=self.server, run_id=run_id)
                    if latest_job:
                        payload = dict(payload or {})
                        payload["job_id"] = str(latest_job.get("job_id", "") or payload.get("job_id", "") or "")
                        payload["job_status"] = str(latest_job.get("status", "") or "")
                        payload["job_error"] = str(latest_job.get("error", "") or "")
                        payload["job_started_at_ms"] = int(latest_job.get("started_at_ms", 0) or 0)
                        payload["job_finished_at_ms"] = int(latest_job.get("finished_at_ms", 0) or 0)
                        if str(payload.get("status", "") or "") in {"", "not_started", "unknown", "running"}:
                            job_status = str(latest_job.get("status", "") or "")
                            if job_status in {"queued", "running"}:
                                payload["status"] = "running"
                                payload.setdefault("stage", job_status)
                            elif job_status == "failed":
                                payload["status"] = "failed"
                                payload.setdefault("stage", "failed")
                                if not payload.get("error"):
                                    payload["error"] = str(latest_job.get("error", "") or "")
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/experiment/run/llm_review_report":
                    run_id = (query.get("run_id", [""])[0] or "").strip()
                    if not run_id:
                        raise ValueError("run_id is required")
                    payload = exp.read_review_report(run_id=run_id)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/experiment/run/manifest":
                    run_id = (query.get("run_id", [""])[0] or "").strip()
                    if not run_id:
                        raise ValueError("run_id is required")
                    base = exp.storage.experiment_runs_dir()  # type: ignore[attr-defined]
                    run_dir = (base / exp.storage.safe_slug(run_id)).resolve()  # type: ignore[attr-defined]
                    try:
                        run_dir.relative_to(base.resolve())
                    except ValueError:
                        raise ValueError("invalid run_id")
                    manifest_path = run_dir / "manifest.json"
                    if not manifest_path.exists():
                        self._send_json({"success": False, "message": f"manifest not found: {run_id}"}, status=HTTPStatus.NOT_FOUND)
                        return
                    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/experiment/run/metrics":
                    run_id = (query.get("run_id", [""])[0] or "").strip()
                    if not run_id:
                        raise ValueError("run_id is required")
                    every = (
                        _maybe_int(query.get("every", [0])[0])
                        or _maybe_int(query.get("downsample_every", [1])[0])
                        or 1
                    )
                    limit = _maybe_int(query.get("limit", [0])[0]) or 0
                    offset = _maybe_int(query.get("offset", [0])[0]) or 0
                    every = max(1, min(1000, int(every)))
                    limit = max(0, min(50000, int(limit)))
                    offset = max(0, min(50000, int(offset)))

                    base = exp.storage.experiment_runs_dir()  # type: ignore[attr-defined]
                    run_dir = (base / exp.storage.safe_slug(run_id)).resolve()  # type: ignore[attr-defined]
                    try:
                        run_dir.relative_to(base.resolve())
                    except ValueError:
                        raise ValueError("invalid run_id")
                    metrics_path = run_dir / "metrics.jsonl"
                    if not metrics_path.exists():
                        self._send_json({"success": False, "message": f"metrics not found: {run_id}"}, status=HTTPStatus.NOT_FOUND)
                        return
                    rows = []
                    i = 0
                    kept = 0
                    for row in exp.io.iter_jsonl(metrics_path):  # type: ignore[attr-defined]
                        if i % every != 0:
                            i += 1
                            continue
                        if kept < offset:
                            kept += 1
                            i += 1
                            continue
                        rows.append(row)
                        kept += 1
                        i += 1
                        if limit and len(rows) >= limit:
                            break
                    self._send_json(
                        {
                            "success": True,
                            "data": {
                                "run_id": run_id,
                                "every": every,
                                "downsample_every": every,
                                "offset": offset,
                                "next_offset": offset + len(rows),
                                "rows": rows,
                            },
                        }
                    )
                    return
                if parsed.path == "/api/experiment/jobs":
                    job_id = (query.get("job_id", [""])[0] or "").strip()
                    with self.server.experiment_jobs_lock:
                        if job_id:
                            job = self.server.experiment_jobs.get(job_id)
                            if not job:
                                self._send_json({"success": False, "message": f"job not found: {job_id}"}, status=HTTPStatus.NOT_FOUND)
                                return
                            self._send_json({"success": True, "data": _experiment_job_row(job)})
                            return
                        # list jobs (recent)
                        jobs = [_experiment_job_row(job) for job in self.server.experiment_jobs.values() if isinstance(job, dict)]
                        jobs.sort(key=lambda j: int(j.get("created_at_ms", 0) or 0), reverse=True)
                        self._send_json({"success": True, "data": {"jobs": jobs[:40]}})
                        return
                if parsed.path == "/api/experiment/llm_review/jobs":
                    job_id = (query.get("job_id", [""])[0] or "").strip()
                    with self.server.llm_review_jobs_lock:
                        if job_id:
                            job = self.server.llm_review_jobs.get(job_id)
                            if not job:
                                self._send_json({"success": False, "message": f"job not found: {job_id}"}, status=HTTPStatus.NOT_FOUND)
                                return
                            self._send_json({"success": True, "data": job})
                            return
                        jobs = list(self.server.llm_review_jobs.values())
                        jobs.sort(key=lambda j: int(j.get("created_at_ms", 0) or 0), reverse=True)
                        self._send_json({"success": True, "data": {"jobs": jobs[:40]}})
                        return
                if parsed.path == "/api/experiment/auto_tuner/config":
                    self._send_json({"success": True, "data": exp.load_auto_tuner_public_config()})
                    return
                if parsed.path == "/api/experiment/auto_tuner/catalog":
                    with self.server.app_lock:
                        payload = exp.read_auto_tuner_catalog(app=self.server.app)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/experiment/auto_tuner/state":
                    payload = _load_auto_tuner_state_cached(self.server)
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/experiment/auto_tuner/audit":
                    limit = _maybe_int(query.get("limit", [200])[0]) or 200
                    payload = exp.read_auto_tuner_audit(limit=max(1, min(2000, limit)))
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/experiment/auto_tuner/rules":
                    with self.server.app_lock:
                        payload = {
                            "rules": exp.load_auto_tuner_rules(),
                            "catalog": exp.build_auto_tuner_rule_catalog(app=self.server.app),
                        }
                    self._send_json({"success": True, "data": payload})
                    return
                if parsed.path == "/api/experiment/auto_tuner/rollback_points":
                    limit = _maybe_int(query.get("limit", [80])[0]) or 80
                    self._send_json({"success": True, "data": exp.list_rollback_points(limit=max(1, min(200, limit)))})
                    return
                if parsed.path == "/api/experiment/auto_tuner/llm/config":
                    self._send_json({"success": True, "data": exp.load_auto_tuner_llm_config()})
                    return
                if parsed.path == "/api/experiment/auto_tuner/llm/jobs":
                    job_id = (query.get("job_id", [""])[0] or "").strip()
                    with self.server.auto_tuner_llm_jobs_lock:
                        if job_id:
                            job = self.server.auto_tuner_llm_jobs.get(job_id)
                            if not job:
                                self._send_json({"success": False, "message": f"job not found: {job_id}"}, status=HTTPStatus.NOT_FOUND)
                                return
                            self._send_json({"success": True, "data": job})
                            return
                        jobs = list(self.server.auto_tuner_llm_jobs.values())
                        jobs.sort(key=lambda j: int(j.get("created_at_ms", 0) or 0), reverse=True)
                        self._send_json({"success": True, "data": {"jobs": jobs[:40]}})
                        return
                self._send_json({"success": False, "message": "Unknown API path"}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._send_json({"success": False, "message": str(exc)}, status=HTTPStatus.BAD_REQUEST)

        def _handle_api_post(self, parsed: urllib.parse.ParseResult) -> None:
            payload = self._read_json_body()
            try:
                if parsed.path == "/api/agent/config/save":
                    config = payload.get("config") if isinstance(payload.get("config"), dict) else payload
                    result = self.server.agent_runtime.update_config(config if isinstance(config, dict) else {})
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/config/preset":
                    result = self.server.agent_runtime.apply_preset(str(payload.get("preset", "") or ""))
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/config/profile/save":
                    result = self.server.agent_runtime.save_config_profile(payload)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/config/profile/apply":
                    result = self.server.agent_runtime.apply_config_profile(payload)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/config/profile/delete":
                    result = self.server.agent_runtime.delete_config_profile(payload)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/message":
                    result = self.server.submit_agent_turn(payload if isinstance(payload, dict) else {})
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/job/stop":
                    result = self.server.request_stop_agent_turn(
                        job_id=str(payload.get("job_id") or payload.get("id") or ""),
                        reason=str(payload.get("reason") or "operator_stop"),
                    )
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/attachments/preview":
                    result = self.server.agent_runtime.preview_attachments(payload)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/stickers/sync":
                    result = self.server.agent_runtime.sync_stickers()
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/stickers/delete":
                    result = self.server.agent_runtime.delete_sticker(payload if isinstance(payload, dict) else {})
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/stickers/clear":
                    result = self.server.agent_runtime.clear_stickers(payload if isinstance(payload, dict) else {})
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/prompt/preview":
                    result = self.server.agent_runtime.prompt_preview(payload)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/ticks":
                    count = max(1, int(payload.get("count", 1) or 1))
                    with self.server.app_lock:
                        apply_experiment_default_app_overrides(
                            self.server.app,
                            source="agent_api_ticks",
                        )
                        result = self.server.agent_runtime.run_ticks(count=count)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/clear":
                    clear_ap_runtime = bool(payload.get("clear_ap_runtime", False))
                    result = self.server.clear_agent_history(clear_ap_runtime=clear_ap_runtime)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/logs/maintain":
                    with self.server.app_lock:
                        result = self.server.agent_runtime.maintain_logs(payload)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/bootstrap":
                    with self.server.app_lock:
                        apply_experiment_default_app_overrides(
                            self.server.app,
                            source="agent_api_bootstrap",
                        )
                        result = self.server.agent_runtime.bootstrap_seed()
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/llm/test":
                    result = self.server.agent_runtime.test_llm()
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/persona/polish":
                    result = self.server.agent_runtime.polish_persona(payload)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/tool/run":
                    with self.server.app_lock:
                        apply_experiment_default_app_overrides(
                            self.server.app,
                            source="agent_api_tool",
                        )
                        result = self.server.agent_runtime.run_tool(payload)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/model-pool/apply":
                    result = self.server.agent_runtime.apply_model_slot(payload)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/model-pool/save":
                    result = self.server.agent_runtime.save_model_slot(payload)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/model-pool/delete":
                    result = self.server.agent_runtime.delete_model_slot(payload)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/prompt/ab":
                    with self.server.app_lock:
                        result = self.server.agent_runtime.prompt_ab_probe(payload)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/background/start":
                    result = self.server.start_agent_background()
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/background/stop":
                    result = self.server.stop_agent_background()
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/background/step":
                    result = self.server.run_agent_background_step()
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/napcat/launch":
                    result = self.server.launch_napcat()
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/wake/preview":
                    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
                    result = self.server.agent_runtime.preview_wake(event if isinstance(event, dict) else {})
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/wake/matrix":
                    result = self.server.agent_runtime.wake_matrix_probe(payload)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/selftest/run":
                    result = self.server.agent_runtime.run_selftest(payload)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/morning-check/run":
                    result = self.server.agent_runtime.run_morning_check(payload, background=self.server.agent_background_status())
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path in {"/api/agent/adapter/event", "/api/agent/napcat/event"}:
                    result = self.server.submit_adapter_event(payload)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/agent/adapter/reply":
                    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
                    text = str(payload.get("text") or payload.get("reply_text") or "")
                    result = self.server.agent_runtime.send_adapter_reply(
                        event if isinstance(event, dict) else {},
                        text,
                        reply_id=str(payload.get("reply_id") or ""),
                        mentions=payload.get("mentions") if isinstance(payload.get("mentions"), list) else None,
                        segments=payload.get("segments") if isinstance(payload.get("segments"), list) else None,
                        attachments=payload.get("attachments") if isinstance(payload.get("attachments"), list) else None,
                        action_type=str(payload.get("action_type") or payload.get("type") or "reply"),
                        sticker_id=str(payload.get("sticker_id") or ""),
                    )
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/cycle":
                    text = payload.get("text")
                    try:
                        with self.server.app_lock:
                            alignment = apply_experiment_default_app_overrides(
                                self.server.app,
                                source="realtime_api_cycle",
                            )
                            report = self.server.app.run_cycle(text=text)
                            if isinstance(report, dict):
                                observatory_report = report.setdefault("observatory", {})
                                if isinstance(observatory_report, dict):
                                    observatory_report["runtime_alignment"] = alignment
                    except Exception as exc:
                        self._send_json(
                            {
                                "success": False,
                                "message": str(exc),
                                "error": str(exc),
                                "error_type": type(exc).__name__,
                                "traceback": traceback.format_exc(limit=12),
                            },
                            status=HTTPStatus.INTERNAL_SERVER_ERROR,
                        )
                        return
                    self._send_json({"success": True, "data": report})
                    return
                if parsed.path == "/api/tick":
                    count = max(1, int(payload.get("count", 1)))
                    with self.server.app_lock:
                        alignment = apply_experiment_default_app_overrides(
                            self.server.app,
                            source="realtime_api_tick",
                        )
                        reports = self.server.app.run_tick_cycles(count=count)
                        for report in reports:
                            if isinstance(report, dict):
                                observatory_report = report.setdefault("observatory", {})
                                if isinstance(observatory_report, dict):
                                    observatory_report["runtime_alignment"] = alignment
                    self._send_json({"success": True, "data": reports})
                    return
                if parsed.path == "/api/check":
                    target = payload.get("target")
                    with self.server.app_lock:
                        result = self.server.app.hdb.self_check_hdb(trace_id="web_check", target_id=target)
                    self._send_json(result)
                    return
                if parsed.path == "/api/repair":
                    target = str(payload.get("target", "")).strip()
                    if not target:
                        raise ValueError("target is required")
                    with self.server.app_lock:
                        result = self.server.app.hdb.repair_hdb(
                            trace_id="web_repair",
                            target_id=target,
                            repair_scope="targeted",
                            background=False,
                        )
                    self._send_json(result)
                    return
                if parsed.path == "/api/repair_all":
                    locked = self.server.app_lock.acquire(blocking=False)
                    if not locked:
                        self._send_json(
                            {
                                "success": False,
                                "code": "BUSY",
                                "message": "当前主循环或维护任务正在占用 HDB，请稍后再提交全局修复。",
                            },
                            status=HTTPStatus.CONFLICT,
                        )
                        return
                    try:
                        result = self.server.app.hdb.repair_hdb(
                            trace_id="web_repair_all",
                            repair_scope="global_quick",
                            background=True,
                        )
                    finally:
                        self.server.app_lock.release()
                    self._send_json(result)
                    return
                if parsed.path == "/api/idle_consolidate":
                    rebuild = payload.get("rebuild_pointer_index", True)
                    apply_limits = payload.get("apply_soft_limits", True)
                    reason = str(payload.get("reason", "") or "").strip() or "web_manual_trigger"
                    background = bool(payload.get("background", False))
                    max_cs_events = payload.get("max_cs_events", None)
                    batch_limit = payload.get("batch_limit", None)
                    try:
                        max_cs_events = int(max_cs_events) if max_cs_events is not None else None
                    except Exception:
                        max_cs_events = None
                    try:
                        batch_limit = int(batch_limit) if batch_limit is not None else None
                    except Exception:
                        batch_limit = None

                    def _run_idle_consolidation() -> dict:
                        with self.server.app_lock:
                            data = {}
                            try:
                                def progress_callback(progress: dict[str, Any]) -> None:
                                    with self.server.maintenance_jobs_lock:
                                        j = self.server.maintenance_jobs.get(job_id) or {}
                                        j["progress"] = dict(progress or {})
                                        j["updated_at_ms"] = int(time.time() * 1000)
                                        self.server.maintenance_jobs[job_id] = j
                                    try:
                                        self.server.app.hdb.update_idle_consolidation_progress(
                                            status="running",
                                            job_id=job_id,
                                            request=dict(j.get("request", {}) or {}),
                                            progress=dict(progress or {}),
                                        )
                                    except Exception:
                                        pass

                                data["hdb"] = self.server.app.hdb.idle_consolidate_hdb(
                                    trace_id="web_idle_consolidate",
                                    reason=reason,
                                    rebuild_pointer_index=bool(rebuild),
                                    apply_soft_limits=bool(apply_limits),
                                    batch_limit=batch_limit,
                                    progress_callback=progress_callback,
                                )
                            except Exception as exc:
                                data["hdb_error"] = str(exc)

                            if hasattr(self.server.app, "cognitive_stitching") and hasattr(self.server.app.cognitive_stitching, "idle_consolidate"):
                                try:
                                    data["cognitive_stitching"] = self.server.app.cognitive_stitching.idle_consolidate(
                                        hdb=self.server.app.hdb,
                                        trace_id="web_idle_consolidate_cs",
                                        tick_id="web_idle_consolidate",
                                        reason=reason,
                                        max_events=max_cs_events,
                                    )
                                except Exception as exc:
                                    data["cognitive_stitching_error"] = str(exc)
                        return data

                    if background:
                        now_ms = int(time.time() * 1000)
                        with self.server.maintenance_jobs_lock:
                            seq = int(self.server.maintenance_jobs.get("_seq", 0) or 0) + 1
                            self.server.maintenance_jobs["_seq"] = seq
                            job_id = f"idle_cons_{now_ms}_{seq:04d}"
                            job = {
                                "job_id": job_id,
                                "job_type": "idle_consolidation",
                                "status": "queued",
                                "created_at_ms": now_ms,
                                "started_at_ms": 0,
                                "finished_at_ms": 0,
                                "request": {
                                    "reason": reason,
                                    "rebuild_pointer_index": bool(rebuild),
                                    "apply_soft_limits": bool(apply_limits),
                                    "max_cs_events": max_cs_events,
                                    "batch_limit": batch_limit,
                                },
                                "data": None,
                                "error": "",
                            }
                            self.server.maintenance_jobs[job_id] = job
                            # Prevent unbounded growth (in-memory only).
                            try:
                                items = [
                                    (jid, j)
                                    for jid, j in self.server.maintenance_jobs.items()
                                    if isinstance(j, dict) and jid and jid != "_seq"
                                ]
                                if len(items) > 80:
                                    items.sort(key=lambda it: int((it[1] or {}).get("created_at_ms", 0) or 0))
                                    for jid, _ in items[: max(0, len(items) - 60)]:
                                        self.server.maintenance_jobs.pop(jid, None)
                            except Exception:
                                pass

                        def worker() -> None:
                            request_payload = {}
                            with self.server.maintenance_jobs_lock:
                                j = self.server.maintenance_jobs.get(job_id) or {}
                                j["status"] = "running"
                                j["started_at_ms"] = int(time.time() * 1000)
                                j["updated_at_ms"] = j["started_at_ms"]
                                request_payload = dict(j.get("request", {}) or {})
                                self.server.maintenance_jobs[job_id] = j
                            try:
                                try:
                                    self.server.app.hdb.update_idle_consolidation_progress(
                                        status="running",
                                        job_id=job_id,
                                        request=request_payload,
                                        progress={"phase": "running"},
                                    )
                                except Exception:
                                    pass
                                data = _run_idle_consolidation()
                                with self.server.maintenance_jobs_lock:
                                    j = self.server.maintenance_jobs.get(job_id) or {}
                                    j["status"] = "completed"
                                    j["finished_at_ms"] = int(time.time() * 1000)
                                    j["updated_at_ms"] = j["finished_at_ms"]
                                    j["data"] = data
                                    hdb_data = ((data.get("hdb") or {}).get("data") or {}) if isinstance(data, dict) else {}
                                    j["progress"] = dict(hdb_data) if isinstance(hdb_data, dict) else {}
                                    self.server.maintenance_jobs[job_id] = j
                                try:
                                    self.server.app.hdb.update_idle_consolidation_progress(
                                        status="completed",
                                        job_id=job_id,
                                        request=request_payload,
                                        progress=dict(hdb_data) if isinstance(hdb_data, dict) else {},
                                    )
                                except Exception:
                                    pass
                            except Exception as exc:
                                with self.server.maintenance_jobs_lock:
                                    j = self.server.maintenance_jobs.get(job_id) or {}
                                    j["status"] = "failed"
                                    j["finished_at_ms"] = int(time.time() * 1000)
                                    j["updated_at_ms"] = j["finished_at_ms"]
                                    j["error"] = str(exc)
                                    self.server.maintenance_jobs[job_id] = j
                                try:
                                    self.server.app.hdb.update_idle_consolidation_progress(
                                        status="failed",
                                        job_id=job_id,
                                        request=request_payload,
                                        progress={"phase": "failed"},
                                        error=str(exc),
                                    )
                                except Exception:
                                    pass

                        threading.Thread(target=worker, daemon=True).start()
                        self._send_json({"success": True, "code": "OK", "message": "idle consolidation job queued", "data": job})
                        return

                    data = _run_idle_consolidation()
                    self._send_json({"success": True, "code": "OK", "message": "idle consolidation completed", "data": data})
                    return
                if parsed.path == "/api/stop_repair":
                    job_id = str(payload.get("repair_job_id", "")).strip()
                    if not job_id:
                        raise ValueError("repair_job_id is required")
                    with self.server.app_lock:
                        result = self.server.app.hdb.stop_repair_job(repair_job_id=job_id, trace_id="web_stop_repair")
                    self._send_json(result)
                    return
                if parsed.path == "/api/clear_hdb":
                    with self.server.app_lock:
                        result = self.server.app.hdb.clear_hdb(trace_id="web_clear_hdb", reason="web_reset", operator="researcher")
                    self._send_json(result)
                    return
                if parsed.path == "/api/clear_all":
                    with self.server.app_lock:
                        result = _reset_app_runtime_modules(
                            self.server.app,
                            clear_hdb=True,
                            trace_prefix="web_clear_all",
                            reason="web_reset",
                            operator="researcher",
                        )
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/clear_runtime":
                    with self.server.app_lock:
                        result = _reset_app_runtime_modules(
                            self.server.app,
                            clear_hdb=False,
                            trace_prefix="web_clear_runtime",
                            reason="web_reset",
                            operator="researcher",
                        )
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path in {"/api/experiment/clear_all", "/api/experiment/runtime/clear", "/api/experiment/hdb/clear"}:
                    with self.server.app_lock:
                        if parsed.path == "/api/experiment/hdb/clear":
                            result = self.server.app.hdb.clear_hdb(
                                trace_id="web_experiment_clear_hdb",
                                reason="web_experiment_reset",
                                operator="researcher",
                            )
                        else:
                            result = _reset_app_runtime_modules(
                                self.server.app,
                                clear_hdb=parsed.path == "/api/experiment/clear_all",
                                trace_prefix=(
                                    "web_experiment_clear_all"
                                    if parsed.path == "/api/experiment/clear_all"
                                    else "web_experiment_clear_runtime"
                                ),
                                reason="web_experiment_reset",
                                operator="researcher",
                            )
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/experiment/datasets/import":
                    # Import a dataset file by uploading text content (no multipart).
                    # Stored under observatory/outputs/datasets_imported (gitignored).
                    content = str(payload.get("content", "") or "")
                    if not content.strip():
                        raise ValueError("content is required")
                    fmt = str(payload.get("format", "yaml") or "yaml").strip().lower()
                    if fmt not in {"yaml", "yml", "jsonl"}:
                        raise ValueError("format must be yaml/yml/jsonl")
                    filename = str(payload.get("filename", "") or "").strip() or "imported_dataset"
                    safe_name = exp.storage.safe_slug(filename, fallback="imported_dataset")  # type: ignore[attr-defined]
                    ext = ".jsonl" if fmt == "jsonl" else ".yaml"
                    out_dir = exp.storage.imported_datasets_dir()  # type: ignore[attr-defined]
                    out_dir.mkdir(parents=True, exist_ok=True)
                    out_path = (out_dir / f"{safe_name}{ext}").resolve()
                    try:
                        out_path.relative_to(out_dir.resolve())
                    except ValueError:
                        raise ValueError("invalid filename")

                    # Validate basic parse for YAML to fail fast.
                    if ext in {".yaml", ".yml"}:
                        try:
                            raw = exp.io.load_yaml_text(content)  # type: ignore[attr-defined]
                            norm = exp.validate_and_normalize_dataset(raw)
                            summary = exp.dataset_overview(norm)
                        except Exception as exc:
                            raise ValueError(f"YAML dataset validation failed: {exc}")
                    else:
                        try:
                            summary = exp.validate_and_summarize_jsonl_text(content)
                        except Exception as exc:
                            raise ValueError(f"JSONL 数据集校验失败: {exc}")
                    out_path.write_text(content, encoding="utf-8")
                    self._send_json(
                        {
                            "success": True,
                            "data": {
                                "source": "imported",
                                "rel_path": out_path.relative_to(out_dir).as_posix(),
                                "summary": summary,
                            },
                        }
                    )
                    return
                if parsed.path == "/api/experiment/datasets/preview":
                    ref = payload.get("dataset_ref") or {}
                    if not isinstance(ref, dict):
                        raise ValueError("dataset_ref must be an object")
                    source = str(ref.get("source", "") or "").strip()
                    rel_path = str(ref.get("rel_path", "") or "").strip()
                    if not source or not rel_path:
                        raise ValueError("dataset_ref.source and dataset_ref.rel_path are required")
                    limit = int(payload.get("limit", 24) or 24)
                    limit = max(1, min(200, limit))
                    dataset_ref = exp.DatasetFileRef(source=source, rel_path=rel_path)
                    dataset_id, digest, normalized_doc, ticks_iter, total_ticks = exp.load_dataset_ticks(dataset_ref=dataset_ref, preview_limit=limit)
                    tick_summary = exp.summarize_tick_counts(normalized_doc) if isinstance(normalized_doc, dict) else {}
                    overview = exp.dataset_overview(normalized_doc) if isinstance(normalized_doc, dict) else {}
                    # ticks_iter is a list when preview_limit is set
                    ticks_list = list(ticks_iter) if not isinstance(ticks_iter, list) else ticks_iter
                    if not isinstance(normalized_doc, dict):
                        p = exp.storage.resolve_dataset_file(dataset_ref)  # type: ignore[attr-defined]
                        try:
                            jsonl_summary = exp.summarize_expanded_tick_items(exp.io.iter_jsonl(p))  # type: ignore[attr-defined]
                        except Exception:
                            jsonl_summary = {}
                        tick_summary = jsonl_summary
                        overview = {
                            "dataset_id": jsonl_summary.get("dataset_id", dataset_id),
                            "title": "",
                            "description": "",
                            "experiment_goal": "",
                            "time_basis": jsonl_summary.get("time_basis", ""),
                            "tick_dt_ms": jsonl_summary.get("tick_dt_ms", None),
                            "estimated_ticks": jsonl_summary.get("total_ticks", total_ticks),
                            "effective_text_ticks": jsonl_summary.get("effective_text_ticks", None),
                            "empty_ticks": jsonl_summary.get("empty_ticks", None),
                            "labeled_ticks": jsonl_summary.get("labeled_ticks", None),
                            "evaluation_dimensions": [],
                            "notes": [],
                        }
                    self._send_json(
                        {
                            "success": True,
                            "data": {
                                "dataset_id": dataset_id,
                                "dataset_sha256": digest,
                                "total_ticks": total_ticks,
                                "effective_text_ticks": tick_summary.get("effective_text_ticks") if tick_summary else None,
                                "empty_ticks": tick_summary.get("empty_ticks") if tick_summary else None,
                                "labeled_ticks": tick_summary.get("labeled_ticks") if tick_summary else None,
                                "preview_limit": limit,
                                "preview_ticks": ticks_list,
                                "normalized_meta": (normalized_doc or {}).get("_meta", {}) if isinstance(normalized_doc, dict) else {},
                                "overview": overview,
                            },
                        }
                    )
                    return
                if parsed.path == "/api/experiment/datasets/expand":
                    ref = payload.get("dataset_ref") or {}
                    if not isinstance(ref, dict):
                        raise ValueError("dataset_ref must be an object")
                    source = str(ref.get("source", "") or "").strip()
                    rel_path = str(ref.get("rel_path", "") or "").strip()
                    if not source or not rel_path:
                        raise ValueError("dataset_ref.source and dataset_ref.rel_path are required")
                    dataset_ref = exp.DatasetFileRef(source=source, rel_path=rel_path)
                    # Expand to observatory/outputs/datasets/<dataset_id>/expanded_ticks.jsonl
                    dataset_id, _, normalized_doc, _, _ = exp.load_dataset_ticks(dataset_ref=dataset_ref, preview_limit=1)
                    if not dataset_id:
                        dataset_id = Path(rel_path).stem
                    out_dir = Path(__file__).resolve().parent / "outputs" / "datasets" / exp.storage.safe_slug(dataset_id)  # type: ignore[attr-defined]
                    out_path = out_dir / "expanded_ticks.jsonl"
                    result = exp.export_expanded_ticks(dataset_ref=dataset_ref, out_path=out_path)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/experiment/run/start":
                    ref = payload.get("dataset_ref") or {}
                    if not isinstance(ref, dict):
                        raise ValueError("dataset_ref must be an object")
                    source = str(ref.get("source", "") or "").strip()
                    rel_path = str(ref.get("rel_path", "") or "").strip()
                    if not source or not rel_path:
                        raise ValueError("dataset_ref.source and dataset_ref.rel_path are required")
                    dataset_ref = exp.DatasetFileRef(source=source, rel_path=rel_path)

                    opt_raw = payload.get("options") or {}
                    if not isinstance(opt_raw, dict):
                        opt_raw = {}
                    options = exp.RunOptions(
                        reset_mode=str(opt_raw.get("reset_mode", "keep") or "keep").strip(),
                        clean_run=bool(opt_raw.get("clean_run", False)),
                        export_json=bool(opt_raw.get("export_json", False)),
                        export_html=bool(opt_raw.get("export_html", False)),
                        auto_tune_enabled=bool(opt_raw.get("auto_tune_enabled", False)),
                        auto_tune_short_term=bool(opt_raw.get("auto_tune_short_term", True)),
                        auto_tune_long_term=bool(opt_raw.get("auto_tune_long_term", True)),
                        time_sensor_time_basis=(str(opt_raw.get("time_sensor_time_basis")).strip() if opt_raw.get("time_sensor_time_basis") is not None else None),
                        tick_interval_sec=(float(opt_raw.get("tick_interval_sec")) if opt_raw.get("tick_interval_sec") is not None else None),
                        max_ticks=(int(opt_raw.get("max_ticks")) if opt_raw.get("max_ticks") is not None else None),
                    )

                    # Prepare job record
                    job_id = f"exp_job_{int(time.time() * 1000)}_{threading.get_ident()}"
                    # Resolve dataset_id early (for UI display) without consuming too much work.
                    try:
                        dataset_id, _, _, _, total_ticks = exp.load_dataset_ticks(dataset_ref=dataset_ref, preview_limit=1)
                    except Exception:
                        dataset_id, total_ticks = Path(rel_path).stem, None
                    run_id = str(payload.get("run_id", "") or "").strip() or exp.make_run_id(dataset_id=dataset_id)

                    job = {
                        "job_id": job_id,
                        "run_id": run_id,
                        "dataset_ref": dataset_ref.to_dict(),
                        "dataset_id": dataset_id,
                        "status": "queued",
                        "tick_done": 0,
                        "tick_planned": total_ticks,
                        "created_at_ms": int(time.time() * 1000),
                        "started_at_ms": 0,
                        "finished_at_ms": 0,
                        "cancelled": False,
                        "error": "",
                        "auto_tuner_run_options": {
                            "enabled": bool(options.auto_tune_enabled),
                            "short_term": bool(options.auto_tune_short_term),
                            "long_term": bool(options.auto_tune_long_term),
                        },
                        "auto_tuner_last_tick": {},
                        "auto_tuner_recent_events": [],
                    }
                    with self.server.experiment_jobs_lock:
                        self.server.experiment_jobs[job_id] = job

                    def progress_cb(update: dict[str, Any]) -> None:
                        with self.server.experiment_jobs_lock:
                            j = self.server.experiment_jobs.get(job_id) or {}
                            if not j:
                                return
                            if update.get("run_id"):
                                j["run_id"] = str(update.get("run_id") or j.get("run_id") or "")
                            j["tick_done"] = int(update.get("tick_done", j.get("tick_done", 0)) or 0)
                            j["source_tick_done"] = int(update.get("source_tick_done", j.get("source_tick_done", j.get("tick_done", 0))) or 0)
                            j["synthetic_tick_done"] = int(update.get("synthetic_tick_done", j.get("synthetic_tick_done", 0)) or 0)
                            j["executed_tick_done_total"] = int(
                                update.get("executed_tick_done_total", j.get("executed_tick_done_total", j.get("tick_done", 0))) or 0
                            )
                            if update.get("tick_planned") is not None:
                                j["tick_planned"] = int(update.get("tick_planned") or 0)
                            if update.get("status"):
                                j["status"] = str(update.get("status") or j.get("status") or "")
                            if update.get("stage"):
                                j["stage"] = str(update.get("stage") or "")
                            if update.get("stage_label"):
                                j["stage_label"] = str(update.get("stage_label") or "")
                            if update.get("lock_waiting") is not None:
                                j["lock_waiting"] = bool(update.get("lock_waiting", False))
                            if update.get("lock_wait_started_at_ms") is not None:
                                j["lock_wait_started_at_ms"] = int(update.get("lock_wait_started_at_ms") or 0)
                            if update.get("lock_wait_ms") is not None:
                                j["lock_wait_ms"] = int(update.get("lock_wait_ms") or 0)
                            if update.get("last_lock_wait_ms") is not None:
                                j["last_lock_wait_ms"] = int(update.get("last_lock_wait_ms") or 0)
                            if update.get("error"):
                                j["error"] = str(update.get("error") or "")
                            if update.get("tick_source"):
                                j["tick_source"] = str(update.get("tick_source") or "")
                            if update.get("tick_index") is not None:
                                try:
                                    j["last_tick_index"] = int(update.get("tick_index") or 0)
                                except Exception:
                                    pass
                            latest_metrics_preview = update.get("latest_metrics_preview")
                            if isinstance(latest_metrics_preview, dict):
                                j["latest_metrics_preview"] = dict(latest_metrics_preview)
                                try:
                                    j["latest_metrics_tick_index"] = int(
                                        latest_metrics_preview.get("tick_index", latest_metrics_preview.get("tick", j.get("last_tick_index", 0))) or 0
                                    )
                                except Exception:
                                    pass
                                j["latest_metrics_preview_source"] = str(latest_metrics_preview.get("preview_source", "experiment_runner_memory") or "")
                            j["last_progress_at_ms"] = int(time.time() * 1000)
                            j["updated_at_ms"] = j["last_progress_at_ms"]
                            short_term = update.get("auto_tuner_short_term")
                            if isinstance(short_term, dict):
                                row = {
                                    "tick_index": j.get("last_tick_index"),
                                    "enabled": bool(short_term.get("enabled", False)),
                                    "applied": bool(short_term.get("applied", False)),
                                    "reason": str(short_term.get("reason", "") or ""),
                                    "applied_count": int(short_term.get("applied_count", 0) or 0),
                                    "applied_updates": [dict(item) for item in (short_term.get("applied_updates") or []) if isinstance(item, dict)][:8],
                                }
                                j["auto_tuner_last_tick"] = row
                                history = list(j.get("auto_tuner_recent_events", [])) if isinstance(j.get("auto_tuner_recent_events"), list) else []
                                prev = history[-1] if history else {}
                                should_append = bool(row.get("applied")) or str(row.get("reason", "") or "") != str(prev.get("reason", "") or "")
                                if should_append:
                                    history.append(row)
                                elif history:
                                    history[-1] = row
                                else:
                                    history.append(row)
                                j["auto_tuner_recent_events"] = history[-40:]
                            self.server.experiment_jobs[job_id] = j

                    def cancel_cb() -> bool:
                        with self.server.experiment_jobs_lock:
                            j = self.server.experiment_jobs.get(job_id) or {}
                            return bool(j.get("cancelled", False))

                    def worker() -> None:
                        with self.server.experiment_jobs_lock:
                            j = self.server.experiment_jobs.get(job_id) or {}
                            j["status"] = "running"
                            j["stage"] = "loading_dataset"
                            j["stage_label"] = "后台线程已启动，正在读取数据集"
                            j["started_at_ms"] = int(time.time() * 1000)
                            j["updated_at_ms"] = j["started_at_ms"]
                            self.server.experiment_jobs[job_id] = j
                        try:
                            # Important: do NOT hold app_lock for the entire run.
                            # We lock per-tick inside exp.run_dataset(app_lock=...),
                            # so the existing observatory UI can still refresh between ticks.
                            res = exp.run_dataset(
                                app=self.server.app,
                                app_lock=self.server.app_lock,
                                dataset_ref=dataset_ref,
                                options=options,
                                run_id=run_id,
                                progress_cb=progress_cb,
                                cancel_cb=cancel_cb,
                            )
                        except Exception as exc:
                            res = {"success": False, "error": str(exc), "run_id": run_id}
                        with self.server.experiment_jobs_lock:
                            j = self.server.experiment_jobs.get(job_id) or {}
                            j["finished_at_ms"] = int(time.time() * 1000)
                            if not res.get("success", False):
                                j["status"] = "failed"
                                j["stage"] = "failed"
                                j["stage_label"] = "运行失败"
                                j["error"] = str(res.get("error", "") or "")
                            else:
                                j["status"] = str(res.get("manifest", {}).get("status", "completed") or "completed")
                                j["stage"] = "finished"
                                j["stage_label"] = _job_stage_label(j["status"], j["status"])
                            j["updated_at_ms"] = j["finished_at_ms"]
                            self.server.experiment_jobs[job_id] = j

                        # Optional: auto-run LLM review after completion.
                        try:
                            cfg = exp.load_review_config()
                            status = str(res.get("manifest", {}).get("status", "") or "")
                            if bool(cfg.enabled) and bool(cfg.auto_analyze_on_completion) and status in {"completed", "stopped_max_ticks"}:
                                _start_llm_review_job(server=self.server, run_id=str(res.get("run_id", run_id) or run_id), force=False)
                        except Exception:
                            pass

                    threading.Thread(target=worker, daemon=True).start()
                    self._send_json({"success": True, "data": {"job_id": job_id, "run_id": run_id}})
                    return
                if parsed.path == "/api/experiment/llm_review/config/save":
                    values = payload.get("config") if isinstance(payload.get("config"), dict) else (payload if isinstance(payload, dict) else {})
                    cfg = exp.save_review_config(values if isinstance(values, dict) else {})
                    self._send_json({"success": True, "data": {"config": cfg.to_public_dict()}})
                    return
                if parsed.path == "/api/experiment/auto_tuner/config/save":
                    values = payload.get("config") if isinstance(payload.get("config"), dict) else (payload if isinstance(payload, dict) else {})
                    data = exp.save_auto_tuner_public_config(values if isinstance(values, dict) else {})
                    self._send_json({"success": True, "data": data})
                    return
                if parsed.path == "/api/experiment/auto_tuner/rules/save":
                    values = payload.get("rules") if isinstance(payload.get("rules"), dict) else (payload if isinstance(payload, dict) else {})
                    saved = exp.save_auto_tuner_rules(values if isinstance(values, dict) else {})
                    with self.server.app_lock:
                        catalog = exp.build_auto_tuner_rule_catalog(app=self.server.app)
                    self._send_json({"success": True, "data": {"rules": saved, "catalog": catalog}})
                    return
                if parsed.path == "/api/experiment/auto_tuner/rollback":
                    point_id = str(payload.get("point_id", "") or "").strip()
                    if not point_id:
                        raise ValueError("point_id is required")
                    with self.server.app_lock:
                        data = exp.rollback_to_point(point_id=point_id, app=self.server.app)
                    self._send_json({"success": True, "data": data})
                    return
                if parsed.path == "/api/experiment/auto_tuner/llm/config/save":
                    values = payload.get("config") if isinstance(payload.get("config"), dict) else (payload if isinstance(payload, dict) else {})
                    data = exp.save_auto_tuner_llm_config(values if isinstance(values, dict) else {})
                    self._send_json({"success": True, "data": data})
                    return
                if parsed.path == "/api/experiment/auto_tuner/llm/analyze":
                    run_id = str(payload.get("run_id", "") or "").strip()
                    prompt = str(payload.get("user_prompt", "") or "").strip()
                    focus_metrics = payload.get("focus_metrics") if isinstance(payload.get("focus_metrics"), list) else []
                    job = _start_auto_tuner_llm_job(server=self.server, run_id=run_id, user_prompt=prompt, focus_metrics=focus_metrics)
                    self._send_json({"success": True, "data": job})
                    return
                if parsed.path == "/api/experiment/run/llm_review/start":
                    run_id = str(payload.get("run_id", "") or "").strip()
                    if not run_id:
                        raise ValueError("run_id is required")
                    force = bool(payload.get("force", False))
                    job = _start_llm_review_job(server=self.server, run_id=run_id, force=force)
                    self._send_json({"success": True, "data": job})
                    return
                if parsed.path == "/api/experiment/run/stop":
                    job_id = str(payload.get("job_id", "") or "").strip()
                    if not job_id:
                        raise ValueError("job_id is required")
                    row: dict[str, Any] | None = None
                    with self.server.experiment_jobs_lock:
                        job = self.server.experiment_jobs.get(job_id)
                        if not job:
                            raise ValueError(f"job not found: {job_id}")
                        status = str(job.get("status", "") or "").lower()
                        if status not in EXPERIMENT_TERMINAL_STATUSES:
                            now_ms = int(time.time() * 1000)
                            job["cancelled"] = True
                            job["cancel_requested_at_ms"] = int(job.get("cancel_requested_at_ms", 0) or now_ms)
                            job["status"] = "cancelling"
                            job["stage"] = "cancelling"
                            job["stage_label"] = "正在停止：会在当前 tick 或收尾阶段结束后取消"
                            job["updated_at_ms"] = now_ms
                        self.server.experiment_jobs[job_id] = job
                        row = _experiment_job_row(job)
                    self._send_json({"success": True, "data": row or {"job_id": job_id, "cancelled": True}})
                    return
                if parsed.path == "/api/experiment/run/delete":
                    run_id = str(payload.get("run_id", "") or "").strip()
                    if not run_id:
                        raise ValueError("run_id is required")
                    with self.server.experiment_jobs_lock:
                        active = [
                            j for j in self.server.experiment_jobs.values()
                            if str(j.get("run_id", "") or "") == run_id
                            and str(j.get("status", "") or "") in EXPERIMENT_ACTIVE_STATUSES
                        ]
                    if active:
                        raise ValueError("该运行任务仍在进行中，不能删除。请先停止任务。")
                    result = exp.delete_run(run_id)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/experiment/runs/clear":
                    with self.server.experiment_jobs_lock:
                        keep_run_ids = {
                            str(j.get("run_id", "") or "")
                            for j in self.server.experiment_jobs.values()
                            if str(j.get("status", "") or "") in EXPERIMENT_ACTIVE_STATUSES
                        }
                    result = exp.clear_runs(keep_run_ids=keep_run_ids)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/reload":
                    with self.server.app_lock:
                        result = json.loads(self.server.app.reload_all())
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/config/save":
                    module_name = str(payload.get("module", "")).strip()
                    values = payload.get("values", {}) or {}
                    with self.server.app_lock:
                        result = self.server.app.save_module_config(module_name, values)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/innate_rules/validate":
                    doc = payload.get("doc")
                    yaml_text = payload.get("yaml")
                    with self.server.app_lock:
                        result = self.server.app.validate_innate_rules(doc=doc if isinstance(doc, dict) else None, yaml_text=str(yaml_text) if yaml_text is not None else None)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/innate_rules/save":
                    doc = payload.get("doc")
                    yaml_text = payload.get("yaml")
                    with self.server.app_lock:
                        result = self.server.app.save_innate_rules(doc=doc if isinstance(doc, dict) else None, yaml_text=str(yaml_text) if yaml_text is not None else None)
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/innate_rules/reload":
                    with self.server.app_lock:
                        result = self.server.app.reload_innate_rules()
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/innate_rules/simulate":
                    with self.server.app_lock:
                        result = self.server.app.simulate_innate_rules()
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/action_stop":
                    # Stop/cancel action nodes.
                    # 行动停止/取消接口：用于验收“必须有行动停止接口”的要求。
                    mode = str(payload.get("mode", "") or "action_id")
                    value = payload.get("value")
                    hold_ticks = int(payload.get("hold_ticks", 2) or 0)
                    reason = str(payload.get("reason", "manual_stop") or "manual_stop")
                    with self.server.app_lock:
                        result = self.server.app.stop_action_nodes(
                            mode=mode,
                            value=value,
                            hold_ticks=hold_ticks,
                            reason=reason,
                            trace_id="web_action_stop",
                        )
                    # stop_action_nodes already returns a {success, code, message, data} style payload.
                    self._send_json(result)
                    return
                if parsed.path == "/api/open_report":
                    trace_id = str(payload.get("trace_id", "latest") or "latest")
                    with self.server.app_lock:
                        result = json.loads(self.server.app.open_report(trace_id, open_browser=False))
                    self._send_json({"success": True, "data": result})
                    return
                if parsed.path == "/api/shutdown":
                    self._send_json({"success": True, "data": {"message": "server shutting down"}})
                    _request_server_stop(self.server, force_exit=True)
                    return
                if parsed.path == "/api/restart":
                    result = _schedule_observatory_restart(self.server)
                    self._send_json({"success": True, "data": result})
                    return
                self._send_json({"success": False, "message": "Unknown API path"}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._send_json({"success": False, "message": str(exc)}, status=HTTPStatus.BAD_REQUEST)

        def _serve_static(self, path: str) -> None:
            static_root = self.server.static_dir
            if path == "/next":
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/next/")
                self.end_headers()
                return
            if path == "/agent":
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/agent/")
                self.end_headers()
                return
            if path.startswith("/next/") or path.startswith("/agent/"):
                static_root = self.server.next_static_dir
                route_prefix = "/agent/" if path.startswith("/agent/") else "/next/"
                next_path = path[len(route_prefix) :]
                relative = Path("index.html") if next_path in {"", "/"} else Path(next_path.lstrip("/"))
            elif path in {"", "/"}:
                relative = Path("index.html")
            else:
                relative = Path(path.lstrip("/"))
            file_path = (static_root / relative).resolve()
            try:
                file_path.relative_to(static_root.resolve())
            except ValueError:
                self._send_json({"success": False, "message": "Forbidden"}, status=HTTPStatus.FORBIDDEN)
                return
            if (path.startswith("/next/") or path.startswith("/agent/")) and (not file_path.exists() or not file_path.is_file()):
                # Vite SPA fallback: keep /next/#..., /agent/, and future route paths working.
                fallback = (static_root / "index.html").resolve()
                try:
                    fallback.relative_to(static_root.resolve())
                except ValueError:
                    fallback = file_path
                if fallback.exists() and fallback.is_file():
                    file_path = fallback
            if not file_path.exists() or not file_path.is_file():
                self._send_json({"success": False, "message": "Not found"}, status=HTTPStatus.NOT_FOUND)
                return
            content = file_path.read_bytes()
            mime_type, _ = mimetypes.guess_type(str(file_path))
            content_type = mime_type or "application/octet-stream"
            # Make UTF-8 explicit for text-like assets to avoid garbled Chinese UI strings.
            if "charset=" not in content_type:
                if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"} or content_type.endswith("+xml"):
                    content_type = f"{content_type}; charset=utf-8"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            # Disable caching for static assets during rapid prototype iteration.
            # 原型迭代阶段强制禁用静态资源缓存：避免浏览器缓存旧版 app.js/styles.css，
            # 导致“明明修了但前端看不到”的错觉（例如图形编辑器的删除/缩放按钮）。
            #
            # 说明：
            # - no-store: 浏览器不应缓存任何内容
            # - no-cache + must-revalidate: 即使缓存也必须每次向服务器确认
            # - max-age=0: 立即过期
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def _read_json_body(self) -> dict[str, Any]:
            raw = b""
            transfer_encoding = str(self.headers.get("Transfer-Encoding", "") or "").lower()
            if "chunked" in transfer_encoding:
                chunks: list[bytes] = []
                while True:
                    line = self.rfile.readline(65536)
                    if not line:
                        break
                    size_text = line.split(b";", 1)[0].strip()
                    if not size_text:
                        continue
                    try:
                        size = int(size_text, 16)
                    except ValueError:
                        break
                    if size <= 0:
                        self.rfile.readline(65536)
                        break
                    chunks.append(self.rfile.read(size))
                    self.rfile.readline(65536)
                raw = b"".join(chunks)
            else:
                length = int(self.headers.get("Content-Length", "0") or "0")
                if length <= 0:
                    return {}
                raw = self.rfile.read(length)
            if not raw:
                return {}
            parsed = json.loads(raw.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {"_raw_payload": parsed}

        def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            # NOTE:
            # Browsers may abort connections (tab refresh, navigation, devtools) while the backend
            # is writing a JSON payload. On Windows this commonly surfaces as WinError 10053.
            # This is not a server bug; suppress these noisy exceptions to keep logs clean.
            try:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                # Disable caching for API responses as well.
                # API 响应也禁用缓存，避免前端因缓存看到旧快照。
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

    return ObservatoryHandler


def run_observatory_web(app: ObservatoryApp, *, host: str, port: int, open_browser: bool = True) -> None:
    server = ObservatoryWebServer(host, port, app)
    url = f"http://{host}:{port}/next/"
    print(f"AP Observatory Web UI: {url}")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    finally:
        server.server_close()
        app.close()


def _maybe_int(raw: Any) -> int | None:
    try:
        if raw in {None, "", "null"}:
            return None
        return int(raw)
    except (TypeError, ValueError):
        return None


def _start_llm_review_job(*, server: ObservatoryWebServer, run_id: str, force: bool = False) -> dict[str, Any]:
    run_id = str(run_id or "").strip()
    if not run_id:
        return {"job_id": "", "run_id": "", "success": False, "error": "run_id is empty"}

    cfg = exp.load_review_config()
    if not bool(cfg.enabled):
        return {"job_id": "", "run_id": run_id, "success": False, "error": "LLM review is disabled (config.enabled=false)"}

    # Avoid duplicate concurrent review jobs for the same run unless forced.
    status = exp.read_review_status(run_id=run_id)
    st = str(status.get("status", "") or "")
    if not force and st in {"running", "completed"}:
        return {"job_id": "", "run_id": run_id, "success": True, "skipped": True, "status": st}

    job_id = f"llm_job_{int(time.time() * 1000)}_{threading.get_ident()}"
    job = {
        "job_id": job_id,
        "run_id": run_id,
        "status": "queued",
        "created_at_ms": int(time.time() * 1000),
        "started_at_ms": 0,
        "finished_at_ms": 0,
        "error": "",
        "config": cfg.to_public_dict(),
        "force": bool(force),
    }
    with server.llm_review_jobs_lock:
        server.llm_review_jobs[job_id] = job

    def worker() -> None:
        with server.llm_review_jobs_lock:
            j = server.llm_review_jobs.get(job_id) or {}
            j["status"] = "running"
            j["started_at_ms"] = int(time.time() * 1000)
            server.llm_review_jobs[job_id] = j
        try:
            res = exp.review_run_with_llm(run_id=run_id)
        except Exception as exc:
            res = {"success": False, "error": str(exc)}
        with server.llm_review_jobs_lock:
            j = server.llm_review_jobs.get(job_id) or {}
            j["finished_at_ms"] = int(time.time() * 1000)
            if not res.get("success", False):
                j["status"] = "failed"
                j["error"] = str(res.get("error", "") or res.get("message", "") or "failed")
            else:
                j["status"] = "completed"
                j["error"] = ""
            server.llm_review_jobs[job_id] = j

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id, "run_id": run_id, "success": True, "status": "queued"}


def _latest_llm_review_job_for_run(*, server: ObservatoryWebServer, run_id: str) -> dict[str, Any] | None:
    run_id = str(run_id or "").strip()
    if not run_id:
        return None
    with server.llm_review_jobs_lock:
        matches = [
            dict(job)
            for job in server.llm_review_jobs.values()
            if str(job.get("run_id", "") or "").strip() == run_id
        ]
    if not matches:
        return None
    matches.sort(key=lambda item: int(item.get("created_at_ms", 0) or 0), reverse=True)
    return matches[0]


def _start_auto_tuner_llm_job(
    *,
    server: ObservatoryWebServer,
    run_id: str = "",
    user_prompt: str = "",
    focus_metrics: list[str] | None = None,
) -> dict[str, Any]:
    cfg_info = exp.load_auto_tuner_llm_config()
    cfg_public = cfg_info.get("config", {}) if isinstance(cfg_info, dict) else {}
    if not bool(cfg_public.get("enabled", False)):
        return {"job_id": "", "success": False, "error": "auto_tuner_llm_disabled"}

    job_id = f"auto_tuner_llm_job_{int(time.time() * 1000)}_{threading.get_ident()}"
    job = {
        "job_id": job_id,
        "run_id": str(run_id or "").strip(),
        "status": "queued",
        "created_at_ms": int(time.time() * 1000),
        "started_at_ms": 0,
        "finished_at_ms": 0,
        "error": "",
        "user_prompt": str(user_prompt or ""),
        "focus_metrics": list(focus_metrics or []),
        "config": cfg_public,
    }
    with server.auto_tuner_llm_jobs_lock:
        server.auto_tuner_llm_jobs[job_id] = job

    def worker() -> None:
        with server.auto_tuner_llm_jobs_lock:
            j = server.auto_tuner_llm_jobs.get(job_id) or {}
            j["status"] = "running"
            j["started_at_ms"] = int(time.time() * 1000)
            server.auto_tuner_llm_jobs[job_id] = j
        try:
            res = exp.analyze_auto_tuner_with_llm(
                app=server.app,
                run_id=str(run_id or "").strip(),
                user_prompt=str(user_prompt or ""),
                focus_metrics=list(focus_metrics or []),
            )
        except Exception as exc:
            res = {"success": False, "error": str(exc)}
        with server.auto_tuner_llm_jobs_lock:
            j = server.auto_tuner_llm_jobs.get(job_id) or {}
            j["finished_at_ms"] = int(time.time() * 1000)
            j["result"] = res
            if not res.get("success", False):
                j["status"] = "failed"
                j["error"] = str(res.get("error", "") or res.get("message", "") or "failed")
            else:
                j["status"] = "completed"
                j["error"] = ""
            server.auto_tuner_llm_jobs[job_id] = j

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id, "success": True, "status": "queued"}


def _compact_report_for_web(report: Any) -> Any:
    """
    Compact a report payload for the Web UI.

    Why: In long runs, a single tick report can grow into tens of MB due to
    debug payloads and verbose per-round details. Serializing such payloads on
    every UI refresh will freeze the browser and waste CPU.

    Scope: This is presentation-only. It must not mutate the in-memory report.
    """

    # Tunables (safe defaults for a browser UI).
    max_depth = 8
    max_list_items_default = 180
    max_str_len_default = 2400

    # Per-key tighter caps for known heavy fields.
    max_list_items_by_key = {
        # raw unit/token lists
        "flat_tokens": 260,
        "tokens": 260,
        "units": 140,
        "feature_units": 140,
        "groups": 80,
        "sequence_groups": 60,
        # deep debug + candidates
        "debug": 0,
        "round_details": 8,
        "candidate_details": 12,
        "cam_items": 32,
        # memory feedback items
        "items": 24,
        "events": 24,
        "target_display_texts": 24,
        # snapshots
        "top_items": 40,
        "memory_item_count": 40,
    }
    max_str_len_by_key = {
        "display_text": 1600,
        "grouped_display_text": 1600,
        "semantic_display_text": 1200,
        "semantic_grouped_display_text": 1200,
        "visible_text": 2000,
        "raw": 2000,
        "normalized": 2000,
        "message": 1600,
    }

    def _is_primitive(x: Any) -> bool:
        return x is None or isinstance(x, (bool, int, float, str))

    def _trim_str(s: str, limit: int) -> str:
        if len(s) <= limit:
            return s
        head = s[: max(0, limit - 120)]
        tail = s[-100:] if limit >= 200 else ""
        return f"{head}…(truncated,len={len(s)})…{tail}"

    def _compact(obj: Any, *, depth: int, key: str | None) -> Any:
        if _is_primitive(obj):
            if isinstance(obj, str):
                limit = max_str_len_by_key.get(str(key or ""), max_str_len_default)
                return _trim_str(obj, int(limit))
            return obj
        if depth <= 0:
            return {"_omitted": True, "reason": "max_depth"}

        if isinstance(obj, list):
            limit = max_list_items_by_key.get(str(key or ""), max_list_items_default)
            if limit <= 0:
                return []
            if len(obj) > limit:
                kept = obj[: int(limit)]
                # Marker element so the UI can hint truncation without breaking type.
                # (If the UI doesn't render it, no harm.)
                marker = f"…(truncated {len(obj) - int(limit)} items)…"
                if kept and isinstance(kept[-1], str):
                    kept = list(kept)
                    kept.append(marker)
                return [_compact(x, depth=depth - 1, key=None) for x in kept]
            return [_compact(x, depth=depth - 1, key=None) for x in obj]

        if isinstance(obj, dict):
            out: dict[str, Any] = {}
            for k, v in obj.items():
                kk = str(k)
                if kk == "debug":
                    # Keep compacted round-level debug details for structure/stimulus panels.
                    # These are the primary observability payloads users inspect in the web UI.
                    out[kk] = _compact(v, depth=depth - 1, key=kk)
                    continue
                out[kk] = _compact(v, depth=depth - 1, key=kk)
            return out

        # Fallback for unknown types (shouldn't happen in JSON payloads).
        return str(obj)

    return _compact(report, depth=max_depth, key=None)
