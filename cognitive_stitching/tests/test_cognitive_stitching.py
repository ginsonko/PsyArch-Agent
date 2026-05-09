# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from cognitive_stitching.main import CognitiveStitchingEngine
from state_pool import StatePool


class _FakeStore:
    def __init__(self):
        self.by_id: dict[str, dict] = {}
        self.by_ref: dict[str, dict] = {}

    def get(self, item_id: str):
        return self.by_id.get(item_id)

    def get_by_ref(self, ref_id: str):
        return self.by_ref.get(ref_id)

    def get_all(self):
        return list(self.by_id.values())

    def bind_ref_alias(self, item_id: str, ref_alias_id: str):
        item = self.by_id.get(item_id)
        if item is not None:
            self.by_ref[ref_alias_id] = item


class _FakePool:
    def __init__(self, items: list[dict]):
        self._items = list(items)
        self._store = _FakeStore()
        self.energy_calls: list[dict] = []
        self.insert_calls: list[dict] = []
        self.bind_attribute_calls: list[dict] = []

    def get_state_snapshot(self, *, trace_id: str, tick_id: str, top_k=None, sort_by="cp_abs", **kwargs):
        del trace_id, tick_id, sort_by, kwargs
        items = list(self._items[: top_k or None])
        return {"success": True, "data": {"snapshot": {"summary": {"active_item_count": len(items)}, "top_items": items}}}

    def apply_energy_update(self, *, target_item_id: str, delta_er: float, delta_ev: float, trace_id: str, tick_id: str, reason: str, source_module: str, **kwargs):
        del trace_id, tick_id, source_module, kwargs
        self.energy_calls.append(
            {
                "target_item_id": target_item_id,
                "delta_er": float(delta_er),
                "delta_ev": float(delta_ev),
                "reason": reason,
            }
        )
        for item in self._items:
            if item.get("item_id") != target_item_id:
                continue
            item["er"] = round(max(0.0, float(item.get("er", 0.0)) + float(delta_er)), 8)
            item["ev"] = round(max(0.0, float(item.get("ev", 0.0)) + float(delta_ev)), 8)
            item["cp_abs"] = round(abs(float(item["er"]) - float(item["ev"])), 8)
            item["salience_score"] = round(max(float(item["er"]), float(item["ev"])), 8)
            break
        return {"success": True, "data": {"after": {}}}

    def insert_runtime_node(self, *, runtime_object: dict, trace_id: str, tick_id: str, allow_merge: bool, source_module: str, reason: str):
        del trace_id, tick_id, allow_merge, source_module, reason
        event_item_id = f"spi_{runtime_object['id']}"
        structure_block = runtime_object.get("structure", {}) if isinstance(runtime_object.get("structure", {}), dict) else {}
        structure_ext = structure_block.get("ext", {}) if isinstance(structure_block.get("ext", {}), dict) else {}
        cs_meta = structure_ext.get("cognitive_stitching", {}) if isinstance(structure_ext.get("cognitive_stitching", {}), dict) else {}
        event_item = {
            "item_id": event_item_id,
            "ref_object_id": runtime_object["id"],
            "ref_object_type": runtime_object["object_type"],
            "display": runtime_object.get("content", {}).get("display", runtime_object["id"]),
            "er": float(runtime_object.get("energy", {}).get("er", 0.0)),
            "ev": float(runtime_object.get("energy", {}).get("ev", 0.0)),
            "cp_abs": abs(float(runtime_object.get("energy", {}).get("er", 0.0)) - float(runtime_object.get("energy", {}).get("ev", 0.0))),
            "salience_score": max(float(runtime_object.get("energy", {}).get("er", 0.0)), float(runtime_object.get("energy", {}).get("ev", 0.0))),
        }
        state_item = {
            "id": event_item_id,
            "ref_object_id": runtime_object["id"],
            "ref_object_type": runtime_object["object_type"],
            "energy": {
                "er": float(runtime_object.get("energy", {}).get("er", 0.0)),
                "ev": float(runtime_object.get("energy", {}).get("ev", 0.0)),
                "cognitive_pressure_abs": event_item["cp_abs"],
                "salience_score": event_item["salience_score"],
            },
            "ref_snapshot": {
                "content_display": runtime_object.get("content", {}).get("display", runtime_object["id"]),
                "content_signature": structure_block.get("content_signature", runtime_object["id"]),
                "member_refs": list(structure_block.get("member_refs", []) or []),
                "flat_tokens": list(structure_block.get("flat_tokens", []) or []),
                "sequence_groups": list(structure_block.get("sequence_groups", []) or []),
                "context_ref_object_id": structure_ext.get("context_ref_object_id", ""),
                "context_owner_id": structure_ext.get("context_owner_structure_id", ""),
                "context_path_ids": list(structure_ext.get("context_path_ids", []) or []),
                "context_text": structure_ext.get("context_text", ""),
                "structure_ext": dict(structure_ext),
            },
            "meta": {
                "ext": {
                    "cognitive_stitching": {
                        "event_ref_id": cs_meta.get("event_ref_id", runtime_object["id"]),
                        "component_ledger": list(cs_meta.get("component_ledger", [])),
                    }
                }
            },
            "ext": {"bound_attributes": []},
        }
        self._items.insert(0, event_item)
        self._store.by_id[event_item_id] = state_item
        self._store.by_ref[runtime_object["id"]] = state_item
        self.insert_calls.append(runtime_object)
        return {"success": True, "data": {"item_id": event_item_id}}

    def bind_attribute_node_to_object(self, *, target_item_id: str, attribute_sa: dict, trace_id: str, tick_id: str, source_module: str, reason: str):
        del trace_id, tick_id, source_module, reason
        state_item = self._store.get(target_item_id)
        if not isinstance(state_item, dict):
            return {"success": False, "code": "NOT_FOUND"}
        ext = state_item.setdefault("ext", {})
        bound = ext.setdefault("bound_attributes", [])
        name = str((attribute_sa.get("content", {}) or {}).get("attribute_name", "") or "")
        bound[:] = [
            row for row in bound
            if str(((row.get("content", {}) or {}).get("attribute_name", "") or "")) != name
        ]
        bound.append(attribute_sa)
        self.bind_attribute_calls.append({"target_item_id": target_item_id, "attribute_sa": attribute_sa})
        return {"success": True, "code": "OK"}


class _FakeStructureStore:
    def __init__(self, structures: dict[str, dict], dbs: dict[str, dict]):
        self._structures = structures
        self._dbs = dbs
        self.created_count = 0

    def get(self, structure_id: str):
        return self._structures.get(structure_id)

    def get_db_by_owner(self, structure_id: str):
        return self._dbs.get(structure_id)

    def iter_structures(self):
        return list(self._structures.values())

    def create_structure(self, *, structure_payload: dict, trace_id: str, tick_id: str, source_interface: str = "", origin: str = "", origin_id: str = "", parent_ids=None):
        del trace_id, tick_id, source_interface, origin, origin_id
        self.created_count += 1
        structure_id = f"st_gen_{self.created_count}"
        ext = dict(structure_payload.get("ext", {}) or {})
        structure_obj = {
            "id": structure_id,
            "object_type": "st",
            "sub_type": structure_payload.get("sub_type", "stimulus_sequence_structure"),
            "structure": {
                "display_text": structure_payload.get("display_text", structure_id),
                "flat_tokens": list(structure_payload.get("flat_tokens", []) or []),
                "content_signature": structure_payload.get("content_signature", structure_id),
                "semantic_signature": structure_payload.get("semantic_signature", structure_payload.get("content_signature", structure_id)),
                "sequence_groups": list(structure_payload.get("sequence_groups", []) or []),
                "member_refs": list(structure_payload.get("member_refs", []) or []),
                "ext": ext,
            },
            "db_pointer": {"structure_db_id": f"sdb_{structure_id}"},
            "source": {"parent_ids": list(parent_ids or [])},
            "stats": {"base_weight": 1.0, "recent_gain": 1.0, "fatigue": 0.0},
        }
        self._structures[structure_id] = structure_obj
        self._dbs[structure_id] = {"owner_structure_id": structure_id, "diff_table": []}
        return structure_obj, self._dbs[structure_id]

    def add_diff_entry(self, owner_structure_id: str, *, target_id: str, content_signature: str, base_weight: float, entry_type: str = "structure_ref", ext: dict | None = None, **kwargs):
        del kwargs
        db = self._dbs.setdefault(owner_structure_id, {"owner_structure_id": owner_structure_id, "diff_table": []})
        entry = {
            "target_id": target_id,
            "content_signature": content_signature,
            "base_weight": float(base_weight),
            "entry_type": entry_type,
            "ext": dict(ext or {}),
        }
        db.setdefault("diff_table", []).append(entry)
        return entry


class _FakeWeight:
    @staticmethod
    def compute_runtime_weight(*, base_weight: float, recent_gain: float, fatigue: float) -> float:
        return float(base_weight) * float(recent_gain) / (1.0 + float(fatigue))


