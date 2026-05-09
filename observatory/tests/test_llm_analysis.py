# -*- coding: utf-8 -*-

from __future__ import annotations

import json

from observatory.experiment import llm_analysis


def test_review_system_prompt_is_evidence_bound_and_not_nitpicky():
    prompt = llm_analysis._build_system_prompt()

    assert "证据与表述原则" in prompt
    assert "Observed" in prompt
    assert "Inferred" in prompt
    assert "Unknown" in prompt
    assert "Recommendation" in prompt
    assert "metric key" in prompt
    assert "tick 区间" in prompt
    assert "cs_concat_count" in prompt
    assert "找茬" not in prompt


def test_review_prompt_includes_current_ap_design_baseline():
    prompt = llm_analysis.build_review_prompt(
        run_id="run_demo",
        config=llm_analysis.LLMReviewConfig(model="demo-model"),
        theory_core_text="理论正文",
        manifest_text='{"run_id":"run_demo"}',
        dataset_text="ticks: []",
        metrics_text='{"tick_index":0,"pool_er_top5":[],"pool_ev_top5":[]}',
        metrics_note="metrics included",
        expectation_contract_events_text="",
        extra_context="enable_structure_level_retrieval_storage: false",
    )

    assert "本次审阅 run_id: run_demo" in prompt
    assert "当前 AP 设计基线摘要" in prompt
    assert "SA 是实际能量载体" in prompt
    assert "分形式感应赋能" in prompt
    assert "教师奖惩" in prompt
    assert "ER/EV Top5" in prompt
    assert "concat_context_structure" in prompt
    assert "理论对齐矩阵" in prompt
    assert "证据字段与 tick 区间" in prompt
    assert "总评" in prompt
    assert "架构效果与区别评估" in prompt
    assert "拟人度评估" in prompt
    assert "与其它架构的对比评估" in prompt
    assert "创新点、特点与可应用场景" in prompt
    assert "纯向量/RAG 检索记忆" in prompt
    assert "普通工具调用 agent loop" in prompt
    assert "传统强化学习/行为策略" in prompt
    assert "预测加工/主动推断类架构" in prompt
    assert "不要删除、合并或跳过前 6 个架构评价章节" in prompt
    assert "curriculum_metrics_summary.json" in prompt
    assert "top5_snapshots" in prompt
    assert "top5_root_summary" in prompt
    assert "expectation_contract_windows" in prompt
    assert "identity_resolution_summary" in prompt
    assert "create_exact_lookup_skipped" in prompt
    assert "causal_chain" in prompt
    assert "performance_hdb_diagnostic_summary" in prompt
    assert "segment_timing_trend" in prompt
    assert "slowest_ticks_by_total_logic_ms" in prompt
    assert "短程 300/1000/3000 tick" in prompt
    assert "理论设计层面的创新/特点" in prompt
    assert "本次 run 已经观察到的实现效果" in prompt
    assert "nt_DA/nt_ADR/nt_OXY/nt_SER/nt_END/nt_COR/nt_NOV/nt_FOC" in prompt
    assert "attention_energy_budget" in prompt
    assert "action_threshold_*_scale_mean" in prompt
    assert "语料规模" in prompt
    assert "小型/低成熟 HDB" in prompt
    assert "单字 SA 波峰偏多" in prompt
    assert "感应生长方案" in prompt
    assert "A+B" in prompt
    assert "owner DB、growth_source、prior_context、parent_ids" in prompt
    assert "身份由完整特征信息" in prompt
    assert "provenance/审计信息" in prompt
    assert "运行态分辨率下降" in prompt
    assert "不应创建新的退化 HDB id" in prompt
    assert "旧 context/provenance" in prompt
    assert "默认折叠为诊断/回滚视图" in prompt
    assert "induction_growth_source_component_er_total" in prompt
    assert "induction_growth_residual_component_ev_total" in prompt
    assert "induction_growth_memory_terminal_passthrough_count" in prompt
    assert "induction_growth_target_apply_ref_fast_merge_enabled" in prompt
    assert "induction_growth_target_apply_fast_ref_hit_merge_count" in prompt
    assert "induction_growth_target_apply_insert_log_suppressed_count" in prompt
    assert "stimulus_cut_common_part_total_count" in prompt
    assert "stimulus_cut_cache_zero_copy_hit_count" in prompt
    assert "stimulus_cut_full_inclusion_fast_path_hit_count" in prompt
    assert "stimulus_cut_single_group_fast_path_hit_count" in prompt
    assert "stimulus_cut_ordered_subsequence_fast_path_hit_count" in prompt
    assert "cache_priority_cut_cache_hit_count" in prompt
    assert "cache_priority_cut_cache_zero_copy_hit_count" in prompt
    assert "cache_priority_cut_single_group_fast_path_hit_count" in prompt
    assert "priority_neutralization_common_part_cache_enabled=false" in prompt
    assert "stimulus_shadow_raw_residual_skipped_count" in prompt
    assert "runtime_residual_promotion_exact_rebind_count" in prompt
    assert "runtime_residual_promotion_full_identity_count" in prompt
    assert "runtime_residual_promotion_hdb_fallback_count" in prompt
    assert "residual_tail_memory_projection_handled=1" in prompt
    assert "运行态残余包晋升只属于 legacy fallback/A-B 对照" in prompt
    assert "promotion 关闭时跳过了观测型影子残差精评分" in prompt
    assert "CS 仅作为显式开启的 residual/对照路径审阅" in prompt
    assert "context/provenance 分流图多为诊断/回滚/兼容视图" in prompt
    assert "`cs_*`、`map_*`、`energy_balance_*`" in prompt
