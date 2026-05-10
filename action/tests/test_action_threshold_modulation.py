from action.main import ActionManager


def _run_single_action_node(*, emotion_state=None, config_override=None, params=None, local_reward_punish_map=None, gain=0.1, threshold=1.0):
    manager = ActionManager(config_override=config_override or {})
    result = manager.run_action_cycle(
        trace_id="trace_action_threshold_probe",
        tick_id="cycle_action_threshold_probe_0001",
        tick_index=1,
        cfs_signals=[],
        emotion_state=emotion_state or {},
        innate_focus_directives=[],
        innate_action_triggers=[
            {
                "action_id": "weather_probe",
                "action_kind": "weather_stub",
                "gain": gain,
                "threshold": threshold,
                "params": dict(params or {}),
                "rule_id": "rule_probe",
            }
        ],
        memory_activation_snapshot={},
        local_reward_punish_map=local_reward_punish_map or {},
    )
    data = result.get("data", {}) or {}
    nodes = data.get("nodes", []) or []
    assert len(nodes) == 1
    return nodes[0], data


def _run_multi_tick_action_series(*, local_reward_punish_map=None, ticks=6):
    manager = ActionManager(
        config_override={
            "drive_decay_ratio": 1.0,
            "action_fatigue_enabled": False,
            "threshold_scale_by_rwd_pun_enabled": False,
            "local_drive_modulation_by_rwd_pun_enabled": True,
        }
    )
    rows = []
    for tick in range(1, int(ticks) + 1):
        result = manager.run_action_cycle(
            trace_id=f"trace_action_multitick_{tick}",
            tick_id=f"cycle_action_multitick_{tick:04d}",
            tick_index=tick,
            cfs_signals=[],
            emotion_state={},
            innate_focus_directives=[],
            innate_action_triggers=[
                {
                    "action_id": "focus_probe",
                    "action_kind": "attention_focus",
                    "gain": 0.4,
                    "threshold": 1.0,
                    "params": {
                        "target_ref_object_id": "st_demo",
                        "target_ref_object_type": "st",
                        "target_display": "示例目标",
                    },
                    "rule_id": "rule_probe",
                }
            ],
            memory_activation_snapshot={},
            local_reward_punish_map=local_reward_punish_map or {},
        )
        data = result.get("data", {}) or {}
        nodes = data.get("nodes", []) or []
        assert len(nodes) == 1
        node = nodes[0]
        attempted = [
            row
            for row in (data.get("executed_actions", []) or [])
            if row.get("action_id") == "focus_probe" and bool(row.get("attempted", False))
        ]
        rows.append(
            {
                "tick": tick,
                "drive": float(node.get("drive", 0.0) or 0.0),
                "effective_threshold": float(node.get("effective_threshold", 0.0) or 0.0),
                "lookup_status": str((node.get("local_drive_modulation", {}) or {}).get("lookup_status", "") or ""),
                "scale_clamped": float((node.get("local_drive_modulation", {}) or {}).get("scale_clamped", 1.0) or 1.0),
                "attempted_exec": bool(attempted),
            }
        )
    return rows


def test_reward_signal_lowers_effective_action_threshold():
    baseline_node, _ = _run_single_action_node(emotion_state={"rwd_pun_snapshot": {"rwd": 0.0, "pun": 0.0}})
    reward_node, _ = _run_single_action_node(emotion_state={"rwd_pun_snapshot": {"rwd": 1.0, "pun": 0.0}})

    assert reward_node["effective_threshold"] < baseline_node["effective_threshold"]
    comps = reward_node["threshold_components"]
    assert comps["rwd_pun_enabled"] is True
    assert comps["rwd_pun_scale_clamped"] < 1.0
    assert comps["rwd_pun_reward_threshold_delta"] < 0.0
    assert comps["rwd_pun_punish_threshold_delta"] == 0.0


