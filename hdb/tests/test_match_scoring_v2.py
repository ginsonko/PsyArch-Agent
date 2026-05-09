# -*- coding: utf-8 -*-

from hdb._match_scoring_v2 import build_match_score_v2
from hdb._stimulus_retrieval import StimulusRetrievalEngine


def _config(**extra):
    base = {
        "match_scoring_v2_base_weight": 0.42,
        "match_scoring_v2_numeric_weight": 0.16,
        "match_scoring_v2_order_weight": 0.16,
        "match_scoring_v2_attribute_weight": 0.12,
        "match_scoring_v2_context_weight": 0.07,
        "match_scoring_v2_energy_weight": 0.07,
        "match_scoring_v2_inclusion_weight": 0.08,
        "match_scoring_v2_half_ratio": 0.14,
        "match_scoring_v2_curve_power": 1.25,
        "match_scoring_v2_noise_mid": 0.02,
        "match_scoring_v2_noise_scale": 0.01,
        "match_scoring_v2_min_score": 0.18,
        "numeric_match_abs_tolerance": 0.2,
        "numeric_match_rel_tolerance": 0.35,
        "match_scoring_v2_enabled": True,
        "match_scoring_v2_shadow_only": False,
        "match_scoring_v2_blend_weight": 0.35,
    }
    base.update(extra)
    return base


def _attribute_unit(name: str, value: float, *, sequence_index: int = 0, group_index: int = 0) -> dict:
    return {
        "unit_id": f"attr_{name}_{sequence_index}_{group_index}",
        "unit_role": "attribute",
        "attribute_name": name,
        "attribute_value": value,
        "sequence_index": sequence_index,
        "group_index": group_index,
        "er": 0.4,
        "ev": 0.1,
    }


def _time_attribute_unit(value: float, *, sequence_index: int = 0, group_index: int = 0) -> dict:
    return {
        **_attribute_unit("时间感受", value, sequence_index=sequence_index, group_index=group_index),
        "meta": {
            "ext": {
                "time_bucket_id": f"tb_{sequence_index}_{group_index}",
                "time_bucket_center_sec": float(value),
                "time_basis": "tick",
                "delta_value": float(value),
            }
        },
    }


def _feature_unit(token: str, *, sequence_index: int, group_index: int = 0) -> dict:
    return {
        "unit_id": f"feature_{token}_{sequence_index}_{group_index}",
        "unit_role": "feature",
        "token": token,
        "display_text": token,
        "sequence_index": sequence_index,
        "group_index": group_index,
        "er": 0.3,
        "ev": 0.2,
    }


def test_match_scoring_v2_prefers_closer_numeric_values():
    existing = [_attribute_unit("压力", 1.0)]
    incoming_near = [_attribute_unit("压力", 1.05)]
    incoming_far = [_attribute_unit("压力", 1.6)]

    near = build_match_score_v2(
        config=_config(),
        base_score=0.35,
        matched_existing_units=existing,
        matched_incoming_units=incoming_near,
    )
    far = build_match_score_v2(
        config=_config(),
        base_score=0.35,
        matched_existing_units=existing,
        matched_incoming_units=incoming_far,
    )

    assert near["numeric_score"] > far["numeric_score"]
    assert near["score"] > far["score"]


def test_match_scoring_v2_numeric_score_survives_position_shift():
    existing = [
        _feature_unit("计划", sequence_index=0),
        _attribute_unit("压力", 1.0, sequence_index=1),
    ]
    incoming = [
        _attribute_unit("压力", 1.02, sequence_index=0),
        _feature_unit("计划", sequence_index=1),
    ]

    shifted = build_match_score_v2(
        config=_config(),
        base_score=0.35,
        matched_existing_units=existing,
        matched_incoming_units=incoming,
    )

    assert shifted["numeric_score"] > 0.9


