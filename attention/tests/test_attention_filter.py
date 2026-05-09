# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from attention import AttentionFilter


class DummyPool:
    def __init__(self, items: list[dict]):
        self._base_items = list(items)
        self._energies: dict[str, dict[str, float]] = {}
        for item in self._base_items:
            self._energies[str(item["item_id"])] = {"er": float(item.get("er", 0.0)), "ev": float(item.get("ev", 0.0))}
        self.apply_calls: list[dict] = []

    def get_state_snapshot(self, *, trace_id: str, tick_id: str, top_k=None, **kwargs) -> dict:
        top_items = []
        for base in self._base_items:
            item_id = str(base["item_id"])
            energy = self._energies[item_id]
            top_items.append({**base, "er": energy["er"], "ev": energy["ev"]})
        return {
            "success": True,
            "code": "OK",
            "data": {
                "snapshot": {
                    "summary": {"active_item_count": len(top_items)},
                    "top_items": top_items,
                }
            },
        }

    def apply_energy_update(
        self,
        *,
        target_item_id: str,
        delta_er: float,
        delta_ev: float,
        trace_id: str,
        tick_id: str,
        reason: str,
        source_module: str,
        **kwargs,
    ) -> dict:
        tid = str(target_item_id)
        before = dict(self._energies[tid])
        after_er = max(0.0, before["er"] + float(delta_er))
        after_ev = max(0.0, before["ev"] + float(delta_ev))
        self._energies[tid] = {"er": after_er, "ev": after_ev}
        self.apply_calls.append(
            {
                "target_item_id": tid,
                "delta_er": float(delta_er),
                "delta_ev": float(delta_ev),
                "reason": str(reason),
                "source_module": str(source_module),
            }
        )
        return {"success": True, "code": "OK", "data": {"before": before, "after": {"er": after_er, "ev": after_ev}}}


def test_build_cam_consumes_energy_and_outputs_budget_snapshot():
    items = [
        {
            "item_id": "i1",
            "ref_object_type": "st",
            "ref_object_id": "st_1",
            "display": "A",
            "er": 2.0,
            "ev": 0.0,
            "cp_abs": 2.0,
            "salience_score": 2.0,
            "updated_at": 1000,
        },
        {
            "item_id": "i2",
            "ref_object_type": "st",
            "ref_object_id": "st_2",
            "display": "B",
            "er": 1.0,
            "ev": 1.0,
            "cp_abs": 0.0,
            "salience_score": 1.0,
            "updated_at": 1000,
        },
        {
            "item_id": "i3",
            "ref_object_type": "st",
            "ref_object_id": "st_3",
            "display": "C",
            "er": 0.1,
            "ev": 0.0,
            "cp_abs": 0.1,
            "salience_score": 0.1,
            "updated_at": 1000,
        },
    ]
    pool = DummyPool(items)
    af = AttentionFilter(config_override={"log_dir": "", "attention_energy_budget_enabled": False})

    resp = af.build_cam_from_pool(
        pool,
        trace_id="t001",
        tick_id="t001",
        top_n=2,
        consume_energy=True,
        memory_energy_ratio=0.5,
    )
    assert resp["success"] is True

    cam = resp["data"]["cam_snapshot"]
    report = resp["data"]["attention_report"]
    assert cam["object_type"] == "runtime_snapshot"
    assert cam["sub_type"] == "cam_snapshot"

    # Selected order should be A then B (higher CP has higher priority)
    assert len(cam["top_items"]) == 2
    assert cam["top_items"][0]["item_id"] == "i1"
    assert cam["top_items"][1]["item_id"] == "i2"

    # CAM budget energy equals extracted portion
    assert cam["top_items"][0]["er"] == 1.0
    assert cam["top_items"][0]["ev"] == 0.0
    assert cam["top_items"][1]["er"] == 0.5
    assert cam["top_items"][1]["ev"] == 0.5

    # Pool energy was deducted
    assert pool._energies["i1"]["er"] == 1.0
    assert pool._energies["i1"]["ev"] == 0.0
    assert pool._energies["i2"]["er"] == 0.5
    assert pool._energies["i2"]["ev"] == 0.5

    assert len(pool.apply_calls) == 2
    assert report["consumed_total_er"] == 1.5
    assert report["consumed_total_ev"] == 0.5
    assert report["consume_enabled"] is True


def test_build_cam_without_consumption_does_not_call_energy_update():
    items = [
        {"item_id": "i1", "ref_object_type": "st", "ref_object_id": "st_1", "display": "A", "er": 1.0, "ev": 0.0, "cp_abs": 1.0, "salience_score": 1.0, "updated_at": 1000},
        {"item_id": "i2", "ref_object_type": "st", "ref_object_id": "st_2", "display": "B", "er": 0.6, "ev": 0.2, "cp_abs": 0.4, "salience_score": 0.6, "updated_at": 1000},
    ]
    pool = DummyPool(items)
    af = AttentionFilter(config_override={"log_dir": "", "attention_energy_budget_enabled": False})

    resp = af.build_cam_from_pool(
        pool,
        trace_id="t002",
        tick_id="t002",
        top_n=2,
        consume_energy=False,
        memory_energy_ratio=0.25,
    )
    assert resp["success"] is True
    cam = resp["data"]["cam_snapshot"]

    assert len(pool.apply_calls) == 0
    assert cam["top_items"][0]["er"] == 1.0
    assert cam["top_items"][1]["er"] == 0.6


