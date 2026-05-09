# -*- coding: utf-8 -*-

import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from observatory._app import ObservatoryApp
from observatory._render_html import export_cycle_html
from observatory._render_terminal import render_cycle_report
from hdb._context_metadata import build_context_metadata, extract_context_metadata
from hdb._structure_resolver import resolve_or_create_structure_from_profile
from state_pool._id_generator import reset_id_generator


HI = "\u4f60\u597d"
YA = "\u5440"
QUESTION = "\uff1f"


def _seed_sa(*, sa_id: str, token: str, er: float, ev: float):
    return {
        "id": sa_id,
        "object_type": "sa",
        "content": {"raw": token, "display": token, "value_type": "discrete"},
        "stimulus": {"role": "feature", "modality": "text"},
        "energy": {"er": float(er), "ev": float(ev)},
        "source": {"parent_ids": []},
    }


def _seed_structure(*, er: float = 0.0, ev: float = 2.0, tokens: list[str] | None = None, member_ids: list[str] | None = None):
    unit_tokens = list(tokens or [HI, YA])
    member_refs = list(member_ids or [f"seed_sa_{index}" for index, _ in enumerate(unit_tokens)])
    return {
        "id": "st_seed_hi_ya",
        "object_type": "st",
        "sub_type": "stimulus_sequence_structure",
        "content": {"raw": "/".join(unit_tokens), "display": "/".join(unit_tokens), "normalized": "/".join(unit_tokens)},
        "energy": {"er": float(er), "ev": float(ev)},
        "structure": {
            "display_text": "/".join(unit_tokens),
            "flat_tokens": list(unit_tokens),
            "sequence_groups": [
                {
                    "group_index": 0,
                    "source_type": "current",
                    "origin_frame_id": "seed",
                    "tokens": list(unit_tokens),
                    "units": [
                        {
                            "unit_id": member_refs[index],
                            "token": token,
                            "unit_role": "feature",
                            "display_visible": True,
                        }
                        for index, token in enumerate(unit_tokens)
                    ],
                },
            ],
            "member_refs": member_refs,
        },
    }


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


def _runtime_projection(structure_obj: dict, *, er: float, ev: float) -> dict:
    runtime_obj = {
        **structure_obj,
        "energy": {
            "er": float(er),
            "ev": float(ev),
        },
    }
    return runtime_obj


def _profile_from_tokens(app: ObservatoryApp, prefix: str, tokens: list[str]) -> dict:
    group = {
        "group_index": 0,
        "source_type": "pytest",
        "origin_frame_id": f"{prefix}_group",
        "units": [
            {
                "unit_id": f"{prefix}_{index}",
                "token": token,
                "display_text": token,
                "unit_role": "feature",
                "sequence_index": index,
                "group_index": 0,
                "display_visible": True,
            }
            for index, token in enumerate(tokens)
        ],
    }
    return app.cut_engine.build_sequence_profile_from_groups([group])


def _resolve_test_structure(app: ObservatoryApp, prefix: str, tokens: list[str], *, base_weight: float = 0.1) -> dict:
    profile = _profile_from_tokens(app, prefix, tokens)
    result = resolve_or_create_structure_from_profile(
        profile=profile,
        structure_store=app.hdb._structure_store,
        pointer_index=app.hdb._pointer_index,
        cut_engine=app.cut_engine,
        trace_id=f"pytest_resolve::{prefix}",
        tick_id=f"pytest_resolve::{prefix}",
        confidence=0.95,
        origin="pytest_growth_projection_seed",
        origin_id=prefix,
        parent_ids=[],
        base_weight=base_weight,
        source_interface="pytest_growth_projection_seed",
        strict_context_owner_match=False,
        strict_context_ref_match=False,
    )
    assert isinstance(result.get("structure"), dict)
    return result["structure"]


@pytest.fixture
def app():
    reset_id_generator()
    temp_hdb_dir = tempfile.mkdtemp(prefix="observatory_hdb_")
    instance = ObservatoryApp(
        config_override={
            "export_html": False,
            "export_json": False,
            "auto_open_html_report": False,
            "web_auto_open_browser": False,
            "state_pool_enable_placeholder_interfaces": False,
            "state_pool_enable_script_broadcast": False,
            "hdb_enable_background_repair": False,
            "hdb_data_dir": temp_hdb_dir,
        }
    )
    yield instance
    instance.close()
    shutil.rmtree(temp_hdb_dir, ignore_errors=True)


def test_cycle_export_defaults_keep_outputs_bounded(tmp_path):
    reset_id_generator()
    temp_hdb_dir = tempfile.mkdtemp(prefix="observatory_export_hdb_")
    instance = ObservatoryApp(
        config_override={
            "export_html": True,
            "export_json": True,
            "auto_open_html_report": False,
            "web_auto_open_browser": False,
            "state_pool_enable_placeholder_interfaces": False,
            "state_pool_enable_script_broadcast": False,
            "hdb_enable_background_repair": False,
            "hdb_data_dir": temp_hdb_dir,
        }
    )
    instance.output_dir = tmp_path
    try:
        report = instance.run_cycle(text="你好，小澪")

        latest_json = tmp_path / "latest.json"
        latest_html = tmp_path / "latest.html"
        assert latest_json.exists()
        assert latest_html.exists()
        assert latest_json.stat().st_size < 2 * 1024 * 1024
        assert latest_html.stat().st_size < 4 * 1024 * 1024
        assert not list(tmp_path.glob("cycle_*.json"))
        assert not list(tmp_path.glob("cycle_*.html"))
        exported = report.get("exports", {})
        assert exported.get("cycle_json_history_enabled") is False
        assert exported.get("cycle_html_history_enabled") is False
    finally:
        instance.close()
        shutil.rmtree(temp_hdb_dir, ignore_errors=True)


def test_cycle_export_cleanup_removes_legacy_huge_cycle_files(tmp_path):
    temp_hdb_dir = tempfile.mkdtemp(prefix="observatory_cleanup_hdb_")
    instance = ObservatoryApp(
        config_override={
            "export_html": False,
            "export_json": False,
            "auto_open_html_report": False,
            "web_auto_open_browser": False,
            "hdb_enable_background_repair": False,
            "hdb_data_dir": temp_hdb_dir,
            "export_cycle_json_max_bytes": 1024,
            "export_cycle_html_max_bytes": 1024,
            "outputs_cycle_max_total_bytes": 2048,
        }
    )
    instance.output_dir = tmp_path
    try:
        huge_json = tmp_path / "cycle_0001.json"
        huge_html = tmp_path / "cycle_0001.html"
        huge_json.write_bytes(b"{" + (b"0" * 4096) + b"}")
        huge_html.write_bytes(b"<html>" + (b"0" * 4096) + b"</html>")

        instance._cleanup_output_reports()

        assert not huge_json.exists()
        assert not huge_html.exists()
    finally:
        instance.close()
        shutil.rmtree(temp_hdb_dir, ignore_errors=True)


def test_apply_packet_to_pool_observes_priority_neutralization(app):
    for sa_obj in (
        _seed_sa(sa_id="seed_sa_0", token=HI, er=0.0, ev=1.0),
        _seed_sa(sa_id="seed_sa_1", token=YA, er=0.0, ev=1.0),
    ):
        insert_sa = app.pool.insert_runtime_node(sa_obj, trace_id=f"{sa_obj['id']}_trace", source_module="pytest")
        assert insert_sa["success"] is True
    insert_result = app.pool.insert_runtime_node(_seed_structure(member_ids=["seed_sa_0", "seed_sa_1"]), trace_id="seed_trace", source_module="pytest")
    assert insert_result["success"] is True

    packet = app.sensor.ingest_text(text=f"{HI}{YA}{QUESTION}", trace_id="sensor_trace", tick_id="sensor_tick")["data"]["stimulus_packet"]
    packet_total_er = float(packet.get("energy_summary", {}).get("total_er", 0.0))

    app._run_state_pool_maintenance("cycle_trace", "cycle_tick")
    app._build_attention_memory_stub("cycle_trace", "cycle_tick")
    apply_result, events, residual_packet = app._apply_packet_to_pool(packet, "cycle_trace", "cycle_tick")

    assert apply_result["priority_neutralized_item_count"] == 1
    assert any(event.get("event_type") == "priority_stimulus_neutralization" for event in events)
    assert float(residual_packet.get("energy_summary", {}).get("total_er", 0.0)) < packet_total_er


def test_build_hdb_snapshot_lightweight_includes_contextual_summary(app):
    app.hdb._structure_store.create_structure(
        structure_payload={
            "sub_type": "stimulus_sequence_structure",
            "display_text": "好",
            "flat_tokens": ["好"],
            "sequence_groups": [{"group_index": 0, "source_type": "pytest", "origin_frame_id": "ctx_a", "tokens": ["好"]}],
            "content_signature": "pytest::hao",
            "semantic_signature": "pytest::hao",
            "ext": build_context_metadata(
                context_owner_structure_id="st_ctx_a",
                context_ref_object_id="st_ctx_a",
                context_path_ids=["st_ctx_a"],
            ),
        },
        trace_id="lightweight_ctx_a",
        tick_id="lightweight_ctx_a",
        source_interface="pytest_seed_structure",
        origin="unit_test_seed",
    )
    app.hdb._structure_store.create_structure(
        structure_payload={
            "sub_type": "stimulus_sequence_structure",
            "display_text": "好",
            "flat_tokens": ["好"],
            "sequence_groups": [{"group_index": 0, "source_type": "pytest", "origin_frame_id": "ctx_b", "tokens": ["好"]}],
            "content_signature": "pytest::hao",
            "semantic_signature": "pytest::hao",
            "ext": build_context_metadata(
                context_owner_structure_id="st_ctx_b",
                context_ref_object_id="st_ctx_b",
                context_path_ids=["st_ctx_a", "st_ctx_b"],
            ),
        },
        trace_id="lightweight_ctx_b",
        tick_id="lightweight_ctx_b",
        source_interface="pytest_seed_structure",
        origin="unit_test_seed",
    )

    summary = app._build_hdb_snapshot_lightweight(trace_id="lightweight_ctx_summary")["summary"]

    assert summary["lightweight_summary"] is True
    assert summary["contextual_structure_count"] == 2
    assert summary["same_content_multi_context_count"] == 1
    assert summary["structure_context_path_depth_mean"] >= 1.0


