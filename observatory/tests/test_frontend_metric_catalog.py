# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path


def _catalog_text() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / "observatory" / "frontend" / "src" / "data" / "metricCatalog.ts").read_text(encoding="utf-8")


def _page_text() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / "observatory" / "frontend" / "src" / "pages" / "ExperimentPage.tsx").read_text(encoding="utf-8")


def test_metric_catalog_marks_legacy_context_cs_and_map_as_diagnostics() -> None:
    text = _catalog_text()

    assert '"id": "context",\n    "label": "激活/旧上下文审计"' in text
    assert '"id": "stitching",\n    "label": "CS 回滚诊断"' in text
    assert '"id": "map",\n    "label": "MAP兼容诊断"' in text
    assert "正式 growth 身份优先看完整特征汇聚" in text
    assert "默认 growth + CS disabled 时，这张图全 0 是预期背景" in text
    assert "默认主口径请优先看感应生长 source-side ER 与 residual-side EV" in text
    assert '"id": "energy_balance_ratio_track"' in text
    assert '"title": "旧式虚实比诊断"' in text
    assert '"diagnostic": true' in text


def test_metric_catalog_exposes_growth_projection_and_guardrail_charts() -> None:
    text = _catalog_text()

    assert '"id": "induction_growth_projection"' in text
    assert '"id": "induction_growth_energy"' in text
    assert '"id": "induction_growth_guardrails"' in text
    assert "induction_growth_source_component_er_total" in text
    assert "induction_growth_residual_component_ev_total" in text
    assert "induction_growth_identity_shared_cache_hit_count" in text
    assert "induction_growth_identity_shared_cache_stale_count" in text
    assert "induction_growth_persistence_batch_enabled" in text
    assert "induction_growth_target_apply_ref_fast_merge_enabled" in text
    assert "induction_growth_target_apply_fast_ref_hit_merge_count" in text
    assert "induction_growth_target_apply_insert_log_suppressed_count" in text
    assert "induction_growth_memory_terminal_passthrough_count" in text
    assert "exact ref 命中快合并" in text
    assert "低能候选可被剪掉，纯虚/未绑定候选可暂存" in text


def test_metric_catalog_exposes_runtime_resolution_main_chart() -> None:
    text = _catalog_text()

    assert '"id": "runtime_resolution_state_pool"' in text
    assert "pool_runtime_resolution_degraded_item_count" in text
    assert "pool_runtime_resolution_active_component_count" in text
    assert "pool_runtime_resolution_dropped_component_count" in text
    assert "maintenance_runtime_resolution_refreshed_item_count" in text
    assert "maintenance_runtime_resolution_degraded_item_count" in text
    assert "不创建退化 HDB 身份" in text
    assert "完整 root identity" in text


def test_metric_catalog_exposes_induction_raw_residual_static_cache_metrics() -> None:
    text = _catalog_text()

    assert '"id": "induction_raw_residual_static_cache"' in text
    assert "induction_raw_residual_projection_profile_local_cache_hit_count" in text
    assert "induction_raw_residual_projection_profile_shared_cache_hit_count" in text
    assert "induction_raw_residual_exact_candidates_shared_cache_hit_count" in text
    assert "induction_raw_residual_component_candidates_shared_cache_hit_count" in text
    assert "induction_full_inclusion_shared_cache_hit_count" in text
    assert "entry runtime_weight" in text


def test_metric_catalog_exposes_stimulus_performance_optimization_counters() -> None:
    text = _catalog_text()

    assert '"id": "stimulus_transfer_residual_balance"' in text
    assert "stimulus_transfer_matched_total" in text
    assert "stimulus_final_residual_total" in text
    assert "stimulus_transfer_to_residual_ratio" in text
    assert "stimulus_effective_transfer_fraction_mean" in text
    assert '"id": "stimulus_growth_projection_balance"' in text
    assert "stimulus_object_projection_total" in text
    assert "stimulus_memory_tail_absorbed_total" in text
    assert "stimulus_unhandled_residual_total" in text
    assert "stimulus_object_projection_dominates_unhandled_residual" in text
    assert "stimulus_early_stop_object_projection_dominance_triggered" in text
    assert "stimulus_early_stop_object_projection_dominance_ratio" in text
    assert '"id": "stimulus_object_projection_stop_guard"' in text
    assert "stimulus_early_stop_object_projection_transfer_guard_blocked_count" in text
    assert "stimulus_early_stop_object_projection_transfer_ratio_at_stop" in text
    assert "多数 source tick" in text
    assert '"id": "stimulus_candidate_cost"' in text
    assert "stimulus_cut_common_part_total_count" in text
    assert "stimulus_cut_exact_fast_path_hit_count" in text
    assert "stimulus_cut_full_inclusion_fast_path_hit_count" in text
    assert "stimulus_cut_single_group_fast_path_hit_count" in text
    assert "stimulus_cut_ordered_subsequence_fast_path_hit_count" in text
    assert "stimulus_cut_cache_zero_copy_hit_count" in text
    assert "stimulus_cut_normalize_cache_hit_count" in text
    assert "stimulus_shadow_raw_residual_skipped_count" in text
    assert "单共现组" in text
    assert "有序子序列" in text
    assert "promotion 关闭时影子残差精评分可默认跳过" in text


def test_metric_catalog_exposes_runtime_residual_promotion_fast_path_counters() -> None:
    text = _catalog_text()

    assert '"id": "runtime_residual_promotion"' in text
    assert "runtime_residual_promotion_exact_rebind_count" in text
    assert "runtime_residual_promotion_full_identity_count" in text
    assert "runtime_residual_promotion_hdb_fallback_count" in text
    assert "residual_tail_memory_projection_handled" in text
    assert "此项保留为 legacy 诊断" in text


def test_metric_catalog_exposes_cache_neutralization_cut_cache_metrics() -> None:
    text = _catalog_text()

    assert '"id": "cache_neutralization_cut_cache"' in text
    assert "cache_priority_cut_cache_hit_count" in text
    assert "cache_priority_cut_cache_zero_copy_hit_count" in text
    assert "cache_priority_cut_single_group_fast_path_hit_count" in text
    assert "priority_neutralization_common_part_cache_enabled" in text
    assert "不改变 SA 粒度能量结算" in text


def test_experiment_page_defaults_to_hiding_diagnostic_charts() -> None:
    text = _page_text()

    assert "showDiagnosticCharts: false" in text
    assert "isDiagnosticChartConfig" in text
    assert "!showDiagnosticCharts && isDiagnosticChartConfig(cfg)" in text
    assert "显示诊断/旧口径" in text
    assert "默认优先展示新版 growth 主口径" in text
