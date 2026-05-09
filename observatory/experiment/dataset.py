# -*- coding: utf-8 -*-
"""
Episode Dataset Protocol (YAML) + Expander (-> JSONL)
=====================================================

This module defines a small, strict dataset protocol that is:
- deterministic
- auditable
- easy to version-control

It is shared by:
- CLI tools in `tools/`
- the Observatory web UI experiment panel (future)
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Iterable

from .expectation_contracts import ExpectationContractError, normalize_expectation_contracts_from_labels


class DatasetValidationError(ValueError):
    pass


@dataclass(frozen=True)
class DatasetMeta:
    dataset_id: str
    seed: int
    time_basis: str
    tick_dt_ms: int | None


DATASET_PROTOCOL_DOC: dict[str, Any] = {
    "title": "AP 实验数据集格式标准（本地实验版）",
    "summary": (
        "数据集分为两种格式：YAML 适合编写、审计与版本控制；JSONL 适合长跑任务直接导入。"
        "所有规模统计都以真实有效文本 tick 为准，空 tick 不计入“100 / 1000 / 10000”这类主规模标称。"
    ),
    "core_rules": [
        "YAML 根节点必须是对象，至少包含 dataset_id、seed、time_basis、episodes。",
        "当 time_basis=tick 时，必须显式给出 tick_dt_ms。",
        "如需专项实验开关，可在 YAML 顶层写 app_config_override；它只在本次 run 内临时生效，结束后恢复。",
        "episodes[*].ticks[*] 必须是 text 或 empty=true 二选一，不能同时出现。",
        "JSONL 每一行都代表一个真实 tick，对象至少要能推导出 input_text 或 input_is_empty。",
        "labels 用于教师反馈、评测标签、工具期望等可审计信息，建议使用中文键名或补充中文注释字段。",
        "若 labels 中使用 expectation_contract / expectation_contracts，应使用结构化条件，并把监督结果写成未来反馈 tick。",
        "推荐额外提供 title、description、experiment_goal、evaluation_dimensions、notes，便于面板展示实验目的与评估维度。",
    ],
    "yaml_required_fields": [
        {"field": "dataset_id", "meaning": "数据集唯一标识。", "required": True},
        {"field": "seed", "meaning": "实验随机种子。", "required": True},
        {"field": "time_basis", "meaning": "时间基准：tick 或 wallclock。", "required": True},
        {"field": "tick_dt_ms", "meaning": "每个 tick 的理论时间跨度；仅当 time_basis=tick 时必填。", "required": False},
        {"field": "episodes", "meaning": "实验片段列表。每个片段可以包含 tags、repeat、title、description。", "required": True},
    ],
    "yaml_optional_fields": [
        {"field": "title", "meaning": "中文标题，建议直接描述实验主题。"},
        {"field": "description", "meaning": "数据集说明，介绍语料来源与设计边界。"},
        {"field": "experiment_goal", "meaning": "实验目标，例如“测试长期学习后是否仍有惊讶感”。"},
        {"field": "evaluation_dimensions", "meaning": "评估维度列表，例如“记忆召回准确率、文本可读性、情绪稳定性”。"},
        {"field": "notes", "meaning": "设计备注或人工审计说明。"},
        {"field": "app_config_override", "meaning": "单次运行时临时覆写观测台 app 配置，例如打开某个专项实验开关。"},
    ],
    "jsonl_fields": [
        {"field": "input_text", "meaning": "当前 tick 的文本输入。空字符串表示空 tick。", "required": False},
        {"field": "input_is_empty", "meaning": "是否为空 tick。与 input_text 二选一即可推导。", "required": False},
        {"field": "dataset_id", "meaning": "数据集标识；建议保留，便于追踪。", "required": False},
        {"field": "tick_index", "meaning": "tick 序号；建议提供，但不是硬性要求。", "required": False},
        {"field": "episode_id", "meaning": "所属片段 ID。", "required": False},
        {"field": "tags", "meaning": "标签数组，用于切片分析。", "required": False},
        {"field": "labels", "meaning": "教师奖惩、期望动作、人工评估标签等。", "required": False},
        {"field": "labels.expectation_contracts", "meaning": "带时窗的期望契约列表，用于延迟监督。", "required": False},
        {"field": "note", "meaning": "该行的中文解释。", "required": False},
    ],
    "yaml_example": """dataset_id: emotion_probe_100_v1
title: 情绪与惊讶感探针（100 条真实文本）
description: >
  用于观察系统在连续情绪相关语料中，惊讶感、违和感、奖惩与递质是否逐步稳定。
