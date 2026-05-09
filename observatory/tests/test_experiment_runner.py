# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

from observatory.experiment.runner import (
    EXPERIMENT_DEFAULT_APP_OVERRIDES,
    RunOptions,
    apply_experiment_default_app_overrides,
    _compact_latest_metrics_preview,
    _resolve_time_sensor_runtime_overrides,
    run_dataset,
)
from observatory.experiment.storage import DatasetFileRef, imported_datasets_dir, resolve_run_dir


def test_resolve_time_sensor_runtime_overrides_uses_dataset_defaults_when_options_empty():
    normalized_doc = {
        "dataset_id": "demo_tick_dataset",
        "time_basis": "tick",
        "tick_dt_ms": 3000,
    }

    basis, tick_interval_sec = _resolve_time_sensor_runtime_overrides(
        normalized_doc=normalized_doc,
        options=RunOptions(),
    )

    assert basis == "tick"
    assert tick_interval_sec == 3.0


def test_resolve_time_sensor_runtime_overrides_preserves_explicit_options():
    normalized_doc = {
        "dataset_id": "demo_tick_dataset",
        "time_basis": "tick",
        "tick_dt_ms": 3000,
    }

    basis, tick_interval_sec = _resolve_time_sensor_runtime_overrides(
        normalized_doc=normalized_doc,
        options=RunOptions(time_sensor_time_basis="wallclock", tick_interval_sec=9.5),
    )

    assert basis == "wallclock"
    assert tick_interval_sec == 9.5


class _NoopSensor:
    def clear_echo_pool(self, trace_id: str):
        return {"success": True, "trace_id": trace_id}


class _NoopPool:
    def clear_state_pool(self, trace_id: str, reason: str, operator: str):
        return {"success": True, "trace_id": trace_id, "reason": reason, "operator": operator}


class _NoopHDB:
    def clear_hdb(self, trace_id: str, reason: str, operator: str):
        return {"success": True, "trace_id": trace_id, "reason": reason, "operator": operator}


