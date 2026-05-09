# -*- coding: utf-8 -*-
"""
Stimulus-level retrieval-storage for HDB.
"""

from __future__ import annotations

import math
import time
from collections import Counter
from typing import Any

from ._context_metadata import extract_context_metadata, merge_context_metadata, merge_residual_metadata
from ._id_generator import next_id
from ._match_scoring_v2 import build_match_score_v2
from ._owner_runtime_budget import build_owner_runtime_candidate_view
from ._profile_restore import restore_profile, restore_structure_profile
from ._structure_resolver import (
    canonicalize_profile as shared_canonicalize_profile,
    find_exact_structure_by_signature as shared_find_exact_structure_by_signature,
    resolve_or_create_structure_from_profile as shared_resolve_or_create_structure_from_profile,
)
from ._sequence_display import (
    format_group_display,
    format_semantic_group_display,
    format_semantic_sequence_groups,
    format_sequence_groups,
)


def _candidate_has_identity_context(candidate: dict) -> bool:
    if not isinstance(candidate, dict):
        return False
    source = candidate.get("source", {}) if isinstance(candidate.get("source", {}), dict) else {}
    meta_ext = (
        candidate.get("meta", {}).get("ext", {})
        if isinstance(candidate.get("meta", {}), dict)
        and isinstance(candidate.get("meta", {}).get("ext", {}), dict)
        else {}
    )
    structure_ext = (
        candidate.get("structure", {}).get("ext", {})
        if isinstance(candidate.get("structure", {}), dict)
        and isinstance(candidate.get("structure", {}).get("ext", {}), dict)
        else {}
    )
    ext = candidate.get("ext", {}) if isinstance(candidate.get("ext", {}), dict) else {}
    for container in (meta_ext, structure_ext, ext, source, candidate):
        if (
            str(container.get("context_ref_object_id", "") or "").strip()
            or str(container.get("context_owner_structure_id", "") or "").strip()
            or any(str(value or "").strip() for value in list(container.get("context_path_ids", []) or []))
        ):
            return True
    return False