def test_match_scoring_v2_numeric_score_penalizes_missing_numeric_family_coverage():
    existing = [
        _attribute_unit("压力", 1.0, sequence_index=0),
        _attribute_unit("期待", 0.8, sequence_index=1),
    ]
    incoming_partial = [
        _attribute_unit("压力", 1.0, sequence_index=0),
    ]
    incoming_full = [
        _attribute_unit("压力", 1.0, sequence_index=0),
        _attribute_unit("期待", 0.8, sequence_index=1),
    ]

    partial = build_match_score_v2(
        config=_config(),
        base_score=0.35,
        matched_existing_units=existing,
        matched_incoming_units=incoming_partial,
    )
    full = build_match_score_v2(
        config=_config(),
        base_score=0.35,
        matched_existing_units=existing,
        matched_incoming_units=incoming_full,
    )

    assert 0.0 <= partial["numeric_score"] < full["numeric_score"] <= 1.0


def test_match_scoring_v2_prefers_better_order_alignment():
    existing = [
        _feature_unit("你", sequence_index=0),
        _feature_unit("好", sequence_index=1),
    ]
    incoming_aligned = [
        _feature_unit("你", sequence_index=0),
        _feature_unit("好", sequence_index=1),
    ]
    incoming_shifted = [
        _feature_unit("你", sequence_index=2),
        _feature_unit("好", sequence_index=3),
    ]

    aligned = build_match_score_v2(
        config=_config(),
        base_score=0.42,
        matched_existing_units=existing,
        matched_incoming_units=incoming_aligned,
    )
    shifted = build_match_score_v2(
        config=_config(),
        base_score=0.42,
        matched_existing_units=existing,
        matched_incoming_units=incoming_shifted,
    )

    assert aligned["order_alignment_score"] > shifted["order_alignment_score"]
    assert aligned["score"] > shifted["score"]


def test_match_scoring_v2_surfaces_time_like_numeric_contribution():
    existing = [
        _feature_unit("计划", sequence_index=0),
        _time_attribute_unit(2.0, sequence_index=1),
    ]
    incoming_near = [
        _feature_unit("计划", sequence_index=0),
        _time_attribute_unit(2.1, sequence_index=1),
    ]
    incoming_far = [
        _feature_unit("计划", sequence_index=0),
        _time_attribute_unit(6.0, sequence_index=1),
    ]

    near = build_match_score_v2(
        config=_config(),
        base_score=0.4,
        matched_existing_units=existing,
        matched_incoming_units=incoming_near,
    )
    far = build_match_score_v2(
        config=_config(),
        base_score=0.4,
        matched_existing_units=existing,
        matched_incoming_units=incoming_far,
    )

    assert near["numeric_time_like_family_count"] == 1
    assert near["numeric_time_like_score"] > 0.0
    assert near["numeric_time_like_score"] >= near["numeric_score"] - 1e-8
    assert near["numeric_time_like_score"] > far["numeric_time_like_score"]
    assert near["score"] > far["score"]


def test_match_scoring_v2_time_factor_soft_bonus_prefers_interval_close_memory():
    now_ms = 10_000
    existing = [
        _feature_unit("天气动作", sequence_index=0),
        _time_attribute_unit(2.0, sequence_index=1),
    ]
    incoming_near = [
        _feature_unit("天气动作", sequence_index=0),
        _time_attribute_unit(2.0, sequence_index=1),
    ]
    incoming_far = [
        _feature_unit("天气动作", sequence_index=0),
        _time_attribute_unit(6.0, sequence_index=1),
    ]
    context_payload = {
        "object_type": "em",
        "ext": {
            "source_em_id": "em_weather_1",
            "source_memory_created_at": now_ms - 2000,
            "residual_origin_kind": "memory_runtime_projection",
        },
    }

    near = build_match_score_v2(
        config=_config(time_factor_soft_bonus_enabled=True),
        base_score=0.4,
        matched_existing_units=existing,
        matched_incoming_units=incoming_near,
        context_payload=context_payload,
        now_ms=now_ms,
    )
    far = build_match_score_v2(
        config=_config(time_factor_soft_bonus_enabled=True),
        base_score=0.4,
        matched_existing_units=existing,
        matched_incoming_units=incoming_far,
        context_payload=context_payload,
        now_ms=now_ms,
    )

    assert near["time_factor_applied"] is True
    assert near["time_factor_soft_bonus"] > 1.0
    assert near["time_factor_similarity"] > far["time_factor_similarity"]
    assert near["score"] > far["score"]


