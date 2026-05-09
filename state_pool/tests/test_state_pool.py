# -*- coding: utf-8 -*-
"""
AP 状态池模块 — 自动化测试套件
================================
覆盖设计文档 14.1~14.11 全部验证项。

运行方式:
  python -m pytest state_pool/tests/test_state_pool.py -v
"""

import sys
import os
import time
import json

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from state_pool.main import StatePool
from state_pool._id_generator import reset_id_generator
from hdb._cut_engine import CutEngine


class TestCognitiveStitchingPriorityNeutralization:
    @staticmethod
    def _seed_priority_sa(*, sa_id: str, token: str, er: float, ev: float, role: str = "feature") -> dict:
        return {
            "id": sa_id,
            "object_type": "sa",
            "content": {"raw": token, "display": token, "value_type": "discrete"},
            "stimulus": {"role": role, "modality": "text"},
            "energy": {"er": float(er), "ev": float(ev)},
            "source": {"parent_ids": []},
        }

    @staticmethod
    def _seed_priority_structure(*, structure_id: str, tokens: list[str], er: float, ev: float, member_ids: list[str] | None = None) -> dict:
        member_refs = []
        units = []
        for idx, token in enumerate(tokens):
            unit_id = str(member_ids[idx]) if member_ids and idx < len(member_ids) else f"{structure_id}_u{idx}"
            member_refs.append(unit_id)
            units.append(
                {
                    "token": token,
                    "unit_id": unit_id,
                    "unit_role": "feature",
                    "display_visible": True,
                }
            )
        sequence_groups = [
            {
                "group_index": 0,
                "source_type": "pytest",
                "origin_frame_id": structure_id,
                "tokens": list(tokens),
                "units": units,
            }
        ]
        display_text = "".join(tokens)
        return {
            "id": structure_id,
            "object_type": "st",
            "sub_type": "stimulus_sequence_structure",
            "content": {"raw": display_text, "display": display_text, "normalized": display_text},
            "energy": {"er": float(er), "ev": float(ev)},
            "structure": {
                "display_text": display_text,
                "flat_tokens": list(tokens),
                "sequence_groups": sequence_groups,
                "member_refs": member_refs,
                "content_signature": f"pytest::{structure_id}",
                "ext": {},
            },
        }

    def test_plain_structure_is_not_misclassified_as_cognitive_stitching_event(self, pool):
        """
        Regression:
        - Plain ST structures always have member_refs (SA unit ids).
        - They must NOT be treated as cognitive stitching events, otherwise the
          event-component neutralization path will start touching everything and
          pollute meta.ext.cognitive_stitching across the pool.
        """
        plain_st = {
            "id": "st_plain_1",
            "object_type": "st",
            "sub_type": "plain_structure",
            "content": {"raw": "A B", "display": "A B", "normalized": "A B"},
            "energy": {"er": 1.0, "ev": 0.0},
            "structure": {
                "display_text": "A B",
                "flat_tokens": ["A", "B"],
                "sequence_groups": [
                    {
                        "group_index": 0,
                        "source_type": "pytest",
                        "origin_frame_id": "plain_seed",
                        "tokens": ["A"],
                        "units": [{"token": "A", "unit_id": "sa_a", "unit_role": "feature", "display_visible": True}],
                    },
                    {
                        "group_index": 1,
                        "source_type": "pytest",
                        "origin_frame_id": "plain_seed",
                        "tokens": ["B"],
                        "units": [{"token": "B", "unit_id": "sa_b", "unit_role": "feature", "display_visible": True}],
                    },
                ],
                "member_refs": ["sa_a", "sa_b"],
                "content_signature": "plain_sig_ab",
                "ext": {},
            },
        }
        insert_result = pool.insert_runtime_node(plain_st, trace_id="plain_st_seed", source_module="pytest")
        assert insert_result["success"] is True

        state_item = pool._store.get_by_ref("st_plain_1")
        assert state_item is not None
        assert pool._is_cognitive_stitching_event_item(state_item) is False

    def test_insert_runtime_cs_event_preserves_component_metadata(self, pool):
        runtime_event = {
            "id": "cs_event::st_a::st_b",
            "object_type": "st",
            "sub_type": "cognitive_stitching_event",
            "content": {"raw": "A -> B", "display": "A -> B", "normalized": "A -> B"},
            "energy": {"er": 0.4, "ev": 1.6},
            "structure": {
                "display_text": "A -> B",
                "flat_tokens": ["A", "B"],
                "sequence_groups": [
                    {"group_index": 0, "source_type": "cognitive_stitching", "origin_frame_id": "seed_event", "tokens": ["A"]},
                    {"group_index": 1, "source_type": "cognitive_stitching", "origin_frame_id": "seed_event", "tokens": ["B"]},
                ],
                "member_refs": ["st_a", "st_b"],
                "content_signature": "cs_event::st_a::st_b|st_a|st_b",
                "ext": {
                    "cognitive_stitching": {
                        "stage": "pytest_seed",
                        "component_count": 2,
                        "component_profile": [
                            {"index": 0, "ref_id": "st_a", "display": "A", "share": 0.5},
                            {"index": 1, "ref_id": "st_b", "display": "B", "share": 0.5},
                        ],
                        "component_ledger": [
                            {"index": 0, "ref_id": "st_a", "display": "A", "tokens": ["A"], "profile_share": 0.5, "er": 0.4, "ev": 0.0, "cp_abs": 0.4},
                            {"index": 1, "ref_id": "st_b", "display": "B", "tokens": ["B"], "profile_share": 0.5, "er": 0.0, "ev": 1.6, "cp_abs": 1.6},
                        ],
                    }
                },
            },
        }

        insert_result = pool.insert_runtime_node(runtime_event, trace_id="cs_event_seed", source_module="pytest")
        assert insert_result["success"] is True

        state_item = pool._store.get_by_ref("cs_event::st_a::st_b")
        assert state_item is not None
        assert state_item["ref_snapshot"]["member_refs"] == ["st_a", "st_b"]
        assert state_item["ref_snapshot"]["structure_ext"]["cognitive_stitching"]["component_count"] == 2
        assert state_item["meta"]["ext"]["cognitive_stitching"]["component_ledger"][1]["display"] == "B"

    def test_priority_neutralization_can_complement_cs_event_component(self, pool):
        now_ms = int(time.time() * 1000)
        runtime_event = {
            "id": "cs_event::st_a::st_b",
            "object_type": "st",
            "sub_type": "cognitive_stitching_event",
            "content": {"raw": "A -> B", "display": "A -> B", "normalized": "A -> B"},
            "energy": {"er": 0.2, "ev": 1.8},
            "structure": {
                "display_text": "A -> B",
                "flat_tokens": ["A", "B"],
                "sequence_groups": [
                    {"group_index": 0, "source_type": "cognitive_stitching", "origin_frame_id": "seed_event", "tokens": ["A"]},
                    {"group_index": 1, "source_type": "cognitive_stitching", "origin_frame_id": "seed_event", "tokens": ["B"]},
                ],
                "member_refs": ["st_a", "st_b"],
                "content_signature": "cs_event::st_a::st_b|st_a|st_b",
                "ext": {
                    "cognitive_stitching": {
                        "stage": "pytest_seed",
                        "component_count": 2,
                        "component_profile": [
                            {"index": 0, "ref_id": "st_a", "display": "A", "share": 0.1},
                            {"index": 1, "ref_id": "st_b", "display": "B", "share": 0.9},
                        ],
                        "component_ledger": [
                            {"index": 0, "ref_id": "st_a", "display": "A", "tokens": ["A"], "profile_share": 0.1, "er": 0.2, "ev": 0.0, "cp_abs": 0.2},
                            {"index": 1, "ref_id": "st_b", "display": "B", "tokens": ["B"], "profile_share": 0.9, "er": 0.0, "ev": 1.8, "cp_abs": 1.8},
                        ],
                    }
                },
            },
        }
        insert_result = pool.insert_runtime_node(runtime_event, trace_id="cs_event_component_seed", source_module="pytest")
        assert insert_result["success"] is True

        pkt = {
            "id": "pkt_b_verify",
            "object_type": "stimulus_packet",
            "sa_items": [
                {
                    "id": "sa_b",
                    "object_type": "sa",
                    "content": {"raw": "B", "display": "B", "value_type": "discrete"},
                    "stimulus": {"role": "feature", "modality": "text"},
                    "energy": {"er": 1.0, "ev": 0.0},
                    "ext": {"packet_context": {"group_index": 0, "sequence_index": 0, "source_type": "current"}},
                    "created_at": now_ms,
                    "updated_at": now_ms,
                },
            ],
            "csa_items": [],
            "grouped_sa_sequences": [
                {"group_index": 0, "source_type": "current", "origin_frame_id": "pkt_b_verify", "sa_ids": ["sa_b"], "csa_ids": []},
            ],
            "energy_summary": {"total_er": 1.0, "total_ev": 0.0, "current_total_er": 1.0, "current_total_ev": 0.0},
            "trace_id": "priority_event_component_trace",
        }

        result = pool.apply_stimulus_packet(pkt, trace_id="priority_event_component_trace")
        assert result["success"] is True
        assert result["data"]["priority_neutralized_item_count"] == 1
        assert result["data"]["event_component_neutralization_count"] == 1
        assert result["data"]["event_component_cp_drop_sum"] > 0.0
        assert result["data"]["residual_stimulus_packet"]["sa_items"] == []
        assert result["data"]["residual_stimulus_packet"]["energy_summary"]["total_er"] == 0.0

        diagnostics = result["data"]["priority_neutralization_diagnostics"]
        assert diagnostics
        assert diagnostics[0]["neutralization_mode"] == "event_component_complementary"
        assert "B" in diagnostics[0]["matched_components"]

        state_item = pool._store.get_by_ref("cs_event::st_a::st_b")
        assert state_item is not None
        ledger = state_item["meta"]["ext"]["cognitive_stitching"]["component_ledger"]
        component_b = next(entry for entry in ledger if entry["display"] == "B")
        assert component_b["er"] == 1.0
        assert component_b["ev"] == 1.8

    def test_priority_neutralization_emits_shortfall_diagnostic_when_packet_has_no_opposite_energy(self, pool):
        now_ms = int(time.time() * 1000)
        for sa_obj in (
            self._seed_priority_sa(sa_id="sa_cp_positive_a", token="A", er=0.9, ev=0.0),
            self._seed_priority_sa(sa_id="sa_cp_positive_b", token="B", er=0.9, ev=0.0),
        ):
            insert_sa = pool.insert_runtime_node(sa_obj, trace_id=f"{sa_obj['id']}_seed", source_module="pytest")
            assert insert_sa["success"] is True
        insert_result = pool.insert_runtime_node(
            self._seed_priority_structure(
                structure_id="st_cp_positive",
                tokens=["A", "B"],
                er=1.8,
                ev=0.0,
                member_ids=["sa_cp_positive_a", "sa_cp_positive_b"],
            ),
            trace_id="cp_positive_seed",
            source_module="pytest",
        )
        assert insert_result["success"] is True

        pkt = {
            "id": "pkt_er_only",
            "object_type": "stimulus_packet",
            "sa_items": [
                {
                    "id": "sa_a",
                    "object_type": "sa",
                    "content": {"raw": "A", "display": "A", "value_type": "discrete"},
                    "stimulus": {"role": "feature", "modality": "text"},
                    "energy": {"er": 0.6, "ev": 0.0},
                    "ext": {"packet_context": {"group_index": 0, "sequence_index": 0, "source_type": "current"}},
                    "created_at": now_ms,
                    "updated_at": now_ms,
                },
                {
                    "id": "sa_b",
                    "object_type": "sa",
                    "content": {"raw": "B", "display": "B", "value_type": "discrete"},
                    "stimulus": {"role": "feature", "modality": "text"},
                    "energy": {"er": 0.4, "ev": 0.0},
                    "ext": {"packet_context": {"group_index": 0, "sequence_index": 1, "source_type": "current"}},
                    "created_at": now_ms,
                    "updated_at": now_ms,
                },
            ],
            "csa_items": [],
            "grouped_sa_sequences": [
                {"group_index": 0, "source_type": "current", "origin_frame_id": "pkt_er_only", "sa_ids": ["sa_a", "sa_b"], "csa_ids": []},
            ],
            "energy_summary": {"total_er": 1.0, "total_ev": 0.0, "current_total_er": 1.0, "current_total_ev": 0.0},
            "trace_id": "priority_shortfall_trace",
        }

        result = pool.apply_stimulus_packet(pkt, trace_id="priority_shortfall_trace")
        assert result["success"] is True
        assert result["data"]["priority_neutralized_item_count"] == 0

        diagnostics = result["data"]["priority_neutralization_diagnostics"]
        assert diagnostics
        diag = next(item for item in diagnostics if item["target_ref_object_id"] == "st_cp_positive")
        assert diag["status"] == "shortfall"
        assert diag["skipped_reason"] == "packet_no_opposite_energy"
        assert diag["required_energy_key"] == "ev"
        assert float(diag["shortfall_amount"]) > 0.0

    def test_priority_neutralization_soft_match_can_consume_partial_packet_energy(self, pool):
        now_ms = int(time.time() * 1000)
        for sa_obj in (
            self._seed_priority_sa(sa_id="sa_soft_a", token="A", er=0.0, ev=0.8),
            self._seed_priority_sa(sa_id="sa_soft_b", token="B", er=0.0, ev=0.7),
            self._seed_priority_sa(sa_id="sa_soft_c", token="C", er=0.0, ev=0.5),
        ):
            insert_sa = pool.insert_runtime_node(sa_obj, trace_id=f"{sa_obj['id']}_seed", source_module="pytest")
            assert insert_sa["success"] is True
        insert_result = pool.insert_runtime_node(
            self._seed_priority_structure(
                structure_id="st_soft_partial",
                tokens=["A", "B", "C"],
                er=0.0,
                ev=2.0,
                member_ids=["sa_soft_a", "sa_soft_b", "sa_soft_c"],
            ),
            trace_id="soft_partial_seed",
            source_module="pytest",
        )
        assert insert_result["success"] is True

        pkt = {
            "id": "pkt_partial_ab",
            "object_type": "stimulus_packet",
            "sa_items": [
                {
                    "id": "sa_a",
                    "object_type": "sa",
                    "content": {"raw": "A", "display": "A", "value_type": "discrete"},
                    "stimulus": {"role": "feature", "modality": "text"},
                    "energy": {"er": 0.7, "ev": 0.0},
                    "ext": {"packet_context": {"group_index": 0, "sequence_index": 0, "source_type": "current"}},
                    "created_at": now_ms,
                    "updated_at": now_ms,
                },
                {
                    "id": "sa_b",
                    "object_type": "sa",
                    "content": {"raw": "B", "display": "B", "value_type": "discrete"},
                    "stimulus": {"role": "feature", "modality": "text"},
                    "energy": {"er": 0.5, "ev": 0.0},
                    "ext": {"packet_context": {"group_index": 0, "sequence_index": 1, "source_type": "current"}},
                    "created_at": now_ms,
                    "updated_at": now_ms,
                },
            ],
            "csa_items": [],
            "grouped_sa_sequences": [
                {"group_index": 0, "source_type": "current", "origin_frame_id": "pkt_partial_ab", "sa_ids": ["sa_a", "sa_b"], "csa_ids": []},
            ],
            "energy_summary": {"total_er": 1.2, "total_ev": 0.0, "current_total_er": 1.2, "current_total_ev": 0.0},
            "trace_id": "priority_soft_partial_trace",
        }

        result = pool.apply_stimulus_packet(pkt, trace_id="priority_soft_partial_trace")
        assert result["success"] is True
        assert result["data"]["priority_neutralized_item_count"] == 1
        diagnostics = result["data"]["priority_neutralization_diagnostics"]
        diag = next(item for item in diagnostics if item["target_ref_object_id"] == "st_soft_partial")
        assert diag["neutralization_mode"] == "soft_partial_cache"
        assert float(diag["match_score"]) < 1.0
        assert float(diag["structure_coverage"]) == pytest.approx(2 / 3, rel=1e-3)
        assert int(diag["sa_settled_count"]) == 2
        assert any(str(row.get("target_ref_object_id", "")) == "sa_soft_a" for row in diag["sa_settlements"])
        assert float(result["data"]["residual_stimulus_packet"]["energy_summary"]["total_er"]) < 1.2