class _FakePointerIndex:
    def __init__(self):
        self._signature_index: dict[str, list[str]] = {}

    def register_structure(self, structure_obj: dict):
        structure = structure_obj.get("structure", {}) if isinstance(structure_obj.get("structure", {}), dict) else {}
        signature = str(structure.get("content_signature", "") or "")
        structure_id = str(structure_obj.get("id", "") or "")
        if signature and structure_id:
            bucket = [item for item in self._signature_index.get(signature, []) if item != structure_id]
            bucket.insert(0, structure_id)
            self._signature_index[signature] = bucket

    def query_candidates_by_signature(self, signature: str):
        return list(self._signature_index.get(signature, []))


class _FakeCut:
    @staticmethod
    def tokens_to_signature(tokens: list[str]) -> str:
        return "|".join(str(token) for token in tokens if str(token))

    @staticmethod
    def build_sequence_profile_from_groups(groups: list[dict]) -> dict:
        flat_tokens = [str(token) for group in groups for token in (group.get("tokens", []) or []) if str(token)]
        return {
            "display_text": "".join(flat_tokens),
            "member_refs": [],
            "sequence_groups": list(groups),
            "flat_tokens": flat_tokens,
        }

    def make_structure_payload_from_profile(self, profile: dict, *, confidence: float = 0.8, ext: dict | None = None) -> dict:
        groups = list(profile.get("sequence_groups", []) or [])
        flat_tokens = [str(token) for token in (profile.get("flat_tokens", []) or []) if str(token)]
        signature = self.tokens_to_signature(flat_tokens)
        return {
            "display_text": profile.get("display_text", "".join(flat_tokens)),
            "member_refs": list(profile.get("member_refs", []) or []),
            "sequence_groups": groups,
            "flat_tokens": flat_tokens,
            "content_signature": signature,
            "semantic_signature": signature,
            "confidence": confidence,
            "ext": dict(ext or {}),
        }

    def make_structure_payload_from_tokens(self, tokens: list[str], *, confidence: float = 0.8, ext: dict | None = None) -> dict:
        flat_tokens = [str(token) for token in tokens if str(token)]
        signature = self.tokens_to_signature(flat_tokens)
        return {
            "display_text": "".join(flat_tokens),
            "member_refs": [],
            "sequence_groups": [{"group_index": 0, "tokens": list(flat_tokens)}] if flat_tokens else [],
            "flat_tokens": flat_tokens,
            "content_signature": signature,
            "semantic_signature": signature,
            "confidence": confidence,
            "ext": dict(ext or {}),
        }


class _FakeHDB:
    def __init__(self, structures: dict[str, dict], dbs: dict[str, dict]):
        self._structure_store = _FakeStructureStore(structures, dbs)
        self._weight = _FakeWeight()
        self._pointer_index = _FakePointerIndex()
        self._cut = _FakeCut()
        for structure in structures.values():
            self._pointer_index.register_structure(structure)

    def make_runtime_structure_object(self, structure_id: str, er: float, ev: float, reason: str = "hdb_projection"):
        del reason
        structure_obj = self._structure_store.get(structure_id)
        if not isinstance(structure_obj, dict):
            return None
        structure_block = structure_obj.get("structure", {}) if isinstance(structure_obj.get("structure", {}), dict) else {}
        display_text = str(structure_block.get("display_text", structure_id) or structure_id)
        flat_tokens = [str(token) for token in (structure_block.get("flat_tokens", []) or []) if str(token)]
        plain_text = "".join(flat_tokens) or display_text
        return {
            "id": structure_id,
            "object_type": "st",
            "sub_type": structure_obj.get("sub_type", "stimulus_sequence_structure"),
            "content": {"raw": plain_text, "display": display_text, "normalized": plain_text},
            "energy": {"er": er, "ev": ev},
            "structure": dict(structure_block),
            "source": {"parent_ids": list((structure_obj.get("source", {}) or {}).get("parent_ids", []))},
        }


def _structure(structure_id: str, display: str, tokens: list[str], *, ext: dict | None = None, sequence_groups: list[dict] | None = None) -> dict:
    return {
        "id": structure_id,
        "object_type": "st",
        "structure": {
            "display_text": display,
            "flat_tokens": list(tokens),
            "content_signature": display,
            "sequence_groups": list(sequence_groups or ([{"group_index": 0, "tokens": list(tokens)}] if tokens else [])),
            "ext": dict(ext or {}),
        },
        "stats": {"base_weight": 1.0, "recent_gain": 1.0, "fatigue": 0.0},
    }


def _event_runtime_object(component_ids: list[str], component_displays: list[str], *, er: float, ev: float) -> dict:
    event_ref_id = "cs_event::" + "::".join(component_ids)
    display = " -> ".join(component_displays)
    return {
        "id": event_ref_id,
        "object_type": "st",
        "sub_type": "cognitive_stitching_event",
        "content": {"raw": display, "display": display, "normalized": display},
        "energy": {"er": er, "ev": ev},
    }


def test_disabled_mode_is_noop():
    engine = CognitiveStitchingEngine(config_override={"enabled": False})
    pool = _FakePool(items=[])
    hdb = _FakeHDB(structures={}, dbs={})

    result = engine.run(pool=pool, hdb=hdb, trace_id="cs_disabled", tick_id="cs_disabled")

    assert result["success"] is True
    assert result["data"]["enabled"] is False
    assert result["data"]["action_count"] == 0
    assert not pool.energy_calls
    assert not pool.insert_calls


def test_stitching_mode_is_normalized_and_exposed_in_report():
    invalid_engine = CognitiveStitchingEngine(config_override={"enabled": False, "stitching_mode": "not_a_mode"})
    assert invalid_engine._config["stitching_mode"] == "legacy_event"

    engine = CognitiveStitchingEngine(config_override={"enabled": False, "stitching_mode": "hybrid_compare", "cs_v2_audit_only": True})
    pool = _FakePool(items=[])
    hdb = _FakeHDB(structures={}, dbs={})

    result = engine.run(pool=pool, hdb=hdb, trace_id="cs_mode", tick_id="cs_mode")

    assert result["success"] is True
    assert result["data"]["stitching_mode"] == "hybrid_compare"
    assert result["data"]["mode_flags"]["hybrid_compare_active"] is True
    assert result["data"]["mode_flags"]["context_match_v2_audit_only"] is True
    assert result["data"]["candidate_audit"]["stitching_mode"] == "hybrid_compare"


def test_hybrid_compare_exposes_v2_candidate_breakdown():
    structures = {
        "st_a": _structure("st_a", "A", ["A"]),
        "st_b": _structure("st_b", "B", ["B"]),
    }
    dbs = {
        "st_a": {
            "diff_table": [
                {
                    "target_id": "st_b",
                    "base_weight": 1.2,
                    "entry_type": "structure_ref",
                }
            ]
        }
    }
    pool = _FakePool(
        items=[
            {"item_id": "spi_a", "ref_object_id": "st_a", "ref_object_type": "st", "display": "A", "er": 1.5, "ev": 0.4, "cp_abs": 1.1, "salience_score": 1.5},
            {"item_id": "spi_b", "ref_object_id": "st_b", "ref_object_type": "st", "display": "B", "er": 1.1, "ev": 0.6, "cp_abs": 0.5, "salience_score": 1.1},
        ]
    )
    hdb = _FakeHDB(structures=structures, dbs=dbs)
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "hybrid_compare",
            "max_events_per_tick": 1,
            "min_candidate_score": 0.05,
        }
    )

    result = engine.run(pool=pool, hdb=hdb, trace_id="cs_v2_breakdown", tick_id="cs_v2_breakdown")

    assert result["success"] is True
    assert result["data"]["mode_flags"]["execution_uses_legacy_score"] is True
    assert result["data"]["mode_flags"]["v2_score_exposed"] is True
    assert result["data"]["candidate_preview"]
    preview = result["data"]["candidate_preview"][0]
    assert preview["v2_score"] > 0.0
    assert preview["v2_context_cover_score"] > 0.0
    assert preview["v2_order_alignment_score"] > 0.0
    assert preview["v2_tail_match_score"] > 0.0
    assert result["data"]["candidate_audit"]["score_means"]["v2_score"] > 0.0
    assert result["data"]["candidate_audit"]["score_means"]["v2_context_db_support_score"] > 0.0


def test_soft_uplift01_raises_mid_scores_without_breaking_bounds():
    assert CognitiveStitchingEngine._soft_uplift01(0.0) == 0.0
    assert CognitiveStitchingEngine._soft_uplift01(1.0) == 1.0
    assert CognitiveStitchingEngine._soft_uplift01(0.36) > 0.36


