# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
import tempfile

from hdb import HDB
from state_pool.main import StatePool
from time_sensor.main import TimeSensor


class _DummyStore:
    def __init__(self, items: dict[str, dict]):
        self._items = items

    def get(self, item_id: str):
        return self._items.get(item_id)

    def get_by_ref(self, ref_id: str):
        for item in self._items.values():
            if str(item.get("ref_object_id", "") or "") == str(ref_id or ""):
                return item
        return None


class _DummyPool:
    def __init__(self, items: dict[str, dict]):
        self._store = _DummyStore(items)
        self.bind_calls: list[dict] = []

    def bind_attribute_node_to_object(
        self,
        *,
        target_item_id: str,
        attribute_sa: dict,
        trace_id: str,
        tick_id: str,
        source_module: str,
        reason: str,
    ) -> dict:
        self.bind_calls.append(
            {
                "target_item_id": target_item_id,
                "attribute_sa": dict(attribute_sa),
                "trace_id": trace_id,
                "tick_id": tick_id,
                "source_module": source_module,
                "reason": reason,
            }
        )
        return {"success": True, "code": "OK", "data": {"target_item_id": target_item_id}}


def _build_pool() -> _DummyPool:
    return _DummyPool(
        {
            "item_atomic": {
                "id": "item_atomic",
                "ref_object_id": "st_atomic",
                "ref_object_type": "st",
                "ref_snapshot": {"content_display": "{A}", "token_count": 1, "flat_tokens": ["A"]},
                "energy": {"er": 0.0, "ev": 0.6},
                "ext": {"bound_attributes": []},
            },
            "item_parent": {
                "id": "item_parent",
                "ref_object_id": "st_parent",
                "ref_object_type": "st",
                "ref_snapshot": {
                    "content_display": "{ABX}",
                    "token_count": 3,
                    "flat_tokens": ["A", "B", "X"],
                    "sequence_groups": [{"group_index": 0}, {"group_index": 1}],
                },
                "energy": {"er": 0.0, "ev": 0.9},
                "ext": {"bound_attributes": []},
            },
        }
    )


def _build_memory_activation_snapshot() -> dict:
    return {
        "items": [
            {
                "memory_id": "em_1",
                "memory_created_at": 1000,
                "created_at": 1000,
                "memory_tick_index": 8,
                "last_delta_er": 0.0,
                "last_delta_ev": 1.0,
                "total_energy": 1.0,
                "display_text": "{ABX}",
            }
        ]
    }


def _build_runtime_memory_activation_snapshot() -> dict:
    snapshot = _build_memory_activation_snapshot()
    snapshot["items"][0]["backing_structure_ids"] = ["st_parent"]
    snapshot["items"][0]["structure_refs"] = ["st_parent"]
    snapshot["items"][0]["structure_ref_items"] = [{"id": "st_parent"}]
    return snapshot


def _build_runtime_memory_activation_snapshot_with_ref_items_only() -> dict:
    snapshot = _build_memory_activation_snapshot()
    snapshot["items"][0]["structure_ref_items"] = [{"id": "st_parent"}]
    return snapshot


def _build_runtime_memory_activation_snapshot_with_atomic_and_parent() -> dict:
    snapshot = _build_memory_activation_snapshot()
    snapshot["items"][0]["backing_structure_ids"] = ["st_atomic", "st_parent"]
    snapshot["items"][0]["structure_refs"] = ["st_atomic", "st_parent"]
    snapshot["items"][0]["structure_ref_items"] = [{"id": "st_atomic"}, {"id": "st_parent"}]
    return snapshot


def _build_memory_feedback_result() -> dict:
    return {
        "items": [
            {
                "memory_id": "em_1",
                "memory_kind": "stimulus_packet",
                "events": [
                    {
                        "target_item_id": "item_atomic",
                        "delta": {"delta_er": 0.0, "delta_ev": 1.0},
                    }
                ],
                "projections": [
                    {
                        "target_item_id": "item_parent",
                        "target_ref_object_id": "st_parent",
                        "target_ref_object_type": "st",
                        "structure_id": "st_parent",
                        "er": 0.0,
                        "ev": 0.35,
                    }
                ],
            }
        ]
    }


