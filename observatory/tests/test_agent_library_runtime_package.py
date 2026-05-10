# -*- coding: utf-8 -*-

import zipfile
from pathlib import Path

from observatory import agent_runtime as ar
from observatory.agent_runtime import AgentConfig, AgentRuntime


class _LibraryFakeApp:
    def __init__(self):
        self._config = {}
        self._config_override = {}
        self.reports = []

    def run_cycle(self, text=None, labels=None):
        tick = len(self.reports) + 1
        report = {
            "tick_counter": tick,
            "tick_id": f"tick_{tick}",
            "tick_labels": labels or {},
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


def _patch_runtime_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ar, "_state_path", lambda: tmp_path / "agent_state.json")
    monkeypatch.setattr(ar, "_diary_path", lambda: tmp_path / "agent_diary.json")
    monkeypatch.setattr(ar, "_scheduled_tasks_path", lambda: tmp_path / "agent_scheduled_tasks.json")
    monkeypatch.setattr(ar, "_stickers_catalog_path", lambda: tmp_path / "agent_stickers.json")
    monkeypatch.setattr(ar, "_events_path", lambda: tmp_path / "agent_events.jsonl")
    monkeypatch.setattr(ar, "_system_log_path", lambda: tmp_path / "agent_system_events.jsonl")
    monkeypatch.setattr(ar, "_library_dir", lambda: tmp_path / "library")
    monkeypatch.setattr(ar, "_library_files_dir", lambda: tmp_path / "library" / "files")
    monkeypatch.setattr(ar, "_library_books_dir", lambda: tmp_path / "library" / "books")
    monkeypatch.setattr(ar, "_library_assets_dir", lambda: tmp_path / "library" / "assets")
    monkeypatch.setattr(ar, "_library_catalog_path", lambda: tmp_path / "library" / "agent_library.json")
    monkeypatch.setattr(ar, "_runtime_packages_dir", lambda: tmp_path / "runtime_packages")


def _runtime(tmp_path: Path, monkeypatch) -> AgentRuntime:
    _patch_runtime_paths(tmp_path, monkeypatch)
    runtime = AgentRuntime(_LibraryFakeApp())
    runtime.config = AgentConfig(
        library_enabled=True,
        library_chunk_target_chars=24,
        library_after_chunk_ticks=2,
        library_review_tick_interval=10,
        library_book_limit=20,
        api_key="sk-secret",
        base_url="https://secret.example/v1",
        qq_napcat_http_url="http://127.0.0.1:3000",
    )
    runtime.record_event = lambda payload: None
    return runtime


def test_runtime_payload_merge_strategies():
    old = {"db": {"you": {"好": 1.0, "也": 1.0}}, "updated_at_ms": 10}
    new = {"db": {"you": {"好": 0.7, "很": 1.2}}, "updated_at_ms": 5}

    stacked = ar._merge_runtime_payload(old, new, strategy="stack")
    assert stacked["db"]["you"]["好"] == 1.7
    assert stacked["db"]["you"]["也"] == 1.0
    assert stacked["db"]["you"]["很"] == 1.2
    assert stacked["updated_at_ms"] == 10

    averaged = ar._merge_runtime_payload(old, new, strategy="stack_average")
    assert averaged["db"]["you"]["好"] == 0.85

    overwritten = ar._merge_runtime_payload(old, new, strategy="overwrite")
    assert overwritten == new

    competitive = ar._merge_runtime_payload(old, new, strategy="competitive")
    assert competitive["db"]["you"]["好"] == 1.0
    assert competitive["db"]["you"]["很"] == 1.2

    retreated = ar._merge_runtime_payload(old, new, strategy="retreat")
    assert retreated == old


