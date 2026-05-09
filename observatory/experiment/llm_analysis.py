# -*- coding: utf-8 -*-
"""
LLM Review (Post-Run)
====================

This module provides an OpenAI-compatible "reviewer" pipeline:
- Read a completed experiment run (manifest + metrics + dataset)
- Inject AP theory core text
- Ask an external LLM to produce a rigorous, evidence-bound, actionable report

Notes:
- The Observatory is local-first; we store secrets under `observatory/outputs/`
  (gitignored) instead of committing them into repo config files.
- We intentionally keep the request shape compatible with OpenAI-style
  `/v1/chat/completions` endpoints so users can point to OpenAI or any
  compatible proxy.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import storage


LLM_REVIEW_EFFECTIVE_PROMPT_CHAR_CAP = 260_000


@dataclass(frozen=True)
class LLMReviewConfig:
    enabled: bool = False
    auto_analyze_on_completion: bool = False
    base_url: str = "https://api.openai.com"
    api_key: str = ""
    model: str = ""
    temperature: float = 0.2
    max_prompt_chars: int = 900_000
    timeout_sec: int = 240
    max_completion_tokens: int = 4096

    def to_public_dict(self) -> dict[str, Any]:
        """Safe for front-end: do not include api_key."""
        return {
            "enabled": bool(self.enabled),
            "auto_analyze_on_completion": bool(self.auto_analyze_on_completion),
            "auto_review_on_completion": bool(self.auto_analyze_on_completion),
            "base_url": str(self.base_url or ""),
            "api_key_masked": mask_api_key(self.api_key),
            "model": str(self.model or ""),
            "temperature": float(self.temperature),
            "max_prompt_chars": int(self.max_prompt_chars),
            "timeout_sec": int(self.timeout_sec),
            "max_completion_tokens": int(self.max_completion_tokens),
        }


def mask_api_key(value: str) -> str:
    v = str(value or "").strip()
    if not v:
        return ""
    if len(v) <= 8:
        return "*" * len(v)
    return f"{v[:3]}...{v[-4:]}"


def _config_path() -> Path:
    # Store secrets in outputs/ (gitignored).
    return storage.repo_root() / "observatory" / "outputs" / "llm_review_config.json"


def load_review_config() -> LLMReviewConfig:
    path = _config_path()
    cfg = LLMReviewConfig()
    if not path.exists():
        return cfg
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return cfg
    if not isinstance(raw, dict):
        return cfg

    def _b(key: str, default: bool) -> bool:
        try:
            return bool(raw.get(key, default))
        except Exception:
            return bool(default)

    def _s(key: str, default: str) -> str:
        try:
            return str(raw.get(key, default) or "").strip() or str(default or "")
        except Exception:
            return str(default or "")

    def _f(key: str, default: float) -> float:
        try:
            return float(raw.get(key, default))
        except Exception:
            return float(default)

    def _i(key: str, default: int) -> int:
        try:
            return int(raw.get(key, default))
        except Exception:
            return int(default)

    return LLMReviewConfig(
        enabled=_b("enabled", cfg.enabled),
        auto_analyze_on_completion=(
            _b("auto_analyze_on_completion", cfg.auto_analyze_on_completion)
            if "auto_analyze_on_completion" in raw
            else _b("auto_review_on_completion", cfg.auto_analyze_on_completion)
        ),
        base_url=_s("base_url", cfg.base_url),
        api_key=_s("api_key", cfg.api_key),
        model=_s("model", cfg.model),
        temperature=_f("temperature", cfg.temperature),
        max_prompt_chars=_i("max_prompt_chars", cfg.max_prompt_chars),
        timeout_sec=_i("timeout_sec", cfg.timeout_sec),
        max_completion_tokens=_i("max_completion_tokens", cfg.max_completion_tokens),
    )


def save_review_config(updates: dict[str, Any]) -> LLMReviewConfig:
    """Persist review config under outputs/. api_key can be omitted to keep current."""
    current = load_review_config()
    updates = updates if isinstance(updates, dict) else {}

    def _pick_bool(key: str, default: bool) -> bool:
        if key not in updates:
            return bool(default)
        try:
            return bool(updates.get(key))
        except Exception:
            return bool(default)

    def _pick_bool_alias(keys: tuple[str, ...], default: bool) -> bool:
        for key in keys:
            if key not in updates:
                continue
            try:
                return bool(updates.get(key))
            except Exception:
                return bool(default)
        return bool(default)

    def _pick_str(key: str, default: str) -> str:
        if key not in updates:
            return str(default or "")
        try:
            return str(updates.get(key) or "").strip()
        except Exception:
            return str(default or "")

    def _pick_float(key: str, default: float) -> float:
        if key not in updates:
            return float(default)
        try:
            return float(updates.get(key))
        except Exception:
            return float(default)

    def _pick_int(key: str, default: int) -> int:
        if key not in updates:
            return int(default)
        try:
            return int(updates.get(key))
        except Exception:
            return int(default)

    new_api_key = current.api_key
    if "api_key" in updates:
        candidate = _pick_str("api_key", "")
        # Empty means "keep existing" (front-end can submit blank to avoid retyping).
        if candidate:
            new_api_key = candidate

    merged = LLMReviewConfig(
        enabled=_pick_bool("enabled", current.enabled),
        auto_analyze_on_completion=_pick_bool_alias(
            ("auto_analyze_on_completion", "auto_review_on_completion"),
            current.auto_analyze_on_completion,
        ),
        base_url=_pick_str("base_url", current.base_url),
        api_key=str(new_api_key or ""),
        model=_pick_str("model", current.model),
        temperature=_pick_float("temperature", current.temperature),
        max_prompt_chars=_pick_int("max_prompt_chars", current.max_prompt_chars),
        timeout_sec=_pick_int("timeout_sec", current.timeout_sec),
        max_completion_tokens=_pick_int("max_completion_tokens", current.max_completion_tokens),
    )

    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "enabled": bool(merged.enabled),
        "auto_analyze_on_completion": bool(merged.auto_analyze_on_completion),
        "base_url": str(merged.base_url or ""),
        "api_key": str(merged.api_key or ""),
        "model": str(merged.model or ""),
        "temperature": float(merged.temperature),
        "max_prompt_chars": int(merged.max_prompt_chars),
        "timeout_sec": int(merged.timeout_sec),
        "max_completion_tokens": int(merged.max_completion_tokens),
        "updated_at_ms": int(time.time() * 1000),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def _safe_read_text(path: Path, *, max_chars: int | None = None) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""
    if max_chars is not None and max_chars > 0 and len(text) > int(max_chars):
        return text[: int(max_chars)]
    return text


def _safe_read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _extract_report_text_from_raw_payload(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("text", "report_markdown", "report_text", "output_text", "content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        choices = payload.get("choices")
        if isinstance(choices, list):
            for item in choices:
                if not isinstance(item, dict):
                    continue
                message = item.get("message")
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content
    return ""


def _join_base_url(base_url: str, path: str) -> str:
    base = str(base_url or "").strip()
    if not base:
        base = "https://api.openai.com"
    base = base.rstrip("/")
    p = "/" + str(path or "").lstrip("/")
    return base + p


def _clip_long_metrics_line(line: str, max_chars: int) -> str:
    text = str(line or "")
    budget = int(max(160, max_chars))
    if len(text) <= budget:
        return text
    marker = f"...[line_truncated omitted_chars={len(text) - budget}]..."
    keep = max(0, budget - len(marker))
    head_keep = max(1, int(keep * 0.68))
    tail_keep = max(0, keep - head_keep)
    if tail_keep <= 0:
        return text[:head_keep] + marker
    return text[:head_keep] + marker + text[-tail_keep:]


def _round_metric_value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if value != value:
            return None
        return round(float(value), 6)
    return value


def _short_metric_text(value: Any, *, max_chars: int = 80) -> str:
    text = str(value or "")
    text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 12)] + "...[cut]"


def _compact_mapping_numbers(
    value: Any,
    *,
    limit: int | None = None,
    include_zero: bool = True,
    key_filter: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    count = 0
    for key, item in value.items():
        key_text = str(key)
        if key_filter is not None and key_text not in key_filter:
            continue
        if limit is not None and count >= int(limit):
            break
        if isinstance(item, (int, float, bool)):
            if not include_zero and abs(float(item)) <= 1e-12:
                continue
            out[key_text] = _round_metric_value(item)
            count += 1
        elif item is None:
            if not include_zero:
                continue
            out[key_text] = None
            count += 1
        elif isinstance(item, str) and len(item) <= 96:
            out[key_text] = item
            count += 1
    return out


def _compact_shape_counts(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: list[Any] = []
    for axis in ("er", "ev", "cp"):
        item = value.get(axis)
        if not isinstance(item, dict):
            out.append([])
            continue
        # Compact tuple: [top_count, structure, atomic_sa, action_node, attribute].
        out.append([
            item.get("count"),
            item.get("structure_count"),
            item.get("atomic_sa_count"),
            item.get("action_node_count"),
            item.get("attribute_count"),
        ])
    return out


def _compact_curriculum_top_item(item: Any, *, max_display_chars: int = 36) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"txt": _short_metric_text(item, max_chars=max_display_chars)}
    out = {
        "r": item.get("rank"),
        "ref": item.get("ref") or (
            f"{item.get('ref_object_type')}:{item.get('ref_object_id')}"
            if item.get("ref_object_type") or item.get("ref_object_id")
            else ""
        ),
        "type": item.get("ref_object_type") or item.get("type"),
        "txt": _short_metric_text(item.get("display"), max_chars=max_display_chars),
        "er": _round_metric_value(item.get("er")),
        "ev": _round_metric_value(item.get("ev")),
        "cp": _round_metric_value(item.get("cp")),
    }
    return {key: value for key, value in out.items() if value not in ("", None)}


def _compact_curriculum_top_list(value: Any, *, limit: int = 1) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_compact_curriculum_top_item(item) for item in value[: max(0, int(limit))]]


def _compact_curriculum_top_array(value: Any) -> list[Any]:
    item = value[0] if isinstance(value, list) and value else None
    if not isinstance(item, dict):
        return []
    ref = item.get("ref") or (
        f"{item.get('ref_object_type')}:{item.get('ref_object_id')}"
        if item.get("ref_object_type") or item.get("ref_object_id")
        else ""
    )
    return [
        ref,
        item.get("ref_object_type") or item.get("type"),
        item.get("context_owner_structure_id") or item.get("context_ref"),
        _round_metric_value(item.get("semantic_signature_len")),
        _round_metric_value(item.get("ref_alias_count")),
        _short_metric_text(item.get("display"), max_chars=24),
        _round_metric_value(item.get("er")),
        _round_metric_value(item.get("ev")),
        _round_metric_value(item.get("cp")),
    ]


def _compact_curriculum_values(value: Any, keys: list[str]) -> list[Any]:
    mapping = value if isinstance(value, dict) else {}
    return [_round_metric_value(mapping.get(key)) for key in keys]


def _compact_curriculum_sparse_values(value: Any, keys: list[str], *, include_zero: bool = False) -> list[list[Any]]:
    mapping = value if isinstance(value, dict) else {}
    out: list[list[Any]] = []
    for idx, key in enumerate(keys):
        if key not in mapping:
            continue
        item = _round_metric_value(mapping.get(key))
        if item is None:
            continue
        if not include_zero and isinstance(item, (int, float)) and abs(float(item)) <= 1e-12:
            continue
        out.append([idx, item])
    return out


def _compact_curriculum_top5_quality(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: list[Any] = []
    for axis in ("er", "ev", "cp"):
        item = value.get(axis)
        if not isinstance(item, dict):
            out.append([])
            continue
        out.append([
            _round_metric_value(item.get("structure_ratio")),
            _round_metric_value(item.get("atomic_sa_ratio")),
            _round_metric_value(item.get("action_node_ratio")),
            _round_metric_value(item.get("attribute_ratio")),
            _round_metric_value(item.get("long_structure_count")),
            _round_metric_value(item.get("char_fragment_like_count")),
            _round_metric_value(item.get("mean_signature_len")),
            _short_metric_text(item.get("dominant_context_owner_structure_id"), max_chars=28),
            _round_metric_value(item.get("dominant_context_owner_share")),
        ])
    return out


def _compact_curriculum_top5_roots(value: Any) -> list[Any]:
    if not isinstance(value, dict):
        return []
    out: list[Any] = []
    for axis in ("er", "ev", "cp"):
        item = value.get(axis)
        if not isinstance(item, dict):
            out.append([])
            continue
        out.append([
            _round_metric_value(item.get("unique_root_count")),
            _round_metric_value(item.get("duplicate_root_count")),
            _short_metric_text(item.get("dominant_root_id"), max_chars=24),
            _round_metric_value(item.get("dominant_root_share")),
        ])
    return out


def _compact_curriculum_snapshot(item: Any) -> list[Any]:
    if not isinstance(item, dict):
        return []
    identity = item.get("identity_at_tick") if isinstance(item.get("identity_at_tick"), dict) else {}
    action_weather = item.get("action_weather_at_tick") if isinstance(item.get("action_weather_at_tick"), dict) else {}
    ratios = identity.get("ratios") if isinstance(identity.get("ratios"), dict) else {}
    overlap = item.get("overlap_with_previous_snapshot") if isinstance(item.get("overlap_with_previous_snapshot"), dict) else {}
    root_overlap = (
        item.get("root_overlap_with_previous_snapshot")
        if isinstance(item.get("root_overlap_with_previous_snapshot"), dict)
        else {}
    )
    weather_keys = [
        "iesm_action_trigger_weather_stub_count",
        "action_node_weather_stub_count",
        "action_drive_weather_stub_max",
        "action_effective_threshold_weather_stub_mean",
        "action_attempted_weather_stub_source_visible",
        "action_scheduled_weather_stub_source_visible",
        "action_executed_weather_stub_source_visible",
    ]
    return [
        item.get("source_dataset_tick_index"),
        item.get("tick_index"),
        1 if bool(item.get("input_is_empty", False)) else 0,
        _short_metric_text(item.get("input_text_preview"), max_chars=30),
        _compact_shape_counts(item.get("pool_shape_counts")),
        _compact_curriculum_top5_quality(item.get("top5_quality")),
        _compact_curriculum_top5_roots(item.get("top5_root_summary")),
        [
            _round_metric_value((overlap.get(axis) or {}).get("jaccard"))
            if isinstance(overlap.get(axis), dict)
            else None
            for axis in ("er", "ev", "cp")
        ],
        [
            _round_metric_value((root_overlap.get(axis) or {}).get("jaccard"))
            if isinstance(root_overlap.get(axis), dict)
            else None
            for axis in ("er", "ev", "cp")
        ],
        [
            _round_metric_value(identity.get("target_count")),
            _round_metric_value(identity.get("hit_count")),
            _round_metric_value(identity.get("created_count")),
            _round_metric_value(identity.get("shared_cache_hit_count")),
            _round_metric_value(identity.get("local_cache_hit_count")),
            _round_metric_value(ratios.get("created_to_target")),
            _round_metric_value(ratios.get("shared_cache_hit_to_target")),
            _round_metric_value(ratios.get("hit_to_target")),
        ],
        _compact_curriculum_values(action_weather, weather_keys),
        _compact_curriculum_top_array(item.get("pool_er_top5")),
        _compact_curriculum_top_array(item.get("pool_ev_top5")),
        _compact_curriculum_top_array(item.get("pool_cp_top5")),
    ]


def _compact_curriculum_stat(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    keys = ("count", "nonzero_count", "min", "max", "mean", "p50", "p95", "latest", "sum")
    out: dict[str, Any] = {}
    for key in keys:
        if key in value:
            out[key] = _round_metric_value(value.get(key))
    return out


def _compact_curriculum_stats_map(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            compact = {
                metric: _round_metric_value(item.get(metric))
                for metric in ("nonzero_count", "mean", "p95", "latest", "sum")
                if metric in item
            }
            if compact:
                out[str(key)] = compact
    return out


def _compact_curriculum_segment(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return []
    stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
    def _stat_pair(key: str) -> dict[str, Any]:
        stat = stats.get(key)
        if not isinstance(stat, dict):
            return []
        return [
            _round_metric_value(stat.get("mean")),
            _round_metric_value(stat.get("p95")),
            _round_metric_value(stat.get("sum")),
        ]
    identity = item.get("identity_maturation") if isinstance(item.get("identity_maturation"), dict) else {}
    identity_ratios = identity.get("ratios") if isinstance(identity.get("ratios"), dict) else {}
    identity_resolution = item.get("identity_resolution") if isinstance(item.get("identity_resolution"), dict) else {}
    resolution_ratios = (
        identity_resolution.get("ratios") if isinstance(identity_resolution.get("ratios"), dict) else {}
    )
    resolution_totals = (
        identity_resolution.get("totals") if isinstance(identity_resolution.get("totals"), dict) else {}
    )
    hdb = item.get("hdb_growth") if isinstance(item.get("hdb_growth"), dict) else {}
    stat_keys = [
        "induction_growth_target_count",
        "induction_growth_identity_created_count",
        "induction_growth_identity_hit_count",
        "induction_growth_identity_shared_cache_hit_count",
        "induction_growth_identity_create_exact_lookup_skipped_count",
        "induction_growth_pruned_low_energy_count",
        "pool_ev_to_er_ratio",
        "stimulus_object_projection_total",
        "stimulus_memory_tail_absorbed_total",
        "pool_runtime_resolution_degraded_item_count",
        "attention_energy_budget",
        "action_threshold_nt_scale_mean",
        "action_threshold_rwd_pun_scale_mean",
        "action_learning_reward_drive_gain_total",
        "cfs_dissonance_live_total_energy",
        "cfs_expectation_live_total_energy",
        "nt_DA",
        "nt_ADR",
        "timing_total_logic_ms",
        "timing_stimulus_level_ms",
    ]
    return [
        item.get("segment_index"),
        item.get("source_tick_start"),
        item.get("source_tick_end"),
        item.get("rows"),
        item.get("source_rows"),
        item.get("synthetic_rows"),
        [
            _round_metric_value(identity_ratios.get("created_to_target")),
            _round_metric_value(identity_ratios.get("shared_cache_hit_to_target")),
            _round_metric_value(identity_ratios.get("local_cache_hit_to_target")),
            _round_metric_value(identity_ratios.get("hit_to_target")),
        ],
        [
            _round_metric_value(resolution_ratios.get("create_exact_lookup_skipped_to_created")),
            _round_metric_value(resolution_ratios.get("lookup_disabled_to_target")),
            _round_metric_value(resolution_ratios.get("shared_cache_stale_to_target")),
            _round_metric_value(resolution_totals.get("created_not_explained_by_create_exact_skip")),
        ],
        [
            _round_metric_value(hdb.get("structure_count_delta")),
            _round_metric_value(hdb.get("delta_per_source_row")),
            _round_metric_value(hdb.get("structure_count_latest")),
        ],
        [_stat_pair(key) for key in stat_keys],
    ]


def _compact_curriculum_performance_diagnostic(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    timing = value.get("timing_breakdown") if isinstance(value.get("timing_breakdown"), dict) else {}
    keep_timing = {
        key: _compact_curriculum_stat(timing.get(key))
        for key in [
            "timing_total_logic_ms",
            "timing_stimulus_level_ms",
            "timing_induction_and_memory_ms",
            "timing_induction_hdb_propagation_ms",
            "timing_induction_projection_prepare_ms",
            "timing_induction_target_apply_ms",
            "timing_cache_neutralization_ms",
            "timing_attention_ms",
            "timing_memory_runtime_projection_ms",
        ]
        if isinstance(timing.get(key), dict)
    }

    segment_items = value.get("segment_timing_trend") if isinstance(value.get("segment_timing_trend"), list) else []
    compact_segments = []
    for item in segment_items[:20]:
        if not isinstance(item, dict):
            continue
        hdb = item.get("hdb_growth") if isinstance(item.get("hdb_growth"), dict) else {}
        total_stats = item.get("timing_total_logic_ms") if isinstance(item.get("timing_total_logic_ms"), dict) else {}
        stimulus_stats = (
            item.get("timing_stimulus_level_ms") if isinstance(item.get("timing_stimulus_level_ms"), dict) else {}
        )
        induction_stats = (
            item.get("timing_induction_and_memory_ms")
            if isinstance(item.get("timing_induction_and_memory_ms"), dict)
            else {}
        )
        compact_segments.append(
            [
                item.get("segment_index"),
                item.get("source_tick_start"),
                item.get("source_tick_end"),
                item.get("source_rows"),
                _round_metric_value(total_stats.get("mean")),
                _round_metric_value(total_stats.get("p95")),
                _round_metric_value(stimulus_stats.get("mean")),
                _round_metric_value(stimulus_stats.get("p95")),
                _round_metric_value(induction_stats.get("mean")),
                _round_metric_value(induction_stats.get("p95")),
                _round_metric_value(hdb.get("structure_count_delta")),
                _round_metric_value(hdb.get("structure_count_latest")),
            ]
        )

    slow_items = (
        value.get("slowest_ticks_by_total_logic_ms")
        if isinstance(value.get("slowest_ticks_by_total_logic_ms"), list)
        else []
    )
    compact_slow = []
    for item in slow_items[:12]:
        if not isinstance(item, dict):
            continue
        compact_slow.append(
            [
                item.get("tick_index"),
                item.get("source_dataset_tick_index"),
                1 if bool(item.get("synthetic_tick")) else 0,
                1 if bool(item.get("input_is_empty")) else 0,
                _short_metric_text(item.get("input_text_preview"), max_chars=40),
                _round_metric_value(item.get("timing_total_logic_ms")),
                _round_metric_value(item.get("timing_stimulus_level_ms")),
                _round_metric_value(item.get("timing_induction_and_memory_ms")),
                _round_metric_value(item.get("timing_induction_hdb_propagation_ms")),
                _round_metric_value(item.get("hdb_structure_count")),
                _round_metric_value(item.get("induction_growth_target_count")),
                _round_metric_value(item.get("induction_growth_identity_created_count")),
                _round_metric_value(item.get("induction_growth_identity_shared_cache_hit_count")),
                _round_metric_value(item.get("stimulus_best_match_candidate_count")),
                _round_metric_value(item.get("stimulus_shadow_raw_residual_candidate_count")),
                _round_metric_value(item.get("stimulus_cut_common_part_total_count")),
                _round_metric_value(item.get("stimulus_cut_cache_store_count")),
                _round_metric_value(item.get("stimulus_cut_normalize_reusable_group_count")),
                _round_metric_value(item.get("stimulus_owner_local_residual_fuzzy_equivalent_call_count")),
            ]
        )

    corr_items = (
        value.get("top_correlated_metrics_with_total_logic_ms")
        if isinstance(value.get("top_correlated_metrics_with_total_logic_ms"), list)
        else []
    )
    compact_corr = []
    for item in corr_items[:20]:
        if not isinstance(item, dict):
            continue
        compact_corr.append(
            [
                _short_metric_text(item.get("key"), max_chars=72),
                _round_metric_value(item.get("corr_with_total_logic_ms")),
                _round_metric_value(item.get("sum")),
                _round_metric_value(item.get("max")),
            ]
        )

    return {
        "available": bool(value.get("available", False)),
        "interpretation_hints": value.get("interpretation_hints") if isinstance(value.get("interpretation_hints"), list) else [],
        "completion_timing": value.get("completion_timing") if isinstance(value.get("completion_timing"), dict) else {},
        "hdb_first_latest_delta": [
            _round_metric_value(value.get("hdb_structure_count_first_source_tick")),
            _round_metric_value(value.get("hdb_structure_count_latest_source_tick")),
            _round_metric_value(value.get("hdb_structure_count_delta_source_ticks")),
        ],
        "timing_breakdown": keep_timing,
        "segment_timing_schema": [
            "segment_index",
            "source_tick_start",
            "source_tick_end",
            "source_rows",
            "total_mean",
            "total_p95",
            "stimulus_mean",
            "stimulus_p95",
            "induction_mean",
            "induction_p95",
            "hdb_delta",
            "hdb_latest",
        ],
        "segment_timing_trend": compact_segments,
        "slowest_tick_schema": [
            "tick_index",
            "source_dataset_tick_index",
            "synthetic_0_1",
            "input_empty_0_1",
            "input_preview",
            "total_ms",
            "stimulus_ms",
            "induction_ms",
            "induction_hdb_ms",
            "hdb_count",
            "growth_target",
            "identity_created",
            "identity_shared_cache",
            "stim_best_candidate",
            "stim_shadow_candidate",
            "stim_cut_common",
            "stim_cut_cache_store",
            "stim_norm_reusable_groups",
            "stim_fuzzy_calls",
        ],
        "slowest_ticks_by_total_logic_ms": compact_slow,
        "correlation_schema": ["metric_key", "corr_with_total_logic_ms", "sum", "max"],
        "top_correlated_metrics_with_total_logic_ms": compact_corr,
    }


def _compact_curriculum_window_row(item: Any) -> list[Any]:
    if not isinstance(item, dict):
        return []
    weather_keys = {
        "iesm_action_trigger_weather_stub_count",
        "action_node_weather_stub_count",
        "action_drive_weather_stub_max",
        "action_effective_threshold_weather_stub_mean",
        "action_drive_margin_weather_stub_max",
        "action_attempted_weather_stub_source_visible",
        "action_scheduled_weather_stub_source_visible",
        "action_executed_weather_stub_source_visible",
    }
    cfs_keys = {
        "teacher_applied_count",
        "teacher_rwd",
        "teacher_pun",
        "reward_signal_live_total_energy",
        "punish_signal_live_total_energy",
        "cfs_expectation_live_total_energy",
        "cfs_pressure_live_total_energy",
        "cfs_dissonance_live_total_energy",
        "cfs_correctness_live_total_energy",
        "cfs_correct_event_live_total_energy",
        "cfs_grasp_live_total_energy",
        "cfs_relief_live_total_energy",
    }
    nt_attention_action_keys = {
        "nt_DA",
        "nt_ADR",
        "nt_COR",
        "nt_NOV",
        "nt_FOC",
        "attention_energy_budget",
        "attention_net_delta_energy",
        "action_threshold_nt_scale_mean",
        "action_threshold_rwd_pun_scale_mean",
        "action_learning_reward_drive_gain_total",
        "action_learning_punish_drive_penalty_total",
    }
    weather_order = [key for key in sorted(weather_keys)]
    cfs_order = [key for key in sorted(cfs_keys)]
    nt_attention_action_order = [key for key in sorted(nt_attention_action_keys)]
    return [
        item.get("source_dataset_tick_index"),
        item.get("tick_index"),
        1 if bool(item.get("input_is_empty", False)) else 0,
        _short_metric_text(item.get("input_text_preview"), max_chars=22),
        _compact_curriculum_sparse_values(item.get("weather"), weather_order),
        _compact_curriculum_sparse_values(item.get("cfs_reward_punish"), cfs_order),
        _compact_curriculum_sparse_values(item.get("nt_attention_action"), nt_attention_action_order),
    ]


def _compact_curriculum_contract_window(item: Any) -> list[Any]:
    if not isinstance(item, dict):
        return []
    rows = item.get("rows") if isinstance(item.get("rows"), list) else []
    aggregate_keys = {
        "iesm_action_trigger_weather_stub_count",
        "iesm_action_trigger_weather_stub_count_source_visible",
        "action_node_weather_stub_count",
        "action_drive_weather_stub_max",
        "action_effective_threshold_weather_stub_mean",
        "action_drive_margin_weather_stub_max",
        "action_attempted_weather_stub_source_visible",
        "action_scheduled_weather_stub_source_visible",
        "action_executed_weather_stub_source_visible",
        "teacher_applied_count",
        "teacher_rwd",
        "teacher_pun",
        "reward_signal_live_total_energy",
        "punish_signal_live_total_energy",
        "cfs_expectation_live_total_energy",
        "cfs_pressure_live_total_energy",
        "cfs_dissonance_live_total_energy",
        "cfs_correctness_live_total_energy",
        "cfs_correct_event_live_total_energy",
        "cfs_grasp_live_total_energy",
        "cfs_relief_live_total_energy",
        "nt_DA",
        "nt_ADR",
        "nt_OXY",
        "nt_SER",
        "nt_END",
        "nt_COR",
        "nt_NOV",
        "nt_FOC",
        "attention_energy_budget",
        "attention_net_delta_energy",
        "attention_mod_attention_energy_budget",
        "action_threshold_scale_mean",
        "action_threshold_nt_scale_mean",
        "action_threshold_rwd_pun_scale_mean",
        "action_threshold_fatigue_scale_mean",
        "action_learning_reward_drive_gain_total",
        "action_learning_punish_drive_penalty_total",
        "action_learning_threshold_delta_mean",
        "action_learning_threshold_delta_sum",
    }
    selected_rows = rows[:1] + rows[-1:] if len(rows) > 1 else rows[:1]
    aggregate_order = [key for key in sorted(aggregate_keys)]
    matched = item.get("matched_detail") if isinstance(item.get("matched_detail"), list) else []
    matched_compact = []
    for entry in matched[:3]:
        if not isinstance(entry, dict):
            continue
        detail = entry.get("detail") if isinstance(entry.get("detail"), dict) else {}
        matched_compact.append(
            [
                entry.get("kind"),
                1 if bool(entry.get("matched", False)) else 0,
                detail.get("metric"),
                _round_metric_value(detail.get("current")),
                _round_metric_value(detail.get("target")),
            ]
        )
    causal = item.get("causal_chain_summary") if isinstance(item.get("causal_chain_summary"), dict) else {}
    weather_action = causal.get("weather_action") if isinstance(causal.get("weather_action"), dict) else {}
    cfs_reward = causal.get("cfs_reward_punish") if isinstance(causal.get("cfs_reward_punish"), dict) else {}
    nt_threshold = causal.get("nt_attention_threshold") if isinstance(causal.get("nt_attention_threshold"), dict) else {}
    chain_flags = causal.get("chain_flags") if isinstance(causal.get("chain_flags"), dict) else {}
    causal_compact = [
        [
            _round_metric_value(weather_action.get("trigger_source_visible_sum")),
            _round_metric_value(weather_action.get("ready_sum")),
            _round_metric_value(weather_action.get("attempted_source_visible_sum")),
            _round_metric_value(weather_action.get("scheduled_source_visible_sum")),
            _round_metric_value(weather_action.get("executed_source_visible_sum")),
            weather_action.get("first_trigger_tick"),
            weather_action.get("first_attempt_tick"),
            weather_action.get("first_scheduled_tick"),
            weather_action.get("first_executed_tick"),
            _round_metric_value(weather_action.get("max_drive")),
            _round_metric_value(weather_action.get("max_threshold")),
            _round_metric_value(weather_action.get("max_margin")),
        ],
        [
            _round_metric_value(cfs_reward.get("teacher_applied_sum")),
            _round_metric_value(cfs_reward.get("teacher_reward_sum")),
            _round_metric_value(cfs_reward.get("teacher_punish_sum")),
            _round_metric_value(cfs_reward.get("reward_live_max")),
            _round_metric_value(cfs_reward.get("punish_live_max")),
            _round_metric_value(cfs_reward.get("expectation_live_max")),
            _round_metric_value(cfs_reward.get("pressure_live_max")),
            _round_metric_value(cfs_reward.get("dissonance_live_max")),
            _round_metric_value(cfs_reward.get("correct_event_live_max")),
        ],
        [
            _round_metric_value(nt_threshold.get("attention_budget_max")),
            _round_metric_value(nt_threshold.get("threshold_scale_max")),
            _round_metric_value(nt_threshold.get("threshold_nt_scale_max")),
            _round_metric_value(nt_threshold.get("threshold_rwd_pun_scale_max")),
            _round_metric_value(nt_threshold.get("threshold_fatigue_scale_max")),
            _round_metric_value(nt_threshold.get("learning_reward_drive_gain_sum")),
            _round_metric_value(nt_threshold.get("learning_punish_drive_penalty_sum")),
            _round_metric_value(nt_threshold.get("learning_threshold_delta_sum")),
        ],
        [
            1 if bool(chain_flags.get("trigger_to_attempt")) else 0,
            1 if bool(chain_flags.get("attempt_to_execute")) else 0,
            1 if bool(chain_flags.get("trigger_to_no_execute")) else 0,
            1 if bool(chain_flags.get("reward_or_expectation_present")) else 0,
            1 if bool(chain_flags.get("punish_or_pressure_present")) else 0,
            1 if bool(chain_flags.get("nt_present")) else 0,
        ],
    ]
    return [
        _short_metric_text(item.get("contract_id"), max_chars=52),
        _short_metric_text(item.get("spec_id"), max_chars=32),
        item.get("outcome"),
        item.get("source_dataset_tick_start"),
        item.get("source_dataset_tick_settled"),
        item.get("deadline_source_tick_cursor"),
        matched_compact,
        item.get("window_row_count"),
        causal_compact,
        _compact_curriculum_sparse_values(item.get("aggregate_sum"), aggregate_order),
        _compact_curriculum_sparse_values(item.get("aggregate_max"), aggregate_order),
        [_compact_curriculum_window_row(row) for row in selected_rows],
    ]


def _compact_curriculum_metrics_summary(data: Any, *, original_chars: int, budget: int) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {
            "format": "curriculum_metrics_summary_compact_for_llm_review_v1",
            "error": "source summary is not a JSON object",
        }
    top5_items = ((data.get("top5_snapshots") or {}).get("items") or []) if isinstance(data.get("top5_snapshots"), dict) else []
    window_items = (
        ((data.get("expectation_contract_windows") or {}).get("items") or [])
        if isinstance(data.get("expectation_contract_windows"), dict)
        else []
    )
    segment_items = ((data.get("segments") or {}).get("items") or []) if isinstance(data.get("segments"), dict) else []
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    critical_aliases = {
        "ev_er": "pool_ev_to_er_ratio",
        "internal_sa": "internal_sa_count",
        "hdb_count": "hdb_structure_count",
        "hdb_group": "hdb_group_count",
        "hdb_signature_index": "hdb_signature_index_count",
        "hdb_contextual_structure": "hdb_contextual_structure_count",
        "hdb_same_content_multi_context": "hdb_same_content_multi_context_count",
        "grow_target": "induction_growth_target_count",
        "grow_hit": "induction_growth_identity_hit_count",
        "grow_created": "induction_growth_identity_created_count",
        "grow_shared": "induction_growth_identity_shared_cache_hit_count",
        "identity_lookup_disabled": "induction_growth_identity_lookup_disabled_count",
        "identity_create_exact_skipped": "induction_growth_identity_create_exact_lookup_skipped_count",
        "grow_pruned": "induction_growth_pruned_low_energy_count",
        "stim_projection": "stimulus_object_projection_total",
        "stim_new_structure": "stimulus_new_structure_count",
        "unhandled_residual": "stimulus_unhandled_residual_total",
        "tail_absorbed": "stimulus_memory_tail_absorbed_total",
        "tail_projection": "residual_tail_memory_projection_applied",
        "legacy_residual_pkg": "runtime_residual_package_applied",
        "runtime_resolution_degraded": "pool_runtime_resolution_degraded_item_count",
        "weather_executed": "action_executed_weather_stub_source_visible",
        "teacher": "teacher_applied_count",
        "cfs_signal": "cfs_signal_count",
        "cfs_dissonance": "cfs_dissonance_max",
        "cfs_dissonance_live": "cfs_dissonance_live_total_energy",
        "cfs_expectation_live": "cfs_expectation_live_total_energy",
        "cfs_pressure_live": "cfs_pressure_live_total_energy",
        "cfs_repetition": "cfs_repetition_max",
        "cfs_complexity": "cfs_complexity_max",
        "nt_DA": "nt_DA",
        "nt_ADR": "nt_ADR",
        "nt_NOV": "nt_NOV",
        "nt_FOC": "nt_FOC",
        "attention_budget": "attention_energy_budget",
        "attention_net_delta": "attention_net_delta_energy",
        "action_threshold": "action_threshold_scale_mean",
        "action_threshold_nt": "action_threshold_nt_scale_mean",
        "action_threshold_rwd_pun": "action_threshold_rwd_pun_scale_mean",
        "timing_total": "timing_total_logic_ms",
        "timing_stimulus": "timing_stimulus_level_ms",
    }
    critical_stats = {
        alias: _compact_curriculum_stat(stats[key])
        for alias, key in critical_aliases.items()
        if isinstance(stats.get(key), dict)
    }
    manifest = data.get("manifest") if isinstance(data.get("manifest"), dict) else {}
    manifest_compact = {
        "status": manifest.get("status"),
        "dataset": manifest.get("dataset"),
        "options": manifest.get("options"),
        "expectation_contracts": manifest.get("expectation_contracts"),
        "completion_timing": manifest.get("completion_timing"),
        "dataset_runtime_override": manifest.get("dataset_runtime_override"),
    }
    expectation_events = data.get("expectation_events") if isinstance(data.get("expectation_events"), dict) else {}
    event_counts = expectation_events.get("event_counts") if isinstance(expectation_events.get("event_counts"), dict) else {}
    outcome_counts = (
        expectation_events.get("settled_outcome_counts")
        if isinstance(expectation_events.get("settled_outcome_counts"), dict)
        else {}
    )
    snapshot_schema = [
        "source_dataset_tick_index",
        "tick_index",
        "input_is_empty_0_1",
        "input_text_preview",
        "shape_by_er_ev_cp:[top_count,structure,atomic_sa,action_node,attribute]",
        "top5_quality_by_er_ev_cp:[structure_ratio,atomic_sa_ratio,action_node_ratio,attribute_ratio,long_structure_count,char_fragment_like_count,mean_signature_len,dominant_context_owner_structure_id,dominant_context_owner_share]",
        "top5_roots_by_er_ev_cp:[unique_root_count,duplicate_root_count,dominant_root_id,dominant_root_share]",
        "overlap_jaccard:[er,ev,cp]",
        "root_overlap_jaccard:[er,ev,cp]",
        "identity:[target,hit,created,shared_cache,local_cache,created_ratio,shared_ratio,hit_ratio]",
        "weather:[iesm_trigger,node_count,drive_max,threshold_mean,attempted,scheduled,executed]",
        "er_top1:[ref,type,context_owner,signature_len,alias_count,display,er,ev,cp]",
        "ev_top1:[ref,type,context_owner,signature_len,alias_count,display,er,ev,cp]",
        "cp_top1:[ref,type,context_owner,signature_len,alias_count,display,er,ev,cp]",
    ]
    aggregate_schema = [
        "action_drive_margin_weather_stub_max",
        "action_drive_weather_stub_max",
        "action_effective_threshold_weather_stub_mean",
        "action_attempted_weather_stub_source_visible",
        "action_executed_weather_stub_source_visible",
        "action_node_weather_stub_count",
        "action_scheduled_weather_stub_source_visible",
        "cfs_expectation_live_total_energy",
        "cfs_pressure_live_total_energy",
        "iesm_action_trigger_weather_stub_count",
        "iesm_action_trigger_weather_stub_count_source_visible",
        "punish_signal_live_total_energy",
        "reward_signal_live_total_energy",
        "teacher_applied_count",
        "teacher_pun",
        "teacher_rwd",
        "cfs_dissonance_live_total_energy",
        "cfs_correctness_live_total_energy",
        "cfs_correct_event_live_total_energy",
        "cfs_grasp_live_total_energy",
        "cfs_relief_live_total_energy",
        "nt_DA",
        "nt_ADR",
        "nt_OXY",
        "nt_SER",
        "nt_END",
        "nt_COR",
        "nt_NOV",
        "nt_FOC",
        "attention_energy_budget",
        "attention_net_delta_energy",
        "attention_mod_attention_energy_budget",
        "action_threshold_scale_mean",
        "action_threshold_nt_scale_mean",
        "action_threshold_rwd_pun_scale_mean",
        "action_threshold_fatigue_scale_mean",
        "action_learning_reward_drive_gain_total",
        "action_learning_punish_drive_penalty_total",
        "action_learning_threshold_delta_mean",
        "action_learning_threshold_delta_sum",
    ]
    window_row_schema = [
        "source_dataset_tick_index",
        "tick_index",
        "input_is_empty_0_1",
        "input_text_preview",
        "weather_sparse:[field_index,value]",
        "cfs_reward_punish_sparse:[field_index,value]",
        "nt_attention_action_sparse:[field_index,value]",
    ]
    return {
        "format": "curriculum_metrics_summary_compact_for_llm_review_v1",
        "schema_note": "Large repeated sections use fixed-order arrays to keep every snapshot/window inside the prompt budget.",
        "schemas": {
        "top5_snapshot_item": snapshot_schema,
        "segment_item": [
            "segment_index",
            "source_tick_start",
            "source_tick_end",
            "rows",
            "source_rows",
            "synthetic_rows",
            "identity_ratios:[created_to_target,shared_cache_hit_to_target,local_cache_hit_to_target,hit_to_target]",
            "identity_resolution:[create_exact_lookup_skipped_to_created,lookup_disabled_to_target,shared_cache_stale_to_target,created_not_explained_by_create_exact_skip]",
            "hdb:[structure_count_delta,delta_per_source_row,structure_count_latest]",
            "stat_triplets:[mean,p95,sum], fields=[grow_target,grow_created,grow_hit,grow_shared,identity_create_exact_skipped,pruned_low_energy,ev_er_ratio,stim_projection,tail_absorbed,runtime_resolution_degraded,attention_budget,action_threshold_nt,action_threshold_rwd_pun,action_learning_reward,cfs_dissonance_live,cfs_expectation_live,nt_DA,nt_ADR,timing_total_ms,timing_stimulus_ms]",
        ],
        "contract_window_item": [
                "contract_id",
                "spec_id",
                "outcome",
                "start_source_tick",
                "settled_source_tick",
                "deadline_source_tick",
                "matched:[kind,matched_0_1,metric,current,target]",
                "window_row_count",
        "causal_chain:[[trigger,ready,attempted,scheduled,executed,first_trigger,first_attempt,first_scheduled,first_executed,max_drive,max_threshold,max_margin],[teacher,teacher_rwd,teacher_pun,reward_live,punish_live,cfs_expectation,cfs_pressure,cfs_dissonance,cfs_correct_event],[attention_budget,threshold_scale,threshold_nt,threshold_rwd_pun,threshold_fatigue,learning_reward,learning_punish,learning_threshold_delta],[trigger_to_attempt,attempt_to_execute,trigger_to_no_execute,reward_or_expectation,punish_or_pressure,nt_present]]",
        f"aggregate_sum_sparse:[field_index,value], fields={aggregate_schema}",
        f"aggregate_max_sparse:[field_index,value], fields={aggregate_schema}",
        f"key_rows:{window_row_schema}",
            ],
        },
        "original_chars": int(original_chars),
        "target_budget": int(budget),
        "run_id": data.get("run_id"),
        "manifest": {key: value for key, value in manifest_compact.items() if value not in ({}, None, "")},
        "rows": data.get("rows") if isinstance(data.get("rows"), dict) else {},
        "by_experiment": data.get("by_experiment") if isinstance(data.get("by_experiment"), dict) else {},
        "identity_maturation": data.get("identity_maturation") if isinstance(data.get("identity_maturation"), dict) else {},
        "identity_resolution_summary": data.get("identity_resolution_summary")
        if isinstance(data.get("identity_resolution_summary"), dict)
        else {},
        "hdb_growth": data.get("hdb_growth") if isinstance(data.get("hdb_growth"), dict) else {},
        "performance_hdb_diagnostic_summary": _compact_curriculum_performance_diagnostic(
            data.get("performance_hdb_diagnostic_summary")
        ),
        "top5_quality_summary": data.get("top5_quality_summary")
        if isinstance(data.get("top5_quality_summary"), dict)
        else {},
        "top5_root_summary": data.get("top5_root_summary")
        if isinstance(data.get("top5_root_summary"), dict)
        else {},
        "target_apply_summary": _compact_curriculum_stats_map(data.get("target_apply_summary")),
        "runtime_resolution_summary": _compact_curriculum_stats_map(data.get("runtime_resolution_summary")),
        "critical_stats": critical_stats,
        "segments": {
            "source_tick_size": (data.get("segments") or {}).get("source_tick_size")
            if isinstance(data.get("segments"), dict)
            else None,
            "count": len(segment_items),
            "items": [_compact_curriculum_segment(item) for item in segment_items],
        },
        "expectation_events": {
            "event_counts": event_counts,
            "settled_outcome_counts": outcome_counts,
        },
        "expectation_contract_windows": {
            "count": len(window_items),
            "items": [_compact_curriculum_contract_window(item) for item in window_items],
        },
        "top5_snapshots": {
            "source_tick_interval": (data.get("top5_snapshots") or {}).get("source_tick_interval")
            if isinstance(data.get("top5_snapshots"), dict)
            else None,
            "count": len(top5_items),
            "items": [_compact_curriculum_snapshot(item) for item in top5_items],
        },
    }


def _sample_compact_items(items: Any, *, max_items: int) -> list[Any]:
    if not isinstance(items, list):
        return []
    if len(items) <= int(max_items):
        return list(items)
    return [items[idx] for idx in _sample_indices(len(items), max_samples=int(max_items))]


def _fit_curriculum_compact_to_budget(compact: dict[str, Any], *, budget: int) -> tuple[str, bool]:
    budget = int(max(1_000, budget))

    def _dump(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    text = _dump(compact)
    if len(text) <= budget:
        return text, False

    preserve_items_candidate = json.loads(json.dumps(compact, ensure_ascii=False))
    manifest = (
        preserve_items_candidate.get("manifest")
        if isinstance(preserve_items_candidate.get("manifest"), dict)
        else {}
    )
    preserve_items_candidate["manifest"] = {
        key: value
        for key, value in {
            "status": manifest.get("status"),
            "expectation_contracts": manifest.get("expectation_contracts"),
        }.items()
        if value not in (None, "", {})
    }
    preserve_items_candidate["by_experiment"] = {"trimmed_for_budget": True}
    quality = (
        preserve_items_candidate.get("top5_quality_summary")
        if isinstance(preserve_items_candidate.get("top5_quality_summary"), dict)
        else {}
    )
    preserve_items_candidate["top5_quality_summary"] = {
        axis: {
            key: value
            for key, value in (item if isinstance(item, dict) else {}).items()
            if key != "dominant_context_owner_top5"
        }
        for axis, item in quality.items()
    }
    roots = (
        preserve_items_candidate.get("top5_root_summary")
        if isinstance(preserve_items_candidate.get("top5_root_summary"), dict)
        else {}
    )
    preserve_items_candidate["top5_root_summary"] = {
        axis: {
            key: value
            for key, value in (item if isinstance(item, dict) else {}).items()
            if key != "dominant_root_top5"
        }
        for axis, item in roots.items()
    }
    preserve_items_candidate["schemas"] = {
        "note": "large repeated schemas mostly omitted for budget; named root summaries use explicit metric keys",
        "contract_window_item": [
            "contract_id",
            "spec_id",
            "outcome",
            "start_source_tick",
            "settled_source_tick",
            "deadline_source_tick",
            "matched",
            "window_row_count",
            "causal_chain:[[trigger,ready,attempted,scheduled,executed,first_trigger,first_attempt,first_scheduled,first_executed,max_drive,max_threshold,max_margin],[teacher,teacher_rwd,teacher_pun,reward_live,punish_live,cfs_expectation,cfs_pressure,cfs_dissonance,cfs_correct_event],[attention_budget,threshold_scale,threshold_nt,threshold_rwd_pun,threshold_fatigue,learning_reward,learning_punish,learning_threshold_delta],[trigger_to_attempt,attempt_to_execute,trigger_to_no_execute,reward_or_expectation,punish_or_pressure,nt_present]]",
        ],
    }
    critical = (
        preserve_items_candidate.get("critical_stats")
        if isinstance(preserve_items_candidate.get("critical_stats"), dict)
        else {}
    )
    keep_critical = {
        key: critical[key]
        for key in [
            "hdb_count",
            "grow_target",
            "grow_hit",
            "grow_created",
            "grow_shared",
            "identity_create_exact_skipped",
            "identity_lookup_disabled",
            "weather_executed",
            "teacher",
            "cfs_signal",
            "timing_total",
            "timing_stimulus",
        ]
        if key in critical
    }
    preserve_items_candidate["critical_stats"] = keep_critical
    preserve_items_candidate["budget_fit"] = {"sampled_for_budget": False, "trimmed": ["schema", "critical_stats"]}
    text = _dump(preserve_items_candidate)
    if len(text) <= budget:
        return text, True

    attempts = [
        (120, 80, 40),
        (80, 50, 24),
        (60, 36, 18),
        (40, 24, 12),
        (24, 16, 8),
        (16, 10, 6),
    ]
    for snapshot_limit, window_limit, segment_limit in attempts:
        candidate = json.loads(json.dumps(compact, ensure_ascii=False))
        top5 = candidate.get("top5_snapshots") if isinstance(candidate.get("top5_snapshots"), dict) else {}
        windows = (
            candidate.get("expectation_contract_windows")
            if isinstance(candidate.get("expectation_contract_windows"), dict)
            else {}
        )
        segments = candidate.get("segments") if isinstance(candidate.get("segments"), dict) else {}
        top5_items = top5.get("items") if isinstance(top5.get("items"), list) else []
        window_items = windows.get("items") if isinstance(windows.get("items"), list) else []
        segment_items = segments.get("items") if isinstance(segments.get("items"), list) else []
        top5["included_count"] = min(len(top5_items), snapshot_limit)
        top5["sampled"] = len(top5_items) > snapshot_limit
        top5["items"] = _sample_compact_items(top5_items, max_items=snapshot_limit)
        windows["included_count"] = min(len(window_items), window_limit)
        windows["sampled"] = len(window_items) > window_limit
        windows["items"] = _sample_compact_items(window_items, max_items=window_limit)
        segments["included_count"] = min(len(segment_items), segment_limit)
        segments["sampled"] = len(segment_items) > segment_limit
        segments["items"] = _sample_compact_items(segment_items, max_items=segment_limit)
        candidate["budget_fit"] = {
            "sampled_for_budget": True,
            "snapshot_limit": snapshot_limit,
            "window_limit": window_limit,
            "segment_limit": segment_limit,
        }
        text = _dump(candidate)
        if len(text) <= budget:
            return text, True

    essential = {
        "format": compact.get("format"),
        "schema_note": compact.get("schema_note"),
        "budget_fit": {"sampled_for_budget": True, "essential_only": True},
        "original_chars": compact.get("original_chars"),
        "target_budget": compact.get("target_budget"),
        "run_id": compact.get("run_id"),
        "rows": compact.get("rows"),
        "by_experiment": compact.get("by_experiment"),
        "identity_maturation": compact.get("identity_maturation"),
        "identity_resolution_summary": compact.get("identity_resolution_summary"),
        "hdb_growth": compact.get("hdb_growth"),
        "performance_hdb_diagnostic_summary": compact.get("performance_hdb_diagnostic_summary"),
        "top5_quality_summary": compact.get("top5_quality_summary"),
        "top5_root_summary": compact.get("top5_root_summary"),
        "target_apply_summary": compact.get("target_apply_summary"),
        "runtime_resolution_summary": compact.get("runtime_resolution_summary"),
        "critical_stats": compact.get("critical_stats"),
        "segments": {
            **(compact.get("segments") if isinstance(compact.get("segments"), dict) else {}),
            "items": _sample_compact_items(
                ((compact.get("segments") or {}).get("items") or [])
                if isinstance(compact.get("segments"), dict)
                else [],
                max_items=4,
            ),
        },
        "expectation_contract_windows": {
            **(
                compact.get("expectation_contract_windows")
                if isinstance(compact.get("expectation_contract_windows"), dict)
                else {}
            ),
            "items": _sample_compact_items(
                ((compact.get("expectation_contract_windows") or {}).get("items") or [])
                if isinstance(compact.get("expectation_contract_windows"), dict)
                else [],
                max_items=6,
            ),
        },
        "top5_snapshots": {
            **(compact.get("top5_snapshots") if isinstance(compact.get("top5_snapshots"), dict) else {}),
            "items": _sample_compact_items(
                ((compact.get("top5_snapshots") or {}).get("items") or [])
                if isinstance(compact.get("top5_snapshots"), dict)
                else [],
                max_items=8,
            ),
        },
    }
    text = _dump(essential)
    if len(text) <= budget:
        return text, True
    return _dump({"format": compact.get("format"), "error": "compact_summary_exceeds_budget", "run_id": compact.get("run_id")}), True


def _metric_prefix(key: str) -> str:
    k = str(key or "")
    if not k:
        return ""
    for prefix in (
        "expectation_contract",
        "internal_resolution",
        "internal_cam",
        "time_sensor",
        "action_local",
        "pool_er_top",
        "pool_ev_top",
    ):
        if k.startswith(prefix):
            return prefix
    return k.split("_", 1)[0]


def _compact_top_items(value: Any, *, limit: int = 3) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value[: max(0, int(limit))]:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "rank": item.get("rank"),
                "type": item.get("ref_object_type"),
                "ref": item.get("ref_object_id"),
                "display": _short_metric_text(item.get("display"), max_chars=64),
                "er": _round_metric_value(item.get("er")),
                "ev": _round_metric_value(item.get("ev")),
                "cp": _round_metric_value(item.get("cp")),
            }
        )
    return out


def _compact_cs_action_log(value: Any, *, limit: int = 6) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value[: max(0, int(limit))]:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "action": _short_metric_text(item.get("action"), max_chars=48),
                "family": _short_metric_text(item.get("action_family"), max_chars=36),
                "visible_text": _short_metric_text(item.get("visible_text"), max_chars=84),
                "context_text": _short_metric_text(item.get("context_text"), max_chars=64),
                "source_ref_id": _short_metric_text(item.get("source_ref_id"), max_chars=48),
                "target_ref_id": _short_metric_text(item.get("target_ref_id"), max_chars=48),
                "score": _round_metric_value(item.get("score")),
                "v2_score": _round_metric_value(item.get("v2_score")),
                "context_ratio": _round_metric_value(item.get("context_ratio")),
                "match_units": _round_metric_value(item.get("effective_match_units")),
            }
        )
    return out


_METRICS_COMPACT_ROW_KEYS = {
    "tick_index",
    "dataset_tick_index",
    "source_dataset_tick_index",
    "tick_source",
    "synthetic_tick",
    "expectation_contract_id",
    "expectation_contract_outcome",
    "input_is_empty",
    "input_len",
    "input_text_preview",
    "external_sa_count",
    "internal_sa_count",
    "internal_total_er",
    "internal_total_ev",
    "internal_to_external_sa_ratio",
    "internal_resolution_selected_sa_count",
    "internal_resolution_selected_unit_count",
    "internal_resolution_budget_sa_cap",
    "pool_active_item_count",
    "pool_total_er",
    "pool_total_ev",
    "pool_ev_to_er_ratio",
    "pool_high_cp_item_count",
    "pool_er_top1_display",
    "pool_er_top1_er",
    "pool_er_top1_ev",
    "pool_ev_top1_display",
    "pool_ev_top1_er",
    "pool_ev_top1_ev",
    "pool_er_atomic_feature_sa_top5_count",
    "pool_ev_atomic_feature_sa_top5_count",
    "pool_er_structure_top5_count",
    "pool_ev_structure_top5_count",
    "stimulus_round_count",
    "stimulus_match_v2_candidate_count",
    "stimulus_match_v2_score_mean",
    "stimulus_new_structure_count",
    "stimulus_transfer_matched_total",
    "stimulus_final_residual_total",
    "stimulus_transfer_to_residual_ratio",
    "stimulus_transfer_dominates_residual",
    "stimulus_effective_transfer_fraction_mean",
    "stimulus_object_projection_total",
    "stimulus_object_projection_seed_total",
    "stimulus_object_projection_matched_total",
    "stimulus_memory_tail_absorbed_total",
    "stimulus_unhandled_residual_total",
    "stimulus_object_projection_to_unhandled_residual_ratio",
    "stimulus_object_projection_dominates_unhandled_residual",
    "stimulus_early_stop_object_projection_dominance_triggered",
    "stimulus_early_stop_object_projection_dominance_ratio",
    "stimulus_early_stop_object_projection_transfer_guard_blocked_count",
    "stimulus_early_stop_object_projection_transfer_total_at_stop",
    "stimulus_early_stop_object_projection_transfer_ratio_at_stop",
    "stimulus_best_match_candidate_count",
    "stimulus_best_match_pruned_count",
    "stimulus_best_match_strict_overlap_fast_reject_count",
    "stimulus_cut_common_part_total_count",
    "stimulus_best_match_common_part_count",
    "stimulus_cut_exact_fast_path_hit_count",
    "stimulus_cut_full_inclusion_fast_path_hit_count",
    "stimulus_cut_single_group_fast_path_hit_count",
    "stimulus_cut_ordered_subsequence_fast_path_hit_count",
    "stimulus_cut_cache_hit_count",
    "stimulus_cut_cache_zero_copy_hit_count",
    "stimulus_cut_cache_store_count",
    "stimulus_cut_cache_deepcopy_count",
    "stimulus_cut_normalize_cache_hit_count",
    "stimulus_cut_full_group_fast_path_hit_count",
    "cache_priority_cut_exact_fast_path_hit_count",
    "cache_priority_cut_full_inclusion_fast_path_hit_count",
    "cache_priority_cut_single_group_fast_path_hit_count",
    "cache_priority_cut_ordered_subsequence_fast_path_hit_count",
    "cache_priority_cut_cache_hit_count",
    "cache_priority_cut_cache_zero_copy_hit_count",
    "cache_priority_cut_cache_store_count",
    "cache_priority_cut_cache_deepcopy_count",
    "cache_priority_cut_normalize_cache_hit_count",
    "cache_priority_cut_full_group_fast_path_hit_count",
    "induction_cut_exact_fast_path_hit_count",
    "induction_cut_full_inclusion_fast_path_hit_count",
    "induction_cut_cache_hit_count",
    "induction_cut_cache_zero_copy_hit_count",
    "induction_cut_cache_store_count",
    "induction_cut_cache_deepcopy_count",
    "induction_cut_single_group_fast_path_hit_count",
    "induction_cut_ordered_subsequence_fast_path_hit_count",
    "induction_cut_full_group_fast_path_hit_count",
    "induction_raw_residual_projection_profile_local_cache_hit_count",
    "induction_raw_residual_projection_profile_shared_cache_hit_count",
    "induction_raw_residual_projection_profile_cache_store_count",
    "induction_raw_residual_exact_candidates_local_cache_hit_count",
    "induction_raw_residual_exact_candidates_shared_cache_hit_count",
    "induction_raw_residual_exact_candidates_cache_store_count",
    "induction_raw_residual_component_candidates_local_cache_hit_count",
    "induction_raw_residual_component_candidates_shared_cache_hit_count",
    "induction_raw_residual_component_candidates_cache_store_count",
    "induction_full_inclusion_shared_cache_hit_count",
    "induction_full_inclusion_shared_cache_store_count",
    "stimulus_shadow_raw_residual_candidate_count",
    "stimulus_shadow_raw_residual_skipped_count",
    "stimulus_shadow_raw_residual_common_part_count",
    "induction_source_memory_terminal_prefilter_skipped_count",
    "residual_tail_memory_projection_applied",
    "residual_tail_memory_projection_handled",
    "residual_tail_memory_projection_er",
    "residual_tail_memory_projection_ev",
    "residual_tail_memory_projection_total_energy",
    "residual_tail_memory_projection_token_count",
    "residual_tail_memory_projection_full_memory_token_count",
    "residual_tail_memory_projection_tail_component_er_share",
    "residual_tail_memory_projection_tail_component_ev_share",
    "runtime_residual_package_applied",
    "runtime_residual_package_er",
    "runtime_residual_package_ev",
    "runtime_residual_package_total_energy",
    "runtime_residual_package_token_count",
    "runtime_residual_immediate_promotion_promoted_count",
    "runtime_residual_immediate_promotion_created_count",
    "runtime_residual_immediate_promotion_matched_count",
    "runtime_residual_immediate_promotion_hdb_fallback_count",
    "runtime_residual_promotion_attempted_count",
    "runtime_residual_promotion_promoted_count",
    "runtime_residual_promotion_exact_rebind_count",
    "runtime_residual_promotion_full_identity_count",
    "runtime_residual_promotion_hdb_fallback_count",
    "runtime_residual_promotion_created_count",
    "runtime_residual_promotion_matched_count",
    "induction_projection_mode_growth",
    "induction_projection_raw_target_count",
    "induction_projection_projected_target_count",
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
    "induction_growth_identity_lookup_disabled_count",
    "induction_growth_runtime_only_count",
    "induction_growth_memory_candidate_count",
    "induction_growth_memory_terminal_passthrough_count",
    "induction_growth_pruned_low_energy_count",
    "induction_growth_failed_count",
    "induction_growth_skipped_missing_source_count",
    "induction_growth_skipped_missing_residual_count",
    "induction_growth_deduped_count",
    "induction_growth_total_delta_er",
    "induction_growth_total_delta_ev",
    "induction_growth_source_component_er_total",
    "induction_growth_residual_component_ev_total",
    "pool_runtime_resolution_degraded_item_count",
    "pool_runtime_resolution_active_component_count",
    "pool_runtime_resolution_dropped_component_count",
    "maintenance_runtime_resolution_refreshed_item_count",
    "maintenance_runtime_resolution_degraded_item_count",
    "induction_total_delta_er",
    "induction_total_delta_ev",
    "cache_priority_consumed_er",
    "cache_priority_consumed_ev",
    "cs_enabled",
    "cs_stage_mode",
    "cs_selected_stage",
    "cs_active_item_count",
    "cs_active_structure_count",
    "cs_seed_scan_count",
    "cs_seed_structure_scan_count",
    "cs_seed_scan_capped",
    "cs_candidate_count",
    "cs_exact_context_index_owner_count",
    "cs_exact_context_index_target_total",
    "cs_exact_context_index_max_bucket_size",
    "cs_context_concat_source_scan_count",
    "cs_context_concat_exact_source_hit_count",
    "cs_context_concat_source_with_candidate_count",
    "cs_context_concat_exact_target_total",
    "cs_context_concat_soft_scan_attempt_count",
    "cs_context_concat_soft_scan_allowed_count",
    "cs_context_concat_soft_scan_blocked_count",
    "cs_context_concat_soft_target_total",
    "cs_context_concat_candidate_target_total",
    "cs_context_concat_candidate_pick_total",
    "cs_candidate_accepted_exact_context_identity_count",
    "cs_candidate_accepted_prefix_trim_count",
    "cs_action_count",
    "cs_concat_count",
    "cs_apply_candidate_input_count",
    "cs_apply_skip_count",
    "cs_apply_skip_exclusive_item_consumed_count",
    "cs_apply_skip_below_min_event_total_count",
    "cs_apply_skip_max_events_count",
    "cs_apply_concat_action_count",
    "cs_apply_exact_concat_action_count",
    "cs_apply_exact_new_concat_action_count",
    "cs_apply_partial_concat_action_count",
    "cs_apply_partial_new_concat_action_count",
    "cs_apply_reinforce_concat_action_count",
    "cs_apply_prefix_trimmed_action_count",
    "cs_apply_lower_energy_cap_audit_count",
    "cs_apply_lower_energy_cap_abs_diff_max",
    "cs_apply_absorb_ratio_mean",
    "cs_apply_absorbed_total_mean",
    "cs_apply_source_absorbed_total_mean",
    "cs_apply_target_absorbed_total_mean",
    "cs_action_log_count",
    "cs_action_log_concat_count",
    "cs_action_log_reinforce_concat_count",
    "cs_created_count",
    "cs_extended_count",
    "cs_merged_count",
    "cs_reinforced_count",
    "cs_event_count",
    "cs_narrative_top_total_energy",
    "cs_narrative_top_grasp",
    "memory_path_mode",
    "memory_runtime_projection_count",
    "action_attempted_count",
    "action_scheduled_count",
    "action_executed_count",
    "action_attempted_weather_stub",
    "action_scheduled_weather_stub",
    "action_executed_weather_stub",
    "action_node_count",
    "action_node_weather_stub_count",
    "action_local_map_count",
    "action_local_nonzero_count",
    "action_local_zero_signal_count",
    "action_local_reward_total",
    "action_local_punish_total",
    "cfs_signal_count",
    "cfs_dissonance_live_total_er",
    "cfs_dissonance_live_total_ev",
    "cfs_correctness_live_total_er",
    "cfs_correctness_live_total_ev",
    "cfs_pressure_live_total_er",
    "cfs_expectation_live_total_er",
    "nt_adrenaline",
    "nt_cortisol",
    "nt_dopamine",
    "nt_serotonin",
    "nt_DA",
    "nt_ADR",
    "nt_OXY",
    "nt_SER",
    "nt_END",
    "nt_COR",
    "nt_NOV",
    "nt_FOC",
    "nt_channel_count",
    "attention_cam_item_cap",
    "attention_mod_min_cam_items",
    "attention_mod_focus_boost_weight",
    "attention_mod_min_total_energy",
    "attention_mod_attention_energy_budget",
    "attention_energy_budget_base",
    "attention_energy_budget",
    "attention_energy_budget_min",
    "attention_energy_budget_max",
    "attention_energy_budget_enabled",
    "attention_energy_filter_applied",
    "attention_net_delta_energy",
    "attention_mod_priority_weight_total_energy",
    "attention_mod_priority_weight_cp_abs",
    "attention_mod_priority_weight_salience",
    "attention_mod_priority_weight_fatigue",
    "attention_mod_priority_weight_recency_gain",
    "action_threshold_scale_mean",
    "action_threshold_nt_scale_mean",
    "action_threshold_rwd_pun_scale_mean",
    "action_threshold_fatigue_scale_mean",
    "action_threshold_rwd_pun_enabled_node_count",
    "hdb_same_content_multi_context_count",
    "hdb_same_content_multi_context_ratio",
    "hdb_residual_diff_entry_count",
    "hdb_residual_diff_entry_ratio",
    "time_sensor_attribute_binding_count",
    "time_sensor_delayed_task_registered_count",
    "time_sensor_delayed_task_executed_count",
    "time_sensor_bucket_energy_sum",
    "cache_priority_cut_exact_fast_path_hit_count",
    "cache_priority_cut_full_inclusion_fast_path_hit_count",
    "cache_priority_cut_single_group_fast_path_hit_count",
    "cache_priority_cut_ordered_subsequence_fast_path_hit_count",
    "cache_priority_cut_cache_hit_count",
    "cache_priority_cut_cache_zero_copy_hit_count",
    "cache_priority_cut_cache_store_count",
    "cache_priority_cut_cache_deepcopy_count",
    "cache_priority_cut_normalize_cache_hit_count",
    "cache_priority_cut_normalize_cache_zero_copy_hit_count",
    "cache_priority_cut_normalize_reusable_hit_count",
    "cache_priority_cut_normalize_reusable_group_count",
    "cache_priority_cut_signature_fast_path_hit_count",
    "cache_priority_cut_empty_group_fast_path_hit_count",
    "cache_priority_cut_full_group_fast_path_hit_count",
    "cache_priority_cut_reindex_fast_path_hit_count",
    "cache_priority_theoretical_match_fast_reject_count",
    "stimulus_best_match_strict_overlap_fast_reject_count",
    "stimulus_cut_full_group_fast_path_hit_count",
    "induction_cut_full_group_fast_path_hit_count",
    "induction_raw_residual_projection_profile_local_cache_hit_count",
    "induction_raw_residual_projection_profile_shared_cache_hit_count",
    "induction_raw_residual_exact_candidates_shared_cache_hit_count",
    "induction_raw_residual_component_candidates_shared_cache_hit_count",
    "induction_full_inclusion_shared_cache_hit_count",
    "timing_total_logic_ms",
    "timing_stimulus_level_ms",
    "timing_cognitive_stitching_ms",
    "timing_cache_neutralization_ms",
    "hdb_structure_count",
    "hdb_group_count",
}


def _compact_metrics_row(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _METRICS_COMPACT_ROW_KEYS:
        if key not in row:
            continue
        value = row.get(key)
        if isinstance(value, str):
            out[key] = _short_metric_text(value, max_chars=120)
        elif isinstance(value, (int, float, bool)):
            out[key] = _round_metric_value(value)
        elif value is None:
            out[key] = None
    for key, value in row.items():
        if key in out:
            continue
        if key.startswith("action_") and any(token in key for token in ("weather_stub", "teacher", "reward", "punish", "local")):
            if isinstance(value, (int, float, bool)):
                out[key] = _round_metric_value(value)
            elif isinstance(value, str) and len(value) <= 120:
                out[key] = value
    er_top = _compact_top_items(row.get("pool_er_top5"), limit=3)
    ev_top = _compact_top_items(row.get("pool_ev_top5"), limit=3)
    if er_top:
        out["pool_er_top3"] = er_top
    if ev_top:
        out["pool_ev_top3"] = ev_top
    cs_action_log = _compact_cs_action_log(row.get("cs_action_log"), limit=4)
    if cs_action_log:
        out["cs_action_log_top"] = cs_action_log
    return dict(sorted(out.items()))


def _sample_indices(total: int, *, max_samples: int) -> list[int]:
    n = int(max(0, total))
    limit = int(max(1, max_samples))
    if n <= limit:
        return list(range(n))
    selected = set(range(min(6, n)))
    selected.update(range(max(0, n - 6), n))
    middle_slots = max(0, limit - len(selected))
    if middle_slots:
        step = max(1, n // (middle_slots + 1))
        for i in range(1, middle_slots + 1):
            selected.add(min(n - 1, i * step))
    return sorted(selected)[:limit]


def _top_counts(counts: dict[str, int], *, limit: int) -> list[dict[str, Any]]:
    items = sorted(counts.items(), key=lambda kv: (-int(kv[1]), str(kv[0])))[: max(0, int(limit))]
    return [{"value": key, "count": int(count)} for key, count in items]


def _build_segment_summary(rows: list[dict[str, Any]], *, segment_count: int = 8) -> list[dict[str, Any]]:
    if not rows:
        return []
    count = max(1, int(segment_count))
    size = max(1, (len(rows) + count - 1) // count)
    segments: list[dict[str, Any]] = []
    for start in range(0, len(rows), size):
        chunk = rows[start : start + size]
        if not chunk:
            continue
        numeric_keys = (
            "pool_total_er",
            "pool_total_ev",
            "internal_sa_count",
            "internal_total_ev",
    "cs_candidate_count",
    "cs_concat_count",
    "cs_action_log_count",
    "cs_action_log_concat_count",
    "cs_action_log_reinforce_concat_count",
    "cs_created_count",
            "action_executed_count",
            "action_executed_weather_stub",
            "cfs_signal_count",
            "time_sensor_delayed_task_executed_count",
            "timing_total_logic_ms",
        )
        summary: dict[str, Any] = {
            "tick_start": chunk[0].get("tick_index"),
            "tick_end": chunk[-1].get("tick_index"),
            "row_count": len(chunk),
            "source_rows": sum(1 for row in chunk if not bool(row.get("synthetic_tick", False))),
            "synthetic_rows": sum(1 for row in chunk if bool(row.get("synthetic_tick", False))),
        }
        for key in numeric_keys:
            values = [float(row.get(key, 0.0) or 0.0) for row in chunk if isinstance(row.get(key, 0.0), (int, float, bool))]
            if not values:
                continue
            summary[f"{key}_max"] = _round_metric_value(max(values))
            summary[f"{key}_mean"] = _round_metric_value(sum(values) / max(1, len(values)))
        er_labels = [str(row.get("pool_er_top1_display", "") or "") for row in chunk if row.get("pool_er_top1_display")]
        ev_labels = [str(row.get("pool_ev_top1_display", "") or "") for row in chunk if row.get("pool_ev_top1_display")]
        if er_labels:
            counts: dict[str, int] = {}
            for label in er_labels:
                counts[_short_metric_text(label, max_chars=72)] = counts.get(_short_metric_text(label, max_chars=72), 0) + 1
            summary["er_top1_modes"] = _top_counts(counts, limit=3)
        if ev_labels:
            counts = {}
            for label in ev_labels:
                counts[_short_metric_text(label, max_chars=72)] = counts.get(_short_metric_text(label, max_chars=72), 0) + 1
            summary["ev_top1_modes"] = _top_counts(counts, limit=3)
        segments.append(summary)
    return segments


def _make_numeric_record(key: str, stats: dict[str, Any]) -> dict[str, Any]:
    count = int(stats.get("count", 0) or 0)
    total = float(stats.get("sum", 0.0) or 0.0)
    return {
        "key": key,
        "count": count,
        "nonzero": int(stats.get("nonzero", 0) or 0),
        "min": _round_metric_value(stats.get("min")),
        "max": _round_metric_value(stats.get("max")),
        "mean": _round_metric_value(total / max(1, count)),
        "first": _round_metric_value(stats.get("first")),
        "latest": _round_metric_value(stats.get("latest")),
        "first_nonzero_tick": stats.get("first_nonzero_tick"),
        "last_nonzero_tick": stats.get("last_nonzero_tick"),
        "max_tick": stats.get("max_tick"),
    }


def _build_metrics_jsonl_digest(metrics_path: Path, *, char_budget: int) -> tuple[str, str]:
    budget = int(max(1_000, char_budget))
    numeric_stats: dict[str, dict[str, Any]] = {}
    categorical_counts: dict[str, dict[str, int]] = {}
    categorical_keys = {
        "tick_source",
        "memory_path_mode",
        "internal_stimulus_mode",
        "expectation_contract_outcome",
        "cs_event_grasp_reason",
        "action_last_executed_kind",
    }
    prefix_numeric_counts: dict[str, int] = {}
    compact_rows: list[dict[str, Any]] = []
    er_top1_counts: dict[str, int] = {}
    ev_top1_counts: dict[str, int] = {}
    row_count = 0
    parse_error_count = 0
    all_key_count: dict[str, int] = {}
    try:
        file_bytes = int(metrics_path.stat().st_size)
    except Exception:
        file_bytes = -1

    try:
        with metrics_path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    parse_error_count += 1
                    continue
                if not isinstance(row, dict):
                    parse_error_count += 1
                    continue
                row_count += 1
                tick = row.get("tick_index")
                compact_rows.append(_compact_metrics_row(row))
                for key in row.keys():
                    all_key_count[str(key)] = all_key_count.get(str(key), 0) + 1
                for key, value in row.items():
                    if isinstance(value, bool):
                        num = 1.0 if value else 0.0
                    elif isinstance(value, (int, float)):
                        num = float(value)
                    else:
                        num = None
                    if num is not None and num == num:
                        stats = numeric_stats.setdefault(
                            str(key),
                            {
                                "count": 0,
                                "nonzero": 0,
                                "sum": 0.0,
                                "min": num,
                                "max": num,
                                "first": num,
                                "latest": num,
                                "first_nonzero_tick": None,
                                "last_nonzero_tick": None,
                                "max_tick": tick,
                            },
                        )
                        stats["count"] += 1
                        stats["sum"] += num
                        stats["latest"] = num
                        if num < float(stats["min"]):
                            stats["min"] = num
                        if num > float(stats["max"]):
                            stats["max"] = num
                            stats["max_tick"] = tick
                        if abs(num) > 1e-12:
                            stats["nonzero"] += 1
                            if stats["first_nonzero_tick"] is None:
                                stats["first_nonzero_tick"] = tick
                            stats["last_nonzero_tick"] = tick
                        prefix = _metric_prefix(str(key))
                        prefix_numeric_counts[prefix] = prefix_numeric_counts.get(prefix, 0) + 1
                    elif isinstance(value, str) and str(key) in categorical_keys:
                        counts = categorical_counts.setdefault(str(key), {})
                        label = _short_metric_text(value, max_chars=96)
                        counts[label] = counts.get(label, 0) + 1
                er_label = row.get("pool_er_top1_display")
                ev_label = row.get("pool_ev_top1_display")
                if isinstance(er_label, str) and er_label.strip():
                    label = _short_metric_text(er_label, max_chars=96)
                    er_top1_counts[label] = er_top1_counts.get(label, 0) + 1
                if isinstance(ev_label, str) and ev_label.strip():
                    label = _short_metric_text(ev_label, max_chars=96)
                    ev_top1_counts[label] = ev_top1_counts.get(label, 0) + 1
    except Exception as exc:
        return json.dumps({"error": f"metrics_digest_failed: {exc}"}, ensure_ascii=False, indent=2), "(metrics digest 生成失败。)"

    always_keys = {
        "tick_index",
        "dataset_tick_index",
        "synthetic_tick",
        "pool_active_item_count",
        "pool_total_er",
        "pool_total_ev",
        "pool_ev_to_er_ratio",
        "pool_er_atomic_feature_sa_top5_count",
        "pool_ev_atomic_feature_sa_top5_count",
        "pool_er_structure_top5_count",
        "pool_ev_structure_top5_count",
        "internal_sa_count",
        "internal_total_er",
        "internal_total_ev",
        "internal_resolution_selected_sa_count",
        "stimulus_round_count",
        "stimulus_match_v2_candidate_count",
        "stimulus_match_v2_score_mean",
        "runtime_residual_package_applied",
        "runtime_residual_package_total_energy",
        "runtime_residual_package_token_count",
        "runtime_residual_immediate_promotion_promoted_count",
        "runtime_residual_immediate_promotion_hdb_fallback_count",
        "runtime_residual_promotion_attempted_count",
        "runtime_residual_promotion_promoted_count",
        "runtime_residual_promotion_exact_rebind_count",
        "runtime_residual_promotion_full_identity_count",
        "runtime_residual_promotion_hdb_fallback_count",
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
        "induction_growth_runtime_only_count",
        "induction_growth_pruned_low_energy_count",
        "induction_growth_failed_count",
        "induction_growth_total_delta_er",
        "induction_growth_total_delta_ev",
        "induction_growth_source_component_er_total",
        "induction_growth_residual_component_ev_total",
        "induction_total_delta_er",
        "induction_total_delta_ev",
        "cs_candidate_count",
        "cs_exact_context_index_target_total",
        "cs_context_concat_exact_source_hit_count",
        "cs_context_concat_source_with_candidate_count",
        "cs_context_concat_soft_scan_allowed_count",
        "cs_concat_count",
        "cs_apply_exact_concat_action_count",
        "cs_apply_exact_new_concat_action_count",
        "cs_apply_partial_concat_action_count",
        "cs_apply_partial_new_concat_action_count",
        "cs_apply_skip_exclusive_item_consumed_count",
        "cs_apply_prefix_trimmed_action_count",
        "cs_apply_lower_energy_cap_abs_diff_max",
        "cs_action_log_count",
        "cs_action_log_concat_count",
        "cs_action_log_reinforce_concat_count",
        "cs_created_count",
        "cs_extended_count",
        "cs_merged_count",
        "cs_reinforced_count",
        "cs_narrative_top_total_energy",
        "action_attempted_count",
        "action_scheduled_count",
        "action_executed_count",
        "action_attempted_weather_stub",
        "action_scheduled_weather_stub",
        "action_executed_weather_stub",
        "action_node_weather_stub_count",
        "action_local_zero_signal_count",
        "action_local_reward_total",
        "action_local_punish_total",
        "cfs_signal_count",
        "cfs_dissonance_live_total_er",
        "cfs_correctness_live_total_er",
        "time_sensor_delayed_task_registered_count",
        "time_sensor_delayed_task_executed_count",
        "timing_total_logic_ms",
        "timing_stimulus_level_ms",
        "timing_runtime_residual_promotion_ms",
        "timing_cache_neutralization_ms",
        "timing_cognitive_stitching_ms",
        "hdb_structure_count",
        "hdb_group_count",
    }
    important_prefixes = (
        "pool_",
        "internal_",
        "stimulus_",
        "runtime_residual_",
        "induction_",
        "cs_",
        "cfs_",
        "nt_",
        "attention_",
        "action_",
        "time_sensor_",
        "cache_",
        "timing_",
        "hdb_",
        "memory_",
        "expectation_contract",
    )

    def _numeric_score(item: tuple[str, dict[str, Any]]) -> tuple[int, int, float, str]:
        key, stats = item
        priority = 0
        if key in always_keys:
            priority += 10_000
        if key.startswith(("action_", "attention_", "cs_", "cfs_", "pool_", "internal_", "stimulus_", "induction_")):
            priority += 2_000
        if key.startswith(("timing_", "time_sensor_", "hdb_", "memory_", "expectation_contract")):
            priority += 1_000
        variable = 1 if stats.get("min") != stats.get("max") else 0
        nonzero = int(stats.get("nonzero", 0) or 0)
        magnitude = max(abs(float(stats.get("min", 0.0) or 0.0)), abs(float(stats.get("max", 0.0) or 0.0)))
        return (priority, variable + min(nonzero, 999), magnitude, key)

    numeric_items = [
        (key, stats)
        for key, stats in numeric_stats.items()
        if key in always_keys or key.startswith(important_prefixes)
    ]
    numeric_items.sort(key=_numeric_score, reverse=True)
    numeric_limit = 220 if budget >= 80_000 else 40
    numeric_summaries = [_make_numeric_record(key, stats) for key, stats in numeric_items[:numeric_limit]]
    zero_keys = [
        key
        for key, stats in numeric_items
        if int(stats.get("nonzero", 0) or 0) == 0 and key not in {"input_is_empty", "synthetic_tick"}
    ][:160]
    critical_field_groups = {
        "nt_channels": ["nt_DA", "nt_ADR", "nt_OXY", "nt_SER", "nt_END", "nt_COR", "nt_NOV", "nt_FOC"],
        "attention_energy_budget": [
            "attention_energy_budget_base",
            "attention_mod_attention_energy_budget",
            "attention_energy_budget",
            "attention_energy_budget_min",
            "attention_energy_budget_max",
            "attention_energy_filter_applied",
            "attention_net_delta_energy",
        ],
        "attention_selection_modulation": [
            "attention_cam_item_cap",
            "attention_mod_min_cam_items",
            "attention_mod_focus_boost_weight",
            "attention_mod_min_total_energy",
            "attention_mod_priority_weight_total_energy",
            "attention_mod_priority_weight_cp_abs",
            "attention_mod_priority_weight_salience",
            "attention_mod_priority_weight_fatigue",
            "attention_mod_priority_weight_recency_gain",
        ],
        "action_threshold_modulation": [
            "action_threshold_scale_mean",
            "action_threshold_nt_scale_mean",
            "action_threshold_rwd_pun_scale_mean",
            "action_threshold_fatigue_scale_mean",
            "action_threshold_rwd_pun_enabled_node_count",
        ],
        "hdb_context_residual": [
            "hdb_same_content_multi_context_count",
            "hdb_same_content_multi_context_ratio",
            "hdb_residual_diff_entry_count",
            "hdb_residual_diff_entry_ratio",
        ],
        "runtime_residual_package": [
            "residual_tail_memory_projection_applied",
            "residual_tail_memory_projection_handled",
            "residual_tail_memory_projection_er",
            "residual_tail_memory_projection_ev",
            "residual_tail_memory_projection_total_energy",
            "residual_tail_memory_projection_token_count",
            "residual_tail_memory_projection_full_memory_token_count",
            "residual_tail_memory_projection_tail_component_er_share",
            "residual_tail_memory_projection_tail_component_ev_share",
            "runtime_residual_package_applied",
            "runtime_residual_package_er",
            "runtime_residual_package_ev",
            "runtime_residual_package_total_energy",
            "runtime_residual_package_token_count",
            "runtime_residual_immediate_promotion_promoted_count",
            "runtime_residual_immediate_promotion_created_count",
            "runtime_residual_immediate_promotion_matched_count",
            "runtime_residual_immediate_promotion_hdb_fallback_count",
            "runtime_residual_promotion_attempted_count",
            "runtime_residual_promotion_promoted_count",
            "runtime_residual_promotion_exact_rebind_count",
            "runtime_residual_promotion_full_identity_count",
            "runtime_residual_promotion_hdb_fallback_count",
            "runtime_residual_promotion_created_count",
            "runtime_residual_promotion_matched_count",
            "timing_runtime_residual_promotion_ms",
        ],
        "stimulus_performance_cost": [
            "stimulus_best_match_candidate_count",
            "stimulus_best_match_pruned_count",
            "stimulus_best_match_strict_overlap_fast_reject_count",
            "stimulus_cut_common_part_total_count",
            "stimulus_best_match_common_part_count",
            "stimulus_cut_exact_fast_path_hit_count",
            "stimulus_cut_full_inclusion_fast_path_hit_count",
            "stimulus_cut_single_group_fast_path_hit_count",
            "stimulus_cut_ordered_subsequence_fast_path_hit_count",
            "stimulus_cut_cache_hit_count",
            "stimulus_cut_cache_zero_copy_hit_count",
            "stimulus_cut_cache_store_count",
            "stimulus_cut_cache_deepcopy_count",
            "stimulus_cut_normalize_cache_hit_count",
            "stimulus_cut_normalize_cache_zero_copy_hit_count",
            "stimulus_cut_normalize_reusable_hit_count",
            "stimulus_cut_normalize_reusable_group_count",
            "stimulus_cut_signature_fast_path_hit_count",
            "stimulus_cut_empty_group_fast_path_hit_count",
            "stimulus_cut_full_group_fast_path_hit_count",
            "stimulus_cut_reindex_fast_path_hit_count",
            "stimulus_early_stop_object_projection_transfer_guard_blocked_count",
            "stimulus_early_stop_object_projection_transfer_ratio_at_stop",
            "stimulus_shadow_raw_residual_candidate_count",
            "stimulus_shadow_raw_residual_skipped_count",
            "stimulus_shadow_raw_residual_common_part_count",
            "timing_stimulus_level_ms",
        ],
        "cache_neutralization_performance": [
            "cache_input_flat_token_count",
            "cache_residual_flat_token_count",
            "cache_priority_consumed_er",
            "cache_priority_consumed_ev",
            "cache_priority_cut_exact_fast_path_hit_count",
            "cache_priority_cut_full_inclusion_fast_path_hit_count",
            "cache_priority_cut_single_group_fast_path_hit_count",
            "cache_priority_cut_ordered_subsequence_fast_path_hit_count",
            "cache_priority_cut_cache_hit_count",
            "cache_priority_cut_cache_zero_copy_hit_count",
            "cache_priority_cut_cache_store_count",
            "cache_priority_cut_cache_deepcopy_count",
            "cache_priority_cut_normalize_cache_hit_count",
            "cache_priority_cut_normalize_cache_zero_copy_hit_count",
            "cache_priority_cut_normalize_reusable_hit_count",
            "cache_priority_cut_normalize_reusable_group_count",
            "cache_priority_cut_signature_fast_path_hit_count",
            "cache_priority_cut_empty_group_fast_path_hit_count",
            "cache_priority_cut_full_group_fast_path_hit_count",
            "cache_priority_cut_reindex_fast_path_hit_count",
            "cache_priority_theoretical_match_fast_reject_count",
            "timing_cache_neutralization_ms",
        ],
        "induction_growth_projection": [
            "induction_projection_mode_growth",
            "induction_projection_raw_target_count",
            "induction_projection_projected_target_count",
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
            "induction_growth_identity_lookup_disabled_count",
            "induction_growth_runtime_only_count",
            "induction_growth_memory_candidate_count",
            "induction_growth_memory_terminal_passthrough_count",
            "induction_growth_pruned_low_energy_count",
            "induction_growth_failed_count",
            "induction_growth_skipped_missing_source_count",
            "induction_growth_skipped_missing_residual_count",
            "induction_growth_deduped_count",
            "induction_growth_total_delta_er",
            "induction_growth_total_delta_ev",
            "induction_growth_source_component_er_total",
            "induction_growth_residual_component_ev_total",
            "pool_runtime_resolution_degraded_item_count",
            "pool_runtime_resolution_active_component_count",
            "pool_runtime_resolution_dropped_component_count",
            "maintenance_runtime_resolution_refreshed_item_count",
            "maintenance_runtime_resolution_degraded_item_count",
            "timing_induction_projection_prepare_ms",
        ],
        "induction_raw_residual_static_cache": [
            "induction_raw_residual_projection_profile_local_cache_hit_count",
            "induction_raw_residual_projection_profile_shared_cache_hit_count",
            "induction_raw_residual_projection_profile_cache_store_count",
            "induction_raw_residual_exact_candidates_local_cache_hit_count",
            "induction_raw_residual_exact_candidates_shared_cache_hit_count",
            "induction_raw_residual_exact_candidates_cache_store_count",
            "induction_raw_residual_component_candidates_local_cache_hit_count",
            "induction_raw_residual_component_candidates_shared_cache_hit_count",
            "induction_raw_residual_component_candidates_cache_store_count",
            "induction_full_inclusion_shared_cache_hit_count",
            "induction_full_inclusion_shared_cache_store_count",
        ],
        "cs_context_match_v2": [
            "cs_stage_mode",
            "cs_selected_stage",
            "cs_active_structure_count",
            "cs_seed_structure_scan_count",
            "cs_seed_scan_capped",
            "cs_concat_count",
            "cs_exact_context_index_owner_count",
            "cs_exact_context_index_target_total",
            "cs_context_concat_source_scan_count",
            "cs_context_concat_exact_source_hit_count",
            "cs_context_concat_source_with_candidate_count",
            "cs_context_concat_soft_scan_attempt_count",
            "cs_context_concat_soft_scan_allowed_count",
            "cs_context_concat_soft_scan_blocked_count",
            "cs_context_concat_candidate_pick_total",
            "cs_candidate_accepted_exact_context_identity_count",
            "cs_candidate_accepted_prefix_trim_count",
            "cs_apply_candidate_input_count",
            "cs_apply_skip_count",
            "cs_apply_skip_exclusive_item_consumed_count",
            "cs_apply_exact_concat_action_count",
            "cs_apply_exact_new_concat_action_count",
            "cs_apply_partial_concat_action_count",
            "cs_apply_partial_new_concat_action_count",
            "cs_apply_prefix_trimmed_action_count",
            "cs_apply_lower_energy_cap_abs_diff_max",
            "cs_apply_absorb_ratio_mean",
            "cs_apply_source_absorbed_total_mean",
            "cs_apply_target_absorbed_total_mean",
            "cs_concat_narrative_count",
            "cs_action_log_concat_count",
            "cs_created_count",
            "cs_extended_count",
            "cs_merged_count",
        ],
    }

    def _field_presence(keys: list[str]) -> dict[str, Any]:
        present = [
            {
                "key": key,
                "count": int(all_key_count.get(key, 0)),
                "numeric": key in numeric_stats,
                "nonzero": int(numeric_stats.get(key, {}).get("nonzero", 0) or 0) if key in numeric_stats else None,
            }
            for key in keys
            if key in all_key_count
        ]
        missing = [key for key in keys if key not in all_key_count]
        return {"present": present, "missing": missing}

    critical_key_order: list[str] = []
    for group_keys in critical_field_groups.values():
        for key in group_keys:
            if key not in critical_key_order:
                critical_key_order.append(key)
    critical_numeric_summaries = [
        _make_numeric_record(key, numeric_stats[key])
        for key in critical_key_order
        if key in numeric_stats
    ]

    sample_rows = []
    for index in _sample_indices(len(compact_rows), max_samples=36 if budget >= 80_000 else 16):
        sample_rows.append(compact_rows[index])

    digest = {
        "format": "metrics_digest_v2_compact_for_llm_review",
        "purpose": "用本地程序消除重复字段名和长标签文本；LLM 应优先引用本摘要，再用下方 compact JSONL 摘录复核。",
        "file": {
            "row_count": int(row_count),
            "parse_error_count": int(parse_error_count),
            "file_bytes": int(file_bytes),
            "observed_key_count": len(all_key_count),
            "numeric_key_count": len(numeric_stats),
        },
        "tick_range": {
            "first": compact_rows[0].get("tick_index") if compact_rows else None,
            "last": compact_rows[-1].get("tick_index") if compact_rows else None,
            "source_rows": sum(1 for row in compact_rows if not bool(row.get("synthetic_tick", False))),
            "synthetic_rows": sum(1 for row in compact_rows if bool(row.get("synthetic_tick", False))),
        },
        "categorical_counts": {
            key: _top_counts(counts, limit=10) for key, counts in sorted(categorical_counts.items())
        },
        "numeric_prefix_observation_counts": dict(sorted(prefix_numeric_counts.items())),
        "field_presence_audit": {
            name: _field_presence(keys) for name, keys in critical_field_groups.items()
        },
        "critical_numeric_summaries": critical_numeric_summaries,
        "important_numeric_summaries": numeric_summaries,
        "constant_zero_important_key_samples": zero_keys,
        "top1_frequency": {
            "er": _top_counts(er_top1_counts, limit=20),
            "ev": _top_counts(ev_top1_counts, limit=20),
        },
        "segment_summaries": _build_segment_summary(compact_rows, segment_count=8),
        "compact_tick_samples": sample_rows,
        "omitted": {
            "numeric_summary_keys_omitted": max(0, len(numeric_items) - len(numeric_summaries)),
            "compact_rows_not_sampled": max(0, len(compact_rows) - len(sample_rows)),
        },
    }
    text = json.dumps(digest, ensure_ascii=False, indent=2)
    if len(text) > budget:
        digest["important_numeric_summaries"] = numeric_summaries[:40]
        digest["constant_zero_important_key_samples"] = zero_keys[:40]
        digest["compact_tick_samples"] = sample_rows[:8]
        digest["segment_summaries"] = digest["segment_summaries"][:4]
        digest["top1_frequency"]["er"] = digest["top1_frequency"]["er"][:10]
        digest["top1_frequency"]["ev"] = digest["top1_frequency"]["ev"][:10]
        digest["omitted"]["digest_truncated_for_budget"] = True
        text = json.dumps(digest, ensure_ascii=False, indent=2)
    if len(text) > budget:
        digest["important_numeric_summaries"] = []
        digest["constant_zero_important_key_samples"] = []
        digest["compact_tick_samples"] = []
        digest["segment_summaries"] = []
        digest["top1_frequency"]["er"] = digest["top1_frequency"]["er"][:5]
        digest["top1_frequency"]["ev"] = digest["top1_frequency"]["ev"][:5]
        digest["omitted"]["digest_minimized_for_budget"] = True
        text = json.dumps(digest, ensure_ascii=False, indent=2)
    if len(text) > budget:
        minimal_digest = {
            "format": digest["format"],
            "purpose": digest["purpose"],
            "file": digest["file"],
            "tick_range": digest["tick_range"],
            "field_presence_audit": digest["field_presence_audit"],
            "critical_numeric_summaries": digest["critical_numeric_summaries"],
            "top1_frequency": {
                "er": digest["top1_frequency"]["er"][:3],
                "ev": digest["top1_frequency"]["ev"][:3],
            },
            "omitted": {
                **digest["omitted"],
                "digest_minimal_for_budget": True,
                "full_digest_chars_before_minimal": len(text),
            },
        }
        text = json.dumps(minimal_digest, ensure_ascii=False, indent=2)
    note = (
        f"(已生成 metrics_digest_v2：rows={row_count}, numeric_keys={len(numeric_stats)}, "
        f"observed_keys={len(all_key_count)}, digest_chars={len(text)}。)"
    )
    return text, note


def _read_metrics_jsonl_compact_excerpt(metrics_path: Path, *, char_budget: int) -> tuple[str, str]:
    budget = int(max(1_000, char_budget))
    if not metrics_path.exists():
        return "", ""
    try:
        size = int(metrics_path.stat().st_size)
    except Exception:
        size = -1

    head_keep = 80
    tail_keep = 40
    head_budget = max(1, int(budget * 0.58))
    tail_budget = max(1, budget - head_budget)

    head: list[str] = []
    head_chars = 0
    tail_candidates: list[str] = []
    total_lines = 0
    parse_error_count = 0
    try:
        with metrics_path.open("r", encoding="utf-8", errors="replace") as fh:
            for total_lines, raw_line in enumerate(fh, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        item = json.dumps(_compact_metrics_row(row), ensure_ascii=False, separators=(",", ":"))
                    else:
                        item = _clip_long_metrics_line(line, 1200)
                except Exception:
                    parse_error_count += 1
                    item = _clip_long_metrics_line(line, 1200)
                if len(head) < head_keep and head_chars < head_budget:
                    remaining = head_budget - head_chars
                    if remaining > 80:
                        clipped = _clip_long_metrics_line(item, remaining)
                        head.append(clipped)
                        head_chars += len(clipped) + 1
                tail_candidates.append(item)
                if len(tail_candidates) > tail_keep:
                    tail_candidates = tail_candidates[-tail_keep:]
    except Exception:
        return "", "(compact metrics excerpt 读取失败或不可用。)"

    tail_reversed: list[str] = []
    tail_chars = 0
    for item in reversed(tail_candidates):
        remaining = tail_budget - tail_chars
        if remaining <= 80:
            break
        clipped = _clip_long_metrics_line(item, remaining)
        tail_reversed.append(clipped)
        tail_chars += len(clipped) + 1
    tail = list(reversed(tail_reversed))

    middle = [
        "",
        f"# ...(middle compact rows omitted; total_lines={total_lines}, file_bytes={size})...",
        "",
    ]
    text = "\n".join(head + middle + tail).strip()
    note = (
        f"(compact metrics JSONL 摘录：字符预算约 {budget}，头部最多 {head_keep} 行、尾部最多 {tail_keep} 行；"
        f"已去除大多数字段重复和长文本，parse_errors={parse_error_count}。)"
    )
    return text, note


def _read_metrics_jsonl_excerpt(metrics_path: Path, *, char_budget: int) -> tuple[str, str]:
    budget = int(max(1_000, char_budget))
    if not metrics_path.exists():
        return "", ""
    try:
        size = int(metrics_path.stat().st_size)
    except Exception:
        size = -1

    if size >= 0 and size <= budget:
        return _safe_read_text(metrics_path, max_chars=None), "(metrics.jsonl 已全量包含。)"

    head_keep = 240
    tail_keep = 120
    head_budget = max(1, int(budget * 0.62))
    tail_budget = max(1, budget - head_budget)
    line_budget = max(260, min(8_000, int(budget / max(12, min(head_keep + tail_keep, 360)))))

    head: list[str] = []
    head_chars = 0
    tail_candidates: list[str] = []
    total_lines = 0
    clipped_line_count = 0
    try:
        with metrics_path.open("r", encoding="utf-8", errors="replace") as fh:
            for total_lines, raw_line in enumerate(fh, start=1):
                line = raw_line.rstrip("\n")
                clipped = _clip_long_metrics_line(line, line_budget)
                if clipped != line:
                    clipped_line_count += 1

                if len(head) < head_keep and head_chars < head_budget:
                    remaining = head_budget - head_chars
                    if remaining > 80:
                        item = _clip_long_metrics_line(clipped, min(line_budget, remaining))
                        head.append(item)
                        head_chars += len(item) + 1

                if line.strip():
                    tail_candidates.append(clipped)
                    if len(tail_candidates) > tail_keep:
                        tail_candidates = tail_candidates[-tail_keep:]
    except Exception:
        return "", "(metrics.jsonl 读取失败或不可用。)"

    tail_reversed: list[str] = []
    tail_chars = 0
    for item in reversed(tail_candidates):
        remaining = tail_budget - tail_chars
        if remaining <= 80:
            break
        clipped = _clip_long_metrics_line(item, min(line_budget, remaining))
        tail_reversed.append(clipped)
        tail_chars += len(clipped) + 1
    tail = list(reversed(tail_reversed))

    middle = [
        "",
        f"# ...(middle omitted for context budget; total_lines={total_lines}, file_bytes={size})...",
        "",
    ]
    text = "\n".join(head + middle + tail).strip()
    note = (
        f"(metrics.jsonl 体量较大，已按字符预算约 {budget} 提供头尾摘录："
        f"头部最多 {head_keep} 行、尾部最多 {tail_keep} 行；"
        f"超长单行会被截断，本次截断行数约 {clipped_line_count}。"
        "如需更长上下文，可在前端提高 max_prompt_chars 或分段分析。)"
    )
    return text, note


def _read_metrics_jsonl_for_review(metrics_path: Path, *, char_budget: int) -> tuple[str, str]:
    budget = int(max(1_500, char_budget))
    digest_budget = max(900, int(budget * 0.68))
    excerpt_budget = max(400, budget - digest_budget)
    digest_text, digest_note = _build_metrics_jsonl_digest(metrics_path, char_budget=digest_budget)
    excerpt_text, excerpt_note = _read_metrics_jsonl_compact_excerpt(metrics_path, char_budget=excerpt_budget)
    text = (
        "METRICS_DIGEST_V2_COMPACT\n"
        "```json\n"
        f"{digest_text.strip()}\n"
        "```\n\n"
        "COMPACT_METRICS_JSONL_EXCERPT\n"
        "```jsonl\n"
        f"{excerpt_text.strip()}\n"
        "```"
    )
    note = (
        f"{digest_note}\n"
        f"{excerpt_note}\n"
        "说明：原始 metrics.jsonl 中有大量重复字段名、长 display 标签和列表对象；本提示词使用 deterministic digest + compact excerpt，"
        "比直接塞原始 JSONL 更适合审阅。若需要逐段 LLM 总结，可在此摘要之上再做分段二次审阅。"
    )
    if len(text) > budget:
        text = _clip_long_metrics_line(text, budget)
    return text.strip(), note.strip()


def _read_curriculum_metrics_summary_for_review(run_dir: Path, *, char_budget: int) -> tuple[str, str]:
    path = run_dir / "curriculum_metrics_summary.json"
    budget = int(max(1_000, char_budget))
    if not path.exists():
        return "", ""
    text = _safe_read_text(path, max_chars=None)
    if not text.strip():
        return "", ""
    note = (
        f"(curriculum_metrics_summary.json 已提供，字符预算约 {budget}。"
        "这是行为课程 run 的优先审阅摘要，包含 Top5 快照、identity 成熟分段、合约窗口行动切片和 HDB 增长。)"
    )
    if len(text) > budget:
        raw = _safe_read_json(path)
        compact = _compact_curriculum_metrics_summary(raw, original_chars=len(text), budget=budget)
        compact_text, sampled_for_budget = _fit_curriculum_compact_to_budget(compact, budget=budget)
        if len(compact_text) <= budget:
            text = compact_text
            note += (
                " 原始摘要较大，已转换为 deterministic compact view；"
                "此 compact view 保留全部 Top5 快照、全部合约窗口、全部分段 identity/HDB 趋势和关键 stats，"
                "但压缩了长 display、窗口逐行明细和巨型 stats。"
            )
            if sampled_for_budget:
                note += " compact view 仍超过预算时已按固定采样策略降级，但保持合法 JSON。"
        else:
            text = compact_text
            note += " compact view 超过预算且无法进一步压缩，仅保留错误占位 JSON。"
    return text.strip(), note


def _read_accumulated_curriculum_summary_for_review(run_dir: Path, *, char_budget: int) -> tuple[str, str]:
    name = str(run_dir.name or "")
    if len(name) < 4 or not name[-2:].isdigit() or name[-4:-2] != "_r":
        return "", ""
    batch_run_id = name[:-4]
    path = run_dir.parent / f"{batch_run_id}_batch" / "accumulated_curriculum_summary.json"
    budget = int(max(1_000, char_budget))
    if not path.exists():
        return "", ""
    text = _safe_read_text(path, max_chars=None)
    if not text.strip():
        return "", ""
    note = (
        f"(accumulated_curriculum_summary.json 已提供，字符预算约 {budget}。"
        "这是同一数据集多轮保留 HDB 累计运行的批次摘要，优先用于评价跨轮 identity/cache 成熟、HDB 增长和合约稳定性。)"
    )
    if len(text) > budget:
        text = _clip_long_metrics_line(text, budget)
        note += " 摘要文件较大，已按预算截断；如需完整跨轮明细，请提高 max_prompt_chars。"
    return text.strip(), note


def _read_expectation_contract_events_summary(run_dir: Path, *, max_chars: int) -> str:
    path = run_dir / "expectation_contract_events.jsonl"
    if not path.exists():
        return ""
    events: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if isinstance(row, dict):
                    events.append(row)
    except Exception:
        return ""
    if not events:
        return ""
    compact: list[dict[str, Any]] = []
    for row in events[:24]:
        compact.append(
            {
                "event": _short_metric_text(row.get("event"), max_chars=24),
                "contract_id": _short_metric_text(row.get("contract_id"), max_chars=56),
                "spec_id": _short_metric_text(row.get("spec_id"), max_chars=40),
                "outcome": _short_metric_text(row.get("outcome"), max_chars=24),
                "source_tick_cursor": _round_metric_value(row.get("source_tick_cursor")),
                "source_dataset_tick_index": _round_metric_value(row.get("source_dataset_tick_index")),
                "settled_source_tick_cursor": _round_metric_value(row.get("settled_source_tick_cursor")),
                "deadline_source_tick_cursor": _round_metric_value(row.get("deadline_source_tick_cursor")),
                "matched_detail": row.get("matched_detail") if isinstance(row.get("matched_detail"), list) else [],
                "frozen_anchor": row.get("frozen_anchor") if isinstance(row.get("frozen_anchor"), dict) else {},
            }
        )
    text = json.dumps(
        {
            "format": "expectation_contract_event_summary_v1",
            "event_count": len(events),
            "sample_events": compact,
        },
        ensure_ascii=False,
        indent=2,
    )
    if len(text) > max_chars:
        text = _clip_long_metrics_line(text, max_chars)
    return text


def _build_system_prompt() -> str:
    return (
        "你是一名 AP 原型实验审阅员，兼具方法学审稿人与系统诊断工程师的视角。\n"
        "你的任务是评估一个本地运行的 Artificial PsyArch (AP) 原型在指定数据集上的运行结果，"
        "帮助研究者理解：哪些现象已经被数据支持，哪些只是合理推断，哪些仍缺少观测证据。\n"
        "\n"
        "总体目标：在尊重当前 AP 理论口径与工程开关的前提下，给出整体、严谨、客观、可复验的评价。"
        "建议应优先落在参数、规则配置、观测字段、对照实验与低风险工程改进上；涉及主逻辑的判断需要给出证据和风险边界。\n"
        "\n"
        "证据与表述原则：\n"
        "1) 每个关键结论都要标注证据来源：metric key、tick 区间、manifest/config 字段、数据集片段、报告中的具体数值或缺失字段。\n"
        "2) 将结论分成 Observed（直接观测）、Inferred（由多项证据推断）、Unknown（材料不足）、Recommendation（建议）四类，避免把推断写成事实。\n"
        "3) 如果某项理论机制无法判断，请说明缺少哪些字段或对照实验，而不是直接判定实现失败。\n"
        "4) 当指标为 0 或长期不变时，先结合配置路径解释其是否为预期口径，再判断是否可能是采集缺口、显示折叠、统计复用或真实逻辑缺失。\n"
        "5) 对 bug/缺口的判断需要给出可证伪路径，例如应查看哪些 tick、哪些 action state、哪些 CFS live_total、哪些 HDB/CS/StatePool 字段。\n"
        "5.1) Target apply performance fields: `timing_induction_target_apply_ms`, `induction_growth_target_apply_ref_fast_merge_enabled`, `induction_growth_target_apply_fast_ref_hit_merge_count`, `induction_growth_target_apply_insert_log_enabled`, and `induction_growth_target_apply_insert_log_suppressed_count`. Exact-ref fast merge is a StatePool performance path after complete A+B identity resolution; insert-log suppression means brief/detail file logs were skipped, not that targets were skipped.\n"
        "6) 调参建议要写明参数名或配置位置、建议方向/范围、预期改善、可能副作用和验证指标；优先避免新增硬编码。\n"
        "7) 不假设你能访问本地文件系统或额外日志；只能使用提示词中提供的理论文本、manifest、dataset、extra context 和 metrics。\n"
        "8) 你的报告不应只做问题清单，还应给出总评：当前架构在这次运行里到底体现出了哪些能力、哪些能力尚弱、哪些现象说明它和常见纯统计检索/纯规则流/普通 agent loop 架构相比有明显差异。\n"
        "9) 对“架构优势、区别、拟人度”的评价必须客观、证据绑定；不要强行吹优点，也不要为了严苛而否认已经有数据支撑的长处。\n"
        "10) 报告必须在开头保留“总评与架构定位、架构对比、创新点、应用场景、拟人度评估”这些一级章节；即使证据不足，也要写明证据不足，不能省略或只放到尾部一句话。\n"
        "11) 架构对比至少覆盖：纯规则系统、纯向量/RAG 检索记忆、普通工具调用 agent loop、传统强化学习/行为策略、预测加工/主动推断类架构。每项都要写 AP 当前实现的相似点、差异、优势、代价或证据不足。\n"
        "12) 评价优势和创新点时，必须区分“理论设计潜力”和“本次 run 已观察到的实现效果”；不要把理论预期直接当成已经实现，也不要把观测字段缺失误写成机制不存在。\n"
        "13) 图表和 AutoTuner 的新版主显示已经以 `induction_growth_*`、运行态分辨率、组件 ER/EV、注意力/内源重采样和性能热点为主；旧 context/provenance、legacy context/provenance、`cs_*`、`map_*` 与旧式能量平衡图默认折叠为诊断/回滚视图。除非 manifest/config 明确开启 residual/CS/MAP 旧路径，否则不要把这些旧口径的 0 值、低值或折叠状态写成主故障。\n"
        "14) 如果提示词中提供了 `curriculum_metrics_summary.json`，它是行为课程 run 的优先审阅材料。审阅 Top5、identity 成熟、合约窗口行动链、HDB 增长和性能慢尾时必须先读其中的 `top5_snapshots`、`top5_quality_summary`、`top5_root_summary`、`identity_maturation`、`identity_resolution_summary`、`segments`、`expectation_contract_windows`、`hdb_growth`、`performance_hdb_diagnostic_summary`。这些字段存在时，不要再笼统说“没有 Top5 信息/没有合约窗口信息/没有性能明细”；若仍不足，应具体写“已有字段但叙事解释、严格因果链或逐函数 profile 仍不足”。identity exact hit 低时，必须同时查看 `identity_resolution_summary` 中的 create_exact_lookup_skipped、shared/local cache、lookup_disabled/stale 与 deduped，不要只用 exact_hit 单项定性。Top 重复/字符片段化时，必须同时查看 `top5_root_summary` 的 unique_root、duplicate_root、dominant_root 与 root_overlap，区分展示重复、运行态分辨率变体和可能的语义自循环。性能慢尾时，必须结合 `performance_hdb_diagnostic_summary` 的 segment_timing_trend、slowest_ticks_by_total_logic_ms 和相关字段；相关性只能作为定位线索，不要写成严格因果证明。\n"
        "15) 短程 300/1000/3000 tick 行为课程不能证明百万语料级逻辑能力。此类 run 的合理优秀标准是：记忆召回或关键特征重采样有迹象、Top5 从纯原子噪声转向结构对象、identity/cache 有成熟趋势、奖惩/行动合约链路正确、CFS/NT 与状态变化有可审阅对应。不要要求短程 run 展示完整自然语言推理；也不要因为未达到百万规模效果而压低对局部机制证据的评价。\n"
        "\n"
        "当前实验流程的审阅口径：\n"
        "1) 当前主流程优先按新版“感应生长方案”理解：刺激级查存一体先命中/创建作为种子的 HDB/状态池对象 A；HDB induction 仍从 A 的局部数据库发现残差结构/残差记忆目标 B；"
        "Observatory 默认把 per-source residual candidate 投影为完整结构 A+B，而不是把 B(context=A) 半成品投进状态池再等待 CS。"
        "默认配置应接近 `induction_projection_mode=growth`、`cognitive_stitching_stage=disabled`、`enable_cognitive_stitching=false`。旧 residual + CS 路径只作为回滚、审计和 A/B 对照。\n"
        "2) 审阅感应链路时优先看 `induction_projection_mode_growth`、`induction_growth_target_count`、`induction_growth_identity_hit_count`、"
        "`induction_growth_identity_created_count`、`induction_growth_identity_local_cache_hit_count`、`induction_growth_identity_shared_cache_hit_count/stale_count`、`induction_growth_persistence_batch_enabled`、`induction_growth_runtime_only_count`、`induction_growth_pruned_low_energy_count`、"
        "`induction_growth_total_delta_er/ev`、`induction_growth_source_component_er_total`、`induction_growth_residual_component_ev_total`、`induction_source_memory_terminal_prefilter_skipped_count` 与 `timing_induction_projection_prepare_ms`。这些字段用于判断 A+B 生长是否真的发生、是否命中同一完整身份、source-side ER 与 residual-side EV 是否分清、记忆终端是否被跳过，以及是否因为低能/缺源/缺残差而被剪枝或暂存。\n"
        "2.1) 感应 raw residual 静态解析缓存是性能护栏，不是语义捷径。默认主路径只开启 `induction_raw_residual_projection_profile_*cache*` 来复用 owner-subtract 后的投影 profile；"
        "`induction_raw_residual_exact_candidates_*cache*` / `induction_raw_residual_component_candidates_*cache*` 候选列表缓存因活跃学习期 HDB lookup revision 常变化而默认关闭，仅作为稳定 HDB 或 profiling 开关；`induction_full_inclusion_shared_cache_*` 用于复用 profile 包含判定。它们不缓存 entry runtime_weight、疲劳、近因或本轮 EV/ER 分配。"
        "若这些命中升高且 `timing_induction_hdb_propagation_ms` / `timing_induction_projection_prepare_ms` 下降，说明重复结构解析被吸收；若命中低而耗时高，应继续看 source/target fanout 和共同切割。\n"
        "3) 生长投影中的 owner DB 只是激活来源，不是新对象身份。完整 A+B 身份应按完整特征内容解析：同一完整结构即使来自不同路径，也应汇聚为同一 HDB-backed ST；"
        "纯 EV 支持的新建结构基础权重应为 0，ER 支持时可按 ER 强度、近因和疲劳给小幅加法增益。结构整体 ER/EV 只是统计，残差 B 的预测能量不应被误写成真实 ER。\n"
        "3.1) 运行态退化现在按“分辨率下降”理解：StatePool 中某个结构的部分组件能量低于阈值时，不应重新查存一体、也不应创建新的退化 HDB id；"
        "它仍保留对象自己的完整 ST/root_structure_id，只刷新 `runtime_resolution_*` 和 `component_energy` 解释字段。"
        "同一完整结构的不同分辨率视图可以按 root identity 合并；但 growth source/root_source 只是生长来源审计，不能拿来合并 A+B1/A+B2 这种同源分支。"
        "审阅时可看 `pool_runtime_resolution_degraded_item_count`、`pool_runtime_resolution_active_component_count`、`pool_runtime_resolution_dropped_component_count`、"
        "`maintenance_runtime_resolution_refreshed_item_count` 和 `maintenance_runtime_resolution_degraded_item_count`。\n"
        "3.2) 默认不启用感应过度预测门控。若 `growth_projection_overprediction_gate_enabled=false`，连续想象/发散应先视为当前拟人化口径的一部分；"
        "只有在能量失控、状态池无界膨胀、Top 长期重复自指或性能证据明显异常时，才建议打开门控做对照。\n"
        "4) `cs_*` 现在不是默认主判断线。若本次 run 中 CS 关闭，请只简要说明这是新版默认口径，不要反复把“没有走 CS/关闭结构级查存一体”当作主要结论。"
        "只有当 manifest/config 显示用户启用了 residual 或 CS 对照时，才深入审阅 `cs_stage_mode/cs_selected_stage`、`cs_concat_count`、精确上下文索引、软扫描、低能侧吸收、前缀裁剪等 CS 细节。\n"
        "5) 如果 CS 被显式启用，精确上下文拼接的能量吸收应遵守低能侧上限：即使匹配 100%，也最多吸收 source/target 二者中较低总能量乘以比例，而不是抽干高能对象。"
        "可用 `cs_apply_source_absorbed_total_mean`、`cs_apply_target_absorbed_total_mean`、`cs_apply_lower_energy_cap_abs_diff_max` 和 action_log 中的吸收字段复核。\n"
        "6) CAM-only 内源刺激通常来自注意力模块输出的 CAM snapshot，并受 DARL+PARS 内源分辨率预算约束。"
        "`internal_sa_count` 或 `internal_resolution_selected_unit_count` 接近预算上限的平顶不必然是 bug，但长期完全同值需要排查统计口径复用或显示重影。\n"
        "7) 跑批可能插入 synthetic ticks。`tick_index` 是执行序号，`dataset_tick_index` 是数据集原序号；期望契约的注册/窗口/满足判定通常只以 source tick 为准，"
        "synthetic feedback ticks 不消耗窗口，也可能导致“行动已发生但合约不可见”的表象。\n"
        "8) 行动闭环至少区分 attempted、scheduled、executed、action node 是否进入状态池、局部 reward/punish map 是否命中，以及目标 action_kind 是否被 source/synthetic 口径看见。\n"
        "9) CFS 需要区分事件峰值口径 `cfs_*_max/count` 与持续态 `cfs_*_live_total_*`；评估维持、回落、疲劳和情绪递质影响时优先看 live_total 与趋势。\n"
        "10) 性能审阅优先区分主链代价与诊断代价。刺激级主链先看对象侧投影与净残余：`stimulus_object_projection_total`、`stimulus_object_projection_seed_total`、`stimulus_object_projection_matched_total`、`stimulus_memory_tail_absorbed_total`、`stimulus_unhandled_residual_total`、`stimulus_object_projection_to_unhandled_residual_ratio`、`stimulus_object_projection_dominates_unhandled_residual`。新版默认期望多数有命中的 source tick 中对象投影总量高于未处理净残余。`stimulus_transfer_matched_total`、`stimulus_final_residual_total`、`stimulus_transfer_to_residual_ratio`、`stimulus_transfer_dominates_residual` 和 `stimulus_effective_transfer_fraction_mean` 保留为逐轮 selected_match 与 raw residual 的审计口径；raw residual 若已被 residual tail -> memory_id 吸收，不应误判为未处理污染。再看 `stimulus_best_match_candidate_count`、`stimulus_cut_common_part_total_count`、"
        "`stimulus_best_match_common_part_count`、`stimulus_best_match_strict_overlap_fast_reject_count`、`stimulus_cut_exact_fast_path_hit_count`、`stimulus_cut_full_inclusion_fast_path_hit_count`、`stimulus_cut_single_group_fast_path_hit_count`、`stimulus_cut_ordered_subsequence_fast_path_hit_count`、`stimulus_cut_cache_hit_count`、`stimulus_cut_cache_zero_copy_hit_count`、`stimulus_cut_normalize_cache_hit_count`、`stimulus_cut_normalize_cache_zero_copy_hit_count`、`stimulus_cut_normalize_reusable_hit_count`、`stimulus_cut_signature_fast_path_hit_count`、`stimulus_cut_empty_group_fast_path_hit_count`、`stimulus_cut_full_group_fast_path_hit_count` 和 `timing_stimulus_level_ms`；"
        "owner-local residual normalization 看 `stimulus_anchor_owner_residual_presence_cache_hit_count`、`stimulus_anchor_owner_residual_presence_scan_count`、`stimulus_owner_local_residual_list_cache_hit_count`、`stimulus_owner_local_residual_index_build_count/cache_hit_count`、`stimulus_owner_local_residual_raw_signature_hit_count/common_signature_hit_count`、`stimulus_owner_local_residual_fuzzy_equivalent_call_count/cache_hit_count/signature_hit_count/fast_reject_count`、`stimulus_owner_local_residual_common_overlap_fast_reject_count`、`stimulus_owner_local_residual_fuzzy_unit_bucket_pruned_count` 与 `stimulus_owner_local_residual_fuzzy_equivalent_cut_count`。锚点 owner 残差存在性缓存只缓存 diff_table 里是否已有 residual/common entry，不缓存 ER/EV、疲劳或同包重复计数；unit 分桶剪枝只跳过 unit 数不可能等价的候选；common overlap 快速拒绝只在两侧都是严格 unit 签名 profile、且签名重叠上界达不到最小共同覆盖时跳过 maximum_common_part。它不拒绝属性、数值、时间或模糊 ST profile，不改变残差共有结构或完整身份语义；`stimulus_round_debug_full_text_rounds`、`stimulus_round_debug_token_preview_limit` 与 candidate detail limit 只控制刺激级 round_details 的审计负载和前端可读性，不应被解释为认知链路被剪枝；"
        "缓存中和性能看 `cache_priority_theoretical_match_fast_reject_count`、`cache_priority_cut_cache_hit_count`、`cache_priority_cut_cache_zero_copy_hit_count`、`cache_priority_cut_cache_store_count`、`cache_priority_cut_exact_fast_path_hit_count`、`cache_priority_cut_single_group_fast_path_hit_count`、`cache_priority_cut_ordered_subsequence_fast_path_hit_count`、`cache_priority_cut_normalize_cache_zero_copy_hit_count`、`cache_priority_cut_normalize_reusable_hit_count`、`cache_priority_cut_signature_fast_path_hit_count`、`cache_priority_cut_empty_group_fast_path_hit_count`、`cache_priority_cut_full_group_fast_path_hit_count` 与 `timing_cache_neutralization_ms`；理论低分剪枝只用 token 重叠计算软匹配分上界，低于阈值才跳过共同切割，不改变能通过候选的 SA 粒度中和；"
        "感应 raw residual 静态缓存看 `induction_raw_residual_projection_profile_local_cache_hit_count/shared_cache_hit_count/cache_store_count`、`induction_raw_residual_exact_candidates_local_cache_hit_count/shared_cache_hit_count/cache_store_count`、`induction_raw_residual_component_candidates_local_cache_hit_count/shared_cache_hit_count/cache_store_count`、`induction_full_inclusion_shared_cache_hit_count/store_count` 与 `timing_induction_hdb_propagation_ms`；"
        "刺激级尾巴看 `residual_tail_memory_projection_*`，默认应按本轮 `episodic_memory_id` 接管；够能量时合并为运行态记忆，低于阈值时直接消散，不应再产生大量 `rt_residual_*` 或碎片 SA。"
        "`runtime_residual_package_*` / `runtime_residual_promotion_*` 只代表旧残余包 fallback 或对照开关。"
        "`stimulus_shadow_raw_residual_skipped_count` 非零通常表示旧 promotion/影子审计关闭时跳过了影子残差精评分，这是性能模式的预期背景，不应误判为主链缺失。"
        "如果需要时间 wildcard / raw residual shadow 全量审计，可建议关闭 `stimulus_residual_memory_shadow_skip_when_promotion_disabled_enabled` 做对照。\n"
        "11) TimeSensor 和 delayed tasks 的过热判断需要引用 bucket energy、delayed task 创建/执行数、耗时、cooldown/top_k/gain 配置，并用禁用或降参对照验证。\n"
        "\n"
        "报告语气：中文输出，保持审慎、具体、克制。可以指出严重问题，但不要用夸张措辞；不要为迎合理论而忽略反证。\n"
    )


def _current_ap_design_baseline() -> str:
    return """