def test_punish_signal_raises_effective_action_threshold():
    baseline_node, _ = _run_single_action_node(emotion_state={"rwd_pun_snapshot": {"rwd": 0.0, "pun": 0.0}})
    punish_node, _ = _run_single_action_node(emotion_state={"rwd_pun_snapshot": {"rwd": 0.0, "pun": 1.0}})

    assert punish_node["effective_threshold"] > baseline_node["effective_threshold"]
    comps = punish_node["threshold_components"]
    assert comps["rwd_pun_enabled"] is True
    assert comps["rwd_pun_scale_clamped"] > 1.0
    assert comps["rwd_pun_reward_threshold_delta"] == 0.0
    assert comps["rwd_pun_punish_threshold_delta"] > 0.0


def test_reward_punish_threshold_modulation_can_be_disabled_globally_and_per_node():
    disabled_global_node, disabled_global_data = _run_single_action_node(
        emotion_state={"rwd_pun_snapshot": {"rwd": 1.0, "pun": 1.0}},
        config_override={"threshold_scale_by_rwd_pun_enabled": False},
    )
    baseline_node, _ = _run_single_action_node(emotion_state={"rwd_pun_snapshot": {"rwd": 0.0, "pun": 0.0}})
    disabled_local_node, disabled_local_data = _run_single_action_node(
        emotion_state={"rwd_pun_snapshot": {"rwd": 1.0, "pun": 1.0}},
        params={"disable_rwd_pun_threshold_modulation": True},
    )

    assert disabled_global_node["effective_threshold"] == baseline_node["effective_threshold"]
    assert disabled_local_node["effective_threshold"] == baseline_node["effective_threshold"]
    assert disabled_global_node["threshold_components"]["rwd_pun_enabled"] is False
    assert disabled_local_node["threshold_components"]["rwd_pun_enabled"] is False
    assert disabled_global_data["threshold_modulation"]["threshold_scale_by_rwd_pun_enabled"] is False
    assert disabled_local_data["threshold_modulation"]["threshold_scale_by_rwd_pun_enabled"] is True


def test_local_reward_signal_increases_targeted_action_drive_gain():
    baseline_node, baseline_data = _run_single_action_node(
        params={"target_ref_object_id": "st_demo", "target_ref_object_type": "st", "disable_threshold_modulation": True},
        gain=0.4,
        threshold=2.0,
    )
    reward_node, reward_data = _run_single_action_node(
        params={"target_ref_object_id": "st_demo", "target_ref_object_type": "st", "disable_threshold_modulation": True},
        local_reward_punish_map={"by_ref": {"st_demo": {"rwd": 0.8, "pun": 0.0, "detail": {"source": "pytest"}}}},
        gain=0.4,
        threshold=2.0,
    )

    assert reward_node["drive"] > baseline_node["drive"]
    assert reward_node["local_drive_modulation"]["lookup_hit"] is True
    assert reward_node["local_drive_modulation"]["applied"] is True
    assert reward_node["local_drive_modulation"]["reward_bonus_gain"] > 0.0
    summary = reward_data["action_learning_summary"]
    assert summary["local_modulated_node_count"] == 1
    assert summary["local_reward_drive_bonus_total"] > 0.0


def test_local_punish_signal_reduces_targeted_action_drive_gain_and_can_be_disabled():
    punish_node, punish_data = _run_single_action_node(
        params={"target_ref_object_id": "st_demo", "target_ref_object_type": "st", "disable_threshold_modulation": True},
        local_reward_punish_map={"by_ref": {"st_demo": {"rwd": 0.0, "pun": 0.9, "detail": {"source": "pytest"}}}},
        gain=0.4,
        threshold=2.0,
    )
    disabled_node, disabled_data = _run_single_action_node(
        params={
            "target_ref_object_id": "st_demo",
            "target_ref_object_type": "st",
            "disable_threshold_modulation": True,
            "disable_local_reward_punish_drive_modulation": True,
        },
        local_reward_punish_map={"by_ref": {"st_demo": {"rwd": 0.0, "pun": 0.9, "detail": {"source": "pytest"}}}},
        gain=0.4,
        threshold=2.0,
    )

    assert punish_node["drive"] < disabled_node["drive"]
    assert punish_node["local_drive_modulation"]["lookup_hit"] is True
    assert punish_node["local_drive_modulation"]["punish_penalty_gain"] > 0.0
    assert disabled_node["local_drive_modulation"]["applied"] is False
    assert disabled_data["action_learning_summary"]["local_modulated_node_count"] == 0
    assert punish_data["action_learning_summary"]["local_punish_drive_penalty_total"] > 0.0


