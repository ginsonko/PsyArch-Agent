# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from emotion import EmotionManager


def test_default_channels_include_focus_and_novelty() -> None:
    mgr = EmotionManager()
    try:
        snapshot = mgr.get_emotion_snapshot(trace_id="emotion_test_default").get("data", {}) or {}
        channels = ((snapshot.get("nt_state_snapshot", {}) or {}).get("channels", {}) or {})
        assert "NOV" in channels
        assert "FOC" in channels
        assert len(channels) >= 8
    finally:
        mgr.close()


def test_cfs_updates_raise_new_and_existing_channels() -> None:
    mgr = EmotionManager(config_override={"cfs_to_nt_source_mode": "builtin"})
    try:
        result = mgr.update_emotion_state(
            {
                "cfs_signals": [
                    {"kind": "surprise", "strength": 0.80},
                    {"kind": "pressure", "strength": 0.65},
                    {"kind": "grasp", "strength": 0.70},
                    {"kind": "correct_event", "strength": 0.55},
                    {"kind": "simplicity", "strength": 0.60},
                ]
            },
            trace_id="emotion_test_cfs",
            tick_id="emotion_test_cfs",
        )
        data = result.get("data", {}) or {}
        before = data.get("nt_state_before", {}) or {}
        after = data.get("nt_state_after", {}) or {}
        assert float(after.get("NOV", 0.0)) > float(before.get("NOV", 0.0))
        assert float(after.get("FOC", 0.0)) > float(before.get("FOC", 0.0))
        assert float(after.get("ADR", 0.0)) > float(before.get("ADR", 0.0))
        assert float(after.get("OXY", 0.0)) > float(before.get("OXY", 0.0))
        assert float(after.get("END", 0.0)) > float(before.get("END", 0.0))
    finally:
        mgr.close()


def test_builtin_recovery_cfs_can_raise_serenity_and_lower_alert_channels() -> None:
    mgr = EmotionManager(config_override={"cfs_to_nt_source_mode": "builtin"})
    try:
        result = mgr.update_emotion_state(
            {
                "cfs_signals": [
                    {"kind": "relief", "strength": 0.72},
                    {"kind": "reassurance", "strength": 0.68},
                ]
            },
            trace_id="emotion_test_recovery_cfs",
            tick_id="emotion_test_recovery_cfs",
        )
        data = result.get("data", {}) or {}
        before = data.get("nt_state_before", {}) or {}
        after = data.get("nt_state_after", {}) or {}
        assert float(after.get("SER", 0.0)) > float(before.get("SER", 0.0))
        assert float(after.get("END", 0.0)) > float(before.get("END", 0.0))
        assert float(after.get("OXY", 0.0)) > float(before.get("OXY", 0.0))
        assert float(after.get("COR", 0.0)) <= float(before.get("COR", 0.0))
        assert float(after.get("ADR", 0.0)) <= float(before.get("ADR", 0.0))
    finally:
        mgr.close()


def test_script_updates_can_drive_channels_when_builtin_cfs_mapping_disabled() -> None:
    mgr = EmotionManager(config_override={"cfs_to_nt_source_mode": "iesm_rules"})
    try:
        result = mgr.update_emotion_state(
            {
                "cfs_signals": [{"kind": "surprise", "strength": 0.80}],
                "emotion_updates": {"新颖探索": 0.18, "专注锁定（FOC）": 0.12},
            },
            trace_id="emotion_test_script_only",
            tick_id="emotion_test_script_only",
        )
        data = result.get("data", {}) or {}
        before = data.get("nt_state_before", {}) or {}
        after = data.get("nt_state_after", {}) or {}
        deltas = data.get("deltas", {}) or {}
        assert float((deltas.get("from_cfs", {}) or {}).get("NOV", 0.0)) == 0.0
        assert float((deltas.get("from_script", {}) or {}).get("NOV", 0.0)) == 0.18
        assert float((deltas.get("from_script", {}) or {}).get("FOC", 0.0)) == 0.12
        assert float(after.get("NOV", 0.0)) > float(before.get("NOV", 0.0))
        assert float(after.get("FOC", 0.0)) > float(before.get("FOC", 0.0))
    finally:
        mgr.close()