当前 AP 设计基线摘要（用于帮助审阅模型理解理论文本和指标；若与 manifest/config 明显冲突，请在报告中说明冲突并以实际运行配置为准）：

1. ER/EV 能量语义
   - 实能量 ER 表示现实发生的证据强度，主要来自外源性感受器、先天规则或实际行动消耗后的行动节点赋能。
   - 虚能量 EV 表示基于记忆和经验的预期强度，主要来自感应赋能、内源性刺激、注意力调制和结构/记忆残差传播。
   - 注意力模块对被选中的记忆体/对象进行波形调制，通常整体放大或抑制对象携带的 ER 与 EV；内源性刺激中的 EV 不应被误写为 ER。
   - HDB 基础权重应体现 ER/EV 语义：实能量命中新对象或已有对象时以 ER 强度、近因和疲劳等因素做加法增益；纯 EV 新建内容可以被记录为“想象/预测曾出现过”，但基础权重应为 0 或极低，默认不应像真实经验一样参与强感应赋能。
   - 虚能量对已有权重的磨损应更像乘法折损而非线性减法；无论被 EV 多次命中，都不应轻易把历史权重硬扣到 0。审阅时请区分“想象内容被记录”“真实经验权重增强”和“预测磨损”三种现象。

2. SA 是实际能量载体，ST/结构是统计与索引对象
   - 当前新口径中，真正拥有能量粒度的是 SA；字符串、共现组、时序结构、CS 事件、残差结构等 ST 对象应主要统计其内部 SA 的 ER/EV、能量图景和上下文。
   - 感应赋能的“目标”可以是结构数据库内的残差信息，但实际赋能应按残差信息的能量图景比例分配到其中 SA。
   - 审阅时要区分状态池独立 SA 的实时能量、结构中 SA 的统计能量、以及前端为了可读性展示的聚合对象。

