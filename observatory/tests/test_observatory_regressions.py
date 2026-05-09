# -*- coding: utf-8 -*-

from __future__ import annotations

from observatory._app import ObservatoryApp
from observatory.experiment.metrics import extract_tick_metrics


def _run_observatory_local_action_bias_series(
    *,
    attr_name: str = "",
    attr_value: float = 0.0,
    ticks: int = 12,
    app_config_override: dict | None = None,
) -> dict:
    config_override = {
        "history_limit": 2,
        "export_html": False,
        "export_json": False,
        "drive_decay_ratio": 1.0,
        "action_fatigue_enabled": False,
        "threshold_scale_by_rwd_pun_enabled": False,
        "local_drive_modulation_by_rwd_pun_enabled": True,
    }
    if isinstance(app_config_override, dict):
        config_override.update(app_config_override)
    app = ObservatoryApp(
        config_override=config_override
    )
    try:
        suffix = attr_name or "baseline"
        runtime_structure = {
            "id": f"st_demo_{suffix}",
            "object_type": "st",
            "sub_type": "stimulus_sequence_structure",
            "content": {"raw": "AB", "display": "AB", "normalized": "AB"},
            "energy": {"er": 0.5, "ev": 2.0},
            "structure": {"display_text": "AB", "flat_tokens": ["A", "B"]},
        }
        insert_result = app.pool.insert_runtime_node(runtime_structure, trace_id=f"seed_{suffix}", source_module="pytest")
        assert insert_result["success"] is True
        item_id = insert_result["data"]["item_id"]

        if attr_name:
            attribute_sa = {
                "id": f"sa_{attr_name}_{suffix}",
                "object_type": "sa",
                "content": {
                    "raw": f"{attr_name}:{attr_value}",
                    "display": attr_name,
                    "value_type": "numerical",
                    "attribute_name": attr_name,
                    "attribute_value": attr_value,
                },
                "stimulus": {"role": "attribute", "modality": "internal"},
                "energy": {"er": 0.0, "ev": float(attr_value)},
                "meta": {"ext": {"bound_from": "pytest"}},
            }
            bind_result = app.pool.bind_attribute_node_to_object(
                target_item_id=item_id,
                attribute_sa=attribute_sa,
                trace_id=f"bind_{suffix}",
                source_module="pytest",
                reason=f"pytest_local_bind:{attr_name}",
            )
            assert bind_result["success"] is True

        rows = []
        for item in list(app.pool._store.get_all()):  # type: ignore[attr-defined]
            row = app.pool._snapshot._build_top_item_summary(item)  # type: ignore[attr-defined]
            if isinstance(row, dict):
                rows.append(row)
        local_map = app._build_local_rwd_pun_map_from_pool_items(
            rows,
            trace_id=f"local_map_{suffix}",
            tick_id=f"cycle_local_map_{suffix}",
        )

        series = []
        for tick in range(1, int(ticks) + 1):
            result = app.action.run_action_cycle(
                trace_id=f"trace_{suffix}_{tick}",
                tick_id=f"cycle_{suffix}_{tick:04d}",
                tick_index=tick,
                cfs_signals=[],
                emotion_state={},
                innate_focus_directives=[],
                innate_action_triggers=[
                    {
                        "action_id": f"act_{suffix}",
                        "action_kind": "attention_focus",
                        "gain": 0.4,
                        "threshold": 1.0,
                        "params": {
                            "target_ref_object_id": f"st_demo_{suffix}",
                            "target_ref_object_type": "st",
                            "target_display": "AB",
                        },
                        "rule_id": "rule_probe",
                    }
                ],
                memory_activation_snapshot={},
                local_reward_punish_map=local_map,
            )
            data = result.get("data", {}) or {}
            nodes = data.get("nodes", []) or []
            assert len(nodes) == 1
            node = nodes[0]
            attempted = [
                row
                for row in (data.get("executed_actions", []) or [])
                if row.get("action_id") == f"act_{suffix}" and bool(row.get("attempted", False))
            ]
            series.append(
                {
                    "tick": tick,
                    "lookup_status": str((node.get("local_drive_modulation", {}) or {}).get("lookup_status", "") or ""),
                    "drive": float(node.get("drive", 0.0) or 0.0),
                    "scale_clamped": float((node.get("local_drive_modulation", {}) or {}).get("scale_clamped", 1.0) or 1.0),
                    "attempted_exec": bool(attempted),
                }
            )

        return {
            "rows": rows,
            "local_map": local_map,
            "series": series,
            "attempt_ticks": [int(row["tick"]) for row in series if bool(row["attempted_exec"])],
        }
    finally:
        app.close()


def test_clear_all_resets_cached_reports_and_runtime_state():
    app = ObservatoryApp(
        config_override={
            "history_limit": 4,
            "export_html": False,
            "export_json": False,
        }
    )
    try:
        report = app.run_cycle("你好")
        assert report
        assert app._last_report is not None
        assert app._report_history
        assert app.tick_counter == 1

        app.time_sensor._delayed_tasks["demo"] = {"target_item_id": "spi_demo", "due_tick": 3}
        app.time_sensor._task_fatigue_until_tick["demo"] = 5
        app.action._nodes["act_demo"] = {"action_id": "act_demo"}
        app.action._pending_async_completions.append({"action_id": "act_demo", "due_tick_number": 8})
        app.cognitive_stitching._esdb["cs_event::demo"] = {"event_ref_id": "cs_event::demo"}
        app.attention._total_calls = 7
        app.hdb._structure_retrieval._internal_resolution_cursor["st_demo"] = 2
        app._pending_external_text_chunks = ["旧片段一", "旧片段二"]
        app._current_external_source_text = "旧输入"
        app._pending_focus_directives = [{"directive_id": "focus_demo"}]
        app._last_modulation = {"attention": {"top_n": 9}}
        app._projection_fatigue["demo"] = 0.4

        app.clear_all()

        assert app._last_report is None
        assert app._report_history == []
        assert app.time_sensor._delayed_tasks == {}
        assert app.time_sensor._task_fatigue_until_tick == {}
        assert app.action._nodes == {}
        assert app.action._pending_async_completions == []
        assert app.cognitive_stitching._esdb == {}
        assert app.attention._total_calls == 0
        assert app.hdb._structure_retrieval._internal_resolution_cursor == {}
        assert app._pending_external_text_chunks == []
        assert app._current_external_source_text == ""
        assert app._pending_focus_directives == []
        assert app._last_modulation == {}
        assert app._projection_fatigue == {}
        assert app.tick_counter == 0
        dashboard = app.get_dashboard_data()
        assert dashboard.get("tick_counter") == 0
        assert dashboard.get("meta", {}).get("tick_counter") == 0
        assert dashboard.get("last_report") is None
        assert dashboard.get("recent_cycles") == []
        assert app.pool._tick_counter == 0
        snapshot = app.hdb.get_memory_activation_snapshot(trace_id="after_clear")["data"]
        assert snapshot["summary"]["count"] == 0
    finally:
        app.close()


