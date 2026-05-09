# -*- coding: utf-8 -*-
"""
Main entry for HDB.
"""

from __future__ import annotations

import math
import os
import threading
import time
import traceback
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from . import __module_name__, __schema_version__, __version__
from ._audit import AuditLogger
from ._cut_engine import CutEngine
from ._delete_engine import DeleteEngine
from ._episodic_store import EpisodicStore
from ._group_store import GroupStore
from ._logger import ModuleLogger
from ._maintenance import MaintenanceEngine
from ._memory_activation_store import MemoryActivationStore
from ._pointer_index import PointerIndex
from ._profile_restore import restore_group_profile
from ._repair_engine import RepairEngine
from ._self_check import SelfCheckEngine
from ._snapshot_engine import SnapshotEngine
from ._induction_engine import InductionEngine
from ._stimulus_retrieval import StimulusRetrievalEngine
from ._storage_utils import ensure_dir, list_json_files, load_json_file, write_json_file
from ._structure_retrieval import StructureRetrievalEngine
from ._structure_store import StructureStore
from ._weight_engine import WeightEngine
from ._context_metadata import merge_context_metadata, merge_residual_metadata


def _parse_simple_yaml_scalar(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return ""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"\"", "'"}:
        return text[1:-1]
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none", "~"}:
        return None
    try:
        if any(marker in text for marker in (".", "e", "E")):
            return float(text)
        return int(text)
    except ValueError:
        return text