@pytest.mark.parametrize("relation_type", ["residual_context", "residual_context_common"])
def test_induction_growth_projection_composes_source_and_residual_identity(app, relation_type):
    source = _resolve_test_structure(app, "growth_source", ["你"])
    residual = _resolve_test_structure(app, "growth_residual", ["好"])
    source_id = str(source["id"])
    residual_id = str(residual["id"])
    residual_profile = app.cut_engine.build_sequence_profile_from_structure(residual)

    induction_data = {
        "induction_targets": [
            {
                "projection_kind": "structure",
                "target_structure_id": residual_id,
                "delta_ev": 0.75,
            }
        ],
        "debug": {
            "source_details": [
                {
                    "source_structure_id": source_id,
                    "source_er": 1.5,
                    "source_ev": 0.0,
                    "candidate_entries": [
                        {
                            "projection_kind": "structure",
                            "target_structure_id": residual_id,
                            "backing_structure_id": residual_id,
                            "target_display_text": "好",
                            "target_profile": residual_profile,
                            "relation_type": relation_type,
                            "growth_source_structure_id": source_id,
                            "direct_source_structure_id": source_id,
                            "delta_ev": 0.75,
                            "mode": "pytest_growth",
                        }
                    ],
                }
            ]
        },
    }

    projected, summary = app._prepare_induction_projection_targets(
        induction_data=induction_data,
        trace_id="pytest_growth_projection",
        tick_id="pytest_growth_projection_tick",
    )

    assert summary["mode"] == "growth"
    assert summary["growth_target_count"] == 1
    assert summary["growth_identity_created_count"] == 1
    assert summary["growth_runtime_only_count"] == 0
    assert len(projected) == 1
    row = projected[0]
    assert row["target_structure_id"] not in {source_id, residual_id}
    assert row["delta_ev"] == 0.75
    assert row["delta_er"] == 0.75
    component_energy = row["component_energy"]
    assert component_energy["source_component_er_share"] == 0.75
    assert component_energy["residual_component_ev_share"] == 0.75
    grown_profile = app.cut_engine.build_sequence_profile_from_structure(
        app.hdb._structure_store.get(row["target_structure_id"])
    )
    assert grown_profile["flat_tokens"] == ["你", "好"]

    projected_again, summary_again = app._prepare_induction_projection_targets(
        induction_data=induction_data,
        trace_id="pytest_growth_projection_again",
        tick_id="pytest_growth_projection_tick_again",
    )
    assert summary_again["growth_identity_shared_cache_hit_count"] == 1
    assert projected_again[0]["target_structure_id"] == row["target_structure_id"]

    projected_third, summary_third = app._prepare_induction_projection_targets(
        induction_data=induction_data,
        trace_id="pytest_growth_projection_shared_cache",
        tick_id="pytest_growth_projection_tick_shared_cache",
    )
    assert summary_third["growth_identity_shared_cache_hit_count"] == 1
    assert projected_third[0]["target_structure_id"] == row["target_structure_id"]


def test_induction_growth_projection_does_not_reuse_contextual_identity(app):
    source = _resolve_test_structure(app, "growth_ctx_source", ["我"])
    residual = _resolve_test_structure(app, "growth_ctx_residual", ["在"])
    source_id = str(source["id"])
    residual_id = str(residual["id"])
    contextual_profile = _profile_from_tokens(app, "growth_ctx_existing", ["我", "在"])
    contextual_profile["ext"] = build_context_metadata(
        context_owner_structure_id=source_id,
        context_ref_object_id=source_id,
        context_path_ids=[source_id],
    )
    contextual = resolve_or_create_structure_from_profile(
        profile=contextual_profile,
        structure_store=app.hdb._structure_store,
        pointer_index=app.hdb._pointer_index,
        cut_engine=app.cut_engine,
        trace_id="pytest_growth_contextual_existing",
        tick_id="pytest_growth_contextual_existing",
        confidence=0.95,
        origin="pytest_growth_contextual_existing",
        origin_id="contextual",
        parent_ids=[source_id],
        base_weight=0.1,
        source_interface="pytest_growth_contextual_existing",
        strict_context_owner_match=False,
        strict_context_ref_match=False,
    )["structure"]
    assert str(contextual["id"]) not in {source_id, residual_id}

    induction_data = {
        "induction_targets": [
            {
                "projection_kind": "structure",
                "target_structure_id": residual_id,
                "delta_ev": 0.6,
            }
        ],
        "debug": {
            "source_details": [
                {
                    "source_structure_id": source_id,
                    "source_er": 1.2,
                    "source_ev": 0.0,
                    "candidate_entries": [
                        {
                            "projection_kind": "structure",
                            "target_structure_id": residual_id,
                            "backing_structure_id": residual_id,
                            "target_display_text": "在",
                            "relation_type": "residual_context",
                            "growth_source_structure_id": source_id,
                            "direct_source_structure_id": source_id,
                            "delta_ev": 0.6,
                            "mode": "pytest_growth",
                        }
                    ],
                }
            ]
        },
    }

    projected, summary = app._prepare_induction_projection_targets(
        induction_data=induction_data,
        trace_id="pytest_growth_context_free",
        tick_id="pytest_growth_context_free",
    )

    assert summary["growth_identity_created_count"] == 1
    assert projected[0]["target_structure_id"] != contextual["id"]
    grown = app.hdb._structure_store.get(projected[0]["target_structure_id"])
    assert grown is not None
    grown_context = extract_context_metadata(grown)
    assert grown_context["context_owner_structure_id"] == ""
    assert grown_context["context_ref_object_id"] == ""
    assert grown_context["context_path_ids"] == []


def test_induction_growth_projection_shared_cache_can_be_disabled(app):
    source = _resolve_test_structure(app, "growth_shared_cache_off_source", ["关"])
    residual = _resolve_test_structure(app, "growth_shared_cache_off_residual", ["闭"])
    source_id = str(source["id"])
    residual_id = str(residual["id"])
    residual_profile = app.cut_engine.build_sequence_profile_from_structure(residual)
    induction_data = {
        "induction_targets": [],
        "debug": {
            "source_details": [
                {
                    "source_structure_id": source_id,
                    "source_er": 1.0,
                    "source_ev": 0.0,
                    "candidate_entries": [
                        {
                            "projection_kind": "structure",
                            "target_structure_id": residual_id,
                            "target_display_text": "闭",
                            "target_profile": residual_profile,
                            "relation_type": "residual_context",
                            "growth_source_structure_id": source_id,
                            "direct_source_structure_id": source_id,
                            "delta_ev": 0.5,
                            "mode": "pytest_growth",
                        }
                    ],
                }
            ]
        },
    }
    projected, summary = app._prepare_induction_projection_targets(
        induction_data=induction_data,
        trace_id="pytest_growth_shared_cache_off_seed",
        tick_id="pytest_growth_shared_cache_off_seed",
    )
    assert summary["growth_identity_created_count"] == 1
    app._config["growth_projection_identity_shared_cache_enabled"] = False

    projected_again, summary_again = app._prepare_induction_projection_targets(
        induction_data=induction_data,
        trace_id="pytest_growth_shared_cache_off",
        tick_id="pytest_growth_shared_cache_off",
    )

    assert summary_again["growth_identity_shared_cache_hit_count"] == 0
    assert summary_again["growth_identity_hit_count"] == 1
    assert projected_again[0]["target_structure_id"] == projected[0]["target_structure_id"]


def test_growth_projection_component_energy_is_carried_to_state_item(app):
    source = _resolve_test_structure(app, "growth_audit_source", ["想"])
    residual = _resolve_test_structure(app, "growth_audit_residual", ["你"])
    source_id = str(source["id"])
    residual_id = str(residual["id"])
    residual_profile = app.cut_engine.build_sequence_profile_from_structure(residual)
    induction_data = {
        "induction_targets": [],
        "debug": {
            "source_details": [
                {
                    "source_structure_id": source_id,
                    "source_er": 1.0,
                    "source_ev": 0.0,
                    "candidate_entries": [
                        {
                            "projection_kind": "structure",
                            "target_structure_id": residual_id,
                            "backing_structure_id": residual_id,
                            "target_display_text": "你",
                            "target_profile": residual_profile,
                            "relation_type": "residual_context",
                            "growth_source_structure_id": source_id,
                            "direct_source_structure_id": source_id,
                            "delta_ev": 0.4,
                            "mode": "pytest_growth",
                        }
                    ],
                }
            ]
        },
    }
    projected, _summary = app._prepare_induction_projection_targets(
        induction_data=induction_data,
        trace_id="pytest_growth_component_audit",
        tick_id="pytest_growth_component_audit",
    )

    applied = app._apply_induction_targets(
        projected,
        trace_id="pytest_growth_component_audit_apply",
        tick_id="pytest_growth_component_audit_apply",
    )

    assert applied
    target_item_id = applied[0]["target_item_id"]
    state_item = app.pool._store.get(target_item_id)
    assert state_item is not None
    structure_ext = state_item["ref_snapshot"]["structure_ext"]
    assert structure_ext["growth_projection"] is True
    meta_ext = state_item["meta"]["ext"]
    assert meta_ext["component_energy"]["source_component_er_share"] == 0.4
    assert meta_ext["component_energy"]["residual_component_ev_share"] == 0.4
    assert meta_ext["growth_projection"]["projection_mode"] == "growth"


def test_runtime_residual_promotion_rebinds_to_context_free_structure_identity(app):
    structure = _resolve_test_structure(app, "residual_promoted_structure", ["问"])
    state_item = {
        "id": "spi_runtime_residual_promoted",
        "object_type": "state_item",
        "sub_type": "runtime_residual_package",
        "ref_object_type": "st",
        "ref_object_id": "rt_residual_package_1",
        "ref_alias_ids": ["rt_residual_package_1"],
        "semantic_signature": "obj|问",
        "semantic_context_key": "semctx|obj|问|ref_type=<none>|ref=spkt_residual_demo|owner=<none>|text=<none>|role=<none>|attr=<none>",
        "ref_snapshot": {
            "content_display": "{问}",
            "sequence_groups": [
                {
                    "group_index": 0,
                    "tokens": ["问"],
                    "units": [{"unit_id": "sa_demo", "token": "问", "unit_role": "feature"}],
                }
            ],
            "context_ref_object_id": "spkt_residual_demo",
            "context_path_ids": ["spkt_residual_demo", "rt_residual_package_1"],
            "context_explicit": True,
            "residual_origin_kind": "stimulus_runtime_residual_package",
        },
        "energy": {"er": 0.3, "ev": 0.0},
        "source": {
            "module": "observatory",
            "origin": "stimulus_runtime_residual_package",
            "parent_ids": ["spkt_residual_demo", "rt_residual_package_1"],
            "context_ref_object_id": "spkt_residual_demo",
            "context_path_ids": ["spkt_residual_demo", "rt_residual_package_1"],
        },
        "meta": {
            "ext": {
                "runtime_only_residual": True,
                "context_ref_object_id": "spkt_residual_demo",
                "context_path_ids": ["spkt_residual_demo", "rt_residual_package_1"],
                "residual_origin_kind": "stimulus_runtime_residual_package",
            }
        },
    }

    app._rebind_runtime_residual_state_item_to_structure(
        state_item=state_item,
        structure_obj=structure,
        runtime_ref_id="rt_residual_package_1",
        trace_id="pytest_residual_promote",
        tick_id="pytest_residual_promote",
        reason="pytest",
    )

    context = extract_context_metadata(state_item)
    assert context["context_ref_object_id"] == ""
    assert context["context_owner_structure_id"] == ""
    assert context["context_path_ids"] == []
    assert "ref=spkt_residual_demo" not in state_item["semantic_context_key"]
    assert "|ref=<none>|owner=<none>|" in state_item["semantic_context_key"]
    meta_ext = state_item["meta"]["ext"]
    assert meta_ext["pre_promotion_context"]["context_ref_object_id"] == "spkt_residual_demo"
    assert meta_ext["provenance_parent_ids"] == ["spkt_residual_demo", "rt_residual_package_1"]
    assert meta_ext["hdb_backed"] is True
    assert state_item["source"]["parent_ids"] == []
    assert state_item["source"]["provenance_parent_ids"] == ["spkt_residual_demo", "rt_residual_package_1"]