def test_projection_fatigue_lazy_decay_matches_tick_decay(tmp_path):
    app = ObservatoryApp(
        config_override={
            "history_limit": 1,
            "export_html": False,
            "export_json": False,
            "hdb_enable_background_repair": False,
            "hdb_data_dir": str(tmp_path / "projection_fatigue_hdb"),
            "projection_fatigue_lazy_decay_enabled": True,
            "projection_fatigue_decay": 0.5,
            "projection_fatigue_step": 1.0,
        }
    )
    try:
        item = {
            "projection_kind": "structure",
            "structure_id": "st_lazy_projection",
            "display_text": "lazy projection",
            "er": 4.0,
            "ev": 2.0,
            "reason": "pytest",
        }
        app.tick_counter = 1
        app._mark_projection_fatigue(item)
        app.tick_counter = 3
        effective = app._apply_projection_fatigue_to_item(item)
        assert effective is not None
        assert effective["projection_fatigue"] == 0.25
        assert effective["er"] == 3.2
        assert effective["ev"] == 1.6
    finally:
        app.close()


def test_run_cycle_preserves_fifo_queue_and_reports_submitted_text_separately():
    app = ObservatoryApp(
        config_override={
            "history_limit": 2,
            "export_html": False,
            "export_json": False,
            "input_chunk_soft_limit": 4,
            "input_chunk_hard_limit": 4,
        }
    )
    try:
        first = app.run_cycle("ABCDEFGH")
        assert first.get("sensor", {}).get("input_text") == "ABCD"
        first_queue = first.get("input_queue", {}) or {}
        assert first_queue.get("submitted_text") == "ABCDEFGH"
        assert first_queue.get("tick_text") == "ABCD"
        assert first_queue.get("source_text") == "ABCDEFGH"
        assert app._pending_external_text_chunks == ["EFGH"]

        second = app.run_cycle("XY")
        assert second.get("sensor", {}).get("input_text") == "EFGH"
        input_queue = second.get("input_queue", {}) or {}
        assert input_queue.get("submitted_text") == "XY"
        assert input_queue.get("tick_text") == "EFGH"
        assert input_queue.get("source_text") == "XY"
        assert input_queue.get("pending_count_before_enqueue") == 1
        assert input_queue.get("pending_count_before_dequeue") == 2
        assert input_queue.get("pending_count_after_dequeue") == 1
        assert app._pending_external_text_chunks == ["XY"]

        third = app.run_cycle("")
        assert third.get("sensor", {}).get("input_text") == "XY"
        third_queue = third.get("input_queue", {}) or {}
        assert third_queue.get("submitted_text") == ""
        assert third_queue.get("tick_text") == "XY"
        assert third_queue.get("pending_count_after_dequeue") == 0
    finally:
        app.close()


def test_run_cycle_accepts_empty_text_without_crash():
    app = ObservatoryApp(
        config_override={
            "history_limit": 2,
            "export_html": False,
            "export_json": False,
        }
    )
    try:
        report = app.run_cycle("")
        assert report.get("tick_id")
        sensor = report.get("sensor", {}) or {}
        assert sensor.get("success") is False
        assert sensor.get("code") in {"INPUT_VALIDATION_ERROR", "OK"}
    finally:
        app.close()


def test_run_cycle_rejects_suspect_garbled_text_before_queueing():
    app = ObservatoryApp(
        config_override={
            "history_limit": 2,
            "export_html": False,
            "export_json": False,
        }
    )
    try:
        report = app.run_cycle("????")
        queue = report.get("input_queue", {}) or {}
        sensor = report.get("sensor", {}) or {}
        assert queue.get("submission_status") == "rejected"
        assert queue.get("queued_from_new_input_count") == 0
        assert queue.get("tick_text") == ""
        assert app._pending_external_text_chunks == []
        assert sensor.get("success") is False
        assert sensor.get("code") == "INPUT_TEXT_INTEGRITY_ERROR"
    finally:
        app.close()


def test_run_cycle_report_includes_monotonic_tick_counter():
    app = ObservatoryApp(
        config_override={
            "history_limit": 2,
            "export_html": False,
            "export_json": False,
        }
    )
    try:
        r1 = app.run_cycle("第一轮")
        r2 = app.run_cycle("")
        assert r1.get("tick_counter") == 1
        assert r2.get("tick_counter") == 2
    finally:
        app.close()


def test_action_runtime_snapshot_is_available_after_run_cycle():
    app = ObservatoryApp(
        config_override={
            "history_limit": 2,
            "export_html": False,
            "export_json": False,
        }
    )
    try:
        app.run_cycle("你好")
        snapshot = app.action.get_runtime_snapshot(trace_id="reg_action_runtime")
        assert snapshot.get("success") is True
        data = snapshot.get("data", {}) or {}
        assert isinstance(data.get("nodes", []), list)
        assert "recent_executed_actions" in data
    finally:
        app.close()


def test_observatory_action_config_override_reaches_action_manager():
    app = ObservatoryApp(
        config_override={
            "history_limit": 2,
            "export_html": False,
            "export_json": False,
            "drive_decay_ratio": 1.0,
            "threshold_scale_by_rwd_pun_enabled": False,
            "local_drive_modulation_by_rwd_pun_enabled": False,
        }
    )
    try:
        cfg = getattr(app.action, "_config", {}) or {}
        assert float(cfg.get("drive_decay_ratio", 0.0) or 0.0) == 1.0
        assert bool(cfg.get("threshold_scale_by_rwd_pun_enabled", True)) is False
        assert bool(cfg.get("local_drive_modulation_by_rwd_pun_enabled", True)) is False
    finally:
        app.close()