def _build_runtime_projection_feedback_result() -> dict:
    return {
        "items": [
            {
                "memory_id": "em_1",
                "memory_kind": "runtime_em_projection",
                "projections": [
                    {
                        "target_item_id": "item_parent",
                        "target_ref_object_id": "st_parent",
                        "target_ref_object_type": "st",
                        "structure_id": "st_parent",
                        "er": 0.0,
                        "ev": 0.55,
                    }
                ],
            }
        ]
    }


def _build_sensor(enable_projection_targets: bool) -> TimeSensor:
    return TimeSensor(
        config_override={
            "enabled": True,
            "time_basis": "tick",
            "enable_bucket_nodes": False,
            "enable_bind_attribute": True,
            "enable_delayed_tasks": False,
            "enable_projection_target_bindings": enable_projection_targets,
            "max_bind_targets_per_memory": 1,
            "max_projection_bind_targets_per_memory": 1,
            "max_total_bindings": 4,
            "peak_keep_ratio": 0.72,
            "projection_target_keep_ratio": 0.72,
            "memory_top_k": 8,
            "energy_gain_ratio": 0.2,
            "base_energy_source": "last_delta_energy",
        }
    )


def _build_real_hdb_with_time_structure() -> tuple[str, HDB]:
    temp_dir = tempfile.mkdtemp(prefix="time_sensor_hdb_")
    hdb = HDB(config_override={"data_dir": temp_dir, "enable_background_repair": False})
    groups = [
        {
            "group_index": 0,
            "source_type": "current",
            "origin_frame_id": "frame_time_projection",
            "order_sensitive": True,
            "units": [
                {
                    "unit_id": "u_anchor",
                    "token": "A",
                    "display_text": "A",
                    "unit_role": "feature",
                    "sequence_index": 0,
                    "source_type": "current",
                },
                {
                    "unit_id": "u_time",
                    "token": "时间感受:1.0",
                    "display_text": "时间感受:约1tick",
                    "unit_role": "attribute",
                    "attribute_name": "时间感受",
                    "attribute_value": 1.0,
                    "sequence_index": 1,
                    "source_type": "current",
                },
            ],
            "csa_bundles": [
                {
                    "bundle_id": "bundle_time_1",
                    "anchor_unit_id": "u_anchor",
                    "member_unit_ids": ["u_anchor", "u_time"],
                }
            ],
        }
    ]
    profile = hdb._cut.build_sequence_profile_from_groups(groups)
    payload = hdb._cut.make_structure_payload_from_profile(
        profile,
        confidence=0.92,
        ext={"kind": "test_time_projection"},
    )
    structure_obj, _ = hdb._structure_store.create_structure(
        structure_payload=payload,
        trace_id="ts_time_struct_seed",
        tick_id="ts_time_struct_seed",
        origin="test_time_projection",
        origin_id="test_time_projection",
        parent_ids=[],
    )
    hdb._pointer_index.register_structure(structure_obj)
    return temp_dir, hdb


def _build_real_pool() -> StatePool:
    return StatePool(
        config_override={
            "enable_script_broadcast": False,
            "placeholder_hdb_enabled": False,
            "placeholder_script_enabled": False,
            "placeholder_attention_enabled": False,
            "placeholder_emotion_enabled": False,
            "placeholder_action_enabled": False,
            "insert_attribute_sa_as_state_item": True,
            "attribute_binding_runtime_mode": "state_item",
        }
    )