def _load_simple_yaml_config(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    data: dict[str, Any] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line or line.startswith("#") or ":" not in raw_line:
                    continue
                key, raw_value = raw_line.split(":", 1)
                key = key.strip()
                if not key:
                    continue
                value_text = raw_value.split("#", 1)[0].strip()
                data[key] = _parse_simple_yaml_scalar(value_text)
    except Exception:
        return {}
    return data



def _load_yaml_config(path: str) -> dict:
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else _load_simple_yaml_config(path)
    except ImportError:
        return _load_simple_yaml_config(path)
    except Exception:
        return _load_simple_yaml_config(path)

_DEFAULT_CONFIG = {
    "data_dir": "",
    "stimulus_level_max_rounds": 48,
    "stimulus_early_stop_enabled": True,
    "stimulus_early_stop_patience_rounds": 2,
    "stimulus_early_stop_min_progress_ratio": 0.10,
    "stimulus_early_stop_high_energy_unit_threshold": 0.25,
    "stimulus_object_projection_dominance_early_stop_enabled": True,
    "stimulus_object_projection_dominance_min_rounds": 8,
    "stimulus_object_projection_dominance_ratio": 1.25,
    "stimulus_object_projection_dominance_min_remaining_energy": 0.05,
    "stimulus_object_projection_dominance_require_memory_id_enabled": True,
    "stimulus_object_projection_dominance_require_transfer_dominance_enabled": True,
    "stimulus_object_projection_dominance_transfer_ratio": 1.0,
    "structure_level_max_rounds": 4,
    "top_n_attention_stub_default": 16,
    "stimulus_match_transfer_ratio": 1.0,
    "stimulus_competition_noise_mid": 0.01,
    "stimulus_competition_noise_scale": 0.004,
    "stimulus_competition_half_ratio": 0.1,
    "stimulus_competition_curve_power": 1.2,
    "stimulus_competition_stimulus_ratio_power": 0.35,
    "stimulus_competition_structure_ratio_power": 0.85,
    "stimulus_competition_attribute_ratio_power": 1.0,
    "stimulus_transfer_curve_enabled": True,
    "stimulus_transfer_curve_half_score": 0.12,
    "stimulus_transfer_curve_power": 0.38,
    "stimulus_transfer_curve_normalize_at_one": True,
    "stimulus_anchor_owner_residual_presence_cache_enabled": True,
    "stimulus_anchor_owner_residual_presence_shared_cache_enabled": True,
    "stimulus_round_debug_full_text_rounds": 8,
    "stimulus_round_debug_token_preview_limit": 24,
    "stimulus_round_debug_candidate_detail_limit": 16,
    "stimulus_round_debug_shadow_candidate_detail_limit": 8,
    "match_scoring_v2_enabled": True,
    "match_scoring_v2_shadow_only": False,
    "match_scoring_v2_blend_weight": 0.35,
    "match_scoring_v2_min_score": 0.18,
    "soft_partial_match_competition_enabled": True,
    "match_scoring_v2_noise_mid": 0.02,
    "match_scoring_v2_noise_scale": 0.01,
    "match_scoring_v2_half_ratio": 0.14,
    "match_scoring_v2_curve_power": 1.25,
    "match_scoring_v2_base_weight": 0.42,
    "match_scoring_v2_numeric_weight": 0.16,
    "match_scoring_v2_order_weight": 0.16,
    "match_scoring_v2_attribute_weight": 0.12,
    "match_scoring_v2_context_weight": 0.07,
    "match_scoring_v2_energy_weight": 0.07,
    "match_scoring_v2_inclusion_weight": 0.08,
    "match_scoring_v2_numeric_coverage_power": 1.0,
    "residual_memory_as_structure_enabled": True,
    "residual_memory_as_structure_shadow_mode": False,
    "residual_memory_runtime_object_type": "em",
    "unified_numeric_scoring_enabled": True,
    "attribute_soft_scoring_enabled": True,
    "sequence_soft_scoring_enabled": True,
    "time_factor_soft_bonus_enabled": True,
    "time_like_memory_wildcard_enabled": True,
    "stimulus_residual_memory_shadow_v2_enabled": True,
    "stimulus_residual_memory_shadow_skip_when_promotion_disabled_enabled": True,
    "stimulus_residual_memory_promotion_enabled": False,
    "stimulus_residual_memory_promotion_require_time_signal": True,
    "stimulus_residual_memory_promotion_min_v2_score": 0.28,
    "stimulus_residual_memory_promotion_max_candidates_per_owner": 1,
    "stimulus_local_child_candidate_max_per_owner": 48,
    "stimulus_best_match_candidate_max_per_owner": 64,
    "stimulus_shadow_raw_residual_candidate_max_per_owner": 32,
    "time_factor_soft_bonus_max_factor": 1.35,
    "time_factor_soft_bonus_abs_tolerance": 0.35,
    "time_factor_soft_bonus_rel_tolerance": 0.55,
    "stimulus_residual_min_energy": 0.12,
    "stimulus_attribute_energy_scale": 0.22,
    "stimulus_placeholder_energy_scale": 1.0,
    "stimulus_anchor_er_weight": 1.25,
    "stimulus_anchor_ev_weight": 0.9,
    "stimulus_anchor_external_bonus": 0.08,
    "stimulus_anchor_non_punctuation_bonus": 0.05,
    "stimulus_anchor_hidden_attribute_score_scale": 0.22,
    "stimulus_anchor_existing_structure_bonus": 0.18,
    "stimulus_anchor_owner_residual_bonus": 0.85,
    "stimulus_anchor_owner_residual_bonus_energy_half": 0.12,
    "stimulus_anchor_current_packet_preseed_penalty": 0.12,
    "stimulus_anchor_left_to_right_bias_enabled": True,
    "stimulus_anchor_left_to_right_bias_rounds": 1,
    "stimulus_anchor_group_position_penalty": 0.35,
    "stimulus_anchor_sequence_position_penalty": 0.18,
    "stimulus_anchor_punctuation_penalty": 0.35,
    "stimulus_anchor_fatigue_enabled": True,
    "stimulus_anchor_fatigue_decay_per_tick": 0.90,
    "stimulus_anchor_fatigue_step": 0.75,
    "stimulus_anchor_fatigue_cap": 32.0,
    "stimulus_anchor_fatigue_floor_scale": 0.03,
    "stimulus_anchor_fatigue_keep_ticks": 256,
    "stimulus_anchor_fatigue_max_entries": 4096,
    "stimulus_anchor_same_packet_repeat_fatigue_enabled": True,
    "stimulus_anchor_same_packet_repeat_fatigue_step": 2.5,
    "stimulus_residual_projection_ratio": 0.16,
    "stimulus_atomic_seed_confidence": 0.95,
    "stimulus_anchor_seed_confidence": 0.9,
    "stimulus_focus_seed_confidence": 0.9,
    "stimulus_max_common_confidence": 0.86,
    "stimulus_overlap_residual_confidence": 0.68,
    "stimulus_residual_common_confidence": 0.78,
    "stimulus_residual_context_confidence": 0.7,
    "stimulus_extension_confidence": 0.74,
    "stimulus_overlap_residual_link_base_weight": 0.7,
    "stimulus_extension_link_base_weight": 0.75,
    "stimulus_atomic_extension_link_base_weight": 0.72,
    "structure_competition_noise_mid": 0.01,
    "structure_competition_noise_scale": 0.004,
    "structure_competition_half_ratio": 0.1,
    "structure_competition_curve_power": 1.15,
    "structure_path_runtime_scale": 1.35,
    "structure_path_runtime_gain": 0.3,
    "structure_anchor_runtime_scale": 1.35,
    "structure_anchor_runtime_gain": 0.22,
    "structure_anchor_temp_fatigue_step": 0.55,
    "structure_anchor_temp_fatigue_base": 0.7,
    "structure_anchor_temp_fatigue_rho_gain": 0.6,
    "structure_anchor_runtime_family_bonus_enabled": False,
    "structure_anchor_runtime_family_bonus_patterns": [
        "teacher_reward_signal",
        "teacher_punish_signal",
        "reward_signal",
        "punish_signal",
        "cfs_*",
        "时间感受",
    ],
    "structure_anchor_runtime_family_bonus_value": 0.55,
    "structure_anchor_runtime_family_bonus_abs_gain": 0.05,
    "structure_anchor_runtime_family_bonus_abs_value_cap": 2.0,
    "structure_anchor_runtime_family_bonus_max_families": 2,
    "structure_anchor_runtime_family_priority_rank_gain": 0.45,
    "structure_wave_similarity_floor": 0.35,
    "structure_descend_match_floor": 0.35,
    "structure_bias_er_ratio": 0.18,
    "structure_bias_ev_ratio": 0.28,
    "structure_profile_merge_alpha": 0.22,
    "structure_group_entry_reinforce_ratio": 0.15,
    "structure_group_entry_recent_gain_boost": 0.04,
    "structure_common_group_confidence": 0.82,
    "structure_memory_table_soft_limit": 128,
    # ================================================================
    # Internal Residual Resolution (DARL + PARS)
    # ================================================================
    # Goal:
    # - prevent "few huge structures" from exploding internal residual stimulus size
    # - keep endogenous stimulus in the loop, but with dynamic, resource-aware resolution
    #
    # Notes:
    # - Values are intentionally conservative for prototype safety.
    # - These knobs do NOT hardcode any token/word meaning. They only regulate
    #   how much structure detail is emitted per tick for stimulus-level processing.
    "internal_resolution_enabled": True,
    # Global budget unit: "detail units" ~= number of internal SA units emitted.
    # (CutEngine converts internal fragments -> SA/CSA; each selected unit becomes one SA.)
    "internal_resolution_detail_budget_base": 56,
    # ADR (alertness) can temporarily raise the budget (more "mental throughput").
    "internal_resolution_detail_budget_adr_gain": 56,
    # Always guarantee at least this many detail units per CAM structure (prevents energy from disappearing).
    "internal_resolution_min_detail_per_structure": 4,
    "internal_resolution_max_detail_per_structure": 40,
    # Soft allocation curve temperature (higher -> flatter, more even distribution).
    "internal_resolution_temperature": 1.0,
    # Value weights (no semantics, purely runtime signals).
    "internal_resolution_value_weight_total_energy": 1.0,
    "internal_resolution_value_weight_cp_abs": 0.35,
    "internal_resolution_value_weight_runtime_weight": 0.15,
    # Cost soft cap (avoid ultra-huge structures dominating the allocation math).
    "internal_resolution_cost_cap": 512,
    # Hard caps used by auto-tuner/runtime hot reload as well.
    "internal_resolution_flat_unit_cap_per_structure": 240,
    "internal_resolution_max_structures_per_tick": 5,
    # Entrance selection is hybrid: keep density-efficient fragments, but reserve
    # some room for "richer" residual structures so endogenous content does not
    # collapse into many one-unit fragments.
    "internal_resolution_rich_structure_ratio": 0.4,
    "internal_resolution_rich_structure_min_units": 6,
    "internal_resolution_structure_richness_power": 0.5,
    # Detail sampling policy
    "internal_resolution_stable_anchor_count": 1,
    "internal_resolution_anchor_ratio": 0.35,
    # Detail fatigue (within-structure rotation) to gradually cover long structures across ticks.
    "internal_resolution_detail_fatigue_window": 64,
    "internal_resolution_detail_fatigue_start": 2.0,
    "internal_resolution_detail_fatigue_full": 8.0,
    "internal_resolution_detail_fatigue_min_scale": 0.0,
    "internal_resolution_detail_fatigue_beta": 1.0,
    # Focus credit: sustained attention gradually increases detail resolution over long reasoning.
    "internal_resolution_focus_credit_enabled": True,
    "internal_resolution_focus_credit_gain": 0.35,
    "internal_resolution_focus_credit_decay": 0.90,
    "internal_resolution_focus_credit_cap": 6.0,
    "internal_resolution_focus_credit_gamma": 0.25,
    "internal_resolution_runtime_family_bonus_enabled": True,
    "internal_resolution_runtime_family_bonus_patterns": [
        "teacher_reward_signal",
        "teacher_punish_signal",
        "reward_signal",
        "punish_signal",
        "cfs_*",
        "时间感受",
    ],
    "internal_resolution_runtime_family_bonus_value": 0.35,
    "internal_resolution_runtime_family_bonus_abs_gain": 0.08,
    "internal_resolution_runtime_family_bonus_abs_value_cap": 2.0,
    "internal_resolution_runtime_family_bonus_max_families": 2,
    "internal_resolution_runtime_family_priority_rank_gain": 0.45,
    "internal_resolution_runtime_attribute_rescue_enabled": True,
    "internal_resolution_runtime_attribute_rescue_patterns": [
        "teacher_reward_signal",
        "teacher_punish_signal",
        "reward_signal",
        "punish_signal",
        "cfs_*",
        "时间感受",
    ],
    "internal_resolution_runtime_attribute_rescue_ratio": 0.25,
    "internal_resolution_runtime_attribute_rescue_min_slots": 1,
    "internal_resolution_runtime_attribute_rescue_max_slots": 2,
    "internal_resolution_runtime_attribute_score_bonus": 0.75,
    "internal_resolution_runtime_attribute_abs_gain": 0.10,
    "internal_resolution_runtime_attribute_abs_value_cap": 2.0,
    "internal_resolution_runtime_attribute_priority_rank_gain": 0.35,
    # When structure-level fails to hit an existing group, we still want the
    # freshly canonicalized residual runtime context to become endogenous
    # stimulus. This keeps "active landscape -> internal stimulus" alive even
    # during low-match phases, without replacing the tail residual path.
    "internal_storage_projection_enabled": True,
    "internal_storage_projection_ratio": 0.14,
    "internal_storage_projection_max_fragments_per_round": 1,
    "internal_fragment_include_runtime_bound_attributes": False,
    "internal_fragment_runtime_attribute_numeric_only": True,
    "internal_fragment_runtime_attribute_max_count": 8,
    "internal_fragment_runtime_attribute_priority_enabled": True,
    "internal_fragment_runtime_attribute_sort_by_abs_value_desc": True,
    "internal_fragment_runtime_attribute_priority_patterns": [
        "teacher_reward_signal",
        "teacher_punish_signal",
        "reward_signal",
        "punish_signal",
        "cfs_*",
        "时间感受",
    ],
    # CAM runtime-priority side-path:
    # when a high-priority runtime family is visible on a CAM structure but has
    # not been represented by the already-built internal fragments, emit a very
    # small attribute-only fragment so teacher / reward / punish / CFS / time
    # signals still have a chance to survive into the next tick's endogenous
    # stimulus without forcibly perturbing the main anchor competition.
    "internal_cam_runtime_priority_projection_enabled": True,
    "internal_cam_runtime_priority_projection_patterns": [
        "teacher_reward_signal",
        "teacher_punish_signal",
        "reward_signal",
        "punish_signal",
        "cfs_*",
        "时间感受",
    ],
    "internal_cam_runtime_priority_projection_ratio": 0.08,
    "internal_cam_runtime_priority_projection_min_energy": 0.05,
    "internal_cam_runtime_priority_projection_max_fragments": 2,
    "internal_cam_runtime_priority_projection_require_unrepresented": True,
    "internal_attention_landscape_enabled": True,
    "internal_attention_landscape_ratio": 0.08,
    "min_cut_common_length": 2,
    "enable_goal_b_char_sa_string_mode": False,
    "internal_stimulus_flatten_to_single_cooccurrence_group_enabled": True,
    "goal_b_string_seed_soft_max_units": 32,
    "goal_b_string_seed_min_avg_unit_energy_for_long": 0.18,
    "goal_b_string_seed_require_single_source_for_long": True,
    "stimulus_goal_b_string_seed_context_free_identity_enabled": True,
    "stimulus_residual_common_context_free_identity_enabled": True,
    "stimulus_residual_common_require_owner_prefix_alignment_enabled": True,
    "stimulus_residual_common_soft_max_units": 28,
    "stimulus_residual_common_min_avg_unit_energy_for_long": 0.18,
    "stimulus_memory_structure_energy_profile_mode": "runtime_projection_energy",
    "owner_db_persistence_trim_enabled": False,
    "owner_db_runtime_budget_enabled": True,
    "owner_db_runtime_recent_budget": 50,
    "owner_db_runtime_strong_budget": 28,
    "owner_db_runtime_explore_budget": 50,
    "diff_table_soft_limit": 0,
    "group_table_soft_limit": 0,
    "ev_propagation_threshold": 0.12,
    "er_induction_threshold": 0.15,
    "induction_source_effective_energy_prefilter_enabled": True,
    "ev_propagation_ratio": 1.0,
    "er_induction_ratio": 1.0,
    "induction_energy_graph_v2_enabled": True,
    "induction_energy_graph_v2_max_rounds": 1,
    "induction_energy_graph_v2_root_er_decay_ratio": 0.82,
    "induction_energy_graph_v2_root_source_ev_ratio": 1.0,
    "induction_energy_graph_v2_frontier_ev_ratio": 1.0,
    "induction_energy_graph_v2_er_round_ratio": 1.0,
    "induction_energy_graph_v2_min_frontier_ev": 0.05,
    "induction_energy_graph_v2_min_budget": 0.03,
    "induction_energy_graph_v2_max_frontier_nodes_per_source": 0,
    "induction_energy_graph_v2_target_top_k": 0,
    "induction_target_top_k": 0,
    "induction_filter_nonprojectable_targets": True,
    "induction_min_entry_base_weight": 0.001,
    "induction_min_source_base_weight": 0.0,
    "induction_min_projected_delta_ev": 0.0,
    "induction_raw_residual_existing_structure_projection_enabled": True,
    "induction_raw_residual_structure_share": 1.0,
    "induction_raw_residual_structure_target_top_k": 1,
    "induction_raw_residual_group_component_projection_enabled": True,
    "induction_raw_residual_component_target_top_k": 3,
    "induction_raw_residual_component_min_group_units": 3,
    "induction_raw_residual_projection_drop_owner_placeholder_enabled": True,
    "induction_raw_residual_materialized_structure_context_free_identity_enabled": True,
    "induction_raw_residual_static_cache_enabled": True,
    "induction_raw_residual_projection_profile_cache_enabled": True,
    "induction_raw_residual_candidate_static_cache_enabled": False,
    "induction_full_inclusion_shared_cache_enabled": True,
    "memory_activation_decay_round_ratio_ev": 0.88,
    "memory_activation_prune_threshold_ev": 0.05,
    "memory_activation_event_history_limit": 24,
    "runtime_memory_display_max_chars": 240,
    "base_weight_er_gain": 0.08,
    "base_weight_ev_wear": 0.03,
    "base_weight_ev_wear_mode": "multiplicative",
    "base_weight_storage_floor": 0.0,
    "base_weight_new_default": 0.0,
    "ev_only_creation_base_weight": 0.0,
    "residual_base_weight_initial_bias": 0.0,
    "weight_floor": 0.05,
    "recency_gain_boost": 0.08,
    "recency_gain_peak": 10.0,
    "recency_gain_hold_rounds": 2,
    "recency_gain_refresh_floor": 0.45,
    "recency_gain_decay_mode": "by_round",
    "recency_half_life_ms": 60000,
    "recency_gain_decay_ratio": 0.9999976974,
    "fatigue_cap": 1.5,
    "fatigue_increase_per_match": 0.08,
    "fatigue_decay_per_tick": 0.92,
    "fatigue_half_life_ms": 60000,
    "energy_decay_mode": "by_round",
    "energy_decay_round_ratio_er": 0.97,
    "energy_decay_round_ratio_ev": 0.93,
    "energy_decay_half_life_ms_er": 60000,
    "energy_decay_half_life_ms_ev": 30000,
    "enable_pointer_fallback": True,
    "fallback_lookup_max_candidates": 32,
    "enable_cs_event_structures_in_stimulus_retrieval": False,
    "fallback_scan_hard_limit": 200,
    "allow_global_scan_on_runtime_path": False,
    "lru_db_cache_size": 64,
    "exact_lookup_cache_size": 8192,
    "shared_runtime_cache_max_entries": 16384,
    "normalize_sequence_groups_cache_max_entries": 8192,
    "normalize_sequence_groups_cache_shallow_copy_enabled": True,
    "normalize_sequence_groups_cache_zero_copy_enabled": False,
    "structure_fuzzy_metadata_runtime_cache_enabled": True,
    "numeric_bucket_max_per_family": 16,
    "numeric_bucket_neighbor_count": 2,
    "numeric_bucket_creation_abs_gap": 0.2,
    "numeric_bucket_creation_rel_gap": 0.35,
    "numeric_match_abs_tolerance": 0.2,
    "numeric_bucket_synthetic_lookup_rebuild_enabled": False,
    "numeric_bucket_lazy_rebuild_enabled": True,
    "stimulus_atomic_structure_cross_tick_cache_enabled": False,
    "stimulus_atomic_structure_cross_tick_cache_max_entries": 2048,
    "stimulus_atomic_preseed_context_free_identity_enabled": True,
    "stimulus_atomic_preseed_defer_current_packet_matching_enabled": True,
    "stimulus_atomic_preseed_unique_context_direct_create_enabled": True,
    "stimulus_owner_local_residual_shared_index_cache_enabled": True,
    "maximum_common_part_cache_enabled": True,
    "maximum_common_part_exact_fast_path_enabled": True,
    "maximum_common_part_full_inclusion_fast_path_enabled": True,
    "maximum_common_part_single_group_fast_path_enabled": True,
    "maximum_common_group_ordered_subsequence_fast_path_enabled": True,
    "maximum_common_part_cache_max_entries": 4096,
    "maximum_common_part_cache_deepcopy_enabled": False,
    "structure_store_backend": "sqlite",
    "structure_store_sqlite_path": "",
    "structure_store_sqlite_compression_enabled": True,
    "structure_store_sqlite_compression_min_bytes": 4096,
    "structure_store_sqlite_compression_level": 1,
    "structure_store_sqlite_import_legacy_json_on_empty_enabled": True,
    "deferred_persistence_enabled": True,
    "deferred_persistence_flush_interval_calls": 0,
    "deferred_persistence_parallel_flush_enabled": True,
    "deferred_persistence_parallel_flush_min_items": 64,
    "deferred_persistence_parallel_flush_workers": 8,
    "compact_sequence_groups_for_persistence_enabled": False,
    "common_group_length_cache_max_entries": 4096,
    "numeric_match_rel_tolerance": 0.35,
    "numeric_match_min_similarity": 0.4,
    "self_check_default_scope": "quick",
    "repair_batch_limit": 100,
    "repair_sleep_ms_between_batches": 10,
    "allow_delete_unrecoverable": True,
    "max_repair_runtime_ms": 30000,
    "enable_background_repair": True,
    "detail_log_dump_cut_summary": True,
    "detail_log_dump_group_match_profile": False,
    "detail_log_dump_pointer_fallback": True,
    "log_dir": "",
    "log_max_file_bytes": 5 * 1024 * 1024,
}


class HDB:
    def __init__(self, config_path: str = "", config_override: dict | None = None):
        self._config_path = config_path or os.path.join(os.path.dirname(__file__), "config", "hdb_config.yaml")
        self._config = self._build_config(config_override)
        self._paths = self._build_paths()

        self._logger = ModuleLogger(
            log_dir=self._config.get("log_dir", ""),
            max_file_bytes=int(self._config.get("log_max_file_bytes", 5 * 1024 * 1024)),
        )
        self._audit = AuditLogger(self._logger)
        self._weight = WeightEngine(self._config)
        self._cut = CutEngine(self._config)
        self._maintenance = MaintenanceEngine(self._config)
        self._structure_store = StructureStore(self._paths["structures"], self._paths["indexes"], self._config)
        self._group_store = GroupStore(self._paths["groups"], self._config)
        self._episodic_store = EpisodicStore(self._paths["episodic"])
        self._memory_activation_store = MemoryActivationStore(self._paths["memory_activation"], self._config)
        self._pointer_index = PointerIndex(self._config)
        self._cut.set_pointer_index(self._pointer_index)
        self._pointer_index.rebuild_from_store(self._structure_store)
        self._self_check = SelfCheckEngine(self._config)
        self._delete = DeleteEngine(self._config)
        self._repair = RepairEngine(self._config, self._paths["repair"], self._self_check)
        self._snapshot = SnapshotEngine(self._config)
        self._stimulus = StimulusRetrievalEngine(self._config, self._weight, self._logger, self._maintenance)
        self._structure_retrieval = StructureRetrievalEngine(self._config, self._weight, self._logger, self._maintenance)
        self._induction = InductionEngine(self._config, self._weight, self._logger, self._maintenance)

        self._issue_queue: list[dict] = self._load_issue_queue()
        self._repair.set_issue_callback(self._register_issue)
        self._load_repair_jobs()
        self._total_calls = 0
        self._deferred_persistence_call_counter = 0
        # Idle consolidation last result snapshot (for observability/UI); safe to keep in memory.
        self._idle_consolidation_count_total = 0
        self._last_idle_consolidation: dict | None = None
        self._idle_consolidation_lock = threading.RLock()

    def _build_config(self, config_override: dict | None) -> dict:
        config = dict(_DEFAULT_CONFIG)
        config.update(_load_yaml_config(self._config_path))
        if config_override:
            config.update(config_override)
        return config

    def _build_paths(self) -> dict[str, str]:
        data_dir = self._config.get("data_dir") or os.path.join(os.path.dirname(__file__), "data")
        data_dir = str(Path(data_dir))
        paths = {
            "data": data_dir,
            "episodic": os.path.join(data_dir, "episodic"),
            "structures": os.path.join(data_dir, "structures"),
            "groups": os.path.join(data_dir, "groups"),
            "indexes": os.path.join(data_dir, "indexes"),
            "repair": os.path.join(data_dir, "repair"),
            "cache": os.path.join(data_dir, "cache"),
            "memory_activation": os.path.join(data_dir, "memory_activation"),
        }
        for path in paths.values():
            ensure_dir(path)
        return paths

    def _should_flush_deferred_persistence(self) -> bool:
        """Decide whether this hot-path HDB stage should flush pending JSON writes."""
        try:
            raw_interval = self._config.get("deferred_persistence_flush_interval_calls", 1)
            interval = int(1 if raw_interval is None else raw_interval)
        except Exception:
            interval = 1
        if interval <= 0:
            return False
        if interval <= 1:
            return True
        self._deferred_persistence_call_counter = int(getattr(self, "_deferred_persistence_call_counter", 0) or 0) + 1
        return (self._deferred_persistence_call_counter % interval) == 0

    def run_structure_level_retrieval_storage(
        self,
        *,
        state_snapshot: dict,
        trace_id: str,
        tick_id: str | None = None,
        now_ms: int | None = None,
        attention_mode: str = "top_n_stub",
        top_n: int = 16,
        enable_storage: bool = True,
        enable_new_group_creation: bool = True,
        max_rounds: int | None = None,
        metadata: dict | None = None,
    ) -> dict:
        start_time = time.time()
        tick_id = tick_id or trace_id
        self._total_calls += 1
        err = self._validate_state_snapshot(state_snapshot, attention_mode, top_n)
        if err:
            return self._make_error_response("run_structure_level_retrieval_storage", err["code"], err["zh"], err["en"], trace_id, tick_id, start_time)
        try:
            # Important:
            # - `max_rounds` may be explicitly set to 0 by the caller (for "CAM-only internal stimulus"
            #   without any group matching rounds). We must NOT treat 0 as falsy and overwrite it by
            #   the config default.
            effective_max_rounds = (
                int(max_rounds) if max_rounds is not None else int(self._config.get("structure_level_max_rounds", 4))
            )
            batch_ctx = (
                self._structure_store.batch_persistence(flush=self._should_flush_deferred_persistence())
                if bool(self._config.get("deferred_persistence_enabled", True))
                else nullcontext()
            )
            with batch_ctx:
                result = self._structure_retrieval.run(
                    state_snapshot=state_snapshot,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    structure_store=self._structure_store,
                    group_store=self._group_store,
                    pointer_index=self._pointer_index,
                    cut_engine=self._cut,
                    episodic_store=self._episodic_store,
                    attention_mode=attention_mode,
                    top_n=top_n,
                    enable_storage=enable_storage,
                    enable_new_group_creation=enable_new_group_creation,
                    max_rounds=effective_max_rounds,
                    now_ms=now_ms,
                )
            if result.get("fallback_used"):
                self._register_issue({"issue_type": "pointer_fallback_runtime", "target_id": "", "repair_suggestion": ["rebuild_pointer"]})
            self._logger.brief(
                trace_id=trace_id,
                tick_id=tick_id,
                interface="run_structure_level_retrieval_storage",
                success=result.get("code") == "OK",
                message_zh="结构级查存一体执行完成",
                message_en="Structure-level retrieval-storage completed",
                input_summary={"top_n": top_n, "attention_mode": attention_mode},
                output_summary={
                    "round_count": result.get("round_count", 0),
                    "matched_group_count": len(result.get("matched_group_ids", [])),
                    "new_group_count": len(result.get("new_group_ids", [])),
                    "bias_structure_count": len(result.get("bias_structure_ids", [])),
                },
            )
            return self._make_response(
                True,
                result.get("code", "OK"),
                "结构级查存一体执行成功 / Structure-level retrieval-storage completed successfully",
                data=result,
                trace_id=trace_id,
                tick_id=tick_id,
                elapsed_ms=self._elapsed_ms(start_time),
                interface="run_structure_level_retrieval_storage",
            )
        except Exception as exc:
            return self._make_exception_response("run_structure_level_retrieval_storage", exc, trace_id, tick_id, start_time)

    def run_stimulus_level_retrieval_storage(
        self,
        *,
        stimulus_packet: dict,
        trace_id: str,
        tick_id: str | None = None,
        now_ms: int | None = None,
        top_n_attention_stub: int | None = None,
        source_module: str = "state_pool",
        enable_storage: bool = True,
        enable_new_structure_creation: bool = True,
        max_rounds: int | None = None,
        metadata: dict | None = None,
    ) -> dict:
        start_time = time.time()
        tick_id = tick_id or trace_id
        self._total_calls += 1
        err = self._validate_stimulus_packet(stimulus_packet, trace_id)
        if err:
            return self._make_error_response("run_stimulus_level_retrieval_storage", err["code"], err["zh"], err["en"], trace_id, tick_id, start_time)
        try:
            # Same note as structure-level: allow explicit 0.
            effective_max_rounds = (
                int(max_rounds) if max_rounds is not None else int(self._config.get("stimulus_level_max_rounds", 6))
            )
            previous_tick_number = self._config.get("_current_tick_number")
            if isinstance(metadata, dict) and metadata.get("tick_number") is not None:
                self._config["_current_tick_number"] = int(metadata.get("tick_number") or 0)
            batch_ctx = (
                self._structure_store.batch_persistence(flush=self._should_flush_deferred_persistence())
                if bool(self._config.get("deferred_persistence_enabled", True))
                else nullcontext()
            )
            try:
                with batch_ctx:
                    if hasattr(self._cut, "reset_runtime_metrics"):
                        self._cut.reset_runtime_metrics()
                    result = self._stimulus.run(
                        stimulus_packet=stimulus_packet,
                        trace_id=trace_id,
                        tick_id=tick_id,
                        structure_store=self._structure_store,
                        pointer_index=self._pointer_index,
                        cut_engine=self._cut,
                        episodic_store=self._episodic_store,
                        enable_storage=enable_storage,
                        enable_new_structure_creation=enable_new_structure_creation,
                        max_rounds=effective_max_rounds,
                        now_ms=now_ms,
                    )
                    cut_metrics = self._cut.pop_runtime_metrics() if hasattr(self._cut, "pop_runtime_metrics") else {}
                    if isinstance(cut_metrics, dict) and isinstance(result, dict):
                        metrics = result.setdefault("metrics", {})
                        if isinstance(metrics, dict):
                            for key, value in cut_metrics.items():
                                metrics[str(key)] = int(metrics.get(str(key), 0) or 0) + int(value or 0)
            finally:
                if previous_tick_number is None:
                    self._config.pop("_current_tick_number", None)
                else:
                    self._config["_current_tick_number"] = previous_tick_number
            if result.get("fallback_used"):
                self._register_issue({"issue_type": "pointer_fallback_runtime", "target_id": "", "repair_suggestion": ["rebuild_pointer"]})
            self._logger.brief(
                trace_id=trace_id,
                tick_id=tick_id,
                interface="run_stimulus_level_retrieval_storage",
                success=result.get("code") == "OK",
                message_zh="刺激级查存一体执行完成",
                message_en="Stimulus-level retrieval-storage completed",
                input_summary={"packet_id": stimulus_packet.get("id", ""), "source_module": source_module},
                output_summary={
                    "round_count": result.get("round_count", 0),
                    "matched_structure_count": len(result.get("matched_structure_ids", [])),
                    "new_structure_count": len(result.get("new_structure_ids", [])),
                    "remaining_stimulus_sa_count": result.get("remaining_stimulus_sa_count", 0),
                },
            )
            return self._make_response(
                True,
                result.get("code", "OK"),
                "刺激级查存一体执行成功 / Stimulus-level retrieval-storage completed successfully",
                data=result,
                trace_id=trace_id,
                tick_id=tick_id,
                elapsed_ms=self._elapsed_ms(start_time),
                interface="run_stimulus_level_retrieval_storage",
            )
        except Exception as exc:
            return self._make_exception_response("run_stimulus_level_retrieval_storage", exc, trace_id, tick_id, start_time)

    def run_induction_propagation(
        self,
        *,
        state_snapshot: dict,
        trace_id: str,
        tick_id: str | None = None,
        max_source_items: int | None = None,
        enable_ev_propagation: bool = True,
        enable_er_induction: bool = True,
        metadata: dict | None = None,
    ) -> dict:
        start_time = time.time()
        tick_id = tick_id or trace_id
        self._total_calls += 1
        err = self._validate_state_snapshot(state_snapshot, "top_n_stub", 1)
        if err:
            return self._make_error_response("run_induction_propagation", err["code"], err["zh"], err["en"], trace_id, tick_id, start_time)
        if not enable_ev_propagation and not enable_er_induction:
            return self._make_error_response("run_induction_propagation", "INPUT_VALIDATION_ERROR", "至少启用一种感应赋能模式", "At least one induction mode must be enabled", trace_id, tick_id, start_time)
        try:
            batch_ctx = (
                self._structure_store.batch_persistence(flush=self._should_flush_deferred_persistence())
                if bool(self._config.get("deferred_persistence_enabled", True))
                else nullcontext()
            )
            with batch_ctx:
                if hasattr(self._cut, "reset_runtime_metrics"):
                    self._cut.reset_runtime_metrics()
                result = self._induction.run(
                    state_snapshot=state_snapshot,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    structure_store=self._structure_store,
                    episodic_store=self._episodic_store,
                    pointer_index=self._pointer_index,
                    cut_engine=self._cut,
                    max_source_items=max_source_items,
                    enable_ev_propagation=enable_ev_propagation,
                    enable_er_induction=enable_er_induction,
                )
                cut_metrics = self._cut.pop_runtime_metrics() if hasattr(self._cut, "pop_runtime_metrics") else {}
                if isinstance(cut_metrics, dict) and isinstance(result, dict):
                    metrics = result.setdefault("metrics", {})
                    if isinstance(metrics, dict):
                        for key, value in cut_metrics.items():
                            metrics[str(key)] = int(metrics.get(str(key), 0) or 0) + int(value or 0)
            if result.get("fallback_used"):
                self._register_issue({"issue_type": "pointer_fallback_runtime", "target_id": "", "repair_suggestion": ["rebuild_pointer"]})
            self._logger.brief(
                trace_id=trace_id,
                tick_id=tick_id,
                interface="run_induction_propagation",
                success=result.get("code") == "OK",
                message_zh="感应赋能执行完成",
                message_en="Induction propagation completed",
                input_summary={"max_source_items": max_source_items, "enable_ev_propagation": enable_ev_propagation, "enable_er_induction": enable_er_induction},
                output_summary={
                    "source_item_count": result.get("source_item_count", 0),
                    "propagated_target_count": result.get("propagated_target_count", 0),
                    "induced_target_count": result.get("induced_target_count", 0),
                    "total_delta_ev": result.get("total_delta_ev", 0.0),
                },
            )
            return self._make_response(
                True,
                result.get("code", "OK"),
                "感应赋能执行成功 / Induction propagation completed successfully",
                data=result,
                trace_id=trace_id,
                tick_id=tick_id,
                elapsed_ms=self._elapsed_ms(start_time),
                interface="run_induction_propagation",
            )
        except Exception as exc:
            return self._make_exception_response("run_induction_propagation", exc, trace_id, tick_id, start_time)

    def query_structure_database(
        self,
        *,
        structure_id: str,
        trace_id: str,
        include_diff_table: bool = True,
        include_group_table: bool = True,
        limit: int | None = None,
    ) -> dict:
        start_time = time.time()
        self._total_calls += 1
        if not structure_id:
            return self._make_error_response("query_structure_database", "INPUT_VALIDATION_ERROR", "structure_id 不能为空", "structure_id is required", trace_id, "", start_time)
        structure_obj = self._structure_store.get(structure_id)
        if not structure_obj:
            return self._make_error_response("query_structure_database", "STATE_ERROR", f"结构不存在: {structure_id}", f"Structure not found: {structure_id}", trace_id, "", start_time)
        structure_db, pointer_info = self._pointer_index.resolve_db(structure_obj=structure_obj, structure_store=self._structure_store, logger=self._logger, trace_id=trace_id, tick_id="")
        if not structure_db:
            self._register_issue({"issue_type": "missing_primary_pointer", "target_id": structure_id, "repair_suggestion": ["rebuild_pointer"]})
            return self._make_error_response("query_structure_database", "STATE_ERROR", f"结构数据库不存在: {structure_id}", f"Structure database missing: {structure_id}", trace_id, "", start_time)
        payload = {
            "structure": structure_obj,
            "structure_db": {
                "structure_db_id": structure_db.get("structure_db_id", ""),
                "owner_structure_id": structure_db.get("owner_structure_id", ""),
                "integrity": structure_db.get("integrity", {}),
            },
            "pointer_info": pointer_info,
        }
        if include_diff_table:
            diff_table = []
            for entry in list(structure_db.get("diff_table", []))[: limit or None]:
                enriched_entry = dict(entry)
                target_id = enriched_entry.get("target_id", "")
                target_structure = self._structure_store.get(target_id) if target_id else None
                if target_structure:
                    enriched_entry["target_display_text"] = target_structure.get("structure", {}).get("display_text", target_id)
                    enriched_entry["target_signature"] = target_structure.get("structure", {}).get("content_signature", "")
                    enriched_entry["target_structure_stats"] = self._resolve_structure_ref(target_id)
                diff_table.append(enriched_entry)
            payload["structure_db"]["diff_table"] = diff_table
        if include_group_table:
            group_table = []
            for entry in list(structure_db.get("group_table", []))[: limit or None]:
                enriched_entry = dict(entry)
                group_id = enriched_entry.get("group_id", "")
                group_obj = self._group_store.get(group_id) if group_id else None
                if group_obj:
                    enriched_entry["group_stats"] = {
                        "base_weight": round(float(group_obj.get("stats", {}).get("base_weight", 0.0)), 8),
                        "recent_gain": round(float(group_obj.get("stats", {}).get("recent_gain", 1.0)), 8),
                        "fatigue": round(float(group_obj.get("stats", {}).get("fatigue", 0.0)), 8),
                    }
                    enriched_entry["required_structures"] = self._resolve_structure_refs(group_obj.get("required_structure_ids", []))
                    enriched_entry["bias_structures"] = self._resolve_structure_refs(group_obj.get("bias_structure_ids", []))
                group_table.append(enriched_entry)
            payload["structure_db"]["group_table"] = group_table
        return self._make_response(True, "OK", "结构数据库查询成功 / Structure database queried successfully", data=payload, trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time), interface="query_structure_database")

    def query_group(self, *, group_id: str, trace_id: str) -> dict:
        start_time = time.time()
        group_obj = self._group_store.get(group_id)
        if not group_obj:
            return self._make_error_response("query_group", "STATE_ERROR", f"结构组不存在: {group_id}", f"Group not found: {group_id}", trace_id, "", start_time)
        return self._make_response(
            True,
            "OK",
            "结构组查询成功 / Group queried successfully",
            data={
                "group": group_obj,
                "required_structures": self._resolve_structure_refs(group_obj.get("required_structure_ids", [])),
                "bias_structures": self._resolve_structure_refs(group_obj.get("bias_structure_ids", [])),
            },
            trace_id=trace_id,
            elapsed_ms=self._elapsed_ms(start_time),
            interface="query_group",
        )

    def append_episodic_memory(self, *, episodic_payload: dict, trace_id: str, tick_id: str | None = None) -> dict:
        start_time = time.time()
        tick_id = tick_id or trace_id
        event_summary = episodic_payload.get("event_summary", "")
        if not event_summary:
            return self._make_error_response("append_episodic_memory", "INPUT_VALIDATION_ERROR", "event_summary 不能为空", "event_summary is required", trace_id, tick_id, start_time)
        if not episodic_payload.get("timestamp_range") and not episodic_payload.get("created_at"):
            episodic_payload = dict(episodic_payload)
            episodic_payload["created_at"] = int(time.time() * 1000)
        item = self._episodic_store.append(episodic_payload, trace_id=trace_id, tick_id=tick_id)
        self._logger.brief(trace_id=trace_id, tick_id=tick_id, interface="append_episodic_memory", success=True, message_zh="情景记忆追加写成功", message_en="Episodic memory appended", input_summary={"event_summary": event_summary}, output_summary={"episodic_id": item.get("id", "")})
        return self._make_response(True, "OK", "情景记忆追加写成功 / Episodic memory appended successfully", data={"episodic_id": item.get("id", "")}, trace_id=trace_id, tick_id=tick_id, elapsed_ms=self._elapsed_ms(start_time), interface="append_episodic_memory")

    def delete_structure(self, *, structure_id: str, trace_id: str, delete_mode: str = "safe_detach", operator: str | None = None) -> dict:
        start_time = time.time()
        if delete_mode not in {"safe_detach", "force_delete"}:
            return self._make_error_response("delete_structure", "INPUT_VALIDATION_ERROR", f"delete_mode 不合法: {delete_mode}", f"Invalid delete_mode: {delete_mode}", trace_id, "", start_time)
        if delete_mode == "force_delete":
            self._audit.record(trace_id=trace_id, interface="delete_structure", action="force_delete_structure", reason="force_delete", operator=operator or "unknown", detail={"structure_id": structure_id})
        result = self._delete.delete_structure(
            structure_id=structure_id,
            delete_mode=delete_mode,
            structure_store=self._structure_store,
            group_store=self._group_store,
            pointer_index=self._pointer_index,
            issue_callback=self._register_issue,
        )
        return self._make_response(True, "OK", "结构删除执行完成 / Structure deletion completed", data=result, trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time), interface="delete_structure")

    def clear_hdb(self, *, trace_id: str, reason: str, operator: str | None = None, clear_mode: str = "full") -> dict:
        start_time = time.time()
        if clear_mode not in {"full", "episodic_only", "structures_only", "groups_only"}:
            return self._make_error_response("clear_hdb", "INPUT_VALIDATION_ERROR", f"clear_mode 不合法: {clear_mode}", f"Invalid clear_mode: {clear_mode}", trace_id, "", start_time)
        result = self._delete.clear_hdb(
            clear_mode=clear_mode,
            structure_store=self._structure_store,
            group_store=self._group_store,
            episodic_store=self._episodic_store,
            memory_activation_store=self._memory_activation_store,
            pointer_index=self._pointer_index,
            issue_queue=self._issue_queue,
            repair_jobs=self._repair.jobs,
            repair_dir=self._paths["repair"],
        )
        result["runtime_reset"] = self._reset_runtime_state()
        self._save_issue_queue()
        self._audit.record(trace_id=trace_id, interface="clear_hdb", action="clear_hdb", reason=reason, operator=operator or "unknown", detail={"clear_mode": clear_mode, **result})
        return self._make_response(True, "OK", "HDB 清空完成 / HDB cleared successfully", data=result, trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time), interface="clear_hdb")

    def clear_runtime_state(self, *, trace_id: str, reason: str = "runtime_reset") -> dict:
        start_time = time.time()
        result = self._reset_runtime_state()
        self._audit.record(
            trace_id=trace_id,
            interface="clear_runtime_state",
            action="clear_runtime_state",
            reason=reason,
            detail=result,
        )
        return self._make_response(
            True,
            "OK",
            "HDB 运行态已清空 / HDB runtime state cleared",
            data=result,
            trace_id=trace_id,
            elapsed_ms=self._elapsed_ms(start_time),
            interface="clear_runtime_state",
        )

    def idle_consolidate_hdb(
        self,
        *,
        trace_id: str,
        reason: str = "idle_consolidation",
        rebuild_pointer_index: bool = True,
        apply_soft_limits: bool = True,
        batch_limit: int | None = None,
        progress_callback: Any | None = None,
    ) -> dict:
        """
        Idle-time consolidation / compaction for HDB.

        Scope (intentionally conservative):
        - apply diff_table/group_table soft limits across all structure DBs
        - rebuild pointer index (in-memory) to eliminate drift after many writes/deletes

        This is designed to be safe to run:
        - at experiment completion
        - via manual UI trigger
        """
        start_time = time.time()
        now_ms = int(time.time() * 1000)

        scanned_db_count = 0
        updated_db_count = 0
        trimmed_diff_total = 0
        trimmed_group_total = 0
        pointer_before: dict[str, Any] = {}
        pointer_after: dict[str, Any] = {}

        try:
            if hasattr(self, "_pointer_index") and hasattr(self._pointer_index, "export_snapshot"):
                pointer_before = dict(self._pointer_index.export_snapshot() or {})
        except Exception:
            pointer_before = {}

        if apply_soft_limits:
            selected_structure_dbs: list[dict] = []
            normalized_batch_limit = int(batch_limit) if batch_limit is not None else 0
            if normalized_batch_limit > 0 and hasattr(self._structure_store, "get_recent_structures"):
                for structure_obj in self._structure_store.get_recent_structures(normalized_batch_limit):
                    structure_id = str(structure_obj.get("id", "") or "")
                    structure_db = self._structure_store.get_db_by_owner(structure_id) if structure_id else None
                    if isinstance(structure_db, dict):
                        selected_structure_dbs.append(structure_db)
            else:
                selected_structure_dbs = list(self._structure_store.iter_structure_dbs())

            selected_db_total = len(selected_structure_dbs)
            for structure_db in selected_structure_dbs:
                if not isinstance(structure_db, dict):
                    continue
                scanned_db_count += 1
                before_diff = len(structure_db.get("diff_table", []) or [])
                before_group = len(structure_db.get("group_table", []) or [])

                try:
                    self._maintenance.apply_structure_db_soft_limits(structure_db)
                except Exception:
                    continue

                after_diff = len(structure_db.get("diff_table", []) or [])
                after_group = len(structure_db.get("group_table", []) or [])

                if after_diff != before_diff or after_group != before_group:
                    updated_db_count += 1
                    trimmed_diff_total += max(0, int(before_diff) - int(after_diff))
                    trimmed_group_total += max(0, int(before_group) - int(after_group))
                    self._structure_store.update_db(structure_db)
                if callable(progress_callback) and (
                    scanned_db_count == 1
                    or scanned_db_count == selected_db_total
                    or scanned_db_count % 10 == 0
                ):
                    try:
                        progress_callback(
                            {
                                "phase": "soft_limits",
                                "scanned_structure_db_count": int(scanned_db_count),
                                "selected_structure_db_total": int(selected_db_total),
                                "updated_structure_db_count": int(updated_db_count),
                                "trimmed_diff_entry_total": int(trimmed_diff_total),
                                "trimmed_group_entry_total": int(trimmed_group_total),
                            }
                        )
                    except Exception:
                        pass

        if rebuild_pointer_index:
            if callable(progress_callback):
                try:
                    progress_callback(
                        {
                            "phase": "rebuild_pointer_index",
                            "scanned_structure_db_count": int(scanned_db_count),
                            "updated_structure_db_count": int(updated_db_count),
                            "trimmed_diff_entry_total": int(trimmed_diff_total),
                            "trimmed_group_entry_total": int(trimmed_group_total),
                        }
                    )
                except Exception:
                    pass
            try:
                self._pointer_index.rebuild_from_store(self._structure_store)
            except Exception:
                # Pointer rebuild is best-effort; do not fail the consolidation call.
                pass

        try:
            if hasattr(self, "_pointer_index") and hasattr(self._pointer_index, "export_snapshot"):
                pointer_after = dict(self._pointer_index.export_snapshot() or {})
        except Exception:
            pointer_after = {}

        result = {
            "reason": str(reason or ""),
            "timestamp_ms": now_ms,
            "rebuild_pointer_index": bool(rebuild_pointer_index),
            "apply_soft_limits": bool(apply_soft_limits),
            "batch_limit": int(batch_limit) if batch_limit is not None else 0,
            "pointer_index_before": pointer_before,
            "pointer_index_after": pointer_after,
            "scanned_structure_db_count": int(scanned_db_count),
            "updated_structure_db_count": int(updated_db_count),
            "trimmed_diff_entry_total": int(trimmed_diff_total),
            "trimmed_group_entry_total": int(trimmed_group_total),
        }
        self._audit.record(
            trace_id=trace_id,
            interface="idle_consolidate_hdb",
            action="idle_consolidate_hdb",
            reason=reason,
            detail=result,
        )
        resp = self._make_response(
            True,
            "OK",
            "HDB 闲时巩固完成 / HDB idle consolidation completed",
            data=result,
            trace_id=trace_id,
            elapsed_ms=self._elapsed_ms(start_time),
            interface="idle_consolidate_hdb",
        )
        try:
            with self._idle_consolidation_lock:
                self._idle_consolidation_count_total = int(getattr(self, "_idle_consolidation_count_total", 0) or 0) + 1
                self._last_idle_consolidation = dict(resp)
        except Exception:
            pass
        return resp

    def update_idle_consolidation_progress(
        self,
        *,
        status: str,
        job_id: str = "",
        request: dict[str, Any] | None = None,
        progress: dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        payload = {
            "success": not bool(error),
            "code": "OK" if not error else "ERROR",
            "message": "HDB 闲时整理进度 / HDB idle consolidation progress",
            "interface": "idle_consolidate_hdb",
            "data": {
                "job_id": str(job_id or ""),
                "status": str(status or ""),
                "request": dict(request or {}),
                "progress": dict(progress or {}),
                "error": str(error or ""),
                "timestamp_ms": int(time.time() * 1000),
            },
        }
        with self._idle_consolidation_lock:
            self._last_idle_consolidation = payload

    def _reset_runtime_state(self) -> dict:
        structure_runtime = {}
        if hasattr(self._structure_retrieval, "clear_runtime_state"):
            structure_runtime = dict(self._structure_retrieval.clear_runtime_state() or {})

        stimulus_runtime = {}
        if hasattr(self._stimulus, "clear_runtime_state"):
            stimulus_runtime = dict(self._stimulus.clear_runtime_state() or {})

        induction_runtime = {}
        if hasattr(self._induction, "clear_runtime_state"):
            induction_runtime = dict(self._induction.clear_runtime_state() or {})

        shared_runtime_cache = {}
        if hasattr(self._structure_store, "clear_shared_runtime_cache"):
            shared_runtime_cache = dict(self._structure_store.clear_shared_runtime_cache() or {})

        self._idle_consolidation_count_total = 0
        with self._idle_consolidation_lock:
            self._last_idle_consolidation = None
        self._total_calls = 0
        self._deferred_persistence_call_counter = 0
        return {
            "structure_retrieval": structure_runtime,
            "stimulus_retrieval": stimulus_runtime,
            "induction": induction_runtime,
            "shared_runtime_cache": shared_runtime_cache,
            "idle_consolidation_cleared": True,
            "total_calls_reset": True,
        }

    def upsert_cognitive_stitching_event_structure(
        self,
        *,
        event_ref_id: str,
        member_refs: list[str],
        display_text: str,
        diff_rows: list[dict] | None,
        trace_id: str,
        tick_id: str,
        reason: str = "cognitive_stitching_idle_consolidate",
        max_diff_entries: int | None = None,
        sequence_groups: list[dict] | None = None,
        flat_tokens: list[str] | None = None,
        cs_ext: dict | None = None,
        link_members_to_event: bool = True,
        ensure_component_chain_index: bool = True,
    ) -> dict:
        """
        Persist (or update) a Cognitive Stitching event as a HDB structure.

        Design goals:
        - safe to call during idle-time consolidation OR conservative hot-path upsert
        - file-safe structure_id is generated by HDB (event_ref_id itself may contain ':' etc)
        - stable lookup via pointer signature index: structure.structure.content_signature == event_ref_id
        - stored structure MUST be "健全的长期结构": has its own DB pointer, can be O(1) resolved/opened,
          and can participate in stimulus-level retrieval (when enabled by config).
        """
        start_time = time.time()
        tick_id = tick_id or trace_id

        signature = str(event_ref_id or "").strip()
        if not signature:
            return self._make_error_response(
                "upsert_cognitive_stitching_event_structure",
                "INPUT_VALIDATION_ERROR",
                "event_ref_id 不能为空",
                "event_ref_id must not be empty",
                trace_id,
                tick_id,
                start_time,
            )

        cleaned_members = [str(x) for x in (member_refs or []) if str(x)]
        cleaned_members = list(dict.fromkeys(cleaned_members))
        if len(cleaned_members) < 2:
            return self._make_error_response(
                "upsert_cognitive_stitching_event_structure",
                "INPUT_VALIDATION_ERROR",
                "member_refs 至少需要 2 个结构引用",
                "member_refs must contain at least 2 structure refs",
                trace_id,
                tick_id,
                start_time,
            )

        display_text = str(display_text or "").strip() or signature
        now_ms = int(time.time() * 1000)

        structure_store = self._structure_store
        pointer_index = self._pointer_index

        def _build_event_groups_from_members() -> tuple[list[dict], list[str]]:
            """
            Build a compact event structure content from member ST structures (best-effort).

            Important:
            - CS event structures MUST stay matchable by stimulus-level retrieval (existing_length <= incoming_length),
              therefore we do NOT expand the full member token stream into the event structure.
            - We instead sample a bounded number of representative tokens from each member ST and emit them as
              ordered one-token sequence groups. This keeps the event "健全" and retrievable without blowing up
              pointer-index buckets or creating ultra-long structures that can never be fully included by an input packet.
            """
            groups_out: list[dict] = []
            flat_tokens_out: list[str] = []
            next_group_index = 0

            def _is_punctuation_token(token: str) -> bool:
                text = str(token or "").strip()
                if not text:
                    return True
                punct = set(
                    [
                        ",",
                        ".",
                        "!",
                        "?",
                        ";",
                        ":",
                        "，",
                        "。",
                        "！",
                        "？",
                        "；",
                        "：",
                        "、",
                        "…",
                        "(",
                        ")",
                        "（",
                        "）",
                        "[",
                        "]",
                        "【",
                        "】",
                        "{",
                        "}",
                        "《",
                        "》",
                        "<",
                        ">",
                        "\"",
                        "'",
                        "`",
                        "~",
                        "|",
                        "\\",
                        "/",
                        "-",
                        "_",
                        "+",
                        "=",
                    ]
                )
                return all(ch in punct for ch in text)

            def _dedupe_keep_order(tokens: list[str]) -> list[str]:
                out: list[str] = []
                seen: set[str] = set()
                for tok in tokens:
                    t = str(tok or "").strip()
                    if not t or t in seen:
                        continue
                    seen.add(t)
                    out.append(t)
                return out

            # Conservative token budgets: keep events short, but not too short.
            # - For 2 components: 24 tokens max (12 each)
            # - For 8 components: 96 tokens max (12 each)
            max_units_total = max(8, min(96, int(len(cleaned_members)) * 12))
            max_units_per_component = max(2, min(24, int(math.ceil(float(max_units_total) / max(1, len(cleaned_members))))))

            for comp_index, member_id in enumerate(cleaned_members):
                if len(flat_tokens_out) >= max_units_total:
                    break

                try:
                    st_obj = structure_store.get(member_id)
                except Exception:
                    st_obj = None

                st_block = st_obj.get("structure", {}) if isinstance(st_obj, dict) and isinstance(st_obj.get("structure", {}), dict) else {}
                member_tokens: list[str] = []

                # Prefer canonical tokens from sequence_groups.
                # Goal B safety: never propagate presentation-wrapped display tokens such as "{??}" into
                # cognitive stitching event structures. Use string_token_text for char_sequence groups, and only
                # fall back to raw unit tokens when they are not display wrappers.
                for g in list(st_block.get("sequence_groups", []) or []):
                    if not isinstance(g, dict):
                        continue
                    if bool(g.get("order_sensitive", False)) and str(g.get("string_unit_kind", "") or "") == "char_sequence":
                        canonical_text = str(g.get("string_token_text", "") or "").strip()
                        if canonical_text:
                            member_tokens.append(canonical_text)
                            continue
                    for u in list(g.get("units", []) or []):
                        if not isinstance(u, dict):
                            continue
                        tok = str(u.get("token", "") or "").strip()
                        if tok.startswith("{") and tok.endswith("}"):
                            continue
                        if tok:
                            member_tokens.append(tok)
                    for tok in list(g.get("tokens", []) or []):
                        text = str(tok or "").strip()
                        if text.startswith("{") and text.endswith("}"):
                            continue
                        if text:
                            member_tokens.append(text)

                if not member_tokens:
                    member_tokens = [str(t) for t in (st_block.get("flat_tokens", []) or []) if str(t)]

                member_tokens = _dedupe_keep_order(member_tokens)
                member_tokens = [t for t in member_tokens if t and not _is_punctuation_token(t)]
                member_tokens = member_tokens[:max_units_per_component]

                if not member_tokens:
                    fallback_text = ""
                    for g in list(st_block.get("sequence_groups", []) or []):
                        if not isinstance(g, dict):
                            continue
                        if bool(g.get("order_sensitive", False)) and str(g.get("string_unit_kind", "") or "") == "char_sequence":
                            fallback_text = str(g.get("string_token_text", "") or "").strip()
                            if fallback_text:
                                break
                    if not fallback_text:
                        flat_fallback = [str(t) for t in (st_block.get("flat_tokens", []) or []) if str(t)]
                        fallback_text = "".join(flat_fallback).strip() if flat_fallback else ""
                    if not fallback_text:
                        fallback_text = str(member_id).strip()
                    if fallback_text:
                        member_tokens = [fallback_text]

                for tok_index, tok in enumerate(member_tokens):
                    if len(flat_tokens_out) >= max_units_total:
                        break
                    token_text = str(tok or "").strip()
                    if not token_text:
                        continue
                    group = {
                        "group_index": int(next_group_index),
                        "source_type": "cognitive_stitching_event",
                        "origin_frame_id": signature,
                        "tokens": [token_text],
                        "units": [
                            {
                                "token": token_text,
                                "unit_role": "feature",
                                "display_visible": True,
                                "cs_origin_structure_id": member_id,
                                "cs_component_index": int(comp_index),
                                "cs_component_token_index": int(tok_index),
                            }
                        ],
                        "ext": {
                            "cs_event_ref_id": signature,
                            "cs_origin_structure_id": member_id,
                            "cs_component_index": int(comp_index),
                            "cs_component_token_index": int(tok_index),
                        },
                    }
                    groups_out.append(group)
                    flat_tokens_out.append(token_text)
                    next_group_index += 1

            return groups_out, flat_tokens_out

        # Build event content (sequence_groups/flat_tokens).
        # 说明：事件结构必须是“健全的长期结构”，不能只存空壳，否则无法被刺激级查存一体命中。
        event_sequence_groups: list[dict] = []
        event_flat_tokens: list[str] = []
        if isinstance(sequence_groups, list) and sequence_groups:
            # Caller-provided override (already normalized upstream).
            for idx, g in enumerate(sequence_groups):
                if not isinstance(g, dict):
                    continue
                gg = dict(g)
                gg["group_index"] = int(idx)
                if isinstance(gg.get("units", []), list) and gg.get("units"):
                    units_out: list[dict] = []
                    for u in list(gg.get("units", []) or []):
                        if not isinstance(u, dict):
                            continue
                        uu = dict(u)
                        uu["group_index"] = int(idx)
                        units_out.append(uu)
                    gg["units"] = units_out
                ext = gg.get("ext", {}) if isinstance(gg.get("ext", {}), dict) else {}
                ext = dict(ext)
                ext.setdefault("cs_event_ref_id", signature)
                gg["ext"] = ext
                event_sequence_groups.append(gg)
                event_flat_tokens.extend([str(t) for t in (gg.get("tokens", []) or []) if str(t)])
        else:
            event_sequence_groups, event_flat_tokens = _build_event_groups_from_members()

        if isinstance(flat_tokens, list) and flat_tokens:
            event_flat_tokens = [str(t) for t in flat_tokens if str(t)]
        else:
            event_flat_tokens = [str(t) for t in event_flat_tokens if str(t)]

        if not event_sequence_groups:
            # Ultra-fallback: keep the structure usable for indexing/inspection.
            # 极端兜底：至少保证结构可索引、可打开、可展示。
            fallback_tokens: list[str] = []
            for member_id in cleaned_members:
                try:
                    st_obj = structure_store.get(member_id)
                    st_block = (st_obj or {}).get("structure", {}) if isinstance(st_obj, dict) else {}
                    token = str(st_block.get("display_text", "") or member_id)
                except Exception:
                    token = str(member_id)
                if token:
                    fallback_tokens.append(token)
            fallback_tokens = fallback_tokens or list(cleaned_members)
            event_flat_tokens = list(event_flat_tokens) or list(fallback_tokens)
            event_sequence_groups = [
                {
                    "group_index": index,
                    "source_type": "cognitive_stitching_event_fallback",
                    "origin_frame_id": signature,
                    "tokens": [token],
                    "units": [{"token": token, "unit_role": "feature", "display_visible": True}],
                    "ext": {"cs_event_ref_id": signature, "cs_component_index": index},
                }
                for index, token in enumerate(fallback_tokens)
                if str(token)
            ]

        existing_id = ""
        try:
            for candidate_id in pointer_index.query_candidates_by_signature(signature):
                candidate = structure_store.get(candidate_id)
                if not isinstance(candidate, dict):
                    continue
                if str(candidate.get("sub_type", "") or "") != "cognitive_stitching_event_structure":
                    continue
                cand_sig = str((candidate.get("structure", {}) or {}).get("content_signature", "") or "")
                if cand_sig != signature:
                    continue
                existing_id = str(candidate_id)
                break
        except Exception:
            existing_id = ""

        created = False
        updated_structure_fields = False
        upserted_diff_count = 0
        removed_diff_count = 0
        structure_id = ""
        component_chain_prefix_upserted_count = 0
        component_chain_edge_upserted_count = 0

        if existing_id:
            structure_id = existing_id
            structure_obj = structure_store.get(structure_id) or {}
            structure_block = structure_obj.get("structure", {}) if isinstance(structure_obj.get("structure", {}), dict) else {}
            ext = structure_block.get("ext", {}) if isinstance(structure_block.get("ext", {}), dict) else {}
            existing_cs_meta = ext.get("cognitive_stitching", {}) if isinstance(ext.get("cognitive_stitching", {}), dict) else {}

            next_member_refs = cleaned_members
            next_display_text = display_text
            if str(structure_block.get("display_text", "") or "") != next_display_text:
                structure_block["display_text"] = next_display_text
                updated_structure_fields = True
            if list(structure_block.get("member_refs", []) or []) != next_member_refs:
                structure_block["member_refs"] = list(next_member_refs)
                updated_structure_fields = True
            if list(structure_block.get("sequence_groups", []) or []) != list(event_sequence_groups):
                structure_block["sequence_groups"] = list(event_sequence_groups)
                updated_structure_fields = True
            if list(structure_block.get("flat_tokens", []) or []) != list(event_flat_tokens):
                structure_block["flat_tokens"] = list(event_flat_tokens)
                structure_block["token_count"] = int(len(event_flat_tokens))
                updated_structure_fields = True

            next_cs_meta = dict(existing_cs_meta)
            if isinstance(cs_ext, dict):
                next_cs_meta.update(dict(cs_ext))
            next_cs_meta.update(
                {
                    "event_ref_id": signature,
                    "member_refs": list(next_member_refs),
                    "persisted_at_ms": now_ms,
                    "persist_reason": str(reason or ""),
                }
            )
            ext["cognitive_stitching"] = next_cs_meta
            structure_block["ext"] = ext
            structure_obj["structure"] = structure_block
            structure_store.update_structure(structure_obj)
            try:
                pointer_index.register_structure(structure_obj)
            except Exception:
                pass
        else:
            created = True
            cs_meta = dict(cs_ext) if isinstance(cs_ext, dict) else {}
            cs_meta.update(
                {
                    "event_ref_id": signature,
                    "member_refs": list(cleaned_members),
                    "persisted_at_ms": now_ms,
                    "persist_reason": str(reason or ""),
                }
            )
            payload = {
                "sub_type": "cognitive_stitching_event_structure",
                "unit_type": "cognitive_stitching_event",
                "display_text": display_text,
                "member_refs": list(cleaned_members),
                "sequence_groups": list(event_sequence_groups),
                "flat_tokens": list(event_flat_tokens),
                "content_signature": signature,
                "semantic_signature": signature,
                "ext": {"cognitive_stitching": cs_meta},
                "meta": {"confidence": 0.75, "field_registry_version": __schema_version__, "debug": {}, "ext": {}},
            }
            structure_obj, _structure_db = structure_store.create_structure(
                structure_payload=payload,
                trace_id=trace_id,
                tick_id=tick_id,
                source_interface="upsert_cognitive_stitching_event_structure",
                origin="cognitive_stitching_event_persist",
                origin_id=signature,
                parent_ids=list(cleaned_members),
            )
            structure_id = str(structure_obj.get("id", "") or "")
            try:
                pointer_index.register_structure(structure_obj)
            except Exception:
                pass

        # Link: member ST -> event ST (makes the event discoverable in stimulus-level chain traversal).
        # 说明：刺激级查存一体当前主要通过 diff_table 链式扩展来找到长结构；
        # 若不建立这类“成员 -> 事件”的结构边，则事件结构很难被检索命中。
        member_link_upserted_count = 0
        # NOTE:
        # - These links are part of the "健全长期结构" requirement: the CS event must be discoverable
        #   through stimulus-level chain traversal (diff_table) even after hot-path updates.
        # - We therefore upsert links on both create and update. StructureStore.add_diff_entry() is
        #   already idempotent (same target/residual/relation_type will be reinforced instead of duplicated).
        if bool(link_members_to_event) and structure_id:
            try:
                link_w = max(0.05, min(1.2, 0.85 / max(1.0, math.sqrt(float(len(cleaned_members))))))
            except Exception:
                link_w = 0.2
            for comp_index, member_id in enumerate(cleaned_members):
                if not member_id or member_id == structure_id:
                    continue
                try:
                    stored = structure_store.add_diff_entry(
                        member_id,
                        target_id=structure_id,
                        content_signature=structure_id,
                        base_weight=float(link_w),
                        entry_type="structure_ref",
                        ext={
                            "relation_type": "cs_event_member",
                            "cs_event_ref_id": signature,
                            "cs_event_structure_id": structure_id,
                            "cs_component_index": int(comp_index),
                            "persisted_at_ms": now_ms,
                            "persist_reason": str(reason or ""),
                        },
                    )
                    if stored is not None:
                        member_link_upserted_count += 1
                except Exception:
                    pass

        # ================================================================
        # Component Chain Index (local DB chain, O(local) existence check)
        # ================================================================
        #
        # Goal:
        # - event structures should be "健全": discoverable via local DB chain traversal,
        #   not only via global signature lookup.
        # - Align with the design doc: open A DB, find residual B -> get A+B pointer,
        #   open A+B DB, find residual D -> get A+B+D pointer, ...
        #
        # Implementation:
        # - Ensure prefix event structures exist for [c1,c2], [c1,c2,c3], ... (bounded by max_event_component_count).
        # - Upsert one-step diff edges:
        #   owner=c1 -> target=prefix2 (next_component=c2)
        #   owner=prefix2 -> target=prefix3 (next_component=c3)
        #   ...
        #
        # Notes:
        # - We keep member->event links (cs_event_member) as an additional bridge, but the chain edges
        #   are the primary "existence check" path for CS events.
        if structure_id and bool(ensure_component_chain_index):
            try:
                parts = str(signature).split("::")
                prefix_base = str(parts[0] or "").strip() if len(parts) >= 2 else ""
                if prefix_base and len(cleaned_members) >= 2:
                    # Resolve component display tokens once (for prefix display text).
                    comp_display: dict[str, str] = {}
                    for mid in cleaned_members:
                        try:
                            st_obj = structure_store.get(mid)
                            st_block = st_obj.get("structure", {}) if isinstance(st_obj, dict) else {}
                            disp = str((st_block or {}).get("display_text", "") or "").strip()
                            comp_display[mid] = disp or str(mid)
                        except Exception:
                            comp_display[mid] = str(mid)

                    def _sig_for_prefix(members: list[str]) -> str:
                        return f"{prefix_base}::" + "::".join(str(x) for x in members if str(x))

                    def _display_for_prefix(members: list[str]) -> str:
                        # Keep a stable, readable joiner; exact joiner is not semantically critical.
                        return " -> ".join(comp_display.get(mid, mid) for mid in members)

                    prefix_structure_id_by_len: dict[int, str] = {len(cleaned_members): str(structure_id)}
                    prefix_sig_by_len: dict[int, str] = {len(cleaned_members): str(signature)}

                    # Ensure prefix structures exist for len=2..n-1 (n is the full event length).
                    for k in range(2, len(cleaned_members)):
                        prefix_members = cleaned_members[:k]
                        prefix_sig = _sig_for_prefix(prefix_members)
                        prefix_sig_by_len[k] = prefix_sig
                        prefix_display = _display_for_prefix(prefix_members) or prefix_sig
                        res = self.upsert_cognitive_stitching_event_structure(
                            event_ref_id=prefix_sig,
                            member_refs=list(prefix_members),
                            display_text=prefix_display,
                            diff_rows=None,
                            trace_id=f"{trace_id}_cs_prefix_{k}",
                            tick_id=tick_id,
                            reason=f"{reason}:component_chain_prefix",
                            max_diff_entries=max_diff_entries,
                            sequence_groups=None,
                            flat_tokens=None,
                            cs_ext={
                                "stage": "cs_event_component_chain_prefix",
                                "full_event_ref_id": signature,
                                "prefix_len": int(k),
                            },
                            link_members_to_event=False,
                            ensure_component_chain_index=False,
                        )
                        if bool(res.get("success", False)):
                            pid = str((res.get("data", {}) or {}).get("structure_id", "") or "")
                            if pid:
                                prefix_structure_id_by_len[k] = pid
                                component_chain_prefix_upserted_count += 1

                    # For n==2, the only prefix structure is the full event itself.
                    if len(cleaned_members) == 2:
                        prefix_structure_id_by_len[2] = str(structure_id)
                        prefix_sig_by_len[2] = str(signature)
                    else:
                        prefix_sig_by_len[2] = _sig_for_prefix(cleaned_members[:2])

                    # Chain edges: c1 -> prefix2, prefix2 -> prefix3, ...
                    chain_w = 0.85
                    # Step 1: owner is the first component structure.
                    owner0 = cleaned_members[0]
                    target2 = prefix_structure_id_by_len.get(2, "")
                    if owner0 and target2:
                        target2_sig = prefix_sig_by_len.get(2, "")
                        stored = structure_store.add_diff_entry(
                            owner0,
                            target_id=target2,
                            content_signature=cleaned_members[1],
                            base_weight=float(chain_w),
                            entry_type="structure_ref",
                            ext={
                                "relation_type": "cs_event_component_step",
                                # Stable key: the edge represents the existence of the *target prefix*.
                                # Do NOT store the full-event ref id here, otherwise repeated upserts for
                                # longer events could overwrite ext fields in-place.
                                "cs_event_ref_id": target2_sig,
                                "cs_next_component_id": cleaned_members[1],
                                "cs_target_prefix_len": 2,
                                "cs_target_prefix_ref_id": target2_sig,
                                "persisted_at_ms": now_ms,
                                "persist_reason": str(reason or ""),
                            },
                        )
                        if stored is not None:
                            component_chain_edge_upserted_count += 1

                    # Steps 2..n-1
                    for k in range(2, len(cleaned_members)):
                        owner_id = prefix_structure_id_by_len.get(k, "")
                        target_id = prefix_structure_id_by_len.get(k + 1, "")
                        next_component_id = cleaned_members[k]  # 0-based
                        if not owner_id or not target_id or not next_component_id:
                            continue
                        target_sig = prefix_sig_by_len.get(k + 1, signature)
                        stored = structure_store.add_diff_entry(
                            owner_id,
                            target_id=target_id,
                            content_signature=next_component_id,
                            base_weight=float(chain_w),
                            entry_type="structure_ref",
                            ext={
                                "relation_type": "cs_event_component_step",
                                "cs_event_ref_id": target_sig,
                                "cs_next_component_id": next_component_id,
                                "cs_target_prefix_len": int(k + 1),
                                "cs_target_prefix_ref_id": target_sig,
                                "persisted_at_ms": now_ms,
                                "persist_reason": str(reason or ""),
                            },
                        )
                        if stored is not None:
                            component_chain_edge_upserted_count += 1
            except Exception:
                # Best-effort only: if chain indexing fails, the event structure itself is still persisted.
                pass

        if structure_id and diff_rows:
            max_n = int(max_diff_entries) if max_diff_entries is not None else 96
            max_n = max(0, min(512, max_n))
            # Remove previously consolidated edges for this event (keep other relation types).
            try:
                removed_diff_count = int(
                    structure_store.remove_diff_entries(
                        structure_id,
                        predicate=lambda e: isinstance(e, dict)
                        and str((e.get("ext", {}) or {}).get("relation_type", "") or "") == "cs_event_outgoing"
                        and str((e.get("ext", {}) or {}).get("cs_event_ref_id", "") or "") == signature,
                    )
                    or 0
                )
            except Exception:
                removed_diff_count = 0

            for row in list(diff_rows[:max_n]):
                if not isinstance(row, dict):
                    continue
                target_id = str(row.get("target_id", "") or "")
                if not target_id:
                    continue
                try:
                    w = max(0.0, float(row.get("base_weight", 0.0) or 0.0))
                except Exception:
                    w = 0.0
                if w <= 0.0:
                    continue
                entry_type = str(row.get("entry_type", "structure_ref") or "structure_ref")
                ext = dict(row.get("ext", {}) or {})
                ext.update(
                    {
                        "relation_type": "cs_event_outgoing",
                        "cs_event_ref_id": signature,
                        "persist_reason": str(reason or ""),
                        "persisted_at_ms": now_ms,
                    }
                )
                stored = structure_store.add_diff_entry(
                    structure_id,
                    target_id=target_id,
                    content_signature=target_id,
                    base_weight=float(w),
                    entry_type=entry_type,
                    ext=ext,
                )
                if stored is not None:
                    upserted_diff_count += 1

        result = {
            "event_ref_id": signature,
            "structure_id": structure_id,
            "created": bool(created),
            "updated_structure_fields": bool(updated_structure_fields),
            "member_ref_count": int(len(cleaned_members)),
            "member_link_upserted_count": int(member_link_upserted_count),
            "component_chain_prefix_upserted_count": int(component_chain_prefix_upserted_count),
            "component_chain_edge_upserted_count": int(component_chain_edge_upserted_count),
            "diff_row_input_count": int(len(diff_rows or [])),
            "diff_removed_count": int(removed_diff_count),
            "diff_upserted_count": int(upserted_diff_count),
        }
        self._audit.record(
            trace_id=trace_id,
            interface="upsert_cognitive_stitching_event_structure",
            action="upsert_cognitive_stitching_event_structure",
            reason=str(reason or ""),
            detail=result,
        )
        return self._make_response(
            True,
            "OK",
            "CS 事件结构已持久化 / CS event persisted",
            data=result,
            trace_id=trace_id,
            tick_id=tick_id,
            elapsed_ms=self._elapsed_ms(start_time),
            interface="upsert_cognitive_stitching_event_structure",
        )

    def self_check_hdb(
        self,
        *,
        trace_id: str,
        target_id: str | None = None,
        check_scope: str = "quick",
        max_items: int | None = None,
        include_orphans: bool = True,
        allow_fallback_scan: bool = False,
    ) -> dict:
        start_time = time.time()
        result = self._self_check.run(
            structure_store=self._structure_store,
            group_store=self._group_store,
            episodic_store=self._episodic_store,
            memory_activation_store=self._memory_activation_store,
            pointer_index=self._pointer_index,
            trace_id=trace_id,
            target_id=target_id,
            check_scope=check_scope,
            max_items=max_items,
            include_orphans=include_orphans,
        )
        return self._make_response(True, "OK", "HDB 自检完成 / HDB self-check completed", data=result, trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time), interface="self_check_hdb")

    def repair_hdb(
        self,
        *,
        trace_id: str,
        target_id: str | None = None,
        repair_scope: str = "targeted",
        repair_actions: list[str] | None = None,
        batch_limit: int = 100,
        allow_delete_unrecoverable: bool = True,
        background: bool = False,
    ) -> dict:
        start_time = time.time()
        if repair_scope not in {"targeted", "global_quick", "global_full"}:
            return self._make_error_response("repair_hdb", "INPUT_VALIDATION_ERROR", f"repair_scope 不合法: {repair_scope}", f"Invalid repair_scope: {repair_scope}", trace_id, "", start_time)
        if (repair_scope == "global_full" or allow_delete_unrecoverable) and background:
            self._audit.record(trace_id=trace_id, interface="repair_hdb", action="repair_hdb_background", reason=repair_scope, detail={"allow_delete_unrecoverable": allow_delete_unrecoverable})
        result = self._repair.start_or_run(
            trace_id=trace_id,
            structure_store=self._structure_store,
            group_store=self._group_store,
            episodic_store=self._episodic_store,
            memory_activation_store=self._memory_activation_store,
            pointer_index=self._pointer_index,
            delete_engine=self._delete,
            target_id=target_id,
            repair_scope=repair_scope,
            repair_actions=repair_actions,
            batch_limit=batch_limit,
            allow_delete_unrecoverable=allow_delete_unrecoverable,
            background=background,
        )
        message = "HDB 修复任务已提交 / HDB repair started"
        if not background or result.get("status") in {"completed", "stopped", "failed", "timeout"}:
            message = "HDB 修复执行完成 / HDB repair completed"
        return self._make_response(True, "OK", message, data=result, trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time), interface="repair_hdb")

    def stop_repair_job(self, *, repair_job_id: str, trace_id: str) -> dict:
        start_time = time.time()
        result = self._repair.stop_job(repair_job_id)
        if not result.get("success"):
            return self._make_error_response("stop_repair_job", result.get("code", "STATE_ERROR"), "修复任务不存在", "Repair job not found", trace_id, "", start_time)
        return self._make_response(True, "OK", "修复任务停止请求已发送 / Repair job stop requested", data=result, trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time), interface="stop_repair_job")

    def get_hdb_snapshot(
        self,
        *,
        trace_id: str,
        include_stats: bool = True,
        include_recent_structures: bool = True,
        include_recent_groups: bool = True,
        top_k: int = 10,
    ) -> dict:
        start_time = time.time()
        now_ms = int(time.time() * 1000)
        for item in self._structure_store.get_recent_structures(limit=top_k):
            self._weight.decay_structure(item, now_ms=now_ms, round_step=1)
            self._structure_store.update_structure(item)
        for item in self._group_store.get_recent(limit=top_k):
            self._weight.decay_group(item, now_ms=now_ms, round_step=1)
            self._group_store.update(item)
        snapshot = self._snapshot.build_hdb_snapshot(
            trace_id=trace_id,
            structure_store=self._structure_store,
            group_store=self._group_store,
            episodic_store=self._episodic_store,
            memory_activation_store=self._memory_activation_store,
            pointer_index=self._pointer_index,
            issue_queue=self._issue_queue,
            repair_jobs=self._repair.jobs,
            top_k=top_k,
            include_stats=include_stats,
            include_recent_structures=include_recent_structures,
            include_recent_groups=include_recent_groups,
        )
        return self._make_response(True, "OK", "HDB 快照获取成功 / HDB snapshot retrieved", data=snapshot, trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time), interface="get_hdb_snapshot")

    def get_recent_episodic(self, *, trace_id: str, limit: int = 10) -> dict:
        start_time = time.time()
        items = []
        for item in self._episodic_store.get_recent(limit=limit):
            enriched = dict(item)
            enriched["structure_ref_items"] = self._resolve_structure_refs(item.get("structure_refs", []))
            enriched["group_ref_items"] = self._resolve_group_refs(item.get("group_refs", []))
            items.append(enriched)
        return self._make_response(True, "OK", "最近情景记忆获取成功 / Recent episodic memories retrieved", data={"items": items}, trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time), interface="get_recent_episodic")

    def apply_memory_activation_targets(
        self,
        *,
        targets: list[dict],
        trace_id: str,
        tick_id: str | None = None,
    ) -> dict:
        start_time = time.time()
        tick_id = tick_id or trace_id
        result = self._memory_activation_store.apply_targets(
            targets=targets,
            episodic_store=self._episodic_store,
            trace_id=trace_id,
            tick_id=tick_id,
        )
        for item in result.get("items", []):
            memory_id = str(item.get("memory_id", ""))
            if memory_id:
                episodic_obj = self._episodic_store.get(memory_id)
                memory_material = (
                    dict((episodic_obj or {}).get("meta", {}).get("ext", {}).get("memory_material", {}) or {})
                    if isinstance(episodic_obj, dict)
                    else {}
                )
                seq_groups = memory_material.get("sequence_groups", [])
                grouped_display_text = str(memory_material.get("grouped_display_text", "") or "")
                if grouped_display_text:
                    item["display_text"] = grouped_display_text
                elif isinstance(seq_groups, list) and seq_groups:
                    refreshed = self._cut.build_sequence_profile_from_groups(
                        [dict(group) for group in seq_groups if isinstance(group, dict)]
                    ).get("display_text", "")
                    if refreshed:
                        item["display_text"] = refreshed
            item["structure_ref_items"] = self._resolve_structure_refs(item.get("structure_refs", []))
            item["group_ref_items"] = self._resolve_group_refs(item.get("group_refs", []))
        self._logger.brief(
            trace_id=trace_id,
            tick_id=tick_id,
            interface="apply_memory_activation_targets",
            success=True,
            message_zh="记忆赋能池更新完成",
            message_en="Memory activation pool updated",
            input_summary={"target_count": len(targets or [])},
            output_summary={
                "applied_count": result.get("applied_count", 0),
                "total_delta_er": result.get("total_delta_er", 0.0),
                "total_delta_ev": result.get("total_delta_ev", 0.0),
                "total_delta_energy": result.get("total_delta_energy", 0.0),
            },
        )
        return self._make_response(
            True,
            "OK",
            "记忆赋能池更新完成 / Memory activation pool updated",
            data=result,
            trace_id=trace_id,
            tick_id=tick_id,
            elapsed_ms=self._elapsed_ms(start_time),
            interface="apply_memory_activation_targets",
        )

    def tick_memory_activation_pool(self, *, trace_id: str, tick_id: str | None = None) -> dict:
        start_time = time.time()
        tick_id = tick_id or trace_id
        result = self._memory_activation_store.tick(trace_id=trace_id, tick_id=tick_id)
        return self._make_response(
            True,
            "OK",
            "记忆赋能池维护完成 / Memory activation pool maintenance completed",
            data=result,
            trace_id=trace_id,
            tick_id=tick_id,
            elapsed_ms=self._elapsed_ms(start_time),
            interface="tick_memory_activation_pool",
        )

    def get_memory_activation_snapshot(
        self,
        *,
        trace_id: str,
        limit: int = 16,
        sort_by: str = "energy_desc",
    ) -> dict:
        start_time = time.time()
        result = self._memory_activation_store.snapshot(
            episodic_store=self._episodic_store,
            limit=limit,
            sort_by=sort_by,
        )
        for item in result.get("items", []):
            memory_id = str(item.get("memory_id", ""))
            if memory_id:
                episodic_obj = self._episodic_store.get(memory_id)
                memory_material = (
                    dict((episodic_obj or {}).get("meta", {}).get("ext", {}).get("memory_material", {}) or {})
                    if isinstance(episodic_obj, dict)
                    else {}
                )
                seq_groups = memory_material.get("sequence_groups", [])
                grouped_display_text = str(memory_material.get("grouped_display_text", "") or "")
                if grouped_display_text:
                    item["display_text"] = grouped_display_text
                elif isinstance(seq_groups, list) and seq_groups:
                    refreshed = self._cut.build_sequence_profile_from_groups(
                        [dict(group) for group in seq_groups if isinstance(group, dict)]
                    ).get("display_text", "")
                    if refreshed:
                        item["display_text"] = refreshed
            item["structure_ref_items"] = self._resolve_structure_refs(item.get("structure_refs", []))
            item["group_ref_items"] = self._resolve_group_refs(item.get("group_refs", []))
        return self._make_response(
            True,
            "OK",
            "记忆赋能池快照获取成功 / Memory activation snapshot retrieved",
            data=result,
            trace_id=trace_id,
            elapsed_ms=self._elapsed_ms(start_time),
            interface="get_memory_activation_snapshot",
        )

    def query_memory_activation(self, *, memory_id: str, trace_id: str) -> dict:
        start_time = time.time()
        if not memory_id:
            return self._make_error_response(
                "query_memory_activation",
                "INPUT_VALIDATION_ERROR",
                "memory_id 不能为空",
                "memory_id is required",
                trace_id,
                "",
                start_time,
            )
        item = self._memory_activation_store.query(memory_id=memory_id, episodic_store=self._episodic_store)
        if item is None:
            return self._make_error_response(
                "query_memory_activation",
                "STATE_ERROR",
                f"记忆赋能条目不存在: {memory_id}",
                f"Memory activation entry not found: {memory_id}",
                trace_id,
                "",
                start_time,
            )
        item["structure_ref_items"] = self._resolve_structure_refs(item.get("structure_refs", []))
        item["group_ref_items"] = self._resolve_group_refs(item.get("group_refs", []))
        return self._make_response(
            True,
            "OK",
            "记忆赋能条目查询成功 / Memory activation entry queried successfully",
            data={"item": item},
            trace_id=trace_id,
            elapsed_ms=self._elapsed_ms(start_time),
            interface="query_memory_activation",
        )

    def record_memory_feedback(
        self,
        *,
        feedback_items: list[dict],
        trace_id: str,
        tick_id: str | None = None,
    ) -> dict:
        start_time = time.time()
        tick_id = tick_id or trace_id
        result = self._memory_activation_store.record_feedback(
            feedback_items=feedback_items,
            episodic_store=self._episodic_store,
            trace_id=trace_id,
            tick_id=tick_id,
        )
        for item in result.get("items", []):
            item["structure_ref_items"] = self._resolve_structure_refs(item.get("structure_refs", []))
            item["group_ref_items"] = self._resolve_group_refs(item.get("group_refs", []))
        return self._make_response(
            True,
            "OK",
            "记忆反哺事件记录完成 / Memory feedback events recorded",
            data=result,
            trace_id=trace_id,
            tick_id=tick_id,
            elapsed_ms=self._elapsed_ms(start_time),
            interface="record_memory_feedback",
        )

    def build_internal_stimulus_packet(self, fragments: list[dict], trace_id: str, tick_id: str | None = None) -> dict:
        return self._cut.build_internal_stimulus_packet(fragments, trace_id=trace_id, tick_id=tick_id or trace_id)

    def merge_stimulus_packets(self, external_packet: dict | None, internal_packet: dict | None, trace_id: str, tick_id: str | None = None) -> dict:
        return self._cut.merge_stimulus_packets(external_packet, internal_packet, trace_id=trace_id, tick_id=tick_id or trace_id)

    def make_runtime_structure_object(
        self,
        structure_id: str,
        er: float,
        ev: float,
        reason: str = "hdb_projection",
        *,
        structure_obj: dict | None = None,
    ) -> dict | None:
        return self._structure_store.make_runtime_object(
            structure_id,
            er=er,
            ev=ev,
            reason=reason,
            structure_obj=structure_obj,
        )

    def make_runtime_group_object(self, group_id: str, er: float, ev: float, reason: str = "hdb_group_projection") -> dict | None:
        group_obj = self._group_store.get(group_id)
        if group_obj is None:
            return None
        profile = restore_group_profile(
            group_obj,
            cut_engine=self._cut,
            structure_store=self._structure_store,
            group_store=self._group_store,
        )
        display_text = str(profile.get("display_text", "") or group_id)
        now_ms = int(time.time() * 1000)
        return {
            "id": group_id,
            "object_type": "sg",
            "sub_type": group_obj.get("sub_type", "event_template_group"),
            "content": {
                "raw": display_text,
                "display": display_text,
                "normalized": display_text,
            },
            "energy": {
                "er": round(float(er), 6),
                "ev": round(float(ev), 6),
            },
            # Keep the stored group object, but attach a restored view for runtime visibility.
            "group": dict(group_obj),
            "group_structure": dict(profile),
            "source": {
                "module": __module_name__,
                "interface": "make_runtime_group_object",
                "origin": reason or "hdb_group_projection",
                "origin_id": group_id,
                "parent_ids": list(group_obj.get("required_structure_ids", [])),
            },
            "created_at": group_obj.get("created_at", now_ms),
            "updated_at": now_ms,
        }

    def make_runtime_memory_object(
        self,
        memory_id: str,
        er: float,
        ev: float,
        reason: str = "hdb_memory_projection",
        display_text: str = "",
        backing_structure_id: str = "",
        runtime_object_type: str = "",
    ) -> dict | None:
        episodic_obj = self._episodic_store.get(memory_id)
        if episodic_obj is None:
            return None
        ext = dict(episodic_obj.get("meta", {}).get("ext", {}) or {})
        memory_material = dict(ext.get("memory_material", {}) or {})
        grouped_display_text = str(memory_material.get("grouped_display_text", "") or "")
        sequence_groups = list(memory_material.get("sequence_groups", []) or [])
        structure_refs = list(episodic_obj.get("structure_refs", []) or [])
        group_refs = list(episodic_obj.get("group_refs", []) or [])
        context_ref_id = str(backing_structure_id or (structure_refs[0] if structure_refs else "")).strip()
        context_ref_type = "st" if context_ref_id.startswith("st") else ""
        context_text = grouped_display_text or str(display_text or "")
        if context_ref_id:
            structure_obj = self._structure_store.get(context_ref_id)
            if isinstance(structure_obj, dict):
                context_text = str(
                    (structure_obj.get("structure", {}) or {}).get("display_text", "")
                    or context_text
                    or context_ref_id
                )
        full_runtime_display = (
            str(display_text or "")
            or grouped_display_text
            or str(episodic_obj.get("meta", {}).get("ext", {}).get("display_text", ""))
            or str(episodic_obj.get("event_summary", ""))
            or str(memory_id)
        )
        max_display_chars = max(80, int(self._config.get("runtime_memory_display_max_chars", 240)))
        runtime_display = full_runtime_display
        if len(runtime_display) > max_display_chars:
            runtime_display = f"{runtime_display[:max_display_chars]}...(len={len(full_runtime_display)})"
        requested_object_type = str(
            runtime_object_type or self._config.get("residual_memory_runtime_object_type", "em") or "em"
        ).strip().lower()
        if requested_object_type not in {"st", "em"}:
            requested_object_type = "st"
        runtime_ext_base = merge_context_metadata(
            {
                "source_em_id": memory_id,
                "source_memory_created_at": int(episodic_obj.get("created_at", 0) or 0),
                "context_text": context_text or context_ref_id or runtime_display,
                "memory_kind": str(memory_material.get("memory_kind", "") or ""),
                "residual_memory_as_structure": True,
                "memory_projection_object_type_requested": requested_object_type,
                "memory_projection_backing_structure_id": context_ref_id,
            },
            context_ref_object_id=context_ref_id,
            context_ref_object_type=context_ref_type,
            context_owner_structure_id=context_ref_id if context_ref_type == "st" else "",
            parent_ids=structure_refs,
        )
        runtime_ext_base = merge_residual_metadata(
            runtime_ext_base,
            residual_origin_kind="memory_runtime_projection",
            residual_origin_entry_id=memory_id,
        )
        runtime_memory = {
            "memory_id": memory_id,
            "event_summary": episodic_obj.get("event_summary", ""),
            "structure_refs": structure_refs,
            "group_refs": group_refs,
            "backing_structure_id": str(backing_structure_id or ""),
            "grouped_display_text": grouped_display_text,
            "semantic_grouped_display_text": grouped_display_text,
            "sequence_groups": sequence_groups,
            "display_text": runtime_display,
            "full_display_text": full_runtime_display,
            "memory_created_at": int(episodic_obj.get("created_at", 0) or 0),
        }
        runtime_source = {
            "module": __module_name__,
            "interface": "make_runtime_memory_object",
            "origin": reason or "hdb_memory_projection",
            "origin_id": memory_id,
            "parent_ids": structure_refs,
        }
        runtime_meta = {
            "confidence": 1.0,
            "field_registry_version": __schema_version__,
            "debug": {},
        }
        if requested_object_type == "st" and context_ref_id:
            runtime_structure = self.make_runtime_structure_object(
                context_ref_id,
                er=er,
                ev=ev,
                reason=reason,
            )
            if isinstance(runtime_structure, dict):
                runtime_ext = dict(runtime_ext_base)
                runtime_ext["memory_projection_object_type_actual"] = "st"
                runtime_meta_with_ext = dict(runtime_meta)
                runtime_meta_with_ext["ext"] = dict(runtime_ext)
                runtime_structure = dict(runtime_structure)
                runtime_structure["source"] = dict(runtime_source)
                runtime_structure["ext"] = dict(runtime_ext)
                runtime_structure["meta"] = runtime_meta_with_ext
                runtime_structure["memory"] = dict(runtime_memory)
                runtime_structure["created_at"] = episodic_obj.get("created_at", int(time.time() * 1000))
                runtime_structure["updated_at"] = int(time.time() * 1000)
                return runtime_structure
        runtime_ext = dict(runtime_ext_base)
        runtime_ext["memory_projection_object_type_actual"] = "em"
        if requested_object_type == "st":
            runtime_ext["memory_projection_runtime_fallback"] = "legacy_em_fallback_missing_backing_structure"
        runtime_meta["ext"] = dict(runtime_ext)
        return {
            "id": memory_id,
            "object_type": "em",
            "sub_type": episodic_obj.get("sub_type", "tick_episode"),
            "content": {
                "raw": runtime_display,
                "display": runtime_display,
                "normalized": runtime_display,
            },
            "energy": {
                "er": round(float(er), 6),
                "ev": round(float(ev), 6),
            },
            "memory": runtime_memory,
            "source": runtime_source,
            "ext": runtime_ext,
            "meta": runtime_meta,
            "created_at": episodic_obj.get("created_at", int(time.time() * 1000)),
            "updated_at": int(time.time() * 1000),
        }

    def reload_config(self, *, trace_id: str, config_path: str | None = None, apply_partial: bool = True) -> dict:
        start_time = time.time()
        path = config_path or self._config_path
        raw = _load_yaml_config(path)
        if not raw:
            return self._make_error_response("reload_config", "CONFIG_ERROR", f"配置加载失败或为空: {path}", f"Config failed to load or empty: {path}", trace_id, "", start_time)
        applied = []
        rejected = []
        for key, value in raw.items():
            if key in _DEFAULT_CONFIG:
                self._config[key] = value
                applied.append(key)
            else:
                rejected.append(key)
        self._weight.update_config(self._config)
        self._cut.update_config(self._config)
        self._pointer_index.update_config(self._config)
        self._maintenance.update_config(self._config)
        self._snapshot.update_config(self._config)
        self._stimulus.update_config(self._config)
        self._structure_retrieval.update_config(self._config)
        self._induction.update_config(self._config)
        self._structure_store.update_config(self._config)
        self._group_store.update_config(self._config)
        self._memory_activation_store.update_config(self._config)
        self._self_check.update_config(self._config)
        self._delete.update_config(self._config)
        self._repair.update_config(self._config)
        self._logger.update_config(log_dir=self._config.get("log_dir", ""), max_file_bytes=int(self._config.get("log_max_file_bytes", 0)))
        return self._make_response(True, "OK", "配置热加载完成 / Config hot reload done", data={"applied": applied, "rejected": rejected}, trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time), interface="reload_config")

    def close(self) -> None:
        try:
            self._structure_store.flush_pending_persistence()
        except Exception:
            pass
        try:
            self._structure_store.close()
        except Exception:
            pass
        self._save_issue_queue()
        self._logger.close()

    def _load_issue_queue(self) -> list[dict]:
        issues_path = os.path.join(self._paths["repair"], "issues.json")
        payload = load_json_file(issues_path, default=[])
        return payload if isinstance(payload, list) else []

    def _save_issue_queue(self) -> None:
        issues_path = os.path.join(self._paths["repair"], "issues.json")
        write_json_file(issues_path, self._issue_queue)

    def _load_repair_jobs(self) -> None:
        for path in list_json_files(self._paths["repair"]):
            payload = load_json_file(path, default=None)
            if isinstance(payload, dict) and payload.get("repair_job_id"):
                self._repair.jobs[payload["repair_job_id"]] = payload

    def _register_issue(self, issue: dict) -> dict:
        issue = dict(issue)
        issue.setdefault("issue_id", f"hdb_issue_{len(self._issue_queue) + 1:06d}")
        issue.setdefault("created_at", int(time.time() * 1000))
        self._issue_queue.append(issue)
        if len(self._issue_queue) > 5000:
            self._issue_queue = self._issue_queue[-5000:]
        self._save_issue_queue()
        return issue

    def _resolve_structure_ref(self, structure_id: str) -> dict:
        structure_obj = self._structure_store.get(structure_id)
        if not structure_obj:
            return {
                "structure_id": structure_id,
                "display_text": structure_id,
                "content_signature": "",
                "base_weight": 0.0,
                "recent_gain": 1.0,
                "fatigue": 0.0,
                "exists": False,
            }
        stats = structure_obj.get("stats", {})
        return {
            "structure_id": structure_id,
            "display_text": structure_obj.get("structure", {}).get("display_text", structure_id),
            "content_signature": structure_obj.get("structure", {}).get("content_signature", ""),
            "base_weight": round(float(stats.get("base_weight", 0.0)), 8),
            "recent_gain": round(float(stats.get("recent_gain", 1.0)), 8),
            "fatigue": round(float(stats.get("fatigue", 0.0)), 8),
            "exists": True,
        }

    def _resolve_structure_refs(self, structure_ids: list[str]) -> list[dict]:
        return [self._resolve_structure_ref(structure_id) for structure_id in structure_ids or []]

    def _resolve_group_refs(self, group_ids: list[str]) -> list[dict]:
        refs = []
        for group_id in group_ids or []:
            group_obj = self._group_store.get(group_id)
            if not group_obj:
                refs.append(
                    {
                        "group_id": group_id,
                        "required_structures": [],
                        "bias_structures": [],
                        "exists": False,
                    }
                )
                continue
            refs.append(
                {
                    "group_id": group_id,
                    "required_structures": self._resolve_structure_refs(group_obj.get("required_structure_ids", [])),
                    "bias_structures": self._resolve_structure_refs(group_obj.get("bias_structure_ids", [])),
                    "exists": True,
                }
            )
        return refs

    def _validate_stimulus_packet(self, stimulus_packet: Any, trace_id: str) -> dict | None:
        if not isinstance(stimulus_packet, dict):
            return {"code": "INPUT_VALIDATION_ERROR", "zh": "stimulus_packet 必须是 dict", "en": "stimulus_packet must be a dict"}
        if stimulus_packet.get("object_type") != "stimulus_packet":
            return {"code": "INPUT_VALIDATION_ERROR", "zh": "stimulus_packet.object_type 必须为 stimulus_packet", "en": "stimulus_packet.object_type must be stimulus_packet"}
        for field in ("sa_items", "csa_items", "grouped_sa_sequences"):
            if field not in stimulus_packet:
                return {"code": "INPUT_VALIDATION_ERROR", "zh": f"stimulus_packet 缺少字段: {field}", "en": f"stimulus_packet missing field: {field}"}
        if not trace_id:
            return {"code": "INPUT_VALIDATION_ERROR", "zh": "trace_id 不能为空", "en": "trace_id is required"}
        return None

    def _validate_state_snapshot(self, state_snapshot: Any, attention_mode: str, top_n: int) -> dict | None:
        if not isinstance(state_snapshot, dict):
            return {"code": "INPUT_VALIDATION_ERROR", "zh": "state_snapshot 必须是 dict", "en": "state_snapshot must be a dict"}
        if "summary" not in state_snapshot:
            return {"code": "INPUT_VALIDATION_ERROR", "zh": "state_snapshot 缺少 summary", "en": "state_snapshot missing summary"}
        if "top_items" not in state_snapshot and "items" not in state_snapshot:
            return {"code": "INPUT_VALIDATION_ERROR", "zh": "state_snapshot 缺少 top_items 或 items", "en": "state_snapshot missing top_items or items"}
        # 注意力模式（attention_mode）说明：
        # - top_n_stub: 旧版占位口径（仍保留兼容）
        # - cam_snapshot: 正式口径，表示 state_snapshot 本身就是 CAM（当前注意记忆体）的输出快照
        if attention_mode not in {"top_n_stub", "cam_snapshot"}:
            return {"code": "NOT_IMPLEMENTED_ERROR", "zh": f"attention_mode 尚未实现: {attention_mode}", "en": f"attention_mode not implemented: {attention_mode}"}
        if top_n <= 0:
            return {"code": "INPUT_VALIDATION_ERROR", "zh": "top_n 必须大于 0", "en": "top_n must be greater than 0"}
        return None

    def _make_exception_response(self, interface: str, exc: Exception, trace_id: str, tick_id: str, start_time: float) -> dict:
        self._logger.error(trace_id=trace_id, tick_id=tick_id, interface=interface, code="INTERNAL_ERROR", message_zh=f"内部异常: {exc}", message_en=f"Internal exception: {exc}", detail={"traceback": traceback.format_exc()})
        return self._make_response(False, "INTERNAL_ERROR", f"内部异常 / Internal exception: {exc}", error={"message": str(exc)}, trace_id=trace_id, tick_id=tick_id, elapsed_ms=self._elapsed_ms(start_time), interface=interface)

    def _make_error_response(self, interface: str, code: str, zh: str, en: str, trace_id: str, tick_id: str, start_time: float) -> dict:
        self._logger.error(trace_id=trace_id, tick_id=tick_id, interface=interface, code=code, message_zh=zh, message_en=en)
        return self._make_response(False, code, f"{zh} / {en}", error={"code": code, "message_zh": zh, "message_en": en}, trace_id=trace_id, tick_id=tick_id, elapsed_ms=self._elapsed_ms(start_time), interface=interface)

    @staticmethod
    def _elapsed_ms(start_time: float) -> int:
        return int((time.time() - start_time) * 1000)

    @staticmethod
    def _make_response(success: bool, code: str, message: str, *, data: Any = None, error: Any = None, trace_id: str = "", tick_id: str = "", elapsed_ms: int = 0, interface: str = "") -> dict:
        return {
            "success": success,
            "code": code,
            "message": message,
            "data": data,
            "error": error,
            "meta": {
                "module": __module_name__,
                "interface": interface,
                "trace_id": trace_id,
                "tick_id": tick_id,
                "elapsed_ms": elapsed_ms,
                "logged": True,
                "version": __version__,
                "schema_version": __schema_version__,
            },
        }






