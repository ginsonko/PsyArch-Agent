# -*- coding: utf-8 -*-

from pathlib import Path

from observatory.agent_runtime import AgentConfig, AgentRuntime


class _DiaryFakeApp:
    def __init__(self):
        self._config = {}
        self._config_override = {}
        self.reports = []

    def run_cycle(self, text=None, labels=None):
        tick = len(self.reports) + 1
        report = {
            "tick_counter": tick,
            "tick_id": f"tick_{tick}",
            "state_snapshot": {"summary": {"active_item_count": 0}, "top_items": []},
            "state_energy_summary": {"total_er": 0.0, "total_ev": 0.0, "total_cp": 0.0, "active_item_count": 0},
            "emotion": {"channels": []},
            "action": {"top_actions": [], "executed": []},
            "hdb_snapshot": {},
            "timing": {},
        }
        self.reports.append(report)
        return report

    def get_dashboard_data(self):
        return {
            "tick_counter": len(self.reports),
            "state_snapshot": {"summary": {}, "top_items": []},
            "state_energy_summary": {"total_er": 0.0, "total_ev": 0.0, "total_cp": 0.0},
            "hdb_snapshot": {},
            "last_report": self.reports[-1] if self.reports else {},
        }


def _runtime(tmp_path: Path, monkeypatch) -> AgentRuntime:
    monkeypatch.setattr("observatory.agent_runtime._diary_path", lambda: tmp_path / "agent_diary.json")
    monkeypatch.setattr("observatory.agent_runtime._scheduled_tasks_path", lambda: tmp_path / "agent_scheduled_tasks.json")
    monkeypatch.setattr("observatory.agent_runtime._events_path", lambda: tmp_path / "agent_events.jsonl")
    runtime = AgentRuntime(_DiaryFakeApp())
    runtime.config = AgentConfig(
        diary_enabled=True,
        diary_entry_limit=10,
        diary_gc_oldest_count=5,
        diary_entry_max_chars=4000,
        diary_read_total_max_chars=12000,
        scheduled_tasks_enabled=True,
        scheduled_task_limit=5,
    )
    runtime.record_event = lambda payload: None
    return runtime


def test_diary_create_list_read_and_append(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)

    created = runtime.tools.run(
        "写日记",
        {"title": "和银子的约定", "content": "约定：发布前先本地验收。", "importance": 92},
        source="test",
    )
    assert created["ok"] is True
    entry_id = created["output"]["entry"]["id"]

    listed = runtime.tools.run("查日记", {}, source="test")
    assert listed["ok"] is True
    assert listed["output"]["view"] == "list"
    assert listed["output"]["entries"][0]["title"] == "和银子的约定"
    assert "content" not in listed["output"]["entries"][0]

    detailed = runtime.tools.run("read_diary", {"ids": [entry_id]}, source="test")
    assert detailed["ok"] is True
    assert detailed["output"]["entries"][0]["content"] == "约定：发布前先本地验收。"

    appended = runtime.tools.run(
        "write_diary",
        {"id": entry_id, "content": "补充：验收没问题后再考虑更新仓库。", "importance": 95, "mode": "append"},
        source="test",
    )
    assert appended["ok"] is True
    updated = runtime.read_diary({"id": entry_id})
    content = updated["entries"][0]["content"]
    assert "发布前先本地验收" in content
    assert "验收没问题后再考虑更新仓库" in content
    assert updated["entries"][0]["importance"] == 95


def test_diary_gc_removes_low_importance_from_oldest_window(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)

    scores = [80, 10, 70, 60, 50, 1, 2, 3, 4, 5, 6]
    for idx, importance in enumerate(scores, start=1):
        result = runtime.write_diary(
            {"title": f"条目 {idx}", "content": f"内容 {idx}", "importance": importance},
            source="test",
        )
        assert result["ok"] is True

    listed = runtime.read_diary({})
    titles = {row["title"] for row in listed["entries"]}
    assert len(titles) == 10
    assert "条目 2" not in titles
    assert {"条目 1", "条目 3", "条目 6", "条目 11"} <= titles


def test_default_allowlist_contains_diary_tools():
    config = AgentConfig.from_dict({})
    assert "write_diary" in config.tool_allowlist
    assert "read_diary" in config.tool_allowlist
    assert "schedule_task" in config.tool_allowlist