def test_review_prompt_mentions_raw_residual_static_cache_baseline():
    prompt = llm_analysis.build_review_prompt(
        run_id="run_cache",
        config=llm_analysis.LLMReviewConfig(model="demo-model"),
        theory_core_text="theory",
        manifest_text='{"run_id":"run_cache"}',
        dataset_text="ticks: []",
        metrics_text=(
            '{"tick_index":0,'
            '"induction_raw_residual_projection_profile_shared_cache_hit_count":1,'
            '"induction_raw_residual_exact_candidates_shared_cache_hit_count":2,'
            '"induction_raw_residual_component_candidates_shared_cache_hit_count":3,'
            '"induction_full_inclusion_shared_cache_hit_count":4}'
        ),
        metrics_note="metrics included",
        expectation_contract_events_text="",
        extra_context="",
    )

    assert "induction_raw_residual_projection_profile_shared_cache_hit_count" in prompt
    assert "induction_raw_residual_exact_candidates_shared_cache_hit_count" in prompt
    assert "induction_raw_residual_component_candidates_shared_cache_hit_count" in prompt
    assert "induction_full_inclusion_shared_cache_hit_count" in prompt
    assert "entry runtime_weight" in prompt


def test_metrics_digest_preserves_nt_attention_and_action_threshold_fields(tmp_path):
    run_dir = tmp_path / "run_demo"
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "tick_index": 0,
            "nt_DA": 0.2,
            "nt_ADR": 0.3,
            "attention_energy_budget": 10.0,
            "attention_net_delta_energy": 9.5,
            "action_threshold_nt_scale_mean": 0.95,
            "hdb_residual_diff_entry_ratio": 0.1,
        },
        {
            "tick_index": 1,
            "nt_DA": 0.25,
            "nt_ADR": 0.35,
            "attention_energy_budget": 11.0,
            "attention_net_delta_energy": 10.0,
            "action_threshold_nt_scale_mean": 0.9,
            "hdb_residual_diff_entry_ratio": 0.2,
        },
    ]
    metrics_path = run_dir / "metrics.jsonl"
    metrics_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    digest_text, _note = llm_analysis._build_metrics_jsonl_digest(metrics_path, char_budget=80_000)
    digest = json.loads(digest_text)
    keys = {item["key"] for item in digest["important_numeric_summaries"]}
    critical_keys = {item["key"] for item in digest["critical_numeric_summaries"]}
    field_audit = digest["field_presence_audit"]

    assert "nt_DA" in keys
    assert "nt_ADR" in keys
    assert "attention_energy_budget" in keys
    assert "attention_net_delta_energy" in keys
    assert "action_threshold_nt_scale_mean" in keys
    assert "hdb_residual_diff_entry_ratio" in keys
    assert "nt_DA" in critical_keys
    assert "attention_energy_budget" in critical_keys
    assert "action_threshold_nt_scale_mean" in critical_keys
    assert field_audit["nt_channels"]["present"][0]["key"] == "nt_DA"
    assert field_audit["attention_energy_budget"]["present"]
    assert field_audit["action_threshold_modulation"]["present"]