def test_runtime_residual_promotion_exact_rebind_fast_path_reuses_existing_structure(app):
    structure = _resolve_test_structure(app, "residual_exact_rebind", ["快", "路"])
    signature = str(structure["structure"]["content_signature"])
    app._runtime_residual_exact_rebind_cache[signature] = structure["id"]
    state_item = {
        "id": "spi_runtime_residual_exact_rebind",
        "object_type": "state_item",
        "sub_type": "runtime_residual_package",
        "ref_object_type": "st",
        "ref_object_id": "rt_residual_exact_rebind",
        "ref_alias_ids": ["rt_residual_exact_rebind"],
        "ref_snapshot": {
            "content_display": "{快 + 路}",
            "sequence_groups": [
                {
                    "group_index": 0,
                    "source_type": "pytest",
                    "origin_frame_id": "residual_exact_rebind_group",
                    "tokens": ["快", "路"],
                    "units": [
                        {"unit_id": "residual_exact_rebind_0", "token": "快", "display_text": "快", "unit_role": "feature", "sequence_index": 0},
                        {"unit_id": "residual_exact_rebind_1", "token": "路", "display_text": "路", "unit_role": "feature", "sequence_index": 1},
                    ],
                }
            ],
        },
        "energy": {"er": 0.8, "ev": 0.2},
        "source": {"module": "observatory", "origin": "stimulus_runtime_residual_package"},
        "meta": {"ext": {"runtime_only_residual": True, "residual_origin_kind": "stimulus_runtime_residual_package"}},
    }
    assert app.pool._store.insert(state_item) is True

    result = app._promote_runtime_residual_state_item(
        state_item=state_item,
        trace_id="pytest_exact_rebind",
        tick_id="pytest_exact_rebind",
        now_ms=123456,
        reason="pytest_exact_rebind",
    )

    assert result["promoted"] is True
    assert result["structure_id"] == structure["id"]
    assert result["matched"] is True
    assert result["created"] is False
    assert result["fast_path"] == "exact_rebind"
    assert result["cache_hit"] is True
    assert result["hdb_fallback"] is False
    rebound = app.pool._store.get("spi_runtime_residual_exact_rebind")
    assert rebound["ref_object_id"] == structure["id"]
    assert rebound["ref_snapshot"]["structure_ext"]["hdb_backed"] is True
    assert app._is_runtime_only_residual_item(rebound) is False
    assert int(structure["stats"]["match_count_total"]) >= 1


def test_runtime_residual_promotion_full_identity_uses_complete_package_identity(app):
    partial = _resolve_test_structure(app, "residual_partial_question", ["问"])
    state_item = {
        "id": "spi_runtime_residual_full_identity",
        "object_type": "state_item",
        "sub_type": "runtime_residual_package",
        "ref_object_type": "st",
        "ref_object_id": "rt_residual_full_identity",
        "ref_alias_ids": ["rt_residual_full_identity"],
        "ref_snapshot": {
            "content_display": "{问 + 答}",
            "sequence_groups": [
                {
                    "group_index": 0,
                    "source_type": "pytest",
                    "origin_frame_id": "residual_full_identity_group",
                    "tokens": ["问", "答"],
                    "units": [
                        {"unit_id": "residual_full_identity_0", "token": "问", "display_text": "问", "unit_role": "feature", "sequence_index": 0},
                        {"unit_id": "residual_full_identity_1", "token": "答", "display_text": "答", "unit_role": "feature", "sequence_index": 1},
                    ],
                }
            ],
        },
        "energy": {"er": 0.8, "ev": 0.2},
        "source": {"module": "observatory", "origin": "stimulus_runtime_residual_package"},
        "meta": {"ext": {"runtime_only_residual": True, "residual_origin_kind": "stimulus_runtime_residual_package"}},
    }
    assert app.pool._store.insert(state_item) is True

    result = app._promote_runtime_residual_state_item(
        state_item=state_item,
        trace_id="pytest_full_identity",
        tick_id="pytest_full_identity",
        now_ms=123456,
        reason="pytest_full_identity",
    )

    assert result["promoted"] is True
    assert result["fast_path"] == "full_identity"
    assert result["hdb_fallback"] is False
    assert result["structure_id"] != partial["id"]
    rebound = app.pool._store.get("spi_runtime_residual_full_identity")
    assert rebound["ref_object_id"] == result["structure_id"]
    assert rebound["ref_snapshot"]["flat_tokens"] == ["问", "答"]
    assert rebound["ref_snapshot"]["structure_ext"]["runtime_residual_full_identity"] is True
    assert rebound["ref_snapshot"]["structure_ext"]["context_free_identity"] is True
    context = extract_context_metadata(rebound)
    assert context["context_ref_object_id"] == ""
    assert context["context_owner_structure_id"] == ""
    assert app._is_runtime_only_residual_item(rebound) is False


def test_runtime_residual_promotion_exact_rebind_can_be_disabled(app):
    _resolve_test_structure(app, "residual_exact_rebind_disabled", ["回", "退"])
    app._config["runtime_residual_package_exact_rebind_fast_path_enabled"] = False
    app._config["runtime_residual_package_full_identity_promotion_enabled"] = False
    state_item = {
        "id": "spi_runtime_residual_exact_rebind_disabled",
        "object_type": "state_item",
        "sub_type": "runtime_residual_package",
        "ref_object_type": "st",
        "ref_object_id": "rt_residual_exact_rebind_disabled",
        "ref_alias_ids": ["rt_residual_exact_rebind_disabled"],
        "ref_snapshot": {
            "content_display": "{回 + 退}",
            "sequence_groups": [
                {
                    "group_index": 0,
                    "source_type": "pytest",
                    "origin_frame_id": "residual_exact_rebind_disabled_group",
                    "tokens": ["回", "退"],
                    "units": [
                        {"unit_id": "residual_exact_rebind_disabled_0", "token": "回", "display_text": "回", "unit_role": "feature", "sequence_index": 0},
                        {"unit_id": "residual_exact_rebind_disabled_1", "token": "退", "display_text": "退", "unit_role": "feature", "sequence_index": 1},
                    ],
                }
            ],
        },
        "energy": {"er": 0.8, "ev": 0.2},
        "source": {"module": "observatory", "origin": "stimulus_runtime_residual_package"},
        "meta": {"ext": {"runtime_only_residual": True, "residual_origin_kind": "stimulus_runtime_residual_package"}},
    }
    assert app.pool._store.insert(state_item) is True

    result = app._promote_runtime_residual_state_item(
        state_item=state_item,
        trace_id="pytest_exact_rebind_disabled",
        tick_id="pytest_exact_rebind_disabled",
        now_ms=123456,
        reason="pytest_exact_rebind_disabled",
    )

    assert result["promoted"] is True
    assert result.get("fast_path", "") != "exact_rebind"
    assert result["hdb_fallback"] is True


def test_runtime_residual_promotion_exact_rebind_probe_on_miss_is_opt_in(app):
    _resolve_test_structure(app, "residual_exact_rebind_probe_disabled", ["跳", "过"])
    app._config["runtime_residual_package_full_identity_promotion_enabled"] = False
    state_item = {
        "id": "spi_runtime_residual_probe_disabled",
        "object_type": "state_item",
        "sub_type": "runtime_residual_package",
        "ref_object_type": "st",
        "ref_object_id": "rt_residual_probe_disabled",
        "ref_alias_ids": ["rt_residual_probe_disabled"],
        "ref_snapshot": {
            "content_display": "{跳 + 过}",
            "sequence_groups": [
                {
                    "group_index": 0,
                    "source_type": "pytest",
                    "origin_frame_id": "residual_probe_disabled_group",
                    "tokens": ["跳", "过"],
                    "units": [
                        {"unit_id": "residual_probe_disabled_0", "token": "跳", "display_text": "跳", "unit_role": "feature", "sequence_index": 0},
                        {"unit_id": "residual_probe_disabled_1", "token": "过", "display_text": "过", "unit_role": "feature", "sequence_index": 1},
                    ],
                }
            ],
        },
        "energy": {"er": 0.8, "ev": 0.2},
        "source": {"module": "observatory", "origin": "stimulus_runtime_residual_package"},
        "meta": {"ext": {"runtime_only_residual": True, "residual_origin_kind": "stimulus_runtime_residual_package"}},
    }
    assert app.pool._store.insert(state_item) is True

    result = app._promote_runtime_residual_state_item(
        state_item=state_item,
        trace_id="pytest_probe_disabled",
        tick_id="pytest_probe_disabled",
        now_ms=123456,
        reason="pytest_probe_disabled",
    )

    assert result["promoted"] is True
    assert result.get("fast_path", "") != "exact_rebind"
    assert result["hdb_fallback"] is True
    assert result["exact_rebind_probe_skipped"] is True
    assert result["exact_rebind_cache_learned"] is True


def test_run_cycle_report_surfaces_priority_neutralization(app, tmp_path):
    for sa_obj in (
        _seed_sa(sa_id="seed_sa_0", token=HI, er=0.0, ev=1.0),
        _seed_sa(sa_id="seed_sa_1", token=YA, er=0.0, ev=1.0),
    ):
        insert_sa = app.pool.insert_runtime_node(sa_obj, trace_id=f"{sa_obj['id']}_cycle_trace", source_module="pytest")
        assert insert_sa["success"] is True
    insert_result = app.pool.insert_runtime_node(_seed_structure(member_ids=["seed_sa_0", "seed_sa_1"]), trace_id="seed_cycle_trace", source_module="pytest")
    assert insert_result["success"] is True

    report = app.run_cycle(text=f"{HI}{YA}{QUESTION}")
    pool_apply = report["pool_apply"]

    assert pool_apply["priority_summary"]["priority_neutralized_item_count"] == 1
    assert len(pool_apply["priority_events"]) == 1
    assert pool_apply["input_packet"]["total_er"] > pool_apply["residual_packet"]["total_er"]

    terminal_report = render_cycle_report(report)
    assert "priority_stimulus_neutralization" in terminal_report
    assert "matched_sig=" in terminal_report

    html_path = export_cycle_html(report, tmp_path / "priority_report.html")
    with open(html_path, "r", encoding="utf-8") as fh:
        html_text = fh.read()

    assert "priority neutralization events" in html_text
    assert "priority neutralization packet delta" in html_text


def test_run_cycle_tolerates_stimulus_level_error_payload(app, monkeypatch):
    def _broken_stimulus_level(**kwargs):
        return {
            "success": False,
            "code": "INTERNAL_ERROR",
            "message": "刺激级故障（pytest）",
            "data": None,
            "error": {"message": "pytest simulated failure"},
        }

    monkeypatch.setattr(app.hdb, "run_stimulus_level_retrieval_storage", _broken_stimulus_level)

    report = app.run_cycle(text=HI)

    stimulus_result = report["stimulus_level"]["result"]
    assert isinstance(stimulus_result, dict)
    assert stimulus_result.get("matched_structure_ids") == []
    assert stimulus_result.get("new_structure_ids") == []
    assert stimulus_result.get("residual_stimulus_packet")
    assert stimulus_result.get("debug", {}).get("runtime_error", {}).get("message") == "pytest simulated failure"


