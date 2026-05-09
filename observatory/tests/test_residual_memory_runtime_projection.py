# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from observatory._app import ObservatoryApp


def _seed_hdb_structure(app: ObservatoryApp, display_text: str, flat_tokens: list[str]) -> dict:
    structure_obj, _ = app.hdb._structure_store.create_structure(
        structure_payload={
            "sub_type": "stimulus_sequence_structure",
            "display_text": display_text,
            "flat_tokens": list(flat_tokens),
            "sequence_groups": [
                {
                    "group_index": 0,
                    "source_type": "pytest",
                    "origin_frame_id": f"seed_{display_text}",
                    "tokens": list(flat_tokens),
                }
            ],
            "content_signature": f"pytest::{display_text}",
            "semantic_signature": f"pytest::{display_text}",
        },
        trace_id=f"seed_hdb_structure::{display_text}",
        tick_id=f"seed_hdb_structure::{display_text}",
        source_interface="pytest_seed_structure",
        origin="unit_test_seed",
    )
    return structure_obj


def _seed_episodic_memory(app: ObservatoryApp, *, structure_id: str, display_text: str) -> dict:
    return app.hdb._episodic_store.append(
        {
            "event_summary": display_text,
            "structure_refs": [structure_id],
            "meta": {
                "confidence": 1.0,
                "field_registry_version": 1,
                "debug": {},
                "ext": {
                    "memory_material": {
                        "memory_kind": "stimulus_packet",
                        "grouped_display_text": display_text,
                        "ordered_structure_ids": [structure_id],
                        "sequence_groups": [
                            {
                                "group_index": 0,
                                "units": [
                                    {
                                        "object_type": "sa",
                                        "unit_id": f"sa_{structure_id}",
                                        "token": display_text,
                                        "display_text": display_text,
                                        "unit_role": "feature",
                                        "sequence_index": 0,
                                        "group_index": 0,
                                    }
                                ],
                            }
                        ],
                    }
                },
            },
        },
        trace_id=f"pytest_seed_memory::{display_text}",
        tick_id=f"pytest_seed_memory::{display_text}",
    )


def _residual_tail_memory_runtime_object(*, memory_id: str, display_text: str, er: float = 0.5) -> dict:
    ext = {
        "source_em_id": memory_id,
        "memory_id": memory_id,
        "residual_origin_kind": "residual_tail_memory_projection",
        "residual_origin_entry_id": memory_id,
        "component_energy": {
            "ownership_level": "sa_component_audit",
            "memory_id": memory_id,
            "tail_component_er_share": er,
            "tail_component_ev_share": 0.0,
        },
    }
    return {
        "id": memory_id,
        "object_type": "em",
        "sub_type": "stimulus_tail_memory_runtime",
        "content": {
            "raw": display_text,
            "display": display_text,
            "normalized": display_text,
        },
        "energy": {
            "er": er,
            "ev": 0.0,
            "ownership_level": "sa_component_audit",
        },
        "memory": {
            "memory_id": memory_id,
            "event_summary": "stimulus-level retrieval-storage",
            "structure_refs": [],
            "group_refs": [],
            "backing_structure_id": "",
            "display_text": display_text,
            "grouped_display_text": display_text,
            "sequence_groups": [],
        },
        "source": {
            "module": "pytest",
            "interface": "_insert_residual_tail_memory_projection_to_pool",
            "origin": "residual_tail_memory_projection",
            "origin_id": memory_id,
            "parent_ids": [],
        },
        "ext": dict(ext),
        "meta": {
            "confidence": 1.0,
            "field_registry_version": "runtime",
            "debug": {},
            "ext": dict(ext),
        },
    }


