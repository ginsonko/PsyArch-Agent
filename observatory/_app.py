# -*- coding: utf-8 -*-
"""
# sanitized
=============================

# sanitized
  # sanitized
  # sanitized
  # sanitized
  # sanitized

English (short):
  Local observatory application for AP prototype testing and monitoring.
"""

from __future__ import annotations

import copy
import gc
import hashlib
import heapq
import json
import os
import shutil
import shlex
import sys
import time
import webbrowser
from contextlib import nullcontext
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from attention import AttentionFilter
from attention.main import _DEFAULT_CONFIG as ATTENTION_DEFAULT_CONFIG
from cognitive_feeling import CognitiveFeelingSystem
from cognitive_stitching import CognitiveStitchingEngine
from cognitive_feeling.main import _DEFAULT_CONFIG as CFS_DEFAULT_CONFIG
from cognitive_stitching.main import _DEFAULT_CONFIG as COGNITIVE_STITCHING_DEFAULT_CONFIG
from emotion import EmotionManager
from emotion.main import _DEFAULT_CONFIG as EMOTION_DEFAULT_CONFIG
from hdb import HDB
from hdb.main import _DEFAULT_CONFIG as HDB_DEFAULT_CONFIG
from hdb._cut_engine import CutEngine
from hdb._context_metadata import (
    build_context_metadata,
    build_residual_metadata,
    extract_context_metadata,
    extract_residual_metadata,
    merge_context_metadata,
    merge_residual_metadata,
)
from hdb._id_generator import next_id
from hdb._runtime_projection_policy import classify_runtime_projection_block_reason
from hdb._sequence_display import (
    format_group_display,
    format_semantic_group_display,
    format_semantic_sequence_groups,
    format_sequence_groups,
)
from hdb._structure_resolver import resolve_or_create_structure_from_profile
from hdb._structure_resolver import find_exact_structure_by_signature
from state_pool.main import StatePool, _DEFAULT_CONFIG as STATE_POOL_DEFAULT_CONFIG
from state_pool._semantic_identity import semantic_context_key_from_parts
from text_sensor import TextSensor
from text_sensor.main import _DEFAULT_CONFIG as TEXT_SENSOR_DEFAULT_CONFIG
from time_sensor import TimeSensor
from time_sensor.main import TIME_SENSOR_DEFAULT_CONFIG
from innate_script import InnateScriptManager
from innate_script.main import _DEFAULT_CONFIG as IESM_DEFAULT_CONFIG
from action import ActionManager
from action.main import _DEFAULT_CONFIG as ACTION_DEFAULT_CONFIG
from energy_balance import EnergyBalanceController
from energy_balance.main import _DEFAULT_CONFIG as ENERGY_BALANCE_DEFAULT_CONFIG

from ._config_layout import build_config_view, coerce_updates_by_defaults, load_yaml_dict, save_annotated_config
from ._render_html import export_cycle_html
from ._render_terminal import (
    format_help,
    render_check_report,
    render_cycle_report,
    render_group_report,
    render_hdb_snapshot,
    render_header,
    render_repair_report,
    render_state_snapshot,
    render_structure_report,
    render_episodic_report,
)


DEFAULT_CONFIG = {
    "attention_top_n": 16,
    "attention_stub_consume_energy": True,
    "attention_memory_energy_ratio": 0.5,
    "snapshot_top_k": 24,
    "final_state_snapshot_top_k": 24,
    "induction_source_selection_mode": "all_energetic_runtime",
    "induction_source_max_items": 0,
    "induction_source_candidate_top_k": 24,
    "induction_source_ev_quota_ratio": 0.5,
    "induction_source_local_target_bias_mode": "prefer_nonzero",
    "induction_source_skip_memory_terminal_enabled": True,
    "induction_target_batch_pool_apply_enabled": True,
    "induction_projection_stable_sa_ids_enabled": True,
    "induction_projection_batch_dedupe_sa_enabled": True,
    "induction_projection_sa_min_energy_floor": 0.001,
    "induction_projection_runtime_st_enabled": True,
    "induction_projection_mode": "growth",
    "growth_projection_identity_resolution_enabled": True,
    "growth_projection_runtime_only_for_unbacked_virtual": True,
    "growth_projection_component_energy_enabled": True,
    "growth_projection_low_energy_prune_enabled": True,
    "growth_projection_create_hdb_structure_enabled": True,
    "growth_projection_er_base_weight_ratio": 0.08,
    "growth_projection_er_base_weight_cap": 0.35,
    "growth_projection_source_er_runtime_share_enabled": True,
    "growth_projection_source_er_runtime_share_ratio": 1.0,
    "growth_projection_identity_shared_cache_enabled": True,
    "growth_projection_skip_create_exact_lookup_after_probe_enabled": True,
    "growth_projection_persistence_batch_enabled": True,
    "growth_projection_overprediction_gate_enabled": False,
    "induction_target_runtime_insert_log_enabled": False,
    "induction_target_runtime_ref_fast_merge_enabled": True,
    "cognitive_stitching_stage": "disabled",
    "residual_tail_memory_projection_enabled": True,
    "residual_tail_memory_projection_min_energy": 0.05,
    "residual_tail_memory_projection_fast_ref_merge_enabled": True,
    "runtime_residual_package_enabled": False,
    "runtime_residual_package_min_energy": 0.05,
    "runtime_residual_package_stable_id_enabled": True,
    "runtime_residual_package_attention_promotion_enabled": False,
    "runtime_residual_package_attention_promotion_max_per_tick": 8,
    "runtime_residual_package_high_energy_promotion_enabled": False,
    "runtime_residual_package_high_energy_promotion_min_energy": 1.0,
    "runtime_residual_package_immediate_high_energy_promotion_enabled": False,
    "runtime_residual_package_exact_rebind_fast_path_enabled": True,
    "runtime_residual_package_exact_rebind_probe_hdb_on_miss_enabled": False,
    "runtime_residual_package_full_identity_promotion_enabled": True,
    "runtime_residual_package_full_identity_create_enabled": True,
    "induction_projection_skip_new_target_below_pool_threshold_enabled": True,
    "induction_projection_new_target_min_energy_floor": 0.0,
    # Pipeline-stage master switches:
    # - Growth induction is now the main path; CS is retained as rollback/audit.
    # - Structure-level retrieval-storage is now a legacy comparison stage and stays off by default.
    # - Goal B char-SA string mode is still the current main text path and stays on by default.
    "enable_cognitive_stitching": False,
    "enable_structure_level_retrieval_storage": False,
    "enable_goal_b_char_sa_string_mode": True,
    "cfs_source_mode": "iesm",
    "iesm_lightweight_state_window_checks": True,
    "iesm_context_pool_item_limit": 256,
    "iesm_context_pool_bucket_size": 96,
    "iesm_context_pool_min_total_energy": 1e-8,
    "iesm_emotion_post_reuse_context_enabled": True,
    "iesm_post_pool_context_delta_refresh_enabled": True,
    "iesm_fast_pool_item_summary_enabled": True,
    "iesm_pool_bind_attribute_drop_zero_numeric_enabled": True,
    "iesm_pool_bind_attribute_zero_numeric_epsilon": 1e-9,
    "runtime_pool_item_summary_cache_enabled": False,
    "runtime_pool_item_summary_cache_max_entries": 4096,
    "runtime_pool_summary_fast_metadata_enabled": True,
    "final_hdb_snapshot_lightweight_enabled": True,
    "induction_target_gc_pause_enabled": True,
    "run_cycle_gc_pause_enabled": True,
    "maintenance_lightweight_summary_enabled": True,
    "export_html": True,
    "export_json": True,
    "export_full_cycle_json": False,
    "export_cycle_json_history": False,
    "export_cycle_html_history": False,
    "export_compact_json": True,
    "export_compact_html": True,
    "export_cycle_json_history_limit": 12,
    "export_cycle_html_history_limit": 12,
    "export_cycle_json_max_bytes": 2 * 1024 * 1024,
    "export_cycle_html_max_bytes": 4 * 1024 * 1024,
    "outputs_cycle_max_total_bytes": 64 * 1024 * 1024,
    "outputs_cycle_max_age_days": 2,
    "auto_open_html_report": False,
    "history_limit": 24,
    "stimulus_packet_preview_group_limit": 10,
    "stimulus_packet_preview_unit_limit": 24,
    "stimulus_packet_preview_flat_token_limit": 96,
    "stimulus_packet_preview_bundle_limit": 24,
    "default_launch_mode": "web",
    "web_host": "127.0.0.1",
    "web_port": 8765,
    "web_auto_open_browser": True,
    "sensor_default_mode": "advanced",
    "sensor_tokenizer_backend": "jieba",
    "sensor_enable_token_output": True,
    "sensor_enable_char_output": False,
    "sensor_enable_stimulus_intensity_attribute_sa": False,
    "sensor_stimulus_intensity_attribute_min_er": 0.0,
    "sensor_attribute_er_ratio": 0.25,
    "sensor_attribute_ev_ratio": 0.0,
    "sensor_enable_echo": True,
    "sensor_include_echoes_in_packet": True,
    "state_pool_enable_placeholder_interfaces": False,
    "state_pool_enable_script_broadcast": False,
    "hdb_enable_background_repair": True,
    "cognitive_stitching_runtime_override": {},
    "input_chunking_enabled": True,
    "input_chunk_soft_limit": 10,
    "input_chunk_hard_limit": 30,
    "projection_fatigue_enabled": True,
    "projection_fatigue_decay": 0.82,
    "projection_fatigue_step": 0.28,
    "projection_fatigue_min_effective_ev": 0.03,
    "projection_fatigue_min_effective_er": 0.03,
    "projection_fatigue_lazy_decay_enabled": True,
    "projection_fatigue_cleanup_interval_ticks": 32,
    "memory_feedback_stimulus_packet_structure_projection_enabled": True,
    "memory_feedback_stimulus_packet_structure_projection_ratio": 0.55,
    "memory_feedback_stimulus_packet_structure_projection_adaptive_enabled": True,
    "memory_feedback_stimulus_packet_structure_projection_adaptive_min_ratio": 0.20,
    "memory_feedback_stimulus_packet_structure_projection_adaptive_ev_er_floor": 0.55,
    "memory_feedback_stimulus_packet_structure_projection_adaptive_ev_er_ceiling": 0.95,
    "memory_feedback_structure_projection_max_targets": 6,
    "memory_feedback_structure_projection_budget_aware_enabled": True,
    "memory_feedback_structure_projection_min_effective_ev": 0.01,
    "memory_feedback_structure_projection_min_effective_er": 0.01,
    # Teacher feedback attributes should carry live energy, otherwise they exist
    # only as zero-energy labels and can never win attention / internal projection.
    # Use scales instead of a hardcoded constant so the old zero-energy behavior
    # remains recoverable by setting both scales to 0.
    "teacher_feedback_attribute_er_scale": 1.0,
    "teacher_feedback_attribute_ev_scale": 0.0,
    # Teacher feedback can also emit a next-tick focus directive so the
    # rewarded / punished target has a fair chance to re-enter CAM instead of
    # staying as a low-energy bound label on a drowned-out anchor.
    "teacher_feedback_focus_directive_enabled": True,
    "teacher_feedback_focus_strength_scale": 1.0,
    "teacher_feedback_focus_boost": 1.2,
    "teacher_feedback_focus_ttl_ticks": 2,
    "teacher_feedback_focus_context_carrier_enabled": True,
    "teacher_feedback_focus_context_carrier_top_k": 1,
    "teacher_feedback_focus_context_carrier_strength_scale": 0.85,
    # When the resolved teacher target is too atomic (for example `{A}`) and is
    # likely to be shadowed by larger string structures in CAM selection, mirror
    # the same teacher attribute onto current attention-visible contextual
    # carrier structures as a helper path. Keep it switchable and scaled so the
    # old anchor-only behavior remains available for rollback / ablation.
    "teacher_feedback_context_binding_enabled": True,
    "teacher_feedback_context_binding_only_when_primary_atomic": True,
    "teacher_feedback_context_binding_top_k": 1,
    "teacher_feedback_context_binding_strength_scale": 0.85,
    # Teacher local feedback alias cache:
    # Teacher labels are external supervision side-channels. Besides binding the
    # chosen runtime structure, keep a short-lived text-matched alias so the next
    # same-kind input action target (for example `ctx_input_current`) can read the
    # teacher value as local action shaping without parsing display strings.
    "teacher_feedback_local_alias_cache_enabled": True,
    "teacher_feedback_local_alias_cache_ttl_ticks": 6,
    "teacher_feedback_local_alias_cache_max_entries": 64,
    "teacher_feedback_local_alias_cache_min_score": 0.55,
    "teacher_feedback_local_alias_cache_min_chars": 6,
    # Reward/Action humanlike V2:
    # - reward/punish should exist as first-class runtime SA nodes;
    # - action nodes should re-enter StatePool as attention-visible objects;
    # - attention should apply soft bonuses instead of hard action-credit windows.
    "reward_action_humanlike_v2_enabled": True,
    "reward_action_runtime_signal_nodes_enabled": True,
    "reward_action_runtime_signal_er_scale": 0.0,
    "reward_action_runtime_signal_ev_scale": 1.0,
    "reward_action_runtime_action_nodes_enabled": True,
    "reward_action_runtime_action_node_drive_to_ev_scale": 1.0,
    "reward_action_runtime_action_node_execute_to_er_scale": 1.0,
    "reward_action_runtime_action_node_max_sync": 24,
    "dedicated_memory_pool_enabled": False,
    "residual_memory_as_structure_enabled": True,
    "residual_memory_as_structure_shadow_mode": False,
    "residual_memory_runtime_object_type": "em",
    "unified_numeric_scoring_enabled": True,
    "attribute_soft_scoring_enabled": True,
    "sequence_soft_scoring_enabled": True,
    "time_factor_soft_bonus_enabled": True,
    "context_concat_v2_enabled": True,
}

OBSERVATORY_CONFIG_SCHEMA = {
    "title": "Observatory Config",
    "description": "Configuration schema for the observatory prototype.",
    "groups": [],
}

def _load_yaml_config(path: str) -> dict:
    return load_yaml_dict(path)


def _serialize_simple_yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f"\"{escaped}\""


def _dump_simple_yaml(data: dict[str, Any], indent: int = 0) -> str:
    lines: list[str] = []
    prefix = " " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            if value:
                lines.append(_dump_simple_yaml(value, indent + 2))
            else:
                lines.append(f"{prefix}  {{}}")
        elif isinstance(value, list):
            if not value:
                lines.append(f"{prefix}{key}: []")
                continue
            lines.append(f"{prefix}{key}:")
            for item in value:
                if isinstance(item, dict):
                    lines.append(f"{prefix}  -")
                    lines.append(_dump_simple_yaml(item, indent + 4))
                else:
                    lines.append(f"{prefix}  - {_serialize_simple_yaml_scalar(item)}")
        else:
            lines.append(f"{prefix}{key}: {_serialize_simple_yaml_scalar(value)}")
    return "\n".join(lines)


def _write_yaml_config(path: str, data: dict[str, Any]) -> None:
    try:
        import yaml

        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
        return
    except ImportError:
        pass

    content = _dump_simple_yaml(data).strip() + "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


class ObservatoryApp:
    def __init__(self, config_path: str = "", config_override: dict | None = None):
        self._config_path = config_path or os.path.join(os.path.dirname(__file__), "config", "observatory_config.yaml")
        self._config_override = copy.deepcopy(config_override or {})
        self._config = self._build_config(config_override)
        self.output_dir = Path(__file__).resolve().parent / "outputs"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.sensor = TextSensor(
            config_override=self._sensor_config_override()
        )
        # sanitized
        # sanitized
        self.time_sensor = TimeSensor()
        self.pool = StatePool(
            config_override=self._state_pool_config_override()
        )
        self.hdb = HDB(config_override=self._hdb_config_override())
        self.attention = AttentionFilter(
            config_override=self._attention_config_override()
        )
        self.cfs = CognitiveFeelingSystem()
        self.cognitive_stitching = CognitiveStitchingEngine(
            config_override=self._cognitive_stitching_config_override()
        )
        self.emotion = EmotionManager()
        self.iesm = InnateScriptManager()
        # sanitized
        # sanitized
        # sanitized
        self.action = ActionManager(config_override=self._action_config_override())
        # sanitized
        # sanitized
        # sanitized
        # sanitized
        # sanitized
        self.energy_balance = EnergyBalanceController()
        self.cut_engine = CutEngine(config=self._cut_engine_config_override())
        self.tick_counter = 0
        self._last_report: dict[str, Any] | None = None
        self._report_history: list[dict[str, Any]] = []
        self._last_report_trace_id: str = ""
        self._started_at = int(time.time() * 1000)
        self._pending_focus_directives: list[dict[str, Any]] = []
        self._last_modulation: dict[str, Any] = {}
        self._pending_external_text_chunks: list[str] = []
        self._current_external_source_text: str = ""
        self._projection_fatigue: dict[str, Any] = {}
        self._projection_fatigue_last_cleanup_tick = 0
        self._runtime_pool_item_summary_cache: dict[tuple, dict[str, Any]] = {}
        self._teacher_local_feedback_alias_cache: list[dict[str, Any]] = []
        self._runtime_residual_exact_rebind_cache: dict[str, str] = {}
        # sanitized
        # sanitized
        self._hdb_config_base: dict[str, Any] = dict(self.hdb._config)
        self.cut_engine.update_config(self._cut_engine_config_override())
        self.cut_engine.update_config(self._cut_engine_config_override())
        self._cleanup_output_reports()
        self._silence_jieba_logs()

    def close(self) -> None:
        self.sensor._logger.close()
        self.time_sensor.close()
        self.pool._logger.close()
        self.hdb.close()
        self.attention.close()
        self.cfs.close()
        self.cognitive_stitching.close()
        self.emotion.close()
        self.iesm.close()
        self.action.close()
        self.energy_balance.close()

    def _split_input_text_for_ticks(self, text: str) -> list[str]:
        raw = str(text or "")
        if not raw:
            return []
        if not bool(self._config.get("input_chunking_enabled", True)):
            return [raw]
        soft_limit = max(4, int(self._config.get("input_chunk_soft_limit", 10) or 10))
        hard_limit = max(soft_limit, int(self._config.get("input_chunk_hard_limit", 30) or 30))
        chunks: list[str] = []
        remaining = raw
        punctuation_breaks = set("。！？!?；;，,、：:\n\r")
        while remaining:
            if len(remaining) <= hard_limit:
                chunks.append(remaining)
                break
            window = remaining[: hard_limit + 1]
            split_at = -1
            search_start = min(max(soft_limit - 1, 0), max(0, len(window) - 1))
            for idx in range(min(len(window) - 1, hard_limit), search_start - 1, -1):
                if window[idx] in punctuation_breaks:
                    split_at = idx
                    break
            if split_at >= 0:
                current = remaining[:split_at]
                if not str(current).strip():
                    current = remaining[:hard_limit]
                    remaining = remaining[hard_limit:]
                else:
                    remaining = remaining[split_at:]
            else:
                current = remaining[:hard_limit]
                remaining = remaining[hard_limit:]
            if str(current).strip():
                chunks.append(current)
        return [str(c).strip() for c in chunks if str(c).strip()]

    def _enqueue_external_text(self, text: str) -> list[str]:
        chunks = self._split_input_text_for_ticks(text)
        if chunks:
            self._current_external_source_text = str(text or "")
        self._pending_external_text_chunks.extend(chunks)
        return chunks

    def _push_single_tick_text(self, text: str) -> list[str]:
        raw = str(text or "").strip()
        if not raw:
            return []
        self._current_external_source_text = raw
        self._pending_external_text_chunks = [raw]
        return [raw]

    def _clear_external_input_queue(self) -> dict[str, Any]:
        cleared_count = int(len(self._pending_external_text_chunks))
        cleared_source_text = str(self._current_external_source_text or "")
        self._pending_external_text_chunks = []
        self._current_external_source_text = ""
        return {
            "cleared_pending_count": cleared_count,
            "cleared_source_text": cleared_source_text,
        }

    def _dequeue_external_text_for_tick(self) -> str | None:
        if not self._pending_external_text_chunks:
            self._current_external_source_text = ""
            return None
        chunk = self._pending_external_text_chunks.pop(0)
        if not self._pending_external_text_chunks:
            # Keep source text visible for the current tick; clear on next empty dequeue.
            pass
        return chunk

    def _decay_projection_fatigue(self) -> None:
        if bool(self._config.get("projection_fatigue_lazy_decay_enabled", True)):
            self._cleanup_projection_fatigue_if_needed()
            return
        decay = max(0.0, min(1.0, float(self._config.get("projection_fatigue_decay", 0.82) or 0.82)))
        next_state: dict[str, float] = {}
        for key, value in self._projection_fatigue.items():
            raw_value = value.get("value", 0.0) if isinstance(value, dict) else value
            v = max(0.0, float(raw_value) * decay)
            if v >= 1e-6:
                next_state[key] = v
        self._projection_fatigue = next_state

    def _projection_fatigue_decay_ratio(self) -> float:
        try:
            value = float(self._config.get("projection_fatigue_decay", 0.82) or 0.82)
        except Exception:
            value = 0.82
        return max(0.0, min(1.0, value))

    def _projection_fatigue_current_tick(self) -> int:
        try:
            return max(0, int(self.tick_counter))
        except Exception:
            return 0

    def _projection_fatigue_value(self, key: str) -> float:
        raw = self._projection_fatigue.get(key)
        if raw is None:
            return 0.0
        lazy_enabled = bool(self._config.get("projection_fatigue_lazy_decay_enabled", True))
        if not lazy_enabled:
            try:
                return max(0.0, float(raw.get("value", 0.0) if isinstance(raw, dict) else raw))
            except Exception:
                return 0.0
        if isinstance(raw, dict):
            value = max(0.0, float(raw.get("value", 0.0) or 0.0))
            last_tick = int(raw.get("tick", self._projection_fatigue_current_tick()) or 0)
        else:
            value = max(0.0, float(raw or 0.0))
            last_tick = self._projection_fatigue_current_tick()
        elapsed = max(0, self._projection_fatigue_current_tick() - int(last_tick))
        if elapsed > 0 and value > 0.0:
            value *= self._projection_fatigue_decay_ratio() ** elapsed
        if value < 1e-6:
            self._projection_fatigue.pop(key, None)
            return 0.0
        self._projection_fatigue[key] = {
            "value": round(float(value), 8),
            "tick": self._projection_fatigue_current_tick(),
        }
        return max(0.0, value)

    def _set_projection_fatigue_value(self, key: str, value: float) -> None:
        value = max(0.0, float(value or 0.0))
        if value < 1e-6:
            self._projection_fatigue.pop(key, None)
            return
        if bool(self._config.get("projection_fatigue_lazy_decay_enabled", True)):
            self._projection_fatigue[key] = {
                "value": round(float(value), 8),
                "tick": self._projection_fatigue_current_tick(),
            }
        else:
            self._projection_fatigue[key] = round(float(value), 8)

    def _cleanup_projection_fatigue_if_needed(self) -> None:
        if not self._projection_fatigue:
            return
        try:
            interval = int(self._config.get("projection_fatigue_cleanup_interval_ticks", 32) or 32)
        except Exception:
            interval = 32
        interval = max(1, interval)
        current_tick = self._projection_fatigue_current_tick()
        if current_tick - int(self._projection_fatigue_last_cleanup_tick or 0) < interval:
            return
        self._projection_fatigue_last_cleanup_tick = current_tick
        decay = self._projection_fatigue_decay_ratio()
        next_state: dict[str, Any] = {}
        for key, raw in list(self._projection_fatigue.items()):
            try:
                if isinstance(raw, dict):
                    value = max(0.0, float(raw.get("value", 0.0) or 0.0))
                    last_tick = int(raw.get("tick", current_tick) or current_tick)
                else:
                    value = max(0.0, float(raw or 0.0))
                    last_tick = current_tick
                elapsed = max(0, current_tick - last_tick)
                if elapsed > 0 and value > 0.0:
                    value *= decay ** elapsed
                if value >= 1e-6:
                    next_state[key] = {"value": round(float(value), 8), "tick": current_tick}
            except Exception:
                continue
        self._projection_fatigue = next_state

    def _projection_fatigue_key(self, item: dict) -> str:
        projection_kind = str(item.get("projection_kind", "structure") or "structure")
        memory_id = str(item.get("memory_id", "") or "")
        structure_id = str(item.get("structure_id", item.get("target_structure_id", "")) or "")
        backing_structure_id = str(item.get("backing_structure_id", "") or "")
        display_text = str(item.get("display_text", item.get("grouped_display_text", "")) or "").strip()
        reason = str(item.get("reason", "") or "")
        stable_ref = backing_structure_id or structure_id or display_text or memory_id
        return "|".join([projection_kind, stable_ref, reason])

    def _projection_min_effective_thresholds(self, item: dict) -> tuple[float, float]:
        projection_kind = str(item.get("projection_kind", "structure") or "structure")
        if projection_kind == "memory_feedback_structure_ref":
            min_er = max(
                0.0,
                float(
                    self._config.get(
                        "memory_feedback_structure_projection_min_effective_er",
                        self._config.get("projection_fatigue_min_effective_er", 0.03),
                    )
                    or 0.0
                ),
            )
            min_ev = max(
                0.0,
                float(
                    self._config.get(
                        "memory_feedback_structure_projection_min_effective_ev",
                        self._config.get("projection_fatigue_min_effective_ev", 0.03),
                    )
                    or 0.0
                ),
            )
            return min_er, min_ev
        min_er = max(0.0, float(self._config.get("projection_fatigue_min_effective_er", 0.03) or 0.03))
        min_ev = max(0.0, float(self._config.get("projection_fatigue_min_effective_ev", 0.03) or 0.03))
        return min_er, min_ev

    def _apply_projection_fatigue_to_item(self, item: dict) -> dict | None:
        if not bool(self._config.get("projection_fatigue_enabled", True)):
            return dict(item)
        key = self._projection_fatigue_key(item)
        fatigue = self._projection_fatigue_value(key)
        effective = dict(item)
        effective_er = max(0.0, float(item.get("er", 0.0) or 0.0)) / (1.0 + fatigue)
        effective_ev = max(0.0, float(item.get("ev", 0.0) or 0.0)) / (1.0 + fatigue)
        effective["er"] = round(float(effective_er), 8)
        effective["ev"] = round(float(effective_ev), 8)
        effective["projection_fatigue"] = round(float(fatigue), 8)
        min_er, min_ev = self._projection_min_effective_thresholds(item)
        if effective_er < min_er and effective_ev < min_ev:
            return None
        return effective

    def _mark_projection_fatigue(self, item: dict) -> None:
        if not bool(self._config.get("projection_fatigue_enabled", True)):
            return
        key = self._projection_fatigue_key(item)
        step = max(0.0, float(self._config.get("projection_fatigue_step", 0.28) or 0.28))
        self._set_projection_fatigue_value(key, self._projection_fatigue_value(key) + step)

    @staticmethod
    def _split_feedback_budget(total_value: float, ratio: float) -> tuple[float, float]:
        total = max(0.0, float(total_value or 0.0))
        share = max(0.0, min(1.0, float(ratio or 0.0)))
        direct = round(total * share, 8)
        retained = round(max(0.0, total - direct), 8)
        direct = round(max(0.0, total - retained), 8)
        return retained, direct

    def _get_live_pool_energy_summary(self) -> dict[str, float]:
        try:
            items = list(self.pool._store.get_all())
        except Exception:
            items = []
        total_er = 0.0
        total_ev = 0.0
        counted_items = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("ref_object_type", "") or "").strip() == "em":
                continue
            energy = item.get("energy", {}) if isinstance(item.get("energy", {}), dict) else {}
            total_er += max(0.0, float(energy.get("er", 0.0) or 0.0))
            total_ev += max(0.0, float(energy.get("ev", 0.0) or 0.0))
            counted_items += 1
        if total_er > 1e-8:
            ev_to_er_ratio = total_ev / total_er
        else:
            ev_to_er_ratio = 1.0 if total_ev <= 1e-8 else 999.0
        return {
            "item_count": float(counted_items),
            "total_er": round(total_er, 8),
            "total_ev": round(total_ev, 8),
            "ev_to_er_ratio": round(float(ev_to_er_ratio), 8),
        }

    def _cognitive_stitching_stage_mode(self) -> str:
        mode = str(self._config.get("cognitive_stitching_stage", "post_induction") or "post_induction").strip().lower()
        if mode not in {"pre_induction", "post_induction", "both", "disabled"}:
            mode = "post_induction"
        return mode

    def _run_cognitive_stitching_stage(
        self,
        *,
        stage: str,
        attention_snapshot: dict,
        privileged_ref_ids: list[str] | set[str] | tuple[str, ...] | None = None,
        trace_id: str,
        tick_id: str,
    ) -> tuple[dict[str, Any], int]:
        t0 = time.perf_counter()
        if not bool(self._config.get("enable_cognitive_stitching", False)):
            data: dict[str, Any] = {
                "enabled": False,
                "reason": "disabled_by_observatory",
                "stage": str(stage or ""),
            }
            return data, int((time.perf_counter() - t0) * 1000)
        try:
            cs_result = self.cognitive_stitching.run(
                pool=self.pool,
                hdb=self.hdb,
                attention_snapshot=attention_snapshot,
                privileged_ref_ids=privileged_ref_ids,
                trace_id=f"{trace_id}_cs_{stage}",
                tick_id=tick_id,
            )
            data = (cs_result.get("data", {}) or {}) if isinstance(cs_result, dict) else {}
            if not isinstance(data, dict):
                data = {}
            data = dict(data)
            data["observatory_stage"] = str(stage or "")
        except Exception as exc:
            data = {
                "enabled": bool(self._config.get("enable_cognitive_stitching", False)),
                "reason": "exception",
                "observatory_stage": str(stage or ""),
                "error": {"message": str(exc)},
            }
        return data, int((time.perf_counter() - t0) * 1000)

    def _clear_shadow_memory_runtime_items(self) -> dict[str, Any]:
        if not bool(self._config.get("residual_memory_as_structure_enabled", True)):
            return {"enabled": False, "shadow_mode": bool(self._config.get("residual_memory_as_structure_shadow_mode", False)), "removed_count": 0}
        if not bool(self._config.get("residual_memory_as_structure_shadow_mode", False)):
            return {"enabled": True, "shadow_mode": False, "removed_count": 0}
        try:
            items = list(self.pool._store.get_all())
        except Exception:
            items = []
        removed_count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            if not self._is_residual_memory_runtime_pool_item(item):
                continue
            item_id = str(item.get("id", "") or item.get("item_id", "") or "").strip()
            if not item_id:
                continue
            removed = self.pool._store.remove(item_id)
            if removed is not None:
                removed_count += 1
        return {"enabled": True, "shadow_mode": True, "removed_count": int(removed_count)}

    def _use_dedicated_memory_pool(self) -> bool:
        return bool(self._config.get("dedicated_memory_pool_enabled", False))

    def _memory_path_mode(self) -> str:
        return "dedicated_map" if self._use_dedicated_memory_pool() else "runtime_em_only"

    def _residual_memory_runtime_object_type(self) -> str:
        value = str(self._config.get("residual_memory_runtime_object_type", "em") or "em").strip().lower()
        return value if value in {"st", "em"} else "em"

    @staticmethod
    def _is_residual_memory_runtime_pool_item(item: dict | None) -> bool:
        if not isinstance(item, dict):
            return False
        ref_type = str(item.get("ref_object_type", "") or "").strip().lower()
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        meta_ext = (item.get("meta", {}) or {}).get("ext", {}) if isinstance((item.get("meta", {}) or {}).get("ext", {}), dict) else {}
        source_em_id = str(
            ref_snapshot.get("source_em_id", "")
            or meta_ext.get("source_em_id", "")
            or ref_snapshot.get("memory_id", "")
            or meta_ext.get("memory_id", "")
            or ""
        ).strip()
        residual_kind = str(ref_snapshot.get("residual_kind", "") or "").strip().lower()
        if ref_type == "em" and source_em_id:
            return True
        if str(meta_ext.get("residual_memory_as_structure", False)).lower() == "true" and source_em_id:
            return True
        return bool(source_em_id and residual_kind == "memory")

    def _build_memory_activation_maintenance_payload(self, *, trace_id: str, tick_id: str) -> dict[str, Any]:
        if self._use_dedicated_memory_pool():
            return self.hdb.tick_memory_activation_pool(trace_id=trace_id, tick_id=tick_id)["data"]
        return {
            "enabled": False,
            "mode": self._memory_path_mode(),
            "message": "专门记忆池主链已关闭；当前由 StatePool 内残差运行态对象承担活化链路。",
            "maintained_count": 0,
        }

    def _build_runtime_memory_apply_result_from_targets(
        self,
        *,
        targets: list[dict],
        trace_id: str,
        tick_id: str,
    ) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        items: list[dict[str, Any]] = []
        total_delta_er = 0.0
        total_delta_ev = 0.0
        for target in targets or []:
            if not isinstance(target, dict):
                continue
            if str(target.get("projection_kind", "memory") or "memory") != "memory":
                continue
            memory_id = str(target.get("memory_id", "") or "").strip()
            if not memory_id:
                continue
            episodic_obj = self.hdb._episodic_store.get(memory_id)
            if not isinstance(episodic_obj, dict):
                continue
            meta_ext = dict((episodic_obj.get("meta", {}) or {}).get("ext", {}) or {})
            memory_material = dict(meta_ext.get("memory_material", {}) or {})
            grouped_display_text = str(
                memory_material.get("grouped_display_text", "")
                or memory_material.get("semantic_grouped_display_text", "")
                or target.get("target_display_text", "")
                or target.get("display_text", "")
                or episodic_obj.get("event_summary", "")
                or memory_id
            )
            backing_structure_id = str(
                target.get("backing_structure_id", "")
                or target.get("target_structure_id", "")
                or target.get("structure_id", "")
                or ""
            ).strip()
            structure_refs = [str(x) for x in (episodic_obj.get("structure_refs", []) or []) if str(x)]
            if backing_structure_id:
                structure_refs = list(dict.fromkeys([backing_structure_id] + structure_refs))
            group_refs = [str(x) for x in (episodic_obj.get("group_refs", []) or []) if str(x)]
            delta_er = round(max(0.0, float(target.get("delta_er", target.get("er", 0.0)) or 0.0)), 8)
            delta_ev = round(max(0.0, float(target.get("delta_ev", target.get("ev", 0.0)) or 0.0)), 8)
            total_delta_er += delta_er
            total_delta_ev += delta_ev
            items.append(
                {
                    "memory_id": memory_id,
                    "display_text": grouped_display_text,
                    "grouped_display_text": grouped_display_text,
                    "semantic_grouped_display_text": grouped_display_text,
                    "memory_created_at": int(episodic_obj.get("created_at", 0) or 0),
                    "created_at": int(episodic_obj.get("created_at", 0) or 0),
                    "last_updated_at": now_ms,
                    "memory_tick_index": int((episodic_obj.get("meta", {}) or {}).get("tick_number", 0) or 0),
                    "structure_refs": list(structure_refs),
                    "group_refs": list(group_refs),
                    "structure_ref_items": self.hdb._resolve_structure_refs(structure_refs),
                    "group_ref_items": self.hdb._resolve_group_refs(group_refs),
                    "backing_structure_ids": list(structure_refs),
                    "last_delta_er": delta_er,
                    "last_delta_ev": delta_ev,
                    "er": delta_er,
                    "ev": delta_ev,
                    "total_er": delta_er,
                    "total_ev": delta_ev,
                    "total_energy": round(delta_er + delta_ev, 8),
                    "sources": list(target.get("sources", []) or []),
                    "modes": list(target.get("modes", []) or []),
                    "memory_kind": str(memory_material.get("memory_kind", "") or ""),
                    "runtime_only": True,
                    "path_mode": self._memory_path_mode(),
                    "trace_id": trace_id,
                    "tick_id": tick_id,
                }
            )
        return {
            "applied_count": len(items),
            "total_delta_er": round(total_delta_er, 8),
            "total_delta_ev": round(total_delta_ev, 8),
            "total_delta_energy": round(total_delta_er + total_delta_ev, 8),
            "items": items,
            "runtime_only": True,
            "path_mode": self._memory_path_mode(),
        }

    def _build_runtime_memory_snapshot_from_pool(
        self,
        *,
        trace_id: str,
        tick_id: str,
        limit: int = 24,
        sort_by: str = "energy_desc",
        source_items: list[dict] | None = None,
        projection_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            pool_items = list(self.pool._store.get_all())
        except Exception:
            pool_items = []
        pool_items = [item for item in pool_items if self._is_residual_memory_runtime_pool_item(item)]
        pool_by_item_id = {
            str(item.get("id", "") or ""): item
            for item in pool_items
            if isinstance(item, dict) and str(item.get("id", "") or "").strip()
        }
        projection_by_memory_id: dict[str, dict[str, Any]] = {}
        for row in list((projection_result or {}).get("items", []) or []):
            if not isinstance(row, dict):
                continue
            memory_id = str(row.get("memory_id", "") or row.get("source_em_id", "") or "").strip()
            if memory_id:
                projection_by_memory_id[memory_id] = row
        rows: list[dict[str, Any]] = []
        total_er = 0.0
        total_ev = 0.0
        source_rows = [row for row in (source_items or []) if isinstance(row, dict)]
        if source_rows:
            for source_row in source_rows:
                memory_id = str(source_row.get("memory_id", "") or "").strip()
                if not memory_id:
                    continue
                projection_row = projection_by_memory_id.get(memory_id, {})
                target_item_id = str(projection_row.get("target_item_id", "") or "").strip()
                pool_item = pool_by_item_id.get(target_item_id)
                pool_energy = (pool_item.get("energy", {}) or {}) if isinstance(pool_item, dict) else {}
                pool_snapshot = (pool_item.get("ref_snapshot", {}) or {}) if isinstance(pool_item, dict) else {}
                projection_ref_type = str(
                    (pool_item or {}).get("ref_object_type", "")
                    or projection_row.get("projected_ref_object_type", "")
                    or self._residual_memory_runtime_object_type()
                ).strip()
                delta_er = round(max(0.0, float(source_row.get("last_delta_er", 0.0) or 0.0)), 8)
                delta_ev = round(max(0.0, float(source_row.get("last_delta_ev", 0.0) or 0.0)), 8)
                display_text = str(
                    source_row.get("display_text", "")
                    or pool_snapshot.get("content_display", "")
                    or projection_row.get("display_text", "")
                    or memory_id
                )
                structure_refs = [str(x) for x in (source_row.get("structure_refs", []) or []) if str(x)]
                backing_structure_ids = [str(x) for x in (source_row.get("backing_structure_ids", []) or []) if str(x)]
                if backing_structure_ids:
                    structure_refs = list(dict.fromkeys(backing_structure_ids + structure_refs))
                elif projection_ref_type == "st" and isinstance(pool_item, dict):
                    pool_ref_id = str(pool_item.get("ref_object_id", "") or "").strip()
                    if pool_ref_id:
                        structure_refs = list(dict.fromkeys([pool_ref_id] + structure_refs))
                group_refs = [str(x) for x in (source_row.get("group_refs", []) or []) if str(x)]
                memory_created_at = int(source_row.get("memory_created_at", source_row.get("created_at", 0)) or 0)
                updated_at = int(source_row.get("last_updated_at", source_row.get("created_at", 0)) or 0)
                live_er = round(max(0.0, float(pool_energy.get("er", delta_er) or delta_er)), 8)
                live_ev = round(max(0.0, float(pool_energy.get("ev", delta_ev) or delta_ev)), 8)
                total_er += delta_er
                total_ev += delta_ev
                rows.append(
                    {
                        "memory_id": memory_id,
                        "item_id": target_item_id or str((pool_item or {}).get("id", "") or ""),
                        "display_text": display_text,
                        "grouped_display_text": str(source_row.get("grouped_display_text", "") or display_text),
                        "memory_created_at": memory_created_at,
                        "created_at": memory_created_at,
                        "last_updated_at": updated_at,
                        "structure_refs": list(structure_refs),
                        "group_refs": list(group_refs),
                        "structure_ref_items": self.hdb._resolve_structure_refs(structure_refs),
                        "group_ref_items": self.hdb._resolve_group_refs(group_refs),
                        "backing_structure_ids": list(structure_refs),
                        "last_delta_er": delta_er,
                        "last_delta_ev": delta_ev,
                        "er": delta_er,
                        "ev": delta_ev,
                        "total_er": delta_er,
                        "total_ev": delta_ev,
                        "total_energy": round(delta_er + delta_ev, 8),
                        "linked_live_er": live_er,
                        "linked_live_ev": live_ev,
                        "linked_live_total_energy": round(live_er + live_ev, 8),
                        "context_owner_id": str(
                            projection_row.get("context_owner_id", "")
                            or pool_snapshot.get("context_owner_id", "")
                            or ""
                        ),
                        "context_ref_object_id": str(
                            projection_row.get("context_ref_object_id", "")
                            or pool_snapshot.get("context_ref_object_id", "")
                            or ""
                        ),
                        "context_ref_object_type": str(
                            projection_row.get("context_ref_object_type", "")
                            or pool_snapshot.get("context_ref_object_type", "")
                            or ""
                        ),
                        "context_text": str(
                            projection_row.get("context_text", "")
                            or pool_snapshot.get("context_text", "")
                            or ""
                        ),
                        "source_em_id": str(
                            projection_row.get("source_em_id", "")
                            or pool_snapshot.get("source_em_id", "")
                            or memory_id
                        ),
                        "projection_ref_object_type": projection_ref_type,
                        "runtime_only": True,
                        "path_mode": self._memory_path_mode(),
                        "trace_id": trace_id,
                        "tick_id": tick_id,
                    }
                )
        else:
            for item in pool_items:
                if not isinstance(item, dict):
                    continue
                energy = item.get("energy", {}) if isinstance(item.get("energy", {}), dict) else {}
                er = max(0.0, float(energy.get("er", 0.0) or 0.0))
                ev = max(0.0, float(energy.get("ev", 0.0) or 0.0))
                total_er += er
                total_ev += ev
                ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
                memory_id = str(
                    ref_snapshot.get("memory_id", "")
                    or ref_snapshot.get("source_em_id", "")
                    or item.get("ref_object_id", "")
                    or ""
                ).strip()
                structure_refs = [str(x) for x in (ref_snapshot.get("structure_refs", []) or []) if str(x)]
                backing_structure_id = str(ref_snapshot.get("backing_structure_id", "") or "").strip()
                if backing_structure_id:
                    structure_refs = list(dict.fromkeys([backing_structure_id] + structure_refs))
                elif str(item.get("ref_object_type", "") or "").strip() == "st":
                    ref_object_id = str(item.get("ref_object_id", "") or "").strip()
                    if ref_object_id:
                        structure_refs = list(dict.fromkeys([ref_object_id] + structure_refs))
                group_refs = [str(x) for x in (ref_snapshot.get("group_refs", []) or []) if str(x)]
                created_at = int(
                    ref_snapshot.get("source_memory_created_at", 0)
                    or item.get("created_at", 0)
                    or 0
                )
                updated_at = int(item.get("updated_at", created_at) or created_at)
                rows.append(
                    {
                        "memory_id": memory_id,
                        "item_id": str(item.get("id", "") or ""),
                        "display_text": str(ref_snapshot.get("content_display", "") or memory_id),
                        "grouped_display_text": str(ref_snapshot.get("content_display", "") or memory_id),
                        "memory_created_at": created_at,
                        "created_at": created_at,
                        "last_updated_at": updated_at,
                        "structure_refs": list(structure_refs),
                        "group_refs": list(group_refs),
                        "structure_ref_items": self.hdb._resolve_structure_refs(structure_refs),
                        "group_ref_items": self.hdb._resolve_group_refs(group_refs),
                        "backing_structure_ids": list(structure_refs),
                        "last_delta_er": round(er, 8),
                        "last_delta_ev": round(ev, 8),
                        "er": round(er, 8),
                        "ev": round(ev, 8),
                        "total_er": round(er, 8),
                        "total_ev": round(ev, 8),
                        "total_energy": round(er + ev, 8),
                        "linked_live_er": round(er, 8),
                        "linked_live_ev": round(ev, 8),
                        "linked_live_total_energy": round(er + ev, 8),
                        "context_owner_id": str(ref_snapshot.get("context_owner_id", "") or ""),
                        "context_ref_object_id": str(ref_snapshot.get("context_ref_object_id", "") or ""),
                        "context_ref_object_type": str(ref_snapshot.get("context_ref_object_type", "") or ""),
                        "context_text": str(ref_snapshot.get("context_text", "") or ""),
                        "source_em_id": str(ref_snapshot.get("source_em_id", "") or memory_id),
                        "projection_ref_object_type": str(item.get("ref_object_type", "") or ""),
                        "runtime_only": True,
                        "path_mode": self._memory_path_mode(),
                        "trace_id": trace_id,
                        "tick_id": tick_id,
                    }
                )
        if str(sort_by or "").strip().lower() == "recent":
            rows.sort(key=lambda row: int(row.get("last_updated_at", row.get("created_at", 0)) or 0), reverse=True)
        else:
            rows.sort(
                key=lambda row: (
                    float(row.get("total_energy", 0.0) or 0.0),
                    int(row.get("last_updated_at", row.get("created_at", 0)) or 0),
                ),
                reverse=True,
            )
        limited = rows[: max(1, int(limit or 24))]
        return {
            "items": limited,
            "summary": {
                "count": len(rows),
                "returned_count": len(limited),
                "total_er": round(total_er, 8),
                "total_ev": round(total_ev, 8),
                "total_energy": round(total_er + total_ev, 8),
            },
            "runtime_only": True,
            "path_mode": self._memory_path_mode(),
        }

    def _build_runtime_memory_feedback_stub(
        self,
        *,
        memory_snapshot: dict[str, Any],
        trace_id: str,
        tick_id: str,
    ) -> dict[str, Any]:
        return {
            "enabled": False,
            "synthetic": True,
            "hidden_in_ui": True,
            "ui_visible": False,
            "path_mode": self._memory_path_mode(),
            "message": "MAP 兼容反馈主链默认关闭；默认残差运行态口径下不再把兼容 stub 当作真实主路径展示。",
            "applied_count": 0,
            "total_feedback_er": 0.0,
            "total_feedback_ev": 0.0,
            "total_feedback_energy": 0.0,
            "structure_projection_count": 0,
            "structure_projection_total_er": 0.0,
            "structure_projection_total_ev": 0.0,
            "projection_binding_stub_count": 0,
            "items": [],
            "record_result": {
                "recorded_count": 0,
                "total_feedback_er": 0.0,
                "total_feedback_ev": 0.0,
                "total_feedback_energy": 0.0,
                "items": [],
            },
            "trace_id": trace_id,
            "tick_id": tick_id,
        }

    def _resolve_memory_feedback_structure_projection_ratio(
        self,
        *,
        base_ratio: float,
        pool_energy_summary: dict[str, Any] | None = None,
    ) -> tuple[float, dict[str, Any]]:
        configured_ratio = max(0.0, min(0.95, float(base_ratio or 0.0)))
        adaptive_enabled = bool(
            self._config.get("memory_feedback_stimulus_packet_structure_projection_adaptive_enabled", True)
        )
        audit: dict[str, Any] = {
            "adaptive_enabled": adaptive_enabled,
            "configured_ratio": round(configured_ratio, 8),
        }
        if not adaptive_enabled:
            return configured_ratio, audit
        min_ratio = max(
            0.0,
            min(
                configured_ratio,
                float(
                    self._config.get(
                        "memory_feedback_stimulus_packet_structure_projection_adaptive_min_ratio",
                        0.20,
                    )
                    or 0.20
                ),
            ),
        )
        floor = max(
            0.0,
            float(
                self._config.get(
                    "memory_feedback_stimulus_packet_structure_projection_adaptive_ev_er_floor",
                    0.55,
                )
                or 0.55
            ),
        )
        ceiling = max(
            floor + 1e-6,
            float(
                self._config.get(
                    "memory_feedback_stimulus_packet_structure_projection_adaptive_ev_er_ceiling",
                    0.95,
                )
                or 0.95
            ),
        )
        if not isinstance(pool_energy_summary, dict):
            pool_energy_summary = self._get_live_pool_energy_summary()
        pool_ratio = float(pool_energy_summary.get("ev_to_er_ratio", 1.0) or 1.0)
        if pool_ratio <= floor:
            effective_ratio = min_ratio
        elif pool_ratio >= ceiling:
            effective_ratio = configured_ratio
        else:
            progress = (pool_ratio - floor) / max(1e-6, ceiling - floor)
            effective_ratio = min_ratio + (configured_ratio - min_ratio) * progress
        effective_ratio = max(0.0, min(0.95, float(effective_ratio)))
        audit.update(
            {
                "min_ratio": round(min_ratio, 8),
                "ev_to_er_floor": round(floor, 8),
                "ev_to_er_ceiling": round(ceiling, 8),
                "pool_ev_to_er_ratio_before_feedback": round(pool_ratio, 8),
                "effective_ratio": round(effective_ratio, 8),
            }
        )
        return effective_ratio, audit

    def next_trace(self, prefix: str = "cycle") -> str:
        self.tick_counter += 1
        return f"{prefix}_{self.tick_counter:04d}"

    def print_header(self) -> None:
        print(render_header())
        print(format_help())

    def run_cycle(
        self,
        text: str | None = None,
        *,
        labels: dict[str, Any] | None = None,
        now_ms_override: int | None = None,
    ) -> dict:
        pause_gc = bool(self._config.get("run_cycle_gc_pause_enabled", True))
        gc_was_enabled = False
        if pause_gc:
            try:
                gc_was_enabled = bool(gc.isenabled())
                if gc_was_enabled:
                    gc.disable()
            except Exception:
                gc_was_enabled = False
        try:
            return self._run_cycle_impl(
                text=text,
                labels=labels,
                now_ms_override=now_ms_override,
            )
        finally:
            if pause_gc and gc_was_enabled:
                try:
                    gc.enable()
                except Exception:
                    pass

    def _run_cycle_impl(
        self,
        text: str | None = None,
        *,
        labels: dict[str, Any] | None = None,
        now_ms_override: int | None = None,
    ) -> dict:
        trace_id = self.next_trace("cycle")
        tick_id = trace_id
        self._decay_projection_fatigue()
        self._clear_shadow_memory_runtime_items()
        # sanitized
        # sanitized
        # sanitized
        cycle_t0 = time.perf_counter()
        timing_steps_ms: dict[str, int] = {}
        try:
            effective_now_ms = int(now_ms_override) if now_ms_override is not None else int(time.time() * 1000)
        except Exception:
            effective_now_ms = int(time.time() * 1000)
        if effective_now_ms <= 0:
            effective_now_ms = int(time.time() * 1000)

        report: dict[str, Any] = {
            "trace_id": trace_id,
            # sanitized
            # sanitized
            "tick_id": tick_id,
            "started_at": int(effective_now_ms),
            "observatory": {
                "module": "observatory",
                "config": dict(self._config),
                "output_dir": str(self.output_dir),
                "runtime_clock": {
                    "now_ms": int(effective_now_ms),
                    "override_applied": bool(now_ms_override is not None),
                },
            },
        }

        # Optional per-tick labels (experiment/teacher signals).
        # sanitized
        # sanitized
        # sanitized
        tick_labels = labels if isinstance(labels, dict) else {}
        report["tick_labels"] = dict(tick_labels) if tick_labels else {}
        external_action_triggers = tick_labels.get("external_action_triggers", []) if isinstance(tick_labels, dict) else []
        if not isinstance(external_action_triggers, list):
            external_action_triggers = []

        external_packet = None
        sensor_result = None
        queued_chunks: list[str] = []
        submission_error: dict[str, Any] | None = None
        submission_integrity: dict[str, Any] | None = None
        submission_status = "empty"
        submitted_text = str(text or "") if text is not None else ""
        accepted_text = submitted_text
        pending_count_before_enqueue = int(len(self._pending_external_text_chunks))
        if text is not None and str(text).strip():
            preflight = self.sensor.preflight_input_text(
                str(text), trace_id=f"{trace_id}_preflight"
            )
            submission_integrity = (
                dict(preflight.get("integrity") or {})
                if isinstance(preflight.get("integrity"), dict)
                else None
            )
            if bool(preflight.get("success", False)):
                accepted_text = str(preflight.get("text") or "")
                submission_status = (
                    "repaired"
                    if (submission_integrity or {}).get("status") == "repaired"
                    else "accepted"
                )
                label_flags = tick_labels if isinstance(tick_labels, dict) else {}
                single_tick_input = bool(
                    label_flags.get("single_tick_input")
                    or label_flags.get("single_tick_text")
                    or label_flags.get("bypass_input_chunk_queue")
                )
                queued_chunks = (
                    self._push_single_tick_text(accepted_text)
                    if single_tick_input
                    else self._enqueue_external_text(accepted_text)
                )
            else:
                accepted_text = ""
                submission_status = "rejected"
                submission_error = (
                    dict(preflight.get("error") or {})
                    if isinstance(preflight.get("error"), dict)
                    else {
                        "code": "INPUT_TEXT_INTEGRITY_ERROR",
                        "message": "输入文本预检失败。",
                    }
                )
        pending_count_before_dequeue = int(len(self._pending_external_text_chunks))
        tick_text = self._dequeue_external_text_for_tick()
        report["input_queue"] = {
            "submitted_text": accepted_text,
            "submission_status": submission_status,
            "submission_integrity": submission_integrity or {},
            "submission_error": submission_error,
            "queued_from_new_input_count": len(queued_chunks),
            "pending_count_before_enqueue": pending_count_before_enqueue,
            "pending_count_before_dequeue": pending_count_before_dequeue,
            "pending_count_after_dequeue": len(self._pending_external_text_chunks),
            "tick_text": tick_text or "",
            "source_text": str(self._current_external_source_text or ""),
            "queued_preview": queued_chunks[:8],
        }
        if tick_text is not None:
            t0 = time.perf_counter()
            sensor_result = self.sensor.ingest_text(text=tick_text, trace_id=trace_id, tick_id=tick_id)
            # sanitized
            # sanitized
            # sanitized
            # sanitized
            try:
                if isinstance(sensor_result, dict) and bool(sensor_result.get("success", False)):
                    data = sensor_result.get("data", {}) if isinstance(sensor_result.get("data", {}), dict) else {}
                    if isinstance(data.get("stimulus_packet"), dict):
                        external_packet = copy.deepcopy(data.get("stimulus_packet"))
            except Exception:
                external_packet = None
            report["sensor"] = self._build_sensor_report(tick_text, sensor_result)
            timing_steps_ms["sensor_ms"] = int((time.perf_counter() - t0) * 1000)
        else:
            if submission_error:
                report["sensor"] = {
                    "success": False,
                    "code": submission_error.get(
                        "code", "INPUT_TEXT_INTEGRITY_ERROR"
                    ),
                    "message": submission_error.get(
                        "message", "输入文本预检失败。"
                    ),
                    "input_text": "",
                    "feature_sa_count": 0,
                    "attribute_sa_count": 0,
                    "csa_bundle_count": 0,
                    "echo_pool_size": int(getattr(self.sensor, "_echo_pool_size", 0) or 0) if getattr(self, "sensor", None) is not None else 0,
                    "echo_current_round": int(getattr(self.sensor, "_echo_current_round", 0) or 0) if getattr(self, "sensor", None) is not None else 0,
                    "error": submission_error,
                }
            else:
                report["sensor"] = {
                    "success": False,
                    "code": "INPUT_VALIDATION_ERROR",
                    "message": "当前 tick 没有可供文本感受器处理的输入。",
                    "input_text": "",
                    "feature_sa_count": 0,
                    "attribute_sa_count": 0,
                    "csa_bundle_count": 0,
                    "echo_pool_size": int(getattr(self.sensor, "_echo_pool_size", 0) or 0) if getattr(self, "sensor", None) is not None else 0,
                    "echo_current_round": int(getattr(self.sensor, "_echo_current_round", 0) or 0) if getattr(self, "sensor", None) is not None else 0,
                }
            timing_steps_ms["sensor_ms"] = 0

        t0 = time.perf_counter()
        report["maintenance"] = self._run_state_pool_maintenance(trace_id, tick_id)
        timing_steps_ms["maintenance_ms"] = int((time.perf_counter() - t0) * 1000)
        report["memory_activation"] = {
            "path_mode": self._memory_path_mode(),
            "dedicated_memory_pool_enabled": self._use_dedicated_memory_pool(),
            "maintenance": self._build_memory_activation_maintenance_payload(trace_id=trace_id, tick_id=tick_id),
            "apply_result": {
                "applied_count": 0,
                "total_delta_er": 0.0,
                "total_delta_ev": 0.0,
                "total_delta_energy": 0.0,
                "items": [],
            },
            "seed_targets": [],
            "feedback_result": {
                "applied_count": 0,
                "total_feedback_er": 0.0,
                "total_feedback_ev": 0.0,
                "total_feedback_energy": 0.0,
                "structure_projection_attempted_count": 0,
                "structure_projection_skipped_count": 0,
                "items": [],
                "record_result": {
                    "recorded_count": 0,
                    "total_feedback_er": 0.0,
                    "total_feedback_ev": 0.0,
                    "total_feedback_energy": 0.0,
                    "items": [],
                },
            },
            "snapshot": {
                "summary": {"count": 0, "total_er": 0.0, "total_ev": 0.0, "total_energy": 0.0, "top_total_energy": 0.0},
                "items": [],
                "sort_by": "energy_desc",
            },
        }
        cs_stage_mode = self._cognitive_stitching_stage_mode()
        cs_stage_results: dict[str, dict[str, Any]] = {}
        cs_timing_total_ms = 0

        # sanitized
        modulation_in = self._last_modulation.get("attention", {}) if isinstance(self._last_modulation, dict) else {}
        focus_directives_in: list[dict[str, Any]] = []
        for directive in self._pending_focus_directives:
            if not isinstance(directive, dict):
                continue
            ttl = int(directive.get("ttl_ticks", 0) or 0)
            if ttl > 0:
                focus_directives_in.append(directive)
        report["modulation_inputs"] = {
            "attention": dict(modulation_in) if isinstance(modulation_in, dict) else {},
            "focus_directives": [dict(item) for item in focus_directives_in[:16]],
        }

        # sanitized
        # sanitized
        hdb_mod_in = self._last_modulation.get("hdb", {}) if isinstance(self._last_modulation, dict) else {}
        hdb_mod_apply = self._apply_hdb_modulation_for_tick(
            modulation=hdb_mod_in if isinstance(hdb_mod_in, dict) else {},
            trace_id=trace_id,
            tick_id=tick_id,
        )
        report["modulation_inputs"]["hdb"] = dict(hdb_mod_in) if isinstance(hdb_mod_in, dict) else {}
        report["modulation_applied"] = {"hdb": hdb_mod_apply}

        t0 = time.perf_counter()
        attention_snapshot, attention_report = self._build_attention_memory_stub(
            trace_id,
            tick_id,
            focus_directives=focus_directives_in,
            modulation=modulation_in,
        )
        report["attention"] = attention_report
        timing_steps_ms["attention_ms"] = int((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        runtime_residual_promotion = self._promote_attention_runtime_residual_packages(
            attention_snapshot=attention_snapshot,
            trace_id=trace_id,
            tick_id=tick_id,
            now_ms=int(effective_now_ms),
        )
        report["runtime_residual_promotion"] = runtime_residual_promotion
        timing_steps_ms["runtime_residual_promotion_ms"] = int((time.perf_counter() - t0) * 1000)

        # sanitized
        decayed: list[dict[str, Any]] = []
        for directive in self._pending_focus_directives:
            if not isinstance(directive, dict):
                continue
            ttl = int(directive.get("ttl_ticks", 0) or 0)
            ttl -= 1
            if ttl <= 0:
                continue
            decayed.append({**directive, "ttl_ticks": ttl})
        self._pending_focus_directives = decayed

        t0 = time.perf_counter()
        structure_result = self.hdb.run_structure_level_retrieval_storage(
            state_snapshot=attention_snapshot,
            trace_id=trace_id,
            tick_id=tick_id,
            now_ms=int(effective_now_ms),
            # sanitized
            # sanitized
            attention_mode="cam_snapshot",
            top_n=max(
                1,
                sum(1 for it in (attention_snapshot.get("top_items", []) or []) if str(it.get("ref_object_type", "")) == "st"),
            ),
            enable_storage=bool(self._config.get("enable_structure_level_retrieval_storage", False)),
            max_rounds=(None if bool(self._config.get("enable_structure_level_retrieval_storage", False)) else 0),
        )
        structure_data = (structure_result.get("data", {}) or {}) if isinstance(structure_result, dict) else {}
        internal_fragments = list(structure_data.get("internal_stimulus_fragments", []) or [])
        if (not internal_fragments) and (not bool(self._config.get("enable_structure_level_retrieval_storage", False))):
            try:
                cam_only = self.hdb._structure_retrieval._run_cam_internal_stimulus_only(
                    items=list((attention_snapshot or {}).get("top_items", []) or []),
                    trace_id=trace_id,
                    tick_id=tick_id,
                    cut_engine=self.cut_engine,
                )
                if isinstance(cam_only, dict):
                    internal_fragments = list(cam_only.get("internal_stimulus_fragments", []) or [])
                    if internal_fragments:
                        structure_data["internal_stimulus_fragments"] = internal_fragments
                        structure_data["internal_resolution"] = dict(cam_only.get("internal_resolution", {}) or {})
                        structure_data.setdefault("debug", {})
                        if isinstance(structure_data.get("debug", {}), dict):
                            structure_data["debug"]["cam_internal_only"] = dict(cam_only.get("debug", {}) or {})
            except Exception as exc:
                structure_data.setdefault("debug", {})
                if isinstance(structure_data.get("debug", {}), dict):
                    structure_data["debug"]["cam_internal_only_error"] = str(exc)
        internal_packet = self.hdb.build_internal_stimulus_packet(
            internal_fragments,
            trace_id=trace_id,
            tick_id=tick_id,
        )
        combined_packet = self.hdb.merge_stimulus_packets(external_packet, internal_packet, trace_id=trace_id, tick_id=tick_id)
        report["structure_level"] = {"result": structure_data}
        report["internal_stimulus"] = self._describe_stimulus_packet(internal_packet)
        report["internal_stimulus_raw"] = internal_packet
        report["merged_stimulus_raw"] = combined_packet
        report["merged_stimulus"] = self._describe_stimulus_packet(combined_packet)
        timing_steps_ms["structure_level_ms"] = int((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        structure_bias_projection = self._project_runtime_structures(
            structure_data.get("bias_projections", []),
            trace_id=trace_id,
            tick_id=tick_id,
        )
        cache_neutralization = self._neutralize_packet_against_pool(combined_packet, trace_id, tick_id)
        residual_packet = cache_neutralization["residual_packet_raw"]
        report["cache_neutralization"] = {
            "input_packet": cache_neutralization["input_packet"],
            "residual_packet": cache_neutralization["residual_packet"],
            "priority_events": cache_neutralization["priority_events"],
            "priority_diagnostics": cache_neutralization.get("priority_diagnostics", []),
            "priority_summary": cache_neutralization["priority_summary"],
        }
        report["pool_apply"] = {
            "apply_result": {},
            "events": [],
            "priority_events": cache_neutralization["priority_events"],
            "priority_diagnostics": cache_neutralization.get("priority_diagnostics", []),
            "bias_projection": structure_bias_projection,
            "input_packet": cache_neutralization["input_packet"],
            "residual_packet": cache_neutralization["residual_packet"],
            "priority_summary": dict(cache_neutralization["priority_summary"]),
        }
        timing_steps_ms["cache_neutralization_ms"] = int((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        stimulus_result = self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=residual_packet,
            trace_id=trace_id,
            tick_id=tick_id,
            now_ms=int(effective_now_ms),
            metadata={"tick_number": int(self.tick_counter)},
        )
        stimulus_payload = stimulus_result.get("data", {}) if isinstance(stimulus_result, dict) else {}
        if isinstance(stimulus_payload, dict):
            stimulus_data = stimulus_payload
        else:
            stimulus_error = {}
            if isinstance(stimulus_result, dict) and isinstance(stimulus_result.get("error", {}), dict):
                stimulus_error = dict(stimulus_result.get("error", {}))
            stimulus_data = {
                "round_count": 0,
                "matched_structure_ids": [],
                "new_structure_ids": [],
                "runtime_projection_structures": [],
                "storage_summary": {"written_index_count": 0, "cut_count": 0},
                "residual_stimulus_packet": residual_packet,
                "debug": {
                    "runtime_error": {
                        "code": str((stimulus_result or {}).get("code", "")) if isinstance(stimulus_result, dict) else "",
                        "message": str(stimulus_error.get("message", "") or (stimulus_result or {}).get("message", "")) if isinstance(stimulus_result, dict) else "",
                        "interface": "run_stimulus_level_retrieval_storage",
                    }
                },
            }
        report["stimulus_level"] = {"result": stimulus_data}
        timing_steps_ms["stimulus_level_ms"] = int((time.perf_counter() - t0) * 1000)

        landing_packet = stimulus_data.get("residual_stimulus_packet", residual_packet)
        t0 = time.perf_counter()
        residual_tail_memory_projection = self._insert_residual_tail_memory_projection_to_pool(
            landing_packet,
            trace_id=trace_id,
            tick_id=tick_id,
            source_packet_id=str((landing_packet or {}).get("id", "") or ""),
            stimulus_data=stimulus_data,
        )
        runtime_residual_package: dict[str, Any] = {"applied": False, "reason": "superseded_by_memory_tail_projection"}
        if residual_tail_memory_projection.get("applied"):
            apply_result = {
                "residual_tail_memory_projection_applied": True,
                "residual_tail_memory_projection_handled": True,
                "residual_tail_memory_projection": dict(residual_tail_memory_projection.get("memory", {}) or {}),
            }
            apply_events = list(residual_tail_memory_projection.get("events", []) or [])
            landed_packet = {
                "id": "",
                "object_type": "stimulus_packet",
                "sa_items": [],
                "csa_items": [],
                "grouped_sa_sequences": [],
                "energy_summary": {"total_er": 0.0, "total_ev": 0.0},
            }
        elif residual_tail_memory_projection.get("handled"):
            apply_result = {
                "residual_tail_memory_projection_applied": False,
                "residual_tail_memory_projection_handled": True,
                "residual_tail_memory_projection_reason": str(residual_tail_memory_projection.get("reason", "") or ""),
                "residual_tail_memory_projection_memory_id": str(residual_tail_memory_projection.get("memory_id", "") or ""),
            }
            apply_events = []
            landed_packet = {
                "id": "",
                "object_type": "stimulus_packet",
                "sa_items": [],
                "csa_items": [],
                "grouped_sa_sequences": [],
                "energy_summary": {"total_er": 0.0, "total_ev": 0.0},
            }
        else:
            runtime_residual_package = self._insert_runtime_residual_package_to_pool(
                landing_packet,
                trace_id=trace_id,
                tick_id=tick_id,
                source_packet_id=str((landing_packet or {}).get("id", "") or ""),
            )
            if runtime_residual_package.get("applied"):
                apply_result = {
                    "runtime_residual_package_applied": True,
                    "runtime_residual_package": dict(runtime_residual_package.get("package", {}) or {}),
                    "residual_tail_memory_projection": dict(residual_tail_memory_projection or {}),
                }
                apply_events = list(runtime_residual_package.get("events", []) or [])
                landed_packet = {
                    "id": "",
                    "object_type": "stimulus_packet",
                    "sa_items": [],
                    "csa_items": [],
                    "grouped_sa_sequences": [],
                    "energy_summary": {"total_er": 0.0, "total_ev": 0.0},
                }
            else:
                apply_result, apply_events, landed_packet = self._apply_packet_to_pool(
                    landing_packet,
                    trace_id,
                    tick_id,
                    disable_priority_neutralization=True,
                )
        runtime_projection = self._project_runtime_structures(
            stimulus_data.get("runtime_projection_structures", []),
            trace_id=trace_id,
            tick_id=tick_id,
        )
        report["pool_apply"]["apply_result"] = apply_result
        report["pool_apply"]["events"] = apply_events
        report["pool_apply"]["landed_packet"] = self._describe_stimulus_packet(landed_packet)
        report["pool_apply"]["residual_tail_memory_projection"] = residual_tail_memory_projection
        report["pool_apply"]["runtime_residual_package"] = runtime_residual_package
        report["pool_apply"]["runtime_projection"] = runtime_projection
        timing_steps_ms["pool_apply_ms"] = int((time.perf_counter() - t0) * 1000)

        if cs_stage_mode in {"pre_induction", "both"}:
            cs_data, cs_elapsed_ms = self._run_cognitive_stitching_stage(
                stage="pre_induction",
                attention_snapshot=attention_snapshot,
                privileged_ref_ids=[],
                trace_id=trace_id,
                tick_id=tick_id,
            )
            cs_stage_results["pre_induction"] = cs_data
            cs_timing_total_ms += int(cs_elapsed_ms)

        t0 = time.perf_counter()
        phase_t0 = time.perf_counter()
        induction_snapshot = self._build_induction_source_snapshot(
            trace_id=f"{trace_id}_induction_snapshot",
            tick_id=tick_id,
        )
        timing_steps_ms["induction_source_snapshot_ms"] = int((time.perf_counter() - phase_t0) * 1000)
        phase_t0 = time.perf_counter()
        induction_result = self.hdb.run_induction_propagation(
            state_snapshot=induction_snapshot,
            trace_id=trace_id,
            tick_id=tick_id,
            max_source_items=int((induction_snapshot.get("summary", {}) or {}).get("induction_source_selected_count", 0) or 0),
        )
        timing_steps_ms["induction_hdb_propagation_ms"] = int((time.perf_counter() - phase_t0) * 1000)
        phase_t0 = time.perf_counter()
        induction_data = dict(induction_result["data"])
        induction_data["source_selection"] = dict((induction_snapshot.get("summary", {}) or {}))
        source_ev_events = self._apply_induction_source_consumptions(
            induction_data.get("source_ev_consumptions", []),
            trace_id,
            tick_id,
        )
        timing_steps_ms["induction_source_consumption_ms"] = int((time.perf_counter() - phase_t0) * 1000)
        raw_induction_targets = list(induction_data.get("induction_targets", []))
        phase_t0 = time.perf_counter()
        induction_targets, induction_projection_summary = self._prepare_induction_projection_targets(
            induction_data=induction_data,
            trace_id=trace_id,
            tick_id=tick_id,
        )
        induction_data["raw_induction_target_count"] = len(raw_induction_targets)
        induction_data["projection_mode"] = induction_projection_summary.get("mode", "residual")
        induction_data["growth_projection"] = induction_projection_summary
        timing_steps_ms["induction_projection_prepare_ms"] = int((time.perf_counter() - phase_t0) * 1000)
        structure_targets = [
            item for item in induction_targets if str(item.get("projection_kind", "structure")) != "memory"
        ]
        memory_targets = [
            item for item in raw_induction_targets if str(item.get("projection_kind", "structure")) == "memory"
        ]
        memory_seed_targets: list[dict[str, Any]] = []
        combined_memory_targets: list[dict[str, Any]] = []
        if self._use_dedicated_memory_pool():
            phase_t0 = time.perf_counter()
            memory_seed_targets = self._collect_memory_activation_seed_targets(report)
            combined_memory_targets = memory_targets + memory_seed_targets
            timing_steps_ms["memory_seed_collect_ms"] = int((time.perf_counter() - phase_t0) * 1000)
            phase_t0 = time.perf_counter()
            applied_targets = self._apply_induction_targets(structure_targets, trace_id, tick_id)
            timing_steps_ms["induction_target_apply_ms"] = int((time.perf_counter() - phase_t0) * 1000)
            phase_t0 = time.perf_counter()
            memory_apply_result = self.hdb.apply_memory_activation_targets(
                targets=combined_memory_targets,
                trace_id=trace_id,
                tick_id=tick_id,
            )["data"]
            timing_steps_ms["memory_activation_apply_ms"] = int((time.perf_counter() - phase_t0) * 1000)
            phase_t0 = time.perf_counter()
            memory_feedback_result = self._apply_memory_feedback(
                memory_items=memory_apply_result.get("items", []),
                trace_id=trace_id,
                tick_id=tick_id,
            )
            timing_steps_ms["memory_feedback_apply_ms"] = int((time.perf_counter() - phase_t0) * 1000)
            phase_t0 = time.perf_counter()
            memory_runtime_projection = self._project_memory_activation_runtime_items(
                memory_items=memory_apply_result.get("items", []),
                trace_id=trace_id,
                tick_id=tick_id,
            )
            timing_steps_ms["memory_runtime_projection_ms"] = int((time.perf_counter() - phase_t0) * 1000)
            phase_t0 = time.perf_counter()
            memory_snapshot = self.hdb.get_memory_activation_snapshot(
                trace_id=f"{trace_id}_memory_activation_snapshot",
                limit=24,
                sort_by="energy_desc",
            )["data"]
            timing_steps_ms["memory_activation_snapshot_ms"] = int((time.perf_counter() - phase_t0) * 1000)
        else:
            phase_t0 = time.perf_counter()
            memory_seed_targets = self._collect_memory_activation_seed_targets(report)
            combined_memory_targets = memory_targets + memory_seed_targets
            timing_steps_ms["memory_seed_collect_ms"] = int((time.perf_counter() - phase_t0) * 1000)
            phase_t0 = time.perf_counter()
            applied_targets = self._apply_induction_targets(induction_targets, trace_id, tick_id)
            timing_steps_ms["induction_target_apply_ms"] = int((time.perf_counter() - phase_t0) * 1000)
            phase_t0 = time.perf_counter()
            memory_apply_result = self._build_runtime_memory_apply_result_from_targets(
                targets=combined_memory_targets,
                trace_id=trace_id,
                tick_id=tick_id,
            )
            timing_steps_ms["memory_activation_apply_ms"] = int((time.perf_counter() - phase_t0) * 1000)
            phase_t0 = time.perf_counter()
            memory_runtime_projection = self._project_memory_activation_runtime_items(
                memory_items=memory_apply_result.get("items", []),
                trace_id=trace_id,
                tick_id=tick_id,
            )
            timing_steps_ms["memory_runtime_projection_ms"] = int((time.perf_counter() - phase_t0) * 1000)
            phase_t0 = time.perf_counter()
            memory_snapshot = self._build_runtime_memory_snapshot_from_pool(
                trace_id=f"{trace_id}_runtime_memory_snapshot",
                tick_id=tick_id,
                limit=24,
                sort_by="energy_desc",
                source_items=memory_apply_result.get("items", []),
                projection_result=memory_runtime_projection,
            )
            timing_steps_ms["memory_activation_snapshot_ms"] = int((time.perf_counter() - phase_t0) * 1000)
            phase_t0 = time.perf_counter()
            memory_feedback_result = self._build_runtime_memory_feedback_stub(
                memory_snapshot=memory_snapshot,
                trace_id=trace_id,
                tick_id=tick_id,
            )
            timing_steps_ms["memory_feedback_apply_ms"] = int((time.perf_counter() - phase_t0) * 1000)
        if isinstance(induction_projection_summary, dict):
            induction_projection_summary["target_apply_fast_ref_hit_merge_count"] = len(
                [
                    row for row in list(applied_targets or [])
                    if isinstance(row, dict) and bool(row.get("fast_ref_hit_merge", False))
                ]
            )
            induction_projection_summary["target_apply_insert_log_suppressed_count"] = len(
                [
                    row for row in list(applied_targets or [])
                    if isinstance(row, dict) and bool(row.get("insert_log_suppressed", False))
                ]
            )
            induction_projection_summary["target_apply_insert_log_enabled"] = bool(
                self._config.get("induction_target_runtime_insert_log_enabled", False)
            )
            induction_projection_summary["target_apply_ref_fast_merge_enabled"] = bool(
                self._config.get("induction_target_runtime_ref_fast_merge_enabled", True)
            )
        report["induction"] = {
            "result": induction_data,
            "source_selection": dict(induction_data.get("source_selection", {}) or {}),
            "source_ev_events": source_ev_events,
            "applied_targets": applied_targets,
            "structure_target_count": len(structure_targets),
            "memory_target_count": len(memory_targets),
            "memory_seed_target_count": len(memory_seed_targets),
            "memory_target_total_count": len(combined_memory_targets),
        }
        report["memory_activation"]["apply_result"] = memory_apply_result
        report["memory_activation"]["seed_targets"] = memory_seed_targets
        report["memory_activation"]["feedback_result"] = memory_feedback_result
        report["memory_activation"]["runtime_projection"] = memory_runtime_projection
        report["memory_activation"]["snapshot"] = memory_snapshot
        report["memory_feedback"] = memory_feedback_result
        report["memory_runtime_projection"] = memory_runtime_projection
        timing_steps_ms["induction_and_memory_ms"] = int((time.perf_counter() - t0) * 1000)

        if cs_stage_mode in {"post_induction", "both"}:
            post_induction_privileged_refs = self._collect_post_induction_cs_privileged_refs(
                induction_snapshot=induction_snapshot,
                applied_targets=applied_targets,
                induction_targets=induction_targets,
            )
            cs_data, cs_elapsed_ms = self._run_cognitive_stitching_stage(
                stage="post_induction",
                attention_snapshot=attention_snapshot,
                privileged_ref_ids=post_induction_privileged_refs,
                trace_id=trace_id,
                tick_id=tick_id,
            )
            cs_stage_results["post_induction"] = cs_data
            cs_timing_total_ms += int(cs_elapsed_ms)
        if cs_stage_results:
            selected_stage = "post_induction" if "post_induction" in cs_stage_results else "pre_induction"
            cs_data = dict(cs_stage_results.get(selected_stage, {}) or {})
            cs_data["stage_mode"] = cs_stage_mode
            cs_data["selected_stage"] = selected_stage
            cs_data["stage_results"] = cs_stage_results
        else:
            cs_data = {
                "enabled": bool(self._config.get("enable_cognitive_stitching", False)),
                "reason": "stage_disabled",
                "stage_mode": cs_stage_mode,
                "selected_stage": "",
                "stage_results": {},
            }
        report["cognitive_stitching"] = cs_data
        timing_steps_ms["cognitive_stitching_ms"] = int(cs_timing_total_ms)
        timing_steps_ms["event_grasp_ms"] = int((((cs_data.get("event_grasp", {}) or {}).get("elapsed_ms", 0)) or 0))

        # =============================================================== #
        # sanitized
        # =============================================================== #
        # sanitized
        # sanitized
        # sanitized
        # sanitized
        # sanitized
        t0 = time.perf_counter()
        try:
            ts_res = self.time_sensor.run_time_feeling_tick(
                pool=self.pool,
                hdb=self.hdb,
                trace_id=trace_id,
                tick_id=tick_id,
                now_ms=int(report.get("started_at", 0) or 0) or None,
                memory_activation_snapshot=memory_snapshot,
                memory_feedback_result=memory_feedback_result,
                source_mode="memory_activation_snapshot" if self._use_dedicated_memory_pool() else "runtime_memory_projection",
            )
            report["time_sensor"] = ts_res.get("data", {}) if isinstance(ts_res, dict) else {}
        except Exception as exc:
            report["time_sensor"] = {"error": str(exc)}
        timing_steps_ms["time_sensor_ms"] = int((time.perf_counter() - t0) * 1000)

        # =============================================================== #
        # sanitized
        # =============================================================== #
        # sanitized
        # sanitized
        # sanitized
        # sanitized
        t0 = time.perf_counter()
        try:
            report["teacher_feedback"] = self._apply_teacher_feedback(
                labels=tick_labels,
                report=report,
                trace_id=trace_id,
                tick_id=tick_id,
            )
        except Exception as exc:
            report["teacher_feedback"] = {"ok": False, "code": "EXCEPTION", "message": f"teacher_feedback failed: {exc}"}
        teacher_focus_directives = list((report.get("teacher_feedback", {}) or {}).get("focus_directives", []) or [])
        if teacher_focus_directives:
            self._append_focus_directives(teacher_focus_directives)
        timing_steps_ms["teacher_feedback_ms"] = int((time.perf_counter() - t0) * 1000)

        # =============================================================== #
        # sanitized
        # =============================================================== #
        # sanitized
        # sanitized
        # sanitized
        #
        # sanitized
        # sanitized
        # sanitized

        cfs_source_mode = str(self._config.get("cfs_source_mode", "iesm") or "iesm").strip().lower() or "iesm"
        t0 = time.perf_counter()
        cfs_data: dict[str, Any] = {}
        cfs_signals: list[dict[str, Any]] = []

        if cfs_source_mode in {"legacy", "module", "cfs"}:
            # Legacy CFS module path (transition / comparison only).
            # sanitized
            cfs_snapshot = self.pool.get_state_snapshot(
                trace_id=f"{trace_id}_cfs_snapshot",
                tick_id=tick_id,
                top_k=int(self._config.get("snapshot_top_k", 24)),
            )["data"]["snapshot"]
            cfs_result = self.cfs.run_cfs(
                pool=self.pool,
                state_snapshot=cfs_snapshot,
                cam_snapshot=attention_snapshot,
                attention_report=report.get("attention", {}),
                trace_id=trace_id,
                tick_id=tick_id,
                context={
                    "structure_level": report.get("structure_level", {}).get("result", {}),
                    "stimulus_level": report.get("stimulus_level", {}).get("result", {}),
                    "induction": report.get("induction", {}).get("result", {}),
                    "cache_neutralization": report.get("cache_neutralization", {}),
                },
            )
            cfs_data = cfs_result.get("data", {}) or {}
            report["cognitive_feeling"] = cfs_data
            cfs_signals = list(cfs_data.get("cfs_signals", []) or [])
        else:
            # Preferred path: IESM rules generate CFS signals.
            # sanitized
            cfs_data = {
                "cfs_signals": [],
                "writes": {"runtime_nodes": [], "attribute_bindings": []},
                "meta": {"tick_number": int(self.tick_counter), "source_mode": "iesm_rules"},
            }
            report["cognitive_feeling"] = cfs_data
            cfs_signals = []

        timing_steps_ms["cfs_ms"] = int((time.perf_counter() - t0) * 1000)
        t_iesm0 = time.perf_counter()

        innate_script_report: dict[str, Any] = {
            "active_scripts": self.iesm.get_active_scripts(trace_id=f"{trace_id}_iesm_scripts").get("data", {}),
            "state_window_checks": [],
            "focus": {},
        }
        maint_packet: dict[str, Any] = {}
        apply_packet: dict[str, Any] = {}
        try:
            # sanitized
            maint_packet = self.pool._snapshot.build_script_check_packet(
                events=report.get("maintenance", {}).get("events", []),
                pool_store=self.pool._store,
                trace_id=f"{trace_id}_iesm_maint",
                tick_id=tick_id,
            )
            if bool(self._config.get("iesm_lightweight_state_window_checks", True)):
                maint_check = self._build_lightweight_iesm_state_window_check(
                    maint_packet,
                    stage="maintenance",
                )
            else:
                maint_check = self.iesm.check_state_window(maint_packet, trace_id=trace_id).get("data", {})
            innate_script_report["state_window_checks"].append(
                {"stage": "maintenance", "packet_summary": maint_packet.get("summary", {}), "check": maint_check}
            )
        except Exception:
            innate_script_report["state_window_checks"].append({"stage": "maintenance", "error": "packet_build_failed"})

        try:
            # sanitized
            apply_events = report.get("pool_apply", {}).get("events", [])
            apply_packet = self.pool._snapshot.build_script_check_packet(
                events=apply_events,
                pool_store=self.pool._store,
                trace_id=f"{trace_id}_iesm_apply",
                tick_id=tick_id,
            )
            if bool(self._config.get("iesm_lightweight_state_window_checks", True)):
                apply_check = self._build_lightweight_iesm_state_window_check(
                    apply_packet,
                    stage="pool_apply",
                )
            else:
                apply_check = self.iesm.check_state_window(apply_packet, trace_id=trace_id).get("data", {})
            innate_script_report["state_window_checks"].append(
                {"stage": "pool_apply", "packet_summary": apply_packet.get("summary", {}), "check": apply_check}
            )
        except Exception:
            innate_script_report["state_window_checks"].append({"stage": "pool_apply", "error": "packet_build_failed"})

        # sanitized
        # Build runtime context for IESM metric predicates.
        innate_rules_context = self._build_innate_rules_context(
            report=report,
            pool_snapshot=None,  # use live StatePool store
            emotion_state=None,  # IESM runs before EMgr update; use current snapshot + CFS-derived rwd/pun
            cfs_signals=cfs_signals,
            trace_id=trace_id,
            tick_id=tick_id,
        )

        def _merge_emotion_update_maps(*maps: dict[str, Any] | None) -> dict[str, float]:
            merged: dict[str, float] = {}
            for mapping in maps:
                if not isinstance(mapping, dict):
                    continue
                for raw_key, raw_value in mapping.items():
                    key = str(raw_key or "").strip()
                    if not key:
                        continue
                    try:
                        delta = float(raw_value or 0.0)
                    except Exception:
                        continue
                    merged[key] = round(float(merged.get(key, 0.0)) + float(delta), 8)
            return merged

        # sanitized
        tick_rules_result = self.iesm.run_tick_rules(
            trace_id=trace_id,
            tick_id=tick_id,
            tick_index=int(self.tick_counter),
            cfs_signals=cfs_signals,
            state_windows=[
                {"stage": "maintenance", "packet": maint_packet},
                {"stage": "pool_apply", "packet": apply_packet},
            ],
            context=innate_rules_context,
            dry_run=False,
            allowed_phases=["cfs", "directives"],
        )
        tick_rules_data = tick_rules_result.get("data", {}) or {}
        directives = tick_rules_data.get("directives", {}) or {}

        # If CFS is sourced from IESM rules, treat directives.cfs_signals as canonical.
        # sanitized
        # sanitized
        if cfs_source_mode not in {"legacy", "module", "cfs"}:
            cfs_signals = list(directives.get("cfs_signals", []) or [])
            report["cognitive_feeling"] = {
                "cfs_signals": cfs_signals,
                "writes": {"runtime_nodes": [], "attribute_bindings": []},
                "meta": {"tick_number": int(self.tick_counter), "source_mode": "iesm_rules"},
            }
        pool_effects = list(directives.get("pool_effects", []) or [])
        pool_effect_apply = {}
        if pool_effects:
            # Apply pool effects immediately so the same tick can affect later steps/snapshots.
            # sanitized
            pool_effect_apply = self._apply_innate_pool_effects(
                effects=pool_effects,
                context=innate_rules_context,
                trace_id=trace_id,
                tick_id=tick_id,
            )
        pool_effect_mutated = int((pool_effect_apply.get("applied_count", 0) or 0)) > 0 if isinstance(pool_effect_apply, dict) else False

        # Enrich episodic memory material with runtime-bound attributes (CFS/time-feeling/rwd/pun tags).
        # sanitized
        # sanitized
        try:
            enrich_res = self._enrich_tick_episodic_memory_with_bound_attributes(report=report, trace_id=trace_id, tick_id=tick_id)
        except Exception as exc:
            enrich_res = {"ok": False, "code": "EXCEPTION", "message": f"enrich episodic memory failed: {exc}"}
        try:
            stim_res = (report.get("stimulus_level", {}) or {}).get("result", {})
            if isinstance(stim_res, dict):
                stim_res["episodic_memory_enrichment"] = enrich_res
        except Exception:
            pass
        focus_data = {
            # sanitized
            # Note: This is the rule-engine output list, not necessarily the legacy CFS module output.
            "cfs_signals": list(directives.get("cfs_signals", []) or []),
            "focus_directives": list(directives.get("focus_directives", []) or []),
            "emotion_updates": dict(directives.get("emotion_updates", {}) or {}),
            "action_triggers": list(directives.get("action_triggers", []) or []),
            "pool_effects": pool_effects,
            "pool_effect_apply": pool_effect_apply,
            "episodic_memory_enrichment": enrich_res,
            "audit": tick_rules_data.get("audit", {}) or {},
            "triggered_rules": list(tick_rules_data.get("triggered_rules", []) or []),
            "triggered_scripts": list(tick_rules_data.get("triggered_scripts", []) or []),
        }

        # =============================================================== #
        # sanitized
        # =============================================================== #
        # sanitized
        # Compute rwd/pun override from the *current* pool (after IESM/time-sensor binding).
        # sanitized
        # sanitized
        rwd_pun_override = None
        local_reward_punish_map = {}
        post_pool_items_for_context: list[dict[str, Any]] = []
        try:
            rows: list[dict[str, Any]] = []
            if isinstance(innate_rules_context.get("pool_items", []), list):
                for row in innate_rules_context.get("pool_items", []) or []:
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("item_id", "") or "") == "ctx_input_current":
                        continue
                    rows.append(dict(row))
            if pool_effect_mutated and rows and bool(self._config.get("iesm_post_pool_context_delta_refresh_enabled", True)):
                mutated_item_ids: list[str] = []
                for applied_row in list(pool_effect_apply.get("applied", []) or []) if isinstance(pool_effect_apply, dict) else []:
                    if not isinstance(applied_row, dict):
                        continue
                    for key in ("target_item_id", "item_id"):
                        text = str(applied_row.get(key, "") or "")
                        if text and text not in mutated_item_ids:
                            mutated_item_ids.append(text)
                    data = applied_row.get("data", {}) if isinstance(applied_row.get("data", {}), dict) else {}
                    for key in ("target_item_id", "item_id"):
                        text = str(data.get(key, "") or "")
                        if text and text not in mutated_item_ids:
                            mutated_item_ids.append(text)
                if mutated_item_ids:
                    row_index = {
                        str(row.get("item_id", "") or ""): idx
                        for idx, row in enumerate(rows)
                        if isinstance(row, dict) and str(row.get("item_id", "") or "")
                    }
                    for item_id in mutated_item_ids:
                        item = self.pool._store.get(item_id)  # type: ignore[attr-defined]
                        if not isinstance(item, dict):
                            continue
                        refreshed = self._build_runtime_pool_item_summary_fast(item, include_sequence_payload=False)
                        if not isinstance(refreshed, dict):
                            continue
                        if item_id in row_index:
                            rows[row_index[item_id]] = refreshed
                        else:
                            row_index[item_id] = len(rows)
                            rows.append(refreshed)
                else:
                    rows = []
            elif pool_effect_mutated:
                rows = []
            if not rows:
                for item in list(self.pool._store.get_all()):  # type: ignore[attr-defined]
                    if not isinstance(item, dict):
                        continue
                    row = self._build_runtime_pool_item_summary_fast(item, include_sequence_payload=False)
                    if isinstance(row, dict):
                        rows.append(row)
            post_pool_items_for_context = [dict(row) for row in rows if isinstance(row, dict)]
            rwd_pun_override = self._estimate_rwd_pun_from_pool_items(rows, trace_id=trace_id, tick_id=tick_id)
            local_reward_punish_map = self._build_local_rwd_pun_map_from_pool_items(rows, trace_id=trace_id, tick_id=tick_id)
            local_reward_punish_map = self._overlay_teacher_feedback_local_rwd_pun_map(
                local_reward_punish_map,
                teacher_feedback=report.get("teacher_feedback", {}) if isinstance(report.get("teacher_feedback", {}), dict) else {},
            )
            report["teacher_local_feedback_alias_cache"] = self._overlay_teacher_local_feedback_alias_cache(
                local_reward_punish_map,
                report=report,
                current_tick=int(self.tick_counter),
                tick_id=tick_id,
            )
        except Exception:
            rwd_pun_override = None
            local_reward_punish_map = {}
            report["teacher_local_feedback_alias_cache"] = {
                "enabled": bool(self._config.get("teacher_feedback_local_alias_cache_enabled", True)),
                "overlay_applied_count": 0,
                "error": "local_map_build_failed",
            }

        # External teacher reward/punish can add on top of pool aggregation.
        # sanitized
        try:
            tfb = report.get("teacher_feedback", {}) if isinstance(report.get("teacher_feedback", {}), dict) else {}
            teacher_rwd = float(tfb.get("teacher_rwd", 0.0) or 0.0)
            teacher_pun = float(tfb.get("teacher_pun", 0.0) or 0.0)
            if teacher_rwd > 0.0 or teacher_pun > 0.0:
                base = dict(rwd_pun_override or {})
                base_rwd = float(base.get("rwd", 0.0) or 0.0)
                base_pun = float(base.get("pun", 0.0) or 0.0)
                merged_rwd = self._clamp01(base_rwd + max(0.0, teacher_rwd))
                merged_pun = self._clamp01(base_pun + max(0.0, teacher_pun))
                detail = dict(base.get("detail", {}) or {}) if isinstance(base.get("detail", {}), dict) else {}
                detail.update(
                    {
                        "teacher_rwd": round(float(max(0.0, teacher_rwd)), 8),
                        "teacher_pun": round(float(max(0.0, teacher_pun)), 8),
                        "teacher_mode": str(tfb.get("mode", "") or ""),
                        "teacher_anchor": str(tfb.get("anchor", "") or ""),
                    }
                )
                rwd_pun_override = {
                    **base,
                    "rwd": round(float(merged_rwd), 8),
                    "pun": round(float(merged_pun), 8),
                    "source": f"{str(base.get('source', '') or 'pool_items')}+teacher",
                    "detail": detail,
                }
        except Exception:
            pass
        post_tick_rules_result: dict[str, Any] = {}
        post_tick_rules_data: dict[str, Any] = {}
        post_directives: dict[str, Any] = {}
        post_tick_rules_error = ""
        try:
            emotion_context_override = {
                "rwd_pun_snapshot": dict(rwd_pun_override or {}),
                "rwd_pun_source": str((rwd_pun_override or {}).get("source", "") or ""),
                "rwd_pun_detail": dict((rwd_pun_override or {}).get("detail", {}) or {})
                if isinstance((rwd_pun_override or {}).get("detail", {}), dict)
                else {},
            }
            if bool(self._config.get("iesm_emotion_post_reuse_context_enabled", True)):
                post_innate_rules_context = dict(innate_rules_context)
                if post_pool_items_for_context:
                    post_innate_rules_context["pool_items"] = [dict(row) for row in post_pool_items_for_context if isinstance(row, dict)]
                base_emotion = dict(post_innate_rules_context.get("emotion", {}) or {})
                override_snapshot = dict(rwd_pun_override or {})
                base_emotion.update(
                    {
                        "rwd": float(override_snapshot.get("rwd", 0.0) or 0.0),
                        "pun": float(override_snapshot.get("pun", 0.0) or 0.0),
                        "rwd_pun_source": str(
                            emotion_context_override.get("rwd_pun_source", "")
                            or override_snapshot.get("source", "")
                            or "state_override"
                        ),
                        "rwd_pun_detail": dict(emotion_context_override.get("rwd_pun_detail", {}) or {}),
                    }
                )
                post_innate_rules_context["emotion"] = base_emotion
                post_innate_rules_context["meta"] = {
                    **dict(post_innate_rules_context.get("meta", {}) or {}),
                    "emotion_post_context_reused": True,
                    "built_at_ms": int(time.time() * 1000),
                }
            else:
                post_innate_rules_context = self._build_innate_rules_context(
                    report=report,
                    pool_snapshot={"top_items": post_pool_items_for_context} if post_pool_items_for_context else None,
                    emotion_state=emotion_context_override,
                    cfs_signals=cfs_signals,
                    trace_id=trace_id,
                    tick_id=tick_id,
                )
            post_tick_rules_result = self.iesm.run_tick_rules(
                trace_id=trace_id,
                tick_id=tick_id,
                tick_index=int(self.tick_counter),
                cfs_signals=cfs_signals,
                state_windows=[
                    {"stage": "maintenance", "packet": maint_packet},
                    {"stage": "pool_apply", "packet": apply_packet},
                ],
                context=post_innate_rules_context,
                dry_run=False,
                allowed_phases=["emotion_post"],
            )
            post_tick_rules_data = post_tick_rules_result.get("data", {}) or {}
            post_directives = post_tick_rules_data.get("directives", {}) or {}
        except Exception as exc:
            post_tick_rules_error = str(exc)

        post_emotion_updates = dict(post_directives.get("emotion_updates", {}) or {})
        if post_emotion_updates:
            focus_data["emotion_updates"] = _merge_emotion_update_maps(
                focus_data.get("emotion_updates", {}),
                post_emotion_updates,
            )
        post_focus_directives = list(post_directives.get("focus_directives", []) or [])
        if post_focus_directives:
            focus_data["focus_directives"] = list(focus_data.get("focus_directives", []) or []) + post_focus_directives
        post_action_triggers = list(post_directives.get("action_triggers", []) or [])
        if post_action_triggers:
            focus_data["action_triggers"] = list(focus_data.get("action_triggers", []) or []) + post_action_triggers
        post_triggered_rules = list(post_tick_rules_data.get("triggered_rules", []) or [])
        if post_triggered_rules:
            focus_data["triggered_rules"] = list(focus_data.get("triggered_rules", []) or []) + post_triggered_rules
        post_triggered_scripts = list(post_tick_rules_data.get("triggered_scripts", []) or [])
        if post_triggered_scripts:
            focus_data["triggered_scripts"] = list(focus_data.get("triggered_scripts", []) or []) + post_triggered_scripts

        innate_script_report["focus"] = focus_data
        innate_script_report["tick_rules"] = {
            "code": tick_rules_result.get("code", ""),
            "triggered_rule_count": len(focus_data.get("triggered_rules", []) or []),
            "focus_directive_count": len(focus_data.get("focus_directives", []) or []),
            "emotion_update_key_count": len((focus_data.get("emotion_updates") or {}).keys()),
            "action_trigger_count": len(focus_data.get("action_triggers", []) or []),
            "pool_effect_count": len(focus_data.get("pool_effects", []) or []),
            "audit": tick_rules_data.get("audit", {}) if isinstance(tick_rules_data.get("audit", {}), dict) else {},
        }
        innate_script_report["emotion_post_tick_rules"] = {
            "code": post_tick_rules_result.get("code", "") if isinstance(post_tick_rules_result, dict) else "",
            "error": post_tick_rules_error,
            "triggered_rule_count": len(post_triggered_rules),
            "focus_directive_count": len(post_focus_directives),
            "emotion_update_key_count": len(post_emotion_updates.keys()),
            "action_trigger_count": len(post_action_triggers),
            "pool_effect_count": len(list(post_directives.get("pool_effects", []) or [])),
            "audit": post_tick_rules_data.get("audit", {}) if isinstance(post_tick_rules_data.get("audit", {}), dict) else {},
            "triggered_rules": post_triggered_rules,
        }
        new_directives = list(focus_data.get("focus_directives", []) or [])
        new_action_triggers = list(focus_data.get("action_triggers", []) or [])
        if external_action_triggers:
            new_action_triggers = new_action_triggers + [dict(item) for item in external_action_triggers if isinstance(item, dict)]
        if new_directives:
            # sanitized
            # sanitized
            # sanitized
            action_enabled = bool(getattr(self, "action", None) and getattr(self.action, "_config", {}).get("enabled", True))
            if not action_enabled:
                self._append_focus_directives(new_directives)

        report["innate_script"] = innate_script_report
        timing_steps_ms["iesm_ms"] = int((time.perf_counter() - t_iesm0) * 1000)
        t0 = time.perf_counter()
        emotion_result = self.emotion.update_emotion_state(
            {
                "cfs_signals": cfs_signals,
                "tick_id": tick_id,
                "emotion_updates": focus_data.get("emotion_updates", {}),
                "rwd_pun_override": rwd_pun_override or {},
            },
            trace_id=trace_id,
            tick_id=tick_id,
        )
        emotion_data = emotion_result.get("data", {}) or {}
        report["emotion"] = emotion_data
        timing_steps_ms["emotion_ms"] = int((time.perf_counter() - t0) * 1000)
        # sanitized
        # sanitized
        next_modulation: dict[str, Any] = dict(emotion_data.get("modulation", {}) or {})

        # =============================================================== #
        # sanitized
        # =============================================================== #

        # sanitized
        # sanitized
        # sanitized
        # sanitized
        # sanitized
        t0 = time.perf_counter()
        action_result = self.action.run_action_cycle(
            trace_id=trace_id,
            tick_id=tick_id,
            tick_index=int(self.tick_counter),
            cfs_signals=cfs_signals,
            emotion_state=emotion_data,
            innate_focus_directives=new_directives,
            innate_action_triggers=new_action_triggers,
            memory_activation_snapshot=memory_snapshot,
            local_reward_punish_map=local_reward_punish_map,
        )
        action_data = action_result.get("data", {}) or {}
        report["action"] = action_data
        timing_steps_ms["action_ms"] = int((time.perf_counter() - t0) * 1000)

        # sanitized
        focus_directives_out = list(action_data.get("focus_directives_out", []) or [])
        if focus_directives_out:
            self._append_focus_directives(focus_directives_out)

        # sanitized
        action_mod_out = action_data.get("modulation_out", {}) or {}
        if isinstance(action_mod_out, dict):
            for key, value in action_mod_out.items():
                if isinstance(value, dict) and isinstance(next_modulation.get(key), dict):
                    next_modulation[key] = {**dict(next_modulation.get(key) or {}), **dict(value)}
                else:
                    next_modulation[key] = value
        # sanitized
        # sanitized
        # sanitized

        # =============================================================== #
        # sanitized
        # =============================================================== #
        # sanitized
        # sanitized
        # sanitized
        #
        # sanitized
        # sanitized
        # sanitized
        # sanitized
        t0 = time.perf_counter()
        recall_requests = [x for x in (action_data.get("recall_requests_out", []) or []) if isinstance(x, dict)]
        recall_apply_results: list[dict[str, Any]] = []
        recall_feedback_results: list[dict[str, Any]] = []
        recall_total_target_count = 0

        for req in recall_requests:
            targets = list(req.get("map_targets", req.get("targets", [])) or [])
            targets = [t for t in targets if isinstance(t, dict)]
            if not targets:
                continue
            recall_total_target_count += len(targets)
            if self._use_dedicated_memory_pool():
                apply_data = self.hdb.apply_memory_activation_targets(
                    targets=targets,
                    trace_id=f"{trace_id}_recall_map",
                    tick_id=tick_id,
                ).get("data", {}) or {}
                recall_apply_results.append(apply_data)

                fb_data = self._apply_memory_feedback(
                    memory_items=list(apply_data.get("items", []) or []),
                    trace_id=f"{trace_id}_recall_feedback",
                    tick_id=tick_id,
                )
                recall_feedback_results.append(fb_data)
            else:
                apply_data = self._build_runtime_memory_apply_result_from_targets(
                    targets=targets,
                    trace_id=f"{trace_id}_recall_runtime",
                    tick_id=tick_id,
                )
                runtime_projection = self._project_memory_activation_runtime_items(
                    memory_items=apply_data.get("items", []),
                    trace_id=f"{trace_id}_recall_runtime",
                    tick_id=tick_id,
                )
                apply_data["runtime_projection"] = runtime_projection
                recall_apply_results.append(apply_data)
                recall_feedback_results.append(
                    {
                        "enabled": False,
                        "synthetic": True,
                        "path_mode": self._memory_path_mode(),
                        "applied_count": 0,
                        "runtime_projection": runtime_projection,
                        "items": [],
                    }
                )

        recall_memory_snapshot_after: dict[str, Any] = {}
        if recall_apply_results:
            try:
                if self._use_dedicated_memory_pool():
                    recall_memory_snapshot_after = self.hdb.get_memory_activation_snapshot(
                        trace_id=f"{trace_id}_recall_map_snapshot",
                        limit=16,
                        sort_by="energy_desc",
                    ).get("data", {}) or {}
                else:
                    recall_memory_snapshot_after = self._build_runtime_memory_snapshot_from_pool(
                        trace_id=f"{trace_id}_recall_runtime_snapshot",
                        tick_id=tick_id,
                        limit=16,
                        sort_by="energy_desc",
                        source_items=apply_data.get("items", []),
                        projection_result=apply_data.get("runtime_projection", {}),
                    )
            except Exception:
                recall_memory_snapshot_after = {}

        if recall_requests:
            action_data["recall_side_effects"] = {
                "request_count": len(recall_requests),
                "target_count": int(recall_total_target_count),
                "apply_results": recall_apply_results,
                "feedback_results": recall_feedback_results,
                "memory_snapshot_after": recall_memory_snapshot_after,
            }
            # sanitized
            report.setdefault("memory_activation", {})
            report["memory_activation"]["snapshot_after_action"] = recall_memory_snapshot_after

        timing_steps_ms["action_recall_side_effect_ms"] = int((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        reward_action_runtime_sync = self._sync_reward_action_runtime_nodes(
            emotion_data=emotion_data,
            action_data=action_data,
            trace_id=trace_id,
            tick_id=tick_id,
        )
        action_data["reward_action_runtime_sync"] = reward_action_runtime_sync
        action_learning_summary = dict(action_data.get("action_learning_summary", {}) or {})
        sync_summary = reward_action_runtime_sync.get("summary", {}) if isinstance(reward_action_runtime_sync.get("summary", {}), dict) else {}
        action_learning_summary["humanlike_runtime_sync_enabled"] = bool(reward_action_runtime_sync.get("enabled", False))
        action_learning_summary["runtime_signal_node_count"] = int(sync_summary.get("signal_node_count", 0) or 0)
        action_learning_summary["runtime_signal_node_active_count"] = int(sync_summary.get("signal_node_active_count", 0) or 0)
        action_learning_summary["runtime_action_node_count"] = int(sync_summary.get("action_node_count", 0) or 0)
        action_learning_summary["runtime_action_node_active_count"] = int(sync_summary.get("action_node_active_count", 0) or 0)
        action_learning_summary["runtime_action_node_executed_count"] = int(sync_summary.get("action_node_executed_count", 0) or 0)
        action_learning_summary["runtime_action_target_ref_count"] = int(sync_summary.get("action_target_ref_count", 0) or 0)
        action_learning_summary["runtime_action_target_item_count"] = int(sync_summary.get("action_target_item_count", 0) or 0)
        action_data["action_learning_summary"] = action_learning_summary
        report["reward_action_runtime_sync"] = reward_action_runtime_sync
        timing_steps_ms["reward_action_runtime_sync_ms"] = int((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        try:
            final_snapshot_top_k_raw = int(
                self._config.get(
                    "final_state_snapshot_top_k",
                    self._config.get("snapshot_top_k", 24),
                )
                or 0
            )
        except Exception:
            final_snapshot_top_k_raw = 24
        final_snapshot_top_k = None if final_snapshot_top_k_raw <= 0 else max(1, final_snapshot_top_k_raw)
        final_state_snapshot = self.pool.get_state_snapshot(
            trace_id=f"{trace_id}_final_snapshot",
            tick_id=tick_id,
            top_k=final_snapshot_top_k,
        )["data"]["snapshot"]
        if bool(self._config.get("final_hdb_snapshot_lightweight_enabled", True)):
            hdb_snapshot = self._build_hdb_snapshot_lightweight(trace_id=f"{trace_id}_hdb_snapshot")
        else:
            hdb_snapshot = self.hdb.get_hdb_snapshot(trace_id=f"{trace_id}_hdb_snapshot", top_k=12)["data"]
        report["final_state"] = {
            "state_snapshot": final_state_snapshot,
            "state_energy_summary": self._summarize_state_snapshot(final_state_snapshot),
            "hdb_snapshot": hdb_snapshot,
        }
        timing_steps_ms["final_snapshot_ms"] = int((time.perf_counter() - t0) * 1000)

        # =============================================================== #
        # sanitized
        # =============================================================== #
        # sanitized
        # sanitized
        # sanitized
        # sanitized
        t0 = time.perf_counter()
        ebc_data: dict[str, Any] = {}
        try:
            es = report.get("final_state", {}).get("state_energy_summary", {}) or {}
            total_er = float(es.get("total_er", 0.0) or 0.0)
            total_ev = float(es.get("total_ev", 0.0) or 0.0)
            ebc_res = self.energy_balance.update_from_energy_summary(
                trace_id=f"{trace_id}_ebc",
                tick_id=tick_id,
                tick_index=int(self.tick_counter),
                total_er=total_er,
                total_ev=total_ev,
            )
            if isinstance(ebc_res, dict):
                ebc_data = ebc_res.get("data", {}) or {}
        except Exception as exc:
            ebc_data = {"error": str(exc)}
        report["energy_balance"] = ebc_data
        timing_steps_ms["energy_balance_ms"] = int((time.perf_counter() - t0) * 1000)

        # Merge EBC HDB scales into next_modulation (multiplicative).
        # sanitized
        try:
            hdb_scales = ebc_data.get("hdb_scales_out", {}) if isinstance(ebc_data, dict) else {}
            if isinstance(hdb_scales, dict) and hdb_scales:
                hdb_mod = next_modulation.get("hdb", {}) if isinstance(next_modulation.get("hdb", {}), dict) else {}
                hdb_mod = dict(hdb_mod)
                for k, v in hdb_scales.items():
                    key = str(k or "").strip()
                    if not key:
                        continue
                    try:
                        scale = float(v or 1.0)
                    except Exception:
                        scale = 1.0
                    if not (scale > 0.0):
                        scale = 1.0
                    try:
                        existing = float(hdb_mod.get(key, 1.0) or 1.0)
                    except Exception:
                        existing = 1.0
                    hdb_mod[key] = round(float(existing) * float(scale), 8)
                next_modulation["hdb"] = hdb_mod
        except Exception:
            pass

        # Commit the final merged modulation for the next tick.
        # sanitized
        self._last_modulation = dict(next_modulation)

        # sanitized
        total_logic_ms = int((time.perf_counter() - cycle_t0) * 1000)
        timing_steps_ms["total_logic_ms"] = int(total_logic_ms)
        report["timing"] = {
            "total_logic_ms": int(total_logic_ms),
            "steps_ms": dict(timing_steps_ms),
        }
        report["tick_counter"] = int(self.tick_counter)
        report["finished_at"] = int(time.time() * 1000)
        report["exports"] = self._export_report(trace_id, report)
        runtime_report = self._compact_report_for_runtime_cache(report)
        self._last_report = runtime_report
        self._last_report_trace_id = str(runtime_report.get("trace_id", "") or trace_id)
        self._report_history.append(runtime_report)
        history_limit = max(1, int(self._config.get("history_limit", 24)))
        if len(self._report_history) > history_limit:
            self._report_history = self._report_history[-history_limit:]
        if self._config.get("auto_open_html_report", False):
            open_target = trace_id if self._config.get("export_cycle_html_history", False) else "latest"
            self.open_report(open_target, open_browser=True)
        return report

    def show_state_snapshot(self, top_k: str | int | None = None) -> str:
        snapshot = self.pool.get_state_snapshot(trace_id="cmd_snap", top_k=None if top_k == "all" else top_k)["data"]["snapshot"]
        return render_state_snapshot(snapshot, None if top_k == "all" else top_k)

    def show_hdb_snapshot(self) -> str:
        snapshot = self.hdb.get_hdb_snapshot(trace_id="cmd_hdb", top_k=12)["data"]
        return render_hdb_snapshot(snapshot)

    def show_structure(self, structure_id: str) -> str:
        result = self.hdb.query_structure_database(structure_id=structure_id, trace_id="cmd_st")
        if not result["success"]:
            return result["message"]
        return render_structure_report(result["data"])

    def show_group(self, group_id: str) -> str:
        result = self.hdb.query_group(group_id=group_id, trace_id="cmd_sg")
        if not result["success"]:
            return result["message"]
        return render_group_report(result["data"])

    def show_episodic(self, limit: int = 10) -> str:
        result = self.hdb.get_recent_episodic(trace_id="cmd_em", limit=limit)
        return render_episodic_report(result["data"])

    def open_report(self, target: str = "latest", *, open_browser: bool = True) -> str:
        html_path = self.output_dir / ("latest.html" if target in {"", "latest"} else f"{target}.html")
        if not html_path.exists():
            return f"未找到报告 / Report not found: {html_path}"
        opened = False
        if open_browser:
            try:
                opened = webbrowser.open(html_path.resolve().as_uri())
            except Exception:
                opened = False
        return json.dumps(
            {
                "html_path": str(html_path),
                "opened": opened,
            },
            ensure_ascii=False,
            indent=2,
        )

    def run_tick_cycles(self, count: int = 1) -> list[dict]:
        reports = []
        for _ in range(max(1, int(count))):
            reports.append(self.run_cycle(text=None))
        return reports

    def get_last_report(self) -> dict[str, Any] | None:
        return self._last_report

    def get_report(self, trace_id: str = "latest") -> dict[str, Any] | None:
        if trace_id in {"", "latest"}:
            candidate_paths: list[Path] = []
            last_trace_id = str(self._last_report_trace_id or "").strip()
            if last_trace_id:
                candidate_paths.append(self.output_dir / f"{last_trace_id}.full.json")
                candidate_paths.append(self.output_dir / f"{last_trace_id}.json")
            candidate_paths.append(self.output_dir / "latest.json")
            for report_path in candidate_paths:
                if not report_path.exists():
                    continue
                try:
                    return json.loads(report_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
            return self._last_report
        candidate_paths = [
            self.output_dir / f"{trace_id}.full.json",
            self.output_dir / f"{trace_id}.json",
        ]
        for report_path in candidate_paths:
            if not report_path.exists():
                continue
            try:
                return json.loads(report_path.read_text(encoding="utf-8"))
            except Exception:
                continue
        return None

    def get_recent_cycle_summaries(self, limit: int | None = None) -> list[dict]:
        items = self._report_history[-(limit or len(self._report_history)) :]
        summaries = []
        for report in reversed(items):
            input_queue = report.get("input_queue", {}) if isinstance(report.get("input_queue", {}), dict) else {}
            matched_structure_ids = list(report.get("stimulus_level", {}).get("result", {}).get("matched_structure_ids", []))
            new_structure_ids = list(report.get("stimulus_level", {}).get("result", {}).get("new_structure_ids", []))
            matched_group_ids = list(report.get("structure_level", {}).get("result", {}).get("matched_group_ids", []))
            new_group_ids = list(report.get("structure_level", {}).get("result", {}).get("new_group_ids", []))
            summaries.append(
                {
                    "trace_id": report.get("trace_id", ""),
                    "started_at": report.get("started_at", 0),
                    "finished_at": report.get("finished_at", 0),
                    "input_text": report.get("sensor", {}).get("input_text", ""),
                    "tick_text": input_queue.get("tick_text", report.get("sensor", {}).get("input_text", "")),
                    "submitted_text": input_queue.get("submitted_text", ""),
                    "queue_source_text": input_queue.get("source_text", ""),
                    "pending_queue_after_tick": int(input_queue.get("pending_count_after_dequeue", 0) or 0),
                    "sensor_mode": report.get("sensor", {}).get("mode", ""),
                    "structure_rounds": report.get("structure_level", {}).get("result", {}).get("round_count", 0),
                    "stimulus_rounds": report.get("stimulus_level", {}).get("result", {}).get("round_count", 0),
                    "attention_memory_count": report.get("attention", {}).get("memory_item_count", 0),
                    "attention_consumed_total": report.get("attention", {}).get("consumed_total_energy", 0.0),
                    "matched_structures": matched_structure_ids,
                    "new_structures": new_structure_ids,
                    "matched_groups": matched_group_ids,
                    "new_groups": new_group_ids,
                    "matched_structure_refs": self._build_cycle_structure_refs(matched_structure_ids),
                    "new_structure_refs": self._build_cycle_structure_refs(new_structure_ids),
                    "matched_group_refs": self._build_cycle_group_refs(matched_group_ids),
                    "new_group_refs": self._build_cycle_group_refs(new_group_ids),
                    "total_delta_ev": report.get("induction", {}).get("result", {}).get("total_delta_ev", 0.0),
                    "memory_path_mode": report.get("memory_activation", {}).get("path_mode", ""),
                    "memory_activation_applied_count": report.get("memory_activation", {}).get("apply_result", {}).get("applied_count", 0),
                    "memory_feedback_applied_count": report.get("memory_activation", {}).get("feedback_result", {}).get("applied_count", 0),
                    "memory_feedback_total_er": report.get("memory_activation", {}).get("feedback_result", {}).get("total_feedback_er", 0.0),
                    "memory_feedback_total_ev": report.get("memory_activation", {}).get("feedback_result", {}).get("total_feedback_ev", 0.0),
                    "memory_activation_total_er": report.get("memory_activation", {}).get("snapshot", {}).get("summary", {}).get("total_er", 0.0),
                    "memory_activation_total_ev": report.get("memory_activation", {}).get("snapshot", {}).get("summary", {}).get("total_ev", 0.0),
                    "memory_runtime_projection_count": report.get("memory_activation", {}).get("runtime_projection", {}).get("summary", {}).get("inserted_count", 0),
                    "cfs_signal_count": len(report.get("cognitive_feeling", {}).get("cfs_signals", []) or []),
                    "nt_state": dict(report.get("emotion", {}).get("nt_state_after", {}) or {}),
                }
            )
        return summaries

    def _build_cycle_structure_refs(self, structure_ids: list[str]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for structure_id in list(dict.fromkeys(structure_ids)):
            if not structure_id:
                continue
            structure_obj = self.hdb._structure_store.get(structure_id)
            display_text = structure_id
            signature = ""
            flat_tokens: list[str] = []
            if structure_obj:
                payload = structure_obj.get("structure", {})
                display_text = payload.get("display_text", structure_id)
                signature = payload.get("content_signature", "")
                flat_tokens = list(payload.get("flat_tokens", []))
            refs.append(
                {
                    "structure_id": structure_id,
                    "display_text": display_text,
                    "content_signature": signature,
                    "flat_tokens": flat_tokens,
                }
            )
        return refs

    def _build_cycle_group_refs(self, group_ids: list[str]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for group_id in list(dict.fromkeys(group_ids)):
            if not group_id:
                continue
            if group_id.startswith("sg_single_"):
                structure_id = group_id.removeprefix("sg_single_")
                refs.append(
                    {
                        "group_id": group_id,
                        "synthetic": True,
                        "required_structures": self._build_cycle_structure_refs([structure_id] if structure_id else []),
                        "bias_structures": [],
                    }
                )
                continue
            group_obj = self.hdb._group_store.get(group_id)
            required_ids = list(group_obj.get("required_structure_ids", [])) if group_obj else []
            bias_ids = list(group_obj.get("bias_structure_ids", [])) if group_obj else []
            refs.append(
                {
                    "group_id": group_id,
                    "required_structures": self._build_cycle_structure_refs(required_ids),
                    "bias_structures": self._build_cycle_structure_refs(bias_ids),
                }
            )
        return refs

    def get_dashboard_data(self) -> dict[str, Any]:
        snapshot_top_k = int(self._config.get("snapshot_top_k", 24))
        state_snapshot = self.pool.get_state_snapshot(
            trace_id="dashboard_state",
            top_k=snapshot_top_k,
        )["data"]["snapshot"]
        hdb_snapshot = self.hdb.get_hdb_snapshot(trace_id="dashboard_hdb", top_k=snapshot_top_k)["data"]
        sensor_runtime = self.sensor.get_runtime_snapshot(trace_id="dashboard_sensor")["data"]
        time_sensor_runtime = self.time_sensor.get_runtime_snapshot(trace_id="dashboard_time_sensor")["data"]
        # sanitized
        energy_balance_runtime = {}
        try:
            energy_balance_runtime = self.energy_balance.get_runtime_snapshot(trace_id="dashboard_energy_balance")  # type: ignore[attr-defined]
        except Exception:
            energy_balance_runtime = {}
        current_tick_counter = int(self.tick_counter)
        return {
            "tick_counter": current_tick_counter,
            "meta": {
                "started_at": self._started_at,
                "tick_counter": current_tick_counter,
                "last_cycle_id": self._last_report.get("trace_id", "") if self._last_report else "",
                "output_dir": str(self.output_dir),
            },
            "last_report": self._last_report,
            "recent_cycles": self.get_recent_cycle_summaries(limit=int(self._config.get("history_limit", 24))),
            "state_snapshot": state_snapshot,
            "state_energy_summary": self._summarize_state_snapshot(state_snapshot),
            "hdb_snapshot": hdb_snapshot,
            "sensor_runtime": sensor_runtime,
            "time_sensor_runtime": time_sensor_runtime,
            "energy_balance_runtime": energy_balance_runtime,
            "module_configs": self.get_config_bundle(),
            "placeholder_modules": self.get_placeholder_modules(),
        }

    def get_state_snapshot_data(self, top_k: int | None = None) -> dict[str, Any]:
        snapshot = self.pool.get_state_snapshot(
            trace_id="api_state_snapshot",
            top_k=top_k,
        )["data"]["snapshot"]
        return {
            "snapshot": snapshot,
            "energy_summary": self._summarize_state_snapshot(snapshot),
        }

    def get_hdb_snapshot_data(self, top_k: int = 12) -> dict[str, Any]:
        return self.hdb.get_hdb_snapshot(trace_id="api_hdb_snapshot", top_k=top_k)["data"]

    def get_action_runtime_data(self) -> dict[str, Any]:
        """
        Action runtime snapshot for real-time monitoring.
        # sanitized
        """
        if not getattr(self, "action", None):
            return {"enabled": False, "message": "行动模块未初始化 / action module not initialized", "data": {}}
        return self.action.get_runtime_snapshot(trace_id="api_action_runtime")["data"]

    def stop_action_nodes(
        self,
        *,
        mode: str,
        value: Any = None,
        hold_ticks: int = 2,
        reason: str = "manual_stop",
        trace_id: str = "api_action_stop",
    ) -> dict[str, Any]:
        """
        Stop/cancel action nodes (exposed to Web UI).
        # sanitized
        """
        if not getattr(self, "action", None):
            return {"success": False, "code": "STATE_ERROR", "message": "行动模块未初始化 / action not initialized", "data": {}}
        res = self.action.stop_actions(
            trace_id=trace_id,
            mode=str(mode or ""),
            value=value,
            hold_ticks=int(hold_ticks or 0),
            reason=str(reason or "manual_stop"),
        )
        return res

    def get_structure_data(self, structure_id: str) -> dict[str, Any]:
        result = self.hdb.query_structure_database(structure_id=structure_id, trace_id="api_structure")
        if not result["success"]:
            raise ValueError(result["message"])
        return result["data"]

    def get_group_data(self, group_id: str) -> dict[str, Any]:
        if group_id.startswith("sg_single_"):
            structure_id = group_id.removeprefix("sg_single_")
            return {
                "group": {
                    "id": group_id,
                    "synthetic": True,
                    "group_kind": "implicit_single_st",
                    "required_structure_ids": [structure_id] if structure_id else [],
                    "bias_structure_ids": [],
                    "avg_energy_profile": {structure_id: 1.0} if structure_id else {},
                },
                "required_structures": self._build_cycle_structure_refs([structure_id] if structure_id else []),
                "bias_structures": [],
            }
        result = self.hdb.query_group(group_id=group_id, trace_id="api_group")
        if not result["success"]:
            raise ValueError(result["message"])
        return result["data"]

    def get_episodic_data(self, limit: int = 10) -> dict[str, Any]:
        return self.hdb.get_recent_episodic(trace_id="api_episodic", limit=limit)["data"]

    def run_check(self, target: str | None = None) -> str:
        result = self.hdb.self_check_hdb(trace_id="cmd_check", target_id=target)
        return render_check_report(result["data"])

    def run_repair(self, target: str) -> str:
        result = self.hdb.repair_hdb(
            trace_id="cmd_repair",
            target_id=target,
            repair_scope="targeted",
            background=False,
        )
        return render_repair_report(result["data"])

    def run_repair_all(self) -> str:
        result = self.hdb.repair_hdb(
            trace_id="cmd_repair_all",
            repair_scope="global_quick",
            background=True,
        )
        return render_repair_report(result["data"])

    def stop_repair(self, job_id: str) -> str:
        result = self.hdb.stop_repair_job(repair_job_id=job_id, trace_id="cmd_stop_repair")
        if not result["success"]:
            return result["message"]
        return render_repair_report(result["data"])

    def clear_hdb(self) -> str:
        result = self.hdb.clear_hdb(trace_id="cmd_clear_hdb", reason="interactive_reset", operator="researcher")
        return json.dumps(result["data"], ensure_ascii=False, indent=2)

    def _clear_runtime_modules(
        self,
        *,
        clear_hdb: bool,
        trace_prefix: str = "cmd_clear_all",
        reason: str = "interactive_reset",
        operator: str = "researcher",
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "sensor": self.sensor.clear_echo_pool(trace_id=f"{trace_prefix}_sensor"),
            "state_pool": self.pool.clear_state_pool(
                trace_id=f"{trace_prefix}_pool",
                reason=reason,
                operator=operator,
            ),
            "external_input_queue": self._clear_external_input_queue(),
        }
        if clear_hdb:
            result["hdb"] = self.hdb.clear_hdb(
                trace_id=trace_prefix,
                reason=reason,
                operator=operator,
            )
        try:
            result["time_sensor"] = self.time_sensor.clear_runtime_state(
                trace_id=f"{trace_prefix}_time_sensor",
                reason=reason,
            )
        except Exception as exc:
            result["time_sensor_error"] = str(exc)
        try:
            result["action"] = self.action.clear_runtime_state(
                trace_id=f"{trace_prefix}_action",
                reason=reason,
            )
        except Exception as exc:
            result["action_error"] = str(exc)
        try:
            result["attention"] = self.attention.clear_runtime_state(
                trace_id=f"{trace_prefix}_attention",
                reason=reason,
            )
        except Exception as exc:
            result["attention_error"] = str(exc)
        try:
            result["cognitive_stitching"] = self.cognitive_stitching.clear_runtime_state(
                trace_id=f"{trace_prefix}_cognitive_stitching",
                reason=reason,
            )
        except Exception as exc:
            result["cognitive_stitching_error"] = str(exc)
        self._pending_focus_directives = []
        self._last_modulation = {}
        self._projection_fatigue = {}
        self._runtime_residual_exact_rebind_cache = {}
        self._teacher_local_feedback_alias_cache = []
        self._last_report = None
        self._report_history = []
        self._last_report_trace_id = ""
        old_tick_counter = int(getattr(self, "tick_counter", 0) or 0)
        self.tick_counter = 0
        self._started_at = int(time.time() * 1000)
        result["report_cache_cleared"] = True
        result["tick_counter_reset"] = True
        result["tick_counter_before_reset"] = old_tick_counter
        result["started_at_reset"] = True
        result["focus_directives_cleared"] = True
        result["last_modulation_cleared"] = True
        result["projection_fatigue_cleared"] = True
        result["runtime_residual_exact_rebind_cache_cleared"] = True
        result["teacher_local_feedback_alias_cache_cleared"] = True
        return result

    def clear_all(self) -> str:
        result = self._clear_runtime_modules(
            clear_hdb=True,
            trace_prefix="cmd_clear_all",
            reason="interactive_reset",
            operator="researcher",
        )
        return json.dumps(result, ensure_ascii=False, indent=2)

    def show_config(self) -> str:
        payload = {
            "sensor_backend": self.sensor.get_runtime_snapshot()["data"]["config_summary"]["tokenizer_backend"],
            "sensor_tokenizer_available": self.sensor.get_runtime_snapshot()["data"]["config_summary"]["tokenizer_available"],
            "hdb_core": {
                key: self.hdb._config[key]
                for key in [
                    "stimulus_level_max_rounds",
                    "structure_level_max_rounds",
                    "ev_propagation_threshold",
                    "er_induction_threshold",
                    "fallback_lookup_max_candidates",
                ]
            },
            "observatory": dict(self._config),
            "observatory_config_path": self._config_path,
            "output_dir": str(self.output_dir),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def reload_all(self) -> str:
        self._config = self._build_config(self._config_override)
        payload = {
            "observatory": "OK",
            "text_sensor": self.sensor.reload_config(trace_id="cmd_reload_sensor")["code"],
            "time_sensor": self.time_sensor.reload_config(trace_id="cmd_reload_time_sensor")["code"],
            "state_pool": self.pool.reload_config(trace_id="cmd_reload_pool")["code"],
            "hdb": self.hdb.reload_config(trace_id="cmd_reload_hdb")["code"],
            "attention": self.attention.reload_config(trace_id="cmd_reload_attention")["code"],
            "cognitive_stitching": self.cognitive_stitching.reload_config(trace_id="cmd_reload_cs")["code"],
            "cognitive_feeling": self.cfs.reload_config(trace_id="cmd_reload_cfs")["code"],
            "emotion": self.emotion.reload_config(trace_id="cmd_reload_emotion")["code"],
            "innate_script": self.iesm.reload_config(trace_id="cmd_reload_iesm")["code"],
            "action": self.action.reload_config(trace_id="cmd_reload_action")["code"],
        }
        self._apply_runtime_overrides()
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def loop(self) -> None:
        self.print_header()
        try:
            while True:
                line = input("\nAP-OBS> ").strip().lstrip("\ufeff\ufffe")
                if not line:
                    continue
                if line in {"quit", "exit"}:
                    break
                if line == "help":
                    print(format_help())
                    continue
                if line.startswith("text "):
                    print(render_cycle_report(self.run_cycle(text=line[5:])))
                    continue

                parts = shlex.split(line)
                cmd = parts[0]
                if cmd == "tick":
                    count = int(parts[1]) if len(parts) > 1 else 1
                    for _ in range(max(1, count)):
                        print(render_cycle_report(self.run_cycle(text=None)))
                elif cmd == "snap":
                    arg = parts[1] if len(parts) > 1 else str(self._config["snapshot_top_k"])
                    top_k: str | int | None = "all" if arg == "all" else int(arg)
                    print(self.show_state_snapshot(top_k))
                elif cmd == "hdb":
                    print(self.show_hdb_snapshot())
                elif cmd == "st" and len(parts) > 1:
                    print(self.show_structure(parts[1]))
                elif cmd == "sg" and len(parts) > 1:
                    print(self.show_group(parts[1]))
                elif cmd == "em":
                    limit = int(parts[1]) if len(parts) > 1 else 10
                    print(self.show_episodic(limit))
                elif cmd == "check":
                    target = parts[1] if len(parts) > 1 else None
                    print(self.run_check(target))
                elif cmd == "repair" and len(parts) > 1:
                    print(self.run_repair(parts[1]))
                elif cmd == "repair_all":
                    print(self.run_repair_all())
                elif cmd == "stop_repair" and len(parts) > 1:
                    print(self.stop_repair(parts[1]))
                elif cmd == "clear_hdb":
                    print(self.clear_hdb())
                elif cmd == "clear_all":
                    print(self.clear_all())
                elif cmd == "config":
                    print(self.show_config())
                elif cmd == "reload":
                    print(self.reload_all())
                elif cmd == "open_report":
                    target = parts[1] if len(parts) > 1 else "latest"
                    print(self.open_report(target))
                else:
                    print(render_cycle_report(self.run_cycle(text=line)))
        finally:
            self.close()

    def _build_config(self, config_override: dict | None = None) -> dict:
        config = dict(DEFAULT_CONFIG)
        config.update(_load_yaml_config(self._config_path))
        if config_override:
            config.update(config_override)
        return config

    @staticmethod
    def _prefixed_runtime_override(
        config: dict[str, Any],
        *,
        prefix: str,
        exclude_keys: set[str] | None = None,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        pre = f"{str(prefix or '').strip()}_"
        if not pre.strip("_"):
            return out
        excluded = set(exclude_keys or set())
        for raw_key, raw_value in dict(config or {}).items():
            key = str(raw_key or "")
            if not key.startswith(pre):
                continue
            if key in excluded:
                continue
            stripped = key[len(pre):]
            if not stripped:
                continue
            out[stripped] = copy.deepcopy(raw_value)
        return out

    def _sensor_config_override(self) -> dict[str, Any]:
        goal_b_char_sa_string_mode = bool(self._config.get("enable_goal_b_char_sa_string_mode", False))
        default_mode = self._config.get("sensor_default_mode", "advanced")
        tokenizer_backend = self._config.get("sensor_tokenizer_backend", "jieba")
        enable_token_output = bool(self._config.get("sensor_enable_token_output", True))
        enable_char_output = bool(self._config.get("sensor_enable_char_output", False))
        if goal_b_char_sa_string_mode:
            default_mode = "simple"
            tokenizer_backend = "none"
            enable_token_output = False
            enable_char_output = True
        return {
            "default_mode": default_mode,
            "tokenizer_backend": tokenizer_backend,
            "enable_goal_b_char_sa_string_mode": goal_b_char_sa_string_mode,
            "enable_token_output": enable_token_output,
            "enable_char_output": enable_char_output,
            "enable_stimulus_intensity_attribute_sa": bool(self._config.get("sensor_enable_stimulus_intensity_attribute_sa", False)),
            "stimulus_intensity_attribute_min_er": max(0.0, float(self._config.get("sensor_stimulus_intensity_attribute_min_er", 0.0) or 0.0)),
            "attribute_er_ratio": float(self._config.get("sensor_attribute_er_ratio", 0.25)),
            "attribute_ev_ratio": float(self._config.get("sensor_attribute_ev_ratio", 0.0)),
            "enable_echo": bool(self._config.get("sensor_enable_echo", True)),
            "include_echoes_in_stimulus_packet_objects": bool(self._config.get("sensor_include_echoes_in_packet", True)),
        }

    def _state_pool_config_override(self) -> dict[str, Any]:
        return {
            "enable_placeholder_interfaces": bool(self._config.get("state_pool_enable_placeholder_interfaces", False)),
            "enable_script_broadcast": bool(self._config.get("state_pool_enable_script_broadcast", False)),
        }

    def _hdb_config_override(self) -> dict[str, Any]:
        override = self._prefixed_runtime_override(
            self._config,
            prefix="hdb",
            exclude_keys={"hdb_enable_background_repair", "hdb_data_dir"},
        )
        for key in (
            "residual_memory_as_structure_enabled",
            "residual_memory_as_structure_shadow_mode",
            "residual_memory_runtime_object_type",
            "unified_numeric_scoring_enabled",
            "attribute_soft_scoring_enabled",
            "sequence_soft_scoring_enabled",
            "time_factor_soft_bonus_enabled",
            "stimulus_residual_memory_promotion_enabled",
            "stimulus_residual_memory_promotion_require_time_signal",
            "stimulus_residual_memory_promotion_min_v2_score",
            "stimulus_residual_memory_promotion_max_candidates_per_owner",
        ):
            if key in self._config and key in HDB_DEFAULT_CONFIG:
                override[key] = copy.deepcopy(self._config.get(key))
        override.update({
            "enable_background_repair": bool(self._config.get("hdb_enable_background_repair", True)),
            "enable_goal_b_char_sa_string_mode": bool(self._config.get("enable_goal_b_char_sa_string_mode", False)),
        })
        if self._config.get("hdb_data_dir"):
            override["data_dir"] = self._config.get("hdb_data_dir")
        return override

    def _action_config_override(self) -> dict[str, Any]:
        override = self._prefixed_runtime_override(self._config, prefix="action")
        for key in ACTION_DEFAULT_CONFIG.keys():
            if key == "enabled":
                continue
            if key in self._config:
                override[key] = copy.deepcopy(self._config.get(key))
        return override

    def _apply_hdb_modulation_for_tick(
        self,
        *,
        modulation: dict[str, Any] | None,
        trace_id: str,
        tick_id: str,
    ) -> dict[str, Any]:
        """
        Apply HDB modulation scales for the current tick (best-effort).
        # sanitized

        Design / 闁荤姳鐒﹀畷姗€顢橀崫銉﹀暫濞达絽鎼禒顖炴煥?
        - modulation 闂佸搫顦崕鎾吹濠婂嫮鈻斿┑鐘辫兌椤?tick 闂?EMgr/Action 闁哄鐗婇幐鎼佸吹椤撱垺鏅柛褏娅漧f._last_modulation["hdb"]闂佹寧绋戦ˇ顓㈠焵?
        # sanitized
          闂佺粯甯熷▔娑㈠箖濡ゅ懎绀冪€广儱妫楅惁?scale 闁荤姳绶ょ槐鏇㈡偩?effective 闂佺锕﹂鏇㈠焵?
        # sanitized
        """
        mod = modulation if isinstance(modulation, dict) else {}
        base = getattr(self, "_hdb_config_base", None)
        if not isinstance(base, dict) or not base:
            base = dict(getattr(self.hdb, "_config", {}) or {})
            self._hdb_config_base = dict(base)

        applied: dict[str, Any] = {}

        def apply_scale(
            scale_key: str,
            cfg_key: str,
            *,
            min_value: float | None = None,
            runtime_min: float | None = None,
            runtime_max: float | None = None,
        ) -> None:
            # Reset to baseline first (avoid drift).
            try:
                base_val = float(base.get(cfg_key, self.hdb._config.get(cfg_key, 0.0) or 0.0) or 0.0)
            except Exception:
                base_val = float(self.hdb._config.get(cfg_key, 0.0) or 0.0)
            self.hdb._config[cfg_key] = base_val

            try:
                scale = float(mod.get(scale_key, 1.0) or 1.0)
            except Exception:
                scale = 1.0
            if not (scale > 0.0):
                scale = 1.0

            eff = float(base_val) * float(scale)
            if min_value is not None:
                eff = max(float(min_value), float(eff))
            self.hdb._config[cfg_key] = float(eff)
            runtime_eff = float(eff)
            runtime_clamped = False
            if runtime_min is not None and runtime_eff < float(runtime_min):
                runtime_eff = float(runtime_min)
                runtime_clamped = True
            if runtime_max is not None and runtime_eff > float(runtime_max):
                runtime_eff = float(runtime_max)
                runtime_clamped = True
            self.hdb._config[cfg_key] = float(runtime_eff)

            applied[cfg_key] = {
                "base": round(float(base_val), 8),
                "scale": round(float(scale), 8),
                "effective": round(float(eff), 8),
                "runtime_effective": round(float(runtime_eff), 8),
                "runtime_clamped": bool(runtime_clamped),
                "scale_key": scale_key,
            }
            if runtime_min is not None:
                applied[cfg_key]["runtime_min"] = round(float(runtime_min), 8)
            if runtime_max is not None:
                applied[cfg_key]["runtime_max"] = round(float(runtime_max), 8)

        # sanitized
        apply_scale("base_weight_er_gain_scale", "base_weight_er_gain", min_value=0.0)
        apply_scale("base_weight_ev_wear_scale", "base_weight_ev_wear", min_value=0.0)
        # sanitized
        apply_scale("ev_propagation_threshold_scale", "ev_propagation_threshold", min_value=0.0)
        apply_scale("ev_propagation_ratio_scale", "ev_propagation_ratio", min_value=0.0, runtime_min=1.0, runtime_max=1.0)
        apply_scale("er_induction_ratio_scale", "er_induction_ratio", min_value=0.0, runtime_min=1.0, runtime_max=1.0)

        try:
            # Update only the affected engines (fast enough for prototype).
            # sanitized
            self.hdb._weight.update_config(self.hdb._config)
            self.hdb._stimulus.update_config(self.hdb._config)
            self.hdb._structure_retrieval.update_config(self.hdb._config)
            self.hdb._induction.update_config(self.hdb._config)
        except Exception as exc:
            return {"error": str(exc), "applied": applied}

        return {"applied": applied, "base_refreshed": True, "tick_id": tick_id, "trace_id": trace_id}

    def _attention_config_override(self) -> dict[str, Any]:
        """Runtime overrides for the attention module."""
        override = {
            "top_n": int(self._config.get("attention_top_n", 16)),
            "consume_energy": bool(self._config.get("attention_stub_consume_energy", True)),
            "memory_energy_ratio": float(self._config.get("attention_memory_energy_ratio", 0.5)),
        }
        for key in ATTENTION_DEFAULT_CONFIG.keys():
            if key in {"top_n", "consume_energy", "memory_energy_ratio"}:
                continue
            if key in self._config:
                override[key] = copy.deepcopy(self._config.get(key))
        return override

    def _cognitive_stitching_config_override(self) -> dict[str, Any]:
        raw = self._config.get("cognitive_stitching_runtime_override", {})
        override = dict(raw) if isinstance(raw, dict) else {}
        if "context_concat_v2_enabled" in self._config:
            enabled = bool(self._config.get("context_concat_v2_enabled", True))
            override.setdefault("context_concat_v2_enabled", enabled)
            if "stitching_mode" not in override:
                override["stitching_mode"] = "context_match_v2" if enabled else "legacy_event"
            if "cs_v2_audit_only" not in override:
                override["cs_v2_audit_only"] = False if enabled else True
        return override

    def _cut_engine_config_override(self) -> dict[str, Any]:
        flatten_internal_group = self._config.get(
            "internal_stimulus_flatten_to_single_cooccurrence_group_enabled",
            self._config.get("hdb_internal_stimulus_flatten_to_single_cooccurrence_group_enabled", True),
        )
        return {
            "enable_goal_b_char_sa_string_mode": bool(self._config.get("enable_goal_b_char_sa_string_mode", False)),
            "internal_stimulus_flatten_to_single_cooccurrence_group_enabled": bool(flatten_internal_group),
        }

    def _apply_runtime_overrides(self) -> None:
        sensor_override = self._sensor_config_override()
        self.sensor._config.update(sensor_override)
        self.sensor._normalizer.update_config(self.sensor._config)
        self.sensor._segmenter.update_config(self.sensor._config)
        self.sensor._scorer.update_config(self.sensor._config)
        self.sensor._echo_mgr.update_config(self.sensor._config)
        self.sensor._logger.update_config(
            log_dir=self.sensor._config.get("log_dir", ""),
            max_file_bytes=self.sensor._config.get("log_max_file_bytes", 0),
        )

        pool_override = self._state_pool_config_override()
        self.pool._config.update(pool_override)
        self.pool._store.update_config(self.pool._config)
        self.pool._energy.update_config(self.pool._config)
        self.pool._neutralization.update_config(self.pool._config)
        self.pool._merge.update_config(self.pool._config)
        self.pool._binding.update_config(self.pool._config)
        self.pool._maintenance.update_config(self.pool._config)
        self.pool._snapshot.update_config(self.pool._config)
        self.pool._history.update_config(self.pool._config)
        self.pool._logger.update_config(
            log_dir=self.pool._config.get("log_dir", ""),
            max_file_bytes=self.pool._config.get("log_max_file_bytes", 0),
        )

        hdb_override = self._hdb_config_override()
        self.hdb._config.update(hdb_override)
        self.hdb._weight.update_config(self.hdb._config)
        self.hdb._pointer_index.update_config(self.hdb._config)
        self.hdb._maintenance.update_config(self.hdb._config)
        self.hdb._snapshot.update_config(self.hdb._config)
        self.hdb._cut.update_config(self.hdb._config)
        self.hdb._stimulus.update_config(self.hdb._config)
        self.hdb._structure_retrieval.update_config(self.hdb._config)
        self.hdb._induction.update_config(self.hdb._config)
        self.hdb._memory_activation_store.update_config(self.hdb._config)
        self.hdb._self_check.update_config(self.hdb._config)
        self.hdb._delete.update_config(self.hdb._config)
        self.hdb._repair.update_config(self.hdb._config)
        self.hdb._logger.update_config(
            log_dir=self.hdb._config.get("log_dir", ""),
            max_file_bytes=int(self.hdb._config.get("log_max_file_bytes", 0)),
        )
        # Refresh baseline after config changes (avoid drift in per-tick modulation).
        # sanitized
        self.cut_engine.update_config(self._cut_engine_config_override())
        self._hdb_config_base = dict(self.hdb._config)

        self.cut_engine.update_config(self._cut_engine_config_override())
        attention_override = self._attention_config_override()
        self.attention._config.update(attention_override)
        self.attention._logger.update_config(
            log_dir=self.attention._config.get("log_dir", ""),
            max_file_bytes=int(self.attention._config.get("log_max_file_bytes", 0)),
        )

        cs_override = self._cognitive_stitching_config_override()
        if cs_override:
            self.cognitive_stitching.update_config(cs_override, trace_id="observatory_runtime_override")

        action_override = self._action_config_override()
        if action_override:
            self.action._config.update(action_override)
        self.action._logger.update_config(
            log_dir=self.action._config.get("log_dir", ""),
            max_file_bytes=int(self.action._config.get("log_max_file_bytes", 0)),
        )

    def _module_config_specs(self) -> dict[str, dict[str, Any]]:
        return {
            "observatory": {
                "path": self._config_path,
                "defaults": dict(DEFAULT_CONFIG),
                "effective": lambda: dict(self._config),
                "runtime_override": lambda: {},
            },
            "text_sensor": {
                "path": self.sensor._config_path,
                "defaults": dict(TEXT_SENSOR_DEFAULT_CONFIG),
                "effective": lambda: dict(self.sensor._config),
                "runtime_override": self._sensor_config_override,
            },
            "time_sensor": {
                "path": self.time_sensor._config_path,
                "defaults": dict(TIME_SENSOR_DEFAULT_CONFIG),
                "effective": lambda: dict(self.time_sensor._config),
                "runtime_override": lambda: {},
            },
            "state_pool": {
                "path": self.pool._config_path,
                "defaults": dict(STATE_POOL_DEFAULT_CONFIG),
                "effective": lambda: dict(self.pool._config),
                "runtime_override": self._state_pool_config_override,
            },
            "hdb": {
                "path": self.hdb._config_path,
                "defaults": dict(HDB_DEFAULT_CONFIG),
                "effective": lambda: dict(self.hdb._config),
                "runtime_override": self._hdb_config_override,
            },
            "attention": {
                "path": self.attention._config_path,
                "defaults": dict(ATTENTION_DEFAULT_CONFIG),
                "effective": lambda: dict(self.attention._config),
                "runtime_override": self._attention_config_override,
            },
            "cognitive_stitching": {
                "path": self.cognitive_stitching._config_path,
                "defaults": dict(COGNITIVE_STITCHING_DEFAULT_CONFIG),
                "effective": lambda: dict(self.cognitive_stitching._config),
                "runtime_override": self._cognitive_stitching_config_override,
            },
            "cognitive_feeling": {
                "path": self.cfs._config_path,
                "defaults": dict(CFS_DEFAULT_CONFIG),
                "effective": lambda: dict(self.cfs._config),
                "runtime_override": lambda: {},
            },
            "emotion": {
                "path": self.emotion._config_path,
                "defaults": dict(EMOTION_DEFAULT_CONFIG),
                "effective": lambda: dict(self.emotion._config),
                "runtime_override": lambda: {},
            },
            "innate_script": {
                "path": self.iesm._config_path,
                "defaults": dict(IESM_DEFAULT_CONFIG),
                "effective": lambda: dict(self.iesm._config),
                "runtime_override": lambda: {},
            },
            "action": {
                "path": self.action._config_path,
                "defaults": dict(ACTION_DEFAULT_CONFIG),
                "effective": lambda: dict(self.action._config),
                "runtime_override": self._action_config_override,
            },
            "energy_balance": {
                "path": self.energy_balance._config_path,
                "defaults": dict(ENERGY_BALANCE_DEFAULT_CONFIG),
                "effective": lambda: dict(self.energy_balance._config),
                "runtime_override": lambda: {},
            },
        }

    def get_config_bundle(self) -> dict[str, Any]:
        bundle: dict[str, Any] = {}
        for module_name, spec in self._module_config_specs().items():
            bundle[module_name] = build_config_view(
                module_name=module_name,
                path=spec["path"],
                defaults=spec["defaults"],
                file_values=load_yaml_dict(spec["path"]),
                effective=spec["effective"](),
                runtime_override=spec["runtime_override"](),
            )
        return bundle

    def save_module_config(self, module_name: str, values: dict[str, Any]) -> dict[str, Any]:
        normalized_name = str(module_name).strip().lower()
        specs = self._module_config_specs()
        if normalized_name not in specs:
            raise ValueError(f"unsupported module_name: {module_name}")
        spec = specs[normalized_name]
        coerced, rejected = coerce_updates_by_defaults(spec["defaults"], values or {})
        merged = save_annotated_config(
            path=spec["path"],
            defaults=spec["defaults"],
            updates=coerced,
        )
        self.reload_all()
        return {
            "module": normalized_name,
            "path": spec["path"],
            "saved_values": coerced,
            "rejected_values": rejected,
            "file_values": merged,
            "config_bundle": self.get_config_bundle(),
        }

    # =============================================================== #
    # sanitized
    # =============================================================== #

    def get_innate_rules_data(self) -> dict[str, Any]:
        """Expose IESM rules bundle for the web UI."""
        return self.iesm.get_rules_bundle(trace_id="api_innate_rules", include_file_yaml=True)["data"]

    def validate_innate_rules(self, *, doc: dict[str, Any] | None = None, yaml_text: str | None = None) -> dict[str, Any]:
        """Validate innate rules doc/yaml and return normalized preview."""
        result = self.iesm.validate_rules(trace_id="api_innate_rules_validate", doc=doc, yaml_text=yaml_text)
        data = result.get("data", {}) or {}
        return {
            "valid": bool(result.get("success", False)),
            "code": result.get("code", ""),
            "message": result.get("message", ""),
            "errors": list(data.get("errors", []) or []),
            "warnings": list(data.get("warnings", []) or []),
            "normalized_doc": data.get("normalized_doc", {}) or {},
            "yaml_preview": str(data.get("yaml_preview", "") or ""),
        }

    def save_innate_rules(self, *, doc: dict[str, Any] | None = None, yaml_text: str | None = None) -> dict[str, Any]:
        """doc"""
        result = self.iesm.save_rules(trace_id="api_innate_rules_save", doc=doc, yaml_text=yaml_text)
        return {
            "saved": bool(result.get("success", False)),
            "code": result.get("code", ""),
            "message": result.get("message", ""),
            "data": result.get("data", {}) or {},
            "error": result.get("error", {}) or {},
        }

    def reload_innate_rules(self) -> dict[str, Any]:
        """Reload innate rules from disk."""
        result = self.iesm.reload_rules(trace_id="api_innate_rules_reload")
        return {
            "reloaded_ok": bool(result.get("success", False)),
            "code": result.get("code", ""),
            "message": result.get("message", ""),
            "data": result.get("data", {}) or {},
        }

    def simulate_innate_rules(self) -> dict[str, Any]:
        """Simulate rules on the last report context (dry-run)."""
        if not self._last_report:
            return {"ok": False, "message": "no last report yet"}
        trace_id = str(self._last_report.get("trace_id", "latest") or "latest")
        tick_id = trace_id

        cfs_signals = list((self._last_report.get("cognitive_feeling", {}) or {}).get("cfs_signals", []) or [])
        maint_events = list((self._last_report.get("maintenance", {}) or {}).get("events", []) or [])
        apply_events = list((self._last_report.get("pool_apply", {}) or {}).get("events", []) or [])

        try:
            maint_packet = self.pool._snapshot.build_script_check_packet(
                events=maint_events,
                pool_store=self.pool._store,
                trace_id=f"{trace_id}_sim_maint",
                tick_id=tick_id,
            )
        except Exception:
            maint_packet = {}
        try:
            apply_packet = self.pool._snapshot.build_script_check_packet(
                events=apply_events,
                pool_store=self.pool._store,
                trace_id=f"{trace_id}_sim_apply",
                tick_id=tick_id,
            )
        except Exception:
            apply_packet = {}

        # Build context from the last report (prefer report snapshots), so metric predicates can work in simulate.
        # sanitized
        pool_snapshot = (self._last_report.get("final_state", {}) or {}).get("state_snapshot") or {}
        emotion_state = self._last_report.get("emotion", {}) or {}
        sim_context = self._build_innate_rules_context(
            report=self._last_report,
            pool_snapshot=pool_snapshot if isinstance(pool_snapshot, dict) else None,
            emotion_state=emotion_state if isinstance(emotion_state, dict) else None,
            cfs_signals=cfs_signals,
            trace_id=trace_id,
            tick_id=tick_id,
        )

        sim = self.iesm.run_tick_rules(
            trace_id=trace_id,
            tick_id=tick_id,
            # Provide a real tick_index so delta/avg_rate metrics can use history (dry-run won't mutate runtime_state).
            # sanitized
            tick_index=int(self.tick_counter),
            cfs_signals=cfs_signals,
            state_windows=[
                {"stage": "maintenance", "packet": maint_packet},
                {"stage": "pool_apply", "packet": apply_packet},
            ],
            context=sim_context,
            dry_run=True,
        )
        return {"ok": bool(sim.get("success", False)), "code": sim.get("code", ""), "message": sim.get("message", ""), "data": sim.get("data", {}) or {}}

    # ================================================================== #
    # Innate Rules Context + Pool Effects                                 #
    # sanitized
    # ================================================================== #

    @staticmethod
    def _pool_item_has_iesm_relevant_attribute(item: dict[str, Any]) -> bool:
        if not isinstance(item, dict):
            return False
        binding_state = item.get("binding_state", {}) if isinstance(item.get("binding_state", {}), dict) else {}
        if binding_state.get("packet_attribute_by_name") or binding_state.get("bound_attribute_by_name"):
            return True
        if binding_state.get("bound_attribute_sa_ids"):
            return True
        ext = item.get("ext", {}) if isinstance(item.get("ext", {}), dict) else {}
        if ext.get("bound_attributes"):
            return True
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        if str(ref_snapshot.get("attribute_name", "") or "").strip():
            return True
        if ref_snapshot.get("attribute_displays") or ref_snapshot.get("bound_attribute_displays"):
            return True
        return False

    @staticmethod
    def _runtime_item_context_metadata_fast(item: dict[str, Any], ref_snapshot: dict[str, Any]) -> dict[str, Any]:
        meta = item.get("meta", {}) if isinstance(item.get("meta", {}), dict) else {}
        meta_ext = meta.get("ext", {}) if isinstance(meta.get("ext", {}), dict) else {}
        source = item.get("source", {}) if isinstance(item.get("source", {}), dict) else {}
        context_path_ids = (
            meta_ext.get("context_path_ids")
            or source.get("context_path_ids")
            or ref_snapshot.get("context_path_ids")
            or []
        )
        parent_ids = source.get("parent_ids") or meta_ext.get("parent_ids") or []
        return {
            "context_ref_object_id": str(
                meta_ext.get("context_ref_object_id")
                or source.get("context_ref_object_id")
                or ref_snapshot.get("context_ref_object_id")
                or ""
            ),
            "context_ref_object_type": str(
                meta_ext.get("context_ref_object_type")
                or source.get("context_ref_object_type")
                or ref_snapshot.get("context_ref_object_type")
                or ""
            ),
            "context_owner_structure_id": str(
                meta_ext.get("context_owner_structure_id")
                or source.get("context_owner_structure_id")
                or ref_snapshot.get("context_owner_id")
                or ref_snapshot.get("context_owner_structure_id")
                or ""
            ),
            "context_path_ids": [str(value) for value in list(context_path_ids or []) if str(value)],
            "parent_ids": [str(value) for value in list(parent_ids or []) if str(value)],
        }

    @staticmethod
    def _runtime_item_residual_metadata_fast(item: dict[str, Any], ref_snapshot: dict[str, Any]) -> dict[str, Any]:
        meta = item.get("meta", {}) if isinstance(item.get("meta", {}), dict) else {}
        meta_ext = meta.get("ext", {}) if isinstance(meta.get("ext", {}), dict) else {}
        return {
            "residual_origin_kind": str(
                meta_ext.get("residual_origin_kind")
                or ref_snapshot.get("residual_origin_kind")
                or ref_snapshot.get("residual_kind")
                or ""
            ),
            "residual_origin_entry_id": str(
                meta_ext.get("residual_origin_entry_id")
                or ref_snapshot.get("residual_origin_entry_id")
                or ""
            ),
        }

    def _build_runtime_pool_item_summary_fast(
        self,
        item: dict[str, Any],
        *,
        include_sequence_payload: bool = False,
    ) -> dict[str, Any]:
        """Build the small selector/projection subset without the full UI summary materializer."""
        cache_key = self._runtime_pool_item_summary_cache_key(
            item,
            include_sequence_payload=include_sequence_payload,
        )
        if cache_key is not None:
            cached = self._runtime_pool_item_summary_cache.get(cache_key)
            if isinstance(cached, dict):
                return self._clone_runtime_pool_item_summary(cached)

        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        energy = item.get("energy", {}) if isinstance(item.get("energy", {}), dict) else {}
        dynamics = item.get("dynamics", {}) if isinstance(item.get("dynamics", {}), dict) else {}
        binding_state = item.get("binding_state", {}) if isinstance(item.get("binding_state", {}), dict) else {}
        packet_by_name = binding_state.get("packet_attribute_by_name", {})
        runtime_by_name = binding_state.get("bound_attribute_by_name", {})
        packet_attribute_names = (
            sorted([str(key) for key in packet_by_name.keys() if str(key)])
            if isinstance(packet_by_name, dict)
            else []
        )
        runtime_attribute_names = (
            sorted([str(key) for key in runtime_by_name.keys() if str(key)])
            if isinstance(runtime_by_name, dict)
            else []
        )

        runtime_bound_attribute_units: list[dict[str, Any]] = []
        time_bucket_ref_object_id = ""
        time_bucket_id = ""
        time_bucket_label_zh = ""
        time_bucket_unit = ""
        time_basis = ""
        time_bucket_center_sec: float | None = None
        for attr in item.get("ext", {}).get("bound_attributes", []) or []:
            if not isinstance(attr, dict):
                continue
            content = attr.get("content", {}) if isinstance(attr.get("content", {}), dict) else {}
            meta = attr.get("meta", {}) if isinstance(attr.get("meta", {}), dict) else {}
            ext_meta = meta.get("ext", {}) if isinstance(meta.get("ext", {}), dict) else {}
            attr_name = str(content.get("attribute_name", "") or "").strip()
            attr_raw = str(content.get("raw", "") or "").strip()
            if not attr_name and ":" in attr_raw:
                attr_name = attr_raw.split(":", 1)[0].strip()
            attr_display = str(content.get("display", "") or attr_raw or attr.get("id", "")).strip()
            attr_value = content.get("attribute_value", None)
            if attr_name:
                runtime_attribute_names.append(attr_name)
            if attr_name or attr_value not in ("", None):
                runtime_bound_attribute_units.append(
                    {
                        "attribute_name": attr_name,
                        "attribute_value": attr_value,
                        "value_type": str(content.get("value_type", "") or "").strip(),
                        "raw": attr_raw,
                        "display": attr_display,
                        "meta": {"ext": {key: ext_meta.get(key) for key in (
                            "time_bucket_id",
                            "time_bucket_ref_object_id",
                            "time_bucket_center_sec",
                            "time_bucket_center_value",
                            "time_bucket_secondary_id",
                            "time_bucket_secondary_center_sec",
                            "time_bucket_secondary_center_value",
                            "time_basis",
                            "time_unit",
                            "delta_sec",
                            "delta_value",
                        ) if key in ext_meta}},
                    }
                )
            if attr_name == "时间感受":
                time_bucket_ref_object_id = str(ext_meta.get("time_bucket_ref_object_id", "") or "").strip()
                time_bucket_id = str(ext_meta.get("time_bucket_id", "") or "").strip()
                time_bucket_label_zh = str(ext_meta.get("time_bucket_label_zh", "") or "").strip()
                time_bucket_unit = str(ext_meta.get("time_bucket_unit", "") or "").strip()
                time_basis = str(ext_meta.get("time_basis", "") or "").strip()
                try:
                    if ext_meta.get("time_bucket_center_sec", None) is not None:
                        time_bucket_center_sec = float(ext_meta.get("time_bucket_center_sec"))
                except Exception:
                    time_bucket_center_sec = None

        runtime_attribute_names = sorted(set([name for name in runtime_attribute_names if str(name)]))
        self_attribute_name = str(ref_snapshot.get("attribute_name", "") or "").strip()
        seen_names: set[str] = set()
        all_attribute_names: list[str] = []
        for name in [*packet_attribute_names, *runtime_attribute_names, *([self_attribute_name] if self_attribute_name else [])]:
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            all_attribute_names.append(name)

        if bool(self._config.get("runtime_pool_summary_fast_metadata_enabled", True)):
            context_meta = self._runtime_item_context_metadata_fast(item, ref_snapshot)
            residual_meta = self._runtime_item_residual_metadata_fast(item, ref_snapshot)
        else:
            context_meta = extract_context_metadata(item)
            residual_meta = extract_residual_metadata(item)
        ref_light: dict[str, Any] = {
            "content_display": ref_snapshot.get("content_display", ""),
            "content_display_detail": ref_snapshot.get("content_display_detail", ""),
            "content_signature": ref_snapshot.get("content_signature", ""),
            "token_count": int(ref_snapshot.get("token_count", len(ref_snapshot.get("flat_tokens", []) or [])) or ref_snapshot.get("member_count", 0) or 0),
            "member_count": ref_snapshot.get("member_count", 0),
            "context_ref_object_id": ref_snapshot.get("context_ref_object_id", context_meta.get("context_ref_object_id", "")),
            "context_ref_object_type": ref_snapshot.get("context_ref_object_type", context_meta.get("context_ref_object_type", "")),
            "context_owner_id": ref_snapshot.get("context_owner_id", context_meta.get("context_owner_structure_id", "")),
            "context_path_ids": context_meta.get("context_path_ids", []),
            "context_text": ref_snapshot.get("context_text", ""),
            "residual_kind": ref_snapshot.get("residual_kind", ""),
            "source_em_id": ref_snapshot.get("source_em_id", ""),
            "memory_id": ref_snapshot.get("memory_id", ""),
            "source_memory_created_at": ref_snapshot.get("source_memory_created_at", 0),
            "attribute_displays": ref_snapshot.get("attribute_displays", []),
            "feature_displays": ref_snapshot.get("feature_displays", []),
            "bound_attribute_displays": ref_snapshot.get("bound_attribute_displays", []),
        }
        for key in (
            "role",
            "attribute_name",
            "attribute_value",
            "value_type",
            "action_id",
            "action_kind",
            "target_ref_object_id",
            "target_ref_object_type",
            "target_item_id",
            "target_display",
            "backing_structure_id",
            "structure_refs",
            "required_structure_ids",
            "bias_structure_ids",
        ):
            value = ref_snapshot.get(key, None)
            if value not in ("", None, [], {}):
                ref_light[key] = value
        if include_sequence_payload:
            ref_light["flat_tokens"] = ref_snapshot.get("flat_tokens", [])
            ref_light["sequence_groups"] = ref_snapshot.get("sequence_groups", [])
            ref_light["member_refs"] = ref_snapshot.get("member_refs", [])
            if ref_snapshot.get("structure_ext"):
                ref_light["structure_ext"] = ref_snapshot.get("structure_ext", {})
            if ref_snapshot.get("group_ext"):
                ref_light["group_ext"] = ref_snapshot.get("group_ext", {})

        display = str(ref_snapshot.get("content_display", "") or item.get("display_text", "") or item.get("display", "") or item.get("ref_object_id", "") or "")
        summary = {
            "item_id": item.get("id", item.get("item_id", "")),
            "ref_object_id": item.get("ref_object_id", ""),
            "ref_object_type": item.get("ref_object_type", ""),
            "ref_alias_ids": item.get("ref_alias_ids", []),
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
            "context_ref_object_id": context_meta.get("context_ref_object_id", ""),
            "context_ref_object_type": context_meta.get("context_ref_object_type", ""),
            "context_owner_structure_id": context_meta.get("context_owner_structure_id", ""),
            "context_owner_id": ref_snapshot.get("context_owner_id", context_meta.get("context_owner_structure_id", "")),
            "context_path_ids": context_meta.get("context_path_ids", []),
            "context_text": ref_snapshot.get("context_text", ""),
            "target_ref_object_id": ref_snapshot.get("target_ref_object_id", ""),
            "target_ref_object_type": ref_snapshot.get("target_ref_object_type", ""),
            "target_item_id": ref_snapshot.get("target_item_id", ""),
            "target_display": ref_snapshot.get("target_display", ""),
            "residual_origin_kind": residual_meta.get("residual_origin_kind", ""),
            "residual_origin_entry_id": residual_meta.get("residual_origin_entry_id", ""),
            "residual_kind": ref_snapshot.get("residual_kind", ""),
            "source_em_id": ref_snapshot.get("source_em_id", ""),
            "memory_id": ref_snapshot.get("memory_id", ""),
            "source_memory_created_at": ref_snapshot.get("source_memory_created_at", 0),
            "attribute_displays": ref_snapshot.get("attribute_displays", []),
            "feature_displays": ref_snapshot.get("feature_displays", []),
            "bound_attribute_displays": ref_snapshot.get("bound_attribute_displays", []),
            "runtime_bound_attribute_units": runtime_bound_attribute_units,
            "time_bucket_ref_object_id": time_bucket_ref_object_id,
            "time_bucket_id": time_bucket_id,
            "time_bucket_label_zh": time_bucket_label_zh,
            "time_bucket_unit": time_bucket_unit,
            "time_basis": time_basis,
            "time_bucket_center_sec": time_bucket_center_sec,
            "packet_attribute_names": packet_attribute_names,
            "runtime_attribute_names": runtime_attribute_names,
            "all_attribute_names": all_attribute_names,
            "bound_attribute_names": list(runtime_attribute_names),
            "member_count": ref_snapshot.get("member_count", 0),
            "er": energy.get("er", 0),
            "ev": energy.get("ev", 0),
            "cp_delta": energy.get("cognitive_pressure_delta", 0),
            "cp_abs": energy.get("cognitive_pressure_abs", 0),
            "salience_score": energy.get("salience_score", 0),
            "fatigue": energy.get("fatigue", 0),
            "recency_gain": energy.get("recency_gain", 0),
            "delta_er": dynamics.get("delta_er", 0),
            "delta_ev": dynamics.get("delta_ev", 0),
            "delta_cp_delta": dynamics.get("delta_cp_delta", 0),
            "delta_cp_abs": dynamics.get("delta_cp_abs", 0),
            "er_change_rate": dynamics.get("er_change_rate", 0),
            "ev_change_rate": dynamics.get("ev_change_rate", 0),
            "cp_delta_rate": dynamics.get("cp_delta_rate", 0),
            "cp_abs_rate": dynamics.get("cp_abs_rate", 0),
            "update_count": dynamics.get("update_count", 0),
            "last_update_tick": dynamics.get("last_update_tick", 0),
            "bound_attribute_count": len(binding_state.get("bound_attribute_sa_ids", [])),
            "bound_csa_item_id": binding_state.get("bound_csa_item_id"),
            "status": item.get("status", "active"),
            "updated_at": item.get("updated_at", 0),
            "created_at": item.get("created_at", 0),
        }
        if cache_key is not None:
            self._remember_runtime_pool_item_summary(cache_key, summary)
            return self._clone_runtime_pool_item_summary(summary)
        return summary

    def _runtime_pool_item_summary_cache_key(
        self,
        item: dict[str, Any],
        *,
        include_sequence_payload: bool,
    ) -> tuple | None:
        if not bool(self._config.get("runtime_pool_item_summary_cache_enabled", True)):
            return None
        if not isinstance(item, dict):
            return None
        item_id = str(item.get("id", "") or item.get("item_id", "") or "")
        if not item_id:
            return None
        energy = item.get("energy", {}) if isinstance(item.get("energy", {}), dict) else {}
        dynamics = item.get("dynamics", {}) if isinstance(item.get("dynamics", {}), dict) else {}
        binding_state = item.get("binding_state", {}) if isinstance(item.get("binding_state", {}), dict) else {}
        ext = item.get("ext", {}) if isinstance(item.get("ext", {}), dict) else {}
        bound_attributes = ext.get("bound_attributes", []) if isinstance(ext.get("bound_attributes", []), list) else []
        packet_by_name = binding_state.get("packet_attribute_by_name", {})
        runtime_by_name = binding_state.get("bound_attribute_by_name", {})
        return (
            item_id,
            bool(include_sequence_payload),
            str(item.get("ref_object_id", "") or ""),
            str(item.get("ref_object_type", "") or ""),
            str(item.get("semantic_signature", "") or ""),
            int(item.get("updated_at", 0) or 0),
            self._cache_safe_float(energy.get("er", 0.0)),
            self._cache_safe_float(energy.get("ev", 0.0)),
            self._cache_safe_float(energy.get("cognitive_pressure_delta", 0.0)),
            self._cache_safe_float(energy.get("cognitive_pressure_abs", 0.0)),
            self._cache_safe_float(energy.get("salience_score", 0.0)),
            self._cache_safe_float(energy.get("fatigue", 0.0)),
            self._cache_safe_float(energy.get("recency_gain", 0.0)),
            int(dynamics.get("last_update_tick", 0) or 0),
            int(dynamics.get("update_count", 0) or 0),
            self._cache_safe_float(dynamics.get("delta_er", 0.0)),
            self._cache_safe_float(dynamics.get("delta_ev", 0.0)),
            self._cache_safe_float(dynamics.get("delta_cp_delta", 0.0)),
            self._cache_safe_float(dynamics.get("delta_cp_abs", 0.0)),
            len(bound_attributes),
            tuple(sorted(str(key) for key in packet_by_name.keys() if str(key))) if isinstance(packet_by_name, dict) else (),
            tuple(sorted(str(key) for key in runtime_by_name.keys() if str(key))) if isinstance(runtime_by_name, dict) else (),
        )

    @staticmethod
    def _cache_safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    def _remember_runtime_pool_item_summary(self, key: tuple, summary: dict[str, Any]) -> None:
        if not key or not isinstance(summary, dict):
            return
        try:
            max_entries = int(self._config.get("runtime_pool_item_summary_cache_max_entries", 4096) or 0)
        except Exception:
            max_entries = 4096
        if max_entries <= 0:
            return
        cache = self._runtime_pool_item_summary_cache
        if key in cache:
            cache[key] = summary
            return
        while len(cache) >= max_entries:
            try:
                cache.pop(next(iter(cache)))
            except StopIteration:
                break
        cache[key] = summary

    @staticmethod
    def _clone_runtime_pool_item_summary(summary: dict[str, Any]) -> dict[str, Any]:
        cloned = dict(summary)
        if isinstance(cloned.get("ref_snapshot"), dict):
            cloned["ref_snapshot"] = dict(cloned.get("ref_snapshot") or {})
        for key in (
            "ref_alias_ids",
            "attribute_displays",
            "feature_displays",
            "bound_attribute_displays",
            "runtime_bound_attribute_units",
            "packet_attribute_names",
            "runtime_attribute_names",
            "all_attribute_names",
            "bound_attribute_names",
            "context_path_ids",
        ):
            if isinstance(cloned.get(key), list):
                cloned[key] = list(cloned.get(key) or [])
        return cloned

    @staticmethod
    def _raw_pool_metric_totals(items: list[dict[str, Any]]) -> dict[str, Any]:
        total_er = 0.0
        total_ev = 0.0
        total_cp_delta = 0.0
        total_cp_abs = 0.0
        energies: list[float] = []
        core_energies: list[float] = []
        fallback_energies: list[float] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            energy = item.get("energy", {}) if isinstance(item.get("energy", {}), dict) else {}
            try:
                er = max(0.0, float(energy.get("er", 0.0) or 0.0))
                ev = max(0.0, float(energy.get("ev", 0.0) or 0.0))
                cp_delta = float(energy.get("cognitive_pressure_delta", 0.0) or 0.0)
                cp_abs = float(energy.get("cognitive_pressure_abs", 0.0) or 0.0)
            except Exception:
                er = ev = cp_delta = cp_abs = 0.0
            total = er + ev
            total_er += er
            total_ev += ev
            total_cp_delta += cp_delta
            total_cp_abs += cp_abs
            energies.append(max(0.0, total))
            ref_type = str(item.get("ref_object_type", "") or "").strip().lower()
            if ref_type in {"st", "sg"}:
                core_energies.append(max(0.0, total))
            elif ref_type != "em":
                fallback_energies.append(max(0.0, total))
        return {
            "item_count": len([x for x in items if isinstance(x, dict)]),
            "total_er": round(float(total_er), 8),
            "total_ev": round(float(total_ev), 8),
            "total_cp_delta": round(float(total_cp_delta), 8),
            "total_cp_abs": round(float(total_cp_abs), 8),
            "energies": energies,
            "core_energies": core_energies if core_energies else fallback_energies,
        }

    def _collect_iesm_live_pool_context_items(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        try:
            all_items = [item for item in list(self.pool._store.get_all()) if isinstance(item, dict)]  # type: ignore[attr-defined]
        except Exception:
            all_items = []
        totals = self._raw_pool_metric_totals(all_items)
        try:
            limit = int(self._config.get("iesm_context_pool_item_limit", 256) or 0)
        except Exception:
            limit = 256
        try:
            bucket_size = int(self._config.get("iesm_context_pool_bucket_size", 96) or 96)
        except Exception:
            bucket_size = 96
        try:
            min_total_energy = float(self._config.get("iesm_context_pool_min_total_energy", 1e-8) or 0.0)
        except Exception:
            min_total_energy = 1e-8
        if limit <= 0:
            selected_items = all_items
        else:
            bucket_size = max(1, min(max(limit, 1), bucket_size))
            selected_by_id: dict[str, dict[str, Any]] = {}
            attr_relevance_cache: dict[str, bool] = {}

            def _energy_total(item: dict[str, Any]) -> float:
                energy = item.get("energy", {}) if isinstance(item.get("energy", {}), dict) else {}
                try:
                    return max(0.0, float(energy.get("er", 0.0) or 0.0)) + max(0.0, float(energy.get("ev", 0.0) or 0.0))
                except Exception:
                    return 0.0

            def _has_relevant_attr(item: dict[str, Any]) -> bool:
                item_id = str(item.get("id", "") or item.get("item_id", "") or "")
                if item_id and item_id in attr_relevance_cache:
                    return bool(attr_relevance_cache[item_id])
                value = self._pool_item_has_iesm_relevant_attribute(item)
                if item_id:
                    attr_relevance_cache[item_id] = bool(value)
                return bool(value)

            def _add_candidates(candidates: list[dict[str, Any]]) -> None:
                for item in candidates:
                    if not isinstance(item, dict):
                        continue
                    item_id = str(item.get("id", "") or item.get("item_id", "") or "")
                    if not item_id:
                        continue
                    if _energy_total(item) < min_total_energy and not _has_relevant_attr(item):
                        continue
                    selected_by_id[item_id] = item

            ranked_rows: list[tuple[float, float, float, float, float, dict[str, Any]]] = []
            for item in all_items:
                if not isinstance(item, dict):
                    continue
                energy = item.get("energy", {}) if isinstance(item.get("energy", {}), dict) else {}
                try:
                    er = max(0.0, float(energy.get("er", 0.0) or 0.0))
                    ev = max(0.0, float(energy.get("ev", 0.0) or 0.0))
                    cp_abs = max(0.0, float(energy.get("cognitive_pressure_abs", 0.0) or 0.0))
                except Exception:
                    er = ev = cp_abs = 0.0
                total = er + ev
                attr_bonus = 1.0 if _has_relevant_attr(item) else 0.0
                if total >= min_total_energy or attr_bonus > 0.0:
                    ranked_rows.append((cp_abs, er, ev, total, float(item.get("updated_at", 0) or 0), item))
            bucket_take = max(0, min(bucket_size, len(ranked_rows)))
            for column_index in range(5):
                rows = heapq.nlargest(bucket_take, ranked_rows, key=lambda row: row[column_index])
                _add_candidates([row[5] for row in rows])

            def _rank(item: dict[str, Any]) -> tuple[float, float, float, float, float]:
                energy = item.get("energy", {}) if isinstance(item.get("energy", {}), dict) else {}
                try:
                    er = max(0.0, float(energy.get("er", 0.0) or 0.0))
                    ev = max(0.0, float(energy.get("ev", 0.0) or 0.0))
                    cp_abs = max(0.0, float(energy.get("cognitive_pressure_abs", 0.0) or 0.0))
                except Exception:
                    er = ev = cp_abs = 0.0
                attr_bonus = 1.0 if _has_relevant_attr(item) else 0.0
                return (
                    attr_bonus,
                    max(cp_abs, er, ev),
                    er + ev,
                    float(item.get("updated_at", 0) or 0),
                    cp_abs,
                )

            selected_items = sorted(selected_by_id.values(), key=_rank, reverse=True)
            if len(selected_items) > limit:
                selected_items = selected_items[:limit]

        pool_items: list[dict[str, Any]] = []
        for item in selected_items:
            try:
                if bool(self._config.get("iesm_fast_pool_item_summary_enabled", True)):
                    summary = self._build_runtime_pool_item_summary_fast(item, include_sequence_payload=False)
                else:
                    summary = self.pool._snapshot._build_top_item_summary(item)  # type: ignore[attr-defined]
                if isinstance(summary, dict):
                    pool_items.append(summary)
            except Exception:
                continue
        totals["context_item_count"] = len(pool_items)
        totals["context_item_limit"] = int(limit)
        return pool_items, totals

    def _build_innate_rules_context(
        self,
        *,
        report: dict[str, Any] | None,
        pool_snapshot: dict[str, Any] | None,
        emotion_state: dict[str, Any] | None,
        cfs_signals: list[dict] | None,
        trace_id: str,
        tick_id: str,
    ) -> dict[str, Any]:
        """
        Build the runtime context for IESM metric predicates.
        # sanitized

        # sanitized
          - pool: total_er/total_ev/total_cp_delta/total_cp_abs/energy_concentration/effective_peak_count/complexity_score
          - pool_items: list of item summaries (selectors use display/attrs/etc.)
          - cam: size/energy_concentration (閻熸粎澧楅幐鍛婃櫠閻樻祴鏋栭柕濠忕畱婢瑰牓鎮规担瑙勭凡缂佽鍊归幏鍛村箻鐎涙ê鏋€闁?
          - memory_activation: item_count/total_ev (闁荤姳鐒﹀妯兼崲閸屾粍灏庨悗锝庡幖閸樺瓨鎱ㄩ崷顓炐ｉ柟鎻掔－閹?
          - emotion: {nt:{}, rwd, pun}
          - stimulus: {residual_ratio}
          - retrieval: {stimulus:{best_match_score, grasp_score}}

        Notes / 说明:
        - IESM runs before EMgr update in run_cycle, so emotion_state may be None.
          # sanitized
          # sanitized
        """
        report = report if isinstance(report, dict) else {}
        cfs_signals = list(cfs_signals or [])

        # ---- pool_items ----
        pool_items: list[dict[str, Any]] = []
        pool_metric_totals: dict[str, Any] = {}
        if isinstance(pool_snapshot, dict) and isinstance(pool_snapshot.get("top_items"), list):
            for row in pool_snapshot.get("top_items", []) or []:
                if isinstance(row, dict):
                    pool_items.append(dict(row))
        else:
            # Runtime rule selectors only need active candidates, while global metrics
            # still use raw full-pool energy totals. This keeps CFS/IESM responsive as
            # low-energy residual tails grow.
            pool_items, pool_metric_totals = self._collect_iesm_live_pool_context_items()

        # Ensure total_energy is available for selector.top_n.
        # sanitized
        input_queue = report.get("input_queue", {}) if isinstance(report.get("input_queue", {}), dict) else {}
        input_source_text = str(input_queue.get("source_text", "") or report.get("sensor", {}).get("input_text", "") or "")
        input_tick_text = str(input_queue.get("tick_text", "") or report.get("sensor", {}).get("input_text", "") or "")
        tick_labels = report.get("tick_labels", {}) if isinstance(report.get("tick_labels", {}), dict) else {}
        stream_meta = tick_labels.get("stream", {}) if isinstance(tick_labels.get("stream", {}), dict) else {}
        input_stream_role = str(stream_meta.get("role", "") or "").strip().lower()
        input_stream_kind = str(stream_meta.get("kind", "") or "").strip().lower()
        input_stream_phase = str(stream_meta.get("phase", "") or "").strip().lower()
        input_has_text = 1 if (input_source_text or input_tick_text) else 0
        input_is_empty = 1 if not (input_tick_text or input_source_text) else 0
        current_input_flags = {
            "input_stream_role": input_stream_role,
            "input_stream_kind": input_stream_kind,
            "input_stream_phase": input_stream_phase,
            "input_has_text": input_has_text,
            "input_is_empty": input_is_empty,
            "input_is_user": 1 if input_stream_role == "user" else 0,
            "input_is_assistant": 1 if input_stream_role == "assistant" else 0,
            "input_is_system": 1 if input_stream_role == "system" else 0,
            "input_is_message": 1 if input_stream_kind == "message" else 0,
            "input_is_reply": 1 if input_stream_kind == "reply" else 0,
            "input_is_session_restore": 1 if input_stream_kind == "session_restore" else 0,
        }
        if input_source_text or input_tick_text:
            input_display = input_source_text or input_tick_text
            input_detail = input_tick_text if input_tick_text and input_tick_text != input_display else ""
            pool_items.append(
                {
                    "item_id": "ctx_input_current",
                    "ref_object_id": "ctx_input_current",
                    "ref_object_type": "input",
                    "display": input_display,
                    "display_text": input_display,
                    "display_detail": input_detail,
                    "attribute_displays": [],
                    "feature_displays": [input_tick_text] if input_tick_text else [],
                    "bound_attribute_displays": [],
                    "er": 0.0,
                    "ev": 0.0,
                    "cp_delta": 0.0,
                    "cp_abs": 0.0,
                    "total_energy": 0.0,
                    **current_input_flags,
                }
            )

        for row in pool_items:
            if isinstance(row, dict):
                for key, value in current_input_flags.items():
                    row[key] = value

        for row in pool_items:
            try:
                er = float(row.get("er", 0.0) or 0.0)
                ev = float(row.get("ev", 0.0) or 0.0)
                row["total_energy"] = round(max(0.0, er) + max(0.0, ev), 8)
            except Exception:
                row["total_energy"] = 0.0

        # Verification anchor / 验证锚点：
        # - expectation/pressure 这类“预测 + 奖惩属性”经常挂在较复杂的复合结构上；
        # - 这些复合结构本身不一定稳定获得后续 ER，因此 verified 分支容易长期为 0；
        # - 这里把每个对象映射到一个更简单、更稳定的“主特征锚点”，供 IESM 做验证跟踪。
        def _collect_verification_anchor_candidates(row: dict[str, Any]) -> list[dict[str, Any]]:
            if not isinstance(row, dict):
                return []
            ref_snapshot = row.get("ref_snapshot", {}) if isinstance(row.get("ref_snapshot", {}), dict) else {}
            groups = ref_snapshot.get("sequence_groups", []) if isinstance(ref_snapshot.get("sequence_groups", []), list) else []
            candidates: list[dict[str, Any]] = []
            seen_signatures: set[str] = set()
            for group in groups:
                if not isinstance(group, dict):
                    continue
                tokens = [str(tok) for tok in (group.get("tokens", []) or []) if str(tok)]
                if not tokens:
                    continue
                display = str(
                    group.get("display_text", "")
                    or group.get("string_token_text", "")
                    or "".join(tokens)
                ).strip()
                signature = str(group.get("group_signature", "") or "").strip()
                if not signature:
                    signature = f"group::{int(bool(group.get('order_sensitive', False)))}::{'|'.join(tokens)}"
                if not signature or signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                candidates.append(
                    {
                        "signature": signature,
                        "display": display or str(row.get("display", "") or ""),
                        "token_count": len(tokens),
                        "preferred_rank": 0
                        if bool(group.get("order_sensitive", False)) and str(group.get("string_unit_kind", "") or "") == "char_sequence"
                        else 1,
                    }
                )
            if candidates:
                return candidates
            flat_tokens = [str(tok) for tok in (ref_snapshot.get("flat_tokens", []) or []) if str(tok)]
            display = str(row.get("display", "") or row.get("display_text", "") or row.get("ref_object_id", "") or "").strip()
            signature = ""
            if flat_tokens:
                signature = f"flat::{str(row.get('ref_object_type', '') or '').strip()}::{'|'.join(flat_tokens)}"
            elif display:
                signature = f"display::{display}"
            if not signature:
                return []
            return [
                {
                    "signature": signature,
                    "display": display,
                    "token_count": len(flat_tokens),
                    "preferred_rank": 9,
                }
            ]

        anchor_rows: dict[str, dict[str, Any]] = {}

        def _anchor_row_score(row: dict[str, Any], meta: dict[str, Any]) -> tuple[float, ...]:
            ref_snapshot = row.get("ref_snapshot", {}) if isinstance(row.get("ref_snapshot", {}), dict) else {}
            flat_tokens = ref_snapshot.get("flat_tokens", []) if isinstance(ref_snapshot.get("flat_tokens", []), list) else []
            ref_type = str(row.get("ref_object_type", "") or "").strip().lower()
            type_rank = {
                "st": 0.0,
                "sg": 1.0,
                "sa": 2.0,
            }.get(ref_type, 3.0)
            token_count = int(meta.get("token_count", 0) or len(flat_tokens) or 0)
            attr_count = len([x for x in (row.get("all_attribute_names", []) or []) if str(x)])
            er = max(0.0, float(row.get("er", 0.0) or 0.0))
            total_energy = max(0.0, float(row.get("total_energy", 0.0) or 0.0))
            updated_at = int(row.get("updated_at", 0) or 0)
            return (
                type_rank,
                float(token_count),
                float(attr_count),
                -float(er),
                -float(total_energy),
                -float(updated_at),
            )

        for row in pool_items:
            if not isinstance(row, dict):
                continue
            candidates = _collect_verification_anchor_candidates(row)
            row["_verification_anchor_candidates"] = [dict(meta) for meta in candidates]
            primary = candidates[0] if candidates else {"signature": "", "display": str(row.get("display", "") or ""), "token_count": 0, "preferred_rank": 9}
            row["verification_anchor_signature"] = str(primary.get("signature", "") or "")
            row["verification_anchor_display"] = str(primary.get("display", "") or row.get("display", "") or "")
            for meta in candidates:
                signature = str(meta.get("signature", "") or "").strip()
                if not signature:
                    continue
                current_entry = anchor_rows.get(signature)
                if current_entry is None or _anchor_row_score(row, meta) < _anchor_row_score(
                    current_entry.get("row", {}),
                    current_entry.get("meta", {}) if isinstance(current_entry.get("meta", {}), dict) else meta,
                ):
                    anchor_rows[signature] = {"row": row, "meta": dict(meta)}

        for row in pool_items:
            if not isinstance(row, dict):
                continue
            candidates = row.get("_verification_anchor_candidates", []) if isinstance(row.get("_verification_anchor_candidates", []), list) else []
            chosen_entry: dict[str, Any] | None = None
            chosen_meta: dict[str, Any] | None = None
            best_pick_score: tuple[float, ...] | None = None
            for meta in candidates:
                if not isinstance(meta, dict):
                    continue
                signature = str(meta.get("signature", "") or "").strip()
                entry = anchor_rows.get(signature)
                if not isinstance(entry, dict):
                    continue
                rep_row = entry.get("row", {}) if isinstance(entry.get("row", {}), dict) else {}
                rep_type = str(rep_row.get("ref_object_type", "") or "").strip().lower()
                rep_type_rank = {
                    "st": 0.0,
                    "sg": 1.0,
                    "sa": 2.0,
                }.get(rep_type, 3.0)
                rep_er = max(0.0, float(rep_row.get("er", 0.0) or 0.0))
                rep_total = max(0.0, float(rep_row.get("total_energy", 0.0) or 0.0))
                pick_score = (
                    rep_type_rank,
                    0.0 if rep_er > 1e-9 else 1.0,
                    float(meta.get("preferred_rank", 9) or 9),
                    float(meta.get("token_count", 0) or 0),
                    -float(rep_er),
                    -float(rep_total),
                )
                if best_pick_score is None or pick_score < best_pick_score:
                    best_pick_score = pick_score
                    chosen_entry = entry
                    chosen_meta = meta
            anchor_row = chosen_entry.get("row", {}) if isinstance(chosen_entry, dict) and isinstance(chosen_entry.get("row", {}), dict) else row
            anchor_meta = chosen_meta if isinstance(chosen_meta, dict) else (candidates[0] if candidates else {})
            row["verification_anchor_signature"] = str(anchor_meta.get("signature", "") or row.get("verification_anchor_signature", "") or "")
            row["verification_anchor_item_id"] = str(anchor_row.get("item_id", "") or "")
            row["verification_anchor_ref_object_id"] = str(anchor_row.get("ref_object_id", "") or "")
            row["verification_anchor_ref_object_type"] = str(anchor_row.get("ref_object_type", "") or "")
            row["verification_anchor_display"] = str(
                anchor_meta.get("display", "")
                or anchor_row.get("display", "")
                or row.get("display", "")
                or row.get("ref_object_id", "")
                or ""
            ).strip()
            row.pop("_verification_anchor_candidates", None)

        if pool_metric_totals:
            total_er = round(float(pool_metric_totals.get("total_er", 0.0) or 0.0), 8)
            total_ev = round(float(pool_metric_totals.get("total_ev", 0.0) or 0.0), 8)
            total_cp_delta = round(float(pool_metric_totals.get("total_cp_delta", 0.0) or 0.0), 8)
            total_cp_abs = round(float(pool_metric_totals.get("total_cp_abs", 0.0) or 0.0), 8)
        else:
            total_er = round(sum(float(r.get("er", 0.0) or 0.0) for r in pool_items), 8)
            total_ev = round(sum(float(r.get("ev", 0.0) or 0.0) for r in pool_items), 8)
            total_cp_delta = round(sum(float(r.get("cp_delta", 0.0) or 0.0) for r in pool_items), 8)
            total_cp_abs = round(sum(float(r.get("cp_abs", 0.0) or 0.0) for r in pool_items), 8)

        # Energy concentration (Herfindahl index on (er+ev)).
        # sanitized
        # sanitized
        # sanitized
        energies = (
            [max(0.0, float(e or 0.0)) for e in list(pool_metric_totals.get("energies", []) or [])]
            if pool_metric_totals
            else [max(0.0, float(r.get("total_energy", 0.0) or 0.0)) for r in pool_items]
        )
        e_sum = float(sum(energies))
        if e_sum > 1e-12:
            energy_concentration = round(sum((e / e_sum) ** 2 for e in energies if e > 1e-12), 8)
        else:
            energy_concentration = 0.0

        # Effective peak count (inverse Herfindahl), roughly interpretable as "number of peaks".
        # sanitized
        #
        # sanitized
        # sanitized
        if float(energy_concentration) > 1e-12:
            effective_peak_count = float(round(1.0 / float(energy_concentration), 8))
        else:
            effective_peak_count = 0.0

        # Core peak count: keep a structure-dominant view for positive/relief feelings.
        # Rationale:
        # - the full StatePool may contain a large SA tail (including residual/runtime shadow items),
        #   which is useful for "complexity/pressure" observability;
        # - but "simplicity" should not be permanently blocked just because many weak SA fragments
        #   are still alive in the pool.
        if pool_metric_totals:
            core_energies = [max(0.0, float(e or 0.0)) for e in list(pool_metric_totals.get("core_energies", []) or [])]
        else:
            core_peak_rows = [
                row
                for row in pool_items
                if str(row.get("ref_object_type", "") or "").strip().lower() in {"st", "sg"}
            ]
            if not core_peak_rows:
                core_peak_rows = [
                    row
                    for row in pool_items
                    if str(row.get("ref_object_type", "") or "").strip().lower() != "em"
                ]
            core_energies = [max(0.0, float(r.get("total_energy", 0.0) or 0.0)) for r in core_peak_rows]
        core_energy_sum = float(sum(core_energies))
        if core_energy_sum > 1e-12:
            core_energy_concentration = round(
                sum((e / core_energy_sum) ** 2 for e in core_energies if e > 1e-12),
                8,
            )
        else:
            core_energy_concentration = 0.0
        if float(core_energy_concentration) > 1e-12:
            core_effective_peak_count = float(round(1.0 / float(core_energy_concentration), 8))
        else:
            core_effective_peak_count = 0.0

        # ---- CAM (Current Attention Memory) ----
        # sanitized
        cam_size = 0
        cam_concentration = 0.0
        try:
            att = report.get("attention", {}) if isinstance(report.get("attention", {}), dict) else {}
            cam_size = int(att.get("memory_item_count", 0) or 0)
            cam_items = list(att.get("top_items", []) or [])
            cam_energies = []
            for it in cam_items:
                if not isinstance(it, dict):
                    continue
                # Prefer extracted memory energy if available; fall back to current er/ev.
                # sanitized
                er = float(it.get("memory_er", it.get("er", 0.0)) or 0.0)
                ev = float(it.get("memory_ev", it.get("ev", 0.0)) or 0.0)
                cam_energies.append(max(0.0, er) + max(0.0, ev))
            s = float(sum(cam_energies))
            if s > 1e-12:
                cam_concentration = float(round(sum((e / s) ** 2 for e in cam_energies if e > 1e-12), 8))
            else:
                cam_concentration = 0.0
        except Exception:
            cam_size = 0
            cam_concentration = 0.0

        # sanitized
        # sanitized
        # sanitized
        # sanitized
        # sanitized
        # sanitized
        #
        # sanitized
        # sanitized
        # sanitized
        # sanitized
        try:
            size_min = 6.0
            size_max = 24.0
            if size_max <= size_min:
                size_max = size_min + 1.0
            size_norm = (float(cam_size) - size_min) / (size_max - size_min)
            size_norm = max(0.0, min(1.0, float(size_norm)))

            peak_min = 1.0
            peak_max = 12.0
            if peak_max <= peak_min:
                peak_max = peak_min + 1.0
            peak_norm = (float(effective_peak_count) - peak_min) / (peak_max - peak_min)
            peak_norm = max(0.0, min(1.0, float(peak_norm)))

            # sanitized
            complexity_score = 0.55 * size_norm + 0.45 * peak_norm
            complexity_score = max(0.0, min(1.0, float(complexity_score)))
            complexity_score = float(round(complexity_score, 8))

            core_peak_norm = (float(core_effective_peak_count) - peak_min) / (peak_max - peak_min)
            core_peak_norm = max(0.0, min(1.0, float(core_peak_norm)))
            core_complexity_score = 0.55 * size_norm + 0.45 * core_peak_norm
            core_complexity_score = max(0.0, min(1.0, float(core_complexity_score)))
            core_complexity_score = float(round(core_complexity_score, 8))
        except Exception:
            complexity_score = 0.0
            core_complexity_score = 0.0

        # ---- Memory Activation Pool (MAP) ----
        # sanitized
        map_item_count = 0
        map_total_ev = 0.0
        try:
            snap = (report.get("memory_activation", {}) or {}).get("snapshot", {}) or {}
            items = list(snap.get("items", []) or [])
            map_item_count = len([x for x in items if isinstance(x, dict)])
            map_total_ev = float(((snap.get("summary", {}) or {}).get("total_ev", 0.0) or 0.0))
        except Exception:
            map_item_count = 0
            map_total_ev = 0.0

        # ---- stimulus metrics ----
        # Residual ratio: (after stimulus retrieval) / (before stimulus retrieval).
        # sanitized
        residual_ratio = 0.0
        try:
            before = report.get("cache_neutralization", {}).get("residual_packet", {}) or {}
            after = report.get("pool_apply", {}).get("landed_packet", {}) or {}
            before_total = float(before.get("total_er", 0.0) or 0.0) + float(before.get("total_ev", 0.0) or 0.0)
            after_total = float(after.get("total_er", 0.0) or 0.0) + float(after.get("total_ev", 0.0) or 0.0)
            residual_ratio = float(after_total / before_total) if before_total > 1e-12 else 0.0
        except Exception:
            residual_ratio = 0.0

        best_match_score = 0.0
        match_scores: dict[str, float] = {}
        best_match_target_id = ""
        best_match_target_display = ""
        match_displays: dict[str, str] = {}
        try:
            rounds = list(
                (report.get("stimulus_level", {}) or {})
                .get("result", {})
                .get("debug", {})
                .get("round_details", [])
                or []
            )
            for rd in rounds:
                if not isinstance(rd, dict):
                    continue
                sm = rd.get("selected_match") or {}
                if not isinstance(sm, dict):
                    continue
                score = float(sm.get("competition_score", sm.get("match_score", 0.0)) or 0.0)
                best_match_score = max(best_match_score, score)

                # Per-target match score map (best-effort).
                # sanitized
                sid = str(
                    sm.get("structure_id", "")
                    or sm.get("structure_db_id", "")
                    or sm.get("structure_signature", "")
                    or ""
                ).strip()
                if sid:
                    match_scores[sid] = max(float(match_scores.get(sid, 0.0) or 0.0), float(score))
            best_match_score = round(float(best_match_score), 8)
            if match_scores:
                best_match_target_id = max(match_scores.items(), key=lambda kv: float(kv[1] or 0.0))[0]

            # Best-effort: resolve display text for retrieval targets (st_*).
            # sanitized
            try:
                # Helper: structure_id -> display_text
                def _st_display(sid: str) -> str:
                    if not sid or not str(sid).startswith("st_"):
                        return ""
                    st_obj = self.hdb._structure_store.get(str(sid))  # type: ignore[attr-defined]
                    if not isinstance(st_obj, dict):
                        return ""
                    block = st_obj.get("structure", {}) if isinstance(st_obj.get("structure", {}), dict) else {}
                    return str(block.get("display_text", "") or sid)

                if best_match_target_id:
                    best_match_target_display = _st_display(best_match_target_id) or str(best_match_target_id)
                for sid in list(match_scores.keys()):
                    disp = _st_display(sid)
                    if disp:
                        match_displays[str(sid)] = disp
            except Exception:
                best_match_target_display = best_match_target_display or ""
                match_displays = match_displays or {}
        except Exception:
            best_match_score = 0.0
            match_scores = {}
            best_match_target_id = ""
            best_match_target_display = ""
            match_displays = {}

        # ---- structure-level retrieval metrics ----
        # sanitized
        #
        # sanitized
        # sanitized
        # sanitized
        # sanitized
        structure_best_match_score = 0.0
        structure_match_scores: dict[str, float] = {}
        structure_best_match_target_id = ""
        structure_best_match_target_display = ""
        structure_match_displays: dict[str, str] = {}
        try:
            rounds = list(
                (report.get("structure_level", {}) or {})
                .get("result", {})
                .get("debug", {})
                .get("round_details", [])
                or []
            )
            for rd in rounds:
                if not isinstance(rd, dict):
                    continue
                # Current HDB structure-level debug uses "selected_group" as the main selected record.
                # sanitized
                sel = rd.get("selected_group") or rd.get("selected_match") or {}
                if not isinstance(sel, dict):
                    continue
                try:
                    score = float(
                        sel.get("score", sel.get("competition_score", sel.get("match_score", 0.0)))
                        or 0.0
                    )
                except Exception:
                    score = 0.0
                structure_best_match_score = max(structure_best_match_score, score)

                gid = str(sel.get("group_id", "") or sel.get("id", "") or "").strip()
                if gid:
                    structure_match_scores[gid] = max(float(structure_match_scores.get(gid, 0.0) or 0.0), float(score))
            structure_best_match_score = round(float(structure_best_match_score), 8)
            if structure_match_scores:
                structure_best_match_target_id = max(structure_match_scores.items(), key=lambda kv: float(kv[1] or 0.0))[0]

            # Best-effort display for group ids (sg_*). GroupStore has no direct display_text,
            # so we keep a readable fallback: "sg_xxx" (future: derive from required structures).
            # sanitized
            if structure_best_match_target_id:
                structure_best_match_target_display = str(structure_best_match_target_id)
            for gid in list(structure_match_scores.keys()):
                if str(gid):
                    structure_match_displays[str(gid)] = str(gid)
        except Exception:
            structure_best_match_score = 0.0
            structure_match_scores = {}
            structure_best_match_target_id = ""
            structure_best_match_target_display = ""
            structure_match_displays = {}

        # sanitized
        # sanitized
        # sanitized
        # sanitized
        # sanitized
        # sanitized
        #
        # sanitized
        # sanitized
        # sanitized
        # sanitized
        # sanitized
        # sanitized
        # sanitized
        try:
            # sanitized
            # sanitized
            m_lo = 0.40
            m_hi = 0.95
            if m_hi <= m_lo:
                m_hi = m_lo + 1e-6
            match_norm = (float(best_match_score) - float(m_lo)) / (float(m_hi) - float(m_lo))
            match_norm = max(0.0, min(1.0, float(match_norm)))

            rr = float(residual_ratio)
            rr = max(0.0, min(1.0, rr))
            residual_complement = 1.0 - rr

            # sanitized
            # sanitized
            #
            # sanitized
            has_structure = bool(structure_match_scores) or float(structure_best_match_score) > 1e-9
            if has_structure:
                s_lo = 0.20
                s_hi = 0.90
                if s_hi <= s_lo:
                    s_hi = s_lo + 1e-6
                structure_norm = (float(structure_best_match_score) - float(s_lo)) / (float(s_hi) - float(s_lo))
                structure_norm = max(0.0, min(1.0, float(structure_norm)))
            else:
                structure_norm = 0.0

            # sanitized
            # sanitized
            # sanitized
            # sanitized
            best_row: dict[str, Any] | None = None
            if best_match_target_id:
                for row in pool_items:
                    if not isinstance(row, dict):
                        continue
                    rid = str(row.get("ref_object_id", "") or "").strip()
                    if rid and rid == str(best_match_target_id):
                        best_row = row
                        break
                    aliases = row.get("ref_alias_ids", [])
                    if isinstance(aliases, list) and str(best_match_target_id) in {str(x) for x in aliases if str(x)}:
                        best_row = row
                        break

            ev_stability = 0.0
            ev_coverage = 0.0
            cp_relief = 0.0
            if best_row:
                # sanitized
                best_ev = float(best_row.get("ev", 0.0) or 0.0)
                best_ev_rate = float(best_row.get("ev_change_rate", best_row.get("delta_ev", 0.0)) or 0.0)
                rel = abs(best_ev_rate) / max(1e-6, abs(best_ev))
                k_rel = 0.35  # 闂佸憡顨呴敃銊╁灳濠婂懍鐒婇柛婵嗗椤斿﹪鏌ㄥ☉娆樺姇el=k 闂佸搫鍟晶搴ゅ綂闁诲氦顫夌喊宥夊焵椤戭兘鍋撳?.5闂佹寧绋戦悧鍡氥亹閺屻儱瑙﹂幖杈剧悼閺侀箖鏌熺粙娆炬█闁绘稒鐟╁銊╂嚋閸偅顔嶉梺纭咁嚃閸犳盯鎯冮悢鐓庣煑闁稿矉濡囩粈?
                ev_stability = 1.0 / (1.0 + (rel / max(1e-9, k_rel)))
                ev_stability = max(0.0, min(1.0, float(ev_stability)))

                # sanitized
                ev_sum = max(1e-9, float(total_ev))
                ev_coverage = float(best_ev) / float(ev_sum)
                ev_coverage = max(0.0, min(1.0, float(ev_coverage)))

                # sanitized
                cp_abs_rate = float(best_row.get("cp_abs_rate", best_row.get("delta_cp_abs", 0.0)) or 0.0)
                relief = max(0.0, -cp_abs_rate)
                # Softcap to (0,1): relief/(relief+k)
                k_relief = 0.30
                cp_relief = float(relief / (relief + max(1e-9, k_relief))) if relief > 0.0 else 0.0
                cp_relief = max(0.0, min(1.0, float(cp_relief)))

            # sanitized
            # sanitized
            # sanitized
            # sanitized
            if has_structure:
                grasp_score = (
                    0.30 * match_norm
                    + 0.25 * residual_complement
                    + 0.15 * structure_norm
                    + 0.15 * ev_stability
                    + 0.10 * ev_coverage
                    + 0.05 * cp_relief
                )
            else:
                grasp_score = (
                    0.35 * match_norm
                    + 0.30 * residual_complement
                    + 0.15 * ev_stability
                    + 0.10 * ev_coverage
                    + 0.10 * cp_relief
                )

            grasp_score = max(0.0, min(1.0, float(grasp_score)))
            grasp_score = float(round(grasp_score, 8))
        except Exception:
            grasp_score = 0.0

        # Also store these metrics into report for observability (best-effort).
        # sanitized
        try:
            stim_res = (report.get("stimulus_level", {}) or {}).get("result", {})
            if isinstance(stim_res, dict):
                metrics = stim_res.setdefault("metrics", {})
                if isinstance(metrics, dict):
                    metrics["residual_ratio"] = round(float(residual_ratio), 8)
                    metrics["best_match_score"] = round(float(best_match_score), 8)
                    metrics["grasp_score"] = round(float(grasp_score), 8)
                    metrics["match_score_target_count"] = len(match_scores)
                    metrics["best_match_target_id"] = str(best_match_target_id or "")
        except Exception:
            pass

        # Also store structure-level match metrics for observability (best-effort).
        # sanitized
        try:
            st_res = (report.get("structure_level", {}) or {}).get("result", {})
            if isinstance(st_res, dict):
                metrics = st_res.setdefault("metrics", {})
                if isinstance(metrics, dict):
                    metrics["best_match_score"] = round(float(structure_best_match_score), 8)
                    metrics["match_score_target_count"] = len(structure_match_scores)
                    metrics["best_match_target_id"] = str(structure_best_match_target_id or "")
        except Exception:
            pass

        # ---- emotion ----
        nt_state: dict[str, float] = {}
        if isinstance(emotion_state, dict) and isinstance(emotion_state.get("nt_state_after"), dict):
            nt_state = {str(k): float(v) for k, v in (emotion_state.get("nt_state_after") or {}).items() if str(k)}
        else:
            # Snapshot from EMgr (previous tick state).
            try:
                snap = self.emotion.get_emotion_snapshot(trace_id=f"{trace_id}_emotion_snapshot_for_rules").get("data", {}) or {}
                channels = (snap.get("nt_state_snapshot", {}) or {}).get("channels", {}) or {}
                if isinstance(channels, dict):
                    for ch, row in channels.items():
                        if not str(ch):
                            continue
                        if isinstance(row, dict) and "value" in row:
                            nt_state[str(ch)] = float(row.get("value", 0.0) or 0.0)
            except Exception:
                nt_state = {}

        # Expand NT aliases for readability (Chinese-first).
        # sanitized
        # sanitized
        # sanitized
        try:
            snap = self.emotion.get_emotion_snapshot(trace_id=f"{trace_id}_emotion_labels_for_rules").get("data", {}) or {}
            labels = snap.get("nt_channel_labels", {}) if isinstance(snap.get("nt_channel_labels", {}), dict) else {}
            if labels:
                for ch, v in list(nt_state.items()):
                    lab = str(labels.get(ch, "") or "").strip()
                    if not lab:
                        continue
                    # sanitized
                    if lab not in nt_state:
                        nt_state[lab] = float(v)
                    # sanitized
                    short = lab.split("(", 1)[0].strip()
                    if short and short not in nt_state:
                        nt_state[short] = float(v)
        except Exception:
            pass

        # sanitized
        # ----------------------------------------------------
        # sanitized
        # sanitized
        # sanitized
        # sanitized
        #
        # sanitized
        # sanitized
        override_snapshot = emotion_state.get("rwd_pun_snapshot") if isinstance(emotion_state, dict) else None
        if isinstance(override_snapshot, dict):
            rwd = float(override_snapshot.get("rwd", 0.0) or 0.0)
            pun = float(override_snapshot.get("pun", 0.0) or 0.0)
            rwd_pun_source = str(
                (emotion_state or {}).get("rwd_pun_source", "")
                or override_snapshot.get("source", "")
                or "state_override"
            )
            rwd_pun_detail = {}
            override_detail = (emotion_state or {}).get("rwd_pun_detail") if isinstance(emotion_state, dict) else None
            if isinstance(override_detail, dict):
                rwd_pun_detail.update(dict(override_detail))
        else:
            rwd_pun_pool = self._estimate_rwd_pun_from_pool_items(pool_items, trace_id=trace_id, tick_id=tick_id)
            rwd = float(rwd_pun_pool.get("rwd", 0.0) or 0.0)
            pun = float(rwd_pun_pool.get("pun", 0.0) or 0.0)
            rwd_pun_source = str(rwd_pun_pool.get("source", "") or "pool_items")
            rwd_pun_detail = dict(rwd_pun_pool.get("detail", {}) or {}) if isinstance(rwd_pun_pool.get("detail", {}), dict) else {}

        return {
            "pool": {
                "total_er": total_er,
                "total_ev": total_ev,
                "total_energy": round(float(total_er) + float(total_ev), 8),
                "item_count": int(pool_metric_totals.get("item_count", len(pool_items)) if pool_metric_totals else len(pool_items)),
                "context_item_count": len(pool_items),
                "context_item_limit": int(pool_metric_totals.get("context_item_limit", 0) or 0) if pool_metric_totals else 0,
                "total_cp_delta": total_cp_delta,
                "total_cp_abs": total_cp_abs,
                "energy_concentration": float(energy_concentration),
                "effective_peak_count": float(effective_peak_count),
                "complexity_score": float(complexity_score),
                "core_energy_concentration": float(core_energy_concentration),
                "core_effective_peak_count": float(core_effective_peak_count),
                "core_complexity_score": float(core_complexity_score),
            },
            "pool_items": pool_items,
            "cam": {"size": int(cam_size), "energy_concentration": float(cam_concentration)},
            "memory_activation": {"item_count": int(map_item_count), "total_ev": float(map_total_ev)},
            "emotion": {
                "nt": nt_state,
                "rwd": float(rwd),
                "pun": float(pun),
                "rwd_pun_source": str(rwd_pun_source or "pool_items"),
                "rwd_pun_detail": dict(rwd_pun_detail),
            },
            "stimulus": {
                "residual_ratio": round(float(residual_ratio), 8),
                "input_has_text": int(input_has_text),
                "input_is_empty": int(input_is_empty),
                "input_is_user": int(current_input_flags["input_is_user"]),
                "input_is_assistant": int(current_input_flags["input_is_assistant"]),
                "input_is_system": int(current_input_flags["input_is_system"]),
                "input_is_message": int(current_input_flags["input_is_message"]),
                "input_is_reply": int(current_input_flags["input_is_reply"]),
                "input_is_session_restore": int(current_input_flags["input_is_session_restore"]),
            },
            "retrieval": {
                "stimulus": {
                    "best_match_score": round(float(best_match_score), 8),
                    "grasp_score": round(float(grasp_score), 8),
                    "best_match_target_id": str(best_match_target_id or ""),
                    "best_match_target_display": str(best_match_target_display or ""),
                    # match_scores: {target_id -> score}. Target id is typically structure_id/st_*.
                    # sanitized
                    "match_scores": dict(match_scores),
                    "match_displays": dict(match_displays),
                }
                ,
                "structure": {
                    "best_match_score": round(float(structure_best_match_score), 8),
                    "best_match_target_id": str(structure_best_match_target_id or ""),
                    "best_match_target_display": str(structure_best_match_target_display or ""),
                    # match_scores: {group_id -> score}. Target id is typically sg_*.
                    # sanitized
                    "match_scores": dict(structure_match_scores),
                    "match_displays": dict(structure_match_displays),
                },
            },
            "meta": {"trace_id": trace_id, "tick_id": tick_id, "built_at_ms": int(time.time() * 1000)},
        }

    def _build_lightweight_iesm_state_window_check(self, packet: dict[str, Any], *, stage: str) -> dict[str, Any]:
        summary = packet.get("summary", {}) if isinstance(packet.get("summary", {}), dict) else {}
        triggered_scripts: list[dict[str, Any]] = []
        fast_rise_count = int(summary.get("fast_cp_rise_item_count", 0) or 0)
        fast_drop_count = int(summary.get("fast_cp_drop_item_count", 0) or 0)
        if fast_rise_count > 0:
            triggered_scripts.append(
                {
                    "script_id": "innate_state_window_cp_rise",
                    "script_kind": "window_trigger",
                    "priority": 50,
                    "trigger": "fast_cp_rise",
                    "trigger_count": fast_rise_count,
                }
            )
        if fast_drop_count > 0:
            triggered_scripts.append(
                {
                    "script_id": "innate_state_window_cp_drop",
                    "script_kind": "window_trigger",
                    "priority": 50,
                    "trigger": "fast_cp_drop",
                    "trigger_count": fast_drop_count,
                }
            )
        return {
            "script_version": str(getattr(self.iesm, "_config", {}).get("script_version", "")),
            "triggered_scripts": triggered_scripts,
            "directives": {},
            "audit": {
                "lightweight_runtime_observability": True,
                "stage": str(stage or ""),
                "reason": "duplicate dry check_state_window skipped; run_tick_rules evaluates real effects",
                "packet_summary": dict(summary),
            },
            "triggered_rules": [],
        }

    # ================================================================== #
    # Reward/Punish Aggregation                                            #
    # sanitized
    # ================================================================== #

    @staticmethod
    def _clamp01(x: float) -> float:
        try:
            v = float(x)
        except Exception:
            v = 0.0
        return max(0.0, min(1.0, v))

    @staticmethod
    def _softcap(x: float, *, k: float) -> float:
        """
        Soft-saturating mapping x -> x/(x+k).
        # sanitized
        """
        try:
            v = float(x)
        except Exception:
            v = 0.0
        k = max(1e-9, float(k))
        if v <= 0.0:
            return 0.0
        return float(v / (v + k))

    @staticmethod
    def _row_has_bound_attribute(row: dict[str, Any], attr_name: str) -> bool:
        """doc"""
        if not isinstance(row, dict) or not attr_name:
            return False
        names = row.get("bound_attribute_names", [])
        if isinstance(names, list):
            for name in names:
                if str(name) == attr_name:
                    return True
        displays = row.get("bound_attribute_displays", []) or []
        if not displays:
            return False
        hay = " ".join(str(x) for x in displays if str(x))
        return attr_name in hay

    def _row_attribute_strength(self, row: dict[str, Any], attr_name: str, *, fallback: float = 1.0) -> float:
        """Best-effort attribute strength for reward/punish aggregation and local action bias."""
        if not isinstance(row, dict):
            return 0.0
        target = str(attr_name or "").strip()
        if not target:
            return 0.0
        try:
            fallback_value = max(0.0, float(fallback or 0.0))
        except Exception:
            fallback_value = 1.0

        strengths: list[float] = []

        def _push_strength(value: Any) -> None:
            try:
                num = float(value)
            except Exception:
                return
            if num < 0.0:
                return
            strengths.append(num)

        unit_sources: list[Any] = []
        unit_sources.append(row.get("runtime_bound_attribute_units", []))
        ref_snapshot = row.get("ref_snapshot", {}) if isinstance(row.get("ref_snapshot", {}), dict) else {}
        unit_sources.append(ref_snapshot.get("runtime_bound_attribute_units", []))
        for units in unit_sources:
            if not isinstance(units, list):
                continue
            for unit in units:
                if not isinstance(unit, dict):
                    continue
                unit_name = str(unit.get("attribute_name", "") or "").strip()
                if unit_name != target:
                    continue
                raw_value = unit.get("attribute_value", None)
                if raw_value in ("", None):
                    _push_strength(fallback_value)
                else:
                    _push_strength(raw_value)

        self_attr_name = str(row.get("attribute_name", ref_snapshot.get("attribute_name", "")) or "").strip()
        if self_attr_name == target:
            self_attr_value = row.get("attribute_value", ref_snapshot.get("attribute_value", None))
            if self_attr_value in ("", None):
                _push_strength(fallback_value)
            else:
                _push_strength(self_attr_value)

        if strengths:
            return round(min(2.0, max(strengths)), 8)
        if self._row_has_bound_attribute(row, target):
            return round(fallback_value, 8)
        return 0.0

    def _select_teacher_feedback_context_carriers(
        self,
        *,
        report: dict[str, Any] | None,
        ref_object_types: list[str] | None,
        exclude_item_id: str = "",
        exclude_ref_object_id: str = "",
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        att = (report or {}).get("attention", {}) if isinstance((report or {}).get("attention", {}), dict) else {}
        top_items = [row for row in list(att.get("top_items", []) or []) if isinstance(row, dict)]
        allowed_types = {str(x).strip() for x in (ref_object_types or []) if str(x).strip()}
        try:
            limit = int(
                top_k
                if top_k is not None
                else (self._config.get("teacher_feedback_focus_context_carrier_top_k", 1) or 1)
            )
        except Exception:
            limit = 1
        limit = max(0, min(8, limit))
        if limit <= 0:
            return []
        rows: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for row in top_items:
            row_ref_type = str(row.get("ref_object_type", "") or "").strip()
            if row_ref_type != "st":
                continue
            if allowed_types and row_ref_type not in allowed_types:
                continue
            row_ref_id = str(row.get("ref_object_id", "") or "").strip()
            row_item_id = str(row.get("item_id", "") or "").strip()
            if (exclude_ref_object_id and row_ref_id == exclude_ref_object_id) or (
                exclude_item_id and row_item_id == exclude_item_id
            ):
                continue
            carrier_key = row_ref_id or row_item_id
            if not carrier_key or carrier_key in seen_keys:
                continue
            seen_keys.add(carrier_key)
            rows.append(dict(row))
            if len(rows) >= limit:
                break
        return rows

    def _is_teacher_feedback_atomic_target(
        self,
        *,
        target_item_id: str,
        target_row: dict[str, Any] | None = None,
    ) -> bool:
        item = None
        if target_item_id:
            try:
                item = self.pool._store.get(target_item_id)  # type: ignore[attr-defined]
            except Exception:
                item = None
        row = item if isinstance(item, dict) else (target_row if isinstance(target_row, dict) else {})
        ref_type = str(row.get("ref_object_type", "") or row.get("object_type", "") or "").strip()
        if ref_type == "sa":
            return True
        ref_snapshot = row.get("ref_snapshot", {}) if isinstance(row.get("ref_snapshot", {}), dict) else {}
        flat_tokens = [str(token) for token in (ref_snapshot.get("flat_tokens", []) or []) if str(token)]
        if len(flat_tokens) == 1:
            return True
        try:
            token_count = int(ref_snapshot.get("token_count", 0) or 0)
        except Exception:
            token_count = 0
        if token_count == 1:
            return True
        groups = [dict(group) for group in (ref_snapshot.get("sequence_groups", []) or []) if isinstance(group, dict)]
        if len(groups) != 1:
            return False
        units = [dict(unit) for unit in (groups[0].get("units", []) or []) if isinstance(unit, dict)]
        if len(units) == 1:
            return True
        tokens = [str(token) for token in (groups[0].get("tokens", []) or []) if str(token)]
        return len(tokens) == 1

    def _append_focus_directives(self, directives: list[dict[str, Any]] | None) -> int:
        rows = [row for row in (directives or []) if isinstance(row, dict)]
        if not rows:
            return 0
        existing_by_id = {
            str(item.get("directive_id", "")): item
            for item in self._pending_focus_directives
            if isinstance(item, dict) and str(item.get("directive_id", ""))
        }
        merged = 0
        for directive in rows:
            directive_id = str(directive.get("directive_id", "") or "").strip()
            if not directive_id:
                continue
            existing_by_id[directive_id] = directive
            merged += 1
        self._pending_focus_directives = list(existing_by_id.values())
        return int(merged)

    def _build_teacher_feedback_focus_directives(
        self,
        *,
        teacher_rwd: float,
        teacher_pun: float,
        target_item_id: str,
        target_row: dict[str, Any] | None,
        report: dict[str, Any] | None,
        applied_count: int,
        mode: str,
        anchor: str,
        resolve_reason: str,
        tick_id: str,
        ref_object_types: list[str] | None,
        context_carrier_rows: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        if not bool(self._config.get("teacher_feedback_focus_directive_enabled", True)):
            return []
        if applied_count <= 0 or (teacher_rwd <= 0.0 and teacher_pun <= 0.0):
            return []
        row = target_row if isinstance(target_row, dict) else {}
        ref_object_id = str(row.get("ref_object_id", "") or "").strip()
        ref_object_type = str(row.get("ref_object_type", "") or "").strip()
        item_id = str(target_item_id or row.get("item_id", "") or "").strip()
        if not item_id and not ref_object_id:
            return []
        strength_scale = max(0.0, float(self._config.get("teacher_feedback_focus_strength_scale", 1.0) or 0.0))
        signal_strength = self._clamp01(max(0.0, max(float(teacher_rwd or 0.0), float(teacher_pun or 0.0))) * strength_scale)
        if signal_strength <= 0.0:
            return []
        focus_boost = max(0.0, float(self._config.get("teacher_feedback_focus_boost", 1.2) or 0.0))
        if focus_boost <= 0.0:
            return []
        try:
            ttl_ticks = int(self._config.get("teacher_feedback_focus_ttl_ticks", 2) or 2)
        except Exception:
            ttl_ticks = 2
        ttl_ticks = max(1, min(64, ttl_ticks))
        target_key = ref_object_id or item_id
        reasons: list[str] = ["teacher_feedback", f"anchor:{anchor}", f"resolve:{resolve_reason}"]
        if teacher_rwd > 0.0:
            reasons.append("teacher_reward_signal")
        if teacher_pun > 0.0:
            reasons.append("teacher_punish_signal")
        directives: list[dict[str, Any]] = []
        directive = {
            "directive_id": f"teacher_feedback_focus_{target_key}_{tick_id}",
            "directive_type": "attention_focus",
            "source_kind": "teacher_feedback",
            "strength": round(float(signal_strength), 6),
            "focus_boost": round(float(focus_boost), 6),
            "ttl_ticks": int(ttl_ticks),
            "target_ref_object_id": ref_object_id,
            "target_ref_object_type": ref_object_type,
            "target_item_id": item_id,
            "target_display": str(row.get("display", "") or ""),
            "created_at": int(time.time() * 1000),
            "teacher_rwd": round(float(max(0.0, teacher_rwd)), 8),
            "teacher_pun": round(float(max(0.0, teacher_pun)), 8),
            "mode": str(mode or ""),
            "anchor": str(anchor or ""),
            "resolve_reason": str(resolve_reason or ""),
            "reasons": reasons,
        }
        directives.append(directive)

        if bool(self._config.get("teacher_feedback_focus_context_carrier_enabled", True)):
            try:
                carrier_top_k = int(self._config.get("teacher_feedback_focus_context_carrier_top_k", 1) or 1)
            except Exception:
                carrier_top_k = 1
            carrier_top_k = max(0, min(8, carrier_top_k))
            carrier_scale = max(
                0.0,
                float(self._config.get("teacher_feedback_focus_context_carrier_strength_scale", 0.85) or 0.0),
            )
            carrier_strength = self._clamp01(signal_strength * carrier_scale)
            carrier_rows = [dict(row) for row in (context_carrier_rows or []) if isinstance(row, dict)]
            if not carrier_rows:
                carrier_rows = self._select_teacher_feedback_context_carriers(
                    report=report,
                    ref_object_types=ref_object_types,
                    exclude_item_id=item_id,
                    exclude_ref_object_id=ref_object_id,
                    top_k=carrier_top_k,
                )
            carrier_count = 0
            for row in carrier_rows:
                row_ref_type = str(row.get("ref_object_type", "") or "").strip()
                row_ref_id = str(row.get("ref_object_id", "") or "").strip()
                row_item_id = str(row.get("item_id", "") or "").strip()
                if (row_ref_id and row_ref_id == ref_object_id) or (row_item_id and row_item_id == item_id):
                    continue
                if carrier_strength <= 0.0:
                    break
                carrier_key = row_ref_id or row_item_id
                if not carrier_key:
                    continue
                directives.append(
                    {
                        "directive_id": f"teacher_feedback_context_focus_{carrier_key}_{tick_id}",
                        "directive_type": "attention_focus",
                        "source_kind": "teacher_feedback_context_carrier",
                        "strength": round(float(carrier_strength), 6),
                        "focus_boost": round(float(focus_boost), 6),
                        "ttl_ticks": int(ttl_ticks),
                        "target_ref_object_id": row_ref_id,
                        "target_ref_object_type": row_ref_type,
                        "target_item_id": row_item_id,
                        "target_display": str(row.get("display", "") or ""),
                        "created_at": int(time.time() * 1000),
                        "teacher_rwd": round(float(max(0.0, teacher_rwd)), 8),
                        "teacher_pun": round(float(max(0.0, teacher_pun)), 8),
                        "mode": str(mode or ""),
                        "anchor": str(anchor or ""),
                        "resolve_reason": str(resolve_reason or ""),
                        "reasons": [
                            "teacher_feedback_context_carrier",
                            f"anchor:{anchor}",
                            f"resolve:{resolve_reason}",
                            f"carrier_from_attention:{carrier_key}",
                        ],
                    }
                )
                carrier_count += 1
                if carrier_count >= carrier_top_k:
                    break
        return directives

    # ================================================================== #
    # Teacher Feedback (External Reward/Punish)                           #
    # sanitized
    # ================================================================== #

    def _apply_teacher_feedback(
        self,
        *,
        labels: dict[str, Any] | None,
        report: dict[str, Any] | None,
        trace_id: str,
        tick_id: str,
    ) -> dict[str, Any]:
        """
        Apply external teacher feedback to the runtime StatePool.

        Goals / 闂佺儵鏅╅崰妤呮偉閿濆鏅?
        # sanitized
        # sanitized
        # sanitized

        # sanitized
        - teacher_rwd / teacher_pun: float in [0,1]
        - teacher_anchor: cam_top1 | pool_top1_total | pool_top1_total_any | specific_item | specific_ref | none
        - teacher_anchor_item_id / teacher_anchor_ref_object_id / teacher_anchor_ref_object_type
        - teacher_anchor_ref_object_types: ['st', 'sa', ...] (default ['st'])
        - tool_feedback_rwd / tool_feedback_pun: aliases for teacher_rwd/pun (for tool experiments)
        """
        labels = labels if isinstance(labels, dict) else {}
        report = report if isinstance(report, dict) else {}

        # Allow a nested "teacher" dict, but keep top-level keys as the stable protocol.
        teacher = labels.get("teacher") if isinstance(labels.get("teacher"), dict) else {}

        def _pick(keys: list[str], *, default: Any = None) -> Any:
            for k in keys:
                if k in teacher:
                    return teacher.get(k)
                if k in labels:
                    return labels.get(k)
            return default

        def _as_float(v: Any) -> float:
            try:
                return float(v)
            except Exception:
                return 0.0

        teacher_rwd = self._clamp01(_as_float(_pick(["teacher_rwd", "tool_feedback_rwd", "rwd"], default=0.0)))
        teacher_pun = self._clamp01(_as_float(_pick(["teacher_pun", "tool_feedback_pun", "pun"], default=0.0)))
        mode = str(_pick(["teacher_mode", "mode"], default="bind_attribute") or "bind_attribute").strip() or "bind_attribute"

        anchor = str(_pick(["teacher_anchor", "anchor"], default="pool_top1_total") or "pool_top1_total").strip() or "pool_top1_total"
        if anchor == "pool_top1":
            anchor = "pool_top1_total"
        if anchor == "pool_top1_any":
            anchor = "pool_top1_total_any"

        allow_types = _pick(["teacher_anchor_ref_object_types", "ref_object_types"], default=None)
        ref_object_types: list[str] = []
        if isinstance(allow_types, list):
            ref_object_types = [str(x) for x in allow_types if str(x).strip()]
        if not ref_object_types:
            ref_object_types = ["st"]

        explicit_item_id = str(_pick(["teacher_anchor_item_id", "item_id"], default="") or "").strip()
        explicit_ref_id = str(_pick(["teacher_anchor_ref_object_id", "ref_object_id"], default="") or "").strip()
        explicit_ref_type = str(_pick(["teacher_anchor_ref_object_type", "ref_object_type"], default="") or "").strip()
        contains_text = str(_pick(["teacher_anchor_contains_text", "contains_text"], default="") or "").strip()
        note = str(_pick(["teacher_note", "note", "teacher_reason", "reason"], default="") or "").strip()

        # Early exit: no feedback provided.
        if teacher_rwd <= 0.0 and teacher_pun <= 0.0:
            return {
                "ok": True,
                "mode": mode,
                "anchor": anchor,
                "teacher_rwd": 0.0,
                "teacher_pun": 0.0,
                "applied_count": 0,
                "applied": [],
                "message": "no teacher feedback on this tick",
            }

        if anchor in {"none", "off", "disabled"}:
            return {
                "ok": True,
                "mode": mode,
                "anchor": anchor,
                "teacher_rwd": round(float(teacher_rwd), 8),
                "teacher_pun": round(float(teacher_pun), 8),
                "applied_count": 0,
                "applied": [],
                "message": "teacher feedback ignored by anchor policy",
            }

        # ---- Resolve target ----
        target_item_id = ""
        target_row: dict[str, Any] = {}
        resolve_reason = ""

        # (1) Specific item id
        if explicit_item_id:
            it = self.pool._store.get(explicit_item_id)  # type: ignore[attr-defined]
            if isinstance(it, dict):
                target_item_id = explicit_item_id
                try:
                    target_row = self.pool._snapshot._build_top_item_summary(it)  # type: ignore[attr-defined]
                except Exception:
                    target_row = {}
                resolve_reason = "specific_item"

        # (2) Specific ref id
        if not target_item_id and explicit_ref_id:
            it = self.pool._store.get_by_ref(explicit_ref_id)  # type: ignore[attr-defined]
            if isinstance(it, dict):
                if explicit_ref_type and str(it.get("ref_object_type", "")) != explicit_ref_type:
                    pass
                else:
                    target_item_id = str(it.get("id", "") or "")
                    try:
                        target_row = self.pool._snapshot._build_top_item_summary(it)  # type: ignore[attr-defined]
                    except Exception:
                        target_row = {}
                    resolve_reason = "specific_ref"

        # (3) CAM top1
        if not target_item_id and anchor == "cam_top1":
            att = report.get("attention", {}) if isinstance(report.get("attention", {}), dict) else {}
            top_items = list(att.get("top_items", []) or [])
            for r in top_items:
                if not isinstance(r, dict):
                    continue
                if ref_object_types and str(r.get("ref_object_type", "")) not in set(ref_object_types):
                    continue
                iid = str(r.get("item_id", "") or "").strip()
                if iid:
                    target_item_id = iid
                    target_row = dict(r)
                    resolve_reason = "cam_top1"
                    break

        # (4) Contains text
        if not target_item_id and (contains_text or anchor.startswith("contains_text")):
            needle = contains_text
            if not needle and ":" in anchor:
                needle = anchor.split(":", 1)[1].strip()
            if needle:
                # Use a cheap scan on the live pool store.
                try:
                    all_items = list(self.pool._store.get_all())  # type: ignore[attr-defined]
                except Exception:
                    all_items = []
                for it in all_items:
                    if not isinstance(it, dict):
                        continue
                    try:
                        row = self.pool._snapshot._build_top_item_summary(it)  # type: ignore[attr-defined]
                    except Exception:
                        continue
                    if not isinstance(row, dict):
                        continue
                    if ref_object_types and str(row.get("ref_object_type", "")) not in set(ref_object_types):
                        continue
                    hay = " ".join(
                        [
                            str(row.get("display", "") or ""),
                            str(row.get("display_detail", "") or ""),
                            " ".join(str(x) for x in (row.get("attribute_displays", []) or []) if str(x)),
                            " ".join(str(x) for x in (row.get("feature_displays", []) or []) if str(x)),
                            " ".join(str(x) for x in (row.get("bound_attribute_displays", []) or []) if str(x)),
                        ]
                    )
                    if needle in hay or needle.lower() in hay.lower():
                        target_item_id = str(row.get("item_id", "") or "")
                        target_row = dict(row)
                        resolve_reason = f"contains_text:{needle}"
                        break

        # (5) Default: pool top1 by total_energy
        if not target_item_id and anchor in {"pool_top1_total", "pool_top1_total_any"}:
            prefer_any = anchor == "pool_top1_total_any"
            try:
                all_items = list(self.pool._store.get_all())  # type: ignore[attr-defined]
            except Exception:
                all_items = []
            best_it: dict[str, Any] | None = None
            best_total = -1.0
            allow = set(ref_object_types)
            for it in all_items:
                if not isinstance(it, dict):
                    continue
                if (not prefer_any) and allow and str(it.get("ref_object_type", "")) not in allow:
                    continue
                e = it.get("energy", {}) if isinstance(it.get("energy", {}), dict) else {}
                try:
                    total = float(e.get("er", 0.0) or 0.0) + float(e.get("ev", 0.0) or 0.0)
                except Exception:
                    total = 0.0
                if total > best_total:
                    best_total = total
                    best_it = it
            if best_it is not None:
                target_item_id = str(best_it.get("id", "") or "")
                try:
                    target_row = self.pool._snapshot._build_top_item_summary(best_it)  # type: ignore[attr-defined]
                except Exception:
                    target_row = {}
                resolve_reason = f"{anchor}:top_by_total_energy"

        if not target_item_id:
            return {
                "ok": False,
                "mode": mode,
                "anchor": anchor,
                "teacher_rwd": round(float(teacher_rwd), 8),
                "teacher_pun": round(float(teacher_pun), 8),
                "ref_object_types": list(ref_object_types),
                "applied_count": 0,
                "applied": [],
                "message": "teacher feedback provided but no anchor target found",
                "resolve_reason": resolve_reason or "no_target",
            }

        # ---- Apply bindings ----
        primary_target_atomic = self._is_teacher_feedback_atomic_target(target_item_id=target_item_id, target_row=target_row)
        focus_carrier_enabled = bool(self._config.get("teacher_feedback_focus_context_carrier_enabled", True))
        context_binding_enabled = bool(self._config.get("teacher_feedback_context_binding_enabled", True))
        context_binding_only_when_primary_atomic = bool(
            self._config.get("teacher_feedback_context_binding_only_when_primary_atomic", True)
        )
        try:
            focus_carrier_top_k = int(self._config.get("teacher_feedback_focus_context_carrier_top_k", 1) or 1)
        except Exception:
            focus_carrier_top_k = 1
        focus_carrier_top_k = max(0, min(8, focus_carrier_top_k))
        try:
            context_binding_top_k = int(self._config.get("teacher_feedback_context_binding_top_k", 1) or 1)
        except Exception:
            context_binding_top_k = 1
        context_binding_top_k = max(0, min(8, context_binding_top_k))
        context_binding_scale = max(
            0.0,
            float(self._config.get("teacher_feedback_context_binding_strength_scale", 0.85) or 0.0),
        )
        context_binding_reason = "disabled"
        should_bind_context = bool(context_binding_enabled)
        if not context_binding_enabled:
            context_binding_reason = "disabled"
        elif context_binding_only_when_primary_atomic and not primary_target_atomic:
            should_bind_context = False
            context_binding_reason = "primary_not_atomic"
        elif context_binding_scale <= 0.0:
            should_bind_context = False
            context_binding_reason = "scale_non_positive"
        elif context_binding_top_k <= 0:
            should_bind_context = False
            context_binding_reason = "top_k_zero"
        else:
            context_binding_reason = "eligible"

        max_context_top_k = 0
        if focus_carrier_enabled:
            max_context_top_k = max(max_context_top_k, focus_carrier_top_k)
        if should_bind_context:
            max_context_top_k = max(max_context_top_k, context_binding_top_k)
        context_carrier_rows_all: list[dict[str, Any]] = []
        if max_context_top_k > 0:
            context_carrier_rows_all = self._select_teacher_feedback_context_carriers(
                report=report,
                ref_object_types=ref_object_types,
                exclude_item_id=target_item_id,
                exclude_ref_object_id=str(target_row.get("ref_object_id", "") or ""),
                top_k=max_context_top_k,
            )
        context_binding_rows = context_carrier_rows_all[:context_binding_top_k] if should_bind_context else []
        if should_bind_context and not context_binding_rows and context_binding_reason == "eligible":
            context_binding_reason = "no_context_carrier"
        focus_directive_carrier_rows = context_carrier_rows_all[:focus_carrier_top_k] if focus_carrier_enabled else []

        primary_applied: list[dict[str, Any]] = []
        context_applied: list[dict[str, Any]] = []
        primary_ref_object_id = str(target_row.get("ref_object_id", "") or "")

        def bind_attr(
            *,
            bind_target_item_id: str,
            bind_target_row: dict[str, Any],
            attr_name: str,
            attr_value: float,
            display: str,
            binding_kind: str,
            binding_scale: float = 1.0,
            carrier_rank: int = 0,
            record_bucket: list[dict[str, Any]],
        ) -> None:
            target_ref_id = str(bind_target_row.get("ref_object_id", "") or bind_target_item_id)
            attr_id = f"sa_teacher_attr_{attr_name}_{target_ref_id}"
            scaled_attr_value = max(0.0, float(attr_value) * max(0.0, float(binding_scale)))
            try:
                attr_er = max(
                    0.0,
                    float(scaled_attr_value) * float(self._config.get("teacher_feedback_attribute_er_scale", 1.0) or 0.0),
                )
            except Exception:
                attr_er = max(0.0, float(scaled_attr_value))
            try:
                attr_ev = max(
                    0.0,
                    float(scaled_attr_value) * float(self._config.get("teacher_feedback_attribute_ev_scale", 0.0) or 0.0),
                )
            except Exception:
                attr_ev = 0.0
            attr_er = round(float(attr_er), 8)
            attr_ev = round(float(attr_ev), 8)
            attribute_sa = {
                "id": attr_id,
                "object_type": "sa",
                "content": {
                    "raw": f"{attr_name}:{round(float(scaled_attr_value), 8)}",
                    "display": display,
                    "value_type": "numerical",
                    "attribute_name": attr_name,
                    "attribute_value": round(float(scaled_attr_value), 8),
                },
                "stimulus": {"role": "attribute", "modality": "external"},
                "energy": {"er": attr_er, "ev": attr_ev},
                "meta": {
                    "ext": {
                        "bound_from": "teacher_feedback",
                        "trace_id": trace_id,
                        "tick_id": tick_id,
                        "mode": mode,
                        "anchor": anchor,
                        "resolve_reason": resolve_reason,
                        "note": note,
                        "energy_update_mode": "set",
                        "binding_kind": binding_kind,
                        "binding_scale": round(float(binding_scale), 8),
                        "primary_target_item_id": target_item_id,
                        "primary_target_ref_object_id": primary_ref_object_id,
                        "carrier_rank": int(carrier_rank),
                    }
                },
            }
            res = self.pool.bind_attribute_node_to_object(
                target_item_id=bind_target_item_id,
                attribute_sa=attribute_sa,
                trace_id=f"{trace_id}_teacher_bind_attr",
                tick_id=tick_id,
                source_module=("teacher_feedback" if binding_kind == "primary" else "teacher_feedback_context_binding"),
                reason=f"teacher_feedback:{binding_kind}:{attr_name}",
            )
            record_bucket.append(
                {
                    "attribute_name": attr_name,
                    "attribute_sa_id": attr_id,
                    "target_item_id": bind_target_item_id,
                    "target_ref_object_id": target_ref_id,
                    "target_display": str(bind_target_row.get("display", "") or ""),
                    "binding_kind": binding_kind,
                    "binding_scale": round(float(binding_scale), 8),
                    "carrier_rank": int(carrier_rank),
                    "success": bool(res.get("success", False)),
                    "code": str(res.get("code", "") or ""),
                    "data": res.get("data", {}) if isinstance(res.get("data", {}), dict) else {},
                }
            )

        if teacher_rwd > 0.0:
            bind_attr(
                bind_target_item_id=target_item_id,
                bind_target_row=target_row,
                attr_name="teacher_reward_signal",
                attr_value=teacher_rwd,
                display="teacher_reward_signal",
                binding_kind="primary",
                binding_scale=1.0,
                record_bucket=primary_applied,
            )
        if teacher_pun > 0.0:
            bind_attr(
                bind_target_item_id=target_item_id,
                bind_target_row=target_row,
                attr_name="teacher_punish_signal",
                attr_value=teacher_pun,
                display="teacher_punish_signal",
                binding_kind="primary",
                binding_scale=1.0,
                record_bucket=primary_applied,
            )
        if context_binding_rows:
            for carrier_rank, carrier_row in enumerate(context_binding_rows, start=1):
                carrier_item_id = str(carrier_row.get("item_id", "") or "").strip()
                if not carrier_item_id:
                    continue
                if teacher_rwd > 0.0:
                    bind_attr(
                        bind_target_item_id=carrier_item_id,
                        bind_target_row=carrier_row,
                        attr_name="teacher_reward_signal",
                        attr_value=teacher_rwd,
                        display="teacher_reward_signal",
                        binding_kind="context_carrier",
                        binding_scale=context_binding_scale,
                        carrier_rank=carrier_rank,
                        record_bucket=context_applied,
                    )
                if teacher_pun > 0.0:
                    bind_attr(
                        bind_target_item_id=carrier_item_id,
                        bind_target_row=carrier_row,
                        attr_name="teacher_punish_signal",
                        attr_value=teacher_pun,
                        display="teacher_punish_signal",
                        binding_kind="context_carrier",
                        binding_scale=context_binding_scale,
                        carrier_rank=carrier_rank,
                        record_bucket=context_applied,
                    )
        applied = primary_applied + context_applied
        focus_directives = self._build_teacher_feedback_focus_directives(
            teacher_rwd=teacher_rwd,
            teacher_pun=teacher_pun,
            target_item_id=target_item_id,
            target_row=target_row,
            report=report,
            applied_count=len(applied),
            mode=mode,
            anchor=anchor,
            resolve_reason=resolve_reason,
            tick_id=tick_id,
            ref_object_types=list(ref_object_types),
            context_carrier_rows=focus_directive_carrier_rows,
        )
        local_alias_summary = self._record_teacher_local_feedback_aliases(
            teacher_feedback={"teacher_rwd": teacher_rwd, "teacher_pun": teacher_pun},
            applied_rows=applied,
            current_tick=int(self.tick_counter),
            tick_id=tick_id,
        )

        return {
            "ok": True,
            "mode": mode,
            "anchor": anchor,
            "teacher_rwd": round(float(teacher_rwd), 8),
            "teacher_pun": round(float(teacher_pun), 8),
            "ref_object_types": list(ref_object_types),
            "resolve_reason": resolve_reason,
            "target": {
                "item_id": target_item_id,
                "ref_object_id": str(target_row.get("ref_object_id", "") or ""),
                "ref_object_type": str(target_row.get("ref_object_type", "") or ""),
                "display": str(target_row.get("display", "") or ""),
            },
            "applied_count": len(primary_applied),
            "applied": primary_applied[:8],
            "total_binding_applied_count": len(applied),
            "primary_applied_count": len(primary_applied),
            "primary_target_atomic": bool(primary_target_atomic),
            "context_binding_enabled": bool(context_binding_enabled),
            "context_binding_only_when_primary_atomic": bool(context_binding_only_when_primary_atomic),
            "context_binding_scale": round(float(context_binding_scale), 8),
            "context_binding_reason": str(context_binding_reason or ""),
            "context_binding_candidate_count": len(context_binding_rows),
            "context_binding_applied_count": len(context_applied),
            "context_binding_applied": context_applied[:8],
            "context_binding_targets": [
                {
                    "item_id": str(row.get("item_id", "") or ""),
                    "ref_object_id": str(row.get("ref_object_id", "") or ""),
                    "ref_object_type": str(row.get("ref_object_type", "") or ""),
                    "display": str(row.get("display", "") or ""),
                }
                for row in context_binding_rows[:8]
                if isinstance(row, dict)
            ],
            "focus_directive_enabled": bool(self._config.get("teacher_feedback_focus_directive_enabled", True)),
            "focus_directive_count": len(focus_directives),
            "focus_context_carrier_count": len(
                [row for row in focus_directives if str(row.get("source_kind", "") or "") == "teacher_feedback_context_carrier"]
            ),
            "focus_directives": focus_directives[:8],
            "local_feedback_alias_cache": local_alias_summary,
        }

    def _upsert_runtime_projection_object(
        self,
        *,
        runtime_object: dict[str, Any],
        target_er: float,
        target_ev: float,
        trace_id: str,
        tick_id: str,
        source_module: str,
        reason: str,
        skip_create_when_zero: bool = True,
    ) -> dict[str, Any]:
        ref_id = str(runtime_object.get("id", "") or "").strip()
        if not ref_id:
            return {"ok": False, "code": "MISSING_ID", "ref_id": ""}

        target_er = max(0.0, float(target_er or 0.0))
        target_ev = max(0.0, float(target_ev or 0.0))
        if skip_create_when_zero and target_er <= 0.0 and target_ev <= 0.0:
            existing = None
            try:
                existing = self.pool._store.get_by_ref(ref_id)  # type: ignore[attr-defined]
            except Exception:
                existing = None
            if not isinstance(existing, dict):
                return {
                    "ok": True,
                    "code": "SKIP_ZERO_CREATE",
                    "ref_id": ref_id,
                    "target_er": round(float(target_er), 8),
                    "target_ev": round(float(target_ev), 8),
                }

        existing = None
        try:
            existing = self.pool._store.get_by_ref(ref_id)  # type: ignore[attr-defined]
        except Exception:
            existing = None

        if isinstance(existing, dict) and str(existing.get("id", "") or "").strip():
            before_er = max(0.0, float(existing.get("energy", {}).get("er", 0.0) or 0.0))
            before_ev = max(0.0, float(existing.get("energy", {}).get("ev", 0.0) or 0.0))
            update = self.pool.apply_energy_update(
                target_item_id=str(existing.get("id", "") or ""),
                delta_er=round(float(target_er) - float(before_er), 8),
                delta_ev=round(float(target_ev) - float(before_ev), 8),
                trace_id=f"{trace_id}_reward_action_sync_update",
                tick_id=tick_id,
                reason=reason,
                source_module=source_module,
            )
            data = update.get("data", {}) if isinstance(update.get("data", {}), dict) else {}
            return {
                "ok": bool(update.get("success", False)),
                "code": str(update.get("code", "") or ""),
                "operation": "set_existing",
                "ref_id": ref_id,
                "item_id": str(existing.get("id", "") or ""),
                "target_er": round(float(target_er), 8),
                "target_ev": round(float(target_ev), 8),
                "after": dict(data.get("after", {}) or {}),
            }

        obj = copy.deepcopy(runtime_object)
        obj["energy"] = {
            **dict(obj.get("energy", {}) or {}),
            "er": round(float(target_er), 8),
            "ev": round(float(target_ev), 8),
        }
        insert = self.pool.insert_runtime_node(
            runtime_object=obj,
            trace_id=f"{trace_id}_reward_action_sync_insert",
            tick_id=tick_id,
            allow_merge=True,
            source_module=source_module,
            reason=reason,
        )
        data = insert.get("data", {}) if isinstance(insert.get("data", {}), dict) else {}
        return {
            "ok": bool(insert.get("success", False)),
            "code": str(insert.get("code", "") or ""),
            "operation": "insert_or_merge",
            "ref_id": ref_id,
            "item_id": str(data.get("item_id", data.get("target_item_id", "")) or ""),
            "target_er": round(float(target_er), 8),
            "target_ev": round(float(target_ev), 8),
        }

    def _build_reward_action_signal_runtime_object(self, *, signal_name: str, display: str, trace_id: str, tick_id: str) -> dict[str, Any]:
        return {
            "id": str(signal_name),
            "object_type": "sa",
            "content": {
                "raw": str(signal_name),
                "display": str(display),
                "normalized": str(signal_name),
                "value_type": "discrete",
            },
            "stimulus": {
                "role": "meta_signal",
                "modality": "internal",
            },
            "energy": {"er": 0.0, "ev": 0.0},
            "source": {
                "module": "observatory",
                "interface": "reward_action_runtime_sync",
                "origin": "reward_action_global_signal",
                "origin_id": tick_id,
                "parent_ids": [],
            },
            "trace_id": trace_id,
            "tick_id": tick_id,
            "ext": {
                "reward_action_humanlike_v2": True,
                "signal_name": str(signal_name),
                "signal_scope": "global",
            },
            "meta": {
                "ext": {
                    "reward_action_humanlike_v2": True,
                    "signal_name": str(signal_name),
                    "signal_scope": "global",
                }
            },
        }

    def _action_kind_title(self, action_kind: str) -> str:
        kind = str(action_kind or "").strip()
        registry = list(getattr(self.action, "_executor_registry", []) or [])
        for row in registry:
            if not isinstance(row, dict):
                continue
            if str(row.get("action_kind", "") or "").strip() == kind:
                return str(row.get("title_zh", "") or kind or "action")
        return kind or "action"

    def _build_action_runtime_object(self, *, node: dict[str, Any], trace_id: str, tick_id: str) -> dict[str, Any]:
        action_id = str(node.get("action_id", "") or "").strip()
        action_kind = str(node.get("action_kind", "") or "").strip() or "action"
        target_ref_object_id = str(node.get("target_ref_object_id", "") or "").strip()
        target_ref_object_type = str(node.get("target_ref_object_type", "") or "").strip()
        target_item_id = str(node.get("target_item_id", "") or "").strip()
        target_display = str(node.get("target_display", "") or "").strip()
        display_title = self._action_kind_title(action_kind)
        content_display = f"行动节点:{display_title}"
        if target_display:
            content_display = f"{content_display}@{target_display}"
        return {
            "id": f"action::{action_id}",
            "object_type": "action_node",
            "sub_type": action_kind,
            "content": {
                "raw": f"{action_kind}:{action_id}",
                "display": content_display,
                "normalized": f"action_node|{action_kind}|{action_id}",
                "value_type": "discrete",
            },
            "energy": {"er": 0.0, "ev": 0.0},
            "source": {
                "module": "observatory",
                "interface": "reward_action_runtime_sync",
                "origin": "action_runtime_projection",
                "origin_id": tick_id,
                "parent_ids": [],
            },
            "trace_id": trace_id,
            "tick_id": tick_id,
            "ext": {
                "reward_action_humanlike_v2": True,
                "action_id": action_id,
                "action_kind": action_kind,
                "target_ref_object_id": target_ref_object_id,
                "target_ref_object_type": target_ref_object_type,
                "target_item_id": target_item_id,
                "target_display": target_display,
                "drive_hint": round(float(node.get("drive", 0.0) or 0.0), 8),
                "consumed_drive_hint": round(float(node.get("last_consumed_drive", 0.0) or 0.0), 8),
                "effective_threshold": round(float(node.get("effective_threshold", 0.0) or 0.0), 8),
                "threshold_scale": round(float(node.get("threshold_scale", 1.0) or 1.0), 8),
            },
            "meta": {
                "ext": {
                    "reward_action_humanlike_v2": True,
                    "action_id": action_id,
                    "action_kind": action_kind,
                    "target_ref_object_id": target_ref_object_id,
                    "target_ref_object_type": target_ref_object_type,
                    "target_item_id": target_item_id,
                    "target_display": target_display,
                    "drive_hint": round(float(node.get("drive", 0.0) or 0.0), 8),
                    "consumed_drive_hint": round(float(node.get("last_consumed_drive", 0.0) or 0.0), 8),
                    "effective_threshold": round(float(node.get("effective_threshold", 0.0) or 0.0), 8),
                    "threshold_scale": round(float(node.get("threshold_scale", 1.0) or 1.0), 8),
                }
            },
        }

    def _sync_reward_action_runtime_nodes(
        self,
        *,
        emotion_data: dict[str, Any],
        action_data: dict[str, Any],
        trace_id: str,
        tick_id: str,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "enabled": bool(self._config.get("reward_action_humanlike_v2_enabled", True)),
            "signal_nodes_enabled": bool(self._config.get("reward_action_runtime_signal_nodes_enabled", True)),
            "action_nodes_enabled": bool(self._config.get("reward_action_runtime_action_nodes_enabled", True)),
            "signal_nodes": [],
            "action_nodes": [],
            "summary": {},
        }
        if not bool(self._config.get("reward_action_humanlike_v2_enabled", True)):
            result["summary"] = {"reason": "config_disabled"}
            return result

        signal_rows: list[dict[str, Any]] = []
        if bool(self._config.get("reward_action_runtime_signal_nodes_enabled", True)):
            snapshot = emotion_data.get("rwd_pun_snapshot", {}) if isinstance(emotion_data.get("rwd_pun_snapshot", {}), dict) else {}
            signal_er_scale = max(0.0, float(self._config.get("reward_action_runtime_signal_er_scale", 0.0) or 0.0))
            signal_ev_scale = max(0.0, float(self._config.get("reward_action_runtime_signal_ev_scale", 1.0) or 0.0))
            for signal_name, label_zh, key in (
                ("reward_signal", "奖励信号（全局）", "rwd"),
                ("punish_signal", "惩罚信号（全局）", "pun"),
            ):
                value = max(0.0, float(snapshot.get(key, 0.0) or 0.0))
                row = self._upsert_runtime_projection_object(
                    runtime_object=self._build_reward_action_signal_runtime_object(
                        signal_name=signal_name,
                        display=f"{label_zh}:{round(float(value), 3)}",
                        trace_id=trace_id,
                        tick_id=tick_id,
                    ),
                    target_er=float(value) * float(signal_er_scale),
                    target_ev=float(value) * float(signal_ev_scale),
                    trace_id=trace_id,
                    tick_id=tick_id,
                    source_module="observatory",
                    reason=f"reward_action_runtime_signal:{signal_name}",
                    skip_create_when_zero=True,
                )
                row["signal_name"] = signal_name
                row["source_value"] = round(float(value), 8)
                signal_rows.append(row)

        action_rows: list[dict[str, Any]] = []
        if bool(self._config.get("reward_action_runtime_action_nodes_enabled", True)):
            nodes = [row for row in (action_data.get("nodes", []) or []) if isinstance(row, dict)]
            nodes.sort(key=lambda row: float(row.get("drive", 0.0) or 0.0), reverse=True)
            max_sync = max(1, int(self._config.get("reward_action_runtime_action_node_max_sync", 24) or 24))
            drive_to_ev_scale = max(0.0, float(self._config.get("reward_action_runtime_action_node_drive_to_ev_scale", 1.0) or 0.0))
            execute_to_er_scale = max(0.0, float(self._config.get("reward_action_runtime_action_node_execute_to_er_scale", 1.0) or 0.0))
            consumed_by_action_id: dict[str, float] = {}
            for row in (action_data.get("executed_actions", []) or []):
                if not isinstance(row, dict):
                    continue
                action_id = str(row.get("action_id", "") or "").strip()
                if not action_id:
                    continue
                consumed = max(0.0, float(row.get("consumed_drive", 0.0) or 0.0))
                consumed_by_action_id[action_id] = max(float(consumed_by_action_id.get(action_id, 0.0) or 0.0), float(consumed))

            for node in nodes[:max_sync]:
                action_id = str(node.get("action_id", "") or "").strip()
                if not action_id:
                    continue
                drive = max(0.0, float(node.get("drive", 0.0) or 0.0))
                consumed = max(
                    float(consumed_by_action_id.get(action_id, 0.0) or 0.0),
                    max(0.0, float(node.get("last_consumed_drive", 0.0) or 0.0)),
                )
                row = self._upsert_runtime_projection_object(
                    runtime_object=self._build_action_runtime_object(node=node, trace_id=trace_id, tick_id=tick_id),
                    target_er=float(consumed) * float(execute_to_er_scale),
                    target_ev=float(drive) * float(drive_to_ev_scale),
                    trace_id=trace_id,
                    tick_id=tick_id,
                    source_module="observatory",
                    reason=f"reward_action_runtime_action_node:{action_id}",
                    skip_create_when_zero=True,
                )
                row["action_id"] = action_id
                row["action_kind"] = str(node.get("action_kind", "") or "")
                row["drive"] = round(float(drive), 8)
                row["consumed_drive"] = round(float(consumed), 8)
                row["target_ref_object_id"] = str(node.get("target_ref_object_id", "") or "")
                row["target_item_id"] = str(node.get("target_item_id", "") or "")
                action_rows.append(row)

        result["signal_nodes"] = signal_rows
        result["action_nodes"] = action_rows
        result["summary"] = {
            "signal_node_count": int(len(signal_rows)),
            "signal_node_active_count": int(sum(1 for row in signal_rows if float(row.get("source_value", 0.0) or 0.0) > 0.0)),
            "action_node_count": int(len(action_rows)),
            "action_node_active_count": int(sum(1 for row in action_rows if float(row.get("drive", 0.0) or 0.0) > 0.0)),
            "action_node_executed_count": int(sum(1 for row in action_rows if float(row.get("consumed_drive", 0.0) or 0.0) > 0.0)),
            "action_target_ref_count": int(len({str(row.get("target_ref_object_id", "") or "") for row in action_rows if str(row.get("target_ref_object_id", "") or "")})),
            "action_target_item_count": int(len({str(row.get("target_item_id", "") or "") for row in action_rows if str(row.get("target_item_id", "") or "")})),
        }
        return result

    def _estimate_rwd_pun_from_pool_items(self, pool_items: list[dict[str, Any]], *, trace_id: str, tick_id: str) -> dict[str, Any]:
        """
        Estimate global reward/punish signals from pool_items.
        # sanitized

        # sanitized
        # sanitized
        # sanitized
        # sanitized

        # sanitized
        # sanitized
        # sanitized
        """
        cfg = getattr(self.emotion, "_config", {}) or {}
        agg = cfg.get("rwd_pun_pool_aggregation", {}) if isinstance(cfg.get("rwd_pun_pool_aggregation", {}), dict) else {}

        reward_attr = str(agg.get("reward_attr_name", "reward_signal") or "reward_signal").strip() or "reward_signal"
        punish_attr = str(agg.get("punish_attr_name", "punish_signal") or "punish_signal").strip() or "punish_signal"
        ev_min = float(agg.get("ev_min", 0.0) or 0.0)
        attr_weight_enabled = bool(agg.get("attribute_value_weight_enabled", True))
        attr_weight_fallback = float(agg.get("attribute_value_fallback", 1.0) or 1.0)

        rwd_pred_ev = 0.0
        pun_pred_ev = 0.0
        rwd_got_er = 0.0
        pun_got_er = 0.0

        for row in pool_items or []:
            if not isinstance(row, dict):
                continue
            ev = float(row.get("ev", 0.0) or 0.0)
            der = float(row.get("delta_er", 0.0) or 0.0)
            reward_strength = (
                self._row_attribute_strength(row, reward_attr, fallback=attr_weight_fallback)
                if attr_weight_enabled
                else (1.0 if self._row_has_bound_attribute(row, reward_attr) else 0.0)
            )
            punish_strength = (
                self._row_attribute_strength(row, punish_attr, fallback=attr_weight_fallback)
                if attr_weight_enabled
                else (1.0 if self._row_has_bound_attribute(row, punish_attr) else 0.0)
            )
            if reward_strength > 0.0:
                if ev >= ev_min:
                    rwd_pred_ev += max(0.0, ev) * float(reward_strength)
                if der > 0.0:
                    rwd_got_er += der * float(reward_strength)
            if punish_strength > 0.0:
                if ev >= ev_min:
                    pun_pred_ev += max(0.0, ev) * float(punish_strength)
                if der > 0.0:
                    pun_got_er += der * float(punish_strength)

        k_pred = float(agg.get("k_pred", 1.0) or 1.0)
        k_got = float(agg.get("k_got", 0.5) or 0.5)
        w_pred = float(agg.get("w_pred", 0.7) or 0.7)
        w_got = float(agg.get("w_got", 0.3) or 0.3)
        w_sum = max(1e-9, abs(w_pred) + abs(w_got))
        w_pred = w_pred / w_sum
        w_got = w_got / w_sum

        rwd = self._clamp01(w_pred * self._softcap(rwd_pred_ev, k=k_pred) + w_got * self._softcap(rwd_got_er, k=k_got))
        pun = self._clamp01(w_pred * self._softcap(pun_pred_ev, k=k_pred) + w_got * self._softcap(pun_got_er, k=k_got))

        return {
            "rwd": round(float(rwd), 8),
            "pun": round(float(pun), 8),
            "source": "pool_items",
            "detail": {
                "reward_attr_name": reward_attr,
                "punish_attr_name": punish_attr,
                "ev_min": ev_min,
                "rwd_pred_ev_sum": round(float(rwd_pred_ev), 8),
                "pun_pred_ev_sum": round(float(pun_pred_ev), 8),
                "rwd_got_er_sum": round(float(rwd_got_er), 8),
                "pun_got_er_sum": round(float(pun_got_er), 8),
                "attribute_value_weight_enabled": bool(attr_weight_enabled),
                "attribute_value_fallback": round(float(attr_weight_fallback), 8),
                "k_pred": k_pred,
                "k_got": k_got,
                "w_pred": round(float(w_pred), 6),
                "w_got": round(float(w_got), 6),
            },
        }

    def _teacher_local_alias_normalized_text(self, text: Any) -> str:
        normalizer = getattr(getattr(self, "action", None), "_normalize_local_feedback_text", None)
        if callable(normalizer):
            try:
                return str(normalizer(text) or "")
            except Exception:
                pass
        raw = str(text or "").strip().lower()
        if not raw:
            return ""
        try:
            import re as _re

            raw = _re.sub(r"[a-z_][a-z0-9_\-]*:[0-9.]+", "", raw)
            fragments = _re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", raw)
            return "".join(fragments).strip() if fragments else raw.strip()
        except Exception:
            return raw.strip()

    def _teacher_local_alias_text_score(self, *, target_display: str, candidate_display: str) -> float:
        scorer = getattr(getattr(self, "action", None), "_score_local_feedback_text_similarity", None)
        if callable(scorer):
            try:
                return self._clamp01(float(scorer(target_display=target_display, candidate_display=candidate_display)))
            except Exception:
                pass
        target_norm = self._teacher_local_alias_normalized_text(target_display)
        candidate_norm = self._teacher_local_alias_normalized_text(candidate_display)
        if not target_norm or not candidate_norm:
            return 0.0
        if target_norm == candidate_norm or target_norm in candidate_norm or candidate_norm in target_norm:
            return 1.0
        return self._clamp01(float(len(set(target_norm) & set(candidate_norm))) / float(max(1, len(set(target_norm)))))

    def _teacher_local_alias_current_input_display(self, report: dict[str, Any] | None) -> str:
        report = report if isinstance(report, dict) else {}
        input_queue = report.get("input_queue", {}) if isinstance(report.get("input_queue", {}), dict) else {}
        sensor = report.get("sensor", {}) if isinstance(report.get("sensor", {}), dict) else {}
        for value in (
            input_queue.get("source_text", ""),
            input_queue.get("tick_text", ""),
            sensor.get("input_text", ""),
            sensor.get("normalized_text", ""),
        ):
            text = str(value or "").strip()
            if text:
                return text
        return ""

    def _prune_teacher_local_feedback_alias_cache(self, *, current_tick: int) -> None:
        if not isinstance(getattr(self, "_teacher_local_feedback_alias_cache", None), list):
            self._teacher_local_feedback_alias_cache = []
        kept: list[dict[str, Any]] = []
        for entry in self._teacher_local_feedback_alias_cache:
            if not isinstance(entry, dict):
                continue
            try:
                expires_at = int(entry.get("expires_at_tick", 0) or 0)
            except Exception:
                expires_at = 0
            if expires_at >= int(current_tick):
                kept.append(entry)
        try:
            max_entries = int(self._config.get("teacher_feedback_local_alias_cache_max_entries", 64) or 64)
        except Exception:
            max_entries = 64
        max_entries = max(0, min(1024, max_entries))
        if max_entries > 0 and len(kept) > max_entries:
            kept.sort(key=lambda row: int(row.get("created_tick", 0) or 0), reverse=True)
            kept = kept[:max_entries]
            kept.sort(key=lambda row: int(row.get("created_tick", 0) or 0))
        self._teacher_local_feedback_alias_cache = kept

    def _record_teacher_local_feedback_aliases(
        self,
        *,
        teacher_feedback: dict[str, Any] | None,
        applied_rows: list[dict[str, Any]] | None = None,
        current_tick: int,
        tick_id: str,
    ) -> dict[str, Any]:
        enabled = bool(self._config.get("teacher_feedback_local_alias_cache_enabled", True))
        summary: dict[str, Any] = {
            "enabled": bool(enabled),
            "created_count": 0,
            "active_count": len(getattr(self, "_teacher_local_feedback_alias_cache", []) or []),
        }
        if not enabled:
            return summary
        teacher_feedback = teacher_feedback if isinstance(teacher_feedback, dict) else {}
        try:
            ttl_ticks = int(self._config.get("teacher_feedback_local_alias_cache_ttl_ticks", 6) or 6)
        except Exception:
            ttl_ticks = 6
        ttl_ticks = max(1, min(256, ttl_ticks))
        try:
            min_chars = int(self._config.get("teacher_feedback_local_alias_cache_min_chars", 6) or 6)
        except Exception:
            min_chars = 6
        min_chars = max(1, min(256, min_chars))
        teacher_rwd = max(0.0, float(teacher_feedback.get("teacher_rwd", 0.0) or 0.0))
        teacher_pun = max(0.0, float(teacher_feedback.get("teacher_pun", 0.0) or 0.0))
        if teacher_rwd <= 0.0 and teacher_pun <= 0.0:
            summary["reason"] = "no_teacher_signal"
            return summary

        self._prune_teacher_local_feedback_alias_cache(current_tick=int(current_tick))
        rows = [row for row in (applied_rows or []) if isinstance(row, dict)]
        if not rows:
            rows = []
            rows.extend([row for row in (teacher_feedback.get("applied", []) or []) if isinstance(row, dict)])
            rows.extend([row for row in (teacher_feedback.get("context_binding_applied", []) or []) if isinstance(row, dict)])
        created: list[dict[str, Any]] = []
        for row in rows:
            if not bool(row.get("success", False)):
                continue
            attr_name = str(row.get("attribute_name", "") or "").strip()
            if attr_name not in {"teacher_reward_signal", "teacher_punish_signal"}:
                continue
            binding_scale = max(0.0, float(row.get("binding_scale", 1.0) or 0.0))
            rwd = self._clamp01(float(teacher_rwd) * float(binding_scale)) if attr_name == "teacher_reward_signal" else 0.0
            pun = self._clamp01(float(teacher_pun) * float(binding_scale)) if attr_name == "teacher_punish_signal" else 0.0
            if rwd <= 0.0 and pun <= 0.0:
                continue
            display = str(row.get("target_display", "") or "").strip()
            if not display:
                display = str(row.get("target_ref_object_id", "") or row.get("target_item_id", "") or "").strip()
            normalized = self._teacher_local_alias_normalized_text(display)
            if len(normalized) < min_chars:
                continue
            alias_id = f"teacher_local_alias_{int(current_tick):06d}_{len(self._teacher_local_feedback_alias_cache) + len(created) + 1:04d}"
            created.append(
                {
                    "alias_id": alias_id,
                    "created_tick": int(current_tick),
                    "available_from_tick": int(current_tick) + 1,
                    "expires_at_tick": int(current_tick) + ttl_ticks,
                    "tick_id": str(tick_id or ""),
                    "attribute_name": attr_name,
                    "rwd": round(float(rwd), 8),
                    "pun": round(float(pun), 8),
                    "display": display,
                    "normalized_text": normalized,
                    "source_target_item_id": str(row.get("target_item_id", "") or ""),
                    "source_target_ref_object_id": str(row.get("target_ref_object_id", "") or ""),
                    "binding_kind": str(row.get("binding_kind", "") or ""),
                    "binding_scale": round(float(binding_scale), 8),
                }
            )
        if created:
            self._teacher_local_feedback_alias_cache.extend(created)
            self._prune_teacher_local_feedback_alias_cache(current_tick=int(current_tick))
        summary.update(
            {
                "created_count": int(len(created)),
                "active_count": int(len(self._teacher_local_feedback_alias_cache)),
                "ttl_ticks": int(ttl_ticks),
                "min_chars": int(min_chars),
                "created_aliases": [
                    {
                        "alias_id": row.get("alias_id", ""),
                        "attribute_name": row.get("attribute_name", ""),
                        "rwd": row.get("rwd", 0.0),
                        "pun": row.get("pun", 0.0),
                        "available_from_tick": row.get("available_from_tick", 0),
                        "expires_at_tick": row.get("expires_at_tick", 0),
                        "source_target_ref_object_id": row.get("source_target_ref_object_id", ""),
                    }
                    for row in created[:8]
                ],
            }
        )
        return summary

    def _overlay_teacher_local_feedback_alias_cache(
        self,
        local_map: dict[str, Any] | None,
        *,
        report: dict[str, Any] | None,
        current_tick: int,
        tick_id: str,
    ) -> dict[str, Any]:
        enabled = bool(self._config.get("teacher_feedback_local_alias_cache_enabled", True))
        summary: dict[str, Any] = {
            "enabled": bool(enabled),
            "active_count": 0,
            "available_count": 0,
            "matched_count": 0,
            "overlay_applied_count": 0,
        }
        if not isinstance(local_map, dict):
            summary["reason"] = "invalid_local_map"
            return summary
        if not enabled:
            summary["reason"] = "config_disabled"
            return summary
        if not bool(local_map.get("enabled", False)):
            summary["reason"] = "local_map_disabled"
            return summary

        self._prune_teacher_local_feedback_alias_cache(current_tick=int(current_tick))
        active_entries = [row for row in self._teacher_local_feedback_alias_cache if isinstance(row, dict)]
        summary["active_count"] = int(len(active_entries))
        if not active_entries:
            summary["reason"] = "empty_cache"
            return summary

        current_display = self._teacher_local_alias_current_input_display(report)
        current_norm = self._teacher_local_alias_normalized_text(current_display)
        try:
            min_chars = int(self._config.get("teacher_feedback_local_alias_cache_min_chars", 6) or 6)
        except Exception:
            min_chars = 6
        min_chars = max(1, min(256, min_chars))
        if len(current_norm) < min_chars:
            summary["reason"] = "current_input_too_short_or_empty"
            summary["current_input_norm_len"] = int(len(current_norm))
            return summary
        try:
            min_score = float(self._config.get("teacher_feedback_local_alias_cache_min_score", 0.55) or 0.55)
        except Exception:
            min_score = 0.55
        min_score = self._clamp01(min_score)

        candidates: list[tuple[float, int, float, dict[str, Any]]] = []
        for entry in active_entries:
            try:
                available_from = int(entry.get("available_from_tick", 0) or 0)
                expires_at = int(entry.get("expires_at_tick", 0) or 0)
            except Exception:
                continue
            if int(current_tick) < available_from or int(current_tick) > expires_at:
                continue
            summary["available_count"] = int(summary.get("available_count", 0) or 0) + 1
            score = self._teacher_local_alias_text_score(
                target_display=current_display,
                candidate_display=str(entry.get("display", "") or ""),
            )
            if score < min_score:
                continue
            signal_mag = max(0.0, float(entry.get("rwd", 0.0) or 0.0)) + max(0.0, float(entry.get("pun", 0.0) or 0.0))
            candidates.append((float(score), int(entry.get("created_tick", 0) or 0), float(signal_mag), entry))
        summary["matched_count"] = int(len(candidates))
        summary["min_score"] = round(float(min_score), 8)
        if not candidates:
            summary["reason"] = "no_alias_above_threshold"
            return summary

        # Prefer semantic match first, then the most recent teacher supervision.
        # Recency before magnitude prevents an older reward from outvoting a newer
        # punishment just because its numeric value is slightly larger.
        candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        best_score, _created_tick, _signal_mag, best = candidates[0]
        alias_ref_id = f"teacher_local_alias::{best.get('alias_id', '')}"
        payload = {
            "rwd": round(max(0.0, float(best.get("rwd", 0.0) or 0.0)), 8),
            "pun": round(max(0.0, float(best.get("pun", 0.0) or 0.0)), 8),
            "display": str(best.get("display", "") or ""),
            "detail": {
                "source": "teacher_local_feedback_alias_cache",
                "alias_id": str(best.get("alias_id", "") or ""),
                "alias_attribute_name": str(best.get("attribute_name", "") or ""),
                "alias_created_tick": int(best.get("created_tick", 0) or 0),
                "alias_available_from_tick": int(best.get("available_from_tick", 0) or 0),
                "alias_expires_at_tick": int(best.get("expires_at_tick", 0) or 0),
                "alias_match_score": round(float(best_score), 8),
                "source_target_ref_object_id": str(best.get("source_target_ref_object_id", "") or ""),
                "source_target_item_id": str(best.get("source_target_item_id", "") or ""),
                "tick_id": str(best.get("tick_id", "") or ""),
            },
        }
        by_ref = local_map.get("by_ref", {}) if isinstance(local_map.get("by_ref", {}), dict) else {}
        # Put the matched alias first so action text-fallback sees it even when a
        # large local map would otherwise hit the max-candidates cap.
        local_map["by_ref"] = {alias_ref_id: payload, **by_ref}
        summary.update(
            {
                "overlay_applied_count": 1,
                "overlay_ref_id": alias_ref_id,
                "overlay_rwd": payload["rwd"],
                "overlay_pun": payload["pun"],
                "overlay_match_score": round(float(best_score), 8),
                "overlay_source_target_ref_object_id": str(best.get("source_target_ref_object_id", "") or ""),
            }
        )
        map_summary = local_map.get("summary", {}) if isinstance(local_map.get("summary", {}), dict) else {}
        map_summary.update(
            {
                "teacher_local_alias_active_count": int(summary.get("active_count", 0) or 0),
                "teacher_local_alias_available_count": int(summary.get("available_count", 0) or 0),
                "teacher_local_alias_matched_count": int(summary.get("matched_count", 0) or 0),
                "teacher_local_alias_overlay_applied_count": 1,
                "teacher_local_alias_overlay_ref_id": alias_ref_id,
            }
        )
        local_map["summary"] = map_summary
        return summary

    def _build_local_rwd_pun_map_from_pool_items(self, pool_items: list[dict[str, Any]], *, trace_id: str, tick_id: str) -> dict[str, Any]:
        cfg = getattr(self.action, "_config", {}) or {}
        enabled = bool(cfg.get("local_drive_modulation_by_rwd_pun_enabled", True))
        reward_attrs = [str(x).strip() for x in (cfg.get("local_drive_reward_attribute_names") or []) if str(x).strip()]
        punish_attrs = [str(x).strip() for x in (cfg.get("local_drive_punish_attribute_names") or []) if str(x).strip()]
        ev_min = float(cfg.get("local_drive_feedback_ev_min", 0.0) or 0.0)
        k_pred = float(cfg.get("local_drive_feedback_k_pred", 1.0) or 1.0)
        k_got = float(cfg.get("local_drive_feedback_k_got", 0.5) or 0.5)
        w_pred = float(cfg.get("local_drive_feedback_w_pred", 0.7) or 0.7)
        w_got = float(cfg.get("local_drive_feedback_w_got", 0.3) or 0.3)
        w_sum = max(1e-9, abs(w_pred) + abs(w_got))
        w_pred = w_pred / w_sum
        w_got = w_got / w_sum
        drop_zero_signal = bool(cfg.get("local_drive_feedback_drop_zero_signal_enabled", True))
        try:
            min_signal = max(0.0, float(cfg.get("local_drive_feedback_min_signal", 1e-9) or 0.0))
        except Exception:
            min_signal = 1e-9
        teacher_override_enabled = bool(cfg.get("local_drive_teacher_feedback_override_enabled", True))
        teacher_floor_scale = max(0.0, float(cfg.get("local_drive_teacher_feedback_floor_scale", 1.0) or 0.0))
        teacher_cross_suppress_scale = self._clamp01(
            float(cfg.get("local_drive_teacher_feedback_cross_suppress_scale", 0.35) or 0.0)
        )
        emotion_cfg = getattr(self.emotion, "_config", {}) or {}
        agg_cfg = (
            emotion_cfg.get("rwd_pun_pool_aggregation", {})
            if isinstance(emotion_cfg.get("rwd_pun_pool_aggregation", {}), dict)
            else {}
        )
        attr_weight_enabled = bool(agg_cfg.get("attribute_value_weight_enabled", True))
        attr_weight_fallback = float(agg_cfg.get("attribute_value_fallback", 1.0) or 1.0)

        result = {
            "enabled": bool(enabled),
            "by_ref": {},
            "by_item": {},
            "summary": {
                "row_count": len([row for row in (pool_items or []) if isinstance(row, dict)]),
                "mapped_ref_count": 0,
                "mapped_item_count": 0,
                "reward_attr_names": list(reward_attrs),
                "punish_attr_names": list(punish_attrs),
                "ev_min": float(ev_min),
                "attribute_value_weight_enabled": bool(attr_weight_enabled),
                "drop_zero_signal_enabled": bool(drop_zero_signal),
                "min_signal": float(min_signal),
                "zero_signal_skipped_count": 0,
            },
        }
        if not enabled:
            result["summary"]["reason"] = "config_disabled"
            return result

        rows_payload: list[dict[str, Any]] = []
        for row in pool_items or []:
            if not isinstance(row, dict):
                continue
            reward_hit_names = [name for name in reward_attrs if self._row_has_bound_attribute(row, name)]
            punish_hit_names = [name for name in punish_attrs if self._row_has_bound_attribute(row, name)]
            if not reward_hit_names and not punish_hit_names:
                continue

            ev = float(row.get("ev", 0.0) or 0.0)
            der = float(row.get("delta_er", 0.0) or 0.0)
            reward_strength = 0.0
            for name in reward_hit_names:
                reward_strength = max(
                    reward_strength,
                    self._row_attribute_strength(row, name, fallback=attr_weight_fallback)
                    if attr_weight_enabled
                    else 1.0,
                )
            punish_strength = 0.0
            for name in punish_hit_names:
                punish_strength = max(
                    punish_strength,
                    self._row_attribute_strength(row, name, fallback=attr_weight_fallback)
                    if attr_weight_enabled
                    else 1.0,
                )
            reward_pred_ev = max(0.0, ev) * reward_strength if reward_hit_names and ev >= ev_min else 0.0
            punish_pred_ev = max(0.0, ev) * punish_strength if punish_hit_names and ev >= ev_min else 0.0
            reward_got_er = max(0.0, der) * reward_strength if reward_hit_names and der > 0.0 else 0.0
            punish_got_er = max(0.0, der) * punish_strength if punish_hit_names and der > 0.0 else 0.0
            reward_value = self._clamp01(w_pred * self._softcap(reward_pred_ev, k=k_pred) + w_got * self._softcap(reward_got_er, k=k_got))
            punish_value = self._clamp01(w_pred * self._softcap(punish_pred_ev, k=k_pred) + w_got * self._softcap(punish_got_er, k=k_got))
            teacher_reward_strength = 0.0
            teacher_punish_strength = 0.0
            if teacher_override_enabled:
                if "teacher_reward_signal" in reward_hit_names:
                    teacher_reward_strength = self._clamp01(float(reward_strength) * float(teacher_floor_scale))
                    reward_value = max(float(reward_value), float(teacher_reward_strength))
                if "teacher_punish_signal" in punish_hit_names:
                    teacher_punish_strength = self._clamp01(float(punish_strength) * float(teacher_floor_scale))
                    punish_value = max(float(punish_value), float(teacher_punish_strength))
                if teacher_reward_strength > 0.0 and teacher_punish_strength <= 0.0:
                    punish_value = self._clamp01(float(punish_value) * float(teacher_cross_suppress_scale))
                elif teacher_punish_strength > 0.0 and teacher_reward_strength <= 0.0:
                    reward_value = self._clamp01(float(reward_value) * float(teacher_cross_suppress_scale))

            payload = {
                "rwd": round(float(reward_value), 8),
                "pun": round(float(punish_value), 8),
                "display": str(row.get("display", "") or row.get("display_text", "") or row.get("ref_object_id", "") or row.get("item_id", "")).strip(),
                "detail": {
                    "reward_hit_names": list(reward_hit_names),
                    "punish_hit_names": list(punish_hit_names),
                    "ref_object_id": str(row.get("ref_object_id", "") or ""),
                    "item_id": str(row.get("item_id", "") or ""),
                    "ev": round(float(ev), 8),
                    "delta_er": round(float(der), 8),
                    "reward_attr_strength": round(float(reward_strength), 8),
                    "punish_attr_strength": round(float(punish_strength), 8),
                    "reward_pred_ev": round(float(reward_pred_ev), 8),
                    "punish_pred_ev": round(float(punish_pred_ev), 8),
                    "reward_got_er": round(float(reward_got_er), 8),
                    "punish_got_er": round(float(punish_got_er), 8),
                    "teacher_reward_strength": round(float(teacher_reward_strength), 8),
                    "teacher_punish_strength": round(float(teacher_punish_strength), 8),
                    "teacher_override_enabled": bool(teacher_override_enabled),
                    "teacher_cross_suppress_scale": round(float(teacher_cross_suppress_scale), 8),
                },
            }
            if drop_zero_signal and (float(payload["rwd"]) + float(payload["pun"])) <= float(min_signal):
                result["summary"]["zero_signal_skipped_count"] = int(result["summary"].get("zero_signal_skipped_count", 0) or 0) + 1
                continue
            rows_payload.append({"row": row, "payload": payload})

        by_ref = result["by_ref"]
        by_item = result["by_item"]
        for entry in rows_payload:
            row = entry["row"]
            payload = entry["payload"]
            ref_ids: list[str] = []
            primary_ref_id = str(row.get("ref_object_id", "") or "").strip()
            if primary_ref_id:
                ref_ids.append(primary_ref_id)
            for alias in row.get("ref_alias_ids", []) or []:
                alias_id = str(alias or "").strip()
                if alias_id and alias_id not in ref_ids:
                    ref_ids.append(alias_id)
            item_id = str(row.get("item_id", "") or "").strip()
            for ref_id in ref_ids:
                by_ref[ref_id] = dict(payload)
            if item_id:
                by_item[item_id] = dict(payload)

        result["summary"]["mapped_ref_count"] = len(by_ref)
        result["summary"]["mapped_item_count"] = len(by_item)
        return result

    def _overlay_teacher_feedback_local_rwd_pun_map(
        self,
        local_map: dict[str, Any] | None,
        *,
        teacher_feedback: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not isinstance(local_map, dict):
            return {"enabled": False, "by_ref": {}, "by_item": {}, "summary": {"reason": "invalid_local_map"}}
        if not isinstance(teacher_feedback, dict):
            return local_map
        if not bool(local_map.get("enabled", False)):
            return local_map

        by_ref = local_map.get("by_ref", {}) if isinstance(local_map.get("by_ref", {}), dict) else {}
        by_item = local_map.get("by_item", {}) if isinstance(local_map.get("by_item", {}), dict) else {}
        if not isinstance(by_ref, dict) or not isinstance(by_item, dict):
            return local_map

        cfg = getattr(self.action, "_config", {}) or {}
        suppress_scale = self._clamp01(float(cfg.get("local_drive_teacher_feedback_cross_suppress_scale", 0.35) or 0.0))
        overlays: dict[str, dict[str, Any]] = {}
        all_rows = []
        all_rows.extend([row for row in (teacher_feedback.get("applied", []) or []) if isinstance(row, dict)])
        all_rows.extend([row for row in (teacher_feedback.get("context_binding_applied", []) or []) if isinstance(row, dict)])
        teacher_rwd = max(0.0, float(teacher_feedback.get("teacher_rwd", 0.0) or 0.0))
        teacher_pun = max(0.0, float(teacher_feedback.get("teacher_pun", 0.0) or 0.0))

        def _note_target(target_key: str, *, payload: dict[str, Any], overlay_rwd: float, overlay_pun: float) -> None:
            if not target_key:
                return
            entry = overlays.setdefault(target_key, {"payload": payload, "teacher_rwd": 0.0, "teacher_pun": 0.0})
            entry["teacher_rwd"] = max(float(entry.get("teacher_rwd", 0.0) or 0.0), float(overlay_rwd))
            entry["teacher_pun"] = max(float(entry.get("teacher_pun", 0.0) or 0.0), float(overlay_pun))

        for row in all_rows:
            attr_name = str(row.get("attribute_name", "") or "").strip()
            binding_scale = max(0.0, float(row.get("binding_scale", 1.0) or 0.0))
            target_ref = str(row.get("target_ref_object_id", "") or "").strip()
            target_item = str(row.get("target_item_id", "") or "").strip()
            target_display = str(row.get("target_display", "") or "").strip()
            overlay_rwd = 0.0
            overlay_pun = 0.0
            if attr_name == "teacher_reward_signal":
                overlay_rwd = self._clamp01(float(teacher_rwd) * float(binding_scale))
            elif attr_name == "teacher_punish_signal":
                overlay_pun = self._clamp01(float(teacher_pun) * float(binding_scale))
            else:
                continue
            if target_ref:
                payload = by_ref.setdefault(
                    target_ref,
                    {"rwd": 0.0, "pun": 0.0, "display": target_display or target_ref, "detail": {}},
                )
                _note_target(f"ref::{target_ref}", payload=payload, overlay_rwd=overlay_rwd, overlay_pun=overlay_pun)
            if target_item:
                payload = by_item.setdefault(
                    target_item,
                    {"rwd": 0.0, "pun": 0.0, "display": target_display or target_item, "detail": {}},
                )
                _note_target(f"item::{target_item}", payload=payload, overlay_rwd=overlay_rwd, overlay_pun=overlay_pun)

        applied_count = 0
        for entry in overlays.values():
            payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else None
            if not isinstance(payload, dict):
                continue
            overlay_rwd = max(0.0, float(entry.get("teacher_rwd", 0.0) or 0.0))
            overlay_pun = max(0.0, float(entry.get("teacher_pun", 0.0) or 0.0))
            current_rwd = max(0.0, float(payload.get("rwd", 0.0) or 0.0))
            current_pun = max(0.0, float(payload.get("pun", 0.0) or 0.0))
            if overlay_rwd > 0.0:
                current_rwd = max(current_rwd, overlay_rwd)
                if overlay_pun <= 0.0:
                    current_pun = self._clamp01(current_pun * suppress_scale)
            if overlay_pun > 0.0:
                current_pun = max(current_pun, overlay_pun)
                if overlay_rwd <= 0.0:
                    current_rwd = self._clamp01(current_rwd * suppress_scale)
            payload["rwd"] = round(float(current_rwd), 8)
            payload["pun"] = round(float(current_pun), 8)
            detail = payload.get("detail", {}) if isinstance(payload.get("detail", {}), dict) else {}
            detail.update(
                {
                    "teacher_overlay_applied": True,
                    "teacher_overlay_reward": round(float(overlay_rwd), 8),
                    "teacher_overlay_punish": round(float(overlay_pun), 8),
                    "teacher_overlay_cross_suppress_scale": round(float(suppress_scale), 8),
                }
            )
            payload["detail"] = detail
            applied_count += 1

        summary = local_map.get("summary", {}) if isinstance(local_map.get("summary", {}), dict) else {}
        summary["teacher_overlay_applied_count"] = int(applied_count)
        local_map["summary"] = summary
        local_map["by_ref"] = by_ref
        local_map["by_item"] = by_item
        return local_map

    # ================================================================== #
    # Episodic Memory Enrichment                                          #
    # sanitized
    # ================================================================== #

    def _enrich_tick_episodic_memory_with_bound_attributes(self, *, report: dict[str, Any], trace_id: str, tick_id: str) -> dict[str, Any]:
        """
        Enrich current tick episodic memory material with runtime bound attributes.
        # sanitized
        """
        try:
            stim_res = (report.get("stimulus_level", {}) or {}).get("result", {}) or {}
            memory_id = str(stim_res.get("episodic_memory_id", "") or "").strip()
        except Exception:
            memory_id = ""
        if not memory_id:
            return {"ok": False, "code": "NO_MEMORY_ID", "message": "No episodic_memory_id in this tick stimulus_level result."}

        try:
            episodic_obj = self.hdb._episodic_store.get(memory_id)  # type: ignore[attr-defined]
        except Exception:
            episodic_obj = None
        if not isinstance(episodic_obj, dict):
            return {"ok": False, "code": "MEMORY_NOT_FOUND", "message": f"未找到情景记忆 / episodic memory not found: {memory_id}"}

        meta = episodic_obj.get("meta", {}) if isinstance(episodic_obj.get("meta", {}), dict) else {}
        ext = meta.get("ext", {}) if isinstance(meta.get("ext", {}), dict) else {}
        mm = ext.get("memory_material", {}) if isinstance(ext.get("memory_material", {}), dict) else {}
        if str(mm.get("memory_kind", "")) != "stimulus_packet":
            return {"ok": False, "code": "SKIP_KIND", "message": "跳过当前记忆类型 / skip memory_kind=" + str(mm.get("memory_kind"))}
        enrich_meta = mm.get("runtime_enrichment", {}) if isinstance(mm.get("runtime_enrichment", {}), dict) else {}
        if enrich_meta.get("bound_attributes_included") is True:
            return {"ok": True, "code": "OK_ALREADY", "message": "runtime_enrichment already contains bound attributes", "data": enrich_meta}

        seq_groups = list(mm.get("sequence_groups", []) or [])
        if not seq_groups:
            return {"ok": False, "code": "EMPTY_MATERIAL", "message": "memory_material.sequence_groups is empty"}

        include_exact = {"reward_signal", "punish_signal", "teacher_reward_signal", "teacher_punish_signal"}
        max_attrs_per_anchor = 6
        added_unit_count = 0
        added_bundle_count = 0
        anchor_hit_count = 0

        for group in seq_groups:
            if not isinstance(group, dict):
                continue
            units = list(group.get("units", []) or [])
            if not units:
                continue
            existing_unit_ids = {str(u.get("unit_id", "")) for u in units if isinstance(u, dict) and str(u.get("unit_id", ""))}
            try:
                next_si = max(int(u.get("sequence_index", 0) or 0) for u in units if isinstance(u, dict)) + 1
            except Exception:
                next_si = 0

            bundles = group.get("csa_bundles", [])
            if not isinstance(bundles, list):
                bundles = []
            existing_bundle_keys = {str(b.get("bundle_id", "") or "") for b in bundles if isinstance(b, dict) and str(b.get("bundle_id", ""))}

            for u in list(units):
                if not isinstance(u, dict):
                    continue
                role = str(u.get("unit_role", u.get("role", "feature")) or "feature").strip() or "feature"
                if role == "attribute":
                    continue
                anchor_unit_id = str(u.get("unit_id", "") or "").strip()
                if not anchor_unit_id:
                    continue
                try:
                    st_item = self.pool._store.get_by_ref(anchor_unit_id)  # type: ignore[attr-defined]
                except Exception:
                    st_item = None
                if not isinstance(st_item, dict):
                    continue
                bound_attrs = (st_item.get("ext", {}) or {}).get("bound_attributes", [])
                if not isinstance(bound_attrs, list) or not bound_attrs:
                    continue

                selected_attrs: list[dict] = []
                for attr in bound_attrs:
                    if not isinstance(attr, dict):
                        continue
                    content = attr.get("content", {}) if isinstance(attr.get("content", {}), dict) else {}
                    attr_name = str(content.get("attribute_name", "") or "").strip()
                    raw = str(content.get("raw", "") or "")
                    if not attr_name:
                        if ":" in raw:
                            attr_name = raw.split(":", 1)[0].strip()
                        else:
                            attr_name = raw.strip()
                    if not attr_name:
                        continue
                    if attr_name in include_exact or attr_name.startswith("cfs_"):
                        selected_attrs.append(attr)

                if not selected_attrs:
                    continue

                anchor_hit_count += 1
                member_unit_ids = [anchor_unit_id]
                for attr in selected_attrs[:max_attrs_per_anchor]:
                    attr_unit_id = str(attr.get("id", "") or "").strip()
                    if not attr_unit_id or attr_unit_id in existing_unit_ids:
                        continue
                    content = attr.get("content", {}) if isinstance(attr.get("content", {}), dict) else {}
                    attr_name = str(content.get("attribute_name", "") or "").strip()
                    raw = str(content.get("raw", "") or "")
                    if not attr_name:
                        if ":" in raw:
                            attr_name = raw.split(":", 1)[0].strip()
                        else:
                            attr_name = raw.strip()
                    display = str(content.get("display", "") or raw or attr_unit_id)
                    token = display
                    if attr_name and attr_name not in token:
                        token = f"{token}闂佹寧绋戝鏈紅tr_name闂?"
                    attribute_value = content.get("attribute_value")
                    value_type = str(content.get("value_type", "numerical" if attribute_value is not None else "discrete") or "discrete")
                    units.append(
                        {
                            "object_type": "sa",
                            "unit_id": attr_unit_id,
                            "token": token,
                            "display_text": token,
                            "unit_role": "attribute",
                            "attribute_name": attr_name,
                            "attribute_value": attribute_value,
                            "value_type": value_type,
                            "sequence_index": int(next_si),
                            "group_index": int(group.get("group_index", 0) or 0),
                            "origin_frame_id": memory_id,
                            "source_type": "runtime_enrichment",
                        }
                    )
                    existing_unit_ids.add(attr_unit_id)
                    member_unit_ids.append(attr_unit_id)
                    next_si += 1
                    added_unit_count += 1

                if len(member_unit_ids) >= 2:
                    bundle_id = f"enrich::{anchor_unit_id}"
                    if bundle_id in existing_bundle_keys:
                        continue
                    bundles.append({"bundle_id": bundle_id, "anchor_unit_id": anchor_unit_id, "member_unit_ids": member_unit_ids})
                    existing_bundle_keys.add(bundle_id)
                    added_bundle_count += 1

            group["units"] = units
            group["csa_bundles"] = bundles
            # Keep tokens in sync (best-effort).
            try:
                group["tokens"] = [str(x.get("token", "")) for x in units if isinstance(x, dict) and str(x.get("token", ""))]
            except Exception:
                pass

        mm["sequence_groups"] = seq_groups
        mm["runtime_enrichment"] = {
            "bound_attributes_included": True,
            "memory_id": memory_id,
            "tick_id": tick_id,
            "trace_id": trace_id,
            "added_unit_count": int(added_unit_count),
            "added_bundle_count": int(added_bundle_count),
            "anchor_hit_count": int(anchor_hit_count),
            "include_exact": sorted(list(include_exact)),
            "max_attrs_per_anchor": int(max_attrs_per_anchor),
            "built_at_ms": int(time.time() * 1000),
        }
        ext["memory_material"] = mm
        meta["ext"] = ext
        episodic_obj["meta"] = meta
        try:
            self.hdb._episodic_store.update(episodic_obj)  # type: ignore[attr-defined]
        except Exception as exc:
            return {"ok": False, "code": "UPDATE_FAILED", "message": f"更新情景记忆失败 / episodic_store.update failed: {exc}"}

        return {"ok": True, "code": "OK", "message": "已将绑定属性写回情景记忆 / runtime enrichment written back to episodic memory", "data": dict(mm.get("runtime_enrichment", {}) or {})}

    def _apply_innate_pool_effects(
        self,
        *,
        effects: list[dict[str, Any]],
        context: dict[str, Any],
        trace_id: str,
        tick_id: str,
    ) -> dict[str, Any]:
        """
        Apply IESM pool_effects to StatePool (safe executor).
        # sanitized

        Safety / 闁诲海鎳撻ˇ顖炲矗韫囨洜椹抽柡宥庡亝濞堬綁鏌?
        - 闂佸憡鐟禍婵嬪极椤曗偓楠炴劖鎷呴悜姗嗕槐闂佸憡鑹剧粔鏉戠暦?effect_type闂佹寧绋戝绌檕l_energy / pool_bind_attribute闂?
        # sanitized
        # sanitized
        """
        effects = [e for e in (effects or []) if isinstance(e, dict)]
        pool_items = list(context.get("pool_items", []) or [])
        pool_items = [it for it in pool_items if isinstance(it, dict)]

        def select_items(selector: dict[str, Any] | None) -> list[dict[str, Any]]:
            if not selector or not isinstance(selector, dict):
                return list(pool_items)
            mode = str(selector.get("mode", "all") or "all").strip()
            rows = list(pool_items)

            ref_types = selector.get("ref_object_types")
            if isinstance(ref_types, list):
                allow = {str(x) for x in ref_types if str(x)}
                if allow:
                    rows = [r for r in rows if str(r.get("ref_object_type", "")) in allow]

            if mode in {"all", "any"}:
                return rows
            if mode == "specific_item":
                iid = str(selector.get("item_id", "") or "").strip()
                return [r for r in rows if str(r.get("item_id", "")) == iid] if iid else []
            if mode == "specific_ref":
                rid = str(selector.get("ref_object_id", "") or "").strip()
                rtype = str(selector.get("ref_object_type", "") or "").strip()
                out = [r for r in rows if str(r.get("ref_object_id", "")) == rid] if rid else []
                if rtype:
                    out = [r for r in out if str(r.get("ref_object_type", "")) == rtype]
                return out
            if mode == "contains_text":
                needle = str(selector.get("contains_text", "") or "").strip()
                if not needle:
                    return []
                needle_low = needle.lower()
                out: list[dict[str, Any]] = []
                for r in rows:
                    hay = " ".join(
                        [
                            str(r.get("display", "") or ""),
                            str(r.get("display_detail", "") or ""),
                            " ".join(str(x) for x in (r.get("attribute_displays", []) or []) if str(x)),
                            " ".join(str(x) for x in (r.get("feature_displays", []) or []) if str(x)),
                            " ".join(str(x) for x in (r.get("bound_attribute_displays", []) or []) if str(x)),
                        ]
                    )
                    if needle in hay or needle_low in hay.lower():
                        out.append(r)
                return out
            if mode == "top_n":
                try:
                    n = int(selector.get("top_n", 8) or 8)
                except Exception:
                    n = 8
                n = max(1, min(512, n))
                rows.sort(key=lambda r: float(r.get("total_energy", 0.0) or 0.0), reverse=True)
                return rows[:n]
            return rows

        def coerce_float(v: Any, default: float = 0.0) -> float:
            try:
                if v is None or v == "":
                    return float(default)
                return float(v)
            except Exception:
                return float(default)

        def coerce_float_optional(v: Any) -> float | None:
            try:
                if v is None or v == "":
                    return None
                return float(v)
            except Exception:
                return None

        def resolve_ref_target_fields(
            spec_dict: dict[str, Any],
            selector_dict: dict[str, Any] | None = None,
        ) -> tuple[str, str]:
            ref_id = str(spec_dict.get("ref_object_id", "") or spec_dict.get("target_ref_object_id", "") or "").strip()
            ref_type = str(spec_dict.get("ref_object_type", "") or spec_dict.get("target_ref_object_type", "") or "").strip()
            if isinstance(selector_dict, dict) and str(selector_dict.get("mode", "") or "").strip() == "specific_ref":
                if not ref_id:
                    ref_id = str(selector_dict.get("ref_object_id", "") or "").strip()
                if not ref_type:
                    ref_type = str(selector_dict.get("ref_object_type", "") or "").strip()
            return ref_id, ref_type

        def refresh_pool_item_summary_by_ref(ref_id: str, ref_type: str = "") -> dict[str, Any] | None:
            try:
                new_item = self.pool._store.get_by_ref(ref_id)
                if new_item and isinstance(new_item, dict):
                    summary = self.pool._snapshot._build_top_item_summary(new_item)  # type: ignore[attr-defined]
                    if isinstance(summary, dict):
                        summary["total_energy"] = round(
                            max(0.0, float(summary.get("er", 0.0) or 0.0))
                            + max(0.0, float(summary.get("ev", 0.0) or 0.0)),
                            8,
                        )
                        item_id = str(summary.get("item_id", "") or "")
                        filtered: list[dict[str, Any]] = []
                        for row in pool_items:
                            row_item_id = str(row.get("item_id", "") or "")
                            row_ref_id = str(row.get("ref_object_id", "") or "")
                            row_ref_type = str(row.get("ref_object_type", "") or "")
                            if item_id and row_item_id == item_id:
                                continue
                            if row_ref_id == ref_id and (not ref_type or row_ref_type == ref_type):
                                continue
                            filtered.append(row)
                        filtered.append(summary)
                        pool_items[:] = filtered
                        return summary
            except Exception:
                pass
            return None

        def create_missing_ref_target(
            spec_dict: dict[str, Any],
            selector_dict: dict[str, Any] | None,
            *,
            initial_er: float,
            initial_ev: float,
            effect_kind: str,
            rule_name: str,
        ) -> dict[str, Any] | None:
            ref_id, ref_type = resolve_ref_target_fields(spec_dict, selector_dict)
            if not ref_id:
                return None
            obj_type = str(
                spec_dict.get("create_ref_object_type", "")
                or ref_type
                or spec_dict.get("ref_object_type", "")
                or spec_dict.get("target_ref_object_type", "")
                or "sa"
            ).strip() or "sa"
            display = str(spec_dict.get("create_display", "") or spec_dict.get("display", "") or ref_id)
            runtime_obj = {
                "id": ref_id,
                "object_type": obj_type,
                "content": {"raw": display, "display": display, "value_type": "discrete"},
                "energy": {"er": round(max(0.0, initial_er), 8), "ev": round(max(0.0, initial_ev), 8)},
            }
            insert = self.pool.insert_runtime_node(
                runtime_object=runtime_obj,
                trace_id=f"{trace_id}_iesm_{effect_kind}_create",
                tick_id=tick_id,
                allow_merge=True,
                source_module="innate_script",
                reason=f"iesm_{effect_kind}_create:{rule_name or 'rule'}",
            )
            insert_data = insert.get("data", {}) if isinstance(insert.get("data", {}), dict) else {}
            target_item_id = str(insert_data.get("item_id", "") or insert_data.get("target_item_id", "") or "")
            target_summary = refresh_pool_item_summary_by_ref(ref_id, obj_type)
            if not isinstance(target_summary, dict):
                target_summary = {
                    "item_id": target_item_id,
                    "ref_object_id": ref_id,
                    "ref_object_type": obj_type,
                    "display": display,
                    "er": round(max(0.0, initial_er), 8),
                    "ev": round(max(0.0, initial_ev), 8),
                    "total_energy": round(max(0.0, initial_er) + max(0.0, initial_ev), 8),
                }
            return {
                "ref_id": ref_id,
                "ref_type": obj_type,
                "insert": insert,
                "target": target_summary,
            }

        applied: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        cap = 64  # single tick cap / 闂?tick 婵炴垶鎸搁敃顏勵瀶?
        for eff in effects[:cap]:
            et = str(eff.get("effect_type", "") or "")
            spec = eff.get("spec") if isinstance(eff.get("spec"), dict) else {}
            rule_id = str(eff.get("rule_id", "") or "")
            effect_id = str(eff.get("effect_id", "") or "")

            if et == "pool_energy":
                delta_er = coerce_float(spec.get("delta_er", spec.get("er", 0.0)), 0.0)
                delta_ev = coerce_float(spec.get("delta_ev", spec.get("ev", 0.0)), 0.0)
                if abs(delta_er) < 1e-12 and abs(delta_ev) < 1e-12:
                    skipped.append({"effect_id": effect_id, "effect_type": et, "rule_id": rule_id, "reason": "delta_both_zero"})
                    continue

                # Resolve targets
                targets: list[dict[str, Any]] = []
                selector = spec.get("selector") if isinstance(spec.get("selector"), dict) else None
                if selector:
                    targets = select_items(selector)
                else:
                    item_id = str(spec.get("target_item_id", "") or spec.get("item_id", "") or "").strip()
                    if item_id:
                        targets = [r for r in pool_items if str(r.get("item_id", "")) == item_id]
                    if not targets:
                        ref_id = str(spec.get("ref_object_id", "") or spec.get("target_ref_object_id", "") or "").strip()
                        ref_type = str(spec.get("ref_object_type", "") or spec.get("target_ref_object_type", "") or "").strip()
                        if ref_id:
                            targets = [r for r in pool_items if str(r.get("ref_object_id", "")) == ref_id and (not ref_type or str(r.get("ref_object_type", "")) == ref_type)]

                # Optional create-if-missing (only for specific ref targets)
                if not targets and bool(spec.get("create_if_missing", False)):
                    if max(0.0, delta_er) > 0.0 or max(0.0, delta_ev) > 0.0:
                        create_result = create_missing_ref_target(
                            spec,
                            selector,
                            initial_er=max(0.0, delta_er),
                            initial_ev=max(0.0, delta_ev),
                            effect_kind="pool_energy",
                            rule_name=rule_id,
                        )
                    else:
                        create_result = None
                    if create_result is not None:
                        insert = create_result.get("insert", {}) if isinstance(create_result, dict) else {}
                        applied.append(
                            {
                                "effect_id": effect_id,
                                "effect_type": et,
                                "rule_id": rule_id,
                                "op": "create",
                                "ref_object_id": create_result.get("ref_id", ""),
                                "ref_object_type": create_result.get("ref_type", ""),
                                "success": bool(insert.get("success", False)),
                                "code": insert.get("code", ""),
                                "data": insert.get("data", {}) or {},
                            }
                        )
                        continue

                if not targets:
                    skipped.append({"effect_id": effect_id, "effect_type": et, "rule_id": rule_id, "reason": "no_targets"})
                    continue

                # Apply to each target (cap per effect).
                reason = str(spec.get("reason", "") or f"iesm_pool_energy:{rule_id}").strip()
                for t in targets[:24]:
                    tid = str(t.get("item_id", "") or "")
                    if not tid:
                        continue
                    res = self.pool.apply_energy_update(
                        target_item_id=tid,
                        delta_er=float(delta_er),
                        delta_ev=float(delta_ev),
                        trace_id=f"{trace_id}_iesm_pool_energy",
                        tick_id=tick_id,
                        reason=reason,
                        source_module="innate_script",
                    )
                    applied.append(
                        {
                            "effect_id": effect_id,
                            "effect_type": et,
                            "rule_id": rule_id,
                            "op": "update",
                            "target_item_id": tid,
                            "success": bool(res.get("success", False)),
                            "code": res.get("code", ""),
                            "data": res.get("data", {}) or {},
                        }
                    )
                continue

            if et == "pool_bind_attribute":
                selector = spec.get("selector") if isinstance(spec.get("selector"), dict) else None
                targets = select_items(selector) if selector else []

                if not targets:
                    item_id = str(spec.get("target_item_id", "") or spec.get("item_id", "") or "").strip()
                    if item_id:
                        targets = [r for r in pool_items if str(r.get("item_id", "")) == item_id]
                if not targets:
                    ref_id, ref_type = resolve_ref_target_fields(spec, selector)
                    if ref_id:
                        targets = [r for r in pool_items if str(r.get("ref_object_id", "")) == ref_id and (not ref_type or str(r.get("ref_object_type", "")) == ref_type)]

                if not targets and bool(spec.get("create_if_missing", False)):
                    create_result = create_missing_ref_target(
                        spec,
                        selector,
                        initial_er=0.0,
                        initial_ev=0.0,
                        effect_kind="pool_bind_attribute",
                        rule_name=rule_id,
                    )
                    if create_result is not None:
                        insert = create_result.get("insert", {}) if isinstance(create_result, dict) else {}
                        applied.append(
                            {
                                "effect_id": effect_id,
                                "effect_type": et,
                                "rule_id": rule_id,
                                "op": "create",
                                "ref_object_id": create_result.get("ref_id", ""),
                                "ref_object_type": create_result.get("ref_type", ""),
                                "success": bool(insert.get("success", False)),
                                "code": insert.get("code", ""),
                                "data": insert.get("data", {}) or {},
                            }
                        )
                        target = create_result.get("target", {}) if isinstance(create_result, dict) else {}
                        if isinstance(target, dict):
                            targets = [target]

                if not targets:
                    skipped.append({"effect_id": effect_id, "effect_type": et, "rule_id": rule_id, "reason": "no_targets"})
                    continue

                attr = spec.get("attribute") if isinstance(spec.get("attribute"), dict) else spec
                raw = str(attr.get("raw", "") or attr.get("attribute_raw", "") or "").strip()
                display = str(attr.get("display", "") or attr.get("attribute_display", "") or raw or "attribute")
                value_type = str(attr.get("value_type", "") or ("numerical" if isinstance(attr.get("attribute_value"), (int, float)) else "discrete"))
                attr_name = str(attr.get("attribute_name", "") or "").strip()
                attr_value = attr.get("attribute_value")
                if not attr_name:
                    # best-effort infer from raw "name:value"
                    if ":" in raw:
                        attr_name = raw.split(":", 1)[0].strip()
                    else:
                        attr_name = raw.strip() or "attribute"

                modality = str(attr.get("modality", "") or "internal")
                er = coerce_float(attr.get("er", 0.0), 0.0)
                ev = coerce_float(attr.get("ev", 0.0), 0.0)
                reason = str(spec.get("reason", "") or f"iesm_pool_bind_attribute:{rule_id}").strip()
                if bool(self._config.get("iesm_pool_bind_attribute_drop_zero_numeric_enabled", True)):
                    epsilon = max(
                        0.0,
                        float(self._config.get("iesm_pool_bind_attribute_zero_numeric_epsilon", 1e-9) or 0.0),
                    )
                    attr_value_f = coerce_float_optional(attr_value)
                    numeric_value_is_zero = (
                        value_type == "numerical"
                        and attr_value_f is not None
                        and abs(float(attr_value_f)) <= epsilon
                    )
                    if numeric_value_is_zero and abs(float(er)) <= epsilon and abs(float(ev)) <= epsilon:
                        skipped.append(
                            {
                                "effect_id": effect_id,
                                "effect_type": et,
                                "rule_id": rule_id,
                                "reason": "zero_numeric_attribute",
                                "attribute_name": attr_name,
                                "attribute_value": attr_value_f,
                            }
                        )
                        continue

                for t in targets[:24]:
                    tid = str(t.get("item_id", "") or "")
                    if not tid:
                        continue
                    # Stable attribute id for deduplication on the same target+name.
                    # sanitized
                    target_ref_id = str(t.get("ref_object_id", "") or tid)
                    attr_id = f"sa_iesm_attr_{attr_name}_{target_ref_id}"
                    attribute_sa = {
                        "id": attr_id,
                        "object_type": "sa",
                        "content": {
                            "raw": raw or f"{attr_name}:{attr_value}",
                            "display": display,
                            "value_type": value_type,
                            "attribute_name": attr_name,
                            "attribute_value": attr_value,
                        },
                        "stimulus": {"role": "attribute", "modality": modality},
                        "energy": {"er": float(er), "ev": float(ev)},
                        # meta.ext: keep minimal provenance for observability and downstream memory enrichment.
                        # sanitized
                        "meta": {
                            "ext": {
                                "bound_from": "iesm_pool_bind_attribute",
                                "rule_id": rule_id,
                                "rule_title": str(eff.get("rule_title", "") or ""),
                                "rule_phase": str(eff.get("rule_phase", "") or ""),
                                "rule_priority": int(eff.get("rule_priority", 0) or 0),
                                "reason": reason,
                                "trace_id": trace_id,
                                "tick_id": tick_id,
                            }
                        },
                    }
                    res = self.pool.bind_attribute_node_to_object(
                        target_item_id=tid,
                        attribute_sa=attribute_sa,
                        trace_id=f"{trace_id}_iesm_bind_attr",
                        tick_id=tick_id,
                        source_module="innate_script",
                        reason=reason,
                    )
                    applied.append(
                        {
                            "effect_id": effect_id,
                            "effect_type": et,
                            "rule_id": rule_id,
                            "target_item_id": tid,
                            "attribute_sa_id": attr_id,
                            "success": bool(res.get("success", False)),
                            "code": res.get("code", ""),
                            "data": res.get("data", {}) or {},
                        }
                    )
                continue

            skipped.append({"effect_id": effect_id, "effect_type": et, "rule_id": rule_id, "reason": "unsupported_effect_type"})

        return {
            "applied_count": len(applied),
            "skipped_count": len(skipped),
            "applied": applied[:256],
            "skipped": skipped[:256],
        }

    def get_placeholder_modules(self) -> list[dict[str, Any]]:
        return [
            {
                "module": "attention",
                "title": "注意力模块",
                "status": "MVP 可用",
                "description": "已接入 CAM 选取、内源分辨率、注意力放大与行动阈值联动。",
            },
            {
                "module": "cognitive_feeling",
                "title": "认知感受模块",
                "status": "MVP 可用（IESM 主链）",
                "description": "默认由先天脚本 phase=cfs 生成认知感受；旧 CFS 模块仅保留作对照/回退。",
            },
            {
                "module": "emotion",
                "title": "情绪模块",
                "status": "MVP 可用（8 通道）",
                "description": "8 通道 NT 已接入 IESM emotion_update、奖励惩罚后置调制与行动阈值缩放。",
            },
            {
                "module": "innate_script",
                "title": "先天脚本模块",
                "status": "MVP 可用（规则驱动）",
                "description": "支持 cfs / directives / emotion_post 三阶段，默认承担认知感受与后置情绪调制。",
            },
            {
                "module": "action",
                "title": "行动模块",
                "status": "MVP 可用",
                "description": "已接入驱动力、教师奖惩、局部反馈塑形与天气探针动作。",
            },
        ]

    def _build_sensor_report(self, text: str, sensor_result: dict) -> dict:
        # sanitized
        # sanitized
        if not isinstance(sensor_result, dict):
            return {"input_text": text, "success": False, "code": "SENSOR_RESULT_INVALID", "message": "sensor_result 不是 dict / sensor_result is not a dict"}
        if not bool(sensor_result.get("success", False)):
            return {
                "input_text": text,
                "success": False,
                "code": str(sensor_result.get("code", "") or ""),
                "message": str(sensor_result.get("message", "") or ""),
                "error": sensor_result.get("error", {}) if isinstance(sensor_result.get("error", {}), dict) else {},
                # sanitized
            }

        data = sensor_result.get("data", {}) if isinstance(sensor_result.get("data", {}), dict) else {}
        packet = data.get("stimulus_packet", {}) if isinstance(data.get("stimulus_packet", {}), dict) else {}
        sensor_frame = data.get("sensor_frame", {}) if isinstance(data.get("sensor_frame", {}), dict) else {}
        trace_id = str(((sensor_result.get("meta", {}) or {}).get("trace_id", "")) or "")
        runtime_snapshot = self.sensor.get_runtime_snapshot(trace_id=f"{trace_id}_sensor_runtime")["data"]
        unit_rows = self._describe_packet_units(packet)
        groups = self._describe_packet_groups(packet)
        # sanitized
        # sanitized
        # sanitized
        # sanitized
        csa_bundle_count = sum(int(g.get("csa_count", 0) or 0) for g in groups if isinstance(g, dict))
        feature_sa_count = sum(1 for row in unit_rows if str(row.get("role", "") or "") != "attribute")
        attribute_sa_count = sum(1 for row in unit_rows if str(row.get("role", "") or "") == "attribute")
        return {
            "input_text": text,
            "success": True,
            "normalized_text": sensor_frame.get("normalized_text", text),
            "mode": data.get("tokenization_summary", {}).get("mode", ""),
            "tokenizer_backend": runtime_snapshot["config_summary"]["tokenizer_backend"],
            "tokenizer_available": runtime_snapshot["config_summary"]["tokenizer_available"],
            "tokenizer_fallback": data.get("tokenization_summary", {}).get("tokenizer_fallback", False),
            "sa_count": len(packet.get("sa_items", [])),
            "csa_count": len(packet.get("csa_items", [])),
            "feature_sa_count": feature_sa_count,
            "attribute_sa_count": attribute_sa_count,
            "csa_bundle_count": csa_bundle_count,
            "groups": groups,
            "units": unit_rows,
            "feature_units": unit_rows,
            "echo_frames_used": list(data.get("echo_frames_used", [])),
            "echo_decay_summary": data.get("echo_decay_summary", {}),
            "fatigue_summary": data.get("fatigue_summary", {}),
        }

    def _state_pool_summary_lightweight(self) -> dict[str, Any]:
        try:
            items = [item for item in list(self.pool._store.get_all()) if isinstance(item, dict)]  # type: ignore[attr-defined]
        except Exception:
            items = []
        type_counts: dict[str, int] = {}
        high_er_count = 0
        high_ev_count = 0
        high_cp_count = 0
        bound_attribute_item_count = 0
        binding_csa_item_count = 0
        contextual_item_count = 0
        multi_context_item_count = 0
        residual_origin_item_count = 0
        context_path_depth_total = 0
        for item in items:
            ref_type = str(item.get("ref_object_type", "unknown") or "unknown")
            type_counts[ref_type] = int(type_counts.get(ref_type, 0)) + 1
            energy = item.get("energy", {}) if isinstance(item.get("energy", {}), dict) else {}
            try:
                if float(energy.get("er", 0.0) or 0.0) >= 0.5:
                    high_er_count += 1
                if float(energy.get("ev", 0.0) or 0.0) >= 0.5:
                    high_ev_count += 1
                if float(energy.get("cognitive_pressure_abs", 0.0) or 0.0) >= 0.5:
                    high_cp_count += 1
            except Exception:
                pass
            binding_state = item.get("binding_state", {}) if isinstance(item.get("binding_state", {}), dict) else {}
            if binding_state.get("bound_attribute_sa_ids"):
                bound_attribute_item_count += 1
            if item.get("sub_type") == "csa_binding_item":
                binding_csa_item_count += 1
            source = item.get("source", {}) if isinstance(item.get("source", {}), dict) else {}
            meta_ext = (
                item.get("meta", {}).get("ext", {})
                if isinstance(item.get("meta", {}), dict) and isinstance(item.get("meta", {}).get("ext", {}), dict)
                else {}
            )
            context_path_ids = (
                meta_ext.get("context_path_ids")
                if isinstance(meta_ext.get("context_path_ids"), list)
                else source.get("context_path_ids", [])
            )
            context_ref = str(meta_ext.get("context_ref_object_id", "") or source.get("context_ref_object_id", "") or "")
            context_owner = str(meta_ext.get("context_owner_structure_id", "") or source.get("context_owner_structure_id", "") or "")
            if context_ref or context_owner or context_path_ids:
                contextual_item_count += 1
                depth = len(context_path_ids) if isinstance(context_path_ids, list) and context_path_ids else 1
                context_path_depth_total += int(depth)
                if depth > 1:
                    multi_context_item_count += 1
            residual_kind = str(meta_ext.get("residual_origin_kind", "") or "")
            residual_entry = str(meta_ext.get("residual_origin_entry_id", "") or "")
            if residual_kind or residual_entry:
                residual_origin_item_count += 1
        return {
            "active_item_count": len(items),
            "high_er_item_count": high_er_count,
            "high_ev_item_count": high_ev_count,
            "high_cp_item_count": high_cp_count,
            "object_type_counts": type_counts,
            "bound_attribute_item_count": bound_attribute_item_count,
            "binding_csa_item_count": binding_csa_item_count,
            "contextual_item_count": contextual_item_count,
            "multi_context_item_count": multi_context_item_count,
            "context_path_depth_mean": round(float(context_path_depth_total) / float(contextual_item_count), 8)
            if contextual_item_count
            else 0.0,
            "residual_origin_item_count": residual_origin_item_count,
            "attribute_energy_totals": {},
            "bound_attribute_energy_totals": {},
            "lightweight_summary": True,
        }

    def _build_hdb_snapshot_lightweight(self, *, trace_id: str) -> dict[str, Any]:
        memory_items = []
        try:
            memory_items = list(self.hdb._memory_activation_store.iter_items())
        except Exception:
            memory_items = []
        try:
            active_jobs = [
                job for job in self.hdb._repair.jobs.values()
                if isinstance(job, dict) and job.get("status") in {"running", "pending", "stopping"}
            ]
        except Exception:
            active_jobs = []
        memory_er = round(sum(float(item.get("er", 0.0) or 0.0) for item in memory_items if isinstance(item, dict)), 8)
        memory_ev = round(sum(float(item.get("ev", 0.0) or 0.0) for item in memory_items if isinstance(item, dict)), 8)
        pointer_stats = {}
        try:
            pointer_stats = self.hdb._pointer_index.export_snapshot()
        except Exception:
            pointer_stats = {}
        contextual_summary = {}
        try:
            contextual_summary = self._build_hdb_lightweight_context_summary()
        except Exception:
            contextual_summary = {}
        return {
            "snapshot_id": next_id("hdbs"),
            "object_type": "runtime_snapshot",
            "sub_type": "hdb_snapshot",
            "trace_id": trace_id,
            "timestamp_ms": int(time.time() * 1000),
            "summary": {
                "structure_count": int(getattr(self.hdb._structure_store, "structure_count", 0) or 0),
                "structure_db_count": int(getattr(self.hdb._structure_store, "structure_db_count", 0) or 0),
                "group_count": int(getattr(self.hdb._group_store, "size", 0) or 0),
                "episodic_count": int(getattr(self.hdb._episodic_store, "size", 0) or 0),
                "memory_activation_count": int(getattr(self.hdb._memory_activation_store, "size", 0) or 0),
                "memory_activation_total_er": memory_er,
                "memory_activation_total_ev": memory_ev,
                "memory_activation_total_energy": round(memory_er + memory_ev, 8),
                "issue_count": len(getattr(self.hdb, "_issue_queue", []) or []),
                "active_repair_job_count": len(active_jobs),
                **contextual_summary,
                "lightweight_summary": True,
            },
            "stats": {"pointer_index": pointer_stats},
            "recent_structures": [],
            "recent_groups": [],
            "lightweight_snapshot": True,
        }

    def _build_hdb_lightweight_context_summary(self) -> dict[str, Any]:
        structure_store = getattr(self.hdb, "_structure_store", None)
        if structure_store is None:
            return {}
        summary_getter = getattr(structure_store, "get_runtime_context_summary", None)
        if callable(summary_getter):
            try:
                summary = summary_getter()
                return dict(summary) if isinstance(summary, dict) else {}
            except Exception:
                pass

        revision = int(getattr(structure_store, "runtime_revision", 0) or 0)
        cache = getattr(self, "_hdb_lightweight_context_summary_cache", None)
        if isinstance(cache, dict) and int(cache.get("revision", -1)) == revision:
            summary = cache.get("summary", {})
            return dict(summary) if isinstance(summary, dict) else {}

        from hdb._context_metadata import (
            context_path_depth,
            extract_context_metadata,
            has_context_metadata,
        )

        structures = list(structure_store.iter_structures())
        structure_dbs = list(structure_store.iter_structure_dbs())
        contextual_structure_count = 0
        multi_context_structure_count = 0
        structure_context_path_depth_total = 0
        signature_context_pairs: dict[str, set[str]] = {}
        for structure in structures:
            if has_context_metadata(structure):
                contextual_structure_count += 1
                depth = context_path_depth(structure)
                structure_context_path_depth_total += depth
                if depth > 1:
                    multi_context_structure_count += 1
            context_meta = extract_context_metadata(structure)
            signature = str(structure.get("structure", {}).get("content_signature", "") or "").strip()
            context_key = str(
                context_meta.get("context_owner_structure_id")
                or context_meta.get("context_ref_object_id")
                or ""
            ).strip()
            if signature and context_key:
                signature_context_pairs.setdefault(signature, set()).add(context_key)
        same_content_multi_context_count = sum(
            1 for contexts in signature_context_pairs.values()
            if len(contexts) > 1
        )

        diff_entry_count = 0
        contextual_diff_entry_count = 0
        residual_diff_entry_count = 0
        diff_entry_with_memory_ref_count = 0
        for structure_db in structure_dbs:
            owner_structure_id = str(structure_db.get("owner_structure_id", "") or "")
            for entry in list(structure_db.get("diff_table", []) or []):
                if not isinstance(entry, dict):
                    continue
                diff_entry_count += 1
                if entry.get("memory_refs"):
                    diff_entry_with_memory_ref_count += 1
                if self.hdb._snapshot._is_contextual_diff_entry(entry, owner_structure_id=owner_structure_id):  # type: ignore[attr-defined]
                    contextual_diff_entry_count += 1
                if self.hdb._snapshot._is_residual_local_diff_entry(entry):  # type: ignore[attr-defined]
                    residual_diff_entry_count += 1

        summary = {
            "contextual_structure_count": int(contextual_structure_count),
            "multi_context_structure_count": int(multi_context_structure_count),
            "structure_context_path_depth_mean": round(
                float(structure_context_path_depth_total) / float(contextual_structure_count),
                8,
            ) if contextual_structure_count else 0.0,
            "same_content_multi_context_count": int(same_content_multi_context_count),
            "diff_entry_count": int(diff_entry_count),
            "contextual_diff_entry_count": int(contextual_diff_entry_count),
            "residual_diff_entry_count": int(residual_diff_entry_count),
            "diff_entry_with_memory_ref_count": int(diff_entry_with_memory_ref_count),
        }
        self._hdb_lightweight_context_summary_cache = {
            "revision": revision,
            "summary": dict(summary),
        }
        return summary

    def _run_state_pool_maintenance(self, trace_id: str, tick_id: str) -> dict:
        timing: dict[str, int] = {}
        phase_t0 = time.perf_counter()
        if bool(self._config.get("maintenance_lightweight_summary_enabled", True)):
            before_summary = self._state_pool_summary_lightweight()
        else:
            before_snapshot = self.pool.get_state_snapshot(
                trace_id=f"{trace_id}_maint_before",
                tick_id=tick_id,
                include_items=False,
                top_k=0,
            )["data"]["snapshot"]
            before_summary = before_snapshot.get("summary", {})
        timing["before_summary_ms"] = int((time.perf_counter() - phase_t0) * 1000)
        before_count = self.pool._history.size
        start_ms = int(time.time() * 1000)
        phase_t0 = time.perf_counter()
        result = self.pool.tick_maintain_state_pool(
            trace_id=f"{trace_id}_maint",
            tick_id=tick_id,
            apply_decay=True,
            apply_neutralization=True,
            apply_prune=True,
            apply_merge=True,
            enable_script_broadcast=False,
        )
        timing["pool_maintenance_ms"] = int((time.perf_counter() - phase_t0) * 1000)
        phase_t0 = time.perf_counter()
        if bool(self._config.get("maintenance_lightweight_summary_enabled", True)):
            after_summary = self._state_pool_summary_lightweight()
        else:
            after_snapshot = self.pool.get_state_snapshot(
                trace_id=f"{trace_id}_maint_after",
                tick_id=tick_id,
                include_items=False,
                top_k=0,
            )["data"]["snapshot"]
            after_summary = after_snapshot.get("summary", {})
        timing["after_summary_ms"] = int((time.perf_counter() - phase_t0) * 1000)
        phase_t0 = time.perf_counter()
        events = self._collect_history_events(before_count, start_ms)
        timing["history_events_ms"] = int((time.perf_counter() - phase_t0) * 1000)
        return {
            "summary": result["data"],
            "before_summary": before_summary,
            "after_summary": after_summary,
            "events": events,
            "timing": timing,
        }

    def _build_attention_memory_stub(self, trace_id: str, tick_id: str, *, focus_directives: list[dict] | None = None, modulation: dict | None = None) -> tuple[dict, dict]:
        modulation = modulation or {}
        base_top_n = int(self._config.get("attention_top_n", 16))
        effective_top_n = int(modulation.get("top_n", base_top_n) or base_top_n)
        result = self.attention.build_cam_from_pool(
            self.pool,
            trace_id=trace_id,
            tick_id=tick_id,
            top_n=effective_top_n,
            consume_energy=bool(self._config.get("attention_stub_consume_energy", True)),
            memory_energy_ratio=float(self._config.get("attention_memory_energy_ratio", 0.5)),
            focus_directives=focus_directives,
            modulation=modulation,
        )
        if not result.get("success"):
            return (
                {
                    "snapshot_id": f"{trace_id}_cam",
                    "object_type": "runtime_snapshot",
                    "sub_type": "cam_snapshot_error_fallback",
                    "schema_version": "1.1",
                    "trace_id": trace_id,
                    "tick_id": tick_id,
                    "summary": {"active_item_count": 0},
                    "top_items": [],
                },
                {"top_items": [], "structure_items": []},
            )

        data = result.get("data", {}) or {}
        cam_snapshot = data.get("cam_snapshot", {}) or {}
        attention_report = data.get("attention_report", {}) or {}
        if "memory_snapshot_summary" not in attention_report and "cam_snapshot_summary" in attention_report:
            attention_report["memory_snapshot_summary"] = attention_report.get("cam_snapshot_summary", {})
        return cam_snapshot, attention_report

    def _make_attention_memory_snapshot(self, *, selected_items: list[dict], trace_id: str, tick_id: str) -> dict:
        top_items = []
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
            "snapshot_id": f"{trace_id}_attention_memory",
            "object_type": "runtime_snapshot",
            "sub_type": "attention_memory_stub_snapshot",
            "schema_version": "1.1",
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
    def _attention_priority(item: dict) -> float:
        total_energy = float(item.get("er", 0.0)) + float(item.get("ev", 0.0))
        cp_abs = float(item.get("cp_abs", 0.0))
        salience = float(item.get("salience_score", 0.0))
        updated_at = float(item.get("updated_at", 0.0))
        return round(total_energy * 1.25 + cp_abs * 0.35 + salience * 0.15 + updated_at * 1e-12, 12)

    def _neutralize_packet_against_pool(self, packet: dict, trace_id: str, tick_id: str) -> dict:
        input_packet_summary = self._describe_stimulus_packet(packet)
        if not packet.get("sa_items") and not packet.get("csa_items"):
            return {
                "input_packet": input_packet_summary,
                "residual_packet": input_packet_summary,
                "residual_packet_raw": packet,
                "priority_events": [],
                "priority_diagnostics": [],
                "priority_summary": {
                    "priority_neutralized_item_count": 0,
                    "priority_event_count": 0,
                    "priority_diagnostic_count": 0,
                    "event_component_neutralization_count": 0,
                    "event_component_neutralization_er_added_sum": 0.0,
                    "event_component_neutralization_ev_added_sum": 0.0,
                    "event_component_cp_drop_sum": 0.0,
                    "input_total_er": round(float(input_packet_summary.get("total_er", 0.0)), 8),
                    "input_total_ev": round(float(input_packet_summary.get("total_ev", 0.0)), 8),
                    "residual_total_er": round(float(input_packet_summary.get("total_er", 0.0)), 8),
                    "residual_total_ev": round(float(input_packet_summary.get("total_ev", 0.0)), 8),
                "consumed_er": 0.0,
                "consumed_ev": 0.0,
                "input_flat_token_count": len(input_packet_summary.get("flat_tokens", [])),
                "residual_flat_token_count": len(input_packet_summary.get("flat_tokens", [])),
                "cut_metrics": {},
            },
        }

        before_count = self.pool._history.size
        start_ms = int(time.time() * 1000)
        neutralization_result = self.pool._priority_neutralize_stimulus_packet(
            stimulus_packet=packet,
            tick_number=self.pool._tick_counter + 1,
            trace_id=f"{trace_id}_cache_neutralize",
            tick_id=tick_id,
            source_module="observatory",
        )
        priority_events = self._collect_history_events(before_count, start_ms)
        if not priority_events:
            priority_events = [
                self._enrich_history_event(event)
                for event in neutralization_result.get("events", [])
            ]
        residual_packet = neutralization_result.get("residual_packet", packet)
        residual_packet_summary = self._describe_stimulus_packet(residual_packet)
        priority_diagnostics = list(neutralization_result.get("diagnostics", []))
        priority_cut_metrics = {
            str(key): int(value)
            for key, value in dict(neutralization_result.get("cut_metrics", {}) or {}).items()
            if str(key)
        }
        return {
            "input_packet": input_packet_summary,
            "residual_packet": residual_packet_summary,
            "residual_packet_raw": residual_packet,
            "priority_events": priority_events,
            "priority_diagnostics": priority_diagnostics,
            "priority_summary": {
                "priority_neutralized_item_count": int(neutralization_result.get("neutralized_item_count", 0)),
                "priority_event_count": len(priority_events),
                "priority_diagnostic_count": len(priority_diagnostics),
                "event_component_neutralization_count": int(neutralization_result.get("event_component_neutralization_count", 0) or 0),
                "event_component_neutralization_er_added_sum": round(float(neutralization_result.get("event_component_neutralization_er_added_sum", 0.0) or 0.0), 8),
                "event_component_neutralization_ev_added_sum": round(float(neutralization_result.get("event_component_neutralization_ev_added_sum", 0.0) or 0.0), 8),
                "event_component_cp_drop_sum": round(float(neutralization_result.get("event_component_cp_drop_sum", 0.0) or 0.0), 8),
                "input_total_er": round(float(input_packet_summary.get("total_er", 0.0)), 8),
                "input_total_ev": round(float(input_packet_summary.get("total_ev", 0.0)), 8),
                "residual_total_er": round(float(residual_packet_summary.get("total_er", 0.0)), 8),
                "residual_total_ev": round(float(residual_packet_summary.get("total_ev", 0.0)), 8),
                "consumed_er": round(float(input_packet_summary.get("total_er", 0.0)) - float(residual_packet_summary.get("total_er", 0.0)), 8),
                "consumed_ev": round(float(input_packet_summary.get("total_ev", 0.0)) - float(residual_packet_summary.get("total_ev", 0.0)), 8),
                "input_flat_token_count": len(input_packet_summary.get("flat_tokens", [])),
                "residual_flat_token_count": len(residual_packet_summary.get("flat_tokens", [])),
                "cut_metrics": priority_cut_metrics,
            },
        }

    def _apply_packet_to_pool(
        self,
        packet: dict,
        trace_id: str,
        tick_id: str,
        disable_priority_neutralization: bool = False,
        source_module: str = "observatory",
        collect_history_events: bool = True,
        enable_script_broadcast: bool = True,
        enable_brief_log: bool = True,
        compute_post_apply_summary: bool = True,
        clone_packet_for_safety: bool | None = None,
        enable_change_event_log: bool = True,
    ) -> tuple[dict, list[dict], dict]:
        if not packet.get("sa_items") and not packet.get("csa_items"):
            return {}, [], {
                "id": "",
                "object_type": "stimulus_packet",
                "sa_items": [],
                "csa_items": [],
                "grouped_sa_sequences": [],
                "energy_summary": {"total_er": 0.0, "total_ev": 0.0},
            }
        before_count = self.pool._history.size
        start_ms = int(time.time() * 1000)
        original_priority_flag = bool(self.pool._config.get("enable_priority_stimulus_neutralization", True))
        if disable_priority_neutralization:
            self.pool._config["enable_priority_stimulus_neutralization"] = False
        try:
            result = self.pool.apply_stimulus_packet(
                stimulus_packet=packet,
                trace_id=f"{trace_id}_pool_apply",
                tick_id=tick_id,
                source_module=source_module,
                enable_script_broadcast=enable_script_broadcast,
                enable_brief_log=enable_brief_log,
                compute_post_apply_summary=compute_post_apply_summary,
                clone_packet_for_safety=clone_packet_for_safety,
                enable_change_event_log=enable_change_event_log,
            )
        finally:
            if disable_priority_neutralization:
                self.pool._config["enable_priority_stimulus_neutralization"] = original_priority_flag
        history_events = self._collect_history_events(before_count, start_ms) if collect_history_events else []
        return (
            result.get("data", {}),
            history_events,
            result.get("data", {}).get("residual_stimulus_packet", packet),
        )

    def _insert_residual_tail_memory_projection_to_pool(
        self,
        packet: dict,
        *,
        trace_id: str,
        tick_id: str,
        source_packet_id: str = "",
        stimulus_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not bool(self._config.get("residual_tail_memory_projection_enabled", True)):
            return {"applied": False, "reason": "disabled"}
        if (
            bool(self._config.get("dedicated_memory_pool_enabled", False))
            and not bool(self._config.get("residual_memory_as_structure_enabled", True))
        ):
            return {"applied": False, "reason": "disabled_by_dedicated_memory_pool"}
        memory_id = str((stimulus_data or {}).get("episodic_memory_id", "") or "").strip()
        if not memory_id:
            return {"applied": False, "handled": False, "reason": "missing_episodic_memory_id"}
        memory_object = self._build_residual_tail_memory_projection(
            packet,
            memory_id=memory_id,
            trace_id=trace_id,
            tick_id=tick_id,
            source_packet_id=source_packet_id,
            stimulus_data=stimulus_data or {},
        )
        if not memory_object:
            return {
                "applied": False,
                "handled": True,
                "reason": "empty_or_below_threshold",
                "memory_id": memory_id,
            }
        before_count = self.pool._history.size
        start_ms = int(time.time() * 1000)
        result = self.pool.insert_runtime_node(
            runtime_object=memory_object,
            trace_id=f"{trace_id}_residual_tail_memory",
            tick_id=tick_id,
            allow_merge=True,
            source_module="observatory",
            reason="residual_tail_memory_projection",
            enable_brief_log=False,
            enable_detail_log=False,
            fast_ref_hit_energy_merge=bool(
                self._config.get("residual_tail_memory_projection_fast_ref_merge_enabled", True)
            ),
        )
        data = result.get("data", {}) if isinstance(result, dict) else {}
        success = bool(result.get("success", False)) if isinstance(result, dict) else False
        events = self._collect_history_events(before_count, start_ms)
        energy = memory_object.get("energy", {}) if isinstance(memory_object.get("energy", {}), dict) else {}
        memory_block = memory_object.get("memory", {}) if isinstance(memory_object.get("memory", {}), dict) else {}
        meta_ext = (
            memory_object.get("meta", {}).get("ext", {})
            if isinstance(memory_object.get("meta", {}).get("ext", {}), dict)
            else {}
        )
        return {
            "applied": bool(success),
            "handled": True,
            "reason": "inserted_or_merged" if success else "insert_failed",
            "memory_id": memory_id,
            "result": data,
            "events": events,
            "memory": {
                "id": memory_object.get("id", ""),
                "object_type": memory_object.get("object_type", ""),
                "sub_type": memory_object.get("sub_type", ""),
                "display": memory_object.get("content", {}).get("display", ""),
                "energy": dict(energy),
                "token_count": int(meta_ext.get("tail_token_count", 0) or 0),
                "full_memory_token_count": int(memory_block.get("token_count", 0) or 0),
                "source_packet_id": source_packet_id,
                "component_energy": dict(meta_ext.get("component_energy", {}) or {}),
            },
        }

    def _build_residual_tail_memory_projection(
        self,
        packet: dict,
        *,
        memory_id: str,
        trace_id: str,
        tick_id: str,
        source_packet_id: str = "",
        stimulus_data: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not isinstance(packet, dict) or (not packet.get("sa_items") and not packet.get("csa_items")):
            return None
        profile = self.cut_engine.build_sequence_profile_from_stimulus_packet(packet)
        sequence_groups = [group for group in list(profile.get("sequence_groups", []) or []) if isinstance(group, dict)]
        if not sequence_groups:
            return None
        total_er = 0.0
        total_ev = 0.0
        tail_units: list[dict[str, Any]] = []
        tail_unit_er_by_id: dict[str, float] = {}
        tail_unit_ev_by_id: dict[str, float] = {}
        for group in sequence_groups:
            group_index = group.get("group_index", len(tail_units))
            for unit in list(group.get("units", []) or []):
                if not isinstance(unit, dict):
                    continue
                unit_er = max(0.0, float(unit.get("er", 0.0) or 0.0))
                unit_ev = max(0.0, float(unit.get("ev", 0.0) or 0.0))
                total_er += unit_er
                total_ev += unit_ev
                unit_id = str(unit.get("unit_id", "") or unit.get("sa_id", "") or "").strip()
                if unit_id:
                    tail_unit_er_by_id[unit_id] = round(float(tail_unit_er_by_id.get(unit_id, 0.0) or 0.0) + unit_er, 8)
                    tail_unit_ev_by_id[unit_id] = round(float(tail_unit_ev_by_id.get(unit_id, 0.0) or 0.0) + unit_ev, 8)
                tail_units.append(
                    {
                        "unit_id": unit_id,
                        "token": str(unit.get("token", "") or unit.get("display_text", "") or ""),
                        "role": str(unit.get("unit_role", unit.get("role", "")) or ""),
                        "group_index": group_index,
                        "er": round(float(unit_er), 8),
                        "ev": round(float(unit_ev), 8),
                    }
                )
        total_er = round(float(total_er), 8)
        total_ev = round(float(total_ev), 8)
        if total_er <= 0.0 and total_ev <= 0.0:
            return None
        try:
            configured_floor = float(self._config.get("residual_tail_memory_projection_min_energy", 0.05) or 0.0)
        except Exception:
            configured_floor = 0.05
        try:
            pool_floor = min(
                float(getattr(self.pool, "_config", {}).get("er_elimination_threshold", 0.05) or 0.05),
                float(getattr(self.pool, "_config", {}).get("ev_elimination_threshold", 0.05) or 0.05),
            )
        except Exception:
            pool_floor = 0.05
        min_energy = max(0.0, configured_floor if configured_floor > 0 else pool_floor)
        if (total_er + total_ev) < min_energy:
            return None

        stimulus_data = stimulus_data or {}
        memory_material = stimulus_data.get("episodic_memory_material", {})
        if not isinstance(memory_material, dict):
            memory_material = {}
        full_sequence_groups = [
            group for group in list(memory_material.get("sequence_groups", []) or []) if isinstance(group, dict)
        ]
        if not full_sequence_groups:
            full_sequence_groups = sequence_groups
        full_semantic_display = format_semantic_sequence_groups(full_sequence_groups, context="stimulus")
        tail_semantic_display = format_semantic_sequence_groups(sequence_groups, context="stimulus")
        full_display_text = (
            str(stimulus_data.get("semantic_display_text", "") or "")
            or str(stimulus_data.get("episodic_display_text", "") or "")
            or str(memory_material.get("semantic_grouped_display_text", "") or "")
            or full_semantic_display
            or str(memory_material.get("grouped_display_text", "") or "")
            or format_sequence_groups(full_sequence_groups)
            or str(profile.get("display_text", "") or "")
            or str(memory_id)
        )
        tail_display_text = (
            tail_semantic_display
            or str(profile.get("semantic_display_text", "") or "")
            or format_sequence_groups(sequence_groups)
            or str(profile.get("display_text", "") or "")
        )
        try:
            max_display_chars = max(
                80,
                int(getattr(self.hdb, "_config", {}).get("runtime_memory_display_max_chars", 240) or 240),
            )
        except Exception:
            max_display_chars = 240
        runtime_display = full_display_text
        if len(runtime_display) > max_display_chars:
            runtime_display = f"{runtime_display[:max_display_chars]}...(len={len(full_display_text)})"

        flat_tokens = [str(token) for token in list(profile.get("flat_tokens", []) or []) if str(token)]
        full_flat_tokens = [
            str(unit.get("token", "") or unit.get("display_text", "") or "")
            for group in full_sequence_groups
            for unit in list(group.get("units", []) or [])
            if isinstance(unit, dict) and str(unit.get("token", "") or unit.get("display_text", "") or "")
        ]
        now_ms = int(time.time() * 1000)
        source_packet_id = str(source_packet_id or packet.get("id", "") or "")
        ext = {
            "source_em_id": memory_id,
            "memory_id": memory_id,
            "memory_kind": str(memory_material.get("memory_kind", "stimulus_packet") or "stimulus_packet"),
            "residual_origin_kind": "residual_tail_memory_projection",
            "residual_origin_entry_id": memory_id,
            "source_packet_id": source_packet_id,
            "tail_display_text": tail_display_text,
            "tail_content_signature": str(profile.get("content_signature", "") or ""),
            "tail_token_count": int(profile.get("token_count", len(flat_tokens)) or len(flat_tokens)),
            "hdb_backed": True,
            "runtime_only_residual": False,
            "projection_rule": "tail_energy_merged_to_full_episodic_memory_id",
            "created_from_trace_id": trace_id,
            "created_from_tick_id": tick_id,
            "component_energy": {
                "ownership_level": "sa_component_audit",
                "memory_id": memory_id,
                "tail_component_er_share": total_er,
                "tail_component_ev_share": total_ev,
                "tail_unit_count": int(profile.get("unit_count", 0) or len(flat_tokens)),
                "full_memory_unit_count": int(memory_material.get("unit_count", 0) or len(full_flat_tokens)),
                "tail_unit_er_by_id": dict(tail_unit_er_by_id),
                "tail_unit_ev_by_id": dict(tail_unit_ev_by_id),
                "tail_units": tail_units[:512],
            },
        }
        memory_block = {
            "memory_id": memory_id,
            "event_summary": "stimulus-level retrieval-storage",
            "structure_refs": list(memory_material.get("ordered_structure_ids", []) or []),
            "group_refs": [],
            "backing_structure_id": "",
            "grouped_display_text": full_display_text,
            "semantic_grouped_display_text": full_semantic_display or full_display_text,
            "sequence_groups": full_sequence_groups,
            "display_text": runtime_display,
            "semantic_display_text": full_semantic_display or runtime_display,
            "full_display_text": full_display_text,
            "tail_display_text": tail_display_text,
            "tail_sequence_groups": sequence_groups,
            "token_count": int(len(full_flat_tokens) or len(flat_tokens)),
            "memory_created_at": now_ms,
        }
        return {
            "id": memory_id,
            "object_type": "em",
            "sub_type": "stimulus_tail_memory_runtime",
            "schema_version": "runtime",
            "content": {
                "raw": runtime_display,
                "display": runtime_display,
                "normalized": runtime_display,
            },
            "energy": {
                "er": total_er,
                "ev": total_ev,
                "ownership_level": "sa_component_audit",
                "computed_from_residual_tail_sa": True,
            },
            "memory": memory_block,
            "source": {
                "module": "observatory",
                "interface": "_insert_residual_tail_memory_projection_to_pool",
                "origin": "residual_tail_memory_projection",
                "origin_id": memory_id,
                "parent_ids": [source_packet_id] if source_packet_id else [],
            },
            "ext": dict(ext),
            "meta": {
                "confidence": 1.0,
                "field_registry_version": "runtime",
                "debug": {},
                "ext": dict(ext),
            },
            "created_at": now_ms,
            "updated_at": now_ms,
        }

    def _insert_runtime_residual_package_to_pool(
        self,
        packet: dict,
        *,
        trace_id: str,
        tick_id: str,
        source_packet_id: str = "",
    ) -> dict[str, Any]:
        if not bool(self._config.get("runtime_residual_package_enabled", True)):
            return {"applied": False, "reason": "disabled"}
        package = self._build_runtime_residual_package(
            packet,
            trace_id=trace_id,
            tick_id=tick_id,
            source_packet_id=source_packet_id,
        )
        if not package:
            return {"applied": False, "reason": "empty_or_below_threshold"}
        before_count = self.pool._history.size
        start_ms = int(time.time() * 1000)
        result = self.pool.insert_runtime_node(
            runtime_object=package,
            trace_id=f"{trace_id}_runtime_residual_package",
            tick_id=tick_id,
            allow_merge=True,
            source_module="observatory",
            reason="stimulus_runtime_residual_package",
        )
        data = result.get("data", {}) if isinstance(result, dict) else {}
        success = bool(result.get("success", False)) if isinstance(result, dict) else False
        immediate_promotion: dict[str, Any] | None = None
        if (
            success
            and bool(self._config.get("runtime_residual_package_high_energy_promotion_enabled", True))
            and bool(self._config.get("runtime_residual_package_immediate_high_energy_promotion_enabled", True))
        ):
            try:
                min_energy = max(
                    0.0,
                    float(self._config.get("runtime_residual_package_high_energy_promotion_min_energy", 1.0) or 1.0),
                )
            except Exception:
                min_energy = 1.0
            energy = package.get("energy", {}) if isinstance(package.get("energy", {}), dict) else {}
            package_total_energy = (
                max(0.0, float(energy.get("er", 0.0) or 0.0))
                + max(0.0, float(energy.get("ev", 0.0) or 0.0))
            )
            target_item_id = str(data.get("target_item_id", "") or data.get("item_id", "") or "").strip()
            if package_total_energy >= min_energy and target_item_id:
                state_item = self.pool._store.get(target_item_id)  # type: ignore[attr-defined]
                if isinstance(state_item, dict) and self._is_runtime_only_residual_item(state_item):
                    immediate_promotion = self._promote_runtime_residual_state_item(
                        state_item=state_item,
                        trace_id=trace_id,
                        tick_id=tick_id,
                        now_ms=int(time.time() * 1000),
                        reason="immediate_high_energy_runtime_residual",
                    )
        events = self._collect_history_events(before_count, start_ms)
        return {
            "applied": bool(success),
            "reason": "inserted_or_merged" if success else "insert_failed",
            "result": data,
            "events": events,
            "immediate_promotion": immediate_promotion or {},
            "package": {
                "id": package.get("id", ""),
                "object_type": package.get("object_type", ""),
                "sub_type": package.get("sub_type", ""),
                "display": package.get("content", {}).get("display", ""),
                "energy": dict(package.get("energy", {}) or {}),
                "structure": {
                    "content_signature": package.get("structure", {}).get("content_signature", ""),
                    "token_count": package.get("structure", {}).get("token_count", 0),
                    "flat_tokens": list(package.get("structure", {}).get("flat_tokens", []) or [])[:32],
                    "ext": dict(package.get("structure", {}).get("ext", {}) or {}),
                },
            },
        }

    def _promote_attention_runtime_residual_packages(
        self,
        *,
        attention_snapshot: dict[str, Any],
        trace_id: str,
        tick_id: str,
        now_ms: int | None = None,
    ) -> dict[str, Any]:
        if not bool(self._config.get("runtime_residual_package_attention_promotion_enabled", True)):
            return {"enabled": False, "attempted_count": 0, "promoted_count": 0, "items": []}
        if not isinstance(attention_snapshot, dict):
            return {"enabled": True, "attempted_count": 0, "promoted_count": 0, "items": [], "reason": "missing_attention_snapshot"}

        max_per_tick = max(0, int(self._config.get("runtime_residual_package_attention_promotion_max_per_tick", 2) or 0))
        if max_per_tick <= 0:
            return {"enabled": True, "attempted_count": 0, "promoted_count": 0, "items": [], "reason": "max_per_tick_zero"}

        items: list[dict[str, Any]] = []
        attempted = 0
        promoted = 0
        seen_item_ids: set[str] = set()

        candidate_rows: list[dict[str, Any]] = []
        for row in list(attention_snapshot.get("top_items", []) or []):
            if isinstance(row, dict) and self._is_runtime_only_residual_item(row):
                candidate_rows.append({**row, "promotion_trigger": "attention_selected"})
        if bool(self._config.get("runtime_residual_package_high_energy_promotion_enabled", True)):
            min_energy = max(0.0, float(self._config.get("runtime_residual_package_high_energy_promotion_min_energy", 1.0) or 1.0))
            for pool_item in self._iter_high_energy_runtime_residual_packages(min_total_energy=min_energy):
                candidate_rows.append({**pool_item, "item_id": pool_item.get("id", ""), "promotion_trigger": "high_energy_runtime_residual"})

        for row in candidate_rows:
            if attempted >= max_per_tick:
                break
            item_id = str(row.get("item_id", "") or row.get("id", "") or "").strip()
            if not item_id or item_id in seen_item_ids:
                continue
            seen_item_ids.add(item_id)
            state_item = self.pool._store.get(item_id)  # type: ignore[attr-defined]
            if not isinstance(state_item, dict) or not self._is_runtime_only_residual_item(state_item):
                continue

            attempted += 1
            item_result = self._promote_runtime_residual_state_item(
                state_item=state_item,
                trace_id=trace_id,
                tick_id=tick_id,
                now_ms=now_ms,
                reason=str(row.get("promotion_trigger", "") or "attention_selected_runtime_residual_package"),
            )
            if item_result.get("promoted"):
                promoted += 1
            items.append(item_result)

        return {
            "enabled": True,
            "attempted_count": int(attempted),
            "promoted_count": int(promoted),
            "exact_rebind_count": int(sum(1 for item in items if str(item.get("fast_path", "") or "") == "exact_rebind" and bool(item.get("promoted", False)))),
            "full_identity_count": int(sum(1 for item in items if str(item.get("fast_path", "") or "") == "full_identity" and bool(item.get("promoted", False)))),
            "hdb_fallback_count": int(sum(1 for item in items if bool(item.get("hdb_fallback", False)))),
            "items": items,
        }

    def _iter_high_energy_runtime_residual_packages(self, *, min_total_energy: float) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        try:
            pool_items = list(self.pool._store.get_all())  # type: ignore[attr-defined]
        except Exception:
            pool_items = []
        for item in pool_items:
            if not isinstance(item, dict) or not self._is_runtime_only_residual_item(item):
                continue
            energy = item.get("energy", {}) if isinstance(item.get("energy", {}), dict) else {}
            total = max(0.0, float(energy.get("er", 0.0) or 0.0)) + max(0.0, float(energy.get("ev", 0.0) or 0.0))
            if total < min_total_energy:
                continue
            candidates.append(item)
        candidates.sort(
            key=lambda row: -(
                max(0.0, float((row.get("energy", {}) or {}).get("er", 0.0) or 0.0))
                + max(0.0, float((row.get("energy", {}) or {}).get("ev", 0.0) or 0.0))
            )
        )
        return candidates

    def _promote_runtime_residual_state_item(
        self,
        *,
        state_item: dict[str, Any],
        trace_id: str,
        tick_id: str,
        now_ms: int | None,
        reason: str,
    ) -> dict[str, Any]:
        item_id = str(state_item.get("id", "") or state_item.get("item_id", "") or "").strip()
        runtime_ref_id = str(state_item.get("ref_object_id", "") or "").strip()
        ref_snapshot = state_item.get("ref_snapshot", {}) if isinstance(state_item.get("ref_snapshot", {}), dict) else {}
        sequence_groups = [dict(group) for group in list(ref_snapshot.get("sequence_groups", []) or []) if isinstance(group, dict)]
        if not sequence_groups:
            return {
                "item_id": item_id,
                "runtime_ref_id": runtime_ref_id,
                "promoted": False,
                "reason": "missing_sequence_groups",
            }
        exact_rebind = self._try_promote_runtime_residual_exact_rebind(
            state_item=state_item,
            item_id=item_id,
            runtime_ref_id=runtime_ref_id,
            sequence_groups=sequence_groups,
            trace_id=trace_id,
            tick_id=tick_id,
            now_ms=now_ms,
            reason=reason,
        )
        if isinstance(exact_rebind, dict) and exact_rebind.get("promoted"):
            return exact_rebind
        exact_rebind_probe_skipped = bool(isinstance(exact_rebind, dict) and exact_rebind.get("probe_skipped", False))

        full_identity = self._try_promote_runtime_residual_full_identity(
            state_item=state_item,
            item_id=item_id,
            runtime_ref_id=runtime_ref_id,
            sequence_groups=sequence_groups,
            trace_id=trace_id,
            tick_id=tick_id,
            now_ms=now_ms,
            reason=reason,
        )
        if isinstance(full_identity, dict) and full_identity.get("promoted"):
            return full_identity

        packet = self._build_stimulus_packet_from_sequence_groups(
            sequence_groups=sequence_groups,
            trace_id=f"{trace_id}_runtime_residual_promote",
            tick_id=tick_id,
            packet_type="runtime_residual_promotion",
            origin="runtime_residual_package_attention_promotion",
            origin_id=runtime_ref_id,
        )
        if not packet.get("sa_items") and not packet.get("csa_items"):
            return {
                "item_id": item_id,
                "runtime_ref_id": runtime_ref_id,
                "promoted": False,
                "reason": "empty_promotion_packet",
            }

        try:
            hdb_result = self.hdb.run_stimulus_level_retrieval_storage(
                stimulus_packet=packet,
                trace_id=f"{trace_id}_runtime_residual_promote",
                tick_id=tick_id,
                now_ms=now_ms,
                enable_storage=True,
                enable_new_structure_creation=True,
                max_rounds=1,
                source_module="runtime_residual_package",
                metadata={"reason": reason, "runtime_ref_id": runtime_ref_id, "state_item_id": item_id, "tick_number": int(self.tick_counter)},
            )
        except Exception as exc:
            return {
                "item_id": item_id,
                "runtime_ref_id": runtime_ref_id,
                "promoted": False,
                "reason": "hdb_exception",
                "error": str(exc),
            }

        data = hdb_result.get("data", {}) if isinstance(hdb_result, dict) else {}
        structure_id = self._select_promoted_runtime_residual_structure_id(data)
        if not structure_id:
            return {
                "item_id": item_id,
                "runtime_ref_id": runtime_ref_id,
                "promoted": False,
                "reason": "no_hdb_structure_resolved",
                "hdb_code": str((hdb_result or {}).get("code", "")) if isinstance(hdb_result, dict) else "",
                "matched_structure_ids": list(data.get("matched_structure_ids", []) or [])[:8] if isinstance(data, dict) else [],
                "new_structure_ids": list(data.get("new_structure_ids", []) or [])[:8] if isinstance(data, dict) else [],
            }

        structure_obj = self.hdb._structure_store.get(structure_id)
        if not isinstance(structure_obj, dict):
            return {
                "item_id": item_id,
                "runtime_ref_id": runtime_ref_id,
                "promoted": False,
                "reason": "resolved_structure_missing",
                "structure_id": structure_id,
            }

        self._rebind_runtime_residual_state_item_to_structure(
            state_item=state_item,
            structure_obj=structure_obj,
            runtime_ref_id=runtime_ref_id,
            trace_id=trace_id,
            tick_id=tick_id,
            reason=reason,
        )
        signature_for_cache = ""
        if exact_rebind_probe_skipped:
            try:
                signature_for_cache = str(self.cut_engine.sequence_groups_to_signature(sequence_groups) or "")
            except Exception:
                signature_for_cache = ""
            if signature_for_cache:
                self._runtime_residual_exact_rebind_cache[signature_for_cache] = structure_id
        return {
            "item_id": item_id,
            "runtime_ref_id": runtime_ref_id,
            "promoted": True,
            "structure_id": structure_id,
            "created": structure_id in set(str(x) for x in list(data.get("new_structure_ids", []) or [])),
            "matched": structure_id in set(str(x) for x in list(data.get("matched_structure_ids", []) or [])),
            "hdb_fallback": True,
            "exact_rebind_probe_skipped": exact_rebind_probe_skipped,
            "exact_rebind_cache_learned": bool(signature_for_cache),
            "display": str((structure_obj.get("structure", {}) or {}).get("display_text", "") or structure_obj.get("content", {}).get("display", "")),
        }

    def _try_promote_runtime_residual_exact_rebind(
        self,
        *,
        state_item: dict[str, Any],
        item_id: str,
        runtime_ref_id: str,
        sequence_groups: list[dict],
        trace_id: str,
        tick_id: str,
        now_ms: int | None,
        reason: str,
    ) -> dict[str, Any] | None:
        if not bool(self._config.get("runtime_residual_package_exact_rebind_fast_path_enabled", True)):
            return None
        try:
            profile = self.cut_engine.build_sequence_profile_from_groups(sequence_groups)
        except Exception as exc:
            return {
                "item_id": item_id,
                "runtime_ref_id": runtime_ref_id,
                "promoted": False,
                "reason": "exact_rebind_profile_error",
                "fast_path": "exact_rebind",
                "hdb_fallback": True,
                "error": str(exc),
            }
        signature = str(profile.get("content_signature", "") or "")
        if not signature:
            return None
        cached_structure_id = str(self._runtime_residual_exact_rebind_cache.get(signature, "") or "")
        if cached_structure_id:
            existing = self.hdb._structure_store.get(cached_structure_id)
            if isinstance(existing, dict):
                return self._finish_runtime_residual_exact_rebind(
                    state_item=state_item,
                    item_id=item_id,
                    runtime_ref_id=runtime_ref_id,
                    structure_obj=existing,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    now_ms=now_ms,
                    reason=reason,
                    cache_hit=True,
                )
            self._runtime_residual_exact_rebind_cache.pop(signature, None)
        if not bool(self._config.get("runtime_residual_package_exact_rebind_probe_hdb_on_miss_enabled", False)):
            return {
                "item_id": item_id,
                "runtime_ref_id": runtime_ref_id,
                "promoted": False,
                "reason": "exact_rebind_cache_miss_probe_disabled",
                "probe_skipped": True,
                "hdb_fallback": True,
            }
        try:
            existing = find_exact_structure_by_signature(
                signature=signature,
                structure_store=self.hdb._structure_store,
                pointer_index=self.hdb._pointer_index,
                cut_engine=self.cut_engine,
                expected_tokens=list(profile.get("flat_tokens", []) or []),
                expected_sequence_groups=list(profile.get("sequence_groups", []) or []),
                expected_context={},
                strict_context_owner_match=False,
                strict_context_ref_match=False,
                require_context_free=True,
            )
        except Exception as exc:
            return {
                "item_id": item_id,
                "runtime_ref_id": runtime_ref_id,
                "promoted": False,
                "reason": "exact_rebind_lookup_error",
                "fast_path": "exact_rebind",
                "hdb_fallback": True,
                "error": str(exc),
            }
        if not isinstance(existing, dict):
            return None

        return self._finish_runtime_residual_exact_rebind(
            state_item=state_item,
            item_id=item_id,
            runtime_ref_id=runtime_ref_id,
            structure_obj=existing,
            trace_id=trace_id,
            tick_id=tick_id,
            now_ms=now_ms,
            reason=reason,
            cache_hit=False,
        )

    def _try_promote_runtime_residual_full_identity(
        self,
        *,
        state_item: dict[str, Any],
        item_id: str,
        runtime_ref_id: str,
        sequence_groups: list[dict],
        trace_id: str,
        tick_id: str,
        now_ms: int | None,
        reason: str,
    ) -> dict[str, Any] | None:
        if not bool(self._config.get("runtime_residual_package_full_identity_promotion_enabled", True)):
            return None
        try:
            profile = self.cut_engine.build_sequence_profile_from_groups(sequence_groups)
        except Exception as exc:
            return {
                "item_id": item_id,
                "runtime_ref_id": runtime_ref_id,
                "promoted": False,
                "reason": "full_identity_profile_error",
                "fast_path": "full_identity",
                "hdb_fallback": True,
                "error": str(exc),
            }
        if not isinstance(profile, dict) or not profile.get("sequence_groups"):
            return None

        canonical_profile = self._growth_projection_canonical_profile(profile)
        signature = str(canonical_profile.get("content_signature", "") or "")
        if not signature:
            return None
        existing = None
        try:
            existing = find_exact_structure_by_signature(
                signature=signature,
                structure_store=self.hdb._structure_store,
                pointer_index=self.hdb._pointer_index,
                cut_engine=self.cut_engine,
                expected_tokens=list(canonical_profile.get("flat_tokens", []) or []),
                expected_sequence_groups=list(canonical_profile.get("sequence_groups", []) or []),
                expected_context={},
                strict_context_owner_match=False,
                strict_context_ref_match=False,
                require_context_free=True,
            )
        except Exception as exc:
            return {
                "item_id": item_id,
                "runtime_ref_id": runtime_ref_id,
                "promoted": False,
                "reason": "full_identity_lookup_error",
                "fast_path": "full_identity",
                "hdb_fallback": True,
                "error": str(exc),
            }
        created = False
        structure_obj = existing if isinstance(existing, dict) else None
        if structure_obj is None:
            if not bool(self._config.get("runtime_residual_package_full_identity_create_enabled", True)):
                return {
                    "item_id": item_id,
                    "runtime_ref_id": runtime_ref_id,
                    "promoted": False,
                    "reason": "full_identity_create_disabled",
                    "fast_path": "full_identity",
                    "hdb_fallback": True,
                }
            energy = state_item.get("energy", {}) if isinstance(state_item.get("energy", {}), dict) else {}
            source_er = max(0.0, float(energy.get("er", 0.0) or 0.0))
            source_ev = max(0.0, float(energy.get("ev", 0.0) or 0.0))
            base_weight = self._growth_projection_base_weight(source_er=source_er, delta_ev=source_ev)
            canonical_profile_for_create = dict(canonical_profile)
            exact_probe_is_final = bool(canonical_profile_for_create.pop("_growth_projection_exact_probe_is_final", False))
            skip_create_exact_lookup = bool(
                self._config.get("growth_projection_skip_create_exact_lookup_after_probe_enabled", True)
                and exact_probe_is_final
            )
            ext = dict(canonical_profile_for_create.get("ext", {}) or {})
            for key in ("context_ref_object_id", "context_ref_object_type", "context_owner_structure_id", "context_path_ids"):
                ext.pop(key, None)
            ext.update(
                {
                    "kind": "runtime_residual_full_identity_promotion",
                    "runtime_residual_promotion": True,
                    "runtime_residual_full_identity": True,
                    "runtime_residual_ref_id": str(runtime_ref_id or ""),
                    "runtime_residual_source_item_id": str(item_id or ""),
                    "runtime_residual_reason": str(reason or ""),
                    "context_free_identity": True,
                }
            )
            try:
                batch_ctx = (
                    self.hdb._structure_store.batch_persistence(flush=self.hdb._should_flush_deferred_persistence())
                    if bool(self.hdb._config.get("deferred_persistence_enabled", True))
                    else nullcontext()
                )
                with batch_ctx:
                    result = resolve_or_create_structure_from_profile(
                        profile={**dict(profile), "ext": ext},
                        canonical_profile={**canonical_profile_for_create, "ext": ext},
                        structure_store=self.hdb._structure_store,
                        pointer_index=self.hdb._pointer_index,
                        cut_engine=self.cut_engine,
                        trace_id=f"{trace_id}_runtime_residual_full_identity",
                        tick_id=tick_id,
                        confidence=0.68,
                        origin="runtime_residual_full_identity_promotion",
                        origin_id=runtime_ref_id or item_id,
                        parent_ids=[],
                        base_weight=base_weight,
                        ext=ext,
                        source_interface="observatory_runtime_residual_full_identity_promotion",
                        strict_context_owner_match=False,
                        strict_context_ref_match=False,
                        require_context_free=True,
                        skip_exact_lookup=skip_create_exact_lookup,
                    )
            except Exception as exc:
                return {
                    "item_id": item_id,
                    "runtime_ref_id": runtime_ref_id,
                    "promoted": False,
                    "reason": "full_identity_create_error",
                    "fast_path": "full_identity",
                    "hdb_fallback": True,
                    "error": str(exc),
                }
            structure_obj = result.get("structure") if isinstance(result, dict) else None
            if not isinstance(structure_obj, dict):
                return {
                    "item_id": item_id,
                    "runtime_ref_id": runtime_ref_id,
                    "promoted": False,
                    "reason": "full_identity_create_no_structure",
                    "fast_path": "full_identity",
                    "hdb_fallback": True,
                }
            created = bool(result.get("created", False)) if isinstance(result, dict) else True

        return self._finish_runtime_residual_exact_rebind(
            state_item=state_item,
            item_id=item_id,
            runtime_ref_id=runtime_ref_id,
            structure_obj=structure_obj,
            trace_id=trace_id,
            tick_id=tick_id,
            now_ms=now_ms,
            reason=reason,
            cache_hit=False,
            fast_path="full_identity",
            created=created,
        )

    def _finish_runtime_residual_exact_rebind(
        self,
        *,
        state_item: dict[str, Any],
        item_id: str,
        runtime_ref_id: str,
        structure_obj: dict[str, Any],
        trace_id: str,
        tick_id: str,
        now_ms: int | None,
        reason: str,
        cache_hit: bool,
        fast_path: str = "exact_rebind",
        created: bool = False,
    ) -> dict[str, Any] | None:
        existing = structure_obj
        structure_id = str(existing.get("id", "") or "").strip()
        if not structure_id:
            return None
        structure_block = existing.get("structure", {}) if isinstance(existing.get("structure", {}), dict) else {}
        signature = str(structure_block.get("content_signature", "") or "")
        if signature:
            self._runtime_residual_exact_rebind_cache[signature] = structure_id
        try:
            energy = state_item.get("energy", {}) if isinstance(state_item.get("energy", {}), dict) else {}
            reality_support = max(0.0, float(energy.get("er", 0.0) or 0.0))
            virtual_support = max(0.0, float(energy.get("ev", 0.0) or 0.0))
            batch_ctx = (
                self.hdb._structure_store.batch_persistence(flush=self.hdb._should_flush_deferred_persistence())
                if bool(self.hdb._config.get("deferred_persistence_enabled", True))
                else nullcontext()
            )
            with batch_ctx:
                self.hdb._weight.mark_structure_match(
                    existing,
                    match_score=1.0,
                    reality_support=reality_support,
                    virtual_support=virtual_support,
                    now_ms=now_ms,
                )
                self.hdb._structure_store.update_structure(existing)
        except Exception:
            pass
        self._rebind_runtime_residual_state_item_to_structure(
            state_item=state_item,
            structure_obj=existing,
            runtime_ref_id=runtime_ref_id,
            trace_id=trace_id,
            tick_id=tick_id,
            reason=reason,
        )
        return {
            "item_id": item_id,
            "runtime_ref_id": runtime_ref_id,
            "promoted": True,
            "structure_id": structure_id,
            "created": bool(created),
            "matched": not bool(created),
            "fast_path": str(fast_path or "exact_rebind"),
            "cache_hit": bool(cache_hit),
            "hdb_fallback": False,
            "display": str((existing.get("structure", {}) or {}).get("display_text", "") or existing.get("content", {}).get("display", "")),
        }

    def _build_stimulus_packet_from_sequence_groups(
        self,
        *,
        sequence_groups: list[dict],
        trace_id: str,
        tick_id: str,
        packet_type: str,
        origin: str,
        origin_id: str,
    ) -> dict[str, Any]:
        sa_items: list[dict[str, Any]] = []
        grouped: list[dict[str, Any]] = []
        total_er = 0.0
        total_ev = 0.0
        for group_index, group in enumerate(sequence_groups):
            if not isinstance(group, dict):
                continue
            units_out: list[dict[str, Any]] = []
            source_type = str(group.get("source_type", "runtime_residual") or "runtime_residual")
            origin_frame_id = str(group.get("origin_frame_id", "") or origin_id or f"{packet_type}_{group_index}")
            group_sa_ids: list[str] = []
            for seq_index, unit in enumerate(list(group.get("units", []) or [])):
                if not isinstance(unit, dict):
                    continue
                token = str(unit.get("token", unit.get("display_text", "")) or "")
                if token == "":
                    continue
                unit_id = str(unit.get("unit_id", "") or unit.get("id", "") or f"sa_promote_{group_index}_{seq_index}")
                er = max(0.0, float(unit.get("er", unit.get("total_er", 0.0)) or 0.0))
                ev = max(0.0, float(unit.get("ev", unit.get("total_ev", 0.0)) or 0.0))
                total_er += er
                total_ev += ev
                packet_context = {
                    "group_index": group_index,
                    "source_group_index": int(group.get("source_group_index", group.get("group_index", group_index)) or group_index),
                    "sequence_index": seq_index,
                    "source_type": source_type,
                    "origin_frame_id": origin_frame_id,
                    "order_sensitive": bool(group.get("order_sensitive", unit.get("order_sensitive", False))),
                    "string_unit_kind": str(group.get("string_unit_kind", unit.get("string_unit_kind", "")) or ""),
                    "string_token_text": str(group.get("string_token_text", unit.get("string_token_text", "")) or ""),
                }
                sa_obj = {
                    "id": unit_id,
                    "object_type": "sa",
                    "content": {
                        "raw": token,
                        "display": str(unit.get("display_text", "") or token),
                        "value_type": str(unit.get("value_type", "discrete") or "discrete"),
                    },
                    "stimulus": {
                        "role": str(unit.get("unit_role", unit.get("role", "feature")) or "feature"),
                        "modality": str(unit.get("modality", "text") or "text"),
                    },
                    "energy": {"er": er, "ev": ev},
                    "source": {
                        "module": "observatory",
                        "interface": "_build_stimulus_packet_from_sequence_groups",
                        "origin": origin,
                        "origin_id": origin_id,
                        "parent_ids": [origin_id] if origin_id else [],
                    },
                    "ext": {"packet_context": packet_context},
                }
                for key in ("attribute_name", "attribute_value", "anchor_sa_id", "bundle_anchor_unit_id"):
                    if unit.get(key, None) not in ("", None, [], {}):
                        sa_obj["content" if key in {"attribute_name", "attribute_value"} else "ext"][key] = unit.get(key)
                sa_items.append(sa_obj)
                group_sa_ids.append(unit_id)
                units_out.append(
                    {
                        "unit_id": unit_id,
                        "token": token,
                        "display_text": str(unit.get("display_text", "") or token),
                        "unit_role": str(unit.get("unit_role", unit.get("role", "feature")) or "feature"),
                        "er": er,
                        "ev": ev,
                        "sequence_index": seq_index,
                    }
                )
            if units_out:
                grouped.append(
                    {
                        "group_index": group_index,
                        "source_type": source_type,
                        "origin_frame_id": origin_frame_id,
                        "sa_ids": group_sa_ids,
                        "csa_ids": [],
                        "tokens": [str(unit.get("token", "") or "") for unit in units_out],
                        "units": units_out,
                        "order_sensitive": bool(group.get("order_sensitive", False)),
                        "string_unit_kind": str(group.get("string_unit_kind", "") or ("char_sequence" if group.get("string_token_text") else "")),
                        "string_token_text": str(group.get("string_token_text", "") or ""),
                    }
                )

        return {
            "id": f"spkt_runtime_residual_promotion_{hashlib.sha1((origin_id + trace_id).encode('utf-8')).hexdigest()[:16]}",
            "object_type": "stimulus_packet",
            "packet_type": packet_type,
            "trace_id": trace_id,
            "tick_id": tick_id,
            "sa_items": sa_items,
            "csa_items": [],
            "grouped_sa_sequences": grouped,
            "energy_summary": {"total_er": round(total_er, 8), "total_ev": round(total_ev, 8)},
        }

    @staticmethod
    def _select_promoted_runtime_residual_structure_id(stimulus_data: dict[str, Any]) -> str:
        if not isinstance(stimulus_data, dict):
            return ""
        for key in ("matched_structure_ids", "new_structure_ids"):
            values = [str(value) for value in list(stimulus_data.get(key, []) or []) if str(value)]
            if values:
                return values[-1]
        for projection in list(stimulus_data.get("runtime_projection_structures", []) or []):
            if not isinstance(projection, dict):
                continue
            structure_id = str(projection.get("structure_id", "") or "").strip()
            if structure_id:
                return structure_id
        values = [str(value) for value in list(stimulus_data.get("seeded_atomic_structure_ids", []) or []) if str(value)]
        if values:
            return values[-1]
        for detail in list(((stimulus_data.get("debug", {}) or {}).get("round_details", []) or [])):
            if not isinstance(detail, dict):
                continue
            for key in ("created_fresh_structure", "created_residual_structure", "created_common_structure", "selected_match"):
                block = detail.get(key, {}) if isinstance(detail.get(key, {}), dict) else {}
                structure_id = str(block.get("structure_id", "") or "").strip()
                if structure_id:
                    return structure_id
        return ""

    def _rebind_runtime_residual_state_item_to_structure(
        self,
        *,
        state_item: dict[str, Any],
        structure_obj: dict[str, Any],
        runtime_ref_id: str,
        trace_id: str,
        tick_id: str,
        reason: str,
    ) -> None:
        structure_id = str(structure_obj.get("id", "") or "").strip()
        if not structure_id:
            return
        structure_block = structure_obj.get("structure", {}) if isinstance(structure_obj.get("structure", {}), dict) else {}
        content_block = structure_obj.get("content", {}) if isinstance(structure_obj.get("content", {}), dict) else {}
        display = format_semantic_sequence_groups(structure_block.get("sequence_groups", []), context="stimulus") or str(
            structure_block.get("semantic_display_text", "")
            or structure_block.get("display_text", "")
            or content_block.get("display", "")
            or content_block.get("raw", "")
            or structure_id
        )
        aliases = [str(value) for value in list(state_item.get("ref_alias_ids", []) or []) if str(value)]
        for value in (runtime_ref_id, structure_id):
            if value and value not in aliases:
                aliases.append(value)
        structure_ext = dict(structure_block.get("ext", {}) or {}) if isinstance(structure_block.get("ext", {}), dict) else {}
        structure_ext.update(
            {
                "runtime_only_residual": False,
                "hdb_backed": True,
                "promotion_status": "promoted_hdb_backed",
                "promoted_from_runtime_ref_id": runtime_ref_id,
                "promoted_trace_id": trace_id,
                "promoted_tick_id": tick_id,
                "promotion_reason": reason,
            }
        )
        if bool(structure_ext.get("runtime_residual_full_identity", False)):
            structure_ext["runtime_residual_full_identity"] = True
            structure_ext["context_free_identity"] = True
        previous_context = extract_context_metadata(state_item)
        previous_residual = extract_residual_metadata(state_item)
        provenance_parent_ids = [str(value) for value in list(previous_context.get("context_path_ids", []) or []) if str(value)]
        source_block = state_item.get("source", {}) if isinstance(state_item.get("source", {}), dict) else {}
        for value in list(source_block.get("parent_ids", []) or []):
            text = str(value or "").strip()
            if text and text not in provenance_parent_ids:
                provenance_parent_ids.append(text)
        context_free_meta = build_context_metadata()
        state_item["ref_object_type"] = "st"
        state_item["ref_object_id"] = structure_id
        state_item["ref_alias_ids"] = aliases
        state_item["sub_type"] = "st_runtime_item"
        state_item["semantic_signature"] = str(structure_obj.get("semantic_signature", "") or structure_block.get("semantic_signature", "") or "")
        state_item["semantic_context_key"] = semantic_context_key_from_parts(
            semantic_signature=state_item.get("semantic_signature", ""),
            role="",
            attribute_name="",
        )
        state_item["updated_at"] = int(time.time() * 1000)
        state_item["trace_id"] = trace_id
        state_item["tick_id"] = tick_id
        state_item["ref_snapshot"] = {
            **dict(state_item.get("ref_snapshot", {}) or {}),
            "content_display": display,
            "content_display_detail": display,
            "content_signature": str(structure_block.get("content_signature", "") or ""),
            "token_count": int(structure_block.get("token_count", len(structure_block.get("flat_tokens", []) or [])) or 0),
            "member_count": len(structure_block.get("member_refs", []) or []),
            "flat_tokens": list(structure_block.get("flat_tokens", []) or []),
            "sequence_groups": list(structure_block.get("sequence_groups", []) or []),
            "member_refs": list(structure_block.get("member_refs", []) or []),
            "structure_ext": structure_ext,
            "residual_kind": "structure",
            "context_ref_object_id": "",
            "context_ref_object_type": "",
            "context_owner_id": "",
            "context_owner_structure_id": "",
            "context_path_ids": [],
            "context_text": "",
            "context_explicit": False,
            "residual_origin_kind": "",
            "residual_origin_entry_id": "",
        }
        meta = state_item.setdefault("meta", {})
        if not isinstance(meta, dict):
            meta = {}
            state_item["meta"] = meta
        meta_ext = meta.setdefault("ext", {})
        if not isinstance(meta_ext, dict):
            meta_ext = {}
            meta["ext"] = meta_ext
        meta_ext.update(
            {
                "runtime_only_residual": False,
                "hdb_backed": True,
                "promotion_status": "promoted_hdb_backed",
                "promoted_from_runtime_ref_id": runtime_ref_id,
                "promoted_structure_id": structure_id,
                "promotion_reason": reason,
                "pre_promotion_context": previous_context,
                "pre_promotion_residual": previous_residual,
                "provenance_parent_ids": provenance_parent_ids,
                "context_explicit": False,
                **context_free_meta,
            }
        )
        meta_ext.pop("residual_origin_kind", None)
        meta_ext.pop("residual_origin_entry_id", None)
        source = state_item.setdefault("source", {})
        if isinstance(source, dict):
            source["origin"] = "runtime_residual_package_promoted"
            source["origin_id"] = structure_id
            source["parent_ids"] = []
            source["context_ref_object_id"] = ""
            source["context_ref_object_type"] = ""
            source["context_owner_structure_id"] = ""
            source["context_path_ids"] = []
            source["provenance_parent_ids"] = provenance_parent_ids
        try:
            self.pool._store.update(state_item["id"], state_item)  # type: ignore[attr-defined]
            self.pool._store.rebuild_index()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _build_runtime_residual_package(
        self,
        packet: dict,
        *,
        trace_id: str,
        tick_id: str,
        source_packet_id: str = "",
    ) -> dict[str, Any] | None:
        if not isinstance(packet, dict) or (not packet.get("sa_items") and not packet.get("csa_items")):
            return None
        profile = self.cut_engine.build_sequence_profile_from_stimulus_packet(packet)
        sequence_groups = [group for group in list(profile.get("sequence_groups", []) or []) if isinstance(group, dict)]
        if not sequence_groups:
            return None
        total_er = 0.0
        total_ev = 0.0
        for group in sequence_groups:
            for unit in list(group.get("units", []) or []):
                if not isinstance(unit, dict):
                    continue
                total_er += max(0.0, float(unit.get("er", 0.0) or 0.0))
                total_ev += max(0.0, float(unit.get("ev", 0.0) or 0.0))
        total_er = round(float(total_er), 8)
        total_ev = round(float(total_ev), 8)
        if total_er <= 0.0 and total_ev <= 0.0:
            return None
        try:
            configured_floor = float(self._config.get("runtime_residual_package_min_energy", 0.05) or 0.0)
        except Exception:
            configured_floor = 0.05
        try:
            pool_floor = min(
                float(getattr(self.pool, "_config", {}).get("er_elimination_threshold", 0.05) or 0.05),
                float(getattr(self.pool, "_config", {}).get("ev_elimination_threshold", 0.05) or 0.05),
            )
        except Exception:
            pool_floor = 0.05
        min_energy = max(0.0, configured_floor if configured_floor > 0 else pool_floor)
        if (total_er + total_ev) < min_energy:
            return None

        signature = str(profile.get("content_signature", "") or "")
        flat_tokens = [str(token) for token in list(profile.get("flat_tokens", []) or []) if str(token)]
        display_text = (
            format_semantic_sequence_groups(sequence_groups, context="stimulus")
            or str(profile.get("semantic_display_text", "") or "")
            or format_sequence_groups(sequence_groups)
            or str(profile.get("display_text", "") or "".join(flat_tokens))
        )
        if bool(self._config.get("runtime_residual_package_stable_id_enabled", True)):
            stable_material = json.dumps(
                {
                    "signature": signature,
                    "tokens": flat_tokens,
                    "groups": [
                        {
                            "signature": str(group.get("group_signature", "") or ""),
                            "order_sensitive": bool(group.get("order_sensitive", False)),
                            "string_unit_kind": str(group.get("string_unit_kind", "") or ""),
                        }
                        for group in sequence_groups
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            package_id = "rt_residual_" + hashlib.sha1(stable_material.encode("utf-8")).hexdigest()[:24]
        else:
            package_id = next_id("rt_residual")
        now_ms = int(time.time() * 1000)
        source_packet_id = str(source_packet_id or packet.get("id", "") or "")
        ext = {
            "runtime_only_residual": True,
            "hdb_backed": False,
            "source_packet_id": source_packet_id,
            "residual_origin_kind": "stimulus_runtime_residual_package",
            "promotion_status": "pending_runtime_only",
            "created_from_trace_id": trace_id,
            "created_from_tick_id": tick_id,
        }
        return {
            "id": package_id,
            "object_type": "st",
            "sub_type": "runtime_residual_package",
            "schema_version": "runtime",
            "content": {
                "raw": display_text,
                "display": display_text,
                "normalized": display_text,
            },
            "structure": {
                "unit_type": "sa_csa_sequence",
                "display_text": display_text,
                "member_refs": list(profile.get("member_refs", []) or []),
                "sequence_groups": sequence_groups,
                "flat_tokens": flat_tokens,
                "content_signature": signature,
                "semantic_signature": str(profile.get("semantic_signature", "") or signature),
                "token_count": int(profile.get("token_count", len(flat_tokens)) or len(flat_tokens)),
                "unit_count": int(profile.get("unit_count", 0) or 0),
                "ext": ext,
            },
            "energy": {
                "er": total_er,
                "ev": total_ev,
                "ownership_level": "runtime_residual_package",
                "computed_from_children": True,
            },
            "source": {
                "module": "observatory",
                "interface": "_insert_runtime_residual_package_to_pool",
                "origin": "stimulus_runtime_residual_package",
                "origin_id": source_packet_id,
                "parent_ids": [source_packet_id] if source_packet_id else [],
            },
            "meta": {
                "confidence": 0.5,
                "field_registry_version": "runtime",
                "debug": {},
                "ext": dict(ext),
            },
            "created_at": now_ms,
            "updated_at": now_ms,
        }

    def _project_runtime_structures(
        self,
        projections: list[dict],
        trace_id: str,
        tick_id: str,
        *,
        enable_insert_log: bool = True,
        fast_ref_hit_energy_merge: bool = False,
    ) -> list[dict]:
        def _is_attribute_only_structure(structure_block: dict) -> bool:
            """
            Detect attribute-only structures (should NOT become standalone StatePool objects).
            # sanitized

            Why / 婵炴垶鎹佸銊у垝閸喓鈻曢柛顐墰缁?
              # sanitized
              # sanitized

            Rule / 闁荤喐鐟ョ€氼剟宕归鐐存櫖闁革富鎽怭闂佹寧绋戦¨鈧紒?
              - 闂佸吋鐪归崕宕囧垝閵娾晛鍑犻柛鏇ㄥ幗閻?sequence_groups.units 婵炴垶鎼╅崢濂告偤閵娾晛鎹堕柕濞垮€栧畷鏌ユ煙?unit_role != attribute 闂?token闂佹寧绋戦懟顖炲垂椤栨粍濯奸柕鍫濆缁€瀣槈閹惧磭校婵℃彃鎽滈惀顏堫敍濮樿鲸鍓戦梺璇″劯閸涱垱灏濋梺鍝勵儏鐎氬摜妲?
              # sanitized
            """
            if not isinstance(structure_block, dict):
                return False
            groups = structure_block.get("sequence_groups", [])
            tokens_seen = 0
            feature_seen = 0
            if isinstance(groups, list) and groups:
                for g in groups:
                    if not isinstance(g, dict):
                        continue
                    units = g.get("units", [])
                    if isinstance(units, list) and units:
                        for u in units:
                            if not isinstance(u, dict):
                                continue
                            tok = str(u.get("token", "") or "")
                            if not tok:
                                continue
                            tokens_seen += 1
                            role = str(u.get("unit_role", "") or "")
                            if role != "attribute":
                                feature_seen += 1
                    else:
                        # Legacy fallback: if no units, treat tokens as features (cannot decide attribute-only).
                        # sanitized
                        return False
            else:
                # No groups: fallback to flat_tokens, assume not attribute-only.
                # sanitized
                return False
            return tokens_seen > 0 and feature_seen == 0

        results = []
        for item in projections:
            projection_kind = str(item.get("projection_kind", "structure") or "structure")
            memory_id = str(item.get("memory_id", ""))
            structure_id = str(item.get("structure_id", ""))
            backing_structure_id = str(item.get("backing_structure_id", structure_id))
            if projection_kind == "memory" and memory_id:
                results.append(
                    {
                        "projection_kind": projection_kind,
                        "memory_id": memory_id,
                        "structure_id": structure_id,
                        "display_text": str(item.get("display_text", memory_id)),
                        "er": round(float(item.get("er", 0.0)), 8),
                        "ev": round(float(item.get("ev", 0.0)), 8),
                        "reason": item.get("reason", ""),
                        "result": "memory_projection_skipped_state_pool",
                    }
                )
                continue

            # Skip structures that should not become ordinary StatePool anchors.
            st_obj: dict | None = None
            try:
                st_obj = self.hdb._structure_store.get(structure_id)  # type: ignore[attr-defined]
                st_block = (st_obj or {}).get("structure", {}) if isinstance(st_obj, dict) else {}
                block_reason = classify_runtime_projection_block_reason(st_obj)
                if _is_attribute_only_structure(st_block):
                    results.append(
                        {
                            "projection_kind": projection_kind,
                            "memory_id": memory_id,
                            "structure_id": structure_id,
                            "target_item_id": "",
                            "target_ref_object_id": structure_id,
                            "target_ref_object_type": "st",
                            "display_text": (st_block.get("display_text") if isinstance(st_block, dict) else "") or structure_id,
                            "er": round(float(item.get("er", 0.0)), 8),
                            "ev": round(float(item.get("ev", 0.0)), 8),
                            "reason": item.get("reason", ""),
                            "result": "skipped_attribute_only_structure",
                        }
                    )
                    continue
                if block_reason == "cognitive_stitching_event_structure":
                    results.append(
                        {
                            "projection_kind": projection_kind,
                            "memory_id": memory_id,
                            "structure_id": structure_id,
                            "target_item_id": "",
                            "target_ref_object_id": structure_id,
                            "target_ref_object_type": "st",
                            "display_text": (st_block.get("display_text") if isinstance(st_block, dict) else "") or structure_id,
                            "er": round(float(item.get("er", 0.0)), 8),
                            "ev": round(float(item.get("ev", 0.0)), 8),
                            "reason": item.get("reason", ""),
                            "result": "skipped_cognitive_stitching_event_structure",
                        }
                    )
                    continue
            except Exception:
                # Best-effort: if detection fails, do not block projection.
                pass

            runtime_object = self.hdb.make_runtime_structure_object(
                structure_id,
                er=float(item.get("er", 0.0)),
                ev=float(item.get("ev", 0.0)),
                reason=item.get("reason", "hdb_projection"),
                structure_obj=st_obj if isinstance(st_obj, dict) else None,
            )
            if not runtime_object:
                continue
            projection_ext: dict[str, Any] = {}
            growth_projection = item.get("growth_projection", {})
            if isinstance(growth_projection, dict) and growth_projection:
                projection_ext["growth_projection"] = copy.deepcopy(growth_projection)
            component_energy = item.get("component_energy", {})
            if isinstance(component_energy, dict) and component_energy:
                projection_ext["component_energy"] = copy.deepcopy(component_energy)
            if projection_ext:
                existing_ext = runtime_object.get("ext", {}) if isinstance(runtime_object.get("ext", {}), dict) else {}
                runtime_object["ext"] = {**existing_ext, **projection_ext}
                runtime_meta = runtime_object.get("meta", {}) if isinstance(runtime_object.get("meta", {}), dict) else {}
                runtime_meta_ext = runtime_meta.get("ext", {}) if isinstance(runtime_meta.get("ext", {}), dict) else {}
                runtime_meta["ext"] = {**runtime_meta_ext, **projection_ext}
                runtime_object["meta"] = runtime_meta
            insert_result = self.pool.insert_runtime_node(
                runtime_object=runtime_object,
                trace_id=f"{trace_id}_projection",
                tick_id=tick_id,
                source_module="hdb",
                reason=item.get("reason", "hdb_projection"),
                enable_brief_log=enable_insert_log,
                enable_detail_log=enable_insert_log,
                fast_ref_hit_energy_merge=fast_ref_hit_energy_merge,
            )
            # For observability: carry the resulting StatePool item_id so other modules
            # (e.g. TimeSensor binding, IESM scripts) can reference the exact runtime anchor.
            # sanitized
            ir_data = insert_result.get("data", {}) if isinstance(insert_result, dict) else {}
            target_item_id = ""
            if isinstance(ir_data, dict):
                target_item_id = str(ir_data.get("item_id", "") or ir_data.get("target_item_id", "") or "")
            results.append(
                {
                    "projection_kind": projection_kind,
                    "memory_id": memory_id,
                    "structure_id": structure_id,
                    "target_item_id": target_item_id,
                    "target_ref_object_id": structure_id,
                    "target_ref_object_type": "st",
                    "display_text": runtime_object.get("content", {}).get("display", structure_id),
                    "er": round(float(item.get("er", 0.0)), 8),
                    "ev": round(float(item.get("ev", 0.0)), 8),
                    "reason": item.get("reason", ""),
                    "growth_projection": copy.deepcopy(item.get("growth_projection", {}))
                    if isinstance(item.get("growth_projection", {}), dict)
                    else {},
                    "component_energy": copy.deepcopy(item.get("component_energy", {}))
                    if isinstance(item.get("component_energy", {}), dict)
                    else {},
                    "result": insert_result.get("message", ""),
                    "fast_ref_hit_merge": bool(isinstance(ir_data, dict) and ir_data.get("fast_ref_hit", False)),
                    "insert_log_suppressed": not enable_insert_log,
                }
            )
            try:
                self._mark_projection_fatigue(item)
            except Exception:
                pass
        return results

    def _collect_memory_activation_seed_targets(self, report: dict) -> list[dict]:
        """
        Seed memory activation directly from newly written residual-memory records.

        This keeps fresh episodic memories visible even in cycles where the current
        induction source energy in StatePool is too small to cross the induction
        threshold, while still preserving the separate memory pool design.
        """
        er_ratio = max(0.0, float(self.hdb._config.get("er_induction_ratio", 0.22)))
        ev_ratio = max(0.0, float(self.hdb._config.get("ev_propagation_ratio", 0.28)))
        seed_targets: list[dict] = []

        stimulus_rounds = list(
            report.get("stimulus_level", {}).get("result", {}).get("debug", {}).get("round_details", [])
        )
        for round_detail in stimulus_rounds:
            residual = dict(round_detail.get("created_residual_structure", {}) or {})
            memory_id = str(residual.get("memory_id", ""))
            if not memory_id:
                continue
            delta_ev = round(
                max(
                    0.0,
                    float(round_detail.get("transferred_er", 0.0)) * er_ratio
                    + float(round_detail.get("transferred_ev", 0.0)) * ev_ratio,
                ),
                8,
            )
            if delta_ev <= 0.0:
                continue
            matched_structure_id = str((round_detail.get("selected_match") or {}).get("structure_id", ""))
            target_display_text = (
                str(residual.get("canonical_grouped_display_text", ""))
                or str(residual.get("canonical_display_text", ""))
                or memory_id
            )
            seed_targets.append(
                {
                    "projection_kind": "memory",
                    "memory_id": memory_id,
                    "backing_structure_id": matched_structure_id,
                    "target_display_text": target_display_text,
                    "delta_ev": delta_ev,
                    "sources": [matched_structure_id] if matched_structure_id else [],
                    "modes": ["residual_storage_seed"],
                }
            )

        structure_rounds = list(
            report.get("structure_level", {}).get("result", {}).get("debug", {}).get("round_details", [])
        )
        structure_summaries = {
            int(item.get("round_index", 0)): dict(item)
            for item in report.get("structure_level", {}).get("result", {}).get("round_summaries", [])
            if int(item.get("round_index", 0)) > 0
        }
        for round_detail in structure_rounds:
            storage_summary = dict(round_detail.get("storage_summary", {}) or {})
            actions = list(storage_summary.get("actions", []) or [])
            if not actions:
                continue
            round_summary = structure_summaries.get(int(round_detail.get("round_index", 0)), {})
            delta_ev = round(
                max(
                    0.0,
                    float(round_summary.get("matched_er_total", 0.0)) * er_ratio
                    + float(round_summary.get("matched_ev_total", 0.0)) * ev_ratio,
                ),
                8,
            )
            if delta_ev <= 0.0:
                continue
            selected_group = dict(round_detail.get("selected_group", {}) or {})
            source_ids = [
                str(item.get("structure_id", ""))
                for item in selected_group.get("required_structures", [])
                if str(item.get("structure_id", ""))
            ]
            for action in actions:
                if str(action.get("type", "")) != "append_raw_residual":
                    continue
                memory_id = str(action.get("memory_id", ""))
                if not memory_id:
                    continue
                target_display_text = (
                    str(action.get("canonical_grouped_display_text", ""))
                    or str(action.get("canonical_display_text", ""))
                    or memory_id
                )
                seed_targets.append(
                    {
                        "projection_kind": "memory",
                        "memory_id": memory_id,
                        "backing_structure_id": str(storage_summary.get("owner_id", "")),
                        "target_display_text": target_display_text,
                        "delta_ev": delta_ev,
                        "sources": list(dict.fromkeys(source_ids)),
                        "modes": ["residual_storage_seed"],
                    }
                )
        filtered_targets: list[dict] = []
        for item in seed_targets:
            projection_probe = {
                "projection_kind": "memory",
                "memory_id": item.get("memory_id", ""),
                "structure_id": item.get("backing_structure_id", ""),
                "backing_structure_id": item.get("backing_structure_id", ""),
                "display_text": item.get("target_display_text", ""),
                "er": 0.0,
                "ev": float(item.get("delta_ev", 0.0) or 0.0),
                "reason": "memory_seed_target",
            }
            effective = self._apply_projection_fatigue_to_item(projection_probe)
            if effective is None:
                continue
            next_item = dict(item)
            next_item["delta_ev"] = round(float(effective.get("ev", item.get("delta_ev", 0.0)) or 0.0), 8)
            next_item["projection_fatigue"] = round(float(effective.get("projection_fatigue", 0.0) or 0.0), 8)
            filtered_targets.append(next_item)
        return filtered_targets

    def _project_memory_activation_runtime_items(self, *, memory_items: list[dict], trace_id: str, tick_id: str) -> dict:
        enabled = bool(self._config.get("residual_memory_as_structure_enabled", True))
        shadow_mode = bool(self._config.get("residual_memory_as_structure_shadow_mode", False))
        result: dict[str, Any] = {
            "enabled": enabled,
            "shadow_mode": shadow_mode,
            "items": [],
            "summary": {
                "attempted_count": 0,
                "inserted_count": 0,
                "skipped_count": 0,
                "total_er": 0.0,
                "total_ev": 0.0,
            },
        }
        if not enabled:
            return result

        attempted = 0
        inserted = 0
        skipped = 0
        total_er = 0.0
        total_ev = 0.0
        reason = "residual_memory_as_structure_shadow" if shadow_mode else "residual_memory_as_structure"
        runtime_object_type = self._residual_memory_runtime_object_type()

        for item in memory_items or []:
            memory_id = str(item.get("memory_id", "") or "")
            if not memory_id:
                continue
            projection_probe = {
                "projection_kind": "memory_runtime_projection",
                "memory_id": memory_id,
                "display_text": str(item.get("display_text", "") or memory_id),
                "grouped_display_text": str(item.get("grouped_display_text", "") or ""),
                "backing_structure_id": str((item.get("backing_structure_ids", []) or [""])[0] or ""),
                "er": round(max(0.0, float(item.get("last_delta_er", 0.0) or 0.0)), 8),
                "ev": round(max(0.0, float(item.get("last_delta_ev", 0.0) or 0.0)), 8),
                "reason": reason,
            }
            if projection_probe["er"] <= 0.0 and projection_probe["ev"] <= 0.0:
                continue
            attempted += 1
            effective = self._apply_projection_fatigue_to_item(projection_probe)
            if effective is None:
                skipped += 1
                result["items"].append(
                    {
                        "memory_id": memory_id,
                        "projection_kind": "memory_runtime_projection",
                        "result": "skipped_projection_fatigue_threshold",
                    }
                )
                continue
            runtime_object = self.hdb.make_runtime_memory_object(
                memory_id,
                er=float(effective.get("er", 0.0)),
                ev=float(effective.get("ev", 0.0)),
                reason=reason,
                display_text=str(effective.get("display_text", "") or memory_id),
                backing_structure_id=str(effective.get("backing_structure_id", "") or ""),
                runtime_object_type=runtime_object_type,
            )
            if not isinstance(runtime_object, dict):
                skipped += 1
                result["items"].append(
                    {
                        "memory_id": memory_id,
                        "projection_kind": "memory_runtime_projection",
                        "result": "runtime_memory_object_not_found",
                    }
                )
                continue
            insert_result = self.pool.insert_runtime_node(
                runtime_object=runtime_object,
                trace_id=f"{trace_id}_memory_runtime_projection",
                tick_id=tick_id,
                source_module="hdb_memory_runtime_projection",
                reason=reason,
            )
            insert_data = (insert_result.get("data", {}) or {}) if isinstance(insert_result, dict) else {}
            runtime_ext = dict(runtime_object.get("ext", {}) or {})
            runtime_memory = dict(runtime_object.get("memory", {}) or {})
            inserted += 1
            total_er += float(effective.get("er", 0.0) or 0.0)
            total_ev += float(effective.get("ev", 0.0) or 0.0)
            self._mark_projection_fatigue(effective)
            result["items"].append(
                {
                    "memory_id": memory_id,
                    "projection_kind": "memory_runtime_projection",
                    "backing_structure_id": str(effective.get("backing_structure_id", "") or ""),
                    "target_item_id": str(insert_data.get("item_id", "") or insert_data.get("target_item_id", "") or ""),
                    "target_ref_object_id": str(runtime_object.get("id", "") or ""),
                    "projected_ref_object_type": str(runtime_object.get("object_type", "") or runtime_object_type),
                    "display_text": str(runtime_memory.get("display_text", "") or effective.get("display_text", "") or memory_id),
                    "grouped_display_text": str(runtime_memory.get("grouped_display_text", "") or effective.get("grouped_display_text", "") or ""),
                    "source_em_id": str(runtime_ext.get("source_em_id", "") or memory_id),
                    "residual_kind": str(runtime_ext.get("residual_kind", "") or ""),
                    "residual_origin_kind": str(runtime_ext.get("residual_origin_kind", "") or ""),
                    "context_owner_id": str(
                        runtime_ext.get("context_owner_id", "")
                        or runtime_ext.get("context_owner_structure_id", "")
                        or ""
                    ),
                    "context_owner_structure_id": str(runtime_ext.get("context_owner_structure_id", "") or ""),
                    "context_ref_object_id": str(runtime_ext.get("context_ref_object_id", "") or ""),
                    "context_ref_object_type": str(runtime_ext.get("context_ref_object_type", "") or ""),
                    "context_text": str(runtime_ext.get("context_text", "") or ""),
                    "source_memory_created_at": int(runtime_ext.get("source_memory_created_at", 0) or runtime_memory.get("memory_created_at", 0) or 0),
                    "shadow_mode": bool(shadow_mode),
                    "reason": reason,
                    "er": round(float(effective.get("er", 0.0) or 0.0), 8),
                    "ev": round(float(effective.get("ev", 0.0) or 0.0), 8),
                    "projection_fatigue": round(float(effective.get("projection_fatigue", 0.0) or 0.0), 8),
                    "result": str(insert_result.get("message", "")),
                }
            )

        result["summary"] = {
            "attempted_count": int(attempted),
            "inserted_count": int(inserted),
            "skipped_count": int(skipped),
            "total_er": round(float(total_er), 8),
            "total_ev": round(float(total_ev), 8),
        }
        return result

    def _apply_memory_feedback(self, *, memory_items: list[dict], trace_id: str, tick_id: str) -> dict:
        feedback_items: list[dict] = []
        feedback_results: list[dict] = []
        feedback_bucket_counts: dict[str, int] = {}
        packet_feedback_count = 0
        packet_feedback_total_er = 0.0
        packet_feedback_total_ev = 0.0
        packet_applied_total_er = 0.0
        packet_applied_total_ev = 0.0
        packet_apply_new_item_count = 0
        packet_apply_updated_item_count = 0
        packet_apply_merged_item_count = 0
        structure_projection_attempted_count = 0
        structure_projection_skipped_count = 0
        structure_projection_count = 0
        structure_projection_total_er = 0.0
        structure_projection_total_ev = 0.0
        pool_energy_before_feedback = self._get_live_pool_energy_summary()
        configured_structure_projection_ratio = max(
            0.0,
            min(
                0.95,
                float(self._config.get("memory_feedback_stimulus_packet_structure_projection_ratio", 0.55) or 0.55),
            ),
        )
        adaptive_structure_projection_ratio, structure_projection_ratio_audit = (
            self._resolve_memory_feedback_structure_projection_ratio(
                base_ratio=configured_structure_projection_ratio,
                pool_energy_summary=pool_energy_before_feedback,
            )
        )

        for item in memory_items or []:
            memory_id = str(item.get("memory_id", ""))
            if not memory_id:
                continue
            # Only the newly assigned activation delta of this round may feed back.
            # The pool's retained live energy is not a per-round replay budget.
            delta_er = round(max(0.0, float(item.get("last_delta_er", 0.0))), 8)
            delta_ev = round(max(0.0, float(item.get("last_delta_ev", 0.0))), 8)
            if delta_er <= 0.0 and delta_ev <= 0.0:
                continue
            episodic_obj = self.hdb._episodic_store.get(memory_id)
            if not episodic_obj:
                continue
            memory_material = dict(episodic_obj.get("meta", {}).get("ext", {}).get("memory_material", {}) or {})
            memory_kind = str(memory_material.get("memory_kind", ""))
            if memory_kind == "stimulus_packet":
                feedback_bucket_key = str(memory_material.get("grouped_display_text", "") or item.get("display_text", memory_id) or memory_id)
                bucket_seen = int(feedback_bucket_counts.get(feedback_bucket_key, 0) or 0)
                structure_projection_enabled = bool(
                    self._config.get("memory_feedback_stimulus_packet_structure_projection_enabled", True)
                )
                structure_projection_ratio = adaptive_structure_projection_ratio if structure_projection_enabled else 0.0
                projection_probe = {
                    "projection_kind": "memory_feedback_packet",
                    "memory_id": memory_id,
                    "display_text": str(memory_material.get("grouped_display_text", "") or item.get("display_text", memory_id)),
                    "grouped_display_text": str(memory_material.get("grouped_display_text", "") or ""),
                    "er": delta_er,
                    "ev": delta_ev,
                    "reason": "memory_feedback_stimulus_packet",
                }
                effective_feedback = self._apply_projection_fatigue_to_item(projection_probe)
                if effective_feedback is None:
                    continue
                delta_er = round(max(0.0, float(effective_feedback.get("er", delta_er) or 0.0)), 8)
                delta_ev = round(max(0.0, float(effective_feedback.get("ev", delta_ev) or 0.0)), 8)
                if bucket_seen > 0:
                    crowd_ratio = 1.0 / float(1 + bucket_seen)
                    delta_er = round(delta_er * crowd_ratio, 8)
                    delta_ev = round(delta_ev * crowd_ratio, 8)
                if delta_er <= 0.0 and delta_ev <= 0.0:
                    continue
                packet_delta_er = delta_er
                packet_delta_ev = delta_ev
                structure_projection_results: list[dict] = []
                structure_target_texts: list[str] = []
                effective_structure_projections: list[dict] = []
                skipped_structure_projection_count = 0
                raw_structure_projections: list[dict] = []
                if structure_projection_enabled and structure_projection_ratio > 0.0:
                    packet_delta_er, structure_delta_er = self._split_feedback_budget(delta_er, structure_projection_ratio)
                    packet_delta_ev, structure_delta_ev = self._split_feedback_budget(delta_ev, structure_projection_ratio)
                    raw_structure_projections = self._build_memory_feedback_structure_projections(
                        memory_id=memory_id,
                        memory_material=memory_material,
                        total_er=structure_delta_er,
                        total_ev=structure_delta_ev,
                        projection_kind="memory_feedback_structure_ref",
                        reason="memory_feedback_structure_ref",
                    )
                    structure_projection_attempted_count += len(raw_structure_projections)
                    if raw_structure_projections:
                        for projection in raw_structure_projections:
                            effective = self._apply_projection_fatigue_to_item(projection)
                            if effective is None:
                                skipped_structure_projection_count += 1
                                continue
                            effective_structure_projections.append(effective)
                        if effective_structure_projections:
                            structure_projection_results = self._project_runtime_structures(
                                effective_structure_projections,
                                trace_id=f"{trace_id}_memory_feedback_structure",
                                tick_id=tick_id,
                            )
                            structure_target_texts = [
                                str(projection.get("display_text", projection.get("structure_id", "")))
                                for projection in effective_structure_projections
                                if str(projection.get("structure_id", ""))
                            ]
                            structure_projection_count += len(effective_structure_projections)
                            structure_projection_total_er += sum(
                                float(projection.get("er", 0.0) or 0.0) for projection in effective_structure_projections
                            )
                            structure_projection_total_ev += sum(
                                float(projection.get("ev", 0.0) or 0.0) for projection in effective_structure_projections
                            )
                    else:
                        packet_delta_er = delta_er
                        packet_delta_ev = delta_ev
                    structure_projection_skipped_count += skipped_structure_projection_count
                packet_result = self._build_memory_feedback_stimulus_packet(
                    memory_id=memory_id,
                    memory_material=memory_material,
                    total_er=packet_delta_er,
                    total_ev=packet_delta_ev,
                    trace_id=trace_id,
                    tick_id=tick_id,
                )
                packet = packet_result.get("packet")
                packet_apply_result: dict[str, Any] = {}
                packet_events: list[dict[str, Any]] = []
                landed_packet: dict[str, Any] = {}
                target_texts: list[str] = []
                packet_applied = False
                packet_apply_data: dict[str, Any] = {}
                packet_state_delta_summary: dict[str, Any] = {}
                if packet:
                    packet_apply_result, packet_events, landed_packet = self._apply_packet_to_pool(
                        packet,
                        trace_id=f"{trace_id}_memory_feedback",
                        tick_id=tick_id,
                        disable_priority_neutralization=True,
                        source_module="observatory_memory_feedback",
                    )
                    packet_apply_data = dict(packet_apply_result) if isinstance(packet_apply_result, dict) else {}
                    packet_state_delta_summary = (
                        dict(packet_apply_data.get("state_delta_summary", {}))
                        if isinstance(packet_apply_data.get("state_delta_summary", {}), dict)
                        else {}
                    )
                    target_texts = list(packet_result.get("target_display_texts", []))
                    packet_applied = True
                    packet_feedback_count += 1
                    packet_feedback_total_er += packet_delta_er
                    packet_feedback_total_ev += packet_delta_ev
                    packet_applied_total_er += float(packet_state_delta_summary.get("total_delta_er", 0.0) or 0.0)
                    packet_applied_total_ev += float(packet_state_delta_summary.get("total_delta_ev", 0.0) or 0.0)
                    packet_apply_new_item_count += int(packet_apply_data.get("new_item_count", 0) or 0)
                    packet_apply_updated_item_count += int(packet_apply_data.get("updated_item_count", 0) or 0)
                    packet_apply_merged_item_count += int(packet_apply_data.get("merged_item_count", 0) or 0)
                elif not structure_projection_results:
                    continue
                feedback_items.append(
                    {
                        "memory_id": memory_id,
                        "delta_er": delta_er,
                        "delta_ev": delta_ev,
                        "feedback_kind": "stimulus_packet",
                        "target_count": len(target_texts) + len(structure_target_texts),
                        "grouped_display_text": str(memory_material.get("grouped_display_text", "")),
                        "target_display_texts": list(target_texts) + list(structure_target_texts),
                        "packet_target_count": len(target_texts),
                        "structure_projection_count": len(effective_structure_projections),
                        "structure_projection_skipped_count": skipped_structure_projection_count,
                    }
                )
                feedback_results.append(
                    {
                        "memory_id": memory_id,
                        "memory_kind": "stimulus_packet",
                        "display_text": str(item.get("display_text", memory_id)),
                        "grouped_display_text": str(memory_material.get("grouped_display_text", "")),
                        "delta_er": delta_er,
                        "delta_ev": delta_ev,
                        "packet_delta_er": packet_delta_er if packet_applied else 0.0,
                        "packet_delta_ev": packet_delta_ev if packet_applied else 0.0,
                        "structure_projection_total_er": round(
                            sum(float(projection.get("er", 0.0) or 0.0) for projection in effective_structure_projections), 8
                        ),
                        "structure_projection_total_ev": round(
                            sum(float(projection.get("ev", 0.0) or 0.0) for projection in effective_structure_projections), 8
                        ),
                        "same_tick_bucket_rank": int(bucket_seen + 1),
                        "projection_fatigue": round(float(effective_feedback.get("projection_fatigue", 0.0) or 0.0), 8),
                        "structure_projection_ratio_base": round(configured_structure_projection_ratio, 8),
                        "structure_projection_ratio_used": round(structure_projection_ratio, 8),
                        "target_count": len(target_texts) + len(structure_target_texts),
                        "target_display_texts": list(target_texts) + list(structure_target_texts),
                        "packet_target_count": len(target_texts),
                        "structure_target_texts": structure_target_texts,
                        "structure_projection_count": len(effective_structure_projections),
                        "structure_projection_skipped_count": skipped_structure_projection_count,
                        "packet": self._describe_stimulus_packet(packet) if packet else {},
                        "landed_packet": self._describe_stimulus_packet(landed_packet) if landed_packet else {},
                        "packet_apply_result": packet_apply_result,
                        "packet_apply_data": packet_apply_data,
                        "packet_apply_state_delta": packet_state_delta_summary,
                        "apply_result": packet_apply_result,
                        "events": packet_events,
                        "structure_projections": structure_projection_results,
                    }
                )
                feedback_bucket_counts[feedback_bucket_key] = bucket_seen + 1
                self._mark_projection_fatigue(projection_probe)
                continue

            if memory_kind == "structure_group":
                projections = self._build_memory_feedback_structure_projections(
                    memory_id=memory_id,
                    memory_material=memory_material,
                    total_er=delta_er,
                    total_ev=delta_ev,
                )
                if not projections:
                    continue
                structure_projection_attempted_count += len(projections)
                effective_projections: list[dict] = []
                skipped_projection_count = 0
                for projection in projections:
                    effective = self._apply_projection_fatigue_to_item(projection)
                    if effective is None:
                        skipped_projection_count += 1
                        continue
                    effective_projections.append(effective)
                if not effective_projections:
                    structure_projection_skipped_count += skipped_projection_count
                    continue
                projection_results = self._project_runtime_structures(
                    effective_projections,
                    trace_id=f"{trace_id}_memory_feedback",
                    tick_id=tick_id,
                )
                target_texts = [
                    str(projection.get("display_text", projection.get("structure_id", "")))
                    for projection in effective_projections
                    if str(projection.get("structure_id", ""))
                ]
                feedback_items.append(
                    {
                        "memory_id": memory_id,
                        "delta_er": delta_er,
                        "delta_ev": delta_ev,
                        "feedback_kind": "structure_group",
                        "target_count": len(target_texts),
                        "grouped_display_text": str(memory_material.get("grouped_display_text", "")),
                        "target_display_texts": target_texts,
                        "skipped_projection_count": skipped_projection_count,
                    }
                )
                feedback_results.append(
                    {
                        "memory_id": memory_id,
                        "memory_kind": "structure_group",
                        "display_text": str(item.get("display_text", memory_id)),
                        "grouped_display_text": str(memory_material.get("grouped_display_text", "")),
                        "delta_er": delta_er,
                        "delta_ev": delta_ev,
                        "packet_delta_er": 0.0,
                        "packet_delta_ev": 0.0,
                        "structure_projection_total_er": round(
                            sum(float(projection.get("er", 0.0) or 0.0) for projection in effective_projections), 8
                        ),
                        "structure_projection_total_ev": round(
                            sum(float(projection.get("ev", 0.0) or 0.0) for projection in effective_projections), 8
                        ),
                        "target_count": len(target_texts),
                        "target_display_texts": target_texts,
                        "packet_target_count": 0,
                        "structure_projection_count": len(effective_projections),
                        "structure_projection_skipped_count": skipped_projection_count,
                        "projections": projection_results,
                    }
                )
                structure_projection_count += len(effective_projections)
                structure_projection_total_er += sum(float(projection.get("er", 0.0) or 0.0) for projection in effective_projections)
                structure_projection_total_ev += sum(float(projection.get("ev", 0.0) or 0.0) for projection in effective_projections)
                structure_projection_skipped_count += skipped_projection_count

        record_result = self.hdb.record_memory_feedback(
            feedback_items=feedback_items,
            trace_id=trace_id,
            tick_id=tick_id,
        )["data"]
        total_feedback_er = round(sum(float(item.get("delta_er", 0.0)) for item in feedback_results), 8)
        total_feedback_ev = round(sum(float(item.get("delta_ev", 0.0)) for item in feedback_results), 8)
        return {
            "applied_count": len(feedback_results),
            "total_feedback_er": total_feedback_er,
            "total_feedback_ev": total_feedback_ev,
            "total_feedback_energy": round(total_feedback_er + total_feedback_ev, 8),
            "packet_feedback_count": int(packet_feedback_count),
            "packet_feedback_total_er": round(packet_feedback_total_er, 8),
            "packet_feedback_total_ev": round(packet_feedback_total_ev, 8),
            "packet_applied_total_er": round(packet_applied_total_er, 8),
            "packet_applied_total_ev": round(packet_applied_total_ev, 8),
            "packet_apply_new_item_count": int(packet_apply_new_item_count),
            "packet_apply_updated_item_count": int(packet_apply_updated_item_count),
            "packet_apply_merged_item_count": int(packet_apply_merged_item_count),
            "packet_apply_efficiency_er": round(
                float(packet_applied_total_er) / float(packet_feedback_total_er),
                8,
            ) if packet_feedback_total_er > 1e-8 else 0.0,
            "packet_apply_efficiency_ev": round(
                float(packet_applied_total_ev) / float(packet_feedback_total_ev),
                8,
            ) if packet_feedback_total_ev > 1e-8 else 0.0,
            "structure_projection_ratio_base": round(configured_structure_projection_ratio, 8),
            "structure_projection_ratio_used": round(adaptive_structure_projection_ratio, 8),
            "structure_projection_ratio_audit": structure_projection_ratio_audit,
            "pool_energy_before_feedback": pool_energy_before_feedback,
            "structure_projection_attempted_count": int(structure_projection_attempted_count),
            "structure_projection_skipped_count": int(structure_projection_skipped_count),
            "structure_projection_count": int(structure_projection_count),
            "structure_projection_total_er": round(structure_projection_total_er, 8),
            "structure_projection_total_ev": round(structure_projection_total_ev, 8),
            "items": feedback_results,
            "record_result": record_result,
        }

    def _build_memory_feedback_structure_projections(
        self,
        *,
        memory_id: str,
        memory_material: dict,
        total_er: float,
        total_ev: float,
        projection_kind: str = "structure",
        reason: str = "memory_feedback",
    ) -> list[dict]:
        structure_items = list(memory_material.get("structure_items", []))
        ordered_structure_ids = [
            str(item.get("structure_id", ""))
            for item in structure_items
            if str(item.get("structure_id", ""))
        ]
        if not ordered_structure_ids:
            ordered_structure_ids = [
                str(structure_id)
                for structure_id in memory_material.get("structure_refs", [])
                if str(structure_id)
            ]
        if not ordered_structure_ids:
            return []
        ordered_structure_ids = list(dict.fromkeys(ordered_structure_ids))
        structure_energy_profile = dict(memory_material.get("structure_energy_profile", {}) or {})
        max_targets = int(self._config.get("memory_feedback_structure_projection_max_targets", 6) or 0)
        if max_targets > 0 and len(ordered_structure_ids) > max_targets:
            weighted_order = sorted(
                enumerate(ordered_structure_ids),
                key=lambda item: (
                    -max(0.0, float(structure_energy_profile.get(item[1], 0.0) or 0.0)),
                    item[0],
                ),
            )
            kept_ids = {structure_id for _, structure_id in weighted_order[:max_targets]}
            ordered_structure_ids = [structure_id for structure_id in ordered_structure_ids if structure_id in kept_ids]
        if (
            bool(self._config.get("memory_feedback_structure_projection_budget_aware_enabled", True))
            and len(ordered_structure_ids) > 1
            and (total_er > 0.0 or total_ev > 0.0)
        ):
            ranked_ids = [
                structure_id
                for _, structure_id in sorted(
                    enumerate(ordered_structure_ids),
                    key=lambda item: (
                        -max(0.0, float(structure_energy_profile.get(item[1], 0.0) or 0.0)),
                        item[0],
                    ),
                )
            ]
            display_lookup = {
                str(item.get("structure_id", "")): str(
                    item.get("display_text", item.get("grouped_display_text", item.get("structure_id", "")))
                )
                for item in structure_items
                if str(item.get("structure_id", ""))
            }
            best_ids = list(ranked_ids[:1])
            best_score = (-1, -1.0, -1.0)
            for candidate_count in range(1, len(ranked_ids) + 1):
                candidate_ids = ranked_ids[:candidate_count]
                er_preview = self._allocate_weighted_values(
                    keys=candidate_ids,
                    raw_weights=structure_energy_profile,
                    total_value=total_er,
                )
                ev_preview = self._allocate_weighted_values(
                    keys=candidate_ids,
                    raw_weights=structure_energy_profile,
                    total_value=total_ev,
                )
                effective_items = [
                    effective
                    for structure_id in candidate_ids
                    if (
                        effective := self._apply_projection_fatigue_to_item(
                            {
                                "projection_kind": projection_kind,
                                "memory_id": memory_id,
                                "structure_id": structure_id,
                                "display_text": display_lookup.get(structure_id, structure_id),
                                "er": round(float(er_preview.get(structure_id, 0.0)), 8),
                                "ev": round(float(ev_preview.get(structure_id, 0.0)), 8),
                                "reason": reason,
                            }
                        )
                    )
                    is not None
                ]
                effective_count = len(effective_items)
                effective_ratio = effective_count / float(max(1, len(candidate_ids)))
                effective_energy = sum(
                    max(0.0, float(item.get("er", 0.0) or 0.0)) + max(0.0, float(item.get("ev", 0.0) or 0.0))
                    for item in effective_items
                )
                score = (effective_count, effective_ratio, effective_energy)
                if score > best_score:
                    best_score = score
                    best_ids = list(candidate_ids)
            best_id_set = set(best_ids)
            ordered_structure_ids = [structure_id for structure_id in ordered_structure_ids if structure_id in best_id_set]
        er_allocations = self._allocate_weighted_values(
            keys=ordered_structure_ids,
            raw_weights=structure_energy_profile,
            total_value=total_er,
        )
        ev_allocations = self._allocate_weighted_values(
            keys=ordered_structure_ids,
            raw_weights=structure_energy_profile,
            total_value=total_ev,
        )
        display_lookup = {
            str(item.get("structure_id", "")): str(item.get("display_text", item.get("grouped_display_text", item.get("structure_id", ""))))
            for item in structure_items
            if str(item.get("structure_id", ""))
        }
        return [
            {
                "projection_kind": projection_kind,
                "memory_id": memory_id,
                "structure_id": structure_id,
                "display_text": display_lookup.get(structure_id, structure_id),
                "er": round(float(er_allocations.get(structure_id, 0.0)), 8),
                "ev": round(float(ev_allocations.get(structure_id, 0.0)), 8),
                "reason": reason,
            }
            for structure_id in ordered_structure_ids
            if float(er_allocations.get(structure_id, 0.0)) > 0.0 or float(ev_allocations.get(structure_id, 0.0)) > 0.0
        ]

    def _build_memory_feedback_stimulus_packet(
        self,
        *,
        memory_id: str,
        memory_material: dict,
        total_er: float,
        total_ev: float,
        trace_id: str,
        tick_id: str,
    ) -> dict:
        sequence_groups = list(memory_material.get("sequence_groups", []))
        if not sequence_groups or (total_er <= 0.0 and total_ev <= 0.0):
            return {"packet": None, "target_display_texts": []}

        ordered_unit_ids = [
            str(unit.get("unit_id", ""))
            for group in sequence_groups
            for unit in group.get("units", [])
            if str(unit.get("unit_id", ""))
        ]
        er_allocations = self._allocate_weighted_values(
            keys=ordered_unit_ids,
            raw_weights=dict(memory_material.get("unit_energy_profile", {}) or {}),
            total_value=total_er,
        )
        ev_allocations = self._allocate_weighted_values(
            keys=ordered_unit_ids,
            raw_weights=dict(memory_material.get("unit_energy_profile", {}) or {}),
            total_value=total_ev,
        )

        now_ms = int(time.time() * 1000)
        packet_id = next_id("mfpkt")
        sa_items: list[dict] = []
        csa_items: list[dict] = []
        grouped_sequences: list[dict] = []
        packet_sequence_index = 0

        for group_order, group in enumerate(sequence_groups):
            units = sorted(
                [dict(unit) for unit in group.get("units", []) if isinstance(unit, dict)],
                key=lambda item: int(item.get("sequence_index", 0)),
            )
            if not units:
                continue
            packet_group_index = len(grouped_sequences)
            source_group_index = int(group.get("source_group_index", group.get("group_index", packet_group_index)))
            origin_frame_id = str(group.get("origin_frame_id", memory_id)) or memory_id
            group_unit_id_map: dict[str, str] = {}
            created_sa_by_id: dict[str, dict] = {}
            group_sa_ids: list[str] = []
            group_csa_ids: list[str] = []

            for unit in units:
                original_unit_id = str(unit.get("unit_id", ""))
                if not original_unit_id:
                    continue
                token = str(unit.get("token", unit.get("display_text", "")) or "")
                if (
                    token.startswith("{") and token.endswith("}")
                    and not bool(group.get("order_sensitive", False))
                    and str(group.get("string_unit_kind", "") or "") != "char_sequence"
                ):
                    # Goal B safety: do not replay presentation-wrapped structure tokens back into SA.
                    continue
                sa_id = next_id("sa_memfb")
                unit_role = str(unit.get("unit_role", unit.get("role", "feature")))
                attribute_name = str(unit.get("attribute_name", ""))
                attribute_value = unit.get("attribute_value")
                if attribute_name:
                    content = {
                        "raw": token,
                        "display": token,
                        "normalized": token,
                        "value_type": "numerical" if attribute_value is not None else str(unit.get("value_type", "discrete") or "discrete"),
                        "attribute_name": attribute_name,
                        "attribute_value": attribute_value,
                    }
                else:
                    content = {
                        "raw": token,
                        "display": token,
                        "normalized": token,
                        "value_type": str(unit.get("value_type", "discrete") or "discrete"),
                    }
                packet_context = {
                    "source_type": "memory_feedback",
                    "group_index": packet_group_index,
                    "source_group_index": source_group_index,
                    "origin_frame_id": origin_frame_id,
                    "echo_depth": 0,
                    "round_created": 0,
                    "decay_count": 0,
                    "sequence_index": packet_sequence_index,
                    "order_sensitive": bool(group.get("order_sensitive", False)),
                    "string_unit_kind": str(group.get("string_unit_kind", "") or ""),
                    "string_token_text": str(group.get("string_token_text", "") or ""),
                }
                sa_obj = {
                    "id": sa_id,
                    "object_type": "sa",
                    "content": content,
                    "stimulus": {
                        "role": unit_role,
                        "modality": "memory_feedback",
                        "order_sensitive": bool(group.get("order_sensitive", False)),
                        "string_unit_kind": str(group.get("string_unit_kind", "") or ""),
                        "string_token_text": str(group.get("string_token_text", "") or ""),
                    },
                    "energy": {
                        "er": round(float(er_allocations.get(original_unit_id, 0.0)), 8),
                        "ev": round(float(ev_allocations.get(original_unit_id, 0.0)), 8),
                    },
                    "source": {
                        "module": "observatory",
                        "interface": "memory_feedback",
                        "origin": "episodic_memory_feedback",
                        "origin_id": memory_id,
                        "parent_ids": [],
                    },
                    "ext": {
                        "packet_context": packet_context,
                    },
                    "created_at": now_ms,
                    "updated_at": now_ms,
                }
                group_unit_id_map[original_unit_id] = sa_id
                created_sa_by_id[sa_id] = sa_obj
                sa_items.append(sa_obj)
                group_sa_ids.append(sa_id)
                packet_sequence_index += 1

            for bundle in group.get("csa_bundles", []):
                anchor_id = group_unit_id_map.get(str(bundle.get("anchor_unit_id", "")), "")
                member_ids = [
                    group_unit_id_map.get(str(member_id), "")
                    for member_id in bundle.get("member_unit_ids", [])
                    if group_unit_id_map.get(str(member_id), "")
                ]
                member_ids = list(dict.fromkeys(member_ids))
                if not anchor_id or len(member_ids) < 2:
                    continue
                csa_id = next_id("csa_memfb")
                csa_obj = {
                    "id": csa_id,
                    "object_type": "csa",
                    "anchor_sa_id": anchor_id,
                    "member_sa_ids": member_ids,
                    "content": {
                        "display": created_sa_by_id.get(anchor_id, {}).get("content", {}).get("display", ""),
                        "raw": created_sa_by_id.get(anchor_id, {}).get("content", {}).get("raw", ""),
                    },
                    "bundle_summary": {
                        "member_count": len(member_ids),
                        "display_total_er": round(
                            sum(float(created_sa_by_id.get(member_id, {}).get("energy", {}).get("er", 0.0)) for member_id in member_ids),
                            6,
                        ),
                        "display_total_ev": round(
                            sum(float(created_sa_by_id.get(member_id, {}).get("energy", {}).get("ev", 0.0)) for member_id in member_ids),
                            6,
                        ),
                    },
                    "ext": {
                        "packet_context": {
                            "group_index": packet_group_index,
                            "source_group_index": source_group_index,
                            "origin_frame_id": origin_frame_id,
                            "source_type": "memory_feedback",
                            "sequence_index": int(
                                created_sa_by_id.get(anchor_id, {}).get("ext", {}).get("packet_context", {}).get("sequence_index", 0)
                            ),
                        }
                    },
                    "created_at": now_ms,
                    "updated_at": now_ms,
                }
                csa_items.append(csa_obj)
                group_csa_ids.append(csa_id)
                for member_id in member_ids:
                    sa_obj = created_sa_by_id.get(member_id)
                    if not sa_obj:
                        continue
                    if member_id != anchor_id and sa_obj.get("stimulus", {}).get("role") == "attribute":
                        sa_obj.setdefault("source", {}).setdefault("parent_ids", [])
                        sa_obj["source"]["parent_ids"] = [anchor_id]

            grouped_sequences.append(
                {
                    "group_index": packet_group_index,
                    "source_type": "memory_feedback",
                    "origin_frame_id": origin_frame_id,
                    "sa_ids": group_sa_ids,
                    "csa_ids": group_csa_ids,
                    "source_group_index": source_group_index,
                    "order_sensitive": bool(group.get("order_sensitive", False)),
                    "string_unit_kind": str(group.get("string_unit_kind", "") or ""),
                    "string_token_text": str(group.get("string_token_text", "") or ""),
                }
            )

        total_packet_er = round(sum(float(item.get("energy", {}).get("er", 0.0)) for item in sa_items), 6)
        total_packet_ev = round(sum(float(item.get("energy", {}).get("ev", 0.0)) for item in sa_items), 6)
        packet = {
            "id": packet_id,
            "object_type": "stimulus_packet",
            "sub_type": "memory_feedback_stimulus_packet",
            "schema_version": "1.1",
            "packet_type": "memory_feedback",
            "current_frame_id": packet_id,
            "echo_frame_ids": [],
            "sa_items": sa_items,
            "csa_items": csa_items,
            "echo_frames": [],
            "grouped_sa_sequences": grouped_sequences,
            "energy_summary": {
                "total_er": total_packet_er,
                "total_ev": total_packet_ev,
                "current_total_er": total_packet_er,
                "current_total_ev": total_packet_ev,
                "echo_total_er": 0.0,
                "echo_total_ev": 0.0,
                "combined_context_er": total_packet_er,
                "combined_context_ev": total_packet_ev,
                "ownership_level": "sa",
                "echo_merged_into_objects": False,
            },
            "trace_id": trace_id,
            "tick_id": tick_id or trace_id,
            "created_at": now_ms,
            "updated_at": now_ms,
            "source": {
                "module": "observatory",
                "interface": "memory_feedback",
                "origin": "episodic_memory_feedback",
                "origin_id": memory_id,
                "parent_ids": [memory_id],
            },
            "status": "active",
            "ext": {
                "memory_id": memory_id,
                "grouped_display_text": str(memory_material.get("grouped_display_text", "")),
            },
            "meta": {"confidence": 0.7, "field_registry_version": "1.1", "debug": {}, "ext": {}},
        }
        target_display_texts = [
            str(unit.get("content", {}).get("display", ""))
            for unit in sa_items
            if str(unit.get("content", {}).get("display", ""))
        ]
        return {"packet": packet, "target_display_texts": target_display_texts}

    @staticmethod
    def _allocate_weighted_values(*, keys: list[str], raw_weights: dict[str, float], total_value: float) -> dict[str, float]:
        ordered_keys = [str(key) for key in keys if str(key)]
        if not ordered_keys:
            return {}
        total_value = round(max(0.0, float(total_value)), 8)
        if total_value <= 0.0:
            return {key: 0.0 for key in ordered_keys}
        positive_weights = {
            key: max(0.0, float(raw_weights.get(key, 0.0)))
            for key in ordered_keys
        }
        total_weight = sum(positive_weights.values())
        if total_weight <= 0.0:
            positive_weights = {key: 1.0 for key in ordered_keys}
            total_weight = float(len(ordered_keys))
        allocations: dict[str, float] = {}
        remaining = total_value
        for index, key in enumerate(ordered_keys):
            if index == len(ordered_keys) - 1:
                allocations[key] = round(max(0.0, remaining), 8)
                continue
            value = round(total_value * positive_weights[key] / total_weight, 8)
            allocations[key] = value
            remaining = round(remaining - value, 8)
        return allocations

    def _build_sequence_projection_packet(
        self,
        *,
        sequence_groups: list[dict],
        raw_weights: dict[str, float],
        total_er: float,
        total_ev: float,
        trace_id: str,
        tick_id: str,
        display_text: str,
        packet_type: str,
        projection_kind: str,
        origin: str,
        origin_id: str,
        context_ref_object_id: str,
        context_owner_structure_id: str = "",
        context_path_ids: list[str] | None = None,
        source_em_id: str = "",
        residual_origin_kind: str = "induction_target",
        residual_origin_entry_id: str = "",
    ) -> dict[str, Any]:
        sequence_groups = [group for group in sequence_groups if isinstance(group, dict)]
        total_er = round(max(0.0, float(total_er or 0.0)), 8)
        total_ev = round(max(0.0, float(total_ev or 0.0)), 8)
        if not sequence_groups or (total_er <= 0.0 and total_ev <= 0.0):
            return {"packet": None, "target_display_texts": []}

        ordered_unit_ids = [
            str(unit.get("unit_id", ""))
            for group in sequence_groups
            for unit in (group.get("units", []) or [])
            if isinstance(unit, dict) and str(unit.get("unit_id", ""))
        ]
        er_allocations = self._allocate_weighted_values(
            keys=ordered_unit_ids,
            raw_weights=raw_weights or {},
            total_value=total_er,
        )
        ev_allocations = self._allocate_weighted_values(
            keys=ordered_unit_ids,
            raw_weights=raw_weights or {},
            total_value=total_ev,
        )

        now_ms = int(time.time() * 1000)
        packet_id = next_id("indpkt")
        sa_items: list[dict[str, Any]] = []
        csa_items: list[dict[str, Any]] = []
        grouped_sequences: list[dict[str, Any]] = []
        packet_sequence_index = 0
        try:
            min_sa_energy_floor = max(
                0.0,
                float(self._config.get("induction_projection_sa_min_energy_floor", 0.001) or 0.0),
            )
        except Exception:
            min_sa_energy_floor = 0.001
        pruned_sa_count = 0
        pruned_total_er = 0.0
        pruned_total_ev = 0.0
        pruned_new_target_count = 0
        pruned_new_target_er = 0.0
        pruned_new_target_ev = 0.0
        skip_new_target_below_pool_floor = bool(
            self._config.get("induction_projection_skip_new_target_below_pool_threshold_enabled", True)
        )
        try:
            configured_new_target_floor = max(
                0.0,
                float(self._config.get("induction_projection_new_target_min_energy_floor", 0.0) or 0.0),
            )
        except Exception:
            configured_new_target_floor = 0.0
        try:
            pool_new_target_floor = min(
                float(getattr(self.pool, "_config", {}).get("er_elimination_threshold", 0.05) or 0.05),
                float(getattr(self.pool, "_config", {}).get("ev_elimination_threshold", 0.05) or 0.05),
            )
        except Exception:
            pool_new_target_floor = 0.05
        new_target_min_energy_floor = max(0.0, configured_new_target_floor, pool_new_target_floor)
        base_context_ref_id = str(context_ref_object_id or "").strip()
        base_owner_id = str(context_owner_structure_id or base_context_ref_id or "").strip()
        base_context_path_ids = list(context_path_ids or ([base_context_ref_id] if base_context_ref_id else []))
        base_parent_ids = [base_context_ref_id] if base_context_ref_id else []
        base_context_meta = build_context_metadata(
            context_ref_object_id=base_context_ref_id,
            context_ref_object_type="st" if base_context_ref_id else "",
            context_owner_structure_id=base_owner_id,
            context_path_ids=base_context_path_ids,
            parent_ids=base_parent_ids,
        )
        base_residual_meta = build_residual_metadata(
            residual_origin_kind=residual_origin_kind,
            residual_origin_entry_id=residual_origin_entry_id or source_em_id or base_context_ref_id,
        )

        for group in sequence_groups:
            units = [unit for unit in (group.get("units", []) or []) if isinstance(unit, dict)]
            if len(units) > 1:
                last_sequence_index = None
                already_sorted = True
                for unit in units:
                    try:
                        sequence_index = int(unit.get("sequence_index", 0) or 0)
                    except Exception:
                        sequence_index = 0
                    if last_sequence_index is not None and sequence_index < last_sequence_index:
                        already_sorted = False
                        break
                    last_sequence_index = sequence_index
                if not already_sorted:
                    units = sorted(units, key=lambda item: int(item.get("sequence_index", 0) or 0))
            if not units:
                continue
            packet_group_index = len(grouped_sequences)
            source_group_index = int(group.get("source_group_index", group.get("group_index", packet_group_index)) or packet_group_index)
            origin_frame_id = str(group.get("origin_frame_id", origin_id or packet_id) or origin_id or packet_id)
            group_unit_id_map: dict[str, str] = {}
            created_sa_by_id: dict[str, dict] = {}
            group_sa_ids: list[str] = []
            group_csa_ids: list[str] = []

            for unit in units:
                original_unit_id = str(unit.get("unit_id", "") or "")
                if not original_unit_id:
                    continue
                token = str(unit.get("token", unit.get("display_text", "")) or "")
                if (
                    token.startswith("{")
                    and token.endswith("}")
                    and not bool(group.get("order_sensitive", False))
                    and str(group.get("string_unit_kind", "") or "") != "char_sequence"
                ):
                    continue
                unit_role = str(unit.get("unit_role", unit.get("role", "feature")) or "feature")
                attribute_name = str(unit.get("attribute_name", "") or "")
                attribute_value = unit.get("attribute_value")
                value_type = str(unit.get("value_type", "discrete") or "discrete")
                allocated_er = round(float(er_allocations.get(original_unit_id, 0.0) or 0.0), 8)
                allocated_ev = round(float(ev_allocations.get(original_unit_id, 0.0) or 0.0), 8)
                if min_sa_energy_floor > 0.0 and (allocated_er + allocated_ev) < min_sa_energy_floor:
                    pruned_sa_count += 1
                    pruned_total_er = round(pruned_total_er + allocated_er, 8)
                    pruned_total_ev = round(pruned_total_ev + allocated_ev, 8)
                    continue
                if bool(self._config.get("induction_projection_stable_sa_ids_enabled", True)):
                    sa_id = self._stable_induction_projection_sa_id(
                        projection_kind=projection_kind,
                        origin=origin,
                        origin_id=origin_id,
                        context_ref_object_id=base_context_ref_id,
                        context_owner_structure_id=base_owner_id,
                        source_em_id=source_em_id,
                        original_unit_id=original_unit_id,
                        token=token,
                        unit_role=unit_role,
                        attribute_name=attribute_name,
                        attribute_value=attribute_value,
                        source_group_index=source_group_index,
                    )
                else:
                    sa_id = next_id("sa_ind")
                if (
                    skip_new_target_below_pool_floor
                    and new_target_min_energy_floor > 0.0
                    and (allocated_er + allocated_ev) < new_target_min_energy_floor
                ):
                    exists_in_pool = False
                    try:
                        store = getattr(self.pool, "_store", None)
                        exists_in_pool = bool(store is not None and hasattr(store, "get_by_ref") and store.get_by_ref(sa_id))
                    except Exception:
                        exists_in_pool = False
                    if not exists_in_pool:
                        pruned_new_target_count += 1
                        pruned_new_target_er = round(pruned_new_target_er + allocated_er, 8)
                        pruned_new_target_ev = round(pruned_new_target_ev + allocated_ev, 8)
                        continue
                if attribute_name:
                    content = {
                        "raw": token,
                        "display": token,
                        "normalized": token,
                        "value_type": "numerical" if attribute_value is not None else value_type,
                        "attribute_name": attribute_name,
                        "attribute_value": attribute_value,
                    }
                else:
                    content = {
                        "raw": token,
                        "display": token,
                        "normalized": token,
                        "value_type": value_type,
                    }
                packet_context = {
                    "source_type": "induction",
                    "group_index": packet_group_index,
                    "source_group_index": source_group_index,
                    "origin_frame_id": origin_frame_id,
                    "echo_depth": 0,
                    "round_created": 0,
                    "decay_count": 0,
                    "sequence_index": packet_sequence_index,
                    "order_sensitive": bool(group.get("order_sensitive", False)),
                    "string_unit_kind": str(group.get("string_unit_kind", "") or ""),
                    "string_token_text": str(group.get("string_token_text", "") or ""),
                }
                sa_ext = {
                    "packet_context": packet_context,
                    "projection_kind": projection_kind,
                    "backing_structure_id": base_context_ref_id,
                    "target_display_text": display_text,
                    **base_context_meta,
                    **base_residual_meta,
                }
                if source_em_id:
                    sa_ext["source_em_id"] = str(source_em_id)
                sa_obj = {
                    "id": sa_id,
                    "object_type": "sa",
                    "content": content,
                    "stimulus": {
                        "role": unit_role,
                        "modality": "induction",
                        "order_sensitive": bool(group.get("order_sensitive", False)),
                        "string_unit_kind": str(group.get("string_unit_kind", "") or ""),
                        "string_token_text": str(group.get("string_token_text", "") or ""),
                    },
                    "energy": {
                        "er": allocated_er,
                        "ev": allocated_ev,
                    },
                    "source": {
                        "module": "observatory",
                        "interface": "induction_target_packet",
                        "origin": origin,
                        "origin_id": origin_id,
                        "parent_ids": [base_context_ref_id] if base_context_ref_id else [],
                    },
                    "ext": sa_ext,
                    "created_at": now_ms,
                    "updated_at": now_ms,
                }
                group_unit_id_map[original_unit_id] = sa_id
                created_sa_by_id[sa_id] = sa_obj
                sa_items.append(sa_obj)
                group_sa_ids.append(sa_id)
                packet_sequence_index += 1

            for bundle in list(group.get("csa_bundles", []) or []):
                if not isinstance(bundle, dict):
                    continue
                anchor_id = group_unit_id_map.get(str(bundle.get("anchor_unit_id", "") or ""), "")
                member_ids = [
                    group_unit_id_map.get(str(member_id), "")
                    for member_id in (bundle.get("member_unit_ids", []) or [])
                    if group_unit_id_map.get(str(member_id), "")
                ]
                member_ids = list(dict.fromkeys(member_ids))
                if not anchor_id or len(member_ids) < 2:
                    continue
                csa_id = next_id("csa_ind")
                csa_obj = {
                    "id": csa_id,
                    "object_type": "csa",
                    "anchor_sa_id": anchor_id,
                    "member_sa_ids": member_ids,
                    "content": {
                        "display": created_sa_by_id.get(anchor_id, {}).get("content", {}).get("display", ""),
                        "raw": created_sa_by_id.get(anchor_id, {}).get("content", {}).get("raw", ""),
                    },
                    "bundle_summary": {
                        "member_count": len(member_ids),
                        "display_total_er": round(
                            sum(float(created_sa_by_id.get(member_id, {}).get("energy", {}).get("er", 0.0)) for member_id in member_ids),
                            6,
                        ),
                        "display_total_ev": round(
                            sum(float(created_sa_by_id.get(member_id, {}).get("energy", {}).get("ev", 0.0)) for member_id in member_ids),
                            6,
                        ),
                    },
                    "ext": {
                        "packet_context": {
                            "group_index": packet_group_index,
                            "source_group_index": source_group_index,
                            "origin_frame_id": origin_frame_id,
                            "source_type": "induction",
                            "sequence_index": int(
                                created_sa_by_id.get(anchor_id, {}).get("ext", {}).get("packet_context", {}).get("sequence_index", 0)
                            ),
                        }
                    },
                    "created_at": now_ms,
                    "updated_at": now_ms,
                }
                csa_items.append(csa_obj)
                group_csa_ids.append(csa_id)
                for member_id in member_ids:
                    sa_obj = created_sa_by_id.get(member_id)
                    if not sa_obj:
                        continue
                    if member_id != anchor_id and sa_obj.get("stimulus", {}).get("role") == "attribute":
                        sa_obj.setdefault("source", {}).setdefault("parent_ids", [])
                        sa_obj["source"]["parent_ids"] = [anchor_id]

            if group_sa_ids or group_csa_ids:
                grouped_sequences.append(
                    {
                        "group_index": packet_group_index,
                        "source_type": "induction",
                        "origin_frame_id": origin_frame_id,
                        "sa_ids": group_sa_ids,
                        "csa_ids": group_csa_ids,
                        "source_group_index": source_group_index,
                        "order_sensitive": bool(group.get("order_sensitive", False)),
                        "string_unit_kind": str(group.get("string_unit_kind", "") or ""),
                        "string_token_text": str(group.get("string_token_text", "") or ""),
                    }
                )

        if not sa_items and not csa_items:
            return {"packet": None, "target_display_texts": []}

        total_packet_er = round(sum(float(item.get("energy", {}).get("er", 0.0)) for item in sa_items), 6)
        total_packet_ev = round(sum(float(item.get("energy", {}).get("ev", 0.0)) for item in sa_items), 6)
        packet_ext = {
            "projection_kind": projection_kind,
            "backing_structure_id": base_context_ref_id,
            "grouped_display_text": display_text,
            **base_context_meta,
            **base_residual_meta,
        }
        if pruned_sa_count:
            packet_ext["projection_pruned_sa_count"] = int(pruned_sa_count)
            packet_ext["projection_pruned_er"] = round(float(pruned_total_er), 8)
            packet_ext["projection_pruned_ev"] = round(float(pruned_total_ev), 8)
            packet_ext["projection_min_sa_energy_floor"] = round(float(min_sa_energy_floor), 8)
        if pruned_new_target_count:
            packet_ext["projection_pruned_new_target_below_pool_floor_count"] = int(pruned_new_target_count)
            packet_ext["projection_pruned_new_target_er"] = round(float(pruned_new_target_er), 8)
            packet_ext["projection_pruned_new_target_ev"] = round(float(pruned_new_target_ev), 8)
            packet_ext["projection_new_target_min_energy_floor"] = round(float(new_target_min_energy_floor), 8)
        if source_em_id:
            packet_ext["source_em_id"] = str(source_em_id)
        packet = {
            "id": packet_id,
            "object_type": "stimulus_packet",
            "sub_type": "induction_projection_packet",
            "schema_version": "1.1",
            "packet_type": packet_type,
            "current_frame_id": packet_id,
            "echo_frame_ids": [],
            "sa_items": sa_items,
            "csa_items": csa_items,
            "echo_frames": [],
            "grouped_sa_sequences": grouped_sequences,
            "energy_summary": {
                "total_er": total_packet_er,
                "total_ev": total_packet_ev,
                "current_total_er": total_packet_er,
                "current_total_ev": total_packet_ev,
                "echo_total_er": 0.0,
                "echo_total_ev": 0.0,
                "combined_context_er": total_packet_er,
                "combined_context_ev": total_packet_ev,
                "ownership_level": "sa",
                "echo_merged_into_objects": False,
            },
            "trace_id": trace_id,
            "tick_id": tick_id or trace_id,
            "created_at": now_ms,
            "updated_at": now_ms,
            "source": {
                "module": "observatory",
                "interface": "induction_target_packet",
                "origin": origin,
                "origin_id": origin_id,
                "parent_ids": [base_context_ref_id] if base_context_ref_id else [],
            },
            "status": "active",
            "ext": packet_ext,
            "meta": {"confidence": 0.7, "field_registry_version": "1.1", "debug": {}, "ext": {}},
        }
        target_display_texts = [
            str(item.get("content", {}).get("display", ""))
            for item in sa_items
            if str(item.get("content", {}).get("display", ""))
        ]
        return {"packet": packet, "target_display_texts": target_display_texts}

    @staticmethod
    def _stable_induction_projection_sa_id(
        *,
        projection_kind: str,
        origin: str,
        origin_id: str,
        context_ref_object_id: str,
        context_owner_structure_id: str,
        source_em_id: str,
        original_unit_id: str,
        token: str,
        unit_role: str,
        attribute_name: str,
        attribute_value: Any,
        source_group_index: int,
    ) -> str:
        payload = "|".join(
            [
                str(projection_kind or ""),
                str(origin or ""),
                str(origin_id or ""),
                str(context_ref_object_id or ""),
                str(context_owner_structure_id or ""),
                str(source_em_id or ""),
                str(original_unit_id or ""),
                str(source_group_index),
                str(token or ""),
                str(unit_role or ""),
                str(attribute_name or ""),
                repr(attribute_value),
            ]
        )
        digest = hashlib.sha1(payload.encode("utf-8", errors="replace")).hexdigest()[:20]
        return f"sa_ind_{digest}"

    def _build_induction_target_stimulus_packet(
        self,
        *,
        target: dict,
        trace_id: str,
        tick_id: str,
    ) -> dict[str, Any]:
        projection_kind = str(target.get("projection_kind", "structure") or "structure")
        total_er = round(max(0.0, float(target.get("delta_er", target.get("er", 0.0)) or 0.0)), 8)
        total_ev = round(max(0.0, float(target.get("delta_ev", target.get("ev", 0.0)) or 0.0)), 8)
        display_text = str(
            target.get("target_display_text", "")
            or target.get("display_text", "")
            or target.get("target_structure_id", "")
            or target.get("memory_id", "")
        ).strip()
        if total_er <= 0.0 and total_ev <= 0.0:
            return {"packet": None, "target_display_texts": []}

        if projection_kind == "memory":
            memory_id = str(target.get("memory_id", "") or "").strip()
            if not memory_id:
                return {"packet": None, "target_display_texts": []}
            episodic_obj = self.hdb._episodic_store.get(memory_id)
            if not isinstance(episodic_obj, dict):
                return {"packet": None, "target_display_texts": []}
            memory_material = dict((episodic_obj.get("meta", {}) or {}).get("ext", {}).get("memory_material", {}) or {})
            sequence_groups = list(memory_material.get("sequence_groups", []) or [])
            structure_refs = [str(x) for x in (memory_material.get("structure_refs", []) or []) if str(x)]
            backing_structure_id = str(
                target.get("backing_structure_id", "")
                or target.get("target_structure_id", "")
                or (structure_refs[0] if structure_refs else "")
                or ""
            ).strip()
            return self._build_sequence_projection_packet(
                sequence_groups=sequence_groups,
                raw_weights=dict(memory_material.get("unit_energy_profile", {}) or {}),
                total_er=total_er,
                total_ev=total_ev,
                trace_id=trace_id,
                tick_id=tick_id,
                display_text=str(memory_material.get("grouped_display_text", "") or display_text or memory_id),
                packet_type="induction_memory",
                projection_kind=projection_kind,
                origin="induction_memory_target",
                origin_id=memory_id,
                context_ref_object_id=backing_structure_id,
                context_owner_structure_id=backing_structure_id,
                context_path_ids=[backing_structure_id] if backing_structure_id else [],
                source_em_id=memory_id,
                residual_origin_kind="induction_memory_target",
                residual_origin_entry_id=memory_id,
            )

        structure_id = str(target.get("target_structure_id", "") or target.get("structure_id", "") or "").strip()
        if not structure_id:
            return {"packet": None, "target_display_texts": []}
        structure_obj = self.hdb._structure_store.get(structure_id)
        if not isinstance(structure_obj, dict):
            return {"packet": None, "target_display_texts": []}
        structure_block = structure_obj.get("structure", {}) if isinstance(structure_obj.get("structure", {}), dict) else {}
        structure_cache_key = (
            "induction_structure_projection_template",
            structure_id,
            int(structure_obj.get("updated_at", 0) or 0),
            str(structure_block.get("content_signature", "") or ""),
        )
        cached_projection_template = None
        if hasattr(self.hdb._structure_store, "get_shared_runtime_cache_entry"):
            cached_projection_template = self.hdb._structure_store.get_shared_runtime_cache_entry(
                "observatory_induction_projection_templates",
                structure_cache_key,
            )
        if not isinstance(cached_projection_template, dict):
            sequence_groups = list(structure_block.get("sequence_groups", []) or [])
            raw_weights: dict[str, float] = {}
            for group in sequence_groups:
                if not isinstance(group, dict):
                    continue
                for unit in list(group.get("units", []) or []):
                    if not isinstance(unit, dict):
                        continue
                    unit_id = str(unit.get("unit_id", "") or "")
                    if not unit_id or bool(unit.get("is_placeholder", False)):
                        continue
                    raw_weights[unit_id] = round(
                        float(raw_weights.get(unit_id, 0.0))
                        + max(0.0, float(unit.get("er", 0.0) or 0.0))
                        + max(0.0, float(unit.get("ev", 0.0) or 0.0)),
                        8,
                    )
            cached_projection_template = {
                "sequence_groups": sequence_groups,
                "raw_weights": raw_weights,
                "display_text": str(structure_block.get("display_text", "") or display_text or structure_id),
                "structure_ext": dict(structure_block.get("ext", {}) or {}),
            }
            if hasattr(self.hdb._structure_store, "set_shared_runtime_cache_entry"):
                self.hdb._structure_store.set_shared_runtime_cache_entry(
                    "observatory_induction_projection_templates",
                    structure_cache_key,
                    cached_projection_template,
                )
        sequence_groups = list(cached_projection_template.get("sequence_groups", []) or [])
        raw_weights = dict(cached_projection_template.get("raw_weights", {}) or {})
        structure_ext = dict(cached_projection_template.get("structure_ext", {}) or {})
        return self._build_sequence_projection_packet(
            sequence_groups=sequence_groups,
            raw_weights=raw_weights,
            total_er=total_er,
            total_ev=total_ev,
            trace_id=trace_id,
            tick_id=tick_id,
            display_text=str(cached_projection_template.get("display_text", "") or display_text or structure_id),
            packet_type="induction_structure",
            projection_kind=projection_kind,
            origin="induction_structure_target",
            origin_id=structure_id,
            context_ref_object_id=structure_id,
            context_owner_structure_id=str(structure_ext.get("context_owner_structure_id", "") or structure_id),
            context_path_ids=[structure_id],
            source_em_id=str(target.get("source_em_id", "") or ""),
            residual_origin_kind=str(structure_ext.get("residual_origin_kind", "") or "induction_structure_target"),
            residual_origin_entry_id=structure_id,
        )

    def _project_structure_ids(self, structure_ids: list[str], trace_id: str, tick_id: str, *, er: float, ev: float, reason: str) -> list[dict]:
        projections = []
        for structure_id in structure_ids:
            projections.append({"structure_id": structure_id, "er": er, "ev": ev, "reason": reason})
        return self._project_runtime_structures(projections, trace_id, tick_id)

    def _induction_projection_mode(self) -> str:
        mode = str(self._config.get("induction_projection_mode", "growth") or "growth").strip().lower()
        if mode not in {"growth", "residual"}:
            mode = "growth"
        return mode

    def _prepare_induction_projection_targets(
        self,
        *,
        induction_data: dict,
        trace_id: str,
        tick_id: str,
    ) -> tuple[list[dict], dict[str, Any]]:
        raw_targets = [dict(item) for item in list(induction_data.get("induction_targets", []) or []) if isinstance(item, dict)]
        mode = self._induction_projection_mode()
        if mode != "growth":
            return raw_targets, {
                "mode": "residual",
                "raw_target_count": len(raw_targets),
                "projected_target_count": len(raw_targets),
                "growth_target_count": 0,
                "rollback_path": "legacy_residual_projection",
            }
        return self._build_growth_projection_targets_from_source_details(
            induction_data=induction_data,
            raw_targets=raw_targets,
            trace_id=trace_id,
            tick_id=tick_id,
        )

    def _build_growth_projection_targets_from_source_details(
        self,
        *,
        induction_data: dict,
        raw_targets: list[dict],
        trace_id: str,
        tick_id: str,
    ) -> tuple[list[dict], dict[str, Any]]:
        summary: dict[str, Any] = {
            "mode": "growth",
            "raw_target_count": len(raw_targets),
            "projected_target_count": 0,
            "source_detail_count": 0,
            "candidate_entry_count": 0,
            "growth_target_count": 0,
            "growth_identity_hit_count": 0,
            "growth_identity_created_count": 0,
            "growth_identity_local_cache_hit_count": 0,
            "growth_identity_shared_cache_hit_count": 0,
            "growth_identity_shared_cache_stale_count": 0,
            "growth_identity_create_exact_lookup_skipped_count": 0,
            "growth_identity_lookup_disabled_count": 0,
            "growth_runtime_only_count": 0,
            "growth_memory_candidate_count": 0,
            "growth_memory_terminal_passthrough_count": 0,
            "growth_pruned_low_energy_count": 0,
            "growth_failed_count": 0,
            "growth_skipped_missing_source_count": 0,
            "growth_skipped_missing_residual_count": 0,
            "growth_deduped_count": 0,
            "growth_total_delta_er": 0.0,
            "growth_total_delta_ev": 0.0,
            "identity_resolution_enabled": bool(
                self._config.get("growth_projection_identity_resolution_enabled", True)
            ),
            "create_hdb_structure_enabled": bool(
                self._config.get("growth_projection_create_hdb_structure_enabled", True)
            ),
            "runtime_only_for_unbacked_virtual": bool(
                self._config.get("growth_projection_runtime_only_for_unbacked_virtual", True)
            ),
            "component_energy_enabled": bool(
                self._config.get("growth_projection_component_energy_enabled", True)
            ),
            "low_energy_prune_enabled": bool(
                self._config.get("growth_projection_low_energy_prune_enabled", True)
            ),
            "identity_shared_cache_enabled": bool(
                self._config.get("growth_projection_identity_shared_cache_enabled", True)
            ),
            "overprediction_gate_enabled": bool(
                self._config.get("growth_projection_overprediction_gate_enabled", False)
            ),
            "persistence_batch_enabled": False,
        }
        debug = induction_data.get("debug", {}) if isinstance(induction_data.get("debug", {}), dict) else {}
        source_details = [
            row for row in list(debug.get("source_details", []) or [])
            if isinstance(row, dict)
        ]
        summary["source_detail_count"] = len(source_details)

        create_enabled = bool(summary["create_hdb_structure_enabled"])
        identity_enabled = bool(summary["identity_resolution_enabled"])
        runtime_only_enabled = bool(summary["runtime_only_for_unbacked_virtual"])
        low_energy_prune_enabled = bool(summary["low_energy_prune_enabled"])
        try:
            energy_floor = max(
                0.0,
                float(self._config.get("induction_projection_sa_min_energy_floor", 0.001) or 0.001),
            )
        except Exception:
            energy_floor = 0.001
        try:
            pool_floor = min(
                float(getattr(self.pool, "_config", {}).get("er_elimination_threshold", 0.05) or 0.05),
                float(getattr(self.pool, "_config", {}).get("ev_elimination_threshold", 0.05) or 0.05),
            )
        except Exception:
            pool_floor = 0.05
        if low_energy_prune_enabled:
            energy_floor = max(energy_floor, max(0.0, pool_floor))

        projected: list[dict] = []
        by_structure_id: dict[str, dict] = {}
        runtime_only_rows: list[dict] = []
        source_profile_cache: dict[str, dict] = {}
        residual_profile_cache: dict[tuple[str, str], dict] = {}
        identity_resolution_cache: dict[tuple[str, str], dict[str, Any]] = {}
        persistence_batch_enabled = bool(
            self._config.get("growth_projection_persistence_batch_enabled", True)
            and create_enabled
            and bool(getattr(self.hdb, "_config", {}).get("deferred_persistence_enabled", True))
            and hasattr(self.hdb._structure_store, "batch_persistence")
        )
        summary["persistence_batch_enabled"] = bool(persistence_batch_enabled)
        batch_ctx = (
            self.hdb._structure_store.batch_persistence(
                flush=self.hdb._should_flush_deferred_persistence()
            )
            if persistence_batch_enabled
            else nullcontext()
        )

        with batch_ctx:
            for source_detail in source_details:
                root_source_structure_id = str(source_detail.get("source_structure_id", "") or "").strip()
                source_er = max(0.0, float(source_detail.get("source_er", 0.0) or 0.0))
                source_ev = max(0.0, float(source_detail.get("source_ev", 0.0) or 0.0))
                candidates = [
                    row for row in list(source_detail.get("candidate_entries", []) or [])
                    if isinstance(row, dict)
                ]
                summary["candidate_entry_count"] = int(summary["candidate_entry_count"]) + len(candidates)
                for candidate in candidates:
                    projection_kind = str(candidate.get("projection_kind", "structure") or "structure")
                    delta_ev = round(max(0.0, float(candidate.get("delta_ev", 0.0) or 0.0)), 8)
                    if low_energy_prune_enabled and delta_ev < energy_floor:
                        summary["growth_pruned_low_energy_count"] = int(summary["growth_pruned_low_energy_count"]) + 1
                        continue
                    if projection_kind == "memory":
                        summary["growth_memory_candidate_count"] = int(summary["growth_memory_candidate_count"]) + 1
                        summary["growth_memory_terminal_passthrough_count"] = int(summary["growth_memory_terminal_passthrough_count"]) + 1
                        continue

                    direct_source_structure_id = str(
                        candidate.get("growth_source_structure_id", "")
                        or candidate.get("direct_source_structure_id", "")
                        or root_source_structure_id
                    ).strip()
                    source_profile = self._growth_projection_source_profile(
                        direct_source_structure_id,
                        cache=source_profile_cache,
                    )
                    if not source_profile:
                        summary["growth_skipped_missing_source_count"] = int(summary["growth_skipped_missing_source_count"]) + 1
                        continue
                    residual_profile = self._growth_projection_residual_profile(
                        candidate,
                        cache=residual_profile_cache,
                    )
                    if not residual_profile:
                        summary["growth_skipped_missing_residual_count"] = int(summary["growth_skipped_missing_residual_count"]) + 1
                        continue

                    grown_profile = self._compose_growth_projection_profile(
                        source_profile=source_profile,
                        residual_profile=residual_profile,
                        candidate=candidate,
                        source_structure_id=direct_source_structure_id,
                        root_source_structure_id=root_source_structure_id,
                    )
                    if not grown_profile:
                        summary["growth_failed_count"] = int(summary["growth_failed_count"]) + 1
                        continue

                    resolved = self._resolve_growth_projection_profile(
                        profile=grown_profile,
                        source_structure_id=direct_source_structure_id,
                        candidate=candidate,
                        trace_id=trace_id,
                        tick_id=tick_id,
                        create_enabled=create_enabled,
                        identity_enabled=identity_enabled,
                        source_er=source_er,
                        delta_ev=delta_ev,
                        cache=identity_resolution_cache,
                    )
                    if bool(resolved.get("shared_cache_stale", False)):
                        summary["growth_identity_shared_cache_stale_count"] = int(summary["growth_identity_shared_cache_stale_count"]) + 1
                    structure_obj = resolved.get("structure") if isinstance(resolved, dict) else None
                    if not isinstance(structure_obj, dict):
                        if runtime_only_enabled:
                            runtime_only_rows.append(
                                {
                                    "projection_kind": "structure",
                                    "target_structure_id": "",
                                    "backing_structure_id": "",
                                    "target_display_text": str(grown_profile.get("display_text", "")),
                                    "delta_er": 0.0,
                                    "delta_ev": delta_ev,
                                    "growth_projection": {
                                        "runtime_only": True,
                                        "source_structure_id": direct_source_structure_id,
                                        "root_source_structure_id": root_source_structure_id,
                                        "target_structure_id": str(candidate.get("target_structure_id", "") or ""),
                                        "target_display_text": str(candidate.get("target_display_text", "") or ""),
                                        "reason": str(resolved.get("reason", "identity_unresolved") if isinstance(resolved, dict) else "identity_unresolved"),
                                    },
                                }
                            )
                            summary["growth_runtime_only_count"] = int(summary["growth_runtime_only_count"]) + 1
                        else:
                            summary["growth_failed_count"] = int(summary["growth_failed_count"]) + 1
                        continue

                    grown_structure_id = str(structure_obj.get("id", "") or "").strip()
                    if not grown_structure_id:
                        summary["growth_failed_count"] = int(summary["growth_failed_count"]) + 1
                        continue
                    if bool(resolved.get("identity_lookup_disabled", False)):
                        summary["growth_identity_lookup_disabled_count"] = int(summary["growth_identity_lookup_disabled_count"]) + 1
                    elif bool(resolved.get("local_cache_hit", False)):
                        summary["growth_identity_local_cache_hit_count"] = int(summary["growth_identity_local_cache_hit_count"]) + 1
                    elif bool(resolved.get("shared_cache_hit", False)):
                        summary["growth_identity_shared_cache_hit_count"] = int(summary["growth_identity_shared_cache_hit_count"]) + 1
                    elif bool(resolved.get("created", False)):
                        summary["growth_identity_created_count"] = int(summary["growth_identity_created_count"]) + 1
                    else:
                        summary["growth_identity_hit_count"] = int(summary["growth_identity_hit_count"]) + 1
                    if bool(resolved.get("create_exact_lookup_skipped", False)):
                        summary["growth_identity_create_exact_lookup_skipped_count"] = int(
                            summary["growth_identity_create_exact_lookup_skipped_count"]
                        ) + 1

                    delta_er = self._growth_projection_delta_er_share(
                        source_er=source_er,
                        delta_ev=delta_ev,
                    )
                    component_energy = self._growth_projection_component_energy_audit(
                        source_structure_id=direct_source_structure_id,
                        root_source_structure_id=root_source_structure_id,
                        residual_target_structure_id=str(candidate.get("target_structure_id", "") or ""),
                        source_er=source_er,
                        source_ev=source_ev,
                        delta_er=delta_er,
                        delta_ev=delta_ev,
                        source_profile=source_profile,
                        residual_profile=residual_profile,
                    )
                    row = {
                    "projection_kind": "structure",
                    "memory_id": "",
                    "target_structure_id": grown_structure_id,
                    "structure_id": grown_structure_id,
                    "backing_structure_id": grown_structure_id,
                    "target_display_text": str(
                        grown_profile.get("display_text", "")
                        or (structure_obj.get("structure", {}) or {}).get("display_text", "")
                        or grown_structure_id
                    ),
                    "delta_er": delta_er,
                    "delta_ev": delta_ev,
                    "sources": [direct_source_structure_id],
                    "modes": [str(candidate.get("mode", "") or "growth_projection")],
                    "mode": str(candidate.get("mode", "") or "growth_projection"),
                    "runtime_weight": round(float(candidate.get("runtime_weight", 0.0) or 0.0), 8),
                    "source_em_id": str(candidate.get("source_em_id", "") or ""),
                    "growth_projection": {
                        "enabled": True,
                        "source_structure_id": direct_source_structure_id,
                        "root_source_structure_id": root_source_structure_id,
                        "residual_target_structure_id": str(candidate.get("target_structure_id", "") or ""),
                        "residual_backing_structure_id": str(candidate.get("backing_structure_id", "") or ""),
                        "residual_display_text": str(candidate.get("target_display_text", "") or ""),
                        "identity_created": bool(resolved.get("created", False)),
                        "identity_lookup_disabled": bool(resolved.get("identity_lookup_disabled", False)),
                        "projection_mode": "growth",
                    },
                    "component_energy": component_energy,
                    "reason": "induction_growth_target",
                }
                    existing = by_structure_id.get(grown_structure_id)
                    if existing is None:
                        by_structure_id[grown_structure_id] = row
                        projected.append(row)
                    else:
                        existing["delta_er"] = round(float(existing.get("delta_er", 0.0) or 0.0) + delta_er, 8)
                        existing["delta_ev"] = round(float(existing.get("delta_ev", 0.0) or 0.0) + delta_ev, 8)
                        existing["er"] = existing["delta_er"]
                        existing["ev"] = existing["delta_ev"]
                        gp = existing.setdefault("growth_projection", {})
                        if isinstance(gp, dict):
                            sources = list(gp.get("source_structure_ids", []) or [])
                            if not sources:
                                sources = [str(gp.get("source_structure_id", "") or "")]
                            if direct_source_structure_id and direct_source_structure_id not in sources:
                                sources.append(direct_source_structure_id)
                            gp["source_structure_ids"] = [source for source in sources if source]
                            gp["merged_candidate_count"] = int(gp.get("merged_candidate_count", 1) or 1) + 1
                        summary["growth_deduped_count"] = int(summary["growth_deduped_count"]) + 1

        for row in projected:
            row["er"] = round(float(row.get("delta_er", row.get("er", 0.0)) or 0.0), 8)
            row["ev"] = round(float(row.get("delta_ev", row.get("ev", 0.0)) or 0.0), 8)
            summary["growth_total_delta_er"] = round(float(summary["growth_total_delta_er"]) + float(row["er"]), 8)
            summary["growth_total_delta_ev"] = round(float(summary["growth_total_delta_ev"]) + float(row["ev"]), 8)

        summary["growth_target_count"] = len(projected)
        summary["projected_target_count"] = len(projected)
        summary["runtime_only_preview"] = runtime_only_rows[:8]
        return projected, summary

    def _growth_projection_source_profile(self, structure_id: str, *, cache: dict[str, dict]) -> dict:
        structure_id = str(structure_id or "").strip()
        if not structure_id:
            return {}
        if structure_id in cache:
            return dict(cache.get(structure_id, {}) or {})
        structure_obj = self.hdb._structure_store.get(structure_id)
        if not isinstance(structure_obj, dict):
            cache[structure_id] = {}
            return {}
        profile = self.cut_engine.build_sequence_profile_from_structure(structure_obj)
        cache[structure_id] = dict(profile or {})
        return dict(profile or {})

    def _growth_projection_residual_profile(self, candidate: dict, *, cache: dict[tuple[str, str], dict]) -> dict:
        projection_kind = str(candidate.get("projection_kind", "structure") or "structure")
        if projection_kind == "memory":
            memory_id = str(candidate.get("memory_id", "") or "").strip()
            cache_key = ("memory", memory_id)
            if cache_key in cache:
                return dict(cache.get(cache_key, {}) or {})
            episodic_obj = self.hdb._episodic_store.get(memory_id) if memory_id else None
            if not isinstance(episodic_obj, dict):
                cache[cache_key] = {}
                return {}
            memory_material = dict((episodic_obj.get("meta", {}) or {}).get("ext", {}).get("memory_material", {}) or {})
            sequence_groups = list(memory_material.get("sequence_groups", []) or [])
            profile = self.cut_engine.build_sequence_profile_from_groups(sequence_groups) if sequence_groups else {}
            cache[cache_key] = dict(profile or {})
            return dict(profile or {})

        embedded_profile = candidate.get("target_profile", {})
        if isinstance(embedded_profile, dict) and embedded_profile.get("sequence_groups"):
            return dict(embedded_profile)
        structure_id = str(candidate.get("target_structure_id", "") or candidate.get("structure_id", "") or "").strip()
        cache_key = ("structure", structure_id)
        if cache_key in cache:
            return dict(cache.get(cache_key, {}) or {})
        structure_obj = self.hdb._structure_store.get(structure_id) if structure_id else None
        if not isinstance(structure_obj, dict):
            cache[cache_key] = {}
            return {}
        profile = self.cut_engine.build_sequence_profile_from_structure(structure_obj)
        cache[cache_key] = dict(profile or {})
        return dict(profile or {})

    def _compose_growth_projection_profile(
        self,
        *,
        source_profile: dict,
        residual_profile: dict,
        candidate: dict,
        source_structure_id: str,
        root_source_structure_id: str,
    ) -> dict:
        relation_type = str(candidate.get("relation_type", "") or "").strip()
        if not self._growth_projection_should_compose_source(candidate):
            profile = dict(residual_profile or {})
            if not profile.get("sequence_groups"):
                return {}
            display_text = format_sequence_groups(list(profile.get("sequence_groups", []) or [])) or str(profile.get("display_text", ""))
            ext = dict(profile.get("ext", {}) or {}) if isinstance(profile.get("ext", {}), dict) else {}
            for key in ("context_ref_object_id", "context_ref_object_type", "context_owner_structure_id", "context_path_ids"):
                ext.pop(key, None)
            ext.update(
                {
                    "kind": "induction_growth_projection",
                    "sequence_mode": "group_relaxed",
                    "growth_projection": True,
                    "growth_projection_direct_complete_target": True,
                    "growth_source_structure_id": str(source_structure_id or ""),
                    "growth_root_source_structure_id": str(root_source_structure_id or ""),
                    "growth_residual_target_structure_id": str(candidate.get("target_structure_id", "") or ""),
                    "growth_residual_backing_structure_id": str(candidate.get("backing_structure_id", "") or ""),
                    "growth_residual_display_text": str(candidate.get("target_display_text", "") or ""),
                    "growth_relation_type": relation_type,
                    "growth_mode": str(candidate.get("mode", "") or ""),
                    "growth_projection_owner_is_provenance_only": True,
                }
            )
            profile["display_text"] = display_text
            profile["grouped_display_text"] = display_text
            profile["ext"] = ext
            return profile

        source_groups = [dict(group) for group in list(source_profile.get("sequence_groups", []) or []) if isinstance(group, dict)]
        residual_groups = [dict(group) for group in list(residual_profile.get("sequence_groups", []) or []) if isinstance(group, dict)]
        if not source_groups or not residual_groups:
            return {}
        merged_groups: list[dict] = []
        for group in source_groups + residual_groups:
            next_group = dict(group)
            next_group["group_index"] = len(merged_groups)
            merged_groups.append(next_group)
        profile = self.cut_engine.build_sequence_profile_from_groups(merged_groups)
        display_text = format_sequence_groups(list(profile.get("sequence_groups", []) or [])) or str(profile.get("display_text", ""))
        provenance = {
            "kind": "induction_growth_projection",
            "sequence_mode": "group_relaxed",
            "growth_projection": True,
            "growth_source_structure_id": str(source_structure_id or ""),
            "growth_root_source_structure_id": str(root_source_structure_id or ""),
            "growth_residual_target_structure_id": str(candidate.get("target_structure_id", "") or ""),
            "growth_residual_backing_structure_id": str(candidate.get("backing_structure_id", "") or ""),
            "growth_residual_display_text": str(candidate.get("target_display_text", "") or ""),
            "growth_relation_type": relation_type,
            "growth_mode": str(candidate.get("mode", "") or ""),
            "growth_projection_owner_is_provenance_only": True,
        }
        profile["display_text"] = display_text
        profile["grouped_display_text"] = display_text
        profile["ext"] = provenance
        return profile

    @staticmethod
    def _growth_projection_should_compose_source(candidate: dict) -> bool:
        relation_type = str(candidate.get("relation_type", "") or "").strip()
        if relation_type in {
            "residual_context",
            "residual_context_common",
            "structure_raw_residual",
            "stimulus_raw_residual",
            "stimulus_raw_residual_materialized_structure",
        }:
            return True
        residual_kind = str(candidate.get("residual_origin_kind", "") or "").strip()
        if residual_kind in {
            "structure_raw_residual",
            "stimulus_raw_residual",
            "stimulus_raw_residual_materialized_structure",
        }:
            return True
        return False

    def _resolve_growth_projection_profile(
        self,
        *,
        profile: dict,
        source_structure_id: str,
        candidate: dict,
        trace_id: str,
        tick_id: str,
        create_enabled: bool,
        identity_enabled: bool,
        source_er: float,
        delta_ev: float,
        cache: dict[tuple[str, str], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not profile:
            return {"structure": None, "created": False, "reason": "empty_profile"}
        profile_no_context = dict(profile)
        ext = dict(profile_no_context.get("ext", {}) or {})
        for key in ("context_ref_object_id", "context_ref_object_type", "context_owner_structure_id", "context_path_ids"):
            ext.pop(key, None)
        profile_no_context["ext"] = ext
        if not identity_enabled:
            return {"structure": None, "created": False, "identity_lookup_disabled": True, "reason": "identity_resolution_disabled"}

        canonical_profile = self._growth_projection_canonical_profile(profile_no_context)
        signature = str(canonical_profile.get("content_signature", "") or profile_no_context.get("content_signature", "") or "")
        group_signature = ""
        try:
            group_signature = "|".join(
                str(group.get("group_signature", "") or "")
                for group in list(canonical_profile.get("sequence_groups", []) or [])
                if isinstance(group, dict)
            )
        except Exception:
            group_signature = ""
        cache_key = (signature, group_signature)
        if isinstance(cache, dict):
            cached = cache.get(cache_key)
            if isinstance(cached, dict):
                structure_id = str(cached.get("structure_id", "") or "")
                structure_obj = self.hdb._structure_store.get(structure_id) if structure_id else None
                if isinstance(structure_obj, dict):
                    return {
                        "structure": structure_obj,
                        "created": False,
                        "canonical_profile": cached.get("canonical_profile", canonical_profile),
                        "local_cache_hit": True,
                    }
        shared_cache_enabled = bool(self._config.get("growth_projection_identity_shared_cache_enabled", True))
        shared_cache_key = None
        shared_cache_stale = False
        if shared_cache_enabled and hasattr(self.hdb._structure_store, "get_shared_runtime_cache_entry"):
            shared_cache_key = (
                "growth_projection_identity",
                signature,
                group_signature,
                "context_free",
            )
            shared_cached = self.hdb._structure_store.get_shared_runtime_cache_entry(
                "observatory_growth_projection_identity",
                shared_cache_key,
            )
            if isinstance(shared_cached, dict):
                structure_id = str(shared_cached.get("structure_id", "") or "")
                structure_obj = self.hdb._structure_store.get(structure_id) if structure_id else None
                if isinstance(structure_obj, dict):
                    if isinstance(cache, dict):
                        cache[cache_key] = {
                            "structure_id": structure_id,
                            "canonical_profile": shared_cached.get("canonical_profile", canonical_profile),
                        }
                    return {
                        "structure": structure_obj,
                        "created": False,
                        "canonical_profile": shared_cached.get("canonical_profile", canonical_profile),
                        "shared_cache_hit": True,
                    }
                shared_cache_stale = True
                if hasattr(self.hdb._structure_store, "set_shared_runtime_cache_entry"):
                    # Replace the stale entry with an empty miss marker for this revision.
                    self.hdb._structure_store.set_shared_runtime_cache_entry(
                        "observatory_growth_projection_identity",
                        shared_cache_key,
                        {"structure_id": "", "stale": True},
                    )
        existing = find_exact_structure_by_signature(
            signature=signature,
            structure_store=self.hdb._structure_store,
            pointer_index=self.hdb._pointer_index,
            cut_engine=self.cut_engine,
            expected_tokens=list(canonical_profile.get("flat_tokens", []) or []),
            expected_sequence_groups=list(canonical_profile.get("sequence_groups", []) or []),
            expected_context={},
            strict_context_owner_match=False,
            strict_context_ref_match=False,
            require_context_free=True,
        )
        if isinstance(existing, dict):
            if isinstance(cache, dict):
                cache[cache_key] = {
                    "structure_id": str(existing.get("id", "") or ""),
                    "canonical_profile": canonical_profile,
                }
            if (
                shared_cache_enabled
                and shared_cache_key is not None
                and hasattr(self.hdb._structure_store, "set_shared_runtime_cache_entry")
            ):
                self.hdb._structure_store.set_shared_runtime_cache_entry(
                    "observatory_growth_projection_identity",
                    shared_cache_key,
                    {
                        "structure_id": str(existing.get("id", "") or ""),
                        "canonical_profile": canonical_profile,
                    },
                )
            return {"structure": existing, "created": False, "canonical_profile": canonical_profile}
        if not create_enabled:
            return {"structure": None, "created": False, "reason": "create_disabled", "shared_cache_stale": shared_cache_stale}
        base_weight = self._growth_projection_base_weight(source_er=source_er, delta_ev=delta_ev)
        exact_probe_is_final = bool(canonical_profile.get("_growth_projection_exact_probe_is_final", False))
        canonical_profile_for_create = dict(canonical_profile)
        canonical_profile_for_create.pop("_growth_projection_exact_probe_is_final", None)
        skip_create_exact_lookup = bool(
            self._config.get("growth_projection_skip_create_exact_lookup_after_probe_enabled", True)
            and exact_probe_is_final
        )
        result = resolve_or_create_structure_from_profile(
            profile=profile_no_context,
            canonical_profile=canonical_profile_for_create,
            structure_store=self.hdb._structure_store,
            pointer_index=self.hdb._pointer_index,
            cut_engine=self.cut_engine,
            trace_id=f"{trace_id}_growth_projection",
            tick_id=tick_id,
            confidence=0.72,
            origin="induction_growth_projection",
            origin_id="|".join(
                [
                    str(source_structure_id or ""),
                    str(candidate.get("target_structure_id", "") or ""),
                    str(candidate.get("memory_id", "") or ""),
                    str(candidate.get("mode", "") or ""),
                ]
            ),
            parent_ids=[],
            base_weight=base_weight,
            ext=ext,
            source_interface="observatory_induction_growth_projection",
            strict_context_owner_match=False,
            strict_context_ref_match=False,
            require_context_free=True,
            skip_exact_lookup=skip_create_exact_lookup,
        )
        if isinstance(result, dict) and skip_create_exact_lookup:
            result["create_exact_lookup_skipped"] = True
        if isinstance(cache, dict) and isinstance(result, dict):
            structure_obj = result.get("structure")
            if isinstance(structure_obj, dict):
                cache[cache_key] = {
                    "structure_id": str(structure_obj.get("id", "") or ""),
                    "canonical_profile": result.get("canonical_profile", canonical_profile),
                }
                if (
                    shared_cache_enabled
                    and shared_cache_key is not None
                    and hasattr(self.hdb._structure_store, "set_shared_runtime_cache_entry")
                ):
                    self.hdb._structure_store.set_shared_runtime_cache_entry(
                        "observatory_growth_projection_identity",
                        shared_cache_key,
                        {
                            "structure_id": str(structure_obj.get("id", "") or ""),
                            "canonical_profile": result.get("canonical_profile", canonical_profile),
                        },
                    )
                if shared_cache_stale:
                    result["shared_cache_stale"] = True
        return result

    def _growth_projection_canonical_profile(self, profile: dict) -> dict:
        groups = [group for group in list(profile.get("sequence_groups", []) or []) if isinstance(group, dict)]
        signature = str(profile.get("content_signature", "") or "")
        has_stable_groups = bool(groups) and all(str(group.get("group_signature", "") or "") for group in groups)
        has_self_placeholder = self._growth_projection_profile_has_self_placeholder(groups)
        if signature and has_stable_groups and not has_self_placeholder:
            canonical = dict(profile)
            canonical["sequence_groups"] = groups
            canonical["_growth_projection_exact_probe_is_final"] = True
            return canonical
        canonical = self.cut_engine.build_sequence_profile_from_groups(groups)
        canonical["_growth_projection_exact_probe_is_final"] = not has_self_placeholder
        return canonical

    @staticmethod
    def _growth_projection_profile_has_self_placeholder(groups: list[dict]) -> bool:
        for group in groups:
            if not isinstance(group, dict):
                continue
            for unit in list(group.get("units", []) or []):
                if isinstance(unit, dict) and str(unit.get("token", "") or "").startswith("SELF["):
                    return True
        return False

    def _growth_projection_base_weight(self, *, source_er: float, delta_ev: float) -> float:
        source_er = max(0.0, float(source_er or 0.0))
        if source_er <= 0.0:
            return 0.0
        try:
            ratio = max(0.0, float(self._config.get("growth_projection_er_base_weight_ratio", 0.08) or 0.08))
        except Exception:
            ratio = 0.08
        try:
            cap = max(0.0, float(self._config.get("growth_projection_er_base_weight_cap", 0.35) or 0.35))
        except Exception:
            cap = 0.35
        return round(min(cap, source_er * ratio), 8)

    def _growth_projection_delta_er_share(self, *, source_er: float, delta_ev: float) -> float:
        if not bool(self._config.get("growth_projection_source_er_runtime_share_enabled", True)):
            return 0.0
        source_er = max(0.0, float(source_er or 0.0))
        delta_ev = max(0.0, float(delta_ev or 0.0))
        if source_er <= 0.0 or delta_ev <= 0.0:
            return 0.0
        try:
            ratio = max(0.0, min(1.0, float(self._config.get("growth_projection_source_er_runtime_share_ratio", 1.0) or 1.0)))
        except Exception:
            ratio = 1.0
        return round(min(source_er, delta_ev) * ratio, 8)

    @staticmethod
    def _growth_projection_component_energy_audit(
        *,
        source_structure_id: str,
        root_source_structure_id: str,
        residual_target_structure_id: str,
        source_er: float,
        source_ev: float,
        delta_er: float,
        delta_ev: float,
        source_profile: dict,
        residual_profile: dict,
    ) -> dict[str, Any]:
        return {
            "ownership_level": "sa_component_audit",
            "structure_energy_is_statistical": True,
            "source_structure_id": str(source_structure_id or ""),
            "root_source_structure_id": str(root_source_structure_id or ""),
            "residual_target_structure_id": str(residual_target_structure_id or ""),
            "source_available_er": round(max(0.0, float(source_er or 0.0)), 8),
            "source_available_ev": round(max(0.0, float(source_ev or 0.0)), 8),
            "source_component_er_share": round(max(0.0, float(delta_er or 0.0)), 8),
            "source_component_ev_share": 0.0,
            "residual_component_er_share": 0.0,
            "residual_component_ev_share": round(max(0.0, float(delta_ev or 0.0)), 8),
            "source_unit_count": int(source_profile.get("unit_count", 0) or 0),
            "residual_unit_count": int(residual_profile.get("unit_count", 0) or 0),
        }

    def _collect_induction_source_support_structure_ids(self, item: dict) -> list[str]:
        """Best-effort resolve runtime source -> supporting structure ids for induction lookup."""
        if not isinstance(item, dict):
            return []
        if self._is_runtime_only_residual_item(item):
            return []

        structure_store = getattr(getattr(self, "hdb", None), "_structure_store", None)
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        ref_object_type = str(item.get("ref_object_type", "") or "").strip().lower()
        ref_object_id = str(item.get("ref_object_id", "") or "").strip()
        context_owner_id = str(
            item.get("context_owner_structure_id", "")
            or item.get("context_owner_id", "")
            or ref_snapshot.get("context_owner_id", "")
            or ""
        ).strip()
        context_ref_type = str(
            item.get("context_ref_object_type", "")
            or ref_snapshot.get("context_ref_object_type", "")
            or ""
        ).strip().lower()
        context_ref_id = str(
            item.get("context_ref_object_id", "")
            or ref_snapshot.get("context_ref_object_id", "")
            or ""
        ).strip()
        target_ref_type = str(
            item.get("target_ref_object_type", "")
            or ref_snapshot.get("target_ref_object_type", "")
            or ""
        ).strip().lower()
        target_ref_id = str(
            item.get("target_ref_object_id", "")
            or ref_snapshot.get("target_ref_object_id", "")
            or ""
        ).strip()

        ordered_ids: list[str] = []
        seen_ids: set[str] = set()

        def _push(raw_id: str) -> None:
            structure_id = str(raw_id or "").strip()
            if not structure_id or structure_id in seen_ids:
                return
            if structure_store is not None and not isinstance(structure_store.get(structure_id), dict):
                return
            seen_ids.add(structure_id)
            ordered_ids.append(structure_id)

        for raw_id in list(item.get("induction_source_support_structure_ids", []) or []):
            _push(raw_id)

        if ref_object_type == "st":
            _push(ref_object_id)
        _push(str(item.get("backing_structure_id", "") or ref_snapshot.get("backing_structure_id", "") or ""))
        for raw_id in list(ref_snapshot.get("structure_refs", []) or []):
            _push(raw_id)
        for raw_id in list(ref_snapshot.get("required_structure_ids", []) or []):
            _push(raw_id)
        for raw_id in list(ref_snapshot.get("bias_structure_ids", []) or []):
            _push(raw_id)
        for raw_id in list(item.get("ref_alias_ids", []) or []):
            _push(raw_id)
        return ordered_ids

    @staticmethod
    def _is_runtime_only_residual_item(item: dict) -> bool:
        if not isinstance(item, dict):
            return False
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        structure_ext = ref_snapshot.get("structure_ext", {}) if isinstance(ref_snapshot.get("structure_ext", {}), dict) else {}
        meta = item.get("meta", {}) if isinstance(item.get("meta", {}), dict) else {}
        meta_ext = meta.get("ext", {}) if isinstance(meta.get("ext", {}), dict) else {}
        item_ext = item.get("ext", {}) if isinstance(item.get("ext", {}), dict) else {}
        source = item.get("source", {}) if isinstance(item.get("source", {}), dict) else {}
        containers = (structure_ext, meta_ext, item_ext, source, item)
        if any(bool(container.get("runtime_only_residual", False)) for container in containers if isinstance(container, dict)):
            return True
        if any(container.get("hdb_backed", None) is False for container in containers if isinstance(container, dict)):
            return True
        if str(source.get("origin", "") or "") == "stimulus_runtime_residual_package":
            return True
        return False

    @staticmethod
    def _classify_induction_source_energy_kind(item: dict) -> str:
        er = max(0.0, float((item.get("energy", {}) or {}).get("er", item.get("er", 0.0)) or 0.0))
        ev = max(0.0, float((item.get("energy", {}) or {}).get("ev", item.get("ev", 0.0)) or 0.0))
        if er > 0.0 and ev > 0.0:
            return "er_ev"
        if er > 0.0:
            return "er"
        if ev > 0.0:
            return "ev"
        return "none"

    def _estimate_induction_local_target_hint_for_item(
        self,
        item: dict,
        *,
        cache: dict[str, int] | None = None,
    ) -> int:
        support_structure_ids = self._collect_induction_source_support_structure_ids(item)
        if not support_structure_ids:
            return 0
        return sum(
            int(self._estimate_induction_local_target_hint(structure_id, cache=cache) or 0)
            for structure_id in support_structure_ids
        )

    def _estimate_induction_local_target_hint(self, structure_id: str, *, cache: dict[str, int] | None = None) -> int:
        structure_key = str(structure_id or "").strip()
        if not structure_key:
            return 0
        if cache is not None and structure_key in cache:
            return int(cache.get(structure_key, 0) or 0)

        structure_store = getattr(getattr(self, "hdb", None), "_structure_store", None)
        episodic_store = getattr(getattr(self, "hdb", None), "_episodic_store", None)
        if structure_store is None:
            if cache is not None:
                cache[structure_key] = 0
            return 0

        structure_db = structure_store.get_db_by_owner(structure_key)
        if not isinstance(structure_db, dict):
            if cache is not None:
                cache[structure_key] = 0
            return 0

        filter_nonprojectable = bool(
            getattr(getattr(self, "hdb", None), "_config", {}).get("induction_filter_nonprojectable_targets", True)
        )
        unique_targets: set[tuple[str, str]] = set()
        for entry in list(structure_db.get("diff_table", []) or []):
            entry_type = str(entry.get("entry_type", "structure_ref") or "structure_ref")
            entry_ext = entry.get("ext", {}) if isinstance(entry.get("ext", {}), dict) else {}
            relation_type = str(entry_ext.get("relation_type", "") or "")
            target_id = str(entry.get("target_id", "") or "").strip()
            if entry_type == "raw_residual" and relation_type == "stimulus_raw_residual":
                for memory_id in list(entry.get("memory_refs", []) or []):
                    memory_key = str(memory_id or "").strip()
                    if not memory_key:
                        continue
                    if episodic_store is not None and episodic_store.get(memory_key) is None:
                        continue
                    unique_targets.add(("memory", memory_key))
                continue
            if target_id and structure_store.get(target_id):
                if filter_nonprojectable:
                    target_structure = structure_store.get(target_id)
                    if classify_runtime_projection_block_reason(target_structure):
                        continue
                unique_targets.add(("structure", target_id))

        hint_count = len(unique_targets)
        if cache is not None:
            cache[structure_key] = hint_count
        return hint_count

    def _apply_induction_local_target_bias(
        self,
        items: list[dict],
        *,
        bias_mode: str,
        cache: dict[str, int] | None = None,
    ) -> list[dict]:
        normalized_mode = str(bias_mode or "").strip().lower()
        if normalized_mode != "prefer_nonzero":
            return list(items or [])

        ranked = []
        for idx, item in enumerate(list(items or [])):
            hint_count = self._estimate_induction_local_target_hint_for_item(item, cache=cache)
            ranked.append((0 if hint_count > 0 else 1, -hint_count, idx, item))
        ranked.sort(key=lambda row: (row[0], row[1], row[2]))
        return [row[3] for row in ranked]

    def _build_induction_source_snapshot(self, *, trace_id: str, tick_id: str) -> dict:
        store = getattr(self.pool, "_store", None)
        snapshot_engine = getattr(self.pool, "_snapshot", None)
        mode = str(self._config.get("induction_source_selection_mode", "all_energetic_runtime") or "").strip().lower()
        if mode not in {"all_energetic_runtime", "legacy_cp_abs", "hybrid_er_ev", "er_root_priority"}:
            mode = "all_energetic_runtime"
        raw_max_items = int(self._config.get("induction_source_max_items", 0) or 0)
        max_items = max(0, raw_max_items) if mode == "all_energetic_runtime" else max(1, raw_max_items or 12)
        candidate_top_k = max(max_items, int(self._config.get("induction_source_candidate_top_k", 24) or 24))
        ev_quota_ratio = max(0.0, min(1.0, float(self._config.get("induction_source_ev_quota_ratio", 0.5) or 0.5)))
        local_target_bias_mode = str(self._config.get("induction_source_local_target_bias_mode", "prefer_nonzero") or "").strip().lower()
        if local_target_bias_mode not in {"off", "prefer_nonzero"}:
            local_target_bias_mode = "prefer_nonzero"
        # In the theory-aligned all-source mode (max_items=0), local-target
        # hints are only diagnostic: every effective source participates
        # regardless of their order. Avoid scanning every owner DB just to fill
        # hint columns on long runs.
        should_estimate_local_target_hints = bool(
            local_target_bias_mode == "prefer_nonzero"
            and (mode != "all_energetic_runtime" or max_items > 0)
        )
        local_target_hint_cache: dict[str, int] = {}
        runtime_only_residual_prefilter_skipped_count = 0
        memory_terminal_prefilter_skipped_count = 0
        fallback_sort_by = "er" if mode == "er_root_priority" else "cp_abs"
        if store is None or snapshot_engine is None:
            return self.pool.get_state_snapshot(
                trace_id=trace_id,
                tick_id=tick_id,
                top_k=(max_items if max_items > 0 else max(64, candidate_top_k)),
                sort_by=fallback_sort_by,
            )["data"]["snapshot"]

        def _sorted_st_items(sort_by: str) -> list[dict]:
            nonlocal runtime_only_residual_prefilter_skipped_count
            items = []
            for item in store.get_sorted(sort_by=sort_by, top_k=candidate_top_k):
                if str(item.get("ref_object_type", "") or "") != "st":
                    continue
                if self._is_runtime_only_residual_item(item):
                    runtime_only_residual_prefilter_skipped_count += 1
                    continue
                items.append(item)
            return self._apply_induction_local_target_bias(
                items,
                bias_mode=local_target_bias_mode if should_estimate_local_target_hints else "off",
                cache=local_target_hint_cache,
            )

        def _sorted_energetic_runtime_items(*, min_er: float = 0.0, min_ev: float = 0.0) -> list[dict]:
            nonlocal runtime_only_residual_prefilter_skipped_count, memory_terminal_prefilter_skipped_count
            energetic_items = []
            for item in list(store.get_all() if hasattr(store, "get_all") else []):
                if self._is_runtime_only_residual_item(item):
                    runtime_only_residual_prefilter_skipped_count += 1
                    continue
                if (
                    bool(self._config.get("induction_source_skip_memory_terminal_enabled", True))
                    and str(item.get("ref_object_type", "") or "").strip().lower() == "em"
                ):
                    memory_terminal_prefilter_skipped_count += 1
                    continue
                energy = item.get("energy", {}) if isinstance(item.get("energy", {}), dict) else {}
                er_value = max(0.0, float(energy.get("er", item.get("er", 0.0)) or 0.0))
                ev_value = max(0.0, float(energy.get("ev", item.get("ev", 0.0)) or 0.0))
                if er_value <= 0.0 and ev_value <= 0.0:
                    continue
                if (min_er > 0.0 or min_ev > 0.0) and not (er_value >= min_er or ev_value >= min_ev):
                    continue
                energetic_items.append(item)
            energetic_items.sort(
                key=lambda row: (
                    -(max(0.0, float((row.get("energy", {}) or {}).get("er", 0.0) or 0.0)) + max(0.0, float((row.get("energy", {}) or {}).get("ev", 0.0) or 0.0))),
                    -max(0.0, float((row.get("energy", {}) or {}).get("er", 0.0) or 0.0)),
                    -max(0.0, float((row.get("energy", {}) or {}).get("ev", 0.0) or 0.0)),
                    -float(row.get("updated_at", 0) or 0),
                )
            )
            return self._apply_induction_local_target_bias(
                energetic_items,
                bias_mode=local_target_bias_mode if should_estimate_local_target_hints else "off",
                cache=local_target_hint_cache,
            )

        def _positive_energy_items(items: list[dict], *, energy_key: str) -> list[dict]:
            filtered = []
            for item in items:
                energy = max(0.0, float((item.get("energy", {}) or {}).get(energy_key, 0.0) or 0.0))
                if energy > 0.0:
                    filtered.append(item)
            return filtered

        selected_items: list[dict] = []
        selected_channels: dict[str, str] = {}
        seen_ids: set[str] = set()
        channel_counts = {"ev": 0, "er": 0, "cp_abs": 0}
        available_candidate_items: dict[str, dict] = {}

        def _remember_available(items: list[dict]) -> None:
            for item in items:
                item_id = str(item.get("id", "") or "")
                if item_id:
                    available_candidate_items[item_id] = item

        def _append_items(items: list[dict], *, channel: str, limit: int | None = None) -> None:
            remaining = None if limit is None else max(0, int(limit))
            for item in items:
                if remaining is not None and remaining <= 0:
                    break
                item_id = str(item.get("id", "") or "")
                if not item_id or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                selected_items.append(item)
                selected_channels[item_id] = channel
                channel_counts[channel] = int(channel_counts.get(channel, 0) or 0) + 1
                if remaining is not None:
                    remaining -= 1
                if len(selected_items) >= max_items:
                    break

        cp_candidates = [] if mode == "all_energetic_runtime" else _sorted_st_items("cp_abs")
        ev_quota_count = 0
        if mode == "all_energetic_runtime":
            try:
                ev_threshold = float(getattr(self.hdb, "_config", {}).get("ev_propagation_threshold", 0.12) or 0.12)
            except Exception:
                ev_threshold = 0.12
            try:
                er_threshold = float(getattr(self.hdb, "_config", {}).get("er_induction_threshold", 0.15) or 0.15)
            except Exception:
                er_threshold = 0.15
            ev_threshold = max(0.0, float(ev_threshold))
            er_threshold = max(0.0, float(er_threshold))

            energetic_candidates = _sorted_energetic_runtime_items(min_er=er_threshold, min_ev=ev_threshold)
            _remember_available(energetic_candidates)
            for item in energetic_candidates:
                item_id = str(item.get("id", "") or "")
                energy_kind = self._classify_induction_source_energy_kind(item)
                if item_id and energy_kind != "none":
                    selected_channels[item_id] = energy_kind
            selected_items = energetic_candidates[:max_items] if max_items > 0 else energetic_candidates
        elif mode == "legacy_cp_abs":
            _remember_available(cp_candidates)
            _append_items(cp_candidates, channel="cp_abs", limit=max_items)
        elif mode == "er_root_priority":
            er_candidates = _positive_energy_items(_sorted_st_items("er"), energy_key="er")
            _remember_available(er_candidates)
            _append_items(er_candidates, channel="er", limit=max_items)
        else:
            ev_candidates = _sorted_st_items("ev")
            er_candidates = _sorted_st_items("er")
            _remember_available(cp_candidates)
            _remember_available(ev_candidates)
            _remember_available(er_candidates)
            if ev_quota_ratio > 0.0:
                ev_quota_count = int(round(float(max_items) * ev_quota_ratio))
                if ev_quota_count <= 0:
                    ev_quota_count = 1
            ev_quota_count = min(max_items, ev_quota_count)
            _append_items(ev_candidates, channel="ev", limit=ev_quota_count)
            if len(selected_items) < max_items:
                _append_items(er_candidates, channel="er", limit=max_items - len(selected_items))
            if len(selected_items) < max_items:
                _append_items(ev_candidates, channel="ev", limit=max_items - len(selected_items))
            if len(selected_items) < max_items:
                _append_items(cp_candidates, channel="cp_abs", limit=max_items - len(selected_items))

        top_items = []
        selected_with_local_target_hint_count = 0
        selected_runtime_count = 0
        selected_st_count = 0
        selected_er_count = 0
        selected_ev_count = 0
        selected_er_ev_count = 0
        selected_iter = selected_items[:max_items] if max_items > 0 else selected_items
        selected_support_ids_by_item: dict[str, list[str]] = {}
        selected_hint_by_item: dict[str, int] = {}
        for item in selected_iter:
            summary = self._build_runtime_pool_item_summary_fast(item, include_sequence_payload=True)
            item_id = str(item.get("id", "") or "")
            # Support ids are cheap identity routing data and must remain
            # available even when local-target hint diagnostics are skipped.
            # The expensive part is opening owner DBs to count targets, which
            # stays guarded by should_estimate_local_target_hints below.
            support_structure_ids = self._collect_induction_source_support_structure_ids(item)
            local_target_hint_count = 0
            if should_estimate_local_target_hints:
                local_target_hint_count = sum(
                    int(self._estimate_induction_local_target_hint(structure_id, cache=local_target_hint_cache) or 0)
                    for structure_id in support_structure_ids
                )
            if item_id:
                selected_support_ids_by_item[item_id] = list(support_structure_ids)
                selected_hint_by_item[item_id] = int(local_target_hint_count)
            energy_kind = selected_channels.get(item_id, self._classify_induction_source_energy_kind(item))
            summary["induction_source_channel"] = energy_kind
            summary["induction_source_local_target_hint_count"] = local_target_hint_count
            summary["induction_source_support_structure_ids"] = list(support_structure_ids)
            summary["induction_source_energy_kind"] = energy_kind
            if local_target_hint_count > 0:
                selected_with_local_target_hint_count += 1
            selected_runtime_count += 1
            if str(summary.get("ref_object_type", "") or "") == "st":
                selected_st_count += 1
            if energy_kind in {"er", "er_ev"}:
                selected_er_count += 1
            if energy_kind in {"ev", "er_ev"}:
                selected_ev_count += 1
            if energy_kind == "er_ev":
                selected_er_ev_count += 1
            top_items.append(summary)

        available_with_local_target_hint_count = 0
        available_st_count = 0
        if should_estimate_local_target_hints:
            for item in list(available_candidate_items.values()):
                item_id = str(item.get("id", "") or "")
                if str(item.get("ref_object_type", "") or "").strip() == "st":
                    available_st_count += 1
                if item_id in selected_hint_by_item:
                    hint_count = int(selected_hint_by_item.get(item_id, 0) or 0)
                else:
                    support_structure_ids = selected_support_ids_by_item.get(item_id)
                    if support_structure_ids is None:
                        support_structure_ids = self._collect_induction_source_support_structure_ids(item)
                    hint_count = sum(
                        int(self._estimate_induction_local_target_hint(structure_id, cache=local_target_hint_cache) or 0)
                        for structure_id in support_structure_ids
                    )
                if hint_count > 0:
                    available_with_local_target_hint_count += 1
        else:
            available_st_count = sum(
                1
                for item in list(available_candidate_items.values())
                if str(item.get("ref_object_type", "") or "").strip() == "st"
            )

        return {
            "snapshot_id": f"induction::{tick_id or trace_id}",
            "object_type": "runtime_snapshot",
            "sub_type": "induction_source_snapshot",
            "trace_id": trace_id,
            "tick_id": tick_id,
            "summary": {
                "active_item_count": int(getattr(store, "size", 0) or 0),
                "induction_source_selection_mode": mode,
                "induction_source_available_st_count": int(available_st_count),
                "induction_source_available_runtime_count": int(len(available_candidate_items)),
                "induction_source_runtime_only_residual_prefilter_skipped_count": int(runtime_only_residual_prefilter_skipped_count),
                "induction_source_memory_terminal_prefilter_skipped_count": int(memory_terminal_prefilter_skipped_count),
                "induction_source_selected_count": len(top_items),
                "induction_source_selected_runtime_count": int(selected_runtime_count),
                "induction_source_selected_st_count": int(selected_st_count),
                "induction_source_selected_non_st_count": max(0, int(selected_runtime_count - selected_st_count)),
                "induction_source_selected_from_ev_count": int(selected_ev_count if mode == "all_energetic_runtime" else (channel_counts.get("ev", 0) or 0)),
                "induction_source_selected_from_er_count": int(selected_er_count if mode == "all_energetic_runtime" else (channel_counts.get("er", 0) or 0)),
                "induction_source_selected_from_er_ev_count": int(selected_er_ev_count),
                "induction_source_selected_from_cp_abs_count": int(channel_counts.get("cp_abs", 0) or 0),
                "induction_source_max_items": max_items,
                "induction_source_candidate_top_k": candidate_top_k,
                "induction_source_ev_quota_ratio": round(ev_quota_ratio, 8),
                "induction_source_ev_quota_count": ev_quota_count,
                "induction_source_local_target_bias_mode": local_target_bias_mode,
                "induction_source_local_target_hint_diagnostics_skipped": int(not should_estimate_local_target_hints),
                "induction_source_available_with_local_target_hint_count": available_with_local_target_hint_count,
                "induction_source_selected_with_local_target_hint_count": selected_with_local_target_hint_count,
                "induction_source_selected_zero_local_target_hint_count": max(0, len(top_items) - selected_with_local_target_hint_count),
                "induction_source_selection_cap_hit": int(max_items > 0 and len(top_items) >= max_items and len(available_candidate_items) > len(top_items)),
            },
            "top_items": top_items,
        }

    def _apply_induction_targets(self, targets: list[dict], trace_id: str, tick_id: str) -> list[dict]:
        pause_gc = bool(self._config.get("induction_target_gc_pause_enabled", True))
        gc_was_enabled = False
        if pause_gc:
            try:
                gc_was_enabled = bool(gc.isenabled())
                if gc_was_enabled:
                    gc.disable()
            except Exception:
                gc_was_enabled = False
        try:
            return self._apply_induction_targets_impl(targets, trace_id, tick_id)
        finally:
            if pause_gc and gc_was_enabled:
                try:
                    gc.enable()
                except Exception:
                    pass

    def _apply_induction_targets_impl(self, targets: list[dict], trace_id: str, tick_id: str) -> list[dict]:
        projections = []
        pending_packets: list[dict] = []
        pending_runtime_structures: list[dict] = []
        runtime_st_enabled = bool(self._config.get("induction_projection_runtime_st_enabled", True))
        for target in targets:
            item = {
                "projection_kind": target.get("projection_kind", "structure"),
                "memory_id": target.get("memory_id", ""),
                "structure_id": target.get("target_structure_id", ""),
                "backing_structure_id": target.get("backing_structure_id", target.get("target_structure_id", "")),
                "display_text": target.get("target_display_text", ""),
                "er": float(target.get("delta_er", 0.0)),
                "ev": float(target.get("delta_ev", 0.0)),
                "reason": "induction_target",
            }
            if isinstance(target.get("growth_projection", {}), dict):
                item["growth_projection"] = copy.deepcopy(target.get("growth_projection", {}))
            if isinstance(target.get("component_energy", {}), dict):
                item["component_energy"] = copy.deepcopy(target.get("component_energy", {}))
            effective = self._apply_projection_fatigue_to_item(item)
            if effective is None:
                continue
            projection_kind = str(effective.get("projection_kind", target.get("projection_kind", "structure")) or "structure")
            if runtime_st_enabled and projection_kind != "memory":
                pending_runtime_structures.append(
                    {
                        "projection_kind": projection_kind,
                        "memory_id": target.get("memory_id", ""),
                        "structure_id": target.get("target_structure_id", effective.get("structure_id", "")),
                        "backing_structure_id": target.get("backing_structure_id", target.get("target_structure_id", effective.get("structure_id", ""))),
                        "display_text": effective.get("display_text", target.get("target_display_text", "")),
                        "er": round(float(effective.get("er", 0.0) or 0.0), 8),
                        "ev": round(float(effective.get("ev", 0.0) or 0.0), 8),
                        "reason": "induction_target",
                        "projection_fatigue": round(float(effective.get("projection_fatigue", 0.0) or 0.0), 8),
                        "growth_projection": copy.deepcopy(effective.get("growth_projection", {}))
                        if isinstance(effective.get("growth_projection", {}), dict)
                        else {},
                        "component_energy": copy.deepcopy(effective.get("component_energy", {}))
                        if isinstance(effective.get("component_energy", {}), dict)
                        else {},
                    }
                )
                continue
            packet_result = self._build_induction_target_stimulus_packet(
                target={
                    **dict(target),
                    "delta_er": float(effective.get("er", 0.0) or 0.0),
                    "delta_ev": float(effective.get("ev", 0.0) or 0.0),
                    "display_text": effective.get("display_text", target.get("target_display_text", "")),
                },
                trace_id=trace_id,
                tick_id=tick_id,
            )
            packet = packet_result.get("packet")
            if not isinstance(packet, dict):
                projections.append(
                    {
                        "projection_kind": effective.get("projection_kind", target.get("projection_kind", "structure")),
                        "memory_id": target.get("memory_id", ""),
                        "structure_id": target.get("target_structure_id", ""),
                        "backing_structure_id": target.get("backing_structure_id", target.get("target_structure_id", "")),
                        "display_text": effective.get("display_text", target.get("target_display_text", "")),
                        "er": round(float(effective.get("er", 0.0) or 0.0), 8),
                        "ev": round(float(effective.get("ev", 0.0) or 0.0), 8),
                        "reason": "induction_target",
                        "result": "induction_packet_build_skipped",
                    }
                )
                continue
            pending_packets.append(
                {
                    "projection_kind": effective.get("projection_kind", target.get("projection_kind", "structure")),
                    "memory_id": target.get("memory_id", ""),
                    "structure_id": target.get("target_structure_id", ""),
                    "backing_structure_id": target.get("backing_structure_id", target.get("target_structure_id", "")),
                    "display_text": effective.get("display_text", target.get("target_display_text", "")),
                    "er": round(float(effective.get("er", 0.0) or 0.0), 8),
                    "ev": round(float(effective.get("ev", 0.0) or 0.0), 8),
                    "reason": "induction_target",
                    "packet_id": str(packet.get("id", "") or ""),
                    "target_sa_count": len(list(packet.get("sa_items", []) or [])),
                    "target_csa_count": len(list(packet.get("csa_items", []) or [])),
                    "landed_total_er": round(float((packet.get("energy_summary", {}) or {}).get("total_er", effective.get("er", 0.0)) or 0.0), 8),
                    "landed_total_ev": round(float((packet.get("energy_summary", {}) or {}).get("total_ev", effective.get("ev", 0.0)) or 0.0), 8),
                    "pool_apply_event_count": 0,
                    "result": "induction_packet_applied",
                    "_packet": packet,
                }
            )

        if pending_runtime_structures:
            enable_runtime_insert_log = bool(
                self._config.get("induction_target_runtime_insert_log_enabled", False)
            )
            fast_runtime_ref_merge = bool(
                self._config.get("induction_target_runtime_ref_fast_merge_enabled", True)
            )
            runtime_rows = self._project_runtime_structures(
                pending_runtime_structures,
                trace_id=f"{trace_id}_induction_target_st",
                tick_id=tick_id,
                enable_insert_log=enable_runtime_insert_log,
                fast_ref_hit_energy_merge=fast_runtime_ref_merge,
            )
            projections.extend(runtime_rows)

        if pending_packets:
            use_batch_apply = bool(
                self._config.get("induction_target_batch_pool_apply_enabled", False)
            ) and not bool(self.pool._config.get("aggregate_same_semantic_incoming_objects", False))
            if use_batch_apply and len(pending_packets) > 1:
                batch_packet = self._combine_induction_target_packets(
                    [dict(item.get("_packet", {}) or {}) for item in pending_packets],
                    trace_id=trace_id,
                    tick_id=tick_id,
                )
                if isinstance(batch_packet, dict) and (batch_packet.get("sa_items") or batch_packet.get("csa_items")):
                    apply_data, _, _ = self._apply_packet_to_pool(
                        batch_packet,
                        f"{trace_id}_induction_target_batch",
                        tick_id,
                        disable_priority_neutralization=True,
                        source_module="hdb_induction",
                        collect_history_events=False,
                        enable_script_broadcast=False,
                        enable_brief_log=False,
                        compute_post_apply_summary=False,
                        clone_packet_for_safety=False,
                        enable_change_event_log=False,
                    )
                    event_count = int(len(list(apply_data.get("events", []) or [])))
                    for row in pending_packets:
                        row["pool_apply_event_count"] = event_count
            else:
                for row in pending_packets:
                    packet = dict(row.get("_packet", {}) or {})
                    if not packet:
                        continue
                    apply_data, _, landed_packet = self._apply_packet_to_pool(
                        packet,
                        f"{trace_id}_induction_target",
                        tick_id,
                        disable_priority_neutralization=True,
                        source_module="hdb_induction",
                        collect_history_events=False,
                        enable_script_broadcast=False,
                        enable_brief_log=False,
                        compute_post_apply_summary=False,
                        clone_packet_for_safety=False,
                        enable_change_event_log=False,
                    )
                    landed_energy = dict(landed_packet.get("energy_summary", {}) or {})
                    row["landed_total_er"] = round(float(landed_energy.get("total_er", row.get("er", 0.0)) or 0.0), 8)
                    row["landed_total_ev"] = round(float(landed_energy.get("total_ev", row.get("ev", 0.0)) or 0.0), 8)
                    row["pool_apply_event_count"] = int(len(list(apply_data.get("events", []) or [])))
            for row in pending_packets:
                row.pop("_packet", None)
                projections.append(row)
        return projections

    def _combine_induction_target_packets(self, packets: list[dict], *, trace_id: str, tick_id: str) -> dict:
        valid_packets = [packet for packet in packets if isinstance(packet, dict)]
        if not valid_packets:
            return {}
        now_ms = int(time.time() * 1000)
        batch_id = next_id("indbatch")
        sa_items: list[dict] = []
        csa_items: list[dict] = []
        grouped_sequences: list[dict] = []
        echo_frames: list[dict] = []
        for packet in valid_packets:
            sa_items.extend([item for item in (packet.get("sa_items", []) or []) if isinstance(item, dict)])
            csa_items.extend([item for item in (packet.get("csa_items", []) or []) if isinstance(item, dict)])
            echo_frames.extend([item for item in (packet.get("echo_frames", []) or []) if isinstance(item, dict)])
            for group in list(packet.get("grouped_sa_sequences", []) or []):
                if not isinstance(group, dict):
                    continue
                merged_group = dict(group)
                merged_group["group_index"] = len(grouped_sequences)
                grouped_sequences.append(merged_group)
        if bool(self._config.get("induction_projection_batch_dedupe_sa_enabled", True)):
            sa_items = self._dedupe_projection_sa_items_by_id(sa_items)
        total_er = round(sum(float((item.get("energy", {}) or {}).get("er", 0.0) or 0.0) for item in sa_items), 6)
        total_ev = round(sum(float((item.get("energy", {}) or {}).get("ev", 0.0) or 0.0) for item in sa_items), 6)
        return {
            "id": batch_id,
            "object_type": "stimulus_packet",
            "sub_type": "induction_projection_batch_packet",
            "schema_version": "1.1",
            "packet_type": "induction_batch",
            "current_frame_id": batch_id,
            "echo_frame_ids": [],
            "sa_items": sa_items,
            "csa_items": csa_items,
            "echo_frames": echo_frames,
            "grouped_sa_sequences": grouped_sequences,
            "energy_summary": {
                "total_er": total_er,
                "total_ev": total_ev,
                "current_total_er": total_er,
                "current_total_ev": total_ev,
                "echo_total_er": 0.0,
                "echo_total_ev": 0.0,
                "combined_context_er": total_er,
                "combined_context_ev": total_ev,
                "ownership_level": "sa",
                "echo_merged_into_objects": False,
            },
            "trace_id": trace_id,
            "tick_id": tick_id or trace_id,
            "created_at": now_ms,
            "updated_at": now_ms,
            "source": {
                "module": "observatory",
                "interface": "induction_target_batch_packet",
                "origin": "induction_target_batch",
                "origin_id": batch_id,
                "parent_ids": [str(packet.get("id", "")) for packet in valid_packets if str(packet.get("id", ""))],
            },
            "status": "active",
            "ext": {
                "projection_kind": "induction_batch",
                "batch_packet_ids": [str(packet.get("id", "")) for packet in valid_packets if str(packet.get("id", ""))],
            },
            "meta": {"confidence": 0.7, "field_registry_version": "1.1", "debug": {}, "ext": {}},
        }

    @staticmethod
    def _dedupe_projection_sa_items_by_id(sa_items: list[dict]) -> list[dict]:
        merged_by_id: dict[str, dict] = {}
        order: list[str] = []
        for item in sa_items:
            if not isinstance(item, dict):
                continue
            sa_id = str(item.get("id", "") or "")
            if not sa_id:
                continue
            existing = merged_by_id.get(sa_id)
            if existing is None:
                merged = dict(item)
                merged["energy"] = dict(item.get("energy", {}) or {})
                if isinstance(item.get("source", {}), dict):
                    merged["source"] = dict(item.get("source", {}) or {})
                    if isinstance(merged["source"].get("parent_ids"), list):
                        merged["source"]["parent_ids"] = list(merged["source"].get("parent_ids") or [])
                if isinstance(item.get("ext", {}), dict):
                    merged["ext"] = dict(item.get("ext", {}) or {})
                    merged["ext"]["batch_duplicate_count"] = 1
                merged_by_id[sa_id] = merged
                order.append(sa_id)
                continue
            energy = existing.setdefault("energy", {})
            incoming_energy = item.get("energy", {}) if isinstance(item.get("energy", {}), dict) else {}
            energy["er"] = round(float(energy.get("er", 0.0) or 0.0) + float(incoming_energy.get("er", 0.0) or 0.0), 8)
            energy["ev"] = round(float(energy.get("ev", 0.0) or 0.0) + float(incoming_energy.get("ev", 0.0) or 0.0), 8)
            ext = existing.setdefault("ext", {})
            if isinstance(ext, dict):
                ext["batch_duplicate_count"] = int(ext.get("batch_duplicate_count", 1) or 1) + 1
            source = existing.setdefault("source", {})
            incoming_source = item.get("source", {}) if isinstance(item.get("source", {}), dict) else {}
            if isinstance(source, dict):
                parent_ids = list(source.get("parent_ids", []) or [])
                for parent_id in incoming_source.get("parent_ids", []) or []:
                    text = str(parent_id or "")
                    if text and text not in parent_ids:
                        parent_ids.append(text)
                source["parent_ids"] = parent_ids
        return [merged_by_id[sa_id] for sa_id in order if sa_id in merged_by_id]

    def _apply_induction_source_consumptions(self, consumptions: list[dict], trace_id: str, tick_id: str) -> list[dict]:
        results = []
        for item in consumptions:
            structure_id = str(item.get("source_structure_id", ""))
            source_item_id = str(item.get("source_item_id", "") or "")
            consumed_ev = max(0.0, float(item.get("consumed_ev", 0.0)))
            if (not source_item_id and not structure_id) or consumed_ev <= 0.0:
                continue
            state_item = self.pool._store.get(source_item_id) if source_item_id else None
            if not state_item and structure_id:
                state_item = self.pool._store.get_by_ref(structure_id)
            if not state_item:
                continue
            available_ev = max(0.0, float(state_item.get("energy", {}).get("ev", 0.0)))
            delta_ev = -min(consumed_ev, available_ev)
            if delta_ev >= 0.0:
                continue
            result = self.pool.apply_energy_update(
                target_item_id=state_item.get("id", ""),
                delta_er=0.0,
                delta_ev=delta_ev,
                trace_id=f"{trace_id}_induction_source",
                tick_id=tick_id,
                reason="induction_source_ev_consumed",
            )
            results.append(
                {
                    "source_structure_id": structure_id,
                    "source_item_id": source_item_id,
                    "target_item_id": state_item.get("id", ""),
                    "delta_ev": round(delta_ev, 8),
                    "result": result.get("message", ""),
                }
            )
        return results

    @staticmethod
    def _collect_post_induction_cs_privileged_refs(
        *,
        induction_snapshot: dict,
        applied_targets: list[dict],
        induction_targets: list[dict],
    ) -> list[str]:
        """Collect refs that should bypass CS seed energy gates after induction.

        These refs are not forced to stitch; they are only kept visible to the
        post-induction CS pass so freshly landed residual targets and their
        just-used sources can compete through the normal context-concat score.
        """
        refs: list[str] = []
        seen: set[str] = set()

        def _push(raw: Any) -> None:
            ref = str(raw or "").strip()
            if not ref or ref in seen:
                return
            seen.add(ref)
            refs.append(ref)

        snapshot_items = list((induction_snapshot or {}).get("top_items", []) or [])
        for row in snapshot_items:
            if not isinstance(row, dict):
                continue
            _push(row.get("ref_object_id", ""))
            _push(row.get("backing_structure_id", ""))
            for support_id in list(row.get("induction_source_support_structure_ids", []) or []):
                _push(support_id)
            ref_snapshot = row.get("ref_snapshot", {}) if isinstance(row.get("ref_snapshot", {}), dict) else {}
            _push(ref_snapshot.get("backing_structure_id", ""))
            for support_id in list(ref_snapshot.get("induction_source_support_structure_ids", []) or []):
                _push(support_id)

        for row in list(induction_targets or []):
            if not isinstance(row, dict):
                continue
            _push(row.get("target_structure_id", ""))
            _push(row.get("backing_structure_id", ""))
            for source_id in list(row.get("sources", []) or []):
                _push(source_id)

        for row in list(applied_targets or []):
            if not isinstance(row, dict):
                continue
            _push(row.get("structure_id", ""))
            _push(row.get("backing_structure_id", ""))
            _push(row.get("target_item_ref_object_id", ""))
            _push(row.get("target_ref_object_id", ""))
            _push(row.get("merged_ref_object_id", ""))
            _push(row.get("ref_object_id", ""))
        return refs

    def _collect_history_events(self, before_count: int, since_ms: int) -> list[dict]:
        recent_count = max(0, self.pool._history.size - before_count)
        events = self.pool._history.get_recent(recent_count)
        enriched = []
        for event in events:
            if event.get("timestamp_ms", 0) < since_ms:
                continue
            enriched.append(self._enrich_history_event(event))
        return enriched

    def _describe_stimulus_packet(self, packet: dict, *, mode: str = "preview") -> dict:
        if str(mode or "preview").strip().lower() == "full":
            return self._describe_stimulus_packet_full(packet)
        return self._describe_stimulus_packet_preview(packet)

    def _describe_stimulus_packet_full(self, packet: dict) -> dict:
        profile = self.cut_engine.build_sequence_profile_from_stimulus_packet(packet)
        unit_rows = self._describe_packet_units(packet, profile=profile)
        groups = self._describe_packet_groups(packet, profile=profile)
        flat_tokens = [str(unit.get("display", "")) for unit in unit_rows if str(unit.get("display", ""))]
        total_er = round(sum(float(unit.get("er", 0.0)) for unit in unit_rows), 8)
        total_ev = round(sum(float(unit.get("ev", 0.0)) for unit in unit_rows), 8)
        semantic_display_text = format_semantic_sequence_groups(list(profile.get("sequence_groups", [])), context="stimulus")
        return {
            "packet_id": packet.get("id", ""),
            "display_text": " / ".join(group.get("display_text", "") for group in groups if group.get("display_text", "")),
            "grouped_display_text": " / ".join(group.get("display_text", "") for group in groups if group.get("display_text", "")),
            "semantic_display_text": semantic_display_text,
            "semantic_grouped_display_text": semantic_display_text,
            "visible_text": profile.get("display_text", ""),
            "flat_tokens": flat_tokens,
            "sequence_groups": [
                {
                    **dict(group),
                    "units": [dict(unit) for unit in group.get("units", []) if isinstance(unit, dict)],
                    "csa_bundles": [dict(bundle) for bundle in group.get("csa_bundles", []) if isinstance(bundle, dict)],
                }
                for group in profile.get("sequence_groups", [])
                if isinstance(group, dict)
            ],
            "groups": groups,
            "units": unit_rows,
            "feature_units": unit_rows,
            "sa_count": len(unit_rows),
            "csa_count": sum(len(group.get("csa_bundles", []) or []) for group in groups if isinstance(group, dict)),
            "unit_count": len(unit_rows),
            "total_er": total_er,
            "total_ev": total_ev,
        }

    def _describe_stimulus_packet_preview(self, packet: dict) -> dict:
        packet = packet if isinstance(packet, dict) else {}
        group_limit = max(1, int(self._config.get("stimulus_packet_preview_group_limit", 10) or 10))
        unit_limit = max(1, int(self._config.get("stimulus_packet_preview_unit_limit", 24) or 24))
        flat_token_limit = max(unit_limit, int(self._config.get("stimulus_packet_preview_flat_token_limit", 96) or 96))
        bundle_limit = max(1, int(self._config.get("stimulus_packet_preview_bundle_limit", 24) or 24))

        sa_items = [item for item in (packet.get("sa_items", []) or []) if isinstance(item, dict)]
        csa_items = [item for item in (packet.get("csa_items", []) or []) if isinstance(item, dict)]
        grouped_raw = [group for group in (packet.get("grouped_sa_sequences", []) or []) if isinstance(group, dict)]
        sa_index = {str(item.get("id", "")): item for item in sa_items if str(item.get("id", ""))}
        csa_index = {str(item.get("id", "")): item for item in csa_items if str(item.get("id", ""))}
        assigned_sa_ids = {
            str(sa_id)
            for group in grouped_raw
            for sa_id in (group.get("sa_ids", []) or [])
            if str(sa_id)
        }

        sa_ids_by_ctx: dict[tuple[str, str, int], list[str]] = {}
        for item_id, item in sa_index.items():
            ctx = self._packet_item_context(item)
            ctx_key = self._packet_ctx_key(ctx.get("source_type", ""), ctx.get("origin_frame_id", ""), int(ctx.get("source_group_index", -1)))
            if not any((ctx_key[0], ctx_key[1], ctx_key[2] >= 0)):
                continue
            sa_ids_by_ctx.setdefault(ctx_key, []).append(item_id)
        for item_ids in sa_ids_by_ctx.values():
            item_ids.sort(key=lambda item_id: self._packet_item_sequence_index(sa_index.get(item_id, {})))

        group_specs: list[dict[str, Any]] = []
        seen_ctx_keys: set[tuple[str, str, int]] = set()
        for order_index, raw_group in enumerate(grouped_raw):
            source_type = str(raw_group.get("source_type", "current") or "current")
            origin_frame_id = str(raw_group.get("origin_frame_id", "") or "")
            try:
                source_group_index = int(raw_group.get("source_group_index", raw_group.get("group_index", order_index)) or order_index)
            except Exception:
                source_group_index = order_index
            ctx_key = self._packet_ctx_key(source_type, origin_frame_id, source_group_index)
            seen_ctx_keys.add(ctx_key)
            group_specs.append(
                {
                    "order_index": order_index,
                    "group_index": int(raw_group.get("group_index", order_index) or order_index),
                    "source_type": source_type,
                    "origin_frame_id": origin_frame_id,
                    "source_group_index": source_group_index,
                    "order_sensitive": bool(raw_group.get("order_sensitive", False)),
                    "string_unit_kind": str(raw_group.get("string_unit_kind", "") or ""),
                    "string_token_text": str(raw_group.get("string_token_text", "") or ""),
                    "sa_ids": self._dedupe_preserve_order(list(raw_group.get("sa_ids", []) or []) + list(sa_ids_by_ctx.get(ctx_key, []) or [])),
                    "csa_ids": [str(csa_id) for csa_id in (raw_group.get("csa_ids", []) or []) if str(csa_id)],
                    "ext": dict(raw_group.get("ext", {}) or {}) if isinstance(raw_group.get("ext", {}), dict) else {},
                }
            )

        next_order_index = len(group_specs)
        for ctx_key, item_ids in sa_ids_by_ctx.items():
            remaining_item_ids = [item_id for item_id in item_ids if str(item_id) not in assigned_sa_ids]
            if not remaining_item_ids:
                continue
            if ctx_key in seen_ctx_keys:
                continue
            source_type, origin_frame_id, source_group_index = ctx_key
            group_specs.append(
                {
                    "order_index": next_order_index,
                    "group_index": source_group_index if source_group_index >= 0 else next_order_index,
                    "source_type": source_type or "current",
                    "origin_frame_id": origin_frame_id,
                    "source_group_index": source_group_index,
                    "order_sensitive": False,
                    "string_unit_kind": "",
                    "string_token_text": "",
                    "sa_ids": list(remaining_item_ids),
                    "csa_ids": [],
                    "ext": {},
                }
            )
            next_order_index += 1

        preview_units: list[dict[str, Any]] = []
        preview_groups: list[dict[str, Any]] = []
        preview_sequence_groups: list[dict[str, Any]] = []
        flat_tokens_preview: list[str] = []
        flat_token_count = 0

        total_er = round(sum(float((item.get("energy", {}) or {}).get("er", 0.0) or 0.0) for item in sa_items), 8)
        total_ev = round(sum(float((item.get("energy", {}) or {}).get("ev", 0.0) or 0.0) for item in sa_items), 8)

        for spec in group_specs:
            unit_items = [sa_index.get(item_id, {}) for item_id in spec.get("sa_ids", []) if sa_index.get(item_id, {})]
            unit_items = sorted(unit_items, key=self._packet_item_sequence_index)
            bundle_displays, bundle_defs, bundle_by_unit = self._build_packet_bundle_preview(
                csa_ids=[str(csa_id) for csa_id in spec.get("csa_ids", []) if str(csa_id)],
                csa_index=csa_index,
                sa_index=sa_index,
                bundle_limit=bundle_limit,
            )
            unit_rows_full = [
                self._build_packet_unit_preview(
                    item,
                    group_index=int(spec.get("group_index", 0) or 0),
                    source_type=str(spec.get("source_type", "current") or "current"),
                    bundle_display=bundle_by_unit.get(str(item.get("id", "")), ""),
                )
                for item in unit_items
            ]
            tokens_all = [str(row.get("display", "")) for row in unit_rows_full if str(row.get("display", ""))]
            visible_tokens = [str(row.get("display", "")) for row in unit_rows_full if str(row.get("display", "")) and bool(row.get("display_visible", False))]
            if not visible_tokens:
                visible_tokens = list(tokens_all)
            flat_token_count += len(tokens_all)
            if len(flat_tokens_preview) < flat_token_limit:
                remaining = max(0, flat_token_limit - len(flat_tokens_preview))
                flat_tokens_preview.extend(tokens_all[:remaining])

            raw_ext = dict(spec.get("ext", {}) or {}) if isinstance(spec.get("ext", {}), dict) else {}
            internal_strings = [
                str(group.get("string_token_text", "") or "")
                for group in (raw_ext.get("internal_string_groups", []) or [])
                if isinstance(group, dict) and str(group.get("string_token_text", "") or "")
            ]
            display_text = self._compose_packet_group_display(
                base_text=str(spec.get("string_token_text", "") or ""),
                tokens=visible_tokens,
                order_sensitive=bool(spec.get("order_sensitive", False)),
                internal_texts=internal_strings,
            )
            total_group_er = round(sum(float(row.get("er", 0.0) or 0.0) for row in unit_rows_full), 8)
            total_group_ev = round(sum(float(row.get("ev", 0.0) or 0.0) for row in unit_rows_full), 8)
            unit_preview = unit_rows_full[: max(0, unit_limit - len(preview_units))]
            if len(preview_units) < unit_limit:
                preview_units.extend(unit_preview)
            if len(preview_groups) < group_limit:
                group_preview = {
                    "group_index": int(spec.get("group_index", 0) or 0),
                    "source_type": str(spec.get("source_type", "current") or "current"),
                    "origin_frame_id": str(spec.get("origin_frame_id", "") or ""),
                    "contains_internal_group": bool(raw_ext.get("contains_internal_group", False)),
                    "internal_merge_mode": str(raw_ext.get("internal_merge_mode", "") or ""),
                    "internal_string_group_count": len((raw_ext.get("internal_string_groups", []) or [])),
                    "internal_string_texts": internal_strings,
                    "display_text": display_text,
                    "semantic_display_text": display_text,
                    "token_text": " / ".join(tokens_all),
                    "visible_text": "".join(visible_tokens),
                    "tokens": tokens_all,
                    "visible_tokens": visible_tokens,
                    "sa_count": len(unit_rows_full),
                    "csa_count": len([csa_id for csa_id in spec.get("csa_ids", []) if str(csa_id)]),
                    "unit_count": len(unit_rows_full),
                    "csa_bundles": bundle_displays,
                    "csa_bundle_defs": bundle_defs,
                    "units": [dict(unit) for unit in unit_preview if isinstance(unit, dict)],
                    "sequence_groups": [
                        {
                            "group_index": int(spec.get("group_index", 0) or 0),
                            "source_type": str(spec.get("source_type", "current") or "current"),
                            "origin_frame_id": str(spec.get("origin_frame_id", "") or ""),
                            "tokens": list(tokens_all),
                            "order_sensitive": bool(spec.get("order_sensitive", False)),
                            "string_unit_kind": str(spec.get("string_unit_kind", "") or ""),
                            "string_token_text": str(spec.get("string_token_text", "") or ""),
                            "units": [dict(unit) for unit in unit_preview if isinstance(unit, dict)],
                            "csa_bundles": [dict(bundle) for bundle in bundle_defs if isinstance(bundle, dict)],
                            "ext": raw_ext,
                        }
                    ],
                    "total_er": total_group_er,
                    "total_ev": total_group_ev,
                    "total_energy": round(total_group_er + total_group_ev, 8),
                }
                preview_groups.append(group_preview)
                preview_sequence_groups.extend(group_preview.get("sequence_groups", []))

        group_count = len(group_specs)
        unit_count = len(sa_items)
        csa_count = len(csa_items)
        group_texts = [str(group.get("display_text", "") or "") for group in preview_groups if str(group.get("display_text", "") or "")]
        display_text = " / ".join(group_texts)
        if group_count > len(preview_groups):
            suffix = f" / …(+{group_count - len(preview_groups)}组)"
            display_text = f"{display_text}{suffix}" if display_text else suffix.lstrip(" / ")

        return {
            "packet_id": packet.get("id", ""),
            "display_text": display_text,
            "grouped_display_text": display_text,
            "semantic_display_text": display_text,
            "semantic_grouped_display_text": display_text,
            "visible_text": display_text,
            "flat_tokens": flat_tokens_preview,
            "flat_token_count": flat_token_count,
            "sequence_groups": preview_sequence_groups,
            "groups": preview_groups,
            "units": preview_units,
            "feature_units": preview_units,
            "group_count": group_count,
            "sa_count": unit_count,
            "csa_count": csa_count,
            "csa_bundle_count": csa_count,
            "unit_count": unit_count,
            "total_er": total_er,
            "total_ev": total_ev,
            "preview_mode": True,
            "preview_truncated": bool(group_count > len(preview_groups) or unit_count > len(preview_units) or flat_token_count > len(flat_tokens_preview)),
        }

    @staticmethod
    def _packet_ctx_key(source_type: str, origin_frame_id: str, source_group_index: int) -> tuple[str, str, int]:
        return (str(source_type or ""), str(origin_frame_id or ""), int(source_group_index))

    @staticmethod
    def _dedupe_preserve_order(values: list[Any]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            text = str(value or "")
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    def _packet_item_context(self, item: dict) -> dict[str, Any]:
        ext = dict(item.get("ext", {}) or {}) if isinstance(item.get("ext", {}), dict) else {}
        ctx = dict(ext.get("packet_context", {}) or {}) if isinstance(ext.get("packet_context", {}), dict) else {}
        stimulus = dict(item.get("stimulus", {}) or {}) if isinstance(item.get("stimulus", {}), dict) else {}
        try:
            source_group_index = int(ctx.get("source_group_index", ctx.get("group_index", stimulus.get("group_index", -1))) or -1)
        except Exception:
            source_group_index = -1
        return {
            "source_type": str(ctx.get("source_type", stimulus.get("source_type", "")) or ""),
            "origin_frame_id": str(ctx.get("origin_frame_id", stimulus.get("origin_frame_id", "")) or ""),
            "source_group_index": source_group_index,
            "sequence_index": self._packet_item_sequence_index(item),
            "order_sensitive": bool(ctx.get("order_sensitive", False)),
            "string_unit_kind": str(ctx.get("string_unit_kind", "") or ""),
            "string_token_text": str(ctx.get("string_token_text", "") or ""),
        }

    def _packet_item_sequence_index(self, item: dict) -> int:
        ext = dict(item.get("ext", {}) or {}) if isinstance(item.get("ext", {}), dict) else {}
        ctx = dict(ext.get("packet_context", {}) or {}) if isinstance(ext.get("packet_context", {}), dict) else {}
        stimulus = dict(item.get("stimulus", {}) or {}) if isinstance(item.get("stimulus", {}), dict) else {}
        candidates = [
            ctx.get("sequence_index"),
            ctx.get("position_in_group"),
            stimulus.get("global_sequence_index"),
            stimulus.get("position_in_group"),
        ]
        for value in candidates:
            try:
                return int(value)
            except Exception:
                continue
        return 0

    def _packet_item_display_token(self, item: dict) -> str:
        content = dict(item.get("content", {}) or {}) if isinstance(item.get("content", {}), dict) else {}
        for value in (
            content.get("display"),
            content.get("raw"),
            content.get("normalized"),
            item.get("display_text"),
            item.get("token"),
        ):
            text = str(value or "")
            if text:
                return text
        binding = dict(item.get("binding", {}) or {}) if isinstance(item.get("binding", {}), dict) else {}
        attribute_name = str(binding.get("attribute_name", "") or "")
        if attribute_name:
            attribute_value = binding.get("attribute_value")
            return f"{attribute_name}={attribute_value}" if attribute_value not in {None, ""} else attribute_name
        return str(item.get("id", "") or "")

    def _build_packet_unit_preview(self, item: dict, *, group_index: int, source_type: str, bundle_display: str) -> dict[str, Any]:
        energy = dict(item.get("energy", {}) or {}) if isinstance(item.get("energy", {}), dict) else {}
        ext = dict(item.get("ext", {}) or {}) if isinstance(item.get("ext", {}), dict) else {}
        stimulus = dict(item.get("stimulus", {}) or {}) if isinstance(item.get("stimulus", {}), dict) else {}
        binding = dict(item.get("binding", {}) or {}) if isinstance(item.get("binding", {}), dict) else {}
        sensor_fatigue = dict(ext.get("sensor_fatigue", {}) or {}) if isinstance(ext.get("sensor_fatigue", {}), dict) else {}
        token = self._packet_item_display_token(item)
        role = str(binding.get("attribute_name", "") or "")
        role = "attribute" if role else str(stimulus.get("role", ext.get("unit_role", "feature")) or "feature")
        display_visible = not bool((dict(item.get("linguistic", {}) or {}) if isinstance(item.get("linguistic", {}), dict) else {}).get("is_whitespace", False))
        er = round(float(energy.get("er", 0.0) or 0.0), 8)
        ev = round(float(energy.get("ev", 0.0) or 0.0), 8)
        return {
            "id": str(item.get("id", "") or ""),
            "display": token,
            "role": role,
            "unit_kind": str(item.get("object_type", "sa") or "sa"),
            "source_type": source_type,
            "group_index": group_index,
            "sequence_index": self._packet_item_sequence_index(item),
            "attribute_name": str(binding.get("attribute_name", "") or ""),
            "attribute_value": binding.get("attribute_value"),
            "bundle_display": bundle_display,
            "display_visible": display_visible,
            "er": er,
            "ev": ev,
            "total_energy": round(er + ev, 8),
            "fatigue": round(float(energy.get("fatigue", 0.0) or 0.0), 8),
            "suppression_ratio": round(float(sensor_fatigue.get("suppression_ratio", 0.0) or 0.0), 6),
            "er_before_fatigue": round(float(sensor_fatigue.get("er_before_fatigue", energy.get("er", 0.0)) or 0.0), 8),
            "er_after_fatigue": round(float(sensor_fatigue.get("er_after_fatigue", energy.get("er", 0.0)) or 0.0), 8),
            "window_count": int(sensor_fatigue.get("window_count", 0) or 0),
            "threshold_count": int(sensor_fatigue.get("threshold_count", 0) or 0),
            "window_rounds": int(sensor_fatigue.get("window_rounds", 0) or 0),
            "sensor_round": int(sensor_fatigue.get("sensor_round", 0) or 0),
            "sensor_fatigue": sensor_fatigue,
        }

    def _build_packet_bundle_preview(
        self,
        *,
        csa_ids: list[str],
        csa_index: dict[str, dict],
        sa_index: dict[str, dict],
        bundle_limit: int,
    ) -> tuple[list[str], list[dict[str, Any]], dict[str, str]]:
        displays: list[str] = []
        bundle_defs: list[dict[str, Any]] = []
        bundle_by_unit: dict[str, str] = {}
        for csa_id in csa_ids[:bundle_limit]:
            csa = dict(csa_index.get(str(csa_id), {}) or {})
            member_ids = [str(member_id) for member_id in (csa.get("member_sa_ids", []) or []) if str(member_id)]
            if not member_ids and str(csa.get("anchor_sa_id", "") or ""):
                member_ids = [str(csa.get("anchor_sa_id", "") or "")]
            member_tokens = [self._packet_item_display_token(sa_index.get(member_id, {})) for member_id in member_ids if sa_index.get(member_id, {})]
            display = f"({' + '.join(member_tokens)})" if member_tokens else str(csa.get("bundle_summary", "") or csa.get("id", "") or "")
            displays.append(display)
            bundle_defs.append(
                {
                    "bundle_id": str(csa.get("id", csa_id) or csa_id),
                    "bundle_signature": display,
                    "member_unit_ids": member_ids,
                }
            )
            for member_id in member_ids:
                bundle_by_unit[member_id] = display
        if len(csa_ids) > bundle_limit:
            displays.append(f"…(+{len(csa_ids) - bundle_limit} bundles)")
        return displays, bundle_defs, bundle_by_unit

    @staticmethod
    def _compose_packet_group_display(*, base_text: str, tokens: list[str], order_sensitive: bool, internal_texts: list[str]) -> str:
        parts: list[str] = []
        base = str(base_text or "").strip()
        if not base:
            base = ("".join(tokens) if order_sensitive else " / ".join(tokens)).strip()
        if base:
            parts.append(base)
        for text in internal_texts:
            text_value = str(text or "").strip()
            if text_value and text_value not in parts:
                parts.append(text_value)
        if len(parts) > 1:
            return "{" + " / ".join(parts) + "}"
        return parts[0] if parts else ""

    def _describe_packet_groups(self, packet: dict, *, profile: dict | None = None) -> list[dict]:
        profile = profile or self.cut_engine.build_sequence_profile_from_stimulus_packet(packet)
        groups = []
        packet_groups_by_index = {
            int(group.get("group_index", -1) or -1): dict(group)
            for group in (packet.get("grouped_sa_sequences", []) or [])
            if isinstance(group, dict)
        }
        for group in profile.get("sequence_groups", []):
            raw_group = packet_groups_by_index.get(int(group.get("group_index", -1) or -1), {})
            raw_ext = dict(raw_group.get("ext", {}) or {}) if isinstance(raw_group, dict) else {}
            units = sorted(group.get("units", []), key=lambda item: int(item.get("sequence_index", 0)))
            total_er = round(sum(float(item.get("er", 0.0)) for item in units), 8)
            total_ev = round(sum(float(item.get("ev", 0.0)) for item in units), 8)
            all_tokens = [str(unit.get("token", "")) for unit in units if str(unit.get("token", ""))]
            visible_tokens = [
                str(unit.get("token", ""))
                for unit in units
                if str(unit.get("token", "")) and (bool(unit.get("display_visible", False)) or bool(unit.get("is_placeholder", False)))
            ]
            bundle_displays = self._describe_group_bundles(group)
            cloned_group = {
                **dict(group),
                "units": [dict(unit) for unit in group.get("units", []) if isinstance(unit, dict)],
                "csa_bundles": [dict(bundle) for bundle in group.get("csa_bundles", []) if isinstance(bundle, dict)],
            }
            groups.append(
                {
                    "group_index": group.get("group_index", 0),
                    "source_type": group.get("source_type", ""),
                    "origin_frame_id": group.get("origin_frame_id", ""),
                    "contains_internal_group": bool(raw_ext.get("contains_internal_group", False)),
                    "internal_merge_mode": str(raw_ext.get("internal_merge_mode", "") or ""),
                    "internal_string_group_count": len((raw_ext.get("internal_string_groups", []) or [])),
                    "display_text": self._format_group_display(group),
                    "semantic_display_text": format_semantic_group_display(cloned_group, context="stimulus"),
                    "token_text": " / ".join(all_tokens),
                    "visible_text": "".join(visible_tokens),
                    "tokens": all_tokens,
                    "visible_tokens": visible_tokens,
                    "sa_count": len(units),
                    "csa_count": len(bundle_displays),
                    "unit_count": len(units),
                    "csa_bundles": bundle_displays,
                    "csa_bundle_defs": [dict(bundle) for bundle in group.get("csa_bundles", []) if isinstance(bundle, dict)],
                    "units": [dict(unit) for unit in units if isinstance(unit, dict)],
                    "sequence_groups": [cloned_group],
                    "total_er": total_er,
                    "total_ev": total_ev,
                    "total_energy": round(total_er + total_ev, 8),
                }
            )
        return groups

    def _describe_packet_units(self, packet: dict, *, profile: dict | None = None) -> list[dict]:
        profile = profile or self.cut_engine.build_sequence_profile_from_stimulus_packet(packet)
        rows = []
        for group in profile.get("sequence_groups", []):
            bundle_by_unit = self._map_group_unit_bundles(group)
            for unit in sorted(group.get("units", []), key=lambda item: int(item.get("sequence_index", 0))):
                rows.append(
                    {
                        "id": unit.get("unit_id", ""),
                        "display": unit.get("token", ""),
                        "role": unit.get("unit_role", ""),
                        "unit_kind": unit.get("object_type", "sa"),
                        "source_type": unit.get("source_type", "current"),
                        "group_index": unit.get("group_index", group.get("group_index", 0)),
                        "sequence_index": unit.get("sequence_index", 0),
                        "attribute_name": unit.get("attribute_name", ""),
                        "attribute_value": unit.get("attribute_value"),
                        "bundle_display": bundle_by_unit.get(str(unit.get("unit_id", "")), ""),
                        "display_visible": bool(unit.get("display_visible", False)),
                        "er": round(float(unit.get("er", 0.0)), 8),
                        "ev": round(float(unit.get("ev", 0.0)), 8),
                        "total_energy": round(float(unit.get("total_energy", 0.0)), 8),
                        "fatigue": round(float(unit.get("fatigue", 0.0)), 8),
                        "suppression_ratio": round(float(unit.get("suppression_ratio", 0.0)), 6),
                        "er_before_fatigue": round(float(unit.get("er_before_fatigue", unit.get("er", 0.0))), 8),
                        "er_after_fatigue": round(float(unit.get("er_after_fatigue", unit.get("er", 0.0))), 8),
                        "window_count": int(unit.get("window_count", 0) or 0),
                        "threshold_count": int(unit.get("threshold_count", 0) or 0),
                        "window_rounds": int(unit.get("window_rounds", 0) or 0),
                        "sensor_round": int(unit.get("sensor_round", 0) or 0),
                        "sensor_fatigue": dict(unit.get("sensor_fatigue", {}) or {}),
                    }
                )
        return rows

    def _describe_feature_units(self, packet: dict) -> list[dict]:
        return self._describe_packet_units(packet)

    def _describe_group_bundles(self, group: dict) -> list[str]:
        units_by_id = {
            str(unit.get("unit_id", "")): unit
            for unit in group.get("units", [])
            if str(unit.get("unit_id", ""))
        }
        displays = []
        for bundle in group.get("csa_bundles", []):
            member_tokens = [
                str(units_by_id.get(str(member_id), {}).get("token", ""))
                for member_id in bundle.get("member_unit_ids", [])
                if str(units_by_id.get(str(member_id), {}).get("token", ""))
            ]
            if member_tokens:
                displays.append(f"({' + '.join(member_tokens)})")
            else:
                displays.append(str(bundle.get("bundle_signature", "")))
        return displays

    def _format_group_display(self, group: dict) -> str:
        ext = group.get("ext", {}) if isinstance(group.get("ext", {}), dict) else {}
        string_groups = ext.get("string_groups", []) if isinstance(ext.get("string_groups", []), list) else []
        if string_groups:
            rendered_parts = []
            for sg in string_groups:
                if not isinstance(sg, dict):
                    continue
                part_text = str(sg.get("string_token_text", "") or "")
                if not part_text:
                    part_text = format_semantic_group_display(dict(sg), context="stimulus") or format_group_display(sg.get("units", []), sg.get("csa_bundles", []))
                part_text = str(part_text or "").strip()
                if part_text.startswith("{") and part_text.endswith("}"):
                    part_text = part_text[1:-1]
                if part_text:
                    rendered_parts.append(part_text)
            if rendered_parts:
                return "{" + " / ".join(rendered_parts) + "}"
        return format_group_display(group.get("units", []), group.get("csa_bundles", []))

    def _map_group_unit_bundles(self, group: dict) -> dict[str, str]:
        bundle_map: dict[str, str] = {}
        bundle_displays = self._describe_group_bundles(group)
        for bundle, display in zip(group.get("csa_bundles", []), bundle_displays):
            for member_id in bundle.get("member_unit_ids", []):
                member_text = str(member_id)
                if member_text:
                    bundle_map[member_text] = display
        return bundle_map

    def _export_report(self, trace_id: str, report: dict) -> dict:
        json_path = self.output_dir / f"{trace_id}.json"
        full_json_path = self.output_dir / f"{trace_id}.full.json"
        html_path = self.output_dir / f"{trace_id}.html"
        latest_json = self.output_dir / "latest.json"
        latest_html = self.output_dir / "latest.html"
        compact_report = self._compact_report_for_disk_export(report)
        json_report = compact_report if self._config.get("export_compact_json", True) else report
        exports: dict[str, Any] = {
            "json_path": "",
            "full_json_path": "",
            "html_path": "",
            "latest_json_path": str(latest_json),
            "latest_html_path": str(latest_html),
            "compact_export": bool(self._config.get("export_compact_json", True)),
            "cycle_json_history_enabled": bool(self._config.get("export_cycle_json_history", False)),
            "cycle_html_history_enabled": bool(self._config.get("export_cycle_html_history", False)),
            "full_cycle_json_enabled": bool(self._config.get("export_full_cycle_json", False)),
        }
        try:
            if self._config.get("export_json", True):
                self._write_report_json(latest_json, json_report, compact=bool(self._config.get("export_compact_json", True)))
                exports["latest_json_bytes"] = latest_json.stat().st_size if latest_json.exists() else 0
                if self._config.get("export_cycle_json_history", False):
                    self._write_report_json(json_path, json_report, compact=bool(self._config.get("export_compact_json", True)))
                    exports["json_path"] = str(json_path)
                    exports["json_bytes"] = json_path.stat().st_size if json_path.exists() else 0
                if self._config.get("export_full_cycle_json", False):
                    self._write_report_json(full_json_path, report, compact=False)
                    exports["full_json_path"] = str(full_json_path)
                    exports["full_json_bytes"] = full_json_path.stat().st_size if full_json_path.exists() else 0
            if self._config.get("export_html", True):
                html_report = compact_report if self._config.get("export_compact_html", True) else report
                export_cycle_html(html_report, latest_html)
                exports["latest_html_bytes"] = latest_html.stat().st_size if latest_html.exists() else 0
                if self._config.get("export_cycle_html_history", False):
                    export_cycle_html(html_report, html_path)
                    exports["html_path"] = str(html_path)
                    exports["html_bytes"] = html_path.stat().st_size if html_path.exists() else 0
            self._cleanup_output_reports()
        except Exception as exc:
            exports["error"] = str(exc)
        return exports

    def _write_report_json(self, path: Path, payload: dict, *, compact: bool = True) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":") if compact else None,
            indent=None if compact else 2,
        )
        data = text.encode("utf-8")
        max_bytes = int(self._config.get("export_cycle_json_max_bytes", 2 * 1024 * 1024) or 0)
        if max_bytes > 0 and len(data) > max_bytes:
            fallback = self._emergency_compact_report(payload, original_bytes=len(data), max_bytes=max_bytes)
            data = json.dumps(fallback, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def _compact_report_for_disk_export(self, report: dict) -> dict:
        return self._bounded_json_value(
            report,
            max_depth=7,
            default_list_limit=80,
            default_string_limit=1600,
            list_limits={
                "top_items": 32,
                "items": 32,
                "events": 32,
                "round_details": 6,
                "candidate_details": 8,
                "cam_items": 24,
                "groups": 40,
                "sequence_groups": 32,
                "units": 96,
                "flat_tokens": 160,
                "target_display_texts": 24,
                "memory_item_count": 24,
                "history": 24,
            },
            string_limits={
                "display_text": 1200,
                "grouped_display_text": 1200,
                "semantic_display_text": 1000,
                "semantic_grouped_display_text": 1000,
                "visible_text": 1400,
                "raw": 1400,
                "normalized": 1400,
                "message": 1200,
                "input_text": 1200,
                "normalized_text": 1200,
            },
        )

    def _compact_report_for_runtime_cache(self, report: dict) -> dict:
        return self._bounded_json_value(
            report,
            max_depth=6,
            default_list_limit=48,
            default_string_limit=1200,
            list_limits={
                "top_items": 24,
                "items": 24,
                "events": 24,
                "round_details": 4,
                "candidate_details": 6,
                "cam_items": 20,
                "groups": 24,
                "sequence_groups": 20,
                "units": 64,
                "flat_tokens": 96,
                "target_display_texts": 16,
                "memory_item_count": 16,
                "history": 16,
            },
            string_limits={
                "display_text": 900,
                "grouped_display_text": 900,
                "semantic_display_text": 800,
                "semantic_grouped_display_text": 800,
                "visible_text": 1000,
                "raw": 1000,
                "normalized": 1000,
                "message": 900,
                "input_text": 900,
                "normalized_text": 900,
            },
        )

    def _emergency_compact_report(self, payload: dict, *, original_bytes: int, max_bytes: int) -> dict:
        if not isinstance(payload, dict):
            return {"truncated": True, "reason": "report_payload_too_large", "original_bytes": original_bytes, "max_bytes": max_bytes}
        final_state = payload.get("final_state", {}) if isinstance(payload.get("final_state"), dict) else {}
        state_snapshot = final_state.get("state_snapshot", {}) if isinstance(final_state.get("state_snapshot"), dict) else {}
        return {
            "trace_id": payload.get("trace_id", ""),
            "tick_counter": payload.get("tick_counter", 0),
            "started_at": payload.get("started_at", 0),
            "finished_at": payload.get("finished_at", 0),
            "timing": payload.get("timing", {}),
            "sensor": self._bounded_json_value(payload.get("sensor", {}), max_depth=3, default_list_limit=24, default_string_limit=800),
            "input_queue": self._bounded_json_value(payload.get("input_queue", {}), max_depth=3, default_list_limit=24, default_string_limit=800),
            "state_summary": state_snapshot.get("summary") or final_state.get("state_energy_summary") or {},
            "top_items": self._bounded_json_value(state_snapshot.get("top_items", [])[:12] if isinstance(state_snapshot.get("top_items"), list) else [], max_depth=4, default_list_limit=12, default_string_limit=600),
            "cognitive_feeling": self._bounded_json_value(payload.get("cognitive_feeling", {}), max_depth=4, default_list_limit=16, default_string_limit=800),
            "emotion": self._bounded_json_value(payload.get("emotion", {}), max_depth=4, default_list_limit=16, default_string_limit=800),
            "truncated": True,
            "reason": "report_payload_too_large",
            "original_bytes": original_bytes,
            "max_bytes": max_bytes,
        }

    def _bounded_json_value(
        self,
        value: Any,
        *,
        max_depth: int,
        default_list_limit: int,
        default_string_limit: int,
        list_limits: dict[str, int] | None = None,
        string_limits: dict[str, int] | None = None,
        _key: str = "",
    ) -> Any:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            limit = int((string_limits or {}).get(_key, default_string_limit))
            if len(value) <= limit:
                return value
            tail = value[-80:] if limit >= 180 else ""
            return f"{value[: max(0, limit - 120)]}...(truncated,len={len(value)})...{tail}"
        if max_depth <= 0:
            return {"_omitted": True, "reason": "max_depth"}
        if isinstance(value, list):
            limit = max(0, int((list_limits or {}).get(_key, default_list_limit)))
            rows = [
                self._bounded_json_value(
                    item,
                    max_depth=max_depth - 1,
                    default_list_limit=default_list_limit,
                    default_string_limit=default_string_limit,
                    list_limits=list_limits,
                    string_limits=string_limits,
                )
                for item in value[:limit]
            ]
            if len(value) > limit:
                rows.append({"_truncated_items": len(value) - limit})
            return rows
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                out[key_text] = self._bounded_json_value(
                    item,
                    max_depth=max_depth - 1,
                    default_list_limit=default_list_limit,
                    default_string_limit=default_string_limit,
                    list_limits=list_limits,
                    string_limits=string_limits,
                    _key=key_text,
                )
            return out
        return str(value)

    def _cleanup_output_reports(self) -> None:
        try:
            if not self.output_dir.exists():
                return
            now = time.time()
            max_age_days = float(self._config.get("outputs_cycle_max_age_days", 2) or 0)
            cutoff = now - max_age_days * 24 * 3600 if max_age_days > 0 else 0
            max_json_bytes = int(self._config.get("export_cycle_json_max_bytes", 2 * 1024 * 1024) or 0)
            max_html_bytes = int(self._config.get("export_cycle_html_max_bytes", 4 * 1024 * 1024) or 0)
            json_keep = int(self._config.get("export_cycle_json_history_limit", 12) or 0) if self._config.get("export_cycle_json_history", False) else 0
            full_json_keep = 2 if self._config.get("export_full_cycle_json", False) else 0
            html_keep = int(self._config.get("export_cycle_html_history_limit", 12) or 0) if self._config.get("export_cycle_html_history", False) else 0
            groups = (
                ([path for path in self.output_dir.glob("cycle_*.json") if not path.name.endswith(".full.json")], json_keep, max_json_bytes),
                (list(self.output_dir.glob("cycle_*.full.json")), full_json_keep, max_json_bytes),
                (list(self.output_dir.glob("cycle_*.html")), html_keep, max_html_bytes),
            )
            candidates: list[Path] = []
            for group_files, keep, max_bytes in groups:
                files = sorted(group_files, key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
                for index, path in enumerate(files):
                    try:
                        stat = path.stat()
                        too_old = bool(cutoff and stat.st_mtime < cutoff)
                        too_many = index >= max(0, keep)
                        too_big = bool(max_bytes and stat.st_size > max_bytes)
                        if too_old or too_many or too_big:
                            path.unlink()
                        else:
                            candidates.append(path)
                    except OSError:
                        continue
            max_total = int(self._config.get("outputs_cycle_max_total_bytes", 64 * 1024 * 1024) or 0)
            if max_total <= 0:
                return
            existing = sorted(
                [path for path in candidates if path.exists()],
                key=lambda item: item.stat().st_mtime if item.exists() else 0,
                reverse=True,
            )
            total = 0
            for path in existing:
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                total += size
                if total > max_total:
                    try:
                        path.unlink()
                    except OSError:
                        pass
            self._cleanup_jsonl_logs()
        except Exception:
            return

    def _cleanup_jsonl_logs(self) -> None:
        max_bytes = 2 * 1024 * 1024
        max_archives = 3
        for path in self.output_dir.rglob("*.jsonl"):
            try:
                if path.stat().st_size <= max_bytes:
                    continue
                archive = path.with_name(f"{path.stem}.{time.strftime('%Y%m%d-%H%M%S')}.jsonl.gz")
                with path.open("rb") as src, archive.open("wb") as raw_dst:
                    import gzip

                    with gzip.GzipFile(fileobj=raw_dst, mode="wb", compresslevel=5) as dst:
                        shutil.copyfileobj(src, dst, length=1024 * 1024)
                path.write_text("", encoding="utf-8")
                archives = sorted(path.parent.glob(f"{path.stem}.*.jsonl.gz"), key=lambda item: item.stat().st_mtime)
                for old in archives[:-max_archives]:
                    try:
                        old.unlink()
                    except OSError:
                        pass
            except Exception:
                continue

    def _silence_jieba_logs(self) -> None:
        try:
            import jieba

            jieba.setLogLevel(60)
        except Exception:
            pass

    def _summarize_state_snapshot(self, snapshot: dict) -> dict:
        items = list(snapshot.get("top_items", []))
        summary = dict(snapshot.get("summary", {}) or {})
        total_er = float(summary.get("total_er", 0.0) or 0.0)
        total_ev = float(summary.get("total_ev", 0.0) or 0.0)
        total_cp = float(summary.get("total_cp", 0.0) or 0.0)
        if not summary:
            total_er = sum(float(item.get("er", 0.0) or 0.0) for item in items)
            total_ev = sum(float(item.get("ev", 0.0) or 0.0) for item in items)
            total_cp = sum(float(item.get("cp_abs", 0.0) or 0.0) for item in items)
        energy_by_type = summary.get("energy_by_type", {})
        if not isinstance(energy_by_type, dict) or not energy_by_type:
            energy_by_type = {}
            for item in items:
                ref_type = item.get("ref_object_type", "unknown")
                bucket = energy_by_type.setdefault(
                    ref_type,
                    {"count": 0, "total_er": 0.0, "total_ev": 0.0, "total_cp": 0.0},
                )
                bucket["count"] += 1
                bucket["total_er"] += float(item.get("er", 0.0))
                bucket["total_ev"] += float(item.get("ev", 0.0))
                bucket["total_cp"] += float(item.get("cp_abs", 0.0))
            for bucket in energy_by_type.values():
                bucket["total_er"] = round(float(bucket.get("total_er", 0.0) or 0.0), 8)
                bucket["total_ev"] = round(float(bucket.get("total_ev", 0.0) or 0.0), 8)
                bucket["total_cp"] = round(float(bucket.get("total_cp", 0.0) or 0.0), 8)
        top_er_items = list(snapshot.get("er_top_items", [])) if isinstance(snapshot.get("er_top_items", []), list) else []
        top_ev_items = list(snapshot.get("ev_top_items", [])) if isinstance(snapshot.get("ev_top_items", []), list) else []
        if not top_er_items:
            top_er_items = sorted(items, key=lambda item: item.get("er", 0.0), reverse=True)[:8]
        if not top_ev_items:
            top_ev_items = sorted(items, key=lambda item: item.get("ev", 0.0), reverse=True)[:8]
        active_item_count = int(summary.get("active_item_count", len(items)) or len(items))
        pool_summary = dict(summary.get("pool", {}) or {})
        if not pool_summary:
            energy_values: list[float] = []
            core_energy_values: list[float] = []
            for item in items:
                try:
                    er = max(0.0, float(item.get("er", 0.0) or 0.0))
                    ev = max(0.0, float(item.get("ev", 0.0) or 0.0))
                    total_energy = max(0.0, float(item.get("total_energy", er + ev) or 0.0))
                    if total_energy <= 0.0:
                        total_energy = er + ev
                except Exception:
                    total_energy = 0.0
                if total_energy <= 1e-12:
                    continue
                energy_values.append(total_energy)
                ref_type = str(item.get("ref_object_type", "") or "").strip().lower()
                if ref_type in {"st", "sg"} or (ref_type and ref_type not in {"em", "memory", "episodic_memory"}):
                    core_energy_values.append(total_energy)

            def _energy_shape(values: list[float]) -> tuple[float, float]:
                total = float(sum(max(0.0, float(value or 0.0)) for value in values))
                if total <= 1e-12:
                    return 0.0, 0.0
                concentration = round(
                    sum((max(0.0, float(value or 0.0)) / total) ** 2 for value in values if float(value or 0.0) > 1e-12),
                    8,
                )
                effective_peak_count = round(1.0 / concentration, 8) if concentration > 1e-12 else 0.0
                return float(concentration), float(effective_peak_count)

            def _complexity_score(active_count: int, peak_count: float) -> float:
                size_norm = max(0.0, min(1.0, (float(active_count) - 6.0) / 18.0))
                peak_norm = max(0.0, min(1.0, (float(peak_count) - 1.0) / 11.0))
                return float(round(max(0.0, min(1.0, 0.55 * size_norm + 0.45 * peak_norm)), 8))

            energy_concentration, effective_peak_count = _energy_shape(energy_values)
            core_energy_concentration, core_effective_peak_count = _energy_shape(core_energy_values or energy_values)
            pool_summary = {
                "item_count": active_item_count,
                "active_item_count": active_item_count,
                "total_er": round(total_er, 8),
                "total_ev": round(total_ev, 8),
                "total_cp_abs": round(total_cp, 8),
                "energy_concentration": energy_concentration,
                "effective_peak_count": effective_peak_count,
                "complexity_score": _complexity_score(active_item_count, effective_peak_count),
                "core_energy_concentration": core_energy_concentration,
                "core_effective_peak_count": core_effective_peak_count,
                "core_complexity_score": _complexity_score(active_item_count, core_effective_peak_count),
            }
        return {
            "total_er": round(total_er, 8),
            "total_ev": round(total_ev, 8),
            "total_energy": round(total_er + total_ev, 8),
            "total_cp": round(total_cp, 8),
            "active_item_count": active_item_count,
            "summary_ref": summary,
            "pool": pool_summary,
            "energy_by_type": energy_by_type,
            "top_er_items": top_er_items[:8],
            "top_ev_items": top_ev_items[:8],
            "top_cp_items": sorted(items, key=lambda item: item.get("cp_abs", 0.0), reverse=True)[:8],
        }

    def _enrich_history_event(self, event: dict) -> dict:
        enriched = dict(event)
        target_item = self.pool._store.get(event.get("target_item_id", ""))
        if target_item:
            ref_snapshot = target_item.get("ref_snapshot", {})
            enriched["target_display"] = ref_snapshot.get("content_display", event.get("target_item_id", ""))
            enriched["target_detail"] = ref_snapshot.get("content_display_detail", "")
            enriched["target_ref_object_id"] = target_item.get("ref_object_id", "")
            enriched["target_ref_object_type"] = target_item.get("ref_object_type", "")
        else:
            enriched["target_display"] = event.get("target_item_id", "")
            enriched["target_detail"] = ""
            enriched["target_ref_object_id"] = ""
            enriched["target_ref_object_type"] = ""
        return enriched






















