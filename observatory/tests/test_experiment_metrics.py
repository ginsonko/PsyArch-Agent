# -*- coding: utf-8 -*-

from __future__ import annotations

from observatory.experiment.metrics import extract_tick_metrics


def test_extract_tick_metrics_flattens_attention_energy_resource():
    report = {
        "trace_id": "trace_attention_energy_resource",
        "tick_id": "cycle_attention_energy_resource_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {
            "base_memory_total_energy": 12.0,
            "attention_gain_budget_applied": 4.5,
            "attention_gross_gain_energy_applied": 5.25,
            "attention_suppressed_total_energy": 0.75,
            "attention_net_delta_energy": 4.5,
            "attention_energy_resource": {
                "enabled": True,
                "filter_applied": True,
                "base": 10.0,
                "min": 0.0,
                "max": 32.0,
                "budget": 11.5,
                "filtered_total_energy": 16.5,
                "gross_gain_energy_applied": 5.25,
                "gain_weight_total": 1.75,
                "gain_floor": 0.52,
                "suppression_floor": 0.36,
                "suppression_min_ratio": 0.25,
            },
            "modulation_applied": {
                "attention_energy_budget": 11.5,
            },
        },
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 1, "input_text": "", "input_is_empty": True})

    assert metrics["attention_base_memory_total_energy"] == 12.0
    assert metrics["attention_final_memory_total_energy"] == 16.5
    assert metrics["attention_energy_budget_enabled"] == 1
    assert metrics["attention_energy_filter_applied"] == 1
    assert metrics["attention_energy_budget_base"] == 10.0
    assert metrics["attention_energy_budget_min"] == 0.0
    assert metrics["attention_energy_budget_max"] == 32.0
    assert metrics["attention_mod_attention_energy_budget"] == 11.5
    assert metrics["attention_energy_budget"] == 11.5
    assert metrics["attention_gain_budget_applied"] == 4.5
    assert metrics["attention_gross_gain_energy_applied"] == 5.25
    assert metrics["attention_suppressed_total_energy"] == 0.75
    assert metrics["attention_net_delta_energy"] == 4.5
    assert metrics["attention_gain_weight_total"] == 1.75
    assert metrics["attention_gain_floor"] == 0.52
    assert metrics["attention_suppression_floor"] == 0.36
    assert metrics["attention_suppression_min_ratio"] == 0.25
    assert metrics["attention_gain_possible"] == 1
    assert metrics["attention_unallocated_budget"] == 7.0


def test_extract_tick_metrics_exports_readable_top_display_with_raw_audit_copy():
    report = {
        "trace_id": "trace_readable_top_display",
        "tick_id": "cycle_readable_top_display_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {
            "state_snapshot": {
                "summary": {"active_item_count": 1},
                "er_top_items": [
                    {
                        "item_id": "spi_1",
                        "ref_object_id": "st_1",
                        "ref_object_type": "st",
                        "display": "{明 + 白 + 先 + 按}",
                        "er": 3.0,
                        "ev": 0.2,
                    }
                ],
            },
            "state_energy_summary": {},
            "hdb_snapshot": {"summary": {}},
        },
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 1, "input_text": "", "input_is_empty": True})

    assert metrics["pool_er_top5"][0]["display"] == "{明 白 先 按}"
    assert metrics["pool_er_top5"][0]["raw_display"] == "{明 + 白 + 先 + 按}"
    assert metrics["pool_er_top1_display"] == "{明 白 先 按}"


def test_extract_tick_metrics_exposes_pool_total_energy_and_cs_success_count():
    report = {
        "trace_id": "trace_pool_energy_cs_success",
        "tick_id": "cycle_pool_energy_cs_success_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {
            "state_snapshot": {"summary": {"active_item_count": 3}},
            "state_energy_summary": {
                "total_er": 2.5,
                "total_ev": 1.25,
                "total_energy": 3.75,
                "total_cp": 0.5,
            },
            "hdb_snapshot": {"summary": {}},
        },
        "attention": {
            "attention_gain_budget_applied": 0.0,
            "attention_suppressed_total_energy": 0.2,
            "attention_net_delta_energy": -0.2,
            "attention_energy_resource": {
                "budget": 10.0,
                "gain_weight_total": 0.0,
            },
        },
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "cognitive_stitching": {
            "enabled": True,
            "candidate_count": 4,
            "action_count": 3,
            "success_count": 3,
            "concat_count": 2,
        },
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 1, "input_text": "", "input_is_empty": True})

    assert metrics["pool_total_er"] == 2.5
    assert metrics["pool_total_ev"] == 1.25
    assert metrics["pool_total_energy"] == 3.75
    assert metrics["cs_action_count"] == 3
    assert metrics["cs_success_count"] == 3
    assert metrics["attention_gain_possible"] == 0
    assert metrics["attention_unallocated_budget"] == 10.0


def test_extract_tick_metrics_flattens_iesm_selector_cache_audit():
    report = {
        "trace_id": "trace_iesm_selector_cache",
        "tick_id": "cycle_iesm_selector_cache_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "innate_script": {
            "tick_rules": {
                "audit": {
                    "selector_cache_hit": 7,
                    "selector_cache_miss": 5,
                    "selector_cache_size": 5,
                }
            }
        },
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 1, "input_text": "", "input_is_empty": True})

    assert metrics["iesm_selector_cache_hit"] == 7
    assert metrics["iesm_selector_cache_miss"] == 5
    assert metrics["iesm_selector_cache_size"] == 5


def test_extract_tick_metrics_exposes_stimulus_cut_performance_counters():
    report = {
        "trace_id": "trace_stimulus_perf",
        "tick_id": "cycle_stimulus_perf_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {
            "result": {
                "metrics": {
                    "best_structure_match_candidate_count": 9,
                    "best_structure_match_pruned_count": 2,
                    "best_structure_match_common_part_count": 7,
                    "shadow_raw_residual_candidate_count": 5,
                    "shadow_raw_residual_candidate_pruned_count": 1,
                    "shadow_raw_residual_skipped_count": 4,
                    "shadow_raw_residual_common_part_count": 3,
                    "owner_local_residual_list_cache_hit_count": 17,
                    "owner_local_residual_index_build_count": 18,
                    "owner_local_residual_index_cache_hit_count": 19,
                    "owner_local_residual_raw_signature_hit_count": 20,
                    "owner_local_residual_common_signature_hit_count": 21,
                    "owner_local_residual_fuzzy_equivalent_call_count": 22,
                    "owner_local_residual_fuzzy_equivalent_cache_hit_count": 23,
                    "owner_local_residual_fuzzy_equivalent_signature_hit_count": 24,
                    "owner_local_residual_fuzzy_equivalent_fast_reject_count": 25,
                    "owner_local_residual_fuzzy_unit_bucket_pruned_count": 26,
                    "owner_local_residual_fuzzy_equivalent_cut_count": 27,
                    "maximum_common_part_exact_fast_path_hit_count": 6,
                    "maximum_common_part_full_inclusion_fast_path_hit_count": 7,
                    "maximum_common_part_single_group_fast_path_hit_count": 8,
                    "maximum_common_group_ordered_subsequence_fast_path_hit_count": 9,
                    "maximum_common_part_cache_hit_count": 4,
                    "maximum_common_part_cache_zero_copy_hit_count": 4,
                    "maximum_common_part_cache_store_count": 5,
                    "maximum_common_part_cache_deepcopy_count": 0,
                    "normalize_sequence_groups_cache_hit_count": 11,
                    "normalize_sequence_groups_reusable_hit_count": 12,
                    "normalize_sequence_groups_reusable_group_count": 13,
                    "sequence_groups_signature_fast_path_hit_count": 14,
                    "empty_group_from_normalized_template_fast_path_hit_count": 15,
                    "reindex_reusable_group_fast_path_hit_count": 16,
                }
            }
        },
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {
            "priority_summary": {
                "cut_metrics": {
                    "maximum_common_part_exact_fast_path_hit_count": 5,
                    "maximum_common_part_full_inclusion_fast_path_hit_count": 4,
                    "maximum_common_part_single_group_fast_path_hit_count": 3,
                    "maximum_common_group_ordered_subsequence_fast_path_hit_count": 2,
                    "maximum_common_part_cache_hit_count": 7,
                    "maximum_common_part_cache_zero_copy_hit_count": 7,
                    "maximum_common_part_cache_store_count": 8,
                    "maximum_common_part_cache_deepcopy_count": 0,
                    "normalize_sequence_groups_cache_hit_count": 9,
                    "normalize_sequence_groups_reusable_hit_count": 10,
                    "normalize_sequence_groups_reusable_group_count": 11,
                    "sequence_groups_signature_fast_path_hit_count": 12,
                    "empty_group_from_normalized_template_fast_path_hit_count": 13,
                    "reindex_reusable_group_fast_path_hit_count": 14,
                }
            }
        },
        "pool_apply": {},
        "induction": {
            "result": {
                "metrics": {
                    "maximum_common_part_exact_fast_path_hit_count": 2,
                    "maximum_common_part_full_inclusion_fast_path_hit_count": 1,
                    "maximum_common_part_single_group_fast_path_hit_count": 3,
                    "maximum_common_group_ordered_subsequence_fast_path_hit_count": 4,
                    "maximum_common_part_cache_hit_count": 3,
                    "maximum_common_part_cache_zero_copy_hit_count": 3,
                    "maximum_common_part_cache_store_count": 4,
                    "maximum_common_part_cache_deepcopy_count": 0,
                    "normalize_sequence_groups_cache_hit_count": 8,
                    "normalize_sequence_groups_reusable_hit_count": 9,
                    "normalize_sequence_groups_reusable_group_count": 10,
                    "sequence_groups_signature_fast_path_hit_count": 11,
                    "empty_group_from_normalized_template_fast_path_hit_count": 12,
                    "reindex_reusable_group_fast_path_hit_count": 13,
                    "induction_raw_residual_projection_profile_local_cache_hit_count": 14,
                    "induction_raw_residual_projection_profile_shared_cache_hit_count": 15,
                    "induction_raw_residual_projection_profile_cache_store_count": 16,
                    "induction_raw_residual_exact_candidates_local_cache_hit_count": 17,
                    "induction_raw_residual_exact_candidates_shared_cache_hit_count": 18,
                    "induction_raw_residual_exact_candidates_cache_store_count": 19,
                    "induction_raw_residual_component_candidates_local_cache_hit_count": 20,
                    "induction_raw_residual_component_candidates_shared_cache_hit_count": 21,
                    "induction_raw_residual_component_candidates_cache_store_count": 22,
                    "induction_full_inclusion_checks_shared_cache_hit_count": 23,
                    "induction_full_inclusion_shared_cache_store_count": 24,
                }
            }
        },
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 1, "input_text": "", "input_is_empty": True})

    assert metrics["stimulus_best_match_candidate_count"] == 9
    assert metrics["stimulus_best_match_pruned_count"] == 2
    assert metrics["stimulus_best_match_common_part_count"] == 7
    assert metrics["stimulus_shadow_raw_residual_candidate_count"] == 5
    assert metrics["stimulus_shadow_raw_residual_candidate_pruned_count"] == 1
    assert metrics["stimulus_shadow_raw_residual_skipped_count"] == 4
    assert metrics["stimulus_shadow_raw_residual_common_part_count"] == 3
    assert metrics["stimulus_owner_local_residual_list_cache_hit_count"] == 17
    assert metrics["stimulus_owner_local_residual_index_build_count"] == 18
    assert metrics["stimulus_owner_local_residual_index_cache_hit_count"] == 19
    assert metrics["stimulus_owner_local_residual_raw_signature_hit_count"] == 20
    assert metrics["stimulus_owner_local_residual_common_signature_hit_count"] == 21
    assert metrics["stimulus_owner_local_residual_fuzzy_equivalent_call_count"] == 22
    assert metrics["stimulus_owner_local_residual_fuzzy_equivalent_cache_hit_count"] == 23
    assert metrics["stimulus_owner_local_residual_fuzzy_equivalent_signature_hit_count"] == 24
    assert metrics["stimulus_owner_local_residual_fuzzy_equivalent_fast_reject_count"] == 25
    assert metrics["stimulus_owner_local_residual_fuzzy_unit_bucket_pruned_count"] == 26
    assert metrics["stimulus_owner_local_residual_fuzzy_equivalent_cut_count"] == 27
    assert metrics["stimulus_cut_common_part_total_count"] == 10
    assert metrics["stimulus_cut_exact_fast_path_hit_count"] == 6
    assert metrics["stimulus_cut_full_inclusion_fast_path_hit_count"] == 7
    assert metrics["stimulus_cut_single_group_fast_path_hit_count"] == 8
    assert metrics["stimulus_cut_ordered_subsequence_fast_path_hit_count"] == 9
    assert metrics["stimulus_cut_cache_hit_count"] == 4
    assert metrics["stimulus_cut_cache_zero_copy_hit_count"] == 4
    assert metrics["stimulus_cut_cache_store_count"] == 5
    assert metrics["stimulus_cut_cache_deepcopy_count"] == 0
    assert metrics["stimulus_cut_normalize_cache_hit_count"] == 11
    assert metrics["stimulus_cut_normalize_reusable_hit_count"] == 12
    assert metrics["stimulus_cut_normalize_reusable_group_count"] == 13
    assert metrics["stimulus_cut_signature_fast_path_hit_count"] == 14
    assert metrics["stimulus_cut_empty_group_fast_path_hit_count"] == 15
    assert metrics["stimulus_cut_reindex_fast_path_hit_count"] == 16
    assert metrics["cache_priority_cut_exact_fast_path_hit_count"] == 5
    assert metrics["cache_priority_cut_full_inclusion_fast_path_hit_count"] == 4
    assert metrics["cache_priority_cut_single_group_fast_path_hit_count"] == 3
    assert metrics["cache_priority_cut_ordered_subsequence_fast_path_hit_count"] == 2
    assert metrics["cache_priority_cut_cache_hit_count"] == 7
    assert metrics["cache_priority_cut_cache_zero_copy_hit_count"] == 7
    assert metrics["cache_priority_cut_cache_store_count"] == 8
    assert metrics["cache_priority_cut_cache_deepcopy_count"] == 0
    assert metrics["cache_priority_cut_normalize_cache_hit_count"] == 9
    assert metrics["cache_priority_cut_normalize_reusable_hit_count"] == 10
    assert metrics["cache_priority_cut_normalize_reusable_group_count"] == 11
    assert metrics["cache_priority_cut_signature_fast_path_hit_count"] == 12
    assert metrics["cache_priority_cut_empty_group_fast_path_hit_count"] == 13
    assert metrics["cache_priority_cut_reindex_fast_path_hit_count"] == 14
    assert metrics["induction_cut_exact_fast_path_hit_count"] == 2
    assert metrics["induction_cut_full_inclusion_fast_path_hit_count"] == 1
    assert metrics["induction_cut_single_group_fast_path_hit_count"] == 3
    assert metrics["induction_cut_ordered_subsequence_fast_path_hit_count"] == 4
    assert metrics["induction_cut_cache_hit_count"] == 3
    assert metrics["induction_cut_cache_zero_copy_hit_count"] == 3
    assert metrics["induction_cut_cache_store_count"] == 4
    assert metrics["induction_cut_cache_deepcopy_count"] == 0
    assert metrics["induction_cut_normalize_cache_hit_count"] == 8
    assert metrics["induction_cut_normalize_reusable_hit_count"] == 9
    assert metrics["induction_cut_normalize_reusable_group_count"] == 10
    assert metrics["induction_cut_signature_fast_path_hit_count"] == 11
    assert metrics["induction_cut_empty_group_fast_path_hit_count"] == 12
    assert metrics["induction_cut_reindex_fast_path_hit_count"] == 13
    assert metrics["induction_raw_residual_projection_profile_local_cache_hit_count"] == 14
    assert metrics["induction_raw_residual_projection_profile_shared_cache_hit_count"] == 15
    assert metrics["induction_raw_residual_projection_profile_cache_store_count"] == 16
    assert metrics["induction_raw_residual_exact_candidates_local_cache_hit_count"] == 17
    assert metrics["induction_raw_residual_exact_candidates_shared_cache_hit_count"] == 18
    assert metrics["induction_raw_residual_exact_candidates_cache_store_count"] == 19
    assert metrics["induction_raw_residual_component_candidates_local_cache_hit_count"] == 20
    assert metrics["induction_raw_residual_component_candidates_shared_cache_hit_count"] == 21
    assert metrics["induction_raw_residual_component_candidates_cache_store_count"] == 22
    assert metrics["induction_full_inclusion_shared_cache_hit_count"] == 23
    assert metrics["induction_full_inclusion_shared_cache_store_count"] == 24


