# -*- coding: utf-8 -*-

from __future__ import annotations

import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from observatory._config_layout import build_config_view, coerce_updates_by_defaults, load_yaml_dict, save_annotated_config
from observatory._app import DEFAULT_CONFIG, ObservatoryApp
from text_sensor.main import _DEFAULT_CONFIG as TEXT_SENSOR_DEFAULT_CONFIG
from state_pool.main import _DEFAULT_CONFIG as STATE_POOL_DEFAULT_CONFIG
from hdb.main import _DEFAULT_CONFIG as HDB_DEFAULT_CONFIG
from cognitive_stitching.main import _DEFAULT_CONFIG as COGNITIVE_STITCHING_DEFAULT_CONFIG


ROOT = Path(__file__).resolve().parents[2]


def test_build_config_view_covers_all_current_fields():
    module_specs = {
        "observatory": (
            ROOT / "observatory" / "config" / "observatory_config.yaml",
            DEFAULT_CONFIG,
            {},
        ),
        "text_sensor": (
            ROOT / "text_sensor" / "config" / "text_sensor_config.yaml",
            TEXT_SENSOR_DEFAULT_CONFIG,
            {},
        ),
        "state_pool": (
            ROOT / "state_pool" / "config" / "state_pool_config.yaml",
            STATE_POOL_DEFAULT_CONFIG,
            {},
        ),
        "hdb": (
            ROOT / "hdb" / "config" / "hdb_config.yaml",
            HDB_DEFAULT_CONFIG,
            {},
        ),
        "cognitive_stitching": (
            ROOT / "cognitive_stitching" / "config" / "cognitive_stitching_config.yaml",
            COGNITIVE_STITCHING_DEFAULT_CONFIG,
            {},
        ),
    }

    for module_name, (path, defaults, runtime_override) in module_specs.items():
        view = build_config_view(
            module_name=module_name,
            path=str(path),
            defaults=defaults,
            file_values=load_yaml_dict(path),
            effective=dict(defaults),
            runtime_override=runtime_override,
        )
        field_count = sum(len(section["fields"]) for section in view["sections"])
        field_keys = [field["key"] for section in view["sections"] for field in section["fields"]]
        assert field_count == len(defaults)
        assert set(field_keys) == set(defaults)


def test_save_annotated_config_preserves_comments_and_updates_value(tmp_path):
    source = ROOT / "hdb" / "config" / "hdb_config.yaml"
    target = tmp_path / "hdb_config.yaml"
    shutil.copyfile(source, target)

    save_annotated_config(
        path=str(target),
        defaults=HDB_DEFAULT_CONFIG,
        updates={
            "recency_gain_peak": 10.0,
            "recency_gain_decay_ratio": 0.9999976974,
        },
    )

    text = target.read_text(encoding="utf-8")
    assert "recency_gain_peak / 近因增益上限" in text
    assert "recency_gain_peak: 10.0" in text
    assert "recency_gain_decay_ratio / 近因增益每 Tick 保留系数" in text


def test_coerce_updates_by_defaults_handles_list_and_dict_text_payloads():
    updates, rejected = coerce_updates_by_defaults(
        STATE_POOL_DEFAULT_CONFIG,
        {
            "priority_stimulus_target_ref_types": '["st", "sa"]',
            "per_object_type_decay_override": '{"sa": {"er": 0.9, "ev": 0.8}}',
        },
    )

    assert rejected == []
    assert updates["priority_stimulus_target_ref_types"] == ["st", "sa"]
    assert updates["per_object_type_decay_override"] == {"sa": {"er": 0.9, "ev": 0.8}}


def test_observatory_save_module_config_accepts_pipeline_switches(tmp_path):
    source = ROOT / "observatory" / "config" / "observatory_config.yaml"
    target = tmp_path / "observatory_config.yaml"
    shutil.copyfile(source, target)

    app = ObservatoryApp(
        config_path=str(target),
        config_override={
            "export_html": False,
            "export_json": False,
            "web_auto_open_browser": False,
        },
    )
    try:
        result = app.save_module_config(
            "observatory",
            {
                "enable_cognitive_stitching": True,
                "enable_structure_level_retrieval_storage": False,
                "enable_goal_b_char_sa_string_mode": True,
            },
        )

        assert result["rejected_values"] == []
        saved = load_yaml_dict(target)
        assert saved["enable_cognitive_stitching"] is True
        assert saved["enable_structure_level_retrieval_storage"] is False
        assert saved["enable_goal_b_char_sa_string_mode"] is True

        effective = (((result.get("config_bundle", {}) or {}).get("observatory", {}) or {}).get("effective", {}) or {})
        assert effective["enable_structure_level_retrieval_storage"] is False

        text = target.read_text(encoding="utf-8")
        assert "enable_structure_level_retrieval_storage: false" in text
    finally:
        app.close()


def test_observatory_save_module_config_accepts_cognitive_stitching_v2_fields():
    source = ROOT / "cognitive_stitching" / "config" / "cognitive_stitching_config.yaml"
    target = ROOT / "observatory" / "outputs" / "test_tmp_cognitive_stitching_config.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)

    app = ObservatoryApp(
        config_override={
            "export_html": False,
            "export_json": False,
            "web_auto_open_browser": False,
        },
    )
    try:
        app.cognitive_stitching._config_path = str(target)
        result = app.save_module_config(
            "cognitive_stitching",
            {
                "context_concat_result_confidence": 0.79,
                "cs_v2_component_soft_power": 0.7,
                "cs_v2_component_soft_linear_mix": 0.3,
                "cs_v2_base_raw_mix": 0.34,
                "cs_v2_fatigue_soft_power": 0.76,
                "cs_v2_fatigue_soft_linear_mix": 0.38,
                "event_grasp_include_post_cs_action_events": True,
            },
        )

        assert result["rejected_values"] == []
        effective = (((result.get("config_bundle", {}) or {}).get("cognitive_stitching", {}) or {}).get("effective", {}) or {})
        assert effective["context_concat_result_confidence"] == 0.79
        assert effective["cs_v2_component_soft_power"] == 0.7
        assert effective["cs_v2_component_soft_linear_mix"] == 0.3
        assert effective["cs_v2_base_raw_mix"] == 0.34
        assert effective["cs_v2_fatigue_soft_power"] == 0.76
        assert effective["cs_v2_fatigue_soft_linear_mix"] == 0.38
        assert effective["event_grasp_include_post_cs_action_events"] is True
        saved = load_yaml_dict(target)
        assert saved["context_concat_result_confidence"] == 0.79
        assert saved["cs_v2_component_soft_power"] == 0.7
        assert saved["event_grasp_include_post_cs_action_events"] is True
    finally:
        app.close()
        if target.exists():
            target.unlink()