3. 分形式感应赋能与剪枝
   - 外源性刺激赋予 A 实能量后，A 可按比例诱发其数据库中的一级残差对象 A1/A2/A3 获得 EV；下一轮先传播 EV，让 A1 继续诱发 A11/A12 等，再由仍有 ER 的 A 继续诱发一级残差。
   - 理想图景是逐层探索：每一圈层的 EV 总量与上层来源能量保持近似比例关系（可允许 0.9/1.1 等系数），直到无数据库、命中记忆残差叶子、或赋能量低于阈值被剪枝。
   - EV 总量可自然高于 ER，比例近似反映平均探索深度；不要仅用 ER/EV 总量比直接判定能量失衡，除非配置明确启用了相应平衡目标。
   - 感应赋能应剪枝实际权重过低、来源能量过低或赋能量低于状态池保留阈值且对象当前不在池中的目标；这类剪枝是规模保护，不等于理论机制缺失。

4. 完整身份、来源元数据与内源汇聚
   - 新版默认 growth 口径下，正式 HDB-backed 状态池结构不应再以“B(context=A)”半成品作为主身份；它应是 A+B 这样的完整对象，身份由完整特征信息经精确身份解析/查存一体得到。
   - owner DB、growth_source、prior_context、parent_ids 等只说明对象本轮如何被激活或从哪里长出来，是 provenance/审计信息，不应成为 A+B 的身份组成部分。同一完整结构即使由不同路径激活，也应汇聚到同一个 HDB-backed ST。
   - legacy residual/CS 对照、运行态残余包、属性刺激元锚点和旧上下文结构仍可能保留 context/anchor 元数据。审阅时要区分“正式完整身份”“属性锚点评分元数据”“旧 residual/context 诊断残留”“旧 context/provenance 审计字段”和“provenance 来源链”，不能把所有 context 字段都解释成新版主身份。
   - 当多个对象进入注意力/内源性刺激流后，刺激流可按字符/字符串/SA 内容汇聚，不携带原状态池 provenance 身份，因此相同内容可以叠加强度，形成内源性波峰，允许高概率或情绪赋能事件压过外源刺激。
   - 内源性刺激本身不保留独立时序组；它会作为一个共现组并入外源性刺激的最后一个时序组。字符串信息仍应保留，但审阅时不要把内源共现组误读成外源时序输入。

