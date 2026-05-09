# -*- coding: utf-8 -*-
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from text_sensor.main import TextSensor
from text_sensor._id_generator import reset_id_generator


@pytest.fixture
def sensor():
    reset_id_generator()
    instance = TextSensor(
        config_override={
            'default_mode': 'simple',
            'enable_echo': False,
            'char_base_er': 1.0,
            'attribute_er_ratio': 0.25,
            # 该用例需要 “stimulus_intensity 属性 SA” 存在，
            # 用于验证：即使重复疲劳把 feature ER 压到 0，属性单元仍会被保留并进入 CSA。
            'enable_stimulus_intensity_attribute_sa': True,
            'enable_stimulus_fatigue': True,
            'stimulus_fatigue_window_rounds': 3,
            'stimulus_fatigue_threshold_count': 2,
            'stimulus_fatigue_max_suppression': 1.0,
        }
    )
    yield instance
    instance._logger.close()


def _feature_sa(result: dict) -> dict:
    return next(
        sa for sa in result['data']['stimulus_packet']['sa_items']
        if sa.get('stimulus', {}).get('role') == 'feature'
    )


def test_repeated_same_stimulus_reduces_er_and_preserves_units(sensor):
    first = sensor.ingest_text(text='你', trace_id='sensor_fatigue_1')
    second = sensor.ingest_text(text='你', trace_id='sensor_fatigue_2')
    third = sensor.ingest_text(text='你', trace_id='sensor_fatigue_3')

    first_feature = _feature_sa(first)
    second_feature = _feature_sa(second)
    third_feature = _feature_sa(third)

    assert first_feature['energy']['er'] > second_feature['energy']['er'] > third_feature['energy']['er']
    assert third_feature['energy']['er'] == pytest.approx(0.0)
    assert third_feature['ext']['sensor_fatigue']['suppression_ratio'] == pytest.approx(1.0)
    assert third['data']['stats']['feature_sa_count'] == 1
    assert third['data']['stats']['attribute_sa_count'] == 1
    assert third['data']['stats']['csa_count'] == 1
    assert third['data']['fatigue_summary']['zero_er_unit_count'] >= 1


def test_clear_echo_pool_resets_stimulus_fatigue_history(sensor):
    sensor.ingest_text(text='你', trace_id='sensor_clear_1')
    sensor.ingest_text(text='你', trace_id='sensor_clear_2')

    before = sensor.get_runtime_snapshot(trace_id='sensor_before_clear')['data']
    assert before['statistics']['ingest_round'] == 2
    assert before['statistics']['fatigue_history_key_count'] > 0

    sensor.clear_echo_pool(trace_id='sensor_clear_pool')
    after = sensor.get_runtime_snapshot(trace_id='sensor_after_clear')['data']
    assert after['statistics']['ingest_round'] == 0
    assert after['statistics']['fatigue_history_key_count'] == 0


def test_sensor_fatigue_metadata_is_exposed_in_packet_and_summary(sensor):
    sensor.ingest_text(text='你', trace_id='sensor_meta_1')
    result = sensor.ingest_text(text='你', trace_id='sensor_meta_2')

    feature = _feature_sa(result)
    meta = feature['ext']['sensor_fatigue']
    summary = result['data']['fatigue_summary']

    assert meta['window_rounds'] == 3
    assert meta['threshold_count'] == 2
    assert meta['window_count'] == 2
    assert meta['er_before_fatigue'] > meta['er_after_fatigue']
    assert summary['suppressed_unit_count'] >= 1
    assert summary['total_er_before_fatigue'] > summary['total_er_after_fatigue']
