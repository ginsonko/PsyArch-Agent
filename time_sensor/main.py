# -*- coding: utf-8 -*-
"""
AP 时间感受器模块（Time Sensor）— 主模块
=======================================

目标（MVP，先跑通再逐步对齐理论的完整版本）：
  1) 时间差（time delta）：当前时间戳 - 记忆时间戳
  2) 时间桶（time buckets）：用有限数量的区间覆盖连续时间尺度
  3) 双桶赋能（dual-bucket energization）：把一个时间差 t 的能量分配给最接近的两个桶
  4) 输出形式（可配置，可同时启用）：
     - bucket_nodes（时间桶节点层）：
         把“时间桶节点”写入状态池（SP=StatePool/状态池）为有限数量的稳定节点（可匹配、可门控、可触发行动）。
         对齐理论核心 4.2.6 的“基础结构表分段 + 双表赋能/匹配”。
     - bind_attribute（属性绑定层）：
         把“时间感受/时间间隔”作为运行态属性刺激元绑定到具体锚点对象上（例如记忆反哺投影的能量波峰对象），
         便于形成结构与提升可解释性（例如节奏结构示例中的【咚 + 时间间隔：约 1 秒】）。
     注意：二者并不冲突，它们应共享同一套桶体系（bucket_id），只是“表达层级”不同。
     后续由 IESM（先天编码脚本管理器）通过 metric 条件观察“时间桶节点能量/变化”并触发行动（例如 recall 回忆）。

对齐理论核心的对应章节：
  - 4.2.6 时间感受的数值刺激元设计（基础结构表分段 + 双表赋能）
  - 4.2.7 回忆行动与时间感受器（时间感受节点能量超过阈值 -> 触发回忆行动）

实现约束（结合你当前的产品验收口径）：
  - 中文优先；缩写要能在注释里找到中文全称
  - 绝不能让状态池出现“每 tick 新增成百上千对象”的噪音：
    时间桶节点数量必须是固定有限桶数，且 ref_object_id 稳定可合并。
"""

from __future__ import annotations

import math
import os
import re
import time
import traceback
from typing import Any

from hdb._structure_resolver import resolve_or_create_structure_from_profile

from . import __module_name__, __schema_version__, __version__
from ._logger import ModuleLogger


def _load_yaml_config(path: str) -> dict:
    try:
        import yaml  # type: ignore

        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else {}
    except ImportError:
        return {}
    except Exception:
        return {}


TIME_SENSOR_DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    # time_basis / 时间基准开关
    # - wallclock: 使用真实时间戳差（单位：秒）
    # - tick: 使用 tick_id 解析出的 tick_index 差（单位：tick）
    "time_basis": "wallclock",
    # tick_interval_sec / tick 的近似秒数（仅用于展示/兼容，不参与 tick 模式的计算）
    "tick_interval_sec": 1.0,
    "buckets": [
        {"id": "0_25s", "label_zh": "约 0.5 秒内", "min_sec": 0.0, "max_sec": 0.5, "center_sec": 0.25},
        {"id": "1s", "label_zh": "约 1 秒", "min_sec": 0.5, "max_sec": 1.5, "center_sec": 1.0},
        {"id": "3_25s", "label_zh": "约 3 秒", "min_sec": 1.5, "max_sec": 5.0, "center_sec": 3.25},
        {"id": "10s", "label_zh": "约 10 秒", "min_sec": 5.0, "max_sec": 15.0, "center_sec": 10.0},
        {"id": "37_5s", "label_zh": "约 30~60 秒", "min_sec": 15.0, "max_sec": 60.0, "center_sec": 37.5},
        {"id": "180s", "label_zh": "约 3 分钟", "min_sec": 60.0, "max_sec": 300.0, "center_sec": 180.0},
        {"id": "1050s", "label_zh": "约 15 分钟", "min_sec": 300.0, "max_sec": 1800.0, "center_sec": 1050.0},
        {"id": "3600s", "label_zh": "约 1 小时", "min_sec": 1800.0, "max_sec": 7200.0, "center_sec": 3600.0},
        {"id": "21600s", "label_zh": "约 6 小时", "min_sec": 7200.0, "max_sec": 86400.0, "center_sec": 21600.0},
        {"id": "86400s", "label_zh": "约 1 天", "min_sec": 86400.0, "max_sec": 172800.0, "center_sec": 86400.0},
    ],
    # tick_buckets / tick 时间桶（用于 time_basis=tick）
    # 说明：字段名沿用 *_sec 是为了减少结构变更；在 tick 模式下它们表示 “tick 单位”。
    "tick_buckets": [
        {"id": "0_5t", "label_zh": "约 1 tick 内", "min_sec": 0.0, "max_sec": 1.0, "center_sec": 0.5},
        {"id": "1_5t", "label_zh": "约 2 tick", "min_sec": 1.0, "max_sec": 2.0, "center_sec": 1.5},
        {"id": "3t", "label_zh": "约 3 tick", "min_sec": 2.0, "max_sec": 4.0, "center_sec": 3.0},
        {"id": "6t", "label_zh": "约 6 tick", "min_sec": 4.0, "max_sec": 8.0, "center_sec": 6.0},
        {"id": "12t", "label_zh": "约 12 tick", "min_sec": 8.0, "max_sec": 16.0, "center_sec": 12.0},
        {"id": "24t", "label_zh": "约 24 tick", "min_sec": 16.0, "max_sec": 32.0, "center_sec": 24.0},
        {"id": "48t", "label_zh": "约 48 tick", "min_sec": 32.0, "max_sec": 64.0, "center_sec": 48.0},
        {"id": "96t", "label_zh": "约 96 tick", "min_sec": 64.0, "max_sec": 128.0, "center_sec": 96.0},
    ],
    "source_mode": "runtime_memory_projection",
    "memory_top_k": 12,
    "energy_gain_ratio": 0.14,
    # base_energy_source / 时间感受赋能的能量来源口径
    # - total_energy: 使用 MAP 条目的当前总能量（更“粘”，可能导致时间感受每 tick 都持续出现）
    # - last_delta_energy: 使用 MAP 条目的最近增量（更贴近“被重新接触/被赋能”的语义，且更不易形成回忆正反馈）
    "base_energy_source": "last_delta_energy",
    "energy_key": "ev",  # "ev" (虚能量) or "er" (实能量)
    "min_bucket_energy": 0.02,
    # ---- delayed energization tasks (theory 4.2.8) / 延迟赋能任务表（理论 4.2.8）----
    "enable_delayed_tasks": True,
    "delayed_task_capacity": 48,
    "delayed_task_register_min_delta_energy": 0.30,
    "delayed_task_fatigue_ticks": 4,
    "delayed_task_fatigue_ms": 800,
    "delayed_task_min_interval_sec": 0.5,
    "delayed_task_min_interval_ticks": 2,
    "delayed_task_due_tolerance_sec": 0.15,
    "delayed_task_due_tolerance_ticks": 0,
    "delayed_task_energy_key": "ev",
    "delayed_task_energy_ratio": 0.65,
    "delayed_task_energy_min": 0.06,
    "delayed_task_energy_max": 0.85,
    # enable_bucket_nodes / 是否写入“时间桶节点”（桶节点层）
    # Chinese: true 表示把固定数量的时间桶作为稳定 SA 写入状态池，并给其赋能（双桶分配）。
    # English: When true, write stable bucket nodes into StatePool and energize them (dual-bucket distribution).
    "enable_bucket_nodes": False,
    # enable_bind_attribute / 是否执行“时间感受属性绑定”（属性绑定层）
    # Chinese: true 表示把时间感受作为属性刺激元绑定到具体锚点对象上（更贴近“约束/标记”语义）。
    # English: When true, bind time-feeling as an attribute SA to peak target objects for interpretability.
    "enable_bind_attribute": True,
    # output_mode / 旧版兼容字段（deprecated）
    # - bucket_nodes: 仅写入时间桶节点
    # - bind_attribute: 仅执行属性绑定
    # - both: 二者都启用
    # 说明：当 enable_bucket_nodes/enable_bind_attribute 其中任一被显式设置为 bool 时，
    #      本字段将仅作为“默认回退”使用。
    "output_mode": "bind_attribute",
    # attribute_name / 绑定到对象上的属性名（用于 contains_text 触发、前端展示）
    "attribute_name": "时间感受",
    # max_bind_targets_per_memory / 每条记忆最多绑定到几个“能量波峰对象”
    "max_bind_targets_per_memory": 2,
    # peak_keep_ratio / 波峰保留比例（>= max_delta * ratio 的目标会被视为“同一波峰”）
    "peak_keep_ratio": 0.72,
    # max_total_bindings / 单 tick 最大绑定条数（安全刹车，防止 MAP 爆炸时刷屏）
    "max_total_bindings": 12,
    # enable_projection_target_bindings / 是否额外把“结构投影目标”也纳入时间感受绑定候选
    # - false: 仅沿用旧版“记忆反馈事件峰值目标”绑定路径
    # - true: 在旧路径之外，额外为每条记忆挑选少量 structure projection 目标做镜像绑定
    #         用于把时间感受更稳定地挂到高阶结构对象上，避免长期只停留在 A/B/X 这类底层原子结构。
    "enable_projection_target_bindings": True,
    # enable_runtime_snapshot_target_bindings / runtime-em 主链是否直接从 memory snapshot 提取结构目标
    # - false: 仍主要依赖 memory_feedback_result / synthetic projection stub
    # - true: 当主链是 runtime_memory_projection 时，直接依据 memory_activation_snapshot.backing_structure_ids 绑定时间感受
    #         这样时间感受主链就不再依赖专门记忆池回流结果。
    "enable_runtime_snapshot_target_bindings": True,
    # runtime_snapshot_target_richness_bias_enabled / runtime-em 目标选择是否偏向更“整体”的结构
    # - true: backing_structure_ids 同时包含原子结构与父结构时，不再平均后按列表顺序取第一个；
    #         会结合结构复杂度与当前活跃能量，把时间感受优先挂到更高阶、更有代表性的结构上。
    # - false: 保留旧版“平均分 + 顺序打平”口径。
    "runtime_snapshot_target_richness_bias_enabled": True,
    # runtime_snapshot_target_complexity_bonus_per_token / 每多 1 个 token 带来的 richness 加成
    "runtime_snapshot_target_complexity_bonus_per_token": 0.45,
    # runtime_snapshot_target_group_bonus / 每多 1 个 sequence_group 带来的 richness 加成
    "runtime_snapshot_target_group_bonus": 0.15,
    # runtime_snapshot_target_runtime_attr_bonus / 运行态绑定属性数量带来的 richness 加成
    "runtime_snapshot_target_runtime_attr_bonus": 0.08,
    # max_projection_bind_targets_per_memory / 每条记忆最多额外镜像绑定几个 structure projection 目标
    "max_projection_bind_targets_per_memory": 1,
    # projection_target_keep_ratio / structure projection 波峰保留比例
    # 说明：与 peak_keep_ratio 逻辑一致，但单独可调，便于保守放开高阶结构绑定。
    "projection_target_keep_ratio": 0.72,
    # time_factor_stripped_projection_context_free_identity_enabled / 去时间因子结构使用无上下文身份
    "time_factor_stripped_projection_context_free_identity_enabled": True,
    "node_id_prefix": "sa_time_bucket_",
    "node_display_prefix": "时间感受",
    # ---- logging ----
    "log_dir": "",
    "log_max_file_bytes": 5 * 1024 * 1024,
    "stdout_fallback_when_log_fail": True,
}


