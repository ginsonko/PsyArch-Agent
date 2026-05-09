# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from attention.main import AttentionFilter


class _DummyPool:
    def __init__(self, items):
        self._items = items

    def get_state_snapshot(self, *, trace_id: str, tick_id: str | None = None, top_k=None):
        return {
            "success": True,
            "data": {
                "snapshot": {
                    "summary": {"active_item_count": len(self._items)},
                    "top_items": list(self._items),
                }
            },
        }

    def apply_energy_update(self, **kwargs):
        return {"success": True, "data": {"after": {"er": 0.0, "ev": 0.0}}}


def _row(
    *,
    item_id: str,
    ref_object_id: str,
    ref_object_type: str,
    er: float,
    ev: float,
    cp_abs: float | None = None,
    ref_snapshot=None,
    extra=None,
):
    row = {
        "item_id": item_id,
        "ref_object_id": ref_object_id,
        "ref_object_type": ref_object_type,
        "display": ref_object_id,
        "er": float(er),
        "ev": float(ev),
        "cp_abs": float(cp_abs if cp_abs is not None else abs(er - ev)),
        "salience_score": max(float(er), float(ev)),
        "fatigue": 0.0,
        "recency_gain": 1.0,
        "updated_at": 1,
        "ref_snapshot": dict(ref_snapshot or {}),
        "ref_alias_ids": [],
        "runtime_attribute_names": [],
        "packet_attribute_names": [],
        "all_attribute_names": [],
        "bound_attribute_names": [],
        "runtime_bound_attribute_units": [],
    }
    if isinstance(extra, dict):
        row.update(extra)
    return row


def test_reward_action_priority_prefers_structure_carriers_and_penalizes_bare_special_nodes():
    attention = AttentionFilter(
        config_override={
            "top_n": 8,
            "consume_energy": False,
            "reward_action_humanlike_v2_enabled": True,
            "reward_action_priority_enabled": True,
            "reward_action_structure_first_mode": True,
        }
    )

    items = [
        _row(
            item_id="spi_reward",
            ref_object_id="reward_signal",
            ref_object_type="sa",
            er=0.0,
            ev=0.6,
            ref_snapshot={
                "content_display": "reward_signal:0.6",
                "role": "attribute",
                "attribute_name": "reward_signal",
                "attribute_value": 0.6,
            },
            extra={
                "role": "attribute",
                "attribute_name": "reward_signal",
                "attribute_value": 0.6,
            },
        ),
        _row(
            item_id="spi_action",
            ref_object_id="action::act_weather",
            ref_object_type="action_node",
            er=0.2,
            ev=0.5,
            ref_snapshot={
                "content_display": "行动节点:天气查询",
                "target_ref_object_id": "st_weather",
                "target_ref_object_type": "st",
                "target_display": "天气",
            },
        ),
        _row(
            item_id="spi_weather",
            ref_object_id="st_weather",
            ref_object_type="st",
            er=0.25,
            ev=0.25,
            ref_snapshot={
                "content_display": "天气",
                "token_count": 2,
                "feature_displays": ["天气"],
            },
            extra={
                "runtime_attribute_names": ["reward_signal"],
                "all_attribute_names": ["reward_signal"],
                "bound_attribute_names": ["reward_signal"],
                "runtime_bound_attribute_units": [{"attribute_name": "reward_signal", "attribute_value": 0.8}],
            },
        ),
        _row(
            item_id="spi_neutral",
            ref_object_id="st_neutral",
            ref_object_type="st",
            er=0.25,
            ev=0.25,
            ref_snapshot={"content_display": "普通结构", "token_count": 2, "feature_displays": ["普通结构"]},
        ),
    ]
    pool = _DummyPool(items)

    reward_action_context = attention._build_reward_action_context(items)
    reward_bonus = attention._compute_reward_action_bonus(items[0], reward_action_context)
    action_bonus = attention._compute_reward_action_bonus(items[1], reward_action_context)
    weather_bonus = attention._compute_reward_action_bonus(items[2], reward_action_context)
    neutral_bonus = attention._compute_reward_action_bonus(items[3], reward_action_context)

    assert reward_bonus["bonus"] < 0.0
    assert reward_bonus["is_special_standalone"] is True
    assert action_bonus["bonus"] < 0.0
    assert weather_bonus["bonus"] > 0.0
    assert weather_bonus["is_structure_carrier"] is True
    assert neutral_bonus["bonus"] == 0.0

    result = attention.build_cam_from_pool(pool, trace_id="pytest_reward_action_priority", tick_id="cycle_0001")
    assert result["success"] is True

    report = result["data"]["attention_report"]
    top_items = report["top_items"]
    by_ref = {str(row.get("ref_object_id", "")): row for row in top_items}

    assert report["reward_action_context"]["signal_item_count"] == 1
    assert report["reward_action_context"]["action_node_count"] == 1
    assert report["reward_action_structure_carrier_selected_count"] >= 1
    assert float(by_ref["st_weather"]["reward_action_bonus"]) > float(by_ref["st_neutral"]["reward_action_bonus"])
    assert float(by_ref["st_weather"]["attention_priority"]) > float(by_ref["st_neutral"]["attention_priority"])