def test_extract_tick_metrics_exposes_stimulus_transfer_vs_residual_balance():
    report = {
        "trace_id": "trace_stimulus_transfer_balance",
        "tick_id": "cycle_stimulus_transfer_balance_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {
            "result": {
                "runtime_projection_structures": [
                    {"reason": "goal_b_string_relation_seed", "er": 12.0, "ev": 0.0},
                    {"reason": "matched_structure", "er": 7.0, "ev": 3.0},
                    {"reason": "new_relation_structure", "er": 1.0, "ev": 0.0},
                ],
                "debug": {
                    "early_stop": {
                        "triggered": True,
                        "reason": "object_projection_dominates_remaining completed_rounds=8 projection_total=23 remaining_total=3 ratio=7.666667 threshold=1.25 memory_id_ready=True",
                        "object_projection_ratio_at_stop": 7.66666667,
                        "object_projection_total_at_stop": 23.0,
                        "remaining_total_at_stop": 3.0,
                        "object_projection_transfer_guard_blocked_count": 2,
                        "transfer_total_at_stop": 10.0,
                        "transfer_ratio_at_stop": 3.33333333,
                    },
                    "round_details": [
                        {
                            "selected_match": {"structure_id": "st_a"},
                            "transferred_er": 4.0,
                            "transferred_ev": 1.0,
                            "effective_transfer_fraction": 0.62,
                            "transfer_similarity": 0.44,
                            "remaining_total_er_after": 5.0,
                            "remaining_total_ev_after": 1.0,
                        },
                        {
                            "selected_match": {"structure_id": "st_b"},
                            "transferred_er": 3.0,
                            "transferred_ev": 2.0,
                            "effective_transfer_fraction": 0.78,
                            "transfer_similarity": 0.72,
                            "remaining_total_er_after": 2.0,
                            "remaining_total_ev_after": 1.0,
                        },
                    ]
                }
            }
        },
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {
            "residual_tail_memory_projection": {
                "handled": True,
                "memory": {"energy": {"er": 1.0, "ev": 0.5}},
            }
        },
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 1, "input_text": "", "input_is_empty": True})

    assert metrics["stimulus_transfer_round_count"] == 2
    assert metrics["stimulus_transfer_selected_round_count"] == 2
    assert metrics["stimulus_transfer_matched_er"] == 7.0
    assert metrics["stimulus_transfer_matched_ev"] == 3.0
    assert metrics["stimulus_transfer_matched_total"] == 10.0
    assert metrics["stimulus_final_residual_er"] == 2.0
    assert metrics["stimulus_final_residual_ev"] == 1.0
    assert metrics["stimulus_final_residual_total"] == 3.0
    assert metrics["stimulus_transfer_minus_residual_total"] == 7.0
    assert metrics["stimulus_transfer_to_residual_ratio"] == 3.33333333
    assert metrics["stimulus_transfer_share_of_matched_plus_residual"] == 0.76923077
    assert metrics["stimulus_transfer_dominates_residual"] == 1
    assert metrics["stimulus_effective_transfer_fraction_mean"] == 0.7
    assert metrics["stimulus_transfer_similarity_mean"] == 0.58
    assert metrics["stimulus_object_projection_count"] == 3
    assert metrics["stimulus_object_projection_total"] == 23.0
    assert metrics["stimulus_object_projection_seed_total"] == 12.0
    assert metrics["stimulus_object_projection_matched_total"] == 10.0
    assert metrics["stimulus_object_projection_relation_total"] == 1.0
    assert metrics["stimulus_memory_tail_absorbed_total"] == 1.5
    assert metrics["stimulus_unhandled_residual_er"] == 1.0
    assert metrics["stimulus_unhandled_residual_ev"] == 0.5
    assert metrics["stimulus_unhandled_residual_total"] == 1.5
    assert metrics["stimulus_object_projection_minus_unhandled_residual_total"] == 21.5
    assert metrics["stimulus_object_projection_to_unhandled_residual_ratio"] == 15.33333333
    assert metrics["stimulus_object_projection_dominates_unhandled_residual"] == 1
    assert metrics["stimulus_object_projection_dominates_raw_residual"] == 1
    assert metrics["stimulus_early_stop_triggered"] == 1
    assert metrics["stimulus_early_stop_object_projection_dominance_triggered"] == 1
    assert metrics["stimulus_early_stop_object_projection_dominance_ratio"] == 7.66666667
    assert metrics["stimulus_early_stop_object_projection_transfer_guard_blocked_count"] == 2
    assert metrics["stimulus_early_stop_object_projection_transfer_total_at_stop"] == 10.0
    assert metrics["stimulus_early_stop_object_projection_transfer_ratio_at_stop"] == 3.33333333
    assert metrics["stimulus_early_stop_object_projection_total_at_stop"] == 23.0
    assert metrics["stimulus_early_stop_remaining_total_at_stop"] == 3.0


def test_extract_tick_metrics_exposes_runtime_residual_promotion_fast_path_counters():
    report = {
        "trace_id": "trace_runtime_residual_fast_path",
        "tick_id": "cycle_runtime_residual_fast_path_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "runtime_residual_promotion": {
            "attempted_count": 3,
            "promoted_count": 3,
            "exact_rebind_count": 1,
            "full_identity_count": 1,
            "hdb_fallback_count": 1,
            "items": [
                {"promoted": True, "matched": True, "created": False, "fast_path": "exact_rebind"},
                {"promoted": True, "matched": False, "created": True, "fast_path": "full_identity"},
                {"promoted": True, "matched": False, "created": True, "hdb_fallback": True},
            ],
        },
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {"runtime_residual_promotion_ms": 7}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 1, "input_text": "", "input_is_empty": True})

    assert metrics["runtime_residual_promotion_attempted_count"] == 3
    assert metrics["runtime_residual_promotion_promoted_count"] == 3
    assert metrics["runtime_residual_promotion_exact_rebind_count"] == 1
    assert metrics["runtime_residual_promotion_full_identity_count"] == 1
    assert metrics["runtime_residual_promotion_hdb_fallback_count"] == 1
    assert metrics["runtime_residual_promotion_created_count"] == 2
    assert metrics["runtime_residual_promotion_matched_count"] == 1
    assert metrics["timing_runtime_residual_promotion_ms"] == 7


def test_extract_tick_metrics_distinguishes_action_attempts_and_successes():
    report = {
        "trace_id": "trace_demo",
        "tick_id": "cycle_0003",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "innate_script": {
            "focus": {
                "action_triggers": [
                    {
                        "action_kind": "weather_stub",
                        "rule_id": "innate_action_weather_stub_from_weather_only",
                        "params": {
                            "target_ref_object_id": "ctx_input_current",
                            "target_ref_object_type": "input",
                            "target_item_id": "ctx_input_current",
                            "target_display": "【用户消息】天气",
                        },
                    },
                    {"action_kind": "recall", "rule_id": "innate_action_recall_demo"},
                ],
                "triggered_rules": [
                    {"rule_id": "innate_action_weather_stub_from_weather_only"},
                    {"rule_id": "innate_action_recall_demo"},
                ],
                "triggered_scripts": [
                    {"script_id": "demo_script"},
                ],
            },
            "tick_rules": {
                "triggered_rule_count": 2,
                "action_trigger_count": 2,
            },
        },
        "emotion": {"nt_state_after": {}},
        "action": {
            "executed_actions": [
                {"action_kind": "recall", "success": False, "attempted": True},
                {"action_kind": "recall", "success": True},
                {"action_kind": "weather_stub", "success": True, "attempted": False},
                {"action_kind": "attention_focus", "success": True},
            ],
            "nodes": [],
        },
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 3, "input_text": "", "input_is_empty": True})

    assert metrics["action_attempted_count"] == 3
    assert metrics["action_attempted_count_source_visible"] == 3
    assert metrics["action_attempted_count_synthetic_only"] == 0
    assert metrics["action_attempted_recall"] == 2
    assert metrics["action_attempted_weather_stub"] == 0
    assert metrics["action_attempted_recall_source_visible"] == 2
    assert metrics["action_attempted_recall_synthetic_only"] == 0
    assert metrics["action_scheduled_weather_stub"] == 1
    assert metrics["action_scheduled_weather_stub_source_visible"] == 1
    assert metrics["action_scheduled_weather_stub_synthetic_only"] == 0
    assert metrics["iesm_triggered_rule_count"] == 2
    assert metrics["iesm_triggered_rule_count_source_visible"] == 2
    assert metrics["iesm_triggered_rule_count_synthetic_only"] == 0
    assert metrics["iesm_triggered_script_count"] == 1
    assert metrics["iesm_action_trigger_count"] == 2
    assert metrics["iesm_action_trigger_count_source_visible"] == 2
    assert metrics["iesm_action_trigger_count_synthetic_only"] == 0
    assert metrics["iesm_action_trigger_targeted_count"] == 1
    assert metrics["iesm_action_trigger_targeted_count_source_visible"] == 1
    assert metrics["iesm_action_trigger_target_missing_count"] == 1
    assert metrics["iesm_action_trigger_weather_stub_count"] == 1
    assert metrics["iesm_action_trigger_weather_stub_count_source_visible"] == 1
    assert metrics["iesm_action_trigger_targeted_weather_stub_count"] == 1
    assert metrics["iesm_action_trigger_target_missing_weather_stub_count"] == 0
    assert metrics["iesm_triggered_rule_innate_action_weather_stub_from_weather_only_count"] == 1
    assert metrics["action_executed_count"] == 3
    assert metrics["action_executed_count_source_visible"] == 3
    assert metrics["action_executed_count_synthetic_only"] == 0
    assert metrics["action_executed_recall"] == 1
    assert metrics["action_executed_weather_stub"] == 1
    assert metrics["action_executed_weather_stub_source_visible"] == 1
    assert metrics["action_executed_weather_stub_synthetic_only"] == 0
    assert metrics["action_executed_attention_focus"] == 1


def test_extract_tick_metrics_exposes_local_zero_signal_hits_by_action_kind():
    report = {
        "trace_id": "trace_local_zero_signal",
        "tick_id": "cycle_local_zero_signal_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {
            "executed_actions": [],
            "nodes": [
                {
                    "action_id": "weather_stub",
                    "action_kind": "weather_stub",
                    "drive": 0.2,
                    "threshold": 0.6,
                    "target_ref_object_id": "ctx_input_current",
                    "target_item_id": "ctx_input_current",
                    "local_drive_modulation": {
                        "lookup_status": "hit",
                        "lookup_mode": "text_fallback",
                        "reward": 0.0,
                        "punish": 0.0,
                        "reward_bonus_gain": 0.0,
                        "punish_penalty_gain": 0.0,
                        "scale_clamped": 1.0,
                    },
                },
                {
                    "action_id": "attention_focus_st_demo",
                    "action_kind": "attention_focus",
                    "drive": 0.4,
                    "threshold": 0.3,
                    "target_ref_object_id": "st_demo",
                    "local_drive_modulation": {
                        "lookup_status": "hit",
                        "lookup_mode": "direct_ref",
                        "reward": 0.0,
                        "punish": 0.55,
                        "reward_bonus_gain": 0.0,
                        "punish_penalty_gain": 0.1,
                        "scale_clamped": 0.7,
                        "applied": True,
                    },
                },
            ],
        },
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 1, "input_text": "天气", "input_is_empty": False})

    assert metrics["action_local_zero_signal_hit_count"] == 1
    assert metrics["action_local_text_fallback_zero_signal_hit_count"] == 1
    assert metrics["action_local_zero_signal_hit_count_weather_stub"] == 1
    assert metrics["action_local_text_fallback_zero_signal_hit_count_weather_stub"] == 1
    assert metrics["action_local_punish_signal_total_attention_focus"] == 0.55
    assert metrics["action_local_punish_drive_penalty_total_attention_focus"] == 0.1
    assert metrics["action_local_punish_drive_penalty_total_weather_stub"] == 0.0


def test_extract_tick_metrics_exposes_cs_concat_count():
    report = {
        "trace_id": "trace_cs_concat",
        "tick_id": "cycle_cs_concat_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "cognitive_stitching": {
            "enabled": True,
            "candidate_count": 3,
            "action_count": 2,
            "concat_count": 2,
            "created_count": 0,
            "extended_count": 0,
            "merged_count": 0,
            "reinforced_count": 0,
            "pair_fatigue_state_size": 4,
            "object_stitch_fatigue_state_size": 7,
            "event_grasp": {},
            "narrative_top_items": [],
            "candidate_audit": {},
            "action_log": [
                {
                    "action": "concat_context_structure",
                    "action_family": "concat_context_structure",
                    "object_stitch_fatigue_before": 0.0,
                    "object_stitch_fatigue_scale": 1.0,
                },
                {
                    "action": "reinforce_concat_context_structure",
                    "action_family": "concat_context_structure",
                    "object_stitch_fatigue_before": 0.85,
                    "object_stitch_fatigue_scale": 0.72181818,
                },
            ],
        },
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 9, "input_text": "", "input_is_empty": True})

    assert metrics["cs_candidate_count"] == 3
    assert metrics["cs_action_count"] == 2
    assert metrics["cs_concat_count"] == 2
    assert metrics["cs_created_count"] == 0
    assert metrics["cs_pair_fatigue_state_size"] == 4
    assert metrics["cs_object_stitch_fatigue_state_size"] == 7
    assert metrics["cs_action_object_stitch_fatigue_hit_count"] == 1
    assert metrics["cs_action_object_stitch_fatigue_before_mean"] == 0.425
    assert metrics["cs_action_object_stitch_fatigue_scale_mean"] == 0.86090909