5. 残差记忆与“取消专门记忆池”的方向
   - 新口径下，刺激级查存一体已经把本轮完整刺激流保存为 episodic memory。若查存后仍有未完全吸收的刺激尾巴，默认不再包成 `rt_residual_*`、不再等待晋升，而是把这段尾巴视为该完整记忆的运行态能量回响，直接按本轮 `episodic_memory_id` 接管：够能量时合并到 StatePool 中的 `em` 记忆对象，低于阈值时直接消散。
   - 这条路径的身份是 memory_id，不是尾巴内容另造的临时结构 id；能量仍按尾巴 SA 粒度结算到 `residual_tail_memory_projection_*` 与 `component_energy`，显示内容则优先用完整刺激记忆内容。`residual_tail_memory_projection_handled=1` 表示尾巴已经由 memory_id 路径消费，即使 `applied=0` 也不应再期待碎片 SA 或旧残余包入池。审阅时若看到 `runtime_residual_package_*` 或 `runtime_residual_promotion_*`，应先检查 manifest/config 是否显式开启旧 fallback。
   - 内源性刺激有分辨率上限，理论上不应把完整长记忆无限回灌；若报告怀疑记忆无限叠加，应引用 internal_resolution、残差长度、CAM 选择、`induction_growth_memory_terminal_passthrough_count`、`memory_runtime_projection_*`、`residual_tail_memory_projection_*` 和状态池增长证据。
   - 若旧记忆池/MAP 反馈仍开启，应标注这是兼容旧口径或开关状态，不要把旧路径直接当成新理论必然缺口。默认主链优先看感应生长和运行态记忆旁路。