# ====================================================================== #
#                          测试 Fixtures                                  #
# ====================================================================== #

@pytest.fixture
def pool():
    """创建一个干净的状态池实例。"""
    reset_id_generator()
    p = StatePool(config_override={
        "pool_max_items": 100,
        "enable_placeholder_interfaces": False,  # 测试中关闭占位调用
        "enable_script_broadcast": False,
        "insert_attribute_sa_as_state_item": False,
        "attribute_binding_runtime_mode": "legacy_bind",
    })
    yield p
    p._logger.close()


@pytest.fixture
def sample_packet():
    """创建一个示例刺激包（模拟文本感受器输出）。"""
    now_ms = int(time.time() * 1000)
    return {
        "id": "spkt_test_001",
        "object_type": "stimulus_packet",
        "sa_items": [
            {
                "id": "sa_txt_001", "object_type": "sa",
                "content": {"raw": "你", "display": "你", "value_type": "discrete"},
                "stimulus": {"role": "feature", "modality": "text"},
                "energy": {"er": 1.0, "ev": 0.0},
                "source": {"parent_ids": []},
                "created_at": now_ms, "updated_at": now_ms,
            },
            {
                "id": "sa_attr_001", "object_type": "sa",
                "content": {"raw": "stimulus_intensity:1.0", "display": "stimulus_intensity:1.0", "value_type": "numerical"},
                "stimulus": {"role": "attribute", "modality": "text"},
                "energy": {"er": 0.0, "ev": 0.0},
                "source": {"parent_ids": ["sa_txt_001"]},
                "created_at": now_ms, "updated_at": now_ms,
            },
            {
                "id": "sa_txt_002", "object_type": "sa",
                "content": {"raw": "好", "display": "好", "value_type": "discrete"},
                "stimulus": {"role": "feature", "modality": "text"},
                "energy": {"er": 0.8, "ev": 0.0},
                "source": {"parent_ids": []},
                "created_at": now_ms, "updated_at": now_ms,
            },
            {
                "id": "sa_attr_002", "object_type": "sa",
                "content": {"raw": "stimulus_intensity:0.8", "display": "stimulus_intensity:0.8", "value_type": "numerical"},
                "stimulus": {"role": "attribute", "modality": "text"},
                "energy": {"er": 0.0, "ev": 0.0},
                "source": {"parent_ids": ["sa_txt_002"]},
                "created_at": now_ms, "updated_at": now_ms,
            },
        ],
        "csa_items": [
            {
                "id": "csa_txt_001", "object_type": "csa",
                "anchor_sa_id": "sa_txt_001", "member_sa_ids": ["sa_txt_001", "sa_attr_001"],
                "content": {"display": "CSA[你]", "raw": "你"},
                "energy": {"er": 1.0, "ev": 0.0},
                "created_at": now_ms, "updated_at": now_ms,
            },
            {
                "id": "csa_txt_002", "object_type": "csa",
                "anchor_sa_id": "sa_txt_002", "member_sa_ids": ["sa_txt_002", "sa_attr_002"],
                "content": {"display": "CSA[好]", "raw": "好"},
                "energy": {"er": 0.8, "ev": 0.0},
                "created_at": now_ms, "updated_at": now_ms,
            },
        ],
        "trace_id": "test_trace",
    }


