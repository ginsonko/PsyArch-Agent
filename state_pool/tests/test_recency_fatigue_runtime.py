# -*- coding: utf-8 -*-
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from state_pool.main import StatePool
from state_pool._id_generator import reset_id_generator


def _build_packet(sa_id: str = 'sa_runtime_001', text: str = '你', er: float = 1.0) -> dict:
    now_ms = int(time.time() * 1000)
    return {
        'id': f'spkt_{sa_id}',
        'object_type': 'stimulus_packet',
        'sa_items': [
            {
                'id': sa_id,
                'object_type': 'sa',
                'content': {'raw': text, 'display': text, 'value_type': 'discrete'},
                'stimulus': {'role': 'feature', 'modality': 'text'},
                'energy': {'er': er, 'ev': 0.0},
                'created_at': now_ms,
                'updated_at': now_ms,
            }
        ],
        'csa_items': [],
        'trace_id': f'trace_{sa_id}',
    }


@pytest.fixture
def pool():
    reset_id_generator()
    instance = StatePool(
        config_override={
            'pool_max_items': 100,
            'enable_placeholder_interfaces': False,
            'enable_script_broadcast': False,
            'default_er_decay_ratio': 1.0,
            'default_ev_decay_ratio': 1.0,
            'er_elimination_threshold': 0.0,
            'ev_elimination_threshold': 0.0,
        }
    )
    yield instance
    instance._logger.close()


def test_new_item_seeds_recency_peak_and_activation_history(pool):
    packet = _build_packet()
    result = pool.apply_stimulus_packet(packet, trace_id='recency_seed_1')
    assert result['success'] is True

    item = pool._store.get_all()[0]
    assert item['energy']['recency_gain'] == pytest.approx(pool._config['recency_gain_peak'])
    assert item['energy']['fatigue'] == pytest.approx(0.0)
    assert item['lifecycle']['last_active_tick'] == 1
    assert item['lifecycle']['recent_activation_ticks'] == [1]


def test_maintenance_recency_decays_but_never_below_one():
    reset_id_generator()
    pool = StatePool(
        config_override={
            'pool_max_items': 100,
            'enable_placeholder_interfaces': False,
            'enable_script_broadcast': False,
            'default_er_decay_ratio': 1.0,
            'default_ev_decay_ratio': 1.0,
            'er_elimination_threshold': 0.0,
            'ev_elimination_threshold': 0.0,
            'recency_gain_peak': 2.0,
            'recency_gain_hold_ticks': 1,
            'recency_gain_decay_ratio': 0.5,
        }
    )
    try:
        pool.apply_stimulus_packet(_build_packet(), trace_id='recency_decay_1')
        item = pool._store.get_all()[0]
        assert item['energy']['recency_gain'] == pytest.approx(2.0)

        pool.tick_maintain_state_pool(trace_id='recency_decay_tick_1')
        assert item['energy']['recency_gain'] == pytest.approx(2.0)

        pool.tick_maintain_state_pool(trace_id='recency_decay_tick_2')
        assert item['energy']['recency_gain'] == pytest.approx(1.0)

        pool.tick_maintain_state_pool(trace_id='recency_decay_tick_3')
        assert item['energy']['recency_gain'] == pytest.approx(1.0)
    finally:
        pool._logger.close()


def test_repeated_activations_raise_runtime_fatigue():
    reset_id_generator()
    pool = StatePool(
        config_override={
            'pool_max_items': 100,
            'enable_placeholder_interfaces': False,
            'enable_script_broadcast': False,
            'default_er_decay_ratio': 1.0,
            'default_ev_decay_ratio': 1.0,
            'er_elimination_threshold': 0.0,
            'ev_elimination_threshold': 0.0,
            'fatigue_window_ticks': 5,
            'fatigue_threshold_count': 2,
            'fatigue_max_value': 1.0,
        }
    )
    try:
        packet = _build_packet()
        pool.apply_stimulus_packet(packet, trace_id='fatigue_round_1')
        pool.apply_stimulus_packet(packet, trace_id='fatigue_round_2')
        pool.apply_stimulus_packet(packet, trace_id='fatigue_round_3')

        item = pool._store.get_all()[0]
        assert item['lifecycle']['recent_activation_ticks'] == [1, 2, 3]
        assert item['energy']['fatigue'] > 0.0
        assert item['energy']['fatigue'] == pytest.approx(0.5)
    finally:
        pool._logger.close()


def test_tick_decay_does_not_refresh_last_active_tick(pool):
    packet = _build_packet()
    pool.apply_stimulus_packet(packet, trace_id='decay_tick_1')
    item = pool._store.get_all()[0]
    assert item['lifecycle']['last_active_tick'] == 1

    pool.tick_maintain_state_pool(trace_id='decay_tick_2')
    assert item['lifecycle']['last_active_tick'] == 1
    assert item['energy']['last_decay_tick'] == 2
