# -*- coding: utf-8 -*-
"""
Shared V2 fuzzy match scoring helpers for HDB.

Design goals:
- keep legacy retrieval eligibility semantics intact unless explicitly blended
- expose richer, soft-scored diagnostics for numeric / order / attribute / context / energy
- avoid hardcoded semantic rules; prefer small, configurable, reusable math helpers
"""

from __future__ import annotations

import math
import time
from typing import Any

from ._context_metadata import extract_context_metadata
from ._numeric_match import coerce_numeric_value, describe_numeric_match


def _bounded(value: Any, *, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except Exception:
        return float(default)
    if not math.isfinite(numeric):
        return float(default)
    return max(0.0, min(1.0, numeric))


def _positive(value: Any, *, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except Exception:
        return float(default)
    if not math.isfinite(numeric):
        return float(default)
    return max(0.0, numeric)


def _safe_mean(values: list[float]) -> float:
    cleaned = [float(value) for value in values if isinstance(value, (int, float))]
    if not cleaned:
        return 0.0
    return sum(cleaned) / max(1, len(cleaned))


def _sigmoid(value: float, *, midpoint: float, slope: float) -> float:
    safe_slope = max(1e-6, float(slope))
    try:
        result = 1.0 / (1.0 + math.exp(-(float(value) - float(midpoint)) / safe_slope))
    except OverflowError:
        result = 0.0 if value < midpoint else 1.0
    return _bounded(result)


def _hill_score(value: float, *, half_point: float, power: float) -> float:
    bounded = _bounded(value)
    if bounded <= 0.0:
        return 0.0
    safe_half = max(1e-6, min(1.0, float(half_point)))
    safe_power = max(0.2, float(power))
    numerator = pow(bounded, safe_power)
    denominator = numerator + pow(safe_half, safe_power)
    if denominator <= 0.0:
        return 0.0
    return _bounded(numerator / denominator)


def _pair_units(existing_units: list[dict], incoming_units: list[dict]) -> list[tuple[dict, dict]]:
    left = [
        dict(unit)
        for unit in existing_units
        if isinstance(unit, dict) and not bool(unit.get("is_placeholder", False))
    ]
    right = [
        dict(unit)
        for unit in incoming_units
        if isinstance(unit, dict) and not bool(unit.get("is_placeholder", False))
    ]
    left.sort(key=lambda item: (int(item.get("group_index", 0)), int(item.get("sequence_index", 0)), str(item.get("unit_id", ""))))
    right.sort(key=lambda item: (int(item.get("group_index", 0)), int(item.get("sequence_index", 0)), str(item.get("unit_id", ""))))
    pair_count = min(len(left), len(right))
    return [(left[index], right[index]) for index in range(pair_count)]


def _unit_numeric_descriptors(unit: dict) -> list[dict[str, float | int | str]]:
    if not isinstance(unit, dict):
        return []
    content = unit.get("content", {})
    if not isinstance(content, dict):
        content = {}
    descriptors: list[dict[str, float | int | str]] = []
    seen: set[tuple[str, float, int, int, str]] = set()

    meta = unit.get("meta", {})
    if not isinstance(meta, dict):
        meta = {}
    content_meta = content.get("meta", {})
    if not isinstance(content_meta, dict):
        content_meta = {}
    ext_meta = meta.get("ext", {})
    if not isinstance(ext_meta, dict):
        ext_meta = {}
    content_ext_meta = content_meta.get("ext", {})
    if not isinstance(content_ext_meta, dict):
        content_ext_meta = {}

    def _is_time_like_descriptor() -> bool:
        merged_ext = {}
        if isinstance(content_ext_meta, dict):
            merged_ext.update(content_ext_meta)
        if isinstance(ext_meta, dict):
            merged_ext.update(ext_meta)
        if any(
            key in merged_ext
            for key in (
                "time_bucket_id",
                "time_bucket_ref_object_id",
                "time_bucket_center_sec",
                "time_bucket_center_value",
                "time_basis",
                "delta_sec",
                "delta_value",
            )
        ):
            return True
        family_name = str(unit.get("attribute_name", content.get("attribute_name", "")) or "").strip()
        return family_name == "时间感受"

    is_time_like = _is_time_like_descriptor()

    def _push_descriptor(*, family: Any, value: Any, source: str, semantic_kind: str = "") -> None:
        family_name = str(family or "").strip()
        numeric_value = coerce_numeric_value(value)
        if not family_name or numeric_value is None:
            return
        try:
            sequence_index = int(unit.get("sequence_index", 0))
        except Exception:
            sequence_index = 0
        try:
            group_index = int(unit.get("group_index", 0))
        except Exception:
            group_index = 0
        signature = (family_name, round(float(numeric_value), 8), sequence_index, group_index, str(source or ""))
        if signature in seen:
            return
        seen.add(signature)
        descriptors.append(
            {
                "family": family_name,
                "value": round(float(numeric_value), 8),
                "sequence_index": sequence_index,
                "group_index": group_index,
                "source": str(source or ""),
                "semantic_kind": str(semantic_kind or ("time_like" if is_time_like else "")),
            }
        )

    role = str(unit.get("unit_role", unit.get("role", "")) or "").strip().lower()
    value_type = str(unit.get("value_type", content.get("value_type", "")) or "").strip().lower()
    attribute_family = str(unit.get("attribute_name", content.get("attribute_name", "")) or "").strip()
    attribute_value = unit.get("attribute_value", content.get("attribute_value", None))
    if attribute_family and (role == "attribute" or value_type == "numerical" or attribute_value is not None):
        _push_descriptor(family=attribute_family, value=attribute_value, source="attribute")

    for slot_key in ("structure_numeric_slots", "average_numeric_slots"):
        slots = unit.get(slot_key, content.get(slot_key, []))
        if not isinstance(slots, list):
            continue
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            _push_descriptor(
                family=slot.get("family", ""),
                value=slot.get("value", None),
                source=slot_key,
                semantic_kind=str(slot.get("semantic_kind", "") or ""),
            )

    return descriptors


def _collect_numeric_descriptors(units: list[dict]) -> list[dict[str, float | int | str]]:
    descriptors: list[dict[str, float | int | str]] = []
    for unit in units:
        descriptors.extend(_unit_numeric_descriptors(unit))
    descriptors.sort(
        key=lambda item: (
            str(item.get("family", "")),
            int(item.get("group_index", 0)),
            int(item.get("sequence_index", 0)),
            str(item.get("source", "")),
        )
    )
    return descriptors


def _numeric_similarity(
    *,
    config: dict,
    left_descriptor: dict[str, float | int | str],
    right_descriptor: dict[str, float | int | str],
) -> float:
    match = describe_numeric_match(
        left_value=left_descriptor.get("value"),
        right_value=right_descriptor.get("value"),
        family=str(left_descriptor.get("family", "") or ""),
        abs_tolerance=float(config.get("numeric_match_abs_tolerance", 0.2)),
        rel_tolerance=float(config.get("numeric_match_rel_tolerance", 0.35)),
        min_similarity=0.0,
    )
    if match is None:
        return 0.0
    return _bounded(match.get("similarity", 0.0))


def _numeric_family_score(
    *,
    config: dict,
    left_descriptors: list[dict[str, float | int | str]],
    right_descriptors: list[dict[str, float | int | str]],
) -> tuple[float, int]:
    family_weight = max(len(left_descriptors), len(right_descriptors))
    if family_weight <= 0:
        return 0.0, 0
    if not left_descriptors or not right_descriptors:
        return 0.0, family_weight

    candidate_pairs: list[tuple[float, float, int, int]] = []
    for left_index, left in enumerate(left_descriptors):
        for right_index, right in enumerate(right_descriptors):
            similarity = _numeric_similarity(config=config, left_descriptor=left, right_descriptor=right)
            position_gap = abs(int(left.get("sequence_index", 0)) - int(right.get("sequence_index", 0))) + abs(
                int(left.get("group_index", 0)) - int(right.get("group_index", 0))
            )
            candidate_pairs.append((similarity, -float(position_gap), left_index, right_index))

    candidate_pairs.sort(reverse=True)
    used_left: set[int] = set()
    used_right: set[int] = set()
    matched_scores: list[float] = []
    for similarity, _position_bonus, left_index, right_index in candidate_pairs:
        if left_index in used_left or right_index in used_right:
            continue
        used_left.add(left_index)
        used_right.add(right_index)
        matched_scores.append(float(similarity))

    if not matched_scores:
        return 0.0, family_weight

    coverage_ratio = float(len(matched_scores)) / max(1.0, float(family_weight))
    coverage_power = max(0.2, float(config.get("match_scoring_v2_numeric_coverage_power", 1.0)))
    family_score = _bounded(_safe_mean(matched_scores) * pow(max(0.0, coverage_ratio), coverage_power))
    return round(family_score, 8), family_weight


def _numeric_breakdown(*, config: dict, existing_units: list[dict], incoming_units: list[dict]) -> dict[str, Any] | None:
    if not bool(config.get("unified_numeric_scoring_enabled", True)):
        return None
    left_descriptors = _collect_numeric_descriptors(existing_units)
    right_descriptors = _collect_numeric_descriptors(incoming_units)
    if not left_descriptors and not right_descriptors:
        return None
    families = sorted(
        {
            str(item.get("family", "") or "").strip()
            for item in left_descriptors + right_descriptors
            if str(item.get("family", "") or "").strip()
        }
    )
    if not families:
        return None
    weighted_sum = 0.0
    total_weight = 0.0
    family_rows: list[dict[str, Any]] = []
    for family in families:
        left_family = [item for item in left_descriptors if str(item.get("family", "")) == family]
        right_family = [item for item in right_descriptors if str(item.get("family", "")) == family]
        family_score, family_weight = _numeric_family_score(
            config=config,
            left_descriptors=left_family,
            right_descriptors=right_family,
        )
        if family_weight <= 0:
            continue
        weighted_sum += float(family_score) * float(family_weight)
        total_weight += float(family_weight)
        family_rows.append(
            {
                "family": family,
                "score": round(float(family_score), 8),
                "weight": int(family_weight),
                "time_like": bool(
                    any(str(item.get("semantic_kind", "")) == "time_like" for item in (left_family + right_family))
                ),
            }
        )
    if total_weight <= 0.0:
        return None

    time_like_rows = [row for row in family_rows if bool(row.get("time_like", False))]
    non_time_like_rows = [row for row in family_rows if not bool(row.get("time_like", False))]
    time_like_weight = float(sum(int(row.get("weight", 0) or 0) for row in time_like_rows))
    non_time_like_weight = float(sum(int(row.get("weight", 0) or 0) for row in non_time_like_rows))
    time_like_score = None
    non_time_like_score = None
    if time_like_weight > 0.0:
        time_like_weighted_sum = sum(float(row.get("score", 0.0) or 0.0) * float(int(row.get("weight", 0) or 0)) for row in time_like_rows)
        time_like_score = round(_bounded(time_like_weighted_sum / time_like_weight), 8)
    if non_time_like_weight > 0.0:
        non_time_like_weighted_sum = sum(
            float(row.get("score", 0.0) or 0.0) * float(int(row.get("weight", 0) or 0))
            for row in non_time_like_rows
        )
        non_time_like_score = round(_bounded(non_time_like_weighted_sum / non_time_like_weight), 8)

    return {
        "score": round(_bounded(weighted_sum / total_weight), 8),
        "family_rows": family_rows,
        "family_count": int(len(family_rows)),
        "time_like_score": time_like_score,
        "time_like_family_count": int(len(time_like_rows)),
        "time_like_weight": round(float(time_like_weight), 8),
        "non_time_like_score": non_time_like_score,
        "non_time_like_family_count": int(len(non_time_like_rows)),
        "non_time_like_weight": round(float(non_time_like_weight), 8),
    }


def _order_alignment_score(*, existing_units: list[dict], incoming_units: list[dict]) -> float | None:
    pairs = _pair_units(existing_units, incoming_units)
    if not pairs:
        return None
    if len(pairs) == 1:
        return 1.0
    penalties: list[float] = []
    for index, (left, right) in enumerate(pairs):
        left_seq = float(left.get("sequence_index", index))
        right_seq = float(right.get("sequence_index", index))
        left_group = float(left.get("group_index", 0))
        right_group = float(right.get("group_index", 0))
        penalties.append(min(1.0, abs(left_seq - right_seq) / max(1.0, float(len(pairs)))))
        penalties.append(min(1.0, abs(left_group - right_group) / max(1.0, float(len(pairs)))))
    return round(_bounded(1.0 - _safe_mean(penalties)), 8)


def _attribute_anchor_score(*, bundle_constraints: dict, full_structure_included: bool) -> float | None:
    if not isinstance(bundle_constraints, dict) and not full_structure_included:
        return None
    exact = bool(bundle_constraints.get("exact", False))
    existing_ok = bool(bundle_constraints.get("existing_included", bundle_constraints.get("existing_included_in_incoming", False)))
    incoming_ok = bool(bundle_constraints.get("incoming_included", bundle_constraints.get("incoming_included_in_existing", False)))
    if exact or (full_structure_included and existing_ok and incoming_ok):
        return 1.0
    if existing_ok and incoming_ok:
        return 0.82
    if existing_ok or incoming_ok:
        return 0.58
    if full_structure_included:
        return 0.46
    return 0.0


def _context_support_score(
    *,
    context_payload: dict | None = None,
    context_support_hint: float | None = None,
    runtime_weight: float = 1.0,
    entry_runtime_weight: float = 1.0,
) -> float | None:
    if context_support_hint is not None:
        return round(_bounded(context_support_hint), 8)
    context = extract_context_metadata(context_payload or {})
    has_ref = bool(context.get("context_ref_object_id", ""))
    has_owner = bool(context.get("context_owner_structure_id", ""))
    path_depth = len(context.get("context_path_ids", []) or [])
    if not has_ref and not has_owner and path_depth <= 0:
        return None
    base = 0.0
    if has_owner:
        base += 0.42
    if has_ref:
        base += 0.22
    if path_depth > 0:
        base += min(0.24, 0.06 * float(path_depth))
    runtime_scale = math.sqrt(max(1e-8, float(runtime_weight)) * max(1e-8, float(entry_runtime_weight)))
    runtime_bonus = 0.12 * _bounded(0.5 + 0.5 * math.tanh(math.log(max(1e-8, runtime_scale))))
    return round(_bounded(base + runtime_bonus), 8)


def _energy_profile_score(*, existing_units: list[dict], incoming_units: list[dict], fallback_hint: float | None = None) -> float | None:
    left_er = sum(_positive(unit.get("er", 0.0)) for unit in existing_units if isinstance(unit, dict))
    left_ev = sum(_positive(unit.get("ev", 0.0)) for unit in existing_units if isinstance(unit, dict))
    right_er = sum(_positive(unit.get("er", 0.0)) for unit in incoming_units if isinstance(unit, dict))
    right_ev = sum(_positive(unit.get("ev", 0.0)) for unit in incoming_units if isinstance(unit, dict))
    left_total = left_er + left_ev
    right_total = right_er + right_ev
    if left_total <= 0.0 or right_total <= 0.0:
        if fallback_hint is None:
            return None
        return round(_bounded(fallback_hint), 8)
    left_vec = [left_er / left_total, left_ev / left_total]
    right_vec = [right_er / right_total, right_ev / right_total]
    l1_similarity = 1.0 - 0.5 * sum(abs(lv - rv) for lv, rv in zip(left_vec, right_vec))
    return round(_bounded(l1_similarity), 8)


def _context_ext_candidates(payload: dict | None) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    meta = payload.get("meta", {})
    meta_ext = meta.get("ext", {}) if isinstance(meta, dict) else {}
    structure = payload.get("structure", {})
    structure_ext = structure.get("ext", {}) if isinstance(structure, dict) else {}
    memory = payload.get("memory", {})
    memory_ext = memory.get("ext", {}) if isinstance(memory, dict) else {}
    ext = payload.get("ext", {})
    source = payload.get("source", {})
    out: list[dict] = []
    for candidate in (meta_ext, structure_ext, memory_ext, ext, source, payload):
        if isinstance(candidate, dict):
            out.append(candidate)
    return out


def _extract_memory_time_hint(context_payload: dict | None) -> tuple[bool, int | None]:
    if not isinstance(context_payload, dict):
        return False, None
    obj_type = str(context_payload.get("object_type", "") or "").strip()
    residual_kind = ""
    source_em_id = ""
    memory_id = ""
    timestamp_candidates: list[int] = []
    for candidate in _context_ext_candidates(context_payload):
        if not residual_kind:
            residual_kind = str(candidate.get("residual_origin_kind", "") or candidate.get("residual_kind", "") or "").strip()
        if not source_em_id:
            source_em_id = str(candidate.get("source_em_id", "") or candidate.get("anchor_memory_id", "") or "").strip()
        if not memory_id:
            memory_id = str(candidate.get("memory_id", "") or "").strip()
        for key in ("source_memory_created_at", "memory_created_at", "created_at", "last_updated_at", "updated_at"):
            try:
                value = int(candidate.get(key, 0) or 0)
            except Exception:
                value = 0
            if value > 0:
                timestamp_candidates.append(value)
    is_memory_like = bool(
        obj_type == "em"
        or source_em_id.startswith("em_")
        or memory_id.startswith("em_")
        or "memory" in residual_kind
    )
    timestamp_ms = min(timestamp_candidates) if timestamp_candidates else None
    return is_memory_like, timestamp_ms


def _extract_time_like_targets(units: list[dict]) -> list[float]:
    targets: list[float] = []
    for descriptor in _collect_numeric_descriptors(units):
        if str(descriptor.get("semantic_kind", "") or "").strip() != "time_like":
            continue
        try:
            value = float(descriptor.get("value", 0.0))
        except Exception:
            continue
        if math.isfinite(value) and value >= 0.0:
            targets.append(float(value))
    return targets


def _time_factor_soft_bonus(
    *,
    config: dict,
    incoming_units: list[dict],
    context_payload: dict | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    detail = {
        "applied": False,
        "factor": 1.0,
        "similarity": 0.0,
        "target_interval_sec": None,
        "memory_age_sec": None,
        "is_memory_candidate": False,
    }
    if not bool(config.get("time_factor_soft_bonus_enabled", True)):
        return detail
    is_memory_candidate, created_at_ms = _extract_memory_time_hint(context_payload)
    detail["is_memory_candidate"] = bool(is_memory_candidate)
    if not is_memory_candidate or not created_at_ms:
        return detail
    target_values = _extract_time_like_targets(incoming_units)
    if not target_values:
        return detail
    current_ms = int(now_ms if now_ms is not None else int(time.time() * 1000))
    if current_ms <= 0 or created_at_ms <= 0:
        return detail
    memory_age_sec = max(0.0, abs(float(current_ms - created_at_ms)) / 1000.0)
    target_interval_sec = _safe_mean(target_values)
    similarity_detail = describe_numeric_match(
        left_value=memory_age_sec,
        right_value=target_interval_sec,
        family="时间感受",
        abs_tolerance=float(config.get("time_factor_soft_bonus_abs_tolerance", config.get("numeric_match_abs_tolerance", 0.35))),
        rel_tolerance=float(config.get("time_factor_soft_bonus_rel_tolerance", config.get("numeric_match_rel_tolerance", 0.55))),
        min_similarity=0.0,
    )
    similarity = _bounded((similarity_detail or {}).get("similarity", 0.0))
    max_factor = max(1.0, float(config.get("time_factor_soft_bonus_max_factor", 1.35)))
    factor = 1.0 + similarity * max(0.0, max_factor - 1.0)
    detail.update(
        {
            "applied": bool(similarity > 0.0),
            "factor": round(float(factor), 8),
            "similarity": round(float(similarity), 8),
            "target_interval_sec": round(float(target_interval_sec), 8),
            "memory_age_sec": round(float(memory_age_sec), 8),
        }
    )
    return detail


def build_match_score_v2(
    *,
    config: dict,
    base_score: float,
    matched_existing_units: list[dict],
    matched_incoming_units: list[dict],
    bundle_constraints: dict | None = None,
    full_structure_included: bool = False,
    context_payload: dict | None = None,
    context_support_hint: float | None = None,
    runtime_weight: float = 1.0,
    entry_runtime_weight: float = 1.0,
    energy_profile_hint: float | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    base = _bounded(base_score)
    numeric_breakdown = _numeric_breakdown(config=config, existing_units=matched_existing_units, incoming_units=matched_incoming_units)
    numeric_score = None if not isinstance(numeric_breakdown, dict) else numeric_breakdown.get("score", None)
    order_alignment_score = (
        _order_alignment_score(existing_units=matched_existing_units, incoming_units=matched_incoming_units)
        if bool(config.get("sequence_soft_scoring_enabled", True))
        else None
    )
    attribute_anchor_score = (
        _attribute_anchor_score(
            bundle_constraints=dict(bundle_constraints or {}),
            full_structure_included=bool(full_structure_included),
        )
        if bool(config.get("attribute_soft_scoring_enabled", True))
        else None
    )
    context_score = _context_support_score(
        context_payload=context_payload,
        context_support_hint=context_support_hint,
        runtime_weight=runtime_weight,
        entry_runtime_weight=entry_runtime_weight,
    )
    energy_profile_score = _energy_profile_score(
        existing_units=matched_existing_units,
        incoming_units=matched_incoming_units,
        fallback_hint=energy_profile_hint,
    )
    structure_inclusion_score = 1.0 if full_structure_included else base
    time_factor = _time_factor_soft_bonus(
        config=config,
        incoming_units=matched_incoming_units,
        context_payload=context_payload,
        now_ms=now_ms,
    )
    numeric_score_effective = numeric_score
    time_like_memory_wildcard_applied = False
    if (
        bool(config.get("time_like_memory_wildcard_enabled", True))
        and bool(time_factor.get("is_memory_candidate", False))
        and isinstance(numeric_breakdown, dict)
        and int(numeric_breakdown.get("time_like_family_count", 0) or 0) > 0
    ):
        numeric_score_effective = numeric_breakdown.get("non_time_like_score", None)
        time_like_memory_wildcard_applied = True

    component_values = {
        "base_score": base,
        "numeric_score": numeric_score_effective,
        "order_alignment_score": order_alignment_score,
        "attribute_anchor_score": attribute_anchor_score,
        "context_support_score": context_score,
        "energy_profile_score": energy_profile_score,
        "structure_inclusion_score": structure_inclusion_score,
    }
    component_weights = {
        "base_score": max(0.0, float(config.get("match_scoring_v2_base_weight", 0.42))),
        "numeric_score": max(0.0, float(config.get("match_scoring_v2_numeric_weight", 0.16))),
        "order_alignment_score": max(0.0, float(config.get("match_scoring_v2_order_weight", 0.16))),
        "attribute_anchor_score": max(0.0, float(config.get("match_scoring_v2_attribute_weight", 0.12))),
        "context_support_score": max(0.0, float(config.get("match_scoring_v2_context_weight", 0.07))),
        "energy_profile_score": max(0.0, float(config.get("match_scoring_v2_energy_weight", 0.07))),
        "structure_inclusion_score": max(0.0, float(config.get("match_scoring_v2_inclusion_weight", 0.08))),
    }

    weighted_sum = 0.0
    total_weight = 0.0
    available_count = 0
    for key, value in component_values.items():
        if value is None:
            continue
        weight = float(component_weights.get(key, 0.0))
        if weight <= 0.0:
            continue
        weighted_sum += _bounded(value) * weight
        total_weight += weight
        available_count += 1

    if total_weight <= 0.0:
        blended = base
    else:
        blended = _bounded(weighted_sum / total_weight)

    hill = _hill_score(
        blended,
        half_point=float(config.get("match_scoring_v2_half_ratio", 0.14)),
        power=float(config.get("match_scoring_v2_curve_power", 1.25)),
    )
    denoise = _sigmoid(
        blended,
        midpoint=float(config.get("match_scoring_v2_noise_mid", 0.02)),
        slope=float(config.get("match_scoring_v2_noise_scale", 0.01)),
    )
    score = _bounded(hill * denoise * max(1.0, float(time_factor.get("factor", 1.0) or 1.0)))
    min_score = _bounded(config.get("match_scoring_v2_min_score", 0.18))
    threshold_margin = round(score - min_score, 8)

    return {
        "score": round(score, 8),
        "base_score": round(base, 8),
        "blended_component_mean": round(blended, 8),
        "numeric_score": round(_bounded(numeric_score), 8) if numeric_score is not None else -1.0,
        "numeric_score_effective": round(_bounded(numeric_score_effective), 8) if numeric_score_effective is not None else -1.0,
        "numeric_family_count": int((numeric_breakdown or {}).get("family_count", 0)) if isinstance(numeric_breakdown, dict) else 0,
        "numeric_time_like_score": round(_bounded((numeric_breakdown or {}).get("time_like_score", -1.0)), 8)
        if isinstance(numeric_breakdown, dict) and numeric_breakdown.get("time_like_score", None) is not None
        else -1.0,
        "numeric_time_like_family_count": int((numeric_breakdown or {}).get("time_like_family_count", 0)) if isinstance(numeric_breakdown, dict) else 0,
        "numeric_time_like_weight": round(float((numeric_breakdown or {}).get("time_like_weight", 0.0) or 0.0), 8)
        if isinstance(numeric_breakdown, dict)
        else 0.0,
        "numeric_non_time_like_score": round(_bounded((numeric_breakdown or {}).get("non_time_like_score", -1.0)), 8)
        if isinstance(numeric_breakdown, dict) and numeric_breakdown.get("non_time_like_score", None) is not None
        else -1.0,
        "numeric_non_time_like_family_count": int((numeric_breakdown or {}).get("non_time_like_family_count", 0))
        if isinstance(numeric_breakdown, dict)
        else 0,
        "numeric_time_like_wildcard_applied": bool(time_like_memory_wildcard_applied),
        "order_alignment_score": round(_bounded(order_alignment_score), 8) if order_alignment_score is not None else -1.0,
        "attribute_anchor_score": round(_bounded(attribute_anchor_score), 8) if attribute_anchor_score is not None else -1.0,
        "context_support_score": round(_bounded(context_score), 8) if context_score is not None else -1.0,
        "energy_profile_score": round(_bounded(energy_profile_score), 8) if energy_profile_score is not None else -1.0,
        "structure_inclusion_score": round(_bounded(structure_inclusion_score), 8),
        "time_factor_soft_bonus": round(float(time_factor.get("factor", 1.0) or 1.0), 8),
        "time_factor_applied": bool(time_factor.get("applied", False)),
        "time_factor_similarity": round(float(time_factor.get("similarity", 0.0) or 0.0), 8),
        "time_factor_target_interval_sec": round(float(time_factor.get("target_interval_sec", 0.0) or 0.0), 8)
        if time_factor.get("target_interval_sec", None) is not None
        else -1.0,
        "time_factor_memory_age_sec": round(float(time_factor.get("memory_age_sec", 0.0) or 0.0), 8)
        if time_factor.get("memory_age_sec", None) is not None
        else -1.0,
        "time_factor_is_memory_candidate": bool(time_factor.get("is_memory_candidate", False)),
        "available_component_count": int(available_count),
        "threshold_margin": threshold_margin,
    }