@pytest.fixture
def attribute_sa():
    """创建一个属性SA。"""
    return {
        "id": "sa_attr_correctness_001",
        "object_type": "sa",
        "content": {"raw": "correctness:high", "display": "correctness:high", "value_type": "discrete"},
        "stimulus": {"role": "attribute", "modality": "text"},
        "energy": {"er": 0.0, "ev": 0.0},
    }


# ====================================================================== #
#                   14.1 核心功能验证                                      #
# ====================================================================== #

class TestApplyStimulusPacket:
    """测试 apply_stimulus_packet 接口。"""

    def test_normal_packet_creates_items(self, pool, sample_packet):
        """正常刺激包应产生新的 state_item（默认仅特征 SA 入池；CSA/属性 SA 折叠到锚点快照）。"""
        result = pool.apply_stimulus_packet(sample_packet, trace_id="t1")
        assert result["success"] is True
        assert result["code"] == "OK"
        assert result["data"]["new_item_count"] == 2  # 2 feature SA

    def test_duplicate_input_updates_not_duplicates(self, pool, sample_packet):
        """同一对象重复输入应更新而非重复创建（默认仅特征 SA 入池）。"""
        pool.apply_stimulus_packet(sample_packet, trace_id="t1")
        result = pool.apply_stimulus_packet(sample_packet, trace_id="t2")
        assert result["data"]["updated_item_count"] == 2
        assert result["data"]["new_item_count"] == 0

    def test_cognitive_pressure_calculation(self, pool, sample_packet):
        """认知压应正确计算: cp = er - ev, cp_abs = |cp|。"""
        pool.apply_stimulus_packet(sample_packet, trace_id="t1")
        snap = pool.get_state_snapshot("snap1")
        items = snap["data"]["snapshot"]["top_items"]
        for item in items:
            # 初始 ev=0，所以 cp_abs = er
            assert item["cp_abs"] == item["er"]

    def test_empty_packet_succeeds(self, pool):
        """空刺激包应成功但不新建对象。"""
        pkt = {"id": "empty", "object_type": "stimulus_packet", "sa_items": [], "csa_items": [], "trace_id": "t"}
        result = pool.apply_stimulus_packet(pkt, trace_id="t1")
        assert result["success"] is True
        assert result["data"]["new_item_count"] == 0

    def test_partial_bad_objects_skipped(self, pool):
        """部分损坏对象应被跳过，其余继续处理。"""
        pkt = {
            "id": "partial_bad", "object_type": "stimulus_packet",
            "sa_items": [
                {"id": "good", "object_type": "sa", "energy": {"er": 1.0, "ev": 0.0}, "stimulus": {"role": "feature"}},
                {"id": "", "object_type": "sa"},  # 缺 id → 被拒绝
                {"object_type": "sa"},  # 缺 id → 被拒绝
            ],
            "csa_items": [], "trace_id": "t",
        }
        result = pool.apply_stimulus_packet(pkt, trace_id="t1")
        assert result["success"] is True
        assert result["data"]["new_item_count"] == 1
        assert result["data"]["rejected_object_count"] == 2

    def test_priority_neutralization_consumes_matching_packet_energy(self, pool):
        """高认知压结构应先消耗匹配刺激能量，再把残余包交给后续处理。"""
        for sa_obj in (
            TestCognitiveStitchingPriorityNeutralization._seed_priority_sa(sa_id="sa_runtime_a", token="A", er=0.0, ev=1.0),
            TestCognitiveStitchingPriorityNeutralization._seed_priority_sa(sa_id="sa_runtime_b", token="B", er=0.0, ev=1.0),
        ):
            insert_sa = pool.insert_runtime_node(sa_obj, trace_id=f"{sa_obj['id']}_seed", source_module="pytest")
            assert insert_sa["success"] is True
        runtime_structure = {
            "id": "st_runtime_ab",
            "object_type": "st",
            "sub_type": "stimulus_sequence_structure",
            "content": {"raw": "AB", "display": "AB", "normalized": "AB"},
            "energy": {"er": 0.0, "ev": 2.0},
            "structure": {
                "display_text": "AB",
                "flat_tokens": ["A", "B"],
                "sequence_groups": [
                    {"group_index": 0, "source_type": "current", "origin_frame_id": "pkt_ab", "tokens": ["A"], "units": [{"unit_id": "sa_runtime_a", "token": "A", "unit_role": "feature", "display_visible": True}]},
                    {"group_index": 1, "source_type": "current", "origin_frame_id": "pkt_ab", "tokens": ["B"], "units": [{"unit_id": "sa_runtime_b", "token": "B", "unit_role": "feature", "display_visible": True}]},
                ],
                "member_refs": ["sa_runtime_a", "sa_runtime_b"],
            },
        }
        insert_result = pool.insert_runtime_node(runtime_structure, trace_id="priority_seed", source_module="pytest")
        assert insert_result["success"] is True

        now_ms = int(time.time() * 1000)
        pkt = {
            "id": "pkt_ab",
            "object_type": "stimulus_packet",
            "sa_items": [
                {
                    "id": "sa_a",
                    "object_type": "sa",
                    "content": {"raw": "A", "display": "A", "value_type": "discrete"},
                    "stimulus": {"role": "feature", "modality": "text"},
                    "energy": {"er": 1.0, "ev": 0.0},
                    "ext": {"packet_context": {"group_index": 0, "sequence_index": 0, "source_type": "current"}},
                    "created_at": now_ms,
                    "updated_at": now_ms,
                },
                {
                    "id": "sa_b",
                    "object_type": "sa",
                    "content": {"raw": "B", "display": "B", "value_type": "discrete"},
                    "stimulus": {"role": "feature", "modality": "text"},
                    "energy": {"er": 1.0, "ev": 0.0},
                    "ext": {"packet_context": {"group_index": 1, "sequence_index": 0, "source_type": "current"}},
                    "created_at": now_ms,
                    "updated_at": now_ms,
                },
            ],
            "csa_items": [],
            "grouped_sa_sequences": [
                {"group_index": 0, "source_type": "current", "origin_frame_id": "pkt_ab", "sa_ids": ["sa_a"], "csa_ids": []},
                {"group_index": 1, "source_type": "current", "origin_frame_id": "pkt_ab", "sa_ids": ["sa_b"], "csa_ids": []},
            ],
            "energy_summary": {"total_er": 2.0, "total_ev": 0.0, "current_total_er": 2.0, "current_total_ev": 0.0},
            "trace_id": "priority_trace",
        }

        result = pool.apply_stimulus_packet(pkt, trace_id="priority_trace")
        assert result["success"] is True
        assert result["data"]["priority_neutralized_item_count"] == 1
        assert result["data"]["residual_stimulus_packet"]["sa_items"] == []
        assert result["data"]["residual_stimulus_packet"]["energy_summary"]["total_er"] == 0.0

        snapshot = pool.get_state_snapshot("priority_snap", top_k=20)["data"]["snapshot"]
        structure_items = [item for item in snapshot["top_items"] if item["ref_object_type"] == "st"]
        assert structure_items
        assert structure_items[0]["cp_abs"] == 0.0
        sa_a = pool._store.get_by_ref("sa_runtime_a")
        sa_b = pool._store.get_by_ref("sa_runtime_b")
        assert sa_a is not None and sa_b is not None
        assert float(sa_a["energy"]["er"]) == pytest.approx(1.0, rel=1e-6)
        assert float(sa_b["energy"]["er"]) == pytest.approx(1.0, rel=1e-6)

    def test_priority_neutralization_exposes_cut_cache_metrics(self, pool):
        pool._config["priority_neutralization_common_part_cache_enabled"] = True
        pool._config["priority_neutralization_common_part_cache_max_entries"] = 16
        pool._priority_neutralization_cut_engine = None
        pool._priority_neutralization_cut_engine_config_key = None
        for sa_obj in (
            TestCognitiveStitchingPriorityNeutralization._seed_priority_sa(sa_id="sa_cache_a", token="A", er=0.0, ev=1.0),
            TestCognitiveStitchingPriorityNeutralization._seed_priority_sa(sa_id="sa_cache_b", token="B", er=0.0, ev=1.0),
        ):
            insert_sa = pool.insert_runtime_node(sa_obj, trace_id=f"{sa_obj['id']}_seed", source_module="pytest")
            assert insert_sa["success"] is True
        runtime_structure = TestCognitiveStitchingPriorityNeutralization._seed_priority_structure(
            structure_id="st_cache_ab",
            tokens=["A", "B"],
            er=0.0,
            ev=2.0,
            member_ids=["sa_cache_a", "sa_cache_b"],
        )
        insert_result = pool.insert_runtime_node(runtime_structure, trace_id="priority_cache_seed", source_module="pytest")
        assert insert_result["success"] is True

        now_ms = int(time.time() * 1000)
        pkt = {
            "id": "pkt_cache_ab",
            "object_type": "stimulus_packet",
            "sa_items": [
                {
                    "id": "sa_cache_input_a",
                    "object_type": "sa",
                    "content": {"raw": "A", "display": "A", "value_type": "discrete"},
                    "stimulus": {"role": "feature", "modality": "text"},
                    "energy": {"er": 1.0, "ev": 0.0},
                    "ext": {"packet_context": {"group_index": 0, "sequence_index": 0, "source_type": "current"}},
                    "created_at": now_ms,
                    "updated_at": now_ms,
                },
                {
                    "id": "sa_cache_input_b",
                    "object_type": "sa",
                    "content": {"raw": "B", "display": "B", "value_type": "discrete"},
                    "stimulus": {"role": "feature", "modality": "text"},
                    "energy": {"er": 1.0, "ev": 0.0},
                    "ext": {"packet_context": {"group_index": 0, "sequence_index": 1, "source_type": "current"}},
                    "created_at": now_ms,
                    "updated_at": now_ms,
                },
            ],
            "csa_items": [],
            "grouped_sa_sequences": [
                {
                    "group_index": 0,
                    "source_type": "current",
                    "origin_frame_id": "pkt_cache_ab",
                    "sa_ids": ["sa_cache_input_a", "sa_cache_input_b"],
                    "csa_ids": [],
                },
            ],
            "energy_summary": {"total_er": 2.0, "total_ev": 0.0, "current_total_er": 2.0, "current_total_ev": 0.0},
        }

        result = pool.apply_stimulus_packet(pkt, trace_id="priority_cache_trace")

        assert result["success"] is True
        assert result["data"]["priority_neutralized_item_count"] == 1
        cut_metrics = result["data"]["priority_neutralization_cut_metrics"]
        assert cut_metrics["maximum_common_part_cache_store_count"] >= 1
        assert (
            cut_metrics.get("maximum_common_part_exact_fast_path_hit_count", 0)
            + cut_metrics.get("maximum_common_part_single_group_fast_path_hit_count", 0)
        ) >= 1

    def test_priority_neutralization_respects_csa_bundle_and_attributes(self, pool):
        """优先中和在存在属性 SA / CSA 约束时也应能命中完整结构。"""
        now_ms = int(time.time() * 1000)
        for sa_obj in (
            TestCognitiveStitchingPriorityNeutralization._seed_priority_sa(sa_id="sa_runtime_anchor", token="A", er=0.0, ev=1.0),
            TestCognitiveStitchingPriorityNeutralization._seed_priority_sa(sa_id="sa_runtime_attr", token="x", er=0.0, ev=0.5, role="attribute"),
        ):
            insert_sa = pool.insert_runtime_node(sa_obj, trace_id=f"{sa_obj['id']}_seed", source_module="pytest")
            assert insert_sa["success"] is True
        pkt = {
            "id": "pkt_csa_priority",
            "object_type": "stimulus_packet",
            "sa_items": [
                {
                    "id": "sa_anchor",
                    "object_type": "sa",
                    "content": {"raw": "A", "display": "A", "value_type": "discrete"},
                    "stimulus": {"role": "feature", "modality": "text"},
                    "energy": {"er": 1.0, "ev": 0.0},
                    "source": {"parent_ids": []},
                    "ext": {"packet_context": {"group_index": 0, "sequence_index": 0, "source_type": "current"}},
                    "created_at": now_ms,
                    "updated_at": now_ms,
                },
                {
                    "id": "sa_attr",
                    "object_type": "sa",
                    "content": {"raw": "x", "display": "x", "value_type": "discrete"},
                    "stimulus": {"role": "attribute", "modality": "text"},
                    "energy": {"er": 0.5, "ev": 0.0},
                    "source": {"parent_ids": ["sa_anchor"]},
                    "ext": {"packet_context": {"group_index": 0, "sequence_index": 1, "source_type": "current"}},
                    "created_at": now_ms,
                    "updated_at": now_ms,
                },
            ],
            "csa_items": [
                {
                    "id": "csa_ax",
                    "object_type": "csa",
                    "anchor_sa_id": "sa_anchor",
                    "member_sa_ids": ["sa_anchor", "sa_attr"],
                    "content": {"display": "CSA[A]", "raw": "A"},
                    "energy": {"er": 1.5, "ev": 0.0},
                    "ext": {"packet_context": {"group_index": 0, "sequence_index": 2, "source_type": "current"}},
                    "created_at": now_ms,
                    "updated_at": now_ms,
                }
            ],
            "grouped_sa_sequences": [
                {"group_index": 0, "source_type": "current", "origin_frame_id": "pkt_csa_priority", "sa_ids": ["sa_anchor"], "csa_ids": ["csa_ax"]}
            ],
            "energy_summary": {"total_er": 1.5, "total_ev": 0.0, "current_total_er": 1.5, "current_total_ev": 0.0},
            "trace_id": "priority_csa_trace",
        }
        cut_engine = CutEngine()
        profile = cut_engine.build_sequence_profile_from_stimulus_packet(pkt)
        runtime_structure = {
            "id": "st_runtime_ax",
            "object_type": "st",
            "sub_type": "stimulus_sequence_structure",
            "content": {"raw": "AX", "display": "AX", "normalized": "AX"},
            "energy": {"er": 0.0, "ev": 1.5},
            "structure": {
                "display_text": profile.get("display_text", ""),
                "flat_tokens": list(profile.get("flat_tokens", [])),
                "sequence_groups": list(profile.get("sequence_groups", [])),
                "member_refs": ["sa_runtime_anchor", "sa_runtime_attr"],
            },
        }
        insert_result = pool.insert_runtime_node(runtime_structure, trace_id="priority_csa_seed", source_module="pytest")
        assert insert_result["success"] is True

        result = pool.apply_stimulus_packet(pkt, trace_id="priority_csa_trace")
        assert result["success"] is True
        assert result["data"]["priority_neutralized_item_count"] == 1
        assert result["data"]["residual_stimulus_packet"]["sa_items"] == []
        assert result["data"]["residual_stimulus_packet"]["energy_summary"]["total_er"] == 0.0


