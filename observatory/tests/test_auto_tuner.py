# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from observatory.experiment import auto_tuner, param_catalog


def test_default_metric_targets_include_distribution_envelopes_for_reward_punish_and_nt_channels():
    targets = {item.key: item for item in auto_tuner._default_metric_targets()}

    for key in ["rwd_pun_rwd", "rwd_pun_pun", "nt_DA", "nt_ADR", "nt_COR", "nt_SER", "nt_OXY", "nt_END"]:
        target = targets[key]
        assert target.high_band_threshold is not None
        assert target.high_band_max_ratio is not None
        assert target.high_band_soft_p95 is not None
        assert target.high_band_max_run is not None


def test_default_metric_targets_follow_param_catalog_for_core_baselines():
    targets = {item.key: item for item in auto_tuner._default_metric_targets()}
    definitions = {item["key"]: item for item in param_catalog.list_metric_definitions()}

    for key in [
        "rwd_pun_rwd",
        "nt_DA",
        "nt_COR",
        "time_sensor_bucket_energy_sum",
        "induction_raw_residual_memory_target_count",
        "induction_raw_residual_memory_target_total_ev",
    ]:
        target = targets[key]
        definition = definitions[key]
        assert target.expected_min == definition["expected_min"]
        assert target.expected_max == definition["expected_max"]
        assert target.ideal == definition["ideal"]
        assert target.min_std == definition["min_std"]


def test_attention_energy_budget_defaults_are_capped_near_ten():
    targets = {item.key: item for item in auto_tuner._default_metric_targets()}
    bounds = auto_tuner._default_param_bounds()

    budget_target = targets["attention_energy_budget"]
    net_delta_target = targets["attention_net_delta_energy"]
    budget_bound = bounds["attention.attention_energy_budget_base"]

    assert 0.0 <= budget_target.expected_min <= 4.0
    assert budget_target.expected_max <= 18.0
    assert budget_target.ideal <= 10.0
    assert net_delta_target.expected_max <= 12.0
    assert net_delta_target.ideal <= 8.0
    assert budget_bound.max_value <= 10.0
    assert budget_bound.max_step_abs == 1.0


def test_attention_budget_related_catalog_bounds_do_not_reopen_high_baseline():
    specs = [
        param_catalog.ParamSpec(
            param_id="action.mode_attention_energy_budget_base",
            source_kind="module_config",
            module="action",
            path_tokens=["mode_attention_energy_budget_base"],
            value=10.0,
            value_type="float",
            auto_tune_allowed=True,
            tags=[],
            impacts=[],
        ),
        param_catalog.ParamSpec(
            param_id="emotion.modulation.attention.field_specs.attention_energy_budget.base",
            source_kind="module_config",
            module="emotion",
            path_tokens=["modulation", "attention", "field_specs", "attention_energy_budget", "base"],
            value=10.0,
            value_type="float",
            auto_tune_allowed=True,
            tags=[],
            impacts=[],
        ),
        param_catalog.ParamSpec(
            param_id="attention.attention_energy_budget_max",
            source_kind="module_config",
            module="attention",
            path_tokens=["attention_energy_budget_max"],
            value=32.0,
            value_type="float",
            auto_tune_allowed=True,
            tags=[],
            impacts=[],
        ),
    ]
    bounds = param_catalog.build_default_param_bounds(specs)

    assert bounds["action.mode_attention_energy_budget_base"].max_value <= 10.0
    assert bounds["emotion.modulation.attention.field_specs.attention_energy_budget.base"].max_value <= 10.0
    assert bounds["attention.attention_energy_budget_max"].max_value == 32.0


def test_default_metric_targets_skip_diagnostic_only_metrics():
    targets = {item.key: item for item in auto_tuner._default_metric_targets()}

    assert "induction_raw_residual_entry_materialized_structure_count" not in targets
    assert "hdb_primary_pointer_count" not in targets
    assert "hdb_exact_lookup_cache_count" not in targets
    assert "hdb_contextual_structure_ratio" not in targets
    assert "hdb_multi_context_structure_ratio" not in targets


def test_default_metric_targets_zero_out_raw_residual_memory_targets_under_structure_mode():
    targets = {item.key: item for item in auto_tuner._default_metric_targets()}

    count_target = targets["induction_raw_residual_memory_target_count"]
    ev_target = targets["induction_raw_residual_memory_target_total_ev"]

    assert count_target.expected_max == 0.0
    assert count_target.ideal == 0.0
    assert ev_target.expected_max == 0.0
    assert ev_target.ideal == 0.0


def test_normalize_metric_target_item_accepts_distribution_fields_and_tolerates_bad_run_cap():
    norm = auto_tuner._normalize_metric_target_item(
        {
            "key": "rwd_pun_rwd",
            "expected_min": 0.0,
            "expected_max": 0.55,
            "ideal": 0.24,
            "min_std": 0.03,
            "weight": 0.6,
            "high_band_threshold": "0.5",
            "high_band_max_ratio": "0.2",
            "high_band_soft_p95": "0.72",
            "high_band_max_run": "bad-value",
        }
    )

    assert norm is not None
    assert norm["high_band_threshold"] == 0.5
    assert norm["high_band_max_ratio"] == 0.2
    assert norm["high_band_soft_p95"] == 0.72
    assert norm["high_band_max_run"] is None


def test_save_public_config_preserves_ev_ratio_and_memory_feedback_toggles(monkeypatch, tmp_path):
    cfg_path = tmp_path / "auto_tuner_config.json"
    monkeypatch.setattr(auto_tuner, "_config_path", lambda: cfg_path)
    monkeypatch.setattr(auto_tuner, "_load_raw_config_dict", lambda: {})

    saved = auto_tuner.save_auto_tuner_public_config(
        {
            "enabled": True,
            "enable_ev_er_ratio_tuning": False,
            "enable_memory_feedback_tuning": True,
        }
    )

    loaded = auto_tuner.load_auto_tuner_config()
    assert saved["config"]["enable_ev_er_ratio_tuning"] is False
    assert saved["config"]["enable_memory_feedback_tuning"] is True
    assert loaded.enable_ev_er_ratio_tuning is False
    assert loaded.enable_memory_feedback_tuning is True


def test_auto_tuner_missing_config_keeps_ev_ratio_tuning_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(auto_tuner, "_config_path", lambda: tmp_path / "missing_config.json")

    cfg = auto_tuner.load_auto_tuner_config()

    assert cfg.enable_ev_er_ratio_tuning is False