experiment_goal: 验证长期学习后，意外事件是否仍能触发显著惊讶与解释更新
evaluation_dimensions:
  - 惊讶感峰值是否逐步降低但不消失
  - 违和感是否会在相似事件中重复爆炸
  - 文本可读性是否持续保持
notes:
  - 规模统计只按真实文本 tick 计数
  - 空 tick 只允许用于专门的时间/遗忘实验
app_config_override:
  stimulus_residual_memory_promotion_enabled: true
seed: 20260419
time_basis: tick
tick_dt_ms: 100
episodes:
  - id: ep_emotion_warmup
    title: 情绪热身
    tags: [情绪, 热身]
    ticks:
      - text: 研究员听到实验通过，先高兴，随后担心是不是偶然成功。
      - text: 学生看到老师点头，先安心，随后又怀疑自己有没有漏掉条件。
  - id: ep_emotion_gap
    title: 时间间隔对照
    tags: [情绪, 空档]
    ticks:
      - empty: true
      - text: 第二天再看同一结果时，他依然感到惊讶，但比昨天平稳一些。
""",
    "jsonl_example": """{"dataset_id":"demo_jsonl_v1","tick_index":0,"input_text":"请先打个招呼，再说明你现在的判断依据。","tags":["问候","解释"]}
{"dataset_id":"demo_jsonl_v1","tick_index":1,"input_text":"","input_is_empty":true,"tags":["空档"]}
{"dataset_id":"demo_jsonl_v1","tick_index":2,"input_text":"如果上一条记忆是错的，你会怎样修正当前结论？","labels":{"teacher":{"pun":0.2}}}""",
}


def _as_str(v: Any) -> str:
    return str(v) if v is not None else ""


def _as_int(v: Any, *, where: str) -> int:
    try:
        return int(v)
    except Exception as exc:
        raise DatasetValidationError(f"{where} must be int, got: {v!r}") from exc


def _ensure_list(v: Any, *, where: str) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    raise DatasetValidationError(f"{where} must be a list, got: {type(v).__name__}")


def _normalize_labels(v: Any, *, where: str) -> dict[str, Any]:
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise DatasetValidationError(f"{where} must be a mapping (dict).")
    out = dict(v)
    try:
        contracts = normalize_expectation_contracts_from_labels(out, where=where)
    except ExpectationContractError as exc:
        raise DatasetValidationError(str(exc)) from exc
    if contracts:
        out["expectation_contracts"] = contracts
        out.pop("expectation_contract", None)
    return out


def _normalize_override_mapping(v: Any, *, where: str) -> dict[str, Any]:
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise DatasetValidationError(f"{where} must be a mapping (dict).")
    return copy.deepcopy(v)


def validate_meta(raw: dict[str, Any]) -> DatasetMeta:
    dataset_id = _as_str(raw.get("dataset_id", "")).strip()
    if not dataset_id:
        raise DatasetValidationError("dataset_id is required.")

    seed = _as_int(raw.get("seed", 0), where="seed")
    time_basis = _as_str(raw.get("time_basis", "")).strip().lower()
    if time_basis not in {"tick", "wallclock"}:
        raise DatasetValidationError("time_basis must be 'tick' or 'wallclock'.")

    tick_dt_ms: int | None = None
    if time_basis == "tick":
        if raw.get("tick_dt_ms", None) is None:
            raise DatasetValidationError("tick_dt_ms is required when time_basis=tick.")
        tick_dt_ms = _as_int(raw.get("tick_dt_ms"), where="tick_dt_ms")
        if tick_dt_ms <= 0:
            raise DatasetValidationError("tick_dt_ms must be > 0.")

    return DatasetMeta(dataset_id=dataset_id, seed=seed, time_basis=time_basis, tick_dt_ms=tick_dt_ms)


def normalize_tick(tick: Any, *, where: str) -> dict[str, Any]:
    # Allow a shortcut: `- \"hello\"` means `{\"text\": \"hello\"}`
    if isinstance(tick, str):
        return {"text": tick}
    if not isinstance(tick, dict):
        raise DatasetValidationError(f"{where} must be a mapping (dict) or string, got: {type(tick).__name__}")

    has_text = "text" in tick
    has_empty = bool(tick.get("empty", False))
    if has_text and has_empty:
        raise DatasetValidationError(f"{where} has both text and empty=true. Choose one.")
    if not has_text and not has_empty:
        raise DatasetValidationError(f"{where} must have 'text' or 'empty: true'.")

    out = dict(tick)
    # Optional per-tick repeat (for compact datasets, especially long empty gaps).
    # 说明：episode.repeat 是“整段 ticks 模板”重复；tick.repeat 是“单个 tick”重复。
    if "repeat" in out:
        rep = _as_int(out.get("repeat", 1), where=f"{where}.repeat")
        if rep <= 0:
            raise DatasetValidationError(f"{where}.repeat must be >= 1.")
        out["repeat"] = rep
    if has_empty:
        out["text"] = ""
        out["empty"] = True
    else:
        out["text"] = _as_str(out.get("text", ""))
        out.pop("empty", None)
    if "labels" in out:
        out["labels"] = _normalize_labels(out.get("labels"), where=f"{where}.labels")
    return out


def normalize_episode(ep: Any, *, index: int) -> dict[str, Any]:
    where = f"episodes[{index}]"
    if not isinstance(ep, dict):
        raise DatasetValidationError(f"{where} must be a mapping (dict).")

    ep_id = _as_str(ep.get("id", "")).strip()
    if not ep_id:
        raise DatasetValidationError(f"{where}.id is required.")

    repeat = int(ep.get("repeat", 1) or 1)
    if repeat <= 0:
        raise DatasetValidationError(f"{where}.repeat must be >= 1.")

    tags_raw = ep.get("tags", [])
    tags = []
    if tags_raw is not None:
        if not isinstance(tags_raw, list):
            raise DatasetValidationError(f"{where}.tags must be a list.")
        tags = [str(x) for x in tags_raw if str(x).strip()]

    ticks_raw = ep.get("ticks", None)
    if ticks_raw is None:
        raise DatasetValidationError(f"{where}.ticks is required.")
    ticks_list = _ensure_list(ticks_raw, where=f"{where}.ticks")
    if not ticks_list:
        raise DatasetValidationError(f"{where}.ticks must not be empty.")

    ticks_norm: list[dict[str, Any]] = []
    for j, t in enumerate(ticks_list):
        ticks_norm.append(normalize_tick(t, where=f"{where}.ticks[{j}]"))

    out = dict(ep)
    out["id"] = ep_id
    out["repeat"] = repeat
    out["tags"] = tags
    out["ticks"] = ticks_norm
    return out


def validate_and_normalize_dataset(raw: dict[str, Any]) -> dict[str, Any]:
    meta = validate_meta(raw)
    episodes_raw = raw.get("episodes", None)
    if episodes_raw is None:
        raise DatasetValidationError("episodes is required.")
    episodes_list = _ensure_list(episodes_raw, where="episodes")
    if not episodes_list:
        raise DatasetValidationError("episodes must not be empty.")

    episodes_norm: list[dict[str, Any]] = []
    for i, ep in enumerate(episodes_list):
        episodes_norm.append(normalize_episode(ep, index=i))

    legacy_runtime_override = _normalize_override_mapping(
        raw.get("runtime_config_override", None),
        where="runtime_config_override",
    )
    app_config_override = _normalize_override_mapping(
        raw.get("app_config_override", None),
        where="app_config_override",
    )
    merged_app_config_override = dict(legacy_runtime_override)
    merged_app_config_override.update(app_config_override)

    out = dict(raw)
    out["_meta"] = {
        "dataset_id": meta.dataset_id,
        "seed": meta.seed,
        "time_basis": meta.time_basis,
        "tick_dt_ms": meta.tick_dt_ms,
    }
    out["dataset_id"] = meta.dataset_id
    out["seed"] = meta.seed
    out["time_basis"] = meta.time_basis
    if meta.time_basis == "tick":
        out["tick_dt_ms"] = meta.tick_dt_ms
    out["episodes"] = episodes_norm
    out.pop("runtime_config_override", None)
    if merged_app_config_override:
        out["app_config_override"] = merged_app_config_override
    else:
        out.pop("app_config_override", None)
    return out


def estimate_total_ticks(dataset: dict[str, Any]) -> int:
    episodes = dataset.get("episodes", [])
    total = 0
    if not isinstance(episodes, list):
        return 0
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        repeat = int(ep.get("repeat", 1) or 1)
        ticks = ep.get("ticks", [])
        if not isinstance(ticks, list):
            continue
        per_ep = 0
        for t in ticks:
            if isinstance(t, dict):
                try:
                    per_ep += max(1, int(t.get("repeat", 1) or 1))
                except Exception:
                    per_ep += 1
            else:
                per_ep += 1
        total += max(0, repeat) * int(per_ep)
    return int(total)


def summarize_tick_counts(dataset: dict[str, Any]) -> dict[str, int]:
    episodes = dataset.get("episodes", [])
    summary = {
        "total_ticks": 0,
        "effective_text_ticks": 0,
        "empty_ticks": 0,
        "labeled_ticks": 0,
    }
    if not isinstance(episodes, list):
        return summary
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        repeat = max(0, int(ep.get("repeat", 1) or 1))
        ticks = ep.get("ticks", [])
        if not isinstance(ticks, list):
            continue
        for t in ticks:
            if not isinstance(t, dict):
                tick_repeat = 1
                text = str(t or "")
                is_empty = not bool(text)
                has_labels = False
            else:
                try:
                    tick_repeat = max(1, int(t.get("repeat", 1) or 1))
                except Exception:
                    tick_repeat = 1
                text = str(t.get("text", "") or "")
                is_empty = bool(t.get("empty", False)) or not bool(text)
                has_labels = isinstance(t.get("labels"), dict) and bool(t.get("labels"))
            amount = repeat * tick_repeat
            summary["total_ticks"] += amount
            if is_empty:
                summary["empty_ticks"] += amount
            else:
                summary["effective_text_ticks"] += amount
            if has_labels:
                summary["labeled_ticks"] += amount
    return summary


def dataset_overview(dataset: dict[str, Any]) -> dict[str, Any]:
    counts = summarize_tick_counts(dataset)
    dims_raw = dataset.get("evaluation_dimensions", [])
    notes_raw = dataset.get("notes", [])
    evaluation_dimensions = [str(x).strip() for x in dims_raw if str(x).strip()] if isinstance(dims_raw, list) else []
    notes = [str(x).strip() for x in notes_raw if str(x).strip()] if isinstance(notes_raw, list) else []
    app_config_override = (
        copy.deepcopy(dataset.get("app_config_override", {}))
        if isinstance(dataset.get("app_config_override"), dict)
        else {}
    )
    app_config_override_keys = sorted(str(key).strip() for key in app_config_override.keys() if str(key).strip())
    return {
        "dataset_id": str(dataset.get("dataset_id", "") or ""),
        "title": str(dataset.get("title", "") or ""),
        "description": str(dataset.get("description", "") or ""),
        "experiment_goal": str(dataset.get("experiment_goal", "") or ""),
        "time_basis": str(dataset.get("time_basis", "") or ""),
        "tick_dt_ms": dataset.get("tick_dt_ms", None),
        "estimated_ticks": estimate_total_ticks(dataset),
        "effective_text_ticks": counts.get("effective_text_ticks", 0),
        "empty_ticks": counts.get("empty_ticks", 0),
        "labeled_ticks": counts.get("labeled_ticks", 0),
        "evaluation_dimensions": evaluation_dimensions,
        "notes": notes,
        "app_config_override": app_config_override,
        "app_config_override_keys": app_config_override_keys,
    }


def summarize_expanded_tick_items(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "total_ticks": 0,
        "effective_text_ticks": 0,
        "empty_ticks": 0,
        "labeled_ticks": 0,
        "dataset_id": "",
        "time_basis": "",
        "tick_dt_ms": None,
    }
    dataset_ids: set[str] = set()
    time_bases: set[str] = set()
    tick_dts: set[int] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        summary["total_ticks"] += 1
        text = str(item.get("input_text", "") or "")
        is_empty = bool(item.get("input_is_empty", False)) or not text
        if is_empty:
            summary["empty_ticks"] += 1
        else:
            summary["effective_text_ticks"] += 1
        if isinstance(item.get("labels"), dict) and bool(item.get("labels")):
            summary["labeled_ticks"] += 1
        did = str(item.get("dataset_id", "") or "").strip()
        if did:
            dataset_ids.add(did)
        tb = str(item.get("time_basis", "") or "").strip().lower()
        if tb:
            time_bases.add(tb)
        try:
            tick_dt = item.get("tick_dt_ms", None)
            if tick_dt is not None:
                tick_dts.add(int(tick_dt))
        except Exception:
            pass
    if len(dataset_ids) == 1:
        summary["dataset_id"] = next(iter(dataset_ids))
    if len(time_bases) == 1:
        summary["time_basis"] = next(iter(time_bases))
    if len(tick_dts) == 1:
        summary["tick_dt_ms"] = next(iter(tick_dts))
    return summary


def validate_and_summarize_jsonl_text(text: str, *, preview_limit: int = 24) -> dict[str, Any]:
    lines = str(text or "").splitlines()
    preview_ticks: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    for line_no, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except Exception as exc:
            raise DatasetValidationError(f"JSONL 第 {line_no} 行不是合法 JSON 对象。") from exc
        if not isinstance(obj, dict):
            raise DatasetValidationError(f"JSONL 第 {line_no} 行必须是对象（dict）。")
        item = dict(obj)
        if "input_text" not in item and "text" in item:
            item["input_text"] = item.get("text", "")
        if "input_is_empty" not in item and "empty" in item:
            item["input_is_empty"] = bool(item.get("empty", False))

        has_text = "input_text" in item
        has_empty_flag = "input_is_empty" in item
        text_value = str(item.get("input_text", "") or "")
        is_empty = bool(item.get("input_is_empty", False)) or not text_value
        if not has_text and not has_empty_flag:
            raise DatasetValidationError(f"JSONL 第 {line_no} 行至少需要 input_text 或 input_is_empty。")
        if bool(item.get("input_is_empty", False)) and text_value:
            raise DatasetValidationError(f"JSONL 第 {line_no} 行同时给出了非空 input_text 与 input_is_empty=true，语义冲突。")

        item["input_text"] = "" if is_empty else text_value
        item["input_is_empty"] = bool(is_empty)
        if "tags" in item and item.get("tags") is not None and not isinstance(item.get("tags"), list):
            raise DatasetValidationError(f"JSONL 第 {line_no} 行的 tags 必须是数组。")
        if "labels" in item and item.get("labels") is not None and not isinstance(item.get("labels"), dict):
            raise DatasetValidationError(f"JSONL 第 {line_no} 行的 labels 必须是对象。")
        if "labels" in item:
            item["labels"] = _normalize_labels(item.get("labels"), where=f"JSONL[{line_no}].labels")
        normalized.append(item)
        if len(preview_ticks) < max(1, int(preview_limit)):
            preview_ticks.append(item)

    if not normalized:
        raise DatasetValidationError("JSONL 内容不能为空，至少需要一条真实 tick。")

    summary = summarize_expanded_tick_items(normalized)
    summary["preview_ticks"] = preview_ticks
    return summary


def dataset_protocol_doc() -> dict[str, Any]:
    return dict(DATASET_PROTOCOL_DOC)


def expand_dataset(dataset: dict[str, Any]) -> Iterable[dict[str, Any]]:
    meta = dataset.get("_meta", {})
    dataset_id = str(meta.get("dataset_id", "") or dataset.get("dataset_id", ""))
    seed = int(meta.get("seed", 0) or dataset.get("seed", 0) or 0)
    time_basis = str(meta.get("time_basis", "") or dataset.get("time_basis", "")).strip().lower()
    tick_dt_ms = meta.get("tick_dt_ms", dataset.get("tick_dt_ms", None))
    tick_dt_ms = int(tick_dt_ms) if tick_dt_ms is not None else None

    episodes = dataset.get("episodes", [])
    tick_index = 0
    for ep in episodes:
        ep_id = str(ep.get("id", ""))
        repeat = int(ep.get("repeat", 1) or 1)
        tags = ep.get("tags", [])
        ticks = ep.get("ticks", [])
        for rep_i in range(repeat):
            for j, t in enumerate(ticks):
                tick_repeat = 1
                try:
                    tick_repeat = max(1, int(t.get("repeat", 1) or 1))
                except Exception:
                    tick_repeat = 1

                for rep_j in range(tick_repeat):
                    text = str(t.get("text", "") or "")
                    is_empty = bool(t.get("empty", False)) or (text == "")
                    tick_tags = [str(tag).strip() for tag in t.get("tags", []) if str(tag).strip()] if isinstance(t.get("tags"), list) else []
                    merged_tags = list(dict.fromkeys([*(list(tags) if isinstance(tags, list) else []), *tick_tags]))
                    item: dict[str, Any] = {
                        "dataset_id": dataset_id,
                        "seed": seed,
                        "time_basis": time_basis,
                        "tick_dt_ms": tick_dt_ms,
                        "tick_index": tick_index,
                        "episode_id": ep_id,
                        "episode_repeat_index": rep_i,
                        "tick_in_episode_index": j,
                        "tick_repeat_index": rep_j,
                        "tags": merged_tags,
                        "input_text": "" if is_empty else text,
                        "input_is_empty": is_empty,
                    }
                    # Optional labels pass-through (future use).
                    labels = t.get("labels")
                    if isinstance(labels, dict) and labels:
                        item["labels"] = labels
                    note = str(t.get("note", "") or "").strip()
                    if note:
                        item["note"] = note

                    yield item
                    tick_index += 1