def test_schedule_task_create_list_cancel_and_gc(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)

    created = runtime.tools.run(
        "schedule_task",
        {
            "commands": [
                {
                    "operation": "create",
                    "summary": f"任务 {idx}",
                    "prompt": f"提醒内容 {idx}",
                    "trigger": {"type": "daily", "time": f"0{idx}:00"},
                }
                for idx in range(1, 7)
            ]
        },
        source="test",
    )
    assert created["ok"] is True
    assert len(created["output"]["tasks"]) == 5
    assert created["output"]["removed_by_gc"]

    listed = runtime.tools.run("定时任务", {}, source="test")
    assert listed["ok"] is True
    ids = [row["id"] for row in listed["output"]["tasks"]]
    assert len(ids) == 5

    cancelled = runtime.tools.run("schedule_task", {"operation": "cancel", "ids": ids[:2]}, source="test")
    assert cancelled["ok"] is True
    assert len(cancelled["output"]["cancelled_tasks"]) == 2

    active = runtime.scheduled_tasks_public(include_inactive=False)
    assert active["active_count"] == 3


def test_schedule_task_claim_due_once_and_interval(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    now_ms = 1_800_000_000_000
    once = runtime.schedule_task(
        {
            "operation": "create",
            "summary": "一次提醒",
            "prompt": "该履约了",
            "trigger": {"type": "once", "at": now_ms - 1000},
        },
        source="test",
    )
    interval = runtime.schedule_task(
        {
            "operation": "create",
            "summary": "循环提醒",
            "prompt": "检查状态",
            "trigger": {"type": "interval", "interval_seconds": 10},
        },
        source="test",
    )
    interval_id = interval["created_tasks"][0]["id"]
    with runtime._scheduled_tasks_lock:
        payload = runtime._load_scheduled_tasks_payload()
        rows = payload["tasks"]
        for row in rows:
            if row["id"] == interval_id:
                row["next_fire_at_ms"] = now_ms - 500
        runtime._save_scheduled_tasks(rows)

    claimed = runtime.claim_due_scheduled_tasks(now_ms=now_ms, limit=10)
    assert claimed["count"] == 2
    prompts = {row["prompt"] for row in claimed["tasks"]}
    assert {"该履约了", "检查状态"} <= prompts

    all_tasks = runtime.scheduled_tasks_public(include_inactive=True, detail=True)
    once_rows = [row for row in all_tasks["tasks"] if row["summary"] == "一次提醒"]
    interval_rows = [row for row in all_tasks["tasks"] if row["summary"] == "循环提醒"]
    assert once_rows[0]["status"] == "completed"
    assert interval_rows[0]["status"] == "active"
    assert interval_rows[0]["next_fire_at_ms"] > now_ms


def test_schedule_task_keeps_qq_origin_from_tool_context(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    origin = {
        "source": "napcat_qq",
        "conversation_id": "private:1000010001",
        "adapter_label": "私聊 测试用户 (1000010001)",
        "reply_target": {
            "adapter": "napcat_qq",
            "message_type": "private",
            "conversation_id": "private:1000010001",
            "user_id": "1000010001",
            "target_label": "私聊 测试用户 (1000010001)",
        },
        "adapter_event": {
            "adapter": "napcat_qq",
            "message_type": "private",
            "conversation_id": "private:1000010001",
            "user_id": "1000010001",
            "target_label": "私聊 测试用户 (1000010001)",
        },
    }

    result = runtime._execute_tool_calls(
        [
            {
                "name": "schedule_task",
                "args": {
                    "operation": "create",
                    "summary": "提醒测试用户睡觉",
                    "prompt": "提醒测试用户该睡觉了",
                    "trigger": {"type": "once", "at": "2099-01-01 00:00"},
                },
            }
        ],
        turn_id="turn_qq",
        thought_index=1,
        context=origin,
    )

    assert result[0]["ok"] is True
    task = result[0]["output"]["created_tasks"][0]
    assert task["origin"]["source"] == "napcat_qq"
    assert task["origin"]["conversation_id"] == "private:1000010001"
    assert task["origin"]["reply_target"]["user_id"] == "1000010001"