def test_context_match_v2_surfaces_softened_breakdown_and_soft_fatigue_gate():
    structures = {
        "st_a": _structure("st_a", "A", ["A"]),
        "st_b": _structure("st_b", "B", ["B"]),
    }
    dbs = {
        "st_a": {
            "diff_table": [
                {
                    "target_id": "st_b",
                    "base_weight": 1.2,
                    "entry_type": "structure_ref",
                }
            ]
        }
    }
    items = [
        {"item_id": "spi_a", "ref_object_id": "st_a", "ref_object_type": "st", "display": "A", "er": 1.5, "ev": 0.4, "cp_abs": 1.1, "salience_score": 1.5},
        {"item_id": "spi_b", "ref_object_id": "st_b", "ref_object_type": "st", "display": "B", "er": 1.1, "ev": 0.6, "cp_abs": 0.5, "salience_score": 1.1},
    ]
    pool = _FakePool(items=[dict(row) for row in items])
    hdb = _FakeHDB(structures=structures, dbs=dbs)
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "context_match_v2",
            "cs_v2_audit_only": False,
            "context_concat_v2_enabled": False,
            "max_events_per_tick": 1,
            "insert_event_runtime_items_into_state_pool": True,
        }
    )
    engine._pair_fatigue["create_event::st_a|st_b"] = 1.4

    result = engine.run(pool=pool, hdb=hdb, trace_id="cs_v2_soft_gate", tick_id="cs_v2_soft_gate")

    assert result["success"] is True
    preview = result["data"]["candidate_preview"][0]
    assert preview["v2_base_score_soft"] >= preview["v2_base_score_raw"]
    assert preview["v2_fatigue_gate_soft"] > preview["v2_fatigue_gate_raw"]
    assert preview["v2_fatigue_gate"] == preview["v2_fatigue_gate_soft"]
    assert result["data"]["candidate_audit"]["score_means"]["v2_fatigue_gate_soft"] > result["data"]["candidate_audit"]["score_means"]["v2_fatigue_gate_raw"]


def test_context_match_v2_can_execute_with_v2_threshold_when_audit_only_disabled():
    structures = {
        "st_a": _structure("st_a", "A", ["A"]),
        "st_b": _structure("st_b", "B", ["B"]),
    }
    dbs = {
        "st_a": {
            "diff_table": [
                {
                    "target_id": "st_b",
                    "base_weight": 1.2,
                    "entry_type": "structure_ref",
                }
            ]
        }
    }
    items = [
        {"item_id": "spi_a", "ref_object_id": "st_a", "ref_object_type": "st", "display": "A", "er": 1.5, "ev": 0.4, "cp_abs": 1.1, "salience_score": 1.5},
        {"item_id": "spi_b", "ref_object_id": "st_b", "ref_object_type": "st", "display": "B", "er": 1.1, "ev": 0.6, "cp_abs": 0.5, "salience_score": 1.1},
    ]
    hdb = _FakeHDB(structures=structures, dbs=dbs)

    legacy_pool = _FakePool(items=[dict(row) for row in items])
    legacy_engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "hybrid_compare",
            "min_candidate_score": 1.25,
            "cs_v2_min_match_score": 0.55,
            "max_events_per_tick": 1,
            "insert_event_runtime_items_into_state_pool": True,
        }
    )
    legacy_result = legacy_engine.run(pool=legacy_pool, hdb=hdb, trace_id="cs_hybrid_threshold", tick_id="cs_hybrid_threshold")

    v2_pool = _FakePool(items=[dict(row) for row in items])
    v2_engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "context_match_v2",
            "cs_v2_audit_only": False,
            "context_concat_v2_enabled": False,
            "min_candidate_score": 1.25,
            "cs_v2_min_match_score": 0.55,
            "max_events_per_tick": 1,
            "insert_event_runtime_items_into_state_pool": True,
        }
    )
    v2_result = v2_engine.run(pool=v2_pool, hdb=hdb, trace_id="cs_v2_threshold", tick_id="cs_v2_threshold")

    assert legacy_result["success"] is True
    assert legacy_result["data"]["action_count"] == 0
    assert legacy_result["data"]["mode_flags"]["execution_uses_legacy_score"] is True

    assert v2_result["success"] is True
    assert v2_result["data"]["action_count"] == 1
    assert v2_result["data"]["mode_flags"]["execution_uses_v2_score"] is True
    assert v2_result["data"]["candidate_preview"][0]["score_source"] == "v2"
    assert v2_result["data"]["candidate_preview"][0]["legacy_threshold_margin"] < 0.0
    assert v2_result["data"]["candidate_preview"][0]["threshold_margin"] > 0.0


def test_context_match_v2_concat_creates_plain_structure_from_tail_context():
    structures = {
        "st_you": _structure("st_you", "你", ["你"]),
        "st_hao": _structure(
            "st_hao",
            "好",
            ["好"],
            ext={
                "context_ref_object_id": "st_you",
                "context_owner_structure_id": "st_you",
                "context_path_ids": ["st_you"],
                "context_text": "你",
            },
        ),
    }
    dbs = {"st_you": {"diff_table": []}, "st_hao": {"diff_table": []}}
    pool = _FakePool(
        items=[
            {"item_id": "spi_you", "ref_object_id": "st_you", "ref_object_type": "st", "display": "你", "er": 2.2, "ev": 0.3, "cp_abs": 1.9, "salience_score": 2.2},
            {"item_id": "spi_hao", "ref_object_id": "st_hao", "ref_object_type": "st", "display": "好", "er": 1.6, "ev": 0.4, "cp_abs": 1.2, "salience_score": 1.6},
        ]
    )
    hdb = _FakeHDB(structures=structures, dbs=dbs)
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "context_match_v2",
            "cs_v2_audit_only": False,
            "context_concat_v2_enabled": True,
            "max_events_per_tick": 1,
        }
    )

    result = engine.run(pool=pool, hdb=hdb, trace_id="cs_concat_exact", tick_id="cs_concat_exact")

    assert result["success"] is True
    assert result["data"]["action_count"] == 1
    assert result["data"]["concat_count"] == 1
    action = result["data"]["actions"][0]
    assert action["action_family"] == "concat_context_structure"
    assert action["structure_display"] == "你好"
    structure_obj = hdb._structure_store.get(action["structure_id"])
    assert structure_obj["structure"]["flat_tokens"] == ["你", "好"]
    assert structure_obj["structure"]["ext"]["context_owner_structure_id"] == "st_you"
    assert structure_obj["structure"]["ext"]["context_ref_object_id"] == "st_you"


def test_context_match_v2_exact_concat_absorbs_lower_energy_side_only():
    structures = {
        "st_you": _structure("st_you", "你", ["你"]),
        "st_hao": _structure(
            "st_hao",
            "好",
            ["好"],
            ext={
                "context_ref_object_id": "st_you",
                "context_owner_structure_id": "st_you",
                "context_path_ids": ["st_you"],
                "context_text": "你",
            },
        ),
    }
    pool = _FakePool(
        items=[
            {"item_id": "spi_you", "ref_object_id": "st_you", "ref_object_type": "st", "display": "你", "er": 0.0, "ev": 10.0, "cp_abs": 10.0, "salience_score": 10.0},
            {"item_id": "spi_hao", "ref_object_id": "st_hao", "ref_object_type": "st", "display": "好", "er": 0.0, "ev": 2.0, "cp_abs": 2.0, "salience_score": 2.0},
        ]
    )
    hdb = _FakeHDB(structures=structures, dbs={"st_you": {"diff_table": []}, "st_hao": {"diff_table": []}})
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "context_match_v2",
            "cs_v2_audit_only": False,
            "context_concat_v2_enabled": True,
            "context_concat_exact_absorb_ratio": 0.94,
            "context_concat_use_lower_energy_cap": True,
            "max_events_per_tick": 1,
        }
    )

    result = engine.run(pool=pool, hdb=hdb, trace_id="cs_concat_lower_cap", tick_id="cs_concat_lower_cap")

    assert result["success"] is True
    action = result["data"]["actions"][0]
    assert action["action_family"] == "concat_context_structure"
    assert action["absorb_ratio"] == 0.94
    assert action["source_absorbed_ev"] == 1.88
    assert action["target_absorbed_ev"] == 1.88
    assert action["source_absorbed_total"] == 1.88
    assert action["target_absorbed_total"] == 1.88
    assert action["absorbed_total"] == 3.76


def test_context_match_v2_concat_trims_target_context_prefix_before_append():
    structures = {
        "st_hui": _structure("st_hui", "会", ["会"]),
        "st_huihua": _structure(
            "st_huihua",
            "会话恢复",
            ["会", "话", "恢", "复"],
            ext={
                "context_ref_object_id": "st_hui",
                "context_owner_structure_id": "st_hui",
                "context_path_ids": ["st_hui"],
                "context_text": "会",
            },
        ),
    }
    pool = _FakePool(
        items=[
            {"item_id": "spi_hui", "ref_object_id": "st_hui", "ref_object_type": "st", "display": "会", "er": 3.0, "ev": 0.0, "cp_abs": 3.0, "salience_score": 3.0},
            {"item_id": "spi_huihua", "ref_object_id": "st_huihua", "ref_object_type": "st", "display": "会话恢复", "er": 2.0, "ev": 0.0, "cp_abs": 2.0, "salience_score": 2.0},
        ]
    )
    hdb = _FakeHDB(structures=structures, dbs={"st_hui": {"diff_table": []}, "st_huihua": {"diff_table": []}})
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "context_match_v2",
            "cs_v2_audit_only": False,
            "context_concat_v2_enabled": True,
            "max_events_per_tick": 1,
        }
    )

    result = engine.run(pool=pool, hdb=hdb, trace_id="cs_concat_trim_prefix", tick_id="cs_concat_trim_prefix")

    assert result["success"] is True
    action = result["data"]["actions"][0]
    assert action["action_family"] == "concat_context_structure"
    assert action["structure_display"] == "会话恢复"
    structure_obj = hdb._structure_store.get(action["structure_id"])
    assert structure_obj["structure"]["flat_tokens"] == ["会", "话", "恢", "复"]
    preview = result["data"]["candidate_preview"][0]
    assert preview["result_display"] == "会话恢复"