def test_teacher_feedback_bound_attribute_carries_live_energy():
    app = ObservatoryApp(
        config_override={
            "history_limit": 4,
            "export_html": False,
            "export_json": False,
            "teacher_feedback_attribute_er_scale": 1.0,
            "teacher_feedback_attribute_ev_scale": 0.0,
        }
    )
    try:
        app.run_cycle("ABX")
        report = app.run_cycle(
            "ABX",
            labels={
                "teacher_rwd": 0.9,
                "teacher_anchor": "pool_top1_total",
                "teacher_anchor_ref_object_types": ["st"],
            },
        )
        summary = (((report.get("final_state") or {}).get("state_snapshot") or {}).get("summary") or {})
        bound_totals = summary.get("bound_attribute_energy_totals") or {}
        teacher_reward = bound_totals.get("teacher_reward_signal") or {}
        assert float(teacher_reward.get("total_energy", 0.0) or 0.0) > 0.0
        assert float(teacher_reward.get("total_er", 0.0) or 0.0) >= 0.9
    finally:
        app.close()


def test_pool_bind_attribute_create_if_missing_supports_specific_ref_global_cfs():
    app = ObservatoryApp(
        config_override={
            "history_limit": 2,
            "export_html": False,
            "export_json": False,
        }
    )
    try:
        result = app._apply_innate_pool_effects(
            effects=[
                {
                    "effect_id": "pytest_bind_attr_create_specific_ref",
                    "effect_type": "pool_bind_attribute",
                    "rule_id": "pytest_global_cfs_complexity",
                    "spec": {
                        "selector": {
                            "mode": "specific_ref",
                            "ref_object_id": "st_global_cfs",
                            "ref_object_type": "st",
                        },
                        "create_if_missing": True,
                        "create_ref_object_type": "st",
                        "create_display": "[GlobalCFS]",
                        "attribute": {
                            "attribute_name": "cfs_complexity",
                            "attribute_value": 0.64,
                            "raw": "复杂度:0.64",
                            "display": "复杂度:0.64",
                            "value_type": "numerical",
                            "modality": "internal",
                            "er": 0.64,
                            "ev": 0.0,
                        },
                        "reason": "pytest:global_cfs_complexity",
                    },
                }
            ],
            context={"pool_items": []},
            trace_id="pytest_bind_attr_create_specific_ref",
            tick_id="cycle_0001",
        )
        assert result["skipped_count"] == 0
        assert any(
            str(item.get("op", "")) == "create" and str(item.get("ref_object_id", "")) == "st_global_cfs"
            for item in result.get("applied", [])
        )
        created = app.pool._store.get_by_ref("st_global_cfs")
        assert created is not None

        snapshot = app.pool.get_state_snapshot(
            trace_id="pytest_bind_attr_create_specific_ref_snapshot",
            tick_id="cycle_0001",
            include_history_window=False,
        )["data"]["snapshot"]
        summary = snapshot.get("summary", {}) or {}
        bound_totals = summary.get("bound_attribute_energy_totals") or {}
        complexity = bound_totals.get("cfs_complexity") or {}
        assert float(complexity.get("total_energy", 0.0) or 0.0) > 0.0
        assert float(complexity.get("total_er", 0.0) or 0.0) >= 0.64
    finally:
        app.close()


def test_pool_bind_attribute_skips_zero_value_zero_energy_numeric_attrs_by_default():
    app = ObservatoryApp(
        config_override={
            "history_limit": 2,
            "export_html": False,
            "export_json": False,
        }
    )
    try:
        result = app._apply_innate_pool_effects(
            effects=[
                {
                    "effect_id": "pytest_zero_numeric_attr",
                    "effect_type": "pool_bind_attribute",
                    "rule_id": "pytest_zero_numeric_attr",
                    "spec": {
                        "selector": {
                            "mode": "specific_ref",
                            "ref_object_id": "st_global_cfs",
                            "ref_object_type": "st",
                        },
                        "create_if_missing": True,
                        "create_ref_object_type": "st",
                        "create_display": "[GlobalCFS]",
                        "attribute": {
                            "attribute_name": "cfs_complexity",
                            "attribute_value": 0.0,
                            "raw": "复杂度:0.0",
                            "display": "复杂度:0.0",
                            "value_type": "numerical",
                            "modality": "internal",
                            "er": 0.0,
                            "ev": 0.0,
                        },
                        "reason": "pytest:zero_numeric_attr",
                    },
                }
            ],
            context={"pool_items": []},
            trace_id="pytest_zero_numeric_attr",
            tick_id="cycle_0001",
        )
        assert any(
            str(item.get("reason", "")) == "zero_numeric_attribute"
            for item in result.get("skipped", [])
        )
        assert not any(
            str(item.get("attribute_sa_id", "")).startswith("sa_iesm_attr_cfs_complexity")
            for item in result.get("applied", [])
        )
        assert app.pool._store.get_by_ref("st_global_cfs") is not None

        snapshot = app.pool.get_state_snapshot(
            trace_id="pytest_zero_numeric_attr_snapshot",
            tick_id="cycle_0001",
            include_history_window=False,
        )["data"]["snapshot"]
        bound_totals = (snapshot.get("summary", {}) or {}).get("bound_attribute_energy_totals") or {}
        assert "cfs_complexity" not in bound_totals
    finally:
        app.close()


def test_pool_bind_attribute_zero_numeric_attr_legacy_switch_can_keep_tag():
    app = ObservatoryApp(
        config_override={
            "history_limit": 2,
            "export_html": False,
            "export_json": False,
            "iesm_pool_bind_attribute_drop_zero_numeric_enabled": False,
        }
    )
    try:
        result = app._apply_innate_pool_effects(
            effects=[
                {
                    "effect_id": "pytest_zero_numeric_attr_legacy",
                    "effect_type": "pool_bind_attribute",
                    "rule_id": "pytest_zero_numeric_attr_legacy",
                    "spec": {
                        "selector": {
                            "mode": "specific_ref",
                            "ref_object_id": "st_global_cfs",
                            "ref_object_type": "st",
                        },
                        "create_if_missing": True,
                        "create_ref_object_type": "st",
                        "create_display": "[GlobalCFS]",
                        "attribute": {
                            "attribute_name": "cfs_complexity",
                            "attribute_value": 0.0,
                            "raw": "复杂度:0.0",
                            "display": "复杂度:0.0",
                            "value_type": "numerical",
                            "modality": "internal",
                            "er": 0.0,
                            "ev": 0.0,
                        },
                        "reason": "pytest:zero_numeric_attr_legacy",
                    },
                }
            ],
            context={"pool_items": []},
            trace_id="pytest_zero_numeric_attr_legacy",
            tick_id="cycle_0001",
        )
        assert not any(
            str(item.get("reason", "")) == "zero_numeric_attribute"
            for item in result.get("skipped", [])
        )
        assert any(
            str(item.get("attribute_sa_id", "")).startswith("sa_iesm_attr_cfs_complexity")
            for item in result.get("applied", [])
        )
    finally:
        app.close()