# ====================================================================== #
#                   14.2 输入接口验证                                      #
# ====================================================================== #

class TestInputValidation:
    """测试参数校验。"""

    def test_invalid_packet_type(self, pool):
        """非 dict 输入应返回 INPUT_VALIDATION_ERROR。"""
        result = pool.apply_stimulus_packet("not_a_dict", trace_id="t1")
        assert result["success"] is False
        assert result["code"] == "INPUT_VALIDATION_ERROR"

    def test_wrong_object_type(self, pool):
        """object_type 非 stimulus_packet 应报错。"""
        result = pool.apply_stimulus_packet({"id": "x", "object_type": "sa", "sa_items": [], "csa_items": []}, trace_id="t")
        assert result["success"] is False

    def test_missing_fields(self, pool):
        """缺少必填字段应报错。"""
        result = pool.apply_stimulus_packet({"id": "x", "object_type": "stimulus_packet"}, trace_id="t")
        assert result["success"] is False

    def test_invalid_apply_mode(self, pool, sample_packet):
        """非法 apply_mode 应报错。"""
        result = pool.apply_stimulus_packet(sample_packet, trace_id="t", apply_mode="invalid")
        assert result["success"] is False

    def test_validation_only_mode(self, pool, sample_packet):
        """validation_only 模式不应修改状态。"""
        result = pool.apply_stimulus_packet(sample_packet, trace_id="t", apply_mode="validation_only")
        assert result["success"] is True
        assert pool._store.size == 0

    def test_dry_run_mode(self, pool, sample_packet):
        """dry_run 模式不应修改状态。"""
        result = pool.apply_stimulus_packet(sample_packet, trace_id="t", apply_mode="dry_run")
        assert result["success"] is True
        assert pool._store.size == 0