def test_extract_tick_metrics_splits_synthetic_only_action_visibility():
    report = {
        "trace_id": "trace_synth",
        "tick_id": "cycle_synth_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "innate_script": {
            "focus": {
                "action_triggers": [
                    {
                        "action_kind": "weather_stub",
                        "rule_id": "innate_action_weather_stub_from_query_weather",
                        "target_ref_object_id": "ctx_input_current",
                        "target_ref_object_type": "input",
                        "target_item_id": "ctx_input_current",
                        "target_display": "【用户消息】查天气",
                    },
                    {"action_kind": "weather_stub", "rule_id": "innate_action_weather_stub_from_weather_only"},
                ],
                "triggered_rules": [
                    {"rule_id": "innate_action_weather_stub_from_query_weather"},
                    {"rule_id": "innate_action_weather_stub_from_weather_only"},
                ],
                "triggered_scripts": [],
            },
            "tick_rules": {
                "triggered_rule_count": 2,
                "action_trigger_count": 2,
            },
        },
        "emotion": {"nt_state_after": {}},
        "action": {
            "executed_actions": [
                {"action_kind": "weather_stub", "success": True},
                {"action_kind": "weather_stub", "success": False},
                {"action_kind": "recall", "success": True, "attempted": True},
            ],
            "nodes": [],
        },
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(
        report=report,
        dataset_tick={
            "tick_index": 7,
            "input_text": "synthetic",
            "input_is_empty": False,
            "tick_source": "expectation_contract_feedback",
            "synthetic_tick": True,
            "source_dataset_tick_index": 3,
        },
    )

    assert metrics["synthetic_tick"] is True
    assert metrics["action_attempted_count"] == 3
    assert metrics["action_attempted_count_source_visible"] == 0
    assert metrics["action_attempted_count_synthetic_only"] == 3
    assert metrics["iesm_triggered_rule_count"] == 2
    assert metrics["iesm_triggered_rule_count_source_visible"] == 0
    assert metrics["iesm_triggered_rule_count_synthetic_only"] == 2
    assert metrics["iesm_action_trigger_count"] == 2
    assert metrics["iesm_action_trigger_count_source_visible"] == 0
    assert metrics["iesm_action_trigger_count_synthetic_only"] == 2
    assert metrics["iesm_action_trigger_targeted_count"] == 1
    assert metrics["iesm_action_trigger_targeted_count_source_visible"] == 0
    assert metrics["iesm_action_trigger_targeted_count_synthetic_only"] == 1
    assert metrics["iesm_action_trigger_target_missing_count"] == 1
    assert metrics["iesm_action_trigger_target_missing_count_synthetic_only"] == 1
    assert metrics["iesm_action_trigger_weather_stub_count"] == 2
    assert metrics["iesm_action_trigger_weather_stub_count_source_visible"] == 0
    assert metrics["iesm_action_trigger_weather_stub_count_synthetic_only"] == 2
    assert metrics["iesm_action_trigger_targeted_weather_stub_count"] == 1
    assert metrics["iesm_action_trigger_targeted_weather_stub_count_synthetic_only"] == 1
    assert metrics["iesm_action_trigger_target_missing_weather_stub_count"] == 1
    assert metrics["iesm_action_trigger_target_missing_weather_stub_count_synthetic_only"] == 1
    assert metrics["iesm_triggered_rule_innate_action_weather_stub_from_query_weather_count"] == 1
    assert metrics["iesm_triggered_rule_innate_action_weather_stub_from_query_weather_count_synthetic_only"] == 1
    assert metrics["iesm_triggered_rule_innate_action_weather_stub_from_weather_only_count"] == 1
    assert metrics["iesm_triggered_rule_innate_action_weather_stub_from_weather_only_count_synthetic_only"] == 1
    assert metrics["action_executed_count"] == 2
    assert metrics["action_executed_count_source_visible"] == 0
    assert metrics["action_executed_count_synthetic_only"] == 2
    assert metrics["action_executed_weather_stub"] == 1
    assert metrics["action_executed_weather_stub_source_visible"] == 0
    assert metrics["action_executed_weather_stub_synthetic_only"] == 1
    assert metrics["action_attempted_weather_stub_source_visible"] == 0
    assert metrics["action_attempted_weather_stub_synthetic_only"] == 2


def test_extract_tick_metrics_flattens_iesm_emotion_updates() -> None:
    report = {
        "trace_id": "trace_iesm_emotion_updates",
        "tick_id": "cycle_iesm_emotion_updates_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "innate_script": {
            "focus": {
                "emotion_updates": {
                    "DA": 0.2,
                    "皮质醇（COR）": -0.1,
                    "新颖探索": 0.05,
                },
                "action_triggers": [],
                "triggered_rules": [],
                "triggered_scripts": [],
            },
            "tick_rules": {
                "emotion_update_key_count": 3,
            },
        },
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(
        report=report,
        dataset_tick={"tick_index": 9, "input_text": "", "input_is_empty": True},
    )

    assert metrics["iesm_emotion_update_key_count"] == 3
    assert metrics["iesm_emotion_update_key_count_source_visible"] == 3
    assert metrics["iesm_emotion_update_key_count_synthetic_only"] == 0
    assert metrics["iesm_emotion_update_abs_total"] == 0.35
    assert metrics["iesm_emotion_update_abs_total_source_visible"] == 0.35
    assert metrics["iesm_emotion_update_abs_total_synthetic_only"] == 0.0
    assert metrics["iesm_emotion_update_DA"] == 0.2
    assert metrics["iesm_emotion_update_COR"] == -0.1
    assert metrics["iesm_emotion_update_NOV"] == 0.05
    assert metrics["iesm_emotion_update_ADR"] == 0.0
    assert metrics["iesm_emotion_update_FOC"] == 0.0


def test_extract_tick_metrics_prefers_live_report_input_for_empty_flag() -> None:
    report = {
        "trace_id": "trace_live_input",
        "tick_id": "cycle_live_input_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {"input_text": "实时输入仍然存在"},
        "input_queue": {
            "submitted_text": "新输入",
            "source_text": "新输入",
            "tick_text": "实时输入仍然存在",
            "queued_from_new_input_count": 1,
            "pending_count_before_enqueue": 1,
            "pending_count_before_dequeue": 2,
            "pending_count_after_dequeue": 1,
        },
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(
        report=report,
        dataset_tick={"tick_index": 8, "input_text": "", "input_is_empty": True},
    )

    assert metrics["input_is_empty"] is False
    assert metrics["input_len"] > 0
    assert "实时输入" in metrics["input_text_preview"]
    assert metrics["input_queue_tick_submitted_mismatch_count"] == 1
    assert metrics["input_queue_deferred_chunk_consumed_count"] == 1
    assert metrics["input_queue_pending_count_before_dequeue"] == 2


def test_extract_tick_metrics_flattens_induction_energy_graph_v2_metrics() -> None:
    report = {
        "trace_id": "trace_induction_energy_graph_v2",
        "tick_id": "cycle_induction_energy_graph_v2_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {
            "result": {
                "total_delta_ev": 1.8,
                "total_ev_consumed": 0.28,
                "propagated_budget_total_ev": 1.12,
                "energy_graph_v2_enabled": True,
                "energy_graph_config_max_rounds": 4,
                "energy_graph_round_count_max": 3,
                "energy_graph_depth_max": 2,
                "energy_graph_frontier_generated_count": 4,
                "energy_graph_frontier_pruned_count": 1,
                "energy_graph_terminal_memory_count": 2,
                "energy_graph_root_reinduction_count": 3,
                "energy_graph_layer_histogram": {"1": 3, "2": 1},
                "energy_graph_round_summaries": [
                    {
                        "round_index": 1,
                        "frontier_in_count": 1,
                        "frontier_out_count": 2,
                        "frontier_pruned_count": 0,
                        "frontier_memory_terminal_count": 0,
                        "root_reinduction_count": 1,
                        "frontier_budget_ev": 0.28,
                        "root_induction_budget_ev": 0.44,
                        "round_delta_ev": 0.72,
                    },
                    {
                        "round_index": 2,
                        "frontier_in_count": 2,
                        "frontier_out_count": 1,
                        "frontier_pruned_count": 1,
                        "frontier_memory_terminal_count": 1,
                        "root_reinduction_count": 1,
                        "frontier_budget_ev": 0.56,
                        "root_induction_budget_ev": 0.20,
                        "round_delta_ev": 0.76,
                    },
                    {
                        "round_index": 3,
                        "frontier_in_count": 1,
                        "frontier_out_count": 0,
                        "frontier_pruned_count": 0,
                        "frontier_memory_terminal_count": 1,
                        "root_reinduction_count": 1,
                        "frontier_budget_ev": 0.28,
                        "root_induction_budget_ev": 0.04,
                        "round_delta_ev": 0.32,
                    },
                ],
                "induction_targets": [
                    {
                        "projection_kind": "structure",
                        "target_structure_id": "st_ab",
                        "delta_ev": 1.12,
                        "raw_residual_structure_delta_ev": 1.12,
                    },
                    {
                        "projection_kind": "memory",
                        "memory_id": "em_001",
                        "target_structure_id": "st_abc",
                        "delta_ev": 0.68,
                        "raw_residual_memory_delta_ev": 0.68,
                    },
                ],
            }
        },
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(
        report=report,
        dataset_tick={"tick_index": 9, "input_text": "", "input_is_empty": True},
    )

    assert metrics["induction_energy_graph_v2_enabled"] == 1
    assert metrics["induction_energy_graph_config_max_rounds"] == 4
    assert metrics["induction_total_ev_consumed"] == 0.28
    assert metrics["induction_propagated_budget_total_ev"] == 1.12
    assert metrics["induction_propagated_ev_total"] == 1.12
    assert metrics["induction_ev_from_er_total"] == 0.68
    assert metrics["induction_energy_graph_round_count_max"] == 3
    assert metrics["induction_energy_graph_depth_max"] == 2
    assert metrics["induction_energy_graph_frontier_generated_count"] == 4
    assert metrics["induction_energy_graph_frontier_pruned_count"] == 1
    assert metrics["induction_energy_graph_terminal_memory_count"] == 2
    assert metrics["induction_energy_graph_root_reinduction_count"] == 3
    assert metrics["induction_energy_graph_layer_count"] == 2
    assert metrics["induction_energy_graph_layer_max_width"] == 3
    assert metrics["induction_energy_graph_layer_total_nodes"] == 4
    assert metrics["induction_energy_graph_round_summary_count"] == 3
    assert metrics["induction_energy_graph_frontier_budget_total_ev"] == 1.12
    assert metrics["induction_energy_graph_root_induction_budget_total_ev"] == 0.68
    assert metrics["induction_energy_graph_round_delta_ev_total"] == 1.8
    assert metrics["induction_energy_graph_round_delta_ev_max"] == 0.76
    assert metrics["induction_energy_graph_round_delta_ev_last"] == 0.32
    assert metrics["induction_energy_graph_frontier_in_count_max"] == 2
    assert metrics["induction_energy_graph_frontier_out_count_max"] == 2


def test_extract_tick_metrics_flattens_action_drive_by_kind():
    report = {
        "trace_id": "trace_action_drive_kind",
        "tick_id": "cycle_action_drive_kind_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}, "rwd_pun_snapshot": {}},
        "action": {
            "executed_actions": [],
            "nodes": [
                {"action_kind": "weather_stub", "drive": 0.42, "effective_threshold": 0.60},
                {"action_kind": "weather_stub", "drive": 0.82, "effective_threshold": 0.70},
                {"action_kind": "recall", "drive": 0.33, "effective_threshold": 0.20},
            ],
        },
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 5, "input_text": "", "input_is_empty": True})

    assert metrics["action_node_weather_stub_count"] == 2
    assert metrics["action_active_weather_stub_count"] == 2
    assert metrics["action_ready_weather_stub_count"] == 1
    assert metrics["action_drive_weather_stub_max"] == 0.82
    assert metrics["action_drive_weather_stub_mean"] == 0.62
    assert metrics["action_effective_threshold_weather_stub_mean"] == 0.65
    assert metrics["action_drive_margin_weather_stub_max"] == 0.12
    assert metrics["action_drive_margin_weather_stub_mean"] == -0.03