def test_context_match_v2_concat_can_soft_match_partial_context():
    structures = {
        "st_ctx": _structure("st_ctx", "和你", ["和", "你"]),
        "st_src": _structure(
            "st_src",
            "想你",
            ["想", "你"],
            ext={
                "context_ref_object_id": "st_ctx",
                "context_owner_structure_id": "st_ctx",
                "context_path_ids": ["st_ctx"],
                "context_text": "和你",
            },
        ),
        "st_tgt": _structure(
            "st_tgt",
            "好",
            ["好"],
            ext={
                "context_ref_object_id": "st_ctx",
                "context_owner_structure_id": "st_ctx",
                "context_path_ids": ["st_ctx"],
                "context_text": "和你",
            },
        ),
    }
    dbs = {"st_ctx": {"diff_table": []}, "st_src": {"diff_table": []}, "st_tgt": {"diff_table": []}}
    pool = _FakePool(
        items=[
            {"item_id": "spi_src", "ref_object_id": "st_src", "ref_object_type": "st", "display": "想你", "er": 2.1, "ev": 0.2, "cp_abs": 1.9, "salience_score": 2.1},
            {"item_id": "spi_tgt", "ref_object_id": "st_tgt", "ref_object_type": "st", "display": "好", "er": 1.8, "ev": 0.3, "cp_abs": 1.5, "salience_score": 1.8},
        ]
    )
    hdb = _FakeHDB(structures=structures, dbs=dbs)
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "context_match_v2",
            "cs_v2_audit_only": False,
            "context_concat_v2_enabled": True,
            "max_events_per_tick": 1,
            "min_candidate_score": 0.01,
            "cs_v2_min_match_score": 0.01,
        }
    )

    result = engine.run(pool=pool, hdb=hdb, trace_id="cs_concat_partial", tick_id="cs_concat_partial")

    assert result["success"] is True
    assert result["data"]["action_count"] == 1
    preview = result["data"]["candidate_preview"][0]
    assert preview["action_type"] == "concat_context_structure"
    assert preview["match_mode"] == "context_tail_partial"
    assert preview["score"] > 0.0


def test_context_concat_tie_breaks_by_energy_then_cp_then_earlier_created_at():
    engine = CognitiveStitchingEngine(config_override={"enabled": True})
    base = {
        "score": 0.9,
        "context_ratio": 1.0,
        "edge_weight_ratio": 0.5,
        "match_strength": 0.8,
    }

    low_energy = dict(base, competition_energy=2.0, competition_cp_abs=10.0, competition_created_at=1)
    high_energy = dict(base, competition_energy=3.0, competition_cp_abs=1.0, competition_created_at=99)
    assert engine._candidate_competition_key(high_energy) > engine._candidate_competition_key(low_energy)

    low_cp = dict(base, competition_energy=3.0, competition_cp_abs=1.0, competition_created_at=1)
    high_cp = dict(base, competition_energy=3.0, competition_cp_abs=2.0, competition_created_at=99)
    assert engine._candidate_competition_key(high_cp) > engine._candidate_competition_key(low_cp)

    earlier = dict(base, competition_energy=3.0, competition_cp_abs=2.0, competition_created_at=5)
    later = dict(base, competition_energy=3.0, competition_cp_abs=2.0, competition_created_at=6)
    assert engine._candidate_competition_key(earlier) > engine._candidate_competition_key(later)


def test_context_concat_narrative_includes_plain_concat_structure():
    structures = {
        "st_you": _structure("st_you", "你", ["你"]),
        "st_hao": _structure(
            "st_hao",
            "好",
            ["好"],
            ext={
                "context_ref_object_id": "st_you",
                "context_owner_structure_id": "st_you",
                "context_path_ids": ["st_you"],
                "context_text": "你",
            },
        ),
    }
    pool = _FakePool(
        items=[
            {"item_id": "spi_you", "ref_object_id": "st_you", "ref_object_type": "st", "display": "你", "er": 2.2, "ev": 0.3, "cp_abs": 1.9, "salience_score": 2.2},
            {"item_id": "spi_hao", "ref_object_id": "st_hao", "ref_object_type": "st", "display": "好", "er": 1.6, "ev": 0.4, "cp_abs": 1.2, "salience_score": 1.6},
        ]
    )
    hdb = _FakeHDB(structures=structures, dbs={"st_you": {"diff_table": []}, "st_hao": {"diff_table": []}})
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "context_match_v2",
            "context_concat_v2_enabled": True,
            "max_events_per_tick": 1,
        }
    )

    result = engine.run(pool=pool, hdb=hdb, trace_id="cs_concat_narrative", tick_id="cs_concat_narrative")

    assert result["success"] is True
    top = result["data"]["narrative_top_items"][0]
    assert top["narrative_kind"] == "concat_structure"
    assert top["display_text"] == "你好"
    assert "ctx=你" in top["visible_text"]


def test_context_concat_longer_match_count_wins_for_same_source():
    structures = {
        "st_ctx_long": _structure("st_ctx_long", "想和你", ["想", "和", "你"]),
        "st_ctx_short": _structure("st_ctx_short", "你", ["你"]),
        "st_src": _structure("st_src", "想和你", ["想", "和", "你"]),
        "st_tgt_long": _structure(
            "st_tgt_long",
            "好",
            ["好"],
            ext={
                "context_ref_object_id": "st_ctx_long",
                "context_owner_structure_id": "st_ctx_long",
                "context_path_ids": ["st_ctx_long"],
                "context_text": "想和你",
            },
        ),
        "st_tgt_short": _structure(
            "st_tgt_short",
            "啊",
            ["啊"],
            ext={
                "context_ref_object_id": "st_ctx_short",
                "context_owner_structure_id": "st_ctx_short",
                "context_path_ids": ["st_ctx_short"],
                "context_text": "你",
            },
        ),
    }
    pool = _FakePool(
        items=[
            {"item_id": "spi_src", "ref_object_id": "st_src", "ref_object_type": "st", "display": "想和你", "er": 2.4, "ev": 0.2, "cp_abs": 2.2, "salience_score": 2.4},
            {"item_id": "spi_long", "ref_object_id": "st_tgt_long", "ref_object_type": "st", "display": "好", "er": 1.4, "ev": 0.2, "cp_abs": 1.2, "salience_score": 1.4},
            {"item_id": "spi_short", "ref_object_id": "st_tgt_short", "ref_object_type": "st", "display": "啊", "er": 1.4, "ev": 0.2, "cp_abs": 1.2, "salience_score": 1.4},
        ]
    )
    hdb = _FakeHDB(
        structures=structures,
        dbs={key: {"diff_table": []} for key in structures.keys()},
    )
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "context_match_v2",
            "context_concat_v2_enabled": True,
            "max_events_per_tick": 2,
            "min_candidate_score": 0.01,
            "cs_v2_min_match_score": 0.01,
        }
    )

    result = engine.run(pool=pool, hdb=hdb, trace_id="cs_concat_matchcount", tick_id="cs_concat_matchcount")

    assert result["success"] is True
    previews = [row for row in result["data"]["candidate_preview"] if row["action_type"] == "concat_context_structure"]
    assert previews
    assert previews[0]["result_display"] == "想和你好"
    assert previews[0]["match_count_score"] >= previews[-1]["match_count_score"]


def test_context_concat_object_fatigue_softly_suppresses_repeated_attribution():
    structures = {
        "st_bang_ctx": _structure("st_bang_ctx", "!", ["!"]),
        "st_bang_a": _structure("st_bang_a", "!", ["!"]),
        "st_bang_b": _structure(
            "st_bang_b",
            "!",
            ["!"],
            ext={
                "context_ref_object_id": "st_bang_ctx",
                "context_owner_structure_id": "st_bang_ctx",
                "context_path_ids": ["st_bang_ctx"],
                "context_text": "!",
            },
        ),
    }
    pool = _FakePool(
        items=[
            {"item_id": "spi_bang_a", "ref_object_id": "st_bang_a", "ref_object_type": "st", "display": "!", "er": 0.0, "ev": 20.0, "cp_abs": 20.0, "salience_score": 20.0},
            {"item_id": "spi_bang_b", "ref_object_id": "st_bang_b", "ref_object_type": "st", "display": "!", "er": 0.0, "ev": 18.0, "cp_abs": 18.0, "salience_score": 18.0},
        ]
    )
    hdb = _FakeHDB(
        structures=structures,
        dbs={key: {"diff_table": []} for key in structures.keys()},
    )
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "context_match_v2",
            "context_concat_v2_enabled": True,
            "context_concat_exact_ignore_object_fatigue": False,
            "max_events_per_tick": 1,
            "min_candidate_score": 0.01,
            "cs_v2_min_match_score": 0.01,
            "object_stitch_fatigue_enabled": True,
            "object_stitch_fatigue_decay": 1.0,
            "object_stitch_fatigue_step": 1.1,
            "object_stitch_fatigue_cap": 2.2,
            "object_stitch_fatigue_floor_scale": 0.25,
        }
    )

    first = engine.run(pool=pool, hdb=hdb, trace_id="cs_bang_guard_1", tick_id="cs_bang_guard_1")

    assert first["success"] is True
    assert first["data"]["concat_count"] == 1
    assert first["data"]["actions"][0]["structure_display"] == "!!"
    assert first["data"]["actions"][0]["object_stitch_fatigue_scale"] == 1.0
    refs = set(first["data"]["actions"][0]["object_stitch_fatigue_refs"])
    assert "refctx:st_bang_a|owner=<none>|text=<none>" in refs
    assert "refctx:st_bang_b|owner=st_bang_ctx|text=!" in refs
    assert engine._object_stitch_fatigue.get("refctx:st_bang_a|owner=<none>|text=<none>", 0.0) > 0.0
    assert engine._object_stitch_fatigue.get("refctx:st_bang_b|owner=st_bang_ctx|text=!", 0.0) > 0.0

    second = engine.run(pool=pool, hdb=hdb, trace_id="cs_bang_guard_2", tick_id="cs_bang_guard_2")

    assert second["success"] is True
    previews = [row for row in second["data"]["candidate_preview"] if row["action_type"] == "concat_context_structure"]
    assert previews
    assert previews[0]["object_stitch_fatigue_scale"] < 1.0
    assert previews[0]["score"] < first["data"]["candidate_preview"][0]["score"]