def test_run_cycle_routes_teacher_reward_into_emotion_post_script_updates():
    temp_hdb_dir = tempfile.mkdtemp(prefix="observatory_iesm_emotion_post_")
    app = ObservatoryApp(
        config_override={
            "export_html": False,
            "export_json": False,
            "auto_open_html_report": False,
            "web_auto_open_browser": False,
            "hdb_enable_background_repair": False,
            "hdb_data_dir": temp_hdb_dir,
            "cfs_to_nt_source_mode": "iesm_rules",
            "rwd_pun_to_nt_source_mode": "iesm_rules",
        }
    )
    try:
        report = app.run_cycle(
            text=HI,
            labels={
                "teacher_rwd": 0.8,
                "teacher_anchor": "none",
            },
        )

        innate_script = report.get("innate_script", {}) or {}
        focus = innate_script.get("focus", {}) or {}
        post_tick = innate_script.get("emotion_post_tick_rules", {}) or {}
        emotion = report.get("emotion", {}) or {}
        deltas = emotion.get("deltas", {}) or {}
        emotion_updates = focus.get("emotion_updates", {}) or {}
        triggered_rule_ids = [
            str(row.get("rule_id", "") or "")
            for row in (post_tick.get("triggered_rules", []) or [])
            if isinstance(row, dict)
        ]

        assert "nt_update_from_reward_state" in triggered_rule_ids
        assert float((emotion.get("rwd_pun_snapshot", {}) or {}).get("rwd", 0.0)) == pytest.approx(0.8)
        assert float(emotion_updates.get("DA", 0.0)) >= (0.072 - 1e-6)
        assert float((deltas.get("from_rwd_pun", {}) or {}).get("DA", 0.0)) == 0.0
        assert float((deltas.get("from_script", {}) or {}).get("DA", 0.0)) >= (0.072 - 1e-6)
        assert int(post_tick.get("emotion_update_key_count", 0) or 0) >= 1
    finally:
        app.close()
        shutil.rmtree(temp_hdb_dir, ignore_errors=True)


def test_placeholder_modules_reflect_current_runtime_availability(app):
    modules = {str(row.get("module", "") or ""): row for row in app.get_placeholder_modules() if isinstance(row, dict)}

    assert modules["attention"]["status"] == "MVP 可用"
    assert modules["cognitive_feeling"]["status"] == "MVP 可用（IESM 主链）"
    assert modules["emotion"]["status"] == "MVP 可用（8 通道）"
    assert modules["innate_script"]["status"] == "MVP 可用（规则驱动）"
    assert modules["action"]["status"] == "MVP 可用"
    assert "认知感受" in str(modules["cognitive_feeling"].get("description", ""))
    assert "8 通道 NT" in str(modules["emotion"].get("description", ""))
    assert "emotion_post" in str(modules["innate_script"].get("description", ""))


def test_export_cycle_html_includes_action_learning_summary(tmp_path):
    report = {
        "trace_id": "trace_action_html",
        "tick_id": "cycle_action_html_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "maintenance": {},
        "attention": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "cognitive_feeling": {},
        "emotion": {},
        "innate_script": {},
        "final_state": {
            "state_snapshot": {"summary": {}, "top_items": []},
            "state_energy_summary": {"energy_by_type": {}},
            "hdb_snapshot": {"summary": {}, "recent_structures": []},
        },
        "action": {
            "action_learning_summary": {
                "humanlike_runtime_sync_enabled": True,
                "runtime_signal_node_count": 2,
                "runtime_signal_node_active_count": 2,
                "runtime_action_node_count": 3,
                "runtime_action_node_active_count": 2,
                "runtime_action_node_executed_count": 1,
                "runtime_action_target_ref_count": 1,
                "runtime_action_target_item_count": 1,
                "local_drive_modulation_enabled": True,
                "targeted_node_count": 2,
                "local_lookup_hit_count": 1,
                "local_lookup_text_fallback_hit_count": 1,
                "local_lookup_miss_count": 1,
                "local_lookup_skipped_count": 1,
                "local_target_missing_count": 1,
                "local_modulation_disabled_count": 1,
                "local_modulated_node_count": 1,
                "local_drive_scale_mean": 1.18,
                "local_reward_drive_bonus_total": 0.07,
                "local_punish_drive_penalty_total": 0.02,
                "examples": [
                    {
                        "action_kind": "weather_stub",
                        "action_id": "act_weather",
                        "target_display": "示例目标",
                        "reward": 0.8,
                        "punish": 0.0,
                        "scale_clamped": 1.18,
                        "reward_bonus_gain": 0.07,
                        "punish_penalty_gain": 0.0,
                    }
                ],
            },
            "nodes": [
                {
                    "action_kind": "weather_stub",
                    "action_id": "act_weather",
                    "target_display": "示例目标",
                    "drive": 0.47,
                    "tick_consumed_drive_total": 0.13,
                    "effective_threshold": 0.62,
                    "local_drive_modulation": {
                        "lookup_status": "hit",
                        "lookup_hit": True,
                        "reward": 0.8,
                        "punish": 0.0,
                        "scale_clamped": 1.18,
                    },
                }
            ],
            "executed_actions": [
                {
                    "action_kind": "weather_stub",
                    "action_id": "act_weather",
                    "target_display": "示例目标",
                    "success": True,
                    "attempted": True,
                    "consumed_drive": 0.13,
                    "local_drive_modulation": {
                        "lookup_status": "miss",
                        "lookup_hit": False,
                        "detail": {"reason": "local_feedback_not_found"},
                    },
                }
            ],
        },
    }

    html_path = export_cycle_html(report, tmp_path / "action_learning_report.html")
    html_text = Path(html_path).read_text(encoding="utf-8")
    terminal_report = render_cycle_report(report)

    assert "行动学习摘要 / Action Learning Summary" in html_text
    assert "人形主路径" in html_text
    assert "运行态显影" in html_text
    assert "局部塑形样例 / Local modulation examples" in html_text
    assert "当前行动节点 / Current action nodes" in html_text
    assert "最近执行行动 / Recent executed actions" in html_text
    assert "text_fallback 1" in html_text
    assert "tick_consumed" in html_text
    assert "consumed_drive" in html_text
    assert "示例目标" in html_text
    assert "[8.5/9] 行动模块 / Action Runtime" in terminal_report
    assert "人形主路径=是" in terminal_report
    assert "text_fallback=1" in terminal_report


def test_memory_feedback_structure_projection_caps_to_weighted_top_targets(app):
    memory_material = {
        "structure_items": [
            {"structure_id": "st_alpha", "display_text": "甲"},
            {"structure_id": "st_beta", "display_text": "乙"},
            {"structure_id": "st_gamma", "display_text": "丙"},
            {"structure_id": "st_delta", "display_text": "丁"},
        ],
        "structure_energy_profile": {
            "st_alpha": 0.42,
            "st_beta": 0.08,
            "st_gamma": 0.31,
            "st_delta": 0.19,
        },
    }
    app._config["memory_feedback_structure_projection_max_targets"] = 3

    projections = app._build_memory_feedback_structure_projections(
        memory_id="em_test_topk",
        memory_material=memory_material,
        total_er=0.0,
        total_ev=1.0,
    )

    assert [item["structure_id"] for item in projections] == ["st_alpha", "st_gamma", "st_delta"]
    assert "st_beta" not in {item["structure_id"] for item in projections}
    assert round(sum(float(item["ev"]) for item in projections), 8) == 1.0
    assert projections[0]["ev"] > projections[1]["ev"] > projections[2]["ev"]


def test_memory_feedback_structure_projection_concentrates_when_budget_is_too_thin(app):
    memory_material = {
        "structure_items": [
            {"structure_id": "st_alpha", "display_text": "alpha"},
            {"structure_id": "st_beta", "display_text": "beta"},
            {"structure_id": "st_gamma", "display_text": "gamma"},
            {"structure_id": "st_delta", "display_text": "delta"},
        ],
        "structure_energy_profile": {
            "st_alpha": 0.42,
            "st_beta": 0.08,
            "st_gamma": 0.31,
            "st_delta": 0.19,
        },
    }
    app._config["memory_feedback_structure_projection_max_targets"] = 6
    app._config["memory_feedback_structure_projection_budget_aware_enabled"] = True
    app._config["memory_feedback_structure_projection_min_effective_ev"] = 0.01
    app._config["memory_feedback_structure_projection_min_effective_er"] = 0.01

    projections = app._build_memory_feedback_structure_projections(
        memory_id="em_budget_aware",
        memory_material=memory_material,
        total_er=0.0,
        total_ev=0.018,
    )

    assert len(projections) == 1
    assert projections[0]["structure_id"] == "st_alpha"
    assert projections[0]["ev"] == pytest.approx(0.018, abs=1e-8)


def test_run_cycle_maintains_separate_memory_activation_pool(app):
    app._config["dedicated_memory_pool_enabled"] = True
    app._config["residual_memory_as_structure_enabled"] = False
    report = app.run_cycle(text=f"{HI}{YA}!")
    memory_activation = report["memory_activation"]

    assert memory_activation["apply_result"]["applied_count"] > 0
    assert memory_activation["snapshot"]["summary"]["count"] > 0
    assert not any(
        item.get("ref_object_type") == "em"
        for item in report["final_state"]["state_snapshot"].get("top_items", [])
    )


def test_run_cycle_default_memory_path_is_runtime_em_only(app):
    report = app.run_cycle(text=HI)
    memory_activation = report["memory_activation"]

    assert memory_activation["path_mode"] == "runtime_em_only"
    assert memory_activation["dedicated_memory_pool_enabled"] is False
    assert memory_activation["maintenance"]["enabled"] is False
    assert memory_activation["feedback_result"]["synthetic"] is True
    assert memory_activation["feedback_result"]["hidden_in_ui"] is True
    assert memory_activation["feedback_result"]["items"] == []
    assert report["memory_feedback"]["hidden_in_ui"] is True


def test_run_cycle_emotion_report_exposes_all_eight_nt_channels(app):
    report = app.run_cycle(text=HI)
    emotion = report["emotion"]

    expected = {"DA", "ADR", "OXY", "SER", "END", "COR", "NOV", "FOC"}
    assert expected.issubset(set((emotion.get("nt_state_after", {}) or {}).keys()))
    assert expected.issubset(set(((emotion.get("nt_state_snapshot", {}) or {}).get("channels", {}) or {}).keys()))
    assert expected.issubset(set((emotion.get("nt_channel_meta", {}) or {}).keys()))
    assert int((emotion.get("audit", {}) or {}).get("channel_count", 0) or 0) >= 8


def test_run_cycle_emotion_html_report_counts_all_eight_nt_channels(app, tmp_path):
    report = app.run_cycle(text=HI)

    html_path = export_cycle_html(report, tmp_path / "emotion_report.html")
    html_text = Path(html_path).read_text(encoding="utf-8")
    channel_count = re.search(
        r"通道数（channels）</div><div class='metric-value'>(\d+)</div><div class='metric-note'>NT（递质通道）数量</div>",
        html_text,
    )

    assert channel_count is not None
    assert int(channel_count.group(1)) >= 8


def test_run_cycle_runtime_em_only_hides_memory_feedback_stub_and_surfaces_cache_shortfall(app):
    for sa_obj in (
        _seed_sa(sa_id="seed_sa_0", token=HI, er=0.9, ev=0.0),
        _seed_sa(sa_id="seed_sa_1", token=YA, er=0.9, ev=0.0),
    ):
        insert_sa = app.pool.insert_runtime_node(sa_obj, trace_id=f"{sa_obj['id']}_positive_trace", source_module="pytest")
        assert insert_sa["success"] is True
    insert_result = app.pool.insert_runtime_node(
        _seed_structure(er=1.8, ev=0.0, tokens=[HI, YA], member_ids=["seed_sa_0", "seed_sa_1"]),
        trace_id="seed_positive_cp_trace",
        source_module="pytest",
    )
    assert insert_result["success"] is True

    report = app.run_cycle(text=f"{HI}{YA}{QUESTION}")
    cache = report["cache_neutralization"]

    assert report["memory_feedback"]["hidden_in_ui"] is True
    assert report["memory_feedback"]["items"] == []
    assert cache["priority_summary"]["priority_neutralized_item_count"] == 0
    assert cache["priority_diagnostics"]
    assert any(
        str(row.get("skipped_reason", "")) == "packet_no_opposite_energy"
        for row in cache["priority_diagnostics"]
    )


