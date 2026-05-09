# -*- coding: utf-8 -*-
"""
AP 状态池模块（State Pool Module, SPM）— 主模块
=================================================
AP 运行态认知层核心中枢。负责维护当前活跃认知图景。

对外接口 (8个):
  1. apply_stimulus_packet()          — 接收刺激包
  2. apply_energy_update()            — 定向能量更新
  3. bind_attribute_node_to_object()  — 属性绑定
  4. insert_runtime_node()            — 手动插入运行态对象
  5. tick_maintain_state_pool()       — Tick 维护
  6. get_state_snapshot()             — 状态快照
  7. reload_config()                  — 热加载配置
  8. clear_state_pool()               — 清空状态池

职责边界:
  ✓ 接收刺激、维护对象、更新能量与认知压、衰减/中和/淘汰/合并
  ✓ 属性绑定、脚本检查抄送、快照输出、占位接口联调
  ✗ 不负责感受器残响、长期存储(HDB)、脚本判断、情绪更新、行动决策
"""

import os
import time
import traceback
import copy
import heapq
from collections import Counter
from pathlib import Path
from typing import Any

# ---- 子模块 ----
from ._pool_store import PoolStore
from ._state_item_builder import build_state_item, SUPPORTED_REF_TYPES
from ._id_generator import next_id
from ._energy_engine import EnergyEngine
from ._neutralization_engine import NeutralizationEngine
from ._merge_engine import MergeEngine
from ._binding_engine_v2 import BindingEngine
from ._maintenance_engine import MaintenanceEngine
from ._snapshot_engine import SnapshotEngine
from ._history_window import HistoryWindow
from ._logger import ModuleLogger
from ._audit import AuditLogger
from ._semantic_identity import semantic_context_key_from_item
from . import __version__, __schema_version__, __module_name__


# ====================================================================== #
#                          配置加载工具                                    #
# ====================================================================== #

def _load_yaml_config(path: str) -> dict:
    """加载 YAML 配置文件。加载失败返回空 dict。"""
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except ImportError:
        return {}
    except Exception:
        return {}


# ====================================================================== #
#                          默认配置                                       #
# ====================================================================== #

_DEFAULT_CONFIG = {
    "pool_max_items": 5000,
    "insert_zero_energy_object": True,
    "allow_negative_energy": False,
    "energy_update_floor_to_zero": True,
    "energy_injection_fatigue_enabled": True,
    "energy_injection_fatigue_same_side_knee_er": 4.0,
    "energy_injection_fatigue_same_side_knee_ev": 3.0,
    "energy_injection_fatigue_total_knee": 8.0,
    "energy_injection_fatigue_saturation_power": 1.25,
    "energy_injection_fatigue_total_weight": 0.35,
    "energy_injection_fatigue_min_scale": 0.18,
    "energy_injection_repeat_fatigue_enabled": True,
    "energy_injection_repeat_fatigue_identity_enabled": True,
    "energy_injection_repeat_fatigue_step": 0.35,
    "energy_injection_repeat_fatigue_decay_per_tick": 0.90,
    "energy_injection_repeat_fatigue_floor_scale": 0.04,
    "energy_injection_repeat_fatigue_identity_weight": 1.0,
    "energy_injection_fatigue_stats_keep_ticks": 256,
    "energy_injection_fatigue_bypass_reasons": [
        "tick_decay",
        "attention_memory_extract",
        "priority_stimulus_real_verification",
        "priority_stimulus_virtual_confirmation",
        "priority_neutralization_sa_projection_sync",
        "priority_event_component_neutralization",
    ],
    "tick_time_floor_ms": 1,
    "recency_gain_peak": 10.0,
    "recency_gain_decay_ratio": 0.9999976974,
    "recency_gain_hold_ticks": 2,
    "fatigue_window_ticks": 12,
    "fatigue_threshold_count": 3,
    "fatigue_max_value": 1.0,
    "default_er_decay_ratio": 0.95,
    "default_ev_decay_ratio": 0.98,
    # Runtime-bound attributes decay (CFS/time-feeling/rwd/pun tags, etc.)
    # 运行态绑定属性的半衰期/衰减：用于让“认知感受”等属性具备持续态，而不是只有触发峰值。
    "bound_attribute_apply_decay": True,
    "bound_attribute_er_decay_ratio": 0.97,
    "bound_attribute_ev_decay_ratio": 0.97,
    "bound_attribute_decay_ignore_names": [],
    # CFS conservation-style transform (MVP): dissonance drop -> correctness rise (same amount).
    "enable_cfs_correctness_transfer": True,
    "cfs_dissonance_attribute_name": "cfs_dissonance",
    "cfs_correctness_attribute_name": "cfs_correctness",
    # Snapshot payload size control
    "snapshot_bound_attribute_energy_top_n": 64,
    "snapshot_energy_top_k": 5,
    "enable_snapshot_item_summary_cache": True,
    "snapshot_item_summary_cache_max_entries": 8192,
    "snapshot_item_summary_copy_mode": "shallow",
    # soft_capacity_* / 状态池“软上限”衰减调制
    # 说明：当对象数量超过 soft_capacity_start_items 后，维护阶段衰减会变得更激进，
    # 以避免状态池规模无界增长（尤其是原型调试阶段）。
    # 算法：ratio' = ratio ** decay_power，decay_power 随对象数量线性从 1 -> soft_capacity_decay_power_max。
    "soft_capacity_enabled": True,
    "soft_capacity_start_items": 100,
    "soft_capacity_full_items": 800,
    # 经验值（验收口径）：在严重超载时，希望“每 tick 最多可衰减到约剩余 20%”（约 80% 衰减），
    # 以便状态池能在调试阶段快速自我收缩、避免对象数量无界增长。
    # 注意：由于 ER/EV 基础保留系数不同（默认 ER=0.95, EV=0.90），同一 power 下 EV 会更快衰减。
    "soft_capacity_decay_power_max": 30.0,
    "per_object_type_decay_override": {},
    "enable_neutralization": True,
    "neutralization_mode": "simple_min_cancel",
    "neutralization_apply_stage": "maintenance",
    "neutralization_min_effect_threshold": 0.01,
    "maintenance_emit_decay_events_enabled": False,
    "enable_priority_stimulus_neutralization": True,
    "priority_stimulus_target_ref_types": ["st"],
    "priority_neutralization_settlement_mode": "structure_match_sa_settlement",
    "priority_neutralization_min_effect_threshold": 0.01,
    "priority_neutralization_soft_matching_enabled": True,
    "priority_neutralization_candidate_cp_min": 0.05,
    "priority_neutralization_min_match_score": 0.35,
    "priority_neutralization_min_structure_coverage": 0.45,
    "priority_neutralization_candidate_top_k": 48,
    "priority_neutralization_emit_pruned_diagnostics": False,
    "priority_neutralization_common_part_cache_enabled": False,
    "priority_neutralization_common_part_cache_deepcopy_enabled": False,
    "priority_neutralization_common_part_cache_max_entries": 512,
    "priority_neutralization_common_group_length_cache_max_entries": 4096,
    "enable_event_component_neutralization": True,
    "event_component_neutralization_ratio_cap": 1.0,
    "er_elimination_threshold": 0.05,
    "ev_elimination_threshold": 0.05,
    "cp_elimination_ignore_below": 0.02,
    "prune_if_both_energy_low": True,
    "pool_overflow_strategy": "prune_lowest_then_reject",
    "enable_change_rate_tracking": True,
    "rate_window_mode": "last_update",
    "fast_cp_rise_threshold": 0.5,
    "fast_cp_drop_threshold": -0.5,
    "fast_er_rise_threshold": 0.5,
    "fast_ev_rise_threshold": 0.5,
    "rate_smoothing_alpha": 1.0,
    "merge_duplicate_items": True,
    "merge_only_same_ref_object": True,
    "enable_semantic_same_object_merge": True,
    "enable_semantic_context_same_object_merge": True,
    "allow_weak_semantic_merge": False,
    "aggregate_same_semantic_incoming_objects": True,
    # runtime_structure_* / 运行态结构分辨率
    # 新口径：结构退化只是 StatePool 运行态分辨率下降，不重新查存一体、不创建新的 HDB 身份。
    "runtime_structure_root_identity_merge_enabled": True,
    "runtime_structure_resolution_degradation_enabled": True,
    "runtime_structure_resolution_component_energy_floor": 0.05,
    "runtime_structure_resolution_update_display_enabled": False,
    "enable_state_item_template_cache": True,
    "state_item_template_cache_max_entries": 8192,
    "sensor_input_reconcile_mode": "max",
    "memory_feedback_packet_additive_merge_enabled": True,
    "induction_packet_additive_merge_enabled": True,
    "induction_packet_ref_hit_fast_apply_enabled": True,
    "induction_packet_new_sa_fast_materialize_enabled": True,
    "induction_packet_fast_event_materialization_enabled": False,
    # 是否把 CSA（组合刺激元）作为独立 state_item 写入状态池。
    # 注意：理论层面 CSA 是“匹配约束单元”，工程上不一定要以独立对象存在于 SP。
    # 当前原型默认不写入 CSA，避免与 SA 同时存在导致展示混乱与维护成本上升。
    "insert_csa_as_state_item": False,
    # 是否把“属性 SA”（stimulus.role == attribute）作为独立 state_item 写入状态池。
    # 新口径默认开启：属性刺激元与普通 SA 等价，可独立入池、竞争、被注意、进入内源刺激。
    # 旧式“只挂在锚点对象上、不作为运行态对象存在”的路径仅作为兼容开关保留。
    "insert_attribute_sa_as_state_item": True,
    # 属性绑定接口默认运行语义：
    # - state_item: 把属性 SA 作为一等运行态对象入池，并附带锚点上下文信息
    # - legacy_bind: 仅写入锚点对象的 runtime binding（旧口径兼容）
    "attribute_binding_runtime_mode": "state_item",
    # 绑定属性时是否自动创建“绑定型 CSA”state_item（synthetic）。
    # 当前原型默认关闭：CSA 主要在 packet/HDB 中承担匹配约束作用，运行态 SP 以 SA/ST 为主。
    "allow_auto_create_csa_on_attribute_bind": False,
    "attribute_bind_deduplicate_by_id": True,
    "attribute_bind_deduplicate_by_content": False,
    # 绑定属性时的“替换语义”（对齐理论：同一属性名在同一对象上应保持唯一）
    # - true: 若目标对象已存在同名 attribute_name，则替换旧属性（更贴近“额外约束信息”的语义）
    # - false: 允许同名属性重复绑定（更像“多次打标签”），可能导致 runtime_attrs 爆炸
    #
    # Attribute binding replace semantics:
    # - true: replace existing attribute with the same attribute_name
    # - false: allow duplicates (can blow up runtime_attrs)
    "attribute_bind_replace_by_attribute_name": True,
    "attribute_binding_supported_target_types": ["sa", "csa", "st"],
    "enable_script_broadcast": True,
    "script_broadcast_stage_after_apply": True,
    "script_broadcast_stage_after_maintenance": True,
    "script_broadcast_include_full_event_dump": True,
    "script_broadcast_top_k_items": 128,
    "script_broadcast_min_event_count": 1,
    "enable_placeholder_interfaces": True,
    "placeholder_hdb_enabled": True,
    "placeholder_script_enabled": True,
    "placeholder_attention_enabled": True,
    "placeholder_emotion_enabled": True,
    "placeholder_action_enabled": True,
    "detail_log_dump_full_object": True,
    "detail_log_dump_change_event": False,
    "history_window_max_events": 5000,
    "log_dir": "",
    "log_max_file_bytes": 5 * 1024 * 1024,
    "log_archive_keep_per_level": {
        "error": 64,
        "brief": 24,
        "detail": 24,
    },
    "stdout_fallback_when_log_fail": True,
}


# ====================================================================== #
#                       StatePool 主类                                     #
# ====================================================================== #


