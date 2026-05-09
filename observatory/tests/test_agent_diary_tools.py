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
    monkeypatch.setattr("observatory.agent_runtime._events_path", lambda: tmp_path / "agent_events.jsonl")
    runtime = AgentRuntime(_DiaryFakeApp())
    runtime.config = AgentConfig(
        diary_enabled=True,
        diary_entry_limit=10,
        diary_gc_oldest_count=5,
        diary_entry_max_chars=4000,
        diary_read_total_max_chars=12000,
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