def test_attention_energy_budget_caps_filtered_cam_net_gain():
    items = [
        {
            "item_id": "i1",
            "ref_object_type": "st",
            "ref_object_id": "st_1",
            "display": "high",
            "er": 0.0,
            "ev": 1000.0,
            "cp_abs": 1000.0,
            "salience_score": 1000.0,
            "updated_at": 1000,
        },
        {
            "item_id": "i2",
            "ref_object_type": "st",
            "ref_object_id": "st_2",
            "display": "mid",
            "er": 0.0,
            "ev": 100.0,
            "cp_abs": 100.0,
            "salience_score": 100.0,
            "updated_at": 1000,
        },
    ]
    pool = DummyPool(items)
    af = AttentionFilter(
        config_override={
            "log_dir": "",
            "attention_energy_budget_base": 40.0,
            "attention_energy_budget_min": 0.0,
            "attention_energy_budget_max": 40.0,
            "attention_filter_suppression_floor": 0.0,
            "attention_filter_gain_floor": 0.0,
        }
    )

    resp = af.build_cam_from_pool(
        pool,
        trace_id="t003",
        tick_id="t003",
        top_n=2,
        consume_energy=True,
        memory_energy_ratio=0.5,
    )
    assert resp["success"] is True
    report = resp["data"]["attention_report"]
    cam = resp["data"]["cam_snapshot"]

    base_total = report["base_memory_total_energy"]
    final_total = report["memory_total_er"] + report["memory_total_ev"]
    assert base_total == 550.0
    assert round(final_total - base_total, 6) == 40.0
    assert report["attention_energy_resource"]["net_delta_energy"] == 40.0
    assert report["attention_gain_budget_applied"] == 40.0
    assert report["attention_energy_resource"]["base"] == 40.0
    assert report["attention_energy_resource"]["budget"] == 40.0

    # StatePool is charged only for the base transfer; the extra 40 is the
    # bounded attention resource carried by CAM/internal stimulus.
    assert pool._energies["i1"]["ev"] == 500.0
    assert pool._energies["i2"]["ev"] == 50.0
    assert sum(item["ev"] for item in cam["top_items"]) == 590.0


def test_attention_energy_resource_reports_static_base_separately_from_modulated_budget():
    items = [
        {
            "item_id": "i1",
            "ref_object_type": "st",
            "ref_object_id": "st_1",
            "display": "high",
            "er": 10.0,
            "ev": 0.0,
            "cp_abs": 10.0,
            "salience_score": 10.0,
            "updated_at": 1000,
        }
    ]
    pool = DummyPool(items)
    af = AttentionFilter(
        config_override={
            "log_dir": "",
            "attention_energy_budget_base": 10.0,
            "attention_energy_budget_min": 0.0,
            "attention_energy_budget_max": 32.0,
            "attention_filter_gain_floor": 0.0,
        }
    )

    resp = af.build_cam_from_pool(
        pool,
        trace_id="t003b",
        tick_id="t003b",
        top_n=1,
        consume_energy=True,
        memory_energy_ratio=0.5,
        modulation={"attention_energy_budget": 14.0},
    )

    assert resp["success"] is True
    resource = resp["data"]["attention_report"]["attention_energy_resource"]
    assert resource["base"] == 10.0
    assert resource["requested"] == 14.0
    assert resource["budget"] == 14.0


def test_attention_filter_can_suppress_low_weight_items_while_budgeting_gain():
    items = [
        {
            "item_id": "i1",
            "ref_object_type": "st",
            "ref_object_id": "st_1",
            "display": "peak",
            "er": 0.0,
            "ev": 100.0,
            "cp_abs": 100.0,
            "salience_score": 100.0,
            "updated_at": 1000,
        },
        {
            "item_id": "i2",
            "ref_object_type": "st",
            "ref_object_id": "st_2",
            "display": "weak",
            "er": 0.0,
            "ev": 1.0,
            "cp_abs": 1.0,
            "salience_score": 1.0,
            "updated_at": 1000,
        },
    ]
    pool = DummyPool(items)
    af = AttentionFilter(
        config_override={
            "log_dir": "",
            "keep_score_ratio_base": 0.0,
            "keep_score_ratio_min": 0.0,
            "attention_energy_budget_base": 10.0,
            "attention_energy_budget_max": 10.0,
            "attention_filter_suppression_floor": 0.5,
            "attention_filter_suppression_min_ratio": 0.2,
            "attention_filter_gain_floor": 0.5,
        }
    )

    resp = af.build_cam_from_pool(
        pool,
        trace_id="t004",
        tick_id="t004",
        top_n=2,
        consume_energy=True,
        memory_energy_ratio=0.5,
    )
    assert resp["success"] is True
    items_out = resp["data"]["cam_snapshot"]["top_items"]
    weak = next(item for item in items_out if item["item_id"] == "i2")
    report = resp["data"]["attention_report"]

    assert weak["attention_suppression_ratio"] < 1.0
    assert weak["memory_ev"] < weak["base_memory_ev"]
    assert report["attention_suppressed_total_energy"] > 0.0
    assert report["attention_net_delta_energy"] <= 10.0