def test_memory_feedback_stimulus_packet_projects_er_and_ev_without_em_runtime_nodes(app):
    app._config["residual_memory_as_structure_enabled"] = False
    clear_result = app.pool.clear_state_pool(trace_id="stimulus_feedback_pool_clear", reason="unit_test_reset")
    assert clear_result["success"] is True

    grouped_text = f"{{{HI} + stimulus_intensity:1.1}} / {{{YA}}}"
    append_result = app.hdb.append_episodic_memory(
        episodic_payload={
            "event_summary": "stimulus_feedback_memory",
            "structure_refs": [],
            "group_refs": [],
            "meta": {
                "ext": {
                    "display_text": grouped_text,
                    "memory_material": {
                        "memory_kind": "stimulus_packet",
                        "grouped_display_text": grouped_text,
                        "sequence_groups": [
                            {
                                "group_index": 0,
                                "source_group_index": 0,
                                "origin_frame_id": "seed_frame_0",
                                "units": [
                                    {
                                        "unit_id": "unit_hi",
                                        "token": HI,
                                        "display_text": HI,
                                        "sequence_index": 0,
                                        "unit_role": "anchor",
                                        "role": "anchor",
                                        "value_type": "discrete",
                                    },
                                    {
                                        "unit_id": "unit_energy",
                                        "token": "stimulus_intensity:1.1",
                                        "display_text": "stimulus_intensity:1.1",
                                        "sequence_index": 1,
                                        "unit_role": "attribute",
                                        "role": "attribute",
                                        "attribute_name": "stimulus_intensity",
                                        "attribute_value": 1.1,
                                        "value_type": "numerical",
                                    },
                                ],
                                "csa_bundles": [
                                    {
                                        "bundle_id": "bundle_hi_energy",
                                        "anchor_unit_id": "unit_hi",
                                        "member_unit_ids": ["unit_hi", "unit_energy"],
                                    }
                                ],
                            },
                            {
                                "group_index": 1,
                                "source_group_index": 1,
                                "origin_frame_id": "seed_frame_1",
                                "units": [
                                    {
                                        "unit_id": "unit_ya",
                                        "token": YA,
                                        "display_text": YA,
                                        "sequence_index": 0,
                                        "unit_role": "anchor",
                                        "role": "anchor",
                                        "value_type": "discrete",
                                    }
                                ],
                                "csa_bundles": [],
                            },
                        ],
                        "unit_energy_profile": {
                            "unit_hi": 0.5,
                            "unit_energy": 0.3,
                            "unit_ya": 0.2,
                        },
                        "group_energy_profile": {"0": 0.8, "1": 0.2},
                    },
                }
            },
        },
        trace_id="append_stimulus_feedback_memory",
    )
    assert append_result["success"] is True
    memory_id = append_result["data"]["episodic_id"]

    apply_result = app.hdb.apply_memory_activation_targets(
        targets=[
            {
                "projection_kind": "memory",
                "memory_id": memory_id,
                "target_display_text": grouped_text,
                "delta_er": 0.6,
                "delta_ev": 0.4,
                "sources": ["st_seed_feedback"],
                "modes": ["manual_recall"],
            }
        ],
        trace_id="apply_stimulus_feedback_memory",
    )
    assert apply_result["success"] is True

    memory_item = app.hdb.query_memory_activation(
        memory_id=memory_id,
        trace_id="query_stimulus_feedback_memory",
    )["data"]["item"]
    feedback_result = app._apply_memory_feedback(
        memory_items=[memory_item],
        trace_id="stimulus_feedback",
        tick_id="stimulus_feedback",
    )

    assert feedback_result["applied_count"] == 1
    assert feedback_result["total_feedback_er"] == pytest.approx(0.6, abs=1e-6)
    assert feedback_result["total_feedback_ev"] == pytest.approx(0.4, abs=1e-6)
    assert feedback_result["packet_applied_total_er"] == pytest.approx(0.6, abs=1e-6)
    assert feedback_result["packet_applied_total_ev"] == pytest.approx(0.4, abs=1e-6)
    assert feedback_result["packet_apply_efficiency_er"] == pytest.approx(1.0, abs=1e-6)
    assert feedback_result["packet_apply_efficiency_ev"] == pytest.approx(1.0, abs=1e-6)
    assert feedback_result["items"][0]["packet"]["total_er"] == pytest.approx(0.6, abs=1e-6)
    assert feedback_result["items"][0]["packet"]["total_ev"] == pytest.approx(0.4, abs=1e-6)

    state_data = app.get_state_snapshot_data(top_k=32)
    assert state_data["energy_summary"]["total_er"] == pytest.approx(0.6, abs=1e-6)
    assert state_data["energy_summary"]["total_ev"] == pytest.approx(0.4, abs=1e-6)
    assert not any(
        item.get("ref_object_type") == "em"
        for item in state_data["snapshot"].get("top_items", [])
    )
    assert all(
        item.get("ref_object_type") == "sa"
        for item in state_data["snapshot"].get("top_items", [])
    )


def test_memory_feedback_structure_split_adapts_when_pool_ev_is_thin(app):
    clear_result = app.pool.clear_state_pool(trace_id="adaptive_feedback_pool_clear", reason="unit_test_reset")
    assert clear_result["success"] is True

    app._config["memory_feedback_stimulus_packet_structure_projection_enabled"] = True
    app._config["memory_feedback_stimulus_packet_structure_projection_ratio"] = 0.55
    app._config["memory_feedback_stimulus_packet_structure_projection_adaptive_enabled"] = True
    app._config["memory_feedback_stimulus_packet_structure_projection_adaptive_min_ratio"] = 0.20
    app._config["memory_feedback_stimulus_packet_structure_projection_adaptive_ev_er_floor"] = 0.55
    app._config["memory_feedback_stimulus_packet_structure_projection_adaptive_ev_er_ceiling"] = 0.95

    app.run_cycle(text=HI)
    structure_obj = _seed_hdb_structure(app, display_text=HI, flat_tokens=[HI])
    insert_result = app.pool.insert_runtime_node(
        _runtime_projection(structure_obj, er=12.0, ev=0.3),
        trace_id="adaptive_feedback_er_heavy_seed",
        source_module="pytest",
    )
    assert insert_result["success"] is True

    append_result = app.hdb.append_episodic_memory(
        episodic_payload={
            "event_summary": "adaptive_feedback_memory",
            "structure_refs": [structure_obj["id"]],
            "group_refs": [],
            "meta": {
                "ext": {
                    "display_text": HI,
                    "memory_material": {
                        "memory_kind": "stimulus_packet",
                        "grouped_display_text": HI,
                        "structure_refs": [structure_obj["id"]],
                        "structure_items": [
                            {
                                "structure_id": structure_obj["id"],
                                "display_text": HI,
                                "grouped_display_text": HI,
                            }
                        ],
                        "structure_energy_profile": {structure_obj["id"]: 1.0},
                        "sequence_groups": [
                            {
                                "group_index": 0,
                                "source_group_index": 0,
                                "origin_frame_id": "adaptive_frame_0",
                                "units": [
                                    {
                                        "unit_id": "unit_hi",
                                        "token": HI,
                                        "display_text": HI,
                                        "sequence_index": 0,
                                        "unit_role": "anchor",
                                        "role": "anchor",
                                        "value_type": "discrete",
                                    }
                                ],
                                "csa_bundles": [],
                            }
                        ],
                        "unit_energy_profile": {"unit_hi": 1.0},
                        "group_energy_profile": {"0": 1.0},
                    },
                }
            },
        },
        trace_id="append_adaptive_feedback_memory",
    )
    assert append_result["success"] is True
    memory_id = append_result["data"]["episodic_id"]

    apply_result = app.hdb.apply_memory_activation_targets(
        targets=[
            {
                "projection_kind": "memory",
                "memory_id": memory_id,
                "target_display_text": HI,
                "delta_er": 0.0,
                "delta_ev": 1.0,
                "sources": [structure_obj["id"]],
                "modes": ["manual_recall"],
            }
        ],
        trace_id="apply_adaptive_feedback_memory",
    )
    assert apply_result["success"] is True

    memory_item = app.hdb.query_memory_activation(
        memory_id=memory_id,
        trace_id="query_adaptive_feedback_memory",
    )["data"]["item"]
    feedback_result = app._apply_memory_feedback(
        memory_items=[memory_item],
        trace_id="adaptive_feedback",
        tick_id="adaptive_feedback",
    )

    assert feedback_result["applied_count"] == 1
    assert feedback_result["pool_energy_before_feedback"]["ev_to_er_ratio"] < 0.55
    assert feedback_result["structure_projection_ratio_base"] == pytest.approx(0.55, abs=1e-6)
    assert feedback_result["structure_projection_ratio_used"] == pytest.approx(0.20, abs=1e-6)
    assert feedback_result["packet_feedback_total_ev"] > feedback_result["structure_projection_total_ev"]
    assert feedback_result["packet_applied_total_ev"] >= 0.0
    assert feedback_result["packet_apply_efficiency_ev"] >= 0.0
    assert feedback_result["items"][0]["structure_projection_ratio_used"] == pytest.approx(0.20, abs=1e-6)
    assert "state_delta_summary" in feedback_result["items"][0]["packet_apply_result"]


def test_memory_feedback_structure_group_projects_er_and_ev_without_em_runtime_nodes(app):
    app._config["residual_memory_as_structure_enabled"] = False
    app.run_cycle(text=f"{HI}{YA}!")
    hdb_snapshot = app.hdb.get_hdb_snapshot(trace_id="seed_structure_hdb")["data"]
    structure_id = hdb_snapshot["recent_structures"][0]["structure_id"]
    assert structure_id

    clear_result = app.pool.clear_state_pool(trace_id="structure_feedback_pool_clear", reason="unit_test_reset")
    assert clear_result["success"] is True

    append_result = app.hdb.append_episodic_memory(
        episodic_payload={
            "event_summary": "structure_feedback_memory",
            "structure_refs": [structure_id],
            "group_refs": [],
            "meta": {
                "ext": {
                    "display_text": HI,
                    "memory_material": {
                        "memory_kind": "structure_group",
                        "grouped_display_text": HI,
                        "structure_refs": [structure_id],
                        "structure_items": [
                            {
                                "structure_id": structure_id,
                                "display_text": HI,
                                "grouped_display_text": HI,
                            }
                        ],
                        "structure_energy_profile": {structure_id: 1.0},
                    },
                }
            },
        },
        trace_id="append_structure_feedback_memory",
    )
    assert append_result["success"] is True
    memory_id = append_result["data"]["episodic_id"]

    apply_result = app.hdb.apply_memory_activation_targets(
        targets=[
            {
                "projection_kind": "memory",
                "memory_id": memory_id,
                "target_display_text": HI,
                "delta_er": 0.75,
                "delta_ev": 0.25,
                "sources": [structure_id],
                "modes": ["manual_recall"],
            }
        ],
        trace_id="apply_structure_feedback_memory",
    )
    assert apply_result["success"] is True

    memory_item = app.hdb.query_memory_activation(
        memory_id=memory_id,
        trace_id="query_structure_feedback_memory",
    )["data"]["item"]
    feedback_result = app._apply_memory_feedback(
        memory_items=[memory_item],
        trace_id="structure_feedback",
        tick_id="structure_feedback",
    )

    assert feedback_result["applied_count"] == 1
    assert feedback_result["total_feedback_er"] == pytest.approx(0.75, abs=1e-6)
    assert feedback_result["total_feedback_ev"] == pytest.approx(0.25, abs=1e-6)

    state_data = app.get_state_snapshot_data(top_k=32)
    assert state_data["energy_summary"]["total_er"] == pytest.approx(0.75, abs=1e-6)
    assert state_data["energy_summary"]["total_ev"] == pytest.approx(0.25, abs=1e-6)
    assert not any(
        item.get("ref_object_type") == "em"
        for item in state_data["snapshot"].get("top_items", [])
    )
    assert any(
        item.get("ref_object_type") == "st"
        for item in state_data["snapshot"].get("top_items", [])
    )


