# -*- coding: utf-8 -*-
"""Attention Filter module."""

from __future__ import annotations

import os
import math
import time
import traceback
from typing import Any

from . import __module_name__, __schema_version__, __version__
from ._logger import ModuleLogger

try:
    from state_pool._semantic_identity import semantic_context_key_from_item
except Exception:  # pragma: no cover - attention can still run in isolation.
    def semantic_context_key_from_item(item: dict | None) -> str:
        return ""


def _load_yaml_config(path: str) -> dict:
    """Load YAML config. Return empty dict on failure."""
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else {}
    except ImportError:
        return {}
    except Exception:
        return {}


_DEFAULT_CONFIG: dict[str, Any] = {
    # ---- CAM capacity / CAM ?? ----
    # `top_n` is the main CAM capacity cap. `max_cam_items` is kept as a
    # compatibility alias for older observatory callers.
    "top_n": 16,

    # ---- Size-aware CAM resource accounting / ?????? ----
    # ST / SG objects can be much larger than single SA items, so selection uses a
    # simple token-count-based cost to avoid one oversized structure monopolizing CAM.
    "size_cost_enabled": True,
    "size_cost_ref_object_types": ["st", "sg"],
    "size_cost_token_divisor": 12,
    "size_cost_max_cost": 8,

    # ---- Dynamic cutoff / ???? ----
    # The cutoff ratio rises when candidate scores become more concentrated, so CAM
    # keeps fewer low-value items under sharp peaks and more items under flatter peaks.
    "keep_score_ratio_base": 0.28,
    "keep_score_ratio_concentration_gain": 0.22,
    "keep_score_ratio_min": 0.18,
    "keep_score_ratio_max": 0.72,
    "score_entropy_eps": 1e-9,

    # ---- CAM extraction / CAM ?? ----
    "consume_energy": True,
    "memory_energy_ratio": 0.5,
    # ---- Attention energy resource / 注意力能量资源 ----
    # The selected CAM first receives a base transfer from StatePool
    # (`memory_energy_ratio`). Attention filtering then suppresses weakly weighted
    # items and gives a bounded net gain to strongly weighted items. The net
    # filtered CAM energy increase is capped by this per-tick resource budget.
    "attention_energy_budget_enabled": True,
    "attention_energy_budget_base": 8.0,
    "attention_energy_budget_min": 0.0,
    "attention_energy_budget_max": 32.0,
    "attention_energy_budget_apply_when_not_consuming": False,
    "attention_filter_suppression_enabled": True,
    "attention_filter_suppression_floor": 0.36,
    "attention_filter_suppression_min_ratio": 0.25,
    "attention_filter_gain_floor": 0.52,
    "attention_filter_gain_exponent": 1.15,
    "fast_source_snapshot_enabled": True,
    "exclude_ref_object_types": ["em"],
    "residual_memory_as_structure_enabled": True,
    "residual_memory_as_structure_shadow_mode": False,
    "residual_memory_runtime_object_type": "em",

    # ---- Minimum energy gate / ?????? ----
    "min_total_energy": 0.0,

    # ---- Priority weights / ????? ----
    "priority_weight_total_energy": 1.25,
    "priority_weight_cp_abs": 0.35,
    "priority_weight_salience": 0.15,
    "priority_weight_updated_at": 1e-12,
    "priority_weight_fatigue": 0.0,
    "priority_weight_recency_gain": 0.0,
    "sa_count_preference_enabled": True,
    "sa_count_preference_peak": 4.0,
    "sa_count_preference_reward": 0.42,
    "sa_count_preference_penalty": 0.14,
    "sa_count_preference_no_reward_below_or_equal": 2.0,
    "sa_count_preference_no_reward_above_or_equal": 6.0,
    "sa_count_preference_min_scale": 0.5,

    # ---- Focus directives / ???? ----
    "focus_boost_weight": 1.0,

    # ---- Reward / Action humanlike shaping V2 ----
    "reward_action_humanlike_v2_enabled": True,
    "reward_action_priority_enabled": True,
    "reward_action_structure_first_mode": True,
    "reward_action_signal_names": ["reward_signal", "punish_signal", "teacher_reward_signal", "teacher_punish_signal"],
    "reward_action_special_attribute_names": [
        "reward_signal",
        "punish_signal",
        "teacher_reward_signal",
        "teacher_punish_signal",
        "cfs_dissonance",
        "cfs_correctness",
        "cfs_correct_event",
        "cfs_expectation",
        "cfs_expectation_unverified",
        "cfs_expectation_verified",
        "cfs_pressure",
        "cfs_pressure_unverified",
        "cfs_pressure_verified",
        "cfs_surprise",
        "cfs_grasp",
        "cfs_complexity",
        "cfs_simplicity",
        "cfs_repetition",
        "cfs_relief",
        "cfs_reassurance",
    ],
    "reward_action_direct_signal_bonus": 0.72,
    "reward_action_direct_signal_energy_gain": 0.48,
    "reward_action_action_node_bonus": 0.62,
    "reward_action_action_node_energy_gain": 0.45,
    "reward_action_bound_signal_bonus": 0.36,
    "reward_action_bound_signal_value_gain": 0.22,
    "reward_action_target_association_bonus": 0.58,
    "reward_action_target_association_energy_gain": 0.34,
    "reward_action_bonus_cap": 2.4,
    "reward_action_penalty_cap": 1.8,
    "reward_action_special_standalone_penalty": 0.98,
    "reward_action_special_standalone_energy_gain": 0.30,
    "reward_action_action_node_penalty": 0.46,
    "reward_action_action_node_energy_gain": 0.1,
    "reward_action_structure_carrier_bonus": 0.56,
    "reward_action_structure_carrier_value_gain": 0.22,
    "reward_action_structure_carrier_context_gain": 0.28,
    "reward_action_min_carrier_score": 0.35,
    "attention_repeat_fatigue_special_multiplier": 2.0,
    "attention_repeat_fatigue_structure_carrier_multiplier": 0.82,
    "attention_repeat_fatigue_enabled": True,
    "attention_repeat_fatigue_semantic_context_first": True,
    "attention_repeat_fatigue_window_calls": 6,
    "attention_repeat_fatigue_recovery_per_call": 0.57,
    "attention_repeat_fatigue_penalty_gain": 0.58,
    "attention_repeat_fatigue_selected_gain": 1.18,
    "attention_repeat_fatigue_max_penalty": 1.70,
    "attention_repeat_fatigue_max_strength": 4.0,

    # ---- Logging / ?? ----
    "log_dir": "",
    "log_max_file_bytes": 5 * 1024 * 1024,
    "stdout_fallback_when_log_fail": True,
}