def test_local_lookup_miss_only_counts_real_lookup_failures():
    skipped_node, skipped_data = _run_single_action_node(
        params={
            "target_ref_object_id": "st_demo",
            "target_ref_object_type": "st",
            "disable_threshold_modulation": True,
            "disable_local_reward_punish_drive_modulation": True,
        },
        gain=0.4,
        threshold=2.0,
    )
    missing_target_node, missing_target_data = _run_single_action_node(
        params={"disable_threshold_modulation": True},
        gain=0.4,
        threshold=2.0,
    )
    miss_node, miss_data = _run_single_action_node(
        params={"target_ref_object_id": "st_demo", "target_ref_object_type": "st", "disable_threshold_modulation": True},
        gain=0.4,
        threshold=2.0,
    )

    assert skipped_node["local_drive_modulation"]["lookup_status"] == "skipped"
    assert skipped_data["action_learning_summary"]["local_lookup_miss_count"] == 0
    assert skipped_data["action_learning_summary"]["local_lookup_skipped_count"] == 1
    assert skipped_data["action_learning_summary"]["local_modulation_disabled_count"] == 1

    assert missing_target_node["local_drive_modulation"]["lookup_status"] == "skipped"
    assert missing_target_data["action_learning_summary"]["local_lookup_miss_count"] == 0
    assert missing_target_data["action_learning_summary"]["local_lookup_skipped_count"] == 1
    assert missing_target_data["action_learning_summary"]["local_target_missing_count"] == 1

    assert miss_node["local_drive_modulation"]["lookup_status"] == "miss"
    assert miss_data["action_learning_summary"]["local_lookup_miss_count"] == 1
    assert miss_data["action_learning_summary"]["local_lookup_skipped_count"] == 0


def test_local_reward_punish_changes_multi_tick_action_execution_bias():
    baseline_rows = _run_multi_tick_action_series(local_reward_punish_map={}, ticks=6)
    reward_rows = _run_multi_tick_action_series(
        local_reward_punish_map={"by_ref": {"st_demo": {"rwd": 0.8, "pun": 0.0}}},
        ticks=6,
    )
    punish_rows = _run_multi_tick_action_series(
        local_reward_punish_map={"by_ref": {"st_demo": {"rwd": 0.0, "pun": 0.9}}},
        ticks=6,
    )

    def _attempt_ticks(rows):
        return [int(row["tick"]) for row in rows if bool(row["attempted_exec"])]

    baseline_attempt_ticks = _attempt_ticks(baseline_rows)
    reward_attempt_ticks = _attempt_ticks(reward_rows)
    punish_attempt_ticks = _attempt_ticks(punish_rows)

    assert baseline_attempt_ticks == [3, 5]
    assert reward_attempt_ticks == [2, 4, 6]
    assert punish_attempt_ticks == [5]
    assert reward_attempt_ticks[0] < baseline_attempt_ticks[0] < punish_attempt_ticks[0]
    assert len(reward_attempt_ticks) > len(baseline_attempt_ticks) > len(punish_attempt_ticks)
    assert reward_rows[0]["drive"] > baseline_rows[0]["drive"] > punish_rows[0]["drive"]
    assert all(str(row["lookup_status"]) == "hit" for row in reward_rows)
    assert all(str(row["lookup_status"]) == "hit" for row in punish_rows)
    assert all(str(row["lookup_status"]) == "miss" for row in baseline_rows)