class _FakeExperimentApp:
    def __init__(self):
        self._config = {}
        self.time_sensor = SimpleNamespace(_config={})
        self.sensor = _NoopSensor()
        self.pool = _NoopPool()
        self.hdb = _NoopHDB()
        self._last_report = None
        self._report_history = []
        self.tick_counter = 0

    def run_cycle(self, text=None, labels=None):
        self.tick_counter += 1
        input_text = str(text or "")
        labels = labels if isinstance(labels, dict) else {}
        executed_actions = []
        if "触发回忆" in input_text:
            executed_actions.append({"action_kind": "recall", "success": True})
        if "QUERY_WEATHER_OK" in input_text:
            executed_actions.append({"action_kind": "weather_stub", "success": True})
        teacher_rwd = float(labels.get("teacher_rwd", 0.0) or 0.0)
        teacher_pun = float(labels.get("teacher_pun", 0.0) or 0.0)
        report = {
            "trace_id": f"trace_{self.tick_counter}",
            "tick_id": f"tick_{self.tick_counter}",
            "tick_counter": self.tick_counter,
            "started_at": self.tick_counter,
            "finished_at": self.tick_counter + 1,
            "sensor": {"input_text": input_text},
            "final_state": {
                "state_snapshot": {
                    "summary": {"active_item_count": 1},
                    "top_items": [
                        {
                            "item_id": "spi_anchor",
                            "ref_object_id": "st_anchor",
                            "ref_object_type": "st",
                            "display": "anchor",
                        }
                    ],
                },
                "state_energy_summary": {},
                "hdb_snapshot": {"summary": {}},
            },
            "attention": {
                "top_items": [
                    {
                        "item_id": "spi_anchor",
                        "ref_object_id": "st_anchor",
                        "ref_object_type": "st",
                        "display": "anchor",
                    }
                ]
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
            "emotion": {"nt_state_after": {}, "rwd_pun_snapshot": {"rwd": teacher_rwd, "pun": teacher_pun}},
            "action": {"executed_actions": executed_actions, "nodes": []},
            "teacher_feedback": {
                "teacher_rwd": teacher_rwd,
                "teacher_pun": teacher_pun,
                "applied_count": 1 if (teacher_rwd > 0.0 or teacher_pun > 0.0) else 0,
                "mode": "bind_attribute",
                "anchor": str(labels.get("teacher_anchor", "") or ""),
            },
            "timing": {"steps_ms": {}, "total_logic_ms": 0.0},
            "time_sensor": {},
        }
        self._last_report = report
        self._report_history.append(report)
        return report


class _ChunkingFakeExperimentApp(_FakeExperimentApp):
    def __init__(self):
        super().__init__()
        self._config = {
            "input_chunking_enabled": True,
            "enable_goal_b_char_sa_string_mode": False,
            "induction_projection_mode": "residual",
            "enable_cognitive_stitching": True,
            "cognitive_stitching_stage": "post_induction",
        }
        self._pending_external_text_chunks: list[str] = []
        self.runtime_override_snapshots: list[dict] = []

    def _apply_runtime_overrides(self):
        self.runtime_override_snapshots.append(dict(self._config))

    def _split_for_ticks(self, text: str) -> list[str]:
        if not bool(self._config.get("input_chunking_enabled", True)):
            return [text] if text else []
        if len(text) <= 6:
            return [text] if text else []
        return [text[:6], text[6:]]

    def run_cycle(self, text=None, labels=None):
        submitted_text = str(text or "") if text is not None else ""
        pending_before_enqueue = len(self._pending_external_text_chunks)
        queued = []
        if submitted_text:
            queued = self._split_for_ticks(submitted_text)
            self._pending_external_text_chunks.extend(queued)
        pending_before_dequeue = len(self._pending_external_text_chunks)
        tick_text = self._pending_external_text_chunks.pop(0) if self._pending_external_text_chunks else ""
        report = super().run_cycle(text=tick_text, labels=labels)
        report["input_queue"] = {
            "submitted_text": submitted_text,
            "source_text": submitted_text,
            "tick_text": tick_text,
            "queued_from_new_input_count": len(queued),
            "pending_count_before_enqueue": pending_before_enqueue,
            "pending_count_before_dequeue": pending_before_dequeue,
            "pending_count_after_dequeue": len(self._pending_external_text_chunks),
        }
        return report


def _write_imported_dataset(name: str, text: str) -> DatasetFileRef:
    base = imported_datasets_dir()
    base.mkdir(parents=True, exist_ok=True)
    path = base / name
    path.write_text(text, encoding="utf-8")
    return DatasetFileRef(source="imported", rel_path=path.name)


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _assert_growth_cs_off_baseline(manifest: dict, metrics_rows: list[dict]) -> None:
    runtime_override = dict(manifest.get("dataset_runtime_override", {}) or {})
    effective = dict(runtime_override.get("effective_app_baseline", {}) or {})
    assert runtime_override.get("baseline_conforms_to_growth_cs_off") is True
    assert effective.get("induction_projection_mode") == "growth"
    assert effective.get("enable_cognitive_stitching") is False
    assert effective.get("cognitive_stitching_stage") == "disabled"
    assert all(int(row.get("induction_projection_mode_growth", 0) or 0) == 1 for row in metrics_rows)
    assert sum(int(row.get("cs_enabled", 0) or 0) for row in metrics_rows) == 0
    assert sum(int(row.get("cs_concat_count", 0) or 0) for row in metrics_rows) == 0
    assert any(int(row.get("induction_growth_target_count", 0) or 0) > 0 for row in metrics_rows)
    assert any(int(row.get("pool_er_structure_top5_count", 0) or 0) > 0 for row in metrics_rows)
    assert any(int(row.get("pool_ev_structure_top5_count", 0) or 0) > 0 for row in metrics_rows)


def test_compact_latest_metrics_preview_keeps_live_structure_top_payload():
    metrics = {
        "tick_index": 27,
        "trace_id": "cycle_0027",
        "input_is_empty": False,
        "input_text_preview": "明白，继续。",
        "pool_active_item_count": 12,
        "hdb_structure_count": 34,
        "pool_er_top5": [{"rank": 1, "display": "{明 白}", "er": 2.0}],
        "pool_er_structure_top5": [{"rank": 1, "display": "{明 白 继续}", "er": 2.5}],
        "pool_ev_structure_top5": [{"rank": 1, "display": "{天气 建议}", "ev": 1.2}],
        "pool_cp_structure_top5": [{"rank": 1, "display": "{天气 建议}", "cp": 1.1}],
        "attention_top5": [{"rank": 1, "display": "{明 白 继续}", "attention_priority": 0.7}],
    }

    preview = _compact_latest_metrics_preview(metrics)

    assert preview["preview_source"] == "experiment_runner_memory"
    assert preview["tick_index"] == 27
    assert preview["pool_er_structure_top5"][0]["display"] == "{明 白 继续}"
    assert preview["pool_ev_structure_top5"][0]["display"] == "{天气 建议}"
    assert preview["attention_top5"][0]["attention_priority"] == 0.7


def _build_real_experiment_app(*, hdb_dir: Path, extra_config: dict | None = None):
    from observatory._app import ObservatoryApp

    config_override = {
        "enable_goal_b_char_sa_string_mode": True,
        "enable_structure_level_retrieval_storage": True,
        "sensor_enable_stimulus_intensity_attribute_sa": True,
        "sensor_stimulus_intensity_attribute_min_er": 0.0,
        "sensor_attribute_er_ratio": 0.25,
        "sensor_attribute_ev_ratio": 0.0,
        "hdb_enable_background_repair": False,
        "hdb_data_dir": str(hdb_dir),
        "export_json": False,
        "export_html": False,
    }
    if isinstance(extra_config, dict):
        config_override.update(extra_config)
    return ObservatoryApp(config_override=config_override)



def test_expectation_contract_metric_eq_treats_missing_action_count_as_zero():
    from observatory.experiment.expectation_contracts import _evaluate_condition_item

    matched, detail = _evaluate_condition_item(
        {"kind": "metric_eq", "metric": "action_executed_weather_stub", "value": 0},
        report={},
        metrics={},
    )

    assert matched is True
    assert detail["current"] == 0
    assert detail["target"] == 0


def test_run_dataset_honors_dataset_chunking_override_and_applies_mainline_runtime():
    dataset_name = f"contract_chunk_alignment_{uuid.uuid4().hex}.yaml"
    run_id = f"test_contract_chunk_alignment_{uuid.uuid4().hex}"
    ref = _write_imported_dataset(
        dataset_name,
        """dataset_id: contract_chunk_alignment_demo
seed: 1
time_basis: tick
tick_dt_ms: 100
app_config_override:
  input_chunking_enabled: false
episodes:
  - id: ep_contract_chunk_alignment
    ticks:
      - text: REGISTER_CONTRACT
        labels:
          expectation_contract:
            id: weather_contract
            within_ticks: 1
            success_conditions:
              kind: action_executed_kind_min
              action_kind: weather_stub
              min_count: 1
            on_success:
              teacher_rwd: 0.3
              feedback_text: LONG-FEEDBACK-SENTENCE
      - text: QUERY_WEATHER_OK
      - text: NEXT_PROBE
""",
    )
    app = _ChunkingFakeExperimentApp()

    try:
        result = run_dataset(app=app, dataset_ref=ref, options=RunOptions(), run_id=run_id)
        assert result["success"] is True
        manifest = result["manifest"]
        assert manifest["dataset_runtime_override"]["experiment_default_overrides"]["input_chunking_enabled"] is True
        assert manifest["dataset_runtime_override"]["experiment_default_overrides_applied"]["input_chunking_enabled"] is False
        assert manifest["dataset_runtime_override"]["app_config_override"]["input_chunking_enabled"] is False
        assert manifest["dataset_runtime_override"]["experiment_default_overrides"]["induction_projection_mode"] == "growth"
        assert manifest["dataset_runtime_override"]["experiment_default_overrides"]["enable_cognitive_stitching"] is False
        assert manifest["dataset_runtime_override"]["experiment_default_overrides"]["cognitive_stitching_stage"] == "disabled"
        assert manifest["dataset_runtime_override"]["baseline_conforms_to_growth_cs_off"] is True
        assert any(
            snapshot.get("input_chunking_enabled") is False
            and snapshot.get("induction_projection_mode") == "growth"
            and snapshot.get("enable_cognitive_stitching") is False
            and snapshot.get("cognitive_stitching_stage") == "disabled"
            for snapshot in app.runtime_override_snapshots
        )

        rows = _read_jsonl(resolve_run_dir(run_id) / "metrics.jsonl")
        timing_rows = _read_jsonl(resolve_run_dir(run_id) / "runner_timing.jsonl")
        previews = [row.get("input_text_preview") for row in rows]
        assert previews == ["REGISTER_CONTRACT", "QUERY_WEATHER_OK", "LONG-FEEDBACK-SENTENCE", "NEXT_PROBE"]
        assert len(timing_rows) == len(rows)
        assert manifest.get("runner_timing_path", "").endswith("runner_timing.jsonl")
        assert manifest.get("tick_loop_finished_at_ms", 0) > 0
        assert manifest.get("finished_at_ms", 0) >= manifest.get("tick_loop_finished_at_ms", 0)
        assert manifest.get("runner_timing", {}).get("executed_tick_count") == len(rows)
        assert "timing_runner_manifest_persist_ms" in rows[0]
        assert "timing_runner_metrics_serialize_ms" in timing_rows[0]
        assert [row.get("input_queue_deferred_chunk_consumed_count", 0) for row in rows] == [0, 0, 0, 0]
        assert rows[2]["synthetic_tick"] is True
        assert rows[3]["tick_source"] == "dataset"
        assert app._config.get("input_chunking_enabled") is True
        assert app._config.get("induction_projection_mode") == "residual"
        assert app._config.get("enable_cognitive_stitching") is True
        assert app._config.get("cognitive_stitching_stage") == "post_induction"
    finally:
        dataset_path = imported_datasets_dir() / dataset_name
        if dataset_path.exists():
            dataset_path.unlink()
        run_dir = resolve_run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


def test_realtime_cycle_alignment_helper_matches_experiment_mainline_overrides():
    app = _ChunkingFakeExperimentApp()
    app._config.update(
        {
            "input_chunking_enabled": False,
            "enable_goal_b_char_sa_string_mode": False,
            "induction_projection_mode": "residual",
            "enable_cognitive_stitching": True,
            "cognitive_stitching_stage": "post_induction",
        }
    )

    result = apply_experiment_default_app_overrides(
        app,
        source="pytest_realtime_api_cycle",
    )

    assert result["source"] == "pytest_realtime_api_cycle"
    assert result["baseline_conforms_to_growth_cs_off"] is True
    assert result["runtime_refresh_applied"] is True
    assert result["effective_app_baseline"] == EXPERIMENT_DEFAULT_APP_OVERRIDES
    assert app.runtime_override_snapshots[-1] == EXPERIMENT_DEFAULT_APP_OVERRIDES
    for key, expected in EXPERIMENT_DEFAULT_APP_OVERRIDES.items():
        assert app._config.get(key) == expected


def test_run_dataset_expectation_contract_success_emits_synthetic_feedback_tick():
    dataset_name = f"contract_success_{uuid.uuid4().hex}.yaml"
    run_id = f"test_contract_success_{uuid.uuid4().hex}"
    ref = _write_imported_dataset(
        dataset_name,
        """dataset_id: contract_success_demo
seed: 1
time_basis: tick
tick_dt_ms: 100
episodes:
  - id: ep_contract_success
    ticks:
      - text: 发起延迟期望
        labels:
          expectation_contract:
            id: recall_contract
            within_ticks: 2
            success_conditions:
              kind: action_executed_kind_min
              action_kind: recall
              min_count: 1
            on_success:
              teacher_rwd: 0.3
              feedback_text: 系统反馈：执行成功
              feedback_note: delayed reward after recall
      - text: 触发回忆
""",
    )
    app = _FakeExperimentApp()

    try:
        result = run_dataset(app=app, dataset_ref=ref, options=RunOptions(), run_id=run_id)
        assert result["success"] is True
        manifest = result["manifest"]
        assert manifest["status"] == "completed"
        assert manifest["source_tick_done"] == 2
        assert manifest["synthetic_tick_done"] == 1
        assert manifest["executed_tick_done_total"] == 3
        assert manifest["registered_count"] == 1
        assert manifest["success_count"] == 1
        assert manifest["failure_count"] == 0
        assert manifest["expectation_contracts"]["registered_count"] == 1
        assert manifest["expectation_contracts"]["success_count"] == 1
        assert manifest["expectation_contracts"]["failure_count"] == 0

        run_dir = resolve_run_dir(run_id)
        metrics_rows = _read_jsonl(run_dir / "metrics.jsonl")
        assert len(metrics_rows) == 3
        assert metrics_rows[1]["action_executed_recall"] == 1
        assert metrics_rows[1]["action_executed_recall_source_visible"] == 1
        assert metrics_rows[1]["action_executed_recall_synthetic_only"] == 0
        assert metrics_rows[-1]["tick_source"] == "expectation_contract_feedback"
        assert metrics_rows[-1]["synthetic_tick"] is True
        assert metrics_rows[-1]["expectation_contract_outcome"] == "success"
        assert metrics_rows[-1]["action_executed_count_source_visible"] == 0
        assert metrics_rows[-1]["action_executed_count_synthetic_only"] == 0
        assert metrics_rows[-1]["teacher_rwd"] == 0.3

        events_rows = _read_jsonl(run_dir / "expectation_contract_events.jsonl")
        settled = [row for row in events_rows if row.get("event") == "settled"]
        assert settled
        assert settled[-1]["outcome"] == "success"
        assert settled[-1]["frozen_anchor"]["teacher_anchor_ref_object_id"] == "st_anchor"
    finally:
        dataset_path = imported_datasets_dir() / dataset_name
        if dataset_path.exists():
            dataset_path.unlink()
        run_dir = resolve_run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


def test_run_dataset_expectation_contract_run_end_failure_emits_timeout_feedback_tick():
    dataset_name = f"contract_failure_{uuid.uuid4().hex}.yaml"
    run_id = f"test_contract_failure_{uuid.uuid4().hex}"
    ref = _write_imported_dataset(
        dataset_name,
        """dataset_id: contract_failure_demo
seed: 1
time_basis: tick
tick_dt_ms: 100
episodes:
  - id: ep_contract_failure
    ticks:
      - text: 发起但不会满足
        labels:
          expectation_contract:
            id: missing_recall_contract
            within_ticks: 1
            success_conditions:
              kind: action_executed_kind_min
              action_kind: recall
              min_count: 1
            on_failure:
              teacher_pun: 0.4
              feedback_text: 系统反馈：没有执行
              feedback_note: delayed punish at run end
""",
    )
    app = _FakeExperimentApp()

    try:
        result = run_dataset(app=app, dataset_ref=ref, options=RunOptions(), run_id=run_id)
        assert result["success"] is True
        manifest = result["manifest"]
        assert manifest["status"] == "completed"
        assert manifest["source_tick_done"] == 1
        assert manifest["synthetic_tick_done"] == 1
        assert manifest["executed_tick_done_total"] == 2
        assert manifest["registered_count"] == 1
        assert manifest["success_count"] == 0
        assert manifest["failure_count"] == 1
        assert manifest["expectation_contracts"]["registered_count"] == 1
        assert manifest["expectation_contracts"]["success_count"] == 0
        assert manifest["expectation_contracts"]["failure_count"] == 1

        run_dir = resolve_run_dir(run_id)
        metrics_rows = _read_jsonl(run_dir / "metrics.jsonl")
        assert len(metrics_rows) == 2
        assert metrics_rows[-1]["tick_source"] == "expectation_contract_feedback"
        assert metrics_rows[-1]["expectation_contract_outcome"] == "failure"
        assert metrics_rows[-1]["action_executed_count_source_visible"] == 0
        assert metrics_rows[-1]["action_executed_count_synthetic_only"] == 0
        assert metrics_rows[-1]["teacher_pun"] == 0.4

        events_rows = _read_jsonl(run_dir / "expectation_contract_events.jsonl")
        settled = [row for row in events_rows if row.get("event") == "settled"]
        assert settled
        assert settled[-1]["outcome"] == "failure"
        assert settled[-1]["reason"] == "run_end"
    finally:
        dataset_path = imported_datasets_dir() / dataset_name
        if dataset_path.exists():
            dataset_path.unlink()
        run_dir = resolve_run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


def test_run_dataset_expectation_contract_duplicate_spec_ids_are_separate_instances():
    dataset_name = f"contract_duplicate_weather_{uuid.uuid4().hex}.yaml"
    run_id = f"test_contract_duplicate_weather_{uuid.uuid4().hex}"
    ref = _write_imported_dataset(
        dataset_name,
        """dataset_id: contract_duplicate_weather_demo
seed: 1
time_basis: tick
tick_dt_ms: 100
episodes:
  - id: ep_contract_duplicate_weather
    ticks:
      - text: weak weather request
        labels:
          expectation_contract:
            id: reused_weather_contract
            within_ticks: 1
            success_conditions:
              kind: action_executed_kind_min
              action_kind: weather_stub
              min_count: 1
            on_failure:
              teacher_pun: 0.2
              feedback_text: weather missing
      - text: idle after weak request
      - text: second weather request
        labels:
          expectation_contract:
            id: reused_weather_contract
            within_ticks: 1
            success_conditions:
              kind: action_executed_kind_min
              action_kind: weather_stub
              min_count: 1
            on_success:
              teacher_rwd: 0.3
              feedback_text: weather executed
      - text: settle second QUERY_WEATHER_OK request
""",
    )
    app = _FakeExperimentApp()

    try:
        result = run_dataset(app=app, dataset_ref=ref, options=RunOptions(max_ticks=10), run_id=run_id)
        assert result["success"] is True
        manifest = result["manifest"]
        assert manifest["tick_planned"] == 4
        assert manifest["registered_count"] == 2
        assert manifest["success_count"] == 1
        assert manifest["failure_count"] == 1
        assert manifest["expectation_contracts"]["registered_count"] == 2
        assert manifest["expectation_contracts"]["success_count"] == 1
        assert manifest["expectation_contracts"]["failure_count"] == 1

        run_dir = resolve_run_dir(run_id)
        events_rows = _read_jsonl(run_dir / "expectation_contract_events.jsonl")
        registered = [row for row in events_rows if row.get("event") == "registered"]
        settled = [row for row in events_rows if row.get("event") == "settled"]
        assert len(registered) == 2
        assert len(settled) == 2
        assert {row["outcome"] for row in settled} == {"success", "failure"}
        assert registered[0]["spec_id"] == registered[1]["spec_id"] == "reused_weather_contract"
        assert registered[0]["contract_id"] != registered[1]["contract_id"]
    finally:
        dataset_path = imported_datasets_dir() / dataset_name
        if dataset_path.exists():
            dataset_path.unlink()
        run_dir = resolve_run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


def test_run_dataset_prints_progress_for_long_run_without_callback(capsys):
    dataset_name = f"progress_probe_{uuid.uuid4().hex}.yaml"
    run_id = f"test_progress_probe_{uuid.uuid4().hex}"
    tick_lines = "\n".join([f"      - text: tick_{idx}" for idx in range(21)])
    ref = _write_imported_dataset(
        dataset_name,
        f"""dataset_id: progress_probe_demo
seed: 1
time_basis: tick
tick_dt_ms: 100
episodes:
  - id: ep_progress_probe
    ticks:
{tick_lines}
""",
    )
    app = _FakeExperimentApp()

    try:
        result = run_dataset(app=app, dataset_ref=ref, options=RunOptions(), run_id=run_id)
        assert result["success"] is True
        stdout = capsys.readouterr().out
        assert "[Experiment] status=running" in stdout
        assert "source=20/21" in stdout
        assert "status=completed" in stdout
    finally:
        dataset_path = imported_datasets_dir() / dataset_name
        if dataset_path.exists():
            dataset_path.unlink()
        run_dir = resolve_run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


def test_run_dataset_blank_hdb_structure_numeric_probe_surfaces_competition(tmp_path):
    from observatory._app import ObservatoryApp

    dataset_name = f"structure_numeric_probe_{uuid.uuid4().hex}.yaml"
    run_id = f"test_structure_numeric_probe_{uuid.uuid4().hex}"
    ref = _write_imported_dataset(
        dataset_name,
        """dataset_id: structure_numeric_probe
seed: 20260428
time_basis: tick
tick_dt_ms: 100
episodes:
  - id: ep_probe
    ticks:
      - text: ABX
      - text: ABY
      - text: ABZ
      - text: ABQ
      - text: ABR
      - text: ABX
      - text: ABY
      - text: ABZ
      - text: ABQ
      - text: ABR
""",
    )
    hdb_dir = tmp_path / "hdb_blank_probe"
    app = ObservatoryApp(
        config_override={
            "enable_goal_b_char_sa_string_mode": True,
            "enable_structure_level_retrieval_storage": True,
            "sensor_enable_stimulus_intensity_attribute_sa": True,
            "sensor_stimulus_intensity_attribute_min_er": 0.0,
            "sensor_attribute_er_ratio": 0.25,
            "sensor_attribute_ev_ratio": 0.0,
            "hdb_enable_background_repair": False,
            "hdb_data_dir": str(hdb_dir),
            "export_json": False,
            "export_html": False,
        }
    )

    try:
        result = run_dataset(
            app=app,
            dataset_ref=ref,
            options=RunOptions(reset_mode="clear_all", export_json=False, export_html=False),
            run_id=run_id,
            progress_cb=lambda payload: None,
        )
        assert result["success"] is True
        manifest = result["manifest"]
        baseline = dict(manifest.get("runtime_baseline", {}) or {})
        assert isinstance(baseline.get("hdb_before_reset"), dict)
        assert isinstance(baseline.get("hdb_after_reset"), dict)
        assert str((baseline.get("hdb_after_reset", {}) or {}).get("hdb_data_dir", "")).endswith("hdb_blank_probe")

        run_dir = resolve_run_dir(run_id)
        metrics_rows = _read_jsonl(run_dir / "metrics.jsonl")
        assert len(metrics_rows) == 10
        assert any(int(row.get("structure_round_competitive_count", 0) or 0) > 0 for row in metrics_rows)
        assert any(int(row.get("structure_match_v2_numeric_nonzero_count", 0) or 0) > 0 for row in metrics_rows)
    finally:
        try:
            app.close()
        except Exception:
            pass
        dataset_path = imported_datasets_dir() / dataset_name
        if dataset_path.exists():
            dataset_path.unlink()
        run_dir = resolve_run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


def test_run_dataset_blank_hdb_time_projection_probe_surfaces_runtime_time_like_visibility(tmp_path):
    from observatory._app import ObservatoryApp

    dataset_name = f"time_projection_probe_{uuid.uuid4().hex}.yaml"
    run_id = f"test_time_projection_probe_{uuid.uuid4().hex}"
    ref = _write_imported_dataset(
        dataset_name,
        """dataset_id: time_projection_probe
seed: 20260428
time_basis: tick
tick_dt_ms: 1000
episodes:
  - id: ep_probe
    ticks:
      - text: ABX
      - text: ABY
      - text: ABZ
      - text: ABQ
      - text: ABR
      - text: ABX
      - text: ABY
      - text: ABZ
      - text: ABQ
      - text: ABR
""",
    )
    hdb_dir = tmp_path / "hdb_time_projection_probe"
    app = ObservatoryApp(
        config_override={
            "enable_goal_b_char_sa_string_mode": True,
            "enable_structure_level_retrieval_storage": True,
            "sensor_enable_stimulus_intensity_attribute_sa": True,
            "sensor_stimulus_intensity_attribute_min_er": 0.0,
            "sensor_attribute_er_ratio": 0.25,
            "sensor_attribute_ev_ratio": 0.0,
            "hdb_enable_background_repair": False,
            "hdb_data_dir": str(hdb_dir),
            "export_json": False,
            "export_html": False,
        }
    )

    try:
        result = run_dataset(
            app=app,
            dataset_ref=ref,
            options=RunOptions(reset_mode="clear_all", export_json=False, export_html=False),
            run_id=run_id,
            progress_cb=lambda payload: None,
        )
        assert result["success"] is True

        run_dir = resolve_run_dir(run_id)
        metrics_rows = _read_jsonl(run_dir / "metrics.jsonl")
        assert len(metrics_rows) == 10
        assert any(int(row.get("time_sensor_projection_binding_count", 0) or 0) > 0 for row in metrics_rows)
        assert any(int(row.get("structure_match_v2_numeric_nonzero_count", 0) or 0) > 0 for row in metrics_rows)
        assert any(int(row.get("internal_time_like_attribute_count", 0) or 0) > 0 for row in metrics_rows)
    finally:
        try:
            app.close()
        except Exception:
            pass
        dataset_path = imported_datasets_dir() / dataset_name
        if dataset_path.exists():
            dataset_path.unlink()
        run_dir = resolve_run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


def test_run_dataset_builtin_structure_numeric_competition_probe_stays_observable(tmp_path):
    run_id = f"test_builtin_structure_numeric_{uuid.uuid4().hex}"
    hdb_dir = tmp_path / "hdb_builtin_structure_numeric"
    app = _build_real_experiment_app(hdb_dir=hdb_dir)

    try:
        result = run_dataset(
            app=app,
            dataset_ref=DatasetFileRef(source="built_in", rel_path="structure_numeric_competition_v2.yaml"),
            options=RunOptions(reset_mode="clear_all", export_json=False, export_html=False),
            run_id=run_id,
            progress_cb=lambda payload: None,
        )
        assert result["success"] is True

        metrics_rows = _read_jsonl(resolve_run_dir(run_id) / "metrics.jsonl")
        assert len(metrics_rows) == 10
        assert any(int(row.get("structure_round_competitive_count", 0) or 0) > 0 for row in metrics_rows)
        assert any(int(row.get("structure_match_v2_numeric_nonzero_count", 0) or 0) > 0 for row in metrics_rows)
        assert any(int(row.get("time_sensor_projection_binding_count", 0) or 0) > 0 for row in metrics_rows)
    finally:
        try:
            app.close()
        except Exception:
            pass
        run_dir = resolve_run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


def test_run_dataset_builtin_teacher_signal_probe_surfaces_projection_and_feedback_chain(tmp_path):
    run_id = f"test_builtin_teacher_projection_{uuid.uuid4().hex}"
    hdb_dir = tmp_path / "hdb_builtin_teacher_projection"
    app = _build_real_experiment_app(hdb_dir=hdb_dir)

    try:
        result = run_dataset(
            app=app,
            dataset_ref=DatasetFileRef(source="built_in", rel_path="teacher_signal_next_tick_projection_v1.yaml"),
            options=RunOptions(reset_mode="clear_all", export_json=False, export_html=False),
            run_id=run_id,
            progress_cb=lambda payload: None,
        )
        assert result["success"] is True

        metrics_rows = _read_jsonl(resolve_run_dir(run_id) / "metrics.jsonl")
        assert len(metrics_rows) == 10
        _assert_growth_cs_off_baseline(result["manifest"], metrics_rows)
        assert any(int(row.get("time_sensor_projection_binding_count", 0) or 0) > 0 for row in metrics_rows)
        assert any(int(row.get("teacher_applied_count", 0) or 0) > 0 for row in metrics_rows)
        assert any(float(row.get("reward_signal_live_total_energy", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("punish_signal_live_total_energy", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("cfs_expectation_count", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("cfs_expectation_unverified_count", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("cfs_grasp_live_total_energy", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(int(row.get("structure_match_v2_soft_partial_selected_count", 0) or 0) > 0 for row in metrics_rows)
        assert any(float(row.get("iesm_emotion_update_abs_total", 0.0) or 0.0) > 0.0 for row in metrics_rows)
    finally:
        try:
            app.close()
        except Exception:
            pass
        run_dir = resolve_run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


def test_run_dataset_builtin_cfs_positive_guidance_probe_surfaces_positive_feelings(tmp_path):
    run_id = f"test_builtin_cfs_positive_{uuid.uuid4().hex}"
    hdb_dir = tmp_path / "hdb_builtin_cfs_positive"
    app = _build_real_experiment_app(hdb_dir=hdb_dir)

    try:
        result = run_dataset(
            app=app,
            dataset_ref=DatasetFileRef(source="built_in", rel_path="cfs_positive_guidance_probe_v1.yaml"),
            options=RunOptions(reset_mode="clear_all", export_json=False, export_html=False),
            run_id=run_id,
            progress_cb=lambda payload: None,
        )
        assert result["success"] is True

        metrics_rows = _read_jsonl(resolve_run_dir(run_id) / "metrics.jsonl")
        assert len(metrics_rows) == 24
        assert any(float(row.get("cfs_correct_event_live_total_energy", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("cfs_grasp_live_total_energy", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("cfs_simplicity_live_total_energy", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("cfs_repetition_live_total_energy", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("iesm_emotion_update_abs_total", 0.0) or 0.0) > 0.0 for row in metrics_rows)
    finally:
        try:
            app.close()
        except Exception:
            pass
        run_dir = resolve_run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


def test_run_dataset_builtin_teacher_positive_recovery_probe_surfaces_positive_teacher_chain(tmp_path):
    run_id = f"test_builtin_teacher_positive_recovery_{uuid.uuid4().hex}"
    hdb_dir = tmp_path / "hdb_builtin_teacher_positive_recovery"
    app = _build_real_experiment_app(
        hdb_dir=hdb_dir,
        extra_config={
            "enable_structure_level_retrieval_storage": False,
            "sensor_enable_stimulus_intensity_attribute_sa": False,
            "sensor_attribute_er_ratio": 0.0,
            "sensor_attribute_ev_ratio": 0.0,
            "cfs_to_nt_source_mode": "iesm_rules",
            "rwd_pun_to_nt_source_mode": "iesm_rules",
        },
    )

    try:
        result = run_dataset(
            app=app,
            dataset_ref=DatasetFileRef(source="built_in", rel_path="teacher_positive_recovery_probe_v1.yaml"),
            options=RunOptions(reset_mode="clear_all", export_json=False, export_html=False),
            run_id=run_id,
            progress_cb=lambda payload: None,
        )
        assert result["success"] is True

        metrics_rows = _read_jsonl(resolve_run_dir(run_id) / "metrics.jsonl")
        assert len(metrics_rows) == 13
        _assert_growth_cs_off_baseline(result["manifest"], metrics_rows)
        assert any(int(row.get("teacher_applied_count", 0) or 0) > 0 for row in metrics_rows)
        assert any(float(row.get("cfs_expectation_count", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("cfs_expectation_unverified_count", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("cfs_grasp_live_total_energy", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("cfs_simplicity_live_total_energy", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("reward_signal_live_total_energy", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("punish_signal_live_total_energy", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("iesm_emotion_update_abs_total", 0.0) or 0.0) > 0.0 for row in metrics_rows)
    finally:
        try:
            app.close()
        except Exception:
            pass
        run_dir = resolve_run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


def test_run_dataset_builtin_teacher_relief_reassurance_probe_surfaces_lighter_positive_teacher_chain(tmp_path):
    run_id = f"test_builtin_teacher_relief_reassurance_{uuid.uuid4().hex}"
    hdb_dir = tmp_path / "hdb_builtin_teacher_relief_reassurance"
    app = _build_real_experiment_app(
        hdb_dir=hdb_dir,
        extra_config={
            "enable_structure_level_retrieval_storage": False,
            "sensor_enable_stimulus_intensity_attribute_sa": False,
            "sensor_attribute_er_ratio": 0.0,
            "sensor_attribute_ev_ratio": 0.0,
            "cfs_to_nt_source_mode": "iesm_rules",
            "rwd_pun_to_nt_source_mode": "iesm_rules",
        },
    )

    try:
        result = run_dataset(
            app=app,
            dataset_ref=DatasetFileRef(source="built_in", rel_path="teacher_relief_reassurance_probe_v1.yaml"),
            options=RunOptions(reset_mode="clear_all", export_json=False, export_html=False),
            run_id=run_id,
            progress_cb=lambda payload: None,
        )
        assert result["success"] is True

        metrics_rows = _read_jsonl(resolve_run_dir(run_id) / "metrics.jsonl")
        assert len(metrics_rows) == 6
        _assert_growth_cs_off_baseline(result["manifest"], metrics_rows)
        assert any(int(row.get("teacher_applied_count", 0) or 0) > 0 for row in metrics_rows)
        assert any(float(row.get("rwd_pun_rwd", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("cfs_expectation_count", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("cfs_expectation_unverified_count", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("cfs_grasp_live_total_energy", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("cfs_simplicity_live_total_energy", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("iesm_emotion_update_abs_total", 0.0) or 0.0) > 0.0 for row in metrics_rows)
    finally:
        try:
            app.close()
        except Exception:
            pass
        run_dir = resolve_run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


def test_run_dataset_builtin_time_like_gap_probe_surfaces_structure_time_like_matching(tmp_path):
    run_id = f"test_builtin_time_like_gap_{uuid.uuid4().hex}"
    hdb_dir = tmp_path / "hdb_builtin_time_like_gap"
    app = _build_real_experiment_app(hdb_dir=hdb_dir)

    try:
        result = run_dataset(
            app=app,
            dataset_ref=DatasetFileRef(source="built_in", rel_path="time_like_gap_repetition_v1.yaml"),
            options=RunOptions(reset_mode="clear_all", export_json=False, export_html=False),
            run_id=run_id,
            progress_cb=lambda payload: None,
        )
        assert result["success"] is True
        manifest = result["manifest"]
        assert ((manifest.get("runtime_clock_override", {}) or {}).get("mode", "")) == "dataset_tick"

        metrics_rows = _read_jsonl(resolve_run_dir(run_id) / "metrics.jsonl")
        assert len(metrics_rows) == 16
        _assert_growth_cs_off_baseline(manifest, metrics_rows)
        assert any(int(row.get("time_sensor_projection_binding_count", 0) or 0) > 0 for row in metrics_rows)
        assert any(int(row.get("internal_time_like_attribute_count", 0) or 0) > 0 for row in metrics_rows)
        assert any(int(row.get("structure_match_v2_soft_partial_selected_count", 0) or 0) > 0 for row in metrics_rows)
        assert any(float(row.get("cfs_correct_event_live_total_energy", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("cfs_reassurance_live_total_energy", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(int(row.get("action_executed_diverge_mode", 0) or 0) > 0 for row in metrics_rows)
    finally:
        try:
            app.close()
        except Exception:
            pass
        run_dir = resolve_run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


def test_run_dataset_builtin_attention_mode_complexity_probe_surfaces_focus_and_diverge_modes(tmp_path):
    run_id = f"test_builtin_attention_mode_complexity_{uuid.uuid4().hex}"
    hdb_dir = tmp_path / "hdb_builtin_attention_mode_complexity"
    app = _build_real_experiment_app(hdb_dir=hdb_dir)

    try:
        result = run_dataset(
            app=app,
            dataset_ref=DatasetFileRef(source="built_in", rel_path="attention_mode_complexity_probe_v1.yaml"),
            options=RunOptions(reset_mode="clear_all", export_json=False, export_html=False),
            run_id=run_id,
            progress_cb=lambda payload: None,
        )
        assert result["success"] is True
        manifest = result["manifest"]
        assert ((manifest.get("runtime_clock_override", {}) or {}).get("mode", "")) == "dataset_tick"

        metrics_rows = _read_jsonl(resolve_run_dir(run_id) / "metrics.jsonl")
        assert len(metrics_rows) == 16
        _assert_growth_cs_off_baseline(manifest, metrics_rows)
        assert any(int(row.get("cfs_simplicity_count", 0) or 0) > 0 for row in metrics_rows)
        assert any(float(row.get("cfs_correct_event_live_total_energy", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(int(row.get("action_attempted_diverge_mode", 0) or 0) > 0 for row in metrics_rows)
        assert any(int(row.get("action_executed_diverge_mode", 0) or 0) > 0 for row in metrics_rows)
    finally:
        try:
            app.close()
        except Exception:
            pass
        run_dir = resolve_run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


def test_run_dataset_builtin_time_like_gap_probe_can_promote_shadow_memory_time_wildcard_when_enabled(tmp_path):
    run_id = f"test_builtin_time_like_gap_promoted_{uuid.uuid4().hex}"
    hdb_dir = tmp_path / "hdb_builtin_time_like_gap_promoted"
    from observatory._app import ObservatoryApp

    app = ObservatoryApp(
        config_override={
            "enable_goal_b_char_sa_string_mode": True,
            "enable_structure_level_retrieval_storage": True,
            "sensor_enable_stimulus_intensity_attribute_sa": True,
            "sensor_stimulus_intensity_attribute_min_er": 0.0,
            "sensor_attribute_er_ratio": 0.25,
            "sensor_attribute_ev_ratio": 0.0,
            "hdb_enable_background_repair": False,
            "hdb_data_dir": str(hdb_dir),
            "export_json": False,
            "export_html": False,
            "stimulus_residual_memory_promotion_enabled": True,
        }
    )

    try:
        result = run_dataset(
            app=app,
            dataset_ref=DatasetFileRef(source="built_in", rel_path="time_like_gap_repetition_v1.yaml"),
            options=RunOptions(reset_mode="clear_all", export_json=False, export_html=False),
            run_id=run_id,
            progress_cb=lambda payload: None,
        )
        assert result["success"] is True

        metrics_rows = _read_jsonl(resolve_run_dir(run_id) / "metrics.jsonl")
        assert len(metrics_rows) == 16
        assert any(int(row.get("stimulus_match_v2_numeric_time_like_wildcard_applied_count", 0) or 0) > 0 for row in metrics_rows)
        assert any(int(row.get("stimulus_match_v2_time_factor_bonus_applied_count", 0) or 0) > 0 for row in metrics_rows)
    finally:
        try:
            app.close()
        except Exception:
            pass
        run_dir = resolve_run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


def test_run_dataset_builtin_time_like_gap_promoted_dataset_applies_runtime_override_and_restores_default(tmp_path):
    run_id = f"test_builtin_time_like_gap_promoted_dataset_{uuid.uuid4().hex}"
    hdb_dir = tmp_path / "hdb_builtin_time_like_gap_promoted_dataset"
    app = _build_real_experiment_app(hdb_dir=hdb_dir)

    try:
        assert bool(app.hdb._config.get("stimulus_residual_memory_promotion_enabled", False)) is False

        result = run_dataset(
            app=app,
            dataset_ref=DatasetFileRef(source="built_in", rel_path="time_like_gap_repetition_promoted_v1.yaml"),
            options=RunOptions(reset_mode="clear_all", export_json=False, export_html=False),
            run_id=run_id,
            progress_cb=lambda payload: None,
        )
        assert result["success"] is True
        manifest = result["manifest"]
        dataset_runtime_override = dict(manifest.get("dataset_runtime_override", {}) or {})
        assert dataset_runtime_override.get("applied") is True
        assert "stimulus_residual_memory_promotion_enabled" in set(dataset_runtime_override.get("app_config_override_keys", []) or [])

        metrics_rows = _read_jsonl(resolve_run_dir(run_id) / "metrics.jsonl")
        assert len(metrics_rows) == 16
        assert any(int(row.get("stimulus_match_v2_numeric_time_like_wildcard_applied_count", 0) or 0) > 0 for row in metrics_rows)
        assert any(int(row.get("stimulus_match_v2_time_factor_bonus_applied_count", 0) or 0) > 0 for row in metrics_rows)
        assert bool(app.hdb._config.get("stimulus_residual_memory_promotion_enabled", False)) is False
    finally:
        try:
            app.close()
        except Exception:
            pass
        run_dir = resolve_run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


def test_run_dataset_builtin_weather_teacher_action_probe_surfaces_action_and_teacher_feedback(tmp_path):
    run_id = f"test_builtin_weather_teacher_action_{uuid.uuid4().hex}"
    hdb_dir = tmp_path / "hdb_builtin_weather_teacher_action"
    app = _build_real_experiment_app(hdb_dir=hdb_dir)

    try:
        result = run_dataset(
            app=app,
            dataset_ref=DatasetFileRef(source="built_in", rel_path="weather_teacher_action_probe_v1.yaml"),
            options=RunOptions(reset_mode="clear_all", export_json=False, export_html=False),
            run_id=run_id,
            progress_cb=lambda payload: None,
        )
        assert result["success"] is True

        manifest = result["manifest"]
        assert ((manifest.get("runtime_clock_override", {}) or {}).get("mode", "")) == "dataset_tick"
        assert manifest["status"] == "completed"
        assert manifest["source_tick_done"] == 4
        assert manifest["synthetic_tick_done"] == 2
        assert manifest["success_count"] == 1
        assert manifest["failure_count"] == 1

        metrics_rows = _read_jsonl(resolve_run_dir(run_id) / "metrics.jsonl")
        assert len(metrics_rows) == 6
        assert any(int(row.get("action_executed_weather_stub", 0) or 0) > 0 for row in metrics_rows)
        assert sum(int(row.get("teacher_applied_count", 0) or 0) for row in metrics_rows) >= 2
        assert any(float(row.get("reward_signal_live_total_energy", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("punish_signal_live_total_energy", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("iesm_emotion_update_abs_total", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(int(row.get("time_sensor_projection_binding_count", 0) or 0) > 0 for row in metrics_rows)
    finally:
        try:
            app.close()
        except Exception:
            pass
        run_dir = resolve_run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


def test_run_dataset_builtin_weather_teacher_action_local_feedback_probe_surfaces_reward_and_punish_bias(tmp_path):
    run_id = f"test_builtin_weather_teacher_local_feedback_{uuid.uuid4().hex}"
    hdb_dir = tmp_path / "hdb_builtin_weather_teacher_local_feedback"
    app = _build_real_experiment_app(hdb_dir=hdb_dir)

    try:
        result = run_dataset(
            app=app,
            dataset_ref=DatasetFileRef(source="built_in", rel_path="weather_teacher_action_local_feedback_probe_v1.yaml"),
            options=RunOptions(reset_mode="clear_all", export_json=False, export_html=False),
            run_id=run_id,
            progress_cb=lambda payload: None,
        )
        assert result["success"] is True

        manifest = result["manifest"]
        assert ((manifest.get("runtime_clock_override", {}) or {}).get("mode", "")) == "dataset_tick"
        assert manifest["status"] == "completed"
        assert manifest["success_count"] == 1
        assert manifest["failure_count"] == 1

        metrics_rows = _read_jsonl(resolve_run_dir(run_id) / "metrics.jsonl")
        assert len(metrics_rows) == 10
        assert any(int(row.get("action_executed_weather_stub", 0) or 0) > 0 for row in metrics_rows)
        assert any(int(row.get("action_local_lookup_hit_count_weather_stub", 0) or 0) > 0 for row in metrics_rows)
        assert any(int(row.get("action_local_lookup_text_fallback_hit_count_weather_stub", 0) or 0) > 0 for row in metrics_rows)
        assert sum(int(row.get("action_local_lookup_miss_count_weather_stub", 0) or 0) for row in metrics_rows) == 0
        assert any(float(row.get("action_local_reward_drive_bonus_total_weather_stub", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("action_local_punish_drive_penalty_total_weather_stub", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("reward_signal_live_total_energy", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("punish_signal_live_total_energy", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("cfs_expectation_count", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("cfs_expectation_unverified_count", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("cfs_pressure_count", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("cfs_pressure_verified_count", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("cfs_pressure_unverified_count", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert any(float(row.get("iesm_emotion_update_abs_total", 0.0) or 0.0) > 0.0 for row in metrics_rows)
        assert sum(int(row.get("teacher_applied_count", 0) or 0) for row in metrics_rows) >= 2
    finally:
        try:
            app.close()
        except Exception:
            pass
        run_dir = resolve_run_dir(run_id)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)
