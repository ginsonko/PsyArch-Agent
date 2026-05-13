# -*- coding: utf-8 -*-

from pathlib import Path

from observatory import agent_runtime as ar
from observatory.agent_runtime import AgentConfig, AgentRuntime


class _TimelineFakeApp:
    def __init__(self):
        self._config = {}
        self._config_override = {}
        self._report_history = []
        self._last_report = {}
        self._runtime_residual_exact_rebind_cache = {}
        self._projection_fatigue = {}
        self._teacher_local_feedback_alias_cache = []
        self._runtime_pool_item_summary_cache = {}
        self._pending_external_text_chunks = []
        self.pool = type("Pool", (), {})()
        self.pool._snapshot = type("Snapshot", (), {})()
        self.pool._snapshot._item_summary_cache = {}
        self.pool._snapshot._item_summary_cache_order = []

        def _clear_item_summary_cache():
            self.pool._snapshot._item_summary_cache.clear()
            self.pool._snapshot._item_summary_cache_order.clear()

        self.pool._snapshot.clear_item_summary_cache = _clear_item_summary_cache
        self.hdb = type("Hdb", (), {})()
        self.hdb._reset_runtime_state = lambda: {"reset": True}
        self.hdb._structure_store = type("StructureStore", (), {})()
        self.hdb._structure_store._shared_runtime_cache = {"ns": {"k1": 1, "k2": 2}}

    def run_cycle(self, text=None, labels=None):
        tick = len(self._report_history) + 1
        report = {
            "tick_counter": tick,
            "tick_id": f"tick_{tick}",
            "tick_labels": labels or {},
            "timing": {},
            "final_state": {
                "state_energy_summary": {"active_item_count": 0},
            },
            "memory_activation": {"snapshot": {"summary": {"active_count": 0}}},
        }
        self._last_report = report
        self._report_history.append(report)
        return report

    def get_dashboard_data(self):
        return {
            "tick_counter": len(self._report_history),
            "state_snapshot": {"summary": {"active_item_count": 0}, "top_items": []},
            "state_energy_summary": {"active_item_count": 0, "total_er": 0.0, "total_ev": 0.0, "total_cp": 0.0},
            "hdb_snapshot": {},
            "last_report": self._last_report,
        }


def _patch_runtime_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ar, "_state_path", lambda: tmp_path / "agent_state.json")
    monkeypatch.setattr(ar, "_diary_path", lambda: tmp_path / "agent_diary.json")
    monkeypatch.setattr(ar, "_scheduled_tasks_path", lambda: tmp_path / "agent_scheduled_tasks.json")
    monkeypatch.setattr(ar, "_events_path", lambda: tmp_path / "agent_events.jsonl")
    monkeypatch.setattr(ar, "_system_log_path", lambda: tmp_path / "agent_system_events.jsonl")
    monkeypatch.setattr(ar, "_timeline_memory_dir", lambda: tmp_path / "timeline_memory")
    monkeypatch.setattr(ar, "_timeline_index_path", lambda: tmp_path / "timeline_memory" / "index.json")


def _runtime(tmp_path: Path, monkeypatch) -> AgentRuntime:
    _patch_runtime_paths(tmp_path, monkeypatch)
    runtime = AgentRuntime(_TimelineFakeApp())
    runtime.config = AgentConfig(
        timeline_memory_enabled=True,
        timeline_memory_shard_max_chars=60,
        timeline_memory_result_limit=8,
        timeline_memory_neighbor_window=1,
        runtime_report_history_soft_limit=4,
    )
    runtime.record_event = lambda payload: None
    runtime.record_system_log = lambda payload: payload
    return runtime