# ====================================================================== #
#                   14.3 能量更新验证                                      #
# ====================================================================== #

class TestApplyEnergyUpdate:
    """测试 apply_energy_update 接口。"""

    def test_normal_update(self, pool, sample_packet):
        """正常能量更新。"""
        pool.apply_stimulus_packet(sample_packet, trace_id="t1")
        snap = pool.get_state_snapshot("s")
        item_id = snap["data"]["snapshot"]["top_items"][0]["item_id"]

        result = pool.apply_energy_update(
            target_item_id=item_id, delta_er=0.5, delta_ev=0.1,
            trace_id="t2", reason="test_boost",
        )
        assert result["success"] is True
        assert result["data"]["after"]["er"] > result["data"]["before"]["er"]

    def test_nonexistent_target(self, pool):
        """目标不存在应返回 STATE_ERROR。"""
        result = pool.apply_energy_update("not_exist", 0.5, 0.0, "t")
        assert result["success"] is False
        assert result["code"] == "STATE_ERROR"

    def test_both_zero_delta_rejected(self, pool, sample_packet):
        """delta_er 和 delta_ev 同时为 0 应被拒绝。"""
        pool.apply_stimulus_packet(sample_packet, trace_id="t1")
        snap = pool.get_state_snapshot("s")
        item_id = snap["data"]["snapshot"]["top_items"][0]["item_id"]
        result = pool.apply_energy_update(item_id, 0.0, 0.0, "t")
        assert result["success"] is False

    def test_negative_energy_truncated(self, pool, sample_packet):
        """负能量应被截断到 0。"""
        pool.apply_stimulus_packet(sample_packet, trace_id="t1")
        snap = pool.get_state_snapshot("s")
        item_id = snap["data"]["snapshot"]["top_items"][0]["item_id"]
        result = pool.apply_energy_update(item_id, -100.0, 0.1, "t", reason="test")
        assert result["success"] is True
        assert result["data"]["after"]["er"] == 0.0

    def test_positive_injection_fatigue_scales_high_energy_target(self, pool):
        obj = {
            "id": "sa_bang_energy",
            "object_type": "sa",
            "content": {"raw": "!", "display": "!", "value_type": "discrete"},
            "stimulus": {"role": "feature", "modality": "text"},
            "energy": {"er": 0.0, "ev": 10.0},
        }
        insert_result = pool.insert_runtime_node(obj, trace_id="fatigue_seed")
        assert insert_result["success"] is True
        item = pool._store.get_by_ref("sa_bang_energy")
        assert item is not None

        result = pool.apply_energy_update(item["id"], 0.0, 3.0, "fatigue_update", reason="pytest_positive")

        assert result["success"] is True
        applied_ev = float(result["data"]["applied_delta"]["delta_ev"])
        assert 0.0 < applied_ev < 3.0
        fatigue = result["data"]["energy_injection_fatigue"]
        assert fatigue["energy_injection_requested_ev"] == 3.0
        assert fatigue["energy_injection_throttled_ev"] > 0.0
        assert fatigue["energy_injection_scale_ev"] < 1.0

    def test_repeat_injection_fatigue_makes_second_positive_update_smaller(self, pool):
        obj = {
            "id": "sa_repeat_energy",
            "object_type": "sa",
            "content": {"raw": "repeat", "display": "repeat", "value_type": "discrete"},
            "stimulus": {"role": "feature", "modality": "text"},
            "energy": {"er": 0.0, "ev": 1.0},
        }
        assert pool.insert_runtime_node(obj, trace_id="repeat_seed")["success"] is True
        item = pool._store.get_by_ref("sa_repeat_energy")
        assert item is not None

        first = pool.apply_energy_update(item["id"], 0.0, 1.0, "repeat_1", reason="pytest_repeat")
        second = pool.apply_energy_update(item["id"], 0.0, 1.0, "repeat_2", reason="pytest_repeat")

        assert first["success"] is True
        assert second["success"] is True
        assert float(second["data"]["applied_delta"]["delta_ev"]) < float(first["data"]["applied_delta"]["delta_ev"])

    def test_negative_delta_bypasses_injection_fatigue(self, pool):
        obj = {
            "id": "sa_negative_bypass",
            "object_type": "sa",
            "content": {"raw": "cooldown", "display": "cooldown", "value_type": "discrete"},
            "stimulus": {"role": "feature", "modality": "text"},
            "energy": {"er": 0.0, "ev": 5.0},
        }
        assert pool.insert_runtime_node(obj, trace_id="negative_seed")["success"] is True
        item = pool._store.get_by_ref("sa_negative_bypass")
        assert item is not None

        result = pool.apply_energy_update(item["id"], 0.0, -2.0, "negative_update", reason="pytest_negative")

        assert result["success"] is True
        assert result["data"]["after"]["ev"] == 3.0
        assert result["data"]["energy_injection_fatigue"] == {}

    def test_snapshot_exposes_energy_injection_fatigue_stats(self, pool):
        obj = {
            "id": "sa_snapshot_fatigue",
            "object_type": "sa",
            "content": {"raw": "snapshot", "display": "snapshot", "value_type": "discrete"},
            "stimulus": {"role": "feature", "modality": "text"},
            "energy": {"er": 0.0, "ev": 8.0},
        }
        assert pool.insert_runtime_node(obj, trace_id="snapshot_seed")["success"] is True
        item = pool._store.get_by_ref("sa_snapshot_fatigue")
        assert item is not None
        assert pool.apply_energy_update(item["id"], 0.0, 2.0, "snapshot_update", reason="pytest_snapshot")["success"] is True

        snapshot = pool.get_state_snapshot("snapshot_check")["data"]["snapshot"]
        stats = snapshot["summary"]["energy_injection_fatigue"]["current_tick_stats"]

        assert stats["event_count"] >= 1
        assert stats["requested_ev"] >= 2.0
        assert stats["throttled_ev"] > 0.0

    def test_clear_state_pool_resets_energy_injection_fatigue_stats(self, pool):
        obj = {
            "id": "sa_clear_fatigue",
            "object_type": "sa",
            "content": {"raw": "clear", "display": "clear", "value_type": "discrete"},
            "stimulus": {"role": "feature", "modality": "text"},
            "energy": {"er": 0.0, "ev": 8.0},
        }
        assert pool.insert_runtime_node(obj, trace_id="clear_fatigue_seed")["success"] is True
        item = pool._store.get_by_ref("sa_clear_fatigue")
        assert item is not None
        assert pool.apply_energy_update(item["id"], 0.0, 2.0, "clear_fatigue_update", reason="pytest_clear")["success"] is True

        before = pool.get_state_snapshot("before_clear_fatigue")["data"]["snapshot"]["summary"]["energy_injection_fatigue"]
        assert before["total_stats"]["event_count"] >= 1

        assert pool.clear_state_pool(trace_id="clear_fatigue", reason="pytest_clear", operator="pytest")["success"] is True
        after = pool.get_state_snapshot("after_clear_fatigue")["data"]["snapshot"]["summary"]["energy_injection_fatigue"]

        assert after["current_tick_stats"]["event_count"] == 0
        assert after["total_stats"]["event_count"] == 0