def test_time_sensor_mirrors_structure_projection_targets_when_enabled():
    sensor = _build_sensor(enable_projection_targets=True)
    pool = _build_pool()

    result = sensor.run_time_feeling_tick(
        pool=pool,
        trace_id="ts_projection_on",
        tick_id="cycle_0010",
        now_ms=2000,
        memory_activation_snapshot=_build_memory_activation_snapshot(),
        memory_feedback_result=_build_memory_feedback_result(),
        source_mode="memory_activation_snapshot",
    )["data"]

    assert result["source_mode"] == "memory_activation_snapshot"
    binding_targets = {str(row.get("target_item_id", "")) for row in result.get("attribute_bindings", [])}
    binding_sources = {str(row.get("target_score_source", "")) for row in result.get("attribute_bindings", [])}
    source_counts = result.get("attribute_binding_source_counts", {})

    assert binding_targets == {"item_atomic", "item_parent"}
    assert binding_sources == {"legacy_peak", "projection_peak"}
    assert source_counts.get("legacy_peak", 0) == 1
    assert source_counts.get("projection_peak", 0) == 1


def test_time_sensor_keeps_legacy_only_when_projection_binding_disabled():
    sensor = _build_sensor(enable_projection_targets=False)
    pool = _build_pool()

    result = sensor.run_time_feeling_tick(
        pool=pool,
        trace_id="ts_projection_off",
        tick_id="cycle_0010",
        now_ms=2000,
        memory_activation_snapshot=_build_memory_activation_snapshot(),
        memory_feedback_result=_build_memory_feedback_result(),
        source_mode="memory_activation_snapshot",
    )["data"]

    assert result["source_mode"] == "memory_activation_snapshot"
    binding_targets = [str(row.get("target_item_id", "")) for row in result.get("attribute_bindings", [])]
    source_counts = result.get("attribute_binding_source_counts", {})

    assert binding_targets == ["item_atomic"]
    assert source_counts.get("legacy_peak", 0) == 1
    assert source_counts.get("projection_peak", 0) == 0


def test_time_sensor_accepts_runtime_memory_projection_source_mode():
    sensor = _build_sensor(enable_projection_targets=True)
    pool = _build_pool()

    result = sensor.run_time_feeling_tick(
        pool=pool,
        trace_id="ts_runtime_projection",
        tick_id="cycle_0010",
        now_ms=2000,
        memory_activation_snapshot=_build_runtime_memory_activation_snapshot(),
        memory_feedback_result=_build_runtime_projection_feedback_result(),
        source_mode="runtime_memory_projection",
    )["data"]

    assert result["source_mode"] == "runtime_memory_projection"
    binding_targets = {str(row.get("target_item_id", "")) for row in result.get("attribute_bindings", [])}
    assert binding_targets == {"item_parent"}


def test_time_sensor_runtime_memory_projection_no_longer_requires_feedback_result():
    sensor = _build_sensor(enable_projection_targets=True)
    pool = _build_pool()

    result = sensor.run_time_feeling_tick(
        pool=pool,
        trace_id="ts_runtime_projection_snapshot_only",
        tick_id="cycle_0010",
        now_ms=2000,
        memory_activation_snapshot=_build_runtime_memory_activation_snapshot(),
        memory_feedback_result=None,
        source_mode="runtime_memory_projection",
    )["data"]

    assert result["source_mode"] == "runtime_memory_projection"
    binding_targets = {str(row.get("target_item_id", "")) for row in result.get("attribute_bindings", [])}
    binding_sources = {str(row.get("target_score_source", "")) for row in result.get("attribute_bindings", [])}
    source_counts = result.get("attribute_binding_source_counts", {})

    assert binding_targets == {"item_parent"}
    assert binding_sources == {"runtime_projection_peak"}
    assert source_counts.get("runtime_projection_peak", 0) == 1