def test_match_scoring_v2_time_like_can_be_wildcard_for_memory_candidates():
    now_ms = 10_000
    existing = [
        _feature_unit("天气动作", sequence_index=0),
        _time_attribute_unit(2.0, sequence_index=1),
    ]
    incoming = [
        _feature_unit("天气动作", sequence_index=0),
        _time_attribute_unit(6.0, sequence_index=1),
    ]
    context_payload = {
        "object_type": "em",
        "ext": {
            "source_em_id": "em_weather_2",
            "source_memory_created_at": now_ms - 2000,
            "residual_origin_kind": "memory_runtime_projection",
        },
    }

    score = build_match_score_v2(
        config=_config(
            time_factor_soft_bonus_enabled=True,
            time_like_memory_wildcard_enabled=True,
        ),
        base_score=0.4,
        matched_existing_units=existing,
        matched_incoming_units=incoming,
        context_payload=context_payload,
        now_ms=now_ms,
    )

    assert score["numeric_time_like_family_count"] == 1
    assert score["numeric_time_like_wildcard_applied"] is True
    assert score["numeric_score_effective"] == -1.0
    assert score["time_factor_is_memory_candidate"] is True
    assert score["time_factor_target_interval_sec"] == 6.0


def test_match_scoring_v2_respects_soft_component_switches():
    existing = [
        _feature_unit("你", sequence_index=0),
        _attribute_unit("压力", 1.0, sequence_index=1),
    ]
    incoming = [
        _attribute_unit("压力", 1.0, sequence_index=0),
        _feature_unit("你", sequence_index=1),
    ]

    score = build_match_score_v2(
        config=_config(
            unified_numeric_scoring_enabled=False,
            attribute_soft_scoring_enabled=False,
            sequence_soft_scoring_enabled=False,
        ),
        base_score=0.4,
        matched_existing_units=existing,
        matched_incoming_units=incoming,
        bundle_constraints={"exact": True, "existing_included": True, "incoming_included": True},
        full_structure_included=True,
    )

    assert score["numeric_score"] == -1.0
    assert score["order_alignment_score"] == -1.0
    assert score["attribute_anchor_score"] == -1.0


def test_stimulus_blend_score_can_fallback_to_legacy():
    engine = StimulusRetrievalEngine(
        config=_config(match_scoring_v2_enabled=False),
        weight_engine=None,
        logger=None,
        maintenance_engine=None,
    )
    assert engine._blend_v2_match_score(legacy_score=0.2, v2_score=0.8) == 0.2

    engine.update_config(_config(match_scoring_v2_enabled=True, match_scoring_v2_shadow_only=True))
    assert engine._blend_v2_match_score(legacy_score=0.2, v2_score=0.8) == 0.2

    engine.update_config(_config(match_scoring_v2_enabled=True, match_scoring_v2_shadow_only=False, match_scoring_v2_blend_weight=0.25))
    assert engine._blend_v2_match_score(legacy_score=0.2, v2_score=0.8) == 0.35


def test_stimulus_competition_lifts_small_valid_hits_in_long_stimulus():
    engine = StimulusRetrievalEngine(
        config=_config(
            stimulus_competition_noise_mid=0.01,
            stimulus_competition_noise_scale=0.004,
            stimulus_competition_half_ratio=0.1,
            stimulus_competition_curve_power=1.2,
            stimulus_competition_stimulus_ratio_power=0.35,
            stimulus_competition_structure_ratio_power=0.85,
        ),
        weight_engine=None,
        logger=None,
        maintenance_engine=None,
    )

    score = engine._compose_match_score(stimulus_match_ratio=0.12, structure_match_ratio=0.85)

    assert score > 0.5


