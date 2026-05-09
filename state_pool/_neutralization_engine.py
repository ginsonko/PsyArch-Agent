# -*- coding: utf-8 -*-
"""
AP 状态池模块 — 中和引擎
==========================
实现 er 与 ev 之间的中和策略。

当前策略:
  simple_min_cancel: neutralized = min(er, ev), er -= n, ev -= n
  cp_only_reduce:    按比例缩减低侧能量使 cp_abs 降低（预留）
  custom:            占位，未来自定义策略
"""

import time
from ._id_generator import next_id


class NeutralizationEngine:
    """
    中和引擎。

    中和含义：当对象同时拥有实能量（现实证据）和虚能量（预测/期望）时，
    两者相互抵消的量称为中和量。中和后认知压可能显著下降，这正是
    "正确感"（预测被证实后认知压降低）的工程体现。
    """

    def __init__(self, config: dict):
        self._config = config

    def neutralize(
        self,
        item: dict,
        tick_number: int,
        trace_id: str = "",
        tick_id: str = "",
    ) -> dict | None:
        """
        对一个 state_item 执行中和。

        返回:
            state_change_event dict（若发生了有效中和）
            None（若中和量低于阈值或未启用）
        """
        if not self._config.get("enable_neutralization", True):
            return None

        mode = self._config.get("neutralization_mode", "simple_min_cancel")
        min_threshold = self._config.get("neutralization_min_effect_threshold", 0.01)

        energy = item["energy"]
        er = energy["er"]
        ev = energy["ev"]

        if mode == "simple_min_cancel":
            return self._simple_min_cancel(item, er, ev, min_threshold, tick_number, trace_id, tick_id)
        elif mode == "cp_only_reduce":
            # 占位：按比例缩减策略（未来实现）
            return self._simple_min_cancel(item, er, ev, min_threshold, tick_number, trace_id, tick_id)
        else:
            return None

    def _simple_min_cancel(
        self,
        item: dict,
        er: float,
        ev: float,
        min_threshold: float,
        tick_number: int,
        trace_id: str,
        tick_id: str,
    ) -> dict | None:
        """
        simple_min_cancel 策略:
          neutralized = min(er, ev)
          如果 neutralized < min_threshold，则忽略
          否则 er -= neutralized, ev -= neutralized
        """
        neutralized = min(er, ev)
        if neutralized < min_threshold:
            return None

        now_ms = int(time.time() * 1000)
        energy = item["energy"]

        # before
        before_er = er
        before_ev = ev
        before_cp_delta = energy["cognitive_pressure_delta"]
        before_cp_abs = energy["cognitive_pressure_abs"]

        # 执行中和
        new_er = round(er - neutralized, 8)
        new_ev = round(ev - neutralized, 8)
        new_cp_delta = new_er - new_ev
        new_cp_abs = abs(new_cp_delta)

        energy["er"] = new_er
        energy["ev"] = new_ev
        energy["cognitive_pressure_delta"] = round(new_cp_delta, 8)
        energy["cognitive_pressure_abs"] = round(new_cp_abs, 8)
        energy["salience_score"] = max(new_er, new_ev)

        # 更新动态指标
        dynamics = item["dynamics"]
        dynamics["prev_er"] = before_er
        dynamics["prev_ev"] = before_ev
        dynamics["delta_er"] = round(new_er - before_er, 8)
        dynamics["delta_ev"] = round(new_ev - before_ev, 8)
        dynamics["prev_cp_delta"] = round(before_cp_delta, 8)
        dynamics["prev_cp_abs"] = round(before_cp_abs, 8)
        dynamics["delta_cp_delta"] = round(new_cp_delta - before_cp_delta, 8)
        dynamics["delta_cp_abs"] = round(new_cp_abs - before_cp_abs, 8)
        dynamics["last_update_at"] = now_ms
        dynamics["update_count"] = dynamics.get("update_count", 0) + 1

        item["updated_at"] = now_ms

        # 生成事件
        return {
            "event_id": next_id("sce"),
            "event_type": "neutralization",
            "target_item_id": item["id"],
            "trace_id": trace_id,
            "tick_id": tick_id,
            "timestamp_ms": now_ms,
            "before": {
                "er": round(before_er, 8), "ev": round(before_ev, 8),
                "cp_delta": round(before_cp_delta, 8), "cp_abs": round(before_cp_abs, 8),
            },
            "after": {
                "er": new_er, "ev": new_ev,
                "cp_delta": round(new_cp_delta, 8), "cp_abs": round(new_cp_abs, 8),
            },
            "delta": {
                "delta_er": round(-neutralized, 8), "delta_ev": round(-neutralized, 8),
                "delta_cp_delta": round(new_cp_delta - before_cp_delta, 8),
                "delta_cp_abs": round(new_cp_abs - before_cp_abs, 8),
            },
            "rate": {"er_change_rate": 0, "ev_change_rate": 0, "cp_delta_rate": 0, "cp_abs_rate": 0},
            "reason": f"neutralization_{self._config.get('neutralization_mode', 'simple_min_cancel')}",
            "source_module": "state_pool",
            "extra_context": {"neutralized_amount": round(neutralized, 8)},
        }

    def update_config(self, config: dict):
        self._config = config