def test_context_concat_exact_identity_ignores_object_fatigue_by_default():
    structures = {
        "st_you": _structure("st_you", "你", ["你"]),
        "st_hao": _structure(
            "st_hao",
            "好",
            ["好"],
            ext={
                "context_ref_object_id": "st_you",
                "context_owner_structure_id": "st_you",
                "context_path_ids": ["st_you"],
                "context_text": "你",
            },
        ),
    }
    hdb = _FakeHDB(structures=structures, dbs={key: {"diff_table": []} for key in structures.keys()})
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "context_match_v2",
            "context_concat_v2_enabled": True,
            "max_events_per_tick": 1,
            "min_candidate_score": 0.01,
            "cs_v2_min_match_score": 0.01,
            "object_stitch_fatigue_enabled": True,
            "object_stitch_fatigue_decay": 1.0,
            "object_stitch_fatigue_step": 1.1,
            "object_stitch_fatigue_cap": 2.2,
            "object_stitch_fatigue_floor_scale": 0.25,
        }
    )

    first_pool = _FakePool(
        items=[
            {"item_id": "spi_you", "ref_object_id": "st_you", "ref_object_type": "st", "display": "你", "er": 0.0, "ev": 10.0, "cp_abs": 10.0, "salience_score": 10.0},
            {"item_id": "spi_hao", "ref_object_id": "st_hao", "ref_object_type": "st", "display": "好", "er": 0.0, "ev": 2.0, "cp_abs": 2.0, "salience_score": 2.0},
        ]
    )
    first = engine.run(pool=first_pool, hdb=hdb, trace_id="cs_exact_no_obj_fatigue_1", tick_id="cs_exact_no_obj_fatigue_1")
    assert first["success"] is True
    assert first["data"]["concat_count"] == 1
    assert first["data"]["actions"][0]["exact_context_identity_match"] is True

    second_pool = _FakePool(
        items=[
            {"item_id": "spi_you", "ref_object_id": "st_you", "ref_object_type": "st", "display": "你", "er": 0.0, "ev": 10.0, "cp_abs": 10.0, "salience_score": 10.0},
            {"item_id": "spi_hao", "ref_object_id": "st_hao", "ref_object_type": "st", "display": "好", "er": 0.0, "ev": 2.0, "cp_abs": 2.0, "salience_score": 2.0},
        ]
    )
    second = engine.run(pool=second_pool, hdb=hdb, trace_id="cs_exact_no_obj_fatigue_2", tick_id="cs_exact_no_obj_fatigue_2")
    assert second["success"] is True
    preview = [row for row in second["data"]["candidate_preview"] if row["action_type"] == "concat_context_structure"][0]
    assert preview["exact_context_identity_match"] is True
    assert preview["object_stitch_fatigue_scale"] == 1.0
    assert preview["score"] >= 0.86


def test_context_concat_projects_non_st_support_source_and_debits_runtime_item():
    structures = {
        "st_ask": _structure("st_ask", "问", ["问"]),
        "st_tail": _structure(
            "st_tail",
            "题",
            ["题"],
            ext={
                "context_ref_object_id": "st_ask",
                "context_owner_structure_id": "st_ask",
                "context_path_ids": ["st_ask"],
                "context_text": "问",
            },
        ),
    }
    pool = _FakePool(
        items=[
            {
                "item_id": "spi_sa_ask",
                "ref_object_id": "sa_ask",
                "ref_object_type": "sa",
                "display": "问",
                "er": 0.0,
                "ev": 8.0,
                "cp_abs": 8.0,
                "salience_score": 8.0,
                "ref_snapshot": {
                    "content_display": "问",
                    "backing_structure_id": "st_ask",
                    "flat_tokens": ["问"],
                    "sequence_groups": [{"group_index": 0, "tokens": ["问"]}],
                },
            },
            {
                "item_id": "spi_tail",
                "ref_object_id": "st_tail",
                "ref_object_type": "st",
                "display": "题",
                "er": 0.0,
                "ev": 2.0,
                "cp_abs": 2.0,
                "salience_score": 2.0,
            },
        ]
    )
    hdb = _FakeHDB(structures=structures, dbs={key: {"diff_table": []} for key in structures.keys()})
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "context_match_v2",
            "context_concat_v2_enabled": True,
            "max_events_per_tick": 1,
            "min_candidate_score": 0.01,
            "cs_v2_min_match_score": 0.01,
        }
    )

    result = engine.run(pool=pool, hdb=hdb, trace_id="cs_non_st_support", tick_id="cs_non_st_support")

    assert result["success"] is True
    assert result["data"]["concat_count"] == 1
    action = result["data"]["actions"][0]
    assert action["source_ref_id"] == "st_ask"
    assert action["target_ref_id"] == "st_tail"
    assert action["structure_display"] == "问题"
    assert action["source_absorbed_ev"] == 1.88
    assert any(call["target_item_id"] == "spi_sa_ask" and call["delta_ev"] == -1.88 for call in pool.energy_calls)
    preview = result["data"]["candidate_preview"][0]
    assert preview["source_projected_from_non_st_support"] is True
    assert preview["source_runtime_ref_object_id"] == "sa_ask"
    assert action["source_projected_from_non_st_support"] is True
    assert action["source_runtime_ref_object_id"] == "sa_ask"


def test_context_concat_projects_plain_sa_source_by_profile_lookup():
    structures = {
        "st_ask": _structure("st_ask", "问", ["问"]),
        "st_tail": _structure(
            "st_tail",
            "题",
            ["题"],
            ext={
                "context_ref_object_id": "st_ask",
                "context_owner_structure_id": "st_ask",
                "context_path_ids": ["st_ask"],
                "context_text": "问",
            },
        ),
    }
    pool = _FakePool(
        items=[
            {
                "item_id": "spi_sa_ask",
                "ref_object_id": "sa_ask",
                "ref_object_type": "sa",
                "display": "问",
                "er": 0.0,
                "ev": 8.0,
                "cp_abs": 8.0,
                "salience_score": 8.0,
                "ref_snapshot": {
                    "content_display": "问",
                    "flat_tokens": ["问"],
                    "sequence_groups": [{"group_index": 0, "tokens": ["问"]}],
                },
            },
            {
                "item_id": "spi_tail",
                "ref_object_id": "st_tail",
                "ref_object_type": "st",
                "display": "题",
                "er": 0.0,
                "ev": 2.0,
                "cp_abs": 2.0,
                "salience_score": 2.0,
            },
        ]
    )
    hdb = _FakeHDB(structures=structures, dbs={key: {"diff_table": []} for key in structures.keys()})
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "context_match_v2",
            "context_concat_v2_enabled": True,
            "max_events_per_tick": 1,
            "min_candidate_score": 0.01,
            "cs_v2_min_match_score": 0.01,
        }
    )

    result = engine.run(pool=pool, hdb=hdb, trace_id="cs_plain_sa_profile", tick_id="cs_plain_sa_profile")

    assert result["success"] is True
    assert result["data"]["concat_count"] == 1
    action = result["data"]["actions"][0]
    assert action["source_ref_id"] == "st_ask"
    assert action["target_ref_id"] == "st_tail"
    assert action["structure_display"] == "问题"
    assert action["source_projected_from_non_st_support"] is True
    assert action["source_runtime_ref_object_id"] == "sa_ask"
    assert any(call["target_item_id"] == "spi_sa_ask" and call["delta_ev"] == -1.88 for call in pool.energy_calls)