class StimulusRetrievalEngine:
    def __init__(self, config: dict, weight_engine, logger, maintenance_engine):
        self._config = config
        self._weight = weight_engine
        self._logger = logger
        self._maintenance = maintenance_engine
        # Runtime-only caches scoped to a single `run()` invocation. This is reset
        # at the beginning of each run to avoid cross-tick semantic coupling.
        self._runtime_cache: dict | None = None
        self._runtime_match_now_ms: int | None = None
        self._atomic_structure_id_cache: dict[str, str] = {}
        self._anchor_fatigue: dict[str, dict[str, float]] = {}

    def update_config(self, config: dict) -> None:
        self._config = config
        max_entries = int(self._config.get("stimulus_atomic_structure_cross_tick_cache_max_entries", 2048) or 2048)
        if max_entries <= 0 or not bool(self._config.get("stimulus_atomic_structure_cross_tick_cache_enabled", True)):
            self._atomic_structure_id_cache.clear()
        elif len(self._atomic_structure_id_cache) > max_entries:
            keep = list(self._atomic_structure_id_cache.items())[-max_entries:]
            self._atomic_structure_id_cache = dict(keep)

    def clear_runtime_state(self) -> dict:
        had_runtime_cache = bool(self._runtime_cache)
        had_anchor_fatigue = bool(self._anchor_fatigue)
        self._runtime_cache = None
        self._runtime_match_now_ms = None
        self._anchor_fatigue.clear()
        return {"had_runtime_cache": had_runtime_cache, "had_anchor_fatigue": had_anchor_fatigue}

    def run(
        self,
        *,
        stimulus_packet: dict,
        trace_id: str,
        tick_id: str,
        structure_store,
        pointer_index,
        cut_engine,
        episodic_store,
        enable_storage: bool,
        enable_new_structure_creation: bool,
        max_rounds: int,
        now_ms: int | None = None,
    ) -> dict:
        self._runtime_cache = {
            "raw_residual_entry_profiles": {},
            "structure_profiles": {},
            "owner_local_residual_items": {},
            "owner_local_residual_versions": {},
            "owner_local_residual_indices": {},
            "profile_fuzzy_equivalent_cache": {},
            "profile_signature_count_cache": {},
            "atomic_structure_ids": {},
            "anchor_owner_residual_presence": {},
            "anchor_selected_counts": {},
            "metrics": {
                "local_child_candidate_count": 0,
                "local_child_candidate_pruned_count": 0,
                "shadow_raw_residual_candidate_count": 0,
                "shadow_raw_residual_candidate_pruned_count": 0,
                "shadow_raw_residual_skipped_count": 0,
                "best_structure_match_candidate_count": 0,
                "best_structure_match_pruned_count": 0,
                "best_structure_match_common_part_count": 0,
                "best_structure_match_strict_overlap_fast_reject_count": 0,
                "shadow_raw_residual_common_part_count": 0,
                "owner_local_residual_list_cache_hit_count": 0,
                "owner_local_residual_index_build_count": 0,
                "owner_local_residual_index_cache_hit_count": 0,
                "owner_local_residual_raw_signature_hit_count": 0,
                "owner_local_residual_common_signature_hit_count": 0,
                "owner_local_residual_fuzzy_equivalent_call_count": 0,
                "owner_local_residual_fuzzy_equivalent_cache_hit_count": 0,
                "owner_local_residual_fuzzy_equivalent_signature_hit_count": 0,
                "owner_local_residual_fuzzy_equivalent_fast_reject_count": 0,
                "owner_local_residual_common_overlap_fast_reject_count": 0,
                "owner_local_residual_fuzzy_unit_bucket_pruned_count": 0,
                "owner_local_residual_fuzzy_equivalent_cut_count": 0,
                "owner_runtime_budget_selected_count": 0,
                "owner_runtime_budget_pruned_count": 0,
                "anchor_owner_residual_presence_cache_hit_count": 0,
                "anchor_owner_residual_presence_shared_cache_hit_count": 0,
                "anchor_owner_residual_presence_shared_cache_store_count": 0,
                "anchor_owner_residual_presence_scan_count": 0,
            },
        }
        try:
            self._runtime_match_now_ms = int(now_ms) if now_ms is not None else None
        except Exception:
            self._runtime_match_now_ms = None
        profile = cut_engine.build_sequence_profile_from_stimulus_packet(stimulus_packet)
        # 刺激级的“当前刺激组”必须以 cut engine 规范化后的整包分组为准，
        # 后续匹配、残差记忆、最大共同结构切割都在这个统一视图上进行。
        working_set = self._build_working_set(stimulus_packet, cut_engine=cut_engine)
        if not working_set["groups"]:
            episodic_memory_id = ""
            if enable_storage:
                episodic = episodic_store.append(
                    {
                        "event_summary": "stimulus-level retrieval-storage (empty packet)",
                        "structure_refs": [],
                        "origin": "stimulus_level_rs_empty",
                    },
                    trace_id=trace_id,
                    tick_id=tick_id,
                )
                episodic_memory_id = episodic.get("id", "")
            return {
                "code": "OK",
                "message": "no effective stimulus tokens",
                "round_count": 0,
                "matched_structure_ids": [],
                "new_structure_ids": [],
                "remaining_stimulus_sa_count": 0,
                "episodic_memory_id": episodic_memory_id,
                "episodic_display_text": "",
                "episodic_memory_material": {},
                "storage_summary": {"written_index_count": 0, "cut_count": 0, "new_structure_count": 0},
                "runtime_projection_structures": [],
                "seeded_atomic_structure_ids": [],
                "fallback_used": False,
                "debug": {
                    "input_profile": {
                        "display_text": profile.get("display_text", ""),
                        "flat_tokens": list(profile.get("flat_tokens", [])),
                        "sequence_groups": list(profile.get("sequence_groups", [])),
                        "content_signature": profile.get("content_signature", ""),
                        "feature_units": [],
                    },
                    "round_details": [],
                },
            }

        matched_structure_ids: list[str] = []
        new_structure_ids: list[str] = []
        runtime_projection_structures: list[dict] = []
        written_index_count = 0
        cut_count = 0
        fallback_used = False
        round_count = 0
        debug_round_details: list[dict] = []
        seeded_atomic_structure_ids = self._ensure_atomic_structure_databases(
            working_groups=working_set["groups"],
            structure_store=structure_store,
            pointer_index=pointer_index,
            cut_engine=cut_engine,
            trace_id=trace_id,
            tick_id=tick_id,
            parent_ids=list(stimulus_packet.get("source", {}).get("parent_ids", [])),
            source_packet_id=stimulus_packet.get("id", ""),
        )
        current_packet_preseeded_ids = set(seeded_atomic_structure_ids)
        defer_current_packet_preseed_matching = bool(
            self._config.get("stimulus_atomic_preseed_defer_current_packet_matching_enabled", True)
        )
        seeded_string_projection_ids = self._ensure_goal_b_string_structure_projections(
            working_groups=working_set["groups"],
            structure_store=structure_store,
            pointer_index=pointer_index,
            cut_engine=cut_engine,
            trace_id=trace_id,
            tick_id=tick_id,
            parent_ids=list(stimulus_packet.get("source", {}).get("parent_ids", [])),
            source_packet_id=stimulus_packet.get("id", ""),
            runtime_projection_structures=runtime_projection_structures,
        )
        for sid in seeded_string_projection_ids:
            if sid:
                new_structure_ids.append(sid)
        episodic_memory_id = ""
        episodic_item = None
        episodic_display_text = ""
        episodic_memory_material = {}
        if enable_storage:
            episodic_item = episodic_store.append(
                {
                    "event_summary": "stimulus-level retrieval-storage",
                    "structure_refs": [],
                    "origin": "stimulus_level_rs",
                    "origin_id": stimulus_packet.get("id", ""),
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
            episodic_memory_id = episodic_item.get("id", "")

        transfer_ratio = max(0.0, float(self._config.get("stimulus_match_transfer_ratio", 1.0)))
        residual_min_energy = max(0.0, float(self._config.get("stimulus_residual_min_energy", 0.05)))
        min_common_length = int(self._config.get("min_cut_common_length", 2))
        early_stop_enabled = bool(self._config.get("stimulus_early_stop_enabled", True))
        early_stop_patience_rounds = max(1, int(self._config.get("stimulus_early_stop_patience_rounds", 2)))
        early_stop_min_progress_ratio = max(0.0, float(self._config.get("stimulus_early_stop_min_progress_ratio", 0.01)))
        early_stop_high_energy_unit_threshold = max(
            0.0,
            float(self._config.get("stimulus_early_stop_high_energy_unit_threshold", max(0.0, residual_min_energy * 5.0))),
        )
        object_projection_dominance_early_stop_enabled = bool(
            self._config.get("stimulus_object_projection_dominance_early_stop_enabled", True)
        )
        object_projection_dominance_min_rounds = max(
            0,
            int(self._config.get("stimulus_object_projection_dominance_min_rounds", 8)),
        )
        object_projection_dominance_ratio = max(
            0.0,
            float(self._config.get("stimulus_object_projection_dominance_ratio", 1.25)),
        )
        object_projection_dominance_min_remaining_energy = max(
            1e-9,
            float(self._config.get("stimulus_object_projection_dominance_min_remaining_energy", 0.05)),
        )
        object_projection_dominance_require_memory_id = bool(
            self._config.get("stimulus_object_projection_dominance_require_memory_id_enabled", True)
        )
        object_projection_dominance_require_transfer = bool(
            self._config.get(
                "stimulus_object_projection_dominance_require_transfer_dominance_enabled",
                True,
            )
        )
        object_projection_dominance_transfer_ratio = max(
            0.0,
            float(self._config.get("stimulus_object_projection_dominance_transfer_ratio", 1.0)),
        )

        low_progress_streak = 0
        last_round_progress_ratio: float | None = None
        last_round_consumed_total = 0.0
        last_round_remaining_total = 0.0
        cumulative_transferred_total = 0.0
        early_stop_reason = ""
        early_stop_object_projection_total = 0.0
        early_stop_remaining_total = 0.0
        early_stop_object_projection_ratio = 0.0
        early_stop_transfer_total = 0.0
        early_stop_transfer_ratio = 0.0
        early_stop_transfer_guard_blocked_count = 0

        for round_index in range(1, max_rounds + 1):
            remaining_units = self._flatten_remaining_units(working_set["groups"])
            if not remaining_units:
                break

            remaining_total_er = round(sum(float(unit.get("er", 0.0)) for unit in remaining_units), 8)
            remaining_total_ev = round(sum(float(unit.get("ev", 0.0)) for unit in remaining_units), 8)
            if remaining_total_er + remaining_total_ev < residual_min_energy:
                break

            # Growth-era stop: once full object-side projection already dominates
            # the raw tail, continuing to nibble one atomic fallback after another
            # adds cost and old-mouth audit detail, but little cognition value.
            if (
                early_stop_enabled
                and object_projection_dominance_early_stop_enabled
                and round_count >= object_projection_dominance_min_rounds
                and object_projection_dominance_ratio > 0.0
            ):
                remaining_total_energy = float(remaining_total_er + remaining_total_ev)
                projection_total = self._runtime_projection_energy_total(runtime_projection_structures)
                denominator = max(remaining_total_energy, object_projection_dominance_min_remaining_energy)
                observed_ratio = float(projection_total) / float(max(1e-9, denominator))
                memory_ready = (not object_projection_dominance_require_memory_id) or bool(episodic_memory_id)
                transfer_denominator = max(remaining_total_energy, object_projection_dominance_min_remaining_energy)
                observed_transfer_ratio = float(cumulative_transferred_total) / float(max(1e-9, transfer_denominator))
                transfer_ready = (
                    (not object_projection_dominance_require_transfer)
                    or object_projection_dominance_transfer_ratio <= 0.0
                    or observed_transfer_ratio >= object_projection_dominance_transfer_ratio
                )
                if (
                    memory_ready
                    and projection_total > 0.0
                    and observed_ratio >= object_projection_dominance_ratio
                    and not transfer_ready
                ):
                    early_stop_transfer_guard_blocked_count += 1
                    self._increment_runtime_metric("object_projection_dominance_transfer_guard_blocked_count", 1)
                if (
                    memory_ready
                    and transfer_ready
                    and projection_total > 0.0
                    and observed_ratio >= object_projection_dominance_ratio
                ):
                    early_stop_object_projection_total = round(float(projection_total), 8)
                    early_stop_remaining_total = round(float(remaining_total_energy), 8)
                    early_stop_object_projection_ratio = round(float(observed_ratio), 8)
                    early_stop_transfer_total = round(float(cumulative_transferred_total), 8)
                    early_stop_transfer_ratio = round(float(observed_transfer_ratio), 8)
                    early_stop_reason = (
                        "object_projection_dominates_remaining"
                        f" completed_rounds={int(round_count)}"
                        f" projection_total={round(float(projection_total), 6)}"
                        f" remaining_total={round(float(remaining_total_energy), 6)}"
                        f" ratio={round(float(observed_ratio), 6)}"
                        f" transfer_total={round(float(cumulative_transferred_total), 6)}"
                        f" transfer_ratio={round(float(observed_transfer_ratio), 6)}"
                        f" threshold={round(float(object_projection_dominance_ratio), 6)}"
                        f" transfer_threshold={round(float(object_projection_dominance_transfer_ratio), 6)}"
                        f" memory_id_ready={bool(episodic_memory_id)}"
                    )
                    self._set_runtime_metric("object_projection_dominance_early_stop_triggered", 1)
                    self._set_runtime_metric("object_projection_dominance_early_stop_completed_rounds", int(round_count))
                    self._set_runtime_metric(
                        "object_projection_dominance_early_stop_projection_total",
                        early_stop_object_projection_total,
                    )
                    self._set_runtime_metric(
                        "object_projection_dominance_early_stop_remaining_total",
                        early_stop_remaining_total,
                    )
                    self._set_runtime_metric(
                        "object_projection_dominance_early_stop_ratio",
                        early_stop_object_projection_ratio,
                    )
                    self._set_runtime_metric(
                        "object_projection_dominance_early_stop_transfer_total",
                        early_stop_transfer_total,
                    )
                    self._set_runtime_metric(
                        "object_projection_dominance_early_stop_transfer_ratio",
                        early_stop_transfer_ratio,
                    )
                    break

            # Early-stop check (evaluated on the residual packet *after* the previous round).
            # Suppress early-stop if there is still a clearly high-energy stimulus unit in the stream.
            if early_stop_enabled and last_round_progress_ratio is not None:
                remaining_total_energy = float(remaining_total_er + remaining_total_ev)
                max_unit_energy = 0.0
                for unit in remaining_units:
                    try:
                        e = float(unit.get("er", 0.0)) + float(unit.get("ev", 0.0))
                    except Exception:
                        e = 0.0
                    if e > max_unit_energy:
                        max_unit_energy = e
                high_energy_present = max_unit_energy >= early_stop_high_energy_unit_threshold
                low_progress = float(last_round_progress_ratio) < early_stop_min_progress_ratio
                if (not high_energy_present) and low_progress:
                    low_progress_streak += 1
                else:
                    low_progress_streak = 0
                if low_progress_streak >= early_stop_patience_rounds:
                    early_stop_reason = (
                        "low_progress_no_high_energy"
                        f" streak={low_progress_streak}"
                        f" last_progress_ratio={round(float(last_round_progress_ratio), 6)}"
                        f" last_consumed_total={round(float(last_round_consumed_total), 6)}"
                        f" last_remaining_total={round(float(last_round_remaining_total), 6)}"
                        f" remaining_total={round(float(remaining_total_energy), 6)}"
                        f" max_unit_energy={round(float(max_unit_energy), 6)}"
                        f" high_energy_threshold={round(float(early_stop_high_energy_unit_threshold), 6)}"
                    )
                    break

            round_count = round_index
            anchor_unit = self._select_anchor_unit(
                remaining_units,
                structure_store=structure_store,
                pointer_index=pointer_index,
                round_index=round_index,
                current_packet_preseeded_ids=current_packet_preseeded_ids
                if defer_current_packet_preseed_matching
                else set(),
            )
            if not anchor_unit:
                break

            focus_group = self._find_group(working_set["groups"], int(anchor_unit.get("group_index", 0)))
            if not focus_group:
                break

            groups_before = self._clone_working_groups(working_set["groups"])
            emit_full_round_debug = self._emit_full_round_debug(round_index)
            remaining_tokens_before = (
                self._collect_remaining_tokens(groups_before)
                if emit_full_round_debug
                else self._collect_remaining_tokens_preview(groups_before)
            )
            remaining_profile = cut_engine.build_sequence_profile_from_groups(groups_before)
            focus_tokens_before = (
                self._collect_remaining_tokens([focus_group])
                if emit_full_round_debug
                else self._collect_remaining_tokens_preview([focus_group])
            )
            candidate_lookup, best, candidate_details, shadow_candidate_details = self._resolve_anchor_chain_match(
                anchor_unit=anchor_unit,
                # PERF: remaining_units 已经是从当前 working_set 扁平化得到的快照（并且是 dict 拷贝）。
                # 这里再对 groups_before 扁平化一次属于重复工作，且对匹配结果没有影响。
                focus_window_units=remaining_units,
                incoming_profile=remaining_profile,
                competition_units=remaining_units,
                structure_store=structure_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
                trace_id=trace_id,
                tick_id=tick_id,
                source_packet_id=stimulus_packet.get("id", ""),
                parent_ids=list(stimulus_packet.get("source", {}).get("parent_ids", [])),
                round_index=round_index,
            )
            fallback_used = fallback_used or bool(candidate_lookup.get("used_recent_fallback"))

            created_common_structure = None
            created_residual_structure = None
            created_fresh_structure = None
            structure_stats_before = None
            structure_stats_after = None
            transferred_er = 0.0
            transferred_ev = 0.0
            covered_tokens: list[str] = []
            covered_range = [0, 0]
            transfer_similarity = 0.0

            if not best:
                debug_round_details.append(
                    self._build_round_debug(
                        round_index=round_index,
                        anchor_unit=anchor_unit,
                        focus_group=focus_group,
                        focus_tokens_before=focus_tokens_before,
                        remaining_tokens_before=remaining_tokens_before,
                        remaining_total_er=remaining_total_er,
                        remaining_total_ev=remaining_total_ev,
                        candidate_lookup=candidate_lookup,
                        candidate_details=candidate_details,
                        shadow_candidate_details=shadow_candidate_details,
                        selected_match=None,
                        structure_stats_before=structure_stats_before,
                        structure_stats_after=structure_stats_after,
                        covered_range=covered_range,
                        covered_tokens=covered_tokens,
                        transfer_ratio=transfer_ratio,
                        transfer_similarity=transfer_similarity,
                        effective_transfer_fraction=0.0,
                        transferred_er=transferred_er,
                        transferred_ev=transferred_ev,
                        created_common_structure=created_common_structure,
                        created_residual_structure=created_residual_structure,
                        created_fresh_structure=created_fresh_structure,
                        groups_before=groups_before,
                        groups_after=working_set["groups"],
                    )
                )
                break

            structure_obj = structure_store.get(best["structure_id"])
            if not structure_obj:
                break

            common_part = best["common_part"]
            covered_units = self._collect_matched_units(groups_before, common_part)
            if not covered_units:
                break

            covered_tokens = [unit.get("token", "") for unit in covered_units if unit.get("token")]
            covered_range = list(common_part.get("incoming_range", [0, 0]))
            transfer_similarity = round(max(0.0, float(best.get("similarity_score", 0.0))), 8)
            effective_transfer_fraction = self._effective_transfer_fraction(transfer_ratio, transfer_similarity)
            transferred_er = round(sum(float(unit.get("er", 0.0)) for unit in covered_units) * effective_transfer_fraction, 8)
            transferred_ev = round(sum(float(unit.get("ev", 0.0)) for unit in covered_units) * effective_transfer_fraction, 8)
            last_round_consumed_total = float(max(0.0, transferred_er + transferred_ev))
            last_round_remaining_total = float(max(0.0, remaining_total_er + remaining_total_ev))
            cumulative_transferred_total = round(float(cumulative_transferred_total + last_round_consumed_total), 8)
            last_round_progress_ratio = (
                float(last_round_consumed_total) / float(max(1e-9, last_round_remaining_total))
                if last_round_remaining_total > 0.0
                else 0.0
            )

            effective_match_now_ms = int(self._runtime_match_now_ms) if self._runtime_match_now_ms is not None else int(time.time() * 1000)
            structure_stats_before = self._capture_structure_stats(structure_obj)
            matched_structure_id = structure_obj.get("id", "")
            if matched_structure_id:
                matched_structure_ids.append(matched_structure_id)
            self._weight.mark_structure_match(
                structure_obj,
                match_score=best.get("match_score", 0.0),
                reality_support=transferred_er,
                virtual_support=transferred_ev,
                now_ms=effective_match_now_ms,
            )
            structure_store.update_structure(structure_obj)
            self._mark_chain_entries(
                best=best,
                structure_store=structure_store,
                transferred_er=transferred_er,
                transferred_ev=transferred_ev,
            )
            structure_stats_after = self._capture_structure_stats(structure_obj)
            runtime_projection_structures.append(
                {
                    "structure_id": matched_structure_id,
                    "display_text": structure_obj.get("structure", {}).get("display_text", matched_structure_id),
                    "er": transferred_er,
                    "ev": transferred_ev,
                    "reason": "matched_structure",
                    "match_mode": best.get("match_mode", "candidate_match"),
                }
            )

            residual_store_result = None
            if enable_new_structure_creation:
                residual_store_result = self._store_residual_context_for_match(
                    owner_structure_id=matched_structure_id,
                    current_groups=groups_before,
                    current_profile=remaining_profile,
                    covered_units=covered_units,
                    matched_structure=structure_obj,
                    structure_store=structure_store,
                    pointer_index=pointer_index,
                    cut_engine=cut_engine,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    source_packet_id=stimulus_packet.get("id", ""),
                    round_index=round_index,
                    min_common_length=min_common_length,
                    episodic_memory_id=episodic_memory_id,
                )
            if residual_store_result:
                written_index_count += int(residual_store_result.get("written_index_count", 0))
                cut_count += int(residual_store_result.get("cut_count", 0))
                # Propagate newly-created structures from residual normalization into the run summary.
                # 把“残差归一化/共同结构切割”过程中创建的新结构回填到 stimulus-level 的 new_structure_ids，
                # 否则前端/摘要会出现“新建结构=0，但逐轮日志里却出现新建共同结构”的误导。
                for sid in list(residual_store_result.get("new_structure_ids", []) or []):
                    sid = str(sid or "").strip()
                    if sid:
                        new_structure_ids.append(sid)
                        new_obj = structure_store.get(sid)
                        if isinstance(new_obj, dict):
                            runtime_projection_structures.append(
                                {
                                    "structure_id": sid,
                                    "display_text": new_obj.get("structure", {}).get("display_text", sid),
                                    "er": round(float(transferred_er), 8),
                                    "ev": round(float(transferred_ev), 8),
                                    "reason": "new_relation_structure",
                                    "match_mode": "residual_relation_projection",
                                }
                            )
                if not created_common_structure and residual_store_result.get("common_structure"):
                    created_common_structure = residual_store_result.get("common_structure")
                if not created_residual_structure and residual_store_result.get("residual_structure"):
                    created_residual_structure = residual_store_result.get("residual_structure")

            self._apply_common_part_consumption(
                working_set["groups"],
                covered_units=covered_units,
                consume_fraction=effective_transfer_fraction,
                prune_threshold=max(1e-6, residual_min_energy * 0.02),
            )
            debug_round_details.append(
                self._build_round_debug(
                    round_index=round_index,
                    anchor_unit=anchor_unit,
                    focus_group=focus_group,
                    focus_tokens_before=focus_tokens_before,
                    remaining_tokens_before=remaining_tokens_before,
                    remaining_total_er=remaining_total_er,
                    remaining_total_ev=remaining_total_ev,
                    candidate_lookup=candidate_lookup,
                    candidate_details=candidate_details,
                    shadow_candidate_details=shadow_candidate_details,
                    selected_match=best,
                    structure_stats_before=structure_stats_before,
                    structure_stats_after=structure_stats_after,
                    covered_range=covered_range,
                    covered_tokens=covered_tokens,
                    transfer_ratio=transfer_ratio,
                    transfer_similarity=transfer_similarity,
                    effective_transfer_fraction=effective_transfer_fraction,
                    transferred_er=transferred_er,
                    transferred_ev=transferred_ev,
                    created_common_structure=created_common_structure,
                    created_residual_structure=created_residual_structure,
                    created_fresh_structure=created_fresh_structure,
                    groups_before=groups_before,
                    groups_after=working_set["groups"],
                )
            )

        remaining_units = self._flatten_remaining_units(working_set["groups"])
        residual_packet = self._build_packet_from_working_groups(
            groups=working_set["groups"],
            trace_id=trace_id,
            tick_id=tick_id,
            source_packet_id=stimulus_packet.get("id", ""),
        )
        if enable_storage and episodic_item:
            meta = dict(episodic_item.get("meta", {}))
            ext = dict(meta.get("ext", {}))
            episodic_display_text = (
                format_semantic_sequence_groups(profile.get("sequence_groups", []), context="stimulus")
                or profile.get("semantic_display_text", "")
                or format_sequence_groups(profile.get("sequence_groups", []))
                or profile.get("display_text", "")
            )
            ext["display_text"] = episodic_display_text
            episodic_item["structure_refs"] = list(dict.fromkeys(matched_structure_ids + new_structure_ids))
            episodic_memory_material = self._build_stimulus_memory_material(
                profile=profile,
                structure_ids=episodic_item["structure_refs"],
                structure_store=structure_store,
                runtime_projection_structures=runtime_projection_structures,
            )
            ext["memory_material"] = episodic_memory_material
            meta["ext"] = ext
            episodic_item["meta"] = meta
            episodic_store.update(episodic_item)

        return {
            "code": "OK",
            "message": "Stimulus-level retrieval-storage completed",
            "round_count": round_count,
            "matched_structure_ids": list(dict.fromkeys(matched_structure_ids)),
            "new_structure_ids": list(dict.fromkeys(new_structure_ids)),
            "remaining_stimulus_sa_count": len(remaining_units),
            "episodic_memory_id": episodic_memory_id,
            "episodic_display_text": episodic_display_text,
            "episodic_memory_material": episodic_memory_material,
            "storage_summary": {
                "written_index_count": written_index_count,
                "cut_count": cut_count,
                "new_structure_count": len(list(dict.fromkeys(new_structure_ids))),
            },
            "residual_stimulus_packet": residual_packet,
            "runtime_projection_structures": runtime_projection_structures,
            "seeded_atomic_structure_ids": seeded_atomic_structure_ids,
            "fallback_used": fallback_used,
            "metrics": self._runtime_metrics_snapshot(),
            "debug": {
                "input_profile": {
                    "display_text": profile.get("display_text", ""),
                    "content_signature": profile.get("content_signature", ""),
                    # Keep the debug profile compact: store counts + a short token preview only.
                    "token_count": int(profile.get("token_count", len(profile.get("flat_tokens", []) or []))),
                    "unit_count": int(profile.get("unit_count", profile.get("token_count", len(profile.get("flat_tokens", []) or [])))),
                    "flat_tokens_preview": [
                        str(token)
                        for token in (profile.get("flat_tokens", []) or [])[:48]
                        if str(token)
                    ],
                },
                "round_details": debug_round_details,
                "early_stop": {
                    "enabled": bool(early_stop_enabled),
                    "triggered": bool(early_stop_reason),
                    "reason": str(early_stop_reason),
                    "patience_rounds": int(early_stop_patience_rounds),
                    "min_progress_ratio": float(early_stop_min_progress_ratio),
                    "high_energy_unit_threshold": float(early_stop_high_energy_unit_threshold),
                    "object_projection_dominance_enabled": bool(object_projection_dominance_early_stop_enabled),
                    "object_projection_dominance_min_rounds": int(object_projection_dominance_min_rounds),
                    "object_projection_dominance_ratio": float(object_projection_dominance_ratio),
                    "object_projection_dominance_min_remaining_energy": float(
                        object_projection_dominance_min_remaining_energy
                    ),
                    "object_projection_dominance_require_memory_id": bool(
                        object_projection_dominance_require_memory_id
                    ),
                    "object_projection_dominance_require_transfer_dominance": bool(
                        object_projection_dominance_require_transfer
                    ),
                    "object_projection_dominance_transfer_ratio": float(
                        object_projection_dominance_transfer_ratio
                    ),
                    "object_projection_transfer_guard_blocked_count": int(
                        early_stop_transfer_guard_blocked_count
                    ),
                    "object_projection_total_at_stop": float(early_stop_object_projection_total),
                    "remaining_total_at_stop": float(early_stop_remaining_total),
                    "object_projection_ratio_at_stop": float(early_stop_object_projection_ratio),
                    "transfer_total_at_stop": float(early_stop_transfer_total),
                    "transfer_ratio_at_stop": float(early_stop_transfer_ratio),
                },
            },
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

    def _set_runtime_metric(self, key: str, value: int | float) -> None:
        if not isinstance(self._runtime_cache, dict):
            return
        metrics = self._runtime_cache.setdefault("metrics", {})
        if not isinstance(metrics, dict):
            return
        metrics[key] = value

    def _runtime_metrics_snapshot(self) -> dict:
        if not isinstance(self._runtime_cache, dict):
            return {}
        metrics = self._runtime_cache.get("metrics", {})
        if not isinstance(metrics, dict):
            return {}
        return dict(metrics)

    @staticmethod
    def _runtime_projection_energy_total(rows: list[dict]) -> float:
        total = 0.0
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            try:
                er = max(0.0, float(row.get("er", 0.0) or 0.0))
                ev = max(0.0, float(row.get("ev", 0.0) or 0.0))
            except Exception:
                continue
            total += er + ev
        return round(float(total), 8)

    def _ensure_atomic_structure_databases(
        self,
        *,
        working_groups: list[dict],
        structure_store,
        pointer_index,
        cut_engine,
        trace_id: str,
        tick_id: str,
        parent_ids: list[str],
        source_packet_id: str,
    ) -> list[str]:
        created_ids: list[str] = []
        seen_tokens: set[str] = set()
        context_free_identity = bool(
            self._config.get("stimulus_atomic_preseed_context_free_identity_enabled", True)
        )
        skip_exact_lookup = self._should_direct_create_atomic_preseed(
            source_packet_id=source_packet_id,
            parent_ids=parent_ids,
        ) if not context_free_identity else False
        provenance_parent_ids = [str(item or "") for item in list(parent_ids or []) if str(item or "")]
        for group in working_groups:
            for unit in sorted(group.get("units", []), key=lambda item: int(item.get("sequence_index", 0))):
                token = str(unit.get("token", ""))
                if str(unit.get("object_type", "sa") or "sa") != "sa":
                    continue
                if bool(unit.get("is_placeholder", False)) or token.startswith("SELF["):
                    continue
                if token.startswith("st_") or token.startswith("sg_"):
                    continue
                # Safety guard: never persist polluted "display text" as atomic token structures.
                # This must only trigger on abnormal tokens and must not affect normal flows.
                if token and (("{{" in token) or ("->" in token) or (len(token) > 512)):
                    continue
                if not token or token in seen_tokens:
                    continue
                seen_tokens.add(token)
                existing = self._get_cached_atomic_structure(unit=unit, structure_store=structure_store)
                if existing is not None:
                    self._put_cached_atomic_structure(unit=unit, structure_obj=existing)
                    continue
                result = self._find_or_create_structure_from_units(
                    units=[unit],
                    structure_store=structure_store,
                    pointer_index=pointer_index,
                    cut_engine=cut_engine,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    confidence=float(self._config.get("stimulus_atomic_seed_confidence", 0.95)),
                    origin="stimulus_atomic_preseed",
                    origin_id=source_packet_id,
                    parent_ids=[] if context_free_identity else parent_ids,
                    ext={
                        "source_packet_id": source_packet_id,
                        "provenance_parent_ids": provenance_parent_ids,
                        "origin_group_index": unit.get("group_index", 0),
                        "origin_source_type": unit.get("source_type", ""),
                        "kind": "atomic_preseed",
                        "relation_type": "atomic_preseed",
                        "identity_context_free": context_free_identity,
                    },
                    skip_exact_lookup=skip_exact_lookup,
                )
                structure_obj = result.get("structure") if isinstance(result, dict) else None
                if isinstance(structure_obj, dict):
                    self._put_cached_atomic_structure(unit=unit, structure_obj=structure_obj)
                if result.get("created") and result["structure"].get("id", ""):
                    created_ids.append(result["structure"]["id"])
        return created_ids

    def _ensure_goal_b_string_structure_projections(
        self,
        *,
        working_groups: list[dict],
        structure_store,
        pointer_index,
        cut_engine,
        trace_id: str,
        tick_id: str,
        parent_ids: list[str],
        source_packet_id: str,
        runtime_projection_structures: list[dict],
    ) -> list[str]:
        if not bool(self._config.get("enable_goal_b_char_sa_string_mode", False)):
            return []
        created_or_found_ids: list[str] = []
        string_bucket_counts: dict[str, int] = {}
        context_free_identity = bool(
            self._config.get("stimulus_goal_b_string_seed_context_free_identity_enabled", True)
        )
        provenance_parent_ids = [str(item or "") for item in list(parent_ids or []) if str(item or "")]
        for group in working_groups:
            if not isinstance(group, dict):
                continue
            if not (bool(group.get("order_sensitive", False)) and str(group.get("string_unit_kind", "") or "") == "char_sequence"):
                continue
            units = [dict(unit) for unit in group.get("units", []) or [] if isinstance(unit, dict)]
            units = [
                unit
                for unit in units
                if str(unit.get("object_type", "sa") or "sa") == "sa"
                and not bool(unit.get("is_placeholder", False))
                and not str(unit.get("token", "") or "").startswith("SELF[")
                and not str(unit.get("token", "") or "").startswith("st_")
                and not str(unit.get("token", "") or "").startswith("sg_")
            ]
            if len(units) <= 1:
                continue
            profile = cut_engine.build_sequence_profile_from_groups([dict(group, units=units)])
            string_key = str(profile.get("display_text", "") or group.get("string_token_text", "") or "").strip()
            bucket_seen = int(string_bucket_counts.get(string_key, 0) or 0)
            if not self._allow_long_profile_seed(
                profile,
                soft_max_units_key="goal_b_string_seed_soft_max_units",
                min_avg_energy_key="goal_b_string_seed_min_avg_unit_energy_for_long",
                require_single_source_for_long=bool(self._config.get("goal_b_string_seed_require_single_source_for_long", True)),
            ):
                continue
            result = self._find_or_create_structure_from_profile(
                profile=profile,
                structure_store=structure_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
                trace_id=trace_id,
                tick_id=tick_id,
                confidence=float(self._config.get("stimulus_focus_seed_confidence", 0.9)),
                origin="stimulus_goal_b_string_seed",
                origin_id=source_packet_id,
                parent_ids=[] if context_free_identity else parent_ids,
                ext={
                    "source_packet_id": source_packet_id,
                    "provenance_parent_ids": provenance_parent_ids,
                    "origin_group_index": group.get("group_index", 0),
                    "origin_source_type": group.get("source_type", ""),
                    "kind": "goal_b_string_relation_seed",
                    "relation_type": "goal_b_string_relation",
                    "identity_context_free": context_free_identity,
                },
                require_context_free=context_free_identity,
            )
            structure_obj = result.get("structure") if isinstance(result, dict) else None
            if not isinstance(structure_obj, dict):
                continue
            sid = str(structure_obj.get("id", "") or "")
            if not sid:
                continue
            created_or_found_ids.append(sid)
            total_er = round(sum(float(unit.get("er", 0.0) or 0.0) for unit in units), 8)
            total_ev = round(sum(float(unit.get("ev", 0.0) or 0.0) for unit in units), 8)
            if bucket_seen > 0:
                crowd_ratio = 1.0 / float(1 + bucket_seen)
                total_er = round(total_er * crowd_ratio, 8)
                total_ev = round(total_ev * crowd_ratio, 8)
            runtime_projection_structures.append(
                {
                    "structure_id": sid,
                    "display_text": structure_obj.get("structure", {}).get("display_text", profile.get("display_text", sid)),
                    "er": total_er,
                    "ev": total_ev,
                    "reason": "goal_b_string_relation_seed",
                    "match_mode": "goal_b_string_relation_seed",
                    "same_tick_bucket_rank": int(bucket_seen + 1),
                }
            )
            string_bucket_counts[string_key] = bucket_seen + 1
        return list(dict.fromkeys(created_or_found_ids))

    def _build_working_set(self, stimulus_packet: dict, *, cut_engine) -> dict:
        sa_index = {
            item.get("id", ""): item
            for item in stimulus_packet.get("sa_items", [])
            if isinstance(item, dict) and item.get("id")
        }
        csa_index = {
            item.get("id", ""): item
            for item in stimulus_packet.get("csa_items", [])
            if isinstance(item, dict) and item.get("id")
        }

        groups = []
        for order_index, group in enumerate(stimulus_packet.get("grouped_sa_sequences", [])):
            source_type = group.get("source_type", "")
            origin_frame_id = group.get("origin_frame_id", "")
            source_group_index = int(group.get("source_group_index", group.get("group_index", order_index)))
            csa_members = [csa_index.get(csa_id) for csa_id in group.get("csa_ids", []) if csa_index.get(csa_id)]
            csa_members.sort(key=lambda item: item.get("ext", {}).get("packet_context", {}).get("sequence_index", 0))

            referenced_sa_ids = [str(sa_id) for sa_id in group.get("sa_ids", []) if str(sa_id)]
            for csa in csa_members:
                for member_id in csa.get("member_sa_ids", []):
                    member_text = str(member_id)
                    if member_text:
                        referenced_sa_ids.append(member_text)
            ordered_sa_ids = self._dedupe_preserve_order(referenced_sa_ids)
            sa_members = [sa_index.get(sa_id) for sa_id in ordered_sa_ids if sa_index.get(sa_id)]
            sa_members.sort(key=lambda item: item.get("ext", {}).get("packet_context", {}).get("sequence_index", 0))

            units = []
            for sa in sa_members:
                unit = self._make_unit_from_object(
                    obj=sa,
                    object_type="sa",
                    group_index=order_index,
                    source_group_index=source_group_index,
                    source_type=source_type,
                    origin_frame_id=origin_frame_id,
                )
                if unit:
                    units.append(unit)

            units_by_id = {str(unit.get("unit_id", "")): unit for unit in units if str(unit.get("unit_id", ""))}
            csa_bundles = []
            for csa in csa_members:
                anchor_unit_id = str(csa.get("anchor_sa_id", ""))
                member_ids = [
                    str(member_id)
                    for member_id in csa.get("member_sa_ids", [])
                    if str(member_id) in units_by_id
                ]
                if not anchor_unit_id or anchor_unit_id not in units_by_id or len(member_ids) < 2:
                    continue
                anchor_signature = str(units_by_id[anchor_unit_id].get("unit_signature", ""))
                member_signatures = [
                    str(units_by_id[member_id].get("unit_signature", ""))
                    for member_id in member_ids
                    if str(units_by_id[member_id].get("unit_signature", ""))
                ]
                csa_bundles.append(
                    {
                        "bundle_id": str(csa.get("id", "")),
                        "anchor_unit_id": anchor_unit_id,
                        "member_unit_ids": member_ids,
                        "anchor_unit_signature": anchor_signature,
                        "member_unit_signatures": member_signatures,
                        "bundle_signature": f"CSA[{anchor_signature}=>{'|'.join(sorted(member_signatures[1:]))}]",
                    }
                )

            if not units:
                continue

            groups.append(
                {
                    "group_index": order_index,
                    "source_group_index": source_group_index,
                    "source_type": source_type,
                    "origin_frame_id": origin_frame_id,
                    "order_sensitive": bool(group.get("order_sensitive", False)),
                    "string_unit_kind": str(group.get("string_unit_kind", "") or ""),
                    "string_token_text": str(group.get("string_token_text", "") or ""),
                    "units": units,
                    "csa_bundles": csa_bundles,
                }
            )

        # 统一交给 cut engine 做一次规范化，确保单位字段、CSA 绑定和时序分组
        # 在刺激级的所有后续流程里都保持一致。
        profile = cut_engine.build_sequence_profile_from_groups(groups)
        return {"groups": list(profile.get("sequence_groups", []))}

    @staticmethod
    def _atomic_structure_cache_key(unit: dict) -> str:
        if not isinstance(unit, dict):
            return ""
        return str(unit.get("unit_signature", "") or unit.get("token", "") or "").strip()

    def _should_direct_create_atomic_preseed(self, *, source_packet_id: str, parent_ids: list[str]) -> bool:
        if not bool(self._config.get("stimulus_atomic_preseed_unique_context_direct_create_enabled", True)):
            return False
        if not str(source_packet_id or "").startswith("spkt_merge_"):
            return False
        parent_packet_ids = [str(item or "") for item in list(parent_ids or [])]
        return any(item.startswith(("spkt_", "ispkt_")) for item in parent_packet_ids if item)

    def _get_cached_atomic_structure(self, *, unit: dict, structure_store) -> dict | None:
        cache = self._runtime_cache.get("atomic_structure_ids", {}) if isinstance(self._runtime_cache, dict) else {}
        if not isinstance(cache, dict):
            return None
        cache_key = self._atomic_structure_cache_key(unit)
        if not cache_key:
            return None
        structure_id = str(cache.get(cache_key, "") or "")
        if not structure_id and bool(self._config.get("stimulus_atomic_structure_cross_tick_cache_enabled", True)):
            structure_id = str(self._atomic_structure_id_cache.get(cache_key, "") or "")
        if not structure_id:
            return None
        structure_obj = structure_store.get(structure_id)
        if structure_obj is None:
            cache.pop(cache_key, None)
            self._atomic_structure_id_cache.pop(cache_key, None)
            return None
        if cache_key not in cache:
            cache[cache_key] = structure_id
        return structure_obj

    def _put_cached_atomic_structure(self, *, unit: dict, structure_obj: dict) -> None:
        if not isinstance(self._runtime_cache, dict):
            return
        cache = self._runtime_cache.setdefault("atomic_structure_ids", {})
        if not isinstance(cache, dict):
            return
        cache_key = self._atomic_structure_cache_key(unit)
        structure_id = str((structure_obj or {}).get("id", "") or "")
        if not cache_key or not structure_id:
            return
        cache[cache_key] = structure_id
        if bool(self._config.get("stimulus_atomic_structure_cross_tick_cache_enabled", True)):
            max_entries = int(self._config.get("stimulus_atomic_structure_cross_tick_cache_max_entries", 2048) or 2048)
            if max_entries > 0:
                if cache_key in self._atomic_structure_id_cache:
                    self._atomic_structure_id_cache.pop(cache_key, None)
                while len(self._atomic_structure_id_cache) >= max_entries:
                    try:
                        self._atomic_structure_id_cache.pop(next(iter(self._atomic_structure_id_cache)))
                    except StopIteration:
                        break
                self._atomic_structure_id_cache[cache_key] = structure_id

    def _make_unit_from_object(
        self,
        *,
        obj: dict,
        object_type: str,
        group_index: int,
        source_group_index: int,
        source_type: str,
        origin_frame_id: str,
    ) -> dict | None:
        token = str(obj.get("content", {}).get("display") or obj.get("content", {}).get("raw") or obj.get("id", ""))
        if not token:
            return None
        sequence_index = int(
            obj.get("ext", {}).get("packet_context", {}).get("sequence_index", obj.get("stimulus", {}).get("global_sequence_index", 0))
        )
        er = round(float(obj.get("energy", {}).get("er", 0.0)), 8)
        ev = round(float(obj.get("energy", {}).get("ev", 0.0)), 8)
        role = str(obj.get("stimulus", {}).get("role", "feature") or "feature")
        is_placeholder = token.startswith("SELF[")
        unit_signature_prefix = "P" if is_placeholder else ("A" if role == "attribute" else "F")
        attribute_name = str(obj.get("content", {}).get("attribute_name", ""))
        attribute_value = obj.get("content", {}).get("attribute_value")
        parent_ids = list((obj.get("source", {}) or {}).get("parent_ids", []))
        context = extract_context_metadata(obj)
        return {
            "unit_id": obj.get("id", ""),
            "object_type": object_type,
            "token": token,
            "display_text": token,
            "unit_role": "placeholder" if is_placeholder else role,
            "unit_signature": f"{unit_signature_prefix}:{token}",
            "sequence_index": sequence_index,
            "group_index": group_index,
            "source_group_index": source_group_index,
            "source_type": source_type,
            "origin_frame_id": origin_frame_id,
            "er": er,
            "ev": ev,
            "total_energy": round(er + ev, 8),
            "is_punctuation": self._is_punctuation_token(token),
            "display_visible": role != "attribute" or is_placeholder,
            "is_placeholder": is_placeholder,
            "attribute_name": attribute_name,
            "attribute_value": attribute_value,
            "context_ref_object_id": str(context.get("context_ref_object_id", "") or ""),
            "context_ref_object_type": str(context.get("context_ref_object_type", "") or ""),
            "context_owner_structure_id": str(context.get("context_owner_structure_id", "") or ""),
            "context_path_ids": list(context.get("context_path_ids", []) or []),
            "bundle_id": "",
            "bundle_anchor_unit_id": str(parent_ids[0]) if role == "attribute" and parent_ids else "",
            "bundle_anchor_signature": "",
            "bundle_signature": "",
            "bundle_member_unit_ids": [],
            "bundle_member_signatures": [],
        }

    def _build_packet_from_working_groups(
        self,
        *,
        groups: list[dict],
        trace_id: str,
        tick_id: str,
        source_packet_id: str,
    ) -> dict:
        now_ms = int(time.time() * 1000)
        sa_items = []
        csa_items = []
        grouped_sequences = []
        total_er = 0.0
        total_ev = 0.0

        for group_index, group in enumerate(groups):
            units = sorted(group.get("units", []), key=lambda item: int(item.get("sequence_index", 0)))
            sa_ids = []
            group_csa_ids = []
            seen_bundle_ids = set()
            for seq_index, unit in enumerate(units):
                token = str(unit.get("token", ""))
                unit_id = str(unit.get("unit_id", ""))
                if not token or not unit_id:
                    continue
                er = round(max(0.0, float(unit.get("er", 0.0))), 8)
                ev = round(max(0.0, float(unit.get("ev", 0.0))), 8)
                if er + ev <= 0.0:
                    continue
                sa_ids.append(unit_id)
                total_er += er
                total_ev += ev
                sa_items.append(
                    {
                        "id": unit_id,
                        "object_type": "sa",
                        "content": {"raw": token, "display": token, "normalized": token, "value_type": "discrete"},
                        "stimulus": {"role": unit.get("unit_role", "feature"), "modality": unit.get("source_type", "text")},
                        "energy": {"er": er, "ev": ev},
                        "source": {
                            "module": "hdb",
                            "interface": "run_stimulus_level_retrieval_storage",
                            "origin": group.get("source_type", ""),
                            "origin_id": group.get("origin_frame_id", ""),
                            "parent_ids": [str(unit.get("bundle_anchor_unit_id", ""))] if str(unit.get("unit_role", "")) == "attribute" and str(unit.get("bundle_anchor_unit_id", "")) else [],
                        },
                        "ext": {
                            "packet_context": {
                                "group_index": group_index,
                                "source_group_index": int(group.get("source_group_index", group_index)),
                                "origin_frame_id": group.get("origin_frame_id", ""),
                                "source_type": group.get("source_type", ""),
                                "sequence_index": seq_index,
                                "order_sensitive": bool(group.get("order_sensitive", False)),
                                "string_unit_kind": str(group.get("string_unit_kind", "") or ""),
                                "string_token_text": str(group.get("string_token_text", "") or ""),
                            }
                        },
                        "created_at": now_ms,
                        "updated_at": now_ms,
                    }
                )
                bundle_id = str(unit.get("bundle_id", ""))
                member_ids = [str(member_id) for member_id in unit.get("bundle_member_unit_ids", []) if str(member_id)]
                if bundle_id and len(member_ids) >= 2 and bundle_id not in seen_bundle_ids:
                    seen_bundle_ids.add(bundle_id)
                    anchor_id = str(unit.get("bundle_anchor_unit_id", ""))
                    if anchor_id:
                        member_id_set = set(member_ids)
                        csa_items.append(
                            {
                                "id": bundle_id,
                                "object_type": "csa",
                                "anchor_sa_id": anchor_id,
                                "member_sa_ids": member_ids,
                                "content": {"display": f"CSA[{anchor_id}]", "raw": anchor_id},
                                "energy": {
                                    "er": round(sum(max(0.0, float(item.get("er", 0.0))) for item in units if str(item.get("unit_id", "")) in member_id_set), 8),
                                    "ev": round(sum(max(0.0, float(item.get("ev", 0.0))) for item in units if str(item.get("unit_id", "")) in member_id_set), 8),
                                },
                                "ext": {
                                    "packet_context": {
                                        "group_index": group_index,
                                        "source_group_index": int(group.get("source_group_index", group_index)),
                                        "origin_frame_id": group.get("origin_frame_id", ""),
                                        "source_type": group.get("source_type", ""),
                                        "sequence_index": len(group_csa_ids),
                                        "order_sensitive": bool(group.get("order_sensitive", False)),
                                        "string_unit_kind": str(group.get("string_unit_kind", "") or ""),
                                        "string_token_text": str(group.get("string_token_text", "") or ""),
                                    }
                                },
                                "created_at": now_ms,
                                "updated_at": now_ms,
                            }
                        )
                        group_csa_ids.append(bundle_id)
            if not sa_ids:
                continue
            grouped_sequences.append(
                {
                    "group_index": group_index,
                    "source_type": group.get("source_type", ""),
                    "origin_frame_id": group.get("origin_frame_id", ""),
                    "sa_ids": sa_ids,
                    "csa_ids": group_csa_ids,
                    "source_group_index": int(group.get("source_group_index", group_index)),
                    "order_sensitive": bool(group.get("order_sensitive", False)),
                    "string_unit_kind": str(group.get("string_unit_kind", "") or ""),
                    "string_token_text": str(group.get("string_token_text", "") or ""),
                }
            )

        return {
            "id": f"spkt_residual_{int(time.time() * 1000)}",
            "object_type": "stimulus_packet",
            "sub_type": "stimulus_residual_packet",
            "packet_type": "residual_after_stimulus",
            "sa_items": sa_items,
            "csa_items": csa_items,
            "grouped_sa_sequences": grouped_sequences,
            "energy_summary": {
                "total_er": round(total_er, 8),
                "total_ev": round(total_ev, 8),
                "current_total_er": round(total_er, 8),
                "current_total_ev": round(total_ev, 8),
            },
            "trace_id": trace_id,
            "tick_id": tick_id,
            "source": {
                "module": "hdb",
                "interface": "run_stimulus_level_retrieval_storage",
                "origin": "residual_after_stimulus",
                "origin_id": source_packet_id,
                "parent_ids": [source_packet_id] if source_packet_id else [],
            },
            "created_at": now_ms,
            "updated_at": now_ms,
        }

    def _build_round_debug(
        self,
        *,
        round_index: int,
        anchor_unit: dict,
        focus_group: dict,
        focus_tokens_before: list[str],
        remaining_tokens_before: list[str],
        remaining_total_er: float,
        remaining_total_ev: float,
        candidate_lookup: dict,
        candidate_details: list[dict],
        shadow_candidate_details: list[dict],
        selected_match: dict | None,
        structure_stats_before: dict | None,
        structure_stats_after: dict | None,
        covered_range: list[int],
        covered_tokens: list[str],
        transfer_ratio: float,
        transfer_similarity: float,
        effective_transfer_fraction: float,
        transferred_er: float,
        transferred_ev: float,
        created_common_structure: dict | None,
        created_residual_structure: dict | None,
        created_fresh_structure: dict | None,
        groups_before: list[dict],
        groups_after: list[dict],
    ) -> dict:
        # Debug payload is intentionally summary-first.
        # Keeping full sequence groups for both "before/after" states makes the per-tick report
        # explode in size during long runs and hurts UI responsiveness.
        selected_summary = None
        if isinstance(selected_match, dict):
            cp = selected_match.get("common_part", {})
            selected_summary = {
                "structure_id": selected_match.get("structure_id", ""),
                "display_text": selected_match.get("display_text", ""),
                "match_mode": selected_match.get("match_mode", ""),
                "match_score": selected_match.get("match_score", 0.0),
                "match_score_legacy": selected_match.get("match_score_legacy"),
                "match_score_v2": selected_match.get("match_score_v2"),
                "competition_score": selected_match.get("competition_score", 0.0),
                "competition_score_legacy": selected_match.get("competition_score_legacy"),
                "competition_score_v2": selected_match.get("competition_score_v2"),
                "coverage_ratio": selected_match.get("coverage_ratio", 0.0),
                "structure_match_ratio": selected_match.get("structure_match_ratio", 0.0),
                "stimulus_match_ratio": selected_match.get("stimulus_match_ratio", 0.0),
                "exact_match": bool(selected_match.get("exact_match", False)),
                "full_structure_included": bool(selected_match.get("full_structure_included", False)),
                "incoming_range": list(selected_match.get("incoming_range", [0, 0]) or [0, 0]),
                "existing_length": selected_match.get("existing_length", 0),
                "incoming_length": selected_match.get("incoming_length", 0),
                "matched_existing_length": selected_match.get("matched_existing_length", 0),
                "matched_incoming_length": selected_match.get("matched_incoming_length", 0),
                "v2_base_score": selected_match.get("v2_base_score"),
                "v2_numeric_score": selected_match.get("v2_numeric_score"),
                "v2_order_alignment_score": selected_match.get("v2_order_alignment_score"),
                "v2_attribute_anchor_score": selected_match.get("v2_attribute_anchor_score"),
                "v2_context_support_score": selected_match.get("v2_context_support_score"),
                "v2_energy_profile_score": selected_match.get("v2_energy_profile_score"),
                "v2_structure_inclusion_score": selected_match.get("v2_structure_inclusion_score"),
                "v2_threshold_margin": selected_match.get("v2_threshold_margin"),
                "v2_available_component_count": selected_match.get("v2_available_component_count"),
                "common_part": {
                    "common_length": cp.get("common_length", 0) if isinstance(cp, dict) else 0,
                    "residual_existing_signature": cp.get("residual_existing_signature", "") if isinstance(cp, dict) else "",
                    "residual_incoming_signature": cp.get("residual_incoming_signature", "") if isinstance(cp, dict) else "",
                },
            }

        remaining_total_er_after = 0.0
        remaining_total_ev_after = 0.0
        for group in groups_after or []:
            for unit in group.get("units", []) or []:
                remaining_total_er_after += float(unit.get("er", 0.0))
                remaining_total_ev_after += float(unit.get("ev", 0.0))
        return {
            "round_index": round_index,
            "anchor_unit": anchor_unit,
            "focus_group_index": focus_group.get("group_index", 0),
            "focus_group_source_type": focus_group.get("source_type", ""),
            "focus_group_text_before": self._format_runtime_group_text(focus_group),
            "remaining_tokens_before": remaining_tokens_before,
            "remaining_grouped_text_before": self._debug_grouped_text(
                groups_before,
                round_index=round_index,
                phase="before",
            ),
            "remaining_total_er_before": remaining_total_er,
            "remaining_total_ev_before": remaining_total_ev,
            "candidate_lookup_source": candidate_lookup.get("candidate_source", "unknown"),
            "candidate_signature_hits": candidate_lookup.get("signature_hits", []),
            "chain_steps": list(candidate_lookup.get("chain_steps", [])),
            "candidate_details": self._limit_debug_candidate_details(
                candidate_details,
                config_key="stimulus_round_debug_candidate_detail_limit",
                default_limit=16,
            ),
            "shadow_candidate_details": self._limit_debug_candidate_details(
                shadow_candidate_details,
                config_key="stimulus_round_debug_shadow_candidate_detail_limit",
                default_limit=8,
            ),
            "selected_match": selected_summary,
            "structure_stats_before": structure_stats_before,
            "structure_stats_after": structure_stats_after,
            "covered_range": covered_range,
            "covered_tokens": covered_tokens,
            "transfer_ratio": transfer_ratio,
            "transfer_similarity": transfer_similarity,
            "effective_transfer_fraction": effective_transfer_fraction,
            "transferred_er": transferred_er,
            "transferred_ev": transferred_ev,
            "created_common_structure": created_common_structure,
            "created_residual_structure": created_residual_structure,
            "created_fresh_structure": created_fresh_structure,
            "remaining_tokens_after": (
                self._collect_remaining_tokens(groups_after)
                if self._emit_full_round_debug(round_index)
                else self._collect_remaining_tokens_preview(groups_after)
            ),
            "remaining_grouped_text_after": self._debug_grouped_text(
                groups_after,
                round_index=round_index,
                phase="after",
            ),
            "remaining_total_er_after": round(float(remaining_total_er_after), 8),
            "remaining_total_ev_after": round(float(remaining_total_ev_after), 8),
        }

    def _debug_grouped_text(self, groups: list[dict], *, round_index: int, phase: str) -> str:
        if self._emit_full_round_debug(round_index):
            return self._format_runtime_group_texts(groups)
        full_rounds = self._round_debug_full_text_rounds()
        unit_count = 0
        token_preview: list[str] = []
        for group in groups or []:
            if not isinstance(group, dict):
                continue
            for unit in group.get("units", []) or []:
                if not isinstance(unit, dict):
                    continue
                unit_count += 1
                if len(token_preview) < self._round_debug_token_preview_limit():
                    token = str(unit.get("token", "") or "").strip()
                    if token:
                        token_preview.append(token)
        preview = " ".join(token_preview)
        suffix = f"; preview={preview}" if preview else ""
        return (
            f"<{phase} grouped text omitted after debug round {full_rounds}; "
            f"groups={len(groups or [])}; units={unit_count}{suffix}>"
        )

    def _emit_full_round_debug(self, round_index: int) -> bool:
        full_rounds = self._round_debug_full_text_rounds()
        return full_rounds <= 0 or int(round_index) <= max(0, full_rounds)

    def _round_debug_full_text_rounds(self) -> int:
        try:
            return int(self._config.get("stimulus_round_debug_full_text_rounds", 8) or 0)
        except Exception:
            return 8

    def _round_debug_token_preview_limit(self) -> int:
        try:
            return max(0, int(self._config.get("stimulus_round_debug_token_preview_limit", 24) or 0))
        except Exception:
            return 24

    def _limit_debug_candidate_details(self, details: list[dict], *, config_key: str, default_limit: int) -> list[dict]:
        try:
            limit = int(self._config.get(config_key, default_limit) or 0)
        except Exception:
            limit = int(default_limit)
        if limit <= 0 or len(details) <= limit:
            return details
        trimmed = list(details[:limit])
        trimmed.append(
            {
                "omitted_debug_candidate_detail_count": int(max(0, len(details) - limit)),
                "debug_limit": int(limit),
            }
        )
        return trimmed

    def _resolve_anchor_chain_match(
        self,
        *,
        anchor_unit: dict,
        focus_window_units: list[dict],
        incoming_profile: dict,
        competition_units: list[dict] | None,
        structure_store,
        pointer_index,
        cut_engine,
        trace_id: str,
        tick_id: str,
        source_packet_id: str,
        parent_ids: list[str],
        round_index: int,
    ) -> tuple[dict, dict | None, list[dict], list[dict]]:
        anchor_best, anchor_detail, _ = self._get_or_create_atomic_structure_for_unit(
            unit=anchor_unit,
            focus_units=focus_window_units,
            competition_units=competition_units,
            structure_store=structure_store,
            pointer_index=pointer_index,
            cut_engine=cut_engine,
            trace_id=trace_id,
            tick_id=tick_id,
            parent_ids=parent_ids,
            source_packet_id=source_packet_id,
            round_index=round_index,
        )
        candidate_details = []
        shadow_candidate_details = []
        if anchor_detail:
            candidate_details = self._upsert_candidate_detail(candidate_details, anchor_detail)
        if not anchor_best:
            candidate_details = self._sort_candidate_details(candidate_details)
            return {
                "candidate_source": "anchor_atomic_chain",
                "signature_hits": [{"signature": str(anchor_unit.get("token", "")), "candidate_count": 0}],
                "used_recent_fallback": False,
            }, None, candidate_details, shadow_candidate_details

        best = dict(anchor_best)
        best["path_entries"] = []
        chain_steps = []
        seen_ids = {best.get("structure_id", "")}
        max_chain_depth = max(1, int(incoming_profile.get("token_count", len(incoming_profile.get("flat_tokens", [])))))

        for depth in range(1, max_chain_depth + 1):
            shadow_details, promoted_shadow_candidates, promoted_entry_lookup = self._build_local_shadow_raw_residual_candidate_details(
                owner_match=best,
                incoming_profile=incoming_profile,
                competition_units=competition_units,
                structure_store=structure_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
                anchor_token=str(anchor_unit.get("token", "")),
                min_existing_length=int(best.get("existing_length", 0)) + 1,
                chain_depth=depth,
                parent_match=best,
                trace_id=trace_id,
                tick_id=tick_id,
            )
            for detail in shadow_details:
                shadow_candidate_details = self._upsert_candidate_detail(shadow_candidate_details, detail)
            local_lookup = self._collect_local_child_candidates(
                owner_match=best,
                structure_store=structure_store,
                seen_structure_ids=seen_ids,
                tick_id=tick_id,
            )
            if promoted_shadow_candidates:
                local_candidates = list(local_lookup.get("candidates", []) or [])
                local_entry_lookup = dict(local_lookup.get("entry_lookup", {}) or {})
                for candidate in promoted_shadow_candidates:
                    candidate_id = str(candidate.get("id", "") or "").strip()
                    if not candidate_id or candidate_id in seen_ids:
                        continue
                    seen_ids.add(candidate_id)
                    local_candidates.append(candidate)
                    promoted_entry = promoted_entry_lookup.get(candidate_id)
                    if isinstance(promoted_entry, dict):
                        local_entry_lookup[candidate_id] = promoted_entry
                local_lookup = {
                    "candidates": local_candidates,
                    "entry_lookup": local_entry_lookup,
                }
            chain_steps.append(
                {
                    "owner_structure_id": best.get("structure_id", ""),
                    "owner_display_text": best.get("display_text", ""),
                    "candidate_count": len(local_lookup.get("candidates", [])),
                    "shadow_candidate_count": len(shadow_details),
                }
            )
            if not local_lookup.get("candidates"):
                break
            local_best, local_details = self._best_structure_match(
                incoming_profile=incoming_profile,
                competition_units=competition_units,
                candidates=local_lookup.get("candidates", []),
                structure_store=structure_store,
                cut_engine=cut_engine,
                anchor_token=str(anchor_unit.get("token", "")),
                entry_lookup=local_lookup.get("entry_lookup", {}),
                min_existing_length=int(best.get("existing_length", 0)) + 1,
                chain_depth=depth,
                parent_match=best,
            )
            for detail in local_details:
                candidate_details = self._upsert_candidate_detail(candidate_details, detail)
            if not local_best:
                break
            best = local_best
            seen_ids.add(best.get("structure_id", ""))

        candidate_details = self._sort_candidate_details(candidate_details)
        shadow_candidate_details = self._sort_candidate_details(shadow_candidate_details)

        return {
            "candidate_source": "anchor_atomic_chain",
            "signature_hits": [
                {"signature": str(anchor_unit.get("token", "")), "candidate_count": 1 if best.get("structure_id", "") else 0},
                *[
                    {
                        "signature": f"local:{step.get('owner_display_text', '') or step.get('owner_structure_id', '')}",
                        "candidate_count": int(step.get("candidate_count", 0)),
                    }
                    for step in chain_steps
                ],
            ],
            "used_recent_fallback": False,
            "chain_steps": chain_steps,
        }, best, candidate_details, shadow_candidate_details

    def _build_local_shadow_raw_residual_candidate_details(
        self,
        *,
        owner_match: dict,
        incoming_profile: dict,
        competition_units: list[dict] | None,
        structure_store,
        pointer_index,
        cut_engine,
        anchor_token: str,
        min_existing_length: int = 1,
        chain_depth: int = 0,
        parent_match: dict | None = None,
        trace_id: str = "",
        tick_id: str = "",
    ) -> tuple[list[dict], list[dict], dict[str, dict]]:
        if not bool(self._config.get("stimulus_residual_memory_shadow_v2_enabled", True)):
            return [], [], {}
        structure_db = self._open_structure_db_from_match(owner_match, structure_store)
        if not structure_db:
            return [], [], {}

        owner_structure_id = str(structure_db.get("owner_structure_id", "") or owner_match.get("structure_id", "") or "")
        promotion_enabled = bool(self._config.get("stimulus_residual_memory_promotion_enabled", True))
        if (
            not promotion_enabled
            and bool(self._config.get("stimulus_residual_memory_shadow_skip_when_promotion_disabled_enabled", True))
        ):
            raw_entries = [
                entry
                for entry in structure_db.get("diff_table", [])
                if isinstance(entry, dict) and entry.get("entry_type") == "raw_residual"
            ]
            raw_shadow_count = len(raw_entries)
            canonical_complete = all(
                str(entry.get("canonical_content_signature", "") or "")
                and str(entry.get("canonical_display_text", "") or "")
                and bool(entry.get("canonical_sequence_groups", []))
                for entry in raw_entries
            )
            if canonical_complete:
                if raw_shadow_count > 0:
                    self._increment_runtime_metric("shadow_raw_residual_candidate_count", raw_shadow_count)
                    self._increment_runtime_metric("shadow_raw_residual_skipped_count", raw_shadow_count)
                return [], [], {}

        owner_profile = {}
        if owner_structure_id:
            owner_structure = structure_store.get(owner_structure_id)
            if isinstance(owner_structure, dict):
                owner_profile = self._build_structure_profile(
                    structure_obj=owner_structure,
                    structure_store=structure_store,
                    cut_engine=cut_engine,
                )
        try:
            max_shadow_candidates = int(self._config.get("stimulus_shadow_raw_residual_candidate_max_per_owner", 32) or 0)
        except Exception:
            max_shadow_candidates = 32
        max_shadow_candidates = max(0, int(max_shadow_candidates))
        raw_shadow_count, raw_items = self._list_owner_shadow_raw_residual_items(
            owner_db=structure_db,
            structure_store=structure_store,
            cut_engine=cut_engine,
            max_candidates=max_shadow_candidates,
            tick_id=tick_id,
        )
        if not raw_items:
            return [], [], {}
        self._increment_runtime_metric("shadow_raw_residual_candidate_count", raw_shadow_count)
        self._increment_runtime_metric("shadow_raw_residual_candidate_pruned_count", max(0, raw_shadow_count - len(raw_items)))

        incoming_groups = list(incoming_profile.get("sequence_groups", []))
        incoming_length = int(incoming_profile.get("unit_count", incoming_profile.get("token_count", len(incoming_profile.get("flat_tokens", [])))))
        incoming_all_units = list(incoming_profile.get("all_units", []))
        if not incoming_all_units:
            incoming_all_units = [
                unit
                for group in incoming_groups
                for unit in group.get("units", [])
                if isinstance(unit, dict)
            ]
        competition_all_units = [
            unit
            for unit in (competition_units or incoming_all_units)
            if isinstance(unit, dict)
        ]
        competition_length = sum(1 for unit in competition_all_units if str(unit.get("token", "")))
        details: list[dict] = []
        promoted_candidates: list[dict] = []
        promoted_entry_lookup: dict[str, dict] = {}
        promotion_require_time_signal = bool(
            self._config.get("stimulus_residual_memory_promotion_require_time_signal", True)
        )
        try:
            promotion_min_v2_score = float(
                self._config.get(
                    "stimulus_residual_memory_promotion_min_v2_score",
                    max(0.28, float(self._config.get("match_scoring_v2_min_score", 0.18) or 0.18)),
                )
                or 0.0
            )
        except Exception:
            promotion_min_v2_score = max(0.28, float(self._config.get("match_scoring_v2_min_score", 0.18) or 0.18))
        try:
            promotion_max_candidates = int(
                self._config.get("stimulus_residual_memory_promotion_max_candidates_per_owner", 1) or 1
            )
        except Exception:
            promotion_max_candidates = 1
        promotion_max_candidates = max(0, min(8, promotion_max_candidates))

        for item in raw_items:
            entry = item.get("entry_ref", {})
            if not isinstance(entry, dict):
                continue
            existing_profile = item.get("canonical_profile", {})
            existing_groups = list(existing_profile.get("sequence_groups", []))
            if not existing_groups:
                continue
            existing_length = int(existing_profile.get("unit_count", existing_profile.get("token_count", len(existing_profile.get("flat_tokens", [])))))
            entry_runtime_weight = float(item.get("entry_runtime_weight", 0.0) or 0.0)
            runtime_weight = 1.0
            memory_id = ""
            memory_refs = item.get("entry_ref", {}).get("memory_refs", [])
            if isinstance(memory_refs, list) and memory_refs:
                memory_id = str(memory_refs[-1] or "")
            detail_id = f"shadow::{owner_structure_id}::{entry.get('entry_id', '')}"
            grouped_display_text = self._format_runtime_group_texts(existing_groups)
            base_detail = {
                "structure_id": detail_id,
                "display_text": str(entry.get("canonical_display_text", "") or entry.get("display_text", "") or detail_id),
                "grouped_display_text": grouped_display_text,
                "runtime_weight": round(float(runtime_weight), 8),
                "entry_runtime_weight": round(float(entry_runtime_weight), 8),
                "match_mode": "shadow_raw_residual_memory",
                "chain_depth": int(chain_depth),
                "entry_id": entry.get("entry_id", ""),
                "owner_structure_id": owner_structure_id,
                "parent_structure_id": parent_match.get("structure_id", "") if parent_match else "",
                "structure_db_id": str(structure_db.get("structure_db_id", "")),
                "structure_signature": existing_profile.get("content_signature", ""),
                "candidate_kind": "raw_residual_memory",
                "candidate_object_type": "em",
                "memory_id": memory_id,
                "shadow_only": True,
                "stats": {
                    "base_weight": round(float(entry.get("base_weight", 0.0) or 0.0), 8),
                    "recent_gain": round(float(entry.get("recent_gain", 1.0) or 1.0), 8),
                    "fatigue": round(float(entry.get("fatigue", 0.0) or 0.0), 8),
                    "runtime_er": round(float(entry.get("runtime_er", 0.0) or 0.0), 8),
                    "runtime_ev": round(float(entry.get("runtime_ev", 0.0) or 0.0), 8),
                    "match_count_total": int(entry.get("match_count_total", 0) or 0),
                },
            }
            if existing_length > incoming_length or existing_length < max(1, int(min_existing_length)):
                detail = {
                    **base_detail,
                    "match_score": 0.0,
                    "competition_score": 0.0,
                    "weighted_rank_score": 0.0,
                    "similarity_score": 0.0,
                    "exact_match": False,
                    "full_structure_included": False,
                    "coverage_ratio": 0.0,
                    "structure_match_ratio": 0.0,
                    "stimulus_match_ratio": 0.0,
                    "existing_length": existing_length,
                    "incoming_length": incoming_length,
                    "matched_existing_length": 0,
                    "matched_incoming_length": 0,
                    "contains_anchor": True,
                    "eligible": False,
                    "soft_partial_eligible": False,
                    "eligibility_reason": "length_guard",
                    "common_part": {"common_length": 0, "common_tokens": []},
                }
                details.append(detail)
                continue

            if anchor_token:
                flat_tokens = existing_profile.get("flat_tokens", []) or []
                all_unit_token_counts = existing_profile.get("all_unit_token_counts", {}) or {}
                if (flat_tokens and anchor_token in flat_tokens) or bool(all_unit_token_counts.get(anchor_token, 0)):
                    pass
                else:
                    continue

            self._increment_runtime_metric("shadow_raw_residual_common_part_count")
            common_part = cut_engine.maximum_common_part(existing_groups, incoming_groups)
            common_length = int(common_part.get("common_length", 0))
            matched_incoming_units = self._collect_matched_units(incoming_groups, common_part)
            contains_anchor = (
                any(str(unit.get("token", "")) == anchor_token for unit in matched_incoming_units)
                if anchor_token
                else True
            )
            matched_existing_units = self._collect_matched_units(
                existing_groups,
                common_part,
                use_existing_side=True,
            )
            stimulus_match_ratio = self._energy_match_ratio(
                matched_units=matched_incoming_units,
                all_units=competition_all_units,
                fallback_numerator=common_length,
                fallback_denominator=max(1, competition_length),
            )
            structure_match_ratio = self._energy_match_ratio(
                matched_units=matched_existing_units,
                all_units=list(existing_profile.get("all_units", []))
                or [
                    unit
                    for group in existing_groups
                    for unit in group.get("units", [])
                    if isinstance(unit, dict)
                ],
                fallback_numerator=common_length,
                fallback_denominator=max(1, existing_length),
            )
            matched_existing_length = int(common_part.get("matched_existing_unit_count", 0))
            matched_incoming_length = int(common_part.get("matched_incoming_unit_count", 0))
            exact_match = (
                common_length > 0
                and not common_part.get("residual_existing_signature", "")
                and not common_part.get("residual_incoming_signature", "")
                and matched_existing_length >= existing_length
                and matched_incoming_length >= incoming_length
                and bool(common_part.get("bundle_constraints_ok_exact", True))
            )
            full_structure_included = bool(
                common_length > 0
                and not common_part.get("residual_existing_signature", "")
                and matched_existing_length >= existing_length
            )
            bundle_constraints = {
                "exact": bool(common_part.get("bundle_constraints_ok_exact", True)),
                "existing_included": bool(common_part.get("bundle_constraints_ok_existing_included", True)),
                "incoming_included": bool(common_part.get("bundle_constraints_ok_incoming_included", True)),
            }
            match_score = self._compose_match_score(
                stimulus_match_ratio=stimulus_match_ratio,
                structure_match_ratio=structure_match_ratio,
                attribute_anchor_only=bool(
                    matched_incoming_units
                    and all(str(unit.get("unit_role", "")) == "attribute" for unit in matched_incoming_units)
                ),
            )
            context_payload = self._merge_match_context_payload(
                {
                    "object_type": "em",
                    "display_text": str(entry.get("canonical_display_text", "") or entry.get("display_text", "")),
                    "structure": {"ext": dict(existing_profile.get("ext", {}) or {})},
                },
                entry,
            )
            v2_breakdown = self._build_match_score_v2_breakdown(
                base_score=match_score,
                matched_existing_units=matched_existing_units,
                matched_incoming_units=matched_incoming_units,
                bundle_constraints=bundle_constraints,
                full_structure_included=full_structure_included,
                context_payload=context_payload,
                runtime_weight=runtime_weight,
                entry_runtime_weight=entry_runtime_weight,
                context_support_hint=0.42 if owner_profile else None,
            )
            blended_similarity_score = self._blend_v2_match_score(
                legacy_score=match_score,
                v2_score=float(v2_breakdown.get("score", match_score)),
            )
            similarity_score = blended_similarity_score if common_length > 0 else 0.0
            soft_partial_enabled = bool(self._config.get("soft_partial_match_competition_enabled", True))
            soft_partial_min_score = max(0.0, float(self._config.get("match_scoring_v2_min_score", 0.18) or 0.0))
            soft_partial_eligible = bool(
                soft_partial_enabled
                and common_length > 0
                and contains_anchor
                and existing_length >= max(1, int(min_existing_length))
                and not full_structure_included
                and float(similarity_score) >= soft_partial_min_score
            )
            eligible = bool(
                contains_anchor
                and existing_length >= max(1, int(min_existing_length))
                and (full_structure_included or soft_partial_eligible)
            )
            competition_score_legacy = round(float(match_score if eligible else 0.0), 8)
            competition_score_v2 = round(float(v2_breakdown.get("score", 0.0) if eligible else 0.0), 8)
            competition_score = round(float(similarity_score if eligible else 0.0), 8)
            common_part_summary = {
                "common_length": int(common_part.get("common_length", 0)),
                "incoming_range": list(common_part.get("incoming_range", [0, 0]) or [0, 0]),
                "matched_existing_unit_count": int(common_part.get("matched_existing_unit_count", 0)),
                "matched_incoming_unit_count": int(common_part.get("matched_incoming_unit_count", 0)),
                "residual_existing_signature": str(common_part.get("residual_existing_signature", "") or ""),
                "residual_incoming_signature": str(common_part.get("residual_incoming_signature", "") or ""),
                "bundle_constraints_ok_exact": bool(common_part.get("bundle_constraints_ok_exact", True)),
                "bundle_constraints_ok_existing_included": bool(common_part.get("bundle_constraints_ok_existing_included", True)),
                "bundle_constraints_ok_incoming_included": bool(common_part.get("bundle_constraints_ok_incoming_included", True)),
            }
            detail = {
                **base_detail,
                "match_score": round(float(match_score), 8),
                "match_score_legacy": round(float(match_score), 8),
                "match_score_v2": round(float(v2_breakdown.get("score", 0.0)), 8),
                "competition_score": competition_score,
                "competition_score_legacy": competition_score_legacy,
                "competition_score_v2": competition_score_v2,
                "weighted_rank_score": competition_score,
                "similarity_score": round(float(similarity_score), 8),
                "exact_match": exact_match,
                "full_structure_included": full_structure_included,
                "coverage_ratio": round(float(stimulus_match_ratio), 8),
                "structure_match_ratio": round(float(structure_match_ratio), 8),
                "stimulus_match_ratio": round(float(stimulus_match_ratio), 8),
                "existing_length": existing_length,
                "incoming_length": incoming_length,
                "matched_existing_length": matched_existing_length,
                "matched_incoming_length": matched_incoming_length,
                "contains_anchor": contains_anchor,
                "eligible": eligible,
                "soft_partial_eligible": soft_partial_eligible,
                "eligibility_reason": "full_structure_included" if full_structure_included else ("soft_partial_score" if soft_partial_eligible else "not_eligible"),
                "common_part": common_part_summary,
            }
            detail.update(self._flatten_match_score_v2(v2_breakdown))
            if promotion_enabled and len(promoted_candidates) < promotion_max_candidates:
                time_signal_visible = bool(
                    detail.get("v2_numeric_time_like_wildcard_applied", False)
                    or detail.get("v2_time_factor_applied", False)
                    or float(detail.get("v2_numeric_time_like_score", -1.0) or -1.0) > 0.0
                )
                promotion_ok = bool(
                    detail.get("eligible", False)
                    and float(detail.get("match_score_v2", 0.0) or 0.0) >= promotion_min_v2_score
                    and (time_signal_visible or not promotion_require_time_signal)
                )
                if promotion_ok:
                    promoted_candidate, promoted_entry = self._materialize_shadow_raw_residual_candidate(
                        entry=entry,
                        target_profile=existing_profile,
                        owner_structure_id=owner_structure_id,
                        structure_store=structure_store,
                        pointer_index=pointer_index,
                        cut_engine=cut_engine,
                        trace_id=trace_id,
                        tick_id=tick_id,
                    )
                    promoted_id = str((promoted_candidate or {}).get("id", "") or "").strip()
                    if promoted_id:
                        detail["promoted_structure_id"] = promoted_id
                        if all(str(item.get("id", "") or "") != promoted_id for item in promoted_candidates):
                            promoted_candidates.append(promoted_candidate)
                        if isinstance(promoted_entry, dict):
                            promoted_entry_lookup[promoted_id] = promoted_entry
            details.append(detail)

        details.sort(
            key=lambda item: (
                0 if item.get("eligible") else 1,
                -float(item.get("competition_score", 0.0)),
                -int(item.get("existing_length", 0)),
                -float(item.get("entry_runtime_weight", 0.0)),
                -float(item.get("runtime_weight", 0.0)),
            )
        )
        return details, promoted_candidates, promoted_entry_lookup

    def _materialize_shadow_raw_residual_candidate(
        self,
        *,
        entry: dict,
        target_profile: dict,
        owner_structure_id: str,
        structure_store,
        pointer_index,
        cut_engine,
        trace_id: str,
        tick_id: str,
    ) -> tuple[dict | None, dict | None]:
        canonical_display_text = str(
            target_profile.get("display_text", "")
            or entry.get("canonical_display_text", "")
            or entry.get("display_text", "")
            or target_profile.get("content_signature", "")
            or ""
        ).strip()
        memory_refs = [str(item) for item in list(entry.get("memory_refs", []) or []) if str(item)]
        profile_ext = dict(target_profile.get("ext", {}) or {}) if isinstance(target_profile.get("ext", {}), dict) else {}
        context_free_identity = bool(
            self._config.get("induction_raw_residual_materialized_structure_context_free_identity_enabled", True)
        )
        if context_free_identity:
            for key in ("context_ref_object_id", "context_ref_object_type", "context_owner_structure_id", "context_path_ids"):
                profile_ext.pop(key, None)
        else:
            profile_ext = merge_context_metadata(
                profile_ext,
                context_ref_object_id=owner_structure_id,
                context_ref_object_type="st" if owner_structure_id else str(profile_ext.get("context_ref_object_type", "") or ""),
                context_owner_structure_id=owner_structure_id,
                parent_ids=[owner_structure_id] if owner_structure_id else [],
            )
        profile_ext.update(
            {
                "residual_memory_as_structure": True,
                "residual_origin_kind": "stimulus_raw_residual_promoted_structure",
                "raw_residual_memory_refs": list(memory_refs),
                "growth_projection_owner_is_provenance_only": context_free_identity,
                "provenance_owner_structure_id": owner_structure_id if context_free_identity else "",
            }
        )
        if memory_refs:
            profile_ext.setdefault("source_em_id", memory_refs[0])
            profile_ext.setdefault("memory_id", memory_refs[0])

        result = self._find_or_create_structure_from_profile(
            profile={
                **dict(target_profile),
                "display_text": canonical_display_text or str(target_profile.get("content_signature", "") or ""),
                "grouped_display_text": canonical_display_text or str(target_profile.get("content_signature", "") or ""),
                "ext": profile_ext,
            },
            structure_store=structure_store,
            pointer_index=pointer_index,
            cut_engine=cut_engine,
            trace_id=f"{trace_id}_shadow_raw_residual_promote",
            tick_id=tick_id,
            confidence=0.72,
            origin="stimulus_shadow_raw_residual_promote",
            origin_id=str(
                target_profile.get("content_signature", "")
                or entry.get("canonical_content_signature", "")
                or entry.get("content_signature", "")
                or canonical_display_text
            ),
            parent_ids=[] if context_free_identity else ([owner_structure_id] if owner_structure_id else []),
            base_weight=max(0.0, float(entry.get("base_weight", 0.0) or 0.0)),
            ext=profile_ext,
            require_context_free=context_free_identity,
        )
        structure_obj = result.get("structure") if isinstance(result, dict) else None
        if not isinstance(structure_obj, dict):
            return None, None
        structure_id = str(structure_obj.get("id", "") or "").strip()
        if not structure_id or structure_id == owner_structure_id:
            return None, None
        candidate = dict(structure_obj)
        candidate.setdefault("_runtime_path", {})
        candidate["_runtime_path"] = {
            "entry_id": str(entry.get("entry_id", "") or ""),
            "owner_structure_id": owner_structure_id,
            "owner_structure_db_id": str(
                (structure_store.get_db_by_owner(owner_structure_id) or {}).get("structure_db_id", "")
            )
            if owner_structure_id
            else "",
            "target_db_id": str(
                (
                    candidate.get("db_pointer", {})
                    if isinstance(candidate.get("db_pointer", {}), dict)
                    else {}
                ).get("structure_db_id", "")
            ),
            "promoted_shadow_raw_residual": True,
        }
        promoted_entry = dict(entry)
        promoted_entry.setdefault("entry_type", "raw_residual_promoted_structure")
        promoted_entry.setdefault("ext", {})
        if isinstance(promoted_entry.get("ext", {}), dict):
            promoted_entry["ext"] = {
                **dict(promoted_entry.get("ext", {}) or {}),
                "relation_type": "stimulus_raw_residual_promoted_structure",
                "promoted_shadow_raw_residual": True,
                "context_owner_structure_id": owner_structure_id,
                "context_ref_object_id": owner_structure_id,
                "context_ref_object_type": "st" if owner_structure_id else "",
            }
        return candidate, promoted_entry

    def _collect_local_child_candidates(
        self,
        *,
        owner_match: dict,
        structure_store,
        seen_structure_ids: set[str] | None = None,
        tick_id: str = "",
    ) -> dict:
        seen = set(seen_structure_ids or set())
        entry_lookup: dict[str, dict] = {}
        candidates: list[dict] = []
        structure_db = self._open_structure_db_from_match(owner_match, structure_store)
        if not structure_db:
            return {"candidates": candidates, "entry_lookup": entry_lookup}

        allow_cs_event_structures = bool(self._config.get("enable_cs_event_structures_in_stimulus_retrieval", False))
        try:
            max_candidates = int(self._config.get("stimulus_local_child_candidate_max_per_owner", 48) or 0)
        except Exception:
            max_candidates = 48
        max_candidates = max(0, int(max_candidates))
        raw_candidate_count = 0
        guard_pruned_count = 0
        owner_structure_id = str(structure_db.get("owner_structure_id", "") or owner_match.get("structure_id", "") or "")
        diff_source, budget_debug = build_owner_runtime_candidate_view(
            entries=structure_db.get("diff_table", []),
            config=self._config,
            owner_structure_id=owner_structure_id,
            path_kind="stimulus_local_child",
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
        diff_table = sorted(
            diff_source,
            key=lambda item: (
                -float(item.get("base_weight", 0.0)),
                -float(item.get("recent_gain", 1.0)),
                float(item.get("fatigue", 0.0)),
                str(item.get("entry_id", "")),
            ),
        )
        for entry in diff_table:
            if entry.get("entry_type", "structure_ref") != "structure_ref":
                continue
            if str(entry.get("ext", {}).get("relation_type", "")) == "residual_context":
                continue
            raw_candidate_count += 1
            if max_candidates > 0 and len(candidates) >= max_candidates:
                guard_pruned_count += 1
                continue
            target_structure, target_db_id = self._resolve_diff_target(entry, structure_store)
            if not target_structure:
                continue
            if (
                (not allow_cs_event_structures)
                and str(target_structure.get("sub_type", "") or "") == "cognitive_stitching_event_structure"
            ):
                continue
            target_id = target_structure.get("id", "")
            if not target_id or target_id in seen:
                continue
            seen.add(target_id)
            candidate = dict(target_structure)
            candidate.setdefault("_runtime_path", {})
            candidate["_runtime_path"] = {
                "entry_id": entry.get("entry_id", ""),
                "owner_structure_id": structure_db.get("owner_structure_id", ""),
                "owner_structure_db_id": structure_db.get("structure_db_id", ""),
                "target_db_id": target_db_id,
            }
            candidates.append(candidate)
            entry_lookup[target_id] = entry
        self._increment_runtime_metric("local_child_candidate_count", raw_candidate_count)
        self._increment_runtime_metric("local_child_candidate_pruned_count", guard_pruned_count)
        return {"candidates": candidates, "entry_lookup": entry_lookup, "structure_db_id": structure_db.get("structure_db_id", "")}

    def _open_structure_db_from_match(self, match: dict, structure_store) -> dict | None:
        structure_db_id = str(match.get("structure_db_id", ""))
        if structure_db_id:
            structure_db = structure_store.get_db(structure_db_id)
            if structure_db:
                return structure_db
        structure_id = str(match.get("structure_id", ""))
        if not structure_id:
            return None
        return structure_store.get_db_by_owner(structure_id)

    def _resolve_diff_target(self, entry: dict, structure_store) -> tuple[dict | None, str]:
        target_id = str(entry.get("target_id", ""))
        if not target_id:
            return None, ""
        target_structure = structure_store.get(target_id)
        target_db_id = str(entry.get("target_db_id", ""))
        if not target_db_id and target_structure:
            target_db_id = str(target_structure.get("db_pointer", {}).get("structure_db_id", ""))
            if target_db_id:
                entry["target_db_id"] = target_db_id
        return target_structure, target_db_id

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

    def _mark_chain_entries(
        self,
        *,
        best: dict,
        structure_store,
        transferred_er: float,
        transferred_ev: float,
    ) -> None:
        for path_entry in best.get("path_entries", []):
            owner_structure_id = str(path_entry.get("owner_structure_id", ""))
            entry_id = str(path_entry.get("entry_id", ""))
            if not owner_structure_id or not entry_id:
                continue
            structure_db = structure_store.get_db_by_owner(owner_structure_id)
            if not structure_db:
                continue
            updated = False
            for entry in structure_db.get("diff_table", []):
                if str(entry.get("entry_id", "")) != entry_id:
                    continue
                self._weight.mark_entry_activation(
                    entry,
                    delta_er=transferred_er,
                    delta_ev=transferred_ev,
                    match_score=float(best.get("match_score", 0.0)),
                    now_ms=int(time.time() * 1000),
                )
                updated = True
                break
            if updated:
                structure_store.update_db(structure_db)

    def _collect_candidates(
        self,
        *,
        signatures: list[str],
        structure_store,
        pointer_index,
        exclude_structure_ids: list[str] | None = None,
    ) -> dict:
        candidates = []
        signature_hits = []
        seen_ids = set(exclude_structure_ids or [])
        allow_cs_event_structures = bool(self._config.get("enable_cs_event_structures_in_stimulus_retrieval", False))

        def append_candidate(candidate_id: str) -> None:
            if not candidate_id or candidate_id in seen_ids:
                return
            candidate = structure_store.get(candidate_id)
            if not candidate:
                return
            if not allow_cs_event_structures and str(candidate.get("sub_type", "") or "") == "cognitive_stitching_event_structure":
                return
            seen_ids.add(candidate_id)
            candidates.append(candidate)

        def append_children(owner_structure_id: str) -> None:
            if not allow_cs_event_structures:
                try:
                    owner_obj = structure_store.get(owner_structure_id)
                    if owner_obj and str(owner_obj.get("sub_type", "") or "") == "cognitive_stitching_event_structure":
                        return
                except Exception:
                    pass
            structure_db = structure_store.get_db_by_owner(owner_structure_id)
            if not structure_db:
                return
            for entry in sorted(structure_db.get("diff_table", []), key=lambda item: float(item.get("base_weight", 0.0)), reverse=True):
                append_candidate(entry.get("target_id", ""))

        unique_signatures = []
        for signature in signatures:
            text = str(signature or "")
            if text and text not in unique_signatures:
                unique_signatures.append(text)

        for signature in unique_signatures:
            candidate_ids = pointer_index.query_candidates_by_signature(signature)
            signature_hits.append({"signature": signature, "candidate_count": len(candidate_ids)})
            direct_ids = []
            for candidate_id in candidate_ids:
                if candidate_id in seen_ids:
                    continue
                append_candidate(candidate_id)
                direct_ids.append(candidate_id)
            for candidate_id in direct_ids:
                append_children(candidate_id)

        used_recent_fallback = False
        candidate_source = "signature_index" if candidates else "recent_structure_fallback"
        if not candidates:
            used_recent_fallback = True
            for candidate in structure_store.get_recent_structures(
                limit=int(self._config.get("fallback_lookup_max_candidates", 32))
            ):
                candidate_id = candidate.get("id", "")
                if (
                    candidate_id
                    and candidate_id not in seen_ids
                    and (
                        allow_cs_event_structures
                        or str(candidate.get("sub_type", "") or "") != "cognitive_stitching_event_structure"
                    )
                ):
                    seen_ids.add(candidate_id)
                    candidates.append(candidate)

        return {
            "candidates": candidates[: int(self._config.get("fallback_lookup_max_candidates", 32))],
            "used_recent_fallback": used_recent_fallback,
            "candidate_source": candidate_source,
            "signature_hits": signature_hits,
        }

    def _best_structure_match(
        self,
        *,
        incoming_profile: dict,
        competition_units: list[dict] | None,
        candidates: list[dict],
        structure_store,
        cut_engine,
        anchor_token: str,
        entry_lookup: dict[str, dict] | None = None,
        min_existing_length: int = 1,
        chain_depth: int = 0,
        parent_match: dict | None = None,
    ) -> tuple[dict | None, list[dict]]:
        best = None
        candidate_details = []
        now_ms = int(time.time() * 1000)
        incoming_groups = list(incoming_profile.get("sequence_groups", []))
        incoming_length = int(incoming_profile.get("unit_count", incoming_profile.get("token_count", len(incoming_profile.get("flat_tokens", [])))))
        entry_lookup = entry_lookup or {}
        # PERF: 这里仅用于计算能量匹配比例（只读），不需要对每个 unit 做 dict 拷贝。
        incoming_all_units = list(incoming_profile.get("all_units", []))
        if not incoming_all_units:
            incoming_all_units = [
                unit
                for group in incoming_groups
                for unit in group.get("units", [])
                if isinstance(unit, dict)
            ]
        competition_all_units = [
            unit
            for unit in (competition_units or incoming_all_units)
            if isinstance(unit, dict)
        ]
        competition_length = sum(1 for unit in competition_all_units if str(unit.get("token", "")))
        raw_candidate_count = len(candidates)
        try:
            max_match_candidates = int(self._config.get("stimulus_best_match_candidate_max_per_owner", 64) or 0)
        except Exception:
            max_match_candidates = 64
        max_match_candidates = max(0, int(max_match_candidates))
        if max_match_candidates > 0 and len(candidates) > max_match_candidates:
            candidates = sorted(
                list(candidates),
                key=lambda row: (
                    -float(entry_lookup.get(row.get("id", ""), {}).get("base_weight", 0.0) or 0.0),
                    -float(entry_lookup.get(row.get("id", ""), {}).get("recent_gain", 1.0) or 1.0),
                    float(entry_lookup.get(row.get("id", ""), {}).get("fatigue", 0.0) or 0.0),
                    -float(row.get("stats", {}).get("base_weight", 0.0) or 0.0),
                    str(row.get("id", "") or ""),
                ),
            )[:max_match_candidates]
        self._increment_runtime_metric("best_structure_match_candidate_count", raw_candidate_count)
        self._increment_runtime_metric("best_structure_match_pruned_count", max(0, raw_candidate_count - len(candidates)))

        for candidate in candidates:
            self._weight.decay_structure(candidate, now_ms=now_ms, round_step=1)
            entry = entry_lookup.get(candidate.get("id", ""))
            if entry is not None:
                self._weight.decay_entry(entry, now_ms=now_ms, round_step=1)
            match_mode = (
                "promoted_shadow_raw_residual"
                if bool(candidate.get("_runtime_path", {}).get("promoted_shadow_raw_residual", False))
                else "candidate_match"
            )
            existing_profile = self._build_structure_profile(
                structure_obj=candidate,
                structure_store=structure_store,
                cut_engine=cut_engine,
            )
            existing_groups = list(existing_profile.get("sequence_groups", []))
            if not existing_groups:
                continue

            existing_length = int(existing_profile.get("unit_count", existing_profile.get("token_count", len(existing_profile.get("flat_tokens", [])))))
            candidate_runtime_weight = self._weight.compute_runtime_weight(
                base_weight=float(candidate.get("stats", {}).get("base_weight", 0.0)),
                recent_gain=float(candidate.get("stats", {}).get("recent_gain", 1.0)),
                fatigue=float(candidate.get("stats", {}).get("fatigue", 0.0)),
            )
            entry_runtime_weight = self._weight.entry_runtime_weight(entry) if entry is not None else 0.0
            if existing_length > incoming_length or existing_length < max(1, int(min_existing_length)):
                candidate_details.append(
                    {
                        "structure_id": candidate.get("id", ""),
                        "display_text": candidate.get("structure", {}).get("display_text", candidate.get("id", "")),
                        "grouped_display_text": "",
                        "runtime_weight": round(float(candidate_runtime_weight), 8),
                        "entry_runtime_weight": round(float(entry_runtime_weight), 8),
                        "match_score": 0.0,
                        "competition_score": 0.0,
                        "weighted_rank_score": 0.0,
                        "similarity_score": 0.0,
                        "exact_match": False,
                        "full_structure_included": False,
                        "coverage_ratio": 0.0,
                        "structure_match_ratio": 0.0,
                        "stimulus_match_ratio": 0.0,
                        "existing_length": existing_length,
                        "incoming_length": incoming_length,
                        "matched_existing_length": 0,
                        "matched_incoming_length": 0,
                        "contains_anchor": True,
                        "eligible": False,
                        "common_part": {"common_length": 0, "common_tokens": []},
                        "match_mode": match_mode,
                        "chain_depth": int(chain_depth),
                        "entry_id": entry.get("entry_id", "") if entry else "",
                        "owner_structure_id": str(candidate.get("_runtime_path", {}).get("owner_structure_id", "")),
                        "parent_structure_id": parent_match.get("structure_id", "") if parent_match else "",
                        "structure_db_id": str(candidate.get("_runtime_path", {}).get("target_db_id", ""))
                        or str(candidate.get("db_pointer", {}).get("structure_db_id", "")),
                        "structure_signature": existing_profile.get("content_signature", ""),
                        "stats": self._capture_structure_stats(candidate),
                    }
                )
                continue

            # PERF: contains_anchor 的必要条件之一是“结构侧必须包含 anchor token”。
            # 若结构侧根本没有该 token，则不可能成为 eligible match，直接跳过昂贵的 common_part 计算。
            #
            # ⚠️ 重要细节（与属性刺激元/CSA 设计强相关）:
            # - cut_engine.profile.flat_tokens 默认来自 group.tokens，它会倾向于“隐藏属性 unit”（display_visible=false）
            #   以保持展示更清爽；
            # - 但 pointer_index.register_structure() 会把 group.units[*].token 全部注册进签名索引（包含属性 token）。因此，
            #   当锚点 token 恰好是“属性刺激元 token”时，候选结构可能会被索引命中，但却在这里因为 flat_tokens 不含属性 token
            #   而被错误跳过，导致属性锚点无法扩展到长结构（违背“属性可脱锚抽象”的理论目标）。
            #
            # 解决方案：保持 flat_tokens 的展示洁净语义不变，但此处额外检查一次 unit.token（包含属性 unit）。
            if anchor_token:
                flat_tokens = existing_profile.get("flat_tokens", []) or []
                all_unit_token_counts = existing_profile.get("all_unit_token_counts", {}) or {}
                if (flat_tokens and anchor_token in flat_tokens) or bool(all_unit_token_counts.get(anchor_token, 0)):
                    pass
                else:
                    continue

            strict_overlap_upper_bound = self._profile_strict_overlap_upper_bound(existing_profile, incoming_profile)
            if strict_overlap_upper_bound <= 0:
                self._increment_runtime_metric("best_structure_match_strict_overlap_fast_reject_count")
                continue
            if strict_overlap_upper_bound < max(1, int(min_existing_length)):
                self._increment_runtime_metric("best_structure_match_strict_overlap_fast_reject_count")
                continue

            self._increment_runtime_metric("best_structure_match_common_part_count")
            common_part = cut_engine.maximum_common_part(existing_groups, incoming_groups)
            common_length = int(common_part.get("common_length", 0))
            matched_incoming_units = self._collect_matched_units(incoming_groups, common_part)
            # Anchor containment should be defined on matched units (unit.token), not only on
            # group.tokens-derived common_tokens. Otherwise, attribute anchors (display_visible=false)
            # can never satisfy contains_anchor, which breaks the "attribute SA can be an anchor"
            # semantic and blocks "脱锚抽象" paths.
            contains_anchor = (
                any(str(unit.get("token", "")) == anchor_token for unit in matched_incoming_units)
                if anchor_token
                else True
            )
            matched_existing_units = self._collect_matched_units(
                existing_groups,
                common_part,
                use_existing_side=True,
            )
            stimulus_match_ratio = self._energy_match_ratio(
                matched_units=matched_incoming_units,
                all_units=competition_all_units,
                fallback_numerator=common_length,
                fallback_denominator=max(1, competition_length),
            )
            structure_match_ratio = self._energy_match_ratio(
                matched_units=matched_existing_units,
                all_units=list(existing_profile.get("all_units", []))
                or [
                    unit
                    for group in existing_groups
                    for unit in group.get("units", [])
                    if isinstance(unit, dict)
                ],
                fallback_numerator=common_length,
                fallback_denominator=max(1, existing_length),
            )
            matched_existing_length = int(common_part.get("matched_existing_unit_count", 0))
            matched_incoming_length = int(common_part.get("matched_incoming_unit_count", 0))
            exact_match = (
                common_length > 0
                and not common_part.get("residual_existing_signature", "")
                and not common_part.get("residual_incoming_signature", "")
                and matched_existing_length >= existing_length
                and matched_incoming_length >= incoming_length
                # CSA 门控：要求双方 bundle 约束也完全满足，避免“跨对象拼接”造成假阳性。
                and bool(common_part.get("bundle_constraints_ok_exact", True))
            )
            full_structure_included = bool(
                common_length > 0
                and not common_part.get("residual_existing_signature", "")
                and matched_existing_length >= existing_length
            )
            bundle_constraints = {
                "exact": bool(common_part.get("bundle_constraints_ok_exact", True)),
                "existing_included": bool(common_part.get("bundle_constraints_ok_existing_included", True)),
                "incoming_included": bool(common_part.get("bundle_constraints_ok_incoming_included", True)),
            }
            match_score = self._compose_match_score(
                stimulus_match_ratio=stimulus_match_ratio,
                structure_match_ratio=structure_match_ratio,
                attribute_anchor_only=bool(
                    matched_incoming_units
                    and all(str(unit.get("unit_role", "")) == "attribute" for unit in matched_incoming_units)
                ),
            )
            v2_breakdown = self._build_match_score_v2_breakdown(
                base_score=match_score,
                matched_existing_units=matched_existing_units,
                matched_incoming_units=matched_incoming_units,
                bundle_constraints=bundle_constraints,
                full_structure_included=full_structure_included,
                context_payload=self._merge_match_context_payload(candidate, entry),
                runtime_weight=candidate_runtime_weight,
                entry_runtime_weight=entry_runtime_weight,
            )
            blended_similarity_score = self._blend_v2_match_score(
                legacy_score=match_score,
                v2_score=float(v2_breakdown.get("score", match_score)),
            )
            similarity_score = blended_similarity_score if common_length > 0 else 0.0
            soft_partial_enabled = bool(self._config.get("soft_partial_match_competition_enabled", True))
            soft_partial_min_score = max(0.0, float(self._config.get("match_scoring_v2_min_score", 0.18) or 0.0))
            soft_partial_eligible = bool(
                soft_partial_enabled
                and common_length > 0
                and contains_anchor
                and existing_length >= max(1, int(min_existing_length))
                and not full_structure_included
                and float(similarity_score) >= soft_partial_min_score
            )
            eligible = bool(
                contains_anchor
                and existing_length >= max(1, int(min_existing_length))
                and (full_structure_included or soft_partial_eligible)
            )
            competition_score_legacy = round(float(match_score if eligible else 0.0), 8)
            competition_score_v2 = round(float(v2_breakdown.get("score", 0.0) if eligible else 0.0), 8)
            competition_score = round(float(similarity_score if eligible else 0.0), 8)

            # Keep candidate details compact: common_part can be very large (full group payloads).
            common_part_summary = {
                "common_length": int(common_part.get("common_length", 0)),
                "incoming_range": list(common_part.get("incoming_range", [0, 0]) or [0, 0]),
                "matched_existing_unit_count": int(common_part.get("matched_existing_unit_count", 0)),
                "matched_incoming_unit_count": int(common_part.get("matched_incoming_unit_count", 0)),
                "residual_existing_signature": str(common_part.get("residual_existing_signature", "") or ""),
                "residual_incoming_signature": str(common_part.get("residual_incoming_signature", "") or ""),
                "bundle_constraints_ok_exact": bool(common_part.get("bundle_constraints_ok_exact", True)),
                "bundle_constraints_ok_existing_included": bool(common_part.get("bundle_constraints_ok_existing_included", True)),
                "bundle_constraints_ok_incoming_included": bool(common_part.get("bundle_constraints_ok_incoming_included", True)),
            }
            grouped_display_text = self._format_runtime_group_texts(existing_groups)

            detail = {
                "structure_id": candidate.get("id", ""),
                "display_text": candidate.get("structure", {}).get("display_text", candidate.get("id", "")),
                "grouped_display_text": grouped_display_text,
                "runtime_weight": round(float(candidate_runtime_weight), 8),
                "entry_runtime_weight": round(float(entry_runtime_weight), 8),
                "match_score": round(float(match_score), 8),
                "match_score_legacy": round(float(match_score), 8),
                "match_score_v2": round(float(v2_breakdown.get("score", 0.0)), 8),
                "competition_score": competition_score,
                "competition_score_legacy": competition_score_legacy,
                "competition_score_v2": competition_score_v2,
                "weighted_rank_score": competition_score,
                "similarity_score": round(float(similarity_score), 8),
                "exact_match": exact_match,
                "full_structure_included": full_structure_included,
                "coverage_ratio": round(float(stimulus_match_ratio), 8),
                "structure_match_ratio": round(float(structure_match_ratio), 8),
                "stimulus_match_ratio": round(float(stimulus_match_ratio), 8),
                "existing_length": existing_length,
                "incoming_length": incoming_length,
                "matched_existing_length": matched_existing_length,
                "matched_incoming_length": matched_incoming_length,
                "contains_anchor": contains_anchor,
                "eligible": eligible,
                "soft_partial_eligible": soft_partial_eligible,
                "eligibility_reason": "full_structure_included" if full_structure_included else ("soft_partial_score" if soft_partial_eligible else "not_eligible"),
                "common_part": common_part_summary,
                "match_mode": match_mode,
                "chain_depth": int(chain_depth),
                "entry_id": entry.get("entry_id", "") if entry else "",
                "owner_structure_id": str(candidate.get("_runtime_path", {}).get("owner_structure_id", "")),
                "parent_structure_id": parent_match.get("structure_id", "") if parent_match else "",
                "structure_db_id": str(candidate.get("_runtime_path", {}).get("target_db_id", "")) or str(candidate.get("db_pointer", {}).get("structure_db_id", "")),
                "structure_signature": existing_profile.get("content_signature", ""),
                "stats": self._capture_structure_stats(candidate),
            }
            detail.update(self._flatten_match_score_v2(v2_breakdown))
            candidate_details.append(detail)

            if not detail["eligible"]:
                continue

            if self._is_better_structure_match(detail, best):
                best = {
                    "structure_id": candidate.get("id", ""),
                    "display_text": candidate.get("structure", {}).get("display_text", candidate.get("id", "")),
                    "grouped_display_text": grouped_display_text,
                    "exact_match": exact_match,
                    "full_structure_included": full_structure_included,
                    "coverage_ratio": stimulus_match_ratio,
                    "match_score": round(float(match_score), 8),
                    "match_score_legacy": round(float(match_score), 8),
                    "match_score_v2": round(float(v2_breakdown.get("score", 0.0)), 8),
                    "competition_score": round(float(competition_score), 8),
                    "competition_score_legacy": competition_score_legacy,
                    "competition_score_v2": competition_score_v2,
                    "weighted_rank_score": competition_score,
                    "similarity_score": round(float(similarity_score), 8),
                    "structure_match_ratio": round(float(structure_match_ratio), 8),
                    "stimulus_match_ratio": round(float(stimulus_match_ratio), 8),
                    "existing_length": existing_length,
                    "matched_existing_length": matched_existing_length,
                    "matched_incoming_length": matched_incoming_length,
                    "runtime_weight": candidate_runtime_weight,
                    "entry_runtime_weight": entry_runtime_weight,
                    "common_part": common_part,
                    "incoming_range": list(common_part.get("incoming_range", [0, 0])),
                    "match_mode": match_mode,
                    "structure_signature": existing_profile.get("content_signature", ""),
                    "structure_db_id": str(candidate.get("_runtime_path", {}).get("target_db_id", ""))
                    or str(candidate.get("db_pointer", {}).get("structure_db_id", "")),
                    "path_entries": list(parent_match.get("path_entries", [])) if parent_match else [],
                }
                best.update(self._flatten_match_score_v2(v2_breakdown))
                if entry is not None:
                    best["path_entries"].append(
                        {
                            "entry_id": entry.get("entry_id", ""),
                            "owner_structure_id": str(
                                candidate.get("_runtime_path", {}).get("owner_structure_id", "")
                            ),
                            "owner_structure_db_id": str(
                                candidate.get("_runtime_path", {}).get("owner_structure_db_id", "")
                            ),
                            "target_structure_id": candidate.get("id", ""),
                            "target_db_id": str(candidate.get("_runtime_path", {}).get("target_db_id", "")),
                        }
                    )

        candidate_details.sort(
            key=lambda item: (
                0 if item.get("eligible") else 1,
                -float(item.get("competition_score", 0.0)),
                -int(item.get("existing_length", 0)),
                -float(item.get("entry_runtime_weight", 0.0)),
                -float(item.get("runtime_weight", 0.0)),
            )
        )
        return best, candidate_details

    def _get_or_create_focus_window_fallback(
        self,
        *,
        anchor_unit: dict,
        focus_units: list[dict],
        incoming_profile: dict,
        competition_units: list[dict] | None,
        structure_store,
        pointer_index,
        cut_engine,
        trace_id: str,
        tick_id: str,
        parent_ids: list[str],
        source_packet_id: str,
        round_index: int,
    ) -> tuple[dict | None, dict | None, dict | None]:
        if not focus_units:
            return None, None, None
        focus_profile = cut_engine.make_structure_payload_from_units(
            focus_units,
            confidence=float(self._config.get("stimulus_focus_seed_confidence", 0.9)),
        )
        focus_signature = focus_profile.get("content_signature", "")
        existing = self._find_exact_structure_by_signature(
            signature=focus_signature,
            structure_store=structure_store,
            pointer_index=pointer_index,
            cut_engine=cut_engine,
            expected_tokens=list(focus_profile.get("flat_tokens", [])),
            expected_sequence_groups=list(focus_profile.get("sequence_groups", [])),
        )
        created_structure = None
        if existing is None:
            kind = "atomic_anchor" if len(focus_units) == 1 else "focus_window_seed"
            result = self._find_or_create_structure_from_units(
                units=focus_units,
                structure_store=structure_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
                trace_id=trace_id,
                tick_id=tick_id,
                confidence=float(self._config.get("stimulus_focus_seed_confidence", 0.9)),
                origin="stimulus_focus_window_seed",
                origin_id=source_packet_id,
                parent_ids=parent_ids,
                ext={
                    "origin_round": round_index,
                    "source_packet_id": source_packet_id,
                    "origin_group_index": anchor_unit.get("group_index", 0),
                    "origin_source_type": anchor_unit.get("source_type", ""),
                    "kind": kind,
                    "relation_type": kind,
                },
            )
            existing = result["structure"]
            created_structure = existing if result.get("created") else None
        if existing is None:
            return None, None, created_structure

        existing_profile = self._build_structure_profile(
            structure_obj=existing,
            structure_store=structure_store,
            cut_engine=cut_engine,
        )
        common_part = cut_engine.maximum_common_part(existing_profile.get("sequence_groups", []), incoming_profile.get("sequence_groups", []))
        common_length = int(common_part.get("common_length", 0))
        incoming_length = max(1, int(incoming_profile.get("token_count", len(incoming_profile.get("flat_tokens", [])))))
        existing_length = max(1, int(existing_profile.get("token_count", len(existing_profile.get("flat_tokens", [])))))
        focus_groups = self._units_to_groups(focus_units)
        matched_incoming_units = self._collect_matched_units(focus_groups, common_part)
        matched_existing_units = self._collect_matched_units(
            existing_profile.get("sequence_groups", []),
            common_part,
            use_existing_side=True,
        )
        stimulus_match_ratio = self._energy_match_ratio(
            matched_units=matched_incoming_units,
            all_units=[
                dict(unit)
                for unit in (competition_units or focus_units)
                if isinstance(unit, dict)
            ],
            fallback_numerator=common_length,
            fallback_denominator=max(
                1,
                len([unit for unit in (competition_units or focus_units) if str(unit.get("token", ""))]),
            ),
        )
        structure_match_ratio = self._energy_match_ratio(
            matched_units=matched_existing_units,
            all_units=list(existing_profile.get("all_units", []))
            or [
                dict(unit)
                for group in existing_profile.get("sequence_groups", [])
                for unit in group.get("units", [])
            ],
            fallback_numerator=common_length,
            fallback_denominator=existing_length,
        )
        match_score = self._compose_match_score(
            stimulus_match_ratio=stimulus_match_ratio,
            structure_match_ratio=structure_match_ratio,
            attribute_anchor_only=bool(
                matched_incoming_units
                and all(str(unit.get("unit_role", "")) == "attribute" for unit in matched_incoming_units)
            ),
        )
        matched_existing_length = int(common_part.get("matched_existing_unit_count", 0))
        matched_incoming_length = int(common_part.get("matched_incoming_unit_count", 0))
        full_structure_included = bool(
            common_length > 0
            and not common_part.get("residual_existing_signature", "")
            and matched_existing_length >= existing_length
        )
        exact_match = bool(
            full_structure_included
            and not common_part.get("residual_incoming_signature", "")
            and matched_incoming_length >= incoming_length
            and bool(common_part.get("bundle_constraints_ok_exact", True))
        )
        v2_breakdown = self._build_match_score_v2_breakdown(
            base_score=match_score,
            matched_existing_units=matched_existing_units,
            matched_incoming_units=matched_incoming_units,
            bundle_constraints={
                "exact": bool(common_part.get("bundle_constraints_ok_exact", True)),
                "existing_included": bool(common_part.get("bundle_constraints_ok_existing_included", True)),
                "incoming_included": bool(common_part.get("bundle_constraints_ok_incoming_included", True)),
            },
            full_structure_included=full_structure_included,
            context_payload=existing,
        )
        blended_match_score = self._blend_v2_match_score(
            legacy_score=match_score,
            v2_score=float(v2_breakdown.get("score", match_score)),
        )
        fallback_best = {
            "structure_id": existing.get("id", ""),
            "display_text": existing.get("structure", {}).get("display_text", existing.get("id", "")),
            "grouped_display_text": self._format_runtime_group_texts(existing_profile.get("sequence_groups", [])),
            "exact_match": exact_match,
            "full_structure_included": full_structure_included,
            "coverage_ratio": stimulus_match_ratio,
            "match_score": match_score,
            "match_score_legacy": match_score,
            "match_score_v2": round(float(v2_breakdown.get("score", 0.0)), 8),
            "competition_score": blended_match_score,
            "competition_score_legacy": round(float(match_score), 8),
            "competition_score_v2": round(float(v2_breakdown.get("score", 0.0)), 8),
            "weighted_rank_score": blended_match_score,
            "similarity_score": blended_match_score,
            "structure_match_ratio": structure_match_ratio,
            "stimulus_match_ratio": stimulus_match_ratio,
            "existing_length": existing_length,
            "runtime_weight": 1.0,
            "common_part": common_part,
            "incoming_range": list(common_part.get("incoming_range", [0, 0])),
            "match_mode": "focus_window_fallback",
            "structure_signature": existing_profile.get("content_signature", focus_signature),
            "structure_db_id": str(existing.get("db_pointer", {}).get("structure_db_id", "")),
            "path_entries": [],
        }
        fallback_best.update(self._flatten_match_score_v2(v2_breakdown))
        fallback_detail = {
            **fallback_best,
            "contains_anchor": True,
            "eligible": True,
            "existing_length": existing_length,
            "incoming_length": incoming_length,
            "stats": self._capture_structure_stats(existing),
        }
        return fallback_best, fallback_detail, created_structure

    @staticmethod
    def _is_numeric_attribute_unit(unit: dict) -> bool:
        if str(unit.get("unit_role", "")) != "attribute":
            return False
        if not str(unit.get("attribute_name", "")):
            return False
        value = unit.get("attribute_value")
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)):
            return True
        try:
            return str(value or "").strip() != "" and float(str(value).strip()) == float(str(value).strip())
        except Exception:
            return False

    def _find_numeric_atomic_structure_candidate(
        self,
        *,
        unit: dict,
        structure_store,
        pointer_index,
        cut_engine,
    ) -> tuple[dict | None, dict | None]:
        if not self._is_numeric_attribute_unit(unit):
            return None, None
        family = str(unit.get("attribute_name", ""))
        value = unit.get("attribute_value")
        buckets = pointer_index.resolve_numeric_buckets(
            attribute_name=family,
            value=value,
            create_if_missing=True,
            neighbor_count=2,
        )
        candidate_ids: list[str] = []
        seen_ids: set[str] = set()
        for bucket in buckets:
            for candidate_id in bucket.get("candidate_ids", []):
                candidate_text = str(candidate_id)
                if not candidate_text or candidate_text in seen_ids:
                    continue
                seen_ids.add(candidate_text)
                candidate_ids.append(candidate_text)
        best = None
        best_match = None
        best_key = None
        for candidate_id in candidate_ids:
            candidate = structure_store.get(candidate_id)
            if not candidate:
                continue
            candidate_profile = self._build_structure_profile(
                structure_obj=candidate,
                structure_store=structure_store,
                cut_engine=cut_engine,
            )
            candidate_units = list(candidate_profile.get("all_units", []))
            if not candidate_units:
                candidate_units = [
                    dict(item)
                    for group in candidate_profile.get("sequence_groups", [])
                    for item in group.get("units", [])
                    if isinstance(item, dict)
                ]
            if len(candidate_units) != 1:
                continue
            candidate_unit = candidate_units[0]
            if not self._is_numeric_attribute_unit(candidate_unit):
                continue
            if str(candidate_unit.get("attribute_name", "")) != family:
                continue
            numeric_match = pointer_index.describe_numeric_match(
                attribute_name=family,
                left_value=candidate_unit.get("attribute_value"),
                right_value=value,
            )
            if not numeric_match:
                continue
            candidate_key = (
                float(numeric_match.get("similarity", 0.0)),
                -float(numeric_match.get("distance", 0.0)),
                -float(candidate.get("stats", {}).get("base_weight", 0.0)),
            )
            if best_key is None or candidate_key > best_key:
                best_key = candidate_key
                best = candidate
                best_match = numeric_match
        return best, best_match

    def _get_or_create_atomic_structure_for_unit(
        self,
        *,
        unit: dict,
        focus_units: list[dict],
        competition_units: list[dict] | None,
        structure_store,
        pointer_index,
        cut_engine,
        trace_id: str,
        tick_id: str,
        parent_ids: list[str],
        source_packet_id: str,
        round_index: int,
    ) -> tuple[dict | None, dict | None, dict | None]:
        token = str(unit.get("token", ""))
        if not token:
            return None, None, None
        numeric_anchor_match = None
        existing = self._get_cached_atomic_structure(unit=unit, structure_store=structure_store)
        if existing is None:
            existing, numeric_anchor_match = self._find_numeric_atomic_structure_candidate(
                unit=unit,
                structure_store=structure_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
            )
            if existing is not None:
                self._put_cached_atomic_structure(unit=unit, structure_obj=existing)
        created_structure = None
        if existing is None:
            result = self._find_or_create_structure_from_units(
                units=[unit],
                structure_store=structure_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
                trace_id=trace_id,
                tick_id=tick_id,
                confidence=float(self._config.get("stimulus_anchor_seed_confidence", 0.9)),
                origin="stimulus_atomic_anchor_seed",
                origin_id=source_packet_id,
                parent_ids=parent_ids,
                ext={
                    "origin_round": round_index,
                    "source_packet_id": source_packet_id,
                    "origin_group_index": unit.get("group_index", 0),
                    "origin_source_type": unit.get("source_type", ""),
                    "kind": "atomic_anchor",
                    "relation_type": "atomic_anchor",
                },
            )
            existing = result["structure"]
            created_structure = existing if result.get("created") else None
            if existing is not None:
                self._put_cached_atomic_structure(unit=unit, structure_obj=existing)
        if existing is None:
            return None, None, created_structure

        focus_groups = self._units_to_groups(focus_units)
        group_pos = self._find_group_position(focus_groups, int(unit.get("group_index", 0)))
        residual_units = self._subtract_units(focus_units, [unit])
        existing_profile = self._build_structure_profile(
            structure_obj=existing,
            structure_store=structure_store,
            cut_engine=cut_engine,
        )
        existing_atomic_units = list(existing_profile.get("all_units", []))
        if not existing_atomic_units:
            existing_atomic_units = [
                dict(item)
                for group in existing_profile.get("sequence_groups", [])
                for item in group.get("units", [])
                if isinstance(item, dict)
            ]
        common_unit = dict(unit)
        match_mode = "anchor_atomic_fallback"
        if numeric_anchor_match and existing_atomic_units:
            common_unit = cut_engine._generalize_numeric_common_unit(
                existing_unit=existing_atomic_units[0],
                incoming_unit=unit,
                numeric_match=numeric_anchor_match,
            )
            match_mode = "anchor_numeric_bucket"
        common_profile = cut_engine.build_sequence_profile_from_groups(
            [
                {
                    "group_index": 0,
                    "source_type": unit.get("source_type", ""),
                    "origin_frame_id": unit.get("origin_frame_id", ""),
                    "source_group_index": group_pos,
                    "units": [common_unit],
                }
            ]
        )
        common_groups = list(common_profile.get("sequence_groups", []))
        common_group = common_groups[0] if common_groups else {
            "group_index": 0,
            "source_type": unit.get("source_type", ""),
            "origin_frame_id": unit.get("origin_frame_id", ""),
            "tokens": [common_unit.get("token", token)],
            "units": [common_unit],
        }
        common_part = {
            "common_tokens": list(common_group.get("tokens", [])) or [common_unit.get("token", token)],
            "common_length": 1,
            "common_group_count": 1,
            "matched_existing_unit_count": 1,
            "matched_incoming_unit_count": 1,
            "common_signature": common_profile.get("content_signature", "") or token,
            "common_display": common_profile.get("display_text", "") or token,
            "common_groups": [common_group],
            "matched_pairs": [
                {
                    "existing_group_index": 0,
                    "incoming_group_index": group_pos,
                    "common_tokens": list(common_group.get("tokens", [])) or [common_unit.get("token", token)],
                    "existing_unit_refs": [str(existing_atomic_units[0].get("unit_id", ""))] if existing_atomic_units else [],
                    "incoming_unit_refs": [str(unit.get("unit_id", ""))] if str(unit.get("unit_id", "")) else [],
                }
            ],
            "existing_range": [0, 1],
            "incoming_range": [group_pos, group_pos + 1],
            "matched_existing_group_indices": [0],
            "matched_incoming_group_indices": [group_pos],
            "residual_existing_groups": [],
            "residual_incoming_groups": self._units_to_groups(residual_units),
            "residual_existing_tokens": [],
            "residual_incoming_tokens": [item.get("token", "") for item in residual_units if item.get("token")],
            "residual_existing_signature": "",
            "residual_incoming_signature": cut_engine.sequence_groups_to_signature(self._units_to_groups(residual_units)),
        }
        numeric_similarity = float(numeric_anchor_match.get("similarity", 1.0)) if numeric_anchor_match else 1.0
        stimulus_match_ratio = self._energy_match_ratio(
            matched_units=[{**dict(unit), "match_similarity": numeric_similarity}],
            all_units=[
                dict(item)
                for item in (competition_units or focus_units)
                if isinstance(item, dict)
            ],
            fallback_numerator=1.0,
            fallback_denominator=max(
                1,
                len([item for item in (competition_units or focus_units) if str(item.get("token", ""))]),
            ),
        )
        match_score = self._compose_match_score(
            stimulus_match_ratio=stimulus_match_ratio,
            structure_match_ratio=numeric_similarity,
            attribute_anchor_only=str(unit.get("unit_role", "")) == "attribute",
        )
        exact_match = numeric_similarity >= 0.99999999
        existing_anchor_unit = dict(existing_atomic_units[0]) if existing_atomic_units else dict(common_unit)
        incoming_anchor_unit = dict(unit)
        v2_breakdown = self._build_match_score_v2_breakdown(
            base_score=match_score,
            matched_existing_units=[{**existing_anchor_unit, "match_similarity": numeric_similarity}],
            matched_incoming_units=[{**incoming_anchor_unit, "match_similarity": numeric_similarity}],
            bundle_constraints={"exact": exact_match, "existing_included": True, "incoming_included": True},
            full_structure_included=True,
            context_payload=existing,
        )
        blended_match_score = self._blend_v2_match_score(
            legacy_score=match_score,
            v2_score=float(v2_breakdown.get("score", match_score)),
        )
        fallback_best = {
            "structure_id": existing.get("id", ""),
            "display_text": existing.get("structure", {}).get("display_text", existing.get("id", "")),
            "grouped_display_text": self._format_runtime_group_texts(existing_profile.get("sequence_groups", [])),
            "exact_match": exact_match,
            "full_structure_included": True,
            "coverage_ratio": stimulus_match_ratio,
            "match_score": match_score,
            "match_score_legacy": match_score,
            "match_score_v2": round(float(v2_breakdown.get("score", 0.0)), 8),
            "competition_score": blended_match_score,
            "competition_score_legacy": round(float(match_score), 8),
            "competition_score_v2": round(float(v2_breakdown.get("score", 0.0)), 8),
            "weighted_rank_score": blended_match_score,
            "similarity_score": blended_match_score,
            "structure_match_ratio": 1.0,
            "stimulus_match_ratio": stimulus_match_ratio,
            "existing_length": 1,
            "runtime_weight": 1.0,
            "common_part": common_part,
            "incoming_range": list(common_part.get("incoming_range", [0, 0])),
            "match_mode": match_mode,
            "structure_signature": existing_profile.get("content_signature", token),
            "structure_db_id": str(existing.get("db_pointer", {}).get("structure_db_id", "")),
            "path_entries": [],
        }
        fallback_best.update(self._flatten_match_score_v2(v2_breakdown))
        fallback_detail = {
            **fallback_best,
            "contains_anchor": True,
            "eligible": True,
            "existing_length": 1,
            "incoming_length": len([item for item in focus_units if item.get("token")]),
            "stats": self._capture_structure_stats(existing),
        }
        return fallback_best, fallback_detail, created_structure

    def _find_or_create_extension_structure(
        self,
        *,
        full_units: list[dict],
        matched_structure_id: str,
        common_part: dict,
        structure_store,
        pointer_index,
        cut_engine,
        trace_id: str,
        tick_id: str,
        source_packet_id: str,
        round_index: int,
    ) -> dict | None:
        if not full_units:
            return None
        result = self._find_or_create_structure_from_units(
            units=full_units,
            structure_store=structure_store,
            pointer_index=pointer_index,
            cut_engine=cut_engine,
            trace_id=trace_id,
            tick_id=tick_id,
            confidence=float(self._config.get("stimulus_extension_confidence", 0.74)),
            origin="stimulus_extension_create",
            origin_id=source_packet_id,
            parent_ids=[matched_structure_id],
            ext={
                "origin_round": round_index,
                "source_packet_id": source_packet_id,
                "kind": "incoming_extension",
                "relation_type": "incoming_extension",
                "parent_structure_id": matched_structure_id,
                "common_signature": common_part.get("common_signature", ""),
                "residual_incoming_signature": common_part.get("residual_incoming_signature", ""),
            },
        )
        structure_obj = result["structure"]
        structure_id = structure_obj.get("id", "")
        if structure_id and structure_id != matched_structure_id:
            structure_store.add_diff_entry(
                matched_structure_id,
                target_id=structure_id,
                content_signature=structure_obj.get("structure", {}).get("content_signature", ""),
                base_weight=float(self._config.get("stimulus_extension_link_base_weight", 0.75)),
                residual_existing_signature="",
                residual_incoming_signature=common_part.get("residual_incoming_signature", ""),
                ext={
                    "linked_from_parent": matched_structure_id,
                    "relation_type": "incoming_extension",
                    "source_packet_id": source_packet_id,
                },
            )
            structure_db = structure_store.get_db_by_owner(matched_structure_id)
            if structure_db:
                self._maintenance.apply_structure_db_soft_limits(structure_db)
                structure_store.update_db(structure_db)
            self._register_atomic_extension_paths(
                full_units=full_units,
                matched_structure_id=matched_structure_id,
                target_structure=structure_obj,
                structure_store=structure_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
                source_packet_id=source_packet_id,
            )
        return result

    def _store_residual_context_for_match(
        self,
        *,
        owner_structure_id: str,
        current_groups: list[dict],
        current_profile: dict,
        covered_units: list[dict],
        matched_structure: dict,
        structure_store,
        pointer_index,
        cut_engine,
        trace_id: str,
        tick_id: str,
        source_packet_id: str,
        round_index: int,
        min_common_length: int,
        episodic_memory_id: str,
    ) -> dict | None:
        # 刺激级残差信息改为“owner 局部库 + raw residual entry + common structure”模型。
        # 这里不再走旧的 residual structure 递归树，而是始终基于“本轮当前刺激组”归一化。
        return self._store_owner_local_residual_context(
            owner_structure_id=owner_structure_id,
            current_groups=current_groups,
            current_profile=current_profile,
            covered_units=covered_units,
            matched_structure=matched_structure,
            structure_store=structure_store,
            pointer_index=pointer_index,
            cut_engine=cut_engine,
            trace_id=trace_id,
            tick_id=tick_id,
            source_packet_id=source_packet_id,
            round_index=round_index,
            min_common_length=min_common_length,
            episodic_memory_id=episodic_memory_id,
        )

    def _store_owner_local_residual_context(
        self,
        *,
        owner_structure_id: str,
        current_groups: list[dict],
        current_profile: dict,
        covered_units: list[dict],
        matched_structure: dict,
        structure_store,
        pointer_index,
        cut_engine,
        trace_id: str,
        tick_id: str,
        source_packet_id: str,
        round_index: int,
        min_common_length: int,
        episodic_memory_id: str,
    ) -> dict | None:
        del matched_structure
        owner_structure = structure_store.get(owner_structure_id)
        owner_db = structure_store.get_db_by_owner(owner_structure_id)
        if not owner_structure or not owner_db:
            return None

        owner_profile = self._build_structure_profile(
            structure_obj=owner_structure,
            structure_store=structure_store,
            cut_engine=cut_engine,
        )
        owner_placeholder = self._self_placeholder_token(owner_structure)
        canonical_profile = self._apply_grouped_display_to_profile(dict(current_profile or {}))
        residual_profile = self._build_relative_residual_profile_from_groups(
            full_groups=current_groups,
            covered_units=covered_units,
            owner_placeholder=owner_placeholder,
            cut_engine=cut_engine,
            origin_frame_id=f"{tick_id}:{round_index}:{owner_structure_id}",
            canonical_profile=canonical_profile,
        )
        if not residual_profile:
            return None
        if not self._profile_has_non_placeholder_tokens(residual_profile, placeholder_token=owner_placeholder):
            return None

        summary = {
            "written_index_count": 0,
            "cut_count": 0,
            "new_structure_ids": [],
            "common_structure": None,
            "residual_structure": None,
            "common_signature_counts": {},
        }
        self._normalize_owner_local_residual(
            owner_structure_id=owner_structure_id,
            owner_db=owner_db,
            owner_profile=owner_profile,
            owner_placeholder=owner_placeholder,
            residual_profile=residual_profile,
            structure_store=structure_store,
            pointer_index=pointer_index,
            cut_engine=cut_engine,
            trace_id=trace_id,
            tick_id=tick_id,
            source_packet_id=source_packet_id,
            round_index=round_index,
            min_common_length=max(1, int(min_common_length)),
            episodic_memory_id=episodic_memory_id,
            summary=summary,
            depth=0,
        )
        if (
            summary["written_index_count"] <= 0
            and summary["cut_count"] <= 0
            and not summary["new_structure_ids"]
            and not summary["common_structure"]
            and not summary["residual_structure"]
        ):
            return None
        self._maintenance.apply_structure_db_soft_limits(owner_db)
        structure_store.update_db(owner_db)
        summary["new_structure_ids"] = list(dict.fromkeys(summary["new_structure_ids"]))
        return summary

    def _normalize_owner_local_residual(
        self,
        *,
        owner_structure_id: str,
        owner_db: dict,
        owner_profile: dict,
        owner_placeholder: str,
        residual_profile: dict,
        structure_store,
        pointer_index,
        cut_engine,
        trace_id: str,
        tick_id: str,
        source_packet_id: str,
        round_index: int,
        min_common_length: int,
        episodic_memory_id: str,
        summary: dict,
        depth: int,
    ) -> None:
        if depth >= 12:
            return

        canonical_profile = self._apply_grouped_display_to_profile(
            self._canonicalize_profile(
                residual_profile,
                structure_store=structure_store,
                cut_engine=cut_engine,
            )
        )
        if not self._profile_has_non_placeholder_tokens(canonical_profile, placeholder_token=owner_placeholder):
            return

        local_items = self._list_owner_local_residual_items(
            owner_db=owner_db,
            owner_structure_id=owner_structure_id,
            structure_store=structure_store,
            cut_engine=cut_engine,
        )
        local_index = self._index_owner_local_residual_items(
            owner_structure_id=owner_structure_id,
            items=local_items,
            structure_store=structure_store,
        )
        now_ms = int(time.time() * 1000)

        canonical_signature = str(canonical_profile.get("content_signature", ""))
        raw_items = list(local_index.get("raw_items", []))
        common_items = list(local_index.get("common_items", []))
        if bool(self._config.get("stimulus_owner_local_residual_fuzzy_fast_reject_enabled", True)):
            canonical_unit_count = self._profile_unit_count(canonical_profile)
            raw_fuzzy_items = list(local_index.get("raw_by_unit_count", {}).get(canonical_unit_count, raw_items))
            common_fuzzy_items = list(local_index.get("common_by_unit_count", {}).get(canonical_unit_count, common_items))
            self._increment_runtime_metric(
                "owner_local_residual_fuzzy_unit_bucket_pruned_count",
                max(0, len(raw_items) - len(raw_fuzzy_items)) + max(0, len(common_items) - len(common_fuzzy_items)),
            )
        else:
            raw_fuzzy_items = raw_items
            common_fuzzy_items = common_items
        exact_raw_item = None
        if canonical_signature:
            exact_raw_item = local_index.get("raw_by_signature", {}).get(canonical_signature)
            if exact_raw_item is not None:
                self._increment_runtime_metric("owner_local_residual_raw_signature_hit_count")
        if exact_raw_item is None:
            exact_raw_item = next(
                (
                    item
                    for item in raw_fuzzy_items
                    if self._profiles_fuzzy_equivalent(
                        left_profile=item.get("canonical_profile", {}),
                        right_profile=canonical_profile,
                        cut_engine=cut_engine,
                    )
                ),
                None,
            )
        if exact_raw_item:
            self._reinforce_raw_residual_entry(
                entry=exact_raw_item["entry_ref"],
                residual_profile=residual_profile,
                canonical_profile=canonical_profile,
                episodic_memory_id=episodic_memory_id,
                round_index=round_index,
                source_packet_id=source_packet_id,
                structure_store=structure_store,
                cut_engine=cut_engine,
                now_ms=now_ms,
            )
            summary["written_index_count"] += 1
            if not summary.get("residual_structure"):
                summary["residual_structure"] = self._build_raw_residual_debug(
                    entry=exact_raw_item["entry_ref"],
                    created=False,
                    fallback_memory_id=episodic_memory_id,
                    structure_store=structure_store,
                    cut_engine=cut_engine,
                )
            return

        exact_common_item = None
        if canonical_signature:
            exact_common_item = local_index.get("common_by_signature", {}).get(canonical_signature)
            if exact_common_item is not None:
                self._increment_runtime_metric("owner_local_residual_common_signature_hit_count")
        if exact_common_item is None:
            exact_common_item = next(
                (
                    item
                    for item in common_fuzzy_items
                    if self._profiles_fuzzy_equivalent(
                        left_profile=item.get("profile", {}),
                        right_profile=canonical_profile,
                        cut_engine=cut_engine,
                    )
                ),
                None,
            )
        if exact_common_item:
            self._reinforce_common_structure_entry(
                entry=exact_common_item["entry_ref"],
                delta_profile=canonical_profile,
                episodic_memory_id=episodic_memory_id,
                round_index=round_index,
                source_packet_id=source_packet_id,
                now_ms=now_ms,
            )
            summary["written_index_count"] += 1
            if not summary.get("common_structure"):
                summary["common_structure"] = {
                    **self._build_structure_debug(exact_common_item.get("structure_obj", {})),
                    "created": False,
                    "relation_type": "residual_context_common",
                    "parent_structure_id": owner_structure_id,
                    "memory_id": episodic_memory_id,
                }
            return

        parent_candidate = self._find_parent_common_candidate(
            residual_profile=canonical_profile,
            common_items=common_items,
            cut_engine=cut_engine,
        )
        if parent_candidate:
            self._reinforce_common_structure_entry(
                entry=parent_candidate["entry_ref"],
                delta_profile=canonical_profile,
                episodic_memory_id=episodic_memory_id,
                round_index=round_index,
                source_packet_id=source_packet_id,
                now_ms=now_ms,
            )
            summary["written_index_count"] += 1
            if not summary.get("common_structure"):
                summary["common_structure"] = {
                    **self._build_structure_debug(parent_candidate.get("structure_obj", {})),
                    "created": False,
                    "relation_type": "residual_context_common",
                    "parent_structure_id": owner_structure_id,
                    "memory_id": episodic_memory_id,
                }
            child_structure = parent_candidate.get("structure_obj", {})
            child_structure_id = str(child_structure.get("id", ""))
            child_db = structure_store.get_db_by_owner(child_structure_id)
            if not child_db:
                return
            child_profile = self._build_descend_relative_profile_for_common(
                full_profile=canonical_profile,
                common_part=parent_candidate.get("common_part", {}),
                child_placeholder=self._self_placeholder_token(child_structure),
                cut_engine=cut_engine,
                origin_frame_id=f"{tick_id}:{round_index}:descend:{child_structure_id}",
            )
            if not child_profile:
                return
            self._normalize_owner_local_residual(
                owner_structure_id=child_structure_id,
                owner_db=child_db,
                owner_profile=self._build_structure_profile(
                    structure_obj=child_structure,
                    structure_store=structure_store,
                    cut_engine=cut_engine,
                ),
                owner_placeholder=self._self_placeholder_token(child_structure),
                residual_profile=child_profile,
                structure_store=structure_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
                trace_id=trace_id,
                tick_id=tick_id,
                source_packet_id=source_packet_id,
                round_index=round_index,
                min_common_length=min_common_length,
                episodic_memory_id=episodic_memory_id,
                summary=summary,
                depth=depth + 1,
            )
            self._maintenance.apply_structure_db_soft_limits(child_db)
            structure_store.update_db(child_db)
            return

        overlap_candidate = self._find_best_raw_overlap_candidate(
            residual_profile=canonical_profile,
            raw_items=raw_items,
            owner_profile=owner_profile,
            cut_engine=cut_engine,
            min_common_length=max(1, int(min_common_length)),
        )
        if overlap_candidate:
            common_part = overlap_candidate.get("common_part", {})
            common_profile = overlap_candidate.get("common_profile", {}) or self._apply_grouped_display_to_profile(
                cut_engine.build_sequence_profile_from_groups(list(common_part.get("common_groups", [])))
            )
        if overlap_candidate:
            common_part = overlap_candidate.get("common_part", {})
            common_profile = overlap_candidate.get("common_profile", {}) or common_profile
            common_signature = str(common_profile.get("content_signature", "") or common_profile.get("display_text", "") or "").strip()
            common_signature_counts = summary.get("common_signature_counts", {}) if isinstance(summary.get("common_signature_counts", {}), dict) else {}
            common_seen = int(common_signature_counts.get(common_signature, 0) or 0) if common_signature else 0
            context_free_common_identity = bool(
                self._config.get("stimulus_residual_common_context_free_identity_enabled", True)
            )
            common_result = None
            common_structure = None
            if not self._allow_long_profile_seed(
                common_profile,
                soft_max_units_key="stimulus_residual_common_soft_max_units",
                min_avg_energy_key="stimulus_residual_common_min_avg_unit_energy_for_long",
            ):
                overlap_candidate = None
            elif common_seen > 0:
                overlap_candidate = None
            else:
                common_result = self._find_or_create_structure_from_profile(
                    profile=common_profile,
                    structure_store=structure_store,
                    pointer_index=pointer_index,
                    cut_engine=cut_engine,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    confidence=float(self._config.get("stimulus_residual_common_confidence", 0.78)),
                    origin="stimulus_residual_common",
                    origin_id=source_packet_id,
                    parent_ids=[] if context_free_common_identity else [owner_structure_id],
                    base_weight=self._weight.update_base_weight_by_support(
                        current_base_weight=overlap_candidate.get("base_weight", 0.0),
                        reality_support=self._profile_reality_energy(canonical_profile),
                        virtual_support=0.0,
                        match_score=1.0,
                    ),
                    ext={
                        "kind": "residual_context_common",
                        "relation_type": "residual_context_common",
                        "owner_structure_id": owner_structure_id,
                        "provenance_owner_structure_id": owner_structure_id,
                        "source_packet_id": source_packet_id,
                        "identity_context_free": context_free_common_identity,
                    },
                    require_context_free=context_free_common_identity,
                )
                common_structure = common_result["structure"]
                if common_signature:
                    common_signature_counts[common_signature] = common_seen + 1
                    summary["common_signature_counts"] = common_signature_counts
            if overlap_candidate is None or not isinstance(common_result, dict) or not isinstance(common_structure, dict):
                return
            else:
                common_structure_id = str(common_structure.get("id", ""))
                if common_result.get("created") and common_structure_id:
                    summary["new_structure_ids"].append(common_structure_id)
                if not summary.get("common_structure"):
                    summary["common_structure"] = {
                        **self._build_structure_debug(common_structure),
                        "created": bool(common_result.get("created")),
                        "relation_type": "residual_context_common",
                        "parent_structure_id": owner_structure_id,
                    "memory_id": episodic_memory_id,
                }

            removed_count = self._remove_owner_diff_entry(
                owner_db=owner_db,
                entry_id=str(overlap_candidate.get("entry_id", "")),
            )
            if removed_count > 0:
                self._invalidate_owner_local_residual_cache(owner_structure_id=owner_structure_id)
            summary["cut_count"] += max(1, removed_count)
            common_entry = self._append_or_reinforce_common_structure_entry(
                owner_structure_id=owner_structure_id,
                owner_db=owner_db,
                common_structure=common_structure,
                common_profile=common_profile,
                structure_store=structure_store,
                base_weight=self._weight.update_base_weight_by_support(
                    current_base_weight=overlap_candidate.get("base_weight", 0.0),
                    reality_support=self._profile_reality_energy(canonical_profile),
                    virtual_support=0.0,
                    match_score=1.0,
                ),
                source_packet_id=source_packet_id,
                round_index=round_index,
                episodic_memory_id=episodic_memory_id,
                now_ms=now_ms,
            )
            summary["written_index_count"] += int(bool(common_entry))

            common_db = structure_store.get_db_by_owner(common_structure_id)
            if not common_db:
                return
            common_placeholder = self._self_placeholder_token(common_structure)
            common_owner_profile = self._build_structure_profile(
                structure_obj=common_structure,
                structure_store=structure_store,
                cut_engine=cut_engine,
            )
            existing_child_profile = self._build_descend_relative_profile_for_common(
                full_profile=overlap_candidate.get("canonical_profile", {}),
                common_part=common_part,
                child_placeholder=common_placeholder,
                cut_engine=cut_engine,
                origin_frame_id=f"{tick_id}:{round_index}:existing:{common_structure_id}",
            )
            incoming_child_profile = self._build_descend_relative_profile_for_common(
                full_profile=canonical_profile,
                common_part=common_part,
                child_placeholder=common_placeholder,
                cut_engine=cut_engine,
                origin_frame_id=f"{tick_id}:{round_index}:incoming:{common_structure_id}",
            )
            if incoming_child_profile:
                # Prefer surfacing the current tick branch in debug output.
                # The user-facing "new residual" should describe the current stimulus group
                # written this round, not the historical branch migrated from the old raw item.
                self._normalize_owner_local_residual(
                    owner_structure_id=common_structure_id,
                    owner_db=common_db,
                    owner_profile=common_owner_profile,
                    owner_placeholder=common_placeholder,
                    residual_profile=incoming_child_profile,
                    structure_store=structure_store,
                    pointer_index=pointer_index,
                    cut_engine=cut_engine,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    source_packet_id=source_packet_id,
                    round_index=round_index,
                    min_common_length=min_common_length,
                    episodic_memory_id=episodic_memory_id,
                    summary=summary,
                    depth=depth + 1,
                )
            if existing_child_profile:
                self._normalize_owner_local_residual(
                    owner_structure_id=common_structure_id,
                    owner_db=common_db,
                    owner_profile=common_owner_profile,
                    owner_placeholder=common_placeholder,
                    residual_profile=existing_child_profile,
                    structure_store=structure_store,
                    pointer_index=pointer_index,
                    cut_engine=cut_engine,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    source_packet_id=source_packet_id,
                    round_index=round_index,
                    min_common_length=min_common_length,
                    episodic_memory_id=episodic_memory_id,
                    summary=summary,
                    depth=depth + 1,
                )
            self._maintenance.apply_structure_db_soft_limits(common_db)
            structure_store.update_db(common_db)
            return

        created_entry = self._append_raw_residual_entry(
            owner_db=owner_db,
            residual_profile=residual_profile,
            canonical_profile=canonical_profile,
            episodic_memory_id=episodic_memory_id,
            round_index=round_index,
            source_packet_id=source_packet_id,
        )
        summary["written_index_count"] += 1
        if not summary.get("residual_structure"):
            summary["residual_structure"] = self._build_raw_residual_debug(
                entry=created_entry,
                created=True,
                fallback_memory_id=episodic_memory_id,
                structure_store=structure_store,
                cut_engine=cut_engine,
            )

    def _build_relative_residual_profile_from_groups(
        self,
        *,
        full_groups: list[dict],
        covered_units: list[dict],
        owner_placeholder: str,
        cut_engine,
        origin_frame_id: str,
        canonical_profile: dict,
    ) -> dict | None:
        covered_ids = {str(unit.get("unit_id", "")) for unit in covered_units if str(unit.get("unit_id", ""))}
        if not covered_ids:
            return None
        residual_groups = self._build_relative_groups_with_placeholder(
            full_groups=full_groups,
            matched_unit_ids=covered_ids,
            placeholder_token=owner_placeholder,
            origin_frame_id=origin_frame_id,
        )
        if not residual_groups:
            return None
        raw_profile = self._apply_grouped_display_to_profile(
            cut_engine.build_sequence_profile_from_groups(residual_groups)
        )
        canonical = dict(canonical_profile or {})
        return self._attach_explicit_canonical_profile(raw_profile, canonical_profile=canonical)

    def _build_descend_relative_profile_for_common(
        self,
        *,
        full_profile: dict,
        common_part: dict,
        child_placeholder: str,
        cut_engine,
        origin_frame_id: str,
    ) -> dict | None:
        full_groups = list(full_profile.get("sequence_groups", []))
        if not full_groups:
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
        full_unit_ids = {
            str(unit.get("unit_id", ""))
            for group in full_groups
            for unit in group.get("units", [])
            if isinstance(unit, dict) and str(unit.get("unit_id", ""))
        }
        existing_overlap = len(full_unit_ids & existing_refs)
        incoming_overlap = len(full_unit_ids & incoming_refs)
        matched_refs = incoming_refs if incoming_overlap >= existing_overlap else existing_refs
        if not matched_refs:
            return None
        child_groups = self._build_relative_groups_with_placeholder(
            full_groups=full_groups,
            matched_unit_ids=matched_refs,
            placeholder_token=child_placeholder,
            origin_frame_id=origin_frame_id,
        )
        if not child_groups:
            return None
        child_profile = self._apply_grouped_display_to_profile(
            cut_engine.build_sequence_profile_from_groups(child_groups)
        )
        if not self._profile_has_non_placeholder_tokens(child_profile, placeholder_token=child_placeholder):
            return None
        return self._attach_explicit_canonical_profile(
            child_profile,
            canonical_profile=dict(full_profile or {}),
        )

    def _build_relative_groups_with_placeholder(
        self,
        *,
        full_groups: list[dict],
        matched_unit_ids: set[str],
        placeholder_token: str,
        origin_frame_id: str,
    ) -> list[dict]:
        if not matched_unit_ids:
            return []
        groups: list[dict] = []
        placeholder_inserted = False
        for group in full_groups:
            if not isinstance(group, dict):
                continue
            template_units = [
                unit
                for unit in group.get("units", [])
                if isinstance(unit, dict)
            ]
            if not template_units:
                continue
            next_units: list[dict] = []
            for unit in template_units:
                unit_id = str(unit.get("unit_id", ""))
                if unit_id in matched_unit_ids:
                    if not placeholder_inserted:
                        next_units.append(
                            self._make_placeholder_unit_for_relative_profile(
                                placeholder_token=placeholder_token,
                                template_unit=unit,
                                origin_frame_id=origin_frame_id,
                            )
                        )
                        placeholder_inserted = True
                    continue
                copied_unit = dict(unit)
                copied_unit["origin_frame_id"] = str(
                    group.get("origin_frame_id", unit.get("origin_frame_id", origin_frame_id))
                )
                copied_unit["source_type"] = str(group.get("source_type", unit.get("source_type", "")))
                next_units.append(copied_unit)
            if not next_units:
                continue
            groups.append(
                {
                    "group_index": len(groups),
                    "source_type": str(group.get("source_type", "")),
                    "origin_frame_id": str(group.get("origin_frame_id", origin_frame_id)),
                    "source_group_index": int(group.get("source_group_index", group.get("group_index", len(groups)))),
                    "source_sequence_index": int(group.get("source_sequence_index", 0)),
                    "units": next_units,
                }
            )
        return groups if placeholder_inserted else []

    @staticmethod
    def _make_placeholder_unit_for_relative_profile(
        *,
        placeholder_token: str,
        template_unit: dict,
        origin_frame_id: str,
    ) -> dict:
        return {
            "unit_id": f"placeholder::{placeholder_token}::{template_unit.get('unit_id', '')}",
            "object_type": "sa",
            "token": placeholder_token,
            "display_text": placeholder_token,
            "unit_role": "placeholder",
            "unit_signature": f"P:{placeholder_token}",
            "sequence_index": int(template_unit.get("sequence_index", 0)),
            "group_index": int(template_unit.get("group_index", 0)),
            "source_group_index": int(template_unit.get("source_group_index", template_unit.get("group_index", 0))),
            "source_type": str(template_unit.get("source_type", "")),
            "origin_frame_id": str(origin_frame_id),
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

    def _list_owner_local_residual_items(
        self,
        *,
        owner_db: dict,
        owner_structure_id: str,
        structure_store,
        cut_engine,
    ) -> list[dict]:
        cache = None
        cache_version = 0
        owner_cache_key = str(owner_structure_id or owner_db.get("owner_structure_id", "") or "")
        if isinstance(self._runtime_cache, dict):
            cache = self._runtime_cache.setdefault("owner_local_residual_items", {})
            version_map = self._runtime_cache.setdefault("owner_local_residual_versions", {})
            try:
                cache_version = int(version_map.get(owner_cache_key, 0) or 0)
            except Exception:
                cache_version = 0
        if isinstance(cache, dict) and owner_cache_key:
            cached_record = cache.get(owner_cache_key)
            if isinstance(cached_record, dict):
                try:
                    cached_version = int(cached_record.get("version", -1))
                except Exception:
                    cached_version = -1
                cached_items = cached_record.get("items", [])
                if cached_version == cache_version and isinstance(cached_items, list):
                    self._increment_runtime_metric("owner_local_residual_list_cache_hit_count")
                    return cached_items

        items = []
        for entry in owner_db.get("diff_table", []):
            if entry.get("entry_type") == "raw_residual":
                items.append(
                    self._build_owner_raw_residual_local_item(
                        entry=entry,
                        structure_store=structure_store,
                        cut_engine=cut_engine,
                    )
                )
                continue
            if entry.get("entry_type", "structure_ref") != "structure_ref":
                continue
            relation_type = str(entry.get("ext", {}).get("relation_type", ""))
            if relation_type != "residual_context_common":
                continue
            target_structure, _ = self._resolve_diff_target(entry, structure_store)
            if not target_structure:
                continue
            items.append(
                {
                    "item_kind": "common_structure",
                    "entry_ref": entry,
                    "entry_id": entry.get("entry_id", ""),
                    "structure_id": target_structure.get("id", ""),
                    "structure_obj": target_structure,
                    "profile": self._build_structure_profile(
                        structure_obj=target_structure,
                        structure_store=structure_store,
                        cut_engine=cut_engine,
                    ),
                    "base_weight": float(entry.get("base_weight", 0.0)),
                    "entry_runtime_weight": self._weight.entry_runtime_weight(entry),
                    "owner_structure_id": owner_structure_id,
                }
            )
        items.sort(
            key=lambda item: (
                -float(item.get("entry_runtime_weight", 0.0)),
                -float(item.get("base_weight", 0.0)),
                str(item.get("entry_id", "")),
            )
        )
        if isinstance(cache, dict) and owner_cache_key:
            cache[owner_cache_key] = {
                "version": cache_version,
                "items": items,
            }
        return items

    def _build_owner_raw_residual_local_item(
        self,
        *,
        entry: dict,
        structure_store,
        cut_engine,
        entry_runtime_weight: float | None = None,
    ) -> dict:
        profiles = self._ensure_raw_residual_entry_profiles(
            entry=entry,
            structure_store=structure_store,
            cut_engine=cut_engine,
            include_raw=False,
        )
        if entry_runtime_weight is None:
            entry_runtime_weight = self._weight.entry_runtime_weight(entry)
        return {
            "item_kind": "raw_residual",
            "entry_ref": entry,
            "entry_id": entry.get("entry_id", ""),
            "signature": entry.get("canonical_content_signature", ""),
            "profile": {},
            "canonical_profile": profiles.get("canonical_profile", {}),
            "base_weight": float(entry.get("base_weight", 0.0)),
            "entry_runtime_weight": float(entry_runtime_weight),
        }

    def _list_owner_shadow_raw_residual_items(
        self,
        *,
        owner_db: dict,
        structure_store,
        cut_engine,
        max_candidates: int,
        tick_id: str = "",
    ) -> tuple[int, list[dict]]:
        owner_structure_id = str(owner_db.get("owner_structure_id", "") or "")
        diff_source, budget_debug = build_owner_runtime_candidate_view(
            entries=owner_db.get("diff_table", []),
            config=self._config,
            owner_structure_id=owner_structure_id,
            path_kind="stimulus_shadow_raw_residual",
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
        ranked_entries: list[tuple[float, float, str, dict]] = []
        for entry in diff_source:
            if not isinstance(entry, dict) or entry.get("entry_type") != "raw_residual":
                continue
            entry_runtime_weight = float(self._weight.entry_runtime_weight(entry) or 0.0)
            base_weight = float(entry.get("base_weight", 0.0) or 0.0)
            ranked_entries.append((entry_runtime_weight, base_weight, str(entry.get("entry_id", "")), entry))
        ranked_entries.sort(
            key=lambda item: (
                -float(item[0]),
                -float(item[1]),
                str(item[2]),
            )
        )
        raw_shadow_count = len(ranked_entries)
        if max_candidates > 0 and raw_shadow_count > max_candidates:
            ranked_entries = ranked_entries[:max_candidates]
        items = [
            self._build_owner_raw_residual_local_item(
                entry=entry,
                structure_store=structure_store,
                cut_engine=cut_engine,
                entry_runtime_weight=entry_runtime_weight,
            )
            for entry_runtime_weight, _, _, entry in ranked_entries
        ]
        return raw_shadow_count, items

    def _owner_local_residual_items_signature(self, items: list[dict]) -> tuple[Any, ...]:
        signatures: list[tuple[Any, ...]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            entry = item.get("entry_ref", {}) if isinstance(item.get("entry_ref", {}), dict) else {}
            entry_id = str(item.get("entry_id", "") or entry.get("entry_id", "") or "")
            try:
                last_updated_at = int(entry.get("last_updated_at", entry.get("last_matched_at", 0)) or 0)
            except Exception:
                last_updated_at = 0
            signatures.append(
                (
                    str(item.get("item_kind", "") or ""),
                    entry_id,
                    str(item.get("signature", "") or item.get("profile", {}).get("content_signature", "") or item.get("canonical_profile", {}).get("content_signature", "") or ""),
                    str(item.get("structure_id", "") or ""),
                    round(float(item.get("base_weight", 0.0) or 0.0), 8),
                    round(float(item.get("entry_runtime_weight", 0.0) or 0.0), 8),
                    last_updated_at,
                )
            )
        return tuple(signatures)

    def _index_owner_local_residual_items(self, *, owner_structure_id: str, items: list[dict], structure_store=None) -> dict:
        owner_cache_key = str(owner_structure_id or "")
        items_signature: tuple[Any, ...] | None = None
        if (
            owner_cache_key
            and bool(self._config.get("stimulus_owner_local_residual_index_cache_enabled", True))
            and isinstance(self._runtime_cache, dict)
        ):
            cache = self._runtime_cache.setdefault("owner_local_residual_indices", {})
            if isinstance(cache, dict):
                cached = cache.get(owner_cache_key)
                items_ref_id = id(items)
                if (
                    isinstance(cached, dict)
                    and int(cached.get("items_ref_id", -1) or -1) == items_ref_id
                    and isinstance(cached.get("index"), dict)
                ):
                    self._increment_runtime_metric("owner_local_residual_index_cache_hit_count")
                    return cached["index"]
        if (
            owner_cache_key
            and structure_store is not None
            and bool(self._config.get("stimulus_owner_local_residual_shared_index_cache_enabled", True))
            and hasattr(structure_store, "get_shared_runtime_cache_entry")
        ):
            items_signature = self._owner_local_residual_items_signature(items)
            shared_cache_key = ("owner_local_residual_index", owner_cache_key, items_signature)
            shared_cached = structure_store.get_shared_runtime_cache_entry(
                "stimulus_owner_local_residual_indices",
                shared_cache_key,
            )
            if isinstance(shared_cached, dict):
                self._increment_runtime_metric("owner_local_residual_shared_index_cache_hit_count")
                if isinstance(self._runtime_cache, dict):
                    cache = self._runtime_cache.setdefault("owner_local_residual_indices", {})
                    if isinstance(cache, dict):
                        cache[owner_cache_key] = {"items_ref_id": id(items), "index": shared_cached}
                return shared_cached
        raw_items: list[dict] = []
        common_items: list[dict] = []
        raw_by_signature: dict[str, dict] = {}
        common_by_signature: dict[str, dict] = {}
        raw_by_unit_count: dict[int, list[dict]] = {}
        common_by_unit_count: dict[int, list[dict]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            item_kind = str(item.get("item_kind", "") or "")
            if item_kind == "raw_residual":
                raw_items.append(item)
                raw_by_unit_count.setdefault(self._profile_unit_count(item.get("canonical_profile", {})), []).append(item)
                signature = str(item.get("signature", "") or item.get("canonical_profile", {}).get("content_signature", "") or "")
                if signature and signature not in raw_by_signature:
                    raw_by_signature[signature] = item
                continue
            if item_kind == "common_structure":
                common_items.append(item)
                common_by_unit_count.setdefault(self._profile_unit_count(item.get("profile", {})), []).append(item)
                signature = str(item.get("profile", {}).get("content_signature", "") or "")
                if signature and signature not in common_by_signature:
                    common_by_signature[signature] = item
        index = {
            "owner_structure_id": str(owner_structure_id or ""),
            "raw_items": raw_items,
            "common_items": common_items,
            "raw_by_signature": raw_by_signature,
            "common_by_signature": common_by_signature,
            "raw_by_unit_count": raw_by_unit_count,
            "common_by_unit_count": common_by_unit_count,
        }
        self._increment_runtime_metric("owner_local_residual_index_build_count")
        if (
            owner_cache_key
            and bool(self._config.get("stimulus_owner_local_residual_index_cache_enabled", True))
            and isinstance(self._runtime_cache, dict)
        ):
            cache = self._runtime_cache.setdefault("owner_local_residual_indices", {})
            if isinstance(cache, dict):
                cache[owner_cache_key] = {"items_ref_id": id(items), "index": index}
        if (
            owner_cache_key
            and structure_store is not None
            and bool(self._config.get("stimulus_owner_local_residual_shared_index_cache_enabled", True))
            and hasattr(structure_store, "set_shared_runtime_cache_entry")
        ):
            if items_signature is None:
                items_signature = self._owner_local_residual_items_signature(items)
            structure_store.set_shared_runtime_cache_entry(
                "stimulus_owner_local_residual_indices",
                ("owner_local_residual_index", owner_cache_key, items_signature),
                index,
            )
        return index

    def _invalidate_owner_local_residual_cache(self, *, owner_structure_id: str) -> None:
        owner_cache_key = str(owner_structure_id or "")
        if not owner_cache_key or not isinstance(self._runtime_cache, dict):
            return
        version_map = self._runtime_cache.setdefault("owner_local_residual_versions", {})
        try:
            version_map[owner_cache_key] = int(version_map.get(owner_cache_key, 0) or 0) + 1
        except Exception:
            version_map[owner_cache_key] = 1
        cache = self._runtime_cache.get("owner_local_residual_items")
        if isinstance(cache, dict):
            cache.pop(owner_cache_key, None)
        index_cache = self._runtime_cache.get("owner_local_residual_indices")
        if isinstance(index_cache, dict):
            index_cache.pop(owner_cache_key, None)
        presence_cache = self._runtime_cache.get("anchor_owner_residual_presence")
        if isinstance(presence_cache, dict):
            presence_cache.pop(owner_cache_key, None)

    def _build_owner_local_residual_cache_key(
        self,
        *,
        owner_db: dict,
        owner_structure_id: str,
        structure_store,
    ) -> tuple[Any, ...]:
        relevant_entries: list[tuple[Any, ...]] = []
        for raw_entry in owner_db.get("diff_table", []):
            if not isinstance(raw_entry, dict):
                continue
            entry_type = str(raw_entry.get("entry_type", "structure_ref") or "structure_ref")
            base_weight = round(float(raw_entry.get("base_weight", 0.0) or 0.0), 8)
            recent_gain = round(float(raw_entry.get("recent_gain", 1.0) or 1.0), 8)
            fatigue = round(float(raw_entry.get("fatigue", 0.0) or 0.0), 8)
            last_updated_at = int(raw_entry.get("last_updated_at", raw_entry.get("last_matched_at", 0)) or 0)
            entry_id = str(raw_entry.get("entry_id", "") or "")
            if entry_type == "raw_residual":
                relevant_entries.append(
                    (
                        "raw_residual",
                        entry_id,
                        str(raw_entry.get("canonical_content_signature", "") or raw_entry.get("content_signature", "")),
                        last_updated_at,
                        base_weight,
                        recent_gain,
                        fatigue,
                    )
                )
                continue
            if entry_type != "structure_ref":
                continue
            relation_type = str(raw_entry.get("ext", {}).get("relation_type", "") or "")
            if relation_type != "residual_context_common":
                continue
            target_id = str(raw_entry.get("target_id", "") or "")
            target_signature = ""
            if target_id:
                target_structure = structure_store.get(target_id)
                if isinstance(target_structure, dict):
                    target_signature = str(target_structure.get("structure", {}).get("content_signature", "") or "")
            relevant_entries.append(
                (
                    "common_structure",
                    entry_id,
                    target_id,
                    target_signature,
                    last_updated_at,
                    base_weight,
                    recent_gain,
                    fatigue,
                )
            )
        return (str(owner_structure_id or ""), tuple(relevant_entries))

    def _find_parent_common_candidate(
        self,
        *,
        residual_profile: dict,
        common_items: list[dict],
        cut_engine,
    ) -> dict | None:
        best = None
        residual_unit_count = max(0, self._profile_unit_count(residual_profile))
        for item in common_items:
            existing_profile = item.get("profile", {})
            existing_unit_count = max(0, self._profile_unit_count(existing_profile))
            if existing_unit_count <= 0 or existing_unit_count > residual_unit_count:
                continue
            if self._profile_strict_overlap_upper_bound(existing_profile, residual_profile) < existing_unit_count:
                self._increment_runtime_metric("owner_local_residual_common_overlap_fast_reject_count")
                continue
            common_part = cut_engine.maximum_common_part(
                existing_profile.get("sequence_groups", []),
                residual_profile.get("sequence_groups", []),
            )
            if common_part.get("residual_existing_signature", ""):
                continue
            if int(common_part.get("matched_existing_unit_count", 0)) < max(1, existing_unit_count):
                continue
            if self._profiles_fuzzy_equivalent(
                left_profile=existing_profile,
                right_profile=residual_profile,
                cut_engine=cut_engine,
                common_part=common_part,
            ):
                continue
            candidate_key = (
                self._profile_unit_count(existing_profile),
                float(item.get("entry_runtime_weight", 0.0)),
            )
            current_key = (
                self._profile_unit_count(best.get("profile", {})),
                float(best.get("entry_runtime_weight", 0.0)),
            ) if best else None
            if best is None or candidate_key > current_key:
                best = {**item, "common_part": common_part}
        return best

    def _find_best_raw_overlap_candidate(
        self,
        *,
        residual_profile: dict,
        raw_items: list[dict],
        owner_profile: dict,
        cut_engine,
        min_common_length: int,
    ) -> dict | None:
        best = None
        residual_unit_count = max(0, self._profile_unit_count(residual_profile))
        min_common_length = max(1, int(min_common_length))
        for item in raw_items:
            existing_profile = item.get("canonical_profile", {})
            existing_unit_count = max(0, self._profile_unit_count(existing_profile))
            if existing_unit_count <= 0 or min(existing_unit_count, residual_unit_count) < min_common_length:
                continue
            if self._profile_strict_overlap_upper_bound(existing_profile, residual_profile) < min_common_length:
                self._increment_runtime_metric("owner_local_residual_common_overlap_fast_reject_count")
                continue
            common_part = cut_engine.maximum_common_part(
                existing_profile.get("sequence_groups", []),
                residual_profile.get("sequence_groups", []),
            )
            common_signature = str(common_part.get("common_signature", ""))
            if not common_signature:
                continue
            if int(common_part.get("common_length", 0)) < min_common_length:
                continue
            validated_common = self._validate_owner_overlap_common_part(
                common_part=common_part,
                owner_profile=owner_profile,
                cut_engine=cut_engine,
            )
            if not validated_common:
                continue
            if self._profiles_fuzzy_equivalent(
                left_profile=existing_profile,
                right_profile=residual_profile,
                cut_engine=cut_engine,
                common_part=common_part,
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
                    "common_profile": validated_common.get("common_profile", {}),
                }
        return best

    def _ensure_raw_residual_entry_schema(self, entry: dict) -> None:
        now_ms = int(time.time() * 1000)
        entry.setdefault("entry_id", next_id("srr"))
        entry.setdefault("entry_type", "raw_residual")
        entry.setdefault("target_id", "")
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
        entry.setdefault("memory_refs", [])
        entry.setdefault("ext", {})
        entry["ext"] = merge_context_metadata(entry.get("ext", {}))
        entry["ext"] = merge_residual_metadata(
            entry["ext"],
            residual_origin_entry_id=entry.get("entry_id", ""),
        )

    def _profile_from_stored_groups(self, groups: list[dict], *, cut_engine, ext: dict | None = None) -> dict:
        profile = self._apply_grouped_display_to_profile(
            cut_engine.build_sequence_profile_from_groups(list(groups or []))
        )
        merged_ext = dict(profile.get("ext", {}))
        merged_ext.update(ext or {})
        profile["ext"] = merged_ext
        return profile

    def _ensure_raw_residual_entry_profiles(self, *, entry: dict, structure_store, cut_engine, include_raw: bool = True) -> dict:
        self._ensure_raw_residual_entry_schema(entry)
        cache = None
        if isinstance(self._runtime_cache, dict):
            cache = self._runtime_cache.get("raw_residual_entry_profiles")
        entry_id = str(entry.get("entry_id", ""))
        entry_updated_at = int(entry.get("last_updated_at", 0) or 0)
        canonical_signature = str(
            entry.get("canonical_content_signature", "")
            or entry.get("content_signature", "")
            or ""
        )
        cache_key = (entry_id, entry_updated_at, canonical_signature, int(bool(include_raw)))
        if isinstance(cache, dict) and entry_id and cache_key in cache:
            return cache[cache_key]
        shared_cache_key = ("raw_residual_entry_profiles",) + cache_key
        shared_cached = None
        if hasattr(structure_store, "get_shared_runtime_cache_entry"):
            shared_cached = structure_store.get_shared_runtime_cache_entry(
                "stimulus_raw_residual_entry_profiles",
                shared_cache_key,
            )
        if isinstance(shared_cached, dict):
            if isinstance(cache, dict) and entry_id:
                cache[cache_key] = shared_cached
            return shared_cached

        raw_profile = {}
        raw_profile_built = False
        canonical_groups = list(entry.get("canonical_sequence_groups", []))
        if canonical_groups:
            canonical_profile = self._profile_from_stored_groups(
                canonical_groups,
                cut_engine=cut_engine,
                ext={"kind": "stimulus_raw_residual_canonical"},
            )
        else:
            raw_profile = self._profile_from_stored_groups(
                entry.get("sequence_groups", []),
                cut_engine=cut_engine,
                ext={"kind": "stimulus_raw_residual"},
            )
            raw_profile_built = True
            canonical_profile = self._apply_grouped_display_to_profile(
                self._canonicalize_profile(
                    raw_profile,
                    structure_store=structure_store,
                    cut_engine=cut_engine,
                )
            )
            entry["canonical_content_signature"] = canonical_profile.get("content_signature", "")
            entry["canonical_display_text"] = canonical_profile.get("display_text", "")
            entry["canonical_flat_tokens"] = list(canonical_profile.get("flat_tokens", []))
            entry["canonical_sequence_groups"] = list(canonical_profile.get("sequence_groups", []))
        if include_raw and not raw_profile_built:
            raw_profile = self._profile_from_stored_groups(
                entry.get("sequence_groups", []),
                cut_engine=cut_engine,
                ext={"kind": "stimulus_raw_residual"},
            )
        profiles = {"raw_profile": raw_profile, "canonical_profile": canonical_profile}
        if isinstance(cache, dict) and entry_id:
            cache[cache_key] = profiles
        if hasattr(structure_store, "set_shared_runtime_cache_entry"):
            structure_store.set_shared_runtime_cache_entry(
                "stimulus_raw_residual_entry_profiles",
                shared_cache_key,
                profiles,
            )
        return profiles

    def _append_raw_residual_entry(
        self,
        *,
        owner_db: dict,
        residual_profile: dict,
        canonical_profile: dict,
        episodic_memory_id: str,
        round_index: int,
        source_packet_id: str,
    ) -> dict:
        er, ev = self._residual_profile_energy(canonical_profile)
        owner_structure_id = str(owner_db.get("owner_structure_id", "") or "")
        entry_id = next_id("srr")
        entry_ext = merge_context_metadata(
            {
                "relation_type": "stimulus_raw_residual",
                "source_packet_id": source_packet_id,
                "round_index": round_index,
                "source_em_id": episodic_memory_id,
                "source_memory_created_at": int(time.time() * 1000),
            },
            context_ref_object_id=owner_structure_id,
            context_ref_object_type="st",
            context_owner_structure_id=owner_structure_id,
            parent_ids=[owner_structure_id] if owner_structure_id else [],
        )
        entry_ext = merge_residual_metadata(
            entry_ext,
            residual_origin_kind="stimulus_raw_residual",
            residual_origin_entry_id=entry_id,
        )
        entry = {
            "entry_id": entry_id,
            "entry_type": "raw_residual",
            "target_id": "",
            "content_signature": residual_profile.get("content_signature", ""),
            "display_text": residual_profile.get("display_text", ""),
            "flat_tokens": list(residual_profile.get("flat_tokens", [])),
            "sequence_groups": list(residual_profile.get("sequence_groups", [])),
            "canonical_content_signature": canonical_profile.get("content_signature", ""),
            "canonical_display_text": canonical_profile.get("display_text", ""),
            "canonical_flat_tokens": list(canonical_profile.get("flat_tokens", [])),
            "canonical_sequence_groups": list(canonical_profile.get("sequence_groups", [])),
            "base_weight": self._residual_base_weight_from_profile(canonical_profile),
            "recent_gain": self._weight._target_recent_gain(strength=1.0),
            "fatigue": 0.0,
            "runtime_er": er,
            "runtime_ev": ev,
            "match_count_total": 0,
            "last_updated_at": int(time.time() * 1000),
            "last_matched_at": 0,
            "last_recency_refresh_at": int(time.time() * 1000),
            "recency_hold_rounds_remaining": int(self._config.get("recency_gain_hold_rounds", 2)),
            "memory_refs": [episodic_memory_id] if episodic_memory_id else [],
            "ext": entry_ext,
        }
        owner_db.setdefault("diff_table", []).append(entry)
        self._invalidate_owner_local_residual_cache(owner_structure_id=owner_structure_id)
        return entry

    def _reinforce_raw_residual_entry(
        self,
        *,
        entry: dict,
        residual_profile: dict,
        canonical_profile: dict,
        episodic_memory_id: str,
        round_index: int,
        source_packet_id: str,
        structure_store,
        cut_engine,
        now_ms: int,
    ) -> dict:
        self._ensure_raw_residual_entry_schema(entry)
        existing_profiles = self._ensure_raw_residual_entry_profiles(
            entry=entry,
            structure_store=structure_store,
            cut_engine=cut_engine,
        )
        merged_canonical = canonical_profile
        existing_canonical = existing_profiles.get("canonical_profile", {})
        common_part = None
        if existing_canonical:
            common_part = cut_engine.maximum_common_part(
                existing_canonical.get("sequence_groups", []),
                canonical_profile.get("sequence_groups", []),
            )
        if existing_canonical and common_part and self._profiles_fuzzy_equivalent(
            left_profile=existing_canonical,
            right_profile=canonical_profile,
            cut_engine=cut_engine,
            common_part=common_part,
        ):
            merged_canonical = self._profile_from_stored_groups(
                list(common_part.get("common_groups", [])),
                cut_engine=cut_engine,
                ext={"kind": "stimulus_raw_residual_canonical_merged"},
            )
        self._reinforce_residual_entry_from_profile(entry, merged_canonical, now_ms=now_ms)
        entry["canonical_content_signature"] = merged_canonical.get("content_signature", "")
        entry["canonical_display_text"] = merged_canonical.get("display_text", "")
        entry["canonical_flat_tokens"] = list(merged_canonical.get("flat_tokens", []))
        entry["canonical_sequence_groups"] = list(merged_canonical.get("sequence_groups", []))
        if episodic_memory_id:
            memory_refs = list(entry.get("memory_refs", []))
            if episodic_memory_id not in memory_refs:
                memory_refs.append(episodic_memory_id)
            entry["memory_refs"] = memory_refs
        entry.setdefault("ext", {})["round_index"] = round_index
        entry["ext"]["source_packet_id"] = source_packet_id
        entry["last_updated_at"] = now_ms
        owner_structure_id = str(
            entry.get("ext", {}).get("context_owner_structure_id", "")
            or entry.get("ext", {}).get("owner_structure_id", "")
            or entry.get("context_owner_structure_id", "")
            or ""
        )
        self._invalidate_owner_local_residual_cache(owner_structure_id=owner_structure_id)
        return entry

    def _append_or_reinforce_common_structure_entry(
        self,
        *,
        owner_structure_id: str,
        owner_db: dict,
        common_structure: dict,
        common_profile: dict,
        structure_store,
        base_weight: float,
        source_packet_id: str,
        round_index: int,
        episodic_memory_id: str,
        now_ms: int,
    ) -> dict | None:
        common_structure_id = str(common_structure.get("id", ""))
        common_signature = str(common_profile.get("content_signature", ""))
        for entry in owner_db.get("diff_table", []):
            if entry.get("entry_type", "structure_ref") != "structure_ref":
                continue
            if str(entry.get("target_id", "")) != common_structure_id:
                continue
            if str(entry.get("ext", {}).get("relation_type", "")) != "residual_context_common":
                continue
            if str(entry.get("content_signature", "")) != common_signature:
                continue
            self._reinforce_common_structure_entry(
                entry=entry,
                delta_profile=common_profile,
                episodic_memory_id=episodic_memory_id,
                round_index=round_index,
                source_packet_id=source_packet_id,
                now_ms=now_ms,
            )
            return entry
        entry = structure_store.add_diff_entry(
            owner_structure_id,
            target_id=common_structure_id,
            content_signature=common_signature,
            base_weight=base_weight,
            residual_existing_signature="",
            residual_incoming_signature="",
            ext={
                "relation_type": "residual_context_common",
                "kind": "residual_context_common",
                "source_packet_id": source_packet_id,
                "round_index": round_index,
                "memory_refs": [episodic_memory_id] if episodic_memory_id else [],
                "grouped_display_text": common_profile.get("display_text", ""),
            },
        )
        if entry:
            self._reinforce_common_structure_entry(
                entry=entry,
                delta_profile=common_profile,
                episodic_memory_id=episodic_memory_id,
                round_index=round_index,
                source_packet_id=source_packet_id,
                now_ms=now_ms,
            )
        return entry

    def _reinforce_common_structure_entry(
        self,
        *,
        entry: dict,
        delta_profile: dict,
        episodic_memory_id: str,
        round_index: int,
        source_packet_id: str,
        now_ms: int,
    ) -> dict:
        self._reinforce_residual_entry_from_profile(entry, delta_profile, now_ms=now_ms)
        ext = dict(entry.get("ext", {}))
        memory_refs = list(ext.get("memory_refs", []))
        if episodic_memory_id and episodic_memory_id not in memory_refs:
            memory_refs.append(episodic_memory_id)
        ext["memory_refs"] = memory_refs
        ext["round_index"] = round_index
        ext["source_packet_id"] = source_packet_id
        entry["ext"] = ext
        owner_structure_id = str(
            ext.get("context_owner_structure_id", "")
            or ext.get("owner_structure_id", "")
            or entry.get("context_owner_structure_id", "")
            or ""
        )
        self._invalidate_owner_local_residual_cache(owner_structure_id=owner_structure_id)
        return entry

    @staticmethod
    def _remove_owner_diff_entry(*, owner_db: dict, entry_id: str) -> int:
        if not entry_id:
            return 0
        before = len(owner_db.get("diff_table", []))
        owner_db["diff_table"] = [
            entry
            for entry in owner_db.get("diff_table", [])
            if str(entry.get("entry_id", "")) != entry_id
        ]
        return max(0, before - len(owner_db.get("diff_table", [])))

    def _profiles_fuzzy_equivalent(self, *, left_profile: dict, right_profile: dict, cut_engine, common_part: dict | None = None) -> bool:
        self._increment_runtime_metric("owner_local_residual_fuzzy_equivalent_call_count")
        left_signature = str(left_profile.get("content_signature", ""))
        right_signature = str(right_profile.get("content_signature", ""))
        if left_signature and left_signature == right_signature:
            self._increment_runtime_metric("owner_local_residual_fuzzy_equivalent_signature_hit_count")
            return True

        cache_key = None
        if bool(self._config.get("stimulus_owner_local_residual_fuzzy_cache_enabled", True)):
            cache_key = (
                self._profile_fuzzy_cache_key(left_profile),
                self._profile_fuzzy_cache_key(right_profile),
            )
            if isinstance(self._runtime_cache, dict):
                cache = self._runtime_cache.setdefault("profile_fuzzy_equivalent_cache", {})
                if isinstance(cache, dict) and cache_key in cache:
                    self._increment_runtime_metric("owner_local_residual_fuzzy_equivalent_cache_hit_count")
                    return bool(cache[cache_key])

        if bool(self._config.get("stimulus_owner_local_residual_fuzzy_fast_reject_enabled", True)):
            left_unit_count = self._profile_unit_count(left_profile)
            right_unit_count = self._profile_unit_count(right_profile)
            if left_unit_count != right_unit_count:
                self._increment_runtime_metric("owner_local_residual_fuzzy_equivalent_fast_reject_count")
                if cache_key is not None and isinstance(self._runtime_cache, dict):
                    cache = self._runtime_cache.setdefault("profile_fuzzy_equivalent_cache", {})
                    if isinstance(cache, dict):
                        cache[cache_key] = False
                return False
            if self._profile_uses_strict_signature_equivalence(left_profile) and self._profile_uses_strict_signature_equivalence(right_profile):
                left_unit_signature_counts = self._profile_unit_signature_counts(left_profile)
                right_unit_signature_counts = self._profile_unit_signature_counts(right_profile)
                if left_unit_signature_counts and right_unit_signature_counts and left_unit_signature_counts != right_unit_signature_counts:
                    self._increment_runtime_metric("owner_local_residual_fuzzy_equivalent_fast_reject_count")
                    if cache_key is not None and isinstance(self._runtime_cache, dict):
                        cache = self._runtime_cache.setdefault("profile_fuzzy_equivalent_cache", {})
                        if isinstance(cache, dict):
                            cache[cache_key] = False
                    return False

        if common_part is None:
            self._increment_runtime_metric("owner_local_residual_fuzzy_equivalent_cut_count")
            common_part = cut_engine.maximum_common_part(
                left_profile.get("sequence_groups", []),
                right_profile.get("sequence_groups", []),
            )
        result = bool(
            int(common_part.get("common_length", 0)) > 0
            and not common_part.get("residual_existing_signature", "")
            and not common_part.get("residual_incoming_signature", "")
            and int(common_part.get("matched_existing_unit_count", 0)) >= self._profile_unit_count(left_profile)
            and int(common_part.get("matched_incoming_unit_count", 0)) >= self._profile_unit_count(right_profile)
        )
        if cache_key is not None and isinstance(self._runtime_cache, dict):
            cache = self._runtime_cache.setdefault("profile_fuzzy_equivalent_cache", {})
            if isinstance(cache, dict):
                cache[cache_key] = result
        return result

    @staticmethod
    def _profile_unit_count(profile: dict) -> int:
        return int(profile.get("unit_count", profile.get("token_count", len(profile.get("flat_tokens", [])))))

    @staticmethod
    def _profile_fuzzy_cache_key(profile: dict) -> tuple[Any, ...]:
        content_signature = str(profile.get("content_signature", "") or "")
        unit_signatures = tuple(
            str(signature)
            for signature in list(profile.get("flat_unit_signatures", []) or [])
            if str(signature)
        )
        if content_signature or unit_signatures:
            return ("sig", content_signature, unit_signatures)
        group_keys: list[tuple[Any, ...]] = []
        for group in list(profile.get("sequence_groups", []) or []):
            if not isinstance(group, dict):
                continue
            units = []
            for unit in list(group.get("units", []) or []):
                if not isinstance(unit, dict):
                    continue
                units.append(
                    (
                        str(unit.get("unit_signature", "") or ""),
                        str(unit.get("token", unit.get("text", unit.get("value", ""))) or ""),
                        str(unit.get("object_type", "") or ""),
                        str(unit.get("ref_object_id", unit.get("sa_id", "")) or ""),
                    )
                )
            group_keys.append(
                (
                    str(group.get("group_signature", "") or ""),
                    str(group.get("group_text", group.get("display_text", "")) or ""),
                    tuple(units),
                )
            )
        if group_keys:
            return ("groups", tuple(group_keys))
        flat_tokens = tuple(str(token) for token in list(profile.get("flat_tokens", []) or []) if str(token))
        return ("tokens", flat_tokens, str(profile.get("display_text", "") or ""))

    @staticmethod
    def _profile_unit_signature_counts(profile: dict) -> Counter:
        signatures = [
            str(signature)
            for signature in list(profile.get("flat_unit_signatures", []) or [])
            if str(signature)
        ]
        if not signatures:
            signatures = [
                str(unit.get("unit_signature", "") or "")
                for group in list(profile.get("sequence_groups", []) or [])
                if isinstance(group, dict)
                for unit in list(group.get("units", []) or [])
                if isinstance(unit, dict) and str(unit.get("unit_signature", "") or "")
            ]
        return Counter(signatures)

    def _profile_unit_signature_counts_cached(self, profile: dict) -> Counter:
        cache_key = self._profile_fuzzy_cache_key(profile)
        if isinstance(self._runtime_cache, dict):
            cache = self._runtime_cache.setdefault("profile_signature_count_cache", {})
            if isinstance(cache, dict) and cache_key in cache:
                return Counter(cache[cache_key])
        counts = self._profile_unit_signature_counts(profile)
        if isinstance(self._runtime_cache, dict):
            cache = self._runtime_cache.setdefault("profile_signature_count_cache", {})
            if isinstance(cache, dict):
                cache[cache_key] = dict(counts)
        return counts

    def _profile_strict_overlap_upper_bound(self, left_profile: dict, right_profile: dict) -> int:
        """Return a cheap upper bound for strict-token overlap, or a permissive bound.

        Attribute/numeric/time/fuzzy-structure profiles need full cut-engine scoring,
        so this guard only rejects profiles that opt into strict signature equivalence.
        """
        if not (
            self._profile_uses_strict_signature_equivalence(left_profile)
            and self._profile_uses_strict_signature_equivalence(right_profile)
        ):
            return max(self._profile_unit_count(left_profile), self._profile_unit_count(right_profile))
        left_counts = self._profile_unit_signature_counts_cached(left_profile)
        right_counts = self._profile_unit_signature_counts_cached(right_profile)
        if not left_counts or not right_counts:
            return max(self._profile_unit_count(left_profile), self._profile_unit_count(right_profile))
        return sum(min(int(count), int(right_counts.get(signature, 0))) for signature, count in left_counts.items())

    @staticmethod
    def _profile_uses_strict_signature_equivalence(profile: dict) -> bool:
        for group in list(profile.get("sequence_groups", []) or []):
            if not isinstance(group, dict):
                continue
            for unit in list(group.get("units", []) or []):
                if not isinstance(unit, dict):
                    continue
                unit_role = str(unit.get("unit_role", unit.get("role", "feature")) or "feature")
                if unit_role == "attribute" and str(unit.get("attribute_name", "") or ""):
                    return False
                if str(unit.get("object_type", "") or "") == "st" and str(unit.get("structure_fuzzy_signature", "") or ""):
                    return False
                signature = str(unit.get("unit_signature", "") or "")
                if signature.startswith("AN:"):
                    return False
        return True

    def _profile_total_energy(self, profile: dict) -> float:
        er, ev = self._residual_profile_energy(profile)
        return round(er + ev, 8)

    def _profile_reality_energy(self, profile: dict) -> float:
        er, _ = self._residual_profile_energy(profile)
        return round(er, 8)

    def _allow_long_profile_seed(
        self,
        profile: dict,
        *,
        soft_max_units_key: str,
        min_avg_energy_key: str,
        require_single_source_for_long: bool = False,
    ) -> bool:
        unit_count = max(0, int(self._profile_unit_count(profile)))
        soft_max_units = max(2, int(self._config.get(soft_max_units_key, 48) or 48))
        if unit_count <= soft_max_units:
            return True
        total_energy = max(0.0, float(self._profile_total_energy(profile) or 0.0))
        avg_unit_energy = total_energy / max(1.0, float(unit_count))
        min_avg_energy = max(0.0, float(self._config.get(min_avg_energy_key, 0.08) or 0.08))
        if avg_unit_energy < min_avg_energy:
            return False
        if require_single_source_for_long:
            source_types = set()
            origin_frames = set()
            for group in profile.get('sequence_groups', []) or []:
                if not isinstance(group, dict):
                    continue
                for unit in group.get('units', []) or []:
                    if not isinstance(unit, dict):
                        continue
                    st = str(unit.get('source_type', '') or '').strip()
                    of = str(unit.get('origin_frame_id', '') or '').strip()
                    if st:
                        source_types.add(st)
                    if of:
                        origin_frames.add(of)
            if len(source_types) > 1:
                return False
            if len(origin_frames) > 1:
                return False
        return True

    def _build_stimulus_memory_material(
        self,
        *,
        profile: dict,
        structure_ids: list[str] | None = None,
        structure_store=None,
        runtime_projection_structures: list[dict] | None = None,
    ) -> dict:
        sequence_groups = self._clone_working_groups(list(profile.get("sequence_groups", [])))
        grouped_display_text = (
            format_semantic_sequence_groups(sequence_groups, context="stimulus")
            or str(profile.get("semantic_display_text", "") or "")
            or format_sequence_groups(sequence_groups)
            or str(profile.get("display_text", ""))
        )
        unit_weights: dict[str, float] = {}
        group_weights: dict[str, float] = {}
        total_weight = 0.0
        for group in sequence_groups:
            group_weight = 0.0
            for unit in group.get("units", []):
                unit_id = str(unit.get("unit_id", ""))
                if not unit_id:
                    continue
                unit_weight = round(max(0.0, float(unit.get("er", 0.0))) + max(0.0, float(unit.get("ev", 0.0))), 8)
                unit_weights[unit_id] = unit_weight
                group_weight += unit_weight
            group_key = str(group.get("group_index", len(group_weights)))
            group_weights[group_key] = round(group_weight, 8)
            total_weight += group_weight
        if total_weight > 0.0:
            unit_energy_profile = {
                unit_id: round(weight / total_weight, 8)
                for unit_id, weight in unit_weights.items()
                if weight > 0.0
            }
            group_energy_profile = {
                group_id: round(weight / total_weight, 8)
                for group_id, weight in group_weights.items()
                if weight > 0.0
            }
        else:
            ordered_units = [
                str(unit.get("unit_id", ""))
                for group in sequence_groups
                for unit in group.get("units", [])
                if str(unit.get("unit_id", ""))
            ]
            fallback_share = round(1.0 / len(ordered_units), 8) if ordered_units else 0.0
            unit_energy_profile = {unit_id: fallback_share for unit_id in ordered_units}
            group_energy_profile = {}
        ordered_structure_ids = [str(structure_id) for structure_id in (structure_ids or []) if str(structure_id)]
        structure_items: list[dict] = []
        structure_energy_profile: dict[str, float] = {}
        if ordered_structure_ids:
            structure_profile_mode = str(
                self._config.get("stimulus_memory_structure_energy_profile_mode", "runtime_projection_energy") or "runtime_projection_energy"
            ).strip().lower()
            deduped_structure_ids: list[str] = []
            seen_structure_ids: set[str] = set()
            for structure_id in ordered_structure_ids:
                if structure_id in seen_structure_ids:
                    continue
                seen_structure_ids.add(structure_id)
                deduped_structure_ids.append(structure_id)
                structure_obj = structure_store.get(structure_id) if structure_store is not None else None
                display_text = str((structure_obj or {}).get("structure", {}).get("display_text", structure_id))
                grouped_text = str((structure_obj or {}).get("structure", {}).get("grouped_display_text", display_text))
                structure_items.append(
                    {
                        "structure_id": structure_id,
                        "display_text": display_text,
                        "grouped_display_text": grouped_text,
                    }
                )
            ordered_structure_ids = deduped_structure_ids
            structure_weight_sums: dict[str, float] = {}
            if structure_profile_mode == "runtime_projection_energy":
                for projection in runtime_projection_structures or []:
                    if not isinstance(projection, dict):
                        continue
                    structure_id = str(projection.get("structure_id", "") or "")
                    if not structure_id or structure_id not in seen_structure_ids:
                        continue
                    weight = round(
                        max(0.0, float(projection.get("er", 0.0) or 0.0))
                        + max(0.0, float(projection.get("ev", 0.0) or 0.0)),
                        8,
                    )
                    if weight <= 0.0:
                        continue
                    structure_weight_sums[structure_id] = round(
                        float(structure_weight_sums.get(structure_id, 0.0) or 0.0) + weight,
                        8,
                    )
            total_structure_weight = round(sum(float(v or 0.0) for v in structure_weight_sums.values()), 8)
            if total_structure_weight > 0.0:
                structure_energy_profile = {
                    structure_id: round(float(structure_weight_sums.get(structure_id, 0.0) or 0.0) / total_structure_weight, 8)
                    for structure_id in ordered_structure_ids
                    if float(structure_weight_sums.get(structure_id, 0.0) or 0.0) > 0.0
                }
            else:
                fallback_structure_share = round(1.0 / len(ordered_structure_ids), 8) if ordered_structure_ids else 0.0
                structure_energy_profile = {
                    structure_id: fallback_structure_share
                    for structure_id in ordered_structure_ids
                }
        return {
            "memory_kind": "stimulus_packet",
            "storage_grain": "sa",
            "grouped_display_text": grouped_display_text,
            "sequence_groups": sequence_groups,
            "unit_energy_profile": unit_energy_profile,
            "group_energy_profile": group_energy_profile,
            "structure_refs": ordered_structure_ids,
            "structure_items": structure_items,
            "structure_energy_profile": structure_energy_profile,
        }

    def _apply_grouped_display_to_profile(self, profile: dict) -> dict:
        updated = dict(profile or {})
        grouped_display_text = (
            format_semantic_sequence_groups(updated.get("sequence_groups", []), context="stimulus")
            or str(updated.get("semantic_display_text", "") or "")
            or format_sequence_groups(updated.get("sequence_groups", []))
        )
        if grouped_display_text:
            updated["grouped_display_text"] = grouped_display_text
            updated["display_text"] = grouped_display_text
            updated["semantic_display_text"] = grouped_display_text
        return updated

    def _build_raw_residual_debug(
        self,
        *,
        entry: dict,
        created: bool,
        fallback_memory_id: str,
        structure_store,
        cut_engine,
    ) -> dict:
        raw_display_text = str(entry.get("display_text", "") or "")
        canonical_display_text = str(entry.get("canonical_display_text", "") or "")
        content_signature = str(entry.get("canonical_content_signature", "") or entry.get("content_signature", "") or "")
        if (not raw_display_text) or (not canonical_display_text) or (not content_signature):
            profiles = self._ensure_raw_residual_entry_profiles(
                entry=entry,
                structure_store=structure_store,
                cut_engine=cut_engine,
                include_raw=True,
            )
            raw_profile = profiles.get("raw_profile", {})
            canonical_profile = profiles.get("canonical_profile", {})
            raw_display_text = raw_display_text or str(raw_profile.get("display_text", "") or "")
            canonical_display_text = canonical_display_text or str(canonical_profile.get("display_text", "") or "")
            content_signature = content_signature or str(canonical_profile.get("content_signature", "") or "")
        return {
            "entry_id": entry.get("entry_id", ""),
            "memory_id": (entry.get("memory_refs", []) or [fallback_memory_id] or [""])[-1],
            "kind": "raw_residual_memory",
            "created": bool(created),
            "display_text": canonical_display_text or raw_display_text,
            "raw_display_text": raw_display_text,
            "canonical_display_text": canonical_display_text,
            "raw_grouped_display_text": raw_display_text,
            "canonical_grouped_display_text": canonical_display_text,
            "content_signature": content_signature,
            "stats": {
            "base_weight": round(float(entry.get("base_weight", 0.0)), 8),
                "recent_gain": round(float(entry.get("recent_gain", 1.0)), 8),
                "fatigue": round(float(entry.get("fatigue", 0.0)), 8),
                "runtime_er": round(float(entry.get("runtime_er", 0.0)), 8),
                "runtime_ev": round(float(entry.get("runtime_ev", 0.0)), 8),
                "match_count_total": int(entry.get("match_count_total", 0)),
            },
        }

    def _find_or_create_structure_from_profile(
        self,
        *,
        profile: dict,
        structure_store,
        pointer_index,
        cut_engine,
        trace_id: str,
        tick_id: str,
        confidence: float,
        origin: str,
        origin_id: str,
        parent_ids: list[str],
        base_weight: float | None = None,
        ext: dict | None = None,
        skip_exact_lookup: bool = False,
        require_context_free: bool = False,
    ) -> dict:
        resolved_ext = dict(profile.get("ext", {}) if isinstance(profile.get("ext", {}), dict) else {})
        resolved_ext.update(ext or {})
        if require_context_free:
            for key in ("context_ref_object_id", "context_ref_object_type", "context_owner_structure_id", "context_path_ids"):
                resolved_ext.pop(key, None)
        context = extract_context_metadata({"ext": resolved_ext})
        if base_weight is None:
            base_weight = self._residual_base_weight_from_profile({**dict(profile), "ext": resolved_ext})
        profile = {**dict(profile), "ext": resolved_ext}
        result = shared_resolve_or_create_structure_from_profile(
            profile=profile,
            structure_store=structure_store,
            pointer_index=pointer_index,
            cut_engine=cut_engine,
            trace_id=trace_id,
            tick_id=tick_id,
            confidence=confidence,
            origin=origin,
            origin_id=origin_id,
            parent_ids=parent_ids,
            base_weight=base_weight,
            ext=resolved_ext,
            allow_cs_event_structures=bool(self._config.get("enable_cs_event_structures_in_stimulus_retrieval", False)),
            strict_context_owner_match=False if require_context_free else bool(context.get("context_owner_structure_id", "")),
            strict_context_ref_match=False if require_context_free else bool(context.get("context_ref_object_id", "")),
            require_context_free=require_context_free,
            skip_exact_lookup=skip_exact_lookup,
        )
        return {"created": bool(result.get("created", False)), "structure": result.get("structure")}

    @staticmethod
    def _self_placeholder_token(structure_obj: dict) -> str:
        structure_id = str(structure_obj.get("id", ""))
        display_text = str(structure_obj.get("structure", {}).get("display_text", structure_id))
        return f"SELF[{structure_id}:{display_text}]"


    def _build_structure_profile(self, *, structure_obj: dict, structure_store, cut_engine) -> dict:
        structure_id = str(structure_obj.get("id", ""))
        content_signature = str(structure_obj.get("structure", {}).get("content_signature", ""))
        updated_at = int(structure_obj.get("updated_at", 0) or 0)
        cache_key = (structure_id, content_signature, updated_at)
        cache = None
        if isinstance(self._runtime_cache, dict):
            cache = self._runtime_cache.get("structure_profiles")
        if isinstance(cache, dict) and cache_key in cache:
            return cache[cache_key]
        shared_cache_key = ("structure_profiles",) + cache_key
        shared_cached = None
        if hasattr(structure_store, "get_shared_runtime_cache_entry"):
            shared_cached = structure_store.get_shared_runtime_cache_entry(
                "structure_profiles",
                shared_cache_key,
            )
        if isinstance(shared_cached, dict):
            if isinstance(cache, dict) and structure_id:
                cache[cache_key] = shared_cached
            return shared_cached

        profile = restore_structure_profile(
            structure_obj,
            cut_engine=cut_engine,
            structure_store=structure_store,
            group_store=None,
        )
        if isinstance(cache, dict) and structure_id:
            cache[cache_key] = profile
        if hasattr(structure_store, "set_shared_runtime_cache_entry"):
            structure_store.set_shared_runtime_cache_entry(
                "structure_profiles",
                shared_cache_key,
                profile,
            )
        return profile

    @staticmethod
    def _attach_explicit_canonical_profile(profile: dict, *, canonical_profile: dict) -> dict:
        attached = dict(profile)
        attached["canonical_display_text"] = canonical_profile.get("display_text", "")
        attached["canonical_flat_tokens"] = list(canonical_profile.get("flat_tokens", []))
        attached["canonical_sequence_groups"] = list(canonical_profile.get("sequence_groups", []))
        return attached

    def _build_explicit_canonical_profile(self, profile: dict, *, cut_engine) -> dict | None:
        canonical_groups = list(profile.get("canonical_sequence_groups", []))
        if not canonical_groups:
            return None
        explicit = cut_engine.build_sequence_profile_from_groups(canonical_groups)
        explicit["display_text"] = str(profile.get("canonical_display_text", explicit.get("display_text", "")))
        explicit["flat_tokens"] = list(profile.get("canonical_flat_tokens", explicit.get("flat_tokens", [])))
        return explicit

    def _canonicalize_profile(self, profile: dict, *, structure_store, cut_engine) -> dict:
        return shared_canonicalize_profile(
            profile=profile,
            structure_store=structure_store,
            cut_engine=cut_engine,
        )

    @staticmethod
    def _build_residual_entry_ext(
        *,
        source_packet_id: str,
        round_index: int,
        episodic_memory_id: str,
        raw_profile: dict,
        canonical_profile: dict,
        raw_signature: str,
    ) -> dict:
        return {
            "relation_type": "residual_context",
            "source_packet_id": source_packet_id,
            "origin_round": round_index,
            "anchor_memory_id": episodic_memory_id,
            "raw_residual_signature": str(raw_signature or ""),
            "canonical_signature": str(canonical_profile.get("content_signature", "")),
            "raw_display_text": str(raw_profile.get("display_text", "")),
            "canonical_display_text": str(canonical_profile.get("display_text", "")),
        }

    @staticmethod
    def _profile_has_non_placeholder_tokens(profile: dict, *, placeholder_token: str) -> bool:
        return any(
            str(unit.get("token", "")) and str(unit.get("token", "")) != placeholder_token
            for group in profile.get("sequence_groups", [])
            for unit in group.get("units", [])
        )

    @staticmethod
    def _common_part_has_bidirectional_residuals(common_part: dict) -> bool:
        return bool(common_part.get("residual_existing_signature", "")) and bool(common_part.get("residual_incoming_signature", ""))

    # 刺激级共有结构必须完整保留当前命中的 owner 结构，并且 owner 外还要确实存在额外公共内容。
    # 如果共同部分已经不再包含当前 owner，就只能保留原始残差，不能错误地下沉为 owner 的子共有结构。
    def _validate_owner_overlap_common_part(self, *, common_part: dict, owner_profile: dict, cut_engine) -> dict | None:
        fast_status = self._common_overlap_beyond_owner_fast_status(
            common_part=common_part,
            owner_profile=owner_profile,
        )
        if fast_status is False:
            return None
        common_profile = self._apply_grouped_display_to_profile(
            cut_engine.build_sequence_profile_from_groups(list(common_part.get("common_groups", [])))
        )
        if fast_status is True:
            return {"common_profile": common_profile}
        if not self._common_overlap_beyond_owner(
            common_part=common_part,
            owner_profile=owner_profile,
            common_profile=common_profile,
            cut_engine=cut_engine,
        ):
            return None
        return {"common_profile": common_profile}

    def _common_overlap_beyond_owner_fast_status(self, *, common_part: dict, owner_profile: dict) -> bool | None:
        owner_unit_count = max(1, self._profile_unit_count(owner_profile))
        if int(common_part.get("common_length", 0)) <= owner_unit_count:
            return False
        owner_tokens = [str(token) for token in list(owner_profile.get("flat_tokens", []) or []) if str(token)]
        common_tokens = [str(token) for token in list(common_part.get("common_tokens", []) or []) if str(token)]
        if bool(self._config.get("stimulus_residual_common_require_owner_prefix_alignment_enabled", True)):
            if owner_tokens and common_tokens[: len(owner_tokens)] != owner_tokens:
                return False
            if self._profile_uses_strict_signature_equivalence(owner_profile):
                owner_signatures = self._profile_unit_signatures_ordered(owner_profile)
                common_signatures = self._common_part_unit_signatures_ordered(common_part)
                if owner_signatures and common_signatures[: len(owner_signatures)] == owner_signatures:
                    return True
        return None

    def _common_overlap_beyond_owner(self, *, common_part: dict, owner_profile: dict, common_profile: dict, cut_engine) -> bool:
        owner_unit_count = max(1, self._profile_unit_count(owner_profile))
        if int(common_part.get("common_length", 0)) <= owner_unit_count:
            return False
        if bool(self._config.get("stimulus_residual_common_require_owner_prefix_alignment_enabled", True)):
            owner_tokens = [str(token) for token in list(owner_profile.get("flat_tokens", []) or []) if str(token)]
            common_tokens = [str(token) for token in list(common_profile.get("flat_tokens", []) or []) if str(token)]
            if owner_tokens and common_tokens[: len(owner_tokens)] != owner_tokens:
                return False
        return self._profile_fully_contains_subprofile(
            container_profile=common_profile,
            required_profile=owner_profile,
            cut_engine=cut_engine,
        )

    @staticmethod
    def _profile_unit_signatures_ordered(profile: dict) -> list[str]:
        signatures = [str(signature) for signature in list(profile.get("flat_unit_signatures", []) or []) if str(signature)]
        if signatures:
            return signatures
        return [
            str(unit.get("unit_signature", "") or "")
            for group in list(profile.get("sequence_groups", []) or [])
            if isinstance(group, dict)
            for unit in list(group.get("units", []) or [])
            if isinstance(unit, dict) and str(unit.get("unit_signature", "") or "")
        ]

    @staticmethod
    def _common_part_unit_signatures_ordered(common_part: dict) -> list[str]:
        signatures: list[str] = []
        for group in list(common_part.get("common_groups", []) or []):
            if not isinstance(group, dict):
                continue
            for unit in list(group.get("units", []) or []):
                if not isinstance(unit, dict):
                    continue
                signature = str(unit.get("unit_signature", "") or "")
                if signature:
                    signatures.append(signature)
        if signatures:
            return signatures
        return [
            str(signature)
            for pair in list(common_part.get("matched_pairs", []) or [])
            if isinstance(pair, dict)
            for signature in list(pair.get("common_unit_signatures", []) or [])
            if str(signature)
        ]

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

    @staticmethod
    def _subtract_tokens_preserve_order(tokens: list[str], tokens_to_remove: list[str]) -> list[str]:
        remove_counter = Counter(str(token) for token in tokens_to_remove if str(token))
        residual = []
        for token in tokens:
            text = str(token)
            if remove_counter.get(text, 0) > 0:
                remove_counter[text] -= 1
                continue
            residual.append(text)
        return residual

    def _register_atomic_extension_paths(
        self,
        *,
        full_units: list[dict],
        matched_structure_id: str,
        target_structure: dict,
        structure_store,
        pointer_index,
        cut_engine,
        source_packet_id: str,
    ) -> None:
        if not full_units:
            return
        target_id = target_structure.get("id", "")
        if not target_id:
            return
        target_signature = target_structure.get("structure", {}).get("content_signature", "")
        for unit in full_units:
            token = str(unit.get("token", ""))
            if not token:
                continue
            atomic_structure = self._find_exact_structure_by_signature(
                signature=token,
                structure_store=structure_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
                expected_tokens=[token],
                expected_sequence_groups=[{"group_index": 0, "tokens": [token], "source_type": unit.get("source_type", "")}],
            )
            if not atomic_structure:
                continue
            owner_structure_id = atomic_structure.get("id", "")
            if not owner_structure_id or owner_structure_id == matched_structure_id:
                continue
            residual_units = self._subtract_units(full_units, [unit])
            residual_signature = cut_engine.sequence_groups_to_signature(self._units_to_groups(residual_units))
            structure_store.add_diff_entry(
                owner_structure_id,
                target_id=target_id,
                content_signature=target_signature,
                base_weight=float(self._config.get("stimulus_atomic_extension_link_base_weight", 0.72)),
                residual_existing_signature="",
                residual_incoming_signature=residual_signature,
                ext={
                    "linked_from_parent": owner_structure_id,
                    "relation_type": "incoming_extension",
                    "source_packet_id": source_packet_id,
                },
            )
            owner_db = structure_store.get_db_by_owner(owner_structure_id)
            if owner_db:
                self._maintenance.apply_structure_db_soft_limits(owner_db)
                structure_store.update_db(owner_db)

    def _find_or_create_structure_from_units(
        self,
        *,
        units: list[dict],
        structure_store,
        pointer_index,
        cut_engine,
        trace_id: str,
        tick_id: str,
        confidence: float,
        origin: str,
        origin_id: str,
        parent_ids: list[str],
        base_weight: float | None = None,
        ext: dict | None = None,
        skip_exact_lookup: bool = False,
        require_context_free: bool = False,
    ) -> dict:
        profile = cut_engine.build_sequence_profile_from_groups(self._units_to_groups(units))
        resolved_ext = dict(profile.get("ext", {}) if isinstance(profile.get("ext", {}), dict) else {})
        resolved_ext.update(ext or {})
        if require_context_free:
            for key in ("context_ref_object_id", "context_ref_object_type", "context_owner_structure_id", "context_path_ids"):
                resolved_ext.pop(key, None)
        profile["ext"] = resolved_ext
        context = extract_context_metadata({"ext": resolved_ext})
        if base_weight is None:
            base_weight = self._residual_base_weight_from_profile(profile)
        result = shared_resolve_or_create_structure_from_profile(
            profile=profile,
            structure_store=structure_store,
            pointer_index=pointer_index,
            cut_engine=cut_engine,
            trace_id=trace_id,
            tick_id=tick_id,
            confidence=confidence,
            origin=origin,
            origin_id=origin_id,
            parent_ids=parent_ids,
            base_weight=base_weight,
            ext=resolved_ext,
            allow_cs_event_structures=bool(self._config.get("enable_cs_event_structures_in_stimulus_retrieval", False)),
            strict_context_owner_match=False if require_context_free else bool(context.get("context_owner_structure_id", "")),
            strict_context_ref_match=False if require_context_free else bool(context.get("context_ref_object_id", "")),
            require_context_free=require_context_free,
            skip_exact_lookup=skip_exact_lookup,
        )
        return {"created": bool(result.get("created", False)), "structure": result.get("structure")}

    def _find_exact_structure_by_signature(
        self,
        *,
        signature: str,
        structure_store,
        pointer_index,
        cut_engine,
        expected_tokens: list[str] | None = None,
        expected_sequence_groups: list[dict] | None = None,
    ) -> dict | None:
        return shared_find_exact_structure_by_signature(
            signature=signature,
            structure_store=structure_store,
            pointer_index=pointer_index,
            cut_engine=cut_engine,
            expected_tokens=expected_tokens,
            expected_sequence_groups=expected_sequence_groups,
            allow_cs_event_structures=bool(self._config.get("enable_cs_event_structures_in_stimulus_retrieval", False)),
        )

    @staticmethod
    def _sort_candidate_details(candidate_details: list[dict]) -> list[dict]:
        ordered = list(candidate_details)
        ordered.sort(
            key=lambda item: (
                0 if item.get("eligible") else 1,
                -float(item.get("competition_score", 0.0)),
                -int(item.get("existing_length", 0)),
                -float(item.get("entry_runtime_weight", 0.0)),
                -float(item.get("runtime_weight", 0.0)),
            )
        )
        return ordered

    @staticmethod
    def _upsert_candidate_detail(candidate_details: list[dict], detail: dict) -> list[dict]:
        detail_id = detail.get("structure_id", "")
        if not detail_id:
            return list(candidate_details)
        for index, item in enumerate(candidate_details):
            if item.get("structure_id", "") == detail_id:
                candidate_details[index] = detail
                return candidate_details
        candidate_details.append(detail)
        return candidate_details

    @staticmethod
    def _is_better_structure_match(candidate_detail: dict, current_best: dict | None) -> bool:
        if current_best is None:
            return True
        candidate_key = (
            1 if candidate_detail.get("eligible") else 0,
            float(candidate_detail.get("competition_score", 0.0)),
            int(candidate_detail.get("existing_length", 0)),
            float(candidate_detail.get("entry_runtime_weight", 0.0)),
            float(candidate_detail.get("runtime_weight", 0.0)),
        )
        current_key = (
            1 if current_best.get("eligible") else 0,
            float(current_best.get("competition_score", 0.0)),
            int(current_best.get("existing_length", 0)),
            float(current_best.get("entry_runtime_weight", 0.0)),
            float(current_best.get("runtime_weight", 0.0)),
        )
        return candidate_key > current_key

    @staticmethod
    def _unit_total_energy(unit: dict) -> float:
        return round(
            max(
                0.0,
                float(unit.get("total_energy", float(unit.get("er", 0.0)) + float(unit.get("ev", 0.0)))),
            ),
            8,
        )

    def _unit_competition_energy(self, unit: dict) -> float:
        base_energy = self._unit_total_energy(unit)
        if base_energy <= 0.0:
            return 0.0
        role = str(unit.get("unit_role", unit.get("role", "")) or "")
        if unit.get("is_placeholder"):
            scale = float(self._config.get("stimulus_placeholder_energy_scale", 1.0))
        elif role == "attribute":
            scale = float(self._config.get("stimulus_attribute_energy_scale", 0.22))
        else:
            scale = 1.0
        match_similarity = max(0.0, min(1.0, float(unit.get("match_similarity", 1.0))))
        return round(base_energy * max(0.0, scale) * match_similarity, 8)

    def _units_total_energy(self, units: list[dict]) -> float:
        return round(
            sum(self._unit_competition_energy(unit) for unit in units if isinstance(unit, dict)),
            8,
        )

    def _energy_match_ratio(
        self,
        *,
        matched_units: list[dict],
        all_units: list[dict],
        fallback_numerator: float,
        fallback_denominator: float,
    ) -> float:
        total_energy = self._units_total_energy(all_units)
        matched_energy = self._units_total_energy(matched_units)
        if total_energy > 0.0:
            return round(max(0.0, min(1.0, matched_energy / total_energy)), 8)
        if fallback_denominator <= 0:
            return 0.0
        return round(max(0.0, min(1.0, float(fallback_numerator) / float(fallback_denominator))), 8)

    def _residual_profile_energy(self, profile: dict) -> tuple[float, float]:
        er = 0.0
        ev = 0.0
        for group in profile.get("sequence_groups", []):
            for unit in group.get("units", []):
                if not isinstance(unit, dict):
                    continue
                er += max(0.0, float(unit.get("er", 0.0)))
                ev += max(0.0, float(unit.get("ev", 0.0)))
        return round(er, 8), round(ev, 8)

    def _residual_weight_delta(self, *, er: float, ev: float) -> float:
        del ev
        return round(max(0.0, float(er)) * float(self._config.get("base_weight_er_gain", 0.08)), 8)

    def _residual_base_weight_from_profile(self, profile: dict, *, seed: float | None = None) -> float:
        er, ev = self._residual_profile_energy(profile)
        del ev
        if er <= 0.0:
            return round(max(0.0, float(self._config.get("ev_only_creation_base_weight", 0.0) or 0.0)), 8)
        if seed is None:
            seed = float(self._config.get("residual_base_weight_initial_bias", 0.0) or 0.0)
        return round(max(0.0, float(seed) + self._residual_weight_delta(er=er, ev=0.0)), 8)

    def _reinforce_residual_entry_from_profile(self, entry: dict, profile: dict, *, now_ms: int) -> dict:
        er, ev = self._residual_profile_energy(profile)
        self._weight.mark_entry_activation(
            entry,
            delta_er=er,
            delta_ev=ev,
            match_score=1.0,
            now_ms=now_ms,
        )
        entry["base_weight"] = self._weight.update_base_weight_by_support(
            current_base_weight=entry.get("base_weight", None),
            reality_support=er,
            virtual_support=ev,
            match_score=1.0,
        )
        return entry

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

    @staticmethod
    def _sigmoid(value: float, *, midpoint: float, slope: float) -> float:
        safe_slope = max(1e-6, float(slope))
        try:
            result = 1.0 / (1.0 + math.exp(-(float(value) - float(midpoint)) / safe_slope))
        except OverflowError:
            result = 0.0 if value < midpoint else 1.0
        return round(max(0.0, min(1.0, result)), 8)

    @staticmethod
    def _shape_ratio(value: float, *, power: float) -> float:
        bounded = max(0.0, min(1.0, float(value)))
        if bounded <= 0.0:
            return 0.0
        if bounded >= 1.0:
            return 1.0
        safe_power = max(0.05, float(power))
        return round(max(0.0, min(1.0, pow(bounded, safe_power))), 8)

    def _compose_match_score(
        self,
        *,
        stimulus_match_ratio: float,
        structure_match_ratio: float,
        attribute_anchor_only: bool = False,
    ) -> float:
        stimulus_component = self._shape_ratio(
            stimulus_match_ratio,
            power=float(
                self._config.get(
                    "stimulus_competition_attribute_ratio_power"
                    if attribute_anchor_only
                    else "stimulus_competition_stimulus_ratio_power",
                    1.0 if attribute_anchor_only else 0.35,
                )
            ),
        )
        structure_component = self._shape_ratio(
            structure_match_ratio,
            power=float(self._config.get("stimulus_competition_structure_ratio_power", 0.85)),
        )
        joint_ratio = max(0.0, min(1.0, float(min(stimulus_component, structure_component))))
        if joint_ratio >= 1.0:
            return 1.0
        denoise = self._sigmoid(
            joint_ratio,
            midpoint=float(self._config.get("stimulus_competition_noise_mid", 0.01)),
            slope=max(1e-6, float(self._config.get("stimulus_competition_noise_scale", 0.004))),
        )
        hill = self._hill_score(
            joint_ratio,
            half_point=float(self._config.get("stimulus_competition_half_ratio", 0.1)),
            power=float(self._config.get("stimulus_competition_curve_power", 1.2)),
        )
        score = hill * denoise
        return round(max(0.0, score), 8)

    def _build_match_score_v2_breakdown(
        self,
        *,
        base_score: float,
        matched_existing_units: list[dict],
        matched_incoming_units: list[dict],
        bundle_constraints: dict | None,
        full_structure_included: bool,
        context_payload: dict | None,
        runtime_weight: float = 1.0,
        entry_runtime_weight: float = 1.0,
        context_support_hint: float | None = None,
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

    def _effective_transfer_fraction(self, transfer_ratio: float, similarity_score: float) -> float:
        ratio = max(0.0, min(1.0, float(transfer_ratio)))
        similarity = max(0.0, min(1.0, float(similarity_score)))
        if ratio <= 0.0 or similarity <= 0.0:
            return 0.0
        if not bool(self._config.get("stimulus_transfer_curve_enabled", True)):
            return round(max(0.0, min(1.0, ratio * similarity)), 8)
        curved = self._hill_score(
            similarity,
            half_point=float(self._config.get("stimulus_transfer_curve_half_score", 0.2)),
            power=float(self._config.get("stimulus_transfer_curve_power", 0.45)),
        )
        if bool(self._config.get("stimulus_transfer_curve_normalize_at_one", True)):
            curve_at_one = self._hill_score(
                1.0,
                half_point=float(self._config.get("stimulus_transfer_curve_half_score", 0.2)),
                power=float(self._config.get("stimulus_transfer_curve_power", 0.45)),
            )
            if curve_at_one > 1e-9:
                curved = max(0.0, min(1.0, curved / curve_at_one))
        return round(max(0.0, min(1.0, ratio * curved)), 8)

    def _capture_structure_stats(self, structure_obj: dict) -> dict:
        stats = structure_obj.get("stats", {})
        return {
            "base_weight": round(float(stats.get("base_weight", 0.0)), 8),
            "recent_gain": round(float(stats.get("recent_gain", 1.0)), 8),
            "fatigue": round(float(stats.get("fatigue", 0.0)), 8),
            "runtime_er": round(float(stats.get("runtime_er", 0.0)), 8),
            "runtime_ev": round(float(stats.get("runtime_ev", 0.0)), 8),
            "match_count_total": int(stats.get("match_count_total", 0)),
            "verified_count_er": int(stats.get("verified_count_er", 0)),
            "worn_count_ev": int(stats.get("worn_count_ev", 0)),
        }

    def _build_structure_debug(self, structure_obj: dict) -> dict:
        sequence_groups = list(structure_obj.get("structure", {}).get("sequence_groups", []))
        return {
            "structure_id": structure_obj.get("id", ""),
            "display_text": structure_obj.get("structure", {}).get("display_text", structure_obj.get("id", "")),
            "flat_tokens": list(structure_obj.get("structure", {}).get("flat_tokens", [])),
            "sequence_groups": sequence_groups,
            "grouped_display_text": format_sequence_groups(sequence_groups),
            "content_signature": structure_obj.get("structure", {}).get("content_signature", ""),
            "ext": dict(structure_obj.get("structure", {}).get("ext", {})),
            "stats": self._capture_structure_stats(structure_obj),
        }

    @staticmethod
    def _clone_working_groups(groups: list[dict]) -> list[dict]:
        return [
            {
                **dict(group),
                "units": [dict(unit) for unit in group.get("units", []) if isinstance(unit, dict)],
                "csa_bundles": [dict(bundle) for bundle in group.get("csa_bundles", []) if isinstance(bundle, dict)],
            }
            for group in groups
            if isinstance(group, dict)
        ]

    @classmethod
    def _describe_runtime_groups(cls, groups: list[dict]) -> list[dict]:
        described = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            units = sorted(
                [dict(unit) for unit in group.get("units", []) if isinstance(unit, dict)],
                key=lambda item: int(item.get("sequence_index", 0)),
            )
            described.append(
                {
                    "group_index": int(group.get("group_index", 0)),
                    "source_type": str(group.get("source_type", "")),
                    "origin_frame_id": str(group.get("origin_frame_id", "")),
                    "tokens": [str(unit.get("token", "")) for unit in units if str(unit.get("token", ""))],
                    "display_text": format_group_display(units, group.get("csa_bundles", [])),
                    "semantic_display_text": format_semantic_group_display(
                        {
                            **dict(group),
                            "units": [dict(unit) for unit in units if isinstance(unit, dict)],
                            "csa_bundles": [dict(bundle) for bundle in group.get("csa_bundles", []) if isinstance(bundle, dict)],
                        },
                        context="stimulus",
                    ),
                    "visible_text": "".join(
                        str(unit.get("token", ""))
                        for unit in units
                        if str(unit.get("token", "")) and (bool(unit.get("display_visible", False)) or bool(unit.get("is_placeholder", False)))
                    ),
                    "csa_bundles": cls._format_runtime_bundle_texts(group),
                    "csa_bundle_defs": [dict(bundle) for bundle in group.get("csa_bundles", []) if isinstance(bundle, dict)],
                    "units": [dict(unit) for unit in units if isinstance(unit, dict)],
                    "sequence_groups": [
                        {
                            **dict(group),
                            "units": [dict(unit) for unit in units if isinstance(unit, dict)],
                            "csa_bundles": [dict(bundle) for bundle in group.get("csa_bundles", []) if isinstance(bundle, dict)],
                        }
                    ],
                }
            )
        return described

    @classmethod
    def _format_runtime_group_texts(cls, groups: list[dict]) -> str:
        parts = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            text = str(group.get("display_text", "") or "")
            if not text:
                return format_sequence_groups(groups)
            parts.append(text)
        return " / ".join(parts)

    @classmethod
    def _format_runtime_group_text(cls, group: dict) -> str:
        text = str(group.get("display_text", "") or "")
        if text:
            return text
        units = [dict(unit) for unit in group.get("units", []) if isinstance(unit, dict)]
        bundles = [dict(bundle) for bundle in group.get("csa_bundles", []) if isinstance(bundle, dict)]
        return format_group_display({**dict(group), "units": units, "csa_bundles": bundles})

    @classmethod
    def _format_runtime_bundle_texts(cls, group: dict) -> list[str]:
        units_by_id = {
            str(unit.get("unit_id", "")): unit
            for unit in group.get("units", [])
            if isinstance(unit, dict) and str(unit.get("unit_id", ""))
        }
        displays = []
        for bundle in group.get("csa_bundles", []):
            if not isinstance(bundle, dict):
                continue
            member_tokens = [
                str(units_by_id.get(str(member_id), {}).get("token", ""))
                for member_id in bundle.get("member_unit_ids", [])
                if str(units_by_id.get(str(member_id), {}).get("token", ""))
            ]
            if member_tokens:
                displays.append(f"({' + '.join(member_tokens)})")
        return displays

    @staticmethod
    def _find_group(groups: list[dict], group_index: int) -> dict | None:
        for group in groups:
            if int(group.get("group_index", 0)) == int(group_index):
                return group
        return None

    @staticmethod
    def _flatten_remaining_units(groups: list[dict]) -> list[dict]:
        units = []
        for group in groups:
            for unit in group.get("units", []):
                units.append(dict(unit))
        return units

    @staticmethod
    def _collect_remaining_tokens(groups: list[dict]) -> list[str]:
        tokens = []
        for group in groups:
            for unit in sorted(group.get("units", []), key=lambda item: item.get("sequence_index", 0)):
                token = unit.get("token", "")
                if token:
                    tokens.append(token)
        return tokens

    def _collect_remaining_tokens_preview(self, groups: list[dict]) -> list[str]:
        limit = self._round_debug_token_preview_limit()
        if limit <= 0:
            return []
        tokens = []
        for group in groups:
            for unit in sorted(group.get("units", []), key=lambda item: item.get("sequence_index", 0)):
                token = unit.get("token", "")
                if token:
                    tokens.append(token)
                    if len(tokens) >= limit:
                        return tokens
        return tokens

    def _collect_focus_window_groups(self, groups: list[dict], anchor_unit: dict) -> list[dict]:
        anchor_group = self._find_group(groups, int(anchor_unit.get("group_index", 0)))
        if not anchor_group:
            return []
        source_type = anchor_group.get("source_type", "")
        origin_frame_id = anchor_group.get("origin_frame_id", "")
        return [
            group
            for group in groups
            if group.get("source_type", "") == source_type and group.get("origin_frame_id", "") == origin_frame_id
        ]

    def _find_group_position(self, groups: list[dict], group_index: int) -> int:
        for position, group in enumerate(groups):
            if int(group.get("group_index", 0)) == int(group_index):
                return position
        return 0

    @staticmethod
    def _units_to_groups(units: list[dict]) -> list[dict]:
        grouped: dict[int, list[dict]] = {}
        order: list[int] = []
        for unit in units:
            key = int(unit.get("group_index", 0))
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append(dict(unit))

        result: list[dict] = []
        for key in order:
            group_units = sorted(grouped[key], key=lambda item: int(item.get("sequence_index", 0)))
            first = group_units[0] if group_units else {}
            order_sensitive = any(bool(unit.get("order_sensitive", False)) for unit in group_units)
            string_texts = [str(unit.get("string_token_text", "") or "") for unit in group_units if str(unit.get("string_token_text", "") or "")]
            string_token_text = string_texts[0] if string_texts and all(text == string_texts[0] for text in string_texts) else ""
            string_unit_kind = "char_sequence" if string_token_text else str(first.get("string_unit_kind", "") or "")
            result.append(
                {
                    "group_index": key,
                    "source_type": first.get("source_type", "") if first else "",
                    "origin_frame_id": first.get("origin_frame_id", "") if first else "",
                    "source_group_index": int(first.get("source_group_index", key)) if first else key,
                    "order_sensitive": bool(order_sensitive and string_token_text),
                    "string_unit_kind": string_unit_kind,
                    "string_token_text": string_token_text,
                    "units": group_units,
                }
            )
        return result

    @staticmethod
    def _subtract_units(units: list[dict], matched_units: list[dict]) -> list[dict]:
        matched_ids = {str(unit.get("unit_id", "")) for unit in matched_units if str(unit.get("unit_id", ""))}
        return [dict(unit) for unit in units if str(unit.get("unit_id", "")) not in matched_ids]

    @staticmethod
    def _groups_in_span(groups: list[dict], span: list[int]) -> list[dict]:
        if not span or len(span) < 2:
            return []
        start = max(0, int(span[0]))
        end = max(start, min(len(groups), int(span[1])))
        return [groups[index] for index in range(start, end)]

    def _collect_matched_units(
        self,
        groups: list[dict],
        common_part: dict,
        *,
        use_existing_side: bool = False,
    ) -> list[dict]:
        matched_units = []
        group_index_key = "existing_group_index" if use_existing_side else "incoming_group_index"
        unit_refs_key = "existing_unit_refs" if use_existing_side else "incoming_unit_refs"
        similarity_map_key = "matched_existing_unit_similarities" if use_existing_side else "matched_incoming_unit_similarities"
        global_similarity_map = {
            str(unit_id): float(similarity)
            for unit_id, similarity in common_part.get(similarity_map_key, {}).items()
            if str(unit_id)
        }
        for pair in common_part.get("matched_pairs", []):
            group_index = int(pair.get(group_index_key, -1))
            if group_index < 0 or group_index >= len(groups):
                continue
            needed_ids = {str(unit_id) for unit_id in pair.get(unit_refs_key, []) if str(unit_id)}
            pair_similarity_map = {
                str(unit_id): float(similarity)
                for unit_id, similarity in pair.get(similarity_map_key, {}).items()
                if str(unit_id)
            }
            needed_tokens = Counter(str(token) for token in pair.get("common_tokens", []) if str(token))
            group_units = sorted(groups[group_index].get("units", []), key=lambda item: int(item.get("sequence_index", 0)))
            for unit in group_units:
                unit_id = str(unit.get("unit_id", ""))
                if needed_ids:
                    if unit_id in needed_ids:
                        similarity = pair_similarity_map.get(unit_id, global_similarity_map.get(unit_id, 1.0))
                        matched_units.append({**dict(unit), "match_similarity": round(max(0.0, min(1.0, float(similarity))), 8)})
                    continue
                token = str(unit.get("token", ""))
                if needed_tokens.get(token, 0) > 0:
                    needed_tokens[token] -= 1
                    similarity = global_similarity_map.get(unit_id, 1.0)
                    matched_units.append({**dict(unit), "match_similarity": round(max(0.0, min(1.0, float(similarity))), 8)})
        return matched_units

    def _apply_common_part_consumption(
        self,
        groups: list[dict],
        *,
        covered_units: list[dict],
        consume_fraction: float,
        prune_threshold: float,
    ) -> None:
        matched_ids = {str(unit.get("unit_id", "")) for unit in covered_units if str(unit.get("unit_id", ""))}
        effective_fraction = max(0.0, min(1.0, float(consume_fraction)))
        retained_groups = []
        for group in groups:
            retained_units = []
            for unit in group.get("units", []):
                unit_id = str(unit.get("unit_id", ""))
                cloned = dict(unit)
                if unit_id in matched_ids:
                    cloned["er"] = round(max(0.0, float(cloned.get("er", 0.0)) * (1.0 - effective_fraction)), 8)
                    cloned["ev"] = round(max(0.0, float(cloned.get("ev", 0.0)) * (1.0 - effective_fraction)), 8)
                    cloned["total_energy"] = round(float(cloned.get("er", 0.0)) + float(cloned.get("ev", 0.0)), 8)
                    if cloned["total_energy"] <= prune_threshold:
                        continue
                retained_units.append(cloned)
            if not retained_units:
                continue
            retained_groups.append({**group, "units": retained_units})
        groups[:] = retained_groups

    def _select_anchor_unit(
        self,
        remaining_units: list[dict],
        *,
        structure_store=None,
        pointer_index=None,
        round_index: int = 1,
        current_packet_preseeded_ids: set[str] | None = None,
    ) -> dict | None:
        current_tick = int(self._config.get("_current_tick_number", 0) or 0)
        blocked_ids = {
            str(value or "").strip()
            for value in set(current_packet_preseeded_ids or set())
            if str(value or "").strip()
        }
        selected: dict | None = None
        selected_key: tuple[float, int, int] | None = None
        for unit in remaining_units:
            fatigue_key = self._anchor_fatigue_key(unit)
            score = self._anchor_selection_score(
                unit,
                current_tick=current_tick,
                structure_store=structure_store,
                pointer_index=pointer_index,
                round_index=round_index,
                current_packet_preseeded_ids=blocked_ids,
                fatigue_key=fatigue_key,
            )
            try:
                group_index = int(unit.get("group_index", 0))
            except Exception:
                group_index = 0
            try:
                sequence_index = int(unit.get("sequence_index", 0))
            except Exception:
                sequence_index = 0
            key = (-float(score), group_index, sequence_index)
            if selected_key is None or key < selected_key:
                selected_key = key
                selected = unit
        if selected is None:
            return None
        selected = dict(selected)
        self._mark_anchor_fatigue(selected, current_tick=current_tick)
        return selected

    def _anchor_selection_score(
        self,
        unit: dict,
        *,
        current_tick: int,
        structure_store=None,
        pointer_index=None,
        round_index: int = 1,
        current_packet_preseeded_ids: set[str] | None = None,
        fatigue_key: str | None = None,
    ) -> float:
        score = float(self._anchor_score_with_fatigue(unit, current_tick=current_tick, fatigue_key=fatigue_key))
        if structure_store is None:
            return score
        structure_id = self._find_context_free_atomic_structure_id_for_unit(
            unit,
            structure_store=structure_store,
            pointer_index=pointer_index,
        )
        if not structure_id:
            return score
        score += max(0.0, float(self._config.get("stimulus_anchor_existing_structure_bonus", 0.18) or 0.18))
        if self._anchor_owner_has_residual_entries(structure_id=structure_id, structure_store=structure_store):
            bonus = max(0.0, float(self._config.get("stimulus_anchor_owner_residual_bonus", 0.85) or 0.85))
            unit_energy = max(0.0, float(unit.get("er", 0.0) or 0.0) + float(unit.get("ev", 0.0) or 0.0))
            energy_half = max(
                1e-9,
                float(self._config.get("stimulus_anchor_owner_residual_bonus_energy_half", 0.12) or 0.12),
            )
            score += bonus * (unit_energy / (unit_energy + energy_half))
        if structure_id in (current_packet_preseeded_ids or set()):
            score -= max(0.0, float(self._config.get("stimulus_anchor_current_packet_preseed_penalty", 0.12) or 0.12))
        left_to_right_rounds = max(0, int(self._config.get("stimulus_anchor_left_to_right_bias_rounds", 1) or 1))
        if bool(self._config.get("stimulus_anchor_left_to_right_bias_enabled", True)) and int(round_index) <= left_to_right_rounds:
            try:
                group_index = max(0, int(unit.get("group_index", 0) or 0))
            except Exception:
                group_index = 0
            try:
                sequence_index = max(0, int(unit.get("sequence_index", 0) or 0))
            except Exception:
                sequence_index = 0
            group_penalty = max(0.0, float(self._config.get("stimulus_anchor_group_position_penalty", 0.35) or 0.35))
            sequence_penalty = max(0.0, float(self._config.get("stimulus_anchor_sequence_position_penalty", 0.18) or 0.18))
            score -= (group_index * group_penalty) + (sequence_index * sequence_penalty)
        score *= self._anchor_same_packet_repeat_scale(unit, fatigue_key=fatigue_key)
        return round(score, 8)

    def _anchor_owner_has_residual_entries(self, *, structure_id: str, structure_store) -> bool:
        structure_id = str(structure_id or "").strip()
        if not structure_id or structure_store is None:
            return False
        cache_enabled = bool(self._config.get("stimulus_anchor_owner_residual_presence_cache_enabled", True))
        cache = None
        if cache_enabled and isinstance(self._runtime_cache, dict):
            cache = self._runtime_cache.setdefault("anchor_owner_residual_presence", {})
            if isinstance(cache, dict) and structure_id in cache:
                self._increment_runtime_metric("anchor_owner_residual_presence_cache_hit_count")
                return bool(cache[structure_id])
        try:
            owner_db = structure_store.get_db_by_owner(structure_id)
        except Exception:
            owner_db = None
        shared_cache_key = None
        if (
            isinstance(owner_db, dict)
            and bool(self._config.get("stimulus_anchor_owner_residual_presence_shared_cache_enabled", True))
            and hasattr(structure_store, "get_shared_runtime_cache_entry")
        ):
            shared_cache_key = (
                "anchor_owner_residual_presence",
                structure_id,
                str(owner_db.get("structure_db_id", "") or ""),
                int(owner_db.get("updated_at", 0) or 0),
                len(list(owner_db.get("diff_table", []) or [])),
            )
            shared_cached = structure_store.get_shared_runtime_cache_entry(
                "stimulus_anchor_owner_residual_presence",
                shared_cache_key,
            )
            if isinstance(shared_cached, bool):
                self._increment_runtime_metric("anchor_owner_residual_presence_shared_cache_hit_count")
                if isinstance(cache, dict):
                    cache[structure_id] = bool(shared_cached)
                return bool(shared_cached)
        self._increment_runtime_metric("anchor_owner_residual_presence_scan_count")
        has_residual = False
        if isinstance(owner_db, dict):
            for entry in owner_db.get("diff_table", []) or []:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("entry_type", "") or "") in {"raw_residual", "structure_ref"}:
                    has_residual = True
                    break
        if isinstance(cache, dict):
            cache[structure_id] = bool(has_residual)
        if (
            shared_cache_key is not None
            and bool(self._config.get("stimulus_anchor_owner_residual_presence_shared_cache_enabled", True))
            and hasattr(structure_store, "set_shared_runtime_cache_entry")
        ):
            structure_store.set_shared_runtime_cache_entry(
                "stimulus_anchor_owner_residual_presence",
                shared_cache_key,
                bool(has_residual),
            )
            self._increment_runtime_metric("anchor_owner_residual_presence_shared_cache_store_count")
        return bool(has_residual)

    def _find_context_free_atomic_structure_id_for_unit(self, unit: dict, *, structure_store, pointer_index=None) -> str:
        token = str(unit.get("token", "") or "").strip()
        if not token:
            return ""
        cached = None
        try:
            cached = self._get_cached_atomic_structure(unit=unit, structure_store=structure_store)
        except Exception:
            cached = None
        if isinstance(cached, dict):
            return str(cached.get("id", "") or "")
        unit_signature = str(unit.get("unit_signature", "") or f"F:{token}")
        candidate_ids: list[str] = []
        if pointer_index is not None and hasattr(pointer_index, "query_candidates_by_signature"):
            signatures = []
            if unit_signature:
                signatures.append(f"U[{unit_signature}]")
                signatures.append(unit_signature)
            signatures.append(token)
            seen_candidate_ids: set[str] = set()
            for signature in signatures:
                try:
                    queried_ids = pointer_index.query_candidates_by_signature(str(signature))
                except Exception:
                    queried_ids = []
                for candidate_id in queried_ids or []:
                    candidate_id = str(candidate_id or "")
                    if candidate_id and candidate_id not in seen_candidate_ids:
                        seen_candidate_ids.add(candidate_id)
                        candidate_ids.append(candidate_id)
            if candidate_ids:
                self._increment_runtime_metric("anchor_atomic_lookup_index_candidate_count", len(candidate_ids))
        for candidate_id in candidate_ids:
            structure_obj = structure_store.get(candidate_id)
            if not isinstance(structure_obj, dict):
                continue
            structure = structure_obj.get("structure", {}) if isinstance(structure_obj.get("structure", {}), dict) else {}
            if list(structure.get("flat_tokens", []) or []) != [token]:
                continue
            signature = str(structure.get("content_signature", "") or structure.get("semantic_signature", "") or "")
            if unit_signature and signature and unit_signature not in signature:
                continue
            if _candidate_has_identity_context(structure_obj):
                continue
            self._put_cached_atomic_structure(unit=unit, structure_obj=structure_obj)
            self._increment_runtime_metric("anchor_atomic_lookup_index_hit_count")
            return str(structure_obj.get("id", "") or "")
        if candidate_ids:
            self._increment_runtime_metric("anchor_atomic_lookup_index_miss_count")
        self._increment_runtime_metric("anchor_atomic_lookup_full_scan_count")
        for structure_obj in structure_store.iter_structures():
            if not isinstance(structure_obj, dict):
                continue
            structure = structure_obj.get("structure", {}) if isinstance(structure_obj.get("structure", {}), dict) else {}
            if list(structure.get("flat_tokens", []) or []) != [token]:
                continue
            signature = str(structure.get("content_signature", "") or structure.get("semantic_signature", "") or "")
            if unit_signature and signature and unit_signature not in signature:
                continue
            if _candidate_has_identity_context(structure_obj):
                continue
            self._put_cached_atomic_structure(unit=unit, structure_obj=structure_obj)
            return str(structure_obj.get("id", "") or "")
        return ""

    def _anchor_score_with_fatigue(
        self,
        unit: dict,
        *,
        current_tick: int,
        round_index: int = 1,
        fatigue_key: str | None = None,
    ) -> float:
        base_score = float(self._anchor_score(unit))
        return round(base_score * self._anchor_fatigue_scale(unit, current_tick=current_tick, fatigue_key=fatigue_key), 8)

    def _anchor_fatigue_scale(self, unit: dict, *, current_tick: int, fatigue_key: str | None = None) -> float:
        if not bool(self._config.get("stimulus_anchor_fatigue_enabled", True)):
            return 1.0
        key = fatigue_key if fatigue_key is not None else self._anchor_fatigue_key(unit)
        if not key:
            return 1.0
        state = self._anchor_fatigue.get(key, {})
        fatigue = self._decayed_anchor_fatigue(state=state, current_tick=current_tick)
        floor = max(0.0, min(1.0, float(self._config.get("stimulus_anchor_fatigue_floor_scale", 0.03) or 0.03)))
        return round(max(floor, 1.0 / (1.0 + max(0.0, fatigue))), 8)

    def _anchor_same_packet_repeat_scale(self, unit: dict, *, fatigue_key: str | None = None) -> float:
        if not bool(self._config.get("stimulus_anchor_same_packet_repeat_fatigue_enabled", True)):
            return 1.0
        key = fatigue_key if fatigue_key is not None else self._anchor_fatigue_key(unit)
        if not key:
            return 1.0
        selected_counts = self._runtime_cache.get("anchor_selected_counts", {}) if isinstance(self._runtime_cache, dict) else {}
        if not isinstance(selected_counts, dict):
            return 1.0
        try:
            same_packet_count = max(0, int(selected_counts.get(key, 0) or 0))
        except Exception:
            same_packet_count = 0
        if same_packet_count <= 0:
            return 1.0
        fatigue = same_packet_count * max(0.0, float(self._config.get("stimulus_anchor_same_packet_repeat_fatigue_step", 2.5) or 2.5))
        floor = max(0.0, min(1.0, float(self._config.get("stimulus_anchor_fatigue_floor_scale", 0.03) or 0.03)))
        return round(max(floor, 1.0 / (1.0 + max(0.0, fatigue))), 8)

    def _anchor_score(self, unit: dict) -> float:
        er = float(unit.get("er", 0.0))
        ev = float(unit.get("ev", 0.0))
        score = (
            er * float(self._config.get("stimulus_anchor_er_weight", 1.25))
            + ev * float(self._config.get("stimulus_anchor_ev_weight", 0.9))
        )
        if unit.get("source_type") != "internal":
            score += float(self._config.get("stimulus_anchor_external_bonus", 0.08))
        if unit.get("is_punctuation"):
            score *= float(self._config.get("stimulus_anchor_punctuation_penalty", 0.35))
        else:
            score += float(self._config.get("stimulus_anchor_non_punctuation_bonus", 0.05))
        if str(unit.get("unit_role", "")) == "attribute" and not bool(unit.get("display_visible", False)):
            score *= max(
                0.0,
                min(
                    1.0,
                    float(self._config.get("stimulus_anchor_hidden_attribute_score_scale", 0.22)),
                ),
            )
        return round(score, 8)

    def _mark_anchor_fatigue(self, unit: dict, *, current_tick: int) -> None:
        if not bool(self._config.get("stimulus_anchor_fatigue_enabled", True)):
            return
        key = self._anchor_fatigue_key(unit)
        if not key:
            return
        state = self._anchor_fatigue.setdefault(key, {})
        fatigue = self._decayed_anchor_fatigue(state=state, current_tick=current_tick)
        step = max(0.0, float(self._config.get("stimulus_anchor_fatigue_step", 0.75) or 0.75))
        cap = max(0.01, float(self._config.get("stimulus_anchor_fatigue_cap", 32.0) or 32.0))
        state["value"] = round(min(cap, fatigue + step), 8)
        state["last_tick"] = float(current_tick)
        if isinstance(self._runtime_cache, dict):
            selected_counts = self._runtime_cache.setdefault("anchor_selected_counts", {})
            if isinstance(selected_counts, dict):
                selected_counts[key] = max(0, int(selected_counts.get(key, 0) or 0)) + 1
        self._prune_anchor_fatigue(current_tick=current_tick)

    def _decayed_anchor_fatigue(self, *, state: dict, current_tick: int) -> float:
        value = max(0.0, float(state.get("value", 0.0) or 0.0))
        try:
            last_tick = int(state.get("last_tick", current_tick) or current_tick)
        except Exception:
            last_tick = int(current_tick)
        elapsed = max(0, int(current_tick) - last_tick)
        if elapsed <= 0 or value <= 0.0:
            return value
        decay = max(0.0, min(1.0, float(self._config.get("stimulus_anchor_fatigue_decay_per_tick", 0.90) or 0.90)))
        value *= decay ** elapsed
        return 0.0 if value < 1e-9 else round(value, 8)

    def _anchor_fatigue_key(self, unit: dict) -> str:
        token = str(unit.get("token", "") or unit.get("unit_signature", "") or "").strip()
        if not token:
            return ""
        parts = [
            f"token={token}",
            f"role={str(unit.get('unit_role', '') or '').strip() or '<none>'}",
            f"attr={str(unit.get('attribute_name', '') or '').strip() or '<none>'}",
            f"ctx_type={str(unit.get('context_ref_object_type', '') or '').strip() or '<none>'}",
            f"ctx_ref={str(unit.get('context_ref_object_id', '') or '').strip() or '<none>'}",
            f"ctx_owner={str(unit.get('context_owner_structure_id', '') or '').strip() or '<none>'}",
        ]
        return "anchor|" + "|".join(parts)

    def _prune_anchor_fatigue(self, *, current_tick: int) -> None:
        if len(self._anchor_fatigue) <= int(self._config.get("stimulus_anchor_fatigue_max_entries", 4096) or 4096):
            return
        keep_after = int(current_tick) - max(10, int(self._config.get("stimulus_anchor_fatigue_keep_ticks", 256) or 256))
        for key, state in list(self._anchor_fatigue.items()):
            try:
                last_tick = int(state.get("last_tick", 0) or 0)
            except Exception:
                last_tick = 0
            if last_tick < keep_after:
                self._anchor_fatigue.pop(key, None)

    @staticmethod
    def _is_punctuation_token(token: str) -> bool:
        text = str(token or "").strip()
        if not text:
            return True
        for char in text:
            if char.isalnum() or "\u4e00" <= char <= "\u9fff":
                return False
        return True

    @staticmethod
    def _dedupe_preserve_order(items: list[str]) -> list[str]:
        seen = set()
        ordered = []
        for item in items:
            text = str(item)
            if not text or text in seen:
                continue
            seen.add(text)
            ordered.append(text)
        return ordered