def test_build_induction_source_snapshot_mixes_ev_and_er_channels(app):
    structure_er = _seed_hdb_structure(app, "ER", ["E", "R"])
    structure_ev = _seed_hdb_structure(app, "EV", ["E", "V"])
    structure_mid = _seed_hdb_structure(app, "MID", ["M", "I", "D"])

    assert app.pool.insert_runtime_node(
        _runtime_projection(structure_er, er=5.0, ev=0.1),
        trace_id="seed_runtime_er",
        source_module="pytest",
    )["success"] is True
    assert app.pool.insert_runtime_node(
        _runtime_projection(structure_ev, er=0.8, ev=4.2),
        trace_id="seed_runtime_ev",
        source_module="pytest",
    )["success"] is True
    assert app.pool.insert_runtime_node(
        _runtime_projection(structure_mid, er=2.8, ev=0.6),
        trace_id="seed_runtime_mid",
        source_module="pytest",
    )["success"] is True

    app._config["induction_source_selection_mode"] = "hybrid_er_ev"
    app._config["induction_source_max_items"] = 2
    app._config["induction_source_candidate_top_k"] = 6
    app._config["induction_source_ev_quota_ratio"] = 0.5

    snapshot = app._build_induction_source_snapshot(
        trace_id="pytest_induction_source",
        tick_id="pytest_induction_source",
    )
    top_items = list(snapshot.get("top_items", []))
    summary = dict(snapshot.get("summary", {}) or {})

    assert len(top_items) == 2
    ref_ids = {str(item.get("ref_object_id", "") or "") for item in top_items}
    by_id = {str(item.get("ref_object_id", "") or ""): item for item in top_items}

    assert structure_ev["id"] in ref_ids
    assert structure_er["id"] in ref_ids
    assert by_id[structure_ev["id"]]["induction_source_channel"] == "ev"
    assert by_id[structure_er["id"]]["induction_source_channel"] == "er"
    assert summary["induction_source_selected_from_ev_count"] == 1
    assert summary["induction_source_selected_from_er_count"] == 1
    assert summary["induction_source_selection_cap_hit"] == 1


def test_build_induction_source_snapshot_default_all_energetic_runtime_includes_non_st_sources(app):
    structure_root = _seed_hdb_structure(app, "ROOT", ["R"])

    assert app.pool.insert_runtime_node(
        _seed_sa(sa_id="runtime_sa_r", token="R", er=1.4, ev=0.0),
        trace_id="seed_runtime_sa_r",
        source_module="pytest",
    )["success"] is True
    assert app.pool.insert_runtime_node(
        _runtime_projection(structure_root, er=0.8, ev=0.2),
        trace_id="seed_runtime_st_root",
        source_module="pytest",
    )["success"] is True

    snapshot = app._build_induction_source_snapshot(
        trace_id="pytest_induction_source_all_runtime",
        tick_id="pytest_induction_source_all_runtime",
    )
    top_items = list(snapshot.get("top_items", []))
    summary = dict(snapshot.get("summary", {}) or {})

    assert summary["induction_source_selection_mode"] == "all_energetic_runtime"
    assert summary["induction_source_available_runtime_count"] == 2
    assert summary["induction_source_selected_count"] == 2
    assert summary["induction_source_selected_non_st_count"] == 1
    assert {str(item.get("ref_object_type", "") or "") for item in top_items} == {"sa", "st"}


def test_build_induction_source_snapshot_skips_runtime_only_residual_package(app):
    app._config["runtime_residual_package_enabled"] = True
    app._config["runtime_residual_package_immediate_high_energy_promotion_enabled"] = False
    packet = app.sensor.ingest_text(
        text="runtime-only residual package",
        trace_id="runtime_only_residual_sensor",
        tick_id="runtime_only_residual_sensor",
    )["data"]["stimulus_packet"]
    package_result = app._insert_runtime_residual_package_to_pool(
        packet,
        trace_id="runtime_only_residual",
        tick_id="runtime_only_residual",
        source_packet_id=str(packet.get("id", "") or ""),
    )
    assert package_result["applied"] is True
    assert app.pool.insert_runtime_node(
        _seed_sa(sa_id="runtime_sa_visible_source", token="source", er=1.4, ev=0.0),
        trace_id="seed_runtime_sa_visible_source",
        source_module="pytest",
    )["success"] is True

    snapshot = app._build_induction_source_snapshot(
        trace_id="pytest_induction_source_runtime_only_residual",
        tick_id="pytest_induction_source_runtime_only_residual",
    )
    top_items = list(snapshot.get("top_items", []))
    summary = dict(snapshot.get("summary", {}) or {})

    assert summary["induction_source_runtime_only_residual_prefilter_skipped_count"] == 1
    assert summary["induction_source_selected_count"] == 1
    assert top_items[0]["ref_object_id"] == "runtime_sa_visible_source"


def test_run_cycle_projects_residual_tail_as_episodic_memory_id(app):
    app._config["residual_tail_memory_projection_enabled"] = True
    app._config["runtime_residual_package_enabled"] = False

    report = app.run_cycle(text="tail memory projection")
    tail_projection = report["pool_apply"]["residual_tail_memory_projection"]
    package_projection = report["pool_apply"]["runtime_residual_package"]

    assert tail_projection["applied"] is True
    assert tail_projection["handled"] is True
    memory_id = tail_projection["memory_id"]
    assert memory_id.startswith("em_")
    assert package_projection["applied"] is False

    state_item = app.pool._store.get_by_ref(memory_id)
    assert state_item is not None
    assert state_item["ref_object_type"] == "em"
    assert state_item["ref_object_id"] == memory_id
    assert state_item["ref_snapshot"].get("source_em_id") == memory_id
    assert app._is_runtime_only_residual_item(state_item) is False
    assert sum(
        1
        for item in app.pool._store.get_all()
        if item.get("ref_object_type") == "em" and item.get("ref_object_id") == memory_id
    ) == 1

    snapshot = app._build_induction_source_snapshot(
        trace_id="pytest_tail_memory_not_induction_source",
        tick_id="pytest_tail_memory_not_induction_source",
    )
    assert all(str(item.get("ref_object_id", "") or "") != memory_id for item in snapshot.get("top_items", []))


def test_low_energy_residual_tail_is_consumed_by_memory_id_without_fragment_pool_apply(app):
    app._config["residual_tail_memory_projection_enabled"] = True
    app._config["runtime_residual_package_enabled"] = True
    app._config["residual_tail_memory_projection_min_energy"] = 999.0

    report = app.run_cycle(text="weak tail should fade")
    tail_projection = report["pool_apply"]["residual_tail_memory_projection"]
    package_projection = report["pool_apply"]["runtime_residual_package"]
    landed_packet = report["pool_apply"]["landed_packet"]

    assert tail_projection["handled"] is True
    assert tail_projection["applied"] is False
    assert tail_projection["reason"] == "empty_or_below_threshold"
    assert str(tail_projection["memory_id"]).startswith("em_")
    assert package_projection["applied"] is False
    assert landed_packet["sa_count"] == 0
    assert not any(str(item.get("ref_object_id", "") or "").startswith("rt_residual_") for item in app.pool._store.get_all())


def test_residual_tail_memory_projection_merges_same_memory_id_by_ref(app):
    app._config["residual_tail_memory_projection_enabled"] = True
    packet = app.sensor.ingest_text(
        text="same memory tail",
        trace_id="same_memory_tail_sensor",
        tick_id="same_memory_tail_sensor",
    )["data"]["stimulus_packet"]
    stimulus_data = {
        "episodic_memory_id": "em_same_tail_projection",
        "episodic_display_text": "same memory tail full",
        "episodic_memory_material": {
            "memory_kind": "stimulus_packet",
            "sequence_groups": list(packet.get("grouped_sa_sequences", []) or []),
        },
    }

    first = app._insert_residual_tail_memory_projection_to_pool(
        packet,
        trace_id="pytest_same_memory_tail_first",
        tick_id="pytest_same_memory_tail_first",
        source_packet_id=str(packet.get("id", "") or ""),
        stimulus_data=stimulus_data,
    )
    second = app._insert_residual_tail_memory_projection_to_pool(
        packet,
        trace_id="pytest_same_memory_tail_second",
        tick_id="pytest_same_memory_tail_second",
        source_packet_id=str(packet.get("id", "") or ""),
        stimulus_data=stimulus_data,
    )

    assert first["applied"] is True
    assert second["applied"] is True
    assert second["result"]["merged"] is True
    assert second["result"]["merge_mode"] == "ref_fast"
    state_item = app.pool._store.get_by_ref("em_same_tail_projection")
    assert state_item is not None
    component = state_item["meta"]["ext"]["component_energy"]
    assert component["tail_component_er_share"] >= first["memory"]["energy"]["er"] + second["memory"]["energy"]["er"]


def test_attention_promotes_runtime_residual_package_to_hdb_backed_structure(app):
    app._config["runtime_residual_package_enabled"] = True
    app._config["residual_tail_memory_projection_enabled"] = False
    app._config["runtime_residual_package_attention_promotion_enabled"] = True
    app._config["runtime_residual_package_high_energy_promotion_enabled"] = True
    app._config["runtime_residual_package_immediate_high_energy_promotion_enabled"] = False
    app._config["runtime_residual_package_high_energy_promotion_min_total_energy"] = 0.01

    first_report = app.run_cycle(text="runtime residual promote")
    package_result = first_report["pool_apply"]["runtime_residual_package"]

    assert package_result["applied"] is True
    assert package_result["package"]["id"].startswith("rt_residual_")

    second_report = app.run_cycle(text="")
    promotion = second_report["runtime_residual_promotion"]

    assert promotion["attempted_count"] >= 1
    assert promotion["promoted_count"] >= 1
    promoted = next(item for item in promotion["items"] if item.get("promoted"))
    assert promoted["runtime_ref_id"].startswith("rt_residual_")
    assert promoted["structure_id"].startswith("st_")

    state_item = app.pool._store.get(promoted["item_id"])
    assert state_item is not None
    assert state_item["ref_object_id"] == promoted["structure_id"]
    assert state_item["ref_object_type"] == "st"
    assert state_item["ref_snapshot"]["structure_ext"]["runtime_only_residual"] is False
    assert state_item["ref_snapshot"]["structure_ext"]["hdb_backed"] is True
    assert app._is_runtime_only_residual_item(state_item) is False