def test_local_reward_punish_map_builds_per_target_feedback():
    app = ObservatoryApp(
        config_override={
            "history_limit": 2,
            "export_html": False,
            "export_json": False,
            "local_drive_modulation_by_rwd_pun_enabled": True,
        }
    )
    try:
        local_map = app._build_local_rwd_pun_map_from_pool_items(
            [
                {
                    "item_id": "spi_demo_reward",
                    "ref_object_id": "st_demo_reward",
                    "ref_alias_ids": ["sa_demo_reward"],
                    "display": "奖励对象",
                    "ev": 0.8,
                    "delta_er": 0.2,
                    "bound_attribute_names": ["reward_signal", "teacher_reward_signal"],
                    "bound_attribute_displays": ["奖励信号:存在", "teacher_reward_signal"],
                },
                {
                    "item_id": "spi_demo_punish",
                    "ref_object_id": "st_demo_punish",
                    "display": "惩罚对象",
                    "ev": 0.6,
                    "delta_er": 0.1,
                    "bound_attribute_names": ["punish_signal"],
                    "bound_attribute_displays": ["惩罚信号:存在"],
                },
            ],
            trace_id="trace_local_map",
            tick_id="cycle_local_map_0001",
        )
        assert local_map["enabled"] is True
        assert local_map["summary"]["mapped_ref_count"] >= 2
        assert local_map["by_ref"]["st_demo_reward"]["rwd"] > 0.0
        assert local_map["by_ref"]["sa_demo_reward"]["rwd"] > 0.0
        assert local_map["by_ref"]["st_demo_reward"]["pun"] == 0.0
        assert local_map["by_ref"]["st_demo_punish"]["pun"] > 0.0
        assert local_map["by_item"]["spi_demo_reward"]["rwd"] > 0.0
    finally:
        app.close()


def test_local_reward_punish_map_weights_runtime_attribute_strength_when_available():
    app = ObservatoryApp(
        config_override={
            "history_limit": 2,
            "export_html": False,
            "export_json": False,
            "local_drive_modulation_by_rwd_pun_enabled": True,
        }
    )
    try:
        local_map = app._build_local_rwd_pun_map_from_pool_items(
            [
                {
                    "item_id": "spi_reward_weak",
                    "ref_object_id": "st_reward_weak",
                    "display": "弱奖励对象",
                    "ev": 0.8,
                    "delta_er": 0.2,
                    "bound_attribute_names": ["reward_signal"],
                    "runtime_bound_attribute_units": [{"attribute_name": "reward_signal", "attribute_value": 0.25}],
                },
                {
                    "item_id": "spi_reward_strong",
                    "ref_object_id": "st_reward_strong",
                    "display": "强奖励对象",
                    "ev": 0.8,
                    "delta_er": 0.2,
                    "bound_attribute_names": ["reward_signal"],
                    "runtime_bound_attribute_units": [{"attribute_name": "reward_signal", "attribute_value": 0.9}],
                },
                {
                    "item_id": "spi_punish_weak",
                    "ref_object_id": "st_punish_weak",
                    "display": "弱惩罚对象",
                    "ev": 0.8,
                    "delta_er": 0.2,
                    "bound_attribute_names": ["punish_signal"],
                    "runtime_bound_attribute_units": [{"attribute_name": "punish_signal", "attribute_value": 0.2}],
                },
                {
                    "item_id": "spi_punish_strong",
                    "ref_object_id": "st_punish_strong",
                    "display": "强惩罚对象",
                    "ev": 0.8,
                    "delta_er": 0.2,
                    "bound_attribute_names": ["punish_signal"],
                    "runtime_bound_attribute_units": [{"attribute_name": "punish_signal", "attribute_value": 0.85}],
                },
            ],
            trace_id="trace_local_map_strength_weight",
            tick_id="cycle_local_map_strength_weight_0001",
        )
        assert local_map["summary"]["attribute_value_weight_enabled"] is True
        assert local_map["by_ref"]["st_reward_strong"]["rwd"] > local_map["by_ref"]["st_reward_weak"]["rwd"] > 0.0
        assert local_map["by_ref"]["st_punish_strong"]["pun"] > local_map["by_ref"]["st_punish_weak"]["pun"] > 0.0
        assert local_map["by_ref"]["st_reward_strong"]["detail"]["reward_attr_strength"] == 0.9
        assert local_map["by_ref"]["st_punish_weak"]["detail"]["punish_attr_strength"] == 0.2
    finally:
        app.close()


def test_local_reward_punish_map_skips_zero_signal_feedback_rows_by_default():
    app = ObservatoryApp(
        config_override={
            "history_limit": 2,
            "export_html": False,
            "export_json": False,
            "local_drive_modulation_by_rwd_pun_enabled": True,
        }
    )
    try:
        local_map = app._build_local_rwd_pun_map_from_pool_items(
            [
                {
                    "item_id": "spi_zero_reward",
                    "ref_object_id": "st_zero_reward",
                    "display": "零奖励对象",
                    "ev": 0.8,
                    "delta_er": 0.0,
                    "bound_attribute_names": ["reward_signal"],
                    "runtime_bound_attribute_units": [{"attribute_name": "reward_signal", "attribute_value": 0.0}],
                }
            ],
            trace_id="trace_local_zero_map",
            tick_id="cycle_local_zero_map_0001",
        )
        assert local_map["summary"]["zero_signal_skipped_count"] == 1
        assert local_map["summary"]["mapped_ref_count"] == 0
        assert "st_zero_reward" not in local_map["by_ref"]
    finally:
        app.close()

    legacy = ObservatoryApp(
        config_override={
            "history_limit": 2,
            "export_html": False,
            "export_json": False,
            "local_drive_modulation_by_rwd_pun_enabled": True,
            "local_drive_feedback_drop_zero_signal_enabled": False,
        }
    )
    try:
        legacy_map = legacy._build_local_rwd_pun_map_from_pool_items(
            [
                {
                    "item_id": "spi_zero_reward",
                    "ref_object_id": "st_zero_reward",
                    "display": "零奖励对象",
                    "ev": 0.8,
                    "delta_er": 0.0,
                    "bound_attribute_names": ["reward_signal"],
                    "runtime_bound_attribute_units": [{"attribute_name": "reward_signal", "attribute_value": 0.0}],
                }
            ],
            trace_id="trace_local_zero_map_legacy",
            tick_id="cycle_local_zero_map_legacy_0001",
        )
        assert legacy_map["summary"]["zero_signal_skipped_count"] == 0
        assert legacy_map["summary"]["mapped_ref_count"] == 1
        assert legacy_map["by_ref"]["st_zero_reward"]["rwd"] == 0.0
        assert legacy_map["by_ref"]["st_zero_reward"]["pun"] == 0.0
    finally:
        legacy.close()