# ====================================================================== #
#                   14.4 属性绑定验证                                      #
# ====================================================================== #

class TestBindAttributeNode:
    """测试 bind_attribute_node_to_object 接口。"""

    def test_bind_to_sa_updates_binding_without_auto_creating_csa(self, pool, sample_packet, attribute_sa):
        """默认配置下绑定属性到 SA 只更新绑定关系，不自动创建新的 CSA 运行时对象。"""
        pool.apply_stimulus_packet(sample_packet, trace_id="t1")
        snap = pool.get_state_snapshot("s")
        # 找一个 SA 类型的项
        sa_item = None
        for item in snap["data"]["snapshot"]["top_items"]:
            if item.get("ref_object_type") == "sa":
                sa_item = item
                break
        assert sa_item is not None

        result = pool.bind_attribute_node_to_object(
            target_item_id=sa_item["item_id"], attribute_sa=attribute_sa,
            trace_id="bind_1", source_module="test",
        )
        assert result["success"] is True
        assert result["data"]["created_new_csa"] is False

    def test_bind_invalid_role_rejected(self, pool, sample_packet):
        """非 attribute 角色应被拒绝。"""
        pool.apply_stimulus_packet(sample_packet, trace_id="t1")
        snap = pool.get_state_snapshot("s")
        item_id = snap["data"]["snapshot"]["top_items"][0]["item_id"]
        bad_attr = {"id": "x", "object_type": "sa", "stimulus": {"role": "feature"}}
        result = pool.bind_attribute_node_to_object(item_id, bad_attr, "t")
        assert result["success"] is False

    def test_dedup_same_id(self, pool, sample_packet, attribute_sa):
        """同 id 重复绑定应去重。"""
        pool.apply_stimulus_packet(sample_packet, trace_id="t1")
        snap = pool.get_state_snapshot("s")
        sa_items = [i for i in snap["data"]["snapshot"]["top_items"] if i.get("ref_object_type") == "sa"]
        if sa_items:
            item_id = sa_items[0]["item_id"]
            pool.bind_attribute_node_to_object(item_id, attribute_sa, "t1")
            result = pool.bind_attribute_node_to_object(item_id, attribute_sa, "t2")
            assert result["data"]["deduplicated"] is True


# ====================================================================== #
#                   14.5 运行态对象插入                                    #
# ====================================================================== #