def test_metrics_digest_preserves_growth_projection_component_fields(tmp_path):
    run_dir = tmp_path / "run_growth"
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "tick_index": 0,
            "induction_projection_mode_growth": 1,
            "induction_growth_target_count": 3,
            "induction_growth_identity_hit_count": 2,
            "induction_growth_identity_created_count": 1,
            "induction_growth_identity_local_cache_hit_count": 4,
            "induction_growth_identity_shared_cache_hit_count": 6,
            "induction_growth_identity_shared_cache_stale_count": 0,
            "induction_growth_persistence_batch_enabled": 1,
            "induction_growth_target_apply_ref_fast_merge_enabled": 1,
            "induction_growth_target_apply_fast_ref_hit_merge_count": 3,
            "induction_growth_target_apply_insert_log_enabled": 0,
            "induction_growth_target_apply_insert_log_suppressed_count": 3,
            "induction_growth_runtime_only_count": 0,
            "induction_growth_memory_terminal_passthrough_count": 1,
            "induction_growth_pruned_low_energy_count": 2,
            "induction_growth_total_delta_er": 1.5,
            "induction_growth_total_delta_ev": 2.5,
            "induction_growth_source_component_er_total": 1.5,
            "induction_growth_residual_component_ev_total": 2.5,
            "timing_induction_projection_prepare_ms": 12.5,
            "cs_enabled": 0,
            "timing_cognitive_stitching_ms": 0.0,
        },
        {
            "tick_index": 1,
            "induction_projection_mode_growth": 1,
            "induction_growth_target_count": 4,
            "induction_growth_identity_hit_count": 3,
            "induction_growth_identity_created_count": 1,
            "induction_growth_identity_local_cache_hit_count": 5,
            "induction_growth_identity_shared_cache_hit_count": 7,
            "induction_growth_identity_shared_cache_stale_count": 0,
            "induction_growth_persistence_batch_enabled": 1,
            "induction_growth_target_apply_ref_fast_merge_enabled": 1,
            "induction_growth_target_apply_fast_ref_hit_merge_count": 4,
            "induction_growth_target_apply_insert_log_enabled": 0,
            "induction_growth_target_apply_insert_log_suppressed_count": 4,
            "induction_growth_runtime_only_count": 1,
            "induction_growth_memory_terminal_passthrough_count": 2,
            "induction_growth_pruned_low_energy_count": 1,
            "induction_growth_total_delta_er": 1.75,
            "induction_growth_total_delta_ev": 2.75,
            "induction_growth_source_component_er_total": 1.75,
            "induction_growth_residual_component_ev_total": 2.75,
            "timing_induction_projection_prepare_ms": 10.0,
            "cs_enabled": 0,
            "timing_cognitive_stitching_ms": 0.0,
        },
    ]
    metrics_path = run_dir / "metrics.jsonl"
    metrics_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    digest_text, _note = llm_analysis._build_metrics_jsonl_digest(metrics_path, char_budget=80_000)
    digest = json.loads(digest_text)
    critical_keys = {item["key"] for item in digest["critical_numeric_summaries"]}
    growth_presence = digest["field_presence_audit"]["induction_growth_projection"]["present"]
    growth_keys = {item["key"] for item in growth_presence}

    for key in [
        "induction_projection_mode_growth",
        "induction_growth_target_count",
        "induction_growth_identity_hit_count",
        "induction_growth_identity_created_count",
        "induction_growth_identity_local_cache_hit_count",
        "induction_growth_identity_shared_cache_hit_count",
        "induction_growth_identity_shared_cache_stale_count",
        "induction_growth_persistence_batch_enabled",
        "induction_growth_target_apply_ref_fast_merge_enabled",
        "induction_growth_target_apply_fast_ref_hit_merge_count",
        "induction_growth_target_apply_insert_log_enabled",
        "induction_growth_target_apply_insert_log_suppressed_count",
        "induction_growth_memory_terminal_passthrough_count",
        "induction_growth_source_component_er_total",
        "induction_growth_residual_component_ev_total",
        "timing_induction_projection_prepare_ms",
    ]:
        assert key in critical_keys
        assert key in growth_keys


def test_metrics_digest_preserves_stimulus_performance_cost_fields(tmp_path):
    run_dir = tmp_path / "run_stimulus_perf"
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "tick_index": 0,
            "stimulus_best_match_candidate_count": 10,
            "stimulus_best_match_pruned_count": 2,
            "stimulus_cut_common_part_total_count": 8,
            "stimulus_best_match_common_part_count": 6,
            "stimulus_cut_exact_fast_path_hit_count": 3,
            "stimulus_cut_full_inclusion_fast_path_hit_count": 2,
            "stimulus_cut_single_group_fast_path_hit_count": 6,
            "stimulus_cut_ordered_subsequence_fast_path_hit_count": 5,
            "stimulus_cut_cache_hit_count": 4,
            "stimulus_cut_cache_zero_copy_hit_count": 4,
            "stimulus_cut_cache_store_count": 5,
            "stimulus_cut_cache_deepcopy_count": 0,
            "stimulus_cut_normalize_cache_hit_count": 12,
            "stimulus_shadow_raw_residual_candidate_count": 5,
            "stimulus_shadow_raw_residual_skipped_count": 5,
            "stimulus_shadow_raw_residual_common_part_count": 0,
            "timing_stimulus_level_ms": 120.0,
        },
        {
            "tick_index": 1,
            "stimulus_best_match_candidate_count": 8,
            "stimulus_best_match_pruned_count": 1,
            "stimulus_cut_common_part_total_count": 7,
            "stimulus_best_match_common_part_count": 5,
            "stimulus_cut_exact_fast_path_hit_count": 2,
            "stimulus_cut_full_inclusion_fast_path_hit_count": 1,
            "stimulus_cut_single_group_fast_path_hit_count": 5,
            "stimulus_cut_ordered_subsequence_fast_path_hit_count": 4,
            "stimulus_cut_cache_hit_count": 3,
            "stimulus_cut_cache_zero_copy_hit_count": 3,
            "stimulus_cut_cache_store_count": 4,
            "stimulus_cut_cache_deepcopy_count": 0,
            "stimulus_cut_normalize_cache_hit_count": 10,
            "stimulus_shadow_raw_residual_candidate_count": 4,
            "stimulus_shadow_raw_residual_skipped_count": 4,
            "stimulus_shadow_raw_residual_common_part_count": 0,
            "timing_stimulus_level_ms": 110.0,
        },
    ]
    metrics_path = run_dir / "metrics.jsonl"
    metrics_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    digest_text, _note = llm_analysis._build_metrics_jsonl_digest(metrics_path, char_budget=80_000)
    digest = json.loads(digest_text)
    critical_keys = {item["key"] for item in digest["critical_numeric_summaries"]}
    perf_presence = digest["field_presence_audit"]["stimulus_performance_cost"]["present"]
    perf_keys = {item["key"] for item in perf_presence}

    for key in [
        "stimulus_cut_common_part_total_count",
        "stimulus_cut_exact_fast_path_hit_count",
        "stimulus_cut_full_inclusion_fast_path_hit_count",
        "stimulus_cut_single_group_fast_path_hit_count",
        "stimulus_cut_ordered_subsequence_fast_path_hit_count",
        "stimulus_cut_cache_hit_count",
        "stimulus_cut_cache_zero_copy_hit_count",
        "stimulus_cut_cache_deepcopy_count",
        "stimulus_cut_normalize_cache_hit_count",
        "stimulus_shadow_raw_residual_skipped_count",
        "timing_stimulus_level_ms",
    ]:
        assert key in critical_keys
        assert key in perf_keys