def test_extract_tick_metrics_exposes_action_threshold_modulation_breakdown():
    report = {
        "trace_id": "trace_action_threshold_breakdown",
        "tick_id": "cycle_action_threshold_breakdown_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}, "rwd_pun_snapshot": {"rwd": 0.9, "pun": 0.2}},
        "action": {
            "executed_actions": [],
            "nodes": [
                {
                    "action_kind": "weather_stub",
                    "drive": 0.80,
                    "base_threshold": 0.70,
                    "threshold_scale": 0.90,
                    "effective_threshold": 0.63,
                    "target_ref_object_id": "st_demo_a",
                    "target_ref_object_type": "st",
                    "target_display": "示例A",
                    "local_drive_modulation": {
                        "lookup_status": "hit",
                        "lookup_hit": True,
                        "lookup_mode": "text_fallback",
                        "applied": True,
                        "scale_clamped": 1.18,
                        "reward_bonus_gain": 0.07,
                        "punish_penalty_gain": 0.0,
                    },
                    "threshold_components": {
                        "nt_scale_clamped": 0.95,
                        "rwd_pun_scale_clamped": 0.90,
                        "fatigue_scale": 1.05,
                        "threshold_delta": -0.07,
                        "rwd_pun_enabled": True,
                        "rwd_pun_reward_threshold_delta": -0.09,
                        "rwd_pun_punish_threshold_delta": 0.0,
                    },
                },
                {
                    "action_kind": "recall",
                    "drive": 0.40,
                    "base_threshold": 0.50,
                    "threshold_scale": 1.20,
                    "effective_threshold": 0.60,
                    "target_ref_object_id": "st_demo_b",
                    "target_ref_object_type": "st",
                    "target_display": "示例B",
                    "local_drive_modulation": {
                        "lookup_status": "hit",
                        "lookup_hit": True,
                        "applied": True,
                        "scale_clamped": 0.74,
                        "reward_bonus_gain": 0.0,
                        "punish_penalty_gain": 0.05,
                    },
                    "threshold_components": {
                        "nt_scale_clamped": 1.10,
                        "rwd_pun_scale_clamped": 1.08,
                        "fatigue_scale": 1.01,
                        "threshold_delta": 0.10,
                        "rwd_pun_enabled": True,
                        "rwd_pun_reward_threshold_delta": 0.0,
                        "rwd_pun_punish_threshold_delta": 0.05,
                    },
                },
            ],
        },
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 6, "input_text": "", "input_is_empty": True})

    assert metrics["action_base_threshold_mean"] == 0.6
    assert metrics["action_effective_threshold_mean"] == 0.615
    assert metrics["action_threshold_scale_mean"] == 1.05
    assert metrics["action_threshold_nt_scale_mean"] == 1.025
    assert metrics["action_threshold_rwd_pun_scale_mean"] == 0.99
    assert metrics["action_threshold_fatigue_scale_mean"] == 1.03
    assert metrics["action_threshold_rwd_pun_enabled_node_count"] == 2
    assert metrics["action_learning_threshold_delta_mean"] == 0.015
    assert metrics["action_learning_threshold_delta_sum"] == 0.03
    assert metrics["action_learning_reward_drive_gain_total"] == 0.09
    assert metrics["action_learning_punish_drive_penalty_total"] == 0.05
    assert metrics["action_local_targeted_node_count"] == 2
    assert metrics["action_local_lookup_hit_count"] == 2
    assert metrics["action_local_lookup_text_fallback_hit_count"] == 1
    assert metrics["action_local_lookup_miss_count"] == 0
    assert metrics["action_local_lookup_skipped_count"] == 0
    assert metrics["action_local_target_missing_count"] == 0
    assert metrics["action_local_modulation_disabled_count"] == 0
    assert metrics["action_local_drive_modulated_node_count"] == 2
    assert metrics["action_local_drive_scale_mean"] == 0.96
    assert metrics["action_local_reward_drive_bonus_total"] == 0.07
    assert metrics["action_local_punish_drive_penalty_total"] == 0.05
    assert metrics["action_local_targeted_node_count_weather_stub"] == 1
    assert metrics["action_local_lookup_hit_count_weather_stub"] == 1
    assert metrics["action_local_lookup_text_fallback_hit_count_weather_stub"] == 1
    assert metrics["action_local_lookup_miss_count_weather_stub"] == 0
    assert metrics["action_local_lookup_skipped_count_weather_stub"] == 0
    assert metrics["action_local_target_missing_count_weather_stub"] == 0
    assert metrics["action_local_modulation_disabled_count_weather_stub"] == 0
    assert metrics["action_local_drive_modulated_node_count_weather_stub"] == 1
    assert metrics["action_local_drive_scale_mean_weather_stub"] == 1.18
    assert metrics["action_local_reward_drive_bonus_total_weather_stub"] == 0.07
    assert metrics["action_local_punish_drive_penalty_total_weather_stub"] == 0.0
    assert metrics["action_local_targeted_node_count_recall"] == 1
    assert metrics["action_local_lookup_hit_count_recall"] == 1
    assert metrics["action_local_lookup_text_fallback_hit_count_recall"] == 0
    assert metrics["action_local_lookup_miss_count_recall"] == 0
    assert metrics["action_local_lookup_skipped_count_recall"] == 0
    assert metrics["action_local_target_missing_count_recall"] == 0
    assert metrics["action_local_modulation_disabled_count_recall"] == 0
    assert metrics["action_local_drive_modulated_node_count_recall"] == 1
    assert metrics["action_local_drive_scale_mean_recall"] == 0.74
    assert metrics["action_local_reward_drive_bonus_total_recall"] == 0.0
    assert metrics["action_local_punish_drive_penalty_total_recall"] == 0.05


def test_extract_tick_metrics_distinguishes_local_lookup_miss_vs_skipped():
    report = {
        "trace_id": "trace_action_local_lookup_status",
        "tick_id": "cycle_action_local_lookup_status_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}, "rwd_pun_snapshot": {}},
        "action": {
            "executed_actions": [],
            "nodes": [
                {
                    "action_kind": "weather_stub",
                    "drive": 0.5,
                    "effective_threshold": 0.7,
                    "target_ref_object_id": "st_demo_miss",
                    "local_drive_modulation": {
                        "lookup_status": "miss",
                        "lookup_hit": False,
                        "detail": {"reason": "local_feedback_not_found"},
                    },
                },
                {
                    "action_kind": "recall",
                    "drive": 0.3,
                    "effective_threshold": 0.6,
                    "target_ref_object_id": "st_demo_disabled",
                    "local_drive_modulation": {
                        "lookup_status": "skipped",
                        "lookup_hit": False,
                        "detail": {"reason": "node_disabled"},
                    },
                },
                {
                    "action_kind": "attention_focus",
                    "drive": 0.1,
                    "effective_threshold": 0.4,
                    "local_drive_modulation": {
                        "lookup_status": "skipped",
                        "lookup_hit": False,
                        "detail": {"reason": "target_required_but_missing"},
                    },
                },
            ],
        },
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 10, "input_text": "", "input_is_empty": True})

    assert metrics["action_local_targeted_node_count"] == 2
    assert metrics["action_local_lookup_hit_count"] == 0
    assert metrics["action_local_lookup_text_fallback_hit_count"] == 0
    assert metrics["action_local_lookup_miss_count"] == 1
    assert metrics["action_local_lookup_skipped_count"] == 2
    assert metrics["action_local_target_missing_count"] == 1
    assert metrics["action_local_modulation_disabled_count"] == 1
    assert metrics["action_local_lookup_miss_count_weather_stub"] == 1
    assert metrics["action_local_lookup_hit_count_weather_stub"] == 0
    assert metrics["action_local_lookup_text_fallback_hit_count_weather_stub"] == 0
    assert metrics["action_local_targeted_node_count_weather_stub"] == 1
    assert metrics["action_local_target_missing_count_weather_stub"] == 0
    assert metrics["action_local_modulation_disabled_count_weather_stub"] == 0
    assert metrics["action_local_lookup_skipped_count_recall"] == 1
    assert metrics["action_local_lookup_text_fallback_hit_count_recall"] == 0
    assert metrics["action_local_modulation_disabled_count_recall"] == 1
    assert metrics["action_local_targeted_node_count_recall"] == 1
    assert metrics["action_local_lookup_skipped_count_attention_focus"] == 1
    assert metrics["action_local_target_missing_count_attention_focus"] == 1
    assert metrics["action_local_targeted_node_count_attention_focus"] == 0


def test_extract_tick_metrics_exposes_structure_synthetic_path_breakdown():
    report = {
        "trace_id": "trace_structure_paths",
        "tick_id": "cycle_structure_paths_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {
            "result": {
                "round_count": 2,
                "debug": {
                    "round_details": [
                        {
                            "candidate_groups": [],
                            "selected_group": {"group_kind": "implicit_single_st", "synthetic": True},
                        },
                        {
                            "candidate_groups": [
                                {
                                    "eligible": True,
                                    "competition_score_legacy": 0.41,
                                    "competition_score": 0.52,
                                    "v2_score": 0.57,
                                    "v2_base_score": 0.48,
                                    "v2_numeric_score": 0.91,
                                    "v2_order_alignment_score": 0.76,
                                    "v2_attribute_anchor_score": 0.63,
                                    "v2_context_support_score": 0.58,
                                    "v2_energy_profile_score": 0.69,
                                    "v2_structure_inclusion_score": 0.71,
                                    "v2_threshold_margin": 0.14,
                                }
                            ],
                            "selected_group": {"group_kind": "group", "synthetic": False},
                        },
                    ]
                },
            }
        },
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}, "rwd_pun_snapshot": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 9, "input_text": "", "input_is_empty": True})

    assert metrics["structure_round_count"] == 2
    assert metrics["structure_round_synthetic_count"] == 1
    assert metrics["structure_round_implicit_single_count"] == 1
    assert metrics["structure_round_competitive_count"] == 1
    assert metrics["structure_round_synthetic_ratio"] == 0.5
    assert metrics["structure_round_competitive_ratio"] == 0.5
    assert metrics["structure_match_v2_candidate_count"] == 1
    assert metrics["structure_match_v2_numeric_score_mean"] == 0.91


def test_extract_tick_metrics_flattens_energy_balance_controller_fields():
    report = {
        "trace_id": "trace_energy_balance",
        "tick_id": "cycle_energy_balance_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "energy_balance": {
            "enabled": True,
            "updated": True,
            "window_ticks": 6,
            "target_ratio": 1.08,
            "ratio_raw": 0.42,
            "ratio_smooth": 0.57,
            "error_log": -0.64,
            "ki": 0.04,
            "g_before": 1.12,
            "g_after": 1.25,
            "min_total_energy_to_update": 0.5,
            "hdb_scales_out": {
                "ev_propagation_ratio_scale": 1.25,
                "er_induction_ratio_scale": 1.25,
            },
        },
        "modulation_applied": {
            "hdb": {
                "applied": {
                    "ev_propagation_ratio": {
                        "base": 0.28,
                        "scale": 5.0,
                        "effective": 1.4,
                        "runtime_effective": 1.0,
                        "runtime_clamped": True,
                    },
                    "er_induction_ratio": {
                        "base": 0.22,
                        "scale": 5.0,
                        "effective": 1.1,
                        "runtime_effective": 1.0,
                        "runtime_clamped": True,
                    },
                }
            }
        },
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 9, "input_text": "", "input_is_empty": True})

    assert metrics["energy_balance_enabled"] == 1
    assert metrics["energy_balance_updated"] == 1
    assert metrics["energy_balance_window_ticks"] == 6
    assert metrics["energy_balance_target_ratio"] == 1.08
    assert metrics["energy_balance_ratio_raw"] == 0.42
    assert metrics["energy_balance_ratio_smooth"] == 0.57
    assert metrics["energy_balance_error_log"] == -0.64
    assert metrics["energy_balance_ki"] == 0.04
    assert metrics["energy_balance_g_before"] == 1.12
    assert metrics["energy_balance_g_after"] == 1.25
    assert metrics["energy_balance_min_total_energy_to_update"] == 0.5
    assert metrics["energy_balance_hdb_scale_count"] == 2
    assert metrics["energy_balance_ev_propagation_ratio_scale"] == 1.25
    assert metrics["energy_balance_er_induction_ratio_scale"] == 1.25
    assert metrics["hdb_requested_ev_propagation_ratio"] == 1.4
    assert metrics["hdb_effective_ev_propagation_ratio"] == 1.0
    assert metrics["hdb_requested_er_induction_ratio"] == 1.1
    assert metrics["hdb_effective_er_induction_ratio"] == 1.0
    assert metrics["hdb_ev_propagation_ratio_clamped"] == 1
    assert metrics["hdb_er_induction_ratio_clamped"] == 1
    assert metrics["energy_balance_skipped_low_energy"] == 0
    assert metrics["energy_balance_skipped_disabled"] == 0


def test_extract_tick_metrics_flattens_context_and_residual_audit_fields():
    report = {
        "trace_id": "trace_context",
        "tick_id": "cycle_context_0001",
        "started_at": 10,
        "finished_at": 11,
        "sensor": {},
        "final_state": {
            "state_snapshot": {
                "summary": {
                    "active_item_count": 9,
                    "contextual_item_count": 4,
                    "explicit_context_item_count": 3,
                    "multi_context_item_count": 2,
                    "context_path_depth_mean": 1.75,
                    "explicit_context_path_depth_mean": 2.0,
                    "residual_origin_item_count": 3,
                }
            },
            "state_energy_summary": {
                "total_er": 10.0,
                "total_ev": 6.0,
            },
            "hdb_snapshot": {
                "summary": {
                    "contextual_structure_count": 5,
                    "multi_context_structure_count": 2,
                    "structure_context_path_depth_mean": 2.2,
                    "same_content_multi_context_count": 1,
                    "diff_entry_count": 12,
                    "contextual_diff_entry_count": 7,
                    "residual_diff_entry_count": 6,
                    "diff_entry_with_memory_ref_count": 4,
                }
            },
        },
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 1, "input_text": "", "input_is_empty": True})

    assert metrics["pool_contextual_item_count"] == 4
    assert metrics["pool_explicit_context_item_count"] == 3
    assert metrics["pool_multi_context_item_count"] == 2
    assert metrics["pool_context_path_depth_mean"] == 1.75
    assert metrics["pool_explicit_context_path_depth_mean"] == 2.0
    assert metrics["pool_residual_origin_item_count"] == 3
    assert metrics["pool_contextual_item_ratio"] == 0.44444444
    assert metrics["pool_explicit_context_item_ratio"] == 0.33333333
    assert metrics["pool_multi_context_item_ratio"] == 0.22222222
    assert metrics["pool_residual_origin_item_ratio"] == 0.33333333
    assert metrics["pool_ev_to_er_ratio"] == 0.6
    assert metrics["hdb_contextual_structure_count"] == 5
    assert metrics["hdb_same_content_multi_context_count"] == 1
    assert metrics["hdb_residual_diff_entry_count"] == 6
    assert metrics["hdb_diff_entry_with_memory_ref_count"] == 4
    assert metrics["hdb_contextual_structure_ratio"] == 1.0
    assert metrics["hdb_multi_context_structure_ratio"] == 0.4
    assert metrics["hdb_same_content_multi_context_ratio"] == 0.2
    assert metrics["hdb_contextual_diff_entry_ratio"] == 0.58333333
    assert metrics["hdb_residual_diff_entry_ratio"] == 0.5


def test_extract_tick_metrics_source_dataset_tick_index_falls_back_to_dataset_tick_index():
    report = {
        "trace_id": "trace_dataset_tick_fallback",
        "tick_id": "cycle_dataset_tick_fallback_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(
        report=report,
        dataset_tick={
            "tick_index": 17,
            "input_text": "demo",
            "input_is_empty": False,
        },
    )

    assert metrics["dataset_tick_index"] == 17
    assert metrics["source_dataset_tick_index"] == 17


def test_extract_tick_metrics_records_state_pool_er_ev_top5():
    report = {
        "trace_id": "trace_pool_energy_top5",
        "tick_id": "cycle_pool_energy_top5_0001",
        "started_at": 10,
        "finished_at": 11,
        "sensor": {},
        "final_state": {
            "state_snapshot": {
                "summary": {},
                "er_top_items": [
                    {"item_id": "spi_a", "ref_object_id": "sa_a", "ref_object_type": "sa", "display": "证据A", "er": 1.2, "ev": 0.1, "cp_abs": 1.1},
                    {"item_id": "spi_b", "ref_object_id": "sa_b", "ref_object_type": "sa", "display": "证据B", "er": 2.4, "ev": 0.2, "cp_abs": 2.2},
                ],
                "ev_top_items": [
                    {"item_id": "spi_x", "ref_object_id": "st_x", "ref_object_type": "st", "display": "预期X", "er": 0.0, "ev": 1.7, "cp_abs": 1.7},
                    {"item_id": "spi_y", "ref_object_id": "st_y", "ref_object_type": "st", "display": "预期Y", "er": 0.4, "ev": 3.1, "cp_abs": 2.7},
                ],
            },
            "state_energy_summary": {"total_er": 5.0, "total_ev": 4.0},
            "hdb_snapshot": {"summary": {}},
        },
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 1, "input_text": "天气", "input_is_empty": False})

    assert metrics["pool_er_top5_count"] == 2
    assert metrics["pool_ev_top5_count"] == 2
    assert [row["display"] for row in metrics["pool_er_top5"]] == ["证据B", "证据A"]
    assert [row["display"] for row in metrics["pool_ev_top5"]] == ["预期Y", "预期X"]
    assert metrics["pool_er_top1_display"] == "证据B"
    assert metrics["pool_er_top1_er"] == 2.4
    assert metrics["pool_ev_top1_display"] == "预期Y"
    assert metrics["pool_ev_top1_ev"] == 3.1
    assert "证据B" in metrics["pool_er_top5_text"]
    assert "预期Y" in metrics["pool_ev_top5_text"]