def test_time_sensor_runtime_memory_projection_prefers_richer_parent_structure_target():
    sensor = _build_sensor(enable_projection_targets=True)
    pool = _build_pool()

    result = sensor.run_time_feeling_tick(
        pool=pool,
        trace_id="ts_runtime_projection_richer_parent",
        tick_id="cycle_0010",
        now_ms=2000,
        memory_activation_snapshot=_build_runtime_memory_activation_snapshot_with_atomic_and_parent(),
        memory_feedback_result=None,
        source_mode="runtime_memory_projection",
    )["data"]

    assert result["source_mode"] == "runtime_memory_projection"
    binding_targets = [str(row.get("target_item_id", "")) for row in result.get("attribute_bindings", [])]
    binding_sources = [str(row.get("target_score_source", "")) for row in result.get("attribute_bindings", [])]

    assert binding_targets == ["item_parent"]
    assert binding_sources == ["runtime_projection_peak"]


def test_time_sensor_delayed_tasks_register_anchor_and_structure_projection_in_parallel():
    temp_dir, hdb = _build_real_hdb_with_time_structure()
    pool = _build_real_pool()
    try:
        runtime_obj = hdb.make_runtime_structure_object(
            next(iter(hdb._structure_store.iter_structures()))["id"],
            er=0.6,
            ev=0.2,
            reason="test_runtime_seed",
        )
        assert runtime_obj is not None
        pool.insert_runtime_node(
            runtime_object=runtime_obj,
            trace_id="ts_pool_seed",
            tick_id="cycle_0010",
            allow_merge=True,
            source_module="test",
            reason="ts_pool_seed",
        )
        structure_id = str(runtime_obj.get("id", "") or "")
        seeded_item = pool._store.get_by_ref(structure_id)
        assert seeded_item is not None

        sensor = TimeSensor(
            config_override={
                "enabled": True,
                "time_basis": "tick",
                "enable_bucket_nodes": False,
                "enable_bind_attribute": True,
                "enable_delayed_tasks": True,
                "enable_projection_target_bindings": True,
                "enable_runtime_snapshot_target_bindings": True,
                "memory_top_k": 4,
                "energy_gain_ratio": 0.2,
                "base_energy_source": "last_delta_energy",
                "max_bind_targets_per_memory": 1,
                "max_projection_bind_targets_per_memory": 1,
                "max_total_bindings": 4,
                "delayed_task_register_min_delta_energy": 0.01,
                "delayed_task_min_interval_ticks": 1,
                "delayed_task_due_tolerance_ticks": 0,
                "delayed_task_energy_ratio": 1.0,
                "delayed_task_energy_min": 0.05,
                "delayed_task_energy_max": 1.0,
            }
        )
        snapshot = {
            "items": [
                {
                    "memory_id": "em_time_1",
                    "memory_created_at": 1000,
                    "created_at": 1000,
                    "memory_tick_index": 10,
                    "last_delta_er": 0.0,
                    "last_delta_ev": 1.0,
                    "total_energy": 1.0,
                    "display_text": "A",
                    "backing_structure_ids": [structure_id],
                    "structure_refs": [structure_id],
                    "structure_ref_items": [{"id": structure_id}],
                }
            ]
        }

        result = sensor.run_time_feeling_tick(
            pool=pool,
            hdb=hdb,
            trace_id="ts_dual_register",
            tick_id="cycle_0010",
            now_ms=2000,
            memory_activation_snapshot=snapshot,
            memory_feedback_result=None,
            source_mode="runtime_memory_projection",
        )["data"]

        delayed_reg = result.get("delayed_tasks", {}).get("registered", {})
        task_rows = list(delayed_reg.get("tasks", []) or [])
        task_kinds = {str(row.get("task_kind", "")) for row in task_rows}

        assert delayed_reg.get("registered_count", 0) == 2
        assert task_kinds == {"anchor_item", "structure_projection"}
        assert any(str(row.get("target_item_id", "")) == str(seeded_item.get("id", "")) for row in task_rows)
        structure_task = next(row for row in task_rows if str(row.get("task_kind", "")) == "structure_projection")
        assert str(structure_task.get("target_structure_id", "") or structure_task.get("target_ref_object_id", ""))
    finally:
        hdb.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_time_sensor_delayed_structure_projection_executes_on_stripped_structure():
    temp_dir, hdb = _build_real_hdb_with_time_structure()
    pool = _build_real_pool()
    try:
        runtime_obj = hdb.make_runtime_structure_object(
            next(iter(hdb._structure_store.iter_structures()))["id"],
            er=0.6,
            ev=0.2,
            reason="test_runtime_seed",
        )
        assert runtime_obj is not None
        source_structure_id = str(runtime_obj.get("id", "") or "")
        pool.insert_runtime_node(
            runtime_object=runtime_obj,
            trace_id="ts_pool_seed_exec",
            tick_id="cycle_0010",
            allow_merge=True,
            source_module="test",
            reason="ts_pool_seed_exec",
        )
        seeded_item = pool._store.get_by_ref(source_structure_id)
        assert seeded_item is not None
        seeded_item_id = str(seeded_item.get("id", "") or "")
        seeded_ev_before = float(seeded_item.get("energy", {}).get("ev", 0.0) or 0.0)

        sensor = TimeSensor(
            config_override={
                "enabled": True,
                "time_basis": "tick",
                "enable_bucket_nodes": False,
                "enable_bind_attribute": True,
                "enable_delayed_tasks": True,
                "enable_projection_target_bindings": True,
                "enable_runtime_snapshot_target_bindings": True,
                "memory_top_k": 4,
                "energy_gain_ratio": 0.2,
                "base_energy_source": "last_delta_energy",
                "max_bind_targets_per_memory": 1,
                "max_projection_bind_targets_per_memory": 1,
                "max_total_bindings": 4,
                "delayed_task_register_min_delta_energy": 0.01,
                "delayed_task_min_interval_ticks": 1,
                "delayed_task_due_tolerance_ticks": 0,
                "delayed_task_energy_ratio": 1.0,
                "delayed_task_energy_min": 0.05,
                "delayed_task_energy_max": 1.0,
            }
        )
        snapshot = {
            "items": [
                {
                    "memory_id": "em_time_exec",
                    "memory_created_at": 1000,
                    "created_at": 1000,
                    "memory_tick_index": 10,
                    "last_delta_er": 0.0,
                    "last_delta_ev": 1.0,
                    "total_energy": 1.0,
                    "display_text": "A",
                    "backing_structure_ids": [source_structure_id],
                    "structure_refs": [source_structure_id],
                    "structure_ref_items": [{"id": source_structure_id}],
                }
            ]
        }
        first = sensor.run_time_feeling_tick(
            pool=pool,
            hdb=hdb,
            trace_id="ts_dual_exec_seed",
            tick_id="cycle_0010",
            now_ms=2000,
            memory_activation_snapshot=snapshot,
            memory_feedback_result=None,
            source_mode="runtime_memory_projection",
        )["data"]
        task_rows = list(first.get("delayed_tasks", {}).get("registered", {}).get("tasks", []) or [])
        structure_task = next(row for row in task_rows if str(row.get("task_kind", "")) == "structure_projection")
        stripped_structure_id = str(
            structure_task.get("target_structure_id", "") or structure_task.get("target_ref_object_id", "")
        )
        assert stripped_structure_id
        assert pool._store.get_by_ref(stripped_structure_id) is None

        second = sensor.run_time_feeling_tick(
            pool=pool,
            hdb=hdb,
            trace_id="ts_dual_exec_due",
            tick_id="cycle_0011",
            now_ms=2500,
            memory_activation_snapshot={"items": []},
            memory_feedback_result=None,
            source_mode="runtime_memory_projection",
        )["data"]

        delayed_exec = second.get("delayed_tasks", {})
        executed = list(delayed_exec.get("executed", []) or [])
        executed_kinds = {str(row.get("task_kind", "")) for row in executed if bool(row.get("ok", False))}
        assert delayed_exec.get("executed_count", 0) == 2
        assert executed_kinds == {"anchor_item", "structure_projection"}

        seeded_item_after = pool._store.get(seeded_item_id)
        assert seeded_item_after is not None
        assert float(seeded_item_after.get("energy", {}).get("ev", 0.0) or 0.0) > seeded_ev_before

        stripped_item = pool._store.get_by_ref(stripped_structure_id)
        assert stripped_item is not None
        assert float(stripped_item.get("energy", {}).get("ev", 0.0) or 0.0) > 0.0
    finally:
        hdb.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_time_sensor_runtime_memory_projection_accepts_structure_ref_items_without_ids():
    sensor = _build_sensor(enable_projection_targets=True)
    pool = _build_pool()

    result = sensor.run_time_feeling_tick(
        pool=pool,
        trace_id="ts_runtime_projection_ref_items_only",
        tick_id="cycle_0010",
        now_ms=2000,
        memory_activation_snapshot=_build_runtime_memory_activation_snapshot_with_ref_items_only(),
        memory_feedback_result=None,
        source_mode="runtime_memory_projection",
    )["data"]

    assert result["source_mode"] == "runtime_memory_projection"
    binding_targets = {str(row.get("target_item_id", "")) for row in result.get("attribute_bindings", [])}
    binding_sources = {str(row.get("target_score_source", "")) for row in result.get("attribute_bindings", [])}

    assert binding_targets == {"item_parent"}
    assert binding_sources == {"runtime_projection_peak"}


