# -*- coding: utf-8 -*-
"""
状态池快照增强测试
==================

重点覆盖：
1. CSA 快照必须能展示锚点和属性摘要。
2. 属性绑定后，快照里必须能看到运行时绑定属性。
3. Tick 维护必须推进内部 tick 计数，并刷新疲劳等维护字段。
4. 上下文/残差/记忆来源字段必须稳定透传到快照。
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from state_pool.main import StatePool
from state_pool._id_generator import reset_id_generator


@pytest.fixture
def pool():
    reset_id_generator()
    instance = StatePool(
        config_override={
            "pool_max_items": 100,
            "enable_placeholder_interfaces": False,
            "enable_script_broadcast": False,
        }
    )
    yield instance
    instance._logger.close()


def build_packet_with_csa_details():
    now_ms = int(time.time() * 1000)
    feature_sa = {
        "id": "sa_feature_001",
        "object_type": "sa",
        "content": {"raw": "你", "display": "你", "value_type": "discrete"},
        "stimulus": {"role": "feature", "modality": "text"},
        "energy": {"er": 1.0, "ev": 0.0},
        "created_at": now_ms,
        "updated_at": now_ms,
    }
    attribute_sa = {
        "id": "sa_attr_001",
        "object_type": "sa",
        "content": {
            "raw": "stimulus_intensity:1.0",
            "display": "stimulus_intensity:1.0",
            "value_type": "numerical",
        },
        "stimulus": {"role": "attribute", "modality": "text"},
        "energy": {"er": 0.0, "ev": 0.0},
        "created_at": now_ms,
        "updated_at": now_ms,
    }
    csa = {
        "id": "csa_feature_001",
        "object_type": "csa",
        "anchor_sa_id": feature_sa["id"],
        "member_sa_ids": [feature_sa["id"], attribute_sa["id"]],
        "content": {"display": "CSA[你]"},
        "energy": {"er": 1.0, "ev": 0.0},
        "created_at": now_ms,
        "updated_at": now_ms,
    }
    return {
        "id": "spkt_detail_001",
        "object_type": "stimulus_packet",
        "sa_items": [feature_sa, attribute_sa],
        "csa_items": [csa],
        "trace_id": "detail_trace",
    }


def test_csa_snapshot_contains_anchor_and_attribute_summary(pool):
    packet = build_packet_with_csa_details()
    result = pool.apply_stimulus_packet(packet, trace_id="detail_trace")
    assert result["success"] is True

    snapshot = pool.get_state_snapshot("snap_detail", top_k=10)["data"]["snapshot"]
    # 默认配置下 CSA 不作为独立 state_item 入池；但 CSA/属性信息应折叠到锚点 SA 的快照里，
    # 以便前端可读、避免出现大量 "CSA[...]" 噪音对象。
    sa_items = [item for item in snapshot["top_items"] if item["ref_object_type"] == "sa" and item["display"] == "你"]
    assert sa_items

    anchor_summary = sa_items[0]
    assert "stimulus_intensity:1.0" in anchor_summary["attribute_displays"]
    assert "attrs=stimulus_intensity:1.0" in anchor_summary["display_detail"]


def test_binding_default_runtime_mode_inserts_standalone_attribute_state_item(pool):
    packet = build_packet_with_csa_details()
    pool.apply_stimulus_packet(packet, trace_id="bind_trace")

    snapshot = pool.get_state_snapshot("snap_bind", top_k=10)["data"]["snapshot"]
    sa_items = [item for item in snapshot["top_items"] if item["ref_object_type"] == "sa" and item["display"] == "你"]
    assert sa_items

    attribute_sa = {
        "id": "sa_attr_correctness_001",
        "object_type": "sa",
        "content": {
            "raw": "correctness:0.6",
            "display": "correctness:0.6",
            "value_type": "numerical",
            "attribute_name": "correctness",
            "attribute_value": 0.6,
        },
        "stimulus": {"role": "attribute", "modality": "internal"},
        "energy": {"er": 0.0, "ev": 0.6},
    }
    result = pool.bind_attribute_node_to_object(
        target_item_id=sa_items[0]["item_id"],
        attribute_sa=attribute_sa,
        trace_id="bind_trace_2",
        source_module="pytest",
    )
    assert result["success"] is True

    after_snapshot = pool.get_state_snapshot("snap_bind_after", top_k=20)["data"]["snapshot"]
    anchor_row = next(item for item in after_snapshot["top_items"] if item["item_id"] == sa_items[0]["item_id"])
    attr_rows = [
        item for item in after_snapshot["top_items"]
        if str(item.get("attribute_name", "")) == "correctness" and str(item.get("role", "")) == "attribute"
    ]
    assert attr_rows
    attr_row = attr_rows[0]

    assert "correctness:0.6" in anchor_row["bound_attribute_displays"]
    assert anchor_row["runtime_bound_attribute_units"][0]["attribute_name"] == "correctness"
    assert anchor_row["runtime_bound_attribute_units"][0]["attribute_value"] == pytest.approx(0.6)
    assert attr_row["display"] == "correctness:0.6"
    assert attr_row["all_attribute_names"] == ["correctness"]
    assert attr_row["attribute_value"] == pytest.approx(0.6)
    assert attr_row["value_type"] == "numerical"
    assert attr_row["context_ref_object_id"] == "sa_feature_001"
    assert attr_row["context_ref_object_type"] == "sa"
    assert attr_row["ref_snapshot"]["attribute_name"] == "correctness"
    assert attr_row["ref_snapshot"]["attribute_value"] == pytest.approx(0.6)
    assert attr_row["ref_snapshot"]["role"] == "attribute"

    summary = after_snapshot["summary"]
    correctness_totals = summary["bound_attribute_energy_totals"]["correctness"]
    assert correctness_totals["total_ev"] == pytest.approx(0.6)
    assert correctness_totals["item_count"] == 1


def test_tick_maintenance_advances_tick_counter_and_fatigue(pool):
    packet = build_packet_with_csa_details()
    pool.apply_stimulus_packet(packet, trace_id="tick_trace")
    before_tick = pool._tick_counter

    result = pool.tick_maintain_state_pool(trace_id="tick_maintain_trace")
    assert result["success"] is True
    assert pool._tick_counter == before_tick + 1

    snapshot = pool.get_state_snapshot("tick_snapshot", top_k=10)["data"]["snapshot"]
    top_item = snapshot["top_items"][0]
    assert top_item["recency_gain"] > 1.0
    assert top_item["fatigue"] == pytest.approx(0.0)


def test_snapshot_exposes_context_residual_and_memory_origin_fields(pool):
    now_ms = int(time.time() * 1000)
    packet = {
        "id": "spkt_context_fields",
        "object_type": "stimulus_packet",
        "sa_items": [
            {
                "id": "sa_ctx_anchor",
                "object_type": "sa",
                "content": {"raw": "你", "display": "你", "value_type": "discrete"},
                "stimulus": {"role": "feature", "modality": "text"},
                "energy": {"er": 1.0, "ev": 0.0},
                "created_at": now_ms,
                "updated_at": now_ms,
            },
            {
                "id": "sa_ctx_residual",
                "object_type": "sa",
                "content": {"raw": "好", "display": "好", "value_type": "discrete"},
                "stimulus": {"role": "feature", "modality": "text"},
                "energy": {"er": 0.7, "ev": 0.0},
                "ext": {
                    "context_ref_object_id": "sa_ctx_anchor",
                    "context_ref_object_type": "sa",
                    "context_owner_structure_id": "st_ctx_owner",
                    "context_path_ids": ["st_ctx_owner", "sa_ctx_anchor"],
                    "residual_origin_kind": "stimulus_raw_residual",
                    "anchor_memory_id": "em_ctx_001",
                },
                "created_at": now_ms,
                "updated_at": now_ms,
            },
        ],
        "csa_items": [],
        "trace_id": "context_fields_trace",
    }

    result = pool.apply_stimulus_packet(packet, trace_id="context_fields_trace")
    assert result["success"] is True

    snapshot = pool.get_state_snapshot("snap_context_fields", top_k=10)["data"]["snapshot"]
    target = next(item for item in snapshot["top_items"] if item["ref_object_id"] == "sa_ctx_residual")

    assert target["context_ref_object_id"] == "sa_ctx_anchor"
    assert target["context_owner_id"] == "st_ctx_owner"
    assert target["context_text"] == "你"
    assert target["residual_origin_kind"] == "stimulus_raw_residual"
    assert target["residual_kind"] == "memory"
    assert target["source_em_id"] == "em_ctx_001"

    ref_snapshot = target["ref_snapshot"]
    assert ref_snapshot["context_text"] == "你"
    assert ref_snapshot["context_owner_id"] == "st_ctx_owner"
    assert ref_snapshot["residual_kind"] == "memory"
    assert ref_snapshot["source_em_id"] == "em_ctx_001"

    summary = snapshot["summary"]
    assert summary["contextual_item_count"] >= 1
    assert summary["explicit_context_item_count"] >= 1
    assert summary["multi_context_item_count"] >= 1
    assert summary["explicit_context_path_depth_mean"] >= 2.0


def test_snapshot_summary_exposes_full_pool_energy_totals(pool):
    now_ms = int(time.time() * 1000)
    packet = {
        "id": "spkt_energy_summary",
        "object_type": "stimulus_packet",
        "sa_items": [
            {
                "id": "sa_energy_a",
                "object_type": "sa",
                "content": {"raw": "甲", "display": "甲", "value_type": "discrete"},
                "stimulus": {"role": "feature", "modality": "text"},
                "energy": {"er": 0.8, "ev": 0.1},
                "created_at": now_ms,
                "updated_at": now_ms,
            },
            {
                "id": "sa_energy_b",
                "object_type": "sa",
                "content": {"raw": "乙", "display": "乙", "value_type": "discrete"},
                "stimulus": {"role": "feature", "modality": "text"},
                "energy": {"er": 0.2, "ev": 0.4},
                "created_at": now_ms,
                "updated_at": now_ms,
            },
        ],
        "csa_items": [],
        "trace_id": "energy_summary_trace",
    }

    result = pool.apply_stimulus_packet(packet, trace_id="energy_summary_trace")
    assert result["success"] is True

    snapshot = pool.get_state_snapshot("snap_energy_summary", top_k=1)["data"]["snapshot"]
    summary = snapshot["summary"]

    assert summary["active_item_count"] == 2
    assert summary["total_er"] == pytest.approx(1.0)
    assert summary["total_ev"] == pytest.approx(0.5)
    assert summary["total_energy"] == pytest.approx(1.5)
    assert summary["total_cp"] == pytest.approx(0.9)
    assert summary["energy_by_type"]["sa"]["count"] == 2
    assert summary["energy_by_type"]["sa"]["total_er"] == pytest.approx(1.0)
    assert summary["energy_by_type"]["sa"]["total_ev"] == pytest.approx(0.5)