def test_extract_tick_metrics_records_attention_top5_and_anchor_about_text():
    report = {
        "trace_id": "trace_attention_top5",
        "tick_id": "cycle_attention_top5_0001",
        "started_at": 10,
        "finished_at": 11,
        "sensor": {},
        "final_state": {
            "state_snapshot": {"summary": {}},
            "state_energy_summary": {"total_er": 5.0, "total_ev": 4.0},
            "hdb_snapshot": {"summary": {}},
        },
        "attention": {
            "top_items": [
                {
                    "item_id": "cam_attr",
                    "ref_object_id": "sa_attr_1",
                    "ref_object_type": "sa",
                    "display": "违和感:0.7",
                    "anchor_display": "天气",
                    "role": "attribute",
                    "attribute_name": "cfs_dissonance",
                    "er": 0.0,
                    "ev": 0.7,
                    "attention_priority": 1.2,
                    "reward_action_bonus": -0.5,
                    "repeat_attention_penalty": 0.0,
                    "selected_by": "cutoff",
                },
                {
                    "item_id": "cam_struct",
                    "ref_object_id": "st_weather",
                    "ref_object_type": "st",
                    "display": "天气",
                    "target_display": "查天气",
                    "all_attribute_names": ["reward_signal"],
                    "er": 0.3,
                    "ev": 0.4,
                    "attention_priority": 1.8,
                    "reward_action_bonus": 0.6,
                    "repeat_attention_penalty": 0.2,
                    "selected_by": "cutoff",
                },
            ],
            "reward_action_structure_carrier_selected_count": 1,
            "reward_action_standalone_special_selected_count": 1,
            "repeat_attention_penalty_selected_count": 1,
            "repeat_attention_penalty_total": 0.2,
        },
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 1, "input_text": "天气", "input_is_empty": False})

    assert metrics["attention_top5_count"] == 2
    assert metrics["attention_top1_display"] == "天气"
    assert metrics["attention_top1_about"] == "查天气"
    assert metrics["attention_structure_carrier_selected_count"] == 1
    assert metrics["attention_standalone_special_selected_count"] == 1
    assert metrics["attention_repeat_penalty_selected_count"] == 1
    assert metrics["attention_repeat_penalty_total"] == 0.2
    assert metrics["attention_top5"][1]["about"] == "天气"
    assert "天气 <- 查天气" in metrics["attention_top5_text"]


def test_extract_tick_metrics_flattens_cognitive_stitching_candidate_audit():
    report = {
        "trace_id": "trace_cs_audit",
        "tick_id": "cycle_cs_audit_0001",
        "started_at": 20,
        "finished_at": 22,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "cognitive_stitching": {
            "enabled": True,
            "candidate_count": 3,
            "action_count": 1,
            "action_log": [
                {
                    "action": "concat_context_structure",
                    "action_family": "concat_context_structure",
                    "visible_text": "你好|ctx=你",
                    "context_text": "你",
                    "source_ref_id": "st_src",
                    "target_ref_id": "st_tgt",
                    "score": 0.41,
                    "v2_score": 0.57,
                    "context_ratio": 0.44,
                    "effective_match_units": 1.8,
                }
            ],
            "event_grasp": {
                "reason": "ok",
                "focus_mode": "cam_plus_post_cs_action",
                "selected_event_count": 2,
                "emitted_count": 1,
                "focus_candidate_item_count": 3,
                "cam_seed_count": 1,
                "post_action_seed_count": 2,
                "cam_selected_event_count": 0,
                "post_action_selected_event_count": 1,
            },
            "narrative_top_items": [
                {
                    "event_grasp": 0.41,
                    "total_energy": 1.86,
                    "narrative_kind": "concat_structure",
                }
            ],
            "candidate_audit": {
                "raw_accepted_count": 5,
                "deduped_candidate_count": 3,
                "deduped_pruned_count": 2,
                "rejected_count": 4,
                "replacement_count": 1,
                "kept_existing_count": 2,
                "rejected_reason_counts": {
                    "below_min_candidate_score": 2,
                    "below_v2_min_match_score": 1,
                    "component_count_exceeded": 1,
                    "non_positive_edge": 1,
                },
                "score_means": {
                    "score": 0.41,
                    "base_score": 0.58,
                    "edge_weight_ratio": 0.52,
                    "match_strength": 0.63,
                    "context_ratio": 0.44,
                    "energy_balance": 0.81,
                    "runtime_balance": 0.76,
                    "bridge_span_ratio": 0.36,
                    "anchor_scale": 0.88,
                    "fatigue_scale": 0.73,
                    "threshold_margin": 0.19,
                    "v2_score": 0.57,
                    "v2_base_score": 0.66,
                    "v2_threshold_margin": 0.39,
                    "v2_context_cover_score": 0.72,
                    "v2_order_alignment_score": 0.84,
                    "v2_tail_match_score": 0.61,
                    "v2_context_db_support_score": 0.53,
                    "v2_energy_profile_score": 0.77,
                },
            },
        },
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 1, "input_text": "", "input_is_empty": True})

    assert metrics["cs_candidate_count"] == 3
    assert metrics["cs_candidate_raw_accepted_count"] == 5
    assert metrics["cs_candidate_deduped_count"] == 3
    assert metrics["cs_candidate_deduped_pruned_count"] == 2
    assert metrics["cs_candidate_rejected_count"] == 4
    assert metrics["cs_candidate_rejected_low_score_count"] == 3
    assert metrics["cs_candidate_rejected_v2_low_score_count"] == 1
    assert metrics["cs_candidate_rejected_component_limit_count"] == 1
    assert metrics["cs_candidate_rejected_non_positive_edge_count"] == 1
    assert metrics["cs_candidate_replacement_count"] == 1
    assert metrics["cs_candidate_kept_existing_count"] == 2
    assert metrics["cs_event_grasp_reason"] == "ok"
    assert metrics["cs_event_grasp_focus_mode"] == "cam_plus_post_cs_action"
    assert metrics["cs_event_grasp_selected_event_count"] == 2
    assert metrics["cs_event_grasp_emitted_count"] == 1
    assert metrics["cs_event_grasp_focus_candidate_item_count"] == 3
    assert metrics["cs_event_grasp_cam_seed_count"] == 1
    assert metrics["cs_event_grasp_post_action_seed_count"] == 2
    assert metrics["cs_event_grasp_cam_selected_event_count"] == 0
    assert metrics["cs_event_grasp_post_action_selected_event_count"] == 1
    assert metrics["cs_narrative_top_grasp"] == 0.41
    assert metrics["cs_narrative_grasp_max"] == 0.41
    assert metrics["cs_narrative_grasp_positive_count"] == 1
    assert metrics["cs_narrative_top_total_energy"] == 1.86
    assert metrics["cs_concat_narrative_count"] == 1
    assert metrics["cs_action_log_count"] == 1
    assert metrics["cs_action_log_concat_count"] == 1
    assert metrics["cs_action_log_reinforce_concat_count"] == 0
    assert isinstance(metrics["cs_action_log"], list) and len(metrics["cs_action_log"]) == 1
    assert metrics["cs_candidate_score_mean"] == 0.41
    assert metrics["cs_candidate_base_score_mean"] == 0.58
    assert metrics["cs_candidate_edge_weight_ratio_mean"] == 0.52
    assert metrics["cs_candidate_match_strength_mean"] == 0.63
    assert metrics["cs_candidate_context_ratio_mean"] == 0.44
    assert metrics["cs_candidate_energy_balance_mean"] == 0.81
    assert metrics["cs_candidate_runtime_balance_mean"] == 0.76
    assert metrics["cs_candidate_bridge_span_ratio_mean"] == 0.36
    assert metrics["cs_candidate_anchor_scale_mean"] == 0.88
    assert metrics["cs_candidate_fatigue_scale_mean"] == 0.73
    assert metrics["cs_candidate_threshold_margin_mean"] == 0.19
    assert metrics["cs_candidate_v2_score_mean"] == 0.57
    assert metrics["cs_candidate_v2_base_score_mean"] == 0.66
    assert metrics["cs_candidate_v2_threshold_margin_mean"] == 0.39
    assert metrics["cs_candidate_v2_context_cover_mean"] == 0.72
    assert metrics["cs_candidate_v2_order_alignment_mean"] == 0.84
    assert metrics["cs_candidate_v2_tail_match_mean"] == 0.61
    assert metrics["cs_candidate_v2_context_db_support_mean"] == 0.53
    assert metrics["cs_candidate_v2_energy_profile_mean"] == 0.77


def test_extract_tick_metrics_distinguishes_concat_and_reinforce_action_log_counts():
    report = {
        "trace_id": "trace_cs_action_log_mix",
        "tick_id": "cycle_cs_action_log_mix_0001",
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "cognitive_stitching": {
            "enabled": True,
            "candidate_count": 0,
            "action_count": 2,
            "action_log": [
                {"action": "concat_context_structure", "action_family": "concat_context_structure"},
                {"action": "reinforce_concat_context_structure", "action_family": "concat_context_structure"},
            ],
            "event_grasp": {},
            "narrative_top_items": [],
            "candidate_audit": {},
        },
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 2, "input_text": "", "input_is_empty": True})

    assert metrics["cs_action_log_count"] == 2
    assert metrics["cs_action_log_concat_count"] == 1
    assert metrics["cs_action_log_reinforce_concat_count"] == 1


def test_extract_tick_metrics_collects_stimulus_and_structure_match_v2_metrics():
    report = {
        "trace_id": "trace_match_v2",
        "tick_id": "cycle_match_v2_0001",
        "started_at": 10,
        "finished_at": 20,
        "sensor": {},
        "final_state": {
            "state_snapshot": {"summary": {}},
            "state_energy_summary": {"total_er": 4.0, "total_ev": 2.0},
            "hdb_snapshot": {"summary": {}},
        },
        "attention": {},
        "maintenance": {},
        "structure_level": {
            "result": {
                "metrics": {
                    "best_match_score": 1.0,
                    "match_score_target_count": 1,
                    "best_match_target_id": "sg_single_st_030157",
                },
                "debug": {
                    "round_details": [
                        {
                            "candidate_groups": [
                                {
                                    "eligible": True,
                                    "competition_score": 0.66,
                                    "competition_score_legacy": 0.5,
                                    "v2_score": 0.72,
                                    "v2_base_score": 0.61,
                                    "v2_numeric_score": 0.81,
                                    "v2_order_alignment_score": 0.63,
                                    "v2_attribute_anchor_score": 0.74,
                                    "v2_context_support_score": 0.57,
                                    "v2_energy_profile_score": 0.69,
                                    "v2_structure_inclusion_score": 0.88,
                                    "v2_threshold_margin": 0.22,
                                }
                            ]
                        }
                    ]
                }
            }
        },
        "stimulus_level": {
            "result": {
                "metrics": {
                    "residual_ratio": 0.42,
                    "best_match_score": 0.73,
                    "grasp_score": 0.58,
                    "match_score_target_count": 2,
                    "best_match_target_id": "st_000001",
                },
                "debug": {
                    "round_details": [
                        {
                            "candidate_details": [
                                {
                                    "eligible": True,
                                    "competition_score": 0.73,
                                    "competition_score_legacy": 0.54,
                                    "v2_score": 0.79,
                                    "v2_base_score": 0.68,
                                    "v2_numeric_score": 0.83,
                                    "v2_order_alignment_score": 0.77,
                                    "v2_attribute_anchor_score": 0.71,
                                    "v2_context_support_score": 0.59,
                                    "v2_energy_profile_score": 0.64,
                                    "v2_structure_inclusion_score": 0.91,
                                    "v2_threshold_margin": 0.27,
                                },
                                {
                                    "eligible": False,
                                    "competition_score": 0.1,
                                    "competition_score_legacy": 0.1,
                                    "v2_score": 0.12,
                                },
                            ]
                        }
                    ]
                }
            }
        },
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "cognitive_stitching": {"enabled": False},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 1, "input_text": "", "input_is_empty": True})

    assert metrics["stimulus_match_v2_candidate_count"] == 2
    assert metrics["stimulus_match_v2_eligible_count"] == 1
    assert metrics["stimulus_match_v2_eligible_ratio"] == 0.5
    assert metrics["stimulus_match_v2_score_mean"] == 0.79
    assert metrics["stimulus_match_v2_numeric_score_mean"] == 0.83
    assert metrics["stimulus_match_v2_numeric_scored_count"] == 1
    assert metrics["stimulus_match_v2_numeric_scored_ratio"] == 1.0
    assert metrics["stimulus_match_v2_numeric_nonzero_count"] == 1
    assert metrics["stimulus_match_v2_numeric_nonzero_ratio"] == 1.0
    assert metrics["stimulus_match_v2_context_support_mean"] == 0.59
    assert metrics["stimulus_match_v2_threshold_margin_mean"] == 0.27
    assert metrics["stimulus_match_v2_blend_gain_mean"] == 0.19
    assert metrics["stimulus_match_v2_time_factor_bonus_applied_count"] == 0
    assert metrics["stimulus_match_v2_numeric_time_like_wildcard_applied_count"] == 0
    assert metrics["stimulus_match_v2_soft_partial_eligible_count"] == 0
    assert metrics["stimulus_match_v2_soft_partial_selected_count"] == 0
    assert metrics["stimulus_match_v2_bundle_exact_selected_count"] == 0
    assert metrics["stimulus_match_v2_exact_match_selected_count"] == 0
    assert metrics["stimulus_residual_ratio"] == 0.42
    assert metrics["stimulus_best_match_score"] == 0.73
    assert metrics["stimulus_grasp_score"] == 0.58
    assert metrics["grasp_score"] == 0.58
    assert metrics["stimulus_match_score_target_count"] == 2
    assert metrics["stimulus_best_match_target_id"] == "st_000001"

    assert metrics["structure_match_v2_candidate_count"] == 1
    assert metrics["structure_match_v2_eligible_count"] == 1
    assert metrics["structure_match_v2_score_mean"] == 0.72
    assert metrics["structure_match_v2_numeric_scored_count"] == 1
    assert metrics["structure_match_v2_numeric_scored_ratio"] == 1.0
    assert metrics["structure_match_v2_numeric_nonzero_count"] == 1
    assert metrics["structure_match_v2_numeric_nonzero_ratio"] == 1.0
    assert metrics["structure_match_v2_order_alignment_mean"] == 0.63
    assert metrics["structure_match_v2_attribute_anchor_mean"] == 0.74
    assert metrics["structure_match_v2_structure_inclusion_mean"] == 0.88
    assert metrics["structure_match_v2_blend_gain_mean"] == 0.16
    assert metrics["structure_match_v2_time_factor_bonus_applied_count"] == 0
    assert metrics["structure_best_match_score"] == 1.0
    assert metrics["structure_match_score_target_count"] == 1
    assert metrics["structure_best_match_target_id"] == "sg_single_st_030157"
    assert metrics["structure_match_v2_numeric_time_like_wildcard_applied_count"] == 0
    assert metrics["structure_match_v2_soft_partial_eligible_count"] == 0
    assert metrics["structure_match_v2_soft_partial_selected_count"] == 0
    assert metrics["structure_match_v2_bundle_exact_selected_count"] == 0
    assert metrics["structure_match_v2_exact_match_selected_count"] == 0


