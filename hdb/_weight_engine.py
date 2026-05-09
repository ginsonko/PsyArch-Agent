# -*- coding: utf-8 -*-
"""
Runtime weight, recency, fatigue, and energy decay calculations for HDB.
"""

from __future__ import annotations

import math
import time


class WeightEngine:
    def __init__(self, config: dict):
        self._config = config

    def update_config(self, config: dict) -> None:
        self._config = config

    def seed_recent_state(self, target: dict, *, now_ms: int | None = None, strength: float = 1.0) -> None:
        now_ms = now_ms or int(time.time() * 1000)
        target["recent_gain"] = self._target_recent_gain(strength=strength)
        target["last_recency_refresh_at"] = now_ms
        target["recency_hold_rounds_remaining"] = self._recency_hold_rounds()

    def refresh_recent_state(self, target: dict, *, now_ms: int | None = None, strength: float = 1.0) -> None:
        now_ms = now_ms or int(time.time() * 1000)
        current = float(target.get("recent_gain", 1.0))
        target_gain = self._target_recent_gain(strength=strength)
        additive_gain = current + float(self._config.get("recency_gain_boost", 0.08)) * max(0.1, min(1.0, float(strength)))
        peak = self._recency_peak()
        target["recent_gain"] = round(min(peak, max(current, target_gain, additive_gain)), 8)
        target["last_recency_refresh_at"] = now_ms
        target["recency_hold_rounds_remaining"] = self._recency_hold_rounds()

    def apply_match_fatigue(self, target: dict, *, strength: float = 1.0) -> None:
        fatigue_cap = float(self._config.get("fatigue_cap", 1.5))
        fatigue_increase = float(self._config.get("fatigue_increase_per_match", 0.08))
        target["fatigue"] = round(
            min(
                fatigue_cap,
                float(target.get("fatigue", 0.0)) + fatigue_increase * max(0.5, min(1.0, float(strength))),
            ),
            8,
        )

    def compute_runtime_weight(self, *, base_weight: float, recent_gain: float, fatigue: float, modulation: float = 1.0) -> float:
        fatigue_factor = 1.0 / (1.0 + max(0.0, fatigue))
        return round(max(self._config.get("weight_floor", 0.05), base_weight * recent_gain * fatigue_factor * modulation), 8)

    def update_base_weight_by_support(
        self,
        *,
        current_base_weight: float | None,
        reality_support: float,
        virtual_support: float,
        match_score: float = 1.0,
    ) -> float:
        storage_floor = max(0.0, float(self._config.get("base_weight_storage_floor", 0.0) or 0.0))
        default_base = max(0.0, float(self._config.get("base_weight_new_default", 0.0) or 0.0))
        try:
            current = float(current_base_weight) if current_base_weight is not None else default_base
        except Exception:
            current = default_base
        current = max(storage_floor, current)
        score = max(0.0, float(match_score))
        er_gain = max(0.0, float(reality_support)) * score * float(self._config.get("base_weight_er_gain", 0.08))
        ev_wear_strength = max(0.0, float(virtual_support)) * score * float(self._config.get("base_weight_ev_wear", 0.03))
        wear_mode = str(self._config.get("base_weight_ev_wear_mode", "multiplicative") or "multiplicative").strip().lower()
        worn = current
        if ev_wear_strength > 0.0:
            if wear_mode == "subtractive":
                worn = max(storage_floor, current - ev_wear_strength)
            else:
                wear_factor = math.exp(-ev_wear_strength)
                worn = storage_floor + max(0.0, current - storage_floor) * wear_factor
        return round(max(storage_floor, worn + er_gain), 8)

    def decay_structure(self, structure_obj: dict, now_ms: int | None = None, round_step: int = 1) -> dict:
        stats = structure_obj.setdefault("stats", {})
        now_ms = now_ms or int(time.time() * 1000)
        stats["recent_gain"], stats["recency_hold_rounds_remaining"] = self._decay_recent_gain(
            current=stats.get("recent_gain", 1.0),
            last_refresh_ms=stats.get("last_recency_refresh_at", stats.get("last_matched_at", 0)),
            now_ms=now_ms,
            round_step=round_step,
            hold_remaining=stats.get("recency_hold_rounds_remaining", 0),
        )
        stats["fatigue"] = self._decay_fatigue(stats.get("fatigue", 0.0), stats.get("last_matched_at", 0), now_ms, round_step)
        stats["runtime_er"] = self._decay_energy(stats.get("runtime_er", 0.0), stats.get("last_runtime_energy_at", 0), now_ms, round_step, kind="er")
        stats["runtime_ev"] = self._decay_energy(stats.get("runtime_ev", 0.0), stats.get("last_runtime_energy_at", 0), now_ms, round_step, kind="ev")
        stats["last_runtime_energy_at"] = now_ms
        return structure_obj

    def decay_group(self, group_obj: dict, now_ms: int | None = None, round_step: int = 1) -> dict:
        stats = group_obj.setdefault("stats", {})
        now_ms = now_ms or int(time.time() * 1000)
        stats["recent_gain"], stats["recency_hold_rounds_remaining"] = self._decay_recent_gain(
            current=stats.get("recent_gain", 1.0),
            last_refresh_ms=stats.get("last_recency_refresh_at", stats.get("last_matched_at", 0)),
            now_ms=now_ms,
            round_step=round_step,
            hold_remaining=stats.get("recency_hold_rounds_remaining", 0),
        )
        stats["fatigue"] = self._decay_fatigue(stats.get("fatigue", 0.0), stats.get("last_matched_at", 0), now_ms, round_step)
        return group_obj

    def decay_entry(self, entry: dict, now_ms: int | None = None, round_step: int = 1) -> dict:
        now_ms = now_ms or int(time.time() * 1000)
        entry["recent_gain"], entry["recency_hold_rounds_remaining"] = self._decay_recent_gain(
            current=entry.get("recent_gain", 1.0),
            last_refresh_ms=entry.get("last_recency_refresh_at", entry.get("last_matched_at", 0)),
            now_ms=now_ms,
            round_step=round_step,
            hold_remaining=entry.get("recency_hold_rounds_remaining", 0),
        )
        entry["fatigue"] = self._decay_fatigue(entry.get("fatigue", 0.0), entry.get("last_matched_at", 0), now_ms, round_step)
        entry["runtime_er"] = self._decay_energy(entry.get("runtime_er", 0.0), entry.get("last_updated_at", 0), now_ms, round_step, kind="er")
        entry["runtime_ev"] = self._decay_energy(entry.get("runtime_ev", 0.0), entry.get("last_updated_at", 0), now_ms, round_step, kind="ev")
        entry["last_updated_at"] = now_ms
        return entry

    def mark_structure_match(self, structure_obj: dict, *, match_score: float, reality_support: float, virtual_support: float, now_ms: int | None = None) -> dict:
        stats = structure_obj.setdefault("stats", {})
        now_ms = now_ms or int(time.time() * 1000)
        self.decay_structure(structure_obj, now_ms=now_ms, round_step=1)

        stats["base_weight"] = self.update_base_weight_by_support(
            current_base_weight=stats.get("base_weight", None),
            reality_support=reality_support,
            virtual_support=virtual_support,
            match_score=match_score,
        )
        self.refresh_recent_state(stats, now_ms=now_ms, strength=max(self._recency_refresh_floor(), float(match_score)))
        self.apply_match_fatigue(stats, strength=match_score)
        stats["runtime_er"] = round(max(0.0, float(stats.get("runtime_er", 0.0)) + max(0.0, reality_support)), 8)
        stats["runtime_ev"] = round(max(0.0, float(stats.get("runtime_ev", 0.0)) + max(0.0, virtual_support)), 8)
        stats["last_matched_at"] = now_ms
        stats["match_count_total"] = int(stats.get("match_count_total", 0)) + 1
        if reality_support > 0:
            stats["verified_count_er"] = int(stats.get("verified_count_er", 0)) + 1
            stats["last_verified_by_er_at"] = now_ms
        if virtual_support > 0:
            stats["worn_count_ev"] = int(stats.get("worn_count_ev", 0)) + 1
            stats["last_worn_by_ev_at"] = now_ms
        stats["last_runtime_energy_at"] = now_ms
        return structure_obj

    def mark_group_match(self, group_obj: dict, *, match_score: float, now_ms: int | None = None) -> dict:
        stats = group_obj.setdefault("stats", {})
        now_ms = now_ms or int(time.time() * 1000)
        self.decay_group(group_obj, now_ms=now_ms, round_step=1)
        stats["base_weight"] = self.update_base_weight_by_support(
            current_base_weight=stats.get("base_weight", None),
            reality_support=max(0.25, match_score),
            virtual_support=0.0,
            match_score=1.0,
        )
        self.refresh_recent_state(stats, now_ms=now_ms, strength=max(self._recency_refresh_floor(), float(match_score)))
        self.apply_match_fatigue(stats, strength=match_score)
        stats["last_matched_at"] = now_ms
        stats["match_count_total"] = int(stats.get("match_count_total", 0)) + 1
        return group_obj

    def mark_entry_activation(self, entry: dict, *, delta_er: float = 0.0, delta_ev: float = 0.0, match_score: float = 1.0, now_ms: int | None = None) -> dict:
        now_ms = now_ms or int(time.time() * 1000)
        self.decay_entry(entry, now_ms=now_ms, round_step=1)
        entry["runtime_er"] = round(max(0.0, float(entry.get("runtime_er", 0.0)) + max(0.0, delta_er)), 8)
        entry["runtime_ev"] = round(max(0.0, float(entry.get("runtime_ev", 0.0)) + max(0.0, delta_ev)), 8)
        self.refresh_recent_state(entry, now_ms=now_ms, strength=max(self._recency_refresh_floor(), float(match_score)))
        self.apply_match_fatigue(entry, strength=max(0.1, 0.5 * float(match_score)))
        entry["match_count_total"] = int(entry.get("match_count_total", 0)) + 1
        if delta_er > 0:
            path_stats = entry.setdefault("path_stats", {})
            path_stats["verified_count_er"] = int(path_stats.get("verified_count_er", 0)) + 1
        if delta_ev > 0:
            path_stats = entry.setdefault("path_stats", {})
            path_stats["worn_count_ev"] = int(path_stats.get("worn_count_ev", 0)) + 1
        entry["last_matched_at"] = now_ms
        entry["last_updated_at"] = now_ms
        return entry

    def entry_runtime_weight(self, entry: dict) -> float:
        return self.compute_runtime_weight(
            base_weight=float(entry.get("base_weight", 0.0)),
            recent_gain=float(entry.get("recent_gain", 1.0)),
            fatigue=float(entry.get("fatigue", 0.0)),
        )

    def _decay_recent_gain(
        self,
        current: float,
        last_refresh_ms: int,
        now_ms: int,
        round_step: int,
        hold_remaining: int = 0,
    ) -> tuple[float, int]:
        if self._config.get("recency_gain_decay_mode", "by_round") == "by_time":
            hold_ms = max(0.0, float(self._config.get("recency_hold_ms", 1500)))
            last_refresh_ms = int(last_refresh_ms or now_ms)
            if hold_ms > 0.0 and max(0.0, float(now_ms - last_refresh_ms)) <= hold_ms:
                return round(max(1.0, float(current)), 8), max(0, int(hold_remaining))
            half_life_ms = max(1.0, float(self._config.get("recency_half_life_ms", 60000)))
            dt_ms = max(0.0, float(now_ms - last_refresh_ms) - hold_ms)
            return round(1.0 + (float(current) - 1.0) * math.pow(0.5, dt_ms / half_life_ms), 8), max(0, int(hold_remaining))
        hold_remaining = max(0, int(hold_remaining))
        decay_rounds = max(1, int(round_step))
        if hold_remaining > 0:
            if hold_remaining >= decay_rounds:
                return round(max(1.0, float(current)), 8), hold_remaining - decay_rounds
            decay_rounds -= hold_remaining
        decay_ratio = float(self._config.get("recency_gain_decay_ratio", 0.9999976974))
        return round(max(1.0, float(current) * math.pow(decay_ratio, max(1, decay_rounds))), 8), 0

    def _decay_fatigue(self, current: float, last_ms: int, now_ms: int, round_step: int) -> float:
        if self._config.get("recency_gain_decay_mode", "by_round") == "by_time":
            half_life_ms = max(1.0, float(self._config.get("fatigue_half_life_ms", 60000)))
            dt_ms = max(0.0, float(now_ms - (last_ms or now_ms)))
            return round(float(current) * math.pow(0.5, dt_ms / half_life_ms), 8)
        decay_ratio = float(self._config.get("fatigue_decay_per_tick", 0.92))
        return round(float(current) * math.pow(decay_ratio, max(1, round_step)), 8)

    def _decay_energy(self, current: float, last_ms: int, now_ms: int, round_step: int, *, kind: str) -> float:
        mode = self._config.get("energy_decay_mode", "by_round")
        if mode == "by_time":
            if kind == "er":
                half_life_ms = max(1.0, float(self._config.get("energy_decay_half_life_ms_er", 60000)))
            else:
                half_life_ms = max(1.0, float(self._config.get("energy_decay_half_life_ms_ev", 30000)))
            dt_ms = max(0.0, float(now_ms - (last_ms or now_ms)))
            return round(float(current) * math.pow(0.5, dt_ms / half_life_ms), 8)
        if kind == "er":
            ratio = float(self._config.get("energy_decay_round_ratio_er", 0.97))
        else:
            ratio = float(self._config.get("energy_decay_round_ratio_ev", 0.93))
        return round(float(current) * math.pow(ratio, max(1, round_step)), 8)

    def _recency_peak(self) -> float:
        return max(1.0, float(self._config.get("recency_gain_peak", 10.0)))

    def _recency_hold_rounds(self) -> int:
        return max(0, int(self._config.get("recency_gain_hold_rounds", 2)))

    def _recency_refresh_floor(self) -> float:
        return max(0.0, min(1.0, float(self._config.get("recency_gain_refresh_floor", 0.45))))

    def _target_recent_gain(self, *, strength: float) -> float:
        bounded_strength = max(0.0, min(1.0, float(strength)))
        peak = self._recency_peak()
        return round(1.0 + (peak - 1.0) * bounded_strength, 8)