def test_local_reward_text_fallback_matches_input_target_against_structure_feedback():
    node, data = _run_single_action_node(
        params={
            "target_ref_object_id": "ctx_input_current",
            "target_ref_object_type": "input",
            "target_item_id": "ctx_input_current",
            "target_display": "【用户消息】可以帮我查一下明天上海天气吗？",
            "disable_threshold_modulation": True,
        },
        local_reward_punish_map={
            "by_ref": {
                "st_demo_weather_reward": {
                    "rwd": 0.8,
                    "pun": 0.0,
                    "display": "结构: 用户消息 可以帮我查一下明天上海天气吗",
                    "detail": {"source": "pytest_text_fallback"},
                }
            }
        },
        gain=0.4,
        threshold=2.0,
    )

    assert node["local_drive_modulation"]["lookup_status"] == "hit"
    assert node["local_drive_modulation"]["lookup_mode"] == "text_fallback"
    assert node["local_drive_modulation"]["lookup_hit"] is True
    assert node["local_drive_modulation"]["reward_bonus_gain"] > 0.0
    assert data["action_learning_summary"]["local_lookup_hit_count"] == 1
    assert data["action_learning_summary"]["local_lookup_text_fallback_hit_count"] == 1
    assert data["action_learning_summary"]["local_reward_drive_bonus_total"] > 0.0


def test_local_reward_text_fallback_can_be_disabled():
    node, data = _run_single_action_node(
        config_override={"local_drive_feedback_text_fallback_enabled": False},
        params={
            "target_ref_object_id": "ctx_input_current",
            "target_ref_object_type": "input",
            "target_item_id": "ctx_input_current",
            "target_display": "【用户消息】可以帮我查一下明天上海天气吗？",
            "disable_threshold_modulation": True,
        },
        local_reward_punish_map={
            "by_ref": {
                "st_demo_weather_reward": {
                    "rwd": 0.8,
                    "pun": 0.0,
                    "display": "结构: 用户消息 可以帮我查一下明天上海天气吗",
                    "detail": {"source": "pytest_text_fallback_disabled"},
                }
            }
        },
        gain=0.4,
        threshold=2.0,
    )

    assert node["local_drive_modulation"]["lookup_status"] == "miss"
    assert node["local_drive_modulation"]["lookup_mode"] == ""
    assert node["local_drive_modulation"]["detail"]["text_fallback_reason"] == "config_disabled"
    assert data["action_learning_summary"]["local_lookup_hit_count"] == 0
    assert data["action_learning_summary"]["local_lookup_text_fallback_hit_count"] == 0
    assert data["action_learning_summary"]["local_lookup_miss_count"] == 1


def test_local_reward_text_fallback_handles_structure_display_noise():
    node, data = _run_single_action_node(
        params={
            "target_ref_object_id": "ctx_input_current",
            "target_ref_object_type": "input",
            "target_item_id": "ctx_input_current",
            "target_display": "【用户消息】可以帮我查询一下天气吗？",
            "disable_threshold_modulation": True,
        },
        local_reward_punish_map={
            "by_ref": {
                "st_demo_weather_reward_noisy": {
                    "rwd": 0.8,
                    "pun": 0.0,
                    "display": "{(【 + stimulus_intensity:0.35) / (用 + stimulus_intensity:1.0) / (户 + stimulus_intensity:1.0) / (消 + stimulus_intensity:1.0) / (息 + stimulus_intensity:1.0) / (】 + stimulus_intensity:0.35) / (可 + stimulus_intensity:1.0) / (以 + stimulus_intensity:1.0) / (帮 + stimulus_intensity:1.0) / (我 + stimulus_intensity:1.0) / (查 + stimulus_intensity:1.0) / (询 + stimulus_intensity:1.0) / (一 + stimulus_intensity:1.0) / (下 + stimulus_intensity:1.0) / (天 + stimulus_intensity:1.0) / (气 + stimulus_intensity:1.0) / (吗 + stimulus_intensity:1.0) / (？ + stimulus_intensity:0.385)}",
                    "detail": {"source": "pytest_text_fallback_noisy"},
                }
            }
        },
        gain=0.75,
        threshold=0.6,
    )

    assert node["local_drive_modulation"]["lookup_status"] == "hit"
    assert node["local_drive_modulation"]["lookup_mode"] == "text_fallback"
    assert node["local_drive_modulation"]["lookup_hit"] is True
    assert node["local_drive_modulation"]["reward_bonus_gain"] > 0.0
    assert data["action_learning_summary"]["local_lookup_hit_count"] == 1
    assert data["action_learning_summary"]["local_lookup_text_fallback_hit_count"] == 1