def test_public_config_exposes_defaults_and_overrides_for_frontend_editors(monkeypatch, tmp_path):
    cfg_path = tmp_path / "auto_tuner_config.json"
    monkeypatch.setattr(auto_tuner, "_config_path", lambda: cfg_path)

    cfg_path.write_text(
        json.dumps(
            {
                "metric_targets": [
                    {
                        "key": "attention_energy_budget",
                        "expected_min": 5.0,
                        "expected_max": 12.0,
                        "ideal": 9.0,
                    }
                ],
                "param_bounds": {
                    "attention.attention_energy_budget_base": {
                        "min_value": 1.0,
                        "max_value": 9.0,
                        "max_step_abs": 1.0,
                        "quantum": 1.0,
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = auto_tuner.load_auto_tuner_public_config()

    assert payload["metric_target_defaults"]
    assert payload["metric_target_overrides"][0]["key"] == "attention_energy_budget"
    assert payload["param_bounds"]["attention.attention_energy_budget_base"]["max_value"] == 9.0


def test_merge_metric_target_defs_keeps_catalog_distribution_defaults_when_override_omits_optional_fields(monkeypatch):
    monkeypatch.setattr(
        auto_tuner,
        "_load_raw_config_dict",
        lambda: {
            "metric_targets": [
                {
                    "key": "rwd_pun_rwd",
                    "expected_min": 0.0,
                    "expected_max": 0.55,
                    "ideal": 0.25,
                    "min_std": 0.02,
                    "weight": 0.55,
                }
            ]
        },
    )

    merged = {item["key"]: item for item in auto_tuner._merge_metric_target_defs()}
    reward_def = merged["rwd_pun_rwd"]

    assert reward_def["expected_max"] == 0.55
    assert reward_def["ideal"] == 0.25
    assert reward_def["high_band_threshold"] == 0.50
    assert reward_def["high_band_max_ratio"] == 0.20
    assert reward_def["high_band_soft_p95"] == 0.72
    assert reward_def["high_band_max_run"] == 3


def test_metric_issue_snapshot_uses_high_band_occupancy_even_when_mean_is_not_above_expected_max():
    target = auto_tuner.MetricTarget(
        key="cfs_dissonance_max",
        expected_min=0.0,
        expected_max=0.55,
        ideal=0.18,
        min_std=0.03,
        high_band_threshold=0.50,
        high_band_max_ratio=0.20,
        high_band_soft_p95=0.68,
        high_band_max_run=2,
    )
    tuner = auto_tuner.AutoTuner.__new__(auto_tuner.AutoTuner)
    tuner.metric_targets = {target.key: target}

    rows = [{"cfs_dissonance_max": value} for value in [0.12, 0.18, 0.20, 0.16, 0.74, 0.76, 0.78, 0.14, 0.18, 0.20]]
    issue = auto_tuner.AutoTuner._metric_issue_snapshot(tuner, rows=rows, metric_key="cfs_dissonance_max")

    assert issue is not None
    assert issue["mean"] < target.expected_max
    assert issue["band"]["occupancy_ratio"] == 0.3
    assert issue["band"]["occupancy_over_ratio"] > 0.0
    assert issue["high_ratio"] > 0.0


def test_auto_tuner_constructor_preserves_default_distribution_caps_for_partial_metric_overrides(monkeypatch, tmp_path):
    monkeypatch.setattr(auto_tuner, "load_auto_tuner_config", lambda: auto_tuner.AutoTunerConfig())
    monkeypatch.setattr(
        auto_tuner,
        "_load_raw_config_dict",
        lambda: {
            "metric_targets": [
                {
                    "key": "rwd_pun_rwd",
                    "expected_min": 0.0,
                    "expected_max": 0.55,
                    "ideal": 0.25,
                    "min_std": 0.02,
                    "weight": 0.55,
                }
            ]
        },
    )
    monkeypatch.setattr(auto_tuner, "load_auto_tuner_rules", lambda: auto_tuner._default_rules_payload())
    monkeypatch.setattr(auto_tuner.AutoTuner, "_load_state", lambda self: auto_tuner._default_state_payload())
    monkeypatch.setattr(auto_tuner.AutoTuner, "_ensure_candidate_observations", lambda self: None)
    monkeypatch.setattr(auto_tuner.param_catalog, "build_param_catalog", lambda app=None: [])
    monkeypatch.setattr(auto_tuner.param_catalog, "build_default_param_bounds", lambda specs: {})

    tuner = auto_tuner.AutoTuner(
        app=None,
        run_dir=tmp_path / "run",
        enabled=False,
        enable_short_term=False,
        enable_long_term=False,
    )

    reward_target = tuner.metric_targets["rwd_pun_rwd"]
    assert reward_target.expected_max == 0.55
    assert reward_target.ideal == 0.25
    assert reward_target.high_band_threshold == 0.50
    assert reward_target.high_band_max_ratio == 0.20
    assert reward_target.high_band_soft_p95 == 0.72
    assert reward_target.high_band_max_run == 3


def test_prepare_and_apply_overrides_rebuilds_runtime_rules_from_latest_baseline(monkeypatch, tmp_path):
    monkeypatch.setattr(auto_tuner, "load_auto_tuner_config", lambda: auto_tuner.AutoTunerConfig())
    monkeypatch.setattr(auto_tuner, "_load_raw_config_dict", lambda: {})
    monkeypatch.setattr(auto_tuner, "load_auto_tuner_rules", lambda: auto_tuner._default_rules_payload())
    monkeypatch.setattr(auto_tuner.AutoTuner, "_load_state", lambda self: auto_tuner._default_state_payload())
    monkeypatch.setattr(auto_tuner.AutoTuner, "_ensure_candidate_observations", lambda self: None)
    monkeypatch.setattr(auto_tuner.param_catalog, "build_param_catalog", lambda app=None: [])
    monkeypatch.setattr(auto_tuner.param_catalog, "build_default_param_bounds", lambda specs: {})
    monkeypatch.setattr(auto_tuner, "_overrides_dir", lambda: tmp_path / "overrides")
    monkeypatch.setattr(auto_tuner.AutoTuner, "_get_runtime_module_config", lambda self, module: {})
    monkeypatch.setattr(auto_tuner.AutoTuner, "_reload_module_config", lambda self, module, trace_id, config_path: {"code": "OK"})

    repo_root = tmp_path / "repo"
    innate_dir = repo_root / "innate_script" / "config"
    innate_dir.mkdir(parents=True, exist_ok=True)
    baseline_rules_path = innate_dir / "innate_rules.yaml"
    baseline_doc = {
        "rules_schema_version": "1.0",
        "rules_version": "0.6",
        "enabled": True,
        "defaults": {},
        "rules": [
            {
                "id": "innate_action_weather_stub_from_query_weather",
                "title": "weather query",
                "phase": "directives",
                "enabled": True,
                "priority": 1,
                "cooldown_ticks": 0,
                "when": {
                    "all": [
                        {
                            "metric": {
                                "metric": "item.exists",
                                "selector": {"mode": "contains_text", "contains_text": "天气", "ref_object_types": ["input"]},
                                "op": ">=",
                                "value": 0.0,
                            }
                        },
                        {
                            "any": [
                                {
                                    "metric": {
                                        "metric": "item.exists",
                                        "selector": {"mode": "contains_text", "contains_text": "查询", "ref_object_types": ["input"]},
                                        "op": ">=",
                                        "value": 0.0,
                                    }
                                },
                                {
                                    "metric": {
                                        "metric": "item.exists",
                                        "selector": {"mode": "contains_text", "contains_text": "帮我查", "ref_object_types": ["input"]},
                                        "op": ">=",
                                        "value": 0.0,
                                    }
                                },
                            ]
                        },
                    ]
                },
                "then": [
                    {
                        "action_trigger": {
                            "from": "metric_matches",
                            "match_policy": "strongest",
                            "max_triggers": 1,
                            "action_kind": "weather_stub",
                            "action_id": "weather_stub",
                            "gain": 0.75,
                            "threshold": 0.60,
                        }
                    }
                ],
            }
        ],
    }
    baseline_rules_path.write_text(auto_tuner.io.dump_yaml(baseline_doc).strip() + "\n", encoding="utf-8")

    stale_persist_doc = {
        "rules_schema_version": "1.0",
        "rules_version": "0.6",
        "enabled": True,
        "defaults": {},
        "rules": [
            {
                "id": "innate_action_weather_stub_from_query_weather",
                "title": "weather query",
                "phase": "directives",
                "enabled": True,
                "priority": 1,
                "cooldown_ticks": 0,
                "when": {
                    "all": [
                        {
                            "metric": {
                                "metric": "item.exists",
                                "selector": {"mode": "contains_text", "contains_text": "天气", "ref_object_types": ["input"]},
                                "op": ">=",
                                "value": 0.0,
                            }
                        },
                        {
                            "metric": {
                                "metric": "item.exists",
                                "selector": {"mode": "contains_text", "contains_text": "查询", "ref_object_types": ["input"]},
                                "op": ">=",
                                "value": 0.0,
                            }
                        },
                    ]
                },
                "then": [],
            }
        ],
    }

    fake_iesm = SimpleNamespace(
        _rules_path=str(baseline_rules_path),
        reload_config=lambda trace_id, config_path: {"code": "OK"},
        reload_rules=lambda trace_id: {"code": "OK"},
    )
    fake_app = SimpleNamespace(iesm=fake_iesm)
    monkeypatch.setattr(auto_tuner.storage, "repo_root", lambda: repo_root)

    tuner = auto_tuner.AutoTuner(
        app=fake_app,
        run_dir=tmp_path / "run",
        enabled=True,
        enable_short_term=False,
        enable_long_term=False,
    )
    tuner.persist_rules_path.parent.mkdir(parents=True, exist_ok=True)
    tuner.persist_rules_path.write_text(auto_tuner.io.dump_yaml(stale_persist_doc).strip() + "\n", encoding="utf-8")

    tuner.prepare_and_apply_overrides(trace_id="pytest_sync_rules")

    runtime_doc = yaml.safe_load(tuner.runtime_rules_path.read_text(encoding="utf-8"))
    rule = next(item for item in runtime_doc["rules"] if item.get("id") == "innate_action_weather_stub_from_query_weather")
    when_all = rule["when"]["all"]
    any_branch = when_all[1]["any"]
    selector_texts = [child["metric"]["selector"]["contains_text"] for child in any_branch]
    assert "帮我查" in selector_texts


def test_apply_param_update_can_defer_runtime_reload_and_state_save():
    tuner = auto_tuner.AutoTuner.__new__(auto_tuner.AutoTuner)
    tuner.param_bounds = {
        "hdb.ev_propagation_ratio": auto_tuner.ParamBound(0.10, 1.00, 0.10, quantum=0.01),
    }
    tuner.spec_by_id = {}
    tuner.runtime_params = {"hdb.ev_propagation_ratio": 0.40}
    tuner.persisted_params = {"hdb.ev_propagation_ratio": 0.40}
    tuner.cfg = auto_tuner.AutoTunerConfig()
    runtime_calls: list[tuple[str, list[str]]] = []
    persist_calls: list[list[str]] = []
    save_calls: list[bool] = []
    tuner._apply_overrides_to_runtime = lambda trace_id, touched_modules=None: runtime_calls.append(
        (str(trace_id), sorted(str(item) for item in (touched_modules or set())))
    )
    tuner._apply_persisted_overrides_to_persist_files = lambda touched_modules=None: persist_calls.append(
        sorted(str(item) for item in (touched_modules or set()))
    )
    tuner._save_state = lambda: save_calls.append(True)

    update = {"param": "hdb.ev_propagation_ratio", "delta": 0.05}
    ok = auto_tuner.AutoTuner._apply_param_update(
        tuner,
        update,
        persist=True,
        apply_runtime=False,
        write_persist_files=False,
        save_state=False,
    )

    assert ok is True
    assert tuner.runtime_params["hdb.ev_propagation_ratio"] == 0.45
    assert tuner.persisted_params["hdb.ev_propagation_ratio"] == 0.45
    assert update["from"] == 0.40
    assert update["to"] == 0.45
    assert runtime_calls == []
    assert persist_calls == []
    assert save_calls == []


def test_apply_overrides_to_runtime_reloads_only_touched_modules(tmp_path):
    tuner = auto_tuner.AutoTuner.__new__(auto_tuner.AutoTuner)
    tuner.enabled = True
    tuner.runtime_rules_path = tmp_path / "runtime_rules.yaml"
    tuner.runtime_rules_path.write_text("rules_schema_version: '1.0'\nrules: []\n", encoding="utf-8")
    tuner.runtime_params = {}
    tuner.runtime_module_patch_paths = {
        "cognitive_stitching": tmp_path / "cognitive_stitching.yaml",
        "hdb": tmp_path / "hdb.yaml",
        "emotion": tmp_path / "emotion.yaml",
        "innate_script": tmp_path / "innate.yaml",
    }
    tuner._base_module_configs = {"cognitive_stitching": {}, "hdb": {}, "emotion": {}, "innate_script": {}}
    tuner._materialize_module_patch = lambda module, params, base: {"value": 1} if module in {"cognitive_stitching", "hdb", "emotion"} else {}
    reloaded: list[tuple[str, str]] = []
    tuner._reload_module_config = (
        lambda module, trace_id, config_path: reloaded.append((str(module), Path(config_path).name)) or {"code": "OK"}
    )

    def _unexpected_reload_rules(trace_id):
        raise AssertionError("innate rules should not reload for unrelated touched modules")

    tuner.app = SimpleNamespace(iesm=SimpleNamespace(reload_rules=_unexpected_reload_rules))

    auto_tuner.AutoTuner._apply_overrides_to_runtime(
        tuner,
        trace_id="pytest_runtime_apply",
        touched_modules={"cognitive_stitching", "hdb"},
    )

    assert reloaded == [("cognitive_stitching", "cognitive_stitching.yaml"), ("hdb", "hdb.yaml")]
    assert (tmp_path / "cognitive_stitching.yaml").exists()
    assert (tmp_path / "hdb.yaml").exists()
    assert not (tmp_path / "emotion.yaml").exists()


def test_build_param_catalog_exposes_cognitive_stitching_param_specs():
    specs = {item.param_id: item for item in param_catalog.build_param_catalog()}

    assert "cognitive_stitching.min_candidate_score" in specs
    assert "cognitive_stitching.max_seed_items" in specs
    assert "cognitive_stitching.context_concat_max_targets_per_seed" in specs


def test_param_catalog_exposes_distribution_metadata_for_reward_punish_and_nt_metrics():
    definitions = {item["key"]: item for item in param_catalog.list_metric_definitions()}

    for key in ["cfs_dissonance_max", "cfs_pressure_max", "cfs_expectation_max", "rwd_pun_rwd", "rwd_pun_pun", "nt_DA", "nt_ADR", "nt_COR", "nt_SER", "nt_OXY", "nt_END"]:
        item = definitions[key]
        assert item["high_band_threshold"] == 0.50
        assert "description" in item and item["description"]

    assert definitions["rwd_pun_rwd"]["expected_max"] == 0.60
    assert definitions["rwd_pun_rwd"]["ideal"] == 0.24
    assert "半量程" in definitions["rwd_pun_rwd"]["description"]


def test_default_metric_targets_exclude_legacy_context_and_cs_diagnostic_metrics():
    targets = {item.key: item for item in auto_tuner._default_metric_targets()}

    for key in [
        "pool_contextual_item_ratio",
        "pool_residual_origin_item_ratio",
        "hdb_contextual_structure_ratio",
        "hdb_multi_context_structure_ratio",
        "hdb_same_content_multi_context_ratio",
        "cs_candidate_rejected_low_score_count",
        "cs_candidate_threshold_margin_mean",
    ]:
        assert key not in targets

    for key in [
        "pool_runtime_resolution_degraded_item_count",
        "pool_runtime_resolution_active_component_count",
        "pool_runtime_resolution_dropped_component_count",
        "maintenance_runtime_resolution_refreshed_item_count",
        "maintenance_runtime_resolution_degraded_item_count",
        "hdb_residual_diff_entry_ratio",
    ]:
        assert key in targets


def test_param_catalog_exposes_runtime_resolution_and_legacy_diagnostic_metric_definitions():
    definitions = {item["key"]: item for item in param_catalog.list_metric_definitions()}

    assert definitions["pool_contextual_item_ratio"]["group"] == "旧上下文审计"
    assert definitions["pool_contextual_item_ratio"]["diagnostic_only"] is True
    assert "owner/context" in definitions["pool_contextual_item_ratio"]["description"]
    assert definitions["pool_residual_origin_item_ratio"]["group"] == "旧上下文审计"
    assert definitions["pool_residual_origin_item_ratio"]["diagnostic_only"] is True
    assert definitions["hdb_contextual_structure_ratio"]["diagnostic_only"] is True
    assert "旧上下文残留" in definitions["hdb_contextual_structure_ratio"]["description"]
    assert definitions["hdb_multi_context_structure_ratio"]["diagnostic_only"] is True
    assert definitions["hdb_same_content_multi_context_ratio"]["diagnostic_only"] is True
    assert "不再表示主链必须制造多上下文身份" in definitions["hdb_same_content_multi_context_ratio"]["description"]
    assert definitions["pool_runtime_resolution_degraded_item_count"]["group"] == "状态池运行态分辨率"
    assert "不代表 HDB 新建了退化身份" in definitions["pool_runtime_resolution_degraded_item_count"]["description"]
    assert "残差" in definitions["hdb_residual_diff_entry_ratio"]["description"]
    assert definitions["cs_candidate_rejected_low_score_count"]["group"] == "认知拼接"
    assert definitions["cs_candidate_rejected_low_score_count"]["diagnostic_only"] is True
    assert "阈值" in definitions["cs_candidate_threshold_margin_mean"]["description"]


def test_param_catalog_exposes_event_grasp_pipeline_metric_definitions():
    definitions = {item["key"]: item for item in param_catalog.list_metric_definitions()}

    assert definitions["cs_event_grasp_emitted_count"]["group"] == "认知拼接"
    assert "旧 CS 事件" in definitions["cs_event_grasp_emitted_count"]["description"]
    assert definitions["cs_event_grasp_post_action_seed_count"]["group"] == "认知拼接"
    assert "旧 CS 新建/强化事件动作" in definitions["cs_event_grasp_post_action_seed_count"]["description"]
    assert definitions["cs_event_grasp_post_action_seed_count"]["diagnostic_only"] is True
    assert definitions["cs_event_grasp_cam_selected_event_count"]["group"] == "认知拼接"


def test_cognitive_stitching_nudges_use_candidate_audit_reasons():
    tuner = auto_tuner.AutoTuner.__new__(auto_tuner.AutoTuner)
    tuner.disabled_rule_ids = []
    tuner.spec_by_id = {}
    tuner._get_runtime_module_config = lambda module: {
        "enabled": True,
        "snapshot_top_k": 48,
        "max_seed_items": 16,
        "max_events_per_tick": 4,
        "context_concat_max_targets_per_seed": 10,
    } if module == "cognitive_stitching" else {}
    tuner.param_bounds = {
        "cognitive_stitching.min_candidate_score": auto_tuner.ParamBound(0.05, 0.60, 0.03, quantum=0.005),
        "cognitive_stitching.min_seed_total_energy": auto_tuner.ParamBound(0.10, 0.90, 0.04, quantum=0.005),
        "cognitive_stitching.snapshot_top_k": auto_tuner.ParamBound(24.0, 96.0, 8.0, quantum=1.0),
        "cognitive_stitching.max_seed_items": auto_tuner.ParamBound(8.0, 32.0, 4.0, quantum=1.0),
        "cognitive_stitching.max_events_per_tick": auto_tuner.ParamBound(2.0, 8.0, 1.0, quantum=1.0),
        "cognitive_stitching.context_concat_max_targets_per_seed": auto_tuner.ParamBound(6.0, 20.0, 2.0, quantum=1.0),
        "cognitive_stitching.max_event_component_count": auto_tuner.ParamBound(4.0, 16.0, 1.0, quantum=1.0),
        "cognitive_stitching.anchor_distance_penalty": auto_tuner.ParamBound(0.00, 0.80, 0.04, quantum=0.01),
        "cognitive_stitching.match_strength_weight": auto_tuner.ParamBound(0.05, 1.20, 0.06, quantum=0.01),
        "cognitive_stitching.context_support_weight": auto_tuner.ParamBound(0.00, 0.90, 0.04, quantum=0.01),
    }
    tuner.metric_targets = {
        "timing_cognitive_stitching_ms": auto_tuner.MetricTarget(
            key="timing_cognitive_stitching_ms",
            expected_min=0.0,
            expected_max=1200.0,
            ideal=180.0,
            min_std=25.0,
        )
    }

    low_score_rows = [
        {
            "cs_candidate_raw_accepted_count": 0.0,
            "cs_candidate_count": 0.0,
            "cs_candidate_rejected_low_score_count": 3.0,
            "cs_candidate_rejected_component_limit_count": 0.0,
            "cs_candidate_rejected_non_positive_edge_count": 0.0,
            "cs_candidate_replacement_count": 0.0,
            "cs_candidate_kept_existing_count": 0.0,
            "cs_candidate_threshold_margin_mean": 0.0,
            "cs_action_count": 0.0,
            "cs_created_count": 0.0,
            "cs_extended_count": 0.0,
            "cs_merged_count": 0.0,
            "cs_reinforced_count": 0.0,
            "stimulus_new_structure_count": 1.0,
            "timing_cognitive_stitching_ms": 80.0,
        }
        for _ in range(4)
    ]
    low_score_snapshot = auto_tuner.AutoTuner._cognitive_stitching_snapshot(tuner, rows=low_score_rows)
    low_score_updates = auto_tuner.AutoTuner._decide_cognitive_stitching_nudges(tuner, snapshot=low_score_snapshot, long_term=False)
    low_score_params = {item["param"] for item in low_score_updates}
    assert "cognitive_stitching.min_candidate_score" in low_score_params
    assert "cognitive_stitching.min_seed_total_energy" in low_score_params

    supply_rows = [
        {
            "cs_candidate_raw_accepted_count": 1.1,
            "cs_candidate_count": 1.2,
            "cs_candidate_rejected_low_score_count": 0.1,
            "cs_candidate_rejected_component_limit_count": 0.0,
            "cs_candidate_rejected_non_positive_edge_count": 0.0,
            "cs_candidate_replacement_count": 0.0,
            "cs_candidate_kept_existing_count": 0.0,
            "cs_candidate_threshold_margin_mean": 0.04,
            "cs_action_count": 0.0,
            "cs_created_count": 0.0,
            "cs_extended_count": 0.0,
            "cs_merged_count": 0.0,
            "cs_reinforced_count": 0.0,
            "cs_event_grasp_emitted_count": 0.0,
            "cs_event_grasp_selected_event_count": 0.0,
            "cs_event_grasp_post_action_seed_count": 0.0,
            "cs_event_grasp_post_action_selected_event_count": 0.0,
            "cs_narrative_top_grasp": 0.0,
            "cs_narrative_grasp_max": 0.0,
            "cs_narrative_grasp_positive_count": 0.0,
            "stimulus_new_structure_count": 0.8,
            "timing_cognitive_stitching_ms": 90.0,
        }
        for _ in range(4)
    ]
    supply_snapshot = auto_tuner.AutoTuner._cognitive_stitching_snapshot(tuner, rows=supply_rows)
    supply_updates = auto_tuner.AutoTuner._decide_cognitive_stitching_nudges(tuner, snapshot=supply_snapshot, long_term=False)
    supply_params = {item["param"] for item in supply_updates}
    assert "cognitive_stitching.snapshot_top_k" in supply_params
    assert "cognitive_stitching.max_seed_items" in supply_params
    assert "cognitive_stitching.max_events_per_tick" in supply_params
    assert "cognitive_stitching.context_concat_max_targets_per_seed" in supply_params

    component_limit_rows = [
        {
            "cs_candidate_raw_accepted_count": 0.0,
            "cs_candidate_count": 0.0,
            "cs_candidate_rejected_low_score_count": 0.0,
            "cs_candidate_rejected_component_limit_count": 2.0,
            "cs_candidate_rejected_non_positive_edge_count": 0.0,
            "cs_candidate_replacement_count": 0.0,
            "cs_candidate_kept_existing_count": 0.0,
            "cs_candidate_threshold_margin_mean": 0.0,
            "cs_action_count": 0.0,
            "cs_created_count": 0.0,
            "cs_extended_count": 0.0,
            "cs_merged_count": 0.0,
            "cs_reinforced_count": 0.0,
            "stimulus_new_structure_count": 1.0,
            "timing_cognitive_stitching_ms": 80.0,
        }
        for _ in range(4)
    ]
    component_limit_snapshot = auto_tuner.AutoTuner._cognitive_stitching_snapshot(tuner, rows=component_limit_rows)
    component_limit_updates = auto_tuner.AutoTuner._decide_cognitive_stitching_nudges(tuner, snapshot=component_limit_snapshot, long_term=False)
    assert any(item["param"] == "cognitive_stitching.max_event_component_count" for item in component_limit_updates)


def test_cognitive_stitching_event_grasp_gate_uses_post_action_focus_evidence():
    tuner = auto_tuner.AutoTuner.__new__(auto_tuner.AutoTuner)
    tuner.disabled_rule_ids = []
    tuner.spec_by_id = {}
    tuner._get_runtime_module_config = lambda module: {"enabled": True} if module == "cognitive_stitching" else {}
    tuner.param_bounds = {
        "cognitive_stitching.event_grasp_min_total_energy": auto_tuner.ParamBound(0.05, 0.60, 0.03, quantum=0.005),
    }
    tuner.metric_targets = {
        "timing_cognitive_stitching_ms": auto_tuner.MetricTarget(
            key="timing_cognitive_stitching_ms",
            expected_min=0.0,
            expected_max=1200.0,
            ideal=180.0,
            min_std=25.0,
        )
    }

    rows = [
        {
            "cs_candidate_raw_accepted_count": 1.0,
            "cs_candidate_count": 1.0,
            "cs_candidate_rejected_low_score_count": 0.0,
            "cs_candidate_rejected_component_limit_count": 0.0,
            "cs_candidate_rejected_non_positive_edge_count": 0.0,
            "cs_candidate_replacement_count": 0.0,
            "cs_candidate_kept_existing_count": 0.0,
            "cs_candidate_threshold_margin_mean": 0.06,
            "cs_action_count": 1.0,
            "cs_created_count": 1.0,
            "cs_extended_count": 0.0,
            "cs_merged_count": 0.0,
            "cs_reinforced_count": 0.0,
            "cs_event_grasp_emitted_count": 0.0,
            "cs_event_grasp_selected_event_count": 1.0,
            "cs_event_grasp_post_action_seed_count": 1.0,
            "cs_event_grasp_post_action_selected_event_count": 1.0,
            "cs_narrative_top_grasp": 0.0,
            "stimulus_new_structure_count": 1.0,
            "timing_cognitive_stitching_ms": 90.0,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._cognitive_stitching_snapshot(tuner, rows=rows)
    updates = auto_tuner.AutoTuner._decide_cognitive_stitching_nudges(tuner, snapshot=snapshot, long_term=False)

    assert any(item["param"] == "cognitive_stitching.event_grasp_min_total_energy" for item in updates)
    assert any(str(item.get("reason", "")).startswith("event_grasp_not_emitting_after_post_action_focus") for item in updates)


def test_cognitive_stitching_event_grasp_gate_respects_mature_narrative_zone():
    tuner = auto_tuner.AutoTuner.__new__(auto_tuner.AutoTuner)
    tuner.disabled_rule_ids = []
    tuner.spec_by_id = {}
    tuner._get_runtime_module_config = lambda module: {"enabled": True} if module == "cognitive_stitching" else {}
    tuner.param_bounds = {
        "cognitive_stitching.event_grasp_min_total_energy": auto_tuner.ParamBound(0.05, 0.60, 0.03, quantum=0.005),
    }
    tuner.metric_targets = {
        "timing_cognitive_stitching_ms": auto_tuner.MetricTarget(
            key="timing_cognitive_stitching_ms",
            expected_min=0.0,
            expected_max=1200.0,
            ideal=180.0,
            min_std=25.0,
        )
    }

    rows = [
        {
            "cs_candidate_raw_accepted_count": 1.0,
            "cs_candidate_count": 1.0,
            "cs_candidate_rejected_low_score_count": 0.0,
            "cs_candidate_rejected_component_limit_count": 0.0,
            "cs_candidate_rejected_non_positive_edge_count": 0.0,
            "cs_candidate_replacement_count": 0.0,
            "cs_candidate_kept_existing_count": 0.0,
            "cs_candidate_threshold_margin_mean": 0.06,
            "cs_action_count": 1.0,
            "cs_created_count": 1.0,
            "cs_extended_count": 0.0,
            "cs_merged_count": 0.0,
            "cs_reinforced_count": 0.0,
            "cs_event_grasp_emitted_count": 0.0,
            "cs_event_grasp_selected_event_count": 1.0,
            "cs_event_grasp_post_action_seed_count": 1.0,
            "cs_event_grasp_post_action_selected_event_count": 1.0,
            "cs_narrative_top_grasp": 0.0,
            "cs_narrative_grasp_max": 0.24,
            "cs_narrative_grasp_positive_count": 2.0,
            "stimulus_new_structure_count": 1.0,
            "timing_cognitive_stitching_ms": 90.0,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._cognitive_stitching_snapshot(tuner, rows=rows)
    updates = auto_tuner.AutoTuner._decide_cognitive_stitching_nudges(tuner, snapshot=snapshot, long_term=False)

    assert not any(item["param"] == "cognitive_stitching.event_grasp_min_total_energy" for item in updates)


def test_cognitive_stitching_open_gate_does_not_overreact_when_narrative_zone_alive():
    tuner = auto_tuner.AutoTuner.__new__(auto_tuner.AutoTuner)
    tuner.disabled_rule_ids = []
    tuner.spec_by_id = {}
    tuner._get_runtime_module_config = lambda module: {"enabled": True} if module == "cognitive_stitching" else {}
    tuner.param_bounds = {
        "cognitive_stitching.min_candidate_score": auto_tuner.ParamBound(0.05, 0.60, 0.03, quantum=0.005),
        "cognitive_stitching.min_seed_total_energy": auto_tuner.ParamBound(0.10, 0.90, 0.04, quantum=0.005),
        "cognitive_stitching.min_event_total_energy": auto_tuner.ParamBound(0.03, 0.40, 0.02, quantum=0.005),
        "cognitive_stitching.event_grasp_min_total_energy": auto_tuner.ParamBound(0.05, 0.60, 0.03, quantum=0.005),
    }
    tuner.metric_targets = {
        "timing_cognitive_stitching_ms": auto_tuner.MetricTarget(
            key="timing_cognitive_stitching_ms",
            expected_min=0.0,
            expected_max=1200.0,
            ideal=180.0,
            min_std=25.0,
        )
    }

    rows = [
        {
            "cs_candidate_raw_accepted_count": 0.0,
            "cs_candidate_count": 2.0,
            "cs_candidate_rejected_low_score_count": 0.0,
            "cs_candidate_rejected_component_limit_count": 0.0,
            "cs_candidate_rejected_non_positive_edge_count": 0.0,
            "cs_candidate_replacement_count": 0.0,
            "cs_candidate_kept_existing_count": 0.0,
            "cs_candidate_threshold_margin_mean": 0.05,
            "cs_action_count": 0.0,
            "cs_created_count": 0.0,
            "cs_extended_count": 0.0,
            "cs_merged_count": 0.0,
            "cs_reinforced_count": 0.0,
            "cs_event_grasp_emitted_count": 0.0,
            "cs_event_grasp_selected_event_count": 0.0,
            "cs_event_grasp_post_action_seed_count": 0.0,
            "cs_event_grasp_post_action_selected_event_count": 0.0,
            "cs_narrative_top_grasp": 0.0,
            "cs_narrative_grasp_max": 0.18,
            "cs_narrative_grasp_positive_count": 2.0,
            "stimulus_new_structure_count": 1.0,
            "timing_cognitive_stitching_ms": 80.0,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._cognitive_stitching_snapshot(tuner, rows=rows)
    updates = auto_tuner.AutoTuner._decide_cognitive_stitching_nudges(tuner, snapshot=snapshot, long_term=False)
    params = {item["param"] for item in updates}

    assert "cognitive_stitching.min_candidate_score" not in params
    assert "cognitive_stitching.min_seed_total_energy" not in params
    assert "cognitive_stitching.min_event_total_energy" not in params
    assert "cognitive_stitching.event_grasp_min_total_energy" not in params


def test_structure_supply_prefers_retention_when_runtime_resolution_supply_is_thin():
    tuner = auto_tuner.AutoTuner.__new__(auto_tuner.AutoTuner)
    tuner.disabled_rule_ids = []
    tuner.spec_by_id = {}
    tuner.runtime_params = {"hdb.internal_resolution_max_structures_per_tick": 5.0}
    tuner.persisted_params = {}
    tuner.param_bounds = {
        "hdb.internal_resolution_max_structures_per_tick": auto_tuner.ParamBound(3.0, 12.0, 1.0, quantum=1.0),
        "state_pool.default_er_decay_ratio": auto_tuner.ParamBound(0.93, 0.99, 0.005, quantum=0.001),
        "state_pool.default_ev_decay_ratio": auto_tuner.ParamBound(0.94, 0.995, 0.005, quantum=0.001),
        "attention.max_cam_items": auto_tuner.ParamBound(4.0, 32.0, 2.0, quantum=1.0),
    }
    tuner.metric_targets = {
        "internal_sa_count": auto_tuner.MetricTarget("internal_sa_count", 64.0, 260.0, 140.0, min_std=8.0),
        "internal_to_external_sa_ratio": auto_tuner.MetricTarget("internal_to_external_sa_ratio", 1.25, 6.0, 2.2, min_std=0.08),
        "internal_resolution_structure_count_selected": auto_tuner.MetricTarget("internal_resolution_structure_count_selected", 3.0, 12.0, 5.0, min_std=0.4),
    }

    rows = [
        {
            "internal_sa_count": 20.0,
            "internal_to_external_sa_ratio": 0.5,
            "internal_resolution_structure_count_selected": 1.0,
            "external_sa_count": 60.0,
            "internal_resolution_raw_unit_count": 14.0,
            "internal_resolution_selected_unit_count": 14.0,
            "internal_resolution_detail_budget": 80.0,
            "cam_item_count": 4.0,
            "pool_active_item_count": 70.0,
            "pool_runtime_resolution_degraded_item_count": 0.0,
            "pool_runtime_resolution_active_component_count": 1.0,
            "pool_runtime_resolution_dropped_component_count": 8.0,
            "hdb_residual_diff_entry_ratio": 0.08,
        }
        for _ in range(4)
    ]

    balance = auto_tuner.AutoTuner._endogenous_balance_snapshot(tuner, rows=rows)
    updates = auto_tuner.AutoTuner._decide_structure_supply_nudges(tuner, balance=balance, long_term=False)
    params = {item["param"] for item in updates}

    assert balance["source_supply_thin"] is True
    assert "hdb.internal_resolution_max_structures_per_tick" not in params
    assert "state_pool.default_er_decay_ratio" in params
    assert "state_pool.default_ev_decay_ratio" in params


def test_attention_special_selection_nudges_penalize_bare_special_nodes_and_raise_fatigue():
    tuner = auto_tuner.AutoTuner.__new__(auto_tuner.AutoTuner)
    tuner.disabled_rule_ids = []
    tuner.spec_by_id = {}
    tuner.param_bounds = {
        "attention.reward_action_special_standalone_penalty": auto_tuner.ParamBound(0.40, 1.40, 0.08, quantum=0.01),
        "attention.reward_action_special_standalone_energy_gain": auto_tuner.ParamBound(0.05, 0.40, 0.03, quantum=0.01),
        "attention.attention_repeat_fatigue_special_multiplier": auto_tuner.ParamBound(1.00, 3.20, 0.12, quantum=0.01),
        "attention.attention_repeat_fatigue_selected_gain": auto_tuner.ParamBound(0.40, 2.20, 0.10, quantum=0.01),
        "attention.attention_repeat_fatigue_penalty_gain": auto_tuner.ParamBound(0.10, 1.20, 0.06, quantum=0.01),
        "attention.attention_repeat_fatigue_max_penalty": auto_tuner.ParamBound(0.40, 3.20, 0.12, quantum=0.01),
    }

    rows = [
        {
            "attention_standalone_special_selected_count": 1.4,
            "attention_structure_carrier_selected_count": 0.4,
            "attention_repeat_penalty_total": 0.3,
            "attention_reward_action_selected_count": 2.0,
            "cam_item_count": 5.0,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._attention_special_selection_snapshot(tuner, rows=rows)
    updates = auto_tuner.AutoTuner._decide_attention_special_selection_nudges(tuner, snapshot=snapshot, long_term=False)
    params = {item["param"] for item in updates}

    assert snapshot["standalone_hot"] is True
    assert snapshot["repeat_penalty_weak"] is True
    assert "attention.reward_action_special_standalone_penalty" in params
    assert "attention.reward_action_special_standalone_energy_gain" in params
    assert "attention.attention_repeat_fatigue_special_multiplier" in params
    assert "attention.attention_repeat_fatigue_selected_gain" in params
    assert "attention.attention_repeat_fatigue_penalty_gain" in params


def test_attention_special_selection_nudges_boost_structure_carriers_when_too_thin():
    tuner = auto_tuner.AutoTuner.__new__(auto_tuner.AutoTuner)
    tuner.disabled_rule_ids = []
    tuner.spec_by_id = {}
    tuner.param_bounds = {
        "attention.reward_action_structure_carrier_bonus": auto_tuner.ParamBound(0.20, 1.10, 0.06, quantum=0.01),
        "attention.reward_action_structure_carrier_context_gain": auto_tuner.ParamBound(0.05, 0.55, 0.03, quantum=0.01),
        "attention.reward_action_structure_carrier_value_gain": auto_tuner.ParamBound(0.05, 0.45, 0.03, quantum=0.01),
    }

    rows = [
        {
            "attention_standalone_special_selected_count": 0.2,
            "attention_structure_carrier_selected_count": 0.3,
            "attention_repeat_penalty_total": 0.8,
            "attention_reward_action_selected_count": 1.8,
            "cam_item_count": 5.0,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._attention_special_selection_snapshot(tuner, rows=rows)
    updates = auto_tuner.AutoTuner._decide_attention_special_selection_nudges(tuner, snapshot=snapshot, long_term=False)
    params = {item["param"] for item in updates}

    assert snapshot["carrier_thin"] is True
    assert "attention.reward_action_structure_carrier_bonus" in params
    assert "attention.reward_action_structure_carrier_context_gain" in params
    assert "attention.reward_action_structure_carrier_value_gain" in params


def test_catalog_nudges_no_longer_directly_tune_internal_external_ratio():
    tuner = auto_tuner.AutoTuner.__new__(auto_tuner.AutoTuner)
    tuner.disabled_rule_ids = []
    tuner.spec_by_id = {}
    tuner.catalog_specs = [
        param_catalog.ParamSpec(
            param_id="hdb.stimulus_level_max_rounds",
            source_kind="module_config",
            module="hdb",
            path_tokens=["stimulus_level_max_rounds"],
            value=12.0,
            value_type="int",
            auto_tune_allowed=True,
            tags=["budget"],
            impacts=["internal_to_external_sa_ratio"],
            note="legacy generic impact",
        )
    ]
    tuner.param_bounds = {
        "hdb.stimulus_level_max_rounds": auto_tuner.ParamBound(4.0, 20.0, 1.0, quantum=1.0),
    }
    tuner.metric_targets = {
        "internal_to_external_sa_ratio": auto_tuner.MetricTarget("internal_to_external_sa_ratio", 1.25, 12.0, 4.0, min_std=0.08, weight=0.35),
    }

    rows = [
        {"internal_to_external_sa_ratio": 42.0, "external_sa_count": 0.0},
        {"internal_to_external_sa_ratio": 37.0, "external_sa_count": 0.0},
        {"internal_to_external_sa_ratio": 51.0, "external_sa_count": 1.0},
        {"internal_to_external_sa_ratio": 48.0, "external_sa_count": 0.0},
    ]

    updates = auto_tuner.AutoTuner._decide_catalog_nudges(tuner, recent=rows, long_term=False)

    assert updates == []


def test_catalog_nudges_do_not_dual_control_dedicated_endogenous_metrics():
    tuner = auto_tuner.AutoTuner.__new__(auto_tuner.AutoTuner)
    tuner.disabled_rule_ids = []
    tuner.spec_by_id = {}
    tuner.catalog_specs = [
        param_catalog.ParamSpec(
            param_id="state_pool.soft_capacity_start_items",
            source_kind="module_config",
            module="state_pool",
            path_tokens=["soft_capacity_start_items"],
            value=96.0,
            value_type="int",
            auto_tune_allowed=True,
            tags=["capacity"],
            impacts=["internal_sa_count"],
            note="legacy generic impact",
        ),
        param_catalog.ParamSpec(
            param_id="hdb.top_n_attention_stub_default",
            source_kind="module_config",
            module="hdb",
            path_tokens=["top_n_attention_stub_default"],
            value=4.0,
            value_type="int",
            auto_tune_allowed=True,
            tags=["budget"],
            impacts=["internal_resolution_structure_count_selected"],
            note="legacy generic impact",
        ),
        param_catalog.ParamSpec(
            param_id="hdb.internal_resolution_flat_unit_cap_per_structure",
            source_kind="module_config",
            module="hdb",
            path_tokens=["internal_resolution_flat_unit_cap_per_structure"],
            value=48.0,
            value_type="int",
            auto_tune_allowed=True,
            tags=["performance", "budget"],
            impacts=["internal_resolution_raw_unit_count"],
            note="legacy generic impact",
        ),
    ]
    tuner.param_bounds = {
        "state_pool.soft_capacity_start_items": auto_tuner.ParamBound(24.0, 240.0, 8.0, quantum=1.0),
        "hdb.top_n_attention_stub_default": auto_tuner.ParamBound(1.0, 16.0, 1.0, quantum=1.0),
        "hdb.internal_resolution_flat_unit_cap_per_structure": auto_tuner.ParamBound(8.0, 128.0, 8.0, quantum=1.0),
    }
    tuner.metric_targets = {
        "internal_sa_count": auto_tuner.MetricTarget("internal_sa_count", 64.0, 260.0, 140.0, min_std=8.0, weight=1.0),
        "internal_resolution_structure_count_selected": auto_tuner.MetricTarget(
            "internal_resolution_structure_count_selected", 3.0, 12.0, 5.0, min_std=0.4, weight=0.9
        ),
        "internal_resolution_raw_unit_count": auto_tuner.MetricTarget(
            "internal_resolution_raw_unit_count", 0.0, 350.0, 160.0, min_std=10.0, weight=1.0
        ),
    }

    rows = [
        {
            "internal_sa_count": 12.0,
            "internal_resolution_structure_count_selected": 1.0,
            "internal_resolution_raw_unit_count": 520.0,
        },
        {
            "internal_sa_count": 14.0,
            "internal_resolution_structure_count_selected": 1.0,
            "internal_resolution_raw_unit_count": 505.0,
        },
        {
            "internal_sa_count": 16.0,
            "internal_resolution_structure_count_selected": 2.0,
            "internal_resolution_raw_unit_count": 498.0,
        },
        {
            "internal_sa_count": 13.0,
            "internal_resolution_structure_count_selected": 1.0,
            "internal_resolution_raw_unit_count": 530.0,
        },
    ]

    updates = auto_tuner.AutoTuner._decide_catalog_nudges(tuner, recent=rows, long_term=False)

    assert updates == []


def test_catalog_nudges_treat_global_timing_and_merged_tokens_as_diagnostic_only():
    tuner = auto_tuner.AutoTuner.__new__(auto_tuner.AutoTuner)
    tuner.disabled_rule_ids = []
    tuner.spec_by_id = {}
    tuner.catalog_specs = [
        param_catalog.ParamSpec(
            param_id="emotion.nt_channels.COR.soft_cap_k",
            source_kind="module_config",
            module="emotion",
            path_tokens=["nt_channels", "COR", "soft_cap_k"],
            value=0.8,
            value_type="float",
            auto_tune_allowed=True,
            tags=["emotion", "performance"],
            impacts=["timing_total_logic_ms"],
            note="legacy generic impact",
        ),
        param_catalog.ParamSpec(
            param_id="text_sensor.max_text_length",
            source_kind="module_config",
            module="text_sensor",
            path_tokens=["max_text_length"],
            value=512.0,
            value_type="int",
            auto_tune_allowed=True,
            tags=["text_sensor", "performance"],
            impacts=["merged_flat_token_count"],
            note="legacy generic impact",
        ),
    ]
    tuner.param_bounds = {
        "emotion.nt_channels.COR.soft_cap_k": auto_tuner.ParamBound(0.1, 2.0, 0.1, quantum=0.01),
        "text_sensor.max_text_length": auto_tuner.ParamBound(64.0, 2048.0, 64.0, quantum=1.0),
    }
    tuner.metric_targets = {
        "timing_total_logic_ms": auto_tuner.MetricTarget("timing_total_logic_ms", 0.0, 8000.0, 4500.0, min_std=200.0, weight=1.0),
        "merged_flat_token_count": auto_tuner.MetricTarget("merged_flat_token_count", 0.0, 240.0, 140.0, min_std=8.0, weight=0.9),
    }

    rows = [
        {"timing_total_logic_ms": 13200.0, "merged_flat_token_count": 410.0},
        {"timing_total_logic_ms": 12800.0, "merged_flat_token_count": 396.0},
        {"timing_total_logic_ms": 13640.0, "merged_flat_token_count": 428.0},
        {"timing_total_logic_ms": 13120.0, "merged_flat_token_count": 402.0},
    ]

    updates = auto_tuner.AutoTuner._decide_catalog_nudges(tuner, recent=rows, long_term=False)

    assert updates == []


def _make_ev_balance_tuner():
    tuner = auto_tuner.AutoTuner.__new__(auto_tuner.AutoTuner)
    tuner.disabled_rule_ids = []
    tuner.spec_by_id = {}
    tuner.catalog_specs = []
    tuner.param_bounds = {
        "hdb.er_induction_ratio": auto_tuner.ParamBound(0.40, 1.00, 0.04, quantum=0.01),
        "hdb.ev_propagation_ratio": auto_tuner.ParamBound(0.15, 1.00, 0.05, quantum=0.01),
        "hdb.ev_propagation_threshold": auto_tuner.ParamBound(0.03, 0.40, 0.03, quantum=0.005),
        "hdb.induction_raw_residual_structure_share": auto_tuner.ParamBound(0.30, 1.00, 0.08, quantum=0.01),
        "observatory.memory_feedback_stimulus_packet_structure_projection_ratio": auto_tuner.ParamBound(0.15, 0.90, 0.05, quantum=0.01),
        "observatory.memory_feedback_structure_projection_max_targets": auto_tuner.ParamBound(2.0, 12.0, 2.0, quantum=1.0),
        "observatory.induction_source_max_items": auto_tuner.ParamBound(4.0, 24.0, 2.0, quantum=1.0),
        "state_pool.default_ev_decay_ratio": auto_tuner.ParamBound(0.94, 0.995, 0.005, quantum=0.001),
        "state_pool.default_er_decay_ratio": auto_tuner.ParamBound(0.93, 0.99, 0.005, quantum=0.001),
    }
    tuner.metric_targets = {
        "pool_total_er": auto_tuner.MetricTarget("pool_total_er", 60.0, 260.0, 130.0, min_std=3.0, weight=0.7),
        "pool_total_ev": auto_tuner.MetricTarget("pool_total_ev", 60.0, 320.0, 150.0, min_std=3.0, weight=0.95),
        "pool_ev_to_er_ratio": auto_tuner.MetricTarget("pool_ev_to_er_ratio", 1.02, 1.30, 1.10, min_std=0.04, weight=0.9),
    }
    return tuner


def test_default_metric_targets_include_pool_ev_to_er_ratio():
    targets = {item.key: item for item in auto_tuner._default_metric_targets()}
    target = targets["pool_ev_to_er_ratio"]

    assert target.expected_min == 1.02
    assert target.expected_max == 1.30
    assert target.ideal == 1.10
    assert target.weight == 0.0


def test_param_catalog_exposes_pool_ev_to_er_ratio_definition():
    definitions = {item["key"]: item for item in param_catalog.list_metric_definitions()}
    item = definitions["pool_ev_to_er_ratio"]

    assert item["group"] == "能量传播（诊断）"
    assert item["expected_min"] == 1.02
    assert "诊断" in item["description"]


def test_build_param_catalog_exposes_emotion_ev_balance_param_specs():
    specs = {item.param_id: item for item in param_catalog.build_param_catalog()}

    for key in [
        "emotion.modulation.hdb.scales.ev_propagation_ratio.base",
        "emotion.modulation.hdb.scales.er_induction_ratio.base",
        "emotion.modulation.hdb.scales.ev_propagation_threshold.base",
    ]:
        assert key in specs
        assert specs[key].module == "emotion"
        assert specs[key].auto_tune_allowed is True


def test_param_catalog_exposes_memory_feedback_split_metric_definitions():
    definitions = {item["key"]: item for item in param_catalog.list_metric_definitions()}

    assert definitions["memory_feedback_packet_total_ev"]["group"] == "记忆回响"
    assert "整包回放" in definitions["memory_feedback_packet_total_ev"]["description"]
    assert definitions["memory_feedback_structure_projection_total_ev"]["group"] == "记忆回响"
    assert "结构引用" in definitions["memory_feedback_structure_projection_total_ev"]["description"]


def test_param_catalog_exposes_induction_source_selection_metric_definitions():
    definitions = {item["key"]: item for item in param_catalog.list_metric_definitions()}

    assert definitions["induction_source_available_st_count"]["group"] == "能量传播"
    assert (
        "可供挑选" in definitions["induction_source_available_st_count"]["description"]
        or "参与源" in definitions["induction_source_available_st_count"]["description"]
    )
    assert definitions["induction_source_available_with_local_target_hint_count"]["group"] == "能量传播"
    assert "确实带着本地可用目标" in definitions["induction_source_available_with_local_target_hint_count"]["description"]
    assert definitions["induction_source_selected_from_ev_count"]["group"] == "能量传播"
    assert (
        "EV 排序通道" in definitions["induction_source_selected_from_ev_count"]["description"]
        or "正 EV" in definitions["induction_source_selected_from_ev_count"]["description"]
    )
    assert definitions["induction_source_selected_zero_local_target_hint_count"]["group"] == "能量传播"
    assert "白占名额" in definitions["induction_source_selected_zero_local_target_hint_count"]["description"]
    assert definitions["induction_source_selection_cap_hit"]["group"] == "能量传播"
    assert "名额已经用满" in definitions["induction_source_selection_cap_hit"]["description"]
    assert definitions["induction_raw_residual_entry_with_existing_structure_count"]["group"] == "能量传播"
    assert "canonical signature" in definitions["induction_raw_residual_entry_with_existing_structure_count"]["description"]
    assert definitions["induction_raw_residual_structure_target_total_ev"]["group"] == "能量传播"
    assert "续写到了已有结构" in definitions["induction_raw_residual_structure_target_total_ev"]["description"]


def test_param_catalog_exposes_induction_energy_graph_v2_metric_definitions():
    definitions = {item["key"]: item for item in param_catalog.list_metric_definitions()}

    assert definitions["induction_propagated_budget_total_ev"]["group"] == "能量传播"
    assert "所有前沿传播步骤" in definitions["induction_propagated_budget_total_ev"]["description"]
    assert definitions["induction_energy_graph_round_count_max"]["group"] == "能量传播"
    assert "最大轮数" in definitions["induction_energy_graph_round_count_max"]["title"]
    assert definitions["induction_energy_graph_root_reinduction_count"]["group"] == "能量传播"
    assert "再次用剩余 ER" in definitions["induction_energy_graph_root_reinduction_count"]["description"]
    assert definitions["induction_energy_graph_round_delta_ev_last"]["group"] == "能量传播"
    assert "最后一轮" in definitions["induction_energy_graph_round_delta_ev_last"]["description"]


def test_param_catalog_exposes_new_diagnostic_metric_definitions():
    definitions = {item["key"]: item for item in param_catalog.list_metric_definitions()}

    assert definitions["induction_raw_residual_entry_materialized_structure_count"]["diagnostic_only"] is True
    assert definitions["induction_raw_residual_materialized_structure_target_count"]["diagnostic_only"] is True
    assert definitions["induction_raw_residual_materialized_structure_budget_weight"]["diagnostic_only"] is True
    assert definitions["hdb_primary_pointer_count"]["diagnostic_only"] is True
    assert definitions["hdb_fallback_pointer_count"]["diagnostic_only"] is True
    assert definitions["hdb_signature_index_count"]["diagnostic_only"] is True
    assert definitions["hdb_recent_cache_count"]["diagnostic_only"] is True
    assert definitions["hdb_exact_lookup_cache_count"]["diagnostic_only"] is True
    assert definitions["hdb_numeric_bucket_family_count"]["diagnostic_only"] is True
    assert definitions["hdb_numeric_bucket_count"]["diagnostic_only"] is True


def test_default_param_bounds_include_memory_feedback_structure_projection_ratio():
    bounds = auto_tuner._default_param_bounds()
    bound = bounds["observatory.memory_feedback_stimulus_packet_structure_projection_ratio"]

    assert bound.min_value == 0.15
    assert bound.max_value == 0.90
    assert bound.max_step_abs == 0.05


def test_default_param_bounds_include_memory_feedback_structure_projection_target_cap():
    bounds = auto_tuner._default_param_bounds()
    bound = bounds["observatory.memory_feedback_structure_projection_max_targets"]

    assert bound.min_value == 2.0
    assert bound.max_value == 12.0
    assert bound.max_step_abs == 2.0


def test_default_param_bounds_include_induction_source_selection_knobs():
    bounds = auto_tuner._default_param_bounds()

    assert bounds["hdb.ev_propagation_ratio"].min_value == 0.45
    assert bounds["hdb.ev_propagation_ratio"].max_value == 1.10
    assert bounds["hdb.er_induction_ratio"].min_value == 0.55
    assert bounds["hdb.er_induction_ratio"].max_value == 1.00
    assert bounds["hdb.ev_propagation_threshold"].min_value == 0.04
    assert bounds["hdb.ev_propagation_threshold"].max_value == 0.24
    assert bounds["observatory.induction_source_max_items"].min_value == 4.0
    assert bounds["observatory.induction_source_max_items"].max_value == 24.0
    assert bounds["observatory.induction_source_candidate_top_k"].min_value == 8.0
    assert bounds["observatory.induction_source_candidate_top_k"].max_value == 48.0
    assert bounds["observatory.induction_source_ev_quota_ratio"].min_value == 0.20
    assert bounds["observatory.induction_source_ev_quota_ratio"].max_value == 0.80
    assert bounds["hdb.induction_raw_residual_structure_share"].min_value == 0.85
    assert bounds["hdb.induction_raw_residual_structure_share"].max_value == 1.00
    assert bounds["hdb.induction_raw_residual_structure_target_top_k"].max_value == 3.0
    assert bounds["time_sensor.memory_top_k"].min_value == 4.0
    assert bounds["time_sensor.memory_top_k"].max_value == 24.0
    assert bounds["time_sensor.projection_target_keep_ratio"].min_value == 0.45
    assert bounds["time_sensor.projection_target_keep_ratio"].max_value == 0.90
    assert bounds["time_sensor.max_projection_bind_targets_per_memory"].min_value == 1.0
    assert bounds["time_sensor.max_projection_bind_targets_per_memory"].max_value == 4.0
    assert bounds["emotion.modulation.hdb.scales.ev_propagation_ratio.base"].min_value == 0.55
    assert bounds["emotion.modulation.hdb.scales.ev_propagation_ratio.base"].max_value == 1.45


def test_build_param_catalog_exposes_observatory_induction_source_param_impacts():
    specs = {item.param_id: item for item in param_catalog.build_param_catalog()}

    max_items = specs["observatory.induction_source_max_items"]
    candidate_top_k = specs["observatory.induction_source_candidate_top_k"]
    ev_quota = specs["observatory.induction_source_ev_quota_ratio"]
    raw_residual_share = specs["hdb.induction_raw_residual_structure_share"]

    assert "induction_source_selected_from_ev_count" in max_items.impacts
    assert "induction_source_selection_cap_hit" in max_items.impacts
    assert "induction_source_selected_with_local_target_hint_count" in max_items.impacts
    assert "induction_source_selected_from_er_count" in candidate_top_k.impacts
    assert "induction_source_available_st_count" in candidate_top_k.impacts
    assert "induction_source_selected_zero_local_target_hint_count" in candidate_top_k.impacts
    assert "pool_ev_to_er_ratio" in ev_quota.impacts
    assert "induction_source_selected_from_ev_count" in ev_quota.impacts
    assert "induction_raw_residual_entry_with_existing_structure_count" in raw_residual_share.impacts
    assert "induction_raw_residual_structure_target_total_ev" in raw_residual_share.impacts
    assert "induction_raw_residual_entry_materialized_structure_count" in raw_residual_share.impacts
    assert "induction_raw_residual_materialized_structure_target_count" in raw_residual_share.impacts
    assert "induction_raw_residual_materialized_structure_budget_weight" in raw_residual_share.impacts


def test_build_param_catalog_exposes_time_projection_and_nt_focus_impacts():
    specs = {item.param_id: item for item in param_catalog.build_param_catalog()}

    projection_keep = specs["time_sensor.projection_target_keep_ratio"]
    projection_top_k = specs["time_sensor.max_projection_bind_targets_per_memory"]
    nov_base = specs["emotion.nt_channels.NOV.base"]
    foc_base = specs["emotion.nt_channels.FOC.base"]

    assert "time_sensor_projection_binding_count" in projection_keep.impacts
    assert "time_sensor_delayed_task_executed_count" in projection_keep.impacts
    assert "time_sensor_projection_binding_count" in projection_top_k.impacts
    assert "nt_NOV" in nov_base.impacts
    assert "attention_mod_priority_weight_recency_gain" in nov_base.impacts
    assert "nt_FOC" in foc_base.impacts
    assert "attention_mod_focus_boost_weight" in foc_base.impacts
    assert "attention_mod_min_total_energy" in foc_base.impacts


def test_param_catalog_guess_bounds_align_new_time_sensor_and_nt_ranges():
    specs = {item.param_id: item for item in param_catalog.build_param_catalog()}
    bounds = param_catalog.build_default_param_bounds(specs.values())

    assert bounds["time_sensor.memory_top_k"].min_value == 4.0
    assert bounds["time_sensor.memory_top_k"].max_value == 24.0
    assert bounds["time_sensor.max_projection_bind_targets_per_memory"].min_value == 1.0
    assert bounds["time_sensor.max_projection_bind_targets_per_memory"].max_value == 4.0
    assert bounds["time_sensor.projection_target_keep_ratio"].min_value == 0.45
    assert bounds["time_sensor.projection_target_keep_ratio"].max_value == 0.90
    assert bounds["emotion.nt_channels.DA.base"].max_value == 0.35
    assert bounds["emotion.nt_channels.NOV.soft_cap_k"].min_value == 0.18
    assert bounds["emotion.nt_channels.NOV.soft_cap_k"].max_value == 0.60
    assert bounds["emotion.nt_channels.FOC.decay_ratio"].min_value == 0.80
    assert bounds["emotion.nt_channels.FOC.decay_ratio"].max_value == 0.97
    assert bounds["emotion.rwd_pun_to_nt_gains.rwd.DA"].min_value == -0.18
    assert bounds["emotion.rwd_pun_to_nt_gains.pun.NOV"].max_value == 0.28


def test_build_param_catalog_exposes_induction_energy_graph_v2_param_impacts():
    specs = {item.param_id: item for item in param_catalog.build_param_catalog()}

    max_rounds = specs["hdb.induction_energy_graph_v2_max_rounds"]
    frontier_ratio = specs["hdb.induction_energy_graph_v2_frontier_ev_ratio"]
    target_top_k = specs["hdb.induction_energy_graph_v2_target_top_k"]

    assert "induction_energy_graph_round_count_max" in max_rounds.impacts
    assert "induction_energy_graph_depth_max" in max_rounds.impacts
    assert "induction_energy_graph_root_reinduction_count" in max_rounds.impacts
    assert "induction_propagated_budget_total_ev" in frontier_ratio.impacts
    assert "induction_energy_graph_frontier_budget_total_ev" in frontier_ratio.impacts
    assert "induction_energy_graph_round_delta_ev_total" in frontier_ratio.impacts
    assert "induction_energy_graph_frontier_generated_count" in target_top_k.impacts
    assert "induction_energy_graph_layer_total_nodes" in target_top_k.impacts
    assert "induction_energy_graph_frontier_pruned_count" in target_top_k.impacts


def test_canonicalize_param_id_maps_legacy_emotion_ev_aliases():
    tuner = auto_tuner.AutoTuner.__new__(auto_tuner.AutoTuner)
    tuner.param_bounds = {
        "emotion.modulation.hdb.scales.ev_propagation_ratio.base": auto_tuner.ParamBound(0.20, 1.00, 0.05, quantum=0.01),
        "emotion.modulation.hdb.scales.er_induction_ratio.base": auto_tuner.ParamBound(0.20, 1.00, 0.05, quantum=0.01),
        "emotion.modulation.hdb.scales.ev_propagation_threshold.base": auto_tuner.ParamBound(0.60, 1.20, 0.05, quantum=0.01),
    }
    tuner.spec_by_id = {}

    assert tuner._canonicalize_param_id("emotion.subjective_modulators.ev_propagation_ratio.base") == "emotion.modulation.hdb.scales.ev_propagation_ratio.base"
    assert tuner._canonicalize_param_id("emotion.subjective_modulators.er_induction_ratio.base") == "emotion.modulation.hdb.scales.er_induction_ratio.base"
    assert tuner._canonicalize_param_id("emotion.subjective_modulators.ev_propagation_threshold.base") == "emotion.modulation.hdb.scales.ev_propagation_threshold.base"


def test_ev_balance_prefers_propagation_knob_when_local_residual_chain_is_thin():
    tuner = _make_ev_balance_tuner()
    rows = [
        {
            "pool_total_er": 120.0,
            "pool_total_ev": 66.0,
            "pool_ev_to_er_ratio": 0.55,
            "induction_total_delta_ev": 5.0,
            "induction_total_ev_consumed": 4.0,
            "induction_propagated_ev_total": 0.4,
            "induction_ev_from_er_total": 4.6,
            "induction_propagated_target_ratio": 0.10,
            "induction_ev_from_er_ratio": 0.92,
            "induction_source_item_count": 4.0,
            "induction_target_count": 8.0,
            "induction_propagated_target_count": 1.0,
            "induction_induced_target_count": 7.0,
            "induction_targets_per_source_mean": 2.0,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._ev_balance_snapshot(tuner, rows=rows)
    updates = auto_tuner.AutoTuner._decide_ev_balance_nudges(tuner, snapshot=snapshot, long_term=False)
    params = {item["param"] for item in updates}

    assert snapshot["propagation_chain_weak"] is True
    assert snapshot["induction_chain_weak"] is False
    assert snapshot["retention_chain_weak"] is False
    assert "hdb.ev_propagation_ratio" in params
    assert "hdb.er_induction_ratio" not in params
    assert "state_pool.default_ev_decay_ratio" not in params


def test_ev_balance_stops_raising_propagation_ratio_after_runtime_saturation():
    tuner = _make_ev_balance_tuner()
    rows = [
        {
            "pool_total_er": 120.0,
            "pool_total_ev": 18.0,
            "pool_ev_to_er_ratio": 0.15,
            "induction_total_delta_ev": 5.0,
            "induction_total_ev_consumed": 4.0,
            "induction_propagated_ev_total": 0.4,
            "induction_ev_from_er_total": 4.6,
            "induction_propagated_target_ratio": 0.10,
            "induction_ev_from_er_ratio": 0.92,
            "induction_source_item_count": 4.0,
            "induction_target_count": 8.0,
            "induction_propagated_target_count": 1.0,
            "induction_induced_target_count": 7.0,
            "induction_targets_per_source_mean": 2.0,
            "hdb_requested_ev_propagation_ratio": 1.4,
            "hdb_effective_ev_propagation_ratio": 1.0,
            "hdb_ev_propagation_ratio_clamped": 1.0,
            "hdb_requested_er_induction_ratio": 0.55,
            "hdb_effective_er_induction_ratio": 0.55,
            "hdb_er_induction_ratio_clamped": 0.0,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._ev_balance_snapshot(tuner, rows=rows)
    updates = auto_tuner.AutoTuner._decide_ev_balance_nudges(tuner, snapshot=snapshot, long_term=False)
    params = {item["param"] for item in updates}

    assert snapshot["propagation_chain_weak"] is True
    assert snapshot["propagation_ratio_saturated"] is True
    assert "hdb.ev_propagation_ratio" not in params
    assert "state_pool.default_ev_decay_ratio" in params


def test_ev_balance_prefers_induction_knob_when_er_to_ev_conversion_is_thin():
    tuner = _make_ev_balance_tuner()
    rows = [
        {
            "pool_total_er": 130.0,
            "pool_total_ev": 78.0,
            "pool_ev_to_er_ratio": 0.60,
            "induction_total_delta_ev": 4.0,
            "induction_total_ev_consumed": 3.4,
            "induction_propagated_ev_total": 3.2,
            "induction_ev_from_er_total": 0.2,
            "induction_propagated_target_ratio": 0.78,
            "induction_ev_from_er_ratio": 0.05,
            "induction_source_item_count": 5.0,
            "induction_target_count": 10.0,
            "induction_propagated_target_count": 8.0,
            "induction_induced_target_count": 2.0,
            "induction_targets_per_source_mean": 2.0,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._ev_balance_snapshot(tuner, rows=rows)
    updates = auto_tuner.AutoTuner._decide_ev_balance_nudges(tuner, snapshot=snapshot, long_term=False)
    params = {item["param"] for item in updates}

    assert snapshot["propagation_chain_weak"] is False
    assert snapshot["induction_chain_weak"] is True
    assert snapshot["retention_chain_weak"] is False
    assert "hdb.er_induction_ratio" in params
    assert "hdb.ev_propagation_ratio" not in params
    assert "state_pool.default_ev_decay_ratio" not in params


def test_ev_balance_prefers_retention_when_both_chain_shares_are_alive_but_ev_still_thin():
    tuner = _make_ev_balance_tuner()
    rows = [
        {
            "pool_total_er": 118.0,
            "pool_total_ev": 106.0,
            "pool_ev_to_er_ratio": 0.90,
            "induction_total_delta_ev": 6.0,
            "induction_total_ev_consumed": 4.2,
            "induction_propagated_ev_total": 4.0,
            "induction_ev_from_er_total": 2.0,
            "induction_propagated_target_ratio": 0.68,
            "induction_ev_from_er_ratio": 0.33,
            "induction_source_item_count": 5.0,
            "induction_target_count": 9.0,
            "induction_propagated_target_count": 6.0,
            "induction_induced_target_count": 3.0,
            "induction_targets_per_source_mean": 1.8,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._ev_balance_snapshot(tuner, rows=rows)
    updates = auto_tuner.AutoTuner._decide_ev_balance_nudges(tuner, snapshot=snapshot, long_term=False)
    params = {item["param"] for item in updates}

    assert snapshot["propagation_chain_weak"] is False
    assert snapshot["induction_chain_weak"] is False
    assert snapshot["retention_chain_weak"] is True
    assert "state_pool.default_ev_decay_ratio" in params
    assert "hdb.ev_propagation_ratio" not in params
    assert "hdb.er_induction_ratio" not in params


def test_ev_balance_prefers_retention_first_when_induction_supply_itself_is_missing():
    tuner = _make_ev_balance_tuner()
    rows = [
        {
            "pool_total_er": 96.0,
            "pool_total_ev": 60.0,
            "pool_ev_to_er_ratio": 0.625,
            "induction_total_delta_ev": 0.2,
            "induction_total_ev_consumed": 0.0,
            "induction_propagated_ev_total": 0.0,
            "induction_ev_from_er_total": 0.2,
            "induction_propagated_target_ratio": 0.0,
            "induction_ev_from_er_ratio": 1.0,
            "induction_source_item_count": 0.0,
            "induction_target_count": 0.0,
            "induction_propagated_target_count": 0.0,
            "induction_induced_target_count": 0.0,
            "induction_targets_per_source_mean": 0.0,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._ev_balance_snapshot(tuner, rows=rows)
    updates = auto_tuner.AutoTuner._decide_ev_balance_nudges(tuner, snapshot=snapshot, long_term=False)
    params = {item["param"] for item in updates}

    assert snapshot["source_supply_thin"] is True
    assert snapshot["retention_chain_weak"] is True
    assert "state_pool.default_ev_decay_ratio" in params
    assert "hdb.ev_propagation_ratio" not in params
    assert "hdb.er_induction_ratio" not in params


def test_ev_balance_can_lower_propagation_threshold_when_source_items_exist_but_targets_are_too_sparse():
    tuner = _make_ev_balance_tuner()
    rows = [
        {
            "pool_total_er": 132.0,
            "pool_total_ev": 62.0,
            "pool_ev_to_er_ratio": 0.47,
            "induction_total_delta_ev": 1.4,
            "induction_total_ev_consumed": 0.1,
            "induction_propagated_ev_total": 0.1,
            "induction_ev_from_er_total": 1.3,
            "induction_propagated_target_ratio": 0.12,
            "induction_ev_from_er_ratio": 0.93,
            "induction_source_item_count": 8.0,
            "induction_target_count": 1.0,
            "induction_propagated_target_count": 1.0,
            "induction_induced_target_count": 0.0,
            "induction_targets_per_source_mean": 0.12,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._ev_balance_snapshot(tuner, rows=rows)
    updates = auto_tuner.AutoTuner._decide_ev_balance_nudges(tuner, snapshot=snapshot, long_term=False)
    params = {item["param"] for item in updates}

    assert snapshot["ev_starved"] is True
    assert snapshot["mean_source_items"] >= 3.0
    assert snapshot["mean_target_count"] < 1.8
    assert snapshot["mean_targets_per_source"] < 0.30
    assert "hdb.ev_propagation_threshold" in params


def test_ev_balance_can_raise_memory_feedback_structure_projection_when_packet_replay_dominates():
    tuner = _make_ev_balance_tuner()
    rows = [
        {
            "pool_total_er": 122.0,
            "pool_total_ev": 78.0,
            "pool_ev_to_er_ratio": 0.64,
            "induction_total_delta_ev": 4.2,
            "induction_total_ev_consumed": 2.1,
            "induction_propagated_ev_total": 2.0,
            "induction_ev_from_er_total": 2.2,
            "induction_propagated_target_ratio": 0.58,
            "induction_ev_from_er_ratio": 0.52,
            "induction_source_item_count": 5.0,
            "induction_target_count": 9.0,
            "induction_propagated_target_count": 5.0,
            "induction_induced_target_count": 4.0,
            "induction_targets_per_source_mean": 1.8,
            "memory_feedback_total_ev": 2.6,
            "memory_feedback_packet_count": 2.0,
            "memory_feedback_packet_total_ev": 2.2,
            "memory_feedback_structure_projection_count": 1.0,
            "memory_feedback_structure_projection_total_ev": 0.4,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._ev_balance_snapshot(tuner, rows=rows)
    updates = auto_tuner.AutoTuner._decide_ev_balance_nudges(tuner, snapshot=snapshot, long_term=False)
    params = {item["param"] for item in updates}

    assert snapshot["memory_feedback_packet_dominant"] is True
    assert snapshot["memory_feedback_structure_projection_share"] < 0.24
    assert "observatory.memory_feedback_stimulus_packet_structure_projection_ratio" in params


def test_ev_balance_memory_feedback_nudges_are_suppressed_when_memory_feedback_tuning_disabled():
    tuner = _make_ev_balance_tuner()
    tuner.cfg = SimpleNamespace(enable_memory_feedback_tuning=False)
    rows = [
        {
            "pool_total_er": 122.0,
            "pool_total_ev": 78.0,
            "pool_ev_to_er_ratio": 0.64,
            "induction_total_delta_ev": 4.2,
            "induction_total_ev_consumed": 2.1,
            "induction_propagated_ev_total": 2.0,
            "induction_ev_from_er_total": 2.2,
            "induction_propagated_target_ratio": 0.58,
            "induction_ev_from_er_ratio": 0.52,
            "induction_source_item_count": 5.0,
            "induction_target_count": 9.0,
            "induction_propagated_target_count": 5.0,
            "induction_induced_target_count": 4.0,
            "induction_targets_per_source_mean": 1.8,
            "memory_feedback_total_ev": 2.6,
            "memory_feedback_packet_count": 2.0,
            "memory_feedback_packet_total_ev": 2.2,
            "memory_feedback_structure_projection_count": 1.0,
            "memory_feedback_structure_projection_total_ev": 0.4,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._ev_balance_snapshot(tuner, rows=rows)
    updates = auto_tuner.AutoTuner._decide_ev_balance_nudges(tuner, snapshot=snapshot, long_term=False)
    params = {item["param"] for item in updates}

    assert snapshot["memory_feedback_packet_dominant"] is True
    assert "observatory.memory_feedback_stimulus_packet_structure_projection_ratio" not in params
    assert "observatory.memory_feedback_structure_projection_max_targets" not in params


def test_ev_balance_can_raise_raw_residual_structure_share_when_existing_hits_are_present_but_structure_path_is_underused():
    tuner = _make_ev_balance_tuner()
    rows = [
        {
            "pool_total_er": 140.0,
            "pool_total_ev": 12.0,
            "pool_ev_to_er_ratio": 0.08571429,
            "induction_total_delta_ev": 5.2,
            "induction_total_ev_consumed": 2.4,
            "induction_propagated_ev_total": 2.4,
            "induction_ev_from_er_total": 2.8,
            "induction_propagated_target_ratio": 0.54,
            "induction_ev_from_er_ratio": 0.46,
            "induction_source_item_count": 8.0,
            "induction_target_count": 10.0,
            "induction_propagated_target_count": 5.0,
            "induction_induced_target_count": 5.0,
            "induction_targets_per_source_mean": 1.25,
            "induction_raw_residual_entry_count": 10.0,
            "induction_raw_residual_entry_with_existing_structure_count": 2.5,
            "induction_raw_residual_entry_routed_to_structure_count": 2.5,
            "induction_raw_residual_structure_target_total_ev": 0.18,
            "induction_raw_residual_hit_memory_target_total_ev": 0.82,
            "induction_raw_residual_miss_memory_target_total_ev": 2.38,
            "induction_raw_residual_memory_target_total_ev": 3.2,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._ev_balance_snapshot(tuner, rows=rows)
    updates = auto_tuner.AutoTuner._decide_ev_balance_nudges(tuner, snapshot=snapshot, long_term=False)
    params = {item["param"] for item in updates}

    assert snapshot["raw_residual_structure_path_underused"] is True
    assert snapshot["raw_residual_hit_structure_share"] < 0.42
    assert "hdb.induction_raw_residual_structure_share" in params


def test_ev_balance_does_not_raise_raw_residual_structure_share_when_only_miss_memory_is_high():
    tuner = _make_ev_balance_tuner()
    rows = [
        {
            "pool_total_er": 140.0,
            "pool_total_ev": 12.0,
            "pool_ev_to_er_ratio": 0.08571429,
            "induction_total_delta_ev": 5.2,
            "induction_total_ev_consumed": 2.4,
            "induction_propagated_ev_total": 2.4,
            "induction_ev_from_er_total": 2.8,
            "induction_propagated_target_ratio": 0.54,
            "induction_ev_from_er_ratio": 0.46,
            "induction_source_item_count": 8.0,
            "induction_target_count": 10.0,
            "induction_propagated_target_count": 5.0,
            "induction_induced_target_count": 5.0,
            "induction_targets_per_source_mean": 1.25,
            "induction_raw_residual_entry_count": 10.0,
            "induction_raw_residual_entry_with_existing_structure_count": 2.5,
            "induction_raw_residual_entry_routed_to_structure_count": 2.5,
            "induction_raw_residual_structure_target_total_ev": 0.60,
            "induction_raw_residual_hit_memory_target_total_ev": 0.40,
            "induction_raw_residual_miss_memory_target_total_ev": 3.00,
            "induction_raw_residual_memory_target_total_ev": 3.40,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._ev_balance_snapshot(tuner, rows=rows)
    updates = auto_tuner.AutoTuner._decide_ev_balance_nudges(tuner, snapshot=snapshot, long_term=False)
    params = {item["param"] for item in updates}

    assert snapshot["raw_residual_hit_structure_share"] == 0.6
    assert snapshot["raw_residual_structure_path_underused"] is False
    assert "hdb.induction_raw_residual_structure_share" not in params


def test_ev_balance_can_tighten_memory_feedback_structure_target_cap_when_projection_is_diluted():
    tuner = _make_ev_balance_tuner()
    rows = [
        {
            "pool_total_er": 132.0,
            "pool_total_ev": 8.4,
            "pool_ev_to_er_ratio": 0.06363636,
            "induction_total_delta_ev": 4.8,
            "induction_total_ev_consumed": 2.0,
            "induction_propagated_ev_total": 1.9,
            "induction_ev_from_er_total": 2.9,
            "induction_propagated_target_ratio": 0.52,
            "induction_ev_from_er_ratio": 0.60,
            "induction_source_item_count": 5.0,
            "induction_target_count": 8.0,
            "induction_propagated_target_count": 4.0,
            "induction_induced_target_count": 4.0,
            "induction_targets_per_source_mean": 1.6,
            "memory_feedback_total_ev": 4.8,
            "memory_feedback_packet_count": 2.0,
            "memory_feedback_packet_total_ev": 2.2,
            "memory_feedback_structure_projection_attempted_count": 38.0,
            "memory_feedback_structure_projection_skipped_count": 27.0,
            "memory_feedback_structure_projection_count": 11.0,
            "memory_feedback_structure_projection_effective_ratio": round(11.0 / 38.0, 8),
            "memory_feedback_structure_projection_total_ev": 1.9,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._ev_balance_snapshot(tuner, rows=rows)
    updates = auto_tuner.AutoTuner._decide_ev_balance_nudges(tuner, snapshot=snapshot, long_term=False)
    params = {item["param"] for item in updates}

    assert snapshot["memory_feedback_projection_diluted"] is True
    assert snapshot["mean_memory_feedback_structure_projection_attempted_count"] == 38.0
    assert snapshot["mean_memory_feedback_structure_projection_skipped_count"] == 27.0
    assert "observatory.memory_feedback_structure_projection_max_targets" in params


def test_catalog_does_not_dual_control_memory_feedback_packet_split_metric():
    tuner = auto_tuner.AutoTuner.__new__(auto_tuner.AutoTuner)
    tuner.disabled_rule_ids = []
    tuner.metric_targets = {
        "memory_feedback_packet_total_ev": auto_tuner.MetricTarget(
            "memory_feedback_packet_total_ev",
            0.0,
            3.0,
            1.8,
            min_std=0.2,
            weight=0.2,
        )
    }
    tuner.catalog_specs = [
        SimpleNamespace(
            param_id="observatory.memory_feedback_stimulus_packet_structure_projection_ratio",
            impacts=["memory_feedback_packet_total_ev"],
            tags=["ratio"],
            module="observatory",
            auto_tune_allowed=True,
        )
    ]
    tuner.param_bounds = {
        "observatory.memory_feedback_stimulus_packet_structure_projection_ratio": auto_tuner.ParamBound(
            0.15, 0.90, 0.05, quantum=0.01
        )
    }

    rows = [{"memory_feedback_packet_total_ev": 5.6} for _ in range(6)]
    updates = auto_tuner.AutoTuner._decide_catalog_nudges(tuner, recent=rows, long_term=False)

    assert not any(
        item.get("param") == "observatory.memory_feedback_stimulus_packet_structure_projection_ratio"
        for item in updates
    )


def test_ev_balance_can_raise_induction_source_span_when_source_cap_is_always_hit():
    tuner = _make_ev_balance_tuner()
    rows = [
        {
            "pool_total_er": 150.0,
            "pool_total_ev": 12.0,
            "pool_ev_to_er_ratio": 0.08,
            "induction_total_delta_ev": 0.6,
            "induction_total_ev_consumed": 0.0,
            "induction_propagated_ev_total": 0.0,
            "induction_ev_from_er_total": 0.6,
            "induction_propagated_target_ratio": 0.0,
            "induction_ev_from_er_ratio": 1.0,
            "induction_source_item_count": 8.0,
            "induction_source_available_st_count": 18.0,
            "induction_source_max_items": 8.0,
            "induction_source_selection_cap_hit": 1.0,
            "induction_target_count": 1.0,
            "induction_propagated_target_count": 0.0,
            "induction_induced_target_count": 1.0,
            "induction_targets_per_source_mean": 0.125,
            "memory_feedback_total_ev": 0.4,
            "memory_feedback_packet_count": 0.0,
            "memory_feedback_packet_total_ev": 0.0,
            "memory_feedback_structure_projection_count": 1.0,
            "memory_feedback_structure_projection_total_ev": 0.4,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._ev_balance_snapshot(tuner, rows=rows)
    updates = auto_tuner.AutoTuner._decide_ev_balance_nudges(tuner, snapshot=snapshot, long_term=False)
    params = {item["param"] for item in updates}

    assert snapshot["source_cap_reached"] is True
    assert "observatory.induction_source_max_items" in params


def test_ev_balance_does_not_treat_memory_heavy_induction_split_as_projection_blocked():
    tuner = _make_ev_balance_tuner()
    rows = [
        {
            "pool_total_er": 150.0,
            "pool_total_ev": 12.0,
            "pool_ev_to_er_ratio": 0.08,
            "induction_total_delta_ev": 6.0,
            "induction_total_ev_consumed": 0.8,
            "induction_propagated_ev_total": 0.8,
            "induction_ev_from_er_total": 5.2,
            "induction_propagated_target_ratio": 0.20,
            "induction_ev_from_er_ratio": 0.86666667,
            "induction_source_item_count": 10.0,
            "induction_source_available_st_count": 18.0,
            "induction_source_max_items": 10.0,
            "induction_source_selection_cap_hit": 1.0,
            "induction_target_count": 10.0,
            "induction_structure_target_count": 2.0,
            "induction_memory_target_count": 8.0,
            "induction_propagated_target_count": 2.0,
            "induction_induced_target_count": 8.0,
            "induction_targets_per_source_mean": 1.0,
            "induction_structure_target_total_ev": 1.2,
            "induction_memory_target_total_ev": 4.8,
            "induction_applied_target_count": 2.0,
            "induction_skipped_target_count": 0.0,
            "induction_skipped_cs_event_target_count": 0.0,
            "induction_applied_total_ev": 0.9,
            "induction_skipped_target_total_ev": 0.0,
            "induction_applied_ev_ratio": 0.75,
            "induction_applied_target_ratio": 1.0,
            "memory_feedback_total_ev": 1.2,
            "memory_feedback_packet_count": 1.0,
            "memory_feedback_packet_total_ev": 0.4,
            "memory_feedback_structure_projection_count": 1.0,
            "memory_feedback_structure_projection_total_ev": 0.8,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._ev_balance_snapshot(tuner, rows=rows)

    assert snapshot["projection_blocked"] is False
    assert round(snapshot["mean_structure_target_ev_share"], 8) == 0.2
    assert snapshot["mean_applied_ev_ratio"] == 0.75


def test_ev_balance_still_marks_projection_blocked_when_structure_share_is_real_and_apply_ratio_is_low():
    tuner = _make_ev_balance_tuner()
    rows = [
        {
            "pool_total_er": 150.0,
            "pool_total_ev": 14.0,
            "pool_ev_to_er_ratio": 0.09333333,
            "induction_total_delta_ev": 6.0,
            "induction_total_ev_consumed": 1.2,
            "induction_propagated_ev_total": 1.2,
            "induction_ev_from_er_total": 4.8,
            "induction_propagated_target_ratio": 0.50,
            "induction_ev_from_er_ratio": 0.8,
            "induction_source_item_count": 8.0,
            "induction_source_available_st_count": 12.0,
            "induction_source_max_items": 8.0,
            "induction_source_selection_cap_hit": 0.0,
            "induction_target_count": 8.0,
            "induction_structure_target_count": 7.0,
            "induction_memory_target_count": 1.0,
            "induction_propagated_target_count": 4.0,
            "induction_induced_target_count": 4.0,
            "induction_targets_per_source_mean": 1.0,
            "induction_structure_target_total_ev": 5.2,
            "induction_memory_target_total_ev": 0.8,
            "induction_applied_target_count": 2.0,
            "induction_skipped_target_count": 0.0,
            "induction_skipped_cs_event_target_count": 0.0,
            "induction_applied_total_ev": 1.1,
            "induction_skipped_target_total_ev": 0.0,
            "induction_applied_ev_ratio": round(1.1 / 5.2, 8),
            "induction_applied_target_ratio": round(2.0 / 7.0, 8),
            "memory_feedback_total_ev": 1.0,
            "memory_feedback_packet_count": 1.0,
            "memory_feedback_packet_total_ev": 0.3,
            "memory_feedback_structure_projection_count": 1.0,
            "memory_feedback_structure_projection_total_ev": 0.7,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._ev_balance_snapshot(tuner, rows=rows)

    assert snapshot["projection_blocked"] is True
    assert snapshot["mean_structure_target_ev_share"] > 0.8
    assert snapshot["mean_applied_ev_ratio"] < 0.25


def test_catalog_nudges_do_not_dual_control_pool_ev_to_er_ratio():
    tuner = auto_tuner.AutoTuner.__new__(auto_tuner.AutoTuner)
    tuner.disabled_rule_ids = []
    tuner.spec_by_id = {}
    tuner.catalog_specs = [
        param_catalog.ParamSpec(
            param_id="hdb.ev_propagation_ratio",
            source_kind="module_config",
            module="hdb",
            path_tokens=["ev_propagation_ratio"],
            value=0.55,
            value_type="float",
            auto_tune_allowed=True,
            tags=["hdb", "energy"],
            impacts=["pool_ev_to_er_ratio"],
            note="dedicated energy control metric",
        )
    ]
    tuner.param_bounds = {
        "hdb.ev_propagation_ratio": auto_tuner.ParamBound(0.15, 1.00, 0.05, quantum=0.01),
    }
    tuner.metric_targets = {
        "pool_ev_to_er_ratio": auto_tuner.MetricTarget("pool_ev_to_er_ratio", 1.02, 1.30, 1.10, min_std=0.04, weight=0.9),
    }

    rows = [
        {"pool_ev_to_er_ratio": 0.62},
        {"pool_ev_to_er_ratio": 0.64},
        {"pool_ev_to_er_ratio": 0.60},
        {"pool_ev_to_er_ratio": 0.63},
    ]

    updates = auto_tuner.AutoTuner._decide_catalog_nudges(tuner, recent=rows, long_term=False)

    assert updates == []


def test_timing_hotspot_prefers_state_pool_chain_when_cache_and_maintenance_dominate():
    tuner = auto_tuner.AutoTuner.__new__(auto_tuner.AutoTuner)
    tuner.disabled_rule_ids = []
    tuner.spec_by_id = {}
    tuner.runtime_params = {"attention.max_cam_items": 16.0, "time_sensor.delayed_task_capacity": 48.0}
    tuner.param_bounds = {
        "state_pool.soft_capacity_start_items": auto_tuner.ParamBound(80.0, 1200.0, 10.0, quantum=1.0),
        "state_pool.soft_capacity_full_items": auto_tuner.ParamBound(160.0, 2400.0, 10.0, quantum=1.0),
        "state_pool.priority_neutralization_min_effect_threshold": auto_tuner.ParamBound(0.0, 1.0, 0.02, quantum=0.01),
        "state_pool.neutralization_min_effect_threshold": auto_tuner.ParamBound(0.0, 1.0, 0.02, quantum=0.01),
        "hdb.structure_level_max_rounds": auto_tuner.ParamBound(3.0, 10.0, 1.0, quantum=1.0),
        "hdb.stimulus_level_max_rounds": auto_tuner.ParamBound(4.0, 20.0, 1.0, quantum=1.0),
    }
    tuner.metric_targets = {
        "timing_total_logic_ms": auto_tuner.MetricTarget("timing_total_logic_ms", 0.0, 8000.0, 4500.0, min_std=200.0, weight=1.0),
        "timing_structure_level_ms": auto_tuner.MetricTarget("timing_structure_level_ms", 0.0, 1400.0, 450.0, min_std=60.0, weight=0.55),
        "timing_stimulus_level_ms": auto_tuner.MetricTarget("timing_stimulus_level_ms", 0.0, 4200.0, 2200.0, min_std=120.0, weight=0.65),
        "timing_cache_neutralization_ms": auto_tuner.MetricTarget("timing_cache_neutralization_ms", 0.0, 2400.0, 1200.0, min_std=80.0, weight=0.55),
        "timing_maintenance_ms": auto_tuner.MetricTarget("timing_maintenance_ms", 0.0, 900.0, 260.0, min_std=25.0, weight=0.45),
        "internal_resolution_raw_unit_count": auto_tuner.MetricTarget("internal_resolution_raw_unit_count", 0.0, 350.0, 160.0, min_std=10.0, weight=1.0),
        "merged_flat_token_count": auto_tuner.MetricTarget("merged_flat_token_count", 0.0, 240.0, 140.0, min_std=8.0, weight=0.9),
        "pool_active_item_count": auto_tuner.MetricTarget("pool_active_item_count", 40.0, 260.0, 150.0, min_std=0.0, weight=0.75),
        "sensor_echo_pool_size": auto_tuner.MetricTarget("sensor_echo_pool_size", 0.0, 24.0, 6.0, min_std=0.0, weight=0.35),
    }

    rows = [
        {
            "timing_total_logic_ms": 7600.0,
            "timing_structure_level_ms": 120.0,
            "timing_stimulus_level_ms": 1400.0,
            "timing_cache_neutralization_ms": 3050.0,
            "timing_maintenance_ms": 980.0,
            "internal_resolution_raw_unit_count": 180.0,
            "merged_flat_token_count": 220.0,
            "pool_active_item_count": 340.0,
            "cache_residual_flat_token_count": 52.0,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._timing_hotspot_snapshot(tuner, rows=rows)
    updates = auto_tuner.AutoTuner._decide_timing_hotspot_nudges(
        tuner,
        snapshot=snapshot,
        balance={"needs_recovery": False, "source_supply_thin": False},
        long_term=False,
    )
    params = {item["param"] for item in updates}

    assert snapshot["dominant_group_id"] == "state_pool"
    assert "state_pool.soft_capacity_start_items" in params
    assert "state_pool.soft_capacity_full_items" in params
    assert "state_pool.priority_neutralization_min_effect_threshold" in params
    assert "state_pool.neutralization_min_effect_threshold" in params
    assert "hdb.structure_level_max_rounds" not in params
    assert "hdb.stimulus_level_max_rounds" not in params


def test_timing_hotspot_prefers_hdb_round_controls_when_hdb_chain_dominates():
    tuner = auto_tuner.AutoTuner.__new__(auto_tuner.AutoTuner)
    tuner.disabled_rule_ids = []
    tuner.spec_by_id = {}
    tuner.runtime_params = {}
    tuner.param_bounds = {
        "hdb.structure_level_max_rounds": auto_tuner.ParamBound(3.0, 10.0, 1.0, quantum=1.0),
        "hdb.stimulus_level_max_rounds": auto_tuner.ParamBound(4.0, 20.0, 1.0, quantum=1.0),
        "hdb.internal_resolution_flat_unit_cap_per_structure": auto_tuner.ParamBound(128.0, 800.0, 20.0, quantum=1.0),
        "state_pool.soft_capacity_start_items": auto_tuner.ParamBound(80.0, 1200.0, 10.0, quantum=1.0),
    }
    tuner.metric_targets = {
        "timing_total_logic_ms": auto_tuner.MetricTarget("timing_total_logic_ms", 0.0, 8000.0, 4500.0, min_std=200.0, weight=1.0),
        "timing_structure_level_ms": auto_tuner.MetricTarget("timing_structure_level_ms", 0.0, 1400.0, 450.0, min_std=60.0, weight=0.55),
        "timing_stimulus_level_ms": auto_tuner.MetricTarget("timing_stimulus_level_ms", 0.0, 4200.0, 2200.0, min_std=120.0, weight=0.65),
        "timing_cache_neutralization_ms": auto_tuner.MetricTarget("timing_cache_neutralization_ms", 0.0, 2400.0, 1200.0, min_std=80.0, weight=0.55),
        "timing_maintenance_ms": auto_tuner.MetricTarget("timing_maintenance_ms", 0.0, 900.0, 260.0, min_std=25.0, weight=0.45),
        "internal_resolution_raw_unit_count": auto_tuner.MetricTarget("internal_resolution_raw_unit_count", 0.0, 350.0, 160.0, min_std=10.0, weight=1.0),
        "merged_flat_token_count": auto_tuner.MetricTarget("merged_flat_token_count", 0.0, 240.0, 140.0, min_std=8.0, weight=0.9),
        "pool_active_item_count": auto_tuner.MetricTarget("pool_active_item_count", 40.0, 260.0, 150.0, min_std=0.0, weight=0.75),
        "sensor_echo_pool_size": auto_tuner.MetricTarget("sensor_echo_pool_size", 0.0, 24.0, 6.0, min_std=0.0, weight=0.35),
    }

    rows = [
        {
            "timing_total_logic_ms": 7900.0,
            "timing_structure_level_ms": 1820.0,
            "timing_stimulus_level_ms": 4680.0,
            "timing_cache_neutralization_ms": 420.0,
            "timing_maintenance_ms": 140.0,
            "internal_resolution_raw_unit_count": 430.0,
            "merged_flat_token_count": 320.0,
            "pool_active_item_count": 180.0,
            "cache_residual_flat_token_count": 12.0,
        }
        for _ in range(4)
    ]

    snapshot = auto_tuner.AutoTuner._timing_hotspot_snapshot(tuner, rows=rows)
    updates = auto_tuner.AutoTuner._decide_timing_hotspot_nudges(
        tuner,
        snapshot=snapshot,
        balance={"needs_recovery": False, "source_supply_thin": False},
        long_term=False,
    )
    params = {item["param"] for item in updates}

    assert snapshot["dominant_group_id"] == "hdb"
    assert "hdb.structure_level_max_rounds" in params
    assert "hdb.stimulus_level_max_rounds" in params
    assert "hdb.internal_resolution_flat_unit_cap_per_structure" in params
    assert "state_pool.soft_capacity_start_items" not in params


def test_prepare_and_apply_overrides_uses_repo_baseline_even_if_app_rules_path_points_to_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(auto_tuner, "load_auto_tuner_config", lambda: auto_tuner.AutoTunerConfig())
    monkeypatch.setattr(auto_tuner, "_load_raw_config_dict", lambda: {})
    monkeypatch.setattr(auto_tuner, "load_auto_tuner_rules", lambda: auto_tuner._default_rules_payload())
    monkeypatch.setattr(auto_tuner.AutoTuner, "_load_state", lambda self: auto_tuner._default_state_payload())
    monkeypatch.setattr(auto_tuner.AutoTuner, "_ensure_candidate_observations", lambda self: None)
    monkeypatch.setattr(auto_tuner.param_catalog, "build_param_catalog", lambda app=None: [])
    monkeypatch.setattr(auto_tuner.param_catalog, "build_default_param_bounds", lambda specs: {})
    monkeypatch.setattr(auto_tuner, "_overrides_dir", lambda: tmp_path / "overrides")
    monkeypatch.setattr(auto_tuner.AutoTuner, "_get_runtime_module_config", lambda self, module: {})
    monkeypatch.setattr(auto_tuner.AutoTuner, "_reload_module_config", lambda self, module, trace_id, config_path: {"code": "OK"})

    repo_root = tmp_path / "repo"
    innate_dir = repo_root / "innate_script" / "config"
    innate_dir.mkdir(parents=True, exist_ok=True)

    repo_baseline_doc = {
        "rules_schema_version": "1.0",
        "rules_version": "9.9",
        "enabled": True,
        "defaults": {},
        "rules": [
            {
                "id": "repo_truth_rule",
                "title": "repo baseline wins",
                "phase": "directives",
                "enabled": True,
                "priority": 1,
                "cooldown_ticks": 0,
                "when": {"timer": {"at_tick": 1}},
                "then": [{"log": {"message": "repo baseline"}}],
            }
        ],
    }
    stale_runtime_like_doc = {
        "rules_schema_version": "1.0",
        "rules_version": "0.1",
        "enabled": True,
        "defaults": {},
        "rules": [
            {
                "id": "runtime_stale_rule",
                "title": "runtime stale",
                "phase": "directives",
                "enabled": True,
                "priority": 1,
                "cooldown_ticks": 0,
                "when": {"timer": {"at_tick": 2}},
                "then": [{"log": {"message": "runtime stale"}}],
            }
        ],
    }

    baseline_path = innate_dir / "innate_rules.yaml"
    baseline_path.write_text(auto_tuner.io.dump_yaml(repo_baseline_doc).strip() + "\n", encoding="utf-8")
    stale_runtime_like_path = tmp_path / "runtime_like.yaml"
    stale_runtime_like_path.write_text(auto_tuner.io.dump_yaml(stale_runtime_like_doc).strip() + "\n", encoding="utf-8")

    fake_iesm = SimpleNamespace(
        _rules_path=str(stale_runtime_like_path),
        reload_config=lambda trace_id, config_path: {"code": "OK"},
        reload_rules=lambda trace_id: {"code": "OK"},
    )
    fake_app = SimpleNamespace(iesm=fake_iesm)

    monkeypatch.setattr(auto_tuner.storage, "repo_root", lambda: repo_root)

    tuner = auto_tuner.AutoTuner(
        app=fake_app,
        run_dir=tmp_path / "run",
        enabled=True,
        enable_short_term=False,
        enable_long_term=False,
    )

    tuner.prepare_and_apply_overrides(trace_id="pytest_repo_baseline_rules")

    runtime_doc = yaml.safe_load(tuner.runtime_rules_path.read_text(encoding="utf-8"))
    runtime_rule_ids = [str(item.get("id", "")) for item in runtime_doc.get("rules", []) if isinstance(item, dict)]
    assert "repo_truth_rule" in runtime_rule_ids
    assert "runtime_stale_rule" not in runtime_rule_ids