def test_extract_tick_metrics_flattens_induction_energy_semantics():
    report = {
        "trace_id": "trace_induction",
        "tick_id": "cycle_induction_0001",
        "started_at": 30,
        "finished_at": 35,
        "sensor": {},
        "final_state": {
            "state_snapshot": {"summary": {}},
            "state_energy_summary": {"total_er": 20.0, "total_ev": 12.0},
            "hdb_snapshot": {
                "summary": {},
                "stats": {
                    "pointer_index": {
                        "primary_pointer_count": 11,
                        "fallback_pointer_count": 2,
                        "signature_index_count": 7,
                        "recent_cache_count": 5,
                        "exact_lookup_cache_count": 3,
                        "numeric_bucket_family_count": 4,
                        "numeric_bucket_count": 9,
                    }
                },
            },
        },
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {
            "result": {
                "source_item_count": 4,
                "source_selection": {
                    "induction_source_available_st_count": 9,
                    "induction_source_selected_from_ev_count": 2,
                    "induction_source_selected_from_er_count": 2,
                    "induction_source_selected_from_cp_abs_count": 0,
                    "induction_source_max_items": 4,
                    "induction_source_candidate_top_k": 12,
                    "induction_source_ev_quota_ratio": 0.5,
                    "induction_source_ev_quota_count": 2,
                    "induction_source_selection_cap_hit": 1,
                },
                "raw_residual_entry_count": 5,
                "raw_residual_entry_with_existing_structure_count": 3,
                "raw_residual_entry_routed_to_structure_count": 2,
                "raw_residual_existing_structure_target_count": 2,
                "raw_residual_entry_materialized_structure_count": 2,
                "raw_residual_materialized_structure_target_count": 3,
                "raw_residual_entry_with_component_structure_count": 1,
                "raw_residual_entry_routed_to_component_structure_count": 1,
                "raw_residual_component_structure_target_count": 1,
                "raw_residual_structure_budget_weight": 2.0,
                "raw_residual_exact_structure_budget_weight": 1.1,
                "raw_residual_materialized_structure_budget_weight": 0.6,
                "raw_residual_component_structure_budget_weight": 0.9,
                "raw_residual_hit_memory_budget_weight": 0.9,
                "raw_residual_miss_memory_budget_weight": 0.7,
                "propagated_target_count": 6,
                "induced_target_count": 2,
                "total_delta_ev": 9.5,
                "total_ev_consumed": 6.0,
                "fallback_used": True,
                "growth_projection": {
                    "mode": "growth",
                    "raw_target_count": 4,
                    "projected_target_count": 3,
                    "growth_target_count": 3,
                    "growth_identity_hit_count": 2,
                    "growth_identity_created_count": 1,
                    "growth_identity_shared_cache_hit_count": 4,
                    "growth_identity_shared_cache_stale_count": 0,
                    "persistence_batch_enabled": True,
                    "target_apply_ref_fast_merge_enabled": True,
                    "target_apply_fast_ref_hit_merge_count": 2,
                    "target_apply_insert_log_enabled": False,
                    "target_apply_insert_log_suppressed_count": 3,
                    "growth_total_delta_er": 1.25,
                    "growth_total_delta_ev": 2.75,
                },
                "induction_targets": [
                    {"id": "a", "projection_kind": "structure", "delta_ev": 1.0, "raw_residual_structure_delta_ev": 0.8, "raw_residual_exact_structure_delta_ev": 0.8},
                    {"id": "b", "projection_kind": "structure", "delta_ev": 1.5, "raw_residual_structure_delta_ev": 1.2, "raw_residual_component_structure_delta_ev": 1.2},
                    {"id": "c", "projection_kind": "structure", "delta_ev": 1.0},
                    {"id": "d", "projection_kind": "structure", "delta_ev": 1.0},
                    {"id": "e", "projection_kind": "memory", "delta_ev": 1.5, "raw_residual_memory_delta_ev": 0.9, "raw_residual_hit_memory_delta_ev": 0.9},
                    {"id": "f", "projection_kind": "memory", "delta_ev": 1.0, "raw_residual_memory_delta_ev": 0.7, "raw_residual_miss_memory_delta_ev": 0.7},
                    {"id": "g", "projection_kind": "memory", "delta_ev": 1.0},
                    {"id": "h", "projection_kind": "memory", "delta_ev": 1.5},
                ],
            },
            "applied_targets": [
                {"ev": 2.0, "result": "运行态对象插入成功 / Runtime node inserted successfully"},
                {"ev": 1.5, "result": "对象已合并到已有项 / Object merged into existing item", "fast_ref_hit_merge": True, "insert_log_suppressed": True},
                {"ev": 3.0, "result": "skipped_cognitive_stitching_event_structure"},
                {"ev": 0.5, "result": "skipped_attribute_only_structure"},
            ],
        },
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 1, "input_text": "", "input_is_empty": True})

    assert metrics["induction_projection_mode_growth"] == 1
    assert metrics["induction_projection_raw_target_count"] == 4
    assert metrics["induction_projection_projected_target_count"] == 3
    assert metrics["induction_growth_target_count"] == 3
    assert metrics["induction_growth_identity_hit_count"] == 2
    assert metrics["induction_growth_identity_created_count"] == 1
    assert metrics["induction_growth_identity_shared_cache_hit_count"] == 4
    assert metrics["induction_growth_identity_shared_cache_stale_count"] == 0
    assert metrics["induction_growth_persistence_batch_enabled"] == 1
    assert metrics["induction_growth_target_apply_ref_fast_merge_enabled"] == 1
    assert metrics["induction_growth_target_apply_fast_ref_hit_merge_count"] == 2
    assert metrics["induction_growth_target_apply_insert_log_enabled"] == 0
    assert metrics["induction_growth_target_apply_insert_log_suppressed_count"] == 3
    assert metrics["induction_growth_total_delta_er"] == 1.25
    assert metrics["induction_growth_total_delta_ev"] == 2.75
    assert metrics["induction_growth_source_component_er_total"] == 1.25
    assert metrics["induction_growth_residual_component_ev_total"] == 2.75
    assert metrics["induction_total_delta_er"] == 1.25
    assert metrics["induction_total_delta_ev"] == 9.5
    assert metrics["induction_total_ev_consumed"] == 6.0
    assert metrics["induction_propagated_ev_total"] == 6.0
    assert metrics["induction_ev_from_er_total"] == 3.5
    assert metrics["induction_source_item_count"] == 4
    assert metrics["induction_source_available_st_count"] == 9
    assert metrics["induction_source_selected_from_ev_count"] == 2
    assert metrics["induction_source_selected_from_er_count"] == 2
    assert metrics["induction_source_selected_from_cp_abs_count"] == 0
    assert metrics["induction_source_max_items"] == 4
    assert metrics["induction_source_candidate_top_k"] == 12
    assert metrics["induction_source_ev_quota_ratio"] == 0.5
    assert metrics["induction_source_ev_quota_count"] == 2
    assert metrics["induction_source_selection_cap_hit"] == 1
    assert metrics["induction_raw_residual_entry_count"] == 5
    assert metrics["induction_raw_residual_entry_with_existing_structure_count"] == 3
    assert metrics["induction_raw_residual_entry_routed_to_structure_count"] == 2
    assert metrics["induction_raw_residual_existing_structure_target_count"] == 2
    assert metrics["induction_raw_residual_entry_materialized_structure_count"] == 2
    assert metrics["induction_raw_residual_materialized_structure_target_count"] == 3
    assert metrics["induction_raw_residual_entry_with_component_structure_count"] == 1
    assert metrics["induction_raw_residual_entry_routed_to_component_structure_count"] == 1
    assert metrics["induction_raw_residual_component_structure_target_count"] == 1
    assert metrics["induction_target_count"] == 8
    assert metrics["induction_structure_target_count"] == 4
    assert metrics["induction_memory_target_count"] == 4
    assert metrics["induction_raw_residual_structure_target_count"] == 2
    assert metrics["induction_raw_residual_exact_structure_target_count"] == 1
    assert metrics["induction_raw_residual_component_structure_ev_target_count"] == 1
    assert metrics["induction_raw_residual_memory_target_count"] == 2
    assert metrics["induction_raw_residual_hit_memory_target_count"] == 1
    assert metrics["induction_raw_residual_miss_memory_target_count"] == 1
    assert metrics["induction_applied_target_count"] == 2
    assert metrics["induction_skipped_target_count"] == 2
    assert metrics["induction_skipped_cs_event_target_count"] == 1
    assert metrics["induction_propagated_target_count"] == 6
    assert metrics["induction_induced_target_count"] == 2
    assert metrics["induction_structure_target_total_ev"] == 4.5
    assert metrics["induction_memory_target_total_ev"] == 5.0
    assert metrics["induction_raw_residual_target_total_ev"] == 3.6
    assert metrics["induction_raw_residual_structure_target_total_ev"] == 2.0
    assert metrics["induction_raw_residual_exact_structure_target_total_ev"] == 0.8
    assert metrics["induction_raw_residual_component_structure_target_total_ev"] == 1.2
    assert metrics["induction_raw_residual_memory_target_total_ev"] == 1.6
    assert metrics["induction_raw_residual_hit_memory_target_total_ev"] == 0.9
    assert metrics["induction_raw_residual_miss_memory_target_total_ev"] == 0.7
    assert metrics["induction_raw_residual_hit_path_target_total_ev"] == 2.9
    assert metrics["induction_structure_target_ev_share"] == round(4.5 / 9.5, 8)
    assert metrics["induction_memory_target_ev_share"] == round(5.0 / 9.5, 8)
    assert metrics["induction_raw_residual_structure_target_ev_share"] == round(2.0 / 3.6, 8)
    assert metrics["induction_raw_residual_exact_structure_ev_share"] == round(0.8 / 2.0, 8)
    assert metrics["induction_raw_residual_component_structure_ev_share"] == round(1.2 / 2.0, 8)
    assert metrics["induction_raw_residual_memory_target_ev_share"] == round(1.6 / 3.6, 8)
    assert metrics["induction_raw_residual_hit_path_structure_ev_share"] == round(2.0 / 2.9, 8)
    assert metrics["induction_raw_residual_hit_path_memory_ev_share"] == round(0.9 / 2.9, 8)
    assert metrics["induction_raw_residual_structure_budget_weight"] == 2.0
    assert metrics["induction_raw_residual_exact_structure_budget_weight"] == 1.1
    assert metrics["induction_raw_residual_materialized_structure_budget_weight"] == 0.6
    assert metrics["induction_raw_residual_component_structure_budget_weight"] == 0.9
    assert metrics["induction_raw_residual_hit_memory_budget_weight"] == 0.9
    assert metrics["induction_raw_residual_miss_memory_budget_weight"] == 0.7
    assert metrics["hdb_primary_pointer_count"] == 11
    assert metrics["hdb_fallback_pointer_count"] == 2
    assert metrics["hdb_signature_index_count"] == 7
    assert metrics["hdb_recent_cache_count"] == 5
    assert metrics["hdb_exact_lookup_cache_count"] == 3
    assert metrics["hdb_numeric_bucket_family_count"] == 4
    assert metrics["hdb_numeric_bucket_count"] == 9
    assert metrics["induction_applied_total_ev"] == 3.5
    assert metrics["induction_skipped_target_total_ev"] == 3.5
    assert metrics["induction_applied_ev_ratio"] == round(3.5 / 4.5, 8)
    assert metrics["induction_applied_target_ratio"] == 0.5
    assert metrics["induction_structure_applied_total_ev"] == 3.5
    assert metrics["induction_structure_applied_ev_ratio"] == round(3.5 / 4.5, 8)
    assert metrics["induction_structure_applied_target_count"] == 2
    assert metrics["induction_structure_skipped_target_count"] == 2
    assert metrics["induction_propagated_target_ratio"] == 0.75
    assert metrics["induction_ev_from_er_ratio"] == round(3.5 / 9.5, 8)
    assert metrics["induction_targets_per_source_mean"] == 2.0
    assert metrics["induction_fallback_used"] == 1


def test_extract_tick_metrics_exports_internal_resolution_compat_aliases():
    report = {
        "trace_id": "trace_internal_resolution",
        "tick_id": "cycle_internal_resolution_0001",
        "started_at": 40,
        "finished_at": 41,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {
            "result": {
                "internal_resolution": {
                    "max_structures_per_tick": 5,
                    "detail_budget": 144,
                    "detail_budget_base": 128,
                    "detail_budget_adr_gain": 64,
                    "raw_unit_count": 23,
                    "raw_unit_count_total": 31,
                    "raw_unit_count_total_candidates": 42,
                    "selected_unit_count": 11,
                    "structure_count_total": 7,
                    "structure_count_selected": 4,
                    "structure_count_dropped": 3,
                    "runtime_priority_structure_count_total_candidates": 3,
                    "runtime_priority_structure_count": 2,
                    "runtime_priority_family_match_total_candidates": 4,
                    "runtime_priority_family_match_total": 3,
                    "runtime_family_bonus_total": 1.14,
                    "selected_attribute_unit_count": 5,
                    "selected_priority_attribute_unit_count": 2,
                    "rescued_priority_attribute_unit_count": 1,
                },
                "internal_stimulus_fragments": [{}, {}, {}],
            }
        },
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 1, "input_text": "", "input_is_empty": True})

    assert metrics["internal_fragment_count"] == 3
    assert metrics["internal_source_structure_count"] == 7
    assert metrics["internal_candidate_structure_count"] == 7
    assert metrics["internal_selected_structure_count"] == 4
    assert metrics["internal_resolution_budget_sa_cap"] == 144
    assert metrics["internal_resolution_detail_budget"] == 144
    assert metrics["internal_resolution_detail_budget_base"] == 128
    assert metrics["internal_resolution_detail_budget_adr_gain"] == 64
    assert metrics["internal_resolution_raw_sa_count"] == 23
    assert metrics["internal_resolution_raw_unit_count"] == 23
    assert metrics["internal_resolution_raw_unit_count_total"] == 31
    assert metrics["internal_resolution_raw_unit_count_total_candidates"] == 42
    assert metrics["internal_resolution_selected_sa_count"] == 11
    assert metrics["internal_resolution_selected_unit_count"] == 11
    assert metrics["internal_resolution_runtime_priority_structure_count_total_candidates"] == 3
    assert metrics["internal_resolution_runtime_priority_structure_count"] == 2
    assert metrics["internal_resolution_runtime_priority_family_match_total_candidates"] == 4
    assert metrics["internal_resolution_runtime_priority_family_match_total"] == 3
    assert metrics["internal_resolution_runtime_family_bonus_total"] == 1.14
    assert metrics["internal_resolution_selected_attribute_unit_count"] == 5
    assert metrics["internal_resolution_selected_priority_attribute_unit_count"] == 2
    assert metrics["internal_resolution_rescued_priority_attribute_unit_count"] == 1