def test_explicit_input_drive_scale_can_overpower_local_punish_penalty():
    baseline_node, baseline_data = _run_single_action_node(
        params={
            "target_ref_object_id": "ctx_input_current",
            "target_ref_object_type": "input",
            "target_item_id": "ctx_input_current",
            "target_display": "【用户消息】可以帮我查询一下天气吗？",
            "disable_threshold_modulation": True,
        },
        local_reward_punish_map={
            "by_ref": {
                "st_demo_weather_punish": {
                    "rwd": 0.0,
                    "pun": 0.9,
                    "display": "结构: 用户消息 可以帮我查询一下天气吗",
                    "detail": {"source": "pytest_input_drive_baseline"},
                }
            }
        },
        gain=0.75,
        threshold=0.6,
    )
    boosted_node, boosted_data = _run_single_action_node(
        params={
            "target_ref_object_id": "ctx_input_current",
            "target_ref_object_type": "input",
            "target_item_id": "ctx_input_current",
            "target_display": "【用户消息】可以帮我查询一下天气吗？",
            "disable_threshold_modulation": True,
            "explicit_input_drive_scale": 1.60,
        },
        local_reward_punish_map={
            "by_ref": {
                "st_demo_weather_punish": {
                    "rwd": 0.0,
                    "pun": 0.9,
                    "display": "结构: 用户消息 可以帮我查询一下天气吗",
                    "detail": {"source": "pytest_input_drive_boosted"},
                }
            }
        },
        gain=0.75,
        threshold=0.6,
    )

    baseline_attempted = any(
        row.get("action_id") == "weather_probe" and bool(row.get("attempted", False))
        for row in (baseline_data.get("executed_actions", []) or [])
    )
    boosted_exec = next(
        row
        for row in (boosted_data.get("executed_actions", []) or [])
        if row.get("action_id") == "weather_probe" and bool(row.get("attempted", False))
    )

    assert baseline_node["drive"] < baseline_node["effective_threshold"]
    assert baseline_attempted is False
    assert boosted_exec["drive_before"] > baseline_node["drive"]
    assert boosted_exec["drive_before"] >= boosted_exec["effective_threshold"]
    assert boosted_node["local_drive_modulation"]["input_drive_boost_applied"] is True
    assert boosted_node["local_drive_modulation"]["input_drive_scale"] == 1.6
    assert boosted_node["local_drive_modulation"]["input_drive_boost_gain"] > 0.0


def test_iesm_action_trigger_top_level_target_fields_are_folded_into_node_params_and_meta():
    manager = ActionManager(
        config_override={
            "local_drive_modulation_by_rwd_pun_enabled": True,
            "local_drive_modulation_require_target": True,
            "threshold_scale_by_rwd_pun_enabled": False,
        }
    )
    result = manager.run_action_cycle(
        trace_id="trace_action_target_binding",
        tick_id="cycle_action_target_binding_0001",
        tick_index=1,
        cfs_signals=[],
        emotion_state={},
        innate_focus_directives=[],
        innate_action_triggers=[
            {
                "action_id": "weather_probe",
                "action_kind": "weather_stub",
                "gain": 0.4,
                "threshold": 0.9,
                "target_ref_object_id": "ctx_input_current",
                "target_ref_object_type": "input",
                "target_item_id": "ctx_input_current",
                "target_display": "【用户消息】可以帮我查一下天气吗？",
                "target_binding_strategy": "match",
                "target_binding_requested_from": "match",
                "target_binding_applied": True,
                "target_binding_reason": "match_target_bound",
                "target_binding_match_source": "metric_matches",
                "target_binding_match_ref_object_id": "ctx_input_current",
                "target_binding_match_ref_object_type": "input",
                "target_binding_match_item_id": "ctx_input_current",
                "target_binding_match_display": "【用户消息】可以帮我查一下天气吗？",
                "rule_id": "innate_action_weather_stub_from_query_weather",
            }
        ],
        memory_activation_snapshot={},
        local_reward_punish_map={},
    )
    data = result.get("data", {}) or {}
    nodes = data.get("nodes", []) or []
    assert len(nodes) == 1
    node = nodes[0]
    assert node["target_ref_object_id"] == "ctx_input_current"
    assert node["target_ref_object_type"] == "input"
    assert node["target_item_id"] == "ctx_input_current"
    assert node["params"]["target_ref_object_id"] == "ctx_input_current"
    assert node["target_binding_strategy"] == "match"
    assert node["target_binding_requested_from"] == "match"
    assert node["target_binding_applied"] is True
    assert node["target_binding_match_source"] == "metric_matches"
    assert node["local_drive_modulation"]["lookup_status"] == "miss"