def test_rwd_pun_updates_can_be_fully_externalized_to_script_mode() -> None:
    mgr = EmotionManager(config_override={"rwd_pun_to_nt_source_mode": "iesm_rules"})
    try:
        result = mgr.update_emotion_state(
            {
                "cfs_signals": [],
                "emotion_updates": {"DA": 0.11, "COR": 0.07},
                "rwd_pun_override": {"rwd": 0.8, "pun": 0.6},
            },
            trace_id="emotion_test_rwd_pun_script",
            tick_id="emotion_test_rwd_pun_script",
        )
        data = result.get("data", {}) or {}
        deltas = data.get("deltas", {}) or {}
        assert float((deltas.get("from_rwd_pun", {}) or {}).get("DA", 0.0)) == 0.0
        assert float((deltas.get("from_rwd_pun", {}) or {}).get("COR", 0.0)) == 0.0
        assert float((deltas.get("from_script", {}) or {}).get("DA", 0.0)) == 0.11
        assert float((deltas.get("from_script", {}) or {}).get("COR", 0.0)) == 0.07
        audit = data.get("audit", {}) or {}
        assert audit.get("rwd_pun_to_nt_source_mode") == "iesm_rules"
    finally:
        mgr.close()


def test_builtin_rwd_pun_mapping_remains_available_as_fallback() -> None:
    mgr = EmotionManager(config_override={"rwd_pun_to_nt_source_mode": "builtin"})
    try:
        result = mgr.update_emotion_state(
            {
                "cfs_signals": [],
                "rwd_pun_override": {"rwd": 0.7, "pun": 0.5},
            },
            trace_id="emotion_test_rwd_pun_builtin",
            tick_id="emotion_test_rwd_pun_builtin",
        )
        data = result.get("data", {}) or {}
        deltas = data.get("deltas", {}) or {}
        assert float((deltas.get("from_rwd_pun", {}) or {}).get("DA", 0.0)) > 0.0
        assert float((deltas.get("from_rwd_pun", {}) or {}).get("COR", 0.0)) > 0.0
    finally:
        mgr.close()


def test_attention_modulation_exposes_richer_fields() -> None:
    mgr = EmotionManager()
    try:
        result = mgr.update_emotion_state(
            {
                "cfs_signals": [],
                "emotion_updates": {"NOV": 0.90, "FOC": 0.90, "OXY": 0.70, "ADR": 0.40},
            },
            trace_id="emotion_test_attention",
            tick_id="emotion_test_attention",
        )
        attention = ((result.get("data", {}) or {}).get("modulation", {}) or {}).get("attention", {}) or {}
        assert "priority_weight_total_energy" in attention
        assert "priority_weight_salience" in attention
        assert "priority_weight_recency_gain" in attention
        assert "focus_boost_weight" in attention
        assert "keep_score_ratio_base" in attention
        assert "min_cam_items" in attention
        assert float(attention.get("priority_weight_total_energy", 0.0)) > 1.25
        assert float(attention.get("priority_weight_recency_gain", 0.0)) > 0.0
        assert float(attention.get("focus_boost_weight", 0.0)) > 1.0
    finally:
        mgr.close()


def test_hdb_scales_accept_new_channel_coefficients() -> None:
    mgr = EmotionManager(
        config_override={
            "nt_channels": {
                "NOV": {"min": 0.0, "max": 1.0, "decay_ratio": 0.90, "base": 0.0, "soft_cap_k": 0.35},
            },
            "modulation": {
                "attention": {},
                "hdb": {
                    "clamp_min": 0.40,
                    "clamp_max": 2.50,
                    "scales": {
                        "probe": {"base": 1.00, "nov_gain": 0.50},
                    },
                },
            },
        }
    )
    try:
        result = mgr.update_emotion_state(
            {
                "cfs_signals": [],
                "emotion_updates": {"NOV": 0.90},
            },
            trace_id="emotion_test_hdb",
            tick_id="emotion_test_hdb",
        )
        hdb = ((result.get("data", {}) or {}).get("modulation", {}) or {}).get("hdb", {}) or {}
        assert "probe_scale" in hdb
        assert float(hdb.get("probe_scale", 0.0)) > 1.0
    finally:
        mgr.close()
