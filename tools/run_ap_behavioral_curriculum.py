# -*- coding: utf-8 -*-
"""Run and summarize AP behavioral-curriculum experiment datasets.

This is a thin local helper around the existing Observatory experiment runner.
It does not change AP runtime logic; it only starts bounded runs and writes a
compact metrics summary for audit/review.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from observatory._app import ObservatoryApp
from observatory.experiment.llm_analysis import review_run_with_llm
from observatory.experiment.runner import RunOptions, run_dataset
from observatory.experiment.storage import DatasetFileRef, make_run_dir, resolve_run_dir


SUMMARY_KEYS = [
    "pool_active_item_count",
    "pool_total_er",
    "pool_total_ev",
    "pool_ev_to_er_ratio",
    "hdb_structure_count",
    "hdb_group_count",
    "hdb_signature_index_count",
    "hdb_contextual_structure_count",
    "hdb_multi_context_structure_count",
    "hdb_same_content_multi_context_count",
    "hdb_contextual_diff_entry_count",
    "hdb_diff_entry_with_memory_ref_count",
    "hdb_residual_diff_entry_count",
    "induction_growth_target_count",
    "induction_growth_identity_hit_count",
    "induction_growth_identity_created_count",
    "induction_growth_identity_local_cache_hit_count",
    "induction_growth_identity_shared_cache_hit_count",
    "induction_growth_identity_shared_cache_stale_count",
    "induction_growth_identity_lookup_disabled_count",
    "induction_growth_identity_create_exact_lookup_skipped_count",
    "induction_growth_deduped_count",
    "induction_growth_pruned_low_energy_count",
    "induction_growth_runtime_only_count",
    "induction_growth_total_delta_er",
    "induction_growth_total_delta_ev",
    "induction_growth_source_component_er_total",
    "induction_growth_residual_component_ev_total",
    "induction_owner_runtime_budget_selected_count",
    "induction_owner_runtime_budget_pruned_count",
    "timing_induction_target_apply_ms",
    "induction_growth_target_apply_ref_fast_merge_enabled",
    "induction_growth_target_apply_fast_ref_hit_merge_count",
    "induction_growth_target_apply_insert_log_enabled",
    "induction_growth_target_apply_insert_log_suppressed_count",
    "stimulus_object_projection_total",
    "stimulus_new_structure_count",
    "stimulus_unhandled_residual_total",
    "stimulus_object_projection_to_unhandled_residual_ratio",
    "stimulus_object_projection_dominates_unhandled_residual",
    "stimulus_memory_tail_absorbed_total",
    "stimulus_owner_runtime_budget_selected_count",
    "stimulus_owner_runtime_budget_pruned_count",
    "pool_runtime_resolution_degraded_item_count",
    "pool_runtime_resolution_active_component_count",
    "pool_runtime_resolution_dropped_component_count",
    "maintenance_runtime_resolution_degraded_item_count",
    "maintenance_runtime_resolution_refreshed_item_count",
    "residual_tail_memory_projection_applied",
    "residual_tail_memory_projection_handled",
    "runtime_residual_package_applied",
    "cache_priority_consumed_er",
    "cache_priority_consumed_ev",
    "internal_sa_count",
    "attention_energy_budget",
    "attention_energy_budget_base",
    "attention_net_delta_energy",
    "attention_mod_attention_energy_budget",
    "iesm_action_trigger_weather_stub_count",
    "action_node_count",
    "action_node_attention_focus_count",
    "action_node_weather_stub_count",
    "action_executed_weather_stub",
    "action_executed_weather_stub_source_visible",
    "action_attempted_weather_stub",
    "action_scheduled_weather_stub",
    "action_drive_weather_stub_max",
    "action_effective_threshold_weather_stub_mean",
    "action_threshold_scale_mean",
    "action_threshold_nt_scale_mean",
    "action_threshold_rwd_pun_scale_mean",
    "action_threshold_fatigue_scale_mean",
    "action_learning_reward_drive_gain_total",
    "action_learning_punish_drive_penalty_total",
    "action_learning_threshold_delta_mean",
    "action_learning_threshold_delta_sum",
    "action_executed_recall",
    "action_attempted_recall",
    "time_sensor_delayed_task_table_size",
    "time_sensor_delayed_task_registered_count",
    "time_sensor_memory_used_count",
    "teacher_applied_count",
    "teacher_rwd",
    "teacher_pun",
    "teacher_reward_signal_live_total_energy",
    "teacher_punish_signal_live_total_energy",
    "reward_signal_live_total_energy",
    "punish_signal_live_total_energy",
    "cfs_signal_count",
    "cfs_surprise_max",
    "cfs_surprise_live_total_energy",
    "cfs_dissonance_max",
    "cfs_dissonance_live_total_energy",
    "cfs_pressure_max",
    "cfs_pressure_live_total_energy",
    "cfs_complexity_max",
    "cfs_complexity_live_total_energy",
    "cfs_repetition_max",
    "cfs_repetition_live_total_energy",
    "cfs_grasp_max",
    "cfs_grasp_live_total_energy",
    "cfs_correct_event_max",
    "cfs_correct_event_live_total_energy",
    "cfs_correctness_live_total_energy",
    "cfs_expectation_live_total_energy",
    "cfs_relief_live_total_energy",
    "cfs_reassurance_live_total_energy",
    "nt_DA",
    "nt_ADR",
    "nt_OXY",
    "nt_SER",
    "nt_END",
    "nt_COR",
    "nt_NOV",
    "nt_FOC",
    "timing_total_logic_ms",
    "timing_stimulus_level_ms",
    "timing_induction_and_memory_ms",
]

EXPERIMENT_TAGS = [f"E{i:02d}" for i in range(1, 11)]
SEGMENT_SOURCE_TICK_SIZE = 300
TOP_SAMPLE_SOURCE_TICK_INTERVAL = 100
TOP5_SNAPSHOT_SOURCE_TICK_INTERVAL = 50
TOP_DISPLAY_MAX_CHARS = 180
WINDOW_TEXT_MAX_CHARS = 120
PERFORMANCE_SLOW_TICK_LIMIT = 12


PERFORMANCE_ROW_KEYS = [
    "timing_total_logic_ms",
    "timing_stimulus_level_ms",
    "timing_induction_and_memory_ms",
    "timing_induction_hdb_propagation_ms",
    "timing_induction_projection_prepare_ms",
    "timing_induction_target_apply_ms",
    "timing_cache_neutralization_ms",
    "timing_attention_ms",
    "timing_memory_runtime_projection_ms",
    "hdb_structure_count",
    "induction_growth_target_count",
    "induction_growth_identity_created_count",
    "induction_growth_identity_hit_count",
    "induction_growth_identity_shared_cache_hit_count",
    "induction_growth_identity_local_cache_hit_count",
    "stimulus_best_match_candidate_count",
    "stimulus_shadow_raw_residual_candidate_count",
    "stimulus_shadow_raw_residual_skipped_count",
    "stimulus_cut_common_part_total_count",
    "stimulus_cut_cache_store_count",
    "stimulus_cut_cache_hit_count",
    "stimulus_cut_cache_zero_copy_hit_count",
    "stimulus_cut_normalize_reusable_hit_count",
    "stimulus_cut_normalize_reusable_group_count",
    "stimulus_cut_reindex_fast_path_hit_count",
    "stimulus_cut_normalized_unit_subset_group_fast_path_hit_count",
    "stimulus_cut_signature_fast_path_hit_count",
    "stimulus_local_child_candidate_count",
    "stimulus_owner_runtime_budget_selected_count",
    "stimulus_owner_runtime_budget_pruned_count",
    "stimulus_owner_local_residual_fuzzy_equivalent_call_count",
    "stimulus_owner_local_residual_fuzzy_equivalent_cache_hit_count",
    "stimulus_owner_local_residual_fuzzy_unit_bucket_pruned_count",
    "stimulus_anchor_owner_residual_presence_cache_hit_count",
    "induction_raw_residual_entry_count",
    "induction_owner_runtime_budget_selected_count",
    "induction_owner_runtime_budget_pruned_count",
    "induction_raw_residual_existing_structure_target_count",
    "induction_raw_residual_projection_profile_cache_store_count",
    "induction_raw_residual_projection_profile_shared_cache_hit_count",
    "induction_cut_normalize_reusable_hit_count",
    "induction_cut_normalize_reusable_group_count",
]


def _quiet_progress_cb(_: dict[str, Any]) -> None:
    return None


def _to_float(value: Any) -> float | None:
    try:
        result = float(value)
    except Exception:
        return None
    if not math.isfinite(result):
        return None
    return result


def _round_float(value: Any, digits: int = 6) -> float | None:
    num = _to_float(value)
    if num is None:
        return None
    return round(num, int(digits))


def _short_text(value: Any, max_chars: int = TOP_DISPLAY_MAX_CHARS) -> str:
    text = str(value or "").replace("\n", " ").strip()
    limit = int(max(8, max_chars))
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "…"


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if isinstance(payload, dict):
                yield payload


def _ref_key(item: dict[str, Any]) -> str:
    ref_type = str(item.get("ref_object_type", "") or "")
    ref_id = str(item.get("ref_object_id", "") or "")
    if ref_type or ref_id:
        return f"{ref_type}:{ref_id}"
    item_id = str(item.get("item_id", "") or "")
    return item_id or _short_text(item.get("display", ""), 64)


def _compact_top_item(item: Any, *, rank_fallback: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"rank": int(rank_fallback), "display": _short_text(item)}
    out = {
        "rank": int(item.get("rank", rank_fallback) or rank_fallback),
        "ref": _ref_key(item),
        "ref_object_type": str(item.get("ref_object_type", "") or ""),
        "ref_object_id": str(item.get("ref_object_id", "") or ""),
        "display": _short_text(item.get("display", "")),
        "about": _short_text(item.get("about", ""), 140),
        "role": str(item.get("role", "") or ""),
        "attribute_name": str(item.get("attribute_name", "") or ""),
        "ref_alias_count": _round_float(item.get("ref_alias_count"), 3),
        "semantic_signature_len": _round_float(item.get("semantic_signature_len"), 3),
        "semantic_context_key_len": _round_float(item.get("semantic_context_key_len"), 3),
        "context_owner_id": str(item.get("context_owner_id", "") or ""),
        "context_owner_structure_id": str(item.get("context_owner_structure_id", "") or ""),
        "context_path_depth": _round_float(item.get("context_path_depth"), 3),
        "attribute_count": _round_float(item.get("attribute_count"), 3),
        "er": _round_float(item.get("er")),
        "ev": _round_float(item.get("ev")),
        "cp": _round_float(item.get("cp")),
        "total_energy": _round_float(item.get("total_energy")),
        "context_ref": str(item.get("context_ref_object_id", "") or ""),
        "target_display": _short_text(item.get("target_display", ""), 90),
    }
    return {key: value for key, value in out.items() if value not in ("", None)}


def _compact_top_list(value: Any) -> list[dict[str, Any]]:
    items = value if isinstance(value, list) else []
    return [_compact_top_item(item, rank_fallback=idx + 1) for idx, item in enumerate(items[:5])]


def _top_shape(items: list[dict[str, Any]]) -> dict[str, Any]:
    type_counts = Counter(str(item.get("ref_object_type", "") or "unknown") for item in items)
    structure_count = sum(1 for item in items if str(item.get("ref_object_type", "")) == "st")
    atomic_count = sum(1 for item in items if str(item.get("ref_object_type", "")) == "sa")
    action_count = sum(1 for item in items if str(item.get("ref_object_type", "")) == "action_node")
    attribute_count = sum(1 for item in items if str(item.get("role", "")) == "attribute" or item.get("attribute_name"))
    return {
        "count": len(items),
        "structure_count": structure_count,
        "atomic_sa_count": atomic_count,
        "action_node_count": action_count,
        "attribute_count": attribute_count,
        "type_counts": dict(type_counts),
    }


def _display_quality(item: dict[str, Any]) -> dict[str, Any]:
    display = str(item.get("display", "") or "")
    raw_display = str(item.get("raw_display", "") or "")
    about = str(item.get("about", "") or "")
    ref_type = str(item.get("ref_object_type", "") or "")
    text = display or raw_display or about
    char_count = len(text)
    separator_count = text.count(" / ") + text.count(" || ") + text.count(" + ")
    spaced_char_like = 0
    if text:
        tokens = [token for token in text.replace("{", " ").replace("}", " ").split() if token]
        spaced_char_like = sum(1 for token in tokens if len(token) == 1)
    return {
        "is_structure": 1 if ref_type == "st" else 0,
        "is_atomic_sa": 1 if ref_type == "sa" else 0,
        "is_action_node": 1 if ref_type == "action_node" else 0,
        "is_attribute": 1 if str(item.get("role", "")) == "attribute" or item.get("attribute_name") else 0,
        "display_chars": char_count,
        "separator_count": separator_count,
        "spaced_char_like_count": spaced_char_like,
        "signature_len": _round_float(item.get("semantic_signature_len")) or 0.0,
        "context_key_len": _round_float(item.get("semantic_context_key_len")) or 0.0,
        "alias_count": _round_float(item.get("ref_alias_count")) or 0.0,
        "attribute_count": _round_float(item.get("attribute_count")) or 0.0,
        "context_owner_structure_id": str(item.get("context_owner_structure_id", "") or ""),
        "context_ref_object_id": str(item.get("context_ref_object_id", "") or ""),
    }


def _quality_summary(top_lists: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for axis, items in top_lists.items():
        qualities = [_display_quality(item) for item in items if isinstance(item, dict)]
        if not qualities:
            out[axis] = {}
            continue
        count = len(qualities)
        structure_count = sum(int(q["is_structure"]) for q in qualities)
        atomic_count = sum(int(q["is_atomic_sa"]) for q in qualities)
        action_count = sum(int(q["is_action_node"]) for q in qualities)
        attribute_count = sum(int(q["is_attribute"]) for q in qualities)
        long_structure_count = sum(
            1
            for q in qualities
            if int(q["is_structure"]) and (float(q["display_chars"]) >= 60 or float(q["signature_len"]) >= 40)
        )
        char_fragment_like_count = sum(
            1
            for q in qualities
            if float(q["spaced_char_like_count"]) >= 8 or float(q["separator_count"]) >= 8
        )
        owner_ids = [str(q["context_owner_structure_id"]) for q in qualities if q.get("context_owner_structure_id")]
        owner_counts = Counter(owner_ids)
        out[axis] = {
            "count": count,
            "structure_ratio": round(structure_count / max(1, count), 6),
            "atomic_sa_ratio": round(atomic_count / max(1, count), 6),
            "action_node_ratio": round(action_count / max(1, count), 6),
            "attribute_ratio": round(attribute_count / max(1, count), 6),
            "long_structure_count": long_structure_count,
            "char_fragment_like_count": char_fragment_like_count,
            "mean_signature_len": round(
                sum(float(q["signature_len"]) for q in qualities) / max(1, count), 6
            ),
            "mean_context_key_len": round(
                sum(float(q["context_key_len"]) for q in qualities) / max(1, count), 6
            ),
            "mean_alias_count": round(
                sum(float(q["alias_count"]) for q in qualities) / max(1, count), 6
            ),
            "dominant_context_owner_structure_id": owner_counts.most_common(1)[0][0] if owner_counts else "",
            "dominant_context_owner_share": (
                round(owner_counts.most_common(1)[0][1] / max(1, len(owner_ids)), 6) if owner_counts else 0.0
            ),
        }
    return out


def _aggregate_top5_quality(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for axis in ("er", "ev", "cp"):
        axis_items: list[dict[str, Any]] = []
        owner_counter: Counter[str] = Counter()
        for snapshot in snapshots:
            quality = snapshot.get("top5_quality") if isinstance(snapshot, dict) else {}
            item = quality.get(axis) if isinstance(quality, dict) else {}
            if not isinstance(item, dict) or not item:
                continue
            axis_items.append(item)
            owner = str(item.get("dominant_context_owner_structure_id", "") or "")
            if owner:
                owner_counter[owner] += 1
        if not axis_items:
            out[axis] = {}
            continue
        count = len(axis_items)

        def mean(key: str) -> float:
            return round(sum(float(item.get(key) or 0.0) for item in axis_items) / max(1, count), 6)

        out[axis] = {
            "snapshot_count": count,
            "mean_structure_ratio": mean("structure_ratio"),
            "mean_atomic_sa_ratio": mean("atomic_sa_ratio"),
            "mean_action_node_ratio": mean("action_node_ratio"),
            "mean_attribute_ratio": mean("attribute_ratio"),
            "long_structure_snapshot_count": sum(1 for item in axis_items if int(item.get("long_structure_count") or 0) > 0),
            "char_fragment_like_snapshot_count": sum(
                1 for item in axis_items if int(item.get("char_fragment_like_count") or 0) > 0
            ),
            "mean_signature_len": mean("mean_signature_len"),
            "mean_context_key_len": mean("mean_context_key_len"),
            "mean_alias_count": mean("mean_alias_count"),
            "dominant_context_owner_top5": [
                {"context_owner_structure_id": owner, "snapshot_count": count}
                for owner, count in owner_counter.most_common(5)
            ],
        }
    return out


def _stats_subset(values: dict[str, list[float]], keys: list[str]) -> dict[str, Any]:
    return {key: _stats(list(values.get(key, []) or [])) for key in keys}


def _identity_resolution_summary_from_totals(
    totals: dict[str, float],
    *,
    stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target = float(totals.get("induction_growth_target_count", 0.0) or 0.0)
    created = float(totals.get("induction_growth_identity_created_count", 0.0) or 0.0)
    hit = float(totals.get("induction_growth_identity_hit_count", 0.0) or 0.0)
    shared = float(totals.get("induction_growth_identity_shared_cache_hit_count", 0.0) or 0.0)
    local = float(totals.get("induction_growth_identity_local_cache_hit_count", 0.0) or 0.0)
    deduped = float(totals.get("induction_growth_deduped_count", 0.0) or 0.0)
    skipped = float(totals.get("induction_growth_identity_create_exact_lookup_skipped_count", 0.0) or 0.0)
    disabled = float(totals.get("induction_growth_identity_lookup_disabled_count", 0.0) or 0.0)
    stale = float(totals.get("induction_growth_identity_shared_cache_stale_count", 0.0) or 0.0)
    unresolved_created = max(0.0, created - skipped)
    out: dict[str, Any] = {
        "totals": {
            "target": round(target, 6),
            "exact_hit": round(hit, 6),
            "created": round(created, 6),
            "shared_cache_hit": round(shared, 6),
            "local_cache_hit": round(local, 6),
            "deduped": round(deduped, 6),
            "create_exact_lookup_skipped": round(skipped, 6),
            "lookup_disabled": round(disabled, 6),
            "shared_cache_stale": round(stale, 6),
            "created_not_explained_by_create_exact_skip": round(unresolved_created, 6),
        },
        "ratios": {
            "exact_hit_to_target": round(hit / max(1.0, target), 6),
            "created_to_target": round(created / max(1.0, target), 6),
            "created_to_hit_plus_created": round(created / max(1.0, hit + created), 6),
            "exact_hit_to_hit_plus_created": round(hit / max(1.0, hit + created), 6),
            "shared_cache_hit_to_target": round(shared / max(1.0, target), 6),
            "local_cache_hit_to_target": round(local / max(1.0, target), 6),
            "deduped_to_target": round(deduped / max(1.0, target), 6),
            "create_exact_lookup_skipped_to_created": round(skipped / max(1.0, created), 6),
            "create_exact_lookup_skipped_to_target": round(skipped / max(1.0, target), 6),
            "created_not_explained_by_create_exact_skip_to_created": round(unresolved_created / max(1.0, created), 6),
            "lookup_disabled_to_target": round(disabled / max(1.0, target), 6),
            "shared_cache_stale_to_target": round(stale / max(1.0, target), 6),
        },
        "interpretation_hints": [
            "exact_hit is only the strict identity-reuse path; cache hits and deduped targets are separate reuse evidence.",
            "create_exact_lookup_skipped matching created means many creations came from the create path that did not run exact lookup, so low exact_hit should not be read alone.",
        ],
    }
    if stats:
        out["nonzero_tick_counts"] = {
            "exact_hit": (stats.get("induction_growth_identity_hit_count", {}) or {}).get("nonzero_count"),
            "created": (stats.get("induction_growth_identity_created_count", {}) or {}).get("nonzero_count"),
            "shared_cache_hit": (stats.get("induction_growth_identity_shared_cache_hit_count", {}) or {}).get("nonzero_count"),
            "local_cache_hit": (stats.get("induction_growth_identity_local_cache_hit_count", {}) or {}).get("nonzero_count"),
            "create_exact_lookup_skipped": (
                stats.get("induction_growth_identity_create_exact_lookup_skipped_count", {}) or {}
            ).get("nonzero_count"),
            "lookup_disabled": (stats.get("induction_growth_identity_lookup_disabled_count", {}) or {}).get("nonzero_count"),
            "shared_cache_stale": (stats.get("induction_growth_identity_shared_cache_stale_count", {}) or {}).get("nonzero_count"),
        }
    return out


def _top_overlap(prev: list[dict[str, Any]], current: list[dict[str, Any]]) -> dict[str, Any]:
    prev_refs = {_ref for _ref in (str(item.get("ref", "") or "") for item in prev) if _ref}
    cur_refs = {_ref for _ref in (str(item.get("ref", "") or "") for item in current) if _ref}
    if not prev_refs and not cur_refs:
        return {"retained_count": 0, "jaccard": 0.0}
    inter = prev_refs & cur_refs
    union = prev_refs | cur_refs
    return {
        "retained_count": len(inter),
        "jaccard": round(len(inter) / max(1, len(union)), 6),
    }


def _top_root_id(item: dict[str, Any]) -> str:
    owner = str(item.get("context_owner_structure_id", "") or "")
    if owner:
        return owner
    ref_type = str(item.get("ref_object_type", "") or "")
    ref_id = str(item.get("ref_object_id", "") or "")
    if ref_type == "st" and ref_id:
        return ref_id
    context_ref = str(item.get("context_ref", "") or "")
    if context_ref:
        return context_ref
    return str(item.get("ref", "") or "")


def _top_root_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    roots = [_top_root_id(item) for item in items if isinstance(item, dict)]
    roots = [root for root in roots if root]
    if not roots:
        return {
            "item_count": len(items),
            "unique_root_count": 0,
            "duplicate_root_count": 0,
            "dominant_root_id": "",
            "dominant_root_count": 0,
            "dominant_root_share": 0.0,
        }
    counts = Counter(roots)
    dominant, dominant_count = counts.most_common(1)[0]
    return {
        "item_count": len(items),
        "unique_root_count": len(counts),
        "duplicate_root_count": max(0, len(roots) - len(counts)),
        "dominant_root_id": dominant,
        "dominant_root_count": int(dominant_count),
        "dominant_root_share": round(dominant_count / max(1, len(roots)), 6),
        "repeated_roots": [
            {"root_id": root, "count": count}
            for root, count in counts.most_common(5)
            if count > 1
        ],
    }


def _top_root_overlap(prev: list[dict[str, Any]], current: list[dict[str, Any]]) -> dict[str, Any]:
    prev_roots = {_root for _root in (_top_root_id(item) for item in prev if isinstance(item, dict)) if _root}
    cur_roots = {_root for _root in (_top_root_id(item) for item in current if isinstance(item, dict)) if _root}
    if not prev_roots and not cur_roots:
        return {"retained_count": 0, "jaccard": 0.0}
    inter = prev_roots & cur_roots
    union = prev_roots | cur_roots
    return {
        "retained_count": len(inter),
        "previous_count": len(prev_roots),
        "current_count": len(cur_roots),
        "jaccard": round(len(inter) / max(1, len(union)), 6),
    }


def _aggregate_top_root_summary(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for axis in ("er", "ev", "cp"):
        root_counter: Counter[str] = Counter()
        summary_items: list[dict[str, Any]] = []
        overlap_items: list[dict[str, Any]] = []
        for snapshot in snapshots:
            root_summary = snapshot.get("top5_root_summary") if isinstance(snapshot, dict) else {}
            item = root_summary.get(axis) if isinstance(root_summary, dict) else {}
            if isinstance(item, dict) and item:
                summary_items.append(item)
                dominant = str(item.get("dominant_root_id", "") or "")
                if dominant:
                    root_counter[dominant] += 1
            root_overlap = snapshot.get("root_overlap_with_previous_snapshot") if isinstance(snapshot, dict) else {}
            overlap = root_overlap.get(axis) if isinstance(root_overlap, dict) else {}
            if isinstance(overlap, dict) and overlap:
                overlap_items.append(overlap)
        if not summary_items:
            out[axis] = {}
            continue
        count = len(summary_items)

        def mean(key: str) -> float:
            return round(sum(float(item.get(key) or 0.0) for item in summary_items) / max(1, count), 6)

        out[axis] = {
            "snapshot_count": count,
            "mean_unique_root_count": mean("unique_root_count"),
            "mean_duplicate_root_count": mean("duplicate_root_count"),
            "mean_dominant_root_share": mean("dominant_root_share"),
            "snapshots_with_duplicate_roots": sum(
                1 for item in summary_items if int(item.get("duplicate_root_count", 0) or 0) > 0
            ),
            "mean_root_overlap_jaccard": (
                round(sum(float(item.get("jaccard") or 0.0) for item in overlap_items) / max(1, len(overlap_items)), 6)
                if overlap_items
                else 0.0
            ),
            "dominant_root_top5": [
                {"root_id": root, "snapshot_count": count}
                for root, count in root_counter.most_common(5)
            ],
        }
    return out


def _correlation(xs: list[float], ys: list[float]) -> float | None:
    if not xs or len(xs) != len(ys):
        return None
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denom_x = sum((x - mean_x) ** 2 for x in xs)
    denom_y = sum((y - mean_y) ** 2 for y in ys)
    if denom_x <= 0.0 or denom_y <= 0.0:
        return None
    return numerator / math.sqrt(denom_x * denom_y)


def _short_row_performance(row: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "timing_total_logic_ms",
        "timing_stimulus_level_ms",
        "timing_induction_and_memory_ms",
        "timing_induction_hdb_propagation_ms",
        "hdb_structure_count",
        "induction_growth_target_count",
        "induction_growth_identity_created_count",
        "induction_growth_identity_shared_cache_hit_count",
        "stimulus_best_match_candidate_count",
        "stimulus_shadow_raw_residual_candidate_count",
        "stimulus_owner_runtime_budget_selected_count",
        "stimulus_owner_runtime_budget_pruned_count",
        "stimulus_cut_common_part_total_count",
        "stimulus_cut_cache_store_count",
        "stimulus_cut_normalize_reusable_group_count",
        "stimulus_owner_local_residual_fuzzy_equivalent_call_count",
        "induction_owner_runtime_budget_selected_count",
        "induction_owner_runtime_budget_pruned_count",
        "induction_raw_residual_entry_count",
    ]
    out: dict[str, Any] = {
        "tick_index": row.get("tick_index"),
        "source_dataset_tick_index": row.get("source_dataset_tick_index"),
        "synthetic_tick": bool(row.get("synthetic_tick", False)) or str(row.get("tick_source", "")) == "synthetic",
        "input_is_empty": bool(row.get("input_is_empty", False)),
        "input_text_preview": _short_text(row.get("input_text_preview", ""), 80),
    }
    for key in keys:
        value = _round_float(row.get(key))
        if value is not None:
            out[key] = value
    return out


def _build_performance_hdb_diagnostic_summary(
    *,
    rows: list[dict[str, Any]],
    segmented_stats: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    source_rows = [
        row
        for row in rows
        if not (bool(row.get("synthetic_tick", False)) or str(row.get("tick_source", "")) == "synthetic")
    ]
    total_values = [_to_float(row.get("timing_total_logic_ms")) or 0.0 for row in rows]
    if not total_values:
        return {
            "available": False,
            "interpretation_hints": [
                "No per-tick timing rows were available, so performance slow-tail diagnosis could not be built.",
            ],
        }

    timing_breakdown = _stats_subset(
        {key: [_to_float(row.get(key)) or 0.0 for row in rows] for key in PERFORMANCE_ROW_KEYS},
        [
            "timing_total_logic_ms",
            "timing_stimulus_level_ms",
            "timing_induction_and_memory_ms",
            "timing_induction_hdb_propagation_ms",
            "timing_induction_projection_prepare_ms",
            "timing_induction_target_apply_ms",
            "timing_cache_neutralization_ms",
            "timing_attention_ms",
            "timing_memory_runtime_projection_ms",
        ],
    )
    slow_rows = sorted(
        rows,
        key=lambda row: _to_float(row.get("timing_total_logic_ms")) or 0.0,
        reverse=True,
    )[:PERFORMANCE_SLOW_TICK_LIMIT]

    correlations: list[dict[str, Any]] = []
    for key in PERFORMANCE_ROW_KEYS:
        if key == "timing_total_logic_ms":
            continue
        values = [_to_float(row.get(key)) or 0.0 for row in rows]
        corr = _correlation(values, total_values)
        if corr is None or abs(corr) < 0.2:
            continue
        correlations.append(
            {
                "key": key,
                "corr_with_total_logic_ms": round(corr, 6),
                "sum": round(sum(values), 6),
                "max": round(max(values), 6) if values else 0.0,
            }
        )
    correlations.sort(key=lambda item: abs(float(item.get("corr_with_total_logic_ms") or 0.0)), reverse=True)

    segment_timing = []
    for item in segmented_stats:
        if not isinstance(item, dict):
            continue
        stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
        hdb = item.get("hdb_growth") if isinstance(item.get("hdb_growth"), dict) else {}
        segment_timing.append(
            {
                "segment_index": item.get("segment_index"),
                "source_tick_start": item.get("source_tick_start"),
                "source_tick_end": item.get("source_tick_end"),
                "source_rows": item.get("source_rows"),
                "timing_total_logic_ms": stats.get("timing_total_logic_ms", {}),
                "timing_stimulus_level_ms": stats.get("timing_stimulus_level_ms", {}),
                "timing_induction_and_memory_ms": stats.get("timing_induction_and_memory_ms", {}),
                "hdb_growth": hdb,
            }
        )

    completion = manifest.get("completion_timing") if isinstance(manifest.get("completion_timing"), dict) else {}
    first_hdb = _round_float(source_rows[0].get("hdb_structure_count")) if source_rows else None
    last_hdb = _round_float(source_rows[-1].get("hdb_structure_count")) if source_rows else None
    return {
        "available": True,
        "interpretation_hints": [
            "This diagnostic is observability-only: correlations locate slow-tail companions, not strict causal proof.",
            "A large completion flush can come from delayed HDB persistence batching; it does not imply structures were invisible during the tick loop.",
            "If late segments slow while HDB count rises, first inspect stimulus candidate fanout/cut/normalization and induction HDB propagation before changing theory logic.",
        ],
        "completion_timing": completion,
        "hdb_structure_count_first_source_tick": first_hdb,
        "hdb_structure_count_latest_source_tick": last_hdb,
        "hdb_structure_count_delta_source_ticks": (
            round(float(last_hdb) - float(first_hdb), 6)
            if first_hdb is not None and last_hdb is not None
            else None
        ),
        "timing_breakdown": timing_breakdown,
        "segment_timing_trend": segment_timing,
        "slowest_ticks_by_total_logic_ms": [_short_row_performance(row) for row in slow_rows],
        "top_correlated_metrics_with_total_logic_ms": correlations[:20],
    }


def _sum_row_keys(row: dict[str, Any], keys: list[str]) -> float:
    total = 0.0
    for key in keys:
        value = _to_float(row.get(key))
        if value is not None:
            total += value
    return total


def _row_slice(row: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in keys:
        value = row.get(key)
        if isinstance(value, (int, float, bool)):
            rounded = _round_float(value)
            out[key] = rounded if rounded is not None else value
        elif value not in (None, ""):
            out[key] = _short_text(value, 160)
    return out


def _first_tick_with(rows: list[dict[str, Any]], key: str) -> int | None:
    for row in rows:
        value = _to_float(row.get(key))
        if value is not None and abs(value) > 1e-12:
            tick = row.get("source_dataset_tick_index")
            if tick is None:
                tick = row.get("tick_index")
            try:
                return int(tick)
            except Exception:
                return None
    return None


def _last_tick_with(rows: list[dict[str, Any]], key: str) -> int | None:
    for row in reversed(rows):
        value = _to_float(row.get(key))
        if value is not None and abs(value) > 1e-12:
            tick = row.get("source_dataset_tick_index")
            if tick is None:
                tick = row.get("tick_index")
            try:
                return int(tick)
            except Exception:
                return None
    return None


def _max_row_value(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [_to_float(row.get(key)) for row in rows]
    values = [value for value in values if value is not None]
    if not values:
        return None
    return round(max(values), 6)


def _sum_row_value(rows: list[dict[str, Any]], key: str) -> float:
    return round(sum(float(value) for value in (_to_float(row.get(key)) for row in rows) if value is not None), 6)


def _build_action_causal_chain_summary(
    rows: list[dict[str, Any]],
    *,
    outcome: Any,
    spec_id: Any,
) -> dict[str, Any]:
    executed_sum = _sum_row_value(rows, "action_executed_weather_stub_source_visible")
    attempted_sum = _sum_row_value(rows, "action_attempted_weather_stub_source_visible")
    scheduled_sum = _sum_row_value(rows, "action_scheduled_weather_stub_source_visible")
    ready_sum = _sum_row_value(rows, "action_ready_weather_stub_count")
    trigger_sum = _sum_row_value(rows, "iesm_action_trigger_weather_stub_count_source_visible")
    max_margin = _max_row_value(rows, "action_drive_margin_weather_stub_max")
    reward_live_max = _max_row_value(rows, "reward_signal_live_total_energy")
    punish_live_max = _max_row_value(rows, "punish_signal_live_total_energy")
    expectation_live_max = _max_row_value(rows, "cfs_expectation_live_total_energy")
    pressure_live_max = _max_row_value(rows, "cfs_pressure_live_total_energy")
    nt_keys = ["nt_DA", "nt_ADR", "nt_OXY", "nt_SER", "nt_END", "nt_COR", "nt_NOV", "nt_FOC"]
    nt_max = {key: _max_row_value(rows, key) for key in nt_keys}
    nt_max = {key: value for key, value in nt_max.items() if value is not None and abs(value) > 1e-12}
    return {
        "spec_id": str(spec_id or ""),
        "outcome": str(outcome or ""),
        "window_row_count": len(rows),
        "weather_action": {
            "trigger_source_visible_sum": trigger_sum,
            "ready_sum": ready_sum,
            "attempted_source_visible_sum": attempted_sum,
            "scheduled_source_visible_sum": scheduled_sum,
            "executed_source_visible_sum": executed_sum,
            "first_trigger_tick": _first_tick_with(rows, "iesm_action_trigger_weather_stub_count_source_visible"),
            "first_attempt_tick": _first_tick_with(rows, "action_attempted_weather_stub_source_visible"),
            "first_scheduled_tick": _first_tick_with(rows, "action_scheduled_weather_stub_source_visible"),
            "first_executed_tick": _first_tick_with(rows, "action_executed_weather_stub_source_visible"),
            "last_executed_tick": _last_tick_with(rows, "action_executed_weather_stub_source_visible"),
            "max_drive": _max_row_value(rows, "action_drive_weather_stub_max"),
            "max_threshold": _max_row_value(rows, "action_effective_threshold_weather_stub_mean"),
            "max_margin": max_margin,
            "positive_margin_seen": bool(max_margin is not None and max_margin > 0),
        },
        "cfs_reward_punish": {
            "teacher_applied_sum": _sum_row_value(rows, "teacher_applied_count"),
            "teacher_reward_sum": _sum_row_value(rows, "teacher_rwd"),
            "teacher_punish_sum": _sum_row_value(rows, "teacher_pun"),
            "reward_live_max": reward_live_max,
            "punish_live_max": punish_live_max,
            "expectation_live_max": expectation_live_max,
            "pressure_live_max": pressure_live_max,
            "dissonance_live_max": _max_row_value(rows, "cfs_dissonance_live_total_energy"),
            "correct_event_live_max": _max_row_value(rows, "cfs_correct_event_live_total_energy"),
            "grasp_live_max": _max_row_value(rows, "cfs_grasp_live_total_energy"),
            "relief_live_max": _max_row_value(rows, "cfs_relief_live_total_energy"),
        },
        "nt_attention_threshold": {
            "nt_max": nt_max,
            "attention_budget_max": _max_row_value(rows, "attention_energy_budget"),
            "attention_net_delta_max": _max_row_value(rows, "attention_net_delta_energy"),
            "threshold_scale_max": _max_row_value(rows, "action_threshold_scale_mean"),
            "threshold_nt_scale_max": _max_row_value(rows, "action_threshold_nt_scale_mean"),
            "threshold_rwd_pun_scale_max": _max_row_value(rows, "action_threshold_rwd_pun_scale_mean"),
            "threshold_fatigue_scale_max": _max_row_value(rows, "action_threshold_fatigue_scale_mean"),
            "learning_reward_drive_gain_sum": _sum_row_value(rows, "action_learning_reward_drive_gain_total"),
            "learning_punish_drive_penalty_sum": _sum_row_value(rows, "action_learning_punish_drive_penalty_total"),
            "learning_threshold_delta_sum": _sum_row_value(rows, "action_learning_threshold_delta_sum"),
        },
        "chain_flags": {
            "trigger_to_attempt": bool(trigger_sum > 0 and attempted_sum > 0),
            "attempt_to_execute": bool(attempted_sum > 0 and executed_sum > 0),
            "trigger_to_no_execute": bool(trigger_sum > 0 and executed_sum <= 0),
            "reward_or_expectation_present": bool(
                (reward_live_max is not None and reward_live_max > 0)
                or (expectation_live_max is not None and expectation_live_max > 0)
            ),
            "punish_or_pressure_present": bool(
                (punish_live_max is not None and punish_live_max > 0)
                or (pressure_live_max is not None and pressure_live_max > 0)
            ),
            "nt_present": bool(nt_max),
        },
    }


def _identity_ratios_from_totals(totals: dict[str, float]) -> dict[str, float]:
    hit = float(totals.get("induction_growth_identity_hit_count", 0.0) or 0.0)
    created = float(totals.get("induction_growth_identity_created_count", 0.0) or 0.0)
    target = float(totals.get("induction_growth_target_count", 0.0) or 0.0)
    shared = float(totals.get("induction_growth_identity_shared_cache_hit_count", 0.0) or 0.0)
    local = float(totals.get("induction_growth_identity_local_cache_hit_count", 0.0) or 0.0)
    deduped = float(totals.get("induction_growth_deduped_count", 0.0) or 0.0)
    skipped = float(totals.get("induction_growth_identity_create_exact_lookup_skipped_count", 0.0) or 0.0)
    disabled = float(totals.get("induction_growth_identity_lookup_disabled_count", 0.0) or 0.0)
    stale = float(totals.get("induction_growth_identity_shared_cache_stale_count", 0.0) or 0.0)
    return {
        "hit_to_hit_plus_created": round(hit / max(1.0, hit + created), 6),
        "created_to_target": round(created / max(1.0, target), 6),
        "hit_to_target": round(hit / max(1.0, target), 6),
        "shared_cache_hit_to_target": round(shared / max(1.0, target), 6),
        "local_cache_hit_to_target": round(local / max(1.0, target), 6),
        "deduped_to_target": round(deduped / max(1.0, target), 6),
        "create_exact_lookup_skipped_to_created": round(skipped / max(1.0, created), 6),
        "create_exact_lookup_skipped_to_target": round(skipped / max(1.0, target), 6),
        "lookup_disabled_to_target": round(disabled / max(1.0, target), 6),
        "shared_cache_stale_to_target": round(stale / max(1.0, target), 6),
    }


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "nonzero_count": 0,
            "first_nonzero_tick": None,
            "last_nonzero_tick": None,
            "min": 0.0,
            "max": 0.0,
            "mean": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "latest": 0.0,
            "sum": 0.0,
        }
    sorted_values = sorted(values)

    def percentile(p: float) -> float:
        if not sorted_values:
            return 0.0
        idx = min(len(sorted_values) - 1, max(0, int(round((len(sorted_values) - 1) * p))))
        return sorted_values[idx]

    return {
        "count": len(values),
        "nonzero_count": sum(1 for v in values if abs(v) > 1e-12),
        "first_nonzero_tick": None,
        "last_nonzero_tick": None,
        "min": round(min(values), 8),
        "max": round(max(values), 8),
        "mean": round(statistics.fmean(values), 8),
        "p50": round(percentile(0.50), 8),
        "p95": round(percentile(0.95), 8),
        "latest": round(values[-1], 8),
        "sum": round(sum(values), 8),
    }


def _new_segment(index: int) -> dict[str, Any]:
    start = int(index) * SEGMENT_SOURCE_TICK_SIZE
    end = start + SEGMENT_SOURCE_TICK_SIZE - 1
    return {
        "segment_index": int(index),
        "source_tick_start": int(start),
        "source_tick_end": int(end),
        "rows": 0,
        "source_rows": 0,
        "synthetic_rows": 0,
        "values": defaultdict(list),
    }


def _read_manifest(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "manifest.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def summarize_run(run_id: str) -> dict[str, Any]:
    run_dir = resolve_run_dir(run_id)
    metrics_path = run_dir / "metrics.jsonl"
    events_path = run_dir / "expectation_contract_events.jsonl"
    manifest = _read_manifest(run_dir)
    values: dict[str, list[float]] = {key: [] for key in SUMMARY_KEYS}
    first_nonzero: dict[str, int | None] = {key: None for key in SUMMARY_KEYS}
    last_nonzero: dict[str, int | None] = {key: None for key in SUMMARY_KEYS}
    by_experiment: dict[str, dict[str, Any]] = {
        tag: {"rows": 0, "source_text_rows": 0, "synthetic_rows": 0} for tag in EXPERIMENT_TAGS
    }
    row_count = 0
    source_rows = 0
    synthetic_rows = 0
    text_rows = 0
    empty_rows = 0
    top_er_counter: Counter[str] = Counter()
    top_ev_counter: Counter[str] = Counter()
    segments: dict[int, dict[str, Any]] = {}
    top_samples: list[dict[str, Any]] = []
    top5_snapshots: list[dict[str, Any]] = []
    sampled_source_ticks: set[int] = set()
    snapshot_source_ticks: set[int] = set()
    last_top_snapshot: dict[str, list[dict[str, Any]]] = {}
    rows_by_source_tick: dict[int, dict[str, Any]] = {}
    all_metric_rows: list[dict[str, Any]] = []
    source_tick_max = -1
    synthetic_tick_indices: list[int] = []

    if metrics_path.exists():
        for row in _iter_jsonl(metrics_path):
            all_metric_rows.append(row)
            row_count += 1
            tick_index = int(row.get("tick_index", row_count - 1) or (row_count - 1))
            is_synthetic = bool(row.get("synthetic_tick", False)) or str(row.get("tick_source", "")) == "synthetic"
            if is_synthetic:
                synthetic_rows += 1
                synthetic_tick_indices.append(tick_index)
                source_dataset_tick_index = None
            else:
                source_rows += 1
                source_dataset_tick_index = int(row.get("source_dataset_tick_index", tick_index) or tick_index)
                source_tick_max = max(source_tick_max, source_dataset_tick_index)
                rows_by_source_tick[source_dataset_tick_index] = row
            segment_index = int(max(0, source_dataset_tick_index or 0)) // SEGMENT_SOURCE_TICK_SIZE
            segment = segments.setdefault(segment_index, _new_segment(segment_index))
            segment["rows"] += 1
            if is_synthetic:
                segment["synthetic_rows"] += 1
            else:
                segment["source_rows"] += 1
            is_empty = bool(row.get("input_is_empty", False))
            if is_empty:
                empty_rows += 1
            else:
                text_rows += 1
            tags = [str(x) for x in row.get("tags", []) or []]
            for tag in EXPERIMENT_TAGS:
                if tag in tags:
                    by_experiment[tag]["rows"] += 1
                    if is_synthetic:
                        by_experiment[tag]["synthetic_rows"] += 1
                    elif not is_empty:
                        by_experiment[tag]["source_text_rows"] += 1
            for key in SUMMARY_KEYS:
                value = _to_float(row.get(key))
                if value is None:
                    continue
                values[key].append(value)
                segment["values"][key].append(value)
                if abs(value) > 1e-12:
                    if first_nonzero[key] is None:
                        first_nonzero[key] = tick_index
                    last_nonzero[key] = tick_index
            er_top = row.get("pool_er_top5") if isinstance(row.get("pool_er_top5"), list) else []
            ev_top = row.get("pool_ev_top5") if isinstance(row.get("pool_ev_top5"), list) else []
            if er_top and isinstance(er_top[0], dict):
                top_er_counter[str(er_top[0].get("display", "") or "")[:160]] += 1
            if ev_top and isinstance(ev_top[0], dict):
                top_ev_counter[str(ev_top[0].get("display", "") or "")[:160]] += 1
            compact_er_top = _compact_top_list(er_top)
            compact_ev_top = _compact_top_list(ev_top)
            compact_cp_top = _compact_top_list(row.get("pool_cp_top5", []) if isinstance(row.get("pool_cp_top5"), list) else [])
            if (
                source_dataset_tick_index is not None
                and source_dataset_tick_index % TOP_SAMPLE_SOURCE_TICK_INTERVAL == 0
                and source_dataset_tick_index not in sampled_source_ticks
            ):
                sampled_source_ticks.add(source_dataset_tick_index)
                top_samples.append(
                    {
                        "source_dataset_tick_index": int(source_dataset_tick_index),
                        "tick_index": int(tick_index),
                        "input_is_empty": bool(is_empty),
                        "input_text_preview": str(row.get("input_text_preview", "") or "")[:120],
                        "pool_er_top5": compact_er_top,
                        "pool_ev_top5": compact_ev_top,
                        "pool_cp_top5": compact_cp_top,
                    }
                )
            if (
                source_dataset_tick_index is not None
                and source_dataset_tick_index % TOP5_SNAPSHOT_SOURCE_TICK_INTERVAL == 0
                and source_dataset_tick_index not in snapshot_source_ticks
            ):
                snapshot_source_ticks.add(source_dataset_tick_index)
                identity_totals = {
                    key: float(row.get(key) or 0.0)
                    for key in [
                        "induction_growth_target_count",
                        "induction_growth_identity_hit_count",
                        "induction_growth_identity_created_count",
                        "induction_growth_identity_local_cache_hit_count",
                        "induction_growth_identity_shared_cache_hit_count",
                        "induction_growth_deduped_count",
                    ]
                }
                top5_snapshots.append(
                    {
                        "source_dataset_tick_index": int(source_dataset_tick_index),
                        "tick_index": int(tick_index),
                        "input_is_empty": bool(is_empty),
                        "input_text_preview": _short_text(row.get("input_text_preview", ""), WINDOW_TEXT_MAX_CHARS),
                        "pool_shape_counts": {
                            "er": _top_shape(compact_er_top),
                            "ev": _top_shape(compact_ev_top),
                            "cp": _top_shape(compact_cp_top),
                        },
                        "top5_quality": _quality_summary(
                            {"er": compact_er_top, "ev": compact_ev_top, "cp": compact_cp_top}
                        ),
                        "top5_root_summary": {
                            "er": _top_root_summary(compact_er_top),
                            "ev": _top_root_summary(compact_ev_top),
                            "cp": _top_root_summary(compact_cp_top),
                        },
                        "overlap_with_previous_snapshot": {
                            "er": _top_overlap(last_top_snapshot.get("er", []), compact_er_top),
                            "ev": _top_overlap(last_top_snapshot.get("ev", []), compact_ev_top),
                            "cp": _top_overlap(last_top_snapshot.get("cp", []), compact_cp_top),
                        },
                        "root_overlap_with_previous_snapshot": {
                            "er": _top_root_overlap(last_top_snapshot.get("er", []), compact_er_top),
                            "ev": _top_root_overlap(last_top_snapshot.get("ev", []), compact_ev_top),
                            "cp": _top_root_overlap(last_top_snapshot.get("cp", []), compact_cp_top),
                        },
                        "identity_at_tick": {
                            "target_count": _round_float(row.get("induction_growth_target_count")),
                            "hit_count": _round_float(row.get("induction_growth_identity_hit_count")),
                            "created_count": _round_float(row.get("induction_growth_identity_created_count")),
                            "shared_cache_hit_count": _round_float(row.get("induction_growth_identity_shared_cache_hit_count")),
                            "local_cache_hit_count": _round_float(row.get("induction_growth_identity_local_cache_hit_count")),
                            "ratios": _identity_ratios_from_totals(identity_totals),
                        },
                        "action_weather_at_tick": _row_slice(
                            row,
                            [
                                "iesm_action_trigger_weather_stub_count",
                                "action_node_weather_stub_count",
                                "action_drive_weather_stub_max",
                                "action_effective_threshold_weather_stub_mean",
                                "action_attempted_weather_stub_source_visible",
                                "action_scheduled_weather_stub_source_visible",
                                "action_executed_weather_stub_source_visible",
                            ],
                        ),
                        "pool_er_top5": compact_er_top,
                        "pool_ev_top5": compact_ev_top,
                        "pool_cp_top5": compact_cp_top,
                    }
                )
                last_top_snapshot = {"er": compact_er_top, "ev": compact_ev_top, "cp": compact_cp_top}

    summary_stats: dict[str, Any] = {}
    for key, vals in values.items():
        item = _stats(vals)
        item["first_nonzero_tick"] = first_nonzero[key]
        item["last_nonzero_tick"] = last_nonzero[key]
        summary_stats[key] = item

    segmented_stats: list[dict[str, Any]] = []
    segment_keys = [
        "hdb_structure_count",
        "hdb_group_count",
        "hdb_signature_index_count",
        "hdb_contextual_structure_count",
        "hdb_multi_context_structure_count",
        "hdb_same_content_multi_context_count",
        "hdb_contextual_diff_entry_count",
        "hdb_diff_entry_with_memory_ref_count",
        "induction_growth_target_count",
        "induction_growth_identity_hit_count",
        "induction_growth_identity_created_count",
        "induction_growth_identity_local_cache_hit_count",
        "induction_growth_identity_shared_cache_hit_count",
        "induction_growth_identity_lookup_disabled_count",
        "induction_growth_identity_create_exact_lookup_skipped_count",
        "induction_growth_deduped_count",
        "induction_growth_pruned_low_energy_count",
        "induction_growth_runtime_only_count",
        "induction_growth_total_delta_er",
        "induction_growth_total_delta_ev",
        "induction_growth_source_component_er_total",
        "induction_growth_residual_component_ev_total",
        "pool_active_item_count",
        "pool_ev_to_er_ratio",
        "pool_runtime_resolution_degraded_item_count",
        "pool_runtime_resolution_active_component_count",
        "pool_runtime_resolution_dropped_component_count",
        "stimulus_object_projection_total",
        "stimulus_new_structure_count",
        "stimulus_unhandled_residual_total",
        "stimulus_object_projection_to_unhandled_residual_ratio",
        "stimulus_object_projection_dominates_unhandled_residual",
        "stimulus_memory_tail_absorbed_total",
        "attention_energy_budget",
        "attention_net_delta_energy",
        "action_threshold_scale_mean",
        "action_threshold_nt_scale_mean",
        "action_threshold_rwd_pun_scale_mean",
        "action_learning_reward_drive_gain_total",
        "action_learning_punish_drive_penalty_total",
        "cfs_signal_count",
        "cfs_dissonance_live_total_energy",
        "cfs_expectation_live_total_energy",
        "cfs_pressure_live_total_energy",
        "nt_DA",
        "nt_ADR",
        "nt_NOV",
        "nt_FOC",
        "timing_total_logic_ms",
        "timing_stimulus_level_ms",
        "timing_induction_and_memory_ms",
    ]
    for idx in sorted(segments.keys()):
        seg = segments[idx]
        values_map = seg.get("values", {})
        identity_totals = {
            key: sum(list(values_map.get(key, []) or []))
            for key in [
                "induction_growth_target_count",
                "induction_growth_identity_hit_count",
                "induction_growth_identity_created_count",
                "induction_growth_identity_local_cache_hit_count",
                "induction_growth_identity_shared_cache_hit_count",
                "induction_growth_identity_shared_cache_stale_count",
                "induction_growth_identity_lookup_disabled_count",
                "induction_growth_identity_create_exact_lookup_skipped_count",
                "induction_growth_deduped_count",
            ]
        }
        hdb_values = list(values_map.get("hdb_structure_count", []) or [])
        hdb_delta = 0.0
        if len(hdb_values) >= 2:
            hdb_delta = float(hdb_values[-1]) - float(hdb_values[0])
        segmented_stats.append(
            {
                "segment_index": int(seg.get("segment_index", idx)),
                "source_tick_start": int(seg.get("source_tick_start", 0)),
                "source_tick_end": int(seg.get("source_tick_end", 0)),
                "rows": int(seg.get("rows", 0)),
                "source_rows": int(seg.get("source_rows", 0)),
                "synthetic_rows": int(seg.get("synthetic_rows", 0)),
                "identity_maturation": {
                    "totals": {key: round(value, 6) for key, value in identity_totals.items()},
                    "ratios": _identity_ratios_from_totals(identity_totals),
                },
                "identity_resolution": _identity_resolution_summary_from_totals(identity_totals),
                "hdb_growth": {
                    "structure_count_first": _round_float(hdb_values[0]) if hdb_values else None,
                    "structure_count_latest": _round_float(hdb_values[-1]) if hdb_values else None,
                    "structure_count_delta": round(hdb_delta, 6),
                    "delta_per_source_row": round(hdb_delta / max(1, int(seg.get("source_rows", 0))), 6),
                },
                "stats": {
                    key: _stats(list(values_map.get(key, []) or []))
                    for key in segment_keys
                },
            }
        )

    events = []
    event_counts: Counter[str] = Counter()
    outcome_counts: Counter[str] = Counter()
    registered_by_contract: dict[str, dict[str, Any]] = {}
    if events_path.exists():
        for event in _iter_jsonl(events_path):
            events.append(event)
            event_counts[str(event.get("event", ""))] += 1
            if event.get("event") == "registered":
                registered_by_contract[str(event.get("contract_id", "") or "")] = event
            if event.get("event") == "settled":
                outcome_counts[str(event.get("outcome", ""))] += 1

    action_window_keys = [
        "iesm_action_trigger_weather_stub_count",
        "iesm_action_trigger_weather_stub_count_source_visible",
        "iesm_action_trigger_targeted_weather_stub_count",
        "iesm_action_trigger_target_missing_weather_stub_count",
        "action_node_weather_stub_count",
        "action_active_weather_stub_count",
        "action_ready_weather_stub_count",
        "action_drive_weather_stub_max",
        "action_effective_threshold_weather_stub_mean",
        "action_drive_margin_weather_stub_max",
        "action_attempted_weather_stub_source_visible",
        "action_scheduled_weather_stub_source_visible",
        "action_executed_weather_stub_source_visible",
        "action_local_lookup_hit_count_weather_stub",
        "action_local_lookup_text_fallback_hit_count_weather_stub",
        "action_local_lookup_miss_count_weather_stub",
        "action_local_reward_signal_total_weather_stub",
        "action_local_punish_signal_total_weather_stub",
        "teacher_applied_count",
        "teacher_rwd",
        "teacher_pun",
        "reward_signal_live_total_energy",
        "punish_signal_live_total_energy",
        "cfs_expectation_live_total_energy",
        "cfs_pressure_live_total_energy",
        "cfs_dissonance_live_total_energy",
        "cfs_correctness_live_total_energy",
        "cfs_correct_event_live_total_energy",
        "cfs_grasp_live_total_energy",
        "cfs_relief_live_total_energy",
        "nt_DA",
        "nt_ADR",
        "nt_OXY",
        "nt_SER",
        "nt_END",
        "nt_COR",
        "nt_NOV",
        "nt_FOC",
        "attention_energy_budget",
        "attention_net_delta_energy",
        "attention_mod_attention_energy_budget",
        "action_threshold_scale_mean",
        "action_threshold_nt_scale_mean",
        "action_threshold_rwd_pun_scale_mean",
        "action_threshold_fatigue_scale_mean",
        "action_learning_reward_drive_gain_total",
        "action_learning_punish_drive_penalty_total",
        "action_learning_threshold_delta_mean",
        "action_learning_threshold_delta_sum",
    ]
    weather_row_keys = action_window_keys[:18]
    cfs_reward_punish_keys = [
        "teacher_applied_count",
        "teacher_rwd",
        "teacher_pun",
        "reward_signal_live_total_energy",
        "punish_signal_live_total_energy",
        "cfs_expectation_live_total_energy",
        "cfs_pressure_live_total_energy",
        "cfs_dissonance_live_total_energy",
        "cfs_correctness_live_total_energy",
        "cfs_correct_event_live_total_energy",
        "cfs_grasp_live_total_energy",
        "cfs_relief_live_total_energy",
    ]
    nt_attention_action_keys = [
        "nt_DA",
        "nt_ADR",
        "nt_OXY",
        "nt_SER",
        "nt_END",
        "nt_COR",
        "nt_NOV",
        "nt_FOC",
        "attention_energy_budget",
        "attention_net_delta_energy",
        "attention_mod_attention_energy_budget",
        "action_threshold_scale_mean",
        "action_threshold_nt_scale_mean",
        "action_threshold_rwd_pun_scale_mean",
        "action_threshold_fatigue_scale_mean",
        "action_learning_reward_drive_gain_total",
        "action_learning_punish_drive_penalty_total",
        "action_learning_threshold_delta_mean",
        "action_learning_threshold_delta_sum",
    ]
    contract_windows: list[dict[str, Any]] = []
    for event in events:
        if event.get("event") != "settled":
            continue
        contract_id = str(event.get("contract_id", "") or "")
        reg = registered_by_contract.get(contract_id, {})
        try:
            start_tick = int(reg.get("source_dataset_tick_index", event.get("source_dataset_tick_index", 0)) or 0)
        except Exception:
            start_tick = 0
        try:
            end_tick = int(event.get("settled_source_tick_cursor", event.get("source_dataset_tick_index", start_tick)) or start_tick)
        except Exception:
            end_tick = start_tick
        end_tick = max(start_tick, end_tick)
        rows_in_window = [
            rows_by_source_tick[source_tick]
            for source_tick in range(start_tick, end_tick + 1)
            if source_tick in rows_by_source_tick
        ]
        aggregate: dict[str, float] = {key: 0.0 for key in action_window_keys}
        max_values: dict[str, float] = {}
        row_summaries: list[dict[str, Any]] = []
        for row in rows_in_window:
            for key in action_window_keys:
                value = _to_float(row.get(key))
                if value is None:
                    continue
                aggregate[key] += value
                max_values[key] = max(max_values.get(key, value), value)
            row_summaries.append(
                {
                    "source_dataset_tick_index": row.get("source_dataset_tick_index"),
                    "tick_index": row.get("tick_index"),
                    "input_is_empty": bool(row.get("input_is_empty", False)),
                    "input_text_preview": _short_text(row.get("input_text_preview", ""), WINDOW_TEXT_MAX_CHARS),
                    "pool_er_top1_display": _short_text(row.get("pool_er_top1_display", ""), 100),
                    "pool_ev_top1_display": _short_text(row.get("pool_ev_top1_display", ""), 100),
                    "pool_cp_top1_display": _short_text(row.get("pool_cp_top1_display", ""), 100),
                    "weather": _row_slice(row, weather_row_keys),
                    "cfs_reward_punish": _row_slice(row, cfs_reward_punish_keys),
                    "nt_attention_action": _row_slice(row, nt_attention_action_keys),
                }
            )
        contract_windows.append(
            {
                "contract_id": contract_id,
                "spec_id": event.get("spec_id"),
                "outcome": event.get("outcome"),
                "reason": event.get("reason"),
                "source_dataset_tick_start": start_tick,
                "source_dataset_tick_settled": end_tick,
                "deadline_source_tick_cursor": reg.get("deadline_source_tick_cursor", event.get("deadline_source_tick_cursor")),
                "matched_detail": event.get("matched_detail", []),
                "window_row_count": len(rows_in_window),
                "causal_chain_summary": _build_action_causal_chain_summary(
                    rows_in_window,
                    outcome=event.get("outcome"),
                    spec_id=event.get("spec_id"),
                ),
                "aggregate_sum": {key: round(value, 6) for key, value in aggregate.items() if abs(value) > 1e-12},
                "aggregate_max": {key: round(value, 6) for key, value in max_values.items() if abs(value) > 1e-12},
                "rows": row_summaries,
            }
        )

    identity_totals_all = {
        key: sum(values.get(key, []) or [])
        for key in [
            "induction_growth_target_count",
            "induction_growth_identity_hit_count",
            "induction_growth_identity_created_count",
            "induction_growth_identity_local_cache_hit_count",
            "induction_growth_identity_shared_cache_hit_count",
            "induction_growth_identity_shared_cache_stale_count",
            "induction_growth_deduped_count",
            "induction_growth_identity_lookup_disabled_count",
            "induction_growth_identity_create_exact_lookup_skipped_count",
        ]
    }
    hdb_values_all = values.get("hdb_structure_count", []) or []
    hdb_growth_summary = {
        "structure_count_first": _round_float(hdb_values_all[0]) if hdb_values_all else None,
        "structure_count_latest": _round_float(hdb_values_all[-1]) if hdb_values_all else None,
        "structure_count_delta": round(float(hdb_values_all[-1] - hdb_values_all[0]), 6) if len(hdb_values_all) >= 2 else 0.0,
        "delta_per_source_row": (
            round(float(hdb_values_all[-1] - hdb_values_all[0]) / max(1, source_rows), 6)
            if len(hdb_values_all) >= 2
            else 0.0
        ),
        "new_structure_count_sum": round(sum(values.get("stimulus_new_structure_count", []) or []), 6),
        "hdb_group_count_latest": _round_float((values.get("hdb_group_count", []) or [None])[-1]),
        "hdb_signature_index_count_latest": _round_float((values.get("hdb_signature_index_count", []) or [None])[-1]),
        "hdb_contextual_structure_count_latest": _round_float(
            (values.get("hdb_contextual_structure_count", []) or [None])[-1]
        ),
        "hdb_multi_context_structure_count_latest": _round_float(
            (values.get("hdb_multi_context_structure_count", []) or [None])[-1]
        ),
        "hdb_same_content_multi_context_count_latest": _round_float(
            (values.get("hdb_same_content_multi_context_count", []) or [None])[-1]
        ),
        "hdb_contextual_diff_entry_count_latest": _round_float(
            (values.get("hdb_contextual_diff_entry_count", []) or [None])[-1]
        ),
        "hdb_diff_entry_with_memory_ref_count_latest": _round_float(
            (values.get("hdb_diff_entry_with_memory_ref_count", []) or [None])[-1]
        ),
    }
    top5_quality_summary = _aggregate_top5_quality(top5_snapshots)
    top5_root_summary = _aggregate_top_root_summary(top5_snapshots)
    performance_hdb_diagnostic_summary = _build_performance_hdb_diagnostic_summary(
        rows=all_metric_rows,
        segmented_stats=segmented_stats,
        manifest=manifest,
    )
    target_apply_summary = _stats_subset(
        values,
        [
            "timing_induction_target_apply_ms",
            "induction_growth_target_apply_ref_fast_merge_enabled",
            "induction_growth_target_apply_fast_ref_hit_merge_count",
            "induction_growth_target_apply_insert_log_enabled",
            "induction_growth_target_apply_insert_log_suppressed_count",
        ],
    )
    runtime_resolution_summary = _stats_subset(
        values,
        [
            "pool_runtime_resolution_degraded_item_count",
            "pool_runtime_resolution_active_component_count",
            "pool_runtime_resolution_dropped_component_count",
            "maintenance_runtime_resolution_degraded_item_count",
            "maintenance_runtime_resolution_refreshed_item_count",
        ],
    )

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "manifest": {
            "status": manifest.get("status"),
            "dataset": manifest.get("dataset", {}),
            "options": manifest.get("options", {}),
            "expectation_contracts": manifest.get("expectation_contracts", {}),
            "runner_timing": manifest.get("runner_timing", {}),
            "total_wall_ms": manifest.get("total_wall_ms"),
            "tick_loop_wall_ms": manifest.get("tick_loop_wall_ms"),
            "completion_timing": manifest.get("completion_timing", {}),
            "dataset_runtime_override": manifest.get("dataset_runtime_override", {}),
        },
        "rows": {
            "metrics_rows": row_count,
            "source_rows": source_rows,
            "synthetic_rows": synthetic_rows,
            "text_rows_including_synthetic": text_rows,
            "empty_rows": empty_rows,
            "source_dataset_tick_max": source_tick_max,
            "synthetic_tick_indices": synthetic_tick_indices[:20],
        },
        "by_experiment": by_experiment,
        "stats": summary_stats,
        "segments": {
            "source_tick_size": SEGMENT_SOURCE_TICK_SIZE,
            "items": segmented_stats,
        },
        "identity_maturation": {
            "totals": {key: round(value, 6) for key, value in identity_totals_all.items()},
            "ratios": _identity_ratios_from_totals(identity_totals_all),
            "segment_source_tick_size": SEGMENT_SOURCE_TICK_SIZE,
        },
        "identity_resolution_summary": _identity_resolution_summary_from_totals(
            identity_totals_all,
            stats=summary_stats,
        ),
        "hdb_growth": hdb_growth_summary,
        "top5_quality_summary": top5_quality_summary,
        "top5_root_summary": top5_root_summary,
        "performance_hdb_diagnostic_summary": performance_hdb_diagnostic_summary,
        "target_apply_summary": target_apply_summary,
        "runtime_resolution_summary": runtime_resolution_summary,
        "expectation_events": {
            "event_counts": dict(event_counts),
            "settled_outcome_counts": dict(outcome_counts),
            "events": events,
        },
        "expectation_contract_windows": {
            "action_window_keys": action_window_keys,
            "items": contract_windows,
        },
        "top1_frequency": {
            "er": [{"display": key, "count": count} for key, count in top_er_counter.most_common(12)],
            "ev": [{"display": key, "count": count} for key, count in top_ev_counter.most_common(12)],
        },
        "top_samples": {
            "source_tick_interval": TOP_SAMPLE_SOURCE_TICK_INTERVAL,
            "items": top_samples,
        },
        "top5_snapshots": {
            "source_tick_interval": TOP5_SNAPSHOT_SOURCE_TICK_INTERVAL,
            "items": top5_snapshots,
        },
    }


def _write_summary(run_id: str, summary: dict[str, Any]) -> Path:
    run_dir = resolve_run_dir(run_id)
    out_path = run_dir / "curriculum_metrics_summary.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def write_summary(run_id: str) -> Path:
    """Public helper for tests and accumulated runs."""
    return _write_summary(run_id, summarize_run(run_id))


def _print_human_summary(summary: dict[str, Any]) -> None:
    stats = summary.get("stats", {})

    def latest(key: str) -> Any:
        return stats.get(key, {}).get("latest")

    def mean(key: str) -> Any:
        return stats.get(key, {}).get("mean")

    def nz(key: str) -> Any:
        return stats.get(key, {}).get("nonzero_count")

    print(json.dumps({
        "run_id": summary.get("run_id"),
        "status": summary.get("manifest", {}).get("status"),
        "rows": summary.get("rows"),
        "contracts": summary.get("manifest", {}).get("expectation_contracts"),
        "key_latest": {
            "hdb_structure_count": latest("hdb_structure_count"),
            "pool_active_item_count": latest("pool_active_item_count"),
            "pool_ev_to_er_ratio": latest("pool_ev_to_er_ratio"),
        },
        "key_mean": {
            "identity_hit": mean("induction_growth_identity_hit_count"),
            "identity_created": mean("induction_growth_identity_created_count"),
            "shared_cache_hit": mean("induction_growth_identity_shared_cache_hit_count"),
            "timing_total_logic_ms": mean("timing_total_logic_ms"),
        },
        "identity_maturation": summary.get("identity_maturation", {}),
        "identity_resolution_summary": summary.get("identity_resolution_summary", {}),
        "hdb_growth": summary.get("hdb_growth", {}),
        "top5_snapshot_count": len((summary.get("top5_snapshots", {}) or {}).get("items", []) or []),
        "contract_window_count": len((summary.get("expectation_contract_windows", {}) or {}).get("items", []) or []),
        "nonzero_counts": {
            "weather_executed_source_visible": nz("action_executed_weather_stub_source_visible"),
            "teacher_applied": nz("teacher_applied_count"),
            "cfs_signal": nz("cfs_signal_count"),
            "residual_tail_applied": nz("residual_tail_memory_projection_applied"),
            "runtime_residual_package": nz("runtime_residual_package_applied"),
        },
    }, ensure_ascii=False, indent=2))


def run_curriculum(args: argparse.Namespace) -> int:
    app = ObservatoryApp()
    try:
        result = run_dataset(
            app=app,
            dataset_ref=DatasetFileRef(source=args.source, rel_path=args.dataset),
            options=RunOptions(
                reset_mode=str(args.reset_mode),
                clean_run=bool(args.clean_run),
                export_json=False,
                export_html=False,
                auto_tune_enabled=bool(args.auto_tune),
                max_ticks=int(args.max_ticks) if args.max_ticks else None,
            ),
            run_id=args.run_id,
            progress_cb=None if args.progress else _quiet_progress_cb,
        )
        run_id = str(result.get("run_id") or args.run_id)
    finally:
        app.close()
    summary = summarize_run(run_id)
    out_path = _write_summary(run_id, summary)
    print(f"summary_path={out_path}")
    _print_human_summary(summary)
    if args.llm_review:
        res = review_run_with_llm(run_id=run_id)
        print(json.dumps({"llm_review": res}, ensure_ascii=False, indent=2))
    return 0


def _run_curriculum_once(
    *,
    app: ObservatoryApp,
    dataset: str,
    source: str,
    run_id: str,
    max_ticks: int | None,
    reset_mode: str,
    clean_run: bool,
    auto_tune: bool,
    progress: bool,
) -> dict[str, Any]:
    result = run_dataset(
        app=app,
        dataset_ref=DatasetFileRef(source=source, rel_path=dataset),
        options=RunOptions(
            reset_mode=str(reset_mode),
            clean_run=bool(clean_run),
            export_json=False,
            export_html=False,
            auto_tune_enabled=bool(auto_tune),
            max_ticks=int(max_ticks) if max_ticks else None,
        ),
        run_id=run_id,
        progress_cb=None if progress else _quiet_progress_cb,
    )
    actual_run_id = str(result.get("run_id") or run_id)
    summary = summarize_run(actual_run_id)
    out_path = _write_summary(actual_run_id, summary)
    return {"run_id": actual_run_id, "summary_path": str(out_path), "summary": summary}


def _build_accumulated_summary(*, batch_run_id: str, runs: list[dict[str, Any]], reset_modes: list[str]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    previous_hdb_latest: float | None = None
    for idx, entry in enumerate(runs):
        summary = entry.get("summary", {}) if isinstance(entry, dict) else {}
        stats = summary.get("stats", {}) if isinstance(summary, dict) else {}
        hdb_latest = _to_float((stats.get("hdb_structure_count", {}) or {}).get("latest"))
        hdb_delta_from_previous = None
        if hdb_latest is not None and previous_hdb_latest is not None:
            hdb_delta_from_previous = round(hdb_latest - previous_hdb_latest, 6)
        if hdb_latest is not None:
            previous_hdb_latest = hdb_latest
        items.append(
            {
                "index": idx + 1,
                "run_id": entry.get("run_id"),
                "summary_path": entry.get("summary_path"),
                "reset_mode": reset_modes[idx] if idx < len(reset_modes) else None,
                "status": (summary.get("manifest", {}) or {}).get("status"),
                "rows": summary.get("rows", {}),
                "contracts": (summary.get("manifest", {}) or {}).get("expectation_contracts", {}),
                "identity_maturation": summary.get("identity_maturation", {}),
                "identity_resolution_summary": summary.get("identity_resolution_summary", {}),
                "hdb_growth": summary.get("hdb_growth", {}),
                "hdb_structure_latest": hdb_latest,
                "hdb_structure_delta_from_previous_run": hdb_delta_from_previous,
                "top5_snapshot_count": len((summary.get("top5_snapshots", {}) or {}).get("items", []) or []),
                "contract_window_count": len((summary.get("expectation_contract_windows", {}) or {}).get("items", []) or []),
                "key_nonzero_counts": {
                    "weather_executed_source_visible": (stats.get("action_executed_weather_stub_source_visible", {}) or {}).get("nonzero_count"),
                    "teacher_applied": (stats.get("teacher_applied_count", {}) or {}).get("nonzero_count"),
                    "cfs_signal": (stats.get("cfs_signal_count", {}) or {}).get("nonzero_count"),
                    "residual_tail_applied": (stats.get("residual_tail_memory_projection_applied", {}) or {}).get("nonzero_count"),
                },
            }
        )
    first_hdb = _to_float(items[0].get("hdb_structure_latest")) if items else None
    last_hdb = _to_float(items[-1].get("hdb_structure_latest")) if items else None
    return {
        "batch_run_id": batch_run_id,
        "run_count": len(items),
        "reset_modes": reset_modes,
        "hdb_accumulated_delta_latest_minus_first": (
            round(last_hdb - first_hdb, 6) if first_hdb is not None and last_hdb is not None else None
        ),
        "items": items,
    }


def run_accumulated_curriculum(args: argparse.Namespace) -> int:
    app = ObservatoryApp()
    run_entries: list[dict[str, Any]] = []
    reset_modes: list[str] = []
    try:
        for idx in range(int(args.repeat)):
            reset_mode = str(args.first_reset_mode if idx == 0 else args.next_reset_mode)
            clean_run = bool(args.first_clean_run) if idx == 0 else False
            run_id = f"{args.run_id_prefix}_r{idx + 1:02d}"
            reset_modes.append(reset_mode)
            entry = _run_curriculum_once(
                app=app,
                dataset=args.dataset,
                source=args.source,
                run_id=run_id,
                max_ticks=int(args.max_ticks) if args.max_ticks else None,
                reset_mode=reset_mode,
                clean_run=clean_run,
                auto_tune=bool(args.auto_tune),
                progress=bool(args.progress),
            )
            run_entries.append(entry)
            print(f"completed_run={entry['run_id']} summary_path={entry['summary_path']}")
    finally:
        app.close()
    batch_summary = _build_accumulated_summary(
        batch_run_id=str(args.run_id_prefix),
        runs=run_entries,
        reset_modes=reset_modes,
    )
    batch_dir = make_run_dir(f"{args.run_id_prefix}_batch")
    out_path = batch_dir / "accumulated_curriculum_summary.json"
    out_path.write_text(json.dumps(batch_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"accumulated_summary_path={out_path}")
    print(json.dumps(batch_summary, ensure_ascii=False, indent=2))
    if args.llm_review:
        last_run_id = run_entries[-1]["run_id"] if run_entries else ""
        if last_run_id:
            res = review_run_with_llm(run_id=last_run_id)
            print(json.dumps({"llm_review_last_run": res}, ensure_ascii=False, indent=2))
    return 0


def summarize_curriculum(args: argparse.Namespace) -> int:
    summary = summarize_run(args.run_id)
    out_path = _write_summary(args.run_id, summary)
    print(f"summary_path={out_path}")
    _print_human_summary(summary)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run")
    p_run.add_argument("--dataset", required=True, help="Dataset relative path.")
    p_run.add_argument("--source", choices=["built_in", "imported"], default="built_in")
    p_run.add_argument("--run-id", required=True)
    p_run.add_argument("--max-ticks", type=int, default=None)
    p_run.add_argument("--reset-mode", choices=["keep", "clear_runtime", "clear_all"], default="clear_all")
    p_run.add_argument("--clean-run", action=argparse.BooleanOptionalAction, default=True)
    p_run.add_argument("--llm-review", action="store_true")
    p_run.add_argument("--auto-tune", action="store_true")
    p_run.add_argument("--progress", action="store_true", help="Print runner progress lines.")
    p_run.set_defaults(func=run_curriculum)

    p_acc = sub.add_parser("run-accumulated")
    p_acc.add_argument("--dataset", required=True, help="Dataset relative path.")
    p_acc.add_argument("--source", choices=["built_in", "imported"], default="built_in")
    p_acc.add_argument("--run-id-prefix", required=True)
    p_acc.add_argument("--repeat", type=int, default=3)
    p_acc.add_argument("--max-ticks", type=int, default=300)
    p_acc.add_argument("--first-reset-mode", choices=["keep", "clear_runtime", "clear_all"], default="clear_all")
    p_acc.add_argument("--next-reset-mode", choices=["keep", "clear_runtime", "clear_all"], default="clear_runtime")
    p_acc.add_argument("--first-clean-run", action=argparse.BooleanOptionalAction, default=True)
    p_acc.add_argument("--llm-review", action="store_true")
    p_acc.add_argument("--auto-tune", action="store_true")
    p_acc.add_argument("--progress", action="store_true", help="Print runner progress lines.")
    p_acc.set_defaults(func=run_accumulated_curriculum)

    p_sum = sub.add_parser("summarize")
    p_sum.add_argument("--run-id", required=True)
    p_sum.set_defaults(func=summarize_curriculum)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