def test_metrics_digest_preserves_cache_neutralization_performance_fields(tmp_path):
    run_dir = tmp_path / "run_cache_neutralization_perf"
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "tick_index": 0,
            "cache_input_flat_token_count": 12,
            "cache_residual_flat_token_count": 7,
            "cache_priority_consumed_er": 0.4,
            "cache_priority_consumed_ev": 0.2,
            "cache_priority_cut_exact_fast_path_hit_count": 1,
            "cache_priority_cut_full_inclusion_fast_path_hit_count": 0,
            "cache_priority_cut_single_group_fast_path_hit_count": 6,
            "cache_priority_cut_ordered_subsequence_fast_path_hit_count": 3,
            "cache_priority_cut_cache_hit_count": 5,
            "cache_priority_cut_cache_zero_copy_hit_count": 5,
            "cache_priority_cut_cache_store_count": 7,
            "cache_priority_cut_cache_deepcopy_count": 0,
            "cache_priority_cut_normalize_cache_hit_count": 9,
            "timing_cache_neutralization_ms": 40.0,
        },
        {
            "tick_index": 1,
            "cache_input_flat_token_count": 11,
            "cache_residual_flat_token_count": 6,
            "cache_priority_consumed_er": 0.3,
            "cache_priority_consumed_ev": 0.25,
            "cache_priority_cut_exact_fast_path_hit_count": 2,
            "cache_priority_cut_full_inclusion_fast_path_hit_count": 1,
            "cache_priority_cut_single_group_fast_path_hit_count": 5,
            "cache_priority_cut_ordered_subsequence_fast_path_hit_count": 2,
            "cache_priority_cut_cache_hit_count": 6,
            "cache_priority_cut_cache_zero_copy_hit_count": 6,
            "cache_priority_cut_cache_store_count": 6,
            "cache_priority_cut_cache_deepcopy_count": 0,
            "cache_priority_cut_normalize_cache_hit_count": 8,
            "timing_cache_neutralization_ms": 32.0,
        },
    ]
    metrics_path = run_dir / "metrics.jsonl"
    metrics_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    digest_text, _note = llm_analysis._build_metrics_jsonl_digest(metrics_path, char_budget=80_000)
    digest = json.loads(digest_text)
    critical_keys = {item["key"] for item in digest["critical_numeric_summaries"]}
    cache_presence = digest["field_presence_audit"]["cache_neutralization_performance"]["present"]
    cache_keys = {item["key"] for item in cache_presence}

    for key in [
        "cache_priority_cut_cache_hit_count",
        "cache_priority_cut_cache_zero_copy_hit_count",
        "cache_priority_cut_cache_deepcopy_count",
        "cache_priority_cut_single_group_fast_path_hit_count",
        "timing_cache_neutralization_ms",
    ]:
        assert key in critical_keys
        assert key in cache_keys
def test_metrics_digest_preserves_induction_raw_residual_static_cache_fields(tmp_path):
    run_dir = tmp_path / "run_induction_raw_residual_cache"
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "tick_index": 0,
            "induction_raw_residual_projection_profile_local_cache_hit_count": 1,
            "induction_raw_residual_projection_profile_shared_cache_hit_count": 2,
            "induction_raw_residual_projection_profile_cache_store_count": 3,
            "induction_raw_residual_exact_candidates_local_cache_hit_count": 4,
            "induction_raw_residual_exact_candidates_shared_cache_hit_count": 5,
            "induction_raw_residual_exact_candidates_cache_store_count": 6,
            "induction_raw_residual_component_candidates_local_cache_hit_count": 7,
            "induction_raw_residual_component_candidates_shared_cache_hit_count": 8,
            "induction_raw_residual_component_candidates_cache_store_count": 9,
            "induction_full_inclusion_shared_cache_hit_count": 10,
            "induction_full_inclusion_shared_cache_store_count": 11,
        },
        {
            "tick_index": 1,
            "induction_raw_residual_projection_profile_local_cache_hit_count": 2,
            "induction_raw_residual_projection_profile_shared_cache_hit_count": 3,
            "induction_raw_residual_projection_profile_cache_store_count": 4,
            "induction_raw_residual_exact_candidates_local_cache_hit_count": 5,
            "induction_raw_residual_exact_candidates_shared_cache_hit_count": 6,
            "induction_raw_residual_exact_candidates_cache_store_count": 7,
            "induction_raw_residual_component_candidates_local_cache_hit_count": 8,
            "induction_raw_residual_component_candidates_shared_cache_hit_count": 9,
            "induction_raw_residual_component_candidates_cache_store_count": 10,
            "induction_full_inclusion_shared_cache_hit_count": 11,
            "induction_full_inclusion_shared_cache_store_count": 12,
        },
    ]
    metrics_path = run_dir / "metrics.jsonl"
    metrics_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    digest_text, _note = llm_analysis._build_metrics_jsonl_digest(metrics_path, char_budget=80_000)
    digest = json.loads(digest_text)
    critical_keys = {item["key"] for item in digest["critical_numeric_summaries"]}
    cache_presence = digest["field_presence_audit"]["induction_raw_residual_static_cache"]["present"]
    cache_keys = {item["key"] for item in cache_presence}

    for key in [
        "induction_raw_residual_projection_profile_local_cache_hit_count",
        "induction_raw_residual_projection_profile_shared_cache_hit_count",
        "induction_raw_residual_exact_candidates_shared_cache_hit_count",
        "induction_raw_residual_component_candidates_shared_cache_hit_count",
        "induction_full_inclusion_shared_cache_hit_count",
    ]:
        assert key in critical_keys
        assert key in cache_keys