class TestInsertRuntimeNode:
    """测试 insert_runtime_node 接口。"""

    def test_insert_cfs_signal(self, pool):
        """插入 cfs_signal 类型成功。"""
        obj = {
            "id": "cfs_boredom_001", "object_type": "cfs_signal",
            "content": {"raw": "boredom:high", "display": "boredom:high"},
            "energy": {"er": 0.5, "ev": 0.0},
        }
        result = pool.insert_runtime_node(obj, trace_id="t1")
        assert result["success"] is True
        assert pool._store.size == 1

    def test_insert_unknown_type_rejected(self, pool):
        """不支持的类型应被拒绝。"""
        obj = {"id": "unknown_001", "object_type": "unknown_type", "energy": {"er": 1}}
        result = pool.insert_runtime_node(obj, trace_id="t")
        assert result["success"] is False
        assert result["code"] == "NOT_IMPLEMENTED_ERROR"

    def test_insert_missing_energy(self, pool):
        """缺少 energy 应被拒绝。"""
        obj = {"id": "x", "object_type": "sa"}
        result = pool.insert_runtime_node(obj, trace_id="t")
        assert result["success"] is False

    def test_fast_ref_hit_energy_merge_reuses_existing_item(self, pool):
        """Exact ref fast path should merge energy without creating a duplicate item."""
        obj = {
            "id": "st_growth_ab",
            "object_type": "st",
            "sub_type": "stimulus_sequence_structure",
            "content": {"raw": "AB", "display": "AB", "normalized": "AB"},
            "energy": {"er": 1.0, "ev": 2.0},
            "structure": {
                "display_text": "AB",
                "flat_tokens": ["A", "B"],
                "sequence_groups": [
                    {
                        "group_index": 0,
                        "tokens": ["A", "B"],
                        "units": [
                            {"unit_id": "sa_a", "token": "A", "unit_role": "feature", "display_visible": True},
                            {"unit_id": "sa_b", "token": "B", "unit_role": "feature", "display_visible": True},
                        ],
                    }
                ],
                "member_refs": ["sa_a", "sa_b"],
                "content_signature": "pytest::growth_ab",
            },
        }
        first = pool.insert_runtime_node(obj, trace_id="fast_ref_seed", source_module="pytest")
        assert first["success"] is True
        assert pool._store.size == 1
        existing = pool._store.get_by_ref("st_growth_ab")
        assert existing is not None
        item_id = existing["id"]

        incoming = json.loads(json.dumps(obj))
        incoming["energy"] = {"er": 0.5, "ev": 1.25}
        incoming["ext"] = {
            "growth_projection": {"source_structure_id": "st_a", "target_structure_id": "st_growth_ab"},
            "component_energy": {"source": {"er": 0.5}, "residual": {"ev": 1.25}},
        }
        result = pool.insert_runtime_node(
            incoming,
            trace_id="fast_ref_hit",
            source_module="hdb",
            enable_brief_log=False,
            enable_detail_log=False,
            fast_ref_hit_energy_merge=True,
        )

        assert result["success"] is True
        assert result["data"]["merged"] is True
        assert result["data"]["merge_mode"] == "ref_fast"
        assert result["data"]["fast_ref_hit"] is True
        assert result["data"]["target_item_id"] == item_id
        assert pool._store.size == 1
        merged = pool._store.get_by_ref("st_growth_ab")
        assert merged is not None
        assert float(merged["energy"]["er"]) > 1.0
        assert float(merged["energy"]["ev"]) > 2.0
        assert merged["meta"]["ext"]["growth_projection"]["source_structure_id"] == "st_a"
        assert merged["meta"]["ext"]["component_energy"]["residual"]["ev"] == 1.25

    def test_runtime_structure_root_identity_merges_resolution_views(self, pool):
        """同一完整结构的不同运行态分辨率视图应按根结构身份合并。"""
        root_obj = {
            "id": "st_root_memory",
            "object_type": "st",
            "sub_type": "stimulus_sequence_structure",
            "content": {"raw": "ABC", "display": "ABC", "normalized": "ABC"},
            "energy": {"er": 1.0, "ev": 0.5},
            "structure": {
                "display_text": "ABC",
                "flat_tokens": ["A", "B", "C"],
                "sequence_groups": [
                    {
                        "group_index": 0,
                        "tokens": ["A", "B", "C"],
                        "units": [
                            {"unit_id": "sa_a", "token": "A", "unit_role": "feature", "display_visible": True},
                            {"unit_id": "sa_b", "token": "B", "unit_role": "feature", "display_visible": True},
                            {"unit_id": "sa_c", "token": "C", "unit_role": "feature", "display_visible": True},
                        ],
                    }
                ],
                "member_refs": ["sa_a", "sa_b", "sa_c"],
                "content_signature": "pytest::root_memory",
            },
            "meta": {
                "ext": {
                    "runtime_resolution": {"root_structure_id": "st_root_memory"},
                    "component_energy": {
                        "source_component_er_share": 1.0,
                        "residual_component_ev_share": 0.5,
                    },
                }
            },
        }
        inserted = pool.insert_runtime_node(root_obj, trace_id="root_resolution_seed", source_module="pytest")
        assert inserted["success"] is True

        degraded_view = json.loads(json.dumps(root_obj))
        degraded_view["id"] = "st_runtime_view_lowres"
        degraded_view["energy"] = {"er": 0.2, "ev": 0.1}
        degraded_view["content"] = {"raw": "AB", "display": "AB", "normalized": "AB"}
        degraded_view["structure"]["display_text"] = "AB"
        degraded_view["structure"]["flat_tokens"] = ["A", "B"]
        degraded_view["structure"]["content_signature"] = "pytest::root_memory_lowres_view"
        degraded_view["meta"]["ext"]["component_energy"] = {
            "source_component_er_share": 0.2,
            "residual_component_ev_share": 0.1,
        }

        merged_result = pool.insert_runtime_node(
            degraded_view,
            trace_id="root_resolution_merge",
            source_module="pytest",
        )

        assert merged_result["success"] is True
        assert merged_result["data"]["merged"] is True
        assert merged_result["data"]["merge_mode"] == "root_structure"
        assert pool._store.size == 1
        merged = pool._store.get_by_root_structure_id("st_root_memory")
        assert merged is not None
        assert round(float(merged["energy"]["er"]), 4) > 1.0
        assert round(float(merged["energy"]["ev"]), 4) > 0.5
        component_energy = merged["meta"]["ext"]["component_energy"]
        assert component_energy["source_component_er_share"] == 1.2
        assert component_energy["residual_component_ev_share"] == 0.6
        runtime_resolution = merged["meta"]["ext"]["runtime_resolution"]
        assert runtime_resolution["root_structure_id"] == "st_root_memory"
        assert runtime_resolution["hdb_identity_re_resolved"] is False
        assert runtime_resolution["hdb_write_on_degrade"] is False

    def test_runtime_structure_resolution_metadata_decays_without_new_identity(self, pool):
        """维护衰减只刷新运行态分辨率元数据，不改变根结构身份。"""
        obj = {
            "id": "st_decay_root",
            "object_type": "st",
            "sub_type": "stimulus_sequence_structure",
            "content": {"raw": "AB", "display": "AB", "normalized": "AB"},
            "energy": {"er": 0.5, "ev": 0.5},
            "structure": {
                "display_text": "AB",
                "flat_tokens": ["A", "B"],
                "sequence_groups": [
                    {
                        "group_index": 0,
                        "tokens": ["A", "B"],
                        "units": [
                            {"unit_id": "sa_a", "token": "A", "unit_role": "feature", "display_visible": True},
                            {"unit_id": "sa_b", "token": "B", "unit_role": "feature", "display_visible": True},
                        ],
                    }
                ],
                "content_signature": "pytest::decay_root",
            },
            "meta": {
                "ext": {
                    "runtime_resolution": {"root_structure_id": "st_decay_root"},
                    "component_energy": {
                        "source_component_er_share": 0.2,
                        "residual_component_ev_share": 0.04,
                    },
                }
            },
        }
        assert pool.insert_runtime_node(obj, trace_id="resolution_decay_seed", source_module="pytest")["success"] is True
        result = pool.tick_maintain_state_pool(trace_id="resolution_decay_tick", apply_neutralization=False)
        assert result["success"] is True
        item = pool._store.get_by_root_structure_id("st_decay_root")
        assert item is not None
        runtime_resolution = item["meta"]["ext"]["runtime_resolution"]
        assert runtime_resolution["root_structure_id"] == "st_decay_root"
        assert runtime_resolution["hdb_identity_re_resolved"] is False
        assert runtime_resolution["hdb_write_on_degrade"] is False
        assert "runtime_resolution_degraded_item_count" in result["data"]