def test_local_reward_punish_map_teacher_feedback_can_override_generic_opposite_bias():
    app = ObservatoryApp(
        config_override={
            "history_limit": 2,
            "export_html": False,
            "export_json": False,
            "local_drive_modulation_by_rwd_pun_enabled": True,
            "local_drive_teacher_feedback_override_enabled": True,
            "local_drive_teacher_feedback_floor_scale": 1.0,
            "local_drive_teacher_feedback_cross_suppress_scale": 0.35,
        }
    )
    try:
        reward_map = app._build_local_rwd_pun_map_from_pool_items(
            [
                {
                    "item_id": "spi_teacher_reward",
                    "ref_object_id": "st_teacher_reward",
                    "display": "教师奖励对象",
                    "ev": 0.0,
                    "delta_er": 0.0,
                    "bound_attribute_names": ["teacher_reward_signal", "punish_signal"],
                    "runtime_bound_attribute_units": [
                        {"attribute_name": "teacher_reward_signal", "attribute_value": 0.6},
                        {"attribute_name": "punish_signal", "attribute_value": 0.95},
                    ],
                }
            ],
            trace_id="trace_teacher_reward_override",
            tick_id="cycle_teacher_reward_override_0001",
        )
        punish_map = app._build_local_rwd_pun_map_from_pool_items(
            [
                {
                    "item_id": "spi_teacher_punish",
                    "ref_object_id": "st_teacher_punish",
                    "display": "教师惩罚对象",
                    "ev": 0.0,
                    "delta_er": 0.0,
                    "bound_attribute_names": ["teacher_punish_signal", "reward_signal"],
                    "runtime_bound_attribute_units": [
                        {"attribute_name": "teacher_punish_signal", "attribute_value": 0.55},
                        {"attribute_name": "reward_signal", "attribute_value": 0.8},
                    ],
                }
            ],
            trace_id="trace_teacher_punish_override",
            tick_id="cycle_teacher_punish_override_0001",
        )

        reward_payload = reward_map["by_ref"]["st_teacher_reward"]
        punish_payload = punish_map["by_ref"]["st_teacher_punish"]

        assert reward_payload["rwd"] >= 0.6
        assert reward_payload["pun"] < 0.95
        assert reward_payload["detail"]["teacher_reward_strength"] == 0.6
        assert reward_payload["detail"]["teacher_punish_strength"] == 0.0

        assert punish_payload["pun"] >= 0.55
        assert punish_payload["rwd"] < 0.8
        assert punish_payload["detail"]["teacher_punish_strength"] == 0.55
        assert punish_payload["detail"]["teacher_reward_strength"] == 0.0
    finally:
        app.close()


def test_teacher_feedback_local_alias_cache_projects_punish_to_next_matching_input():
    app = ObservatoryApp(
        config_override={
            "history_limit": 2,
            "export_html": False,
            "export_json": False,
            "local_drive_modulation_by_rwd_pun_enabled": True,
            "threshold_scale_by_rwd_pun_enabled": False,
            "action_fatigue_enabled": False,
            "teacher_feedback_local_alias_cache_enabled": True,
            "teacher_feedback_local_alias_cache_ttl_ticks": 6,
        }
    )
    try:
        teacher_feedback = {"teacher_rwd": 0.0, "teacher_pun": 0.55}
        created = app._record_teacher_local_feedback_aliases(
            teacher_feedback=teacher_feedback,
            applied_rows=[
                {
                    "success": True,
                    "attribute_name": "teacher_punish_signal",
                    "target_item_id": "spi_teacher_target",
                    "target_ref_object_id": "st_teacher_target",
                    "target_display": "{用户消息 可以帮我查询一下天气吗 teacher_punish_signal:0.55}",
                    "binding_kind": "primary",
                    "binding_scale": 1.0,
                }
            ],
            current_tick=3,
            tick_id="cycle_teacher_feedback_0003",
        )
        assert created["created_count"] == 1

        local_map = {"enabled": True, "by_ref": {}, "by_item": {}, "summary": {}}
        overlay = app._overlay_teacher_local_feedback_alias_cache(
            local_map,
            report={
                "input_queue": {
                    "source_text": "【用户消息】可以帮我查询一下天气吗？",
                    "tick_text": "【用户消息】可以帮我查询一下天气吗？",
                },
                "sensor": {"input_text": "【用户消息】可以帮我查询一下天气吗？"},
            },
            current_tick=4,
            tick_id="cycle_weather_probe_0004",
        )
        assert overlay["overlay_applied_count"] == 1
        assert overlay["overlay_pun"] == 0.55
        assert overlay["overlay_rwd"] == 0.0

        action_result = app.action.run_action_cycle(
            trace_id="trace_teacher_alias_action",
            tick_id="cycle_teacher_alias_action_0004",
            tick_index=4,
            cfs_signals=[],
            emotion_state={},
            innate_focus_directives=[],
            innate_action_triggers=[
                {
                    "action_id": "weather_stub",
                    "action_kind": "weather_stub",
                    "gain": 0.75,
                    "threshold": 2.0,
                    "params": {
                        "target_ref_object_id": "ctx_input_current",
                        "target_ref_object_type": "input",
                        "target_item_id": "ctx_input_current",
                        "target_display": "【用户消息】可以帮我查询一下天气吗？",
                        "disable_threshold_modulation": True,
                    },
                    "rule_id": "rule_weather_probe",
                }
            ],
            memory_activation_snapshot={},
            local_reward_punish_map=local_map,
        )
        nodes = (action_result.get("data", {}) or {}).get("nodes", []) or []
        assert len(nodes) == 1
        local_mod = nodes[0]["local_drive_modulation"]
        assert local_mod["lookup_status"] == "hit"
        assert local_mod["lookup_mode"] == "text_fallback"
        assert local_mod["punish"] == 0.55
        assert local_mod["reward"] == 0.0
        assert local_mod["punish_penalty_gain"] > 0.0
        assert local_mod["detail"]["source"] == "teacher_local_feedback_alias_cache"
    finally:
        app.close()