def test_residual_memory_runtime_projection_em_rollback_keeps_legacy_em_shell():
    temp_hdb_dir = tempfile.mkdtemp(prefix="observatory_memory_runtime_projection_")
    app = ObservatoryApp(
        config_override={
            "export_html": False,
            "export_json": False,
            "auto_open_html_report": False,
            "web_auto_open_browser": False,
            "hdb_enable_background_repair": False,
            "hdb_data_dir": temp_hdb_dir,
            "residual_memory_as_structure_enabled": True,
            "residual_memory_as_structure_shadow_mode": False,
            "residual_memory_runtime_object_type": "em",
        }
    )
    try:
        episodic = app.hdb._episodic_store.append(
            {
                "event_summary": "天气动作记忆",
                "structure_refs": ["st_weather_context"],
                "origin": "pytest_memory_runtime_projection",
                "meta": {
                    "confidence": 1.0,
                    "field_registry_version": 1,
                    "debug": {},
                    "ext": {
                        "memory_material": {
                            "memory_kind": "stimulus_packet",
                            "grouped_display_text": "天气动作+奖励",
                            "sequence_groups": [
                                {
                                    "group_index": 0,
                                    "units": [
                                        {
                                            "object_type": "sa",
                                            "unit_id": "sa_weather_action",
                                            "token": "天气动作",
                                            "display_text": "天气动作",
                                            "unit_role": "feature",
                                            "sequence_index": 0,
                                            "group_index": 0,
                                        },
                                        {
                                            "object_type": "sa",
                                            "unit_id": "sa_reward_signal",
                                            "token": "reward_signal",
                                            "display_text": "reward_signal",
                                            "unit_role": "feature",
                                            "sequence_index": 1,
                                            "group_index": 0,
                                        },
                                    ],
                                }
                            ],
                        }
                    },
                },
            },
            trace_id="pytest_memory_runtime_projection",
            tick_id="cycle_memory_runtime_projection_0001",
        )

        projection = app._project_memory_activation_runtime_items(
            memory_items=[
                {
                    "memory_id": episodic["id"],
                    "display_text": "天气动作+奖励",
                    "grouped_display_text": "天气动作+奖励",
                    "backing_structure_ids": ["st_weather_context"],
                    "last_delta_er": 0.18,
                    "last_delta_ev": 0.42,
                }
            ],
            trace_id="pytest_memory_runtime_projection",
            tick_id="cycle_memory_runtime_projection_0001",
        )

        assert projection["enabled"] is True
        assert projection["shadow_mode"] is False
        assert projection["summary"]["inserted_count"] == 1
        assert projection["items"][0]["projected_ref_object_type"] == "em"

        snapshot = app.pool.get_state_snapshot(
            trace_id="pytest_memory_runtime_projection_snapshot",
            tick_id="cycle_memory_runtime_projection_0001",
            top_k=None,
        )["data"]["snapshot"]
        by_ref = {
            str(row.get("ref_object_id", "")): row
            for row in (snapshot.get("top_items", []) or [])
            if isinstance(row, dict)
        }
        row = by_ref[episodic["id"]]
        assert row["ref_object_type"] == "em"
        ref_snapshot = row.get("ref_snapshot", {}) or {}
        assert ref_snapshot.get("source_em_id") == episodic["id"]
        assert ref_snapshot.get("residual_kind") == "memory"
        assert ref_snapshot.get("context_owner_id") == "st_weather_context"
        assert "天气动作+奖励" in str(ref_snapshot.get("content_display", ""))

        cam_snapshot, _attention_report = app._build_attention_memory_stub(
            "pytest_memory_runtime_projection_cam",
            "cycle_memory_runtime_projection_0001",
        )
        assert any(
            str(item.get("ref_object_type", "")) == "em" and str(item.get("ref_object_id", "")) == episodic["id"]
            for item in (cam_snapshot.get("top_items", []) or [])
        )
    finally:
        app.close()
        shutil.rmtree(temp_hdb_dir, ignore_errors=True)


