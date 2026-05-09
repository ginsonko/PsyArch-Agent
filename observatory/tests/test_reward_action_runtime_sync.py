# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from observatory._app import ObservatoryApp


def test_reward_action_runtime_sync_projects_global_signal_and_action_nodes():
    temp_hdb_dir = tempfile.mkdtemp(prefix="observatory_reward_action_sync_")
    app = ObservatoryApp(
        config_override={
            "export_html": False,
            "export_json": False,
            "auto_open_html_report": False,
            "web_auto_open_browser": False,
            "hdb_enable_background_repair": False,
            "hdb_data_dir": temp_hdb_dir,
            "reward_action_humanlike_v2_enabled": True,
            "reward_action_runtime_signal_nodes_enabled": True,
            "reward_action_runtime_action_nodes_enabled": True,
        }
    )
    try:
        sync = app._sync_reward_action_runtime_nodes(
            emotion_data={"rwd_pun_snapshot": {"rwd": 0.6, "pun": 0.2}},
            action_data={
                "nodes": [
                    {
                        "action_id": "act_weather",
                        "action_kind": "weather_stub",
                        "drive": 0.55,
                        "effective_threshold": 0.3,
                        "threshold_scale": 0.9,
                        "target_ref_object_id": "st_weather",
                        "target_ref_object_type": "st",
                        "target_item_id": "spi_weather",
                        "target_display": "天气请求",
                        "last_consumed_drive": 0.35,
                    }
                ],
                "executed_actions": [
                    {
                        "action_id": "act_weather",
                        "action_kind": "weather_stub",
                        "consumed_drive": 0.35,
                    }
                ],
            },
            trace_id="pytest_reward_action_sync",
            tick_id="cycle_reward_action_sync_0001",
        )

        assert sync["enabled"] is True
        assert sync["summary"]["signal_node_active_count"] == 2
        assert sync["summary"]["action_node_count"] == 1
        assert sync["summary"]["action_node_executed_count"] == 1

        snapshot = app.pool.get_state_snapshot(
            trace_id="pytest_reward_action_sync_snapshot",
            tick_id="cycle_reward_action_sync_0001",
            top_k=None,
        )["data"]["snapshot"]
        by_ref = {str(row.get("ref_object_id", "")): row for row in (snapshot.get("top_items", []) or []) if isinstance(row, dict)}

        reward_row = by_ref["reward_signal"]
        punish_row = by_ref["punish_signal"]
        action_row = by_ref["action::act_weather"]

        assert reward_row["ref_object_type"] == "sa"
        assert punish_row["ref_object_type"] == "sa"
        assert float(reward_row["ev"]) == 0.6
        assert float(punish_row["ev"]) == 0.2

        assert action_row["ref_object_type"] == "action_node"
        assert float(action_row["ev"]) == 0.55
        assert float(action_row["er"]) == 0.35
        ref_snapshot = action_row.get("ref_snapshot", {}) or {}
        assert ref_snapshot.get("target_ref_object_id") == "st_weather"
        assert ref_snapshot.get("target_item_id") == "spi_weather"
    finally:
        app.close()
        shutil.rmtree(temp_hdb_dir, ignore_errors=True)
