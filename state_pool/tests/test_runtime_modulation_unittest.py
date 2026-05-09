# -*- coding: utf-8 -*-

import math
import time
import unittest

from state_pool.main import StatePool
from state_pool._id_generator import reset_id_generator


def _build_packet(sa_id: str = "sa_runtime_001", text: str = "你", er: float = 1.0) -> dict:
    now_ms = int(time.time() * 1000)
    return {
        "id": f"spkt_{sa_id}",
        "object_type": "stimulus_packet",
        "sa_items": [
            {
                "id": sa_id,
                "object_type": "sa",
                "content": {"raw": text, "display": text, "value_type": "discrete"},
                "stimulus": {"role": "feature", "modality": "text"},
                "energy": {"er": er, "ev": 0.0},
                "created_at": now_ms,
                "updated_at": now_ms,
            }
        ],
        "csa_items": [],
        "trace_id": f"trace_{sa_id}",
    }


class TestStatePoolRuntimeModulationDefaults(unittest.TestCase):
    def setUp(self):
        reset_id_generator()
        self.pool = StatePool(
            config_override={
                "pool_max_items": 100,
                "enable_placeholder_interfaces": False,
                "enable_script_broadcast": False,
                "default_er_decay_ratio": 1.0,
                "default_ev_decay_ratio": 1.0,
                "er_elimination_threshold": 0.0,
                "ev_elimination_threshold": 0.0,
            }
        )

    def tearDown(self):
        self.pool._logger.close()

    def test_default_recency_peak_matches_theory_profile(self):
        self.assertAlmostEqual(float(self.pool._config["recency_gain_peak"]), 10.0, places=6)
        self.assertAlmostEqual(float(self.pool._config["recency_gain_decay_ratio"]), 0.9999976974, places=10)

        result = self.pool.apply_stimulus_packet(_build_packet(), trace_id="theory_seed")
        self.assertTrue(result["success"])

        item = self.pool._store.get_all()[0]
        self.assertAlmostEqual(float(item["energy"]["recency_gain"]), 10.0, places=6)
        self.assertEqual(item["lifecycle"]["recency_hold_ticks_remaining"], 2)

    def test_default_decay_ratio_returns_near_one_on_million_tick_scale(self):
        ratio = float(self.pool._config["recency_gain_decay_ratio"])
        peak = float(self.pool._config["recency_gain_peak"])
        projected = peak * math.pow(ratio, 1_000_000)
        self.assertAlmostEqual(projected, 1.0, delta=0.01)


if __name__ == "__main__":
    unittest.main()