6. 查存一体、残差结构与上下文数据库
   - 查存一体通过最大共同切割建立残差结构；例如“你好啊”和“你好!”在“你”的数据库中可抽出上下文为“你”的结构“好”，并把残差“啊”“!”移动到“你好”上下文下。
   - 残差记忆、残差结构、新进入残差对象之间都可创建共有结构；完全相同时应增加权重而非重复存储。
   - 新对象取 id 原则上应先查缓存，缓存未命中再走查存一体，以建立从基础 SA 到深层结构的索引链；仅新建裸 id 但不接入索引链会影响后续刺激级命中。
   - 刺激级剩余内容默认不再碎片 SA 回灌，也不再整体进入状态池为待晋升残余包；它优先作为本轮完整 episodic memory 的尾巴能量投影，太弱则被视为已消散的尾响。旧“运行态残余包 -> 注意力/高能晋升 -> HDB-backed ST”只作为 legacy fallback 或 A/B 对照。
   - 因此默认运行中 `residual_tail_memory_projection_applied` 可以非零，`runtime_residual_package_applied` 与 `runtime_residual_promotion_promoted_count` 应接近 0。若旧残余包指标非零，请先查配置，而不是把它解释为新版必要主链。

7. 感应生长、认知拼接与软匹配
   - 当前默认主链已经从“残差投影 + CS 拼接”迁移为“感应生长方案”：刺激级命中对象 A 后，HDB induction 从 A 的局部数据库发现残差目标 B，Observatory 将 per-source residual candidate 直接投影为完整结构 A+B。
   - A+B 的身份不继承 owner DB。owner DB 只说明“本轮从哪个结构库生长出来”，完整对象身份应由 A+B 的完整特征内容通过精确身份解析/查存一体得到；同一完整结构从不同路径激活时应汇聚到同一个 HDB-backed ST。
   - 生长投影要保留组件能量审计：A 的 ER 可以作为 source-side ER 份额显示在 A+B 结构统计里，B 的残差预测能量仍应是 EV；审阅字段优先看 `induction_growth_source_component_er_total`、`induction_growth_residual_component_ev_total`、`induction_growth_total_delta_er`、`induction_growth_total_delta_ev`。纯 EV 新建结构基础权重为 0，ER 支持的新建才按 ER 强度给小幅加法增益。
   - 结构退化现在只是 StatePool 运行态分辨率下降：低能组件会在当前视图中淡出，但对象仍保留自己的完整 ST/root_structure_id，不重新查存一体、不应创建新的退化 HDB id，也不写新的退化 HDB 结构。相同完整结构的不同分辨率视图可以在状态池内按 root identity 合并，合并对象的组件 ER/EV 汇总到同一个运行态对象；growth source/root_source 仅作生长来源审计，不参与同源分支身份合并。
   - 审阅运行态退化时优先看 `pool_runtime_resolution_degraded_item_count`、`pool_runtime_resolution_active_component_count`、`pool_runtime_resolution_dropped_component_count`、`maintenance_runtime_resolution_refreshed_item_count` 与 `maintenance_runtime_resolution_degraded_item_count`；这些字段为 0 不等于机制缺失，可能只是本 run 没有组件跌破阈值或摘要未包含分辨率字段。
   - 状态池 Top 中 ER 偏高不自动表示感应 EV 缺失。小型/稀疏数据集、外源文字 tick、刚命中的完整记忆对象和 source-side ER 继承，都会让总能量 Top 看起来 ER 更醒目；判断 EV 是否正常，应同时看 induction delta、growth residual component EV、pool EV/ER ratio、EV Top/CP Top 与输入 tick/空 tick 切片。
   - 刺激级查存一体的命中赋能现在不再让“命中 SA 能量 / 总刺激能量”直接线性压低结果，而是先对刺激侧覆盖率和结构侧覆盖率做可配置幂次缓和，再用 Hill 转移曲线把 similarity 映射为实际能量转移比例。新版验收优先看 growth 对象投影口径：多数有有效命中的 source tick 中，`stimulus_object_projection_total` 应高于 `stimulus_unhandled_residual_total`，`stimulus_object_projection_to_unhandled_residual_ratio` 多数应大于 1；`stimulus_memory_tail_absorbed_total` 表示 raw residual tail 已按 episodic memory_id 并入完整记忆对象，不应再当作最终污染。`stimulus_transfer_matched_total` / `stimulus_final_residual_total` 保留为逐轮 selected_match 与 raw residual 审计；若它们长期低于 1，应先检查是否只是完整字符串/结构种子和 memory tail 吸收未计入旧口径，再结合 `stimulus_effective_transfer_fraction_mean`、`stimulus_match_v2_score_mean`、候选/剪枝/共同切割指标判断是命中不足、候选太少、合流输入过长，还是曲线仍过保守。
   - 当前不默认加感应过度预测门控；连续发散、过度想象和沿一个种子持续生长是拟人化能力的一部分。只有当 metrics 同时显示状态池/HDB 无界膨胀、Top 重复自指、能量不受衰减/疲劳约束或单 tick 性能异常时，才建议启用 `growth_projection_overprediction_gate_enabled` 做保守对照。
   - 默认 `cognitive_stitching_stage=disabled`，CS 不再是主链必经环节。它保留为旧 residual 方案的回滚/对照工具：当用户显式开启 residual 或 CS 时，才用 `context_match_v2`、精确上下文索引、软扫描、前缀裁剪和低能侧吸收指标审阅拼接质量。
   - 如果 CS 被显式启用，`concat_context_structure` 仍是合法的一等产出：结果会以普通 HDB 结构落库并回到状态池，而不是强行包装成 CS 事件壳。
   - CS 精确匹配的吸能不是抽干高能对象：即使上下文完全匹配，也按低能侧总能量乘以 `context_concat_exact_absorb_ratio` 附近的比例转移；action_log 中的 source/target absorbed total 应近似对称。
   - 跨对象联想主要依靠注意力选出的多对象进入内源性刺激，再由刺激级查存一体命中或现场创建同时包含多者特征的信息整体；这更像“把当前状态池叠加图景重新采样为新的种子”，不应强行要求 CS 承担所有联想。
   - 顺序敏感、属性锚点、数值 SA、时间间隔等应尽量采用连续分数而非硬门控：精确匹配胜出，近似匹配可在低分时保留泛化能力，过低分数被剪枝。

