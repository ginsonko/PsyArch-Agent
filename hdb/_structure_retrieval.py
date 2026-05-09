# -*- coding: utf-8 -*-
"""
Structure-level retrieval-storage for HDB.
"""

from __future__ import annotations

from collections import deque
import math
import time

from ._context_metadata import merge_context_metadata, merge_residual_metadata
from ._display_semantics import strip_display_only_glyphs
from ._id_generator import next_id
from ._match_scoring_v2 import build_match_score_v2
from ._profile_restore import restore_group_profile, restore_profile, restore_structure_profile
from ._sequence_display import format_sequence_groups


class StructureRetrievalEngine:
    def __init__(self, config: dict, weight_engine, logger, maintenance_engine):
        self._config = config
        self._weight = weight_engine
        self._logger = logger
        self._maintenance = maintenance_engine
        # Runtime state for internal residual resolution (DARL + PARS).
        # This is intentionally in-memory only: it models "temporary fatigue" and
        # "progressive detail revealing" across consecutive ticks, without any hard-coded semantics.
        self._internal_resolution_cursor: dict[str, int] = {}
        self._internal_resolution_history: dict[str, deque[str]] = {}
        self._internal_resolution_history_counts: dict[str, dict[str, int]] = {}
        self._internal_resolution_focus_credit: dict[str, float] = {}
        self._runtime_match_now_ms: int | None = None
        self._runtime_cache: dict | None = None

    def update_config(self, config: dict) -> None:
        self._config = config

    def clear_runtime_state(self) -> dict:
        summary = {
            "internal_resolution_cursor_count": len(self._internal_resolution_cursor),
            "internal_resolution_history_count": len(self._internal_resolution_history),
            "internal_resolution_history_bucket_count": len(self._internal_resolution_history_counts),
            "internal_resolution_focus_credit_count": len(self._internal_resolution_focus_credit),
        }
        self._internal_resolution_cursor.clear()
        self._internal_resolution_history.clear()
        self._internal_resolution_history_counts.clear()
        self._internal_resolution_focus_credit.clear()
        self._runtime_match_now_ms = None
        self._runtime_cache = None
        return summary

    def run(
        self,
        *,
        state_snapshot: dict,
        trace_id: str,
        tick_id: str,
        structure_store,
        group_store,
        pointer_index,
        cut_engine,
        episodic_store,
        attention_mode: str,
        top_n: int,
        enable_storage: bool,
        enable_new_group_creation: bool,
        max_rounds: int,
        now_ms: int | None = None,
    ) -> dict:
        del enable_new_group_creation
        try:
            self._runtime_match_now_ms = int(now_ms) if now_ms is not None else None
        except Exception:
            self._runtime_match_now_ms = None
        self._runtime_cache = {
            "structure_fuzzy_metadata": {},
            "metrics": {
                "structure_fuzzy_metadata_cache_hit_count": 0,
                "structure_fuzzy_metadata_cache_store_count": 0,
            },
        }
        items = list(state_snapshot.get("top_items") or state_snapshot.get("items") or [])
        # 注意力模式（attention_mode）说明：
        # - top_n_stub: 旧版占位口径（兼容保留）
        # - cam_snapshot: 正式口径，state_snapshot 本身已经是 CAM（当前注意记忆体）快照
        if attention_mode not in {"top_n_stub", "cam_snapshot"}:
            return self._empty_result(code="NOT_IMPLEMENTED_ERROR", message="attention_mode not implemented")

        # CAM-only internal stimulus mode (结构级开关关闭时使用):
        # - Convert the current CAM snapshot directly into endogenous (co-occurrence) stimulus fragments.
        # - Still apply DARL+PARS so internal SA count stays bounded.
        # - Must NOT require HDB-backed structure objects: CAM may contain runtime ST items not yet persisted.
        if attention_mode == "cam_snapshot" and int(max_rounds) <= 0:
            return self._run_cam_internal_stimulus_only(
                items=items,
                trace_id=trace_id,
                tick_id=tick_id,
                cut_engine=cut_engine,
            )

        # 只消费结构（ST）。top_n 在这里是“安全上限”，避免误配置时 CAM 过大导致结构级展开爆炸。
        safe_cap = max(1, int(top_n or 1))
        st_items = [item for item in items if item.get("ref_object_type") == "st"][:safe_cap]
        if not st_items:
            return self._empty_result(code="OK", message="no structure items in cam")

        now_ms = int(time.time() * 1000)
        cam_items = self._collect_cam_items(st_items=st_items, structure_store=structure_store, now_ms=now_ms)
        if not cam_items:
            return self._empty_result(code="OK", message="no valid structure items in cam")

        cam_structure_ids = [item["structure_id"] for item in cam_items]
        budget_er_map = {item["structure_id"]: item["er"] for item in cam_items}
        budget_ev_map = {item["structure_id"]: item["ev"] for item in cam_items}
        debug_cam_items = [dict(item["debug"]) for item in cam_items]
        profile_restore_cache: dict[str, dict] = {}
        episodic_memory_id = ""
        if enable_storage:
            episodic = episodic_store.append(
                {
                    "event_summary": "structure-level runtime memory",
                    "structure_refs": list(dict.fromkeys(cam_structure_ids)),
                    "group_refs": [],
                    "origin": "structure_level_runtime_memory",
                    "meta": {
                        "confidence": 1.0,
                        "field_registry_version": 1,
                        "debug": {},
                        "ext": {
                            "trace_id": trace_id,
                            "tick_id": tick_id,
                        },
                    },
                },
                trace_id=trace_id,
                tick_id=tick_id,
            )
            episodic_memory_id = episodic.get("id", "")
            if episodic_memory_id:
                initial_runtime_profile = self._build_runtime_profile_from_cam(
                    cam_items=cam_items,
                    budget_er_map=budget_er_map,
                    budget_ev_map=budget_ev_map,
                    cut_engine=cut_engine,
                    origin_frame_id=tick_id,
                    structure_store=structure_store,
                )
                episodic_meta = dict(episodic.get("meta", {}))
                episodic_ext = dict(episodic_meta.get("ext", {}))
                episodic_ext["display_text"] = format_sequence_groups(initial_runtime_profile.get("sequence_groups", [])) or initial_runtime_profile.get("display_text", "")
                episodic_ext["memory_material"] = self._build_structure_memory_material(profile=initial_runtime_profile)
                episodic_meta["ext"] = episodic_ext
                episodic["meta"] = episodic_meta
                episodic_store.update(episodic)

        matched_group_ids: list[str] = []
        new_group_ids: list[str] = []
        group_projections: list[dict] = []
        bias_structure_ids: list[str] = []
        bias_projections: list[dict] = []
        runtime_bound_attribute_map: dict[str, list[dict]] = {
            str(item.get("structure_id", "")): [dict(unit) for unit in (item.get("runtime_bound_attribute_units", []) or []) if isinstance(unit, dict)]
            for item in cam_items
            if str(item.get("structure_id", ""))
        }
        internal_fragments: list[dict] = []
        round_summaries: list[dict] = []
        debug_round_details: list[dict] = []
        debug_new_group_details: list[dict] = []
        fallback_used = False
        temp_anchor_fatigue: dict[str, float] = {}
        single_group_processed_ids: set[str] = set()
        min_budget_threshold = max(0.01, float(self._config.get("stimulus_residual_min_energy", 0.05)))
        # Goal B / 方案A：当 CAM-only 内源刺激直接由当前注意记忆体构造时，
        # 不再额外叠加 attention_landscape fragment。否则会把同一 CAM 内容重复投影，
        # 导致主字符串 fragment 与景观 fragment 同时进入 internal_packet，形成重复字符串组和碎片组。
        attention_landscape_fragment = self._build_attention_landscape_fragment(
            items=items,
            tick_id=tick_id,
            structure_store=structure_store,
            group_store=group_store,
            cut_engine=cut_engine,
            total_er=sum(max(0.0, float(item.get("er", 0.0))) for item in items if isinstance(item, dict)),
            total_ev=sum(max(0.0, float(item.get("ev", 0.0))) for item in items if isinstance(item, dict)),
            profile_cache=profile_restore_cache,
        )
        if attention_landscape_fragment is not None and attention_mode != "cam_snapshot":
            internal_fragments.append(attention_landscape_fragment)

        for round_index in range(1, max_rounds + 1):
            if self._max_total_budget(cam_structure_ids, budget_er_map, budget_ev_map) < min_budget_threshold:
                break

            runtime_profile = self._build_runtime_profile_from_cam(
                cam_items=cam_items,
                budget_er_map=budget_er_map,
                budget_ev_map=budget_ev_map,
                cut_engine=cut_engine,
                origin_frame_id=tick_id,
                structure_store=structure_store,
            )
            budget_before = self._build_budget_snapshot(cam_structure_ids, budget_er_map, budget_ev_map)
            anchor_item = self._select_anchor_item(
                cam_items=cam_items,
                budget_er_map=budget_er_map,
                budget_ev_map=budget_ev_map,
                temp_anchor_fatigue=temp_anchor_fatigue,
                skip_structure_ids=single_group_processed_ids,
                now_ms=now_ms,
            )
            if not anchor_item:
                break

            lookup, best, candidate_details = self._resolve_anchor_chain_match(
                anchor_structure_id=anchor_item["structure_id"],
                runtime_profile=runtime_profile,
                budget_er_map=budget_er_map,
                budget_ev_map=budget_ev_map,
                structure_store=structure_store,
                group_store=group_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
                trace_id=trace_id,
                tick_id=tick_id,
                round_index=round_index,
                now_ms=now_ms,
            )
            fallback_used = fallback_used or bool(lookup.get("used_fallback"))

            if not best:
                storage_summary = None
                storage_fragments: list[dict] = []
                selected_group = self._build_implicit_single_group_debug(
                    anchor_item=anchor_item,
                    structure_store=structure_store,
                    cut_engine=cut_engine,
                    runtime_profile=runtime_profile,
                    tick_id=tick_id,
                    round_index=round_index,
                )
                if enable_storage:
                    storage_summary = self._store_runtime_context(
                        owner_kind="st",
                        owner_id=anchor_item["structure_id"],
                        full_profile=runtime_profile,
                        covered_structure_ids=[anchor_item["structure_id"]],
                        full_energy_profile=self._profile_energy_map(runtime_profile),
                        structure_store=structure_store,
                        group_store=group_store,
                        pointer_index=pointer_index,
                        cut_engine=cut_engine,
                        trace_id=trace_id,
                        tick_id=tick_id,
                        round_index=round_index,
                        episodic_memory_id=episodic_memory_id,
                    )
                    if storage_summary:
                        for group_id in storage_summary.get("new_group_ids", []):
                            if group_id:
                                new_group_ids.append(group_id)
                        debug_new_group_details.extend(storage_summary.get("new_group_details", []))
                        storage_fragments = self._build_internal_storage_fragments(
                            storage_summary=storage_summary,
                            source_group_id=selected_group.get("group_id", ""),
                            source_phase="storage_residual_round",
                            fallback_total_er=float(anchor_item.get("er", 0.0)),
                            fallback_total_ev=float(anchor_item.get("ev", 0.0)),
                            cut_engine=cut_engine,
                            runtime_bound_attribute_units=self._collect_runtime_bound_attribute_units_for_structure_ids(
                                structure_ids=[anchor_item["structure_id"]],
                                runtime_bound_attribute_map=runtime_bound_attribute_map,
                            ),
                        )
                        internal_fragments.extend(storage_fragments)
                round_summaries.append(
                    {
                        "round_index": round_index,
                        "group_id": selected_group.get("group_id", ""),
                        "score": round(float(selected_group.get("score", 1.0)), 8),
                        "coverage_ratio": round(float(selected_group.get("coverage_ratio", 0.0)), 8),
                        "wave_similarity": round(float(selected_group.get("wave_similarity", 1.0)), 8),
                        "matched_er_total": round(float(anchor_item.get("er", 0.0)), 8),
                        "matched_ev_total": round(float(anchor_item.get("ev", 0.0)), 8),
                        "bias_structure_ids": [],
                        "internal_fragment_count": len(storage_fragments),
                        "synthetic": True,
                    }
                )
                debug_round_details.append(
                    {
                        "round_index": round_index,
                        "anchor": self._build_anchor_debug(anchor_item),
                        "budget_before": budget_before,
                        "budget_after": budget_before,
                        "candidate_groups": candidate_details,
                        "selected_group": selected_group,
                        "bias_projections": [],
                        "internal_fragments": [
                            {
                                "source_structure_id": fragment.get("source_structure_id", ""),
                                "display_text": fragment.get("display_text", ""),
                                "token_count": len(fragment.get("flat_tokens", [])),
                                "er_hint": round(float(fragment.get("er_hint", 0.0)), 8),
                                "ev_hint": round(float(fragment.get("ev_hint", 0.0)), 8),
                                "energy_hint": round(float(fragment.get("er_hint", 0.0)) + float(fragment.get("ev_hint", 0.0)), 8),
                            }
                            for fragment in storage_fragments
                        ],
                        "storage_summary": storage_summary,
                        "chain_steps": list(lookup.get("chain_steps", [])),
                    }
                )
                single_group_processed_ids.add(anchor_item["structure_id"])
                temp_anchor_fatigue[anchor_item["structure_id"]] = round(
                    float(temp_anchor_fatigue.get(anchor_item["structure_id"], 0.0))
                    + max(
                        float(self._config.get("structure_anchor_temp_fatigue_step", 0.55)),
                        float(self._config.get("structure_single_anchor_temp_fatigue_step", 1.1)),
                    ),
                    8,
                )
                continue

            group_obj = group_store.get(best["group_id"])
            if not group_obj:
                break
            matched_group_ids.append(group_obj.get("id", ""))
            rho = round(max(0.0, min(1.0, float(best.get("competition_score", 0.0)))), 8)
            required_ids = list(best.get("required_ids", []))
            current_required_profile = self._normalize_energy(required_ids, budget_er_map, budget_ev_map)
            matched_er_total = round(sum(float(budget_er_map.get(structure_id, 0.0)) for structure_id in required_ids), 8)
            matched_ev_total = round(sum(float(budget_ev_map.get(structure_id, 0.0)) for structure_id in required_ids), 8)
            projected_er = round(max(0.0, float(matched_er_total)) * max(0.0, float(rho)), 8)
            projected_ev = round(max(0.0, float(matched_ev_total)) * max(0.0, float(rho)), 8)
            if projected_er + projected_ev > 0.0:
                group_projections.append(
                    {
                        "group_id": group_obj.get("id", ""),
                        "er": projected_er,
                        "ev": projected_ev,
                        "reason": "structure_group_matched",
                    }
                )

            self._update_group_after_match(
                group_obj=group_obj,
                current_profile=current_required_profile,
                match_score=rho,
                matched_er_total=matched_er_total,
                matched_ev_total=matched_ev_total,
            )
            group_store.update(group_obj)
            self._mark_path_entries(
                best=best,
                structure_store=structure_store,
                group_store=group_store,
                transferred_er=round(matched_er_total * rho, 8),
                transferred_ev=round(matched_ev_total * rho, 8),
                match_score=rho,
            )

            round_bias_projections = self._build_bias_projections(
                group_obj=group_obj,
                required_ids=required_ids,
                matched_er_total=matched_er_total,
                matched_ev_total=matched_ev_total,
                rho=rho,
                structure_store=structure_store,
            )
            bias_projections.extend(round_bias_projections)
            bias_structure_ids.extend(
                projection.get("structure_id", "")
                for projection in round_bias_projections
                if projection.get("structure_id")
            )
            active_group_fragment = self._build_internal_group_fragment(
                group_obj=group_obj,
                required_ids=required_ids,
                matched_er_total=matched_er_total,
                matched_ev_total=matched_ev_total,
                rho=rho,
                structure_store=structure_store,
                group_store=group_store,
                cut_engine=cut_engine,
                profile_cache=profile_restore_cache,
                runtime_bound_attribute_units=self._collect_runtime_bound_attribute_units_for_structure_ids(
                    structure_ids=required_ids,
                    runtime_bound_attribute_map=runtime_bound_attribute_map,
                ),
            )

            transferred_er_map: dict[str, float] = {}
            transferred_ev_map: dict[str, float] = {}
            for structure_id in cam_structure_ids:
                transferred_er = round(float(budget_er_map.get(structure_id, 0.0)) * rho, 8)
                transferred_ev = round(float(budget_ev_map.get(structure_id, 0.0)) * rho, 8)
                budget_er_map[structure_id] = round(float(budget_er_map.get(structure_id, 0.0)) - transferred_er, 8)
                budget_ev_map[structure_id] = round(float(budget_ev_map.get(structure_id, 0.0)) - transferred_ev, 8)
                if structure_id in required_ids:
                    continue
                transferred_er_map[structure_id] = transferred_er
                transferred_ev_map[structure_id] = transferred_ev

            residual_ids = [
                structure_id
                for structure_id in cam_structure_ids
                if float(transferred_er_map.get(structure_id, 0.0)) + float(transferred_ev_map.get(structure_id, 0.0)) > 0.0
            ]
            round_fragments = self._build_internal_fragments(
                source_group_id=group_obj.get("id", ""),
                source_phase="residual_round",
                structure_ids=residual_ids,
                transfer_er_map=transferred_er_map,
                transfer_ev_map=transferred_ev_map,
                structure_store=structure_store,
                group_store=group_store,
                cut_engine=cut_engine,
                profile_cache=profile_restore_cache,
                runtime_bound_attribute_map=runtime_bound_attribute_map,
            )
            if active_group_fragment is not None:
                round_fragments.insert(0, active_group_fragment)
            internal_fragments.extend(round_fragments)

            storage_summary = None
            if enable_storage:
                storage_summary = self._store_runtime_context(
                    owner_kind="sg",
                    owner_id=group_obj.get("id", ""),
                    full_profile=runtime_profile,
                    covered_structure_ids=required_ids,
                    full_energy_profile=self._profile_energy_map(runtime_profile),
                    structure_store=structure_store,
                    group_store=group_store,
                    pointer_index=pointer_index,
                    cut_engine=cut_engine,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    round_index=round_index,
                    episodic_memory_id=episodic_memory_id,
                )
                if storage_summary:
                    for group_id in storage_summary.get("new_group_ids", []):
                        if group_id:
                            new_group_ids.append(group_id)
                    debug_new_group_details.extend(storage_summary.get("new_group_details", []))

            budget_after = self._build_budget_snapshot(cam_structure_ids, budget_er_map, budget_ev_map)
            selected_group = {
                **self._build_group_debug_payload(group_obj, structure_store, cut_engine),
                "group_kind": "group",
                "synthetic": False,
                "score": round(float(best.get("competition_score", 0.0)), 8),
                "competition_score": round(float(best.get("competition_score", 0.0)), 8),
                "competition_score_legacy": round(float(best.get("competition_score_legacy", 0.0)), 8),
                "competition_score_v2": round(float(best.get("competition_score_v2", 0.0)), 8),
                "similarity": round(float(best.get("competition_score", 0.0)), 8),
                "base_similarity": round(float(best.get("base_similarity", 0.0)), 8),
                "base_similarity_legacy": round(float(best.get("base_similarity_legacy", 0.0)), 8),
                "base_similarity_v2": round(float(best.get("base_similarity_v2", 0.0)), 8),
                "coverage_ratio": round(float(best.get("coverage_ratio", 0.0)), 8),
                "structure_ratio": round(float(best.get("structure_ratio", 0.0)), 8),
                "wave_similarity": round(float(best.get("wave_similarity", 0.0)), 8),
                "path_strength": round(float(best.get("path_strength", 1.0)), 8),
                "runtime_weight": round(float(best.get("runtime_weight", 1.0)), 8),
                "entry_runtime_weight": round(float(best.get("entry_runtime_weight", 1.0)), 8),
                "chain_depth": int(best.get("chain_depth", 0)),
                "owner_kind": best.get("owner_kind", ""),
                "owner_id": best.get("owner_id", ""),
                "v2_base_score": best.get("v2_base_score"),
                "v2_numeric_score": best.get("v2_numeric_score"),
                "v2_order_alignment_score": best.get("v2_order_alignment_score"),
                "v2_attribute_anchor_score": best.get("v2_attribute_anchor_score"),
                "v2_context_support_score": best.get("v2_context_support_score"),
                "v2_energy_profile_score": best.get("v2_energy_profile_score"),
                "v2_structure_inclusion_score": best.get("v2_structure_inclusion_score"),
                "v2_threshold_margin": best.get("v2_threshold_margin"),
                "v2_available_component_count": best.get("v2_available_component_count"),
                "common_part": dict(best.get("common_part", {})),
            }
            debug_round_details.append(
                {
                    "round_index": round_index,
                    "anchor": self._build_anchor_debug(anchor_item),
                    "budget_before": budget_before,
                    "budget_after": budget_after,
                    "candidate_groups": candidate_details,
                    "selected_group": selected_group,
                    "bias_projections": list(round_bias_projections),
                    "internal_fragments": [
                        {
                            **fragment,
                            "display_text": " / ".join(fragment.get("flat_tokens", [])),
                            "sequence_groups": list(fragment.get("sequence_groups", [])),
                            "energy_hint": round(float(fragment.get("er_hint", 0.0)) + float(fragment.get("ev_hint", 0.0)), 8),
                        }
                        for fragment in round_fragments
                    ],
                    "active_group_fragment": dict(active_group_fragment) if isinstance(active_group_fragment, dict) else None,
                    "storage_summary": storage_summary,
                    "chain_steps": list(lookup.get("chain_steps", [])),
                }
            )
            round_summaries.append(
                {
                    "round_index": round_index,
                    "group_id": group_obj.get("id", ""),
                    "score": round(float(best.get("competition_score", 0.0)), 8),
                    "coverage_ratio": round(float(best.get("coverage_ratio", 0.0)), 8),
                    "wave_similarity": round(float(best.get("wave_similarity", 0.0)), 8),
                    "matched_er_total": matched_er_total,
                    "matched_ev_total": matched_ev_total,
                    "bias_structure_ids": [projection.get("structure_id", "") for projection in round_bias_projections],
                    "internal_fragment_count": len(round_fragments),
                    "active_group_fragment_count": 1 if active_group_fragment is not None else 0,
                }
            )
            temp_anchor_fatigue[anchor_item["structure_id"]] = round(
                float(temp_anchor_fatigue.get(anchor_item["structure_id"], 0.0))
                + float(self._config.get("structure_anchor_temp_fatigue_step", 0.55))
                * (
                    float(self._config.get("structure_anchor_temp_fatigue_base", 0.7))
                    + float(self._config.get("structure_anchor_temp_fatigue_rho_gain", 0.6)) * rho
                ),
                8,
            )

        tail_ids = [
            structure_id
            for structure_id in cam_structure_ids
            if float(budget_er_map.get(structure_id, 0.0)) + float(budget_ev_map.get(structure_id, 0.0)) > 0.0
        ]
        tail_fragments = self._build_internal_fragments(
            source_group_id="",
            source_phase="tail_residual",
            structure_ids=tail_ids,
            transfer_er_map=budget_er_map,
            transfer_ev_map=budget_ev_map,
            structure_store=structure_store,
            group_store=group_store,
            cut_engine=cut_engine,
            profile_cache=profile_restore_cache,
        )
        internal_fragments.extend(tail_fragments)
        internal_fragments = self._merge_internal_fragments(internal_fragments)
        focus_credit_ids = list(dict.fromkeys(list(cam_structure_ids) + list(matched_group_ids)))
        internal_fragments, internal_resolution_summary = self._apply_internal_resolution_to_fragments(
            fragments=internal_fragments,
            cam_items=cam_items,
            cam_structure_ids=focus_credit_ids,
            now_ms=now_ms,
            trace_id=trace_id,
            tick_id=tick_id,
        )
        cam_runtime_priority_fragments, cam_runtime_priority_projection_summary = self._build_cam_runtime_priority_fragments(
            cam_items=cam_items,
            budget_er_map=budget_er_map,
            budget_ev_map=budget_ev_map,
            existing_fragments=internal_fragments,
        )
        if cam_runtime_priority_fragments:
            internal_fragments = self._merge_internal_fragments(list(internal_fragments) + list(cam_runtime_priority_fragments))

        if self._config.get("detail_log_dump_group_match_profile", True):
            self._logger.detail(
                trace_id=trace_id,
                tick_id=tick_id,
                step="structure_level_match_profile",
                message_zh="结构级查存一体轮次摘要",
                message_en="Structure-level retrieval round summaries",
                info={
                    "round_summaries": round_summaries,
                    "cam_structure_ids": cam_structure_ids,
                },
            )

        return {
            "code": "OK",
            "message": "Structure-level retrieval-storage completed",
            "cam_stub_count": len(cam_structure_ids),
            "round_count": len(round_summaries) if round_summaries else len(debug_round_details),
            "matched_group_ids": list(dict.fromkeys(matched_group_ids)),
            "new_group_ids": list(dict.fromkeys(new_group_ids)),
            "group_projections": list(group_projections),
            "bias_structure_ids": list(dict.fromkeys(bias_structure_ids)),
            "bias_projections": bias_projections,
            "internal_stimulus_fragments": internal_fragments,
            "internal_resolution": internal_resolution_summary,
            "cam_runtime_priority_projection": cam_runtime_priority_projection_summary,
            "episodic_memory_id": episodic_memory_id,
            "fallback_used": fallback_used,
            "metrics": self._runtime_metrics_snapshot(),
            "debug": {
                "cam_items": debug_cam_items,
                "round_details": debug_round_details,
                "new_group_details": list({item.get("group_id", ""): item for item in debug_new_group_details if item.get("group_id", "")}.values()),
            },
        }

    def _run_cam_internal_stimulus_only(
        self,
        *,
        items: list[dict],
        trace_id: str,
        tick_id: str,
        cut_engine,
    ) -> dict:
        """
        Build internal stimulus fragments directly from CAM snapshot items.

        Why:
          When structure-level retrieval-storage is disabled, we still need endogenous stimulus
          to keep the closed loop alive. In this mode we intentionally avoid any HDB group matching
          (rounds=0) and do NOT require HDB-backed structures to exist in `structure_store`.
        """
        now_ms = int(time.time() * 1000)

        # Best-effort CAM structure list for internal resolution (focus credit, per-structure allocation).
        cam_items: list[dict] = []
        cam_structure_ids: list[str] = []
        debug_cam_items: list[dict] = []

        internal_fragments: list[dict] = []
        for order_index, item in enumerate(items or []):
            if not isinstance(item, dict):
                continue
            ref_type = str(item.get("ref_object_type", "") or item.get("object_type", "") or "").strip()
            ref_id = str(item.get("ref_object_id", "") or item.get("id", "") or item.get("item_id", "") or "").strip()
            ref_snapshot = item.get("ref_snapshot", {}) or {}
            if not isinstance(ref_snapshot, dict):
                ref_snapshot = {}
            structure_ext = ref_snapshot.get("structure_ext", {}) if isinstance(ref_snapshot.get("structure_ext", {}), dict) else {}
            structure_kind = str(structure_ext.get("kind", "") or "").strip()
            if ref_type in {"st", "sg"} and structure_kind in {"residual_context_common"}:
                # Goal B / 方案A：上下文全景残差结构不应在 CAM-only 内源路径中再次回投。
                continue
                continue
                ref_snapshot = {}

            display_text = str(
                item.get("display", "")
                or ref_snapshot.get("content_display_detail", "")
                or ref_snapshot.get("content_display", "")
                or ref_id
                or item.get("item_id", "")
                or ""
            ).strip()
            if not display_text:
                continue

            # Goal B / 方案A口径：若 CAM 项已经携带字符串 sequence_groups，则内源片段必须优先复用这些顺序敏感组，
            # 不能退化为 display 文本字符拆分或无序 tokens。否则后续刺激级匹配会丢失字符串剪枝信息。
            raw_groups = ref_snapshot.get("sequence_groups", []) or item.get("sequence_groups", []) or []
            sequence_groups = []
            goal_b_mode = bool(self._config.get("enable_goal_b_char_sa_string_mode", False))
            has_goal_b_string_group = False
            for group in raw_groups:
                if not isinstance(group, dict):
                    continue
                normalized_group = dict(group)
                if bool(group.get("order_sensitive", False)) and str(group.get("string_unit_kind", "") or "") == "char_sequence":
                    normalized_group.setdefault("string_token_text", str(group.get("string_token_text", "") or "".join([str(t) for t in (group.get("tokens", []) or []) if str(t)])))
                if goal_b_mode and not (bool(group.get("order_sensitive", False)) and str(group.get("string_unit_kind", "") or "") == "char_sequence"):
                    continue
                if bool(group.get("order_sensitive", False)) and str(group.get("string_unit_kind", "") or "") == "char_sequence":
                    has_goal_b_string_group = True
                sequence_groups.append(normalized_group)
            flat_tokens = [str(t) for t in (ref_snapshot.get("flat_tokens", []) or item.get("flat_tokens", []) or []) if str(t)]
            used_display_fallback_char_split = False

            er = round(max(0.0, float(item.get("er", 0.0))), 8)
            ev = round(max(0.0, float(item.get("ev", 0.0))), 8)
            cp_abs = round(max(0.0, float(item.get("cp_abs", 0.0))), 8)
            runtime_bound_attribute_units = [
                dict(unit)
                for unit in (
                    item.get("runtime_bound_attribute_units", [])
                    or ref_snapshot.get("runtime_bound_attribute_units", [])
                    or []
                )
                if isinstance(unit, dict)
            ]

            # Build a stored-group-like payload from snapshot when available; otherwise fall back to tokens.
            if not flat_tokens and sequence_groups:
                flat_tokens = [str(token) for group in sequence_groups for token in (group.get("tokens", []) or []) if str(token)]
            if not sequence_groups:
                if not flat_tokens:
                    is_runtime_event_like = (
                        ref_type in {"event", "cs_event", "narrative_event"}
                        or ref_id.startswith("cs_event::")
                        or str(ref_snapshot.get("event_ref_id", "") or "").startswith("cs_event::")
                    )
                    if is_runtime_event_like:
                        # Goal B safety: runtime event displays are presentation summaries, not canonical feature tokens.
                        # If an event-like CAM item has no canonical sequence_groups/flat_tokens, skip it rather than
                        # injecting formatted display text such as "{??}" back into endogenous SA.
                        continue
                    # IMPORTANT SAFETY:
                    # - Never use `display_text` as a SINGLE canonical token. display_text may contain
                    #   "{...}" / "->" / debug merge chains, which would pollute endogenous SA tokens
                    #   and then be atomically persisted by stimulus-level preseed.
                    #
                    # Fallback policy (CS-first CAM-only endogenous stimulus):
                    # - If this is an *attribute stimulus* (e.g. 违和感/正确感), do NOT split it into
                    #   characters. Instead emit a stable single token derived from attribute_name.
                    # - Otherwise, if the fallback text is short enough, we may split into characters
                    #   so each character can act as a minimal SA feature token. If it's too long,
                    #   skip emitting this fragment (avoid generating large ungrounded internal streams).
                    stimulus = ref_snapshot.get("stimulus", {}) if isinstance(ref_snapshot.get("stimulus", {}), dict) else {}
                    content = ref_snapshot.get("content", {}) if isinstance(ref_snapshot.get("content", {}), dict) else {}
                    role = str(
                        ref_snapshot.get("role", "")
                        or item.get("role", "")
                        or stimulus.get("role", "")
                        or ""
                    ).strip()
                    attribute_name = str(
                        ref_snapshot.get("attribute_name", "")
                        or item.get("attribute_name", "")
                        or content.get("attribute_name", "")
                        or ""
                    ).strip()
                    is_attribute = (role == "attribute") or bool(attribute_name)

                    if is_attribute:
                        # Attributes may be numerical and MUST preserve their value when possible.
                        # We keep a single-token representation for safety (avoid large streams),
                        # but include the numeric value so downstream can reconstruct/parse it.
                        #
                        # Note: we intentionally do NOT split attributes into characters.
                        raw = str(
                            content.get("raw", "")
                            or ref_snapshot.get("content_display", "")
                            or item.get("display", "")
                            or ""
                        ).strip()
                        value_type = str(
                            ref_snapshot.get("value_type", "")
                            or item.get("value_type", "")
                            or content.get("value_type", "")
                            or ""
                        ).strip()
                        val = (
                            ref_snapshot.get("attribute_value", None)
                            if ref_snapshot.get("attribute_value", None) not in ("", None)
                            else item.get("attribute_value", content.get("attribute_value", None))
                        )
                        if not attribute_name and raw and ":" in raw:
                            attribute_name = raw.split(":", 1)[0].strip()
                        if attribute_name:
                            attribute_token = ""
                            if value_type == "numerical" and val is not None:
                                try:
                                    v = float(val)
                                except Exception:
                                    v = None
                                if v is not None and math.isfinite(v):
                                    attribute_token = f"{attribute_name}:{round(v, 6)}"
                                    flat_tokens = [attribute_token]
                                    sequence_groups = [
                                        {
                                            "group_index": 0,
                                            "source_type": "cam_snapshot",
                                            "origin_frame_id": tick_id,
                                            "tokens": [attribute_token],
                                            "units": [
                                                {
                                                    "unit_id": f"cam_attr::{ref_id or display_text or order_index}",
                                                    "object_type": "sa",
                                                    "token": attribute_token,
                                                    "display_text": attribute_token,
                                                    "unit_role": "attribute",
                                                    "attribute_name": attribute_name,
                                                    "attribute_value": float(v),
                                                    "value_type": "numerical",
                                                    "sequence_index": 0,
                                                    "group_index": 0,
                                                }
                                            ],
                                            "csa_bundles": [],
                                        }
                                    ]
                                else:
                                    # Can't preserve a valid numeric -> drop attribute fragment rather than pollute.
                                    flat_tokens = []
                            elif raw:
                                # Non-numerical attribute: keep raw string if present.
                                safe = raw
                                if len(safe) > 96:
                                    safe = safe[:96]
                                attribute_token = safe
                                flat_tokens = [attribute_token]
                                sequence_groups = [
                                    {
                                        "group_index": 0,
                                        "source_type": "cam_snapshot",
                                        "origin_frame_id": tick_id,
                                        "tokens": [attribute_token],
                                        "units": [
                                            {
                                                "unit_id": f"cam_attr::{ref_id or display_text or order_index}",
                                                "object_type": "sa",
                                                "token": attribute_token,
                                                "display_text": attribute_token,
                                                "unit_role": "attribute",
                                                "attribute_name": attribute_name,
                                                "attribute_value": val,
                                                "value_type": value_type or "discrete",
                                                "sequence_index": 0,
                                                "group_index": 0,
                                            }
                                        ],
                                        "csa_bundles": [],
                                    }
                                ]
                            else:
                                attribute_token = attribute_name
                                flat_tokens = [attribute_token]
                                sequence_groups = [
                                    {
                                        "group_index": 0,
                                        "source_type": "cam_snapshot",
                                        "origin_frame_id": tick_id,
                                        "tokens": [attribute_token],
                                        "units": [
                                            {
                                                "unit_id": f"cam_attr::{ref_id or display_text or order_index}",
                                                "object_type": "sa",
                                                "token": attribute_token,
                                                "display_text": attribute_token,
                                                "unit_role": "attribute",
                                                "attribute_name": attribute_name,
                                                "attribute_value": val,
                                                "value_type": value_type or "discrete",
                                                "sequence_index": 0,
                                                "group_index": 0,
                                            }
                                        ],
                                        "csa_bundles": [],
                                    }
                                ]
                        else:
                            # Unknown attribute name -> skip (don't emit valueless attribute).
                            flat_tokens = []
                    else:
                        max_len = int(self._config.get("cam_internal_fallback_char_split_max_len", 500) or 500)
                        # Remove common formatting glyphs from display strings (not semantic tokens).
                        text = strip_display_only_glyphs(display_text)
                        if 0 < len(text) <= max_len:
                            flat_tokens = [ch for ch in text if ch and not ch.isspace()]
                            used_display_fallback_char_split = bool(flat_tokens)
                        else:
                            flat_tokens = []

                    if not flat_tokens:
                        # Too long / empty / unsupported -> skip this item.
                        continue
                if not sequence_groups:
                    sequence_groups = [
                        {
                            "group_index": 0,
                            "source_type": "cam_snapshot",
                            "origin_frame_id": tick_id,
                            "tokens": list(flat_tokens),
                        }
                    ]

            profile = self._profile_from_stored_groups(
                sequence_groups,
                cut_engine=cut_engine,
                ext={"kind": "cam_snapshot_internal", "tick_id": tick_id, "ref_type": ref_type},
            )
            fragment = self._build_internal_fragment_from_profile(
                owner_id=ref_id or display_text,
                owner_kind=ref_type or "runtime_item",
                source_group_id="",
                source_phase="cam_snapshot",
                display_text=display_text,
                profile=profile,
                total_er=er,
                total_ev=ev,
                ext={
                    "ref_object_type": ref_type,
                    "ref_object_id": ref_id,
                    "display_fallback_char_split": bool(used_display_fallback_char_split),
                    "goal_b_has_string_group": bool(has_goal_b_string_group),
                    "goal_b_string_group_count": int(len([g for g in sequence_groups if bool(g.get("order_sensitive", False)) and str(g.get("string_unit_kind", "") or "") == "char_sequence"])),
                    "goal_b_string_texts": [str(g.get("string_token_text", "") or "") for g in sequence_groups if bool(g.get("order_sensitive", False)) and str(g.get("string_unit_kind", "") or "") == "char_sequence"],
                    "sequence_group_count": int(len(sequence_groups)),
                },
                runtime_bound_attribute_units=runtime_bound_attribute_units,
            )
            if fragment is not None:
                internal_fragments.append(fragment)

            if ref_type in {"st", "sg"}:
                sid = ref_id or display_text
                cam_structure_ids.append(sid)
                cam_items.append(
                    {
                        "structure_id": sid,
                        "structure_obj": None,  # intentionally absent in this mode
                        "runtime_bound_attribute_units": runtime_bound_attribute_units,
                        "display_text": display_text,
                        "er": er,
                        "ev": ev,
                        "cp_abs": cp_abs,
                        "order_index": int(order_index),
                        "runtime_weight": 1.0,
                        "debug": {
                            "structure_id": sid,
                            "display_text": display_text,
                            "sequence_groups": sequence_groups,
                            "er": er,
                            "ev": ev,
                            "total_energy": round(er + ev, 8),
                            "cp_abs": cp_abs,
                            "runtime_bound_attribute_units": runtime_bound_attribute_units,
                            "base_weight": 1.0,
                            "recent_gain": 1.0,
                            "fatigue": 0.0,
                            "runtime_weight": 1.0,
                            "fallback": "cam_snapshot_no_structure_store",
                        },
                    }
                )
                debug_cam_items.append(dict(cam_items[-1].get("debug", {})))

        # Ensure deterministic ids and avoid duplicated fragments when multiple CAM items map to the same owner id.
        internal_fragments = self._merge_internal_fragments(internal_fragments)
        internal_fragments, internal_resolution_summary = self._apply_internal_resolution_to_fragments(
            fragments=internal_fragments,
            cam_items=cam_items,
            cam_structure_ids=list(dict.fromkeys(cam_structure_ids)),
            now_ms=now_ms,
            trace_id=trace_id,
            tick_id=tick_id,
        )
        cam_runtime_priority_fragments, cam_runtime_priority_projection_summary = self._build_cam_runtime_priority_fragments(
            cam_items=cam_items,
            budget_er_map={str(item.get("structure_id", "") or ""): max(0.0, float(item.get("er", 0.0))) for item in cam_items if str(item.get("structure_id", "") or "")},
            budget_ev_map={str(item.get("structure_id", "") or ""): max(0.0, float(item.get("ev", 0.0))) for item in cam_items if str(item.get("structure_id", "") or "")},
            existing_fragments=internal_fragments,
        )
        if cam_runtime_priority_fragments:
            internal_fragments = self._merge_internal_fragments(list(internal_fragments) + list(cam_runtime_priority_fragments))

        return {
            "code": "OK",
            "message": "CAM internal stimulus only (no group matching rounds)",
            "cam_stub_count": len(cam_structure_ids),
            "round_count": 0,
            "matched_group_ids": [],
            "new_group_ids": [],
            "group_projections": [],
            "bias_structure_ids": [],
            "bias_projections": [],
            "internal_stimulus_fragments": internal_fragments,
            "internal_resolution": internal_resolution_summary,
            "cam_runtime_priority_projection": cam_runtime_priority_projection_summary,
            "episodic_memory_id": "",
            "fallback_used": False,
            "metrics": self._runtime_metrics_snapshot(),
            "debug": {
                "cam_items": debug_cam_items,
                "round_details": [],
                "new_group_details": [],
            },
        }

    def _empty_result(self, *, code: str, message: str) -> dict:
        return {
            "code": code,
            "message": message,
            "cam_stub_count": 0,
            "round_count": 0,
            "matched_group_ids": [],
            "new_group_ids": [],
            "group_projections": [],
            "bias_structure_ids": [],
            "bias_projections": [],
            "internal_stimulus_fragments": [],
            "episodic_memory_id": "",
            "fallback_used": False,
            "metrics": self._runtime_metrics_snapshot(),
            "debug": {"cam_items": [], "round_details": [], "new_group_details": []},
        }

    def _increment_runtime_metric(self, key: str, amount: int | float = 1) -> None:
        if not isinstance(self._runtime_cache, dict):
            return
        metrics = self._runtime_cache.setdefault("metrics", {})
        if not isinstance(metrics, dict):
            return
        try:
            metrics[key] = metrics.get(key, 0) + amount
        except Exception:
            metrics[key] = amount

    def _runtime_metrics_snapshot(self) -> dict:
        if not isinstance(self._runtime_cache, dict):
            return {}
        metrics = self._runtime_cache.get("metrics", {})
        if not isinstance(metrics, dict):
            return {}
        return dict(metrics)

    def _collect_cam_items(self, *, st_items: list[dict], structure_store, now_ms: int) -> list[dict]:
        cam_items = []
        for order_index, item in enumerate(st_items):
            structure_id = item.get("ref_object_id", "") or item.get("id", "")
            structure_obj = structure_store.get(structure_id)
            if not structure_id or not structure_obj:
                continue
            ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
            runtime_bound_attribute_units = [
                dict(unit)
                for unit in (
                    item.get("runtime_bound_attribute_units", [])
                    or ref_snapshot.get("runtime_bound_attribute_units", [])
                    or []
                )
                if isinstance(unit, dict)
            ]
            runtime_stats = self._preview_structure_stats(structure_obj, now_ms=now_ms)
            er = round(max(0.0, float(item.get("er", 0.0))), 8)
            ev = round(max(0.0, float(item.get("ev", 0.0))), 8)
            cp_abs = round(max(0.0, float(item.get("cp_abs", 0.0))), 8)
            cam_items.append(
                {
                    "structure_id": structure_id,
                    "structure_obj": structure_obj,
                    "runtime_bound_attribute_units": runtime_bound_attribute_units,
                    "display_text": self._structure_display_text(structure_obj),
                    "er": er,
                    "ev": ev,
                    "cp_abs": cp_abs,
                    "order_index": order_index,
                    "runtime_weight": runtime_stats["runtime_weight"],
                    "debug": {
                        "structure_id": structure_id,
                        "display_text": self._structure_display_text(structure_obj),
                        "sequence_groups": list(structure_obj.get("structure", {}).get("sequence_groups", [])),
                        "er": er,
                        "ev": ev,
                        "total_energy": round(er + ev, 8),
                        "cp_abs": cp_abs,
                        "runtime_bound_attribute_units": runtime_bound_attribute_units,
                        "base_weight": runtime_stats["base_weight"],
                        "recent_gain": runtime_stats["recent_gain"],
                        "fatigue": runtime_stats["fatigue"],
                        "runtime_weight": runtime_stats["runtime_weight"],
                    },
                }
            )
        return cam_items

    def _preview_structure_stats(self, structure_obj: dict, *, now_ms: int) -> dict:
        preview = {"stats": dict(structure_obj.get("stats", {}))}
        self._weight.decay_structure(preview, now_ms=now_ms, round_step=1)
        stats = preview.get("stats", {})
        runtime_weight = self._weight.compute_runtime_weight(
            base_weight=float(stats.get("base_weight", 0.0)),
            recent_gain=float(stats.get("recent_gain", 1.0)),
            fatigue=float(stats.get("fatigue", 0.0)),
        )
        return {
            "base_weight": round(float(stats.get("base_weight", 0.0)), 8),
            "recent_gain": round(float(stats.get("recent_gain", 1.0)), 8),
            "fatigue": round(float(stats.get("fatigue", 0.0)), 8),
            "runtime_weight": round(float(runtime_weight), 8),
        }

    def _preview_group_stats(self, group_obj: dict, *, now_ms: int) -> dict:
        preview = {"stats": dict(group_obj.get("stats", {}))}
        self._weight.decay_group(preview, now_ms=now_ms, round_step=1)
        stats = preview.get("stats", {})
        runtime_weight = self._weight.compute_runtime_weight(
            base_weight=float(stats.get("base_weight", 0.0)),
            recent_gain=float(stats.get("recent_gain", 1.0)),
            fatigue=float(stats.get("fatigue", 0.0)),
        )
        return {
            "base_weight": round(float(stats.get("base_weight", 0.0)), 8),
            "recent_gain": round(float(stats.get("recent_gain", 1.0)), 8),
            "fatigue": round(float(stats.get("fatigue", 0.0)), 8),
            "runtime_weight": round(float(runtime_weight), 8),
        }

    def _preview_entry_stats(self, entry: dict, *, now_ms: int) -> dict:
        preview = dict(entry)
        self._weight.decay_entry(preview, now_ms=now_ms, round_step=1)
        runtime_weight = self._weight.entry_runtime_weight(preview)
        return {
            "base_weight": round(float(preview.get("base_weight", 0.0)), 8),
            "recent_gain": round(float(preview.get("recent_gain", 1.0)), 8),
            "fatigue": round(float(preview.get("fatigue", 0.0)), 8),
            "runtime_weight": round(float(runtime_weight), 8),
        }

    def _build_runtime_profile_from_cam(
        self,
        *,
        cam_items: list[dict],
        budget_er_map: dict[str, float],
        budget_ev_map: dict[str, float],
        cut_engine,
        origin_frame_id: str,
        structure_store,
    ) -> dict:
        units = []
        for order_index, item in enumerate(cam_items):
            structure_id = item["structure_id"]
            structure_obj = item["structure_obj"]
            units.append(
                self._make_structure_unit(
                    structure_id=structure_id,
                    display_text=self._structure_display_text(structure_obj),
                    structure_obj=structure_obj,
                    runtime_bound_attribute_units=item.get("runtime_bound_attribute_units", []),
                    er=float(budget_er_map.get(structure_id, 0.0)),
                    ev=float(budget_ev_map.get(structure_id, 0.0)),
                    order_index=order_index,
                    source_type="cam",
                    origin_frame_id=origin_frame_id,
                )
            )
        profile = self._profile_from_units(units=units, cut_engine=cut_engine, ext={"kind": "structure_level_runtime"})
        return self._enrich_profile_structure_units(
            profile=profile,
            structure_store=structure_store,
        )

    def _make_structure_unit(
        self,
        *,
        structure_id: str,
        display_text: str,
        structure_obj: dict | None = None,
        runtime_bound_attribute_units: list[dict] | None = None,
        er: float,
        ev: float,
        order_index: int,
        source_type: str,
        origin_frame_id: str,
    ) -> dict:
        fuzzy_metadata = self._build_structure_fuzzy_metadata(
            structure_obj,
            runtime_bound_attribute_units=runtime_bound_attribute_units,
        )
        return {
            "unit_id": structure_id,
            "object_type": "st",
            "token": structure_id,
            "display_text": fuzzy_metadata.get("grouped_display_text", "") or display_text or structure_id,
            "unit_role": "feature",
            "unit_signature": f"ST:{structure_id}",
            "sequence_index": order_index,
            "group_index": order_index,
            "source_group_index": order_index,
            "source_type": source_type,
            "origin_frame_id": origin_frame_id,
            "er": round(max(0.0, float(er)), 8),
            "ev": round(max(0.0, float(ev)), 8),
            "total_energy": round(max(0.0, float(er)) + max(0.0, float(ev)), 8),
            "is_punctuation": False,
            "display_visible": True,
            "is_placeholder": False,
            "bundle_id": "",
            "bundle_anchor_unit_id": "",
            "bundle_anchor_signature": "",
            "bundle_signature": "",
            "bundle_member_unit_ids": [],
            "bundle_member_signatures": [],
            "structure_display_text": display_text or structure_id,
            "structure_grouped_display_text": fuzzy_metadata.get("grouped_display_text", "") or display_text or structure_id,
            "structure_sequence_groups": [dict(group) for group in (structure_obj or {}).get("structure", {}).get("sequence_groups", []) if isinstance(group, dict)],
            "structure_display_template": fuzzy_metadata.get("display_template", "") or display_text or structure_id,
            "structure_fuzzy_signature": fuzzy_metadata.get("fuzzy_signature", "") or f"ST:{structure_id}",
            "structure_numeric_slots": list(fuzzy_metadata.get("numeric_slots", [])),
        }

    # 结构级把 ST 当成“结构特征单元”比较时，不能只看 structure_id。
    # 这里显式抽取一个“数值可模糊匹配”的签名与显示模板，供 cut_engine
    # 在最大共同部分与结构组竞争时复用，避免 1.0 / 1.1 这种同类数值把本质相同的结构判成不同结构。
    def _build_structure_fuzzy_metadata(
        self,
        structure_obj: dict | None,
        *,
        runtime_bound_attribute_units: list[dict] | None = None,
    ) -> dict:
        if not structure_obj:
            return {
                "fuzzy_signature": "",
                "numeric_slots": [],
                "grouped_display_text": "",
                "display_template": "",
            }
        cache_key = self._structure_fuzzy_metadata_cache_key(
            structure_obj=structure_obj,
            runtime_bound_attribute_units=runtime_bound_attribute_units,
        ) if bool(self._config.get("structure_fuzzy_metadata_runtime_cache_enabled", True)) else None
        metadata_cache = (
            self._runtime_cache.get("structure_fuzzy_metadata", {})
            if isinstance(self._runtime_cache, dict)
            else {}
        )
        if cache_key and isinstance(metadata_cache, dict) and cache_key in metadata_cache:
            self._increment_runtime_metric("structure_fuzzy_metadata_cache_hit_count", 1)
            return self._clone_structure_fuzzy_metadata(metadata_cache[cache_key])
        structure = structure_obj.get("structure", {})
        sequence_groups = list(structure.get("sequence_groups", []))
        if not sequence_groups:
            result = {
                "fuzzy_signature": "",
                "numeric_slots": [],
                "grouped_display_text": str(structure.get("display_text", structure_obj.get("id", ""))),
                "display_template": str(structure.get("display_text", structure_obj.get("id", ""))),
            }
            if cache_key and isinstance(metadata_cache, dict):
                metadata_cache[cache_key] = self._clone_structure_fuzzy_metadata(result)
                self._increment_runtime_metric("structure_fuzzy_metadata_cache_store_count", 1)
            return result

        normalized_group_signatures: list[str] = []
        numeric_slots: list[dict] = []
        grouped_segments: list[str] = []
        template_segments: list[str] = []
        numeric_index = 0

        for group in sequence_groups:
            units = sorted(
                [dict(unit) for unit in group.get("units", []) if isinstance(unit, dict)],
                key=lambda item: int(item.get("sequence_index", 0)),
            )
            if not units:
                continue
            units_by_id = {str(unit.get("unit_id", "")): unit for unit in units if str(unit.get("unit_id", ""))}
            unit_signatures: list[str] = []
            bundle_signatures: list[str] = []
            covered_ids: set[str] = set()
            visible_segments: list[str] = []
            template_group_segments: list[str] = []

            for bundle in sorted(
                [dict(bundle) for bundle in group.get("csa_bundles", []) if isinstance(bundle, dict)],
                key=lambda item: int(units_by_id.get(str(item.get("anchor_unit_id", "")), {}).get("sequence_index", 0)),
            ):
                anchor_id = str(bundle.get("anchor_unit_id", ""))
                anchor_unit = units_by_id.get(anchor_id, {})
                if not anchor_unit:
                    continue
                anchor_token = str(anchor_unit.get("token", ""))
                if not anchor_token:
                    continue
                member_ids = [
                    str(member_id)
                    for member_id in bundle.get("member_unit_ids", [])
                    if str(member_id) in units_by_id
                ]
                attr_tokens: list[str] = []
                attr_template_tokens: list[str] = []
                attr_signatures: list[str] = []
                for member_id in member_ids:
                    if member_id == anchor_id:
                        continue
                    member = units_by_id.get(member_id, {})
                    normalized_signature, slot_value = self._normalize_structure_child_signature(member)
                    if not normalized_signature:
                        continue
                    attr_signatures.append(normalized_signature)
                    if slot_value is not None:
                        numeric_slots.append({"family": str(member.get("attribute_name", "")), "value": slot_value})
                        placeholder = f"{{{{NUM{numeric_index}}}}}"
                        numeric_index += 1
                        attr_tokens.append(str(member.get("token", "")))
                        attr_template_tokens.append(placeholder)
                    elif str(member.get("token", "")):
                        attr_tokens.append(str(member.get("token", "")))
                        attr_template_tokens.append(str(member.get("token", "")))
                if attr_signatures:
                    bundle_signatures.append(
                        f"CSA[{self._normalize_structure_child_signature(anchor_unit)[0]}=>{'|'.join(sorted(attr_signatures))}]"
                    )
                covered_ids.update(member_ids)
                segment_tokens = [anchor_token, *[token for token in attr_tokens if token]]
                template_tokens = [anchor_token, *[token for token in attr_template_tokens if token]]
                if segment_tokens:
                    visible_segments.append(f"({' + '.join(segment_tokens)})")
                if template_tokens:
                    template_group_segments.append(f"({' + '.join(template_tokens)})")

            for unit in units:
                unit_id = str(unit.get("unit_id", ""))
                normalized_signature, slot_value = self._normalize_structure_child_signature(unit)
                if normalized_signature:
                    unit_signatures.append(normalized_signature)
                if unit_id in covered_ids:
                    continue
                token = str(unit.get("token", ""))
                if not token:
                    continue
                if slot_value is not None:
                    numeric_slots.append({"family": str(unit.get("attribute_name", "")), "value": slot_value})
                    placeholder = f"{{{{NUM{numeric_index}}}}}"
                    numeric_index += 1
                    visible_segments.append(token)
                    template_group_segments.append(placeholder)
                else:
                    visible_segments.append(token)
                    template_group_segments.append(token)

            unit_signatures = sorted(signature for signature in unit_signatures if signature)
            bundle_signatures = sorted(signature for signature in bundle_signatures if signature)
            unit_part = "|".join(unit_signatures)
            bundle_part = "|".join(bundle_signatures)
            if unit_part and bundle_part:
                normalized_group_signatures.append(f"U[{unit_part}]#B[{bundle_part}]")
            elif bundle_part:
                normalized_group_signatures.append(f"B[{bundle_part}]")
            elif unit_part:
                normalized_group_signatures.append(f"U[{unit_part}]")
            if visible_segments:
                grouped_segments.append(f"{{{' + '.join(visible_segments)}}}")
            if template_group_segments:
                template_segments.append(f"{{{' + '.join(template_group_segments)}}}")

        grouped_display_text = " / ".join(segment for segment in grouped_segments if segment)
        display_template = " / ".join(segment for segment in template_segments if segment)
        for attr_unit in runtime_bound_attribute_units or []:
            if not isinstance(attr_unit, dict):
                continue
            family = str(attr_unit.get("attribute_name", "") or "").strip()
            numeric_value = self._coerce_numeric(attr_unit.get("attribute_value"))
            if not family or numeric_value is None:
                continue
            meta = attr_unit.get("meta", {}) if isinstance(attr_unit.get("meta", {}), dict) else {}
            ext_meta = meta.get("ext", {}) if isinstance(meta.get("ext", {}), dict) else {}
            numeric_slots.append(
                {
                    "family": family,
                    "value": float(numeric_value),
                    "semantic_kind": "time_like"
                    if any(
                        key in ext_meta
                        for key in (
                            "time_bucket_id",
                            "time_bucket_ref_object_id",
                            "time_bucket_center_sec",
                            "time_basis",
                            "delta_sec",
                            "delta_value",
                        )
                    )
                    else "",
                }
            )
        result = {
            "fuzzy_signature": "||".join(signature for signature in normalized_group_signatures if signature),
            "numeric_slots": numeric_slots,
            "grouped_display_text": grouped_display_text,
            "display_template": display_template or grouped_display_text,
        }
        if cache_key and isinstance(metadata_cache, dict):
            metadata_cache[cache_key] = self._clone_structure_fuzzy_metadata(result)
            self._increment_runtime_metric("structure_fuzzy_metadata_cache_store_count", 1)
        return result

    def _structure_fuzzy_metadata_cache_key(
        self,
        *,
        structure_obj: dict | None,
        runtime_bound_attribute_units: list[dict] | None = None,
    ) -> tuple | None:
        if not isinstance(structure_obj, dict):
            return None
        structure_id = str(structure_obj.get("id", "") or "")
        if not structure_id:
            return None
        structure = structure_obj.get("structure", {}) if isinstance(structure_obj.get("structure", {}), dict) else {}
        signature = str(structure.get("content_signature", "") or "")
        updated_at = int(structure_obj.get("updated_at", 0) or 0)
        attr_key: tuple = ()
        if runtime_bound_attribute_units:
            attr_parts = []
            for unit in runtime_bound_attribute_units:
                if not isinstance(unit, dict):
                    continue
                family = str(unit.get("attribute_name", "") or "")
                value = str(unit.get("attribute_value", "") or "")
                meta = unit.get("meta", {}) if isinstance(unit.get("meta", {}), dict) else {}
                ext = meta.get("ext", {}) if isinstance(meta.get("ext", {}), dict) else {}
                time_marker = "|".join(
                    f"{key}={ext.get(key)}"
                    for key in (
                        "time_bucket_id",
                        "time_bucket_ref_object_id",
                        "time_bucket_center_sec",
                        "time_basis",
                        "delta_sec",
                        "delta_value",
                    )
                    if key in ext
                )
                attr_parts.append((family, value, time_marker))
            attr_key = tuple(sorted(attr_parts))
        return (structure_id, signature, updated_at, attr_key)

    @staticmethod
    def _clone_structure_fuzzy_metadata(metadata: dict) -> dict:
        if not isinstance(metadata, dict):
            return {
                "fuzzy_signature": "",
                "numeric_slots": [],
                "grouped_display_text": "",
                "display_template": "",
            }
        return {
            "fuzzy_signature": str(metadata.get("fuzzy_signature", "") or ""),
            "numeric_slots": [
                dict(slot)
                for slot in metadata.get("numeric_slots", [])
                if isinstance(slot, dict)
            ] if isinstance(metadata.get("numeric_slots", []), list) else [],
            "grouped_display_text": str(metadata.get("grouped_display_text", "") or ""),
            "display_template": str(metadata.get("display_template", "") or ""),
        }

    @staticmethod
    def _normalize_structure_child_signature(unit: dict) -> tuple[str, float | None]:
        role = str(unit.get("unit_role", unit.get("role", "")) or "")
        attribute_name = str(unit.get("attribute_name", ""))
        attribute_value = unit.get("attribute_value")
        numeric_value = StructureRetrievalEngine._coerce_numeric(attribute_value)
        if role == "attribute" and attribute_name and numeric_value is not None:
            return f"A_NUM_FAMILY:{attribute_name}", float(numeric_value)
        signature = str(unit.get("unit_signature", ""))
        if signature:
            return signature, None
        token = str(unit.get("token", ""))
        prefix = "P" if bool(unit.get("is_placeholder")) else ("A" if role == "attribute" else "F")
        return (f"{prefix}:{token}" if token else "", None)

    @staticmethod
    def _coerce_numeric(value) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _normalize_runtime_family_patterns(patterns_raw) -> list[str]:
        if not isinstance(patterns_raw, (list, tuple)):
            return []
        return [str(pattern).strip() for pattern in patterns_raw if str(pattern).strip()]

    @classmethod
    def _match_runtime_family_pattern(cls, family: str, patterns: list[str]) -> tuple[bool, int, str]:
        normalized_family = str(family or "").strip()
        normalized_patterns = cls._normalize_runtime_family_patterns(patterns)
        if not normalized_family or not normalized_patterns:
            return False, len(normalized_patterns), ""
        for index, pattern in enumerate(normalized_patterns):
            if pattern.endswith("*"):
                prefix = pattern[:-1].strip()
                if prefix and normalized_family.startswith(prefix):
                    return True, index, pattern
            elif normalized_family == pattern:
                return True, index, pattern
        return False, len(normalized_patterns), ""

    def _runtime_family_patterns_from_config(self, config_key: str, *, fallback_key: str | None = None) -> list[str]:
        patterns = self._normalize_runtime_family_patterns(self._config.get(config_key, []))
        if patterns or not fallback_key:
            return patterns
        return self._normalize_runtime_family_patterns(self._config.get(fallback_key, []))

    def _runtime_attribute_priority_meta(self, unit: dict, patterns: list[str]) -> dict:
        family = str(unit.get("attribute_name", "") or "").strip()
        matched, priority_rank, matched_pattern = self._match_runtime_family_pattern(family, patterns)
        meta = unit.get("meta", {}) if isinstance(unit.get("meta", {}), dict) else {}
        ext = meta.get("ext", {}) if isinstance(meta.get("ext", {}), dict) else {}
        numeric_value = self._coerce_numeric(unit.get("attribute_value"))
        abs_value = self._coerce_numeric(ext.get("projection_sort_abs_value"))
        if abs_value is None and numeric_value is not None:
            abs_value = abs(float(numeric_value))
        return {
            "family": family,
            "matched": bool(matched),
            "priority_rank": int(priority_rank),
            "matched_pattern": str(matched_pattern or ""),
            "numeric_value": numeric_value,
            "abs_value": 0.0 if abs_value is None else round(abs(float(abs_value)), 8),
        }

    def _summarize_runtime_priority_units(self, units: list[dict] | None, patterns: list[str]) -> dict:
        matched_families: dict[str, dict] = {}
        matched_patterns: list[str] = []
        matched_units = 0
        max_abs_value = 0.0
        for unit in units or []:
            if not isinstance(unit, dict):
                continue
            priority_meta = self._runtime_attribute_priority_meta(unit, patterns)
            if not priority_meta.get("matched"):
                continue
            matched_units += 1
            family = str(priority_meta.get("family", "") or "")
            matched_pattern = str(priority_meta.get("matched_pattern", "") or "")
            priority_rank = int(priority_meta.get("priority_rank", len(patterns)))
            abs_value = float(priority_meta.get("abs_value", 0.0) or 0.0)
            max_abs_value = max(max_abs_value, abs_value)
            existing = matched_families.get(family)
            if existing is None or priority_rank < int(existing.get("priority_rank", len(patterns))) or abs_value > float(existing.get("abs_value", 0.0)):
                matched_families[family] = {
                    "priority_rank": priority_rank,
                    "matched_pattern": matched_pattern,
                    "abs_value": abs_value,
                }
            if matched_pattern and matched_pattern not in matched_patterns:
                matched_patterns.append(matched_pattern)
        ordered_families = [
            family
            for family, _meta in sorted(
                matched_families.items(),
                key=lambda item: (
                    int(item[1].get("priority_rank", len(patterns))),
                    -float(item[1].get("abs_value", 0.0)),
                    str(item[0]),
                ),
            )
        ]
        return {
            "matched_unit_count": int(matched_units),
            "matched_family_count": int(len(matched_families)),
            "matched_families": ordered_families,
            "matched_patterns": list(matched_patterns),
            "best_priority_rank": min(
                [int(meta.get("priority_rank", len(patterns))) for meta in matched_families.values()] or [len(patterns)]
            ),
            "max_abs_value": round(float(max_abs_value), 8),
        }

    def _summarize_fragment_runtime_priority(self, fragment: dict, patterns: list[str]) -> dict:
        fragment_units: list[dict] = []
        for group in fragment.get("sequence_groups", []) if isinstance(fragment.get("sequence_groups", []), list) else []:
            if not isinstance(group, dict):
                continue
            for unit in group.get("units", []) if isinstance(group.get("units", []), list) else []:
                if not isinstance(unit, dict):
                    continue
                fragment_units.append(unit)
        return self._summarize_runtime_priority_units(fragment_units, patterns)

    def _build_internal_runtime_attribute_groups(
        self,
        *,
        owner_id: str,
        owner_kind: str,
        runtime_bound_attribute_units: list[dict] | None,
        start_group_index: int,
        origin_frame_id: str,
        force_include: bool = False,
    ) -> list[dict]:
        if (not force_include) and (not bool(self._config.get("internal_fragment_include_runtime_bound_attributes", True))):
            return []
        max_count = max(0, int(self._config.get("internal_fragment_runtime_attribute_max_count", 8) or 8))
        if max_count <= 0:
            return []
        numeric_only = bool(self._config.get("internal_fragment_runtime_attribute_numeric_only", True))
        priority_enabled = bool(self._config.get("internal_fragment_runtime_attribute_priority_enabled", True))
        sort_by_abs_value = bool(self._config.get("internal_fragment_runtime_attribute_sort_by_abs_value_desc", True))
        priority_patterns = self._runtime_family_patterns_from_config(
            "internal_fragment_runtime_attribute_priority_patterns",
            fallback_key=None,
        )
        groups: list[dict] = []
        seen: set[tuple[str, str, str, str]] = set()
        owner_label = str(owner_id or owner_kind or "runtime")
        ranked_units: list[tuple[int, float, int, str, float | None, dict, dict, dict, str]] = []
        for raw_index, attr_unit in enumerate(runtime_bound_attribute_units or []):
            if not isinstance(attr_unit, dict):
                continue
            family = str(attr_unit.get("attribute_name", "") or "").strip()
            if not family:
                continue
            numeric_value = self._coerce_numeric(attr_unit.get("attribute_value"))
            if numeric_only and numeric_value is None:
                continue
            meta = attr_unit.get("meta", {}) if isinstance(attr_unit.get("meta", {}), dict) else {}
            ext_meta = meta.get("ext", {}) if isinstance(meta.get("ext", {}), dict) else {}
            priority_rank = len(priority_patterns)
            matched_pattern = ""
            if priority_enabled and priority_patterns:
                matched, priority_rank, matched_pattern = self._match_runtime_family_pattern(family, priority_patterns)
                if not matched:
                    priority_rank = len(priority_patterns)
            sort_value = -abs(float(numeric_value)) if (sort_by_abs_value and numeric_value is not None) else 0.0
            ranked_units.append(
                (
                    int(priority_rank),
                    float(sort_value),
                    int(raw_index),
                    family,
                    numeric_value,
                    meta,
                    ext_meta,
                    dict(attr_unit),
                    matched_pattern,
                )
            )
        ranked_units.sort(key=lambda item: (item[0], item[1], item[2]))
        for priority_rank, _sort_value, raw_index, family, numeric_value, meta, ext_meta, attr_unit, matched_pattern in ranked_units:
            if len(groups) >= max_count:
                break
            discrete_value = "" if numeric_value is not None else str(attr_unit.get("attribute_value", "") or "").strip()
            dedupe_key = (
                family,
                f"{round(float(numeric_value), 8):.8f}" if numeric_value is not None else discrete_value,
                str(ext_meta.get("time_bucket_id", "") or ""),
                str(ext_meta.get("time_basis", "") or ""),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            if numeric_value is not None:
                token = f"{family}:{round(float(numeric_value), 6)}"
                attribute_value = round(float(numeric_value), 8)
                value_type = "numerical"
            else:
                raw_token = str(
                    attr_unit.get("token", "")
                    or attr_unit.get("display_text", "")
                    or attr_unit.get("raw", "")
                    or ""
                ).strip()
                attribute_value = attr_unit.get("attribute_value")
                token = raw_token or (f"{family}:{attribute_value}" if attribute_value not in {None, ""} else family)
                value_type = str(attr_unit.get("value_type", "discrete") or "discrete")
            group_index = int(start_group_index + len(groups))
            unit_id = f"internal_attr::{owner_kind}::{owner_label}::{family}::{group_index}::{raw_index}"
            unit_meta = dict(meta)
            unit_ext = unit_meta.get("ext", {}) if isinstance(unit_meta.get("ext", {}), dict) else {}
            unit_ext = dict(unit_ext)
            unit_ext["projection_priority_rank"] = int(priority_rank)
            if matched_pattern:
                unit_ext["projection_priority_pattern"] = str(matched_pattern)
            if numeric_value is not None:
                unit_ext["projection_sort_abs_value"] = round(abs(float(numeric_value)), 8)
            unit_meta["ext"] = unit_ext
            unit = {
                "unit_id": unit_id,
                "object_type": "sa",
                "token": token,
                "display_text": token,
                "unit_role": "attribute",
                "unit_signature": f"A:{family}",
                "sequence_index": 0,
                "group_index": group_index,
                "source_group_index": group_index,
                "source_type": "internal_runtime_attribute",
                "origin_frame_id": origin_frame_id,
                "er": 0.0,
                "ev": 0.0,
                "total_energy": 0.0,
                "is_punctuation": False,
                "display_visible": True,
                "is_placeholder": False,
                "bundle_id": "",
                "bundle_anchor_unit_id": "",
                "bundle_anchor_signature": "",
                "bundle_signature": "",
                "bundle_member_unit_ids": [],
                "bundle_member_signatures": [],
                "attribute_name": family,
                "attribute_value": attribute_value,
                "value_type": value_type,
                "meta": unit_meta,
            }
            groups.append(
                {
                    "group_index": group_index,
                    "source_group_index": group_index,
                    "source_type": "internal_runtime_attribute",
                    "origin_frame_id": origin_frame_id,
                    "tokens": [token],
                    "units": [unit],
                    "csa_bundles": [],
                }
            )
        return groups

    @staticmethod
    def _collect_runtime_bound_attribute_units_for_structure_ids(
        *,
        structure_ids: list[str],
        runtime_bound_attribute_map: dict[str, list[dict]] | None,
    ) -> list[dict]:
        if not runtime_bound_attribute_map:
            return []
        collected: list[dict] = []
        for structure_id in structure_ids:
            for unit in runtime_bound_attribute_map.get(str(structure_id), []) or []:
                if isinstance(unit, dict):
                    collected.append(dict(unit))
        return collected

    def _make_placeholder_unit(self, *, placeholder_token: str, order_index: int, origin_frame_id: str) -> dict:
        return {
            "unit_id": f"placeholder::{placeholder_token}::{order_index}",
            "object_type": "st_placeholder",
            "token": placeholder_token,
            "display_text": placeholder_token,
            "unit_role": "placeholder",
            "unit_signature": f"P:{placeholder_token}",
            "sequence_index": order_index,
            "group_index": order_index,
            "source_group_index": order_index,
            "source_type": "structure_local",
            "origin_frame_id": origin_frame_id,
            "er": 0.0,
            "ev": 0.0,
            "total_energy": 0.0,
            "is_punctuation": False,
            "display_visible": True,
            "is_placeholder": True,
            "bundle_id": "",
            "bundle_anchor_unit_id": "",
            "bundle_anchor_signature": "",
            "bundle_signature": "",
            "bundle_member_unit_ids": [],
            "bundle_member_signatures": [],
        }

    def _profile_from_units(self, *, units: list[dict], cut_engine, ext: dict | None = None) -> dict:
        groups = []
        for order_index, unit in enumerate(units):
            groups.append(
                {
                    "group_index": order_index,
                    "source_type": unit.get("source_type", "structure_local"),
                    "origin_frame_id": unit.get("origin_frame_id", ""),
                    "units": [{**unit, "group_index": order_index, "sequence_index": order_index}],
                }
            )
        profile = cut_engine.build_sequence_profile_from_groups(groups)
        merged_ext = dict(profile.get("ext", {}))
        merged_ext.update(ext or {})
        profile["ext"] = merged_ext
        return profile

    def _select_anchor_item(
        self,
        *,
        cam_items: list[dict],
        budget_er_map: dict[str, float],
        budget_ev_map: dict[str, float],
        temp_anchor_fatigue: dict[str, float],
        skip_structure_ids: set[str] | None,
        now_ms: int,
    ) -> dict | None:
        ranked = []
        anchor_bonus_enabled = bool(self._config.get("structure_anchor_runtime_family_bonus_enabled", True))
        anchor_bonus_patterns = self._runtime_family_patterns_from_config(
            "structure_anchor_runtime_family_bonus_patterns",
            fallback_key="internal_fragment_runtime_attribute_priority_patterns",
        )
        anchor_bonus_value = max(0.0, float(self._config.get("structure_anchor_runtime_family_bonus_value", 0.55) or 0.55))
        anchor_bonus_abs_gain = max(0.0, float(self._config.get("structure_anchor_runtime_family_bonus_abs_gain", 0.05) or 0.05))
        anchor_bonus_abs_value_cap = max(0.0, float(self._config.get("structure_anchor_runtime_family_bonus_abs_value_cap", 2.0) or 2.0))
        anchor_bonus_max_families = max(1, int(self._config.get("structure_anchor_runtime_family_bonus_max_families", 2) or 2))
        anchor_priority_rank_gain = max(0.0, float(self._config.get("structure_anchor_runtime_family_priority_rank_gain", 0.45) or 0.45))
        for item in cam_items:
            if skip_structure_ids and item["structure_id"] in skip_structure_ids:
                continue
            structure_obj = item["structure_obj"]
            runtime_stats = self._preview_structure_stats(structure_obj, now_ms=now_ms)
            total_energy = round(
                float(budget_er_map.get(item["structure_id"], 0.0)) + float(budget_ev_map.get(item["structure_id"], 0.0)),
                8,
            )
            temp_fatigue = float(temp_anchor_fatigue.get(item["structure_id"], 0.0))
            score = self._anchor_score(
                total_energy=total_energy,
                runtime_weight=float(runtime_stats["runtime_weight"]),
                temp_fatigue=temp_fatigue,
            )
            runtime_priority = self._summarize_runtime_priority_units(
                item.get("runtime_bound_attribute_units", []) or [],
                anchor_bonus_patterns,
            )
            runtime_family_bonus = 0.0
            if anchor_bonus_enabled and int(runtime_priority.get("matched_family_count", 0) or 0) > 0:
                rank_scale = 1.0
                if anchor_bonus_patterns:
                    max_rank = max(1, len(anchor_bonus_patterns) - 1)
                    best_rank = max(0, min(max_rank, int(runtime_priority.get("best_priority_rank", len(anchor_bonus_patterns)) or len(anchor_bonus_patterns))))
                    rank_scale += anchor_priority_rank_gain * (float(max_rank - best_rank) / float(max_rank))
                runtime_family_bonus = (
                    anchor_bonus_value
                    * min(anchor_bonus_max_families, int(runtime_priority.get("matched_family_count", 0) or 0))
                    * rank_scale
                )
                if float(runtime_priority.get("max_abs_value", 0.0) or 0.0) > 0.0 and anchor_bonus_abs_gain > 0.0:
                    runtime_family_bonus += anchor_bonus_abs_gain * min(
                        float(runtime_priority.get("max_abs_value", 0.0) or 0.0),
                        anchor_bonus_abs_value_cap,
                    )
            ranked.append((score + runtime_family_bonus, item["order_index"], temp_fatigue, runtime_stats, item, score, runtime_family_bonus, runtime_priority))
        if not ranked:
            return None
        ranked.sort(key=lambda payload: (-payload[0], payload[1]))
        score, _, temp_fatigue, runtime_stats, item, base_score, runtime_family_bonus, runtime_priority = ranked[0]
        return {
            **item,
            "anchor_score": round(float(score), 8),
            "anchor_score_base": round(float(base_score), 8),
            "anchor_runtime_family_bonus": round(float(runtime_family_bonus), 8),
            "anchor_runtime_priority_families": list(runtime_priority.get("matched_families", [])),
            "temp_anchor_fatigue": round(float(temp_fatigue), 8),
            "runtime_weight": runtime_stats["runtime_weight"],
        }

    def _build_implicit_single_group_debug(
        self,
        *,
        anchor_item: dict,
        structure_store,
        cut_engine,
        runtime_profile: dict,
        tick_id: str,
        round_index: int,
    ) -> dict:
        structure_id = str(anchor_item.get("structure_id", ""))
        structure_obj = anchor_item.get("structure_obj") or structure_store.get(structure_id)
        display_text = self._structure_display_text(structure_obj) or structure_id
        single_profile = self._profile_from_units(
            units=[
                self._make_structure_unit(
                    structure_id=structure_id,
                    display_text=display_text,
                    structure_obj=structure_obj,
                    er=float(anchor_item.get("er", 0.0)),
                    ev=float(anchor_item.get("ev", 0.0)),
                    order_index=0,
                    source_type="structure_owner",
                    origin_frame_id=tick_id,
                )
            ],
            cut_engine=cut_engine,
            ext={"kind": "implicit_single_structure_group", "owner_id": structure_id},
        )
        owner_placeholder = self._owner_placeholder_token(
            owner_kind="st",
            owner_id=structure_id,
            owner_display_text=display_text,
        )
        residual_profile = self._build_relative_residual_profile(
            full_profile=runtime_profile,
            covered_structure_ids=[structure_id],
            owner_placeholder=owner_placeholder,
            cut_engine=cut_engine,
            origin_frame_id=f"{tick_id}:{round_index}:single:{structure_id}",
        ) or {"content_signature": "", "flat_tokens": [], "sequence_groups": []}
        runtime_total = max(1e-8, self._profile_total_energy(runtime_profile))
        anchor_total = round(float(anchor_item.get("er", 0.0)) + float(anchor_item.get("ev", 0.0)), 8)
        return {
            "group_id": self._implicit_single_group_id(structure_id),
            "group_kind": "implicit_single_st",
            "synthetic": True,
            "display_text": display_text,
            "required_structure_ids": [structure_id],
            "bias_structure_ids": [],
            "required_structures": self._build_structure_refs([structure_id], structure_store),
            "bias_structures": [],
            "avg_energy_profile": {structure_id: 1.0},
            "content_signature": single_profile.get("content_signature", ""),
            "temporal_signature": single_profile.get("content_signature", ""),
            "flat_tokens": list(single_profile.get("flat_tokens", [])),
            "sequence_groups": list(single_profile.get("sequence_groups", [])),
            "base_weight": round(float(anchor_item.get("runtime_weight", 1.0)), 8),
            "recent_gain": 1.0,
            "fatigue": 0.0,
            "runtime_weight": round(float(anchor_item.get("runtime_weight", 1.0)), 8),
            "score": 1.0,
            "competition_score": 1.0,
            "similarity": 1.0,
            "base_similarity": 1.0,
            "coverage_ratio": round(anchor_total / runtime_total, 8),
            "structure_ratio": 1.0,
            "wave_similarity": 1.0,
            "path_strength": 1.0,
            "entry_runtime_weight": round(float(anchor_item.get("runtime_weight", 1.0)), 8),
            "chain_depth": 0,
            "owner_kind": "st",
            "owner_id": structure_id,
            "common_part": {
                "common_tokens": list(single_profile.get("flat_tokens", [])),
                "common_length": int(single_profile.get("unit_count", 1)),
                "common_group_count": len(single_profile.get("sequence_groups", [])),
                "common_signature": single_profile.get("content_signature", ""),
                "common_display": single_profile.get("display_text", display_text),
                "common_groups": list(single_profile.get("sequence_groups", [])),
                "matched_pairs": [],
                "existing_range": [0, len(single_profile.get("sequence_groups", []))],
                "incoming_range": [0, len(single_profile.get("sequence_groups", []))],
                "matched_existing_group_indices": list(range(len(single_profile.get("sequence_groups", [])))),
                "matched_incoming_group_indices": list(range(len(single_profile.get("sequence_groups", [])))),
                "residual_existing_tokens": [],
                "residual_incoming_tokens": list(residual_profile.get("flat_tokens", [])),
                "residual_existing_groups": [],
                "residual_incoming_groups": list(residual_profile.get("sequence_groups", [])),
                "residual_existing_signature": "",
                "residual_incoming_signature": residual_profile.get("content_signature", ""),
            },
        }

    @staticmethod
    def _implicit_single_group_id(structure_id: str) -> str:
        return f"sg_single_{structure_id}"

    def _anchor_score(self, *, total_energy: float, runtime_weight: float, temp_fatigue: float) -> float:
        if total_energy <= 0.0:
            return 0.0
        runtime_signal = math.tanh(math.log(max(1e-6, float(runtime_weight))) / max(0.25, float(self._config.get("structure_anchor_runtime_scale", 1.35))))
        runtime_factor = math.exp(float(self._config.get("structure_anchor_runtime_gain", 0.22)) * runtime_signal)
        return round(float(total_energy) * runtime_factor / (1.0 + max(0.0, float(temp_fatigue))), 8)

    def _build_anchor_debug(self, anchor_item: dict) -> dict:
        return {
            "structure_id": anchor_item.get("structure_id", ""),
            "display_text": anchor_item.get("display_text", ""),
            "sequence_groups": list((anchor_item.get("structure_obj") or {}).get("structure", {}).get("sequence_groups", [])),
            "er": round(float(anchor_item.get("er", 0.0)), 8),
            "ev": round(float(anchor_item.get("ev", 0.0)), 8),
            "total_energy": round(float(anchor_item.get("er", 0.0)) + float(anchor_item.get("ev", 0.0)), 8),
            "runtime_weight": round(float(anchor_item.get("runtime_weight", 1.0)), 8),
            "temp_anchor_fatigue": round(float(anchor_item.get("temp_anchor_fatigue", 0.0)), 8),
            "anchor_score": round(float(anchor_item.get("anchor_score", 0.0)), 8),
            "anchor_score_base": round(float(anchor_item.get("anchor_score_base", 0.0)), 8),
            "anchor_runtime_family_bonus": round(float(anchor_item.get("anchor_runtime_family_bonus", 0.0)), 8),
            "anchor_runtime_priority_families": list(anchor_item.get("anchor_runtime_priority_families", [])),
        }

    def _resolve_anchor_chain_match(
        self,
        *,
        anchor_structure_id: str,
        runtime_profile: dict,
        budget_er_map: dict[str, float],
        budget_ev_map: dict[str, float],
        structure_store,
        group_store,
        pointer_index,
        cut_engine,
        trace_id: str,
        tick_id: str,
        round_index: int,
        now_ms: int,
    ) -> tuple[dict, dict | None, list[dict]]:
        candidate_details: list[dict] = []
        lookup = self._collect_local_group_candidates(
            owner_kind="st",
            owner_id=anchor_structure_id,
            structure_store=structure_store,
            group_store=group_store,
            pointer_index=pointer_index,
            cut_engine=cut_engine,
            trace_id=trace_id,
            tick_id=tick_id,
            now_ms=now_ms,
        )
        best, local_details = self._best_group_match(
            anchor_structure_id=anchor_structure_id,
            runtime_profile=runtime_profile,
            budget_er_map=budget_er_map,
            budget_ev_map=budget_ev_map,
            candidates=lookup.get("candidates", []),
            structure_store=structure_store,
            group_store=group_store,
            cut_engine=cut_engine,
            now_ms=now_ms,
            min_required_count=2,
            parent_match=None,
        )
        candidate_details = self._upsert_group_details(candidate_details, local_details)
        if not best:
            return {
                "candidate_source": "anchor_structure_chain",
                "used_fallback": bool(lookup.get("used_fallback")),
                "chain_steps": lookup.get("chain_steps", []),
            }, None, candidate_details

        max_depth = max(1, int(runtime_profile.get("unit_count", len(runtime_profile.get("flat_tokens", [])))))
        seen_group_ids = {best.get("group_id", "")}
        chain_steps = list(lookup.get("chain_steps", []))
        for depth in range(1, max_depth + 1):
            child_lookup = self._collect_local_group_candidates(
                owner_kind="sg",
                owner_id=best.get("group_id", ""),
                structure_store=structure_store,
                group_store=group_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
                trace_id=trace_id,
                tick_id=tick_id,
                now_ms=now_ms,
            )
            chain_steps.append(
                {
                    "owner_kind": "sg",
                    "owner_id": best.get("group_id", ""),
                    "owner_display_text": best.get("display_text", ""),
                    "candidate_count": len(child_lookup.get("candidates", [])),
                    "round_index": round_index,
                    "depth": depth,
                }
            )
            child_best, child_details = self._best_group_match(
                anchor_structure_id=anchor_structure_id,
                runtime_profile=runtime_profile,
                budget_er_map=budget_er_map,
                budget_ev_map=budget_ev_map,
                candidates=[candidate for candidate in child_lookup.get("candidates", []) if candidate.get("group_id", "") not in seen_group_ids],
                structure_store=structure_store,
                group_store=group_store,
                cut_engine=cut_engine,
                now_ms=now_ms,
                min_required_count=max(len(best.get("required_ids", [])) + 1, 2),
                parent_match=best,
            )
            candidate_details = self._upsert_group_details(candidate_details, child_details)
            if not child_best:
                break
            best = child_best
            seen_group_ids.add(best.get("group_id", ""))
        return {
            "candidate_source": "anchor_structure_chain",
            "used_fallback": bool(lookup.get("used_fallback")),
            "chain_steps": chain_steps,
        }, best, candidate_details

    def _collect_local_group_candidates(
        self,
        *,
        owner_kind: str,
        owner_id: str,
        structure_store,
        group_store,
        pointer_index,
        cut_engine,
        trace_id: str,
        tick_id: str,
        now_ms: int,
    ) -> dict:
        owner_ctx = self._open_owner_context(
            owner_kind=owner_kind,
            owner_id=owner_id,
            structure_store=structure_store,
            group_store=group_store,
            pointer_index=pointer_index,
            cut_engine=cut_engine,
            trace_id=trace_id,
            tick_id=tick_id,
        )
        if not owner_ctx:
            return {"candidates": [], "used_fallback": False, "chain_steps": []}
        numeric_anchor = self._extract_numeric_atomic_structure(owner_ctx.get("structure_obj")) if owner_kind == "st" else None
        if numeric_anchor and pointer_index is not None:
            candidates = self._collect_numeric_bucket_group_candidates(
                numeric_anchor=numeric_anchor,
                pointer_index=pointer_index,
                structure_store=structure_store,
                group_store=group_store,
                cut_engine=cut_engine,
                trace_id=trace_id,
                tick_id=tick_id,
                now_ms=now_ms,
            )
        else:
            candidates = self._group_candidates_from_owner_ctx(
                owner_ctx=owner_ctx,
                structure_store=structure_store,
                group_store=group_store,
                cut_engine=cut_engine,
                now_ms=now_ms,
            )
        candidates.sort(
            key=lambda item: (
                -float(item.get("entry_runtime_weight", 0.0)),
                -float(item.get("group_runtime_weight", 0.0)),
                item.get("group_id", ""),
            )
        )
        return {
            "candidates": candidates,
            "used_fallback": bool(owner_ctx.get("used_fallback")),
            "chain_steps": [
                {
                    "owner_kind": owner_kind,
                    "owner_id": owner_id,
                    "owner_display_text": owner_ctx.get("owner_display_text", owner_id),
                    "candidate_count": len(candidates),
                }
            ],
        }

    def _group_candidates_from_owner_ctx(self, *, owner_ctx: dict, structure_store, group_store, cut_engine, now_ms: int) -> list[dict]:
        candidates = []
        owner_kind = str(owner_ctx.get("owner_kind", ""))
        owner_id = str(owner_ctx.get("owner_id", ""))
        owner_display_text = owner_ctx.get("owner_display_text", owner_id)
        for entry in list(owner_ctx.get("group_table", [])):
            self._ensure_group_entry_schema(entry)
            group_id = str(entry.get("group_id", ""))
            group_obj = group_store.get(group_id)
            if not group_obj:
                continue
            relative_profile = self._group_entry_relative_profile(
                owner_ctx=owner_ctx,
                entry=entry,
                group_obj=group_obj,
                cut_engine=cut_engine,
            )
            if not relative_profile:
                continue
            entry_stats = self._preview_entry_stats(entry, now_ms=now_ms)
            group_stats = self._preview_group_stats(group_obj, now_ms=now_ms)
            required_ids = [str(structure_id) for structure_id in group_obj.get("required_structure_ids", []) if str(structure_id)]
            candidates.append(
                {
                    "owner_kind": owner_kind,
                    "owner_id": owner_id,
                    "owner_display_text": owner_display_text,
                    "entry_ref": entry,
                    "entry_id": entry.get("entry_id", ""),
                    "entry_runtime_weight": entry_stats["runtime_weight"],
                    "group_id": group_id,
                    "group_obj": group_obj,
                    "group_runtime_weight": group_stats["runtime_weight"],
                    "relative_profile": relative_profile,
                    "required_ids": required_ids,
                }
            )
        return candidates

    @staticmethod
    def _merge_match_context_payload(base_payload: dict | None, entry: dict | None = None) -> dict | None:
        if not isinstance(base_payload, dict) and not isinstance(entry, dict):
            return None
        payload = dict(base_payload or {})
        if not isinstance(entry, dict):
            return payload
        entry_ext = dict(entry.get("ext", {}) or {}) if isinstance(entry.get("ext"), dict) else {}
        payload["match_entry"] = dict(entry)
        base_ext = dict(payload.get("ext", {}) or {}) if isinstance(payload.get("ext"), dict) else {}
        merged_ext = dict(base_ext)
        merged_ext.update(entry_ext)
        if merged_ext:
            payload["ext"] = merged_ext
        meta = dict(payload.get("meta", {}) or {}) if isinstance(payload.get("meta"), dict) else {}
        meta_ext = dict(meta.get("ext", {}) or {}) if isinstance(meta.get("ext"), dict) else {}
        meta_ext.update(entry_ext)
        if meta_ext:
            meta["ext"] = meta_ext
            payload["meta"] = meta
        for key in (
            "source_em_id",
            "memory_id",
            "source_memory_created_at",
            "memory_created_at",
            "created_at",
            "updated_at",
            "last_updated_at",
            "residual_origin_kind",
            "residual_kind",
        ):
            if payload.get(key) not in (None, "", [], {}):
                continue
            value = entry.get(key)
            if value in (None, "", [], {}):
                value = entry_ext.get(key)
            if value not in (None, "", [], {}):
                payload[key] = value
        if payload.get("object_type") in (None, ""):
            residual_kind = str(payload.get("residual_origin_kind", "") or entry_ext.get("residual_origin_kind", "") or "")
            source_em_id = str(payload.get("source_em_id", "") or entry_ext.get("source_em_id", "") or "")
            memory_id = str(payload.get("memory_id", "") or entry_ext.get("memory_id", "") or "")
            if source_em_id.startswith("em_") or memory_id.startswith("em_") or "memory" in residual_kind:
                payload["object_type"] = "em"
        return payload

    def _collect_numeric_bucket_group_candidates(
        self,
        *,
        numeric_anchor: dict,
        pointer_index,
        structure_store,
        group_store,
        cut_engine,
        trace_id: str,
        tick_id: str,
        now_ms: int,
    ) -> list[dict]:
        buckets = pointer_index.resolve_numeric_buckets(
            attribute_name=numeric_anchor.get("family", ""),
            value=numeric_anchor.get("value"),
            create_if_missing=True,
            neighbor_count=max(1, int(self._config.get("numeric_bucket_neighbor_count", 2))),
        )
        candidates = []
        seen_owner_ids: set[str] = set()
        for bucket in buckets:
            for bucket_owner_id in bucket.get("candidate_ids", []):
                bucket_owner_id = str(bucket_owner_id)
                if not bucket_owner_id or bucket_owner_id in seen_owner_ids:
                    continue
                seen_owner_ids.add(bucket_owner_id)
                bucket_owner_ctx = self._open_owner_context(
                    owner_kind="st",
                    owner_id=bucket_owner_id,
                    structure_store=structure_store,
                    group_store=group_store,
                    pointer_index=pointer_index,
                    cut_engine=cut_engine,
                    trace_id=trace_id,
                    tick_id=tick_id,
                )
                if not bucket_owner_ctx:
                    continue
                candidates.extend(
                    self._group_candidates_from_owner_ctx(
                        owner_ctx=bucket_owner_ctx,
                        structure_store=structure_store,
                        group_store=group_store,
                        cut_engine=cut_engine,
                        now_ms=now_ms,
                    )
                )
        return candidates

    def _extract_numeric_atomic_structure(self, structure_obj: dict | None) -> dict | None:
        if not structure_obj:
            return None
        sequence_groups = list(structure_obj.get("structure", {}).get("sequence_groups", []))
        units = [
            dict(unit)
            for group in sequence_groups
            for unit in group.get("units", [])
            if isinstance(unit, dict)
        ]
        if len(units) != 1:
            return None
        unit = units[0]
        family = str(unit.get("attribute_name", ""))
        numeric_value = self._coerce_numeric(unit.get("attribute_value"))
        if str(unit.get("unit_role", unit.get("role", "")) or "") != "attribute" or not family or numeric_value is None:
            return None
        return {"family": family, "value": numeric_value}

    def _best_group_match(
        self,
        *,
        anchor_structure_id: str,
        runtime_profile: dict,
        budget_er_map: dict[str, float],
        budget_ev_map: dict[str, float],
        candidates: list[dict],
        structure_store,
        group_store,
        cut_engine,
        now_ms: int,
        min_required_count: int,
        parent_match: dict | None,
    ) -> tuple[dict | None, list[dict]]:
        del group_store
        best = None
        candidate_details = []
        current_total_energy = max(1e-8, self._profile_total_energy(runtime_profile))
        runtime_structure_counts = self._count_structure_ids(self._extract_structure_ids_from_profile(runtime_profile))
        for candidate in candidates:
            group_obj = candidate.get("group_obj") or {}
            required_ids = list(candidate.get("required_ids", []) or group_obj.get("required_structure_ids", []))
            min_required = max(1, int(min_required_count))
            skip_reason = ""
            required_counts_covered = self._structure_id_counts_cover(
                required_counts=self._count_structure_ids(required_ids),
                available_counts=runtime_structure_counts,
            )
            if len(required_ids) < min_required:
                skip_reason = "below_min_required_count"
            elif anchor_structure_id not in required_ids:
                skip_reason = "missing_anchor_structure"
            if skip_reason:
                detail = self._build_group_skip_detail(
                    candidate=candidate,
                    group_obj=group_obj,
                    required_ids=required_ids,
                    skip_reason=skip_reason,
                    min_required_count=min_required,
                )
                candidate_details.append(detail)
                continue

            group_profile = self._group_full_profile(group_obj=group_obj, structure_store=structure_store, cut_engine=cut_engine)
            common_part = cut_engine.maximum_common_part(
                group_profile.get("sequence_groups", []),
                runtime_profile.get("sequence_groups", []),
            )
            existing_length = max(1, len(required_ids) or int(group_profile.get("unit_count", 0)))
            matched_current_units = self._collect_matched_units_from_common_part(runtime_profile, common_part, use_existing_side=False)
            matched_current_ids = self._matched_structure_ids_from_units(matched_current_units)
            coverage_ratio = round(
                self._profile_total_energy_from_units(matched_current_units) / current_total_energy,
                8,
            ) if current_total_energy > 0 else 0.0
            structure_ratio = round(
                max(0.0, min(1.0, float(int(common_part.get("common_length", 0))) / max(1, existing_length))),
                8,
            )
            matched_existing_length = int(common_part.get("matched_existing_unit_count", 0))
            full_structure_included = bool(
                int(common_part.get("common_length", 0)) > 0
                and not common_part.get("residual_existing_signature", "")
                and matched_existing_length >= existing_length
            )
            contains_anchor = anchor_structure_id in matched_current_ids
            wave_similarity = self._wave_similarity(
                required_ids=required_ids,
                budget_er_map=budget_er_map,
                budget_ev_map=budget_ev_map,
                avg_energy_profile=group_obj.get("avg_energy_profile", {}),
            )
            path_strength = self._path_strength(
                group_runtime_weight=float(candidate.get("group_runtime_weight", 1.0)),
                entry_runtime_weight=float(candidate.get("entry_runtime_weight", 1.0)),
            )
            base_similarity = self._compose_group_match_score(
                coverage_ratio=coverage_ratio,
                structure_ratio=structure_ratio,
                wave_similarity=wave_similarity,
            )
            context_support_hint = min(
                1.0,
                0.2
                + (0.2 if candidate.get("owner_id", "") else 0.0)
                + (0.15 if candidate.get("entry_id", "") else 0.0)
                + (0.45 * max(0.0, min(1.0, float(path_strength) / max(1.0, float(path_strength) + 1.0)))),
            )
            v2_breakdown = self._build_group_match_score_v2_breakdown(
                base_score=base_similarity,
                matched_existing_units=self._collect_matched_units_from_common_part(group_profile, common_part, use_existing_side=True),
                matched_incoming_units=matched_current_units,
                bundle_constraints={
                    "exact": bool(common_part.get("bundle_constraints_ok_exact", True)),
                    "existing_included": bool(common_part.get("bundle_constraints_ok_existing_included", True)),
                    "incoming_included": bool(common_part.get("bundle_constraints_ok_incoming_included", True)),
                },
                full_structure_included=full_structure_included,
                context_payload=self._merge_match_context_payload(group_obj, candidate.get("entry_ref")),
                context_support_hint=context_support_hint,
                runtime_weight=float(candidate.get("group_runtime_weight", 1.0)),
                entry_runtime_weight=float(candidate.get("entry_runtime_weight", 1.0)),
                energy_profile_hint=wave_similarity,
            )
            blended_base_similarity = self._blend_v2_match_score(
                legacy_score=base_similarity,
                v2_score=float(v2_breakdown.get("score", base_similarity)),
            )
            soft_partial_enabled = bool(self._config.get("soft_partial_match_competition_enabled", True))
            soft_partial_min_score = max(0.0, float(self._config.get("match_scoring_v2_min_score", 0.18) or 0.0))
            soft_partial_eligible = bool(
                soft_partial_enabled
                and int(common_part.get("common_length", 0)) > 0
                and contains_anchor
                and len(required_ids) >= max(1, int(min_required_count))
                and not full_structure_included
                and float(blended_base_similarity) >= soft_partial_min_score
            )
            eligible = bool(
                contains_anchor
                and len(required_ids) >= max(1, int(min_required_count))
                and (full_structure_included or soft_partial_eligible)
            )
            if not required_counts_covered and not eligible:
                skip_reason = "required_structure_ids_not_covered"
            competition_score_legacy = self._apply_runtime_modulation(
                base_similarity=base_similarity,
                path_strength=path_strength,
            ) if eligible else 0.0
            competition_score_v2 = self._apply_runtime_modulation(
                base_similarity=float(v2_breakdown.get("score", 0.0)),
                path_strength=path_strength,
            ) if eligible else 0.0
            competition_score = self._apply_runtime_modulation(
                base_similarity=blended_base_similarity,
                path_strength=path_strength,
            ) if eligible else 0.0
            detail = {
                **self._build_group_debug_payload(group_obj, structure_store, cut_engine, group_profile=group_profile),
                "owner_kind": candidate.get("owner_kind", ""),
                "owner_id": candidate.get("owner_id", ""),
                "owner_display_text": candidate.get("owner_display_text", ""),
                "entry_id": candidate.get("entry_id", ""),
                "runtime_weight": round(float(candidate.get("group_runtime_weight", 1.0)), 8),
                "entry_runtime_weight": round(float(candidate.get("entry_runtime_weight", 1.0)), 8),
                "path_strength": round(float(path_strength), 8),
                "base_similarity": round(float(base_similarity), 8),
                "base_similarity_legacy": round(float(base_similarity), 8),
                "base_similarity_v2": round(float(v2_breakdown.get("score", 0.0)), 8),
                "coverage_ratio": round(float(coverage_ratio), 8),
                "structure_ratio": round(float(structure_ratio), 8),
                "wave_similarity": round(float(wave_similarity), 8),
                "score": round(float(competition_score), 8),
                "competition_score": round(float(competition_score), 8),
                "competition_score_legacy": round(float(competition_score_legacy), 8),
                "competition_score_v2": round(float(competition_score_v2), 8),
                "similarity": round(float(competition_score), 8),
                "full_structure_included": full_structure_included,
                "contains_anchor": contains_anchor,
                "eligible": eligible,
                "soft_partial_eligible": soft_partial_eligible,
                "eligibility_reason": "full_structure_included" if full_structure_included else ("soft_partial_score" if soft_partial_eligible else "not_eligible"),
                "skip_reason": str(skip_reason or ""),
                "common_part": common_part,
                "chain_depth": int(parent_match.get("chain_depth", 0) + 1 if parent_match else 1),
            }
            detail.update(self._flatten_match_score_v2(v2_breakdown))
            candidate_details.append(detail)
            if not eligible:
                continue
            if self._is_better_group_match(detail, best):
                best = {
                    "group_id": group_obj.get("id", ""),
                    "display_text": self._group_display_text(group_obj),
                    "required_ids": required_ids,
                    "competition_score": round(float(competition_score), 8),
                    "competition_score_legacy": round(float(competition_score_legacy), 8),
                    "competition_score_v2": round(float(competition_score_v2), 8),
                    "base_similarity": round(float(base_similarity), 8),
                    "base_similarity_legacy": round(float(base_similarity), 8),
                    "base_similarity_v2": round(float(v2_breakdown.get("score", 0.0)), 8),
                    "coverage_ratio": round(float(coverage_ratio), 8),
                    "structure_ratio": round(float(structure_ratio), 8),
                    "wave_similarity": round(float(wave_similarity), 8),
                    "path_strength": round(float(path_strength), 8),
                    "runtime_weight": round(float(candidate.get("group_runtime_weight", 1.0)), 8),
                    "entry_runtime_weight": round(float(candidate.get("entry_runtime_weight", 1.0)), 8),
                    "common_part": common_part,
                    "chain_depth": int(parent_match.get("chain_depth", 0) + 1 if parent_match else 1),
                    "owner_kind": candidate.get("owner_kind", ""),
                    "owner_id": candidate.get("owner_id", ""),
                    "path_entries": list(parent_match.get("path_entries", [])) if parent_match else [],
                }
                best.update(self._flatten_match_score_v2(v2_breakdown))
                best["path_entries"].append(
                    {
                        "owner_kind": candidate.get("owner_kind", ""),
                        "owner_id": candidate.get("owner_id", ""),
                        "entry_id": candidate.get("entry_id", ""),
                        "group_id": group_obj.get("id", ""),
                    }
                )
        candidate_details.sort(
            key=lambda item: (
                0 if item.get("eligible") else 1,
                -float(item.get("competition_score", 0.0)),
                -len(item.get("required_structure_ids", [])),
                -float(item.get("entry_runtime_weight", 0.0)),
                -float(item.get("runtime_weight", 0.0)),
            )
        )
        return best, candidate_details

    @staticmethod
    def _count_structure_ids(structure_ids: list[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for structure_id in structure_ids or []:
            sid = str(structure_id)
            if not sid:
                continue
            counts[sid] = int(counts.get(sid, 0)) + 1
        return counts

    @staticmethod
    def _structure_id_counts_cover(*, required_counts: dict[str, int], available_counts: dict[str, int]) -> bool:
        for structure_id, required_count in (required_counts or {}).items():
            if int(available_counts.get(structure_id, 0)) < int(required_count):
                return False
        return True

    def _build_group_skip_detail(
        self,
        *,
        candidate: dict,
        group_obj: dict,
        required_ids: list[str],
        skip_reason: str,
        min_required_count: int,
    ) -> dict:
        group_structure = group_obj.get("group_structure", {})
        grouped_display_text = self._group_display_text(group_obj)
        return {
            "group_id": group_obj.get("id", ""),
            "display_text": grouped_display_text,
            "grouped_display_text": grouped_display_text,
            "sequence_groups": list(group_structure.get("sequence_groups", [])),
            "required_structure_ids": list(required_ids),
            "bias_structure_ids": list(group_obj.get("bias_structure_ids", [])),
            "avg_energy_profile": dict(group_obj.get("avg_energy_profile", {})),
            "flat_tokens": list(group_structure.get("flat_tokens", [])),
            "content_signature": group_structure.get("content_signature", ""),
            "temporal_signature": group_structure.get("temporal_signature", group_structure.get("content_signature", "")),
            "owner_kind": candidate.get("owner_kind", ""),
            "owner_id": candidate.get("owner_id", ""),
            "owner_display_text": candidate.get("owner_display_text", ""),
            "entry_id": candidate.get("entry_id", ""),
            "runtime_weight": round(float(candidate.get("group_runtime_weight", 1.0)), 8),
            "entry_runtime_weight": round(float(candidate.get("entry_runtime_weight", 1.0)), 8),
            "path_strength": 0.0,
            "base_similarity": 0.0,
            "coverage_ratio": 0.0,
            "structure_ratio": 0.0,
            "wave_similarity": 0.0,
            "score": 0.0,
            "competition_score": 0.0,
            "similarity": 0.0,
            "full_structure_included": False,
            "contains_anchor": False,
            "eligible": False,
            "common_part": {},
            "chain_depth": 1,
            "skip_reason": str(skip_reason or ""),
            "min_required_count": int(min_required_count),
        }

    @staticmethod
    def _is_better_group_match(candidate: dict, current_best: dict | None) -> bool:
        if current_best is None:
            return True
        candidate_key = (
            float(candidate.get("competition_score", 0.0)),
            len(candidate.get("required_structure_ids", [])),
            float(candidate.get("entry_runtime_weight", 0.0)),
            float(candidate.get("runtime_weight", 0.0)),
        )
        current_key = (
            float(current_best.get("competition_score", 0.0)),
            len(current_best.get("required_ids", [])),
            float(current_best.get("entry_runtime_weight", 0.0)),
            float(current_best.get("runtime_weight", 0.0)),
        )
        return candidate_key > current_key

    def _path_strength(self, *, group_runtime_weight: float, entry_runtime_weight: float) -> float:
        return round(math.sqrt(max(1e-8, float(group_runtime_weight)) * max(1e-8, float(entry_runtime_weight))), 8)

    def _compose_group_match_score(self, *, coverage_ratio: float, structure_ratio: float, wave_similarity: float) -> float:
        joint_ratio = max(0.0, min(1.0, float(min(coverage_ratio, structure_ratio))))
        if joint_ratio >= 1.0 and wave_similarity >= 1.0:
            return 1.0
        coverage_curve = self._coverage_curve(joint_ratio)
        wave_floor = max(0.0, min(1.0, float(self._config.get("structure_wave_similarity_floor", 0.35))))
        shape_factor = wave_floor + (1.0 - wave_floor) * max(0.0, min(1.0, float(wave_similarity)))
        score = coverage_curve * shape_factor
        if score >= 1.0:
            return 1.0
        return round(max(0.0, score), 8)

    def _coverage_curve(self, raw_ratio: float) -> float:
        bounded = max(0.0, min(1.0, float(raw_ratio)))
        if bounded <= 0.0:
            return 0.0
        denoise = self._sigmoid(
            bounded,
            midpoint=float(self._config.get("structure_competition_noise_mid", 0.01)),
            slope=max(1e-6, float(self._config.get("structure_competition_noise_scale", 0.004))),
        )
        hill = self._hill_score(
            bounded,
            half_point=float(self._config.get("structure_competition_half_ratio", 0.1)),
            power=float(self._config.get("structure_competition_curve_power", 1.15)),
        )
        return round(max(0.0, hill * denoise), 8)

    @staticmethod
    def _sigmoid(value: float, *, midpoint: float, slope: float) -> float:
        safe_slope = max(1e-6, float(slope))
        try:
            result = 1.0 / (1.0 + math.exp(-(float(value) - float(midpoint)) / safe_slope))
        except OverflowError:
            result = 0.0 if value < midpoint else 1.0
        return round(max(0.0, min(1.0, result)), 8)

    @staticmethod
    def _hill_score(value: float, *, half_point: float, power: float) -> float:
        bounded = max(0.0, min(1.0, float(value)))
        if bounded <= 0.0:
            return 0.0
        safe_half = max(1e-6, min(1.0, float(half_point)))
        safe_power = max(0.2, float(power))
        numerator = pow(bounded, safe_power)
        denominator = numerator + pow(safe_half, safe_power)
        if denominator <= 0.0:
            return 0.0
        return round(max(0.0, min(1.0, numerator / denominator)), 8)

    def _apply_runtime_modulation(self, *, base_similarity: float, path_strength: float) -> float:
        base = max(0.0, min(1.0, float(base_similarity)))
        if base <= 0.0 or base >= 1.0:
            return round(base, 8)
        runtime_signal = math.tanh(
            math.log(max(1e-8, float(path_strength))) / max(0.25, float(self._config.get("structure_path_runtime_scale", 1.35)))
        )
        adjustment = float(self._config.get("structure_path_runtime_gain", 0.3)) * runtime_signal * base * (1.0 - base)
        adjusted = base + adjustment
        return round(max(0.0, min(1.0, adjusted)), 8)

    def _build_group_match_score_v2_breakdown(
        self,
        *,
        base_score: float,
        matched_existing_units: list[dict],
        matched_incoming_units: list[dict],
        bundle_constraints: dict | None,
        full_structure_included: bool,
        context_payload: dict | None,
        context_support_hint: float | None = None,
        runtime_weight: float = 1.0,
        entry_runtime_weight: float = 1.0,
        energy_profile_hint: float | None = None,
    ) -> dict[str, float | int]:
        return build_match_score_v2(
            config=self._config,
            base_score=base_score,
            matched_existing_units=matched_existing_units,
            matched_incoming_units=matched_incoming_units,
            bundle_constraints=bundle_constraints,
            full_structure_included=full_structure_included,
            context_payload=context_payload,
            context_support_hint=context_support_hint,
            runtime_weight=runtime_weight,
            entry_runtime_weight=entry_runtime_weight,
            energy_profile_hint=energy_profile_hint,
            now_ms=self._runtime_match_now_ms,
        )

    def _blend_v2_match_score(self, *, legacy_score: float, v2_score: float) -> float:
        legacy = max(0.0, min(1.0, float(legacy_score)))
        v2 = max(0.0, min(1.0, float(v2_score)))
        if not bool(self._config.get("match_scoring_v2_enabled", True)):
            return round(legacy, 8)
        if bool(self._config.get("match_scoring_v2_shadow_only", False)):
            return round(legacy, 8)
        blend = max(0.0, min(1.0, float(self._config.get("match_scoring_v2_blend_weight", 0.35))))
        return round((legacy * (1.0 - blend)) + (v2 * blend), 8)

    @staticmethod
    def _flatten_match_score_v2(breakdown: dict[str, Any]) -> dict[str, float | int]:
        return {
            "v2_score": round(float(breakdown.get("score", 0.0)), 8),
            "v2_base_score": round(float(breakdown.get("base_score", 0.0)), 8),
            "v2_blended_component_mean": round(float(breakdown.get("blended_component_mean", 0.0)), 8),
            "v2_numeric_score": round(float(breakdown.get("numeric_score", -1.0)), 8),
            "v2_numeric_family_count": int(breakdown.get("numeric_family_count", 0)),
            "v2_numeric_time_like_score": round(float(breakdown.get("numeric_time_like_score", -1.0)), 8),
            "v2_numeric_time_like_family_count": int(breakdown.get("numeric_time_like_family_count", 0)),
            "v2_numeric_time_like_wildcard_applied": bool(breakdown.get("numeric_time_like_wildcard_applied", False)),
            "v2_numeric_time_like_weight": round(float(breakdown.get("numeric_time_like_weight", 0.0)), 8),
            "v2_order_alignment_score": round(float(breakdown.get("order_alignment_score", -1.0)), 8),
            "v2_attribute_anchor_score": round(float(breakdown.get("attribute_anchor_score", -1.0)), 8),
            "v2_context_support_score": round(float(breakdown.get("context_support_score", -1.0)), 8),
            "v2_energy_profile_score": round(float(breakdown.get("energy_profile_score", -1.0)), 8),
            "v2_structure_inclusion_score": round(float(breakdown.get("structure_inclusion_score", 0.0)), 8),
            "v2_time_factor_soft_bonus": round(float(breakdown.get("time_factor_soft_bonus", 1.0)), 8),
            "v2_time_factor_applied": bool(breakdown.get("time_factor_applied", False)),
            "v2_time_factor_similarity": round(float(breakdown.get("time_factor_similarity", 0.0)), 8),
            "v2_time_factor_target_interval_sec": round(float(breakdown.get("time_factor_target_interval_sec", -1.0)), 8),
            "v2_time_factor_memory_age_sec": round(float(breakdown.get("time_factor_memory_age_sec", -1.0)), 8),
            "v2_available_component_count": int(breakdown.get("available_component_count", 0)),
            "v2_threshold_margin": round(float(breakdown.get("threshold_margin", 0.0)), 8),
        }

    def _wave_similarity(
        self,
        *,
        required_ids: list[str],
        budget_er_map: dict[str, float],
        budget_ev_map: dict[str, float],
        avg_energy_profile: dict[str, float],
    ) -> float:
        if not required_ids:
            return 0.0
        current = [max(0.0, float(budget_er_map.get(structure_id, 0.0)) + float(budget_ev_map.get(structure_id, 0.0))) for structure_id in required_ids]
        history = [max(0.0, float(avg_energy_profile.get(structure_id, 0.0))) for structure_id in required_ids]
        current = self._normalize_vector(current)
        history = self._normalize_vector(history)
        l1_similarity = 1.0 - 0.5 * sum(abs(left - right) for left, right in zip(current, history))
        centered_cosine = self._centered_cosine_similarity(current, history)
        slope_similarity = self._slope_similarity(current, history)
        return round(max(0.0, min(1.0, (l1_similarity + centered_cosine + slope_similarity) / 3.0)), 8)

    @staticmethod
    def _normalize_vector(values: list[float]) -> list[float]:
        total = sum(max(0.0, float(value)) for value in values)
        if total <= 0.0:
            return [1.0 / max(1, len(values)) for _ in values]
        return [max(0.0, float(value)) / total for value in values]

    @staticmethod
    def _centered_cosine_similarity(left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        mean_left = sum(left) / len(left)
        mean_right = sum(right) / len(right)
        left_centered = [value - mean_left for value in left]
        right_centered = [value - mean_right for value in right]
        norm_left = math.sqrt(sum(value * value for value in left_centered))
        norm_right = math.sqrt(sum(value * value for value in right_centered))
        if norm_left <= 1e-8 and norm_right <= 1e-8:
            return 1.0
        if norm_left <= 1e-8 or norm_right <= 1e-8:
            return 0.5
        cosine = sum(lv * rv for lv, rv in zip(left_centered, right_centered)) / (norm_left * norm_right)
        return max(0.0, min(1.0, 0.5 + 0.5 * cosine))

    @staticmethod
    def _slope_similarity(left: list[float], right: list[float]) -> float:
        if len(left) <= 1 or len(right) <= 1 or len(left) != len(right):
            return 1.0
        left_deltas = [left[index + 1] - left[index] for index in range(len(left) - 1)]
        right_deltas = [right[index + 1] - right[index] for index in range(len(right) - 1)]
        norm_left = sum(abs(value) for value in left_deltas)
        norm_right = sum(abs(value) for value in right_deltas)
        if norm_left > 0.0:
            left_deltas = [value / norm_left for value in left_deltas]
        if norm_right > 0.0:
            right_deltas = [value / norm_right for value in right_deltas]
        diff = sum(abs(lv - rv) for lv, rv in zip(left_deltas, right_deltas)) / max(1, len(left_deltas))
        return max(0.0, min(1.0, 1.0 - 0.5 * diff))

    def _collect_matched_units_from_common_part(self, profile: dict, common_part: dict, *, use_existing_side: bool) -> list[dict]:
        groups = list(profile.get("sequence_groups", []))
        matched_units = []
        group_key = "existing_group_index" if use_existing_side else "incoming_group_index"
        unit_key = "existing_unit_refs" if use_existing_side else "incoming_unit_refs"
        similarity_key = "matched_existing_unit_similarities" if use_existing_side else "matched_incoming_unit_similarities"
        global_similarity_map = {
            str(unit_id): float(similarity)
            for unit_id, similarity in common_part.get(similarity_key, {}).items()
            if str(unit_id)
        }
        for pair in common_part.get("matched_pairs", []):
            group_index = int(pair.get(group_key, -1))
            if group_index < 0 or group_index >= len(groups):
                continue
            needed_ids = {str(unit_id) for unit_id in pair.get(unit_key, []) if str(unit_id)}
            pair_similarity_map = {
                str(unit_id): float(similarity)
                for unit_id, similarity in pair.get(similarity_key, {}).items()
                if str(unit_id)
            }
            for unit in groups[group_index].get("units", []):
                unit_id = str(unit.get("unit_id", ""))
                if needed_ids and unit_id in needed_ids:
                    similarity = pair_similarity_map.get(unit_id, global_similarity_map.get(unit_id, 1.0))
                    matched_units.append({**dict(unit), "match_similarity": round(max(0.0, min(1.0, float(similarity))), 8)})
        return matched_units

    @staticmethod
    def _matched_structure_ids_from_units(units: list[dict]) -> list[str]:
        ordered = []
        seen = set()
        for unit in units:
            unit_id = str(unit.get("unit_id", ""))
            if not unit_id or unit.get("is_placeholder"):
                continue
            if unit_id in seen:
                continue
            seen.add(unit_id)
            ordered.append(unit_id)
        return ordered

    def _profile_total_energy(self, profile: dict) -> float:
        return self._profile_total_energy_from_units(self._collect_profile_units(profile))

    def _profile_er_ev_totals(self, profile: dict) -> tuple[float, float]:
        return self._profile_er_ev_totals_from_units(self._collect_profile_units(profile))

    @staticmethod
    def _profile_unit_count(profile: dict) -> int:
        return int(profile.get("unit_count", profile.get("token_count", len(profile.get("flat_tokens", [])))))

    def _profiles_fuzzy_equivalent(self, *, left_profile: dict, right_profile: dict, cut_engine) -> bool:
        common_part = cut_engine.maximum_common_part(
            left_profile.get("sequence_groups", []),
            right_profile.get("sequence_groups", []),
        )
        return bool(
            int(common_part.get("common_length", 0)) > 0
            and not common_part.get("residual_existing_signature", "")
            and not common_part.get("residual_incoming_signature", "")
            and int(common_part.get("matched_existing_unit_count", 0)) >= self._profile_unit_count(left_profile)
            and int(common_part.get("matched_incoming_unit_count", 0)) >= self._profile_unit_count(right_profile)
            # CSA 门控：两侧 bundle 约束也必须完全满足，避免属性跨对象拼接导致“看起来相等”。
            and bool(common_part.get("bundle_constraints_ok_exact", True))
        )

    @staticmethod
    def _profile_total_energy_from_units(units: list[dict]) -> float:
        return round(
            sum(
                (
                    max(0.0, float(unit.get("er", 0.0))) + max(0.0, float(unit.get("ev", 0.0)))
                ) * max(0.0, min(1.0, float(unit.get("match_similarity", 1.0))))
                for unit in units
                if isinstance(unit, dict)
            ),
            8,
        )

    @staticmethod
    def _profile_er_ev_totals_from_units(units: list[dict]) -> tuple[float, float]:
        er_total = 0.0
        ev_total = 0.0
        for unit in units:
            if not isinstance(unit, dict):
                continue
            similarity = max(0.0, min(1.0, float(unit.get("match_similarity", 1.0))))
            er_total += max(0.0, float(unit.get("er", 0.0))) * similarity
            ev_total += max(0.0, float(unit.get("ev", 0.0))) * similarity
        return round(er_total, 8), round(ev_total, 8)

    @staticmethod
    def _collect_profile_units(profile: dict) -> list[dict]:
        return [dict(unit) for group in profile.get("sequence_groups", []) for unit in group.get("units", []) if isinstance(unit, dict)]

    def _profile_energy_map(self, profile: dict) -> dict[str, float]:
        weights = {}
        for unit in self._collect_profile_units(profile):
            if unit.get("is_placeholder"):
                continue
            structure_id = str(unit.get("unit_id", ""))
            if not structure_id:
                continue
            weights[structure_id] = round(
                float(weights.get(structure_id, 0.0)) + max(0.0, float(unit.get("er", 0.0))) + max(0.0, float(unit.get("ev", 0.0))),
                8,
            )
        total = sum(max(0.0, value) for value in weights.values())
        if total <= 0.0:
            if not weights:
                return {}
            return {key: round(1.0 / len(weights), 8) for key in weights}
        return {key: round(max(0.0, value) / total, 8) for key, value in weights.items()}

    def _build_structure_memory_material(self, *, profile: dict) -> dict:
        sequence_groups = []
        structure_items: list[dict] = []
        ordered_structure_ids: list[str] = []
        seen_structure_ids: set[str] = set()

        for group in list(profile.get("sequence_groups", [])):
            cloned_group = {
                "group_index": int(group.get("group_index", 0)),
                "source_type": str(group.get("source_type", "")),
                "origin_frame_id": str(group.get("origin_frame_id", "")),
                "source_group_index": int(group.get("source_group_index", group.get("group_index", 0))),
                "units": [dict(unit) for unit in group.get("units", []) if isinstance(unit, dict)],
                "csa_bundles": [dict(bundle) for bundle in group.get("csa_bundles", []) if isinstance(bundle, dict)],
                "tokens": list(group.get("tokens", [])),
                "display_text": str(group.get("display_text", "")),
            }
            sequence_groups.append(cloned_group)
            for unit in cloned_group["units"]:
                structure_id = str(unit.get("unit_id", ""))
                if not structure_id or unit.get("is_placeholder"):
                    continue
                if structure_id in seen_structure_ids:
                    continue
                seen_structure_ids.add(structure_id)
                ordered_structure_ids.append(structure_id)
                structure_items.append(
                    {
                        "structure_id": structure_id,
                        "display_text": str(unit.get("structure_display_text", unit.get("display_text", unit.get("token", structure_id)))),
                        "grouped_display_text": str(unit.get("structure_grouped_display_text", unit.get("display_text", structure_id))),
                    }
                )

        return {
            "memory_kind": "structure_group",
            "storage_grain": "st",
            "grouped_display_text": format_sequence_groups(sequence_groups) or str(profile.get("display_text", "")),
            "sequence_groups": sequence_groups,
            "structure_refs": ordered_structure_ids,
            "structure_items": structure_items,
            "structure_energy_profile": self._profile_energy_map(profile),
        }

    def _normalize_energy(self, structure_ids: list[str], budget_er_map: dict[str, float], budget_ev_map: dict[str, float]) -> dict[str, float]:
        values = {
            structure_id: max(0.0, float(budget_er_map.get(structure_id, 0.0)) + float(budget_ev_map.get(structure_id, 0.0)))
            for structure_id in structure_ids
        }
        total = sum(values.values())
        if total <= 0.0:
            if not values:
                return {}
            return {structure_id: round(1.0 / len(values), 8) for structure_id in values}
        return {
            structure_id: round(value / total, 8)
            for structure_id, value in values.items()
        }

    def _update_group_after_match(
        self,
        *,
        group_obj: dict,
        current_profile: dict[str, float],
        match_score: float,
        matched_er_total: float,
        matched_ev_total: float,
    ) -> None:
        now_ms = int(time.time() * 1000)
        stats = group_obj.setdefault("stats", {})
        self._weight.decay_group(group_obj, now_ms=now_ms, round_step=1)
        stats["base_weight"] = self._weight.update_base_weight_by_support(
            current_base_weight=stats.get("base_weight", None),
            reality_support=max(0.0, float(matched_er_total)),
            virtual_support=max(0.0, float(matched_ev_total)),
            match_score=max(0.0, float(match_score)),
        )
        self._weight.refresh_recent_state(stats, now_ms=now_ms, strength=max(float(self._config.get("recency_gain_refresh_floor", 0.45)), float(match_score)))
        self._weight.apply_match_fatigue(stats, strength=match_score)
        stats["last_matched_at"] = now_ms
        stats["match_count_total"] = int(stats.get("match_count_total", 0)) + 1
        group_obj["avg_energy_profile"] = self._smooth_profile_merge(
            existing=dict(group_obj.get("avg_energy_profile", {})),
            observed=current_profile,
            alpha=max(0.12, min(0.45, 0.18 + 0.32 * float(match_score))),
        )
        local_db = group_obj.setdefault("local_db", {})
        local_db.setdefault("group_table", [])
        local_db.setdefault("residual_table", [])
        local_db.setdefault("memory_table", [])

    def _mark_path_entries(self, *, best: dict, structure_store, group_store, transferred_er: float, transferred_ev: float, match_score: float) -> None:
        for path_entry in best.get("path_entries", []):
            owner_kind = str(path_entry.get("owner_kind", ""))
            owner_id = str(path_entry.get("owner_id", ""))
            entry_id = str(path_entry.get("entry_id", ""))
            if not owner_kind or not owner_id or not entry_id:
                continue
            owner_ctx = self._open_owner_context(
                owner_kind=owner_kind,
                owner_id=owner_id,
                structure_store=structure_store,
                group_store=group_store,
                pointer_index=None,
                cut_engine=None,
                trace_id="",
                tick_id="",
            )
            if not owner_ctx:
                continue
            updated = False
            for entry in owner_ctx.get("group_table", []):
                if str(entry.get("entry_id", "")) != entry_id:
                    continue
                self._mark_entry_weight(
                    entry,
                    delta_er=transferred_er,
                    delta_ev=transferred_ev,
                    match_score=match_score,
                )
                updated = True
                break
            if updated:
                self._persist_owner_context(owner_ctx, structure_store=structure_store, group_store=group_store)

    def _mark_entry_weight(self, entry: dict, *, delta_er: float, delta_ev: float, match_score: float) -> None:
        now_ms = int(time.time() * 1000)
        self._ensure_group_entry_schema(entry)
        self._weight.mark_entry_activation(
            entry,
            delta_er=max(0.0, float(delta_er)),
            delta_ev=max(0.0, float(delta_ev)),
            match_score=max(0.0, float(match_score)),
            now_ms=now_ms,
        )
        entry["base_weight"] = self._weight.update_base_weight_by_support(
            current_base_weight=entry.get("base_weight", None),
            reality_support=max(0.0, float(delta_er)),
            virtual_support=max(0.0, float(delta_ev)),
            match_score=max(0.0, float(match_score)),
        )
        entry["last_updated_at"] = now_ms

    @staticmethod
    def _mark_owner_context_dirty(owner_ctx: dict) -> None:
        if isinstance(owner_ctx, dict):
            owner_ctx["_dirty"] = True

    def _smooth_profile_merge(self, *, existing: dict[str, float], observed: dict[str, float], alpha: float) -> dict[str, float]:
        keys = set(existing.keys()) | set(observed.keys())
        if not keys:
            return {}
        merged = {}
        for key in keys:
            before = float(existing.get(key, 0.0))
            after = float(observed.get(key, 0.0))
            merged[key] = round((1.0 - float(alpha)) * before + float(alpha) * after, 8)
        total = sum(max(0.0, value) for value in merged.values())
        if total <= 0.0:
            return {key: round(1.0 / len(merged), 8) for key in merged}
        return {key: round(max(0.0, value) / total, 8) for key, value in merged.items()}

    def _store_runtime_context(
        self,
        *,
        owner_kind: str,
        owner_id: str,
        full_profile: dict,
        covered_structure_ids: list[str],
        full_energy_profile: dict[str, float],
        structure_store,
        group_store,
        pointer_index,
        cut_engine,
        trace_id: str,
        tick_id: str,
        round_index: int,
        episodic_memory_id: str,
    ) -> dict | None:
        owner_ctx = self._open_owner_context(
            owner_kind=owner_kind,
            owner_id=owner_id,
            structure_store=structure_store,
            group_store=group_store,
            pointer_index=pointer_index,
            cut_engine=cut_engine,
            trace_id=trace_id,
            tick_id=tick_id,
        )
        if not owner_ctx:
            return None
        summary = {
            "owner_kind": owner_kind,
            "owner_id": owner_id,
            "owner_display_text": owner_ctx.get("owner_display_text", owner_id),
            "resolved_db_id": owner_ctx.get("resolved_db_id", ""),
            "used_fallback": bool(owner_ctx.get("used_fallback", False)),
            "new_group_ids": [],
            "new_group_details": [],
            "actions": [],
        }
        if episodic_memory_id:
            self._append_memory_ref(
                owner_ctx=owner_ctx,
                memory_id=episodic_memory_id,
                content_signature=full_profile.get("content_signature", ""),
                round_index=round_index,
                event_kind="structure_runtime",
            )
        owner_placeholder = owner_ctx.get("owner_placeholder", "")
        residual_profile = self._build_relative_residual_profile(
            full_profile=full_profile,
            covered_structure_ids=covered_structure_ids,
            owner_placeholder=owner_placeholder,
            cut_engine=cut_engine,
            origin_frame_id=f"{tick_id}:{round_index}:{owner_id}",
        )
        if not residual_profile or not self._profile_has_non_placeholder_content(residual_profile, placeholder_token=owner_placeholder):
            self._persist_owner_context(owner_ctx, structure_store=structure_store, group_store=group_store)
            return summary
        self._normalize_owner_local_residual(
            owner_ctx=owner_ctx,
            residual_profile=residual_profile,
            full_energy_profile=full_energy_profile,
            structure_store=structure_store,
            group_store=group_store,
            pointer_index=pointer_index,
            cut_engine=cut_engine,
            trace_id=trace_id,
            tick_id=tick_id,
            round_index=round_index,
            episodic_memory_id=episodic_memory_id,
            summary=summary,
            depth=0,
        )
        self._persist_owner_context(owner_ctx, structure_store=structure_store, group_store=group_store)
        summary["new_group_ids"] = list(dict.fromkeys(summary.get("new_group_ids", [])))
        return summary

    def _normalize_owner_local_residual(
        self,
        *,
        owner_ctx: dict,
        residual_profile: dict,
        full_energy_profile: dict[str, float],
        structure_store,
        group_store,
        pointer_index,
        cut_engine,
        trace_id: str,
        tick_id: str,
        round_index: int,
        episodic_memory_id: str,
        summary: dict,
        depth: int,
    ) -> None:
        if depth >= 12:
            return
        owner_placeholder = owner_ctx.get("owner_placeholder", "")
        if not self._profile_has_non_placeholder_content(residual_profile, placeholder_token=owner_placeholder):
            return
        residual_signature = residual_profile.get("content_signature", "")
        if not residual_signature:
            return
        canonical_profile = self._canonicalize_local_profile(
            profile=residual_profile,
            structure_store=structure_store,
            group_store=group_store,
            cut_engine=cut_engine,
        )
        canonical_signature = canonical_profile.get("content_signature", "") or residual_signature

        local_items = self._list_local_storage_items(
            owner_ctx=owner_ctx,
            structure_store=structure_store,
            group_store=group_store,
            cut_engine=cut_engine,
        )
        exact_raw_item = next(
            (
                item
                for item in local_items
                if item.get("item_kind") == "raw_residual"
                and (
                    item.get("signature", "") == canonical_signature
                    or self._profiles_fuzzy_equivalent(
                        left_profile=item.get("canonical_profile", item.get("profile", {})),
                        right_profile=canonical_profile,
                        cut_engine=cut_engine,
                    )
                )
            ),
            None,
        )
        if exact_raw_item:
            self._reinforce_raw_residual_entry(
                entry=exact_raw_item["entry_ref"],
                residual_profile=canonical_profile,
                full_energy_profile=full_energy_profile,
                episodic_memory_id=episodic_memory_id,
                round_index=round_index,
                structure_store=structure_store,
                group_store=group_store,
                cut_engine=cut_engine,
            )
            self._mark_owner_context_dirty(owner_ctx)
            summary["actions"].append(
                self._build_raw_residual_action(
                    action_type="reinforce_raw_residual",
                    owner_ctx=owner_ctx,
                    entry=exact_raw_item["entry_ref"],
                )
            )
            return

        exact_item = next(
            (
                item
                for item in local_items
                if item.get("item_kind") != "raw_residual"
                and (
                    item.get("signature", "") in {residual_signature, canonical_signature}
                    or self._profiles_fuzzy_equivalent(
                        left_profile=item.get("profile", {}),
                        right_profile=residual_profile,
                        cut_engine=cut_engine,
                    )
                )
            ),
            None,
        )
        if exact_item:
            self._mark_entry_weight(
                exact_item["entry_ref"],
                delta_er=self._profile_total_energy(residual_profile),
                delta_ev=0.0,
                match_score=1.0,
            )
            self._mark_owner_context_dirty(owner_ctx)
            child_ctx = self._open_owner_context(
                owner_kind="sg",
                owner_id=exact_item.get("group_id", ""),
                structure_store=structure_store,
                group_store=group_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
                trace_id=trace_id,
                tick_id=tick_id,
            )
            if child_ctx and episodic_memory_id:
                self._append_memory_ref(
                    owner_ctx=child_ctx,
                    memory_id=episodic_memory_id,
                    content_signature=residual_signature,
                    round_index=round_index,
                    event_kind="structure_exact_child",
                )
                self._persist_owner_context(child_ctx, structure_store=structure_store, group_store=group_store)
            summary["actions"].append({"type": "reinforce_child_group", "group_id": exact_item.get("group_id", "")})
            return

        parent_group = self._find_parent_group_candidate(
            owner_ctx=owner_ctx,
            residual_profile=residual_profile,
            local_items=local_items,
            cut_engine=cut_engine,
        )
        if parent_group:
            self._mark_entry_weight(
                parent_group["entry_ref"],
                delta_er=self._profile_total_energy(residual_profile),
                delta_ev=0.0,
                match_score=max(
                    float(self._config.get("structure_descend_match_floor", 0.35)),
                    float(parent_group.get("entry_runtime_weight", 1.0))
                    / max(1.0, float(parent_group.get("path_strength", 1.0))),
                ),
            )
            self._mark_owner_context_dirty(owner_ctx)
            child_ctx = self._open_owner_context(
                owner_kind="sg",
                owner_id=parent_group.get("group_id", ""),
                structure_store=structure_store,
                group_store=group_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
                trace_id=trace_id,
                tick_id=tick_id,
            )
            if child_ctx and episodic_memory_id:
                self._append_memory_ref(
                    owner_ctx=child_ctx,
                    memory_id=episodic_memory_id,
                    content_signature=residual_signature,
                    round_index=round_index,
                    event_kind="structure_parent_child",
                )
            child_profile = self._build_descend_relative_profile(
                full_profile=residual_profile,
                common_part=parent_group.get("common_part", {}),
                child_placeholder=child_ctx.get("owner_placeholder", "") if child_ctx else "",
                cut_engine=cut_engine,
                origin_frame_id=f"{tick_id}:{round_index}:descend:{parent_group.get('group_id', '')}",
            )
            if child_ctx and child_profile:
                self._normalize_owner_local_residual(
                    owner_ctx=child_ctx,
                    residual_profile=child_profile,
                    full_energy_profile=full_energy_profile,
                    structure_store=structure_store,
                    group_store=group_store,
                    pointer_index=pointer_index,
                    cut_engine=cut_engine,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    round_index=round_index,
                    episodic_memory_id=episodic_memory_id,
                    summary=summary,
                    depth=depth + 1,
                )
                self._persist_owner_context(child_ctx, structure_store=structure_store, group_store=group_store)
            summary["actions"].append({"type": "descend_existing_group", "group_id": parent_group.get("group_id", "")})
            return

        overlap_item = self._find_best_overlap_candidate(
            owner_ctx=owner_ctx,
            residual_profile=residual_profile,
            local_items=local_items,
            cut_engine=cut_engine,
        )
        if overlap_item:
            common_part = overlap_item.get("common_part", {})
            common_relative_profile = overlap_item.get("common_relative_profile", {}) or self._profile_from_stored_groups(
                list(common_part.get("common_groups", [])),
                cut_engine=cut_engine,
                ext={
                    "kind": "structure_group_relative_common",
                    "owner_id": owner_ctx.get("owner_id", ""),
                    "owner_kind": owner_ctx.get("owner_kind", ""),
                },
            )
            common_full_profile = overlap_item.get("common_full_profile", {}) or self._expand_relative_profile(
                relative_profile=common_relative_profile,
                owner_profile=owner_ctx.get("owner_profile", {}),
                owner_placeholder=owner_placeholder,
                cut_engine=cut_engine,
            )
            if not self._common_overlap_beyond_owner(
                common_relative_profile=common_relative_profile,
                owner_placeholder=owner_placeholder,
            ) or not self._profile_fully_contains_subprofile(
                container_profile=common_full_profile,
                required_profile=owner_ctx.get("owner_profile", {}),
                cut_engine=cut_engine,
            ):
                overlap_item = None
        if overlap_item:
            common_part = overlap_item.get("common_part", {})
            common_relative_profile = overlap_item.get("common_relative_profile", {}) or common_relative_profile
            common_full_profile = overlap_item.get("common_full_profile", {}) or common_full_profile
            observed_maps = [dict(full_energy_profile)]
            if overlap_item.get("item_kind") == "raw_residual":
                observed_maps.append(dict(overlap_item.get("observed_energy_profile", {})))
            else:
                observed_maps.append(dict(overlap_item.get("group_obj", {}).get("avg_energy_profile", {})))
            avg_energy_profile = self._merge_observed_energy_profiles(
                profile_maps=observed_maps,
                required_ids=self._extract_structure_ids_from_profile(common_full_profile),
            )
            common_group_result = self._find_or_create_common_group(
                owner_ctx=owner_ctx,
                relative_profile=common_relative_profile,
                full_profile=common_full_profile,
                avg_energy_profile=avg_energy_profile,
                structure_store=structure_store,
                group_store=group_store,
                cut_engine=cut_engine,
                trace_id=trace_id,
                tick_id=tick_id,
            )
            common_group = common_group_result["group_obj"]
            common_group_id = common_group.get("id", "")
            if common_group_result.get("created") and common_group_id:
                summary["new_group_ids"].append(common_group_id)
                summary["new_group_details"].append(self._build_group_debug_payload(common_group, structure_store, cut_engine))
            self._remove_local_item(owner_ctx=owner_ctx, item=overlap_item)
            self._mark_owner_context_dirty(owner_ctx)
            self._append_group_entry(
                owner_ctx=owner_ctx,
                group_obj=common_group,
                relative_profile=common_relative_profile,
                base_weight=self._weight.update_base_weight_by_support(
                    current_base_weight=overlap_item.get("base_weight", 0.0),
                    reality_support=self._profile_total_energy(residual_profile),
                    virtual_support=0.0,
                    match_score=1.0,
                ),
            )

            common_ctx = self._open_owner_context(
                owner_kind="sg",
                owner_id=common_group_id,
                structure_store=structure_store,
                group_store=group_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
                trace_id=trace_id,
                tick_id=tick_id,
            )
            if common_ctx and episodic_memory_id:
                self._append_memory_ref(
                    owner_ctx=common_ctx,
                    memory_id=episodic_memory_id,
                    content_signature=common_full_profile.get("content_signature", ""),
                    round_index=round_index,
                    event_kind="structure_common_group",
                )

            if overlap_item.get("item_kind") == "group_entry" and common_ctx:
                existing_child_profile = self._build_descend_relative_profile(
                    full_profile=overlap_item.get("relative_profile", {}),
                    common_part=common_part,
                    child_placeholder=common_ctx.get("owner_placeholder", ""),
                    cut_engine=cut_engine,
                    origin_frame_id=f"{tick_id}:{round_index}:existing:{common_group_id}",
                )
                if existing_child_profile and self._profile_has_non_placeholder_content(existing_child_profile, placeholder_token=common_ctx.get("owner_placeholder", "")):
                    self._append_group_entry(
                        owner_ctx=common_ctx,
                        group_obj=overlap_item.get("group_obj", {}),
                        relative_profile=existing_child_profile,
                        base_weight=max(0.0, float(overlap_item.get("base_weight", 0.0))),
                    )
                    self._mark_owner_context_dirty(common_ctx)

            if overlap_item.get("item_kind") == "raw_residual" and common_ctx:
                existing_child_profile = self._build_descend_relative_profile(
                    full_profile=overlap_item.get("profile", {}),
                    common_part=common_part,
                    child_placeholder=common_ctx.get("owner_placeholder", ""),
                    cut_engine=cut_engine,
                    origin_frame_id=f"{tick_id}:{round_index}:existing_raw:{common_group_id}",
                )
                if existing_child_profile and self._profile_has_non_placeholder_content(existing_child_profile, placeholder_token=common_ctx.get("owner_placeholder", "")):
                    self._normalize_owner_local_residual(
                        owner_ctx=common_ctx,
                        residual_profile=existing_child_profile,
                        full_energy_profile=overlap_item.get("observed_energy_profile", {}),
                        structure_store=structure_store,
                        group_store=group_store,
                        pointer_index=pointer_index,
                        cut_engine=cut_engine,
                        trace_id=trace_id,
                        tick_id=tick_id,
                        round_index=round_index,
                        episodic_memory_id=episodic_memory_id,
                        summary=summary,
                        depth=depth + 1,
                    )

            incoming_child_profile = self._build_descend_relative_profile(
                full_profile=residual_profile,
                common_part=common_part,
                child_placeholder=common_ctx.get("owner_placeholder", "") if common_ctx else "",
                cut_engine=cut_engine,
                origin_frame_id=f"{tick_id}:{round_index}:incoming:{common_group_id}",
            )
            if common_ctx and incoming_child_profile:
                self._normalize_owner_local_residual(
                    owner_ctx=common_ctx,
                    residual_profile=incoming_child_profile,
                    full_energy_profile=full_energy_profile,
                    structure_store=structure_store,
                    group_store=group_store,
                    pointer_index=pointer_index,
                    cut_engine=cut_engine,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    round_index=round_index,
                    episodic_memory_id=episodic_memory_id,
                    summary=summary,
                    depth=depth + 1,
                )
                self._persist_owner_context(common_ctx, structure_store=structure_store, group_store=group_store)
            summary["actions"].append({"type": "create_common_group", "group_id": common_group_id})
            return

        created_entry = self._append_raw_residual_entry(
            owner_ctx=owner_ctx,
            residual_profile=residual_profile,
            full_energy_profile=full_energy_profile,
            episodic_memory_id=episodic_memory_id,
            round_index=round_index,
            structure_store=structure_store,
            group_store=group_store,
            cut_engine=cut_engine,
        )
        self._mark_owner_context_dirty(owner_ctx)
        summary["actions"].append(
            self._build_raw_residual_action(
                action_type="append_raw_residual",
                owner_ctx=owner_ctx,
                entry=created_entry,
            )
        )

    def _find_parent_group_candidate(self, *, owner_ctx: dict, residual_profile: dict, local_items: list[dict], cut_engine) -> dict | None:
        best = None
        for item in local_items:
            if item.get("item_kind") != "group_entry":
                continue
            existing_profile = item.get("relative_profile", {})
            common_part = cut_engine.maximum_common_part(
                existing_profile.get("sequence_groups", []),
                residual_profile.get("sequence_groups", []),
            )
            existing_length = self._profile_unit_count(existing_profile)
            if common_part.get("residual_existing_signature", ""):
                continue
            bundle_gate_existing_included = bool(common_part.get("bundle_constraints_ok_existing_included", True))
            if int(common_part.get("matched_existing_unit_count", 0)) < max(1, existing_length):
                continue
            if self._profiles_fuzzy_equivalent(
                left_profile=existing_profile,
                right_profile=residual_profile,
                cut_engine=cut_engine,
            ):
                continue
            candidate_key = (
                1 if bundle_gate_existing_included else 0,
                len(item.get("group_obj", {}).get("required_structure_ids", [])),
                float(item.get("entry_runtime_weight", 0.0)),
            )
            current_key = (
                1 if best.get("bundle_gate_existing_included", False) else 0,
                len(best.get("group_obj", {}).get("required_structure_ids", [])),
                float(best.get("entry_runtime_weight", 0.0)),
            ) if best else None
            if best is None or candidate_key > current_key:
                best = {
                    **item,
                    "common_part": common_part,
                    "bundle_gate_existing_included": bundle_gate_existing_included,
                }
        return best

    def _find_best_overlap_candidate(self, *, owner_ctx: dict, residual_profile: dict, local_items: list[dict], cut_engine) -> dict | None:
        best = None
        for item in local_items:
            existing_profile = item.get("profile", {})
            common_part = cut_engine.maximum_common_part(
                existing_profile.get("sequence_groups", []),
                residual_profile.get("sequence_groups", []),
            )
            common_signature = common_part.get("common_signature", "")
            if not common_signature:
                continue
            validated_common = self._validate_owner_overlap_common_part(
                owner_ctx=owner_ctx,
                common_part=common_part,
                cut_engine=cut_engine,
            )
            if not validated_common:
                continue
            if self._profiles_fuzzy_equivalent(
                left_profile=existing_profile,
                right_profile=residual_profile,
                cut_engine=cut_engine,
            ):
                continue
            candidate_key = (
                int(common_part.get("common_length", 0)),
                int(common_part.get("common_group_count", 0)),
                float(item.get("entry_runtime_weight", 0.0)),
            )
            current_key = (
                int(best.get("common_part", {}).get("common_length", 0)),
                int(best.get("common_part", {}).get("common_group_count", 0)),
                float(best.get("entry_runtime_weight", 0.0)),
            ) if best else None
            if best is None or candidate_key > current_key:
                best = {
                    **item,
                    "common_part": common_part,
                    "common_relative_profile": validated_common.get("relative_profile", {}),
                    "common_full_profile": validated_common.get("full_profile", {}),
                }
        return best

    # 结构级残差只能在“共同部分仍然保留当前 owner，且 owner 外还有额外内容”时创建子共有结构组。
    # 否则就会把不包含当前组选中结构的内容错误地下沉到当前 owner 的本地库里。
    def _validate_owner_overlap_common_part(self, *, owner_ctx: dict, common_part: dict, cut_engine) -> dict | None:
        owner_placeholder = str(owner_ctx.get("owner_placeholder", ""))
        common_relative_profile = self._profile_from_stored_groups(
            list(common_part.get("common_groups", [])),
            cut_engine=cut_engine,
            ext={
                "kind": "structure_group_relative_common_candidate",
                "owner_id": owner_ctx.get("owner_id", ""),
                "owner_kind": owner_ctx.get("owner_kind", ""),
            },
        )
        if not self._common_overlap_beyond_owner(
            common_relative_profile=common_relative_profile,
            owner_placeholder=owner_placeholder,
        ):
            return None
        common_full_profile = self._expand_relative_profile(
            relative_profile=common_relative_profile,
            owner_profile=owner_ctx.get("owner_profile", {}),
            owner_placeholder=owner_placeholder,
            cut_engine=cut_engine,
        )
        if not self._profile_fully_contains_subprofile(
            container_profile=common_full_profile,
            required_profile=owner_ctx.get("owner_profile", {}),
            cut_engine=cut_engine,
        ):
            return None
        return {
            "relative_profile": common_relative_profile,
            "full_profile": common_full_profile,
        }

    def _common_overlap_beyond_owner(self, *, common_relative_profile: dict, owner_placeholder: str) -> bool:
        if not owner_placeholder:
            return False
        tokens = [
            str(unit.get("token", ""))
            for unit in self._collect_profile_units(common_relative_profile)
            if str(unit.get("token", ""))
        ]
        if owner_placeholder not in tokens:
            return False
        return self._profile_has_non_placeholder_content(common_relative_profile, placeholder_token=owner_placeholder)

    def _profile_fully_contains_subprofile(self, *, container_profile: dict, required_profile: dict, cut_engine) -> bool:
        if not container_profile or not required_profile:
            return False
        common_part = cut_engine.maximum_common_part(
            required_profile.get("sequence_groups", []),
            container_profile.get("sequence_groups", []),
        )
        return bool(
            int(common_part.get("common_length", 0)) > 0
            and not common_part.get("residual_existing_signature", "")
            and int(common_part.get("matched_existing_unit_count", 0)) >= self._profile_unit_count(required_profile)
        )

    def _list_local_storage_items(self, *, owner_ctx: dict, structure_store, group_store, cut_engine) -> list[dict]:
        items = []
        for entry in owner_ctx.get("residual_table", []):
            profiles = self._ensure_raw_residual_canonical_fields(
                entry=entry,
                structure_store=structure_store,
                group_store=group_store,
                cut_engine=cut_engine,
            )
            items.append(
                {
                    "item_kind": "raw_residual",
                    "entry_ref": entry,
                    "entry_id": entry.get("entry_id", ""),
                    "signature": entry.get("canonical_content_signature", ""),
                    "profile": profiles.get("raw_profile", {}),
                    "canonical_profile": profiles.get("canonical_profile", {}),
                    "raw_profile": profiles.get("raw_profile", {}),
                    "base_weight": float(entry.get("base_weight", 0.0)),
                    "entry_runtime_weight": self._weight.entry_runtime_weight(entry),
                    "observed_energy_profile": dict(entry.get("observed_energy_profile", {})),
                }
            )
        for entry in owner_ctx.get("group_table", []):
            self._ensure_group_entry_schema(entry)
            group_obj = group_store.get(entry.get("group_id", ""))
            if not group_obj:
                continue
            relative_profile = self._group_entry_relative_profile(owner_ctx=owner_ctx, entry=entry, group_obj=group_obj, cut_engine=cut_engine)
            if not relative_profile:
                continue
            items.append(
                {
                    "item_kind": "group_entry",
                    "entry_ref": entry,
                    "entry_id": entry.get("entry_id", ""),
                    "group_id": group_obj.get("id", ""),
                    "group_obj": group_obj,
                    "signature": relative_profile.get("content_signature", ""),
                    "profile": relative_profile,
                    "relative_profile": relative_profile,
                    "base_weight": float(entry.get("base_weight", 0.0)),
                    "entry_runtime_weight": self._weight.entry_runtime_weight(entry),
                    "path_strength": self._path_strength(
                        group_runtime_weight=self._preview_group_stats(group_obj, now_ms=int(time.time() * 1000))["runtime_weight"],
                        entry_runtime_weight=self._weight.entry_runtime_weight(entry),
                    ),
                }
            )
        items.sort(
            key=lambda item: (
                -float(item.get("entry_runtime_weight", 0.0)),
                -float(item.get("base_weight", 0.0)),
                item.get("entry_id", ""),
            )
        )
        return items

    def _reinforce_raw_residual_entry(
        self,
        *,
        entry: dict,
        residual_profile: dict,
        full_energy_profile: dict[str, float],
        episodic_memory_id: str,
        round_index: int,
        structure_store,
        group_store,
        cut_engine,
    ) -> None:
        now_ms = int(time.time() * 1000)
        self._ensure_raw_residual_schema(entry)
        existing_profiles = self._ensure_raw_residual_canonical_fields(
            entry=entry,
            structure_store=structure_store,
            group_store=group_store,
            cut_engine=cut_engine,
        )
        canonical_profile = self._canonicalize_local_profile(
            profile=residual_profile,
            structure_store=structure_store,
            group_store=group_store,
            cut_engine=cut_engine,
        )
        existing_canonical_profile = existing_profiles.get("canonical_profile", {})
        if existing_canonical_profile and self._profiles_fuzzy_equivalent(
            left_profile=existing_canonical_profile,
            right_profile=canonical_profile,
            cut_engine=cut_engine,
        ):
            common_part = cut_engine.maximum_common_part(
                existing_canonical_profile.get("sequence_groups", []),
                canonical_profile.get("sequence_groups", []),
            )
            canonical_profile = self._profile_from_stored_groups(
                list(common_part.get("common_groups", [])),
                cut_engine=cut_engine,
                ext={"kind": "structure_raw_residual_canonical_merged"},
            )
        self._mark_entry_weight(
            entry,
            delta_er=self._profile_total_energy(canonical_profile),
            delta_ev=0.0,
            match_score=1.0,
        )
        entry["canonical_content_signature"] = canonical_profile.get("content_signature", "")
        entry["canonical_display_text"] = canonical_profile.get("display_text", "")
        entry["canonical_flat_tokens"] = list(canonical_profile.get("flat_tokens", []))
        entry["canonical_sequence_groups"] = list(canonical_profile.get("sequence_groups", []))
        entry["observed_energy_profile"] = self._smooth_profile_merge(
            existing=dict(entry.get("observed_energy_profile", {})),
            observed=dict(full_energy_profile),
            alpha=float(self._config.get("structure_profile_merge_alpha", 0.22)),
        )
        entry["sample_count"] = int(entry.get("sample_count", 1)) + 1
        entry["last_updated_at"] = now_ms
        if episodic_memory_id:
            memory_refs = list(entry.get("memory_refs", []))
            if episodic_memory_id not in memory_refs:
                memory_refs.append(episodic_memory_id)
            entry["memory_refs"] = memory_refs
        entry.setdefault("ext", {})["last_round_index"] = round_index

    def _append_raw_residual_entry(
        self,
        *,
        owner_ctx: dict,
        residual_profile: dict,
        full_energy_profile: dict[str, float],
        episodic_memory_id: str,
        round_index: int,
        structure_store,
        group_store,
        cut_engine,
    ) -> dict:
        canonical_profile = self._canonicalize_local_profile(
            profile=residual_profile,
            structure_store=structure_store,
            group_store=group_store,
            cut_engine=cut_engine,
        )
        owner_id = str(owner_ctx.get("owner_id", "") or "")
        owner_kind = str(owner_ctx.get("owner_kind", "") or "")
        entry_id = next_id("sgr")
        entry_ext = merge_context_metadata(
            {
                "relation_type": "structure_raw_residual",
                "owner_kind": owner_kind,
                "owner_id": owner_id,
                "round_index": round_index,
                "source_em_id": episodic_memory_id,
                "source_memory_created_at": int(time.time() * 1000),
            },
            context_ref_object_id=owner_id,
            context_ref_object_type=owner_kind,
            context_owner_structure_id=owner_id if owner_kind == "st" else "",
            parent_ids=[owner_id] if owner_id else [],
        )
        entry_ext = merge_residual_metadata(
            entry_ext,
            residual_origin_kind="structure_raw_residual",
            residual_origin_entry_id=entry_id,
        )
        entry = {
            "entry_id": entry_id,
            "entry_type": "raw_residual",
            "content_signature": residual_profile.get("content_signature", ""),
            "display_text": residual_profile.get("display_text", ""),
            "flat_tokens": list(residual_profile.get("flat_tokens", [])),
            "sequence_groups": list(residual_profile.get("sequence_groups", [])),
            "canonical_content_signature": canonical_profile.get("content_signature", ""),
            "canonical_display_text": canonical_profile.get("display_text", ""),
            "canonical_flat_tokens": list(canonical_profile.get("flat_tokens", [])),
            "canonical_sequence_groups": list(canonical_profile.get("sequence_groups", [])),
            "base_weight": self._weight.update_base_weight_by_support(
                current_base_weight=None,
                reality_support=self._profile_total_energy(canonical_profile),
                virtual_support=0.0,
                match_score=1.0,
            ),
            "recent_gain": self._weight._target_recent_gain(strength=1.0),
            "fatigue": 0.0,
            "runtime_er": round(self._profile_total_energy(canonical_profile), 8),
            "runtime_ev": 0.0,
            "match_count_total": 0,
            "last_updated_at": int(time.time() * 1000),
            "last_matched_at": 0,
            "last_recency_refresh_at": int(time.time() * 1000),
            "recency_hold_rounds_remaining": int(self._config.get("recency_gain_hold_rounds", 2)),
            "observed_energy_profile": dict(full_energy_profile),
            "sample_count": 1,
            "memory_refs": [episodic_memory_id] if episodic_memory_id else [],
            "ext": entry_ext,
        }
        owner_ctx.setdefault("residual_table", []).append(entry)
        self._mark_owner_context_dirty(owner_ctx)
        return entry

    def _append_group_entry(self, *, owner_ctx: dict, group_obj: dict, relative_profile: dict, base_weight: float) -> dict:
        signature = relative_profile.get("content_signature", "")
        for existing in owner_ctx.get("group_table", []):
            self._ensure_group_entry_schema(existing)
            if existing.get("group_id", "") != group_obj.get("id", ""):
                continue
            if existing.get("relative_content_signature", "") != signature:
                continue
            existing["base_weight"] = round(
                max(0.0, float(existing.get("base_weight", 0.0)))
                + max(0.0, float(base_weight)) * float(self._config.get("structure_group_entry_reinforce_ratio", 0.15)),
                8,
            )
            self._weight.refresh_recent_state(existing, now_ms=int(time.time() * 1000), strength=1.0)
            existing["last_updated_at"] = int(time.time() * 1000)
            self._mark_owner_context_dirty(owner_ctx)
            return existing
        entry = {
            "entry_id": next_id("sge"),
            "group_id": group_obj.get("id", ""),
            "required_structure_ids": list(group_obj.get("required_structure_ids", [])),
            "avg_energy_profile": dict(group_obj.get("avg_energy_profile", {})),
            "content_signature": group_obj.get("group_structure", {}).get("content_signature", ""),
            "temporal_signature": group_obj.get("group_structure", {}).get("temporal_signature", ""),
            "display_text": self._group_display_text(group_obj),
            "relative_content_signature": signature,
            "relative_flat_tokens": list(relative_profile.get("flat_tokens", [])),
            "relative_sequence_groups": list(relative_profile.get("sequence_groups", [])),
            "base_weight": round(max(0.0, float(base_weight)), 8),
            "recent_gain": self._weight._target_recent_gain(strength=1.0),
            "fatigue": 0.0,
            "runtime_er": 0.0,
            "runtime_ev": 0.0,
            "match_count_total": 0,
            "last_updated_at": int(time.time() * 1000),
            "last_matched_at": 0,
            "last_recency_refresh_at": int(time.time() * 1000),
            "recency_hold_rounds_remaining": int(self._config.get("recency_gain_hold_rounds", 2)),
            "ext": {
                "relation_type": "structure_group_ref",
                "owner_kind": owner_ctx.get("owner_kind", ""),
                "owner_id": owner_ctx.get("owner_id", ""),
            },
        }
        owner_ctx.setdefault("group_table", []).append(entry)
        self._mark_owner_context_dirty(owner_ctx)
        return entry

    def _find_or_create_common_group(
        self,
        *,
        owner_ctx: dict,
        relative_profile: dict,
        full_profile: dict,
        avg_energy_profile: dict[str, float],
        structure_store,
        group_store,
        cut_engine,
        trace_id: str,
        tick_id: str,
    ) -> dict:
        relative_signature = str(relative_profile.get("content_signature", ""))
        full_signature = str(full_profile.get("content_signature", ""))
        required_ids = self._extract_structure_ids_from_profile(full_profile)
        for entry in owner_ctx.get("group_table", []):
            self._ensure_group_entry_schema(entry)
            group_obj = group_store.get(str(entry.get("group_id", "")))
            if not group_obj:
                continue
            existing_relative_profile = self._group_entry_relative_profile(
                owner_ctx=owner_ctx,
                entry=entry,
                group_obj=group_obj,
                cut_engine=cut_engine,
            )
            existing_full_profile = self._group_full_profile(
                group_obj=group_obj,
                structure_store=structure_store,
                cut_engine=cut_engine,
            )
            if not existing_relative_profile or not existing_full_profile:
                continue
            if str(entry.get("relative_content_signature", "")) != relative_signature and not self._profiles_fuzzy_equivalent(
                left_profile=existing_relative_profile,
                right_profile=relative_profile,
                cut_engine=cut_engine,
            ):
                continue
            group_signature = str(group_obj.get("group_structure", {}).get("content_signature", ""))
            if group_signature and group_signature != full_signature and not self._profiles_fuzzy_equivalent(
                left_profile=existing_full_profile,
                right_profile=full_profile,
                cut_engine=cut_engine,
            ):
                continue
            group_obj.setdefault("local_db", {})
            group_obj["local_db"].setdefault("group_table", [])
            group_obj["local_db"].setdefault("residual_table", [])
            group_obj["local_db"].setdefault("memory_table", [])
            if required_ids:
                group_obj["required_structure_ids"] = list(required_ids)
            group_obj["avg_energy_profile"] = self._smooth_profile_merge(
                existing=dict(group_obj.get("avg_energy_profile", {})),
                observed=self._normalize_external_profile(avg_energy_profile, required_ids),
                alpha=float(self._config.get("structure_profile_merge_alpha", 0.22)),
            )
            group_obj["group_structure"] = {
                **full_profile,
                "temporal_signature": full_profile.get("content_signature", ""),
            }
            group_store.update(group_obj)
            return {"created": False, "group_obj": group_obj}

        indexed_candidates = []
        candidate_seen: set[str] = set()
        candidate_limit = max(1, int(self._config.get("fallback_scan_hard_limit", 200) or 200))
        if hasattr(group_store, "query_by_signature"):
            indexed_candidates.extend(group_store.query_by_signature(full_signature, limit=candidate_limit))
        if hasattr(group_store, "query_by_required_structures"):
            indexed_candidates.extend(group_store.query_by_required_structures(required_ids, limit=candidate_limit))
        if hasattr(group_store, "get_recent"):
            recent_limit = max(0, min(candidate_limit, int(self._config.get("common_group_recent_fallback_limit", 32) or 32)))
            indexed_candidates.extend(group_store.get_recent(recent_limit))
        elif (
            not indexed_candidates
            and bool(self._config.get("allow_global_scan_on_runtime_path", False))
            and hasattr(group_store, "iter_items")
        ):
            indexed_candidates.extend(group_store.iter_items()[:candidate_limit])

        for existing_group in indexed_candidates:
            group_id = str(existing_group.get("id", "") or "")
            if group_id and group_id in candidate_seen:
                continue
            if group_id:
                candidate_seen.add(group_id)
            existing_signature = str(existing_group.get("group_structure", {}).get("content_signature", ""))
            existing_full_profile = self._group_full_profile(
                group_obj=existing_group,
                structure_store=structure_store,
                cut_engine=cut_engine,
            )
            if existing_signature and existing_signature != full_signature and not self._profiles_fuzzy_equivalent(
                left_profile=existing_full_profile,
                right_profile=full_profile,
                cut_engine=cut_engine,
            ):
                continue
            existing_group.setdefault("local_db", {})
            existing_group["local_db"].setdefault("group_table", [])
            existing_group["local_db"].setdefault("residual_table", [])
            existing_group["local_db"].setdefault("memory_table", [])
            if required_ids:
                existing_group["required_structure_ids"] = list(required_ids)
            existing_group["group_structure"] = {
                **full_profile,
                "temporal_signature": full_profile.get("content_signature", ""),
            }
            existing_group["avg_energy_profile"] = self._smooth_profile_merge(
                existing=dict(existing_group.get("avg_energy_profile", {})),
                observed=self._normalize_external_profile(avg_energy_profile, required_ids),
                alpha=float(self._config.get("structure_profile_merge_alpha", 0.22)),
            )
            group_store.update(existing_group)
            return {"created": False, "group_obj": existing_group}

        group_obj = group_store.create_group(
            required_structure_ids=required_ids,
            avg_energy_profile=self._normalize_external_profile(avg_energy_profile, required_ids),
            trace_id=trace_id,
            tick_id=tick_id,
            bias_structure_ids=[],
            origin="structure_local_common_group",
            origin_id=owner_ctx.get("owner_id", ""),
            metadata={
                "confidence": float(self._config.get("structure_common_group_confidence", 0.82)),
                "field_registry_version": 1,
                "debug": {},
                "ext": {
                    "owner_kind": owner_ctx.get("owner_kind", ""),
                    "owner_id": owner_ctx.get("owner_id", ""),
                    "relative_content_signature": relative_signature,
                    "group_signature": full_signature,
                },
            },
        )
        group_obj["group_structure"] = {
            **full_profile,
            "temporal_signature": full_profile.get("content_signature", ""),
        }
        group_obj.setdefault("local_db", {})
        group_obj["local_db"].setdefault("group_table", [])
        group_obj["local_db"].setdefault("residual_table", [])
        group_obj["local_db"].setdefault("memory_table", [])
        group_store.update(group_obj)
        return {"created": True, "group_obj": group_obj}

    def _expand_relative_profile(
        self,
        *,
        relative_profile: dict,
        owner_profile: dict,
        owner_placeholder: str,
        cut_engine,
    ) -> dict:
        expanded_units = []
        owner_units = self._collect_profile_units(owner_profile)
        for unit in self._collect_profile_units(relative_profile):
            if bool(unit.get("is_placeholder")) or str(unit.get("token", "")) == owner_placeholder:
                expanded_units.extend(dict(owner_unit) for owner_unit in owner_units)
                continue
            expanded_units.append(dict(unit))
        if not expanded_units:
            return self._profile_from_units(units=[], cut_engine=cut_engine, ext={"kind": "structure_expanded_profile"})
        return self._profile_from_units(
            units=expanded_units,
            cut_engine=cut_engine,
            ext={
                "kind": "structure_expanded_profile",
                "owner_placeholder": owner_placeholder,
            },
        )

    def _build_relative_residual_profile(
        self,
        *,
        full_profile: dict,
        covered_structure_ids: list[str],
        owner_placeholder: str,
        cut_engine,
        origin_frame_id: str,
    ) -> dict | None:
        covered_ids = {str(structure_id) for structure_id in covered_structure_ids if str(structure_id)}
        if not covered_ids:
            return dict(full_profile)
        residual_units = []
        placeholder_inserted = False
        placeholder_index = 0
        for unit in self._collect_profile_units(full_profile):
            unit_id = str(unit.get("unit_id", ""))
            if unit_id in covered_ids:
                if not placeholder_inserted:
                    residual_units.append(
                        self._make_placeholder_unit(
                            placeholder_token=owner_placeholder,
                            order_index=placeholder_index,
                            origin_frame_id=origin_frame_id,
                        )
                    )
                    placeholder_inserted = True
                    placeholder_index += 1
                continue
            residual_units.append(
                {
                    **dict(unit),
                    "origin_frame_id": origin_frame_id,
                    "source_type": unit.get("source_type", "structure_local"),
                }
            )
            placeholder_index += 1
        if not placeholder_inserted:
            return None
        return self._profile_from_units(
            units=residual_units,
            cut_engine=cut_engine,
            ext={
                "kind": "structure_relative_residual",
                "owner_placeholder": owner_placeholder,
            },
        )

    def _build_descend_relative_profile(
        self,
        *,
        full_profile: dict,
        common_part: dict,
        child_placeholder: str,
        cut_engine,
        origin_frame_id: str,
    ) -> dict | None:
        full_units = self._collect_profile_units(full_profile)
        if not full_units:
            return None
        existing_refs = {
            str(unit_id)
            for pair in common_part.get("matched_pairs", [])
            for unit_id in pair.get("existing_unit_refs", [])
            if str(unit_id)
        }
        incoming_refs = {
            str(unit_id)
            for pair in common_part.get("matched_pairs", [])
            for unit_id in pair.get("incoming_unit_refs", [])
            if str(unit_id)
        }
        full_unit_ids = {str(unit.get("unit_id", "")) for unit in full_units if str(unit.get("unit_id", ""))}
        existing_overlap = len(full_unit_ids & existing_refs)
        incoming_overlap = len(full_unit_ids & incoming_refs)
        matched_refs = incoming_refs if incoming_overlap >= existing_overlap else existing_refs
        if not matched_refs:
            return None
        child_units = []
        placeholder_inserted = False
        placeholder_index = 0
        for unit in full_units:
            unit_id = str(unit.get("unit_id", ""))
            if unit_id in matched_refs:
                if not placeholder_inserted:
                    child_units.append(
                        self._make_placeholder_unit(
                            placeholder_token=child_placeholder,
                            order_index=placeholder_index,
                            origin_frame_id=origin_frame_id,
                        )
                    )
                    placeholder_inserted = True
                    placeholder_index += 1
                continue
            child_units.append(
                {
                    **dict(unit),
                    "origin_frame_id": origin_frame_id,
                    "source_type": unit.get("source_type", "structure_local"),
                }
            )
            placeholder_index += 1
        if not placeholder_inserted:
            return None
        profile = self._profile_from_units(
            units=child_units,
            cut_engine=cut_engine,
            ext={
                "kind": "structure_descend_relative",
                "owner_placeholder": child_placeholder,
            },
        )
        if not self._profile_has_non_placeholder_content(profile, placeholder_token=child_placeholder):
            return None
        return profile

    @staticmethod
    def _profile_has_non_placeholder_content(profile: dict, *, placeholder_token: str) -> bool:
        return any(
            str(unit.get("token", "")) and str(unit.get("token", "")) != placeholder_token
            for group in profile.get("sequence_groups", [])
            for unit in group.get("units", [])
            if isinstance(unit, dict)
        )

    @staticmethod
    def _extract_structure_ids_from_profile(profile: dict) -> list[str]:
        ordered = []
        seen = set()
        for group in profile.get("sequence_groups", []):
            for unit in group.get("units", []):
                if not isinstance(unit, dict) or bool(unit.get("is_placeholder")):
                    continue
                unit_id = str(unit.get("unit_id", ""))
                object_type = str(unit.get("object_type", ""))
                if not unit_id:
                    continue
                if object_type != "st" and not unit_id.startswith("st_"):
                    continue
                if unit_id in seen:
                    continue
                seen.add(unit_id)
                ordered.append(unit_id)
        return ordered

    def _merge_observed_energy_profiles(self, *, profile_maps: list[dict[str, float]], required_ids: list[str]) -> dict[str, float]:
        normalized_maps = [
            self._normalize_external_profile(profile_map, required_ids)
            for profile_map in profile_maps
            if isinstance(profile_map, dict)
        ]
        if not normalized_maps:
            return self._normalize_external_profile({}, required_ids)
        merged = {structure_id: 0.0 for structure_id in required_ids}
        for profile_map in normalized_maps:
            for structure_id in required_ids:
                merged[structure_id] = round(float(merged.get(structure_id, 0.0)) + float(profile_map.get(structure_id, 0.0)), 8)
        divisor = float(len(normalized_maps))
        averaged = {
            structure_id: round(float(merged.get(structure_id, 0.0)) / divisor, 8)
            for structure_id in required_ids
        }
        return self._normalize_external_profile(averaged, required_ids)

    def _normalize_external_profile(self, profile_map: dict[str, float], required_ids: list[str]) -> dict[str, float]:
        keys = [str(structure_id) for structure_id in required_ids if str(structure_id)]
        if not keys:
            keys = [str(key) for key in profile_map.keys() if str(key)]
        if not keys:
            return {}
        values = {key: max(0.0, float(profile_map.get(key, 0.0))) for key in keys}
        total = sum(values.values())
        if total <= 0.0:
            return {key: round(1.0 / len(keys), 8) for key in keys}
        return {key: round(float(values.get(key, 0.0)) / total, 8) for key in keys}

    def _open_owner_context(
        self,
        *,
        owner_kind: str,
        owner_id: str,
        structure_store,
        group_store,
        pointer_index,
        cut_engine,
        trace_id: str,
        tick_id: str,
    ) -> dict | None:
        if owner_kind == "st":
            structure_obj = structure_store.get(owner_id)
            if not structure_obj:
                return None
            pointer_info = {"used_fallback": False, "resolved_db_id": ""}
            structure_db = structure_store.get_db_by_owner(owner_id)
            if not structure_db and pointer_index is not None:
                structure_db, pointer_info = pointer_index.resolve_db(
                    structure_obj=structure_obj,
                    structure_store=structure_store,
                    logger=self._logger,
                    trace_id=trace_id,
                    tick_id=tick_id,
                )
            if not structure_db:
                return None
            if pointer_index is not None:
                pointer_index.cache_structure_db(owner_id, structure_db)
            structure_db.setdefault("group_table", list(structure_db.get("group_table", [])))
            structure_db.setdefault("group_residual_table", [])
            structure_db.setdefault("group_memory_table", [])
            owner_display_text = self._structure_display_text(structure_obj)
            if cut_engine is not None:
                owner_profile = self._profile_from_units(
                    units=[
                        self._make_structure_unit(
                            structure_id=owner_id,
                            display_text=owner_display_text,
                            structure_obj=structure_obj,
                            er=0.0,
                            ev=0.0,
                            order_index=0,
                            source_type="structure_owner",
                            origin_frame_id=owner_id,
                        )
                    ],
                    cut_engine=cut_engine,
                    ext={"kind": "structure_owner_profile", "owner_id": owner_id},
                )
            else:
                owner_profile = {
                    "display_text": owner_display_text,
                    "flat_tokens": [owner_display_text] if owner_display_text else [owner_id],
                    "sequence_groups": [],
                    "content_signature": owner_id,
                }
            return {
                "owner_kind": "st",
                "owner_id": owner_id,
                "owner_display_text": owner_display_text,
                "owner_placeholder": self._owner_placeholder_token(owner_kind="st", owner_id=owner_id, owner_display_text=owner_display_text),
                "owner_profile": owner_profile,
                "structure_obj": structure_obj,
                "db_ref": structure_db,
                "group_table": structure_db.get("group_table", []),
                "residual_table": structure_db.get("group_residual_table", []),
                "memory_table": structure_db.get("group_memory_table", []),
                "used_fallback": bool(pointer_info.get("used_fallback")),
                "resolved_db_id": structure_db.get("structure_db_id", ""),
                "_dirty": False,
            }

        if owner_kind == "sg":
            group_obj = group_store.get(owner_id)
            if not group_obj:
                return None
            group_obj.setdefault("local_db", {})
            local_db = group_obj["local_db"]
            local_db.setdefault("group_table", [])
            local_db.setdefault("residual_table", [])
            local_db.setdefault("memory_table", [])
            owner_profile = self._group_full_profile(group_obj=group_obj, structure_store=structure_store, cut_engine=cut_engine)
            owner_display_text = self._group_display_text(group_obj)
            return {
                "owner_kind": "sg",
                "owner_id": owner_id,
                "owner_display_text": owner_display_text,
                "owner_placeholder": self._owner_placeholder_token(owner_kind="sg", owner_id=owner_id, owner_display_text=owner_display_text),
                "owner_profile": owner_profile,
                "group_obj": group_obj,
                "local_db": local_db,
                "group_table": local_db.get("group_table", []),
                "residual_table": local_db.get("residual_table", []),
                "memory_table": local_db.get("memory_table", []),
                "used_fallback": False,
                "resolved_db_id": owner_id,
                "_dirty": False,
            }
        return None

    def _persist_owner_context(self, owner_ctx: dict, *, structure_store, group_store) -> None:
        if not owner_ctx:
            return
        if not bool(owner_ctx.get("_dirty", False)):
            return
        self._trim_owner_tables(owner_ctx)
        if owner_ctx.get("owner_kind") == "st":
            structure_db = owner_ctx.get("db_ref")
            if not structure_db:
                return
            structure_db["group_table"] = list(owner_ctx.get("group_table", []))
            structure_db["group_residual_table"] = list(owner_ctx.get("residual_table", []))
            structure_db["group_memory_table"] = list(owner_ctx.get("memory_table", []))
            structure_store.update_db(structure_db)
            owner_ctx["_dirty"] = False
            return
        if owner_ctx.get("owner_kind") == "sg":
            group_obj = owner_ctx.get("group_obj")
            if not group_obj:
                return
            local_db = group_obj.setdefault("local_db", {})
            local_db["group_table"] = list(owner_ctx.get("group_table", []))
            local_db["residual_table"] = list(owner_ctx.get("residual_table", []))
            local_db["memory_table"] = list(owner_ctx.get("memory_table", []))
            group_store.update(group_obj)
            owner_ctx["_dirty"] = False

    def _trim_owner_tables(self, owner_ctx: dict) -> None:
        group_limit = max(8, int(self._config.get("group_table_soft_limit", 128)))
        residual_limit = max(16, int(self._config.get("diff_table_soft_limit", 128)))
        memory_limit = max(16, int(self._config.get("structure_memory_table_soft_limit", 128)))
        for entry in owner_ctx.get("group_table", []):
            self._ensure_group_entry_schema(entry)
        for entry in owner_ctx.get("residual_table", []):
            self._ensure_raw_residual_schema(entry)
        owner_ctx["group_table"] = sorted(
            owner_ctx.get("group_table", []),
            key=lambda entry: (
                -float(self._weight.entry_runtime_weight(entry)),
                -float(entry.get("base_weight", 0.0)),
                str(entry.get("entry_id", "")),
            ),
        )[:group_limit]
        owner_ctx["residual_table"] = sorted(
            owner_ctx.get("residual_table", []),
            key=lambda entry: (
                -float(self._weight.entry_runtime_weight(entry)),
                -float(entry.get("base_weight", 0.0)),
                str(entry.get("entry_id", "")),
            ),
        )[:residual_limit]
        owner_ctx["memory_table"] = sorted(
            owner_ctx.get("memory_table", []),
            key=lambda entry: (
                -int(entry.get("last_updated_at", 0)),
                str(entry.get("memory_id", "")),
            ),
        )[:memory_limit]

    def _append_memory_ref(
        self,
        *,
        owner_ctx: dict,
        memory_id: str,
        content_signature: str,
        round_index: int,
        event_kind: str,
    ) -> None:
        if not memory_id:
            return
        now_ms = int(time.time() * 1000)
        for entry in owner_ctx.get("memory_table", []):
            if str(entry.get("memory_id", "")) != memory_id:
                continue
            if str(entry.get("content_signature", "")) != str(content_signature):
                continue
            entry["hit_count"] = int(entry.get("hit_count", 0)) + 1
            entry["last_updated_at"] = now_ms
            entry["round_index"] = round_index
            entry["event_kind"] = event_kind
            self._mark_owner_context_dirty(owner_ctx)
            return
        owner_ctx.setdefault("memory_table", []).append(
            {
                "memory_id": memory_id,
                "content_signature": str(content_signature),
                "event_kind": event_kind,
                "round_index": int(round_index),
                "hit_count": 1,
                "last_updated_at": now_ms,
            }
        )
        self._mark_owner_context_dirty(owner_ctx)

    def _ensure_group_entry_schema(self, entry: dict) -> None:
        now_ms = int(time.time() * 1000)
        entry.setdefault("entry_id", next_id("sge"))
        entry.setdefault("group_id", "")
        entry.setdefault("required_structure_ids", [])
        entry.setdefault("avg_energy_profile", {})
        entry.setdefault("content_signature", "")
        entry.setdefault("temporal_signature", entry.get("content_signature", ""))
        entry.setdefault("display_text", entry.get("group_id", ""))
        entry.setdefault("relative_content_signature", entry.get("content_signature", ""))
        entry.setdefault("relative_flat_tokens", [])
        entry.setdefault("relative_sequence_groups", [])
        entry.setdefault("base_weight", 0.0)
        entry.setdefault("recent_gain", self._weight._target_recent_gain(strength=1.0))
        entry.setdefault("fatigue", 0.0)
        entry.setdefault("runtime_er", 0.0)
        entry.setdefault("runtime_ev", 0.0)
        entry.setdefault("match_count_total", 0)
        entry.setdefault("last_updated_at", now_ms)
        entry.setdefault("last_matched_at", 0)
        entry.setdefault("last_recency_refresh_at", now_ms)
        entry.setdefault("recency_hold_rounds_remaining", int(self._config.get("recency_gain_hold_rounds", 2)))
        entry.setdefault("ext", {})

    def _ensure_raw_residual_schema(self, entry: dict) -> None:
        now_ms = int(time.time() * 1000)
        entry.setdefault("entry_id", next_id("sgr"))
        entry.setdefault("entry_type", "raw_residual")
        entry.setdefault("content_signature", "")
        entry.setdefault("display_text", "")
        entry.setdefault("flat_tokens", [])
        entry.setdefault("sequence_groups", [])
        entry.setdefault("canonical_content_signature", "")
        entry.setdefault("canonical_display_text", "")
        entry.setdefault("canonical_flat_tokens", [])
        entry.setdefault("canonical_sequence_groups", [])
        entry.setdefault("base_weight", 0.0)
        entry.setdefault("recent_gain", self._weight._target_recent_gain(strength=1.0))
        entry.setdefault("fatigue", 0.0)
        entry.setdefault("runtime_er", 0.0)
        entry.setdefault("runtime_ev", 0.0)
        entry.setdefault("match_count_total", 0)
        entry.setdefault("last_updated_at", now_ms)
        entry.setdefault("last_matched_at", 0)
        entry.setdefault("last_recency_refresh_at", now_ms)
        entry.setdefault("recency_hold_rounds_remaining", int(self._config.get("recency_gain_hold_rounds", 2)))
        entry.setdefault("observed_energy_profile", {})
        entry.setdefault("sample_count", 1)
        entry.setdefault("memory_refs", [])
        entry.setdefault("ext", {})
        entry["ext"] = merge_context_metadata(entry.get("ext", {}))
        entry["ext"] = merge_residual_metadata(
            entry["ext"],
            residual_origin_entry_id=entry.get("entry_id", ""),
        )

    def _remove_local_item(self, *, owner_ctx: dict, item: dict) -> None:
        entry_id = str(item.get("entry_id", ""))
        if not entry_id:
            return
        if item.get("item_kind") == "group_entry":
            owner_ctx["group_table"] = [
                entry for entry in owner_ctx.get("group_table", [])
                if str(entry.get("entry_id", "")) != entry_id
            ]
            return
        owner_ctx["residual_table"] = [
            entry for entry in owner_ctx.get("residual_table", [])
            if str(entry.get("entry_id", "")) != entry_id
        ]

    def _group_entry_relative_profile(self, *, owner_ctx: dict, entry: dict, group_obj: dict, cut_engine) -> dict | None:
        self._ensure_group_entry_schema(entry)
        relative_groups = list(entry.get("relative_sequence_groups", []))
        if relative_groups:
            return self._profile_from_stored_groups(
                relative_groups,
                cut_engine=cut_engine,
                ext={
                    "kind": "structure_group_relative",
                    "owner_kind": owner_ctx.get("owner_kind", ""),
                    "owner_id": owner_ctx.get("owner_id", ""),
                },
            )
        full_profile = self._group_full_profile(group_obj=group_obj, structure_store=None, cut_engine=cut_engine)
        owner_ids = set(self._extract_structure_ids_from_profile(owner_ctx.get("owner_profile", {})))
        if not owner_ids:
            return full_profile
        placeholder_token = owner_ctx.get("owner_placeholder", "")
        relative_units = []
        placeholder_inserted = False
        placeholder_index = 0
        for unit in self._collect_profile_units(full_profile):
            unit_id = str(unit.get("unit_id", ""))
            if unit_id in owner_ids:
                if not placeholder_inserted:
                    relative_units.append(
                        self._make_placeholder_unit(
                            placeholder_token=placeholder_token,
                            order_index=placeholder_index,
                            origin_frame_id=str(group_obj.get("id", "")),
                        )
                    )
                    placeholder_inserted = True
                    placeholder_index += 1
                continue
            relative_units.append(dict(unit))
            placeholder_index += 1
        if not placeholder_inserted:
            return None
        profile = self._profile_from_units(
            units=relative_units,
            cut_engine=cut_engine,
            ext={
                "kind": "structure_group_relative",
                "owner_kind": owner_ctx.get("owner_kind", ""),
                "owner_id": owner_ctx.get("owner_id", ""),
            },
        )
        entry["relative_content_signature"] = profile.get("content_signature", "")
        entry["relative_flat_tokens"] = list(profile.get("flat_tokens", []))
        entry["relative_sequence_groups"] = list(profile.get("sequence_groups", []))
        return profile

    def _profile_from_stored_groups(self, groups: list[dict], *, cut_engine, ext: dict | None = None) -> dict:
        if cut_engine is None:
            flat_tokens = [str(token) for group in groups for token in group.get("tokens", []) if str(token)]
            return {
                "display_text": format_sequence_groups(groups) or " / ".join(flat_tokens),
                "flat_tokens": flat_tokens,
                "sequence_groups": list(groups),
                "content_signature": "||".join(str(group.get("group_signature", "")) for group in groups if str(group.get("group_signature", ""))),
                "ext": dict(ext or {}),
            }
        profile = cut_engine.build_sequence_profile_from_groups(groups)
        merged_ext = dict(profile.get("ext", {}))
        merged_ext.update(ext or {})
        profile["ext"] = merged_ext
        return profile

    def _canonicalize_local_profile(self, *, profile: dict, structure_store, group_store, cut_engine) -> dict:
        restored = restore_profile(
            profile,
            cut_engine=cut_engine,
            structure_store=structure_store,
            group_store=group_store,
        )
        merged_ext = dict(restored.get("ext", {}))
        merged_ext.update(profile.get("ext", {}))
        restored["ext"] = merged_ext
        return restored

    def _ensure_raw_residual_canonical_fields(self, *, entry: dict, structure_store, group_store, cut_engine) -> dict:
        self._ensure_raw_residual_schema(entry)
        raw_profile = self._profile_from_stored_groups(
            entry.get("sequence_groups", []),
            cut_engine=cut_engine,
            ext={"kind": "structure_raw_residual"},
        )
        canonical_groups = list(entry.get("canonical_sequence_groups", []))
        if canonical_groups:
            canonical_profile = self._profile_from_stored_groups(
                canonical_groups,
                cut_engine=cut_engine,
                ext={"kind": "structure_raw_residual_canonical"},
            )
        else:
            canonical_profile = self._canonicalize_local_profile(
                profile=raw_profile,
                structure_store=structure_store,
                group_store=group_store,
                cut_engine=cut_engine,
            )
            entry["canonical_content_signature"] = canonical_profile.get("content_signature", "")
            entry["canonical_display_text"] = canonical_profile.get("display_text", "")
            entry["canonical_flat_tokens"] = list(canonical_profile.get("flat_tokens", []))
            entry["canonical_sequence_groups"] = list(canonical_profile.get("sequence_groups", []))
        return {"raw_profile": raw_profile, "canonical_profile": canonical_profile}

    def _build_raw_residual_action(
        self,
        *,
        action_type: str,
        owner_ctx: dict,
        entry: dict,
    ) -> dict:
        storage_table = "group_residual_table" if owner_ctx.get("owner_kind") == "st" else "local_db.residual_table"
        return {
            "type": action_type,
            "type_zh": "追加原始残差信息" if action_type == "append_raw_residual" else "强化原始残差信息",
            "owner_kind": owner_ctx.get("owner_kind", ""),
            "owner_id": owner_ctx.get("owner_id", ""),
            "resolved_db_id": owner_ctx.get("resolved_db_id", ""),
            "storage_table": storage_table,
            "storage_table_zh": "结构数据库.结构组残差表" if storage_table == "group_residual_table" else "结构组本地库.残差表",
            "entry_id": entry.get("entry_id", ""),
            "memory_id": (entry.get("memory_refs", []) or [""])[-1] if entry.get("memory_refs", []) else "",
            "raw_display_text": entry.get("display_text", ""),
            "raw_signature": entry.get("content_signature", ""),
            "raw_sequence_groups": list(entry.get("sequence_groups", [])),
            "canonical_display_text": entry.get("canonical_display_text", ""),
            "canonical_signature": entry.get("canonical_content_signature", ""),
            "canonical_sequence_groups": list(entry.get("canonical_sequence_groups", [])),
        }

    def _group_full_profile(self, *, group_obj: dict, structure_store, cut_engine) -> dict:
        group_structure = group_obj.get("group_structure", {})
        required_ids = [str(structure_id) for structure_id in group_obj.get("required_structure_ids", []) if str(structure_id)]
        if group_structure.get("sequence_groups"):
            stored_profile = self._profile_from_stored_groups(
                list(group_structure.get("sequence_groups", [])),
                cut_engine=cut_engine,
                ext={
                    "kind": "structure_group_full",
                    "group_id": group_obj.get("id", ""),
                },
            )
            stored_ids = self._extract_structure_ids_from_profile(stored_profile)
            if stored_ids == required_ids and len(stored_ids) == len(required_ids):
                return self._enrich_profile_structure_units(
                    profile=stored_profile,
                    structure_store=structure_store,
                )
        units = []
        for order_index, structure_id in enumerate(required_ids):
            structure_obj = structure_store.get(structure_id) if structure_store is not None else None
            display_text = self._structure_display_text(structure_obj) if structure_obj else structure_id
            total = float(group_obj.get("avg_energy_profile", {}).get(structure_id, 1.0))
            units.append(
                self._make_structure_unit(
                    structure_id=structure_id,
                    display_text=display_text,
                    structure_obj=structure_obj,
                    er=total,
                    ev=0.0,
                    order_index=order_index,
                    source_type="group",
                    origin_frame_id=group_obj.get("id", ""),
                )
            )
        profile = self._profile_from_units(
            units=units,
            cut_engine=cut_engine,
            ext={
                "kind": "structure_group_full",
                "group_id": group_obj.get("id", ""),
            },
        ) if cut_engine is not None else {
            "display_text": " / ".join(str(unit.get("token", "")) for unit in units if str(unit.get("token", ""))),
            "flat_tokens": [str(unit.get("token", "")) for unit in units if str(unit.get("token", ""))],
            "sequence_groups": [
                {
                    "group_index": index,
                    "source_type": unit.get("source_type", "group"),
                    "origin_frame_id": unit.get("origin_frame_id", group_obj.get("id", "")),
                    "tokens": [unit.get("token", "")],
                    "units": [dict(unit)],
                }
                for index, unit in enumerate(units)
            ],
            "content_signature": "||".join(f"ST:{unit.get('unit_id', '')}" for unit in units),
        }
        display_text = group_structure.get("display_text", "") or self._group_display_text(group_obj)
        if display_text:
            profile["display_text"] = display_text
        return profile

    def _enrich_profile_structure_units(self, *, profile: dict, structure_store) -> dict:
        if structure_store is None or not isinstance(profile, dict):
            return profile
        sequence_groups = []
        touched = False
        for raw_group in profile.get("sequence_groups", []):
            if not isinstance(raw_group, dict):
                sequence_groups.append(raw_group)
                continue
            cloned_group = dict(raw_group)
            cloned_units = []
            for raw_unit in raw_group.get("units", []):
                if not isinstance(raw_unit, dict):
                    cloned_units.append(raw_unit)
                    continue
                cloned_unit = dict(raw_unit)
                structure_id = str(cloned_unit.get("unit_id", "") or cloned_unit.get("token", "") or "")
                unit_signature = str(cloned_unit.get("unit_signature", "") or "")
                if structure_id and (
                    str(cloned_unit.get("object_type", "") or "") == "st"
                    or unit_signature.startswith("ST:")
                ):
                    structure_obj = structure_store.get(structure_id)
                    if structure_obj is not None:
                        existing_structure_numeric_slots = [
                            dict(slot)
                            for slot in cloned_unit.get("structure_numeric_slots", [])
                            if isinstance(slot, dict)
                        ] if isinstance(cloned_unit.get("structure_numeric_slots", []), list) else []
                        existing_average_numeric_slots = [
                            dict(slot)
                            for slot in cloned_unit.get("average_numeric_slots", [])
                            if isinstance(slot, dict)
                        ] if isinstance(cloned_unit.get("average_numeric_slots", []), list) else []
                        fuzzy_metadata = self._build_structure_fuzzy_metadata(structure_obj)
                        merged_numeric_slots = []
                        seen_numeric_slots: set[tuple[str, float, str]] = set()
                        for slot in [
                            *[dict(slot) for slot in fuzzy_metadata.get("numeric_slots", []) if isinstance(slot, dict)],
                            *existing_structure_numeric_slots,
                        ]:
                            family = str(slot.get("family", "") or "")
                            value = self._coerce_numeric(slot.get("value"))
                            semantic_kind = str(slot.get("semantic_kind", "") or "")
                            if not family or value is None:
                                continue
                            signature = (family, round(float(value), 8), semantic_kind)
                            if signature in seen_numeric_slots:
                                continue
                            seen_numeric_slots.add(signature)
                            merged_numeric_slots.append(
                                {
                                    "family": family,
                                    "value": round(float(value), 8),
                                    **({"semantic_kind": semantic_kind} if semantic_kind else {}),
                                }
                            )
                        cloned_unit["structure_display_text"] = self._structure_display_text(structure_obj)
                        cloned_unit["structure_grouped_display_text"] = (
                            fuzzy_metadata.get("grouped_display_text", "")
                            or cloned_unit.get("display_text", "")
                            or structure_id
                        )
                        cloned_unit["structure_sequence_groups"] = [
                            dict(group)
                            for group in (structure_obj.get("structure", {}) or {}).get("sequence_groups", [])
                            if isinstance(group, dict)
                        ]
                        cloned_unit["structure_display_template"] = (
                            fuzzy_metadata.get("display_template", "")
                            or cloned_unit["structure_grouped_display_text"]
                        )
                        cloned_unit["structure_fuzzy_signature"] = (
                            fuzzy_metadata.get("fuzzy_signature", "")
                            or unit_signature
                        )
                        cloned_unit["structure_numeric_slots"] = merged_numeric_slots
                        if existing_average_numeric_slots:
                            cloned_unit["average_numeric_slots"] = existing_average_numeric_slots
                        touched = True
                cloned_units.append(cloned_unit)
            cloned_group["units"] = cloned_units
            sequence_groups.append(cloned_group)
        if not touched:
            return profile
        enriched = dict(profile)
        enriched["sequence_groups"] = sequence_groups
        return enriched

    @staticmethod
    def _structure_display_text(structure_obj: dict | None) -> str:
        if not structure_obj:
            return ""
        return str(structure_obj.get("structure", {}).get("display_text", structure_obj.get("id", "")))

    @staticmethod
    def _group_display_text(group_obj: dict) -> str:
        group_structure = group_obj.get("group_structure", {})
        display_text = str(group_structure.get("display_text", ""))
        if display_text:
            return display_text
        grouped = format_sequence_groups(list(group_structure.get("sequence_groups", [])))
        if grouped:
            return grouped
        flat_tokens = [str(token) for token in group_structure.get("flat_tokens", []) if str(token)]
        if flat_tokens:
            return " / ".join(flat_tokens)
        return str(group_obj.get("id", ""))

    @staticmethod
    def _owner_placeholder_token(*, owner_kind: str, owner_id: str, owner_display_text: str) -> str:
        """
        Build a SHORT placeholder token.

        Safety note:
        - This token may be used as a last-resort endogenous fragment seed when canonical tokens
          are missing. It must be bounded in length to avoid "display_text pollution" blow-ups.
        """
        label = str(owner_display_text or owner_id or "").strip()
        oid = str(owner_id or "").strip()
        if not label:
            return ""
        # hard cap to keep any fallback token small and safe
        if len(label) > 96:
            label = label[:96]
        if len(oid) > 48:
            oid = oid[:48]
        if owner_kind in {"st", "sg"} and oid:
            return f"SELF[{oid}:{label}]"
        return f"SELF[{label}]"

    def _upsert_group_details(self, base_items: list[dict], new_items: list[dict]) -> list[dict]:
        merged = {}
        for item in list(base_items) + list(new_items):
            key = "|".join(
                [
                    str(item.get("owner_kind", "")),
                    str(item.get("owner_id", "")),
                    str(item.get("entry_id", "")),
                    str(item.get("group_id", "")),
                ]
            )
            current = merged.get(key)
            if current is None or self._is_better_group_detail(item, current):
                merged[key] = item
        return sorted(
            merged.values(),
            key=lambda item: (
                0 if item.get("eligible") else 1,
                -float(item.get("competition_score", 0.0)),
                -len(item.get("required_structure_ids", [])),
                -float(item.get("entry_runtime_weight", 0.0)),
                -float(item.get("runtime_weight", 0.0)),
            ),
        )

    @staticmethod
    def _is_better_group_detail(candidate: dict, current: dict) -> bool:
        candidate_key = (
            bool(candidate.get("eligible")),
            float(candidate.get("competition_score", 0.0)),
            len(candidate.get("required_structure_ids", [])),
            float(candidate.get("entry_runtime_weight", 0.0)),
            float(candidate.get("runtime_weight", 0.0)),
        )
        current_key = (
            bool(current.get("eligible")),
            float(current.get("competition_score", 0.0)),
            len(current.get("required_structure_ids", [])),
            float(current.get("entry_runtime_weight", 0.0)),
            float(current.get("runtime_weight", 0.0)),
        )
        return candidate_key > current_key

    def _build_bias_projections(
        self,
        *,
        group_obj: dict,
        required_ids: list[str],
        matched_er_total: float,
        matched_ev_total: float,
        rho: float,
        structure_store,
    ) -> list[dict]:
        target_ids = self._derive_bias_structures(group_obj=group_obj, required_ids=required_ids)
        if not target_ids:
            return []
        target_weights = self._derive_bias_weight_map(target_ids=target_ids, structure_store=structure_store)
        er_budget = max(0.0, float(matched_er_total)) * max(0.0, float(rho)) * float(self._config.get("structure_bias_er_ratio", 0.18))
        ev_budget = max(0.0, float(matched_ev_total)) * max(0.0, float(rho)) * float(self._config.get("structure_bias_ev_ratio", 0.28))
        projections = []
        for structure_id in target_ids:
            weight = float(target_weights.get(structure_id, 0.0))
            structure_obj = structure_store.get(structure_id)
            projections.append(
                {
                    "structure_id": structure_id,
                    "display_text": self._structure_display_text(structure_obj),
                    "er": round(er_budget * weight, 8),
                    "ev": round(ev_budget * weight, 8),
                    "reason": "structure_group_bias",
                    "source_group_id": group_obj.get("id", ""),
                }
            )
        return [item for item in projections if float(item.get("er", 0.0)) > 0.0 or float(item.get("ev", 0.0)) > 0.0]

    def _derive_bias_structures(self, *, group_obj: dict, required_ids: list[str]) -> list[str]:
        explicit = [str(structure_id) for structure_id in group_obj.get("bias_structure_ids", []) if str(structure_id)]
        if explicit:
            return list(dict.fromkeys(explicit))
        return self._derive_bias_from_required(required_ids)

    @staticmethod
    def _derive_bias_from_required(required_ids: list[str]) -> list[str]:
        return []

    def _derive_bias_weight_map(self, *, target_ids: list[str], structure_store) -> dict[str, float]:
        weights = {}
        now_ms = int(time.time() * 1000)
        for structure_id in target_ids:
            structure_obj = structure_store.get(structure_id)
            if not structure_obj:
                continue
            weights[structure_id] = float(self._preview_structure_stats(structure_obj, now_ms=now_ms).get("runtime_weight", 1.0))
        total = sum(max(0.0, value) for value in weights.values())
        if total <= 0.0:
            if not target_ids:
                return {}
            return {structure_id: round(1.0 / len(target_ids), 8) for structure_id in target_ids}
        return {structure_id: round(max(0.0, float(weights.get(structure_id, 0.0))) / total, 8) for structure_id in target_ids}

    def _build_internal_fragment_from_profile(
        self,
        *,
        owner_id: str,
        owner_kind: str,
        source_group_id: str,
        source_phase: str,
        display_text: str,
        profile: dict,
        total_er: float,
        total_ev: float,
        ext: dict | None = None,
        runtime_bound_attribute_units: list[dict] | None = None,
        force_runtime_attribute_groups: bool = False,
    ) -> dict | None:
        profile_data = dict(profile or {})
        sequence_groups = [
            dict(group)
            for group in (profile_data.get("sequence_groups", []) or [])
            if isinstance(group, dict)
        ]
        flat_tokens = [str(token) for token in (profile_data.get("flat_tokens", []) or []) if str(token)]
        runtime_attribute_groups = self._build_internal_runtime_attribute_groups(
            owner_id=owner_id,
            owner_kind=owner_kind,
            runtime_bound_attribute_units=runtime_bound_attribute_units,
            start_group_index=len(sequence_groups),
            origin_frame_id=str(source_group_id or owner_id or source_phase),
            force_include=force_runtime_attribute_groups,
        )
        if runtime_attribute_groups:
            sequence_groups.extend(runtime_attribute_groups)
            for group in runtime_attribute_groups:
                flat_tokens.extend([str(token) for token in (group.get("tokens", []) or []) if str(token)])
        if not sequence_groups and flat_tokens:
            sequence_groups = [
                {
                    "group_index": 0,
                    "source_type": "internal",
                    "origin_frame_id": owner_id,
                    "tokens": list(flat_tokens),
                }
            ]
        total_energy = round(max(0.0, float(total_er)) + max(0.0, float(total_ev)), 8)
        if total_energy <= 0.0 or not sequence_groups:
            return None
        fragment_ext = dict(ext or {})
        if runtime_attribute_groups:
            fragment_ext.setdefault("runtime_bound_attribute_unit_count", int(len(runtime_attribute_groups)))
            fragment_ext.setdefault(
                "runtime_bound_attribute_names",
                [
                    str(unit.get("attribute_name", ""))
                    for group in runtime_attribute_groups
                    for unit in (group.get("units", []) or [])
                    if isinstance(unit, dict) and str(unit.get("attribute_name", ""))
                ],
            )
        return {
            "fragment_id": next_id("sif"),
            "source_group_id": source_group_id,
            "source_phase": source_phase,
            "source_structure_id": owner_id,
            "source_owner_kind": owner_kind,
            "source_owner_id": owner_id,
            "display_text": str(display_text or profile_data.get("display_text", "") or owner_id),
            "flat_tokens": list(flat_tokens),
            "sequence_groups": sequence_groups,
            "er_hint": round(max(0.0, float(total_er)), 8),
            "ev_hint": round(max(0.0, float(total_ev)), 8),
            "energy_hint": total_energy,
            "ext": fragment_ext,
        }

    def _build_attention_landscape_fragment(
        self,
        *,
        items: list[dict],
        tick_id: str,
        structure_store,
        group_store,
        cut_engine,
        total_er: float,
        total_ev: float,
        profile_cache: dict[str, list[dict]] | None = None,
    ) -> dict | None:
        if not bool(self._config.get("internal_attention_landscape_enabled", True)):
            return None
        if bool(self._config.get("enable_goal_b_char_sa_string_mode", False)):
            # Goal B / 当前默认口径：
            # 内源刺激应优先由 CAM 选中的字符串/结构对象自身的 sequence_groups 构成，
            # 不再额外把 attention landscape 作为一层“结构特征图景”重新投影到内源，
            # 否则会把 ST/SG 级特征单元（如 st_000123）直接混入刺激流，污染真实语义。
            return None
        if not items:
            return None

        projection_ratio = max(0.0, float(self._config.get("internal_attention_landscape_ratio", 0.22) or 0.22))
        scaled_er = round(max(0.0, float(total_er)) * projection_ratio, 8)
        scaled_ev = round(max(0.0, float(total_ev)) * projection_ratio, 8)
        if scaled_er + scaled_ev <= 0.0:
            return None

        sequence_groups: list[dict] = []
        group_index = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            ref_type = str(item.get("ref_object_type", "") or item.get("object_type", "") or "").strip()
            ref_id = str(item.get("ref_object_id", "") or item.get("id", "") or item.get("item_id", "") or "").strip()
            if ref_type == "st" and ref_id:
                structure_obj = structure_store.get(ref_id) if structure_store is not None else None
                if structure_obj is None:
                    continue
                restored_profile = restore_structure_profile(
                    structure_obj,
                    cut_engine=cut_engine,
                    structure_store=structure_store,
                    group_store=group_store,
                    _cache=profile_cache,
                )
                for group in restored_profile.get("sequence_groups", []) or []:
                    if not isinstance(group, dict):
                        continue
                    cloned_group = dict(group)
                    cloned_group["group_index"] = int(group_index)
                    cloned_group["source_group_index"] = int(cloned_group.get("source_group_index", cloned_group.get("group_index", group_index)))
                    cloned_group["source_type"] = "attention_landscape"
                    cloned_group["origin_frame_id"] = str(cloned_group.get("origin_frame_id", ref_id) or ref_id)
                    sequence_groups.append(cloned_group)
                    group_index += 1
                continue

            if ref_type == "sg" and ref_id:
                group_obj = group_store.get(ref_id) if group_store is not None else None
                if group_obj is None:
                    # Fall back to treating the group as a single unit token (display text),
                    # so CAM still contributes to endogenous stimulus even if group store misses.
                    pass
                else:
                    restored_profile = restore_group_profile(
                        group_obj,
                        cut_engine=cut_engine,
                        structure_store=structure_store,
                        group_store=group_store,
                        _cache=profile_cache,
                    )
                    for group in restored_profile.get("sequence_groups", []) or []:
                        if not isinstance(group, dict):
                            continue
                        cloned_group = dict(group)
                        cloned_group["group_index"] = int(group_index)
                        cloned_group["source_group_index"] = int(cloned_group.get("source_group_index", cloned_group.get("group_index", group_index)))
                        cloned_group["source_type"] = "attention_landscape"
                        cloned_group["origin_frame_id"] = str(cloned_group.get("origin_frame_id", ref_id) or ref_id)
                        sequence_groups.append(cloned_group)
                        group_index += 1
                    continue

            unit = self._build_attention_landscape_unit(item=item, group_index=group_index, tick_id=tick_id)
            if unit is None:
                continue
            sequence_groups.append(
                {
                    "group_index": int(group_index),
                    "source_type": "attention_landscape",
                    "origin_frame_id": tick_id,
                    "tokens": [str(unit.get("token", ""))],
                    "units": [unit],
                    "csa_bundles": [],
                }
            )
            group_index += 1

        if not sequence_groups:
            return None

        profile = self._profile_from_stored_groups(
            sequence_groups,
            cut_engine=cut_engine,
            ext={"kind": "attention_landscape", "tick_id": tick_id},
        )
        return self._build_internal_fragment_from_profile(
            owner_id=f"attention_landscape::{tick_id}",
            owner_kind="attention_landscape",
            source_group_id="",
            source_phase="attention_landscape",
            display_text=format_sequence_groups(sequence_groups) or f"attention_landscape::{tick_id}",
            profile=profile,
            total_er=scaled_er,
            total_ev=scaled_ev,
            ext={"item_count": len(items)},
        )

    def _build_attention_landscape_unit(self, *, item: dict, group_index: int, tick_id: str) -> dict | None:
        display_text = str(
            item.get("display", "")
            or (item.get("content", {}) or {}).get("display", "")
            or (item.get("content", {}) or {}).get("raw", "")
            or item.get("ref_object_id", "")
            or item.get("item_id", "")
            or ""
        ).strip()
        if not display_text:
            return None
        ref_type = str(item.get("ref_object_type", "") or item.get("object_type", "") or "runtime_item").strip()
        ref_id = str(item.get("ref_object_id", "") or item.get("id", "") or item.get("item_id", "") or display_text).strip()
        er = round(max(0.0, float(item.get("er", 0.0))), 8)
        ev = round(max(0.0, float(item.get("ev", 0.0))), 8)
        return {
            "unit_id": f"cam::{ref_type}::{ref_id}::{group_index}",
            "object_type": ref_type or "runtime_item",
            "token": display_text,
            "display_text": display_text,
            "unit_role": "feature",
            "unit_signature": f"CAM:{ref_type}:{ref_id}",
            "sequence_index": 0,
            "group_index": int(group_index),
            "source_group_index": int(group_index),
            "source_type": "attention_landscape",
            "origin_frame_id": tick_id,
            "er": er,
            "ev": ev,
            "total_energy": round(er + ev, 8),
            "is_punctuation": False,
            "display_visible": True,
            "is_placeholder": False,
            "bundle_id": "",
            "bundle_anchor_unit_id": "",
            "bundle_anchor_signature": "",
            "bundle_signature": "",
            "bundle_member_unit_ids": [],
            "bundle_member_signatures": [],
        }

    def _build_internal_storage_fragments(
        self,
        *,
        storage_summary: dict | None,
        source_group_id: str,
        source_phase: str,
        fallback_total_er: float,
        fallback_total_ev: float,
        cut_engine,
        runtime_bound_attribute_units: list[dict] | None = None,
    ) -> list[dict]:
        if not bool(self._config.get("internal_storage_projection_enabled", True)):
            return []
        if not isinstance(storage_summary, dict):
            return []

        projection_ratio = max(0.0, float(self._config.get("internal_storage_projection_ratio", 0.32) or 0.32))
        if projection_ratio <= 0.0:
            return []
        max_fragments = max(1, int(self._config.get("internal_storage_projection_max_fragments_per_round", 1) or 1))

        candidates: list[tuple[int, int, float, dict]] = []
        for order_index, action in enumerate(storage_summary.get("actions", []) or []):
            if not isinstance(action, dict):
                continue
            canonical_groups = [
                dict(group)
                for group in (action.get("canonical_sequence_groups", []) or [])
                if isinstance(group, dict)
            ]
            if not canonical_groups:
                continue
            profile = self._profile_from_stored_groups(
                canonical_groups,
                cut_engine=cut_engine,
                ext={
                    "kind": "storage_residual_projection",
                    "owner_id": storage_summary.get("owner_id", ""),
                    "entry_id": action.get("entry_id", ""),
                    "action_type": action.get("type", ""),
                },
            )
            er_total, ev_total = self._profile_er_ev_totals(profile)
            if er_total + ev_total <= 0.0:
                er_total = max(0.0, float(fallback_total_er))
                ev_total = max(0.0, float(fallback_total_ev))
            er_total = round(er_total * projection_ratio, 8)
            ev_total = round(ev_total * projection_ratio, 8)
            if er_total + ev_total <= 0.0:
                continue
            entry_id = str(action.get("entry_id", "") or "")
            owner_id = entry_id or f"storage_residual::{storage_summary.get('owner_id', '')}:{order_index}"
            fragment = self._build_internal_fragment_from_profile(
                owner_id=owner_id,
                owner_kind="storage_residual",
                source_group_id=source_group_id,
                source_phase=source_phase,
                display_text=str(action.get("canonical_display_text", "") or action.get("raw_display_text", "") or owner_id),
                profile=profile,
                total_er=er_total,
                total_ev=ev_total,
                runtime_bound_attribute_units=runtime_bound_attribute_units,
                ext={
                    "storage_owner_kind": str(storage_summary.get("owner_kind", "") or ""),
                    "storage_owner_id": str(storage_summary.get("owner_id", "") or ""),
                    "storage_action_type": str(action.get("type", "") or ""),
                    "storage_entry_id": entry_id,
                    "storage_signature": str(action.get("canonical_signature", "") or action.get("raw_signature", "") or ""),
                },
            )
            if fragment is None:
                continue
            candidates.append(
                (
                    int(self._profile_unit_count(profile)),
                    int(order_index),
                    float(self._profile_total_energy(profile)),
                    fragment,
                )
            )

        if not candidates:
            return []

        candidates.sort(key=lambda item: (int(item[0]), float(item[2]), -int(item[1])), reverse=True)
        return [dict(item[3]) for item in candidates[:max_fragments]]

    def _build_cam_runtime_priority_fragments(
        self,
        *,
        cam_items: list[dict],
        budget_er_map: dict[str, float],
        budget_ev_map: dict[str, float],
        existing_fragments: list[dict],
    ) -> tuple[list[dict], dict]:
        enabled = bool(self._config.get("internal_cam_runtime_priority_projection_enabled", True))
        if not enabled:
            return [], {"enabled": False, "fragment_count": 0, "projected_family_count": 0, "candidate_count": 0}
        patterns = self._runtime_family_patterns_from_config(
            "internal_cam_runtime_priority_projection_patterns",
            fallback_key="internal_fragment_runtime_attribute_priority_patterns",
        )
        if not patterns:
            return [], {"enabled": True, "fragment_count": 0, "projected_family_count": 0, "candidate_count": 0, "reason": "no_patterns"}
        ratio = max(0.0, float(self._config.get("internal_cam_runtime_priority_projection_ratio", 0.08) or 0.08))
        min_energy = max(0.0, float(self._config.get("internal_cam_runtime_priority_projection_min_energy", 0.05) or 0.05))
        max_fragments = max(0, int(self._config.get("internal_cam_runtime_priority_projection_max_fragments", 2) or 2))
        require_unrepresented = bool(self._config.get("internal_cam_runtime_priority_projection_require_unrepresented", True))
        if ratio <= 0.0 or max_fragments <= 0:
            return [], {"enabled": True, "fragment_count": 0, "projected_family_count": 0, "candidate_count": 0, "reason": "ratio_or_cap_zero"}

        represented_by_structure: dict[str, set[str]] = {}
        for fragment in existing_fragments or []:
            if not isinstance(fragment, dict):
                continue
            ext = fragment.get("ext", {}) if isinstance(fragment.get("ext", {}), dict) else {}
            fragment_families = {
                str(name)
                for name in (ext.get("runtime_bound_attribute_names", []) or [])
                if str(name)
            }
            if not fragment_families:
                continue
            candidate_ids = [
                str(ext.get("runtime_priority_parent_structure_id", "") or ""),
                str(ext.get("storage_owner_id", "") or ""),
                str(fragment.get("source_structure_id", "") or ""),
            ]
            for structure_id in candidate_ids:
                if not structure_id:
                    continue
                represented_by_structure.setdefault(structure_id, set()).update(fragment_families)

        ranked_candidates: list[tuple[int, float, float, int, dict, list[dict], list[str]]] = []
        for raw_index, item in enumerate(cam_items or []):
            if not isinstance(item, dict):
                continue
            structure_id = str(item.get("structure_id", "") or "")
            if not structure_id:
                continue
            remaining_er = max(0.0, float(budget_er_map.get(structure_id, 0.0)))
            remaining_ev = max(0.0, float(budget_ev_map.get(structure_id, 0.0)))
            total_energy = round(remaining_er + remaining_ev, 8)
            if total_energy < min_energy:
                continue
            runtime_units = [dict(unit) for unit in (item.get("runtime_bound_attribute_units", []) or []) if isinstance(unit, dict)]
            if not runtime_units:
                continue
            priority_summary = self._summarize_runtime_priority_units(runtime_units, patterns)
            candidate_families = list(priority_summary.get("matched_families", []))
            if not candidate_families:
                continue
            if require_unrepresented:
                represented = represented_by_structure.get(structure_id, set())
                candidate_families = [family for family in candidate_families if family not in represented]
                if not candidate_families:
                    continue
            filtered_units = [
                unit
                for unit in runtime_units
                if str(unit.get("attribute_name", "") or "") in set(candidate_families)
            ]
            if not filtered_units:
                continue
            best_rank = len(patterns)
            max_abs_value = 0.0
            for unit in filtered_units:
                meta = self._runtime_attribute_priority_meta(unit, patterns)
                best_rank = min(best_rank, int(meta.get("priority_rank", len(patterns))))
                max_abs_value = max(max_abs_value, float(meta.get("abs_value", 0.0) or 0.0))
            ranked_candidates.append(
                (
                    int(best_rank),
                    -float(total_energy),
                    -float(max_abs_value),
                    int(raw_index),
                    dict(item),
                    filtered_units,
                    list(candidate_families),
                )
            )
        ranked_candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3]))

        fragments: list[dict] = []
        projected_family_total = 0
        projected_units_total = 0
        chosen_rows: list[dict] = []
        for best_rank, _neg_energy, _neg_abs, raw_index, item, filtered_units, candidate_families in ranked_candidates[:max_fragments]:
            structure_id = str(item.get("structure_id", "") or "")
            remaining_er = max(0.0, float(budget_er_map.get(structure_id, 0.0)))
            remaining_ev = max(0.0, float(budget_ev_map.get(structure_id, 0.0)))
            projected_er = round(remaining_er * ratio, 8)
            projected_ev = round(remaining_ev * ratio, 8)
            if projected_er + projected_ev <= 0.0:
                continue
            fragment = self._build_internal_fragment_from_profile(
                owner_id=f"runtime_priority::{structure_id}",
                owner_kind="runtime_priority_sidepath",
                source_group_id="",
                source_phase="cam_runtime_priority_sidepath",
                display_text=str(item.get("display_text", "") or structure_id),
                profile={"sequence_groups": [], "flat_tokens": []},
                total_er=projected_er,
                total_ev=projected_ev,
                runtime_bound_attribute_units=filtered_units,
                force_runtime_attribute_groups=True,
                ext={
                    "runtime_priority_parent_structure_id": structure_id,
                    "runtime_priority_projected_families": list(candidate_families),
                    "runtime_priority_candidate_rank": int(best_rank),
                    "runtime_priority_projection_ratio": round(float(ratio), 8),
                    "runtime_priority_projection_source": "cam_sidepath",
                },
            )
            if fragment is None:
                continue
            fragments.append(fragment)
            projected_family_total += len(candidate_families)
            projected_units_total += len(filtered_units)
            represented_by_structure.setdefault(structure_id, set()).update(candidate_families)
            chosen_rows.append(
                {
                    "structure_id": structure_id,
                    "family_count": int(len(candidate_families)),
                    "unit_count": int(len(filtered_units)),
                    "families": list(candidate_families),
                    "candidate_rank": int(best_rank),
                    "projected_er": projected_er,
                    "projected_ev": projected_ev,
                    "raw_index": int(raw_index),
                }
            )
        return fragments, {
            "enabled": True,
            "candidate_count": int(len(ranked_candidates)),
            "fragment_count": int(len(fragments)),
            "projected_family_count": int(projected_family_total),
            "projected_unit_count": int(projected_units_total),
            "projection_ratio": round(float(ratio), 8),
            "require_unrepresented": bool(require_unrepresented),
            "items": chosen_rows[: min(16, len(chosen_rows))],
        }

    def _build_internal_group_fragment(
        self,
        *,
        group_obj: dict,
        required_ids: list[str],
        matched_er_total: float,
        matched_ev_total: float,
        rho: float,
        structure_store,
        group_store,
        cut_engine,
        profile_cache: dict[str, list[dict]] | None = None,
        runtime_bound_attribute_units: list[dict] | None = None,
    ) -> dict | None:
        group_id = str(group_obj.get("id", "") or "")
        if not group_id:
            return None
        consumed_er = round(max(0.0, float(matched_er_total)) * max(0.0, float(rho)), 8)
        consumed_ev = round(max(0.0, float(matched_ev_total)) * max(0.0, float(rho)), 8)
        if consumed_er + consumed_ev <= 0.0:
            return None
        restored_profile = restore_group_profile(
            group_obj,
            cut_engine=cut_engine,
            structure_store=structure_store,
            group_store=group_store,
            _cache=profile_cache,
        )
        return self._build_internal_fragment_from_profile(
            owner_id=group_id,
            owner_kind="sg",
            source_group_id=group_id,
            source_phase="activated_group_round",
            display_text=self._group_display_text(group_obj),
            profile=restored_profile,
            total_er=consumed_er,
            total_ev=consumed_ev,
            ext={"required_structure_ids": list(required_ids)},
            runtime_bound_attribute_units=runtime_bound_attribute_units,
        )

    def _build_internal_fragments(
        self,
        *,
        source_group_id: str,
        source_phase: str,
        structure_ids: list[str],
        transfer_er_map: dict[str, float],
        transfer_ev_map: dict[str, float],
        structure_store,
        group_store,
        cut_engine,
        profile_cache: dict[str, list[dict]] | None = None,
        runtime_bound_attribute_map: dict[str, list[dict]] | None = None,
    ) -> list[dict]:
        fragments = []
        for structure_id in structure_ids:
            total_er = round(max(0.0, float(transfer_er_map.get(structure_id, 0.0))), 8)
            total_ev = round(max(0.0, float(transfer_ev_map.get(structure_id, 0.0))), 8)
            if total_er + total_ev <= 0.0:
                continue
            structure_obj = structure_store.get(structure_id)
            if not structure_obj:
                continue
            structure = structure_obj.get("structure", {})
            restored_profile = restore_structure_profile(
                structure_obj,
                cut_engine=cut_engine,
                structure_store=structure_store,
                group_store=group_store,
                _cache=profile_cache,
            )
            fragment = self._build_internal_fragment_from_profile(
                owner_id=str(structure_id),
                owner_kind="st",
                source_group_id=source_group_id,
                source_phase=source_phase,
                display_text=structure.get("display_text", structure_id),
                profile=restored_profile,
                total_er=total_er,
                total_ev=total_ev,
                runtime_bound_attribute_units=list(runtime_bound_attribute_map.get(str(structure_id), []) or []) if runtime_bound_attribute_map else None,
            )
            if fragment is not None:
                fragments.append(fragment)
        return fragments

    def _merge_internal_fragments(self, fragments: list[dict]) -> list[dict]:
        merged = {}
        goal_b_mode = bool(self._config.get("enable_goal_b_char_sa_string_mode", False))
        for fragment in fragments:
            sequence_groups = fragment.get("sequence_groups", []) if isinstance(fragment.get("sequence_groups", []), list) else []
            key = ""
            if goal_b_mode and len(sequence_groups) == 1:
                group = sequence_groups[0] if isinstance(sequence_groups[0], dict) else {}
                if bool(group.get("order_sensitive", False)) and str(group.get("string_unit_kind", "") or "") == "char_sequence":
                    string_key = str(group.get("string_token_text", "") or "")
                    if not string_key:
                        string_key = "".join([str(t) for t in (group.get("tokens", []) or []) if str(t)])
                    if string_key:
                        key = f"goal_b_string::{string_key}"
            if not key:
                key = str(fragment.get("source_structure_id", "")) or str(fragment.get("display_text", "")) or str(fragment.get("fragment_id", ""))
            current = merged.get(key)
            if current is None:
                merged[key] = dict(fragment)
                continue
            current["er_hint"] = round(float(current.get("er_hint", 0.0)) + float(fragment.get("er_hint", 0.0)), 8)
            current["ev_hint"] = round(float(current.get("ev_hint", 0.0)) + float(fragment.get("ev_hint", 0.0)), 8)
            current["energy_hint"] = round(float(current.get("er_hint", 0.0)) + float(current.get("ev_hint", 0.0)), 8)
        return list(merged.values())

    def _apply_internal_resolution_to_fragments(
        self,
        *,
        fragments: list[dict],
        cam_items: list[dict],
        cam_structure_ids: list[str],
        now_ms: int,
        trace_id: str,
        tick_id: str,
    ) -> tuple[list[dict], dict]:
        """
        Dynamic Attention Resource Limitation (DARL) + Progressive Attention Resolution Sampling (PARS)
        ------------------------------------------------------------------------------------------------
        Compress structure-level internal residual fragments before they are converted into internal SA.

        Why:
          Some structures can become very long (hundreds/thousands units). Even if attention selects only
          ~10-20 structures, fully expanding each residual structure will explode internal SA count and cost.

        Constraints:
          - No semantic hardcoding (no punctuation/stop-word lists; no special casing of tokens).
          - Endogenous stimulus stays in the closed loop (we never "turn it off").
          - Soft, resource-aware limits (budget), with temporary fatigue and progressive detail revealing.
        """
        enabled = bool(self._config.get("internal_resolution_enabled", False))
        if not enabled or not fragments:
            return fragments, {
                "enabled": bool(enabled),
                "structure_count": len(fragments),
                "structure_count_total": len(fragments),
                "structure_count_selected": len(fragments),
                "structure_count_dropped": 0,
                "detail_budget": 0,
                "raw_unit_count": 0,
                "selected_unit_count": 0,
                "max_structures_per_tick": int(self._config.get("internal_resolution_max_structures_per_tick", 0) or 0),
                "reason": "disabled_or_empty",
            }

        # Update per-structure "focus credit" (sustained attention -> higher resolution over time).
        if bool(self._config.get("internal_resolution_focus_credit_enabled", True)):
            self._update_internal_resolution_focus_credit(cam_structure_ids=cam_structure_ids)

        cam_map = {str(item.get("structure_id", "")): dict(item) for item in cam_items if str(item.get("structure_id", ""))}

        # Global detail budget (unit count) for this tick.
        nt = self._config.get("_runtime_nt_snapshot", {})
        adr = 0.0
        if isinstance(nt, dict):
            try:
                adr = float(nt.get("ADR", 0.0) or 0.0)
            except Exception:
                adr = 0.0
        base_budget = float(self._config.get("internal_resolution_detail_budget_base", 128))
        adr_gain = float(self._config.get("internal_resolution_detail_budget_adr_gain", 128))
        detail_budget = int(max(1.0, round(base_budget + adr_gain * max(0.0, min(1.0, adr)))))

        min_per_structure = int(self._config.get("internal_resolution_min_detail_per_structure", 4) or 4)
        min_per_structure = max(1, min_per_structure)
        base_max_per_structure = int(self._config.get("internal_resolution_max_detail_per_structure", 64) or 64)
        base_max_per_structure = max(1, base_max_per_structure)
        cost_cap = int(self._config.get("internal_resolution_cost_cap", 512) or 512)
        cost_cap = max(1, cost_cap)
        # Hard cap on how many units we will *materialize/consider* per structure per tick.
        # This is a resource fuse: it does NOT disable internal fragments; it only bounds
        # the per-structure work, while cursor progression still reveals different parts
        # across ticks.
        flat_cap = int(self._config.get("internal_resolution_flat_unit_cap_per_structure", cost_cap) or cost_cap)
        flat_cap = max(int(base_max_per_structure), max(16, flat_cap))

        w_energy = float(self._config.get("internal_resolution_value_weight_total_energy", 1.0) or 1.0)
        w_cp = float(self._config.get("internal_resolution_value_weight_cp_abs", 0.35) or 0.35)
        w_rw = float(self._config.get("internal_resolution_value_weight_runtime_weight", 0.15) or 0.15)
        focus_gamma = float(self._config.get("internal_resolution_focus_credit_gamma", 0.25) or 0.25)
        runtime_family_bonus_enabled = bool(self._config.get("internal_resolution_runtime_family_bonus_enabled", True))
        runtime_family_bonus_patterns = self._runtime_family_patterns_from_config(
            "internal_resolution_runtime_family_bonus_patterns",
            fallback_key="internal_fragment_runtime_attribute_priority_patterns",
        )
        runtime_family_bonus_value = max(0.0, float(self._config.get("internal_resolution_runtime_family_bonus_value", 0.35) or 0.35))
        runtime_family_bonus_abs_gain = max(0.0, float(self._config.get("internal_resolution_runtime_family_bonus_abs_gain", 0.08) or 0.08))
        runtime_family_bonus_abs_value_cap = max(0.0, float(self._config.get("internal_resolution_runtime_family_bonus_abs_value_cap", 2.0) or 2.0))
        runtime_family_bonus_max_families = max(1, int(self._config.get("internal_resolution_runtime_family_bonus_max_families", 2) or 2))
        runtime_family_priority_rank_gain = max(0.0, float(self._config.get("internal_resolution_runtime_family_priority_rank_gain", 0.45) or 0.45))

        # Gather fragment stats (raw unit counts + value/cost).
        infos: list[dict] = []
        raw_total_units = 0
        for fragment in fragments:
            sid = str(fragment.get("source_structure_id", "")) or str(fragment.get("display_text", ""))
            groups = fragment.get("sequence_groups", []) if isinstance(fragment.get("sequence_groups", []), list) else []
            raw_units = 0
            for g in groups:
                if not isinstance(g, dict):
                    continue
                units = g.get("units", [])
                if isinstance(units, list):
                    raw_units += len([u for u in units if isinstance(u, dict)])
            if raw_units <= 0:
                # Legacy fallback: approximate by token length
                raw_units = len([t for t in (fragment.get("flat_tokens", []) or []) if str(t)])
            raw_units_total = max(0, int(raw_units))
            raw_units_eff = min(int(raw_units_total), int(flat_cap))
            raw_total_units += raw_units_eff

            energy = float(fragment.get("energy_hint", 0.0) or 0.0)
            if energy <= 0.0:
                energy = float(fragment.get("er_hint", 0.0) or 0.0) + float(fragment.get("ev_hint", 0.0) or 0.0)

            cam = cam_map.get(sid, {})
            cp_abs = float(cam.get("cp_abs", 0.0) or 0.0)
            runtime_weight = float(cam.get("runtime_weight", 1.0) or 1.0)
            focus_credit = float(self._internal_resolution_focus_credit.get(sid, 0.0) or 0.0)
            focus_multiplier = 1.0 + max(0.0, float(focus_gamma)) * max(0.0, focus_credit)
            runtime_priority = self._summarize_fragment_runtime_priority(fragment, runtime_family_bonus_patterns)
            runtime_priority_family_count = int(runtime_priority.get("matched_family_count", 0) or 0)
            runtime_priority_unit_count = int(runtime_priority.get("matched_unit_count", 0) or 0)
            runtime_priority_max_abs_value = float(runtime_priority.get("max_abs_value", 0.0) or 0.0)
            runtime_priority_best_rank = int(runtime_priority.get("best_priority_rank", len(runtime_family_bonus_patterns)))

            # Value uses only runtime signals (energy/cp/runtime_weight), no token semantics.
            value = max(0.0, w_energy * energy) + max(0.0, w_cp * cp_abs) + max(0.0, w_rw * runtime_weight)
            runtime_family_bonus = 0.0
            if runtime_family_bonus_enabled and runtime_priority_family_count > 0:
                rank_scale = 1.0
                if runtime_family_bonus_patterns:
                    max_rank = max(1, len(runtime_family_bonus_patterns) - 1)
                    best_rank = max(0, min(max_rank, runtime_priority_best_rank))
                    rank_scale += runtime_family_priority_rank_gain * (float(max_rank - best_rank) / float(max_rank))
                runtime_family_bonus = (
                    runtime_family_bonus_value
                    * min(runtime_family_bonus_max_families, runtime_priority_family_count)
                    * rank_scale
                )
                if runtime_priority_max_abs_value > 0.0 and runtime_family_bonus_abs_gain > 0.0:
                    runtime_family_bonus += runtime_family_bonus_abs_gain * min(
                        runtime_priority_max_abs_value,
                        runtime_family_bonus_abs_value_cap,
                    )
            value += runtime_family_bonus
            value_eff = value * focus_multiplier

            cost = max(1, raw_units_eff)
            cost_eff = min(cost, cost_cap)

            # Effective per-structure max can grow with sustained focus (still bounded by raw length + global budget).
            max_k_eff = min(cost, int(round(base_max_per_structure * focus_multiplier)))
            max_k_eff = max(1, max_k_eff)

            infos.append(
                {
                    "structure_id": sid,
                    "raw_unit_count": cost,
                    "raw_unit_count_total": int(raw_units_total),
                    "raw_unit_cap": int(flat_cap),
                    "cost_eff": cost_eff,
                    "energy": energy,
                    "cp_abs": cp_abs,
                    "runtime_weight": runtime_weight,
                    "focus_credit": focus_credit,
                    "focus_multiplier": focus_multiplier,
                    "value_eff": value_eff,
                    "runtime_family_bonus": round(float(runtime_family_bonus), 8),
                    "runtime_priority_family_count": int(runtime_priority_family_count),
                    "runtime_priority_unit_count": int(runtime_priority_unit_count),
                    "runtime_priority_best_rank": int(runtime_priority_best_rank),
                    "runtime_priority_max_abs_value": round(float(runtime_priority_max_abs_value), 8),
                    "runtime_priority_families": list(runtime_priority.get("matched_families", [])),
                    "runtime_priority_patterns": list(runtime_priority.get("matched_patterns", [])),
                    "weight_base": (value_eff / float(cost_eff)) if cost_eff > 0 else float(value_eff),
                    "richness_score": float(value_eff) * math.pow(max(1.0, float(cost)), max(0.0, float(self._config.get("internal_resolution_structure_richness_power", 0.5) or 0.5))),
                    "max_k_eff": max_k_eff,
                }
            )

        if not infos:
            return fragments, {
                "enabled": True,
                "structure_count": 0,
                "structure_count_total": 0,
                "structure_count_selected": 0,
                "structure_count_dropped": 0,
                "detail_budget": detail_budget,
                "raw_unit_count": 0,
                "selected_unit_count": 0,
                "adr": round(float(adr), 8),
                "max_structures_per_tick": int(self._config.get("internal_resolution_max_structures_per_tick", 0) or 0),
            }

        raw_total_units_all_candidates = int(raw_total_units)
        runtime_priority_structure_count_total = sum(
            1 for info in infos if int(info.get("runtime_priority_family_count", 0) or 0) > 0
        )
        runtime_priority_family_match_total_candidates = sum(
            int(info.get("runtime_priority_family_count", 0) or 0)
            for info in infos
        )
        runtime_family_bonus_total_candidates = round(
            sum(float(info.get("runtime_family_bonus", 0.0) or 0.0) for info in infos),
            8,
        )
        # Sort by weight_base for deterministic allocation.
        infos.sort(key=lambda it: (float(it.get("weight_base", 0.0) or 0.0), float(it.get("value_eff", 0.0) or 0.0)), reverse=True)
        structure_count_total = len(infos)
        selection_mode = "density_only"
        rich_candidate_count = 0
        rich_selected_count = 0

        # Soft-but-hard safety fuse: limit how many residual structures can enter
        # the detail allocator per tick. This keeps worst-case spikes bounded
        # without disabling internal fragments entirely.
        max_structures = int(self._config.get("internal_resolution_max_structures_per_tick", 0) or 0)
        if max_structures > 0 and len(infos) > max_structures:
            rich_ratio = float(self._config.get("internal_resolution_rich_structure_ratio", 0.4) or 0.4)
            rich_ratio = max(0.0, min(1.0, rich_ratio))
            rich_min_units = int(
                self._config.get(
                    "internal_resolution_rich_structure_min_units",
                    max(4, int(min_per_structure) + 1),
                )
                or max(4, int(min_per_structure) + 1)
            )
            rich_min_units = max(2, rich_min_units)
            density_ranked = list(infos)
            rich_ranked = [
                it
                for it in sorted(
                    infos,
                    key=lambda item: (
                        float(item.get("richness_score", 0.0) or 0.0),
                        float(item.get("value_eff", 0.0) or 0.0),
                        int(item.get("raw_unit_count", 0) or 0),
                        float(item.get("weight_base", 0.0) or 0.0),
                    ),
                    reverse=True,
                )
                if int(it.get("raw_unit_count", 0) or 0) >= rich_min_units
            ]
            rich_candidate_count = len(rich_ranked)
            rich_slots = 0
            if rich_ranked and rich_ratio > 0.0:
                rich_slots = int(round(float(max_structures) * rich_ratio))
                if rich_slots <= 0:
                    rich_slots = 1
                rich_slots = min(int(max_structures), len(rich_ranked), rich_slots)
            density_slots = max(0, int(max_structures) - int(rich_slots))
            selected_infos: list[dict] = []
            selected_ids: set[str] = set()

            def _select_info(info: dict) -> None:
                sid = str(info.get("structure_id", ""))
                if not sid or sid in selected_ids:
                    return
                selected_ids.add(sid)
                selected_infos.append(info)

            for it in density_ranked:
                if len(selected_infos) >= density_slots:
                    break
                _select_info(it)
            for it in rich_ranked:
                if len(selected_infos) >= int(max_structures):
                    break
                before = len(selected_infos)
                _select_info(it)
                if len(selected_infos) > before:
                    rich_selected_count += 1
            for it in density_ranked:
                if len(selected_infos) >= int(max_structures):
                    break
                _select_info(it)

            infos = selected_infos[: int(max_structures)]
            selection_mode = "hybrid_density_rich" if rich_selected_count > 0 else "density_only"
            keep = {str(it.get("structure_id", "")) for it in infos if str(it.get("structure_id", ""))}
            fragments = [f for f in fragments if (str(f.get("source_structure_id", "")) or str(f.get("display_text", ""))) in keep]
            raw_total_units = sum(int(it.get("raw_unit_count", 0) or 0) for it in infos)

        # Step 1: allocate floors
        alloc: dict[str, int] = {str(it["structure_id"]): 0 for it in infos}
        floor_total = sum(min(int(it.get("raw_unit_count", 0) or 0), min_per_structure) for it in infos)
        remaining = int(detail_budget)

        if floor_total <= detail_budget:
            for it in infos:
                sid = str(it["structure_id"])
                alloc[sid] = int(min(int(it.get("raw_unit_count", 0) or 0), min_per_structure))
            remaining = max(0, int(detail_budget) - sum(alloc.values()))
        else:
            # If budget is too small, allocate 1 to the best few structures (soft pressure).
            for it in infos:
                if remaining <= 0:
                    break
                sid = str(it["structure_id"])
                if int(it.get("raw_unit_count", 0) or 0) <= 0:
                    continue
                alloc[sid] = 1
                remaining -= 1

        # Step 2: distribute remaining budget with diminishing returns.
        if remaining > 0:
            active = {str(it["structure_id"]) for it in infos}
            # Keep loop bounded even if config is odd.
            for _ in range(int(detail_budget) * 2):
                if remaining <= 0 or not active:
                    break
                best_sid = ""
                best_marginal = -1.0
                for it in infos:
                    sid = str(it["structure_id"])
                    if sid not in active:
                        continue
                    current = int(alloc.get(sid, 0) or 0)
                    if current >= int(it.get("raw_unit_count", 0) or 0):
                        active.discard(sid)
                        continue
                    if current >= int(it.get("max_k_eff", 0) or 0):
                        active.discard(sid)
                        continue
                    weight_base = float(it.get("weight_base", 0.0) or 0.0)
                    marginal = weight_base / (1.0 + float(current))
                    if marginal > best_marginal:
                        best_marginal = marginal
                        best_sid = sid
                if not best_sid:
                    break
                alloc[best_sid] = int(alloc.get(best_sid, 0) or 0) + 1
                remaining -= 1

        # Step 3: trim fragments
        trimmed: list[dict] = []
        per_structure: list[dict] = []
        selected_total_units = 0
        selected_attribute_unit_total = 0
        selected_priority_attribute_unit_total = 0
        rescued_priority_attribute_unit_total = 0

        by_sid = {str(f.get("source_structure_id", "")) or str(f.get("display_text", "")): dict(f) for f in fragments}
        for it in infos:
            sid = str(it["structure_id"])
            fragment = by_sid.get(sid)
            if not fragment:
                continue
            target_k = int(alloc.get(sid, 0) or 0)
            # Always keep at least 1 unit when the fragment carries energy (avoid "silent disappearance").
            if target_k <= 0 and float(fragment.get("energy_hint", 0.0) or 0.0) > 0.0:
                target_k = 1
            trimmed_fragment, trim_info = self._trim_internal_fragment_units(
                fragment=fragment,
                target_unit_count=target_k,
                focus_credit=float(it.get("focus_credit", 0.0) or 0.0),
            )
            selected_total_units += int(trim_info.get("selected_unit_count", 0) or 0)
            selected_attribute_unit_total += int(trim_info.get("selected_attribute_unit_count", 0) or 0)
            selected_priority_attribute_unit_total += int(trim_info.get("selected_priority_attribute_unit_count", 0) or 0)
            rescued_priority_attribute_unit_total += int(trim_info.get("rescued_priority_attribute_count", 0) or 0)
            trimmed.append(trimmed_fragment)
            per_structure.append(
                {
                    "structure_id": sid,
                    "raw_unit_count": int(it.get("raw_unit_count", 0) or 0),
                    "selected_unit_count": int(trim_info.get("selected_unit_count", 0) or 0),
                    "selected_attribute_unit_count": int(trim_info.get("selected_attribute_unit_count", 0) or 0),
                    "selected_priority_attribute_unit_count": int(trim_info.get("selected_priority_attribute_unit_count", 0) or 0),
                    "rescued_priority_attribute_count": int(trim_info.get("rescued_priority_attribute_count", 0) or 0),
                    "target_unit_count": int(target_k),
                    "focus_credit": round(float(it.get("focus_credit", 0.0) or 0.0), 8),
                    "runtime_family_bonus": round(float(it.get("runtime_family_bonus", 0.0) or 0.0), 8),
                    "runtime_priority_family_count": int(it.get("runtime_priority_family_count", 0) or 0),
                    "runtime_priority_unit_count": int(it.get("runtime_priority_unit_count", 0) or 0),
                    "runtime_priority_best_rank": int(it.get("runtime_priority_best_rank", len(runtime_family_bonus_patterns)) or len(runtime_family_bonus_patterns)),
                    "cursor_before": int(trim_info.get("cursor_before", 0) or 0),
                    "cursor_after": int(trim_info.get("cursor_after", 0) or 0),
                }
            )

        # Preserve original fragment order (roughly: structure id order in fragments).
        trimmed_by_sid = {str(f.get("source_structure_id", "")) or str(f.get("display_text", "")): f for f in trimmed}
        final_fragments = []
        for f in fragments:
            sid = str(f.get("source_structure_id", "")) or str(f.get("display_text", ""))
            final_fragments.append(trimmed_by_sid.get(sid, f))

        runtime_priority_structure_count_selected = sum(
            1 for info in infos if int(info.get("runtime_priority_family_count", 0) or 0) > 0
        )
        runtime_priority_family_match_total = sum(
            int(info.get("runtime_priority_family_count", 0) or 0)
            for info in infos
        )
        runtime_family_bonus_total = round(
            sum(float(info.get("runtime_family_bonus", 0.0) or 0.0) for info in infos),
            8,
        )
        summary = {
            "enabled": True,
            "detail_budget": int(detail_budget),
            "detail_budget_base": round(float(base_budget), 8),
            "detail_budget_adr_gain": round(float(adr_gain), 8),
            "adr": round(float(adr), 8),
            "structure_count": len(infos),
            "structure_count_total": int(structure_count_total),
            "structure_count_selected": int(len(infos)),
            "structure_count_dropped": max(0, int(structure_count_total) - int(len(infos))),
            "max_structures_per_tick": int(max_structures),
            "selection_mode": selection_mode,
            "rich_candidate_count": int(rich_candidate_count),
            "rich_selected_count": int(rich_selected_count),
            "runtime_priority_structure_count_total_candidates": int(runtime_priority_structure_count_total),
            "runtime_priority_structure_count": int(runtime_priority_structure_count_selected),
            "runtime_priority_family_match_total_candidates": int(runtime_priority_family_match_total_candidates),
            "runtime_priority_family_match_total": int(runtime_priority_family_match_total),
            "runtime_family_bonus_total_candidates": round(float(runtime_family_bonus_total_candidates), 8),
            "runtime_family_bonus_total": round(float(runtime_family_bonus_total), 8),
            "raw_unit_count": int(raw_total_units),
            "raw_unit_count_total_candidates": int(raw_total_units_all_candidates),
            "selected_unit_count": int(selected_total_units),
            "selected_attribute_unit_count": int(selected_attribute_unit_total),
            "selected_priority_attribute_unit_count": int(selected_priority_attribute_unit_total),
            "rescued_priority_attribute_unit_count": int(rescued_priority_attribute_unit_total),
            "min_per_structure": int(min_per_structure),
            "base_max_per_structure": int(base_max_per_structure),
            "cost_cap": int(cost_cap),
            # keep per-structure detail small and auditable (N is usually <= 20)
            "per_structure": per_structure[: min(32, len(per_structure))],
        }

        return final_fragments, summary

    def _update_internal_resolution_focus_credit(self, *, cam_structure_ids: list[str]) -> None:
        decay = float(self._config.get("internal_resolution_focus_credit_decay", 0.90) or 0.90)
        decay = max(0.0, min(1.0, decay))
        gain = float(self._config.get("internal_resolution_focus_credit_gain", 0.35) or 0.35)
        gain = max(0.0, gain)
        cap = float(self._config.get("internal_resolution_focus_credit_cap", 6.0) or 6.0)
        cap = max(0.0, cap)

        # Apply decay to all tracked structures.
        for sid in list(self._internal_resolution_focus_credit.keys()):
            v = float(self._internal_resolution_focus_credit.get(sid, 0.0) or 0.0) * decay
            if v <= 1e-6:
                self._internal_resolution_focus_credit.pop(sid, None)
            else:
                self._internal_resolution_focus_credit[sid] = v

        # Add credit for currently attended structures.
        for sid in cam_structure_ids or []:
            key = str(sid)
            if not key:
                continue
            v = float(self._internal_resolution_focus_credit.get(key, 0.0) or 0.0) + gain
            if v > cap:
                v = cap
            self._internal_resolution_focus_credit[key] = v

    def _trim_internal_fragment_units(self, *, fragment: dict, target_unit_count: int, focus_credit: float) -> tuple[dict, dict]:
        """
        Trim a single fragment to at most target_unit_count units, using:
        - stable anchors (small, identity-preserving)
        - progressive cursor (cover different parts across ticks)
        - temporary fatigue (avoid always picking the same details)
        """
        sid = str(fragment.get("source_structure_id", "")) or str(fragment.get("display_text", ""))
        seq_groups = fragment.get("sequence_groups", []) if isinstance(fragment.get("sequence_groups", []), list) else []

        # Some legacy internal fragments carry only `tokens` (no pre-built `units`).
        # Build deterministic per-token units so resolution can trim them safely.
        normalized_groups: list[dict] = []
        for g_order, g in enumerate(seq_groups):
            if not isinstance(g, dict):
                continue
            units = g.get("units", [])
            if isinstance(units, list) and any(isinstance(u, dict) for u in units):
                normalized_groups.append(g)
                continue
            tokens = [str(t) for t in (g.get("tokens", []) or []) if str(t)]
            if not tokens:
                normalized_groups.append(g)
                continue
            cloned = dict(g)
            cloned_units = []
            for idx, token in enumerate(tokens):
                cloned_units.append(
                    {
                        "unit_id": f"legacy_{g_order}_{idx}",
                        "unit_signature": token,
                        "unit_role": "feature",
                        "token": token,
                        "display_text": token,
                        "display_visible": True,
                        "sequence_index": int(idx),
                    }
                )
            cloned["units"] = cloned_units
            normalized_groups.append(cloned)
        seq_groups = normalized_groups

        # Flatten units with stable ordering.
        flat: list[dict] = []
        for g_order, g in enumerate(seq_groups):
            if not isinstance(g, dict):
                continue
            units = g.get("units", [])
            if not isinstance(units, list) or not units:
                continue
            normalized_units = [u for u in units if isinstance(u, dict)]
            normalized_units.sort(
                key=lambda u: (
                    int(u.get("sequence_index", 0)),
                    str(u.get("unit_id", "")),
                    str(u.get("unit_signature", "")),
                )
            )
            for u in normalized_units:
                unit_id = str(u.get("unit_id", ""))
                sig = str(u.get("unit_signature", "")) or str(u.get("token", ""))
                if not sig and not unit_id:
                    continue
                flat.append(
                    {
                        "group_order": int(g_order),
                        "sequence_index": int(u.get("sequence_index", 0)),
                        "unit_id": unit_id,
                        "unit_signature": sig,
                        "unit_role": str(u.get("unit_role", "feature") or "feature"),
                        "unit": u,
                    }
                )

        raw_unit_count = len(flat)
        if raw_unit_count <= 0:
            return fragment, {"raw_unit_count": 0, "selected_unit_count": 0, "cursor_before": 0, "cursor_after": 0}

        # Cursor for progressive coverage (in the full unit index space).
        raw_unit_total = int(raw_unit_count)
        cursor_before_total = int(self._internal_resolution_cursor.get(sid, 0) or 0)
        cursor_total = int(cursor_before_total % raw_unit_total)

        # Cap materialized units to keep the per-structure cost bounded.
        flat_cap = int(self._config.get("internal_resolution_flat_unit_cap_per_structure", self._config.get("internal_resolution_cost_cap", 512)) or 512)
        flat_cap = max(16, flat_cap)
        capped = False
        if raw_unit_total > flat_cap:
            capped = True
            end = int(cursor_total + flat_cap)
            if end <= raw_unit_total:
                flat = flat[cursor_total:end]
            else:
                flat = flat[cursor_total:] + flat[: (end % raw_unit_total)]
            raw_unit_count = len(flat)
            cursor = 0
        else:
            cursor = int(cursor_total)

        for idx, entry in enumerate(flat):
            entry["flat_index"] = int(idx)

        runtime_attr_rescue_enabled = bool(self._config.get("internal_resolution_runtime_attribute_rescue_enabled", True))
        runtime_attr_patterns = self._runtime_family_patterns_from_config(
            "internal_resolution_runtime_attribute_rescue_patterns",
            fallback_key="internal_fragment_runtime_attribute_priority_patterns",
        )
        runtime_attr_score_bonus = max(0.0, float(self._config.get("internal_resolution_runtime_attribute_score_bonus", 0.75) or 0.75))
        runtime_attr_abs_gain = max(0.0, float(self._config.get("internal_resolution_runtime_attribute_abs_gain", 0.1) or 0.1))
        runtime_attr_abs_value_cap = max(0.0, float(self._config.get("internal_resolution_runtime_attribute_abs_value_cap", 2.0) or 2.0))
        runtime_attr_priority_rank_gain = max(0.0, float(self._config.get("internal_resolution_runtime_attribute_priority_rank_gain", 0.35) or 0.35))
        runtime_attr_rescue_ratio = max(0.0, min(1.0, float(self._config.get("internal_resolution_runtime_attribute_rescue_ratio", 0.25) or 0.25)))
        runtime_attr_rescue_min_slots = max(0, int(self._config.get("internal_resolution_runtime_attribute_rescue_min_slots", 1) or 1))
        runtime_attr_rescue_max_slots = max(runtime_attr_rescue_min_slots, int(self._config.get("internal_resolution_runtime_attribute_rescue_max_slots", 2) or 2))
        priority_attribute_entries: list[dict] = []
        attribute_candidate_count = 0
        for entry in flat:
            unit = entry["unit"]
            if str(entry.get("unit_role", "")) == "attribute":
                attribute_candidate_count += 1
            priority_meta = self._runtime_attribute_priority_meta(unit, runtime_attr_patterns)
            entry["priority_runtime_attribute"] = bool(priority_meta.get("matched", False))
            entry["priority_runtime_attribute_rank"] = int(priority_meta.get("priority_rank", len(runtime_attr_patterns)))
            entry["priority_runtime_attribute_pattern"] = str(priority_meta.get("matched_pattern", "") or "")
            entry["priority_runtime_attribute_abs_value"] = round(float(priority_meta.get("abs_value", 0.0) or 0.0), 8)
            if bool(entry.get("priority_runtime_attribute")):
                priority_attribute_entries.append(entry)

        target_unit_count = int(max(1, min(raw_unit_count, int(target_unit_count or 1))))
        if raw_unit_count <= target_unit_count:
            return fragment, {
                "raw_unit_count": raw_unit_count,
                "selected_unit_count": raw_unit_count,
                "selected_attribute_unit_count": int(attribute_candidate_count),
                "selected_priority_attribute_unit_count": int(len(priority_attribute_entries)),
                "rescued_priority_attribute_count": 0,
                "priority_attribute_candidate_count": int(len(priority_attribute_entries)),
                "cursor_before": int(self._internal_resolution_cursor.get(sid, 0) or 0),
                "cursor_after": int(self._internal_resolution_cursor.get(sid, 0) or 0),
            }

        # Fatigue state (sliding window over recently selected unit signatures).
        window = int(self._config.get("internal_resolution_detail_fatigue_window", 64) or 64)
        window = max(1, window)
        start = float(self._config.get("internal_resolution_detail_fatigue_start", 2.0) or 2.0)
        full = float(self._config.get("internal_resolution_detail_fatigue_full", 8.0) or 8.0)
        min_scale = float(self._config.get("internal_resolution_detail_fatigue_min_scale", 0.0) or 0.0)
        beta = float(self._config.get("internal_resolution_detail_fatigue_beta", 1.0) or 1.0)

        hist = self._internal_resolution_history.get(sid)
        if hist is None:
            hist = deque()
            self._internal_resolution_history[sid] = hist
        counts = self._internal_resolution_history_counts.get(sid)
        if counts is None:
            counts = {}
            self._internal_resolution_history_counts[sid] = counts

        def fatigue_scale(signature: str) -> float:
            c = float(counts.get(signature, 0) or 0)
            if full <= start:
                return 1.0
            if c <= start:
                return 1.0
            if c >= full:
                return float(min_scale)
            t = (c - start) / (full - start)
            t = max(0.0, min(1.0, t))
            base = (1.0 - t)
            if beta != 1.0:
                try:
                    base = math.pow(base, float(beta))
                except Exception:
                    base = (1.0 - t)
            return float(min_scale) + (1.0 - float(min_scale)) * base

        # Cursor for progressive coverage.
        cursor_before = int(cursor_total)

        # Score units (no semantics: energy + fatigue + mild position bonus).
        for idx, entry in enumerate(flat):
            u = entry["unit"]
            sig = str(entry.get("unit_signature", ""))
            try:
                unit_energy = float(u.get("total_energy", float(u.get("er", 0.0)) + float(u.get("ev", 0.0))) or 0.0)
            except Exception:
                unit_energy = 0.0
            unit_energy = max(0.0, unit_energy)
            fscale = fatigue_scale(sig) if sig else 1.0
            pos_bonus = 1.0 / math.sqrt(1.0 + float(idx))
            runtime_attr_bonus = 0.0
            if bool(entry.get("priority_runtime_attribute")):
                rank_scale = 1.0
                if runtime_attr_patterns:
                    max_rank = max(1, len(runtime_attr_patterns) - 1)
                    best_rank = max(0, min(max_rank, int(entry.get("priority_runtime_attribute_rank", len(runtime_attr_patterns)) or len(runtime_attr_patterns))))
                    rank_scale += runtime_attr_priority_rank_gain * (float(max_rank - best_rank) / float(max_rank))
                runtime_attr_bonus = runtime_attr_score_bonus * rank_scale
                if runtime_attr_abs_gain > 0.0:
                    runtime_attr_bonus += runtime_attr_abs_gain * min(
                        float(entry.get("priority_runtime_attribute_abs_value", 0.0) or 0.0),
                        runtime_attr_abs_value_cap,
                    )
            entry["fatigue_scale"] = fscale
            entry["runtime_attr_bonus"] = round(float(runtime_attr_bonus), 8)
            entry["score"] = (1.0 + unit_energy) * fscale * (0.85 + 0.15 * pos_bonus) + runtime_attr_bonus

        # Anchors: prefer non-attribute units when available (structural role, not token semantics).
        stable_anchor_count = int(self._config.get("internal_resolution_stable_anchor_count", 1) or 1)
        stable_anchor_count = max(0, stable_anchor_count)
        anchor_ratio = float(self._config.get("internal_resolution_anchor_ratio", 0.35) or 0.35)
        anchor_ratio = max(0.0, min(1.0, anchor_ratio))
        anchor_target = int(round(float(target_unit_count) * anchor_ratio))
        anchor_target = max(stable_anchor_count, anchor_target)
        anchor_target = max(0, min(target_unit_count, anchor_target))

        candidates = [e for e in flat if str(e.get("unit_role", "")) != "attribute"]
        if len(candidates) < max(1, anchor_target):
            candidates = list(flat)
        candidates.sort(key=lambda e: (-float(e.get("score", 0.0) or 0.0), int(e.get("sequence_index", 0)), str(e.get("unit_id", ""))))
        selected_idx: set[int] = set()
        anchor_selected_idx: set[int] = set()
        for e in candidates[:anchor_target]:
            index = int(e.get("flat_index", 0) or 0)
            selected_idx.add(index)
            anchor_selected_idx.add(index)

        rescued_priority_idx: set[int] = set()
        if runtime_attr_rescue_enabled and priority_attribute_entries:
            desired_rescue_slots = max(runtime_attr_rescue_min_slots, int(round(float(target_unit_count) * runtime_attr_rescue_ratio)))
            desired_rescue_slots = min(runtime_attr_rescue_max_slots, desired_rescue_slots)
            available_rescue_slots = max(0, target_unit_count - len(anchor_selected_idx))
            rescue_target = min(len(priority_attribute_entries), available_rescue_slots, desired_rescue_slots)
            priority_attribute_entries.sort(
                key=lambda e: (
                    int(e.get("priority_runtime_attribute_rank", len(runtime_attr_patterns))),
                    -float(e.get("priority_runtime_attribute_abs_value", 0.0) or 0.0),
                    -float(e.get("score", 0.0) or 0.0),
                    int(e.get("sequence_index", 0)),
                    str(e.get("unit_id", "")),
                )
            )
            for entry in priority_attribute_entries:
                if len(rescued_priority_idx) >= rescue_target:
                    break
                index = int(entry.get("flat_index", 0) or 0)
                if index in selected_idx:
                    continue
                selected_idx.add(index)
                rescued_priority_idx.add(index)

        # Detail fill: walk from cursor, skipping zero-fatigue units, then fall back to top scores.
        need = int(target_unit_count - len(selected_idx))
        detail_picks = 0
        if need > 0:
            i = cursor
            loops = 0
            while need > 0 and loops < raw_unit_count:
                if i not in selected_idx and float(flat[i].get("fatigue_scale", 1.0) or 1.0) > 0.0:
                    selected_idx.add(i)
                    need -= 1
                    detail_picks += 1
                i = (i + 1) % raw_unit_count
                loops += 1
        if need > 0:
            remaining = [i for i in range(raw_unit_count) if i not in selected_idx]
            remaining.sort(key=lambda i: (-float(flat[i].get("score", 0.0) or 0.0), int(flat[i].get("sequence_index", 0)), str(flat[i].get("unit_id", ""))))
            for i in remaining:
                if need <= 0:
                    break
                selected_idx.add(i)
                need -= 1
                detail_picks += 1

        # Bundle closure: if a bundle member is selected, try to include its bundle anchor.
        id_to_idx = {str(entry.get("unit_id", "")): idx for idx, entry in enumerate(flat) if str(entry.get("unit_id", ""))}
        must_include: set[int] = set()
        for i in list(selected_idx):
            u = flat[i]["unit"]
            anchor_id = str(u.get("bundle_anchor_unit_id", "") or "")
            if anchor_id and anchor_id in id_to_idx:
                must_include.add(int(id_to_idx[anchor_id]))
        if must_include:
            selected_idx |= must_include
            # Enforce hard cap by removing lowest-score non-must units.
            while len(selected_idx) > target_unit_count:
                protected_idx = set(must_include) | set(rescued_priority_idx)
                removable = [i for i in selected_idx if i not in protected_idx]
                if not removable:
                    break
                removable.sort(key=lambda i: (float(flat[i].get("score", 0.0) or 0.0), -int(flat[i].get("sequence_index", 0))))
                selected_idx.discard(removable[0])

        # Rebuild groups with selected units.
        selected_unit_ids = {str(flat[i].get("unit_id", "")) for i in selected_idx if str(flat[i].get("unit_id", ""))}
        selected_signatures = {str(flat[i].get("unit_signature", "")) for i in selected_idx if str(flat[i].get("unit_signature", ""))}

        new_groups: list[dict] = []
        for g_order, g in enumerate(seq_groups):
            if not isinstance(g, dict):
                continue
            units = g.get("units", [])
            if not isinstance(units, list) or not units:
                continue
            new_units = []
            for u in units:
                if not isinstance(u, dict):
                    continue
                uid = str(u.get("unit_id", ""))
                sig = str(u.get("unit_signature", "")) or str(u.get("token", ""))
                if uid and uid in selected_unit_ids:
                    new_units.append(dict(u))
                elif (not uid) and sig and sig in selected_signatures:
                    new_units.append(dict(u))
            if not new_units:
                continue
            cloned = dict(g)
            cloned["units"] = new_units
            cloned["tokens"] = [str(u.get("token", "")) for u in new_units if str(u.get("token", ""))]
            new_groups.append(cloned)

        if not new_groups:
            # Safety fallback: keep a tiny prefix of the first group.
            first = None
            for g in seq_groups:
                if isinstance(g, dict) and isinstance(g.get("units", []), list) and g.get("units"):
                    first = dict(g)
                    first["units"] = [dict(u) for u in (g.get("units", []) or [])[:target_unit_count] if isinstance(u, dict)]
                    first["tokens"] = [str(u.get("token", "")) for u in first["units"] if str(u.get("token", ""))]
                    break
            if first:
                new_groups = [first]

        # Update cursor for progressive coverage.
        advance = max(1, int(detail_picks))
        cursor_after_total = int((cursor_total + advance) % raw_unit_total)
        self._internal_resolution_cursor[sid] = cursor_after_total

        # Update fatigue history with selected signatures (temporary; sliding window).
        selected_sigs = [str(flat[i].get("unit_signature", "")) for i in selected_idx if str(flat[i].get("unit_signature", ""))]
        for sig in selected_sigs:
            # Ensure window size by popping oldest.
            while len(hist) >= window:
                old = hist.popleft()
                if old:
                    counts[old] = int(counts.get(old, 0) or 0) - 1
                    if int(counts.get(old, 0) or 0) <= 0:
                        counts.pop(old, None)
            hist.append(sig)
            counts[sig] = int(counts.get(sig, 0) or 0) + 1

        new_fragment = dict(fragment)
        new_fragment["sequence_groups"] = new_groups
        new_fragment["flat_tokens"] = [token for g in new_groups for token in (g.get("tokens", []) or []) if str(token)]
        new_fragment["ext"] = dict(new_fragment.get("ext", {}) or {})
        new_fragment["ext"]["internal_resolution"] = {
            "enabled": True,
            "raw_unit_count": int(raw_unit_count),
            "raw_unit_count_total": int(raw_unit_total),
            "raw_unit_cap": int(flat_cap),
            "raw_unit_capped": bool(capped),
            "selected_unit_count": int(sum(len(g.get("units", [])) for g in new_groups if isinstance(g, dict))),
            "selected_attribute_unit_count": int(sum(1 for i in selected_idx if str(flat[i].get("unit_role", "")) == "attribute")),
            "selected_priority_attribute_unit_count": int(sum(1 for i in selected_idx if bool(flat[i].get("priority_runtime_attribute")))),
            "rescued_priority_attribute_count": int(len(rescued_priority_idx)),
            "priority_attribute_candidate_count": int(len(priority_attribute_entries)),
            "target_unit_count": int(target_unit_count),
            "cursor_before": int(cursor_before),
            "cursor_after": int(cursor_after_total),
            "focus_credit": round(float(focus_credit), 8),
        }

        return new_fragment, {
            "raw_unit_count": int(raw_unit_count),
            "raw_unit_count_total": int(raw_unit_total),
            "raw_unit_cap": int(flat_cap),
            "raw_unit_capped": bool(capped),
            "selected_unit_count": int(new_fragment["ext"]["internal_resolution"]["selected_unit_count"]),
            "selected_attribute_unit_count": int(new_fragment["ext"]["internal_resolution"]["selected_attribute_unit_count"]),
            "selected_priority_attribute_unit_count": int(new_fragment["ext"]["internal_resolution"]["selected_priority_attribute_unit_count"]),
            "rescued_priority_attribute_count": int(new_fragment["ext"]["internal_resolution"]["rescued_priority_attribute_count"]),
            "priority_attribute_candidate_count": int(new_fragment["ext"]["internal_resolution"]["priority_attribute_candidate_count"]),
            "cursor_before": int(cursor_before),
            "cursor_after": int(cursor_after_total),
        }

    @staticmethod
    def _max_total_budget(structure_ids: list[str], budget_er_map: dict[str, float], budget_ev_map: dict[str, float]) -> float:
        return round(
            sum(
                max(0.0, float(budget_er_map.get(structure_id, 0.0))) + max(0.0, float(budget_ev_map.get(structure_id, 0.0)))
                for structure_id in structure_ids
            ),
            8,
        )

    @staticmethod
    def _build_budget_snapshot(structure_ids: list[str], budget_er_map: dict[str, float], budget_ev_map: dict[str, float]) -> dict[str, dict[str, float]]:
        return {
            structure_id: {
                "er": round(max(0.0, float(budget_er_map.get(structure_id, 0.0))), 8),
                "ev": round(max(0.0, float(budget_ev_map.get(structure_id, 0.0))), 8),
                "total": round(max(0.0, float(budget_er_map.get(structure_id, 0.0))) + max(0.0, float(budget_ev_map.get(structure_id, 0.0))), 8),
            }
            for structure_id in structure_ids
        }

    def _build_structure_refs(self, structure_ids: list[str], structure_store) -> list[dict]:
        refs = []
        for structure_id in structure_ids or []:
            structure_obj = structure_store.get(structure_id)
            refs.append(
                {
                    "structure_id": structure_id,
                    "display_text": self._structure_display_text(structure_obj) or structure_id,
                    "content_signature": structure_obj.get("structure", {}).get("content_signature", "") if structure_obj else "",
                    "exists": bool(structure_obj),
                }
            )
        return refs

    def _build_group_debug_payload(self, group_obj: dict, structure_store, cut_engine, *, group_profile: dict | None = None) -> dict:
        now_ms = int(time.time() * 1000)
        stats = self._preview_group_stats(group_obj, now_ms=now_ms)
        profile = group_profile or self._group_full_profile(group_obj=group_obj, structure_store=structure_store, cut_engine=cut_engine)
        group_structure = group_obj.get("group_structure", {})
        return {
            "group_id": group_obj.get("id", ""),
            "display_text": self._group_display_text(group_obj),
            "grouped_display_text": profile.get("display_text", self._group_display_text(group_obj)),
            "sequence_groups": list(profile.get("sequence_groups", [])),
            "required_structure_ids": list(group_obj.get("required_structure_ids", [])),
            "bias_structure_ids": list(group_obj.get("bias_structure_ids", [])),
            "required_structures": self._build_structure_refs(group_obj.get("required_structure_ids", []), structure_store),
            "bias_structures": self._build_structure_refs(group_obj.get("bias_structure_ids", []), structure_store),
            "avg_energy_profile": dict(group_obj.get("avg_energy_profile", {})),
            "content_signature": group_structure.get("content_signature", profile.get("content_signature", "")),
            "temporal_signature": group_structure.get("temporal_signature", group_structure.get("content_signature", profile.get("content_signature", ""))),
            "flat_tokens": list(profile.get("flat_tokens", [])),
            "base_weight": round(float(stats.get("base_weight", 0.0)), 8),
            "recent_gain": round(float(stats.get("recent_gain", 1.0)), 8),
            "fatigue": round(float(stats.get("fatigue", 0.0)), 8),
            "runtime_weight": round(float(stats.get("runtime_weight", 1.0)), 8),
        }