def test_context_concat_high_throughput_unbounded_exact_pairs():
    pair_count = 40
    structures = {}
    items = []
    for index in range(pair_count):
        source_id = f"st_src_{index}"
        target_id = f"st_tail_{index}"
        source_text = f"S{index}"
        target_text = f"R{index}"
        structures[source_id] = _structure(source_id, source_text, [source_text])
        structures[target_id] = _structure(
            target_id,
            target_text,
            [target_text],
            ext={
                "context_ref_object_id": source_id,
                "context_owner_structure_id": source_id,
                "context_path_ids": [source_id],
                "context_text": source_text,
            },
        )
        items.append({"item_id": f"spi_src_{index}", "ref_object_id": source_id, "ref_object_type": "st", "display": source_text, "er": 0.0, "ev": 3.0, "cp_abs": 3.0, "salience_score": 3.0})
        items.append({"item_id": f"spi_tail_{index}", "ref_object_id": target_id, "ref_object_type": "st", "display": target_text, "er": 0.0, "ev": 1.0, "cp_abs": 1.0, "salience_score": 1.0})
    hdb = _FakeHDB(structures=structures, dbs={key: {"diff_table": []} for key in structures.keys()})
    pool = _FakePool(items=items)
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "context_match_v2",
            "context_concat_v2_enabled": True,
            "snapshot_top_k": 0,
            "max_seed_items": 0,
            "max_events_per_tick": 0,
            "context_concat_max_targets_per_seed": 0,
            "context_concat_soft_scan_enabled": False,
            "min_candidate_score": 0.01,
            "cs_v2_min_match_score": 0.01,
        }
    )

    result = engine.run(pool=pool, hdb=hdb, trace_id="cs_many_exact", tick_id="cs_many_exact")

    assert result["success"] is True
    assert result["data"]["concat_count"] == pair_count
    assert result["data"]["action_count"] == pair_count
    assert all(row["exact_context_identity_match"] is True for row in result["data"]["actions"])


def test_context_concat_attribute_bonus_is_positive_only():
    structures = {
        "st_you": _structure("st_you", "你", ["你"]),
        "st_src": _structure(
            "st_src",
            "你好",
            ["你", "好"],
            ext={
                "packet_attribute_by_name": {
                    "mood": {
                        "attribute_name": "mood",
                        "attribute_value": "warm",
                        "display": "mood:warm",
                    }
                }
            },
        ),
        "st_tgt_match": _structure(
            "st_tgt_match",
            "呀",
            ["呀"],
            ext={
                "context_ref_object_id": "st_you",
                "context_owner_structure_id": "st_you",
                "context_path_ids": ["st_you"],
                "context_text": "你",
                "packet_attribute_by_name": {
                    "mood": {
                        "attribute_name": "mood",
                        "attribute_value": "warm",
                        "display": "mood:warm",
                    }
                },
            },
        ),
        "st_tgt_miss": _structure(
            "st_tgt_miss",
            "呀",
            ["呀"],
            ext={
                "context_ref_object_id": "st_you",
                "context_owner_structure_id": "st_you",
                "context_path_ids": ["st_you"],
                "context_text": "你",
                "packet_attribute_by_name": {
                    "mood": {
                        "attribute_name": "mood",
                        "attribute_value": "cold",
                        "display": "mood:cold",
                    }
                },
            },
        ),
    }
    hdb = _FakeHDB(structures=structures, dbs={key: {"diff_table": []} for key in structures.keys()})
    engine = CognitiveStitchingEngine(config_override={"enabled": True, "stitching_mode": "context_match_v2"})
    source = {
        "ref_object_id": "st_src",
        "display": "你好",
        "tokens": ["你", "好"],
        "sequence_groups": [{"group_index": 0, "tokens": ["你", "好"]}],
        "context_path_ids": [],
        "attribute_descriptors": [
            {
                "attribute_name": "mood",
                "attribute_value": "warm",
                "display": "mood:warm",
                "anchor_ref_object_id": "st_src",
                "anchor_display": "你好",
            }
        ],
        "attribute_displays": ["mood:warm"],
        "attribute_anchor_ref_ids": ["st_src"],
        "attribute_anchor_displays": ["你好"],
    }
    target_base = {
        "display": "呀",
        "tokens": ["呀"],
        "sequence_groups": [{"group_index": 0, "tokens": ["呀"]}],
        "context_owner_id": "st_you",
        "context_ref_object_id": "st_you",
        "context_path_ids": ["st_you"],
        "context_text": "你",
    }

    matched = engine._match_context_tail_for_concat(
        source=source,
        target=dict(
            target_base,
            ref_object_id="st_tgt_match",
            attribute_descriptors=[
                {
                    "attribute_name": "mood",
                    "attribute_value": "warm",
                    "display": "mood:warm",
                    "anchor_ref_object_id": "st_you",
                    "anchor_display": "你",
                }
            ],
            attribute_displays=["mood:warm"],
            attribute_anchor_ref_ids=["st_you"],
            attribute_anchor_displays=["你"],
        ),
        hdb=hdb,
    )
    missed = engine._match_context_tail_for_concat(
        source=source,
        target=dict(
            target_base,
            ref_object_id="st_tgt_miss",
            attribute_descriptors=[
                {
                    "attribute_name": "mood",
                    "attribute_value": "cold",
                    "display": "mood:cold",
                    "anchor_ref_object_id": "st_you",
                    "anchor_display": "你",
                }
            ],
            attribute_displays=["mood:cold"],
            attribute_anchor_ref_ids=["st_you"],
            attribute_anchor_displays=["你"],
        ),
        hdb=hdb,
    )

    assert matched is not None and missed is not None
    assert matched["attribute_bonus_score"] > 0.0
    assert missed["attribute_bonus_score"] == 0.0
    assert matched["context_ratio"] == missed["context_ratio"]


def test_context_match_v2_same_content_different_contexts_do_not_collapse():
    structures = {
        "st_root_a": _structure("st_root_a", "甲", ["甲"]),
        "st_root_c": _structure("st_root_c", "丙", ["丙"]),
        "st_p_a": _structure(
            "st_p_a",
            "P",
            ["P"],
            ext={"context_ref_object_id": "st_root_a", "context_owner_structure_id": "st_root_a", "context_path_ids": ["st_root_a"], "context_text": "甲"},
        ),
        "st_p_c": _structure(
            "st_p_c",
            "P",
            ["P"],
            ext={"context_ref_object_id": "st_root_c", "context_owner_structure_id": "st_root_c", "context_path_ids": ["st_root_c"], "context_text": "丙"},
        ),
        "st_b_a": _structure(
            "st_b_a",
            "B",
            ["B"],
            ext={"context_ref_object_id": "st_p_a", "context_owner_structure_id": "st_p_a", "context_path_ids": ["st_root_a", "st_p_a"], "context_text": "P"},
        ),
        "st_b_c": _structure(
            "st_b_c",
            "B",
            ["B"],
            ext={"context_ref_object_id": "st_p_c", "context_owner_structure_id": "st_p_c", "context_path_ids": ["st_root_c", "st_p_c"], "context_text": "P"},
        ),
    }
    dbs = {key: {"diff_table": []} for key in structures}
    hdb = _FakeHDB(structures=structures, dbs=dbs)
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "context_match_v2",
            "cs_v2_audit_only": False,
            "context_concat_v2_enabled": True,
            "max_events_per_tick": 1,
        }
    )

    pool_a = _FakePool(
        items=[
            {"item_id": "spi_p_a", "ref_object_id": "st_p_a", "ref_object_type": "st", "display": "P", "er": 2.0, "ev": 0.2, "cp_abs": 1.8, "salience_score": 2.0},
            {"item_id": "spi_b_a", "ref_object_id": "st_b_a", "ref_object_type": "st", "display": "B", "er": 1.7, "ev": 0.3, "cp_abs": 1.4, "salience_score": 1.7},
        ]
    )
    pool_c = _FakePool(
        items=[
            {"item_id": "spi_p_c", "ref_object_id": "st_p_c", "ref_object_type": "st", "display": "P", "er": 2.0, "ev": 0.2, "cp_abs": 1.8, "salience_score": 2.0},
            {"item_id": "spi_b_c", "ref_object_id": "st_b_c", "ref_object_type": "st", "display": "B", "er": 1.7, "ev": 0.3, "cp_abs": 1.4, "salience_score": 1.7},
        ]
    )

    result_a = engine.run(pool=pool_a, hdb=hdb, trace_id="cs_concat_ctx_a", tick_id="cs_concat_ctx_a")
    result_c = engine.run(pool=pool_c, hdb=hdb, trace_id="cs_concat_ctx_c", tick_id="cs_concat_ctx_c")

    assert result_a["success"] is True
    assert result_c["success"] is True
    pb_structures = [obj for obj in hdb._structure_store.iter_structures() if obj.get("structure", {}).get("flat_tokens", []) == ["P", "B"]]
    assert len(pb_structures) == 2
    assert {obj.get("structure", {}).get("ext", {}).get("context_owner_structure_id", "") for obj in pb_structures} == {"st_p_a", "st_p_c"}


