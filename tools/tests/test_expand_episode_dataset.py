# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from pathlib import Path

import pytest

from observatory.experiment.dataset import dataset_overview, validate_and_summarize_jsonl_text
from tools.expand_episode_dataset import DatasetValidationError, validate_and_normalize_dataset, expand_dataset
from tools.generate_builtin_datasets import build_companion_chat_dataset


def _summarize_effective_ticks(items: list[dict]) -> dict:
    total = len(items)
    effective = sum(1 for it in items if not bool(it.get("input_is_empty", False)) and str(it.get("input_text", "") or "").strip())
    empty = total - effective
    labeled = sum(1 for it in items if isinstance(it.get("labels"), dict) and bool(it.get("labels")))
    return {"total_ticks": total, "effective_text_ticks": effective, "empty_ticks": empty, "labeled_ticks": labeled}


def test_validate_rejects_missing_dataset_id():
    with pytest.raises(DatasetValidationError):
        validate_and_normalize_dataset({"seed": 1, "time_basis": "tick", "tick_dt_ms": 100, "episodes": []})


def test_expand_produces_stable_tick_indices_and_empty_text():
    raw = {
        "dataset_id": "unit_test_ds",
        "seed": 123,
        "time_basis": "tick",
        "tick_dt_ms": 50,
        "episodes": [
            {"id": "ep1", "repeat": 2, "ticks": [{"text": "A"}, {"empty": True}]},
            {"id": "ep2", "ticks": ["B"]},
        ],
    }
    ds = validate_and_normalize_dataset(raw)
    items = list(expand_dataset(ds))

    assert [it["tick_index"] for it in items] == list(range(len(items)))
    assert items[1]["input_is_empty"] is True
    assert items[1]["input_text"] == ""
    assert items[-1]["episode_id"] == "ep2"


def test_expand_passes_through_tick_tags_and_note():
    raw = {
        "dataset_id": "unit_test_tick_meta",
        "seed": 456,
        "time_basis": "tick",
        "tick_dt_ms": 3000,
        "episodes": [
            {
                "id": "ep_meta",
                "tags": ["episode_tag"],
                "ticks": [
                    {
                        "text": "【用户消息】测试标签透传。",
                        "tags": ["user", "message"],
                        "note": "这一条用于验证 tick 级标签与说明透传。",
                        "labels": {"stream": {"role": "user"}},
                    }
                ],
            }
        ],
    }
    ds = validate_and_normalize_dataset(raw)
    items = list(expand_dataset(ds))
    assert len(items) == 1
    assert items[0]["tags"] == ["episode_tag", "user", "message"]
    assert items[0]["note"] == "这一条用于验证 tick 级标签与说明透传。"
    assert items[0]["labels"]["stream"]["role"] == "user"


def test_if_action_stub_50_yaml_expands_to_300_ticks(tmp_path: Path):
    yaml_path = Path("datasets/companion_bot_chat_if_action_stub_50_v0.yaml").resolve()
    assert yaml_path.exists()

    import yaml  # type: ignore

    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    ds = validate_and_normalize_dataset(raw)
    items = list(expand_dataset(ds))
    assert len(items) == 300
    summary = _summarize_effective_ticks(items)
    assert summary["effective_text_ticks"] == 50
    assert summary["empty_ticks"] == 250

    # Ensure the JSON we will write later is valid and contains required keys.
    sample = items[0]
    for k in ("dataset_id", "seed", "time_basis", "tick_index", "episode_id", "input_text", "input_is_empty"):
        assert k in sample
    json.dumps(sample, ensure_ascii=False)


def test_companion_chat_small_yaml_has_bootstrap_if_training_ticks(tmp_path: Path):
    yaml_path = Path("datasets/companion_bot_chat_small_v0.yaml").resolve()
    assert yaml_path.exists()

    import yaml  # type: ignore

    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    ds = validate_and_normalize_dataset(raw)
    items = list(expand_dataset(ds))
    summary = _summarize_effective_ticks(items)
    assert summary["effective_text_ticks"] == 243


def test_companion_chat_builder_has_idle_ticks_and_labels():
    raw = build_companion_chat_dataset(dataset_id="companion_bot_chat_test_v0", day_count=1)
    ds = validate_and_normalize_dataset(raw)
    items = list(expand_dataset(ds))
    summary = _summarize_effective_ticks(items)
    assert ds["tick_dt_ms"] == 3000
    assert summary["effective_text_ticks"] == 243
    assert summary["empty_ticks"] == 24 * 1200 - 240 + 4
    roles = {item.get("labels", {}).get("stream", {}).get("role", "") for item in items if isinstance(item.get("labels"), dict)}
    assert {"user", "assistant", "system", "api", "ops", "idle"} <= roles


def test_dataset_overview_exposes_counts_and_goal():
    raw = {
        "dataset_id": "overview_demo",
        "title": "概览测试",
        "description": "用于验证数据集概览字段。",
        "experiment_goal": "验证页面能读取描述信息。",
        "evaluation_dimensions": ["记忆召回", "文本可读性"],
        "notes": ["只统计真实文本 tick"],
        "seed": 7,
        "time_basis": "tick",
        "tick_dt_ms": 100,
        "episodes": [
            {"id": "ep1", "ticks": [{"text": "A"}, {"empty": True}]},
        ],
    }
    ds = validate_and_normalize_dataset(raw)
    overview = dataset_overview(ds)
    assert overview["dataset_id"] == "overview_demo"
    assert overview["effective_text_ticks"] == 1
    assert overview["empty_ticks"] == 1
    assert overview["experiment_goal"] == "验证页面能读取描述信息。"
    assert overview["evaluation_dimensions"] == ["记忆召回", "文本可读性"]


def test_validate_and_summarize_jsonl_text_uses_effective_text_ticks():
    text = "\n".join(
        [
            json.dumps({"dataset_id": "jsonl_demo", "tick_index": 0, "input_text": "第一条"}, ensure_ascii=False),
            json.dumps({"dataset_id": "jsonl_demo", "tick_index": 1, "input_text": "", "input_is_empty": True}, ensure_ascii=False),
            json.dumps({"dataset_id": "jsonl_demo", "tick_index": 2, "input_text": "第三条", "labels": {"teacher": {"rwd": 0.2}}}, ensure_ascii=False),
        ]
    )
    summary = validate_and_summarize_jsonl_text(text)
    assert summary["dataset_id"] == "jsonl_demo"
    assert summary["total_ticks"] == 3
    assert summary["effective_text_ticks"] == 2
    assert summary["empty_ticks"] == 1
    assert summary["labeled_ticks"] == 1


def test_validate_and_summarize_jsonl_text_rejects_conflicting_empty_flag():
    bad = json.dumps({"input_text": "不应该同时存在", "input_is_empty": True}, ensure_ascii=False)
    with pytest.raises(DatasetValidationError):
        validate_and_summarize_jsonl_text(bad)