def test_build_induction_source_snapshot_er_root_priority_ignores_zero_er_only_ev_roots(app):
    structure_er = _seed_hdb_structure(app, "ER_ONLY", ["E", "R"])
    structure_ev = _seed_hdb_structure(app, "EV_ONLY", ["E", "V"])

    assert app.pool.insert_runtime_node(
        _runtime_projection(structure_er, er=5.0, ev=0.1),
        trace_id="seed_runtime_er_only",
        source_module="pytest",
    )["success"] is True
    assert app.pool.insert_runtime_node(
        _runtime_projection(structure_ev, er=0.0, ev=4.2),
        trace_id="seed_runtime_ev_only",
        source_module="pytest",
    )["success"] is True

    app._config["induction_source_selection_mode"] = "er_root_priority"
    app._config["induction_source_max_items"] = 2
    app._config["induction_source_candidate_top_k"] = 6

    snapshot = app._build_induction_source_snapshot(
        trace_id="pytest_induction_source_er_root_priority",
        tick_id="pytest_induction_source_er_root_priority",
    )
    top_items = list(snapshot.get("top_items", []))
    summary = dict(snapshot.get("summary", {}) or {})

    assert len(top_items) == 1
    assert top_items[0]["ref_object_id"] == structure_er["id"]
    assert top_items[0]["induction_source_channel"] == "er"
    assert summary["induction_source_selection_mode"] == "er_root_priority"
    assert summary["induction_source_selected_count"] == 1
    assert summary["induction_source_selected_from_er_count"] == 1
    assert summary["induction_source_selected_from_ev_count"] == 0
    assert summary["induction_source_available_st_count"] == 1
    assert summary["induction_source_selection_cap_hit"] == 0


def test_build_induction_source_snapshot_prefers_sources_with_local_targets_when_enabled(app):
    structure_target = _seed_hdb_structure(app, "TARGET", ["T"])
    structure_zero = _seed_hdb_structure(app, "ZERO", ["Z"])
    structure_busy = _seed_hdb_structure(app, "BUSY", ["B"])

    app.hdb._structure_store.add_diff_entry(
        structure_busy["id"],
        target_id=structure_target["id"],
        content_signature=structure_target["structure"]["content_signature"],
        base_weight=0.8,
        residual_existing_signature="",
        residual_incoming_signature="tail",
        ext={"relation_type": "incoming_extension"},
    )

    assert app.pool.insert_runtime_node(
        _runtime_projection(structure_zero, er=0.1, ev=4.0),
        trace_id="seed_runtime_zero_target",
        source_module="pytest",
    )["success"] is True
    assert app.pool.insert_runtime_node(
        _runtime_projection(structure_busy, er=0.1, ev=2.0),
        trace_id="seed_runtime_busy_target",
        source_module="pytest",
    )["success"] is True

    app._config["induction_source_selection_mode"] = "hybrid_er_ev"
    app._config["induction_source_max_items"] = 1
    app._config["induction_source_candidate_top_k"] = 4
    app._config["induction_source_ev_quota_ratio"] = 1.0
    app._config["induction_source_local_target_bias_mode"] = "prefer_nonzero"

    snapshot = app._build_induction_source_snapshot(
        trace_id="pytest_induction_source_local_bias",
        tick_id="pytest_induction_source_local_bias",
    )

    top_items = list(snapshot.get("top_items", []))
    summary = dict(snapshot.get("summary", {}) or {})

    assert len(top_items) == 1
    assert top_items[0]["ref_object_id"] == structure_busy["id"]
    assert top_items[0]["induction_source_local_target_hint_count"] >= 1
    assert summary["induction_source_selected_with_local_target_hint_count"] == 1
    assert summary["induction_source_selected_zero_local_target_hint_count"] == 0


def test_apply_induction_targets_lands_sa_packet_for_structure_targets(app):
    app._config["induction_projection_runtime_st_enabled"] = False
    seeded = _seed_structure(tokens=["T", "A"], member_ids=["seed_t", "seed_a"])
    structure_target, _ = app.hdb._structure_store.create_structure(
        structure_payload={
            "sub_type": "stimulus_sequence_structure",
            "display_text": seeded["structure"]["display_text"],
            "flat_tokens": seeded["structure"]["flat_tokens"],
            "sequence_groups": seeded["structure"]["sequence_groups"],
            "member_refs": seeded["structure"]["member_refs"],
        },
        trace_id="pytest_induction_apply_seed",
        tick_id="pytest_induction_apply_seed",
    )

    projections = app._apply_induction_targets(
        [
            {
                "projection_kind": "structure",
                "target_structure_id": structure_target["id"],
                "backing_structure_id": structure_target["id"],
                "target_display_text": structure_target["structure"]["display_text"],
                "delta_er": 0.0,
                "delta_ev": 1.6,
            }
        ],
        trace_id="pytest_induction_apply",
        tick_id="pytest_induction_apply",
    )

    assert len(projections) == 1
    applied = projections[0]
    assert applied["projection_kind"] == "structure"
    assert applied["result"] == "induction_packet_applied"
    assert int(applied["target_sa_count"]) >= 2
    assert float(applied["landed_total_ev"]) > 0.0
    snapshot = app.pool.get_state_snapshot(
        trace_id="pytest_induction_apply_snapshot",
        tick_id="pytest_induction_apply_snapshot",
        top_k=8,
    )["data"]["snapshot"]
    assert int((snapshot.get("summary", {}) or {}).get("active_item_count", 0) or 0) >= 2


def test_induction_filters_nonprojectable_cs_event_targets_upstream(app):
    structure_left = _seed_hdb_structure(app, "LEFT", ["L"])
    structure_right = _seed_hdb_structure(app, "RIGHT", ["R"])
    structure_source = _seed_hdb_structure(app, "SOURCE", ["S"])

    cs_event_res = app.hdb.upsert_cognitive_stitching_event_structure(
        event_ref_id="cs_event::pytest::left_right",
        member_refs=[structure_left["id"], structure_right["id"]],
        display_text="LEFT+RIGHT",
        diff_rows=None,
        trace_id="pytest_cs_event_seed",
        tick_id="pytest_cs_event_seed",
    )
    assert cs_event_res["success"] is True
    cs_event_structure_id = str((cs_event_res.get("data", {}) or {}).get("structure_id", "") or "")
    assert cs_event_structure_id

    app.hdb._structure_store.add_diff_entry(
        structure_source["id"],
        target_id=cs_event_structure_id,
        content_signature="cs_event::pytest::left_right",
        base_weight=0.9,
        residual_existing_signature="",
        residual_incoming_signature="tail",
        ext={"relation_type": "incoming_extension"},
    )

    assert app.pool.insert_runtime_node(
        _runtime_projection(structure_source, er=0.2, ev=5.0),
        trace_id="seed_runtime_cs_event_source",
        source_module="pytest",
    )["success"] is True

    app.hdb._config["induction_filter_nonprojectable_targets"] = True
    hint_count = app._estimate_induction_local_target_hint(structure_source["id"])
    assert hint_count == 0

    snapshot = app._build_induction_source_snapshot(
        trace_id="pytest_induction_filter_cs_event",
        tick_id="pytest_induction_filter_cs_event",
    )
    top_items = list(snapshot.get("top_items", []))
    assert top_items
    source_item = next(item for item in top_items if item.get("ref_object_id") == structure_source["id"])
    assert source_item["induction_source_local_target_hint_count"] == 0

    induction_res = app.hdb.run_induction_propagation(
        state_snapshot=snapshot,
        trace_id="pytest_induction_filter_cs_event",
        tick_id="pytest_induction_filter_cs_event",
        max_source_items=1,
    )
    assert induction_res["success"] is True
    data = induction_res["data"]
    assert data["induction_targets"] == []
    assert data["propagated_target_count"] == 0
    assert data["total_delta_ev"] == 0.0


def test_observatory_static_flow_order_matches_runtime():
    app_js = Path(__file__).resolve().parents[1] / "web_static" / "app.js"
    html_renderer = Path(__file__).resolve().parents[1] / "_render_html.py"

    app_js_text = app_js.read_text(encoding="utf-8")
    html_text = html_renderer.read_text(encoding="utf-8")

    # Frontend flow blocks may be renumbered when optional stages (e.g. Cognitive Stitching) are enabled/disabled.
    # 前端流程块的序号可能会因为“可选阶段开关”（例如认知拼接）而变化，因此这里按标题关键词做顺序约束，不依赖固定编号。
    assert app_js_text.index("缓存中和") < app_js_text.index("刺激级查存一体")
    assert app_js_text.index("刺激级查存一体") < app_js_text.index("状态池回写与结构投影")
    assert html_text.rindex("<a href='#cache'>") < html_text.rindex("<a href='#stimulus'>")
    assert html_text.rindex("<a href='#stimulus'>") < html_text.rindex("<a href='#projection'>")
    # NOTE:
    # We allow a bounded setInterval for the Action/Drive runtime monitoring auto-refresh.
    # 允许用于行动模块运行态监控的 setInterval（可启动/可停止），以满足“实时监控”验收需求。
    assert "setInterval(" in app_js_text
    assert "clearInterval(" in app_js_text
    assert "actionRuntimeAutoTimer" in app_js_text
    # The UI title is Chinese-first but should still contain the bilingual keyword.
    # UI 标题中文优先，但仍应包含双语关键词，便于稳定检索与回归测试。
    assert ("MAP 兼容反馈" in app_js_text) and ("Compat Feedback" in app_js_text)
    assert app_js_text.count("function renderSettingsInput(") == 1
    assert app_js_text.count("function fmtMemoryActivationCard(") == 1
    assert app_js_text.count("async function refreshDashboard(") == 1