def test_metrics_digest_preserves_runtime_residual_promotion_fast_path_fields(tmp_path):
    run_dir = tmp_path / "run_runtime_residual"
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "tick_index": 0,
            "runtime_residual_package_applied": 1,
            "runtime_residual_package_total_energy": 1.2,
            "runtime_residual_promotion_attempted_count": 1,
            "runtime_residual_promotion_promoted_count": 1,
            "runtime_residual_promotion_exact_rebind_count": 1,
            "runtime_residual_promotion_full_identity_count": 0,
            "runtime_residual_promotion_hdb_fallback_count": 0,
            "timing_runtime_residual_promotion_ms": 4.0,
        },
        {
            "tick_index": 1,
            "runtime_residual_package_applied": 1,
            "runtime_residual_package_total_energy": 0.9,
            "runtime_residual_promotion_attempted_count": 1,
            "runtime_residual_promotion_promoted_count": 1,
            "runtime_residual_promotion_exact_rebind_count": 0,
            "runtime_residual_promotion_full_identity_count": 1,
            "runtime_residual_promotion_hdb_fallback_count": 1,
            "timing_runtime_residual_promotion_ms": 30.0,
        },
    ]
    metrics_path = run_dir / "metrics.jsonl"
    metrics_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    digest_text, _note = llm_analysis._build_metrics_jsonl_digest(metrics_path, char_budget=80_000)
    digest = json.loads(digest_text)
    critical_keys = {item["key"] for item in digest["critical_numeric_summaries"]}
    runtime_presence = digest["field_presence_audit"]["runtime_residual_package"]["present"]
    runtime_keys = {item["key"] for item in runtime_presence}

    for key in [
        "runtime_residual_promotion_exact_rebind_count",
        "runtime_residual_promotion_full_identity_count",
        "runtime_residual_promotion_hdb_fallback_count",
        "timing_runtime_residual_promotion_ms",
    ]:
        assert key in critical_keys
        assert key in runtime_keys


def test_metrics_digest_keeps_valid_json_when_budget_is_tight(tmp_path):
    run_dir = tmp_path / "run_demo"
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for tick in range(20):
        rows.append(
            {
                "tick_index": tick,
                "pool_er_top1_display": "很长的状态池对象" * 20,
                "pool_ev_top1_display": "虚能量对象" * 20,
                "nt_DA": 0.1 + tick * 0.01,
                "attention_energy_budget": 10 + tick,
                "attention_net_delta_energy": 8 + tick,
                "action_threshold_nt_scale_mean": 1.0,
            }
        )
    metrics_path = run_dir / "metrics.jsonl"
    metrics_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    digest_text, _note = llm_analysis._build_metrics_jsonl_digest(metrics_path, char_budget=1_000)
    digest = json.loads(digest_text)

    assert digest["format"] == "metrics_digest_v2_compact_for_llm_review"
    assert digest["field_presence_audit"]["nt_channels"]["present"]
    assert digest["field_presence_audit"]["attention_energy_budget"]["present"]
    critical_keys = {item["key"] for item in digest["critical_numeric_summaries"]}
    assert "nt_DA" in critical_keys
    assert "attention_energy_budget" in critical_keys


def test_read_run_artifacts_bounds_metrics_excerpt_for_huge_lines(tmp_path):
    run_dir = tmp_path / "run_demo"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text('{"run_id":"run_demo"}', encoding="utf-8")
    (run_dir / "dataset.normalized.yaml").write_text("ticks: []\n", encoding="utf-8")
    huge_payload = "x" * 20_000
    rows = [
        json.dumps({"tick_index": i, "pool_er_top5": huge_payload, "pool_ev_top5": huge_payload})
        for i in range(8)
    ]
    (run_dir / "metrics.jsonl").write_text("\n".join(rows), encoding="utf-8")

    (
        _manifest_text,
        _dataset_text,
        _curriculum_summary_text,
        _curriculum_summary_note,
        _accumulated_summary_text,
        _accumulated_summary_note,
        metrics_text,
        metrics_note,
        _metrics_path,
    ) = llm_analysis._read_run_artifacts(
        run_dir=run_dir,
        max_prompt_chars=3_000,
    )

    assert len(metrics_text) <= 3_300
    assert "line_truncated" in metrics_text
    assert "字符预算" in metrics_note


