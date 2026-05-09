# -*- coding: utf-8 -*-
"""
Experiment Metrics Extraction
=============================

Goal:
- turn a full `report` dict (from ObservatoryApp.run_cycle) into a compact,
  per-tick metrics record for plotting and paper evidence.

Principles:
- never crash the batch runner due to a missing field
- keep output stable and auditable (flat keys; mostly numbers)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _readable_ap_display(value: Any) -> str:
    text = _as_str(value, "").strip()
    if not text or "+" not in text:
        return text
    out: list[str] = []
    depth = 0
    index = 0
    while index < len(text):
        ch = text[index]
        if ch == "{":
            depth += 1
            out.append(ch)
            index += 1
            continue
        if ch == "}":
            depth = max(0, depth - 1)
            out.append(ch)
            index += 1
            continue
        if ch == "+" and depth > 0:
            while out and out[-1].isspace():
                out.pop()
            out.append(" ")
            index += 1
            while index < len(text) and text[index].isspace():
                index += 1
            continue
        out.append(ch)
        index += 1
    return "".join(out)


def _as_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _as_str(v: Any, default: str = "") -> str:
    try:
        s = str(v)
    except Exception:
        return default
    return s


def _as_list(v: Any) -> list:
    return list(v) if isinstance(v, list) else []


def _as_dict(v: Any) -> dict:
    return dict(v) if isinstance(v, dict) else {}


def _nested_dict(root: Any, *keys: str) -> dict:
    current = root
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return dict(current) if isinstance(current, dict) else {}


def _looks_like_internal_identifier(v: Any) -> bool:
    text = _as_str(v, "").strip()
    if not text:
        return False
    lowered = text.lower()
    return lowered.startswith(("spkt_", "sa_", "st_", "sg_", "em_", "ctx_", "action::"))


def _as_float_list(values: list[Any], *, skip_negative: bool = False) -> list[float]:
    out: list[float] = []
    for value in values:
        try:
            numeric = float(value)
        except Exception:
            continue
        if skip_negative and numeric < 0.0:
            continue
        out.append(float(numeric))
    return out


def _mean(values: list[Any], *, skip_negative: bool = False) -> float:
    cleaned = _as_float_list(values, skip_negative=skip_negative)
    if not cleaned:
        return 0.0
    return round(sum(cleaned) / max(1, len(cleaned)), 8)


def _metric_key_suffix(v: Any, *, default: str = "metric") -> str:
    raw = _as_str(v, "").strip().lower()
    if not raw:
        return default
    out_chars: list[str] = []
    last_is_sep = False
    for ch in raw:
        if ch.isascii() and ch.isalnum():
            out_chars.append(ch)
            last_is_sep = False
            continue
        if not last_is_sep:
            out_chars.append("_")
            last_is_sep = True
    normalized = "".join(out_chars).strip("_")
    return normalized or default


_EMOTION_CHANNEL_CODES: tuple[str, ...] = ("DA", "ADR", "OXY", "SER", "END", "COR", "NOV", "FOC")
_EMOTION_CHANNEL_ALIAS_TO_CODE: dict[str, str] = {
    "da": "DA",
    "多巴胺": "DA",
    "多巴胺(da)": "DA",
    "adr": "ADR",
    "肾上腺素": "ADR",
    "肾上腺素(adr)": "ADR",
    "oxy": "OXY",
    "催产素": "OXY",
    "催产素(oxy)": "OXY",
    "ser": "SER",
    "血清素": "SER",
    "血清素(ser)": "SER",
    "end": "END",
    "内啡肽": "END",
    "内啡肽(end)": "END",
    "cor": "COR",
    "皮质醇": "COR",
    "皮质醇(cor)": "COR",
    "nov": "NOV",
    "新颖探索": "NOV",
    "新颖探索(nov)": "NOV",
    "foc": "FOC",
    "专注锁定": "FOC",
    "专注锁定(foc)": "FOC",
}


def _normalize_emotion_channel_code(v: Any) -> str:
    raw = _as_str(v, "").strip()
    if not raw:
        return ""
    normalized = raw.replace("（", "(").replace("）", ")").strip().lower()
    return _EMOTION_CHANNEL_ALIAS_TO_CODE.get(normalized, normalized.upper() if normalized.upper() in _EMOTION_CHANNEL_CODES else "")


def _extract_action_target_from_payload(payload: dict[str, Any] | None) -> dict[str, str]:
    payload_dict = payload if isinstance(payload, dict) else {}
    params = _as_dict(payload_dict.get("params"))
    target_ref_object_id = _as_str(
        params.get(
            "target_ref_object_id",
            payload_dict.get("target_ref_object_id", params.get("ref_object_id", payload_dict.get("ref_object_id", ""))),
        )
    ).strip()
    target_ref_object_type = _as_str(
        params.get(
            "target_ref_object_type",
            payload_dict.get("target_ref_object_type", params.get("ref_object_type", payload_dict.get("ref_object_type", ""))),
        )
    ).strip()
    target_item_id = _as_str(
        params.get("target_item_id", payload_dict.get("target_item_id", params.get("item_id", payload_dict.get("item_id", ""))))
    ).strip()
    target_display = _as_str(
        params.get(
            "target_display",
            payload_dict.get("target_display", params.get("trigger_target_display", payload_dict.get("trigger_target_display", ""))),
        )
    ).strip()
    trigger_target_ref = _as_str(
        params.get(
            "trigger_target_ref",
            payload_dict.get(
                "trigger_target_ref",
                params.get("trigger_target", payload_dict.get("trigger_target", params.get("target_ref", payload_dict.get("target_ref", "")))),
            ),
        )
    ).strip()
    if not target_ref_object_id and trigger_target_ref:
        if ":" in trigger_target_ref:
            target_ref_object_type, target_ref_object_id = [x.strip() for x in trigger_target_ref.split(":", 1)]
        else:
            target_ref_object_id = trigger_target_ref
    if not target_display:
        target_display = target_ref_object_id or target_item_id
    return {
        "target_ref_object_id": str(target_ref_object_id or ""),
        "target_ref_object_type": str(target_ref_object_type or ""),
        "target_item_id": str(target_item_id or ""),
        "target_display": str(target_display or ""),
    }


def _collect_v2_candidate_metrics(
    *,
    round_details: list[dict],
    candidate_list_key: str,
    legacy_score_key: str,
    competition_score_key: str,
    metric_prefix: str,
) -> dict[str, Any]:
    candidates: list[dict] = []
    for detail in round_details:
        if not isinstance(detail, dict):
            continue
        for item in _as_list(detail.get(candidate_list_key)):
            if isinstance(item, dict):
                candidates.append(item)
    eligible = [item for item in candidates if bool(item.get("eligible", False))]
    source = eligible if eligible else candidates
    source_count = len(source)
    soft_partial_eligible = [item for item in candidates if bool(item.get("soft_partial_eligible", False))]
    soft_partial_selected = [item for item in source if bool(item.get("soft_partial_eligible", False))]
    exact_match_selected = [item for item in source if bool(item.get("exact_match", False))]
    bundle_exact_selected_count = 0
    for item in source:
        common_part = _as_dict(item.get("common_part"))
        bundle_exact = bool(
            common_part.get(
                "bundle_constraints_ok_exact",
                _as_dict(item.get("bundle_constraints")).get("exact", item.get("exact_match", False)),
            )
        )
        if bundle_exact:
            bundle_exact_selected_count += 1
    time_factor_bonus_values = _as_float_list([item.get("v2_time_factor_soft_bonus", 1.0) for item in source])
    time_factor_bonus_applied_count = len([item for item in source if bool(item.get("v2_time_factor_applied", False))])
    numeric_time_like_wildcard_applied_count = len(
        [item for item in source if bool(item.get("v2_numeric_time_like_wildcard_applied", False))]
    )
    numeric_score_values = _as_float_list([item.get("v2_numeric_score", -1.0) for item in source], skip_negative=True)
    numeric_scored_count = len(numeric_score_values)
    numeric_nonzero_count = len([value for value in numeric_score_values if value > 0.0])
    numeric_time_like_values = _as_float_list([item.get("v2_numeric_time_like_score", -1.0) for item in source], skip_negative=True)
    numeric_time_like_scored_count = len(numeric_time_like_values)
    numeric_time_like_nonzero_count = len([value for value in numeric_time_like_values if value > 0.0])
    blend_gain_values = []
    for item in source:
        try:
            gain = float(item.get(competition_score_key, 0.0)) - float(item.get(legacy_score_key, 0.0))
        except Exception:
            gain = 0.0
        blend_gain_values.append(gain)
    return {
        f"{metric_prefix}_candidate_count": len(candidates),
        f"{metric_prefix}_eligible_count": len(eligible),
        f"{metric_prefix}_eligible_ratio": round(float(len(eligible)) / max(1.0, float(len(candidates) or 1)), 8),
        f"{metric_prefix}_score_mean": _mean([item.get("v2_score", 0.0) for item in source]),
        f"{metric_prefix}_base_score_mean": _mean([item.get("v2_base_score", 0.0) for item in source]),
        f"{metric_prefix}_numeric_score_mean": _mean([item.get("v2_numeric_score", -1.0) for item in source], skip_negative=True),
        f"{metric_prefix}_numeric_scored_count": int(numeric_scored_count),
        f"{metric_prefix}_numeric_scored_ratio": round(float(numeric_scored_count) / max(1.0, float(len(source) or 1)), 8),
        f"{metric_prefix}_numeric_nonzero_count": int(numeric_nonzero_count),
        f"{metric_prefix}_numeric_nonzero_ratio": round(float(numeric_nonzero_count) / max(1.0, float(len(source) or 1)), 8),
        f"{metric_prefix}_numeric_time_like_score_mean": _mean([item.get("v2_numeric_time_like_score", -1.0) for item in source], skip_negative=True),
        f"{metric_prefix}_numeric_time_like_scored_count": int(numeric_time_like_scored_count),
        f"{metric_prefix}_numeric_time_like_scored_ratio": round(float(numeric_time_like_scored_count) / max(1.0, float(len(source) or 1)), 8),
        f"{metric_prefix}_numeric_time_like_nonzero_count": int(numeric_time_like_nonzero_count),
        f"{metric_prefix}_numeric_time_like_nonzero_ratio": round(float(numeric_time_like_nonzero_count) / max(1.0, float(len(source) or 1)), 8),
        f"{metric_prefix}_numeric_time_like_family_count_mean": _mean([item.get("v2_numeric_time_like_family_count", 0.0) for item in source]),
        f"{metric_prefix}_numeric_time_like_wildcard_applied_count": int(numeric_time_like_wildcard_applied_count),
        f"{metric_prefix}_numeric_time_like_wildcard_applied_ratio": round(
            float(numeric_time_like_wildcard_applied_count) / max(1.0, float(source_count or 1)),
            8,
        ),
        f"{metric_prefix}_numeric_family_count_mean": _mean([item.get("v2_numeric_family_count", 0.0) for item in source]),
        f"{metric_prefix}_order_alignment_mean": _mean([item.get("v2_order_alignment_score", -1.0) for item in source], skip_negative=True),
        f"{metric_prefix}_attribute_anchor_mean": _mean([item.get("v2_attribute_anchor_score", -1.0) for item in source], skip_negative=True),
        f"{metric_prefix}_context_support_mean": _mean([item.get("v2_context_support_score", -1.0) for item in source], skip_negative=True),
        f"{metric_prefix}_energy_profile_mean": _mean([item.get("v2_energy_profile_score", -1.0) for item in source], skip_negative=True),
        f"{metric_prefix}_structure_inclusion_mean": _mean([item.get("v2_structure_inclusion_score", 0.0) for item in source]),
        f"{metric_prefix}_time_factor_bonus_applied_count": int(time_factor_bonus_applied_count),
        f"{metric_prefix}_time_factor_bonus_applied_ratio": round(
            float(time_factor_bonus_applied_count) / max(1.0, float(source_count or 1)),
            8,
        ),
        f"{metric_prefix}_time_factor_bonus_mean": _mean(time_factor_bonus_values),
        f"{metric_prefix}_soft_partial_eligible_count": int(len(soft_partial_eligible)),
        f"{metric_prefix}_soft_partial_eligible_ratio": round(
            float(len(soft_partial_eligible)) / max(1.0, float(len(candidates) or 1)),
            8,
        ),
        f"{metric_prefix}_soft_partial_selected_count": int(len(soft_partial_selected)),
        f"{metric_prefix}_soft_partial_selected_ratio": round(
            float(len(soft_partial_selected)) / max(1.0, float(source_count or 1)),
            8,
        ),
        f"{metric_prefix}_bundle_exact_selected_count": int(bundle_exact_selected_count),
        f"{metric_prefix}_bundle_exact_selected_ratio": round(
            float(bundle_exact_selected_count) / max(1.0, float(source_count or 1)),
            8,
        ),
        f"{metric_prefix}_exact_match_selected_count": int(len(exact_match_selected)),
        f"{metric_prefix}_exact_match_selected_ratio": round(
            float(len(exact_match_selected)) / max(1.0, float(source_count or 1)),
            8,
        ),
        f"{metric_prefix}_threshold_margin_mean": _mean([item.get("v2_threshold_margin", 0.0) for item in source]),
        f"{metric_prefix}_blend_gain_mean": _mean(blend_gain_values),
    }


def _collect_structure_round_path_metrics(*, round_details: list[dict]) -> dict[str, Any]:
    total_rounds = 0
    synthetic_rounds = 0
    implicit_single_rounds = 0
    competitive_rounds = 0
    for detail in round_details:
        if not isinstance(detail, dict):
            continue
        total_rounds += 1
        selected_group = _as_dict(detail.get("selected_group"))
        candidate_groups = [item for item in _as_list(detail.get("candidate_groups")) if isinstance(item, dict)]
        is_synthetic = bool(detail.get("synthetic", selected_group.get("synthetic", False)))
        group_kind = _as_str(selected_group.get("group_kind", detail.get("group_kind", ""))).strip()
        if is_synthetic:
            synthetic_rounds += 1
        if group_kind == "implicit_single_st":
            implicit_single_rounds += 1
        if candidate_groups:
            competitive_rounds += 1
    base = max(1.0, float(total_rounds or 1))
    return {
        "structure_round_synthetic_count": int(synthetic_rounds),
        "structure_round_synthetic_ratio": round(float(synthetic_rounds) / base, 8),
        "structure_round_implicit_single_count": int(implicit_single_rounds),
        "structure_round_implicit_single_ratio": round(float(implicit_single_rounds) / base, 8),
        "structure_round_competitive_count": int(competitive_rounds),
        "structure_round_competitive_ratio": round(float(competitive_rounds) / base, 8),
    }


def _collect_stimulus_transfer_metrics(*, round_details: list[dict]) -> dict[str, Any]:
    total_transferred_er = 0.0
    total_transferred_ev = 0.0
    final_residual_er = 0.0
    final_residual_ev = 0.0
    selected_round_count = 0
    transfer_fraction_values: list[float] = []
    transfer_similarity_values: list[float] = []
    valid_details: list[dict] = []
    for detail in round_details:
        if not isinstance(detail, dict):
            continue
        valid_details.append(detail)
        transferred_er = max(0.0, _as_float(detail.get("transferred_er", 0.0)))
        transferred_ev = max(0.0, _as_float(detail.get("transferred_ev", 0.0)))
        total_transferred_er += transferred_er
        total_transferred_ev += transferred_ev
        if transferred_er > 0.0 or transferred_ev > 0.0 or _as_dict(detail.get("selected_match")):
            selected_round_count += 1
        transfer_fraction_values.append(_as_float(detail.get("effective_transfer_fraction", 0.0)))
        transfer_similarity_values.append(_as_float(detail.get("transfer_similarity", 0.0)))

    if valid_details:
        last_detail = valid_details[-1]
        final_residual_er = max(0.0, _as_float(last_detail.get("remaining_total_er_after", 0.0)))
        final_residual_ev = max(0.0, _as_float(last_detail.get("remaining_total_ev_after", 0.0)))

    transfer_total = max(0.0, total_transferred_er + total_transferred_ev)
    residual_total = max(0.0, final_residual_er + final_residual_ev)
    denominator = max(1e-9, residual_total)
    combined = transfer_total + residual_total
    return {
        "stimulus_transfer_round_count": int(len(valid_details)),
        "stimulus_transfer_selected_round_count": int(selected_round_count),
        "stimulus_transfer_matched_er": round(float(total_transferred_er), 8),
        "stimulus_transfer_matched_ev": round(float(total_transferred_ev), 8),
        "stimulus_transfer_matched_total": round(float(transfer_total), 8),
        "stimulus_final_residual_er": round(float(final_residual_er), 8),
        "stimulus_final_residual_ev": round(float(final_residual_ev), 8),
        "stimulus_final_residual_total": round(float(residual_total), 8),
        "stimulus_transfer_minus_residual_total": round(float(transfer_total - residual_total), 8),
        "stimulus_transfer_to_residual_ratio": round(float(transfer_total / denominator), 8) if transfer_total > 0.0 else 0.0,
        "stimulus_transfer_share_of_matched_plus_residual": round(float(transfer_total / max(1e-9, combined)), 8)
        if combined > 0.0
        else 0.0,
        "stimulus_transfer_dominates_residual": 1 if transfer_total > residual_total else 0,
        "stimulus_effective_transfer_fraction_mean": _mean(transfer_fraction_values),
        "stimulus_effective_transfer_fraction_max": round(float(max(transfer_fraction_values)), 8)
        if transfer_fraction_values
        else 0.0,
        "stimulus_transfer_similarity_mean": _mean(transfer_similarity_values),
        "stimulus_transfer_similarity_max": round(float(max(transfer_similarity_values)), 8)
        if transfer_similarity_values
        else 0.0,
    }


def _collect_stimulus_object_projection_metrics(
    *,
    runtime_projection_structures: list[Any],
    transfer_metrics: dict[str, Any],
    residual_tail_memory_projection: dict[str, Any],
) -> dict[str, Any]:
    """Summarize the growth-era object-side landing of stimulus energy.

    `stimulus_transfer_*` intentionally remains the conservative per-round
    selected-match audit. In growth mode, stimulus energy can also land through
    same-tick full string/structure seeds, relation structures, and the
    residual-tail memory_id projection. This helper exposes that newer object
    projection口径 without changing the legacy fields.
    """

    projection_er = 0.0
    projection_ev = 0.0
    projection_count = 0
    seed_er = 0.0
    seed_ev = 0.0
    matched_er = 0.0
    matched_ev = 0.0
    relation_er = 0.0
    relation_ev = 0.0
    for row in runtime_projection_structures:
        if not isinstance(row, dict):
            continue
        er = max(0.0, _as_float(row.get("er", 0.0)))
        ev = max(0.0, _as_float(row.get("ev", 0.0)))
        if er <= 0.0 and ev <= 0.0:
            continue
        projection_count += 1
        projection_er += er
        projection_ev += ev
        reason = _as_str(row.get("reason", row.get("match_mode", ""))).strip()
        if "seed" in reason:
            seed_er += er
            seed_ev += ev
        elif reason == "matched_structure":
            matched_er += er
            matched_ev += ev
        elif "relation" in reason:
            relation_er += er
            relation_ev += ev

    raw_residual_er = max(0.0, _as_float(transfer_metrics.get("stimulus_final_residual_er", 0.0)))
    raw_residual_ev = max(0.0, _as_float(transfer_metrics.get("stimulus_final_residual_ev", 0.0)))
    raw_residual_total = max(0.0, raw_residual_er + raw_residual_ev)
    tail_payload = _as_dict(residual_tail_memory_projection.get("memory"))
    tail_energy = _as_dict(tail_payload.get("energy"))
    tail_er = max(0.0, _as_float(tail_energy.get("er", 0.0)))
    tail_ev = max(0.0, _as_float(tail_energy.get("ev", 0.0)))
    tail_total = max(0.0, tail_er + tail_ev) if bool(residual_tail_memory_projection.get("handled", False)) else 0.0
    unhandled_residual_er = max(0.0, raw_residual_er - tail_er)
    unhandled_residual_ev = max(0.0, raw_residual_ev - tail_ev)
    unhandled_residual_total = max(0.0, unhandled_residual_er + unhandled_residual_ev)
    projection_total = max(0.0, projection_er + projection_ev)
    # Net residual is expected to approach zero when the memory-id tail
    # projection consumes the raw tail. Use a 1-energy floor for the ratio so
    # charts stay readable; the strict acceptance signal is the margin and
    # dominance flag below.
    denominator = max(1.0, unhandled_residual_total)
    combined = projection_total + unhandled_residual_total
    return {
        "stimulus_object_projection_count": int(projection_count),
        "stimulus_object_projection_er": round(float(projection_er), 8),
        "stimulus_object_projection_ev": round(float(projection_ev), 8),
        "stimulus_object_projection_total": round(float(projection_total), 8),
        "stimulus_object_projection_seed_er": round(float(seed_er), 8),
        "stimulus_object_projection_seed_ev": round(float(seed_ev), 8),
        "stimulus_object_projection_seed_total": round(float(seed_er + seed_ev), 8),
        "stimulus_object_projection_matched_er": round(float(matched_er), 8),
        "stimulus_object_projection_matched_ev": round(float(matched_ev), 8),
        "stimulus_object_projection_matched_total": round(float(matched_er + matched_ev), 8),
        "stimulus_object_projection_relation_er": round(float(relation_er), 8),
        "stimulus_object_projection_relation_ev": round(float(relation_ev), 8),
        "stimulus_object_projection_relation_total": round(float(relation_er + relation_ev), 8),
        "stimulus_memory_tail_absorbed_er": round(float(tail_er), 8),
        "stimulus_memory_tail_absorbed_ev": round(float(tail_ev), 8),
        "stimulus_memory_tail_absorbed_total": round(float(tail_total), 8),
        "stimulus_unhandled_residual_er": round(float(unhandled_residual_er), 8),
        "stimulus_unhandled_residual_ev": round(float(unhandled_residual_ev), 8),
        "stimulus_unhandled_residual_total": round(float(unhandled_residual_total), 8),
        "stimulus_object_projection_minus_unhandled_residual_total": round(
            float(projection_total - unhandled_residual_total),
            8,
        ),
        "stimulus_object_projection_to_unhandled_residual_ratio": round(float(projection_total / denominator), 8)
        if projection_total > 0.0
        else 0.0,
        "stimulus_object_projection_share_of_projection_plus_unhandled_residual": round(
            float(projection_total / max(1e-9, combined)),
            8,
        )
        if combined > 0.0
        else 0.0,
        "stimulus_object_projection_dominates_unhandled_residual": 1
        if projection_total > unhandled_residual_total
        else 0,
        "stimulus_object_projection_dominates_raw_residual": 1 if projection_total > raw_residual_total else 0,
    }


CORE_CFS_KINDS: tuple[str, ...] = (
    "dissonance",
    "pressure",
    "pressure_verified",
    "pressure_unverified",
    "expectation",
    "expectation_verified",
    "expectation_unverified",
    "surprise",
    "correct_event",
    "grasp",
    "complexity",
    "simplicity",
    "relief",
    "reassurance",
    "repetition",
)

# Live-state CFS attributes (bound attributes in StatePool).
# These are not "one-tick peaks"; they represent maintained runtime state with decay.
CORE_CFS_BOUND_ATTRS: tuple[str, ...] = (
    "cfs_dissonance",
    "cfs_correctness",
    "cfs_pressure",
    "cfs_pressure_verified",
    "cfs_pressure_unverified",
    "cfs_expectation",
    "cfs_expectation_verified",
    "cfs_expectation_unverified",
    "cfs_grasp",
    "cfs_complexity",
    "cfs_simplicity",
    "cfs_relief",
    "cfs_reassurance",
    "cfs_surprise",
    "cfs_correct_event",
    "cfs_repetition",
)

CORE_RUNTIME_FEEDBACK_BOUND_ATTRS: tuple[str, ...] = (
    "reward_signal",
    "punish_signal",
    "teacher_reward_signal",
    "teacher_punish_signal",
)

BOUND_ATTRIBUTE_FAMILY_PREFIXES: dict[str, str] = {
    "cfs_pressure_family": "cfs_pressure",
    "cfs_expectation_family": "cfs_expectation",
}

CFS_KIND_TO_BOUND_ATTR: dict[str, str] = {
    "dissonance": "cfs_dissonance",
    "correctness": "cfs_correctness",
    "pressure": "cfs_pressure",
    "pressure_verified": "cfs_pressure_verified",
    "pressure_unverified": "cfs_pressure_unverified",
    "expectation": "cfs_expectation",
    "expectation_verified": "cfs_expectation_verified",
    "expectation_unverified": "cfs_expectation_unverified",
    "grasp": "cfs_grasp",
    "complexity": "cfs_complexity",
    "simplicity": "cfs_simplicity",
    "relief": "cfs_relief",
    "reassurance": "cfs_reassurance",
    "surprise": "cfs_surprise",
    "correct_event": "cfs_correct_event",
    "repetition": "cfs_repetition",
}


@dataclass(frozen=True)
class MetricsSchema:
    version: str = "v0"


def _matches_attr_family(attr_name: str, prefix: str) -> bool:
    name = _as_str(attr_name).strip()
    prefix_norm = _as_str(prefix).strip()
    if not name or not prefix_norm:
        return False
    return name == prefix_norm or name.startswith(f"{prefix_norm}_")


def _flatten_bound_attr_row(record: dict[str, Any], *, metric_name: str, row: dict[str, Any] | None) -> None:
    row = row if isinstance(row, dict) else {}
    record[f"{metric_name}_live_total_er"] = round(float(_as_float(row.get("total_er", 0.0))), 8)
    record[f"{metric_name}_live_total_ev"] = round(float(_as_float(row.get("total_ev", 0.0))), 8)
    record[f"{metric_name}_live_total_energy"] = round(float(_as_float(row.get("total_energy", 0.0))), 8)
    record[f"{metric_name}_live_item_count"] = int(_as_int(row.get("item_count", 0)))
    record[f"{metric_name}_live_attribute_count"] = int(_as_int(row.get("attribute_count", 0)))


def _merge_runtime_feedback_signal_rows(record: dict[str, Any], *, runtime_sync: dict[str, Any] | None) -> None:
    runtime_sync = runtime_sync if isinstance(runtime_sync, dict) else {}
    signal_rows = [row for row in _as_list(runtime_sync.get("signal_nodes")) if isinstance(row, dict)]
    if not signal_rows:
        return

    for row in signal_rows:
        metric_name = _as_str(row.get("signal_name", row.get("ref_id", ""))).strip()
        if metric_name not in CORE_RUNTIME_FEEDBACK_BOUND_ATTRS:
            continue
        code = _as_str(row.get("code", "")).strip()
        operation = _as_str(row.get("operation", "")).strip()
        after = _as_dict(row.get("after"))
        if code == "SKIP_ZERO_CREATE":
            continue
        if not bool(row.get("ok", False)) and not operation and not after:
            continue

        runtime_er = max(0.0, _as_float(after.get("er", row.get("target_er", 0.0))))
        runtime_ev = max(0.0, _as_float(after.get("ev", row.get("target_ev", 0.0))))
        runtime_total = round(float(runtime_er + runtime_ev), 8)
        item_present = bool(_as_str(row.get("item_id", "")).strip() or operation in {"insert_or_merge", "set_existing"} or after)
        if not item_present and runtime_total <= 0.0:
            continue

        record[f"{metric_name}_live_total_er"] = round(
            float(_as_float(record.get(f"{metric_name}_live_total_er", 0.0)) + runtime_er),
            8,
        )
        record[f"{metric_name}_live_total_ev"] = round(
            float(_as_float(record.get(f"{metric_name}_live_total_ev", 0.0)) + runtime_ev),
            8,
        )
        record[f"{metric_name}_live_total_energy"] = round(
            float(_as_float(record.get(f"{metric_name}_live_total_energy", 0.0)) + runtime_total),
            8,
        )
        if item_present:
            record[f"{metric_name}_live_item_count"] = int(
                _as_int(record.get(f"{metric_name}_live_item_count", 0)) + 1
            )


def _sum_bound_attr_family(bound_totals: dict[str, Any], *, prefix: str) -> dict[str, Any]:
    total_er = 0.0
    total_ev = 0.0
    total_energy = 0.0
    item_count = 0
    attribute_count = 0
    for attr_name, raw_row in bound_totals.items():
        if not _matches_attr_family(str(attr_name), prefix):
            continue
        row = raw_row if isinstance(raw_row, dict) else {}
        total_er += _as_float(row.get("total_er", 0.0))
        total_ev += _as_float(row.get("total_ev", 0.0))
        total_energy += _as_float(row.get("total_energy", 0.0))
        item_count += _as_int(row.get("item_count", 0))
        attribute_count += _as_int(row.get("attribute_count", 0))
    return {
        "total_er": round(float(total_er), 8),
        "total_ev": round(float(total_ev), 8),
        "total_energy": round(float(total_energy), 8),
        "item_count": int(item_count),
        "attribute_count": int(attribute_count),
    }


def _compact_item_preview(row: dict[str, Any], *, energy_key: str) -> dict[str, Any]:
    key = str(energy_key or "").strip().lower()
    ref_snapshot = _as_dict(row.get("ref_snapshot"))
    er = round(float(_as_float(row.get("er", row.get("memory_er", 0.0)))), 8)
    ev = round(float(_as_float(row.get("ev", row.get("memory_ev", 0.0)))), 8)
    raw_display = (
        _as_str(row.get("display", "")).strip()
        or _as_str(row.get("display_text", "")).strip()
        or _as_str(ref_snapshot.get("content_display", "")).strip()
        or _as_str(row.get("ref_object_id", "")).strip()
        or _as_str(row.get("item_id", "")).strip()
    )
    display = _readable_ap_display(raw_display)
    anchor_display = (
        _as_str(row.get("anchor_display", "")).strip()
        or _as_str(ref_snapshot.get("anchor_display", "")).strip()
    )
    context_text = (
        _as_str(row.get("context_text", "")).strip()
        or _as_str(ref_snapshot.get("context_text", "")).strip()
    )
    target_display = (
        _as_str(row.get("target_display", "")).strip()
        or _as_str(ref_snapshot.get("target_display", "")).strip()
    )
    display_detail = (
        _as_str(row.get("display_detail", "")).strip()
        or _as_str(ref_snapshot.get("content_display_detail", "")).strip()
    )
    context_ref_object_id = (
        _as_str(row.get("context_ref_object_id", "")).strip()
        or _as_str(ref_snapshot.get("context_ref_object_id", "")).strip()
    )
    context_ref_object_type = (
        _as_str(row.get("context_ref_object_type", "")).strip()
        or _as_str(ref_snapshot.get("context_ref_object_type", "")).strip()
    )
    context_owner_id = (
        _as_str(row.get("context_owner_id", "")).strip()
        or _as_str(row.get("context_owner_structure_id", "")).strip()
        or _as_str(ref_snapshot.get("context_owner_id", "")).strip()
        or _as_str(ref_snapshot.get("context_owner_structure_id", "")).strip()
    )
    context_path_ids = [
        _as_str(value).strip()
        for value in (
            _as_list(row.get("context_path_ids"))
            or _as_list(ref_snapshot.get("context_path_ids"))
        )
        if _as_str(value).strip()
    ][:12]
    ref_alias_ids = [
        _as_str(value).strip()
        for value in _as_list(row.get("ref_alias_ids", []))
        if _as_str(value).strip()
    ][:16]
    human_context_text = "" if _looks_like_internal_identifier(context_text) else context_text
    human_detail = "" if _looks_like_internal_identifier(display_detail) else display_detail
    about = anchor_display or target_display or human_context_text or human_detail
    return {
        "item_id": _as_str(row.get("item_id", "")).strip(),
        "ref_object_id": _as_str(row.get("ref_object_id", "")).strip(),
        "ref_object_type": _as_str(row.get("ref_object_type", "")).strip(),
        "ref_alias_count": len(ref_alias_ids),
        "semantic_signature_len": len(_as_str(row.get("semantic_signature", "")).strip()),
        "semantic_context_key_len": len(_as_str(row.get("semantic_context_key", "")).strip()),
        "display": display[:160],
        "raw_display": raw_display[:240] if raw_display and raw_display != display else "",
        "about": _readable_ap_display(about)[:120],
        "anchor_display": anchor_display[:120],
        "context_ref_object_id": context_ref_object_id,
        "context_ref_object_type": context_ref_object_type,
        "context_owner_id": context_owner_id,
        "context_owner_structure_id": context_owner_id,
        "context_path_depth": len(context_path_ids),
        "target_display": target_display[:120],
        "role": _as_str(row.get("role", ref_snapshot.get("role", ""))).strip(),
        "attribute_name": _as_str(row.get("attribute_name", ref_snapshot.get("attribute_name", ""))).strip(),
        "attribute_count": len(
            [
                _as_str(v).strip()
                for v in _as_list(row.get("all_attribute_names", ref_snapshot.get("all_attribute_names", [])))
                if _as_str(v).strip()
            ]
        ),
        "er": er,
        "ev": ev,
        "total_energy": round(float(er + ev), 8),
        "cp": round(float(_as_float(row.get("cp_abs", row.get("cp", 0.0)))), 8),
        "attention_priority": round(float(_as_float(row.get("attention_priority", 0.0))), 8),
        "reward_action_bonus": round(float(_as_float(row.get("reward_action_bonus", 0.0))), 8),
        "repeat_attention_penalty": round(float(_as_float(row.get("repeat_attention_penalty", 0.0))), 8),
        "selected_by": _as_str(row.get("selected_by", "")).strip(),
        "_focus_energy": (
            er
            if key == "er"
            else ev
            if key == "ev"
            else round(float(_as_float(row.get("cp_abs", row.get("cp", 0.0)))), 8)
        ),
    }


def _is_atomic_feature_sa_preview(row: dict[str, Any]) -> bool:
    ref_type = _as_str(row.get("ref_object_type", "")).strip().lower()
    if ref_type != "sa":
        return False
    display = _as_str(row.get("display", "")).strip()
    if display.startswith("{") and display.endswith("}") and len(display) >= 2:
        display = display[1:-1].strip()
    if not display:
        return True
    if any(marker in display for marker in (":", "：", "行动节点", "时间感受", "cfs_", "nt_")):
        return False
    return len(list(display)) <= 2


def _pool_energy_top_items(
    snapshot: dict[str, Any],
    *,
    energy_key: str,
    limit: int = 5,
    exclude_atomic_feature_sa: bool = False,
) -> list[dict[str, Any]]:
    key = str(energy_key or "").strip().lower()
    if key not in {"er", "ev", "cp"}:
        return []
    rows = (
        _as_list(snapshot.get(f"{key}_top_items"))
        or _as_list(snapshot.get(f"top_items_by_{key}"))
        or _as_list(snapshot.get("items"))
        or _as_list(snapshot.get("top_items"))
    )
    compact: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        preview = _compact_item_preview(row, energy_key=key)
        focus_energy = float(preview.get("_focus_energy", 0.0) or 0.0)
        if focus_energy <= 0.0:
            continue
        if exclude_atomic_feature_sa and _is_atomic_feature_sa_preview(preview):
            continue
        compact.append(preview)
    focus_key = "cp" if key == "cp" else key
    compact.sort(
        key=lambda row: (
            float(row.get(focus_key, 0.0)),
            float(row.get("total_energy", 0.0)),
            float(row.get("cp", 0.0)),
        ),
        reverse=True,
    )
    out = compact[: max(1, int(limit))]
    for index, row in enumerate(out, start=1):
        row["rank"] = index
        row.pop("_focus_energy", None)
    return out


def _attention_top_items(rows: list[Any], *, limit: int = 5) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        preview = _compact_item_preview(row, energy_key="er")
        if preview.get("total_energy", 0.0) <= 0.0 and preview.get("attention_priority", 0.0) <= 0.0:
            continue
        compact.append(preview)
    compact.sort(
        key=lambda row: (
            float(row.get("attention_priority", 0.0)),
            float(row.get("total_energy", 0.0)),
            float(row.get("reward_action_bonus", 0.0)),
            -float(row.get("repeat_attention_penalty", 0.0)),
        ),
        reverse=True,
    )
    out = compact[: max(1, int(limit))]
    for index, row in enumerate(out, start=1):
        row["rank"] = index
        row.pop("_focus_energy", None)
    return out


def _dedupe_top_preview_list(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = (
            _as_str(row.get("ref_object_id", "")).strip(),
            _as_str(row.get("display", "")).strip(),
            _as_str(row.get("ref_object_type", "")).strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    for index, row in enumerate(out, start=1):
        row["rank"] = index
    return out


def _same_top_preview_list(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
    if len(left) != len(right):
        return False
    for a, b in zip(left, right):
        if not isinstance(a, dict) or not isinstance(b, dict):
            return False
        for key in ("ref_object_id", "ref_object_type", "display", "er", "ev", "cp"):
            if a.get(key) != b.get(key):
                return False
    return True


def _pool_energy_top_text(rows: list[dict[str, Any]], *, energy_key: str) -> str:
    key = str(energy_key or "").strip().lower()
    label = "ER" if key == "er" else "EV" if key == "ev" else "CP"
    parts: list[str] = []
    for row in rows[:5]:
        display = _as_str(row.get("display", "")).strip() or _as_str(row.get("ref_object_id", "")).strip() or "-"
        ref_type = _as_str(row.get("ref_object_type", "")).strip().upper() or "OBJ"
        about = _as_str(row.get("about", "")).strip()
        if about:
            display = f"{display} <- {about}"
        parts.append(
            f"{int(_as_int(row.get('rank', 0)))}.[{ref_type}] {display}({label}={_as_float(row.get(key, 0.0)):.4f})"
        )
    return " | ".join(parts)


def extract_tick_metrics(*, report: dict[str, Any], dataset_tick: dict[str, Any] | None = None) -> dict[str, Any]:
    """Extract a compact metrics record from a cycle report.

    `dataset_tick` is optional but recommended for slicing/plotting.
    """

    dt = _as_dict(dataset_tick)

    trace_id = _as_str(report.get("trace_id", ""))
    tick_id = _as_str(report.get("tick_id", ""))

    sensor = _as_dict(report.get("sensor"))
    input_queue = _as_dict(report.get("input_queue"))
    input_queue_submitted_text = _as_str(input_queue.get("submitted_text", ""))
    input_queue_source_text = _as_str(input_queue.get("source_text", ""))
    input_queue_tick_text = _as_str(input_queue.get("tick_text", ""))
    input_queue_queued_from_new_input_count = _as_int(input_queue.get("queued_from_new_input_count", 0))
    input_queue_pending_count_before_enqueue = _as_int(input_queue.get("pending_count_before_enqueue", 0))
    input_queue_pending_count_before_dequeue = _as_int(input_queue.get("pending_count_before_dequeue", 0))
    input_queue_pending_count_after_dequeue = _as_int(input_queue.get("pending_count_after_dequeue", 0))
    sensor_input_text = _as_str(sensor.get("input_text", ""))
    input_text = input_queue_tick_text or input_queue_source_text or _as_str(dt.get("input_text", "")) or sensor_input_text
    input_queue_tick_submitted_mismatch = bool(
        input_queue_submitted_text
        and input_queue_tick_text
        and input_queue_tick_text != input_queue_submitted_text
    )
    input_queue_deferred_chunk_consumed = bool(
        input_queue_pending_count_before_enqueue > 0
        and input_queue_tick_text
        and input_queue_tick_text != input_queue_submitted_text
    )
    has_live_input = bool(input_queue_tick_text or input_queue_source_text or sensor_input_text)
    if has_live_input:
        input_is_empty = False
    elif "input_is_empty" in dt:
        input_is_empty = bool(dt.get("input_is_empty", False))
    else:
        input_is_empty = not bool(input_text)

    final_state = _as_dict(report.get("final_state"))
    final_snapshot = _as_dict(final_state.get("state_snapshot"))
    snapshot_summary = _as_dict(final_snapshot.get("summary"))
    if not snapshot_summary:
        snapshot_summary = _nested_dict(report, "state_snapshot", "summary")
    energy_summary = _as_dict(final_state.get("state_energy_summary"))
    if not energy_summary:
        energy_summary = _as_dict(report.get("state_energy_summary"))
    pool_er_top5 = _pool_energy_top_items(final_snapshot, energy_key="er", limit=5)
    pool_ev_top5 = _pool_energy_top_items(final_snapshot, energy_key="ev", limit=5)
    pool_cp_top5 = _pool_energy_top_items(final_snapshot, energy_key="cp", limit=5)
    pool_er_structure_top5 = _pool_energy_top_items(
        final_snapshot,
        energy_key="er",
        limit=5,
        exclude_atomic_feature_sa=True,
    )
    pool_ev_structure_top5 = _pool_energy_top_items(
        final_snapshot,
        energy_key="ev",
        limit=5,
        exclude_atomic_feature_sa=True,
    )
    pool_cp_structure_top5 = _pool_energy_top_items(
        final_snapshot,
        energy_key="cp",
        limit=5,
        exclude_atomic_feature_sa=True,
    )
    pool_er_top5 = _dedupe_top_preview_list(pool_er_top5)
    pool_ev_top5 = _dedupe_top_preview_list(pool_ev_top5)
    pool_cp_top5 = _dedupe_top_preview_list(pool_cp_top5)
    pool_er_structure_top5_same_as_top5 = _same_top_preview_list(pool_er_structure_top5, pool_er_top5)
    pool_ev_structure_top5_same_as_top5 = _same_top_preview_list(pool_ev_structure_top5, pool_ev_top5)
    pool_cp_structure_top5_same_as_top5 = _same_top_preview_list(pool_cp_structure_top5, pool_cp_top5)
    if pool_er_structure_top5_same_as_top5:
        pool_er_structure_top5 = []
    else:
        pool_er_structure_top5 = _dedupe_top_preview_list(pool_er_structure_top5)
    if pool_ev_structure_top5_same_as_top5:
        pool_ev_structure_top5 = []
    else:
        pool_ev_structure_top5 = _dedupe_top_preview_list(pool_ev_structure_top5)
    if pool_cp_structure_top5_same_as_top5:
        pool_cp_structure_top5 = []
    else:
        pool_cp_structure_top5 = _dedupe_top_preview_list(pool_cp_structure_top5)
    hdb_snapshot = _as_dict(final_state.get("hdb_snapshot"))
    if not hdb_snapshot:
        hdb_snapshot = _as_dict(report.get("hdb_snapshot"))
    if not hdb_snapshot:
        hdb_snapshot = _nested_dict(report, "hdb", "snapshot")
    hdb_summary = _as_dict(hdb_snapshot.get("summary"))
    if not hdb_summary:
        hdb_summary = _nested_dict(report, "hdb", "snapshot", "summary")
    hdb_stats = _as_dict(hdb_snapshot.get("stats"))
    if not hdb_stats:
        hdb_stats = _as_dict(report.get("hdb_stats"))
    if not hdb_stats:
        hdb_stats = _nested_dict(report, "hdb", "stats")
    hdb_pointer_index = _as_dict(hdb_stats.get("pointer_index"))

    attention = _as_dict(report.get("attention"))
    cam_snapshot_summary = _as_dict(attention.get("cam_snapshot_summary"))
    memory_snapshot_summary = _as_dict(attention.get("memory_snapshot_summary"))
    attention_top5 = _attention_top_items(_as_list(attention.get("top_items")), limit=5)
    attention_resource = _as_dict(attention.get("attention_energy_resource"))
    maintenance = _as_dict(report.get("maintenance"))
    maintenance_summary = _as_dict(maintenance.get("summary"))
    maintenance_before = _as_dict(maintenance.get("before_summary"))
    maintenance_after = _as_dict(maintenance.get("after_summary"))
    maintenance_timing = _as_dict(maintenance.get("timing"))

    structure_level = _as_dict(report.get("structure_level"))
    structure_result = _as_dict(structure_level.get("result"))
    structure_result_metrics = _as_dict(structure_result.get("metrics"))
    stimulus_level = _as_dict(report.get("stimulus_level"))
    stimulus_result = _as_dict(stimulus_level.get("result"))
    stimulus_result_metrics = _as_dict(stimulus_result.get("metrics"))
    stimulus_perf_metrics = _as_dict(stimulus_result.get("metrics"))
    structure_debug = _as_dict(structure_result.get("debug"))
    stimulus_debug = _as_dict(stimulus_result.get("debug"))
    stimulus_round_details = _as_list(stimulus_debug.get("round_details"))
    stimulus_early_stop = _as_dict(stimulus_debug.get("early_stop"))
    stimulus_early_stop_reason = _as_str(stimulus_early_stop.get("reason", "")).strip()
    stimulus_match_v2_metrics = _collect_v2_candidate_metrics(
        round_details=stimulus_round_details,
        candidate_list_key="candidate_details",
        legacy_score_key="competition_score_legacy",
        competition_score_key="competition_score",
        metric_prefix="stimulus_match_v2",
    )
    stimulus_shadow_memory_match_v2_metrics = _collect_v2_candidate_metrics(
        round_details=stimulus_round_details,
        candidate_list_key="shadow_candidate_details",
        legacy_score_key="competition_score_legacy",
        competition_score_key="competition_score",
        metric_prefix="stimulus_shadow_memory_match_v2",
    )
    stimulus_transfer_metrics = _collect_stimulus_transfer_metrics(round_details=stimulus_round_details)
    structure_match_v2_metrics = _collect_v2_candidate_metrics(
        round_details=_as_list(structure_debug.get("round_details")),
        candidate_list_key="candidate_groups",
        legacy_score_key="competition_score_legacy",
        competition_score_key="competition_score",
        metric_prefix="structure_match_v2",
    )
    structure_round_path_metrics = _collect_structure_round_path_metrics(
        round_details=_as_list(structure_debug.get("round_details"))
    )
    internal_stimulus = _as_dict(report.get("internal_stimulus"))
    internal_stimulus_raw = _as_dict(report.get("internal_stimulus_raw"))
    merged_stimulus = _as_dict(report.get("merged_stimulus"))
    cache_neutralization = _as_dict(report.get("cache_neutralization"))
    cache_input_pkt = _as_dict(cache_neutralization.get("input_packet"))
    cache_residual_pkt = _as_dict(cache_neutralization.get("residual_packet"))
    cache_priority_summary = _as_dict(cache_neutralization.get("priority_summary"))
    cache_priority_cut_metrics = _as_dict(cache_priority_summary.get("cut_metrics"))
    pool_apply = _as_dict(report.get("pool_apply"))
    pool_apply_result = _as_dict(pool_apply.get("apply_result"))
    landed_pkt = _as_dict(pool_apply.get("landed_packet"))
    residual_tail_memory_projection = _as_dict(pool_apply.get("residual_tail_memory_projection"))
    residual_tail_memory_payload = _as_dict(residual_tail_memory_projection.get("memory"))
    residual_tail_memory_energy = _as_dict(residual_tail_memory_payload.get("energy"))
    residual_tail_memory_component = _as_dict(residual_tail_memory_payload.get("component_energy"))
    stimulus_object_projection_metrics = _collect_stimulus_object_projection_metrics(
        runtime_projection_structures=_as_list(stimulus_result.get("runtime_projection_structures")),
        transfer_metrics=stimulus_transfer_metrics,
        residual_tail_memory_projection=residual_tail_memory_projection,
    )
    runtime_residual_package = _as_dict(pool_apply.get("runtime_residual_package"))
    runtime_residual_package_payload = _as_dict(runtime_residual_package.get("package"))
    runtime_residual_package_energy = _as_dict(runtime_residual_package_payload.get("energy"))
    runtime_residual_package_structure = _as_dict(runtime_residual_package_payload.get("structure"))
    runtime_residual_immediate_promotion = _as_dict(runtime_residual_package.get("immediate_promotion"))
    runtime_residual_promotion = _as_dict(report.get("runtime_residual_promotion"))
    runtime_residual_promotion_items = [
        item for item in _as_list(runtime_residual_promotion.get("items")) if isinstance(item, dict)
    ]
    runtime_residual_exact_rebind_count = _as_int(runtime_residual_promotion.get("exact_rebind_count", 0))
    if runtime_residual_exact_rebind_count <= 0 and runtime_residual_promotion_items:
        runtime_residual_exact_rebind_count = int(
            sum(1 for item in runtime_residual_promotion_items if str(item.get("fast_path", "") or "") == "exact_rebind" and bool(item.get("promoted", False)))
        )
    runtime_residual_full_identity_count = _as_int(runtime_residual_promotion.get("full_identity_count", 0))
    if runtime_residual_full_identity_count <= 0 and runtime_residual_promotion_items:
        runtime_residual_full_identity_count = int(
            sum(1 for item in runtime_residual_promotion_items if str(item.get("fast_path", "") or "") == "full_identity" and bool(item.get("promoted", False)))
        )
    runtime_residual_hdb_fallback_count = _as_int(runtime_residual_promotion.get("hdb_fallback_count", 0))
    if runtime_residual_hdb_fallback_count <= 0 and runtime_residual_promotion_items:
        runtime_residual_hdb_fallback_count = int(
            sum(1 for item in runtime_residual_promotion_items if bool(item.get("hdb_fallback", False)))
        )
    internal_resolution = _as_dict(structure_result.get("internal_resolution"))
    cam_runtime_priority_projection = _as_dict(structure_result.get("cam_runtime_priority_projection"))

    induction = _as_dict(report.get("induction"))
    induction_result = _as_dict(induction.get("result"))
    induction_result_metrics = _as_dict(induction_result.get("metrics"))
    induction_projection = _as_dict(induction_result.get("growth_projection"))
    induction_applied_targets = _as_list(induction.get("applied_targets"))
    induction_result_targets = _as_list(induction_result.get("induction_targets", []))
    induction_energy_graph_v2_enabled = int(bool(induction_result.get("energy_graph_v2_enabled", False)))
    induction_energy_graph_round_summaries = _as_list(induction_result.get("energy_graph_round_summaries", []))
    induction_energy_graph_layer_histogram = _as_dict(induction_result.get("energy_graph_layer_histogram", {}))

    memory_activation = _as_dict(report.get("memory_activation"))
    map_snapshot = _as_dict(memory_activation.get("snapshot"))
    map_summary = _as_dict(map_snapshot.get("summary"))
    map_apply = _as_dict(memory_activation.get("apply_result"))
    map_feedback = _as_dict(memory_activation.get("feedback_result"))
    memory_runtime_projection = _as_dict(memory_activation.get("runtime_projection"))
    memory_runtime_projection_summary = _as_dict(memory_runtime_projection.get("summary"))
    memory_path_mode = _as_str(memory_activation.get("path_mode", ""))
    memory_feedback_applied_count = _as_int(map_feedback.get("applied_count", 0))
    memory_feedback_total_er = _as_float(map_feedback.get("total_feedback_er", 0.0))
    memory_feedback_total_ev = _as_float(map_feedback.get("total_feedback_ev", 0.0))
    memory_feedback_total_energy = _as_float(map_feedback.get("total_feedback_energy", 0.0))
    memory_feedback_packet_count = _as_int(map_feedback.get("packet_feedback_count", 0))
    memory_feedback_packet_total_er = _as_float(map_feedback.get("packet_feedback_total_er", 0.0))
    memory_feedback_packet_total_ev = _as_float(map_feedback.get("packet_feedback_total_ev", 0.0))
    memory_feedback_packet_applied_total_er = _as_float(map_feedback.get("packet_applied_total_er", 0.0))
    memory_feedback_packet_applied_total_ev = _as_float(map_feedback.get("packet_applied_total_ev", 0.0))
    memory_feedback_packet_apply_efficiency_er = _as_float(map_feedback.get("packet_apply_efficiency_er", 0.0))
    memory_feedback_packet_apply_efficiency_ev = _as_float(map_feedback.get("packet_apply_efficiency_ev", 0.0))
    memory_feedback_structure_projection_ratio_used = _as_float(map_feedback.get("structure_projection_ratio_used", 0.0))
    memory_feedback_pool_ev_to_er_ratio_before = _as_float(
        _as_dict(map_feedback.get("pool_energy_before_feedback")).get("ev_to_er_ratio", 0.0)
    )
    memory_feedback_structure_projection_attempted_count = _as_int(map_feedback.get("structure_projection_attempted_count", 0))
    memory_feedback_structure_projection_skipped_count = _as_int(map_feedback.get("structure_projection_skipped_count", 0))
    memory_feedback_structure_projection_count = _as_int(map_feedback.get("structure_projection_count", 0))
    memory_feedback_structure_projection_total_er = _as_float(map_feedback.get("structure_projection_total_er", 0.0))
    memory_feedback_structure_projection_total_ev = _as_float(map_feedback.get("structure_projection_total_ev", 0.0))
    memory_feedback_structure_projection_effective_ratio = round(
        float(memory_feedback_structure_projection_count)
        / max(1.0, float(max(1, memory_feedback_structure_projection_attempted_count))),
        8,
    )

    cfs = _as_dict(report.get("cognitive_feeling"))
    cfs_signals = _as_list(cfs.get("cfs_signals"))
    innate_script = _as_dict(report.get("innate_script"))
    innate_focus = _as_dict(innate_script.get("focus"))
    innate_tick_rules = _as_dict(innate_script.get("tick_rules"))
    innate_tick_rules_audit = _as_dict(innate_tick_rules.get("audit"))
    innate_focus_audit = _as_dict(innate_focus.get("audit"))
    if not innate_tick_rules_audit:
        innate_tick_rules_audit = innate_focus_audit
    innate_emotion_updates = _as_dict(innate_focus.get("emotion_updates"))
    innate_action_triggers = _as_list(innate_focus.get("action_triggers"))
    innate_triggered_rules = _as_list(innate_focus.get("triggered_rules"))
    innate_triggered_scripts = _as_list(innate_focus.get("triggered_scripts"))
    iesm_emotion_update_values: dict[str, float] = {}
    iesm_emotion_update_abs_total = 0.0
    for raw_channel, raw_delta in innate_emotion_updates.items():
        channel_code = _normalize_emotion_channel_code(raw_channel)
        if not channel_code:
            continue
        try:
            delta_value = float(raw_delta)
        except Exception:
            continue
        iesm_emotion_update_values[channel_code] = round(
            float(iesm_emotion_update_values.get(channel_code, 0.0)) + float(delta_value),
            8,
        )
        iesm_emotion_update_abs_total += abs(float(delta_value))

    cognitive_stitching = _as_dict(report.get("cognitive_stitching"))
    cs_candidate_audit = _as_dict(cognitive_stitching.get("candidate_audit"))
    cs_apply_audit = _as_dict(cognitive_stitching.get("apply_audit"))
    cs_candidate_score_means = _as_dict(cs_candidate_audit.get("score_means"))
    cs_candidate_rejected_reason_counts = _as_dict(cs_candidate_audit.get("rejected_reason_counts"))
    cs_apply_skip_reason_counts = _as_dict(cs_apply_audit.get("skip_reason_counts"))
    cs_narrative = _as_list(cognitive_stitching.get("narrative_top_items"))
    cs_action_log = _as_list(cognitive_stitching.get("action_log"))
    cs_event_grasp = _as_dict(cognitive_stitching.get("event_grasp"))
    cs_top_grasp = 0.0
    cs_max_grasp = 0.0
    cs_top_total_energy = 0.0
    cs_grasp_positive_count = 0
    cs_concat_narrative_count = 0
    cs_action_log_count = 0
    cs_action_log_concat_count = 0
    cs_action_log_reinforce_concat_count = 0
    cs_action_object_fatigue_hit_count = 0
    cs_action_object_fatigue_before_values: list[float] = []
    cs_action_object_fatigue_scale_values: list[float] = []
    if cs_narrative and isinstance(cs_narrative[0], dict):
        cs_top_grasp = _as_float(cs_narrative[0].get("event_grasp", 0.0))
        cs_top_total_energy = _as_float(cs_narrative[0].get("total_energy", 0.0))
    for item in cs_narrative:
        if not isinstance(item, dict):
            continue
        if _as_str(item.get("narrative_kind", "")) == "concat_structure":
            cs_concat_narrative_count += 1
        value = _as_float(item.get("event_grasp", 0.0))
        if value > cs_max_grasp:
            cs_max_grasp = value
        if value > 0.0:
            cs_grasp_positive_count += 1
    for item in cs_action_log:
        if not isinstance(item, dict):
            continue
        cs_action_log_count += 1
        action_name = _as_str(item.get("action", ""))
        action_family = _as_str(item.get("action_family", ""))
        if action_family == "concat_context_structure":
            if action_name.startswith("reinforce_"):
                cs_action_log_reinforce_concat_count += 1
            else:
                cs_action_log_concat_count += 1
        object_fatigue_before = _as_float(item.get("object_stitch_fatigue_before", 0.0))
        object_fatigue_scale = _as_float(item.get("object_stitch_fatigue_scale", 1.0), 1.0)
        cs_action_object_fatigue_before_values.append(object_fatigue_before)
        cs_action_object_fatigue_scale_values.append(object_fatigue_scale)
        if object_fatigue_before > 0.0 or object_fatigue_scale < 0.999999:
            cs_action_object_fatigue_hit_count += 1

    # Per-kind max strength
    cfs_max_by_kind: dict[str, float] = {k: 0.0 for k in CORE_CFS_KINDS}
    cfs_count_by_kind: dict[str, int] = {k: 0 for k in CORE_CFS_KINDS}
    cfs_total_strength = 0.0
    for sig in cfs_signals:
        if not isinstance(sig, dict):
            continue
        kind = _as_str(sig.get("kind", "")).strip()
        strength = _as_float(sig.get("strength", 0.0))
        cfs_total_strength += max(0.0, strength)
        if kind in cfs_max_by_kind:
            cfs_count_by_kind[kind] = int(cfs_count_by_kind.get(kind, 0)) + 1
            if strength > float(cfs_max_by_kind.get(kind, 0.0) or 0.0):
                cfs_max_by_kind[kind] = float(strength)

    emotion = _as_dict(report.get("emotion"))
    rwd_pun_snapshot = _as_dict(emotion.get("rwd_pun_snapshot"))
    nt_after = _as_dict(emotion.get("nt_state_after"))
    energy_balance = _as_dict(report.get("energy_balance"))
    energy_balance_hdb_scales = _as_dict(energy_balance.get("hdb_scales_out"))
    modulation_applied = _as_dict(report.get("modulation_applied"))
    modulation_applied_hdb = _as_dict(modulation_applied.get("hdb"))
    modulation_applied_hdb_applied = _as_dict(modulation_applied_hdb.get("applied"))
    applied_base_weight_er_gain = _as_dict(modulation_applied_hdb_applied.get("base_weight_er_gain"))
    applied_base_weight_ev_wear = _as_dict(modulation_applied_hdb_applied.get("base_weight_ev_wear"))
    applied_ev_threshold = _as_dict(modulation_applied_hdb_applied.get("ev_propagation_threshold"))
    applied_ev_ratio = _as_dict(modulation_applied_hdb_applied.get("ev_propagation_ratio"))
    applied_er_ratio = _as_dict(modulation_applied_hdb_applied.get("er_induction_ratio"))
    # Normalize channel keys (keep original for audit; provide stable fields for plots)
    nt = {
        "OXY": _as_float(nt_after.get("OXY", nt_after.get("催产素", 0.0))),
        "DA": _as_float(nt_after.get("DA", nt_after.get("多巴胺", 0.0))),
        "END": _as_float(nt_after.get("END", nt_after.get("内啡肽", 0.0))),
        "COR": _as_float(nt_after.get("COR", nt_after.get("皮质醇", 0.0))),
        "ADR": _as_float(nt_after.get("ADR", nt_after.get("肾上腺素", 0.0))),
        "SER": _as_float(nt_after.get("SER", nt_after.get("血清素", 0.0))),
        "NOV": _as_float(nt_after.get("NOV", nt_after.get("新颖探索", 0.0))),
        "FOC": _as_float(nt_after.get("FOC", nt_after.get("专注锁定", 0.0))),
    }

    attention_modulation = _as_dict(attention.get("modulation_applied"))
    attention_effective_priority_weights = _as_dict(attention.get("effective_priority_weights"))
    attention_dynamic_cutoff = _as_dict(attention.get("dynamic_cutoff"))

    action = _as_dict(report.get("action"))
    executed_actions = _as_list(action.get("executed_actions"))
    action_nodes = _as_list(action.get("nodes"))
    tick_is_synthetic = bool(dt.get("synthetic_tick", False))
    iesm_action_trigger_count = 0
    iesm_action_trigger_count_source_visible = 0
    iesm_action_trigger_count_synthetic_only = 0
    iesm_action_trigger_targeted_count = 0
    iesm_action_trigger_targeted_count_source_visible = 0
    iesm_action_trigger_targeted_count_synthetic_only = 0
    iesm_action_trigger_target_missing_count = 0
    iesm_action_trigger_target_missing_count_source_visible = 0
    iesm_action_trigger_target_missing_count_synthetic_only = 0
    iesm_triggered_rule_count = 0
    iesm_triggered_rule_count_source_visible = 0
    iesm_triggered_rule_count_synthetic_only = 0
    iesm_triggered_script_count = len([x for x in innate_triggered_scripts if isinstance(x, dict)])
    iesm_triggered_script_count_source_visible = 0 if tick_is_synthetic else int(iesm_triggered_script_count)
    iesm_triggered_script_count_synthetic_only = int(iesm_triggered_script_count) if tick_is_synthetic else 0
    iesm_action_trigger_kind_counts: dict[str, int] = {}
    iesm_action_trigger_kind_counts_source_visible: dict[str, int] = {}
    iesm_action_trigger_kind_counts_synthetic_only: dict[str, int] = {}
    iesm_action_trigger_targeted_kind_counts: dict[str, int] = {}
    iesm_action_trigger_targeted_kind_counts_source_visible: dict[str, int] = {}
    iesm_action_trigger_targeted_kind_counts_synthetic_only: dict[str, int] = {}
    iesm_action_trigger_target_missing_kind_counts: dict[str, int] = {}
    iesm_action_trigger_target_missing_kind_counts_source_visible: dict[str, int] = {}
    iesm_action_trigger_target_missing_kind_counts_synthetic_only: dict[str, int] = {}
    iesm_action_trigger_rule_counts: dict[str, int] = {}
    iesm_action_trigger_rule_counts_source_visible: dict[str, int] = {}
    iesm_action_trigger_rule_counts_synthetic_only: dict[str, int] = {}
    iesm_triggered_rule_counts: dict[str, int] = {}
    iesm_triggered_rule_counts_source_visible: dict[str, int] = {}
    iesm_triggered_rule_counts_synthetic_only: dict[str, int] = {}
    for row in innate_action_triggers:
        if not isinstance(row, dict):
            continue
        iesm_action_trigger_count += 1
        if tick_is_synthetic:
            iesm_action_trigger_count_synthetic_only += 1
        else:
            iesm_action_trigger_count_source_visible += 1
        kind = _as_str(row.get("action_kind", "")).strip() or _as_str(row.get("kind", "")).strip() or "custom"
        iesm_action_trigger_kind_counts[kind] = int(iesm_action_trigger_kind_counts.get(kind, 0)) + 1
        if tick_is_synthetic:
            iesm_action_trigger_kind_counts_synthetic_only[kind] = int(iesm_action_trigger_kind_counts_synthetic_only.get(kind, 0)) + 1
        else:
            iesm_action_trigger_kind_counts_source_visible[kind] = int(iesm_action_trigger_kind_counts_source_visible.get(kind, 0)) + 1
        target_info = _extract_action_target_from_payload(row)
        has_target = bool(
            _as_str(target_info.get("target_ref_object_id", "")).strip()
            or _as_str(target_info.get("target_item_id", "")).strip()
        )
        if has_target:
            iesm_action_trigger_targeted_count += 1
            iesm_action_trigger_targeted_kind_counts[kind] = int(iesm_action_trigger_targeted_kind_counts.get(kind, 0)) + 1
            if tick_is_synthetic:
                iesm_action_trigger_targeted_count_synthetic_only += 1
                iesm_action_trigger_targeted_kind_counts_synthetic_only[kind] = int(
                    iesm_action_trigger_targeted_kind_counts_synthetic_only.get(kind, 0)
                ) + 1
            else:
                iesm_action_trigger_targeted_count_source_visible += 1
                iesm_action_trigger_targeted_kind_counts_source_visible[kind] = int(
                    iesm_action_trigger_targeted_kind_counts_source_visible.get(kind, 0)
                ) + 1
        else:
            iesm_action_trigger_target_missing_count += 1
            iesm_action_trigger_target_missing_kind_counts[kind] = int(
                iesm_action_trigger_target_missing_kind_counts.get(kind, 0)
            ) + 1
            if tick_is_synthetic:
                iesm_action_trigger_target_missing_count_synthetic_only += 1
                iesm_action_trigger_target_missing_kind_counts_synthetic_only[kind] = int(
                    iesm_action_trigger_target_missing_kind_counts_synthetic_only.get(kind, 0)
                ) + 1
            else:
                iesm_action_trigger_target_missing_count_source_visible += 1
                iesm_action_trigger_target_missing_kind_counts_source_visible[kind] = int(
                    iesm_action_trigger_target_missing_kind_counts_source_visible.get(kind, 0)
                ) + 1
        rule_id = _as_str(row.get("rule_id", "")).strip()
        if not rule_id:
            continue
        iesm_action_trigger_rule_counts[rule_id] = int(iesm_action_trigger_rule_counts.get(rule_id, 0)) + 1
        if tick_is_synthetic:
            iesm_action_trigger_rule_counts_synthetic_only[rule_id] = int(iesm_action_trigger_rule_counts_synthetic_only.get(rule_id, 0)) + 1
        else:
            iesm_action_trigger_rule_counts_source_visible[rule_id] = int(iesm_action_trigger_rule_counts_source_visible.get(rule_id, 0)) + 1
    for row in innate_triggered_rules:
        if not isinstance(row, dict):
            continue
        rule_id = _as_str(row.get("rule_id", "")).strip()
        if not rule_id:
            continue
        iesm_triggered_rule_count += 1
        if tick_is_synthetic:
            iesm_triggered_rule_count_synthetic_only += 1
        else:
            iesm_triggered_rule_count_source_visible += 1
        iesm_triggered_rule_counts[rule_id] = int(iesm_triggered_rule_counts.get(rule_id, 0)) + 1
        if tick_is_synthetic:
            iesm_triggered_rule_counts_synthetic_only[rule_id] = int(iesm_triggered_rule_counts_synthetic_only.get(rule_id, 0)) + 1
        else:
            iesm_triggered_rule_counts_source_visible[rule_id] = int(iesm_triggered_rule_counts_source_visible.get(rule_id, 0)) + 1
    attempted_kind_counts: dict[str, int] = {}
    executed_kind_counts: dict[str, int] = {}
    scheduled_kind_counts: dict[str, int] = {}
    action_attempted_count = 0
    action_executed_count = 0
    action_attempted_count_source_visible = 0
    action_attempted_count_synthetic_only = 0
    action_executed_count_source_visible = 0
    action_executed_count_synthetic_only = 0
    attempted_kind_counts_source_visible: dict[str, int] = {}
    attempted_kind_counts_synthetic_only: dict[str, int] = {}
    scheduled_kind_counts_source_visible: dict[str, int] = {}
    scheduled_kind_counts_synthetic_only: dict[str, int] = {}
    executed_kind_counts_source_visible: dict[str, int] = {}
    executed_kind_counts_synthetic_only: dict[str, int] = {}
    for row in executed_actions:
        if not isinstance(row, dict):
            continue
        kind = _as_str(row.get("action_kind", "")).strip() or _as_str(row.get("kind", "")).strip()
        if not kind:
            continue
        attempted = bool(row.get("attempted", True))
        if attempted:
            action_attempted_count += 1
            attempted_kind_counts[kind] = int(attempted_kind_counts.get(kind, 0)) + 1
            if tick_is_synthetic:
                action_attempted_count_synthetic_only += 1
                attempted_kind_counts_synthetic_only[kind] = int(attempted_kind_counts_synthetic_only.get(kind, 0)) + 1
            else:
                action_attempted_count_source_visible += 1
                attempted_kind_counts_source_visible[kind] = int(attempted_kind_counts_source_visible.get(kind, 0)) + 1
        else:
            scheduled_kind_counts[kind] = int(scheduled_kind_counts.get(kind, 0)) + 1
            if tick_is_synthetic:
                scheduled_kind_counts_synthetic_only[kind] = int(scheduled_kind_counts_synthetic_only.get(kind, 0)) + 1
            else:
                scheduled_kind_counts_source_visible[kind] = int(scheduled_kind_counts_source_visible.get(kind, 0)) + 1
        if bool(row.get("success", False)):
            action_executed_count += 1
            executed_kind_counts[kind] = int(executed_kind_counts.get(kind, 0)) + 1
            if tick_is_synthetic:
                action_executed_count_synthetic_only += 1
                executed_kind_counts_synthetic_only[kind] = int(executed_kind_counts_synthetic_only.get(kind, 0)) + 1
            else:
                action_executed_count_source_visible += 1
                executed_kind_counts_source_visible[kind] = int(executed_kind_counts_source_visible.get(kind, 0)) + 1
    action_drive_vals: list[float] = []
    action_drive_active_count = 0
    action_node_kind_counts: dict[str, int] = {}
    action_active_kind_counts: dict[str, int] = {}
    action_ready_kind_counts: dict[str, int] = {}
    action_drive_kind_vals: dict[str, list[float]] = {}
    action_threshold_kind_vals: dict[str, list[float]] = {}
    action_margin_kind_vals: dict[str, list[float]] = {}
    action_base_threshold_vals: list[float] = []
    action_effective_threshold_vals: list[float] = []
    action_threshold_scale_vals: list[float] = []
    action_threshold_nt_scale_vals: list[float] = []
    action_threshold_rwd_pun_scale_vals: list[float] = []
    action_threshold_fatigue_scale_vals: list[float] = []
    action_threshold_delta_vals: list[float] = []
    action_threshold_rwd_pun_enabled_node_count = 0
    action_learning_reward_drive_gain_total = 0.0
    action_learning_punish_drive_penalty_total = 0.0
    action_local_drive_scale_vals: list[float] = []
    action_local_drive_modulated_node_count = 0
    action_local_targeted_node_count = 0
    action_local_lookup_hit_count = 0
    action_local_lookup_text_fallback_hit_count = 0
    action_local_lookup_miss_count = 0
    action_local_lookup_skipped_count = 0
    action_local_target_missing_count = 0
    action_local_modulation_disabled_count = 0
    action_local_reward_drive_bonus_total = 0.0
    action_local_punish_drive_penalty_total = 0.0
    action_local_reward_signal_total = 0.0
    action_local_punish_signal_total = 0.0
    action_local_zero_signal_hit_count = 0
    action_local_text_fallback_zero_signal_hit_count = 0
    action_local_kind_buckets: dict[str, dict[str, Any]] = {}
    for row in action_nodes:
        if not isinstance(row, dict):
            continue
        kind = _as_str(row.get("action_kind", "")).strip() or _as_str(row.get("kind", "")).strip() or "custom"
        local_kind_bucket = action_local_kind_buckets.setdefault(
            kind,
            {
                "targeted_node_count": 0,
                "lookup_hit_count": 0,
                "lookup_text_fallback_hit_count": 0,
                "lookup_miss_count": 0,
                "lookup_skipped_count": 0,
                "target_missing_count": 0,
                "modulation_disabled_count": 0,
                "drive_modulated_node_count": 0,
                "drive_scale_vals": [],
                "reward_drive_bonus_total": 0.0,
                "punish_drive_penalty_total": 0.0,
                "reward_signal_total": 0.0,
                "punish_signal_total": 0.0,
                "zero_signal_hit_count": 0,
                "text_fallback_zero_signal_hit_count": 0,
            },
        )
        drive = _as_float(row.get("drive", 0.0))
        base_threshold = max(0.0, _as_float(row.get("base_threshold", row.get("threshold", 0.0))))
        effective_threshold = max(0.0, _as_float(row.get("effective_threshold", row.get("threshold", 0.0))))
        threshold_scale = max(0.0, _as_float(row.get("threshold_scale", 1.0)))
        threshold_components = _as_dict(row.get("threshold_components"))
        local_drive_mod = _as_dict(row.get("local_drive_modulation"))
        margin = drive - effective_threshold
        action_drive_vals.append(drive)
        action_base_threshold_vals.append(base_threshold)
        action_effective_threshold_vals.append(effective_threshold)
        action_threshold_scale_vals.append(threshold_scale)
        action_threshold_nt_scale_vals.append(max(0.0, _as_float(threshold_components.get("nt_scale_clamped", 1.0))))
        action_threshold_rwd_pun_scale_vals.append(max(0.0, _as_float(threshold_components.get("rwd_pun_scale_clamped", 1.0))))
        action_threshold_fatigue_scale_vals.append(max(0.0, _as_float(threshold_components.get("fatigue_scale", 1.0))))
        action_threshold_delta_vals.append(_as_float(threshold_components.get("threshold_delta", effective_threshold - base_threshold)))
        if bool(threshold_components.get("rwd_pun_enabled", False)):
            action_threshold_rwd_pun_enabled_node_count += 1
        action_learning_reward_drive_gain_total += max(0.0, -_as_float(threshold_components.get("rwd_pun_reward_threshold_delta", 0.0)))
        action_learning_punish_drive_penalty_total += max(0.0, _as_float(threshold_components.get("rwd_pun_punish_threshold_delta", 0.0)))
        if _as_str(row.get("target_ref_object_id", "")).strip() or _as_str(row.get("target_item_id", "")).strip():
            action_local_targeted_node_count += 1
            local_kind_bucket["targeted_node_count"] = int(local_kind_bucket.get("targeted_node_count", 0)) + 1
        local_reason = _as_str(_as_dict(local_drive_mod.get("detail")).get("reason", "")).strip().lower()
        local_status = _as_str(local_drive_mod.get("lookup_status", "")).strip().lower()
        local_lookup_mode = _as_str(local_drive_mod.get("lookup_mode", "")).strip().lower()
        if not local_status:
            if bool(local_drive_mod.get("lookup_hit", False)):
                local_status = "hit"
            elif local_reason == "local_feedback_not_found":
                local_status = "miss"
            else:
                local_status = "skipped"
        if local_status == "hit":
            action_local_lookup_hit_count += 1
            local_kind_bucket["lookup_hit_count"] = int(local_kind_bucket.get("lookup_hit_count", 0)) + 1
            if local_lookup_mode == "text_fallback":
                action_local_lookup_text_fallback_hit_count += 1
                local_kind_bucket["lookup_text_fallback_hit_count"] = int(local_kind_bucket.get("lookup_text_fallback_hit_count", 0)) + 1
        elif local_status == "miss":
            action_local_lookup_miss_count += 1
            local_kind_bucket["lookup_miss_count"] = int(local_kind_bucket.get("lookup_miss_count", 0)) + 1
        else:
            action_local_lookup_skipped_count += 1
            local_kind_bucket["lookup_skipped_count"] = int(local_kind_bucket.get("lookup_skipped_count", 0)) + 1
            if local_reason in {"target_required_but_missing", "lookup_target_missing"}:
                action_local_target_missing_count += 1
                local_kind_bucket["target_missing_count"] = int(local_kind_bucket.get("target_missing_count", 0)) + 1
            if local_reason in {"config_disabled", "node_disabled"}:
                action_local_modulation_disabled_count += 1
                local_kind_bucket["modulation_disabled_count"] = int(local_kind_bucket.get("modulation_disabled_count", 0)) + 1
        local_reward_signal = max(0.0, _as_float(local_drive_mod.get("reward", 0.0)))
        local_punish_signal = max(0.0, _as_float(local_drive_mod.get("punish", 0.0)))
        action_local_reward_signal_total += local_reward_signal
        action_local_punish_signal_total += local_punish_signal
        local_kind_bucket["reward_signal_total"] = float(local_kind_bucket.get("reward_signal_total", 0.0)) + local_reward_signal
        local_kind_bucket["punish_signal_total"] = float(local_kind_bucket.get("punish_signal_total", 0.0)) + local_punish_signal
        if local_status == "hit" and local_reward_signal <= 0.0 and local_punish_signal <= 0.0:
            action_local_zero_signal_hit_count += 1
            local_kind_bucket["zero_signal_hit_count"] = int(local_kind_bucket.get("zero_signal_hit_count", 0)) + 1
            if local_lookup_mode == "text_fallback":
                action_local_text_fallback_zero_signal_hit_count += 1
                local_kind_bucket["text_fallback_zero_signal_hit_count"] = int(
                    local_kind_bucket.get("text_fallback_zero_signal_hit_count", 0)
                ) + 1
        if bool(local_drive_mod.get("applied", False)):
            action_local_drive_modulated_node_count += 1
            scale_clamped = max(0.0, _as_float(local_drive_mod.get("scale_clamped", 1.0)))
            action_local_drive_scale_vals.append(scale_clamped)
            local_kind_bucket["drive_modulated_node_count"] = int(local_kind_bucket.get("drive_modulated_node_count", 0)) + 1
            kind_scale_vals = local_kind_bucket.get("drive_scale_vals")
            if not isinstance(kind_scale_vals, list):
                kind_scale_vals = []
                local_kind_bucket["drive_scale_vals"] = kind_scale_vals
            kind_scale_vals.append(scale_clamped)
        action_local_reward_drive_bonus_total += max(0.0, _as_float(local_drive_mod.get("reward_bonus_gain", row.get("tick_local_reward_bonus_total", 0.0))))
        action_local_punish_drive_penalty_total += max(0.0, _as_float(local_drive_mod.get("punish_penalty_gain", row.get("tick_local_punish_penalty_total", 0.0))))
        local_kind_bucket["reward_drive_bonus_total"] = float(local_kind_bucket.get("reward_drive_bonus_total", 0.0)) + max(
            0.0,
            _as_float(local_drive_mod.get("reward_bonus_gain", row.get("tick_local_reward_bonus_total", 0.0))),
        )
        local_kind_bucket["punish_drive_penalty_total"] = float(local_kind_bucket.get("punish_drive_penalty_total", 0.0)) + max(
            0.0,
            _as_float(local_drive_mod.get("punish_penalty_gain", row.get("tick_local_punish_penalty_total", 0.0))),
        )
        action_node_kind_counts[kind] = int(action_node_kind_counts.get(kind, 0)) + 1
        action_drive_kind_vals.setdefault(kind, []).append(drive)
        action_threshold_kind_vals.setdefault(kind, []).append(effective_threshold)
        action_margin_kind_vals.setdefault(kind, []).append(margin)
        if drive > 0.05:
            action_drive_active_count += 1
            action_active_kind_counts[kind] = int(action_active_kind_counts.get(kind, 0)) + 1
        if drive >= effective_threshold and (effective_threshold > 0.0 or drive > 0.0):
            action_ready_kind_counts[kind] = int(action_ready_kind_counts.get(kind, 0)) + 1
    action_local_kind_metrics: dict[str, Any] = {}
    used_action_local_suffix_to_kind: dict[str, str] = {}
    for raw_kind, bucket in action_local_kind_buckets.items():
        suffix_base = _metric_key_suffix(raw_kind, default="custom")
        suffix = suffix_base
        suffix_index = 2
        while suffix in used_action_local_suffix_to_kind and used_action_local_suffix_to_kind.get(suffix) != raw_kind:
            suffix = f"{suffix_base}_{suffix_index}"
            suffix_index += 1
        used_action_local_suffix_to_kind[suffix] = raw_kind
        scale_vals = _as_list(bucket.get("drive_scale_vals"))
        action_local_kind_metrics.update(
            {
                f"action_local_targeted_node_count_{suffix}": int(bucket.get("targeted_node_count", 0)),
                f"action_local_lookup_hit_count_{suffix}": int(bucket.get("lookup_hit_count", 0)),
                f"action_local_lookup_text_fallback_hit_count_{suffix}": int(bucket.get("lookup_text_fallback_hit_count", 0)),
                f"action_local_lookup_miss_count_{suffix}": int(bucket.get("lookup_miss_count", 0)),
                f"action_local_lookup_skipped_count_{suffix}": int(bucket.get("lookup_skipped_count", 0)),
                f"action_local_target_missing_count_{suffix}": int(bucket.get("target_missing_count", 0)),
                f"action_local_modulation_disabled_count_{suffix}": int(bucket.get("modulation_disabled_count", 0)),
                f"action_local_drive_modulated_node_count_{suffix}": int(bucket.get("drive_modulated_node_count", 0)),
                f"action_local_drive_scale_mean_{suffix}": round(
                    float(sum(_as_float_list(scale_vals)) / len(_as_float_list(scale_vals))) if _as_float_list(scale_vals) else 1.0,
                    8,
                ),
                f"action_local_reward_drive_bonus_total_{suffix}": round(float(bucket.get("reward_drive_bonus_total", 0.0)), 8),
                f"action_local_punish_drive_penalty_total_{suffix}": round(float(bucket.get("punish_drive_penalty_total", 0.0)), 8),
                f"action_local_reward_signal_total_{suffix}": round(float(bucket.get("reward_signal_total", 0.0)), 8),
                f"action_local_punish_signal_total_{suffix}": round(float(bucket.get("punish_signal_total", 0.0)), 8),
                f"action_local_zero_signal_hit_count_{suffix}": int(bucket.get("zero_signal_hit_count", 0)),
                f"action_local_text_fallback_zero_signal_hit_count_{suffix}": int(bucket.get("text_fallback_zero_signal_hit_count", 0)),
            }
        )

    timing = _as_dict(report.get("timing"))
    steps_ms = _as_dict(timing.get("steps_ms"))

    time_sensor = _as_dict(report.get("time_sensor"))
    ts_bucket_updates = _as_list(time_sensor.get("bucket_updates"))
    ts_attr_bindings = _as_list(time_sensor.get("attribute_bindings"))
    ts_delayed_tasks = _as_dict(time_sensor.get("delayed_tasks"))
    ts_delayed_registered = _as_dict(ts_delayed_tasks.get("registered"))
    ts_attr_source_counts: dict[str, int] = {}
    ts_bucket_energy_vals: list[float] = []
    for row in ts_bucket_updates:
        if not isinstance(row, dict):
            continue
        ts_bucket_energy_vals.append(_as_float(row.get("assigned_energy", 0.0)))
    for row in ts_attr_bindings:
        if not isinstance(row, dict):
            continue
        source = str(row.get("target_score_source", "") or "legacy_peak").strip() or "legacy_peak"
        ts_attr_source_counts[source] = int(ts_attr_source_counts.get(source, 0)) + 1
    ts_bucket_energy_sum = float(sum(ts_bucket_energy_vals)) if ts_bucket_energy_vals else 0.0
    ts_bucket_energy_max = float(max(ts_bucket_energy_vals)) if ts_bucket_energy_vals else 0.0
    external_sa_count = _as_int(
        sensor.get(
            "sa_count",
            _as_int(sensor.get("feature_sa_count", 0)) + _as_int(sensor.get("attribute_sa_count", 0)),
        )
    )
    internal_sa_count = _as_int(
        internal_stimulus.get("sa_count", internal_stimulus.get("unit_count", internal_resolution.get("selected_unit_count", 0)))
    )
    internal_csa_count = _as_int(internal_stimulus.get("csa_count", 0))
    internal_flat_token_count = _as_int(internal_stimulus.get("flat_token_count", len(_as_list(internal_stimulus.get("flat_tokens", []))) or internal_sa_count))
    internal_raw_sa_items = [item for item in _as_list(internal_stimulus_raw.get("sa_items")) if isinstance(item, dict)]
    internal_summary_units = [item for item in _as_list(internal_stimulus.get("feature_units")) if isinstance(item, dict)]
    internal_role_rows = internal_raw_sa_items or internal_summary_units
    internal_attribute_rows: list[dict[str, Any]] = []
    internal_numeric_attribute_count = 0
    internal_time_like_attribute_count = 0
    internal_cfs_attribute_count = 0
    internal_cfs_pressure_family_attribute_count = 0
    internal_cfs_expectation_family_attribute_count = 0
    internal_reward_signal_attribute_count = 0
    internal_punish_signal_attribute_count = 0
    internal_teacher_reward_signal_attribute_count = 0
    internal_teacher_punish_signal_attribute_count = 0
    for row in internal_role_rows:
        stimulus = _as_dict(row.get("stimulus"))
        content = _as_dict(row.get("content"))
        role = _as_str(row.get("role", stimulus.get("role", ""))).strip()
        attr_name = _as_str(row.get("attribute_name", content.get("attribute_name", ""))).strip()
        if role != "attribute" and not attr_name:
            continue
        internal_attribute_rows.append(row)
        attr_value = row.get("attribute_value", content.get("attribute_value"))
        value_type = _as_str(row.get("value_type", content.get("value_type", ""))).strip().lower()
        numeric_like = attr_value not in {None, ""} or value_type == "numerical"
        if numeric_like:
            internal_numeric_attribute_count += 1
        if attr_name.startswith("cfs_"):
            internal_cfs_attribute_count += 1
        if _matches_attr_family(attr_name, "cfs_pressure"):
            internal_cfs_pressure_family_attribute_count += 1
        if _matches_attr_family(attr_name, "cfs_expectation"):
            internal_cfs_expectation_family_attribute_count += 1
        if attr_name == "reward_signal":
            internal_reward_signal_attribute_count += 1
        if attr_name == "punish_signal":
            internal_punish_signal_attribute_count += 1
        if attr_name == "teacher_reward_signal":
            internal_teacher_reward_signal_attribute_count += 1
        if attr_name == "teacher_punish_signal":
            internal_teacher_punish_signal_attribute_count += 1
        row_meta = _as_dict(row.get("meta", content.get("meta", {})))
        row_ext = _as_dict(row_meta.get("ext"))
        is_time_like = bool(
            attr_name == "时间感受"
            or any(
                key in row_ext
                for key in (
                    "time_bucket_id",
                    "time_bucket_ref_object_id",
                    "time_bucket_center_sec",
                    "time_basis",
                    "delta_sec",
                    "delta_value",
                )
            )
        )
        if is_time_like:
            internal_time_like_attribute_count += 1
    internal_to_external_sa_ratio = round(float(internal_sa_count) / max(1.0, float(max(1, external_sa_count))), 8)
    internal_resolution_structure_count_selected = _as_int(
        internal_resolution.get("structure_count_selected", internal_resolution.get("structure_count", 0))
    )
    internal_resolution_structure_count_total = _as_int(
        internal_resolution.get("structure_count_total", internal_resolution_structure_count_selected)
    )
    internal_resolution_structure_count_dropped = _as_int(
        internal_resolution.get(
            "structure_count_dropped",
            max(0, internal_resolution_structure_count_total - internal_resolution_structure_count_selected),
        )
    )
    pool_energy_summary = _as_dict(energy_summary.get("pool"))
    pool_active_item_count = _as_int(snapshot_summary.get("active_item_count", 0))
    pool_contextual_item_count = _as_int(snapshot_summary.get("contextual_item_count", 0))
    pool_explicit_context_item_count = _as_int(snapshot_summary.get("explicit_context_item_count", 0))
    pool_multi_context_item_count = _as_int(snapshot_summary.get("multi_context_item_count", 0))
    pool_residual_origin_item_count = _as_int(snapshot_summary.get("residual_origin_item_count", 0))
    pool_contextual_item_ratio = round(float(pool_contextual_item_count) / max(1.0, float(max(1, pool_active_item_count))), 8)
    pool_explicit_context_item_ratio = round(float(pool_explicit_context_item_count) / max(1.0, float(max(1, pool_active_item_count))), 8)
    pool_multi_context_item_ratio = round(float(pool_multi_context_item_count) / max(1.0, float(max(1, pool_active_item_count))), 8)
    pool_residual_origin_item_ratio = round(float(pool_residual_origin_item_count) / max(1.0, float(max(1, pool_active_item_count))), 8)
    pool_runtime_resolution_degraded_item_count = _as_int(snapshot_summary.get("runtime_resolution_degraded_item_count", 0))
    pool_runtime_resolution_active_component_count = _as_int(snapshot_summary.get("runtime_resolution_active_component_count", 0))
    pool_runtime_resolution_dropped_component_count = _as_int(snapshot_summary.get("runtime_resolution_dropped_component_count", 0))
    pool_energy_concentration = _as_float(pool_energy_summary.get("energy_concentration", 0.0))
    pool_effective_peak_count = _as_float(pool_energy_summary.get("effective_peak_count", 0.0))
    pool_complexity_score = _as_float(pool_energy_summary.get("complexity_score", 0.0))
    pool_core_energy_concentration = _as_float(pool_energy_summary.get("core_energy_concentration", 0.0))
    pool_core_effective_peak_count = _as_float(pool_energy_summary.get("core_effective_peak_count", 0.0))
    pool_core_complexity_score = _as_float(pool_energy_summary.get("core_complexity_score", 0.0))
    injection_fatigue = _as_dict(snapshot_summary.get("energy_injection_fatigue"))
    injection_tick = _as_dict(injection_fatigue.get("current_tick_stats"))
    injection_total = _as_dict(injection_fatigue.get("total_stats"))

    hdb_structure_count = _as_int(hdb_summary.get("structure_count", 0))
    hdb_contextual_structure_count = _as_int(hdb_summary.get("contextual_structure_count", 0))
    hdb_multi_context_structure_count = _as_int(hdb_summary.get("multi_context_structure_count", 0))
    hdb_same_content_multi_context_count = _as_int(hdb_summary.get("same_content_multi_context_count", 0))
    hdb_diff_entry_count = _as_int(hdb_summary.get("diff_entry_count", 0))
    hdb_contextual_diff_entry_count = _as_int(hdb_summary.get("contextual_diff_entry_count", 0))
    hdb_residual_diff_entry_count = _as_int(hdb_summary.get("residual_diff_entry_count", 0))
    hdb_primary_pointer_count = _as_int(hdb_pointer_index.get("primary_pointer_count", 0))
    hdb_fallback_pointer_count = _as_int(hdb_pointer_index.get("fallback_pointer_count", 0))
    hdb_signature_index_count = _as_int(hdb_pointer_index.get("signature_index_count", 0))
    hdb_recent_cache_count = _as_int(hdb_pointer_index.get("recent_cache_count", 0))
    hdb_exact_lookup_cache_count = _as_int(hdb_pointer_index.get("exact_lookup_cache_count", 0))
    hdb_numeric_bucket_family_count = _as_int(hdb_pointer_index.get("numeric_bucket_family_count", 0))
    hdb_numeric_bucket_count = _as_int(hdb_pointer_index.get("numeric_bucket_count", 0))
    hdb_structure_base_count = max(hdb_structure_count, hdb_contextual_structure_count, hdb_multi_context_structure_count, 1)
    hdb_contextual_structure_ratio = round(float(hdb_contextual_structure_count) / max(1.0, float(hdb_structure_base_count)), 8)
    hdb_multi_context_structure_ratio = round(float(hdb_multi_context_structure_count) / max(1.0, float(hdb_structure_base_count)), 8)
    hdb_same_content_multi_context_ratio = round(float(hdb_same_content_multi_context_count) / max(1.0, float(max(1, hdb_contextual_structure_count))), 8)
    hdb_contextual_diff_entry_ratio = round(float(hdb_contextual_diff_entry_count) / max(1.0, float(max(1, hdb_diff_entry_count))), 8)
    hdb_residual_diff_entry_ratio = round(float(hdb_residual_diff_entry_count) / max(1.0, float(max(1, hdb_diff_entry_count))), 8)
    pool_total_er = _as_float(energy_summary.get("total_er", 0.0))
    pool_total_ev = _as_float(energy_summary.get("total_ev", 0.0))
    pool_total_energy = _as_float(energy_summary.get("total_energy", pool_total_er + pool_total_ev))
    pool_total_cp = _as_float(energy_summary.get("total_cp", 0.0))
    induction_projection_mode = _as_str(
        induction_result.get("projection_mode", induction_projection.get("mode", "residual")),
        "residual",
    )
    induction_projection_mode_growth = int(induction_projection_mode == "growth")
    induction_projection_raw_target_count = _as_int(induction_projection.get("raw_target_count", 0))
    induction_projection_projected_target_count = _as_int(induction_projection.get("projected_target_count", 0))
    induction_growth_target_count = _as_int(induction_projection.get("growth_target_count", 0))
    induction_growth_identity_hit_count = _as_int(induction_projection.get("growth_identity_hit_count", 0))
    induction_growth_identity_created_count = _as_int(induction_projection.get("growth_identity_created_count", 0))
    induction_growth_identity_local_cache_hit_count = _as_int(
        induction_projection.get("growth_identity_local_cache_hit_count", 0)
    )
    induction_growth_identity_shared_cache_hit_count = _as_int(
        induction_projection.get("growth_identity_shared_cache_hit_count", 0)
    )
    induction_growth_identity_shared_cache_stale_count = _as_int(
        induction_projection.get("growth_identity_shared_cache_stale_count", 0)
    )
    induction_growth_identity_create_exact_lookup_skipped_count = _as_int(
        induction_projection.get("growth_identity_create_exact_lookup_skipped_count", 0)
    )
    induction_growth_persistence_batch_enabled = int(
        bool(induction_projection.get("persistence_batch_enabled", False))
    )
    induction_growth_target_apply_ref_fast_merge_enabled = int(
        bool(induction_projection.get("target_apply_ref_fast_merge_enabled", False))
    )
    induction_growth_target_apply_fast_ref_hit_merge_count = _as_int(
        induction_projection.get("target_apply_fast_ref_hit_merge_count", 0)
    )
    induction_growth_target_apply_insert_log_enabled = int(
        bool(induction_projection.get("target_apply_insert_log_enabled", False))
    )
    induction_growth_target_apply_insert_log_suppressed_count = _as_int(
        induction_projection.get("target_apply_insert_log_suppressed_count", 0)
    )
    induction_growth_identity_lookup_disabled_count = _as_int(
        induction_projection.get("growth_identity_lookup_disabled_count", 0)
    )
    induction_growth_runtime_only_count = _as_int(induction_projection.get("growth_runtime_only_count", 0))
    induction_growth_memory_candidate_count = _as_int(induction_projection.get("growth_memory_candidate_count", 0))
    induction_growth_memory_terminal_passthrough_count = _as_int(
        induction_projection.get("growth_memory_terminal_passthrough_count", 0)
    )
    induction_growth_pruned_low_energy_count = _as_int(induction_projection.get("growth_pruned_low_energy_count", 0))
    induction_growth_failed_count = _as_int(induction_projection.get("growth_failed_count", 0))
    induction_growth_skipped_missing_source_count = _as_int(
        induction_projection.get("growth_skipped_missing_source_count", 0)
    )
    induction_growth_skipped_missing_residual_count = _as_int(
        induction_projection.get("growth_skipped_missing_residual_count", 0)
    )
    induction_growth_deduped_count = _as_int(induction_projection.get("growth_deduped_count", 0))
    induction_growth_total_delta_er = _as_float(induction_projection.get("growth_total_delta_er", 0.0))
    induction_growth_total_delta_ev = _as_float(induction_projection.get("growth_total_delta_ev", 0.0))
    induction_growth_source_component_er_total = _as_float(
        induction_projection.get("growth_source_component_er_total", induction_growth_total_delta_er)
    )
    induction_growth_residual_component_ev_total = _as_float(
        induction_projection.get("growth_residual_component_ev_total", induction_growth_total_delta_ev)
    )
    induction_raw_residual_projection_profile_local_cache_hit_count = _as_int(
        induction_result_metrics.get("induction_raw_residual_projection_profile_local_cache_hit_count", 0)
    )
    induction_raw_residual_projection_profile_shared_cache_hit_count = _as_int(
        induction_result_metrics.get("induction_raw_residual_projection_profile_shared_cache_hit_count", 0)
    )
    induction_raw_residual_projection_profile_cache_store_count = _as_int(
        induction_result_metrics.get("induction_raw_residual_projection_profile_cache_store_count", 0)
    )
    induction_raw_residual_exact_candidates_local_cache_hit_count = _as_int(
        induction_result_metrics.get("induction_raw_residual_exact_candidates_local_cache_hit_count", 0)
    )
    induction_raw_residual_exact_candidates_shared_cache_hit_count = _as_int(
        induction_result_metrics.get("induction_raw_residual_exact_candidates_shared_cache_hit_count", 0)
    )
    induction_raw_residual_exact_candidates_cache_store_count = _as_int(
        induction_result_metrics.get("induction_raw_residual_exact_candidates_cache_store_count", 0)
    )
    induction_raw_residual_component_candidates_local_cache_hit_count = _as_int(
        induction_result_metrics.get("induction_raw_residual_component_candidates_local_cache_hit_count", 0)
    )
    induction_raw_residual_component_candidates_shared_cache_hit_count = _as_int(
        induction_result_metrics.get("induction_raw_residual_component_candidates_shared_cache_hit_count", 0)
    )
    induction_raw_residual_component_candidates_cache_store_count = _as_int(
        induction_result_metrics.get("induction_raw_residual_component_candidates_cache_store_count", 0)
    )
    induction_full_inclusion_shared_cache_hit_count = _as_int(
        induction_result_metrics.get("induction_full_inclusion_checks_shared_cache_hit_count", 0)
    )
    induction_full_inclusion_shared_cache_store_count = _as_int(
        induction_result_metrics.get("induction_full_inclusion_shared_cache_store_count", 0)
    )
    induction_total_delta_er = induction_growth_total_delta_er
    induction_total_delta_ev = _as_float(induction_result.get("total_delta_ev", 0.0))
    induction_total_ev_consumed = _as_float(induction_result.get("total_ev_consumed", 0.0))
    induction_propagated_budget_total_ev = _as_float(
        induction_result.get("propagated_budget_total_ev", induction_total_ev_consumed)
    )
    if induction_energy_graph_v2_enabled:
        induction_propagated_ev_total = max(0.0, min(induction_total_delta_ev, induction_propagated_budget_total_ev))
    else:
        induction_propagated_ev_total = max(0.0, min(induction_total_delta_ev, induction_total_ev_consumed))
    induction_propagated_ev_total = round(float(induction_propagated_ev_total), 8)
    induction_ev_from_er_total = round(max(0.0, induction_total_delta_ev - induction_propagated_ev_total), 8)
    induction_energy_graph_config = _as_dict(induction_result.get("energy_graph_config", {}))
    induction_energy_graph_config_max_rounds = _as_int(
        induction_result.get(
            "energy_graph_config_max_rounds",
            induction_energy_graph_config.get("max_rounds", 0),
        )
    )
    induction_energy_graph_round_count_max = _as_int(
        induction_result.get("energy_graph_round_count_max", len(induction_energy_graph_round_summaries))
    )
    induction_energy_graph_depth_max = _as_int(induction_result.get("energy_graph_depth_max", 0))
    induction_energy_graph_frontier_generated_count = _as_int(
        induction_result.get("energy_graph_frontier_generated_count", 0)
    )
    induction_energy_graph_frontier_pruned_count = _as_int(
        induction_result.get("energy_graph_frontier_pruned_count", 0)
    )
    induction_energy_graph_terminal_memory_count = _as_int(
        induction_result.get("energy_graph_terminal_memory_count", 0)
    )
    induction_energy_graph_root_reinduction_count = _as_int(
        induction_result.get("energy_graph_root_reinduction_count", 0)
    )
    induction_energy_graph_layer_widths = [
        _as_int(v, 0)
        for v in induction_energy_graph_layer_histogram.values()
        if _as_int(v, 0) > 0
    ]
    induction_energy_graph_layer_count = len(induction_energy_graph_layer_widths)
    induction_energy_graph_layer_max_width = max(induction_energy_graph_layer_widths, default=0)
    induction_energy_graph_layer_total_nodes = sum(induction_energy_graph_layer_widths)
    induction_energy_graph_round_summary_count = len(
        [row for row in induction_energy_graph_round_summaries if isinstance(row, dict)]
    )
    induction_energy_graph_frontier_budget_total_ev = round(
        sum(_as_float(_as_dict(row).get("frontier_budget_ev", 0.0)) for row in induction_energy_graph_round_summaries),
        8,
    )
    induction_energy_graph_root_induction_budget_total_ev = round(
        sum(_as_float(_as_dict(row).get("root_induction_budget_ev", 0.0)) for row in induction_energy_graph_round_summaries),
        8,
    )
    induction_energy_graph_round_delta_ev_total = round(
        sum(_as_float(_as_dict(row).get("round_delta_ev", 0.0)) for row in induction_energy_graph_round_summaries),
        8,
    )
    induction_energy_graph_round_delta_ev_max = round(
        max((_as_float(_as_dict(row).get("round_delta_ev", 0.0)) for row in induction_energy_graph_round_summaries), default=0.0),
        8,
    )
    induction_energy_graph_round_delta_ev_last = _as_float(
        _as_dict(induction_energy_graph_round_summaries[-1]).get("round_delta_ev", 0.0)
        if induction_energy_graph_round_summaries
        else 0.0
    )
    induction_energy_graph_frontier_in_count_max = max(
        (_as_int(_as_dict(row).get("frontier_in_count", 0)) for row in induction_energy_graph_round_summaries),
        default=0,
    )
    induction_energy_graph_frontier_out_count_max = max(
        (_as_int(_as_dict(row).get("frontier_out_count", 0)) for row in induction_energy_graph_round_summaries),
        default=0,
    )
    induction_source_item_count = _as_int(induction_result.get("source_item_count", 0))
    induction_source_selection = _as_dict(induction_result.get("source_selection", report.get("induction", {}).get("source_selection", {})))
    induction_propagated_target_count = _as_int(induction_result.get("propagated_target_count", 0))
    induction_induced_target_count = _as_int(induction_result.get("induced_target_count", 0))
    induction_target_count = len(induction_result_targets)
    induction_structure_target_count = 0
    induction_memory_target_count = 0
    induction_structure_target_total_ev = 0.0
    induction_memory_target_total_ev = 0.0
    induction_raw_residual_structure_target_count = 0
    induction_raw_residual_exact_structure_ev_target_count = 0
    induction_raw_residual_component_structure_ev_target_count = 0
    induction_raw_residual_memory_target_count = 0
    induction_raw_residual_hit_memory_target_count = 0
    induction_raw_residual_miss_memory_target_count = 0
    induction_raw_residual_structure_target_total_ev = 0.0
    induction_raw_residual_exact_structure_target_total_ev = 0.0
    induction_raw_residual_component_structure_target_total_ev = 0.0
    induction_raw_residual_memory_target_total_ev = 0.0
    induction_raw_residual_hit_memory_target_total_ev = 0.0
    induction_raw_residual_miss_memory_target_total_ev = 0.0
    for target in induction_result_targets:
        if not isinstance(target, dict):
            continue
        target_ev = _as_float(target.get("delta_ev", 0.0))
        raw_residual_structure_ev = _as_float(target.get("raw_residual_structure_delta_ev", 0.0))
        raw_residual_exact_structure_ev = _as_float(target.get("raw_residual_exact_structure_delta_ev", 0.0))
        raw_residual_component_structure_ev = _as_float(target.get("raw_residual_component_structure_delta_ev", 0.0))
        raw_residual_memory_ev = _as_float(target.get("raw_residual_memory_delta_ev", 0.0))
        raw_residual_hit_memory_ev = _as_float(target.get("raw_residual_hit_memory_delta_ev", 0.0))
        raw_residual_miss_memory_ev = _as_float(target.get("raw_residual_miss_memory_delta_ev", 0.0))
        projection_kind = _as_str(target.get("projection_kind", "structure")) or "structure"
        if projection_kind == "memory":
            induction_memory_target_count += 1
            induction_memory_target_total_ev += target_ev
        else:
            induction_structure_target_count += 1
            induction_structure_target_total_ev += target_ev
        if raw_residual_structure_ev > 0.0:
            induction_raw_residual_structure_target_count += 1
            induction_raw_residual_structure_target_total_ev += raw_residual_structure_ev
        if raw_residual_exact_structure_ev > 0.0:
            induction_raw_residual_exact_structure_ev_target_count += 1
            induction_raw_residual_exact_structure_target_total_ev += raw_residual_exact_structure_ev
        if raw_residual_component_structure_ev > 0.0:
            induction_raw_residual_component_structure_ev_target_count += 1
            induction_raw_residual_component_structure_target_total_ev += raw_residual_component_structure_ev
        if raw_residual_memory_ev > 0.0:
            induction_raw_residual_memory_target_count += 1
            induction_raw_residual_memory_target_total_ev += raw_residual_memory_ev
        if raw_residual_hit_memory_ev > 0.0:
            induction_raw_residual_hit_memory_target_count += 1
            induction_raw_residual_hit_memory_target_total_ev += raw_residual_hit_memory_ev
        if raw_residual_miss_memory_ev > 0.0:
            induction_raw_residual_miss_memory_target_count += 1
            induction_raw_residual_miss_memory_target_total_ev += raw_residual_miss_memory_ev
    induction_structure_target_total_ev = round(induction_structure_target_total_ev, 8)
    induction_memory_target_total_ev = round(induction_memory_target_total_ev, 8)
    induction_raw_residual_structure_target_total_ev = round(induction_raw_residual_structure_target_total_ev, 8)
    induction_raw_residual_exact_structure_target_total_ev = round(induction_raw_residual_exact_structure_target_total_ev, 8)
    induction_raw_residual_component_structure_target_total_ev = round(induction_raw_residual_component_structure_target_total_ev, 8)
    induction_raw_residual_memory_target_total_ev = round(induction_raw_residual_memory_target_total_ev, 8)
    induction_raw_residual_hit_memory_target_total_ev = round(induction_raw_residual_hit_memory_target_total_ev, 8)
    induction_raw_residual_miss_memory_target_total_ev = round(induction_raw_residual_miss_memory_target_total_ev, 8)
    induction_raw_residual_target_total_ev = round(
        induction_raw_residual_structure_target_total_ev + induction_raw_residual_memory_target_total_ev,
        8,
    )
    induction_raw_residual_hit_path_target_total_ev = round(
        induction_raw_residual_structure_target_total_ev + induction_raw_residual_hit_memory_target_total_ev,
        8,
    )
    induction_structure_target_ev_share = round(
        float(induction_structure_target_total_ev) / max(0.000001, float(max(induction_total_delta_ev, 0.0))),
        8,
    )
    induction_memory_target_ev_share = round(
        float(induction_memory_target_total_ev) / max(0.000001, float(max(induction_total_delta_ev, 0.0))),
        8,
    )
    induction_raw_residual_structure_target_ev_share = round(
        float(induction_raw_residual_structure_target_total_ev)
        / max(0.000001, float(max(induction_raw_residual_target_total_ev, 0.0))),
        8,
    )
    induction_raw_residual_memory_target_ev_share = round(
        float(induction_raw_residual_memory_target_total_ev)
        / max(0.000001, float(max(induction_raw_residual_target_total_ev, 0.0))),
        8,
    )
    induction_raw_residual_hit_path_structure_ev_share = round(
        float(induction_raw_residual_structure_target_total_ev)
        / max(0.000001, float(max(induction_raw_residual_hit_path_target_total_ev, 0.0))),
        8,
    )
    induction_raw_residual_hit_path_memory_ev_share = round(
        float(induction_raw_residual_hit_memory_target_total_ev)
        / max(0.000001, float(max(induction_raw_residual_hit_path_target_total_ev, 0.0))),
        8,
    )
    induction_raw_residual_exact_structure_ev_share = round(
        float(induction_raw_residual_exact_structure_target_total_ev)
        / max(0.000001, float(max(induction_raw_residual_structure_target_total_ev, 0.0))),
        8,
    )
    induction_raw_residual_component_structure_ev_share = round(
        float(induction_raw_residual_component_structure_target_total_ev)
        / max(0.000001, float(max(induction_raw_residual_structure_target_total_ev, 0.0))),
        8,
    )
    induction_propagated_target_ratio = round(
        float(induction_propagated_target_count) / max(1.0, float(max(1, induction_target_count))),
        8,
    )
    induction_ev_from_er_ratio = round(
        float(induction_ev_from_er_total) / max(0.000001, float(max(induction_total_delta_ev, 0.0))),
        8,
    )
    induction_targets_per_source_mean = round(
        float(induction_target_count) / max(1.0, float(max(1, induction_source_item_count))),
        8,
    )
    induction_fallback_used = int(bool(induction_result.get("fallback_used", False)))
    induction_raw_residual_entry_count = _as_int(induction_result.get("raw_residual_entry_count", 0))
    induction_raw_residual_entry_with_existing_structure_count = _as_int(
        induction_result.get("raw_residual_entry_with_existing_structure_count", 0)
    )
    induction_raw_residual_entry_routed_to_structure_count = _as_int(
        induction_result.get("raw_residual_entry_routed_to_structure_count", 0)
    )
    induction_raw_residual_existing_structure_target_count = _as_int(
        induction_result.get("raw_residual_existing_structure_target_count", 0)
    )
    induction_raw_residual_entry_materialized_structure_count = _as_int(
        induction_result.get("raw_residual_entry_materialized_structure_count", 0)
    )
    induction_raw_residual_materialized_structure_target_count = _as_int(
        induction_result.get("raw_residual_materialized_structure_target_count", 0)
    )
    induction_raw_residual_entry_with_component_structure_count = _as_int(
        induction_result.get("raw_residual_entry_with_component_structure_count", 0)
    )
    induction_raw_residual_entry_routed_to_component_structure_count = _as_int(
        induction_result.get("raw_residual_entry_routed_to_component_structure_count", 0)
    )
    induction_raw_residual_component_structure_target_count = _as_int(
        induction_result.get("raw_residual_component_structure_target_count", 0)
    )
    induction_raw_residual_structure_budget_weight = _as_float(
        induction_result.get("raw_residual_structure_budget_weight", 0.0)
    )
    induction_raw_residual_exact_structure_budget_weight = _as_float(
        induction_result.get("raw_residual_exact_structure_budget_weight", 0.0)
    )
    induction_raw_residual_materialized_structure_budget_weight = _as_float(
        induction_result.get("raw_residual_materialized_structure_budget_weight", 0.0)
    )
    induction_raw_residual_component_structure_budget_weight = _as_float(
        induction_result.get("raw_residual_component_structure_budget_weight", 0.0)
    )
    induction_raw_residual_hit_memory_budget_weight = _as_float(
        induction_result.get("raw_residual_hit_memory_budget_weight", 0.0)
    )
    induction_raw_residual_miss_memory_budget_weight = _as_float(
        induction_result.get("raw_residual_miss_memory_budget_weight", 0.0)
    )
    induction_structure_db_update_request_count = _as_int(induction_result.get("structure_db_update_request_count", 0))
    induction_structure_db_update_applied_count = _as_int(induction_result.get("structure_db_update_applied_count", 0))
    induction_structure_db_update_deduped_count = _as_int(induction_result.get("structure_db_update_deduped_count", 0))
    induction_applied_target_count = 0
    induction_applied_total_ev = 0.0
    induction_skipped_target_count = 0
    induction_skipped_target_total_ev = 0.0
    induction_skipped_cs_event_target_count = 0
    induction_applied_fast_ref_hit_merge_count = 0
    induction_applied_insert_log_suppressed_count = 0
    for target in induction_applied_targets:
        if not isinstance(target, dict):
            continue
        target_ev = _as_float(target.get("ev", 0.0))
        result_text = _as_str(target.get("result", ""))
        is_skipped = "skipped" in result_text.lower()
        if is_skipped:
            induction_skipped_target_count += 1
            induction_skipped_target_total_ev += target_ev
            if result_text == "skipped_cognitive_stitching_event_structure":
                induction_skipped_cs_event_target_count += 1
            continue
        if bool(target.get("fast_ref_hit_merge", False)):
            induction_applied_fast_ref_hit_merge_count += 1
        if bool(target.get("insert_log_suppressed", False)):
            induction_applied_insert_log_suppressed_count += 1
        induction_applied_target_count += 1
        induction_applied_total_ev += target_ev
    if induction_growth_target_apply_fast_ref_hit_merge_count <= 0:
        induction_growth_target_apply_fast_ref_hit_merge_count = induction_applied_fast_ref_hit_merge_count
    if induction_growth_target_apply_insert_log_suppressed_count <= 0:
        induction_growth_target_apply_insert_log_suppressed_count = induction_applied_insert_log_suppressed_count
    induction_applied_total_ev = round(induction_applied_total_ev, 8)
    induction_skipped_target_total_ev = round(induction_skipped_target_total_ev, 8)
    induction_applied_ev_ratio = round(
        float(induction_applied_total_ev) / max(0.000001, float(max(induction_structure_target_total_ev, 0.0))),
        8,
    )
    induction_applied_target_ratio = round(
        float(induction_applied_target_count) / max(1.0, float(max(1, induction_structure_target_count))),
        8,
    )

    # For plotting in a paper UI, keep the record flat.
    #
    # tick_index semantics (重要):
    # - tick_index is the *executed* tick index (monotonic, 0-based), derived from report.tick_counter when available.
    #   This keeps charts stable even when synthetic ticks (expectation feedback) are inserted between source ticks.
    # - dataset_tick_index preserves the original expanded-dataset index (dt.tick_index) for slicing/audit.
    #
    # Rationale:
    # - If we mix "dataset tick_index" for source ticks and "executed tick_counter" for synthetic ticks, X may go
    #   backwards (because executed includes synthetic steps but dataset index does not), producing long diagonal lines.
    tick_counter = _as_int(report.get("tick_counter", 0))
    dataset_tick_index = _as_int(dt.get("tick_index", -1), -1)
    source_dataset_tick_index = _as_int(dt.get("source_dataset_tick_index", dataset_tick_index), dataset_tick_index)
    executed_tick_index = max(0, tick_counter - 1) if tick_counter > 0 else _as_int(dt.get("tick_index", 0))
    record: dict[str, Any] = {
        "schema_version": MetricsSchema().version,
        # identifiers
        "tick_index": int(executed_tick_index),
        "trace_id": trace_id,
        "tick_id": tick_id,
        "started_at_ms": _as_int(report.get("started_at", 0)),
        "finished_at_ms": _as_int(report.get("finished_at", 0)),
        # dataset slicing fields (optional)
        "dataset_tick_index": int(dataset_tick_index),
        "dataset_id": _as_str(dt.get("dataset_id", "")),
        "episode_id": _as_str(dt.get("episode_id", "")),
        "episode_repeat_index": _as_int(dt.get("episode_repeat_index", 0)),
        "tick_in_episode_index": _as_int(dt.get("tick_in_episode_index", 0)),
        "tags": _as_list(dt.get("tags", [])),
        "tick_source": _as_str(dt.get("tick_source", "dataset")) or "dataset",
        "synthetic_tick": bool(dt.get("synthetic_tick", False)),
        "expectation_contract_id": _as_str(dt.get("expectation_contract_id", "")),
        "expectation_contract_outcome": _as_str(dt.get("expectation_contract_outcome", "")),
        "source_dataset_tick_index": int(source_dataset_tick_index),
        # input
        "input_is_empty": bool(input_is_empty),
        "input_len": len(input_text or ""),
        "input_text_preview": (input_text or "")[:80],
        "input_queue_tick_text_preview": (input_queue_tick_text or "")[:80],
        "input_queue_submitted_text_preview": (input_queue_submitted_text or "")[:80],
        "input_queue_source_text_preview": (input_queue_source_text or "")[:80],
        "input_queue_queued_from_new_input_count": int(input_queue_queued_from_new_input_count),
        "input_queue_pending_count_before_enqueue": int(input_queue_pending_count_before_enqueue),
        "input_queue_pending_count_before_dequeue": int(input_queue_pending_count_before_dequeue),
        "input_queue_pending_count_after_dequeue": int(input_queue_pending_count_after_dequeue),
        "input_queue_tick_submitted_mismatch_count": 1 if input_queue_tick_submitted_mismatch else 0,
        "input_queue_deferred_chunk_consumed_count": 1 if input_queue_deferred_chunk_consumed else 0,
        # text sensor echo diagnostics (important for long-run budget)
        "sensor_echo_pool_size": _as_int(sensor.get("echo_pool_size", 0)),
        "sensor_echo_current_round": _as_int(sensor.get("echo_current_round", 0)),
        "sensor_feature_sa_count": _as_int(sensor.get("feature_sa_count", 0)),
        "sensor_attribute_sa_count": _as_int(sensor.get("attribute_sa_count", 0)),
        "sensor_attribute_sa_per_feature_ratio": round(
            float(_as_int(sensor.get("attribute_sa_count", 0))) / max(1.0, float(_as_int(sensor.get("feature_sa_count", 0)))),
            8,
        ),
        "sensor_csa_bundle_count": _as_int(sensor.get("csa_bundle_count", 0)),
        "sensor_echo_frames_used_count": len(_as_list(sensor.get("echo_frames_used"))),
        # stimulus packet sizes (external + internal merge)
        "external_sa_count": external_sa_count,
        "internal_sa_count": internal_sa_count,
        "internal_csa_count": internal_csa_count,
        "internal_flat_token_count": internal_flat_token_count,
        "internal_attribute_count": int(len(internal_attribute_rows)),
        "internal_numeric_attribute_count": int(internal_numeric_attribute_count),
        "internal_time_like_attribute_count": int(internal_time_like_attribute_count),
        "internal_cfs_attribute_count": int(internal_cfs_attribute_count),
        "internal_cfs_pressure_family_attribute_count": int(internal_cfs_pressure_family_attribute_count),
        "internal_cfs_expectation_family_attribute_count": int(internal_cfs_expectation_family_attribute_count),
        "internal_reward_signal_attribute_count": int(internal_reward_signal_attribute_count),
        "internal_punish_signal_attribute_count": int(internal_punish_signal_attribute_count),
        "internal_teacher_reward_signal_attribute_count": int(internal_teacher_reward_signal_attribute_count),
        "internal_teacher_punish_signal_attribute_count": int(internal_teacher_punish_signal_attribute_count),
        "internal_total_er": _as_float(internal_stimulus.get("total_er", 0.0)),
        "internal_total_ev": _as_float(internal_stimulus.get("total_ev", 0.0)),
        "internal_to_external_sa_ratio": internal_to_external_sa_ratio,
        "internal_minus_external_sa_count": int(internal_sa_count - external_sa_count),
        "merged_flat_token_count": _as_int(merged_stimulus.get("flat_token_count", len(_as_list(merged_stimulus.get("flat_tokens", []))))),
        "cache_input_flat_token_count": _as_int(cache_input_pkt.get("flat_token_count", len(_as_list(cache_input_pkt.get("flat_tokens", []))))),
        "cache_residual_flat_token_count": _as_int(cache_residual_pkt.get("flat_token_count", len(_as_list(cache_residual_pkt.get("flat_tokens", []))))),
        "landed_flat_token_count": _as_int(landed_pkt.get("flat_token_count", len(_as_list(landed_pkt.get("flat_tokens", []))))),
        "cache_priority_consumed_er": _as_float(cache_priority_summary.get("consumed_er", 0.0)),
        "cache_priority_consumed_ev": _as_float(cache_priority_summary.get("consumed_ev", 0.0)),
        "cache_priority_cut_exact_fast_path_hit_count": _as_int(cache_priority_cut_metrics.get("maximum_common_part_exact_fast_path_hit_count", 0)),
        "cache_priority_cut_full_inclusion_fast_path_hit_count": _as_int(cache_priority_cut_metrics.get("maximum_common_part_full_inclusion_fast_path_hit_count", 0)),
        "cache_priority_cut_single_group_fast_path_hit_count": _as_int(cache_priority_cut_metrics.get("maximum_common_part_single_group_fast_path_hit_count", 0)),
        "cache_priority_cut_ordered_subsequence_fast_path_hit_count": _as_int(cache_priority_cut_metrics.get("maximum_common_group_ordered_subsequence_fast_path_hit_count", 0)),
        "cache_priority_cut_cache_hit_count": _as_int(cache_priority_cut_metrics.get("maximum_common_part_cache_hit_count", 0)),
        "cache_priority_cut_cache_zero_copy_hit_count": _as_int(cache_priority_cut_metrics.get("maximum_common_part_cache_zero_copy_hit_count", 0)),
        "cache_priority_cut_cache_store_count": _as_int(cache_priority_cut_metrics.get("maximum_common_part_cache_store_count", 0)),
        "cache_priority_cut_cache_deepcopy_count": _as_int(cache_priority_cut_metrics.get("maximum_common_part_cache_deepcopy_count", 0)),
        "cache_priority_cut_normalize_cache_hit_count": _as_int(cache_priority_cut_metrics.get("normalize_sequence_groups_cache_hit_count", 0)),
        "cache_priority_cut_normalize_cache_zero_copy_hit_count": _as_int(cache_priority_cut_metrics.get("normalize_sequence_groups_cache_zero_copy_hit_count", 0)),
        "cache_priority_cut_normalize_reusable_hit_count": _as_int(cache_priority_cut_metrics.get("normalize_sequence_groups_reusable_hit_count", 0)),
        "cache_priority_cut_normalize_reusable_group_count": _as_int(cache_priority_cut_metrics.get("normalize_sequence_groups_reusable_group_count", 0)),
        "cache_priority_cut_signature_fast_path_hit_count": _as_int(cache_priority_cut_metrics.get("sequence_groups_signature_fast_path_hit_count", 0)),
        "cache_priority_cut_empty_group_fast_path_hit_count": _as_int(cache_priority_cut_metrics.get("empty_group_from_normalized_template_fast_path_hit_count", 0)),
        "cache_priority_cut_full_group_fast_path_hit_count": _as_int(cache_priority_cut_metrics.get("full_group_from_normalized_template_fast_path_hit_count", 0)),
        "cache_priority_cut_normalized_unit_subset_group_fast_path_hit_count": _as_int(
            cache_priority_cut_metrics.get("normalized_unit_subset_group_fast_path_hit_count", 0)
        ),
        "cache_priority_cut_empty_common_part_reuse_normalized_groups_hit_count": _as_int(
            cache_priority_cut_metrics.get("empty_common_part_reuse_normalized_groups_hit_count", 0)
        ),
        "cache_priority_cut_reindex_fast_path_hit_count": _as_int(cache_priority_cut_metrics.get("reindex_reusable_group_fast_path_hit_count", 0)),
        "cache_priority_theoretical_match_fast_reject_count": _as_int(
            cache_priority_cut_metrics.get("priority_neutralization_theoretical_match_fast_reject_count", 0)
        ),
        # structure-level internal resolution (DARL + PARS) summary
        "internal_fragment_count": len(_as_list(structure_result.get("internal_stimulus_fragments"))),
        "internal_source_structure_count": _as_int(structure_result.get("cam_stub_count", internal_resolution_structure_count_total)),
        "internal_candidate_structure_count": internal_resolution_structure_count_total,
        "internal_selected_structure_count": internal_resolution_structure_count_selected,
        "internal_resolution_structure_count_total": internal_resolution_structure_count_total,
        "internal_resolution_structure_count_selected": internal_resolution_structure_count_selected,
        "internal_resolution_structure_count_dropped": internal_resolution_structure_count_dropped,
        "internal_resolution_max_structures_per_tick": _as_int(internal_resolution.get("max_structures_per_tick", 0)),
        # Compatibility aliases:
        # the current implementation is unit-based, but some legacy frontend charts still
        # read historical `*_sa_count` / `*_budget_sa_cap` keys.
        "internal_resolution_budget_sa_cap": _as_int(internal_resolution.get("detail_budget", 0)),
        "internal_resolution_detail_budget": _as_int(internal_resolution.get("detail_budget", 0)),
        "internal_resolution_detail_budget_base": _as_int(internal_resolution.get("detail_budget_base", 0)),
        "internal_resolution_detail_budget_adr_gain": _as_int(internal_resolution.get("detail_budget_adr_gain", 0)),
        "internal_resolution_raw_sa_count": _as_int(internal_resolution.get("raw_unit_count", 0)),
        "internal_resolution_raw_unit_count": _as_int(internal_resolution.get("raw_unit_count", 0)),
        "internal_resolution_raw_unit_count_total": _as_int(internal_resolution.get("raw_unit_count_total", internal_resolution.get("raw_unit_count", 0))),
        "internal_resolution_raw_unit_count_total_candidates": _as_int(internal_resolution.get("raw_unit_count_total_candidates", internal_resolution.get("raw_unit_count", 0))),
        "internal_resolution_selected_sa_count": _as_int(internal_resolution.get("selected_unit_count", 0)),
        "internal_resolution_selected_unit_count": _as_int(internal_resolution.get("selected_unit_count", 0)),
        "internal_resolution_rich_candidate_count": _as_int(internal_resolution.get("rich_candidate_count", 0)),
        "internal_resolution_rich_selected_count": _as_int(internal_resolution.get("rich_selected_count", 0)),
        "internal_resolution_runtime_priority_structure_count_total_candidates": _as_int(
            internal_resolution.get("runtime_priority_structure_count_total_candidates", 0)
        ),
        "internal_resolution_runtime_priority_structure_count": _as_int(
            internal_resolution.get("runtime_priority_structure_count", 0)
        ),
        "internal_resolution_runtime_priority_family_match_total_candidates": _as_int(
            internal_resolution.get("runtime_priority_family_match_total_candidates", 0)
        ),
        "internal_resolution_runtime_priority_family_match_total": _as_int(
            internal_resolution.get("runtime_priority_family_match_total", 0)
        ),
        "internal_resolution_runtime_family_bonus_total": _as_float(
            internal_resolution.get("runtime_family_bonus_total", 0.0)
        ),
        "internal_resolution_selected_attribute_unit_count": _as_int(
            internal_resolution.get("selected_attribute_unit_count", 0)
        ),
        "internal_resolution_selected_priority_attribute_unit_count": _as_int(
            internal_resolution.get("selected_priority_attribute_unit_count", 0)
        ),
        "internal_resolution_rescued_priority_attribute_unit_count": _as_int(
            internal_resolution.get("rescued_priority_attribute_unit_count", 0)
        ),
        "internal_cam_runtime_priority_projection_enabled": int(bool(cam_runtime_priority_projection.get("enabled", False))),
        "internal_cam_runtime_priority_projection_candidate_count": _as_int(
            cam_runtime_priority_projection.get("candidate_count", 0)
        ),
        "internal_cam_runtime_priority_projection_fragment_count": _as_int(
            cam_runtime_priority_projection.get("fragment_count", 0)
        ),
        "internal_cam_runtime_priority_projection_family_count": _as_int(
            cam_runtime_priority_projection.get("projected_family_count", 0)
        ),
        "internal_cam_runtime_priority_projection_unit_count": _as_int(
            cam_runtime_priority_projection.get("projected_unit_count", 0)
        ),
        "internal_cam_runtime_priority_projection_ratio": _as_float(
            cam_runtime_priority_projection.get("projection_ratio", 0.0)
        ),
        "internal_cam_runtime_priority_projection_require_unrepresented": int(
            bool(cam_runtime_priority_projection.get("require_unrepresented", False))
        ),
        # pool summary
        "pool_active_item_count": pool_active_item_count,
        "pool_high_cp_item_count": _as_int(snapshot_summary.get("high_cp_item_count", 0)),
        "pool_total_er": pool_total_er,
        "pool_total_ev": pool_total_ev,
        "pool_total_energy": pool_total_energy,
        "pool_total_cp": pool_total_cp,
        "pool_ev_to_er_ratio": round(float(pool_total_ev) / max(0.000001, float(pool_total_er)), 8),
        "pool_er_top5": pool_er_top5,
        "pool_ev_top5": pool_ev_top5,
        "pool_cp_top5": pool_cp_top5,
        "pool_er_structure_top5": pool_er_structure_top5,
        "pool_ev_structure_top5": pool_ev_structure_top5,
        "pool_cp_structure_top5": pool_cp_structure_top5,
        "pool_er_structure_top5_same_as_top5": int(pool_er_structure_top5_same_as_top5),
        "pool_ev_structure_top5_same_as_top5": int(pool_ev_structure_top5_same_as_top5),
        "pool_cp_structure_top5_same_as_top5": int(pool_cp_structure_top5_same_as_top5),
        "pool_er_top5_count": len(pool_er_top5),
        "pool_ev_top5_count": len(pool_ev_top5),
        "pool_cp_top5_count": len(pool_cp_top5),
        "pool_er_atomic_feature_sa_top5_count": sum(1 for row in pool_er_top5 if _is_atomic_feature_sa_preview(row)),
        "pool_ev_atomic_feature_sa_top5_count": sum(1 for row in pool_ev_top5 if _is_atomic_feature_sa_preview(row)),
        "pool_cp_atomic_feature_sa_top5_count": sum(1 for row in pool_cp_top5 if _is_atomic_feature_sa_preview(row)),
        "pool_er_structure_top5_count": len(pool_er_top5) if pool_er_structure_top5_same_as_top5 else len(pool_er_structure_top5),
        "pool_ev_structure_top5_count": len(pool_ev_top5) if pool_ev_structure_top5_same_as_top5 else len(pool_ev_structure_top5),
        "pool_cp_structure_top5_count": len(pool_cp_top5) if pool_cp_structure_top5_same_as_top5 else len(pool_cp_structure_top5),
        "pool_er_top5_text": _pool_energy_top_text(pool_er_top5, energy_key="er"),
        "pool_ev_top5_text": _pool_energy_top_text(pool_ev_top5, energy_key="ev"),
        "pool_cp_top5_text": _pool_energy_top_text(pool_cp_top5, energy_key="cp"),
        "pool_er_structure_top5_text": _pool_energy_top_text(pool_er_structure_top5, energy_key="er"),
        "pool_ev_structure_top5_text": _pool_energy_top_text(pool_ev_structure_top5, energy_key="ev"),
        "pool_cp_structure_top5_text": _pool_energy_top_text(pool_cp_structure_top5, energy_key="cp"),
        "pool_runtime_resolution_degraded_item_count": pool_runtime_resolution_degraded_item_count,
        "pool_runtime_resolution_active_component_count": pool_runtime_resolution_active_component_count,
        "pool_runtime_resolution_dropped_component_count": pool_runtime_resolution_dropped_component_count,
        "pool_er_top1_display": _as_str(pool_er_top5[0].get("display", "")) if pool_er_top5 else "",
        "pool_ev_top1_display": _as_str(pool_ev_top5[0].get("display", "")) if pool_ev_top5 else "",
        "pool_cp_top1_display": _as_str(pool_cp_top5[0].get("display", "")) if pool_cp_top5 else "",
        "pool_er_top1_ref_object_id": _as_str(pool_er_top5[0].get("ref_object_id", "")) if pool_er_top5 else "",
        "pool_ev_top1_ref_object_id": _as_str(pool_ev_top5[0].get("ref_object_id", "")) if pool_ev_top5 else "",
        "pool_cp_top1_ref_object_id": _as_str(pool_cp_top5[0].get("ref_object_id", "")) if pool_cp_top5 else "",
        "pool_er_top1_er": _as_float(pool_er_top5[0].get("er", 0.0)) if pool_er_top5 else 0.0,
        "pool_er_top1_ev": _as_float(pool_er_top5[0].get("ev", 0.0)) if pool_er_top5 else 0.0,
        "pool_ev_top1_er": _as_float(pool_ev_top5[0].get("er", 0.0)) if pool_ev_top5 else 0.0,
        "pool_ev_top1_ev": _as_float(pool_ev_top5[0].get("ev", 0.0)) if pool_ev_top5 else 0.0,
        "pool_cp_top1_er": _as_float(pool_cp_top5[0].get("er", 0.0)) if pool_cp_top5 else 0.0,
        "pool_cp_top1_ev": _as_float(pool_cp_top5[0].get("ev", 0.0)) if pool_cp_top5 else 0.0,
        "pool_cp_top1_cp": _as_float(pool_cp_top5[0].get("cp", 0.0)) if pool_cp_top5 else 0.0,
        "pool_contextual_item_count": pool_contextual_item_count,
        "pool_explicit_context_item_count": pool_explicit_context_item_count,
        "pool_multi_context_item_count": pool_multi_context_item_count,
        "pool_context_path_depth_mean": _as_float(snapshot_summary.get("context_path_depth_mean", 0.0)),
        "pool_explicit_context_path_depth_mean": _as_float(snapshot_summary.get("explicit_context_path_depth_mean", 0.0)),
        "pool_residual_origin_item_count": pool_residual_origin_item_count,
        "pool_contextual_item_ratio": pool_contextual_item_ratio,
        "pool_explicit_context_item_ratio": pool_explicit_context_item_ratio,
        "pool_multi_context_item_ratio": pool_multi_context_item_ratio,
        "pool_residual_origin_item_ratio": pool_residual_origin_item_ratio,
        "energy_concentration": pool_energy_concentration,
        "effective_peak_count": pool_effective_peak_count,
        "complexity_score": pool_complexity_score,
        "core_energy_concentration": pool_core_energy_concentration,
        "core_effective_peak_count": pool_core_effective_peak_count,
        "core_complexity_score": pool_core_complexity_score,
        "pool_energy_injection_fatigue_enabled": int(bool(injection_fatigue.get("enabled", False))),
        "pool_energy_injection_event_count": _as_int(injection_tick.get("event_count", 0)),
        "pool_energy_injection_item_count": _as_int(injection_tick.get("item_count", 0)),
        "pool_energy_injection_side_hit_count": _as_int(injection_tick.get("side_hit_count", 0)),
        "pool_energy_injection_requested_er": _as_float(injection_tick.get("requested_er", 0.0)),
        "pool_energy_injection_requested_ev": _as_float(injection_tick.get("requested_ev", 0.0)),
        "pool_energy_injection_applied_er": _as_float(injection_tick.get("applied_er", 0.0)),
        "pool_energy_injection_applied_ev": _as_float(injection_tick.get("applied_ev", 0.0)),
        "pool_energy_injection_throttled_er": _as_float(injection_tick.get("throttled_er", 0.0)),
        "pool_energy_injection_throttled_ev": _as_float(injection_tick.get("throttled_ev", 0.0)),
        "pool_energy_injection_throttle_ratio_er": _as_float(injection_tick.get("throttle_ratio_er", 0.0)),
        "pool_energy_injection_throttle_ratio_ev": _as_float(injection_tick.get("throttle_ratio_ev", 0.0)),
        "pool_energy_injection_throttle_ratio_total": _as_float(injection_tick.get("throttle_ratio_total", 0.0)),
        "pool_energy_injection_min_scale": _as_float(injection_tick.get("min_scale", 1.0)),
        "pool_energy_injection_total_event_count": _as_int(injection_total.get("event_count", 0)),
        "pool_energy_injection_total_side_hit_count": _as_int(injection_total.get("side_hit_count", 0)),
        "pool_energy_injection_total_throttle_ratio": _as_float(injection_total.get("throttle_ratio_total", 0.0)),
        # attention summary
        # cam_item_count: use the canonical AttentionFilter report fields
        # (legacy compat: tolerate older keys if present).
        "cam_item_count": _as_int(
            cam_snapshot_summary.get(
                "active_item_count",
                attention.get(
                    "cam_item_count",
                    attention.get(
                        "cam_count",
                        attention.get("top_item_count", attention.get("memory_item_count", len(_as_list(attention.get("top_items"))))),
                    ),
                ),
            )
        ),
        "attention_cam_item_count": _as_int(
            cam_snapshot_summary.get(
                "active_item_count",
                attention.get(
                    "cam_item_count",
                    attention.get(
                        "cam_count",
                        attention.get("top_item_count", attention.get("memory_item_count", len(_as_list(attention.get("top_items"))))),
                    ),
                ),
            )
        ),
        "attention_memory_item_count": _as_int(attention.get("memory_item_count", 0)),
        "attention_consumed_total_energy": _as_float(attention.get("consumed_total_energy", 0.0)),
        "attention_base_memory_total_energy": _as_float(attention.get("base_memory_total_energy", 0.0)),
        "attention_final_memory_total_energy": _as_float(
            attention.get(
                "attention_energy_resource",
                {},
            ).get("filtered_total_energy", attention.get("memory_total_er", 0.0) + attention.get("memory_total_ev", 0.0))
            if isinstance(attention.get("attention_energy_resource", {}), dict)
            else attention.get("memory_total_er", 0.0) + attention.get("memory_total_ev", 0.0)
        ),
        "attention_energy_budget": _as_float(
            attention_resource.get("budget", 0.0)
        ),
        "attention_energy_budget_enabled": _as_int(attention_resource.get("enabled", False)),
        "attention_energy_filter_applied": _as_int(attention_resource.get("filter_applied", False)),
        "attention_energy_budget_base": _as_float(
            attention_resource.get(
                "base",
                attention_modulation.get("attention_energy_budget", attention_modulation.get("attention_energy_budget_base", 0.0)),
            )
        ),
        "attention_energy_budget_min": _as_float(
            attention_resource.get("min", attention_modulation.get("attention_energy_budget_min", 0.0))
        ),
        "attention_energy_budget_max": _as_float(
            attention_resource.get("max", attention_modulation.get("attention_energy_budget_max", 0.0))
        ),
        "attention_mod_attention_energy_budget": _as_float(
            attention_modulation.get(
                "attention_energy_budget",
                attention_modulation.get("attention_energy_budget_base", attention_resource.get("budget", 0.0)),
            )
        ),
        "attention_gross_gain_energy_applied": _as_float(
            attention.get("attention_gross_gain_energy_applied", attention_resource.get("gross_gain_energy_applied", 0.0))
        ),
        "attention_gain_weight_total": _as_float(attention_resource.get("gain_weight_total", 0.0)),
        "attention_gain_floor": _as_float(attention_resource.get("gain_floor", 0.0)),
        "attention_suppression_floor": _as_float(attention_resource.get("suppression_floor", 0.0)),
        "attention_suppression_min_ratio": _as_float(attention_resource.get("suppression_min_ratio", 0.0)),
        "attention_gain_budget_applied": _as_float(attention.get("attention_gain_budget_applied", 0.0)),
        "attention_suppressed_total_energy": _as_float(attention.get("attention_suppressed_total_energy", 0.0)),
        "attention_net_delta_energy": _as_float(attention.get("attention_net_delta_energy", 0.0)),
        "attention_gain_possible": _as_int(attention_resource.get("gain_weight_total", 0.0) > 1e-12),
        "attention_unallocated_budget": round(
            max(
                0.0,
                _as_float(attention_resource.get("budget", 0.0))
                - _as_float(attention.get("attention_gain_budget_applied", 0.0)),
            ),
            8,
        ),
        "attention_cam_item_cap": _as_int(attention.get("cam_item_cap", attention.get("top_n", 0))),
        "attention_mod_min_cam_items": _as_int(attention.get("min_cam_items", attention_modulation.get("min_cam_items", 0))),
        "attention_mod_focus_boost_weight": _as_float(
            attention_effective_priority_weights.get(
                "focus_boost_weight",
                attention_modulation.get("focus_boost_weight", 0.0),
            )
        ),
        "attention_mod_min_total_energy": _as_float(
            attention_effective_priority_weights.get(
                "min_total_energy",
                attention_modulation.get("min_total_energy", 0.0),
            )
        ),
        "attention_mod_priority_weight_total_energy": _as_float(
            attention_effective_priority_weights.get(
                "priority_weight_total_energy",
                attention_modulation.get("priority_weight_total_energy", 0.0),
            )
        ),
        "attention_mod_priority_weight_cp_abs": _as_float(
            attention_effective_priority_weights.get(
                "priority_weight_cp_abs",
                attention_modulation.get("priority_weight_cp_abs", 0.0),
            )
        ),
        "attention_mod_priority_weight_salience": _as_float(
            attention_effective_priority_weights.get(
                "priority_weight_salience",
                attention_modulation.get("priority_weight_salience", 0.0),
            )
        ),
        "attention_mod_priority_weight_fatigue": _as_float(
            attention_effective_priority_weights.get(
                "priority_weight_fatigue",
                attention_modulation.get("priority_weight_fatigue", 0.0),
            )
        ),
        "attention_sa_count_pref_peak": _as_float(_as_dict(attention.get("sa_count_preference")).get("peak", 0.0)),
        "attention_sa_count_pref_no_reward_below_or_equal": _as_float(
            _as_dict(attention.get("sa_count_preference")).get("no_reward_below_or_equal", 0.0)
        ),
        "attention_sa_count_pref_no_reward_above_or_equal": _as_float(
            _as_dict(attention.get("sa_count_preference")).get("no_reward_above_or_equal", 0.0)
        ),
        "attention_sa_count_pref_bonus_cap": _as_float(
            _as_dict(attention.get("sa_count_preference")).get("bonus_cap", 0.0)
        ),
        "attention_sa_count_pref_penalty_cap": _as_float(
            _as_dict(attention.get("sa_count_preference")).get("penalty_cap", 0.0)
        ),
        "attention_sa_count_pref_min_scale": _as_float(
            _as_dict(attention.get("sa_count_preference")).get("min_scale", 0.0)
        ),
        "attention_sa_count_pref_selected_bonus_total": _as_float(
            _as_dict(attention.get("sa_count_preference")).get("selected_bonus_total", 0.0)
        ),
        "attention_sa_count_pref_selected_scale_mean": _as_float(
            _as_dict(attention.get("sa_count_preference")).get("selected_scale_mean", 0.0)
        ),
        "attention_sa_count_pref_selected_token_count_mean": _as_float(
            _as_dict(attention.get("sa_count_preference")).get("selected_token_count_mean", 0.0)
        ),
        "attention_mod_priority_weight_recency_gain": _as_float(
            attention_effective_priority_weights.get(
                "priority_weight_recency_gain",
                attention_modulation.get("priority_weight_recency_gain", 0.0),
            )
        ),
        "attention_cutoff_keep_ratio": _as_float(attention_dynamic_cutoff.get("keep_ratio", 0.0)),
        "attention_cutoff_score_entropy": _as_float(attention_dynamic_cutoff.get("score_entropy", 0.0)),
        "attention_cutoff_score_concentration": _as_float(attention_dynamic_cutoff.get("score_concentration", 0.0)),
        "attention_state_pool_candidate_count": _as_int(attention.get("state_pool_candidate_count", 0)),
        "attention_skipped_memory_item_count": _as_int(attention.get("skipped_memory_item_count", 0)),
        "attention_reward_action_selected_count": _as_int(attention.get("reward_action_selected_count", 0)),
        "attention_reward_action_selected_bonus_total": _as_float(attention.get("reward_action_selected_bonus_total", 0.0)),
        "attention_structure_carrier_selected_count": _as_int(attention.get("reward_action_structure_carrier_selected_count", 0)),
        "attention_standalone_special_selected_count": _as_int(attention.get("reward_action_standalone_special_selected_count", 0)),
        "attention_repeat_penalty_selected_count": _as_int(attention.get("repeat_attention_penalty_selected_count", 0)),
        "attention_repeat_penalty_total": _as_float(attention.get("repeat_attention_penalty_total", 0.0)),
        "attention_top5": attention_top5,
        "attention_top5_count": len(attention_top5),
        "attention_top5_text": _pool_energy_top_text(attention_top5, energy_key="er"),
        "attention_top1_display": _as_str(attention_top5[0].get("display", "")) if attention_top5 else "",
        "attention_top1_about": _as_str(attention_top5[0].get("about", "")) if attention_top5 else "",
        "attention_top1_priority": _as_float(attention_top5[0].get("attention_priority", 0.0)) if attention_top5 else 0.0,
        # retrieval rounds
        "structure_round_count": _as_int(structure_result.get("round_count", 0)),
        "stimulus_round_count": _as_int(stimulus_result.get("round_count", 0)),
        "stimulus_new_structure_count": _as_int(stimulus_result.get("new_structure_count", 0)),
        "stimulus_local_child_candidate_count": _as_int(stimulus_perf_metrics.get("local_child_candidate_count", 0)),
        "stimulus_local_child_candidate_pruned_count": _as_int(stimulus_perf_metrics.get("local_child_candidate_pruned_count", 0)),
        "stimulus_best_match_candidate_count": _as_int(stimulus_perf_metrics.get("best_structure_match_candidate_count", 0)),
        "stimulus_best_match_pruned_count": _as_int(stimulus_perf_metrics.get("best_structure_match_pruned_count", 0)),
        "stimulus_best_match_common_part_count": _as_int(stimulus_perf_metrics.get("best_structure_match_common_part_count", 0)),
        "stimulus_best_match_strict_overlap_fast_reject_count": _as_int(
            stimulus_perf_metrics.get("best_structure_match_strict_overlap_fast_reject_count", 0)
        ),
        "stimulus_shadow_raw_residual_candidate_count": _as_int(stimulus_perf_metrics.get("shadow_raw_residual_candidate_count", 0)),
        "stimulus_shadow_raw_residual_candidate_pruned_count": _as_int(stimulus_perf_metrics.get("shadow_raw_residual_candidate_pruned_count", 0)),
        "stimulus_shadow_raw_residual_skipped_count": _as_int(stimulus_perf_metrics.get("shadow_raw_residual_skipped_count", 0)),
        "stimulus_shadow_raw_residual_common_part_count": _as_int(stimulus_perf_metrics.get("shadow_raw_residual_common_part_count", 0)),
        "stimulus_owner_local_residual_list_cache_hit_count": _as_int(stimulus_perf_metrics.get("owner_local_residual_list_cache_hit_count", 0)),
        "stimulus_owner_local_residual_index_build_count": _as_int(stimulus_perf_metrics.get("owner_local_residual_index_build_count", 0)),
        "stimulus_owner_local_residual_index_cache_hit_count": _as_int(stimulus_perf_metrics.get("owner_local_residual_index_cache_hit_count", 0)),
        "stimulus_owner_local_residual_shared_index_cache_hit_count": _as_int(stimulus_perf_metrics.get("owner_local_residual_shared_index_cache_hit_count", 0)),
        "stimulus_owner_local_residual_raw_signature_hit_count": _as_int(stimulus_perf_metrics.get("owner_local_residual_raw_signature_hit_count", 0)),
        "stimulus_owner_local_residual_common_signature_hit_count": _as_int(stimulus_perf_metrics.get("owner_local_residual_common_signature_hit_count", 0)),
        "stimulus_owner_local_residual_fuzzy_equivalent_call_count": _as_int(stimulus_perf_metrics.get("owner_local_residual_fuzzy_equivalent_call_count", 0)),
        "stimulus_owner_local_residual_fuzzy_equivalent_cache_hit_count": _as_int(stimulus_perf_metrics.get("owner_local_residual_fuzzy_equivalent_cache_hit_count", 0)),
        "stimulus_owner_local_residual_fuzzy_equivalent_signature_hit_count": _as_int(stimulus_perf_metrics.get("owner_local_residual_fuzzy_equivalent_signature_hit_count", 0)),
        "stimulus_owner_local_residual_fuzzy_equivalent_fast_reject_count": _as_int(stimulus_perf_metrics.get("owner_local_residual_fuzzy_equivalent_fast_reject_count", 0)),
        "stimulus_owner_local_residual_common_overlap_fast_reject_count": _as_int(stimulus_perf_metrics.get("owner_local_residual_common_overlap_fast_reject_count", 0)),
        "stimulus_owner_local_residual_fuzzy_unit_bucket_pruned_count": _as_int(stimulus_perf_metrics.get("owner_local_residual_fuzzy_unit_bucket_pruned_count", 0)),
        "stimulus_owner_local_residual_fuzzy_equivalent_cut_count": _as_int(stimulus_perf_metrics.get("owner_local_residual_fuzzy_equivalent_cut_count", 0)),
        "stimulus_owner_runtime_budget_selected_count": _as_int(stimulus_perf_metrics.get("owner_runtime_budget_selected_count", 0)),
        "stimulus_owner_runtime_budget_pruned_count": _as_int(stimulus_perf_metrics.get("owner_runtime_budget_pruned_count", 0)),
        "stimulus_cut_common_part_total_count": _as_int(stimulus_perf_metrics.get("best_structure_match_common_part_count", 0))
        + _as_int(stimulus_perf_metrics.get("shadow_raw_residual_common_part_count", 0)),
        "stimulus_cut_exact_fast_path_hit_count": _as_int(stimulus_perf_metrics.get("maximum_common_part_exact_fast_path_hit_count", 0)),
        "stimulus_cut_full_inclusion_fast_path_hit_count": _as_int(stimulus_perf_metrics.get("maximum_common_part_full_inclusion_fast_path_hit_count", 0)),
        "stimulus_cut_single_group_fast_path_hit_count": _as_int(stimulus_perf_metrics.get("maximum_common_part_single_group_fast_path_hit_count", 0)),
        "stimulus_cut_ordered_subsequence_fast_path_hit_count": _as_int(stimulus_perf_metrics.get("maximum_common_group_ordered_subsequence_fast_path_hit_count", 0)),
        "stimulus_cut_cache_hit_count": _as_int(stimulus_perf_metrics.get("maximum_common_part_cache_hit_count", 0)),
        "stimulus_cut_cache_zero_copy_hit_count": _as_int(stimulus_perf_metrics.get("maximum_common_part_cache_zero_copy_hit_count", 0)),
        "stimulus_cut_cache_store_count": _as_int(stimulus_perf_metrics.get("maximum_common_part_cache_store_count", 0)),
        "stimulus_cut_cache_deepcopy_count": _as_int(stimulus_perf_metrics.get("maximum_common_part_cache_deepcopy_count", 0)),
        "stimulus_cut_normalize_cache_hit_count": _as_int(stimulus_perf_metrics.get("normalize_sequence_groups_cache_hit_count", 0)),
        "stimulus_cut_normalize_cache_zero_copy_hit_count": _as_int(stimulus_perf_metrics.get("normalize_sequence_groups_cache_zero_copy_hit_count", 0)),
        "stimulus_cut_normalize_reusable_hit_count": _as_int(stimulus_perf_metrics.get("normalize_sequence_groups_reusable_hit_count", 0)),
        "stimulus_cut_normalize_reusable_group_count": _as_int(stimulus_perf_metrics.get("normalize_sequence_groups_reusable_group_count", 0)),
        "stimulus_cut_signature_fast_path_hit_count": _as_int(stimulus_perf_metrics.get("sequence_groups_signature_fast_path_hit_count", 0)),
        "stimulus_cut_empty_group_fast_path_hit_count": _as_int(stimulus_perf_metrics.get("empty_group_from_normalized_template_fast_path_hit_count", 0)),
        "stimulus_cut_full_group_fast_path_hit_count": _as_int(stimulus_perf_metrics.get("full_group_from_normalized_template_fast_path_hit_count", 0)),
        "stimulus_cut_normalized_unit_subset_group_fast_path_hit_count": _as_int(
            stimulus_perf_metrics.get("normalized_unit_subset_group_fast_path_hit_count", 0)
        ),
        "stimulus_cut_empty_common_part_reuse_normalized_groups_hit_count": _as_int(
            stimulus_perf_metrics.get("empty_common_part_reuse_normalized_groups_hit_count", 0)
        ),
        "stimulus_cut_reindex_fast_path_hit_count": _as_int(stimulus_perf_metrics.get("reindex_reusable_group_fast_path_hit_count", 0)),
        "stimulus_anchor_atomic_lookup_index_candidate_count": _as_int(stimulus_perf_metrics.get("anchor_atomic_lookup_index_candidate_count", 0)),
        "stimulus_anchor_atomic_lookup_index_hit_count": _as_int(stimulus_perf_metrics.get("anchor_atomic_lookup_index_hit_count", 0)),
        "stimulus_anchor_atomic_lookup_index_miss_count": _as_int(stimulus_perf_metrics.get("anchor_atomic_lookup_index_miss_count", 0)),
        "stimulus_anchor_atomic_lookup_full_scan_count": _as_int(stimulus_perf_metrics.get("anchor_atomic_lookup_full_scan_count", 0)),
        "stimulus_anchor_owner_residual_presence_cache_hit_count": _as_int(
            stimulus_perf_metrics.get("anchor_owner_residual_presence_cache_hit_count", 0)
        ),
        "stimulus_anchor_owner_residual_presence_shared_cache_hit_count": _as_int(
            stimulus_perf_metrics.get("anchor_owner_residual_presence_shared_cache_hit_count", 0)
        ),
        "stimulus_anchor_owner_residual_presence_shared_cache_store_count": _as_int(
            stimulus_perf_metrics.get("anchor_owner_residual_presence_shared_cache_store_count", 0)
        ),
        "stimulus_anchor_owner_residual_presence_scan_count": _as_int(
            stimulus_perf_metrics.get("anchor_owner_residual_presence_scan_count", 0)
        ),
        "stimulus_early_stop_triggered": int(bool(stimulus_early_stop.get("triggered", False))),
        "stimulus_early_stop_object_projection_dominance_triggered": int(
            stimulus_early_stop_reason.startswith("object_projection_dominates_remaining")
            or _as_int(stimulus_perf_metrics.get("object_projection_dominance_early_stop_triggered", 0)) > 0
        ),
        "stimulus_early_stop_object_projection_dominance_completed_rounds": _as_int(
            stimulus_perf_metrics.get("object_projection_dominance_early_stop_completed_rounds", 0)
        ),
        "stimulus_early_stop_object_projection_dominance_ratio": _as_float(
            stimulus_perf_metrics.get(
                "object_projection_dominance_early_stop_ratio",
                stimulus_early_stop.get("object_projection_ratio_at_stop", 0.0),
            )
        ),
        "stimulus_early_stop_object_projection_transfer_guard_blocked_count": _as_int(
            stimulus_perf_metrics.get(
                "object_projection_dominance_transfer_guard_blocked_count",
                stimulus_early_stop.get("object_projection_transfer_guard_blocked_count", 0),
            )
        ),
        "stimulus_early_stop_object_projection_transfer_total_at_stop": _as_float(
            stimulus_perf_metrics.get(
                "object_projection_dominance_early_stop_transfer_total",
                stimulus_early_stop.get("transfer_total_at_stop", 0.0),
            )
        ),
        "stimulus_early_stop_object_projection_transfer_ratio_at_stop": _as_float(
            stimulus_perf_metrics.get(
                "object_projection_dominance_early_stop_transfer_ratio",
                stimulus_early_stop.get("transfer_ratio_at_stop", 0.0),
            )
        ),
        "stimulus_early_stop_object_projection_total_at_stop": _as_float(
            stimulus_perf_metrics.get(
                "object_projection_dominance_early_stop_projection_total",
                stimulus_early_stop.get("object_projection_total_at_stop", 0.0),
            )
        ),
        "stimulus_early_stop_remaining_total_at_stop": _as_float(
            stimulus_perf_metrics.get(
                "object_projection_dominance_early_stop_remaining_total",
                stimulus_early_stop.get("remaining_total_at_stop", 0.0),
            )
        ),
        "structure_fuzzy_metadata_cache_hit_count": _as_int(
            structure_result_metrics.get("structure_fuzzy_metadata_cache_hit_count", 0)
        ),
        "structure_fuzzy_metadata_cache_store_count": _as_int(
            structure_result_metrics.get("structure_fuzzy_metadata_cache_store_count", 0)
        ),
        "induction_cut_exact_fast_path_hit_count": _as_int(induction_result_metrics.get("maximum_common_part_exact_fast_path_hit_count", 0)),
        "induction_cut_full_inclusion_fast_path_hit_count": _as_int(induction_result_metrics.get("maximum_common_part_full_inclusion_fast_path_hit_count", 0)),
        "induction_cut_single_group_fast_path_hit_count": _as_int(induction_result_metrics.get("maximum_common_part_single_group_fast_path_hit_count", 0)),
        "induction_cut_ordered_subsequence_fast_path_hit_count": _as_int(induction_result_metrics.get("maximum_common_group_ordered_subsequence_fast_path_hit_count", 0)),
        "induction_cut_cache_hit_count": _as_int(induction_result_metrics.get("maximum_common_part_cache_hit_count", 0)),
        "induction_cut_cache_zero_copy_hit_count": _as_int(induction_result_metrics.get("maximum_common_part_cache_zero_copy_hit_count", 0)),
        "induction_cut_cache_store_count": _as_int(induction_result_metrics.get("maximum_common_part_cache_store_count", 0)),
        "induction_cut_cache_deepcopy_count": _as_int(induction_result_metrics.get("maximum_common_part_cache_deepcopy_count", 0)),
        "induction_cut_normalize_cache_hit_count": _as_int(induction_result_metrics.get("normalize_sequence_groups_cache_hit_count", 0)),
        "induction_cut_normalize_cache_zero_copy_hit_count": _as_int(induction_result_metrics.get("normalize_sequence_groups_cache_zero_copy_hit_count", 0)),
        "induction_cut_normalize_reusable_hit_count": _as_int(induction_result_metrics.get("normalize_sequence_groups_reusable_hit_count", 0)),
        "induction_cut_normalize_reusable_group_count": _as_int(induction_result_metrics.get("normalize_sequence_groups_reusable_group_count", 0)),
        "induction_cut_signature_fast_path_hit_count": _as_int(induction_result_metrics.get("sequence_groups_signature_fast_path_hit_count", 0)),
        "induction_cut_empty_group_fast_path_hit_count": _as_int(induction_result_metrics.get("empty_group_from_normalized_template_fast_path_hit_count", 0)),
        "induction_cut_full_group_fast_path_hit_count": _as_int(induction_result_metrics.get("full_group_from_normalized_template_fast_path_hit_count", 0)),
        "induction_cut_normalized_unit_subset_group_fast_path_hit_count": _as_int(
            induction_result_metrics.get("normalized_unit_subset_group_fast_path_hit_count", 0)
        ),
        "induction_cut_empty_common_part_reuse_normalized_groups_hit_count": _as_int(
            induction_result_metrics.get("empty_common_part_reuse_normalized_groups_hit_count", 0)
        ),
        "induction_cut_reindex_fast_path_hit_count": _as_int(induction_result_metrics.get("reindex_reusable_group_fast_path_hit_count", 0)),
        **stimulus_match_v2_metrics,
        **stimulus_shadow_memory_match_v2_metrics,
        **stimulus_transfer_metrics,
        **stimulus_object_projection_metrics,
        **structure_match_v2_metrics,
        **structure_round_path_metrics,
        # induction + MAP
        "induction_projection_mode_growth": induction_projection_mode_growth,
        "induction_projection_raw_target_count": induction_projection_raw_target_count,
        "induction_projection_projected_target_count": induction_projection_projected_target_count,
        "induction_growth_target_count": induction_growth_target_count,
        "induction_growth_identity_hit_count": induction_growth_identity_hit_count,
        "induction_growth_identity_created_count": induction_growth_identity_created_count,
        "induction_growth_identity_local_cache_hit_count": induction_growth_identity_local_cache_hit_count,
        "induction_growth_identity_shared_cache_hit_count": induction_growth_identity_shared_cache_hit_count,
        "induction_growth_identity_shared_cache_stale_count": induction_growth_identity_shared_cache_stale_count,
        "induction_growth_identity_create_exact_lookup_skipped_count": induction_growth_identity_create_exact_lookup_skipped_count,
        "induction_growth_persistence_batch_enabled": induction_growth_persistence_batch_enabled,
        "induction_growth_target_apply_ref_fast_merge_enabled": induction_growth_target_apply_ref_fast_merge_enabled,
        "induction_growth_target_apply_fast_ref_hit_merge_count": induction_growth_target_apply_fast_ref_hit_merge_count,
        "induction_growth_target_apply_insert_log_enabled": induction_growth_target_apply_insert_log_enabled,
        "induction_growth_target_apply_insert_log_suppressed_count": induction_growth_target_apply_insert_log_suppressed_count,
        "induction_growth_identity_lookup_disabled_count": induction_growth_identity_lookup_disabled_count,
        "induction_growth_runtime_only_count": induction_growth_runtime_only_count,
        "induction_growth_memory_candidate_count": induction_growth_memory_candidate_count,
        "induction_growth_memory_terminal_passthrough_count": induction_growth_memory_terminal_passthrough_count,
        "induction_growth_pruned_low_energy_count": induction_growth_pruned_low_energy_count,
        "induction_growth_failed_count": induction_growth_failed_count,
        "induction_growth_skipped_missing_source_count": induction_growth_skipped_missing_source_count,
        "induction_growth_skipped_missing_residual_count": induction_growth_skipped_missing_residual_count,
        "induction_growth_deduped_count": induction_growth_deduped_count,
        "induction_growth_total_delta_er": induction_growth_total_delta_er,
        "induction_growth_total_delta_ev": induction_growth_total_delta_ev,
        "induction_growth_source_component_er_total": induction_growth_source_component_er_total,
        "induction_growth_residual_component_ev_total": induction_growth_residual_component_ev_total,
        "induction_raw_residual_projection_profile_local_cache_hit_count": induction_raw_residual_projection_profile_local_cache_hit_count,
        "induction_raw_residual_projection_profile_shared_cache_hit_count": induction_raw_residual_projection_profile_shared_cache_hit_count,
        "induction_raw_residual_projection_profile_cache_store_count": induction_raw_residual_projection_profile_cache_store_count,
        "induction_raw_residual_exact_candidates_local_cache_hit_count": induction_raw_residual_exact_candidates_local_cache_hit_count,
        "induction_raw_residual_exact_candidates_shared_cache_hit_count": induction_raw_residual_exact_candidates_shared_cache_hit_count,
        "induction_raw_residual_exact_candidates_cache_store_count": induction_raw_residual_exact_candidates_cache_store_count,
        "induction_raw_residual_component_candidates_local_cache_hit_count": induction_raw_residual_component_candidates_local_cache_hit_count,
        "induction_raw_residual_component_candidates_shared_cache_hit_count": induction_raw_residual_component_candidates_shared_cache_hit_count,
        "induction_raw_residual_component_candidates_cache_store_count": induction_raw_residual_component_candidates_cache_store_count,
        "induction_full_inclusion_shared_cache_hit_count": induction_full_inclusion_shared_cache_hit_count,
        "induction_full_inclusion_shared_cache_store_count": induction_full_inclusion_shared_cache_store_count,
        "induction_total_delta_er": induction_total_delta_er,
        "induction_total_delta_ev": induction_total_delta_ev,
        "induction_total_ev_consumed": induction_total_ev_consumed,
        "induction_propagated_budget_total_ev": induction_propagated_budget_total_ev,
        "induction_propagated_ev_total": induction_propagated_ev_total,
        "induction_ev_from_er_total": induction_ev_from_er_total,
        "induction_energy_graph_v2_enabled": induction_energy_graph_v2_enabled,
        "induction_energy_graph_config_max_rounds": induction_energy_graph_config_max_rounds,
        "induction_energy_graph_round_count_max": induction_energy_graph_round_count_max,
        "induction_energy_graph_depth_max": induction_energy_graph_depth_max,
        "induction_energy_graph_frontier_generated_count": induction_energy_graph_frontier_generated_count,
        "induction_energy_graph_frontier_pruned_count": induction_energy_graph_frontier_pruned_count,
        "induction_energy_graph_terminal_memory_count": induction_energy_graph_terminal_memory_count,
        "induction_energy_graph_root_reinduction_count": induction_energy_graph_root_reinduction_count,
        "induction_energy_graph_layer_count": induction_energy_graph_layer_count,
        "induction_energy_graph_layer_max_width": induction_energy_graph_layer_max_width,
        "induction_energy_graph_layer_total_nodes": induction_energy_graph_layer_total_nodes,
        "induction_energy_graph_round_summary_count": induction_energy_graph_round_summary_count,
        "induction_energy_graph_frontier_budget_total_ev": induction_energy_graph_frontier_budget_total_ev,
        "induction_energy_graph_root_induction_budget_total_ev": induction_energy_graph_root_induction_budget_total_ev,
        "induction_energy_graph_round_delta_ev_total": induction_energy_graph_round_delta_ev_total,
        "induction_energy_graph_round_delta_ev_max": induction_energy_graph_round_delta_ev_max,
        "induction_energy_graph_round_delta_ev_last": induction_energy_graph_round_delta_ev_last,
        "induction_energy_graph_frontier_in_count_max": induction_energy_graph_frontier_in_count_max,
        "induction_energy_graph_frontier_out_count_max": induction_energy_graph_frontier_out_count_max,
        "induction_source_item_count": induction_source_item_count,
        "induction_source_available_st_count": _as_int(induction_source_selection.get("induction_source_available_st_count", induction_source_item_count)),
        "induction_source_available_runtime_count": _as_int(induction_source_selection.get("induction_source_available_runtime_count", induction_source_item_count)),
        "induction_source_runtime_only_residual_prefilter_skipped_count": _as_int(induction_source_selection.get("induction_source_runtime_only_residual_prefilter_skipped_count", 0)),
        "induction_source_memory_terminal_prefilter_skipped_count": _as_int(induction_source_selection.get("induction_source_memory_terminal_prefilter_skipped_count", 0)),
        "induction_source_selected_non_st_count": _as_int(induction_source_selection.get("induction_source_selected_non_st_count", 0)),
        "induction_source_selected_from_ev_count": _as_int(induction_source_selection.get("induction_source_selected_from_ev_count", 0)),
        "induction_source_selected_from_er_count": _as_int(induction_source_selection.get("induction_source_selected_from_er_count", 0)),
        "induction_source_selected_from_cp_abs_count": _as_int(induction_source_selection.get("induction_source_selected_from_cp_abs_count", 0)),
        "induction_source_max_items": _as_int(induction_source_selection.get("induction_source_max_items", induction_source_item_count)),
        "induction_source_candidate_top_k": _as_int(induction_source_selection.get("induction_source_candidate_top_k", 0)),
        "induction_source_ev_quota_ratio": _as_float(induction_source_selection.get("induction_source_ev_quota_ratio", 0.0)),
        "induction_source_ev_quota_count": _as_int(induction_source_selection.get("induction_source_ev_quota_count", 0)),
        "induction_source_local_target_hint_diagnostics_skipped": _as_int(induction_source_selection.get("induction_source_local_target_hint_diagnostics_skipped", 0)),
        "induction_source_available_with_local_target_hint_count": _as_int(induction_source_selection.get("induction_source_available_with_local_target_hint_count", 0)),
        "induction_source_selected_with_local_target_hint_count": _as_int(induction_source_selection.get("induction_source_selected_with_local_target_hint_count", 0)),
        "induction_source_selected_zero_local_target_hint_count": _as_int(induction_source_selection.get("induction_source_selected_zero_local_target_hint_count", 0)),
        "induction_source_selection_cap_hit": _as_int(induction_source_selection.get("induction_source_selection_cap_hit", 0)),
        "induction_raw_residual_entry_count": induction_raw_residual_entry_count,
        "induction_raw_residual_entry_with_existing_structure_count": induction_raw_residual_entry_with_existing_structure_count,
        "induction_raw_residual_entry_routed_to_structure_count": induction_raw_residual_entry_routed_to_structure_count,
        "induction_raw_residual_existing_structure_target_count": induction_raw_residual_existing_structure_target_count,
        "induction_raw_residual_entry_materialized_structure_count": induction_raw_residual_entry_materialized_structure_count,
        "induction_raw_residual_materialized_structure_target_count": induction_raw_residual_materialized_structure_target_count,
        "induction_raw_residual_entry_with_component_structure_count": induction_raw_residual_entry_with_component_structure_count,
        "induction_raw_residual_entry_routed_to_component_structure_count": induction_raw_residual_entry_routed_to_component_structure_count,
        "induction_raw_residual_component_structure_target_count": induction_raw_residual_component_structure_target_count,
        "induction_owner_runtime_budget_selected_count": _as_int(induction_result_metrics.get("owner_runtime_budget_selected_count", 0)),
        "induction_owner_runtime_budget_pruned_count": _as_int(induction_result_metrics.get("owner_runtime_budget_pruned_count", 0)),
        "induction_target_count": induction_target_count,
        "induction_structure_target_count": induction_structure_target_count,
        "induction_memory_target_count": induction_memory_target_count,
        "induction_raw_residual_structure_target_count": induction_raw_residual_structure_target_count,
        "induction_raw_residual_exact_structure_target_count": induction_raw_residual_exact_structure_ev_target_count,
        "induction_raw_residual_component_structure_ev_target_count": induction_raw_residual_component_structure_ev_target_count,
        "induction_raw_residual_memory_target_count": induction_raw_residual_memory_target_count,
        "induction_raw_residual_hit_memory_target_count": induction_raw_residual_hit_memory_target_count,
        "induction_raw_residual_miss_memory_target_count": induction_raw_residual_miss_memory_target_count,
        "induction_applied_target_count": induction_applied_target_count,
        "induction_skipped_target_count": induction_skipped_target_count,
        "induction_skipped_cs_event_target_count": induction_skipped_cs_event_target_count,
        "induction_propagated_target_count": induction_propagated_target_count,
        "induction_induced_target_count": induction_induced_target_count,
        "induction_structure_target_total_ev": induction_structure_target_total_ev,
        "induction_memory_target_total_ev": induction_memory_target_total_ev,
        "induction_raw_residual_target_total_ev": induction_raw_residual_target_total_ev,
        "induction_raw_residual_structure_target_total_ev": induction_raw_residual_structure_target_total_ev,
        "induction_raw_residual_exact_structure_target_total_ev": induction_raw_residual_exact_structure_target_total_ev,
        "induction_raw_residual_component_structure_target_total_ev": induction_raw_residual_component_structure_target_total_ev,
        "induction_raw_residual_memory_target_total_ev": induction_raw_residual_memory_target_total_ev,
        "induction_raw_residual_hit_memory_target_total_ev": induction_raw_residual_hit_memory_target_total_ev,
        "induction_raw_residual_miss_memory_target_total_ev": induction_raw_residual_miss_memory_target_total_ev,
        "induction_raw_residual_hit_path_target_total_ev": induction_raw_residual_hit_path_target_total_ev,
        "induction_structure_target_ev_share": induction_structure_target_ev_share,
        "induction_memory_target_ev_share": induction_memory_target_ev_share,
        "induction_raw_residual_structure_target_ev_share": induction_raw_residual_structure_target_ev_share,
        "induction_raw_residual_exact_structure_ev_share": induction_raw_residual_exact_structure_ev_share,
        "induction_raw_residual_component_structure_ev_share": induction_raw_residual_component_structure_ev_share,
        "induction_raw_residual_memory_target_ev_share": induction_raw_residual_memory_target_ev_share,
        "induction_raw_residual_hit_path_structure_ev_share": induction_raw_residual_hit_path_structure_ev_share,
        "induction_raw_residual_hit_path_memory_ev_share": induction_raw_residual_hit_path_memory_ev_share,
        "induction_raw_residual_structure_budget_weight": induction_raw_residual_structure_budget_weight,
        "induction_raw_residual_exact_structure_budget_weight": induction_raw_residual_exact_structure_budget_weight,
        "induction_raw_residual_materialized_structure_budget_weight": induction_raw_residual_materialized_structure_budget_weight,
        "induction_raw_residual_component_structure_budget_weight": induction_raw_residual_component_structure_budget_weight,
        "induction_raw_residual_hit_memory_budget_weight": induction_raw_residual_hit_memory_budget_weight,
        "induction_raw_residual_miss_memory_budget_weight": induction_raw_residual_miss_memory_budget_weight,
        "induction_structure_db_update_request_count": induction_structure_db_update_request_count,
        "induction_structure_db_update_applied_count": induction_structure_db_update_applied_count,
        "induction_structure_db_update_deduped_count": induction_structure_db_update_deduped_count,
        "induction_applied_total_ev": induction_applied_total_ev,
        "induction_skipped_target_total_ev": induction_skipped_target_total_ev,
        "induction_applied_ev_ratio": induction_applied_ev_ratio,
        "induction_applied_target_ratio": induction_applied_target_ratio,
        "induction_structure_applied_target_count": induction_applied_target_count,
        "induction_structure_skipped_target_count": induction_skipped_target_count,
        "induction_structure_applied_total_ev": induction_applied_total_ev,
        "induction_structure_skipped_target_total_ev": induction_skipped_target_total_ev,
        "induction_structure_applied_ev_ratio": induction_applied_ev_ratio,
        "induction_structure_applied_target_ratio": induction_applied_target_ratio,
        "induction_propagated_target_ratio": induction_propagated_target_ratio,
        "induction_ev_from_er_ratio": induction_ev_from_er_ratio,
        "induction_targets_per_source_mean": induction_targets_per_source_mean,
        "induction_fallback_used": induction_fallback_used,
        "map_count": _as_int(map_summary.get("count", hdb_summary.get("memory_activation_count", 0))),
        "map_total_er": _as_float(map_summary.get("total_er", hdb_summary.get("memory_activation_total_er", 0.0))),
        "map_total_ev": _as_float(map_summary.get("total_ev", hdb_summary.get("memory_activation_total_ev", 0.0))),
        "map_apply_count": _as_int(map_apply.get("applied_count", 0)),
        "map_feedback_count": _as_int(map_feedback.get("applied_count", 0)),
        "map_feedback_total_ev": _as_float(map_feedback.get("total_feedback_ev", 0.0)),
        "memory_path_mode": memory_path_mode,
        "memory_runtime_projection_count": _as_int(memory_runtime_projection_summary.get("inserted_count", 0)),
        "memory_feedback_applied_count": memory_feedback_applied_count,
        "memory_feedback_total_er": memory_feedback_total_er,
        "memory_feedback_total_ev": memory_feedback_total_ev,
        "memory_feedback_total_energy": memory_feedback_total_energy,
        "memory_feedback_packet_count": memory_feedback_packet_count,
        "memory_feedback_packet_total_er": memory_feedback_packet_total_er,
        "memory_feedback_packet_total_ev": memory_feedback_packet_total_ev,
        "memory_feedback_packet_applied_total_er": memory_feedback_packet_applied_total_er,
        "memory_feedback_packet_applied_total_ev": memory_feedback_packet_applied_total_ev,
        "memory_feedback_packet_apply_efficiency_er": memory_feedback_packet_apply_efficiency_er,
        "memory_feedback_packet_apply_efficiency_ev": memory_feedback_packet_apply_efficiency_ev,
        "memory_feedback_structure_projection_ratio_used": memory_feedback_structure_projection_ratio_used,
        "memory_feedback_pool_ev_to_er_ratio_before": memory_feedback_pool_ev_to_er_ratio_before,
        "memory_feedback_structure_projection_attempted_count": memory_feedback_structure_projection_attempted_count,
        "memory_feedback_structure_projection_skipped_count": memory_feedback_structure_projection_skipped_count,
        "memory_feedback_structure_projection_count": memory_feedback_structure_projection_count,
        "memory_feedback_structure_projection_total_er": memory_feedback_structure_projection_total_er,
        "memory_feedback_structure_projection_total_ev": memory_feedback_structure_projection_total_ev,
        "memory_feedback_structure_projection_effective_ratio": memory_feedback_structure_projection_effective_ratio,
        # hdb counts
        "hdb_structure_count": hdb_structure_count,
        "hdb_group_count": _as_int(hdb_summary.get("group_count", 0)),
        "hdb_episodic_count": _as_int(hdb_summary.get("episodic_count", 0)),
        "hdb_contextual_structure_count": hdb_contextual_structure_count,
        "hdb_multi_context_structure_count": hdb_multi_context_structure_count,
        "hdb_structure_context_path_depth_mean": _as_float(hdb_summary.get("structure_context_path_depth_mean", 0.0)),
        "hdb_same_content_multi_context_count": hdb_same_content_multi_context_count,
        "hdb_diff_entry_count": hdb_diff_entry_count,
        "hdb_contextual_diff_entry_count": hdb_contextual_diff_entry_count,
        "hdb_residual_diff_entry_count": hdb_residual_diff_entry_count,
        "hdb_diff_entry_with_memory_ref_count": _as_int(hdb_summary.get("diff_entry_with_memory_ref_count", 0)),
        "hdb_contextual_structure_ratio": hdb_contextual_structure_ratio,
        "hdb_multi_context_structure_ratio": hdb_multi_context_structure_ratio,
        "hdb_same_content_multi_context_ratio": hdb_same_content_multi_context_ratio,
        "hdb_contextual_diff_entry_ratio": hdb_contextual_diff_entry_ratio,
        "hdb_residual_diff_entry_ratio": hdb_residual_diff_entry_ratio,
        "hdb_primary_pointer_count": hdb_primary_pointer_count,
        "hdb_fallback_pointer_count": hdb_fallback_pointer_count,
        "hdb_signature_index_count": hdb_signature_index_count,
        "hdb_recent_cache_count": hdb_recent_cache_count,
        "hdb_exact_lookup_cache_count": hdb_exact_lookup_cache_count,
        "hdb_numeric_bucket_family_count": hdb_numeric_bucket_family_count,
        "hdb_numeric_bucket_count": hdb_numeric_bucket_count,
        # maintenance / pool landing
        "maintenance_event_count": len(_as_list(maintenance.get("events"))),
        "maintenance_before_active_item_count": _as_int(maintenance_before.get("active_item_count", 0)),
        "maintenance_after_active_item_count": _as_int(maintenance_after.get("active_item_count", 0)),
        "maintenance_before_high_cp_item_count": _as_int(maintenance_before.get("high_cp_item_count", 0)),
        "maintenance_after_high_cp_item_count": _as_int(maintenance_after.get("high_cp_item_count", 0)),
        "maintenance_delta_active_item_count": _as_int(maintenance_after.get("active_item_count", 0)) - _as_int(maintenance_before.get("active_item_count", 0)),
        "maintenance_delta_high_cp_item_count": _as_int(maintenance_after.get("high_cp_item_count", 0)) - _as_int(maintenance_before.get("high_cp_item_count", 0)),
        "maintenance_runtime_resolution_refreshed_item_count": _as_int(maintenance_summary.get("runtime_resolution_refreshed_item_count", 0)),
        "maintenance_runtime_resolution_degraded_item_count": _as_int(maintenance_summary.get("runtime_resolution_degraded_item_count", 0)),
        "pool_apply_new_item_count": _as_int(pool_apply_result.get("new_item_count", 0)),
        "pool_apply_updated_item_count": _as_int(pool_apply_result.get("updated_item_count", 0)),
        "pool_apply_merged_item_count": _as_int(pool_apply_result.get("merged_item_count", 0)),
        "pool_apply_total_delta_er": _as_float(pool_apply_result.get("state_delta_summary", {}).get("total_delta_er", 0.0) if isinstance(pool_apply_result.get("state_delta_summary"), dict) else 0.0),
        "pool_apply_total_delta_ev": _as_float(pool_apply_result.get("state_delta_summary", {}).get("total_delta_ev", 0.0) if isinstance(pool_apply_result.get("state_delta_summary"), dict) else 0.0),
        "pool_apply_total_delta_cp": _as_float(pool_apply_result.get("state_delta_summary", {}).get("total_delta_cp", 0.0) if isinstance(pool_apply_result.get("state_delta_summary"), dict) else 0.0),
        "residual_tail_memory_projection_applied": int(bool(residual_tail_memory_projection.get("applied", False))),
        "residual_tail_memory_projection_handled": int(bool(residual_tail_memory_projection.get("handled", False))),
        "residual_tail_memory_projection_er": _as_float(residual_tail_memory_energy.get("er", 0.0)),
        "residual_tail_memory_projection_ev": _as_float(residual_tail_memory_energy.get("ev", 0.0)),
        "residual_tail_memory_projection_total_energy": round(
            _as_float(residual_tail_memory_energy.get("er", 0.0))
            + _as_float(residual_tail_memory_energy.get("ev", 0.0)),
            8,
        ),
        "residual_tail_memory_projection_token_count": _as_int(residual_tail_memory_payload.get("token_count", 0)),
        "residual_tail_memory_projection_full_memory_token_count": _as_int(residual_tail_memory_payload.get("full_memory_token_count", 0)),
        "residual_tail_memory_projection_tail_component_er_share": _as_float(residual_tail_memory_component.get("tail_component_er_share", 0.0)),
        "residual_tail_memory_projection_tail_component_ev_share": _as_float(residual_tail_memory_component.get("tail_component_ev_share", 0.0)),
        "runtime_residual_package_applied": int(bool(runtime_residual_package.get("applied", False))),
        "runtime_residual_package_er": _as_float(runtime_residual_package_energy.get("er", 0.0)),
        "runtime_residual_package_ev": _as_float(runtime_residual_package_energy.get("ev", 0.0)),
        "runtime_residual_package_total_energy": round(
            _as_float(runtime_residual_package_energy.get("er", 0.0))
            + _as_float(runtime_residual_package_energy.get("ev", 0.0)),
            8,
        ),
        "runtime_residual_package_token_count": _as_int(runtime_residual_package_structure.get("token_count", 0)),
        "runtime_residual_immediate_promotion_promoted_count": int(bool(runtime_residual_immediate_promotion.get("promoted", False))),
        "runtime_residual_immediate_promotion_created_count": int(bool(runtime_residual_immediate_promotion.get("created", False))),
        "runtime_residual_immediate_promotion_matched_count": int(bool(runtime_residual_immediate_promotion.get("matched", False))),
        "runtime_residual_immediate_promotion_hdb_fallback_count": int(bool(runtime_residual_immediate_promotion.get("hdb_fallback", False))),
        "runtime_residual_promotion_attempted_count": _as_int(runtime_residual_promotion.get("attempted_count", 0)),
        "runtime_residual_promotion_promoted_count": _as_int(runtime_residual_promotion.get("promoted_count", 0)),
        "runtime_residual_promotion_exact_rebind_count": runtime_residual_exact_rebind_count,
        "runtime_residual_promotion_full_identity_count": runtime_residual_full_identity_count,
        "runtime_residual_promotion_hdb_fallback_count": runtime_residual_hdb_fallback_count,
        "runtime_residual_promotion_created_count": int(
            sum(1 for item in runtime_residual_promotion_items if bool(item.get("created", False)))
        ),
        "runtime_residual_promotion_matched_count": int(
            sum(1 for item in runtime_residual_promotion_items if bool(item.get("matched", False)))
        ),
        # retrieval / grasp observability
        "stimulus_residual_ratio": _as_float(stimulus_result_metrics.get("residual_ratio", 0.0)),
        "stimulus_best_match_score": _as_float(stimulus_result_metrics.get("best_match_score", 0.0)),
        "stimulus_grasp_score": _as_float(stimulus_result_metrics.get("grasp_score", 0.0)),
        "grasp_score": _as_float(stimulus_result_metrics.get("grasp_score", 0.0)),
        "stimulus_match_score_target_count": _as_int(stimulus_result_metrics.get("match_score_target_count", 0)),
        "stimulus_best_match_target_id": _as_str(stimulus_result_metrics.get("best_match_target_id", "")),
        "structure_best_match_score": _as_float(structure_result_metrics.get("best_match_score", 0.0)),
        "structure_match_score_target_count": _as_int(structure_result_metrics.get("match_score_target_count", 0)),
        "structure_best_match_target_id": _as_str(structure_result_metrics.get("best_match_target_id", "")),
        # cognitive stitching (CS)
        "cs_enabled": int(bool(cognitive_stitching.get("enabled", False))),
        "cs_stage_mode": _as_str(cognitive_stitching.get("stage_mode", "")),
        "cs_selected_stage": _as_str(cognitive_stitching.get("selected_stage", "")),
        "cs_seed_structure_count": _as_int(cognitive_stitching.get("seed_structure_count", 0)),
        "cs_seed_event_count": _as_int(cognitive_stitching.get("seed_event_count", 0)),
        "cs_candidate_count": _as_int(cognitive_stitching.get("candidate_count", 0)),
        "cs_active_item_count": _as_int(cs_candidate_audit.get("active_item_count", 0)),
        "cs_active_structure_count": _as_int(cs_candidate_audit.get("active_structure_count", 0)),
        "cs_seed_scan_count": _as_int(cs_candidate_audit.get("seed_scan_count", 0)),
        "cs_seed_structure_scan_count": _as_int(cs_candidate_audit.get("seed_structure_scan_count", 0)),
        "cs_seed_scan_capped": int(bool(cs_candidate_audit.get("seed_scan_capped", False))),
        "cs_exact_context_index_owner_count": _as_int(cs_candidate_audit.get("exact_context_index_owner_count", 0)),
        "cs_exact_context_index_target_total": _as_int(cs_candidate_audit.get("exact_context_index_target_total", 0)),
        "cs_exact_context_index_max_bucket_size": _as_int(cs_candidate_audit.get("exact_context_index_max_bucket_size", 0)),
        "cs_exact_context_index_avg_bucket_size": _as_float(cs_candidate_audit.get("exact_context_index_avg_bucket_size", 0.0)),
        "cs_context_concat_source_scan_count": _as_int(cs_candidate_audit.get("context_concat_source_scan_count", 0)),
        "cs_context_concat_exact_source_hit_count": _as_int(cs_candidate_audit.get("context_concat_exact_source_hit_count", 0)),
        "cs_context_concat_source_with_candidate_count": _as_int(cs_candidate_audit.get("context_concat_source_with_candidate_count", 0)),
        "cs_context_concat_attention_seed_source_scan_count": _as_int(
            cs_candidate_audit.get("context_concat_attention_seed_source_scan_count", 0)
        ),
        "cs_context_concat_projected_support_source_scan_count": _as_int(
            cs_candidate_audit.get("context_concat_projected_support_source_scan_count", 0)
        ),
        "cs_context_concat_exact_target_total": _as_int(cs_candidate_audit.get("context_concat_exact_target_total", 0)),
        "cs_context_concat_soft_scan_attempt_count": _as_int(cs_candidate_audit.get("context_concat_soft_scan_attempt_count", 0)),
        "cs_context_concat_soft_scan_allowed_count": _as_int(cs_candidate_audit.get("context_concat_soft_scan_allowed_count", 0)),
        "cs_context_concat_soft_scan_blocked_count": _as_int(cs_candidate_audit.get("context_concat_soft_scan_blocked_count", 0)),
        "cs_context_concat_soft_target_total": _as_int(cs_candidate_audit.get("context_concat_soft_target_total", 0)),
        "cs_context_concat_candidate_target_total": _as_int(cs_candidate_audit.get("context_concat_candidate_target_total", 0)),
        "cs_context_concat_candidate_pick_total": _as_int(cs_candidate_audit.get("context_concat_candidate_pick_total", 0)),
        "cs_context_concat_target_cap_hit_count": _as_int(cs_candidate_audit.get("context_concat_target_cap_hit_count", 0)),
        "cs_context_concat_pick_cap_hit_count": _as_int(cs_candidate_audit.get("context_concat_pick_cap_hit_count", 0)),
        "cs_candidate_accepted_exact_context_identity_count": _as_int(
            cs_candidate_audit.get("accepted_exact_context_identity_count", 0)
        ),
        "cs_candidate_accepted_prefix_trim_count": _as_int(
            cs_candidate_audit.get("accepted_target_context_prefix_trimmed_count", 0)
        ),
        "cs_candidate_raw_accepted_count": _as_int(cs_candidate_audit.get("raw_accepted_count", 0)),
        "cs_candidate_deduped_count": _as_int(cs_candidate_audit.get("deduped_candidate_count", 0)),
        "cs_candidate_deduped_pruned_count": _as_int(cs_candidate_audit.get("deduped_pruned_count", 0)),
        "cs_candidate_rejected_count": _as_int(cs_candidate_audit.get("rejected_count", 0)),
        "cs_candidate_rejected_low_score_count": _as_int(cs_candidate_rejected_reason_counts.get("below_min_candidate_score", 0))
        + _as_int(cs_candidate_rejected_reason_counts.get("below_v2_min_match_score", 0)),
        "cs_candidate_rejected_v2_low_score_count": _as_int(cs_candidate_rejected_reason_counts.get("below_v2_min_match_score", 0)),
        "cs_candidate_rejected_component_limit_count": _as_int(cs_candidate_rejected_reason_counts.get("component_count_exceeded", 0)),
        "cs_candidate_rejected_non_positive_edge_count": _as_int(cs_candidate_rejected_reason_counts.get("non_positive_edge", 0)),
        "cs_candidate_replacement_count": _as_int(cs_candidate_audit.get("replacement_count", 0)),
        "cs_candidate_kept_existing_count": _as_int(cs_candidate_audit.get("kept_existing_count", 0)),
        "cs_candidate_score_mean": _as_float(cs_candidate_score_means.get("score", 0.0)),
        "cs_candidate_base_score_mean": _as_float(cs_candidate_score_means.get("base_score", 0.0)),
        "cs_candidate_edge_weight_ratio_mean": _as_float(cs_candidate_score_means.get("edge_weight_ratio", 0.0)),
        "cs_candidate_match_strength_mean": _as_float(cs_candidate_score_means.get("match_strength", 0.0)),
        "cs_candidate_context_ratio_mean": _as_float(cs_candidate_score_means.get("context_ratio", 0.0)),
        "cs_candidate_energy_balance_mean": _as_float(cs_candidate_score_means.get("energy_balance", 0.0)),
        "cs_candidate_runtime_balance_mean": _as_float(cs_candidate_score_means.get("runtime_balance", 0.0)),
        "cs_candidate_bridge_span_ratio_mean": _as_float(cs_candidate_score_means.get("bridge_span_ratio", 0.0)),
        "cs_candidate_anchor_scale_mean": _as_float(cs_candidate_score_means.get("anchor_scale", 0.0)),
        "cs_candidate_fatigue_scale_mean": _as_float(cs_candidate_score_means.get("fatigue_scale", 0.0)),
        "cs_candidate_threshold_margin_mean": _as_float(cs_candidate_score_means.get("threshold_margin", 0.0)),
        "cs_candidate_match_count_mean": _as_float(cs_candidate_score_means.get("match_count_score", 0.0)),
        "cs_candidate_attribute_bonus_mean": _as_float(cs_candidate_score_means.get("attribute_bonus_score", 0.0)),
        "cs_candidate_effective_match_units_mean": _as_float(cs_candidate_score_means.get("effective_match_units", 0.0)),
        "cs_candidate_v2_score_mean": _as_float(cs_candidate_score_means.get("v2_score", 0.0)),
        "cs_candidate_v2_base_score_mean": _as_float(cs_candidate_score_means.get("v2_base_score", 0.0)),
        "cs_candidate_v2_threshold_margin_mean": _as_float(cs_candidate_score_means.get("v2_threshold_margin", 0.0)),
        "cs_candidate_v2_context_cover_mean": _as_float(cs_candidate_score_means.get("v2_context_cover_score", 0.0)),
        "cs_candidate_v2_order_alignment_mean": _as_float(cs_candidate_score_means.get("v2_order_alignment_score", 0.0)),
        "cs_candidate_v2_tail_match_mean": _as_float(cs_candidate_score_means.get("v2_tail_match_score", 0.0)),
        "cs_candidate_v2_context_db_support_mean": _as_float(cs_candidate_score_means.get("v2_context_db_support_score", 0.0)),
        "cs_candidate_v2_energy_profile_mean": _as_float(cs_candidate_score_means.get("v2_energy_profile_score", 0.0)),
        "cs_candidate_v2_match_count_mean": _as_float(cs_candidate_score_means.get("v2_match_count_score", 0.0)),
        "cs_candidate_v2_attribute_bonus_mean": _as_float(cs_candidate_score_means.get("v2_attribute_bonus_score", 0.0)),
        "cs_action_count": _as_int(cognitive_stitching.get("action_count", 0)),
        "cs_success_count": _as_int(cognitive_stitching.get("success_count", cognitive_stitching.get("action_count", 0))),
        "cs_concat_count": _as_int(cognitive_stitching.get("concat_count", 0)),
        "cs_apply_candidate_input_count": _as_int(cs_apply_audit.get("candidate_input_count", 0)),
        "cs_apply_skip_count": _as_int(cs_apply_audit.get("skip_count", 0)),
        "cs_apply_skip_exclusive_item_consumed_count": _as_int(cs_apply_skip_reason_counts.get("exclusive_item_consumed", 0)),
        "cs_apply_skip_below_min_event_total_count": _as_int(cs_apply_skip_reason_counts.get("below_min_event_total", 0)),
        "cs_apply_skip_max_events_count": _as_int(cs_apply_skip_reason_counts.get("max_events_per_tick", 0)),
        "cs_apply_concat_action_count": _as_int(cs_apply_audit.get("concat_action_count", 0)),
        "cs_apply_exact_concat_action_count": _as_int(cs_apply_audit.get("exact_concat_action_count", 0)),
        "cs_apply_exact_new_concat_action_count": _as_int(cs_apply_audit.get("exact_new_concat_action_count", 0)),
        "cs_apply_partial_concat_action_count": _as_int(cs_apply_audit.get("partial_concat_action_count", 0)),
        "cs_apply_partial_new_concat_action_count": _as_int(cs_apply_audit.get("partial_new_concat_action_count", 0)),
        "cs_apply_reinforce_concat_action_count": _as_int(cs_apply_audit.get("reinforce_concat_action_count", 0)),
        "cs_apply_prefix_trimmed_action_count": _as_int(cs_apply_audit.get("target_context_prefix_trimmed_action_count", 0)),
        "cs_apply_lower_energy_cap_audit_count": _as_int(cs_apply_audit.get("lower_energy_cap_audit_count", 0)),
        "cs_apply_lower_energy_cap_abs_diff_max": _as_float(cs_apply_audit.get("lower_energy_cap_abs_diff_max", 0.0)),
        "cs_apply_absorb_ratio_mean": _as_float(cs_apply_audit.get("absorb_ratio_mean", 0.0)),
        "cs_apply_absorbed_total_mean": _as_float(cs_apply_audit.get("absorbed_total_mean", 0.0)),
        "cs_apply_source_absorbed_total_mean": _as_float(cs_apply_audit.get("source_absorbed_total_mean", 0.0)),
        "cs_apply_target_absorbed_total_mean": _as_float(cs_apply_audit.get("target_absorbed_total_mean", 0.0)),
        "cs_created_count": _as_int(cognitive_stitching.get("created_count", 0)),
        "cs_extended_count": _as_int(cognitive_stitching.get("extended_count", 0)),
        "cs_merged_count": _as_int(cognitive_stitching.get("merged_count", 0)),
        "cs_reinforced_count": _as_int(cognitive_stitching.get("reinforced_count", 0)),
        "cs_pair_fatigue_state_size": _as_int(cognitive_stitching.get("pair_fatigue_state_size", 0)),
        "cs_object_stitch_fatigue_state_size": _as_int(cognitive_stitching.get("object_stitch_fatigue_state_size", 0)),
        "cs_event_grasp_reason": _as_str(cs_event_grasp.get("reason", "")),
        "cs_event_grasp_focus_mode": _as_str(cs_event_grasp.get("focus_mode", "")),
        "cs_event_grasp_selected_event_count": _as_int(cs_event_grasp.get("selected_event_count", 0)),
        "cs_event_grasp_emitted_count": _as_int(cs_event_grasp.get("emitted_count", 0)),
        "cs_event_grasp_focus_candidate_item_count": _as_int(cs_event_grasp.get("focus_candidate_item_count", 0)),
        "cs_event_grasp_cam_seed_count": _as_int(cs_event_grasp.get("cam_seed_count", 0)),
        "cs_event_grasp_post_action_seed_count": _as_int(cs_event_grasp.get("post_action_seed_count", 0)),
        "cs_event_grasp_cam_selected_event_count": _as_int(cs_event_grasp.get("cam_selected_event_count", 0)),
        "cs_event_grasp_post_action_selected_event_count": _as_int(cs_event_grasp.get("post_action_selected_event_count", 0)),
        "cs_narrative_top_grasp": round(float(cs_top_grasp), 8),
        "cs_narrative_grasp_max": round(float(cs_max_grasp), 8),
        "cs_narrative_grasp_positive_count": int(cs_grasp_positive_count),
        "cs_narrative_top_total_energy": round(float(cs_top_total_energy), 8),
        "cs_concat_narrative_count": int(cs_concat_narrative_count),
        "cs_action_log_count": int(cs_action_log_count),
        "cs_action_log_concat_count": int(cs_action_log_concat_count),
        "cs_action_log_reinforce_concat_count": int(cs_action_log_reinforce_concat_count),
        "cs_action_object_stitch_fatigue_hit_count": int(cs_action_object_fatigue_hit_count),
        "cs_action_object_stitch_fatigue_before_mean": _mean(cs_action_object_fatigue_before_values),
        "cs_action_object_stitch_fatigue_scale_mean": _mean(cs_action_object_fatigue_scale_values),
        "cs_action_log": cs_action_log,
        # cfs summary
        "cfs_signal_count": len([x for x in cfs_signals if isinstance(x, dict)]),
        "cfs_total_strength": round(float(cfs_total_strength), 8),
        # emotion / NT
        "nt_OXY": nt["OXY"],
        "nt_DA": nt["DA"],
        "nt_END": nt["END"],
        "nt_COR": nt["COR"],
        "nt_ADR": nt["ADR"],
        "nt_SER": nt["SER"],
        "nt_NOV": nt["NOV"],
        "nt_FOC": nt["FOC"],
        "nt_channel_count": len([x for x in nt.keys() if str(x).strip()]),
        "emotion_hdb_base_weight_er_gain_scale": _as_float(applied_base_weight_er_gain.get("scale", 0.0)),
        "emotion_hdb_base_weight_ev_wear_scale": _as_float(applied_base_weight_ev_wear.get("scale", 0.0)),
        "emotion_hdb_ev_propagation_threshold_scale": _as_float(applied_ev_threshold.get("scale", 0.0)),
        "emotion_hdb_ev_propagation_ratio_scale": _as_float(applied_ev_ratio.get("scale", 0.0)),
        "emotion_hdb_er_induction_ratio_scale": _as_float(applied_er_ratio.get("scale", 0.0)),
        # reward / punish (global snapshot used by EMgr)
        "rwd_pun_rwd": _as_float(rwd_pun_snapshot.get("rwd", 0.0)),
        "rwd_pun_pun": _as_float(rwd_pun_snapshot.get("pun", 0.0)),
        # energy balance controller
        "energy_balance_enabled": int(bool(energy_balance.get("enabled", False))),
        "energy_balance_updated": int(bool(energy_balance.get("updated", False))),
        "energy_balance_window_ticks": _as_int(energy_balance.get("window_ticks", 0)),
        "energy_balance_target_ratio": _as_float(energy_balance.get("target_ratio", 0.0)),
        "energy_balance_ratio_raw": _as_float(energy_balance.get("ratio_raw", 0.0)),
        "energy_balance_ratio_smooth": _as_float(energy_balance.get("ratio_smooth", 0.0)),
        "energy_balance_error_log": _as_float(energy_balance.get("error_log", 0.0)),
        "energy_balance_ki": _as_float(energy_balance.get("ki", 0.0)),
        "energy_balance_g_before": _as_float(energy_balance.get("g_before", 0.0)),
        "energy_balance_g_after": _as_float(energy_balance.get("g_after", 0.0)),
        "energy_balance_min_total_energy_to_update": _as_float(energy_balance.get("min_total_energy_to_update", 0.0)),
        "energy_balance_skipped_low_energy": int(_as_str(energy_balance.get("skipped_reason", "")) == "low_energy"),
        "energy_balance_skipped_disabled": int(_as_str(energy_balance.get("skipped_reason", "")) == "disabled"),
        "energy_balance_hdb_scale_count": len([x for x in energy_balance_hdb_scales.keys() if str(x).strip()]),
        "energy_balance_ev_propagation_ratio_scale": _as_float(energy_balance_hdb_scales.get("ev_propagation_ratio_scale", 0.0)),
        "energy_balance_er_induction_ratio_scale": _as_float(energy_balance_hdb_scales.get("er_induction_ratio_scale", 0.0)),
        "hdb_requested_ev_propagation_ratio": _as_float(applied_ev_ratio.get("effective", 0.0)),
        "hdb_effective_ev_propagation_ratio": _as_float(applied_ev_ratio.get("runtime_effective", applied_ev_ratio.get("effective", 0.0))),
        "hdb_requested_er_induction_ratio": _as_float(applied_er_ratio.get("effective", 0.0)),
        "hdb_effective_er_induction_ratio": _as_float(applied_er_ratio.get("runtime_effective", applied_er_ratio.get("effective", 0.0))),
        "hdb_ev_propagation_ratio_clamped": int(bool(applied_ev_ratio.get("runtime_clamped", False))),
        "hdb_er_induction_ratio_clamped": int(bool(applied_er_ratio.get("runtime_clamped", False))),
        # IESM / innate rules observability
        "iesm_triggered_rule_count": int(iesm_triggered_rule_count or _as_int(innate_tick_rules.get("triggered_rule_count", 0))),
        "iesm_triggered_rule_count_source_visible": int(iesm_triggered_rule_count_source_visible if iesm_triggered_rule_count else (0 if tick_is_synthetic else _as_int(innate_tick_rules.get("triggered_rule_count", 0)))),
        "iesm_triggered_rule_count_synthetic_only": int(iesm_triggered_rule_count_synthetic_only if iesm_triggered_rule_count else (_as_int(innate_tick_rules.get("triggered_rule_count", 0)) if tick_is_synthetic else 0)),
        "iesm_triggered_script_count": int(iesm_triggered_script_count or _as_int(innate_tick_rules.get("triggered_script_count", 0))),
        "iesm_triggered_script_count_source_visible": int(iesm_triggered_script_count_source_visible if iesm_triggered_script_count else (0 if tick_is_synthetic else _as_int(innate_tick_rules.get("triggered_script_count", 0)))),
        "iesm_triggered_script_count_synthetic_only": int(iesm_triggered_script_count_synthetic_only if iesm_triggered_script_count else (_as_int(innate_tick_rules.get("triggered_script_count", 0)) if tick_is_synthetic else 0)),
        "iesm_action_trigger_count": int(iesm_action_trigger_count or _as_int(innate_tick_rules.get("action_trigger_count", 0))),
        "iesm_action_trigger_count_source_visible": int(iesm_action_trigger_count_source_visible if iesm_action_trigger_count else (0 if tick_is_synthetic else _as_int(innate_tick_rules.get("action_trigger_count", 0)))),
        "iesm_action_trigger_count_synthetic_only": int(iesm_action_trigger_count_synthetic_only if iesm_action_trigger_count else (_as_int(innate_tick_rules.get("action_trigger_count", 0)) if tick_is_synthetic else 0)),
        "iesm_selector_cache_hit": _as_int(innate_tick_rules_audit.get("selector_cache_hit", 0)),
        "iesm_selector_cache_miss": _as_int(innate_tick_rules_audit.get("selector_cache_miss", 0)),
        "iesm_selector_cache_size": _as_int(innate_tick_rules_audit.get("selector_cache_size", 0)),
        "iesm_emotion_update_key_count": int(len(iesm_emotion_update_values) or _as_int(innate_tick_rules.get("emotion_update_key_count", 0))),
        "iesm_emotion_update_key_count_source_visible": int(
            0
            if tick_is_synthetic
            else (len(iesm_emotion_update_values) or _as_int(innate_tick_rules.get("emotion_update_key_count", 0)))
        ),
        "iesm_emotion_update_key_count_synthetic_only": int(
            (len(iesm_emotion_update_values) or _as_int(innate_tick_rules.get("emotion_update_key_count", 0)))
            if tick_is_synthetic
            else 0
        ),
        "iesm_emotion_update_abs_total": round(float(iesm_emotion_update_abs_total), 8),
        "iesm_emotion_update_abs_total_source_visible": round(float(0.0 if tick_is_synthetic else iesm_emotion_update_abs_total), 8),
        "iesm_emotion_update_abs_total_synthetic_only": round(float(iesm_emotion_update_abs_total if tick_is_synthetic else 0.0), 8),
        "iesm_action_trigger_targeted_count": int(iesm_action_trigger_targeted_count),
        "iesm_action_trigger_targeted_count_source_visible": int(iesm_action_trigger_targeted_count_source_visible),
        "iesm_action_trigger_targeted_count_synthetic_only": int(iesm_action_trigger_targeted_count_synthetic_only),
        "iesm_action_trigger_target_missing_count": int(iesm_action_trigger_target_missing_count),
        "iesm_action_trigger_target_missing_count_source_visible": int(iesm_action_trigger_target_missing_count_source_visible),
        "iesm_action_trigger_target_missing_count_synthetic_only": int(iesm_action_trigger_target_missing_count_synthetic_only),
        "iesm_action_trigger_weather_stub_count": int(iesm_action_trigger_kind_counts.get("weather_stub", 0)),
        "iesm_action_trigger_weather_stub_count_source_visible": int(iesm_action_trigger_kind_counts_source_visible.get("weather_stub", 0)),
        "iesm_action_trigger_weather_stub_count_synthetic_only": int(iesm_action_trigger_kind_counts_synthetic_only.get("weather_stub", 0)),
        "iesm_action_trigger_targeted_weather_stub_count": int(iesm_action_trigger_targeted_kind_counts.get("weather_stub", 0)),
        "iesm_action_trigger_targeted_weather_stub_count_source_visible": int(
            iesm_action_trigger_targeted_kind_counts_source_visible.get("weather_stub", 0)
        ),
        "iesm_action_trigger_targeted_weather_stub_count_synthetic_only": int(
            iesm_action_trigger_targeted_kind_counts_synthetic_only.get("weather_stub", 0)
        ),
        "iesm_action_trigger_target_missing_weather_stub_count": int(
            iesm_action_trigger_target_missing_kind_counts.get("weather_stub", 0)
        ),
        "iesm_action_trigger_target_missing_weather_stub_count_source_visible": int(
            iesm_action_trigger_target_missing_kind_counts_source_visible.get("weather_stub", 0)
        ),
        "iesm_action_trigger_target_missing_weather_stub_count_synthetic_only": int(
            iesm_action_trigger_target_missing_kind_counts_synthetic_only.get("weather_stub", 0)
        ),
        # action
        "action_attempted_count": int(action_attempted_count),
        "action_attempted_count_source_visible": int(action_attempted_count_source_visible),
        "action_attempted_count_synthetic_only": int(action_attempted_count_synthetic_only),
        "action_attempted_attention_focus": int(attempted_kind_counts.get("attention_focus", 0)),
        "action_attempted_attention_focus_source_visible": int(attempted_kind_counts_source_visible.get("attention_focus", 0)),
        "action_attempted_attention_focus_synthetic_only": int(attempted_kind_counts_synthetic_only.get("attention_focus", 0)),
        "action_attempted_recall": int(attempted_kind_counts.get("recall", 0)),
        "action_attempted_recall_source_visible": int(attempted_kind_counts_source_visible.get("recall", 0)),
        "action_attempted_recall_synthetic_only": int(attempted_kind_counts_synthetic_only.get("recall", 0)),
        "action_attempted_weather_stub": int(attempted_kind_counts.get("weather_stub", 0)),
        "action_attempted_weather_stub_source_visible": int(attempted_kind_counts_source_visible.get("weather_stub", 0)),
        "action_attempted_weather_stub_synthetic_only": int(attempted_kind_counts_synthetic_only.get("weather_stub", 0)),
        "action_attempted_diverge_mode": int(attempted_kind_counts.get("attention_diverge_mode", 0)),
        "action_attempted_diverge_mode_source_visible": int(attempted_kind_counts_source_visible.get("attention_diverge_mode", 0)),
        "action_attempted_diverge_mode_synthetic_only": int(attempted_kind_counts_synthetic_only.get("attention_diverge_mode", 0)),
        "action_attempted_focus_mode": int(attempted_kind_counts.get("attention_focus_mode", 0)),
        "action_attempted_focus_mode_source_visible": int(attempted_kind_counts_source_visible.get("attention_focus_mode", 0)),
        "action_attempted_focus_mode_synthetic_only": int(attempted_kind_counts_synthetic_only.get("attention_focus_mode", 0)),
        "action_executed_count": int(action_executed_count),
        "action_executed_count_source_visible": int(action_executed_count_source_visible),
        "action_executed_count_synthetic_only": int(action_executed_count_synthetic_only),
        "action_executed_attention_focus": int(executed_kind_counts.get("attention_focus", 0)),
        "action_executed_attention_focus_source_visible": int(executed_kind_counts_source_visible.get("attention_focus", 0)),
        "action_executed_attention_focus_synthetic_only": int(executed_kind_counts_synthetic_only.get("attention_focus", 0)),
        "action_executed_recall": int(executed_kind_counts.get("recall", 0)),
        "action_executed_recall_source_visible": int(executed_kind_counts_source_visible.get("recall", 0)),
        "action_executed_recall_synthetic_only": int(executed_kind_counts_synthetic_only.get("recall", 0)),
        "action_executed_weather_stub": int(executed_kind_counts.get("weather_stub", 0)),
        "action_executed_weather_stub_source_visible": int(executed_kind_counts_source_visible.get("weather_stub", 0)),
        "action_executed_weather_stub_synthetic_only": int(executed_kind_counts_synthetic_only.get("weather_stub", 0)),
        "action_executed_diverge_mode": int(executed_kind_counts.get("attention_diverge_mode", 0)),
        "action_executed_diverge_mode_source_visible": int(executed_kind_counts_source_visible.get("attention_diverge_mode", 0)),
        "action_executed_diverge_mode_synthetic_only": int(executed_kind_counts_synthetic_only.get("attention_diverge_mode", 0)),
        "action_executed_focus_mode": int(executed_kind_counts.get("attention_focus_mode", 0)),
        "action_executed_focus_mode_source_visible": int(executed_kind_counts_source_visible.get("attention_focus_mode", 0)),
        "action_executed_focus_mode_synthetic_only": int(executed_kind_counts_synthetic_only.get("attention_focus_mode", 0)),
        "action_scheduled_weather_stub": int(scheduled_kind_counts.get("weather_stub", 0)),
        "action_scheduled_weather_stub_source_visible": int(scheduled_kind_counts_source_visible.get("weather_stub", 0)),
        "action_scheduled_weather_stub_synthetic_only": int(scheduled_kind_counts_synthetic_only.get("weather_stub", 0)),
        "action_node_count": len([x for x in action_nodes if isinstance(x, dict)]),
        "action_drive_max": round(float(max(action_drive_vals) if action_drive_vals else 0.0), 8),
        "action_drive_mean": round(float(sum(action_drive_vals) / len(action_drive_vals)) if action_drive_vals else 0.0, 8),
        "action_drive_active_count": int(action_drive_active_count),
        "action_base_threshold_mean": round(float(sum(action_base_threshold_vals) / len(action_base_threshold_vals)) if action_base_threshold_vals else 0.0, 8),
        "action_effective_threshold_mean": round(float(sum(action_effective_threshold_vals) / len(action_effective_threshold_vals)) if action_effective_threshold_vals else 0.0, 8),
        "action_threshold_scale_mean": round(float(sum(action_threshold_scale_vals) / len(action_threshold_scale_vals)) if action_threshold_scale_vals else 0.0, 8),
        "action_threshold_nt_scale_mean": round(float(sum(action_threshold_nt_scale_vals) / len(action_threshold_nt_scale_vals)) if action_threshold_nt_scale_vals else 0.0, 8),
        "action_threshold_rwd_pun_scale_mean": round(float(sum(action_threshold_rwd_pun_scale_vals) / len(action_threshold_rwd_pun_scale_vals)) if action_threshold_rwd_pun_scale_vals else 0.0, 8),
        "action_threshold_fatigue_scale_mean": round(float(sum(action_threshold_fatigue_scale_vals) / len(action_threshold_fatigue_scale_vals)) if action_threshold_fatigue_scale_vals else 0.0, 8),
        "action_threshold_rwd_pun_enabled_node_count": int(action_threshold_rwd_pun_enabled_node_count),
        "action_learning_threshold_delta_mean": round(float(sum(action_threshold_delta_vals) / len(action_threshold_delta_vals)) if action_threshold_delta_vals else 0.0, 8),
        "action_learning_threshold_delta_sum": round(float(sum(action_threshold_delta_vals)) if action_threshold_delta_vals else 0.0, 8),
        "action_learning_reward_drive_gain_total": round(float(action_learning_reward_drive_gain_total), 8),
        "action_learning_punish_drive_penalty_total": round(float(action_learning_punish_drive_penalty_total), 8),
        "action_local_drive_scale_mean": round(float(sum(action_local_drive_scale_vals) / len(action_local_drive_scale_vals)) if action_local_drive_scale_vals else 1.0, 8),
        "action_local_drive_modulated_node_count": int(action_local_drive_modulated_node_count),
        "action_local_targeted_node_count": int(action_local_targeted_node_count),
        "action_local_lookup_hit_count": int(action_local_lookup_hit_count),
        "action_local_lookup_text_fallback_hit_count": int(action_local_lookup_text_fallback_hit_count),
        "action_local_lookup_miss_count": int(action_local_lookup_miss_count),
        "action_local_lookup_skipped_count": int(action_local_lookup_skipped_count),
        "action_local_target_missing_count": int(action_local_target_missing_count),
        "action_local_modulation_disabled_count": int(action_local_modulation_disabled_count),
        "action_local_reward_drive_bonus_total": round(float(action_local_reward_drive_bonus_total), 8),
        "action_local_punish_drive_penalty_total": round(float(action_local_punish_drive_penalty_total), 8),
        "action_local_reward_signal_total": round(float(action_local_reward_signal_total), 8),
        "action_local_punish_signal_total": round(float(action_local_punish_signal_total), 8),
        "action_local_zero_signal_hit_count": int(action_local_zero_signal_hit_count),
        "action_local_text_fallback_zero_signal_hit_count": int(action_local_text_fallback_zero_signal_hit_count),
        **action_local_kind_metrics,
        "action_node_weather_stub_count": int(action_node_kind_counts.get("weather_stub", 0)),
        "action_active_weather_stub_count": int(action_active_kind_counts.get("weather_stub", 0)),
        "action_ready_weather_stub_count": int(action_ready_kind_counts.get("weather_stub", 0)),
        "action_drive_weather_stub_max": round(float(max(action_drive_kind_vals.get("weather_stub", [0.0]))), 8),
        "action_drive_weather_stub_mean": round(
            float(sum(action_drive_kind_vals.get("weather_stub", [])) / len(action_drive_kind_vals.get("weather_stub", [])))
            if action_drive_kind_vals.get("weather_stub")
            else 0.0,
            8,
        ),
        "action_effective_threshold_weather_stub_mean": round(
            float(
                sum(action_threshold_kind_vals.get("weather_stub", []))
                / len(action_threshold_kind_vals.get("weather_stub", []))
            )
            if action_threshold_kind_vals.get("weather_stub")
            else 0.0,
            8,
        ),
        "action_drive_margin_weather_stub_max": round(
            float(max(action_margin_kind_vals.get("weather_stub", [0.0]))),
            8,
        ),
        "action_drive_margin_weather_stub_mean": round(
            float(sum(action_margin_kind_vals.get("weather_stub", [])) / len(action_margin_kind_vals.get("weather_stub", [])))
            if action_margin_kind_vals.get("weather_stub")
            else 0.0,
            8,
        ),
        # performance / observability
        "timing_total_logic_ms": _as_float(timing.get("total_logic_ms", steps_ms.get("total_logic_ms", 0.0))),
        "timing_sensor_ms": _as_float(steps_ms.get("sensor_ms", 0.0)),
        "timing_maintenance_ms": _as_float(steps_ms.get("maintenance_ms", 0.0)),
        "timing_maintenance_before_summary_ms": _as_float(maintenance_timing.get("before_summary_ms", 0.0)),
        "timing_maintenance_pool_maintenance_ms": _as_float(maintenance_timing.get("pool_maintenance_ms", 0.0)),
        "timing_maintenance_after_summary_ms": _as_float(maintenance_timing.get("after_summary_ms", 0.0)),
        "timing_maintenance_history_events_ms": _as_float(maintenance_timing.get("history_events_ms", 0.0)),
        "timing_cognitive_stitching_ms": _as_float(steps_ms.get("cognitive_stitching_ms", 0.0)),
        "timing_attention_ms": _as_float(steps_ms.get("attention_ms", 0.0)),
        "timing_structure_level_ms": _as_float(steps_ms.get("structure_level_ms", 0.0)),
        "timing_cache_neutralization_ms": _as_float(steps_ms.get("cache_neutralization_ms", 0.0)),
        "timing_stimulus_level_ms": _as_float(steps_ms.get("stimulus_level_ms", 0.0)),
        "timing_pool_apply_ms": _as_float(steps_ms.get("pool_apply_ms", 0.0)),
        "timing_runtime_residual_promotion_ms": _as_float(steps_ms.get("runtime_residual_promotion_ms", 0.0)),
        "timing_event_grasp_ms": _as_float(steps_ms.get("event_grasp_ms", 0.0)),
        "timing_induction_and_memory_ms": _as_float(steps_ms.get("induction_and_memory_ms", 0.0)),
        "timing_induction_source_snapshot_ms": _as_float(steps_ms.get("induction_source_snapshot_ms", 0.0)),
        "timing_induction_hdb_propagation_ms": _as_float(steps_ms.get("induction_hdb_propagation_ms", 0.0)),
        "timing_induction_projection_prepare_ms": _as_float(steps_ms.get("induction_projection_prepare_ms", 0.0)),
        "timing_induction_source_consumption_ms": _as_float(steps_ms.get("induction_source_consumption_ms", 0.0)),
        "timing_induction_target_apply_ms": _as_float(steps_ms.get("induction_target_apply_ms", 0.0)),
        "timing_memory_seed_collect_ms": _as_float(steps_ms.get("memory_seed_collect_ms", 0.0)),
        "timing_memory_activation_apply_ms": _as_float(steps_ms.get("memory_activation_apply_ms", 0.0)),
        "timing_memory_runtime_projection_ms": _as_float(steps_ms.get("memory_runtime_projection_ms", 0.0)),
        "timing_memory_activation_snapshot_ms": _as_float(steps_ms.get("memory_activation_snapshot_ms", 0.0)),
        "timing_memory_feedback_apply_ms": _as_float(steps_ms.get("memory_feedback_apply_ms", 0.0)),
        "timing_time_sensor_ms": _as_float(steps_ms.get("time_sensor_ms", 0.0)),
        # time sensor observability (used by adaptive tuning)
        "time_sensor_bucket_update_count": len([x for x in ts_bucket_updates if isinstance(x, dict)]),
        "time_sensor_bucket_energy_sum": round(float(ts_bucket_energy_sum), 8),
        "time_sensor_bucket_energy_max": round(float(ts_bucket_energy_max), 8),
        "time_sensor_attribute_binding_count": len([x for x in ts_attr_bindings if isinstance(x, dict)]),
        "time_sensor_projection_binding_count": _as_int(ts_attr_source_counts.get("projection_peak", 0))
        + _as_int(ts_attr_source_counts.get("runtime_projection_peak", 0)),
        "time_sensor_legacy_binding_count": _as_int(ts_attr_source_counts.get("legacy_peak", 0)),
        "time_sensor_memory_used_count": _as_int(time_sensor.get("memory_used_count", 0)),
        "time_sensor_memory_sample_count": _as_int(time_sensor.get("memory_used_count", 0)),
        "time_sensor_delayed_task_table_size": _as_int(ts_delayed_tasks.get("table_size", 0)),
        "time_sensor_delayed_task_executed_count": _as_int(ts_delayed_tasks.get("executed_count", 0)),
        "time_sensor_delayed_task_registered_count": _as_int(ts_delayed_registered.get("registered_count", 0)),
        "time_sensor_delayed_task_updated_count": _as_int(ts_delayed_registered.get("updated_count", 0)),
        "time_sensor_delayed_task_pruned_count": _as_int(ts_delayed_registered.get("pruned_count", 0)),
        "time_sensor_delayed_task_skipped_capacity_count": _as_int(ts_delayed_registered.get("skipped", {}).get("capacity", 0) if isinstance(ts_delayed_registered.get("skipped"), dict) else 0),
        "time_sensor_delayed_task_capacity_skip_count": _as_int(ts_delayed_registered.get("skipped", {}).get("capacity", 0) if isinstance(ts_delayed_registered.get("skipped"), dict) else 0),
        "timing_teacher_feedback_ms": _as_float(steps_ms.get("teacher_feedback_ms", 0.0)),
        "timing_cfs_ms": _as_float(steps_ms.get("cfs_ms", 0.0)),
        "timing_iesm_ms": _as_float(steps_ms.get("iesm_ms", 0.0)),
        "timing_emotion_ms": _as_float(steps_ms.get("emotion_ms", 0.0)),
        "timing_action_ms": _as_float(steps_ms.get("action_ms", 0.0)),
        "timing_action_recall_side_effect_ms": _as_float(steps_ms.get("action_recall_side_effect_ms", 0.0)),
        "timing_reward_action_runtime_sync_ms": _as_float(steps_ms.get("reward_action_runtime_sync_ms", 0.0)),
        "timing_final_snapshot_ms": _as_float(steps_ms.get("final_snapshot_ms", 0.0)),
        "timing_energy_balance_ms": _as_float(steps_ms.get("energy_balance_ms", 0.0)),
    }

    # Dynamic per-action_kind counters
    # ------------------------------------------------------------
    # 说明：
    # - 期望契约（Expectation Contracts）支持条件 kind=action_executed_kind_min，它会在 metrics 里读取
    #   `action_executed_{action_kind}_source_visible`（兼容回退到 `action_executed_{action_kind}`）这种动态键。
    # - 因此这里必须把“所有出现过的 action_kind”都输出出来，而不能只输出固定白名单。
    # - 同理，`action_attempted_{action_kind}` 便于调试“哪些行动在频繁尝试但长期失败”。
    for kind, count in attempted_kind_counts.items():
        k = str(kind).strip()
        if not k:
            continue
        record[f"action_attempted_{k}"] = int(count)
        record[f"action_attempted_{k}_source_visible"] = int(attempted_kind_counts_source_visible.get(k, 0))
        record[f"action_attempted_{k}_synthetic_only"] = int(attempted_kind_counts_synthetic_only.get(k, 0))
    for kind, count in scheduled_kind_counts.items():
        k = str(kind).strip()
        if not k:
            continue
        record[f"action_scheduled_{k}"] = int(count)
        record[f"action_scheduled_{k}_source_visible"] = int(scheduled_kind_counts_source_visible.get(k, 0))
        record[f"action_scheduled_{k}_synthetic_only"] = int(scheduled_kind_counts_synthetic_only.get(k, 0))
    for kind, count in executed_kind_counts.items():
        k = str(kind).strip()
        if not k:
            continue
        record[f"action_executed_{k}"] = int(count)
        record[f"action_executed_{k}_source_visible"] = int(executed_kind_counts_source_visible.get(k, 0))
        record[f"action_executed_{k}_synthetic_only"] = int(executed_kind_counts_synthetic_only.get(k, 0))
    for kind, count in action_node_kind_counts.items():
        k = str(kind).strip()
        if not k:
            continue
        drives = action_drive_kind_vals.get(k, [])
        thresholds = action_threshold_kind_vals.get(k, [])
        margins = action_margin_kind_vals.get(k, [])
        record[f"action_node_{k}_count"] = int(count)
        record[f"action_active_{k}_count"] = int(action_active_kind_counts.get(k, 0))
        record[f"action_ready_{k}_count"] = int(action_ready_kind_counts.get(k, 0))
        record[f"action_drive_{k}_max"] = round(float(max(drives) if drives else 0.0), 8)
        record[f"action_drive_{k}_mean"] = round(float(sum(drives) / len(drives)) if drives else 0.0, 8)
        record[f"action_effective_threshold_{k}_mean"] = round(
            float(sum(thresholds) / len(thresholds)) if thresholds else 0.0,
            8,
        )
        record[f"action_drive_margin_{k}_max"] = round(float(max(margins) if margins else 0.0), 8)
        record[f"action_drive_margin_{k}_mean"] = round(float(sum(margins) / len(margins)) if margins else 0.0, 8)
    for kind, count in iesm_action_trigger_kind_counts.items():
        k = str(kind).strip()
        if not k:
            continue
        record[f"iesm_action_trigger_{k}_count"] = int(count)
        record[f"iesm_action_trigger_{k}_count_source_visible"] = int(iesm_action_trigger_kind_counts_source_visible.get(k, 0))
        record[f"iesm_action_trigger_{k}_count_synthetic_only"] = int(iesm_action_trigger_kind_counts_synthetic_only.get(k, 0))
    for kind, count in iesm_action_trigger_targeted_kind_counts.items():
        k = str(kind).strip()
        if not k:
            continue
        record[f"iesm_action_trigger_targeted_{k}_count"] = int(count)
        record[f"iesm_action_trigger_targeted_{k}_count_source_visible"] = int(
            iesm_action_trigger_targeted_kind_counts_source_visible.get(k, 0)
        )
        record[f"iesm_action_trigger_targeted_{k}_count_synthetic_only"] = int(
            iesm_action_trigger_targeted_kind_counts_synthetic_only.get(k, 0)
        )
    for kind, count in iesm_action_trigger_target_missing_kind_counts.items():
        k = str(kind).strip()
        if not k:
            continue
        record[f"iesm_action_trigger_target_missing_{k}_count"] = int(count)
        record[f"iesm_action_trigger_target_missing_{k}_count_source_visible"] = int(
            iesm_action_trigger_target_missing_kind_counts_source_visible.get(k, 0)
        )
        record[f"iesm_action_trigger_target_missing_{k}_count_synthetic_only"] = int(
            iesm_action_trigger_target_missing_kind_counts_synthetic_only.get(k, 0)
        )
    for rule_id, count in iesm_triggered_rule_counts.items():
        rid = str(rule_id).strip()
        if not rid:
            continue
        record[f"iesm_triggered_rule_{rid}_count"] = int(count)
        record[f"iesm_triggered_rule_{rid}_count_source_visible"] = int(iesm_triggered_rule_counts_source_visible.get(rid, 0))
        record[f"iesm_triggered_rule_{rid}_count_synthetic_only"] = int(iesm_triggered_rule_counts_synthetic_only.get(rid, 0))
    for rule_id, count in iesm_action_trigger_rule_counts.items():
        rid = str(rule_id).strip()
        if not rid:
            continue
        record[f"iesm_action_trigger_rule_{rid}_count"] = int(count)
        record[f"iesm_action_trigger_rule_{rid}_count_source_visible"] = int(iesm_action_trigger_rule_counts_source_visible.get(rid, 0))
        record[f"iesm_action_trigger_rule_{rid}_count_synthetic_only"] = int(iesm_action_trigger_rule_counts_synthetic_only.get(rid, 0))
    for channel_code in _EMOTION_CHANNEL_CODES:
        delta_value = round(float(iesm_emotion_update_values.get(channel_code, 0.0)), 8)
        record[f"iesm_emotion_update_{channel_code}"] = delta_value
        record[f"iesm_emotion_update_{channel_code}_source_visible"] = round(float(0.0 if tick_is_synthetic else delta_value), 8)
        record[f"iesm_emotion_update_{channel_code}_synthetic_only"] = round(float(delta_value if tick_is_synthetic else 0.0), 8)

    # Flatten core CFS kinds for charting
    for kind in CORE_CFS_KINDS:
        record[f"cfs_{kind}_max"] = round(float(cfs_max_by_kind.get(kind, 0.0) or 0.0), 8)
        record[f"cfs_{kind}_count"] = int(cfs_count_by_kind.get(kind, 0) or 0)

    # Live-state CFS / runtime feedback
    # ------------------------------------------------------------
    # Bound-attribute part comes from StatePool snapshot summary aggregation:
    #   summary.bound_attribute_energy_totals[attribute_name]
    # and reflects *maintained* state with half-life decay, not just tick-level peaks.
    #
    # For reward/punish global signals, the theory-aligned default chain also
    # injects first-class runtime SA nodes (`reward_signal` / `punish_signal`).
    # Those are not bound attributes, so we merge the runtime sync payload below
    # to avoid reporting a false zero when the global signal exists as a
    # standalone state-pool object.
    bound_totals = snapshot_summary.get("bound_attribute_energy_totals", {})
    if not isinstance(bound_totals, dict):
        bound_totals = {}
    for attr_name in CORE_CFS_BOUND_ATTRS:
        _flatten_bound_attr_row(record, metric_name=attr_name, row=bound_totals.get(attr_name, {}))

    for attr_name in CORE_RUNTIME_FEEDBACK_BOUND_ATTRS:
        _flatten_bound_attr_row(record, metric_name=attr_name, row=bound_totals.get(attr_name, {}))

    _merge_runtime_feedback_signal_rows(record, runtime_sync=_as_dict(report.get("reward_action_runtime_sync")))

    for metric_name, prefix in BOUND_ATTRIBUTE_FAMILY_PREFIXES.items():
        _flatten_bound_attr_row(record, metric_name=metric_name, row=_sum_bound_attr_family(bound_totals, prefix=prefix))

    for kind, attr_name in CFS_KIND_TO_BOUND_ATTR.items():
        live_total_energy = float(record.get(f"{attr_name}_live_total_energy", 0.0) or 0.0)
        live_item_count = int(record.get(f"{attr_name}_live_item_count", 0) or 0)
        live_attribute_count = int(record.get(f"{attr_name}_live_attribute_count", 0) or 0)
        live_active = int(live_total_energy > 0.000001 or live_item_count > 0 or live_attribute_count > 0)
        emitted_count = int(record.get(f"cfs_{kind}_count", 0) or 0)
        record[f"cfs_{kind}_live_active"] = live_active
        record[f"cfs_{kind}_decay_only"] = int(live_active > 0 and emitted_count <= 0)

    # Optional labels pass-through (if present) for later specialized plots.
    labels = dt.get("labels")
    if isinstance(labels, dict) and labels:
        record["labels"] = dict(labels)

        # Common teacher/external feedback labels (paper-friendly flat fields).
        teacher = labels.get("teacher") if isinstance(labels.get("teacher"), dict) else {}
        tr = labels.get("teacher_rwd", teacher.get("rwd", labels.get("tool_feedback_rwd", 0.0)))
        tp = labels.get("teacher_pun", teacher.get("pun", labels.get("tool_feedback_pun", 0.0)))
        record["label_teacher_rwd"] = _as_float(tr, 0.0)
        record["label_teacher_pun"] = _as_float(tp, 0.0)
        record["label_should_call_weather"] = _as_int(labels.get("should_call_weather", labels.get("tool_should_call_weather", 0)), 0)

    # Teacher feedback apply result (from report, after clamping + anchor resolution).
    tfb = _as_dict(report.get("teacher_feedback"))
    record["teacher_rwd"] = _as_float(tfb.get("teacher_rwd", 0.0))
    record["teacher_pun"] = _as_float(tfb.get("teacher_pun", 0.0))
    record["teacher_applied_count"] = _as_int(tfb.get("applied_count", 0))
    record["teacher_total_binding_applied_count"] = _as_int(
        tfb.get("total_binding_applied_count", tfb.get("applied_count", 0))
    )
    record["teacher_primary_target_atomic"] = int(bool(tfb.get("primary_target_atomic", False)))
    record["teacher_context_binding_enabled"] = int(bool(tfb.get("context_binding_enabled", False)))
    record["teacher_context_binding_candidate_count"] = _as_int(tfb.get("context_binding_candidate_count", 0))
    record["teacher_context_binding_applied_count"] = _as_int(tfb.get("context_binding_applied_count", 0))
    teacher_focus_directives = [row for row in _as_list(tfb.get("focus_directives")) if isinstance(row, dict)]
    record["teacher_focus_directive_enabled"] = int(bool(tfb.get("focus_directive_enabled", False)))
    record["teacher_focus_directive_count"] = _as_int(tfb.get("focus_directive_count", len(teacher_focus_directives)))
    record["teacher_focus_context_carrier_count"] = _as_int(tfb.get("focus_context_carrier_count", 0))
    record["teacher_focus_directive_total_strength"] = round(
        sum(_as_float(row.get("strength", 0.0)) for row in teacher_focus_directives),
        8,
    )
    record["teacher_focus_directive_max_focus_boost"] = round(
        max((_as_float(row.get("focus_boost", 0.0)) for row in teacher_focus_directives), default=0.0),
        8,
    )
    record["teacher_focus_directive_ttl_max"] = max((_as_int(row.get("ttl_ticks", 0)) for row in teacher_focus_directives), default=0)

    teacher_alias = _as_dict(report.get("teacher_local_feedback_alias_cache"))
    record["teacher_local_alias_enabled"] = int(bool(teacher_alias.get("enabled", False)))
    record["teacher_local_alias_active_count"] = _as_int(teacher_alias.get("active_count", 0))
    record["teacher_local_alias_available_count"] = _as_int(teacher_alias.get("available_count", 0))
    record["teacher_local_alias_matched_count"] = _as_int(teacher_alias.get("matched_count", 0))
    record["teacher_local_alias_overlay_applied_count"] = _as_int(teacher_alias.get("overlay_applied_count", 0))
    record["teacher_local_alias_overlay_rwd"] = _as_float(teacher_alias.get("overlay_rwd", 0.0))
    record["teacher_local_alias_overlay_pun"] = _as_float(teacher_alias.get("overlay_pun", 0.0))
    record["teacher_local_alias_overlay_match_score"] = _as_float(teacher_alias.get("overlay_match_score", 0.0))

    return record

