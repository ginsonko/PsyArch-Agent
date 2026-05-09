# -*- coding: utf-8 -*-
"""
增强联动控制台的刺激包时序辅助函数测试
======================================

重点覆盖：
1. grouped packet view 能正确区分 echo / current 组。
2. semantic trails 能识别跨组重现对象。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from text_sensor import TextSensor
from text_sensor._id_generator import reset_id_generator as reset_text_ids
from state_pool.tests.run_integration_enhanced import (
    build_packet_group_summaries,
    build_packet_semantic_trails,
    normalize_cli_token,
)


@pytest.fixture
def sensor():
    reset_text_ids()
    instance = TextSensor(
        config_override={
            "default_mode": "simple",
            "enable_echo": True,
            "include_echoes_in_stimulus_packet_objects": True,
            "attribute_er_ratio": 0.25,
        }
    )
    yield instance
    instance._logger.close()


def test_packet_group_summaries_include_echo_and_current(sensor):
    sensor.ingest_text(text="你好", trace_id="pkt_group_1")
    result = sensor.ingest_text(text="你也好", trace_id="pkt_group_2")
    packet = result["data"]["stimulus_packet"]

    summaries = build_packet_group_summaries(packet)
    assert len(summaries) >= 2
    assert summaries[0]["source_type"] == "echo"
    assert summaries[-1]["source_type"] == "current"
    assert summaries[0]["echo_depth"] >= 1
    assert "你" in summaries[0]["feature_samples"]
    assert summaries[-1]["total_sa_er"] > summaries[0]["total_sa_er"]


def test_packet_semantic_trails_detect_cross_group_reappearance(sensor):
    sensor.ingest_text(text="你好", trace_id="pkt_trail_1")
    result = sensor.ingest_text(text="你也好", trace_id="pkt_trail_2")
    packet = result["data"]["stimulus_packet"]

    trails = build_packet_semantic_trails(packet)
    display_map = {trail["display"]: trail for trail in trails}

    assert "你" in display_map
    ni_trail = display_map["你"]
    assert len(ni_trail["appearances"]) >= 2
    assert {appearance["source_type"] for appearance in ni_trail["appearances"]} >= {"echo", "current"}

    assert "CSA[你]" in display_map


def test_normalize_cli_token_supports_bracket_style_arguments():
    assert normalize_cli_token("[on]") == "on"
    assert normalize_cli_token("(groups)") == "groups"
    assert normalize_cli_token("{FULL}") == "full"