def test_teacher_feedback_local_alias_cache_prefers_newer_teacher_signal_and_expires():
    app = ObservatoryApp(
        config_override={
            "history_limit": 2,
            "export_html": False,
            "export_json": False,
            "teacher_feedback_local_alias_cache_enabled": True,
            "teacher_feedback_local_alias_cache_ttl_ticks": 4,
        }
    )
    try:
        target_display = "{用户消息 可以帮我查询一下天气吗}"
        app._record_teacher_local_feedback_aliases(
            teacher_feedback={"teacher_rwd": 0.6, "teacher_pun": 0.0},
            applied_rows=[
                {
                    "success": True,
                    "attribute_name": "teacher_reward_signal",
                    "target_item_id": "spi_reward",
                    "target_ref_object_id": "st_reward",
                    "target_display": target_display,
                    "binding_kind": "primary",
                    "binding_scale": 1.0,
                }
            ],
            current_tick=3,
            tick_id="cycle_reward_0003",
        )
        app._record_teacher_local_feedback_aliases(
            teacher_feedback={"teacher_rwd": 0.0, "teacher_pun": 0.55},
            applied_rows=[
                {
                    "success": True,
                    "attribute_name": "teacher_punish_signal",
                    "target_item_id": "spi_punish",
                    "target_ref_object_id": "st_punish",
                    "target_display": target_display,
                    "binding_kind": "primary",
                    "binding_scale": 1.0,
                }
            ],
            current_tick=5,
            tick_id="cycle_punish_0005",
        )

        local_map = {"enabled": True, "by_ref": {}, "by_item": {}, "summary": {}}
        overlay = app._overlay_teacher_local_feedback_alias_cache(
            local_map,
            report={"input_queue": {"source_text": "【用户消息】可以帮我查询一下天气吗？"}},
            current_tick=6,
            tick_id="cycle_probe_0006",
        )
        assert overlay["overlay_applied_count"] == 1
        assert overlay["overlay_pun"] == 0.55
        assert overlay["overlay_rwd"] == 0.0

        expired_map = {"enabled": True, "by_ref": {}, "by_item": {}, "summary": {}}
        expired = app._overlay_teacher_local_feedback_alias_cache(
            expired_map,
            report={"input_queue": {"source_text": "【用户消息】可以帮我查询一下天气吗？"}},
            current_tick=10,
            tick_id="cycle_probe_0010",
        )
        assert expired["overlay_applied_count"] == 0
        assert expired["active_count"] == 0
    finally:
        app.close()


def test_global_reward_punish_estimate_weights_runtime_attribute_strength_when_available():
    app = ObservatoryApp(
        config_override={
            "history_limit": 2,
            "export_html": False,
            "export_json": False,
        }
    )
    try:
        weak = app._estimate_rwd_pun_from_pool_items(
            [
                {
                    "item_id": "spi_reward_weak",
                    "ref_object_id": "st_reward_weak",
                    "display": "弱奖励对象",
                    "ev": 0.8,
                    "delta_er": 0.2,
                    "bound_attribute_names": ["reward_signal"],
                    "runtime_bound_attribute_units": [{"attribute_name": "reward_signal", "attribute_value": 0.2}],
                },
                {
                    "item_id": "spi_punish_weak",
                    "ref_object_id": "st_punish_weak",
                    "display": "弱惩罚对象",
                    "ev": 0.8,
                    "delta_er": 0.2,
                    "bound_attribute_names": ["punish_signal"],
                    "runtime_bound_attribute_units": [{"attribute_name": "punish_signal", "attribute_value": 0.2}],
                },
            ],
            trace_id="trace_global_rwd_pun_weak",
            tick_id="cycle_global_rwd_pun_weak_0001",
        )
        strong = app._estimate_rwd_pun_from_pool_items(
            [
                {
                    "item_id": "spi_reward_strong",
                    "ref_object_id": "st_reward_strong",
                    "display": "强奖励对象",
                    "ev": 0.8,
                    "delta_er": 0.2,
                    "bound_attribute_names": ["reward_signal"],
                    "runtime_bound_attribute_units": [{"attribute_name": "reward_signal", "attribute_value": 0.9}],
                },
                {
                    "item_id": "spi_punish_strong",
                    "ref_object_id": "st_punish_strong",
                    "display": "强惩罚对象",
                    "ev": 0.8,
                    "delta_er": 0.2,
                    "bound_attribute_names": ["punish_signal"],
                    "runtime_bound_attribute_units": [{"attribute_name": "punish_signal", "attribute_value": 0.9}],
                },
            ],
            trace_id="trace_global_rwd_pun_strong",
            tick_id="cycle_global_rwd_pun_strong_0001",
        )
        assert float(strong["rwd"]) > float(weak["rwd"]) > 0.0
        assert float(strong["pun"]) > float(weak["pun"]) > 0.0
        assert strong["detail"]["attribute_value_weight_enabled"] is True
    finally:
        app.close()


def test_observatory_local_reward_punish_can_be_disabled_via_app_override():
    baseline = _run_observatory_local_action_bias_series(attr_name="", attr_value=0.0, ticks=12)
    probe = _run_observatory_local_action_bias_series(
        attr_name="reward_signal",
        attr_value=1.0,
        app_config_override={
            "local_drive_modulation_by_rwd_pun_enabled": False,
        },
    )

    assert probe["attempt_ticks"] == baseline["attempt_ticks"]
    assert all(row["lookup_status"] == "skipped" for row in probe["series"])
    assert all(abs(float(row["scale_clamped"]) - 1.0) < 1e-9 for row in probe["series"])


def test_observatory_local_reward_punish_bias_changes_multi_tick_action_pattern():
    baseline = _run_observatory_local_action_bias_series(attr_name="", attr_value=0.0, ticks=12)
    reward = _run_observatory_local_action_bias_series(attr_name="reward_signal", attr_value=0.8, ticks=12)
    punish = _run_observatory_local_action_bias_series(attr_name="punish_signal", attr_value=0.9, ticks=12)

    assert baseline["local_map"]["summary"]["mapped_ref_count"] == 0
    assert reward["local_map"]["summary"]["mapped_ref_count"] == 1
    assert punish["local_map"]["summary"]["mapped_ref_count"] == 1
    assert reward["local_map"]["by_ref"]["st_demo_reward_signal"]["rwd"] > 0.0
    assert punish["local_map"]["by_ref"]["st_demo_punish_signal"]["pun"] > 0.0

    baseline_attempt_ticks = baseline["attempt_ticks"]
    reward_attempt_ticks = reward["attempt_ticks"]
    punish_attempt_ticks = punish["attempt_ticks"]

    assert baseline_attempt_ticks == [3, 5, 8, 10]
    assert reward_attempt_ticks == [2, 4, 6, 8, 10, 12]
    assert punish_attempt_ticks == [4, 8, 12]
    assert reward_attempt_ticks[1] < baseline_attempt_ticks[1] < punish_attempt_ticks[1]
    assert len(reward_attempt_ticks) > len(baseline_attempt_ticks) > len(punish_attempt_ticks)
    assert reward["series"][0]["drive"] > baseline["series"][0]["drive"] > punish["series"][0]["drive"]
    assert all(str(row["lookup_status"]) == "miss" for row in baseline["series"])
    assert all(str(row["lookup_status"]) == "hit" for row in reward["series"])
    assert all(str(row["lookup_status"]) == "hit" for row in punish["series"])