def test_context_match_v2_same_content_same_context_reuses_structure():
    structures = {
        "st_you": _structure("st_you", "你", ["你"]),
        "st_hao": _structure(
            "st_hao",
            "好",
            ["好"],
            ext={
                "context_ref_object_id": "st_you",
                "context_owner_structure_id": "st_you",
                "context_path_ids": ["st_you"],
                "context_text": "你",
            },
        ),
    }
    dbs = {"st_you": {"diff_table": []}, "st_hao": {"diff_table": []}}
    hdb = _FakeHDB(structures=structures, dbs=dbs)
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "context_match_v2",
            "cs_v2_audit_only": False,
            "context_concat_v2_enabled": True,
            "max_events_per_tick": 1,
        }
    )

    pool_1 = _FakePool(
        items=[
            {"item_id": "spi_you_1", "ref_object_id": "st_you", "ref_object_type": "st", "display": "你", "er": 2.2, "ev": 0.3, "cp_abs": 1.9, "salience_score": 2.2},
            {"item_id": "spi_hao_1", "ref_object_id": "st_hao", "ref_object_type": "st", "display": "好", "er": 1.6, "ev": 0.4, "cp_abs": 1.2, "salience_score": 1.6},
        ]
    )
    pool_2 = _FakePool(
        items=[
            {"item_id": "spi_you_2", "ref_object_id": "st_you", "ref_object_type": "st", "display": "你", "er": 2.2, "ev": 0.3, "cp_abs": 1.9, "salience_score": 2.2},
            {"item_id": "spi_hao_2", "ref_object_id": "st_hao", "ref_object_type": "st", "display": "好", "er": 1.6, "ev": 0.4, "cp_abs": 1.2, "salience_score": 1.6},
        ]
    )

    first = engine.run(pool=pool_1, hdb=hdb, trace_id="cs_concat_reuse_1", tick_id="cs_concat_reuse_1")
    second = engine.run(pool=pool_2, hdb=hdb, trace_id="cs_concat_reuse_2", tick_id="cs_concat_reuse_2")

    assert first["success"] is True
    assert second["success"] is True
    pb_structures = [obj for obj in hdb._structure_store.iter_structures() if obj.get("structure", {}).get("flat_tokens", []) == ["你", "好"]]
    assert len(pb_structures) == 1
    action = second["data"]["actions"][0]
    assert action["existing_structure_reused"] is True
    assert action["created_structure"] is False


def test_empty_cognitive_stitching_meta_container_is_not_treated_as_event():
    """
    Regression:
    Some runtime paths may create an empty `meta.ext.cognitive_stitching` dict container.
    The CS engine must NOT treat "any dict" as an event marker, otherwise plain ST items
    will be incorrectly shown in the CS narrative panel.
    """
    engine = CognitiveStitchingEngine(config_override={"enabled": True})
    item = {
        "ref_object_type": "st",
        "ref_object_id": "st_plain",
        "ref_snapshot": {"structure_ext": {}},
        "meta": {"ext": {"cognitive_stitching": {}}},  # empty container should not count
    }
    assert engine._is_cognitive_stitching_event_state_item(item) is False


def test_enabled_mode_creates_event_from_diff_table_edge():
    structures = {
        "st_a": _structure("st_a", "A", ["A"]),
        "st_b": _structure("st_b", "B", ["B"]),
    }
    dbs = {
        "st_a": {
            "diff_table": [
                {
                    "target_id": "st_b",
                    "base_weight": 1.2,
                    "entry_type": "structure_ref",
                }
            ]
        }
    }
    pool = _FakePool(
        items=[
            {"item_id": "spi_a", "ref_object_id": "st_a", "ref_object_type": "st", "display": "A", "er": 1.5, "ev": 0.3, "cp_abs": 1.2, "salience_score": 1.5},
            {"item_id": "spi_b", "ref_object_id": "st_b", "ref_object_type": "st", "display": "B", "er": 1.1, "ev": 0.2, "cp_abs": 0.9, "salience_score": 1.1},
        ]
    )
    hdb = _FakeHDB(structures=structures, dbs=dbs)
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "legacy_event",
            "max_events_per_tick": 1,
            "min_candidate_score": 0.05,
            "enable_persist_events_to_hdb": False,
            "insert_event_runtime_items_into_state_pool": True,
        }
    )

    result = engine.run(pool=pool, hdb=hdb, trace_id="cs_enabled", tick_id="cs_enabled")

    assert result["success"] is True
    assert result["data"]["action_count"] == 1
    assert result["data"]["created_count"] == 1
    assert pool.insert_calls
    assert len(pool.energy_calls) >= 2
    assert pool.insert_calls[0]["structure"]["member_refs"] == ["st_a", "st_b"]
    assert len(pool.insert_calls[0]["structure"]["ext"]["cognitive_stitching"]["component_ledger"]) == 2
    assert result["data"]["narrative_top_items"]


def test_existing_event_can_extend_to_new_right_end():
    structures = {
        "st_a": _structure("st_a", "A", ["A"]),
        "st_b": _structure("st_b", "B", ["B"]),
        "st_c": _structure("st_c", "C", ["C"]),
    }
    dbs = {
        "st_b": {
            "diff_table": [
                {
                    "target_id": "st_c",
                    "base_weight": 1.3,
                    "entry_type": "structure_ref",
                }
            ]
        }
    }
    event_runtime = _event_runtime_object(["st_a", "st_b"], ["A", "B"], er=1.5, ev=0.2)
    pool = _FakePool(
        items=[
            {"item_id": "spi_event_ab", "ref_object_id": event_runtime["id"], "ref_object_type": "st", "display": "A -> B", "er": 1.5, "ev": 0.2, "cp_abs": 1.3, "salience_score": 1.5},
            {"item_id": "spi_c", "ref_object_id": "st_c", "ref_object_type": "st", "display": "C", "er": 1.2, "ev": 0.2, "cp_abs": 1.0, "salience_score": 1.2},
        ]
    )
    pool._store.by_ref[event_runtime["id"]] = {"id": "spi_event_ab", "ref_object_id": event_runtime["id"]}
    hdb = _FakeHDB(structures=structures, dbs=dbs)
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "max_events_per_tick": 1,
            "min_candidate_score": 0.05,
            "enable_event_extend": True,
            "enable_event_merge": False,
            "enable_persist_events_to_hdb": False,
            "insert_event_runtime_items_into_state_pool": True,
        }
    )

    result = engine.run(pool=pool, hdb=hdb, trace_id="cs_extend", tick_id="cs_extend")

    assert result["success"] is True
    assert result["data"]["extended_count"] == 1
    assert pool.insert_calls
    assert any(call.get("id") == "cs_event::st_a::st_b::st_c" for call in pool.insert_calls)
    assert result["data"]["actions"][0]["action_family"] == "extend_event"


def test_event_to_event_bridge_merge_creates_longer_event():
    structures = {
        "st_a": _structure("st_a", "A", ["A"]),
        "st_b": _structure("st_b", "B", ["B"]),
        "st_c": _structure("st_c", "C", ["C"]),
        "st_d": _structure("st_d", "D", ["D"]),
        "st_e": _structure("st_e", "E", ["E"]),
        "st_f": _structure("st_f", "F", ["F"]),
        "st_g": _structure("st_g", "G", ["G"]),
        "st_h": _structure("st_h", "H", ["H"]),
    }
    dbs = {
        "st_d": {
            "diff_table": [
                {
                    "target_id": "st_e",
                    "base_weight": 1.25,
                    "entry_type": "structure_ref",
                }
            ]
        }
    }
    left_event = _event_runtime_object(["st_a", "st_b", "st_c", "st_d"], ["A", "B", "C", "D"], er=1.8, ev=0.3)
    right_event = _event_runtime_object(["st_e", "st_f", "st_g", "st_h"], ["E", "F", "G", "H"], er=1.6, ev=0.3)
    pool = _FakePool(
        items=[
            {"item_id": "spi_left", "ref_object_id": left_event["id"], "ref_object_type": "st", "display": "A -> B -> C -> D", "er": 1.8, "ev": 0.3, "cp_abs": 1.5, "salience_score": 1.8},
            {"item_id": "spi_right", "ref_object_id": right_event["id"], "ref_object_type": "st", "display": "E -> F -> G -> H", "er": 1.6, "ev": 0.3, "cp_abs": 1.3, "salience_score": 1.6},
        ]
    )
    pool._store.by_ref[left_event["id"]] = {"id": "spi_left", "ref_object_id": left_event["id"]}
    pool._store.by_ref[right_event["id"]] = {"id": "spi_right", "ref_object_id": right_event["id"]}
    hdb = _FakeHDB(structures=structures, dbs=dbs)
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "max_events_per_tick": 1,
            "min_candidate_score": 0.05,
            "enable_event_extend": False,
            "enable_event_merge": True,
            "enable_persist_events_to_hdb": False,
            "insert_event_runtime_items_into_state_pool": True,
        }
    )

    result = engine.run(pool=pool, hdb=hdb, trace_id="cs_merge", tick_id="cs_merge")

    assert result["success"] is True
    assert result["data"]["merged_count"] == 1
    assert pool.insert_calls
    assert any(call.get("id") == "cs_event::st_a::st_b::st_c::st_d::st_e::st_f::st_g::st_h" for call in pool.insert_calls)
    assert result["data"]["actions"][0]["action_family"] == "merge_event"