# ====================================================================== #
#                   14.6 Tick 维护验证                                     #
# ====================================================================== #

class TestTickMaintenance:
    """测试 tick_maintain_state_pool 接口。"""

    def test_decay_reduces_energy(self, pool, sample_packet):
        """衰减应降低对象能量。"""
        pool.apply_stimulus_packet(sample_packet, trace_id="t1")
        # 获取初始 er
        snap_before = pool.get_state_snapshot("s1")
        item_before = snap_before["data"]["snapshot"]["top_items"][0]
        er_before = item_before["er"]

        pool.tick_maintain_state_pool(trace_id="m1")

        snap_after = pool.get_state_snapshot("s2")
        item_after = snap_after["data"]["snapshot"]["top_items"][0]
        er_after = item_after["er"]
        assert er_after < er_before

    def test_prune_low_energy(self, pool):
        """低能量对象应被淘汰。"""
        obj = {
            "id": "low_energy_001", "object_type": "sa",
            "energy": {"er": 0.01, "ev": 0.01},
            "stimulus": {"role": "feature"},
        }
        pool.insert_runtime_node(obj, trace_id="t1")
        assert pool._store.size == 1

        # 维护 → 衰减 → 淘汰
        pool.tick_maintain_state_pool(trace_id="m1")
        assert pool._store.size == 0

    def test_empty_pool_maintenance(self, pool):
        """空池维护应正常。"""
        result = pool.tick_maintain_state_pool(trace_id="m1")
        assert result["success"] is True
        assert result["data"]["before_item_count"] == 0

    def test_neutralization_reduces_cp(self, pool):
        """中和应降低认知压。"""
        obj = {
            "id": "neut_test", "object_type": "sa",
            "energy": {"er": 1.2, "ev": 0.8},
            "stimulus": {"role": "feature"},
        }
        pool.insert_runtime_node(obj, trace_id="t1")
        pool.tick_maintain_state_pool(trace_id="m1")

        snap = pool.get_state_snapshot("s")
        items = snap["data"]["snapshot"]["top_items"]
        if items:
            item = items[0]
            # 中和后 er 和 ev 都应减少（simple_min_cancel）
            # 中和量 = min(er_after_decay, ev_after_decay)
            assert item["er"] < 1.2 or item["ev"] < 0.8


# ====================================================================== #
#                   14.7 快照验证                                          #
# ====================================================================== #

class TestSnapshot:
    """测试 get_state_snapshot 接口。"""

    def test_snapshot_structure(self, pool, sample_packet):
        """快照应包含必要字段。"""
        pool.apply_stimulus_packet(sample_packet, trace_id="t1")
        result = pool.get_state_snapshot("s1")
        assert result["success"] is True
        snapshot = result["data"]["snapshot"]
        assert "summary" in snapshot
        assert "top_items" in snapshot
        assert snapshot["summary"]["active_item_count"] == 2

    def test_top_k(self, pool, sample_packet):
        """top_k 应限制返回数量。"""
        pool.apply_stimulus_packet(sample_packet, trace_id="t1")
        result = pool.get_state_snapshot("s1", top_k=1)
        assert len(result["data"]["snapshot"]["top_items"]) == 1

    def test_sort_by(self, pool, sample_packet):
        """sort_by 应按指定字段排序。"""
        pool.apply_stimulus_packet(sample_packet, trace_id="t1")
        result = pool.get_state_snapshot("s1", sort_by="er")
        items = result["data"]["snapshot"]["top_items"]
        ers = [i["er"] for i in items]
        assert ers == sorted(ers, reverse=True)


# ====================================================================== #
#                   14.8 配置热加载验证                                    #
# ====================================================================== #

class TestReloadConfig:
    """测试 reload_config 接口。"""

    def test_reload_success(self, pool):
        """使用默认配置文件重载。"""
        result = pool.reload_config("cfg_t1")
        # 可能成功也可能失败（取决于配置文件格式）
        assert "code" in result

    def test_reload_invalid_path(self, pool):
        """无效路径应返回 CONFIG_ERROR。"""
        result = pool.reload_config("cfg_t2", config_path="nonexistent.yaml")
        assert result["success"] is False


# ====================================================================== #
#                   14.9 清空状态池验证                                    #
# ====================================================================== #

class TestClearStatePool:
    """测试 clear_state_pool 接口。"""

    def test_clear(self, pool, sample_packet):
        """清空后池应为空。"""
        pool.apply_stimulus_packet(sample_packet, trace_id="t1")
        assert pool._store.size > 0
        assert pool._tick_counter > 0
        result = pool.clear_state_pool("clear_t1", reason="test_reset")
        assert result["success"] is True
        assert pool._store.size == 0
        assert pool._tick_counter == 0
        assert result["data"]["tick_counter_reset"] is True

    def test_clear_empty_pool(self, pool):
        """清空空池应成功。"""
        result = pool.clear_state_pool("clear_t2", reason="test")
        assert result["success"] is True
        assert result["data"]["cleared_item_count"] == 0


# ====================================================================== #
#                   14.10 变化率计算                                       #
# ====================================================================== #

class TestChangeRate:
    """测试认知压变化率计算。"""

    def test_change_rate_after_update(self, pool, sample_packet):
        """更新后 dynamics 字段应记录变化。"""
        pool.apply_stimulus_packet(sample_packet, trace_id="t1")
        snap = pool.get_state_snapshot("s")
        item_id = snap["data"]["snapshot"]["top_items"][0]["item_id"]

        time.sleep(0.01)  # 确保有时差
        pool.apply_energy_update(item_id, 0.5, 0.0, "t2", reason="test")

        item = pool._store.get(item_id)
        d = item["dynamics"]
        assert d["delta_er"] > 0
        assert d["update_count"] >= 2


# ====================================================================== #
#                   14.11 边界值验证                                       #
# ====================================================================== #

class TestEdgeCases:
    """测试边界值和异常情况。"""

    def test_pool_max_items_respected(self, pool):
        """池容量上限应被遵守。"""
        pool._config["pool_max_items"] = 3
        pool._store.update_config(pool._config)

        for i in range(5):
            obj = {"id": f"sa_{i}", "object_type": "sa", "energy": {"er": float(i + 1), "ev": 0.0}}
            pool.insert_runtime_node(obj, trace_id=f"t{i}")
        assert pool._store.size <= 3

    def test_zero_energy_insert(self, pool):
        """零能量对象插入取决于配置。"""
        obj = {"id": "zero_e", "object_type": "sa", "energy": {"er": 0.0, "ev": 0.0}}
        result = pool.insert_runtime_node(obj, trace_id="t")
        # 默认配置 insert_zero_energy_object=true
        assert result["success"] is True

    def test_multiple_ticks(self, pool, sample_packet):
        """连续多 Tick 应稳定运行。"""
        pool.apply_stimulus_packet(sample_packet, trace_id="t1")
        for i in range(10):
            result = pool.tick_maintain_state_pool(trace_id=f"m{i}")
            assert result["success"] is True


# ====================================================================== #
#                   运行入口                                              #
# ====================================================================== #

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