def test_read_run_artifacts_includes_curriculum_summary(tmp_path):
    run_dir = tmp_path / "run_curriculum"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text('{"run_id":"run_curriculum"}', encoding="utf-8")
    (run_dir / "dataset.normalized.yaml").write_text("ticks: []\n", encoding="utf-8")
    (run_dir / "metrics.jsonl").write_text(json.dumps({"tick_index": 0}), encoding="utf-8")
    (run_dir / "curriculum_metrics_summary.json").write_text(
        json.dumps(
            {
                "top5_snapshots": {"items": [{"source_dataset_tick_index": 0}]},
                "identity_maturation": {"ratios": {"hit_to_hit_plus_created": 0.5}},
                "expectation_contract_windows": {"items": []},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    (
        _manifest_text,
        _dataset_text,
        curriculum_summary_text,
        curriculum_summary_note,
        _accumulated_summary_text,
        _accumulated_summary_note,
        _metrics_text,
        _metrics_note,
        _metrics_path,
    ) = llm_analysis._read_run_artifacts(
        run_dir=run_dir,
        max_prompt_chars=20_000,
    )

    assert "top5_snapshots" in curriculum_summary_text
    assert "identity_maturation" in curriculum_summary_text
    assert "curriculum_metrics_summary.json" in curriculum_summary_note


def test_curriculum_summary_large_file_compacts_without_losing_snapshots(tmp_path):
    run_dir = tmp_path / "run_curriculum_large"
    run_dir.mkdir(parents=True, exist_ok=True)
    big_display = "长文本" * 2000
    snapshots = [
        {
            "source_dataset_tick_index": i * 50,
            "tick_index": i * 50,
            "input_text_preview": f"输入 {i}",
            "pool_shape_counts": {"er": {"structure_count": 5}, "ev": {"structure_count": 5}, "cp": {"structure_count": 4}},
            "overlap_with_previous_snapshot": {"er": {"jaccard": 0.1 * i}},
            "identity_at_tick": {"target_count": 10, "created_count": i, "ratios": {"created_to_target": i / 10}},
            "top5_quality": {
                "er": {
                    "structure_ratio": 1.0,
                    "char_fragment_like_count": i % 2,
                    "dominant_context_owner_structure_id": f"st_owner_{i}",
                }
            },
            "pool_er_top5": [{"rank": 1, "ref": f"st:s{i}", "ref_object_type": "st", "display": big_display, "er": 1.0}],
            "pool_ev_top5": [{"rank": 1, "ref": f"st:e{i}", "ref_object_type": "st", "display": big_display, "ev": 2.0}],
            "pool_cp_top5": [{"rank": 1, "ref": f"st:c{i}", "ref_object_type": "st", "display": big_display, "cp": 3.0}],
        }
        for i in range(12)
    ]
    windows = [
        {
            "contract_id": f"contract_{i}",
            "spec_id": "weather_implicit_success",
            "outcome": "success",
            "source_dataset_tick_start": i,
            "source_dataset_tick_settled": i + 2,
            "aggregate_sum": {"action_executed_weather_stub_source_visible": 1, "nt_DA": 0.2},
            "causal_chain_summary": {
                "weather_action": {
                    "trigger_source_visible_sum": 1,
                    "ready_sum": 1,
                    "attempted_source_visible_sum": 1,
                    "scheduled_source_visible_sum": 1,
                    "executed_source_visible_sum": 1,
                    "first_trigger_tick": i,
                    "first_attempt_tick": i,
                    "first_scheduled_tick": i + 1,
                    "first_executed_tick": i + 1,
                    "max_drive": 1.2,
                    "max_threshold": 0.6,
                    "max_margin": 0.6,
                },
                "cfs_reward_punish": {
                    "teacher_applied_sum": 1,
                    "reward_live_max": 0.4,
                    "expectation_live_max": 0.8,
                },
                "nt_attention_threshold": {
                    "attention_budget_max": 12,
                    "threshold_nt_scale_max": 0.9,
                    "learning_reward_drive_gain_sum": 0.2,
                },
                "chain_flags": {
                    "trigger_to_attempt": True,
                    "attempt_to_execute": True,
                    "reward_or_expectation_present": True,
                    "nt_present": True,
                },
            },
            "rows": [
                {
                    "source_dataset_tick_index": i,
                    "pool_er_top1_display": big_display,
                    "nt_attention_action": {"nt_DA": 0.2, "action_threshold_nt_scale_mean": 0.9},
                }
            ],
        }
        for i in range(8)
    ]
    payload = {
        "run_id": "run_curriculum_large",
        "stats": {"hdb_structure_count": {"count": 1, "latest": 10}},
        "identity_maturation": {"ratios": {"created_to_target": 0.2}},
        "identity_resolution_summary": {
            "ratios": {
                "create_exact_lookup_skipped_to_created": 1.0,
                "shared_cache_hit_to_target": 0.8,
            }
        },
        "hdb_growth": {"structure_count_delta": 10},
        "top5_quality_summary": {"er": {"mean_structure_ratio": 1.0, "char_fragment_like_snapshot_count": 6}},
        "top5_root_summary": {"er": {"mean_unique_root_count": 4.0, "snapshots_with_duplicate_roots": 3}},
        "performance_hdb_diagnostic_summary": {
            "available": True,
            "completion_timing": {"hdb_pending_persistence_flush_ms": 1200},
            "hdb_structure_count_first_source_tick": 10,
            "hdb_structure_count_latest_source_tick": 210,
            "hdb_structure_count_delta_source_ticks": 200,
            "timing_breakdown": {
                "timing_total_logic_ms": {"mean": 90, "p95": 180, "max": 260, "sum": 900},
                "timing_stimulus_level_ms": {"mean": 70, "p95": 150, "max": 220, "sum": 700},
            },
            "segment_timing_trend": [
                {
                    "segment_index": 0,
                    "source_tick_start": 0,
                    "source_tick_end": 299,
                    "source_rows": 300,
                    "timing_total_logic_ms": {"mean": 40, "p95": 80},
                    "timing_stimulus_level_ms": {"mean": 20, "p95": 60},
                    "timing_induction_and_memory_ms": {"mean": 10, "p95": 15},
                    "hdb_growth": {"structure_count_delta": 100, "structure_count_latest": 110},
                }
            ],
            "slowest_ticks_by_total_logic_ms": [
                {
                    "tick_index": 9,
                    "source_dataset_tick_index": 8,
                    "timing_total_logic_ms": 260,
                    "timing_stimulus_level_ms": 220,
                    "hdb_structure_count": 210,
                    "stimulus_best_match_candidate_count": 33,
                }
            ],
            "top_correlated_metrics_with_total_logic_ms": [
                {"key": "stimulus_cut_cache_store_count", "corr_with_total_logic_ms": 0.91, "sum": 22, "max": 7}
            ],
        },
        "segments": {"source_tick_size": 300, "items": []},
        "expectation_contract_windows": {"items": windows},
        "top5_snapshots": {"source_tick_interval": 50, "items": snapshots},
    }
    (run_dir / "curriculum_metrics_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    text, note = llm_analysis._read_curriculum_metrics_summary_for_review(run_dir, char_budget=30_000)
    compact = json.loads(text)

    assert compact["format"] == "curriculum_metrics_summary_compact_for_llm_review_v1"
    assert compact["top5_snapshots"]["count"] == 12
    assert len(compact["top5_snapshots"]["items"]) == 12
    assert compact["expectation_contract_windows"]["count"] == 8
    assert compact["identity_resolution_summary"]["ratios"]["create_exact_lookup_skipped_to_created"] == 1.0
    assert compact["top5_quality_summary"]["er"]["mean_structure_ratio"] == 1.0
    assert compact["top5_root_summary"]["er"]["mean_unique_root_count"] == 4.0
    assert compact["performance_hdb_diagnostic_summary"]["hdb_first_latest_delta"] == [10, 210, 200]
    assert compact["performance_hdb_diagnostic_summary"]["segment_timing_trend"][0][6] == 20
    assert compact["performance_hdb_diagnostic_summary"]["slowest_ticks_by_total_logic_ms"][0][5] == 260
    assert compact["performance_hdb_diagnostic_summary"]["top_correlated_metrics_with_total_logic_ms"][0][0] == "stimulus_cut_cache_store_count"
    assert "top5_roots_by_er_ev_cp" in json.dumps(compact["schemas"], ensure_ascii=False)
    assert "causal_chain" in json.dumps(compact["schemas"], ensure_ascii=False)
    assert compact["expectation_contract_windows"]["items"][0][8][0][4] == 1
    assert "top5_quality_by_er_ev_cp" in json.dumps(compact["schemas"], ensure_ascii=False)
    assert "nt_attention_action_sparse" in json.dumps(compact["schemas"], ensure_ascii=False)
    assert "nt_DA" in text
    assert "deterministic compact view" in note
    assert big_display not in text


def test_read_run_artifacts_includes_accumulated_curriculum_summary(tmp_path):
    runs_root = tmp_path / "runs"
    run_id = "demo_accum_r03"
    run_dir = runs_root / run_id
    batch_dir = runs_root / "demo_accum_batch"
    run_dir.mkdir(parents=True, exist_ok=True)
    batch_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text('{"run_id":"demo_accum_r03"}', encoding="utf-8")
    (run_dir / "dataset.normalized.yaml").write_text("ticks: []\n", encoding="utf-8")
    (run_dir / "metrics.jsonl").write_text(json.dumps({"tick_index": 0}), encoding="utf-8")
    (batch_dir / "accumulated_curriculum_summary.json").write_text(
        json.dumps(
            {
                "batch_run_id": "demo_accum",
                "items": [
                    {"run_id": "demo_accum_r01", "identity_maturation": {"ratios": {"created_to_target": 0.2}}},
                    {"run_id": "demo_accum_r03", "identity_maturation": {"ratios": {"created_to_target": 0.1}}},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    (
        _manifest_text,
        _dataset_text,
        _curriculum_summary_text,
        _curriculum_summary_note,
        accumulated_summary_text,
        accumulated_summary_note,
        _metrics_text,
        _metrics_note,
        _metrics_path,
    ) = llm_analysis._read_run_artifacts(
        run_dir=run_dir,
        max_prompt_chars=20_000,
    )

    assert "demo_accum_r01" in accumulated_summary_text
    assert "created_to_target" in accumulated_summary_text
    assert "accumulated_curriculum_summary.json" in accumulated_summary_note


def test_save_review_config_accepts_legacy_auto_review_alias(tmp_path, monkeypatch):
    cfg_path = tmp_path / "llm_review_config.json"
    monkeypatch.setattr(llm_analysis, "_config_path", lambda: cfg_path)

    cfg = llm_analysis.save_review_config(
        {
            "enabled": True,
            "auto_review_on_completion": True,
            "base_url": "https://example.invalid",
            "model": "demo-model",
        }
    )

    assert cfg.auto_analyze_on_completion is True
    public = cfg.to_public_dict()
    assert public["auto_analyze_on_completion"] is True
    assert public["auto_review_on_completion"] is True


def test_read_review_report_falls_back_to_raw_json_text(tmp_path, monkeypatch):
    run_dir = tmp_path / "run_demo"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "llm_review.raw.json").write_text(
        json.dumps({"success": True, "text": "审查正文来自 raw"}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_analysis.storage, "resolve_run_dir", lambda run_id: run_dir)

    payload = llm_analysis.read_review_report(run_id="run_demo")

    assert payload["exists"] is True
    assert payload["source"] == "raw_json"
    assert payload["text"] == "审查正文来自 raw"
    assert payload["report_file_exists"] is False
    assert payload["raw_file_exists"] is True


def test_read_review_status_reports_artifact_presence(tmp_path, monkeypatch):
    run_dir = tmp_path / "run_demo"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "llm_review.status.json").write_text(
        json.dumps({"run_id": "run_demo", "status": "completed"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "llm_review.report.md").write_text("报告正文", encoding="utf-8")
    (run_dir / "llm_review.raw.json").write_text(json.dumps({"text": "raw"}), encoding="utf-8")
    monkeypatch.setattr(llm_analysis.storage, "resolve_run_dir", lambda run_id: run_dir)

    payload = llm_analysis.read_review_status(run_id="run_demo")

    assert payload["status"] == "completed"
    assert payload["report_exists"] is True
    assert payload["raw_exists"] is True
    assert payload["error_exists"] is False
    assert payload["report_source_hint"] == "report"


def test_review_run_with_llm_treats_empty_success_response_as_failed(tmp_path, monkeypatch):
    run_dir = tmp_path / "run_demo"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(json.dumps({"run_id": "run_demo"}), encoding="utf-8")
    (run_dir / "metrics.jsonl").write_text("{}", encoding="utf-8")
    (run_dir / "dataset.source.yaml").write_text("dataset_id: demo\n", encoding="utf-8")
    monkeypatch.setattr(llm_analysis.storage, "resolve_run_dir", lambda run_id: run_dir)
    monkeypatch.setattr(llm_analysis, "_read_ap_theory_core_text", lambda max_chars: "theory")
    monkeypatch.setattr(llm_analysis, "_read_extra_context", lambda max_chars: "context")
    monkeypatch.setattr(
        llm_analysis,
        "call_openai_chat_completions_stream",
        lambda **kwargs: {"success": True, "stream": True, "text": "", "data": None, "url": "https://example.invalid"},
    )
    monkeypatch.setattr(
        llm_analysis,
        "call_openai_chat_completions",
        lambda **kwargs: {"success": True, "data": {"choices": [{"message": {"content": ""}}]}},
    )

    result = llm_analysis.review_run_with_llm(
        run_id="run_demo",
        config=llm_analysis.LLMReviewConfig(
            enabled=True,
            base_url="https://example.invalid",
            model="demo-model",
        ),
    )

    assert result["success"] is False
    assert result["error"] == "empty_llm_response"
    status = json.loads((run_dir / "llm_review.status.json").read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["received_chars"] == 0
    assert status["stream_empty_fallback_attempted"] is True
    assert "empty_llm_response" in (run_dir / "llm_review.report.md").read_text(encoding="utf-8")


def test_review_run_with_llm_falls_back_when_stream_returns_empty(tmp_path, monkeypatch):
    run_dir = tmp_path / "run_demo"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(json.dumps({"run_id": "run_demo"}), encoding="utf-8")
    (run_dir / "metrics.jsonl").write_text("{}", encoding="utf-8")
    (run_dir / "dataset.source.yaml").write_text("dataset_id: demo\n", encoding="utf-8")
    monkeypatch.setattr(llm_analysis.storage, "resolve_run_dir", lambda run_id: run_dir)
    monkeypatch.setattr(llm_analysis, "_read_ap_theory_core_text", lambda max_chars: "theory")
    monkeypatch.setattr(llm_analysis, "_read_extra_context", lambda max_chars: "context")
    monkeypatch.setattr(
        llm_analysis,
        "call_openai_chat_completions_stream",
        lambda **kwargs: {"success": True, "stream": True, "text": "", "data": None, "url": "https://example.invalid"},
    )
    monkeypatch.setattr(
        llm_analysis,
        "call_openai_chat_completions",
        lambda **kwargs: {
            "success": True,
            "data": {"choices": [{"message": {"content": "非流式 fallback 审阅正文"}}]},
        },
    )

    result = llm_analysis.review_run_with_llm(
        run_id="run_demo",
        config=llm_analysis.LLMReviewConfig(
            enabled=True,
            base_url="https://example.invalid",
            model="demo-model",
        ),
    )

    assert result["success"] is True
    assert result["fallback_from_empty_stream"] is True
    assert (run_dir / "llm_review.report.md").read_text(encoding="utf-8").strip() == "非流式 fallback 审阅正文"
    status = json.loads((run_dir / "llm_review.status.json").read_text(encoding="utf-8"))
    assert status["stream_empty_fallback_attempted"] is True
    assert status["fallback_from_empty_stream"] is True