def test_teacher_feedback_emits_next_tick_focus_directive():
    app = ObservatoryApp(
        config_override={
            "history_limit": 4,
            "export_html": False,
            "export_json": False,
            "teacher_feedback_attribute_er_scale": 1.0,
            "teacher_feedback_attribute_ev_scale": 0.0,
            "teacher_feedback_focus_directive_enabled": True,
            "teacher_feedback_focus_strength_scale": 1.0,
            "teacher_feedback_focus_boost": 1.2,
            "teacher_feedback_focus_ttl_ticks": 2,
        }
    )
    try:
        app.run_cycle("ABX")
        report = app.run_cycle(
            "ABX",
            labels={
                "teacher_rwd": 0.9,
                "teacher_anchor": "pool_top1_total",
                "teacher_anchor_ref_object_types": ["st"],
            },
        )
        teacher_feedback = (report.get("teacher_feedback") or {})
        assert teacher_feedback.get("focus_directive_enabled") is True
        assert int(teacher_feedback.get("focus_directive_count") or 0) >= 1
        directives = [row for row in (teacher_feedback.get("focus_directives") or []) if isinstance(row, dict)]
        primary = next(row for row in directives if row.get("source_kind") == "teacher_feedback")
        assert primary.get("target_item_id") == ((teacher_feedback.get("target") or {}).get("item_id"))
        assert primary.get("ttl_ticks") == 2
        assert int(teacher_feedback.get("focus_context_carrier_count") or 0) >= 0

        next_report = app.run_cycle("")
        next_directives = (((next_report.get("modulation_inputs") or {}).get("focus_directives")) or [])
        teacher_directives = [row for row in next_directives if isinstance(row, dict) and row.get("source_kind") == "teacher_feedback"]
        assert teacher_directives
        assert teacher_directives[0].get("target_item_id") == primary.get("target_item_id")
    finally:
        app.close()


def test_teacher_feedback_context_binding_projects_reward_next_tick(tmp_path):
    app = ObservatoryApp(
        config_override={
            "history_limit": 12,
            "export_html": False,
            "export_json": False,
            "enable_goal_b_char_sa_string_mode": True,
            "hdb_data_dir": str(tmp_path / "teacher_context_binding_hdb"),
            "teacher_feedback_attribute_er_scale": 1.0,
            "teacher_feedback_attribute_ev_scale": 0.0,
            "teacher_feedback_focus_directive_enabled": True,
            "teacher_feedback_focus_context_carrier_enabled": True,
            "teacher_feedback_context_binding_enabled": True,
            "teacher_feedback_context_binding_only_when_primary_atomic": True,
            "teacher_feedback_context_binding_top_k": 1,
            "teacher_feedback_context_binding_strength_scale": 0.85,
        }
    )
    try:
        for text in ["ABX", "ABY", "ABZ", "ABQ", "ABR"]:
            app.run_cycle(text)
        reward_report = app.run_cycle(
            "ABX",
            labels={
                "teacher_rwd": 0.9,
                "teacher_anchor": "pool_top1_total",
                "teacher_anchor_ref_object_types": ["st"],
                "teacher_note": "teacher_reward_probe_round1",
            },
        )
        teacher_feedback = (reward_report.get("teacher_feedback") or {})
        assert teacher_feedback.get("primary_target_atomic") is True
        assert int(teacher_feedback.get("context_binding_candidate_count") or 0) >= 1
        assert int(teacher_feedback.get("context_binding_applied_count") or 0) >= 1

        next_report = app.run_cycle("ABY")
        metrics = extract_tick_metrics(
            report=next_report,
            dataset_tick={"tick_index": 6, "input_text": "ABY", "input_is_empty": False},
        )
        assert metrics["internal_teacher_reward_signal_attribute_count"] >= 1
    finally:
        app.close()


def test_goal_b_switch_forces_character_sa_sensor_mode():
    app = ObservatoryApp(
        config_override={
            "enable_goal_b_char_sa_string_mode": True,
            "sensor_default_mode": "advanced",
            "sensor_tokenizer_backend": "jieba",
            "sensor_enable_token_output": True,
            "sensor_enable_char_output": False,
            "export_html": False,
            "export_json": False,
        }
    )
    try:
        override = app._sensor_config_override()
        assert override["default_mode"] == "simple"
        assert override["tokenizer_backend"] == "none"
        assert override["enable_token_output"] is False
        assert override["enable_char_output"] is True
        assert override["enable_goal_b_char_sa_string_mode"] is True
    finally:
        app.close()


def test_observatory_sensor_numeric_attribute_overrides_passthrough():
    app = ObservatoryApp(
        config_override={
            "export_html": False,
            "export_json": False,
            "sensor_enable_stimulus_intensity_attribute_sa": True,
            "sensor_stimulus_intensity_attribute_min_er": 0.9,
            "sensor_attribute_er_ratio": 0.33,
            "sensor_attribute_ev_ratio": 0.07,
        }
    )
    try:
        override = app._sensor_config_override()
        assert override["enable_stimulus_intensity_attribute_sa"] is True
        assert override["stimulus_intensity_attribute_min_er"] == 0.9
        assert override["attribute_er_ratio"] == 0.33
        assert override["attribute_ev_ratio"] == 0.07
        assert app.sensor._config["enable_stimulus_intensity_attribute_sa"] is True
        assert app.sensor._config["stimulus_intensity_attribute_min_er"] == 0.9
        assert app.sensor._config["attribute_er_ratio"] == 0.33
        assert app.sensor._config["attribute_ev_ratio"] == 0.07
    finally:
        app.close()