8. 属性刺激元、CFS 与数值匹配
   - 属性刺激元等效于 SA，但携带锚点；锚点匹配提供额外增益而非绝对门控。奖励/惩罚信号是全局 SA，不是普通属性。
   - 数值刺激元（例如时间间隔、压力、期待、违和/正确等数值化分量）匹配时应按数值接近程度给 0..1 的贡献，再叠加疲劳、近因、顺序、S 型拟合等因素。
   - 认知感受初始由先天规则触发，一旦进入状态池和记忆/结构残差，也可像普通 SA 一样被注意、拼接、感应赋能和后天学习。

9. 行动、奖励/惩罚与教师信号
   - 行动节点也是 SA。先天规则可冷启动行动接口；当行动真正触发并消耗驱动力时，消耗量应回写为行动节点能量，使系统能后天认识自己的行动。
   - 奖励信号和惩罚信号也是全局 SA，可进入状态池、注意力、刺激流和结构；状态池中的实时奖励/惩罚能量影响全局行动阈值，含行动节点与奖惩信号的结构会产生局部驱动力调制。
   - 外置教师奖惩主要用于快速学习：理想效果是让行动节点、目标上下文和 reward/punish_signal 以普通 SA/结构形式进入记忆统计，而不是污染为不可泛化的硬编码标签。
   - 时序归因允许近时行动与反馈在状态池中自然相遇，不追求百分百归因；审阅应关注学习趋势、归因窗口和证据链，而不是要求单轮绝对准确。

10. 缓存中和与最小认知压
   - 新刺激流进入时，应优先中和状态池内已有对象的认知压，形成认知锚点并降低不必要的查存一体开销。
   - 中和打分可按结构软匹配计算，但实际中和应落到 SA 粒度：每个 SA 按缺口、刺激能量和匹配分数缩放赋能。
   - 认知压低、能量缺口不存在、刺激对应能量为 0 等场景可剪枝，以减少重复计算。

11. 情绪递质 NT 与先天规则外显
   - 情绪递质通道不只是标签，应影响注意力资源、行动阈值、选择宽窄、半衰期等系统系数。
   - 理想工程形态是这些影响规则和参数尽可能在 innate rules / config 中外显，便于人工调整和实验对照；报告应指出哪些效果有指标支持，哪些仍缺少可调入口或可观测字段。