def test_extract_tick_metrics_exports_attention_and_time_sensor_compat_aliases():
    report = {
        "trace_id": "trace_attention_time",
        "tick_id": "cycle_attention_time_0001",
        "started_at": 50,
        "finished_at": 51,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {
            "cam_snapshot_summary": {"active_item_count": 6},
            "memory_item_count": 9,
        },
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {
            "memory_used_count": 8,
            "bucket_updates": [{}, {}],
            "attribute_bindings": [{}, {}, {}],
            "delayed_tasks": {
                "table_size": 5,
                "executed_count": 1,
                "registered": {
                    "registered_count": 2,
                    "updated_count": 3,
                    "pruned_count": 4,
                    "skipped": {"capacity": 7},
                },
            },
        },
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 1, "input_text": "", "input_is_empty": True})

    assert metrics["cam_item_count"] == 6
    assert metrics["attention_cam_item_count"] == 6
    assert metrics["time_sensor_memory_used_count"] == 8
    assert metrics["time_sensor_memory_sample_count"] == 8
    assert metrics["time_sensor_delayed_task_skipped_capacity_count"] == 7
    assert metrics["time_sensor_delayed_task_capacity_skip_count"] == 7


def test_extract_tick_metrics_counts_projection_and_runtime_projection_time_bindings():
    report = {
        "trace_id": "trace_attention_time_projection",
        "tick_id": "cycle_attention_time_projection_0001",
        "started_at": 54,
        "finished_at": 55,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {
            "bucket_updates": [],
            "attribute_bindings": [
                {"target_score_source": "projection_peak"},
                {"target_score_source": "runtime_projection_peak"},
                {"target_score_source": "legacy_peak"},
            ],
            "delayed_tasks": {"registered": {}},
        },
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 1, "input_text": "", "input_is_empty": True})

    assert metrics["time_sensor_attribute_binding_count"] == 3
    assert metrics["time_sensor_projection_binding_count"] == 2
    assert metrics["time_sensor_legacy_binding_count"] == 1


def test_extract_tick_metrics_aggregates_time_like_v2_metrics():
    report = {
        "trace_id": "trace_time_like_v2",
        "tick_id": "cycle_time_like_v2_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {
            "result": {
                "debug": {
                    "round_details": [
                        {
                            "candidate_groups": [
                                {
                                    "eligible": True,
                                    "soft_partial_eligible": True,
                                    "exact_match": True,
                                    "common_part": {"bundle_constraints_ok_exact": True},
                                    "v2_score": 0.8,
                                    "v2_base_score": 0.4,
                                    "v2_numeric_score": 0.9,
                                    "v2_numeric_time_like_score": 0.75,
                                    "v2_numeric_time_like_family_count": 1,
                                    "v2_numeric_time_like_wildcard_applied": True,
                                    "v2_numeric_family_count": 2,
                                    "v2_order_alignment_score": 0.7,
                                    "v2_attribute_anchor_score": 0.6,
                                    "v2_context_support_score": 0.5,
                                    "v2_energy_profile_score": 0.4,
                                    "v2_structure_inclusion_score": 0.9,
                                    "v2_time_factor_soft_bonus": 1.21,
                                    "v2_time_factor_applied": True,
                                    "v2_threshold_margin": 0.2,
                                    "competition_score": 0.8,
                                    "competition_score_legacy": 0.55,
                                }
                            ]
                        }
                    ]
                }
            }
        },
        "stimulus_level": {
            "result": {
                "debug": {
                    "round_details": [
                        {
                            "candidate_details": [
                                {
                                    "eligible": True,
                                    "soft_partial_eligible": True,
                                    "exact_match": False,
                                    "common_part": {"bundle_constraints_ok_exact": False},
                                    "v2_score": 0.85,
                                    "v2_base_score": 0.45,
                                    "v2_numeric_score": 1.0,
                                    "v2_numeric_time_like_score": 1.0,
                                    "v2_numeric_time_like_family_count": 1,
                                    "v2_numeric_time_like_wildcard_applied": True,
                                    "v2_numeric_family_count": 1,
                                    "v2_order_alignment_score": 0.8,
                                    "v2_attribute_anchor_score": 0.7,
                                    "v2_context_support_score": 0.6,
                                    "v2_energy_profile_score": 0.5,
                                    "v2_structure_inclusion_score": 0.95,
                                    "v2_time_factor_soft_bonus": 1.33,
                                    "v2_time_factor_applied": True,
                                    "v2_threshold_margin": 0.25,
                                    "competition_score": 0.85,
                                    "competition_score_legacy": 0.5,
                                }
                            ],
                            "shadow_candidate_details": [
                                {
                                    "eligible": True,
                                    "soft_partial_eligible": False,
                                    "exact_match": False,
                                    "common_part": {"bundle_constraints_ok_exact": False},
                                    "v2_score": 0.78,
                                    "v2_base_score": 0.41,
                                    "v2_numeric_score": 0.6,
                                    "v2_numeric_time_like_score": 0.92,
                                    "v2_numeric_time_like_family_count": 1,
                                    "v2_numeric_time_like_wildcard_applied": True,
                                    "v2_numeric_family_count": 1,
                                    "v2_order_alignment_score": 0.73,
                                    "v2_attribute_anchor_score": 0.55,
                                    "v2_context_support_score": 0.64,
                                    "v2_energy_profile_score": 0.44,
                                    "v2_structure_inclusion_score": 0.8,
                                    "v2_time_factor_soft_bonus": 1.27,
                                    "v2_time_factor_applied": True,
                                    "v2_threshold_margin": 0.19,
                                    "competition_score": 0.78,
                                    "competition_score_legacy": 0.46,
                                }
                            ],
                        }
                    ]
                }
            }
        },
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 9, "input_text": "", "input_is_empty": True})

    assert metrics["stimulus_match_v2_numeric_time_like_score_mean"] == 1.0
    assert metrics["stimulus_match_v2_numeric_time_like_scored_count"] == 1
    assert metrics["stimulus_match_v2_numeric_time_like_nonzero_count"] == 1
    assert metrics["stimulus_match_v2_numeric_time_like_family_count_mean"] == 1.0
    assert metrics["stimulus_match_v2_numeric_time_like_wildcard_applied_count"] == 1
    assert metrics["stimulus_match_v2_time_factor_bonus_applied_count"] == 1
    assert metrics["stimulus_match_v2_time_factor_bonus_mean"] == 1.33
    assert metrics["stimulus_match_v2_soft_partial_eligible_count"] == 1
    assert metrics["stimulus_match_v2_soft_partial_selected_count"] == 1
    assert metrics["stimulus_match_v2_bundle_exact_selected_count"] == 0
    assert metrics["stimulus_match_v2_exact_match_selected_count"] == 0
    assert metrics["stimulus_shadow_memory_match_v2_numeric_time_like_score_mean"] == 0.92
    assert metrics["stimulus_shadow_memory_match_v2_numeric_time_like_nonzero_count"] == 1
    assert metrics["stimulus_shadow_memory_match_v2_numeric_time_like_wildcard_applied_count"] == 1
    assert metrics["stimulus_shadow_memory_match_v2_time_factor_bonus_applied_count"] == 1
    assert metrics["stimulus_shadow_memory_match_v2_time_factor_bonus_mean"] == 1.27
    assert metrics["structure_match_v2_numeric_time_like_score_mean"] == 0.75
    assert metrics["structure_match_v2_numeric_time_like_scored_count"] == 1
    assert metrics["structure_match_v2_numeric_time_like_nonzero_count"] == 1
    assert metrics["structure_match_v2_numeric_time_like_family_count_mean"] == 1.0
    assert metrics["structure_match_v2_numeric_time_like_wildcard_applied_count"] == 1
    assert metrics["structure_match_v2_time_factor_bonus_applied_count"] == 1
    assert metrics["structure_match_v2_time_factor_bonus_mean"] == 1.21
    assert metrics["structure_match_v2_soft_partial_eligible_count"] == 1
    assert metrics["structure_match_v2_soft_partial_selected_count"] == 1
    assert metrics["structure_match_v2_bundle_exact_selected_count"] == 1
    assert metrics["structure_match_v2_exact_match_selected_count"] == 1


def test_extract_tick_metrics_flattens_memory_feedback_split_metrics():
    report = {
        "trace_id": "trace_memory_feedback",
        "tick_id": "cycle_memory_feedback_0001",
        "started_at": 40,
        "finished_at": 45,
        "sensor": {},
        "final_state": {
            "state_snapshot": {"summary": {}},
            "state_energy_summary": {"total_er": 8.0, "total_ev": 11.0},
            "hdb_snapshot": {"summary": {}},
        },
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {
            "snapshot": {"summary": {"count": 3, "total_er": 2.2, "total_ev": 5.8}, "items": []},
            "apply_result": {"applied_count": 2},
            "feedback_result": {
                "applied_count": 2,
                "total_feedback_er": 0.6,
                "total_feedback_ev": 2.4,
                "total_feedback_energy": 3.0,
                "packet_feedback_count": 1,
                "packet_feedback_total_er": 0.2,
                "packet_feedback_total_ev": 0.9,
                "packet_applied_total_er": 0.15,
                "packet_applied_total_ev": 0.6,
                "packet_apply_efficiency_er": 0.75,
                "packet_apply_efficiency_ev": round(0.6 / 0.9, 8),
                "structure_projection_ratio_used": 0.24,
                "pool_energy_before_feedback": {"total_er": 8.0, "total_ev": 3.2, "ev_to_er_ratio": 0.4},
                "structure_projection_attempted_count": 9,
                "structure_projection_skipped_count": 6,
                "structure_projection_count": 3,
                "structure_projection_total_er": 0.4,
                "structure_projection_total_ev": 1.5,
            },
        },
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 1, "input_text": "", "input_is_empty": True})

    assert metrics["map_feedback_count"] == 2
    assert metrics["map_feedback_total_ev"] == 2.4
    assert metrics["memory_feedback_applied_count"] == 2
    assert metrics["memory_feedback_total_er"] == 0.6
    assert metrics["memory_feedback_total_ev"] == 2.4
    assert metrics["memory_feedback_total_energy"] == 3.0
    assert metrics["memory_feedback_packet_count"] == 1
    assert metrics["memory_feedback_packet_total_er"] == 0.2
    assert metrics["memory_feedback_packet_total_ev"] == 0.9
    assert metrics["memory_feedback_packet_applied_total_er"] == 0.15
    assert metrics["memory_feedback_packet_applied_total_ev"] == 0.6
    assert metrics["memory_feedback_packet_apply_efficiency_er"] == 0.75
    assert metrics["memory_feedback_packet_apply_efficiency_ev"] == round(0.6 / 0.9, 8)
    assert metrics["memory_feedback_structure_projection_ratio_used"] == 0.24
    assert metrics["memory_feedback_pool_ev_to_er_ratio_before"] == 0.4
    assert metrics["memory_feedback_structure_projection_attempted_count"] == 9
    assert metrics["memory_feedback_structure_projection_skipped_count"] == 6
    assert metrics["memory_feedback_structure_projection_count"] == 3
    assert metrics["memory_feedback_structure_projection_total_er"] == 0.4
    assert metrics["memory_feedback_structure_projection_total_ev"] == 1.5
    assert metrics["memory_feedback_structure_projection_effective_ratio"] == round(3 / 9, 8)


def test_extract_tick_metrics_exports_memory_runtime_projection_path():
    report = {
        "trace_id": "trace_memory_runtime_projection",
        "tick_id": "cycle_memory_runtime_projection_0001",
        "started_at": 60,
        "finished_at": 66,
        "sensor": {},
        "final_state": {
            "state_snapshot": {"summary": {}},
            "state_energy_summary": {"total_er": 3.0, "total_ev": 4.0},
            "hdb_snapshot": {"summary": {}},
        },
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {
            "path_mode": "runtime-em",
            "runtime_projection": {"summary": {"inserted_count": 5}},
            "snapshot": {"summary": {}, "items": []},
            "apply_result": {},
            "feedback_result": {},
        },
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 2, "input_text": "", "input_is_empty": True})

    assert metrics["memory_path_mode"] == "runtime-em"
    assert metrics["memory_runtime_projection_count"] == 5


def test_extract_tick_metrics_counts_internal_runtime_attribute_units():
    report = {
        "trace_id": "trace_internal_attrs",
        "tick_id": "cycle_internal_attrs_0001",
        "started_at": 10,
        "finished_at": 12,
        "sensor": {},
        "final_state": {
            "state_snapshot": {"summary": {}},
            "state_energy_summary": {"total_er": 3.0, "total_ev": 2.0},
            "hdb_snapshot": {"summary": {}},
        },
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {"sa_count": 3, "csa_count": 0, "flat_token_count": 3},
        "internal_stimulus_raw": {
            "sa_items": [
                {
                    "id": "sa_time",
                    "stimulus": {"role": "attribute"},
                    "content": {
                        "attribute_name": "时间感受",
                        "attribute_value": 2.0,
                        "value_type": "numerical",
                        "meta": {
                            "ext": {
                                "time_bucket_id": "tb_demo",
                                "time_basis": "tick",
                                "delta_value": 2.0,
                            }
                        },
                    },
                },
                {
                    "id": "sa_pressure",
                    "stimulus": {"role": "attribute"},
                    "content": {
                        "attribute_name": "cfs_pressure",
                        "attribute_value": 0.8,
                        "value_type": "numerical",
                    },
                },
                {
                    "id": "sa_pressure_unverified",
                    "stimulus": {"role": "attribute"},
                    "content": {
                        "attribute_name": "cfs_pressure_unverified",
                        "attribute_value": 0.35,
                        "value_type": "numerical",
                    },
                },
                {
                    "id": "sa_teacher_reward",
                    "stimulus": {"role": "attribute"},
                    "content": {
                        "attribute_name": "teacher_reward_signal",
                        "attribute_value": 0.9,
                        "value_type": "numerical",
                    },
                },
                {
                    "id": "sa_reward_signal",
                    "stimulus": {"role": "attribute"},
                    "content": {
                        "attribute_name": "reward_signal",
                        "attribute_value": 1.0,
                        "value_type": "numerical",
                    },
                },
                {
                    "id": "sa_feature",
                    "stimulus": {"role": "feature"},
                    "content": {"raw": "A", "display": "A", "normalized": "A"},
                },
            ]
        },
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 3, "input_text": "", "input_is_empty": True})

    assert metrics["internal_attribute_count"] == 5
    assert metrics["internal_numeric_attribute_count"] == 5
    assert metrics["internal_time_like_attribute_count"] == 1
    assert metrics["internal_cfs_attribute_count"] == 2
    assert metrics["internal_cfs_pressure_family_attribute_count"] == 2
    assert metrics["internal_cfs_expectation_family_attribute_count"] == 0
    assert metrics["internal_teacher_reward_signal_attribute_count"] == 1
    assert metrics["internal_teacher_punish_signal_attribute_count"] == 0
    assert metrics["internal_reward_signal_attribute_count"] == 1
    assert metrics["internal_punish_signal_attribute_count"] == 0