def test_library_import_browse_read_and_recent_context(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    result = runtime.import_book({"title": "测试小书", "text": "第一句。第二句很重要。第三句用来继续阅读。"}, source="test")
    assert result["ok"] is True
    book_id = result["book"]["id"]

    listed = runtime.browse_library({})
    assert listed["total"] == 1
    assert listed["books"][0]["id"] == book_id

    read = runtime.read_book({"book_id": book_id, "chars": 12, "ticks": 1}, source="test")
    assert read["ok"] is True
    assert read["chunk"]["text"]
    assert read["review"]["id"]
    assert read["book"]["cursor"] > 0

    context = runtime._recent_tool_top_context_text()
    assert "测试小书" in context
    assert book_id in context


def test_library_read_batches_multiple_chunks_before_review(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    runtime.config.library_chunk_target_chars = 10
    runtime.config.library_after_chunk_ticks = 2
    runtime.config.library_review_tick_interval = 10
    imported = runtime.import_book(
        {
            "title": "批次阅读测试",
            "text": "第一句用于开头。第二句继续推进。第三句补充信息。第四句继续保留线索。第五句留给下一轮。",
        },
        source="test",
    )
    book_id = imported["book"]["id"]

    read = runtime.read_book({"book_id": book_id}, source="test")

    assert read["ok"] is True
    assert read["review_tick_target"] == 10
    assert read["chunk"]["chunk_count"] >= 4
    assert read["chunk"]["range"]["end"] > 20
    assert read["review"]["id"]
    assert read["book"]["review_count"] == 1
    assert read["ap_tick_count"] >= 5


def test_library_read_uses_llm_review_text(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)

    def fake_generate_text(messages, **kwargs):
        assert kwargs.get("purpose") == "library_review"
        return "这一段先把人物的注意力落在第一句上，AP 的消化更像是在确认文本开端和继续阅读的方向。", {"ok": True, "mode": "test"}

    runtime.gateway.generate_text = fake_generate_text
    imported = runtime.import_book({"title": "LLM 段落理解测试", "text": "第一句。第二句继续铺开。"}, source="test")
    book_id = imported["book"]["id"]

    read = runtime.read_book({"book_id": book_id, "chars": 12, "ticks": 0}, source="test")

    assert read["ok"] is True
    assert read["review"]["llm_generated"] is True
    assert "AP 的消化" in read["review"]["summary"]
    assert "AP 消化线索" not in read["review"]["summary"]


def test_library_review_prompt_includes_persona_and_recent_context(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    runtime.config.persona_name = "测试小澪"
    runtime.config.persona_text = "说话偏轻松，会把阅读理解写得像自己认真读过后的笔记。"
    runtime.write_diary({"title": "阅读偏好", "content": "用户喜欢有个人视角的段落理解。", "importance": 80}, source="test")
    runtime.schedule_task(
        {
            "operation": "create",
            "summary": "提醒继续读书",
            "prompt": "提醒自己继续读这本书。",
            "trigger": {"type": "interval", "interval_seconds": 3600},
        },
        source="test",
    )
    runtime.state["messages"].append(
        {
            "role": "user",
            "text": "这本书我想看你自己的感受，别写成报告。",
            "created_at_ms": 1000,
            "conversation_id": "private:1000010001",
            "adapter_label": "私聊 测试用户",
        }
    )
    runtime.state["thoughts"].append(
        {
            "text": "我得把这段读得像自己的笔记，不要太模板。",
            "decision": "tool_call",
            "tool_calls": [{"name": "read_book", "args": {}}],
            "tool_results": [],
            "created_at_ms": 2000,
        }
    )
    captured = {}

    def fake_generate_text(messages, **kwargs):
        captured["messages"] = messages
        assert kwargs.get("purpose") == "library_review"
        return "我读这段时会先抓住它的情绪方向，再把细节慢慢接起来。", {"ok": True, "mode": "test"}

    runtime.gateway.generate_text = fake_generate_text
    imported = runtime.import_book({"title": "上下文段落理解测试", "text": "第一句有一点情绪。第二句把关系继续展开。第三句留下疑问。"}, source="test")
    read = runtime.read_book({"book_id": imported["book"]["id"], "chars": 12, "ticks": 0}, source="test")

    assert read["ok"] is True
    prompt_text = "\n\n".join(str(item.get("content") or "") for item in captured["messages"])
    assert "当前人设名称" in prompt_text
    assert "测试小澪" in prompt_text
    assert "近期对话" in prompt_text
    assert "别写成报告" in prompt_text
    assert "近期 thought / 决策 / 工具结果" in prompt_text
    assert "像自己的笔记" in prompt_text
    assert "最近将触发的定时任务" in prompt_text
    assert "提醒继续读书" in prompt_text
    assert "最近日记标题" in prompt_text
    assert "阅读偏好" in prompt_text
    assert "干巴巴的中立报告腔" in prompt_text


def test_library_summary_prefers_file_path_over_stale_text(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    source = tmp_path / "真正的书.txt"
    source.write_text("晋中风物第一章。这里写的是山西小城、汾河边的风和夜里的灯。", encoding="utf-8")
    captured = {}

    def fake_generate_text(messages, **kwargs):
        captured["prompt"] = "\n\n".join(str(item.get("content") or "") for item in messages)
        return (
            '{"summary":"这本书从晋中风物写起，描摹山西小城、汾河边的风和夜里的灯。",'
            '"evidence":["晋中风物","山西小城","汾河边的风"]}',
            {"ok": True, "mode": "test"},
        )

    runtime.gateway.generate_text = fake_generate_text
    result = runtime.suggest_library_summary(
        {
            "path": str(source),
            "title": "真正的书",
            "text": "本书围绕当前 AI 的技术理想展开，探讨人设配置、模型交互与想法云。",
        }
    )

    assert result["ok"] is True
    assert "晋中风物" in result["summary"]
    assert "想法云" not in result["summary"]
    assert "晋中风物" in captured["prompt"]
    assert "想法云" not in captured["prompt"]
    assert result["fallback_used"] is False
    assert any("忽略直接文本框" in item for item in result["warnings"])


def test_library_summary_rejects_ungrounded_project_hallucination(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)

    def fake_generate_text(messages, **kwargs):
        return (
            '{"summary":"本书围绕当前 AI 的技术理想展开，探讨人设配置、模型交互与想法云之间的关系。",'
            '"evidence":["想法云","模型交互"]}',
            {"ok": True, "mode": "test"},
        )

    runtime.gateway.generate_text = fake_generate_text
    result = runtime.suggest_library_summary(
        {
            "title": "山城夜雨",
            "text": "山城夜雨第一章。少女在旧车站等一封迟来的信，雨水把路灯照得很软。",
        }
    )

    assert result["ok"] is True
    assert result["fallback_used"] is True
    assert "山城夜雨第一章" in result["summary"]
    assert "想法云" not in result["summary"]
    assert result["reject_reason"]
    assert any("来源校验" in item for item in result["warnings"])


def test_library_file_picker_falls_back_and_sets_title(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    selected = tmp_path / "用户选择的书.docx"
    selected.write_text("placeholder", encoding="utf-8")

    def fail_powershell():
        raise RuntimeError("dialog unavailable")

    monkeypatch.setattr(runtime, "_pick_library_file_with_powershell", fail_powershell)
    monkeypatch.setattr(runtime, "_pick_library_file_with_tkinter", lambda: str(selected))

    result = runtime.pick_library_file()

    assert result["ok"] is True
    assert result["path"] == str(selected)
    assert result["title"] == "用户选择的书"
    assert any("PowerShell 文件选择框失败" in item for item in result["warnings"])


def test_runtime_package_export_redacts_config_and_safe_import(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    runtime.write_diary({"title": "用户信息", "content": "银子是晋中人", "importance": 90}, source="test")
    exported = runtime.export_runtime_package({"name": "share", "include_hdb": False})
    path = Path(exported["package"]["path"])
    assert path.exists()

    with zipfile.ZipFile(path, "r") as zf:
        names = set(zf.namelist())
        assert "agent/config.redacted.json" in names
        config_text = zf.read("agent/config.redacted.json").decode("utf-8")
        assert "sk-secret" not in config_text
        assert "secret.example" not in config_text
        assert "127.0.0.1:3000" not in config_text
        assert not any(name.endswith(".jsonl") for name in names)

    imported = runtime.import_runtime_package({"path": str(path), "strategy": "retreat", "include_hdb": False})
    assert imported["ok"] is True
    assert imported["backup"]
    assert imported["extracted_count"] > 0


def test_runtime_package_import_rejects_zip_slip(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    bad_zip = tmp_path / "runtime_packages" / "bad.zip"
    bad_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("manifest.json", '{"kind":"psyarch_agent_runtime_package"}')
        zf.writestr("../escape.txt", "nope")

    result = runtime.import_runtime_package({"path": str(bad_zip), "include_hdb": False})
    assert result["ok"] is False
    assert result["error"] == "unsafe_or_invalid_zip"
    assert "unsafe zip path" in result["summary"]