def test_stimulus_competition_keeps_standalone_attribute_anchor_conservative():
    engine = StimulusRetrievalEngine(
        config=_config(
            stimulus_competition_noise_mid=0.01,
            stimulus_competition_noise_scale=0.004,
            stimulus_competition_half_ratio=0.1,
            stimulus_competition_curve_power=1.2,
            stimulus_competition_stimulus_ratio_power=0.35,
            stimulus_competition_attribute_ratio_power=1.0,
            stimulus_competition_structure_ratio_power=0.85,
        ),
        weight_engine=None,
        logger=None,
        maintenance_engine=None,
    )

    visible_score = engine._compose_match_score(stimulus_match_ratio=0.02, structure_match_ratio=1.0)
    attr_score = engine._compose_match_score(
        stimulus_match_ratio=0.02,
        structure_match_ratio=1.0,
        attribute_anchor_only=True,
    )

    assert visible_score > attr_score
    assert attr_score < 0.3


def test_hidden_attribute_unit_does_not_monopolize_primary_anchor_selection():
    engine = StimulusRetrievalEngine(
        config=_config(
            stimulus_anchor_er_weight=1.25,
            stimulus_anchor_ev_weight=0.9,
            stimulus_anchor_external_bonus=0.08,
            stimulus_anchor_non_punctuation_bonus=0.05,
            stimulus_anchor_hidden_attribute_score_scale=0.22,
            stimulus_anchor_punctuation_penalty=0.35,
        ),
        weight_engine=None,
        logger=None,
        maintenance_engine=None,
    )
    visible = _feature_unit("你好", sequence_index=0)
    visible["source_type"] = "current"
    visible["display_visible"] = True
    visible["er"] = 0.45
    visible["ev"] = 0.0
    hidden_attr = _attribute_unit("stimulus_intensity", 1.1, sequence_index=0)
    hidden_attr["source_type"] = "current"
    hidden_attr["display_visible"] = False
    hidden_attr["token"] = "stimulus_intensity:1.1"
    hidden_attr["er"] = 1.1
    hidden_attr["ev"] = 0.0

    assert engine._anchor_score(visible) > engine._anchor_score(hidden_attr)


def test_owner_residual_anchor_bonus_fades_with_depleted_unit_energy():
    engine = StimulusRetrievalEngine(
        config=_config(
            stimulus_anchor_owner_residual_bonus=0.85,
            stimulus_anchor_owner_residual_bonus_energy_half=0.12,
        ),
        weight_engine=None,
        logger=None,
        maintenance_engine=None,
    )

    low_energy = {"er": 0.01, "ev": 0.0}
    high_energy = {"er": 1.0, "ev": 0.0}
    bonus = 0.85
    half = 0.12

    low_scaled = bonus * ((low_energy["er"] + low_energy["ev"]) / ((low_energy["er"] + low_energy["ev"]) + half))
    high_scaled = bonus * ((high_energy["er"] + high_energy["ev"]) / ((high_energy["er"] + high_energy["ev"]) + half))

    assert low_scaled < 0.08
    assert high_scaled > 0.7


def test_stimulus_transfer_curve_maps_medium_similarity_to_clear_transfer():
    engine = StimulusRetrievalEngine(
        config=_config(
            stimulus_transfer_curve_enabled=True,
            stimulus_transfer_curve_half_score=0.2,
            stimulus_transfer_curve_power=0.45,
            stimulus_transfer_curve_normalize_at_one=True,
        ),
        weight_engine=None,
        logger=None,
        maintenance_engine=None,
    )

    assert engine._effective_transfer_fraction(1.0, 0.3) > 0.5
    assert engine._effective_transfer_fraction(1.0, 0.6) > 0.6
    assert engine._effective_transfer_fraction(1.0, 1.0) == 1.0

    engine.update_config(_config(stimulus_transfer_curve_enabled=False))
    assert engine._effective_transfer_fraction(1.0, 0.3) == 0.3
