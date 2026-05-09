# -*- coding: utf-8 -*-
"""
Observatory Experiment Utilities
================================

This package hosts the "paper-grade" experiment pipeline building blocks:
- episode dataset validation/expansion
- headless batch runner (future)
- tick metrics extraction (future)

Keeping these utilities under `observatory/` (instead of `tools/`) allows
the web UI to call them without depending on script-only modules.
"""

from . import io, storage
from . import llm_analysis
from .dataset import (
    DatasetValidationError,
    dataset_overview,
    dataset_protocol_doc,
    estimate_total_ticks,
    expand_dataset,
    summarize_expanded_tick_items,
    summarize_tick_counts,
    validate_and_normalize_dataset,
    validate_and_summarize_jsonl_text,
)
from .runner import RunOptions, export_expanded_ticks, load_dataset_ticks, make_run_id, run_dataset
from .storage import DatasetFileRef, clear_runs, delete_run, list_dataset_files, list_run_infos, list_runs, read_run_manifest
from .auto_tuner import (
    analyze_auto_tuner_with_llm,
    build_auto_tuner_rule_catalog,
    list_rollback_points,
    load_auto_tuner_llm_config,
    load_auto_tuner_public_config,
    load_auto_tuner_rules,
    read_auto_tuner_audit,
    read_auto_tuner_catalog,
    read_auto_tuner_state,
    rollback_to_point,
    save_auto_tuner_llm_config,
    save_auto_tuner_public_config,
    save_auto_tuner_rules,
)
from .llm_analysis import (
    LLMReviewConfig,
    load_review_config,
    read_review_report,
    read_review_status,
    review_run_with_llm,
    save_review_config,
)

__all__ = [
    "io",
    "storage",
    "llm_analysis",
    "DatasetFileRef",
    "DatasetValidationError",
    "RunOptions",
    "LLMReviewConfig",
    "analyze_auto_tuner_with_llm",
    "build_auto_tuner_rule_catalog",
    "clear_runs",
    "dataset_overview",
    "dataset_protocol_doc",
    "delete_run",
    "estimate_total_ticks",
    "expand_dataset",
    "export_expanded_ticks",
    "list_rollback_points",
    "load_review_config",
    "load_auto_tuner_llm_config",
    "load_auto_tuner_public_config",
    "load_auto_tuner_rules",
    "list_dataset_files",
    "list_run_infos",
    "list_runs",
    "load_dataset_ticks",
    "make_run_id",
    "read_auto_tuner_audit",
    "read_auto_tuner_catalog",
    "read_auto_tuner_state",
    "read_review_report",
    "read_review_status",
    "read_run_manifest",
    "rollback_to_point",
    "review_run_with_llm",
    "run_dataset",
    "save_auto_tuner_llm_config",
    "save_auto_tuner_public_config",
    "save_auto_tuner_rules",
    "save_review_config",
    "summarize_expanded_tick_items",
    "summarize_tick_counts",
    "validate_and_normalize_dataset",
    "validate_and_summarize_jsonl_text",
]