class TimeSensor:
    """
    时间感受器（Time Sensor）。

    说明：
      - 当前原型只负责“生成时间感受并写入状态池/绑定到对象”，不直接触发行动；
        触发回忆等行动应由 IESM（先天规则）显式描述并输出 action_trigger。
      - 未来扩展（理论 4.2.8）：延迟赋能任务表/任务式生物钟能力，可在本模块内实现。
    """

    def __init__(self, config_path: str = "", config_override: dict | None = None):
        self._config_path = config_path or os.path.join(os.path.dirname(__file__), "config", "time_sensor_config.yaml")
        self._config = self._build_config(config_override)
        self._logger = ModuleLogger(
            log_dir=str(self._config.get("log_dir", "")),
            max_file_bytes=int(self._config.get("log_max_file_bytes", 0) or 0),
            enable_stdout_fallback=bool(self._config.get("stdout_fallback_when_log_fail", True)),
        )
        self._tick_counter = 0
        self._last_tick_report: dict[str, Any] | None = None
        # Delayed energization tasks (theory 4.2.8) / 延迟赋能任务表（理论 4.2.8）
        # - key: task_key = "{task_kind}::{target_identity}"
        self._delayed_tasks: dict[str, dict[str, Any]] = {}
        # Short-term fatigue after execution (avoid immediate re-trigger) / 执行后短时疲劳（避免立刻重复触发）
        self._task_fatigue_until_tick: dict[str, int] = {}
        self._task_fatigue_until_ms: dict[str, int] = {}

    def close(self) -> None:
        try:
            self._logger.close()
        except Exception:
            pass

    def clear_runtime_state(self, trace_id: str = "", reason: str = "runtime_reset") -> dict[str, Any]:
        start = time.time()
        result = {
            "cleared_delayed_task_count": len(self._delayed_tasks),
            "cleared_task_fatigue_tick_count": len(self._task_fatigue_until_tick),
            "cleared_task_fatigue_ms_count": len(self._task_fatigue_until_ms),
            "had_last_tick_report": self._last_tick_report is not None,
            "tick_counter_before": int(self._tick_counter),
        }
        self._tick_counter = 0
        self._last_tick_report = None
        self._delayed_tasks.clear()
        self._task_fatigue_until_tick.clear()
        self._task_fatigue_until_ms.clear()
        return self._make_response(
            True,
            "OK",
            f"时间感受器运行态已清空 / Time sensor runtime cleared ({reason})",
            data=result,
            trace_id=trace_id,
            elapsed_ms=self._elapsed_ms(start),
        )

    def _build_config(self, config_override: dict | None = None) -> dict[str, Any]:
        config = dict(TIME_SENSOR_DEFAULT_CONFIG)
        config.update(_load_yaml_config(self._config_path))
        if config_override:
            config.update(config_override)
        return config

    def reload_config(
        self,
        trace_id: str = "",
        config_path: str | None = None,
        apply_partial: bool = True,
    ) -> dict[str, Any]:
        """
        热加载配置（支持 partial patch）

        说明:
        - 自适应调参器（AutoTuner）需要在不修改仓库追踪配置文件的情况下，
          通过临时 patch 文件热更新 TimeSensor 的少量参数。
        - 因此这里提供与其它模块一致的 reload_config 接口:
            reload_config(trace_id, config_path=None, apply_partial=True)
          其中 config_path 允许指向一个只包含少量键的 YAML patch。
        """
        start = time.time()
        path = str(config_path or self._config_path)
        try:
            new_raw = _load_yaml_config(path)
            if not new_raw:
                return self._make_response(
                    False,
                    "CONFIG_ERROR",
                    f"配置文件加载失败或为空 / Config file failed to load or empty: {path}",
                    data={},
                    trace_id=trace_id,
                    elapsed_ms=self._elapsed_ms(start),
                )

            applied: list[str] = []
            rejected: list[dict[str, Any]] = []
            for key, val in new_raw.items():
                if key not in TIME_SENSOR_DEFAULT_CONFIG:
                    rejected.append({"key": key, "reason": "未知配置项 / Unknown config key"})
                    continue
                expected_type = type(TIME_SENSOR_DEFAULT_CONFIG[key])
                if isinstance(val, expected_type) or (expected_type is float and isinstance(val, (int, float))):
                    self._config[key] = val
                    applied.append(str(key))
                else:
                    rejected.append(
                        {
                            "key": key,
                            "reason": f"类型不匹配 / Type mismatch: expected {expected_type.__name__}, got {type(val).__name__}",
                        }
                    )

            self._logger.update_config(
                log_dir=str(self._config.get("log_dir", "")),
                max_file_bytes=int(self._config.get("log_max_file_bytes", 0) or 0),
            )

            if rejected and not apply_partial:
                return self._make_response(
                    False,
                    "CONFIG_ERROR",
                    f"部分配置项被拒绝 / Some config items rejected: {len(rejected)}",
                    data={"applied": applied, "rejected": rejected},
                    trace_id=trace_id,
                    elapsed_ms=self._elapsed_ms(start),
                )

            return self._make_response(
                True,
                "OK",
                f"热加载完成 / Hot reload done: {len(applied)} applied, {len(rejected)} rejected",
                data={
                    "config_path": path,
                    "enabled": bool(self._config.get("enabled", True)),
                    "applied": applied,
                    "rejected": rejected,
                },
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start),
            )
        except Exception as exc:
            self._logger.error(
                trace_id=trace_id,
                tick_id="",
                interface="reload_config",
                code="CONFIG_ERROR",
                message=f"热加载异常 / Hot reload exception: {exc}",
                detail={"traceback": traceback.format_exc()},
            )
            return self._make_response(
                False,
                "CONFIG_ERROR",
                f"热加载失败 / Hot reload failed: {exc}",
                data={},
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start),
            )

    def get_runtime_snapshot(self, trace_id: str = "") -> dict[str, Any]:
        return self._make_response(
            True,
            "OK",
            "时间感受器运行态快照 / Time sensor runtime snapshot",
            data={
                "module": __module_name__,
                "version": __version__,
                "schema_version": __schema_version__,
                "tick_counter": self._tick_counter,
                "config_path": self._config_path,
                "config": dict(self._config),
                "last_tick_report": self._last_tick_report or {},
            },
            trace_id=trace_id,
            elapsed_ms=0,
        )

    # ================================================================== #
    # Main tick interface                                                 #
    # ================================================================== #

    def run_time_feeling_tick(
        self,
        *,
        pool: Any,
        hdb: Any | None = None,
        trace_id: str,
        tick_id: str,
        now_ms: int | None = None,
        memory_activation_snapshot: dict | None = None,
        memory_feedback_result: dict | None = None,
        source_mode: str | None = None,
    ) -> dict[str, Any]:
        """
        主入口：根据“被重新接触到的记忆”生成时间感受桶，并对状态池节点赋能。

        参数：
          - pool: 状态池对象（StatePool, SP），需要提供：
              - _store.get_by_ref(ref_id) -> state_item | None
              - apply_energy_update(...)
              - insert_runtime_node(...)
          - memory_activation_snapshot: 记忆快照；可来自 HDB 的 MAP，也可来自 StatePool 内 em 运行态整理视图

        返回：
          - time_feelings: 时间桶赋能详情（供观测台展示）
          - pool_events: 对状态池的写入摘要（insert/update）
        """
        start = time.time()
        self._tick_counter += 1
        now_ms = int(now_ms or (time.time() * 1000))

        effective_source_mode = str(
            source_mode or self._config.get("source_mode", "memory_activation_snapshot") or "memory_activation_snapshot"
        ).strip().lower()
        if effective_source_mode not in {"memory_activation_snapshot", "runtime_memory_projection"}:
            effective_source_mode = "memory_activation_snapshot"

        if not bool(self._config.get("enabled", True)):
            out = {
                "now_ms": now_ms,
                "enabled": False,
                "bucket_updates": [],
                "pool_events": [],
                "note": "时间感受器已禁用 / disabled",
            }
            self._last_tick_report = out
            return self._make_response(True, "OK_DISABLED", "时间感受器已禁用 / disabled", data=out, trace_id=trace_id, elapsed_ms=self._elapsed_ms(start))

        # ---- Resolve time basis (wallclock vs tick) / 解析时间基准开关 ----
        time_basis = str(self._config.get("time_basis", "wallclock") or "wallclock").strip().lower() or "wallclock"
        if time_basis in {"tick", "ticks"}:
            time_basis = "tick"
        else:
            time_basis = "wallclock"

        tick_index = self._parse_tick_index(tick_id)
        if time_basis == "tick" and tick_index is None:
            # Fallback to wallclock when tick_index cannot be parsed.
            # tick_id 无法解析 tick_index 时回退到 wallclock，避免混乱输出。
            time_basis = "wallclock"

        bucket_key = "tick_buckets" if time_basis == "tick" else "buckets"
        buckets = self._normalized_buckets(bucket_key)
        if not buckets:
            self._logger.error(trace_id=trace_id, tick_id=tick_id, interface="run_time_feeling_tick", code="CONFIG_ERROR", message="时间桶 buckets 为空", detail={})
            return self._make_response(False, "CONFIG_ERROR", "时间桶 buckets 为空 / empty buckets", data={}, trace_id=trace_id, elapsed_ms=self._elapsed_ms(start))

        # ---- Step 1: execute due delayed tasks (theory 4.2.8) / 执行到期的延迟赋能任务 ----
        delayed_report = self._execute_due_delayed_tasks(
            pool=pool,
            hdb=hdb,
            trace_id=trace_id,
            tick_id=tick_id,
            now_ms=now_ms,
            time_basis=time_basis,
            tick_index=int(tick_index) if tick_index is not None else None,
        )

        # ---- Step 2: collect memory candidates / 收集记忆候选 ----
        memory_activation_snapshot = memory_activation_snapshot or {}
        items = list(memory_activation_snapshot.get("items", []) or [])
        items = [it for it in items if isinstance(it, dict)]
        items.sort(key=lambda x: float(x.get("total_energy", 0.0) or 0.0), reverse=True)
        top_k = int(self._config.get("memory_top_k", 16) or 16)
        top_k = max(1, min(128, top_k))
        items = items[:top_k]

        gain_ratio = float(self._config.get("energy_gain_ratio", 0.18) or 0.18)
        gain_ratio = max(0.0, min(2.0, gain_ratio))
        base_energy_source = str(self._config.get("base_energy_source", "total_energy") or "total_energy").strip().lower() or "total_energy"
        energy_key = str(self._config.get("energy_key", "ev") or "ev").strip().lower() or "ev"
        energy_key = "er" if energy_key == "er" else "ev"
        min_bucket_energy = float(self._config.get("min_bucket_energy", 0.02) or 0.02)
        min_bucket_energy = max(0.0, min(10.0, min_bucket_energy))

        def _resolve_source_energy(it: dict) -> float:
            """Pick the energy base used for time-feeling generation / 选择时间感受赋能的能量基准口径。"""
            if base_energy_source in {"last_delta_energy", "last_delta", "delta"}:
                try:
                    de = float(it.get("last_delta_er", 0.0) or 0.0) + float(it.get("last_delta_ev", 0.0) or 0.0)
                except Exception:
                    de = 0.0
                return max(0.0, float(de))
            try:
                te = float(it.get("total_energy", 0.0) or 0.0)
            except Exception:
                te = 0.0
            return max(0.0, float(te))

        def _collect_runtime_snapshot_target_scores() -> dict[str, dict[str, float]]:
            score_map: dict[str, dict[str, float]] = {}
            if not bool(self._config.get("enable_runtime_snapshot_target_bindings", True)):
                return score_map
            for memory_item in items:
                if not isinstance(memory_item, dict):
                    continue
                memory_id = str(memory_item.get("memory_id", "") or "").strip()
                if not memory_id:
                    continue
                backing_ids_raw: list[str] = []
                for field_name in ("backing_structure_ids", "structure_refs", "source_structure_ids"):
                    for value in list(memory_item.get(field_name, []) or []):
                        text = str(value or "").strip()
                        if text:
                            backing_ids_raw.append(text)
                for field_name in ("structure_ref_items", "backing_structure_items", "source_structure_items"):
                    for ref_item in list(memory_item.get(field_name, []) or []):
                        if not isinstance(ref_item, dict):
                            continue
                        for key in ("id", "structure_id", "ref_object_id"):
                            text = str(ref_item.get(key, "") or "").strip()
                            if text:
                                backing_ids_raw.append(text)
                                break
                backing_ids = list(dict.fromkeys(backing_ids_raw))
                if not backing_ids:
                    continue
                weighted_targets: list[tuple[str, float]] = []
                for backing_id in backing_ids:
                    try:
                        target_item = pool._store.get_by_ref(backing_id)  # type: ignore[attr-defined]
                    except Exception:
                        target_item = None
                    if not isinstance(target_item, dict):
                        continue
                    target_item_id = str(target_item.get("id", "") or "").strip()
                    if target_item_id:
                        weighted_targets.append(
                            (
                                target_item_id,
                                self._runtime_snapshot_target_richness_weight(target_item),
                            )
                        )
                weighted_targets = self._dedupe_runtime_snapshot_weighted_targets(weighted_targets)
                if not weighted_targets:
                    continue
                score_base = _resolve_source_energy(memory_item)
                if score_base <= 0.0:
                    continue
                weight_total = sum(float(weight or 0.0) for _, weight in weighted_targets)
                if weight_total <= 0.0:
                    continue
                score_map.setdefault(memory_id, {})
                for target_item_id, target_weight in weighted_targets:
                    score_share = round(float(score_base) * max(0.0, float(target_weight or 0.0)) / float(weight_total), 8)
                    if score_share <= 0.0:
                        continue
                    score_map[memory_id][target_item_id] = round(
                        float(score_map[memory_id].get(target_item_id, 0.0) or 0.0) + score_share,
                        8,
                    )
            return score_map

        # ---- Step 3: accumulate bucket energies / 汇总每个桶的能量 ----
        bucket_energy: dict[str, float] = {b["id"]: 0.0 for b in buckets}
        mem_rows: list[dict[str, Any]] = []

        for it in items:
            # Prefer the episodic memory timestamp if available.
            # 优先使用“记忆本身时间戳”（对齐理论 4.2.6.3），否则回退到 MAP 条目时间戳。
            memory_created_at = int(it.get("memory_created_at", it.get("created_at", 0)) or 0)
            map_created_at = int(it.get("created_at", 0) or 0)
            if memory_created_at <= 0 and time_basis == "wallclock":
                continue

            dt_value: float | None = None
            dt_unit = "s"
            if time_basis == "tick":
                # tick delta: current_tick_index - memory_tick_index
                dt_unit = "tick"
                cur_tick = int(tick_index or 0)
                mem_tick = int(it.get("memory_tick_index", 0) or 0)
                if mem_tick <= 0:
                    # Fallback: parse from memory_tick_id if provided.
                    mem_tick_id = str(it.get("memory_tick_id", "") or "")
                    parsed = self._parse_tick_index(mem_tick_id)
                    mem_tick = int(parsed or 0)
                if mem_tick <= 0 and memory_created_at > 0:
                    # Best-effort fallback to wallclock delta when tick data is missing.
                    # tick 信息缺失时尽力回退到 wallclock（避免完全无输出）。
                    dt_unit = "s"
                    dt_value = max(0.0, float(now_ms - memory_created_at) / 1000.0)
                else:
                    dt_value = max(0.0, float(cur_tick - mem_tick))
            else:
                dt_unit = "s"
                dt_value = max(0.0, float(now_ms - memory_created_at) / 1000.0)

            if dt_value is None:
                continue
            src_energy = _resolve_source_energy(it)
            base = max(0.0, float(src_energy)) * gain_ratio
            if base <= 0.0:
                continue

            b1, w1, b2, w2 = self._dual_bucket_weights(buckets, float(dt_value))
            if b1:
                bucket_energy[b1] = float(bucket_energy.get(b1, 0.0) or 0.0) + float(base) * float(w1)
            if b2 and b2 != b1:
                bucket_energy[b2] = float(bucket_energy.get(b2, 0.0) or 0.0) + float(base) * float(w2)

            mem_rows.append(
                {
                    "memory_id": str(it.get("memory_id", it.get("id", "")) or ""),
                    "display_text": str(it.get("display_text", "") or it.get("event_summary", "") or ""),
                    # Keep both for audit / 同时保留两套时间戳便于审计
                    "created_at": memory_created_at,
                    "memory_created_at": memory_created_at,
                    "map_created_at": map_created_at,
                    "delta_unit": dt_unit,
                    # Backward compatible field name: delta_sec (may actually be tick delta when time_basis=tick).
                    # 向后兼容字段名：delta_sec（time_basis=tick 时它表示 tick 差值）。
                    "delta_sec": round(float(dt_value), 3),
                    "delta_value": round(float(dt_value), 3),
                    "total_energy": round(float(it.get("total_energy", 0.0) or 0.0), 6),
                    "base_energy_source": base_energy_source,
                    "source_energy": round(float(src_energy), 6),
                    "time_feeling_energy": round(base, 6),
                    "bucket_1": b1,
                    "w1": round(float(w1), 4),
                    "bucket_2": b2,
                    "w2": round(float(w2), 4),
                }
            )

        # ---- Step 4: output to StatePool / 输出到状态池 ----
        # 说明（对齐理论核心 4.2.6~4.2.9）：
        # - 时间桶节点层（bucket_nodes）：有限桶 + 双桶赋能/匹配，是行动门控与脚本条件的稳定入口；
        # - 属性绑定层（bind_attribute）：把时间感受挂到具体锚点对象上，便于结构形成与可解释性；
        # 二者可同时启用，且应共享同一套桶体系（bucket_id）。
        out_flags = self._resolve_output_flags()
        enable_bucket_nodes = bool(out_flags.get("enable_bucket_nodes", False))
        enable_bind_attribute = bool(out_flags.get("enable_bind_attribute", False))
        output_mode = str(out_flags.get("output_mode", "") or "")

        node_prefix = str(self._config.get("node_id_prefix", "sa_time_bucket_") or "sa_time_bucket_")
        display_prefix = str(self._config.get("node_display_prefix", "时间感受") or "时间感受").strip() or "时间感受"
        attr_name = str(self._config.get("attribute_name", "时间感受") or "时间感受").strip() or "时间感受"

        pool_events: list[dict[str, Any]] = []
        bucket_updates: list[dict[str, Any]] = []
        attribute_bindings: list[dict[str, Any]] = []
        # Include delayed-task execution events in pool_events for unified audit.
        # 把延迟任务执行事件合并进 pool_events（统一审计口径）。
        for ev in list((delayed_report.get("pool_events", []) or [])):
            if isinstance(ev, dict):
                pool_events.append(ev)

        bucket_by_id = {str(b.get("id", "") or ""): dict(b) for b in buckets if str(b.get("id", "") or "")}

        # (A) Always emit bucket summary for observability / 无论输出模式都输出桶能量汇总（便于验收）
        for b in buckets:
            bid = str(b.get("id", "") or "")
            if not bid:
                continue
            e = float(bucket_energy.get(bid, 0.0) or 0.0)
            if e < min_bucket_energy:
                continue
            label_zh = str(b.get("label_zh", bid) or bid)
            center_sec = float(b.get("center_sec", 0.0) or 0.0)
            min_sec = float(b.get("min_sec", 0.0) or 0.0)
            max_sec = float(b.get("max_sec", 0.0) or 0.0)
            bucket_updates.append(
                {
                    "bucket_id": bid,
                    "label_zh": label_zh,
                    "center_sec": center_sec,
                    "range_sec": [min_sec, max_sec],
                    "unit": "tick" if time_basis == "tick" else "s",
                    "assigned_energy": round(e, 6),
                    "energy_key": energy_key,
                }
            )

        if enable_bucket_nodes:
            # ------------------------------------------------------------
            # Mode 1: bucket_nodes / 时间桶节点写入 SP
            # ------------------------------------------------------------
            for row in bucket_updates:
                bid = str(row.get("bucket_id", "") or "")
                e = float(row.get("assigned_energy", 0.0) or 0.0)
                if not bid or e < min_bucket_energy:
                    continue

                b = bucket_by_id.get(bid, {})
                ref_id = f"{node_prefix}{bid}"
                label_zh = str(b.get("label_zh", bid) or bid)
                center_sec = float(b.get("center_sec", 0.0) or 0.0)
                min_sec = float(b.get("min_sec", 0.0) or 0.0)
                max_sec = float(b.get("max_sec", 0.0) or 0.0)

                runtime_sa = {
                    "id": ref_id,
                    "object_type": "sa",
                    "schema_version": __schema_version__,
                    "content": {
                        "raw": f"{display_prefix}:{label_zh}",
                        "display": f"{display_prefix}：【{label_zh}】",
                        "normalized": f"{display_prefix}|{label_zh}|center_sec={center_sec}|range_sec={min_sec}~{max_sec}",
                        "value_type": "numerical",
                    },
                    "stimulus": {
                        "role": "time_feeling",
                    },
                    "meta": {
                        "ext": {
                            "time_bucket": {"id": bid, "center_sec": center_sec, "min_sec": min_sec, "max_sec": max_sec},
                        }
                    },
                    "energy": {"er": 0.0, "ev": 0.0},
                }

                delta_er = float(e) if energy_key == "er" else 0.0
                delta_ev = float(e) if energy_key == "ev" else 0.0
                runtime_sa["energy"]["er"] = round(delta_er, 8)
                runtime_sa["energy"]["ev"] = round(delta_ev, 8)

                existing = None
                try:
                    existing = pool._store.get_by_ref(ref_id)  # type: ignore[attr-defined]
                except Exception:
                    existing = None

                if existing and isinstance(existing, dict) and str(existing.get("id", "")):
                    try:
                        res = pool.apply_energy_update(  # type: ignore[attr-defined]
                            target_item_id=str(existing.get("id", "")),
                            delta_er=float(delta_er),
                            delta_ev=float(delta_ev),
                            trace_id=trace_id,
                            tick_id=tick_id,
                            reason="time_feeling_bucket_energy",
                            source_module=__module_name__,
                            allow_create_if_missing=False,
                            extra_context={"time_bucket_id": bid, "time_bucket_label_zh": label_zh, "center_sec": center_sec},
                        )
                        pool_events.append(
                            {
                                "op": "update",
                                "ref_id": ref_id,
                                "target_item_id": str(existing.get("id", "")),
                                "delta_er": round(delta_er, 6),
                                "delta_ev": round(delta_ev, 6),
                                "code": res.get("code", ""),
                            }
                        )
                    except Exception as exc:
                        pool_events.append({"op": "update", "ref_id": ref_id, "error": str(exc)})
                else:
                    try:
                        res = pool.insert_runtime_node(  # type: ignore[attr-defined]
                            runtime_object=runtime_sa,
                            trace_id=trace_id,
                            tick_id=tick_id,
                            allow_merge=True,
                            source_module=__module_name__,
                            reason="time_feeling_bucket_energy",
                        )
                        data = res.get("data", {}) if isinstance(res, dict) else {}
                        pool_events.append(
                            {
                                "op": "insert",
                                "ref_id": ref_id,
                                "delta_er": round(delta_er, 6),
                                "delta_ev": round(delta_ev, 6),
                                "inserted": bool(data.get("inserted", False)),
                                "merged": bool(data.get("merged", False)),
                                "target_item_id": str(data.get("item_id", data.get("target_item_id", "")) or ""),
                                "code": res.get("code", "") if isinstance(res, dict) else "",
                            }
                        )
                    except Exception as exc:
                        pool_events.append({"op": "insert", "ref_id": ref_id, "error": str(exc)})

                # Carry ref_id for UI when in bucket_nodes mode.
                row["ref_object_id"] = ref_id

        if enable_bind_attribute:
            # ------------------------------------------------------------
            # Mode 2: bind_attribute / 绑定到能量波峰对象
            # ------------------------------------------------------------
            # 关键点：
            # - 时间桶节点（bucket_nodes）是“有限域的数值刺激元承载层”（用于匹配与门控）；
            # - 属性绑定（bind_attribute）是“把时间感受作为约束/标记挂到具体对象上”（用于结构与解释）；
            # 二者是互补的表达层，不冲突。

            # ---- Build per-memory bucket summary / 每条记忆的桶摘要（用于属性绑定展示） ----
            # 说明：
            # - 时间感受本质是“数值刺激元”，理论要求双桶赋能/匹配；
            # - 绑定到具体锚点对象上时，为了可读性，默认展示“主桶”，并在 meta 中保留双桶信息。
            mem_time: dict[str, dict[str, Any]] = {}
            for it in items:
                memory_id = str(it.get("memory_id", it.get("id", "")) or "").strip()
                if not memory_id:
                    continue
                memory_created_at = int(it.get("memory_created_at", it.get("created_at", 0)) or 0)
                if memory_created_at <= 0:
                    continue

                dt_value: float | None = None
                dt_unit = "s"
                if time_basis == "tick":
                    dt_unit = "tick"
                    cur_tick = int(tick_index or 0)
                    mem_tick = int(it.get("memory_tick_index", 0) or 0)
                    if mem_tick <= 0:
                        mem_tick_id = str(it.get("memory_tick_id", "") or "")
                        parsed = self._parse_tick_index(mem_tick_id)
                        mem_tick = int(parsed or 0)
                    if mem_tick <= 0:
                        # Fallback to wallclock if tick is missing.
                        dt_unit = "s"
                        dt_value = max(0.0, float(now_ms - memory_created_at) / 1000.0)
                    else:
                        dt_value = max(0.0, float(cur_tick - mem_tick))
                else:
                    dt_unit = "s"
                    dt_value = max(0.0, float(now_ms - memory_created_at) / 1000.0)

                if dt_value is None:
                    continue
                src_energy = _resolve_source_energy(it)
                base = max(0.0, float(src_energy)) * gain_ratio
                if base <= 0.0:
                    continue
                b1, w1, b2, w2 = self._dual_bucket_weights(buckets, float(dt_value))

                # Determine primary/secondary bucket for display.
                # 选择“主桶/副桶”：用于展示与属性绑定，但仍保留双桶信息。
                primary_id = str(b1 or "")
                primary_w = float(w1 or 0.0)
                secondary_id = str(b2 or "")
                secondary_w = float(w2 or 0.0)
                if secondary_id and secondary_w > primary_w:
                    primary_id, secondary_id = secondary_id, primary_id
                    primary_w, secondary_w = secondary_w, primary_w
                if secondary_id == primary_id:
                    secondary_id = ""
                    secondary_w = 0.0

                pmeta = bucket_by_id.get(primary_id, {}) if primary_id else {}
                smeta = bucket_by_id.get(secondary_id, {}) if secondary_id else {}
                mem_time[memory_id] = {
                    "memory_id": memory_id,
                    "display_text": str(it.get("display_text", "") or it.get("event_summary", "") or ""),
                    "created_at": memory_created_at,
                    "delta_unit": dt_unit,
                    # Backward compatible: delta_sec may represent tick delta when time_basis=tick.
                    "delta_sec": round(float(dt_value), 3),
                    "delta_value": round(float(dt_value), 3),
                    "base_energy_source": base_energy_source,
                    "source_energy": round(float(src_energy), 6),
                    "time_feeling_energy": round(float(base), 6),
                    # Primary bucket for display / 主桶（用于展示）
                    "bucket_id": primary_id,
                    "bucket_label_zh": str(pmeta.get("label_zh", primary_id) or primary_id or ""),
                    "bucket_center_sec": float(pmeta.get("center_sec", 0.0) or 0.0),
                    "bucket_weight": round(float(primary_w), 4),
                    # Secondary bucket (kept for audit) / 副桶（用于审计/调试）
                    "bucket_secondary_id": secondary_id,
                    "bucket_secondary_label_zh": str(smeta.get("label_zh", secondary_id) or secondary_id or ""),
                    "bucket_secondary_center_sec": float(smeta.get("center_sec", 0.0) or 0.0),
                    "bucket_secondary_weight": round(float(secondary_w), 4),
                    # Raw dual-bucket result / 原始双桶结果（与 mem_rows 口径对齐）
                    "bucket_1": str(b1 or ""),
                    "w1": round(float(w1 or 0.0), 4),
                    "bucket_2": str(b2 or ""),
                    "w2": round(float(w2 or 0.0), 4),
                    "time_basis": time_basis,
                }

            score_by_mem: dict[str, dict[str, float]] = {}
            projection_scores_by_mem: dict[str, dict[str, float]] = {}
            runtime_snapshot_scores_by_mem: dict[str, dict[str, float]] = {}

            if effective_source_mode == "runtime_memory_projection":
                runtime_snapshot_scores_by_mem = _collect_runtime_snapshot_target_scores()
            else:
                # ---- Parse memory feedback result -> per-memory peak targets ----
                # 输入来自 observatory._apply_memory_feedback() 的返回结构（items 内含 events/projections）。
                fb = memory_feedback_result or {}
                fb_items = list(fb.get("items", []) or [])
                fb_items = [x for x in fb_items if isinstance(x, dict)]

                for fbi in fb_items:
                    mid = str(fbi.get("memory_id", "") or "").strip()
                    if not mid:
                        continue
                    kind = str(fbi.get("memory_kind", "") or "").strip()
                    score_by_mem.setdefault(mid, {})

                    if kind == "stimulus_packet":
                        for ev in list(fbi.get("events", []) or []):
                            if not isinstance(ev, dict):
                                continue
                            tid = str(ev.get("target_item_id", "") or "").strip()
                            if not tid:
                                continue
                            d = ev.get("delta", {}) if isinstance(ev.get("delta", {}), dict) else {}
                            de = max(0.0, float(d.get("delta_er", 0.0) or 0.0)) + max(0.0, float(d.get("delta_ev", 0.0) or 0.0))
                            if de <= 0.0:
                                continue
                            score_by_mem[mid][tid] = float(score_by_mem[mid].get(tid, 0.0) or 0.0) + float(de)

                        # `stimulus_packet` 记忆反馈除了原子事件峰值外，还可能伴随高阶结构投影。
                        # 旧实现没有读取这里的 projections，时间感受会系统性地只绑定到底层 A/B/X 等对象。
                        # 这里单独记录 projection 分数，由开关决定是否做“高阶结构镜像绑定”。
                        for pr in list(fbi.get("projections", []) or fbi.get("structure_projections", []) or []):
                            if not isinstance(pr, dict):
                                continue
                            tid = str(pr.get("target_item_id", "") or "").strip()
                            if not tid:
                                continue
                            ref_type = str(pr.get("target_ref_object_type", "") or "").strip().lower()
                            if ref_type and ref_type != "st":
                                continue
                            de = max(0.0, float(pr.get("er", 0.0) or 0.0)) + max(0.0, float(pr.get("ev", 0.0) or 0.0))
                            if de <= 0.0:
                                continue
                            projection_scores_by_mem.setdefault(mid, {})
                            projection_scores_by_mem[mid][tid] = float(projection_scores_by_mem[mid].get(tid, 0.0) or 0.0) + float(de)

                    elif kind in {"structure_group", "runtime_em_projection"}:
                        for pr in list(fbi.get("projections", []) or []):
                            if not isinstance(pr, dict):
                                continue
                            tid = str(pr.get("target_item_id", "") or "").strip()
                            if not tid:
                                continue
                            de = max(0.0, float(pr.get("er", 0.0) or 0.0)) + max(0.0, float(pr.get("ev", 0.0) or 0.0))
                            if de <= 0.0:
                                continue
                            score_by_mem[mid][tid] = float(score_by_mem[mid].get(tid, 0.0) or 0.0) + float(de)
                            projection_scores_by_mem.setdefault(mid, {})
                            projection_scores_by_mem[mid][tid] = float(projection_scores_by_mem[mid].get(tid, 0.0) or 0.0) + float(de)

            # ---- Select peak targets (per memory) / 每条记忆选取波峰目标 ----
            max_targets = int(self._config.get("max_bind_targets_per_memory", 2) or 2)
            max_targets = max(1, min(8, max_targets))
            keep_ratio = float(self._config.get("peak_keep_ratio", 0.72) or 0.72)
            keep_ratio = max(0.0, min(1.0, keep_ratio))
            enable_projection_targets = bool(self._config.get("enable_projection_target_bindings", True))
            projection_max_targets = int(self._config.get("max_projection_bind_targets_per_memory", 1) or 1)
            projection_max_targets = max(0, min(8, projection_max_targets))
            projection_keep_ratio = float(self._config.get("projection_target_keep_ratio", keep_ratio) or keep_ratio)
            projection_keep_ratio = max(0.0, min(1.0, projection_keep_ratio))
            max_total = int(self._config.get("max_total_bindings", 12) or 12)
            max_total = max(1, min(64, max_total))

            candidates: list[dict[str, Any]] = []
            for mid, scores in score_by_mem.items():
                mt = mem_time.get(mid)
                if not mt:
                    continue
                pairs = [(tid, float(v or 0.0)) for tid, v in (scores or {}).items() if str(tid) and float(v or 0.0) > 0.0]
                if not pairs:
                    continue
                picked = self._pick_peak_targets_from_scores(
                    score_pairs=pairs,
                    max_targets=max_targets,
                    keep_ratio=keep_ratio,
                )
                for tid, sc in picked:
                    candidates.append(
                        {
                            "memory_id": mid,
                            "memory_display_text": mt.get("display_text", ""),
                            "delta_unit": mt.get("delta_unit", "s"),
                            "delta_sec": mt.get("delta_sec", 0.0),
                            "delta_value": mt.get("delta_value", mt.get("delta_sec", 0.0)),
                            "time_basis": mt.get("time_basis", time_basis),
                            "bucket_id": mt.get("bucket_id", ""),
                            "bucket_label_zh": mt.get("bucket_label_zh", ""),
                            "bucket_center_sec": mt.get("bucket_center_sec", 0.0),
                            "bucket_weight": mt.get("bucket_weight", 0.0),
                            "bucket_secondary_id": mt.get("bucket_secondary_id", ""),
                            "bucket_secondary_label_zh": mt.get("bucket_secondary_label_zh", ""),
                            "bucket_secondary_center_sec": mt.get("bucket_secondary_center_sec", 0.0),
                            "bucket_secondary_weight": mt.get("bucket_secondary_weight", 0.0),
                            # Raw dual buckets (for audit) / 原始双桶结果（审计用）
                            "bucket_1": mt.get("bucket_1", ""),
                            "w1": mt.get("w1", 0.0),
                            "bucket_2": mt.get("bucket_2", ""),
                            "w2": mt.get("w2", 0.0),
                            "bucket_ref_object_id": f"{node_prefix}{str(mt.get('bucket_id', '') or '')}" if str(mt.get("bucket_id", "") or "") else "",
                            "bucket_secondary_ref_object_id": f"{node_prefix}{str(mt.get('bucket_secondary_id', '') or '')}" if str(mt.get("bucket_secondary_id", "") or "") else "",
                            "time_feeling_energy": mt.get("time_feeling_energy", 0.0),
                            "target_item_id": tid,
                            "target_delta_energy": round(float(sc), 8),
                            "target_score_source": "legacy_peak",
                            "target_peak_kind": "feedback_peak",
                        }
                    )

            if enable_projection_targets and projection_max_targets > 0:
                for mid, projection_scores in projection_scores_by_mem.items():
                    mt = mem_time.get(mid)
                    if not mt:
                        continue
                    projection_pairs = [
                        (tid, float(v or 0.0))
                        for tid, v in (projection_scores or {}).items()
                        if str(tid) and float(v or 0.0) > 0.0
                    ]
                    if not projection_pairs:
                        continue
                    picked_projection_targets = self._pick_peak_targets_from_scores(
                        score_pairs=projection_pairs,
                        max_targets=projection_max_targets,
                        keep_ratio=projection_keep_ratio,
                    )
                    for tid, sc in picked_projection_targets:
                        candidates.append(
                            {
                                "memory_id": mid,
                                "memory_display_text": mt.get("display_text", ""),
                                "delta_unit": mt.get("delta_unit", "s"),
                                "delta_sec": mt.get("delta_sec", 0.0),
                                "delta_value": mt.get("delta_value", mt.get("delta_sec", 0.0)),
                                "time_basis": mt.get("time_basis", time_basis),
                                "bucket_id": mt.get("bucket_id", ""),
                                "bucket_label_zh": mt.get("bucket_label_zh", ""),
                                "bucket_center_sec": mt.get("bucket_center_sec", 0.0),
                                "bucket_weight": mt.get("bucket_weight", 0.0),
                                "bucket_secondary_id": mt.get("bucket_secondary_id", ""),
                                "bucket_secondary_label_zh": mt.get("bucket_secondary_label_zh", ""),
                                "bucket_secondary_center_sec": mt.get("bucket_secondary_center_sec", 0.0),
                                "bucket_secondary_weight": mt.get("bucket_secondary_weight", 0.0),
                                "bucket_1": mt.get("bucket_1", ""),
                                "w1": mt.get("w1", 0.0),
                                "bucket_2": mt.get("bucket_2", ""),
                                "w2": mt.get("w2", 0.0),
                                "bucket_ref_object_id": f"{node_prefix}{str(mt.get('bucket_id', '') or '')}" if str(mt.get("bucket_id", "") or "") else "",
                                "bucket_secondary_ref_object_id": f"{node_prefix}{str(mt.get('bucket_secondary_id', '') or '')}" if str(mt.get("bucket_secondary_id", "") or "") else "",
                                "time_feeling_energy": mt.get("time_feeling_energy", 0.0),
                                "target_item_id": tid,
                                "target_delta_energy": round(float(sc), 8),
                                "target_score_source": "projection_peak",
                                "target_peak_kind": "structure_projection",
                            }
                        )

            if effective_source_mode == "runtime_memory_projection":
                runtime_keep_ratio = float(self._config.get("projection_target_keep_ratio", keep_ratio) or keep_ratio)
                runtime_keep_ratio = max(0.0, min(1.0, runtime_keep_ratio))
                runtime_max_targets = int(self._config.get("max_projection_bind_targets_per_memory", 1) or 1)
                runtime_max_targets = max(1, min(8, runtime_max_targets))
                for mid, runtime_scores in runtime_snapshot_scores_by_mem.items():
                    mt = mem_time.get(mid)
                    if not mt:
                        continue
                    runtime_pairs = [
                        (tid, float(v or 0.0))
                        for tid, v in (runtime_scores or {}).items()
                        if str(tid) and float(v or 0.0) > 0.0
                    ]
                    if not runtime_pairs:
                        continue
                    picked_runtime_targets = self._pick_peak_targets_from_scores(
                        score_pairs=runtime_pairs,
                        max_targets=runtime_max_targets,
                        keep_ratio=runtime_keep_ratio,
                    )
                    for tid, sc in picked_runtime_targets:
                        candidates.append(
                            {
                                "memory_id": mid,
                                "memory_display_text": mt.get("display_text", ""),
                                "delta_unit": mt.get("delta_unit", "s"),
                                "delta_sec": mt.get("delta_sec", 0.0),
                                "delta_value": mt.get("delta_value", mt.get("delta_sec", 0.0)),
                                "time_basis": mt.get("time_basis", time_basis),
                                "bucket_id": mt.get("bucket_id", ""),
                                "bucket_label_zh": mt.get("bucket_label_zh", ""),
                                "bucket_center_sec": mt.get("bucket_center_sec", 0.0),
                                "bucket_weight": mt.get("bucket_weight", 0.0),
                                "bucket_secondary_id": mt.get("bucket_secondary_id", ""),
                                "bucket_secondary_label_zh": mt.get("bucket_secondary_label_zh", ""),
                                "bucket_secondary_center_sec": mt.get("bucket_secondary_center_sec", 0.0),
                                "bucket_secondary_weight": mt.get("bucket_secondary_weight", 0.0),
                                "bucket_1": mt.get("bucket_1", ""),
                                "w1": mt.get("w1", 0.0),
                                "bucket_2": mt.get("bucket_2", ""),
                                "w2": mt.get("w2", 0.0),
                                "bucket_ref_object_id": f"{node_prefix}{str(mt.get('bucket_id', '') or '')}" if str(mt.get("bucket_id", "") or "") else "",
                                "bucket_secondary_ref_object_id": f"{node_prefix}{str(mt.get('bucket_secondary_id', '') or '')}" if str(mt.get("bucket_secondary_id", "") or "") else "",
                                "time_feeling_energy": mt.get("time_feeling_energy", 0.0),
                                "target_item_id": tid,
                                "target_delta_energy": round(float(sc), 8),
                                "target_score_source": "runtime_projection_peak",
                                "target_peak_kind": "runtime_memory_projection",
                            }
                        )

            # Reduce duplicates by target_item_id: keep strongest.
            best_by_target: dict[str, dict[str, Any]] = {}
            for c in candidates:
                tid = str(c.get("target_item_id", "") or "").strip()
                if not tid:
                    continue
                if tid not in best_by_target or float(c.get("target_delta_energy", 0.0) or 0.0) > float(best_by_target[tid].get("target_delta_energy", 0.0) or 0.0):
                    best_by_target[tid] = c
            selected = list(best_by_target.values())
            selected.sort(key=lambda r: float(r.get("target_delta_energy", 0.0) or 0.0), reverse=True)
            selected = selected[:max_total]

            # ---- Bind runtime attribute to selected targets ----
            for c in selected:
                tid = str(c.get("target_item_id", "") or "").strip()
                bid = str(c.get("bucket_id", "") or "").strip()
                if not tid or not bid:
                    continue
                label_zh = str(c.get("bucket_label_zh", bid) or bid)
                center_sec = float(c.get("bucket_center_sec", 0.0) or 0.0)
                bucket_w = float(c.get("bucket_weight", 0.0) or 0.0)
                sec_id = str(c.get("bucket_secondary_id", "") or "").strip()
                sec_label_zh = str(c.get("bucket_secondary_label_zh", sec_id) or sec_id)
                sec_center_sec = float(c.get("bucket_secondary_center_sec", 0.0) or 0.0)
                sec_w = float(c.get("bucket_secondary_weight", 0.0) or 0.0)
                primary_ref_id = str(c.get("bucket_ref_object_id", "") or "").strip()
                secondary_ref_id = str(c.get("bucket_secondary_ref_object_id", "") or "").strip()
                target_item_before = None
                target_ref_object_id = ""
                target_ref_object_type = ""
                target_display_seed = ""
                context_owner_structure_id = ""
                try:
                    target_item_before = pool._store.get(tid)  # type: ignore[attr-defined]
                except Exception:
                    target_item_before = None
                if isinstance(target_item_before, dict):
                    target_ref_object_id = str(target_item_before.get("ref_object_id", "") or "")
                    target_ref_object_type = str(target_item_before.get("ref_object_type", "") or "")
                    target_ref_snapshot = (
                        target_item_before.get("ref_snapshot", {})
                        if isinstance(target_item_before.get("ref_snapshot", {}), dict)
                        else {}
                    )
                    target_display_seed = str(
                        target_ref_snapshot.get("content_display", "")
                        or target_ref_snapshot.get("content_display_detail", "")
                        or target_ref_object_id
                    )
                    target_runtime_ext = (
                        target_item_before.get("meta", {}).get("ext", {})
                        if isinstance(target_item_before.get("meta", {}), dict)
                        and isinstance(target_item_before.get("meta", {}).get("ext", {}), dict)
                        else {}
                    )
                    context_owner_structure_id = str(
                        target_runtime_ext.get("context_owner_structure_id", "")
                        or (target_ref_object_id if target_ref_object_type == "st" else "")
                    )

                # Attribute SA (not inserted as standalone state item).
                # 属性 SA（不会作为独立 state_item 入池）。
                # 重要：attribute_sa.id 必须尽量稳定，否则 ext.bound_attributes 会随 bucket 变化而膨胀。
                # 因此这里使用 “按目标对象稳定”的 id（每个目标对象 1 条时间感受属性）。
                attr_id = f"sa_time_attr_{tid}"
                attribute_sa = {
                    "id": attr_id,
                    "object_type": "sa",
                    "content": {
                        "raw": f"{attr_name}:{bid}",
                        "display": f"{attr_name}：【{label_zh}】",
                        "value_type": "numerical",
                        "attribute_name": attr_name,
                        "attribute_value": center_sec,
                    },
                    "stimulus": {"role": "attribute", "modality": "internal"},
                    "energy": {"er": 0.0, "ev": 0.0},
                    "source": {
                        "parent_ids": [target_ref_object_id] if target_ref_object_id else [tid],
                        "context_ref_object_id": target_ref_object_id,
                        "context_ref_object_type": target_ref_object_type,
                        **({"context_owner_structure_id": context_owner_structure_id} if context_owner_structure_id else {}),
                    },
                    "meta": {
                        "ext": {
                            "bound_anchor_item_id": tid,
                            "bound_anchor_ref_object_id": target_ref_object_id,
                            "bound_anchor_ref_object_type": target_ref_object_type,
                            "bound_anchor_display": target_display_seed,
                            "attribute_runtime_mode": "state_item",
                            "time_basis": str(c.get("time_basis", time_basis) or time_basis),
                            "time_unit": str(c.get("delta_unit", "s") or "s"),
                            "time_bucket_id": bid,
                            "time_bucket_label_zh": label_zh,
                            "time_bucket_center_sec": center_sec,
                            "time_bucket_center_value": center_sec,
                            "time_bucket_unit": "tick" if time_basis == "tick" else "s",
                            "time_bucket_weight": round(bucket_w, 6),
                            "time_bucket_ref_object_id": primary_ref_id or f"{node_prefix}{bid}",
                            "time_bucket_secondary_id": sec_id,
                            "time_bucket_secondary_label_zh": sec_label_zh,
                            "time_bucket_secondary_center_sec": sec_center_sec,
                            "time_bucket_secondary_center_value": sec_center_sec,
                            "time_bucket_secondary_weight": round(sec_w, 6),
                            "time_bucket_secondary_ref_object_id": secondary_ref_id or (f"{node_prefix}{sec_id}" if sec_id else ""),
                            "memory_id": str(c.get("memory_id", "") or ""),
                            "delta_sec": float(c.get("delta_sec", 0.0) or 0.0),
                            "delta_value": float(c.get("delta_value", c.get("delta_sec", 0.0)) or 0.0),
                            "time_feeling_energy": float(c.get("time_feeling_energy", 0.0) or 0.0),
                            # Keep raw dual-bucket result for audit / 保留原始双桶结果用于审计
                            "dual_bucket_1": str(c.get("bucket_1", "") or ""),
                            "dual_bucket_w1": float(c.get("w1", 0.0) or 0.0),
                            "dual_bucket_2": str(c.get("bucket_2", "") or ""),
                            "dual_bucket_w2": float(c.get("w2", 0.0) or 0.0),
                        }
                    },
                }

                try:
                    res = pool.bind_attribute_node_to_object(  # type: ignore[attr-defined]
                        target_item_id=tid,
                        attribute_sa=attribute_sa,
                        trace_id=trace_id,
                        tick_id=tick_id,
                        source_module=__module_name__,
                        reason="time_feeling_bind_attribute",
                    )
                    pool_events.append(
                        {
                            "op": "bind_attribute",
                            "target_item_id": tid,
                            "attribute_sa_id": attr_id,
                            "bucket_id": bid,
                            "bucket_secondary_id": sec_id,
                            "code": res.get("code", "") if isinstance(res, dict) else "",
                            "success": bool(res.get("success", False)) if isinstance(res, dict) else True,
                        }
                    )
                except Exception as exc:
                    pool_events.append({"op": "bind_attribute", "target_item_id": tid, "attribute_sa_id": attr_id, "bucket_id": bid, "bucket_secondary_id": sec_id, "error": str(exc)})

                # Best-effort target display snapshot (after binding).
                target_display = ""
                target_ref_id = ""
                target_ref_type = ""
                try:
                    target_item = pool._store.get(tid)  # type: ignore[attr-defined]
                    if isinstance(target_item, dict):
                        rs = target_item.get("ref_snapshot", {}) if isinstance(target_item.get("ref_snapshot", {}), dict) else {}
                        target_display = str(rs.get("content_display", "") or target_item.get("ref_object_id", "") or tid)
                        target_ref_id = str(target_item.get("ref_object_id", "") or "")
                        target_ref_type = str(target_item.get("ref_object_type", "") or "")
                except Exception:
                    pass

                attribute_bindings.append(
                    {
                        **dict(c),
                        "attribute_name": attr_name,
                        "attribute_sa_id": attr_id,
                        "attribute_display": attribute_sa.get("content", {}).get("display", ""),
                        "target_ref_object_id": target_ref_id,
                        "target_ref_object_type": target_ref_type,
                        "target_display": target_display,
                    }
                )

        # ---- Step 5: register delayed tasks from attribute time-feelings (theory 4.2.8) ----
        delayed_register = self._register_delayed_tasks_from_bindings(
            attribute_bindings=attribute_bindings,
            pool=pool,
            hdb=hdb,
            now_ms=now_ms,
            time_basis=time_basis,
            tick_index=int(tick_index) if tick_index is not None else None,
        )

        out = {
            "now_ms": now_ms,
            "enabled": True,
            "time_basis": time_basis,
            "tick_index": int(tick_index) if tick_index is not None else None,
            "source_mode": effective_source_mode,
            "enabled_bucket_nodes": bool(enable_bucket_nodes),
            "enabled_bind_attribute": bool(enable_bind_attribute),
            "output_mode": output_mode,
            "memory_used_count": len(items),
            "memory_rows": mem_rows[:24],
            "bucket_updates": bucket_updates,
            "attribute_bindings": attribute_bindings[:64],
            "attribute_binding_source_counts": self._count_binding_sources(attribute_bindings),
            "pool_events": pool_events,
            "delayed_tasks": {
                **dict(delayed_report),
                "registered": dict(delayed_register),
                "table_size": len(self._delayed_tasks),
            },
        }
        self._last_tick_report = out
        self._logger.brief(
            trace_id=trace_id,
            tick_id=tick_id,
            interface="run_time_feeling_tick",
            success=True,
            message="时间感受已计算并输出到状态池 / time feelings output to StatePool",
            input_summary={"memory_item_count": len(items), "gain_ratio": gain_ratio, "energy_key": energy_key},
            output_summary={
                "output_mode": output_mode,
                "bucket_nodes": bool(enable_bucket_nodes),
                "bind_attribute": bool(enable_bind_attribute),
                "bucket_update_count": len(bucket_updates),
                "attr_bind_count": len(attribute_bindings),
                "binding_source_counts": self._count_binding_sources(attribute_bindings),
                "pool_event_count": len(pool_events),
            },
        )
        return self._make_response(True, "OK", "时间感受器执行成功 / Time sensor tick OK", data=out, trace_id=trace_id, elapsed_ms=self._elapsed_ms(start))

    # ================================================================== #
    # Helpers                                                             #
    # ================================================================== #

    def _resolve_output_flags(self) -> dict[str, Any]:
        """
        Resolve effective output switches.
        解析“最终生效”的输出开关。

        Why / 为什么需要：
          - 旧版配置用 output_mode（二选一）。
          - 新版理论口径允许 bucket_nodes 与 bind_attribute 同时存在，因此需要两开关。
          - 为了兼容旧配置，我们允许：
              - 若 enable_bucket_nodes / enable_bind_attribute 任何一个被显式设为 bool，
                则以两开关为准（未显式设置的那个从 output_mode 回退）。
              - 若两者都未显式设置（None/缺失），则完全按 output_mode。
        """
        cfg = self._config or {}
        raw_bucket = cfg.get("enable_bucket_nodes", None)
        raw_bind = cfg.get("enable_bind_attribute", None)
        legacy_mode = str(cfg.get("output_mode", "bind_attribute") or "bind_attribute").strip().lower() or "bind_attribute"

        # Normalize legacy mode / 兼容旧字段
        legacy_bucket = False
        legacy_bind = True
        if legacy_mode in {"bucket_nodes", "bucket", "buckets"}:
            legacy_bucket, legacy_bind = True, False
        elif legacy_mode in {"bind_attribute", "bind", "attribute"}:
            legacy_bucket, legacy_bind = False, True
        elif legacy_mode in {"both", "all", "bucket_and_bind", "bucket+bind"}:
            legacy_bucket, legacy_bind = True, True

        enable_bucket = legacy_bucket
        enable_bind = legacy_bind

        # If user explicitly sets booleans, honor them; fallback unspecified to legacy mode.
        # 若用户显式配置了布尔值，则以其为准；未显式配置者回退到 legacy_mode。
        if isinstance(raw_bucket, bool):
            enable_bucket = raw_bucket
        if isinstance(raw_bind, bool):
            enable_bind = raw_bind

        # Effective label for UI / 输出模式标签（供前端展示）
        if enable_bucket and enable_bind:
            effective_mode = "both"
        elif enable_bucket:
            effective_mode = "bucket_nodes"
        elif enable_bind:
            effective_mode = "bind_attribute"
        else:
            effective_mode = "disabled"

        return {
            "enable_bucket_nodes": bool(enable_bucket),
            "enable_bind_attribute": bool(enable_bind),
            "output_mode": effective_mode,
            "legacy_output_mode": legacy_mode,
        }

    @staticmethod
    def _pick_peak_targets_from_scores(
        *,
        score_pairs: list[tuple[str, float]],
        max_targets: int,
        keep_ratio: float,
    ) -> list[tuple[str, float]]:
        pairs = [
            (str(tid or "").strip(), float(score or 0.0))
            for tid, score in list(score_pairs or [])
            if str(tid or "").strip() and float(score or 0.0) > 0.0
        ]
        if not pairs or max_targets <= 0:
            return []
        pairs.sort(key=lambda item: item[1], reverse=True)
        max_score = float(pairs[0][1] or 0.0)
        picked = [(tid, sc) for (tid, sc) in pairs if sc >= max_score * keep_ratio][:max_targets]
        if not picked:
            picked = [pairs[0]]
        return [(tid, float(round(sc, 8))) for tid, sc in picked]

    def _runtime_snapshot_target_richness_weight(self, target_item: dict | None) -> float:
        if not bool(self._config.get("runtime_snapshot_target_richness_bias_enabled", True)):
            return 1.0
        if not isinstance(target_item, dict):
            return 1.0

        ref_snapshot = target_item.get("ref_snapshot", {}) if isinstance(target_item.get("ref_snapshot", {}), dict) else {}
        sequence_groups = ref_snapshot.get("sequence_groups", []) if isinstance(ref_snapshot.get("sequence_groups", []), list) else []
        flat_tokens = [str(token) for token in (ref_snapshot.get("flat_tokens", []) or []) if str(token)]
        runtime_bound_units = ref_snapshot.get("runtime_bound_attribute_units", [])
        if not isinstance(runtime_bound_units, list):
            runtime_bound_units = []
        ext = target_item.get("ext", {}) if isinstance(target_item.get("ext", {}), dict) else {}
        bound_attributes = ext.get("bound_attributes", []) if isinstance(ext.get("bound_attributes", []), list) else []

        try:
            token_count = int(ref_snapshot.get("token_count", 0) or 0)
        except Exception:
            token_count = 0
        if token_count <= 0:
            try:
                token_count = int(ref_snapshot.get("member_count", 0) or 0)
            except Exception:
                token_count = 0
        if token_count <= 0:
            token_count = len(flat_tokens)
        token_count = max(1, token_count)
        group_count = max(1, len([group for group in sequence_groups if isinstance(group, dict)]) or 0)
        runtime_attr_count = len([unit for unit in runtime_bound_units if isinstance(unit, dict)])
        if runtime_attr_count <= 0:
            runtime_attr_count = len([attr for attr in bound_attributes if isinstance(attr, dict)])

        token_bonus = max(0.0, float(self._config.get("runtime_snapshot_target_complexity_bonus_per_token", 0.45) or 0.45))
        group_bonus = max(0.0, float(self._config.get("runtime_snapshot_target_group_bonus", 0.15) or 0.15))
        runtime_attr_bonus = max(0.0, float(self._config.get("runtime_snapshot_target_runtime_attr_bonus", 0.08) or 0.08))

        complexity_scale = 1.0
        complexity_scale += token_bonus * max(0, token_count - 1)
        complexity_scale += group_bonus * max(0, group_count - 1)
        complexity_scale += runtime_attr_bonus * max(0, runtime_attr_count)

        total_energy = 0.0
        energy = target_item.get("energy", {}) if isinstance(target_item.get("energy", {}), dict) else {}
        try:
            total_energy += float(energy.get("er", 0.0) or 0.0) + float(energy.get("ev", 0.0) or 0.0)
        except Exception:
            total_energy = 0.0
        if total_energy <= 0.0:
            try:
                total_energy += float(target_item.get("er", 0.0) or 0.0) + float(target_item.get("ev", 0.0) or 0.0)
            except Exception:
                total_energy = 0.0
        energy_scale = math.sqrt(total_energy) if total_energy > 0.0 else 1.0
        return round(max(1.0, float(complexity_scale) * max(1.0, float(energy_scale))), 8)

    @staticmethod
    def _dedupe_runtime_snapshot_weighted_targets(weighted_targets: list[tuple[str, float]]) -> list[tuple[str, float]]:
        best_by_target: dict[str, float] = {}
        ordered_ids: list[str] = []
        for raw_target_id, raw_weight in list(weighted_targets or []):
            target_id = str(raw_target_id or "").strip()
            if not target_id:
                continue
            weight = max(0.0, float(raw_weight or 0.0))
            if target_id not in best_by_target:
                ordered_ids.append(target_id)
                best_by_target[target_id] = weight
                continue
            if weight > float(best_by_target.get(target_id, 0.0) or 0.0):
                best_by_target[target_id] = weight
        return [(target_id, round(float(best_by_target.get(target_id, 0.0) or 0.0), 8)) for target_id in ordered_ids]

    @staticmethod
    def _count_binding_sources(attribute_bindings: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in list(attribute_bindings or []):
            if not isinstance(row, dict):
                continue
            source = str(row.get("target_score_source", "") or "legacy_peak").strip() or "legacy_peak"
            counts[source] = int(counts.get(source, 0)) + 1
        return counts

    def _normalized_buckets(self, key: str = "buckets") -> list[dict[str, Any]]:
        raw = list(self._config.get(key, []) or [])
        if not raw and key != "buckets":
            # Fallback to wallclock buckets if tick_buckets is missing / tick_buckets 缺失时回退到秒桶
            raw = list(self._config.get("buckets", []) or [])
        out: list[dict[str, Any]] = []
        for b in raw:
            if not isinstance(b, dict):
                continue
            bid = str(b.get("id", "") or "").strip()
            if not bid:
                continue
            try:
                center = float(b.get("center_sec", 0.0) or 0.0)
            except Exception:
                center = 0.0
            out.append(
                {
                    "id": bid,
                    "label_zh": str(b.get("label_zh", bid) or bid),
                    "min_sec": float(b.get("min_sec", 0.0) or 0.0),
                    "max_sec": float(b.get("max_sec", 0.0) or 0.0),
                    "center_sec": float(center),
                }
            )
        out.sort(key=lambda x: float(x.get("center_sec", 0.0) or 0.0))
        return out

    @staticmethod
    def _parse_tick_index(tick_id: str) -> int | None:
        """Parse numeric tick_index from tick_id tail (e.g. 'cycle_0003' -> 3)."""
        s = str(tick_id or "").strip()
        if not s:
            return None
        m = re.search(r"(\d+)$", s)
        if not m:
            return None
        try:
            return int(m.group(1))
        except Exception:
            return None

    # ================================================================== #
    # Delayed Task Table (theory 4.2.8) / 延迟赋能任务表（理论 4.2.8）       #
    # ================================================================== #

    def _task_in_fatigue(
        self,
        *,
        task_key: str,
        now_ms: int,
        time_basis: str,
        tick_index: int | None,
    ) -> bool:
        if not task_key:
            return False
        if str(time_basis) == "tick":
            until = int(self._task_fatigue_until_tick.get(task_key, 0) or 0)
            if tick_index is None:
                return False
            return int(tick_index) < until
        until_ms = int(self._task_fatigue_until_ms.get(task_key, 0) or 0)
        return int(now_ms) < until_ms

    def _execute_due_delayed_tasks(
        self,
        *,
        pool: Any,
        hdb: Any | None,
        trace_id: str,
        tick_id: str,
        now_ms: int,
        time_basis: str,
        tick_index: int | None,
    ) -> dict[str, Any]:
        """
        Execute due delayed tasks and energize their targets.
        执行到期任务，并对目标对象赋能（理论 4.2.8 的“到点再点亮”）。
        """
        enabled = bool(self._config.get("enable_delayed_tasks", False))
        if not enabled:
            return {"enabled": False, "executed_count": 0, "pool_events": [], "executed": []}

        tasks = dict(self._delayed_tasks or {})
        if not tasks:
            return {"enabled": True, "executed_count": 0, "pool_events": [], "executed": []}

        # Config
        energy_key = str(self._config.get("delayed_task_energy_key", "ev") or "ev").strip().lower() or "ev"
        energy_key = "er" if energy_key == "er" else "ev"
        ratio = float(self._config.get("delayed_task_energy_ratio", 0.80) or 0.80)
        ratio = max(0.0, min(10.0, ratio))
        e_min = float(self._config.get("delayed_task_energy_min", 0.06) or 0.06)
        e_max = float(self._config.get("delayed_task_energy_max", 0.85) or 0.85)
        e_min = max(0.0, min(e_max, e_min))
        e_max = max(e_min, e_max)
        tol_sec = float(self._config.get("delayed_task_due_tolerance_sec", 0.15) or 0.15)
        tol_sec = max(0.0, min(3600.0, tol_sec))
        tol_ticks = int(self._config.get("delayed_task_due_tolerance_ticks", 0) or 0)
        tol_ticks = max(0, min(10_000, tol_ticks))
        fatigue_ticks = int(self._config.get("delayed_task_fatigue_ticks", 2) or 2)
        fatigue_ticks = max(0, min(10_000, fatigue_ticks))
        fatigue_ms = int(self._config.get("delayed_task_fatigue_ms", 800) or 800)
        fatigue_ms = max(0, min(86_400_000, fatigue_ms))

        executed: list[dict[str, Any]] = []
        pool_events: list[dict[str, Any]] = []
        kept: dict[str, dict[str, Any]] = {}

        for task_key, task in tasks.items():
            task_key = str(task_key or "").strip()
            if not task_key or not isinstance(task, dict):
                continue
            task_kind = str(task.get("task_kind", "anchor_item") or "anchor_item").strip() or "anchor_item"

            # Skip if in fatigue window.
            if self._task_in_fatigue(task_key=task_key, now_ms=now_ms, time_basis=time_basis, tick_index=tick_index):
                kept[task_key] = task
                continue

            due = False
            due_reason = ""
            try:
                if str(time_basis) == "tick":
                    if tick_index is None:
                        due = False
                    else:
                        due_tick = int(task.get("due_tick", 0) or 0)
                        due = int(tick_index) >= (due_tick - tol_ticks)
                        due_reason = f"tick>=due({tick_index}>={due_tick}-tol{tol_ticks})"
                else:
                    due_at = int(task.get("due_at_ms", 0) or 0)
                    due = int(now_ms) >= int(due_at - int(tol_sec * 1000.0))
                    due_reason = f"ms>=due({now_ms}>={due_at}-tol{int(tol_sec*1000.0)})"
            except Exception:
                due = False

            if not due:
                kept[task_key] = task
                continue

            # Apply energization
            try:
                weight = max(0.0, float(task.get("weight", 0.0) or 0.0))
            except Exception:
                weight = 0.0
            raw = weight * ratio
            delta_energy = 0.0
            if raw > 0.0:
                delta_energy = max(e_min, min(e_max, raw))
            delta_energy = float(round(delta_energy, 8))

            if delta_energy <= 0.0:
                # Nothing to apply; drop task silently.
                executed.append(
                    {
                        "task_key": task_key,
                        "task_kind": task_kind,
                        "target_item_id": str(task.get("target_item_id", "") or ""),
                        "target_ref_object_id": str(task.get("target_ref_object_id", "") or ""),
                        "ok": False,
                        "reason": "delta_energy_zero",
                    }
                )
            else:
                delta_er = float(delta_energy) if energy_key == "er" else 0.0
                delta_ev = float(delta_energy) if energy_key == "ev" else 0.0
                try:
                    resolved_target = self._resolve_delayed_task_runtime_target(
                        task=task,
                        pool=pool,
                        hdb=hdb,
                        trace_id=trace_id,
                        tick_id=tick_id,
                    )
                    resolved_item_id = str(resolved_target.get("target_item_id", "") or "").strip()
                    resolved_ref_id = str(
                        resolved_target.get("target_ref_object_id", task.get("target_ref_object_id", "")) or ""
                    ).strip()
                    resolved_ref_type = str(
                        resolved_target.get("target_ref_object_type", task.get("target_ref_object_type", "")) or ""
                    ).strip()
                    if not resolved_item_id:
                        raise RuntimeError("delayed_task_target_missing")
                    res = pool.apply_energy_update(  # type: ignore[attr-defined]
                        target_item_id=resolved_item_id,
                        delta_er=delta_er,
                        delta_ev=delta_ev,
                        trace_id=f"{trace_id}_time_sensor_task",
                        tick_id=tick_id,
                        reason="time_sensor_delayed_task_due",
                        source_module=__module_name__,
                    )
                    pool_events.append(
                        {
                            "op": "delayed_task_execute",
                            "task_key": task_key,
                            "task_kind": task_kind,
                            "target_item_id": resolved_item_id,
                            "target_ref_object_id": resolved_ref_id,
                            "target_ref_object_type": resolved_ref_type,
                            "delta_er": round(delta_er, 6),
                            "delta_ev": round(delta_ev, 6),
                            "time_basis": time_basis,
                            "due_reason": due_reason,
                            "success": bool(res.get("success", False)) if isinstance(res, dict) else True,
                            "code": res.get("code", "") if isinstance(res, dict) else "",
                        }
                    )
                    executed.append(
                        {
                            "task_key": task_key,
                            "task_kind": task_kind,
                            "target_item_id": resolved_item_id,
                            "target_ref_object_id": resolved_ref_id,
                            "target_ref_object_type": resolved_ref_type,
                            "target_display": str(
                                resolved_target.get("target_display", task.get("target_display", "")) or ""
                            ),
                            "weight": round(weight, 6),
                            "delta_energy": round(delta_energy, 6),
                            "energy_key": energy_key,
                            "time_basis": time_basis,
                            "due_reason": due_reason,
                            "ok": bool(res.get("success", False)) if isinstance(res, dict) else True,
                        }
                    )
                except Exception as exc:
                    pool_events.append(
                        {
                            "op": "delayed_task_execute",
                            "task_key": task_key,
                            "task_kind": task_kind,
                            "target_item_id": str(task.get("target_item_id", "") or ""),
                            "target_ref_object_id": str(task.get("target_ref_object_id", "") or ""),
                            "target_ref_object_type": str(task.get("target_ref_object_type", "") or ""),
                            "error": str(exc),
                        }
                    )
                    executed.append(
                        {
                            "task_key": task_key,
                            "task_kind": task_kind,
                            "target_item_id": str(task.get("target_item_id", "") or ""),
                            "target_ref_object_id": str(task.get("target_ref_object_id", "") or ""),
                            "target_ref_object_type": str(task.get("target_ref_object_type", "") or ""),
                            "ok": False,
                            "error": str(exc),
                        }
                    )

            # Apply post-exec fatigue window (avoid immediate re-registration/re-trigger)
            if str(time_basis) == "tick" and tick_index is not None and fatigue_ticks > 0:
                self._task_fatigue_until_tick[task_key] = int(tick_index) + int(fatigue_ticks)
            elif str(time_basis) != "tick" and fatigue_ms > 0:
                self._task_fatigue_until_ms[task_key] = int(now_ms) + int(fatigue_ms)

        # Keep only future tasks.
        self._delayed_tasks = kept
        return {
            "enabled": True,
            "executed_count": len([x for x in executed if isinstance(x, dict) and bool(x.get("ok", False))]),
            "executed": executed[:16],
            "pool_events": pool_events,
        }

    def _register_delayed_tasks_from_bindings(
        self,
        *,
        attribute_bindings: list[dict[str, Any]],
        pool: Any,
        hdb: Any | None,
        now_ms: int,
        time_basis: str,
        tick_index: int | None,
    ) -> dict[str, Any]:
        """
        Register (or update) delayed tasks from time-feeling attribute bindings.
        从“时间感受属性绑定”注册/更新延迟赋能任务（理论 4.2.8）。
        默认并行支持两类任务：
        - anchor_item：独立时间间隔 SA -> 到期赋能其锚点对象
        - structure_projection：若目标结构内包含时间感受 SA -> 到期赋能“去掉时间因子后的结构”
        """
        enabled = bool(self._config.get("enable_delayed_tasks", False))
        if not enabled:
            return {"enabled": False, "registered_count": 0, "updated_count": 0, "skipped": {}}

        capacity = int(self._config.get("delayed_task_capacity", 48) or 48)
        capacity = max(1, min(512, capacity))
        min_delta = float(self._config.get("delayed_task_register_min_delta_energy", 0.20) or 0.20)
        min_delta = max(0.0, min(100.0, min_delta))
        min_interval_sec = float(self._config.get("delayed_task_min_interval_sec", 0.5) or 0.5)
        min_interval_sec = max(0.0, min(3600.0, min_interval_sec))
        min_interval_ticks = int(self._config.get("delayed_task_min_interval_ticks", 1) or 1)
        min_interval_ticks = max(1, min(10_000, min_interval_ticks))

        registered = 0
        updated = 0
        skipped_small = 0
        skipped_fatigue = 0
        skipped_bad = 0
        skipped_projection = 0

        for b in list(attribute_bindings or [])[:128]:
            if not isinstance(b, dict):
                continue
            target_item_id = str(b.get("target_item_id", "") or "").strip()
            if not target_item_id:
                skipped_bad += 1
                continue
            try:
                delta = float(b.get("target_delta_energy", 0.0) or 0.0)
            except Exception:
                delta = 0.0
            if delta < min_delta:
                skipped_small += 1
                continue

            # Enforce "attribute time-feeling only": bindings already satisfy this by construction.
            # 这里不再额外检查 attribute_name，避免前端字段变化导致漏注册。

            # Interval value comes from bucket center.
            try:
                interval_value = float(b.get("bucket_center_sec", 0.0) or 0.0)
            except Exception:
                interval_value = 0.0
            if interval_value <= 0.0:
                skipped_bad += 1
                continue

            target_display = str(b.get("target_display", "") or "")
            target_ref_object_id = str(b.get("target_ref_object_id", "") or "")
            target_ref_object_type = str(b.get("target_ref_object_type", "") or "")

            # Compute due
            due_tick: int | None = None
            due_at_ms: int | None = None
            if str(time_basis) == "tick" and tick_index is not None:
                interval_ticks = max(min_interval_ticks, int(round(float(interval_value))))
                due_tick = int(tick_index) + int(interval_ticks)
            else:
                interval_sec = max(min_interval_sec, float(interval_value))
                due_at_ms = int(now_ms) + int(round(interval_sec * 1000.0))

            anchor_task = {
                "task_key": self._build_delayed_task_key(task_kind="anchor_item", target_item_id=target_item_id),
                "task_kind": "anchor_item",
                "target_item_id": target_item_id,
                "target_ref_object_id": target_ref_object_id,
                "target_ref_object_type": target_ref_object_type,
                "target_display": target_display,
                "time_basis": str(time_basis),
                "interval_value": float(interval_value),
            }
            structure_task = self._build_structure_projection_task_from_binding(
                binding=b,
                pool=pool,
                hdb=hdb,
                trace_id="",
                tick_id="",
                time_basis=time_basis,
                interval_value=float(interval_value),
            )
            candidate_tasks = [anchor_task]
            if structure_task:
                candidate_tasks.append(structure_task)
            else:
                skipped_projection += 1

            for task_seed in candidate_tasks:
                task_key = str(task_seed.get("task_key", "") or "").strip()
                if not task_key:
                    skipped_bad += 1
                    continue
                if self._task_in_fatigue(task_key=task_key, now_ms=now_ms, time_basis=time_basis, tick_index=tick_index):
                    skipped_fatigue += 1
                    continue
                task: dict[str, Any] | None = self._delayed_tasks.get(task_key)
                if task:
                    try:
                        task["weight"] = round(max(0.0, float(task.get("weight", 0.0) or 0.0)) + max(0.0, float(delta)), 8)
                    except Exception:
                        task["weight"] = round(max(0.0, float(delta)), 8)
                    task["updated_at"] = int(now_ms)
                    task["register_count"] = int(task.get("register_count", 0) or 0) + 1
                    task["time_basis"] = str(time_basis)
                    task["interval_value"] = float(interval_value)
                    if due_tick is not None:
                        task["due_tick"] = int(due_tick)
                    if due_at_ms is not None:
                        task["due_at_ms"] = int(due_at_ms)
                    for fresh_key in (
                        "target_item_id",
                        "target_ref_object_id",
                        "target_ref_object_type",
                        "target_display",
                        "target_structure_id",
                        "projection_source_structure_id",
                        "stripped_content_signature",
                    ):
                        fresh_value = task_seed.get(fresh_key)
                        if fresh_value not in (None, "", []):
                            task[fresh_key] = fresh_value
                    updated += 1
                else:
                    task = {
                        **dict(task_seed),
                        "task_id": f"ts_task_{task_key}",
                        "weight": round(max(0.0, float(delta)), 8),
                        "created_at": int(now_ms),
                        "updated_at": int(now_ms),
                        "register_count": 1,
                    }
                    if due_tick is not None:
                        task["due_tick"] = int(due_tick)
                    if due_at_ms is not None:
                        task["due_at_ms"] = int(due_at_ms)
                    self._delayed_tasks[task_key] = task
                    registered += 1

        pruned = self._prune_delayed_tasks(capacity=capacity)
        table_size = len(self._delayed_tasks)

        # For UI: show a stable top list (earliest due first).
        rows = list(self._delayed_tasks.values())
        if str(time_basis) == "tick":
            rows.sort(key=lambda t: (int(t.get("due_tick", 0) or 0), -float(t.get("weight", 0.0) or 0.0)))
        else:
            rows.sort(key=lambda t: (int(t.get("due_at_ms", 0) or 0), -float(t.get("weight", 0.0) or 0.0)))

        return {
            "enabled": True,
            "registered_count": registered,
            "updated_count": updated,
            "pruned_count": pruned,
            "table_size": table_size,
            "skipped": {
                "small_delta": skipped_small,
                "fatigue": skipped_fatigue,
                "bad": skipped_bad,
                "projection_unavailable": skipped_projection,
            },
            "tasks": rows[:16],
        }

    def _prune_delayed_tasks(self, *, capacity: int) -> int:
        """
        Prune the delayed task table when exceeding capacity.
        当任务表超过容量时裁剪（对齐理论 4.2.8.2：从较旧任务中淘汰权重较低者）。
        """
        try:
            capacity = int(capacity)
        except Exception:
            capacity = 48
        capacity = max(1, min(512, capacity))
        tasks = dict(self._delayed_tasks or {})
        if len(tasks) <= capacity:
            return 0

        # Sort by updated_at asc (oldest first).
        rows = list(tasks.values())
        rows = [r for r in rows if isinstance(r, dict)]
        rows.sort(key=lambda r: int(r.get("updated_at", r.get("created_at", 0)) or 0))

        over = len(rows) - capacity
        if over <= 0:
            return 0

        # Candidate pool = oldest 1/4 (at least 1).
        cand_size = max(1, int(len(rows) / 4))
        candidates = rows[:cand_size]
        # Drop lowest weight among candidates.
        candidates.sort(key=lambda r: float(r.get("weight", 0.0) or 0.0))

        to_drop = candidates[:over]
        dropped = 0
        drop_ids = {str(r.get("task_key", "") or "") for r in to_drop if str(r.get("task_key", "") or "")}
        for task_key in drop_ids:
            if task_key in tasks:
                tasks.pop(task_key, None)
                dropped += 1

        # If still over (candidate pool too small), drop remaining oldest by weight.
        while len(tasks) > capacity:
            rest = list(tasks.values())
            rest.sort(key=lambda r: (int(r.get("updated_at", r.get("created_at", 0)) or 0), float(r.get("weight", 0.0) or 0.0)))
            victim = rest[0] if rest else None
            if not isinstance(victim, dict):
                break
            vid = str(victim.get("task_key", "") or "")
            if not vid:
                break
            tasks.pop(vid, None)
            dropped += 1

        self._delayed_tasks = tasks
        return dropped

    @staticmethod
    def _build_delayed_task_key(
        *,
        task_kind: str,
        target_item_id: str = "",
        target_structure_id: str = "",
    ) -> str:
        kind = str(task_kind or "anchor_item").strip() or "anchor_item"
        identity = str(target_structure_id or target_item_id or "").strip()
        if not identity:
            identity = "unknown"
        return f"{kind}::{identity}"

    def _resolve_delayed_task_runtime_target(
        self,
        *,
        task: dict[str, Any],
        pool: Any,
        hdb: Any | None,
        trace_id: str,
        tick_id: str,
    ) -> dict[str, Any]:
        task_kind = str(task.get("task_kind", "anchor_item") or "anchor_item").strip() or "anchor_item"
        target_item_id = str(task.get("target_item_id", "") or "").strip()
        target_ref_object_id = str(task.get("target_ref_object_id", "") or "").strip()
        target_ref_object_type = str(task.get("target_ref_object_type", "") or "").strip()
        target_display = str(task.get("target_display", "") or "").strip()

        target_item = None
        if target_item_id:
            try:
                target_item = pool._store.get(target_item_id)  # type: ignore[attr-defined]
            except Exception:
                target_item = None
        if not isinstance(target_item, dict) and target_ref_object_id:
            try:
                target_item = pool._store.get_by_ref(target_ref_object_id)  # type: ignore[attr-defined]
            except Exception:
                target_item = None
        if isinstance(target_item, dict):
            return {
                "task_kind": task_kind,
                "target_item_id": str(target_item.get("id", "") or target_item_id),
                "target_ref_object_id": str(target_item.get("ref_object_id", "") or target_ref_object_id),
                "target_ref_object_type": str(target_item.get("ref_object_type", "") or target_ref_object_type),
                "target_display": str(
                    (
                        target_item.get("ref_snapshot", {})
                        if isinstance(target_item.get("ref_snapshot", {}), dict)
                        else {}
                    ).get("content_display", "")
                    or target_display
                    or target_ref_object_id
                ),
            }

        if target_ref_object_type == "st" and target_ref_object_id and hdb is not None:
            runtime_obj = None
            try:
                runtime_obj = hdb.make_runtime_structure_object(
                    target_ref_object_id,
                    er=0.0,
                    ev=0.0,
                    reason=f"time_sensor_{task_kind}",
                )
            except Exception:
                runtime_obj = None
            if isinstance(runtime_obj, dict):
                try:
                    pool.insert_runtime_node(  # type: ignore[attr-defined]
                        runtime_object=runtime_obj,
                        trace_id=f"{trace_id}_time_sensor_task_materialize",
                        tick_id=tick_id,
                        allow_merge=True,
                        source_module=__module_name__,
                        reason=f"time_sensor_{task_kind}_materialize",
                    )
                except Exception:
                    pass
                try:
                    target_item = pool._store.get_by_ref(target_ref_object_id)  # type: ignore[attr-defined]
                except Exception:
                    target_item = None
                if isinstance(target_item, dict):
                    return {
                        "task_kind": task_kind,
                        "target_item_id": str(target_item.get("id", "") or ""),
                        "target_ref_object_id": str(target_item.get("ref_object_id", "") or target_ref_object_id),
                        "target_ref_object_type": str(target_item.get("ref_object_type", "") or target_ref_object_type),
                        "target_display": str(
                            (
                                target_item.get("ref_snapshot", {})
                                if isinstance(target_item.get("ref_snapshot", {}), dict)
                                else {}
                            ).get("content_display", "")
                            or target_display
                            or target_ref_object_id
                        ),
                    }

        return {
            "task_kind": task_kind,
            "target_item_id": target_item_id,
            "target_ref_object_id": target_ref_object_id,
            "target_ref_object_type": target_ref_object_type,
            "target_display": target_display,
        }

    def _build_structure_projection_task_from_binding(
        self,
        *,
        binding: dict[str, Any],
        pool: Any,
        hdb: Any | None,
        trace_id: str,
        tick_id: str,
        time_basis: str,
        interval_value: float,
    ) -> dict[str, Any] | None:
        if hdb is None:
            return None
        target_item_id = str(binding.get("target_item_id", "") or "").strip()
        if not target_item_id:
            return None
        try:
            target_item = pool._store.get(target_item_id)  # type: ignore[attr-defined]
        except Exception:
            target_item = None
        target_ref_object_id = str(
            binding.get("target_ref_object_id", "")
            or (target_item.get("ref_object_id", "") if isinstance(target_item, dict) else "")
            or ""
        ).strip()
        target_ref_object_type = str(
            binding.get("target_ref_object_type", "")
            or (target_item.get("ref_object_type", "") if isinstance(target_item, dict) else "")
            or ""
        ).strip()
        if target_ref_object_type != "st" or not target_ref_object_id:
            return None

        structure_store = getattr(hdb, "_structure_store", None)
        pointer_index = getattr(hdb, "_pointer_index", None)
        cut_engine = getattr(hdb, "_cut", None)
        group_store = getattr(hdb, "_group_store", None)
        if structure_store is None or pointer_index is None or cut_engine is None:
            return None
        structure_obj = structure_store.get(target_ref_object_id)
        if not isinstance(structure_obj, dict):
            return None

        from hdb._profile_restore import restore_structure_profile

        source_profile = restore_structure_profile(
            structure_obj,
            cut_engine=cut_engine,
            structure_store=structure_store,
            group_store=group_store,
        )
        stripped_profile = self._strip_time_factor_from_profile(
            profile=source_profile,
            cut_engine=cut_engine,
        )
        if not stripped_profile:
            return None
        original_signature = str(source_profile.get("content_signature", "") or "").strip()
        stripped_signature = str(stripped_profile.get("content_signature", "") or "").strip()
        if not stripped_signature or stripped_signature == original_signature:
            return None

        materialized = self._lookup_or_materialize_structure_from_profile(
            hdb=hdb,
            target_profile=stripped_profile,
            source_structure_id=target_ref_object_id,
            trace_id=trace_id,
            tick_id=tick_id,
        )
        if not materialized:
            return None
        stripped_structure_id = str(materialized.get("structure_id", "") or "").strip()
        if not stripped_structure_id:
            return None

        return {
            "task_key": self._build_delayed_task_key(
                task_kind="structure_projection",
                target_structure_id=stripped_structure_id,
            ),
            "task_kind": "structure_projection",
            "target_item_id": "",
            "target_structure_id": stripped_structure_id,
            "target_ref_object_id": stripped_structure_id,
            "target_ref_object_type": "st",
            "target_display": str(materialized.get("display_text", "") or stripped_structure_id),
            "projection_source_structure_id": target_ref_object_id,
            "stripped_content_signature": stripped_signature,
            "time_basis": str(time_basis),
            "interval_value": float(interval_value),
        }

    def _strip_time_factor_from_profile(
        self,
        *,
        profile: dict[str, Any],
        cut_engine: Any,
    ) -> dict[str, Any] | None:
        groups = list(profile.get("sequence_groups", []) or [])
        if not groups:
            return None

        filtered_groups: list[dict[str, Any]] = []
        removed_any = False
        for group_index, group in enumerate(groups):
            if not isinstance(group, dict):
                continue
            units = [dict(unit) for unit in list(group.get("units", []) or []) if isinstance(unit, dict)]
            if not units:
                continue
            allowed_units: list[dict[str, Any]] = []
            allowed_unit_ids: set[str] = set()
            for unit in units:
                if self._is_time_factor_unit(unit):
                    removed_any = True
                    continue
                allowed_units.append(dict(unit))
                unit_id = str(unit.get("unit_id", unit.get("id", "")) or "").strip()
                if unit_id:
                    allowed_unit_ids.add(unit_id)
            if not allowed_units:
                continue

            filtered_bundles: list[dict[str, Any]] = []
            for bundle in list(group.get("csa_bundles", []) or []):
                if not isinstance(bundle, dict):
                    continue
                anchor_unit_id = str(bundle.get("anchor_unit_id", "") or "").strip()
                member_unit_ids = [
                    str(member_id)
                    for member_id in list(bundle.get("member_unit_ids", []) or [])
                    if str(member_id) and str(member_id) in allowed_unit_ids
                ]
                if anchor_unit_id not in allowed_unit_ids or len(member_unit_ids) < 2:
                    continue
                filtered_bundle = dict(bundle)
                filtered_bundle["member_unit_ids"] = member_unit_ids
                filtered_bundles.append(filtered_bundle)

            filtered_groups.append(
                {
                    "group_index": int(group.get("group_index", group_index) or group_index),
                    "source_type": str(group.get("source_type", "") or ""),
                    "origin_frame_id": str(group.get("origin_frame_id", "") or ""),
                    "source_group_index": int(group.get("source_group_index", group.get("group_index", group_index)) or group_index),
                    "source_sequence_index": int(group.get("source_sequence_index", 0) or 0),
                    "order_sensitive": bool(group.get("order_sensitive", False)),
                    "string_unit_kind": str(group.get("string_unit_kind", "") or ""),
                    "string_token_text": str(group.get("string_token_text", "") or ""),
                    "units": allowed_units,
                    "csa_bundles": filtered_bundles,
                }
            )

        if not removed_any or not filtered_groups:
            return None

        stripped_profile = cut_engine.build_sequence_profile_from_groups(filtered_groups)
        stripped_ext = dict(profile.get("ext", {}) or {}) if isinstance(profile.get("ext", {}), dict) else {}
        stripped_ext["time_factor_stripped_projection"] = True
        stripped_profile["ext"] = stripped_ext
        return stripped_profile

    def _is_time_factor_unit(self, unit: dict[str, Any]) -> bool:
        if not isinstance(unit, dict):
            return False
        configured_name = str(self._config.get("attribute_name", "时间感受") or "时间感受").strip()
        attribute_name = str(unit.get("attribute_name", unit.get("content", {}).get("attribute_name", "")) or "").strip()
        unit_role = str(unit.get("unit_role", unit.get("role", "")) or "").strip().lower()
        token = str(unit.get("token", unit.get("display_text", "")) or "")
        display_text = str(unit.get("display_text", token) or token)
        unit_signature = str(unit.get("unit_signature", "") or "")
        probe = " ".join(
            [
                attribute_name,
                token,
                display_text,
                unit_signature,
            ]
        ).lower()
        if attribute_name and attribute_name == configured_name:
            return True
        if "sa_time_bucket_" in probe:
            return True
        if "时间感受" in probe or "time_feeling" in probe or "time_bucket" in probe:
            return unit_role == "attribute" or bool(attribute_name)
        return False

    def _lookup_or_materialize_structure_from_profile(
        self,
        *,
        hdb: Any,
        target_profile: dict[str, Any],
        source_structure_id: str,
        trace_id: str,
        tick_id: str,
    ) -> dict[str, Any] | None:
        structure_store = getattr(hdb, "_structure_store", None)
        pointer_index = getattr(hdb, "_pointer_index", None)
        cut_engine = getattr(hdb, "_cut", None)
        if structure_store is None or pointer_index is None or cut_engine is None:
            return None

        normalized_profile = cut_engine.build_sequence_profile_from_groups(
            list(target_profile.get("sequence_groups", []) or [])
        )
        profile_ext = dict(target_profile.get("ext", {}) or {}) if isinstance(target_profile.get("ext", {}), dict) else {}
        profile_ext.update(dict(normalized_profile.get("ext", {}) or {}) if isinstance(normalized_profile.get("ext", {}), dict) else {})
        context_free_identity = bool(
            self._config.get("time_factor_stripped_projection_context_free_identity_enabled", True)
        )
        context_owner_structure_id = str(profile_ext.get("context_owner_structure_id", "") or source_structure_id).strip()
        if context_free_identity:
            for key in ("context_ref_object_id", "context_ref_object_type", "context_owner_structure_id", "context_path_ids"):
                profile_ext.pop(key, None)
            if source_structure_id:
                profile_ext.setdefault("provenance_owner_structure_id", source_structure_id)
        else:
            profile_ext.setdefault("context_owner_structure_id", context_owner_structure_id)
            profile_ext.setdefault("context_ref_object_id", profile_ext.get("context_ref_object_id", "") or context_owner_structure_id)
            profile_ext.setdefault("context_ref_object_type", profile_ext.get("context_ref_object_type", "") or "st")
        profile_ext["time_factor_stripped_projection"] = True
        profile_ext["time_projection_source_structure_id"] = source_structure_id
        profile_ext["identity_context_free"] = context_free_identity
        result = resolve_or_create_structure_from_profile(
            profile={
                **dict(normalized_profile),
                "display_text": str(
                    normalized_profile.get("display_text", "")
                    or target_profile.get("display_text", "")
                    or target_profile.get("content_signature", "")
                    or ""
                ),
                "ext": profile_ext,
            },
            structure_store=structure_store,
            pointer_index=pointer_index,
            cut_engine=cut_engine,
            trace_id=f"{trace_id}_time_projection_materialize" if trace_id else "time_projection_materialize",
            tick_id=tick_id or trace_id or "time_projection_materialize",
            confidence=0.74,
            origin="time_factor_stripped_projection",
            origin_id=str(
                normalized_profile.get("content_signature", "")
                or target_profile.get("content_signature", "")
                or ""
            ),
            parent_ids=[] if context_free_identity else ([source_structure_id] if source_structure_id else []),
            ext=profile_ext,
            source_interface="run_time_feeling_tick",
            strict_context_owner_match=False if context_free_identity else bool(context_owner_structure_id),
            require_context_free=context_free_identity,
        )
        created_structure = result.get("structure") if isinstance(result, dict) else None
        if not isinstance(created_structure, dict):
            return None
        created_inner = created_structure.get("structure", {}) if isinstance(created_structure.get("structure", {}), dict) else {}
        structure_id = str(created_structure.get("id", "") or "")
        if source_structure_id and structure_id and structure_id != source_structure_id and hasattr(structure_store, "add_diff_entry"):
            try:
                structure_store.add_diff_entry(
                    source_structure_id,
                    target_id=structure_id,
                    content_signature=str(created_inner.get("content_signature", "") or ""),
                    base_weight=0.72,
                    residual_existing_signature="",
                    residual_incoming_signature=str(normalized_profile.get("content_signature", "") or ""),
                    ext={
                        "relation_type": "time_factor_stripped_projection",
                        "kind": "time_factor_stripped_projection",
                        "context_owner_structure_id": context_owner_structure_id,
                        "context_ref_object_id": context_owner_structure_id,
                        "context_ref_object_type": "st",
                    },
                )
            except Exception:
                pass
        return {
            "structure_id": structure_id,
            "display_text": str(created_inner.get("display_text", "") or normalized_profile.get("content_signature", "") or ""),
            "content_signature": str(created_inner.get("content_signature", "") or normalized_profile.get("content_signature", "") or ""),
            "created": bool(result.get("created", False)),
            "order": 0,
        }

    @staticmethod
    def _dual_bucket_weights(buckets: list[dict[str, Any]], t_sec: float) -> tuple[str, float, str, float]:
        """
        Dual-bucket interpolation.
        双桶插值：找到 t 在中心点序列中的相邻两桶，并按距离线性分配权重。

        返回：
          (bucket_id_1, weight_1, bucket_id_2, weight_2)
        """
        if not buckets:
            return "", 0.0, "", 0.0
        centers = [float(b.get("center_sec", 0.0) or 0.0) for b in buckets]
        ids = [str(b.get("id", "") or "") for b in buckets]

        # Clamp to edges / 边界钳制
        if t_sec <= centers[0]:
            return ids[0], 1.0, ids[0], 0.0
        if t_sec >= centers[-1]:
            return ids[-1], 1.0, ids[-1], 0.0

        # Find neighbors / 找相邻中心点
        for i in range(len(centers) - 1):
            c1 = centers[i]
            c2 = centers[i + 1]
            if c1 <= t_sec <= c2:
                span = max(1e-9, float(c2 - c1))
                w2 = float(t_sec - c1) / span
                w2 = max(0.0, min(1.0, w2))
                w1 = 1.0 - w2
                return ids[i], w1, ids[i + 1], w2

        # Fallback / 回退
        return ids[0], 1.0, ids[0], 0.0

    @staticmethod
    def _elapsed_ms(start_time: float) -> int:
        return int((time.time() - start_time) * 1000)

    @staticmethod
    def _make_response(success: bool, code: str, message: str, *, data: dict, trace_id: str, elapsed_ms: int) -> dict[str, Any]:
        return {
            "success": bool(success),
            "code": str(code),
            "message": str(message),
            "data": data,
            "trace_id": trace_id,
            "elapsed_ms": int(elapsed_ms),
        }