def test_residual_memory_runtime_projection_default_config_prefers_em_terminal_semantics():
    temp_hdb_dir = tempfile.mkdtemp(prefix="observatory_memory_runtime_projection_default_")
    app = ObservatoryApp(
        config_override={
            "export_html": False,
            "export_json": False,
            "auto_open_html_report": False,
            "web_auto_open_browser": False,
            "hdb_enable_background_repair": False,
            "hdb_data_dir": temp_hdb_dir,
            "residual_memory_as_structure_enabled": True,
        }
    )
    try:
        assert app._config["dedicated_memory_pool_enabled"] is False
        assert app._config["residual_memory_as_structure_shadow_mode"] is False
        assert app._config["residual_memory_runtime_object_type"] == "em"
        structure_obj = _seed_hdb_structure(app, display_text="默认配置记忆", flat_tokens=["默认配置记忆"])
        structure_id = str(structure_obj["id"])
        episodic = app.hdb._episodic_store.append(
            {
                "event_summary": "默认配置记忆",
                "structure_refs": [structure_id],
                "meta": {
                    "confidence": 1.0,
                    "field_registry_version": 1,
                    "debug": {},
                    "ext": {
                        "memory_material": {
                            "memory_kind": "stimulus_packet",
                            "grouped_display_text": "默认配置记忆",
                            "sequence_groups": [
                                {
                                    "group_index": 0,
                                    "units": [
                                        {
                                            "object_type": "sa",
                                            "unit_id": "sa_default_memory",
                                            "token": "默认配置记忆",
                                            "display_text": "默认配置记忆",
                                            "unit_role": "feature",
                                            "sequence_index": 0,
                                            "group_index": 0,
                                        }
                                    ],
                                }
                            ],
                        }
                    },
                },
            },
            trace_id="pytest_default_memory_runtime_projection",
            tick_id="cycle_default_memory_runtime_projection_0001",
        )
        projection = app._project_memory_activation_runtime_items(
            memory_items=[
                {
                    "memory_id": episodic["id"],
                    "display_text": "默认配置记忆",
                    "grouped_display_text": "默认配置记忆",
                    "backing_structure_ids": [structure_id],
                    "last_delta_er": 0.1,
                    "last_delta_ev": 0.9,
                }
            ],
            trace_id="pytest_default_memory_runtime_projection",
            tick_id="cycle_default_memory_runtime_projection_0001",
        )
        assert projection["summary"]["inserted_count"] == 1
        assert projection["items"][0]["projected_ref_object_type"] == "em"
        assert projection["items"][0]["target_ref_object_id"] == episodic["id"]

        snapshot = app.pool.get_state_snapshot(
            trace_id="pytest_default_memory_runtime_projection_snapshot",
            tick_id="cycle_default_memory_runtime_projection_0001",
            top_k=None,
        )["data"]["snapshot"]
        by_ref = {
            str(row.get("ref_object_id", "")): row
            for row in (snapshot.get("top_items", []) or [])
            if isinstance(row, dict)
        }
        row = by_ref[episodic["id"]]
        assert row["ref_object_type"] == "em"
        ref_snapshot = row.get("ref_snapshot", {}) or {}
        assert ref_snapshot.get("source_em_id") == episodic["id"]
        assert ref_snapshot.get("memory_id") == episodic["id"]
        assert ref_snapshot.get("residual_kind") == "memory"
        assert ref_snapshot.get("context_owner_id") == structure_id
        assert "默认配置记忆" in str(ref_snapshot.get("content_display", ""))

        _cam_snapshot, attention_report = app._build_attention_memory_stub(
            "pytest_default_memory_runtime_projection_cam",
            "cycle_default_memory_runtime_projection_0001",
        )
        assert attention_report.get("state_pool_candidate_count", 0) >= 1
    finally:
        app.close()
        shutil.rmtree(temp_hdb_dir, ignore_errors=True)


def test_residual_memory_runtime_projection_explicit_st_override_merges_tail_when_projection_arrives_first():
    temp_hdb_dir = tempfile.mkdtemp(prefix="observatory_memory_runtime_projection_alias_a_")
    app = ObservatoryApp(
        config_override={
            "export_html": False,
            "export_json": False,
            "auto_open_html_report": False,
            "web_auto_open_browser": False,
            "hdb_enable_background_repair": False,
            "hdb_data_dir": temp_hdb_dir,
            "residual_memory_as_structure_enabled": True,
        }
    )
    try:
        structure_obj = _seed_hdb_structure(app, display_text="别名合并记忆", flat_tokens=["别名合并记忆"])
        structure_id = str(structure_obj["id"])
        episodic = _seed_episodic_memory(app, structure_id=structure_id, display_text="别名合并记忆")
        memory_id = str(episodic["id"])

        projection = app.hdb.make_runtime_memory_object(
            memory_id,
            er=0.0,
            ev=0.7,
            reason="pytest_memory_runtime_projection",
            display_text="别名合并记忆",
            backing_structure_id=structure_id,
            runtime_object_type="st",
        )
        assert projection is not None
        first = app.pool.insert_runtime_node(
            projection,
            trace_id="pytest_projection_first",
            tick_id="pytest_projection_first",
            source_module="pytest",
            reason="memory_runtime_projection",
        )
        assert first["success"] is True

        tail = _residual_tail_memory_runtime_object(memory_id=memory_id, display_text="别名合并记忆尾巴", er=0.5)
        second = app.pool.insert_runtime_node(
            tail,
            trace_id="pytest_tail_second",
            tick_id="pytest_tail_second",
            source_module="pytest",
            reason="residual_tail_memory_projection",
            fast_ref_hit_energy_merge=True,
        )
        assert second["success"] is True
        assert second["data"]["merged"] is True

        by_structure = app.pool._store.get_by_ref(structure_id)
        by_memory = app.pool._store.get_by_ref(memory_id)
        assert by_structure is not None
        assert by_memory is by_structure
        assert by_structure["ref_object_type"] == "em"
        assert by_structure["ref_object_id"] == memory_id
        assert structure_id in by_structure.get("ref_alias_ids", [])
        assert memory_id in by_structure.get("ref_alias_ids", [])
        assert float(by_structure["energy"]["ev"]) > 0.0
        assert float(by_structure["energy"]["er"]) > 0.0

        related = [
            item for item in app.pool._store.get_all()
            if item.get("ref_object_id") in {structure_id, memory_id}
            or memory_id in list(item.get("ref_alias_ids", []) or [])
        ]
        assert len(related) == 1
    finally:
        app.close()
        shutil.rmtree(temp_hdb_dir, ignore_errors=True)