def test_timeline_recall_by_time_and_clue(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    base_ms = 1_800_000_000_000
    rows = [
        runtime._timeline_build_record(
            kind="turn_input",
            role="user",
            text="上午我们聊了晋中天气和睡觉提醒。",
            ts=base_ms - 6 * 3600 * 1000,
            conversation_id="private:474764004",
            adapter_label="私聊 银子",
        ),
        runtime._timeline_build_record(
            kind="thought",
            role="thought",
            text="我得记住她是晋中的，之后查天气能直接用上。",
            ts=base_ms - 6 * 3600 * 1000 + 60_000,
            conversation_id="private:474764004",
            adapter_label="私聊 银子",
        ),
        runtime._timeline_build_record(
            kind="assistant_reply",
            role="assistant",
            text="记住了，五分钟后提醒你睡觉。",
            ts=base_ms - 6 * 3600 * 1000 + 120_000,
            conversation_id="private:474764004",
            adapter_label="私聊 银子",
        ),
    ]
    for row in rows:
        runtime._timeline_append_record(row)

    monkeypatch.setattr(ar, "_now_ms", lambda: base_ms)
    recalled = runtime.timeline_recall({"hours_ago": 6, "clue": "上午 晋中 提醒"}, source="test")

    assert recalled["ok"] is True
    assert recalled["records"]
    joined = "\n".join(str(item.get("text") or "") for item in recalled["records"])
    assert "晋中" in joined
    assert "提醒" in joined
    assert any(float(item.get("score") or 0.0) > 0 for item in recalled["records"])


def test_timeline_recall_shards_roll_and_neighbor_lookup(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    base_ms = 1_800_100_000_000
    large_text = "测试内容" * 1400
    for idx in range(5):
        runtime._timeline_append_record(
            runtime._timeline_build_record(
                kind="turn_input",
                role="user",
                text=f"第 {idx} 条记录 {large_text}",
                ts=base_ms + idx * 60_000,
                conversation_id="private:1",
                adapter_label="私聊 测试",
            )
        )

    index = runtime._timeline_load_index()
    shards = [item for item in index.get("shards", []) if isinstance(item, dict)]
    assert len(shards) >= 2
    target_shard = shards[1]
    result = runtime.timeline_recall(
        {
            "shard_id": target_shard["id"],
            "neighbor_offset": -1,
            "limit": 10,
            "include_adjacent": False,
        },
        source="test",
    )

    shard_ids = {row.get("id") for row in result["shards"]}
    assert target_shard["id"] in shard_ids
    assert shards[0]["id"] in shard_ids


def test_default_allowlist_contains_timeline_recall():
    config = AgentConfig.from_dict({})
    assert "timeline_recall" in config.tool_allowlist


def test_timeline_recall_recent_reverse_without_time_prefers_recent_matches(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    runtime.config.timeline_memory_shard_max_chars = 80
    base_ms = 1_800_200_000_000
    rows = [
        runtime._timeline_build_record(
            kind="turn_input",
            role="user",
            text="很早以前聊过天气和老家，但没有提到晋中。",
            ts=base_ms - 5 * 60_000,
            conversation_id="private:1",
            adapter_label="私聊 测试",
        ),
        runtime._timeline_build_record(
            kind="turn_input",
            role="user",
            text="我是晋中的，以后查天气可以默认查晋中。",
            ts=base_ms - 2 * 60_000,
            conversation_id="private:1",
            adapter_label="私聊 测试",
        ),
        runtime._timeline_build_record(
            kind="assistant_reply",
            role="assistant",
            text="记住了，以后问天气我会先想到晋中。",
            ts=base_ms - 60_000,
            conversation_id="private:1",
            adapter_label="私聊 测试",
        ),
    ]
    for row in rows:
        runtime._timeline_append_record(row)

    monkeypatch.setattr(ar, "_now_ms", lambda: base_ms)
    recalled = runtime.timeline_recall({"clues": ["晋中", "天气"], "limit": 2}, source="test")

    assert recalled["ok"] is True
    assert recalled["recall_mode"] == "clue_recent_reverse"
    assert recalled["records"]
    assert "晋中" in "\n".join(str(item.get("text") or "") for item in recalled["records"])
    assert recalled["search_meta"]["scanned_shards"] >= 1
    assert recalled["search_meta"]["accumulated_score"] > 0


def test_timeline_recall_recent_reverse_reports_timeout_meta(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    runtime.config.timeline_memory_shard_max_chars = 80
    base_ms = 1_800_300_000_000
    for idx in range(6):
        runtime._timeline_append_record(
            runtime._timeline_build_record(
                kind="thought",
                role="thought",
                text=f"第{idx}条记录，内容里有天气、提醒和晋中线索 {idx}",
                ts=base_ms - idx * 60_000,
                conversation_id="private:1",
                adapter_label="私聊 测试",
            )
        )

    call_counter = {"count": 0}

    def fake_now_ms():
        call_counter["count"] += 1
        return base_ms + call_counter["count"] * 50

    monkeypatch.setattr(ar, "_now_ms", fake_now_ms)
    recalled = runtime.timeline_recall({"query": "晋中 提醒", "timeout_ms": 60, "limit": 3}, source="test")

    assert recalled["ok"] is True
    assert recalled["recall_mode"] == "clue_recent_reverse"
    assert recalled["search_meta"]["timeout_ms"] == 200
    assert recalled["search_meta"]["stop_reason"] in {"timeout", "score_threshold_reached", "all_shards_scanned"}


def test_post_cycle_memory_maintenance_throttles_gc_and_trims_runtime_caches(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    runtime.app._runtime_residual_exact_rebind_cache = {f"k{i}": f"st_{i}" for i in range(5000)}
    runtime.app._projection_fatigue = {f"p{i}": {"value": 1.0, "tick": i} for i in range(9000)}
    runtime.app._runtime_pool_item_summary_cache = {("k", i): {"id": i} for i in range(5000)}
    runtime.app.pool._snapshot._item_summary_cache = {("s", i): {"id": i} for i in range(9000)}
    runtime.app._report_history = [{"tick_counter": i} for i in range(12)]
    runtime.state["messages"] = [{"role": "user", "text": "x"}]
    runtime.state["thoughts"] = [{"text": "y"}]
    runtime.state["turns"] = [{"id": "turn_1"}]

    gc_calls: list[int] = []
    system_logs: list[dict] = []
    monkeypatch.setattr(ar.gc, "collect", lambda: gc_calls.append(1) or 0)
    runtime.record_system_log = lambda payload: system_logs.append(dict(payload)) or payload

    now_holder = {"value": 10_000}
    monkeypatch.setattr(ar, "_now_ms", lambda: now_holder["value"])
    runtime._last_runtime_memory_maintenance_ms = -20_000
    runtime._last_runtime_memory_log_ms = -70_000

    runtime._post_cycle_memory_maintenance(source="test_once")
    assert len(gc_calls) == 1
    assert len(runtime.app._runtime_residual_exact_rebind_cache) <= 2048
    assert len(runtime.app._projection_fatigue) <= 4096
    assert len(runtime.app._runtime_pool_item_summary_cache) <= 2048
    assert len(runtime.app.pool._snapshot._item_summary_cache) == 0
    assert runtime._last_runtime_memory_health["report_history_count"] == 4

    runtime._post_cycle_memory_maintenance(source="test_twice")
    assert len(gc_calls) == 1

    now_holder["value"] += 61_000
    runtime._post_cycle_memory_maintenance(source="test_log")
    assert system_logs


def test_idle_memory_maintenance_can_reset_runtime_caches_and_abort(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    runtime.app._runtime_residual_exact_rebind_cache = {f"k{i}": f"st_{i}" for i in range(5000)}
    runtime.app._projection_fatigue = {f"p{i}": {"value": 1.0, "tick": i} for i in range(9000)}
    runtime.app._runtime_pool_item_summary_cache = {("k", i): {"id": i} for i in range(5000)}
    runtime.app.pool._snapshot._item_summary_cache = {("s", i): {"id": i} for i in range(9000)}
    monkeypatch.setattr(ar.gc, "collect", lambda: 0)
    monkeypatch.setattr(ar, "_windows_trim_process_working_set", lambda: True)

    result = runtime.maybe_run_idle_memory_maintenance(source="unit_idle", force=True)

    assert result["ran"] is True
    assert result["gc_collected"] is True
    assert result["working_set_trimmed"] is True
    assert result["hdb_runtime_reset"]["reset"] is True
    assert len(runtime.app._runtime_residual_exact_rebind_cache) <= 2048
    assert len(runtime.app._projection_fatigue) <= 4096
    assert len(runtime.app._runtime_pool_item_summary_cache) <= 2048
    assert runtime.app.pool._snapshot._item_summary_cache == {}

    aborted = runtime.maybe_run_idle_memory_maintenance(
        source="unit_idle_abort",
        force=True,
        should_abort=lambda: True,
    )
    assert aborted["ran"] is False
    assert aborted["aborted"] is True
