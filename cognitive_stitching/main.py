# -*- coding: utf-8 -*-
"""
Cognitive Stitching (CS) runtime engine.

Current rollout scope:
- pair create remains supported
- existing CS events can re-enter the candidate pool as active seeds
- conservative right-end event extension is enabled
- conservative event-to-event bridge merge is enabled
- weak matching and same-path fatigue stay numeric, never hard-blocking
"""

from __future__ import annotations

import math
import os
import time
from typing import Any

from hdb._numeric_match import describe_numeric_match
from hdb._structure_resolver import (
    find_exact_structure_by_signature,
    resolve_or_create_structure_from_profile,
)
from state_pool._semantic_identity import semantic_context_key_from_item


def _parse_simple_yaml_scalar(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return ""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none", "~"}:
        return None
    try:
        if any(marker in text for marker in (".", "e", "E")):
            return float(text)
        return int(text)
    except ValueError:
        return text


def _load_simple_yaml_config(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    data: dict[str, Any] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line or line.startswith("#") or ":" not in raw_line:
                    continue
                key, raw_value = raw_line.split(":", 1)
                key = key.strip()
                if not key:
                    continue
                value_text = raw_value.split("#", 1)[0].strip()
                data[key] = _parse_simple_yaml_scalar(value_text)
    except Exception:
        return {}
    return data


def _load_yaml_config(path: str) -> dict[str, Any]:
    try:
        import yaml

        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else _load_simple_yaml_config(path)
    except ImportError:
        return _load_simple_yaml_config(path)
    except Exception:
        return _load_simple_yaml_config(path)


_DEFAULT_CONFIG = {
    "enabled": False,
    # Mode scaffold for theory-core v2 rollout:
    # - legacy_event: keep current event stitching behavior
    # - context_match_v2: context-tail cover + generic structure concat main path
    # - hybrid_compare: run legacy path now, but surface v2 readiness/audit fields
    "stitching_mode": "context_match_v2",
    "cs_v2_audit_only": False,
    "context_concat_v2_enabled": True,
    "context_concat_min_context_ratio": 0.22,
    "context_concat_allow_partial_without_path_support": True,
    "context_concat_soft_scan_enabled": True,
    "context_concat_soft_scan_when_exact_candidates_missing_only": True,
    "context_concat_soft_scan_privileged_only": True,
    "context_concat_soft_scan_max_sources_per_tick": 32,
    "context_concat_soft_scan_max_targets_per_source": 48,
    "context_concat_project_non_st_support_sources_enabled": True,
    "context_concat_profile_support_lookup_enabled": True,
    "context_concat_max_targets_per_seed": 0,
    "context_concat_compete_per_source_only": False,
    "context_concat_exclusive_items_per_tick": True,
    "context_concat_direct_owner_bonus": 1.0,
    "context_concat_path_bonus": 0.72,
    "context_concat_partial_path_bonus": 0.52,
    "context_concat_match_count_weight": 0.12,
    "context_concat_match_count_half_point": 2.4,
    "context_concat_match_count_soft_power": 0.78,
    "context_concat_match_count_linear_mix": 0.28,
    "context_concat_attribute_bonus_weight": 0.08,
    "context_concat_attribute_bonus_cap": 2.0,
    "context_concat_attribute_anchor_bonus": 0.18,
    "context_concat_attribute_numeric_abs_tolerance": 0.2,
    "context_concat_attribute_numeric_rel_tolerance": 0.35,
    "context_concat_attribute_numeric_min_similarity": 0.4,
    "context_concat_result_confidence": 0.82,
    "cs_v2_min_match_score": 0.18,
    "cs_v2_context_cover_weight": 0.32,
    "cs_v2_order_weight": 0.22,
    "cs_v2_tail_match_weight": 0.28,
    "cs_v2_context_db_weight": 0.10,
    "cs_v2_energy_profile_weight": 0.08,
    "cs_v2_match_count_weight": 0.10,
    "cs_v2_attribute_bonus_weight": 0.06,
    "cs_v2_same_pair_fatigue_enabled": True,
    # V2 评分柔化：
    # - 不直接把多个中低分子项当作“硬损失”连续压缩
    # - 对 0~1 子项做凹形抬升（raw -> soft），让中等质量候选不会因为多个重要但非完美因素而塌得太低
    # - 仍保留 raw 分数，便于审计 / 回滚 / A/B 对照
    "cs_v2_component_soft_power": 0.72,
    "cs_v2_component_soft_linear_mix": 0.32,
    "cs_v2_base_raw_mix": 0.35,
    "cs_v2_fatigue_soft_power": 0.78,
    "cs_v2_fatigue_soft_linear_mix": 0.40,
    "snapshot_top_k": 0,
    "max_seed_items": 0,
    "max_outgoing_edges_per_seed": 8,
    "max_events_per_tick": 0,
    "max_context_k": 2,
    "max_event_head_match_components": 3,
    "max_event_component_count": 8,
    # Event degeneration / 事件退化（组分淘汰）
    # 说明：
    # - 认知拼接事件（CS Event）在长期运行中可能出现“组分退化”：某些组分逐渐失去能量贡献，
    #   最终不再值得保留在事件结构里。
    # - 当退化发生时，我们会把“退化后的事件结构”当作一个新的长期结构写入 HDB，
    #   并建立链式索引，从而保证事件结构始终是“健全的”（可 O(1) 指针打开、可被刺激级查存一体发现）。
    #
    # 重要设计取舍：
    # - 退化判定使用纯数值阈值（share + absolute energy），不硬编码语义规则。
    # - 为了避免在热路径中引入不可控的写放大，本轮退化处理有数量上限。
    "enable_event_degeneration": True,
    # 每 tick 最多处理多少个事件的退化（按事件总能量从高到低挑选）。
    "event_degeneration_max_events_per_tick": 2,
    # 退化后事件最少保留的组分数（小于该值则不生成新的事件结构）。
    "event_degeneration_min_components": 2,
    # share 阈值：某组分在事件中的能量占比（profile_share）低于该值，才有资格被淘汰。
    "event_degeneration_share_threshold": 0.06,
    # absolute 阈值：组分在本事件中分到的绝对能量（share * total_energy）低于该值，才会被淘汰。
    # 注意：该阈值与 share 阈值是“同时满足”才淘汰，以避免小能量事件被过早拆空。
    "event_degeneration_min_component_energy": 0.04,
    "enable_event_extend": True,
    "enable_event_merge": True,
    # Event grasp (a cognitive feeling bound to ES objects).
    # Trigger: event in CAM + energy above threshold (see design doc section 14).
    "enable_event_grasp": True,
    "event_grasp_min_total_energy": 0.25,
    "event_grasp_max_events_per_tick": 4,
    "event_grasp_energy_weight": 1.2,
    "event_grasp_balance_weight": 1.3,
    "event_grasp_margin_weight": 0.8,
    "event_grasp_bias": -1.0,
    "event_grasp_sigmoid_temperature": 1.0,
    "event_grasp_attribute_name": "event_grasp",
    "event_grasp_post_action_threshold_scale": 0.75,
    # Bridge current integrated order:
    # attention CAM is built before CS in Observatory.run_cycle(),
    # so freshly created / reinforced ES would otherwise never qualify for grasp
    # in the same tick. Keep this switchable for rollback / A/B.
    "event_grasp_include_post_cs_action_events": True,
    # ESDB (in-memory) lazy merge (parents+delta) and idle consolidation.
    "enable_esdb_overlay": True,
    # How to open context DB for events:
    # - tail_components: current phase2 conservative behavior (open tail component ST DBs)
    # - event_overlay: open ES overlay DB only
    # - hybrid: open both and take the best candidates (default, still capped by max_outgoing_edges_per_seed)
    "event_context_open_mode": "hybrid",
    "esdb_overlay_parent_beta": 0.35,
    "esdb_overlay_top_k": 16,
    "esdb_overlay_cache_ttl_ms": 2500,
    "esdb_materialize_top_n": 96,
    # ESDB delta: small runtime-only outgoing edge cache for ES (to avoid "parents-only overlay" stalling).
    # This is NOT persisted to HDB in current phases.
    "enable_esdb_delta": True,
    "esdb_delta_import_top_k_per_tail": 6,
    "esdb_delta_max_entries": 96,
    "esdb_delta_distance_decay": 0.75,
    "esdb_delta_merge_beta": 0.25,
    "esdb_delta_min_weight": 0.0001,
    # Persist ES into HDB (event structures must be "健全的长期结构").
    # 说明：本开关为真时，CS 将尽量让事件以 HDB-backed 结构形式存在（有独立数据库指针，O(1) 可索引定位）。
    "enable_persist_events_to_hdb": True,
    # Whether legacy shell-like CS event runtime items should enter StatePool as
    # ordinary runtime structures. Default is OFF to avoid polluting the main
    # runtime chain with event-shell structures.
    "insert_event_runtime_items_into_state_pool": False,
    # When an event has already been persisted into HDB as a normal structure,
    # allow its HDB-backed runtime projection to re-enter StatePool. This keeps
    # narrative/event outputs observable without reopening the old shell-pollution path.
    "insert_persisted_event_runtime_items_into_state_pool": True,
    "persist_events_max_diff_entries": 96,
    # Idle consolidation budgets / guards
    "idle_consolidate_max_events": 256,
    "idle_consolidate_clear_all_caches": True,
    "idle_consolidate_cache_est_bytes_per_row": 220,
    "min_seed_total_energy": 0.03,
    "min_candidate_score": 0.08,
    "min_event_total_energy": 0.01,
    "base_absorb_ratio": 0.12,
    "pair_absorb_ratio_cap": 0.22,
    "context_concat_exact_absorb_ratio": 0.94,
    "context_concat_exact_absorb_cap": 0.98,
    "context_concat_use_lower_energy_cap": True,
    "context_concat_exact_min_score": 0.86,
    "context_concat_exact_ignore_object_fatigue": True,
    "extend_absorb_scale": 0.92,
    "merge_absorb_scale": 0.84,
    "same_pair_fatigue_decay": 0.72,
    "same_pair_fatigue_step": 0.35,
    "same_pair_fatigue_cap": 1.6,
    "same_pair_fatigue_floor_scale": 0.25,
    "object_stitch_fatigue_enabled": True,
    # 0.90 ** 50 ~= 0.005, so an isolated attribution fatigue is almost fully
    # recovered after roughly 50 ticks without requiring a hard timer.
    "object_stitch_fatigue_decay": 0.90,
    "object_stitch_fatigue_step": 0.85,
    "object_stitch_fatigue_cap": 2.2,
    "object_stitch_fatigue_floor_scale": 0.28,
    "object_stitch_fatigue_apply_to_result": True,
    "edge_ratio_weight": 0.42,
    "energy_balance_weight": 0.23,
    "match_strength_weight": 0.20,
    "runtime_weight_weight": 0.15,
    "context_support_weight": 0.18,
    "bridge_span_weight": 0.08,
    "anchor_distance_penalty": 0.18,
    "containment_match_scale": 0.78,
    "weak_overlap_match_scale": 0.42,
    "weak_overlap_min_ratio": 0.5,
    "event_prefix_match_scale": 1.0,
    "event_prefix_weak_scale": 0.36,
    "event_id_prefix": "cs_event",
    "display_joiner": " -> ",
    "narrative_top_k": 6,
}


class CognitiveStitchingEngine:
    def __init__(self, config_path: str = "", config_override: dict | None = None):
        self._config_path = config_path or os.path.join(
            os.path.dirname(__file__), "config", "cognitive_stitching_config.yaml"
        )
        self._config = self._build_config(config_override)
        self._pair_fatigue: dict[str, float] = {}
        self._object_stitch_fatigue: dict[str, float] = {}
        # ESDB: in-memory event DB with lazy merge metadata (parents+delta).
        # Note: this is runtime-only for now; consolidation can flatten chains and clear caches.
        self._esdb: dict[str, dict[str, Any]] = {}
        # Idle consolidation last result snapshot (for observability/UI).
        self._idle_consolidation_count_total = 0
        self._last_idle_consolidation: dict[str, Any] | None = None
        self._last_report: dict[str, Any] = {}
        self._current_candidate_audit: dict[str, Any] | None = None
        self._current_apply_audit: dict[str, Any] | None = None
        self._support_projection_cache: dict[tuple, str] = {}
        self._signature_cache: dict[tuple[int, tuple[str, ...]], str] = {}

    def close(self) -> None:
        return

    def clear_runtime_state(self, trace_id: str = "cs_clear_runtime", reason: str = "runtime_reset") -> dict:
        result = {
            "cleared_pair_fatigue_count": len(self._pair_fatigue),
            "cleared_object_stitch_fatigue_count": len(self._object_stitch_fatigue),
            "cleared_esdb_event_count": len(self._esdb),
            "had_last_idle_consolidation": self._last_idle_consolidation is not None,
            "had_last_report": bool(self._last_report),
            "idle_consolidation_count_before": int(self._idle_consolidation_count_total),
        }
        self._pair_fatigue.clear()
        self._object_stitch_fatigue.clear()
        self._esdb.clear()
        self._support_projection_cache.clear()
        self._signature_cache.clear()
        self._idle_consolidation_count_total = 0
        self._last_idle_consolidation = None
        self._last_report = {}
        self._current_candidate_audit = None
        self._current_apply_audit = None
        return {
            "success": True,
            "code": "OK",
            "message": f"cognitive stitching runtime cleared ({reason})",
            "trace_id": trace_id,
            "data": result,
        }

    def reload_config(self, trace_id: str = "cs_reload", config_path: str | None = None) -> dict:
        path = config_path or self._config_path
        try:
            fresh = dict(_DEFAULT_CONFIG)
            fresh.update(_load_yaml_config(path))
            self._config = self._normalize_config(fresh)
            return {
                "success": True,
                "code": "OK",
                "message": "Cognitive stitching config reloaded",
                "trace_id": trace_id,
                "data": {"config": dict(self._config)},
            }
        except Exception as exc:
            return {
                "success": False,
                "code": "CONFIG_ERROR",
                "message": f"reload failed: {exc}",
                "trace_id": trace_id,
                "error": {"message": str(exc)},
            }

    def update_config(self, updates: dict[str, Any] | None = None, trace_id: str = "cs_update_config") -> dict:
        try:
            merged = dict(self._config)
            if isinstance(updates, dict):
                merged.update(updates)
            self._config = self._normalize_config(merged)
            return {
                "success": True,
                "code": "OK",
                "message": "Cognitive stitching config updated",
                "trace_id": trace_id,
                "data": {"config": dict(self._config)},
            }
        except Exception as exc:
            return {
                "success": False,
                "code": "CONFIG_ERROR",
                "message": f"update failed: {exc}",
                "trace_id": trace_id,
                "error": {"message": str(exc)},
            }

    def run(
        self,
        *,
        pool,
        hdb,
        attention_snapshot: dict | None = None,
        privileged_ref_ids: list[str] | set[str] | tuple[str, ...] | None = None,
        trace_id: str,
        tick_id: str,
    ) -> dict:
        start_time = time.time()
        try:
            self._current_candidate_audit = self._new_candidate_audit()
            self._decay_pair_fatigue()
            self._decay_object_stitch_fatigue()
            if not bool(self._config.get("enabled", False)):
                report = self._empty_report(enabled=False, reason="disabled")
                report["stitching_mode"] = self._stitching_mode()
                report["mode_flags"] = self._stitching_mode_flags()
                report["candidate_audit"]["stitching_mode"] = self._stitching_mode()
                report["candidate_audit"]["mode_flags"] = self._stitching_mode_flags()
                self._last_report = report
                self._current_candidate_audit = None
                self._current_apply_audit = None
                return self._make_response(
                    True,
                    "OK",
                    "cognitive stitching disabled",
                    report,
                    trace_id,
                    tick_id,
                    start_time,
                )

            # Event degeneration (component pruning) / 事件退化（组分淘汰）：
            # - Runs before snapshot so the rest of CS tick sees the updated pool state.
            # - Best-effort and bounded (never raising).
            degeneration = self._maybe_degenerate_events(
                pool=pool,
                hdb=hdb,
                trace_id=trace_id,
                tick_id=tick_id,
            )

            snapshot_top_k = int(self._config.get("snapshot_top_k", 24) or 0)
            snapshot_resp = pool.get_state_snapshot(
                trace_id=f"{trace_id}_cs_pre",
                tick_id=tick_id,
                top_k=None if snapshot_top_k <= 0 else snapshot_top_k,
                sort_by="cp_abs",
            )
            if not snapshot_resp.get("success"):
                report = self._empty_report(enabled=True, reason="snapshot_error")
                report["stitching_mode"] = self._stitching_mode()
                report["mode_flags"] = self._stitching_mode_flags()
                report["candidate_audit"]["stitching_mode"] = self._stitching_mode()
                report["candidate_audit"]["mode_flags"] = self._stitching_mode_flags()
                report["event_degeneration"] = degeneration
                self._last_report = report
                self._current_candidate_audit = None
                self._current_apply_audit = None
                return self._make_response(
                    False,
                    "STATE_SNAPSHOT_ERROR",
                    "state snapshot failed",
                    report,
                    trace_id,
                    tick_id,
                    start_time,
                )

            snapshot = snapshot_resp.get("data", {}).get("snapshot", {}) or {}
            attention_seed_ref_ids = self._collect_attention_seed_ref_ids(attention_snapshot or {})
            for raw_ref in list(privileged_ref_ids or []):
                ref = str(raw_ref or "").strip()
                if ref:
                    attention_seed_ref_ids.add(ref)
            active_items = self._collect_active_items(
                snapshot=snapshot,
                pool=pool,
                hdb=hdb,
                privileged_ref_ids=attention_seed_ref_ids,
            )
            candidates = self._build_candidates(active_items=active_items, hdb=hdb)
            candidates = self._rank_candidates(candidates)
            candidate_audit = self._finalize_candidate_audit(self._current_candidate_audit, candidates)
            actions = self._apply_candidates(
                candidates=candidates,
                pool=pool,
                hdb=hdb,
                trace_id=trace_id,
                tick_id=tick_id,
            )
            apply_audit = self._finalize_apply_audit(self._current_apply_audit, actions)
            event_grasp_resp = self.run_event_grasp(
                pool=pool,
                attention_snapshot=attention_snapshot or {},
                preferred_event_item_ids=[
                    str(item.get("event_item_id", "") or "").strip()
                    for item in actions
                    if isinstance(item, dict) and str(item.get("event_item_id", "") or "").strip()
                ],
                trace_id=trace_id,
                tick_id=tick_id,
            )
            event_grasp_report = dict(event_grasp_resp.get("data", {}) or {})
            event_grasp_report["success"] = bool(event_grasp_resp.get("success", False))
            event_grasp_report["code"] = str(event_grasp_resp.get("code", "") or "")
            event_grasp_report["message"] = str(event_grasp_resp.get("message", "") or "")
            event_grasp_report["elapsed_ms"] = int(event_grasp_resp.get("elapsed_ms", 0) or 0)
            narrative_top_items = self._collect_narrative_top_items(pool=pool, trace_id=trace_id, tick_id=tick_id)

            # ESDB lightweight runtime summary (bounded + cheap).
            esdb_event_count = len(self._esdb)
            esdb_materialized_event_count = 0
            esdb_delta_entry_total = 0
            for _eid, _entry in list(self._esdb.items()):
                if not isinstance(_entry, dict):
                    continue
                if bool(_entry.get("materialized", False)):
                    esdb_materialized_event_count += 1
                esdb_delta_entry_total += len(list(_entry.get("delta_diff_table", []) or []))

            report = {
                "enabled": True,
                "stage": "phase2_contextual_event_stitching",
                "stitching_mode": self._stitching_mode(),
                "mode_flags": self._stitching_mode_flags(),
                "reason": "ok",
                "seed_structure_count": len(active_items),
                "seed_plain_structure_count": sum(1 for item in active_items if item.get("kind") == "structure"),
                "seed_event_count": sum(1 for item in active_items if item.get("kind") == "event"),
                "candidate_count": len(candidates),
                "action_count": len(actions),
                "success_count": len(actions),
                "concat_count": sum(1 for item in actions if item.get("action_family") == "concat_context_structure" and not str(item.get("action", "")).startswith("reinforce_")),
                "created_count": sum(1 for item in actions if item.get("action_family") == "create_event" and not str(item.get("action", "")).startswith("reinforce_")),
                "extended_count": sum(1 for item in actions if item.get("action_family") == "extend_event" and not str(item.get("action", "")).startswith("reinforce_")),
                "merged_count": sum(1 for item in actions if item.get("action_family") == "merge_event" and not str(item.get("action", "")).startswith("reinforce_")),
                "reinforced_count": sum(1 for item in actions if str(item.get("action", "")).startswith("reinforce_")),
                "pair_fatigue_state_size": len(self._pair_fatigue),
                "object_stitch_fatigue_state_size": len(self._object_stitch_fatigue),
                "esdb_event_count": int(esdb_event_count),
                "esdb_materialized_event_count": int(esdb_materialized_event_count),
                "esdb_delta_entry_total": int(esdb_delta_entry_total),
                "candidate_audit": candidate_audit,
                "apply_audit": apply_audit,
                "candidate_preview": [self._candidate_preview(item) for item in candidates[:8]],
                "actions": actions,
                "action_log": [self._build_action_log_row(item) for item in actions if isinstance(item, dict)],
                "event_grasp": event_grasp_report,
                "narrative_top_items": narrative_top_items,
                "event_degeneration": degeneration,
                "throughput_mode": {
                    "snapshot_top_k": snapshot_top_k,
                    "max_seed_items": int(self._config.get("max_seed_items", 0) or 0),
                    "max_events_per_tick": int(self._config.get("max_events_per_tick", 0) or 0),
                    "context_concat_max_targets_per_seed": int(self._config.get("context_concat_max_targets_per_seed", 0) or 0),
                    "zero_means_unbounded": True,
                    "exact_context_index_enabled": True,
                },
            }
            self._last_report = report
            self._current_candidate_audit = None
            self._current_apply_audit = None
            return self._make_response(
                True,
                "OK",
                "cognitive stitching completed",
                report,
                trace_id,
                tick_id,
                start_time,
            )
        except Exception as exc:
            report = self._empty_report(enabled=bool(self._config.get("enabled", False)), reason="exception")
            report["stitching_mode"] = self._stitching_mode()
            report["mode_flags"] = self._stitching_mode_flags()
            report["candidate_audit"]["stitching_mode"] = self._stitching_mode()
            report["candidate_audit"]["mode_flags"] = self._stitching_mode_flags()
            report["error"] = {"message": str(exc)}
            self._last_report = report
            self._current_candidate_audit = None
            self._current_apply_audit = None
            return self._make_response(
                False,
                "CS_RUNTIME_ERROR",
                f"cognitive stitching failed: {exc}",
                report,
                trace_id,
                tick_id,
                start_time,
            )

    def run_event_grasp(
        self,
        *,
        pool,
        attention_snapshot: dict,
        preferred_event_item_ids: list[str] | None = None,
        trace_id: str,
        tick_id: str,
        reason: str = "event_grasp_tick",
    ) -> dict:
        """Emit "event_grasp" as runtime-bound numerical attribute on ES items in CAM.

        Design alignment: see cognitive_stitching/docs/认知拼接模块设计文档.md section 14.
        """
        start_time = time.time()
        try:
            if not bool(self._config.get("enable_event_grasp", True)):
                data = {
                    "enabled": False,
                    "reason": "disabled_by_config",
                    "signals": [],
                    "attribute_bindings": [],
                }
                return self._make_response(True, "OK_DISABLED", "event grasp disabled", data, trace_id, tick_id, start_time)

            if pool is None or not hasattr(pool, "bind_attribute_node_to_object"):
                data = {
                    "enabled": True,
                    "reason": "pool_missing_bind_attribute",
                    "signals": [],
                    "attribute_bindings": [],
                }
                return self._make_response(True, "OK_NOOP", "pool cannot bind attribute nodes", data, trace_id, tick_id, start_time)

            focus_meta = self._collect_event_grasp_focus_item_ids(
                attention_snapshot=attention_snapshot or {},
                preferred_event_item_ids=preferred_event_item_ids,
            )
            selected_item_ids = list(focus_meta.get("item_ids", []) or [])
            if not selected_item_ids:
                data = {
                    "enabled": True,
                    "reason": "no_event_focus_candidates",
                    "signals": [],
                    "attribute_bindings": [],
                    "focus_mode": str(focus_meta.get("focus_mode", "cam_only") or "cam_only"),
                    "focus_candidate_item_count": 0,
                    "cam_seed_count": int(focus_meta.get("cam_seed_count", 0) or 0),
                    "post_action_seed_count": int(focus_meta.get("post_action_seed_count", 0) or 0),
                }
                return self._make_response(True, "OK", "no event grasp emitted", data, trace_id, tick_id, start_time)

            min_total_energy = max(0.0, float(self._config.get("event_grasp_min_total_energy", 0.25)))
            max_events = max(1, int(self._config.get("event_grasp_max_events_per_tick", 4)))
            attr_name = str(self._config.get("event_grasp_attribute_name", "event_grasp") or "event_grasp").strip() or "event_grasp"
            post_action_threshold_scale = self._clamp01(
                float(self._config.get("event_grasp_post_action_threshold_scale", 0.75) or 0.75)
            )

            # Fetch live state items so grasp can reflect post-neutralization/post-absorption energies.
            live_events: list[dict[str, Any]] = []
            cam_event_count = 0
            post_action_event_count = 0
            focus_sources = dict(focus_meta.get("source_by_item_id", {}) or {})
            for item_id in selected_item_ids:
                state_item = self._get_state_item_by_id(pool=pool, item_id=item_id)
                if not isinstance(state_item, dict):
                    continue
                if not self._is_cognitive_stitching_event_state_item(state_item):
                    continue
                source_tags = list(focus_sources.get(item_id, []) or [])
                if "cam" in source_tags:
                    cam_event_count += 1
                if "post_cs_action" in source_tags:
                    post_action_event_count += 1
                ref_id = str(state_item.get("ref_object_id", "") or "")
                event_ref_id = self._extract_event_ref_id_from_state_item(state_item) or ref_id
                energy = dict(state_item.get("energy", {}) or {})
                er = max(0.0, float(energy.get("er", 0.0) or 0.0))
                ev = max(0.0, float(energy.get("ev", 0.0) or 0.0))
                total = round(er + ev, 8)
                effective_min_total_energy = min_total_energy
                if "post_cs_action" in source_tags and "cam" not in source_tags:
                    effective_min_total_energy = round(min_total_energy * post_action_threshold_scale, 8)
                if total < effective_min_total_energy:
                    continue
                live_events.append(
                    {
                        "item_id": item_id,
                        "ref_object_id": ref_id,
                        "event_ref_id": event_ref_id,
                        "display": str((state_item.get("ref_snapshot", {}) or {}).get("content_display", "") or ref_id),
                        "er": round(er, 8),
                        "ev": round(ev, 8),
                        "total_energy": total,
                        "effective_min_total_energy": effective_min_total_energy,
                        "selection_sources": source_tags,
                        "state_item": state_item,
                    }
                )

            if not live_events:
                if cam_event_count > 0 or post_action_event_count > 0:
                    reason_key = "below_energy_threshold"
                elif int(focus_meta.get("post_action_seed_count", 0) or 0) > 0:
                    reason_key = "no_cognitive_stitching_event_in_post_cs_focus"
                elif int(focus_meta.get("cam_seed_count", 0) or 0) > 0:
                    reason_key = "no_cognitive_stitching_event_in_cam"
                else:
                    reason_key = "no_cognitive_stitching_event_in_focus"
                data = {
                    "enabled": True,
                    "reason": reason_key,
                    "signals": [],
                    "attribute_bindings": [],
                    "focus_mode": str(focus_meta.get("focus_mode", "cam_only") or "cam_only"),
                    "focus_candidate_item_count": len(selected_item_ids),
                    "cam_seed_count": int(focus_meta.get("cam_seed_count", 0) or 0),
                    "post_action_seed_count": int(focus_meta.get("post_action_seed_count", 0) or 0),
                    "cam_selected_event_count": int(cam_event_count),
                    "post_action_selected_event_count": int(post_action_event_count),
                }
                return self._make_response(True, "OK", "no event grasp emitted", data, trace_id, tick_id, start_time)

            live_events.sort(key=lambda row: float(row.get("total_energy", 0.0)), reverse=True)
            live_events = live_events[:max_events]

            # Precompute runner-up energy for margin.
            totals = [float(row.get("total_energy", 0.0) or 0.0) for row in live_events]
            margin_by_item: dict[str, float] = {}
            for index, row in enumerate(live_events):
                score = float(row.get("total_energy", 0.0) or 0.0)
                runner = float(totals[index + 1]) if index + 1 < len(totals) else 0.0
                margin_by_item[str(row.get("item_id", "") or "")] = self._clamp01((score - runner) / max(abs(score), 1e-9))

            signals: list[dict[str, Any]] = []
            bindings: list[dict[str, Any]] = []
            for row in live_events:
                state_item = row.get("state_item")
                item_id = str(row.get("item_id", "") or "")
                ref_id = str(row.get("ref_object_id", "") or "")
                event_ref_id = str(row.get("event_ref_id", "") or ref_id)
                total = float(row.get("total_energy", 0.0) or 0.0)
                margin = float(margin_by_item.get(item_id, 0.0) or 0.0)
                balance = self._event_internal_balance_from_ledger(state_item)
                grasp = self._compute_event_grasp(total_energy=total, balance=balance, margin=margin)

                attr_sa = self._build_numerical_attribute_sa(
                    attribute_name=attr_name,
                    attribute_value=grasp,
                    target_item_id=item_id,
                    target_ref_object_id=ref_id,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    sub_type="event_grasp_attribute_presence",
                    display_prefix="事件把握感",
                )
                try:
                    bind_res = pool.bind_attribute_node_to_object(
                        target_item_id=item_id,
                        attribute_sa=attr_sa,
                        trace_id=f"{trace_id}_cs_event_grasp_bind",
                        tick_id=tick_id,
                        source_module="cognitive_stitching",
                        reason=reason,
                    )
                except Exception as exc:
                    bind_res = {"success": False, "code": "EXCEPTION", "message": str(exc)}

                signals.append(
                    {
                        "event_item_id": item_id,
                        "event_structure_id": ref_id,
                        "event_ref_id": event_ref_id,
                        "event_display": str(row.get("display", "") or ref_id),
                        "er": round(float(row.get("er", 0.0) or 0.0), 8),
                        "ev": round(float(row.get("ev", 0.0) or 0.0), 8),
                        "total_energy": round(total, 8),
                        "effective_min_total_energy": round(float(row.get("effective_min_total_energy", min_total_energy) or min_total_energy), 8),
                        "balance": round(balance, 8),
                        "margin": round(margin, 8),
                        "grasp": round(grasp, 8),
                        "selection_sources": list(row.get("selection_sources", []) or []),
                    }
                )
                bindings.append(
                    {
                        "event_item_id": item_id,
                        "attribute_sa_id": str(attr_sa.get("id", "") or ""),
                        "attribute_name": attr_name,
                        "attribute_value": round(grasp, 8),
                        "success": bool(bind_res.get("success", False)),
                        "code": str(bind_res.get("code", "") or ""),
                    }
                )

            data = {
                "enabled": True,
                "reason": "ok",
                "selected_event_count": len(live_events),
                "emitted_count": len(signals),
                "focus_mode": str(focus_meta.get("focus_mode", "cam_only") or "cam_only"),
                "focus_candidate_item_count": len(selected_item_ids),
                "cam_seed_count": int(focus_meta.get("cam_seed_count", 0) or 0),
                "post_action_seed_count": int(focus_meta.get("post_action_seed_count", 0) or 0),
                "cam_selected_event_count": int(cam_event_count),
                "post_action_selected_event_count": int(post_action_event_count),
                "signals": signals,
                "attribute_bindings": bindings,
            }
            return self._make_response(True, "OK", "event grasp emitted", data, trace_id, tick_id, start_time)
        except Exception as exc:
            data = {"enabled": True, "reason": "exception", "signals": [], "attribute_bindings": [], "error": {"message": str(exc)}}
            return self._make_response(False, "CS_EVENT_GRASP_ERROR", f"event grasp failed: {exc}", data, trace_id, tick_id, start_time)

    def idle_consolidate(
        self,
        *,
        hdb,
        trace_id: str,
        tick_id: str,
        reason: str = "idle_consolidation",
        max_events: int | None = None,
    ) -> dict:
        """Idle-time consolidation for CS runtime stores (ESDB overlay + cache release)."""
        start_time = time.time()
        try:
            if not bool(self._config.get("enable_esdb_overlay", True)):
                data = {"enabled": False, "reason": "disabled_by_config", "event_count": len(self._esdb)}
                return self._make_response(True, "OK_DISABLED", "esdb overlay disabled", data, trace_id, tick_id, start_time)

            now_ms = int(time.time() * 1000)
            before_event_count = len(self._esdb)
            before_depths = [self._esdb_parent_depth(event_id, set()) for event_id in list(self._esdb.keys())]
            before_avg_depth = round(sum(before_depths) / max(1, len(before_depths)), 6) if before_depths else 0.0
            before_max_depth = int(max(before_depths)) if before_depths else 0
            before_parent_count_total = 0
            before_delta_entry_total = 0
            before_materialized_event_count = 0
            before_materialized_entry_total = 0
            for _eid, _entry in list(self._esdb.items()):
                if not isinstance(_entry, dict):
                    continue
                before_parent_count_total += len(list(_entry.get("parents", []) or []))
                before_delta_entry_total += len(list(_entry.get("delta_diff_table", []) or []))
                if bool(_entry.get("materialized", False)):
                    before_materialized_event_count += 1
                    before_materialized_entry_total += len(list(_entry.get("materialized_diff_table", []) or []))

            # Optional cache release for all ES entries.
            clear_all_caches = bool(self._config.get("idle_consolidate_clear_all_caches", True))
            cache_bytes_per_row = int(self._config.get("idle_consolidate_cache_est_bytes_per_row", 220) or 220)
            cache_bytes_per_row = max(0, min(5000, cache_bytes_per_row))
            released_cache_event_count = 0
            released_cache_row_total = 0
            if clear_all_caches:
                for _eid, _entry in list(self._esdb.items()):
                    if not isinstance(_entry, dict):
                        continue
                    cache = _entry.get("runtime_cache")
                    if isinstance(cache, dict) and cache:
                        released_cache_event_count += 1
                        cached_rows = cache.get("overlay_cached_rows")
                        if isinstance(cached_rows, list):
                            released_cache_row_total += len(cached_rows)
                    _entry["runtime_cache"] = {}

            materialize_top_n = max(1, int(self._config.get("esdb_materialize_top_n", 96)))
            ids = list(self._esdb.keys())
            ids.sort(key=lambda eid: int((self._esdb.get(eid, {}) or {}).get("updated_at_ms", 0) or 0), reverse=True)
            # Guard: cap how many events we consolidate in one call.
            # Rationale: ES can grow large in long runs; consolidation must remain bounded.
            effective_max_events = max_events
            if effective_max_events is None:
                effective_max_events = self._config.get("idle_consolidate_max_events", 256)
            try:
                effective_max_events = int(effective_max_events) if effective_max_events is not None else None
            except Exception:
                effective_max_events = None
            if effective_max_events is not None:
                if int(effective_max_events) <= 0:
                    ids = []
                else:
                    ids = ids[: int(effective_max_events)]

            materialized_count = 0
            materialized_entry_total = 0
            for event_id in ids:
                entry = self._esdb.get(event_id)
                if not isinstance(entry, dict):
                    continue
                # Materialize overlay top-N (flatten parent chain) + clear runtime cache.
                diff_table = self._esdb_materialize_diff_table(event_ref_id=event_id, hdb=hdb, top_n=materialize_top_n)
                entry["materialized"] = True
                entry["materialized_diff_table"] = diff_table
                entry["parents_before_consolidation"] = list(entry.get("parents", []) or [])
                entry["parents"] = []
                entry["runtime_cache"] = {}
                entry["updated_at_ms"] = int(time.time() * 1000)
                materialized_count += 1
                materialized_entry_total += len(diff_table)

            # Optional: persist consolidated ES into HDB (disabled by default).
            persist_results: list[dict] = []
            if bool(self._config.get("enable_persist_events_to_hdb", False)) and hasattr(hdb, "upsert_cognitive_stitching_event_structure"):
                max_diff_entries = int(self._config.get("persist_events_max_diff_entries", 96) or 96)
                max_diff_entries = max(0, min(512, max_diff_entries))
                structure_store = getattr(hdb, "_structure_store", None)
                for event_id in ids:
                    entry = self._esdb.get(event_id)
                    if not isinstance(entry, dict):
                        continue
                    components = [str(x) for x in (entry.get("components", []) or []) if str(x)]
                    displays = self._resolve_component_displays(components=components, structure_store=structure_store) if structure_store is not None else []
                    if not displays:
                        displays = list(components)
                    display_text = self._event_display_from_components(displays)
                    diff_rows = list(entry.get("materialized_diff_table", []) or [])
                    try:
                        res = hdb.upsert_cognitive_stitching_event_structure(
                            event_ref_id=str(event_id),
                            member_refs=list(components),
                            display_text=str(display_text),
                            diff_rows=diff_rows,
                            trace_id=f"{trace_id}_cs_persist_event",
                            tick_id=tick_id,
                            reason=str(reason or ""),
                            max_diff_entries=int(max_diff_entries),
                        )
                    except Exception as exc:
                        res = {"success": False, "code": "EXCEPTION", "message": str(exc), "data": {"event_ref_id": str(event_id)}}
                    persist_results.append(
                        {
                            "event_ref_id": str(event_id),
                            "success": bool(res.get("success", False)),
                            "code": str(res.get("code", "") or ""),
                            "structure_id": str((res.get("data", {}) or {}).get("structure_id", "") or ""),
                            "created": bool((res.get("data", {}) or {}).get("created", False)),
                            "diff_upserted_count": int((res.get("data", {}) or {}).get("diff_upserted_count", 0) or 0),
                        }
                    )

            after_depths = [self._esdb_parent_depth(event_id, set()) for event_id in list(self._esdb.keys())]
            after_avg_depth = round(sum(after_depths) / max(1, len(after_depths)), 6) if after_depths else 0.0
            after_max_depth = int(max(after_depths)) if after_depths else 0
            after_parent_count_total = 0
            after_delta_entry_total = 0
            after_materialized_event_count = 0
            after_materialized_entry_total = 0
            for _eid, _entry in list(self._esdb.items()):
                if not isinstance(_entry, dict):
                    continue
                after_parent_count_total += len(list(_entry.get("parents", []) or []))
                after_delta_entry_total += len(list(_entry.get("delta_diff_table", []) or []))
                if bool(_entry.get("materialized", False)):
                    after_materialized_event_count += 1
                    after_materialized_entry_total += len(list(_entry.get("materialized_diff_table", []) or []))

            data = {
                "enabled": True,
                "reason": str(reason or ""),
                "timestamp_ms": int(now_ms),
                "event_count": int(before_event_count),
                "consolidated_event_count": int(materialized_count),
                "materialized_top_n": int(materialize_top_n),
                "materialized_diff_entry_total": int(materialized_entry_total),
                "avg_parent_depth_before": float(before_avg_depth),
                "avg_parent_depth_after": float(after_avg_depth),
                "max_parent_depth_before": int(before_max_depth),
                "max_parent_depth_after": int(after_max_depth),
                "parent_ref_total_before": int(before_parent_count_total),
                "parent_ref_total_after": int(after_parent_count_total),
                "delta_diff_entry_total_before": int(before_delta_entry_total),
                "delta_diff_entry_total_after": int(after_delta_entry_total),
                "materialized_event_count_before": int(before_materialized_event_count),
                "materialized_event_count_after": int(after_materialized_event_count),
                "materialized_entry_total_before": int(before_materialized_entry_total),
                "materialized_entry_total_after": int(after_materialized_entry_total),
                "persist_events_enabled": bool(self._config.get("enable_persist_events_to_hdb", False)),
                "persisted_event_count": int(sum(1 for r in persist_results if bool(r.get("success", False)))),
                "persist_results_preview": persist_results[: min(8, len(persist_results))],
                "idle_consolidate_clear_all_caches": bool(clear_all_caches),
                "released_cache_event_count": int(released_cache_event_count),
                "released_cache_row_total": int(released_cache_row_total),
                "released_cache_est_bytes": int(released_cache_row_total) * int(cache_bytes_per_row),
                "effective_max_events": int(effective_max_events) if effective_max_events is not None else None,
            }
            resp = self._make_response(True, "OK", "cognitive stitching idle consolidation completed", data, trace_id, tick_id, start_time)
            try:
                self._idle_consolidation_count_total = int(getattr(self, "_idle_consolidation_count_total", 0) or 0) + 1
                self._last_idle_consolidation = dict(resp)
            except Exception:
                pass
            return resp
        except Exception as exc:
            data = {"enabled": True, "reason": "exception", "error": {"message": str(exc)}}
            return self._make_response(False, "CS_IDLE_CONSOLIDATION_ERROR", f"idle consolidation failed: {exc}", data, trace_id, tick_id, start_time)

    def _build_config(self, config_override: dict | None = None) -> dict[str, Any]:
        config = dict(_DEFAULT_CONFIG)
        config.update(_load_yaml_config(self._config_path))
        if config_override:
            config.update(config_override)
        return self._normalize_config(config)

    @staticmethod
    def _normalize_config(config: dict[str, Any] | None) -> dict[str, Any]:
        normalized = dict(_DEFAULT_CONFIG)
        if isinstance(config, dict):
            normalized.update(config)
        allowed_modes = {"legacy_event", "context_match_v2", "hybrid_compare"}
        mode = str(normalized.get("stitching_mode", "legacy_event") or "legacy_event").strip().lower()
        if mode not in allowed_modes:
            mode = "legacy_event"
        normalized["stitching_mode"] = mode
        normalized["cs_v2_audit_only"] = bool(normalized.get("cs_v2_audit_only", True))
        normalized["context_concat_v2_enabled"] = bool(normalized.get("context_concat_v2_enabled", True))
        normalized["context_concat_soft_scan_when_exact_candidates_missing_only"] = bool(
            normalized.get("context_concat_soft_scan_when_exact_candidates_missing_only", True)
        )
        normalized["context_concat_soft_scan_privileged_only"] = bool(
            normalized.get("context_concat_soft_scan_privileged_only", True)
        )
        normalized["context_concat_soft_scan_max_sources_per_tick"] = max(
            0,
            int(normalized.get("context_concat_soft_scan_max_sources_per_tick", 32) or 0),
        )
        normalized["context_concat_soft_scan_max_targets_per_source"] = max(
            0,
            int(normalized.get("context_concat_soft_scan_max_targets_per_source", 48) or 0),
        )
        normalized["context_concat_project_non_st_support_sources_enabled"] = bool(
            normalized.get("context_concat_project_non_st_support_sources_enabled", True)
        )
        normalized["context_concat_profile_support_lookup_enabled"] = bool(
            normalized.get("context_concat_profile_support_lookup_enabled", True)
        )
        normalized["cs_v2_same_pair_fatigue_enabled"] = bool(normalized.get("cs_v2_same_pair_fatigue_enabled", True))
        normalized["object_stitch_fatigue_enabled"] = bool(normalized.get("object_stitch_fatigue_enabled", True))
        normalized["object_stitch_fatigue_apply_to_result"] = bool(normalized.get("object_stitch_fatigue_apply_to_result", True))
        normalized["context_concat_use_lower_energy_cap"] = bool(normalized.get("context_concat_use_lower_energy_cap", True))
        return normalized

    def _stitching_mode(self) -> str:
        return str(self._config.get("stitching_mode", "legacy_event") or "legacy_event").strip().lower() or "legacy_event"

    def _stitching_mode_flags(self) -> dict[str, Any]:
        mode = self._stitching_mode()
        use_v2_execution = self._uses_v2_execution()
        return {
            "legacy_event_active": mode == "legacy_event",
            "context_match_v2_active": mode == "context_match_v2",
            "hybrid_compare_active": mode == "hybrid_compare",
            "context_concat_v2_enabled": bool(self._config.get("context_concat_v2_enabled", True)),
            "context_match_v2_audit_only": bool(self._config.get("cs_v2_audit_only", True)),
            "execution_uses_legacy_score": not use_v2_execution,
            "execution_uses_v2_score": use_v2_execution,
            "v2_score_exposed": True,
        }

    def _uses_v2_execution(self) -> bool:
        return self._stitching_mode() == "context_match_v2" and not bool(self._config.get("cs_v2_audit_only", True))

    def _context_concat_enabled_for_candidates(self) -> bool:
        return bool(self._config.get("context_concat_v2_enabled", True)) and self._stitching_mode() in {
            "context_match_v2",
            "hybrid_compare",
        }

    @staticmethod
    def _dedupe_ids(values: Any) -> list[str]:
        if values is None:
            return []
        if isinstance(values, (list, tuple, set)):
            raw_values = list(values)
        else:
            raw_values = [values]
        out: list[str] = []
        seen: set[str] = set()
        for raw in raw_values:
            text = str(raw or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
        return out

    def _select_execution_score_bundle(
        self,
        *,
        legacy_score: float,
        legacy_base_score: float,
        legacy_min_candidate_score: float,
        legacy_threshold_margin: float,
        v2_breakdown: dict[str, Any],
    ) -> dict[str, Any]:
        use_v2_execution = self._uses_v2_execution()
        if use_v2_execution:
            execution_score = round(float(v2_breakdown.get("v2_score", 0.0) or 0.0), 8)
            execution_base_score = round(float(v2_breakdown.get("v2_base_score", 0.0) or 0.0), 8)
            execution_min_candidate_score = round(float(v2_breakdown.get("v2_min_match_score", 0.0) or 0.0), 8)
            execution_threshold_margin = round(float(v2_breakdown.get("v2_threshold_margin", 0.0) or 0.0), 8)
            rejection_reason = "below_v2_min_match_score"
            score_source = "v2"
        else:
            execution_score = round(float(legacy_score), 8)
            execution_base_score = round(float(legacy_base_score), 8)
            execution_min_candidate_score = round(float(legacy_min_candidate_score), 8)
            execution_threshold_margin = round(float(legacy_threshold_margin), 8)
            rejection_reason = "below_min_candidate_score"
            score_source = "legacy"
        return {
            "score": execution_score,
            "base_score": execution_base_score,
            "min_candidate_score": execution_min_candidate_score,
            "threshold_margin": execution_threshold_margin,
            "score_source": score_source,
            "execution_uses_v2_score": use_v2_execution,
            "rejection_reason": rejection_reason,
        }

    def _decay_pair_fatigue(self) -> None:
        decay = max(0.0, min(1.0, float(self._config.get("same_pair_fatigue_decay", 0.72))))
        retained: dict[str, float] = {}
        for key, value in self._pair_fatigue.items():
            next_value = round(max(0.0, float(value) * decay), 8)
            if next_value > 1e-6:
                retained[key] = next_value
        self._pair_fatigue = retained

    def _decay_object_stitch_fatigue(self) -> None:
        if not bool(self._config.get("object_stitch_fatigue_enabled", True)):
            self._object_stitch_fatigue.clear()
            return
        decay = max(0.0, min(1.0, float(self._config.get("object_stitch_fatigue_decay", 0.90))))
        retained: dict[str, float] = {}
        for key, value in self._object_stitch_fatigue.items():
            next_value = round(max(0.0, float(value) * decay), 8)
            if next_value > 1e-6:
                retained[key] = next_value
        self._object_stitch_fatigue = retained

    @staticmethod
    def _collect_attention_seed_ref_ids(attention_snapshot: dict) -> set[str]:
        refs: set[str] = set()
        for item in list((attention_snapshot or {}).get("top_items", []) or []):
            if str(item.get("ref_object_type", "") or "") != "st":
                continue
            ref_id = str(item.get("ref_object_id", "") or "").strip()
            if ref_id:
                refs.add(ref_id)
        return refs

    def _collect_active_items(self, *, snapshot: dict, pool, hdb, privileged_ref_ids: set[str] | None = None) -> list[dict]:
        items = list(snapshot.get("top_items", []) or [])
        structure_store = getattr(hdb, "_structure_store", None)
        if structure_store is None:
            return []

        prefix = str(self._config.get("event_id_prefix", "cs_event"))
        min_total_energy = max(0.0, float(self._config.get("min_seed_total_energy", 0.45)))
        privileged_refs = {str(ref).strip() for ref in list(privileged_ref_ids or set()) if str(ref).strip()}
        active: list[dict] = []
        for order_index, item in enumerate(items):
            original_ref_object_type = str(item.get("ref_object_type", "") or "").strip()
            ref_id = str(item.get("ref_object_id", "") or "").strip()
            if not ref_id:
                continue

            er = round(max(0.0, float(item.get("er", 0.0) or 0.0)), 8)
            ev = round(max(0.0, float(item.get("ev", 0.0) or 0.0)), 8)
            total_energy = round(er + ev, 8)

            support_projection = self._resolve_non_st_support_projection(
                snapshot_item=item,
                pool=pool,
                hdb=hdb,
            )
            projection_ref_id = str((support_projection or {}).get("support_structure_id", "") or "").strip()
            effective_ref_id = ref_id
            effective_ref_object_type = original_ref_object_type
            if original_ref_object_type != "st":
                if not projection_ref_id:
                    continue
                effective_ref_id = projection_ref_id
                effective_ref_object_type = "st"

            attention_seed = ref_id in privileged_refs or effective_ref_id in privileged_refs
            if total_energy < min_total_energy and not attention_seed:
                continue

            structure_obj = None
            try:
                structure_obj = structure_store.get(effective_ref_id)
            except Exception:
                structure_obj = None

            if isinstance(structure_obj, dict) and self._is_cognitive_stitching_event_structure_obj(structure_obj):
                event_item = self._build_active_event_item(
                    item_id=str(item.get("item_id", "") or ""),
                    ref_id=effective_ref_id,
                    display=str(item.get("display", "") or ""),
                    er=er,
                    ev=ev,
                    total_energy=total_energy,
                    order_index=order_index,
                    structure_store=structure_store,
                    structure_obj=structure_obj,
                )
                if event_item:
                    event_item["attention_seed"] = attention_seed
                    if support_projection:
                        event_item.update(support_projection)
                        event_item["runtime_ref_object_id"] = ref_id
                        event_item["runtime_ref_object_type"] = original_ref_object_type
                    active.append(event_item)
                continue

            if effective_ref_id.startswith(f"{prefix}::"):
                event_item = self._build_active_event_item(
                    item_id=str(item.get("item_id", "") or ""),
                    ref_id=effective_ref_id,
                    display=str(item.get("display", "") or effective_ref_id),
                    er=er,
                    ev=ev,
                    total_energy=total_energy,
                    order_index=order_index,
                    structure_store=structure_store,
                    structure_obj=None,
                )
                if event_item:
                    event_item["attention_seed"] = attention_seed
                    if support_projection:
                        event_item.update(support_projection)
                        event_item["runtime_ref_object_id"] = ref_id
                        event_item["runtime_ref_object_type"] = original_ref_object_type
                    active.append(event_item)
                continue

            if not isinstance(structure_obj, dict):
                continue

            ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
            state_item = self._get_state_item_by_id(pool=pool, item_id=str(item.get("item_id", "") or ""))
            structure_block = structure_obj.get("structure", {}) if isinstance(structure_obj.get("structure", {}), dict) else {}
            structure_ext = structure_block.get("ext", {}) if isinstance(structure_block.get("ext", {}), dict) else {}
            display = self._structure_display(structure_obj) or str(item.get("display", "") or effective_ref_id)
            tokens = list(structure_block.get("flat_tokens", []) or [])
            if not tokens:
                tokens = [display]
            context_ref_object_id = str(
                item.get("context_ref_object_id", "")
                or ref_snapshot.get("context_ref_object_id", "")
                or structure_ext.get("context_ref_object_id", "")
                or ""
            )
            context_owner_id = str(
                item.get("context_owner_id", "")
                or ref_snapshot.get("context_owner_id", "")
                or structure_ext.get("context_owner_structure_id", "")
                or ""
            )
            context_path_ids = self._dedupe_ids(
                item.get("context_path_ids", [])
                or ref_snapshot.get("context_path_ids", [])
                or structure_ext.get("context_path_ids", [])
                or []
            )
            context_text = str(
                item.get("context_text", "")
                or ref_snapshot.get("context_text", "")
                or structure_ext.get("context_text", "")
                or ""
            )
            attribute_descriptors = self._extract_item_attribute_descriptors(
                snapshot_item=item,
                state_item=state_item,
                structure_obj=structure_obj,
            )
            attribute_displays = self._dedupe_strings(
                list(item.get("attribute_displays", []) or [])
                + list(ref_snapshot.get("attribute_displays", []) or [])
                + [str(row.get("display", "") or "") for row in attribute_descriptors if str(row.get("display", "") or "")]
            )
            attribute_anchor_ref_ids = self._dedupe_ids(
                [
                    str(row.get("anchor_ref_object_id", "") or "")
                    for row in attribute_descriptors
                    if str(row.get("anchor_ref_object_id", "") or "")
                ]
            )
            attribute_anchor_displays = self._dedupe_strings(
                [str(row.get("anchor_display", "") or "") for row in attribute_descriptors if str(row.get("anchor_display", "") or "")]
            )
            runtime_weight = self._runtime_weight(hdb=hdb, structure_obj=structure_obj)
            active.append(
                {
                    "kind": "structure",
                    "item_id": str(item.get("item_id", "") or ""),
                    "ref_object_id": effective_ref_id,
                    "display": display,
                    "tokens": tokens,
                    "components": [effective_ref_id],
                    "component_displays": [display],
                    "structure_obj": structure_obj,
                    "sequence_groups": list(structure_block.get("sequence_groups", []) or []),
                    "er": er,
                    "ev": ev,
                    "total_energy": total_energy,
                    "runtime_weight": runtime_weight,
                    "balance_energy": total_energy,
                    "balance_weight": runtime_weight,
                    "order_index": order_index,
                    "created_at": int(item.get("created_at", 0) or 0),
                    "cp_abs": round(abs(er - ev), 8),
                    "semantic_context_key": str(item.get("semantic_context_key", "") or ""),
                    "attention_seed": attention_seed,
                    "context_ref_object_id": context_ref_object_id,
                    "context_owner_id": context_owner_id,
                    "context_path_ids": context_path_ids,
                    "context_text": context_text,
                    "attribute_descriptors": attribute_descriptors,
                    "attribute_displays": attribute_displays,
                    "attribute_anchor_ref_ids": attribute_anchor_ref_ids,
                    "attribute_anchor_displays": attribute_anchor_displays,
                    "source_em_id": str(item.get("source_em_id", "") or ref_snapshot.get("source_em_id", "") or ""),
                    "residual_kind": str(item.get("residual_kind", "") or ref_snapshot.get("residual_kind", "") or ""),
                    "runtime_ref_object_id": ref_id,
                    "runtime_ref_object_type": original_ref_object_type,
                    "effective_ref_object_type": effective_ref_object_type,
                    **(support_projection or {}),
                }
            )

        active.sort(
            key=lambda item: (
                1 if bool(item.get("attention_seed", False)) else 0,
                float(item.get("total_energy", 0.0)),
                float(item.get("runtime_weight", 0.0)),
                -int(item.get("order_index", 0)),
            ),
            reverse=True,
        )
        max_seed_items = int(self._config.get("max_seed_items", 0) or 0)
        if max_seed_items <= 0:
            return active
        return active[: max(1, max_seed_items * 3)]

    def _resolve_non_st_support_projection(self, *, snapshot_item: dict, pool, hdb) -> dict | None:
        """Project an active non-ST runtime item onto its HDB support ST for CS matching.

        The runtime item keeps its own item_id and energy debit target. Only the
        matching identity is borrowed from a known HDB-backed support structure,
        so a high-energy single SA can stitch with the residual ST it just
        induced without turning runtime-only residual packages into HDB sources.
        """
        if not bool(self._config.get("context_concat_project_non_st_support_sources_enabled", True)):
            return None
        if not isinstance(snapshot_item, dict):
            return None
        if str(snapshot_item.get("ref_object_type", "") or "").strip() == "st":
            return None
        if self._is_runtime_only_residual_snapshot_item(snapshot_item):
            return None

        structure_store = getattr(hdb, "_structure_store", None)
        if structure_store is None:
            return None

        state_item = self._get_state_item_by_id(pool=pool, item_id=str(snapshot_item.get("item_id", "") or ""))
        if self._is_runtime_only_residual_snapshot_item(state_item or {}):
            return None

        support_ids = self._collect_support_structure_ids_from_runtime_item(
            snapshot_item=snapshot_item,
            state_item=state_item,
            structure_store=structure_store,
        )
        if not support_ids:
            resolved_id = self._resolve_support_structure_id_by_profile(
                snapshot_item=snapshot_item,
                state_item=state_item,
                hdb=hdb,
            )
            if resolved_id:
                support_ids = [resolved_id]
        if not support_ids:
            return None

        support_id = support_ids[0]
        support_obj = structure_store.get(support_id) if hasattr(structure_store, "get") else None
        if not isinstance(support_obj, dict):
            return None
        if self._is_cognitive_stitching_event_structure_obj(support_obj):
            return None

        return {
            "projected_from_non_st_support": True,
            "support_structure_id": support_id,
            "support_structure_ids": list(support_ids),
            "runtime_semantic_context_key": str(snapshot_item.get("semantic_context_key", "") or ""),
            "runtime_ref_object_id": str(snapshot_item.get("ref_object_id", "") or ""),
            "runtime_ref_object_type": str(snapshot_item.get("ref_object_type", "") or ""),
        }

    def _resolve_support_structure_id_by_profile(
        self,
        *,
        snapshot_item: dict,
        state_item: dict | None,
        hdb,
    ) -> str:
        """Resolve a non-ST runtime item to its exact HDB ST by content.

        Stimulus-level retrieval/induction can use a runtime SA as an HDB
        source after resolving its feature profile. CS needs the same bridge so
        the source SA can stitch with the residual ST it just induced, while the
        state-pool energy debit still targets the original runtime item.
        """
        if not bool(self._config.get("context_concat_profile_support_lookup_enabled", True)):
            return ""

        structure_store = getattr(hdb, "_structure_store", None)
        pointer_index = getattr(hdb, "_pointer_index", None)
        cut_engine = getattr(hdb, "_cut", None)
        if structure_store is None or pointer_index is None or cut_engine is None:
            return ""

        profile = self._build_runtime_support_profile_for_item(
            snapshot_item=snapshot_item,
            state_item=state_item,
            cut_engine=cut_engine,
        )
        signature = str(profile.get("content_signature", "") or "").strip()
        if not signature:
            return ""

        expected_context = self._expected_context_from_runtime_item(snapshot_item=snapshot_item, state_item=state_item)
        lookup_revision = int(getattr(structure_store, "structure_lookup_revision", 0) or 0)
        cache_key = (
            lookup_revision,
            signature,
            tuple(str(token) for token in list(profile.get("flat_tokens", []) or [])),
            str(expected_context.get("context_owner_structure_id", "") or ""),
            str(expected_context.get("context_ref_object_id", "") or ""),
            str(expected_context.get("context_ref_object_type", "") or ""),
        )
        if cache_key in self._support_projection_cache:
            return str(self._support_projection_cache.get(cache_key, "") or "")

        try:
            structure_obj = find_exact_structure_by_signature(
                signature=signature,
                structure_store=structure_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
                expected_tokens=list(profile.get("flat_tokens", []) or []),
                expected_sequence_groups=list(profile.get("sequence_groups", []) or []),
                expected_context=expected_context,
                strict_context_owner_match=bool(expected_context.get("context_owner_structure_id", "")),
                strict_context_ref_match=False,
            )
        except Exception:
            structure_obj = None
        resolved_id = str(structure_obj.get("id", "") or "") if isinstance(structure_obj, dict) else ""
        if resolved_id:
            self._support_projection_cache[cache_key] = resolved_id
        elif len(self._support_projection_cache) < 4096:
            self._support_projection_cache[cache_key] = ""
        return resolved_id

    def _build_runtime_support_profile_for_item(self, *, snapshot_item: dict, state_item: dict | None, cut_engine) -> dict:
        ref_snapshot = snapshot_item.get("ref_snapshot", {}) if isinstance(snapshot_item.get("ref_snapshot", {}), dict) else {}
        state_snapshot = (state_item or {}).get("ref_snapshot", {}) if isinstance((state_item or {}).get("ref_snapshot", {}), dict) else {}
        sequence_groups = list(ref_snapshot.get("sequence_groups", []) or state_snapshot.get("sequence_groups", []) or [])
        if sequence_groups and hasattr(cut_engine, "build_sequence_profile_from_groups"):
            profile = cut_engine.build_sequence_profile_from_groups(sequence_groups)
            display = str(
                snapshot_item.get("display", "")
                or ref_snapshot.get("content_display", "")
                or state_snapshot.get("content_display", "")
                or ""
            ).strip()
            if display:
                profile["display_text"] = display
            if not str(profile.get("content_signature", "") or ""):
                tokens = [str(token) for token in list(profile.get("flat_tokens", []) or []) if str(token)]
                if hasattr(cut_engine, "tokens_to_signature"):
                    profile["content_signature"] = cut_engine.tokens_to_signature(tokens)
            return profile

        flat_tokens = [
            str(token)
            for token in list(ref_snapshot.get("flat_tokens", []) or state_snapshot.get("flat_tokens", []) or [])
            if str(token)
        ]
        if not flat_tokens:
            display = str(
                snapshot_item.get("display", "")
                or ref_snapshot.get("content_display", "")
                or state_snapshot.get("content_display", "")
                or snapshot_item.get("ref_object_id", "")
                or ""
            ).strip()
            if display:
                flat_tokens = [ch for ch in display if str(ch).strip()]
        if not flat_tokens:
            return {}
        groups = [{"group_index": 0, "source_type": "runtime", "tokens": list(flat_tokens)}]
        if hasattr(cut_engine, "build_sequence_profile_from_groups"):
            profile = cut_engine.build_sequence_profile_from_groups(groups)
        else:
            signature = "|".join(flat_tokens)
            profile = {
                "display_text": "".join(flat_tokens),
                "sequence_groups": groups,
                "flat_tokens": list(flat_tokens),
                "content_signature": signature,
                "semantic_signature": signature,
            }
        if not str(profile.get("content_signature", "") or "") and hasattr(cut_engine, "tokens_to_signature"):
            profile["content_signature"] = cut_engine.tokens_to_signature(flat_tokens)
        return profile

    @staticmethod
    def _expected_context_from_runtime_item(*, snapshot_item: dict, state_item: dict | None) -> dict:
        carriers: list[dict] = []
        for candidate in (snapshot_item, state_item or {}):
            if not isinstance(candidate, dict):
                continue
            carriers.append(candidate)
            ref_snapshot = candidate.get("ref_snapshot", {}) if isinstance(candidate.get("ref_snapshot", {}), dict) else {}
            if ref_snapshot:
                carriers.append(ref_snapshot)
            source = candidate.get("source", {}) if isinstance(candidate.get("source", {}), dict) else {}
            if source:
                carriers.append(source)
            ext = candidate.get("ext", {}) if isinstance(candidate.get("ext", {}), dict) else {}
            if ext:
                carriers.append(ext)
        owner_id = ""
        ref_id = ""
        ref_type = ""
        for carrier in carriers:
            if not owner_id:
                owner_id = str(
                    carrier.get("context_owner_structure_id", "")
                    or carrier.get("context_owner_id", "")
                    or ""
                ).strip()
            if not ref_id:
                ref_id = str(carrier.get("context_ref_object_id", "") or "").strip()
            if not ref_type:
                ref_type = str(carrier.get("context_ref_object_type", "") or "").strip()
        context: dict[str, str] = {}
        if owner_id:
            context["context_owner_structure_id"] = owner_id
        if ref_id:
            context["context_ref_object_id"] = ref_id
        if ref_type:
            context["context_ref_object_type"] = ref_type
        return context

    def _collect_support_structure_ids_from_runtime_item(
        self,
        *,
        snapshot_item: dict,
        state_item: dict | None,
        structure_store,
    ) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()

        def _push(raw_id: Any) -> None:
            structure_id = str(raw_id or "").strip()
            if not structure_id or structure_id in seen:
                return
            try:
                structure_obj = structure_store.get(structure_id)
            except Exception:
                structure_obj = None
            if not isinstance(structure_obj, dict):
                return
            if self._is_cognitive_stitching_event_structure_obj(structure_obj):
                return
            seen.add(structure_id)
            ordered.append(structure_id)

        def _push_many(values: Any) -> None:
            if isinstance(values, (list, tuple, set)):
                for value in list(values):
                    _push(value)
            else:
                _push(values)

        carriers: list[dict] = []
        for candidate in (snapshot_item, state_item or {}):
            if isinstance(candidate, dict):
                carriers.append(candidate)
                ref_snapshot = candidate.get("ref_snapshot", {}) if isinstance(candidate.get("ref_snapshot", {}), dict) else {}
                if ref_snapshot:
                    carriers.append(ref_snapshot)
                source = candidate.get("source", {}) if isinstance(candidate.get("source", {}), dict) else {}
                if source:
                    carriers.append(source)
                ext = candidate.get("ext", {}) if isinstance(candidate.get("ext", {}), dict) else {}
                if ext:
                    carriers.append(ext)

        for carrier in carriers:
            _push_many(carrier.get("induction_source_support_structure_ids", []))
            _push(carrier.get("backing_structure_id", ""))
            _push_many(carrier.get("structure_refs", []))
            _push_many(carrier.get("required_structure_ids", []))
            _push_many(carrier.get("bias_structure_ids", []))
            _push_many(carrier.get("ref_alias_ids", []))
            _push_many(carrier.get("parent_ids", []))

        return ordered

    @staticmethod
    def _is_runtime_only_residual_snapshot_item(item: dict | None) -> bool:
        if not isinstance(item, dict):
            return False
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        structure_ext = ref_snapshot.get("structure_ext", {}) if isinstance(ref_snapshot.get("structure_ext", {}), dict) else {}
        meta = item.get("meta", {}) if isinstance(item.get("meta", {}), dict) else {}
        meta_ext = meta.get("ext", {}) if isinstance(meta.get("ext", {}), dict) else {}
        ext = item.get("ext", {}) if isinstance(item.get("ext", {}), dict) else {}
        source = item.get("source", {}) if isinstance(item.get("source", {}), dict) else {}
        for container in (structure_ext, meta_ext, ext, source, item):
            if not isinstance(container, dict):
                continue
            if bool(container.get("runtime_only_residual", False)):
                return True
            if container.get("hdb_backed", None) is False:
                return True
        return str(source.get("origin", "") or "") == "stimulus_runtime_residual_package"

    @staticmethod
    def _dedupe_strings(values: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for raw in list(values or []):
            value = str(raw or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out

    def _extract_item_attribute_descriptors(
        self,
        *,
        snapshot_item: dict,
        state_item: dict | None,
        structure_obj: dict | None,
    ) -> list[dict]:
        ref_snapshot = snapshot_item.get("ref_snapshot", {}) if isinstance(snapshot_item.get("ref_snapshot", {}), dict) else {}
        structure_block = structure_obj.get("structure", {}) if isinstance((structure_obj or {}).get("structure", {}), dict) else {}
        structure_ext = structure_block.get("ext", {}) if isinstance(structure_block.get("ext", {}), dict) else {}
        current_ref_id = str(
            snapshot_item.get("ref_object_id", "")
            or (state_item or {}).get("ref_object_id", "")
            or (structure_obj or {}).get("id", "")
            or ""
        ).strip()
        current_display = str(
            snapshot_item.get("display", "")
            or ref_snapshot.get("content_display", "")
            or self._structure_display(structure_obj or {})
            or current_ref_id
        ).strip()
        descriptors: list[dict] = []
        seen: set[tuple[str, str, str, str, str]] = set()

        def _append_descriptor(
            *,
            attribute_name: str,
            attribute_value: Any,
            display: str,
            source_kind: str,
            anchor_ref_object_id: str = "",
            anchor_display: str = "",
        ) -> None:
            name = str(attribute_name or "").strip()
            value_text = "" if attribute_value is None else str(attribute_value).strip()
            display_text = str(display or value_text or name).strip()
            anchor_ref = str(anchor_ref_object_id or current_ref_id).strip()
            anchor_text = str(anchor_display or current_display or anchor_ref).strip()
            if not name and not display_text:
                return
            key = (str(source_kind or "unknown"), name, value_text, anchor_ref, display_text)
            if key in seen:
                return
            seen.add(key)
            descriptors.append(
                {
                    "attribute_name": name,
                    "attribute_value": attribute_value,
                    "display": display_text,
                    "source_kind": str(source_kind or "unknown"),
                    "anchor_ref_object_id": anchor_ref,
                    "anchor_display": anchor_text,
                }
            )

        packet_carriers: list[dict] = []
        if isinstance((state_item or {}).get("binding_state", {}), dict):
            packet_carriers.append((state_item or {}).get("binding_state", {}))
        if isinstance(snapshot_item.get("binding_state", {}), dict):
            packet_carriers.append(snapshot_item.get("binding_state", {}))
        if isinstance(structure_ext.get("packet_attribute_by_name", {}), dict):
            packet_carriers.append({"packet_attribute_by_name": structure_ext.get("packet_attribute_by_name", {})})

        for carrier in packet_carriers:
            packet_map = carrier.get("packet_attribute_by_name", {}) if isinstance(carrier.get("packet_attribute_by_name", {}), dict) else {}
            for raw_name, raw_row in packet_map.items():
                row = raw_row if isinstance(raw_row, dict) else {}
                _append_descriptor(
                    attribute_name=str(row.get("attribute_name", "") or raw_name),
                    attribute_value=row.get("attribute_value"),
                    display=str(row.get("display", "") or row.get("raw", "") or raw_name),
                    source_kind="packet",
                    anchor_ref_object_id=current_ref_id,
                    anchor_display=current_display,
                )

        runtime_units: list[dict] = []
        if isinstance((state_item or {}).get("ext", {}), dict):
            runtime_units.extend(
                [row for row in list((state_item or {}).get("ext", {}).get("bound_attributes", []) or []) if isinstance(row, dict)]
            )
        runtime_units.extend([row for row in list(snapshot_item.get("runtime_bound_attribute_units", []) or []) if isinstance(row, dict)])
        runtime_units.extend([row for row in list(ref_snapshot.get("runtime_bound_attribute_units", []) or []) if isinstance(row, dict)])

        for row in runtime_units:
            content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else row
            meta = row.get("meta", {}) if isinstance(row.get("meta", {}), dict) else {}
            meta_ext = meta.get("ext", {}) if isinstance(meta.get("ext", {}), dict) else row.get("ext", {}) if isinstance(row.get("ext", {}), dict) else {}
            _append_descriptor(
                attribute_name=str(content.get("attribute_name", "") or row.get("attribute_name", "") or ""),
                attribute_value=content.get("attribute_value", row.get("attribute_value")),
                display=str(
                    content.get("display", "")
                    or row.get("display", "")
                    or row.get("display_text", "")
                    or content.get("raw", "")
                    or row.get("id", "")
                ),
                source_kind="runtime",
                anchor_ref_object_id=str(meta_ext.get("bound_anchor_ref_object_id", "") or row.get("bound_anchor_ref_object_id", "") or current_ref_id),
                anchor_display=str(meta_ext.get("bound_anchor_display", "") or row.get("bound_anchor_display", "") or current_display),
            )

        return descriptors

    def _build_active_event_item(
        self,
        *,
        item_id: str,
        ref_id: str,
        display: str,
        er: float,
        ev: float,
        total_energy: float,
        order_index: int,
        structure_store,
        structure_obj: dict | None,
    ) -> dict | None:
        if isinstance(structure_obj, dict):
            structure_block = structure_obj.get("structure", {}) if isinstance(structure_obj.get("structure", {}), dict) else {}
            components = [str(x) for x in (structure_block.get("member_refs", []) or []) if str(x)]
            components = list(dict.fromkeys(components))
            if len(components) >= 2:
                event_ref_id = str(structure_block.get("content_signature", "") or "").strip()
                if not event_ref_id:
                    ext = structure_block.get("ext", {}) if isinstance(structure_block.get("ext", {}), dict) else {}
                    cs_meta = ext.get("cognitive_stitching", {}) if isinstance(ext.get("cognitive_stitching", {}), dict) else {}
                    event_ref_id = str(cs_meta.get("event_ref_id", "") or cs_meta.get("cs_event_ref_id", "") or "").strip()
                component_displays = self._resolve_component_displays(components=components, structure_store=structure_store)
                if not component_displays:
                    component_displays = list(components)
                runtime_weight = round(max(total_energy, er, ev, 0.01), 8)
                balance_divisor = max(1.0, math.sqrt(float(len(components))))
                return {
                    "kind": "event",
                    "item_id": str(item_id or ""),
                    "ref_object_id": str(structure_obj.get("id", "") or ref_id),
                    "event_ref_id": event_ref_id,
                    "display": str(structure_block.get("display_text", "") or display or self._event_display_from_components(component_displays)),
                    "tokens": list(component_displays),
                    "components": list(components),
                    "component_displays": list(component_displays),
                    "structure_obj": structure_obj,
                    "er": er,
                    "ev": ev,
                    "total_energy": total_energy,
                    "runtime_weight": runtime_weight,
                    "balance_energy": round(total_energy / balance_divisor, 8),
                    "balance_weight": round(runtime_weight / balance_divisor, 8),
                    "order_index": order_index,
                }

        # Legacy runtime-only event (ref_id itself is the event_ref_id).
        components = self._parse_event_components(ref_id)
        if len(components) < 2:
            return None
        component_displays = self._resolve_component_displays(components=components, structure_store=structure_store)
        if not component_displays:
            component_displays = list(components)
        runtime_weight = round(max(total_energy, er, ev, 0.01), 8)
        balance_divisor = max(1.0, math.sqrt(float(len(components))))
        return {
            "kind": "event",
            "item_id": str(item_id or ""),
            "ref_object_id": ref_id,
            "event_ref_id": ref_id,
            "display": display or self._event_display_from_components(component_displays),
            "tokens": list(component_displays),
            "components": list(components),
            "component_displays": list(component_displays),
            "structure_obj": None,
            "er": er,
            "ev": ev,
            "total_energy": total_energy,
            "runtime_weight": runtime_weight,
            "balance_energy": round(total_energy / balance_divisor, 8),
            "balance_weight": round(runtime_weight / balance_divisor, 8),
            "order_index": order_index,
        }

    def _build_candidates(self, *, active_items: list[dict], hdb) -> list[dict]:
        if not active_items:
            return []
        structure_store = getattr(hdb, "_structure_store", None)
        if structure_store is None:
            return []
        self._soft_scan_source_count_this_tick = 0

        max_seed_items = int(self._config.get("max_seed_items", 0) or 0)
        best_by_signature: dict[str, dict] = {}
        active_by_ref = {
            str(item.get("ref_object_id", "")): item
            for item in active_items
            if str(item.get("ref_object_id", ""))
        }
        exact_context_index: dict[str, list[dict]] = {}
        if self._context_concat_enabled_for_candidates():
            self._prepare_context_concat_active_items(active_items=active_items, hdb=hdb)
            exact_context_index = self._build_context_concat_exact_index(active_items=active_items)
            self._record_candidate_scan_index(
                active_items=active_items,
                exact_context_index=exact_context_index,
            )

        seed_items = active_items if max_seed_items <= 0 else active_items[:max_seed_items]
        self._record_candidate_seed_scan(
            active_items=active_items,
            seed_items=seed_items,
            max_seed_items=max_seed_items,
        )
        for source in seed_items:
            if source.get("kind") == "structure":
                if self._context_concat_enabled_for_candidates():
                    self._collect_context_concat_candidates(
                        source=source,
                        active_items=active_items,
                        exact_context_index=exact_context_index,
                        hdb=hdb,
                        best_by_signature=best_by_signature,
                    )
                if self._stitching_mode() in {"legacy_event", "hybrid_compare"} or (
                    self._stitching_mode() == "context_match_v2"
                    and not bool(self._config.get("context_concat_v2_enabled", True))
                ):
                    self._collect_pair_create_candidates(
                        source=source,
                        active_items=active_items,
                        active_by_ref=active_by_ref,
                        hdb=hdb,
                        best_by_signature=best_by_signature,
                    )
                continue

            if source.get("kind") == "event":
                self._collect_event_bridge_candidates(
                    source=source,
                    active_items=active_items,
                    active_by_ref=active_by_ref,
                    hdb=hdb,
                    best_by_signature=best_by_signature,
                )

        return self._rank_candidates(list(best_by_signature.values()))

    def _prepare_context_concat_active_items(self, *, active_items: list[dict], hdb) -> None:
        structure_store = getattr(hdb, "_structure_store", None)
        for item in active_items:
            if item.get("kind") != "structure":
                continue
            tokens = [str(token) for token in (item.get("tokens", []) or []) if str(token)]
            item["_cs_tokens"] = tokens
            item["_cs_plain_text"] = "".join(tokens) or self._item_plain_text(item)
            item["_cs_source_match_tokens"] = self._strip_trailing_attribute_token_spans(
                tokens=tokens,
                attribute_displays=list(item.get("attribute_displays", []) or []),
            )
            context_tokens = self._context_tokens_for_item(target=item, hdb=hdb)
            item["_cs_context_tokens"] = context_tokens
            item["_cs_context_text"] = str(item.get("context_text", "") or "").strip() or "".join(context_tokens)
            item["_cs_context_path_id_set"] = set(self._dedupe_ids(item.get("context_path_ids", []) or []))
            item["_cs_attribute_anchor_ref_id_set"] = set(self._dedupe_ids(item.get("attribute_anchor_ref_ids", []) or []))
            item["_cs_context_support_id_set"] = self._context_support_id_set(item)
            item["_cs_attribute_by_name"] = self._attribute_descriptors_by_name(item)
            item["_cs_direct_diff_weight_by_target"] = self._direct_diff_weight_map(
                structure_store=structure_store,
                owner_ref_id=str(item.get("ref_object_id", "") or ""),
            )

    @staticmethod
    def _build_context_concat_exact_index(*, active_items: list[dict]) -> dict[str, list[dict]]:
        index: dict[str, list[dict]] = {}
        for item in active_items:
            if item.get("kind") != "structure":
                continue
            for raw_key in (
                item.get("context_owner_id", ""),
                item.get("context_ref_object_id", ""),
            ):
                key = str(raw_key or "").strip()
                if not key:
                    continue
                index.setdefault(key, []).append(item)
        return index

    def _rank_candidates(self, candidates: list[dict]) -> list[dict]:
        return sorted(
            list(candidates or []),
            key=lambda item: (
                float(item.get("score", 0.0) or 0.0),
                float(item.get("context_ratio", 0.0) or 0.0),
                float(item.get("edge_weight_ratio", 0.0) or 0.0),
                float(item.get("match_strength", 0.0) or 0.0),
                float(item.get("competition_energy", 0.0) or 0.0),
                float(item.get("competition_cp_abs", 0.0) or 0.0),
                -float(item.get("competition_created_at", 0.0) or 0.0),
            ),
            reverse=True,
        )

    def _candidate_competition_key(self, candidate: dict) -> tuple[float, float, float, float, float, float, float]:
        return (
            float(candidate.get("score", 0.0) or 0.0),
            float(candidate.get("context_ratio", 0.0) or 0.0),
            float(candidate.get("edge_weight_ratio", 0.0) or 0.0),
            float(candidate.get("match_strength", 0.0) or 0.0),
            float(candidate.get("competition_energy", 0.0) or 0.0),
            float(candidate.get("competition_cp_abs", 0.0) or 0.0),
            -float(candidate.get("competition_created_at", 0.0) or 0.0),
        )

    def _collect_context_concat_candidates(
        self,
        *,
        source: dict,
        active_items: list[dict],
        exact_context_index: dict[str, list[dict]] | None = None,
        hdb,
        best_by_signature: dict[str, dict],
    ) -> None:
        raw_max_targets = int(self._config.get("context_concat_max_targets_per_seed", 0) or 0)
        max_targets = raw_max_targets if raw_max_targets > 0 else None
        picked = 0
        source_ref_id = str(source.get("ref_object_id", "") or "").strip()
        candidate_targets: list[dict] = []
        seen_target_items: set[str] = set()
        for target in list((exact_context_index or {}).get(source_ref_id, []) or []):
            target_key = str(target.get("item_id", "") or target.get("ref_object_id", "") or "")
            if not target_key or target_key in seen_target_items:
                continue
            seen_target_items.add(target_key)
            candidate_targets.append(target)
        exact_target_count = len(candidate_targets)
        soft_scan_enabled = bool(self._config.get("context_concat_soft_scan_enabled", True))
        exact_only_fallback = bool(self._config.get("context_concat_soft_scan_when_exact_candidates_missing_only", True))
        soft_scan_attempted = bool(soft_scan_enabled and (not exact_only_fallback or not candidate_targets))
        soft_scan_allowed = False
        soft_target_count = 0
        if soft_scan_enabled and (not exact_only_fallback or not candidate_targets):
            if not self._allow_context_concat_soft_scan_for_source(source):
                soft_scan_enabled = False
            if soft_scan_enabled:
                soft_scan_allowed = True
                self._soft_scan_source_count_this_tick = int(getattr(self, "_soft_scan_source_count_this_tick", 0) or 0) + 1
            soft_target_limit = int(self._config.get("context_concat_soft_scan_max_targets_per_source", 48) or 0)
            soft_picked = 0
            for target in active_items if soft_scan_enabled else []:
                target_key = str(target.get("item_id", "") or target.get("ref_object_id", "") or "")
                if target_key and target_key in seen_target_items:
                    continue
                if target_key:
                    seen_target_items.add(target_key)
                candidate_targets.append(target)
                soft_picked += 1
                if soft_target_limit > 0 and soft_picked >= soft_target_limit:
                    break
            soft_target_count = int(soft_picked)
        self._record_candidate_source_scan(
            source=source,
            exact_target_count=exact_target_count,
            soft_scan_attempted=soft_scan_attempted,
            soft_scan_allowed=soft_scan_allowed,
            soft_target_count=soft_target_count,
            candidate_target_count=len(candidate_targets),
            raw_max_targets=raw_max_targets,
        )
        for target in candidate_targets:
            if target.get("kind") != "structure":
                continue
            if str(target.get("ref_object_id", "") or "") == str(source.get("ref_object_id", "") or ""):
                continue
            matched = self._match_context_tail_for_concat(source=source, target=target, hdb=hdb)
            if not matched:
                continue

            direct_diff_weight = self._direct_diff_weight_for_pair(
                source=source,
                structure_store=getattr(hdb, "_structure_store", None),
                target_id=str(target.get("ref_object_id", "") or ""),
            )
            support_base = max(
                float(matched.get("path_support_score", 0.0) or 0.0),
                float(matched.get("strength", 0.0) or 0.0),
                0.12,
            )
            synthetic_edge_weight = round(
                max(
                    0.04,
                    float(direct_diff_weight) + float(target.get("runtime_weight", 0.0) or 0.0) * (0.28 + 0.72 * support_base),
                ),
                8,
            )
            positive_total_weight = round(
                max(
                    synthetic_edge_weight,
                    synthetic_edge_weight + max(float(source.get("runtime_weight", 0.0) or 0.0), 0.01),
                ),
                8,
            )
            context_hits = max(1, int(matched.get("context_hits", 1) or 1))
            candidate = self._score_candidate(
                action_type="concat_context_structure",
                source=source,
                target=target,
                entry={
                    "target_id": str(target.get("ref_object_id", "") or ""),
                    "base_weight": synthetic_edge_weight,
                    "ext": {
                        "relation_type": "context_concat_structure",
                        "direct_diff_weight": round(float(direct_diff_weight), 8),
                    },
                },
                positive_total_weight=positive_total_weight,
                matched=matched,
                context_hits=context_hits,
                closest_distance=0,
                new_components=[
                    str(source.get("ref_object_id", "") or ""),
                    str(target.get("ref_object_id", "") or ""),
                ],
                absorb_scale=round(
                    0.86 + 0.16 * float(matched.get("path_support_score", 0.0) or 0.0),
                    8,
                ),
            )
            if not candidate:
                continue
            candidate.update(
                {
                    "result_display": str(matched.get("result_display", "") or ""),
                    "result_tokens": list(matched.get("result_tokens", []) or []),
                    "result_sequence_groups": list(matched.get("result_sequence_groups", []) or []),
                    "result_context_owner_id": str(matched.get("result_context_owner_id", "") or ""),
                    "result_context_ref_object_id": str(matched.get("result_context_ref_object_id", "") or ""),
                    "result_context_ref_object_type": "st",
                    "result_context_path_ids": list(matched.get("result_context_path_ids", []) or []),
                    "result_context_text": str(matched.get("result_context_text", "") or ""),
                    "result_content_signature": str(matched.get("result_content_signature", "") or ""),
                    "context_tokens": list(matched.get("context_tokens", []) or []),
                    "context_tail_char_ratio": round(float(matched.get("context_tail_char_ratio", 0.0) or 0.0), 8),
                    "direct_owner_score": round(float(matched.get("direct_owner_score", 0.0) or 0.0), 8),
                    "path_support_score": round(float(matched.get("path_support_score", 0.0) or 0.0), 8),
                    "last_token_score": round(float(matched.get("last_token_score", 0.0) or 0.0), 8),
                    "contiguous_ratio": round(float(matched.get("contiguous_ratio", 0.0) or 0.0), 8),
                    "gap_ratio": round(float(matched.get("gap_ratio", 0.0) or 0.0), 8),
                    "result_plain_text": str(matched.get("result_plain_text", "") or ""),
                    "target_context_prefix_trimmed": bool(matched.get("target_context_prefix_trimmed", False)),
                    "target_context_prefix_trim_count": int(matched.get("target_context_prefix_trim_count", 0) or 0),
                    "exact_context_identity_match": bool(matched.get("exact_context_identity_match", False)),
                }
            )
            self._upsert_candidate(best_by_signature=best_by_signature, candidate=candidate)
            picked += 1
            if max_targets is not None and picked >= max_targets:
                break
        self._record_candidate_source_result(
            source=source,
            picked_count=picked,
            candidate_target_count=len(candidate_targets),
            max_targets=raw_max_targets,
        )

    def _allow_context_concat_soft_scan_for_source(self, source: dict) -> bool:
        max_sources = int(self._config.get("context_concat_soft_scan_max_sources_per_tick", 32) or 0)
        if max_sources > 0 and int(getattr(self, "_soft_scan_source_count_this_tick", 0) or 0) >= max_sources:
            return False
        if not bool(self._config.get("context_concat_soft_scan_privileged_only", True)):
            return True
        return bool(
            source.get("attention_seed", False)
            or source.get("projected_from_non_st_support", False)
            or source.get("support_structure_id", "")
            or source.get("runtime_ref_object_id", "")
        )

    def _match_context_tail_for_concat(self, *, source: dict, target: dict, hdb) -> dict | None:
        source_tokens = list(source.get("_cs_tokens", []) or []) or [str(token) for token in (source.get("tokens", []) or []) if str(token)]
        target_tokens = list(target.get("_cs_tokens", []) or []) or [str(token) for token in (target.get("tokens", []) or []) if str(token)]
        context_tokens = list(target.get("_cs_context_tokens", []) or []) or self._context_tokens_for_item(target=target, hdb=hdb)
        source_match_tokens = list(source.get("_cs_source_match_tokens", []) or [])
        if not source_match_tokens:
            source_match_tokens = self._strip_trailing_attribute_token_spans(
                tokens=source_tokens,
                attribute_displays=list(source.get("attribute_displays", []) or []),
            )
        source_text = "".join(source_match_tokens) or str(source.get("_cs_plain_text", "") or "") or self._item_plain_text(source)
        context_text = str(target.get("_cs_context_text", "") or "").strip() or str(target.get("context_text", "") or "").strip() or "".join(context_tokens)
        if not source_match_tokens or not target_tokens or not context_tokens or not source_text or not context_text:
            return None

        matched_token_count = 0
        source_index = len(source_match_tokens) - 1
        context_index = len(context_tokens) - 1
        gap_count = 0
        while source_index >= 0 and context_index >= 0:
            if source_match_tokens[source_index] == context_tokens[context_index]:
                matched_token_count += 1
                source_index -= 1
                context_index -= 1
                continue
            gap_count += 1
            source_index -= 1

        suffix_match_count = 0
        max_suffix = min(len(source_match_tokens), len(context_tokens))
        while suffix_match_count < max_suffix and source_match_tokens[-1 - suffix_match_count] == context_tokens[-1 - suffix_match_count]:
            suffix_match_count += 1

        char_suffix_len = self._common_suffix_text_length(source_text, context_text)
        context_ratio_token = float(matched_token_count) / max(1, len(context_tokens))
        context_ratio_char = float(char_suffix_len) / max(1, len(context_text))
        context_ratio = self._clamp01(max(context_ratio_token, context_ratio_char))
        min_ratio = max(0.0, float(self._config.get("context_concat_min_context_ratio", 0.22) or 0.22))
        if context_ratio < min_ratio:
            return None

        last_token_score = (
            1.0
            if source_match_tokens[-1] == context_tokens[-1]
            else (1.0 if source_text[-1:] == context_text[-1:] else 0.0)
        )
        contiguous_ratio = self._clamp01(float(suffix_match_count) / max(1, len(context_tokens)))
        gap_ratio = self._clamp01(float(gap_count) / max(1, len(context_tokens)))
        order_penalty = max(0.0, float(self._config.get("context_concat_order_gap_penalty", 0.12) or 0.12))
        order_score = self._clamp01(max(context_ratio, contiguous_ratio) * max(0.0, 1.0 - order_penalty * gap_ratio))

        direct_owner_score = 1.0 if str(target.get("context_owner_id", "") or "") == str(source.get("ref_object_id", "") or "") else 0.0
        source_ref_id = str(source.get("ref_object_id", "") or "")
        source_path_id_set = self._context_path_id_set(source)
        target_path_id_set = self._context_path_id_set(target)
        target_anchor_ref_id_set = self._attribute_anchor_ref_id_set(target)
        if direct_owner_score > 0.0:
            path_support_score = float(self._config.get("context_concat_direct_owner_bonus", 1.0) or 1.0)
        elif source_ref_id and source_ref_id in target_path_id_set:
            path_support_score = float(self._config.get("context_concat_path_bonus", 0.72) or 0.72)
        elif source_ref_id and source_ref_id in target_anchor_ref_id_set:
            path_support_score = float(self._config.get("context_concat_path_bonus", 0.72) or 0.72)
        elif source_path_id_set & target_path_id_set:
            path_support_score = float(self._config.get("context_concat_partial_path_bonus", 0.52) or 0.52)
        elif source_path_id_set & target_anchor_ref_id_set:
            path_support_score = float(self._config.get("context_concat_partial_path_bonus", 0.52) or 0.52)
        else:
            path_support_score = 0.0
        allow_partial_without_path_support = bool(
            self._config.get("context_concat_allow_partial_without_path_support", True)
        )
        if path_support_score <= 0.0 and context_ratio < 0.999 and not allow_partial_without_path_support:
            return None
        if context_ratio >= 0.999 and last_token_score >= 0.999:
            path_support_score = max(
                float(path_support_score),
                float(self._config.get("context_concat_direct_owner_bonus", 1.0) or 1.0),
            )
        exact_identity_match = bool(
            str(target.get("context_owner_id", "") or "") == str(source.get("ref_object_id", "") or "")
            or str(target.get("context_ref_object_id", "") or "") == str(source.get("ref_object_id", "") or "")
        )

        attribute_bonus = self._attribute_context_bonus_for_concat(source=source, target=target)
        structural_match_units = max(
            1.0,
            float(matched_token_count),
            float(suffix_match_count),
            float(context_ratio_token * max(1, len(context_tokens))),
        )
        match_count_bundle = self._context_match_count_score(
            structural_units=structural_match_units,
            attribute_units=float(attribute_bonus.get("equivalent_units", 0.0) or 0.0),
        )
        match_count_score = float(match_count_bundle.get("score", 0.0) or 0.0)
        attribute_bonus_score = float(attribute_bonus.get("score", 0.0) or 0.0)
        strength = self._clamp01(
            0.40 * context_ratio
            + 0.16 * order_score
            + 0.14 * contiguous_ratio
            + 0.10 * last_token_score
            + 0.08 * path_support_score
            + 0.08 * match_count_score
            + 0.04 * attribute_bonus_score
        )
        append_bundle = self._target_append_bundle_for_context_concat(
            target=target,
            target_tokens=target_tokens,
            context_tokens=context_tokens,
        )
        append_tokens = list(append_bundle.get("tokens", []) or [])
        if not append_tokens:
            return None
        result_tokens = list(source_tokens) + append_tokens
        if len(result_tokens) <= len(source_tokens):
            return None
        result_sequence_groups = self._concat_sequence_groups(
            left=list(source.get("sequence_groups", []) or []),
            right=list(append_bundle.get("sequence_groups", []) or []),
        )
        result_display = self._concat_display(
            source=source,
            target=target,
            tokens=result_tokens,
            target_display_override=str(append_bundle.get("display", "") or ""),
        )
        result_context_path_ids = self._dedupe_ids(list(source.get("context_path_ids", []) or []) + [source_ref_id])
        result_plain_text = "".join(result_tokens) or result_display
        return {
            "mode": "context_tail_exact" if context_ratio >= 0.999 and last_token_score >= 0.999 else "context_tail_partial",
            "exact_context_identity_match": exact_identity_match,
            "strength": round(float(strength), 8),
            "matched_span": max(1, matched_token_count, suffix_match_count),
            "prefix_components": 1,
            "context_ratio": round(float(context_ratio), 8),
            "context_hits": max(1, int(round(context_ratio * max(1, len(context_tokens))))),
            "order_score": round(float(order_score), 8),
            "tail_score": round(float(max(contiguous_ratio, last_token_score)), 8),
            "direct_owner_score": round(float(direct_owner_score), 8),
            "path_support_score": round(float(path_support_score), 8),
            "last_token_score": round(float(last_token_score), 8),
            "contiguous_ratio": round(float(contiguous_ratio), 8),
            "gap_ratio": round(float(gap_ratio), 8),
            "matched_token_count": int(matched_token_count),
            "structural_match_units": round(float(structural_match_units), 8),
            "match_count_score": round(float(match_count_score), 8),
            "match_count_raw": round(float(match_count_bundle.get("raw", 0.0) or 0.0), 8),
            "effective_match_units": round(float(match_count_bundle.get("effective_units", 0.0) or 0.0), 8),
            "attribute_bonus_score": round(float(attribute_bonus_score), 8),
            "attribute_bonus_equivalent_units": round(float(attribute_bonus.get("equivalent_units", 0.0) or 0.0), 8),
            "attribute_match_count": int(attribute_bonus.get("matched_count", 0) or 0),
            "tail_anchor_scale": round(self._clamp01((0.72 + 0.28 * last_token_score) * max(0.0, 1.0 - order_penalty * gap_ratio)), 8),
            "context_tokens": list(context_tokens),
            "context_tail_char_ratio": round(float(context_ratio_char), 8),
            "target_context_prefix_trimmed": bool(append_bundle.get("context_prefix_trimmed", False)),
            "target_context_prefix_trim_count": int(append_bundle.get("context_prefix_trim_count", 0) or 0),
            "exact_context_identity_match": exact_identity_match,
            "result_tokens": result_tokens,
            "result_sequence_groups": result_sequence_groups,
            "result_display": result_display,
            "result_context_owner_id": source_ref_id,
            "result_context_ref_object_id": source_ref_id,
            "result_context_path_ids": result_context_path_ids,
            "result_context_text": str(source.get("display", "") or source_text),
            "result_content_signature": self._tokens_signature(hdb=hdb, tokens=result_tokens),
            "result_plain_text": result_plain_text,
        }

    def _target_append_bundle_for_context_concat(
        self,
        *,
        target: dict,
        target_tokens: list[str],
        context_tokens: list[str],
    ) -> dict[str, Any]:
        tokens = [str(token) for token in list(target_tokens or []) if str(token)]
        context = [str(token) for token in list(context_tokens or []) if str(token)]
        trim_count = 0
        if context and len(tokens) > len(context) and tokens[: len(context)] == context:
            trim_count = len(context)
        append_tokens = tokens[trim_count:]
        append_groups = self._trim_sequence_groups_prefix(
            groups=list(target.get("sequence_groups", []) or []),
            trim_count=trim_count,
        )
        if not append_groups and append_tokens:
            append_groups = [{"group_index": 0, "tokens": list(append_tokens)}]
        return {
            "tokens": append_tokens,
            "sequence_groups": append_groups,
            "display": "".join(append_tokens),
            "context_prefix_trimmed": trim_count > 0,
            "context_prefix_trim_count": int(trim_count),
        }

    def _context_tokens_for_item(self, *, target: dict, hdb) -> list[str]:
        context_owner_id = str(target.get("context_owner_id", "") or target.get("context_ref_object_id", "") or "")
        if context_owner_id:
            owner_tokens = self._structure_tokens_by_ref_id(hdb=hdb, structure_id=context_owner_id)
            if owner_tokens:
                return owner_tokens
        context_text = str(target.get("context_text", "") or "").strip()
        if context_text:
            return [ch for ch in context_text if str(ch).strip()]
        for anchor_ref_id in list(target.get("attribute_anchor_ref_ids", []) or []):
            anchor_tokens = self._structure_tokens_by_ref_id(hdb=hdb, structure_id=str(anchor_ref_id or ""))
            if anchor_tokens:
                return anchor_tokens
        for anchor_display in list(target.get("attribute_anchor_displays", []) or []):
            text = str(anchor_display or "").strip()
            if text:
                return [ch for ch in text if str(ch).strip()]
        return []

    def _structure_tokens_by_ref_id(self, *, hdb, structure_id: str) -> list[str]:
        ref_id = str(structure_id or "").strip()
        if not ref_id:
            return []
        structure_obj = self._get_structure(hdb=hdb, structure_id=ref_id)
        if not isinstance(structure_obj, dict):
            return []
        structure_block = structure_obj.get("structure", {}) if isinstance(structure_obj.get("structure", {}), dict) else {}
        owner_tokens = [str(token) for token in (structure_block.get("flat_tokens", []) or []) if str(token)]
        if owner_tokens:
            return owner_tokens
        owner_display = self._structure_display(structure_obj)
        if owner_display:
            return [ch for ch in owner_display if str(ch).strip()]
        return []

    @staticmethod
    def _strip_trailing_attribute_token_spans(*, tokens: list[str], attribute_displays: list[str]) -> list[str]:
        if not tokens:
            return []
        trimmed = list(tokens)
        attr_spans = []
        for raw_display in list(attribute_displays or []):
            chars = [str(ch) for ch in str(raw_display or "") if str(ch).strip()]
            if chars:
                attr_spans.append(chars)
        attr_spans.sort(key=len, reverse=True)
        changed = True
        while trimmed and changed:
            changed = False
            for chars in attr_spans:
                if len(chars) > len(trimmed):
                    continue
                if trimmed[-len(chars):] == chars:
                    trimmed = trimmed[: -len(chars)]
                    changed = True
                    break
        return trimmed or list(tokens)

    def _attribute_context_bonus_for_concat(self, *, source: dict, target: dict) -> dict[str, Any]:
        source_attrs = [row for row in list(source.get("attribute_descriptors", []) or []) if isinstance(row, dict)]
        target_attrs = [row for row in list(target.get("attribute_descriptors", []) or []) if isinstance(row, dict)]
        if not source_attrs or not target_attrs:
            return {"score": 0.0, "equivalent_units": 0.0, "matched_count": 0}

        source_by_name = source.get("_cs_attribute_by_name")
        if not isinstance(source_by_name, dict):
            source_by_name = self._attribute_descriptors_by_name(source)

        anchor_bonus = max(0.0, float(self._config.get("context_concat_attribute_anchor_bonus", 0.18) or 0.18))
        total_units = 0.0
        matched_count = 0
        for target_row in target_attrs:
            name = str(target_row.get("attribute_name", "") or "").strip()
            if not name:
                continue
            best = 0.0
            for source_row in source_by_name.get(name, []):
                value_score = self._attribute_value_match_score(source_row=source_row, target_row=target_row)
                if value_score <= 0.0:
                    continue
                anchor_support = self._attribute_anchor_context_support_score(
                    source=source,
                    target=target,
                    source_row=source_row,
                    target_row=target_row,
                )
                candidate_score = min(1.0, float(value_score) + anchor_bonus * float(anchor_support))
                if candidate_score > best:
                    best = candidate_score
            if best <= 0.0:
                continue
            total_units += best
            matched_count += 1

        cap_units = max(0.0, float(self._config.get("context_concat_attribute_bonus_cap", 2.0) or 2.0))
        equivalent_units = min(cap_units, total_units) if cap_units > 0.0 else total_units
        return {
            "score": round(self._clamp01(equivalent_units), 8),
            "equivalent_units": round(float(equivalent_units), 8),
            "matched_count": int(matched_count),
        }

    def _attribute_value_match_score(self, *, source_row: dict, target_row: dict) -> float:
        source_name = str(source_row.get("attribute_name", "") or "").strip()
        target_name = str(target_row.get("attribute_name", "") or "").strip()
        if not source_name or source_name != target_name:
            return 0.0

        source_value = source_row.get("attribute_value")
        target_value = target_row.get("attribute_value")
        numeric = describe_numeric_match(
            left_value=source_value,
            right_value=target_value,
            abs_tolerance=float(self._config.get("context_concat_attribute_numeric_abs_tolerance", 0.2) or 0.2),
            rel_tolerance=float(self._config.get("context_concat_attribute_numeric_rel_tolerance", 0.35) or 0.35),
            min_similarity=float(self._config.get("context_concat_attribute_numeric_min_similarity", 0.4) or 0.4),
            family=source_name,
        )
        if isinstance(numeric, dict):
            return self._clamp01(float(numeric.get("similarity", 0.0) or 0.0))

        source_text = str(source_value if source_value is not None else source_row.get("display", "") or "").strip()
        target_text = str(target_value if target_value is not None else target_row.get("display", "") or "").strip()
        if source_text and target_text:
            return 1.0 if source_text == target_text else 0.0
        if source_text or target_text:
            return 0.62
        return 0.78

    def _attribute_anchor_context_support_score(self, *, source: dict, target: dict, source_row: dict, target_row: dict) -> float:
        source_ids = self._context_support_id_set(source)
        target_ids = self._context_support_id_set(target)

        source_anchor = str(source_row.get("anchor_ref_object_id", "") or "").strip()
        target_anchor = str(target_row.get("anchor_ref_object_id", "") or "").strip()
        if target_anchor and target_anchor in source_ids:
            return 1.0
        if source_anchor and source_anchor in target_ids:
            return 1.0
        if source_anchor and target_anchor and source_anchor == target_anchor:
            return 0.82
        if str(source_row.get("anchor_display", "") or "").strip() and str(source_row.get("anchor_display", "") or "").strip() == str(target.get("display", "") or "").strip():
            return 0.72
        if str(target_row.get("anchor_display", "") or "").strip() and str(target_row.get("anchor_display", "") or "").strip() == str(source.get("display", "") or "").strip():
            return 0.72
        return 0.0

    @staticmethod
    def _attribute_descriptors_by_name(item: dict) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for row in list(item.get("attribute_descriptors", []) or []):
            if not isinstance(row, dict):
                continue
            name = str(row.get("attribute_name", "") or "").strip()
            if not name:
                continue
            out.setdefault(name, []).append(row)
        return out

    def _context_support_id_set(self, item: dict) -> set[str]:
        cached = item.get("_cs_context_support_id_set")
        if isinstance(cached, set):
            return cached
        ids = {
            str(item.get("ref_object_id", "") or "").strip(),
            str(item.get("context_owner_id", "") or "").strip(),
            str(item.get("context_ref_object_id", "") or "").strip(),
        }
        ids.update(str(ref or "").strip() for ref in list(item.get("context_path_ids", []) or []))
        ids.discard("")
        return ids

    def _context_path_id_set(self, item: dict) -> set[str]:
        cached = item.get("_cs_context_path_id_set")
        if isinstance(cached, set):
            return cached
        return set(self._dedupe_ids(item.get("context_path_ids", []) or []))

    def _attribute_anchor_ref_id_set(self, item: dict) -> set[str]:
        cached = item.get("_cs_attribute_anchor_ref_id_set")
        if isinstance(cached, set):
            return cached
        return set(self._dedupe_ids(item.get("attribute_anchor_ref_ids", []) or []))

    def _context_match_count_score(self, *, structural_units: float, attribute_units: float) -> dict[str, float]:
        effective_units = max(0.0, float(structural_units)) + max(0.0, float(attribute_units))
        half_point = max(0.05, float(self._config.get("context_concat_match_count_half_point", 2.4) or 2.4))
        raw = effective_units / (effective_units + half_point)
        score = self._soft_uplift01(
            raw,
            power=max(0.05, float(self._config.get("context_concat_match_count_soft_power", 0.78) or 0.78)),
            linear_mix=self._clamp01(float(self._config.get("context_concat_match_count_linear_mix", 0.28) or 0.28)),
        )
        return {
            "raw": round(float(raw), 8),
            "score": round(float(score), 8),
            "effective_units": round(float(effective_units), 8),
        }

    @staticmethod
    def _common_suffix_text_length(left: str, right: str) -> int:
        if not left or not right:
            return 0
        count = 0
        max_len = min(len(left), len(right))
        while count < max_len and left[-1 - count] == right[-1 - count]:
            count += 1
        return count

    @staticmethod
    def _concat_sequence_groups(*, left: list[dict], right: list[dict]) -> list[dict]:
        groups: list[dict] = []
        for raw_group in list(left or []) + list(right or []):
            if not isinstance(raw_group, dict):
                continue
            cloned = dict(raw_group)
            cloned["group_index"] = len(groups)
            groups.append(cloned)
        return groups

    @staticmethod
    def _trim_sequence_groups_prefix(*, groups: list[dict], trim_count: int) -> list[dict]:
        remaining_to_trim = max(0, int(trim_count or 0))
        out: list[dict] = []
        for raw_group in list(groups or []):
            if not isinstance(raw_group, dict):
                continue
            group_tokens = [str(token) for token in (raw_group.get("tokens", []) or []) if str(token)]
            if remaining_to_trim >= len(group_tokens):
                remaining_to_trim -= len(group_tokens)
                continue
            if remaining_to_trim > 0:
                group_tokens = group_tokens[remaining_to_trim:]
                remaining_to_trim = 0
            if not group_tokens:
                continue
            cloned = dict(raw_group)
            cloned["tokens"] = list(group_tokens)
            cloned["group_index"] = len(out)
            out.append(cloned)
        return out

    @staticmethod
    def _concat_display(*, source: dict, target: dict, tokens: list[str], target_display_override: str = "") -> str:
        source_display = str(source.get("display", "") or "")
        target_display = str(target_display_override or target.get("display", "") or "")
        if source_display or target_display:
            return f"{source_display}{target_display}"
        return "".join(str(token) for token in tokens if str(token))

    @staticmethod
    def _item_plain_text(item: dict) -> str:
        tokens = [str(token) for token in (item.get("tokens", []) or []) if str(token)]
        if tokens:
            return "".join(tokens)
        return str(item.get("display", "") or "")

    def _tokens_signature(self, *, hdb, tokens: list[str]) -> str:
        cut = getattr(hdb, "_cut", None)
        valid_tokens = [str(token) for token in tokens if str(token)]
        cache_key = (id(cut), tuple(valid_tokens))
        cached = self._signature_cache.get(cache_key)
        if cached is not None:
            return str(cached)
        if cut is not None and hasattr(cut, "tokens_to_signature"):
            try:
                signature = str(cut.tokens_to_signature(valid_tokens) or "")
                if len(self._signature_cache) < 8192:
                    self._signature_cache[cache_key] = signature
                return signature
            except Exception:
                pass
        signature = "|".join(valid_tokens)
        if len(self._signature_cache) < 8192:
            self._signature_cache[cache_key] = signature
        return signature

    @staticmethod
    def _lookup_direct_diff_weight(*, structure_store, owner_ref_id: str, target_id: str) -> float:
        if structure_store is None or not owner_ref_id or not target_id:
            return 0.0
        source_db = structure_store.get_db_by_owner(owner_ref_id)
        if not isinstance(source_db, dict):
            return 0.0
        best = 0.0
        for entry in list(source_db.get("diff_table", []) or []):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("target_id", "") or "") != target_id:
                continue
            best = max(best, max(0.0, float(entry.get("base_weight", 0.0) or 0.0)))
        return round(best, 8)

    @staticmethod
    def _direct_diff_weight_map(*, structure_store, owner_ref_id: str) -> dict[str, float]:
        if structure_store is None or not owner_ref_id:
            return {}
        source_db = structure_store.get_db_by_owner(owner_ref_id)
        if not isinstance(source_db, dict):
            return {}
        weights: dict[str, float] = {}
        for entry in list(source_db.get("diff_table", []) or []):
            if not isinstance(entry, dict):
                continue
            target_id = str(entry.get("target_id", "") or "")
            if not target_id:
                continue
            weight = max(0.0, float(entry.get("base_weight", 0.0) or 0.0))
            if weight <= 0.0:
                continue
            weights[target_id] = round(max(float(weights.get(target_id, 0.0) or 0.0), weight), 8)
        return weights

    def _direct_diff_weight_for_pair(self, *, source: dict, structure_store, target_id: str) -> float:
        target_ref = str(target_id or "")
        if not target_ref:
            return 0.0
        cached = source.get("_cs_direct_diff_weight_by_target")
        if isinstance(cached, dict):
            return round(max(0.0, float(cached.get(target_ref, 0.0) or 0.0)), 8)
        return self._lookup_direct_diff_weight(
            structure_store=structure_store,
            owner_ref_id=str(source.get("ref_object_id", "") or ""),
            target_id=target_ref,
        )

    def _collect_pair_create_candidates(
        self,
        *,
        source: dict,
        active_items: list[dict],
        active_by_ref: dict[str, dict],
        hdb,
        best_by_signature: dict[str, dict],
    ) -> None:
        entries, positive_total_weight = self._top_diff_entries(
            structure_store=getattr(hdb, "_structure_store", None),
            owner_ref_id=source["ref_object_id"],
        )
        if not entries or positive_total_weight <= 0.0:
            return

        for entry in entries:
            target_id = str(entry.get("target_id", "") or "")
            target_structure = self._get_structure(hdb=hdb, structure_id=target_id)
            if not target_structure:
                continue

            matched = self._resolve_target_match(
                target_structure=target_structure,
                active_items=active_items,
                active_by_ref=active_by_ref,
                source_ref_id=source["ref_object_id"],
                allow_event_targets=False,
            )
            if not matched or matched.get("item", {}).get("kind") != "structure":
                continue

            new_components = [source["ref_object_id"], matched["item"]["ref_object_id"]]
            if not self._is_component_sequence_valid(new_components):
                continue

            candidate = self._score_candidate(
                action_type="create_event",
                source=source,
                target=matched["item"],
                entry=entry,
                positive_total_weight=positive_total_weight,
                matched=matched,
                context_hits=1,
                closest_distance=0,
                new_components=new_components,
                absorb_scale=1.0,
            )
            if candidate:
                self._upsert_candidate(best_by_signature=best_by_signature, candidate=candidate)

    def _collect_event_bridge_candidates(
        self,
        *,
        source: dict,
        active_items: list[dict],
        active_by_ref: dict[str, dict],
        hdb,
        best_by_signature: dict[str, dict],
    ) -> None:
        enable_extend = bool(self._config.get("enable_event_extend", True))
        enable_merge = bool(self._config.get("enable_event_merge", True))
        if not enable_extend and not enable_merge:
            return

        max_context_k = max(1, int(self._config.get("max_context_k", 2)))
        tail_refs = list(source.get("components", []) or [])[-max_context_k:]
        if not tail_refs:
            return

        open_mode = str(self._config.get("event_context_open_mode", "tail_components") or "tail_components").strip().lower()
        if open_mode in {"event_overlay", "hybrid"} and bool(self._config.get("enable_esdb_overlay", True)):
            overlay_entries, overlay_total_weight = self._esdb_open_overlay_top_diff_entries(
                event_ref_id=str(source.get("event_ref_id", "") or source.get("ref_object_id", "") or ""),
                hdb=hdb,
            )
            if overlay_entries and overlay_total_weight > 0.0:
                for entry in overlay_entries:
                    target_structure = self._get_structure(hdb=hdb, structure_id=str(entry.get("target_id", "") or ""))
                    if not target_structure:
                        continue

                    matched = self._resolve_target_match(
                        target_structure=target_structure,
                        active_items=active_items,
                        active_by_ref=active_by_ref,
                        source_ref_id=str(source.get("ref_object_id", "") or ""),
                        allow_event_targets=enable_merge,
                    )
                    if not matched:
                        continue

                    target_item = matched.get("item", {}) or {}
                    if target_item.get("kind") == "structure":
                        if not enable_extend:
                            continue
                        if str(target_item.get("ref_object_id", "")) in list(source.get("components", []) or []):
                            continue
                        action_type = "extend_event"
                        new_components = list(source.get("components", []) or []) + [str(target_item.get("ref_object_id", "") or "")]
                        absorb_scale = float(self._config.get("extend_absorb_scale", 0.92))
                    else:
                        if not enable_merge:
                            continue
                        action_type = "merge_event"
                        new_components = self._merge_event_components(
                            left=list(source.get("components", []) or []),
                            right=list(target_item.get("components", []) or []),
                        )
                        absorb_scale = float(self._config.get("merge_absorb_scale", 0.84))

                    if not self._is_component_sequence_valid(new_components):
                        continue

                    support_hits = int((entry.get("ext", {}) or {}).get("support_hits", 1) or 1)
                    support_hits = max(1, min(max_context_k, support_hits))

                    candidate = self._score_candidate(
                        action_type=action_type,
                        source=source,
                        target=target_item,
                        entry=entry,
                        positive_total_weight=float(overlay_total_weight),
                        matched=matched,
                        context_hits=support_hits,
                        closest_distance=0,
                        new_components=new_components,
                        absorb_scale=absorb_scale,
                    )
                    if candidate:
                        self._upsert_candidate(best_by_signature=best_by_signature, candidate=candidate)

            if open_mode == "event_overlay":
                return

        for context_ref in reversed(tail_refs):
            entries, positive_total_weight = self._top_diff_entries(
                structure_store=getattr(hdb, "_structure_store", None),
                owner_ref_id=context_ref,
            )
            if not entries or positive_total_weight <= 0.0:
                continue

            for entry in entries:
                target_structure = self._get_structure(hdb=hdb, structure_id=str(entry.get("target_id", "") or ""))
                if not target_structure:
                    continue

                matched = self._resolve_target_match(
                    target_structure=target_structure,
                    active_items=active_items,
                    active_by_ref=active_by_ref,
                    source_ref_id=source["ref_object_id"],
                    allow_event_targets=enable_merge,
                )
                if not matched:
                    continue

                target_item = matched.get("item", {}) or {}
                if target_item.get("kind") == "structure":
                    if not enable_extend:
                        continue
                    if str(target_item.get("ref_object_id", "")) in list(source.get("components", []) or []):
                        continue
                    action_type = "extend_event"
                    new_components = list(source.get("components", []) or []) + [str(target_item.get("ref_object_id", "") or "")]
                    absorb_scale = float(self._config.get("extend_absorb_scale", 0.92))
                else:
                    if not enable_merge:
                        continue
                    action_type = "merge_event"
                    new_components = self._merge_event_components(
                        left=list(source.get("components", []) or []),
                        right=list(target_item.get("components", []) or []),
                    )
                    absorb_scale = float(self._config.get("merge_absorb_scale", 0.84))

                if not self._is_component_sequence_valid(new_components):
                    continue

                context_hits, closest_distance = self._estimate_context_support(
                    source_event=source,
                    target_item=target_item,
                    hdb=hdb,
                )
                if context_hits <= 0:
                    continue

                candidate = self._score_candidate(
                    action_type=action_type,
                    source=source,
                    target=target_item,
                    entry=entry,
                    positive_total_weight=positive_total_weight,
                    matched=matched,
                    context_hits=context_hits,
                    closest_distance=closest_distance,
                    new_components=new_components,
                    absorb_scale=absorb_scale,
                )
                if candidate:
                    self._upsert_candidate(best_by_signature=best_by_signature, candidate=candidate)

    def _top_diff_entries(self, *, structure_store, owner_ref_id: str) -> tuple[list[dict], float]:
        if structure_store is None or not owner_ref_id:
            return [], 0.0
        source_db = structure_store.get_db_by_owner(owner_ref_id)
        if not isinstance(source_db, dict):
            return [], 0.0
        raw_entries = [
            entry
            for entry in list(source_db.get("diff_table", []) or [])
            if isinstance(entry, dict) and str(entry.get("target_id", "") or "")
        ]
        if not raw_entries:
            return [], 0.0
        max_outgoing = max(1, int(self._config.get("max_outgoing_edges_per_seed", 8)))
        entries = sorted(
            raw_entries,
            key=lambda item: float(item.get("base_weight", 0.0) or 0.0),
            reverse=True,
        )[:max_outgoing]
        positive_total_weight = sum(max(0.0, float(entry.get("base_weight", 0.0) or 0.0)) for entry in entries)
        return entries, positive_total_weight

    def _resolve_target_match(
        self,
        *,
        target_structure: dict,
        active_items: list[dict],
        active_by_ref: dict[str, dict],
        source_ref_id: str,
        allow_event_targets: bool,
    ) -> dict | None:
        target_ref_id = str(target_structure.get("id", "") or "")
        target_tokens = list(target_structure.get("structure", {}).get("flat_tokens", []) or [])
        if not target_tokens:
            target_tokens = [self._structure_display(target_structure)]

        if target_ref_id and target_ref_id in active_by_ref and target_ref_id != source_ref_id:
            exact_item = active_by_ref[target_ref_id]
            if exact_item.get("kind") == "structure":
                return {
                    "item": exact_item,
                    "mode": "exact",
                    "strength": 1.0,
                    "matched_span": max(1, len(target_tokens)),
                    "prefix_components": 1,
                }

        best: dict | None = None
        for item in active_items:
            if str(item.get("ref_object_id", "")) == source_ref_id:
                continue
            if item.get("kind") == "event" and not allow_event_targets:
                continue
            row = self._match_target_structure_to_item(target_structure=target_structure, item=item)
            if not row:
                continue
            if best is None:
                best = row
                continue
            if float(row.get("strength", 0.0)) > float(best.get("strength", 0.0)):
                best = row
                continue
            if float(row.get("strength", 0.0)) == float(best.get("strength", 0.0)) and int(row.get("matched_span", 0)) > int(best.get("matched_span", 0)):
                best = row
        return best

    def _match_target_structure_to_item(self, *, target_structure: dict, item: dict) -> dict | None:
        if item.get("kind") == "event":
            return self._match_target_structure_to_event_item(target_structure=target_structure, event_item=item)
        return self._match_target_structure_to_structure_item(target_structure=target_structure, item=item)

    def _match_target_structure_to_structure_item(self, *, target_structure: dict, item: dict) -> dict | None:
        target_ref_id = str(target_structure.get("id", "") or "")
        target_tokens = list(target_structure.get("structure", {}).get("flat_tokens", []) or [])
        if not target_tokens:
            target_tokens = [self._structure_display(target_structure)]

        if target_ref_id and target_ref_id == str(item.get("ref_object_id", "") or ""):
            return {
                "item": item,
                "mode": "exact",
                "strength": 1.0,
                "matched_span": max(1, len(target_tokens)),
                "prefix_components": 1,
            }

        candidate_tokens = list(item.get("tokens", []) or [])
        if not candidate_tokens:
            return None

        contiguous_ratio = self._contiguous_subsequence_ratio(target_tokens, candidate_tokens)
        if contiguous_ratio > 0.0:
            return {
                "item": item,
                "mode": "containment",
                "strength": round(float(self._config.get("containment_match_scale", 0.78)) * contiguous_ratio, 8),
                "matched_span": max(1, len(target_tokens)),
                "prefix_components": 1,
            }

        lcs_len = self._lcs_length(target_tokens, candidate_tokens)
        if lcs_len <= 0:
            return None
        overlap_ratio = round(float(lcs_len) / max(1, len(target_tokens)), 8)
        if overlap_ratio < float(self._config.get("weak_overlap_min_ratio", 0.5)):
            return None
        return {
            "item": item,
            "mode": "weak_overlap",
            "strength": round(float(self._config.get("weak_overlap_match_scale", 0.42)) * overlap_ratio, 8),
            "matched_span": lcs_len,
            "prefix_components": 1,
        }

    def _match_target_structure_to_event_item(self, *, target_structure: dict, event_item: dict) -> dict | None:
        target_tokens = list(target_structure.get("structure", {}).get("flat_tokens", []) or [])
        if not target_tokens:
            target_tokens = [self._structure_display(target_structure)]

        component_displays = list(event_item.get("component_displays", []) or [])
        if not component_displays:
            return None

        max_head_components = max(1, int(self._config.get("max_event_head_match_components", 3)))
        max_head_components = min(max_head_components, len(component_displays))
        best: dict | None = None
        for prefix_components in range(1, max_head_components + 1):
            prefix_tokens = component_displays[:prefix_components]
            prefix_match_len = self._common_prefix_length(target_tokens, prefix_tokens)
            if prefix_match_len > 0:
                target_cover = float(prefix_match_len) / max(1, len(target_tokens))
                prefix_cover = float(prefix_match_len) / max(1, len(prefix_tokens))
                strength = float(self._config.get("event_prefix_match_scale", 1.0)) * math.sqrt(target_cover * prefix_cover)
                row = {
                    "item": event_item,
                    "mode": "event_prefix_exact" if target_cover == 1.0 and prefix_cover == 1.0 else "event_prefix",
                    "strength": round(strength, 8),
                    "matched_span": prefix_match_len,
                    "prefix_components": prefix_components,
                }
                if best is None or float(row["strength"]) > float(best.get("strength", 0.0)) or (
                    float(row["strength"]) == float(best.get("strength", 0.0))
                    and int(row["matched_span"]) > int(best.get("matched_span", 0))
                ):
                    best = row

            lcs_len = self._lcs_length(target_tokens, prefix_tokens)
            if lcs_len <= 0:
                continue
            overlap_ratio = round(float(lcs_len) / max(1, len(target_tokens)), 8)
            if overlap_ratio < float(self._config.get("weak_overlap_min_ratio", 0.5)):
                continue
            prefix_ratio = round(float(lcs_len) / max(1, len(prefix_tokens)), 8)
            strength = float(self._config.get("event_prefix_weak_scale", 0.36)) * math.sqrt(overlap_ratio * prefix_ratio)
            row = {
                "item": event_item,
                "mode": "event_prefix_weak",
                "strength": round(strength, 8),
                "matched_span": lcs_len,
                "prefix_components": prefix_components,
            }
            if best is None or float(row["strength"]) > float(best.get("strength", 0.0)) or (
                float(row["strength"]) == float(best.get("strength", 0.0))
                and int(row["matched_span"]) > int(best.get("matched_span", 0))
            ):
                best = row
        return best

    def _estimate_context_support(self, *, source_event: dict, target_item: dict, hdb) -> tuple[int, int]:
        structure_store = getattr(hdb, "_structure_store", None)
        if structure_store is None:
            return 0, max(1, int(self._config.get("max_context_k", 2)))

        max_context_k = max(1, int(self._config.get("max_context_k", 2)))
        tail_refs = list(source_event.get("components", []) or [])[-max_context_k:]
        support_hits = 0
        closest_distance = max_context_k
        for distance, context_ref in enumerate(reversed(tail_refs)):
            entries, _ = self._top_diff_entries(structure_store=structure_store, owner_ref_id=context_ref)
            if not entries:
                continue
            hit = False
            for entry in entries:
                target_structure = self._get_structure(hdb=hdb, structure_id=str(entry.get("target_id", "") or ""))
                if not target_structure:
                    continue
                row = self._match_target_structure_to_item(target_structure=target_structure, item=target_item)
                if row and float(row.get("strength", 0.0)) > 0.0:
                    hit = True
                    break
            if hit:
                support_hits += 1
                closest_distance = min(closest_distance, distance)
        return support_hits, closest_distance

    def _score_candidate(
        self,
        *,
        action_type: str,
        source: dict,
        target: dict,
        entry: dict,
        positive_total_weight: float,
        matched: dict,
        context_hits: int,
        closest_distance: int,
        new_components: list[str],
        absorb_scale: float,
    ) -> dict | None:
        max_component_count = max(2, int(self._config.get("max_event_component_count", 8)))
        if len(new_components) > max_component_count:
            self._audit_candidate_rejection(
                reason="component_count_exceeded",
                payload={
                    "action_type": action_type,
                    "source": source,
                    "target": target,
                    "new_component_count": len(new_components),
                    "max_component_count": max_component_count,
                },
            )
            return None

        edge_weight = max(0.0, float(entry.get("base_weight", 0.0) or 0.0))
        if edge_weight <= 0.0 or positive_total_weight <= 0.0:
            self._audit_candidate_rejection(
                reason="non_positive_edge",
                payload={
                    "action_type": action_type,
                    "source": source,
                    "target": target,
                    "edge_weight": edge_weight,
                    "positive_total_weight": positive_total_weight,
                },
            )
            return None
        edge_ratio = edge_weight / positive_total_weight

        energy_balance = self._energy_balance_ratio(
            float(source.get("balance_energy", source.get("total_energy", 0.0))),
            float(target.get("balance_energy", target.get("total_energy", 0.0))),
        )
        runtime_balance = self._energy_balance_ratio(
            float(source.get("balance_weight", source.get("runtime_weight", 0.0))),
            float(target.get("balance_weight", target.get("runtime_weight", 0.0))),
        )

        if action_type == "concat_context_structure":
            context_ratio = round(self._clamp01(float(matched.get("context_ratio", 0.0) or 0.0)), 8)
            bridge_span_ratio = round(
                self._clamp01(float(matched.get("contiguous_ratio", matched.get("context_ratio", 0.0)) or 0.0)),
                8,
            )
            anchor_scale = round(self._clamp01(float(matched.get("tail_anchor_scale", 1.0) or 1.0)), 8)
            result_signature = str(matched.get("result_content_signature", "") or "")
            if bool(self._config.get("context_concat_compete_per_source_only", True)):
                drain_sig = f"{action_type}::{str(source.get('ref_object_id', '') or '')}"
            else:
                drain_sig = f"{action_type}::{str(source.get('ref_object_id', '') or '')}::{result_signature or '|'.join(new_components)}"
        else:
            max_context_k = max(1, int(self._config.get("max_context_k", 2)))
            context_ratio = round(float(context_hits) / max(1, min(len(source.get("components", []) or []), max_context_k)), 8)

            max_event_head_match_components = max(1, int(self._config.get("max_event_head_match_components", 3)))
            bridge_span_ratio = round(
                min(1.0, float(matched.get("matched_span", 1) or 1) / max(1, max_event_head_match_components)),
                8,
            )

            anchor_penalty = max(0.0, float(self._config.get("anchor_distance_penalty", 0.18)))
            anchor_scale = round(1.0 / (1.0 + anchor_penalty * max(0, int(closest_distance))), 8)
            drain_sig = self._candidate_signature(action_type=action_type, new_components=new_components)
        pair_fatigue_before = round(float(self._pair_fatigue.get(drain_sig, 0.0) or 0.0), 8)
        pair_fatigue_scale = self._fatigue_scale(pair_fatigue_before)
        exact_context_identity_match = bool(matched.get("exact_context_identity_match", False))
        object_fatigue_bundle = self._object_stitch_fatigue_bundle(
            source_ref_id=self._active_item_identity_key(source),
            target_ref_id=self._active_item_identity_key(target),
            # The result object does not have a stable object id until the
            # concat is materialized. Do not use its content signature here:
            # same-content structures under different contexts must not share
            # attribution fatigue.
            result_ref_id="",
        )
        if (
            action_type == "concat_context_structure"
            and exact_context_identity_match
            and bool(self._config.get("context_concat_exact_ignore_object_fatigue", True))
        ):
            object_fatigue_scale = 1.0
            object_fatigue_before = 0.0
        else:
            object_fatigue_scale = float(object_fatigue_bundle.get("scale", 1.0) or 1.0)
            object_fatigue_before = float(object_fatigue_bundle.get("max_fatigue", 0.0) or 0.0)
        fatigue_before = round(max(pair_fatigue_before, object_fatigue_before), 8)
        fatigue_scale = round(float(pair_fatigue_scale) * float(object_fatigue_scale), 8)
        if self._fatigue_upper_bound_prunes_candidate(
            action_type=action_type,
            fatigue_scale=fatigue_scale,
            anchor_scale=anchor_scale,
        ):
            self._audit_candidate_rejection(
                reason="fatigue_upper_bound_below_threshold",
                payload={
                    "action_type": action_type,
                    "source": source,
                    "target": target,
                    "match_mode": matched.get("mode", ""),
                    "score": 0.0,
                    "base_score": 0.0,
                    "min_candidate_score": self._active_execution_min_candidate_score(),
                    "threshold_margin": -self._active_execution_min_candidate_score(),
                    "score_source": "fatigue_upper_bound",
                    "execution_uses_v2_score": self._uses_v2_execution(),
                    "legacy_score": 0.0,
                    "legacy_base_score": 0.0,
                    "legacy_min_candidate_score": max(0.0, float(self._config.get("min_candidate_score", 0.22))),
                    "legacy_threshold_margin": -max(0.0, float(self._config.get("min_candidate_score", 0.22))),
                    "edge_weight_ratio": round(edge_ratio, 8),
                    "match_strength": round(float(matched.get("strength", 0.0)), 8),
                    "context_ratio": context_ratio,
                    "energy_balance": 0.0,
                    "runtime_balance": 0.0,
                    "bridge_span_ratio": bridge_span_ratio,
                    "anchor_scale": anchor_scale,
                    "fatigue_scale": round(fatigue_scale, 8),
                    "match_count_score": 0.0,
                    "attribute_bonus_score": 0.0,
                    "effective_match_units": 0.0,
                    "attribute_bonus_equivalent_units": 0.0,
                    "v2_score": 0.0,
                    "v2_base_score_raw": 0.0,
                    "v2_base_score": 0.0,
                    "v2_base_score_soft": 0.0,
                    "v2_threshold_margin": -max(0.0, float(self._config.get("cs_v2_min_match_score", 0.18))),
                },
            )
            return None
        edge_ratio_component = round(float(self._config.get("edge_ratio_weight", 0.42)) * edge_ratio, 8)
        energy_balance_component = round(float(self._config.get("energy_balance_weight", 0.23)) * energy_balance, 8)
        match_strength_component = round(float(self._config.get("match_strength_weight", 0.20)) * float(matched.get("strength", 0.0)), 8)
        runtime_balance_component = round(float(self._config.get("runtime_weight_weight", 0.15)) * runtime_balance, 8)
        context_support_component = round(
            float(self._config.get("context_support_weight", 0.18))
            * (
                max(context_ratio, float(matched.get("path_support_score", 0.0) or 0.0))
                if action_type == "concat_context_structure"
                else context_ratio
            ),
            8,
        )
        bridge_span_component = round(float(self._config.get("bridge_span_weight", 0.08)) * bridge_span_ratio, 8)
        match_count_score = round(self._clamp01(float(matched.get("match_count_score", 0.0) or 0.0)), 8) if action_type == "concat_context_structure" else 0.0
        attribute_bonus_score = round(self._clamp01(float(matched.get("attribute_bonus_score", 0.0) or 0.0)), 8) if action_type == "concat_context_structure" else 0.0
        match_count_component = round(
            float(self._config.get("context_concat_match_count_weight", 0.12) or 0.12) * match_count_score,
            8,
        ) if action_type == "concat_context_structure" else 0.0
        attribute_bonus_component = round(
            float(self._config.get("context_concat_attribute_bonus_weight", 0.08) or 0.08) * attribute_bonus_score,
            8,
        ) if action_type == "concat_context_structure" else 0.0
        v2_breakdown = self._build_v2_score_breakdown(
            action_type=action_type,
            source=source,
            target=target,
            matched=matched,
            context_hits=context_hits,
            closest_distance=closest_distance,
            edge_ratio=edge_ratio,
            fatigue_scale=fatigue_scale,
        )

        base_score = (
            edge_ratio_component
            + energy_balance_component
            + match_strength_component
            + runtime_balance_component
            + context_support_component
            + bridge_span_component
            + match_count_component
            + attribute_bonus_component
        )
        score = round(max(0.0, base_score * anchor_scale * fatigue_scale), 8)
        min_candidate_score = max(0.0, float(self._config.get("min_candidate_score", 0.22)))
        threshold_margin = round(score - min_candidate_score, 8)
        execution_score_bundle = self._select_execution_score_bundle(
            legacy_score=score,
            legacy_base_score=base_score,
            legacy_min_candidate_score=min_candidate_score,
            legacy_threshold_margin=threshold_margin,
            v2_breakdown=v2_breakdown,
        )
        if (
            action_type == "concat_context_structure"
            and str(matched.get("mode", "") or "") == "context_tail_exact"
            and context_ratio >= 0.999
            and float(matched.get("last_token_score", 0.0) or 0.0) >= 0.999
        ):
            exact_score = max(
                float(execution_score_bundle.get("score", 0.0) or 0.0),
                float(self._config.get("context_concat_exact_min_score", 0.86) or 0.86),
            )
            execution_score_bundle["score"] = round(exact_score, 8)
            execution_score_bundle["base_score"] = max(float(execution_score_bundle.get("base_score", 0.0) or 0.0), round(exact_score, 8))
            execution_score_bundle["threshold_margin"] = round(
                float(execution_score_bundle.get("score", 0.0) or 0.0)
                - float(execution_score_bundle.get("min_candidate_score", 0.0) or 0.0),
                8,
            )
            execution_score_bundle["score_source"] = f"{execution_score_bundle.get('score_source', 'legacy')}:exact_context_floor"
        if float(execution_score_bundle.get("score", 0.0) or 0.0) < float(execution_score_bundle.get("min_candidate_score", 0.0) or 0.0):
            self._audit_candidate_rejection(
                reason=str(execution_score_bundle.get("rejection_reason", "below_min_candidate_score") or "below_min_candidate_score"),
                payload={
                    "action_type": action_type,
                    "source": source,
                    "target": target,
                    "match_mode": matched.get("mode", ""),
                    "score": round(float(execution_score_bundle.get("score", 0.0) or 0.0), 8),
                    "base_score": round(float(execution_score_bundle.get("base_score", 0.0) or 0.0), 8),
                    "min_candidate_score": round(float(execution_score_bundle.get("min_candidate_score", 0.0) or 0.0), 8),
                    "threshold_margin": round(float(execution_score_bundle.get("threshold_margin", 0.0) or 0.0), 8),
                    "score_source": str(execution_score_bundle.get("score_source", "legacy") or "legacy"),
                    "execution_uses_v2_score": bool(execution_score_bundle.get("execution_uses_v2_score", False)),
                    "legacy_score": score,
                    "legacy_base_score": round(base_score, 8),
                    "legacy_min_candidate_score": round(min_candidate_score, 8),
                    "legacy_threshold_margin": threshold_margin,
                    "edge_weight_ratio": round(edge_ratio, 8),
                    "match_strength": round(float(matched.get("strength", 0.0)), 8),
                    "context_ratio": context_ratio,
                    "energy_balance": round(energy_balance, 8),
                    "runtime_balance": round(runtime_balance, 8),
                    "bridge_span_ratio": bridge_span_ratio,
                    "anchor_scale": anchor_scale,
                    "fatigue_scale": round(fatigue_scale, 8),
                    "match_count_score": match_count_score,
                    "attribute_bonus_score": attribute_bonus_score,
                    "effective_match_units": round(float(matched.get("effective_match_units", 0.0) or 0.0), 8),
                    "attribute_bonus_equivalent_units": round(float(matched.get("attribute_bonus_equivalent_units", 0.0) or 0.0), 8),
                    "v2_score": round(float(v2_breakdown.get("v2_score", 0.0) or 0.0), 8),
                    "v2_base_score_raw": round(float(v2_breakdown.get("v2_base_score_raw", 0.0) or 0.0), 8),
                    "v2_base_score": round(float(v2_breakdown.get("v2_base_score", 0.0) or 0.0), 8),
                    "v2_base_score_soft": round(float(v2_breakdown.get("v2_base_score_soft", 0.0) or 0.0), 8),
                    "v2_context_cover_score": round(float(v2_breakdown.get("v2_context_cover_score", 0.0) or 0.0), 8),
                    "v2_context_cover_soft_score": round(float(v2_breakdown.get("v2_context_cover_soft_score", 0.0) or 0.0), 8),
                    "v2_order_alignment_score": round(float(v2_breakdown.get("v2_order_alignment_score", 0.0) or 0.0), 8),
                    "v2_order_alignment_soft_score": round(float(v2_breakdown.get("v2_order_alignment_soft_score", 0.0) or 0.0), 8),
                    "v2_tail_match_score": round(float(v2_breakdown.get("v2_tail_match_score", 0.0) or 0.0), 8),
                    "v2_tail_match_soft_score": round(float(v2_breakdown.get("v2_tail_match_soft_score", 0.0) or 0.0), 8),
                    "v2_context_db_support_score": round(float(v2_breakdown.get("v2_context_db_support_score", 0.0) or 0.0), 8),
                    "v2_context_db_support_soft_score": round(float(v2_breakdown.get("v2_context_db_support_soft_score", 0.0) or 0.0), 8),
                    "v2_energy_profile_score": round(float(v2_breakdown.get("v2_energy_profile_score", 0.0) or 0.0), 8),
                    "v2_energy_profile_soft_score": round(float(v2_breakdown.get("v2_energy_profile_soft_score", 0.0) or 0.0), 8),
                    "v2_match_count_score": round(float(v2_breakdown.get("v2_match_count_score", 0.0) or 0.0), 8),
                    "v2_match_count_soft_score": round(float(v2_breakdown.get("v2_match_count_soft_score", 0.0) or 0.0), 8),
                    "v2_attribute_bonus_score": round(float(v2_breakdown.get("v2_attribute_bonus_score", 0.0) or 0.0), 8),
                    "v2_attribute_bonus_soft_score": round(float(v2_breakdown.get("v2_attribute_bonus_soft_score", 0.0) or 0.0), 8),
                    "v2_fatigue_gate_raw": round(float(v2_breakdown.get("v2_fatigue_gate_raw", 0.0) or 0.0), 8),
                    "v2_fatigue_gate_soft": round(float(v2_breakdown.get("v2_fatigue_gate_soft", 0.0) or 0.0), 8),
                    "v2_threshold_margin": round(float(v2_breakdown.get("v2_threshold_margin", 0.0) or 0.0), 8),
                },
            )
            return None

        candidate = {
            "candidate_signature": drain_sig,
            "action_type": action_type,
            "source": source,
            "target": target,
            "source_identity_key": self._active_item_identity_key(source),
            "target_identity_key": self._active_item_identity_key(target),
            "new_components": list(new_components),
            "edge_target_id": str(entry.get("target_id", "") or ""),
            "edge_weight": round(edge_weight, 8),
            "edge_weight_ratio": round(edge_ratio, 8),
            "match_mode": matched.get("mode", ""),
            "match_strength": round(float(matched.get("strength", 0.0)), 8),
            "order_score": round(float(matched.get("order_score", 0.0) or 0.0), 8),
            "last_token_score": round(float(matched.get("last_token_score", 0.0) or 0.0), 8),
            "contiguous_ratio": round(float(matched.get("contiguous_ratio", 0.0) or 0.0), 8),
            "gap_ratio": round(float(matched.get("gap_ratio", 0.0) or 0.0), 8),
            "matched_span": int(matched.get("matched_span", 1) or 1),
            "prefix_components": int(matched.get("prefix_components", 1) or 1),
            "energy_balance": round(energy_balance, 8),
            "runtime_balance": round(runtime_balance, 8),
            "context_hits": int(context_hits),
            "context_ratio": context_ratio,
            "closest_distance": int(closest_distance),
            "bridge_span_ratio": bridge_span_ratio,
            "anchor_scale": anchor_scale,
            "pair_fatigue_before": pair_fatigue_before,
            "pair_fatigue_scale": round(pair_fatigue_scale, 8),
            "object_stitch_fatigue_before": round(float(object_fatigue_before), 8),
            "object_stitch_fatigue_scale": round(object_fatigue_scale, 8),
            "object_stitch_fatigue_refs": list(object_fatigue_bundle.get("refs", []) or []),
            "fatigue_before": fatigue_before,
            "fatigue_scale": round(fatigue_scale, 8),
            "edge_ratio_component": edge_ratio_component,
            "energy_balance_component": energy_balance_component,
            "match_strength_component": match_strength_component,
            "runtime_balance_component": runtime_balance_component,
            "context_support_component": context_support_component,
            "bridge_span_component": bridge_span_component,
            "match_count_score": match_count_score,
            "attribute_bonus_score": attribute_bonus_score,
            "match_count_component": match_count_component,
            "attribute_bonus_component": attribute_bonus_component,
            "effective_match_units": round(float(matched.get("effective_match_units", 0.0) or 0.0), 8),
            "attribute_bonus_equivalent_units": round(float(matched.get("attribute_bonus_equivalent_units", 0.0) or 0.0), 8),
            "score": round(float(execution_score_bundle.get("score", 0.0) or 0.0), 8),
            "score_source": str(execution_score_bundle.get("score_source", "legacy") or "legacy"),
            "execution_uses_v2_score": bool(execution_score_bundle.get("execution_uses_v2_score", False)),
            "base_score": round(float(execution_score_bundle.get("base_score", 0.0) or 0.0), 8),
            "min_candidate_score": round(float(execution_score_bundle.get("min_candidate_score", 0.0) or 0.0), 8),
            "threshold_margin": round(float(execution_score_bundle.get("threshold_margin", 0.0) or 0.0), 8),
            "legacy_score": score,
            "legacy_base_score": round(base_score, 8),
            "legacy_min_candidate_score": round(min_candidate_score, 8),
            "legacy_threshold_margin": threshold_margin,
            "absorb_scale": round(max(0.0, absorb_scale), 8),
            "competition_energy": round(
                max(
                    float(source.get("total_energy", 0.0) or 0.0),
                    float(target.get("total_energy", 0.0) or 0.0),
                ),
                8,
            ),
            "competition_cp_abs": round(
                max(
                    float(source.get("cp_abs", abs(float(source.get("er", 0.0) or 0.0) - float(source.get("ev", 0.0) or 0.0))) or 0.0),
                    float(target.get("cp_abs", abs(float(target.get("er", 0.0) or 0.0) - float(target.get("ev", 0.0) or 0.0))) or 0.0),
                ),
                8,
            ),
            "competition_created_at": int(
                min(
                    int(source.get("created_at", 0) or 0) or 2**62,
                    int(target.get("created_at", 0) or 0) or 2**62,
                )
            ),
        }
        candidate.update(v2_breakdown)
        self._audit_candidate_accept(candidate)
        return candidate

    def _apply_candidates(self, *, candidates: list[dict], pool, hdb, trace_id: str, tick_id: str) -> list[dict]:
        self._current_apply_audit = self._new_apply_audit(candidates)
        raw_max_events = int(self._config.get("max_events_per_tick", 0) or 0)
        max_events = raw_max_events if raw_max_events > 0 else None
        min_event_total = max(0.0, float(self._config.get("min_event_total_energy", 0.10)))
        base_ratio = max(0.0, float(self._config.get("base_absorb_ratio", 0.12)))
        cap_ratio = max(base_ratio, float(self._config.get("pair_absorb_ratio_cap", 0.22)))
        fatigue_step = max(0.0, float(self._config.get("same_pair_fatigue_step", 0.35)))
        fatigue_cap = max(0.01, float(self._config.get("same_pair_fatigue_cap", 1.6)))

        structure_store = getattr(hdb, "_structure_store", None)
        persist_enabled = bool(self._config.get("enable_persist_events_to_hdb", False)) and hasattr(hdb, "upsert_cognitive_stitching_event_structure") and hasattr(hdb, "make_runtime_structure_object")
        max_diff_entries = int(self._config.get("persist_events_max_diff_entries", 96) or 96)
        max_diff_entries = max(0, min(512, max_diff_entries))

        actions: list[dict] = []
        consumed_item_ids: set[str] = set()
        for candidate in candidates:
            if max_events is not None and len(actions) >= max_events:
                self._audit_apply_skip(candidate=candidate, reason="max_events_per_tick")
                break
            source = candidate["source"]
            target = candidate["target"]
            source_item_id = str(source.get("item_id", "") or "").strip()
            target_item_id = str(target.get("item_id", "") or "").strip()

            # Guard: if we cannot debit energy from both sides, do not create events (avoid energy creation).
            if not source_item_id or not target_item_id:
                self._audit_apply_skip(candidate=candidate, reason="missing_item_id")
                continue
            if (
                str(candidate.get("action_type", "") or "") == "concat_context_structure"
                and bool(self._config.get("context_concat_exclusive_items_per_tick", True))
                and (source_item_id in consumed_item_ids or target_item_id in consumed_item_ids)
            ):
                self._audit_apply_skip(candidate=candidate, reason="exclusive_item_consumed")
                continue

            score = max(0.0, float(candidate.get("score", 0.0)))
            absorb_ratio = self._candidate_absorb_ratio(
                candidate=candidate,
                score=score,
                base_ratio=base_ratio,
                cap_ratio=cap_ratio,
            )
            absorb_ratio = round(max(0.0, absorb_ratio), 8)

            src_er, src_ev, tgt_er, tgt_ev = self._candidate_absorbed_energy(
                source=source,
                target=target,
                absorb_ratio=absorb_ratio,
                use_lower_energy_cap=(
                    str(candidate.get("action_type", "") or "") == "concat_context_structure"
                    and bool(self._config.get("context_concat_use_lower_energy_cap", True))
                ),
            )
            event_er = round(src_er + tgt_er, 8)
            event_ev = round(src_ev + tgt_ev, 8)
            event_total = round(event_er + event_ev, 8)
            if event_total < min_event_total:
                self._audit_apply_skip(candidate=candidate, reason="below_min_event_total", event_total=event_total)
                continue

            action_type = str(candidate.get("action_type", "create_event") or "create_event")
            if action_type == "concat_context_structure":
                applied = self._apply_context_concat_candidate(
                    candidate=candidate,
                    pool=pool,
                    hdb=hdb,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    source=source,
                    target=target,
                    src_er=src_er,
                    src_ev=src_ev,
                    tgt_er=tgt_er,
                    tgt_ev=tgt_ev,
                    structure_er=event_er,
                    structure_ev=event_ev,
                    structure_total=event_total,
                    absorb_ratio=absorb_ratio,
                    fatigue_step=fatigue_step,
                    fatigue_cap=fatigue_cap,
                )
                if applied:
                    actions.append(applied)
                    self._audit_apply_action(applied)
                    consumed_item_ids.update({source_item_id, target_item_id})
                else:
                    self._audit_apply_skip(candidate=candidate, reason="apply_context_concat_failed")
                continue

            component_refs = list(candidate.get("new_components", []) or [])
            event_id = self._event_ref_id_from_components(component_refs)
            event_display = self._event_display_from_components(
                self._resolve_component_displays(
                    components=list(component_refs),
                    structure_store=structure_store,
                )
            )

            action_name = action_type
            event_item_id = ""
            event_structure_id = ""
            existing_item = None

            if persist_enabled:
                # Hot-path persistence: ensure the event is a HDB-backed "健全长期结构".
                component_state = self._build_event_component_state(
                    component_refs=list(component_refs),
                    component_displays=self._resolve_component_displays(components=list(component_refs), structure_store=structure_store),
                    source_components=list(source.get("components", []) or []),
                    target_components=list(target.get("components", []) or []),
                    source_absorbed_er=src_er,
                    source_absorbed_ev=src_ev,
                    target_absorbed_er=tgt_er,
                    target_absorbed_ev=tgt_ev,
                )
                cs_ext = {
                    "stage": "phase2_contextual_event_stitching",
                    "action_type": action_type,
                    "score_source": str(candidate.get("score_source", "legacy") or "legacy"),
                    "execution_uses_v2_score": bool(candidate.get("execution_uses_v2_score", False)),
                    "source_ref_id": str(source.get("ref_object_id", "") or ""),
                    "target_ref_id": str(target.get("ref_object_id", "") or ""),
                    "edge_target_id": str(candidate.get("edge_target_id", "") or ""),
                    "match_mode": str(candidate.get("match_mode", "") or ""),
                    "match_strength": round(float(candidate.get("match_strength", 0.0)), 8),
                    "edge_weight_ratio": round(float(candidate.get("edge_weight_ratio", 0.0)), 8),
                    "candidate_score": round(float(candidate.get("score", 0.0)), 8),
                    "legacy_candidate_score": round(float(candidate.get("legacy_score", 0.0)), 8),
                    "v2_candidate_score": round(float(candidate.get("v2_score", 0.0)), 8),
                    "context_k": int(candidate.get("context_hits", 1) or 1),
                    "matched_span": int(candidate.get("matched_span", 1) or 1),
                    "component_count": int(len(component_refs)),
                    "member_refs": list(component_refs),
                    "component_profile": list(component_state.get("component_profile", []) or []),
                    "component_ledger": list(component_state.get("component_ledger", []) or []),
                    "last_tick_id": str(tick_id or ""),
                }
                try:
                    persist_res = hdb.upsert_cognitive_stitching_event_structure(
                        event_ref_id=str(event_id),
                        member_refs=list(component_refs),
                        display_text=str(event_display or event_id),
                        diff_rows=None,  # keep HDB writes conservative on hot-path; idle_consolidate can fill outgoing edges.
                        trace_id=f"{trace_id}_cs_persist_hot",
                        tick_id=tick_id,
                        reason=f"cognitive_stitching_hot_path:{action_type}",
                        max_diff_entries=int(max_diff_entries),
                        sequence_groups=None,
                        flat_tokens=None,
                        cs_ext=cs_ext,
                        link_members_to_event=True,
                    )
                except Exception as exc:
                    persist_res = {"success": False, "code": "EXCEPTION", "message": str(exc), "data": {"event_ref_id": str(event_id)}}

                if not bool(persist_res.get("success", False)):
                    # If HDB persistence fails, do not create/modify runtime energies (keep the tick conservative).
                    self._audit_apply_skip(candidate=candidate, reason="event_persist_failed")
                    continue
                event_structure_id = str((persist_res.get("data", {}) or {}).get("structure_id", "") or "")
                if not event_structure_id:
                    self._audit_apply_skip(candidate=candidate, reason="event_persist_missing_structure_id")
                    continue

                # Locate existing runtime item by structure_id (primary), then by event_ref_id alias (legacy).
                existing_item = self._get_existing_state_item_by_ref(pool=pool, ref_object_id=event_structure_id)
                if existing_item is None:
                    existing_item = self._get_existing_state_item_by_ref(pool=pool, ref_object_id=event_id)

                if existing_item is not None:
                    action_name = f"reinforce_{action_type}"
                    self._ensure_event_component_state(item=existing_item)
                    event_item_id = str(existing_item.get("id", "") or "")
                    self._safe_bind_ref_alias(pool=pool, item_id=event_item_id, ref_alias_id=event_id)
                    self._safe_apply_energy_update(
                        pool=pool,
                        item_id=event_item_id,
                        delta_er=event_er,
                        delta_ev=event_ev,
                        trace_id=f"{trace_id}_cs_event_update",
                        tick_id=tick_id,
                        reason="cognitive_stitching_reinforce_event",
                    )
                    self._apply_event_component_ledger_delta(
                        item=existing_item,
                        component_refs=list(component_refs),
                        component_displays=self._resolve_component_displays(components=list(component_refs), structure_store=structure_store),
                        source_components=list(source.get("components", []) or []),
                        target_components=list(target.get("components", []) or []),
                        source_absorbed_er=src_er,
                        source_absorbed_ev=src_ev,
                        target_absorbed_er=tgt_er,
                        target_absorbed_ev=tgt_ev,
                    )
                else:
                    runtime_object = hdb.make_runtime_structure_object(
                        event_structure_id,
                        er=float(event_er),
                        ev=float(event_ev),
                        reason="cognitive_stitching_event_create",
                    )
                    if not isinstance(runtime_object, dict):
                        self._audit_apply_skip(candidate=candidate, reason="event_runtime_object_failed")
                        continue
                    if bool(self._config.get("insert_persisted_event_runtime_items_into_state_pool", True)):
                        insert_result = pool.insert_runtime_node(
                            runtime_object=runtime_object,
                            trace_id=f"{trace_id}_cs_insert",
                            tick_id=tick_id,
                            allow_merge=True,
                            source_module="cognitive_stitching",
                            reason="cognitive_stitching_event_create",
                        )
                        event_item_id = str(insert_result.get("data", {}).get("item_id", "") or "")
                        self._safe_bind_ref_alias(pool=pool, item_id=event_item_id, ref_alias_id=event_id)
                    else:
                        event_item_id = ""
            else:
                # Legacy runtime-only event path (event_id is ref_object_id).
                existing_item = self._get_existing_state_item_by_ref(pool=pool, ref_object_id=event_id)
                if existing_item is not None:
                    action_name = f"reinforce_{action_type}"
                    self._ensure_event_component_state(item=existing_item)
                    self._safe_apply_energy_update(
                        pool=pool,
                        item_id=str(existing_item.get("id", "") or ""),
                        delta_er=event_er,
                        delta_ev=event_ev,
                        trace_id=f"{trace_id}_cs_event_update",
                        tick_id=tick_id,
                        reason="cognitive_stitching_reinforce_event",
                    )
                    self._apply_event_component_ledger_delta(
                        item=existing_item,
                        component_refs=list(component_refs),
                        component_displays=self._resolve_component_displays(components=list(component_refs), structure_store=structure_store),
                        source_components=list(source.get("components", []) or []),
                        target_components=list(target.get("components", []) or []),
                        source_absorbed_er=src_er,
                        source_absorbed_ev=src_ev,
                        target_absorbed_er=tgt_er,
                        target_absorbed_ev=tgt_ev,
                    )
                    event_item_id = str(existing_item.get("id", "") or "")
                else:
                    runtime_object = self._build_event_runtime_object(
                        component_refs=list(component_refs),
                        event_id=event_id,
                        event_er=event_er,
                        event_ev=event_ev,
                        candidate=candidate,
                        tick_id=tick_id,
                        hdb=hdb,
                        source_absorbed_er=src_er,
                        source_absorbed_ev=src_ev,
                        target_absorbed_er=tgt_er,
                        target_absorbed_ev=tgt_ev,
                    )
                    if bool(self._config.get("insert_event_runtime_items_into_state_pool", False)):
                        insert_result = pool.insert_runtime_node(
                            runtime_object=runtime_object,
                            trace_id=f"{trace_id}_cs_insert",
                            tick_id=tick_id,
                            allow_merge=True,
                            source_module="cognitive_stitching",
                            reason="cognitive_stitching_event_create",
                        )
                        event_item_id = str(insert_result.get("data", {}).get("item_id", "") or "")
                    else:
                        event_item_id = ""

            if not str(event_item_id or "").strip():
                self._audit_apply_skip(candidate=candidate, reason="event_item_missing")
                continue

            # Debit energy from both sides AFTER we know the event runtime item exists (avoid "energy loss" on failure).
            self._safe_apply_energy_update(
                pool=pool,
                item_id=str(source.get("item_id", "") or ""),
                delta_er=-src_er,
                delta_ev=-src_ev,
                trace_id=f"{trace_id}_cs_deduct",
                tick_id=tick_id,
                reason="cognitive_stitching_absorb_source",
            )
            self._safe_apply_energy_update(
                pool=pool,
                item_id=str(target.get("item_id", "") or ""),
                delta_er=-tgt_er,
                delta_ev=-tgt_ev,
                trace_id=f"{trace_id}_cs_deduct",
                tick_id=tick_id,
                reason="cognitive_stitching_absorb_target",
            )

            # ESDB overlay bookkeeping (parents+delta metadata, runtime-only).
            self._esdb_upsert_event(
                event_ref_id=event_id,
                components=list(component_refs),
                parent_refs=[
                    str(source.get("ref_object_id", "") or ""),
                    str(target.get("ref_object_id", "") or ""),
                ],
                tick_id=tick_id,
                action_type=str(candidate.get("action_type", "") or "create_event"),
            )
            # Delta update: cache a small outgoing edge set from tail components for event_overlay mode.
            try:
                self._esdb_refresh_delta_from_tail_components(
                    event_ref_id=event_id,
                    components=list(component_refs),
                    hdb=hdb,
                    tick_id=tick_id,
                    action_type=str(candidate.get("action_type", "") or "create_event"),
                )
            except Exception:
                pass

            fatigue_after = round(min(fatigue_cap, float(candidate.get("pair_fatigue_before", candidate.get("fatigue_before", 0.0)) or 0.0) + fatigue_step), 8)
            self._pair_fatigue[str(candidate.get("candidate_signature", "") or "")] = fatigue_after
            object_fatigue_after = self._apply_object_stitch_fatigue(
                self._active_item_identity_key(source),
                self._active_item_identity_key(target),
                event_id if bool(self._config.get("object_stitch_fatigue_apply_to_result", True)) else "",
            )
            action_record = {
                "action": action_name,
                "action_family": str(candidate.get("action_type", "") or "create_event"),
                "event_ref_id": event_id,
                "event_structure_id": str(event_structure_id or ""),
                "event_item_id": event_item_id,
                "event_display": event_display,
                "event_component_count": len(list(candidate.get("new_components", []) or [])),
                "source_ref_id": str(source.get("ref_object_id", "") or ""),
                "source_display": str(source.get("display", "") or ""),
                "source_kind": str(source.get("kind", "") or ""),
                "target_ref_id": str(target.get("ref_object_id", "") or ""),
                "target_display": str(target.get("display", "") or ""),
                "target_kind": str(target.get("kind", "") or ""),
                "edge_target_id": str(candidate.get("edge_target_id", "") or ""),
                "match_mode": str(candidate.get("match_mode", "") or ""),
                "matched_span": int(candidate.get("matched_span", 1) or 1),
                "prefix_components": int(candidate.get("prefix_components", 1) or 1),
                "context_k": int(candidate.get("context_hits", 1) or 1),
                "context_distance": int(candidate.get("closest_distance", 0) or 0),
                "score_source": str(candidate.get("score_source", "legacy") or "legacy"),
                "execution_uses_v2_score": bool(candidate.get("execution_uses_v2_score", False)),
                "score": round(score, 8),
                "legacy_score": round(float(candidate.get("legacy_score", 0.0)), 8),
                "v2_score": round(float(candidate.get("v2_score", 0.0)), 8),
                "base_score": round(float(candidate.get("base_score", 0.0)), 8),
                "legacy_base_score": round(float(candidate.get("legacy_base_score", 0.0)), 8),
                "edge_weight": round(float(candidate.get("edge_weight", 0.0)), 8),
                "edge_weight_ratio": round(float(candidate.get("edge_weight_ratio", 0.0)), 8),
                "match_strength": round(float(candidate.get("match_strength", 0.0)), 8),
                "context_ratio": round(float(candidate.get("context_ratio", 0.0)), 8),
                "last_token_score": round(float(candidate.get("last_token_score", 0.0) or 0.0), 8),
                "contiguous_ratio": round(float(candidate.get("contiguous_ratio", 0.0) or 0.0), 8),
                "gap_ratio": round(float(candidate.get("gap_ratio", 0.0) or 0.0), 8),
                "energy_balance": round(float(candidate.get("energy_balance", 0.0)), 8),
                "runtime_balance": round(float(candidate.get("runtime_balance", 0.0)), 8),
                "bridge_span_ratio": round(float(candidate.get("bridge_span_ratio", 0.0)), 8),
                "anchor_scale": round(float(candidate.get("anchor_scale", 0.0)), 8),
                "absorb_ratio": absorb_ratio,
                "absorbed_er": event_er,
                "absorbed_ev": event_ev,
                "absorbed_total": event_total,
                "source_absorbed_er": src_er,
                "source_absorbed_ev": src_ev,
                "source_absorbed_total": round(float(src_er + src_ev), 8),
                "target_absorbed_er": tgt_er,
                "target_absorbed_ev": tgt_ev,
                "target_absorbed_total": round(float(tgt_er + tgt_ev), 8),
                "fatigue_before": round(float(candidate.get("fatigue_before", 0.0)), 8),
                "fatigue_scale": round(float(candidate.get("fatigue_scale", 0.0)), 8),
                "pair_fatigue_before": round(float(candidate.get("pair_fatigue_before", candidate.get("fatigue_before", 0.0)) or 0.0), 8),
                "pair_fatigue_scale": round(float(candidate.get("pair_fatigue_scale", 1.0) or 1.0), 8),
                "object_stitch_fatigue_before": round(float(candidate.get("object_stitch_fatigue_before", 0.0) or 0.0), 8),
                "object_stitch_fatigue_scale": round(float(candidate.get("object_stitch_fatigue_scale", 1.0) or 1.0), 8),
                "object_stitch_fatigue_refs": list(candidate.get("object_stitch_fatigue_refs", []) or []),
                "object_stitch_fatigue_after": dict(object_fatigue_after),
                "min_candidate_score": round(float(candidate.get("min_candidate_score", 0.0)), 8),
                "legacy_min_candidate_score": round(float(candidate.get("legacy_min_candidate_score", 0.0)), 8),
                "threshold_margin": round(float(candidate.get("threshold_margin", 0.0)), 8),
                "legacy_threshold_margin": round(float(candidate.get("legacy_threshold_margin", 0.0)), 8),
                "edge_ratio_component": round(float(candidate.get("edge_ratio_component", 0.0)), 8),
                "energy_balance_component": round(float(candidate.get("energy_balance_component", 0.0)), 8),
                "match_strength_component": round(float(candidate.get("match_strength_component", 0.0)), 8),
                "runtime_balance_component": round(float(candidate.get("runtime_balance_component", 0.0)), 8),
                "context_support_component": round(float(candidate.get("context_support_component", 0.0)), 8),
                "bridge_span_component": round(float(candidate.get("bridge_span_component", 0.0)), 8),
                "fatigue_after": fatigue_after,
            }
            actions.append(action_record)
            self._audit_apply_action(action_record)
            consumed_item_ids.update({source_item_id, target_item_id})
        return actions

    def _candidate_absorb_ratio(
        self,
        *,
        candidate: dict,
        score: float,
        base_ratio: float,
        cap_ratio: float,
    ) -> float:
        action_type = str(candidate.get("action_type", "") or "")
        match_mode = str(candidate.get("match_mode", "") or "")
        context_ratio = self._clamp01(float(candidate.get("context_ratio", 0.0) or 0.0))
        last_token_score = self._clamp01(float(candidate.get("last_token_score", 0.0) or 0.0))
        contiguous_ratio = self._clamp01(float(candidate.get("contiguous_ratio", 0.0) or 0.0))
        absorb_scale = max(0.0, float(candidate.get("absorb_scale", 1.0) or 1.0))
        is_exact_context = (
            action_type == "concat_context_structure"
            and match_mode == "context_tail_exact"
            and context_ratio >= 0.999
            and last_token_score >= 0.999
        )
        if is_exact_context:
            exact_base = self._clamp01(float(self._config.get("context_concat_exact_absorb_ratio", 0.94) or 0.94))
            exact_cap = self._clamp01(float(self._config.get("context_concat_exact_absorb_cap", 0.98) or 0.98))
            quality = self._clamp01(max(context_ratio, contiguous_ratio) * max(0.0, absorb_scale))
            return round(min(exact_cap, exact_base * max(0.0, min(1.0, quality))), 8)
        return round(
            min(
                cap_ratio,
                base_ratio * (0.55 + max(0.0, float(score))) * absorb_scale,
            ),
            8,
        )

    def _candidate_absorbed_energy(
        self,
        *,
        source: dict,
        target: dict,
        absorb_ratio: float,
        use_lower_energy_cap: bool,
    ) -> tuple[float, float, float, float]:
        source_er = max(0.0, float(source.get("er", 0.0) or 0.0))
        source_ev = max(0.0, float(source.get("ev", 0.0) or 0.0))
        target_er = max(0.0, float(target.get("er", 0.0) or 0.0))
        target_ev = max(0.0, float(target.get("ev", 0.0) or 0.0))
        source_total = source_er + source_ev
        target_total = target_er + target_ev
        ratio = max(0.0, float(absorb_ratio))
        if not use_lower_energy_cap:
            return (
                round(source_er * ratio, 8),
                round(source_ev * ratio, 8),
                round(target_er * ratio, 8),
                round(target_ev * ratio, 8),
            )
        lower_total = min(source_total, target_total)
        if lower_total <= 1e-12:
            return 0.0, 0.0, 0.0, 0.0
        source_cap = min(source_total, lower_total) * ratio
        target_cap = min(target_total, lower_total) * ratio
        source_scale = source_cap / source_total if source_total > 1e-12 else 0.0
        target_scale = target_cap / target_total if target_total > 1e-12 else 0.0
        return (
            round(source_er * source_scale, 8),
            round(source_ev * source_scale, 8),
            round(target_er * target_scale, 8),
            round(target_ev * target_scale, 8),
        )

    def _apply_context_concat_candidate(
        self,
        *,
        candidate: dict,
        pool,
        hdb,
        trace_id: str,
        tick_id: str,
        source: dict,
        target: dict,
        src_er: float,
        src_ev: float,
        tgt_er: float,
        tgt_ev: float,
        structure_er: float,
        structure_ev: float,
        structure_total: float,
        absorb_ratio: float,
        fatigue_step: float,
        fatigue_cap: float,
    ) -> dict | None:
        upsert = self._upsert_context_concat_structure(
            candidate=candidate,
            hdb=hdb,
            trace_id=trace_id,
            tick_id=tick_id,
            source=source,
            target=target,
            structure_total=structure_total,
        )
        if not upsert:
            return None

        structure_obj = upsert.get("structure_obj") if isinstance(upsert.get("structure_obj"), dict) else None
        if not isinstance(structure_obj, dict):
            return None
        structure_id = str(structure_obj.get("id", "") or "")
        if not structure_id:
            return None

        runtime_item = self._get_existing_state_item_by_ref(pool=pool, ref_object_id=structure_id)
        action_name = "concat_context_structure"
        structure_item_id = ""
        if runtime_item is not None:
            action_name = "reinforce_concat_context_structure"
            structure_item_id = str(runtime_item.get("id", "") or "")
            self._safe_apply_energy_update(
                pool=pool,
                item_id=structure_item_id,
                delta_er=structure_er,
                delta_ev=structure_ev,
                trace_id=f"{trace_id}_cs_concat_reinforce",
                tick_id=tick_id,
                reason="cognitive_stitching_context_concat_reinforce",
            )
        else:
            runtime_builder = getattr(hdb, "make_runtime_structure_object", None)
            if not callable(runtime_builder):
                return None
            runtime_object = runtime_builder(
                structure_id,
                er=float(structure_er),
                ev=float(structure_ev),
                reason="cognitive_stitching_context_concat",
            )
            if not isinstance(runtime_object, dict):
                return None
            insert_result = pool.insert_runtime_node(
                runtime_object=runtime_object,
                trace_id=f"{trace_id}_cs_concat_insert",
                tick_id=tick_id,
                allow_merge=True,
                source_module="cognitive_stitching",
                reason="cognitive_stitching_context_concat",
            )
            insert_data = insert_result.get("data", {}) if isinstance(insert_result.get("data", {}), dict) else {}
            structure_item_id = str(insert_data.get("item_id", "") or insert_data.get("target_item_id", "") or "").strip()
            if not structure_item_id:
                return None

        self._safe_apply_energy_update(
            pool=pool,
            item_id=str(source.get("item_id", "") or ""),
            delta_er=-src_er,
            delta_ev=-src_ev,
            trace_id=f"{trace_id}_cs_concat_deduct",
            tick_id=tick_id,
            reason="cognitive_stitching_context_concat_absorb_source",
        )
        self._safe_apply_energy_update(
            pool=pool,
            item_id=str(target.get("item_id", "") or ""),
            delta_er=-tgt_er,
            delta_ev=-tgt_ev,
            trace_id=f"{trace_id}_cs_concat_deduct",
            tick_id=tick_id,
            reason="cognitive_stitching_context_concat_absorb_target",
        )

        fatigue_after = round(min(fatigue_cap, float(candidate.get("pair_fatigue_before", candidate.get("fatigue_before", 0.0)) or 0.0) + fatigue_step), 8)
        self._pair_fatigue[str(candidate.get("candidate_signature", "") or "")] = fatigue_after
        object_fatigue_after = self._apply_object_stitch_fatigue(
            self._active_item_identity_key(source),
            self._active_item_identity_key(target),
            structure_id if bool(self._config.get("object_stitch_fatigue_apply_to_result", True)) else "",
        )
        return {
            "action": action_name,
            "action_family": "concat_context_structure",
            "structure_id": structure_id,
            "structure_item_id": structure_item_id,
            "structure_display": str(candidate.get("result_display", "") or ""),
            "context_owner_id": str(candidate.get("result_context_owner_id", "") or ""),
            "context_ref_object_id": str(candidate.get("result_context_ref_object_id", "") or ""),
            "context_path_ids": list(candidate.get("result_context_path_ids", []) or []),
            "context_text": str(candidate.get("result_context_text", "") or ""),
            "source_ref_id": str(source.get("ref_object_id", "") or ""),
            "source_display": str(source.get("display", "") or ""),
            "source_kind": str(source.get("kind", "") or ""),
            "source_projected_from_non_st_support": bool(source.get("projected_from_non_st_support", False)),
            "source_runtime_ref_object_id": str(source.get("runtime_ref_object_id", "") or ""),
            "source_runtime_ref_object_type": str(source.get("runtime_ref_object_type", "") or ""),
            "source_support_structure_ids": list(source.get("support_structure_ids", []) or []),
            "target_ref_id": str(target.get("ref_object_id", "") or ""),
            "target_display": str(target.get("display", "") or ""),
            "target_kind": str(target.get("kind", "") or ""),
            "target_projected_from_non_st_support": bool(target.get("projected_from_non_st_support", False)),
            "target_runtime_ref_object_id": str(target.get("runtime_ref_object_id", "") or ""),
            "target_runtime_ref_object_type": str(target.get("runtime_ref_object_type", "") or ""),
            "target_support_structure_ids": list(target.get("support_structure_ids", []) or []),
            "edge_target_id": str(candidate.get("edge_target_id", "") or ""),
            "match_mode": str(candidate.get("match_mode", "") or ""),
            "matched_span": int(candidate.get("matched_span", 1) or 1),
            "prefix_components": int(candidate.get("prefix_components", 1) or 1),
            "context_k": int(candidate.get("context_hits", 1) or 1),
            "context_distance": int(candidate.get("closest_distance", 0) or 0),
            "score_source": str(candidate.get("score_source", "legacy") or "legacy"),
            "execution_uses_v2_score": bool(candidate.get("execution_uses_v2_score", False)),
            "score": round(float(candidate.get("score", 0.0) or 0.0), 8),
            "legacy_score": round(float(candidate.get("legacy_score", 0.0) or 0.0), 8),
            "v2_score": round(float(candidate.get("v2_score", 0.0) or 0.0), 8),
            "base_score": round(float(candidate.get("base_score", 0.0) or 0.0), 8),
            "legacy_base_score": round(float(candidate.get("legacy_base_score", 0.0) or 0.0), 8),
            "edge_weight": round(float(candidate.get("edge_weight", 0.0) or 0.0), 8),
            "edge_weight_ratio": round(float(candidate.get("edge_weight_ratio", 0.0) or 0.0), 8),
            "match_strength": round(float(candidate.get("match_strength", 0.0) or 0.0), 8),
            "context_ratio": round(float(candidate.get("context_ratio", 0.0) or 0.0), 8),
            "last_token_score": round(float(candidate.get("last_token_score", 0.0) or 0.0), 8),
            "contiguous_ratio": round(float(candidate.get("contiguous_ratio", 0.0) or 0.0), 8),
            "gap_ratio": round(float(candidate.get("gap_ratio", 0.0) or 0.0), 8),
            "target_context_prefix_trimmed": bool(candidate.get("target_context_prefix_trimmed", False)),
            "target_context_prefix_trim_count": int(candidate.get("target_context_prefix_trim_count", 0) or 0),
            "exact_context_identity_match": bool(candidate.get("exact_context_identity_match", False)),
            "energy_balance": round(float(candidate.get("energy_balance", 0.0) or 0.0), 8),
            "runtime_balance": round(float(candidate.get("runtime_balance", 0.0) or 0.0), 8),
            "bridge_span_ratio": round(float(candidate.get("bridge_span_ratio", 0.0) or 0.0), 8),
            "anchor_scale": round(float(candidate.get("anchor_scale", 0.0) or 0.0), 8),
            "absorb_ratio": round(float(absorb_ratio), 8),
            "absorbed_er": round(float(structure_er), 8),
            "absorbed_ev": round(float(structure_ev), 8),
            "absorbed_total": round(float(structure_total), 8),
            "source_absorbed_er": round(float(src_er), 8),
            "source_absorbed_ev": round(float(src_ev), 8),
            "source_absorbed_total": round(float(src_er + src_ev), 8),
            "target_absorbed_er": round(float(tgt_er), 8),
            "target_absorbed_ev": round(float(tgt_ev), 8),
            "target_absorbed_total": round(float(tgt_er + tgt_ev), 8),
            "fatigue_before": round(float(candidate.get("fatigue_before", 0.0)), 8),
            "fatigue_scale": round(float(candidate.get("fatigue_scale", 0.0)), 8),
            "pair_fatigue_before": round(float(candidate.get("pair_fatigue_before", candidate.get("fatigue_before", 0.0)) or 0.0), 8),
            "pair_fatigue_scale": round(float(candidate.get("pair_fatigue_scale", 1.0) or 1.0), 8),
            "object_stitch_fatigue_before": round(float(candidate.get("object_stitch_fatigue_before", 0.0) or 0.0), 8),
            "object_stitch_fatigue_scale": round(float(candidate.get("object_stitch_fatigue_scale", 1.0) or 1.0), 8),
            "object_stitch_fatigue_refs": list(candidate.get("object_stitch_fatigue_refs", []) or []),
            "object_stitch_fatigue_after": dict(object_fatigue_after),
            "min_candidate_score": round(float(candidate.get("min_candidate_score", 0.0)), 8),
            "legacy_min_candidate_score": round(float(candidate.get("legacy_min_candidate_score", 0.0)), 8),
            "threshold_margin": round(float(candidate.get("threshold_margin", 0.0)), 8),
            "legacy_threshold_margin": round(float(candidate.get("legacy_threshold_margin", 0.0)), 8),
            "edge_ratio_component": round(float(candidate.get("edge_ratio_component", 0.0)), 8),
            "energy_balance_component": round(float(candidate.get("energy_balance_component", 0.0)), 8),
            "match_strength_component": round(float(candidate.get("match_strength_component", 0.0)), 8),
            "runtime_balance_component": round(float(candidate.get("runtime_balance_component", 0.0)), 8),
            "context_support_component": round(float(candidate.get("context_support_component", 0.0)), 8),
            "bridge_span_component": round(float(candidate.get("bridge_span_component", 0.0)), 8),
            "match_count_score": round(float(candidate.get("match_count_score", 0.0) or 0.0), 8),
            "attribute_bonus_score": round(float(candidate.get("attribute_bonus_score", 0.0) or 0.0), 8),
            "match_count_component": round(float(candidate.get("match_count_component", 0.0) or 0.0), 8),
            "attribute_bonus_component": round(float(candidate.get("attribute_bonus_component", 0.0) or 0.0), 8),
            "effective_match_units": round(float(candidate.get("effective_match_units", 0.0) or 0.0), 8),
            "attribute_bonus_equivalent_units": round(float(candidate.get("attribute_bonus_equivalent_units", 0.0) or 0.0), 8),
            "v2_match_count_score": round(float(candidate.get("v2_match_count_score", 0.0) or 0.0), 8),
            "v2_attribute_bonus_score": round(float(candidate.get("v2_attribute_bonus_score", 0.0) or 0.0), 8),
            "fatigue_after": fatigue_after,
            "created_structure": bool(upsert.get("created", False)),
            "existing_structure_reused": bool(upsert.get("reused", False)),
        }

    def _upsert_context_concat_structure(
        self,
        *,
        candidate: dict,
        hdb,
        trace_id: str,
        tick_id: str,
        source: dict,
        target: dict,
        structure_total: float,
    ) -> dict | None:
        structure_store = getattr(hdb, "_structure_store", None)
        if structure_store is None or not hasattr(structure_store, "create_structure"):
            return None

        result_tokens = [str(token) for token in (candidate.get("result_tokens", []) or []) if str(token)]
        result_display = str(candidate.get("result_display", "") or "").strip() or "".join(result_tokens)
        result_groups = list(candidate.get("result_sequence_groups", []) or [])
        context_owner_id = str(candidate.get("result_context_owner_id", "") or "")
        context_ref_object_id = str(candidate.get("result_context_ref_object_id", "") or context_owner_id)
        context_path_ids = self._dedupe_ids(candidate.get("result_context_path_ids", []) or [])
        content_signature = str(candidate.get("result_content_signature", "") or self._tokens_signature(hdb=hdb, tokens=result_tokens))
        confidence = max(0.0, min(1.0, float(self._config.get("context_concat_result_confidence", 0.82) or 0.82)))
        cs_ext = {
            "stage": "phase2_contextual_event_stitching",
            "action_type": "concat_context_structure",
            "score_source": str(candidate.get("score_source", "legacy") or "legacy"),
            "execution_uses_v2_score": bool(candidate.get("execution_uses_v2_score", False)),
            "source_ref_id": str(source.get("ref_object_id", "") or ""),
            "target_ref_id": str(target.get("ref_object_id", "") or ""),
            "candidate_score": round(float(candidate.get("score", 0.0) or 0.0), 8),
            "legacy_candidate_score": round(float(candidate.get("legacy_score", 0.0) or 0.0), 8),
            "v2_candidate_score": round(float(candidate.get("v2_score", 0.0) or 0.0), 8),
            "match_mode": str(candidate.get("match_mode", "") or ""),
            "match_strength": round(float(candidate.get("match_strength", 0.0) or 0.0), 8),
            "edge_weight_ratio": round(float(candidate.get("edge_weight_ratio", 0.0) or 0.0), 8),
            "context_ratio": round(float(candidate.get("context_ratio", 0.0) or 0.0), 8),
            "context_text": str(candidate.get("result_context_text", "") or ""),
            "context_owner_structure_id": context_owner_id,
            "context_ref_object_id": context_ref_object_id,
            "context_path_ids": list(context_path_ids),
            "path_support_score": round(float(candidate.get("path_support_score", 0.0) or 0.0), 8),
            "direct_owner_score": round(float(candidate.get("direct_owner_score", 0.0) or 0.0), 8),
            "exact_context_identity_match": bool(candidate.get("exact_context_identity_match", False)),
            "last_token_score": round(float(candidate.get("last_token_score", 0.0) or 0.0), 8),
            "contiguous_ratio": round(float(candidate.get("contiguous_ratio", 0.0) or 0.0), 8),
            "structure_total": round(float(structure_total), 8),
            "last_tick_id": str(tick_id or ""),
        }

        payload: dict[str, Any]
        cut = getattr(hdb, "_cut", None)
        if cut is not None and result_groups and hasattr(cut, "build_sequence_profile_from_groups") and hasattr(cut, "make_structure_payload_from_profile"):
            try:
                profile = cut.build_sequence_profile_from_groups(result_groups)
                payload = cut.make_structure_payload_from_profile(profile, confidence=confidence, ext={"cognitive_stitching": cs_ext})
            except Exception:
                payload = {}
        else:
            payload = {}
        if not payload:
            if cut is not None and hasattr(cut, "make_structure_payload_from_tokens"):
                try:
                    payload = cut.make_structure_payload_from_tokens(result_tokens, confidence=confidence, ext={"cognitive_stitching": cs_ext})
                except Exception:
                    payload = {}
            if not payload:
                payload = {
                    "display_text": result_display,
                    "member_refs": [],
                    "sequence_groups": list(result_groups),
                    "flat_tokens": list(result_tokens),
                    "content_signature": content_signature,
                    "semantic_signature": content_signature,
                    "confidence": confidence,
                    "ext": {"cognitive_stitching": cs_ext},
                }

        payload["display_text"] = result_display
        payload["sequence_groups"] = list(result_groups or payload.get("sequence_groups", []) or [])
        payload["flat_tokens"] = list(result_tokens or payload.get("flat_tokens", []) or [])
        payload["content_signature"] = str(payload.get("content_signature", "") or content_signature)
        payload["semantic_signature"] = str(payload.get("semantic_signature", "") or payload["content_signature"])
        payload_ext = dict(payload.get("ext", {}) or {})
        payload_ext.update(
            {
                "context_ref_object_id": context_ref_object_id,
                "context_ref_object_type": "st",
                "context_owner_structure_id": context_owner_id,
                "context_path_ids": list(context_path_ids),
                "context_text": str(candidate.get("result_context_text", "") or ""),
                "concat_source_ref_id": str(source.get("ref_object_id", "") or ""),
                "concat_target_ref_id": str(target.get("ref_object_id", "") or ""),
                "concat_parent_refs": [
                    str(source.get("ref_object_id", "") or ""),
                    str(target.get("ref_object_id", "") or ""),
                ],
                "cognitive_stitching": cs_ext,
            }
        )
        payload["ext"] = payload_ext
        payload.setdefault(
            "meta",
            {
                "confidence": confidence,
                "field_registry_version": "1.1",
                "debug": {},
                "ext": dict(payload_ext),
            },
        )

        result = resolve_or_create_structure_from_profile(
            profile={
                "display_text": str(payload.get("display_text", "") or ""),
                "sequence_groups": list(payload.get("sequence_groups", []) or []),
                "flat_tokens": list(payload.get("flat_tokens", []) or []),
                "content_signature": str(payload.get("content_signature", "") or ""),
                "semantic_signature": str(payload.get("semantic_signature", "") or payload.get("content_signature", "") or ""),
                "ext": dict(payload_ext),
            },
            structure_store=structure_store,
            pointer_index=getattr(hdb, "_pointer_index", None),
            cut_engine=cut,
            trace_id=f"{trace_id}_cs_concat_create",
            tick_id=tick_id,
            confidence=float(confidence),
            origin="cognitive_stitching_context_concat",
            origin_id=str(payload.get("content_signature", "") or ""),
            parent_ids=[context_owner_id] if context_owner_id else [],
            ext=dict(payload_ext),
            source_interface="cognitive_stitching_context_concat",
            strict_context_owner_match=bool(context_owner_id),
            strict_context_ref_match=bool(context_ref_object_id),
        )
        structure_obj = result.get("structure") if isinstance(result, dict) else None
        if not isinstance(structure_obj, dict):
            return {"structure_obj": None, "created": False, "reused": False}
        created = bool(result.get("created", False))
        reused = not created

        if context_owner_id and hasattr(structure_store, "add_diff_entry"):
            try:
                link_weight = max(0.05, min(1.6, 0.22 + float(candidate.get("score", 0.0) or 0.0) + 0.08 * math.sqrt(max(0.0, float(structure_total)))))
                structure_store.add_diff_entry(
                    context_owner_id,
                    target_id=str(structure_obj.get("id", "") or ""),
                    content_signature=str(payload.get("content_signature", "") or ""),
                    base_weight=float(link_weight),
                    entry_type="structure_ref",
                    ext={
                        "relation_type": "context_concat_structure",
                        "context_ref_object_id": context_ref_object_id,
                        "context_ref_object_type": "st",
                        "context_owner_structure_id": context_owner_id,
                        "context_path_ids": list(context_path_ids),
                        "context_text": str(candidate.get("result_context_text", "") or ""),
                        "concat_source_ref_id": str(source.get("ref_object_id", "") or ""),
                        "concat_target_ref_id": str(target.get("ref_object_id", "") or ""),
                        "candidate_score": round(float(candidate.get("score", 0.0) or 0.0), 8),
                        "last_tick_id": str(tick_id or ""),
                    },
                )
            except Exception:
                pass

        return {"structure_obj": structure_obj, "created": created, "reused": reused}

    def _find_existing_contextual_structure(
        self,
        *,
        hdb,
        content_signature: str,
        flat_tokens: list[str],
        context_owner_id: str,
        context_ref_object_id: str,
    ) -> dict | None:
        if not content_signature:
            return None
        structure_store = getattr(hdb, "_structure_store", None)
        if structure_store is None:
            return None
        pointer_index = getattr(hdb, "_pointer_index", None)
        candidate_ids: list[str] = []
        if pointer_index is not None and hasattr(pointer_index, "query_candidates_by_signature"):
            try:
                candidate_ids.extend(pointer_index.query_candidates_by_signature(content_signature))
            except Exception:
                candidate_ids = []
        if not candidate_ids and hasattr(structure_store, "iter_structures"):
            try:
                candidate_ids.extend(
                    str(obj.get("id", "") or "")
                    for obj in structure_store.iter_structures()
                    if isinstance(obj, dict)
                    and str((obj.get("structure", {}) or {}).get("content_signature", "") or "") == content_signature
                )
            except Exception:
                candidate_ids = []
        seen: set[str] = set()
        for candidate_id in candidate_ids:
            text_id = str(candidate_id or "")
            if not text_id or text_id in seen:
                continue
            seen.add(text_id)
            structure_obj = structure_store.get(text_id) if hasattr(structure_store, "get") else None
            if not isinstance(structure_obj, dict):
                continue
            if self._is_cognitive_stitching_event_structure_obj(structure_obj):
                continue
            structure_block = structure_obj.get("structure", {}) if isinstance(structure_obj.get("structure", {}), dict) else {}
            structure_ext = structure_block.get("ext", {}) if isinstance(structure_block.get("ext", {}), dict) else {}
            if str(structure_block.get("content_signature", "") or "") != content_signature:
                continue
            if list(structure_block.get("flat_tokens", []) or []) != list(flat_tokens):
                continue
            if str(structure_ext.get("context_owner_structure_id", "") or "") != str(context_owner_id or ""):
                continue
            if str(structure_ext.get("context_ref_object_id", "") or "") != str(context_ref_object_id or ""):
                continue
            return structure_obj
        return None

    def _maybe_degenerate_events(self, *, pool, hdb, trace_id: str, tick_id: str) -> dict[str, Any]:
        """
        Event degeneration / 事件退化（组分淘汰）
        ---------------------------------------

        Goal:
        - When a CS event contains some very weak components, the event may "degenerate"
          into a shorter event. This keeps long-run event structures healthy and avoids
          "ultra-long / noisy events" dominating the pool.

        What we guarantee:
        - If persistence is enabled, the degenerated event is persisted into HDB via
          `upsert_cognitive_stitching_event_structure`, so the new structure is indexable
          and discoverable by stimulus-level retrieval (when enabled).
        - Energy conservation: we move ER/EV from the old event item to the new/target
          event item, then set the old one to ~0 energy (so it will be pruned naturally).

        Design constraints:
        - Purely numeric rules (share + absolute energy); no semantic hacks.
        - Bounded work per tick.
        - Best-effort: never raising to avoid breaking the main tick pipeline.
        """
        enabled = bool(self._config.get("enable_event_degeneration", True))
        max_events = int(self._config.get("event_degeneration_max_events_per_tick", 2) or 2)
        max_events = max(0, min(32, max_events))
        min_components = int(self._config.get("event_degeneration_min_components", 2) or 2)
        min_components = max(2, min(16, min_components))
        share_threshold = float(self._config.get("event_degeneration_share_threshold", 0.06) or 0.06)
        share_threshold = max(0.0, min(1.0, share_threshold))
        min_component_energy = float(self._config.get("event_degeneration_min_component_energy", 0.04) or 0.04)
        min_component_energy = max(0.0, float(min_component_energy))

        if not enabled:
            return {
                "enabled": False,
                "reason": "disabled_by_config",
                "max_events_per_tick": int(max_events),
                "min_components": int(min_components),
                "share_threshold": float(share_threshold),
                "min_component_energy": float(min_component_energy),
                "degenerated_count": 0,
                "actions_preview": [],
            }

        persist_enabled = (
            bool(self._config.get("enable_persist_events_to_hdb", False))
            and hasattr(hdb, "upsert_cognitive_stitching_event_structure")
            and hasattr(hdb, "make_runtime_structure_object")
        )
        if not persist_enabled:
            return {
                "enabled": True,
                "reason": "persist_disabled",
                "max_events_per_tick": int(max_events),
                "min_components": int(min_components),
                "share_threshold": float(share_threshold),
                "min_component_energy": float(min_component_energy),
                "degenerated_count": 0,
                "actions_preview": [],
            }

        store = getattr(pool, "_store", None)
        if store is None or not hasattr(store, "get_all"):
            return {
                "enabled": True,
                "reason": "pool_store_missing",
                "max_events_per_tick": int(max_events),
                "min_components": int(min_components),
                "share_threshold": float(share_threshold),
                "min_component_energy": float(min_component_energy),
                "degenerated_count": 0,
                "actions_preview": [],
            }

        structure_store = getattr(hdb, "_structure_store", None)
        max_diff_entries = int(self._config.get("persist_events_max_diff_entries", 96) or 96)
        max_diff_entries = max(0, min(512, max_diff_entries))

        # Pick candidate events by total energy (descending).
        try:
            raw_items = [item for item in list(store.get_all()) if self._is_cognitive_stitching_event_state_item(item)]
        except Exception:
            raw_items = []
        raw_items.sort(
            key=lambda it: float((it.get("energy", {}) or {}).get("er", 0.0) or 0.0) + float((it.get("energy", {}) or {}).get("ev", 0.0) or 0.0),
            reverse=True,
        )

        actions: list[dict[str, Any]] = []
        handled = 0
        for item in raw_items:
            if max_events <= 0 or handled >= max_events:
                break

            source_item_id = str(item.get("id", "") or "").strip()
            if not source_item_id:
                continue

            # Canonical event id (cs_event::<...>) and its component list.
            old_event_ref_id = self._extract_event_ref_id_from_state_item(item)
            if not old_event_ref_id or not self._is_event_ref_id(old_event_ref_id):
                continue
            old_components = list(self._parse_event_components(old_event_ref_id))
            if len(old_components) <= min_components:
                continue

            energy = item.get("energy", {}) if isinstance(item.get("energy", {}), dict) else {}
            old_er = round(max(0.0, float(energy.get("er", 0.0) or 0.0)), 8)
            old_ev = round(max(0.0, float(energy.get("ev", 0.0) or 0.0)), 8)
            old_total = round(old_er + old_ev, 8)
            if old_total <= 1e-9:
                continue

            # Extract component shares from ledger (if present). If missing, fall back to uniform shares.
            cs_meta = self._ensure_event_component_state(item=item)
            ledger = list((cs_meta or {}).get("component_ledger", []) or [])
            share_by_ref_raw: dict[str, float] = {}
            for entry in ledger:
                if not isinstance(entry, dict):
                    continue
                ref_id = str(entry.get("ref_id", "") or "").strip()
                if not ref_id:
                    continue
                try:
                    share_by_ref_raw[ref_id] = max(0.0, float(entry.get("profile_share", 0.0) or 0.0))
                except Exception:
                    continue

            shares: dict[str, float] = {}
            if share_by_ref_raw:
                total_share = 0.0
                for ref_id in old_components:
                    total_share += float(share_by_ref_raw.get(ref_id, 0.0) or 0.0)
                if total_share > 1e-9:
                    for ref_id in old_components:
                        shares[ref_id] = float(share_by_ref_raw.get(ref_id, 0.0) or 0.0) / total_share

            if not shares:
                uniform = 1.0 / float(max(1, len(old_components)))
                shares = {ref_id: uniform for ref_id in old_components}

            removed: list[str] = []
            kept: list[str] = []
            for ref_id in old_components:
                share = float(shares.get(ref_id, 0.0) or 0.0)
                component_energy = share * old_total
                if share < share_threshold and component_energy < min_component_energy:
                    removed.append(ref_id)
                else:
                    kept.append(ref_id)

            # If we would collapse below the minimum component count, keep the strongest components as a skeleton.
            # 若阈值规则会把事件“全部删光/删到不足最少保留组分数”，则保留最强的若干组分作为骨架，
            # 让超长事件能够自然退化为更短、可叙事的核心事件。
            if len(kept) < min_components and len(old_components) >= min_components:
                kept_set = set(kept)
                ranked = sorted(
                    list(old_components),
                    key=lambda rid: (
                        float(shares.get(rid, 0.0) or 0.0),
                        float(shares.get(rid, 0.0) or 0.0) * float(old_total),
                    ),
                    reverse=True,
                )
                for rid in ranked:
                    if rid in kept_set:
                        continue
                    kept.append(rid)
                    kept_set.add(rid)
                    if len(kept) >= min_components:
                        break
                removed = [rid for rid in old_components if rid not in kept_set]

            # Guard: do not degenerate if nothing is removed, or we would collapse below min_components.
            if not removed:
                continue
            if len(kept) < min_components:
                continue

            new_event_ref_id = self._event_ref_id_from_components(kept)
            if not new_event_ref_id or new_event_ref_id == old_event_ref_id:
                continue

            # Persist (or resolve) the new event structure in HDB.
            new_displays = self._resolve_component_displays(components=list(kept), structure_store=structure_store)
            new_display_text = self._event_display_from_components(new_displays) or str(new_event_ref_id)
            try:
                persist_res = hdb.upsert_cognitive_stitching_event_structure(
                    event_ref_id=str(new_event_ref_id),
                    member_refs=list(kept),
                    display_text=str(new_display_text),
                    diff_rows=None,
                    trace_id=f"{trace_id}_cs_degenerate",
                    tick_id=tick_id,
                    reason="cognitive_stitching_event_degeneration",
                    max_diff_entries=int(max_diff_entries),
                    sequence_groups=None,
                    flat_tokens=None,
                    cs_ext={
                        "stage": "event_degeneration",
                        "source_event_ref_id": str(old_event_ref_id),
                        "removed_component_refs": list(removed),
                        "kept_component_refs": list(kept),
                        "last_tick_id": str(tick_id or ""),
                    },
                    link_members_to_event=True,
                )
            except Exception as exc:
                persist_res = {"success": False, "code": "EXCEPTION", "message": str(exc), "data": {}}
            if not bool(persist_res.get("success", False)):
                continue
            new_structure_id = str((persist_res.get("data", {}) or {}).get("structure_id", "") or "").strip()
            if not new_structure_id:
                continue

            # Locate or create the target runtime item, then move energy into it.
            target_item = self._get_existing_state_item_by_ref(pool=pool, ref_object_id=new_structure_id) or self._get_existing_state_item_by_ref(pool=pool, ref_object_id=new_event_ref_id)
            target_item_id = str((target_item or {}).get("id", "") or "").strip()
            created_target_item = False

            if target_item is None:
                runtime_object = hdb.make_runtime_structure_object(
                    new_structure_id,
                    er=float(old_er),
                    ev=float(old_ev),
                    reason="cognitive_stitching_event_degeneration",
                )
                if not isinstance(runtime_object, dict):
                    continue
                insert_res = pool.insert_runtime_node(
                    runtime_object=runtime_object,
                    trace_id=f"{trace_id}_cs_degenerate_insert",
                    tick_id=tick_id,
                    allow_merge=True,  # safe: we already checked get_by_ref; allow semantic merge if needed
                    source_module="cognitive_stitching",
                    reason="cognitive_stitching_event_degeneration",
                )
                insert_data = insert_res.get("data", {}) if isinstance(insert_res.get("data", {}), dict) else {}
                target_item_id = str(insert_data.get("item_id", "") or insert_data.get("target_item_id", "") or "").strip()
                if not target_item_id:
                    continue
                created_target_item = bool(insert_data.get("inserted", False)) and not bool(insert_data.get("merged", False))
            else:
                # Transfer-in to an existing item.
                self._safe_apply_energy_update(
                    pool=pool,
                    item_id=target_item_id,
                    delta_er=float(old_er),
                    delta_ev=float(old_ev),
                    trace_id=f"{trace_id}_cs_degenerate_in",
                    tick_id=tick_id,
                    reason="cognitive_stitching_event_degeneration_transfer_in",
                )

            # Bind the canonical event_ref_id as an alias to the target item.
            self._safe_bind_ref_alias(pool=pool, item_id=target_item_id, ref_alias_id=new_event_ref_id)

            # Transfer-out from the old event item (energy conservation).
            self._safe_apply_energy_update(
                pool=pool,
                item_id=source_item_id,
                delta_er=-float(old_er),
                delta_ev=-float(old_ev),
                trace_id=f"{trace_id}_cs_degenerate_out",
                tick_id=tick_id,
                reason="cognitive_stitching_event_degeneration_transfer_out",
            )

            # Patch a fresh component ledger onto the target item (so later component-neutralization is well-defined).
            try:
                target_state_item = store.get(target_item_id) if hasattr(store, "get") else None
            except Exception:
                target_state_item = None
            if isinstance(target_state_item, dict):
                target_cs_meta = self._ensure_event_component_state(item=target_state_item)
                display_by_ref = {
                    ref_id: disp
                    for ref_id, disp in zip(list(kept), list(new_displays))
                    if str(ref_id) and str(disp)
                }
                normalized_ledger: list[dict[str, Any]] = []
                profile_rows: list[dict[str, Any]] = []
                # Normalize shares within kept components (sum=1).
                share_sum = sum(float(shares.get(ref_id, 0.0) or 0.0) for ref_id in kept)
                if share_sum <= 1e-9:
                    share_sum = 1.0
                for index, ref_id in enumerate(kept):
                    share = float(shares.get(ref_id, 0.0) or 0.0) / share_sum
                    disp = display_by_ref.get(ref_id, ref_id)
                    entry_er = round(old_er * share, 8)
                    entry_ev = round(old_ev * share, 8)
                    normalized_ledger.append(
                        {
                            "index": int(index),
                            "ref_id": ref_id,
                            "display": disp,
                            "tokens": [disp] if disp else [],
                            "profile_share": round(share, 8),
                            "er": entry_er,
                            "ev": entry_ev,
                            "cp_abs": round(abs(entry_er - entry_ev), 8),
                        }
                    )
                    profile_rows.append({"index": int(index), "ref_id": ref_id, "display": disp, "share": round(share, 8)})
                target_cs_meta["event_ref_id"] = str(new_event_ref_id)
                target_cs_meta["member_refs"] = list(kept)
                target_cs_meta["component_ledger"] = normalized_ledger
                target_cs_meta["component_profile"] = profile_rows
                target_cs_meta["degenerated_from_event_ref_id"] = str(old_event_ref_id)
                target_cs_meta["last_tick_id"] = str(tick_id or "")
                try:
                    store.update(target_item_id, target_state_item)
                except Exception:
                    pass

            handled += 1
            actions.append(
                {
                    "action": "degenerate_event",
                    "source_item_id": source_item_id,
                    "source_structure_id": str(item.get("ref_object_id", "") or ""),
                    "source_event_ref_id": str(old_event_ref_id),
                    "target_item_id": target_item_id,
                    "target_structure_id": str(new_structure_id),
                    "target_event_ref_id": str(new_event_ref_id),
                    "removed_component_refs": list(removed),
                    "kept_component_refs": list(kept),
                    "transferred_er": float(old_er),
                    "transferred_ev": float(old_ev),
                    "transferred_total": float(old_total),
                    "created_target_item": bool(created_target_item),
                }
            )

        return {
            "enabled": True,
            "reason": "ok",
            "max_events_per_tick": int(max_events),
            "min_components": int(min_components),
            "share_threshold": float(share_threshold),
            "min_component_energy": float(min_component_energy),
            "candidate_event_count": len(raw_items),
            "degenerated_count": int(handled),
            "actions_preview": actions[:12],
        }

    def _build_event_runtime_object(
        self,
        *,
        component_refs: list[str],
        event_id: str,
        event_er: float,
        event_ev: float,
        candidate: dict,
        tick_id: str,
        hdb,
        source_absorbed_er: float,
        source_absorbed_ev: float,
        target_absorbed_er: float,
        target_absorbed_ev: float,
    ) -> dict:
        component_displays = self._resolve_component_displays(
            components=list(component_refs),
            structure_store=getattr(hdb, "_structure_store", None),
        )
        if not component_displays:
            component_displays = list(component_refs)
        display = self._event_display_from_components(component_displays)
        signature = f"{event_id}|{'|'.join(component_refs)}"
        component_state = self._build_event_component_state(
            component_refs=list(component_refs),
            component_displays=list(component_displays),
            source_components=list(candidate.get("source", {}).get("components", []) or []),
            target_components=list(candidate.get("target", {}).get("components", []) or []),
            source_absorbed_er=source_absorbed_er,
            source_absorbed_ev=source_absorbed_ev,
            target_absorbed_er=target_absorbed_er,
            target_absorbed_ev=target_absorbed_ev,
        )
        return {
            "id": event_id,
            "object_type": "st",
            "sub_type": "cognitive_stitching_event",
            "content": {"raw": display, "display": display, "normalized": signature},
            "energy": {
                "er": round(event_er, 8),
                "ev": round(event_ev, 8),
                "ownership_level": "aggregated_from_st",
                "computed_from_children": True,
            },
            "structure": {
                "display_text": display,
                "flat_tokens": list(component_displays),
                "token_count": len(component_displays),
                "sequence_groups": [
                    {
                        "group_index": index,
                        "source_type": "cognitive_stitching",
                        "origin_frame_id": tick_id,
                        "tokens": [component_display],
                    }
                    for index, component_display in enumerate(component_displays)
                ],
                "member_refs": list(component_refs),
                "content_signature": signature,
                "semantic_signature": signature,
                "ext": {
                    "cognitive_stitching": {
                        "stage": "phase2_contextual_event_stitching",
                        "action_type": str(candidate.get("action_type", "") or ""),
                        "score_source": str(candidate.get("score_source", "legacy") or "legacy"),
                        "execution_uses_v2_score": bool(candidate.get("execution_uses_v2_score", False)),
                        "source_ref_id": str(candidate.get("source", {}).get("ref_object_id", "") or ""),
                        "target_ref_id": str(candidate.get("target", {}).get("ref_object_id", "") or ""),
                        "edge_target_id": str(candidate.get("edge_target_id", "") or ""),
                        "match_mode": str(candidate.get("match_mode", "") or ""),
                        "match_strength": round(float(candidate.get("match_strength", 0.0)), 8),
                        "edge_weight_ratio": round(float(candidate.get("edge_weight_ratio", 0.0)), 8),
                        "candidate_score": round(float(candidate.get("score", 0.0)), 8),
                        "legacy_candidate_score": round(float(candidate.get("legacy_score", 0.0)), 8),
                        "v2_candidate_score": round(float(candidate.get("v2_score", 0.0)), 8),
                        "context_k": int(candidate.get("context_hits", 1) or 1),
                        "matched_span": int(candidate.get("matched_span", 1) or 1),
                        "component_count": len(component_refs),
                        "member_refs": list(component_refs),
                        "component_profile": list(component_state.get("component_profile", [])),
                        "component_ledger": list(component_state.get("component_ledger", [])),
                    }
                },
            },
            "source": {
                "parent_ids": [
                    str(candidate.get("source", {}).get("ref_object_id", "") or ""),
                    str(candidate.get("target", {}).get("ref_object_id", "") or ""),
                ],
            },
        }

    def _build_event_component_state(
        self,
        *,
        component_refs: list[str],
        component_displays: list[str],
        source_components: list[str],
        target_components: list[str],
        source_absorbed_er: float,
        source_absorbed_ev: float,
        target_absorbed_er: float,
        target_absorbed_ev: float,
    ) -> dict[str, list[dict]]:
        display_by_ref: dict[str, str] = {}
        for index, component_ref in enumerate(component_refs):
            display = ""
            if index < len(component_displays):
                display = str(component_displays[index] or "")
            if not display:
                display = str(component_ref or "")
            display_by_ref[str(component_ref or "")] = display

        ledger_by_ref: dict[str, dict[str, Any]] = {}
        for component_ref in component_refs:
            ref_id = str(component_ref or "")
            if not ref_id:
                continue
            display = display_by_ref.get(ref_id, ref_id)
            ledger_by_ref[ref_id] = {
                "ref_id": ref_id,
                "display": display,
                "tokens": [display] if display else [],
                "profile_share": 0.0,
                "er": 0.0,
                "ev": 0.0,
            }

        self._distribute_absorbed_energy_to_components(
            ledger_by_ref=ledger_by_ref,
            component_refs=list(component_refs),
            contributor_components=list(source_components),
            delta_er=float(source_absorbed_er),
            delta_ev=float(source_absorbed_ev),
        )
        self._distribute_absorbed_energy_to_components(
            ledger_by_ref=ledger_by_ref,
            component_refs=list(component_refs),
            contributor_components=list(target_components),
            delta_er=float(target_absorbed_er),
            delta_ev=float(target_absorbed_ev),
        )

        total_energy = round(
            max(0.0, float(source_absorbed_er) + float(source_absorbed_ev) + float(target_absorbed_er) + float(target_absorbed_ev)),
            8,
        )
        component_profile: list[dict] = []
        component_ledger: list[dict] = []
        component_count = max(1, len(component_refs))
        fallback_share = round(1.0 / float(component_count), 8)
        for index, component_ref in enumerate(component_refs):
            ref_id = str(component_ref or "")
            entry = ledger_by_ref.get(ref_id) or {
                "ref_id": ref_id,
                "display": display_by_ref.get(ref_id, ref_id),
                "tokens": [display_by_ref.get(ref_id, ref_id)] if display_by_ref.get(ref_id, ref_id) else [],
                "profile_share": 0.0,
                "er": 0.0,
                "ev": 0.0,
            }
            entry_total = round(max(0.0, float(entry.get("er", 0.0)) + float(entry.get("ev", 0.0))), 8)
            profile_share = (
                round(entry_total / total_energy, 8)
                if total_energy > 0.0
                else fallback_share
            )
            entry["profile_share"] = profile_share
            entry["er"] = round(max(0.0, float(entry.get("er", 0.0))), 8)
            entry["ev"] = round(max(0.0, float(entry.get("ev", 0.0))), 8)
            entry["cp_abs"] = round(abs(float(entry["er"]) - float(entry["ev"])), 8)
            component_profile.append(
                {
                    "index": index,
                    "ref_id": ref_id,
                    "display": str(entry.get("display", "") or ref_id),
                    "share": profile_share,
                }
            )
            component_ledger.append(
                {
                    "index": index,
                    "ref_id": ref_id,
                    "display": str(entry.get("display", "") or ref_id),
                    "tokens": list(entry.get("tokens", []) or []),
                    "profile_share": profile_share,
                    "er": entry["er"],
                    "ev": entry["ev"],
                    "cp_abs": entry["cp_abs"],
                }
            )
        return {
            "component_profile": component_profile,
            "component_ledger": component_ledger,
        }

    @staticmethod
    def _distribute_absorbed_energy_to_components(
        *,
        ledger_by_ref: dict[str, dict[str, Any]],
        component_refs: list[str],
        contributor_components: list[str],
        delta_er: float,
        delta_ev: float,
    ) -> None:
        refs = [
            str(ref_id or "")
            for ref_id in (contributor_components or component_refs or [])
            if str(ref_id or "")
        ]
        if not refs:
            return
        share = 1.0 / float(len(refs))
        for ref_id in refs:
            entry = ledger_by_ref.get(ref_id)
            if entry is None:
                continue
            entry["er"] = round(float(entry.get("er", 0.0)) + max(0.0, float(delta_er)) * share, 8)
            entry["ev"] = round(float(entry.get("ev", 0.0)) + max(0.0, float(delta_ev)) * share, 8)

    @staticmethod
    def _ensure_event_component_state(*, item: dict) -> dict[str, Any]:
        meta = item.setdefault("meta", {})
        meta_ext = meta.setdefault("ext", {})
        cs_meta = meta_ext.get("cognitive_stitching")
        if not isinstance(cs_meta, dict):
            ref_snapshot = item.get("ref_snapshot", {}) or {}
            structure_ext = ref_snapshot.get("structure_ext", {}) or {}
            ref_cs_meta = structure_ext.get("cognitive_stitching")
            cs_meta = dict(ref_cs_meta) if isinstance(ref_cs_meta, dict) else {}
            meta_ext["cognitive_stitching"] = cs_meta
        cs_meta.setdefault("member_refs", list((item.get("ref_snapshot", {}) or {}).get("member_refs", []) or []))
        cs_meta.setdefault("component_profile", [])
        cs_meta.setdefault("component_ledger", [])
        return cs_meta

    def _apply_event_component_ledger_delta(
        self,
        *,
        item: dict,
        component_refs: list[str],
        component_displays: list[str],
        source_components: list[str],
        target_components: list[str],
        source_absorbed_er: float,
        source_absorbed_ev: float,
        target_absorbed_er: float,
        target_absorbed_ev: float,
    ) -> None:
        cs_meta = self._ensure_event_component_state(item=item)
        ledger = list(cs_meta.get("component_ledger", []) or [])
        if not ledger:
            ref_snapshot = item.get("ref_snapshot", {}) or {}
            existing_refs = list(cs_meta.get("member_refs", []) or ref_snapshot.get("member_refs", []) or component_refs)
            existing_displays = list(ref_snapshot.get("flat_tokens", []) or component_displays)
            fallback_state = self._build_event_component_state(
                component_refs=existing_refs,
                component_displays=existing_displays,
                source_components=list(existing_refs),
                target_components=[],
                source_absorbed_er=float(item.get("energy", {}).get("er", 0.0) or 0.0),
                source_absorbed_ev=float(item.get("energy", {}).get("ev", 0.0) or 0.0),
                target_absorbed_er=0.0,
                target_absorbed_ev=0.0,
            )
            ledger = list(fallback_state.get("component_ledger", []) or [])
            cs_meta["component_profile"] = list(fallback_state.get("component_profile", []) or [])
            cs_meta["member_refs"] = list(existing_refs)

        ledger_by_ref = {
            str(entry.get("ref_id", "") or ""): entry
            for entry in ledger
            if str(entry.get("ref_id", "") or "")
        }
        self._distribute_absorbed_energy_to_components(
            ledger_by_ref=ledger_by_ref,
            component_refs=list(component_refs),
            contributor_components=list(source_components),
            delta_er=float(source_absorbed_er),
            delta_ev=float(source_absorbed_ev),
        )
        self._distribute_absorbed_energy_to_components(
            ledger_by_ref=ledger_by_ref,
            component_refs=list(component_refs),
            contributor_components=list(target_components),
            delta_er=float(target_absorbed_er),
            delta_ev=float(target_absorbed_ev),
        )

        total_energy = round(
            sum(
                max(0.0, float(entry.get("er", 0.0))) + max(0.0, float(entry.get("ev", 0.0)))
                for entry in ledger_by_ref.values()
            ),
            8,
        )
        normalized_ledger: list[dict] = []
        normalized_profile: list[dict] = []
        member_refs = list(cs_meta.get("member_refs", []) or component_refs)
        for index, ref_id in enumerate(member_refs):
            ref_text = str(ref_id or "")
            entry = ledger_by_ref.get(ref_text)
            if entry is None:
                display = ""
                if index < len(component_displays):
                    display = str(component_displays[index] or "")
                entry = {
                    "index": index,
                    "ref_id": ref_text,
                    "display": display or ref_text,
                    "tokens": [display] if display else [],
                    "profile_share": 0.0,
                    "er": 0.0,
                    "ev": 0.0,
                }
            entry["index"] = index
            entry["er"] = round(max(0.0, float(entry.get("er", 0.0))), 8)
            entry["ev"] = round(max(0.0, float(entry.get("ev", 0.0))), 8)
            entry["cp_abs"] = round(abs(float(entry["er"]) - float(entry["ev"])), 8)
            current_total = round(float(entry["er"]) + float(entry["ev"]), 8)
            profile_share = round(current_total / total_energy, 8) if total_energy > 0.0 else round(1.0 / float(max(1, len(member_refs))), 8)
            entry["profile_share"] = profile_share
            normalized_ledger.append(
                {
                    "index": index,
                    "ref_id": ref_text,
                    "display": str(entry.get("display", "") or ref_text),
                    "tokens": list(entry.get("tokens", []) or []),
                    "profile_share": profile_share,
                    "er": entry["er"],
                    "ev": entry["ev"],
                    "cp_abs": entry["cp_abs"],
                }
            )
            normalized_profile.append(
                {
                    "index": index,
                    "ref_id": ref_text,
                    "display": str(entry.get("display", "") or ref_text),
                    "share": profile_share,
                }
            )

        cs_meta["component_ledger"] = normalized_ledger
        cs_meta["component_profile"] = normalized_profile

    def _collect_narrative_top_items(self, *, pool, trace_id: str, tick_id: str) -> list[dict]:
        store = getattr(pool, "_store", None)
        if store is not None and hasattr(store, "get_all"):
            try:
                raw_items = [
                    item
                    for item in list(store.get_all())
                    if self._is_cognitive_stitching_narrative_state_item(item)
                ]
                raw_items.sort(
                    key=lambda item: (
                        float(item.get("energy", {}).get("er", 0.0) or 0.0)
                        + float(item.get("energy", {}).get("ev", 0.0) or 0.0),
                        float(item.get("energy", {}).get("salience_score", 0.0) or 0.0),
                    ),
                    reverse=True,
                )
                narrative = []
                for item in raw_items[: max(1, int(self._config.get("narrative_top_k", 6)))]:
                    row = self._build_narrative_row_from_state_item(item)
                    if row:
                        narrative.append(row)
                return narrative
            except Exception:
                pass

        snapshot_resp = pool.get_state_snapshot(
            trace_id=f"{trace_id}_cs_post",
            tick_id=tick_id,
            top_k=max(12, int(self._config.get("snapshot_top_k", 24) or 0)),
            sort_by="cp_abs",
        )
        if not snapshot_resp.get("success"):
            return []
        snapshot = snapshot_resp.get("data", {}).get("snapshot", {}) or {}
        items = [item for item in list(snapshot.get("top_items", []) or []) if str(item.get("ref_object_type", "") or "") == "st"]
        narrative = []
        limit = max(1, int(self._config.get("narrative_top_k", 6)))
        for item in items:
            if len(narrative) >= limit:
                break
            item_id = str(item.get("item_id", "") or "").strip()
            state_item = self._get_state_item_by_id(pool=pool, item_id=item_id)
            if isinstance(state_item, dict):
                row = self._build_narrative_row_from_state_item(state_item)
                if row:
                    narrative.append(row)
                continue

            # Very minimal fallback for unit tests: when PoolStore doesn't support `get()`,
            # we can still surface legacy runtime-only events that use cs_event::<...> as ref_object_id.
            legacy_ref_id = str(item.get("ref_object_id", "") or "").strip()
            if not self._is_event_ref_id(legacy_ref_id):
                continue
            es_entry = self._esdb.get(legacy_ref_id)
            es_parent_depth = self._esdb_parent_depth(legacy_ref_id, set()) if isinstance(es_entry, dict) else 0
            narrative.append(
                {
                    "item_id": item_id,
                    "ref_object_id": legacy_ref_id,
                    "structure_id": legacy_ref_id,
                    "display": str(item.get("display", "") or legacy_ref_id),
                    "er": round(float(item.get("er", 0.0) or 0.0), 8),
                    "ev": round(float(item.get("ev", 0.0) or 0.0), 8),
                    "cp_abs": round(float(item.get("cp_abs", 0.0) or 0.0), 8),
                    "salience_score": round(float(item.get("salience_score", 0.0) or 0.0), 8),
                    "event_grasp": 0.0,
                    "total_energy": round(float(item.get("er", 0.0) or 0.0) + float(item.get("ev", 0.0) or 0.0), 8),
                    "component_count": len(self._parse_event_components(legacy_ref_id)),
                    "esdb_parent_depth": int(es_parent_depth),
                    "esdb_parent_count": len(list(es_entry.get("parents", []) or [])) if isinstance(es_entry, dict) else 0,
                    "esdb_delta_entry_count": len(list(es_entry.get("delta_diff_table", []) or [])) if isinstance(es_entry, dict) else 0,
                    "esdb_materialized": bool(es_entry.get("materialized", False)) if isinstance(es_entry, dict) else False,
                    "esdb_materialized_entry_count": len(list(es_entry.get("materialized_diff_table", []) or [])) if isinstance(es_entry, dict) else 0,
                    "esdb_update_count": int(es_entry.get("update_count", 0) or 0) if isinstance(es_entry, dict) else 0,
                    "narrative_kind": "event",
                    "event_ref_id": legacy_ref_id,
                    "display_text": str(item.get("display", "") or legacy_ref_id),
                    "visible_text": str(item.get("display", "") or legacy_ref_id),
                    "selection_sources": [],
                }
            )
        return narrative

    def _build_narrative_row_from_state_item(self, item: dict) -> dict[str, Any] | None:
        if not self._is_cognitive_stitching_narrative_state_item(item):
            return None
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        structure_ext = ref_snapshot.get("structure_ext", {}) if isinstance(ref_snapshot.get("structure_ext", {}), dict) else {}
        cs_meta = self._extract_cognitive_stitching_meta_from_state_item(item)
        structure_id = str(item.get("ref_object_id", "") or "")
        event_ref_id = self._extract_event_ref_id_from_state_item(item) or structure_id
        display_text = str(ref_snapshot.get("content_display", "") or event_ref_id or structure_id)
        detail_text = str(ref_snapshot.get("content_display_detail", "") or "").strip()
        context_text = str(
            ref_snapshot.get("context_text", "")
            or structure_ext.get("context_text", "")
            or cs_meta.get("context_text", "")
            or ""
        ).strip()
        attr_displays = self._dedupe_strings(
            list(ref_snapshot.get("attribute_displays", []) or []) + list(ref_snapshot.get("bound_attribute_displays", []) or [])
        )
        detail_parts = []
        if detail_text and detail_text != display_text:
            detail_parts.append(detail_text)
        if context_text:
            detail_parts.append(f"ctx={context_text}")
        if attr_displays:
            detail_parts.append(f"attrs={', '.join(attr_displays[:4])}")
        visible_text = display_text if not detail_parts else f"{display_text} | {' | '.join(detail_parts)}"
        total_energy = round(
            float(item.get("energy", {}).get("er", 0.0) or 0.0) + float(item.get("energy", {}).get("ev", 0.0) or 0.0),
            8,
        )
        is_event = self._is_cognitive_stitching_event_state_item(item)
        member_refs = list(ref_snapshot.get("member_refs", []) or [])
        flat_tokens = list(ref_snapshot.get("flat_tokens", []) or [])
        component_count = len(self._parse_event_components(event_ref_id)) if is_event else max(1, len(member_refs) or len(flat_tokens))
        es_entry = self._esdb.get(event_ref_id) if is_event else None
        es_parent_depth = self._esdb_parent_depth(event_ref_id, set()) if isinstance(es_entry, dict) else 0
        action_type = str(cs_meta.get("action_type", "") or ("event" if is_event else "concat_context_structure"))
        selection_sources = [] if is_event else [action_type]
        return {
            "item_id": str(item.get("id", "") or ""),
            "ref_object_id": event_ref_id,
            "event_ref_id": event_ref_id,
            "structure_id": structure_id,
            "display": display_text,
            "display_text": display_text,
            "visible_text": visible_text,
            "narrative_kind": "event" if is_event else "concat_structure",
            "action_type": action_type,
            "er": round(float(item.get("energy", {}).get("er", 0.0) or 0.0), 8),
            "ev": round(float(item.get("energy", {}).get("ev", 0.0) or 0.0), 8),
            "cp_abs": round(float(item.get("energy", {}).get("cognitive_pressure_abs", 0.0) or 0.0), 8),
            "salience_score": round(float(item.get("energy", {}).get("salience_score", 0.0) or 0.0), 8),
            "event_grasp": self._extract_bound_numerical_attribute(
                item,
                attribute_name=str(self._config.get("event_grasp_attribute_name", "event_grasp") or "event_grasp"),
            ),
            "total_energy": total_energy,
            "component_count": int(component_count),
            "selection_sources": selection_sources,
            "match_mode": str(cs_meta.get("match_mode", "") or ""),
            "context_owner_id": str(ref_snapshot.get("context_owner_id", "") or structure_ext.get("context_owner_structure_id", "") or ""),
            "context_ref_object_id": str(ref_snapshot.get("context_ref_object_id", "") or structure_ext.get("context_ref_object_id", "") or ""),
            "context_text": context_text,
            "concat_source_ref_id": str(structure_ext.get("concat_source_ref_id", "") or cs_meta.get("source_ref_id", "") or ""),
            "concat_target_ref_id": str(structure_ext.get("concat_target_ref_id", "") or cs_meta.get("target_ref_id", "") or ""),
            "esdb_parent_depth": int(es_parent_depth),
            "esdb_parent_count": len(list(es_entry.get("parents", []) or [])) if isinstance(es_entry, dict) else 0,
            "esdb_delta_entry_count": len(list(es_entry.get("delta_diff_table", []) or [])) if isinstance(es_entry, dict) else 0,
            "esdb_materialized": bool(es_entry.get("materialized", False)) if isinstance(es_entry, dict) else False,
            "esdb_materialized_entry_count": len(list(es_entry.get("materialized_diff_table", []) or [])) if isinstance(es_entry, dict) else 0,
            "esdb_update_count": int(es_entry.get("update_count", 0) or 0) if isinstance(es_entry, dict) else 0,
        }

    def _build_action_log_row(self, action: dict) -> dict[str, Any]:
        action_type = str(action.get("action_family", "") or action.get("action", "") or "")
        action_name = str(action.get("action", "") or action_type)
        structure_id = str(
            action.get("structure_id", "")
            or action.get("event_structure_id", "")
            or action.get("event_ref_id", "")
            or ""
        )
        visible_text = str(
            action.get("structure_display", "")
            or action.get("event_display", "")
            or action.get("result_display", "")
            or structure_id
        )
        context_text = str(action.get("context_text", "") or "")
        return {
            "action": action_name,
            "action_family": action_type,
            "visible_text": visible_text,
            "structure_id": structure_id,
            "context_text": context_text,
            "source_ref_id": str(action.get("source_ref_id", "") or ""),
            "source_display": str(action.get("source_display", "") or ""),
            "source_kind": str(action.get("source_kind", "") or ""),
            "target_ref_id": str(action.get("target_ref_id", "") or ""),
            "target_display": str(action.get("target_display", "") or ""),
            "target_kind": str(action.get("target_kind", "") or ""),
            "match_mode": str(action.get("match_mode", "") or ""),
            "score": round(float(action.get("score", 0.0) or 0.0), 8),
            "legacy_score": round(float(action.get("legacy_score", 0.0) or 0.0), 8),
            "v2_score": round(float(action.get("v2_score", 0.0) or 0.0), 8),
            "context_ratio": round(float(action.get("context_ratio", 0.0) or 0.0), 8),
            "last_token_score": round(float(action.get("last_token_score", 0.0) or 0.0), 8),
            "contiguous_ratio": round(float(action.get("contiguous_ratio", 0.0) or 0.0), 8),
            "match_count_score": round(float(action.get("match_count_score", 0.0) or 0.0), 8),
            "attribute_bonus_score": round(float(action.get("attribute_bonus_score", 0.0) or 0.0), 8),
            "effective_match_units": round(float(action.get("effective_match_units", 0.0) or 0.0), 8),
            "absorb_ratio": round(float(action.get("absorb_ratio", 0.0) or 0.0), 8),
            "absorbed_er": round(float(action.get("absorbed_er", 0.0) or 0.0), 8),
            "absorbed_ev": round(float(action.get("absorbed_ev", 0.0) or 0.0), 8),
            "absorbed_total": round(float(action.get("absorbed_total", 0.0) or 0.0), 8),
            "source_absorbed_er": round(float(action.get("source_absorbed_er", 0.0) or 0.0), 8),
            "source_absorbed_ev": round(float(action.get("source_absorbed_ev", 0.0) or 0.0), 8),
            "source_absorbed_total": round(
                float(action.get("source_absorbed_total", 0.0) or 0.0)
                or float(action.get("source_absorbed_er", 0.0) or 0.0) + float(action.get("source_absorbed_ev", 0.0) or 0.0),
                8,
            ),
            "target_absorbed_er": round(float(action.get("target_absorbed_er", 0.0) or 0.0), 8),
            "target_absorbed_ev": round(float(action.get("target_absorbed_ev", 0.0) or 0.0), 8),
            "target_absorbed_total": round(
                float(action.get("target_absorbed_total", 0.0) or 0.0)
                or float(action.get("target_absorbed_er", 0.0) or 0.0) + float(action.get("target_absorbed_ev", 0.0) or 0.0),
                8,
            ),
            "target_context_prefix_trimmed": bool(action.get("target_context_prefix_trimmed", False)),
            "target_context_prefix_trim_count": int(action.get("target_context_prefix_trim_count", 0) or 0),
            "exact_context_identity_match": bool(action.get("exact_context_identity_match", False)),
            "object_stitch_fatigue_before": round(float(action.get("object_stitch_fatigue_before", 0.0) or 0.0), 8),
            "object_stitch_fatigue_scale": round(float(action.get("object_stitch_fatigue_scale", 1.0) or 1.0), 8),
            "object_stitch_fatigue_refs": list(action.get("object_stitch_fatigue_refs", []) or [])[:8],
            "fatigue_after": round(float(action.get("fatigue_after", 0.0) or 0.0), 8),
        }

    @staticmethod
    def _empty_apply_audit() -> dict[str, Any]:
        return {
            "candidate_input_count": 0,
            "action_count": 0,
            "concat_action_count": 0,
            "exact_concat_action_count": 0,
            "exact_new_concat_action_count": 0,
            "partial_concat_action_count": 0,
            "partial_new_concat_action_count": 0,
            "reinforce_concat_action_count": 0,
            "target_context_prefix_trimmed_action_count": 0,
            "lower_energy_cap_audit_count": 0,
            "lower_energy_cap_abs_diff_max": 0.0,
            "source_absorbed_total_mean": 0.0,
            "target_absorbed_total_mean": 0.0,
            "absorbed_total_mean": 0.0,
            "absorb_ratio_mean": 0.0,
            "skip_count": 0,
            "skip_reason_counts": {},
            "skip_preview": [],
        }

    def _new_apply_audit(self, candidates: list[dict]) -> dict[str, Any]:
        audit = self._empty_apply_audit()
        audit["candidate_input_count"] = int(len(list(candidates or [])))
        return audit

    def _audit_apply_skip(self, *, candidate: dict, reason: str, event_total: float | None = None) -> None:
        audit = self._current_apply_audit
        if not isinstance(audit, dict):
            return
        audit["skip_count"] = int(audit.get("skip_count", 0) or 0) + 1
        self._bump_counter(audit.setdefault("skip_reason_counts", {}), str(reason or "unknown"))
        preview = audit.setdefault("skip_preview", [])
        if len(preview) >= 8:
            return
        source = candidate.get("source", {}) if isinstance(candidate.get("source", {}), dict) else {}
        target = candidate.get("target", {}) if isinstance(candidate.get("target", {}), dict) else {}
        row = {
            "reason": str(reason or "unknown"),
            "action_type": str(candidate.get("action_type", "") or ""),
            "match_mode": str(candidate.get("match_mode", "") or ""),
            "source_display": str(source.get("display", "") or ""),
            "target_display": str(target.get("display", "") or ""),
            "score": round(float(candidate.get("score", 0.0) or 0.0), 8),
            "context_ratio": round(float(candidate.get("context_ratio", 0.0) or 0.0), 8),
            "exact_context_identity_match": bool(candidate.get("exact_context_identity_match", False)),
        }
        if event_total is not None:
            row["event_total"] = round(float(event_total), 8)
        preview.append(row)

    def _audit_apply_action(self, action: dict) -> None:
        audit = self._current_apply_audit
        if not isinstance(audit, dict):
            return
        audit["action_count"] = int(audit.get("action_count", 0) or 0) + 1
        action_family = str(action.get("action_family", "") or "")
        action_name = str(action.get("action", "") or "")
        if action_family == "concat_context_structure":
            audit["concat_action_count"] = int(audit.get("concat_action_count", 0) or 0) + 1
            match_mode = str(action.get("match_mode", "") or "")
            is_reinforce = action_name.startswith("reinforce_")
            if match_mode == "context_tail_exact" or bool(action.get("exact_context_identity_match", False)):
                audit["exact_concat_action_count"] = int(audit.get("exact_concat_action_count", 0) or 0) + 1
                if not is_reinforce:
                    audit["exact_new_concat_action_count"] = int(audit.get("exact_new_concat_action_count", 0) or 0) + 1
            else:
                audit["partial_concat_action_count"] = int(audit.get("partial_concat_action_count", 0) or 0) + 1
                if not is_reinforce:
                    audit["partial_new_concat_action_count"] = int(audit.get("partial_new_concat_action_count", 0) or 0) + 1
            if is_reinforce:
                audit["reinforce_concat_action_count"] = int(audit.get("reinforce_concat_action_count", 0) or 0) + 1
            if bool(action.get("target_context_prefix_trimmed", False)):
                audit["target_context_prefix_trimmed_action_count"] = int(
                    audit.get("target_context_prefix_trimmed_action_count", 0) or 0
                ) + 1
        source_total = float(action.get("source_absorbed_total", 0.0) or 0.0)
        target_total = float(action.get("target_absorbed_total", 0.0) or 0.0)
        absorbed_total = float(action.get("absorbed_total", 0.0) or 0.0)
        absorb_ratio = float(action.get("absorb_ratio", 0.0) or 0.0)
        audit.setdefault("_source_absorbed_total_values", []).append(source_total)
        audit.setdefault("_target_absorbed_total_values", []).append(target_total)
        audit.setdefault("_absorbed_total_values", []).append(absorbed_total)
        audit.setdefault("_absorb_ratio_values", []).append(absorb_ratio)
        if action_family == "concat_context_structure" and bool(action.get("exact_context_identity_match", False)):
            diff = abs(source_total - target_total)
            audit["lower_energy_cap_audit_count"] = int(audit.get("lower_energy_cap_audit_count", 0) or 0) + 1
            audit["lower_energy_cap_abs_diff_max"] = max(float(audit.get("lower_energy_cap_abs_diff_max", 0.0) or 0.0), diff)

    @staticmethod
    def _mean_float_values(values: list[Any]) -> float:
        numbers: list[float] = []
        for value in list(values or []):
            try:
                numbers.append(float(value))
            except Exception:
                continue
        if not numbers:
            return 0.0
        return round(sum(numbers) / float(len(numbers)), 8)

    def _finalize_apply_audit(self, audit: dict[str, Any] | None, actions: list[dict]) -> dict[str, Any]:
        if not isinstance(audit, dict):
            audit = self._empty_apply_audit()
        result = {k: v for k, v in audit.items() if not str(k).startswith("_")}
        result["action_count"] = int(len(list(actions or [])))
        result["source_absorbed_total_mean"] = self._mean_float_values(audit.get("_source_absorbed_total_values", []))
        result["target_absorbed_total_mean"] = self._mean_float_values(audit.get("_target_absorbed_total_values", []))
        result["absorbed_total_mean"] = self._mean_float_values(audit.get("_absorbed_total_values", []))
        result["absorb_ratio_mean"] = self._mean_float_values(audit.get("_absorb_ratio_values", []))
        result["lower_energy_cap_abs_diff_max"] = round(float(result.get("lower_energy_cap_abs_diff_max", 0.0) or 0.0), 8)
        return result

    def _is_cognitive_stitching_narrative_state_item(self, item: dict) -> bool:
        return self._is_cognitive_stitching_event_state_item(item) or self._is_cognitive_stitching_concat_state_item(item)

    def _is_cognitive_stitching_concat_state_item(self, item: dict) -> bool:
        if not isinstance(item, dict):
            return False
        if str(item.get("ref_object_type", "") or "") != "st":
            return False
        if self._is_cognitive_stitching_event_state_item(item):
            return False
        cs_meta = self._extract_cognitive_stitching_meta_from_state_item(item)
        action_type = str(cs_meta.get("action_type", "") or "").strip()
        if action_type in {"concat_context_structure", "reinforce_concat_context_structure"}:
            return True
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        structure_ext = ref_snapshot.get("structure_ext", {}) if isinstance(ref_snapshot.get("structure_ext", {}), dict) else {}
        concat_refs = list(structure_ext.get("concat_parent_refs", []) or [])
        return bool(concat_refs)

    def _extract_cognitive_stitching_meta_from_state_item(self, item: dict) -> dict[str, Any]:
        if not isinstance(item, dict):
            return {}
        meta = item.get("meta", {}) if isinstance(item.get("meta", {}), dict) else {}
        meta_ext = meta.get("ext", {}) if isinstance(meta.get("ext", {}), dict) else {}
        cs_meta = meta_ext.get("cognitive_stitching", {}) if isinstance(meta_ext.get("cognitive_stitching", {}), dict) else {}
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        structure_ext = ref_snapshot.get("structure_ext", {}) if isinstance(ref_snapshot.get("structure_ext", {}), dict) else {}
        cs_meta2 = structure_ext.get("cognitive_stitching", {}) if isinstance(structure_ext.get("cognitive_stitching", {}), dict) else {}
        if isinstance(cs_meta, dict) and isinstance(cs_meta2, dict):
            merged = dict(cs_meta2)
            merged.update({k: v for k, v in cs_meta.items() if v not in ("", None, [], {})})
            return merged
        if isinstance(cs_meta, dict) and cs_meta:
            return cs_meta
        return cs_meta2 if isinstance(cs_meta2, dict) else {}

    @staticmethod
    def _clamp01(value: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except Exception:
            return 0.0

    @staticmethod
    def _get_state_item_by_id(*, pool, item_id: str) -> dict | None:
        if not item_id:
            return None
        store = getattr(pool, "_store", None)
        if store is None or not hasattr(store, "get"):
            return None
        try:
            item = store.get(item_id)
            return item if isinstance(item, dict) else None
        except Exception:
            return None

    def _collect_event_grasp_focus_item_ids(
        self,
        *,
        attention_snapshot: dict,
        preferred_event_item_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        source_by_item_id: dict[str, set[str]] = {}
        cam_seed_count = 0
        for item in list((attention_snapshot or {}).get("top_items", []) or []):
            if not isinstance(item, dict):
                continue
            if str(item.get("ref_object_type", "") or "") != "st":
                continue
            item_id = str(item.get("item_id", "") or "").strip()
            if not item_id:
                continue
            source_by_item_id.setdefault(item_id, set()).add("cam")
            cam_seed_count += 1

        post_action_seed_count = 0
        if bool(self._config.get("event_grasp_include_post_cs_action_events", True)):
            for raw_item_id in list(preferred_event_item_ids or []):
                item_id = str(raw_item_id or "").strip()
                if not item_id:
                    continue
                source_by_item_id.setdefault(item_id, set()).add("post_cs_action")
                post_action_seed_count += 1

        if cam_seed_count > 0 and post_action_seed_count > 0:
            focus_mode = "cam_plus_post_cs_action"
        elif post_action_seed_count > 0:
            focus_mode = "post_cs_action_only"
        else:
            focus_mode = "cam_only"

        return {
            "item_ids": list(source_by_item_id.keys()),
            "source_by_item_id": {
                item_id: sorted(tags)
                for item_id, tags in source_by_item_id.items()
            },
            "cam_seed_count": int(cam_seed_count),
            "post_action_seed_count": int(post_action_seed_count),
            "focus_mode": focus_mode,
        }

    @staticmethod
    def _safe_bind_ref_alias(*, pool, item_id: str, ref_alias_id: str) -> None:
        """Bind a ref_object_id alias to an existing state_item (best-effort, never raising)."""
        if not item_id or not ref_alias_id:
            return
        store = getattr(pool, "_store", None)
        if store is None or not hasattr(store, "bind_ref_alias"):
            return
        try:
            store.bind_ref_alias(str(item_id), str(ref_alias_id))
        except Exception:
            return

    def _is_cognitive_stitching_event_structure_obj(self, structure_obj: dict) -> bool:
        if not isinstance(structure_obj, dict):
            return False
        if str(structure_obj.get("sub_type", "") or "") == "cognitive_stitching_event_structure":
            return True
        structure_block = structure_obj.get("structure", {}) if isinstance(structure_obj.get("structure", {}), dict) else {}
        ext = structure_block.get("ext", {}) if isinstance(structure_block.get("ext", {}), dict) else {}
        cs_meta = ext.get("cognitive_stitching") if isinstance(ext.get("cognitive_stitching"), dict) else {}
        if not isinstance(cs_meta, dict):
            return False
        event_ref_id = str(
            cs_meta.get("event_ref_id", "")
            or cs_meta.get("cs_event_ref_id", "")
            or structure_block.get("content_signature", "")
            or ""
        ).strip()
        return self._is_event_ref_id(event_ref_id)

    def _is_cognitive_stitching_event_state_item(self, item: dict) -> bool:
        if not isinstance(item, dict):
            return False
        if str(item.get("ref_object_type", "") or "") != "st":
            return False
        # Strict event detection:
        # - Avoid misclassifying "ordinary ST structures" as CS events.
        # - A CS event must have a canonical event_ref_id that starts with "<prefix>::".
        #
        # Note:
        # - For HDB-backed events, ref_object_id is the HDB structure_id (st_*),
        #   while the canonical event_ref_id lives in ref_snapshot.content_signature or CS metadata.
        event_ref_id = self._extract_event_ref_id_from_state_item(item)
        return bool(event_ref_id and self._is_event_ref_id(event_ref_id))

    def _extract_event_ref_id_from_state_item(self, item: dict) -> str:
        """Return the canonical event_ref_id (cs_event::...) for a CS event state item."""
        prefix = f"{self._config.get('event_id_prefix', 'cs_event')}::"
        if not isinstance(item, dict):
            return ""
        ref_id = str(item.get("ref_object_id", "") or "")
        if ref_id.startswith(prefix):
            return ref_id

        meta_ext = (item.get("meta", {}) or {}).get("ext", {}) if isinstance((item.get("meta", {}) or {}).get("ext", {}), dict) else {}
        cs_meta = meta_ext.get("cognitive_stitching", {}) if isinstance(meta_ext.get("cognitive_stitching", {}), dict) else {}
        candidate = str(cs_meta.get("event_ref_id", "") or cs_meta.get("cs_event_ref_id", "") or "").strip()
        if candidate.startswith(prefix):
            return candidate

        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        snap_sig = str(ref_snapshot.get("content_signature", "") or "").strip()
        if snap_sig.startswith(prefix):
            return snap_sig
        structure_ext = ref_snapshot.get("structure_ext", {}) if isinstance(ref_snapshot.get("structure_ext", {}), dict) else {}
        cs_meta2 = structure_ext.get("cognitive_stitching", {}) if isinstance(structure_ext.get("cognitive_stitching", {}), dict) else {}
        candidate2 = str(cs_meta2.get("event_ref_id", "") or cs_meta2.get("cs_event_ref_id", "") or "").strip()
        if candidate2.startswith(prefix):
            return candidate2
        return ""

    @staticmethod
    def _extract_bound_numerical_attribute(state_item: dict, *, attribute_name: str) -> float:
        name = str(attribute_name or "").strip()
        if not name or not isinstance(state_item, dict):
            return 0.0
        try:
            attrs = list((state_item.get("ext", {}) or {}).get("bound_attributes", []) or [])
        except Exception:
            attrs = []
        for attr in attrs:
            if not isinstance(attr, dict):
                continue
            content = attr.get("content", {}) if isinstance(attr.get("content", {}), dict) else {}
            if str(content.get("attribute_name", "") or "").strip() != name:
                continue
            try:
                return round(float(content.get("attribute_value", 0.0) or 0.0), 8)
            except Exception:
                return 0.0
        return 0.0

    def _event_internal_balance_from_ledger(self, state_item: dict | None) -> float:
        """Compute internal balance from ES component ledger: 1 - mean(|er-ev|/(er+ev))."""
        if not isinstance(state_item, dict):
            return 0.0
        meta = state_item.get("meta", {}) if isinstance(state_item.get("meta", {}), dict) else {}
        meta_ext = meta.get("ext", {}) if isinstance(meta.get("ext", {}), dict) else {}
        cs_meta = meta_ext.get("cognitive_stitching") if isinstance(meta_ext.get("cognitive_stitching"), dict) else {}
        ledger = list((cs_meta or {}).get("component_ledger", []) or [])
        if not ledger:
            return 0.0
        norms: list[float] = []
        for entry in ledger:
            if not isinstance(entry, dict):
                continue
            er = max(0.0, float(entry.get("er", 0.0) or 0.0))
            ev = max(0.0, float(entry.get("ev", 0.0) or 0.0))
            total = er + ev
            if total <= 1e-9:
                norms.append(0.0)
                continue
            norms.append(abs(er - ev) / total)
        if not norms:
            return 0.0
        mean_norm = sum(norms) / float(len(norms))
        return self._clamp01(1.0 - mean_norm)

    def _compute_event_grasp(self, *, total_energy: float, balance: float, margin: float) -> float:
        w_e = float(self._config.get("event_grasp_energy_weight", 1.2) or 1.2)
        w_b = float(self._config.get("event_grasp_balance_weight", 1.3) or 1.3)
        w_m = float(self._config.get("event_grasp_margin_weight", 0.8) or 0.8)
        bias = float(self._config.get("event_grasp_bias", -1.0) or -1.0)
        temp = max(1e-6, float(self._config.get("event_grasp_sigmoid_temperature", 1.0) or 1.0))
        z = (
            bias
            + w_e * math.log1p(max(0.0, float(total_energy)))
            + w_b * self._clamp01(float(balance))
            + w_m * self._clamp01(float(margin))
        )
        # Sigmoid with temperature scaling.
        try:
            return self._clamp01(1.0 / (1.0 + math.exp(-float(z) / temp)))
        except OverflowError:
            return 1.0 if z > 0 else 0.0

    @staticmethod
    def _build_numerical_attribute_sa(
        *,
        attribute_name: str,
        attribute_value: float,
        target_item_id: str,
        target_ref_object_id: str,
        trace_id: str,
        tick_id: str,
        sub_type: str,
        display_prefix: str,
    ) -> dict:
        now_ms = int(time.time() * 1000)
        name = str(attribute_name or "").strip() or "attr"
        value = float(attribute_value or 0.0)
        # Stable per-target id (binding engine will also replace-by-name).
        attr_id = f"sa_attr_{name}_{target_item_id or target_ref_object_id or 'global'}"
        raw = f"{name}:{round(value, 6)}"
        display = f"{display_prefix}:{round(value, 3)}"
        return {
            "id": attr_id,
            "object_type": "sa",
            "sub_type": str(sub_type or "marker_attribute_presence"),
            "schema_version": "1.1",
            "content": {
                "raw": raw,
                "normalized": raw,
                "display": display,
                "value_type": "numerical",
                "attribute_name": name,
                "attribute_value": round(value, 8),
            },
            "stimulus": {"modality": "meta", "role": "attribute", "is_anchor": False, "group_index": 0, "position_in_group": 0, "global_sequence_index": 0},
            "energy": {
                "er": 0.0,
                "ev": 0.0,
                "ownership_level": "sa",
                "computed_from_children": False,
                "fatigue": 0.0,
                "recency_gain": 1.0,
                "salience_score": 0.0,
                "cognitive_pressure_delta": 0.0,
                "cognitive_pressure_abs": 0.0,
                "last_decay_tick": 0,
                "last_decay_at": now_ms,
            },
            "source": {
                "module": "cognitive_stitching",
                "interface": "run_event_grasp",
                "origin": "event_grasp_attribute_binding",
                "origin_id": tick_id,
                "parent_ids": [str(target_ref_object_id or "")] if str(target_ref_object_id or "") else [],
            },
            "trace_id": trace_id,
            "tick_id": tick_id,
            "created_at": now_ms,
            "updated_at": now_ms,
            "status": "active",
            "tags": ["cognitive_stitching", "attribute"],
            "ext": {"attribute_name": name, "target_ref_object_id": str(target_ref_object_id or "")},
            "meta": {"confidence": 0.7, "field_registry_version": "1.1", "debug": {}, "ext": {}},
        }

    def _is_event_ref_id(self, ref_id: str) -> bool:
        prefix = f"{self._config.get('event_id_prefix', 'cs_event')}::"
        return bool(ref_id) and str(ref_id).startswith(prefix)

    def _esdb_upsert_event(
        self,
        *,
        event_ref_id: str,
        components: list[str],
        parent_refs: list[str],
        tick_id: str,
        action_type: str,
    ) -> None:
        if not event_ref_id or not self._is_event_ref_id(event_ref_id):
            return
        now_ms = int(time.time() * 1000)
        entry = self._esdb.get(event_ref_id)
        if not isinstance(entry, dict):
            entry = {
                "event_ref_id": event_ref_id,
                "components": list(components),
                "parents": [],
                "delta_diff_table": [],
                "materialized": False,
                "materialized_diff_table": [],
                "runtime_cache": {},
                "created_at_ms": now_ms,
                "updated_at_ms": now_ms,
                "update_count": 0,
                "last_tick_id": "",
                "last_action_type": "",
            }
            self._esdb[event_ref_id] = entry

        prev_components = list(entry.get("components", []) or [])
        prev_parents = list(entry.get("parents", []) or [])

        entry["components"] = list(components)
        parents = list(entry.get("parents", []) or [])
        for parent in parent_refs or []:
            pid = str(parent or "").strip()
            if not pid:
                continue
            if pid not in parents:
                parents.append(pid)
        entry["parents"] = parents
        entry["update_count"] = int(entry.get("update_count", 0) or 0) + 1
        entry["last_tick_id"] = str(tick_id or "")
        entry["last_action_type"] = str(action_type or "")
        entry["updated_at_ms"] = now_ms
        # Parent chain / components change invalidates overlay cache.
        entry["runtime_cache"] = {}
        # If the event's components changed, a previously materialized overlay may become stale.
        # Prefer dropping materialization so future overlay opens can incorporate new tail knowledge.
        if prev_components != list(components):
            entry["materialized"] = False
            entry["materialized_diff_table"] = []

        # Keep delta clean: do not keep edges to already-in-event components.
        try:
            component_set = {str(x) for x in (components or []) if str(x)}
            delta = [d for d in list(entry.get("delta_diff_table", []) or []) if isinstance(d, dict) and str(d.get("target_id", "") or "") and str(d.get("target_id", "") or "") not in component_set]
            entry["delta_diff_table"] = delta
        except Exception:
            pass

        del prev_components, prev_parents

    def _esdb_parent_depth(self, event_ref_id: str, visited: set[str]) -> int:
        if not event_ref_id or event_ref_id in visited:
            return 0
        entry = self._esdb.get(event_ref_id)
        if not isinstance(entry, dict):
            return 0
        visited.add(event_ref_id)
        parents = [str(x) for x in (entry.get("parents", []) or []) if str(x)]
        if not parents:
            return 0
        depths = []
        for parent in parents:
            if self._is_event_ref_id(parent):
                depths.append(1 + self._esdb_parent_depth(parent, visited))
            else:
                depths.append(1)
        return int(max(depths)) if depths else 0

    def _esdb_open_overlay_top_diff_entries(self, *, event_ref_id: str, hdb) -> tuple[list[dict], float]:
        """Open ES overlay DB (parents+delta) and return top diff_table entries."""
        top_k = max(1, int(self._config.get("esdb_overlay_top_k", 16)))
        return self._esdb_open_overlay_diff_entries(
            event_ref_id=event_ref_id,
            hdb=hdb,
            top_k=top_k,
            visited=set(),
            use_cache=True,
        )

    def _esdb_materialize_diff_table(self, *, event_ref_id: str, hdb, top_n: int) -> list[dict]:
        entries, _ = self._esdb_open_overlay_diff_entries(
            event_ref_id=event_ref_id,
            hdb=hdb,
            top_k=max(1, int(top_n)),
            visited=set(),
            use_cache=False,
        )
        return list(entries)

    def _esdb_open_overlay_diff_entries(
        self,
        *,
        event_ref_id: str,
        hdb,
        top_k: int,
        visited: set[str],
        use_cache: bool,
    ) -> tuple[list[dict], float]:
        if not event_ref_id or not self._is_event_ref_id(event_ref_id):
            return [], 0.0
        entry = self._esdb.get(event_ref_id)
        if not isinstance(entry, dict):
            return [], 0.0

        top_k = max(1, int(top_k))
        if bool(entry.get("materialized", False)) and entry.get("materialized_diff_table"):
            # Materialized rows are a baseline; delta can continue to grow after consolidation.
            merged: dict[str, dict[str, Any]] = {}
            for r in list(entry.get("materialized_diff_table", []) or []):
                if not isinstance(r, dict):
                    continue
                target_id = str(r.get("target_id", "") or "")
                if not target_id:
                    continue
                w = max(0.0, float(r.get("base_weight", 0.0) or 0.0))
                merged[target_id] = {
                    "target_id": target_id,
                    "base_weight": round(w, 8),
                    "entry_type": str(r.get("entry_type", "structure_ref") or "structure_ref"),
                    "ext": dict(r.get("ext", {}) or {}),
                }

            # Merge delta on top of baseline (if any).
            beta = max(0.0, min(1.0, float(self._config.get("esdb_overlay_parent_beta", 0.35) or 0.35)))
            for d in list(entry.get("delta_diff_table", []) or []):
                if not isinstance(d, dict):
                    continue
                target_id = str(d.get("target_id", "") or "")
                if not target_id:
                    continue
                w = max(0.0, float(d.get("base_weight", 0.0) or 0.0))
                if w <= 0.0:
                    continue
                existing = merged.get(target_id)
                if existing is None:
                    merged[target_id] = {
                        "target_id": target_id,
                        "base_weight": round(w, 8),
                        "entry_type": str(d.get("entry_type", "structure_ref") or "structure_ref"),
                        "ext": {"support_hits": 1, "sources": ["delta"]},
                    }
                    continue
                old_w = float(existing.get("base_weight", 0.0) or 0.0)
                merged_w = max(old_w, w) + beta * min(old_w, w)
                existing["base_weight"] = round(float(merged_w), 8)
                ext = existing.get("ext") if isinstance(existing.get("ext"), dict) else {}
                sources = list(ext.get("sources", []) or [])
                if "delta" not in sources:
                    sources.append("delta")
                ext["sources"] = sources[:12]
                ext["support_hits"] = int(ext.get("support_hits", 1) or 1) + 1
                existing["ext"] = ext

            rows = list(merged.values())
            rows.sort(key=lambda r: float(r.get("base_weight", 0.0) or 0.0), reverse=True)
            picked = rows[:top_k]
            total = sum(max(0.0, float(r.get("base_weight", 0.0) or 0.0)) for r in picked)
            return picked, float(total)

        ttl_ms = max(0, int(self._config.get("esdb_overlay_cache_ttl_ms", 2500) or 2500))
        if use_cache and ttl_ms > 0:
            cache = entry.get("runtime_cache") if isinstance(entry.get("runtime_cache"), dict) else {}
            now_ms = int(time.time() * 1000)
            cached_at = int(cache.get("overlay_cached_at_ms", 0) or 0)
            cached_top_k = int(cache.get("overlay_cached_top_k", 0) or 0)
            cached_rows = cache.get("overlay_cached_rows")
            cached_total = cache.get("overlay_cached_total")
            if (
                isinstance(cached_rows, list)
                and isinstance(cached_total, (int, float))
                and cached_top_k >= top_k
                and cached_at > 0
                and (now_ms - cached_at) <= ttl_ms
            ):
                return list(cached_rows[:top_k]), float(cached_total)

        if event_ref_id in visited:
            return [], 0.0
        visited.add(event_ref_id)

        beta = max(0.0, min(1.0, float(self._config.get("esdb_overlay_parent_beta", 0.35) or 0.35)))
        merged: dict[str, dict[str, Any]] = {}

        # Start with delta table (kept empty in phase2, reserved for future).
        for d in list(entry.get("delta_diff_table", []) or []):
            if not isinstance(d, dict):
                continue
            target_id = str(d.get("target_id", "") or "")
            if not target_id:
                continue
            w = max(0.0, float(d.get("base_weight", 0.0) or 0.0))
            merged[target_id] = {
                "target_id": target_id,
                "base_weight": round(w, 8),
                "entry_type": str(d.get("entry_type", "structure_ref") or "structure_ref"),
                "ext": {"support_hits": 1, "sources": ["delta"]},
            }

        # Merge parents top-k (parents can be ST DB owners or other ES ids).
        structure_store = getattr(hdb, "_structure_store", None)
        for parent_ref in [str(x) for x in (entry.get("parents", []) or []) if str(x)]:
            parent_rows: list[dict] = []
            if self._is_event_ref_id(parent_ref):
                parent_rows, _ = self._esdb_open_overlay_diff_entries(
                    event_ref_id=parent_ref,
                    hdb=hdb,
                    top_k=top_k,
                    visited=visited,
                    use_cache=use_cache,
                )
            else:
                if structure_store is None:
                    continue
                parent_db = structure_store.get_db_by_owner(parent_ref) if hasattr(structure_store, "get_db_by_owner") else None
                if not isinstance(parent_db, dict):
                    continue
                diff_table = [r for r in list(parent_db.get("diff_table", []) or []) if isinstance(r, dict) and str(r.get("target_id", "") or "")]
                if not diff_table:
                    continue
                diff_table.sort(key=self._diff_entry_effective_weight, reverse=True)
                parent_rows = diff_table[:top_k]

            for pr in parent_rows:
                if not isinstance(pr, dict):
                    continue
                target_id = str(pr.get("target_id", "") or "")
                if not target_id:
                    continue
                w = max(0.0, float(self._diff_entry_effective_weight(pr)))
                if w <= 0.0:
                    continue
                existing = merged.get(target_id)
                if existing is None:
                    merged[target_id] = {
                        "target_id": target_id,
                        "base_weight": round(w, 8),
                        "entry_type": str(pr.get("entry_type", "structure_ref") or "structure_ref"),
                        "ext": {"support_hits": 1, "sources": [parent_ref]},
                    }
                    continue
                old_w = float(existing.get("base_weight", 0.0) or 0.0)
                merged_w = max(old_w, w) + beta * min(old_w, w)
                existing["base_weight"] = round(float(merged_w), 8)
                ext = existing.get("ext") if isinstance(existing.get("ext"), dict) else {}
                sources = list(ext.get("sources", []) or [])
                if parent_ref not in sources:
                    sources.append(parent_ref)
                ext["sources"] = sources[:12]
                ext["support_hits"] = int(ext.get("support_hits", 1) or 1) + 1
                existing["ext"] = ext

        rows = list(merged.values())
        rows.sort(key=lambda r: float(r.get("base_weight", 0.0) or 0.0), reverse=True)
        picked = rows[:top_k]
        total = sum(max(0.0, float(r.get("base_weight", 0.0) or 0.0)) for r in picked)

        if use_cache and ttl_ms > 0:
            cache = entry.get("runtime_cache") if isinstance(entry.get("runtime_cache"), dict) else {}
            cache["overlay_cached_at_ms"] = int(time.time() * 1000)
            cache["overlay_cached_top_k"] = int(top_k)
            cache["overlay_cached_rows"] = picked
            cache["overlay_cached_total"] = float(total)
            entry["runtime_cache"] = cache

        return picked, float(total)

    def _esdb_delta_upsert_edge(
        self,
        *,
        event_ref_id: str,
        target_id: str,
        base_weight: float,
        source_ref: str,
        tick_id: str,
        action_type: str,
        distance: int,
    ) -> None:
        if not event_ref_id or not self._is_event_ref_id(event_ref_id):
            return
        if not target_id:
            return
        if base_weight <= 0.0:
            return
        entry = self._esdb.get(event_ref_id)
        if not isinstance(entry, dict):
            return

        now_ms = int(time.time() * 1000)
        beta = max(0.0, min(1.0, float(self._config.get("esdb_delta_merge_beta", 0.25) or 0.25)))
        max_entries = max(8, int(self._config.get("esdb_delta_max_entries", 96)))

        delta = [d for d in list(entry.get("delta_diff_table", []) or []) if isinstance(d, dict)]
        found = None
        for d in delta:
            if str(d.get("target_id", "") or "") == target_id:
                found = d
                break
        if found is None:
            delta.append(
                {
                    "target_id": target_id,
                    "base_weight": round(float(base_weight), 8),
                    "entry_type": "structure_ref",
                    "recent_gain": 1.0,
                    "fatigue": 0.0,
                    "created_at_ms": now_ms,
                    "updated_at_ms": now_ms,
                    "ext": {
                        "support_hits": 1,
                        "sources": [source_ref] if str(source_ref or "") else [],
                        "action_type": str(action_type or ""),
                        "distance": int(distance),
                        "last_tick_id": str(tick_id or ""),
                    },
                }
            )
        else:
            old_w = max(0.0, float(found.get("base_weight", 0.0) or 0.0))
            merged_w = max(old_w, float(base_weight)) + beta * min(old_w, float(base_weight))
            found["base_weight"] = round(float(merged_w), 8)
            found["updated_at_ms"] = now_ms
            ext = found.get("ext") if isinstance(found.get("ext"), dict) else {}
            ext["support_hits"] = int(ext.get("support_hits", 1) or 1) + 1
            sources = list(ext.get("sources", []) or [])
            if str(source_ref or "") and str(source_ref) not in sources:
                sources.append(str(source_ref))
            ext["sources"] = sources[:12]
            ext["action_type"] = str(action_type or "") or ext.get("action_type", "")
            ext["distance"] = int(distance)
            ext["last_tick_id"] = str(tick_id or "")
            found["ext"] = ext

        # Keep delta ordered and bounded.
        delta = [d for d in delta if str(d.get("target_id", "") or "")]
        delta.sort(key=lambda r: float(r.get("base_weight", 0.0) or 0.0), reverse=True)
        entry["delta_diff_table"] = delta[:max_entries]
        # Delta change invalidates overlay cache (but does not force re-materialization).
        entry["runtime_cache"] = {}

    def _esdb_refresh_delta_from_tail_components(self, *, event_ref_id: str, components: list[str], hdb, tick_id: str, action_type: str) -> dict:
        """Import a small set of outgoing edges from tail component ST DBs into ES delta."""
        if not bool(self._config.get("enable_esdb_delta", True)):
            return {"enabled": False, "reason": "disabled_by_config", "imported_edge_count": 0}
        if not event_ref_id or not self._is_event_ref_id(event_ref_id):
            return {"enabled": False, "reason": "not_event", "imported_edge_count": 0}
        entry = self._esdb.get(event_ref_id)
        if not isinstance(entry, dict):
            return {"enabled": False, "reason": "missing_esdb_entry", "imported_edge_count": 0}

        structure_store = getattr(hdb, "_structure_store", None)
        if structure_store is None:
            return {"enabled": False, "reason": "no_structure_store", "imported_edge_count": 0}

        max_context_k = max(1, int(self._config.get("max_context_k", 2)))
        tail_refs = [str(x) for x in list(components or [])[-max_context_k:] if str(x)]
        if not tail_refs:
            return {"enabled": False, "reason": "empty_tail", "imported_edge_count": 0}

        import_top_k = max(1, int(self._config.get("esdb_delta_import_top_k_per_tail", 6)))
        distance_decay = max(0.0, min(1.0, float(self._config.get("esdb_delta_distance_decay", 0.75) or 0.75)))
        min_weight = max(0.0, float(self._config.get("esdb_delta_min_weight", 0.0001) or 0.0001))
        component_set = {str(x) for x in (components or []) if str(x)}

        imported = 0
        for distance, tail_ref in enumerate(reversed(tail_refs)):
            entries, _ = self._top_diff_entries(structure_store=structure_store, owner_ref_id=tail_ref)
            if not entries:
                continue
            scale = 1.0 if distance <= 0 else (distance_decay ** float(distance))
            for e in list(entries[:import_top_k]):
                if not isinstance(e, dict):
                    continue
                target_id = str(e.get("target_id", "") or "")
                if not target_id:
                    continue
                if target_id in component_set:
                    continue
                w = max(0.0, float(self._diff_entry_effective_weight(e))) * float(scale)
                if w < min_weight:
                    continue
                self._esdb_delta_upsert_edge(
                    event_ref_id=event_ref_id,
                    target_id=target_id,
                    base_weight=float(w),
                    source_ref=tail_ref,
                    tick_id=tick_id,
                    action_type=action_type,
                    distance=int(distance),
                )
                imported += 1

        # Keep delta clean: do not keep edges to already-in-event components.
        try:
            delta = [d for d in list(entry.get("delta_diff_table", []) or []) if isinstance(d, dict) and str(d.get("target_id", "") or "") and str(d.get("target_id", "") or "") not in component_set]
            entry["delta_diff_table"] = delta
        except Exception:
            pass

        return {"enabled": True, "reason": "ok", "imported_edge_count": int(imported)}

    @staticmethod
    def _diff_entry_effective_weight(entry: dict) -> float:
        try:
            base_weight = max(0.0, float(entry.get("base_weight", 0.0) or 0.0))
            recent_gain = max(1.0, float(entry.get("recent_gain", 1.0) or 1.0))
            fatigue = max(0.0, float(entry.get("fatigue", 0.0) or 0.0))
            return round(base_weight * recent_gain / (1.0 + fatigue), 8)
        except Exception:
            return 0.0

    @staticmethod
    def _safe_apply_energy_update(
        *,
        pool,
        item_id: str,
        delta_er: float,
        delta_ev: float,
        trace_id: str,
        tick_id: str,
        reason: str,
    ) -> None:
        if not item_id:
            return
        if abs(float(delta_er)) < 1e-9 and abs(float(delta_ev)) < 1e-9:
            return
        if not hasattr(pool, "apply_energy_update"):
            return
        pool.apply_energy_update(
            target_item_id=item_id,
            delta_er=float(delta_er),
            delta_ev=float(delta_ev),
            trace_id=trace_id,
            tick_id=tick_id,
            reason=reason,
            source_module="cognitive_stitching",
        )

    @staticmethod
    def _get_existing_state_item_by_ref(*, pool, ref_object_id: str) -> dict | None:
        store = getattr(pool, "_store", None)
        if store is None or not hasattr(store, "get_by_ref"):
            return None
        try:
            return store.get_by_ref(ref_object_id)
        except Exception:
            return None

    def _upsert_candidate(self, *, best_by_signature: dict[str, dict], candidate: dict) -> None:
        signature = str(candidate.get("candidate_signature", "") or "")
        existing = best_by_signature.get(signature)
        if existing is None:
            best_by_signature[signature] = candidate
            self._audit_candidate_competition(existing=None, candidate=candidate, outcome="stored_new")
            return
        if self._candidate_competition_key(candidate) > self._candidate_competition_key(existing):
            best_by_signature[signature] = candidate
            self._audit_candidate_competition(existing=existing, candidate=candidate, outcome="replaced_existing")
            return
        self._audit_candidate_competition(existing=existing, candidate=candidate, outcome="kept_existing")

    def _candidate_signature(self, *, action_type: str, new_components: list[str]) -> str:
        return f"{action_type}::{'|'.join(new_components)}"

    def _fatigue_scale(self, fatigue_before: float) -> float:
        floor_scale = max(0.0, min(1.0, float(self._config.get("same_pair_fatigue_floor_scale", 0.25))))
        fatigue_cap = max(0.01, float(self._config.get("same_pair_fatigue_cap", 1.6)))
        return max(
            floor_scale,
            1.0 - min(max(0.0, float(fatigue_before)), fatigue_cap) / fatigue_cap * (1.0 - floor_scale),
        )

    def _object_stitch_fatigue_bundle(self, *, source_ref_id: str, target_ref_id: str, result_ref_id: str = "") -> dict[str, Any]:
        if not bool(self._config.get("object_stitch_fatigue_enabled", True)):
            return {"scale": 1.0, "max_fatigue": 0.0, "refs": []}
        refs = self._dedupe_ids([source_ref_id, target_ref_id, result_ref_id])
        values = [max(0.0, float(self._object_stitch_fatigue.get(ref_id, 0.0) or 0.0)) for ref_id in refs]
        max_fatigue = max(values) if values else 0.0
        return {
            "scale": round(float(self._object_stitch_fatigue_scale(max_fatigue)), 8),
            "max_fatigue": round(float(max_fatigue), 8),
            "refs": refs,
        }

    def _active_item_identity_key(self, item: dict | None) -> str:
        if not isinstance(item, dict):
            return ""
        key = str(item.get("semantic_context_key", "") or "").strip()
        if key:
            return f"semctx:{key}"
        ref_id = str(item.get("ref_object_id", "") or "").strip()
        if ref_id:
            context_owner_id = str(item.get("context_owner_id", "") or "").strip() or "<none>"
            context_text = str(item.get("context_text", "") or "").strip() or "<none>"
            return f"refctx:{ref_id}|owner={context_owner_id}|text={context_text}"
        try:
            computed = semantic_context_key_from_item(item)
        except Exception:
            computed = ""
        if computed:
            return f"semctx:{computed}"
        item_id = str(item.get("item_id", "") or "").strip()
        return f"item:{item_id}" if item_id else ""

    def _object_stitch_fatigue_scale(self, fatigue_before: float) -> float:
        floor_scale = max(0.0, min(1.0, float(self._config.get("object_stitch_fatigue_floor_scale", 0.28))))
        fatigue_cap = max(0.01, float(self._config.get("object_stitch_fatigue_cap", 2.2)))
        fatigue = min(max(0.0, float(fatigue_before)), fatigue_cap)
        return max(floor_scale, 1.0 - fatigue / fatigue_cap * (1.0 - floor_scale))

    def _active_execution_min_candidate_score(self) -> float:
        if self._uses_v2_execution():
            return max(0.0, float(self._config.get("cs_v2_min_match_score", 0.18)))
        return max(0.0, float(self._config.get("min_candidate_score", 0.22)))

    def _fatigue_upper_bound_prunes_candidate(self, *, action_type: str, fatigue_scale: float, anchor_scale: float) -> bool:
        if action_type != "concat_context_structure":
            return False
        fatigue_gate = max(0.0, float(fatigue_scale))
        if fatigue_gate <= 0.0:
            return True
        if self._uses_v2_execution():
            if not bool(self._config.get("cs_v2_same_pair_fatigue_enabled", True)):
                return False
            fatigue_soft_power = max(0.05, float(self._config.get("cs_v2_fatigue_soft_power", 0.78) or 0.78))
            fatigue_soft_mix = self._clamp01(float(self._config.get("cs_v2_fatigue_soft_linear_mix", 0.40) or 0.40))
            max_v2_score = self._soft_uplift01(
                self._clamp01(fatigue_gate),
                power=fatigue_soft_power,
                linear_mix=fatigue_soft_mix,
            )
            return max_v2_score < max(0.0, float(self._config.get("cs_v2_min_match_score", 0.18)))

        max_legacy_base_score = (
            max(0.0, float(self._config.get("edge_ratio_weight", 0.42)))
            + max(0.0, float(self._config.get("energy_balance_weight", 0.23)))
            + max(0.0, float(self._config.get("match_strength_weight", 0.20)))
            + max(0.0, float(self._config.get("runtime_weight_weight", 0.15)))
            + max(0.0, float(self._config.get("context_support_weight", 0.18)))
            + max(0.0, float(self._config.get("bridge_span_weight", 0.08)))
            + max(0.0, float(self._config.get("context_concat_match_count_weight", 0.12) or 0.12))
            + max(0.0, float(self._config.get("context_concat_attribute_bonus_weight", 0.08) or 0.08))
        )
        max_legacy_score = max_legacy_base_score * self._clamp01(float(anchor_scale)) * fatigue_gate
        return max_legacy_score < max(0.0, float(self._config.get("min_candidate_score", 0.22)))

    def _apply_object_stitch_fatigue(self, *ref_ids: str) -> dict[str, float]:
        if not bool(self._config.get("object_stitch_fatigue_enabled", True)):
            return {}
        step = max(0.0, float(self._config.get("object_stitch_fatigue_step", 0.85) or 0.85))
        cap = max(0.01, float(self._config.get("object_stitch_fatigue_cap", 2.2) or 2.2))
        updated: dict[str, float] = {}
        for ref_id in self._dedupe_ids(list(ref_ids)):
            next_value = round(min(cap, max(0.0, float(self._object_stitch_fatigue.get(ref_id, 0.0) or 0.0)) + step), 8)
            self._object_stitch_fatigue[ref_id] = next_value
            updated[ref_id] = next_value
        return updated

    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _mode_alignment_scale(match_mode: str) -> float:
        mode = str(match_mode or "").strip().lower()
        if mode in {"exact", "event_prefix_exact"}:
            return 1.0
        if mode in {"containment", "event_prefix"}:
            return 0.92
        if mode in {"weak_overlap", "event_prefix_weak"}:
            return 0.72
        return 0.84

    @classmethod
    def _soft_uplift01(cls, value: float, *, power: float = 0.72, linear_mix: float = 0.32) -> float:
        raw = cls._clamp01(value)
        curved_power = max(0.05, float(power))
        mix = cls._clamp01(linear_mix)
        curved = math.pow(raw, curved_power) if raw > 0.0 else 0.0
        return cls._clamp01(mix * raw + (1.0 - mix) * curved)

    @classmethod
    def _energy_profile_similarity(cls, source: dict, target: dict) -> float:
        src_er = max(0.0, float(source.get("er", 0.0) or 0.0))
        src_ev = max(0.0, float(source.get("ev", 0.0) or 0.0))
        tgt_er = max(0.0, float(target.get("er", 0.0) or 0.0))
        tgt_ev = max(0.0, float(target.get("ev", 0.0) or 0.0))
        src_total = src_er + src_ev
        tgt_total = tgt_er + tgt_ev
        if src_total <= 1e-9 or tgt_total <= 1e-9:
            return 0.0
        src_ev_share = src_ev / src_total
        tgt_ev_share = tgt_ev / tgt_total
        return round(cls._clamp01(1.0 - abs(src_ev_share - tgt_ev_share)), 8)

    def _build_v2_score_breakdown(
        self,
        *,
        action_type: str,
        source: dict,
        target: dict,
        matched: dict,
        context_hits: int,
        closest_distance: int,
        edge_ratio: float,
        fatigue_scale: float,
    ) -> dict[str, Any]:
        max_context_k = max(1, int(self._config.get("max_context_k", 2)))
        max_event_head_match_components = max(1, int(self._config.get("max_event_head_match_components", 3)))
        source_components = [str(x) for x in (source.get("components", []) or []) if str(x)]
        target_components = [str(x) for x in (target.get("components", []) or []) if str(x)]
        target_tokens = [str(x) for x in (target.get("tokens", []) or []) if str(x)]
        matched_span = int(matched.get("matched_span", 1) or 1)
        prefix_components = int(matched.get("prefix_components", 1) or 1)
        if action_type == "concat_context_structure":
            context_cover_raw = self._clamp01(float(matched.get("context_ratio", 0.0) or 0.0))
            context_cover_score = context_cover_raw
            order_alignment_score = self._clamp01(float(matched.get("order_score", context_cover_raw) or context_cover_raw))
            tail_match_score = self._clamp01(
                max(
                    float(matched.get("tail_score", 0.0) or 0.0),
                    float(matched.get("last_token_score", 0.0) or 0.0),
                )
            )
            edge_support = math.sqrt(self._clamp01(edge_ratio))
            context_db_support_score = self._clamp01(
                0.46 * edge_support
                + 0.34 * float(matched.get("path_support_score", 0.0) or 0.0)
                + 0.20 * float(matched.get("direct_owner_score", 0.0) or 0.0)
            )
            match_count_score = self._clamp01(float(matched.get("match_count_score", 0.0) or 0.0))
            attribute_bonus_score = self._clamp01(float(matched.get("attribute_bonus_score", 0.0) or 0.0))
        else:
            context_denominator = max(1, min(len(source_components), max_context_k))
            context_cover_raw = self._clamp01(float(context_hits) / float(context_denominator))

            if str(target.get("kind", "") or "") == "event":
                prefix_denominator = max(1, min(len(target_components) or prefix_components, max_event_head_match_components))
                prefix_ratio = self._clamp01(float(prefix_components) / float(prefix_denominator))
                context_cover_score = self._clamp01(max(context_cover_raw, math.sqrt(max(0.0, context_cover_raw * prefix_ratio))))
                overlap = self._boundary_overlap(source_components, target_components)
                order_denominator = max(1, min(len(target_components), max_event_head_match_components))
                order_alignment_score = self._clamp01(float(overlap) / float(order_denominator))
                tail_span_denominator = max(1, min(len(target_components) or len(target_tokens) or 1, max_event_head_match_components))
            else:
                context_cover_score = context_cover_raw
                order_alignment_score = self._mode_alignment_scale(str(matched.get("mode", "") or ""))
                tail_span_denominator = max(1, len(target_tokens) or 1)

            tail_match_score = self._clamp01(float(matched_span) / float(tail_span_denominator))
            distance_score = self._clamp01(
                1.0 - min(max(0, int(closest_distance)), max_context_k) / float(max(1, max_context_k))
            )
            edge_support = math.sqrt(self._clamp01(edge_ratio))
            context_db_support_score = self._clamp01(0.58 * edge_support + 0.22 * distance_score + 0.20 * context_cover_score)
            match_count_score = 0.0
            attribute_bonus_score = 0.0
        energy_profile_score = self._energy_profile_similarity(source, target)

        weight_context_cover = max(0.0, float(self._config.get("cs_v2_context_cover_weight", 0.32)))
        weight_order = max(0.0, float(self._config.get("cs_v2_order_weight", 0.22)))
        weight_tail = max(0.0, float(self._config.get("cs_v2_tail_match_weight", 0.28)))
        weight_context_db = max(0.0, float(self._config.get("cs_v2_context_db_weight", 0.10)))
        weight_energy_profile = max(0.0, float(self._config.get("cs_v2_energy_profile_weight", 0.08)))
        weight_match_count = max(0.0, float(self._config.get("cs_v2_match_count_weight", 0.10) or 0.10))
        weight_attribute_bonus = max(0.0, float(self._config.get("cs_v2_attribute_bonus_weight", 0.06) or 0.06))
        component_soft_power = max(0.05, float(self._config.get("cs_v2_component_soft_power", 0.72) or 0.72))
        component_soft_mix = self._clamp01(float(self._config.get("cs_v2_component_soft_linear_mix", 0.32) or 0.32))
        base_raw_mix = self._clamp01(float(self._config.get("cs_v2_base_raw_mix", 0.35) or 0.35))
        fatigue_soft_power = max(0.05, float(self._config.get("cs_v2_fatigue_soft_power", 0.78) or 0.78))
        fatigue_soft_mix = self._clamp01(float(self._config.get("cs_v2_fatigue_soft_linear_mix", 0.40) or 0.40))
        context_cover_soft_score = self._soft_uplift01(
            context_cover_score,
            power=component_soft_power,
            linear_mix=component_soft_mix,
        )
        order_alignment_soft_score = self._soft_uplift01(
            order_alignment_score,
            power=component_soft_power,
            linear_mix=component_soft_mix,
        )
        tail_match_soft_score = self._soft_uplift01(
            tail_match_score,
            power=component_soft_power,
            linear_mix=component_soft_mix,
        )
        context_db_support_soft_score = self._soft_uplift01(
            context_db_support_score,
            power=component_soft_power,
            linear_mix=component_soft_mix,
        )
        energy_profile_soft_score = self._soft_uplift01(
            energy_profile_score,
            power=component_soft_power,
            linear_mix=component_soft_mix,
        )
        match_count_soft_score = self._soft_uplift01(
            match_count_score,
            power=component_soft_power,
            linear_mix=component_soft_mix,
        )
        attribute_bonus_soft_score = self._soft_uplift01(
            attribute_bonus_score,
            power=component_soft_power,
            linear_mix=component_soft_mix,
        )
        v2_weight_sum = max(
            1e-9,
            weight_context_cover
            + weight_order
            + weight_tail
            + weight_context_db
            + weight_energy_profile
            + weight_match_count
            + weight_attribute_bonus,
        )
        v2_base_score_raw = (
            weight_context_cover * context_cover_score
            + weight_order * order_alignment_score
            + weight_tail * tail_match_score
            + weight_context_db * context_db_support_score
            + weight_energy_profile * energy_profile_score
            + weight_match_count * match_count_score
            + weight_attribute_bonus * attribute_bonus_score
        ) / v2_weight_sum
        v2_base_score_soft = (
            weight_context_cover * context_cover_soft_score
            + weight_order * order_alignment_soft_score
            + weight_tail * tail_match_soft_score
            + weight_context_db * context_db_support_soft_score
            + weight_energy_profile * energy_profile_soft_score
            + weight_match_count * match_count_soft_score
            + weight_attribute_bonus * attribute_bonus_soft_score
        ) / v2_weight_sum
        v2_base_score = self._clamp01(base_raw_mix * v2_base_score_raw + (1.0 - base_raw_mix) * v2_base_score_soft)
        v2_fatigue_gate_raw = fatigue_scale if bool(self._config.get("cs_v2_same_pair_fatigue_enabled", True)) else 1.0
        v2_fatigue_gate_soft = self._soft_uplift01(
            v2_fatigue_gate_raw,
            power=fatigue_soft_power,
            linear_mix=fatigue_soft_mix,
        )
        v2_fatigue_gate = v2_fatigue_gate_soft
        if action_type == "merge_event":
            v2_fatigue_gate = min(v2_fatigue_gate, 1.0)
        v2_score = self._clamp01(v2_base_score * max(0.0, float(v2_fatigue_gate)))
        v2_min_match_score = max(0.0, float(self._config.get("cs_v2_min_match_score", 0.18)))
        return {
            "v2_base_score_raw": round(v2_base_score_raw, 8),
            "v2_base_score_soft": round(v2_base_score_soft, 8),
            "v2_base_score": round(v2_base_score, 8),
            "v2_score": round(v2_score, 8),
            "v2_min_match_score": round(v2_min_match_score, 8),
            "v2_threshold_margin": round(v2_score - v2_min_match_score, 8),
            "v2_context_cover_score": round(context_cover_score, 8),
            "v2_context_cover_soft_score": round(context_cover_soft_score, 8),
            "v2_order_alignment_score": round(order_alignment_score, 8),
            "v2_order_alignment_soft_score": round(order_alignment_soft_score, 8),
            "v2_tail_match_score": round(tail_match_score, 8),
            "v2_tail_match_soft_score": round(tail_match_soft_score, 8),
            "v2_context_db_support_score": round(context_db_support_score, 8),
            "v2_context_db_support_soft_score": round(context_db_support_soft_score, 8),
            "v2_energy_profile_score": round(energy_profile_score, 8),
            "v2_energy_profile_soft_score": round(energy_profile_soft_score, 8),
            "v2_match_count_score": round(match_count_score, 8),
            "v2_match_count_soft_score": round(match_count_soft_score, 8),
            "v2_attribute_bonus_score": round(attribute_bonus_score, 8),
            "v2_attribute_bonus_soft_score": round(attribute_bonus_soft_score, 8),
            "v2_fatigue_gate_raw": round(float(v2_fatigue_gate_raw), 8),
            "v2_fatigue_gate_soft": round(float(v2_fatigue_gate_soft), 8),
            "v2_fatigue_gate": round(float(v2_fatigue_gate), 8),
            "v2_passes_threshold": bool(v2_score >= v2_min_match_score),
        }

    def _is_component_sequence_valid(self, components: list[str]) -> bool:
        if len(components) < 2:
            return False
        max_component_count = max(2, int(self._config.get("max_event_component_count", 8)))
        if len(components) > max_component_count:
            return False
        return all(str(item or "").strip() for item in components)

    def _merge_event_components(self, *, left: list[str], right: list[str]) -> list[str]:
        if not left or not right:
            return []
        overlap = self._boundary_overlap(left, right)
        if overlap == 0:
            shared = set(left) & set(right)
            if shared:
                return []
        merged = list(left) + list(right[overlap:])
        if len(merged) <= max(len(left), len(right)):
            return []
        return merged

    @staticmethod
    def _boundary_overlap(left: list[str], right: list[str]) -> int:
        max_overlap = min(len(left), len(right))
        for overlap in range(max_overlap, 0, -1):
            if left[-overlap:] == right[:overlap]:
                return overlap
        return 0

    def _event_ref_id_from_components(self, components: list[str]) -> str:
        prefix = str(self._config.get("event_id_prefix", "cs_event"))
        return f"{prefix}::" + "::".join(str(item) for item in components if str(item))

    def _parse_event_components(self, ref_object_id: str) -> list[str]:
        prefix = f"{self._config.get('event_id_prefix', 'cs_event')}::"
        if not ref_object_id.startswith(prefix):
            return []
        tail = ref_object_id[len(prefix) :]
        return [part for part in tail.split("::") if part]

    def _resolve_component_displays(self, *, components: list[str], structure_store) -> list[str]:
        if not components:
            return []
        displays: list[str] = []
        for component_ref in components:
            display = ""
            if structure_store is not None:
                structure_obj = structure_store.get(component_ref)
                if isinstance(structure_obj, dict):
                    display = self._structure_display(structure_obj)
            displays.append(display or str(component_ref))
        return displays

    def _event_display_from_components(self, component_displays: list[str]) -> str:
        if not component_displays:
            return ""
        return str(self._config.get("display_joiner", " -> ")).join(component_displays)

    @staticmethod
    def _candidate_preview(candidate: dict) -> dict[str, Any]:
        return {
            "action_type": candidate.get("action_type", ""),
            "source_display": candidate.get("source", {}).get("display", ""),
            "source_kind": candidate.get("source", {}).get("kind", ""),
            "source_ref_id": candidate.get("source", {}).get("ref_object_id", ""),
            "source_item_id": candidate.get("source", {}).get("item_id", ""),
            "source_projected_from_non_st_support": bool(candidate.get("source", {}).get("projected_from_non_st_support", False)),
            "source_runtime_ref_object_id": candidate.get("source", {}).get("runtime_ref_object_id", ""),
            "source_runtime_ref_object_type": candidate.get("source", {}).get("runtime_ref_object_type", ""),
            "source_support_structure_ids": list(candidate.get("source", {}).get("support_structure_ids", []) or []),
            "target_display": candidate.get("target", {}).get("display", ""),
            "target_kind": candidate.get("target", {}).get("kind", ""),
            "target_ref_id": candidate.get("target", {}).get("ref_object_id", ""),
            "target_item_id": candidate.get("target", {}).get("item_id", ""),
            "result_display": candidate.get("result_display", ""),
            "context_owner_id": candidate.get("result_context_owner_id", ""),
            "edge_target_id": candidate.get("edge_target_id", ""),
            "match_mode": candidate.get("match_mode", ""),
            "score_source": candidate.get("score_source", "legacy"),
            "execution_uses_v2_score": bool(candidate.get("execution_uses_v2_score", False)),
            "score": round(float(candidate.get("score", 0.0)), 8),
            "legacy_score": round(float(candidate.get("legacy_score", 0.0)), 8),
            "edge_weight_ratio": round(float(candidate.get("edge_weight_ratio", 0.0)), 8),
            "match_strength": round(float(candidate.get("match_strength", 0.0)), 8),
            "context_k": int(candidate.get("context_hits", 1) or 1),
            "context_ratio": round(float(candidate.get("context_ratio", 0.0)), 8),
            "matched_span": int(candidate.get("matched_span", 1) or 1),
            "energy_balance": round(float(candidate.get("energy_balance", 0.0)), 8),
            "runtime_balance": round(float(candidate.get("runtime_balance", 0.0)), 8),
            "bridge_span_ratio": round(float(candidate.get("bridge_span_ratio", 0.0)), 8),
            "base_score": round(float(candidate.get("base_score", 0.0)), 8),
            "legacy_base_score": round(float(candidate.get("legacy_base_score", 0.0)), 8),
            "anchor_scale": round(float(candidate.get("anchor_scale", 0.0)), 8),
            "path_support_score": round(float(candidate.get("path_support_score", 0.0)), 8),
            "last_token_score": round(float(candidate.get("last_token_score", 0.0)), 8),
            "pair_fatigue_before": round(float(candidate.get("pair_fatigue_before", candidate.get("fatigue_before", 0.0)) or 0.0), 8),
            "pair_fatigue_scale": round(float(candidate.get("pair_fatigue_scale", 1.0) or 1.0), 8),
            "target_context_prefix_trimmed": bool(candidate.get("target_context_prefix_trimmed", False)),
            "target_context_prefix_trim_count": int(candidate.get("target_context_prefix_trim_count", 0) or 0),
            "exact_context_identity_match": bool(candidate.get("exact_context_identity_match", False)),
            "object_stitch_fatigue_before": round(float(candidate.get("object_stitch_fatigue_before", 0.0) or 0.0), 8),
            "object_stitch_fatigue_scale": round(float(candidate.get("object_stitch_fatigue_scale", 1.0) or 1.0), 8),
            "object_stitch_fatigue_refs": list(candidate.get("object_stitch_fatigue_refs", []) or []),
            "fatigue_before": round(float(candidate.get("fatigue_before", 0.0)), 8),
            "fatigue_scale": round(float(candidate.get("fatigue_scale", 0.0)), 8),
            "min_candidate_score": round(float(candidate.get("min_candidate_score", 0.0)), 8),
            "legacy_min_candidate_score": round(float(candidate.get("legacy_min_candidate_score", 0.0)), 8),
            "threshold_margin": round(float(candidate.get("threshold_margin", 0.0)), 8),
            "legacy_threshold_margin": round(float(candidate.get("legacy_threshold_margin", 0.0)), 8),
            "edge_ratio_component": round(float(candidate.get("edge_ratio_component", 0.0)), 8),
            "energy_balance_component": round(float(candidate.get("energy_balance_component", 0.0)), 8),
            "match_strength_component": round(float(candidate.get("match_strength_component", 0.0)), 8),
            "runtime_balance_component": round(float(candidate.get("runtime_balance_component", 0.0)), 8),
            "context_support_component": round(float(candidate.get("context_support_component", 0.0)), 8),
            "bridge_span_component": round(float(candidate.get("bridge_span_component", 0.0)), 8),
            "match_count_score": round(float(candidate.get("match_count_score", 0.0)), 8),
            "attribute_bonus_score": round(float(candidate.get("attribute_bonus_score", 0.0)), 8),
            "match_count_component": round(float(candidate.get("match_count_component", 0.0)), 8),
            "attribute_bonus_component": round(float(candidate.get("attribute_bonus_component", 0.0)), 8),
            "effective_match_units": round(float(candidate.get("effective_match_units", 0.0)), 8),
            "attribute_bonus_equivalent_units": round(float(candidate.get("attribute_bonus_equivalent_units", 0.0)), 8),
            "v2_score": round(float(candidate.get("v2_score", 0.0)), 8),
            "v2_base_score_raw": round(float(candidate.get("v2_base_score_raw", 0.0)), 8),
            "v2_base_score": round(float(candidate.get("v2_base_score", 0.0)), 8),
            "v2_base_score_soft": round(float(candidate.get("v2_base_score_soft", 0.0)), 8),
            "v2_min_match_score": round(float(candidate.get("v2_min_match_score", 0.0)), 8),
            "v2_threshold_margin": round(float(candidate.get("v2_threshold_margin", 0.0)), 8),
            "v2_context_cover_score": round(float(candidate.get("v2_context_cover_score", 0.0)), 8),
            "v2_context_cover_soft_score": round(float(candidate.get("v2_context_cover_soft_score", 0.0)), 8),
            "v2_order_alignment_score": round(float(candidate.get("v2_order_alignment_score", 0.0)), 8),
            "v2_order_alignment_soft_score": round(float(candidate.get("v2_order_alignment_soft_score", 0.0)), 8),
            "v2_tail_match_score": round(float(candidate.get("v2_tail_match_score", 0.0)), 8),
            "v2_tail_match_soft_score": round(float(candidate.get("v2_tail_match_soft_score", 0.0)), 8),
            "v2_context_db_support_score": round(float(candidate.get("v2_context_db_support_score", 0.0)), 8),
            "v2_context_db_support_soft_score": round(float(candidate.get("v2_context_db_support_soft_score", 0.0)), 8),
            "v2_energy_profile_score": round(float(candidate.get("v2_energy_profile_score", 0.0)), 8),
            "v2_energy_profile_soft_score": round(float(candidate.get("v2_energy_profile_soft_score", 0.0)), 8),
            "v2_match_count_score": round(float(candidate.get("v2_match_count_score", 0.0)), 8),
            "v2_match_count_soft_score": round(float(candidate.get("v2_match_count_soft_score", 0.0)), 8),
            "v2_attribute_bonus_score": round(float(candidate.get("v2_attribute_bonus_score", 0.0)), 8),
            "v2_attribute_bonus_soft_score": round(float(candidate.get("v2_attribute_bonus_soft_score", 0.0)), 8),
            "v2_fatigue_gate_raw": round(float(candidate.get("v2_fatigue_gate_raw", 0.0)), 8),
            "v2_fatigue_gate_soft": round(float(candidate.get("v2_fatigue_gate_soft", 0.0)), 8),
            "v2_fatigue_gate": round(float(candidate.get("v2_fatigue_gate", 0.0)), 8),
            "v2_passes_threshold": bool(candidate.get("v2_passes_threshold", False)),
        }

    @staticmethod
    def _empty_candidate_audit() -> dict[str, Any]:
        return {
            "stitching_mode": "legacy_event",
            "mode_flags": {
                "legacy_event_active": True,
                "context_match_v2_active": False,
                "hybrid_compare_active": False,
                "context_concat_v2_enabled": True,
                "context_match_v2_audit_only": True,
                "execution_uses_legacy_score": True,
                "v2_score_exposed": True,
            },
            "raw_accepted_count": 0,
            "accepted_exact_context_identity_count": 0,
            "accepted_target_context_prefix_trimmed_count": 0,
            "deduped_candidate_count": 0,
            "rejected_count": 0,
            "stored_new_count": 0,
            "replacement_count": 0,
            "kept_existing_count": 0,
            "active_item_count": 0,
            "active_structure_count": 0,
            "seed_scan_count": 0,
            "seed_structure_scan_count": 0,
            "seed_scan_capped": False,
            "max_seed_items": 0,
            "exact_context_index_enabled": False,
            "exact_context_index_owner_count": 0,
            "exact_context_index_target_total": 0,
            "exact_context_index_max_bucket_size": 0,
            "exact_context_index_avg_bucket_size": 0.0,
            "context_concat_source_scan_count": 0,
            "context_concat_attention_seed_source_scan_count": 0,
            "context_concat_projected_support_source_scan_count": 0,
            "context_concat_exact_source_hit_count": 0,
            "context_concat_soft_scan_attempt_count": 0,
            "context_concat_soft_scan_allowed_count": 0,
            "context_concat_soft_scan_blocked_count": 0,
            "context_concat_exact_target_total": 0,
            "context_concat_soft_target_total": 0,
            "context_concat_candidate_target_total": 0,
            "context_concat_source_with_candidate_count": 0,
            "context_concat_candidate_pick_total": 0,
            "context_concat_target_cap_hit_count": 0,
            "context_concat_pick_cap_hit_count": 0,
            "rejected_reason_counts": {},
            "accepted_action_type_counts": {},
            "accepted_match_mode_counts": {},
            "rejected_action_type_counts": {},
            "rejected_match_mode_counts": {},
            "score_means": {
                "score": 0.0,
                "base_score": 0.0,
                "edge_weight_ratio": 0.0,
                "match_strength": 0.0,
                "context_ratio": 0.0,
                "energy_balance": 0.0,
                "runtime_balance": 0.0,
                "bridge_span_ratio": 0.0,
                "anchor_scale": 0.0,
                "fatigue_scale": 0.0,
                "threshold_margin": 0.0,
                "match_count_score": 0.0,
                "attribute_bonus_score": 0.0,
                "effective_match_units": 0.0,
                "attribute_bonus_equivalent_units": 0.0,
                "v2_score": 0.0,
                "v2_base_score_raw": 0.0,
                "v2_base_score": 0.0,
                "v2_base_score_soft": 0.0,
                "v2_threshold_margin": 0.0,
                "v2_context_cover_score": 0.0,
                "v2_context_cover_soft_score": 0.0,
                "v2_order_alignment_score": 0.0,
                "v2_order_alignment_soft_score": 0.0,
                "v2_tail_match_score": 0.0,
                "v2_tail_match_soft_score": 0.0,
                "v2_context_db_support_score": 0.0,
                "v2_context_db_support_soft_score": 0.0,
                "v2_energy_profile_score": 0.0,
                "v2_energy_profile_soft_score": 0.0,
                "v2_match_count_score": 0.0,
                "v2_match_count_soft_score": 0.0,
                "v2_attribute_bonus_score": 0.0,
                "v2_attribute_bonus_soft_score": 0.0,
                "v2_fatigue_gate_raw": 0.0,
                "v2_fatigue_gate_soft": 0.0,
                "v2_fatigue_gate": 0.0,
            },
            "rejection_preview": [],
            "competition_preview": [],
        }

    def _new_candidate_audit(self) -> dict[str, Any]:
        audit = self._empty_candidate_audit()
        audit["stitching_mode"] = self._stitching_mode()
        audit["mode_flags"] = self._stitching_mode_flags()
        audit["_score_sums"] = {key: 0.0 for key in audit["score_means"].keys()}
        return audit

    @staticmethod
    def _bump_counter(bucket: dict[str, int], key: str) -> None:
        name = str(key or "unknown")
        bucket[name] = int(bucket.get(name, 0) or 0) + 1

    @staticmethod
    def _append_preview(rows: list[dict], payload: dict[str, Any], *, limit: int = 8) -> None:
        if len(rows) >= limit:
            return
        rows.append(payload)

    def _audit_candidate_rejection(self, *, reason: str, payload: dict[str, Any]) -> None:
        audit = self._current_candidate_audit
        if not isinstance(audit, dict):
            return
        audit["rejected_count"] = int(audit.get("rejected_count", 0) or 0) + 1
        self._bump_counter(audit.setdefault("rejected_reason_counts", {}), str(reason or "unknown"))
        self._bump_counter(audit.setdefault("rejected_action_type_counts", {}), str(payload.get("action_type", "") or "unknown"))
        self._bump_counter(audit.setdefault("rejected_match_mode_counts", {}), str(payload.get("match_mode", "") or "unknown"))
        source = payload.get("source", {}) if isinstance(payload.get("source", {}), dict) else {}
        target = payload.get("target", {}) if isinstance(payload.get("target", {}), dict) else {}
        self._append_preview(
            audit.setdefault("rejection_preview", []),
            {
                "reason": str(reason or "unknown"),
                "action_type": str(payload.get("action_type", "") or ""),
                "match_mode": str(payload.get("match_mode", "") or ""),
                "source_display": str(source.get("display", "") or ""),
                "target_display": str(target.get("display", "") or ""),
                "score_source": str(payload.get("score_source", "legacy") or "legacy"),
                "execution_uses_v2_score": bool(payload.get("execution_uses_v2_score", False)),
                "score": round(float(payload.get("score", 0.0) or 0.0), 8),
                "legacy_score": round(float(payload.get("legacy_score", 0.0) or 0.0), 8),
                "base_score": round(float(payload.get("base_score", 0.0) or 0.0), 8),
                "legacy_base_score": round(float(payload.get("legacy_base_score", 0.0) or 0.0), 8),
                "min_candidate_score": round(float(payload.get("min_candidate_score", 0.0) or 0.0), 8),
                "legacy_min_candidate_score": round(float(payload.get("legacy_min_candidate_score", 0.0) or 0.0), 8),
                "threshold_margin": round(float(payload.get("threshold_margin", 0.0) or 0.0), 8),
                "legacy_threshold_margin": round(float(payload.get("legacy_threshold_margin", 0.0) or 0.0), 8),
                "edge_weight_ratio": round(float(payload.get("edge_weight_ratio", 0.0) or 0.0), 8),
                "match_strength": round(float(payload.get("match_strength", 0.0) or 0.0), 8),
                "context_ratio": round(float(payload.get("context_ratio", 0.0) or 0.0), 8),
                "energy_balance": round(float(payload.get("energy_balance", 0.0) or 0.0), 8),
                "runtime_balance": round(float(payload.get("runtime_balance", 0.0) or 0.0), 8),
                "bridge_span_ratio": round(float(payload.get("bridge_span_ratio", 0.0) or 0.0), 8),
                "anchor_scale": round(float(payload.get("anchor_scale", 0.0) or 0.0), 8),
                "fatigue_scale": round(float(payload.get("fatigue_scale", 0.0) or 0.0), 8),
                "match_count_score": round(float(payload.get("match_count_score", 0.0) or 0.0), 8),
                "attribute_bonus_score": round(float(payload.get("attribute_bonus_score", 0.0) or 0.0), 8),
                "effective_match_units": round(float(payload.get("effective_match_units", 0.0) or 0.0), 8),
                "attribute_bonus_equivalent_units": round(float(payload.get("attribute_bonus_equivalent_units", 0.0) or 0.0), 8),
                "v2_score": round(float(payload.get("v2_score", 0.0) or 0.0), 8),
                "v2_base_score_raw": round(float(payload.get("v2_base_score_raw", 0.0) or 0.0), 8),
                "v2_base_score": round(float(payload.get("v2_base_score", 0.0) or 0.0), 8),
                "v2_base_score_soft": round(float(payload.get("v2_base_score_soft", 0.0) or 0.0), 8),
                "v2_context_cover_score": round(float(payload.get("v2_context_cover_score", 0.0) or 0.0), 8),
                "v2_context_cover_soft_score": round(float(payload.get("v2_context_cover_soft_score", 0.0) or 0.0), 8),
                "v2_order_alignment_score": round(float(payload.get("v2_order_alignment_score", 0.0) or 0.0), 8),
                "v2_order_alignment_soft_score": round(float(payload.get("v2_order_alignment_soft_score", 0.0) or 0.0), 8),
                "v2_tail_match_score": round(float(payload.get("v2_tail_match_score", 0.0) or 0.0), 8),
                "v2_tail_match_soft_score": round(float(payload.get("v2_tail_match_soft_score", 0.0) or 0.0), 8),
                "v2_context_db_support_score": round(float(payload.get("v2_context_db_support_score", 0.0) or 0.0), 8),
                "v2_context_db_support_soft_score": round(float(payload.get("v2_context_db_support_soft_score", 0.0) or 0.0), 8),
                "v2_energy_profile_score": round(float(payload.get("v2_energy_profile_score", 0.0) or 0.0), 8),
                "v2_energy_profile_soft_score": round(float(payload.get("v2_energy_profile_soft_score", 0.0) or 0.0), 8),
                "v2_match_count_score": round(float(payload.get("v2_match_count_score", 0.0) or 0.0), 8),
                "v2_match_count_soft_score": round(float(payload.get("v2_match_count_soft_score", 0.0) or 0.0), 8),
                "v2_attribute_bonus_score": round(float(payload.get("v2_attribute_bonus_score", 0.0) or 0.0), 8),
                "v2_attribute_bonus_soft_score": round(float(payload.get("v2_attribute_bonus_soft_score", 0.0) or 0.0), 8),
                "v2_fatigue_gate_raw": round(float(payload.get("v2_fatigue_gate_raw", 0.0) or 0.0), 8),
                "v2_fatigue_gate_soft": round(float(payload.get("v2_fatigue_gate_soft", 0.0) or 0.0), 8),
                "v2_threshold_margin": round(float(payload.get("v2_threshold_margin", 0.0) or 0.0), 8),
                "new_component_count": int(payload.get("new_component_count", 0) or 0),
                "max_component_count": int(payload.get("max_component_count", 0) or 0),
            },
        )

    def _audit_candidate_accept(self, candidate: dict) -> None:
        audit = self._current_candidate_audit
        if not isinstance(audit, dict):
            return
        audit["raw_accepted_count"] = int(audit.get("raw_accepted_count", 0) or 0) + 1
        self._bump_counter(audit.setdefault("accepted_action_type_counts", {}), str(candidate.get("action_type", "") or "unknown"))
        self._bump_counter(audit.setdefault("accepted_match_mode_counts", {}), str(candidate.get("match_mode", "") or "unknown"))
        score_sums = audit.setdefault("_score_sums", {})
        for key in (
            "score",
            "base_score",
            "edge_weight_ratio",
            "match_strength",
            "context_ratio",
            "energy_balance",
            "runtime_balance",
            "bridge_span_ratio",
            "anchor_scale",
            "fatigue_scale",
            "threshold_margin",
            "match_count_score",
            "attribute_bonus_score",
            "effective_match_units",
            "attribute_bonus_equivalent_units",
            "v2_score",
            "v2_base_score_raw",
            "v2_base_score",
            "v2_base_score_soft",
            "v2_threshold_margin",
            "v2_context_cover_score",
            "v2_context_cover_soft_score",
            "v2_order_alignment_score",
            "v2_order_alignment_soft_score",
            "v2_tail_match_score",
            "v2_tail_match_soft_score",
            "v2_context_db_support_score",
            "v2_context_db_support_soft_score",
            "v2_energy_profile_score",
            "v2_energy_profile_soft_score",
            "v2_match_count_score",
            "v2_match_count_soft_score",
            "v2_attribute_bonus_score",
            "v2_attribute_bonus_soft_score",
            "v2_fatigue_gate_raw",
            "v2_fatigue_gate_soft",
            "v2_fatigue_gate",
        ):
            score_sums[key] = round(float(score_sums.get(key, 0.0) or 0.0) + float(candidate.get(key, 0.0) or 0.0), 8)
        if str(candidate.get("action_type", "") or "") == "concat_context_structure":
            if bool(candidate.get("exact_context_identity_match", False)):
                audit["accepted_exact_context_identity_count"] = int(audit.get("accepted_exact_context_identity_count", 0) or 0) + 1
            if bool(candidate.get("target_context_prefix_trimmed", False)):
                audit["accepted_target_context_prefix_trimmed_count"] = int(
                    audit.get("accepted_target_context_prefix_trimmed_count", 0) or 0
                ) + 1

    def _record_candidate_seed_scan(self, *, active_items: list[dict], seed_items: list[dict], max_seed_items: int) -> None:
        audit = self._current_candidate_audit
        if not isinstance(audit, dict):
            return
        audit["active_item_count"] = int(len(list(active_items or [])))
        audit["active_structure_count"] = int(
            sum(1 for item in list(active_items or []) if isinstance(item, dict) and item.get("kind") == "structure")
        )
        audit["seed_scan_count"] = int(len(list(seed_items or [])))
        audit["seed_structure_scan_count"] = int(
            sum(1 for item in list(seed_items or []) if isinstance(item, dict) and item.get("kind") == "structure")
        )
        audit["seed_scan_capped"] = bool(max_seed_items > 0 and len(list(active_items or [])) > len(list(seed_items or [])))
        audit["max_seed_items"] = int(max_seed_items)

    def _record_candidate_scan_index(self, *, active_items: list[dict], exact_context_index: dict[str, list[dict]]) -> None:
        audit = self._current_candidate_audit
        if not isinstance(audit, dict):
            return
        bucket_sizes = [len(list(values or [])) for values in (exact_context_index or {}).values()]
        audit["exact_context_index_owner_count"] = int(len(bucket_sizes))
        audit["exact_context_index_target_total"] = int(sum(bucket_sizes))
        audit["exact_context_index_max_bucket_size"] = int(max(bucket_sizes) if bucket_sizes else 0)
        audit["exact_context_index_avg_bucket_size"] = round(
            float(sum(bucket_sizes)) / float(max(1, len(bucket_sizes))),
            8,
        ) if bucket_sizes else 0.0
        audit["exact_context_index_enabled"] = True

    def _record_candidate_source_scan(
        self,
        *,
        source: dict,
        exact_target_count: int,
        soft_scan_attempted: bool,
        soft_scan_allowed: bool,
        soft_target_count: int,
        candidate_target_count: int,
        raw_max_targets: int,
    ) -> None:
        audit = self._current_candidate_audit
        if not isinstance(audit, dict):
            return
        audit["context_concat_source_scan_count"] = int(audit.get("context_concat_source_scan_count", 0) or 0) + 1
        if bool(source.get("attention_seed", False)):
            audit["context_concat_attention_seed_source_scan_count"] = int(
                audit.get("context_concat_attention_seed_source_scan_count", 0) or 0
            ) + 1
        if bool(source.get("projected_from_non_st_support", False)):
            audit["context_concat_projected_support_source_scan_count"] = int(
                audit.get("context_concat_projected_support_source_scan_count", 0) or 0
            ) + 1
        if int(exact_target_count) > 0:
            audit["context_concat_exact_source_hit_count"] = int(audit.get("context_concat_exact_source_hit_count", 0) or 0) + 1
        if bool(soft_scan_attempted):
            audit["context_concat_soft_scan_attempt_count"] = int(audit.get("context_concat_soft_scan_attempt_count", 0) or 0) + 1
        if bool(soft_scan_allowed):
            audit["context_concat_soft_scan_allowed_count"] = int(audit.get("context_concat_soft_scan_allowed_count", 0) or 0) + 1
        elif bool(soft_scan_attempted):
            audit["context_concat_soft_scan_blocked_count"] = int(audit.get("context_concat_soft_scan_blocked_count", 0) or 0) + 1
        if int(raw_max_targets) > 0 and int(candidate_target_count) >= int(raw_max_targets):
            audit["context_concat_target_cap_hit_count"] = int(audit.get("context_concat_target_cap_hit_count", 0) or 0) + 1
        audit["context_concat_exact_target_total"] = int(audit.get("context_concat_exact_target_total", 0) or 0) + max(
            0,
            int(exact_target_count),
        )
        audit["context_concat_soft_target_total"] = int(audit.get("context_concat_soft_target_total", 0) or 0) + max(
            0,
            int(soft_target_count),
        )
        audit["context_concat_candidate_target_total"] = int(
            audit.get("context_concat_candidate_target_total", 0) or 0
        ) + max(0, int(candidate_target_count))

    def _record_candidate_source_result(
        self,
        *,
        source: dict,
        picked_count: int,
        candidate_target_count: int,
        max_targets: int,
    ) -> None:
        audit = self._current_candidate_audit
        if not isinstance(audit, dict):
            return
        if int(picked_count) > 0:
            audit["context_concat_source_with_candidate_count"] = int(
                audit.get("context_concat_source_with_candidate_count", 0) or 0
            ) + 1
        audit["context_concat_candidate_pick_total"] = int(audit.get("context_concat_candidate_pick_total", 0) or 0) + max(
            0,
            int(picked_count),
        )
        if int(max_targets) > 0 and int(picked_count) >= int(max_targets) and int(candidate_target_count) > int(picked_count):
            audit["context_concat_pick_cap_hit_count"] = int(audit.get("context_concat_pick_cap_hit_count", 0) or 0) + 1

    def _audit_candidate_competition(self, *, existing: dict | None, candidate: dict, outcome: str) -> None:
        audit = self._current_candidate_audit
        if not isinstance(audit, dict):
            return
        outcome_key = str(outcome or "unknown")
        if outcome_key == "stored_new":
            audit["stored_new_count"] = int(audit.get("stored_new_count", 0) or 0) + 1
            return
        if outcome_key == "replaced_existing":
            audit["replacement_count"] = int(audit.get("replacement_count", 0) or 0) + 1
        elif outcome_key == "kept_existing":
            audit["kept_existing_count"] = int(audit.get("kept_existing_count", 0) or 0) + 1
        self._append_preview(
            audit.setdefault("competition_preview", []),
            {
                "outcome": outcome_key,
                "candidate_signature": str(candidate.get("candidate_signature", "") or ""),
                "action_type": str(candidate.get("action_type", "") or ""),
                "score_source": str(candidate.get("score_source", "legacy") or "legacy"),
                "incoming_score": round(float(candidate.get("score", 0.0) or 0.0), 8),
                "existing_score": round(float(existing.get("score", 0.0) or 0.0), 8) if isinstance(existing, dict) else 0.0,
                "incoming_legacy_score": round(float(candidate.get("legacy_score", 0.0) or 0.0), 8),
                "existing_legacy_score": round(float(existing.get("legacy_score", 0.0) or 0.0), 8) if isinstance(existing, dict) else 0.0,
                "incoming_source_display": str(candidate.get("source", {}).get("display", "") or ""),
                "incoming_target_display": str(candidate.get("target", {}).get("display", "") or ""),
                "existing_source_display": str(existing.get("source", {}).get("display", "") or "") if isinstance(existing, dict) else "",
                "existing_target_display": str(existing.get("target", {}).get("display", "") or "") if isinstance(existing, dict) else "",
                "match_mode": str(candidate.get("match_mode", "") or ""),
                "incoming_v2_score": round(float(candidate.get("v2_score", 0.0) or 0.0), 8),
                "existing_v2_score": round(float(existing.get("v2_score", 0.0) or 0.0), 8) if isinstance(existing, dict) else 0.0,
            },
        )

    def _finalize_candidate_audit(self, audit: dict[str, Any] | None, ranked_candidates: list[dict]) -> dict[str, Any]:
        if not isinstance(audit, dict):
            return self._empty_candidate_audit()
        result = {k: v for k, v in audit.items() if not str(k).startswith("_")}
        deduped_count = len(list(ranked_candidates or []))
        raw_accepted_count = int(result.get("raw_accepted_count", 0) or 0)
        result["deduped_candidate_count"] = int(deduped_count)
        result["deduped_pruned_count"] = max(0, raw_accepted_count - deduped_count)
        score_sums = audit.get("_score_sums", {}) if isinstance(audit.get("_score_sums", {}), dict) else {}
        score_means = {}
        for key in result.get("score_means", {}).keys():
            score_means[key] = round(float(score_sums.get(key, 0.0) or 0.0) / float(max(1, raw_accepted_count)), 8) if raw_accepted_count > 0 else 0.0
        result["score_means"] = score_means
        return result

    @staticmethod
    def _make_response(success: bool, code: str, message: str, data: dict, trace_id: str, tick_id: str, start_time: float) -> dict:
        return {
            "success": bool(success),
            "code": str(code),
            "message": str(message),
            "trace_id": trace_id,
            "tick_id": tick_id,
            "elapsed_ms": int((time.time() - start_time) * 1000),
            "data": data,
        }

    @staticmethod
    def _structure_display(structure_obj: dict) -> str:
        structure = structure_obj.get("structure", {}) if isinstance(structure_obj.get("structure", {}), dict) else {}
        for group in list(structure.get("sequence_groups", []) or []):
            if not isinstance(group, dict):
                continue
            if bool(group.get("order_sensitive", False)) and str(group.get("string_unit_kind", "") or "") == "char_sequence":
                text = str(group.get("string_token_text", "") or "").strip()
                group_tokens = [str(token) for token in (group.get("tokens", []) or []) if str(token)]
                if text and group_tokens and "".join(group_tokens) == text:
                    return text
        flat_tokens = [str(token) for token in (structure.get("flat_tokens", []) or []) if str(token)]
        if flat_tokens:
            return "".join(flat_tokens)
        return str(structure.get("display_text", "") or structure_obj.get("id", ""))

    @staticmethod
    def _runtime_weight(*, hdb, structure_obj: dict) -> float:
        stats = dict(structure_obj.get("stats", {}) or {})
        try:
            weight_engine = getattr(hdb, "_weight", None)
            if weight_engine is not None and hasattr(weight_engine, "compute_runtime_weight"):
                return round(
                    float(
                        weight_engine.compute_runtime_weight(
                            base_weight=float(stats.get("base_weight", 1.0) or 1.0),
                            recent_gain=float(stats.get("recent_gain", 1.0) or 1.0),
                            fatigue=float(stats.get("fatigue", 0.0) or 0.0),
                        )
                    ),
                    8,
                )
        except Exception:
            pass
        base_weight = max(0.01, float(stats.get("base_weight", 1.0) or 1.0))
        recent_gain = max(1.0, float(stats.get("recent_gain", 1.0) or 1.0))
        fatigue = max(0.0, float(stats.get("fatigue", 0.0) or 0.0))
        return round(base_weight * recent_gain / (1.0 + fatigue), 8)

    @staticmethod
    def _energy_balance_ratio(a: float, b: float) -> float:
        x = max(0.0, float(a))
        y = max(0.0, float(b))
        if x <= 0.0 and y <= 0.0:
            return 0.0
        return round(min(x, y) / max(x, y, 1e-9), 8)

    @staticmethod
    def _get_structure(*, hdb, structure_id: str) -> dict | None:
        structure_store = getattr(hdb, "_structure_store", None)
        if structure_store is None or not structure_id:
            return None
        structure = structure_store.get(structure_id)
        return structure if isinstance(structure, dict) else None

    @staticmethod
    def _common_prefix_length(a_tokens: list[str], b_tokens: list[str]) -> int:
        limit = min(len(a_tokens), len(b_tokens))
        count = 0
        for index in range(limit):
            if a_tokens[index] != b_tokens[index]:
                break
            count += 1
        return count

    @staticmethod
    def _contiguous_subsequence_ratio(target_tokens: list[str], candidate_tokens: list[str]) -> float:
        if not target_tokens or not candidate_tokens or len(target_tokens) > len(candidate_tokens):
            return 0.0
        target = list(target_tokens)
        candidate = list(candidate_tokens)
        width = len(target)
        for start in range(0, len(candidate) - width + 1):
            if candidate[start : start + width] == target:
                return round(len(target) / max(1, len(candidate)), 8)
        return 0.0

    @staticmethod
    def _lcs_length(a_tokens: list[str], b_tokens: list[str]) -> int:
        if not a_tokens or not b_tokens:
            return 0
        rows = len(a_tokens) + 1
        cols = len(b_tokens) + 1
        dp = [[0] * cols for _ in range(rows)]
        for i in range(1, rows):
            for j in range(1, cols):
                if a_tokens[i - 1] == b_tokens[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1] + 1
                else:
                    dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
        return int(dp[-1][-1])

    @classmethod
    def _lcs_ratio(cls, a_tokens: list[str], b_tokens: list[str]) -> float:
        lcs_len = cls._lcs_length(a_tokens, b_tokens)
        if lcs_len <= 0:
            return 0.0
        return round(float(lcs_len) / max(1, len(a_tokens)), 8)

    @staticmethod
    def _empty_report(*, enabled: bool, reason: str) -> dict[str, Any]:
        return {
            "enabled": bool(enabled),
            "stage": "phase2_contextual_event_stitching",
            "stitching_mode": "legacy_event",
            "mode_flags": {
                "legacy_event_active": True,
                "context_match_v2_active": False,
                "hybrid_compare_active": False,
                "context_match_v2_audit_only": True,
                "execution_uses_legacy_score": True,
                "v2_score_exposed": True,
            },
            "reason": str(reason),
            "seed_structure_count": 0,
            "seed_plain_structure_count": 0,
            "seed_event_count": 0,
            "candidate_count": 0,
            "action_count": 0,
            "concat_count": 0,
            "created_count": 0,
            "extended_count": 0,
            "merged_count": 0,
            "reinforced_count": 0,
            "pair_fatigue_state_size": 0,
            "object_stitch_fatigue_state_size": 0,
            "candidate_audit": CognitiveStitchingEngine._empty_candidate_audit(),
            "apply_audit": CognitiveStitchingEngine._empty_apply_audit(),
            "candidate_preview": [],
            "actions": [],
            "action_log": [],
            "event_grasp": {
                "enabled": False,
                "reason": "not_run",
                "signals": [],
                "attribute_bindings": [],
                "selected_event_count": 0,
                "emitted_count": 0,
                "success": False,
                "code": "",
                "message": "",
                "elapsed_ms": 0,
            },
            "narrative_top_items": [],
        }