def test_extract_tick_metrics_marks_cfs_live_active_and_decay_only():
    report = {
        "trace_id": "trace_cfs_live_active",
        "tick_id": "cycle_cfs_live_active_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {
            "state_snapshot": {
                "summary": {
                    "bound_attribute_energy_totals": {
                        "cfs_pressure": {
                            "total_er": 0.3,
                            "total_ev": 0.0,
                            "total_energy": 0.3,
                            "item_count": 1,
                            "attribute_count": 1,
                        }
                    }
                }
            },
            "state_energy_summary": {},
            "hdb_snapshot": {"summary": {}},
        },
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 9, "input_text": "", "input_is_empty": True})

    assert metrics["cfs_pressure_count"] == 0
    assert metrics["cfs_pressure_live_active"] == 1
    assert metrics["cfs_pressure_decay_only"] == 1


def test_extract_tick_metrics_flattens_runtime_feedback_and_cfs_family_live_metrics():
    report = {
        "trace_id": "trace_runtime_feedback_families",
        "tick_id": "cycle_runtime_feedback_families_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {
            "state_snapshot": {
                "summary": {
                    "bound_attribute_energy_totals": {
                        "cfs_pressure": {
                            "total_er": 0.2,
                            "total_ev": 0.1,
                            "total_energy": 0.3,
                            "item_count": 1,
                            "attribute_count": 1,
                        },
                        "cfs_pressure_unverified": {
                            "total_er": 0.0,
                            "total_ev": 0.4,
                            "total_energy": 0.4,
                            "item_count": 2,
                            "attribute_count": 2,
                        },
                        "cfs_pressure_verified": {
                            "total_er": 0.1,
                            "total_ev": 0.0,
                            "total_energy": 0.1,
                            "item_count": 1,
                            "attribute_count": 1,
                        },
                        "cfs_expectation_verified": {
                            "total_er": 0.5,
                            "total_ev": 0.0,
                            "total_energy": 0.5,
                            "item_count": 1,
                            "attribute_count": 1,
                        },
                        "cfs_expectation_unverified": {
                            "total_er": 0.0,
                            "total_ev": 0.2,
                            "total_energy": 0.2,
                            "item_count": 1,
                            "attribute_count": 1,
                        },
                        "cfs_simplicity": {
                            "total_er": 0.3,
                            "total_ev": 0.0,
                            "total_energy": 0.3,
                            "item_count": 1,
                            "attribute_count": 1,
                        },
                        "cfs_relief": {
                            "total_er": 0.25,
                            "total_ev": 0.0,
                            "total_energy": 0.25,
                            "item_count": 1,
                            "attribute_count": 1,
                        },
                        "cfs_reassurance": {
                            "total_er": 0.35,
                            "total_ev": 0.0,
                            "total_energy": 0.35,
                            "item_count": 1,
                            "attribute_count": 1,
                        },
                        "reward_signal": {
                            "total_er": 0.0,
                            "total_ev": 0.7,
                            "total_energy": 0.7,
                            "item_count": 1,
                            "attribute_count": 1,
                        },
                        "teacher_reward_signal": {
                            "total_er": 0.0,
                            "total_ev": 0.9,
                            "total_energy": 0.9,
                            "item_count": 1,
                            "attribute_count": 1,
                        },
                        "teacher_punish_signal": {
                            "total_er": 0.2,
                            "total_ev": 0.0,
                            "total_energy": 0.2,
                            "item_count": 1,
                            "attribute_count": 1,
                        },
                    }
                }
            },
            "state_energy_summary": {},
            "hdb_snapshot": {"summary": {}},
        },
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {
            "cfs_signals": [
                {"kind": "expectation_verified", "strength": 0.5},
                {"kind": "expectation_unverified", "strength": 0.2},
                {"kind": "pressure_verified", "strength": 0.1},
                {"kind": "pressure_unverified", "strength": 0.4},
                {"kind": "simplicity", "strength": 0.3},
                {"kind": "relief", "strength": 0.25},
                {"kind": "reassurance", "strength": 0.35},
            ]
        },
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 4, "input_text": "", "input_is_empty": True})

    assert metrics["cfs_pressure_family_live_total_energy"] == 0.8
    assert metrics["cfs_pressure_family_live_item_count"] == 4
    assert metrics["cfs_pressure_family_live_attribute_count"] == 4
    assert metrics["cfs_expectation_family_live_total_energy"] == 0.7
    assert metrics["cfs_expectation_family_live_attribute_count"] == 2
    assert metrics["cfs_pressure_verified_count"] == 1
    assert metrics["cfs_pressure_unverified_count"] == 1
    assert metrics["cfs_expectation_verified_count"] == 1
    assert metrics["cfs_expectation_unverified_count"] == 1
    assert metrics["cfs_simplicity_count"] == 1
    assert metrics["cfs_relief_count"] == 1
    assert metrics["cfs_reassurance_count"] == 1
    assert metrics["cfs_pressure_verified_live_total_energy"] == 0.1
    assert metrics["cfs_pressure_unverified_live_total_energy"] == 0.4
    assert metrics["cfs_expectation_verified_live_total_energy"] == 0.5
    assert metrics["cfs_expectation_unverified_live_total_energy"] == 0.2
    assert metrics["cfs_simplicity_live_total_energy"] == 0.3
    assert metrics["cfs_relief_live_total_energy"] == 0.25
    assert metrics["cfs_reassurance_live_total_energy"] == 0.35
    assert metrics["reward_signal_live_total_energy"] == 0.7
    assert metrics["teacher_reward_signal_live_total_energy"] == 0.9
    assert metrics["teacher_punish_signal_live_total_energy"] == 0.2


def test_extract_tick_metrics_merges_runtime_reward_signal_nodes_into_live_totals():
    report = {
        "trace_id": "trace_runtime_reward_signal_live",
        "tick_id": "cycle_runtime_reward_signal_live_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {
            "state_snapshot": {
                "summary": {
                    "bound_attribute_energy_totals": {
                        "reward_signal": {
                            "total_er": 0.1,
                            "total_ev": 0.2,
                            "total_energy": 0.3,
                            "item_count": 1,
                            "attribute_count": 1,
                        }
                    }
                }
            },
            "state_energy_summary": {},
            "hdb_snapshot": {"summary": {}},
        },
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "reward_action_runtime_sync": {
            "signal_nodes": [
                {
                    "ok": True,
                    "code": "OK",
                    "operation": "set_existing",
                    "signal_name": "reward_signal",
                    "item_id": "spi_reward_signal",
                    "target_er": 0.0,
                    "target_ev": 0.6,
                    "after": {"er": 0.0, "ev": 0.6},
                },
                {
                    "ok": True,
                    "code": "OK",
                    "operation": "insert_or_merge",
                    "signal_name": "punish_signal",
                    "item_id": "spi_punish_signal",
                    "target_er": 0.15,
                    "target_ev": 0.05,
                },
            ]
        },
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 1, "input_text": "", "input_is_empty": True})

    assert metrics["reward_signal_live_total_er"] == 0.1
    assert metrics["reward_signal_live_total_ev"] == 0.8
    assert metrics["reward_signal_live_total_energy"] == 0.9
    assert metrics["reward_signal_live_item_count"] == 2
    assert metrics["reward_signal_live_attribute_count"] == 1
    assert metrics["punish_signal_live_total_er"] == 0.15
    assert metrics["punish_signal_live_total_ev"] == 0.05
    assert metrics["punish_signal_live_total_energy"] == 0.2
    assert metrics["punish_signal_live_item_count"] == 1


def test_extract_tick_metrics_skips_zero_runtime_reward_signal_create():
    report = {
        "trace_id": "trace_runtime_reward_signal_zero_skip",
        "tick_id": "cycle_runtime_reward_signal_zero_skip_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "reward_action_runtime_sync": {
            "signal_nodes": [
                {
                    "ok": True,
                    "code": "SKIP_ZERO_CREATE",
                    "signal_name": "reward_signal",
                    "target_er": 0.0,
                    "target_ev": 0.0,
                }
            ]
        },
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 2, "input_text": "", "input_is_empty": True})

    assert metrics["reward_signal_live_total_er"] == 0.0
    assert metrics["reward_signal_live_total_ev"] == 0.0
    assert metrics["reward_signal_live_total_energy"] == 0.0
    assert metrics["reward_signal_live_item_count"] == 0
    assert metrics["reward_signal_live_attribute_count"] == 0


def test_extract_tick_metrics_flattens_teacher_focus_directive_metrics():
    report = {
        "trace_id": "trace_teacher_focus_directives",
        "tick_id": "cycle_teacher_focus_directives_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
        "teacher_feedback": {
            "teacher_rwd": 0.9,
            "teacher_pun": 0.2,
            "applied_count": 2,
            "total_binding_applied_count": 3,
            "primary_target_atomic": True,
            "context_binding_enabled": True,
            "context_binding_candidate_count": 1,
            "context_binding_applied_count": 1,
            "focus_directive_enabled": True,
            "focus_directive_count": 2,
            "focus_context_carrier_count": 1,
            "focus_directives": [
                {
                    "directive_id": "teacher_feedback_focus_st_demo_cycle_0001",
                    "source_kind": "teacher_feedback",
                    "strength": 0.9,
                    "focus_boost": 1.2,
                    "ttl_ticks": 2,
                },
                {
                    "directive_id": "teacher_feedback_context_focus_st_carrier_cycle_0001",
                    "source_kind": "teacher_feedback_context_carrier",
                    "strength": 0.765,
                    "focus_boost": 1.2,
                    "ttl_ticks": 2,
                }
            ],
        },
        "teacher_local_feedback_alias_cache": {
            "enabled": True,
            "active_count": 2,
            "available_count": 1,
            "matched_count": 1,
            "overlay_applied_count": 1,
            "overlay_rwd": 0.0,
            "overlay_pun": 0.55,
            "overlay_match_score": 0.91,
        },
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 6, "input_text": "", "input_is_empty": True})

    assert metrics["teacher_rwd"] == 0.9
    assert metrics["teacher_pun"] == 0.2
    assert metrics["teacher_applied_count"] == 2
    assert metrics["teacher_total_binding_applied_count"] == 3
    assert metrics["teacher_primary_target_atomic"] == 1
    assert metrics["teacher_context_binding_enabled"] == 1
    assert metrics["teacher_context_binding_candidate_count"] == 1
    assert metrics["teacher_context_binding_applied_count"] == 1
    assert metrics["teacher_focus_directive_enabled"] == 1
    assert metrics["teacher_focus_directive_count"] == 2
    assert metrics["teacher_focus_context_carrier_count"] == 1
    assert metrics["teacher_focus_directive_total_strength"] == 1.665
    assert metrics["teacher_focus_directive_max_focus_boost"] == 1.2
    assert metrics["teacher_focus_directive_ttl_max"] == 2
    assert metrics["teacher_local_alias_enabled"] == 1
    assert metrics["teacher_local_alias_active_count"] == 2
    assert metrics["teacher_local_alias_available_count"] == 1
    assert metrics["teacher_local_alias_matched_count"] == 1
    assert metrics["teacher_local_alias_overlay_applied_count"] == 1
    assert metrics["teacher_local_alias_overlay_rwd"] == 0.0
    assert metrics["teacher_local_alias_overlay_pun"] == 0.55
    assert metrics["teacher_local_alias_overlay_match_score"] == 0.91


def test_extract_tick_metrics_counts_time_sensor_binding_sources():
    report = {
        "trace_id": "trace_time_binding_sources",
        "tick_id": "cycle_time_binding_sources_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {"result": {}},
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {
            "bucket_updates": [],
            "attribute_bindings": [
                {"target_score_source": "legacy_peak"},
                {"target_score_source": "projection_peak"},
                {"target_score_source": "projection_peak"},
            ],
            "delayed_tasks": {},
        },
    }

    metrics = extract_tick_metrics(
        report=report,
        dataset_tick={"tick_index": 1, "input_text": "", "input_is_empty": True},
    )

    assert metrics["time_sensor_attribute_binding_count"] == 3
    assert metrics["time_sensor_legacy_binding_count"] == 1
    assert metrics["time_sensor_projection_binding_count"] == 2


def test_extract_tick_metrics_flattens_cam_runtime_priority_sidepath_summary():
    report = {
        "trace_id": "trace_cam_runtime_sidepath_metrics",
        "tick_id": "cycle_cam_runtime_sidepath_metrics_0001",
        "started_at": 1,
        "finished_at": 2,
        "sensor": {},
        "final_state": {"state_snapshot": {"summary": {}}, "state_energy_summary": {}, "hdb_snapshot": {"summary": {}}},
        "attention": {},
        "maintenance": {},
        "structure_level": {
            "result": {
                "internal_resolution": {},
                "cam_runtime_priority_projection": {
                    "enabled": True,
                    "candidate_count": 3,
                    "fragment_count": 2,
                    "projected_family_count": 4,
                    "projected_unit_count": 5,
                    "projection_ratio": 0.08,
                    "require_unrepresented": True,
                },
            }
        },
        "stimulus_level": {"result": {}},
        "internal_stimulus": {},
        "merged_stimulus": {},
        "cache_neutralization": {},
        "pool_apply": {},
        "induction": {"result": {}},
        "memory_activation": {"snapshot": {"summary": {}, "items": []}, "apply_result": {}, "feedback_result": {}},
        "cognitive_feeling": {"cfs_signals": []},
        "emotion": {"nt_state_after": {}},
        "action": {"executed_actions": [], "nodes": []},
        "timing": {"steps_ms": {}},
        "time_sensor": {},
    }

    metrics = extract_tick_metrics(report=report, dataset_tick={"tick_index": 1, "input_text": "", "input_is_empty": True})

    assert metrics["internal_cam_runtime_priority_projection_enabled"] == 1
    assert metrics["internal_cam_runtime_priority_projection_candidate_count"] == 3
    assert metrics["internal_cam_runtime_priority_projection_fragment_count"] == 2
    assert metrics["internal_cam_runtime_priority_projection_family_count"] == 4
    assert metrics["internal_cam_runtime_priority_projection_unit_count"] == 5
    assert metrics["internal_cam_runtime_priority_projection_ratio"] == 0.08
    assert metrics["internal_cam_runtime_priority_projection_require_unrepresented"] == 1