def test_hdb_prefixed_config_override_passthrough():
    app = ObservatoryApp(
        config_override={
            "export_html": False,
            "export_json": False,
            "hdb_induction_raw_residual_group_component_projection_enabled": False,
            "hdb_induction_raw_residual_component_target_top_k": 5,
        }
    )
    try:
        override = app._hdb_config_override()
        assert override["induction_raw_residual_group_component_projection_enabled"] is False
        assert override["induction_raw_residual_component_target_top_k"] == 5
        assert app.hdb._config["induction_raw_residual_group_component_projection_enabled"] is False
        assert app.hdb._config["induction_raw_residual_component_target_top_k"] == 5
    finally:
        app.close()


def test_hdb_modulation_reports_runtime_clamped_effective_ratios():
    app = ObservatoryApp(
        config_override={
            "export_html": False,
            "export_json": False,
        }
    )
    try:
        result = app._apply_hdb_modulation_for_tick(
            modulation={
                "ev_propagation_ratio_scale": 5.0,
                "er_induction_ratio_scale": 5.0,
            },
            trace_id="reg_hdb_modulation",
            tick_id="cycle_0001",
        )
        applied = ((result or {}).get("applied", {}) or {})
        ev = applied.get("ev_propagation_ratio", {}) or {}
        er = applied.get("er_induction_ratio", {}) or {}
        assert ev.get("effective") == 1.4
        assert ev.get("runtime_effective") == 1.0
        assert ev.get("runtime_clamped") is True
        assert er.get("effective") == 1.1
        assert er.get("runtime_effective") == 1.0
        assert er.get("runtime_clamped") is True
    finally:
        app.close()


def test_second_goal_b_cycle_with_html_export_does_not_crash():
    app = ObservatoryApp(
        config_override={
            "enable_goal_b_char_sa_string_mode": True,
            "enable_structure_level_retrieval_storage": False,
            "enable_cognitive_stitching": True,
            "export_html": True,
            "export_json": False,
        }
    )
    try:
        rep1 = app.run_cycle("你好啊")
        rep2 = app.run_cycle("你好")
        assert isinstance(rep1, dict)
        assert isinstance(rep2, dict)
        assert "merged_stimulus" in rep2
    finally:
        app.close()


def test_goal_b_internal_stimulus_keeps_single_string_group():
    app = ObservatoryApp(
        config_override={
            "enable_goal_b_char_sa_string_mode": True,
            "enable_structure_level_retrieval_storage": False,
            "enable_cognitive_stitching": True,
            "export_html": False,
            "export_json": False,
        }
    )
    try:
        app.run_cycle("你好啊")
        report = app.run_cycle("你好")
        internal_raw = report.get("internal_stimulus_raw", {}) or {}
        seqs = list(internal_raw.get("sequence_groups", []) or [])

        merged = report.get("merged_stimulus", {}) or {}
        groups = list(merged.get("groups", []) or [])
        assert groups
        assert all("+" not in str(g.get("semantic_display_text", "")) for g in groups)

        if seqs:
            assert len(seqs) == 1
            seq = seqs[0]
            assert seq.get("order_sensitive") is True
            assert seq.get("string_unit_kind") == "char_sequence"
            assert seq.get("string_token_text") == "你好啊"
            assert any(bool(g.get("contains_internal_group", False)) for g in groups)
            assert any(int(g.get("internal_string_group_count", 0) or 0) >= 1 for g in groups)
    finally:
        app.close()


def test_goal_b_internal_only_merged_stimulus_stays_single_cooccurrence_group():
    app = ObservatoryApp(
        config_override={
            "enable_goal_b_char_sa_string_mode": True,
            "enable_structure_level_retrieval_storage": False,
            "enable_cognitive_stitching": True,
            "export_html": False,
            "export_json": False,
        }
    )
    try:
        app.run_cycle("你好啊")
        report = app.run_cycle("")
        merged_raw = report.get("merged_stimulus_raw", {}) or {}
        merged = report.get("merged_stimulus", {}) or {}
        raw_groups = list(merged_raw.get("grouped_sa_sequences", []) or [])
        preview_groups = list(merged.get("groups", []) or [])

        assert len(raw_groups) == 1
        assert len(preview_groups) == 1
        assert preview_groups[0].get("source_type") == "internal"
        assert bool(preview_groups[0].get("contains_internal_group", False)) is True
        assert preview_groups[0].get("internal_merge_mode") == "internal_only_packet"
    finally:
        app.close()


def test_structure_level_internal_stimulus_projects_runtime_numeric_attributes(tmp_path):
    app = ObservatoryApp(
        config_override={
            "enable_goal_b_char_sa_string_mode": True,
            "enable_structure_level_retrieval_storage": True,
            "hdb_enable_background_repair": False,
            "hdb_data_dir": str(tmp_path / "hdb_internal_runtime_attr"),
            "export_html": False,
            "export_json": False,
        }
    )
    try:
        sequence = ["ABX", "ABY", "ABZ", "ABQ", "ABR", "ABX", "ABY", "ABZ", "ABQ", "ABR"]
        saw_time_attribute = False
        for text in sequence:
            report = app.run_cycle(text)
            internal_raw = report.get("internal_stimulus_raw", {}) or {}
            attribute_items = [
                item
                for item in (internal_raw.get("sa_items", []) or [])
                if ((item.get("stimulus", {}) or {}).get("role") == "attribute")
            ]
            if any(str((item.get("content", {}) or {}).get("attribute_name", "") or "") == "时间感受" for item in attribute_items):
                saw_time_attribute = True
                time_values = [
                    float((item.get("content", {}) or {}).get("attribute_value", 0.0) or 0.0)
                    for item in attribute_items
                    if str((item.get("content", {}) or {}).get("attribute_name", "") or "") == "时间感受"
                ]
                assert any(value > 0.0 for value in time_values)
                break
        assert saw_time_attribute is True
    finally:
        app.close()


def test_stimulus_packet_preview_keeps_total_counts_when_units_are_truncated():
    app = ObservatoryApp(
        config_override={
            "export_html": False,
            "export_json": False,
            "stimulus_packet_preview_unit_limit": 3,
            "stimulus_packet_preview_flat_token_limit": 4,
        }
    )
    try:
        report = app.run_cycle("abcdefg")
        merged = report.get("merged_stimulus", {}) or {}
        assert merged.get("preview_mode") is True
        assert int(merged.get("unit_count", 0) or 0) >= len(list(merged.get("feature_units", []) or []))
        assert int(merged.get("flat_token_count", 0) or 0) >= len(list(merged.get("flat_tokens", []) or []))
        assert int(merged.get("sa_count", 0) or 0) >= len(list(merged.get("feature_units", []) or []))
    finally:
        app.close()
