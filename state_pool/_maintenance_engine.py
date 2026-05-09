# -*- coding: utf-8 -*-
"""StatePool tick maintenance engine."""

from __future__ import annotations

import time


class MaintenanceEngine:
    def __init__(self, config: dict):
        self._config = config

    @staticmethod
    def _extract_attribute_name(attribute_sa: dict) -> str:
        content = attribute_sa.get("content", {}) if isinstance(attribute_sa.get("content", {}), dict) else {}
        name = str(content.get("attribute_name", "") or "").strip()
        if name:
            return name
        raw = str(content.get("raw", "") or "")
        if ":" in raw:
            return raw.split(":", 1)[0].strip()
        return ""

    def _decay_bound_attributes(self, *, item: dict, tick_number: int, now_ms: int) -> int:
        """
        Decay runtime-bound attribute SA energies (CFS/time-feeling/rwd/pun tags, etc.).

        Why:
        - These attributes are part of the StatePool "live state" and should behave like
          other slow variables: they persist and fade by a half-life/decay ratio.
        - Without this, UIs tend to show only "trigger peaks" instead of a maintained state.
        """
        if not bool(self._config.get("bound_attribute_apply_decay", True)):
            return 0

        ext = item.get("ext", {}) if isinstance(item.get("ext", {}), dict) else {}
        attrs = ext.get("bound_attributes", []) if isinstance(ext.get("bound_attributes", []), list) else []
        if not attrs:
            return 0

        er_ratio = float(self._config.get("bound_attribute_er_decay_ratio", 0.97) or 0.97)
        ev_ratio = float(self._config.get("bound_attribute_ev_decay_ratio", 0.97) or 0.97)
        er_ratio = max(0.0, min(1.0, er_ratio))
        ev_ratio = max(0.0, min(1.0, ev_ratio))

        ignore_names = self._config.get("bound_attribute_decay_ignore_names", [])
        ignore: set[str] = set(str(x).strip() for x in (ignore_names or []) if str(x).strip())

        decayed = 0
        for a in attrs:
            if not isinstance(a, dict):
                continue
            name = self._extract_attribute_name(a)
            if name and name in ignore:
                continue
            energy = a.get("energy", {}) if isinstance(a.get("energy", {}), dict) else {}
            er0 = float(energy.get("er", 0.0) or 0.0)
            ev0 = float(energy.get("ev", 0.0) or 0.0)
            er1 = round(er0 * er_ratio, 8)
            ev1 = round(ev0 * ev_ratio, 8)
            if er1 != er0 or ev1 != ev0:
                a["energy"] = {"er": er1, "ev": ev1}
                a.setdefault("meta", {}).setdefault("ext", {})["last_decay_tick"] = int(tick_number)
                a["updated_at"] = int(max(int(a.get("updated_at", 0) or 0), now_ms))
                decayed += 1
        return int(decayed)

    def _soft_capacity_profile(self, item_count: int) -> dict:
        """
        Soft capacity decay modulation / 软上限衰减调制

        Chinese:
          当状态池对象数量超过“软上限”后，维护阶段的衰减会变得更激进，
          以避免对象数量与能量残留无界增长（尤其是原型调试阶段）。

        English:
          When active item count exceeds the soft-cap threshold, we increase
          the decay aggressiveness so the pool naturally self-tightens.

        Implementation note / 实现说明：
          We modulate decay by applying a "decay power" to the base retention ratio:
            ratio' = ratio ** power
          - power == 1   => unchanged
          - power > 1    => ratio decreases => stronger decay
          This keeps ratios in (0, 1) and preserves the per-type override semantics.
        """
        enabled = bool(self._config.get("soft_capacity_enabled", True))
        start_items = int(self._config.get("soft_capacity_start_items", 200) or 200)
        full_items = int(self._config.get("soft_capacity_full_items", 400) or 400)
        power_max = float(self._config.get("soft_capacity_decay_power_max", 6.0) or 6.0)

        start_items = max(0, start_items)
        full_items = max(start_items + 1, full_items)
        power_max = max(1.0, power_max)

        pressure_ratio = 0.0
        if enabled and item_count > start_items:
            if item_count >= full_items:
                pressure_ratio = 1.0
            else:
                pressure_ratio = float(item_count - start_items) / float(full_items - start_items)
                pressure_ratio = max(0.0, min(1.0, pressure_ratio))

        decay_power = 1.0 + (power_max - 1.0) * pressure_ratio
        return {
            "enabled": enabled,
            "active_item_count": int(item_count),
            "start_items": int(start_items),
            "full_items": int(full_items),
            "pressure_ratio": round(float(pressure_ratio), 6),
            "decay_power": round(float(decay_power), 6),
            "decay_power_max": round(float(power_max), 6),
        }

    @staticmethod
    def _apply_decay_power(ratio: float, power: float) -> float:
        # Defensive clamp: keep ratio within (0, 1].
        # 防御性钳制：保证 ratio 在 (0,1] 范围内。
        r = float(ratio)
        if r <= 0.0:
            return 0.0
        if r >= 1.0:
            return 1.0
        p = max(1.0, float(power))
        return max(0.0, min(1.0, r ** p))

    def run_maintenance(
        self,
        pool_store,
        energy_engine,
        neutralization_engine,
        merge_engine,
        tick_number: int,
        trace_id: str,
        tick_id: str,
        apply_decay: bool = True,
        apply_neutralization: bool = True,
        apply_prune: bool = True,
        apply_merge: bool = True,
    ) -> dict:
        del merge_engine, apply_merge

        all_events: list[dict] = []
        items = pool_store.get_all()
        before_count = len(items)
        soft = self._soft_capacity_profile(before_count)
        decay_power = float(soft.get("decay_power", 1.0) or 1.0)
        now_ms = int(time.time() * 1000)

        decayed_count = 0
        decayed_bound_attr_count = 0
        runtime_resolution_refreshed_count = 0
        runtime_resolution_degraded_count = 0
        neutralized_count = 0
        pruned_count = 0
        merged_count = 0
        emit_decay_events = bool(self._config.get("maintenance_emit_decay_events_enabled", False))

        if apply_decay:
            decay_ratio_cache: dict[str, tuple[float, float]] = {}
            for item in items:
                ref_type = item.get("ref_object_type", "")
                cached_ratios = decay_ratio_cache.get(ref_type)
                if cached_ratios is None:
                    er_ratio, ev_ratio = self._get_decay_ratios(ref_type)
                    # Soft-cap modulation / 软上限调制：对象越多，衰减越激进。
                    er_ratio = self._apply_decay_power(er_ratio, decay_power)
                    ev_ratio = self._apply_decay_power(ev_ratio, decay_power)
                    cached_ratios = (er_ratio, ev_ratio)
                    decay_ratio_cache[ref_type] = cached_ratios
                else:
                    er_ratio, ev_ratio = cached_ratios
                event = energy_engine.apply_decay(
                    item=item,
                    er_ratio=er_ratio,
                    ev_ratio=ev_ratio,
                    tick_number=tick_number,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    emit_event=emit_decay_events,
                )
                if emit_decay_events and event:
                    all_events.append(event)
                decayed_count += 1
                decayed_bound_attr_count += self._decay_bound_attributes(item=item, tick_number=tick_number, now_ms=now_ms)
                if self._refresh_runtime_resolution_after_decay(
                    item=item,
                    er_ratio=er_ratio,
                    ev_ratio=ev_ratio,
                    tick_number=tick_number,
                    now_ms=now_ms,
                ):
                    runtime_resolution_refreshed_count += 1
                    runtime_resolution = (
                        item.get("meta", {}).get("ext", {}).get("runtime_resolution", {})
                        if isinstance(item.get("meta", {}).get("ext", {}).get("runtime_resolution", {}), dict)
                        else {}
                    )
                    if bool(runtime_resolution.get("is_degraded", False)):
                        runtime_resolution_degraded_count += 1

        neut_stage = self._config.get("neutralization_apply_stage", "maintenance")
        if apply_neutralization and neut_stage in ("maintenance", "both"):
            for item in items:
                event = neutralization_engine.neutralize(
                    item=item,
                    tick_number=tick_number,
                    trace_id=trace_id,
                    tick_id=tick_id,
                )
                if event:
                    all_events.append(event)
                    neutralized_count += 1

        for item in items:
            self._refresh_runtime_modulation(item=item, tick_number=tick_number, now_ms=now_ms)

        if apply_prune:
            er_thresh = float(self._config.get("er_elimination_threshold", 0.05))
            ev_thresh = float(self._config.get("ev_elimination_threshold", 0.05))
            cp_ignore = float(self._config.get("cp_elimination_ignore_below", 0.02))
            prune_both = bool(self._config.get("prune_if_both_energy_low", True))

            to_prune = []
            for item in items:
                energy = item["energy"]
                er_low = float(energy.get("er", 0.0)) < er_thresh
                ev_low = float(energy.get("ev", 0.0)) < ev_thresh
                cp_low = float(energy.get("cognitive_pressure_abs", 0.0)) < cp_ignore

                should_prune = False
                if prune_both and er_low and ev_low:
                    should_prune = True
                elif er_low and ev_low and cp_low:
                    should_prune = True

                if should_prune:
                    to_prune.append(item["id"])

            for spi_id in to_prune:
                removed = pool_store.remove(spi_id)
                if removed:
                    pruned_count += 1
                    all_events.append(
                        {
                            "event_id": f"prune_{spi_id}",
                            "event_type": "pruned",
                            "target_item_id": spi_id,
                            "trace_id": trace_id,
                            "tick_id": tick_id,
                            "timestamp_ms": now_ms,
                            "reason": "both_energy_below_threshold",
                            "before": {
                                "er": removed["energy"]["er"],
                                "ev": removed["energy"]["ev"],
                            },
                            "source_module": "state_pool",
                        }
                    )

        after_items = pool_store.get_all()
        after_count = len(after_items)
        fast_cp_rise = float(self._config.get("fast_cp_rise_threshold", 0.5))
        fast_cp_drop = float(self._config.get("fast_cp_drop_threshold", -0.5))

        high_cp = sum(1 for item in after_items if float(item["energy"].get("cognitive_pressure_abs", 0.0)) >= 0.5)
        fast_rise = sum(1 for item in after_items if float(item["dynamics"].get("delta_cp_abs", 0.0)) >= fast_cp_rise)
        fast_drop = sum(1 for item in after_items if float(item["dynamics"].get("delta_cp_abs", 0.0)) <= fast_cp_drop)

        return {
            "events": all_events,
            "summary": {
                "before_item_count": before_count,
                "after_item_count": after_count,
                "decayed_item_count": decayed_count,
                "decayed_bound_attribute_count": int(decayed_bound_attr_count),
                "runtime_resolution_refreshed_item_count": int(runtime_resolution_refreshed_count),
                "runtime_resolution_degraded_item_count": int(runtime_resolution_degraded_count),
                "neutralized_item_count": neutralized_count,
                "pruned_item_count": pruned_count,
                "merged_item_count": merged_count,
                "high_cp_item_count": high_cp,
                "fast_cp_drop_item_count": fast_drop,
                "fast_cp_rise_item_count": fast_rise,
                "soft_capacity": soft,
            },
        }

    def _refresh_runtime_resolution_after_decay(
        self,
        *,
        item: dict,
        er_ratio: float,
        ev_ratio: float,
        tick_number: int,
        now_ms: int,
    ) -> bool:
        if not bool(self._config.get("runtime_structure_resolution_degradation_enabled", True)):
            return False
        if not isinstance(item, dict) or str(item.get("ref_object_type", "") or "").strip() != "st":
            return False

        meta = item.setdefault("meta", {})
        if not isinstance(meta, dict):
            meta = {}
            item["meta"] = meta
        meta_ext = meta.setdefault("ext", {})
        if not isinstance(meta_ext, dict):
            meta_ext = {}
            meta["ext"] = meta_ext
        component_energy = meta_ext.get("component_energy", {})
        if not isinstance(component_energy, dict) or not component_energy:
            return False

        for key, ratio in (
            ("source_component_er_share", er_ratio),
            ("source_component_ev_share", ev_ratio),
            ("residual_component_er_share", er_ratio),
            ("residual_component_ev_share", ev_ratio),
        ):
            if key in component_energy:
                try:
                    component_energy[key] = round(float(component_energy.get(key, 0.0) or 0.0) * float(ratio), 8)
                except Exception:
                    pass
        self._decay_nested_component_energy(component_energy, er_ratio=er_ratio, ev_ratio=ev_ratio)

        total_er = self._component_energy_total(component_energy, "er")
        total_ev = self._component_energy_total(component_energy, "ev")
        try:
            floor = max(
                0.0,
                float(self._config.get("runtime_structure_resolution_component_energy_floor", 0.05) or 0.05),
            )
        except Exception:
            floor = 0.05
        active_count, dropped_count = self._component_energy_count(component_energy, floor=floor)
        if active_count == 0 and (total_er + total_ev) > 0.0:
            active_count = 1
        original_count = active_count + dropped_count
        resolution_ratio = 1.0 if original_count <= 0 else max(0.0, min(1.0, active_count / original_count))
        runtime_resolution = meta_ext.setdefault("runtime_resolution", {})
        if not isinstance(runtime_resolution, dict):
            runtime_resolution = {}
            meta_ext["runtime_resolution"] = runtime_resolution
        root_structure_id = str(runtime_resolution.get("root_structure_id", "") or "").strip()
        if not root_structure_id and str(item.get("ref_object_type", "") or "") == "st":
            root_structure_id = str(item.get("ref_object_id", "") or "").strip()
        runtime_resolution.update(
            {
                "enabled": True,
                "root_structure_id": root_structure_id,
                "degradation_semantics": "state_pool_resolution_drop_only",
                "hdb_identity_re_resolved": False,
                "hdb_write_on_degrade": False,
                "component_energy_floor": round(floor, 8),
                "component_total_er": round(float(total_er), 8),
                "component_total_ev": round(float(total_ev), 8),
                "active_component_count": int(active_count),
                "dropped_component_count": int(dropped_count),
                "resolution_ratio": round(float(resolution_ratio), 8),
                "is_degraded": bool(dropped_count > 0),
                "last_decay_tick": int(tick_number),
            }
        )
        item_ext = item.setdefault("ext", {})
        if isinstance(item_ext, dict):
            item_ext["runtime_root_structure_id"] = root_structure_id
        item["updated_at"] = max(int(item.get("updated_at", 0) or 0), int(now_ms))
        return True

    @staticmethod
    def _decay_nested_component_energy(component_energy: dict, *, er_ratio: float, ev_ratio: float) -> None:
        if not isinstance(component_energy, dict):
            return
        for key, value in list(component_energy.items()):
            if isinstance(value, dict):
                MaintenanceEngine._decay_nested_component_energy(value, er_ratio=er_ratio, ev_ratio=ev_ratio)
                continue
            if str(key) == "er":
                try:
                    component_energy[key] = round(float(value or 0.0) * float(er_ratio), 8)
                except Exception:
                    pass
            elif str(key) == "ev":
                try:
                    component_energy[key] = round(float(value or 0.0) * float(ev_ratio), 8)
                except Exception:
                    pass

    @staticmethod
    def _component_energy_count(component_energy: dict, *, floor: float) -> tuple[int, int]:
        if not isinstance(component_energy, dict):
            return 0, 0
        active = 0
        dropped = 0
        for key, value in component_energy.items():
            if isinstance(value, dict):
                sub_active, sub_dropped = MaintenanceEngine._component_energy_count(value, floor=floor)
                active += sub_active
                dropped += sub_dropped
                continue
            if (
                str(key).endswith("_component_er_share")
                or str(key).endswith("_component_ev_share")
                or str(key) in {"er", "ev"}
            ):
                try:
                    if float(value or 0.0) >= floor:
                        active += 1
                    else:
                        dropped += 1
                except Exception:
                    pass
        return int(active), int(dropped)

    @staticmethod
    def _component_energy_total(component_energy: dict, key: str) -> float:
        total = 0.0
        if not isinstance(component_energy, dict):
            return total
        suffix = f"_{key}_share"
        for field, value in component_energy.items():
            if isinstance(value, dict):
                total += MaintenanceEngine._component_energy_total(value, key)
                continue
            if str(field).endswith(suffix) or str(field) == key:
                try:
                    total += float(value or 0.0)
                except Exception:
                    pass
        return round(total, 8)

    def _refresh_runtime_modulation(self, *, item: dict, tick_number: int, now_ms: int) -> None:
        energy = item.setdefault("energy", {})
        lifecycle = item.setdefault("lifecycle", {})

        history = self._trim_recent_activation_ticks(lifecycle.get("recent_activation_ticks", []), tick_number)
        lifecycle["recent_activation_ticks"] = history

        hold_remaining = max(0, int(lifecycle.get("recency_hold_ticks_remaining", 0)))
        current_gain = max(1.0, float(energy.get("recency_gain", 1.0)))
        if hold_remaining > 0:
            lifecycle["recency_hold_ticks_remaining"] = hold_remaining - 1
            new_gain = current_gain
        else:
            new_gain = max(1.0, current_gain * self._recency_decay_ratio())

        energy["recency_gain"] = round(new_gain, 8)
        energy["fatigue"] = self._fatigue_from_count(len(history))
        lifecycle["last_maintenance_tick"] = int(tick_number)
        item["updated_at"] = max(int(item.get("updated_at", 0)), now_ms)

    def _trim_recent_activation_ticks(self, history: list[int] | tuple[int, ...], current_tick: int) -> list[int]:
        window = max(1, int(self._config.get("fatigue_window_ticks", 12)))
        min_tick = int(current_tick) - window + 1
        return [
            int(tick)
            for tick in list(history or [])
            if isinstance(tick, int) or str(tick).isdigit()
            if int(tick) >= min_tick
        ]

    def _fatigue_from_count(self, count: int) -> float:
        threshold = max(1, int(self._config.get("fatigue_threshold_count", 3)))
        window = max(threshold, int(self._config.get("fatigue_window_ticks", 12)))
        max_value = max(0.0, min(1.0, float(self._config.get("fatigue_max_value", 1.0))))
        if int(count) < threshold:
            return 0.0
        numerator = int(count) - threshold + 1
        denominator = max(1, window - threshold + 1)
        return round(max_value * min(1.0, float(numerator) / float(denominator)), 8)

    def _recency_decay_ratio(self) -> float:
        ratio = float(self._config.get("recency_gain_decay_ratio", 0.9999976974))
        return max(0.0, min(1.0, ratio))

    def _get_decay_ratios(self, ref_object_type: str) -> tuple[float, float]:
        overrides = self._config.get("per_object_type_decay_override", {})
        if ref_object_type in overrides:
            custom = overrides[ref_object_type]
            return (
                float(custom.get("er", self._config.get("default_er_decay_ratio", 0.95))),
                float(custom.get("ev", self._config.get("default_ev_decay_ratio", 0.90))),
            )
        return (
            float(self._config.get("default_er_decay_ratio", 0.95)),
            float(self._config.get("default_ev_decay_ratio", 0.90)),
        )

    def update_config(self, config: dict):
        self._config = config
