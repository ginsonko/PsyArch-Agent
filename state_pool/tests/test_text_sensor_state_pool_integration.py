# -*- coding: utf-8 -*-
"""
TextSensor -> StatePool 联动回归测试
===================================

重点覆盖：
1. 感受器 echo 不应再被当作新的状态池输入重复赋能。
2. 语义同一对象应跨轮次合并到同一个运行态对象。
3. 与当前输入无关的旧对象，不应在后续轮次无故继续涨能量。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from text_sensor import TextSensor
from text_sensor._id_generator import reset_id_generator as reset_text_ids
from state_pool.main import StatePool
from state_pool._id_generator import reset_id_generator as reset_pool_ids


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


@pytest.fixture
def pool():
    reset_pool_ids()
    instance = StatePool(
        config_override={
            "pool_max_items": 200,
            "enable_placeholder_interfaces": False,
            "enable_script_broadcast": False,
            "enable_semantic_same_object_merge": True,
        }
    )
    yield instance
    instance._logger.close()


def _apply_text(sensor: TextSensor, pool: StatePool, text: str, trace_id: str) -> dict:
    sensor_result = sensor.ingest_text(text=text, trace_id=trace_id, tick_id=trace_id)
    assert sensor_result["success"] is True
    apply_result = pool.apply_stimulus_packet(
        stimulus_packet=sensor_result["data"]["stimulus_packet"],
        trace_id=trace_id,
        tick_id=trace_id,
        source_module="text_sensor",
    )
    assert apply_result["success"] is True
    return apply_result


def _find_single_item(pool: StatePool, ref_type: str, display: str) -> dict:
    matches = [
        item
        for item in pool._store.get_all()
        if item.get("ref_object_type") == ref_type
        and item.get("ref_snapshot", {}).get("content_display") == display
    ]
    assert matches, f"未找到对象 / item not found: {ref_type} {display}"
    assert len(matches) == 1, f"语义对象未合并 / semantic merge failed for: {ref_type} {display}"
    return matches[0]


def test_repeated_same_text_merges_into_same_runtime_objects(sensor, pool):
    first = _apply_text(sensor, pool, "你好", "merge_round_1")
    second = _apply_text(sensor, pool, "你好", "merge_round_2")

    # 默认配置下：仅特征 SA 入池；属性 SA 与 CSA 作为“约束/从属信息”折叠进锚点快照。
    assert first["data"]["new_item_count"] == 2
    assert second["data"]["new_item_count"] == 0
    assert second["data"]["updated_item_count"] == 2
    assert pool._store.size == 2

    ni_sa = _find_single_item(pool, "sa", "你")

    assert ni_sa["dynamics"]["update_count"] == 2


def test_unrelated_old_items_do_not_gain_energy_from_echo_reinjection(sensor, pool):
    _apply_text(sensor, pool, "你好呀!", "chain_round_1")

    ya_sa_round_1 = _find_single_item(pool, "sa", "呀")["energy"]["er"]

    _apply_text(sensor, pool, "你也好", "chain_round_2")
    ya_sa_round_2 = _find_single_item(pool, "sa", "呀")["energy"]["er"]

    _apply_text(sensor, pool, "你在做什么?", "chain_round_3")
    ya_sa_round_3 = _find_single_item(pool, "sa", "呀")["energy"]["er"]

    assert ya_sa_round_2 == pytest.approx(ya_sa_round_1)
    assert ya_sa_round_3 == pytest.approx(ya_sa_round_1)