def test_idle_prune_frees_capacity_for_new_tool_action_nodes():
    manager = ActionManager(
        config_override={
            "drive_decay_ratio": 1.0,
            "node_idle_prune_ticks": 2,
            "max_action_nodes": 64,
            "threshold_scale_by_rwd_pun_enabled": False,
            "local_drive_modulation_by_rwd_pun_enabled": False,
            "action_fatigue_enabled": False,
        }
    )
    manager._nodes = {
        f"focus::st::old_{idx:03d}": {
            "action_id": f"focus::st::old_{idx:03d}",
            "action_kind": "attention_focus",
            "drive": 0.01,
            "threshold": 1.0,
            "cooldown_ticks": 0,
            "params": {},
            "trigger_sources": [],
            "created_at": 1,
            "last_update_tick": 1,
            "last_trigger_tick": -999999,
        }
        for idx in range(64)
    }

    result = manager.run_action_cycle(
        trace_id="trace_action_idle_prune_capacity",
        tick_id="cycle_action_idle_prune_capacity_0001",
        tick_index=10,
        cfs_signals=[],
        emotion_state={},
        innate_focus_directives=[],
        innate_action_triggers=[
            {
                "action_id": "weather_stub",
                "action_kind": "weather_stub",
                "gain": 0.75,
                "threshold": 0.60,
                "params": {
                    "disable_threshold_modulation": True,
                    "async_delay_ticks": 1,
                },
                "rule_id": "innate_action_weather_stub_from_query_weather",
            }
        ],
        memory_activation_snapshot={},
        local_reward_punish_map={},
    )

    data = result.get("data", {}) or {}
    nodes = data.get("nodes", []) or []
    executed = data.get("executed_actions", []) or []
    assert len(manager._nodes) == 1
    assert any(node.get("action_kind") == "weather_stub" for node in nodes)
    assert any(
        row.get("action_kind") == "weather_stub" and row.get("failure_reason") == "async_pending_completion"
        for row in executed
    )


def test_action_drive_stacks_by_action_id_and_splits_by_parameterized_target():
    manager = ActionManager(
        config_override={
            "drive_decay_ratio": 1.0,
            "drive_max": 10.0,
            "node_idle_prune_ticks": 999,
            "threshold_scale_by_rwd_pun_enabled": False,
            "local_drive_modulation_by_rwd_pun_enabled": False,
            "action_fatigue_enabled": False,
        }
    )

    same_target_trigger = {
        "action_id": "attention_focus_st_same",
        "action_kind": "attention_focus",
        "gain": 0.3,
        "threshold": 99.0,
        "params": {
            "target_ref_object_id": "st_same",
            "target_ref_object_type": "st",
            "target_display": "同一目标",
        },
    }
    other_target_trigger = {
        "action_id": "attention_focus_st_other",
        "action_kind": "attention_focus",
        "gain": 0.3,
        "threshold": 99.0,
        "params": {
            "target_ref_object_id": "st_other",
            "target_ref_object_type": "st",
            "target_display": "另一个目标",
        },
    }

    for tick in range(1, 4):
        triggers = [same_target_trigger] if tick < 3 else [same_target_trigger, other_target_trigger]
        manager.run_action_cycle(
            trace_id=f"trace_action_identity_{tick}",
            tick_id=f"cycle_action_identity_{tick:04d}",
            tick_index=tick,
            cfs_signals=[],
            emotion_state={},
            innate_focus_directives=[],
            innate_action_triggers=triggers,
            memory_activation_snapshot={},
            local_reward_punish_map={},
        )

    assert set(manager._nodes) == {"attention_focus_st_same", "attention_focus_st_other"}
    assert abs(manager._nodes["attention_focus_st_same"]["drive"] - 0.9) < 1e-12
    assert abs(manager._nodes["attention_focus_st_other"]["drive"] - 0.3) < 1e-12
