# -*- coding: utf-8 -*-
"""
Tests for the IESM declarative rules engine.
IESM 声明式规则引擎测试。

Why / 为什么要测：
- Prototype stage changes quickly; tests keep the core rule semantics stable.
  原型阶段迭代快，用测试锁定核心语义，避免回归。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from innate_script._rules_engine import evaluate_rules, normalize_rules_doc


def _normalize(raw: dict) -> dict:
    doc, errors, _warnings = normalize_rules_doc(raw)
    assert not errors, f"unexpected errors: {errors}"
    return doc


def _load_default_rules_doc() -> dict:
    raw = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "innate_rules.yaml").read_text(encoding="utf-8"))
    return _normalize(raw)


def test_parse_tick_index_via_evaluate_rules() -> None:
    doc = _normalize(
        {
            "rules_schema_version": "1.0",
            "rules_version": "t",
            "enabled": True,
            "defaults": {},
            "rules": [
                {
                    "id": "noop",
                    "title": "noop",
                    "enabled": True,
                    "priority": 1,
                    "cooldown_ticks": 0,
                    "when": {"timer": {"at_tick": 999999}},
                    "then": [{"log": "never"}],
                    "note": "",
                }
            ],
        }
    )

    engine = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0012",
        tick_index=None,
        cfs_signals=[],
        state_windows=[],
        now_ms=None,
        runtime_state={},
    )
    assert engine.get("tick_index") == 12


def test_cfs_focus_directive_happy_path() -> None:
    doc = _normalize(
        {
            "rules_schema_version": "1.0",
            "rules_version": "t",
            "enabled": True,
            "defaults": {"focus_directive": {"ttl_ticks": 2, "focus_boost": 0.9, "deduplicate_by": "target_ref_object_id"}},
            "rules": [
                {
                    "id": "focus_on_dissonance",
                    "title": "CFS -> focus",
                    "enabled": True,
                    "priority": 10,
                    "cooldown_ticks": 0,
                    "when": {"cfs": {"kinds": ["dissonance"], "min_strength": 0.3}},
                    "then": [{"focus": {"from": "cfs_matches", "match_policy": "all"}}],
                    "note": "",
                }
            ],
        }
    )

    engine = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=None,
        cfs_signals=[
            {
                "kind": "dissonance",
                "strength": 0.5,
                "target": {"target_ref_object_id": "st_0001", "target_ref_object_type": "st", "target_display": "test"},
                "reasons": ["cp_abs>=threshold"],
            }
        ],
        state_windows=[],
        now_ms=123,
        runtime_state={},
    )

    directives = (engine.get("directives") or {}).get("focus_directives") or []
    assert len(directives) == 1
    d0 = directives[0]
    assert d0.get("directive_type") == "attention_focus"
    assert d0.get("source_kind") == "dissonance"
    assert d0.get("target_ref_object_id") == "st_0001"
    assert d0.get("ttl_ticks") == 2


def test_cfs_emit_appends_signal() -> None:
    doc = _normalize(
        {
            "rules_schema_version": "1.0",
            "rules_version": "t",
            "enabled": True,
            "defaults": {},
            "rules": [
                {
                    "id": "emit_one",
                    "title": "emit one",
                    "enabled": True,
                    "phase": "cfs",
                    "priority": 10,
                    "cooldown_ticks": 0,
                    "when": {"timer": {"at_tick": 1}},
                    "then": [{"cfs_emit": {"kind": "dissonance", "from": "single", "scope": "global", "strength": 1.0}}],
                    "note": "",
                }
            ],
        }
    )

    engine = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[],
        context={},
        now_ms=123,
        runtime_state={},
        allow_timer=True,
    )
    cfs_out = (engine.get("directives") or {}).get("cfs_signals") or []
    assert len(cfs_out) == 1
    assert cfs_out[0].get("kind") == "dissonance"
    assert cfs_out[0].get("scope") == "global"
    assert float(cfs_out[0].get("strength") or 0.0) == 1.0


def test_cfs_emit_binds_attribute_even_when_below_min_strength() -> None:
    doc = _normalize(
        {
            "rules_schema_version": "1.0",
            "rules_version": "t",
            "enabled": True,
            "defaults": {},
            "rules": [
                {
                    "id": "quiet_bind",
                    "title": "quiet bind",
                    "enabled": True,
                    "phase": "cfs",
                    "priority": 10,
                    "cooldown_ticks": 0,
                    "when": {"timer": {"at_tick": 1}},
                    "then": [
                        {
                            "cfs_emit": {
                                "kind": "dissonance",
                                "from": "single",
                                "scope": "object",
                                "strength": 0.2,
                                "min_strength": 0.3,
                                "emit_gate": {
                                    "mode": "strength_delta",
                                    "min_delta": 0.05,
                                    "bind_attribute_even_when_skipped": True,
                                },
                                "target": {
                                    "from": "specific_item",
                                    "item_id": "spi_quiet",
                                    "display": "quiet target",
                                },
                                "bind_attribute": {
                                    "attribute_name": "cfs_dissonance",
                                    "display": "违和感:{{{strength}}}",
                                    "value_from": "strength",
                                    "value_type": "numerical",
                                    "modality": "internal",
                                    "er": 0.0,
                                    "ev": "{{{strength}}}",
                                },
                            }
                        }
                    ],
                    "note": "",
                }
            ],
        }
    )

    engine = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[],
        context={},
        now_ms=123,
        runtime_state={},
        allow_timer=True,
    )
    directives = engine.get("directives") or {}
    assert (directives.get("cfs_signals") or []) == []
    pool_effects = directives.get("pool_effects") or []
    assert len(pool_effects) == 1
    attr = ((pool_effects[0].get("spec") or {}).get("attribute") or {})
    assert attr.get("attribute_name") == "cfs_dissonance"
    assert attr.get("attribute_value") == 0.2
    assert attr.get("ev") == 0.2
    notes = ((engine.get("audit") or {}).get("notes") or [])
    assert not any("quiet_bind" in str(note) and "action error" in str(note) for note in notes)


def test_emotion_update_can_expand_from_cfs_matches_with_scaled_deltas() -> None:
    doc = _normalize(
        {
            "rules_schema_version": "1.0",
            "rules_version": "t",
            "enabled": True,
            "defaults": {},
            "rules": [
                {
                    "id": "emotion_from_surprise",
                    "title": "emotion from surprise",
                    "enabled": True,
                    "phase": "directives",
                    "priority": 10,
                    "cooldown_ticks": 0,
                    "when": {"cfs": {"kinds": ["surprise"], "min_strength": 0.1}},
                    "then": [
                        {
                            "emotion_update": {
                                "from": "cfs_matches",
                                "match_policy": "all",
                                "ADR": {"from": "match_value", "policy": "scale_offset", "scale": 0.1},
                                "NOV": {"from": "match_value", "policy": "scale_offset", "scale": 0.2},
                                "FOC": {"from": "match_value", "policy": "scale_offset", "scale": -0.05},
                            }
                        }
                    ],
                    "note": "",
                }
            ],
        }
    )

    engine = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        cfs_signals=[
            {"kind": "surprise", "strength": 0.8},
            {"kind": "surprise", "strength": 0.6},
        ],
        state_windows=[],
        context={},
        now_ms=123,
        runtime_state={},
    )

    updates = ((engine.get("directives") or {}).get("emotion_updates") or {})
    assert float(updates.get("ADR", 0.0)) == 0.14
    assert float(updates.get("NOV", 0.0)) == 0.28
    assert float(updates.get("FOC", 0.0)) == -0.07


def test_default_rules_emit_script_driven_nt_updates_for_core_cfs() -> None:
    doc = _load_default_rules_doc()

    engine = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        cfs_signals=[
            {"kind": "surprise", "strength": 0.8},
            {"kind": "expectation", "strength": 0.4},
        ],
        state_windows=[],
        context={},
        now_ms=123,
        runtime_state={},
    )

    updates = ((engine.get("directives") or {}).get("emotion_updates") or {})
    assert float(updates.get("ADR", 0.0)) == pytest.approx(0.056)
    assert float(updates.get("NOV", 0.0)) == pytest.approx(0.09)
    assert float(updates.get("COR", 0.0)) == pytest.approx(0.012)
    assert float(updates.get("FOC", 0.0)) == pytest.approx(-0.016)
    assert float(updates.get("DA", 0.0)) == pytest.approx(0.024)


def test_evaluate_rules_can_filter_emotion_post_phase() -> None:
    doc = _normalize(
        {
            "rules_schema_version": "1.0",
            "rules_version": "t",
            "enabled": True,
            "defaults": {},
            "rules": [
                {
                    "id": "directives_rule",
                    "title": "directives rule",
                    "enabled": True,
                    "phase": "directives",
                    "priority": 10,
                    "cooldown_ticks": 0,
                    "when": {"timer": {"at_tick": 1}},
                    "then": [{"emotion_update": {"NOV": 0.12}}],
                    "note": "",
                },
                {
                    "id": "emotion_post_rule",
                    "title": "emotion post rule",
                    "enabled": True,
                    "phase": "emotion_post",
                    "priority": 9,
                    "cooldown_ticks": 0,
                    "when": {"timer": {"at_tick": 1}},
                    "then": [{"emotion_update": {"SER": 0.08}}],
                    "note": "",
                },
            ],
        }
    )

    directives_only = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[],
        context={},
        now_ms=123,
        runtime_state={},
        allow_timer=True,
        allowed_phases=["directives"],
    )
    directives_updates = ((directives_only.get("directives") or {}).get("emotion_updates") or {})
    directives_rules = directives_only.get("triggered_rules") or []
    assert directives_updates == {"NOV": 0.12}
    assert [row.get("rule_id") for row in directives_rules] == ["directives_rule"]

    emotion_post_only = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[],
        context={},
        now_ms=123,
        runtime_state={},
        allow_timer=True,
        allowed_phases=["emotion_post"],
    )
    emotion_post_updates = ((emotion_post_only.get("directives") or {}).get("emotion_updates") or {})
    emotion_post_rules = emotion_post_only.get("triggered_rules") or []
    assert emotion_post_updates == {"SER": 0.08}
    assert [row.get("rule_id") for row in emotion_post_rules] == ["emotion_post_rule"]


def test_allow_timer_flag_disables_timer_predicates() -> None:
    doc = _normalize(
        {
            "rules_schema_version": "1.0",
            "rules_version": "t",
            "enabled": True,
            "defaults": {},
            "rules": [
                {
                    "id": "timer_test",
                    "title": "Timer",
                    "enabled": True,
                    "priority": 10,
                    "cooldown_ticks": 0,
                    "when": {"timer": {"at_tick": 1}},
                    "then": [{"log": "hi"}],
                    "note": "",
                }
            ],
        }
    )

    engine_on = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=None,
        cfs_signals=[],
        state_windows=[],
        now_ms=None,
        runtime_state={},
        allow_timer=True,
    )
    assert len(engine_on.get("triggered_rules") or []) == 1

    engine_off = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=None,
        cfs_signals=[],
        state_windows=[],
        now_ms=None,
        runtime_state={},
        allow_timer=False,
    )
    assert len(engine_off.get("triggered_rules") or []) == 0


def test_cooldown_ticks_bookkeeping() -> None:
    doc = _normalize(
        {
            "rules_schema_version": "1.0",
            "rules_version": "t",
            "enabled": True,
            "defaults": {},
            "rules": [
                {
                    "id": "cooldown_rule",
                    "title": "Cooldown rule",
                    "enabled": True,
                    "priority": 10,
                    "cooldown_ticks": 3,
                    "when": {"timer": {"every_n_ticks": 1}},
                    "then": [{"log": "fire"}],
                    "note": "",
                }
            ],
        }
    )

    runtime_state: dict = {}
    fired_ticks: list[int] = []
    for tick in (1, 2, 3, 4):
        engine = evaluate_rules(
            doc=doc,
            trace_id="t",
            tick_id=f"cycle_{tick:04d}",
            tick_index=tick,
            cfs_signals=[],
            state_windows=[],
            now_ms=None,
            runtime_state=runtime_state,
            allow_timer=True,
        )
        if engine.get("triggered_rules"):
            fired_ticks.append(tick)

    # With cooldown=3, it should fire at tick=1 and tick=4.
    # cooldown=3 时，应在 tick=1 和 tick=4 触发。
    assert fired_ticks == [1, 4]


def test_action_trigger_can_filter_input_by_user_message_flags() -> None:
    doc = _normalize(
        {
            "rules_schema_version": "1.0",
            "rules_version": "t",
            "enabled": True,
            "defaults": {},
            "rules": [
                {
                    "id": "weather_from_user_message_only",
                    "title": "weather from user message only",
                    "phase": "directives",
                    "enabled": True,
                    "priority": 10,
                    "cooldown_ticks": 0,
                    "when": {
                        "all": [
                            {
                                "metric": {
                                    "metric": "item.exists",
                                    "selector": {
                                        "mode": "contains_text",
                                        "contains_text": "天气",
                                        "ref_object_types": ["input"],
                                        "where": {
                                            "input_is_user": {"op": ">=", "value": 1},
                                            "input_is_message": {"op": ">=", "value": 1},
                                        },
                                    },
                                    "op": ">=",
                                    "value": 0.0,
                                }
                            },
                            {
                                "metric": {
                                    "metric": "item.exists",
                                    "selector": {
                                        "mode": "contains_text",
                                        "contains_text": "查询",
                                        "ref_object_types": ["input"],
                                        "where": {
                                            "input_is_user": {"op": ">=", "value": 1},
                                            "input_is_message": {"op": ">=", "value": 1},
                                        },
                                    },
                                    "op": ">=",
                                    "value": 0.0,
                                }
                            },
                        ]
                    },
                    "then": [
                        {
                            "action_trigger": {
                                "from": "metric_matches",
                                "match_policy": "strongest",
                                "max_triggers": 1,
                                "target_from": "match",
                                "action_kind": "weather_stub",
                                "action_id": "weather_stub",
                                "gain": 0.75,
                                "threshold": 0.60,
                            }
                        }
                    ],
                    "note": "",
                }
            ],
        }
    )

    runtime_state: dict = {}
    system_only = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[],
        context={
            "pool_items": [
                {
                    "item_id": "ctx_input_current",
                    "ref_object_id": "ctx_input_current",
                    "ref_object_type": "input",
                    "display": "【系统事件】会话恢复：天气查询为占位实现。",
                    "display_detail": "",
                    "input_is_user": 0,
                    "input_is_message": 0,
                    "input_is_system": 1,
                    "input_is_session_restore": 1,
                }
            ]
        },
        now_ms=123,
        runtime_state=runtime_state,
    )
    assert ((system_only.get("directives") or {}).get("action_triggers") or []) == []

    user_message = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0002",
        tick_index=2,
        cfs_signals=[],
        state_windows=[],
        context={
            "pool_items": [
                {
                    "item_id": "ctx_input_current",
                    "ref_object_id": "ctx_input_current",
                    "ref_object_type": "input",
                    "display": "【用户消息】可以帮我查询一下天气吗？",
                    "display_detail": "",
                    "input_is_user": 1,
                    "input_is_message": 1,
                    "input_is_system": 0,
                    "input_is_session_restore": 0,
                }
            ]
        },
        now_ms=456,
        runtime_state=runtime_state,
    )
    triggers = ((user_message.get("directives") or {}).get("action_triggers") or [])
    assert len(triggers) == 1
    assert triggers[0].get("action_kind") == "weather_stub"
    params = triggers[0].get("params") or {}
    assert params.get("target_ref_object_id") == "ctx_input_current"
    assert params.get("target_ref_object_type") == "input"
    assert params.get("target_item_id") == "ctx_input_current"
    assert triggers[0].get("target_binding_applied") is True
    assert triggers[0].get("target_binding_requested_from") == "match"


def test_default_weather_query_rule_matches_query_synonym_phrase() -> None:
    doc = _load_default_rules_doc()

    engine = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[],
        context={
            "pool_items": [
                {
                    "item_id": "ctx_input_current",
                    "ref_object_id": "ctx_input_current",
                    "ref_object_type": "input",
                    "display": "【用户消息】那你帮我查一下今天的天气，我想决定到底穿卫衣还是薄针织。",
                    "display_detail": "",
                    "input_is_user": 1,
                    "input_is_message": 1,
                    "input_is_system": 0,
                    "input_is_session_restore": 0,
                }
            ]
        },
        now_ms=123,
        runtime_state={},
    )

    triggered_rule_ids = {str(item.get("rule_id", "") or "") for item in (engine.get("triggered_rules") or [])}
    assert "innate_action_weather_stub_from_query_weather" in triggered_rule_ids
    triggers = ((engine.get("directives") or {}).get("action_triggers") or [])
    weather = next(item for item in triggers if str(item.get("action_kind", "") or "") == "weather_stub")
    params = weather.get("params") or {}
    assert params.get("target_ref_object_id") == "ctx_input_current"
    assert params.get("target_ref_object_type") == "input"
    assert params.get("target_item_id") == "ctx_input_current"
    assert weather.get("target_binding_applied") is True


def test_default_weather_question_rule_matches_implicit_weather_question_phrase() -> None:
    doc = _load_default_rules_doc()

    engine = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[],
        context={
            "pool_items": [
                {
                    "item_id": "ctx_input_current",
                    "ref_object_id": "ctx_input_current",
                    "ref_object_type": "input",
                    "display": "【用户消息】我中午可能要出门拿快递，天气会不会有点凉？",
                    "display_detail": "",
                    "input_is_user": 1,
                    "input_is_message": 1,
                    "input_is_system": 0,
                    "input_is_session_restore": 0,
                }
            ]
        },
        now_ms=123,
        runtime_state={},
    )

    triggered_rule_ids = {str(item.get("rule_id", "") or "") for item in (engine.get("triggered_rules") or [])}
    assert "innate_action_weather_stub_from_weather_only" not in triggered_rule_ids
    assert "innate_action_weather_stub_from_query_weather" not in triggered_rule_ids
    assert "innate_action_weather_stub_from_weather_question" in triggered_rule_ids
    triggers = ((engine.get("directives") or {}).get("action_triggers") or [])
    assert len(triggers) == 1
    assert triggers[0].get("action_kind") == "weather_stub"
    assert float(triggers[0].get("gain", 0.0) or 0.0) >= 0.60
    params = triggers[0].get("params") or {}
    assert params.get("target_ref_object_id") == "ctx_input_current"
    assert params.get("target_item_id") == "ctx_input_current"
    assert triggers[0].get("target_binding_applied") is True


def test_default_weather_only_rule_stays_weak_for_plain_weather_mention() -> None:
    doc = _load_default_rules_doc()

    engine = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[],
        context={
            "pool_items": [
                {
                    "item_id": "ctx_input_current",
                    "ref_object_id": "ctx_input_current",
                    "ref_object_type": "input",
                    "display": "【用户消息】今天的天气有点奇怪，我一会儿再想想要不要出门。",
                    "display_detail": "",
                    "input_is_user": 1,
                    "input_is_message": 1,
                    "input_is_system": 0,
                    "input_is_session_restore": 0,
                }
            ]
        },
        now_ms=123,
        runtime_state={},
    )

    triggered_rule_ids = {str(item.get("rule_id", "") or "") for item in (engine.get("triggered_rules") or [])}
    assert "innate_action_weather_stub_from_weather_only" in triggered_rule_ids
    assert "innate_action_weather_stub_from_query_weather" not in triggered_rule_ids
    assert "innate_action_weather_stub_from_weather_question" not in triggered_rule_ids
    triggers = ((engine.get("directives") or {}).get("action_triggers") or [])
    assert len(triggers) == 1
    assert triggers[0].get("action_kind") == "weather_stub"
    assert float(triggers[0].get("gain", 0.0) or 0.0) == 0.35
    params = triggers[0].get("params") or {}
    assert params.get("target_ref_object_id") == "ctx_input_current"
    assert params.get("target_item_id") == "ctx_input_current"
    assert triggers[0].get("target_binding_applied") is True


def test_state_window_predicate_and_emit_script_action() -> None:
    doc = _normalize(
        {
            "rules_schema_version": "1.0",
            "rules_version": "t",
            "enabled": True,
            "defaults": {},
            "rules": [
                {
                    "id": "sw_emit",
                    "title": "StateWindow -> emit_script",
                    "enabled": True,
                    "priority": 10,
                    "cooldown_ticks": 0,
                    "when": {"state_window": {"stage": "maintenance", "fast_cp_rise_min": 2}},
                    "then": [{"emit_script": {"script_id": "innate_state_window_cp_rise", "script_kind": "window_trigger", "trigger": "fast_cp_rise"}}],
                    "note": "",
                }
            ],
        }
    )

    packet = {"summary": {"fast_cp_rise_item_count": 2, "fast_cp_drop_item_count": 0}, "candidate_triggers": []}
    engine = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[{"stage": "maintenance", "packet": packet}],
        now_ms=100,
        runtime_state={},
    )
    scripts = engine.get("triggered_scripts") or []
    assert len(scripts) == 1
    assert scripts[0].get("script_id") == "innate_state_window_cp_rise"


def test_focus_from_state_window_candidates() -> None:
    doc = _normalize(
        {
            "rules_schema_version": "1.0",
            "rules_version": "t",
            "enabled": True,
            "defaults": {"focus_directive": {"ttl_ticks": 2, "focus_boost": 0.9, "deduplicate_by": "target_item_id"}},
            "rules": [
                {
                    "id": "sw_focus",
                    "title": "StateWindow candidates -> focus",
                    "enabled": True,
                    "priority": 10,
                    "cooldown_ticks": 0,
                    "when": {"state_window": {"stage": "any", "fast_cp_rise_min": 1}},
                    "then": [{"focus": {"from": "state_window_candidates", "match_policy": "all", "deduplicate_by": "target_item_id"}}],
                    "note": "",
                }
            ],
        }
    )

    packet = {
        "summary": {"fast_cp_rise_item_count": 1, "fast_cp_drop_item_count": 0},
        "candidate_triggers": [
            {"item_id": "spi_0001", "trigger_hint": "fast_cp_rise", "value": 0.7, "display": "candidate A"},
        ],
    }
    engine = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[{"stage": "maintenance", "packet": packet}],
        now_ms=100,
        runtime_state={},
    )
    directives = (engine.get("directives") or {}).get("focus_directives") or []
    assert len(directives) == 1
    assert directives[0].get("target_item_id") == "spi_0001"


def test_correct_event_binds_positive_correctness_attribute() -> None:
    doc = _normalize(
        {
            "rules_schema_version": "1.0",
            "rules_version": "t",
            "enabled": True,
            "defaults": {},
            "rules": [
                {
                    "id": "correctness_bind",
                    "title": "correct event -> correctness",
                    "enabled": True,
                    "phase": "cfs",
                    "priority": 10,
                    "cooldown_ticks": 0,
                    "when": {"timer": {"at_tick": 1}},
                    "then": [
                        {
                            "cfs_emit": {
                                "kind": "correct_event",
                                "from": "single",
                                "scope": "object",
                                "strength": 0.7,
                                "target": {
                                    "from": "specific_item",
                                    "item_id": "spi_correct",
                                    "display": "correct target",
                                },
                                "bind_attributes": [
                                    {
                                        "attribute_name": "cfs_correct_event",
                                        "display": "????:{{{strength}}}",
                                        "value_from": "strength",
                                        "value_type": "numerical",
                                        "modality": "internal",
                                        "er": "{{{strength}}}",
                                        "ev": 0.0,
                                    },
                                    {
                                        "attribute_name": "cfs_correctness",
                                        "display": "???:{{{strength}}}",
                                        "value_from": "strength",
                                        "value_type": "numerical",
                                        "modality": "internal",
                                        "er": "{{{strength}}}",
                                        "ev": 0.0,
                                    },
                                ],

                            }
                        }
                    ],
                    "note": "",
                }
            ],
        }
    )

    engine = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[],
        now_ms=100,
        runtime_state={},
        allow_timer=True,
    )
    effects = (engine.get("directives") or {}).get("pool_effects") or []
    by_name = {((e.get("spec") or {}).get("attribute") or {}).get("attribute_name"): e for e in effects}
    assert "cfs_correct_event" in by_name
    assert "cfs_correctness" in by_name
    attr = by_name["cfs_correctness"]["spec"]["attribute"]
    assert attr["attribute_value"] == 0.7
    assert attr["er"] == 0.7
    assert attr["ev"] == 0.0


def test_default_pressure_rule_prefers_packet_punish_signal() -> None:
    doc = _load_default_rules_doc()

    engine = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[],
        now_ms=100,
        runtime_state={},
        context={
            "pool": {"total_er": 0.15, "total_ev": 0.85, "total_energy": 1.0, "item_count": 1},
            "pool_items": [
                {
                    "item_id": "spi_pressure",
                    "ref_object_id": "st_pressure",
                    "ref_object_type": "st",
                    "display": "pressure target",
                    "er": 0.05,
                    "ev": 0.85,
                    "cp_delta": -0.8,
                    "cp_abs": 0.8,
                    "total_energy": 0.9,
                    "runtime_attribute_names": [],
                    "packet_attribute_names": ["punish_signal"],
                }
            ],
            "cam": {"size": 1, "energy_concentration": 1.0},
            "memory_activation": {"item_count": 0, "total_ev": 0.0},
            "emotion": {"nt": {}, "rwd": 0.0, "pun": 0.0},
            "stimulus": {"residual_ratio": 0.0, "input_is_empty": 1, "input_has_text": 0},
            "retrieval": {"stimulus": {"best_match_score": 0.0}, "structure": {"best_match_score": 0.0}},
        },
    )

    cfs_out = ((engine.get("directives") or {}).get("cfs_signals") or [])
    pressure = [row for row in cfs_out if str(row.get("kind", "")) == "pressure"]
    assert pressure, cfs_out
    assert float(pressure[0].get("strength", 0.0) or 0.0) >= 0.3


def test_default_pressure_rule_accepts_teacher_packet_punish_signal() -> None:
    doc = _load_default_rules_doc()

    engine = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[],
        now_ms=100,
        runtime_state={},
        context={
            "pool": {"total_er": 0.15, "total_ev": 0.85, "total_energy": 1.0, "item_count": 1},
            "pool_items": [
                {
                    "item_id": "spi_pressure_teacher",
                    "ref_object_id": "st_pressure_teacher",
                    "ref_object_type": "st",
                    "display": "teacher pressure target",
                    "er": 0.05,
                    "ev": 0.85,
                    "cp_delta": -0.8,
                    "cp_abs": 0.8,
                    "total_energy": 0.9,
                    "runtime_attribute_names": [],
                    "packet_attribute_names": ["teacher_punish_signal"],
                }
            ],
            "cam": {"size": 1, "energy_concentration": 1.0},
            "memory_activation": {"item_count": 0, "total_ev": 0.0},
            "emotion": {"nt": {}, "rwd": 0.0, "pun": 0.0},
            "stimulus": {"residual_ratio": 0.0, "input_is_empty": 1, "input_has_text": 0},
            "retrieval": {"stimulus": {"best_match_score": 0.0}, "structure": {"best_match_score": 0.0}},
        },
    )

    cfs_out = ((engine.get("directives") or {}).get("cfs_signals") or [])
    pressure = [row for row in cfs_out if str(row.get("kind", "")) == "pressure"]
    assert pressure, cfs_out
    assert float(pressure[0].get("strength", 0.0) or 0.0) >= 0.3


def test_default_pressure_runtime_fallback_is_weaker_and_structure_only() -> None:
    doc = _load_default_rules_doc()

    base_context = {
        "pool": {"total_er": 0.15, "total_ev": 0.90, "total_energy": 1.05, "item_count": 1},
        "cam": {"size": 1, "energy_concentration": 1.0},
        "memory_activation": {"item_count": 0, "total_ev": 0.0},
        "emotion": {"nt": {}, "rwd": 0.0, "pun": 0.0},
        "stimulus": {"residual_ratio": 0.0, "input_is_empty": 1, "input_has_text": 0},
        "retrieval": {"stimulus": {"best_match_score": 0.0}, "structure": {"best_match_score": 0.0}},
    }

    st_engine = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[],
        now_ms=100,
        runtime_state={},
        context={
            **base_context,
            "pool_items": [
                {
                    "item_id": "spi_pressure_runtime",
                    "ref_object_id": "st_pressure_runtime",
                    "ref_object_type": "st",
                    "display": "pressure runtime target",
                    "er": 0.05,
                    "ev": 0.9,
                    "cp_delta": -0.85,
                    "cp_abs": 0.85,
                    "total_energy": 0.95,
                    "runtime_attribute_names": ["punish_signal"],
                    "packet_attribute_names": [],
                }
            ],
        },
    )
    st_cfs = ((st_engine.get("directives") or {}).get("cfs_signals") or [])
    st_pressure = [row for row in st_cfs if str(row.get("kind", "")) == "pressure"]
    assert st_pressure, st_cfs
    assert float(st_pressure[0].get("strength", 0.0) or 0.0) < 0.65

    sa_engine = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[],
        now_ms=100,
        runtime_state={},
        context={
            **base_context,
            "pool_items": [
                {
                    "item_id": "spi_pressure_runtime_sa",
                    "ref_object_id": "sa_pressure_runtime",
                    "ref_object_type": "sa",
                    "display": "pressure runtime sa",
                    "er": 0.05,
                    "ev": 0.9,
                    "cp_delta": -0.85,
                    "cp_abs": 0.85,
                    "total_energy": 0.95,
                    "runtime_attribute_names": ["punish_signal"],
                    "packet_attribute_names": [],
                }
            ],
        },
    )
    sa_cfs = ((sa_engine.get("directives") or {}).get("cfs_signals") or [])
    sa_pressure = [row for row in sa_cfs if str(row.get("kind", "")) == "pressure"]
    assert not sa_pressure, sa_cfs


def test_default_expectation_rule_can_emit_verified_when_er_rate_catches_up() -> None:
    doc = _load_default_rules_doc()

    def _ctx(er: float, ev: float = 0.4) -> dict:
        total = float(er + ev)
        return {
            "pool": {"total_er": er, "total_ev": ev, "total_energy": total, "item_count": 1},
            "pool_items": [
                {
                    "item_id": "spi_expect",
                    "ref_object_id": "st_expect",
                    "ref_object_type": "st",
                    "display": "expect target",
                    "verification_anchor_item_id": "spi_expect",
                    "verification_anchor_ref_object_id": "st_expect",
                    "verification_anchor_ref_object_type": "st",
                    "verification_anchor_display": "expect target",
                    "er": er,
                    "ev": ev,
                    "cp_delta": er - ev,
                    "cp_abs": abs(er - ev),
                    "total_energy": total,
                    "packet_attribute_names": ["reward_signal"],
                    "runtime_attribute_names": [],
                    "all_attribute_names": ["reward_signal"],
                }
            ],
            "cam": {"size": 1, "energy_concentration": 1.0},
            "memory_activation": {"item_count": 0, "total_ev": 0.0},
            "emotion": {"nt": {}, "rwd": 0.0, "pun": 0.0},
            "stimulus": {"residual_ratio": 0.0, "input_is_empty": 0, "input_has_text": 1},
            "retrieval": {"stimulus": {"best_match_score": 0.0}, "structure": {"best_match_score": 0.0}},
        }

    runtime_state: dict = {}
    for tick_index, er in enumerate([0.0, 0.15, 0.3, 0.45], start=1):
        evaluate_rules(
            doc=doc,
            trace_id="t",
            tick_id=f"cycle_{tick_index:04d}",
            tick_index=tick_index,
            cfs_signals=[],
            state_windows=[],
            now_ms=100 * tick_index,
            runtime_state=runtime_state,
            context=_ctx(er=er),
        )

    verified_tick = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0005",
        tick_index=5,
        cfs_signals=[],
        state_windows=[],
        now_ms=500,
        runtime_state=runtime_state,
        context=_ctx(er=0.8),
    )

    cfs_out = ((verified_tick.get("directives") or {}).get("cfs_signals") or [])
    by_kind = {str(row.get("kind", "")): row for row in cfs_out if isinstance(row, dict)}
    assert "expectation" in by_kind, cfs_out
    assert "expectation_verified" in by_kind, cfs_out
    assert "expectation_unverified" in by_kind, cfs_out
    base_strength = float(by_kind["expectation"].get("strength", 0.0) or 0.0)
    verified_strength = float(by_kind["expectation_verified"].get("strength", 0.0) or 0.0)
    unverified_strength = float(by_kind["expectation_unverified"].get("strength", 0.0) or 0.0)
    assert base_strength > 0.0
    assert verified_strength > 0.0
    assert verified_strength > unverified_strength


def test_default_expectation_rule_accepts_teacher_packet_reward_signal() -> None:
    doc = _load_default_rules_doc()

    runtime_state: dict = {}
    for tick_index, er in enumerate([0.0, 0.15, 0.3, 0.45], start=1):
        evaluate_rules(
            doc=doc,
            trace_id="t",
            tick_id=f"cycle_{tick_index:04d}",
            tick_index=tick_index,
            cfs_signals=[],
            state_windows=[],
            now_ms=100 * tick_index,
            runtime_state=runtime_state,
            context={
                "pool": {"total_er": er, "total_ev": 0.4, "total_energy": er + 0.4, "item_count": 1},
                "pool_items": [
                    {
                        "item_id": "spi_expect_teacher",
                        "ref_object_id": "st_expect_teacher",
                        "ref_object_type": "st",
                        "display": "teacher expect target",
                        "verification_anchor_item_id": "spi_expect_teacher",
                        "verification_anchor_ref_object_id": "st_expect_teacher",
                        "verification_anchor_ref_object_type": "st",
                        "verification_anchor_display": "teacher expect target",
                        "er": er,
                        "ev": 0.4,
                        "cp_delta": er - 0.4,
                        "cp_abs": abs(er - 0.4),
                        "total_energy": er + 0.4,
                        "packet_attribute_names": ["teacher_reward_signal"],
                        "runtime_attribute_names": [],
                        "all_attribute_names": ["teacher_reward_signal"],
                    }
                ],
                "cam": {"size": 1, "energy_concentration": 1.0},
                "memory_activation": {"item_count": 0, "total_ev": 0.0},
                "emotion": {"nt": {}, "rwd": 0.0, "pun": 0.0},
                "stimulus": {"residual_ratio": 0.0, "input_is_empty": 0, "input_has_text": 1},
                "retrieval": {"stimulus": {"best_match_score": 0.0}, "structure": {"best_match_score": 0.0}},
            },
        )

    verified_tick = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0005",
        tick_index=5,
        cfs_signals=[],
        state_windows=[],
        now_ms=500,
        runtime_state=runtime_state,
        context={
            "pool": {"total_er": 0.8, "total_ev": 0.4, "total_energy": 1.2, "item_count": 1},
            "pool_items": [
                {
                    "item_id": "spi_expect_teacher",
                    "ref_object_id": "st_expect_teacher",
                    "ref_object_type": "st",
                    "display": "teacher expect target",
                    "verification_anchor_item_id": "spi_expect_teacher",
                    "verification_anchor_ref_object_id": "st_expect_teacher",
                    "verification_anchor_ref_object_type": "st",
                    "verification_anchor_display": "teacher expect target",
                    "er": 0.8,
                    "ev": 0.4,
                    "cp_delta": 0.4,
                    "cp_abs": 0.4,
                    "total_energy": 1.2,
                    "packet_attribute_names": ["teacher_reward_signal"],
                    "runtime_attribute_names": [],
                    "all_attribute_names": ["teacher_reward_signal"],
                }
            ],
            "cam": {"size": 1, "energy_concentration": 1.0},
            "memory_activation": {"item_count": 0, "total_ev": 0.0},
            "emotion": {"nt": {}, "rwd": 0.0, "pun": 0.0},
            "stimulus": {"residual_ratio": 0.0, "input_is_empty": 0, "input_has_text": 1},
            "retrieval": {"stimulus": {"best_match_score": 0.0}, "structure": {"best_match_score": 0.0}},
        },
    )

    cfs_out = ((verified_tick.get("directives") or {}).get("cfs_signals") or [])
    by_kind = {str(row.get("kind", "")): row for row in cfs_out if isinstance(row, dict)}
    assert "expectation_verified" in by_kind, cfs_out
    assert "expectation_unverified" in by_kind, cfs_out
    assert float(by_kind["expectation_verified"].get("strength", 0.0) or 0.0) > 0.0


def test_default_surprise_rule_skips_empty_input_ticks() -> None:
    doc = _load_default_rules_doc()

    empty_tick = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[],
        now_ms=100,
        runtime_state={},
        context={
            "pool": {"total_er": 1.0, "total_ev": 0.1, "total_energy": 1.1, "item_count": 1},
            "pool_items": [
                {
                    "item_id": "spi_surprise",
                    "ref_object_id": "st_surprise",
                    "ref_object_type": "st",
                    "display": "surprise target",
                    "er": 0.9,
                    "ev": 0.1,
                    "cp_delta": 0.9,
                    "cp_abs": 0.9,
                    "delta_er": 0.9,
                    "total_energy": 1.0,
                    "input_is_empty": 1,
                }
            ],
            "cam": {"size": 1, "energy_concentration": 1.0},
            "memory_activation": {"item_count": 0, "total_ev": 0.0},
            "emotion": {"nt": {}, "rwd": 0.0, "pun": 0.0},
            "stimulus": {"residual_ratio": 0.0, "input_is_empty": 1, "input_has_text": 0},
            "retrieval": {"stimulus": {"best_match_score": 0.0}, "structure": {"best_match_score": 0.0}},
        },
    )
    empty_kinds = [str(row.get("kind", "")) for row in (((empty_tick.get("directives") or {}).get("cfs_signals") or []))]
    assert "surprise" not in empty_kinds

    non_empty_tick = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0002",
        tick_index=2,
        cfs_signals=[],
        state_windows=[],
        now_ms=100,
        runtime_state={},
        context={
            "pool": {"total_er": 1.0, "total_ev": 0.1, "total_energy": 1.1, "item_count": 1},
            "pool_items": [
                {
                    "item_id": "spi_surprise",
                    "ref_object_id": "st_surprise",
                    "ref_object_type": "st",
                    "display": "surprise target",
                    "er": 0.9,
                    "ev": 0.1,
                    "cp_delta": 0.9,
                    "cp_abs": 0.9,
                    "delta_er": 0.9,
                    "total_energy": 1.0,
                    "input_is_empty": 0,
                }
            ],
            "cam": {"size": 1, "energy_concentration": 1.0},
            "memory_activation": {"item_count": 0, "total_ev": 0.0},
            "emotion": {"nt": {}, "rwd": 0.0, "pun": 0.0},
            "stimulus": {"residual_ratio": 0.0, "input_is_empty": 0, "input_has_text": 1},
            "retrieval": {"stimulus": {"best_match_score": 0.0}, "structure": {"best_match_score": 0.0}},
        },
    )
    non_empty_kinds = [str(row.get("kind", "")) for row in (((non_empty_tick.get("directives") or {}).get("cfs_signals") or []))]
    assert "surprise" in non_empty_kinds


def test_default_correct_event_requires_current_cp_abs_to_settle() -> None:
    doc = _load_default_rules_doc()

    def _ctx(cp_abs: float, delta_cp_abs: float) -> dict:
        return {
            "pool": {"total_er": 0.2, "total_ev": 0.8, "total_energy": 1.0, "item_count": 1},
            "pool_items": [
                {
                    "item_id": "spi_correct",
                    "ref_object_id": "st_correct",
                    "ref_object_type": "st",
                    "display": "correct target",
                    "er": 0.2,
                    "ev": 0.8,
                    "cp_delta": -0.6,
                    "cp_abs": cp_abs,
                    "delta_cp_abs": delta_cp_abs,
                    "total_energy": 1.0,
                    "input_is_empty": 1,
                }
            ],
            "cam": {"size": 1, "energy_concentration": 1.0},
            "memory_activation": {"item_count": 0, "total_ev": 0.0},
            "emotion": {"nt": {}, "rwd": 0.0, "pun": 0.0},
            "stimulus": {"residual_ratio": 0.0, "input_is_empty": 1, "input_has_text": 0},
            "retrieval": {"stimulus": {"best_match_score": 0.0}, "structure": {"best_match_score": 0.0}},
        }

    runtime_state_unsettled: dict = {}
    evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[],
        now_ms=100,
        runtime_state=runtime_state_unsettled,
        context=_ctx(cp_abs=1.1, delta_cp_abs=0.0),
    )
    unsettled = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0002",
        tick_index=2,
        cfs_signals=[],
        state_windows=[],
        now_ms=100,
        runtime_state=runtime_state_unsettled,
        context=_ctx(cp_abs=0.8, delta_cp_abs=-0.9),
    )
    unsettled_kinds = [str(row.get("kind", "")) for row in (((unsettled.get("directives") or {}).get("cfs_signals") or []))]
    assert "correct_event" not in unsettled_kinds

    runtime_state_settled: dict = {}
    evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[],
        now_ms=100,
        runtime_state=runtime_state_settled,
        context=_ctx(cp_abs=1.1, delta_cp_abs=0.0),
    )
    settled = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_0002",
        tick_index=2,
        cfs_signals=[],
        state_windows=[],
        now_ms=100,
        runtime_state=runtime_state_settled,
        context=_ctx(cp_abs=0.3, delta_cp_abs=-0.9),
    )
    settled_kinds = [str(row.get("kind", "")) for row in (((settled.get("directives") or {}).get("cfs_signals") or []))]
    assert "correct_event" in settled_kinds


def test_default_relief_can_appear_before_full_correct_event() -> None:
    doc = _load_default_rules_doc()

    def _ctx(cp_abs: float, delta_cp_abs: float, punish: float = 0.12) -> dict:
        return {
            "pool": {"total_er": 0.2, "total_ev": 0.8, "total_energy": 1.0, "item_count": 1},
            "pool_items": [
                {
                    "item_id": "spi_relief",
                    "ref_object_id": "st_relief",
                    "ref_object_type": "st",
                    "display": "relief target",
                    "er": 0.2,
                    "ev": 0.8,
                    "cp_delta": -0.6,
                    "cp_abs": cp_abs,
                    "delta_cp_abs": delta_cp_abs,
                    "total_energy": 1.0,
                    "input_is_empty": 1,
                }
            ],
            "cam": {"size": 1, "energy_concentration": 1.0},
            "memory_activation": {"item_count": 0, "total_ev": 0.0},
            "emotion": {"nt": {}, "rwd": 0.0, "pun": punish},
            "stimulus": {"residual_ratio": 0.0, "input_is_empty": 1, "input_has_text": 0},
            "retrieval": {"stimulus": {"best_match_score": 0.0, "grasp_score": 0.0}, "structure": {"best_match_score": 0.0}},
        }

    runtime_state: dict = {}
    evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_relief_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[],
        now_ms=100,
        runtime_state=runtime_state,
        context=_ctx(cp_abs=1.08, delta_cp_abs=0.0),
    )
    recovered = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_relief_0002",
        tick_index=2,
        cfs_signals=[],
        state_windows=[],
        now_ms=100,
        runtime_state=runtime_state,
        context=_ctx(cp_abs=0.48, delta_cp_abs=-0.62),
    )
    recovered_kinds = [str(row.get("kind", "")) for row in (((recovered.get("directives") or {}).get("cfs_signals") or []))]
    assert "relief" in recovered_kinds
    assert "correct_event" not in recovered_kinds


def test_default_reassurance_requires_settle_grasp_and_low_complexity() -> None:
    doc = _load_default_rules_doc()

    def _ctx(
        cp_abs: float,
        delta_cp_abs: float,
        *,
        grasp_score: float,
        core_complexity_score: float,
        punish: float,
    ) -> dict:
        return {
            "pool": {
                "total_er": 0.35,
                "total_ev": 0.55,
                "total_energy": 0.90,
                "item_count": 2,
                "complexity_score": core_complexity_score,
                "core_complexity_score": core_complexity_score,
                "total_cp_abs": cp_abs,
            },
            "pool_items": [
                {
                    "item_id": "spi_reassure",
                    "ref_object_id": "st_reassure",
                    "ref_object_type": "st",
                    "display": "reassurance target",
                    "er": 0.35,
                    "ev": 0.55,
                    "cp_delta": -0.20,
                    "cp_abs": cp_abs,
                    "delta_cp_abs": delta_cp_abs,
                    "total_energy": 0.90,
                    "input_is_empty": 1,
                    "fatigue": 0.05,
                }
            ],
            "cam": {"size": 2, "energy_concentration": 0.78},
            "memory_activation": {"item_count": 0, "total_ev": 0.0},
            "emotion": {"nt": {}, "rwd": 0.12, "pun": punish},
            "stimulus": {"residual_ratio": 0.0, "input_is_empty": 1, "input_has_text": 0},
            "retrieval": {"stimulus": {"best_match_score": 0.58, "grasp_score": grasp_score}, "structure": {"best_match_score": 0.0}},
        }

    runtime_state_ok: dict = {}
    evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_reassure_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[],
        now_ms=100,
        runtime_state=runtime_state_ok,
        context=_ctx(cp_abs=1.02, delta_cp_abs=0.0, grasp_score=0.0, core_complexity_score=0.52, punish=0.08),
    )
    ok = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_reassure_0002",
        tick_index=2,
        cfs_signals=[],
        state_windows=[],
        now_ms=100,
        runtime_state=runtime_state_ok,
        context=_ctx(cp_abs=0.30, delta_cp_abs=-0.74, grasp_score=0.48, core_complexity_score=0.22, punish=0.18),
    )
    ok_kinds = [str(row.get("kind", "")) for row in (((ok.get("directives") or {}).get("cfs_signals") or []))]
    assert "reassurance" in ok_kinds

    runtime_state_blocked: dict = {}
    evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_reassure_block_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[],
        now_ms=100,
        runtime_state=runtime_state_blocked,
        context=_ctx(cp_abs=1.02, delta_cp_abs=0.0, grasp_score=0.0, core_complexity_score=0.52, punish=0.08),
    )
    blocked = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_reassure_block_0002",
        tick_index=2,
        cfs_signals=[],
        state_windows=[],
        now_ms=100,
        runtime_state=runtime_state_blocked,
        context=_ctx(cp_abs=0.30, delta_cp_abs=-0.74, grasp_score=0.48, core_complexity_score=0.22, punish=0.72),
    )
    blocked_kinds = [str(row.get("kind", "")) for row in (((blocked.get("directives") or {}).get("cfs_signals") or []))]
    assert "reassurance" not in blocked_kinds


def test_default_simplicity_requires_low_complexity_and_low_punish() -> None:
    doc = _load_default_rules_doc()

    base_context = {
        "pool": {
            "total_er": 0.6,
            "total_ev": 0.2,
            "total_energy": 0.8,
            "item_count": 2,
            "total_cp_abs": 0.4,
            "energy_concentration": 0.7,
            "effective_peak_count": 1.3,
            "complexity_score": 0.18,
            "core_complexity_score": 0.18,
        },
        "pool_items": [
            {
                "item_id": "spi_simple",
                "ref_object_id": "st_simple",
                "ref_object_type": "st",
                "display": "simple target",
                "er": 0.6,
                "ev": 0.2,
                "cp_delta": 0.4,
                "cp_abs": 0.4,
                "delta_cp_abs": -0.05,
                "total_energy": 0.8,
                "input_is_empty": 0,
                "fatigue": 0.1,
            }
        ],
        "cam": {"size": 2, "energy_concentration": 0.8},
        "memory_activation": {"item_count": 0, "total_ev": 0.0},
        "emotion": {"nt": {}, "rwd": 0.1, "pun": 0.12},
        "stimulus": {"residual_ratio": 0.18, "input_is_empty": 0, "input_has_text": 1},
        "retrieval": {"stimulus": {"best_match_score": 0.66, "grasp_score": 0.52}, "structure": {"best_match_score": 0.0}},
    }

    ok = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_1001",
        tick_index=1001,
        cfs_signals=[],
        state_windows=[],
        now_ms=100,
        runtime_state={},
        context=base_context,
    )
    ok_kinds = [str(row.get("kind", "")) for row in (((ok.get("directives") or {}).get("cfs_signals") or []))]
    assert "simplicity" in ok_kinds

    blocked_context = dict(base_context)
    blocked_context["emotion"] = {"nt": {}, "rwd": 0.1, "pun": 0.72}
    blocked = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_1002",
        tick_index=1002,
        cfs_signals=[],
        state_windows=[],
        now_ms=100,
        runtime_state={},
        context=blocked_context,
    )
    blocked_kinds = [str(row.get("kind", "")) for row in (((blocked.get("directives") or {}).get("cfs_signals") or []))]
    assert "simplicity" not in blocked_kinds


def test_default_repetition_emits_global_signal_and_live_bind() -> None:
    doc = _load_default_rules_doc()

    context = {
        "pool": {
            "total_er": 0.7,
            "total_ev": 0.4,
            "total_energy": 1.1,
            "item_count": 3,
            "total_cp_abs": 0.8,
            "energy_concentration": 0.62,
            "effective_peak_count": 2.0,
        },
        "pool_items": [
            {
                "item_id": "spi_repeat",
                "ref_object_id": "st_repeat",
                "ref_object_type": "st",
                "display": "repeat target",
                "er": 0.6,
                "ev": 0.4,
                "cp_delta": 0.3,
                "cp_abs": 0.3,
                "total_energy": 1.0,
                "fatigue": 0.82,
            }
        ],
        "cam": {"size": 3, "energy_concentration": 0.62},
        "memory_activation": {"item_count": 0, "total_ev": 0.0},
        "emotion": {"nt": {}, "rwd": 0.0, "pun": 0.0},
        "stimulus": {"residual_ratio": 0.2, "input_is_empty": 0, "input_has_text": 1},
        "retrieval": {"stimulus": {"best_match_score": 0.0, "grasp_score": 0.0}, "structure": {"best_match_score": 0.0}},
    }

    result = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_1101",
        tick_index=1101,
        cfs_signals=[],
        state_windows=[],
        context=context,
        now_ms=123,
        runtime_state={},
        allow_timer=True,
        allowed_phases=["cfs"],
    )

    directives = result.get("directives") or {}
    cfs_signals = directives.get("cfs_signals") or []
    repetition = [row for row in cfs_signals if str(row.get("kind", "")) == "repetition"]
    assert repetition, "expected repetition cfs signal"
    assert float(repetition[0].get("strength", 0.0) or 0.0) > 0.4

    pool_effects = directives.get("pool_effects") or []
    repetition_bind = [
        row for row in pool_effects
        if str(row.get("effect_type", "")) == "pool_bind_attribute"
        and str(((row.get("spec") or {}).get("attribute") or {}).get("attribute_name", "")) == "cfs_repetition"
    ]
    assert repetition_bind, "expected repetition live bind effect"
    attr = ((repetition_bind[0].get("spec") or {}).get("attribute") or {})
    assert float(attr.get("er", 0.0) or 0.0) > 0.4


def _signal_strength(result: dict, kind: str) -> float:
    signals = ((result.get("directives") or {}).get("cfs_signals") or [])
    matches = [row for row in signals if str(row.get("kind", "")) == kind]
    assert matches, f"expected {kind} cfs signal"
    return float(matches[0].get("strength", 0.0) or 0.0)


def test_default_anthropomorphic_cfs_rules_emit_dynamic_strengths() -> None:
    doc = _load_default_rules_doc()

    def _ctx(*, grasp: float, residual: float, match: float, cp_abs: float) -> dict:
        return {
            "pool": {
                "total_er": 0.8,
                "total_ev": 0.4,
                "total_energy": 1.2,
                "item_count": 3,
                "total_cp_abs": cp_abs,
                "energy_concentration": 0.68,
                "effective_peak_count": 2.0,
                "complexity_score": 0.34,
                "core_complexity_score": 0.34,
            },
            "pool_items": [
                {
                    "item_id": "spi_cfs_probe",
                    "ref_object_id": "st_cfs_probe",
                    "ref_object_type": "st",
                    "display": "cfs probe",
                    "er": 0.8,
                    "ev": 0.4,
                    "cp_delta": cp_abs,
                    "cp_abs": cp_abs,
                    "total_energy": 1.2,
                    "fatigue": 0.1,
                }
            ],
            "cam": {"size": 3, "energy_concentration": 0.68},
            "memory_activation": {"item_count": 0, "total_ev": 0.0},
            "emotion": {"nt": {}, "rwd": 0.04, "pun": 0.08},
            "stimulus": {"residual_ratio": residual, "input_is_empty": 0, "input_has_text": 1},
            "retrieval": {"stimulus": {"best_match_score": match, "grasp_score": grasp}, "structure": {"best_match_score": 0.0}},
        }

    low = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_anthro_low_0001",
        tick_index=1,
        cfs_signals=[],
        state_windows=[],
        context=_ctx(grasp=0.58, residual=0.22, match=0.58, cp_abs=0.32),
        now_ms=123,
        runtime_state={},
        allow_timer=True,
        allowed_phases=["cfs"],
    )
    high = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_anthro_high_0002",
        tick_index=2,
        cfs_signals=[],
        state_windows=[],
        context=_ctx(grasp=0.82, residual=0.48, match=0.78, cp_abs=0.72),
        now_ms=123,
        runtime_state={},
        allow_timer=True,
        allowed_phases=["cfs"],
    )

    assert _signal_strength(high, "familiarity") > _signal_strength(low, "familiarity")
    assert _signal_strength(high, "curiosity") > _signal_strength(low, "curiosity")
    assert _signal_strength(high, "uncanny_valley") > _signal_strength(low, "uncanny_valley")


def test_default_deja_vu_requires_familiarity_without_memory_evidence() -> None:
    doc = _load_default_rules_doc()

    def _ctx(memory_count: int) -> dict:
        return {
            "pool": {
                "total_er": 0.7,
                "total_ev": 0.5,
                "total_energy": 1.2,
                "item_count": 4,
                "total_cp_abs": 0.62,
                "energy_concentration": 0.58,
                "effective_peak_count": 2.4,
                "complexity_score": 0.42,
                "core_complexity_score": 0.42,
            },
            "pool_items": [
                {
                    "item_id": "spi_deja_vu_probe",
                    "ref_object_id": "st_deja_vu_probe",
                    "ref_object_type": "st",
                    "display": "deja vu probe",
                    "er": 0.7,
                    "ev": 0.5,
                    "cp_delta": 0.62,
                    "cp_abs": 0.62,
                    "total_energy": 1.2,
                    "fatigue": 0.12,
                }
            ],
            "cam": {"size": 4, "energy_concentration": 0.58},
            "memory_activation": {"item_count": memory_count, "total_ev": 0.4 if memory_count else 0.0},
            "emotion": {"nt": {}, "rwd": 0.0, "pun": 0.0},
            "stimulus": {"residual_ratio": 0.26, "input_is_empty": 0, "input_has_text": 1},
            "retrieval": {"stimulus": {"best_match_score": 0.0, "grasp_score": 0.0}, "structure": {"best_match_score": 0.0}},
        }

    no_memory = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_deja_vu_nomem_0001",
        tick_index=1,
        cfs_signals=[{"kind": "familiarity", "strength": 0.66}],
        state_windows=[],
        context=_ctx(memory_count=0),
        now_ms=123,
        runtime_state={},
        allow_timer=True,
        allowed_phases=["cfs"],
    )
    with_memory = evaluate_rules(
        doc=doc,
        trace_id="t",
        tick_id="cycle_deja_vu_mem_0002",
        tick_index=2,
        cfs_signals=[{"kind": "familiarity", "strength": 0.66}],
        state_windows=[],
        context=_ctx(memory_count=1),
        now_ms=123,
        runtime_state={},
        allow_timer=True,
        allowed_phases=["cfs"],
    )

    assert _signal_strength(no_memory, "deja_vu") > 0.5
    with_memory_kinds = [str(row.get("kind", "")) for row in (((with_memory.get("directives") or {}).get("cfs_signals") or []))]
    assert "deja_vu" not in with_memory_kinds


def test_default_anthropomorphic_nt_updates_scale_with_cfs_strength() -> None:
    doc = _load_default_rules_doc()

    def _updates(strength: float) -> dict:
        result = evaluate_rules(
            doc=doc,
            trace_id="t",
            tick_id=f"cycle_nt_curiosity_{int(strength * 1000):04d}",
            tick_index=int(strength * 1000),
            cfs_signals=[{"kind": "curiosity", "strength": strength}],
            state_windows=[],
            context={},
            now_ms=123,
            runtime_state={},
            allow_timer=True,
            allowed_phases=["directives"],
        )
        return ((result.get("directives") or {}).get("emotion_updates") or {})

    low = _updates(0.25)
    high = _updates(0.75)

    assert float(high.get("NOV", 0.0)) == pytest.approx(float(low.get("NOV", 0.0)) * 3)
    assert float(high.get("DA", 0.0)) == pytest.approx(float(low.get("DA", 0.0)) * 3)
    assert float(high.get("COR", 0.0)) == pytest.approx(float(low.get("COR", 0.0)) * 3)