def test_reward_action_priority_penalizes_standalone_attribute_signal_sa_under_new_runtime_mode():
    attention = AttentionFilter(
        config_override={
            "top_n": 8,
            "consume_energy": False,
            "reward_action_humanlike_v2_enabled": True,
            "reward_action_priority_enabled": True,
            "reward_action_structure_first_mode": True,
        }
    )

    items = [
        _row(
            item_id="spi_attr_reward_signal",
            ref_object_id="sa_attr_reward_signal_runtime",
            ref_object_type="sa",
            er=0.1,
            ev=0.7,
            ref_snapshot={
                "content_display": "奖励信号:0.8",
                "role": "attribute",
                "attribute_name": "reward_signal",
                "attribute_value": 0.8,
                "value_type": "numerical",
            },
            extra={
                "role": "attribute",
                "attribute_name": "reward_signal",
                "attribute_value": 0.8,
            },
        ),
    ]

    reward_action_context = attention._build_reward_action_context(items)
    bonus = attention._compute_reward_action_bonus(items[0], reward_action_context)

    assert bonus["direct_signal_name"] == "reward_signal"
    assert bonus["matched_signal_values"]["reward_signal"] == 0.8
    assert bonus["is_special_standalone"] is True
    assert bonus["is_structure_carrier"] is False
    assert bonus["bonus"] < 0.0


def test_repeat_attention_fatigue_penalizes_immediate_reselection_and_recovers_when_skipped():
    attention = AttentionFilter(
        config_override={
            "top_n": 4,
            "consume_energy": False,
            "attention_repeat_fatigue_enabled": True,
            "attention_repeat_fatigue_penalty_gain": 0.5,
            "attention_repeat_fatigue_recovery_per_call": 0.5,
            "attention_repeat_fatigue_selected_gain": 1.0,
        }
    )

    pool_ab = _DummyPool(
        [
            _row(item_id="spi_a", ref_object_id="st_a", ref_object_type="st", er=0.5, ev=0.4, ref_snapshot={"content_display": "A", "token_count": 2}),
            _row(item_id="spi_b", ref_object_id="st_b", ref_object_type="st", er=0.45, ev=0.35, ref_snapshot={"content_display": "B", "token_count": 2}),
        ]
    )
    pool_bc = _DummyPool(
        [
            _row(item_id="spi_b2", ref_object_id="st_b", ref_object_type="st", er=0.55, ev=0.35, ref_snapshot={"content_display": "B", "token_count": 2}),
            _row(item_id="spi_c", ref_object_id="st_c", ref_object_type="st", er=0.52, ev=0.32, ref_snapshot={"content_display": "C", "token_count": 2}),
        ]
    )

    first = attention.build_cam_from_pool(pool_ab, trace_id="pytest_repeat_attention_1", tick_id="cycle_0001")
    assert first["success"] is True
    first_by_ref = {str(row.get("ref_object_id", "")): row for row in first["data"]["attention_report"]["top_items"]}
    assert float(first_by_ref["st_a"]["repeat_attention_penalty"]) == 0.0

    second = attention.build_cam_from_pool(pool_ab, trace_id="pytest_repeat_attention_2", tick_id="cycle_0002")
    assert second["success"] is True
    second_by_ref = {str(row.get("ref_object_id", "")): row for row in second["data"]["attention_report"]["top_items"]}
    second_penalty = float(second_by_ref["st_a"]["repeat_attention_penalty"])
    assert second_penalty > 0.0

    third = attention.build_cam_from_pool(pool_bc, trace_id="pytest_repeat_attention_3", tick_id="cycle_0003")
    assert third["success"] is True

    fourth = attention.build_cam_from_pool(pool_ab, trace_id="pytest_repeat_attention_4", tick_id="cycle_0004")
    assert fourth["success"] is True
    fourth_by_ref = {str(row.get("ref_object_id", "")): row for row in fourth["data"]["attention_report"]["top_items"]}
    fourth_penalty = float(fourth_by_ref["st_a"]["repeat_attention_penalty"])
    assert fourth_penalty > 0.0
    assert fourth_penalty < second_penalty
