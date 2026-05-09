# -*- coding: utf-8 -*-
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from hdb._weight_engine import WeightEngine


@pytest.fixture
def engine():
    return WeightEngine(
        {
            'weight_floor': 0.05,
            'recency_gain_peak': 10.0,
            'recency_gain_hold_rounds': 2,
            'recency_gain_decay_ratio': 0.5,
            'recency_gain_refresh_floor': 0.45,
            'recency_gain_boost': 0.08,
            'recency_gain_decay_mode': 'by_round',
            'fatigue_cap': 1.5,
            'fatigue_increase_per_match': 0.1,
            'fatigue_decay_per_tick': 0.5,
            'energy_decay_mode': 'by_round',
            'energy_decay_round_ratio_er': 1.0,
            'energy_decay_round_ratio_ev': 1.0,
            'base_weight_er_gain': 0.08,
            'base_weight_ev_wear': 0.03,
        }
    )


def test_seed_recent_gain_follows_hold_then_decay_to_one(engine):
    entry = {}
    engine.seed_recent_state(entry, now_ms=1000, strength=1.0)
    assert entry['recent_gain'] == pytest.approx(10.0)
    assert entry['recency_hold_rounds_remaining'] == 2

    engine.decay_entry(entry, now_ms=1000, round_step=1)
    assert entry['recent_gain'] == pytest.approx(10.0)
    assert entry['recency_hold_rounds_remaining'] == 1

    engine.decay_entry(entry, now_ms=1000, round_step=1)
    assert entry['recent_gain'] == pytest.approx(10.0)
    assert entry['recency_hold_rounds_remaining'] == 0

    engine.decay_entry(entry, now_ms=1000, round_step=1)
    assert entry['recent_gain'] == pytest.approx(5.0)

    for _ in range(8):
        engine.decay_entry(entry, now_ms=1000, round_step=1)
    assert entry['recent_gain'] == pytest.approx(1.0)


def test_mark_structure_match_refreshes_recency_and_increases_fatigue(engine):
    structure = {
        'stats': {
            'base_weight': 1.0,
            'recent_gain': 1.0,
            'fatigue': 0.0,
            'runtime_er': 0.0,
            'runtime_ev': 0.0,
        }
    }
    engine.mark_structure_match(
        structure,
        match_score=1.0,
        reality_support=2.0,
        virtual_support=0.5,
        now_ms=2000,
    )
    stats = structure['stats']
    assert stats['recent_gain'] > 1.0
    assert stats['fatigue'] > 0.0
    assert stats['runtime_er'] == pytest.approx(2.0)
    assert stats['runtime_ev'] == pytest.approx(0.5)


def test_mark_entry_activation_uses_delta_to_refresh_runtime_state(engine):
    entry = {
        'base_weight': 1.0,
        'recent_gain': 1.0,
        'fatigue': 0.0,
        'runtime_er': 0.0,
        'runtime_ev': 0.0,
    }
    engine.mark_entry_activation(entry, delta_er=1.2, delta_ev=0.4, match_score=0.8, now_ms=3000)
    assert entry['runtime_er'] == pytest.approx(1.2)
    assert entry['runtime_ev'] == pytest.approx(0.4)
    assert entry['recent_gain'] > 1.0
    assert entry['fatigue'] > 0.0
    assert entry['match_count_total'] == 1