class AttentionFilter:
    """Attention Filter main class."""
    def __init__(self, config_path: str = "", config_override: dict | None = None):
        self._config_path = config_path or os.path.join(os.path.dirname(__file__), "config", "attention_config.yaml")
        self._config = self._build_config(config_override)
        self._logger = ModuleLogger(
            log_dir=self._config.get("log_dir", ""),
            max_file_bytes=int(self._config.get("log_max_file_bytes", 5 * 1024 * 1024)),
            enable_stdout_fallback=bool(self._config.get("stdout_fallback_when_log_fail", True)),
        )
        self._total_calls = 0
        self._repeat_attention_state: dict[str, dict[str, float]] = {}

    # ================================================================== #
    # build_cam_from_pool                                                #
    # ================================================================== #

    def build_cam_from_pool(
        self,
        pool: Any,
        *,
        trace_id: str,
        tick_id: str | None = None,
        top_n: int | None = None,
        consume_energy: bool | None = None,
        memory_energy_ratio: float | None = None,
        focus_directives: list[dict] | None = None,
        modulation: dict | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """
        Build the current attention memory (CAM) from the live StatePool snapshot.

        Args:
            pool: StatePool-like object implementing `get_state_snapshot` and
                `apply_energy_update`.
            trace_id / tick_id: runtime audit identifiers.
            top_n: CAM capacity cap for this call.
            consume_energy: whether selection should extract energy from StatePool.
            memory_energy_ratio: extraction ratio in `[0, 1]`.
            focus_directives: optional focus directives from IESM / action module.
            modulation: per-tick modulation from emotion / action layers.
            metadata: optional caller-side context.
        """
        start_time = time.time()
        tick_id = tick_id or trace_id
        self._total_calls += 1

        if not trace_id:
            return self._make_response(
                success=False,
                code="VALIDATION_ERROR",
                message="trace_id is required",
                error={"code": "trace_id_required"},
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        if pool is None or not hasattr(pool, "get_state_snapshot"):
            return self._make_response(
                success=False,
                code="VALIDATION_ERROR",
                message="pool must implement get_state_snapshot",
                error={"code": "pool_invalid"},
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        # ---- Resolve CAM capacity / ???? CAM ?? ----
        modulation = modulation or {}

        base_cap = int(self._config.get("max_cam_items", self._config.get("top_n", 16)) or 16)
        mod_cap = modulation.get("max_cam_items")
        if mod_cap is None:
            # Support both `max_cam_items` and `top_n` from modulation.
            mod_cap = modulation.get("top_n")
        resolved_top_n = int(top_n) if top_n is not None else (int(mod_cap) if mod_cap is not None else base_cap)
        resolved_top_n = max(1, int(resolved_top_n))

        base_min_keep = int(self._config.get("min_cam_items", 2) or 2)
        mod_min_keep = modulation.get("min_cam_items")
        resolved_min_keep = int(mod_min_keep) if mod_min_keep is not None else base_min_keep
        resolved_min_keep = max(1, min(resolved_top_n, int(resolved_min_keep)))
        resolved_consume = bool(consume_energy) if consume_energy is not None else bool(self._config.get("consume_energy", True))
        ratio_raw = float(memory_energy_ratio) if memory_energy_ratio is not None else float(self._config.get("memory_energy_ratio", 0.5))
        resolved_ratio = max(0.0, min(1.0, ratio_raw))

        energy_budget_enabled = bool(
            modulation.get(
                "attention_energy_budget_enabled",
                self._config.get("attention_energy_budget_enabled", True),
            )
        )
        energy_budget_apply_without_consume = bool(
            modulation.get(
                "attention_energy_budget_apply_when_not_consuming",
                self._config.get("attention_energy_budget_apply_when_not_consuming", False),
            )
        )
        energy_budget_config_base = float(
            modulation.get(
                "attention_energy_budget_base",
                self._config.get("attention_energy_budget_base", 8.0),
            )
            or 0.0
        )
        energy_budget_requested = float(
            modulation.get(
                "attention_energy_budget",
                energy_budget_config_base,
            )
            or 0.0
        )
        energy_budget_min = float(
            modulation.get(
                "attention_energy_budget_min",
                self._config.get("attention_energy_budget_min", 0.0),
            )
            or 0.0
        )
        energy_budget_max = float(
            modulation.get(
                "attention_energy_budget_max",
                self._config.get("attention_energy_budget_max", 32.0),
            )
            or 0.0
        )
        if energy_budget_max < energy_budget_min:
            energy_budget_max = energy_budget_min
        resolved_energy_budget = max(energy_budget_min, min(energy_budget_max, energy_budget_requested))

        # ---- Resolve effective weights and cutoff params ----
        effective_weights = {
            "priority_weight_total_energy": float(modulation.get("priority_weight_total_energy", self._config.get("priority_weight_total_energy", 1.25))),
            "priority_weight_cp_abs": float(modulation.get("priority_weight_cp_abs", self._config.get("priority_weight_cp_abs", 0.35))),
            "priority_weight_salience": float(modulation.get("priority_weight_salience", self._config.get("priority_weight_salience", 0.15))),
            "priority_weight_updated_at": float(modulation.get("priority_weight_updated_at", self._config.get("priority_weight_updated_at", 1e-12))),
            "priority_weight_fatigue": float(modulation.get("priority_weight_fatigue", self._config.get("priority_weight_fatigue", 0.0))),
            "priority_weight_recency_gain": float(modulation.get("priority_weight_recency_gain", self._config.get("priority_weight_recency_gain", 0.0))),
            "min_total_energy": float(modulation.get("min_total_energy", self._config.get("min_total_energy", 0.0))),
            "focus_boost_weight": float(modulation.get("focus_boost_weight", self._config.get("focus_boost_weight", 1.0))),
        }
        effective_cutoff = {
            "keep_score_ratio_base": float(modulation.get("keep_score_ratio_base", self._config.get("keep_score_ratio_base", 0.28))),
            "keep_score_ratio_concentration_gain": float(modulation.get("keep_score_ratio_concentration_gain", self._config.get("keep_score_ratio_concentration_gain", 0.22))),
            "keep_score_ratio_min": float(modulation.get("keep_score_ratio_min", self._config.get("keep_score_ratio_min", 0.18))),
            "keep_score_ratio_max": float(modulation.get("keep_score_ratio_max", self._config.get("keep_score_ratio_max", 0.72))),
            "score_entropy_eps": float(modulation.get("score_entropy_eps", self._config.get("score_entropy_eps", 1e-9))),
        }

        # ---- Acquire live StatePool candidates ----
        try:
            source_snapshot = {}
            store = getattr(pool, "_store", None)
            if bool(self._config.get("fast_source_snapshot_enabled", True)) and store is not None and hasattr(store, "get_all"):
                raw_items = list(store.get_all())

                def _raw_cp_abs(row: dict) -> float:
                    energy = row.get("energy", {}) if isinstance(row.get("energy", {}), dict) else {}
                    try:
                        return float(energy.get("cognitive_pressure_abs", row.get("cp_abs", 0.0)) or 0.0)
                    except Exception:
                        return 0.0

                raw_items.sort(key=_raw_cp_abs, reverse=True)
                source_snapshot = {
                    "summary": {
                        "active_item_count": len(raw_items),
                        "snapshot_source": "attention_fast_store",
                    },
                    "top_items": [self._build_attention_candidate_summary(item) for item in raw_items],
                }
            else:
                snapshot_result = pool.get_state_snapshot(
                    trace_id=f"{trace_id}_attention_source",
                    tick_id=tick_id,
                    top_k=None,
                )
                if not snapshot_result.get("success"):
                    raise RuntimeError(snapshot_result.get("message", "state_pool snapshot failed"))
                source_snapshot = snapshot_result.get("data", {}).get("snapshot", {}) or {}
        except Exception as e:
            self._logger.error(
                trace_id=trace_id,
                tick_id=tick_id,
                interface="build_cam_from_pool",
                code="STATE_SNAPSHOT_ERROR",
                message=f"Failed to get state snapshot: {e}",
                detail={"traceback": traceback.format_exc()},
            )
            return self._make_response(
                success=False,
                code="STATE_SNAPSHOT_ERROR",
                message=f"failed to get state snapshot: {e}",
                error={"code": "state_snapshot_error", "message": str(e)},
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        all_items = list(source_snapshot.get("top_items", []))
        excluded = set(str(x) for x in (self._config.get("exclude_ref_object_types") or []))
        residual_runtime_type = str(self._config.get("residual_memory_runtime_object_type", "em") or "em").strip().lower()
        if residual_runtime_type not in {"st", "em"}:
            residual_runtime_type = "st"
        if bool(self._config.get("residual_memory_as_structure_enabled", True)) and not bool(
            self._config.get("residual_memory_as_structure_shadow_mode", False)
        ):
            if residual_runtime_type == "em":
                excluded.discard("em")
        eligible_items = [
            item for item in all_items
            if str(item.get("ref_object_type", "")) not in excluded
        ]
        signal_names = self._special_attribute_name_set()
        reward_action_context = self._build_reward_action_context(eligible_items, signal_names=signal_names)

        # ---- Step 2: compute priority once /                                      ----
        size_cost_enabled = bool(self._config.get("size_cost_enabled", True))
        size_cost_types = set(str(x) for x in (self._config.get("size_cost_ref_object_types") or ["st", "sg"]))
        if bool(self._config.get("residual_memory_as_structure_enabled", True)) and not bool(
            self._config.get("residual_memory_as_structure_shadow_mode", False)
        ):
            if residual_runtime_type == "em":
                size_cost_types.add("em")
        size_cost_token_divisor = float(self._config.get("size_cost_token_divisor", 12) or 12)
        size_cost_token_divisor = max(1.0, float(size_cost_token_divisor))
        size_cost_max_cost = int(self._config.get("size_cost_max_cost", 8) or 8)
        size_cost_max_cost = max(1, int(size_cost_max_cost))

        def _item_cost(it: dict) -> int:
            if not size_cost_enabled:
                return 1
            rtype = str(it.get("ref_object_type", "") or "").strip()
            if size_cost_types and rtype not in size_cost_types:
                return 1
            ref_snapshot = it.get("ref_snapshot", {}) or {}
            token_count = 0
            if isinstance(ref_snapshot, dict):
                token_count = int(ref_snapshot.get("token_count", 0) or 0)
                if token_count <= 0:
                    token_count = len(ref_snapshot.get("flat_tokens", []) or [])
            token_count = max(1, int(token_count))
            cost = int(math.ceil(float(token_count) / float(size_cost_token_divisor)))
            cost = max(1, min(int(size_cost_max_cost), int(cost)))
            return int(cost)

        scored_items: list[dict] = []
        for item in eligible_items:
            try:
                focus_boost = self._compute_focus_boost(item, focus_directives)
                base_score = self._priority_score(
                    item,
                    weights=effective_weights,
                    focus_directives=focus_directives,
                    focus_boost=focus_boost,
                )
            except Exception:
                focus_boost = 0.0
                base_score = 0.0
            reward_action_bonus_detail = self._compute_reward_action_bonus(
                item,
                reward_action_context,
                signal_names=signal_names,
            )
            reward_action_bonus = float(reward_action_bonus_detail.get("bonus", 0.0) or 0.0)
            repeat_attention_detail = self._compute_repeat_attention_penalty(
                item=item,
                attention_call_index=self._total_calls,
                signal_names=signal_names,
            )
            repeat_attention_penalty = float(repeat_attention_detail.get("penalty", 0.0) or 0.0)
            sa_count_preference = self._sa_count_preference_modifier(item=item)
            score = float(base_score) + float(reward_action_bonus) - float(repeat_attention_penalty)
            copied = dict(item)
            copied["attention_priority_base"] = round(float(base_score), 8)
            copied["attention_priority"] = round(float(score), 8)
            copied["focus_boost"] = round(float(focus_boost), 8)
            copied["reward_action_bonus"] = round(float(reward_action_bonus), 8)
            copied["reward_action_bonus_detail"] = dict(reward_action_bonus_detail)
            copied["repeat_attention_penalty"] = round(float(repeat_attention_penalty), 8)
            copied["repeat_attention_penalty_detail"] = dict(repeat_attention_detail)
            copied["sa_count_preference"] = dict(sa_count_preference)
            copied["sa_count_preference_bonus"] = round(float(sa_count_preference.get("bonus", 0.0) or 0.0), 8)
            copied["sa_count_preference_scale"] = round(float(sa_count_preference.get("scale", 1.0) or 1.0), 8)
            copied["sa_count_preference_token_count"] = int(sa_count_preference.get("token_count", 1.0) or 1.0)
            copied["attention_cost"] = int(_item_cost(copied))

            # Ensure token_count is available for downstream CAM-only endogenous
            # stimulus generation even when we do not carry the full payload.
            try:
                    rs = copied.get("ref_snapshot", {}) or {}
                    if isinstance(rs, dict):
                        tc = int(rs.get("token_count", 0) or 0)
                        if tc <= 0:
                            tc = len(rs.get("flat_tokens", []) or [])
                    else:
                        tc = 0
                    copied["token_count"] = max(1, int(tc or 1))
            except Exception:
                copied["token_count"] = int(copied.get("token_count", 1) or 1)
            scored_items.append(copied)

        scored_items.sort(key=lambda it: float(it.get("attention_priority", 0.0) or 0.0), reverse=True)

        sequence_groups_cache: dict[int, tuple[dict, ...]] = {}
        goal_b_signature_cache: dict[int, tuple[str, ...]] = {}

        def _sequence_groups_of(it: dict) -> tuple[dict, ...]:
            cache_key = id(it)
            cached = sequence_groups_cache.get(cache_key)
            if cached is not None:
                return cached
            ref_snapshot = it.get("ref_snapshot", {}) or {}
            groups = ref_snapshot.get("sequence_groups", []) if isinstance(ref_snapshot, dict) else []
            cached = tuple(group for group in groups if isinstance(group, dict))
            sequence_groups_cache[cache_key] = cached
            return cached

        def _goal_b_string_signature(it: dict) -> tuple[str, ...]:
            cache_key = id(it)
            cached = goal_b_signature_cache.get(cache_key)
            if cached is not None:
                return cached
            groups = _sequence_groups_of(it)
            if len(groups) != 1:
                goal_b_signature_cache[cache_key] = ()
                return ()
            group = groups[0]
            if not bool(group.get("order_sensitive", False)):
                goal_b_signature_cache[cache_key] = ()
                return ()
            if str(group.get("string_unit_kind", "") or "") != "char_sequence":
                goal_b_signature_cache[cache_key] = ()
                return ()
            units = [unit for unit in (group.get("units", []) or []) if isinstance(unit, dict)]
            if not units:
                tokens = [str(token) for token in (group.get("tokens", []) or []) if str(token)]
            else:
                sorted_units = sorted(
                    units,
                    key=lambda unit: (int(unit.get("sequence_index", 0) or 0), str(unit.get("unit_id", "") or "")),
                )
                tokens = [str(unit.get("token", "") or unit.get("display_text", "") or "") for unit in sorted_units]
                tokens = [token for token in tokens if token]
            signature = tuple(tokens)
            goal_b_signature_cache[cache_key] = signature
            return signature

        def _has_mixed_goal_b_groups(it: dict) -> bool:
            groups = _sequence_groups_of(it)
            if len(groups) <= 1:
                return False
            has_string = False
            has_non_string = False
            for group in groups:
                is_string = bool(group.get("order_sensitive", False)) and str(group.get("string_unit_kind", "") or "") == "char_sequence"
                if is_string:
                    has_string = True
                else:
                    has_non_string = True
            return bool(has_string and has_non_string)

        def _is_goal_b_string_shell(it: dict) -> bool:
            groups = _sequence_groups_of(it)
            if not groups:
                return False
            has_any_string_payload = False
            for group in groups:
                string_text = str(group.get("string_token_text", "") or "").strip()
                tokens = [str(token) for token in (group.get("tokens", []) or []) if str(token)]
                if string_text or any(len(tok) > 1 for tok in tokens):
                    has_any_string_payload = True
                    is_legal_string = bool(group.get("order_sensitive", False)) and str(group.get("string_unit_kind", "") or "") == "char_sequence"
                    if not is_legal_string:
                        return True
            return False if has_any_string_payload else False

        for it in scored_items:
            it["goal_b_mixed_groups"] = _has_mixed_goal_b_groups(it)

        # Goal B filtering should not collapse legitimate independent objects.
        # Keep distinct SA / string / structure candidates as long as they are real
        # objects in the pool; only drop malformed mixed shells that would pollute
        # CAM and endogenous stimulus construction.
        filtered_scored_items: list[dict] = []
        for it in scored_items:
            if bool(it.get("goal_b_mixed_groups", False)):
                continue
            if _is_goal_b_string_shell(it):
                continue
            filtered_scored_items.append(it)
        scored_items = filtered_scored_items

        # ---- Step 3: selection policy ----
        consume_events: list[dict] = []
        consumed_total_er = 0.0
        consumed_total_ev = 0.0
        min_total_energy = max(0.0, float(effective_weights.get("min_total_energy", 0.0)))

        # Focus target set /          
        focus_ref_set: set[str] = set()
        focus_item_set: set[str] = set()
        for directive in focus_directives or []:
            if not isinstance(directive, dict):
                continue
            rid = str(directive.get("target_ref_object_id", "") or "").strip()
            rtype = str(directive.get("target_ref_object_type", "") or "").strip()
            iid = str(directive.get("target_item_id", "") or "").strip()
            if iid:
                focus_item_set.add(iid)
            if rid:
                # allow both "st:xxx" and raw "xxx" for compatibility
                focus_ref_set.add(rid)
                if rtype:
                    focus_ref_set.add(f"{rtype}:{rid}")

        def _is_shadowed_atomic(it: dict) -> bool:
            if not covered_atomic_tokens:
                return False
            ref_type = str(it.get("ref_object_type", "") or it.get("object_type", "") or "")
            if ref_type == "sa":
                token = str(it.get("display", "") or it.get("token", "") or it.get("display_text", "") or "")
                return bool(token and (token in covered_atomic_tokens or token in covered_atomic_displays))
            if ref_type not in {"st", "sg"}:
                return False
            groups = _sequence_groups_of(it)
            if len(groups) != 1:
                return False
            units = [unit for unit in (groups[0].get("units", []) or []) if isinstance(unit, dict)]
            if len(units) != 1:
                return False
            token = str(units[0].get("token", "") or units[0].get("display_text", "") or "")
            return bool(token and token in covered_atomic_tokens)

        def _is_focus_target(it: dict) -> bool:
            iid = str(it.get("item_id", "") or "").strip()
            rid = str(it.get("ref_object_id", "") or "").strip()
            rtype = str(it.get("ref_object_type", "") or "").strip()
            if iid and iid in focus_item_set:
                return True
            if rid and (rid in focus_ref_set or f"{rtype}:{rid}" in focus_ref_set):
                return True
            return False

        covered_atomic_tokens: set[str] = set()
        covered_atomic_displays: set[str] = set()
        for it in scored_items:
            sig = _goal_b_string_signature(it)
            if len(sig) < 2:
                continue
            for tok in sig:
                token = str(tok or "").strip()
                if token:
                    covered_atomic_tokens.add(token)
                    covered_atomic_displays.add(token)

        # ---- Dynamic cutoff ----
        score_eps = max(0.0, float(effective_cutoff.get("score_entropy_eps", 1e-9) or 1e-9))
        score_weights: list[float] = []
        for it in scored_items:
            before_er = float(it.get("er", 0.0) or 0.0)
            before_ev = float(it.get("ev", 0.0) or 0.0)
            if before_er + before_ev <= min_total_energy:
                continue
            v = float(it.get("attention_priority", 0.0) or 0.0)
            if v > score_eps:
                score_weights.append(v)

        peak_score = float(score_weights[0]) if score_weights else (float(scored_items[0].get("attention_priority", 0.0) or 0.0) if scored_items else 0.0)
        peak_score = max(0.0, float(peak_score))

        entropy = 0.0
        concentration = 0.0
        if len(score_weights) >= 2:
            total_w = float(sum(score_weights))
            if total_w > score_eps:
                probs = [w / total_w for w in score_weights if w > score_eps]
                if probs:
                    raw = -sum(p * math.log(max(p, 1e-12)) for p in probs)
                    denom = max(1e-6, math.log(float(len(probs))))
                    entropy = max(0.0, min(1.0, raw / denom))
                    concentration = max(0.0, min(1.0, 1.0 - entropy))

        ratio_base = float(effective_cutoff.get("keep_score_ratio_base", 0.28) or 0.28)
        ratio_gain = float(effective_cutoff.get("keep_score_ratio_concentration_gain", 0.22) or 0.22)
        ratio_min = float(effective_cutoff.get("keep_score_ratio_min", 0.18) or 0.18)
        ratio_max = float(effective_cutoff.get("keep_score_ratio_max", 0.72) or 0.72)
        keep_ratio = ratio_base + concentration * ratio_gain
        keep_ratio = max(ratio_min, min(ratio_max, float(keep_ratio)))
        cutoff_score = float(peak_score) * float(keep_ratio)

        selected_candidates: list[dict] = []
        selected_item_ids: set[str] = set()
        selected_budget_used = 0
        skipped_by_budget_count = 0

        def _select(it: dict, why: str) -> bool:
            nonlocal selected_budget_used, skipped_by_budget_count
            iid = str(it.get("item_id", "") or "").strip()
            if not iid:
                return False
            if iid in selected_item_ids:
                return False
            cost = max(1, int(it.get("attention_cost", 1) or 1))
            if selected_budget_used + cost > resolved_top_n:
                skipped_by_budget_count += 1
                return False
            selected_item_ids.add(iid)
            selected_candidates.append({**it, "selected_by": why, "attention_cost": cost})
            selected_budget_used += cost
            return True

        # 1) Focus-first /       
        for it in scored_items:
            if selected_budget_used >= resolved_top_n:
                break
            if not _is_focus_target(it):
                continue
            total_energy = float(it.get("er", 0.0) or 0.0) + float(it.get("ev", 0.0) or 0.0)
            if total_energy <= min_total_energy:
                continue
            if _is_shadowed_atomic(it):
                continue
            _select(it, "focus_directive")
        # 2) Cutoff selection
        for it in scored_items:
            if selected_budget_used >= resolved_top_n:
                break
            iid = str(it.get("item_id", "") or "").strip()
            if iid and iid in selected_item_ids:
                continue
            total_energy = float(it.get("er", 0.0) or 0.0) + float(it.get("ev", 0.0) or 0.0)
            if total_energy <= min_total_energy:
                continue
            if _is_shadowed_atomic(it):
                continue
            score = float(it.get("attention_priority", 0.0) or 0.0)
            if score < cutoff_score:
                continue
            _select(it, "cutoff")
        # 3) Min-keep fill /            
        for it in scored_items:
            if selected_budget_used >= resolved_top_n:
                break
            if len(selected_candidates) >= resolved_min_keep:
                break
            iid = str(it.get("item_id", "") or "").strip()
            if iid and iid in selected_item_ids:
                continue
            if _is_shadowed_atomic(it):
                continue
            total_energy = float(it.get("er", 0.0) or 0.0) + float(it.get("ev", 0.0) or 0.0)
            if total_energy <= min_total_energy:
                continue
            _select(it, "min_keep")
        # 4) Extraction
        base_cam_total_er = 0.0
        base_cam_total_ev = 0.0
        base_cam_total_energy = 0.0
        score_floor = float(self._config.get("attention_filter_gain_floor", 0.52) or 0.52)
        score_floor = max(0.0, min(1.0, score_floor))
        suppress_floor = float(self._config.get("attention_filter_suppression_floor", 0.36) or 0.36)
        suppress_floor = max(0.0, min(1.0, suppress_floor))
        suppress_min_ratio = float(self._config.get("attention_filter_suppression_min_ratio", 0.25) or 0.25)
        suppress_min_ratio = max(0.0, min(1.0, suppress_min_ratio))
        gain_exponent = max(0.1, float(self._config.get("attention_filter_gain_exponent", 1.15) or 1.15))
        suppression_enabled = bool(self._config.get("attention_filter_suppression_enabled", True))
        use_budget_filter = bool(energy_budget_enabled and (resolved_consume or energy_budget_apply_without_consume))

        base_records: list[dict[str, Any]] = []
        for item in selected_candidates:
            before_er = round(float(item.get("er", 0.0)), 8)
            before_ev = round(float(item.get("ev", 0.0)), 8)
            total_energy = before_er + before_ev
            if total_energy <= min_total_energy:
                continue
            base_er = round(before_er * resolved_ratio, 8) if resolved_consume else before_er
            base_ev = round(before_ev * resolved_ratio, 8) if resolved_consume else before_ev
            base_total = round(base_er + base_ev, 8)
            if base_total <= 0.0:
                continue
            base_cam_total_er += base_er
            base_cam_total_ev += base_ev
            base_cam_total_energy += base_total
            base_records.append(
                {
                    "item": item,
                    "before_er": before_er,
                    "before_ev": before_ev,
                    "base_memory_er": base_er,
                    "base_memory_ev": base_ev,
                    "base_memory_total": base_total,
                }
            )

        filter_weights: list[float] = []
        for rec in base_records:
            item = rec["item"]
            priority = max(0.0, float(item.get("attention_priority", 0.0) or 0.0))
            normalized = 0.0 if peak_score <= 1e-12 else max(0.0, min(1.0, priority / max(peak_score, 1e-12)))
            if not use_budget_filter:
                suppress_ratio = 1.0
                gain_weight = 0.0
            else:
                if suppression_enabled and normalized < suppress_floor:
                    denom = max(1e-12, suppress_floor)
                    suppress_ratio = suppress_min_ratio + (1.0 - suppress_min_ratio) * max(0.0, normalized / denom)
                else:
                    suppress_ratio = 1.0
                if normalized <= score_floor:
                    gain_weight = 0.0
                else:
                    gain_weight = ((normalized - score_floor) / max(1e-12, 1.0 - score_floor)) ** gain_exponent
            rec["attention_weight_normalized"] = round(float(normalized), 8)
            rec["attention_suppression_ratio"] = round(float(suppress_ratio), 8)
            rec["attention_gain_weight"] = round(float(gain_weight), 8)
            filter_weights.append(float(gain_weight))

        suppressed_total = 0.0
        for rec in base_records:
            base_total = float(rec.get("base_memory_total", 0.0) or 0.0)
            suppress_ratio = float(rec.get("attention_suppression_ratio", 1.0) or 1.0)
            suppressed_total += max(0.0, base_total * (1.0 - suppress_ratio))

        total_gain_weight = sum(w for w in filter_weights if w > 0.0)
        requested_gain_budget = resolved_energy_budget if use_budget_filter else 0.0
        applied_net_gain_budget = requested_gain_budget if total_gain_weight > 0.0 else 0.0
        gross_gain_budget = (applied_net_gain_budget + suppressed_total) if total_gain_weight > 0.0 else 0.0
        filtered_total_energy = 0.0
        filtered_total_er = 0.0
        filtered_total_ev = 0.0
        for rec in base_records:
            base_er = float(rec.get("base_memory_er", 0.0) or 0.0)
            base_ev = float(rec.get("base_memory_ev", 0.0) or 0.0)
            base_total = float(rec.get("base_memory_total", 0.0) or 0.0)
            suppress_ratio = float(rec.get("attention_suppression_ratio", 1.0) or 1.0)
            gain_weight = float(rec.get("attention_gain_weight", 0.0) or 0.0)
            gain_share = (gain_weight / total_gain_weight) if total_gain_weight > 1e-12 else 0.0
            gain_energy = gross_gain_budget * gain_share
            er_ratio = base_er / base_total if base_total > 1e-12 else 0.0
            ev_ratio = base_ev / base_total if base_total > 1e-12 else 0.0
            memory_er = round(base_er * suppress_ratio + gain_energy * er_ratio, 8)
            memory_ev = round(base_ev * suppress_ratio + gain_energy * ev_ratio, 8)
            memory_total = round(memory_er + memory_ev, 8)
            rec["attention_gain_share"] = round(float(gain_share), 8)
            rec["attention_gain_energy"] = round(float(gain_energy), 8)
            rec["memory_er"] = memory_er
            rec["memory_ev"] = memory_ev
            rec["memory_total"] = memory_total
            filtered_total_er += memory_er
            filtered_total_ev += memory_ev
            filtered_total_energy += memory_total

        attention_net_delta_energy = round(float(filtered_total_energy - base_cam_total_energy), 8)
        attention_resource_audit = {
            "enabled": bool(energy_budget_enabled),
            "filter_applied": bool(use_budget_filter),
            "base": round(float(energy_budget_config_base), 8),
            "requested": round(float(energy_budget_requested), 8),
            "min": round(float(energy_budget_min), 8),
            "max": round(float(energy_budget_max), 8),
            "budget": round(float(resolved_energy_budget), 8),
            "base_cam_total_er": round(float(base_cam_total_er), 8),
            "base_cam_total_ev": round(float(base_cam_total_ev), 8),
            "base_cam_total_energy": round(float(base_cam_total_energy), 8),
            "suppressed_total_energy": round(float(suppressed_total), 8),
            "gain_budget_requested": round(float(requested_gain_budget), 8),
            "gain_budget_applied": round(float(applied_net_gain_budget), 8),
            "gain_budget_net_target": round(float(requested_gain_budget), 8),
            "gross_gain_energy_applied": round(float(gross_gain_budget), 8),
            "filtered_total_er": round(float(filtered_total_er), 8),
            "filtered_total_ev": round(float(filtered_total_ev), 8),
            "filtered_total_energy": round(float(filtered_total_energy), 8),
            "net_delta_energy": attention_net_delta_energy,
            "gain_weight_total": round(float(total_gain_weight), 8),
            "suppression_floor": round(float(suppress_floor), 8),
            "suppression_min_ratio": round(float(suppress_min_ratio), 8),
            "gain_floor": round(float(score_floor), 8),
            "gain_exponent": round(float(gain_exponent), 8),
        }

        selected_items: list[dict] = []
        for rec in base_records:
            item = rec["item"]
            before_er = float(rec.get("before_er", 0.0) or 0.0)
            before_ev = float(rec.get("before_ev", 0.0) or 0.0)
            base_memory_er = float(rec.get("base_memory_er", 0.0) or 0.0)
            base_memory_ev = float(rec.get("base_memory_ev", 0.0) or 0.0)
            memory_er = float(rec.get("memory_er", 0.0) or 0.0)
            memory_ev = float(rec.get("memory_ev", 0.0) or 0.0)
            pool_after_er = before_er
            pool_after_ev = before_ev

            if resolved_consume and (base_memory_er > 0.0 or base_memory_ev > 0.0) and hasattr(pool, "apply_energy_update"):
                try:
                    update_result = pool.apply_energy_update(
                        target_item_id=item.get("item_id", ""),
                        delta_er=-base_memory_er,
                        delta_ev=-base_memory_ev,
                        trace_id=f"{trace_id}_attention_extract",
                        tick_id=tick_id,
                        reason="attention_memory_extract",
                        source_module="attention",
                    )
                    update_data = update_result.get("data", {}) if update_result.get("success") else {}
                    pool_after_er = round(float(update_data.get("after", {}).get("er", max(0.0, before_er - base_memory_er))), 8)
                    pool_after_ev = round(float(update_data.get("after", {}).get("ev", max(0.0, before_ev - base_memory_ev))), 8)
                except Exception:
                    self._logger.error(
                        trace_id=trace_id,
                        tick_id=tick_id,
                        interface="apply_energy_update",
                        code="ENERGY_UPDATE_ERROR",
                        message="Energy update failed",
                        detail={"item_id": item.get("item_id", ""), "traceback": traceback.format_exc()},
                    )
                    pool_after_er = before_er
                    pool_after_ev = before_ev

            selected_items.append(
                {
                    **item,
                    "memory_er": memory_er,
                    "memory_ev": memory_ev,
                    "memory_total": round(memory_er + memory_ev, 8),
                    "base_memory_er": round(base_memory_er, 8),
                    "base_memory_ev": round(base_memory_ev, 8),
                    "base_memory_total": round(base_memory_er + base_memory_ev, 8),
                    "attention_weight_normalized": float(rec.get("attention_weight_normalized", 0.0) or 0.0),
                    "attention_suppression_ratio": float(rec.get("attention_suppression_ratio", 1.0) or 1.0),
                    "attention_gain_weight": float(rec.get("attention_gain_weight", 0.0) or 0.0),
                    "attention_gain_share": float(rec.get("attention_gain_share", 0.0) or 0.0),
                    "attention_gain_energy": float(rec.get("attention_gain_energy", 0.0) or 0.0),
                    "pool_before_er": before_er,
                    "pool_before_ev": before_ev,
                    "pool_before_total": round(before_er + before_ev, 8),
                    "pool_after_er": pool_after_er,
                    "pool_after_ev": pool_after_ev,
                    "pool_after_total": round(pool_after_er + pool_after_ev, 8),
                    "attention_extract_ratio": resolved_ratio if resolved_consume else 0.0,
                    "attention_cost_applied": resolved_consume,
                }
            )
            consume_events.append(
                {
                    "item_id": item.get("item_id", ""),
                    "ref_object_id": item.get("ref_object_id", ""),
                    "ref_object_type": item.get("ref_object_type", ""),
                    "display": item.get("display", ""),
                    "attention_cost": int(item.get("attention_cost", 1) or 1),
                    "memory_er": memory_er,
                    "memory_ev": memory_ev,
                    "memory_total": round(memory_er + memory_ev, 8),
                    "base_memory_er": round(base_memory_er, 8),
                    "base_memory_ev": round(base_memory_ev, 8),
                    "base_memory_total": round(base_memory_er + base_memory_ev, 8),
                    "attention_gain_energy": float(rec.get("attention_gain_energy", 0.0) or 0.0),
                    "attention_suppression_ratio": float(rec.get("attention_suppression_ratio", 1.0) or 1.0),
                    "pool_before_er": before_er,
                    "pool_before_ev": before_ev,
                    "pool_after_er": pool_after_er,
                    "pool_after_ev": pool_after_ev,
                    "attention_priority": round(float(item.get("attention_priority", 0.0) or 0.0), 8),
                    "focus_boost": round(float(item.get("focus_boost", 0.0) or 0.0), 8),
                    "selected_by": item.get("selected_by", ""),
                }
            )

            consumed_total_er += base_memory_er
            consumed_total_ev += base_memory_ev

        self._update_repeat_attention_state(selected_items=selected_items, attention_call_index=self._total_calls)

        cam_snapshot = self._make_cam_snapshot(selected_items=selected_items, trace_id=trace_id, tick_id=tick_id)
        structure_items = [item for item in selected_items if item.get("ref_object_type") == "st"]

        # CAM snapshot integrity patch (for CS-first endogenous stimulus path)
        # ------------------------------------------------------------
        # In CS-first mode, HDB structure-level may run with max_rounds=0 and build endogenous stimulus
        # fragments directly from CAM items. That path must NEVER treat an item's display text as a
        # canonical token stream (it may contain "{...}" / "->" / debug text).
        #
        # The safest fix is: for CAM-selected items, ensure `ref_snapshot.flat_tokens/sequence_groups`
        # are present by re-fetching the canonical snapshot from the pool store.
        #
        # Note:
        # - This is bounded by CAM size (<= top_n), so the overhead is small.
        # - We only overwrite missing fields to avoid stomping upstream data.
        try:
            pool_store = getattr(pool, "_store", None)
            if pool_store is not None:
                for cam_item in selected_items:
                    try:
                        spi_id = str(cam_item.get("item_id", "") or "")
                        if not spi_id:
                            continue
                        full_item = pool_store.get(spi_id)
                        if not isinstance(full_item, dict):
                            continue
                        full_snap = full_item.get("ref_snapshot", {}) if isinstance(full_item.get("ref_snapshot", {}), dict) else {}
                        if not full_snap:
                            continue
                        cam_item.setdefault("ref_snapshot", {})
                        if not isinstance(cam_item.get("ref_snapshot", {}), dict):
                            cam_item["ref_snapshot"] = {}
                        # Fill only missing fields (canonical tokens + counts).
                        for key in ("token_count", "flat_tokens", "sequence_groups", "content_signature", "member_refs"):
                            if key not in cam_item["ref_snapshot"] or not cam_item["ref_snapshot"].get(key):
                                if key in full_snap and full_snap.get(key) is not None:
                                    cam_item["ref_snapshot"][key] = full_snap.get(key)
                        for key in ("display_text", "grouped_display_text", "semantic_display_text", "semantic_grouped_display_text", "visible_text"):
                            if (not cam_item.get(key)) and full_item.get(key):
                                cam_item[key] = full_item.get(key)
                        if (not cam_item.get("display_text")) and full_snap.get("display_text"):
                            cam_item["display_text"] = full_snap.get("display_text")
                        if (not cam_item.get("grouped_display_text")) and full_snap.get("grouped_display_text"):
                            cam_item["grouped_display_text"] = full_snap.get("grouped_display_text")
                        if (not cam_item.get("semantic_display_text")) and full_snap.get("semantic_display_text"):
                            cam_item["semantic_display_text"] = full_snap.get("semantic_display_text")
                        if (not cam_item.get("visible_text")) and full_snap.get("visible_text"):
                            cam_item["visible_text"] = full_snap.get("visible_text")
                        fallback_display = (
                            cam_item.get("display")
                            or full_item.get("display")
                            or full_snap.get("content_display")
                            or full_snap.get("display")
                            or full_snap.get("display_text")
                            or ""
                        )
                        fallback_detail = (
                            full_item.get("display_detail")
                            or full_snap.get("content_display_detail")
                            or full_snap.get("grouped_display_text")
                            or ""
                        )
                        if fallback_display:
                            cam_item.setdefault("display", fallback_display)
                            if not cam_item.get("display_text"):
                                cam_item["display_text"] = fallback_display
                            if not cam_item.get("semantic_display_text"):
                                cam_item["semantic_display_text"] = fallback_display
                            if not cam_item.get("visible_text"):
                                cam_item["visible_text"] = fallback_display
                        if fallback_detail:
                            cam_item.setdefault("display_detail", fallback_detail)
                            if not cam_item.get("grouped_display_text"):
                                cam_item["grouped_display_text"] = fallback_detail
                    except Exception:
                        continue
        except Exception:
            pass

        selected_by_counts: dict[str, int] = {}
        for it in selected_items:
            k = str(it.get("selected_by", "") or "unknown")
            selected_by_counts[k] = int(selected_by_counts.get(k, 0) or 0) + 1
        reward_action_selected_count = sum(1 for it in selected_items if float(it.get("reward_action_bonus", 0.0) or 0.0) > 0.0)
        reward_action_selected_bonus_total = round(sum(float(it.get("reward_action_bonus", 0.0) or 0.0) for it in selected_items), 8)
        reward_action_structure_carrier_selected_count = sum(
            1 for it in selected_items if bool((it.get("reward_action_bonus_detail", {}) or {}).get("is_structure_carrier", False))
        )
        reward_action_standalone_special_selected_count = sum(
            1
            for it in selected_items
            if bool((it.get("reward_action_bonus_detail", {}) or {}).get("is_special_standalone", False))
        )
        repeat_attention_penalty_selected_count = sum(
            1 for it in selected_items if float(it.get("repeat_attention_penalty", 0.0) or 0.0) > 0.0
        )
        repeat_attention_penalty_total = round(
            sum(float(it.get("repeat_attention_penalty", 0.0) or 0.0) for it in selected_items),
            8,
        )
        sa_count_preference_bonus_total = round(
            sum(float(it.get("sa_count_preference_bonus", 0.0) or 0.0) for it in selected_items),
            8,
        )
        sa_count_preference_scale_mean = round(
            (
                sum(float(it.get("sa_count_preference_scale", 1.0) or 1.0) for it in selected_items)
                / max(1, len(selected_items))
            ),
            8,
        )
        sa_count_preference_token_count_mean = round(
            (
                sum(float(it.get("sa_count_preference_token_count", 1.0) or 1.0) for it in selected_items)
                / max(1, len(selected_items))
            ),
            8,
        )

        energy_eligible_count = 0
        for it in scored_items:
            total_energy = float(it.get("er", 0.0) or 0.0) + float(it.get("ev", 0.0) or 0.0)
            if total_energy > min_total_energy:
                energy_eligible_count += 1

        report = {
            "selection_basis": "Focus-first + dynamic cutoff + minimum keep; selected items then consume energy into CAM.",
            # top_n is the CAM capacity cap, not a guarantee to fill all slots
            "top_n": resolved_top_n,
            "min_cam_items": resolved_min_keep,
            "cam_resource_budget": {
                "enabled": bool(size_cost_enabled),
                "used": int(selected_budget_used),
                "cap": int(resolved_top_n),
                "skipped_by_budget_count": int(skipped_by_budget_count),
                "token_divisor": round(float(size_cost_token_divisor), 8),
                "max_cost": int(size_cost_max_cost),
                "cost_types": sorted(list(size_cost_types)),
            },
            "consume_enabled": resolved_consume,
            "consume_ratio": round(resolved_ratio, 8),
            "attention_energy_resource": attention_resource_audit,
            "modulation_applied": dict(modulation) if isinstance(modulation, dict) else {},
            "effective_priority_weights": dict(effective_weights),
            "effective_cutoff_params": dict(effective_cutoff),
            "dynamic_cutoff": {
                "peak_score": round(float(peak_score), 8),
                "keep_ratio": round(float(keep_ratio), 8),
                "cutoff_score": round(float(cutoff_score), 8),
                "score_entropy": round(float(entropy), 8),
                "score_concentration": round(float(concentration), 8),
            },
            "focus_directive_count": len(focus_directives or []),
            "focus_directives": [dict(item) for item in (focus_directives or [])[:16] if isinstance(item, dict)],
            "reward_action_context": dict(reward_action_context.get("summary", {}) or {}),
            "sa_count_preference": {
                "enabled": bool(self._config.get("sa_count_preference_enabled", True)),
                "peak": round(float(self._config.get("sa_count_preference_peak", 4.0) or 4.0), 8),
                "no_reward_below_or_equal": round(
                    float(self._config.get("sa_count_preference_no_reward_below_or_equal", 2.0) or 2.0),
                    8,
                ),
                "no_reward_above_or_equal": round(
                    float(self._config.get("sa_count_preference_no_reward_above_or_equal", 6.0) or 6.0),
                    8,
                ),
                "bonus_cap": round(float(self._config.get("sa_count_preference_reward", 0.42) or 0.42), 8),
                "penalty_cap": round(float(self._config.get("sa_count_preference_penalty", 0.14) or 0.14), 8),
                "min_scale": round(float(self._config.get("sa_count_preference_min_scale", 0.5) or 0.5), 8),
                "selected_bonus_total": sa_count_preference_bonus_total,
                "selected_scale_mean": sa_count_preference_scale_mean,
                "selected_token_count_mean": sa_count_preference_token_count_mean,
            },
            "reward_action_selected_count": int(reward_action_selected_count),
            "reward_action_selected_bonus_total": round(float(reward_action_selected_bonus_total), 8),
            "reward_action_structure_carrier_selected_count": int(reward_action_structure_carrier_selected_count),
            "reward_action_standalone_special_selected_count": int(reward_action_standalone_special_selected_count),
            "repeat_attention_penalty_selected_count": int(repeat_attention_penalty_selected_count),
            "repeat_attention_penalty_total": round(float(repeat_attention_penalty_total), 8),
            "selected_by_counts": selected_by_counts,
            "top_item_count": len(selected_items),
            "memory_item_count": len(selected_items),
            "top_items": selected_items,
            "structure_items": structure_items,
            "consume_events": consume_events,
            "consumed_total_er": round(consumed_total_er, 8),
            "consumed_total_ev": round(consumed_total_ev, 8),
            "consumed_total_energy": round(consumed_total_er + consumed_total_ev, 8),
            "base_memory_total_er": round(float(base_cam_total_er), 8),
            "base_memory_total_ev": round(float(base_cam_total_ev), 8),
            "base_memory_total_energy": round(float(base_cam_total_energy), 8),
            "attention_gain_budget_applied": round(float(applied_net_gain_budget), 8),
            "attention_gross_gain_energy_applied": round(float(gross_gain_budget), 8),
            "attention_suppressed_total_energy": round(float(suppressed_total), 8),
            "attention_net_delta_energy": attention_net_delta_energy,
            "memory_total_er": round(sum(float(item.get("memory_er", 0.0)) for item in selected_items), 8),
            "memory_total_ev": round(sum(float(item.get("memory_ev", 0.0)) for item in selected_items), 8),
            "memory_total_cp": round(sum(abs(float(item.get("memory_er", 0.0)) - float(item.get("memory_ev", 0.0))) for item in selected_items), 8),
            "state_pool_candidate_count": len(eligible_items),
            "state_pool_energy_eligible_count": int(energy_eligible_count),
            "skipped_memory_item_count": max(0, len(all_items) - len(eligible_items)),
            "source_pool_summary": source_snapshot.get("summary", {}),
            "cam_snapshot_summary": cam_snapshot.get("summary", {}),
        }

        self._logger.brief(
            trace_id=trace_id,
            tick_id=tick_id,
            interface="build_cam_from_pool",
            success=True,
            input_summary={
                "cam_item_cap": resolved_top_n,
                "min_cam_items": resolved_min_keep,
                "cutoff_score": round(float(cutoff_score), 8),
                "consume_enabled": resolved_consume,
                "consume_ratio": round(resolved_ratio, 8),
                "attention_energy_budget": round(float(resolved_energy_budget), 8),
                "source_candidate_count": len(eligible_items),
                "focus_directive_count": len(focus_directives or []),
            },
            output_summary={
                "cam_item_count": len(selected_items),
                "cam_structure_count": len(structure_items),
                "consumed_total_energy": round(consumed_total_er + consumed_total_ev, 8),
                "attention_net_delta_energy": attention_net_delta_energy,
            },
            message="CAM built",
        )

        return self._make_response(
            success=True,
            code="OK",
            message="CAM        / CAM built",
            data={
                "cam_snapshot": cam_snapshot,
                "attention_report": report,
                "meta": {
                    "version": __version__,
                    "schema_version": __schema_version__,
                    "config": dict(self._config),
                    "metadata": metadata or {},
                },
            },
            trace_id=trace_id,
            elapsed_ms=self._elapsed_ms(start_time),
        )

    # ================================================================== #
    #       get_runtime_snapshot                                         #
    # ================================================================== #

    def get_runtime_snapshot(self, *, trace_id: str = "attention_snapshot") -> dict:
        start_time = time.time()
        return self._make_response(
            success=True,
            code="OK",
            message="attention runtime snapshot",
            data={
                "module": __module_name__,
                "version": __version__,
                "schema_version": __schema_version__,
                "config_summary": dict(self._config),
                "stats": {
                    "total_calls": int(self._total_calls),
                    "repeat_attention_state_count": int(len(self._repeat_attention_state)),
                },
            },
            trace_id=trace_id,
            elapsed_ms=self._elapsed_ms(start_time),
        )

    # ================================================================== #
    #       reload_config                                                #
    # ================================================================== #

    def reload_config(
        self,
        *,
        trace_id: str,
        config_path: str | None = None,
        apply_partial: bool = True,
    ) -> dict:
        start_time = time.time()
        path = config_path or self._config_path

        try:
            new_raw = _load_yaml_config(path)
            if not new_raw:
                return self._make_response(
                    success=False,
                    code="CONFIG_ERROR",
                    message=f"Config file failed to load or empty: {path}",
                    trace_id=trace_id,
                    elapsed_ms=self._elapsed_ms(start_time),
                )

            applied: list[str] = []
            rejected: list[dict] = []
            for key, val in new_raw.items():
                if key not in _DEFAULT_CONFIG:
                    rejected.append({"key": key, "reason": "       ?/ Unknown config key"})
                    continue
                expected_type = type(_DEFAULT_CONFIG[key])
                if isinstance(val, expected_type) or (expected_type is float and isinstance(val, (int, float))):
                    self._config[key] = val
                    applied.append(key)
                else:
                    rejected.append({
                        "key": key,
                        "reason": f"       ?/ Type mismatch: expected {expected_type.__name__}, got {type(val).__name__}",
                    })

            self._logger.update_config(
                log_dir=str(self._config.get("log_dir", "")),
                max_file_bytes=int(self._config.get("log_max_file_bytes", 0) or 0),
            )

            self._logger.brief(
                trace_id=trace_id,
                interface="reload_config",
                success=True,
                input_summary={"path": path},
                output_summary={"applied_count": len(applied), "rejected_count": len(rejected)},
                message="hot reload done",
            )

            if rejected and not apply_partial:
                return self._make_response(
                    success=False,
                    code="CONFIG_ERROR",
                    message=f"             / Some config items rejected: {len(rejected)}",
                    data={"applied": applied, "rejected": rejected},
                    trace_id=trace_id,
                    elapsed_ms=self._elapsed_ms(start_time),
                )

            return self._make_response(
                success=True,
                code="OK",
                message=f"Hot reload done: {len(applied)} applied, {len(rejected)} rejected",
                data={"applied": applied, "rejected": rejected},
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )
        except Exception as e:
            self._logger.error(
                trace_id=trace_id,
                interface="reload_config",
                code="CONFIG_ERROR",
                message=f"reload config error: {e}",
                detail={"traceback": traceback.format_exc()},
            )
            return self._make_response(
                success=False,
                code="CONFIG_ERROR",
                message=f"Hot reload failed: {e}",
                error={"code": "config_error", "message": str(e)},
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

    def close(self) -> None:
        try:
            self._logger.close()
        except Exception:
            pass

    def clear_runtime_state(self, *, trace_id: str = "", reason: str = "runtime_reset") -> dict:
        start_time = time.time()
        total_calls_before = int(self._total_calls)
        repeat_attention_state_count_before = int(len(self._repeat_attention_state))
        self._total_calls = 0
        self._repeat_attention_state = {}
        return self._make_response(
            success=True,
            code="OK",
            message=f"注意力模块运行态已清空 / Attention runtime cleared ({reason})",
            data={
                "total_calls_before": total_calls_before,
                "repeat_attention_state_count_before": repeat_attention_state_count_before,
            },
            trace_id=trace_id,
            elapsed_ms=self._elapsed_ms(start_time),
        )

    # ================================================================== #
    #                                                                   #
    # ================================================================== #

    def _build_config(self, config_override: dict | None) -> dict:
        config = dict(_DEFAULT_CONFIG)
        config.update(_load_yaml_config(self._config_path))
        if config_override:
            config.update(config_override)
        return config

    @staticmethod
    def _build_attention_candidate_summary(item: dict) -> dict:
        """Build the minimal StatePool item view needed by CAM scoring."""
        if not isinstance(item, dict):
            return {}
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        energy = item.get("energy", {}) if isinstance(item.get("energy", {}), dict) else {}
        dynamics = item.get("dynamics", {}) if isinstance(item.get("dynamics", {}), dict) else {}
        binding_state = item.get("binding_state", {}) if isinstance(item.get("binding_state", {}), dict) else {}
        packet_by_name = binding_state.get("packet_attribute_by_name", {})
        runtime_by_name = binding_state.get("bound_attribute_by_name", {})
        packet_attribute_names = (
            sorted(str(key) for key in packet_by_name.keys() if str(key))
            if isinstance(packet_by_name, dict)
            else []
        )
        runtime_attribute_names = (
            sorted(str(key) for key in runtime_by_name.keys() if str(key))
            if isinstance(runtime_by_name, dict)
            else []
        )
        self_attribute_name = str(ref_snapshot.get("attribute_name", "") or "").strip()
        seen_names: set[str] = set()
        all_attribute_names: list[str] = []
        for name in [*packet_attribute_names, *runtime_attribute_names, *([self_attribute_name] if self_attribute_name else [])]:
            text = str(name or "").strip()
            if not text or text in seen_names:
                continue
            seen_names.add(text)
            all_attribute_names.append(text)

        runtime_bound_attribute_units: list[dict[str, Any]] = []
        for attr in item.get("ext", {}).get("bound_attributes", []) or []:
            if not isinstance(attr, dict):
                continue
            content = attr.get("content", {}) if isinstance(attr.get("content", {}), dict) else {}
            attr_name = str(content.get("attribute_name", "") or "").strip()
            attr_raw = str(content.get("raw", "") or "").strip()
            if not attr_name and ":" in attr_raw:
                attr_name = attr_raw.split(":", 1)[0].strip()
            attr_value = content.get("attribute_value", None)
            if attr_name or attr_value not in ("", None):
                runtime_bound_attribute_units.append(
                    {
                        "attribute_name": attr_name,
                        "attribute_value": attr_value,
                        "value_type": str(content.get("value_type", "") or "").strip(),
                        "raw": attr_raw,
                        "display": str(content.get("display", "") or attr_raw or attr.get("id", "")).strip(),
                    }
                )

        token_count = int(ref_snapshot.get("token_count", 0) or 0)
        if token_count <= 0:
            token_count = len(ref_snapshot.get("flat_tokens", []) or [])
        if token_count <= 0:
            token_count = int(ref_snapshot.get("member_count", 0) or 0)
        ref_light = {
            "content_display": ref_snapshot.get("content_display", ""),
            "content_display_detail": ref_snapshot.get("content_display_detail", ""),
            "content_signature": ref_snapshot.get("content_signature", ""),
            "token_count": int(token_count or 0),
            "member_count": ref_snapshot.get("member_count", 0),
            "flat_tokens": ref_snapshot.get("flat_tokens", []),
            "sequence_groups": ref_snapshot.get("sequence_groups", []),
            "member_refs": ref_snapshot.get("member_refs", []),
            "attribute_displays": ref_snapshot.get("attribute_displays", []),
            "feature_displays": ref_snapshot.get("feature_displays", []),
            "bound_attribute_displays": ref_snapshot.get("bound_attribute_displays", []),
            "runtime_bound_attribute_units": runtime_bound_attribute_units,
        }
        if isinstance(ref_snapshot.get("structure_ext", {}), dict) and ref_snapshot.get("structure_ext"):
            ref_light["structure_ext"] = dict(ref_snapshot.get("structure_ext", {}) or {})
        if isinstance(ref_snapshot.get("group_ext", {}), dict) and ref_snapshot.get("group_ext"):
            ref_light["group_ext"] = dict(ref_snapshot.get("group_ext", {}) or {})
        for key in (
            "role",
            "attribute_name",
            "attribute_value",
            "value_type",
            "context_ref_object_id",
            "context_ref_object_type",
            "context_owner_id",
            "context_text",
            "target_ref_object_id",
            "target_ref_object_type",
            "target_item_id",
            "target_display",
            "action_id",
            "action_kind",
        ):
            value = ref_snapshot.get(key, None)
            if value not in ("", None, [], {}):
                ref_light[key] = value

        display = str(
            ref_snapshot.get("content_display", "")
            or item.get("display_text", "")
            or item.get("display", "")
            or item.get("ref_object_id", "")
            or ""
        )
        er = float(energy.get("er", item.get("er", 0.0)) or 0.0)
        ev = float(energy.get("ev", item.get("ev", 0.0)) or 0.0)
        return {
            "item_id": item.get("id", item.get("item_id", "")),
            "ref_object_id": item.get("ref_object_id", ""),
            "ref_object_type": item.get("ref_object_type", ""),
            "ref_alias_ids": list(item.get("ref_alias_ids", []) or []),
            "display": display,
            "display_text": display,
            "display_detail": ref_snapshot.get("content_display_detail", display),
            "anchor_display": ref_snapshot.get("anchor_display", ""),
            "role": ref_snapshot.get("role", ""),
            "attribute_name": ref_snapshot.get("attribute_name", ""),
            "attribute_value": ref_snapshot.get("attribute_value", None),
            "value_type": ref_snapshot.get("value_type", ""),
            "ref_snapshot": ref_light,
            "semantic_signature": str(item.get("semantic_signature", "") or ""),
            "context_ref_object_id": ref_snapshot.get("context_ref_object_id", ""),
            "context_ref_object_type": ref_snapshot.get("context_ref_object_type", ""),
            "context_owner_id": ref_snapshot.get("context_owner_id", ""),
            "context_text": ref_snapshot.get("context_text", ""),
            "target_ref_object_id": ref_snapshot.get("target_ref_object_id", ""),
            "target_ref_object_type": ref_snapshot.get("target_ref_object_type", ""),
            "target_item_id": ref_snapshot.get("target_item_id", ""),
            "target_display": ref_snapshot.get("target_display", ""),
            "attribute_displays": ref_snapshot.get("attribute_displays", []),
            "feature_displays": ref_snapshot.get("feature_displays", []),
            "bound_attribute_displays": ref_snapshot.get("bound_attribute_displays", []),
            "runtime_bound_attribute_units": runtime_bound_attribute_units,
            "packet_attribute_names": packet_attribute_names,
            "runtime_attribute_names": runtime_attribute_names,
            "all_attribute_names": all_attribute_names,
            "bound_attribute_names": list(runtime_attribute_names),
            "member_count": ref_snapshot.get("member_count", 0),
            "er": er,
            "ev": ev,
            "cp_delta": energy.get("cognitive_pressure_delta", er - ev),
            "cp_abs": energy.get("cognitive_pressure_abs", abs(er - ev)),
            "salience_score": energy.get("salience_score", max(er, ev)),
            "fatigue": energy.get("fatigue", 0.0),
            "recency_gain": energy.get("recency_gain", 0.0),
            "delta_er": dynamics.get("delta_er", 0.0),
            "delta_ev": dynamics.get("delta_ev", 0.0),
            "updated_at": item.get("updated_at", 0),
            "created_at": item.get("created_at", 0),
        }

    def _priority_score(
        self,
        item: dict,
        *,
        weights: dict | None = None,
        focus_directives: list[dict] | None = None,
        focus_boost: float | None = None,
    ) -> float:
        weights = weights or self._config
        er = float(item.get("er", 0.0))
        ev = float(item.get("ev", 0.0))
        total_energy = er + ev
        cp_abs = float(item.get("cp_abs", 0.0))
        salience = float(item.get("salience_score", 0.0))
        updated_at = float(item.get("updated_at", 0.0))
        fatigue = float(item.get("fatigue", 0.0))
        recency_gain = float(item.get("recency_gain", 0.0))
        sa_count_modifier = self._sa_count_preference_modifier(item=item)

        score = (
            total_energy * float(weights.get("priority_weight_total_energy", 1.25))
            + cp_abs * float(weights.get("priority_weight_cp_abs", 0.35))
            + salience * float(weights.get("priority_weight_salience", 0.15))
            + updated_at * float(weights.get("priority_weight_updated_at", 1e-12))
            - fatigue * float(weights.get("priority_weight_fatigue", 0.0))
            + recency_gain * float(weights.get("priority_weight_recency_gain", 0.0))
        )
        score *= float(sa_count_modifier.get("scale", 1.0) or 1.0)
        score += float(sa_count_modifier.get("bonus", 0.0) or 0.0)

        resolved_focus_boost = (
            float(focus_boost)
            if focus_boost is not None
            else self._compute_focus_boost(item, focus_directives)
        )
        if resolved_focus_boost > 0.0:
            score += resolved_focus_boost * float(weights.get("focus_boost_weight", 1.0))
        return round(float(score), 12)

    def _item_sa_count(self, item: dict) -> int:
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        token_count = 0
        if isinstance(ref_snapshot, dict):
            token_count = int(ref_snapshot.get("token_count", 0) or 0)
            if token_count <= 0:
                token_count = len(ref_snapshot.get("flat_tokens", []) or [])
            if token_count <= 0:
                token_count = int(ref_snapshot.get("member_count", 0) or 0)
        if token_count <= 0:
            token_count = int(item.get("token_count", 0) or 0)
        return max(1, int(token_count or 1))

    def _sa_count_preference_modifier(self, *, item: dict) -> dict[str, float]:
        if not bool(self._config.get("sa_count_preference_enabled", True)):
            return {"token_count": float(self._item_sa_count(item)), "distance": 0.0, "bonus": 0.0, "scale": 1.0}

        token_count = float(self._item_sa_count(item))
        peak = max(1.0, float(self._config.get("sa_count_preference_peak", 4.0) or 4.0))
        lower_dead = max(0.0, float(self._config.get("sa_count_preference_no_reward_below_or_equal", 2.0) or 2.0))
        upper_dead = max(peak, float(self._config.get("sa_count_preference_no_reward_above_or_equal", 6.0) or 6.0))
        reward_cap = max(0.0, float(self._config.get("sa_count_preference_reward", 0.42) or 0.42))
        penalty_cap = max(0.0, float(self._config.get("sa_count_preference_penalty", 0.14) or 0.14))
        min_scale = max(0.05, min(1.0, float(self._config.get("sa_count_preference_min_scale", 0.5) or 0.5)))
        distance = abs(token_count - peak)

        reward_zone_half_width = max(0.5, min(peak - lower_dead, upper_dead - peak))
        if lower_dead < token_count < upper_dead:
            norm = min(1.0, distance / reward_zone_half_width)
            reward_strength = max(0.0, 1.0 - norm)
            reward_strength = reward_strength * reward_strength
            bonus = reward_cap * reward_strength
            scale = 1.0
        else:
            bonus = 0.0
            if token_count <= lower_dead:
                hard_distance = max(0.0, lower_dead - token_count)
                hard_span = max(1.0, lower_dead - 1.0)
            else:
                hard_distance = max(0.0, token_count - upper_dead)
                hard_span = max(1.0, upper_dead)
            penalty_strength = min(1.0, hard_distance / hard_span)
            scale = max(min_scale, 1.0 - penalty_cap * penalty_strength)

        return {
            "token_count": float(token_count),
            "distance": float(distance),
            "bonus": round(float(bonus), 8),
            "scale": round(float(scale), 8),
        }

    def _build_reward_action_context(
        self,
        items: list[dict] | None,
        *,
        signal_names: set[str] | None = None,
    ) -> dict[str, Any]:
        signal_names = signal_names if signal_names is not None else self._special_attribute_name_set()
        by_target_ref: dict[str, float] = {}
        by_target_item: dict[str, float] = {}
        action_node_count = 0
        signal_item_count = 0

        for item in items or []:
            if not isinstance(item, dict):
                continue
            ref_object_type = str(item.get("ref_object_type", "") or "").strip()
            ref_object_id = str(item.get("ref_object_id", "") or "").strip()
            total_energy = max(0.0, float(item.get("er", 0.0) or 0.0)) + max(0.0, float(item.get("ev", 0.0) or 0.0))
            if self._extract_direct_signal_name(item=item, signal_names=signal_names):
                signal_item_count += 1
            if ref_object_type != "action_node":
                continue
            action_node_count += 1
            ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
            target_ref_object_id = str(ref_snapshot.get("target_ref_object_id", item.get("target_ref_object_id", "")) or "").strip()
            target_item_id = str(ref_snapshot.get("target_item_id", item.get("target_item_id", "")) or "").strip()
            if target_ref_object_id:
                by_target_ref[target_ref_object_id] = max(float(by_target_ref.get(target_ref_object_id, 0.0) or 0.0), float(total_energy))
            if target_item_id:
                by_target_item[target_item_id] = max(float(by_target_item.get(target_item_id, 0.0) or 0.0), float(total_energy))

        return {
            "by_target_ref": by_target_ref,
            "by_target_item": by_target_item,
            "summary": {
                "enabled": bool(
                    self._config.get("reward_action_humanlike_v2_enabled", True)
                    and self._config.get("reward_action_priority_enabled", True)
                ),
                "signal_item_count": int(signal_item_count),
                "action_node_count": int(action_node_count),
                "targeted_ref_count": int(len(by_target_ref)),
                "targeted_item_count": int(len(by_target_item)),
            },
        }

    def _compute_reward_action_bonus(
        self,
        item: dict,
        reward_action_context: dict[str, Any] | None,
        *,
        signal_names: set[str] | None = None,
    ) -> dict[str, Any]:
        enabled = bool(self._config.get("reward_action_humanlike_v2_enabled", True)) and bool(
            self._config.get("reward_action_priority_enabled", True)
        )
        detail: dict[str, Any] = {"enabled": bool(enabled), "bonus": 0.0}
        if not enabled or not isinstance(item, dict):
            return detail

        signal_names = signal_names if signal_names is not None else self._special_attribute_name_set()
        total_energy = max(0.0, float(item.get("er", 0.0) or 0.0)) + max(0.0, float(item.get("ev", 0.0) or 0.0))
        bonus = 0.0

        ref_object_type = str(item.get("ref_object_type", "") or "").strip()
        ref_object_id = str(item.get("ref_object_id", "") or "").strip()
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        item_role = str(item.get("role", ref_snapshot.get("role", "")) or "").strip().lower()
        is_action_node = ref_object_type == "action_node"
        direct_signal_name = self._extract_direct_signal_name(item=item, signal_names=signal_names)
        matched_signal_values = self._extract_signal_attribute_values(item=item, signal_names=signal_names)
        carrier_score = self._compute_structure_carrier_score(item=item, matched_signal_values=matched_signal_values)
        is_special_standalone = bool(direct_signal_name or item_role == "attribute")
        is_structure_carrier = bool(matched_signal_values) and carrier_score >= float(
            self._config.get("reward_action_min_carrier_score", 0.35) or 0.35
        )

        detail["direct_signal_name"] = str(direct_signal_name or "")
        detail["matched_signal_values"] = {str(k): round(float(v), 8) for k, v in matched_signal_values.items()}
        detail["structure_carrier_score"] = round(float(carrier_score), 8)
        detail["is_special_standalone"] = bool(is_special_standalone)
        detail["is_structure_carrier"] = bool(is_structure_carrier)
        detail["role"] = item_role

        if bool(self._config.get("reward_action_structure_first_mode", True)):
            if is_special_standalone:
                part = float(self._config.get("reward_action_special_standalone_penalty", 0.52) or 0.52)
                part += min(1.5, float(total_energy)) * float(
                    self._config.get("reward_action_special_standalone_energy_gain", 0.14) or 0.14
                )
                bonus -= max(0.0, float(part))
                detail["special_standalone_penalty"] = round(float(part), 8)

            if is_action_node:
                part = float(self._config.get("reward_action_action_node_penalty", 0.46) or 0.46)
                part += min(1.5, float(total_energy)) * float(
                    self._config.get("reward_action_action_node_energy_gain", 0.1) or 0.1
                )
                bonus -= max(0.0, float(part))
                detail["action_node_penalty"] = round(float(part), 8)
        else:
            if direct_signal_name:
                part = float(self._config.get("reward_action_direct_signal_bonus", 0.72) or 0.72)
                part += min(1.5, float(total_energy)) * float(
                    self._config.get("reward_action_direct_signal_energy_gain", 0.48) or 0.48
                )
                bonus += max(0.0, float(part))
                detail["direct_signal_bonus"] = round(float(part), 8)

            if is_action_node:
                part = float(self._config.get("reward_action_action_node_bonus", 0.62) or 0.62)
                part += min(1.5, float(total_energy)) * float(
                    self._config.get("reward_action_action_node_energy_gain", 0.45) or 0.45
                )
                bonus += max(0.0, float(part))
                detail["action_node_bonus"] = round(float(part), 8)

        if matched_signal_values and is_structure_carrier:
            matched_count = len(matched_signal_values)
            matched_value_sum = sum(float(value) for value in matched_signal_values.values())
            part = float(matched_count) * float(self._config.get("reward_action_structure_carrier_bonus", 0.48) or 0.48)
            part += min(2.0, float(matched_value_sum)) * float(
                self._config.get("reward_action_structure_carrier_value_gain", 0.18) or 0.18
            )
            part += float(carrier_score) * float(
                self._config.get("reward_action_structure_carrier_context_gain", 0.24) or 0.24
            )
            bonus += max(0.0, float(part))
            detail["structure_carrier_bonus"] = round(float(part), 8)

        ctx = reward_action_context if isinstance(reward_action_context, dict) else {}
        by_target_ref = ctx.get("by_target_ref", {}) if isinstance(ctx.get("by_target_ref", {}), dict) else {}
        by_target_item = ctx.get("by_target_item", {}) if isinstance(ctx.get("by_target_item", {}), dict) else {}
        action_target_strength = 0.0
        item_id = str(item.get("item_id", "") or "").strip()
        if item_id:
            action_target_strength = max(action_target_strength, float(by_target_item.get(item_id, 0.0) or 0.0))
        if ref_object_id:
            action_target_strength = max(action_target_strength, float(by_target_ref.get(ref_object_id, 0.0) or 0.0))
        for alias in item.get("ref_alias_ids", []) or []:
            alias_id = str(alias or "").strip()
            if alias_id:
                action_target_strength = max(action_target_strength, float(by_target_ref.get(alias_id, 0.0) or 0.0))
        if action_target_strength > 0.0 and ref_object_type != "action_node" and carrier_score > 0.0:
            part = float(self._config.get("reward_action_target_association_bonus", 0.58) or 0.58) * float(carrier_score)
            part += min(2.0, float(action_target_strength)) * float(
                self._config.get("reward_action_target_association_energy_gain", 0.34) or 0.34
            )
            bonus += max(0.0, float(part))
            detail["action_target_strength"] = round(float(action_target_strength), 8)
            detail["action_target_bonus"] = round(float(part), 8)

        bonus_cap = max(0.0, float(self._config.get("reward_action_bonus_cap", 2.4) or 2.4))
        penalty_cap = max(0.0, float(self._config.get("reward_action_penalty_cap", bonus_cap) or bonus_cap))
        bonus = max(-float(penalty_cap), min(float(bonus_cap), float(bonus)))
        detail["bonus"] = round(float(bonus), 8)
        return detail

    def _special_attribute_name_set(self) -> set[str]:
        names: set[str] = set()
        for bucket in (
            self._config.get("reward_action_signal_names", []) or [],
            self._config.get("reward_action_special_attribute_names", []) or [],
        ):
            for name in bucket:
                text = str(name or "").strip()
                if text:
                    names.add(text)
        return names

    def _compute_structure_carrier_score(self, *, item: dict, matched_signal_values: dict[str, float] | None = None) -> float:
        if not isinstance(item, dict):
            return 0.0
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        ref_object_type = str(item.get("ref_object_type", "") or "").strip()
        role = str(item.get("role", ref_snapshot.get("role", "")) or "").strip().lower()
        token_count = int(ref_snapshot.get("token_count", item.get("token_count", 0)) or 0)
        member_count = int(ref_snapshot.get("member_count", item.get("member_count", 0)) or 0)
        feature_displays = item.get("feature_displays", ref_snapshot.get("feature_displays", [])) or []
        anchor_display = str(item.get("anchor_display", ref_snapshot.get("anchor_display", "")) or "").strip()
        context_text = str(item.get("context_text", ref_snapshot.get("context_text", "")) or "").strip()
        target_display = str(item.get("target_display", ref_snapshot.get("target_display", "")) or "").strip()
        context_ref = str(item.get("context_ref_object_id", ref_snapshot.get("context_ref_object_id", "")) or "").strip()

        score = 0.0
        if role != "attribute" and ref_object_type != "action_node":
            score += 0.35
        if ref_object_type in {"st", "sg", "em"} or member_count > 1 or token_count > 1:
            score += 0.25
        if feature_displays:
            score += 0.2
        if anchor_display or context_text or target_display or context_ref:
            score += 0.2
        if matched_signal_values:
            score += 0.1
        return max(0.0, min(1.0, float(score)))

    def _repeat_attention_key(self, item: dict) -> str:
        if not isinstance(item, dict):
            return ""
        semantic_context_key = ""
        if bool(self._config.get("attention_repeat_fatigue_semantic_context_first", True)):
            semantic_context_key = str(item.get("semantic_context_key", "") or "").strip()
            if not semantic_context_key:
                semantic_context_key = str(semantic_context_key_from_item(item) or "").strip()
            if semantic_context_key:
                return f"semctx:{semantic_context_key}"
        ref_object_type = str(item.get("ref_object_type", item.get("object_type", "")) or "").strip()
        ref_object_id = str(item.get("ref_object_id", "") or "").strip()
        if ref_object_id:
            return f"{ref_object_type}:{ref_object_id}" if ref_object_type else ref_object_id
        semantic_signature = str(item.get("semantic_signature", "") or "").strip()
        if semantic_signature:
            return f"semantic:{semantic_signature}"
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        content_signature = str(ref_snapshot.get("content_signature", "") or "").strip()
        if content_signature:
            return f"content:{content_signature}"
        item_id = str(item.get("item_id", "") or "").strip()
        return f"item:{item_id}" if item_id else ""

    def _compute_repeat_attention_penalty(
        self,
        *,
        item: dict,
        attention_call_index: int,
        signal_names: set[str] | None = None,
    ) -> dict[str, Any]:
        enabled = bool(self._config.get("attention_repeat_fatigue_enabled", True))
        detail: dict[str, Any] = {"enabled": enabled, "penalty": 0.0}
        if not enabled or not isinstance(item, dict):
            return detail
        key = self._repeat_attention_key(item)
        detail["key"] = key
        if not key:
            return detail
        state = self._repeat_attention_state.get(key, {})
        last_call = int(state.get("last_call", -1) or -1)
        strength = float(state.get("strength", 0.0) or 0.0)
        if last_call < 0 or strength <= 0.0:
            return detail
        gap = max(0, int(attention_call_index) - last_call)
        recovery = max(0.0, min(1.0, float(self._config.get("attention_repeat_fatigue_recovery_per_call", 0.55) or 0.55)))
        effective_strength = float(strength) * (float(recovery) ** float(gap))
        signal_names = signal_names if signal_names is not None else self._special_attribute_name_set()
        role = str(
            item.get(
                "role",
                ((item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}).get("role", "")),
            )
            or ""
        ).strip().lower()
        is_special_standalone = bool(
            self._extract_direct_signal_name(item=item, signal_names=signal_names) or role == "attribute"
        )
        matched_signal_values = self._extract_signal_attribute_values(item=item, signal_names=signal_names)
        carrier_score = self._compute_structure_carrier_score(item=item, matched_signal_values=matched_signal_values)
        is_structure_carrier = bool(matched_signal_values) and carrier_score >= float(
            self._config.get("reward_action_min_carrier_score", 0.35) or 0.35
        )
        fatigue_multiplier = 1.0
        if is_special_standalone:
            fatigue_multiplier *= max(
                1.0,
                float(self._config.get("attention_repeat_fatigue_special_multiplier", 1.55) or 1.55),
            )
        if is_structure_carrier:
            fatigue_multiplier *= max(
                0.0,
                float(self._config.get("attention_repeat_fatigue_structure_carrier_multiplier", 0.82) or 0.82),
            )
        penalty = min(
            max(0.0, float(self._config.get("attention_repeat_fatigue_max_penalty", 1.25) or 1.25)),
            max(0.0, float(effective_strength))
            * max(0.0, float(self._config.get("attention_repeat_fatigue_penalty_gain", 0.42) or 0.42))
            * max(0.0, float(fatigue_multiplier)),
        )
        detail["gap_calls"] = int(gap)
        detail["carried_strength"] = round(float(effective_strength), 8)
        detail["is_special_standalone"] = bool(is_special_standalone)
        detail["is_structure_carrier"] = bool(is_structure_carrier)
        detail["fatigue_multiplier"] = round(float(fatigue_multiplier), 8)
        detail["penalty"] = round(float(penalty), 8)
        return detail

    def _update_repeat_attention_state(self, *, selected_items: list[dict], attention_call_index: int) -> None:
        if not bool(self._config.get("attention_repeat_fatigue_enabled", True)):
            return
        recovery = max(0.0, min(1.0, float(self._config.get("attention_repeat_fatigue_recovery_per_call", 0.55) or 0.55)))
        selected_gain = max(0.0, float(self._config.get("attention_repeat_fatigue_selected_gain", 1.0) or 1.0))
        max_strength = max(0.0, float(self._config.get("attention_repeat_fatigue_max_strength", 4.0) or 4.0))
        window_calls = max(1, int(self._config.get("attention_repeat_fatigue_window_calls", 6) or 6))
        next_state: dict[str, dict[str, float]] = {}

        for key, state in list(self._repeat_attention_state.items()):
            if not key or not isinstance(state, dict):
                continue
            last_call = int(state.get("last_call", -1) or -1)
            strength = float(state.get("strength", 0.0) or 0.0)
            if last_call < 0 or strength <= 0.0:
                continue
            gap = max(0, int(attention_call_index) - last_call)
            if gap > window_calls * 4:
                continue
            carried = float(strength) * (float(recovery) ** float(gap))
            if carried <= 1e-4:
                continue
            next_state[key] = {"last_call": float(last_call), "strength": float(carried)}

        for item in selected_items or []:
            key = self._repeat_attention_key(item)
            if not key:
                continue
            prev = next_state.get(key, {})
            prev_strength = float(prev.get("strength", 0.0) or 0.0)
            updated_strength = min(float(max_strength), max(0.0, float(prev_strength)) + float(selected_gain))
            next_state[key] = {"last_call": float(attention_call_index), "strength": float(updated_strength)}

        self._repeat_attention_state = next_state

    @staticmethod
    def _extract_direct_signal_name(*, item: dict, signal_names: set[str]) -> str:
        if not isinstance(item, dict) or not signal_names:
            return ""

        def _norm(value: Any) -> str:
            return str(value or "").strip()

        for candidate in (
            item.get("ref_object_id", ""),
            item.get("signal_name", ""),
            item.get("attribute_name", ""),
        ):
            name = _norm(candidate)
            if name in signal_names:
                return name

        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        for candidate in (
            ref_snapshot.get("signal_name", ""),
            ref_snapshot.get("attribute_name", ""),
        ):
            name = _norm(candidate)
            if name in signal_names:
                return name
        return ""

    @staticmethod
    def _extract_signal_attribute_values(*, item: dict, signal_names: set[str]) -> dict[str, float]:
        result: dict[str, float] = {}
        if not isinstance(item, dict) or not signal_names:
            return result

        def _push(name: str, value: Any) -> None:
            attr_name = str(name or "").strip()
            if not attr_name or attr_name not in signal_names:
                return
            numeric = 1.0
            try:
                if value not in (None, ""):
                    numeric = abs(float(value))
            except Exception:
                numeric = 1.0
            result[attr_name] = max(float(result.get(attr_name, 0.0) or 0.0), float(numeric))

        _push(str(item.get("attribute_name", "") or ""), item.get("attribute_value", None))
        for field in ("all_attribute_names", "packet_attribute_names", "runtime_attribute_names", "bound_attribute_names"):
            for name in item.get(field, []) or []:
                _push(str(name), 1.0)

        for unit in item.get("runtime_bound_attribute_units", []) or []:
            if not isinstance(unit, dict):
                continue
            _push(str(unit.get("attribute_name", "") or ""), unit.get("attribute_value", None))

        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        _push(str(ref_snapshot.get("attribute_name", "") or ""), ref_snapshot.get("attribute_value", None))
        for unit in ref_snapshot.get("runtime_bound_attribute_units", []) or []:
            if not isinstance(unit, dict):
                continue
            _push(str(unit.get("attribute_name", "") or ""), unit.get("attribute_value", None))

        return result

    @staticmethod
    def _compute_focus_boost(item: dict, focus_directives: list[dict] | None) -> float:
        """
                                               ?
                     target_ref_object_id/target_item_id                  ?        boost = directive.focus_boost * directive.strength
        """
        if not focus_directives:
            return 0.0

        ref_id = str(item.get("ref_object_id", "") or "")
        ref_type = str(item.get("ref_object_type", "") or "")
        item_id = str(item.get("item_id", "") or "")

        best = 0.0
        for directive in focus_directives:
            if not isinstance(directive, dict):
                continue
            target_ref_id = str(directive.get("target_ref_object_id", "") or "")
            target_ref_type = str(directive.get("target_ref_object_type", "") or "")
            target_item_id = str(directive.get("target_item_id", "") or "")

            ref_match = bool(target_ref_id) and target_ref_id == ref_id and (not target_ref_type or target_ref_type == ref_type)
            item_match = bool(target_item_id) and target_item_id == item_id
            if not ref_match and not item_match:
                continue

            strength = float(directive.get("strength", 0.0) or 0.0)
            focus_boost = float(directive.get("focus_boost", 0.0) or 0.0)
            best = max(best, max(0.0, strength) * max(0.0, focus_boost))

        return float(best)

    def _make_cam_snapshot(self, *, selected_items: list[dict], trace_id: str, tick_id: str) -> dict:
        top_items: list[dict] = []
        type_counts: dict[str, int] = {}
        high_er = 0
        high_ev = 0
        high_cp = 0

        for item in selected_items:
            memory_er = round(float(item.get("memory_er", 0.0)), 8)
            memory_ev = round(float(item.get("memory_ev", 0.0)), 8)
            cp_delta = round(memory_er - memory_ev, 8)
            cp_abs = round(abs(cp_delta), 8)
            copied = dict(item)
            copied["er"] = memory_er
            copied["ev"] = memory_ev
            copied["cp_delta"] = cp_delta
            copied["cp_abs"] = cp_abs
            copied["salience_score"] = round(max(memory_er, memory_ev), 8)
            top_items.append(copied)

            ref_type = copied.get("ref_object_type", "unknown")
            type_counts[ref_type] = type_counts.get(ref_type, 0) + 1
            if memory_er >= 0.5:
                high_er += 1
            if memory_ev >= 0.5:
                high_ev += 1
            if cp_abs >= 0.5:
                high_cp += 1

        return {
            "snapshot_id": f"{trace_id}_cam",
            "object_type": "runtime_snapshot",
            "sub_type": "cam_snapshot",
            "schema_version": __schema_version__,
            "trace_id": trace_id,
            "tick_id": tick_id,
            "summary": {
                "active_item_count": len(top_items),
                "high_er_item_count": high_er,
                "high_ev_item_count": high_ev,
                "high_cp_item_count": high_cp,
                "object_type_counts": type_counts,
            },
            "top_items": top_items,
        }

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        return int((time.time() - start) * 1000)

    @staticmethod
    def _make_response(
        success: bool,
        code: str,
        message: str,
        *,
        data: Any = None,
        error: Any = None,
        trace_id: str = "",
        elapsed_ms: int = 0,
    ) -> dict:
        return {
            "success": bool(success),
            "code": str(code),
            "message": str(message),
            "data": data,
            "error": error,
            "meta": {
                "module": __module_name__,
                "interface": "",
                "trace_id": trace_id,
                "elapsed_ms": int(elapsed_ms),
                "logged": True,
            },
        }