def test_observatory_renders_grouped_csa_and_structure_storage_details(tmp_path):
    grouped_text = f"[{HI} + stimulus_intensity:1.1] / [{YA} + stimulus_intensity:1.1] / !"
    report = {
        "trace_id": "obs_dbg_001",
        "sensor": {},
        "maintenance": {"before_summary": {}, "after_summary": {}, "summary": {}, "events": []},
        "attention": {"top_items": [], "structure_items": []},
        "structure_level": {
            "result": {
                "cam_stub_count": 1,
                "round_count": 1,
                "matched_group_ids": [],
                "new_group_ids": [],
                "fallback_used": False,
                "debug": {
                    "cam_items": [
                        {
                            "structure_id": "st_000239",
                            "display_text": HI,
                            "grouped_display_text": HI,
                            "er": 0.4988,
                            "ev": 0.0,
                            "total_energy": 0.4988,
                        }
                    ],
                    "round_details": [
                        {
                            "round_index": 1,
                            "anchor": {
                                "structure_id": "st_000239",
                                "display_text": HI,
                                "grouped_display_text": HI,
                                "anchor_score": 1.0,
                            },
                            "budget_before": {
                                "st_000239": {"er": 0.4988, "ev": 0.0, "total": 0.4988},
                            },
                            "budget_after": {
                                "st_000239": {"er": 0.4988, "ev": 0.0, "total": 0.4988},
                            },
                            "chain_steps": [
                                {"owner_kind": "st", "owner_id": "st_000239", "owner_display_text": HI, "candidate_count": 0}
                            ],
                            "selected_group": {
                                "group_id": "sg_single_st_000239",
                                "display_text": HI,
                                "grouped_display_text": HI,
                                "score": 1.0,
                                "base_similarity": 1.0,
                                "coverage_ratio": 1.0,
                                "structure_ratio": 1.0,
                                "wave_similarity": 1.0,
                                "required_structures": [{"structure_id": "st_000239", "display_text": HI}],
                                "bias_structures": [],
                                "common_part": {"common_display": HI},
                            },
                            "storage_summary": {
                                "owner_display_text": HI,
                                "owner_kind": "st",
                                "resolved_db_id": "sdb_000239",
                                "new_group_ids": [],
                                "new_structure_ids": [],
                                "actions": [
                                    {
                                        "type": "append_raw_residual",
                                        "type_zh": "追加原始残差信息",
                                        "storage_table": "group_residual_table",
                                        "storage_table_zh": "结构数据库.结构组残差表",
                                        "entry_id": "sgr_000001",
                                        "raw_display_text": f"SELF[st_000239:{HI}] / {YA} / stimulus_intensity:1.1",
                                        "canonical_display_text": f"{HI} / {YA} / stimulus_intensity:1.1",
                                        "memory_id": "em_000128",
                                    }
                                ],
                            },
                            "candidate_groups": [],
                            "internal_fragments": [],
                        }
                    ],
                    "new_group_details": [],
                },
            }
        },
        "cache_neutralization": {
            "priority_summary": {
                "priority_neutralized_item_count": 0,
                "priority_event_count": 0,
                "consumed_er": 0.0,
                "consumed_ev": 0.0,
                "input_flat_token_count": 0,
                "residual_flat_token_count": 0,
            },
            "input_packet": {"display_text": grouped_text, "total_er": 2.2, "total_ev": 0.0, "flat_tokens": []},
            "residual_packet": {"display_text": grouped_text, "total_er": 2.2, "total_ev": 0.0, "flat_tokens": []},
            "priority_events": [],
        },
        "merged_stimulus": {
            "display_text": grouped_text,
            "total_er": 2.2,
            "total_ev": 0.0,
            "groups": [
                {
                    "group_index": 0,
                    "source_type": "current",
                    "display_text": f"[{HI} + stimulus_intensity:1.1]",
                    "tokens": [HI, "stimulus_intensity:1.1"],
                    "sa_count": 2,
                    "csa_count": 1,
                    "csa_bundles": [f"CSA[{HI} + stimulus_intensity:1.1]"],
                },
                {
                    "group_index": 1,
                    "source_type": "current",
                    "display_text": f"[{YA} + stimulus_intensity:1.1]",
                    "tokens": [YA, "stimulus_intensity:1.1"],
                    "sa_count": 2,
                    "csa_count": 1,
                    "csa_bundles": [f"CSA[{YA} + stimulus_intensity:1.1]"],
                },
                {
                    "group_index": 2,
                    "source_type": "current",
                    "display_text": "[!]",
                    "tokens": ["!"],
                    "sa_count": 1,
                    "csa_count": 0,
                    "csa_bundles": [],
                },
            ],
        },
        "stimulus_level": {
            "result": {
                "round_count": 1,
                "matched_structure_ids": ["st_000245"],
                "new_structure_ids": ["st_000247"],
                "remaining_stimulus_sa_count": 0,
                "fallback_used": False,
                "runtime_projection_structures": [
                    {
                        "projection_kind": "memory",
                        "memory_id": "em_000128",
                        "display_text": grouped_text,
                        "er": 0.6,
                        "ev": 0.0,
                        "reason": "matched_structure",
                    }
                ],
                "debug": {
                    "round_details": [
                        {
                            "round_index": 1,
                            "anchor": {
                                "display_text": HI,
                                "token": HI,
                                "source_type": "current",
                                "group_index": 0,
                                "sequence_index": 0,
                                "er": 1.1,
                                "ev": 0.0,
                            },
                            "focus_group_text_before": f"[{HI} + stimulus_intensity:1.1]",
                            "remaining_grouped_text_before": grouped_text,
                            "remaining_grouped_text_after": grouped_text,
                            "chain_steps": [{"owner_display_text": HI, "owner_structure_id": "st_000239", "candidate_count": 0}],
                            "candidate_details": [
                                {
                                    "structure_id": "st_000245",
                                    "display_text": grouped_text,
                                    "grouped_display_text": grouped_text,
                                    "eligible": True,
                                    "exact_match": True,
                                    "full_structure_included": True,
                                    "competition_score": 0.88,
                                    "stimulus_match_ratio": 0.88,
                                    "structure_match_ratio": 1.0,
                                    "chain_depth": 0,
                                    "owner_structure_id": "",
                                    "match_mode": "candidate_match",
                                    "common_part": {"common_display": grouped_text},
                                }
                            ],
                            "selected_match": {
                                "structure_id": "st_000245",
                                "display_text": grouped_text,
                                "grouped_display_text": grouped_text,
                                "competition_score": 0.88,
                                "match_score": 0.88,
                                "coverage_ratio": 0.88,
                                "structure_match_ratio": 1.0,
                                "exact_match": True,
                                "full_structure_included": True,
                                "match_mode": "candidate_match",
                                "common_part": {"common_display": grouped_text},
                            },
                            "effective_transfer_fraction": 0.88,
                            "transferred_er": 1.936,
                            "transferred_ev": 0.0,
                            "created_common_structure": {
                                "structure_id": "st_000245",
                                "display_text": grouped_text,
                                "grouped_display_text": grouped_text,
                            },
                            "created_residual_structure": {
                                "structure_id": "st_000247",
                                "display_text": grouped_text,
                                "grouped_display_text": grouped_text,
                            },
                            "created_fresh_structure": None,
                        }
                    ]
                },
            }
        },
        "pool_apply": {
            "apply_result": {
                "new_item_count": 1,
                "updated_item_count": 0,
                "merged_item_count": 0,
                "neutralized_item_count": 0,
                "state_delta_summary": {"total_delta_er": 0.6, "total_delta_ev": 0.0},
            },
            "priority_summary": {
                "priority_neutralized_item_count": 0,
                "priority_event_count": 0,
                "consumed_er": 0.0,
                "consumed_ev": 0.0,
                "input_flat_token_count": 0,
                "residual_flat_token_count": 0,
            },
            "input_packet": {"display_text": grouped_text, "total_er": 2.2, "total_ev": 0.0, "flat_tokens": []},
            "residual_packet": {"display_text": grouped_text, "total_er": 2.2, "total_ev": 0.0, "flat_tokens": []},
            "priority_events": [],
            "bias_projection": [],
            "runtime_projection": [
                {
                    "projection_kind": "memory",
                    "memory_id": "em_000128",
                    "display_text": grouped_text,
                    "er": 0.6,
                    "ev": 0.0,
                    "reason": "stimulus_runtime_memory",
                    "result": "inserted",
                }
            ],
            "events": [],
        },
        "induction": {
            "result": {
                "source_item_count": 1,
                "propagated_target_count": 0,
                "induced_target_count": 1,
                "total_delta_ev": 0.5,
                "total_ev_consumed": 0.0,
                "debug": {
                    "source_details": [
                        {
                            "source_structure_id": "st_000245",
                            "display_text": grouped_text,
                            "source_er": 1.0,
                            "source_ev": 0.0,
                            "candidate_entries": [
                                {
                                    "mode": "er_induction",
                                    "projection_kind": "memory",
                                    "memory_id": "em_000128",
                                    "target_display_text": grouped_text,
                                    "normalized_share": 1.0,
                                    "entry_count": 1,
                                    "delta_ev": 0.5,
                                    "runtime_weight": 1.2,
                                    "base_weight": 1.1,
                                    "recent_gain": 1.0,
                                    "fatigue": 0.0,
                                }
                            ],
                        }
                    ]
                },
            },
            "applied_targets": [
                {
                    "projection_kind": "memory",
                    "memory_id": "em_000128",
                    "display_text": grouped_text,
                    "ev": 0.5,
                    "result": "applied",
                }
            ],
        },
        "final_state": {
            "state_snapshot": {"summary": {"active_item_count": 0, "high_er_item_count": 0, "high_ev_item_count": 0, "high_cp_item_count": 0, "object_type_counts": {}}, "top_items": []},
            "state_energy_summary": {"total_er": 0.0, "total_ev": 0.0, "total_cp": 0.0, "energy_by_type": {}},
            "hdb_snapshot": {"summary": {"structure_count": 0, "group_count": 0, "episodic_count": 0, "issue_count": 0, "active_repair_job_count": 0}, "recent_structures": []},
        },
        "exports": {},
    }

    terminal_report = render_cycle_report(report)
    assert "局部库动作 / Local DB Action" in terminal_report
    assert "原始残差/Raw=SELF[st_000239:你好] / 呀 / stimulus_intensity:1.1" in terminal_report
    assert "还原后/Canonical=你好 / 呀 / stimulus_intensity:1.1" in terminal_report
    assert "关联记忆/em_id=em_000128" in terminal_report
    assert f"轮前残余 / Remaining before={grouped_text}" in terminal_report
    assert f"新建共同结构 / New common structure={grouped_text}[st_000245]" in terminal_report
    assert "类型/Kind=残差记忆 / Residual Memory" in terminal_report

    html_path = export_cycle_html(report, tmp_path / "grouped_observatory.html")
    html_text = Path(html_path).read_text(encoding="utf-8")
    assert "局部库动作 / Local DB Action" in html_text
    assert "写入动作 / Write actions" in html_text
    assert "em_000128" in html_text
    assert grouped_text in html_text
    assert "残差记忆 / Residual Memory" in html_text


def test_run_cycle_weather_stub_ignores_system_restore_but_accepts_user_weather_message(app):
    system_report = app.run_cycle(
        text="【系统事件】会话恢复：本数据集仅用于验证天气查询占位实现。",
        labels={"stream": {"role": "system", "kind": "session_restore", "phase": "open"}},
    )
    system_actions = list((system_report.get("action", {}) or {}).get("executed_actions", []) or [])
    assert not any(str(item.get("action_kind", "")) == "weather_stub" for item in system_actions)

    idle_report = app.run_cycle(text=None)
    idle_actions = list((idle_report.get("action", {}) or {}).get("executed_actions", []) or [])
    assert not any(str(item.get("action_kind", "")) == "weather_stub" for item in idle_actions)

    user_report = app.run_cycle(
        text="【用户消息】可以帮我查询一下天气吗？",
        labels={"stream": {"role": "user", "kind": "message", "phase": "weather"}},
    )
    user_actions = list((user_report.get("action", {}) or {}).get("executed_actions", []) or [])
    assert any(
        str(item.get("action_kind", "")) == "weather_stub" and bool(item.get("attempted", False))
        for item in user_actions
    )
    user_nodes = list((user_report.get("action", {}) or {}).get("nodes", []) or [])
    assert any(
        str(node.get("action_kind", "")) == "weather_stub"
        and (
            str(node.get("target_ref_object_id", "") or "").strip()
            or str(node.get("target_item_id", "") or "").strip()
        )
        for node in user_nodes
    )

    completion_report = app.run_cycle(text=None)
    completion_actions = list((completion_report.get("action", {}) or {}).get("executed_actions", []) or [])
    assert any(
        str(item.get("action_kind", "")) == "weather_stub"
        and not bool(item.get("attempted", True))
        and bool(item.get("success", False))
        for item in completion_actions
    )
