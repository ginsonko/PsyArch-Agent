# -*- coding: utf-8 -*-
from __future__ import annotations

import math

from energy_balance.main import EnergyBalanceController


def test_counter_windup_gain_accelerates_return_from_wrong_side() -> None:
    slow = EnergyBalanceController(
        config_override={
            "enabled": True,
            "target_ratio": 1.0,
            "window_ticks": 1,
            "ki": 0.10,
            "neutral_log_g_decay": 0.0,
            "counter_windup_gain": 1.0,
            "error_deadband": 0.0,
            "g_min": 0.2,
            "g_max": 5.0,
        }
    )
    fast = EnergyBalanceController(
        config_override={
            "enabled": True,
            "target_ratio": 1.0,
            "window_ticks": 1,
            "ki": 0.10,
            "neutral_log_g_decay": 0.0,
            "counter_windup_gain": 3.0,
            "error_deadband": 0.0,
            "g_min": 0.2,
            "g_max": 5.0,
        }
    )
    slow._log_g = math.log(4.0)
    fast._log_g = math.log(4.0)

    slow_res = slow.update_from_energy_summary(
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        total_er=1.0,
        total_ev=2.0,
    )["data"]
    fast_res = fast.update_from_energy_summary(
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        total_er=1.0,
        total_ev=2.0,
    )["data"]

    assert slow_res["counter_windup_active"] is True
    assert fast_res["counter_windup_active"] is True
    assert fast_res["ki_effective"] > slow_res["ki_effective"]
    assert fast_res["g_after"] < slow_res["g_after"]


def test_neutral_log_g_decay_pulls_gain_back_toward_one_inside_deadband() -> None:
    controller = EnergyBalanceController(
        config_override={
            "enabled": True,
            "target_ratio": 1.0,
            "window_ticks": 1,
            "ki": 0.08,
            "neutral_log_g_decay": 0.10,
            "counter_windup_gain": 1.0,
            "error_deadband": 0.20,
            "g_min": 0.2,
            "g_max": 5.0,
        }
    )
    controller._log_g = math.log(2.0)

    res = controller.update_from_energy_summary(
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        total_er=1.0,
        total_ev=1.05,
    )["data"]

    assert abs(res["error_log_effective"]) == 0.0
    assert res["log_g_after_decay"] < res["log_g_before"]
    assert 1.0 < res["g_after"] < res["g_before"]


def test_target_ratio_is_clamped_to_theory_safe_floor() -> None:
    controller = EnergyBalanceController(
        config_override={
            "enabled": True,
            "target_ratio": 1.01,
            "target_ratio_min": 1.08,
            "target_ratio_max": 1.35,
            "window_ticks": 1,
            "ki": 0.04,
        }
    )

    res = controller.update_from_energy_summary(
        trace_id="t",
        tick_id="cycle_0001",
        tick_index=1,
        total_er=1.0,
        total_ev=1.0,
    )["data"]

    assert res["target_ratio"] == 1.08
    assert res["target_ratio_min"] == 1.08