12. 报告评估重点
   - 优先评价：ER/EV Top5 连续性是否呈现可读注意/预测轨迹；`induction_projection_mode_growth`、`induction_growth_target_count`、`induction_growth_identity_hit_count/created_count/local_cache_hit_count/shared_cache_hit_count/deduped_count` 是否说明 A+B 感应生长正在稳定落地；刺激尾巴是否按 memory_id 接管、旧残余包 fallback 是否保持关闭；内源刺激是否受分辨率约束；教师奖惩是否进入可学习结构；CFS/NT 是否体现自我状态认知；缓存中和是否降低认知压；性能开销是否集中在可优化路径。
   - 图表与 AutoTuner 的默认主视图优先展示 growth、完整身份、运行态分辨率、组件 ER/EV、注意力/内源重采样和性能热点；旧 context/provenance、`cs_*`、`map_*` 与旧式能量平衡指标默认折叠为诊断/回滚视图。除非 manifest/config 显式开启旧路径，不要把这些折叠项的 0 值当成主故障。
   - 对感应生长的优先审阅口径是：完整身份命中是否随语料成熟上升；新建是否集中在新语料冷启动而非重复同内容；同 tick 本地身份缓存与跨 tick shared cache 是否正在减少重复精确解析，`shared_cache_stale_count` 是否接近 0；`induction_growth_persistence_batch_enabled` 是否为 1，以确认新建 A+B 结构时只延迟磁盘 flush、不延迟内存身份与索引生效；runtime-only 是否只是低置信暂存；终端记忆旁路是否与记忆激活/运行态记忆字段一致；source-side ER 与 residual-side EV 是否没有混淆。
   - 对运行态分辨率的优先审阅口径是：`pool_runtime_resolution_degraded_item_count`、`pool_runtime_resolution_active_component_count`、`pool_runtime_resolution_dropped_component_count`、`maintenance_runtime_resolution_refreshed_item_count` 与 `maintenance_runtime_resolution_degraded_item_count` 只描述状态池中完整对象的运行态显示/解释分辨率，不代表 HDB 里创建了新的退化身份。若这些字段升高，请结合状态池软容量、半衰期、组件能量阈值和 Top 可读性分析；不要建议用旧上下文多身份分流来“修复”它。
   - 对性能的优先审阅口径是：先看刺激级对象投影是否压过未处理净残余：`stimulus_object_projection_total`、`stimulus_object_projection_seed_total`、`stimulus_object_projection_matched_total`、`stimulus_memory_tail_absorbed_total`、`stimulus_unhandled_residual_total`、`stimulus_object_projection_to_unhandled_residual_ratio`、`stimulus_object_projection_dominates_unhandled_residual`。默认希望多数有命中的 source tick 满足对象投影高于未处理净残余；`stimulus_transfer_matched_total`、`stimulus_final_residual_total`、`stimulus_transfer_to_residual_ratio`、`stimulus_transfer_dominates_residual`、`stimulus_effective_transfer_fraction_mean` 是逐轮 selected_match 与 raw residual 审计口径。若 growth 投影口径不满足，再看 `stimulus_cut_common_part_total_count`、`stimulus_best_match_common_part_count`、`stimulus_best_match_strict_overlap_fast_reject_count`、`stimulus_cut_exact_fast_path_hit_count`、`stimulus_cut_full_inclusion_fast_path_hit_count`、`stimulus_cut_single_group_fast_path_hit_count`、`stimulus_cut_ordered_subsequence_fast_path_hit_count`、`stimulus_cut_cache_hit_count`、`stimulus_cut_cache_zero_copy_hit_count`、`stimulus_cut_cache_deepcopy_count`、`stimulus_cut_normalize_cache_hit_count`、`stimulus_cut_normalize_cache_zero_copy_hit_count`、`stimulus_cut_normalize_reusable_hit_count`、`stimulus_cut_normalize_reusable_group_count`、`stimulus_cut_signature_fast_path_hit_count`、`stimulus_cut_empty_group_fast_path_hit_count`、`stimulus_cut_full_group_fast_path_hit_count`、`stimulus_cut_reindex_fast_path_hit_count` 与 `timing_stimulus_level_ms`，同时看 owner-local residual normalization 的 `stimulus_anchor_owner_residual_presence_cache_hit_count`、`stimulus_anchor_owner_residual_presence_scan_count`、`stimulus_owner_local_residual_list_cache_hit_count`、`stimulus_owner_local_residual_index_build_count/cache_hit_count`、`stimulus_owner_local_residual_raw_signature_hit_count/common_signature_hit_count`、`stimulus_owner_local_residual_fuzzy_equivalent_call_count/cache_hit_count/signature_hit_count/fast_reject_count`、`stimulus_owner_local_residual_common_overlap_fast_reject_count`、`stimulus_owner_local_residual_fuzzy_unit_bucket_pruned_count` 和 `stimulus_owner_local_residual_fuzzy_equivalent_cut_count`。锚点 owner 残差存在性缓存只缓存 diff_table 里是否有 residual/common entry，不缓存 ER/EV、疲劳或同包重复计数；unit 分桶剪枝只跳过 unit 数不可能等价的候选；best-match strict overlap 与 common overlap 快速拒绝都只在严格 unit 签名上界已经低于所需共同覆盖时跳过共同切割，属性/数值/时间/模糊 ST 仍走完整评分，不改变残差共有结构或完整身份语义。`stimulus_round_debug_full_text_rounds`、`stimulus_round_debug_token_preview_limit` 和候选明细上限只影响 round_details 的调试体积与前端展开成本，不影响命中、学习、能量转移或 owner-local residual 写入。再看缓存中和 `cache_priority_cut_cache_hit_count`、`cache_priority_cut_cache_zero_copy_hit_count`、`cache_priority_cut_cache_store_count`、`cache_priority_cut_exact_fast_path_hit_count`、`cache_priority_cut_single_group_fast_path_hit_count`、`cache_priority_cut_ordered_subsequence_fast_path_hit_count`、`cache_priority_cut_normalize_cache_zero_copy_hit_count`、`cache_priority_cut_normalize_reusable_hit_count`、`cache_priority_cut_signature_fast_path_hit_count`、`cache_priority_cut_empty_group_fast_path_hit_count`、`cache_priority_cut_full_group_fast_path_hit_count` 与 `timing_cache_neutralization_ms`，再看感应生长 `timing_induction_projection_prepare_ms`、identity created/hit/cache、`induction_growth_persistence_batch_enabled`、`timing_induction_target_apply_ms`、`induction_growth_target_apply_ref_fast_merge_enabled`、`induction_growth_target_apply_fast_ref_hit_merge_count`、`induction_growth_target_apply_insert_log_enabled` 和 `induction_growth_target_apply_insert_log_suppressed_count`。共同切割 exact/full-inclusion/single-group/ordered-subsequence 快路径命中表示完全相同、稳定完整包含、单共现组或无歧义有序子序列比较已经跳过 DP/LCS；共同切割缓存命中表示重复 DP 被吸收；normalized group 直接复用、签名直读、空 residual/common group 快构造、完整 group 复用和重索引复用命中，表示重复 normalize/组装被跳过；这些都是纯性能路径，不代表候选、学习或能量结算被剪薄。common-part 零拷贝命中是默认性能路径，normalize cache 零拷贝默认应为 0，只有显式开启 `normalize_sequence_groups_cache_zero_copy_enabled` 时才会升高；深拷贝非零通常表示启用了保守回滚开关。缓存中和的 common-part 缓存只复用中和阶段 CutEngine 的读-only 切割结果，不改变 SA 粒度能量结算；若命中长期接近 0 且耗时升高，可回滚 `priority_neutralization_common_part_cache_enabled=false`。生长创建持久化批处理为 1 时，A+B 结构、pointer index 和状态池投影仍即时可见，只是结构/db JSON 写入合并到 HDB 延迟持久化 flush；为 0 时 projection_prepare 慢尾可能包含即时落盘成本。target apply 的 exact ref 快合并命中表示已在状态池中的 A+B 直接经能量引擎合并 ER/EV，跳过候选 state_item 重建；日志抑制数表示关闭逐条 brief/detail 文件日志以减少慢尾，不表示目标被跳过。尾巴投影应结合 `residual_tail_memory_projection_handled/applied/total_energy/token_count` 与 `stimulus_memory_tail_absorbed_total` 判断：handled 非零表示尾巴已被 memory_id 路径消费，applied 非零表示形成了可见 em 能量增量；handled=1 且 applied=0 通常只是低能尾响消散。运行态残余包晋升只属于 legacy fallback/A-B 对照，应结合 `runtime_residual_promotion_exact_rebind_count`、`runtime_residual_promotion_full_identity_count`、`runtime_residual_promotion_hdb_fallback_count` 与 `timing_runtime_residual_promotion_ms` 判断是否被显式打开；默认主链不应依赖它。`stimulus_shadow_raw_residual_skipped_count` 非零说明 promotion 关闭时跳过了观测型影子残差精评分；这是默认性能保护，不等于主链少做了查存一体。
   - 缓存中和理论低分剪枝请看 `cache_priority_theoretical_match_fast_reject_count`。它只用 token 重叠计算软匹配分上界，理论上低于阈值才跳过共同切割；这属于提前判负的性能保护，不改变本来能通过候选的 SA 粒度中和。
   - 记忆相关耗时请按新版口径拆开：`memory_path_mode=runtime_em_only`、`memory_feedback_applied_count=0` 和 `timing_memory_feedback_apply_ms=0` 通常说明旧 MAP/专门记忆池反馈未运行；`memory_runtime_projection_*` 表示残差记忆/运行态记忆旁路投影，`time_sensor_memory_sample_*` 表示时间感受/回忆采样，两者可以存在但不等于旧记忆池维护。不要把“memory feedback 为 0”误判为记忆链路失效。
   - 指标中已有 `pool_cp_top5`、`pool_cp_structure_top5`、`pool_cp_top1_cp` 等认知压 Top 字段时，应把它们用于定位 ER/EV 拉扯波峰；它们是新版图表和实时监控口径，不应退回旧“上下文对象 Top”解释。
   - 感应 raw residual 静态解析缓存字段要作为新版性能基线的一部分审阅：`induction_raw_residual_projection_profile_local_cache_hit_count/shared_cache_hit_count/cache_store_count`、`induction_raw_residual_exact_candidates_local_cache_hit_count/shared_cache_hit_count/cache_store_count`、`induction_raw_residual_component_candidates_local_cache_hit_count/shared_cache_hit_count/cache_store_count`、`induction_full_inclusion_shared_cache_hit_count/store_count`。这些缓存只复用结构形状、候选身份和 profile 包含判定，不缓存 entry runtime_weight、疲劳、近因或本轮 EV/ER 分配；命中升高应优先解释为减少重复 owner-subtract、签名查询、组分查询和包含判定。
   - CS 仅作为显式开启的 residual/对照路径审阅。不要反复把“结构级查存一体关闭、当前走 CS 认知拼接”当作主要发现；在新版默认 growth + CS disabled 口径下，这通常不是问题。只有当 CS 被显式开启，或它解释了具体指标异常、缺证、性能瓶颈或理论偏离时，才展开分析 `cs_*` 细节。
   - 对所有“0 值、平顶、突刺、长期高位、合约失败、行动未触发”等现象，先给出证据和可证伪解释，再给优化建议。
   - 评价叙事可读性和 Top 项形态时必须考虑语料规模：小型/低成熟 HDB 下，单字 SA 波峰偏多、短期叙事不够流畅、HDB 结构增长快，可能是正常冷启动/稀疏语料现象。请同时看 `pool_er_atomic_feature_sa_top5_count`、`pool_ev_atomic_feature_sa_top5_count` 与 `pool_er_structure_top5_count`、`pool_ev_structure_top5_count`：ER 侧原子 SA 偏多通常是外源真实证据仍可见；EV 侧原子 SA 长期偏多才更接近旧残差自循环风险。只有在出现重复自指拼接、能量失控、无界状态池膨胀、每 tick 全库扫描或语义对象长期不可收敛等证据时，才应判为机制异常。
""".strip()


def build_review_prompt(
    *,
    run_id: str,
    config: LLMReviewConfig,
    theory_core_text: str,
    manifest_text: str,
    dataset_text: str,
    metrics_text: str,
    metrics_note: str,
    curriculum_summary_text: str = "",
    curriculum_summary_note: str = "",
    accumulated_summary_text: str = "",
    accumulated_summary_note: str = "",
    expectation_contract_events_text: str,
    extra_context: str,
) -> str:
    # Keep prompt plain and auditable. No fancy tool calls.
    parts: list[str] = []
    parts.append(f"本次审阅 run_id: {run_id}")
    parts.append("")

    parts.append(_current_ap_design_baseline())
    parts.append("")

    parts.append("以下是 AP 理论核心文本（尽可能完整提供）：")
    parts.append("```text")
    parts.append(theory_core_text.strip())
    parts.append("```")
    parts.append("")

    parts.append("以下是本次实验运行的 manifest（运行元信息）：")
    parts.append("```json")
    parts.append(manifest_text.strip())
    parts.append("```")
    parts.append("")

    if dataset_text.strip():
        parts.append("以下是本次实验使用的数据集内容（可能是 normalized YAML 或 source 文件）：")
        parts.append("```text")
        parts.append(dataset_text.strip())
        parts.append("```")
        parts.append("")

    if extra_context.strip():
        parts.append("以下是额外上下文（模块配置、规则文件等）：")
        parts.append("```text")
        parts.append(extra_context.strip())
        parts.append("```")
        parts.append("")

    if curriculum_summary_text.strip():
        parts.append(
            "以下是行为课程专用结构化摘要 curriculum_metrics_summary.json（优先审阅材料）。"
            "请优先使用这里的 top5_snapshots、top5_quality_summary、top5_root_summary、identity_maturation、identity_resolution_summary、segments、expectation_contract_windows、hdb_growth；"
            "性能慢尾请优先读取 performance_hdb_diagnostic_summary 的分段趋势、最慢 tick 和相关字段；"
            "只有当这里确实没有对应字段时，才说 Top5/identity/合约窗口/性能证据缺失。"
        )
        parts.append(curriculum_summary_note.strip())
        parts.append("```json")
        parts.append(curriculum_summary_text.strip())
        parts.append("```")
        parts.append("")

    if accumulated_summary_text.strip():
        parts.append(
            "以下是累计行为课程批次摘要 accumulated_curriculum_summary.json（跨轮优先审阅材料）。"
            "请用它评价在不清除 HDB、重复经历相似数据集后，identity/cache 是否成熟、created/target 是否下降、"
            "shared/local cache 是否上升、HDB 增长是否可控、合约是否保持稳定。"
        )
        parts.append(accumulated_summary_note.strip())
        parts.append("```json")
        parts.append(accumulated_summary_text.strip())
        parts.append("```")
        parts.append("")

    parts.append("以下是本次运行的 metrics 审阅材料（优先包含压缩摘要，其后是 compact JSONL 头尾摘录）。")
    parts.append(metrics_note.strip())
    parts.append("```jsonl")
    parts.append(metrics_text.strip())
    parts.append("```")
    parts.append("")

    if expectation_contract_events_text.strip():
        parts.append("以下是 expectation contract 事件摘要（用于核对 source tick 与 synthetic 反馈/成功 settle 的对应关系）：")
        parts.append("```json")
        parts.append(expectation_contract_events_text.strip())
        parts.append("```")
        parts.append("")

    parts.append(
        "请基于以上材料输出一份严谨、客观、证据绑定的审阅报告。下面是必须遵守的固定结构，不是可选建议；不要删除、合并或跳过前 6 个架构评价章节。\n"
        "审阅优先级补充：如果本提示词包含 `curriculum_metrics_summary.json`，必须优先读取其中的 `top5_snapshots`、`top5_quality_summary`、`top5_root_summary`、`identity_maturation`、`identity_resolution_summary`、`segments`、`expectation_contract_windows`、`hdb_growth`、`performance_hdb_diagnostic_summary`；"
        "这些字段存在时，不要笼统声称缺少 Top5、identity、合约窗口或性能明细，而要具体评价字段是否足以支撑结论。\n"
        "评价 identity exact hit 偏低时，必须检查 `identity_resolution_summary` 中 created 是否主要由 create_exact_lookup_skipped 解释，以及 shared/local cache、lookup_disabled、stale、deduped 是否支持或削弱“身份成熟”的判断。\n"
        "评价 Top5 重复或字符片段化时，必须检查 `top5_root_summary` 和每个 snapshot 的 root 统计；如果重复主要集中在同一 root 或 root overlap 较高，应写成 root 级重复/运行态视图问题或强召回证据，而不是直接判语义失败。\n"
        "评价 CFS/NT/action 因果链时，必须优先看每个 `expectation_contract_windows` 的 `causal_chain` 数组：trigger/ready/attempted/scheduled/executed、first_* tick、drive/threshold/margin、teacher/reward/punish/CFS live、attention/threshold scale/learning delta 和 chain flags。字段存在但仍不足时，应写“仍是窗口相关证据，不是完整因果证明”，不要误写成字段缺失。\n"
        "评价性能慢尾时，必须优先看 `performance_hdb_diagnostic_summary` 的 `segment_timing_trend`、`slowest_ticks_by_total_logic_ms` 和 `top_correlated_metrics_with_total_logic_ms`；这些相关字段只能作为定位线索，不能当作严格因果证明。\n"
        "如果本提示词包含 `accumulated_curriculum_summary.json`，必须单独评价跨轮趋势，尤其是 r01/r02/r03 的 `created_to_target`、`shared_cache_hit_to_target`、`local_cache_hit_to_target`、HDB latest/delta 和 contract success 是否体现保留 HDB 后的积累。\n"
        "短程 300/1000/3000 tick 行为课程的合理评价目标是局部机制证据：记忆召回/关键特征重采样、Top5 结构化、identity/cache 成熟趋势、奖惩行动合约、CFS/NT 对应关系；不要要求它证明百万语料级完整逻辑能力。\n"
        "\n"
        "## 1. 总评与架构定位（必须在报告开头）\n"
        "- 用 2-4 段给出整体评价：当前实现是否像一个可运行的 AP 原型，健康度、理论贴合度、可解释性、可继续优化性分别如何。\n"
        "- 必须给出“整体评分/等级”和“整体置信度”，并列出支撑该总评的 3-6 个关键证据字段。\n"
        "- 必须同时写正面能力、主要短板和最关键不确定性；不要只有问题清单。\n"
        "\n"
        "## 2. 与其它架构的对比评估（架构效果与区别评估，必须有表格）\n"
        "- 用表格逐项比较：纯规则系统、纯向量/RAG 检索记忆、普通工具调用 agent loop、传统强化学习/行为策略、预测加工/主动推断类架构。\n"
        "- 表格列必须包含：对比对象、AP 相似点、AP 差异点、这次 run 体现出的优势或特点、代价/局限、证据或缺证。\n"
        "- 若某项没有证据，写“本次材料不足”，不要省略该行。\n"
        "\n"
        "## 3. 创新点、特点与可应用场景（必须有）\n"
        "- 分开写“理论设计层面的创新/特点”和“本次 run 已经观察到的实现效果”。\n"
        "- 至少覆盖：ER/EV 双能量、感应生长 A+B、完整身份汇聚、运行态分辨率下降、SA/ST 结构层级、内源刺激汇聚、认知感受 CFS、自适应注意/行动/奖惩链路、缓存中和/认知压。\n"
        "- 给出可能应用场景，例如：可解释长期记忆、带自我状态观测的 agent、教师奖惩塑形、认知过程可视化、局部情绪/注意调制实验、低层符号-能量混合研究；每项写适配原因和当前不足。\n"
        "\n"
        "## 4. 拟人度评估（必须证据绑定）\n"
        "- 客观评价这次运行里哪些现象表现出较好的拟人效果，例如短期注意转移、压力/期待参与、内源波峰压过外源、奖惩塑形、叙事连续性、保守行动阈值。\n"
        "- 同时评价哪些部分还机械、僵硬或缺证，例如单字符 EV top、结构优先 Top 缺失、旧 CS 拼接残留、状态池过载、NT 因果链字段不足。\n"
        "- 每条都必须绑定 metric key、tick 区间、Top 项、合约事件或 manifest 字段。\n"
        "\n"
        "## 5. 本次最可靠结论与最大风险\n"
        "- 用 5-10 条说明最可靠发现、最大问题、最大不确定性，以及研究者下一步最该关注的现象。\n"
        "\n"
        "## 6. 证据清单与字段覆盖审计\n"
        "- 列出 run_id、数据集、tick 数量、source/synthetic tick 关系、关键 config、metrics 覆盖情况和缺失字段。\n"
        "- 在说某字段缺失前，必须先检查 metrics digest、manifest snapshot、status/config 中是否已有相关字段；若字段存在但摘要不足，应写“摘要不足/因果链不足”，不要写成“字段不存在”。\n"
        "- 特别注意：NT 通道字段可能以 `nt_DA/nt_ADR/nt_OXY/nt_SER/nt_END/nt_COR/nt_NOV/nt_FOC` 出现，注意力预算字段可能以 `attention_energy_budget*` / `attention_net_delta_energy` 出现，行动阈值调制可能以 `action_threshold_*_scale_mean` 出现；如果这些字段存在，只能评价因果链是否充分，不能说对应数据缺失。\n"
        "- 图表与指标口径也要按新版主次阅读：`induction_growth_*`、`attention_*`、`internal_*`、`stimulus_*`、`pool_*` 是默认主链；`cs_*`、`map_*`、`energy_balance_*` 和 context/provenance 分流图多为诊断/回滚/兼容视图，除非 manifest/config 明确开启相应旧路径，否则不要把它们的 0 值或折叠状态作为主故障证据。\n"
        "\n"
        "## 7. 理论对齐矩阵\n"
        "- 按机制逐行评价。建议列为：机制/理论预期/证据字段与 tick 区间/观测结果/判断(符合、部分符合、缺证、异常)/置信度。\n"
        "- 机制至少覆盖 ER/EV 权重语义、虚能量乘法磨损、感应生长 A+B、完整身份解析与汇聚、运行态分辨率下降、刺激尾巴按 memory_id 合并、旧残余包 fallback 是否关闭、内源刺激合流、CFS/NT、注意力预算、行动/教师奖惩和 HDB 增长。不要只围绕 CS/SLRS 路径开关写矩阵。\n"
        "\n"
        "## 8. 数据异常与解释\n"
        "- 对 0 值、平顶、突刺、长期高位、合约失败、行动未触发、Top5 不连续或不可读等现象逐项分析；每项都区分 Observed、Inferred、Unknown。\n"
        "\n"
        "## 9. 行动与教师奖惩学习链路\n"
        "- 单独评估 action node、reward_signal、punish_signal、teacher_feedback、local map、global threshold、source/synthetic 合约口径之间的证据链。\n"
        "- 对天气工具 action，重点判断“真正执行的时机是否正确、是否符合训练集语境”，而不是简单把“执行频次不高”当作缺陷。若数据表明系统只是经常想到 weather_stub 但只在少数合适时机执行，这可以是符合设计的现象。\n"
        "- 如果存在 `expectation_contract_windows`，必须引用其中至少 1-3 个窗口，说明注册 tick、settle tick、weather trigger/node/drive/threshold/margin/attempted/scheduled/executed、教师信号、CFS/奖惩 live_total、NT/attention/threshold scale 和 learning delta 是否形成合约内闭环；若 compact 中有 `causal_chain`，优先用它给出窗口链路。\n"
        "- 如果 expectation contract 事件摘要已经给出 source_tick_cursor / settled_source_tick_cursor / source_dataset_tick_index 映射，不要再把这一映射误写成缺失；应直接使用这些证据判断时机是否合适。\n"
        "\n"
        "## 10. ER/EV、注意力预算与叙事化观察\n"
        "- 使用状态池 ER/EV Top5、结构优先 Top、`pool_*_atomic_feature_sa_top5_count`、CAM/attention、attention_energy_budget、attention_net_delta_energy、internal stimulus、residual_tail_memory_projection_*、legacy runtime_residual_*、induction_growth_*、memory_runtime_projection_* 等字段，评价是否出现可读的注意/预测连续性。\n"
        "- 如果存在 `top5_snapshots`，必须基于其中至少 3 个 source tick 快照评价 Top5 形态：结构对象/原子 SA/action node/attribute 的比例、前后快照 overlap、root overlap、ER/EV/CP top1 是否对应输入语境或内源重采样。若 Top5 可读性不足，请引用具体快照，并结合 `top5_root_summary` 说明是 root 级重复、运行态分辨率变体、字符片段化还是真正缺乏语义稳定性，而不是说没有 Top5 信息。\n"
        "- 如果存在 `identity_maturation` 和 `segments.items[].identity_maturation`，必须评价 hit/(hit+created)、created/target、shared cache/target 随分段变化是否成熟；如果存在 `identity_resolution_summary`，还必须说明 created 中有多少由 create_exact_lookup_skipped 解释、lookup_disabled/stale 是否为 0、shared/local cache 是否活跃。短程 run 中 identity hit 偏低可以是冷启动或口径现象，但需要与 HDB growth、重复语料和 Top5 结构化程度一起判断。\n"
        "- 新版默认口径下，叙事化观察优先看“状态池种子 -> 感应生长 A+B -> 内源刺激重采样 -> 新种子”的连续性，而不是要求每 tick 都有 CS 拼接动作。\n"
        "- 如果 `induction_projection_mode_growth=1` 且 `cs_enabled=0`，请把它作为当前默认背景；不要把“CS 关闭/没有走 CS 认知拼接”写成核心结论。核心结论应落在感应生长是否发生、完整身份是否汇聚、Top 项是否逐步变长/变具体、刺激尾巴是否按 memory_id 合并、旧残余包 fallback 是否异常出现、能量口径、奖惩学习和性能证据上。\n"
        "- 只有当 manifest/config 显示 CS 被显式开启时，才区分 `narrative_top_items` / `cs_concat_narrative_count` 这类叙事层可见项，以及 `cs_action_log*` / `cs_action_count` 这类实际拼接动作流水；不要把前者误当作后者。\n"
        "\n"
        "## 11. 参数优先建议\n"
        "- 如果只改参数或规则配置，给出 3-8 个建议，包含参数名/位置、建议方向或范围、预期影响、副作用和验证指标。\n"
        "\n"
        "## 12. 工程与观测建议\n"
        "- 如果允许改代码，优先建议新增观测字段、报告展示、缓存/剪枝/性能保护，而不是改变理论主流程；说明风险和回归测试。性能建议需要优先引用 stimulus/growth 共同切割、身份解析、target apply、runtime residual promotion 和磁盘持久化指标。\n"
        "\n"
        "## 13. 下一轮对照实验\n"
        "- 给出可复验实验设计，包括要改的开关、数据集、预期变化、判定指标。\n"
        "\n"
        "## 14. 不应过度断言的部分\n"
        "- 列出由于证据不足而暂不能下结论的机制，以及需要补采的最小字段。\n"
        "\n"
        "## 15. 最终审阅判断\n"
        "- 用一段话收束：当前架构最像什么、最不像什么，当前最有价值的实验信号是什么，下一轮最值得优先修什么。\n"
        "\n"
        "写作约束：每个实质性判断尽量给出至少一个具体证据引用；如果没有证据，请明确写成假设或缺证。"
        "不要只给泛泛建议，也不要把理论预期直接当作实验事实。"
        "在总评、架构区别、创新点、应用场景和拟人度评估部分，允许写出明确的积极现象，但前提是要指出具体证据；如果没有证据，就明确说当前材料不足以判断。"
    )

    return "\n".join(parts).strip() + "\n"


def _read_run_artifacts(*, run_dir: Path, max_prompt_chars: int) -> tuple[str, str, str, str, str, str, str, str, str]:
    manifest_path = run_dir / "manifest.json"
    metrics_path = run_dir / "metrics.jsonl"
    dataset_norm = run_dir / "dataset.normalized.yaml"

    budget = int(max(1_500, max_prompt_chars))
    manifest_text = _safe_read_text(manifest_path, max_chars=min(60_000, max(500, int(budget * 0.12))))

    dataset_text = ""
    if dataset_norm.exists():
        dataset_text = _safe_read_text(dataset_norm, max_chars=min(40_000, max(500, int(budget * 0.08))))
    else:
        # fallback: copy of source dataset (runner writes dataset.source.*)
        for p in sorted(run_dir.glob("dataset.source*")):
            dataset_text = _safe_read_text(p, max_chars=min(40_000, max(500, int(budget * 0.08))))
            if dataset_text.strip():
                break

    metrics_note = ""
    metrics_text = ""
    curriculum_summary_text = ""
    curriculum_summary_note = ""
    accumulated_summary_text = ""
    accumulated_summary_note = ""
    accumulated_budget = min(24_000, max(500, int(budget * 0.12)))
    accumulated_summary_text, accumulated_summary_note = _read_accumulated_curriculum_summary_for_review(
        run_dir,
        char_budget=accumulated_budget,
    )
    curriculum_budget = min(110_000, max(1_000, int(budget * 0.85)))
    curriculum_summary_text, curriculum_summary_note = _read_curriculum_metrics_summary_for_review(
        run_dir,
        char_budget=curriculum_budget,
    )
    if metrics_path.exists():
        metrics_budget = min(
            30_000,
            int(max(1_500, budget - len(curriculum_summary_text) - len(accumulated_summary_text))),
        )
        metrics_text, metrics_note = _read_metrics_jsonl_for_review(metrics_path, char_budget=metrics_budget)

    return (
        manifest_text,
        dataset_text,
        curriculum_summary_text,
        curriculum_summary_note,
        accumulated_summary_text,
        accumulated_summary_note,
        metrics_text,
        metrics_note,
        str(metrics_path),
    )


def _read_ap_theory_core_text(*, max_chars: int) -> str:
    # Repo root: try the known file first.
    root = storage.repo_root()
    candidates = [
        root / "txt版本的理论核心.txt",
        root / "AP理论核心.txt",
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return _safe_read_text(p, max_chars=max_chars)
    # fallback empty
    return ""


def _read_extra_context(*, max_chars: int) -> str:
    # Provide key config/rules sources to help the reviewer propose actionable tuning.
    root = storage.repo_root()
    paths = [
        root / "observatory" / "config" / "observatory_config.yaml",
        root / "cognitive_stitching" / "config" / "cognitive_stitching_config.yaml",
        root / "hdb" / "config" / "hdb_config.yaml",
        root / "state_pool" / "config" / "state_pool_config.yaml",
        root / "attention" / "config" / "attention_config.yaml",
        root / "time_sensor" / "config" / "time_sensor_config.yaml",
        root / "energy_balance" / "config" / "energy_balance_config.yaml",
        root / "action" / "config" / "action_config.yaml",
        root / "innate_script" / "config" / "innate_script_config.yaml",
        root / "innate_script" / "config" / "innate_rules.yaml",
    ]
    chunks: list[str] = []
    for p in paths:
        if not p.exists() or not p.is_file():
            continue
        text = _safe_read_text(p, max_chars=max_chars // max(1, len(paths)))
        if not text.strip():
            continue
        chunks.append(f"[FILE] {p}\n{text}".strip())
    return "\n\n".join(chunks).strip()


def call_openai_chat_completions(
    *,
    config: LLMReviewConfig,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    if not config.model.strip():
        raise ValueError("LLM model is empty")
    if not config.base_url.strip():
        raise ValueError("LLM base_url is empty")

    url = _join_base_url(config.base_url, "/v1/chat/completions")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "ap-observatory-llm-review/0.1",
    }
    if config.api_key.strip():
        headers["Authorization"] = f"Bearer {config.api_key.strip()}"

    body = {
        "model": str(config.model),
        "temperature": float(config.temperature),
        "max_tokens": int(config.max_completion_tokens),
        "messages": [
            {"role": "system", "content": str(system_prompt or "")},
            {"role": "user", "content": str(user_prompt or "")},
        ],
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=int(config.timeout_sec)) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                return {"success": False, "error": "invalid_json_response", "raw": raw}
            return {"success": True, "data": parsed}
    except urllib.error.HTTPError as exc:
        raw = ""
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:
            raw = ""
        return {
            "success": False,
            "error": f"http_error:{exc.code}",
            "message": str(exc),
            "raw": raw,
        }
    except Exception as exc:
        return {"success": False, "error": "request_failed", "message": str(exc)}

def _extract_delta_from_stream_event(payload: dict[str, Any]) -> str:
    """
    Best-effort extractor for OpenAI-compatible streaming events.

    Common shapes:
      - choices[0].delta.content
      - choices[0].message.content (some proxies)
    """
    try:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        c0 = choices[0] if isinstance(choices[0], dict) else {}
        delta = c0.get("delta") if isinstance(c0.get("delta"), dict) else {}
        if isinstance(delta, dict) and str(delta.get("content", "") or ""):
            return str(delta.get("content") or "")
        msg = c0.get("message") if isinstance(c0.get("message"), dict) else {}
        if isinstance(msg, dict) and str(msg.get("content", "") or ""):
            return str(msg.get("content") or "")
    except Exception:
        return ""
    return ""


def call_openai_chat_completions_stream(
    *,
    config: LLMReviewConfig,
    system_prompt: str,
    user_prompt: str,
    on_delta: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    OpenAI-compatible chat.completions with optional SSE streaming.

    Return:
      - success True: {"text": "...", "stream": bool, "data": final_payload_if_any}
      - success False: {"error": "...", "message": "...", "raw": "...", "url": "..."}
    """
    if not config.model.strip():
        raise ValueError("LLM model is empty")
    if not config.base_url.strip():
        raise ValueError("LLM base_url is empty")

    url = _join_base_url(config.base_url, "/v1/chat/completions")
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "ap-observatory-llm-review/0.2",
    }
    if config.api_key.strip():
        headers["Authorization"] = f"Bearer {config.api_key.strip()}"

    body = {
        "model": str(config.model),
        "temperature": float(config.temperature),
        "max_tokens": int(config.max_completion_tokens),
        "stream": True,
        "messages": [
            {"role": "system", "content": str(system_prompt or "")},
            {"role": "user", "content": str(user_prompt or "")},
        ],
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=int(config.timeout_sec)) as resp:
            # Some proxies ignore stream=True and return a normal JSON payload.
            content_type = str(getattr(resp, "headers", {}).get("Content-Type", "") or "").lower()
            is_sse = "text/event-stream" in content_type or "event-stream" in content_type
            if not is_sse:
                raw = resp.read().decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(raw)
                except Exception:
                    return {"success": False, "error": "invalid_json_response", "raw": raw, "url": url}
                text = ""
                if isinstance(parsed, dict):
                    text = _extract_text_from_chat_completions(parsed)
                return {"success": True, "stream": False, "text": str(text or ""), "data": parsed, "url": url}

            chunks: list[str] = []
            while True:
                raw_line = resp.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue
                payload_text = line[len("data:") :].strip()
                if payload_text == "[DONE]":
                    break
                try:
                    payload = json.loads(payload_text)
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                delta = _extract_delta_from_stream_event(payload)
                if not delta:
                    continue
                chunks.append(delta)
                if on_delta is not None:
                    try:
                        on_delta(delta)
                    except Exception:
                        pass

            return {"success": True, "stream": True, "text": "".join(chunks), "data": None, "url": url}
    except urllib.error.HTTPError as exc:
        raw = ""
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:
            raw = ""
        return {
            "success": False,
            "error": f"http_error:{exc.code}",
            "message": str(exc),
            "raw": raw,
            "url": url,
        }
    except Exception as exc:
        return {"success": False, "error": "request_failed", "message": str(exc), "raw": "", "url": url}