def test_run_event_grasp_binds_attribute_to_event_in_cam():
    engine = CognitiveStitchingEngine(config_override={"enabled": True})
    pool = StatePool(config_override={"log_dir": ""})

    event_ref_id = "cs_event::st_a::st_b"
    runtime_object = {
        "id": event_ref_id,
        "object_type": "st",
        "sub_type": "cognitive_stitching_event",
        "content": {"raw": "A -> B", "display": "A -> B", "normalized": "A -> B"},
        "energy": {"er": 1.0, "ev": 0.2, "ownership_level": "aggregated_from_st", "computed_from_children": True},
        "structure": {
            "display_text": "A -> B",
            "flat_tokens": ["A", "B"],
            "token_count": 2,
            "sequence_groups": [
                {"group_index": 0, "tokens": ["A"]},
                {"group_index": 1, "tokens": ["B"]},
            ],
            "member_refs": ["st_a", "st_b"],
            "content_signature": event_ref_id,
            "semantic_signature": event_ref_id,
            "ext": {
                "cognitive_stitching": {
                    "member_refs": ["st_a", "st_b"],
                    "component_profile": [
                        {"index": 0, "ref_id": "st_a", "display": "A", "share": 0.55},
                        {"index": 1, "ref_id": "st_b", "display": "B", "share": 0.45},
                    ],
                    "component_ledger": [
                        {"index": 0, "ref_id": "st_a", "display": "A", "tokens": ["A"], "profile_share": 0.55, "er": 0.6, "ev": 0.1, "cp_abs": 0.5},
                        {"index": 1, "ref_id": "st_b", "display": "B", "tokens": ["B"], "profile_share": 0.45, "er": 0.4, "ev": 0.1, "cp_abs": 0.3},
                    ],
                }
            },
        },
        "source": {"parent_ids": ["st_a", "st_b"]},
    }
    insert_res = pool.insert_runtime_node(
        runtime_object=runtime_object,
        trace_id="eg_insert",
        tick_id="eg_insert",
        allow_merge=False,
        source_module="test",
        reason="insert_event",
    )
    item_id = str(insert_res.get("data", {}).get("item_id", "") or "")
    assert item_id

    attention_snapshot = {
        "top_items": [
            {"item_id": item_id, "ref_object_type": "st", "ref_object_id": event_ref_id},
        ]
    }
    res = engine.run_event_grasp(pool=pool, attention_snapshot=attention_snapshot, trace_id="eg", tick_id="eg")
    assert res["success"] is True
    assert res["data"]["emitted_count"] == 1

    state_item = pool._store.get(item_id)
    bound = list((state_item.get("ext", {}) or {}).get("bound_attributes", []) or [])
    assert any((a.get("content", {}) or {}).get("attribute_name") == "event_grasp" for a in bound)

    narrative = engine._collect_narrative_top_items(pool=pool, trace_id="eg", tick_id="eg")
    assert narrative
    assert narrative[0].get("event_grasp", 0.0) > 0.0


def test_run_uses_post_cs_action_event_for_grasp_when_pre_cs_cam_has_no_event():
    structures = {
        "st_a": _structure("st_a", "A", ["A"]),
        "st_b": _structure("st_b", "B", ["B"]),
    }
    dbs = {
        "st_a": {
            "diff_table": [
                {
                    "target_id": "st_b",
                    "base_weight": 1.2,
                    "entry_type": "structure_ref",
                }
            ]
        }
    }
    pool = _FakePool(
        items=[
            {
                "item_id": "spi_a",
                "ref_object_id": "st_a",
                "ref_object_type": "st",
                "display": "A",
                "er": 0.9,
                "ev": 0.1,
                "cp_abs": 0.8,
                "salience_score": 0.9,
            },
            {
                "item_id": "spi_b",
                "ref_object_id": "st_b",
                "ref_object_type": "st",
                "display": "B",
                "er": 0.8,
                "ev": 0.2,
                "cp_abs": 0.6,
                "salience_score": 0.8,
            },
        ]
    )
    hdb = _FakeHDB(structures=structures, dbs=dbs)
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "legacy_event",
            "insert_event_runtime_items_into_state_pool": True,
            "enable_event_grasp": True,
            "event_grasp_include_post_cs_action_events": True,
        }
    )

    result = engine.run(
        pool=pool,
        hdb=hdb,
        attention_snapshot={
            "top_items": [
                {
                    "item_id": "spi_a",
                    "ref_object_id": "st_a",
                    "ref_object_type": "st",
                },
                {
                    "item_id": "spi_b",
                    "ref_object_id": "st_b",
                    "ref_object_type": "st",
                },
            ]
        },
        trace_id="cs_post_action_grasp",
        tick_id="cs_post_action_grasp",
    )

    assert result["success"] is True
    assert result["data"]["created_count"] == 1
    assert result["data"]["event_grasp"]["reason"] == "ok"
    assert result["data"]["event_grasp"]["emitted_count"] == 1
    assert result["data"]["event_grasp"]["focus_mode"] == "cam_plus_post_cs_action"
    assert result["data"]["event_grasp"]["post_action_seed_count"] == 1
    assert result["data"]["event_grasp"]["signals"][0]["grasp"] > 0.0
    assert "post_cs_action" in result["data"]["event_grasp"]["signals"][0]["selection_sources"]
    assert result["data"]["narrative_top_items"]
    assert result["data"]["narrative_top_items"][0]["event_grasp"] > 0.0


def test_idle_consolidate_materializes_esdb_overlay():
    structures = {
        "st_a": _structure("st_a", "A", ["A"]),
        "st_b": _structure("st_b", "B", ["B"]),
        "st_c": _structure("st_c", "C", ["C"]),
    }
    dbs = {
        # Create event: st_a -> st_b
        # Overlay to materialize: st_a/st_b -> st_c
        "st_a": {"diff_table": [
            {"target_id": "st_b", "base_weight": 1.2, "entry_type": "structure_ref"},
            {"target_id": "st_c", "base_weight": 1.0, "entry_type": "structure_ref"},
        ]},
        "st_b": {"diff_table": [{"target_id": "st_c", "base_weight": 0.8, "entry_type": "structure_ref"}]},
    }
    pool = _FakePool(
        items=[
            {"item_id": "spi_a", "ref_object_id": "st_a", "ref_object_type": "st", "display": "A", "er": 1.4, "ev": 0.2, "cp_abs": 1.2, "salience_score": 1.4},
            {"item_id": "spi_b", "ref_object_id": "st_b", "ref_object_type": "st", "display": "B", "er": 1.2, "ev": 0.2, "cp_abs": 1.0, "salience_score": 1.2},
        ]
    )
    hdb = _FakeHDB(structures=structures, dbs=dbs)
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "legacy_event",
            "max_events_per_tick": 1,
            "min_candidate_score": 0.05,
            "enable_persist_events_to_hdb": False,
            "insert_event_runtime_items_into_state_pool": True,
        }
    )

    run_res = engine.run(pool=pool, hdb=hdb, trace_id="cs_esdb", tick_id="cs_esdb")
    assert run_res["success"] is True
    assert run_res["data"]["created_count"] == 1

    cons = engine.idle_consolidate(hdb=hdb, trace_id="cs_esdb_cons", tick_id="cs_esdb_cons")
    assert cons["success"] is True

    event_id = "cs_event::st_a::st_b"
    assert event_id in engine._esdb
    es_entry = engine._esdb[event_id]
    assert es_entry.get("materialized") is True
    assert es_entry.get("parents") == []
    mat = list(es_entry.get("materialized_diff_table", []) or [])
    assert any(row.get("target_id") == "st_c" for row in mat)


def test_materialized_esdb_overlay_still_merges_delta_updates():
    structures = {
        "st_a": _structure("st_a", "A", ["A"]),
        "st_b": _structure("st_b", "B", ["B"]),
        "st_c": _structure("st_c", "C", ["C"]),
        "st_d": _structure("st_d", "D", ["D"]),
    }
    dbs = {
        "st_a": {"diff_table": [{"target_id": "st_b", "base_weight": 1.2, "entry_type": "structure_ref"}]},
        "st_b": {"diff_table": [{"target_id": "st_c", "base_weight": 1.0, "entry_type": "structure_ref"}]},
        "st_c": {"diff_table": [{"target_id": "st_d", "base_weight": 1.5, "entry_type": "structure_ref"}]},
    }
    pool = _FakePool(
        items=[
            {"item_id": "spi_a", "ref_object_id": "st_a", "ref_object_type": "st", "display": "A", "er": 1.4, "ev": 0.2, "cp_abs": 1.2, "salience_score": 1.4},
            {"item_id": "spi_b", "ref_object_id": "st_b", "ref_object_type": "st", "display": "B", "er": 1.2, "ev": 0.2, "cp_abs": 1.0, "salience_score": 1.2},
        ]
    )
    hdb = _FakeHDB(structures=structures, dbs=dbs)
    engine = CognitiveStitchingEngine(
        config_override={
            "enabled": True,
            "stitching_mode": "legacy_event",
            "max_events_per_tick": 1,
            "min_candidate_score": 0.05,
            "enable_persist_events_to_hdb": False,
            "insert_event_runtime_items_into_state_pool": True,
        }
    )

    run_res = engine.run(pool=pool, hdb=hdb, trace_id="cs_esdb2", tick_id="cs_esdb2")
    assert run_res["success"] is True
    assert run_res["data"]["created_count"] == 1

    cons = engine.idle_consolidate(hdb=hdb, trace_id="cs_esdb2_cons", tick_id="cs_esdb2_cons")
    assert cons["success"] is True

    event_id = "cs_event::st_a::st_b"
    assert event_id in engine._esdb
    assert engine._esdb[event_id].get("materialized") is True

    # After consolidation, delta can still grow; overlay open should merge it.
    engine._esdb_delta_upsert_edge(
        event_ref_id=event_id,
        target_id="st_d",
        base_weight=9.0,
        source_ref="st_c",
        tick_id="cs_esdb2_delta",
        action_type="extend_event",
        distance=0,
    )
    rows, total = engine._esdb_open_overlay_top_diff_entries(event_ref_id=event_id, hdb=hdb)
    assert total > 0.0
    assert any(r.get("target_id") == "st_d" for r in rows)