def test_residual_memory_runtime_projection_explicit_st_override_promotes_tail_when_projection_arrives_second():
    temp_hdb_dir = tempfile.mkdtemp(prefix="observatory_memory_runtime_projection_alias_b_")
    app = ObservatoryApp(
        config_override={
            "export_html": False,
            "export_json": False,
            "auto_open_html_report": False,
            "web_auto_open_browser": False,
            "hdb_enable_background_repair": False,
            "hdb_data_dir": temp_hdb_dir,
            "residual_memory_as_structure_enabled": True,
        }
    )
    try:
        structure_obj = _seed_hdb_structure(app, display_text="别名提升记忆", flat_tokens=["别名提升记忆"])
        structure_id = str(structure_obj["id"])
        episodic = _seed_episodic_memory(app, structure_id=structure_id, display_text="别名提升记忆")
        memory_id = str(episodic["id"])

        tail = _residual_tail_memory_runtime_object(memory_id=memory_id, display_text="别名提升记忆尾巴", er=0.5)
        first = app.pool.insert_runtime_node(
            tail,
            trace_id="pytest_tail_first",
            tick_id="pytest_tail_first",
            source_module="pytest",
            reason="residual_tail_memory_projection",
            fast_ref_hit_energy_merge=True,
        )
        assert first["success"] is True
        assert app.pool._store.get_by_ref(memory_id)["ref_object_type"] == "em"

        projection = app.hdb.make_runtime_memory_object(
            memory_id,
            er=0.0,
            ev=0.7,
            reason="pytest_memory_runtime_projection",
            display_text="别名提升记忆",
            backing_structure_id=structure_id,
            runtime_object_type="st",
        )
        assert projection is not None
        second = app.pool.insert_runtime_node(
            projection,
            trace_id="pytest_projection_second",
            tick_id="pytest_projection_second",
            source_module="pytest",
            reason="memory_runtime_projection",
        )
        assert second["success"] is True
        assert second["data"]["merged"] is True

        by_structure = app.pool._store.get_by_ref(structure_id)
        by_memory = app.pool._store.get_by_ref(memory_id)
        assert by_structure is not None
        assert by_memory is by_structure
        assert by_structure["ref_object_type"] == "em"
        assert by_structure["ref_object_id"] == memory_id
        assert structure_id in by_structure.get("ref_alias_ids", [])
        assert memory_id in by_structure.get("ref_alias_ids", [])
        assert float(by_structure["energy"]["ev"]) > 0.0
        assert float(by_structure["energy"]["er"]) > 0.0

        induction_snapshot = app._build_induction_source_snapshot(
            trace_id="pytest_alias_promoted_induction_source",
            tick_id="pytest_alias_promoted_induction_source",
        )
        assert all(
            str(item.get("ref_object_id", "") or "") != memory_id
            for item in induction_snapshot.get("top_items", [])
        )
    finally:
        app.close()
        shutil.rmtree(temp_hdb_dir, ignore_errors=True)