def _extract_text_from_chat_completions(payload: dict[str, Any]) -> str:
    # OpenAI chat.completions: choices[0].message.content
    try:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        msg = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(msg, dict):
            return ""
        return str(msg.get("content", "") or "")
    except Exception:
        return ""


def review_run_with_llm(*, run_id: str, config: LLMReviewConfig | None = None) -> dict[str, Any]:
    cfg = config or load_review_config()
    run_dir = storage.resolve_run_dir(run_id)
    if not run_dir.exists():
        return {"success": False, "error": f"run not found: {run_id}"}

    if not cfg.enabled:
        return {"success": False, "error": "llm_review_disabled"}
    if not cfg.model.strip():
        return {"success": False, "error": "llm_model_missing"}
    if not cfg.base_url.strip():
        return {"success": False, "error": "llm_base_url_missing"}

    started_at_ms = int(time.time() * 1000)
    status_path = run_dir / "llm_review.status.json"
    out_path = run_dir / "llm_review.report.md"
    raw_path = run_dir / "llm_review.raw.json"
    err_path = run_dir / "llm_review.error.txt"

    def _write_status(status: str, extra: dict[str, Any] | None = None) -> None:
        payload = {
            "run_id": str(run_id),
            "status": str(status),
            "started_at_ms": int(started_at_ms),
            "updated_at_ms": int(time.time() * 1000),
            "model": str(cfg.model),
            "base_url": str(cfg.base_url),
        }
        if extra:
            payload.update(extra)
        try:
            status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    _write_status("running", {"stage": "building_prompt"})

    # Build prompt. Keep an effective cap below proxy/context limits so the
    # reviewer returns usable text instead of a 0-token completion.
    requested_max_chars = int(max(50_000, cfg.max_prompt_chars))
    max_chars = int(min(requested_max_chars, LLM_REVIEW_EFFECTIVE_PROMPT_CHAR_CAP))
    theory = _read_ap_theory_core_text(max_chars=min(45_000, max(20_000, int(max_chars * 0.14))))
    extra_context = _read_extra_context(max_chars=min(45_000, max(16_000, int(max_chars * 0.14))))
    metrics_budget = max(
        70_000,
        int(max_chars - len(theory) - len(extra_context) - len(_current_ap_design_baseline()) - 55_000),
    )
    (
        manifest_text,
        dataset_text,
        curriculum_summary_text,
        curriculum_summary_note,
        accumulated_summary_text,
        accumulated_summary_note,
        metrics_text,
        metrics_note,
        metrics_path_str,
    ) = _read_run_artifacts(
        run_dir=run_dir, max_prompt_chars=metrics_budget
    )
    expectation_contract_events_text = _read_expectation_contract_events_summary(
        run_dir, max_chars=min(120_000, max(12_000, int(max_chars * 0.10)))
    )

    system_prompt = _build_system_prompt()
    user_prompt = build_review_prompt(
        run_id=run_id,
        config=cfg,
        theory_core_text=theory,
        manifest_text=manifest_text,
        dataset_text=dataset_text,
        curriculum_summary_text=curriculum_summary_text,
        curriculum_summary_note=curriculum_summary_note,
        accumulated_summary_text=accumulated_summary_text,
        accumulated_summary_note=accumulated_summary_note,
        metrics_text=metrics_text,
        metrics_note=metrics_note,
        expectation_contract_events_text=expectation_contract_events_text,
        extra_context=extra_context,
    )
    # Trim final prompt if still too long (safety net).
    prompt_truncated = False
    if len(user_prompt) > max_chars:
        prompt_truncated = True
        marker = (
            "\n\n[TRUNCATED_MIDDLE: prompt exceeds max_prompt_chars; "
            "the beginning and final instructions are preserved.]\n\n"
        )
        head_budget = max(1, int(max_chars * 0.64))
        tail_budget = max(1, max_chars - head_budget - len(marker))
        user_prompt = user_prompt[:head_budget] + marker + user_prompt[-tail_budget:]

    prompt_status_meta = {
        "prompt_chars": int(len(user_prompt)),
        "prompt_truncated": bool(prompt_truncated),
        "requested_max_prompt_chars": int(requested_max_chars),
        "effective_max_prompt_chars": int(max_chars),
        "metrics_prompt_budget": int(metrics_budget),
        "theory_chars": int(len(theory)),
        "extra_context_chars": int(len(extra_context)),
        "manifest_chars": int(len(manifest_text)),
        "dataset_chars": int(len(dataset_text)),
        "curriculum_summary_chars": int(len(curriculum_summary_text)),
        "accumulated_summary_chars": int(len(accumulated_summary_text)),
        "expectation_contract_events_chars": int(len(expectation_contract_events_text)),
        "metrics_chars": int(len(metrics_text)),
        "metrics_path": metrics_path_str,
    }

    _write_status(
        "running",
        {
            "stage": "calling_llm",
            **prompt_status_meta,
            "received_chars": 0,
            "streaming": True,
        },
    )

    # Ensure report path exists early so the UI can show streaming progress.
    try:
        out_path.write_text("", encoding="utf-8")
    except Exception:
        pass

    received_chars = 0
    pending_chunks: list[str] = []
    last_flush_ms = int(time.time() * 1000)

    def _flush_partial(force: bool = False) -> None:
        nonlocal pending_chunks, last_flush_ms
        if not pending_chunks:
            return
        now_ms = int(time.time() * 1000)
        if not force and now_ms - last_flush_ms < 650 and sum(len(x) for x in pending_chunks) < 4096:
            return
        try:
            with out_path.open("a", encoding="utf-8") as fh:
                fh.write("".join(pending_chunks))
        except Exception:
            pass
        pending_chunks = []
        last_flush_ms = now_ms
        _write_status(
            "running",
            {
                "stage": "streaming",
                **prompt_status_meta,
                "received_chars": int(received_chars),
                "updated_at_ms": now_ms,
            },
        )

    def _on_delta(delta: str) -> None:
        nonlocal received_chars, pending_chunks
        if not delta:
            return
        pending_chunks.append(str(delta))
        received_chars += len(delta)
        _flush_partial(force=False)

    res = call_openai_chat_completions_stream(config=cfg, system_prompt=system_prompt, user_prompt=user_prompt, on_delta=_on_delta)
    _flush_partial(force=True)
    stream_empty_fallback_attempted = False
    if not res.get("success", False):
        # Persist raw error for audit.
        raw_err = str(res.get("raw", "") or "")
        try:
            err_path.write_text(raw_err, encoding="utf-8")
        except Exception:
            pass
        # Also surface the error inside the report file so the UI can display it
        # without needing a dedicated "raw error" endpoint.
        try:
            with out_path.open("a", encoding="utf-8") as fh:
                fh.write("\n\n---\n\n")
                fh.write("# LLM Review Failed\n\n")
                fh.write(f"- error: {res.get('error', '')}\n")
                fh.write(f"- message: {res.get('message', '')}\n")
                fh.write(f"- url: {res.get('url', '')}\n\n")
                if raw_err.strip():
                    fh.write("```text\n")
                    fh.write(raw_err[:8000])
                    fh.write("\n```\n")
        except Exception:
            pass
        _write_status(
            "failed",
            {
                "stage": "failed",
                "error": res.get("error", ""),
                "message": res.get("message", ""),
                "url": res.get("url", ""),
                "error_path": str(err_path),
                "error_preview": raw_err[:8000],
                **prompt_status_meta,
                "received_chars": int(received_chars),
                "streaming": True,
                "finished_at_ms": int(time.time() * 1000),
            },
        )
        try:
            raw_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return {"success": False, "error": res.get("error", "failed"), "message": res.get("message", "")}

    text = str(res.get("text", "") or "")
    if not text.strip():
        stream_empty_fallback_attempted = True
        _write_status(
            "running",
            {
                "stage": "retrying_non_stream_after_empty_stream",
                **prompt_status_meta,
                "received_chars": 0,
                "streaming": True,
            },
        )
        fallback_res = call_openai_chat_completions(config=cfg, system_prompt=system_prompt, user_prompt=user_prompt)
        if fallback_res.get("success", False):
            fallback_text = _extract_text_from_chat_completions(fallback_res.get("data", {}) if isinstance(fallback_res.get("data"), dict) else {})
            if fallback_text.strip():
                res = {
                    "success": True,
                    "stream": False,
                    "text": fallback_text,
                    "data": fallback_res.get("data"),
                    "url": _join_base_url(cfg.base_url, "/v1/chat/completions"),
                    "fallback_from_empty_stream": True,
                }
                text = fallback_text
            else:
                res = {
                    "success": True,
                    "stream": False,
                    "text": "",
                    "data": fallback_res.get("data"),
                    "url": _join_base_url(cfg.base_url, "/v1/chat/completions"),
                    "fallback_from_empty_stream": True,
                    "fallback_empty": True,
                }
        else:
            res = {
                "success": True,
                "stream": True,
                "text": "",
                "data": None,
                "url": res.get("url", ""),
                "fallback_from_empty_stream": True,
                "fallback_error": fallback_res,
            }
    finished_at_ms = int(time.time() * 1000)
    if not text.strip():
        empty_reason = "empty_llm_response"
        try:
            raw_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        try:
            err_path.write_text(
                json.dumps(
                    {
                        "error": empty_reason,
                        "message": "LLM endpoint returned success but no review text.",
                        "url": res.get("url", ""),
                        "streaming": bool(res.get("stream", False)),
                        "stream_empty_fallback_attempted": bool(stream_empty_fallback_attempted),
                        "fallback_error": res.get("fallback_error"),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass
        try:
            out_path.write_text(
                "# LLM Review Failed\n\n"
                "- error: empty_llm_response\n"
                "- message: LLM endpoint returned success but no review text.\n"
                f"- url: {res.get('url', '')}\n",
                encoding="utf-8",
            )
        except Exception:
            pass
        _write_status(
            "failed",
            {
                "stage": "failed",
                "error": empty_reason,
                "message": "LLM endpoint returned success but no review text.",
                "url": res.get("url", ""),
                "error_path": str(err_path),
                "report_path": str(out_path),
                "raw_path": str(raw_path),
                **prompt_status_meta,
                "received_chars": 0,
                "streaming": bool(res.get("stream", False)),
                "stream_empty_fallback_attempted": bool(stream_empty_fallback_attempted),
                "finished_at_ms": finished_at_ms,
            },
        )
        return {
            "success": False,
            "error": empty_reason,
            "message": "LLM endpoint returned success but no review text.",
            "run_id": run_id,
            "report_path": str(out_path),
            "raw_path": str(raw_path),
        }
    try:
        # Append any buffered output (if any) and ensure newline at end.
        out_path.write_text(str(text or "").strip() + "\n", encoding="utf-8")
    except Exception:
        pass
    try:
        raw_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    _write_status(
        "completed",
        {
            "stage": "completed",
            "finished_at_ms": finished_at_ms,
            "report_path": str(out_path),
            "raw_path": str(raw_path),
            **prompt_status_meta,
            "received_chars": int(len(text or "")),
            "streaming": bool(res.get("stream", False)),
            "stream_empty_fallback_attempted": bool(stream_empty_fallback_attempted),
            "fallback_from_empty_stream": bool(res.get("fallback_from_empty_stream", False)),
            "url": res.get("url", ""),
        },
    )
    return {
        "success": True,
        "run_id": run_id,
        "status": "completed",
        "report_path": str(out_path),
        "raw_path": str(raw_path),
        "prompt_chars": int(len(user_prompt)),
        "prompt_truncated": bool(prompt_truncated),
        "requested_max_prompt_chars": int(requested_max_chars),
        "effective_max_prompt_chars": int(max_chars),
        "metrics_prompt_budget": int(metrics_budget),
        "stream_empty_fallback_attempted": bool(stream_empty_fallback_attempted),
        "fallback_from_empty_stream": bool(res.get("fallback_from_empty_stream", False)),
        "finished_at_ms": finished_at_ms,
    }


def read_review_status(*, run_id: str) -> dict[str, Any]:
    run_dir = storage.resolve_run_dir(run_id)
    status_path = run_dir / "llm_review.status.json"
    report_path = run_dir / "llm_review.report.md"
    raw_path = run_dir / "llm_review.raw.json"
    err_path = run_dir / "llm_review.error.txt"
    payload: dict[str, Any] = {"run_id": run_id, "status": "not_started"}
    try:
        if status_path.exists():
            raw = json.loads(status_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                payload.update(raw)
            else:
                payload["status"] = "unknown"
    except Exception:
        payload["status"] = "unknown"
    report_exists = report_path.exists()
    raw_exists = raw_path.exists()
    error_exists = err_path.exists()
    payload.setdefault("report_path", str(report_path))
    payload.setdefault("raw_path", str(raw_path))
    if error_exists or not payload.get("error_path"):
        payload["error_path"] = str(err_path) if error_exists else str(payload.get("error_path", "") or "")
    payload["report_exists"] = bool(report_exists)
    payload["raw_exists"] = bool(raw_exists)
    payload["error_exists"] = bool(error_exists)
    payload["report_size_bytes"] = int(report_path.stat().st_size) if report_exists else 0
    payload["raw_size_bytes"] = int(raw_path.stat().st_size) if raw_exists else 0
    payload["error_size_bytes"] = int(err_path.stat().st_size) if error_exists else 0
    payload["report_source_hint"] = (
        "report"
        if report_exists
        else "raw_json"
        if raw_exists
        else "error_text"
        if error_exists
        else "missing"
    )
    return payload


def read_review_report(*, run_id: str, max_chars: int = 800_000) -> dict[str, Any]:
    run_dir = storage.resolve_run_dir(run_id)
    report_path = run_dir / "llm_review.report.md"
    raw_path = run_dir / "llm_review.raw.json"
    err_path = run_dir / "llm_review.error.txt"
    report_exists = report_path.exists()
    raw_exists = raw_path.exists()
    error_exists = err_path.exists()
    if report_exists:
        text = _safe_read_text(report_path, max_chars=max_chars)
        if text.strip():
            return {
                "run_id": run_id,
                "exists": True,
                "text": text,
                "path": str(report_path),
                "source": "report",
                "char_count": len(text),
                "report_file_exists": True,
                "raw_file_exists": bool(raw_exists),
                "error_file_exists": bool(error_exists),
            }
    if raw_exists:
        raw_payload = _safe_read_json(raw_path)
        raw_text = _extract_report_text_from_raw_payload(raw_payload)
        if raw_text.strip():
            text = raw_text[: int(max_chars)] if max_chars and len(raw_text) > int(max_chars) else raw_text
            return {
                "run_id": run_id,
                "exists": True,
                "text": text,
                "path": str(raw_path),
                "source": "raw_json",
                "char_count": len(text),
                "report_file_exists": bool(report_exists),
                "raw_file_exists": True,
                "error_file_exists": bool(error_exists),
            }
    if error_exists:
        text = _safe_read_text(err_path, max_chars=max_chars)
        if text.strip():
            return {
                "run_id": run_id,
                "exists": True,
                "text": text,
                "path": str(err_path),
                "source": "error_text",
                "char_count": len(text),
                "report_file_exists": bool(report_exists),
                "raw_file_exists": bool(raw_exists),
                "error_file_exists": True,
            }
    return {
        "run_id": run_id,
        "exists": bool(report_exists or raw_exists or error_exists),
        "text": "",
        "path": str(report_path),
        "source": "missing",
        "char_count": 0,
        "report_file_exists": bool(report_exists),
        "raw_file_exists": bool(raw_exists),
        "error_file_exists": bool(error_exists),
    }
