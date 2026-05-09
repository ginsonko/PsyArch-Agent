# -*- coding: utf-8 -*-
"""StatePool energy update engine."""

from __future__ import annotations

import time

from ._id_generator import next_id
from ._semantic_identity import semantic_context_key_from_item


class EnergyEngine:
    """Apply energy deltas and maintain activation-side runtime modulation."""

    def __init__(self, config: dict):
        self._config = config
        self._injection_fatigue_total_stats = self._empty_injection_stats()
        self._injection_fatigue_tick_stats: dict[int, dict] = {}
        self._identity_injection_fatigue: dict[str, dict] = {}

    def apply_energy_delta(
        self,
        item: dict,
        delta_er: float,
        delta_ev: float,
        tick_number: int,
        reason: str = "stimulus_apply",
        source_module: str = "",
        trace_id: str = "",
        tick_id: str = "",
        *,
        mark_active: bool = True,
        emit_event: bool = True,
    ) -> dict:
        energy = item["energy"]
        dynamics = item["dynamics"]
        now_ms = int(time.time() * 1000)

        before_er = float(energy["er"])
        before_ev = float(energy["ev"])
        before_cp_delta = float(energy["cognitive_pressure_delta"])
        before_cp_abs = float(energy["cognitive_pressure_abs"])

        requested_delta_er = float(delta_er)
        requested_delta_ev = float(delta_ev)
        adjusted_delta_er, adjusted_delta_ev, injection_fatigue_context = self._scale_positive_injection_delta(
            item=item,
            before_er=before_er,
            before_ev=before_ev,
            requested_delta_er=requested_delta_er,
            requested_delta_ev=requested_delta_ev,
            tick_number=tick_number,
            reason=reason,
            source_module=source_module,
        )

        new_er = before_er + adjusted_delta_er
        new_ev = before_ev + adjusted_delta_ev

        if self._config.get("energy_update_floor_to_zero", True) and not self._config.get("allow_negative_energy", False):
            new_er = max(0.0, new_er)
            new_ev = max(0.0, new_ev)

        new_er = round(new_er, 8)
        new_ev = round(new_ev, 8)
        new_cp_delta = round(new_er - new_ev, 8)
        new_cp_abs = round(abs(new_cp_delta), 8)

        energy["er"] = new_er
        energy["ev"] = new_ev
        energy["cognitive_pressure_delta"] = new_cp_delta
        energy["cognitive_pressure_abs"] = new_cp_abs
        energy["salience_score"] = round(max(new_er, new_ev), 8)

        actual_delta_er = round(new_er - before_er, 8)
        actual_delta_ev = round(new_ev - before_ev, 8)
        delta_cp_delta_val = round(new_cp_delta - before_cp_delta, 8)
        delta_cp_abs_val = round(new_cp_abs - before_cp_abs, 8)

        prev_update_ms = int(dynamics.get("last_update_at", now_ms))
        dt_ms = max(now_ms - prev_update_ms, int(self._config.get("tick_time_floor_ms", 1)))
        dt_s = dt_ms / 1000.0 if dt_ms > 0 else 0.001

        if self._config.get("enable_change_rate_tracking", True):
            er_rate = actual_delta_er / dt_s
            ev_rate = actual_delta_ev / dt_s
            cp_delta_rate = delta_cp_delta_val / dt_s
            cp_abs_rate = delta_cp_abs_val / dt_s
        else:
            er_rate = 0.0
            ev_rate = 0.0
            cp_delta_rate = 0.0
            cp_abs_rate = 0.0

        dynamics["prev_er"] = before_er
        dynamics["prev_ev"] = before_ev
        dynamics["delta_er"] = actual_delta_er
        dynamics["delta_ev"] = actual_delta_ev
        dynamics["er_change_rate"] = round(er_rate, 6)
        dynamics["ev_change_rate"] = round(ev_rate, 6)
        dynamics["prev_cp_delta"] = before_cp_delta
        dynamics["prev_cp_abs"] = before_cp_abs
        dynamics["delta_cp_delta"] = delta_cp_delta_val
        dynamics["delta_cp_abs"] = delta_cp_abs_val
        dynamics["cp_delta_rate"] = round(cp_delta_rate, 6)
        dynamics["cp_abs_rate"] = round(cp_abs_rate, 6)
        dynamics["last_update_tick"] = tick_number
        dynamics["last_update_at"] = now_ms
        dynamics["update_count"] = int(dynamics.get("update_count", 0)) + 1

        if mark_active:
            self._register_activation(item=item, tick_number=tick_number, now_ms=now_ms)

        item["updated_at"] = now_ms

        if not emit_event:
            return {}

        event = self._build_change_event(
            target_item_id=item["id"],
            event_type="energy_update",
            trace_id=trace_id or item.get("trace_id", ""),
            tick_id=tick_id or item.get("tick_id", ""),
            before_er=before_er,
            before_ev=before_ev,
            before_cp_delta=before_cp_delta,
            before_cp_abs=before_cp_abs,
            after_er=new_er,
            after_ev=new_ev,
            after_cp_delta=new_cp_delta,
            after_cp_abs=new_cp_abs,
            delta_er=actual_delta_er,
            delta_ev=actual_delta_ev,
            delta_cp_delta=delta_cp_delta_val,
            delta_cp_abs=delta_cp_abs_val,
            er_rate=er_rate,
            ev_rate=ev_rate,
            cp_delta_rate=cp_delta_rate,
            cp_abs_rate=cp_abs_rate,
            reason=reason,
            source_module=source_module,
        )
        if injection_fatigue_context:
            event.setdefault("extra_context", {}).update(injection_fatigue_context)
        return event

    def apply_decay(
        self,
        item: dict,
        er_ratio: float,
        ev_ratio: float,
        tick_number: int,
        trace_id: str = "",
        tick_id: str = "",
        *,
        emit_event: bool = True,
    ) -> dict:
        if not emit_event:
            energy = item["energy"]
            dynamics = item["dynamics"]
            now_ms = int(time.time() * 1000)
            current_er = float(energy["er"])
            current_ev = float(energy["ev"])
            before_cp_delta = float(energy["cognitive_pressure_delta"])
            before_cp_abs = float(energy["cognitive_pressure_abs"])
            new_er = current_er * float(er_ratio)
            new_ev = current_ev * float(ev_ratio)

            if self._config.get("energy_update_floor_to_zero", True) and not self._config.get("allow_negative_energy", False):
                new_er = max(0.0, new_er)
                new_ev = max(0.0, new_ev)

            new_er = round(new_er, 8)
            new_ev = round(new_ev, 8)
            new_cp_delta = round(new_er - new_ev, 8)
            new_cp_abs = round(abs(new_cp_delta), 8)

            actual_delta_er = round(new_er - current_er, 8)
            actual_delta_ev = round(new_ev - current_ev, 8)
            delta_cp_delta_val = round(new_cp_delta - before_cp_delta, 8)
            delta_cp_abs_val = round(new_cp_abs - before_cp_abs, 8)

            prev_update_ms = int(dynamics.get("last_update_at", now_ms))
            dt_ms = max(now_ms - prev_update_ms, int(self._config.get("tick_time_floor_ms", 1)))
            dt_s = dt_ms / 1000.0 if dt_ms > 0 else 0.001

            if self._config.get("enable_change_rate_tracking", True):
                er_rate = actual_delta_er / dt_s
                ev_rate = actual_delta_ev / dt_s
                cp_delta_rate = delta_cp_delta_val / dt_s
                cp_abs_rate = delta_cp_abs_val / dt_s
            else:
                er_rate = 0.0
                ev_rate = 0.0
                cp_delta_rate = 0.0
                cp_abs_rate = 0.0

            energy["er"] = new_er
            energy["ev"] = new_ev
            energy["cognitive_pressure_delta"] = new_cp_delta
            energy["cognitive_pressure_abs"] = new_cp_abs
            energy["salience_score"] = round(max(new_er, new_ev), 8)
            energy["last_decay_tick"] = tick_number
            energy["last_decay_at"] = now_ms

            dynamics["prev_er"] = current_er
            dynamics["prev_ev"] = current_ev
            dynamics["delta_er"] = actual_delta_er
            dynamics["delta_ev"] = actual_delta_ev
            dynamics["er_change_rate"] = round(er_rate, 6)
            dynamics["ev_change_rate"] = round(ev_rate, 6)
            dynamics["prev_cp_delta"] = before_cp_delta
            dynamics["prev_cp_abs"] = before_cp_abs
            dynamics["delta_cp_delta"] = delta_cp_delta_val
            dynamics["delta_cp_abs"] = delta_cp_abs_val
            dynamics["cp_delta_rate"] = round(cp_delta_rate, 6)
            dynamics["cp_abs_rate"] = round(cp_abs_rate, 6)
            dynamics["last_update_tick"] = tick_number
            dynamics["last_update_at"] = now_ms
            dynamics["update_count"] = int(dynamics.get("update_count", 0)) + 1

            item["updated_at"] = now_ms
            return {}

        energy = item["energy"]
        current_er = float(energy["er"])
        current_ev = float(energy["ev"])
        new_er = current_er * float(er_ratio)
        new_ev = current_ev * float(ev_ratio)

        event = self.apply_energy_delta(
            item=item,
            delta_er=new_er - current_er,
            delta_ev=new_ev - current_ev,
            tick_number=tick_number,
            reason="tick_decay",
            source_module="state_pool",
            trace_id=trace_id,
            tick_id=tick_id,
            mark_active=False,
            emit_event=emit_event,
        )
        if event:
            event["event_type"] = "decay"
        energy["last_decay_tick"] = tick_number
        energy["last_decay_at"] = int(time.time() * 1000)
        return event

    def seed_runtime_modulation(self, item: dict, tick_number: int) -> None:
        self._register_activation(item=item, tick_number=tick_number, now_ms=int(time.time() * 1000))

    def recalc_cognitive_pressure(self, item: dict):
        energy = item["energy"]
        er = float(energy.get("er", 0.0))
        ev = float(energy.get("ev", 0.0))
        energy["cognitive_pressure_delta"] = round(er - ev, 8)
        energy["cognitive_pressure_abs"] = round(abs(er - ev), 8)

    def _register_activation(self, *, item: dict, tick_number: int, now_ms: int) -> None:
        energy = item.setdefault("energy", {})
        lifecycle = item.setdefault("lifecycle", {})

        history = self._trim_recent_activation_ticks(lifecycle.get("recent_activation_ticks", []), tick_number)
        if not history or int(history[-1]) != int(tick_number):
            history.append(int(tick_number))

        lifecycle["recent_activation_ticks"] = history
        lifecycle["last_active_tick"] = int(tick_number)
        lifecycle["last_recency_refresh_tick"] = int(tick_number)
        lifecycle["recency_hold_ticks_remaining"] = self._recency_hold_ticks()

        energy["recency_gain"] = self._recency_peak()
        energy["fatigue"] = self._fatigue_from_count(len(history))
        energy.setdefault("last_decay_tick", 0)
        energy.setdefault("last_decay_at", now_ms)
        item["updated_at"] = now_ms

    def _trim_recent_activation_ticks(self, history: list[int] | tuple[int, ...], current_tick: int) -> list[int]:
        window = max(1, int(self._config.get("fatigue_window_ticks", 12)))
        min_tick = int(current_tick) - window + 1
        trimmed: list[int] = []
        for tick in history or ():
            if isinstance(tick, int):
                tick_value = tick
            else:
                text = str(tick)
                if not text.isdigit():
                    continue
                tick_value = int(text)
            if tick_value >= min_tick:
                trimmed.append(tick_value)
        return trimmed

    def _fatigue_from_count(self, count: int) -> float:
        threshold = max(1, int(self._config.get("fatigue_threshold_count", 3)))
        window = max(threshold, int(self._config.get("fatigue_window_ticks", 12)))
        max_value = max(0.0, min(1.0, float(self._config.get("fatigue_max_value", 1.0))))
        if int(count) < threshold:
            return 0.0
        numerator = int(count) - threshold + 1
        denominator = max(1, window - threshold + 1)
        return round(max_value * min(1.0, float(numerator) / float(denominator)), 8)

    def _recency_peak(self) -> float:
        return round(max(1.0, float(self._config.get("recency_gain_peak", 10.0))), 8)

    def _recency_hold_ticks(self) -> int:
        return max(0, int(self._config.get("recency_gain_hold_ticks", 2)))

    def _scale_positive_injection_delta(
        self,
        *,
        item: dict,
        before_er: float,
        before_ev: float,
        requested_delta_er: float,
        requested_delta_ev: float,
        tick_number: int,
        reason: str,
        source_module: str,
    ) -> tuple[float, float, dict]:
        has_positive_er = requested_delta_er > 0.0
        has_positive_ev = requested_delta_ev > 0.0
        if not (has_positive_er or has_positive_ev):
            return requested_delta_er, requested_delta_ev, {}

        if not bool(self._config.get("energy_injection_fatigue_enabled", True)):
            return requested_delta_er, requested_delta_ev, {}

        bypass_reasons = self._config.get("energy_injection_fatigue_bypass_reasons", [])
        if isinstance(bypass_reasons, str):
            bypass_set = {bypass_reasons}
        else:
            try:
                bypass_set = {str(value) for value in (bypass_reasons or [])}
            except Exception:
                bypass_set = set()
        if str(reason or "") in bypass_set:
            return requested_delta_er, requested_delta_ev, {
                "energy_injection_fatigue_enabled": True,
                "energy_injection_fatigue_bypassed": True,
                "energy_injection_fatigue_bypass_reason": str(reason or ""),
                "energy_injection_requested_er": round(requested_delta_er, 8),
                "energy_injection_requested_ev": round(requested_delta_ev, 8),
                "energy_injection_applied_er": round(requested_delta_er, 8),
                "energy_injection_applied_ev": round(requested_delta_ev, 8),
            }

        same_side_knee_er = self._positive_float("energy_injection_fatigue_same_side_knee_er", 4.0)
        same_side_knee_ev = self._positive_float("energy_injection_fatigue_same_side_knee_ev", 3.0)
        total_knee = self._positive_float("energy_injection_fatigue_total_knee", 8.0)
        power = self._positive_float("energy_injection_fatigue_saturation_power", 1.25)
        min_scale = self._clamped_float("energy_injection_fatigue_min_scale", 0.18, 0.0, 1.0)
        total_weight = self._clamped_float("energy_injection_fatigue_total_weight", 0.35, 0.0, 1.0)
        repeat_enabled = bool(self._config.get("energy_injection_repeat_fatigue_enabled", True))
        repeat_identity_enabled = bool(self._config.get("energy_injection_repeat_fatigue_identity_enabled", True))
        repeat_step = self._positive_float("energy_injection_repeat_fatigue_step", 0.35)
        repeat_decay = self._clamped_float("energy_injection_repeat_fatigue_decay_per_tick", 0.86, 0.0, 1.0)
        repeat_floor_scale = self._clamped_float("energy_injection_repeat_fatigue_floor_scale", 0.35, 0.0, 1.0)
        repeat_identity_weight = self._clamped_float("energy_injection_repeat_fatigue_identity_weight", 1.0, 0.0, 1.0)

        fatigue = item.setdefault("energy", {}).setdefault("injection_fatigue", {})
        if not isinstance(fatigue, dict):
            fatigue = {}
            item.setdefault("energy", {})["injection_fatigue"] = fatigue
        identity_key = self._injection_fatigue_identity_key(item)
        identity_fatigue = self._identity_injection_fatigue.setdefault(identity_key, {}) if identity_key and repeat_identity_enabled else {}

        same_side_scale_er = self._saturation_scale(before_er, same_side_knee_er, power)
        same_side_scale_ev = self._saturation_scale(before_ev, same_side_knee_ev, power)
        total_saturation = self._saturation_fraction(before_er + before_ev, total_knee, power)
        total_scale = max(min_scale, 1.0 - total_weight * total_saturation)

        repeat_er_before = self._repeat_fatigue_before(
            fatigue=fatigue,
            side="er",
            tick_number=tick_number,
            repeat_decay=repeat_decay,
        ) if repeat_enabled else 0.0
        repeat_ev_before = self._repeat_fatigue_before(
            fatigue=fatigue,
            side="ev",
            tick_number=tick_number,
            repeat_decay=repeat_decay,
        ) if repeat_enabled else 0.0
        identity_er_before = self._repeat_fatigue_before(
            fatigue=identity_fatigue,
            side="er",
            tick_number=tick_number,
            repeat_decay=repeat_decay,
        ) if repeat_enabled and identity_fatigue is not fatigue else 0.0
        identity_ev_before = self._repeat_fatigue_before(
            fatigue=identity_fatigue,
            side="ev",
            tick_number=tick_number,
            repeat_decay=repeat_decay,
        ) if repeat_enabled and identity_fatigue is not fatigue else 0.0
        effective_repeat_er = max(float(repeat_er_before), float(identity_er_before) * float(repeat_identity_weight))
        effective_repeat_ev = max(float(repeat_ev_before), float(identity_ev_before) * float(repeat_identity_weight))
        repeat_scale_er = max(repeat_floor_scale, 1.0 / (1.0 + effective_repeat_er)) if repeat_enabled else 1.0
        repeat_scale_ev = max(repeat_floor_scale, 1.0 / (1.0 + effective_repeat_ev)) if repeat_enabled else 1.0

        scale_er = 1.0
        scale_ev = 1.0
        if has_positive_er:
            scale_er = max(min_scale, min(1.0, same_side_scale_er * total_scale * repeat_scale_er))
        if has_positive_ev:
            scale_ev = max(min_scale, min(1.0, same_side_scale_ev * total_scale * repeat_scale_ev))

        adjusted_delta_er = requested_delta_er * scale_er if has_positive_er else requested_delta_er
        adjusted_delta_ev = requested_delta_ev * scale_ev if has_positive_ev else requested_delta_ev
        throttled_er = max(0.0, requested_delta_er - adjusted_delta_er) if has_positive_er else 0.0
        throttled_ev = max(0.0, requested_delta_ev - adjusted_delta_ev) if has_positive_ev else 0.0
        hit_count = int(has_positive_er and throttled_er > 1e-12) + int(has_positive_ev and throttled_ev > 1e-12)

        if repeat_enabled:
            if has_positive_er:
                fatigue["repeat_er"] = round(repeat_er_before + repeat_step, 8)
                fatigue["last_er_tick"] = int(tick_number)
                if identity_fatigue is not fatigue:
                    identity_fatigue["repeat_er"] = round(identity_er_before + repeat_step, 8)
                    identity_fatigue["last_er_tick"] = int(tick_number)
            if has_positive_ev:
                fatigue["repeat_ev"] = round(repeat_ev_before + repeat_step, 8)
                fatigue["last_ev_tick"] = int(tick_number)
                if identity_fatigue is not fatigue:
                    identity_fatigue["repeat_ev"] = round(identity_ev_before + repeat_step, 8)
                    identity_fatigue["last_ev_tick"] = int(tick_number)
            if identity_fatigue is not fatigue:
                identity_fatigue["last_tick"] = int(tick_number)
                identity_fatigue["last_item_id"] = str(item.get("id", "") or "")

        previous_requested_er_total = float(fatigue.get("total_requested_er", 0.0) or 0.0)
        previous_requested_ev_total = float(fatigue.get("total_requested_ev", 0.0) or 0.0)
        previous_applied_er_total = float(fatigue.get("total_applied_er", 0.0) or 0.0)
        previous_applied_ev_total = float(fatigue.get("total_applied_ev", 0.0) or 0.0)
        previous_throttled_er_total = float(fatigue.get("total_throttled_er", 0.0) or 0.0)
        previous_throttled_ev_total = float(fatigue.get("total_throttled_ev", 0.0) or 0.0)

        fatigue["last_tick"] = int(tick_number)
        fatigue["last_reason"] = str(reason or "")
        fatigue["last_source_module"] = str(source_module or "")
        fatigue["last_requested_er"] = round(requested_delta_er if has_positive_er else 0.0, 8)
        fatigue["last_requested_ev"] = round(requested_delta_ev if has_positive_ev else 0.0, 8)
        fatigue["last_applied_er"] = round(adjusted_delta_er if has_positive_er else 0.0, 8)
        fatigue["last_applied_ev"] = round(adjusted_delta_ev if has_positive_ev else 0.0, 8)
        fatigue["last_throttled_er"] = round(throttled_er, 8)
        fatigue["last_throttled_ev"] = round(throttled_ev, 8)
        fatigue["last_scale_er"] = round(scale_er if has_positive_er else 1.0, 8)
        fatigue["last_scale_ev"] = round(scale_ev if has_positive_ev else 1.0, 8)
        fatigue["last_hit_count"] = hit_count
        fatigue["hit_count"] = int(fatigue.get("hit_count", 0) or 0) + hit_count
        fatigue["total_requested_er"] = round(previous_requested_er_total + (requested_delta_er if has_positive_er else 0.0), 8)
        fatigue["total_requested_ev"] = round(previous_requested_ev_total + (requested_delta_ev if has_positive_ev else 0.0), 8)
        fatigue["total_applied_er"] = round(previous_applied_er_total + (adjusted_delta_er if has_positive_er else 0.0), 8)
        fatigue["total_applied_ev"] = round(previous_applied_ev_total + (adjusted_delta_ev if has_positive_ev else 0.0), 8)
        fatigue["total_throttled_er"] = round(previous_throttled_er_total + throttled_er, 8)
        fatigue["total_throttled_ev"] = round(previous_throttled_ev_total + throttled_ev, 8)
        self._record_injection_fatigue_stats(
            tick_number=tick_number,
            item_id=str(item.get("id", "") or ""),
            requested_er=requested_delta_er if has_positive_er else 0.0,
            requested_ev=requested_delta_ev if has_positive_ev else 0.0,
            applied_er=adjusted_delta_er if has_positive_er else 0.0,
            applied_ev=adjusted_delta_ev if has_positive_ev else 0.0,
            throttled_er=throttled_er,
            throttled_ev=throttled_ev,
            hit_count=hit_count,
            min_scale=min(scale_er if has_positive_er else 1.0, scale_ev if has_positive_ev else 1.0),
        )

        context = {
            "energy_injection_fatigue_enabled": True,
            "energy_injection_fatigue_bypassed": False,
            "energy_injection_requested_er": round(requested_delta_er, 8),
            "energy_injection_requested_ev": round(requested_delta_ev, 8),
            "energy_injection_applied_er": round(adjusted_delta_er, 8),
            "energy_injection_applied_ev": round(adjusted_delta_ev, 8),
            "energy_injection_throttled_er": round(throttled_er, 8),
            "energy_injection_throttled_ev": round(throttled_ev, 8),
            "energy_injection_scale_er": round(scale_er if has_positive_er else 1.0, 8),
            "energy_injection_scale_ev": round(scale_ev if has_positive_ev else 1.0, 8),
            "energy_injection_same_side_scale_er": round(same_side_scale_er, 8),
            "energy_injection_same_side_scale_ev": round(same_side_scale_ev, 8),
            "energy_injection_total_scale": round(total_scale, 8),
            "energy_injection_repeat_fatigue_before_er": round(repeat_er_before, 8),
            "energy_injection_repeat_fatigue_before_ev": round(repeat_ev_before, 8),
            "energy_injection_repeat_identity_key": identity_key,
            "energy_injection_repeat_identity_fatigue_before_er": round(identity_er_before, 8),
            "energy_injection_repeat_identity_fatigue_before_ev": round(identity_ev_before, 8),
            "energy_injection_repeat_effective_fatigue_er": round(effective_repeat_er, 8),
            "energy_injection_repeat_effective_fatigue_ev": round(effective_repeat_ev, 8),
            "energy_injection_repeat_scale_er": round(repeat_scale_er, 8),
            "energy_injection_repeat_scale_ev": round(repeat_scale_ev, 8),
        }
        return adjusted_delta_er, adjusted_delta_ev, context

    def _injection_fatigue_identity_key(self, item: dict) -> str:
        key = str(item.get("semantic_context_key", "") or "").strip()
        if not key:
            key = str(semantic_context_key_from_item(item) or "").strip()
        if key:
            return f"semctx:{key}"
        ref_type = str(item.get("ref_object_type", "") or "").strip()
        ref_id = str(item.get("ref_object_id", "") or "").strip()
        if ref_id:
            return f"ref:{ref_type}:{ref_id}" if ref_type else f"ref:{ref_id}"
        item_id = str(item.get("id", "") or "").strip()
        return f"item:{item_id}" if item_id else ""

    def _repeat_fatigue_before(
        self,
        *,
        fatigue: dict,
        side: str,
        tick_number: int,
        repeat_decay: float,
    ) -> float:
        raw_value = float(fatigue.get(f"repeat_{side}", 0.0) or 0.0)
        try:
            last_tick = int(fatigue.get(f"last_{side}_tick", tick_number) or tick_number)
        except Exception:
            last_tick = int(tick_number)
        elapsed = max(0, int(tick_number) - last_tick)
        if elapsed > 0 and raw_value > 0.0:
            raw_value *= float(repeat_decay) ** elapsed
        if raw_value < 1e-9:
            raw_value = 0.0
        fatigue[f"repeat_{side}"] = round(raw_value, 8)
        return max(0.0, raw_value)

    @staticmethod
    def _saturation_fraction(value: float, knee: float, power: float) -> float:
        value = max(0.0, float(value))
        knee = max(1e-9, float(knee))
        power = max(1e-9, float(power))
        if value <= 0.0:
            return 0.0
        numerator = value ** power
        denominator = numerator + (knee ** power)
        if denominator <= 0.0:
            return 0.0
        return max(0.0, min(1.0, numerator / denominator))

    @classmethod
    def _saturation_scale(cls, value: float, knee: float, power: float) -> float:
        return max(0.0, min(1.0, 1.0 - cls._saturation_fraction(value, knee, power)))

    def _positive_float(self, key: str, default: float) -> float:
        try:
            value = float(self._config.get(key, default))
        except Exception:
            value = float(default)
        return max(1e-9, value)

    def _clamped_float(self, key: str, default: float, min_value: float, max_value: float) -> float:
        try:
            value = float(self._config.get(key, default))
        except Exception:
            value = float(default)
        return max(float(min_value), min(float(max_value), value))

    @staticmethod
    def _empty_injection_stats() -> dict:
        return {
            "event_count": 0,
            "side_hit_count": 0,
            "requested_er": 0.0,
            "requested_ev": 0.0,
            "applied_er": 0.0,
            "applied_ev": 0.0,
            "throttled_er": 0.0,
            "throttled_ev": 0.0,
            "min_scale": 1.0,
            "_item_ids": set(),
        }

    def _record_injection_fatigue_stats(
        self,
        *,
        tick_number: int,
        item_id: str,
        requested_er: float,
        requested_ev: float,
        applied_er: float,
        applied_ev: float,
        throttled_er: float,
        throttled_ev: float,
        hit_count: int,
        min_scale: float,
    ) -> None:
        tick_key = int(tick_number)
        tick_stats = self._injection_fatigue_tick_stats.setdefault(tick_key, self._empty_injection_stats())
        for stats in (self._injection_fatigue_total_stats, tick_stats):
            stats["event_count"] = int(stats.get("event_count", 0) or 0) + 1
            stats["side_hit_count"] = int(stats.get("side_hit_count", 0) or 0) + int(hit_count)
            stats["requested_er"] = round(float(stats.get("requested_er", 0.0) or 0.0) + float(requested_er), 8)
            stats["requested_ev"] = round(float(stats.get("requested_ev", 0.0) or 0.0) + float(requested_ev), 8)
            stats["applied_er"] = round(float(stats.get("applied_er", 0.0) or 0.0) + float(applied_er), 8)
            stats["applied_ev"] = round(float(stats.get("applied_ev", 0.0) or 0.0) + float(applied_ev), 8)
            stats["throttled_er"] = round(float(stats.get("throttled_er", 0.0) or 0.0) + float(throttled_er), 8)
            stats["throttled_ev"] = round(float(stats.get("throttled_ev", 0.0) or 0.0) + float(throttled_ev), 8)
            stats["min_scale"] = round(min(float(stats.get("min_scale", 1.0) or 1.0), float(min_scale)), 8)
            item_ids = stats.setdefault("_item_ids", set())
            if isinstance(item_ids, set) and item_id:
                item_ids.add(item_id)
        self._prune_injection_fatigue_tick_stats()

    def _prune_injection_fatigue_tick_stats(self) -> None:
        try:
            keep_ticks = int(self._config.get("energy_injection_fatigue_stats_keep_ticks", 256) or 256)
        except Exception:
            keep_ticks = 256
        keep_ticks = max(8, keep_ticks)
        if len(self._injection_fatigue_tick_stats) <= keep_ticks:
            return
        for tick_key in sorted(self._injection_fatigue_tick_stats)[: max(0, len(self._injection_fatigue_tick_stats) - keep_ticks)]:
            self._injection_fatigue_tick_stats.pop(tick_key, None)

    @classmethod
    def _public_injection_stats(cls, stats: dict | None) -> dict:
        stats = stats if isinstance(stats, dict) else cls._empty_injection_stats()
        requested_er = float(stats.get("requested_er", 0.0) or 0.0)
        requested_ev = float(stats.get("requested_ev", 0.0) or 0.0)
        throttled_er = float(stats.get("throttled_er", 0.0) or 0.0)
        throttled_ev = float(stats.get("throttled_ev", 0.0) or 0.0)
        item_ids = stats.get("_item_ids", set())
        item_count = len(item_ids) if isinstance(item_ids, set) else 0
        total_requested = requested_er + requested_ev
        total_throttled = throttled_er + throttled_ev
        return {
            "event_count": int(stats.get("event_count", 0) or 0),
            "item_count": int(item_count),
            "side_hit_count": int(stats.get("side_hit_count", 0) or 0),
            "requested_er": round(requested_er, 8),
            "requested_ev": round(requested_ev, 8),
            "applied_er": round(float(stats.get("applied_er", 0.0) or 0.0), 8),
            "applied_ev": round(float(stats.get("applied_ev", 0.0) or 0.0), 8),
            "throttled_er": round(throttled_er, 8),
            "throttled_ev": round(throttled_ev, 8),
            "throttle_ratio_er": round(throttled_er / requested_er, 8) if requested_er > 1e-12 else 0.0,
            "throttle_ratio_ev": round(throttled_ev / requested_ev, 8) if requested_ev > 1e-12 else 0.0,
            "throttle_ratio_total": round(total_throttled / total_requested, 8) if total_requested > 1e-12 else 0.0,
            "min_scale": round(float(stats.get("min_scale", 1.0) or 1.0), 8),
        }

    def get_injection_fatigue_stats(self, current_tick: int | None = None) -> dict:
        current = self._injection_fatigue_tick_stats.get(int(current_tick), None) if current_tick is not None else None
        return {
            "enabled": bool(self._config.get("energy_injection_fatigue_enabled", True)),
            "current_tick": int(current_tick or 0),
            "current_tick_stats": self._public_injection_stats(current),
            "total_stats": self._public_injection_stats(self._injection_fatigue_total_stats),
        }

    def reset_runtime_stats(self) -> None:
        self._injection_fatigue_total_stats = self._empty_injection_stats()
        self._injection_fatigue_tick_stats.clear()
        self._identity_injection_fatigue.clear()

    @staticmethod
    def _build_change_event(
        target_item_id: str,
        event_type: str,
        trace_id: str,
        tick_id: str,
        before_er: float,
        before_ev: float,
        before_cp_delta: float,
        before_cp_abs: float,
        after_er: float,
        after_ev: float,
        after_cp_delta: float,
        after_cp_abs: float,
        delta_er: float,
        delta_ev: float,
        delta_cp_delta: float,
        delta_cp_abs: float,
        er_rate: float,
        ev_rate: float,
        cp_delta_rate: float,
        cp_abs_rate: float,
        reason: str,
        source_module: str,
    ) -> dict:
        return {
            "event_id": next_id("sce"),
            "event_type": event_type,
            "target_item_id": target_item_id,
            "trace_id": trace_id,
            "tick_id": tick_id,
            "timestamp_ms": int(time.time() * 1000),
            "before": {
                "er": round(before_er, 8),
                "ev": round(before_ev, 8),
                "cp_delta": round(before_cp_delta, 8),
                "cp_abs": round(before_cp_abs, 8),
            },
            "after": {
                "er": round(after_er, 8),
                "ev": round(after_ev, 8),
                "cp_delta": round(after_cp_delta, 8),
                "cp_abs": round(after_cp_abs, 8),
            },
            "delta": {
                "delta_er": round(delta_er, 8),
                "delta_ev": round(delta_ev, 8),
                "delta_cp_delta": round(delta_cp_delta, 8),
                "delta_cp_abs": round(delta_cp_abs, 8),
            },
            "rate": {
                "er_change_rate": round(er_rate, 6),
                "ev_change_rate": round(ev_rate, 6),
                "cp_delta_rate": round(cp_delta_rate, 6),
                "cp_abs_rate": round(cp_abs_rate, 6),
            },
            "reason": reason,
            "source_module": source_module,
            "extra_context": {},
        }

    def update_config(self, config: dict):
        self._config = config