class StatePool:
    """
    AP 状态池主类。

    使用示例:
        pool = StatePool()
        result = pool.apply_stimulus_packet(stimulus_packet=pkt, trace_id="tick_001")
    """

    def __init__(self, config_path: str = "", config_override: dict | None = None):
        """
        初始化状态池。

        参数:
            config_path: YAML 配置文件路径
            config_override: 直接传入配置 dict（优先级最高）
        """
        # 合并配置
        self._config_path = config_path or os.path.join(
            os.path.dirname(__file__), "config", "state_pool_config.yaml"
        )
        self._config = self._build_config(config_override)

        # 初始化子模块
        self._logger = ModuleLogger(
            log_dir=self._config.get("log_dir", ""),
            max_file_bytes=self._config.get("log_max_file_bytes", 5 * 1024 * 1024),
            archive_keep_per_level=self._config.get("log_archive_keep_per_level"),
            enable_stdout_fallback=self._config.get("stdout_fallback_when_log_fail", True),
        )
        self._audit = AuditLogger(self._logger)
        self._store = PoolStore(self._config)
        self._energy = EnergyEngine(self._config)
        self._neutralization = NeutralizationEngine(self._config)
        self._merge = MergeEngine(self._config)
        self._binding = BindingEngine(self._config)
        self._maintenance = MaintenanceEngine(self._config)
        self._snapshot = SnapshotEngine(self._config)
        self._history = HistoryWindow(self._config)

        # 运行统计
        self._tick_counter: int = 0
        self._total_calls: int = 0
        self._total_items_created: int = 0
        self._state_item_template_cache: dict[tuple, dict] = {}
        self._priority_neutralization_group_stats_cache: dict[tuple, dict] = {}
        self._priority_neutralization_cut_engine = None
        self._priority_neutralization_cut_engine_config_key: tuple | None = None

        # 占位接口引用（延迟导入）
        self._placeholder_interfaces: dict = {}

    # ================================================================== #
    #   接口一: apply_stimulus_packet — 接收刺激包                         #
    # ================================================================== #

    def apply_stimulus_packet(
        self,
        stimulus_packet: dict,
        trace_id: str,
        tick_id: str | None = None,
        source_module: str | None = None,
        apply_mode: str = "normal",
        enable_script_broadcast: bool = True,
        enable_brief_log: bool = True,
        compute_post_apply_summary: bool = True,
        clone_packet_for_safety: bool | None = None,
        enable_change_event_log: bool = True,
        metadata: dict | None = None,
    ) -> dict:
        """
        接收刺激包并将其中对象写入或更新状态池。

        处理流程:
          1. 校验 packet
          2. 拆分合法/非法对象
          3. 映射为候选 state_item
          4. 查重、合并或新建
          5. 赋能并刷新动态指标
          6. 即时中和（若配置）
          7. 广播脚本检查
        """
        start_time = time.time()
        tick_id = tick_id or trace_id
        self._total_calls += 1
        self._tick_counter += 1
        tick_number = self._tick_counter

        # ---- Step 1: 参数校验 ----
        err = self._validate_stimulus_packet(stimulus_packet, trace_id, apply_mode)
        if err:
            self._logger.error(
                trace_id=trace_id, interface="apply_stimulus_packet",
                code=err["code"], message_zh=err["message_zh"], message_en=err["message_en"],
                tick_id=tick_id, detail=err.get("detail"),
            )
            return self._make_response(False, err["code"],
                f"{err['message_zh']} / {err['message_en']}",
                error=err, trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time))

        if apply_mode == "validation_only":
            return self._make_response(True, "OK",
                "校验通过（validation_only 模式不入池）/ Validation passed (not applied)",
                trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time))

        if clone_packet_for_safety is None:
            clone_packet_for_safety = bool(
                apply_mode == "normal"
                and self._config.get("enable_priority_stimulus_neutralization", True)
            )
        working_packet = (
            self._clone_stimulus_packet(stimulus_packet)
            if clone_packet_for_safety
            else (stimulus_packet if isinstance(stimulus_packet, dict) else {})
        )
        neutralization_result: dict[str, Any] = {}
        pre_neutralization_events: list[dict] = []
        priority_neutralization_diagnostics: list[dict] = []
        priority_neutralized_item_count = 0
        priority_event_component_summary = {
            "event_component_neutralization_count": 0,
            "event_component_neutralization_er_added_sum": 0.0,
            "event_component_neutralization_ev_added_sum": 0.0,
            "event_component_cp_drop_sum": 0.0,
        }
        priority_cut_metrics: dict[str, int] = {}
        if apply_mode == "normal" and self._config.get("enable_priority_stimulus_neutralization", True):
            neutralization_result = self._priority_neutralize_stimulus_packet(
                stimulus_packet=working_packet,
                tick_number=tick_number,
                trace_id=trace_id,
                tick_id=tick_id,
                source_module=source_module or "text_sensor",
            )
            working_packet = neutralization_result["residual_packet"]
            pre_neutralization_events = neutralization_result["events"]
            priority_neutralization_diagnostics = list(neutralization_result.get("diagnostics", []))
            priority_neutralized_item_count = neutralization_result["neutralized_item_count"]
            priority_cut_metrics = {
                str(key): int(value)
                for key, value in dict(neutralization_result.get("cut_metrics", {}) or {}).items()
                if str(key)
            }
            priority_event_component_summary = {
                "event_component_neutralization_count": int(neutralization_result.get("event_component_neutralization_count", 0) or 0),
                "event_component_neutralization_er_added_sum": round(float(neutralization_result.get("event_component_neutralization_er_added_sum", 0.0) or 0.0), 8),
                "event_component_neutralization_ev_added_sum": round(float(neutralization_result.get("event_component_neutralization_ev_added_sum", 0.0) or 0.0), 8),
                "event_component_cp_drop_sum": round(float(neutralization_result.get("event_component_cp_drop_sum", 0.0) or 0.0), 8),
            }

        # ---- Step 2: 拆分对象 ----
        # SA 是状态池的主要输入对象。
        # CSA/属性 SA 在理论中更像“绑定约束信息”，工程上不一定要作为独立 state_item 常驻于 SP。
        sa_items = list(working_packet.get("sa_items", []) or [])
        csa_items = list(working_packet.get("csa_items", []) or [])

        # 如需调试/观测 CSA 聚合视图，可通过 insert_csa_as_state_item 打开写入。
        store_csa = bool(self._config.get("insert_csa_as_state_item", False))
        # 如需调试/观测属性 SA（例如 stimulus_intensity:1.1），可通过 insert_attribute_sa_as_state_item 打开写入。
        store_attr = bool(self._config.get("insert_attribute_sa_as_state_item", False))

        feature_sa_items: list[dict] = []
        attribute_sa_items: list[dict] = []
        for sa in sa_items:
            if not isinstance(sa, dict):
                continue
            if str(sa.get("object_type", "")) != "sa":
                continue
            role = str(sa.get("stimulus", {}).get("role", "") or "")
            if role == "attribute":
                attribute_sa_items.append(sa)
            else:
                feature_sa_items.append(sa)

        # object_lookup 用于 build_state_item 生成语义签名与轻量快照；必须包含“完整对象视图”。
        # 注意：即使我们选择不把某类对象写入 SP，也应让它参与快照生成与绑定同步。
        object_lookup = {
            str(obj.get("id", "")): obj
            for obj in (list(sa_items) + list(csa_items))
            if isinstance(obj, dict) and str(obj.get("id", ""))
        }

        # 预先收集“锚点 -> 属性成员”映射：用于
        # 1) 当 store_attr=False 时，把属性 SA 的能量折叠进锚点 SA（避免能量丢失）
        # 2) 让锚点对象保存一份稳定的属性视图（便于观测；避免 SA/CSA 双份共存）
        attr_energy_by_anchor: dict[str, dict[str, float | int]] = {}
        attrs_by_anchor: dict[str, list[dict]] = {}
        for attr in attribute_sa_items:
            parent_ids = list(attr.get("source", {}).get("parent_ids", []) or [])
            anchor_id = str(parent_ids[0]) if parent_ids else ""
            if not anchor_id:
                continue
            attrs_by_anchor.setdefault(anchor_id, []).append(attr)
            energy = attr.get("energy", {}) or {}
            bucket = attr_energy_by_anchor.setdefault(anchor_id, {"er": 0.0, "ev": 0.0, "count": 0})
            bucket["er"] = float(bucket.get("er", 0.0)) + float(energy.get("er", 0.0) or 0.0)
            bucket["ev"] = float(bucket.get("ev", 0.0)) + float(energy.get("ev", 0.0) or 0.0)
            bucket["count"] = int(bucket.get("count", 0) or 0) + 1

        # 默认：只把“特征 SA”写入 SP；属性 SA/CSA 只做绑定约束信息（可通过开关打开写入）。
        all_objects = list(feature_sa_items)
        if store_attr:
            all_objects.extend(attribute_sa_items)
        if store_csa:
            all_objects.extend(list(csa_items))

        valid_objects: list[dict] = []
        rejected_count = 0
        for obj in all_objects:
            if not isinstance(obj, dict) or not obj.get("id") or not obj.get("energy"):
                rejected_count += 1
                continue
            valid_objects.append(obj)

        # ---- Step 3~5: 映射、查重、赋能 ----
        all_events: list[dict] = list(pre_neutralization_events)
        new_count = 0
        updated_count = 0
        merged_count = 0
        applied_ids = [
            str(item_id)
            for item_id in neutralization_result.get("applied_state_item_ids", [])
            if str(item_id)
        ] if isinstance(neutralization_result, dict) else []
        if not applied_ids:
            applied_ids = [
                event.get("target_item_id", "")
                for event in pre_neutralization_events
                if event.get("target_item_id", "")
            ]
        induction_fast_emit_events = bool(
            self._config.get("induction_packet_fast_event_materialization_enabled", False)
            or enable_script_broadcast
            or enable_change_event_log
        )
        if (
            apply_mode == "normal"
            and str(source_module or "") == "hdb_induction"
            and bool(self._config.get("induction_packet_ref_hit_fast_apply_enabled", True))
            and bool(self._config.get("induction_packet_additive_merge_enabled", True))
            and not bool(self._config.get("aggregate_same_semantic_incoming_objects", False))
        ):
            (
                valid_objects,
                fast_events,
                fast_applied_ids,
                fast_updated_count,
                fast_merged_count,
            ) = self._apply_induction_ref_hit_objects_fast(
                valid_objects=valid_objects,
                attr_energy_by_anchor=attr_energy_by_anchor,
                store_attr=store_attr,
                tick_number=tick_number,
                trace_id=trace_id,
                tick_id=tick_id,
                source_module=source_module or "hdb_induction",
                enable_change_event_log=enable_change_event_log,
                emit_events=induction_fast_emit_events,
            )
            if fast_events:
                all_events.extend(fast_events)
                applied_ids.extend(fast_applied_ids)
                updated_count += fast_updated_count
                merged_count += fast_merged_count
        if (
            apply_mode == "normal"
            and str(source_module or "") == "hdb_induction"
            and bool(self._config.get("induction_packet_new_sa_fast_materialize_enabled", True))
            and not bool(self._config.get("enable_semantic_same_object_merge", False))
            and not bool(self._config.get("aggregate_same_semantic_incoming_objects", False))
        ):
            (
                valid_objects,
                fast_new_events,
                fast_new_applied_ids,
                fast_new_count,
                fast_new_merged_count,
                fast_new_rejected_count,
            ) = self._apply_induction_new_sa_objects_fast(
                valid_objects=valid_objects,
                attr_energy_by_anchor=attr_energy_by_anchor,
                store_attr=store_attr,
                tick_number=tick_number,
                trace_id=trace_id,
                tick_id=tick_id,
                source_module=source_module or "hdb_induction",
                origin_id=working_packet.get("id", ""),
                enable_change_event_log=enable_change_event_log,
                emit_events=induction_fast_emit_events,
            )
            if fast_new_events:
                all_events.extend(fast_new_events)
            if fast_new_applied_ids:
                applied_ids.extend(fast_new_applied_ids)
            new_count += fast_new_count
            merged_count += fast_new_merged_count
            rejected_count += fast_new_rejected_count
        application_groups: dict[str, dict] = {}
        candidate_template_cache: dict[tuple, dict] = {}
        packet_type = str(working_packet.get("packet_type", "") or "")
        use_candidate_template_cache = bool(
            self._config.get("enable_state_item_template_cache", True)
            and (
                source_module == "hdb_induction"
                or packet_type.startswith("induction_")
            )
        )

        for obj in valid_objects:
            candidate = None
            template_key = self._state_item_template_cache_key(obj) if use_candidate_template_cache else None
            template = None
            if template_key is not None:
                template = candidate_template_cache.get(template_key)
                if template is None:
                    template = self._state_item_template_cache.get(template_key)
                    if template is not None:
                        candidate_template_cache[template_key] = template
            if template is not None:
                candidate = self._clone_state_item_template_for_ref(
                    template,
                    ref_object=obj,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    tick_number=tick_number,
                    source_module=source_module or "text_sensor",
                    source_interface="apply_stimulus_packet",
                    origin="from_stimulus_packet",
                    origin_id=working_packet.get("id", ""),
                )
            else:
                candidate = build_state_item(
                    ref_object=obj, trace_id=trace_id, tick_id=tick_id,
                    tick_number=tick_number, source_module=source_module or "text_sensor",
                    source_interface="apply_stimulus_packet",
                    origin="from_stimulus_packet",
                    origin_id=working_packet.get("id", ""),
                    object_lookup=object_lookup,
                )
                if candidate is not None and template_key is not None:
                    cached_template = self._copy_state_item_template_for_cache(candidate)
                    candidate_template_cache[template_key] = cached_template
                    self._remember_state_item_template(template_key, cached_template)
            if candidate is None:
                rejected_count += 1
                continue

            packet_context = obj.get("ext", {}).get("packet_context", {})
            should_group_by_semantic = (
                bool(packet_context)
                and self._config.get("aggregate_same_semantic_incoming_objects", True)
                and bool(candidate.get("semantic_context_key") or candidate.get("semantic_signature"))
            )

            if should_group_by_semantic:
                aggregate_key = f"semantic_context::{candidate.get('semantic_context_key') or candidate.get('semantic_signature')}"
            else:
                aggregate_key = f"ref::{candidate.get('ref_object_id', '')}"

            group = application_groups.setdefault(
                aggregate_key,
                {
                    "entries": [],
                    "total_er": 0.0,
                    "total_ev": 0.0,
                    # Folded packet attributes (when attribute SA is not stored as state items).
                    # 折叠的属性 SA 统计（当属性 SA 不入池时）。
                    "folded_attribute_sa_count": 0,
                    "folded_attribute_total_er": 0.0,
                    "folded_attribute_total_ev": 0.0,
                    "has_packet_context": False,
                    "source_types": set(),
                },
            )
            group["entries"].append(
                {
                    "ref_object": obj,
                    "candidate": candidate,
                    "packet_context": packet_context,
                }
            )
            group["total_er"] += candidate["energy"]["er"]
            group["total_ev"] += candidate["energy"]["ev"]

            # Fold attribute SA energy into the anchor SA when we choose not to store attributes as state items.
            # 把属性 SA 的能量折叠进锚点 SA（当属性 SA 不入池时），避免能量丢失并减少噪音对象数量。
            if (not store_attr
                and str(obj.get("object_type", "")) == "sa"
                and str(obj.get("stimulus", {}).get("role", "") or "") != "attribute"):
                anchor_id = str(obj.get("id", "") or "")
                folded = attr_energy_by_anchor.get(anchor_id) or {}
                extra_er = float(folded.get("er", 0.0) or 0.0)
                extra_ev = float(folded.get("ev", 0.0) or 0.0)
                extra_count = int(folded.get("count", 0) or 0)
                if extra_count and (extra_er or extra_ev):
                    group["total_er"] += extra_er
                    group["total_ev"] += extra_ev
                    group["folded_attribute_sa_count"] += extra_count
                    group["folded_attribute_total_er"] += extra_er
                    group["folded_attribute_total_ev"] += extra_ev
            if packet_context:
                group["has_packet_context"] = True
                source_type = packet_context.get("source_type", "")
                if source_type:
                    group["source_types"].add(source_type)

        for group in application_groups.values():
            entries = group["entries"]
            if len(entries) == 1:
                representative = entries[0]["candidate"]
            else:
                representative = self._select_representative_candidate(entries)
            representative = self._synchronize_candidate_with_group(
                representative,
                entries=entries,
                total_er=group["total_er"],
                total_ev=group["total_ev"],
            )
            if group.get("folded_attribute_sa_count", 0):
                ext = representative.setdefault("ext", {})
                ext["incoming_packet_folded_attribute_sa_count"] = int(group.get("folded_attribute_sa_count", 0) or 0)
                ext["incoming_packet_folded_attribute_total_er"] = round(float(group.get("folded_attribute_total_er", 0.0) or 0.0), 8)
                ext["incoming_packet_folded_attribute_total_ev"] = round(float(group.get("folded_attribute_total_ev", 0.0) or 0.0), 8)
            self._refresh_runtime_resolution_metadata(representative, source="stimulus_packet_representative")

            existing = None
            matched_by_ref = False
            for entry in entries:
                candidate_ref_id = entry["candidate"].get("ref_object_id", "")
                existing = self._store.get_by_ref(candidate_ref_id)
                if existing is not None:
                    matched_by_ref = True
                    break
            if existing is None:
                existing = self._find_existing_item_for_candidate(representative)

            group_collapse_count = max(0, len(entries) - 1)

            if existing is not None:
                if matched_by_ref:
                    match_mode = "ref"
                elif (
                    self._runtime_root_structure_id(existing)
                    and self._runtime_root_structure_id(existing) == self._runtime_root_structure_id(representative)
                ):
                    match_mode = "root_structure"
                else:
                    match_mode = "semantic"

                if apply_mode == "dry_run":
                    updated_count += 1
                    merged_count += group_collapse_count + (1 if match_mode == "semantic" else 0)
                    continue

                source_module_name = str(source_module or "text_sensor")
                allow_memory_feedback_additive_merge = bool(
                    self._config.get("memory_feedback_packet_additive_merge_enabled", True)
                )
                is_memory_feedback_packet = source_module_name in {"memory_feedback", "observatory_memory_feedback"}
                is_induction_packet = source_module_name == "hdb_induction"
                use_packet_reconcile = (
                    group["has_packet_context"]
                    and self._config.get("sensor_input_reconcile_mode", "max") == "max"
                    and not (allow_memory_feedback_additive_merge and is_memory_feedback_packet)
                    and not (self._config.get("induction_packet_additive_merge_enabled", True) and is_induction_packet)
                )
                if use_packet_reconcile:
                    event = self._reconcile_candidate_on_existing(
                        existing_item=existing,
                        candidate_item=representative,
                        incoming_er=group["total_er"],
                        incoming_ev=group["total_ev"],
                        tick_number=tick_number,
                        reason=f"stimulus_apply_{match_mode}_reconcile",
                        source_module=source_module or "text_sensor",
                        trace_id=trace_id,
                        tick_id=tick_id,
                    )
                    event["merge_mode"] = f"{match_mode}_reconcile"
                else:
                    event = self._merge_candidate_into_existing(
                        existing_item=existing,
                        candidate_item=representative,
                        merge_mode=match_mode,
                        tick_number=tick_number,
                        reason=(
                            "stimulus_apply_semantic_merge"
                            if match_mode == "semantic"
                            else "stimulus_apply_ref_hit"
                        ),
                        source_module=source_module or "text_sensor",
                        trace_id=trace_id,
                        tick_id=tick_id,
                    )

                event["incoming_member_count"] = len(entries)
                event["packet_source_types"] = sorted(group["source_types"])
                all_events.append(event)
                applied_ids.append(existing["id"])
                updated_count += 1
                merged_count += group_collapse_count + (1 if match_mode == "semantic" else 0)
                if enable_change_event_log:
                    self._log_change_event(event, trace_id, tick_id)
                continue

            if apply_mode == "dry_run":
                new_count += 1
                merged_count += group_collapse_count
                continue

            # 检查零能量
            er = representative["energy"]["er"]
            ev = representative["energy"]["ev"]
            if er == 0 and ev == 0 and not self._config.get("insert_zero_energy_object", True):
                rejected_count += 1
                continue

            self._energy.seed_runtime_modulation(representative, tick_number)
            inserted = self._store.insert(representative)
            if inserted:
                self._total_items_created += 1
                applied_ids.append(representative["id"])
                new_count += 1
                merged_count += group_collapse_count
                event = {
                    "event_id": f"new_{representative['id']}",
                    "event_type": "created",
                    "target_item_id": representative["id"],
                    "trace_id": trace_id, "tick_id": tick_id,
                    "timestamp_ms": int(time.time() * 1000),
                    "before": {"er": 0.0, "ev": 0.0, "cp_delta": 0.0, "cp_abs": 0.0},
                    "after": {
                        "er": er,
                        "ev": ev,
                        "cp_delta": representative["energy"]["cognitive_pressure_delta"],
                        "cp_abs": representative["energy"]["cognitive_pressure_abs"],
                    },
                    "delta": {
                        "delta_er": er,
                        "delta_ev": ev,
                        "delta_cp_delta": representative["energy"]["cognitive_pressure_delta"],
                        "delta_cp_abs": representative["energy"]["cognitive_pressure_abs"],
                    },
                    "rate": {
                        "er_change_rate": er,
                        "ev_change_rate": ev,
                        "cp_delta_rate": representative["energy"]["cognitive_pressure_delta"],
                        "cp_abs_rate": representative["energy"]["cognitive_pressure_abs"],
                    },
                    "reason": "stimulus_apply_new_item",
                    "source_module": source_module or "text_sensor",
                    "semantic_signature": representative.get("semantic_signature", ""),
                    "incoming_member_count": len(entries),
                    "packet_source_types": sorted(group["source_types"]),
                }
                all_events.append(event)
                if enable_change_event_log:
                    self._log_change_event(event, trace_id, tick_id)
            else:
                rejected_count += 1

        # ---- CSA / Attribute binding sync / CSA 与属性绑定关系同步 ----
        # 理论层面：CSA（组合刺激元）是“对象-属性绑定”的匹配约束单元（门控约束）。
        # 工程层面：当前原型默认不把 CSA/属性 SA 作为独立 state_item 写入 SP，避免 SA/CSA 双份共存导致展示混乱；
        # 但仍需要把“约束信息”融合回锚点对象，保证每个锚点只有一个 CSA 视图（融合规则）。
        if apply_mode == "normal" and (csa_items or attribute_sa_items):
            now_ms = int(time.time() * 1000)

            def _upsert_packet_attribute(*, anchor_item: dict, attribute_sa: dict) -> None:
                """把 packet 内的属性 SA 以“稳定字典”的形式挂到锚点对象上（按 attribute_name 覆写）。"""
                if not isinstance(anchor_item, dict) or not isinstance(attribute_sa, dict):
                    return
                if str(attribute_sa.get("object_type", "")) != "sa":
                    return
                if str(attribute_sa.get("stimulus", {}).get("role", "") or "") != "attribute":
                    return
                content = attribute_sa.get("content", {}) or {}
                attr_name = str(content.get("attribute_name", "") or "")
                if not attr_name:
                    raw = str(content.get("raw", "") or "")
                    if ":" in raw:
                        attr_name = raw.split(":", 1)[0].strip()
                    else:
                        attr_name = raw.strip()
                if not attr_name:
                    return

                display = str(content.get("display", "") or content.get("raw", "") or attribute_sa.get("id", ""))
                value = content.get("attribute_value")
                sa_id = str(attribute_sa.get("id", "") or "")

                binding_state = anchor_item.setdefault("binding_state", {})
                packet_attrs = binding_state.setdefault("packet_attribute_by_name", {})
                packet_attrs[attr_name] = {
                    "attribute_name": attr_name,
                    "attribute_value": value,
                    "display": display,
                    "sa_id": sa_id,
                    "updated_at": now_ms,
                }

                # 轻量快照：用于前端/报告解释（避免把完整 attribute_sa 挂到 ext 里导致膨胀）。
                ref_snapshot = anchor_item.setdefault("ref_snapshot", {})
                ordered = sorted(
                    list(packet_attrs.values()),
                    key=lambda row: str(row.get("attribute_name", "")),
                )
                ref_snapshot["attribute_displays"] = [
                    str(row.get("display", ""))
                    for row in ordered
                    if str(row.get("display", ""))
                ]

                detail_parts = []
                if ref_snapshot.get("attribute_displays"):
                    detail_parts.append(f"attrs={', '.join(ref_snapshot.get('attribute_displays', [])[:4])}")
                bound = list(ref_snapshot.get("bound_attribute_displays", []) or [])
                if bound:
                    detail_parts.append(f"runtime_attrs={', '.join(bound[:4])}")
                if detail_parts:
                    ref_snapshot["content_display_detail"] = " | ".join(detail_parts)

            # If CSA is inserted, keep the legacy link for compatibility.
            # 若选择写入 CSA，则保留旧的“anchor -> csa_item_id”链接，兼容历史逻辑。
            if store_csa:
                for obj in csa_items:
                    if not isinstance(obj, dict) or obj.get("object_type") != "csa":
                        continue
                    csa_ref_id = str(obj.get("id", "") or "")
                    anchor_ref_id = str(obj.get("anchor_sa_id", "") or "")
                    if not csa_ref_id or not anchor_ref_id:
                        continue
                    csa_item = self._store.get_by_ref(csa_ref_id)
                    anchor_item = self._store.get_by_ref(anchor_ref_id)
                    if not csa_item or not anchor_item:
                        continue
                    binding_state = anchor_item.setdefault("binding_state", {})
                    if not binding_state.get("bound_csa_item_id"):
                        binding_state["bound_csa_item_id"] = csa_item.get("id")

            # 1) Sync from attribute SA parent_ids mapping (works even if CSA output is disabled).
            # 1) 优先用 parent_ids 映射同步（即使感受器关闭了 CSA 输出也能工作）。
            for anchor_ref_id, attrs in attrs_by_anchor.items():
                anchor_item = self._store.get_by_ref(anchor_ref_id)
                if not anchor_item:
                    continue
                for attr in attrs:
                    _upsert_packet_attribute(anchor_item=anchor_item, attribute_sa=attr)
                anchor_item["updated_at"] = now_ms
                anchor_item.setdefault("lifecycle", {})["last_active_tick"] = tick_number

            # 2) Sync from CSA member ids (as a fallback/extra safety).
            # 2) 再从 CSA 的 member_ids 同步一次（兜底，避免某些 packet 缺 parent_ids 时丢失）。
            for csa in csa_items:
                if not isinstance(csa, dict) or csa.get("object_type") != "csa":
                    continue
                anchor_ref_id = str(csa.get("anchor_sa_id", "") or "")
                if not anchor_ref_id:
                    continue
                anchor_item = self._store.get_by_ref(anchor_ref_id)
                if not anchor_item:
                    continue
                for member_id in csa.get("member_sa_ids", []) or []:
                    mid = str(member_id or "")
                    if not mid or mid == anchor_ref_id:
                        continue
                    attr_obj = object_lookup.get(mid)
                    if attr_obj:
                        _upsert_packet_attribute(anchor_item=anchor_item, attribute_sa=attr_obj)
                anchor_item["updated_at"] = now_ms
                anchor_item.setdefault("lifecycle", {})["last_active_tick"] = tick_number

        # ---- Step 6: 即时中和 ----
        neut_stage = self._config.get("neutralization_apply_stage", "maintenance")
        neut_count = 0
        if neut_stage in ("immediate", "both") and apply_mode == "normal":
            for spi_id in applied_ids:
                item = self._store.get(spi_id)
                if item:
                    event = self._neutralization.neutralize(
                        item=item, tick_number=tick_number,
                        trace_id=trace_id, tick_id=tick_id,
                    )
                    if event:
                        all_events.append(event)
                        neut_count += 1
                        if enable_change_event_log:
                            self._log_change_event(event, trace_id, tick_id)

        # ---- 记录事件到历史窗口 ----
        self._history.append_many(all_events)

        # ---- Step 7: 脚本广播 ----
        broadcast_sent = False
        if (enable_script_broadcast
            and self._config.get("enable_script_broadcast", True)
            and self._config.get("script_broadcast_stage_after_apply", True)
            and len(all_events) >= self._config.get("script_broadcast_min_event_count", 1)
            and apply_mode == "normal"):
            broadcast_sent = self._broadcast_script_check(all_events, trace_id, tick_id)

        # ---- 能量统计 ----
        total_delta_er = sum(e.get("delta", {}).get("delta_er", 0) for e in all_events if "delta" in e)
        total_delta_ev = sum(e.get("delta", {}).get("delta_ev", 0) for e in all_events if "delta" in e)
        # CP (Option A): sum of per-event |Δ(ER-EV)| so it matches the global CP definition
        # used by the Observatory (Σ|ER_i - EV_i|). This is an "update intensity" proxy.
        total_delta_cp = sum(abs(e.get("delta", {}).get("delta_cp_delta", 0)) for e in all_events if "delta" in e)
        high_cp = len(self._store.get_high_cp_items(0.5)) if compute_post_apply_summary else None

        elapsed = self._elapsed_ms(start_time)

        # Brief 日志
        if enable_brief_log:
            self._logger.brief(
                trace_id=trace_id, interface="apply_stimulus_packet", success=True,
                message_zh="状态池应用刺激包成功", message_en="Stimulus packet applied successfully",
                tick_id=tick_id,
                input_summary={"packet_id": stimulus_packet.get("id", ""),
                               "sa_count": len(sa_items), "csa_count": len(csa_items)},
                output_summary={"new_item_count": new_count, "updated_item_count": updated_count,
                                "merged_item_count": merged_count, "rejected_object_count": rejected_count,
                                "priority_neutralized_item_count": priority_neutralized_item_count,
                                "priority_event_component_neutralization_count": priority_event_component_summary["event_component_neutralization_count"],
                                "residual_sa_count": len(working_packet.get("sa_items", [])),
                                "residual_csa_count": len(working_packet.get("csa_items", [])),
                                "active_item_count": self._store.size, "high_cp_item_count": high_cp,
                                "script_broadcast_sent": broadcast_sent},
            )

        return self._make_response(
            success=True, code="OK",
            message="状态池应用刺激包成功 / Stimulus packet applied successfully",
            data={
                "applied_state_item_ids": applied_ids,
                "new_item_count": new_count,
                "updated_item_count": updated_count,
                "merged_item_count": merged_count,
                "priority_neutralized_item_count": priority_neutralized_item_count,
                "priority_neutralization_diagnostics": priority_neutralization_diagnostics,
                "priority_neutralization_cut_metrics": priority_cut_metrics,
                **priority_event_component_summary,
                "neutralized_item_count": neut_count,
                "rejected_object_count": rejected_count,
                "script_broadcast_sent": broadcast_sent,
                "residual_stimulus_packet": working_packet,
                "state_delta_summary": {
                    "total_delta_er": round(total_delta_er, 6),
                    "total_delta_ev": round(total_delta_ev, 6),
                    "total_delta_cp": round(total_delta_cp, 6),
                    "high_cp_item_count": high_cp,
                },
            },
            trace_id=trace_id, elapsed_ms=elapsed,
        )

    def apply_projection_packet_fast(
        self,
        stimulus_packet: dict,
        trace_id: str,
        tick_id: str | None = None,
        source_module: str | None = None,
        enable_script_broadcast: bool = False,
        enable_brief_log: bool = False,
        compute_post_apply_summary: bool = False,
    ) -> dict:
        """
        Fast path for already-projected structure/memory packets.

        The packet has already been projected into one semantic object shape, so
        we avoid building one candidate per SA and instead build exactly one
        representative candidate, then run the same merge/reconcile/insert logic.
        """
        return self.apply_stimulus_packet(
            stimulus_packet=stimulus_packet,
            trace_id=trace_id,
            tick_id=tick_id,
            source_module=source_module,
            apply_mode="normal",
            enable_script_broadcast=enable_script_broadcast,
            enable_brief_log=enable_brief_log,
            compute_post_apply_summary=compute_post_apply_summary,
            clone_packet_for_safety=False,
            enable_change_event_log=False,
        )
        start_time = time.time()
        tick_id = tick_id or trace_id
        self._total_calls += 1
        self._tick_counter += 1
        tick_number = self._tick_counter

        err = self._validate_stimulus_packet(stimulus_packet, trace_id, "normal")
        if err:
            return self._make_response(
                False,
                err["code"],
                f"{err['message_zh']} / {err['message_en']}",
                error=err,
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        packet = stimulus_packet if isinstance(stimulus_packet, dict) else {}
        sa_items = [dict(item) for item in (packet.get("sa_items", []) or []) if isinstance(item, dict)]
        csa_items = [dict(item) for item in (packet.get("csa_items", []) or []) if isinstance(item, dict)]
        feature_sa_items: list[dict] = []
        attribute_sa_items: list[dict] = []
        for sa in sa_items:
            if str(sa.get("object_type", "")) != "sa":
                continue
            if str(sa.get("stimulus", {}).get("role", "") or "") == "attribute":
                attribute_sa_items.append(sa)
            else:
                feature_sa_items.append(sa)
        if not feature_sa_items:
            return self._make_response(
                True,
                "OK",
                "投影刺激包为空 / Projection packet has no feature SA",
                data={
                    "applied_state_item_ids": [],
                    "new_item_count": 0,
                    "updated_item_count": 0,
                    "merged_item_count": 0,
                    "priority_neutralized_item_count": 0,
                    "priority_neutralization_diagnostics": [],
                    "event_component_neutralization_count": 0,
                    "event_component_neutralization_er_added_sum": 0.0,
                    "event_component_neutralization_ev_added_sum": 0.0,
                    "event_component_cp_drop_sum": 0.0,
                    "neutralized_item_count": 0,
                    "rejected_object_count": 0,
                    "script_broadcast_sent": False,
                    "residual_stimulus_packet": packet,
                    "state_delta_summary": {
                        "total_delta_er": 0.0,
                        "total_delta_ev": 0.0,
                        "total_delta_cp": 0.0,
                        "high_cp_item_count": None,
                    },
                },
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        object_lookup = {
            str(obj.get("id", "")): obj
            for obj in (list(sa_items) + list(csa_items))
            if str(obj.get("id", ""))
        }
        representative_ref_object = self._select_projection_packet_representative_feature_sa(feature_sa_items)
        candidate = build_state_item(
            ref_object=representative_ref_object,
            trace_id=trace_id,
            tick_id=tick_id,
            tick_number=tick_number,
            source_module=source_module or "observatory",
            source_interface="apply_projection_packet_fast",
            origin="from_projection_packet",
            origin_id=str(packet.get("id", "") or ""),
            object_lookup=object_lookup,
        )
        if candidate is None:
            return self.apply_stimulus_packet(
                stimulus_packet=packet,
                trace_id=trace_id,
                tick_id=tick_id,
                source_module=source_module,
                apply_mode="normal",
                enable_script_broadcast=enable_script_broadcast,
                enable_brief_log=enable_brief_log,
                compute_post_apply_summary=compute_post_apply_summary,
                clone_packet_for_safety=False,
            )

        attr_energy_by_anchor: dict[str, dict[str, float | int]] = {}
        attrs_by_anchor: dict[str, list[dict]] = {}
        for attr in attribute_sa_items:
            parent_ids = list(attr.get("source", {}).get("parent_ids", []) or [])
            anchor_id = str(parent_ids[0]) if parent_ids else ""
            if not anchor_id:
                continue
            attrs_by_anchor.setdefault(anchor_id, []).append(attr)
            energy = attr.get("energy", {}) or {}
            bucket = attr_energy_by_anchor.setdefault(anchor_id, {"er": 0.0, "ev": 0.0, "count": 0})
            bucket["er"] = float(bucket.get("er", 0.0)) + float(energy.get("er", 0.0) or 0.0)
            bucket["ev"] = float(bucket.get("ev", 0.0)) + float(energy.get("ev", 0.0) or 0.0)
            bucket["count"] = int(bucket.get("count", 0) or 0) + 1

        total_er = 0.0
        total_ev = 0.0
        folded_attribute_sa_count = 0
        folded_attribute_total_er = 0.0
        folded_attribute_total_ev = 0.0
        entries = []
        source_types = set()
        has_packet_context = False
        for sa in feature_sa_items:
            energy = sa.get("energy", {}) if isinstance(sa.get("energy", {}), dict) else {}
            total_er += float(energy.get("er", 0.0) or 0.0)
            total_ev += float(energy.get("ev", 0.0) or 0.0)
            anchor_id = str(sa.get("id", "") or "")
            folded = attr_energy_by_anchor.get(anchor_id) or {}
            extra_er = float(folded.get("er", 0.0) or 0.0)
            extra_ev = float(folded.get("ev", 0.0) or 0.0)
            extra_count = int(folded.get("count", 0) or 0)
            if extra_count and (extra_er or extra_ev):
                total_er += extra_er
                total_ev += extra_ev
                folded_attribute_sa_count += extra_count
                folded_attribute_total_er += extra_er
                folded_attribute_total_ev += extra_ev
            packet_context = dict(sa.get("ext", {}).get("packet_context", {}) or {}) if isinstance(sa.get("ext", {}).get("packet_context", {}), dict) else {}
            if packet_context:
                has_packet_context = True
                source_type = str(packet_context.get("source_type", "") or "")
                if source_type:
                    source_types.add(source_type)
            entries.append(
                {
                    "candidate": {"ref_object_id": anchor_id},
                    "packet_context": packet_context,
                }
            )

        candidate = self._synchronize_candidate_with_group(
            candidate,
            entries=entries,
            total_er=round(total_er, 8),
            total_ev=round(total_ev, 8),
        )
        if folded_attribute_sa_count:
            ext = candidate.setdefault("ext", {})
            ext["incoming_packet_folded_attribute_sa_count"] = int(folded_attribute_sa_count)
            ext["incoming_packet_folded_attribute_total_er"] = round(float(folded_attribute_total_er), 8)
            ext["incoming_packet_folded_attribute_total_ev"] = round(float(folded_attribute_total_ev), 8)
        self._refresh_runtime_resolution_metadata(candidate, source="projection_packet_candidate")

        all_events: list[dict] = []
        applied_ids: list[str] = []
        new_count = 0
        updated_count = 0
        merged_count = 0
        rejected_count = 0
        target_item: dict | None = None
        existing = None
        matched_by_ref = False
        for entry in entries:
            candidate_ref_id = str(entry.get("candidate", {}).get("ref_object_id", "") or "")
            existing = self._store.get_by_ref(candidate_ref_id)
            if existing is not None:
                matched_by_ref = True
                break
        if existing is None:
            existing = self._find_existing_item_for_candidate(candidate)
        group_collapse_count = max(0, len(entries) - 1)

        if existing is not None:
            if matched_by_ref:
                match_mode = "ref"
            elif (
                self._runtime_root_structure_id(existing)
                and self._runtime_root_structure_id(existing) == self._runtime_root_structure_id(candidate)
            ):
                match_mode = "root_structure"
            else:
                match_mode = "semantic"
            source_module_name = str(source_module or "observatory")
            allow_memory_feedback_additive_merge = bool(
                self._config.get("memory_feedback_packet_additive_merge_enabled", True)
            )
            is_memory_feedback_packet = source_module_name in {"memory_feedback", "observatory_memory_feedback"}
            is_induction_packet = source_module_name == "hdb_induction"
            use_packet_reconcile = (
                has_packet_context
                and self._config.get("sensor_input_reconcile_mode", "max") == "max"
                and not (allow_memory_feedback_additive_merge and is_memory_feedback_packet)
                and not (self._config.get("induction_packet_additive_merge_enabled", True) and is_induction_packet)
            )
            if use_packet_reconcile:
                event = self._reconcile_candidate_on_existing(
                    existing_item=existing,
                    candidate_item=candidate,
                    incoming_er=round(total_er, 8),
                    incoming_ev=round(total_ev, 8),
                    tick_number=tick_number,
                    reason=f"stimulus_apply_{match_mode}_reconcile",
                    source_module=source_module or "observatory",
                    trace_id=trace_id,
                    tick_id=tick_id,
                )
                event["merge_mode"] = f"{match_mode}_reconcile"
            else:
                event = self._merge_candidate_into_existing(
                    existing_item=existing,
                    candidate_item=candidate,
                    merge_mode=match_mode,
                    tick_number=tick_number,
                    reason=(
                        "stimulus_apply_semantic_merge"
                        if match_mode == "semantic"
                        else "stimulus_apply_ref_hit"
                    ),
                    source_module=source_module or "observatory",
                    trace_id=trace_id,
                    tick_id=tick_id,
                )
            event["incoming_member_count"] = len(entries)
            event["packet_source_types"] = sorted(source_types)
            all_events.append(event)
            applied_ids.append(existing["id"])
            updated_count += 1
            merged_count += group_collapse_count + (1 if match_mode == "semantic" else 0)
            self._log_change_event(event, trace_id, tick_id)
            target_item = existing
        else:
            er = candidate["energy"]["er"]
            ev = candidate["energy"]["ev"]
            if er == 0 and ev == 0 and not self._config.get("insert_zero_energy_object", True):
                rejected_count += 1
            else:
                self._energy.seed_runtime_modulation(candidate, tick_number)
                inserted = self._store.insert(candidate)
                if inserted:
                    self._total_items_created += 1
                    applied_ids.append(candidate["id"])
                    new_count += 1
                    merged_count += group_collapse_count
                    event = {
                        "event_id": f"new_{candidate['id']}",
                        "event_type": "created",
                        "target_item_id": candidate["id"],
                        "trace_id": trace_id,
                        "tick_id": tick_id,
                        "timestamp_ms": int(time.time() * 1000),
                        "before": {"er": 0.0, "ev": 0.0, "cp_delta": 0.0, "cp_abs": 0.0},
                        "after": {
                            "er": er,
                            "ev": ev,
                            "cp_delta": candidate["energy"]["cognitive_pressure_delta"],
                            "cp_abs": candidate["energy"]["cognitive_pressure_abs"],
                        },
                        "delta": {
                            "delta_er": er,
                            "delta_ev": ev,
                            "delta_cp_delta": candidate["energy"]["cognitive_pressure_delta"],
                            "delta_cp_abs": candidate["energy"]["cognitive_pressure_abs"],
                        },
                        "rate": {
                            "er_change_rate": er,
                            "ev_change_rate": ev,
                            "cp_delta_rate": candidate["energy"]["cognitive_pressure_delta"],
                            "cp_abs_rate": candidate["energy"]["cognitive_pressure_abs"],
                        },
                        "reason": "stimulus_apply_new_item",
                        "source_module": source_module or "observatory",
                        "semantic_signature": candidate.get("semantic_signature", ""),
                        "incoming_member_count": len(entries),
                        "packet_source_types": sorted(source_types),
                    }
                    all_events.append(event)
                    self._log_change_event(event, trace_id, tick_id)
                    target_item = candidate
                else:
                    rejected_count += 1

        if target_item is not None and (attribute_sa_items or csa_items):
            self._sync_packet_attribute_bindings(
                target_item=target_item,
                attribute_sa_items=attribute_sa_items,
                csa_items=csa_items,
                attrs_by_anchor=attrs_by_anchor,
                object_lookup=object_lookup,
                tick_number=tick_number,
            )

        self._history.append_many(all_events)
        broadcast_sent = False
        if (
            enable_script_broadcast
            and self._config.get("enable_script_broadcast", True)
            and self._config.get("script_broadcast_stage_after_apply", True)
            and len(all_events) >= self._config.get("script_broadcast_min_event_count", 1)
        ):
            broadcast_sent = self._broadcast_script_check(all_events, trace_id, tick_id)

        total_delta_er = sum(e.get("delta", {}).get("delta_er", 0) for e in all_events if "delta" in e)
        total_delta_ev = sum(e.get("delta", {}).get("delta_ev", 0) for e in all_events if "delta" in e)
        total_delta_cp = sum(abs(e.get("delta", {}).get("delta_cp_delta", 0)) for e in all_events if "delta" in e)
        high_cp = len(self._store.get_high_cp_items(0.5)) if compute_post_apply_summary else None
        elapsed = self._elapsed_ms(start_time)

        if enable_brief_log:
            self._logger.brief(
                trace_id=trace_id,
                interface="apply_projection_packet_fast",
                success=True,
                message_zh="状态池应用投影刺激包成功",
                message_en="Projection packet applied successfully",
                tick_id=tick_id,
                input_summary={"packet_id": packet.get("id", ""), "sa_count": len(sa_items), "csa_count": len(csa_items)},
                output_summary={
                    "new_item_count": new_count,
                    "updated_item_count": updated_count,
                    "merged_item_count": merged_count,
                    "rejected_object_count": rejected_count,
                    "active_item_count": self._store.size,
                    "high_cp_item_count": high_cp,
                    "script_broadcast_sent": broadcast_sent,
                },
            )

        return self._make_response(
            success=True,
            code="OK",
            message="状态池应用投影刺激包成功 / Projection packet applied successfully",
            data={
                "applied_state_item_ids": applied_ids,
                "new_item_count": new_count,
                "updated_item_count": updated_count,
                "merged_item_count": merged_count,
                "priority_neutralized_item_count": 0,
                "priority_neutralization_diagnostics": [],
                "event_component_neutralization_count": 0,
                "event_component_neutralization_er_added_sum": 0.0,
                "event_component_neutralization_ev_added_sum": 0.0,
                "event_component_cp_drop_sum": 0.0,
                "neutralized_item_count": 0,
                "rejected_object_count": rejected_count,
                "script_broadcast_sent": broadcast_sent,
                "residual_stimulus_packet": packet,
                "state_delta_summary": {
                    "total_delta_er": round(total_delta_er, 6),
                    "total_delta_ev": round(total_delta_ev, 6),
                    "total_delta_cp": round(total_delta_cp, 6),
                    "high_cp_item_count": high_cp,
                },
            },
            trace_id=trace_id,
            elapsed_ms=elapsed,
        )

    # ================================================================== #
    #   接口二: apply_energy_update — 定向能量更新                         #
    # ================================================================== #

    def apply_energy_update(
        self,
        target_item_id: str,
        delta_er: float,
        delta_ev: float,
        trace_id: str,
        tick_id: str | None = None,
        reason: str = "external_update",
        source_module: str = "unknown",
        allow_create_if_missing: bool = False,
        extra_context: dict | None = None,
    ) -> dict:
        """对状态池中已有对象执行定向能量更新。"""
        start_time = time.time()
        tick_id = tick_id or trace_id
        self._total_calls += 1

        # 校验
        if not target_item_id or not isinstance(target_item_id, str):
            return self._make_error_response("INPUT_VALIDATION_ERROR",
                "target_item_id 必填且必须为字符串", "target_item_id is required and must be a string",
                trace_id, start_time)

        if delta_er == 0.0 and delta_ev == 0.0:
            return self._make_error_response("INPUT_VALIDATION_ERROR",
                "delta_er 与 delta_ev 不允许同时为 0", "delta_er and delta_ev cannot both be 0",
                trace_id, start_time)

        item = self._store.get(target_item_id)
        if item is None:
            if not allow_create_if_missing:
                return self._make_error_response("STATE_ERROR",
                    f"目标对象不存在: {target_item_id}", f"Target item not found: {target_item_id}",
                    trace_id, start_time)
            # 允许创建时走 insert_runtime_node 逻辑
            return self._make_error_response("STATE_ERROR",
                f"目标对象不存在且未启用自动创建: {target_item_id}",
                f"Target not found and auto-create disabled: {target_item_id}",
                trace_id, start_time)

        # 执行更新
        before_er = item["energy"]["er"]
        before_ev = item["energy"]["ev"]

        event = self._energy.apply_energy_delta(
            item=item, delta_er=delta_er, delta_ev=delta_ev,
            tick_number=self._tick_counter, reason=reason,
            source_module=source_module, trace_id=trace_id, tick_id=tick_id,
        )
        self._history.append(event)
        self._log_change_event(event, trace_id, tick_id)

        after = item["energy"]

        self._logger.brief(
            trace_id=trace_id, interface="apply_energy_update", success=True,
            message_zh="状态池对象能量更新成功", message_en="State item energy updated successfully",
            tick_id=tick_id,
            input_summary={"target": target_item_id, "delta_er": delta_er, "delta_ev": delta_ev, "reason": reason},
            output_summary={"er": after["er"], "ev": after["ev"], "cp_abs": after["cognitive_pressure_abs"]},
        )

        return self._make_response(
            success=True, code="OK",
            message="状态池对象能量更新成功 / State item energy updated successfully",
            data={
                "target_item_id": target_item_id,
                "before": {"er": before_er, "ev": before_ev},
                "after": {"er": after["er"], "ev": after["ev"]},
                "delta": {"delta_er": delta_er, "delta_ev": delta_ev},
                "applied_delta": dict(event.get("delta", {})),
                "energy_injection_fatigue": dict(event.get("extra_context", {})),
                "cp_change": {
                    "before_cp_abs": round(abs(before_er - before_ev), 8),
                    "after_cp_abs": after["cognitive_pressure_abs"],
                },
            },
            trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time),
        )

    # ================================================================== #
    #   接口三: bind_attribute_node_to_object — 属性绑定                   #
    # ================================================================== #

    def bind_attribute_node_to_object(
        self,
        target_item_id: str,
        attribute_sa: dict,
        trace_id: str,
        tick_id: str | None = None,
        bind_mode: str = "append_attribute",
        source_module: str = "unknown",
        reason: str = "attribute_binding",
    ) -> dict:
        """将属性刺激元绑定到已有 SA/CSA 上。"""
        start_time = time.time()
        tick_id = tick_id or trace_id
        self._total_calls += 1

        # 校验属性SA
        validation_err = self._binding.validate_attribute_sa(attribute_sa)
        if validation_err:
            return self._make_error_response("INPUT_VALIDATION_ERROR",
                validation_err, validation_err, trace_id, start_time)

        # 查找目标
        item = self._store.get(target_item_id)
        if item is None:
            return self._make_error_response("STATE_ERROR",
                f"目标对象不存在: {target_item_id}", f"Target item not found: {target_item_id}",
                trace_id, start_time)

        ref_type = item.get("ref_object_type", "")
        supported = self._config.get("attribute_binding_supported_target_types", ["sa", "st", "csa"])
        if ref_type not in supported:
            return self._make_error_response("NOT_IMPLEMENTED_ERROR",
                f"不支持对 {ref_type} 类型执行属性绑定",
                f"Attribute binding not supported for type: {ref_type}",
                trace_id, start_time)

        runtime_mode = str(
            self._config.get(
                "attribute_binding_runtime_mode",
                "state_item" if self._config.get("insert_attribute_sa_as_state_item", True) else "legacy_bind",
            )
            or "legacy_bind"
        ).strip().lower()
        if runtime_mode in {"state_item", "runtime_sa", "insert_state_item"}:
            target_ref_id = str(item.get("ref_object_id", "") or target_item_id)
            target_ref_type = str(item.get("ref_object_type", "") or "")
            target_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
            target_display = str(
                target_snapshot.get("content_display", "")
                or target_snapshot.get("content_display_detail", "")
                or target_ref_id
            )
            runtime_ext = (
                item.get("meta", {}).get("ext", {})
                if isinstance(item.get("meta", {}), dict) and isinstance(item.get("meta", {}).get("ext", {}), dict)
                else {}
            )
            context_owner_structure_id = str(
                runtime_ext.get("context_owner_structure_id", "")
                or (target_ref_id if target_ref_type == "st" else "")
            )
            runtime_attribute_sa = copy.deepcopy(attribute_sa)
            runtime_attribute_sa.setdefault("source", {})
            runtime_attribute_sa["source"]["parent_ids"] = [target_ref_id] if target_ref_id else [target_item_id]
            runtime_attribute_sa["source"]["context_ref_object_id"] = target_ref_id
            runtime_attribute_sa["source"]["context_ref_object_type"] = target_ref_type
            if context_owner_structure_id:
                runtime_attribute_sa["source"]["context_owner_structure_id"] = context_owner_structure_id

            runtime_attribute_sa.setdefault("meta", {})
            if not isinstance(runtime_attribute_sa.get("meta", {}), dict):
                runtime_attribute_sa["meta"] = {}
            runtime_attribute_sa["meta"].setdefault("ext", {})
            if not isinstance(runtime_attribute_sa["meta"].get("ext", {}), dict):
                runtime_attribute_sa["meta"]["ext"] = {}
            runtime_attribute_sa["meta"]["ext"].update(
                {
                    "bound_anchor_item_id": str(item.get("id", "") or target_item_id),
                    "bound_anchor_ref_object_id": target_ref_id,
                    "bound_anchor_ref_object_type": target_ref_type,
                    "bound_anchor_display": target_display,
                    "attribute_runtime_mode": "state_item",
                    "attribute_runtime_source_interface": "bind_attribute_node_to_object",
                }
            )

            res = self.insert_runtime_node(
                runtime_object=runtime_attribute_sa,
                trace_id=f"{trace_id}_attr_runtime",
                tick_id=tick_id,
                allow_merge=True,
                source_module=source_module,
                reason=reason,
            )
            try:
                if hasattr(self, "_binding") and hasattr(self._binding, "_append_bound_attribute_snapshot"):
                    runtime_item_id = str((res.get("data", {}) or {}).get("item_id", "") or "")
                    snapshot_sa = copy.deepcopy(runtime_attribute_sa)
                    if runtime_item_id:
                        snapshot_sa.setdefault("meta", {})
                        if not isinstance(snapshot_sa.get("meta", {}), dict):
                            snapshot_sa["meta"] = {}
                        snapshot_sa["meta"].setdefault("ext", {})
                        if not isinstance(snapshot_sa["meta"].get("ext", {}), dict):
                            snapshot_sa["meta"]["ext"] = {}
                        snapshot_sa["meta"]["ext"]["runtime_attribute_item_id"] = runtime_item_id
                    self._binding._append_bound_attribute_snapshot(
                        item,
                        snapshot_sa,
                        now_ms=int(time.time() * 1000),
                    )
            except Exception:
                pass
            if isinstance(res, dict):
                data = dict(res.get("data", {}) or {})
                data.setdefault("target_item_id", target_item_id)
                data.setdefault("runtime_mode", "state_item")
                data.setdefault("target_ref_object_id", target_ref_id)
                data.setdefault("target_ref_object_type", target_ref_type)
                res["data"] = data
            return res

        # 执行绑定
        if ref_type in {"sa", "st"}:
            # 原型阶段允许对 ST 绑定运行态属性（例如 CFS 元认知属性），用于观测与脚本触发。
            result = self._binding.bind_to_sa_item(
                target_item=item, attribute_sa=attribute_sa, pool_store=self._store,
                trace_id=trace_id, tick_id=tick_id, tick_number=self._tick_counter,
                source_module=source_module,
            )
        else:  # csa
            result = self._binding.bind_to_csa_item(
                target_item=item, attribute_sa=attribute_sa,
                trace_id=trace_id, tick_id=tick_id, tick_number=self._tick_counter,
            )

        self._logger.brief(
            trace_id=trace_id, interface="bind_attribute_node_to_object", success=True,
            message_zh="属性节点绑定成功", message_en="Attribute node bound successfully",
            tick_id=tick_id,
            input_summary={"target": target_item_id, "attr_id": attribute_sa.get("id", ""), "reason": reason},
            output_summary=result,
        )
        self._logger.detail(
            trace_id=trace_id, step="attribute_binding",
            message_zh="属性节点绑定详情", message_en="Attribute binding details",
            tick_id=tick_id,
            info={
                "target_item_id": target_item_id,
                "target_ref_object_id": item.get("ref_object_id", ""),
                "target_ref_object_type": ref_type,
                "attribute_sa_id": attribute_sa.get("id", ""),
                "attribute_display": attribute_sa.get("content", {}).get("display", attribute_sa.get("content", {}).get("raw", "")),
                "binding_result": result,
            },
        )

        return self._make_response(
            success=True, code="OK",
            message="属性节点绑定成功 / Attribute node bound successfully",
            data={"target_item_id": target_item_id, **result},
            trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time),
        )

    # ================================================================== #
    #   接口四: insert_runtime_node — 手动插入运行态对象                    #
    # ================================================================== #

    def insert_runtime_node(
        self,
        runtime_object: dict,
        trace_id: str,
        tick_id: str | None = None,
        allow_merge: bool = True,
        source_module: str = "unknown",
        reason: str = "runtime_insert",
        enable_brief_log: bool = True,
        enable_detail_log: bool = True,
        fast_ref_hit_energy_merge: bool = False,
    ) -> dict:
        """手动插入一个运行态对象到状态池。"""
        start_time = time.time()
        tick_id = tick_id or trace_id
        self._total_calls += 1

        # 校验
        if not isinstance(runtime_object, dict):
            return self._make_error_response("INPUT_VALIDATION_ERROR",
                "runtime_object 必须是 dict", "runtime_object must be a dict",
                trace_id, start_time)

        obj_id = runtime_object.get("id", "")
        obj_type = runtime_object.get("object_type", "")
        energy = runtime_object.get("energy")

        if not obj_id:
            return self._make_error_response("INPUT_VALIDATION_ERROR",
                "runtime_object 缺少 id", "runtime_object missing id", trace_id, start_time)
        if not energy or not isinstance(energy, dict):
            return self._make_error_response("INPUT_VALIDATION_ERROR",
                "runtime_object 缺少 energy", "runtime_object missing energy", trace_id, start_time)
        if obj_type not in SUPPORTED_REF_TYPES:
            return self._make_error_response("NOT_IMPLEMENTED_ERROR",
                f"不支持的对象类型: {obj_type}", f"Unsupported object type: {obj_type}",
                trace_id, start_time)

        if allow_merge and fast_ref_hit_energy_merge:
            existing_ref_item = self._store.get_by_ref(obj_id)
            if existing_ref_item is not None:
                event = self._merge_runtime_ref_hit_fast(
                    existing_item=existing_ref_item,
                    runtime_object=runtime_object,
                    tick_number=self._tick_counter,
                    source_module=source_module,
                    trace_id=trace_id,
                    tick_id=tick_id,
                )
                return self._make_response(True, "OK",
                    "对象已通过 ref 快路径合并到已有项 / Object merged into existing item by ref fast path",
                    data={
                        "merged": True,
                        "target_item_id": existing_ref_item["id"],
                        "merge_mode": "ref_fast",
                        "fast_ref_hit": True,
                        "event": event,
                    },
                    trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time))

        # 构建 state_item
        item = build_state_item(
            ref_object=runtime_object, trace_id=trace_id, tick_id=tick_id,
            tick_number=self._tick_counter, source_module=source_module,
            source_interface="insert_runtime_node", origin=reason,
        )
        if item is None:
            return self._make_error_response("INPUT_VALIDATION_ERROR",
                "runtime_object 转换失败", "runtime_object conversion failed", trace_id, start_time)
        self._refresh_runtime_resolution_metadata(item, source="insert_runtime_node_candidate")
        self._sanitize_residual_memory_ref_aliases(item)

        # 查重：优先精确 ref_id/alias，其次尝试语义同一对象合并
        existing = None
        matched_ref_id = ""
        for candidate_ref_id in [obj_id, *list(item.get("ref_alias_ids", []) or [])]:
            candidate_ref_id = str(candidate_ref_id or "").strip()
            if not candidate_ref_id:
                continue
            existing = self._store.get_by_ref(candidate_ref_id)
            if existing is not None:
                matched_ref_id = candidate_ref_id
                break
        if existing is None:
            existing = self._find_existing_item_for_candidate(item)
        if existing and allow_merge:
            if matched_ref_id or existing.get("ref_object_id") == obj_id or obj_id in existing.get("ref_alias_ids", []):
                merge_mode = "ref"
            elif (
                self._runtime_root_structure_id(existing)
                and self._runtime_root_structure_id(existing) == self._runtime_root_structure_id(item)
            ):
                merge_mode = "root_structure"
            else:
                merge_mode = "semantic"
            self._merge_candidate_into_existing(
                existing_item=existing,
                candidate_item=item,
                merge_mode=merge_mode,
                tick_number=self._tick_counter,
                reason="merge_on_insert",
                source_module=source_module,
                trace_id=trace_id,
                tick_id=tick_id,
            )
            self._merge_residual_memory_alias_conflicts(
                existing_item=existing,
                candidate_item=item,
                tick_number=self._tick_counter,
                source_module=source_module,
                trace_id=trace_id,
                tick_id=tick_id,
            )
            return self._make_response(True, "OK",
                "对象已合并到已有项 / Object merged into existing item",
                data={"merged": True, "target_item_id": existing["id"], "merge_mode": merge_mode},
                trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time))

        self._energy.seed_runtime_modulation(item, self._tick_counter)
        inserted = self._store.insert(item)
        if not inserted:
            return self._make_error_response("STATE_ERROR",
                "插入失败（池已满）", "Insert failed (pool full)", trace_id, start_time)

        self._total_items_created += 1

        if enable_brief_log:
            self._logger.brief(
                trace_id=trace_id, interface="insert_runtime_node", success=True,
                message_zh="运行态对象插入成功", message_en="Runtime node inserted successfully",
                tick_id=tick_id,
                input_summary={"obj_type": obj_type, "obj_id": obj_id, "reason": reason},
                output_summary={"item_id": item["id"], "pool_size": self._store.size},
            )
        if enable_detail_log:
            self._logger.detail(
                trace_id=trace_id, step="insert_runtime_node",
                message_zh="运行态对象插入详情", message_en="Runtime node insertion details",
                tick_id=tick_id,
                info={"item_id": item["id"], "state_item": self._compact_detail_log_payload(item)},
            )

        return self._make_response(True, "OK",
            "运行态对象插入成功 / Runtime node inserted successfully",
            data={"inserted": True, "item_id": item["id"], "pool_size": self._store.size},
            trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time))

    # ================================================================== #
    #   接口五: tick_maintain_state_pool — Tick 维护                       #
    # ================================================================== #

    def tick_maintain_state_pool(
        self,
        trace_id: str,
        tick_id: str | None = None,
        apply_decay: bool = True,
        apply_neutralization: bool = True,
        apply_prune: bool = True,
        apply_merge: bool = True,
        enable_script_broadcast: bool = True,
        emit_attention_snapshot: bool = False,
        metadata: dict | None = None,
    ) -> dict:
        """执行一次完整状态池维护周期。"""
        start_time = time.time()
        tick_id = tick_id or trace_id
        self._total_calls += 1
        self._tick_counter += 1
        tick_number = self._tick_counter

        result = self._maintenance.run_maintenance(
            pool_store=self._store,
            energy_engine=self._energy,
            neutralization_engine=self._neutralization,
            merge_engine=self._merge,
            tick_number=tick_number,
            trace_id=trace_id, tick_id=tick_id,
            apply_decay=apply_decay,
            apply_neutralization=apply_neutralization,
            apply_prune=apply_prune,
            apply_merge=apply_merge,
        )

        events = result["events"]
        summary = result["summary"]

        # 记录事件和日志
        self._history.append_many(events)
        for event in events:
            self._log_change_event(event, trace_id, tick_id)

        # 脚本广播
        broadcast_sent = False
        if (enable_script_broadcast
            and self._config.get("enable_script_broadcast", True)
            and self._config.get("script_broadcast_stage_after_maintenance", True)):
            broadcast_sent = self._broadcast_script_check(events, trace_id, tick_id)

        summary["script_broadcast_sent"] = broadcast_sent

        # 注意力快照（占位）
        if emit_attention_snapshot:
            self._emit_attention_snapshot(trace_id, tick_id)

        elapsed = self._elapsed_ms(start_time)

        self._logger.brief(
            trace_id=trace_id, interface="tick_maintain_state_pool", success=True,
            message_zh="状态池维护成功", message_en="State pool maintenance completed successfully",
            tick_id=tick_id,
            output_summary=summary,
        )

        return self._make_response(True, "OK",
            "状态池维护成功 / State pool maintenance completed successfully",
            data=summary, trace_id=trace_id, elapsed_ms=elapsed)

    # ================================================================== #
    #   接口六: get_state_snapshot — 状态快照                              #
    # ================================================================== #

    def get_state_snapshot(
        self,
        trace_id: str,
        tick_id: str | None = None,
        include_items: bool = True,
        include_history_window: bool = True,
        top_k: int | None = None,
        sort_by: str = "cp_abs",
    ) -> dict:
        """获取当前状态池快照。"""
        self._total_calls += 1
        snapshot = self._snapshot.build_state_snapshot(
            pool_store=self._store, history_window=self._history,
            trace_id=trace_id, tick_id=tick_id or "",
            include_items=include_items, include_history_window=include_history_window,
            top_k=top_k, sort_by=sort_by,
            runtime_stats={"energy_injection_fatigue": self._energy.get_injection_fatigue_stats(self._tick_counter)},
        )

        return self._make_response(True, "OK",
            "状态池快照 / State pool snapshot",
            data={
                "snapshot": snapshot,
                "pool_stats": {
                    "version": __version__,
                    "schema_version": __schema_version__,
                    "pool_size": self._store.size,
                    "tick_counter": self._tick_counter,
                    "total_calls": self._total_calls,
                    "total_items_created": self._total_items_created,
                    "history_window_size": self._history.size,
                },
            },
            trace_id=trace_id, elapsed_ms=0)

    # ================================================================== #
    #   接口七: reload_config — 热加载配置                                 #
    # ================================================================== #

    def reload_config(
        self,
        trace_id: str,
        config_path: str | None = None,
        apply_partial: bool = True,
    ) -> dict:
        """显式触发热加载配置。"""
        start_time = time.time()
        path = config_path or self._config_path
        self._total_calls += 1

        try:
            new_raw = _load_yaml_config(path)
            if not new_raw:
                return self._make_error_response("CONFIG_ERROR",
                    f"配置文件加载失败或为空: {path}",
                    f"Config file failed to load or empty: {path}",
                    trace_id, start_time)

            applied = []
            rejected = []
            for key, val in new_raw.items():
                if key in _DEFAULT_CONFIG:
                    expected_type = type(_DEFAULT_CONFIG[key])
                    if isinstance(val, expected_type) or (expected_type is float and isinstance(val, (int, float))):
                        self._config[key] = val
                        applied.append(key)
                    else:
                        rejected.append({"key": key, "reason": f"类型不匹配 / Type mismatch: expected {expected_type.__name__}, got {type(val).__name__}"})
                else:
                    rejected.append({"key": key, "reason": "未知配置项 / Unknown config key"})

            # 通知子模块
            self._store.update_config(self._config)
            self._energy.update_config(self._config)
            self._neutralization.update_config(self._config)
            self._merge.update_config(self._config)
            self._binding.update_config(self._config)
            self._maintenance.update_config(self._config)
            self._snapshot.update_config(self._config)
            self._history.update_config(self._config)
            self._state_item_template_cache.clear()
            self._priority_neutralization_group_stats_cache.clear()
            self._priority_neutralization_cut_engine = None
            self._priority_neutralization_cut_engine_config_key = None
            self._logger.update_config(
                log_dir=self._config.get("log_dir", ""),
                max_file_bytes=self._config.get("log_max_file_bytes", 0),
                archive_keep_per_level=self._config.get("log_archive_keep_per_level"),
                enable_stdout_fallback=self._config.get("stdout_fallback_when_log_fail", True),
            )

            self._logger.brief(
                trace_id=trace_id, interface="reload_config", success=True,
                message_zh="热加载完成", message_en="Hot reload done",
                input_summary={"path": path},
                output_summary={"applied": len(applied), "rejected": len(rejected)},
            )

            return self._make_response(True, "OK",
                f"热加载完成 / Hot reload done: {len(applied)} applied, {len(rejected)} rejected",
                data={"applied": applied, "rejected": rejected},
                trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time))

        except Exception as e:
            msg_zh = f"热加载异常: {e}"
            msg_en = f"Hot reload exception: {e}"
            self._logger.error(trace_id=trace_id, interface="reload_config",
                code="CONFIG_ERROR", message_zh=msg_zh, message_en=msg_en,
                detail={"traceback": traceback.format_exc()})
            return self._make_error_response("CONFIG_ERROR", msg_zh, msg_en, trace_id, start_time)

    # ================================================================== #
    #   接口八: clear_state_pool — 清空状态池                              #
    # ================================================================== #

    def clear_state_pool(
        self,
        trace_id: str,
        reason: str,
        operator: str | None = None,
    ) -> dict:
        """清空状态池。高风险操作，必须审计。"""
        self._total_calls += 1
        tick_counter_before = int(self._tick_counter)
        cleared = self._store.clear()
        history_cleared = self._history.clear()
        self._tick_counter = 0
        self._energy.reset_runtime_stats()
        self._priority_neutralization_group_stats_cache.clear()
        self._priority_neutralization_cut_engine = None
        self._priority_neutralization_cut_engine_config_key = None

        self._audit.record(
            trace_id=trace_id, interface="clear_state_pool",
            action="clear_state_pool", reason=reason,
            operator=operator or "unknown",
            detail={"cleared_item_count": cleared, "cleared_event_count": history_cleared},
        )

        return self._make_response(True, "OK",
            f"状态池已清空 / State pool cleared: {cleared} items removed",
            data={
                "cleared_item_count": cleared,
                "cleared_event_count": history_cleared,
                "tick_counter_before_reset": tick_counter_before,
                "tick_counter_reset": True,
            },
            trace_id=trace_id, elapsed_ms=0)

    # ================================================================== #
    #                     内部辅助方法                                     #
    # ================================================================== #

    def _build_config(self, override: dict | None) -> dict:
        """构建最终配置: 默认值 → YAML → 代码覆盖。"""
        cfg = dict(_DEFAULT_CONFIG)
        file_cfg = _load_yaml_config(self._config_path)
        if file_cfg:
            cfg.update(file_cfg)
        if override:
            cfg.update(override)
        return cfg

    @staticmethod
    def _clone_stimulus_packet(stimulus_packet: dict) -> dict:
        """深拷贝 stimulus_packet，避免优先中和阶段污染调用方输入。"""
        return copy.deepcopy(stimulus_packet if isinstance(stimulus_packet, dict) else {})

    def _priority_neutralize_stimulus_packet(
        self,
        *,
        stimulus_packet: dict,
        tick_number: int,
        trace_id: str,
        tick_id: str,
        source_module: str,
    ) -> dict:
        """
        让完整刺激信号先对状态池中的高认知压结构做优先验证/中和，
        之后只把剩余刺激继续交给后续流程。
        """
        if not isinstance(stimulus_packet, dict):
            empty_packet = self._clone_stimulus_packet(
                {
                    "id": "",
                    "object_type": "stimulus_packet",
                    "sa_items": [],
                    "csa_items": [],
                    "grouped_sa_sequences": [],
                    "energy_summary": {"total_er": 0.0, "total_ev": 0.0},
                }
            )
            return {
                "residual_packet": empty_packet,
                "events": [],
                "neutralized_item_count": 0,
                "cut_metrics": {},
            }

        cut_config = {
            # This per-packet neutralization pass compares each candidate at most once,
            # but the same candidate/profile pairs recur across ticks. Keep a dedicated
            # CutEngine so its lightweight normalization/group-length caches survive.
            "maximum_common_part_cache_enabled": bool(
                self._config.get("priority_neutralization_common_part_cache_enabled", False)
            ),
            "maximum_common_part_cache_deepcopy_enabled": bool(
                self._config.get("priority_neutralization_common_part_cache_deepcopy_enabled", False)
            ),
            "maximum_common_part_cache_max_entries": int(
                self._config.get("priority_neutralization_common_part_cache_max_entries", 512) or 0
            ),
            "common_group_length_cache_max_entries": int(
                self._config.get("priority_neutralization_common_group_length_cache_max_entries", 4096) or 0
            ),
        }
        cut_config_key = tuple(sorted(cut_config.items()))
        cut_engine = self._priority_neutralization_cut_engine
        if cut_engine is None or self._priority_neutralization_cut_engine_config_key != cut_config_key:
            from hdb._cut_engine import CutEngine

            cut_engine = CutEngine(cut_config)
            self._priority_neutralization_cut_engine = cut_engine
            self._priority_neutralization_cut_engine_config_key = cut_config_key
        min_effect = max(
            0.0,
            float(self._config.get("priority_neutralization_min_effect_threshold", 0.01)),
        )
        soft_matching_enabled = bool(
            self._config.get("priority_neutralization_soft_matching_enabled", True)
        )
        candidate_cp_min = max(
            min_effect,
            float(self._config.get("priority_neutralization_candidate_cp_min", 0.05)),
        )
        min_match_score = max(
            0.0,
            min(1.0, float(self._config.get("priority_neutralization_min_match_score", 0.35))),
        )
        min_structure_coverage = max(
            0.0,
            min(1.0, float(self._config.get("priority_neutralization_min_structure_coverage", 0.45))),
        )
        candidate_top_k = max(
            0,
            int(self._config.get("priority_neutralization_candidate_top_k", 48) or 0),
        )
        emit_pruned_diagnostics = bool(
            self._config.get("priority_neutralization_emit_pruned_diagnostics", True)
        )
        settlement_mode = str(
            self._config.get("priority_neutralization_settlement_mode", "structure_match_sa_settlement") or
            "structure_match_sa_settlement"
        ).strip()
        target_ref_types = {
            str(ref_type)
            for ref_type in self._config.get("priority_stimulus_target_ref_types", ["st"])
            if str(ref_type)
        }
        if not list(stimulus_packet.get("grouped_sa_sequences", [])):
            return {
                "residual_packet": stimulus_packet,
                "events": [],
                "neutralized_item_count": 0,
                "cut_metrics": cut_engine.pop_runtime_metrics(),
            }

        candidate_items = []
        for ref_type in target_ref_types:
            candidate_items.extend(self._store.get_by_type(ref_type))
        if candidate_top_k > 0:
            candidate_items = heapq.nlargest(
                candidate_top_k,
                candidate_items,
                key=lambda item: (
                    float(item.get("energy", {}).get("cognitive_pressure_abs", 0.0)),
                    float(item.get("updated_at", 0.0)),
                ),
            )
        else:
            candidate_items.sort(
                key=lambda item: (
                    float(item.get("energy", {}).get("cognitive_pressure_abs", 0.0)),
                    float(item.get("updated_at", 0.0)),
                ),
                reverse=True,
            )

        events: list[dict] = []
        diagnostics: list[dict] = []
        neutralized_item_count = 0
        consumed_any = False
        theoretical_match_fast_reject_count = 0
        event_component_neutralization_count = 0
        event_component_neutralization_er_added_sum = 0.0
        event_component_neutralization_ev_added_sum = 0.0
        event_component_cp_drop_sum = 0.0

        # PERF: 构建一次 packet 的结构 profile，避免在候选遍历中重复切分/归一化。
        # packet_groups 会根据“剩余能量”过滤 0 能量单元，所以在能量发生变化后仍需重建。
        packet_profile = cut_engine.build_sequence_profile_from_stimulus_packet(stimulus_packet)
        packet_energy_ref_by_id: dict[str, dict] = {}
        for sa_item in stimulus_packet.get("sa_items", []):
            if isinstance(sa_item, dict) and sa_item.get("id"):
                packet_energy_ref_by_id[str(sa_item.get("id", ""))] = sa_item.setdefault("energy", {})

        packet_profile_has_fallback_unit = False
        for group in packet_profile.get("sequence_groups", []) or []:
            for unit in group.get("units", []) or []:
                unit_id = str((unit or {}).get("unit_id", "") or "")
                if unit_id and unit_id not in packet_energy_ref_by_id:
                    packet_profile_has_fallback_unit = True
                    break
            if packet_profile_has_fallback_unit:
                break

        # 若 profile 中存在“fallback unit”（unit_id 不在 sa_items），旧实现会在每次候选检查时重新生成
        # 这类 unit 的 energy_ref，从而行为上等价于“每次都重置这类 unit 的能量”。为了保证结果不变，
        # 我们在这种情况下保持每轮都重建 packet_groups。
        always_rebuild_packet_groups = packet_profile_has_fallback_unit
        packet_groups: list[dict] = []
        packet_groups_dirty = True
        packet_unit_index_by_id: dict[str, list[dict]] = {}
        packet_units_by_id: dict[str, dict] = {}
        packet_token_counter: Counter[str] = Counter()
        packet_unit_count = 0
        packet_total_er_available = 0.0
        packet_total_ev_available = 0.0
        sa_items = self._store.get_by_type("sa")
        sa_items_by_ref = {
            str(sa_item.get("ref_object_id", "") or ""): sa_item
            for sa_item in sa_items
            if isinstance(sa_item, dict) and str(sa_item.get("ref_object_type", "") or "") == "sa"
        }
        sa_items_by_token: dict[str, list[dict]] = {}
        for sa_item in sa_items:
            if not isinstance(sa_item, dict) or str(sa_item.get("ref_object_type", "") or "") != "sa":
                continue
            token = str(sa_item.get("ref_snapshot", {}).get("content_display", "") or "").strip()
            if not token:
                continue
            sa_items_by_token.setdefault(token, []).append(sa_item)
        applied_state_item_ids: list[str] = []

        for item in candidate_items:
            cp_delta = float(item.get("energy", {}).get("cognitive_pressure_delta", 0.0))
            cp_abs = abs(cp_delta)
            if cp_abs < candidate_cp_min:
                continue

            structure_groups = self._extract_sequence_groups_from_state_item(item)
            if not structure_groups:
                continue

            if always_rebuild_packet_groups or packet_groups_dirty:
                packet_groups = self._build_packet_groups_for_neutralization(
                    stimulus_packet,
                    cut_engine=cut_engine,
                    _cached_profile=packet_profile,
                    _energy_ref_by_id=packet_energy_ref_by_id,
                )
                packet_unit_index_by_id = self._index_group_units_by_id_list(packet_groups)
                packet_units_by_id = {
                    unit_id: unit_list[0]
                    for unit_id, unit_list in packet_unit_index_by_id.items()
                    if unit_list
                }
                packet_token_counter = self._build_group_token_counter(packet_groups)
                packet_unit_count = self._count_group_units(packet_groups)
                packet_total_er_available = self._sum_group_energy(packet_groups, "er")
                packet_total_ev_available = self._sum_group_energy(packet_groups, "ev")
                packet_groups_dirty = False
            if not packet_groups:
                break

            required_energy_key = "er" if cp_delta < 0.0 else "ev"
            required_amount_raw = max(
                0.0,
                float(item.get("energy", {}).get("ev" if cp_delta < 0.0 else "er", 0.0))
                - float(item.get("energy", {}).get("er" if cp_delta < 0.0 else "ev", 0.0)),
            )
            if required_amount_raw < min_effect:
                continue
            packet_total_required_available = (
                packet_total_er_available if required_energy_key == "er" else packet_total_ev_available
            )

            component_result = self._priority_neutralize_cognitive_stitching_event(
                item=item,
                packet_groups=packet_groups,
                tick_number=tick_number,
                min_effect=min_effect,
                source_module=source_module,
                trace_id=trace_id,
                tick_id=tick_id,
            )
            if component_result.get("handled", False):
                diagnostic = component_result.get("diagnostic")
                if isinstance(diagnostic, dict):
                    diagnostics.append(diagnostic)
                event_component_neutralization_count += int(component_result.get("component_neutralization_count", 0) or 0)
                event_component_neutralization_er_added_sum = round(
                    event_component_neutralization_er_added_sum + float(component_result.get("total_delta_er", 0.0) or 0.0),
                    8,
                )
                event_component_neutralization_ev_added_sum = round(
                    event_component_neutralization_ev_added_sum + float(component_result.get("total_delta_ev", 0.0) or 0.0),
                    8,
                )
                event_component_cp_drop_sum = round(
                    event_component_cp_drop_sum + float(component_result.get("component_cp_drop_sum", 0.0) or 0.0),
                    8,
                )
                if component_result.get("consumed_any", False) and not always_rebuild_packet_groups:
                    packet_groups_dirty = True
                component_event = component_result.get("event")
                if isinstance(component_event, dict):
                    events.append(component_event)
                    neutralized_item_count += 1
                    consumed_any = True
                continue

            ref_snapshot = item.get("ref_snapshot", {}) or {}
            structure_signature = str(ref_snapshot.get("content_signature", "") or "").strip() or cut_engine.sequence_groups_to_signature(
                structure_groups
            )
            if not structure_signature:
                continue

            structure_stats = self._priority_neutralization_group_stats(
                item=item,
                structure_groups=structure_groups,
                structure_signature=structure_signature,
            )
            structure_unit_count = int(structure_stats.get("unit_count", 0) or 0)
            if structure_unit_count <= 0:
                continue
            structure_token_counter = structure_stats.get("token_counter", Counter())
            if not isinstance(structure_token_counter, Counter):
                structure_token_counter = Counter(structure_token_counter or {})
            potential_overlap_units = self._count_counter_overlap(
                structure_token_counter,
                packet_token_counter,
            )
            potential_structure_coverage = round(
                potential_overlap_units / max(1, structure_unit_count),
                8,
            )
            potential_input_coverage = round(
                potential_overlap_units / max(1, packet_unit_count),
                8,
            )
            target_display = self._priority_neutralization_target_display(item)
            if potential_overlap_units <= 0:
                if emit_pruned_diagnostics:
                    diagnostics.append(
                        self._build_priority_neutralization_diagnostic(
                            item=item,
                            structure_signature=structure_signature,
                            required_energy_key=required_energy_key,
                            raw_required_amount=required_amount_raw,
                            required_amount=0.0,
                            available_amount=0.0,
                            consumed_amount=0.0,
                            packet_available_amount=packet_total_required_available,
                            matched_unit_count=0,
                            matched_tokens=[],
                            common_length=0,
                            structure_unit_count=structure_unit_count,
                            packet_unit_count=packet_unit_count,
                            potential_overlap_units=0,
                            potential_structure_coverage=0.0,
                            potential_input_coverage=0.0,
                            structure_coverage=0.0,
                            input_coverage=0.0,
                            order_score=0.0,
                            bundle_score=0.0,
                            match_score=0.0,
                            neutralization_mode="soft_partial_cache" if soft_matching_enabled else "exact_full_cache",
                            status="skipped",
                            skipped_reason="no_token_overlap",
                            target_display=target_display,
                        )
                    )
                continue
            if soft_matching_enabled and potential_structure_coverage < min_structure_coverage:
                if emit_pruned_diagnostics:
                    diagnostics.append(
                        self._build_priority_neutralization_diagnostic(
                            item=item,
                            structure_signature=structure_signature,
                            required_energy_key=required_energy_key,
                            raw_required_amount=required_amount_raw,
                            required_amount=0.0,
                            available_amount=0.0,
                            consumed_amount=0.0,
                            packet_available_amount=packet_total_required_available,
                            matched_unit_count=0,
                            matched_tokens=[],
                            common_length=0,
                            structure_unit_count=structure_unit_count,
                            packet_unit_count=packet_unit_count,
                            potential_overlap_units=potential_overlap_units,
                            potential_structure_coverage=potential_structure_coverage,
                            potential_input_coverage=potential_input_coverage,
                            structure_coverage=0.0,
                            input_coverage=0.0,
                            order_score=0.0,
                            bundle_score=0.0,
                            match_score=0.0,
                            neutralization_mode="soft_partial_cache",
                            status="skipped",
                            skipped_reason="low_potential_structure_coverage",
                            target_display=target_display,
                        )
                    )
                continue
            if packet_total_required_available <= 0.0:
                diagnostics.append(
                    self._build_priority_neutralization_diagnostic(
                        item=item,
                        structure_signature=structure_signature,
                        required_energy_key=required_energy_key,
                        raw_required_amount=required_amount_raw,
                        required_amount=required_amount_raw,
                        available_amount=0.0,
                        consumed_amount=0.0,
                        packet_available_amount=packet_total_required_available,
                        matched_unit_count=0,
                        matched_tokens=[],
                        common_length=0,
                        structure_unit_count=structure_unit_count,
                        packet_unit_count=packet_unit_count,
                        potential_overlap_units=potential_overlap_units,
                        potential_structure_coverage=potential_structure_coverage,
                        potential_input_coverage=potential_input_coverage,
                        structure_coverage=0.0,
                        input_coverage=0.0,
                        order_score=0.0,
                        bundle_score=0.0,
                        match_score=0.0,
                        neutralization_mode="soft_partial_cache" if soft_matching_enabled else "exact_full_cache",
                        status="shortfall",
                        skipped_reason="packet_no_opposite_energy",
                        target_display=target_display,
                    )
                )
                continue

            if soft_matching_enabled:
                theoretical_match_score = round(
                    potential_structure_coverage * 0.60
                    + potential_input_coverage * 0.15
                    + 0.15
                    + 0.10,
                    8,
                )
                if theoretical_match_score < min_match_score:
                    theoretical_match_fast_reject_count += 1
                    if emit_pruned_diagnostics:
                        diagnostics.append(
                            self._build_priority_neutralization_diagnostic(
                                item=item,
                                structure_signature=structure_signature,
                                required_energy_key=required_energy_key,
                                raw_required_amount=required_amount_raw,
                                required_amount=0.0,
                                available_amount=0.0,
                                consumed_amount=0.0,
                                packet_available_amount=packet_total_required_available,
                                matched_unit_count=0,
                                matched_tokens=[],
                                common_length=0,
                                structure_unit_count=structure_unit_count,
                                packet_unit_count=packet_unit_count,
                                potential_overlap_units=potential_overlap_units,
                                potential_structure_coverage=potential_structure_coverage,
                                potential_input_coverage=potential_input_coverage,
                                structure_coverage=0.0,
                                input_coverage=0.0,
                                order_score=1.0,
                                bundle_score=1.0,
                                match_score=theoretical_match_score,
                                neutralization_mode="soft_partial_cache",
                                status="skipped",
                                skipped_reason="low_theoretical_match_score",
                                target_display=target_display,
                            )
                        )
                    continue

            common_part = cut_engine.maximum_common_part(structure_groups, packet_groups)
            matched_units = self._collect_matched_units_from_common_part(
                packet_groups=packet_groups,
                common_part=common_part,
                packet_unit_index_by_id=packet_unit_index_by_id,
            )
            common_length = int(common_part.get("common_length", 0) or 0)
            if not matched_units or common_length <= 0:
                if emit_pruned_diagnostics:
                    diagnostics.append(
                        self._build_priority_neutralization_diagnostic(
                            item=item,
                            structure_signature=structure_signature,
                            required_energy_key=required_energy_key,
                            raw_required_amount=required_amount_raw,
                            required_amount=0.0,
                            available_amount=0.0,
                            consumed_amount=0.0,
                            packet_available_amount=packet_total_required_available,
                            matched_unit_count=0,
                            matched_tokens=[],
                            common_length=common_length,
                            structure_unit_count=structure_unit_count,
                            packet_unit_count=packet_unit_count,
                            potential_overlap_units=potential_overlap_units,
                            potential_structure_coverage=potential_structure_coverage,
                            potential_input_coverage=potential_input_coverage,
                            structure_coverage=0.0,
                            input_coverage=0.0,
                            order_score=0.0,
                            bundle_score=0.0,
                            match_score=0.0,
                            neutralization_mode="soft_partial_cache" if soft_matching_enabled else "exact_full_cache",
                            status="skipped",
                            skipped_reason="no_common_part",
                            target_display=target_display,
                        )
                    )
                continue

            structure_coverage = round(
                common_length / max(1, structure_unit_count),
                8,
            )
            input_coverage = round(
                int(common_part.get("matched_incoming_unit_count", len(matched_units)) or len(matched_units))
                / max(1, packet_unit_count),
                8,
            )
            order_score = self._compute_priority_neutralization_order_score(common_part)
            bundle_score = 1.0 if bool(common_part.get("bundle_constraints_ok_existing_included", True)) else 0.5
            common_signature = str(common_part.get("common_signature", "") or "")
            if soft_matching_enabled:
                match_score = round(
                    structure_coverage * 0.60
                    + input_coverage * 0.15
                    + order_score * 0.15
                    + bundle_score * 0.10,
                    8,
                )
                if structure_coverage < min_structure_coverage:
                    if emit_pruned_diagnostics:
                        diagnostics.append(
                            self._build_priority_neutralization_diagnostic(
                                item=item,
                                structure_signature=structure_signature,
                                required_energy_key=required_energy_key,
                                raw_required_amount=required_amount_raw,
                                required_amount=0.0,
                                available_amount=0.0,
                                consumed_amount=0.0,
                                packet_available_amount=packet_total_required_available,
                                matched_unit_count=len(matched_units),
                                matched_tokens=[str(unit.get("token", "")) for unit in matched_units],
                                common_length=common_length,
                                structure_unit_count=structure_unit_count,
                                packet_unit_count=packet_unit_count,
                                potential_overlap_units=potential_overlap_units,
                                potential_structure_coverage=potential_structure_coverage,
                                potential_input_coverage=potential_input_coverage,
                                structure_coverage=structure_coverage,
                                input_coverage=input_coverage,
                                order_score=order_score,
                                bundle_score=bundle_score,
                                match_score=match_score,
                                neutralization_mode="soft_partial_cache",
                                status="skipped",
                                skipped_reason="low_structure_coverage",
                                target_display=target_display,
                            )
                        )
                    continue
                if match_score < min_match_score:
                    if emit_pruned_diagnostics:
                        diagnostics.append(
                            self._build_priority_neutralization_diagnostic(
                                item=item,
                                structure_signature=structure_signature,
                                required_energy_key=required_energy_key,
                                raw_required_amount=required_amount_raw,
                                required_amount=0.0,
                                available_amount=0.0,
                                consumed_amount=0.0,
                                packet_available_amount=packet_total_required_available,
                                matched_unit_count=len(matched_units),
                                matched_tokens=[str(unit.get("token", "")) for unit in matched_units],
                                common_length=common_length,
                                structure_unit_count=structure_unit_count,
                                packet_unit_count=packet_unit_count,
                                potential_overlap_units=potential_overlap_units,
                                potential_structure_coverage=potential_structure_coverage,
                                potential_input_coverage=potential_input_coverage,
                                structure_coverage=structure_coverage,
                                input_coverage=input_coverage,
                                order_score=order_score,
                                bundle_score=bundle_score,
                                match_score=match_score,
                                neutralization_mode="soft_partial_cache",
                                status="skipped",
                                skipped_reason="low_match_score",
                                target_display=target_display,
                            )
                        )
                    continue
                required_amount = round(required_amount_raw * match_score, 8)
            else:
                if common_signature != structure_signature or not bool(common_part.get("bundle_constraints_ok_existing_included", True)):
                    if emit_pruned_diagnostics:
                        diagnostics.append(
                            self._build_priority_neutralization_diagnostic(
                                item=item,
                                structure_signature=structure_signature,
                                required_energy_key=required_energy_key,
                                raw_required_amount=required_amount_raw,
                                required_amount=0.0,
                                available_amount=0.0,
                                consumed_amount=0.0,
                                packet_available_amount=packet_total_required_available,
                                matched_unit_count=len(matched_units),
                                matched_tokens=[str(unit.get("token", "")) for unit in matched_units],
                                common_length=common_length,
                                structure_unit_count=structure_unit_count,
                                packet_unit_count=packet_unit_count,
                                potential_overlap_units=potential_overlap_units,
                                potential_structure_coverage=potential_structure_coverage,
                                potential_input_coverage=potential_input_coverage,
                                structure_coverage=structure_coverage,
                                input_coverage=input_coverage,
                                order_score=order_score,
                                bundle_score=bundle_score,
                                match_score=0.0,
                                neutralization_mode="exact_full_cache",
                                status="skipped",
                                skipped_reason="exact_signature_miss",
                                target_display=target_display,
                            )
                        )
                    continue
                match_score = 1.0
                required_amount = required_amount_raw

            matched_tokens = [str(unit.get("token", "")) for unit in matched_units]
            if settlement_mode == "structure_match_sa_settlement":
                settlement_result = self._settle_priority_neutralization_on_matched_sas(
                    item=item,
                    structure_signature=structure_signature,
                    target_display=target_display,
                    structure_groups=structure_groups,
                    packet_groups=packet_groups,
                    common_part=common_part,
                    matched_units=matched_units,
                    match_score=match_score,
                    min_effect=min_effect,
                    tick_number=tick_number,
                    source_module=source_module,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    neutralization_mode="soft_partial_cache" if soft_matching_enabled else "exact_full_cache",
                    structure_coverage=structure_coverage,
                    input_coverage=input_coverage,
                    order_score=order_score,
                    bundle_score=bundle_score,
                    sa_items_by_ref=sa_items_by_ref,
                    sa_items_by_token=sa_items_by_token,
                    packet_units_by_id=packet_units_by_id,
                )
                required_energy_key = str(settlement_result.get("required_energy_key", required_energy_key) or "")
                required_amount_raw = float(settlement_result.get("raw_required_amount", required_amount_raw) or 0.0)
                required_amount = float(settlement_result.get("required_amount", required_amount) or 0.0)
                available_amount = float(settlement_result.get("available_amount", 0.0) or 0.0)
                consumed_amount = float(settlement_result.get("consumed_amount", 0.0) or 0.0)
                packet_available_amount = float(settlement_result.get("packet_available_amount", available_amount) or 0.0)
                status = str(settlement_result.get("status", "") or "")
                skipped_reason = str(settlement_result.get("skipped_reason", "") or "")
                sa_target_count = int(settlement_result.get("sa_target_count", 0) or 0)
                sa_resolved_count = int(settlement_result.get("sa_resolved_count", sa_target_count) or 0)
                sa_settled_count = int(settlement_result.get("sa_settled_count", 0) or 0)
                sa_settlements = list(settlement_result.get("sa_settlements", []) or [])
                diagnostics.append(
                    self._build_priority_neutralization_diagnostic(
                        item=item,
                        structure_signature=structure_signature,
                        required_energy_key=required_energy_key,
                        raw_required_amount=required_amount_raw,
                        required_amount=required_amount,
                        available_amount=available_amount,
                        consumed_amount=consumed_amount,
                        packet_available_amount=packet_available_amount,
                        matched_unit_count=len(matched_units),
                        matched_tokens=matched_tokens,
                        common_length=common_length,
                        structure_unit_count=structure_unit_count,
                        packet_unit_count=packet_unit_count,
                        potential_overlap_units=potential_overlap_units,
                        potential_structure_coverage=potential_structure_coverage,
                        potential_input_coverage=potential_input_coverage,
                        structure_coverage=structure_coverage,
                        input_coverage=input_coverage,
                        order_score=order_score,
                        bundle_score=bundle_score,
                        match_score=match_score,
                        neutralization_mode="soft_partial_cache" if soft_matching_enabled else "exact_full_cache",
                        status=status,
                        skipped_reason=skipped_reason,
                        target_display=target_display,
                        sa_target_count=sa_target_count,
                        sa_resolved_count=sa_resolved_count,
                        sa_settled_count=sa_settled_count,
                        sa_settlements=sa_settlements,
                    )
                )
                if settlement_result.get("consumed_any", False):
                    if not always_rebuild_packet_groups:
                        packet_groups_dirty = True
                    event = settlement_result.get("event")
                    if isinstance(event, dict):
                        events.append(event)
                        neutralized_item_count += 1
                        consumed_any = True
                    for applied_item_id in settlement_result.get("applied_state_item_ids", []) or []:
                        text = str(applied_item_id or "")
                        if text and text not in applied_state_item_ids:
                            applied_state_item_ids.append(text)
                continue

            if required_amount < min_effect:
                if emit_pruned_diagnostics:
                    diagnostics.append(
                        self._build_priority_neutralization_diagnostic(
                            item=item,
                            structure_signature=structure_signature,
                            required_energy_key=required_energy_key,
                            raw_required_amount=required_amount_raw,
                            required_amount=required_amount,
                            available_amount=0.0,
                            consumed_amount=0.0,
                            packet_available_amount=packet_total_required_available,
                            matched_unit_count=len(matched_units),
                            matched_tokens=matched_tokens,
                            common_length=common_length,
                            structure_unit_count=structure_unit_count,
                            packet_unit_count=packet_unit_count,
                            potential_overlap_units=potential_overlap_units,
                            potential_structure_coverage=potential_structure_coverage,
                            potential_input_coverage=potential_input_coverage,
                            structure_coverage=structure_coverage,
                            input_coverage=input_coverage,
                            order_score=order_score,
                            bundle_score=bundle_score,
                            match_score=match_score,
                            neutralization_mode="soft_partial_cache" if soft_matching_enabled else "exact_full_cache",
                            status="skipped",
                            skipped_reason="effective_budget_below_threshold",
                            target_display=target_display,
                        )
                    )
                continue

            available_amount = round(
                sum(max(0.0, float(unit.get(required_energy_key, 0.0))) for unit in matched_units),
                8,
            )
            consumed_amount = self._consume_packet_unit_energy(
                matched_units=matched_units,
                energy_key=required_energy_key,
                amount=required_amount,
            )
            if cp_delta < 0.0:
                delta_er = consumed_amount
                delta_ev = 0.0
                reason = "priority_stimulus_real_verification"
            else:
                delta_er = 0.0
                delta_ev = consumed_amount
                reason = "priority_stimulus_virtual_confirmation"

            if consumed_amount > 0.0 and not always_rebuild_packet_groups:
                packet_groups_dirty = True

            diagnostics.append(
                self._build_priority_neutralization_diagnostic(
                    item=item,
                    structure_signature=structure_signature,
                    required_energy_key=required_energy_key,
                    raw_required_amount=required_amount_raw,
                    required_amount=required_amount,
                    available_amount=available_amount,
                    consumed_amount=consumed_amount,
                    packet_available_amount=packet_total_required_available,
                    matched_unit_count=len(matched_units),
                    matched_tokens=matched_tokens,
                    common_length=common_length,
                    structure_unit_count=structure_unit_count,
                    packet_unit_count=packet_unit_count,
                    potential_overlap_units=potential_overlap_units,
                    potential_structure_coverage=potential_structure_coverage,
                    potential_input_coverage=potential_input_coverage,
                    structure_coverage=structure_coverage,
                    input_coverage=input_coverage,
                    order_score=order_score,
                    bundle_score=bundle_score,
                    match_score=match_score,
                    neutralization_mode="soft_partial_cache" if soft_matching_enabled else "exact_full_cache",
                    status="applied" if consumed_amount >= min_effect else ("shortfall" if available_amount <= 0.0 else "below_effect_threshold"),
                    skipped_reason="" if consumed_amount >= min_effect else ("matched_energy_too_thin" if available_amount > 0.0 else "matched_energy_empty"),
                    target_display=target_display,
                )
            )

            if consumed_amount < min_effect:
                continue

            event = self._energy.apply_energy_delta(
                item=item,
                delta_er=delta_er,
                delta_ev=delta_ev,
                tick_number=tick_number,
                reason=reason,
                source_module=source_module,
                trace_id=trace_id,
                tick_id=tick_id,
            )
            event["event_type"] = "priority_stimulus_neutralization"
            event["matched_structure_signature"] = structure_signature
            event["matched_unit_count"] = len(matched_units)
            event["neutralization_mode"] = "soft_partial_cache" if soft_matching_enabled else "exact_full_cache"
            event["extra_context"] = {
                "consumed_energy_key": required_energy_key,
                "consumed_amount": round(consumed_amount, 8),
                "matched_unit_count": len(matched_units),
                "matched_tokens": matched_tokens,
                "match_score": match_score,
                "structure_coverage": structure_coverage,
                "input_coverage": input_coverage,
                "order_score": order_score,
            }
            events.append(event)
            neutralized_item_count += 1
            consumed_any = True

        residual_packet = (
            self._prune_stimulus_packet_after_consumption(stimulus_packet)
            if consumed_any
            else stimulus_packet
        )
        cut_metrics = cut_engine.pop_runtime_metrics()
        cut_metrics["priority_neutralization_theoretical_match_fast_reject_count"] = int(
            theoretical_match_fast_reject_count
        )
        return {
            "residual_packet": residual_packet,
            "events": events,
            "diagnostics": diagnostics,
            "neutralized_item_count": neutralized_item_count,
            "cut_metrics": cut_metrics,
            "applied_state_item_ids": applied_state_item_ids,
            "event_component_neutralization_count": event_component_neutralization_count,
            "event_component_neutralization_er_added_sum": round(event_component_neutralization_er_added_sum, 8),
            "event_component_neutralization_ev_added_sum": round(event_component_neutralization_ev_added_sum, 8),
            "event_component_cp_drop_sum": round(event_component_cp_drop_sum, 8),
        }

    def _build_packet_groups_for_neutralization(
        self,
        stimulus_packet: dict,
        *,
        cut_engine,
        _cached_profile: dict | None = None,
        _energy_ref_by_id: dict[str, dict] | None = None,
    ) -> list[dict]:
        """把刺激包转成与 cut engine 一致的完整 SA/CSA 视图。"""
        profile = (
            _cached_profile
            if isinstance(_cached_profile, dict)
            else cut_engine.build_sequence_profile_from_stimulus_packet(stimulus_packet)
        )
        if isinstance(_energy_ref_by_id, dict):
            energy_ref_by_id = _energy_ref_by_id
        else:
            energy_ref_by_id = {}
            for item in stimulus_packet.get("sa_items", []):
                if isinstance(item, dict) and item.get("id"):
                    energy_ref_by_id[str(item.get("id", ""))] = item.setdefault("energy", {})

        packet_groups = []
        for group in profile.get("sequence_groups", []):
            units = []
            for unit in group.get("units", []):
                unit_id = str(unit.get("unit_id", ""))
                energy_ref = energy_ref_by_id.get(unit_id)
                if energy_ref is None:
                    energy_ref = {
                        "er": round(float(unit.get("er", 0.0)), 8),
                        "ev": round(float(unit.get("ev", 0.0)), 8),
                    }
                er = max(0.0, float(energy_ref.get("er", 0.0)))
                ev = max(0.0, float(energy_ref.get("ev", 0.0)))
                if er + ev <= 0.0:
                    continue
                units.append(
                    {
                        **dict(unit),
                        "unit_id": unit_id,
                        "unit_type": str(unit.get("object_type", "sa")),
                        "sequence_index": int(unit.get("sequence_index", 0)),
                        "er": round(er, 8),
                        "ev": round(ev, 8),
                        "total_energy": round(er + ev, 8),
                        "energy_ref": energy_ref,
                    }
                )
            if not units:
                continue
            raw_packet_group = {
                "group_index": int(group.get("group_index", len(packet_groups))),
                "source_type": group.get("source_type", ""),
                "origin_frame_id": group.get("origin_frame_id", ""),
                "tokens": [str(unit.get("token", "")) for unit in units if str(unit.get("token", ""))],
                "display_text": group.get("display_text", ""),
                "order_sensitive": bool(group.get("order_sensitive", False)),
                "string_unit_kind": str(group.get("string_unit_kind", "") or ""),
                "string_token_text": str(group.get("string_token_text", "") or ""),
                "units": units,
                "csa_bundles": [dict(bundle) for bundle in group.get("csa_bundles", [])],
            }
            normalize_group = getattr(cut_engine, "_normalize_sequence_group", None)
            if callable(normalize_group):
                normalized_group = normalize_group(raw_packet_group, order_index=len(packet_groups))
                if normalized_group.get("units"):
                    packet_groups.append(normalized_group)
            else:
                packet_groups.append(raw_packet_group)

        return packet_groups

    def _settle_priority_neutralization_on_matched_sas(
        self,
        *,
        item: dict,
        structure_signature: str,
        target_display: str,
        structure_groups: list[dict],
        packet_groups: list[dict],
        common_part: dict,
        matched_units: list[dict],
        match_score: float,
        min_effect: float,
        tick_number: int,
        source_module: str,
        trace_id: str,
        tick_id: str,
        neutralization_mode: str,
        structure_coverage: float,
        input_coverage: float,
        order_score: float,
        bundle_score: float,
        sa_items_by_ref: dict[str, dict],
        sa_items_by_token: dict[str, list[dict]],
        packet_units_by_id: dict[str, dict] | None = None,
    ) -> dict:
        structure_units_by_id = self._index_group_units_by_id(structure_groups)
        if not isinstance(packet_units_by_id, dict):
            packet_units_by_id = self._index_group_units_by_id(packet_groups)
        sa_plans: dict[str, dict] = {}

        for pair in common_part.get("matched_pairs", []):
            existing_refs = [str(text) for text in pair.get("existing_unit_refs", []) if str(text)]
            incoming_refs = [str(text) for text in pair.get("incoming_unit_refs", []) if str(text)]
            common_tokens = [str(text) for text in pair.get("common_tokens", []) if str(text)]
            pair_count = min(len(existing_refs), len(incoming_refs))
            for index in range(pair_count):
                existing_ref = existing_refs[index]
                incoming_ref = incoming_refs[index]
                packet_unit = packet_units_by_id.get(incoming_ref)
                if not isinstance(packet_unit, dict):
                    continue
                structure_unit = dict(structure_units_by_id.get(existing_ref, {}) or {})
                unit_token = str(
                    structure_unit.get("token", "")
                    or (common_tokens[index] if index < len(common_tokens) else "")
                    or packet_unit.get("token", "")
                    or ""
                )
                sa_item, resolution_mode = self._resolve_priority_neutralization_sa_target(
                    owner_item=item,
                    unit_ref=existing_ref,
                    unit_token=unit_token,
                    sa_items_by_ref=sa_items_by_ref,
                    sa_items_by_token=sa_items_by_token,
                )
                if not isinstance(sa_item, dict):
                    continue
                sa_plan = sa_plans.setdefault(
                    str(sa_item.get("id", "")),
                    {
                        "sa_item": sa_item,
                        "support_units": [],
                        "support_unit_ids": set(),
                        "matched_tokens": [],
                        "resolution_modes": set(),
                    },
                )
                packet_unit_id = str(packet_unit.get("unit_id", "") or "")
                if packet_unit_id and packet_unit_id not in sa_plan["support_unit_ids"]:
                    sa_plan["support_unit_ids"].add(packet_unit_id)
                    sa_plan["support_units"].append(packet_unit)
                elif not packet_unit_id:
                    sa_plan["support_units"].append(packet_unit)
                if unit_token and unit_token not in sa_plan["matched_tokens"]:
                    sa_plan["matched_tokens"].append(unit_token)
                if resolution_mode:
                    sa_plan["resolution_modes"].add(resolution_mode)

        if not sa_plans:
            return {
                "status": "skipped",
                "skipped_reason": "no_runtime_sa_target",
                "required_energy_key": "",
                "raw_required_amount": 0.0,
                "required_amount": 0.0,
                "available_amount": 0.0,
                "packet_available_amount": 0.0,
                "consumed_amount": 0.0,
                "consumed_er": 0.0,
                "consumed_ev": 0.0,
                "sa_target_count": 0,
                "sa_resolved_count": 0,
                "sa_settled_count": 0,
                "sa_settlements": [],
                "consumed_any": False,
                "applied_state_item_ids": [],
            }

        keys_used: set[str] = set()
        required_er_total = 0.0
        required_ev_total = 0.0
        available_er_total = 0.0
        available_ev_total = 0.0
        raw_required_total = 0.0
        scaled_required_total = 0.0
        total_available = 0.0
        total_consumed = 0.0
        total_consumed_er = 0.0
        total_consumed_ev = 0.0
        sa_settled_count = 0
        applied_state_item_ids: list[str] = []
        sa_settlements: list[dict] = []

        for plan in sa_plans.values():
            sa_item = plan.get("sa_item")
            if not isinstance(sa_item, dict):
                continue
            before_er = round(max(0.0, float(sa_item.get("energy", {}).get("er", 0.0) or 0.0)), 8)
            before_ev = round(max(0.0, float(sa_item.get("energy", {}).get("ev", 0.0) or 0.0)), 8)
            if before_ev > before_er:
                energy_key = "er"
                deficit = round(before_ev - before_er, 8)
                required_er_total = round(required_er_total + deficit, 8)
            elif before_er > before_ev:
                energy_key = "ev"
                deficit = round(before_er - before_ev, 8)
                required_ev_total = round(required_ev_total + deficit, 8)
            else:
                sa_settlements.append(
                    {
                        "target_item_id": sa_item.get("id", ""),
                        "target_ref_object_id": sa_item.get("ref_object_id", ""),
                        "target_display": sa_item.get("ref_snapshot", {}).get("content_display", "") or sa_item.get("ref_object_id", ""),
                        "matched_tokens": list(plan.get("matched_tokens", []) or []),
                        "energy_key": "",
                        "deficit": 0.0,
                        "packet_available": 0.0,
                        "required_after_score": 0.0,
                        "consumed": 0.0,
                        "resolution_modes": sorted(str(mode) for mode in plan.get("resolution_modes", set()) if str(mode)),
                    }
                )
                continue

            support_units = list(plan.get("support_units", []) or [])
            available_amount = round(
                sum(max(0.0, float(unit.get(energy_key, 0.0) or 0.0)) for unit in support_units),
                8,
            )
            raw_required_total = round(raw_required_total + deficit, 8)
            scaled_required_total = round(scaled_required_total + deficit * float(match_score), 8)
            total_available = round(total_available + available_amount, 8)
            keys_used.add(energy_key)
            if energy_key == "er":
                available_er_total = round(available_er_total + available_amount, 8)
            else:
                available_ev_total = round(available_ev_total + available_amount, 8)

            required_after_score = round(deficit * float(match_score), 8)
            consumed_amount = 0.0
            if available_amount > 0.0:
                effective_cap = min(deficit, available_amount)
                planned_amount = round(effective_cap * float(match_score), 8)
                if planned_amount > 0.0:
                    consumed_amount = self._consume_packet_unit_energy(
                        matched_units=support_units,
                        energy_key=energy_key,
                        amount=planned_amount,
                    )
                    if consumed_amount > 0.0:
                        if energy_key == "er":
                            self._energy.apply_energy_delta(
                                item=sa_item,
                                delta_er=consumed_amount,
                                delta_ev=0.0,
                                tick_number=tick_number,
                                reason="priority_stimulus_real_verification",
                                source_module=source_module,
                                trace_id=trace_id,
                                tick_id=tick_id,
                            )
                            total_consumed_er = round(total_consumed_er + consumed_amount, 8)
                        else:
                            self._energy.apply_energy_delta(
                                item=sa_item,
                                delta_er=0.0,
                                delta_ev=consumed_amount,
                                tick_number=tick_number,
                                reason="priority_stimulus_virtual_confirmation",
                                source_module=source_module,
                                trace_id=trace_id,
                                tick_id=tick_id,
                            )
                            total_consumed_ev = round(total_consumed_ev + consumed_amount, 8)
                        total_consumed = round(total_consumed + consumed_amount, 8)
                        sa_settled_count += 1
                        target_item_id = str(sa_item.get("id", "") or "")
                        if target_item_id and target_item_id not in applied_state_item_ids:
                            applied_state_item_ids.append(target_item_id)

            sa_settlements.append(
                {
                    "target_item_id": sa_item.get("id", ""),
                    "target_ref_object_id": sa_item.get("ref_object_id", ""),
                    "target_display": sa_item.get("ref_snapshot", {}).get("content_display", "") or sa_item.get("ref_object_id", ""),
                    "matched_tokens": list(plan.get("matched_tokens", []) or []),
                    "energy_key": energy_key,
                    "deficit": deficit,
                    "packet_available": available_amount,
                    "required_after_score": required_after_score,
                    "consumed": round(consumed_amount, 8),
                    "resolution_modes": sorted(str(mode) for mode in plan.get("resolution_modes", set()) if str(mode)),
                }
            )

        required_energy_key = ""
        if len(keys_used) == 1:
            required_energy_key = next(iter(keys_used))
        elif len(keys_used) > 1:
            required_energy_key = "mixed"

        status = ""
        skipped_reason = ""
        if raw_required_total <= 0.0:
            status = "skipped"
            skipped_reason = "matched_sa_balanced"
        elif scaled_required_total < min_effect:
            status = "skipped"
            skipped_reason = "effective_budget_below_threshold"
        elif total_available <= 0.0:
            status = "shortfall"
            skipped_reason = "matched_sa_no_opposite_energy"
        elif total_consumed >= min_effect:
            status = "applied"
        else:
            status = "below_effect_threshold"
            skipped_reason = "matched_energy_too_thin"

        summary_event = None
        if total_consumed >= min_effect:
            item.setdefault("energy", {})["ownership_level"] = "aggregated_from_sa"
            item.setdefault("energy", {})["computed_from_children"] = True
            projection_event = self._energy.apply_energy_delta(
                item=item,
                delta_er=total_consumed_er,
                delta_ev=total_consumed_ev,
                tick_number=tick_number,
                reason="priority_neutralization_sa_projection_sync",
                source_module=source_module,
                trace_id=trace_id,
                tick_id=tick_id,
            )
            projection_event["event_type"] = "priority_stimulus_neutralization"
            projection_event["reason"] = "priority_stimulus_sa_settlement_projection"
            projection_event["target_ref_object_id"] = item.get("ref_object_id", "")
            projection_event["target_ref_object_type"] = item.get("ref_object_type", "")
            projection_event["target_display"] = target_display
            projection_event["matched_structure_signature"] = structure_signature
            projection_event["matched_unit_count"] = len(matched_units)
            projection_event["neutralization_mode"] = neutralization_mode
            projection_event["extra_context"] = {
                "consumed_energy_key": required_energy_key or "mixed",
                "consumed_amount": round(total_consumed, 8),
                "consumed_er": round(total_consumed_er, 8),
                "consumed_ev": round(total_consumed_ev, 8),
                "matched_unit_count": len(matched_units),
                "matched_tokens": [str(unit.get("token", "")) for unit in matched_units if str(unit.get("token", ""))],
                "match_score": round(float(match_score), 8),
                "structure_coverage": round(float(structure_coverage), 8),
                "input_coverage": round(float(input_coverage), 8),
                "order_score": round(float(order_score), 8),
                "bundle_score": round(float(bundle_score), 8),
                "sa_target_count": len(sa_plans),
                "sa_settled_count": int(sa_settled_count),
                "sa_settlement_preview": list(sa_settlements[:8]),
            }
            summary_event = projection_event
            if item.get("id") and item.get("id") not in applied_state_item_ids:
                applied_state_item_ids.append(str(item.get("id")))

        return {
            "status": status,
            "skipped_reason": skipped_reason,
            "required_energy_key": required_energy_key,
            "raw_required_amount": round(raw_required_total, 8),
            "required_amount": round(scaled_required_total, 8),
            "available_amount": round(total_available, 8),
            "packet_available_amount": round(total_available, 8),
            "consumed_amount": round(total_consumed, 8),
            "consumed_er": round(total_consumed_er, 8),
            "consumed_ev": round(total_consumed_ev, 8),
            "required_er_total": round(required_er_total, 8),
            "required_ev_total": round(required_ev_total, 8),
            "available_er_total": round(available_er_total, 8),
            "available_ev_total": round(available_ev_total, 8),
            "sa_target_count": len(sa_plans),
            "sa_resolved_count": len(sa_plans),
            "sa_settled_count": int(sa_settled_count),
            "sa_settlements": list(sa_settlements[:12]),
            "consumed_any": bool(total_consumed > 0.0),
            "applied_state_item_ids": applied_state_item_ids,
            "event": summary_event,
        }

    @staticmethod
    def _index_group_units_by_id(groups: list[dict]) -> dict[str, dict]:
        index: dict[str, dict] = {}
        for group in groups:
            for unit in group.get("units", []) or []:
                unit_id = str(unit.get("unit_id", "") or "")
                if unit_id and unit_id not in index:
                    index[unit_id] = unit
        return index

    def _resolve_priority_neutralization_sa_target(
        self,
        *,
        owner_item: dict,
        unit_ref: str,
        unit_token: str,
        sa_items_by_ref: dict[str, dict],
        sa_items_by_token: dict[str, list[dict]],
    ) -> tuple[dict | None, str]:
        direct_hit = sa_items_by_ref.get(str(unit_ref or ""))
        if isinstance(direct_hit, dict):
            return direct_hit, "ref"

        token = str(unit_token or "").strip()
        if not token:
            return None, ""
        candidates = [candidate for candidate in sa_items_by_token.get(token, []) if isinstance(candidate, dict)]
        if not candidates:
            return None, ""
        if len(candidates) == 1:
            return candidates[0], "token_unique"

        owner_snapshot = owner_item.get("ref_snapshot", {}) or {}
        owner_context_ids = {
            str(owner_item.get("ref_object_id", "") or ""),
            str(owner_snapshot.get("context_ref_object_id", "") or ""),
            str(owner_snapshot.get("context_owner_id", "") or ""),
        }
        owner_context_ids.update(str(text) for text in owner_snapshot.get("context_path_ids", []) if str(text))
        filtered = []
        for candidate in candidates:
            source = candidate.get("source", {}) or {}
            candidate_context_ids = {
                str(source.get("context_ref_object_id", "") or ""),
                str(source.get("context_owner_structure_id", "") or ""),
            }
            candidate_context_ids.update(str(text) for text in source.get("context_path_ids", []) if str(text))
            candidate_context_ids.update(str(text) for text in source.get("parent_ids", []) if str(text))
            if owner_context_ids.intersection(candidate_context_ids):
                filtered.append(candidate)
        if len(filtered) == 1:
            return filtered[0], "token_context"
        return None, ""

    def _extract_sequence_groups_from_state_item(self, item: dict) -> list[dict]:
        """从状态池对象中提取稳定的结构时序分组。"""
        ref_snapshot = item.get("ref_snapshot", {})
        sequence_groups = list(ref_snapshot.get("sequence_groups", []))
        if sequence_groups:
            # PERF: CutEngine.maximum_common_part() 内部会归一化并拷贝输入，不会就地修改原对象。
            # 这里深拷贝会随着结构规模增长产生明显开销。
            return sequence_groups

        flat_tokens = list(ref_snapshot.get("flat_tokens", []))
        if not flat_tokens:
            return []
        return [
            {
                "group_index": 0,
                "source_type": "state_pool",
                "origin_frame_id": item.get("ref_object_id", ""),
                "tokens": flat_tokens,
            }
        ]

    def _priority_neutralization_group_stats(
        self,
        *,
        item: dict,
        structure_groups: list[dict],
        structure_signature: str,
    ) -> dict:
        item_id = str(item.get("id", "") or item.get("item_id", "") or "")
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        key = (
            item_id,
            str(item.get("ref_object_id", "") or ""),
            str(item.get("ref_object_type", "") or ""),
            str(structure_signature or ref_snapshot.get("content_signature", "") or ""),
            len(structure_groups or []),
        )
        cache = self._priority_neutralization_group_stats_cache
        cached = cache.get(key)
        if isinstance(cached, dict):
            return {
                "unit_count": int(cached.get("unit_count", 0) or 0),
                "token_counter": Counter(cached.get("token_counter", {}) or {}),
            }
        stats = {
            "unit_count": self._count_group_units(structure_groups),
            "token_counter": self._build_group_token_counter(structure_groups),
        }
        cache[key] = {
            "unit_count": int(stats["unit_count"]),
            "token_counter": dict(stats["token_counter"]),
        }
        try:
            limit = int(self._config.get("priority_neutralization_group_stats_cache_max_entries", 4096) or 4096)
        except Exception:
            limit = 4096
        if limit > 0 and len(cache) > limit:
            for old_key in list(cache.keys())[: max(1, len(cache) - limit)]:
                cache.pop(old_key, None)
        return stats

    def _priority_neutralize_cognitive_stitching_event(
        self,
        *,
        item: dict,
        packet_groups: list[dict],
        tick_number: int,
        min_effect: float,
        source_module: str,
        trace_id: str,
        tick_id: str,
    ) -> dict:
        if not self._config.get("enable_event_component_neutralization", True):
            return {"handled": False}
        if not self._is_cognitive_stitching_event_item(item):
            return {"handled": False}

        component_matches = self._collect_cognitive_stitching_component_matches(
            item=item,
            packet_groups=packet_groups,
        )
        if not component_matches:
            return {"handled": False}

        ratio_cap = max(0.0, min(1.0, float(self._config.get("event_component_neutralization_ratio_cap", 1.0))))
        ref_snapshot = item.get("ref_snapshot", {}) or {}
        structure_signature = str(ref_snapshot.get("content_signature", "") or item.get("ref_object_id", "") or "").strip()
        target_display = (
            ref_snapshot.get("content_display", "")
            or ref_snapshot.get("content_display_detail", "")
            or item.get("ref_object_id", "")
            or item.get("id", "")
        )

        total_delta_er = 0.0
        total_delta_ev = 0.0
        component_cp_drop_sum = 0.0
        total_required = 0.0
        total_available = 0.0
        total_consumed = 0.0
        total_shortfall = 0.0
        matched_unit_count = 0
        component_neutralization_count = 0
        matched_components: list[str] = []
        matched_tokens: list[str] = []
        component_updates: list[dict] = []
        energy_keys_used: list[str] = []

        for match in component_matches:
            ledger_entry = match["ledger_entry"]
            matched_units = list(match.get("matched_units", []) or [])
            if not matched_units:
                continue

            before_er = round(max(0.0, float(ledger_entry.get("er", 0.0) or 0.0)), 8)
            before_ev = round(max(0.0, float(ledger_entry.get("ev", 0.0) or 0.0)), 8)
            before_cp = round(abs(before_er - before_ev), 8)

            if before_ev > before_er:
                energy_key = "er"
                required_amount = round((before_ev - before_er) * ratio_cap, 8)
                available_amount = round(
                    sum(max(0.0, float(unit.get("er", 0.0) or 0.0)) for unit in matched_units),
                    8,
                )
                consumed_amount = self._consume_packet_unit_energy(
                    matched_units=matched_units,
                    energy_key="er",
                    amount=required_amount,
                )
                after_er = round(before_er + consumed_amount, 8)
                after_ev = before_ev
                total_delta_er = round(total_delta_er + consumed_amount, 8)
            elif before_er > before_ev:
                energy_key = "ev"
                required_amount = round((before_er - before_ev) * ratio_cap, 8)
                available_amount = round(
                    sum(max(0.0, float(unit.get("ev", 0.0) or 0.0)) for unit in matched_units),
                    8,
                )
                consumed_amount = self._consume_packet_unit_energy(
                    matched_units=matched_units,
                    energy_key="ev",
                    amount=required_amount,
                )
                after_er = before_er
                after_ev = round(before_ev + consumed_amount, 8)
                total_delta_ev = round(total_delta_ev + consumed_amount, 8)
            else:
                energy_key = "balanced"
                required_amount = 0.0
                available_amount = 0.0
                consumed_amount = 0.0
                after_er = before_er
                after_ev = before_ev

            ledger_entry["er"] = after_er
            ledger_entry["ev"] = after_ev
            ledger_entry["cp_abs"] = round(abs(after_er - after_ev), 8)
            cp_drop = round(max(0.0, before_cp - ledger_entry["cp_abs"]), 8)

            total_required = round(total_required + required_amount, 8)
            total_available = round(total_available + available_amount, 8)
            total_consumed = round(total_consumed + consumed_amount, 8)
            total_shortfall = round(total_shortfall + max(0.0, required_amount - consumed_amount), 8)
            component_cp_drop_sum = round(component_cp_drop_sum + cp_drop, 8)
            matched_unit_count += len(matched_units)
            if consumed_amount > 0.0:
                component_neutralization_count += 1
                if energy_key in ("er", "ev"):
                    energy_keys_used.append(energy_key)

            matched_components.append(str(ledger_entry.get("display", "") or ledger_entry.get("ref_id", "")))
            matched_tokens.extend(
                str(unit.get("token", ""))
                for unit in matched_units
                if str(unit.get("token", ""))
            )
            component_updates.append(
                {
                    "component_index": int(ledger_entry.get("index", 0) or 0),
                    "component_ref_id": str(ledger_entry.get("ref_id", "") or ""),
                    "component_display": str(ledger_entry.get("display", "") or ledger_entry.get("ref_id", "")),
                    "required_energy_key": energy_key,
                    "required_amount": round(required_amount, 8),
                    "available_amount": round(available_amount, 8),
                    "consumed_amount": round(consumed_amount, 8),
                    "shortfall_amount": round(max(0.0, required_amount - consumed_amount), 8),
                    "before_er": before_er,
                    "before_ev": before_ev,
                    "after_er": after_er,
                    "after_ev": after_ev,
                    "before_cp_abs": before_cp,
                    "after_cp_abs": ledger_entry["cp_abs"],
                    "cp_drop": cp_drop,
                    "matched_tokens": [
                        str(unit.get("token", ""))
                        for unit in matched_units
                        if str(unit.get("token", ""))
                    ],
                }
            )

        matched_components = self._deduplicate_strings(matched_components)
        matched_tokens = self._deduplicate_strings(matched_tokens)
        consumed_key = self._merge_consumed_energy_keys(energy_keys_used)
        diagnostic = {
            "target_item_id": item.get("id", ""),
            "target_ref_object_id": item.get("ref_object_id", ""),
            "target_ref_object_type": item.get("ref_object_type", ""),
            "target_display": target_display,
            "matched_structure_signature": structure_signature,
            "neutralization_mode": "event_component_complementary",
            "required_energy_key": consumed_key,
            "required_amount": round(total_required, 8),
            "available_amount": round(total_available, 8),
            "consumed_amount": round(total_consumed, 8),
            "shortfall_amount": round(total_shortfall, 8),
            "matched_unit_count": matched_unit_count,
            "matched_component_count": len(component_matches),
            "matched_components": matched_components,
            "matched_tokens": matched_tokens,
            "component_cp_drop_sum": round(component_cp_drop_sum, 8),
            "component_updates": component_updates,
        }

        if total_consumed < float(min_effect):
            return {
                "handled": True,
                "diagnostic": diagnostic,
                "event": None,
                "consumed_any": False,
                "component_neutralization_count": 0,
                "total_delta_er": 0.0,
                "total_delta_ev": 0.0,
                "component_cp_drop_sum": round(component_cp_drop_sum, 8),
            }

        cs_meta = self._get_cognitive_stitching_event_meta(item, ensure=True)
        cs_meta["component_ledger"] = self._ensure_cognitive_stitching_component_ledger(item)
        cs_meta["last_component_neutralization_tick"] = int(tick_number)

        event = self._energy.apply_energy_delta(
            item=item,
            delta_er=total_delta_er,
            delta_ev=total_delta_ev,
            tick_number=tick_number,
            reason="priority_event_component_neutralization",
            source_module=source_module,
            trace_id=trace_id,
            tick_id=tick_id,
        )
        event["event_type"] = "priority_event_component_neutralization"
        event["matched_structure_signature"] = structure_signature
        event["matched_unit_count"] = matched_unit_count
        event["target_display"] = target_display
        event["extra_context"] = {
            "neutralization_mode": "event_component_complementary",
            "consumed_energy_key": consumed_key,
            "consumed_amount": round(total_consumed, 8),
            "matched_unit_count": matched_unit_count,
            "matched_component_count": len(component_matches),
            "matched_components": matched_components,
            "matched_tokens": matched_tokens,
            "component_cp_drop_sum": round(component_cp_drop_sum, 8),
            "component_neutralization_count": component_neutralization_count,
            "component_updates": component_updates,
        }
        return {
            "handled": True,
            "diagnostic": diagnostic,
            "event": event,
            "consumed_any": True,
            "component_neutralization_count": component_neutralization_count,
            "total_delta_er": round(total_delta_er, 8),
            "total_delta_ev": round(total_delta_ev, 8),
            "component_cp_drop_sum": round(component_cp_drop_sum, 8),
        }

    def _is_cognitive_stitching_event_item(self, item: dict) -> bool:
        if str(item.get("ref_object_type", "") or "") != "st":
            return False
        prefix = "cs_event::"
        ref_object_id = str(item.get("ref_object_id", "") or "")
        if ref_object_id.startswith(prefix):
            return True

        # HDB-backed CS events use structure_id as ref_object_id. The canonical event_ref_id
        # is stored in structure.content_signature (ref_snapshot.content_signature).
        ref_snapshot = item.get("ref_snapshot", {}) or {}
        try:
            snap_sig = str(ref_snapshot.get("content_signature", "") or "").strip()
        except Exception:
            snap_sig = ""
        if snap_sig.startswith(prefix):
            return True

        # Fall back to explicit CS metadata if present.
        structure_ext = ref_snapshot.get("structure_ext", {}) or {}
        cs_meta = structure_ext.get("cognitive_stitching")
        if isinstance(cs_meta, dict):
            event_ref_id = str(cs_meta.get("event_ref_id", "") or cs_meta.get("cs_event_ref_id", "") or "").strip()
            if event_ref_id.startswith(prefix):
                return True

        meta_ext = (item.get("meta", {}) or {}).get("ext", {}) or {}
        cs_meta2 = meta_ext.get("cognitive_stitching")
        if isinstance(cs_meta2, dict):
            event_ref_id2 = str(cs_meta2.get("event_ref_id", "") or cs_meta2.get("cs_event_ref_id", "") or "").strip()
            if event_ref_id2.startswith(prefix):
                return True

        return False

    def _get_cognitive_stitching_event_meta(self, item: dict, *, ensure: bool = False) -> dict | None:
        meta = item.setdefault("meta", {}) if ensure else item.get("meta", {})
        if not isinstance(meta, dict):
            return None
        meta_ext = meta.setdefault("ext", {}) if ensure else meta.get("ext", {})
        if not isinstance(meta_ext, dict):
            return None
        existing = meta_ext.get("cognitive_stitching")
        if isinstance(existing, dict):
            return existing

        ref_snapshot = item.get("ref_snapshot", {}) or {}
        structure_ext = ref_snapshot.get("structure_ext", {}) or {}
        ref_meta = structure_ext.get("cognitive_stitching")
        if isinstance(ref_meta, dict):
            copied = copy.deepcopy(ref_meta)
            if ensure:
                meta_ext["cognitive_stitching"] = copied
            return copied

        if ensure:
            meta_ext["cognitive_stitching"] = {}
            return meta_ext["cognitive_stitching"]
        return None

    def _ensure_cognitive_stitching_component_ledger(self, item: dict) -> list[dict]:
        cs_meta = self._get_cognitive_stitching_event_meta(item, ensure=True) or {}
        existing_ledger = list(cs_meta.get("component_ledger", []) or [])
        if existing_ledger:
            normalized = []
            for index, entry in enumerate(existing_ledger):
                if not isinstance(entry, dict):
                    continue
                ref_id = str(entry.get("ref_id", "") or "")
                display = str(entry.get("display", "") or ref_id)
                er = round(max(0.0, float(entry.get("er", 0.0) or 0.0)), 8)
                ev = round(max(0.0, float(entry.get("ev", 0.0) or 0.0)), 8)
                normalized.append(
                    {
                        "index": int(entry.get("index", index) or index),
                        "ref_id": ref_id,
                        "display": display,
                        "tokens": list(entry.get("tokens", []) or ([display] if display else [])),
                        "profile_share": round(max(0.0, float(entry.get("profile_share", 0.0) or 0.0)), 8),
                        "er": er,
                        "ev": ev,
                        "cp_abs": round(abs(er - ev), 8),
                    }
                )
            cs_meta["component_ledger"] = normalized
            return normalized

        ref_snapshot = item.get("ref_snapshot", {}) or {}
        member_refs = list(ref_snapshot.get("member_refs", []) or cs_meta.get("member_refs", []) or [])
        if not member_refs:
            ref_object_id = str(item.get("ref_object_id", "") or "")
            if ref_object_id.startswith("cs_event::"):
                member_refs = [part for part in ref_object_id.split("::")[1:] if part]
        displays = list(ref_snapshot.get("flat_tokens", []) or [])
        component_count = max(len(member_refs), len(displays))
        if component_count <= 0:
            cs_meta["component_ledger"] = []
            return []

        total_er = round(max(0.0, float(item.get("energy", {}).get("er", 0.0) or 0.0)), 8)
        total_ev = round(max(0.0, float(item.get("energy", {}).get("ev", 0.0) or 0.0)), 8)
        fallback_share = round(1.0 / float(component_count), 8)
        normalized = []
        for index in range(component_count):
            ref_id = str(member_refs[index] if index < len(member_refs) else "")
            display = str(displays[index] if index < len(displays) else ref_id)
            er = round(total_er * fallback_share, 8)
            ev = round(total_ev * fallback_share, 8)
            normalized.append(
                {
                    "index": index,
                    "ref_id": ref_id,
                    "display": display or ref_id,
                    "tokens": [display] if display else [],
                    "profile_share": fallback_share,
                    "er": er,
                    "ev": ev,
                    "cp_abs": round(abs(er - ev), 8),
                }
            )
        cs_meta["member_refs"] = list(member_refs)
        cs_meta["component_profile"] = [
            {
                "index": entry["index"],
                "ref_id": entry.get("ref_id", ""),
                "display": entry.get("display", ""),
                "share": entry.get("profile_share", fallback_share),
            }
            for entry in normalized
        ]
        cs_meta["component_ledger"] = normalized
        return normalized

    def _collect_cognitive_stitching_component_matches(self, *, item: dict, packet_groups: list[dict]) -> list[dict]:
        ledger = self._ensure_cognitive_stitching_component_ledger(item)
        if not ledger:
            return []

        claimed_unit_ids: set[str] = set()
        matches: list[dict] = []
        for entry in ledger:
            token_candidates = self._deduplicate_strings(
                list(entry.get("tokens", []) or [])
                + [entry.get("display", ""), entry.get("ref_id", "")]
            )
            if not token_candidates:
                continue

            matched_units = []
            for packet_group in packet_groups:
                for unit in packet_group.get("units", []):
                    unit_id = str(unit.get("unit_id", "") or "")
                    token = str(unit.get("token", "") or "")
                    if not token or unit_id in claimed_unit_ids:
                        continue
                    if token not in token_candidates:
                        continue
                    matched_units.append(unit)
                    if unit_id:
                        claimed_unit_ids.add(unit_id)

            if matched_units:
                matches.append(
                    {
                        "ledger_entry": entry,
                        "matched_units": matched_units,
                    }
                )
        return matches

    @staticmethod
    def _deduplicate_strings(values: list[str]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "")
            if not text or text in seen:
                continue
            seen.add(text)
            ordered.append(text)
        return ordered

    @staticmethod
    def _merge_consumed_energy_keys(keys: list[str]) -> str:
        normalized = [str(key or "") for key in keys if str(key or "")]
        if not normalized:
            return "balanced"
        uniq: list[str] = []
        for key in normalized:
            if key not in uniq:
                uniq.append(key)
        if len(uniq) == 1:
            return uniq[0]
        return "mixed"

    @staticmethod
    def _priority_neutralization_target_display(item: dict) -> str:
        ref_snapshot = item.get("ref_snapshot", {}) or {}
        return (
            ref_snapshot.get("content_display", "")
            or ref_snapshot.get("content_display_detail", "")
            or item.get("ref_object_id", "")
            or item.get("id", "")
        )

    @staticmethod
    def _compute_priority_neutralization_order_score(common_part: dict) -> float:
        matched_pairs = list(common_part.get("matched_pairs", []) or [])
        if not matched_pairs:
            return 0.0
        pair_count = len(matched_pairs)
        if pair_count <= 1:
            return 1.0
        existing_indices = [int(pair.get("existing_group_index", 0) or 0) for pair in matched_pairs]
        incoming_indices = [int(pair.get("incoming_group_index", 0) or 0) for pair in matched_pairs]
        existing_span = max(existing_indices) - min(existing_indices) + 1
        incoming_span = max(incoming_indices) - min(incoming_indices) + 1
        existing_density = pair_count / max(pair_count, existing_span)
        incoming_density = pair_count / max(pair_count, incoming_span)
        return round((existing_density * incoming_density) ** 0.5, 8)

    @staticmethod
    def _build_priority_neutralization_diagnostic(
        *,
        item: dict,
        structure_signature: str,
        required_energy_key: str,
        raw_required_amount: float,
        required_amount: float,
        available_amount: float,
        consumed_amount: float,
        packet_available_amount: float,
        matched_unit_count: int,
        matched_tokens: list[str],
        common_length: int,
        structure_unit_count: int,
        packet_unit_count: int,
        potential_overlap_units: int,
        potential_structure_coverage: float,
        potential_input_coverage: float,
        structure_coverage: float,
        input_coverage: float,
        order_score: float,
        bundle_score: float,
        match_score: float,
        neutralization_mode: str,
        status: str,
        skipped_reason: str,
        target_display: str,
        sa_target_count: int = 0,
        sa_resolved_count: int = 0,
        sa_settled_count: int = 0,
        sa_settlements: list[dict] | None = None,
    ) -> dict:
        matched_tokens_clean = [str(token or "") for token in matched_tokens if str(token or "")]
        return {
            "target_item_id": item.get("id", ""),
            "target_ref_object_id": item.get("ref_object_id", ""),
            "target_ref_object_type": item.get("ref_object_type", ""),
            "target_display": target_display,
            "matched_structure_signature": structure_signature,
            "required_energy_key": str(required_energy_key or ""),
            "raw_required_amount": round(max(0.0, float(raw_required_amount)), 8),
            "required_amount": round(max(0.0, float(required_amount)), 8),
            "available_amount": round(max(0.0, float(available_amount)), 8),
            "consumed_amount": round(max(0.0, float(consumed_amount)), 8),
            "shortfall_amount": round(max(0.0, float(required_amount) - float(consumed_amount)), 8),
            "full_shortfall_amount": round(max(0.0, float(raw_required_amount) - float(consumed_amount)), 8),
            "packet_available_amount": round(max(0.0, float(packet_available_amount)), 8),
            "matched_unit_count": int(matched_unit_count or 0),
            "matched_tokens": matched_tokens_clean,
            "common_length": int(common_length or 0),
            "structure_unit_count": int(structure_unit_count or 0),
            "packet_unit_count": int(packet_unit_count or 0),
            "potential_overlap_units": int(potential_overlap_units or 0),
            "potential_structure_coverage": round(max(0.0, float(potential_structure_coverage)), 8),
            "potential_input_coverage": round(max(0.0, float(potential_input_coverage)), 8),
            "structure_coverage": round(max(0.0, float(structure_coverage)), 8),
            "input_coverage": round(max(0.0, float(input_coverage)), 8),
            "order_score": round(max(0.0, float(order_score)), 8),
            "bundle_score": round(max(0.0, float(bundle_score)), 8),
            "match_score": round(max(0.0, float(match_score)), 8),
            "neutralization_mode": str(neutralization_mode or ""),
            "status": str(status or ""),
            "skipped_reason": str(skipped_reason or ""),
            "sa_target_count": int(sa_target_count or 0),
            "sa_resolved_count": int(sa_resolved_count or 0),
            "sa_settled_count": int(sa_settled_count or 0),
            "sa_settlements": list(sa_settlements or []),
        }

    @staticmethod
    def _collect_matched_units_from_common_part(
        *,
        packet_groups: list[dict],
        common_part: dict,
        packet_unit_index_by_id: dict[str, list[dict]] | None = None,
    ) -> list[dict]:
        """根据 common_part 的 incoming_unit_refs 精确找出包内命中的单元。"""
        matched_units: list[dict] = []
        remaining_refs: dict[str, int] = {}
        for pair in common_part.get("matched_pairs", []):
            for unit_id in pair.get("incoming_unit_refs", []):
                text = str(unit_id)
                if text:
                    remaining_refs[text] = remaining_refs.get(text, 0) + 1

        if remaining_refs:
            if isinstance(packet_unit_index_by_id, dict) and packet_unit_index_by_id:
                for unit_id, needed in list(remaining_refs.items()):
                    if needed <= 0:
                        continue
                    bucket = packet_unit_index_by_id.get(unit_id, []) or []
                    if not bucket:
                        continue
                    matched_units.extend(bucket[:needed])
                    remaining_refs[unit_id] = max(0, needed - len(bucket))
                return matched_units
            for packet_group in packet_groups:
                for unit in packet_group.get("units", []):
                    unit_id = str(unit.get("unit_id", ""))
                    if remaining_refs.get(unit_id, 0) <= 0:
                        continue
                    matched_units.append(unit)
                    remaining_refs[unit_id] -= 1
            return matched_units

        for pair in common_part.get("matched_pairs", []):
            incoming_group_index = int(pair.get("incoming_group_index", -1))
            if incoming_group_index < 0 or incoming_group_index >= len(packet_groups):
                continue
            packet_group = packet_groups[incoming_group_index]
            remaining_tokens: dict[str, int] = {}
            for token in pair.get("common_tokens", []):
                key = str(token)
                remaining_tokens[key] = remaining_tokens.get(key, 0) + 1
            for unit in packet_group.get("units", []):
                token = str(unit.get("token", ""))
                if remaining_tokens.get(token, 0) <= 0:
                    continue
                matched_units.append(unit)
                remaining_tokens[token] -= 1
        return matched_units

    @staticmethod
    def _index_group_units_by_id_list(groups: list[dict]) -> dict[str, list[dict]]:
        index: dict[str, list[dict]] = {}
        for group in groups or []:
            if not isinstance(group, dict):
                continue
            for unit in group.get("units", []) or []:
                if not isinstance(unit, dict):
                    continue
                unit_id = str(unit.get("unit_id", "") or "")
                if not unit_id:
                    continue
                index.setdefault(unit_id, []).append(unit)
        return index

    @staticmethod
    def _count_counter_overlap(required: Counter[str], available: Counter[str]) -> int:
        total = 0
        for token, need in required.items():
            total += min(int(need), int(available.get(token, 0)))
        return total

    @staticmethod
    def _build_group_token_counter(groups: list[dict]) -> Counter[str]:
        counter: Counter[str] = Counter()
        for group in groups or []:
            units = list(group.get("units", []) or [])
            if units:
                for unit in units:
                    token = str(unit.get("token", "") or "")
                    if token:
                        counter[token] += 1
                continue
            for token in group.get("tokens", []) or []:
                text = str(token or "")
                if text:
                    counter[text] += 1
        return counter

    @staticmethod
    def _count_group_units(groups: list[dict]) -> int:
        total = 0
        for group in groups or []:
            units = list(group.get("units", []) or [])
            if units:
                total += len(units)
            else:
                total += len(list(group.get("tokens", []) or []))
        return total

    @staticmethod
    def _sum_group_energy(groups: list[dict], energy_key: str) -> float:
        total = 0.0
        for group in groups or []:
            for unit in group.get("units", []) or []:
                total += max(0.0, float(unit.get(energy_key, 0.0) or 0.0))
        return round(total, 8)

    @staticmethod
    def _token_counter_exceeds_available(required: Counter[str], available: Counter[str]) -> bool:
        if not required:
            return False
        for token, need in required.items():
            if int(need) > int(available.get(token, 0)):
                return True
        return False

    @staticmethod
    def _consume_packet_unit_energy(*, matched_units: list[dict], energy_key: str, amount: float) -> float:
        """从命中的刺激单元上消费指定侧能量，返回实际消费量。"""
        target_amount = max(0.0, float(amount))
        if target_amount <= 0.0:
            return 0.0

        remaining = target_amount
        for unit in matched_units:
            if remaining <= 0.0:
                break
            energy = unit.get("energy_ref", {})
            available = max(0.0, float(energy.get(energy_key, 0.0)))
            if available <= 0.0:
                continue
            consumed = min(available, remaining)
            energy[energy_key] = round(available - consumed, 8)
            remaining = round(remaining - consumed, 8)

        return round(target_amount - remaining, 8)

    def _prune_stimulus_packet_after_consumption(self, stimulus_packet: dict) -> dict:
        """清理被消费到零的刺激对象，并重建分组与能量摘要。"""
        pruned_packet = stimulus_packet

        kept_sa_items = [
            item
            for item in pruned_packet.get("sa_items", [])
            if max(0.0, float(item.get("energy", {}).get("er", 0.0)))
            + max(0.0, float(item.get("energy", {}).get("ev", 0.0)))
            > 0.0
        ]
        kept_sa_ids = {item.get("id", "") for item in kept_sa_items if item.get("id")}
        kept_sa_index = {
            item.get("id", ""): item
            for item in kept_sa_items
            if isinstance(item, dict) and item.get("id")
        }

        kept_csa_items = []
        kept_csa_ids: set[str] = set()
        for original_csa in pruned_packet.get("csa_items", []):
            if not isinstance(original_csa, dict):
                continue
            csa_id = str(original_csa.get("id", ""))
            anchor_id = str(original_csa.get("anchor_sa_id", ""))
            if not csa_id or anchor_id not in kept_sa_ids:
                continue

            member_sa_ids = []
            seen_member_ids: set[str] = set()
            for member_id in original_csa.get("member_sa_ids", []):
                member_text = str(member_id)
                if not member_text or member_text in seen_member_ids or member_text not in kept_sa_ids:
                    continue
                seen_member_ids.add(member_text)
                member_sa_ids.append(member_text)

            # CSA 只是 SA 的分组关系，只有锚点仍在且至少保留 2 个成员时才继续保留。
            if anchor_id not in member_sa_ids or len(member_sa_ids) < 2:
                continue

            display_total_er = round(
                sum(float(kept_sa_index.get(member_id, {}).get("energy", {}).get("er", 0.0)) for member_id in member_sa_ids),
                8,
            )
            display_total_ev = round(
                sum(float(kept_sa_index.get(member_id, {}).get("energy", {}).get("ev", 0.0)) for member_id in member_sa_ids),
                8,
            )
            rebuilt_csa = dict(original_csa)
            rebuilt_csa["anchor_sa_id"] = anchor_id
            rebuilt_csa["member_sa_ids"] = member_sa_ids
            ownership_map = [
                {
                    "sa_id": member_id,
                    "er": round(float(kept_sa_index.get(member_id, {}).get("energy", {}).get("er", 0.0)), 8),
                    "ev": round(float(kept_sa_index.get(member_id, {}).get("energy", {}).get("ev", 0.0)), 8),
                }
                for member_id in member_sa_ids
            ]
            cp_delta = round(display_total_er - display_total_ev, 8)
            cp_abs = round(abs(cp_delta), 8)
            rebuilt_csa["energy_ownership_map"] = ownership_map
            rebuilt_csa["energy"] = {
                "er": display_total_er,
                "ev": display_total_ev,
                "ownership_level": "aggregated_from_sa",
                "computed_from_children": True,
                "fatigue": float(rebuilt_csa.get("energy", {}).get("fatigue", 0.0) or 0.0),
                "recency_gain": float(rebuilt_csa.get("energy", {}).get("recency_gain", 1.0) or 1.0),
                "salience_score": round(max(display_total_er, display_total_ev), 8),
                "cognitive_pressure_delta": cp_delta,
                "cognitive_pressure_abs": cp_abs,
                "last_decay_tick": int(rebuilt_csa.get("energy", {}).get("last_decay_tick", 0) or 0),
                "last_decay_at": int(time.time() * 1000),
            }
            rebuilt_csa["bundle_summary"] = {
                "member_count": len(member_sa_ids),
                "display_total_er": display_total_er,
                "display_total_ev": display_total_ev,
            }
            kept_csa_items.append(rebuilt_csa)
            kept_csa_ids.add(csa_id)

        rebuilt_groups = []
        for group in pruned_packet.get("grouped_sa_sequences", []):
            group_sa_ids = [sa_id for sa_id in group.get("sa_ids", []) if sa_id in kept_sa_ids]
            group_csa_ids = [csa_id for csa_id in group.get("csa_ids", []) if csa_id in kept_csa_ids]

            if not group_sa_ids and not group_csa_ids:
                continue

            rebuilt_group = dict(group)
            rebuilt_group["group_index"] = len(rebuilt_groups)
            rebuilt_group["sa_ids"] = group_sa_ids
            rebuilt_group["csa_ids"] = group_csa_ids
            rebuilt_groups.append(rebuilt_group)

        total_er = round(
            sum(float(item.get("energy", {}).get("er", 0.0)) for item in kept_sa_items),
            8,
        )
        total_ev = round(
            sum(float(item.get("energy", {}).get("ev", 0.0)) for item in kept_sa_items),
            8,
        )
        echo_total_er = round(
            sum(
                float(item.get("energy", {}).get("er", 0.0))
                for item in kept_sa_items
                if item.get("ext", {}).get("packet_context", {}).get("source_type", "") == "echo"
            ),
            8,
        )
        echo_total_ev = round(
            sum(
                float(item.get("energy", {}).get("ev", 0.0))
                for item in kept_sa_items
                if item.get("ext", {}).get("packet_context", {}).get("source_type", "") == "echo"
            ),
            8,
        )

        pruned_packet["sa_items"] = kept_sa_items
        pruned_packet["csa_items"] = kept_csa_items
        pruned_packet["grouped_sa_sequences"] = rebuilt_groups
        energy_summary = pruned_packet.setdefault("energy_summary", {})
        energy_summary["total_er"] = total_er
        energy_summary["total_ev"] = total_ev
        energy_summary["current_total_er"] = total_er
        energy_summary["current_total_ev"] = total_ev
        energy_summary["echo_total_er"] = echo_total_er
        energy_summary["echo_total_ev"] = echo_total_ev
        energy_summary["combined_context_er"] = total_er
        energy_summary["combined_context_ev"] = total_ev
        pruned_packet["updated_at"] = int(time.time() * 1000)
        return pruned_packet

    def _find_existing_item_for_candidate(self, candidate_item: dict | None) -> dict | None:
        """
        根据候选 state_item 查找是否存在“语义同一对象”。

        当前策略：
        1. 仍然优先使用 ref_id 精确命中；
        2. 对 ST 运行态对象，允许用“对象自己的根结构 id”合并不同分辨率视图；
        3. ref_id 未命中时，再用 semantic_signature 做稳定合并；
        4. 这是“同一对象跨轮次重新进入状态池”的主入口，而不是模糊近义词匹配。
        """
        if not candidate_item:
            return None

        if bool(self._config.get("runtime_structure_root_identity_merge_enabled", True)):
            root_structure_id = self._runtime_root_structure_id(candidate_item)
            if root_structure_id:
                existing = self._store.get_by_root_structure_id(root_structure_id)
                if existing is not None:
                    return existing

        if not self._config.get("enable_semantic_same_object_merge", True):
            return None

        if self._config.get("enable_semantic_context_same_object_merge", True):
            semantic_context_key = (
                str(candidate_item.get("semantic_context_key", "") or "")
                or semantic_context_key_from_item(candidate_item)
            )
            if semantic_context_key:
                existing = self._store.get_by_semantic_context_key(semantic_context_key)
                if existing is not None:
                    return existing

        semantic_signature = candidate_item.get("semantic_signature", "")
        if not semantic_signature:
            return None

        if self._config.get("allow_global_semantic_fallback_merge", False):
            return self._store.get_by_semantic_signature(semantic_signature)
        return None

    def _runtime_root_structure_id(self, item: dict | None) -> str:
        """Return StatePool runtime-root identity without using growth provenance as identity."""
        if not isinstance(item, dict):
            return ""
        if str(item.get("ref_object_type", "") or "").strip() != "st":
            return ""

        def _scan(container: dict | None) -> str:
            if not isinstance(container, dict):
                return ""
            runtime_resolution = container.get("runtime_resolution", {})
            if isinstance(runtime_resolution, dict):
                value = str(runtime_resolution.get("root_structure_id", "") or "").strip()
                if value:
                    return value
            value = str(container.get("runtime_root_structure_id", "") or "").strip()
            if value:
                return value
            value = str(container.get("root_structure_id", "") or "").strip()
            return value

        meta_ext = item.get("meta", {}).get("ext", {}) if isinstance(item.get("meta", {}).get("ext", {}), dict) else {}
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        structure_ext = ref_snapshot.get("structure_ext", {}) if isinstance(ref_snapshot.get("structure_ext", {}), dict) else {}
        for container in (
            item.get("ext", {}) if isinstance(item.get("ext", {}), dict) else {},
            meta_ext,
            structure_ext,
            item,
        ):
            root_id = _scan(container)
            if root_id:
                return root_id

        # A formal ST item is already its own complete HDB identity. Do not fall
        # back to growth_projection.root_source_structure_id; that field is only
        # activation provenance and would merge sibling predictions A+B1/A+B2.
        return str(item.get("ref_object_id", "") or "").strip()

    def _ensure_runtime_resolution_identity(self, item: dict | None, *, source: str = "") -> str:
        if not isinstance(item, dict):
            return ""
        if str(item.get("ref_object_type", "") or "").strip() != "st":
            return ""
        root_structure_id = self._runtime_root_structure_id(item)
        if not root_structure_id:
            return ""

        ext = item.setdefault("ext", {})
        if not isinstance(ext, dict):
            ext = {}
            item["ext"] = ext
        ext["runtime_root_structure_id"] = root_structure_id

        meta = item.setdefault("meta", {})
        if not isinstance(meta, dict):
            meta = {}
            item["meta"] = meta
        meta_ext = meta.setdefault("ext", {})
        if not isinstance(meta_ext, dict):
            meta_ext = {}
            meta["ext"] = meta_ext
        runtime_resolution = meta_ext.setdefault("runtime_resolution", {})
        if not isinstance(runtime_resolution, dict):
            runtime_resolution = {}
            meta_ext["runtime_resolution"] = runtime_resolution
        runtime_resolution.setdefault("root_structure_id", root_structure_id)
        runtime_resolution["identity_rule"] = "own_complete_structure"
        runtime_resolution["identity_participates_in_hdb_lookup"] = False
        if source:
            runtime_resolution.setdefault("last_identity_source", source)
        return root_structure_id

    @staticmethod
    def _merge_component_energy_payload(existing_payload: dict, incoming_payload: dict) -> dict:
        """Merge growth component-energy audits by summing numeric leaf fields."""
        if not isinstance(existing_payload, dict) or not existing_payload:
            return copy.deepcopy(incoming_payload) if isinstance(incoming_payload, dict) else {}
        if not isinstance(incoming_payload, dict) or not incoming_payload:
            return copy.deepcopy(existing_payload)

        def _merge(a: Any, b: Any) -> Any:
            if isinstance(a, dict) and isinstance(b, dict):
                result = copy.deepcopy(a)
                for key, value in b.items():
                    if key in result:
                        if str(key).endswith("_component_er_share") or str(key).endswith("_component_ev_share"):
                            result[key] = _merge(result[key], value)
                        elif key in {"source_available_er", "source_available_ev"}:
                            try:
                                result[key] = round(max(float(result.get(key, 0.0) or 0.0), float(value or 0.0)), 8)
                            except Exception:
                                result[key] = result.get(key)
                        else:
                            result[key] = result.get(key) if result.get(key) not in ("", None, [], {}) else copy.deepcopy(value)
                    else:
                        result[key] = copy.deepcopy(value)
                return result
            if isinstance(a, bool) or isinstance(b, bool):
                return bool(a) or bool(b)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return round(float(a) + float(b), 8)
            if a in ("", None, [], {}):
                return copy.deepcopy(b)
            if isinstance(a, list) and isinstance(b, list):
                result = list(a)
                for value in b:
                    if value not in result:
                        result.append(copy.deepcopy(value))
                return result
            return copy.deepcopy(a)

        merged = _merge(existing_payload, incoming_payload)
        if isinstance(merged, dict):
            merged["runtime_merge_count"] = int(existing_payload.get("runtime_merge_count", 1) or 1) + 1
        return merged if isinstance(merged, dict) else {}

    @staticmethod
    def _runtime_meta_value(item: dict | None, key: str) -> Any:
        if not isinstance(item, dict):
            return None
        meta_ext = item.get("meta", {}).get("ext", {}) if isinstance(item.get("meta", {}).get("ext", {}), dict) else {}
        if key in meta_ext:
            return meta_ext.get(key)
        item_ext = item.get("ext", {}) if isinstance(item.get("ext", {}), dict) else {}
        return item_ext.get(key)

    def _merge_runtime_projection_metadata(self, existing_item: dict, incoming_item: dict | None) -> None:
        if not isinstance(existing_item, dict) or not isinstance(incoming_item, dict):
            return
        existing_meta = existing_item.setdefault("meta", {})
        if not isinstance(existing_meta, dict):
            existing_meta = {}
            existing_item["meta"] = existing_meta
        existing_meta_ext = existing_meta.setdefault("ext", {})
        if not isinstance(existing_meta_ext, dict):
            existing_meta_ext = {}
            existing_meta["ext"] = existing_meta_ext

        incoming_gp = self._runtime_meta_value(incoming_item, "growth_projection")
        if isinstance(incoming_gp, dict) and incoming_gp:
            existing_gp = existing_meta_ext.get("growth_projection", {})
            if not isinstance(existing_gp, dict) or not existing_gp:
                existing_meta_ext["growth_projection"] = copy.deepcopy(incoming_gp)
            else:
                merged_gp = copy.deepcopy(existing_gp)
                source_ids = []
                for raw in list(merged_gp.get("source_structure_ids", []) or []):
                    sid = str(raw or "").strip()
                    if sid and sid not in source_ids:
                        source_ids.append(sid)
                for raw in (
                    merged_gp.get("source_structure_id", ""),
                    incoming_gp.get("source_structure_id", ""),
                    *list(incoming_gp.get("source_structure_ids", []) or []),
                ):
                    sid = str(raw or "").strip()
                    if sid and sid not in source_ids:
                        source_ids.append(sid)
                for key, value in incoming_gp.items():
                    if key in {"source_structure_id", "source_structure_ids"}:
                        continue
                    if key not in merged_gp or merged_gp.get(key) in ("", None, [], {}):
                        merged_gp[key] = copy.deepcopy(value)
                if source_ids:
                    merged_gp["source_structure_ids"] = source_ids
                merged_gp["merged_candidate_count"] = int(merged_gp.get("merged_candidate_count", 1) or 1) + 1
                existing_meta_ext["growth_projection"] = merged_gp

        incoming_component = self._runtime_meta_value(incoming_item, "component_energy")
        if isinstance(incoming_component, dict) and incoming_component:
            existing_component = existing_meta_ext.get("component_energy", {})
            existing_meta_ext["component_energy"] = self._merge_component_energy_payload(
                existing_component if isinstance(existing_component, dict) else {},
                incoming_component,
            )

        root_structure_id = self._ensure_runtime_resolution_identity(existing_item, source="runtime_projection_metadata_merge")
        if root_structure_id:
            try:
                self._store.bind_root_structure_id(existing_item["id"], root_structure_id)
            except Exception:
                pass
        self._refresh_runtime_resolution_metadata(existing_item, source="runtime_projection_metadata_merge")

    @staticmethod
    def _component_energy_total(component_energy: dict, key: str) -> float:
        if not isinstance(component_energy, dict):
            return 0.0
        total = 0.0
        suffix = f"_{key}_share"
        for field, value in component_energy.items():
            if isinstance(value, dict):
                total += StatePool._component_energy_total(value, key)
                continue
            if str(field).endswith(suffix) or str(field) == key:
                try:
                    total += float(value or 0.0)
                except Exception:
                    pass
        return round(total, 8)

    @staticmethod
    def _component_energy_count(component_energy: dict, *, floor: float) -> tuple[int, int]:
        if not isinstance(component_energy, dict):
            return 0, 0
        active = 0
        dropped = 0
        for field, value in component_energy.items():
            if isinstance(value, dict):
                sub_active, sub_dropped = StatePool._component_energy_count(value, floor=floor)
                active += sub_active
                dropped += sub_dropped
                continue
            if (
                str(field).endswith("_component_er_share")
                or str(field).endswith("_component_ev_share")
                or str(field) in {"er", "ev"}
            ):
                try:
                    if float(value or 0.0) >= floor:
                        active += 1
                    else:
                        dropped += 1
                except Exception:
                    pass
        return int(active), int(dropped)

    def _refresh_runtime_resolution_metadata(self, item: dict | None, *, source: str = "") -> bool:
        if not bool(self._config.get("runtime_structure_resolution_degradation_enabled", True)):
            return False
        if not isinstance(item, dict) or str(item.get("ref_object_type", "") or "").strip() != "st":
            return False

        root_structure_id = self._ensure_runtime_resolution_identity(item, source=source)
        meta_ext = item.setdefault("meta", {}).setdefault("ext", {})
        if not isinstance(meta_ext, dict):
            meta_ext = {}
            item.setdefault("meta", {})["ext"] = meta_ext
        runtime_resolution = meta_ext.setdefault("runtime_resolution", {})
        if not isinstance(runtime_resolution, dict):
            runtime_resolution = {}
            meta_ext["runtime_resolution"] = runtime_resolution

        component_energy = meta_ext.get("component_energy", {})
        if not isinstance(component_energy, dict) or not component_energy:
            item_ext = item.get("ext", {}) if isinstance(item.get("ext", {}), dict) else {}
            component_energy = item_ext.get("component_energy", {}) if isinstance(item_ext.get("component_energy", {}), dict) else {}
        total_er = self._component_energy_total(component_energy, "er")
        total_ev = self._component_energy_total(component_energy, "ev")
        total_component_energy = round(total_er + total_ev, 8)

        try:
            floor = float(self._config.get("runtime_structure_resolution_component_energy_floor", 0.05) or 0.05)
        except Exception:
            floor = 0.05
        floor = max(0.0, floor)
        active_component_count, dropped_component_count = self._component_energy_count(
            component_energy,
            floor=floor,
        )

        if active_component_count == 0 and total_component_energy > 0.0:
            active_component_count = 1
        original_count = active_component_count + dropped_component_count
        resolution_ratio = 1.0
        if original_count > 0:
            resolution_ratio = max(0.0, min(1.0, float(active_component_count) / float(original_count)))

        runtime_resolution.update(
            {
                "enabled": True,
                "root_structure_id": root_structure_id,
                "degradation_semantics": "state_pool_resolution_drop_only",
                "hdb_identity_re_resolved": False,
                "hdb_write_on_degrade": False,
                "component_energy_floor": round(floor, 8),
                "component_total_er": total_er,
                "component_total_ev": total_ev,
                "active_component_count": int(active_component_count),
                "dropped_component_count": int(dropped_component_count),
                "resolution_ratio": round(resolution_ratio, 8),
                "is_degraded": bool(dropped_component_count > 0),
            }
        )
        if source:
            runtime_resolution["last_refresh_source"] = source
        return True

    def _apply_induction_ref_hit_objects_fast(
        self,
        *,
        valid_objects: list[dict],
        attr_energy_by_anchor: dict[str, dict[str, float | int]],
        store_attr: bool,
        tick_number: int,
        trace_id: str,
        tick_id: str,
        source_module: str,
        enable_change_event_log: bool,
        emit_events: bool = True,
    ) -> tuple[list[dict], list[dict], list[str], int, int]:
        """
        Fast path for HDB induction packets that already hit existing StatePool refs.

        Induction projection packets are large and mostly revisit the same stable
        SA carriers across ticks. For an exact ref hit, the full candidate
        construction path only rebuilds static snapshots/signatures that are
        already owned by the existing item. We can safely apply the ER/EV delta
        directly, while leaving misses on the normal path so new objects still
        get full StatePool materialization.
        """
        if not valid_objects:
            return [], [], [], 0, 0

        remaining_objects: list[dict] = []
        grouped_hits: dict[str, dict[str, Any]] = {}

        for obj in valid_objects:
            if not isinstance(obj, dict):
                remaining_objects.append(obj)
                continue
            ref_id = str(obj.get("id", "") or "")
            if not ref_id:
                remaining_objects.append(obj)
                continue
            existing = self._store.get_by_ref(ref_id)
            if existing is None:
                remaining_objects.append(obj)
                continue

            energy = obj.get("energy", {}) if isinstance(obj.get("energy", {}), dict) else {}
            incoming_er = self._safe_float(energy.get("er", 0.0))
            incoming_ev = self._safe_float(energy.get("ev", 0.0))

            if (
                not store_attr
                and str(obj.get("object_type", "")) == "sa"
                and str(obj.get("stimulus", {}).get("role", "") or "") != "attribute"
            ):
                folded = attr_energy_by_anchor.get(ref_id) or {}
                incoming_er += self._safe_float(folded.get("er", 0.0))
                incoming_ev += self._safe_float(folded.get("ev", 0.0))

            packet_context = {}
            ext = obj.get("ext", {}) if isinstance(obj.get("ext", {}), dict) else {}
            if isinstance(ext.get("packet_context", {}), dict):
                packet_context = ext.get("packet_context", {}) or {}
            source_type = str(packet_context.get("source_type", "") or "")

            group = grouped_hits.setdefault(
                ref_id,
                {
                    "existing": existing,
                    "total_er": 0.0,
                    "total_ev": 0.0,
                    "incoming_member_count": 0,
                    "source_types": set(),
                },
            )
            group["total_er"] += incoming_er
            group["total_ev"] += incoming_ev
            group["incoming_member_count"] += 1
            if source_type:
                group["source_types"].add(source_type)

        events: list[dict] = []
        applied_ids: list[str] = []
        updated_count = 0
        merged_count = 0
        for ref_id, group in grouped_hits.items():
            existing = group.get("existing")
            if not isinstance(existing, dict):
                continue
            total_er = round(float(group.get("total_er", 0.0) or 0.0), 8)
            total_ev = round(float(group.get("total_ev", 0.0) or 0.0), 8)
            event = self._energy.apply_energy_delta(
                item=existing,
                delta_er=total_er,
                delta_ev=total_ev,
                tick_number=tick_number,
                reason="stimulus_apply_ref_hit",
                source_module=source_module or "hdb_induction",
                trace_id=trace_id,
                tick_id=tick_id,
                emit_event=emit_events,
            )
            member_count = int(group.get("incoming_member_count", 0) or 0)
            if event:
                event["merge_mode"] = "ref"
                event["merge_source_ref_id"] = ref_id
                event["incoming_member_count"] = member_count
                event["packet_source_types"] = sorted(group.get("source_types", set()) or [])
                events.append(event)
            applied_ids.append(str(existing.get("id", "") or ""))
            updated_count += 1
            merged_count += max(0, member_count - 1)
            if enable_change_event_log and event:
                self._log_change_event(event, trace_id, tick_id)

        return remaining_objects, events, applied_ids, updated_count, merged_count

    def _apply_induction_new_sa_objects_fast(
        self,
        *,
        valid_objects: list[dict],
        attr_energy_by_anchor: dict[str, dict[str, float | int]],
        store_attr: bool,
        tick_number: int,
        trace_id: str,
        tick_id: str,
        source_module: str,
        origin_id: str,
        enable_change_event_log: bool,
        emit_events: bool = True,
    ) -> tuple[list[dict], list[dict], list[str], int, int, int]:
        if not valid_objects:
            return [], [], [], 0, 0, 0

        remaining_objects: list[dict] = []
        grouped_new: dict[str, dict[str, Any]] = {}
        for obj in valid_objects:
            if not isinstance(obj, dict) or str(obj.get("object_type", "")) != "sa":
                remaining_objects.append(obj)
                continue
            ref_id = str(obj.get("id", "") or "")
            if not ref_id:
                remaining_objects.append(obj)
                continue
            if self._store.get_by_ref(ref_id) is not None:
                remaining_objects.append(obj)
                continue

            energy = obj.get("energy", {}) if isinstance(obj.get("energy", {}), dict) else {}
            incoming_er = self._safe_float(energy.get("er", 0.0))
            incoming_ev = self._safe_float(energy.get("ev", 0.0))
            folded_count = 0
            folded_er = 0.0
            folded_ev = 0.0
            if str(obj.get("stimulus", {}).get("role", "") or "") != "attribute" and not store_attr:
                folded = attr_energy_by_anchor.get(ref_id) or {}
                folded_er = self._safe_float(folded.get("er", 0.0))
                folded_ev = self._safe_float(folded.get("ev", 0.0))
                folded_count = int(folded.get("count", 0) or 0)
                incoming_er += folded_er
                incoming_ev += folded_ev

            ext = obj.get("ext", {}) if isinstance(obj.get("ext", {}), dict) else {}
            packet_context = ext.get("packet_context", {}) if isinstance(ext.get("packet_context", {}), dict) else {}
            source_type = str(packet_context.get("source_type", "") or "")
            group = grouped_new.setdefault(
                ref_id,
                {
                    "ref_object": obj,
                    "total_er": 0.0,
                    "total_ev": 0.0,
                    "incoming_member_count": 0,
                    "source_types": set(),
                    "folded_attribute_sa_count": 0,
                    "folded_attribute_total_er": 0.0,
                    "folded_attribute_total_ev": 0.0,
                },
            )
            group["total_er"] += incoming_er
            group["total_ev"] += incoming_ev
            group["incoming_member_count"] += 1
            group["folded_attribute_sa_count"] += folded_count
            group["folded_attribute_total_er"] += folded_er
            group["folded_attribute_total_ev"] += folded_ev
            if source_type:
                group["source_types"].add(source_type)

        events: list[dict] = []
        applied_ids: list[str] = []
        new_count = 0
        merged_count = 0
        rejected_count = 0
        now_ms = int(time.time() * 1000)
        recency_peak = self._energy._recency_peak()
        recency_hold_ticks = self._energy._recency_hold_ticks()
        initial_fatigue = self._energy._fatigue_from_count(1)
        for ref_id, group in grouped_new.items():
            ref_object = group.get("ref_object", {})
            if not isinstance(ref_object, dict):
                rejected_count += 1
                continue
            er = round(float(group.get("total_er", 0.0) or 0.0), 8)
            ev = round(float(group.get("total_ev", 0.0) or 0.0), 8)
            if er == 0 and ev == 0 and not self._config.get("insert_zero_energy_object", True):
                rejected_count += 1
                continue
            item = self._build_induction_sa_state_item_fast(
                ref_object=ref_object,
                er=er,
                ev=ev,
                trace_id=trace_id,
                tick_id=tick_id,
                tick_number=tick_number,
                source_module=source_module or "hdb_induction",
                origin_id=str(origin_id or ""),
                now_ms=now_ms,
            )
            if int(group.get("folded_attribute_sa_count", 0) or 0):
                ext = item.setdefault("ext", {})
                ext["incoming_packet_folded_attribute_sa_count"] = int(group.get("folded_attribute_sa_count", 0) or 0)
                ext["incoming_packet_folded_attribute_total_er"] = round(float(group.get("folded_attribute_total_er", 0.0) or 0.0), 8)
                ext["incoming_packet_folded_attribute_total_ev"] = round(float(group.get("folded_attribute_total_ev", 0.0) or 0.0), 8)
            energy = item.setdefault("energy", {})
            lifecycle = item.setdefault("lifecycle", {})
            lifecycle["recent_activation_ticks"] = [int(tick_number)]
            lifecycle["last_active_tick"] = int(tick_number)
            lifecycle["last_recency_refresh_tick"] = int(tick_number)
            lifecycle["recency_hold_ticks_remaining"] = int(recency_hold_ticks)
            energy["recency_gain"] = float(recency_peak)
            energy["fatigue"] = float(initial_fatigue)
            energy.setdefault("last_decay_tick", 0)
            energy.setdefault("last_decay_at", now_ms)
            item["updated_at"] = now_ms
            inserted = self._store.insert(item)
            if not inserted:
                rejected_count += 1
                continue
            self._total_items_created += 1
            applied_ids.append(item["id"])
            new_count += 1
            member_count = int(group.get("incoming_member_count", 0) or 0)
            merged_count += max(0, member_count - 1)
            cp_delta = item["energy"]["cognitive_pressure_delta"]
            cp_abs = item["energy"]["cognitive_pressure_abs"]
            if emit_events:
                event = {
                    "event_id": f"new_{item['id']}",
                    "event_type": "created",
                    "target_item_id": item["id"],
                    "trace_id": trace_id,
                    "tick_id": tick_id,
                    "timestamp_ms": now_ms,
                    "before": {"er": 0.0, "ev": 0.0, "cp_delta": 0.0, "cp_abs": 0.0},
                    "after": {"er": er, "ev": ev, "cp_delta": cp_delta, "cp_abs": cp_abs},
                    "delta": {"delta_er": er, "delta_ev": ev, "delta_cp_delta": cp_delta, "delta_cp_abs": cp_abs},
                    "rate": {"er_change_rate": er, "ev_change_rate": ev, "cp_delta_rate": cp_delta, "cp_abs_rate": cp_abs},
                    "reason": "stimulus_apply_new_item",
                    "source_module": source_module or "hdb_induction",
                    "semantic_signature": item.get("semantic_signature", ""),
                    "incoming_member_count": member_count,
                    "packet_source_types": sorted(group.get("source_types", set()) or []),
                }
                events.append(event)
                if enable_change_event_log:
                    self._log_change_event(event, trace_id, tick_id)

        return remaining_objects, events, applied_ids, new_count, merged_count, rejected_count

    @classmethod
    def _build_induction_sa_state_item_fast(
        cls,
        *,
        ref_object: dict,
        er: float,
        ev: float,
        trace_id: str,
        tick_id: str,
        tick_number: int,
        source_module: str,
        origin_id: str,
        now_ms: int,
    ) -> dict:
        ref_id = str(ref_object.get("id", "") or "")
        content = ref_object.get("content", {}) if isinstance(ref_object.get("content", {}), dict) else {}
        stimulus = ref_object.get("stimulus", {}) if isinstance(ref_object.get("stimulus", {}), dict) else {}
        ref_source = ref_object.get("source", {}) if isinstance(ref_object.get("source", {}), dict) else {}
        ext = ref_object.get("ext", {}) if isinstance(ref_object.get("ext", {}), dict) else {}
        parent_ids = [str(value) for value in list(ref_source.get("parent_ids", []) or ([ref_id] if ref_id else [])) if str(value)]
        context_path_ids = [str(value) for value in list(ext.get("context_path_ids", []) or parent_ids) if str(value)]
        context_ref_object_id = str(ext.get("context_ref_object_id", "") or "")
        context_ref_object_type = str(ext.get("context_ref_object_type", "") or "")
        context_owner_structure_id = str(ext.get("context_owner_structure_id", "") or "")
        residual_origin_kind = str(ext.get("residual_origin_kind", "") or "")
        residual_origin_entry_id = str(ext.get("residual_origin_entry_id", "") or "")
        source_em_id = str(ext.get("source_em_id", "") or "")
        display = str(content.get("display") or content.get("normalized") or content.get("raw") or ref_id)
        role = str(stimulus.get("role", "") or "")
        value_type = str(content.get("value_type", "") or "")
        attribute_name = str(content.get("attribute_name", "") or "")
        attribute_value = content.get("attribute_value")
        cp_delta = round(float(er) - float(ev), 8)
        cp_abs = round(abs(cp_delta), 8)
        semantic_signature = "|".join(
            [
                "sa",
                context_ref_object_id,
                context_owner_structure_id,
                role,
                attribute_name,
                str(attribute_value if attribute_value is not None else ""),
                str(content.get("normalized") or content.get("raw") or display),
            ]
        )
        ref_snapshot: dict[str, Any] = {
            "source_module": source_module,
            "context_ref_object_id": context_ref_object_id,
            "context_ref_object_type": context_ref_object_type,
            "context_owner_id": context_owner_structure_id,
            "context_path_ids": context_path_ids,
            "context_text": "",
            "residual_kind": residual_origin_kind,
            "source_em_id": source_em_id,
            "memory_id": source_em_id,
            "source_memory_created_at": 0,
            "content_display": display,
            "content_display_detail": str(content.get("normalized") or display),
            "content_signature": semantic_signature,
            "role": role,
            "value_type": value_type,
        }
        if attribute_name:
            ref_snapshot["attribute_name"] = attribute_name
            ref_snapshot["attribute_value"] = attribute_value
        return {
            "id": next_id("spi"),
            "object_type": "state_item",
            "sub_type": "sa_runtime_item",
            "schema_version": __schema_version__,
            "ref_object_type": "sa",
            "ref_object_id": ref_id,
            "ref_alias_ids": [ref_id] if ref_id else [],
            "ref_snapshot": ref_snapshot,
            "semantic_signature": semantic_signature,
            "energy": {
                "er": round(float(er), 8),
                "ev": round(float(ev), 8),
                "ownership_level": str((ref_object.get("energy", {}) or {}).get("ownership_level") or "runtime_projection"),
                "computed_from_children": bool((ref_object.get("energy", {}) or {}).get("computed_from_children", False)),
                "fatigue": 0.0,
                "recency_gain": 1.0,
                "salience_score": round(max(float(er), float(ev)), 8),
                "cognitive_pressure_delta": cp_delta,
                "cognitive_pressure_abs": cp_abs,
                "last_decay_tick": 0,
                "last_decay_at": now_ms,
            },
            "dynamics": {
                "prev_er": 0.0,
                "prev_ev": 0.0,
                "delta_er": round(float(er), 8),
                "delta_ev": round(float(ev), 8),
                "er_change_rate": round(float(er), 6),
                "ev_change_rate": round(float(ev), 6),
                "prev_cp_delta": 0.0,
                "prev_cp_abs": 0.0,
                "delta_cp_delta": cp_delta,
                "delta_cp_abs": cp_abs,
                "cp_delta_rate": cp_delta,
                "cp_abs_rate": cp_abs,
                "last_update_tick": tick_number,
                "last_update_at": now_ms,
                "update_count": 1,
            },
            "binding_state": {
                "bound_csa_item_id": None,
                "bound_attribute_sa_ids": [],
            },
            "lifecycle": {
                "created_in_tick": tick_number,
                "last_active_tick": tick_number,
                "elimination_candidate": False,
            },
            "source": {
                "module": source_module or __module_name__,
                "interface": "apply_stimulus_packet",
                "origin": "from_stimulus_packet",
                "origin_id": origin_id,
                "parent_ids": parent_ids,
                "context_ref_object_id": context_ref_object_id,
                "context_ref_object_type": context_ref_object_type,
                "context_owner_structure_id": context_owner_structure_id,
                "context_path_ids": context_path_ids,
            },
            "trace_id": trace_id,
            "tick_id": tick_id,
            "created_at": now_ms,
            "updated_at": now_ms,
            "status": "active",
            "ext": {"semantic_labels": {}},
            "meta": {
                "confidence": 1.0,
                "field_registry_version": __schema_version__,
                "debug": {},
                "ext": {
                    "context_ref_object_id": context_ref_object_id,
                    "context_ref_object_type": context_ref_object_type,
                    "context_owner_structure_id": context_owner_structure_id,
                    "context_path_ids": context_path_ids,
                    "parent_ids": parent_ids,
                    "residual_origin_kind": residual_origin_kind,
                    "residual_origin_entry_id": residual_origin_entry_id,
                },
            },
        }

    @staticmethod
    def _state_item_template_cache_key(ref_object: dict) -> tuple | None:
        if not isinstance(ref_object, dict):
            return None
        obj_type = str(ref_object.get("object_type", "") or "")
        obj_id = str(ref_object.get("id", "") or "")
        if not obj_type or not obj_id:
            return None
        content = ref_object.get("content", {}) if isinstance(ref_object.get("content", {}), dict) else {}
        stimulus = ref_object.get("stimulus", {}) if isinstance(ref_object.get("stimulus", {}), dict) else {}
        source = ref_object.get("source", {}) if isinstance(ref_object.get("source", {}), dict) else {}
        ext = ref_object.get("ext", {}) if isinstance(ref_object.get("ext", {}), dict) else {}
        packet_context = ext.get("packet_context", {}) if isinstance(ext.get("packet_context", {}), dict) else {}
        role = str(stimulus.get("role", "") or "")
        cache_identity_id = obj_id if role == "attribute" else ""
        return (
            obj_type,
            cache_identity_id,
            str(content.get("raw", "") or ""),
            str(content.get("display", "") or ""),
            str(content.get("normalized", "") or ""),
            str(content.get("value_type", "") or ""),
            str(content.get("attribute_name", "") or ""),
            repr(content.get("attribute_value", None)),
            role,
            str(stimulus.get("modality", "") or ""),
            bool(stimulus.get("order_sensitive", packet_context.get("order_sensitive", False))),
            str(stimulus.get("string_unit_kind", packet_context.get("string_unit_kind", "")) or ""),
            str(stimulus.get("string_token_text", packet_context.get("string_token_text", "")) or ""),
            str(packet_context.get("source_type", "") or ""),
            str(packet_context.get("origin_frame_id", "") or ""),
            int(packet_context.get("source_group_index", packet_context.get("group_index", -1)) or -1),
            str(ext.get("context_ref_object_id", "") or ""),
            str(ext.get("context_ref_object_type", "") or ""),
            str(ext.get("context_owner_structure_id", "") or ""),
            tuple(str(item) for item in (ext.get("context_path_ids", []) or []) if str(item)),
            tuple(str(item) for item in (source.get("parent_ids", []) or []) if str(item)),
            str(ext.get("residual_origin_kind", "") or ""),
            str(ext.get("residual_origin_entry_id", "") or ""),
            str(ext.get("source_em_id", "") or ""),
        )

    def _remember_state_item_template(self, key: tuple, template: dict) -> None:
        if not key or not isinstance(template, dict):
            return
        try:
            max_entries = int(self._config.get("state_item_template_cache_max_entries", 4096) or 0)
        except Exception:
            max_entries = 4096
        if max_entries <= 0:
            return
        cache = self._state_item_template_cache
        if key in cache:
            cache[key] = template
            return
        while len(cache) >= max_entries:
            try:
                cache.pop(next(iter(cache)))
            except StopIteration:
                break
        cache[key] = template

    @staticmethod
    def _copy_state_item_template_for_cache(item: dict) -> dict:
        template = dict(item)
        ref_snapshot = dict(item.get("ref_snapshot", {}) or {})
        for key in ("context_path_ids", "attribute_displays", "feature_displays", "member_summaries", "flat_tokens", "sequence_groups", "member_refs", "structure_refs", "group_refs"):
            if isinstance(ref_snapshot.get(key), list):
                ref_snapshot[key] = list(ref_snapshot.get(key) or [])
        template["ref_snapshot"] = ref_snapshot
        template["energy"] = dict(item.get("energy", {}) or {})
        template["dynamics"] = dict(item.get("dynamics", {}) or {})
        binding_state = dict(item.get("binding_state", {}) or {})
        for key in ("bound_attribute_sa_ids",):
            if isinstance(binding_state.get(key), list):
                binding_state[key] = list(binding_state.get(key) or [])
        if isinstance(binding_state.get("packet_attribute_by_name"), dict):
            binding_state["packet_attribute_by_name"] = {
                str(name): dict(value)
                for name, value in binding_state.get("packet_attribute_by_name", {}).items()
                if isinstance(value, dict)
            }
        template["binding_state"] = binding_state
        template["lifecycle"] = dict(item.get("lifecycle", {}) or {})
        source = dict(item.get("source", {}) or {})
        if isinstance(source.get("parent_ids"), list):
            source["parent_ids"] = list(source.get("parent_ids") or [])
        if isinstance(source.get("context_path_ids"), list):
            source["context_path_ids"] = list(source.get("context_path_ids") or [])
        template["source"] = source
        ext = dict(item.get("ext", {}) or {})
        if isinstance(ext.get("semantic_labels"), dict):
            ext["semantic_labels"] = dict(ext.get("semantic_labels") or {})
        template["ext"] = ext
        meta = dict(item.get("meta", {}) or {})
        if isinstance(meta.get("debug"), dict):
            meta["debug"] = dict(meta.get("debug") or {})
        if isinstance(meta.get("ext"), dict):
            meta["ext"] = dict(meta.get("ext") or {})
        template["meta"] = meta
        return template

    @classmethod
    def _clone_state_item_template_for_ref(
        cls,
        template: dict,
        *,
        ref_object: dict,
        trace_id: str,
        tick_id: str,
        tick_number: int,
        source_module: str,
        source_interface: str,
        origin: str,
        origin_id: str,
    ) -> dict:
        ref_object_id = str(ref_object.get("id", "") or "")
        energy_in = ref_object.get("energy", {}) if isinstance(ref_object.get("energy", {}), dict) else {}
        er = cls._safe_float(energy_in.get("er", 0.0))
        ev = cls._safe_float(energy_in.get("ev", 0.0))
        cp_delta = round(er - ev, 8)
        cp_abs = round(abs(cp_delta), 8)
        now_ms = int(time.time() * 1000)
        item = dict(template)
        item["id"] = next_id("spi")
        item["ref_object_id"] = ref_object_id
        item["ref_alias_ids"] = [ref_object_id] if ref_object_id else []
        ref_snapshot = dict(template.get("ref_snapshot", {}) or {})
        for key in ("context_path_ids", "attribute_displays", "feature_displays", "member_summaries", "flat_tokens", "sequence_groups", "member_refs", "structure_refs", "group_refs"):
            if isinstance(ref_snapshot.get(key), list):
                ref_snapshot[key] = list(ref_snapshot.get(key) or [])
        item["ref_snapshot"] = ref_snapshot
        ownership_level = str(energy_in.get("ownership_level") or template.get("energy", {}).get("ownership_level") or "runtime_projection")
        computed_from_children = bool(energy_in.get("computed_from_children", template.get("energy", {}).get("computed_from_children", False)))
        item["energy"] = {
            "er": er,
            "ev": ev,
            "ownership_level": ownership_level,
            "computed_from_children": computed_from_children,
            "fatigue": 0.0,
            "recency_gain": 1.0,
            "salience_score": max(er, ev),
            "cognitive_pressure_delta": cp_delta,
            "cognitive_pressure_abs": cp_abs,
            "last_decay_tick": 0,
            "last_decay_at": now_ms,
        }
        item["dynamics"] = {
            "prev_er": 0.0,
            "prev_ev": 0.0,
            "delta_er": er,
            "delta_ev": ev,
            "er_change_rate": er,
            "ev_change_rate": ev,
            "prev_cp_delta": 0.0,
            "prev_cp_abs": 0.0,
            "delta_cp_delta": cp_delta,
            "delta_cp_abs": cp_abs,
            "cp_delta_rate": cp_delta,
            "cp_abs_rate": cp_abs,
            "last_update_tick": tick_number,
            "last_update_at": now_ms,
            "update_count": 1,
        }
        binding_state = dict(template.get("binding_state", {}) or {})
        for key in ("bound_attribute_sa_ids",):
            if isinstance(binding_state.get(key), list):
                binding_state[key] = list(binding_state.get(key) or [])
        if isinstance(binding_state.get("packet_attribute_by_name"), dict):
            binding_state["packet_attribute_by_name"] = {
                str(name): dict(value)
                for name, value in binding_state.get("packet_attribute_by_name", {}).items()
                if isinstance(value, dict)
            }
        item["binding_state"] = binding_state
        item["lifecycle"] = {
            "created_in_tick": tick_number,
            "last_active_tick": tick_number,
            "elimination_candidate": False,
        }
        source = dict(template.get("source", {}) or {})
        ref_source = ref_object.get("source", {}) if isinstance(ref_object.get("source", {}), dict) else {}
        parent_ids = list(ref_source.get("parent_ids", []) or ([ref_object_id] if ref_object_id else []))
        if isinstance(source.get("parent_ids"), list):
            source["parent_ids"] = parent_ids
        if isinstance(source.get("context_path_ids"), list):
            source["context_path_ids"] = list(source.get("context_path_ids") or [])
        source["module"] = source_module or __module_name__
        source["interface"] = source_interface
        source["origin"] = origin
        source["origin_id"] = origin_id
        item["source"] = source
        item["trace_id"] = trace_id
        item["tick_id"] = tick_id
        item["created_at"] = now_ms
        item["updated_at"] = now_ms
        item["status"] = "active"
        ext = dict(template.get("ext", {}) or {})
        if isinstance(ext.get("semantic_labels"), dict):
            ext["semantic_labels"] = dict(ext.get("semantic_labels") or {})
        item["ext"] = ext
        meta = dict(template.get("meta", {}) or {})
        if isinstance(meta.get("debug"), dict):
            meta["debug"] = dict(meta.get("debug") or {})
        if isinstance(meta.get("ext"), dict):
            meta["ext"] = dict(meta.get("ext") or {})
            if parent_ids:
                meta["ext"]["context_path_ids"] = list(source.get("context_path_ids") or parent_ids)
        item["meta"] = meta
        return item

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _select_projection_packet_representative_feature_sa(feature_sa_items: list[dict]) -> dict:
        ordered = sorted(
            [dict(item) for item in feature_sa_items if isinstance(item, dict)],
            key=lambda item: (
                -(float((item.get("energy", {}) or {}).get("er", 0.0) or 0.0)),
                int(
                    ((item.get("ext", {}) or {}).get("packet_context", {}) or {}).get("sequence_index", 0)
                    or 0
                ),
            ),
        )
        return ordered[0] if ordered else {}

    def _upsert_packet_attribute(self, *, anchor_item: dict, attribute_sa: dict, now_ms: int) -> None:
        if not isinstance(anchor_item, dict) or not isinstance(attribute_sa, dict):
            return
        if str(attribute_sa.get("object_type", "")) != "sa":
            return
        if str(attribute_sa.get("stimulus", {}).get("role", "") or "") != "attribute":
            return
        content = attribute_sa.get("content", {}) or {}
        attr_name = str(content.get("attribute_name", "") or "")
        if not attr_name:
            raw = str(content.get("raw", "") or "")
            if ":" in raw:
                attr_name = raw.split(":", 1)[0].strip()
            else:
                attr_name = raw.strip()
        if not attr_name:
            return

        display = str(content.get("display", "") or content.get("raw", "") or attribute_sa.get("id", ""))
        value = content.get("attribute_value")
        sa_id = str(attribute_sa.get("id", "") or "")

        binding_state = anchor_item.setdefault("binding_state", {})
        packet_attrs = binding_state.setdefault("packet_attribute_by_name", {})
        packet_attrs[attr_name] = {
            "attribute_name": attr_name,
            "attribute_value": value,
            "display": display,
            "sa_id": sa_id,
            "updated_at": now_ms,
        }

        ref_snapshot = anchor_item.setdefault("ref_snapshot", {})
        ordered = sorted(
            list(packet_attrs.values()),
            key=lambda row: str(row.get("attribute_name", "")),
        )
        ref_snapshot["attribute_displays"] = [
            str(row.get("display", ""))
            for row in ordered
            if str(row.get("display", ""))
        ]

        detail_parts = []
        if ref_snapshot.get("attribute_displays"):
            detail_parts.append(f"attrs={', '.join(ref_snapshot.get('attribute_displays', [])[:4])}")
        bound = list(ref_snapshot.get("bound_attribute_displays", []) or [])
        if bound:
            detail_parts.append(f"runtime_attrs={', '.join(bound[:4])}")
        if detail_parts:
            ref_snapshot["content_display_detail"] = " | ".join(detail_parts)

    def _sync_packet_attribute_bindings(
        self,
        *,
        target_item: dict,
        attribute_sa_items: list[dict],
        csa_items: list[dict],
        attrs_by_anchor: dict[str, list[dict]],
        object_lookup: dict[str, dict],
        tick_number: int,
    ) -> None:
        now_ms = int(time.time() * 1000)
        for anchor_ref_id, attrs in attrs_by_anchor.items():
            anchor_item = self._store.get_by_ref(anchor_ref_id)
            if anchor_item is None and anchor_ref_id in list(target_item.get("ref_alias_ids", []) or []):
                anchor_item = target_item
            if not anchor_item:
                continue
            for attr in attrs:
                self._upsert_packet_attribute(anchor_item=anchor_item, attribute_sa=attr, now_ms=now_ms)
            anchor_item["updated_at"] = now_ms
            anchor_item.setdefault("lifecycle", {})["last_active_tick"] = tick_number

        for csa in csa_items:
            if not isinstance(csa, dict) or csa.get("object_type") != "csa":
                continue
            anchor_ref_id = str(csa.get("anchor_sa_id", "") or "")
            if not anchor_ref_id:
                continue
            anchor_item = self._store.get_by_ref(anchor_ref_id)
            if anchor_item is None and anchor_ref_id in list(target_item.get("ref_alias_ids", []) or []):
                anchor_item = target_item
            if not anchor_item:
                continue
            for member_id in csa.get("member_sa_ids", []) or []:
                mid = str(member_id or "")
                if not mid or mid == anchor_ref_id:
                    continue
                attr_obj = object_lookup.get(mid)
                if attr_obj:
                    self._upsert_packet_attribute(anchor_item=anchor_item, attribute_sa=attr_obj, now_ms=now_ms)
            anchor_item["updated_at"] = now_ms
            anchor_item.setdefault("lifecycle", {})["last_active_tick"] = tick_number

    def _merge_candidate_into_existing(
        self,
        existing_item: dict,
        candidate_item: dict,
        merge_mode: str,
        tick_number: int,
        reason: str,
        source_module: str,
        trace_id: str,
        tick_id: str,
    ) -> dict:
        """把候选对象并入已有对象，并返回标准变化事件。"""
        merge_info = self._merge.merge_items(existing_item, candidate_item)
        self._refresh_existing_item_from_candidate(existing_item, candidate_item)
        self._merge_runtime_projection_metadata(existing_item, candidate_item)
        self._maybe_reanchor_existing_item_to_memory_terminal(existing_item, candidate_item)
        # Identity promotion (SA -> ST) / 身份提升（SA -> ST）
        # ---------------------------------------------------
        # 对齐理论核心：SA（基础刺激元）可视为最小 ST（结构）。
        # 当语义合并发生且候选对象是 ST 时，优先把该运行态对象“锚定”为 ST，
        # 这样：
        #   1) 状态池中不会长期出现“同内容 SA 与 ST 并存”
        #   2) 下游模块（注意力/结构级查存/HDB）按 ref_object_type=="st" 过滤时不会漏掉对象
        #   3) 观测台显示更符合直觉：结构对象用 st_* 作为主 ID，SA 作为别名来源
        self._maybe_promote_existing_item_to_structure(existing_item, candidate_item)

        event = self._energy.apply_energy_delta(
            item=existing_item,
            delta_er=merge_info["delta_er"],
            delta_ev=merge_info["delta_ev"],
            tick_number=tick_number,
            reason=reason,
            source_module=source_module,
            trace_id=trace_id,
            tick_id=tick_id,
        )
        event["merge_mode"] = merge_mode
        event["merge_source_ref_id"] = candidate_item.get("ref_object_id", "")
        if merge_mode == "root_structure":
            event["runtime_root_structure_id"] = self._runtime_root_structure_id(existing_item)
        event["semantic_signature"] = candidate_item.get("semantic_signature", "")
        return event

    def _merge_runtime_ref_hit_fast(
        self,
        *,
        existing_item: dict,
        runtime_object: dict,
        tick_number: int,
        source_module: str,
        trace_id: str,
        tick_id: str,
    ) -> dict:
        """
        Fast path for repeated runtime projections of the exact same ref object.

        This is intentionally narrower than semantic merge: it only runs after
        PoolStore has already found the same ref_object_id. That lets hot paths
        such as induction growth skip rebuilding a full candidate state_item
        while still using the normal energy engine, fatigue, recency and event
        semantics.
        """
        runtime_energy = runtime_object.get("energy", {}) if isinstance(runtime_object.get("energy", {}), dict) else {}
        delta_er = float(runtime_energy.get("er", 0.0) or 0.0)
        delta_ev = float(runtime_energy.get("ev", 0.0) or 0.0)
        event = self._energy.apply_energy_delta(
            item=existing_item,
            delta_er=delta_er,
            delta_ev=delta_ev,
            tick_number=tick_number,
            reason="merge_on_insert",
            source_module=source_module,
            trace_id=trace_id,
            tick_id=tick_id,
        )
        if event:
            event["merge_mode"] = "ref_fast"
            event["merge_source_ref_id"] = str(runtime_object.get("id", "") or "")
            event["semantic_signature"] = str(existing_item.get("semantic_signature", "") or "")

        runtime_ext = runtime_object.get("ext", {}) if isinstance(runtime_object.get("ext", {}), dict) else {}
        runtime_meta = runtime_object.get("meta", {}) if isinstance(runtime_object.get("meta", {}), dict) else {}
        runtime_meta_ext = runtime_meta.get("ext", {}) if isinstance(runtime_meta.get("ext", {}), dict) else {}
        incoming_projection_meta = {"meta": {"ext": {}}, "ext": {}}
        for key in ("growth_projection", "component_energy"):
            value = runtime_meta_ext.get(key, runtime_ext.get(key))
            if isinstance(value, dict) and value:
                incoming_projection_meta["meta"]["ext"][key] = copy.deepcopy(value)
        if incoming_projection_meta["meta"]["ext"]:
            self._merge_runtime_projection_metadata(existing_item, incoming_projection_meta)
        else:
            self._refresh_runtime_resolution_metadata(existing_item, source="ref_fast_merge")
        self._maybe_reanchor_existing_item_to_memory_terminal(existing_item, runtime_object)
        existing_item["updated_at"] = max(
            int(existing_item.get("updated_at", 0) or 0),
            int(runtime_object.get("updated_at", 0) or 0),
        )
        return event

    def _merge_residual_memory_alias_conflicts(
        self,
        *,
        existing_item: dict,
        candidate_item: dict,
        tick_number: int,
        source_module: str,
        trace_id: str,
        tick_id: str,
    ) -> int:
        """Fold an already-inserted EM tail into its ST memory projection alias."""
        if not self._is_residual_memory_st_projection_candidate(candidate_item):
            return 0
        if str(existing_item.get("ref_object_type", "") or "").strip().lower() == "em":
            return 0
        existing_spi_id = str(existing_item.get("id", "") or "")
        if not existing_spi_id:
            return 0

        merged_count = 0
        for alias_id in list(candidate_item.get("ref_alias_ids", []) or []):
            alias_id = str(alias_id or "").strip()
            if not alias_id.startswith("em_"):
                continue
            conflict = self._find_residual_memory_alias_conflict(alias_id, existing_spi_id=existing_spi_id)
            if conflict is None:
                continue
            self._merge_candidate_into_existing(
                existing_item=existing_item,
                candidate_item=conflict,
                merge_mode="ref_alias_conflict",
                tick_number=tick_number,
                reason="merge_residual_memory_alias_conflict",
                source_module=source_module,
                trace_id=trace_id,
                tick_id=tick_id,
            )
            conflict_id = str(conflict.get("id", "") or "")
            if conflict_id:
                self._store.remove(conflict_id)
            merged_count += 1
        if merged_count:
            try:
                self._store.reindex_item(existing_spi_id)
            except Exception:
                pass
        return merged_count

    def _sanitize_residual_memory_ref_aliases(self, candidate_item: dict | None) -> None:
        """Keep EM instance aliases unique to their current ST carrier."""
        if not self._is_residual_memory_st_projection_candidate(candidate_item):
            return
        aliases = list(candidate_item.get("ref_alias_ids", []) or [])
        if not aliases:
            return
        filtered: list[str] = []
        for alias_id in aliases:
            alias_id = str(alias_id or "").strip()
            if not alias_id:
                continue
            if alias_id.startswith("em_"):
                existing = self._store.get_by_ref(alias_id)
                if existing is not None and not self._can_share_residual_memory_alias(existing, candidate_item):
                    continue
            if alias_id not in filtered:
                filtered.append(alias_id)
        candidate_item["ref_alias_ids"] = filtered

    def _candidate_ref_alias_ids_for_existing(self, existing_item: dict, candidate_item: dict) -> list[str]:
        aliases: list[str] = []
        for raw in list(candidate_item.get("ref_alias_ids", []) or [candidate_item.get("ref_object_id", "")]):
            alias_id = str(raw or "").strip()
            if not alias_id:
                continue
            if alias_id.startswith("em_") and not self._can_share_residual_memory_alias(existing_item, candidate_item):
                continue
            if alias_id not in aliases:
                aliases.append(alias_id)
        return aliases

    def _can_share_residual_memory_alias(self, existing_item: dict | None, candidate_item: dict | None) -> bool:
        if not isinstance(existing_item, dict) or not isinstance(candidate_item, dict):
            return True
        if not self._is_residual_memory_st_projection_candidate(existing_item):
            return True
        if not self._is_residual_memory_st_projection_candidate(candidate_item):
            return True
        existing_ref_id = str(existing_item.get("ref_object_id", "") or "").strip()
        candidate_ref_id = str(candidate_item.get("ref_object_id", "") or "").strip()
        return bool(existing_ref_id and candidate_ref_id and existing_ref_id == candidate_ref_id)

    @staticmethod
    def _is_residual_memory_st_projection_candidate(candidate_item: dict | None) -> bool:
        if not isinstance(candidate_item, dict):
            return False
        if str(candidate_item.get("ref_object_type", "") or "").strip() != "st":
            return False
        ref_snapshot = candidate_item.get("ref_snapshot", {}) if isinstance(candidate_item.get("ref_snapshot", {}), dict) else {}
        meta_ext = candidate_item.get("meta", {}).get("ext", {}) if isinstance(candidate_item.get("meta", {}).get("ext", {}), dict) else {}
        source_em_id = str(
            ref_snapshot.get("source_em_id", "")
            or ref_snapshot.get("memory_id", "")
            or meta_ext.get("source_em_id", "")
            or meta_ext.get("memory_id", "")
            or ""
        ).strip()
        if not source_em_id.startswith("em_"):
            return False
        residual_kind = str(ref_snapshot.get("residual_origin_kind", "") or meta_ext.get("residual_origin_kind", "") or "").strip()
        actual_type = str(meta_ext.get("memory_projection_object_type_actual", "") or "").strip()
        return bool(
            residual_kind == "memory_runtime_projection"
            or actual_type == "st"
            or bool(meta_ext.get("residual_memory_as_structure", False))
        )

    def _find_residual_memory_alias_conflict(self, memory_id: str, *, existing_spi_id: str) -> dict | None:
        memory_id = str(memory_id or "").strip()
        if not memory_id:
            return None
        for item in list(self._store.get_all()):
            if not isinstance(item, dict):
                continue
            if str(item.get("id", "") or "") == existing_spi_id:
                continue
            if str(item.get("ref_object_type", "") or "").strip() != "em":
                continue
            if str(item.get("ref_object_id", "") or "").strip() != memory_id:
                continue
            ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
            meta_ext = item.get("meta", {}).get("ext", {}) if isinstance(item.get("meta", {}).get("ext", {}), dict) else {}
            item_source_em = str(
                ref_snapshot.get("source_em_id", "")
                or ref_snapshot.get("memory_id", "")
                or meta_ext.get("source_em_id", "")
                or meta_ext.get("memory_id", "")
                or ""
            ).strip()
            if item_source_em and item_source_em != memory_id:
                continue
            residual_kind = str(ref_snapshot.get("residual_origin_kind", "") or meta_ext.get("residual_origin_kind", "") or "").strip()
            source = item.get("source", {}) if isinstance(item.get("source", {}), dict) else {}
            source_origin = str(source.get("origin", "") or "").strip()
            if residual_kind != "residual_tail_memory_projection" and source_origin != "residual_tail_memory_projection":
                continue
            return item
        return None

    def _reconcile_candidate_on_existing(
        self,
        existing_item: dict,
        candidate_item: dict,
        incoming_er: float,
        incoming_ev: float,
        tick_number: int,
        reason: str,
        source_module: str,
        trace_id: str,
        tick_id: str,
    ) -> dict:
        """
        按“当前感受器包的存在度”去对齐已有状态项，而不是盲目叠加。

        当前默认策略为 max：
        - 若本轮 packet 聚合后的能量高于现有运行态，则抬升到该值；
        - 若本轮只是较弱残响，则不再把旧刺激层层叠加放大。
        """
        self._refresh_existing_item_from_candidate(existing_item, candidate_item)
        self._maybe_reanchor_existing_item_to_memory_terminal(existing_item, candidate_item)
        self._maybe_promote_existing_item_to_structure(existing_item, candidate_item)

        current_er = existing_item["energy"]["er"]
        current_ev = existing_item["energy"]["ev"]
        reconcile_mode = self._config.get("sensor_input_reconcile_mode", "max")

        if reconcile_mode == "add":
            target_er = current_er + incoming_er
            target_ev = current_ev + incoming_ev
        else:
            target_er = max(current_er, incoming_er)
            target_ev = max(current_ev, incoming_ev)

        event = self._energy.apply_energy_delta(
            item=existing_item,
            delta_er=target_er - current_er,
            delta_ev=target_ev - current_ev,
            tick_number=tick_number,
            reason=reason,
            source_module=source_module,
            trace_id=trace_id,
            tick_id=tick_id,
        )
        event["incoming_packet_er"] = round(incoming_er, 8)
        event["incoming_packet_ev"] = round(incoming_ev, 8)
        event["reconcile_mode"] = reconcile_mode
        event["semantic_signature"] = candidate_item.get("semantic_signature", "")
        return event

    def _maybe_promote_existing_item_to_structure(self, existing_item: dict, candidate_item: dict) -> None:
        """
        Promote an existing merged item to "structure" (ST) identity when possible.
        当语义合并把 SA 与 ST 合并到一起时，尽量让运行态对象以 ST 作为主身份。

        Why / 为什么要做这个提升：
          - 状态池对象唯一性：同一个概念不应同时以 SA 与 ST 两种身份存在；
          - 下游模块常按 ref_object_type=="st" 做结构级输入过滤；
          - 前端展示更直观：用 st_* 作为主 id，更像“结构对象”。

        Safety / 安全性：
          - 只在 candidate 是 ST 且 existing 不是 ST 时提升；
          - 不会删除旧 ref_id：旧 SA id 仍保留在 ref_alias_ids 并被 PoolStore 索引；
          - 仅修改 existing_item 的 ref_object_id/type 与 type_index，避免破坏能量与绑定状态。
        """
        try:
            cand_type = str(candidate_item.get("ref_object_type", "") or "").strip()
            if cand_type != "st":
                return
            old_type = str(existing_item.get("ref_object_type", "") or "").strip()
            if old_type == "st":
                return
            if self._should_keep_existing_item_as_memory_terminal(existing_item, candidate_item):
                return

            cand_ref_id = str(candidate_item.get("ref_object_id", "") or "").strip()
            if not cand_ref_id:
                return

            spi_id = str(existing_item.get("id", "") or "").strip()
            if not spi_id:
                return

            # Update primary identity fields / 更新主身份字段
            existing_item["ref_object_type"] = "st"
            existing_item["ref_object_id"] = cand_ref_id
            # Keep sub_type aligned for observability (optional)
            # 同步 sub_type（用于观测，不影响语义）
            existing_item["sub_type"] = "st_runtime_item"

            # Update PoolStore type index / 更新类型索引
            try:
                # Remove from old type set
                if old_type and hasattr(self._store, "_type_index") and isinstance(self._store._type_index, dict):
                    if old_type in self._store._type_index:
                        self._store._type_index[old_type].discard(spi_id)
                # Add to ST set
                if hasattr(self._store, "_type_index") and isinstance(self._store._type_index, dict):
                    self._store._type_index.setdefault("st", set()).add(spi_id)
            except Exception:
                # Fallback: rebuild all indexes (best-effort, should be rare).
                try:
                    self._store.rebuild_index()
                except Exception:
                    pass
        except Exception:
            # Best-effort: never crash merges.
            return

    def _maybe_reanchor_existing_item_to_memory_terminal(
        self,
        existing_item: dict | None,
        incoming_item: dict | None,
    ) -> None:
        if not self._should_reanchor_existing_item_to_memory_terminal(existing_item, incoming_item):
            return
        assert isinstance(existing_item, dict)
        memory_id = self._memory_terminal_id_from_item(incoming_item)
        if not memory_id:
            memory_id = self._memory_terminal_id_from_item(existing_item)
        if not memory_id:
            return
        old_ref_id = str(existing_item.get("ref_object_id", "") or "").strip()
        aliases = list(existing_item.get("ref_alias_ids", []) or [])
        merged_aliases: list[str] = []
        for raw in [memory_id, old_ref_id, *aliases]:
            alias_id = str(raw or "").strip()
            if alias_id and alias_id not in merged_aliases:
                merged_aliases.append(alias_id)
        existing_item["ref_object_type"] = "em"
        existing_item["ref_object_id"] = memory_id
        existing_item["ref_alias_ids"] = merged_aliases
        existing_item["sub_type"] = "em_runtime_item"

        ref_snapshot = existing_item.setdefault("ref_snapshot", {})
        if isinstance(ref_snapshot, dict):
            ref_snapshot["source_em_id"] = memory_id
            ref_snapshot["memory_id"] = memory_id
            ref_snapshot["residual_kind"] = "memory"

        meta = existing_item.setdefault("meta", {})
        if isinstance(meta, dict):
            meta_ext = meta.setdefault("ext", {})
            if isinstance(meta_ext, dict):
                meta_ext["source_em_id"] = memory_id
                meta_ext["memory_id"] = memory_id
                meta_ext["memory_terminal_converged"] = True

        try:
            self._store.reindex_item(str(existing_item.get("id", "") or ""))
        except Exception:
            try:
                self._store.rebuild_index()
            except Exception:
                pass

    def _should_reanchor_existing_item_to_memory_terminal(
        self,
        existing_item: dict | None,
        incoming_item: dict | None,
    ) -> bool:
        if not isinstance(existing_item, dict) or not isinstance(incoming_item, dict):
            return False
        if str(existing_item.get("ref_object_type", "") or "").strip().lower() != "st":
            return False
        if not self._is_residual_memory_st_projection_candidate(existing_item):
            return False
        incoming_type = str(
            incoming_item.get("ref_object_type", "")
            or incoming_item.get("object_type", "")
            or ""
        ).strip().lower()
        if incoming_type != "em":
            return False
        existing_memory_id = self._memory_terminal_id_from_item(existing_item)
        incoming_memory_id = self._memory_terminal_id_from_item(incoming_item)
        return bool(existing_memory_id and incoming_memory_id and existing_memory_id == incoming_memory_id)

    @staticmethod
    def _memory_terminal_id_from_item(item: dict | None) -> str:
        if not isinstance(item, dict):
            return ""
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        meta_ext = (
            item.get("meta", {}).get("ext", {})
            if isinstance(item.get("meta", {}), dict) and isinstance(item.get("meta", {}).get("ext", {}), dict)
            else {}
        )
        ext = item.get("ext", {}) if isinstance(item.get("ext", {}), dict) else {}
        candidates = [
            ref_snapshot.get("source_em_id", ""),
            ref_snapshot.get("memory_id", ""),
            meta_ext.get("source_em_id", ""),
            meta_ext.get("memory_id", ""),
            ext.get("source_em_id", ""),
            ext.get("memory_id", ""),
        ]
        item_type = str(item.get("ref_object_type", "") or item.get("object_type", "") or "").strip().lower()
        item_id = str(item.get("ref_object_id", "") or item.get("id", "") or "").strip()
        if item_type == "em":
            candidates.append(item_id)
        for raw in candidates:
            memory_id = str(raw or "").strip()
            if memory_id.startswith("em_"):
                return memory_id
        return ""

    @staticmethod
    def _should_keep_existing_item_as_memory_terminal(existing_item: dict | None, candidate_item: dict | None) -> bool:
        if not isinstance(existing_item, dict) or not isinstance(candidate_item, dict):
            return False
        existing_ref_type = str(existing_item.get("ref_object_type", "") or "").strip().lower()
        if existing_ref_type != "em":
            return False
        candidate_ref_type = str(candidate_item.get("ref_object_type", "") or "").strip().lower()
        if candidate_ref_type != "st":
            return False

        existing_snapshot = (
            existing_item.get("ref_snapshot", {}) if isinstance(existing_item.get("ref_snapshot", {}), dict) else {}
        )
        candidate_snapshot = (
            candidate_item.get("ref_snapshot", {}) if isinstance(candidate_item.get("ref_snapshot", {}), dict) else {}
        )
        existing_meta_ext = (
            existing_item.get("meta", {}).get("ext", {})
            if isinstance(existing_item.get("meta", {}), dict) and isinstance(existing_item.get("meta", {}).get("ext", {}), dict)
            else {}
        )
        candidate_meta_ext = (
            candidate_item.get("meta", {}).get("ext", {})
            if isinstance(candidate_item.get("meta", {}), dict) and isinstance(candidate_item.get("meta", {}).get("ext", {}), dict)
            else {}
        )
        existing_memory_id = str(
            existing_snapshot.get("source_em_id", "")
            or existing_snapshot.get("memory_id", "")
            or existing_meta_ext.get("source_em_id", "")
            or existing_meta_ext.get("memory_id", "")
            or existing_item.get("ref_object_id", "")
            or ""
        ).strip()
        candidate_memory_id = str(
            candidate_snapshot.get("source_em_id", "")
            or candidate_snapshot.get("memory_id", "")
            or candidate_meta_ext.get("source_em_id", "")
            or candidate_meta_ext.get("memory_id", "")
            or ""
        ).strip()
        if not existing_memory_id or not candidate_memory_id or existing_memory_id != candidate_memory_id:
            return False
        actual_type = str(candidate_meta_ext.get("memory_projection_object_type_actual", "") or "").strip().lower()
        return actual_type == "st"

    def _refresh_existing_item_from_candidate(self, existing_item: dict, candidate_item: dict):
        """
        在语义合并时回写候选对象的非能量信息。

        这里不会覆盖运行态字段（如 binding_state、bound runtime attrs），
        只补充 ref alias、语义签名和更完整的静态快照信息。
        """
        candidate_ref_ids = self._candidate_ref_alias_ids_for_existing(existing_item, candidate_item)
        for candidate_ref_id in candidate_ref_ids:
            if candidate_ref_id:
                self._store.bind_ref_alias(existing_item["id"], candidate_ref_id)

        if candidate_item.get("semantic_signature") and not existing_item.get("semantic_signature"):
            existing_item["semantic_signature"] = candidate_item["semantic_signature"]
        if candidate_item.get("semantic_context_key") and not existing_item.get("semantic_context_key"):
            existing_item["semantic_context_key"] = candidate_item["semantic_context_key"]
        elif not existing_item.get("semantic_context_key"):
            computed_key = semantic_context_key_from_item(existing_item)
            if computed_key:
                existing_item["semantic_context_key"] = computed_key

        # Merge learned/packet-side attributes from candidate.
        # 合并“记忆/结构侧属性”（packet 属性）：
        # - 这些属性来自 stimulus_packet/memory_feedback 或结构投影本身；
        # - 它们是期待/压力等规则的关键输入（IESM selector.scope=packet）。
        #
        # 注意：这里仍然不覆盖 runtime 绑定属性（bound_attribute_by_name），只合并 packet 属性映射。
        try:
            cand_bs = candidate_item.get("binding_state", {}) if isinstance(candidate_item.get("binding_state", {}), dict) else {}
            cand_packet = cand_bs.get("packet_attribute_by_name", {})
            if isinstance(cand_packet, dict) and cand_packet:
                ex_bs = existing_item.setdefault("binding_state", {})
                if not isinstance(ex_bs, dict):
                    ex_bs = {}
                    existing_item["binding_state"] = ex_bs
                ex_packet = ex_bs.setdefault("packet_attribute_by_name", {})
                if not isinstance(ex_packet, dict):
                    ex_packet = {}
                    ex_bs["packet_attribute_by_name"] = ex_packet
                for name, row in cand_packet.items():
                    key = str(name or "").strip()
                    if not key or not isinstance(row, dict):
                        continue
                    if key not in ex_packet:
                        ex_packet[key] = dict(row)
                        continue
                    # Prefer the fresher record if updated_at exists.
                    try:
                        old_u = int((ex_packet.get(key) or {}).get("updated_at", 0) or 0)
                        new_u = int(row.get("updated_at", 0) or 0)
                        if new_u > old_u:
                            ex_packet[key] = dict(row)
                    except Exception:
                        # If parsing fails, keep the existing one (stability).
                        pass
        except Exception:
            pass

        existing_ext = existing_item.setdefault("ext", {})
        candidate_ext = candidate_item.get("ext", {})
        if candidate_ext.get("semantic_labels") and not existing_ext.get("semantic_labels"):
            existing_ext["semantic_labels"] = candidate_ext["semantic_labels"]

        existing_snapshot = existing_item.setdefault("ref_snapshot", {})
        candidate_snapshot = candidate_item.get("ref_snapshot", {})
        list_fields = {"attribute_displays", "feature_displays", "bound_attribute_displays", "member_summaries"}
        richer_snapshot_fields = {"sequence_groups", "flat_tokens", "content_signature", "content_display", "content_display_detail", "structure_ext", "member_refs", "token_count"}

        for key, value in candidate_snapshot.items():
            if key in richer_snapshot_fields:
                existing_groups = existing_snapshot.get("sequence_groups", []) or []
                candidate_groups = candidate_snapshot.get("sequence_groups", []) or []
                existing_has_string = any(isinstance(g, dict) and bool(g.get("order_sensitive", False)) and str(g.get("string_unit_kind", "") or "") == "char_sequence" for g in existing_groups)
                candidate_has_string = any(isinstance(g, dict) and bool(g.get("order_sensitive", False)) and str(g.get("string_unit_kind", "") or "") == "char_sequence" for g in candidate_groups)
                should_replace = False
                if key == "sequence_groups":
                    should_replace = bool(candidate_groups) and (not existing_groups or candidate_has_string or len(candidate_groups) > len(existing_groups))
                elif key == "flat_tokens":
                    should_replace = bool(value) and (not existing_snapshot.get(key) or candidate_has_string)
                else:
                    should_replace = value not in ("", None, [], {}) and (existing_snapshot.get(key) in ("", None, [], {}) or candidate_has_string)
                if should_replace:
                    existing_snapshot[key] = value
                continue
            if key in list_fields:
                merged_list = list(existing_snapshot.get(key, []))
                for entry in value or []:
                    if entry not in merged_list:
                        merged_list.append(entry)
                if merged_list:
                    existing_snapshot[key] = merged_list
                continue

            if key not in existing_snapshot or existing_snapshot.get(key) in ("", None, [], {}):
                if value not in ("", None, [], {}):
                    existing_snapshot[key] = value

        existing_item["updated_at"] = max(
            existing_item.get("updated_at", 0),
            candidate_item.get("updated_at", 0),
        )
        self._refresh_runtime_resolution_metadata(existing_item, source="refresh_existing_item_from_candidate")
        try:
            self._store.reindex_item(existing_item["id"])
        except Exception:
            pass

    @staticmethod
    def _select_representative_candidate(entries: list[dict]) -> dict:
        """在同一输入组内选择最适合承载静态快照的候选对象。优先当前刺激，其次能量更高者。"""
        ordered = sorted(
            entries,
            key=lambda entry: (
                entry.get("packet_context", {}).get("source_type") != "current",
                -entry.get("candidate", {}).get("energy", {}).get("er", 0.0),
            ),
        )
        return ordered[0]["candidate"]

    def _synchronize_candidate_with_group(
        self,
        candidate_item: dict,
        *,
        entries: list[dict],
        total_er: float,
        total_ev: float,
    ) -> dict:
        """
        把同组输入聚合后的能量与别名回写到代表候选项上。

        这样“当前刺激 + 多轮残响”的组合，进入状态池前先成为一个更完整的本轮输入投影。
        """
        ref_alias_ids: list[str] = []
        for entry in entries:
            ref_id = entry["candidate"].get("ref_object_id", "")
            if ref_id and ref_id not in ref_alias_ids:
                ref_alias_ids.append(ref_id)

        candidate_item["ref_alias_ids"] = ref_alias_ids or candidate_item.get("ref_alias_ids", [])

        energy = candidate_item["energy"]
        dynamics = candidate_item["dynamics"]
        cp_delta = round(total_er - total_ev, 8)
        cp_abs = round(abs(cp_delta), 8)

        energy["er"] = round(total_er, 8)
        energy["ev"] = round(total_ev, 8)
        energy["salience_score"] = round(max(total_er, total_ev), 8)
        energy["cognitive_pressure_delta"] = cp_delta
        energy["cognitive_pressure_abs"] = cp_abs

        dynamics["delta_er"] = round(total_er, 8)
        dynamics["delta_ev"] = round(total_ev, 8)
        dynamics["er_change_rate"] = round(total_er, 6)
        dynamics["ev_change_rate"] = round(total_ev, 6)
        dynamics["delta_cp_delta"] = cp_delta
        dynamics["delta_cp_abs"] = cp_abs
        dynamics["cp_delta_rate"] = round(cp_delta, 6)
        dynamics["cp_abs_rate"] = round(cp_abs, 6)

        ext = candidate_item.setdefault("ext", {})
        ext["incoming_packet_member_count"] = len(entries)
        ext["incoming_packet_source_types"] = sorted(
            {
                entry.get("packet_context", {}).get("source_type", "")
                for entry in entries
                if entry.get("packet_context")
            }
        )

        return candidate_item

    def _validate_stimulus_packet(self, pkt: Any, trace_id: str, apply_mode: str) -> dict | None:
        """校验刺激包。返回 None 表示通过。"""
        if not isinstance(pkt, dict):
            return {"code": "INPUT_VALIDATION_ERROR",
                    "message_zh": "stimulus_packet 必须是 dict",
                    "message_en": "stimulus_packet must be a dict"}

        if pkt.get("object_type") != "stimulus_packet":
            return {"code": "INPUT_VALIDATION_ERROR",
                    "message_zh": "stimulus_packet.object_type 必须为 'stimulus_packet'",
                    "message_en": "stimulus_packet.object_type must be 'stimulus_packet'"}

        for field in ("id", "sa_items", "csa_items"):
            if field not in pkt:
                return {"code": "INPUT_VALIDATION_ERROR",
                        "message_zh": f"stimulus_packet 缺少字段: {field}",
                        "message_en": f"stimulus_packet missing field: {field}"}

        valid_modes = ("normal", "validation_only", "dry_run")
        if apply_mode not in valid_modes:
            return {"code": "INPUT_VALIDATION_ERROR",
                    "message_zh": f"apply_mode 不合法: {apply_mode}",
                    "message_en": f"Invalid apply_mode: {apply_mode}"}
        return None

    def _broadcast_script_check(self, events: list[dict], trace_id: str, tick_id: str) -> bool:
        """生成脚本检查抄送包并调用占位接口。"""
        try:
            packet = self._snapshot.build_script_check_packet(
                events=events, pool_store=self._store,
                trace_id=trace_id, tick_id=tick_id,
            )

            self._logger.detail(
                trace_id=trace_id, step="broadcast_state_window_for_script_check",
                message_zh="已向先天脚本检查接口抄送状态变化窗口",
                message_en="State change window broadcast to innate script checker",
                tick_id=tick_id,
                info={"packet_id": packet.get("packet_id", ""),
                      "summary": packet.get("summary", {}),
                      "candidate_count": len(packet.get("candidate_triggers", []))},
            )

            # 调用占位接口
            if self._config.get("enable_placeholder_interfaces", True) and self._config.get("placeholder_script_enabled", True):
                try:
                    from interfaces.innate_script.placeholder_innate_script_api import check_state_window
                    result = check_state_window(packet)
                    self._logger.detail(
                        trace_id=trace_id, step="placeholder_script_response",
                        message_zh="占位脚本接口返回", message_en="Placeholder script interface responded",
                        tick_id=tick_id,
                        info={"placeholder_code": result.get("code", ""), "success": result.get("success", False)},
                    )
                except ImportError:
                    self._logger.detail(
                        trace_id=trace_id, step="placeholder_script_unavailable",
                        message_zh="占位脚本接口不可用（模块未找到）",
                        message_en="Placeholder script interface unavailable (module not found)",
                        tick_id=tick_id,
                    )
            return True
        except Exception as e:
            self._logger.error(
                trace_id=trace_id, interface="broadcast_script_check",
                code="OUTPUT_ERROR", message_zh=f"脚本广播失败: {e}",
                message_en=f"Script broadcast failed: {e}", tick_id=tick_id,
            )
            return False

    def _emit_attention_snapshot(self, trace_id: str, tick_id: str):
        """生成并输出注意力快照（占位）。"""
        try:
            snapshot = self._snapshot.build_attention_snapshot(
                pool_store=self._store, trace_id=trace_id, tick_id=tick_id,
            )
            if self._config.get("enable_placeholder_interfaces", True) and self._config.get("placeholder_attention_enabled", True):
                try:
                    from interfaces.attention.placeholder_attention_api import receive_state_snapshot
                    receive_state_snapshot(snapshot)
                except ImportError:
                    pass
        except Exception:
            pass

    def _summarize_state_item_for_log(self, item: dict) -> dict:
        if not isinstance(item, dict):
            return {}
        energy = item.get("energy", {}) if isinstance(item.get("energy", {}), dict) else {}
        source = item.get("source", {}) if isinstance(item.get("source", {}), dict) else {}
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        return {
            "id": item.get("id", ""),
            "sub_type": item.get("sub_type", ""),
            "ref_object_type": item.get("ref_object_type", ""),
            "ref_object_id": item.get("ref_object_id", ""),
            "status": item.get("status", ""),
            "content_display": ref_snapshot.get("content_display", ""),
            "content_signature": ref_snapshot.get("content_signature", ""),
            "er": energy.get("er", 0.0),
            "ev": energy.get("ev", 0.0),
            "cp_abs": energy.get("cognitive_pressure_abs", 0.0),
            "source_module": source.get("module", ""),
            "source_origin": source.get("origin", ""),
        }

    def _compact_detail_log_payload(self, value):
        if self._config.get("detail_log_dump_full_object", True):
            return value
        if isinstance(value, dict):
            if str(value.get("object_type", "")) == "state_item":
                return self._summarize_state_item_for_log(value)
            compact = {}
            for key, item in value.items():
                if isinstance(item, dict) and str(item.get("object_type", "")) == "state_item":
                    compact[key] = self._summarize_state_item_for_log(item)
                elif isinstance(item, list) and item and all(isinstance(x, dict) and str(x.get("object_type", "")) == "state_item" for x in item[:3]):
                    compact[key] = [self._summarize_state_item_for_log(x) for x in item[:5]]
                else:
                    compact[key] = item
            return compact
        return value

    def _log_change_event(self, event: dict, trace_id: str, tick_id: str):
        """将变化事件写入 detail 日志。"""
        if self._config.get("detail_log_dump_change_event", True):
            self._logger.detail(
                trace_id=trace_id, step=event.get("event_type", "unknown_event"),
                message_zh=f"对象状态变化: {event.get('target_item_id', '')}",
                message_en=f"State item changed: {event.get('target_item_id', '')}",
                tick_id=tick_id, info=self._compact_detail_log_payload(event),
            )

    def _make_error_response(self, code: str, msg_zh: str, msg_en: str, trace_id: str, start_time: float) -> dict:
        """构建错误响应并记录日志。"""
        self._logger.error(
            trace_id=trace_id, interface="", code=code,
            message_zh=msg_zh, message_en=msg_en,
        )
        return self._make_response(False, code, f"{msg_zh} / {msg_en}",
            trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time))

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        return int((time.time() - start) * 1000)

    @staticmethod
    def _make_response(success: bool, code: str, message: str,
                       data: Any = None, error: Any = None,
                       trace_id: str = "", elapsed_ms: int = 0) -> dict:
        """构建 AP 标准统一返回结构。"""
        return {
            "success": success, "code": code, "message": message,
            "data": data, "error": error,
            "meta": {
                "module": __module_name__, "interface": "",
                "trace_id": trace_id, "elapsed_ms": elapsed_ms, "logged": True,
            },
        }
