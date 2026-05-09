# -*- coding: utf-8 -*-
"""
Induction propagation engine for HDB.
"""

from __future__ import annotations

import time
from collections import Counter

from ._context_metadata import extract_context_metadata, has_context_metadata, normalize_id_list
from ._owner_runtime_budget import build_owner_runtime_candidate_view
from ._runtime_projection_policy import classify_runtime_projection_block_reason
from ._structure_resolver import (
    find_exact_structure_by_signature as shared_find_exact_structure_by_signature,
    resolve_or_create_structure_from_profile as shared_resolve_or_create_structure_from_profile,
)


class InductionEngine:
    def __init__(self, config: dict, weight_engine, logger, maintenance_engine):
        self._config = config
        self._weight = weight_engine
        self._logger = logger
        self._maintenance = maintenance_engine
        self._runtime_cache: dict | None = None
        self._current_structure_store = None

    def update_config(self, config: dict) -> None:
        self._config = config

    def clear_runtime_state(self) -> dict:
        had_runtime_cache = bool(self._runtime_cache)
        had_structure_store = self._current_structure_store is not None
        self._runtime_cache = None
        self._current_structure_store = None
        return {
            "had_runtime_cache": had_runtime_cache,
            "had_structure_store_binding": had_structure_store,
        }

    def _build_structure_profile_cached(self, *, structure_obj: dict, cut_engine) -> dict:
        if not isinstance(structure_obj, dict):
            return {}
        structure_id = str(structure_obj.get("id", "") or "")
        content_signature = str(structure_obj.get("structure", {}).get("content_signature", "") or "")
        updated_at = int(structure_obj.get("updated_at", 0) or 0)
        cache = None
        if isinstance(self._runtime_cache, dict):
            cache = self._runtime_cache.setdefault("structure_profiles", {})
        cache_key = (structure_id, content_signature, updated_at)
        if isinstance(cache, dict) and structure_id and cache_key in cache:
            return cache[cache_key]
        structure_store = self._current_structure_store
        shared_cache_key = ("structure_profiles",) + cache_key
        shared_cached = None
        if structure_store is not None and hasattr(structure_store, "get_shared_runtime_cache_entry"):
            shared_cached = structure_store.get_shared_runtime_cache_entry(
                "structure_profiles",
                shared_cache_key,
            )
        if isinstance(shared_cached, dict):
            if isinstance(cache, dict) and structure_id:
                cache[cache_key] = shared_cached
            return shared_cached
        profile = cut_engine.build_sequence_profile_from_structure(structure_obj)
        if isinstance(cache, dict) and structure_id:
            cache[cache_key] = profile
        if structure_store is not None and hasattr(structure_store, "set_shared_runtime_cache_entry"):
            structure_store.set_shared_runtime_cache_entry(
                "structure_profiles",
                shared_cache_key,
                profile,
            )
        return profile

    def _resolve_entry_profile_cached(self, *, entry: dict, cut_engine, structure_store) -> dict:
        entry_id = str(entry.get("entry_id", "") or "")
        cache = None
        if isinstance(self._runtime_cache, dict):
            cache = self._runtime_cache.setdefault("entry_profiles", {})
        entry_updated_at = int(entry.get("last_updated_at", entry.get("last_matched_at", 0)) or 0)
        canonical_signature = str(entry.get("canonical_content_signature", "") or entry.get("content_signature", "") or "")
        entry_type = str(entry.get("entry_type", "structure_ref") or "structure_ref")
        cache_key = (
            entry_id,
            entry_updated_at,
            canonical_signature,
            entry_type,
        )
        if isinstance(cache, dict) and entry_id and cache_key in cache:
            return cache[cache_key]
        shared_cache_key = ("entry_profiles",) + cache_key
        shared_cached = None
        if hasattr(structure_store, "get_shared_runtime_cache_entry"):
            shared_cached = structure_store.get_shared_runtime_cache_entry(
                "induction_entry_profiles",
                shared_cache_key,
            )
        if isinstance(shared_cached, dict):
            if isinstance(cache, dict) and entry_id:
                cache[cache_key] = shared_cached
            return shared_cached
        profile = self._resolve_entry_profile(
            entry=entry,
            cut_engine=cut_engine,
            structure_store=structure_store,
        )
        if isinstance(cache, dict) and entry_id:
            cache[cache_key] = profile
        if hasattr(structure_store, "set_shared_runtime_cache_entry"):
            structure_store.set_shared_runtime_cache_entry(
                "induction_entry_profiles",
                shared_cache_key,
                profile,
            )
        return profile

    def run(
        self,
        *,
        state_snapshot: dict,
        trace_id: str,
        tick_id: str,
        structure_store,
        episodic_store,
        pointer_index,
        cut_engine,
        max_source_items: int | None,
        enable_ev_propagation: bool,
        enable_er_induction: bool,
    ) -> dict:
        self._current_structure_store = structure_store
        self._runtime_cache = {
            "structure_profiles": {},
            "entry_profiles": {},
            "runtime_source_profiles": {},
            "runtime_source_data_templates": {},
            "metrics": {},
        }
        top_items = list(state_snapshot.get("top_items") or state_snapshot.get("items") or [])
        try:
            ev_threshold = float(self._config.get("ev_propagation_threshold", 0.12) or 0.12)
        except Exception:
            ev_threshold = 0.12
        try:
            er_threshold = float(self._config.get("er_induction_threshold", 0.15) or 0.15)
        except Exception:
            er_threshold = 0.15
        if bool(self._config.get("induction_source_effective_energy_prefilter_enabled", True)):
            source_items = [
                item for item in top_items
                if self._runtime_source_has_effective_energy(
                    item,
                    enable_ev_propagation=enable_ev_propagation,
                    enable_er_induction=enable_er_induction,
                    ev_threshold=ev_threshold,
                    er_threshold=er_threshold,
                )
            ]
        else:
            source_items = [item for item in top_items if self._runtime_source_has_positive_energy(item)]
        runtime_only_residual_skipped_count = 0
        filtered_source_items = []
        for item in source_items:
            if self._runtime_source_is_runtime_only_residual(item):
                runtime_only_residual_skipped_count += 1
                continue
            filtered_source_items.append(item)
        source_items = filtered_source_items
        if max_source_items is not None and int(max_source_items) > 0:
            source_items = source_items[: int(max_source_items)]

        now_ms = int(time.time() * 1000)
        source_item_count = 0
        propagated_target_count = 0
        induced_target_count = 0
        total_delta_ev = 0.0
        total_ev_consumed = 0.0
        propagated_budget_total_ev = 0.0
        updated_weight_count = 0
        fallback_used = False
        induction_targets: dict[tuple[str, str, str], dict] = {}
        source_details = []
        source_ev_consumptions = []
        raw_residual_entry_count = 0
        raw_residual_entry_with_existing_structure_count = 0
        raw_residual_entry_routed_to_structure_count = 0
        raw_residual_existing_structure_target_count = 0
        raw_residual_entry_materialized_structure_count = 0
        raw_residual_materialized_structure_target_count = 0
        raw_residual_entry_with_component_structure_count = 0
        raw_residual_entry_routed_to_component_structure_count = 0
        raw_residual_component_structure_target_count = 0
        raw_residual_structure_budget_weight = 0.0
        raw_residual_exact_structure_budget_weight = 0.0
        raw_residual_materialized_structure_budget_weight = 0.0
        raw_residual_component_structure_budget_weight = 0.0
        raw_residual_hit_memory_budget_weight = 0.0
        raw_residual_miss_memory_budget_weight = 0.0
        entry_pruned_by_base_weight_count = 0
        shared_structure_source_cache: dict[str, dict] = {}
        structure_db_update_request_count = 0
        structure_db_update_applied_count = 0
        source_pruned_by_base_weight_count = 0
        try:
            min_source_base_weight = max(0.0, float(self._config.get("induction_min_source_base_weight", 0.0) or 0.0))
        except Exception:
            min_source_base_weight = 0.0

        # Ratios / 比例系数（对齐配置语义）
        # --------------------------------
        # 注意：这两个系数在理论与配置文档中明确存在：
        # - ev_propagation_ratio: source EV propagation budget.
        # - er_induction_ratio: source ER -> induced EV budget.
        #
        # Growth-era baseline is 1.0: the first predictive layer starts from
        # a full 1:1 budget, while branching, pruning, fatigue and modulation
        # shape how much survives into visible runtime objects.
        try:
            ev_ratio = float(self._config.get("ev_propagation_ratio", 1.0) or 0.0)
        except Exception:
            ev_ratio = 1.0
        ev_ratio = max(0.0, min(1.0, float(ev_ratio)))

        try:
            er_ratio = float(self._config.get("er_induction_ratio", 1.0) or 0.0)
        except Exception:
            er_ratio = 1.0
        er_ratio = max(0.0, min(1.0, float(er_ratio)))

        energy_graph_v2 = self._resolve_energy_graph_v2_settings(ev_ratio=ev_ratio, er_ratio=er_ratio)
        energy_graph_v2_enabled = bool(energy_graph_v2.get("enabled", False))
        energy_graph_round_count_max = 0
        energy_graph_depth_max = 0
        energy_graph_frontier_generated_count = 0
        energy_graph_frontier_pruned_count = 0
        energy_graph_terminal_memory_count = 0
        energy_graph_root_reinduction_count = 0
        energy_graph_layer_histogram: dict[int, int] = {}
        energy_graph_round_summaries_acc: dict[int, dict] = {}

        for item in source_items:
            source_er = round(max(0.0, float(item.get("er", 0.0))), 8)
            source_ev = round(max(0.0, float(item.get("ev", 0.0))), 8)
            runtime_source = self._resolve_runtime_source_data(
                source_item=item,
                structure_store=structure_store,
                episodic_store=episodic_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
                now_ms=now_ms,
                trace_id=trace_id,
                tick_id=tick_id,
                structure_source_cache=shared_structure_source_cache,
            )
            source_item_count += 1
            fallback_used = fallback_used or bool(runtime_source.get("fallback_used", False))
            source_root_id = str(
                runtime_source.get("source_root_id", "")
                or item.get("ref_object_id", "")
                or item.get("item_id", item.get("id", ""))
            )
            source_display_text = str(
                runtime_source.get("source_display_text", "")
                or item.get("display_text", "")
                or item.get("display", "")
                or source_root_id
            )
            source_profile = runtime_source.get("source_profile", {}) if isinstance(runtime_source.get("source_profile", {}), dict) else {}
            aggregated_targets = dict(runtime_source.get("aggregated_targets", {}) or {})
            induction_candidates = dict(runtime_source.get("induction_candidates", {}) or {})
            aggregate_debug = dict(runtime_source.get("aggregate_debug", {}) or {})
            source_structure_obj = runtime_source.get("source_structure_obj")
            source_base_weight = 0.0
            if isinstance(source_structure_obj, dict):
                try:
                    source_base_weight = max(
                        0.0,
                        float((source_structure_obj.get("stats", {}) or {}).get("base_weight", 0.0) or 0.0),
                    )
                except Exception:
                    source_base_weight = 0.0
            raw_residual_entry_count += int(aggregate_debug.get("raw_residual_entry_count", 0))
            raw_residual_entry_with_existing_structure_count += int(
                aggregate_debug.get("raw_residual_entry_with_existing_structure_count", 0)
            )
            raw_residual_entry_routed_to_structure_count += int(
                aggregate_debug.get("raw_residual_entry_routed_to_structure_count", 0)
            )
            raw_residual_existing_structure_target_count += int(
                aggregate_debug.get("raw_residual_existing_structure_target_count", 0)
            )
            raw_residual_entry_materialized_structure_count += int(
                aggregate_debug.get("raw_residual_entry_materialized_structure_count", 0)
            )
            raw_residual_materialized_structure_target_count += int(
                aggregate_debug.get("raw_residual_materialized_structure_target_count", 0)
            )
            raw_residual_entry_with_component_structure_count += int(
                aggregate_debug.get("raw_residual_entry_with_component_structure_count", 0)
            )
            raw_residual_entry_routed_to_component_structure_count += int(
                aggregate_debug.get("raw_residual_entry_routed_to_component_structure_count", 0)
            )
            raw_residual_component_structure_target_count += int(
                aggregate_debug.get("raw_residual_component_structure_target_count", 0)
            )
            raw_residual_structure_budget_weight += float(
                aggregate_debug.get("raw_residual_structure_budget_weight", 0.0)
            )
            raw_residual_exact_structure_budget_weight += float(
                aggregate_debug.get("raw_residual_exact_structure_budget_weight", 0.0)
            )
            raw_residual_materialized_structure_budget_weight += float(
                aggregate_debug.get("raw_residual_materialized_structure_budget_weight", 0.0)
            )
            raw_residual_component_structure_budget_weight += float(
                aggregate_debug.get("raw_residual_component_structure_budget_weight", 0.0)
            )
            raw_residual_hit_memory_budget_weight += float(
                aggregate_debug.get("raw_residual_hit_memory_budget_weight", 0.0)
            )
            raw_residual_miss_memory_budget_weight += float(
                aggregate_debug.get("raw_residual_miss_memory_budget_weight", 0.0)
            )
            entry_pruned_by_base_weight_count += int(
                aggregate_debug.get("entry_pruned_by_base_weight_count", 0) or 0
            )

            source_detail = {
                "source_structure_id": source_root_id,
                "source_item_id": str(item.get("item_id", item.get("id", "")) or ""),
                "source_ref_object_type": str(item.get("ref_object_type", "") or ""),
                "display_text": source_display_text,
                "source_er": source_er,
                "source_ev": source_ev,
                "pointer_info": dict(runtime_source.get("pointer_info", {}) or {}),
                "pointer_infos": list(runtime_source.get("pointer_infos", []) or []),
                "support_structure_ids": list(runtime_source.get("support_structure_ids", []) or []),
                "resolved_support_structure_ids": list(runtime_source.get("resolved_support_structure_ids", []) or []),
                "source_profile_signature": str(source_profile.get("content_signature", "") or ""),
                "source_profile_unit_count": int(source_profile.get("unit_count", 0) or 0),
                "source_profile_token_count": int(source_profile.get("token_count", 0) or 0),
                "source_base_weight": round(float(source_base_weight), 8),
                "aggregate_debug": aggregate_debug,
                "candidate_entries": [],
            }
            skipped_reason = str(runtime_source.get("skipped_reason", "") or "")
            if skipped_reason:
                source_detail["skipped_reason"] = skipped_reason

            if not source_profile:
                source_details.append(source_detail)
                continue
            if min_source_base_weight > 0.0 and isinstance(source_structure_obj, dict) and source_base_weight < min_source_base_weight:
                source_pruned_by_base_weight_count += 1
                source_detail["skipped_reason"] = "source_base_weight_below_threshold"
                source_detail["min_source_base_weight"] = round(float(min_source_base_weight), 8)
                source_details.append(source_detail)
                continue

            if energy_graph_v2_enabled and aggregated_targets:
                source_graph = self._run_source_energy_graph_v2(
                    source_item=item,
                    source_structure_id=source_root_id,
                    source_structure_obj=runtime_source.get("source_structure_obj"),
                    source_display_text=source_display_text,
                    source_er=source_er,
                    source_ev=source_ev,
                    enable_ev_propagation=enable_ev_propagation,
                    enable_er_induction=enable_er_induction,
                    source_profile=source_profile,
                    structure_db=runtime_source.get("source_structure_db"),
                    pointer_info=dict(runtime_source.get("pointer_info", {}) or {}),
                    aggregated_targets=aggregated_targets,
                    induction_candidates=induction_candidates,
                    structure_store=structure_store,
                    episodic_store=episodic_store,
                    pointer_index=pointer_index,
                    cut_engine=cut_engine,
                    now_ms=now_ms,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    induction_targets=induction_targets,
                    energy_graph_v2=energy_graph_v2,
                    shared_source_data_cache=shared_structure_source_cache,
                )
                propagated_target_count += int(source_graph.get("propagated_target_count", 0))
                induced_target_count += int(source_graph.get("induced_target_count", 0))
                total_delta_ev += float(source_graph.get("total_delta_ev", 0.0))
                total_ev_consumed += float(source_graph.get("total_ev_consumed", 0.0))
                propagated_budget_total_ev += float(source_graph.get("propagated_budget_total_ev", 0.0))
                updated_weight_count += int(source_graph.get("updated_weight_count", 0))
                source_ev_consumptions.extend(list(source_graph.get("source_ev_consumptions", []) or []))
                graph_summary = source_graph.get("energy_graph_summary", {}) if isinstance(source_graph.get("energy_graph_summary", {}), dict) else {}
                energy_graph_round_count_max = max(
                    int(energy_graph_round_count_max),
                    int(graph_summary.get("round_count", 0) or 0),
                )
                energy_graph_depth_max = max(
                    int(energy_graph_depth_max),
                    int(graph_summary.get("depth_max", 0) or 0),
                )
                energy_graph_frontier_generated_count += int(graph_summary.get("frontier_generated_count", 0) or 0)
                energy_graph_frontier_pruned_count += int(graph_summary.get("frontier_pruned_count", 0) or 0)
                energy_graph_terminal_memory_count += int(graph_summary.get("terminal_memory_count", 0) or 0)
                energy_graph_root_reinduction_count += int(graph_summary.get("root_reinduction_count", 0) or 0)
                for raw_depth, raw_count in (graph_summary.get("layer_histogram", {}) or {}).items():
                    try:
                        depth_key = int(raw_depth)
                    except Exception:
                        continue
                    energy_graph_layer_histogram[depth_key] = int(energy_graph_layer_histogram.get(depth_key, 0) or 0) + int(raw_count or 0)
                for row in list(source_graph.get("round_summaries", []) or []):
                    if not isinstance(row, dict):
                        continue
                    try:
                        round_index = int(row.get("round_index", 0) or 0)
                    except Exception:
                        round_index = 0
                    if round_index <= 0:
                        continue
                    bucket = energy_graph_round_summaries_acc.setdefault(
                        round_index,
                        {
                            "round_index": round_index,
                            "frontier_in_count": 0,
                            "frontier_out_count": 0,
                            "frontier_pruned_count": 0,
                            "frontier_memory_terminal_count": 0,
                            "root_reinduction_count": 0,
                            "frontier_budget_ev": 0.0,
                            "root_induction_budget_ev": 0.0,
                            "round_delta_ev": 0.0,
                        },
                    )
                    bucket["frontier_in_count"] += int(row.get("frontier_in_count", 0) or 0)
                    bucket["frontier_out_count"] += int(row.get("frontier_out_count", 0) or 0)
                    bucket["frontier_pruned_count"] += int(row.get("frontier_pruned_count", 0) or 0)
                    bucket["frontier_memory_terminal_count"] += int(row.get("frontier_memory_terminal_count", 0) or 0)
                    bucket["root_reinduction_count"] += int(row.get("root_reinduction_count", 0) or 0)
                    bucket["frontier_budget_ev"] = round(float(bucket.get("frontier_budget_ev", 0.0)) + float(row.get("frontier_budget_ev", 0.0) or 0.0), 8)
                    bucket["root_induction_budget_ev"] = round(float(bucket.get("root_induction_budget_ev", 0.0)) + float(row.get("root_induction_budget_ev", 0.0) or 0.0), 8)
                    bucket["round_delta_ev"] = round(float(bucket.get("round_delta_ev", 0.0)) + float(row.get("round_delta_ev", 0.0) or 0.0), 8)
                source_detail.update(
                    {
                        "energy_graph_v2_enabled": True,
                        "energy_graph_summary": graph_summary,
                        "energy_graph_rounds": list(source_graph.get("round_summaries", []) or []),
                        "candidate_entries": list(source_graph.get("candidate_entries", []) or []),
                    }
                )
                for structure_db in list((runtime_source.get("structure_dbs", {}) or {}).values()):
                    if not isinstance(structure_db, dict):
                        continue
                    self._maintenance.apply_structure_db_soft_limits(structure_db)
                    structure_db_update_request_count += 1
                    structure_store.update_db(structure_db)
                    structure_db_update_applied_count += 1
                source_details.append(source_detail)
                continue

            if enable_ev_propagation and source_ev >= ev_threshold:
                total_weight = sum(float(target.get("runtime_weight", 0.0)) for target in aggregated_targets.values())
                if total_weight > 0.0:
                    # Consume only a fraction of source EV, as configured.
                    # 只消耗/传播源 EV 的一部分（ev_propagation_ratio）
                    consumed_ev = round(source_ev * ev_ratio, 8)
                    if consumed_ev <= 0.0:
                        consumed_ev = 0.0
                    total_ev_consumed += consumed_ev
                    source_ev_consumptions.append(
                        {
                            "source_structure_id": source_root_id,
                            "source_item_id": item.get("item_id", item.get("id", "")),
                            "consumed_ev": consumed_ev,
                        }
                    )
                    for target in aggregated_targets.values():
                        if (
                            str(target.get("projection_kind", "structure") or "structure") == "structure"
                            and str(target.get("target_id", "") or "").strip() == str(source_root_id)
                        ):
                            continue
                        target_runtime_weight = float(target.get("runtime_weight", 0.0))
                        delta_ev = round(consumed_ev * (target_runtime_weight / total_weight), 8)
                        if delta_ev <= 0.0:
                            continue
                        target_debug = self._build_target_debug_entry(
                            target=target,
                            total_weight=total_weight,
                            delta_ev=delta_ev,
                        )
                        self._mark_bucket_entries(
                            entry_items=target.get("entries", []),
                            total_weight=total_weight,
                            delta_er=0.0,
                            delta_ev=consumed_ev,
                            now_ms=now_ms,
                        )
                        updated_weight_count += len(target.get("entries", []))
                        total_delta_ev += delta_ev
                        propagated_target_count += 1
                        target_runtime_total = max(1e-8, target_runtime_weight)
                        raw_residual_memory_delta_ev = round(
                            delta_ev * (float(target.get("raw_residual_memory_runtime_weight", 0.0)) / target_runtime_total),
                            8,
                        )
                        raw_residual_hit_memory_delta_ev = round(
                            delta_ev * (float(target.get("raw_residual_hit_memory_runtime_weight", 0.0)) / target_runtime_total),
                            8,
                        )
                        raw_residual_miss_memory_delta_ev = round(
                            delta_ev * (float(target.get("raw_residual_miss_memory_runtime_weight", 0.0)) / target_runtime_total),
                            8,
                        )
                        raw_residual_structure_delta_ev = round(
                            delta_ev * (float(target.get("raw_residual_structure_runtime_weight", 0.0)) / target_runtime_total),
                            8,
                        )
                        raw_residual_exact_structure_delta_ev = round(
                            delta_ev * (float(target.get("raw_residual_exact_structure_runtime_weight", 0.0)) / target_runtime_total),
                            8,
                        )
                        raw_residual_component_structure_delta_ev = round(
                            delta_ev * (float(target.get("raw_residual_component_structure_runtime_weight", 0.0)) / target_runtime_total),
                            8,
                        )
                        self._append_target_delta(
                            induction_targets=induction_targets,
                            projection_kind=target.get("projection_kind", "structure"),
                            memory_id=target.get("memory_id", ""),
                            target_id=target.get("target_id", ""),
                            backing_structure_id=target.get("backing_structure_id", ""),
                            target_display_text=target.get("display_text", target.get("target_id", "")),
                            mode="ev_propagation",
                            source_structure_id=source_root_id,
                            delta_ev=delta_ev,
                            runtime_weight=target_runtime_weight,
                            raw_residual_memory_delta_ev=raw_residual_memory_delta_ev,
                            raw_residual_hit_memory_delta_ev=raw_residual_hit_memory_delta_ev,
                            raw_residual_miss_memory_delta_ev=raw_residual_miss_memory_delta_ev,
                            raw_residual_structure_delta_ev=raw_residual_structure_delta_ev,
                            raw_residual_exact_structure_delta_ev=raw_residual_exact_structure_delta_ev,
                            raw_residual_component_structure_delta_ev=raw_residual_component_structure_delta_ev,
                            raw_residual_memory_refs=list(target.get("raw_residual_memory_refs", []) or []),
                            source_em_id=str(target.get("source_em_id", "") or ""),
                        )
                        source_detail["candidate_entries"].append(
                            {
                                "projection_kind": target.get("projection_kind", "structure"),
                                "memory_id": target.get("memory_id", ""),
                                "target_structure_id": target.get("target_id", ""),
                                "backing_structure_id": target.get("backing_structure_id", ""),
                                "target_display_text": target.get("display_text", target.get("target_id", "")),
                                "target_profile": target.get("target_profile", {}),
                                "relation_type": target.get("relation_type", ""),
                                "owner_structure_id": target.get("owner_structure_id", ""),
                                "mode": "ev_propagation",
                                "direct_source_structure_id": source_root_id,
                                "growth_source_structure_id": source_root_id,
                                **target_debug,
                            }
                        )

            if enable_er_induction and source_er >= er_threshold:
                total_weight = sum(float(target.get("runtime_weight", 0.0)) for target in induction_candidates.values())
                if total_weight > 0.0:
                    # Induction budget: only use a fraction of source ER to generate EV.
                    # 诱发预算：只使用源 ER 的一部分作为“诱发 EV”的预算（er_induction_ratio）
                    induction_budget = round(source_er * er_ratio, 8)
                    if induction_budget <= 0.0:
                        induction_budget = 0.0
                    for target in induction_candidates.values():
                        if (
                            str(target.get("projection_kind", "structure") or "structure") == "structure"
                            and str(target.get("target_id", "") or "").strip() == str(source_root_id)
                        ):
                            continue
                        target_runtime_weight = float(target.get("runtime_weight", 0.0))
                        delta_ev = round(induction_budget * (target_runtime_weight / total_weight), 8)
                        if delta_ev <= 0.0:
                            continue
                        target_debug = self._build_target_debug_entry(
                            target=target,
                            total_weight=total_weight,
                            delta_ev=delta_ev,
                        )
                        self._mark_bucket_entries(
                            entry_items=target.get("entries", []),
                            total_weight=total_weight,
                            delta_er=induction_budget,
                            delta_ev=induction_budget,
                            now_ms=now_ms,
                        )
                        updated_weight_count += len(target.get("entries", []))
                        total_delta_ev += delta_ev
                        induced_target_count += 1
                        target_runtime_total = max(1e-8, target_runtime_weight)
                        raw_residual_memory_delta_ev = round(
                            delta_ev * (float(target.get("raw_residual_memory_runtime_weight", 0.0)) / target_runtime_total),
                            8,
                        )
                        raw_residual_hit_memory_delta_ev = round(
                            delta_ev * (float(target.get("raw_residual_hit_memory_runtime_weight", 0.0)) / target_runtime_total),
                            8,
                        )
                        raw_residual_miss_memory_delta_ev = round(
                            delta_ev * (float(target.get("raw_residual_miss_memory_runtime_weight", 0.0)) / target_runtime_total),
                            8,
                        )
                        raw_residual_structure_delta_ev = round(
                            delta_ev * (float(target.get("raw_residual_structure_runtime_weight", 0.0)) / target_runtime_total),
                            8,
                        )
                        raw_residual_exact_structure_delta_ev = round(
                            delta_ev * (float(target.get("raw_residual_exact_structure_runtime_weight", 0.0)) / target_runtime_total),
                            8,
                        )
                        raw_residual_component_structure_delta_ev = round(
                            delta_ev * (float(target.get("raw_residual_component_structure_runtime_weight", 0.0)) / target_runtime_total),
                            8,
                        )
                        self._append_target_delta(
                            induction_targets=induction_targets,
                            projection_kind=target.get("projection_kind", "structure"),
                            memory_id=target.get("memory_id", ""),
                            target_id=target.get("target_id", ""),
                            backing_structure_id=target.get("backing_structure_id", ""),
                            target_display_text=target.get("display_text", target.get("target_id", "")),
                            mode="er_induction",
                            source_structure_id=source_root_id,
                            delta_ev=delta_ev,
                            runtime_weight=target_runtime_weight,
                            raw_residual_memory_delta_ev=raw_residual_memory_delta_ev,
                            raw_residual_hit_memory_delta_ev=raw_residual_hit_memory_delta_ev,
                            raw_residual_miss_memory_delta_ev=raw_residual_miss_memory_delta_ev,
                            raw_residual_structure_delta_ev=raw_residual_structure_delta_ev,
                            raw_residual_exact_structure_delta_ev=raw_residual_exact_structure_delta_ev,
                            raw_residual_component_structure_delta_ev=raw_residual_component_structure_delta_ev,
                            raw_residual_memory_refs=list(target.get("raw_residual_memory_refs", []) or []),
                            source_em_id=str(target.get("source_em_id", "") or ""),
                        )
                        source_detail["candidate_entries"].append(
                            {
                                "projection_kind": target.get("projection_kind", "structure"),
                                "memory_id": target.get("memory_id", ""),
                                "target_structure_id": target.get("target_id", ""),
                                "backing_structure_id": target.get("backing_structure_id", ""),
                                "target_display_text": target.get("display_text", target.get("target_id", "")),
                                "target_profile": target.get("target_profile", {}),
                                "relation_type": target.get("relation_type", ""),
                                "owner_structure_id": target.get("owner_structure_id", ""),
                                "mode": "er_induction",
                                "direct_source_structure_id": source_root_id,
                                "growth_source_structure_id": source_root_id,
                                **target_debug,
                            }
                        )

            for structure_db in list((runtime_source.get("structure_dbs", {}) or {}).values()):
                if not isinstance(structure_db, dict):
                    continue
                self._maintenance.apply_structure_db_soft_limits(structure_db)
                structure_db_update_request_count += 1
                structure_store.update_db(structure_db)
                structure_db_update_applied_count += 1
            source_detail["candidate_entries"].sort(
                key=lambda item: (
                    item.get("mode", ""),
                    -float(item.get("runtime_weight", 0.0)),
                    item.get("memory_id", "") or item.get("target_structure_id", ""),
                )
            )
            source_details.append(source_detail)

        runtime_metrics = self._consume_runtime_metrics()
        target_list = []
        for payload in induction_targets.values():
            target_list.append(
                {
                    "projection_kind": payload.get("projection_kind", "structure"),
                    "memory_id": payload.get("memory_id", ""),
                    "target_structure_id": payload.get("target_structure_id", ""),
                    "backing_structure_id": payload.get("backing_structure_id", ""),
                    "target_display_text": payload.get("target_display_text", ""),
                    "delta_ev": round(float(payload.get("delta_ev", 0.0)), 8),
                    "raw_residual_memory_delta_ev": round(float(payload.get("raw_residual_memory_delta_ev", 0.0)), 8),
                    "raw_residual_hit_memory_delta_ev": round(float(payload.get("raw_residual_hit_memory_delta_ev", 0.0)), 8),
                    "raw_residual_miss_memory_delta_ev": round(float(payload.get("raw_residual_miss_memory_delta_ev", 0.0)), 8),
                    "raw_residual_structure_delta_ev": round(float(payload.get("raw_residual_structure_delta_ev", 0.0)), 8),
                    "raw_residual_exact_structure_delta_ev": round(float(payload.get("raw_residual_exact_structure_delta_ev", 0.0)), 8),
                    "raw_residual_component_structure_delta_ev": round(float(payload.get("raw_residual_component_structure_delta_ev", 0.0)), 8),
                    "raw_residual_memory_refs": list(dict.fromkeys(payload.get("raw_residual_memory_refs", []) or [])),
                    "source_em_id": str(payload.get("source_em_id", "") or ""),
                    "sources": list(dict.fromkeys(payload.get("sources", []))),
                    "modes": [payload.get("mode", "")],
                    "runtime_weight": round(float(payload.get("runtime_weight", 0.0)), 8),
                    "energy_graph_round_first": int(payload.get("energy_graph_round_first", 0) or 0),
                    "energy_graph_round_last": int(payload.get("energy_graph_round_last", 0) or 0),
                    "energy_graph_depth_min": int(payload.get("energy_graph_depth_min", 0) or 0),
                    "energy_graph_depth_max": int(payload.get("energy_graph_depth_max", 0) or 0),
                    "energy_graph_emit_count": int(payload.get("energy_graph_emit_count", 0) or 0),
                    "frontier_source_kinds": list(dict.fromkeys(payload.get("frontier_source_kinds", []) or [])),
                }
            )

        self._logger.detail(
            trace_id=trace_id,
            tick_id=tick_id,
            step="induction_targets",
            message_zh="感应赋能目标摘要",
            message_en="Induction target summary",
            info={"targets": target_list[:16]},
        )

        result = {
            "code": "OK",
            "message": "Induction propagation completed",
            "source_item_count": source_item_count,
            "propagated_target_count": propagated_target_count,
            "induced_target_count": induced_target_count,
            "total_delta_ev": round(total_delta_ev, 8),
            "total_ev_consumed": round(total_ev_consumed, 8),
            "propagated_budget_total_ev": round(propagated_budget_total_ev, 8),
            "updated_weight_count": updated_weight_count,
            "induction_targets": target_list,
            "source_ev_consumptions": source_ev_consumptions,
            "fallback_used": fallback_used,
            "raw_residual_entry_count": raw_residual_entry_count,
            "raw_residual_entry_with_existing_structure_count": raw_residual_entry_with_existing_structure_count,
            "raw_residual_entry_routed_to_structure_count": raw_residual_entry_routed_to_structure_count,
            "raw_residual_existing_structure_target_count": raw_residual_existing_structure_target_count,
            "raw_residual_entry_materialized_structure_count": raw_residual_entry_materialized_structure_count,
            "raw_residual_materialized_structure_target_count": raw_residual_materialized_structure_target_count,
            "raw_residual_entry_with_component_structure_count": raw_residual_entry_with_component_structure_count,
            "raw_residual_entry_routed_to_component_structure_count": raw_residual_entry_routed_to_component_structure_count,
            "raw_residual_component_structure_target_count": raw_residual_component_structure_target_count,
            "raw_residual_structure_budget_weight": round(float(raw_residual_structure_budget_weight), 8),
            "raw_residual_exact_structure_budget_weight": round(float(raw_residual_exact_structure_budget_weight), 8),
            "raw_residual_materialized_structure_budget_weight": round(float(raw_residual_materialized_structure_budget_weight), 8),
            "raw_residual_component_structure_budget_weight": round(float(raw_residual_component_structure_budget_weight), 8),
            "raw_residual_hit_memory_budget_weight": round(float(raw_residual_hit_memory_budget_weight), 8),
            "raw_residual_miss_memory_budget_weight": round(float(raw_residual_miss_memory_budget_weight), 8),
            "entry_pruned_by_base_weight_count": int(entry_pruned_by_base_weight_count),
            "source_pruned_by_base_weight_count": int(source_pruned_by_base_weight_count),
            "structure_db_update_request_count": int(structure_db_update_request_count),
            "structure_db_update_applied_count": int(structure_db_update_applied_count),
            "structure_db_update_deduped_count": max(
                0,
                int(structure_db_update_request_count) - int(structure_db_update_applied_count),
            ),
            "runtime_only_residual_source_skipped_count": int(runtime_only_residual_skipped_count),
            "energy_graph_v2_enabled": bool(energy_graph_v2_enabled),
            "energy_graph_config": dict(energy_graph_v2),
            "energy_graph_config_max_rounds": int(energy_graph_v2.get("max_rounds", 0) or 0),
            "energy_graph_config_root_er_decay_ratio": float(energy_graph_v2.get("root_er_decay_ratio", 0.0) or 0.0),
            "energy_graph_config_root_source_ev_ratio": float(energy_graph_v2.get("root_source_ev_ratio", 0.0) or 0.0),
            "energy_graph_config_frontier_ev_ratio": float(energy_graph_v2.get("frontier_ev_ratio", 0.0) or 0.0),
            "energy_graph_config_er_round_ratio": float(energy_graph_v2.get("er_round_ratio", 0.0) or 0.0),
            "energy_graph_config_min_frontier_ev": float(energy_graph_v2.get("min_frontier_ev", 0.0) or 0.0),
            "energy_graph_config_min_budget": float(energy_graph_v2.get("min_budget", 0.0) or 0.0),
            "energy_graph_config_max_frontier_nodes_per_source": int(
                energy_graph_v2.get("max_frontier_nodes_per_source", 0) or 0
            ),
            "energy_graph_config_target_top_k": int(energy_graph_v2.get("target_top_k", 0) or 0),
            "energy_graph_round_count_max": int(energy_graph_round_count_max),
            "energy_graph_depth_max": int(energy_graph_depth_max),
            "energy_graph_frontier_generated_count": int(energy_graph_frontier_generated_count),
            "energy_graph_frontier_pruned_count": int(energy_graph_frontier_pruned_count),
            "energy_graph_terminal_memory_count": int(energy_graph_terminal_memory_count),
            "energy_graph_root_reinduction_count": int(energy_graph_root_reinduction_count),
            "energy_graph_layer_histogram": {
                str(int(depth)): int(count)
                for depth, count in sorted(energy_graph_layer_histogram.items(), key=lambda item: int(item[0]))
            },
            "energy_graph_round_summaries": [
                dict(row)
                for _, row in sorted(energy_graph_round_summaries_acc.items(), key=lambda item: int(item[0]))
            ],
            "debug": {
                "source_details": source_details,
            },
            "metrics": runtime_metrics,
        }
        self._runtime_cache = None
        self._current_structure_store = None
        return result

    @staticmethod
    def _runtime_source_has_positive_energy(source_item: dict) -> bool:
        er = max(0.0, float(source_item.get("er", 0.0) or 0.0))
        ev = max(0.0, float(source_item.get("ev", 0.0) or 0.0))
        return er > 0.0 or ev > 0.0

    @staticmethod
    def _runtime_source_has_effective_energy(
        source_item: dict,
        *,
        enable_ev_propagation: bool,
        enable_er_induction: bool,
        ev_threshold: float,
        er_threshold: float,
    ) -> bool:
        er = max(0.0, float(source_item.get("er", 0.0) or 0.0))
        ev = max(0.0, float(source_item.get("ev", 0.0) or 0.0))
        if enable_ev_propagation and ev >= float(ev_threshold):
            return True
        if enable_er_induction and er >= float(er_threshold):
            return True
        return False

    @staticmethod
    def _runtime_source_is_runtime_only_residual(source_item: dict) -> bool:
        if not isinstance(source_item, dict):
            return False
        ref_snapshot = source_item.get("ref_snapshot", {}) if isinstance(source_item.get("ref_snapshot", {}), dict) else {}
        structure_ext = ref_snapshot.get("structure_ext", {}) if isinstance(ref_snapshot.get("structure_ext", {}), dict) else {}
        meta = source_item.get("meta", {}) if isinstance(source_item.get("meta", {}), dict) else {}
        meta_ext = meta.get("ext", {}) if isinstance(meta.get("ext", {}), dict) else {}
        item_ext = source_item.get("ext", {}) if isinstance(source_item.get("ext", {}), dict) else {}
        source = source_item.get("source", {}) if isinstance(source_item.get("source", {}), dict) else {}
        containers = (structure_ext, meta_ext, item_ext, source, source_item)
        if any(bool(container.get("runtime_only_residual", False)) for container in containers if isinstance(container, dict)):
            return True
        if any(container.get("hdb_backed", None) is False for container in containers if isinstance(container, dict)):
            return True
        if str(source.get("origin", "") or "") == "stimulus_runtime_residual_package":
            return True
        return False

    @staticmethod
    def _profile_fingerprint(profile: dict) -> tuple:
        if not isinstance(profile, dict) or not profile:
            return ("", 0, 0, (), ())
        signature = str(profile.get("content_signature", "") or "")
        try:
            unit_count = int(profile.get("unit_count", 0) or 0)
        except Exception:
            unit_count = 0
        try:
            token_count = int(profile.get("token_count", 0) or 0)
        except Exception:
            token_count = 0
        if signature:
            return (signature, unit_count, token_count)
        flat_tokens = tuple(str(token) for token in (profile.get("flat_tokens", []) or []) if str(token))
        group_keys = []
        for group_index, raw_group in enumerate(profile.get("sequence_groups", []) or []):
            if not isinstance(raw_group, dict):
                continue
            units = raw_group.get("units", [])
            group_keys.append(
                (
                    int(raw_group.get("group_index", group_index) or group_index),
                    str(
                        raw_group.get("group_signature", "")
                        or raw_group.get("content_signature", "")
                        or raw_group.get("string_token_text", "")
                        or raw_group.get("display_text", "")
                    ),
                    len(units) if isinstance(units, list) else 0,
                )
            )
        return (signature, unit_count, token_count, flat_tokens, tuple(group_keys))

    def _increment_runtime_metric(self, key: str, amount: int = 1) -> None:
        if not isinstance(self._runtime_cache, dict):
            return
        metrics = self._runtime_cache.setdefault("metrics", {})
        if not isinstance(metrics, dict):
            return
        metrics[str(key)] = int(metrics.get(str(key), 0) or 0) + int(amount or 0)

    def _consume_runtime_metrics(self) -> dict:
        if not isinstance(self._runtime_cache, dict):
            return {}
        metrics = self._runtime_cache.get("metrics", {})
        if not isinstance(metrics, dict):
            return {}
        return {str(key): int(value or 0) for key, value in metrics.items()}

    @staticmethod
    def _entry_static_cache_identity(entry: dict) -> tuple:
        entry_id = str(entry.get("entry_id", "") or "")
        canonical_signature = str(
            entry.get("canonical_content_signature", "")
            or entry.get("content_signature", "")
            or ""
        )
        canonical_display_text = str(entry.get("canonical_display_text", "") or entry.get("display_text", "") or "")
        entry_type = str(entry.get("entry_type", "structure_ref") or "structure_ref")
        return entry_id, canonical_signature, canonical_display_text, entry_type

    def _raw_residual_static_cache_key(
        self,
        *,
        entry: dict,
        target_profile: dict | None,
        owner_structure_id: str,
        structure_store,
        include_lookup_revision: bool = True,
        extra: tuple = (),
    ) -> tuple:
        owner_updated_at = 0
        if self._current_structure_store is not None and owner_structure_id:
            owner_structure = self._current_structure_store.get(owner_structure_id)
            if isinstance(owner_structure, dict):
                try:
                    owner_updated_at = int(owner_structure.get("updated_at", 0) or 0)
                except Exception:
                    owner_updated_at = 0
        try:
            lookup_revision = int(getattr(structure_store, "structure_lookup_revision", 0) or 0)
        except Exception:
            lookup_revision = 0
        return (
            self._entry_static_cache_identity(entry),
            self._profile_fingerprint(target_profile or {}),
            str(owner_structure_id or ""),
            int(owner_updated_at),
            int(lookup_revision) if bool(include_lookup_revision) else 0,
            tuple(extra or ()),
        )

    def _get_runtime_or_shared_cache(self, namespace: str, key, *, structure_store):
        local_cache = None
        if isinstance(self._runtime_cache, dict):
            local_cache = self._runtime_cache.setdefault(namespace, {})
        if isinstance(local_cache, dict) and key in local_cache:
            self._increment_runtime_metric(f"{namespace}_local_cache_hit_count")
            return local_cache[key]
        if hasattr(structure_store, "get_shared_runtime_cache_entry"):
            shared_cached = structure_store.get_shared_runtime_cache_entry(namespace, key)
            if shared_cached is not None:
                if isinstance(local_cache, dict):
                    local_cache[key] = shared_cached
                self._increment_runtime_metric(f"{namespace}_shared_cache_hit_count")
                return shared_cached
        return None

    def _set_runtime_and_shared_cache(self, namespace: str, key, value, *, structure_store):
        if isinstance(self._runtime_cache, dict):
            local_cache = self._runtime_cache.setdefault(namespace, {})
            if isinstance(local_cache, dict):
                local_cache[key] = value
        if hasattr(structure_store, "set_shared_runtime_cache_entry"):
            structure_store.set_shared_runtime_cache_entry(namespace, key, value)
        return value

    def _build_runtime_source_profile_cache_key(self, *, source_item: dict) -> tuple | None:
        ref_snapshot = source_item.get("ref_snapshot", {}) if isinstance(source_item.get("ref_snapshot", {}), dict) else {}
        ref_object_type = str(source_item.get("ref_object_type", "") or "").strip().lower()
        sequence_groups = list(ref_snapshot.get("sequence_groups", []) or [])
        signature = str(
            ref_snapshot.get("content_signature", "")
            or ref_snapshot.get("canonical_content_signature", "")
            or ""
        ).strip()
        flat_tokens = tuple(str(token) for token in (ref_snapshot.get("flat_tokens", []) or []) if str(token))
        if sequence_groups:
            if signature:
                return ("runtime_groups", ref_object_type, signature, len(sequence_groups), len(flat_tokens))
            return (
                "runtime_groups",
                ref_object_type,
                signature,
                flat_tokens,
                tuple(
                    (
                        int(raw_group.get("group_index", group_index) or group_index),
                        str(
                            raw_group.get("group_signature", "")
                            or raw_group.get("content_signature", "")
                            or raw_group.get("string_token_text", "")
                            or raw_group.get("display_text", "")
                        ),
                        len(raw_group.get("units", [])) if isinstance(raw_group.get("units", []), list) else 0,
                    )
                    for group_index, raw_group in enumerate(sequence_groups)
                    if isinstance(raw_group, dict)
                ),
            )
        if flat_tokens:
            if signature:
                return ("runtime_flat", ref_object_type, signature, len(flat_tokens))
            return ("runtime_flat", ref_object_type, signature, flat_tokens)
        fallback_token = str(
            ref_snapshot.get("content_display", "")
            or source_item.get("display_text", "")
            or source_item.get("display", "")
            or source_item.get("ref_object_id", "")
            or source_item.get("item_id", source_item.get("id", ""))
            or ""
        ).strip()
        if fallback_token:
            return ("runtime_fallback", ref_object_type, fallback_token)
        return None

    def _build_runtime_source_template_key(
        self,
        *,
        support_structure_ids: list[str],
        source_profile: dict,
        structure_lookup_revision: int = 0,
    ) -> tuple | None:
        if not support_structure_ids and not source_profile:
            return None
        return (
            "runtime_source_template",
            tuple(str(structure_id or "") for structure_id in (support_structure_ids or [])),
            self._profile_fingerprint(source_profile),
            int(structure_lookup_revision or 0) if not support_structure_ids else 0,
        )

    @staticmethod
    def _materialize_runtime_source_result(
        *,
        template: dict,
        source_item_id: str,
        source_display_text: str,
    ) -> dict:
        return {
            "source_item_id": source_item_id,
            "source_display_text": str(source_display_text or template.get("source_display_text", "") or ""),
            "source_root_id": template.get("source_root_id", source_item_id) or source_item_id,
            "source_structure_obj": template.get("source_structure_obj"),
            "source_structure_db": template.get("source_structure_db"),
            "source_profile": template.get("source_profile", {}),
            "support_structure_ids": list(template.get("support_structure_ids", []) or []),
            "resolved_support_structure_ids": list(template.get("resolved_support_structure_ids", []) or []),
            "pointer_info": dict(template.get("pointer_info", {}) or {}),
            "pointer_infos": list(template.get("pointer_infos", []) or []),
            "aggregated_targets": dict(template.get("aggregated_targets", {}) or {}),
            "induction_candidates": dict(template.get("induction_candidates", {}) or {}),
            "aggregate_debug": dict(template.get("aggregate_debug", {}) or {}),
            "structure_dbs": dict(template.get("structure_dbs", {}) or {}),
            "fallback_used": bool(template.get("fallback_used", False)),
            "skipped_reason": str(template.get("skipped_reason", "") or ""),
        }

    def _extract_runtime_source_support_structure_ids(
        self,
        *,
        source_item: dict,
        structure_store,
    ) -> list[str]:
        if self._runtime_source_is_runtime_only_residual(source_item):
            return []
        ref_snapshot = source_item.get("ref_snapshot", {}) if isinstance(source_item.get("ref_snapshot", {}), dict) else {}
        ref_object_type = str(source_item.get("ref_object_type", "") or "").strip().lower()
        ref_object_id = str(source_item.get("ref_object_id", "") or "").strip()
        context_owner_id = str(
            source_item.get("context_owner_structure_id", "")
            or source_item.get("context_owner_id", "")
            or ref_snapshot.get("context_owner_id", "")
            or ""
        ).strip()
        context_ref_type = str(
            source_item.get("context_ref_object_type", "")
            or ref_snapshot.get("context_ref_object_type", "")
            or ""
        ).strip().lower()
        context_ref_id = str(
            source_item.get("context_ref_object_id", "")
            or ref_snapshot.get("context_ref_object_id", "")
            or ""
        ).strip()
        target_ref_type = str(
            source_item.get("target_ref_object_type", "")
            or ref_snapshot.get("target_ref_object_type", "")
            or ""
        ).strip().lower()
        target_ref_id = str(
            source_item.get("target_ref_object_id", "")
            or ref_snapshot.get("target_ref_object_id", "")
            or ""
        ).strip()

        support_ids: list[str] = []
        seen_ids: set[str] = set()

        def _push(raw_id: str) -> None:
            structure_id = str(raw_id or "").strip()
            if not structure_id or structure_id in seen_ids:
                return
            if structure_store is not None and not isinstance(structure_store.get(structure_id), dict):
                return
            seen_ids.add(structure_id)
            support_ids.append(structure_id)

        for raw_id in list(source_item.get("induction_source_support_structure_ids", []) or []):
            _push(raw_id)
        if ref_object_type == "st":
            _push(ref_object_id)
        _push(str(source_item.get("backing_structure_id", "") or ref_snapshot.get("backing_structure_id", "") or ""))
        for raw_id in list(ref_snapshot.get("structure_refs", []) or []):
            _push(raw_id)
        for raw_id in list(ref_snapshot.get("required_structure_ids", []) or []):
            _push(raw_id)
        for raw_id in list(ref_snapshot.get("bias_structure_ids", []) or []):
            _push(raw_id)
        for raw_id in list(source_item.get("ref_alias_ids", []) or []):
            _push(raw_id)
        return support_ids

    def _build_runtime_source_profile(self, *, source_item: dict, source_structure_obj: dict | None, cut_engine) -> dict:
        ref_object_type = str(source_item.get("ref_object_type", "") or "").strip().lower()
        if ref_object_type == "st" and isinstance(source_structure_obj, dict):
            return self._build_structure_profile_cached(
                structure_obj=source_structure_obj,
                cut_engine=cut_engine,
            )

        profile_cache_key = self._build_runtime_source_profile_cache_key(source_item=source_item)
        profile_cache = None
        if isinstance(self._runtime_cache, dict):
            profile_cache = self._runtime_cache.setdefault("runtime_source_profiles", {})
        if isinstance(profile_cache, dict) and profile_cache_key is not None and profile_cache_key in profile_cache:
            return profile_cache[profile_cache_key]
        structure_store = self._current_structure_store
        shared_cache_key = None
        if profile_cache_key is not None:
            shared_cache_key = ("runtime_source_profiles",) + tuple(profile_cache_key)
            if structure_store is not None and hasattr(structure_store, "get_shared_runtime_cache_entry"):
                shared_cached = structure_store.get_shared_runtime_cache_entry(
                    "induction_runtime_source_profiles",
                    shared_cache_key,
                )
                if isinstance(shared_cached, dict):
                    if isinstance(profile_cache, dict):
                        profile_cache[profile_cache_key] = shared_cached
                    return shared_cached

        ref_snapshot = source_item.get("ref_snapshot", {}) if isinstance(source_item.get("ref_snapshot", {}), dict) else {}
        sequence_groups = list(ref_snapshot.get("sequence_groups", []) or [])
        if sequence_groups:
            profile = cut_engine.build_sequence_profile_from_groups(sequence_groups)
            display_text = str(
                source_item.get("display_text", "")
                or source_item.get("display", "")
                or ref_snapshot.get("content_display", "")
                or ""
            ).strip()
            if display_text:
                profile["display_text"] = display_text
            if isinstance(profile_cache, dict) and profile_cache_key is not None:
                profile_cache[profile_cache_key] = profile
            if (
                profile_cache_key is not None
                and shared_cache_key is not None
                and structure_store is not None
                and hasattr(structure_store, "set_shared_runtime_cache_entry")
            ):
                structure_store.set_shared_runtime_cache_entry(
                    "induction_runtime_source_profiles",
                    shared_cache_key,
                    profile,
                )
            return profile

        flat_tokens = [str(token) for token in (ref_snapshot.get("flat_tokens", []) or []) if str(token)]
        if not flat_tokens:
            fallback_token = str(
                ref_snapshot.get("content_display", "")
                or source_item.get("display_text", "")
                or source_item.get("display", "")
                or source_item.get("ref_object_id", "")
                or source_item.get("item_id", source_item.get("id", ""))
                or ""
            ).strip()
            if fallback_token:
                flat_tokens = [fallback_token]
        if not flat_tokens:
            if isinstance(source_structure_obj, dict):
                return self._build_structure_profile_cached(
                    structure_obj=source_structure_obj,
                    cut_engine=cut_engine,
                )
            return {}

        profile = cut_engine.build_sequence_profile_from_groups(
            [
                {
                    "group_index": 0,
                    "source_type": "runtime",
                    "origin_frame_id": str(
                        source_item.get("ref_object_id", "")
                        or source_item.get("item_id", source_item.get("id", ""))
                        or "runtime_induction_source"
                    ),
                    "tokens": list(flat_tokens),
                }
            ]
        )
        display_text = str(
            source_item.get("display_text", "")
            or source_item.get("display", "")
            or ref_snapshot.get("content_display", "")
            or ""
        ).strip()
        if display_text:
            profile["display_text"] = display_text
        if isinstance(profile_cache, dict) and profile_cache_key is not None:
            profile_cache[profile_cache_key] = profile
        if (
            profile_cache_key is not None
            and shared_cache_key is not None
            and structure_store is not None
            and hasattr(structure_store, "set_shared_runtime_cache_entry")
        ):
            structure_store.set_shared_runtime_cache_entry(
                "induction_runtime_source_profiles",
                shared_cache_key,
                profile,
            )
        return profile

    def _resolve_runtime_source_structure_by_profile(
        self,
        *,
        source_item: dict,
        source_profile: dict,
        structure_store,
        pointer_index,
        cut_engine,
    ) -> str:
        signature = str(source_profile.get("content_signature", "") or "").strip()
        if not signature:
            return ""
        ref_snapshot = source_item.get("ref_snapshot", {}) if isinstance(source_item.get("ref_snapshot", {}), dict) else {}
        context_owner_id = str(
            source_item.get("context_owner_structure_id", "")
            or source_item.get("context_owner_id", "")
            or ref_snapshot.get("context_owner_id", "")
            or ""
        ).strip()
        context_ref_type = str(
            source_item.get("context_ref_object_type", "")
            or ref_snapshot.get("context_ref_object_type", "")
            or ""
        ).strip()
        context_ref_id = str(
            source_item.get("context_ref_object_id", "")
            or ref_snapshot.get("context_ref_object_id", "")
            or ""
        ).strip()
        expected_context = {}
        if context_owner_id:
            expected_context["context_owner_structure_id"] = context_owner_id
        if context_ref_id and context_ref_type:
            expected_context["context_ref_object_id"] = context_ref_id
            expected_context["context_ref_object_type"] = context_ref_type
        lookup_revision = int(getattr(structure_store, "structure_lookup_revision", 0) or 0)
        cache_key = (
            "runtime_source_structure_by_profile",
            lookup_revision,
            self._profile_fingerprint(source_profile),
            context_owner_id,
            context_ref_type,
            context_ref_id,
        )
        cache = None
        if isinstance(self._runtime_cache, dict):
            cache = self._runtime_cache.setdefault("runtime_source_structure_lookup", {})
            if cache_key in cache:
                return str(cache.get(cache_key, "") or "")
        shared_cache_key = ("runtime_source_structure_lookup",) + cache_key
        if structure_store is not None and hasattr(structure_store, "get_shared_runtime_cache_entry"):
            shared_cached = structure_store.get_shared_runtime_cache_entry(
                "induction_runtime_source_structure_lookup",
                shared_cache_key,
            )
            if shared_cached is not None:
                cached_id = str(shared_cached or "")
                if isinstance(cache, dict):
                    cache[cache_key] = cached_id
                return cached_id
        structure_obj = shared_find_exact_structure_by_signature(
            signature=signature,
            structure_store=structure_store,
            pointer_index=pointer_index,
            cut_engine=cut_engine,
            expected_tokens=list(source_profile.get("flat_tokens", []) or []),
            expected_sequence_groups=list(source_profile.get("sequence_groups", []) or []),
            expected_context=expected_context,
            strict_context_owner_match=bool(context_owner_id),
        )
        resolved_id = str(structure_obj.get("id", "") or "") if isinstance(structure_obj, dict) else ""
        if isinstance(cache, dict):
            cache[cache_key] = resolved_id
        if structure_store is not None and hasattr(structure_store, "set_shared_runtime_cache_entry"):
            structure_store.set_shared_runtime_cache_entry(
                "induction_runtime_source_structure_lookup",
                shared_cache_key,
                resolved_id,
            )
        return resolved_id

    @staticmethod
    def _copy_aggregated_target_bucket(payload: dict) -> dict:
        copied = dict(payload or {})
        copied["entries"] = list(payload.get("entries", []) or [])
        copied["raw_residual_memory_refs"] = list(payload.get("raw_residual_memory_refs", []) or [])
        return copied

    def _merge_aggregated_target_buckets(self, *, aggregated_targets: dict, incoming_targets: dict) -> None:
        numeric_float_keys = (
            "runtime_weight",
            "base_weight_weighted_sum",
            "recent_gain_weighted_sum",
            "fatigue_weighted_sum",
            "raw_residual_memory_runtime_weight",
            "raw_residual_hit_memory_runtime_weight",
            "raw_residual_miss_memory_runtime_weight",
            "raw_residual_structure_runtime_weight",
            "raw_residual_exact_structure_runtime_weight",
            "raw_residual_component_structure_runtime_weight",
        )
        numeric_int_keys = ("entry_count",)
        for bucket_key, payload in (incoming_targets or {}).items():
            if bucket_key not in aggregated_targets:
                aggregated_targets[bucket_key] = self._copy_aggregated_target_bucket(payload)
                continue
            bucket = aggregated_targets[bucket_key]
            for key in numeric_float_keys:
                bucket[key] = round(float(bucket.get(key, 0.0) or 0.0) + float(payload.get(key, 0.0) or 0.0), 8)
            for key in numeric_int_keys:
                bucket[key] = int(bucket.get(key, 0) or 0) + int(payload.get(key, 0) or 0)
            bucket.setdefault("entries", []).extend(list(payload.get("entries", []) or []))
            self._merge_bucket_residual_memory_refs(bucket, list(payload.get("raw_residual_memory_refs", []) or []))
            if not bucket.get("source_em_id") and payload.get("source_em_id"):
                bucket["source_em_id"] = payload.get("source_em_id")
            if not bucket.get("structure_obj") and payload.get("structure_obj"):
                bucket["structure_obj"] = payload.get("structure_obj")
            if not bucket.get("target_profile") and payload.get("target_profile"):
                bucket["target_profile"] = payload.get("target_profile")
            if not bucket.get("relation_type") and payload.get("relation_type"):
                bucket["relation_type"] = payload.get("relation_type")
            if not bucket.get("owner_structure_id") and payload.get("owner_structure_id"):
                bucket["owner_structure_id"] = payload.get("owner_structure_id")

    @staticmethod
    def _merge_numeric_debug(target: dict, incoming: dict) -> None:
        for key, value in (incoming or {}).items():
            if isinstance(value, bool):
                target[key] = int(target.get(key, 0) or 0) + int(value)
            elif isinstance(value, int):
                target[key] = int(target.get(key, 0) or 0) + int(value)
            elif isinstance(value, float):
                target[key] = round(float(target.get(key, 0.0) or 0.0) + float(value), 8)

    def _resolve_runtime_source_data(
        self,
        *,
        source_item: dict,
        structure_store,
        episodic_store,
        pointer_index,
        cut_engine,
        now_ms: int,
        trace_id: str,
        tick_id: str,
        structure_source_cache: dict | None = None,
    ) -> dict:
        source_item_id = str(source_item.get("item_id", source_item.get("id", "")) or "")
        ref_snapshot = source_item.get("ref_snapshot", {}) if isinstance(source_item.get("ref_snapshot", {}), dict) else {}
        source_display_text = str(
            source_item.get("display_text", "")
            or source_item.get("display", "")
            or ref_snapshot.get("content_display", "")
            or source_item.get("ref_object_id", "")
            or source_item_id
        ).strip()
        if self._runtime_source_is_runtime_only_residual(source_item):
            source_profile = self._build_runtime_source_profile(
                source_item=source_item,
                source_structure_obj=None,
                cut_engine=cut_engine,
            )
            return {
                "source_item_id": source_item_id,
                "source_display_text": source_display_text,
                "source_root_id": source_item_id,
                "source_structure_obj": None,
                "source_structure_db": None,
                "source_profile": source_profile,
                "support_structure_ids": [],
                "resolved_support_structure_ids": [],
                "pointer_info": {},
                "pointer_infos": [],
                "aggregated_targets": {},
                "induction_candidates": {},
                "aggregate_debug": {},
                "structure_dbs": {},
                "fallback_used": False,
                "skipped_reason": "runtime_residual_not_hdb_backed",
            }

        support_structure_ids = self._extract_runtime_source_support_structure_ids(
            source_item=source_item,
            structure_store=structure_store,
        )
        primary_structure_obj = None
        if support_structure_ids:
            primary_structure_obj = structure_store.get(support_structure_ids[0])
        source_profile = self._build_runtime_source_profile(
            source_item=source_item,
            source_structure_obj=primary_structure_obj,
            cut_engine=cut_engine,
        )
        if not source_profile and isinstance(primary_structure_obj, dict):
            source_profile = self._build_structure_profile_cached(
                structure_obj=primary_structure_obj,
                cut_engine=cut_engine,
            )
        if source_profile and not source_display_text:
            source_display_text = str(source_profile.get("display_text", "") or source_display_text)

        structure_lookup_revision = int(getattr(structure_store, "structure_lookup_revision", 0) or 0)
        runtime_source_template_key = self._build_runtime_source_template_key(
            support_structure_ids=support_structure_ids,
            source_profile=source_profile,
            structure_lookup_revision=structure_lookup_revision,
        )
        runtime_source_template_cache = None
        if isinstance(self._runtime_cache, dict):
            runtime_source_template_cache = self._runtime_cache.setdefault("runtime_source_data_templates", {})
        if (
            isinstance(runtime_source_template_cache, dict)
            and runtime_source_template_key is not None
            and runtime_source_template_key in runtime_source_template_cache
        ):
            return self._materialize_runtime_source_result(
                template=runtime_source_template_cache[runtime_source_template_key],
                source_item_id=source_item_id,
                source_display_text=source_display_text,
            )
        if not support_structure_ids and source_profile:
            fallback_structure_id = self._resolve_runtime_source_structure_by_profile(
                source_item=source_item,
                source_profile=source_profile,
                structure_store=structure_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
            )
            if fallback_structure_id:
                support_structure_ids.append(fallback_structure_id)
                primary_structure_obj = structure_store.get(fallback_structure_id)
                runtime_source_template_key = self._build_runtime_source_template_key(
                    support_structure_ids=support_structure_ids,
                    source_profile=source_profile,
                    structure_lookup_revision=structure_lookup_revision,
                )
                if (
                    isinstance(runtime_source_template_cache, dict)
                    and runtime_source_template_key is not None
                    and runtime_source_template_key in runtime_source_template_cache
                ):
                    return self._materialize_runtime_source_result(
                        template=runtime_source_template_cache[runtime_source_template_key],
                        source_item_id=source_item_id,
                        source_display_text=source_display_text,
                    )

        aggregated_targets: dict = {}
        induction_candidates: dict = {}
        aggregate_debug: dict = {}
        resolved_support_structure_ids: list[str] = []
        pointer_infos: list[dict] = []
        structure_dbs: dict[str, dict] = {}
        fallback_used = False
        pointer_info_primary: dict = {}
        structure_db_primary = None
        source_root_id = ""
        source_structure_obj = primary_structure_obj

        for structure_id in support_structure_ids:
            source_payload = self._resolve_structure_graph_source_data(
                structure_id=structure_id,
                source_data_cache=(structure_source_cache if isinstance(structure_source_cache, dict) else {}),
                structure_store=structure_store,
                episodic_store=episodic_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
                now_ms=now_ms,
                trace_id=trace_id,
                tick_id=tick_id,
            )
            structure_obj = source_payload.get("structure_obj")
            if not isinstance(structure_obj, dict):
                continue
            structure_db = source_payload.get("structure_db")
            if not isinstance(structure_db, dict):
                continue
            pointer_info = dict(source_payload.get("pointer_info", {}) or {})
            resolved_support_structure_ids.append(structure_id)
            pointer_row = {"structure_id": structure_id, **dict(pointer_info or {})}
            pointer_infos.append(pointer_row)
            if not pointer_info_primary:
                pointer_info_primary = dict(pointer_info or {})
                structure_db_primary = structure_db
                source_root_id = structure_id
                source_structure_obj = structure_obj
            fallback_used = fallback_used or bool(pointer_info.get("used_fallback"))
            structure_dbs[structure_id] = structure_db
            local_targets = dict(source_payload.get("aggregated_targets", {}) or {})
            local_debug = dict(source_payload.get("aggregate_debug", {}) or {})
            self._merge_aggregated_target_buckets(
                aggregated_targets=aggregated_targets,
                incoming_targets=local_targets,
            )
            self._merge_numeric_debug(aggregate_debug, local_debug)

        if aggregated_targets and source_profile:
            induction_candidates = self._filter_full_inclusion_targets(
                source_structure_id=source_root_id,
                source_structure_ids=list(resolved_support_structure_ids),
                source_profile=source_profile,
                aggregated_targets=aggregated_targets,
                cut_engine=cut_engine,
            )

        skipped_reason = ""
        if not source_profile:
            skipped_reason = "source_profile_unavailable"
        elif not support_structure_ids:
            skipped_reason = "support_structure_unresolved"
        elif not resolved_support_structure_ids:
            skipped_reason = "support_structure_db_unresolved"
        elif not aggregated_targets:
            skipped_reason = "no_local_targets"

        result_template = {
            "source_display_text": source_display_text,
            "source_root_id": source_root_id or source_item_id,
            "source_structure_obj": source_structure_obj,
            "source_structure_db": structure_db_primary,
            "source_profile": source_profile,
            "support_structure_ids": support_structure_ids,
            "resolved_support_structure_ids": resolved_support_structure_ids,
            "pointer_info": pointer_info_primary,
            "pointer_infos": pointer_infos,
            "aggregated_targets": aggregated_targets,
            "induction_candidates": induction_candidates,
            "aggregate_debug": aggregate_debug,
            "structure_dbs": structure_dbs,
            "fallback_used": fallback_used,
            "skipped_reason": skipped_reason,
        }
        if (
            isinstance(runtime_source_template_cache, dict)
            and runtime_source_template_key is not None
        ):
            runtime_source_template_cache[runtime_source_template_key] = result_template
        return self._materialize_runtime_source_result(
            template=result_template,
            source_item_id=source_item_id,
            source_display_text=source_display_text,
        )

    def _resolve_energy_graph_v2_settings(self, *, ev_ratio: float, er_ratio: float) -> dict:
        enabled = bool(
            self._config.get(
                "induction_energy_graph_v2_enabled",
                self._config.get("energy_graph_v2_enabled", False),
            )
        )
        try:
            max_rounds = int(
                self._config.get(
                    "induction_energy_graph_v2_max_rounds",
                    self._config.get("energy_graph_v2_max_rounds", 0),
                )
                or 0
            )
        except Exception:
            max_rounds = 0
        try:
            root_er_decay_ratio = float(
                self._config.get(
                    "induction_energy_graph_v2_root_er_decay_ratio",
                    self._config.get("energy_graph_v2_root_er_decay_ratio", 0.82),
                )
                or 0.82
            )
        except Exception:
            root_er_decay_ratio = 0.82
        try:
            root_source_ev_ratio = float(
                self._config.get(
                    "induction_energy_graph_v2_root_source_ev_ratio",
                    self._config.get("energy_graph_v2_root_source_ev_ratio", ev_ratio),
                )
                or ev_ratio
            )
        except Exception:
            root_source_ev_ratio = ev_ratio
        try:
            frontier_ev_ratio = float(
                self._config.get(
                    "induction_energy_graph_v2_frontier_ev_ratio",
                    self._config.get("energy_graph_v2_frontier_ev_ratio", ev_ratio),
                )
                or ev_ratio
            )
        except Exception:
            frontier_ev_ratio = ev_ratio
        try:
            er_round_ratio = float(
                self._config.get(
                    "induction_energy_graph_v2_er_round_ratio",
                    self._config.get("energy_graph_v2_er_round_ratio", er_ratio),
                )
                or er_ratio
            )
        except Exception:
            er_round_ratio = er_ratio
        try:
            min_frontier_ev = float(
                self._config.get(
                    "induction_energy_graph_v2_min_frontier_ev",
                    self._config.get("energy_graph_v2_min_frontier_ev", 0.05),
                )
                or 0.05
            )
        except Exception:
            min_frontier_ev = 0.05
        try:
            min_budget = float(
                self._config.get(
                    "induction_energy_graph_v2_min_budget",
                    self._config.get("energy_graph_v2_min_budget", 0.03),
                )
                or 0.03
            )
        except Exception:
            min_budget = 0.03
        try:
            max_frontier_nodes = int(
                self._config.get(
                    "induction_energy_graph_v2_max_frontier_nodes_per_source",
                    self._config.get("energy_graph_v2_max_frontier_nodes_per_source", 0),
                )
                or 0
            )
        except Exception:
            max_frontier_nodes = 0
        try:
            target_top_k = int(
                self._config.get(
                    "induction_energy_graph_v2_target_top_k",
                    self._config.get("induction_target_top_k", 0),
                )
                or 0
            )
        except Exception:
            target_top_k = 0
        return {
            "enabled": bool(enabled),
            "max_rounds": max(0, int(max_rounds)),
            "root_er_decay_ratio": max(0.0, min(1.0, float(root_er_decay_ratio))),
            "root_source_ev_ratio": max(0.0, min(1.0, float(root_source_ev_ratio))),
            "frontier_ev_ratio": max(0.0, min(1.2, float(frontier_ev_ratio))),
            "er_round_ratio": max(0.0, min(1.2, float(er_round_ratio))),
            "min_frontier_ev": max(0.0, float(min_frontier_ev)),
            "min_budget": max(0.0, float(min_budget)),
            "max_frontier_nodes_per_source": max(0, int(max_frontier_nodes)),
            "target_top_k": max(0, int(target_top_k)),
        }

    def _resolve_structure_graph_source_data(
        self,
        *,
        structure_id: str,
        source_data_cache: dict,
        shared_source_data_cache: dict | None = None,
        structure_store,
        episodic_store,
        pointer_index,
        cut_engine,
        now_ms: int,
        trace_id: str,
        tick_id: str,
    ) -> dict:
        cached = source_data_cache.get(structure_id)
        if isinstance(cached, dict):
            return cached
        if isinstance(shared_source_data_cache, dict):
            shared_cached = shared_source_data_cache.get(structure_id)
            if isinstance(shared_cached, dict):
                source_data_cache[structure_id] = shared_cached
                return shared_cached
        structure_obj = structure_store.get(structure_id)
        if not structure_obj:
            payload = {
                "structure_obj": None,
                "structure_db": None,
                "pointer_info": {},
                "source_profile": {},
                "aggregated_targets": {},
                "induction_candidates": {},
                "aggregate_debug": {},
            }
            source_data_cache[structure_id] = payload
            if isinstance(shared_source_data_cache, dict):
                shared_source_data_cache[structure_id] = payload
            return payload
        structure_db, pointer_info = pointer_index.resolve_db(
            structure_obj=structure_obj,
            structure_store=structure_store,
            logger=self._logger,
            trace_id=trace_id,
            tick_id=tick_id,
        )
        source_profile = self._build_structure_profile_cached(
            structure_obj=structure_obj,
            cut_engine=cut_engine,
        )
        aggregated_targets: dict = {}
        aggregate_debug: dict = {}
        induction_candidates: dict = {}
        if structure_db:
            aggregated_targets, aggregate_debug = self._aggregate_local_targets(
                structure_db=structure_db,
                structure_store=structure_store,
                episodic_store=episodic_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
                now_ms=now_ms,
                trace_id=trace_id,
                tick_id=tick_id,
            )
            induction_candidates = self._filter_full_inclusion_targets(
                source_structure_id=structure_id,
                source_profile=source_profile,
                aggregated_targets=aggregated_targets,
                cut_engine=cut_engine,
            )
        payload = {
            "structure_obj": structure_obj,
            "structure_db": structure_db,
            "pointer_info": pointer_info,
            "source_profile": source_profile,
            "aggregated_targets": aggregated_targets,
            "induction_candidates": induction_candidates,
            "aggregate_debug": aggregate_debug,
        }
        source_data_cache[structure_id] = payload
        if isinstance(shared_source_data_cache, dict):
            shared_source_data_cache[structure_id] = payload
        return payload

    @staticmethod
    def _select_target_buckets(*, buckets: dict, top_k: int) -> list[dict]:
        rows = [dict(item) for item in buckets.values() if isinstance(item, dict)]
        rows.sort(
            key=lambda item: (
                -float(item.get("runtime_weight", 0.0)),
                0 if str(item.get("projection_kind", "structure")) == "structure" else 1,
                str(item.get("target_id", "") or item.get("memory_id", "")),
            )
        )
        if top_k > 0:
            rows = rows[:top_k]
        return rows

    @staticmethod
    def _queue_frontier_target(
        *,
        frontier_map: dict,
        target: dict,
        delta_ev: float,
        depth: int,
        round_index: int,
        parent_structure_id: str,
    ) -> None:
        if str(target.get("projection_kind", "structure")) != "structure":
            return
        target_structure_id = str(target.get("target_id", "") or "")
        if not target_structure_id or delta_ev <= 0.0:
            return
        bucket = frontier_map.setdefault(
            target_structure_id,
            {
                "structure_id": target_structure_id,
                "display_text": str(target.get("display_text", "") or target_structure_id),
                "available_ev": 0.0,
                "depth": int(depth),
                "round_index_first": int(round_index),
                "round_index_last": int(round_index),
                "parent_structure_ids": [],
            },
        )
        bucket["available_ev"] = round(float(bucket.get("available_ev", 0.0)) + float(delta_ev), 8)
        bucket["depth"] = min(int(bucket.get("depth", depth) or depth), int(depth))
        bucket["round_index_last"] = int(round_index)
        bucket.setdefault("parent_structure_ids", []).append(parent_structure_id)

    def _run_source_energy_graph_v2(
        self,
        *,
        source_item: dict,
        source_structure_id: str,
        source_structure_obj: dict,
        source_display_text: str,
        source_er: float,
        source_ev: float,
        enable_ev_propagation: bool,
        enable_er_induction: bool,
        source_profile: dict,
        structure_db: dict,
        pointer_info: dict,
        aggregated_targets: dict,
        induction_candidates: dict,
        structure_store,
        episodic_store,
        pointer_index,
        cut_engine,
        now_ms: int,
        trace_id: str,
        tick_id: str,
        induction_targets: dict,
        energy_graph_v2: dict,
        shared_source_data_cache: dict | None = None,
    ) -> dict:
        round_summaries = []
        candidate_entries = []
        source_ev_consumptions = []
        total_delta_ev = 0.0
        total_ev_consumed = 0.0
        propagated_budget_total_ev = 0.0
        updated_weight_count = 0
        propagated_target_count = 0
        induced_target_count = 0
        frontier_generated_count = 0
        frontier_pruned_count = 0
        terminal_memory_count = 0
        root_reinduction_count = 0
        layer_histogram: dict[int, int] = {}
        source_data_cache = {
            str(source_structure_id): {
                "structure_obj": source_structure_obj,
                "structure_db": structure_db,
                "pointer_info": pointer_info,
                "source_profile": source_profile,
                "aggregated_targets": aggregated_targets,
                "induction_candidates": induction_candidates,
                "aggregate_debug": {},
            }
        }
        frontier = []
        if source_ev > 0.0:
            frontier.append(
                {
                    "structure_id": str(source_structure_id),
                    "display_text": str(
                        source_display_text
                        or (source_structure_obj.get("structure", {}).get("display_text", "") if isinstance(source_structure_obj, dict) else "")
                        or source_structure_id
                    ),
                    "available_ev": round(float(source_ev), 8),
                    "depth": 0,
                    "is_runtime_root": True,
                    "round_index_first": 1,
                    "round_index_last": 1,
                }
            )
        current_root_er = round(float(source_er), 8)
        max_rounds = int(energy_graph_v2.get("max_rounds", 0) or 0)
        min_frontier_ev = float(energy_graph_v2.get("min_frontier_ev", 0.05) or 0.05)
        min_budget = float(energy_graph_v2.get("min_budget", 0.03) or 0.03)
        frontier_ev_ratio = float(energy_graph_v2.get("frontier_ev_ratio", 1.0) or 1.0)
        root_source_ev_ratio = float(energy_graph_v2.get("root_source_ev_ratio", frontier_ev_ratio) or frontier_ev_ratio)
        er_round_ratio = float(energy_graph_v2.get("er_round_ratio", 1.0) or 1.0)
        root_er_decay_ratio = float(energy_graph_v2.get("root_er_decay_ratio", 0.82) or 0.82)
        target_top_k = int(energy_graph_v2.get("target_top_k", 0) or 0)
        max_frontier_nodes = int(energy_graph_v2.get("max_frontier_nodes_per_source", 0) or 0)
        ev_threshold = float(self._config.get("ev_propagation_threshold", 0.12) or 0.12)
        er_threshold = float(self._config.get("er_induction_threshold", 0.15) or 0.15)

        round_index = 0
        while True:
            round_index += 1
            if max_rounds > 0 and round_index > max_rounds:
                break
            round_delta_ev = 0.0
            frontier_budget_ev = 0.0
            root_induction_budget_ev = 0.0
            current_frontier = list(frontier)
            next_frontier_map: dict[str, dict] = {}
            round_frontier_pruned_count = 0
            round_frontier_memory_terminal_count = 0
            round_root_reinduction_count = 0

            for frontier_node in current_frontier:
                node_ev = max(0.0, float(frontier_node.get("available_ev", 0.0) or 0.0))
                if node_ev < min_frontier_ev or node_ev < ev_threshold:
                    frontier_pruned_count += 1
                    round_frontier_pruned_count += 1
                    continue
                node_structure_id = str(frontier_node.get("structure_id", "") or "")
                if not node_structure_id:
                    frontier_pruned_count += 1
                    round_frontier_pruned_count += 1
                    continue
                node_data = self._resolve_structure_graph_source_data(
                    structure_id=node_structure_id,
                    source_data_cache=source_data_cache,
                    shared_source_data_cache=shared_source_data_cache,
                    structure_store=structure_store,
                    episodic_store=episodic_store,
                    pointer_index=pointer_index,
                    cut_engine=cut_engine,
                    now_ms=now_ms,
                    trace_id=trace_id,
                    tick_id=tick_id,
                )
                target_buckets = self._select_target_buckets(
                    buckets=node_data.get("aggregated_targets", {}) or {},
                    top_k=target_top_k,
                )
                if not target_buckets:
                    continue
                source_ratio = root_source_ev_ratio if bool(frontier_node.get("is_runtime_root", False)) else frontier_ev_ratio
                budget_ev = round(node_ev * source_ratio, 8)
                if budget_ev < min_budget:
                    frontier_pruned_count += 1
                    round_frontier_pruned_count += 1
                    continue
                total_weight = sum(float(target.get("runtime_weight", 0.0) or 0.0) for target in target_buckets)
                if total_weight <= 0.0:
                    continue
                frontier_budget_ev = round(float(frontier_budget_ev) + float(budget_ev), 8)
                propagated_budget_total_ev += budget_ev
                if bool(frontier_node.get("is_runtime_root", False)):
                    total_ev_consumed += budget_ev
                    source_ev_consumptions.append(
                        {
                            "source_structure_id": node_structure_id,
                            "source_item_id": source_item.get("item_id", source_item.get("id", "")),
                            "consumed_ev": budget_ev,
                        }
                    )
                for target in target_buckets:
                    if (
                        str(target.get("projection_kind", "structure") or "structure") == "structure"
                        and str(target.get("target_id", "") or "").strip() == node_structure_id
                    ):
                        continue
                    target_runtime_weight = float(target.get("runtime_weight", 0.0) or 0.0)
                    delta_ev = round(budget_ev * (target_runtime_weight / total_weight), 8)
                    if delta_ev <= 0.0:
                        continue
                    self._mark_bucket_entries(
                        entry_items=target.get("entries", []),
                        total_weight=total_weight,
                        delta_er=0.0,
                        delta_ev=budget_ev,
                        now_ms=now_ms,
                    )
                    updated_weight_count += len(target.get("entries", []))
                    total_delta_ev += delta_ev
                    round_delta_ev += delta_ev
                    propagated_target_count += 1
                    depth = int(frontier_node.get("depth", 0) or 0) + 1
                    layer_histogram[depth] = int(layer_histogram.get(depth, 0) or 0) + 1
                    target_runtime_total = max(1e-8, target_runtime_weight)
                    raw_residual_memory_delta_ev = round(
                        delta_ev * (float(target.get("raw_residual_memory_runtime_weight", 0.0)) / target_runtime_total),
                        8,
                    )
                    raw_residual_hit_memory_delta_ev = round(
                        delta_ev * (float(target.get("raw_residual_hit_memory_runtime_weight", 0.0)) / target_runtime_total),
                        8,
                    )
                    raw_residual_miss_memory_delta_ev = round(
                        delta_ev * (float(target.get("raw_residual_miss_memory_runtime_weight", 0.0)) / target_runtime_total),
                        8,
                    )
                    raw_residual_structure_delta_ev = round(
                        delta_ev * (float(target.get("raw_residual_structure_runtime_weight", 0.0)) / target_runtime_total),
                        8,
                    )
                    raw_residual_exact_structure_delta_ev = round(
                        delta_ev * (float(target.get("raw_residual_exact_structure_runtime_weight", 0.0)) / target_runtime_total),
                        8,
                    )
                    raw_residual_component_structure_delta_ev = round(
                        delta_ev * (float(target.get("raw_residual_component_structure_runtime_weight", 0.0)) / target_runtime_total),
                        8,
                    )
                    self._append_target_delta(
                        induction_targets=induction_targets,
                        projection_kind=target.get("projection_kind", "structure"),
                        memory_id=target.get("memory_id", ""),
                        target_id=target.get("target_id", ""),
                        backing_structure_id=target.get("backing_structure_id", ""),
                        target_display_text=target.get("display_text", target.get("target_id", "")),
                        mode="ev_propagation",
                        source_structure_id=node_structure_id,
                        delta_ev=delta_ev,
                        runtime_weight=target_runtime_weight,
                        raw_residual_memory_delta_ev=raw_residual_memory_delta_ev,
                        raw_residual_hit_memory_delta_ev=raw_residual_hit_memory_delta_ev,
                        raw_residual_miss_memory_delta_ev=raw_residual_miss_memory_delta_ev,
                        raw_residual_structure_delta_ev=raw_residual_structure_delta_ev,
                        raw_residual_exact_structure_delta_ev=raw_residual_exact_structure_delta_ev,
                        raw_residual_component_structure_delta_ev=raw_residual_component_structure_delta_ev,
                        raw_residual_memory_refs=list(target.get("raw_residual_memory_refs", []) or []),
                        source_em_id=str(target.get("source_em_id", "") or ""),
                        energy_graph_round=round_index,
                        energy_graph_depth=depth,
                        frontier_source_kind=("root_ev" if bool(frontier_node.get("is_runtime_root", False)) else "frontier_ev"),
                    )
                    target_debug = self._build_target_debug_entry(
                        target=target,
                        total_weight=total_weight,
                        delta_ev=delta_ev,
                    )
                    target_debug["energy_graph_round"] = int(round_index)
                    target_debug["energy_graph_depth"] = int(depth)
                    target_debug["frontier_source_kind"] = "root_ev" if bool(frontier_node.get("is_runtime_root", False)) else "frontier_ev"
                    candidate_entries.append(
                        {
                            "projection_kind": target.get("projection_kind", "structure"),
                            "memory_id": target.get("memory_id", ""),
                            "target_structure_id": target.get("target_id", ""),
                            "backing_structure_id": target.get("backing_structure_id", ""),
                            "target_display_text": target.get("display_text", target.get("target_id", "")),
                            "target_profile": target.get("target_profile", {}),
                            "relation_type": target.get("relation_type", ""),
                            "owner_structure_id": target.get("owner_structure_id", ""),
                            "mode": "ev_propagation",
                            "direct_source_structure_id": node_structure_id,
                            "growth_source_structure_id": node_structure_id,
                            "root_source_structure_id": source_structure_id,
                            **target_debug,
                        }
                    )
                    if str(target.get("projection_kind", "structure")) == "memory":
                        round_frontier_memory_terminal_count += 1
                        terminal_memory_count += 1
                    else:
                        self._queue_frontier_target(
                            frontier_map=next_frontier_map,
                            target=target,
                            delta_ev=delta_ev,
                            depth=depth,
                            round_index=round_index,
                            parent_structure_id=node_structure_id,
                        )

            if enable_er_induction and current_root_er >= er_threshold:
                source_data = source_data_cache.get(str(source_structure_id), {})
                induction_buckets = self._select_target_buckets(
                    buckets=source_data.get("induction_candidates", {}) or {},
                    top_k=target_top_k,
                )
                if induction_buckets:
                    induction_budget = round(current_root_er * er_round_ratio, 8)
                    if induction_budget >= min_budget:
                        total_weight = sum(float(target.get("runtime_weight", 0.0) or 0.0) for target in induction_buckets)
                        if total_weight > 0.0:
                            if round_index > 1:
                                round_root_reinduction_count += 1
                                root_reinduction_count += 1
                            root_induction_budget_ev = round(float(root_induction_budget_ev) + float(induction_budget), 8)
                            for target in induction_buckets:
                                if (
                                    str(target.get("projection_kind", "structure") or "structure") == "structure"
                                    and str(target.get("target_id", "") or "").strip() == str(source_structure_id)
                                ):
                                    continue
                                target_runtime_weight = float(target.get("runtime_weight", 0.0) or 0.0)
                                delta_ev = round(induction_budget * (target_runtime_weight / total_weight), 8)
                                if delta_ev <= 0.0:
                                    continue
                                self._mark_bucket_entries(
                                    entry_items=target.get("entries", []),
                                    total_weight=total_weight,
                                    delta_er=induction_budget,
                                    delta_ev=induction_budget,
                                    now_ms=now_ms,
                                )
                                updated_weight_count += len(target.get("entries", []))
                                total_delta_ev += delta_ev
                                round_delta_ev += delta_ev
                                induced_target_count += 1
                                layer_histogram[1] = int(layer_histogram.get(1, 0) or 0) + 1
                                target_runtime_total = max(1e-8, target_runtime_weight)
                                raw_residual_memory_delta_ev = round(
                                    delta_ev * (float(target.get("raw_residual_memory_runtime_weight", 0.0)) / target_runtime_total),
                                    8,
                                )
                                raw_residual_hit_memory_delta_ev = round(
                                    delta_ev * (float(target.get("raw_residual_hit_memory_runtime_weight", 0.0)) / target_runtime_total),
                                    8,
                                )
                                raw_residual_miss_memory_delta_ev = round(
                                    delta_ev * (float(target.get("raw_residual_miss_memory_runtime_weight", 0.0)) / target_runtime_total),
                                    8,
                                )
                                raw_residual_structure_delta_ev = round(
                                    delta_ev * (float(target.get("raw_residual_structure_runtime_weight", 0.0)) / target_runtime_total),
                                    8,
                                )
                                raw_residual_exact_structure_delta_ev = round(
                                    delta_ev * (float(target.get("raw_residual_exact_structure_runtime_weight", 0.0)) / target_runtime_total),
                                    8,
                                )
                                raw_residual_component_structure_delta_ev = round(
                                    delta_ev * (float(target.get("raw_residual_component_structure_runtime_weight", 0.0)) / target_runtime_total),
                                    8,
                                )
                                self._append_target_delta(
                                    induction_targets=induction_targets,
                                    projection_kind=target.get("projection_kind", "structure"),
                                    memory_id=target.get("memory_id", ""),
                                    target_id=target.get("target_id", ""),
                                    backing_structure_id=target.get("backing_structure_id", ""),
                                    target_display_text=target.get("display_text", target.get("target_id", "")),
                                    mode="er_induction",
                                    source_structure_id=source_structure_id,
                                    delta_ev=delta_ev,
                                    runtime_weight=target_runtime_weight,
                                    raw_residual_memory_delta_ev=raw_residual_memory_delta_ev,
                                    raw_residual_hit_memory_delta_ev=raw_residual_hit_memory_delta_ev,
                                    raw_residual_miss_memory_delta_ev=raw_residual_miss_memory_delta_ev,
                                    raw_residual_structure_delta_ev=raw_residual_structure_delta_ev,
                                    raw_residual_exact_structure_delta_ev=raw_residual_exact_structure_delta_ev,
                                    raw_residual_component_structure_delta_ev=raw_residual_component_structure_delta_ev,
                                    raw_residual_memory_refs=list(target.get("raw_residual_memory_refs", []) or []),
                                    source_em_id=str(target.get("source_em_id", "") or ""),
                                    energy_graph_round=round_index,
                                    energy_graph_depth=1,
                                    frontier_source_kind="root_er",
                                )
                                target_debug = self._build_target_debug_entry(
                                    target=target,
                                    total_weight=total_weight,
                                    delta_ev=delta_ev,
                                )
                                target_debug["energy_graph_round"] = int(round_index)
                                target_debug["energy_graph_depth"] = 1
                                target_debug["frontier_source_kind"] = "root_er"
                                candidate_entries.append(
                                    {
                                        "projection_kind": target.get("projection_kind", "structure"),
                                        "memory_id": target.get("memory_id", ""),
                                        "target_structure_id": target.get("target_id", ""),
                                        "backing_structure_id": target.get("backing_structure_id", ""),
                                        "target_display_text": target.get("display_text", target.get("target_id", "")),
                                        "target_profile": target.get("target_profile", {}),
                                        "relation_type": target.get("relation_type", ""),
                                        "owner_structure_id": target.get("owner_structure_id", ""),
                                        "mode": "er_induction",
                                        "direct_source_structure_id": source_structure_id,
                                        "growth_source_structure_id": source_structure_id,
                                        "root_source_structure_id": source_structure_id,
                                        **target_debug,
                                    }
                                )
                                if str(target.get("projection_kind", "structure")) == "memory":
                                    round_frontier_memory_terminal_count += 1
                                    terminal_memory_count += 1
                                else:
                                    self._queue_frontier_target(
                                        frontier_map=next_frontier_map,
                                        target=target,
                                        delta_ev=delta_ev,
                                        depth=1,
                                        round_index=round_index,
                                        parent_structure_id=source_structure_id,
                                    )
            current_root_er = round(float(current_root_er) * float(root_er_decay_ratio), 8)
            next_frontier_rows = list(next_frontier_map.values())
            next_frontier_rows.sort(
                key=lambda row: (
                    -float(row.get("available_ev", 0.0)),
                    int(row.get("depth", 0)),
                    str(row.get("structure_id", "")),
                )
            )
            if max_frontier_nodes > 0 and len(next_frontier_rows) > max_frontier_nodes:
                overflow = len(next_frontier_rows) - max_frontier_nodes
                frontier_pruned_count += int(overflow)
                round_frontier_pruned_count += int(overflow)
                next_frontier_rows = next_frontier_rows[:max_frontier_nodes]
            frontier_generated_count += len(next_frontier_rows)
            frontier = next_frontier_rows
            for row in frontier:
                try:
                    depth_value = int(row.get("depth", 0) or 0)
                except Exception:
                    depth_value = 0
                if depth_value > 0:
                    layer_histogram[depth_value] = int(layer_histogram.get(depth_value, 0) or 0) + 1
            round_summaries.append(
                {
                    "round_index": int(round_index),
                    "frontier_in_count": len(current_frontier),
                    "frontier_out_count": len(frontier),
                    "frontier_pruned_count": int(round_frontier_pruned_count),
                    "frontier_memory_terminal_count": int(round_frontier_memory_terminal_count),
                    "root_reinduction_count": int(round_root_reinduction_count),
                    "frontier_budget_ev": round(float(frontier_budget_ev), 8),
                    "root_induction_budget_ev": round(float(root_induction_budget_ev), 8),
                    "round_delta_ev": round(float(round_delta_ev), 8),
                }
            )
            if not frontier and current_root_er < er_threshold:
                break

        candidate_entries.sort(
            key=lambda item: (
                int(item.get("energy_graph_round", 0) or 0),
                int(item.get("energy_graph_depth", 0) or 0),
                str(item.get("mode", "") or ""),
                -float(item.get("runtime_weight", 0.0) or 0.0),
            )
        )
        return {
            "propagated_target_count": int(propagated_target_count),
            "induced_target_count": int(induced_target_count),
            "total_delta_ev": round(float(total_delta_ev), 8),
            "total_ev_consumed": round(float(total_ev_consumed), 8),
            "propagated_budget_total_ev": round(float(propagated_budget_total_ev), 8),
            "updated_weight_count": int(updated_weight_count),
            "source_ev_consumptions": list(source_ev_consumptions),
            "candidate_entries": candidate_entries,
            "round_summaries": round_summaries,
            "energy_graph_summary": {
                "round_count": len(round_summaries),
                "depth_max": max([0] + [int(x) for x in layer_histogram.keys()]),
                "frontier_generated_count": int(frontier_generated_count),
                "frontier_pruned_count": int(frontier_pruned_count),
                "terminal_memory_count": int(terminal_memory_count),
                "root_reinduction_count": int(root_reinduction_count),
                "layer_histogram": {str(int(k)): int(v) for k, v in sorted(layer_histogram.items(), key=lambda item: int(item[0]))},
            },
        }

    def _aggregate_local_targets(
        self,
        *,
        structure_db: dict,
        structure_store,
        episodic_store,
        pointer_index,
        cut_engine,
        now_ms: int,
        trace_id: str,
        tick_id: str,
    ) -> tuple[dict[tuple[str, str], dict], dict]:
        targets: dict[tuple[str, str], dict] = {}
        debug = {
            "raw_residual_entry_count": 0,
            "raw_residual_entry_with_existing_structure_count": 0,
            "raw_residual_entry_routed_to_structure_count": 0,
            "raw_residual_existing_structure_target_count": 0,
            "raw_residual_entry_materialized_structure_count": 0,
            "raw_residual_materialized_structure_target_count": 0,
            "raw_residual_entry_with_component_structure_count": 0,
            "raw_residual_entry_routed_to_component_structure_count": 0,
            "raw_residual_component_structure_target_count": 0,
            "raw_residual_structure_budget_weight": 0.0,
            "raw_residual_exact_structure_budget_weight": 0.0,
            "raw_residual_materialized_structure_budget_weight": 0.0,
            "raw_residual_component_structure_budget_weight": 0.0,
            "raw_residual_hit_memory_budget_weight": 0.0,
            "raw_residual_miss_memory_budget_weight": 0.0,
            "entry_pruned_by_base_weight_count": 0,
        }
        try:
            min_entry_base_weight = max(0.0, float(self._config.get("induction_min_entry_base_weight", 0.001) or 0.0))
        except Exception:
            min_entry_base_weight = 0.001
        owner_structure_id_for_budget = str(structure_db.get("owner_structure_id", "") or "")
        diff_source, budget_debug = build_owner_runtime_candidate_view(
            entries=structure_db.get("diff_table", []),
            config=self._config,
            owner_structure_id=owner_structure_id_for_budget,
            path_kind="induction_local_targets",
            tick_id=tick_id,
        )
        if budget_debug.get("enabled", False):
            self._increment_runtime_metric(
                "owner_runtime_budget_selected_count",
                int(budget_debug.get("selected_count", 0) or 0),
            )
            self._increment_runtime_metric(
                "owner_runtime_budget_pruned_count",
                max(
                    0,
                    int(budget_debug.get("total_count", 0) or 0) - int(budget_debug.get("selected_count", 0) or 0),
                ),
            )
        for entry in diff_source:
            if float(entry.get("base_weight", 0.0) or 0.0) < min_entry_base_weight:
                debug["entry_pruned_by_base_weight_count"] += 1
                continue
            self._weight.decay_entry(entry, now_ms=now_ms, round_step=1)
            entry_weight = self._weight.entry_runtime_weight(entry)
            if entry_weight <= 0.0:
                continue
            entry_ext = dict(entry.get("ext", {}) or {})
            relation_type = str(entry_ext.get("relation_type", ""))
            entry_type = str(entry.get("entry_type", "structure_ref"))
            target_id = str(entry.get("target_id", ""))

            # Raw residual entries point to episodic memories rather than structures.
            if entry_type == "raw_residual" and relation_type == "stimulus_raw_residual":
                debug["raw_residual_entry_count"] += 1
                target_profile = self._resolve_entry_profile_cached(
                    entry=entry,
                    cut_engine=cut_engine,
                    structure_store=structure_store,
                )
                if not target_profile:
                    continue
                memory_refs = [str(memory_id) for memory_id in entry.get("memory_refs", []) if str(memory_id)]
                owner_structure_id = str(
                    entry_ext.get("context_owner_structure_id", "")
                    or structure_db.get("owner_structure_id", "")
                )
                target_profile = self._projection_profile_for_raw_residual(
                    target_profile=target_profile,
                    owner_structure_id=owner_structure_id,
                    entry=entry,
                    cut_engine=cut_engine,
                )
                if not target_profile:
                    continue
                exact_structure_candidates = self._select_existing_structure_candidates_for_raw_residual(
                    entry=entry,
                    target_profile=target_profile,
                    owner_structure_id=owner_structure_id,
                    structure_store=structure_store,
                    pointer_index=pointer_index,
                    cut_engine=cut_engine,
                )
                if exact_structure_candidates:
                    debug["raw_residual_entry_with_existing_structure_count"] += 1
                component_structure_candidates: list[dict] = []
                if not exact_structure_candidates:
                    component_structure_candidates = self._select_group_component_candidates_for_raw_residual(
                        entry=entry,
                        target_profile=target_profile,
                        owner_structure_id=owner_structure_id,
                        structure_store=structure_store,
                        pointer_index=pointer_index,
                        cut_engine=cut_engine,
                    )
                    if component_structure_candidates:
                        debug["raw_residual_entry_with_component_structure_count"] += 1
                structure_candidates = exact_structure_candidates or component_structure_candidates
                if (
                    not structure_candidates
                    and bool(self._config.get("residual_memory_as_structure_enabled", True))
                ):
                    structure_candidates = self._materialize_structure_candidate_for_raw_residual(
                        entry=entry,
                        target_profile=target_profile,
                        owner_structure_id=owner_structure_id,
                        memory_refs=memory_refs,
                        structure_store=structure_store,
                        pointer_index=pointer_index,
                        cut_engine=cut_engine,
                        trace_id=trace_id,
                        tick_id=tick_id,
                    )
                structure_route_kind = (
                    "exact"
                    if exact_structure_candidates
                    else ("component" if component_structure_candidates else ("materialized" if structure_candidates else ""))
                )
                residual_total_units = max(1, self._count_profile_units(target_profile))
                component_matched_unit_count = 0
                if component_structure_candidates:
                    matched_group_unit_map: dict[int, int] = {}
                    for candidate in component_structure_candidates:
                        group_indices = candidate.get("matched_group_indices", [])
                        group_unit_map = candidate.get("matched_group_unit_map", {})
                        if not isinstance(group_indices, list) or not isinstance(group_unit_map, dict):
                            continue
                        for raw_idx in group_indices:
                            try:
                                group_index = int(raw_idx)
                            except Exception:
                                continue
                            try:
                                unit_count = int(group_unit_map.get(group_index, 0) or 0)
                            except Exception:
                                unit_count = 0
                            if unit_count > 0:
                                matched_group_unit_map[group_index] = max(
                                    int(matched_group_unit_map.get(group_index, 0) or 0),
                                    unit_count,
                                )
                    component_matched_unit_count = sum(matched_group_unit_map.values())

                structure_share = 0.0
                if structure_candidates:
                    if bool(self._config.get("residual_memory_as_structure_enabled", True)):
                        structure_share = 1.0
                    else:
                        try:
                            structure_share = float(
                                self._config.get("induction_raw_residual_structure_share", 0.6) or 0.0
                            )
                        except Exception:
                            structure_share = 0.6
                        structure_share = max(0.0, min(1.0, structure_share))
                    if not memory_refs:
                        structure_share = 1.0
                    elif structure_route_kind == "component":
                        coverage_ratio = max(
                            0.0,
                            min(1.0, float(component_matched_unit_count) / float(max(1, residual_total_units))),
                        )
                        structure_share = max(0.0, min(1.0, structure_share * coverage_ratio))
                memory_share = (
                    0.0
                    if bool(self._config.get("residual_memory_as_structure_enabled", True))
                    else (1.0 - structure_share if memory_refs else 0.0)
                )
                if structure_candidates and structure_share > 0.0:
                    debug["raw_residual_structure_budget_weight"] += round(entry_weight * structure_share, 8)
                    if structure_route_kind == "exact":
                        debug["raw_residual_exact_structure_budget_weight"] += round(entry_weight * structure_share, 8)
                    elif structure_route_kind == "materialized":
                        debug["raw_residual_materialized_structure_budget_weight"] += round(entry_weight * structure_share, 8)
                    elif structure_route_kind == "component":
                        debug["raw_residual_component_structure_budget_weight"] += round(entry_weight * structure_share, 8)
                if memory_refs and memory_share > 0.0:
                    if structure_candidates:
                        debug["raw_residual_hit_memory_budget_weight"] += round(entry_weight * memory_share, 8)
                    else:
                        debug["raw_residual_miss_memory_budget_weight"] += round(entry_weight * memory_share, 8)

                if memory_refs and memory_share > 0.0:
                    shared_weight = (entry_weight * memory_share) / max(1, len(memory_refs))
                    for memory_id in memory_refs:
                        episodic_obj = episodic_store.get(memory_id)
                        if episodic_obj is None:
                            continue
                        bucket = targets.setdefault(
                            ("memory", memory_id),
                            {
                                "projection_kind": "memory",
                                "memory_id": memory_id,
                                "target_id": "",
                                "backing_structure_id": owner_structure_id,
                                "display_text": (
                                    str(entry.get("canonical_display_text", ""))
                                    or str(episodic_obj.get("meta", {}).get("ext", {}).get("display_text", ""))
                                    or str(episodic_obj.get("event_summary", ""))
                                    or memory_id
                                ),
                                "runtime_weight": 0.0,
                                "entry_count": 0,
                                "base_weight_weighted_sum": 0.0,
                                "recent_gain_weighted_sum": 0.0,
                                "fatigue_weighted_sum": 0.0,
                                "entries": [],
                                "structure_obj": None,
                                "target_profile": target_profile,
                                "relation_type": relation_type,
                                "owner_structure_id": owner_structure_id,
                                "raw_residual_memory_runtime_weight": 0.0,
                                "raw_residual_hit_memory_runtime_weight": 0.0,
                                "raw_residual_miss_memory_runtime_weight": 0.0,
                                "raw_residual_structure_runtime_weight": 0.0,
                                "raw_residual_exact_structure_runtime_weight": 0.0,
                                "raw_residual_component_structure_runtime_weight": 0.0,
                                "raw_residual_memory_refs": [],
                                "source_em_id": "",
                            },
                        )
                        bucket["runtime_weight"] += shared_weight
                        bucket["entry_count"] += 1
                        bucket["base_weight_weighted_sum"] += float(entry.get("base_weight", 0.0)) * shared_weight
                        bucket["recent_gain_weighted_sum"] += float(entry.get("recent_gain", 1.0)) * shared_weight
                        bucket["fatigue_weighted_sum"] += float(entry.get("fatigue", 0.0)) * shared_weight
                        bucket["raw_residual_memory_runtime_weight"] += shared_weight
                        if structure_candidates:
                            bucket["raw_residual_hit_memory_runtime_weight"] += shared_weight
                        else:
                            bucket["raw_residual_miss_memory_runtime_weight"] += shared_weight
                        bucket["entries"].append(
                            {
                                "entry": entry,
                                "entry_runtime_weight": shared_weight,
                            }
                        )
                        self._merge_bucket_residual_memory_refs(bucket, [memory_id])

                if structure_candidates and structure_share > 0.0:
                    if structure_route_kind == "exact":
                        debug["raw_residual_entry_routed_to_structure_count"] += 1
                        debug["raw_residual_existing_structure_target_count"] += len(structure_candidates)
                    elif structure_route_kind == "materialized":
                        debug["raw_residual_entry_materialized_structure_count"] += 1
                        debug["raw_residual_materialized_structure_target_count"] += len(structure_candidates)
                    elif structure_route_kind == "component":
                        debug["raw_residual_entry_routed_to_component_structure_count"] += 1
                        debug["raw_residual_component_structure_target_count"] += len(structure_candidates)
                    structure_weight_budget = entry_weight * structure_share
                    structure_score_total = sum(float(candidate.get("routing_score", 1.0)) for candidate in structure_candidates)
                    safe_structure_score_total = max(1e-8, structure_score_total)
                    for candidate in structure_candidates:
                        target_id = str(candidate.get("structure_id", ""))
                        if not target_id:
                            continue
                        target_structure = candidate.get("structure_obj")
                        if target_structure is None:
                            continue
                        candidate_weight = round(
                            structure_weight_budget * (float(candidate.get("routing_score", 1.0)) / safe_structure_score_total),
                            8,
                        )
                        if candidate_weight <= 0.0:
                            continue
                        target_display_text = (
                            str(target_structure.get("structure", {}).get("display_text", ""))
                            or str(entry.get("canonical_display_text", ""))
                            or target_id
                        )
                        bucket = targets.setdefault(
                            ("structure", target_id),
                            {
                                "projection_kind": "structure",
                                "memory_id": "",
                                "target_id": target_id,
                                "backing_structure_id": target_id,
                                "display_text": target_display_text,
                                "runtime_weight": 0.0,
                                "entry_count": 0,
                                "base_weight_weighted_sum": 0.0,
                                "recent_gain_weighted_sum": 0.0,
                                "fatigue_weighted_sum": 0.0,
                                "entries": [],
                                "structure_obj": target_structure,
                                "target_profile": target_profile,
                                "relation_type": relation_type,
                                "owner_structure_id": owner_structure_id,
                                "raw_residual_memory_runtime_weight": 0.0,
                                "raw_residual_hit_memory_runtime_weight": 0.0,
                                "raw_residual_miss_memory_runtime_weight": 0.0,
                                "raw_residual_structure_runtime_weight": 0.0,
                                "raw_residual_exact_structure_runtime_weight": 0.0,
                                "raw_residual_component_structure_runtime_weight": 0.0,
                                "raw_residual_memory_refs": [],
                                "source_em_id": "",
                            },
                        )
                        bucket["runtime_weight"] += candidate_weight
                        bucket["entry_count"] += 1
                        bucket["base_weight_weighted_sum"] += float(entry.get("base_weight", 0.0)) * candidate_weight
                        bucket["recent_gain_weighted_sum"] += float(entry.get("recent_gain", 1.0)) * candidate_weight
                        bucket["fatigue_weighted_sum"] += float(entry.get("fatigue", 0.0)) * candidate_weight
                        bucket["raw_residual_structure_runtime_weight"] += candidate_weight
                        if structure_route_kind == "exact":
                            bucket["raw_residual_exact_structure_runtime_weight"] += candidate_weight
                        elif structure_route_kind == "component":
                            bucket["raw_residual_component_structure_runtime_weight"] += candidate_weight
                        bucket["entries"].append(
                            {
                                "entry": entry,
                                "entry_runtime_weight": candidate_weight,
                            }
                        )
                        self._merge_bucket_residual_memory_refs(bucket, memory_refs)
                continue

            if not target_id:
                continue
            target_structure = structure_store.get(target_id)
            if not target_structure:
                continue
            if bool(self._config.get("induction_filter_nonprojectable_targets", True)):
                block_reason = classify_runtime_projection_block_reason(target_structure)
                if block_reason:
                    continue
            memory_id = str(entry_ext.get("anchor_memory_id", ""))
            projection_kind = "memory" if memory_id else "structure"
            target_key = memory_id if memory_id else target_id
            bucket_key = (projection_kind, target_key)
            target_display_text = (
                str(entry_ext.get("canonical_display_text", ""))
                or str(target_structure.get("structure", {}).get("display_text", target_id))
                or target_id
            )
            bucket = targets.setdefault(
                bucket_key,
                {
                    "projection_kind": projection_kind,
                    "memory_id": memory_id,
                    "target_id": target_id,
                    "backing_structure_id": target_id,
                    "display_text": target_display_text,
                    "runtime_weight": 0.0,
                    "entry_count": 0,
                    "base_weight_weighted_sum": 0.0,
                    "recent_gain_weighted_sum": 0.0,
                    "fatigue_weighted_sum": 0.0,
                    "entries": [],
                    "structure_obj": target_structure,
                    "target_profile": self._build_structure_profile_cached(
                        structure_obj=target_structure,
                        cut_engine=cut_engine,
                    ),
                    "relation_type": relation_type,
                    "owner_structure_id": str(
                        entry_ext.get("owner_structure_id", "")
                        or target_structure.get("structure", {}).get("ext", {}).get("owner_structure_id", "")
                    ),
                    "raw_residual_memory_runtime_weight": 0.0,
                    "raw_residual_hit_memory_runtime_weight": 0.0,
                    "raw_residual_miss_memory_runtime_weight": 0.0,
                    "raw_residual_structure_runtime_weight": 0.0,
                    "raw_residual_exact_structure_runtime_weight": 0.0,
                    "raw_residual_component_structure_runtime_weight": 0.0,
                    "raw_residual_memory_refs": [],
                    "source_em_id": "",
                },
            )
            bucket["runtime_weight"] += entry_weight
            bucket["entry_count"] += 1
            bucket["base_weight_weighted_sum"] += float(entry.get("base_weight", 0.0)) * entry_weight
            bucket["recent_gain_weighted_sum"] += float(entry.get("recent_gain", 1.0)) * entry_weight
            bucket["fatigue_weighted_sum"] += float(entry.get("fatigue", 0.0)) * entry_weight
            bucket["entries"].append(
                {
                    "entry": entry,
                    "entry_runtime_weight": entry_weight,
                }
            )
        return targets, debug

    def _projection_profile_for_raw_residual(
        self,
        *,
        target_profile: dict,
        owner_structure_id: str,
        entry: dict | None = None,
        cut_engine,
    ) -> dict:
        if not bool(self._config.get("induction_raw_residual_projection_drop_owner_placeholder_enabled", True)):
            return dict(target_profile or {})
        if not isinstance(target_profile, dict):
            return {}
        cache_enabled = bool(self._config.get("induction_raw_residual_static_cache_enabled", True)) and bool(
            self._config.get("induction_raw_residual_projection_profile_cache_enabled", True)
        )
        structure_store = self._current_structure_store
        cache_key = None
        if cache_enabled and structure_store is not None and isinstance(entry, dict):
            cache_key = self._raw_residual_static_cache_key(
                entry=entry,
                target_profile=target_profile,
                owner_structure_id=owner_structure_id,
                structure_store=structure_store,
                include_lookup_revision=False,
                extra=("projection_profile",),
            )
            cached_profile = self._get_runtime_or_shared_cache(
                "induction_raw_residual_projection_profile",
                cache_key,
                structure_store=structure_store,
            )
            if isinstance(cached_profile, dict):
                return cached_profile
        owner_structure = self._current_structure_store.get(owner_structure_id) if self._current_structure_store is not None and owner_structure_id else None
        if isinstance(owner_structure, dict):
            owner_profile = self._build_structure_profile_cached(structure_obj=owner_structure, cut_engine=cut_engine)
            owner_units = self._profile_units_for_subtraction(owner_profile)
            if owner_units:
                residual_units = self._subtract_profile_units(
                    target_profile=target_profile,
                    subtract_units=owner_units,
                )
                if residual_units:
                    profile = cut_engine.build_sequence_profile_from_groups(
                        [
                            {
                                "group_index": 0,
                                "source_type": "induction_raw_residual_projection",
                                "origin_frame_id": f"owner_residual::{owner_structure_id}",
                                "order_sensitive": False,
                                "units": residual_units,
                                "csa_bundles": [],
                            }
                        ]
                    )
                    ext = dict(profile.get("ext", {}) or {}) if isinstance(profile.get("ext", {}), dict) else {}
                    ext.update(
                        {
                            "raw_residual_projection_owner_profile_subtracted": True,
                            "raw_residual_projection_subtracted_owner_unit_count": int(len(owner_units)),
                            "raw_residual_projection_owner_structure_id": str(owner_structure_id or ""),
                        }
                    )
                    profile["ext"] = ext
                    if cache_key is not None and structure_store is not None:
                        self._set_runtime_and_shared_cache(
                            "induction_raw_residual_projection_profile",
                            cache_key,
                            profile,
                            structure_store=structure_store,
                        )
                        self._increment_runtime_metric("induction_raw_residual_projection_profile_cache_store_count")
                    return profile
        owner_marker = f"SELF[{str(owner_structure_id or '')}:"
        groups: list[dict] = []
        removed_count = 0
        for raw_group in list(target_profile.get("sequence_groups", []) or []):
            if not isinstance(raw_group, dict):
                continue
            next_units = []
            for raw_unit in list(raw_group.get("units", []) or []):
                if not isinstance(raw_unit, dict):
                    continue
                token = str(raw_unit.get("token", "") or "")
                if bool(raw_unit.get("is_placeholder", False)) and (not owner_structure_id or token.startswith(owner_marker)):
                    removed_count += 1
                    continue
                next_units.append(dict(raw_unit))
            if not next_units:
                continue
            next_group = dict(raw_group)
            next_group["units"] = next_units
            groups.append(next_group)
        if not groups:
            return {}
        profile = cut_engine.build_sequence_profile_from_groups(groups)
        ext = dict(profile.get("ext", {}) or {}) if isinstance(profile.get("ext", {}), dict) else {}
        ext.update(
            {
                "raw_residual_projection_owner_placeholder_dropped": bool(removed_count),
                "raw_residual_projection_dropped_placeholder_count": int(removed_count),
                "raw_residual_projection_owner_structure_id": str(owner_structure_id or ""),
            }
        )
        profile["ext"] = ext
        if cache_key is not None and structure_store is not None:
            self._set_runtime_and_shared_cache(
                "induction_raw_residual_projection_profile",
                cache_key,
                profile,
                structure_store=structure_store,
            )
            self._increment_runtime_metric("induction_raw_residual_projection_profile_cache_store_count")
        return profile

    @staticmethod
    def _profile_units_for_subtraction(profile: dict) -> list[dict]:
        units = []
        for group in list((profile or {}).get("sequence_groups", []) or []):
            if not isinstance(group, dict):
                continue
            for unit in list(group.get("units", []) or []):
                if not isinstance(unit, dict):
                    continue
                token = str(unit.get("token", "") or "")
                if not token or bool(unit.get("is_placeholder", False)):
                    continue
                units.append(unit)
        return units

    @staticmethod
    def _unit_subtraction_key(unit: dict) -> tuple[str, str]:
        role = str(unit.get("unit_role", "") or unit.get("role", "") or "feature")
        token = str(unit.get("token", "") or "")
        signature = str(unit.get("unit_signature", "") or "")
        if not signature:
            prefix = "A" if role == "attribute" else ("P" if role == "placeholder" else "F")
            signature = f"{prefix}:{token}"
        return signature, token

    def _subtract_profile_units(self, *, target_profile: dict, subtract_units: list[dict]) -> list[dict]:
        subtract_counts: dict[tuple[str, str], int] = {}
        for unit in subtract_units:
            key = self._unit_subtraction_key(unit)
            if not key[0] and not key[1]:
                continue
            subtract_counts[key] = int(subtract_counts.get(key, 0) or 0) + 1
        if not subtract_counts:
            return []
        residual_units = []
        for group in list((target_profile or {}).get("sequence_groups", []) or []):
            if not isinstance(group, dict):
                continue
            for unit in list(group.get("units", []) or []):
                if not isinstance(unit, dict):
                    continue
                if bool(unit.get("is_placeholder", False)):
                    continue
                key = self._unit_subtraction_key(unit)
                if subtract_counts.get(key, 0) > 0:
                    subtract_counts[key] = int(subtract_counts.get(key, 0) or 0) - 1
                    continue
                copied = dict(unit)
                copied["group_index"] = 0
                copied["sequence_index"] = len(residual_units)
                residual_units.append(copied)
        return residual_units

    def _materialize_structure_candidate_for_raw_residual(
        self,
        *,
        entry: dict,
        target_profile: dict,
        owner_structure_id: str,
        memory_refs: list[str],
        structure_store,
        pointer_index,
        cut_engine,
        trace_id: str,
        tick_id: str,
    ) -> list[dict]:
        canonical_display_text = str(
            target_profile.get("display_text", "")
            or entry.get("canonical_display_text", "")
            or entry.get("display_text", "")
            or target_profile.get("content_signature", "")
        ).strip()
        residual_total_units = max(1, self._count_profile_units(target_profile))
        profile_ext = dict(target_profile.get("ext", {}) or {}) if isinstance(target_profile.get("ext", {}), dict) else {}
        context_free_identity = bool(
            self._config.get("induction_raw_residual_materialized_structure_context_free_identity_enabled", True)
        )
        if context_free_identity:
            for key in ("context_ref_object_id", "context_ref_object_type", "context_owner_structure_id", "context_path_ids"):
                profile_ext.pop(key, None)
        else:
            profile_ext.update(
                {
                    "context_owner_structure_id": owner_structure_id,
                    "context_ref_object_id": owner_structure_id,
                    "context_ref_object_type": "st" if owner_structure_id else str(profile_ext.get("context_ref_object_type", "") or ""),
                }
            )
        profile_ext.update(
            {
                "residual_memory_as_structure": True,
                "residual_origin_kind": "stimulus_raw_residual_materialized_structure",
                "raw_residual_memory_refs": list(memory_refs or []),
                "growth_projection_owner_is_provenance_only": context_free_identity,
                "provenance_owner_structure_id": owner_structure_id if context_free_identity else "",
            }
        )
        if memory_refs:
            profile_ext.setdefault("source_em_id", str(memory_refs[0]))
            profile_ext.setdefault("memory_id", str(memory_refs[0]))
        result = shared_resolve_or_create_structure_from_profile(
            profile={
                **dict(target_profile),
                "display_text": canonical_display_text,
                "ext": profile_ext,
            },
            structure_store=structure_store,
            pointer_index=pointer_index,
            cut_engine=cut_engine,
            trace_id=f"{trace_id}_raw_residual_materialize",
            tick_id=tick_id,
            confidence=0.72,
            origin="stimulus_raw_residual_materialize",
            origin_id=str(
                target_profile.get("content_signature", "")
                or entry.get("canonical_content_signature", "")
                or entry.get("content_signature", "")
                or canonical_display_text
            ),
            parent_ids=[] if context_free_identity else ([owner_structure_id] if owner_structure_id else []),
            ext=profile_ext,
            source_interface="run_induction_propagation",
            strict_context_owner_match=False if context_free_identity else bool(owner_structure_id),
            require_context_free=context_free_identity,
        )
        created_structure = result.get("structure") if isinstance(result, dict) else None
        if not isinstance(created_structure, dict):
            return []
        if bool(self._config.get("induction_filter_nonprojectable_targets", True)) and classify_runtime_projection_block_reason(created_structure):
            return []
        self._ensure_owner_materialized_structure_entry(
            owner_structure_id=owner_structure_id,
            target_structure=created_structure,
            target_profile=target_profile,
            entry=entry,
            memory_refs=memory_refs,
            structure_store=structure_store,
        )
        return [
            self._build_raw_residual_structure_candidate(
                candidate_id=str(created_structure.get("id", "") or ""),
                target_structure=created_structure,
                owner_structure_id=owner_structure_id,
                canonical_display_text=canonical_display_text,
                order=0,
                matched_unit_count=residual_total_units,
                matched_unit_ratio=1.0,
                route_kind="exact",
            )
        ]

    def _select_existing_structure_candidates_for_raw_residual(
        self,
        *,
        entry: dict,
        target_profile: dict,
        owner_structure_id: str,
        structure_store,
        pointer_index,
        cut_engine,
    ) -> list[dict]:
        if not bool(self._config.get("induction_raw_residual_existing_structure_projection_enabled", True)):
            return []
        cache_enabled = bool(self._config.get("induction_raw_residual_static_cache_enabled", True)) and bool(
            self._config.get("induction_raw_residual_candidate_static_cache_enabled", False)
        )
        cache_key = None
        if cache_enabled:
            cache_key = self._raw_residual_static_cache_key(
                entry=entry,
                target_profile=target_profile,
                owner_structure_id=owner_structure_id,
                structure_store=structure_store,
                extra=("exact_candidates",),
            )
            cached_candidates = self._get_runtime_or_shared_cache(
                "induction_raw_residual_exact_candidates",
                cache_key,
                structure_store=structure_store,
            )
            if isinstance(cached_candidates, list):
                return list(cached_candidates)
        signature = str(
            target_profile.get("content_signature", "")
            or entry.get("canonical_content_signature", "")
            or entry.get("content_signature", "")
        )
        if not signature:
            return []
        try:
            top_k = int(self._config.get("induction_raw_residual_structure_target_top_k", 1) or 0)
        except Exception:
            top_k = 1
        top_k = max(0, top_k)
        canonical_display_text = str(entry.get("canonical_display_text", "") or entry.get("display_text", ""))
        candidates = []
        residual_total_units = max(1, self._count_profile_units(target_profile))
        for order, candidate_id in enumerate(pointer_index.query_candidates_by_signature(signature)):
            if not candidate_id or candidate_id == owner_structure_id:
                continue
            target_structure = structure_store.get(candidate_id)
            if target_structure is None:
                continue
            if not self._raw_residual_candidate_matches_owner_context(
                target_structure=target_structure,
                owner_structure_id=owner_structure_id,
            ):
                continue
            if bool(self._config.get("induction_filter_nonprojectable_targets", True)):
                if classify_runtime_projection_block_reason(target_structure):
                    continue
            candidates.append(
                self._build_raw_residual_structure_candidate(
                    candidate_id=candidate_id,
                    target_structure=target_structure,
                    owner_structure_id=owner_structure_id,
                    canonical_display_text=canonical_display_text,
                    order=order,
                    matched_unit_count=residual_total_units,
                    matched_unit_ratio=1.0,
                    route_kind="exact",
                )
            )
        candidates.sort(key=lambda item: item.get("sort_key", (0, 0, 0, 999, 999)))
        if top_k > 0:
            candidates = candidates[:top_k]
        if cache_key is not None:
            self._set_runtime_and_shared_cache(
                "induction_raw_residual_exact_candidates",
                cache_key,
                list(candidates),
                structure_store=structure_store,
            )
            self._increment_runtime_metric("induction_raw_residual_exact_candidates_cache_store_count")
        return candidates

    def _select_group_component_candidates_for_raw_residual(
        self,
        *,
        entry: dict,
        target_profile: dict,
        owner_structure_id: str,
        structure_store,
        pointer_index,
        cut_engine,
    ) -> list[dict]:
        if not bool(self._config.get("induction_raw_residual_group_component_projection_enabled", True)):
            return []
        sequence_groups = list(target_profile.get("sequence_groups", []))
        if not sequence_groups:
            return []
        cache_enabled = bool(self._config.get("induction_raw_residual_static_cache_enabled", True)) and bool(
            self._config.get("induction_raw_residual_candidate_static_cache_enabled", False)
        )
        cache_key = None
        if cache_enabled:
            cache_key = self._raw_residual_static_cache_key(
                entry=entry,
                target_profile=target_profile,
                owner_structure_id=owner_structure_id,
                structure_store=structure_store,
                extra=("component_candidates",),
            )
            cached_candidates = self._get_runtime_or_shared_cache(
                "induction_raw_residual_component_candidates",
                cache_key,
                structure_store=structure_store,
            )
            if isinstance(cached_candidates, list):
                return list(cached_candidates)
        try:
            top_k = int(self._config.get("induction_raw_residual_component_target_top_k", 3) or 0)
        except Exception:
            top_k = 3
        try:
            min_group_units = int(self._config.get("induction_raw_residual_component_min_group_units", 3) or 0)
        except Exception:
            min_group_units = 3
        top_k = max(0, top_k)
        min_group_units = max(1, min_group_units)
        residual_total_units = max(1, self._count_profile_units(target_profile))
        aggregated: dict[str, dict] = {}
        for group_index, raw_group in enumerate(sequence_groups):
            if not isinstance(raw_group, dict):
                continue
            group = dict(raw_group)
            group_units = self._count_sequence_group_units(group)
            if group_units < min_group_units:
                continue
            group_profile = cut_engine.build_sequence_profile_from_groups([group])
            group_signature = str(
                group_profile.get("content_signature", "")
                or group.get("group_signature", "")
                or group.get("content_signature", "")
            )
            if not group_signature:
                continue
            component_display_text = str(
                group_profile.get("display_text", "")
                or group.get("string_token_text", "")
                or group.get("display_text", "")
            )
            best_candidate = None
            best_sort_key = None
            best_score = -1.0
            for order, candidate_id in enumerate(pointer_index.query_candidates_by_signature(group_signature)):
                if not candidate_id or candidate_id == owner_structure_id:
                    continue
                target_structure = structure_store.get(candidate_id)
                if target_structure is None:
                    continue
                if not self._raw_residual_candidate_matches_owner_context(
                    target_structure=target_structure,
                    owner_structure_id=owner_structure_id,
                ):
                    continue
                if bool(self._config.get("induction_filter_nonprojectable_targets", True)):
                    if classify_runtime_projection_block_reason(target_structure):
                        continue
                candidate = self._build_raw_residual_structure_candidate(
                    candidate_id=candidate_id,
                    target_structure=target_structure,
                    owner_structure_id=owner_structure_id,
                    canonical_display_text=component_display_text,
                    order=order,
                    matched_unit_count=group_units,
                    matched_unit_ratio=float(group_units) / float(max(1, residual_total_units)),
                    route_kind="component",
                    component_group_count=1,
                )
                candidate_score = float(candidate.get("routing_score", 1.0))
                candidate_sort_key = candidate.get("sort_key", (0, 0, 0, 999, 999))
                if (
                    best_candidate is None
                    or candidate_score > best_score
                    or (candidate_score == best_score and candidate_sort_key < best_sort_key)
                ):
                    best_candidate = candidate
                    best_score = candidate_score
                    best_sort_key = candidate_sort_key
            if best_candidate is None:
                continue
            structure_id = str(best_candidate.get("structure_id", ""))
            if not structure_id:
                continue
            bucket = aggregated.setdefault(
                structure_id,
                {
                    "structure_id": structure_id,
                    "structure_obj": best_candidate.get("structure_obj"),
                    "routing_score": 0.0,
                    "matched_unit_count": 0,
                    "matched_group_count": 0,
                    "matched_group_indices": [],
                    "matched_group_unit_map": {},
                    "route_kind": "component",
                    "sort_key": best_candidate.get("sort_key", (0, 0, 0, 999, 999)),
                },
            )
            bucket["routing_score"] += float(best_candidate.get("routing_score", 1.0)) * float(group_units)
            bucket["matched_unit_count"] += int(group_units)
            bucket["matched_group_count"] += 1
            bucket["matched_group_indices"].append(group_index)
            bucket["matched_group_unit_map"][group_index] = int(group_units)
            bucket["matched_unit_ratio"] = round(
                float(bucket["matched_unit_count"]) / float(max(1, residual_total_units)),
                8,
            )
            bucket["sort_key"] = min(
                bucket.get("sort_key", (0, 0, 0, 999, 999)),
                best_candidate.get("sort_key", (0, 0, 0, 999, 999)),
            )
        candidates = list(aggregated.values())
        candidates.sort(
            key=lambda item: (
                -int(item.get("matched_unit_count", 0)),
                -int(item.get("matched_group_count", 0)),
                -float(item.get("routing_score", 0.0)),
                item.get("sort_key", (0, 0, 0, 999, 999)),
            )
        )
        if top_k > 0:
            candidates = candidates[:top_k]
        if cache_key is not None:
            self._set_runtime_and_shared_cache(
                "induction_raw_residual_component_candidates",
                cache_key,
                list(candidates),
                structure_store=structure_store,
            )
            self._increment_runtime_metric("induction_raw_residual_component_candidates_cache_store_count")
        return candidates

    @staticmethod
    def _count_sequence_group_units(group: dict) -> int:
        units = group.get("units", [])
        return len(units) if isinstance(units, list) else 0

    def _count_profile_units(self, profile: dict) -> int:
        try:
            token_count = int(profile.get("token_count", 0) or 0)
        except Exception:
            token_count = 0
        if token_count > 0:
            return token_count
        total_units = 0
        for raw_group in profile.get("sequence_groups", []):
            if not isinstance(raw_group, dict):
                continue
            total_units += self._count_sequence_group_units(raw_group)
        return total_units

    def _build_raw_residual_structure_candidate(
        self,
        *,
        candidate_id: str,
        target_structure: dict,
        owner_structure_id: str,
        canonical_display_text: str,
        order: int,
        matched_unit_count: int,
        matched_unit_ratio: float,
        route_kind: str,
        component_group_count: int = 0,
    ) -> dict:
        context_meta = extract_context_metadata(target_structure)
        context_path_ids = normalize_id_list(
            context_meta.get("context_path_ids", [])
            or target_structure.get("source", {}).get("parent_ids", [])
        )
        candidate_owner_structure_id = str(
            context_meta.get("context_owner_structure_id", "")
            or target_structure.get("structure", {}).get("ext", {}).get("owner_structure_id", "")
        )
        target_display_text = str(target_structure.get("structure", {}).get("display_text", "") or candidate_id)
        owner_exact = bool(owner_structure_id and candidate_owner_structure_id == owner_structure_id)
        path_contains_owner = bool(owner_structure_id and owner_structure_id in context_path_ids)
        display_exact = bool(canonical_display_text and target_display_text == canonical_display_text)
        routing_score = 1.0
        if owner_exact:
            routing_score += 0.8
        if path_contains_owner:
            routing_score += 0.45
        if display_exact:
            routing_score += 0.2
        return {
            "structure_id": candidate_id,
            "structure_obj": target_structure,
            "routing_score": routing_score,
            "matched_unit_count": int(max(0, matched_unit_count)),
            "matched_unit_ratio": round(max(0.0, matched_unit_ratio), 8),
            "matched_group_count": int(max(0, component_group_count)),
            "route_kind": str(route_kind or "exact"),
            "sort_key": (
                -int(owner_exact),
                -int(path_contains_owner),
                -int(display_exact),
                len(context_path_ids) if context_path_ids else 999,
                order,
            ),
        }

    @staticmethod
    def _raw_residual_candidate_matches_owner_context(*, target_structure: dict, owner_structure_id: str) -> bool:
        if not owner_structure_id:
            return True
        if not has_context_metadata(target_structure):
            return True
        context_meta = extract_context_metadata(target_structure)
        candidate_owner_structure_id = str(
            context_meta.get("context_owner_structure_id", "")
            or target_structure.get("structure", {}).get("ext", {}).get("owner_structure_id", "")
            or ""
        )
        return candidate_owner_structure_id == owner_structure_id

    def _ensure_owner_materialized_structure_entry(
        self,
        *,
        owner_structure_id: str,
        target_structure: dict,
        target_profile: dict,
        entry: dict,
        memory_refs: list[str],
        structure_store,
    ) -> None:
        if not owner_structure_id or not isinstance(target_structure, dict):
            return
        structure_id = str(target_structure.get("id", "") or "")
        if not structure_id or structure_id == owner_structure_id:
            return
        structure_store.add_diff_entry(
            owner_structure_id,
            target_id=structure_id,
            content_signature=str(target_structure.get("structure", {}).get("content_signature", "") or ""),
            base_weight=max(0.0, float(entry.get("base_weight", 0.0) or 0.0)),
            residual_existing_signature="",
            residual_incoming_signature=str(target_profile.get("content_signature", "") or ""),
            ext={
                "relation_type": "stimulus_raw_residual_materialized_structure",
                "kind": "stimulus_raw_residual_materialized_structure",
                "grouped_display_text": str(target_profile.get("display_text", "") or entry.get("canonical_display_text", "") or ""),
                "memory_refs": list(memory_refs or []),
                "source_em_id": str(memory_refs[0]) if memory_refs else "",
                "context_owner_structure_id": owner_structure_id,
                "context_ref_object_id": owner_structure_id,
                "context_ref_object_type": "st",
            },
        )

    @staticmethod
    def _build_target_debug_entry(*, target: dict, total_weight: float, delta_ev: float) -> dict:
        runtime_weight = float(target.get("runtime_weight", 0.0))
        entry_count = int(target.get("entry_count", 0))
        safe_total_weight = max(1e-8, float(total_weight))
        safe_runtime_weight = max(1e-8, runtime_weight)
        raw_residual_memory_runtime_weight = float(target.get("raw_residual_memory_runtime_weight", 0.0))
        raw_residual_hit_memory_runtime_weight = float(target.get("raw_residual_hit_memory_runtime_weight", 0.0))
        raw_residual_miss_memory_runtime_weight = float(target.get("raw_residual_miss_memory_runtime_weight", 0.0))
        raw_residual_structure_runtime_weight = float(target.get("raw_residual_structure_runtime_weight", 0.0))
        raw_residual_exact_structure_runtime_weight = float(target.get("raw_residual_exact_structure_runtime_weight", 0.0))
        raw_residual_component_structure_runtime_weight = float(target.get("raw_residual_component_structure_runtime_weight", 0.0))
        raw_residual_total_runtime_weight = (
            raw_residual_memory_runtime_weight + raw_residual_structure_runtime_weight
        )
        raw_residual_hit_total_runtime_weight = (
            raw_residual_hit_memory_runtime_weight + raw_residual_structure_runtime_weight
        )
        non_raw_runtime_weight = max(0.0, runtime_weight - raw_residual_total_runtime_weight)
        return {
            "runtime_weight": round(runtime_weight, 8),
            "delta_ev": round(float(delta_ev), 8),
            "entry_count": entry_count,
            "normalized_share": round(runtime_weight / safe_total_weight, 8),
            "base_weight": round(float(target.get("base_weight_weighted_sum", 0.0)) / safe_runtime_weight, 8),
            "recent_gain": round(float(target.get("recent_gain_weighted_sum", 0.0)) / safe_runtime_weight, 8),
            "fatigue": round(float(target.get("fatigue_weighted_sum", 0.0)) / safe_runtime_weight, 8),
            "raw_residual_memory_runtime_weight": round(raw_residual_memory_runtime_weight, 8),
            "raw_residual_hit_memory_runtime_weight": round(raw_residual_hit_memory_runtime_weight, 8),
            "raw_residual_miss_memory_runtime_weight": round(raw_residual_miss_memory_runtime_weight, 8),
            "raw_residual_structure_runtime_weight": round(raw_residual_structure_runtime_weight, 8),
            "raw_residual_exact_structure_runtime_weight": round(raw_residual_exact_structure_runtime_weight, 8),
            "raw_residual_component_structure_runtime_weight": round(raw_residual_component_structure_runtime_weight, 8),
            "raw_residual_total_runtime_weight": round(raw_residual_total_runtime_weight, 8),
            "non_raw_runtime_weight": round(non_raw_runtime_weight, 8),
            "raw_residual_memory_share": round(raw_residual_memory_runtime_weight / safe_runtime_weight, 8),
            "raw_residual_hit_memory_share": round(raw_residual_hit_memory_runtime_weight / safe_runtime_weight, 8),
            "raw_residual_miss_memory_share": round(raw_residual_miss_memory_runtime_weight / safe_runtime_weight, 8),
            "raw_residual_structure_share": round(raw_residual_structure_runtime_weight / safe_runtime_weight, 8),
            "raw_residual_exact_structure_share": round(raw_residual_exact_structure_runtime_weight / safe_runtime_weight, 8),
            "raw_residual_component_structure_share": round(raw_residual_component_structure_runtime_weight / safe_runtime_weight, 8),
            "raw_residual_total_share": round(raw_residual_total_runtime_weight / safe_runtime_weight, 8),
            "non_raw_share": round(non_raw_runtime_weight / safe_runtime_weight, 8),
            "raw_residual_hit_path_structure_share": round(
                raw_residual_structure_runtime_weight / max(1e-8, raw_residual_hit_total_runtime_weight),
                8,
            )
            if raw_residual_hit_total_runtime_weight > 0.0
            else 0.0,
        }

    def _filter_full_inclusion_targets(
        self,
        *,
        source_structure_id: str,
        source_structure_ids: list[str] | None = None,
        source_profile: dict,
        aggregated_targets: dict[str, dict],
        cut_engine,
    ) -> dict[str, dict]:
        eligible = {}
        source_structure_id_set = {
            str(candidate_id or "").strip()
            for candidate_id in ([source_structure_id] + list(source_structure_ids or []))
            if str(candidate_id or "").strip()
        }
        source_signature = source_profile.get("content_signature", "")
        source_unit_count = int(source_profile.get("unit_count", 0) or 0)
        source_flat_tokens = [str(token) for token in (source_profile.get("flat_tokens", []) or []) if str(token)]
        source_token_count = int(source_profile.get("token_count", len(source_flat_tokens)) or len(source_flat_tokens))
        source_token_counter = Counter(source_flat_tokens)
        inclusion_cache = None
        if isinstance(self._runtime_cache, dict):
            inclusion_cache = self._runtime_cache.setdefault("full_inclusion_checks", {})
        for target_key, payload in aggregated_targets.items():
            target_id = str(payload.get("target_id", "") or "").strip()
            if (
                str(payload.get("projection_kind", "structure") or "structure") == "structure"
                and target_id
                and target_id in source_structure_id_set
            ):
                continue
            if self._relation_type_allows_context_residual_candidate(str(payload.get("relation_type", ""))):
                if not source_structure_id_set or str(payload.get("owner_structure_id", "")) in source_structure_id_set:
                    eligible[target_key] = payload
                continue
            target_profile = payload.get("target_profile", {})
            if not target_profile:
                target_structure = payload.get("structure_obj")
                if not target_structure:
                    continue
                target_profile = self._build_structure_profile_cached(
                    structure_obj=target_structure,
                    cut_engine=cut_engine,
                )
                payload["target_profile"] = target_profile
            target_unit_count = int(target_profile.get("unit_count", 0) or 0)
            if source_unit_count > 0 and target_unit_count > 0 and target_unit_count < source_unit_count:
                continue
            target_flat_tokens = [str(token) for token in (target_profile.get("flat_tokens", []) or []) if str(token)]
            target_token_count = int(target_profile.get("token_count", len(target_flat_tokens)) or len(target_flat_tokens))
            if source_token_count > 0 and target_token_count > 0 and target_token_count < source_token_count:
                continue
            if source_token_counter:
                cached_counter = payload.get("target_flat_token_counter")
                if isinstance(cached_counter, dict):
                    target_token_counter = Counter({str(key): int(value) for key, value in cached_counter.items() if str(key)})
                else:
                    target_token_counter = Counter(target_flat_tokens)
                    payload["target_flat_token_counter"] = dict(target_token_counter)
                missing = False
                for token, required_count in source_token_counter.items():
                    if int(target_token_counter.get(token, 0) or 0) < int(required_count):
                        missing = True
                        break
                if missing:
                    continue
            target_signature = str(target_profile.get("content_signature", "") or "")
            inclusion_cache_key = (
                self._profile_fingerprint(source_profile),
                self._profile_fingerprint(target_profile),
            )
            included = None
            if isinstance(inclusion_cache, dict):
                included = inclusion_cache.get(inclusion_cache_key)
            shared_inclusion_cache_enabled = bool(
                self._config.get("induction_full_inclusion_shared_cache_enabled", True)
            )
            structure_store = self._current_structure_store
            if included is None and shared_inclusion_cache_enabled and structure_store is not None:
                shared_included = self._get_runtime_or_shared_cache(
                    "induction_full_inclusion_checks",
                    inclusion_cache_key,
                    structure_store=structure_store,
                )
                if isinstance(shared_included, bool):
                    included = bool(shared_included)
            if included is None:
                included = self._profile_exact_full_inclusion(
                    source_profile=source_profile,
                    target_profile=target_profile,
                )
                if not included:
                    common_part = cut_engine.maximum_common_part(
                        source_profile.get("sequence_groups", []),
                        target_profile.get("sequence_groups", []),
                    )
                    included = bool(
                        common_part.get("common_signature", "") == source_signature
                        and not common_part.get("residual_existing_signature", "")
                    )
                if isinstance(inclusion_cache, dict):
                    inclusion_cache[inclusion_cache_key] = bool(included)
                if shared_inclusion_cache_enabled and structure_store is not None:
                    self._set_runtime_and_shared_cache(
                        "induction_full_inclusion_checks",
                        inclusion_cache_key,
                        bool(included),
                        structure_store=structure_store,
                    )
                    self._increment_runtime_metric("induction_full_inclusion_shared_cache_store_count")
            if not included:
                continue
            eligible[target_key] = payload
        return eligible

    @staticmethod
    def _relation_type_allows_context_residual_candidate(relation_type: str) -> bool:
        return str(relation_type or "").strip() in {
            "residual_context",
            "residual_context_common",
            "structure_raw_residual",
            "stimulus_raw_residual",
            "stimulus_raw_residual_materialized_structure",
        }

    @classmethod
    def _profile_exact_full_inclusion(cls, *, source_profile: dict, target_profile: dict) -> bool:
        source_groups = [group for group in list(source_profile.get("sequence_groups", []) or []) if isinstance(group, dict)]
        target_groups = [group for group in list(target_profile.get("sequence_groups", []) or []) if isinstance(group, dict)]
        if not source_groups or not target_groups:
            return False
        target_start = 0
        for source_group in source_groups:
            if cls._group_has_bundle_projection(source_group):
                return False
            source_order_sensitive = bool(source_group.get("order_sensitive", False))
            source_signatures = cls._group_unit_signatures(source_group)
            if not source_signatures:
                return False
            matched = False
            for target_index in range(target_start, len(target_groups)):
                target_group = target_groups[target_index]
                if cls._group_has_bundle_projection(target_group):
                    continue
                if bool(target_group.get("order_sensitive", False)) != source_order_sensitive:
                    continue
                target_signatures = cls._group_unit_signatures(target_group)
                if source_order_sensitive:
                    group_included = cls._signature_subsequence_included(source_signatures, target_signatures)
                else:
                    group_included = cls._signature_multiset_included(source_signatures, target_signatures)
                if not group_included:
                    continue
                matched = True
                target_start = target_index + 1
                break
            if not matched:
                return False
        return True

    @staticmethod
    def _group_unit_signatures(group: dict) -> list[str]:
        signatures = [
            str(signature)
            for signature in list(group.get("unit_signatures", []) or [])
            if str(signature)
        ]
        if signatures:
            return signatures
        return [
            str(unit.get("unit_signature", "") or "")
            for unit in list(group.get("units", []) or [])
            if isinstance(unit, dict) and str(unit.get("unit_signature", "") or "")
        ]

    @staticmethod
    def _group_has_bundle_projection(group: dict) -> bool:
        if list(group.get("csa_bundles", []) or []):
            return True
        if list(group.get("bundle_signatures", []) or []):
            return True
        for unit in list(group.get("units", []) or []):
            if not isinstance(unit, dict):
                continue
            if (
                str(unit.get("bundle_id", "") or "")
                or str(unit.get("bundle_signature", "") or "")
                or str(unit.get("bundle_anchor_unit_id", "") or "")
                or list(unit.get("bundle_member_unit_ids", []) or [])
            ):
                return True
        return False

    @staticmethod
    def _signature_multiset_included(source_signatures: list[str], target_signatures: list[str]) -> bool:
        if not source_signatures:
            return False
        target_counter = Counter(target_signatures)
        for signature, required_count in Counter(source_signatures).items():
            if int(target_counter.get(signature, 0) or 0) < int(required_count):
                return False
        return True

    @staticmethod
    def _signature_subsequence_included(source_signatures: list[str], target_signatures: list[str]) -> bool:
        if not source_signatures:
            return False
        pos = 0
        for signature in target_signatures:
            if signature == source_signatures[pos]:
                pos += 1
                if pos >= len(source_signatures):
                    return True
        return False

    def _mark_bucket_entries(
        self,
        *,
        entry_items: list[dict],
        total_weight: float,
        delta_er: float,
        delta_ev: float,
        now_ms: int,
    ) -> None:
        if total_weight <= 0.0:
            return
        for item in entry_items:
            entry = item.get("entry")
            entry_weight = float(item.get("entry_runtime_weight", 0.0))
            if not entry or entry_weight <= 0.0:
                continue
            ratio = entry_weight / total_weight
            self._weight.mark_entry_activation(
                entry,
                delta_er=round(delta_er * ratio, 8),
                delta_ev=round(delta_ev * ratio, 8),
                match_score=entry_weight,
                now_ms=now_ms,
            )

    @staticmethod
    def _append_target_delta(
        *,
        induction_targets: dict,
        projection_kind: str,
        memory_id: str,
        target_id: str,
        backing_structure_id: str,
        target_display_text: str,
        mode: str,
        source_structure_id: str,
        delta_ev: float,
        runtime_weight: float,
        raw_residual_memory_delta_ev: float = 0.0,
        raw_residual_hit_memory_delta_ev: float = 0.0,
        raw_residual_miss_memory_delta_ev: float = 0.0,
        raw_residual_structure_delta_ev: float = 0.0,
        raw_residual_exact_structure_delta_ev: float = 0.0,
        raw_residual_component_structure_delta_ev: float = 0.0,
        raw_residual_memory_refs: list[str] | None = None,
        source_em_id: str = "",
        energy_graph_round: int | None = None,
        energy_graph_depth: int | None = None,
        frontier_source_kind: str = "",
    ) -> None:
        stable_id = memory_id if projection_kind == "memory" and memory_id else target_id
        key = (projection_kind, stable_id, mode)
        payload = induction_targets.setdefault(
            key,
            {
                "projection_kind": projection_kind,
                "memory_id": memory_id,
                "target_structure_id": target_id,
                "backing_structure_id": backing_structure_id or target_id,
                "target_display_text": target_display_text,
                "delta_ev": 0.0,
                "raw_residual_memory_delta_ev": 0.0,
                "raw_residual_hit_memory_delta_ev": 0.0,
                "raw_residual_miss_memory_delta_ev": 0.0,
                "raw_residual_structure_delta_ev": 0.0,
                "raw_residual_exact_structure_delta_ev": 0.0,
                "raw_residual_component_structure_delta_ev": 0.0,
                "raw_residual_memory_refs": [],
                "source_em_id": "",
                "sources": [],
                "mode": mode,
                "runtime_weight": runtime_weight,
                "energy_graph_round_first": int(energy_graph_round or 0),
                "energy_graph_round_last": int(energy_graph_round or 0),
                "energy_graph_depth_min": int(energy_graph_depth or 0),
                "energy_graph_depth_max": int(energy_graph_depth or 0),
                "energy_graph_emit_count": 0,
                "frontier_source_kinds": [],
            },
        )
        payload["delta_ev"] = round(float(payload.get("delta_ev", 0.0)) + float(delta_ev), 8)
        payload["raw_residual_memory_delta_ev"] = round(
            float(payload.get("raw_residual_memory_delta_ev", 0.0)) + float(raw_residual_memory_delta_ev),
            8,
        )
        payload["raw_residual_hit_memory_delta_ev"] = round(
            float(payload.get("raw_residual_hit_memory_delta_ev", 0.0)) + float(raw_residual_hit_memory_delta_ev),
            8,
        )
        payload["raw_residual_miss_memory_delta_ev"] = round(
            float(payload.get("raw_residual_miss_memory_delta_ev", 0.0)) + float(raw_residual_miss_memory_delta_ev),
            8,
        )
        payload["raw_residual_structure_delta_ev"] = round(
            float(payload.get("raw_residual_structure_delta_ev", 0.0)) + float(raw_residual_structure_delta_ev),
            8,
        )
        payload["raw_residual_exact_structure_delta_ev"] = round(
            float(payload.get("raw_residual_exact_structure_delta_ev", 0.0)) + float(raw_residual_exact_structure_delta_ev),
            8,
        )
        payload["raw_residual_component_structure_delta_ev"] = round(
            float(payload.get("raw_residual_component_structure_delta_ev", 0.0)) + float(raw_residual_component_structure_delta_ev),
            8,
        )
        merged_memory_refs = [str(item) for item in payload.get("raw_residual_memory_refs", []) if str(item)]
        for memory_ref in raw_residual_memory_refs or []:
            memory_ref_text = str(memory_ref)
            if memory_ref_text and memory_ref_text not in merged_memory_refs:
                merged_memory_refs.append(memory_ref_text)
        payload["raw_residual_memory_refs"] = merged_memory_refs
        if source_em_id and not str(payload.get("source_em_id", "")).strip():
            payload["source_em_id"] = str(source_em_id)
        payload["sources"].append(source_structure_id)
        payload["energy_graph_emit_count"] = int(payload.get("energy_graph_emit_count", 0) or 0) + 1
        if energy_graph_round is not None:
            current_first = int(payload.get("energy_graph_round_first", energy_graph_round) or energy_graph_round)
            current_last = int(payload.get("energy_graph_round_last", energy_graph_round) or energy_graph_round)
            payload["energy_graph_round_first"] = min(current_first, int(energy_graph_round))
            payload["energy_graph_round_last"] = max(current_last, int(energy_graph_round))
        if energy_graph_depth is not None:
            current_min = int(payload.get("energy_graph_depth_min", energy_graph_depth) or energy_graph_depth)
            current_max = int(payload.get("energy_graph_depth_max", energy_graph_depth) or energy_graph_depth)
            payload["energy_graph_depth_min"] = min(current_min, int(energy_graph_depth))
            payload["energy_graph_depth_max"] = max(current_max, int(energy_graph_depth))
        if frontier_source_kind:
            payload.setdefault("frontier_source_kinds", []).append(str(frontier_source_kind))

    @staticmethod
    def _resolve_entry_profile(*, entry: dict, cut_engine, structure_store) -> dict:
        canonical_groups = list(entry.get("canonical_sequence_groups", []))
        if canonical_groups:
            return cut_engine.build_sequence_profile_from_groups(canonical_groups)
        display_text = str(entry.get("canonical_display_text", "") or entry.get("display_text", ""))
        sequence_groups = list(entry.get("sequence_groups", []))
        if not sequence_groups:
            return {}
        profile = cut_engine.build_sequence_profile_from_groups(sequence_groups)
        if display_text:
            profile["display_text"] = display_text
        return profile

    @staticmethod
    def _merge_bucket_residual_memory_refs(bucket: dict, memory_refs: list[str]) -> None:
        if not memory_refs:
            return
        merged_memory_refs = [str(item) for item in bucket.get("raw_residual_memory_refs", []) if str(item)]
        for memory_ref in memory_refs:
            memory_ref_text = str(memory_ref)
            if memory_ref_text and memory_ref_text not in merged_memory_refs:
                merged_memory_refs.append(memory_ref_text)
        bucket["raw_residual_memory_refs"] = merged_memory_refs
        if merged_memory_refs and not str(bucket.get("source_em_id", "")).strip():
            bucket["source_em_id"] = merged_memory_refs[0]