def test_time_sensor_stripped_structure_reuses_contextual_id_and_links_owner_chain():
    temp_dir, hdb = _build_real_hdb_with_time_structure()
    try:
        source_structure = next(iter(hdb._structure_store.iter_structures()))
        source_structure_id = str(source_structure.get("id", "") or "")
        sensor = TimeSensor(config_override={"enabled": True})
        source_profile = hdb._cut.build_sequence_profile_from_structure(source_structure)
        stripped_profile = sensor._strip_time_factor_from_profile(
            profile=source_profile,
            cut_engine=hdb._cut,
        )
        assert stripped_profile is not None

        first = sensor._lookup_or_materialize_structure_from_profile(
            hdb=hdb,
            target_profile=stripped_profile,
            source_structure_id=source_structure_id,
            trace_id="ts_lookup_materialize_first",
            tick_id="cycle_0001",
        )
        second = sensor._lookup_or_materialize_structure_from_profile(
            hdb=hdb,
            target_profile=stripped_profile,
            source_structure_id=source_structure_id,
            trace_id="ts_lookup_materialize_second",
            tick_id="cycle_0002",
        )

        assert first is not None
        assert second is not None
        assert str(first.get("structure_id", "") or "").startswith("st_")
        assert str(second.get("structure_id", "") or "") == str(first.get("structure_id", "") or "")
        assert int(hdb._pointer_index.export_snapshot().get("exact_lookup_cache_count", 0) or 0) >= 1
        created_structure = hdb._structure_store.get(str(first.get("structure_id", "") or ""))
        assert created_structure is not None
        structure_ext = created_structure.get("structure", {}).get("ext", {})
        assert structure_ext.get("identity_context_free") is True
        assert structure_ext.get("provenance_owner_structure_id") == source_structure_id
        assert created_structure.get("source", {}).get("parent_ids", []) == []
        assert created_structure.get("source", {}).get("context_ref_object_id", "") == ""
        assert created_structure.get("source", {}).get("context_owner_structure_id", "") == ""
        assert created_structure.get("source", {}).get("context_path_ids", []) == []

        owner_db = hdb._structure_store.get_db_by_owner(source_structure_id)
        assert owner_db is not None
        assert any(
            str(entry.get("target_id", "") or "") == str(first.get("structure_id", "") or "")
            and str(entry.get("ext", {}).get("relation_type", "") or "") == "time_factor_stripped_projection"
            for entry in owner_db.get("diff_table", [])
        )
    finally:
        hdb.close()
        shutil.rmtree(temp_dir, ignore_errors=True)
